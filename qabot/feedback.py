"""피드백 묶음(feedback 명령, 6.6절). qa/inbox 결정 파일에서 승인된 것만 모아 feedback/feedback.json·feedback.md를 쓴다.

- corrections: REVIEW·PASS 표본의 "교정", REJECT의 "직접 교정", 승인된 AUTO_FIX 정규화 값(개별 제외 레코드는 뺀다).
  AUTO_FIX는 결정으로 승인한 규칙이거나 policy의 autofix.approved_rules로 이미 승인된 규칙만 넣는다. 결정으로 기각하면 뺀다.
- rework: REJECT의 "재작업". "검수 오탐"은 rework에 넣지 않고 qa_false_positives에 코드별로 센다(QA_POLICY 제안).
- proposals: 승인된 규칙 제안. TERM은 고른 용도(새 값·동의어)에 맞춰 대상 시트 열 순서의 탭 구분 행을 만든다.
- 기각한 제안은 rejected_proposals에 적고 qa/feedback_rejected.jsonl에 중복 없이 덧붙인다(다음 실행부터 올리지 않는다).
- 보류, 판단 불가는 넣지 않는다. 파일명과 경로는 넣지 않는다. 같은 결정 파일이면 feedback.json이 같다.
- 검수봇은 taxonomy.xlsx, prompts/, work.sqlite를 쓰지 않는다. 반영은 사람이 한다.
"""
from qabot import golden, io, normalize, proposals, queue

TAXONOMY_COLUMNS = ("축", "값", "상위값", "다중값", "계층", "중복 알림 제외", "종류", "정의·판정 규칙", "포함 예", "제외 예",
                    "사용 여부")
SYNONYM_COLUMNS = ("동의어", "표준어", "메모")
CHECK_KINDS = ("AXIS_DEFINITION", "QUESTION_WORDING", "QUOTE_RULE", "FORMAT_RULE", "UNUSED_VALUE")
WHERE = {
    "AXIS_DEFINITION": "taxonomy 시트의 정의·판정 규칙, 분류 프롬프트",
    "QUESTION_WORDING": "questions 시트의 질문 문장",
    "QUOTE_RULE": "라벨러 프롬프트의 인용 규칙",
    "FORMAT_RULE": "라벨러 프롬프트의 표기 규칙",
    "UNUSED_VALUE": "taxonomy 시트의 사용 여부",
    "QA_POLICY": "검수 정책(policy)의 임계값이나 severity",
}


def _cell(s):
    return " ".join(str(s or "").replace("\t", " ").replace("\r", " ").replace("\n", " ").split())


def paste_row(proposal, decision):
    """TERM 승인 결정 → (시트 이름, 탭 구분 행). 필요한 입력이 없으면 (시트 이름 또는 None, None)."""
    term = _cell((proposal.get("subject") or {}).get("term"))
    use = decision.get("as")
    if use == "synonym":
        canonical = _cell(decision.get("canonical"))
        if not term or not canonical:
            return "synonyms", None
        return "synonyms", "\t".join([term, canonical, _cell(decision.get("note"))])
    if use == "value":
        axis = _cell(decision.get("axis"))
        if not term or not axis:
            return "taxonomy", None
        row = [axis, term, _cell(decision.get("parent"))] + [""] * (len(TAXONOMY_COLUMNS) - 3)
        return "taxonomy", "\t".join(row)
    return None, None


def _last_by(items, key):
    out = {}
    for d in items or []:
        if isinstance(d, dict):
            k = key(d)
            if k is not None:
                out[k] = d
    return out


def _autofix(run, doc, corrections):
    approved_policy = set(run.policy["autofix"]["approved_rules"])
    decs = _last_by(doc.get("autofix_decisions"), lambda d: d.get("rule") if isinstance(d.get("rule"), str) else None)
    approved = set(approved_policy) | {r for r, d in decs.items() if d.get("decision") == "approve"}
    rejected = {r for r, d in decs.items() if d.get("decision") == "reject"}
    excepted = {r: set(d.get("except") or []) for r, d in decs.items()}
    for v in run.verdicts:
        if v["verdict"] != "AUTO_FIX" or v.get("human_reviewed"):
            continue
        for fx in v.get("auto_fixes") or []:
            rule = fx["rule"]
            if rule in rejected or v["record_id"] in excepted.get(rule, ()):
                continue
            if rule in approved or normalize.is_approved(fx, approved):
                corrections.append({"record_id": v["record_id"], "field": fx["field"], "value": fx["after"],
                                    "quote": None, "source": "AUTO_FIX", "rule": rule})


