"""규칙 변경 현황판(screens/rules_update.html). rules-update 실행의 규칙별 처리 건수와 값이 바뀐 슬라이드. LLM 호출 0회.

위쪽은 실행 띠(기준 실행, 변경 비율과 상한, 적재 상태, 건수)와 바뀐 규칙 카드, 아래쪽은 값이 바뀐 chunk만 슬라이드 카드
(이미지 + `이전 → 지금`)로 보인다. 사람 검수는 없으므로 검수 시작 버튼이 없다. 슬라이드 이미지·근사 배치는 slidecards가 채운다.
규칙 문장은 화면에만 짧게 넣고(사내 본문 아님) 출력·로그에는 건수만 쓴다.
"""
from labelbot import dashboard, feedback, finals, review, rulesupdate, slidecards, util

CHANGE_LABELS = {"added": "추가", "edited": "수정", "disabled": "끄기", "removed": "기각"}
TEXT_MAX = 120


class BoardError(Exception):
    pass


def _rule_texts(ws):
    """규칙 ID → 짧은 문장(지금 승인 파일). 파일을 못 읽으면 빈 dict(기각된 규칙은 문장이 없다)."""
    try:
        doc = feedback.load_rules(ws)
    except (feedback.FeedbackError, OSError):
        return {}
    out = {}
    for r in doc["rules"]:
        if isinstance(r, dict) and isinstance(r.get("rule_id"), str) and isinstance(r.get("text"), str):
            t = " ".join(r["text"].split())
            out[r["rule_id"]] = t if len(t) <= TEXT_MAX else t[:TEXT_MAX - 1] + "…"
    return out


def _push(ws, con, run_id, pop, labels, blocked):
    """적재 상태: off(Supabase 꺼짐·URL 없음) | pushed(적재 대상 모두 올라감) | blocked(변경 비율 상한) | pending(미적재)."""
    from labelbot import vectorpush

    pushed = dashboard._pushed(con, pop, labels, ws.config["embedding"]["model"])
    if not (ws.config.get("supabase") or {}).get("enabled") or not ws.supabase_url():
        state = "off"
    elif not vectorpush.unpushed(ws, con, run_id):
        state = "pushed"
    else:
        state = "blocked" if blocked else "pending"
    return {"state": state, "pushed_ok": pushed, "total": len(pop),
            "code": rulesupdate.RULES_CHANGE_RATIO_HIGH if state == "blocked" else None}


def build_board(ws, con, run_id, tax):
    """screens/rules_update.html을 만든다. 반환: (경로, 규칙 카드 수, 슬라이드 수). rules-update 실행이 아니면 BoardError."""
    info = rulesupdate.run_info(con, run_id)
    if info is None:
        raise BoardError("NOT_RULES_UPDATE_RUN")
    pop = sorted(review._run_population(con, run_id))
    labels = finals.final_labels(con, run_id, pop)
    blocked, ratio, limit = rulesupdate.blocked(ws, info)
    texts = _rule_texts(ws)
    rules = [{"rule_id": r["rule_id"], "change": r["change"], "kind": r.get("kind"), "stage": r.get("stage"),
              "target": r.get("target"), "axes": list(r.get("axes") or []), "keys": list(r.get("keys") or []),
              "relabeled": int(r.get("relabeled") or 0), "changed": int(r.get("changed") or 0),
              "skipped_human": int(r.get("skipped_human") or 0), "skipped_missing": int(r.get("skipped_missing") or 0),
              "text": texts.get(r["rule_id"], "")}
             for r in info.get("rules") or [] if r.get("axes") or r.get("keys")]  # 축 없는 규칙은 한 줄 건수로만
    by_chunk = {}
    for c in rulesupdate.changes(con, run_id):
        by_chunk.setdefault(c["chunk_id"], []).append(
            {"kind": c["kind"], "key": c["key"], "before": c["before"], "after": c["after"], "stale": bool(c["stale"])})
    slides = [dict(s, changes=by_chunk[s["chunk_id"]]) for s in slidecards.cards(ws, con, list(by_chunk))]
    data = {
        "kind": "rules_update", "run_id": run_id, "parent_run": info.get("parent"), "baseline": info.get("baseline"),
        "generated_at": util.now_iso(),
        "ratio": {"changed": int(info.get("changed") or 0), "relabeled": int(info.get("relabeled") or 0),
                  "ratio": ratio, "limit": limit, "min_relabels": int(info.get("min_relabels") or 0), "blocked": blocked},
        "push": _push(ws, con, run_id, pop, labels, blocked),
        "counts": {k: int(info.get(k) or 0) for k in ("relabeled", "changed", "skipped_human", "skipped_confirmed",
                                                       "skipped_missing", "stale_answers", "unasked_questions", "failed")},
        "rules": rules, "stage_wide": int(info.get("stage_wide") or 0),
        "examples_changed": int(info.get("examples_changed") or 0),
        "change_labels": CHANGE_LABELS, "slides": slides,
    }
    path = ws.path("screens", "rules_update.html")
    util.write_text(path, review.fill_template("rules_update.html", data))
    return path, len(rules), len(slides)
