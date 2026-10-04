"""확정 라벨: 그 실행의 봇 값에 사람 교정을 덮어쓴다. 사람 값은 재실행해도 덮어쓰지 않는다."""
import json

from labelbot import util

UNREVIEWED = "검수하지 않음"
CONFIRMED = "사람이 확인"
CORRECTED = "사람이 교정"
RECHECK = "사람이 교정(재검수 필요)"


def bot_labels(con, run_id, chunk_ids=None):
    """{chunk_id: {"chunk_type", "axes": {...}, "answers": {...}, "extracted": [...]}}"""
    q = "SELECT chunk_id, kind, key, value, status, evidence, confidence FROM labels WHERE run_id=?"
    args = [run_id]
    if chunk_ids is not None:
        if not chunk_ids:
            return {}
        q += " AND chunk_id IN (%s)" % ",".join("?" * len(chunk_ids))
        args += list(chunk_ids)
    out = {}
    for r in con.execute(q + " ORDER BY id", args):
        d = out.setdefault(r["chunk_id"], {"chunk_type": None, "axes": {}, "answers": {}, "extracted": []})
        if r["kind"] == "chunk_type":
            d["chunk_type"] = r["value"]
        elif r["kind"] == "axis":
            d["axes"][r["key"]] = {"values": json.loads(r["value"]), "status": r["status"],
                                   "evidence": r["evidence"] or "", "confidence": r["confidence"]}
        elif r["kind"] == "answer":
            d["answers"][r["key"]] = {"answer": r["value"], "quote": r["evidence"] or "", "confidence": r["confidence"]}
        elif r["kind"] == "extract":
            d["extracted"].append({"item": r["key"], "value": r["value"], "quote": r["evidence"] or "", "flag": r["status"]})
    return out


def corrections(con, chunk_ids=None):
    """chunk별 최신 교정. {chunk_id: {(kind, key): row}}"""
    rows = con.execute("SELECT * FROM corrections ORDER BY applied_at, review_run_id").fetchall()
    out = {}
    for r in rows:
        if chunk_ids is not None and r["chunk_id"] not in chunk_ids:
            continue
        out.setdefault(r["chunk_id"], {})[(r["target_kind"], r["target_key"])] = r
    return out


def final_labels(con, run_id, chunk_ids=None, question_texts=None):
    """question_texts({질문 ID: 현재 문장})를 주면 질문 문장이 바뀐 교정도 재검수로 표시한다."""
    bots = bot_labels(con, run_id, chunk_ids)
    corr = corrections(con, None if chunk_ids is None else set(chunk_ids))
    for cid, items in corr.items():
        d = bots.setdefault(cid, {"chunk_type": "내용", "axes": {}, "answers": {}, "extracted": []})
        cur = con.execute("SELECT text_hash FROM chunks WHERE chunk_id=?", (cid,)).fetchone()
        st = items.get(("chunk", "status"))
        # 확인은 그때의 봇 값이 지금과 같을 때만 유효하다.
        confirmed = bool(st) and st["human_value"] == '"confirmed"' and bool(d["axes"]) \
            and st["bot_value"] == util.dumps(label_hash(d))
        if confirmed:
            for a in list(d["axes"].values()) + list(d["answers"].values()):
                a["review"] = CONFIRMED
        for (kind, key), r in items.items():
            val = json.loads(r["human_value"])
            recheck = bool(r["recheck"]) or bool(cur is not None and r["text_hash"] and cur[0] != r["text_hash"])
            if kind == "answer" and question_texts is not None and r["question_hash"]:
                recheck = recheck or util.sha256_text(question_texts.get(key, ""))[:16] != r["question_hash"]
            status_label = RECHECK if recheck else CORRECTED
            if kind == "axis":
                vals = val if isinstance(val, list) else [val]
                status = "value"
                if vals == ["해당 없음"]:
                    status = "na"
                elif vals in (["unknown"], ["판단 불가"]):
                    status = "unknown"
                d["axes"][key] = dict(d["axes"].get(key, {}), values=vals, status=status, review=status_label)
            elif kind == "answer":
                d["answers"][key] = dict(d["answers"].get(key, {"quote": "", "confidence": None}), answer=val, review=status_label)
    for d in bots.values():
        for a in list(d["axes"].values()) + list(d["answers"].values()):
            a.setdefault("review", UNREVIEWED)
    return bots


def label_hash(d):
    """{축: 정렬한 값 목록, 질문 ID: 답}만 넣은 JSON의 sha256. 확신도·근거·검수 상태·시각은 넣지 않는다."""
    obj = {k: sorted(v["values"]) for k, v in d["axes"].items()}
    obj.update({k: v["answer"] for k, v in d["answers"].items()})
    return util.hash_obj(obj)