def build(run):
    """반환: 피드백 dict. feedback/feedback.json, feedback/feedback.md를 쓰고 기각 제안을 qa/feedback_rejected.jsonl에 덧붙인다."""
    doc, _status = golden.read_inbox(run)
    sha = golden.decisions_sha256(doc)
    doc = doc or {}
    recs = {r["record_id"]: r for r in run.bundle.records}
    vmap = run.verdict_map()
    _queue_rows, rework_rows = queue.build(run)
    rework_map = {r["record_id"]: r for r in rework_rows}
    corrections = []

    # REVIEW 대기열·PASS 표본: "교정"만 넣는다(확정은 골든셋에만 남는다)
    decs = _last_by(doc.get("decisions"), lambda d: (d.get("record_id"), d.get("field"))
                    if isinstance(d.get("record_id"), str) and isinstance(d.get("field"), str) else None)
    for (rid, field), d in sorted(decs.items()):
        if d.get("decision") != "correct":
            continue
        if rid not in recs or rid not in vmap:
            run.log("feedback", rid, "RECORD_UNKNOWN")
            continue
        if golden.text_changed(vmap, run.bundle, rid):
            run.log("feedback", rid, "TEXT_CHANGED")
            continue
        corrections.append({"record_id": rid, "field": field, "value": d.get("value"), "quote": d.get("quote"),
                            "source": "REVIEW", "rule": None})

    # REJECT: 재작업, 직접 교정, 검수 오탐
    rework, fp = [], {}
    rdecs = _last_by(doc.get("reject_decisions"), lambda d: d.get("record_id") if isinstance(d.get("record_id"), str) else None)
    for rid, d in sorted(rdecs.items()):
        row = rework_map.get(rid)
        if row is None:
            run.log("feedback", rid, "RECORD_NOT_REJECT")
            continue
        kind = d.get("decision")
        if kind == "rework":
            rework.append({"record_id": rid, "fields": sorted({i["field"] for i in row["issues"] if i.get("field")}),
                           "issues": row["issues"]})
        elif kind == "correct":
            if golden.text_changed(vmap, run.bundle, rid):
                run.log("feedback", rid, "TEXT_CHANGED")
                continue
            for c in d.get("corrections") or []:
                if isinstance(c, dict) and isinstance(c.get("field"), str):
                    corrections.append({"record_id": rid, "field": c["field"], "value": c.get("value"),
                                        "quote": c.get("quote"), "source": "REJECT", "rule": None})
        elif kind == "false_positive":
            for code in sorted({i["code"] for i in row["issues"] if i["severity"] == "critical"}):
                fp.setdefault(code, set()).add(rid)

    _autofix(run, doc, corrections)
    corrections.sort(key=lambda c: (c["record_id"], c["field"], c["source"], c["rule"] or ""))

    # 규칙 제안
    known = {p["proposal_id"]: p for p in run.proposals}
    already = proposals.rejected_ids(run.paths)
    approved, rejected = [], []
    pdecs = _last_by(doc.get("proposal_decisions"),
                     lambda d: d.get("proposal_id") if isinstance(d.get("proposal_id"), str) else None)
    for pid, d in sorted(pdecs.items()):
        p = known.get(pid)
        if p is None:
            run.log("feedback", pid, "PROPOSAL_UNKNOWN")
            continue
        if d.get("decision") == "reject":
            rejected.append(pid)
        elif d.get("decision") == "approve":
            item = {"proposal_id": pid, "kind": p["kind"], "target": p["target"], "subject": p.get("subject") or {},
                    "as": d.get("as") if p["kind"] == "TERM" else None, "metric": p.get("metric") or {},
                    "examples": list(p.get("examples") or []), "sheet": None, "paste_row": None}
            if p["kind"] == "TERM":
                item["sheet"], item["paste_row"] = paste_row(p, d)
                if item["paste_row"] is None:
                    run.log("feedback", pid, "PASTE_INPUT_MISSING")
            approved.append(item)

    # 검수 오탐 → qa_false_positives와 QA_POLICY 제안
    n_reject_dec = len(rdecs)
    false_positives = [{"code": c, "records": len(fp[c])} for c in sorted(fp)]
    for c in sorted(fp):
        p = proposals.make("QA_POLICY", c, {"code": c},
                           {"name": "검수 오탐 표시 레코드 수", "value": len(fp[c]), "n": n_reject_dec,
                            "count": len(fp[c]), "threshold": None}, list(fp[c]))
        if p["proposal_id"] in already:
            continue
        approved.append(dict(p, **{"as": None, "sheet": None}))
    approved.sort(key=lambda p: (proposals.KINDS.index(p["kind"]), p["target"]))

    fb = {
        "qa_run_id": run.qa_run_id,
        "labeler_run_id": run.labeler_run_id,
        "decisions_sha256": sha,
        "corrections": corrections,
        "rework": sorted(rework, key=lambda r: r["record_id"]),
        "proposals": approved,
        "rejected_proposals": sorted(set(rejected)),
        "qa_false_positives": false_positives,
    }
    if not run.policy["output"]["include_text"]:
        fb = io.strip_text(fb)
    io.write_json(run.path("feedback", "feedback.json"), fb)
    io.write_text(run.path("feedback", "feedback.md"), render_md(fb))
    for pid in fb["rejected_proposals"]:
        if pid not in already:
            p = known[pid]
            io.append_jsonl(run.paths.feedback_rejected,
                            {"proposal_id": pid, "kind": p["kind"], "target": p["target"], "qa_run_id": run.qa_run_id})
            run.log("feedback", pid, "PROPOSAL_REJECTED")
    return fb


