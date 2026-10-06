"""규칙 제안 집계(6.6절). LLM을 쓰지 않는다. 신호, 수치, 예시 레코드 ID만 내고 프롬프트 문장이나 정답 값을 만들지 않는다.

| 종류 | 조건 |
|---|---|
| TERM | L6 용어 후보(metrics["terms"]) |
| UNUSED_VALUE | L6 연속 미사용 값(metrics["unused_streak"]) |
| AXIS_DEFINITION | 한 축에서 L3_NOT_SUPPORTED 또는 unknown인 레코드 비율 ≥ feedback.axis_issue_rate |
| QUESTION_WORDING | 한 질문에서 L3_NOT_SUPPORTED 또는 인용 불일치 비율 ≥ feedback.question_issue_rate |
| QUOTE_RULE | 인용이 있는 레코드 중 L3_SPAN_NOT_FOUND·L3_SPAN_WRONG_UNIT 비율 ≥ feedback.quote_issue_rate |
| FORMAT_RULE | 같은 정규화 규칙의 적용 건수 ≥ feedback.format_rule_min_count |

- 비율 제안은 분모가 feedback.min_n 미만이면 만들지 않는다.
- proposal_id는 (종류, 대상)의 해시라서 다시 실행해도 같다.
- qa/feedback_rejected.jsonl에 있는 제안 ID는 올리지 않는다. QA_POLICY는 feedback 명령이 결정 파일에서 만든다.
- 대상(target) 표기: AXIS_DEFINITION "axis:<축>", QUESTION_WORDING "answer:<질문 ID>", FORMAT_RULE "<규칙 이름>",
  QA_POLICY "<issue code>", QUOTE_RULE "prompt:quote", TERM "term:<용어>", UNUSED_VALUE "value:<축>=<값>".
  리포트의 효과 확인(report.transitions)은 앞의 넷만 이슈율로 잰다.
"""
from domain_engrbot import io, model, normalize

KINDS = ("TERM", "UNUSED_VALUE", "AXIS_DEFINITION", "QUESTION_WORDING", "QUOTE_RULE", "FORMAT_RULE", "QA_POLICY")
SPAN_CODES = ("L3_SPAN_NOT_FOUND", "L3_SPAN_WRONG_UNIT")
MAX_EXAMPLES = 5


def proposal_id(kind, target):
    return model.hash_obj({"kind": kind, "target": target})[:16]


def make(kind, target, subject, metric, examples):
    return {"proposal_id": proposal_id(kind, target), "kind": kind, "target": target, "subject": subject,
            "metric": metric, "examples": sorted(examples)[:MAX_EXAMPLES], "paste_row": None}


def rejected_ids(paths):
    if paths is None:
        return set()
    return {r.get("proposal_id") for r in io.read_own_jsonl(paths.feedback_rejected)}


def _rate_metric(name, hits, n, threshold):
    return {"name": name, "value": round(hits / float(n), 4) if n else 0.0, "n": n, "count": hits,
            "threshold": threshold}


def _issues_by_field(v, codes_):
    return {i.get("field") for i in v["issues"] if i["code"] in codes_}


def _has_quote(ev):
    return isinstance(ev, dict) and isinstance(ev.get("quote"), str) and bool(ev["quote"].strip())


def _record_quotes(rec):
    for a in (rec.get("axes") or {}).values():
        if isinstance(a, dict) and a.get("status") == "value" and _has_quote(a.get("evidence")):
            return True
    for a in (rec.get("answers") or {}).values():
        if isinstance(a, dict) and a.get("answer") in ("O", "X") and _has_quote(a.get("evidence")):
            return True
    for e in rec.get("extracted") or []:
        if isinstance(e, dict) and _has_quote(e.get("evidence")):
            return True
    return False


