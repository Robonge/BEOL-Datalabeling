"""슬라이드 JPG를 로컬 저장소 slides/에 저장하고 벡터 행에 slide_image_* 열을 채운다(python -m labelbot push-slides).

로컬 저장소 slides/는 사본이다. 원본은 slide_images/<sha256>.b64와 work.sqlite slide_images 표다.
slide_image_push_log로 멱등을 보장한다. 같은 저장소(target_hash)·버킷에 같은 chunk·jpg_sha256이 OK로 있으면 보내지 않는다.
벡터 행이 있어야 열을 채울 수 있으므로 push-vectors 다음에 부른다. 행이 없으면 ROW_MISSING으로 남기고 다음에 다시 한다.
라벨과 label_hash는 바꾸지 않는다(push-vectors의 멱등을 건드리지 않는다).
"""
import os
import sqlite3

from labelbot import localstore, store, util
from labelbot.embed import run_chunks
from labelbot.llm import CallFailed
from labelbot.slideimg import object_path

STAGE = "push_slides"
LOCAL_BUCKET = "local"


class LocalSlideSink:
    """저장소 연결을 스스로 연다. close()로 닫는다."""

    def __init__(self, root):
        self.root = root
        self.con = localstore.connect(root)

    def upload(self, bucket, path, data):
        try:
            localstore.put_slide(self.root, util.sha256_bytes(data), data)
        except (OSError, ValueError):
            raise CallFailed("LOCAL_STORE_ERROR")

    def patch_row(self, chunk_id, fields):
        """반환: 갱신된 행 수."""
        try:
            return localstore.patch_slide(self.con, chunk_id, fields)
        except sqlite3.Error:
            raise CallFailed("LOCAL_STORE_ERROR")

    def close(self):
        self.con.close()


def row_fields(bucket, r):
    return {"slide_image_bucket": bucket, "slide_image_path": object_path(r["file_id"], r["seq"]),
            "slide_image_sha256": r["jpg_sha256"], "slide_image_width": r["width"], "slide_image_height": r["height"]}


def push(ws, con, run_id, sink=None, log=None):
    vs = ws.config["vector_store"]
    zero = {"uploaded": 0, "patched": 0, "skipped": 0, "blocked": 0, "failed": 0}
    if not vs.get("slides_enabled"):
        print("[push-slides] vector_store.slides_enabled=false: 저장하지 않습니다.")
        return zero
    root, bucket = localstore.store_root(vs), LOCAL_BUCKET
    lcon = localstore.connect(root)
    try:
        target = localstore.target_hash(lcon)
    finally:
        lcon.close()
    own_sink = sink is None
    if own_sink:
        sink = LocalSlideSink(root)
    try:
        st = _push_rows(ws, con, run_id, sink, log, bucket, target, zero)
    finally:
        if own_sink:
            sink.close()
    print("[push-slides] 업로드 %d, 행 갱신 %d, 건너뜀 %d, 차단 %d, 실패 %d" % (
        st["uploaded"], st["patched"], st["skipped"], st["blocked"], st["failed"]))
    return st


def _push_rows(ws, con, run_id, sink, log, bucket, target, zero):
    ids = [c["chunk_id"] for c in run_chunks(con, run_id)]
    # 지금 본문과 같은 text_hash로 그린 그림만 올린다.
    rows = con.execute(
        "SELECT s.* FROM slide_images s JOIN chunks c ON c.chunk_id=s.chunk_id AND c.text_hash=s.text_hash"
        " WHERE s.chunk_id IN (%s) ORDER BY s.file_id, s.seq" % ",".join("?" * len(ids)), ids).fetchall() if ids else []
    st = dict(zero)
    for r in rows:
        path = object_path(r["file_id"], r["seq"])
        done = con.execute(
            "SELECT 1 FROM slide_image_push_log WHERE chunk_id=? AND jpg_sha256=? AND bucket=? AND target_host_hash=?"
            " AND result_code='OK'", (r["chunk_id"], r["jpg_sha256"], bucket, target)).fetchone()
        if done:
            st["skipped"] += 1
            continue
        code = _send(ws, sink, bucket, path, r, st)
        _log(con, r, bucket, path, target, code)
        if code != "OK":
            store.add_failure(con, run_id, STAGE, r["chunk_id"], code)
            if log:
                log(STAGE, r["chunk_id"], code)
        con.commit()
    return st


def _send(ws, sink, bucket, path, r, st):
    rel = ws.path(r["rel_file"])
    if not os.path.isfile(rel):
        st["failed"] += 1
        return "B64_MISSING"
    data = util.read_b64(rel)
    if util.sha256_bytes(data) != r["jpg_sha256"] or data[:3] != b"\xff\xd8\xff":
        st["failed"] += 1
        return "SHA_MISMATCH"
    try:
        sink.upload(bucket, path, data)
    except CallFailed as ex:
        st["failed"] += 1
        return "UPLOAD_" + ex.reason_code
    st["uploaded"] += 1
    try:
        n = sink.patch_row(r["chunk_id"], row_fields(bucket, r))
    except CallFailed as ex:
        st["failed"] += 1
        return "PATCH_" + ex.reason_code
    if not n:
        st["failed"] += 1
        return "ROW_MISSING"
    st["patched"] += 1
    return "OK"


def _log(con, r, bucket, path, target, code):
    con.execute(
        "INSERT INTO slide_image_push_log(chunk_id, jpg_sha256, bucket, object_path, target_host_hash, pushed_at,"
        " result_code) VALUES(?,?,?,?,?,?,?)", (r["chunk_id"], r["jpg_sha256"], bucket, path, target, util.now_iso(), code))
