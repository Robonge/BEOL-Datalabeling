"""결과 대시보드(screens/results.html). 한 실행의 전체 chunk 라벨과 분포를 보여 준다. LLM 호출 0회."""
import json

from labelbot import alerts, finals, review, util
from labelbot.questions import GEN_PREFIX, all_questions

ALERT_LABELS = {"NA_RATIO_LOW": "N/A 비율이 기준 이하", "DUP_LABEL_HIGH": "중복 라벨링 비율이 기준 이상"}


def build_results(ws, con, run_id, tax):
    pop = sorted(review._run_population(con, run_id))
    labels = finals.final_labels(con, run_id, pop, {q.qid: q.text for q in all_questions(con, tax)})
    flagged = {r["chunk_id"]: json.loads(r["reason_codes"])
               for r in con.execute("SELECT chunk_id, reason_codes FROM flagged_chunks WHERE run_id=?", (run_id,))}
    files = con.execute(
        "SELECT DISTINCT f.file_id, f.file_name, f.status FROM files f JOIN file_locations l ON l.file_id=f.file_id "
        "WHERE l.last_seen_run=? ORDER BY f.file_name", (run_id,)).fetchall()
    names = {f["file_id"]: f["file_name"] for f in files}
    chunks = []
    for cid in pop:
        c = con.execute("SELECT chunk_id, file_id, seq, title, text FROM chunks WHERE chunk_id=?", (cid,)).fetchone()
        if not c:
            continue
        d = labels.get(cid) or {"chunk_type": None, "axes": {}, "answers": {}, "extracted": []}
        chunks.append({
            "chunk_id": cid, "file_id": c["file_id"], "file_name": names.get(c["file_id"], ""), "slide_no": c["seq"],
            "title": c["title"], "text": c["text"], "chunk_type": d["chunk_type"],
            "axes": {k: {"values": v["values"], "status": v["status"], "evidence": v.get("evidence") or "",
                         "confidence": v.get("confidence")} for k, v in d["axes"].items()},
            "answers": {k: {"answer": v["answer"], "quote": v.get("quote") or "", "confidence": v.get("confidence")}
                        for k, v in d["answers"].items()},
            "extracted": [{"item": e["item"], "value": e["value"]} for e in d["extracted"]],
            "reasons": flagged.get(cid, []),
        })
    chunks.sort(key=lambda c: (c["file_name"], c["slide_no"]))
    axes = []
    for a in tax.axes:
        st = {"value": 0, "unknown": 0, "na": 0}
        counts = {v.name: 0 for v in a.values}
        for c in chunks:
            v = c["axes"].get(a.name)
            if not v:
                continue
            st[v["status"]] = st.get(v["status"], 0) + 1
            for x in v["values"]:
                if x in counts:
                    counts[x] += 1
        axes.append({"name": a.name, "kind": a.kind, "multi": a.multi, "active": a.active, "states": st,
                     "values": [{"name": v.name, "n": counts[v.name], "definition": v.definition or ""} for v in a.values]})
    qs = []
    for q in tax.questions:
        ans = [c["answers"][q.qid]["answer"] for c in chunks if q.qid in c["answers"]]
        qs.append({"qid": q.qid, "text": q.text, "O": ans.count("O"), "X": ans.count("X"), "NA": ans.count("N/A")})
    gen = [a["answer"] for c in chunks for qid, a in c["answers"].items() if qid.startswith(GEN_PREFIX)]
    if gen:
        qs.append({"qid": GEN_PREFIX + "*", "text": "1차 라벨 검증 질문(LLM 생성, 전체 합산). X는 1차 라벨이 본문과 어긋난 것이다",
                   "O": gen.count("O"), "X": gen.count("X"), "NA": gen.count("N/A")})
    reasons = {code: sum(1 for c in chunks if code in c["reasons"]) for code in review.REASONS}
    na_r, _ = alerts.na_ratio(con, run_id)
    dup_r, _ = alerts.dup_ratio(con, run_id, tax)
    risk = [c["answers"]["Q-COM-001"]["answer"] for c in chunks if "Q-COM-001" in c["answers"]]
    fails = {r[0]: r[1] for r in con.execute(
        "SELECT stage, COUNT(DISTINCT target_id) FROM failures WHERE run_id=? AND stage IN ('classify','label') GROUP BY stage",
        (run_id,))}
    data = {
        "kind": "results", "run_id": run_id, "generated_at": util.now_iso(), "model": ws.config["llm"]["model"],
        "kpi": {
            "files": sum(1 for f in files if f["status"] == "ok"), "failed_files": sum(1 for f in files if f["status"] != "ok"),
            "chunks": len(chunks), "content": sum(1 for c in chunks if c["chunk_type"] == "내용"),
            "classify_failed": sum(1 for c in chunks if not c["chunk_type"]),
            "label_failed": min(fails.get("label", 0), sum(1 for c in chunks if c["chunk_type"] and not c["answers"])),
            "flagged": len(flagged), "answers": len(risk), "risk_o": risk.count("O"),
            "na_ratio": na_r, "dup_ratio": dup_r,
        },
        "alerts": [dict(r) for r in con.execute("SELECT condition, value, threshold FROM alerts WHERE run_id=?", (run_id,))],
        "alert_labels": ALERT_LABELS,
        "axes": axes, "questions": qs, "reasons": reasons, "reason_labels": review.REASON_LABELS,
        "files": [{"file_id": f["file_id"], "file_name": f["file_name"],
                   "chunks": sum(1 for c in chunks if c["file_id"] == f["file_id"])} for f in files if f["status"] == "ok"],
        "chunks": chunks,
    }
    path = ws.path("screens", "results.html")
    util.write_text(path, review.fill_template("results.html", data))
    return path, len(chunks)
