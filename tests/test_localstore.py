"""로컬 RAG 저장소(labelbot/localstore.py): 스키마·store_id, upsert, 슬라이드 .b64, patch_slide, target_hash.

모두 임시 폴더에 쓴다. 환경변수 BEOL_RAG_STORE도 임시 폴더로 고정한다(실제 workspaces/_rag_store에 쓰지 않는다).
"""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from labelbot import localstore, util
from labelbot.embed import unpack

JPG = b"\xff\xd8\xff\xe0" + b"jpeg-body" * 10


def row(cid, model="m", vec=(0.5, -1.0, 2.0), labels=None, content="본문"):
    return {"chunk_id": cid, "model": model, "file_id": "f" * 64, "file_name": "a.pptx", "seq": 1, "dim": len(vec),
            "embedding": list(vec), "content": content, "labels": labels or {"axes": {"축": ["값"]}},
            "run_id": "r1", "updated_at": "2026-10-11T00:00:00"}


class LocalStoreTest(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="labelbot_ragstore_")
        self.root = os.path.join(self.base, "store")
        self.env = mock.patch.dict(os.environ, {"BEOL_RAG_STORE": os.path.join(self.base, "env_store")})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.base, ignore_errors=True)

    def test_store_root_order(self):
        self.assertEqual(localstore.store_root({"path": self.root}), os.path.abspath(self.root))
        self.assertEqual(localstore.store_root({"path": ""}), os.path.abspath(os.path.join(self.base, "env_store")))
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BEOL_RAG_STORE", None)
            self.assertTrue(localstore.store_root({}).endswith(os.path.join("workspaces", "_rag_store")))

    def test_schema_and_store_id_once(self):
        self.assertFalse(localstore.exists(self.root))
        con = localstore.connect(self.root)
        sid, th = localstore.store_id(con), localstore.target_hash(con)
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        con.close()
        self.assertTrue({"meta", "beol_chunk_embeddings", "beol_rag_feedback"} <= tables)
        con = localstore.connect(self.root)
        try:
            self.assertEqual(localstore.store_id(con), sid)
            self.assertEqual(localstore.target_hash(con), th)
            self.assertEqual(th, util.sha256_text("local:" + sid)[:16])
            self.assertEqual(con.execute("SELECT COUNT(*) FROM meta WHERE key='store_id'").fetchone()[0], 1)
        finally:
            con.close()

    def test_upsert_twice_keeps_slide_columns(self):
        con = localstore.connect(self.root)
        try:
            self.assertEqual(localstore.upsert_rows(con, [row("c1"), row("c2"), row("c1", model="m2")]), 3)
            n = localstore.patch_slide(con, "c1", {"slide_image_bucket": "local", "slide_image_path": "ff/0001.jpg",
                                                   "slide_image_sha256": "s", "slide_image_width": 10,
                                                   "slide_image_height": 5})
            self.assertEqual(n, 2)  # 같은 chunk의 두 모델 행
            self.assertEqual(localstore.patch_slide(con, "없음", {}), 0)
            localstore.upsert_rows(con, [row("c1", vec=(1.0, 2.0), labels={"axes": {"축": ["새 값"]}}, content="새 본문")])
            rows = con.execute("SELECT * FROM beol_chunk_embeddings WHERE chunk_id='c1' AND model='m'").fetchall()
            self.assertEqual(len(rows), 1)
            r = rows[0]
            self.assertEqual((r["dim"], unpack(r["embedding"]), r["content"]), (2, [1.0, 2.0], "새 본문"))
            self.assertEqual(json.loads(r["labels"]), {"axes": {"축": ["새 값"]}})
            self.assertEqual((r["slide_image_bucket"], r["slide_image_path"], r["slide_image_width"]),
                             ("local", "ff/0001.jpg", 10))
            self.assertEqual(con.execute("SELECT COUNT(*) FROM beol_chunk_embeddings").fetchone()[0], 3)
            self.assertEqual(localstore.other_model_rows(con, "m"), 1)
        finally:
            con.close()

    def test_put_slide_idempotent(self):
        sha = util.sha256_bytes(JPG)
        self.assertTrue(localstore.put_slide(self.root, sha, JPG))
        p = localstore.slide_path(self.root, sha)
        mtime = os.path.getmtime(p)
        self.assertFalse(localstore.put_slide(self.root, sha, b"other"))
        self.assertEqual(os.path.getmtime(p), mtime)
        self.assertEqual(util.read_b64(p), JPG)
        self.assertEqual(os.listdir(os.path.dirname(p)), [sha + ".b64"])

    def test_rag_config_and_allowed_extensions(self):
        con = localstore.connect(self.root)
        localstore.upsert_rows(con, [row("c1")])
        con.close()
        localstore.put_slide(self.root, util.sha256_bytes(JPG), JPG)
        p = localstore.write_rag_config(self.root, {"model": "x", "api_key_env": "SOME_KEY_ENV"}, {"model": "e"})
        with open(p, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"llm": {"model": "x", "api_key_env": "SOME_KEY_ENV"},
                                            "embedding": {"model": "e"}})
        for d, _, files in os.walk(self.root):
            for fn in files:
                self.assertTrue(fn.lower().endswith(util.ALLOWED_EXT) or fn.endswith(("-wal", "-shm")), fn)

    def test_recreated_store_changes_target_hash(self):
        con = localstore.connect(self.root)
        th = localstore.target_hash(con)
        con.close()
        shutil.rmtree(self.root)
        con = localstore.connect(self.root)
        try:
            self.assertNotEqual(localstore.target_hash(con), th)
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
