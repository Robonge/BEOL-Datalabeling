"""결과 대시보드(screens/results.html). 한 실행의 전체 chunk 라벨과 분포를 보여 준다. LLM 호출 0회."""
import json

from labelbot import alerts, finals, review, util
from labelbot.questions import CTL_PREFIX, GEN_PREFIX, all_questions

ALERT_LABELS = {"NA_RATIO_LOW": "N/A 비율이 기준 이하", "DUP_LABEL_HIGH": "중복 라벨링 비율이 기준 이상"}


# 검수 반영 뒤 불량 chunk 처리 결과. 앞쪽이 우선한다(재검수 필요가 하나라도 있으면 그 chunk는 아직 남은 불량이다).
OUTCOMES = ("recheck", "corrected", "confirmed", "undecidable", "unreviewed")
OUTCOME_LABELS = {"recheck": "재검수 필요", "corrected": "사람이 교정", "confirmed": "사람이 확인",
                  "undecidable": "판단 불가", "unreviewed": "검수하지 않음"}
REMAINING = ("recheck", "unreviewed")


def _norm(kind, raw):
    v = json.loads(raw) if raw else None
    if kind == "axis":
        return sorted(v if isinstance(v, list) else [] if v is None else [v])
    return v


def _outcome(d, status, edits, changes):
    """edits: 이 실행의 축·질문 교정 행 수, changes: 그중 값이 실제로 바뀐 수."""
    reviews = {a.get("review") for a in list(d["axes"].values()) + list(d["answers"].values())}
    if finals.RECHECK in reviews:
        return "recheck"
    if finals.CORRECTED in reviews:
        # 교정 행이 있어도 값이 모두 봇과 같으면 사실상 확인이다
        return "confirmed" if edits and not changes else "corrected"
    if finals.CONFIRMED in reviews:
        return "confirmed"
    if status == "confirmed":
        return "recheck"  # 확인 뒤 봇 값이 바뀌어 확인이 무효가 됐다
    if status == "undecidable_image":
        return "undecidable"
    return "unreviewed"


def _pushed(con, pop, labels, model):
    """확정 라벨(사람 교정 반영) 그대로 Supabase에 올라간 chunk 수. push-vectors와 같은 label_hash로 본다."""
    from labelbot.vectorpush import load_doc_meta, push_label_hash

    doc_meta, n = load_doc_meta(con), 0
    for c in pop:
        d, row = labels.get(c), con.execute("SELECT file_id, text_hash FROM chunks WHERE chunk_id=?", (c,)).fetchone()
        if not d or not d["chunk_type"] or not row:
            continue
        lh = push_label_hash(d, doc_meta.get(row["file_id"]))
        n += bool(con.execute("SELECT 1 FROM vector_push_log WHERE chunk_id=? AND model=? AND text_hash=? AND label_hash=?"
                              " AND result_code='OK'", (c, model, row["text_hash"], lh)).fetchone())
    return n


