"""배치 리포트(8.3절), taxonomy 개정 후보, 추이, 기준선, 판정 전이표(6.6절 효과 확인).

- report.md, report.json, history.jsonl, baseline.json은 본문 없음 부류다(4.6절). 레코드·파일 ID, 코드, 수치,
  taxonomy 값·축 이름, 질문 ID만 넣는다. 본문, 파일명, 경로는 넣지 않는다.
- 용어 후보(본문 표현)는 taxonomy_candidates.*(작업 폴더 전용)에만 쓰고 report.md에는 건수만 적는다.
- 리포트에는 시각을 넣지 않는다. 같은 저장 실행으로 `report --qa-run`을 돌리면 같은 파일이 나온다.
"""
import os
import re

from domain_engrbot import codes, engine, io, model, normalize, stats
from domain_engrbot.checks import l6_batch

CANDIDATES = "taxonomy_candidates.jsonl"
BATCH_ISSUES_IN_SUMMARY = 8
GAP_FIELDS_TOP = 8
_KIND_RE = re.compile(r"^[A-Z][A-Z_]{0,39}$")


# ---- 지표 -------------------------------------------------------------------

def _ctx(run):
    if run.ctx is None:
        run.ctx = engine.Ctx(run.bundle, run.policy, run.schema, qa_run_id=run.qa_run_id, paths=run.paths)
    return run.ctx


def metrics(run):
    """L6 지표. L6 층을 끈 실행이면 여기서 계산한다(배치 이슈는 만들지 않는다)."""
    if run.metrics and "records" in run.metrics:
        return run.metrics
    ctx = _ctx(run)
    targets = run.targets or engine.batch_only(run.bundle, ctx, run.verdicts)["targets"]
    m, _ = l6_batch.compute(engine.BatchTarget(run.bundle, targets, run.verdict_map(), run.file_issues), ctx)
    ctx.batch.clear()
    ctx.batch.update(m)
    run.metrics = ctx.batch
    return run.metrics


def _counts(run):
    out = {"records": len(run.verdicts), "files": len({v.get("file_id") for v in run.verdicts})}
    out.update(stats.verdict_counts(run.verdicts))
    return out


def _top_codes(m, k=5):
    return [{"code": p["code"], "records": p["records"]} for p in m["pareto"][:k]]


def history_entry(run, m):
    return {
        "qa_run_id": run.qa_run_id,
        "labeler_run_id": run.labeler_run_id,
        "pass_rate": m["pass_rate"],
        "counts": _counts(run),
        "unknown_rate": m["unknown_rate"],
        "coverage": m["coverage"],
        "top_codes": _top_codes(m),
        "unused_labels": m["unused_labels"],
        "taxonomy_version": _ctx(run).tax.version,
    }


# ---- 판정 전이표 ---------------------------------------------------------------

def _empty_matrix():
    return {p: {c: 0 for c in model.VERDICTS} for p in model.VERDICTS}


def _field_hit(issue, target):
    f = issue.get("field") or ""
    return (f == target or f.startswith(target + "#")) and \
        model.SEVERITY_RANK.get(issue["severity"], 0) >= model.SEVERITY_RANK["minor"]


def _issue_rate(verdicts, kind, target):
    if not verdicts:
        return None
    n = 0
    for v in verdicts:
        issues = v.get("issues") or []
        if kind == "field":
            hit = any(_field_hit(i, target) for i in issues)
        elif kind == "code":
            hit = any(i["code"] == target for i in issues)
        else:
            hit = any(target in normalize.rules_of(fx) for fx in v.get("auto_fixes") or [])
        n += 1 if hit else 0
    return stats.ratio(n, len(verdicts))


def _target_kind(target, tax):
    """제안 대상 중 본문이 아닌 것(축 이름, 질문 ID, 코드, 정규화 규칙)만 리포트에 싣는다."""
    if not isinstance(target, str):
        return None
    if target.startswith("axis:") and target[5:] in tax.axes:
        return "field"
    if target.startswith("answer:") and target[7:] in tax.questions:
        return "field"
    if target in codes.catalog():
        return "code"
    if target in normalize.RULES:
        return "rule"
    return None


def previous_run(paths, qa_run_id):
    """이번 실행 ID보다 앞선 실행 중 verdicts.jsonl이 있는 가장 최근 것. 없으면 None."""
    if paths is None or not qa_run_id:
        return None
    for rid in reversed(paths.list_runs()):
        if rid < qa_run_id and os.path.isfile(os.path.join(paths.run_dir(rid), "verdicts.jsonl")):
            return rid
    return None


