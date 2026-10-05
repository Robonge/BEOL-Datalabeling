"""실행 흐름: 번들 읽기 → 검사·판정 → verdicts·manifest → 대기열 → 규칙 제안 → 리포트 → 검토 화면.

산출 파일의 두 부류(4.6절):
- 본문 없음: manifest.json, report.*, history.jsonl, engrbot.log, 콘솔. 파일명·경로·본문을 넣지 않는다.
- 작업 폴더 전용: verdicts.jsonl 등. 발췌는 output.include_text가 true일 때만 넣는다.
"""
import hashlib
import os
import sqlite3
import time

import engrbot
from engrbot import codes, engine, io, model
from engrbot import policy as policy_mod

JUDGE_PROMPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts", "qa_judge.md")


class RunError(Exception):
    def __init__(self, reason_code, detail=None):
        Exception.__init__(self, reason_code if not detail else "%s: %s" % (reason_code, detail))
        self.reason_code = reason_code
        self.detail = detail


class RunResult(object):
    """하류 모듈(queue, proposals, report, screen, feedback)이 받는 실행 결과."""

    def __init__(self, **kw):
        self.qa_run_id = kw.get("qa_run_id")
        self.labeler_run_id = kw.get("labeler_run_id")
        self.paths = kw.get("paths")
        self.run_dir = kw.get("run_dir")
        self.policy = kw.get("policy")
        self.schema = kw.get("schema")
        self.bundle = kw.get("bundle")
        self.ctx = kw.get("ctx")
        self.verdicts = kw.get("verdicts") or []
        self.file_issues = kw.get("file_issues") or []
        self.batch_issues = kw.get("batch_issues") or []
        self.metrics = kw.get("metrics") or {}
        self.manifest = kw.get("manifest") or {}
        self.targets = kw.get("targets") or {}
        self.proposals = kw.get("proposals") or []
        self.queue = kw.get("queue") or []
        self.rework = kw.get("rework") or []
        self.log = kw.get("log") or io.null_log

    def path(self, *parts):
        return os.path.join(self.run_dir, *parts)

    def verdict_map(self):
        return {v["record_id"]: v for v in self.verdicts}