def build_review(con, run_id, pop, labels, flagged, qtext, model=None):
    """검수 전(봇 불량 목록)과 검수 후(사람 처리 결과)를 비교할 건수. 교정이 없으면 applied=False만 낸다."""
    rows = con.execute("SELECT chunk_id, target_kind, target_key, human_value, bot_value, evidence, applied_at "
                       "FROM corrections WHERE review_run_id=?", (run_id,)).fetchall()
    rows = [r for r in rows if r["chunk_id"] in flagged]
    if not rows:
        return {"applied": False}, {}
    status = {r["chunk_id"]: json.loads(r["human_value"]) for r in rows if r["target_kind"] == "chunk"}
    edits = [r for r in rows if r["target_kind"] in ("axis", "answer")]
    changed = [r for r in edits if _norm(r["target_kind"], r["human_value"]) != _norm(r["target_kind"], r["bot_value"])]
    n_edits, per_chunk = {}, {}
    for r in edits:
        n_edits[r["chunk_id"]] = n_edits.get(r["chunk_id"], 0) + 1
    for r in changed:
        per_chunk[r["chunk_id"]] = per_chunk.get(r["chunk_id"], 0) + 1
    empty = {"axes": {}, "answers": {}}
    outcome = {cid: _outcome(labels.get(cid) or empty, status.get(cid), n_edits.get(cid, 0), per_chunk.get(cid, 0))
               for cid in flagged}
    bots = finals.bot_labels(con, run_id, pop)
    # 봇 정답률은 사람이 값을 보고 판단한 chunk(교정·확인)만 센다. 봇에 없던 키를 사람이 더한 것은 따로 센다.
    judged = {cid for cid in flagged if outcome[cid] in ("corrected", "confirmed")}
    n_labels = sum(len((bots.get(c) or empty)["axes"]) + len((bots.get(c) or empty)["answers"]) for c in judged)
    added = [r for r in changed if r["chunk_id"] in judged and json.loads(r["bot_value"] or "null") is None]
    wrong = sum(1 for r in changed if r["chunk_id"] in judged) - len(added)
    remaining = [cid for cid in flagged if outcome[cid] in REMAINING]

    def by_reason(cids):
        return {code: sum(1 for c in cids if code in flagged[c]) for code in review.REASONS}

    def unknown(src):
        return sum(1 for d in src.values() for a in d["axes"].values() if a["status"] == "unknown")

    # 생성 검증 질문(Q-GEN-)은 chunk마다 ID가 달라 그대로 세면 1건씩 흩어진다. 검증한 축으로 묶는다.
    gen_axis = {r[0]: r[1] for r in con.execute("SELECT qid, axis FROM gen_questions")}
    top = {}
    for r in changed:
        k = (r["target_kind"], r["target_key"])
        if r["target_kind"] == "answer" and r["target_key"] in gen_axis:
            k = ("gen", gen_axis[r["target_key"]] or "")
        top[k] = top.get(k, 0) + 1
    marks = ",".join("?" * len(pop))
    embedded = con.execute(
        "SELECT COUNT(DISTINCT e.chunk_id) FROM chunk_embeddings e JOIN chunks c ON c.chunk_id=e.chunk_id "
        "AND c.text_hash=e.text_hash WHERE e.model=? AND e.chunk_id IN (%s)" % marks, [model] + pop).fetchone()[0] if pop else 0
    n_changed = len(changed)
    data = {
        "applied": True,
        "applied_at": max(r["applied_at"] or "" for r in rows),
        "outcome_labels": OUTCOME_LABELS,
        "outcomes": {o: sum(1 for c in flagged if outcome[c] == o) for o in OUTCOMES},
        "before": {"flagged": len(flagged), "by_reason": by_reason(list(flagged))},
        "after": {"remaining": len(remaining), "by_reason": by_reason(remaining)},
        "labels": {"judged_chunks": len(judged), "bot_labels": n_labels, "wrong": wrong, "added": len(added),
                   "changed": n_changed,
                   "axis": sum(1 for r in changed if r["target_kind"] == "axis"),
                   "answer": sum(1 for r in changed if r["target_kind"] == "answer")},
        "unknown": {"before": unknown({c: bots[c] for c in pop if c in bots}), "after": unknown(labels)},
        "top_changed": [{"kind": k, "key": key, "text": qtext.get(key, "") if k == "answer" else "", "n": n}
                        for (k, key), n in sorted(top.items(), key=lambda x: (-x[1], x[0]))[:8]],
        "evidence": {"with": sum(1 for r in changed if r["evidence"]), "total": n_changed},
        "handoff": {
            "embedded": embedded,
            "pushed": _pushed(con, pop, labels, model),
            "revisits": con.execute("SELECT COUNT(*) FROM revisit_requests WHERE review_run_id=?", (run_id,)).fetchone()[0],
            "synonyms": con.execute("SELECT COUNT(DISTINCT content) FROM candidates WHERE source='review' AND run_id=?",
                                    (run_id,)).fetchone()[0],
        },
    }
    return data, {cid: {"outcome": outcome[cid], "changes": per_chunk.get(cid, 0)} for cid in flagged}