def transitions(run, m):
    out = {"previous_qa_run_id": None, "matrix": _empty_matrix(), "matched": 0, "text_changed": 0,
           "only_previous": 0, "only_current": 0, "proposal_effects": [], "proposals_skipped": 0}
    prev_id = previous_run(run.paths, run.qa_run_id)
    if prev_id is None:
        return out
    prev_dir = run.paths.run_dir(prev_id)
    prev = {v["record_id"]: v for v in io.read_own_jsonl(os.path.join(prev_dir, "verdicts.jsonl"))}
    cur = run.verdict_map()
    out["previous_qa_run_id"] = prev_id
    for rid in sorted(set(prev) | set(cur)):
        if rid not in cur:
            out["only_previous"] += 1
        elif rid not in prev:
            out["only_current"] += 1
        elif prev[rid].get("text_hash") != cur[rid].get("text_hash"):
            out["text_changed"] += 1
        else:
            out["matched"] += 1
            out["matrix"][prev[rid]["verdict"]][cur[rid]["verdict"]] += 1

    fb = io.read_own_json(os.path.join(prev_dir, "feedback", "feedback.json")) or {}
    prev_report = io.read_own_json(os.path.join(prev_dir, "report.json")) or {}
    tax = _ctx(run).tax
    prev_v = [prev[k] for k in sorted(prev)]
    cur_v = [cur[k] for k in sorted(cur)]
    rows = []
    for p in fb.get("proposals") or []:
        target = p.get("target")
        kind = _target_kind(target, tax)
        if kind is None:
            out["proposals_skipped"] += 1
            continue
        pk = p.get("kind") if isinstance(p.get("kind"), str) and _KIND_RE.match(p.get("kind")) else "OTHER"
        row = {"proposal_id": str(p.get("proposal_id") or "")[:64], "kind": pk, "target": target,
               "issue_rate": {"before": _issue_rate(prev_v, kind, target), "after": _issue_rate(cur_v, kind, target)}}
        if target.startswith("axis:"):
            row["unknown_rate"] = {"before": (prev_report.get("unknown_rate") or {}).get(target[5:]),
                                   "after": m["unknown_rate"].get(target[5:])}
        rows.append(row)
    out["proposal_effects"] = sorted(rows, key=lambda r: (r["kind"], r["target"], r["proposal_id"]))
    return out


# ---- report.json -------------------------------------------------------------

def _judge(run, m):
    man = run.manifest or {}
    j = man.get("judge") or {}
    ctx = _ctx(run)
    ran = man.get("judge_ran", ctx.judge is not None)
    skip = man.get("judge_skip_reason", ctx.judge_skip_reason)
    if not ran and skip is None and "L3B" not in (run.policy or {}).get("layers", []):
        skip = "L3B_OFF"
    items = dict(m["judge"])
    n = items.get("items") or 0
    return {"ran": bool(ran), "skip_reason": skip, "calls": int(j.get("calls") or 0),
            "cache_hits": int(j.get("cache_hits") or 0), "failed": int(j.get("failed") or 0),
            "items": items, "item_rates": {k: stats.ratio(items[k], n) for k in ("supported", "partial", "unsupported",
                                                                                 "failed")}}


def _int_or_none(x):
    return x if isinstance(x, int) and not isinstance(x, bool) else None


def _ledger(man):
    """manifest ledger의 건수만 뽑는다(경로·본문 없음). 장부가 없으면 None."""
    led = man.get("ledger")
    if not isinstance(led, dict) or not led:
        return None
    intake = led.get("intake") if isinstance(led.get("intake"), dict) else {}
    ex = (man.get("judge") or {}).get("examples")
    ex = ex if isinstance(ex, dict) else {}
    used = _int_or_none(ex.get("used"))
    same, ext = _int_or_none(ex.get("excluded_same_source")), _int_or_none(ex.get("excluded_external"))
    err = led.get("intake_error")
    return {
        "intake_cases": _int_or_none(intake.get("cases")),
        "intake_corrected": _int_or_none(intake.get("corrected")),
        "intake_confirmed": _int_or_none(intake.get("confirmed")),
        "golden_total": _int_or_none(led.get("golden_total")),
        "examples_used": used,
        "examples_excluded": None if same is None and ext is None else (same or 0) + (ext or 0),
        "candidates": _int_or_none(led.get("candidates_loaded")),
        "intake_error": err if isinstance(err, str) and _KIND_RE.match(err) else ("OTHER" if err else None),
    }


