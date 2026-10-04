"""검사 실행 순서, 단락 규칙, 판정(severity → verdict), 점수.

순서는 L0 → L1 → L2 → L3A → L3B → (L4, L5) → L6이다.
- file 범위 이슈는 그 파일의 모든 레코드에 붙는다. file 범위 검사가 record_id를 단 이슈는 그 레코드에만 붙는다.
- L1에서 타입이 깨진 필드(target.broken)는 L2·L3에서 건너뛴다.
- critical이 있는 레코드에는 L3B를 돌리지 않는다.
- batch 범위(L6)는 판정 뒤에 돌고 판정을 바꾸지 않는다. record_id를 단 batch 이슈(L5 확장)만 그 레코드의 판정을 다시 계산한다.
"""
import concurrent.futures

from qabot import codes, model, registry

RECORD_LAYERS = ("L1", "L2", "L3A", "L3B", "L4", "L5")


class FileTarget(object):
    def __init__(self, bundle, file_id):
        self.bundle = bundle
        self.file_id = file_id
        self.source = bundle.sources[file_id]
        self.units = bundle.units_of(file_id)
        self.records = bundle.records_of(file_id)


class RecordTarget(object):
    """record는 L1 정규화 뒤의 작업본이다. original은 adapter가 준 그대로다."""

    def __init__(self, record, unit):
        self.original = record
        self.record = record
        self.unit = unit
        self.issues = []
        self.broken = set()
        self.auto_fixes = []
        self.judge = None

    @property
    def record_id(self):
        return self.original["record_id"]

    @property
    def file_id(self):
        return self.original.get("file_id")

    def has_critical(self):
        return any(i["severity"] == "critical" for i in self.issues)


class BatchTarget(object):
    def __init__(self, bundle, targets, verdicts, file_issues):
        self.bundle = bundle
        self.targets = targets
        self.verdicts = verdicts
        self.file_issues = file_issues


class Ctx(object):
    """검사가 보는 맥락: taxonomy 색인, 스키마, 정책, unit 색인, judge, 실행 메타."""

    def __init__(self, bundle, policy, schema, judge=None, qa_run_id=None, versions=None, log=None, paths=None,
                 judge_skip_reason=None):
        from qabot import io

        self.bundle = bundle
        self.policy = policy
        self.schema = schema
        self.tax = model.TaxIndex(bundle.taxonomy)
        self.units = bundle.units
        self.units_by_file = {}
        for u in bundle.units.values():
            self.units_by_file.setdefault(u["file_id"], []).append(u)
        for lst in self.units_by_file.values():
            lst.sort(key=lambda u: (u["seq"], u["unit_id"]))
        self.judge = judge
        self.judge_skip_reason = judge_skip_reason
        self.qa_run_id = qa_run_id
        self.versions = versions or {}
        self.log = log or io.null_log
        self.paths = paths
        self.batch = {}  # L6 지표 등 batch 검사 산출

    def layer_on(self, layer):
        return layer in self.policy["layers"]


def apply_override(issue, policy):
    sev = policy["severity_overrides"].get(issue["code"])
    if sev:
        issue["severity"] = sev
    if codes.is_fail_safe(issue["code"]) and model.SEVERITY_RANK[issue["severity"]] < model.SEVERITY_RANK["major"]:
        issue["severity"] = "major"
    return issue


def _attach(target, issue, policy):
    issue = dict(issue)
    issue.pop("record_id", None)
    target.issues.append(apply_override(issue, policy))


def _layer_order(layers):
    return [l for l in model.LAYERS if l in layers]