def build_results(ws, con, run_id, tax):
    pop = sorted(review._run_population(con, run_id))
    qtext = {q.qid: q.text for q in all_questions(con, tax)}
    labels = finals.final_labels(con, run_id, pop, qtext)
    flagged = {r["chunk_id"]: json.loads(r["reason_codes"])
               for r in con.execute("SELECT chunk_id, reason_codes FROM flagged_chunks WHERE run_id=?", (run_id,))}
    files = con.execute(
        "SELECT DISTINCT f.file_id, f.file_name, f.status FROM files f JOIN file_locations l ON l.file_id=f.file_id "
        "WHERE l.last_seen_run=? ORDER BY f.file_name", (run_id,)).fetchall()
    names = {f["file_id"]: f["file_name"] for f in files}
    rev, per_chunk = build_review(con, run_id, pop, labels, flagged, qtext, ws.config["embedding"]["model"])
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
            **per_chunk.get(cid, {}),
        })
    chunks.sort(key=lambda c: (c["file_name"], c["slide_no"]))
    # 실행 뒤 taxonomy에 더해진 활성 축은 이 실행에 값이 없다(pending: 다음 실행부터). 실행 축을 모르면 비워 둔다.
    ran = review.run_axes(con, run_id)
    new_axes = [a.name for a in tax.axes if a.active and ran is not None and a.name not in ran]
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
                     "pending": a.name in new_axes,
                     "values": [{"name": v.name, "n": counts[v.name], "definition": v.definition or ""} for v in a.values]})
    qs = []
    for q in tax.questions:
        ans = [c["answers"][q.qid]["answer"] for c in chunks if q.qid in c["answers"]]
        qs.append({"qid": q.qid, "text": q.text, "O": ans.count("O"), "X": ans.count("X"), "NA": ans.count("N/A")})
    gen = [a["answer"] for c in chunks for qid, a in c["answers"].items() if qid.startswith(GEN_PREFIX)]
    if gen:
        qs.append({"qid": GEN_PREFIX + "*", "text": "1차 라벨 검증 질문(LLM 생성, 전체 합산). X는 1차 라벨이 본문과 어긋난 것이다",
                   "O": gen.count("O"), "X": gen.count("X"), "NA": gen.count("N/A")})
    ctl = [r[0] for r in con.execute("SELECT value FROM labels WHERE run_id=? AND kind='control'", (run_id,))]
    if ctl:
        qs.append({"qid": CTL_PREFIX + "*", "text": "대조 질문(붙지 않은 라벨, 전체 합산). O는 1차 분류 누락이나 3차 과잉 판정 신호다",
                   "O": ctl.count("O"), "X": ctl.count("X"), "NA": ctl.count("N/A")})
    reasons = {code: sum(1 for c in chunks if code in c["reasons"]) for code in review.REASONS}
    na_r, _ = alerts.na_ratio(con, run_id)
    dup_r, _ = alerts.dup_ratio(con, run_id, tax)
    pq = review.primary_qid(tax)  # questions 시트의 첫 공통 질문. 없으면 BEOL 연관 집계는 0건이다
    risk = [c["answers"][pq]["answer"] for c in chunks if pq in c["answers"]]
    fails = {r[0]: r[1] for r in con.execute(
        "SELECT stage, COUNT(DISTINCT target_id) FROM failures WHERE run_id=? AND stage IN ('classify','label') GROUP BY stage",
        (run_id,))}
    data = {
        "kind": "results", "run_id": run_id, "generated_at": util.now_iso(), "model": ws.config["llm"]["model"],
        "flag": ws.config["flag"],  # 축 상태 도넛에서 unknown 강조 기준(unknown_ratio_min)으로 쓴다
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
        "axes": axes, "new_axes": new_axes, "primary_qid": pq,
        "questions": qs, "reasons": reasons, "reason_labels": review.REASON_LABELS,
        "files": [{"file_id": f["file_id"], "file_name": f["file_name"],
                   "chunks": sum(1 for c in chunks if c["file_id"] == f["file_id"])} for f in files if f["status"] == "ok"],
        "chunks": chunks,
        "review": rev,
    }
    path = ws.path("screens", "results.html")
    util.write_text(path, review.fill_template("results.html", data))
    return path, len(chunks)