def compute(run):
    """제안 목록(기각 목록 반영 전). 정렬: 종류 순서, 대상."""
    fb = run.policy["feedback"]
    min_n = fb["min_n"]
    recs = {r["record_id"]: r for r in run.bundle.records}
    verdicts = [v for v in run.verdicts if v["record_id"] in recs]
    tax = run.ctx.tax if run.ctx is not None else model.TaxIndex(run.bundle.taxonomy)
    out = []

    # TERM: L6 용어 후보(본문 표현은 term에만 있고 작업 폴더 전용 파일에만 쓴다)
    terms_cfg = run.policy["l6"]["terms"]
    for t in (run.metrics or {}).get("terms") or []:
        term = t.get("term")
        if not term:
            continue
        metric = {"name": "lift", "value": t.get("lift"), "n": t.get("df_all"), "count": t.get("df_u"),
                  "threshold": terms_cfg["min_lift"]}
        out.append(make("TERM", "term:%s" % term, {"term": term}, metric, list(t.get("examples") or [])))

    # UNUSED_VALUE: 연속 미사용 값
    streak = (run.metrics or {}).get("unused_streak") or {}
    for axis in sorted(streak):
        for value in sorted(streak[axis] or []):
            metric = {"name": "연속 미사용 실행 수", "value": run.policy["l6"]["unused_runs"], "n": None,
                      "count": 0, "threshold": run.policy["l6"]["unused_runs"]}
            out.append(make("UNUSED_VALUE", "value:%s=%s" % (axis, value), {"axis": axis, "value": value}, metric, []))

    # AXIS_DEFINITION: 축별 분모 = 그 축이 value 또는 unknown인 레코드
    for axis in sorted(tax.axes):
        n, hits = 0, []
        field = "axis:%s" % axis
        for v in verdicts:
            a = (recs[v["record_id"]].get("axes") or {}).get(axis)
            if not isinstance(a, dict) or a.get("status") not in ("value", "unknown"):
                continue
            n += 1
            if a.get("status") == "unknown" or field in _issues_by_field(v, ("L3_NOT_SUPPORTED",)):
                hits.append(v["record_id"])
        if n >= min_n and hits and len(hits) / float(n) >= fb["axis_issue_rate"]:
            out.append(make("AXIS_DEFINITION", field, {"axis": axis},
                            _rate_metric("L3_NOT_SUPPORTED·unknown 비율", len(hits), n, fb["axis_issue_rate"]), hits))

    # QUESTION_WORDING: 질문별 분모 = 그 질문에 O 또는 X로 답한 레코드
    qids = sorted({q for r in recs.values() for q in (r.get("answers") or {})})
    for qid in qids:
        n, hits = 0, []
        field = "answer:%s" % qid
        for v in verdicts:
            a = (recs[v["record_id"]].get("answers") or {}).get(qid)
            if not isinstance(a, dict) or a.get("answer") not in ("O", "X"):
                continue
            n += 1
            if field in _issues_by_field(v, ("L3_NOT_SUPPORTED",) + SPAN_CODES):
                hits.append(v["record_id"])
        if n >= min_n and hits and len(hits) / float(n) >= fb["question_issue_rate"]:
            out.append(make("QUESTION_WORDING", field, {"qid": qid},
                            _rate_metric("L3_NOT_SUPPORTED·인용 불일치 비율", len(hits), n, fb["question_issue_rate"]),
                            hits))

    # QUOTE_RULE: 분모 = 인용이 하나라도 있는 레코드
    n, hits = 0, []
    for v in verdicts:
        if not _record_quotes(recs[v["record_id"]]):
            continue
        n += 1
        if any(i["code"] in SPAN_CODES for i in v["issues"]):
            hits.append(v["record_id"])
    if n >= min_n and hits and len(hits) / float(n) >= fb["quote_issue_rate"]:
        out.append(make("QUOTE_RULE", "prompt:quote", {},
                        _rate_metric("인용 불일치 비율", len(hits), n, fb["quote_issue_rate"]), hits))

    # FORMAT_RULE: 정규화 규칙별 적용 건수
    per_rule = {}
    for v in verdicts:
        for fx in v.get("auto_fixes") or []:
            for r in normalize.rules_of(fx):
                e = per_rule.setdefault(r, {"count": 0, "records": set()})
                e["count"] += 1
                e["records"].add(v["record_id"])
    for rule in sorted(per_rule):
        cnt, rids = per_rule[rule]["count"], per_rule[rule]["records"]
        if cnt >= fb["format_rule_min_count"]:
            metric = {"name": "%s 적용 건수" % rule, "value": cnt, "n": len(rids), "count": cnt,
                      "threshold": fb["format_rule_min_count"]}
            out.append(make("FORMAT_RULE", rule, {"rule": rule}, metric, list(rids)))

    out.sort(key=lambda p: (KINDS.index(p["kind"]), p["target"]))
    return out


def write(run):
    """proposals.jsonl을 쓴다. 기각된 제안은 뺀다. 반환: 제안 행."""
    skip = rejected_ids(run.paths)
    rows = [p for p in compute(run) if p["proposal_id"] not in skip]
    io.write_jsonl(run.path("proposals.jsonl"), rows)
    return rows