def _labeler_gap(run):
    """labelbot 불량 목록이 놓친 비율. judge가 돈 레코드 중 불량 목록에 없는데 L3_NOT_SUPPORTED가 나온 비율이다.

    불량 목록 정보가 없는 번들(이전 작업 DB, 합성 번들)이면 비율을 내지 않는다.
    """
    meta = (run.bundle.meta or {}) if run.bundle else {}
    flagged = meta.get("labeler_flagged")
    judged = [v for v in run.verdicts if v.get("judge")]
    out = {"flagged_known": flagged is not None, "labeler_flagged": len(flagged or []),
           "human_reviewed": sum(1 for v in run.verdicts if v.get("human_reviewed")), "judged": len(judged),
           "unflagged_judged": None, "unflagged_unsupported": None, "miss_rate": None, "fields": {}}
    if flagged is None:
        return out
    flagged = set(flagged)
    unflagged = [v for v in judged if v["record_id"] not in flagged]
    miss, fields = 0, {}
    for v in unflagged:
        hit = {i.get("field") for i in v["issues"] if i["code"] == "L3_NOT_SUPPORTED"}
        miss += bool(hit)
        for f in hit:
            fields[f] = fields.get(f, 0) + 1
    top = sorted(fields.items(), key=lambda kv: (-kv[1], kv[0] or ""))[:GAP_FIELDS_TOP]
    out.update(unflagged_judged=len(unflagged), unflagged_unsupported=miss,
               miss_rate=stats.ratio(miss, len(unflagged)), fields=dict(top))
    return out


def build(run, m, history, trans):
    man = run.manifest or {}
    ctx = _ctx(run)
    queue_codes = {}
    for row in run.queue:
        for c in sorted(set(row.get("issue_codes") or [])):
            queue_codes[c] = queue_codes.get(c, 0) + 1
    by_kind = {}
    for p in run.proposals:
        k = p.get("kind") if isinstance(p.get("kind"), str) and _KIND_RE.match(p.get("kind")) else "OTHER"
        by_kind[k] = by_kind.get(k, 0) + 1
    file_issues = sorted({(fi["file_id"], fi["code"]) for fi in run.file_issues})
    rep = {
        "qa_run_id": run.qa_run_id,
        "labeler_run_id": run.labeler_run_id,
        "versions": man.get("versions") or dict(ctx.versions),
        "input_fingerprint": man.get("input_fingerprint") or run.bundle.fingerprint(),
        "layers": list((run.policy or {}).get("layers") or []),
        "counts": _counts(run),
        "content_records": m["content_records"],
        "pass_rate": m["pass_rate"],
        "pareto": m["pareto"],
        "layer_issue_rate": m["layer_issue_rate"],
        "file_issues": [{"file_id": f, "code": c} for f, c in file_issues],
        "judge": _judge(run, m),
        "labeler_gap": _labeler_gap(run),
        "l3b_routed": bool(((run.policy or {}).get("judge") or {}).get("route_to_review")),
        "l3b_skip_human": bool(((run.policy or {}).get("judge") or {}).get("skip_human_reviewed")),
        "drift": m["drift"],
        "unknown_rate": m["unknown_rate"],
        "coverage": m["coverage"],
        "unused_labels": m["unused_labels"],
        "unused_streak": m["unused_streak"],
        "answer_distribution": m["answer_distribution"],
        "unmapped_terms": {"count": len(m["terms"]), "file": CANDIDATES},
        "batch_issues": [{"code": i["code"], "field": i.get("field"), "evidence": i.get("evidence") or {}}
                         for i in run.batch_issues],
        "history": history,
        "review_queue": {"count": len(run.queue), "codes": dict(sorted(queue_codes.items()))},
        "proposals": {"count": len(run.proposals), "by_kind": dict(sorted(by_kind.items()))},
        "transitions": trans,
    }
    led = _ledger(man)
    if led is not None:
        rep["ledger"] = led
    return rep


# ---- report.md ---------------------------------------------------------------

def _pct(x):
    return "-" if x is None else "%.1f%%" % (100.0 * x)


