"""L6 배치 통계와 배치 이슈(8.1·8.2절). 판정을 바꾸지 않고 ctx.batch에 지표를 채운다.

- R은 chunk 유형이 내용이고 라벨러가 성공한(L1_LABELER_FAILED 없는) 레코드다.
- 기준선(qa/baseline.json)과 추이(qa/history.jsonl)는 ctx.paths가 있을 때만 읽는다. 기준선은 사람이 `baseline set`으로만 올린다.
- 실행 폴더에 l6_inputs.json(report.write가 그 실행이 본 기준선·추이를 적어 둔다)이 있으면 그것을 쓴다.
  `report --qa-run`이 기준선을 바꾼 뒤에도 같은 리포트를 다시 만들게 하기 위해서다.
- 배치 이슈에는 코드, 축·질문 이름, 수치, taxonomy 값 이름만 넣는다. 용어 후보(본문 표현)는 넣지 않는다.
"""
import os

from qabot import io, model, stats
from qabot.registry import Check, register

INPUTS_FILE = "l6_inputs.json"
HISTORY_SHOWN = 6  # 리포트의 최근 추이 행 수(이번 실행 포함)
NO_BASELINE_NOTE = "기준선 없음. 이 실행을 기준선으로 올리려면 `baseline set`"
TAXONOMY_CHANGED_NOTE = "taxonomy 변경됨. 양쪽에 있는 값만으로 계산했고 경보는 주의로 낮췄다. 기준선을 다시 올린다(`baseline set`)."
JUDGE_KEYS = ("items", "supported", "partial", "unsupported", "failed")


def load_inputs(paths, qa_run_id, keep):
    """반환: {"baseline": dict 또는 None, "history": 이번 실행보다 앞선 추이 행(최근 keep개)}."""
    if paths is None:
        return {"baseline": None, "history": []}
    if qa_run_id:
        snap = io.read_own_json(os.path.join(paths.run_dir(qa_run_id), INPUTS_FILE))
        if snap is not None:
            return snap
    baseline = io.read_own_json(paths.baseline)
    hist = [h for h in io.read_own_jsonl(paths.history)
            if h.get("qa_run_id") != qa_run_id and (qa_run_id is None or str(h.get("qa_run_id") or "") < qa_run_id)]
    return {"baseline": baseline, "history": hist[-keep:] if keep > 0 else []}


def inputs_for(ctx):
    cached = getattr(ctx, "l6_inputs", None)
    if cached is None:
        keep = max(HISTORY_SHOWN - 1, int(ctx.policy["l6"]["unused_runs"]))
        cached = load_inputs(ctx.paths, ctx.qa_run_id, keep)
        ctx.l6_inputs = cached
    return cached


def content_targets(bt, ctx):
    ct = ctx.schema["content_chunk_type"]
    out = []
    for rid in sorted(bt.targets):
        t = bt.targets[rid]
        if (t.record or {}).get("chunk_type") != ct:
            continue
        if any(i["code"] == "L1_LABELER_FAILED" for i in t.issues):
            continue
        out.append(t)
    return out


def active_values(tax):
    return {a["name"]: [v for v in tax.values[a["name"]] if not tax.is_reserved(v)] for a in tax.active_axes()}


def _drift(metrics, baseline, tax, l6):
    """반환: (drift dict, [(field, n, baseline_n)] 표본 부족, [(field, jsd, n)] 경보)."""
    if not baseline:
        return ({"baseline_qa_run_id": None, "taxonomy_changed": False, "axes": {}, "answers": {},
                 "note": NO_BASELINE_NOTE}, [], [])
    changed = baseline.get("taxonomy_version") != tax.version
    reserved = {tax.na, tax.unknown}
    cur_vals = active_values(tax)
    base_vals = baseline.get("taxonomy_values") or {}
    small, alerts = [], []
    out = {"baseline_qa_run_id": baseline.get("qa_run_id"), "taxonomy_changed": changed, "axes": {}, "answers": {},
           "note": TAXONOMY_CHANGED_NOTE if changed else None}

    def one(kind, name, cur, base, support):
        keys = set(cur) | set(base) if support is None else set(support)
        n = sum(cur.get(k, 0) for k in keys)
        bn = sum(base.get(k, 0) for k in keys)
        field = "%s:%s" % (kind, name)
        if n < l6["min_n"] or bn < l6["min_n"]:
            small.append((field, n, bn))
            return {"jsd": None, "n": n, "level": stats.drift_level(None, 0, 0)}
        value = stats.jsd(cur, base, keys)
        level = stats.drift_level(value, l6["jsd_notice"], l6["jsd_alert"], cap_notice=changed)
        if level == "경보":
            alerts.append((field, stats.rnd(value), n))
        return {"jsd": stats.rnd(value), "n": n, "level": level}

    bdist = baseline.get("distribution") or {}
    for a in sorted(metrics["distribution"]):
        if a not in bdist:
            continue
        support = None
        if changed:
            support = (set(cur_vals.get(a, [])) | reserved) & (set(base_vals.get(a, [])) | reserved)
        out["axes"][a] = one("axis", a, metrics["distribution"][a], bdist[a], support)
    bans = baseline.get("answer_distribution") or {}
    for q in sorted(metrics["answer_distribution"]):
        if q in bans:
            out["answers"][q] = one("answer", q, metrics["answer_distribution"][q], bans[q], stats.ANSWER_KEYS)
    return out, small, alerts