def run(bundle, ctx):
    """반환: {"verdicts": [...], "file_issues": [...], "batch_issues": [...], "targets": {...}}"""
    model.check_bundle(bundle)
    policy = ctx.policy
    layers = _layer_order(policy["layers"])
    targets = {}
    for r in sorted(bundle.records, key=lambda r: r["record_id"]):
        targets[r["record_id"]] = RecordTarget(r, bundle.units.get(r["record_id"]))
    by_file = {}
    for t in targets.values():
        by_file.setdefault(t.file_id, []).append(t)

    file_issues = []
    for layer in layers:
        for check in registry.checks(layer, "file"):
            for fid in sorted(bundle.sources):
                for iss in check.run(FileTarget(bundle, fid), ctx) or []:
                    rid = iss.get("record_id")
                    if iss["scope"] == "record" and rid is not None:
                        if rid in targets:
                            _attach(targets[rid], iss, policy)
                        continue
                    iss = apply_override(dict(iss), policy)
                    iss.pop("record_id", None)
                    file_issues.append(dict(iss, file_id=fid))
                    for t in by_file.get(fid, []):
                        _attach(t, iss, policy)

    for layer in layers:
        if layer not in RECORD_LAYERS:
            continue
        for check in registry.checks(layer, "record"):
            todo = list(targets.values())
            if layer == "L3B":
                todo = [t for t in todo if not t.has_critical()]
            if check.parallel and len(todo) > 1:
                workers = int(policy["judge"].get("workers") or 1)
                with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
                    results = list(ex.map(lambda t: check.run(t, ctx) or [], todo))
            else:
                results = [check.run(t, ctx) or [] for t in todo]
            for t, issues in zip(todo, results):
                for iss in issues:
                    _attach(t, iss, policy)

    verdicts = {rid: make_verdict(t, ctx) for rid, t in targets.items()}

    batch_issues = []
    if "L6" in layers or "L5" in layers:
        bt = BatchTarget(bundle, targets, verdicts, file_issues)
        touched = set()
        for layer in layers:
            for check in registry.checks(layer, "batch"):
                for iss in check.run(bt, ctx) or []:
                    rid = iss.get("record_id")
                    if rid is not None and rid in targets:
                        _attach(targets[rid], iss, policy)
                        touched.add(rid)
                    else:
                        batch_issues.append(apply_override(dict(iss), policy))
        for rid in touched:
            verdicts[rid] = make_verdict(targets[rid], ctx)

    return {
        "verdicts": [verdicts[rid] for rid in sorted(verdicts)],
        "file_issues": sorted(file_issues, key=lambda i: (i["file_id"], model.issue_sort_key(i))),
        "batch_issues": batch_issues,
        "targets": targets,
    }


def batch_only(bundle, ctx, verdicts):
    """저장된 판정으로 batch 검사(L6)만 다시 돈다. L1 정규화는 결정론이라 다시 계산한다. LLM을 부르지 않는다."""
    vmap = {v["record_id"]: v for v in verdicts}
    targets = {}
    for r in sorted(bundle.records, key=lambda r: r["record_id"]):
        if r["record_id"] not in vmap:
            continue
        t = RecordTarget(r, bundle.units.get(r["record_id"]))
        if ctx.layer_on("L1"):
            for check in registry.checks("L1", "record"):
                check.run(t, ctx)
        t.issues = list(vmap[r["record_id"]]["issues"])
        t.judge = vmap[r["record_id"]].get("judge")
        targets[r["record_id"]] = t
    batch_issues = []
    bt = BatchTarget(bundle, targets, {k: vmap[k] for k in targets}, [])
    for layer in _layer_order(ctx.policy["layers"]):
        for check in registry.checks(layer, "batch"):
            for iss in check.run(bt, ctx) or []:
                if iss.get("record_id") is None:
                    batch_issues.append(apply_override(dict(iss), ctx.policy))
    return {"targets": targets, "batch_issues": batch_issues}


def make_verdict(t, ctx):
    issues = sorted(t.issues, key=model.issue_sort_key)
    verdict, score = model.decide(issues, ctx.policy)
    rec = t.original
    versions = dict(ctx.versions)
    versions["labeler_prompt"] = dict((rec.get("labeler") or {}).get("prompt_versions") or {})
    unit = t.unit or {}
    return {
        "record_id": t.record_id,
        "file_id": t.file_id,
        "qa_run_id": ctx.qa_run_id,
        "labeler_run_id": rec.get("labeler_run_id"),
        "verdict": verdict,
        "score": score,
        "issues": issues,
        "auto_fixes": list(t.auto_fixes),
        "judge": t.judge,
        "versions": versions,
        "input_hash": model.hash_obj([unit.get("text_hash"), model.label_hash(rec)]),
        "text_hash": unit.get("text_hash"),
        "human_reviewed": bool(rec.get("human_reviewed")),
    }