def _num(x, fmt="%.4f"):
    return "-" if x is None else fmt % x


def _cell(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def _md_summary(rep):
    """머리 요약."""
    c = rep["counts"]
    j = rep["judge"]
    lines = ["# 검수 배치 리포트", ""]
    if not j["ran"]:
        lines.append("> judge 미실행(%s). L3B(근거의 라벨 지지) 판정이 이 리포트에 없다." % (j["skip_reason"] or "-"))
        lines.append("")
    lines.append("- 검수 실행: %s / 라벨러 실행: %s" % (rep["qa_run_id"], rep["labeler_run_id"]))
    lines.append("- 통과율: %s (PASS+AUTO_FIX %d / 전체 %d)" % (_pct(rep["pass_rate"]), c["PASS"] + c["AUTO_FIX"],
                                                          c["records"]))
    lines.append("- 판정: PASS %d, AUTO_FIX %d, REVIEW %d, REJECT %d (파일 %d, 내용 chunk %d)" % (
        c["PASS"], c["AUTO_FIX"], c["REVIEW"], c["REJECT"], c["files"], rep["content_records"]))
    if j["ran"]:
        lines.append("- judge: 실행(호출 %d회, 캐시 %d회, 실패 %d건)" % (j["calls"], j["cache_hits"], j["failed"]))
    else:
        lines.append("- judge: 미실행(%s)" % (j["skip_reason"] or "-"))
    bi = rep["batch_issues"]
    if bi:
        by = {}
        for i in bi:
            by[i["code"]] = by.get(i["code"], 0) + 1
        lines.append("- 배치 이슈 %d건: %s" % (len(bi), ", ".join("%s %d" % kv for kv in sorted(by.items()))))
        for i in bi[:BATCH_ISSUES_IN_SUMMARY]:
            lines.append(("  - %s %s" % (i["code"], i["field"] or "")).rstrip())
        if len(bi) > BATCH_ISSUES_IN_SUMMARY:
            lines.append("  - 외 %d건(6절)" % (len(bi) - BATCH_ISSUES_IN_SUMMARY))
    else:
        lines.append("- 배치 이슈: 없음")
    d = rep["drift"]
    lines.append("- 드리프트: %s" % (d["note"] if d["baseline_qa_run_id"] is None
                                    else "기준선 %s%s" % (d["baseline_qa_run_id"], ", taxonomy 변경됨" if d["taxonomy_changed"] else "")))
    g = rep["labeler_gap"]
    if g["flagged_known"]:
        lines.append("- labelbot 불량 목록 누락 의심: %s (불량 목록 밖 judge %d건 중 근거 불일치 %d건, 지표 전용)" % (
            _pct(g["miss_rate"]), g["unflagged_judged"], g["unflagged_unsupported"]))
    lines.append("- REVIEW 대기 %d건, 규칙 제안 %d건, 용어 후보 %d건" % (
        rep["review_queue"]["count"], rep["proposals"]["count"], rep["unmapped_terms"]["count"]))
    led = rep.get("ledger")
    if led:
        def n(k):
            return "-" if led.get(k) is None else str(led[k])

        lines.append("- 교정 장부: 이번 intake 사례 %s(교정 %s, 확인 %s), 누적 골든 %s, "
                     "judge 예시 사용 %s회(요청 누적, 제외 %s회), L4 후보 %s%s" % (n("intake_cases"), n("intake_corrected"), n("intake_confirmed"),
                                     n("golden_total"), n("examples_used"), n("examples_excluded"), n("candidates"),
                                     ", intake 오류 %s" % led["intake_error"] if led.get("intake_error") else ""))
    lines.append("")
    return lines


def _md_versions(rep):
    v = rep["versions"]
    lines = ["## 1. 버전과 입력 지문", ""]
    for k in sorted(v):
        val = v[k]
        if isinstance(val, dict):
            val = ", ".join("%s=%s" % kv for kv in sorted(val.items()))
        lines.append("- %s: %s" % (k, val))
    lines.append("- 입력 지문: %s" % rep["input_fingerprint"])
    lines.append("- 층: %s" % ", ".join(rep["layers"]))
    lines.append("")
    return lines


def _md_pareto(rep):
    lines = ["## 2. 오류 유형 파레토", ""]
    if rep["pareto"]:
        lines += ["| code | 레코드 | 비율 | 누적 |", "|---|---|---|---|"]
        for p in rep["pareto"]:
            lines.append("| %s | %d | %s | %s |" % (p["code"], p["records"], _pct(p["share"]), _pct(p["cum_share"])))
    else:
        lines.append("이슈가 붙은 레코드가 없다.")
    lines.append("")
    return lines


def _md_layers(rep):
    lines = ["## 3. 층별 이슈율과 파일 단위 이슈", "", "| 층 | 이슈율(minor 이상) |", "|---|---|"]
    for l, r in rep["layer_issue_rate"].items():
        lines.append("| %s | %s |" % (l, _pct(r)))
    lines.append("")
    if rep["file_issues"]:
        lines += ["| 파일 ID | code |", "|---|---|"]
        for fi in rep["file_issues"]:
            lines.append("| %s | %s |" % (fi["file_id"][:16], fi["code"]))
    else:
        lines.append("파일 단위 이슈가 없다.")
    lines.append("")
    return lines


def _md_queue(rep):
    q = rep["review_queue"]
    lines = ["## 4. REVIEW 대기", "", "- 대기 %d건. 목록은 `review.html`에서 본다." % q["count"]]
    if q["codes"]:
        lines += ["", "| code | 레코드 |", "|---|---|"]
        for code, n in q["codes"].items():
            lines.append("| %s | %d |" % (code, n))
    lines.append("")
    return lines


def _md_taxonomy(rep):
    lines = ["## 5. taxonomy 개정 후보", "",
             "| 축 | 커버리지 | unknown 비율 | 미사용 값 | 연속 미사용 |", "|---|---|---|---|---|"]
    for a in sorted(rep["coverage"]):
        lines.append("| %s | %s | %s | %s | %s |" % (
            _cell(a), _pct(rep["coverage"][a]), _pct(rep["unknown_rate"].get(a)),
            _cell(", ".join(rep["unused_labels"].get(a) or []) or "-"),
            _cell(", ".join(rep["unused_streak"].get(a) or []) or "-")))
    lines += ["", "- 매핑되지 않는 빈출 용어 후보: %d건. 목록은 `taxonomy_candidates.md`에서 본다." % rep["unmapped_terms"]["count"], ""]
    return lines


def _md_drift(rep):
    """6. 드리프트와 최근 추이(배치 이슈 표 포함)."""
    d = rep["drift"]
    bi = rep["batch_issues"]
    lines = ["## 6. 드리프트와 최근 추이", ""]
    if d["baseline_qa_run_id"] is None:
        lines.append(d["note"])
    else:
        lines.append("- 기준선: %s" % d["baseline_qa_run_id"])
        if d["note"]:
            lines.append("- %s" % d["note"])
        lines += ["", "| 대상 | JSD | n | 수준 |", "|---|---|---|---|"]
        for a, e in sorted(d["axes"].items()):
            lines.append("| axis:%s | %s | %d | %s |" % (_cell(a), _num(e["jsd"]), e["n"], e["level"]))
        for qid, e in sorted(d["answers"].items()):
            lines.append("| answer:%s | %s | %d | %s |" % (_cell(qid), _num(e["jsd"]), e["n"], e["level"]))
    lines.append("")
    if bi:
        lines += ["| 배치 이슈 | 대상 | 수치 |", "|---|---|---|"]
        for i in bi:
            ev = ", ".join("%s=%s" % (k, ",".join(map(str, val)) if isinstance(val, list) else val)
                           for k, val in sorted(i["evidence"].items()))
            lines.append("| %s | %s | %s |" % (i["code"], _cell(i["field"] or "-"), _cell(ev)))
        lines.append("")
    lines += ["| 검수 실행 | 통과율 | PASS | AUTO_FIX | REVIEW | REJECT | 상위 코드 |", "|---|---|---|---|---|---|---|"]
    for h in rep["history"]:
        hc = h.get("counts") or {}
        top = (h.get("top_codes") or [{}])[0].get("code") if h.get("top_codes") else "-"
        lines.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            h.get("qa_run_id"), _pct(h.get("pass_rate")), hc.get("PASS", "-"), hc.get("AUTO_FIX", "-"),
            hc.get("REVIEW", "-"), hc.get("REJECT", "-"), top))
    lines.append("")
    return lines


