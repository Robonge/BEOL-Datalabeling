"""로컬 RAG 저장소 적재(python -m labelbot push-vectors). 저장소(labelbot/localstore.py)는 사본이다.

vector_push_log로 멱등을 보장한다. 같은 저장소(target_hash)에 같은 chunk·모델·text_hash·label_hash가 성공으로 있으면 보내지 않는다.
파일명(file_name 열)은 넣고 경로는 넣지 않는다. 적재 대상별 부분(행 형식, 저장)은 LocalSink 하나에 모은다.
"""
import json
import sqlite3

from labelbot import finals, localstore, store, util
from labelbot.embed import run_chunks, unpack
from labelbot.llm import CallFailed


class LocalSink:
    def __init__(self, root):
        self.root = root

    def send(self, rows):
        try:
            con = localstore.connect(self.root)
            try:
                localstore.upsert_rows(con, rows)
            finally:
                con.close()
        except (OSError, sqlite3.Error):
            raise CallFailed("LOCAL_STORE_ERROR")

    @staticmethod
    def row(c, model, vec, labels, run_id, file_name=None):
        return {
            "chunk_id": c["chunk_id"], "file_id": c["file_id"], "file_name": file_name, "seq": c["seq"], "model": model,
            "dim": len(vec), "embedding": list(vec), "content": c["text"],
            "labels": labels, "run_id": run_id, "updated_at": util.now_iso(),
        }


def push_label_hash(d, doc_meta=None, file_name=None):
    """vector_push_log의 label_hash. doc_meta·파일명이 바뀌면 다시 보내도록 함께 해시한다."""
    lh = finals.label_hash(d)
    if file_name is not None:
        return util.hash_obj([lh, doc_meta, file_name])
    return util.hash_obj([lh, doc_meta]) if doc_meta is not None else lh


def load_doc_meta(con):
    return {r[0]: json.loads(r[1]) for r in con.execute("SELECT file_id, doc_meta FROM files WHERE doc_meta IS NOT NULL")}


def load_file_names(con):
    return {r[0]: r[1] for r in con.execute("SELECT file_id, file_name FROM files")}


def _pushable(con, run_id, labels):
    """적재할 chunk ID. 분류·라벨 실패 chunk와 axis-update 부분 분류 미완 chunk(finals.incomplete)는 뺀다."""
    lab_failed = {r[0] for r in con.execute("SELECT target_id FROM failures WHERE run_id=? AND stage='label'", (run_id,))}
    bad = finals.incomplete(con, run_id, labels)
    return {cid for cid, d in labels.items()
            if d["chunk_type"] and not (cid in lab_failed and not d["answers"]) and cid not in bad}


def unpushed(ws, con, run_id):
    """적재 대상인데 지금 확정 라벨(label_hash)로 이 저장소에 OK 기록이 없는 chunk 수. vector_store가 꺼져 있으면 0.

    임베딩이 아직 없는 chunk도 적재 전으로 센다. chunk는 file_locations가 아니라 그 실행의 라벨 행으로 고른다.
    확정 라벨은 실행 전체로 한 번 읽고(IN 목록 없음), OK 기록도 한 번의 쿼리로 메모리에 올려 비교한다.
    저장소가 아직 없으면 만들지 않고 모두 미적재로 센다.
    """
    vs = ws.config.get("vector_store") or {}
    if not vs.get("enabled"):
        return 0
    root, target = localstore.store_root(vs), None
    if localstore.exists(root):
        lcon = localstore.connect(root)
        try:
            target = localstore.target_hash(lcon)
        finally:
            lcon.close()
    model = ws.config["embedding"]["model"]
    rows = {r[0]: (r[1], r[2]) for r in con.execute(
        "SELECT c.chunk_id, c.file_id, c.text_hash FROM labels l JOIN chunks c ON c.chunk_id=l.chunk_id"
        " WHERE l.run_id=? AND l.kind='chunk_type'", (run_id,))}
    labels = {cid: d for cid, d in finals.final_labels(con, run_id).items() if cid in rows}
    doc_meta, names = load_doc_meta(con), load_file_names(con)
    done = {tuple(r) for r in con.execute(
        "SELECT chunk_id, text_hash, label_hash FROM vector_push_log WHERE model=? AND target_host_hash=?"
        " AND result_code='OK'", (model, target))}
    return sum(1 for cid in _pushable(con, run_id, labels)
               if (cid, rows[cid][1], push_label_hash(labels[cid], doc_meta.get(rows[cid][0]), names.get(rows[cid][0])))
               not in done)


