"""확정 라벨: 그 실행의 봇 값에 사람 교정을 덮어쓴다. 사람 값은 재실행해도 덮어쓰지 않는다."""
import json

from labelbot import runchain, util

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


def applies(r, chain):
    """부분 실행(chain[0])과 그 조상 부분 실행(axis-update·rules-update)이 이 축 교정을 버렸는지(D5).
    각 실행 자신의 검수 교정은 남긴다. rules-update는 버리는 축이 없어 조상의 판단을 그대로 잇는다."""
    if r["target_kind"] != "axis":
        return True
    if r["target_key"] not in chain[0]["axes"]:
        return False  # 그 실행이 라벨링하지 않은 축(삭제 축)은 교정으로 되살리지 않는다
    for info in chain:
        if r["review_run_id"] == info["run_id"]:
            return True
        if r["target_key"] in runchain.dropped_axes(info):
            return False
    return True


def corrections(con, chunk_ids=None, run_id=None):
    """chunk별 최신 교정. {chunk_id: {(kind, key): row}}

    run_id가 부분 실행이면 그 실행(과 조상 부분 실행)이 버린 삭제·변경 축의 이전 교정과
    그 실행에 없는 축의 교정은 뺀다. 행은 DB에 그대로 남는다.
    """
    chain = runchain.chain(con, run_id)
    rows = con.execute("SELECT * FROM corrections ORDER BY applied_at, review_run_id").fetchall()
    out = {}
    for r in rows:
        if chunk_ids is not None and r["chunk_id"] not in chunk_ids:
            continue
        if chain and not applies(r, chain):
            continue
        out.setdefault(r["chunk_id"], {})[(r["target_kind"], r["target_key"])] = r
    return out


def final_labels(con, run_id, chunk_ids=None, question_texts=None):
    """question_texts({질문 ID: 현재 문장})를 주면 질문 문장이 바뀐 교정도 재검수로 표시한다.

    부분 실행(axis-update·rules-update)이면 이전 실행의 확인은 대상 축을 뺀 축·남긴 답에만 이어받고(D6), 이전 답
    교정은 이어받은 답에만 적용한다(D4로 버린 답을 되살리지 않는다). 대상 축은 그 실행 자신의 검수로만 확인된다.
    rules-update는 대상 축이 없어 이어받은 확인 해시가 모든 축·답에 걸린다.
    """
    info = runchain.run_info(con, run_id)
    bots = bot_labels(con, run_id, chunk_ids)
    corr = corrections(con, None if chunk_ids is None else set(chunk_ids), run_id)
    inherited = {}
    if info:
        inherited = {cid: h for cid, h in info["confirmed"].items() if cid in bots}
    for cid in sorted(set(corr) | set(inherited)):
        items = corr.get(cid, {})
        d = bots.setdefault(cid, {"chunk_type": "내용", "axes": {}, "answers": {}, "extracted": []})
        cur = con.execute("SELECT text_hash FROM chunks WHERE chunk_id=?", (cid,)).fetchone()
        st = items.get(("chunk", "status"))
        # 확인은 그때의 봇 값이 지금과 같을 때만 유효하다. axis-update 실행 자신의 확인은 대상 축에만,
        # rules-update 실행 자신의 확인은 모든 축·답에 적용한다(대상 축이 없다).
        confirmed = bool(st) and st["human_value"] == '"confirmed"' and bool(d["axes"]) \
            and st["bot_value"] == util.dumps(label_hash(d)) and (info is None or st["review_run_id"] == run_id)
        if confirmed:
            for k, a in list(d["axes"].items()) + list(d["answers"].items()):
                if info is None or info["command"] != "axis-update" or k in info["target"]:
                    a["review"] = CONFIRMED
        if info and cid in inherited and inherited[cid] == confirm_hash(d, info["target"]):
            for k, a in list(d["axes"].items()) + list(d["answers"].items()):
                if k not in info["target"]:
                    a["review"] = CONFIRMED
        for (kind, key), r in items.items():
            if info and kind == "answer" and key not in d["answers"] and r["review_run_id"] != run_id:
                continue
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


def incomplete(con, run_id, labels):
    """부분 실행 체인에서 axis-update 대상 축을 아직 못 채운 chunk ID 집합(확정 값, 사람 교정 포함 기준).

    need는 run_id부터 마지막 보통 실행까지 체인의 axis-update 대상 축 합집합(그 실행이 라벨하는 축만)이다.
    axis-update에서 부분 분류에 실패한 chunk는 뒤에 rules-update를 거쳐도(실패 기록이 바뀌어도) 그 축이 채워질
    때까지 여기 남는다. 적재(vectorpush)·내보내기(export)는 이 chunk를 분류 실패 chunk처럼 뺀다.
    """
    chain = runchain.chain(con, run_id)
    if not chain:
        return set()
    need = set().union(*[set(i["target"]) for i in chain if i["command"] == "axis-update"]) & set(chain[0]["axes"])
    if not need:
        return set()
    return {cid for cid, d in labels.items() if d.get("chunk_type") and not need <= set(d["axes"])}


def label_hash(d):
    """{축: 정렬한 값 목록, 질문 ID: 답}만 넣은 JSON의 sha256. 확신도·근거·검수 상태·시각은 넣지 않는다."""
    obj = {k: sorted(v["values"]) for k, v in d["axes"].items()}
    obj.update({k: v["answer"] for k, v in d["answers"].items()})
    return util.hash_obj(obj)


def confirm_hash(d, skip_axes):
    """axis-update의 확인 해시: skip_axes(대상 축)를 뺀 축과 답으로 label_hash와 같게 계산한다(앞 16자)."""
    return label_hash({"axes": {k: v for k, v in d["axes"].items() if k not in skip_axes},
                       "answers": d["answers"]})[:16]