def compute(bt, ctx):
    """반환: (지표 dict, 배치 이슈 목록)."""
    tax, pol = ctx.tax, ctx.policy
    l6 = pol["l6"]
    inputs = inputs_for(ctx)
    baseline, history = inputs.get("baseline"), inputs.get("history") or []
    verdicts = [bt.verdicts[rid] for rid in sorted(bt.verdicts)]
    R = content_targets(bt, ctx)
    recs = [t.record for t in R]
    axis_names = [a["name"] for a in tax.active_axes()]
    counts = stats.verdict_counts(verdicts)
    dist = stats.axis_distribution(recs, axis_names)
    cov, unused = stats.coverage(dist, active_values(tax))

    runs = int(l6["unused_runs"])
    prior = history[-(runs - 1):] if runs > 1 else []
    streak = {}
    for a in axis_names:
        if len(prior) < runs - 1:
            streak[a] = []
        else:
            streak[a] = [v for v in unused[a] if all(v in ((h.get("unused_labels") or {}).get(a) or []) for h in prior)]

    expressions = [tax.na, tax.unknown]
    for vals in tax.values.values():
        expressions += list(vals)
    for s in tax.synonyms:
        expressions += [s.get("alias"), s.get("canonical")]
    excluded = stats.exclusion_keys(expressions, l6["terms"]["stoplist"])
    docs = {t.record_id: (t.unit or {}).get("text") or "" for t in R}
    unknown_ids = {t.record_id for t in R if any(stats.is_unknown(t.record, a, tax.unknown) for a in axis_names)}
    terms = stats.term_candidates(docs, unknown_ids, excluded, l6["terms"]["min_df"], l6["terms"]["min_lift"],
                                  l6["terms"]["top_k"])

    judge = {k: 0 for k in JUDGE_KEYS}
    for rid in sorted(bt.targets):
        j = bt.targets[rid].judge
        if isinstance(j, dict):
            for k in JUDGE_KEYS:
                judge[k] += int(j.get(k) or 0)

    layers = [l for l in model.LAYERS if l in pol["layers"] and l != "L6"]
    metrics = {
        "records": len(verdicts),
        "content_records": len(R),
        "counts": counts,
        "pass_rate": stats.pass_rate(counts, len(verdicts)),
        "pareto": stats.pareto(verdicts),
        "layer_issue_rate": stats.layer_issue_rate(verdicts, layers),
        "distribution": dist,
        "answer_distribution": stats.answer_distribution(recs, sorted(tax.questions)),
        "unknown_rate": stats.unknown_rate(recs, axis_names, tax.na, tax.unknown),
        "coverage": cov,
        "unused_labels": unused,
        "unused_streak": streak,
        "terms": terms,
        "drift": None,
        "judge": judge,
    }
    drift, small, alerts = _drift(metrics, baseline, tax, l6)
    metrics["drift"] = drift

    issues = []
    for field, n, bn in small:
        issues.append(model.issue("L6_SAMPLE_TOO_SMALL", field=field,
                                  evidence={"n": n, "baseline_n": bn, "min_n": l6["min_n"]}))
    for field, value, n in alerts:
        issues.append(model.issue("L6_DRIFT_HIGH", field=field,
                                  evidence={"jsd": value, "n": n, "jsd_alert": l6["jsd_alert"]}))
    for a in axis_names:
        rate = metrics["unknown_rate"][a]
        if rate is not None and rate >= l6["unknown_rate_alert"] - 1e-12:
            issues.append(model.issue("L6_UNKNOWN_RATE_HIGH", field="axis:%s" % a,
                                      evidence={"rate": rate, "unknown_rate_alert": l6["unknown_rate_alert"]}))
    if baseline and baseline.get("pass_rate") is not None:
        drop = baseline["pass_rate"] - metrics["pass_rate"]
        if drop >= l6["pass_rate_drop_alert"] - 1e-12:
            issues.append(model.issue("L6_PASS_RATE_DROP", field=None,
                                      evidence={"pass_rate": metrics["pass_rate"],
                                                "baseline_pass_rate": baseline["pass_rate"],
                                                "drop": stats.rnd(drop), "pass_rate_drop_alert": l6["pass_rate_drop_alert"]}))
    for a in axis_names:
        if streak[a]:
            issues.append(model.issue("L6_UNUSED_LABELS", field="axis:%s" % a,
                                      evidence={"values": list(streak[a]), "runs": runs}))
    if terms:
        issues.append(model.issue("L6_UNMAPPED_TERMS", field=None, evidence={"count": len(terms)}))
    return metrics, issues


@register
class BatchStatsCheck(Check):
    id = "l6.batch"
    layer = "L6"
    scope = "batch"

    def run(self, target, ctx):
        metrics, issues = compute(target, ctx)
        ctx.batch.clear()
        ctx.batch.update(metrics)
        return issues