def push(ws, con, run_id, sink=None, log=None, force=False):
    """force: rules-update 실행의 변경 비율 상한(RULES_CHANGE_RATIO_HIGH)을 넘어 막힌 적재를 사람이 확인한 뒤 보낸다."""
    vs = ws.config["vector_store"]
    if not vs.get("enabled"):
        print("[push-vectors] vector_store.enabled=false: 저장하지 않습니다.")
        return {"called": 0, "sent": 0, "skipped": 0, "blocked": 0}
    from labelbot import rulesupdate

    info = rulesupdate.run_info(con, run_id)
    stop, ratio, limit = rulesupdate.blocked(ws, info) if info else (False, 0.0, 0.0)
    if stop and not force:
        print("[push-vectors] 차단 %s ratio=%.2f limit=%.2f" % (rulesupdate.RULES_CHANGE_RATIO_HIGH, ratio, limit))
        return {"called": 0, "sent": 0, "skipped": 0, "blocked": 0, "reason": rulesupdate.RULES_CHANGE_RATIO_HIGH}
    if stop:  # 사람이 확인하고 막힘을 넘겼다: 줄과 meta(forced_at)에 남긴다
        print("[push-vectors] FORCED %s ratio=%.2f limit=%.2f" % (rulesupdate.RULES_CHANGE_RATIO_HIGH, ratio, limit))
        rulesupdate.mark_forced(con, run_id)
    model = ws.config["embedding"]["model"]
    root = localstore.store_root(vs)
    lcon = localstore.connect(root)
    try:
        target = localstore.target_hash(lcon)
        others = localstore.other_model_rows(lcon, model)
    finally:
        lcon.close()
    if others:
        print("[push-vectors] 저장소에 다른 임베딩 모델 행 %d개" % others)
    own_sink = sink is None
    if own_sink:
        sink = LocalSink(root)
    chunks = {c["chunk_id"]: c for c in run_chunks(con, run_id)}
    emb = con.execute(
        "SELECT chunk_id, model, dim, text_hash, vector FROM chunk_embeddings WHERE chunk_id IN (%s)"
        % ",".join("?" * len(chunks)), list(chunks)).fetchall() if chunks else []
    emb = [e for e in emb if e["model"] == model and chunks[e["chunk_id"]]["text_hash"] == e["text_hash"]]
    if len({e["dim"] for e in emb}) > 1:
        store.add_failure(con, run_id, "push", "*", "MODEL_DIM_MIX")
        con.commit()
        print("[push-vectors] 차원이 다른 벡터가 섞여 있어 거부합니다.")
        return {"called": 0, "sent": 0, "skipped": 0, "blocked": 0, "reason": "MODEL_DIM_MIX"}
    labels = finals.final_labels(con, run_id, [e["chunk_id"] for e in emb])
    doc_meta, names = load_doc_meta(con), load_file_names(con)
    ok = _pushable(con, run_id, labels)
    todo, skipped, blocked = [], 0, 0
    for e in emb:
        c, d = chunks[e["chunk_id"]], labels.get(e["chunk_id"])
        if c["chunk_id"] not in ok:
            skipped += 1  # 분류·라벨 실패 chunk, 대상 축을 못 채운 axis-update chunk는 적재하지 않는다
            continue
        lh = push_label_hash(d, doc_meta.get(c["file_id"]), names.get(c["file_id"]))
        done = con.execute(
            "SELECT 1 FROM vector_push_log WHERE chunk_id=? AND model=? AND text_hash=? AND label_hash=? "
            "AND target_host_hash=? AND result_code='OK'", (c["chunk_id"], model, e["text_hash"], lh, target)).fetchone()
        if done:
            skipped += 1
            continue
        payload = {"axes": {k: v["values"] for k, v in d["axes"].items()},
                   "answers": {k: v["answer"] for k, v in d["answers"].items()}}
        if c["file_id"] in doc_meta:  # 파일 단위 Lot·WF·날짜·작성자를 chunk마다 복사
            payload["doc_meta"] = doc_meta[c["file_id"]]
        todo.append((c, e, lh, LocalSink.row(c, model, unpack(e["vector"]), payload, run_id, names.get(c["file_id"]))))
    called = sent = 0
    size = int(vs.get("batch_size") or 100)
    for i in range(0, len(todo), size):
        batch = todo[i : i + size]
        called += 1
        try:
            sink.send([t[3] for t in batch])
            code = "OK"
            sent += len(batch)
        except CallFailed as ex:
            code = ex.reason_code
            if log:
                log("push", batch[0][0]["chunk_id"], code)
        for c, e, lh, _ in batch:
            _log(con, c["chunk_id"], model, e["text_hash"], lh, target, code)
        con.commit()
    con.commit()
    if own_sink:  # RAG 서버가 읽는 llm·embedding 설정(키 환경변수 이름만). 테스트의 가짜 sink에는 쓰지 않는다.
        localstore.write_rag_config(root, ws.config["llm"], ws.config["embedding"])
    print("[push-vectors] 호출 %d회, 전송 %d행, 건너뜀 %d, 차단 %d" % (called, sent, skipped, blocked))
    return {"called": called, "sent": sent, "skipped": skipped, "blocked": blocked}


def _log(con, chunk_id, model, th, lh, target, code):
    con.execute(
        "INSERT INTO vector_push_log(chunk_id, model, text_hash, label_hash, target_host_hash, pushed_at, result_code)"
        " VALUES(?,?,?,?,?,?,?)", (chunk_id, model, th, lh, target, util.now_iso(), code))