def _md_judge(rep):
    j = rep["judge"]
    lines = ["## 7. judge 통계와 한계", ""]
    if j["ran"]:
        lines.append("- 호출 %d회, 캐시 적중 %d회, 실패 %d건" % (j["calls"], j["cache_hits"], j["failed"]))
    else:
        lines.append("- judge 미실행(%s). L3B 항목 통계가 없다." % (j["skip_reason"] or "-"))
    it, ir = j["items"], j["item_rates"]
    lines.append("- 항목 %d개: supported %d(%s), partial %d(%s), unsupported %d(%s), failed %d(%s)" % (
        it["items"], it["supported"], _pct(ir["supported"]), it["partial"], _pct(ir["partial"]),
        it["unsupported"], _pct(ir["unsupported"]), it["failed"], _pct(ir["failed"])))
    g = rep["labeler_gap"]
    lines.append("- 라우팅: L3B 이슈는 %s. 사람이 이미 본 레코드 %d건%s." % (
        "검토 대기열에 넣는다" if rep.get("l3b_routed") else "판정에 넣지 않는 지표다(info)",
        g["human_reviewed"], ", judge 생략" if rep.get("l3b_skip_human") else ""))
    if g["flagged_known"]:
        lines.append("- labelbot 불량 목록 %d건 / 목록 밖 judge %d건 중 근거 불일치 %d건(누락 의심 %s)" % (
            g["labeler_flagged"], g["unflagged_judged"], g["unflagged_unsupported"], _pct(g["miss_rate"])))
        if g["fields"]:
            lines.append("- 누락 의심 필드: %s" % ", ".join("%s %d" % (_cell(f), n) for f, n in g["fields"].items()))
    else:
        lines.append("- labelbot 불량 목록 정보가 없어 누락 의심 비율을 내지 않는다.")
    lines.append("- 한계: 누락 라벨(본문에 근거가 있는데 붙이지 않은 라벨)은 탐지하지 못한다. 붙은 라벨과 근거만 본다.")
    lines.append("- 한계: judge 판정은 mock이면 배관 확인용이고 품질 지표가 아니다.")
    lines.append("")
    return lines


