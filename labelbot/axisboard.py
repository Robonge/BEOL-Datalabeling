"""축 변경 현황판(screens/axis_update.html). axis-update 실행의 대상 축별 불량·처리 결과와 슬라이드별 새 축 값. LLM 호출 0회.

위쪽은 대상 축 카드(불량 사유별 건수, 교정·확인·남은 불량), 아래쪽은 슬라이드 카드(이미지 + 대상 축 최종 값)다.
슬라이드 이미지·근사 미리보기 배치는 slidecards가 채운다. 본문은 화면(HTML) 안에만 들어가고 출력·로그에는 건수만 쓴다.
"""
import json
import os

from labelbot import axisupdate, dashboard, finals, review, slidecards, taxdiff, util

KIND_LABELS = {"added": "추가", "changed": "변경", "values_added": "값 추가", "values_removed": "값 삭제"}
OUTCOME_LABELS = {"pending": "검수 대기", "corrected": "교정", "confirmed": "확인", "undecidable": "판단 불가",
                  "remaining": "남은 불량"}


class BoardError(Exception):
    pass


def _axis_kinds(con, info):
    """대상 축 → added|changed|values_added|values_removed. 기준 실행과 이 실행의 축 서명을 비교한다."""
    prev, _ = taxdiff.previous_signature(con, info["parent"])
    cur, _ = taxdiff.previous_signature(con, info["run_id"])
    d = taxdiff.diff(prev, cur) if isinstance(cur, list) else {}
    changed = {c["axis"]: set(c["fields"]) for c in d.get("changed") or []}
    out = {}
    for name in info["target"]:
        if name in (d.get("added") or []):
            out[name] = "added"
        elif name in info["values_added_only"]:
            out[name] = "values_added"
        elif name in (d.get("values_removed") or {}) and changed.get(name, set()) <= {"values"}:
            out[name] = "values_removed"  # 값이 빠지면 값 구성(values)도 바뀐 것으로 잡히므로 그 밖의 설정 변경만 '변경'으로 본다
        else:
            out[name] = "changed"
    return out


def _signals(ws, run_id):
    """검수 시작·완료 신호. 파일이 있는지와 완료 신호의 건수(정수)만 읽는다."""
    from labelbot.serve import done_signal_path, start_signal_path

    done = done_signal_path(ws.root, run_id)
    counts = {}
    if os.path.isfile(done):
        try:
            with open(done, encoding="utf-8") as f:
                raw = json.load(f).get("counts") or {}
            counts = {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, int)}
        except (OSError, ValueError, AttributeError):
            counts = {}
    return os.path.isfile(start_signal_path(ws.root, run_id)), os.path.isfile(done), counts


def _outcome(d, target, rows, status):
    """불량 chunk의 처리 결과(results.html과 같은 chunk 단위). rows: 이 실행의 대상 축 교정 행, status: 이 실행의 chunk 상태 값.

    재검수 필요(교정 뒤 본문이 바뀜)가 하나라도 있으면 남은 불량, 값을 바꾼 교정이 있으면 교정, 값이 같은 교정이나
    유효한 확인(확인 당시 봇 값이 지금과 같음)이면 확인, 이미지에만 정보가 있다고 했으면 판단 불가, 그 밖은 남은 불량이다.
    """
    axes = (d or {}).get("axes", {})
    if any((axes.get(r["target_key"]) or {}).get("review") == finals.RECHECK for r in rows):
        return "remaining"
    if any(dashboard._norm("axis", r["human_value"]) != dashboard._norm("axis", r["bot_value"]) for r in rows):
        return "corrected"
    if rows or (status == "confirmed" and any((axes.get(a) or {}).get("review") == finals.CONFIRMED for a in target)):
        return "confirmed"
    return "undecidable" if status == "undecidable_image" else "remaining"


