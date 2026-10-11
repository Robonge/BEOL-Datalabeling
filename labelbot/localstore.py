"""로컬 RAG 저장소(push-vectors·push-slides의 적재 대상, RAG 서버 labelbot.ragsrv가 읽는다). 네트워크 없음.

<store>/rag_store.sqlite     표 meta, beol_chunk_embeddings, beol_rag_feedback
<store>/slides/<jpg_sha256>.b64
<store>/rag_config.json      마지막 push-vectors가 쓴 llm·embedding 블록(환경변수 '이름'만, 값 없음)

<store>는 vector_store.path → 환경변수 BEOL_RAG_STORE → <코드 폴더>/workspaces/_rag_store 순으로 정한다.
행 키는 (chunk_id, model)이고 나중에 적재한 것이 이긴다. 작업 폴더의 원본은 work.sqlite·slide_images/이며 저장소는 사본이다.
"""
import base64
import json
import os
import sqlite3
import uuid

from labelbot import util
from labelbot.embed import pack
from labelbot.workspace import CODE_ROOT

DB_NAME = "rag_store.sqlite"
CONFIG_NAME = "rag_config.json"
SLIDE_COLS = ("slide_image_bucket", "slide_image_path", "slide_image_sha256", "slide_image_width", "slide_image_height")
# upsert가 갱신하는 열. slide_image_* 열은 건드리지 않는다(push-slides 몫).
ROW_COLS = ("chunk_id", "model", "file_id", "file_name", "seq", "dim", "embedding", "content", "labels", "run_id",
            "updated_at")

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS beol_chunk_embeddings(
  chunk_id TEXT NOT NULL, model TEXT NOT NULL, file_id TEXT NOT NULL, file_name TEXT, seq INTEGER,
  dim INTEGER NOT NULL, embedding BLOB NOT NULL,
  content TEXT, labels TEXT,
  run_id TEXT, updated_at TEXT,
  slide_image_bucket TEXT, slide_image_path TEXT, slide_image_sha256 TEXT,
  slide_image_width INTEGER, slide_image_height INTEGER,
  PRIMARY KEY(chunk_id, model));
CREATE INDEX IF NOT EXISTS ix_bce_file ON beol_chunk_embeddings(file_id, seq);
CREATE TABLE IF NOT EXISTS beol_rag_feedback(
  id TEXT PRIMARY KEY, created_at TEXT NOT NULL, session_id TEXT, question TEXT NOT NULL, answer TEXT NOT NULL,
  evidence TEXT NOT NULL DEFAULT '[]', verdict TEXT NOT NULL CHECK(verdict IN ('good','bad')), comment TEXT);
"""


def store_root(vs_cfg=None):
    """저장소 폴더 절대경로. 폴더를 만들지 않는다."""
    p = (vs_cfg or {}).get("path") or os.environ.get("BEOL_RAG_STORE") or os.path.join(CODE_ROOT, "workspaces", "_rag_store")
    return os.path.abspath(p)


def db_path(root):
    return os.path.join(root, DB_NAME)


def exists(root):
    return os.path.isfile(db_path(root))


def connect(root):
    """저장소 연결. 폴더·파일·표가 없으면 만들고, store_id(uuid4)는 처음 한 번만 넣는다."""
    os.makedirs(root, exist_ok=True)
    con = sqlite3.connect(db_path(root))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    con.execute("INSERT OR IGNORE INTO meta(key, value) VALUES('store_id', ?)", (uuid.uuid4().hex,))
    con.commit()
    return con


def store_id(con):
    return con.execute("SELECT value FROM meta WHERE key='store_id'").fetchone()[0]


def target_hash(con):
    """vector_push_log·slide_image_push_log의 target_host_hash 값. 저장소를 다시 만들면 바뀐다."""
    return util.sha256_text("local:" + store_id(con))[:16]


def upsert_rows(con, rows):
    """vectorpush.LocalSink.row()의 dict 행을 넣는다. 같은 (chunk_id, model)은 벡터·본문·라벨 열만 갱신한다."""
    sql = "INSERT INTO beol_chunk_embeddings(%s) VALUES(%s) ON CONFLICT(chunk_id, model) DO UPDATE SET %s" % (
        ", ".join(ROW_COLS), ",".join("?" * len(ROW_COLS)),
        ", ".join("%s=excluded.%s" % (c, c) for c in ROW_COLS[2:]))
    now = util.now_iso()
    con.executemany(sql, [(
        r["chunk_id"], r["model"], r["file_id"], r.get("file_name"), r.get("seq"), len(r["embedding"]),
        pack(r["embedding"]), r.get("content"),
        json.dumps(r.get("labels") or {}, ensure_ascii=False, sort_keys=True), r.get("run_id"),
        r.get("updated_at") or now) for r in rows])
    con.commit()
    return len(rows)


def other_model_rows(con, model):
    return con.execute("SELECT COUNT(*) FROM beol_chunk_embeddings WHERE model<>?", (model,)).fetchone()[0]


def slide_path(root, sha):
    return os.path.join(root, "slides", sha + ".b64")


def put_slide(root, sha, data):
    """JPG bytes를 <store>/slides/<sha>.b64로 쓴다. 이미 있으면 건너뛴다. 반환: 새로 썼는지."""
    p = slide_path(root, sha)
    if os.path.isfile(p):
        return False
    tmp = os.path.join(os.path.dirname(p), sha + ".part.b64")
    util.write_text(tmp, base64.b64encode(data).decode("ascii"))
    os.replace(tmp, p)
    return True


def patch_slide(con, chunk_id, fields):
    """저장소 연결(work.sqlite 아님)의 행에 slide_image_* 열을 쓴다. 반환: 갱신된 행 수."""
    cur = con.execute("UPDATE beol_chunk_embeddings SET %s WHERE chunk_id=?" % ", ".join("%s=?" % c for c in SLIDE_COLS),
                      [fields.get(c) for c in SLIDE_COLS] + [chunk_id])
    con.commit()
    return cur.rowcount


def write_rag_config(root, llm_cfg, emb_cfg):
    """RAG 서버가 쓸 llm·embedding 블록. 설정에는 키 환경변수 이름만 있고 값은 없다."""
    p = os.path.join(root, CONFIG_NAME)
    tmp = os.path.join(root, "rag_config.part.json")
    util.write_text(tmp, json.dumps({"llm": llm_cfg, "embedding": emb_cfg}, ensure_ascii=False, indent=2) + "\n")
    os.replace(tmp, p)
    return p