def _md_proposals(rep):
    t = rep["transitions"]
    lines = ["## 8. 규칙 제안과 효과 확인", ""]
    p = rep["proposals"]
    lines.append("- 규칙 제안 %d건%s" % (p["count"], (": " + ", ".join("%s %d" % kv for kv in p["by_kind"].items()))
                                      if p["by_kind"] else ""))
    if t["previous_qa_run_id"] is None:
        lines.append("- 직전 검수 실행이 없어 판정 전이표를 만들지 않았다.")
    else:
        lines += ["- 직전 실행: %s (같은 본문 %d건, 본문 바뀜 %d건, 직전에만 %d건, 이번에만 %d건)" % (
            t["previous_qa_run_id"], t["matched"], t["text_changed"], t["only_previous"], t["only_current"]), "",
            "| 직전 \\ 이번 | %s |" % " | ".join(model.VERDICTS), "|---|%s" % ("---|" * len(model.VERDICTS))]
        for pv in model.VERDICTS:
            lines.append("| %s | %s |" % (pv, " | ".join(str(t["matrix"][pv][cv]) for cv in model.VERDICTS)))
        lines.append("")
        if t["proposal_effects"]:
            lines += ["| 승인된 제안 | 대상 | 이슈율 전 | 이슈율 후 | unknown 전 | unknown 후 |", "|---|---|---|---|---|---|"]
            for e in t["proposal_effects"]:
                u = e.get("unknown_rate") or {}
                lines.append("| %s | %s | %s | %s | %s | %s |" % (
                    e["kind"], _cell(e["target"]), _pct(e["issue_rate"]["before"]), _pct(e["issue_rate"]["after"]),
                    _pct(u.get("before")), _pct(u.get("after"))))
        else:
            lines.append("- 직전 피드백에서 승인된 제안 중 이슈율을 잴 대상이 없다.")
        if t["proposals_skipped"]:
            lines.append("- 대상이 축·질문·코드·규칙이 아니라 이슈율을 재지 않은 제안: %d건" % t["proposals_skipped"])
    lines.append("")
    return lines


def render_md(rep):
    lines = []
    for section in (_md_summary, _md_versions, _md_pareto, _md_layers, _md_queue, _md_taxonomy, _md_drift,
                    _md_judge, _md_proposals):
        lines += section(rep)
    return "\n".join(lines)


# ---- taxonomy_candidates -----------------------------------------------------