def build_board(ws, con, run_id, tax):
    """screens/axis_update.html을 만든다. 반환: (경로, 대상 축 수, 슬라이드 수). axis-update 실행이 아니면 BoardError."""
    info = axisupdate.run_info(con, run_id)
    if info is None:
        raise BoardError("NOT_AXIS_UPDATE_RUN")
    target = info["target"]
    pop = sorted(review._run_population(con, run_id))
    labels = finals.final_labels(con, run_id, pop)
    flagged = {r["chunk_id"]: (json.loads(r["reason_codes"]), json.loads(r["reason_axes"] or "{}"))
               for r in con.execute("SELECT chunk_id, reason_codes, reason_axes FROM flagged_chunks WHERE run_id=?",
                                    (run_id,))}
    rows = con.execute("SELECT chunk_id, target_kind, target_key, human_value, bot_value FROM corrections"
                       " WHERE review_run_id=?", (run_id,)).fetchall()
    started, done, counts = _signals(ws, run_id)
    # 검수 완료 신호가 있으면 교정이 하나도 없어도(모두 그대로 둠) 검수 뒤로 본다.
    applied = done or any(r["chunk_id"] in flagged for r in rows)
    status = {r["chunk_id"]: json.loads(r["human_value"]) for r in rows if r["target_kind"] == "chunk"}
    axis_rows = {}
    for r in rows:
        if r["target_kind"] == "axis" and r["target_key"] in target:
            axis_rows.setdefault(r["chunk_id"], []).append(r)

    def flagged_axes(cid):
        codes, ra = flagged[cid]
        if "CLASSIFY_FAILED" in codes:
            return set(target)
        hit = {a for axes in ra.values() for a in axes if a in target}
        return hit or set(target)

    # 불량 chunk의 처리 결과. 축 카드는 그 축에서 불량이 난 chunk의 결과를 센다.
    outcome = {cid: "pending" if not applied else _outcome(labels.get(cid), target, axis_rows.get(cid, []), status.get(cid))
               for cid in flagged}
    kinds = _axis_kinds(con, info)
    cards = []
    for a in target:
        reasons = {}
        for cid, (codes, ra) in flagged.items():
            for code in codes:
                if a in (ra.get(code) or []) or code == "CLASSIFY_FAILED":
                    reasons[code] = reasons.get(code, 0) + 1
        mine = [outcome[cid] for cid in flagged if a in flagged_axes(cid)]
        cards.append({"name": a, "kind": kinds.get(a, "changed"),
                      "reasons": {code: reasons[code] for code in review.REASONS if code in reasons},
                      "flagged": len(mine), **{k: mine.count(k) for k in ("corrected", "confirmed", "undecidable", "remaining")}})
    parent = info["parent"]
    removed = [{"name": a, "dropped_rows": con.execute(
        "SELECT COUNT(*) FROM labels WHERE run_id=? AND kind='axis' AND key=?", (parent, a)).fetchone()[0]}
        for a in info["removed"]]
    slides = []
    for s in slidecards.cards(ws, con, pop):
        cid = s["chunk_id"]
        d = labels.get(cid) or {"axes": {}}
        slides.append(dict(s, values={a: list((d["axes"].get(a) or {}).get("values") or []) for a in target},
                           flagged=cid in flagged, reasons=flagged[cid][0] if cid in flagged else [],
                           outcome=outcome.get(cid)))
    data = {
        "kind": "axis_update", "run_id": run_id, "parent_run": parent, "generated_at": util.now_iso(),
        "phase": "after" if applied else "before", "review_started": started, "review_done": done,
        "review_counts": counts, "flagged": len(flagged),
        "axes_target": cards, "axes_removed": removed,
        "dropped_answers": int(info.get("dropped_answers") or 0),
        "dropped_corrections": int(info.get("dropped_corrections") or 0),
        "push": {"pushed_ok": dashboard._pushed(con, pop, labels, ws.config["embedding"]["model"]), "total": len(pop)},
        "kind_labels": KIND_LABELS, "outcome_labels": OUTCOME_LABELS, "reason_labels": review.REASON_LABELS,
        "slides": slides,
    }
    path = ws.path("screens", "axis_update.html")
    util.write_text(path, review.fill_template("axis_update.html", data))
    return path, len(cards), len(slides)