def judge_prompt_hash():
    with open(JUDGE_PROMPT_PATH, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def versions(bundle, pol, sch, judge_model):
    return {
        "taxonomy": (bundle.taxonomy or {}).get("version"),
        "schema": policy_mod.schema_version(sch),
        "reviewer": "%s+%s+%s+%s" % (engrbot.__version__, codes.catalog_hash()[:8], judge_prompt_hash()[:8],
                                     judge_model or "none"),
        "policy": policy_mod.policy_version(pol),
    }


def labeler_prompts(bundle):
    """레코드들이 쓴 라벨러 프롬프트 버전(단계별 고유 값 목록)."""
    out = {}
    for r in bundle.records:
        for stage, h in ((r.get("labeler") or {}).get("prompt_versions") or {}).items():
            out.setdefault(stage, set()).add(h)
    return {k: sorted(v) for k, v in sorted(out.items())}


def load_bundle(paths, labeler_run_id=None, bundle_dir=None):
    if bundle_dir:
        from engrbot.adapters import bundle_files

        return bundle_files.load(bundle_dir)
    from engrbot.adapters import labelbot_ws

    return labelbot_ws.load(paths.root, labeler_run_id)


CHECKED_LAYERS = ("L0", "L1", "L2", "L3A", "L4", "L5")


def require_judge_layer(layers):
    """레코드를 검사하는 층이 하나라도 있는데 L3B가 빠졌으면 L3B를 붙인다(judge 없이 SKIPPED가 붙는다).
    judge를 거치지 않은 레코드는 PASS가 되지 않는다(5.5절). 반환: (층 목록, 강제로 붙였는지)."""
    layers = list(layers)
    if "L3B" not in layers and any(l in layers for l in CHECKED_LAYERS):
        return layers + ["L3B"], True
    return layers, False


def make_judge(pol, bundle, paths, no_judge=False, llm=None, log=None, skip_reason=None):
    """반환: (judge 또는 None, 건너뛴 사유 코드 또는 None)."""
    if "L3B" not in pol["layers"]:
        return None, "L3B_OFF"
    if skip_reason:
        return None, skip_reason
    if no_judge:
        return None, "NO_JUDGE"
    if not pol["judge"]["enabled"]:
        return None, "JUDGE_DISABLED"
    from engrbot import judge as judge_mod

    try:
        j = judge_mod.create(pol, llm_cfg=(bundle.meta or {}).get("llm_cfg"),
                             cache_path=paths.judge_cache if paths else None, log=log, llm=llm)
    except judge_mod.JudgeUnavailable as e:
        return None, e.reason_code
    lcfg = pol.get("ledger") or {}
    jex = lcfg.get("judge_examples") or {}
    if paths and lcfg.get("enabled") and jex.get("enabled") and hasattr(j, "set_examples"):
        # 교정 장부의 사람 판정 예시를 judge 프롬프트에 넣는다. 장부가 없거나 깨졌으면 예시 없이 돈다
        rows, code = _ledger_call(lambda ledger: ledger.read_examples(ledger.ledger_dir(paths.root, pol)))
        if code:
            (log or io.null_log)("ledger", "-", code)
        j.set_examples(rows or [], k_per_item=jex.get("k_per_item", 2), max_per_call=jex.get("max_per_call", 6))
    return j, None


def _counts(verdicts):
    out = {"records": len(verdicts), "PASS": 0, "AUTO_FIX": 0, "REVIEW": 0, "REJECT": 0,
           "files": len({v["file_id"] for v in verdicts})}
    for v in verdicts:
        out[v["verdict"]] += 1
    return out


def execute(bundle, pol, sch, paths=None, qa_run_id=None, no_judge=False, llm=None, log=None, layers=None,
            enforce_judge=False):
    """검사와 판정만 한다(파일을 쓰지 않는다). 하네스와 테스트가 직접 부른다.

    enforce_judge=True(`run` 명령)이면 L3B가 빠진 층 구성에도 L3_JUDGE_SKIPPED를 붙여 PASS를 막는다.
    하네스와 층별 테스트는 결정론 층만 재려고 False로 부른다."""
    if layers is not None:
        bad = [l for l in layers if l not in model.LAYERS]
        if bad:
            raise RunError("LAYER_UNKNOWN", ",".join(bad))
        pol = dict(pol, layers=list(layers))
    skip_reason = None
    if enforce_judge:
        eff, forced = require_judge_layer(pol["layers"])
        if forced:
            pol = dict(pol, layers=eff)
            skip_reason = "L3B_OFF"
    judge, skip = make_judge(pol, bundle, paths, no_judge=no_judge, llm=llm, log=log, skip_reason=skip_reason)
    vers = versions(bundle, pol, sch, getattr(judge, "name", None))
    ctx = engine.Ctx(bundle, pol, sch, judge=judge, qa_run_id=qa_run_id, versions=vers, log=log, paths=paths,
                     judge_skip_reason=skip)
    ctx.ledger_dir, ctx.ledger_error = _ledger_dir(paths, pol)
    out = engine.run(bundle, ctx)
    return RunResult(qa_run_id=qa_run_id, labeler_run_id=bundle.labeler_run_id, paths=paths, policy=pol, schema=sch,
                     bundle=bundle, ctx=ctx, verdicts=out["verdicts"], file_issues=out["file_issues"],
                     batch_issues=out["batch_issues"], metrics=ctx.batch, targets=out["targets"], log=log)


def new_run_id(paths):
    """기존 실행 ID보다 뒤에 정렬되는 ID. 같은 초에 두 번 돌려도 '직전 실행'이 뒤바뀌지 않게 한다."""
    existing = paths.list_runs()
    rid = model.new_qa_run_id()
    while existing and rid <= existing[-1]:
        time.sleep(0.01)
        rid = model.new_qa_run_id()
    return rid


def _judge_stats(judge):
    if judge is None:
        return {"calls": 0, "cache_hits": 0, "failed": 0, "sent_params": {}, "examples": {}}
    return {"calls": judge.calls, "cache_hits": judge.cache_hits, "failed": judge.failed,
            "sent_params": judge.sent_params(), "examples": dict(getattr(judge, "example_stats", {}) or {})}


LEDGER_IO_ERRORS = (OSError, ValueError, KeyError, TypeError, sqlite3.Error)


def _ledger_call(fn):
    """장부 호출을 감싼다. 실패해도 실행을 멈추지 않는다. 반환: (결과 또는 None, 사유 코드 또는 None)."""
    from engrbot import ledger

    try:
        return fn(ledger), None
    except ledger.LedgerError as e:
        return None, e.reason_code
    except model.BundleError as e:
        return None, e.reason_code
    except LEDGER_IO_ERRORS:
        return None, "LEDGER_IO_FAILED"


def _ledger_dir(paths, pol):
    """L4 후보·judge 예시를 읽을 장부 위치. 반환: (위치 또는 None, 사유 코드 또는 None).
    작업 폴더가 없거나 장부를 끄면 (None, None). 허용 위치 밖이면 (None, 코드)."""
    if paths is None or not (pol.get("ledger") or {}).get("enabled"):
        return None, None
    return _ledger_call(lambda ledger: ledger.ledger_dir(paths.root, pol))


def auto_intake(paths, pol, log, schema=None):
    """run 시작 때 그 작업 폴더를 장부에 반영한다. 실패해도 run을 멈추지 않는다. 반환: (intake 결과 또는 None, 사유 코드 또는 None)."""
    out, code = _ledger_call(lambda ledger: ledger.intake(paths.root, pol, schema=schema))
    log("ledger", "-", code or (out or {}).get("reason") or "INTAKE_OK")
    return out, code


def _candidates_loaded(pol, d):
    """L4가 이번 실행에 실제로 더한 후보 규칙 수(L4가 꺼져 있으면 0)."""
    if "L4" not in pol["layers"]:
        return 0
    from engrbot.checks import l4_domain

    try:
        return len(l4_domain.rules_for(pol, d)) - len(l4_domain.rules_for(pol, None))
    except policy_mod.PolicyError:
        return 0


def _ledger_manifest(result, intake_out, intake_error):
    """manifest["ledger"]: 건수, 버전, 표시 이름만 넣는다(경로 전체를 쓰지 않는다)."""
    d = result.ctx.ledger_dir
    out = {"dir": None, "intake": None, "intake_error": intake_error or getattr(result.ctx, "ledger_error", None),
           "examples_loaded": 0, "examples_sha": None, "candidates_loaded": 0, "candidates_version": None,
           "golden_total": 0}
    if d is None:
        return out
    from engrbot import ledger

    pol = result.policy
    st, _ = _ledger_call(lambda lg: lg.status(d))
    cand, _ = _ledger_call(lambda lg: lg.read_candidates(d))
    judge = result.ctx.judge
    jex = (pol.get("ledger") or {}).get("judge_examples") or {}
    ids = []
    if judge is not None and jex.get("enabled") and hasattr(judge, "set_examples"):
        rows, _ = _ledger_call(lambda lg: lg.read_examples(d))
        ids = sorted(e["example_id"] for e in rows or [])
    stats = getattr(judge, "example_stats", None) or {}
    out.update({"dir": ledger.dir_label(d), "intake": ledger.counts_only(intake_out),
                "examples_loaded": int(stats.get("loaded", len(ids)) or 0),
                "examples_sha": model.hash_obj(ids)[:12] if ids else None,
                "candidates_loaded": _candidates_loaded(pol, d),
                "candidates_version": (cand or {}).get("version"), "golden_total": (st or {}).get("golden", 0)})
    return out


def write_verdicts(run):
    rows = run.verdicts
    if not run.policy["output"]["include_text"]:
        rows = [io.strip_text(v) for v in rows]
    io.write_jsonl(run.path("verdicts.jsonl"), rows)


def run(paths, labeler_run_id=None, bundle_dir=None, layers=None, no_judge=False, llm=None, pass_sample=0,
        policy_path=None, schema_path=None):
    """`run` 명령. 반환: RunResult."""
    from engrbot import proposals, queue, report, screen

    pol, sch = policy_mod.load(paths, policy_path, schema_path)
    log = io.Logger(paths.log_path)
    lcfg = pol.get("ledger") or {}
    intake_out = intake_error = None
    if lcfg.get("enabled"):
        _, intake_error = _ledger_dir(paths, pol)
        if intake_error:
            log("ledger", "-", intake_error)
        elif bundle_dir is None and lcfg.get("auto_intake"):
            intake_out, intake_error = auto_intake(paths, pol, log, schema=sch)
    bundle = load_bundle(paths, labeler_run_id, bundle_dir)
    qa_run_id = new_run_id(paths)
    started = model.now_iso()
    log("run", qa_run_id, "START")
    result = execute(bundle, pol, sch, paths=paths, qa_run_id=qa_run_id, no_judge=no_judge, llm=llm, log=log,
                     layers=layers, enforce_judge=True)
    result.run_dir = paths.run_dir(qa_run_id, create=True)
    # 이 실행이 쓴 정책·스키마(층 구성 포함). report·review 등을 다시 만들 때 이것을 쓴다
    io.write_json(result.path("policy_used.json"), result.policy)
    io.write_json(result.path("schema_used.json"), sch)
    write_verdicts(result)
    io.write_jsonl(result.path("file_issues.jsonl"), [io.strip_text(i) for i in result.file_issues])
    for v in result.verdicts:
        if v["verdict"] == "REJECT":
            for code in sorted({i["code"] for i in v["issues"] if i["severity"] == "critical"}):
                log("verdict", v["record_id"], code)
    for fi in result.file_issues:
        log("file", fi["file_id"], fi["code"])
    result.manifest = {
        "qa_run_id": qa_run_id,
        "labeler_run_id": bundle.labeler_run_id,
        "adapter": (bundle.meta or {}).get("adapter", "labelbot_ws"),
        "versions": dict(result.ctx.versions, labeler_prompt=labeler_prompts(bundle)),
        "policy_sha256": model.hash_obj(result.policy),
        "schema_sha256": model.hash_obj(sch),
        "input_fingerprint": bundle.fingerprint(),
        "layers": list(result.policy["layers"]),
        "judge_ran": result.ctx.judge is not None,
        "judge_skip_reason": result.ctx.judge_skip_reason,
        "counts": _counts(result.verdicts),
        "judge": _judge_stats(result.ctx.judge),
        "started_at": started,
        "finished_at": None,
    }
    if lcfg.get("enabled"):
        result.manifest["ledger"] = _ledger_manifest(result, intake_out, intake_error)
    result.queue, result.rework = queue.write(result)
    result.proposals = proposals.write(result)
    report.write(result)
    screen.build(result, pass_sample=pass_sample)
    result.manifest["finished_at"] = model.now_iso()
    io.write_json(result.path("manifest.json"), result.manifest)
    log("run", qa_run_id, "DONE")
    return result


def reload(paths, qa_run_id, bundle_dir=None, recompute_batch=True):
    """저장된 실행을 다시 읽는다(report, review, golden, feedback). LLM을 부르지 않는다."""
    run_dir = paths.run_dir(qa_run_id)
    manifest = io.read_own_json(os.path.join(run_dir, "manifest.json"))
    if not manifest:
        raise RunError("QA_RUN_NOT_FOUND", qa_run_id)
    pol, sch = policy_mod.load(paths)
    used_pol = io.read_own_json(os.path.join(run_dir, "policy_used.json"))
    used_sch = io.read_own_json(os.path.join(run_dir, "schema_used.json"))
    if used_pol is not None:
        pol = policy_mod.validate_policy(used_pol)
    if used_sch is not None:
        sch = policy_mod.validate_schema(used_sch)
    bundle = load_bundle(paths, manifest.get("labeler_run_id"), bundle_dir)
    verdicts = io.read_own_jsonl(os.path.join(run_dir, "verdicts.jsonl"))
    ctx = engine.Ctx(bundle, pol, sch, qa_run_id=qa_run_id, versions=manifest.get("versions"),
                     log=io.Logger(paths.log_path), paths=paths)
    out = {"targets": {}, "batch_issues": []}
    if recompute_batch:
        out = engine.batch_only(bundle, ctx, verdicts)
    result = RunResult(qa_run_id=qa_run_id, labeler_run_id=manifest.get("labeler_run_id"), paths=paths,
                       run_dir=run_dir, policy=pol, schema=sch, bundle=bundle, ctx=ctx, verdicts=verdicts,
                       file_issues=[], batch_issues=out["batch_issues"], metrics=ctx.batch, manifest=manifest,
                       targets=out["targets"], log=ctx.log)
    result.file_issues = io.read_own_jsonl(os.path.join(run_dir, "file_issues.jsonl"))
    result.proposals = io.read_own_jsonl(os.path.join(run_dir, "proposals.jsonl"))
    result.queue = io.read_own_jsonl(os.path.join(run_dir, "review_queue.jsonl"))
    result.rework = io.read_own_jsonl(os.path.join(run_dir, "rework.jsonl"))
    return result
