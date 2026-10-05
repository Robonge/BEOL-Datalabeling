"""Supabase(Postgres + pgvector) 벡터 적재(python -m labelbot push-vectors). Supabase는 사본이다.

vector_push_log로 멱등을 보장한다. 같은 대상 호스트에 같은 chunk·모델·text_hash·label_hash가 성공으로 있으면 보내지 않는다.
파일명과 경로는 보내지 않는다. 적재 대상별 부분(URL, 헤더, 행 형식)은 SupabaseSink 하나에 모은다.
"""
from labelbot import finals, store, util
from labelbot.embed import run_chunks, unpack
from labelbot.llm import CallFailed, SendBlocked, SupabaseSinkBase, check_send, host_hash, post_json, read_key


class SupabaseSink(SupabaseSinkBase):
    @property
    def endpoint(self):
        return "%s/rest/v1/%s?on_conflict=chunk_id,model" % (self.base, self.cfg["table"])

    def send(self, rows):
        hdrs = self._hdrs()
        hdrs["Prefer"] = "resolution=merge-duplicates,return=minimal"
        post_json(self.endpoint, hdrs, rows, self.timeout, self.ca_file)

    @staticmethod
    def row(c, model, vec, labels, run_id):
        return {
            "chunk_id": c["chunk_id"], "file_id": c["file_id"], "seq": c["seq"], "model": model, "dim": len(vec),
            "embedding": "[" + ",".join("%.7g" % x for x in vec) + "]", "content": c["text"],
            "labels": labels, "run_id": run_id,
        }


def push(ws, con, run_id, sink=None, log=None):
    sb = ws.config["supabase"]
    if not sb.get("enabled"):
        print("[push-vectors] supabase.enabled=false: 호출하지 않습니다.")
        return {"called": 0, "sent": 0, "skipped": 0, "blocked": 0}
    url = ws.supabase_url()
    model = ws.config["embedding"]["model"]
    suffixes = ws.config["llm"].get("internal_host_suffixes")
    if sink is None:
        key = read_key(sb.get("key_env"))
        if not url or not key:
            print("[push-vectors] SUPABASE_URL 또는 키 환경변수가 없습니다.")
            return {"called": 0, "sent": 0, "skipped": 0, "blocked": 0, "reason": "CONFIG_MISSING"}
        sink = SupabaseSink(url, sb, key)
    target = host_hash(url)
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
    lab_failed = {r[0] for r in con.execute("SELECT target_id FROM failures WHERE run_id=? AND stage='label'", (run_id,))}
    todo, skipped, blocked = [], 0, 0
    for e in emb:
        c, d = chunks[e["chunk_id"]], labels.get(e["chunk_id"])
        if not d or not d["chunk_type"] or (c["chunk_id"] in lab_failed and not d["answers"]):
            skipped += 1  # 분류·라벨 실패 chunk는 적재하지 않는다
            continue
        lh = finals.label_hash(d)
        done = con.execute(
            "SELECT 1 FROM vector_push_log WHERE chunk_id=? AND model=? AND text_hash=? AND label_hash=? "
            "AND target_host_hash=? AND result_code='OK'", (c["chunk_id"], model, e["text_hash"], lh, target)).fetchone()
        if done:
            skipped += 1
            continue
        try:
            check_send(url, [c["file_id"]], suffixes)
        except SendBlocked as ex:
            _log(con, c["chunk_id"], model, e["text_hash"], lh, target, ex.reason_code)
            store.add_failure(con, run_id, "push", c["chunk_id"], ex.reason_code)
            blocked += 1
            continue
        payload = {"axes": {k: v["values"] for k, v in d["axes"].items()},
                   "answers": {k: v["answer"] for k, v in d["answers"].items()}}
        todo.append((c, e, lh, SupabaseSink.row(c, model, unpack(e["vector"]), payload, run_id)))
    called = sent = 0
    size = int(sb.get("batch_size") or 100)
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
    print("[push-vectors] 호출 %d회, 전송 %d행, 건너뜀 %d, 차단 %d" % (called, sent, skipped, blocked))
    return {"called": called, "sent": sent, "skipped": skipped, "blocked": blocked}


def _log(con, chunk_id, model, th, lh, target, code):
    con.execute(
        "INSERT INTO vector_push_log(chunk_id, model, text_hash, label_hash, target_host_hash, pushed_at, result_code)"
        " VALUES(?,?,?,?,?,?,?)", (chunk_id, model, th, lh, target, util.now_iso(), code))
