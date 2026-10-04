"""기준선 리포트(reports/baseline_<실행ID>.md). 분포만 내고 정확도 지표는 내지 않는다. LLM 호출 0회.

본문, 파일명, 경로는 넣지 않는다(파일 ID와 수치만).
"""
import json

from labelbot import alerts, finals, review, util

NA, UNK = "해당 없음", "unknown"


def _pct(n, d):
    return "%.1f%%" % (100.0 * n / d) if d else "-"


def write_report(ws, con, run_id, tax, stats=None):
    pop = sorted(review._run_population(con, run_id))
    bots = finals.bot_labels(con, run_id, pop)
    content = [c for c, d in bots.items() if d["chunk_type"] == "내용"]
    flagged = [json.loads(r[0]) for r in con.execute("SELECT reason_codes FROM flagged_chunks WHERE run_id=?", (run_id,))]
    failed_files = con.execute(
        "SELECT f.file_id, f.reason_code FROM files f JOIN file_locations l ON l.file_id=f.file_id "
        "WHERE f.status='failed' AND l.last_seen_run=? GROUP BY f.file_id", (run_id,)).fetchall()
    fail_cnt = {}
    for r in con.execute("SELECT stage, reason_code, COUNT(*) FROM failures WHERE run_id=? GROUP BY stage, reason_code", (run_id,)):
        fail_cnt[(r[0], r[1])] = r[2]
    cls_failed = sum(1 for cid in pop if cid not in bots or not bots[cid]["chunk_type"])
    lab_failed = len({r[0] for r in con.execute(
        "SELECT target_id FROM failures WHERE run_id=? AND stage='label'", (run_id,))} - {c for c in bots if bots[c]["answers"]})
    dup_chunks = con.execute(
        "SELECT COUNT(*) FROM chunks WHERE dup_group IS NOT NULL AND chunk_id IN (%s)" % ",".join("?" * len(pop)), pop
    ).fetchone()[0] if pop else 0
    n_corr = con.execute("SELECT COUNT(*) FROM corrections WHERE review_run_id=?", (run_id,)).fetchone()[0]
    na_r, na_n = alerts.na_ratio(con, run_id)
    dup_r, dup_n = alerts.dup_ratio(con, run_id, tax)
    al = con.execute("SELECT condition, value, threshold FROM alerts WHERE run_id=?", (run_id,)).fetchall()
    L = ["# 기준선 리포트", "", "- 실행 ID: %s" % run_id, "- 생성: %s" % util.now_iso(), "",
         "## 요약", "",
         "- 대상 chunk %d개, 내용 chunk %d개, 불량 chunk %d개(%s)" % (len(pop), len(content), len(flagged), _pct(len(flagged), len(pop))),
         "- 사유 코드별 불량: " + ", ".join("%s %d(%s)" % (c, sum(1 for f in flagged if c in f), _pct(sum(1 for f in flagged if c in f), len(pop)))
                                       for c in review.REASONS),
         "- 실패 chunk: 분류 %d, 라벨 %d / 실패 파일 %d" % (cls_failed, lab_failed, len(failed_files)),
         "- dup_group 중복 비율: %s" % _pct(dup_chunks, len(pop)),
         "- 교정 건수: %s" % (n_corr if n_corr else "검수 없음"),
         "- N/A 비율: %s (답 %d개), 중복 라벨링 비율: %s (라벨 %d개)" % (
             "-" if na_r is None else "%.1f%%" % (na_r * 100), na_n, "-" if dup_r is None else "%.1f%%" % (dup_r * 100), dup_n),
         "- H5 알림: %s" % (", ".join("%s=%s(기준 %s)" % tuple(a) for a in al) if al else "없음"),
         ""]
    L += ["## 축별 unknown 비율 (unknown / (전체 − 해당 없음))", "", "| 축 | 종류 | unknown | 분모 | 비율 |", "|---|---|---|---|---|"]
    for a in tax.axes:
        if not a.active:
            L.append("| %s | %s | - | - | 비활성 |" % (a.name, a.kind))
            continue
        labs = [bots[c]["axes"][a.name] for c in bots if a.name in bots[c]["axes"]]
        den = [x for x in labs if x["status"] != "na"]
        unk = sum(1 for x in den if x["status"] == "unknown")
        L.append("| %s | %s | %d | %d | %s |" % (a.name, a.kind, unk, len(den), _pct(unk, len(den))))
    L += ["", "## 값별 사용 빈도 (1% 미만: 합칠 후보, 50% 초과: 쪼갤 후보)", "", "| 축 | 값 | 건수 | 비율 | 표시 |", "|---|---|---|---|---|"]
    total = len(bots) or 1
    for a in tax.axes:
        if not a.active:
            continue
        for v in a.values:
            n = sum(1 for c in bots if v.name in (bots[c]["axes"].get(a.name) or {}).get("values", []))
            mark = "합칠 후보" if n / total < 0.01 else ("쪼갤 후보" if n / total > 0.5 else "")
            L.append("| %s | %s | %d | %s | %s |" % (a.name, v.name, n, _pct(n, total), mark))
    L += ["", "## 질문별 O/X/N/A 분포", "", "| 질문 | O | X | N/A | n | 표시 |", "|---|---|---|---|---|---|"]
    for q in tax.questions:
        ans = [bots[c]["answers"][q.qid]["answer"] for c in bots if q.qid in bots[c]["answers"]]
        n = len(ans)
        na = ans.count("N/A")
        mark = "N/A 편중" if n >= 20 and (na / n >= 0.95 or na / n <= 0.05) else ""
        L.append("| %s | %d | %d | %d | %d | %s |" % (q.qid, ans.count("O"), ans.count("X"), na, n, mark))
    if stats and stats.get("truncated"):
        L += ["", "질문 상한 절단 횟수: " + ", ".join("%s %d" % kv for kv in sorted(stats["truncated"].items()))]
    syn_hit = 0
    from labelbot.synonyms import SynonymTable

    syn = SynonymTable(tax.synonyms)
    for cid in pop:
        r = con.execute("SELECT text FROM chunks WHERE chunk_id=?", (cid,)).fetchone()
        if r and syn.match(r[0]):
            syn_hit += 1
    cands = con.execute("SELECT kind, COUNT(DISTINCT content) FROM candidates WHERE run_id=? GROUP BY kind", (run_id,)).fetchall()
    marks = con.execute("SELECT status, COUNT(*) FROM compare_marks GROUP BY status").fetchall()
    L += ["", "## 후보와 동의어 시트", "",
          "- synonyms 시트 항목 수: %d, 항목이 일치한 chunk 비율: %s" % (len(tax.synonyms), _pct(syn_hit, len(pop))),
          "- 후보 수: " + (", ".join("%s %d" % tuple(r) for r in cands) or "0"), "",
          "## 파싱 대조", "",
          "- 대조 기록: " + (", ".join("%s %d" % tuple(r) for r in marks) or "없음"), "",
          "## 실패 목록 (단계, 사유 코드, 건수)", ""]
    L += ["- %s %s %d" % (k[0], k[1], v) for k, v in sorted(fail_cnt.items())] or ["- 없음"]
    L += ["", "실패 파일: " + (", ".join("%s(%s)" % (r[0][:16], r[1]) for r in failed_files) or "없음"), "",
          "## 조회 검증", "", "- PoC 단계에서는 실행하지 않았다(querycheck 미구현).", ""]
    path = ws.path("reports", "baseline_%s.md" % run_id)
    util.write_text(path, "\n".join(L))
    return path