def candidate_rows(m):
    rows = []
    for a in sorted(m["coverage"]):
        rows.append({"kind": "axis", "axis": a, "coverage": m["coverage"][a], "unknown_rate": m["unknown_rate"].get(a),
                     "unused": list(m["unused_labels"].get(a) or []), "unused_streak": list(m["unused_streak"].get(a) or [])})
    for t in m["terms"]:
        rows.append(dict(t, kind="term"))
    return rows


def render_candidates_md(run, m):
    lines = ["# taxonomy 개정 후보", "", "- 검수 실행: %s" % run.qa_run_id,
             "- 이 파일은 본문 표현(용어 후보)을 담으므로 작업 폴더 밖으로 내지 않는다.", "",
             "## 축별 커버리지, unknown 비율, 미사용 값", "",
             "| 축 | 커버리지 | unknown 비율 | 미사용 값 | 연속 미사용 |", "|---|---|---|---|---|"]
    for a in sorted(m["coverage"]):
        lines.append("| %s | %s | %s | %s | %s |" % (
            _cell(a), _pct(m["coverage"][a]), _pct(m["unknown_rate"].get(a)),
            _cell(", ".join(m["unused_labels"].get(a) or []) or "-"), _cell(", ".join(m["unused_streak"].get(a) or []) or "-")))
    lines += ["", "## 매핑되지 않는 빈출 용어 후보", ""]
    if m["terms"]:
        lines += ["| 용어 | lift | df(unknown) | df(전체) | 예시 레코드 |", "|---|---|---|---|---|"]
        for t in m["terms"]:
            lines.append("| %s | %s | %d | %d | %s |" % (_cell(t["term"]), _num(t["lift"], "%.3f"), t["df_u"], t["df_all"],
                                                      ", ".join(t["examples"])))
    else:
        lines.append("후보가 없다.")
    lines.append("")
    return "\n".join(lines)


# ---- 쓰기 -------------------------------------------------------------------

def write(run, append_history=True):
    """report.json, report.md, taxonomy_candidates.*, l6_inputs.json을 쓰고 history.jsonl에 한 줄 더한다. 반환: report dict."""
    m = metrics(run)
    ctx = _ctx(run)
    inputs = l6_batch.inputs_for(ctx)
    entry = history_entry(run, m)
    history = [h for h in inputs.get("history") or [] if h.get("qa_run_id") != run.qa_run_id]
    history = (history + [entry])[-l6_batch.HISTORY_SHOWN:]
    rep = build(run, m, history, transitions(run, m))
    io.write_json(run.path(l6_batch.INPUTS_FILE), inputs)
    io.write_json(run.path("report.json"), rep)
    io.write_text(run.path("report.md"), render_md(rep))
    io.write_jsonl(run.path(CANDIDATES), candidate_rows(m))
    io.write_text(run.path("taxonomy_candidates.md"), render_candidates_md(run, m))
    if append_history and run.paths is not None:
        done = {h.get("qa_run_id") for h in io.read_own_jsonl(run.paths.history)}
        if run.qa_run_id not in done:
            io.append_jsonl(run.paths.history, entry)
    return rep


def baseline_doc(run):
    m = metrics(run)
    ctx = _ctx(run)
    return {
        "qa_run_id": run.qa_run_id,
        "labeler_run_id": run.labeler_run_id,
        "taxonomy_version": ctx.tax.version,
        "schema_version": (run.manifest or {}).get("versions", {}).get("schema") or ctx.versions.get("schema"),
        "taxonomy_values": l6_batch.active_values(ctx.tax),
        "distribution": m["distribution"],
        "answer_distribution": m["answer_distribution"],
        "unknown_rate": m["unknown_rate"],
        "coverage": m["coverage"],
        "pass_rate": m["pass_rate"],
        "counts": m["counts"],
        "records": m["records"],
        "content_records": m["content_records"],
    }


def set_baseline(run):
    """`baseline set`. 이전 기준선은 qa/baseline_<이전 검수 실행 ID>.json으로 남긴다. 반환: 새 기준선."""
    paths = run.paths
    doc = baseline_doc(run)
    prev = io.read_own_json(paths.baseline)
    if prev and prev.get("qa_run_id") and prev["qa_run_id"] != run.qa_run_id:
        io.write_json(paths.q("baseline_%s.json" % prev["qa_run_id"]), prev)
    io.write_json(paths.baseline, doc)
    return doc