def _metric_text(m):
    if not m:
        return "-"
    parts = ["%s %s" % (m.get("name"), m.get("value"))]
    if m.get("n") is not None:
        parts.append("n=%s" % m["n"])
    if m.get("threshold") is not None:
        parts.append("기준 %s" % m["threshold"])
    return ", ".join(parts)


def render_md(fb):
    """사람이 labelbot에 반영할 일을 순서대로 적는다. 파일명과 경로는 넣지 않는다."""
    lines = ["# 검수봇 피드백 묶음", "",
             "- 검수 실행 ID: %s" % fb["qa_run_id"],
             "- 라벨러 실행 ID: %s" % (fb["labeler_run_id"] or "-"),
             "- 결정 지문: %s" % ((fb["decisions_sha256"] or "결정 파일 없음")[:16]),
             "- 검수봇은 taxonomy 시트, labelbot 프롬프트, 작업 DB를 고치지 않는다. 아래 순서대로 사람이 반영한다.", ""]
    props = fb["proposals"]

    lines += ["## 1. 시트별 붙여넣기 행", ""]
    any_row = False
    for sheet, cols in (("taxonomy", TAXONOMY_COLUMNS), ("synonyms", SYNONYM_COLUMNS)):
        rows = [p for p in props if p["kind"] == "TERM" and p.get("sheet") == sheet]
        if not rows:
            continue
        any_row = True
        lines += ["### %s 시트 (열 순서: %s)" % (sheet, ", ".join(cols)), ""]
        ok = [p["paste_row"] for p in rows if p["paste_row"]]
        if ok:
            lines += ["```"] + ok + ["```"]
        for p in rows:
            if not p["paste_row"]:
                lines.append("- 입력 누락으로 행을 만들지 못했다: 제안 %s(%s). 검토 화면에서 %s을 채워 다시 내려받는다." % (
                    p["proposal_id"], p["target"], "축" if sheet == "taxonomy" else "표준어"))
        lines.append("")
    no_use = [p for p in props if p["kind"] == "TERM" and not p.get("sheet")]
    for p in no_use:
        any_row = True
        lines.append("- 용도(새 값·동의어)를 고르지 않은 용어 제안: %s(%s)" % (p["proposal_id"], p["target"]))
    if not any_row:
        lines += ["- 없음", ""]
    elif no_use:
        lines.append("")

    lines += ["## 2. 점검할 축·질문·프롬프트 규칙", ""]
    checks = [p for p in props if p["kind"] in CHECK_KINDS]
    if checks:
        lines += ["| 종류 | 대상 | 수치 | labelbot에서 고칠 곳 | 예시 레코드 |", "|---|---|---|---|---|"]
        for p in checks:
            lines.append("| %s | %s | %s | %s | %s |" % (p["kind"], p["target"].replace("|", "/"), _metric_text(p["metric"]),
                                                     WHERE[p["kind"]], ", ".join(p["examples"][:3]) or "-"))
    else:
        lines.append("- 없음")
    lines.append("")

    lines += ["## 3. 레코드 교정과 재작업", ""]
    by_src = {}
    for c in fb["corrections"]:
        by_src[c["source"]] = by_src.get(c["source"], 0) + 1
    lines.append("- 레코드 교정: %d건 (REVIEW %d, REJECT %d, AUTO_FIX %d)" % (
        len(fb["corrections"]), by_src.get("REVIEW", 0), by_src.get("REJECT", 0), by_src.get("AUTO_FIX", 0)))
    lines.append("- 재작업: %d건" % len(fb["rework"]))
    lines.append("- labelbot의 apply는 4차 불량 목록에 있는 chunk의 교정만 받는다. 그 밖의 교정은 이 묶음과 골든셋에 남는다.")
    if fb["rework"]:
        lines += ["", "| 레코드 ID | 필드 | 코드 |", "|---|---|---|"]
        for r in fb["rework"]:
            lines.append("| %s | %s | %s |" % (r["record_id"], ", ".join(r["fields"]) or "-",
                                             ", ".join(sorted({i["code"] for i in r["issues"]}))))
    lines.append("")

    lines += ["## 4. 검수 정책 조정 제안", ""]
    if fb["qa_false_positives"]:
        lines += ["| 코드 | 검수 오탐 표시 레코드 수 | 고칠 곳 |", "|---|---|---|"]
        for f in fb["qa_false_positives"]:
            lines.append("| %s | %d | %s |" % (f["code"], f["records"], WHERE["QA_POLICY"]))
    else:
        lines.append("- 없음")
    lines.append("")
    if fb["rejected_proposals"]:
        lines += ["기각한 제안 %d건은 기각 목록(feedback_rejected)에 남겨 다시 올리지 않는다." % len(fb["rejected_proposals"]), ""]
    return "\n".join(lines)
