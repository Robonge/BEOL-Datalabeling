"""chunk 임베딩(python -m labelbot embed). 로컬 work.sqlite의 chunk_embeddings가 원본이다.

text_hash와 model이 같으면 다시 호출하지 않는다. 실패는 사유 코드로 남기고 다른 단계를 막지 않는다.
"""
import struct

from labelbot import store, util
from labelbot.llm import CallFailed, HttpEmbedTransport


def pack(vec):
    return struct.pack("<%df" % len(vec), *vec)


def unpack(blob):
    return list(struct.unpack("<%df" % (len(blob) // 4), blob))


def run_chunks(con, run_id):
    return [dict(r) for r in con.execute(
        "SELECT DISTINCT c.chunk_id, c.file_id, c.seq, c.text, c.text_hash FROM chunks c "
        "JOIN files f ON f.file_id=c.file_id JOIN file_locations l ON l.file_id=f.file_id "
        "WHERE f.status='ok' AND l.last_seen_run=? ORDER BY c.file_id, c.seq", (run_id,))]


def embed(ws, con, run_id, transport=None, log=None, quiet=False):
    """quiet=True(피드백 사례 유사도용, run 안에서 부름): 출력하지 않고 failures 표에도 남기지 않는다(로그만)."""
    cfg = ws.config["embedding"]
    if not cfg.get("enabled"):
        if not quiet:
            print("[embed] embedding.enabled=false: 호출하지 않습니다.")
        return {"called": 0, "stored": 0, "skipped": 0, "blocked": 0}
    if transport is None:
        if cfg.get("transport") == "mock":
            from labelbot.mock import MockEmbedTransport

            transport = MockEmbedTransport()
        else:
            transport = HttpEmbedTransport(cfg)
    model, url = cfg["model"], cfg["base_url"].rstrip("/") + cfg["path"]
    todo, blocked, skipped = [], 0, 0
    for c in run_chunks(con, run_id):
        r = con.execute("SELECT text_hash FROM chunk_embeddings WHERE chunk_id=? AND model=?", (c["chunk_id"], model)).fetchone()
        if r and r[0] == c["text_hash"]:
            skipped += 1
            continue
        todo.append(c)
    called = stored = 0
    size = int(cfg.get("batch_size") or 64)
    for i in range(0, len(todo), size):
        batch = todo[i : i + size]
        try:
            called += 1
            vecs = transport.embed([c["text"] for c in batch])
        except CallFailed as e:
            for c in batch:
                if not quiet:
                    store.add_failure(con, run_id, "embed", c["chunk_id"], e.reason_code)
            if log:
                log("embed", batch[0]["chunk_id"], e.reason_code)
            continue
        if len(vecs) != len(batch):
            for c in batch:
                if not quiet:
                    store.add_failure(con, run_id, "embed", c["chunk_id"], "RESPONSE_SHAPE")
            if log:
                log("embed", batch[0]["chunk_id"], "RESPONSE_SHAPE")
            continue
        for c, v in zip(batch, vecs):
            con.execute(
                "INSERT OR REPLACE INTO chunk_embeddings(chunk_id, model, dim, text_hash, vector, run_id) VALUES(?,?,?,?,?,?)",
                (c["chunk_id"], model, len(v), c["text_hash"], pack(v), run_id),
            )
            stored += 1
        con.commit()
    con.commit()
    if not quiet:
        print("[embed] 호출 %d회, 저장 %d, 건너뜀 %d, 차단 %d" % (called, stored, skipped, blocked))
    return {"called": called, "stored": stored, "skipped": skipped, "blocked": blocked}
