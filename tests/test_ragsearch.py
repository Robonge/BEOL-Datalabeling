"""labelbot.ragsearch: 작은 가짜 저장소(임시 sqlite, local-transformation.md B2 스키마)로 검색 사양을 본다."""
import json
import os
import shutil
import sqlite3
import tempfile
import unittest

from labelbot import ragsearch
from labelbot.embed import pack

MODEL = "text-embedding-3-small"
SCHEMA = """
CREATE TABLE IF NOT EXISTS beol_chunk_embeddings(
  chunk_id TEXT NOT NULL, model TEXT NOT NULL, file_id TEXT NOT NULL, file_name TEXT, seq INTEGER,
  dim INTEGER NOT NULL, embedding BLOB NOT NULL,
  content TEXT, labels TEXT,
  run_id TEXT, updated_at TEXT,
  slide_image_bucket TEXT, slide_image_path TEXT, slide_image_sha256 TEXT,
  slide_image_width INTEGER, slide_image_height INTEGER,
  PRIMARY KEY(chunk_id, model));
"""
DOC_META = {"author": "kim", "lots": []}


def labels(scheme=("SAQP",), doc_meta=DOC_META, **axes):
    out = {"axes": dict({"Patterning/scheme": list(scheme)}, **axes), "answers": {}}
    if doc_meta is not ...:
        out["doc_meta"] = doc_meta
    return out


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.con = sqlite3.connect(os.path.join(self.tmp, "rag_store.sqlite"))
        self.con.executescript(SCHEMA)

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def add(self, chunk_id, vec=(1.0, 0.0), content="", lab=None, file_id="f" * 64, seq=1,
            model=MODEL, path="default"):
        lab = labels() if lab is None else lab
        if path == "default":
            path = "%s/%04d.jpg" % (file_id[:16], seq)
        self.con.execute(
            "INSERT INTO beol_chunk_embeddings(chunk_id, model, file_id, seq, dim, embedding, content, labels,"
            " slide_image_bucket, slide_image_path, slide_image_width, slide_image_height)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (chunk_id, model, file_id, seq, len(vec), pack(list(vec)), content,
             None if lab is None else json.dumps(lab, ensure_ascii=False), "local", path, 1280, 720))
        self.con.commit()

    def ids(self, rows):
        return [r["chunk_id"] for r in rows]

    def search(self, q=(1.0, 0.0), text="", filters=None, k=8):
        return ragsearch.search(self.con, list(q), text, filters, k, MODEL)


class FilterTest(StoreCase):
    def setUp(self):
        super().setUp()
        self.add("c1", lab=labels(Metal=["Cu"], Layer=["M1"]))
        self.add("c2", lab=labels(Metal=["Ru"], Layer=["M1"]))
        self.add("c3", lab=labels(Metal=["Cu", "Co"], Layer=["M2"]))
        self.add("c4", lab=labels(Layer=["M1"]))  # Metal 축 없음

    def test_or_within_axis(self):
        self.assertEqual(sorted(self.ids(self.search(filters={"Metal": ["Ru", "Co"]}))), ["c2", "c3"])

    def test_and_across_axes(self):
        self.assertEqual(self.ids(self.search(filters={"Metal": ["Cu"], "Layer": ["M1"]})), ["c1"])

    def test_exact_case_sensitive_match(self):
        self.assertEqual(self.search(filters={"Metal": ["cu"]}), [])

    def test_empty_axis_ignored(self):
        self.assertEqual(sorted(self.ids(self.search(filters={"Metal": [], "Layer": []}))), ["c1", "c2", "c3", "c4"])

    def test_row_missing_axis_excluded(self):
        self.assertNotIn("c4", self.ids(self.search(filters={"Metal": ["Cu", "Ru", "Co"]})))

    def test_bad_filter(self):
        for bad in (["Metal"], {"Metal": "Cu"}, "x"):
            with self.assertRaises(ragsearch.RagSearchError) as cm:
                self.search(filters=bad)
            self.assertEqual(cm.exception.code, "BAD_FILTER")


class CompleteRowTest(StoreCase):
    def setUp(self):
        super().setUp()
        self.add("ok", file_id="a" * 64, seq=1)
        self.add("other_model", file_id="a" * 64, seq=2, model="other-model")
        self.add("empty_scheme", file_id="a" * 64, seq=3, lab=labels(scheme=()))
        self.add("no_doc_meta", file_id="a" * 64, seq=4, lab=labels(doc_meta=...))
        self.add("null_doc_meta", file_id="a" * 64, seq=5, lab=labels(doc_meta=None))
        self.add("no_image", file_id="a" * 64, seq=6, path=None)
        for cid, seq, lab in (("no_labels", 7, None), ("bad_json", 8, "{oops")):
            self.con.execute("INSERT INTO beol_chunk_embeddings(chunk_id, model, file_id, seq, dim, embedding, labels,"
                             " slide_image_path) VALUES(?, ?, ?, ?, 2, ?, ?, 'p')",
                             (cid, MODEL, "a" * 64, seq, pack([1.0, 0.0]), lab))
        self.con.commit()

    def test_search_siblings_facets_count_use_complete_rows_only(self):
        self.assertEqual(self.ids(self.search()), ["ok"])
        self.assertEqual(self.ids(ragsearch.siblings(self.con, ["a" * 64], MODEL)), ["ok"])
        self.assertEqual(ragsearch.count(self.con, MODEL), 1)
        self.assertEqual(ragsearch.facets(self.con, MODEL), [{"axis": "Patterning/scheme", "value": "SAQP", "n": 1}])

    def test_is_complete(self):
        row = {"model": MODEL, "labels": labels(), "slide_image_path": "p"}
        self.assertTrue(ragsearch.is_complete(row, MODEL))
        self.assertFalse(ragsearch.is_complete(row, "other"))
        self.assertTrue(ragsearch.is_complete(dict(row, labels=json.dumps(labels())), MODEL))


class RankTest(StoreCase):
    def test_vector_only_order_and_columns(self):
        self.add("far", vec=(0.0, 1.0))
        self.add("near", vec=(1.0, 0.0))
        self.add("mid", vec=(1.0, 1.0))
        rows = self.search(q=(1.0, 0.0))
        self.assertEqual(self.ids(rows), ["near", "mid", "far"])
        self.assertEqual([r["vector_pos"] for r in rows], [1, 2, 3])
        self.assertTrue(all(r["text_pos"] is None and r["text_score"] is None for r in rows))
        self.assertAlmostEqual(rows[0]["vector_similarity"], 1.0, places=6)
        self.assertAlmostEqual(rows[2]["vector_similarity"], 0.0, places=6)
        self.assertAlmostEqual(rows[0]["rrf_score"], 1 / 61)
        self.assertEqual(set(rows[0]), {
            "chunk_id", "file_id", "seq", "content", "labels", "slide_image_bucket", "slide_image_path",
            "slide_image_width", "slide_image_height", "vector_similarity", "text_score", "vector_pos",
            "text_pos", "rrf_score"})
        self.assertIsInstance(rows[0]["labels"], dict)

    def test_rrf_tie_prefers_text_pos(self):
        # P: vector 1위·text 2위, Q: vector 2위·text 1위 → rrf 같음 → text_pos가 앞선 Q가 먼저
        self.add("P", vec=(1.0, 0.0), content="via")
        self.add("Q", vec=(0.9, 0.1), content="via via")
        self.add("R", vec=(0.0, 1.0), content="other")
        rows = self.search(text="via")
        self.assertEqual(self.ids(rows), ["Q", "P", "R"])
        self.assertEqual(rows[0]["rrf_score"], rows[1]["rrf_score"])
        self.assertEqual((rows[0]["vector_pos"], rows[0]["text_pos"]), (2, 1))
        self.assertIsNone(rows[2]["text_pos"])

    def test_full_tie_broken_by_chunk_id(self):
        for cid in ("b", "c", "a"):
            self.add(cid, vec=(1.0, 0.0), content="same")
        self.assertEqual(self.ids(self.search(text="same")), ["a", "b", "c"])

    def test_missing_vector_pos_sorts_after(self):
        # 205행 중 벡터 상위 200 밖의 행(T)은 vector_pos 없음. text 1위만으로 rrf=1/61 → vector 1위(V)와 동점
        self.add("V", vec=(1.0, 0.0), content="")
        for i in range(203):
            self.add("n%03d" % i, vec=(1.0, 0.01 * (i + 1)), content="")
        self.add("T", vec=(-1.0, 0.0), content="needle")
        rows = self.search(text="needle", k=2)
        self.assertEqual(self.ids(rows), ["T", "V"])
        self.assertIsNone(rows[0]["vector_pos"])
        self.assertEqual(rows[0]["text_pos"], 1)
        self.assertEqual(rows[0]["rrf_score"], rows[1]["rrf_score"])

    def test_k_range(self):
        for i in range(10):
            self.add("c%02d" % i, vec=(1.0, 0.1 * i))
        for k, n in ((None, 5), (0, 1), (-3, 1), (1, 1), (3, 3), (8, 8), (50, 8)):
            self.assertEqual(len(self.search(k=k)), n, k)

    def test_dim_mismatch(self):
        self.add("x", vec=(1.0, 0.0))
        with self.assertRaises(ragsearch.RagSearchError) as cm:
            self.search(q=(1.0, 0.0, 0.0))
        self.assertEqual(cm.exception.code, "DIM_MISMATCH")

    def test_cached_rows_same_result(self):
        self.add("a", vec=(1.0, 0.0), content="via")
        self.add("b", vec=(0.0, 1.0), content="line")
        rows = ragsearch.load_rows(self.con, MODEL)
        self.assertEqual(ragsearch.search(self.con, [0.0, 1.0], "via", None, 5, MODEL, rows=rows),
                         self.search(q=(0.0, 1.0), text="via", k=5))


class TokenTest(StoreCase):
    def test_hyphen_tokens(self):
        self.assertEqual(ragsearch.tokens("Cu-CMP 저항이 µ"), ["cu-cmp", "cu", "cmp", "저항이"])

    def test_query_preprocess(self):
        self.assertEqual(ragsearch.query_tokens('"Cu-CMP" -Ru or via'), ["cu-cmp", "cu", "cmp", "ru", "via"])
        self.assertEqual(ragsearch.query_tokens('  " - " '), [])

    def test_hyphen_part_and_no_stemming(self):
        self.add("h", vec=(0.0, 1.0), content="# Cu-CMP 결과\n저항이 높다")
        self.add("x", vec=(1.0, 0.0), content="other")
        rows = self.search(text="CMP")
        self.assertEqual(rows[0]["chunk_id"], "h")
        self.assertEqual(rows[0]["text_pos"], 1)
        self.assertTrue(all(r["text_pos"] is None for r in self.search(text="저항")))
        self.assertEqual(self.search(text="-저항이")[0]["chunk_id"], "h")


class SiblingFacetTest(StoreCase):
    def test_siblings_order_and_columns(self):
        fa, fb = "a" * 64, "b" * 64
        self.add("b2", file_id=fb, seq=2)
        self.add("a3", file_id=fa, seq=3)
        self.add("a1", file_id=fa, seq=1)
        self.add("c1", file_id="c" * 64, seq=1)
        rows = ragsearch.siblings(self.con, [fb, fa, fa], MODEL)
        self.assertEqual(self.ids(rows), ["a1", "a3", "b2"])
        self.assertEqual(set(rows[0]), {"chunk_id", "file_id", "seq", "content", "labels",
                                        "slide_image_bucket", "slide_image_path"})
        self.assertEqual(ragsearch.siblings(self.con, [], MODEL), [])

    def test_facets_sorted(self):
        self.add("1", lab=labels(Metal=["Cu", "Ru"]))
        self.add("2", lab=labels(Metal=["Cu"], Layer="M1"))
        self.add("3", lab=labels(scheme=("SADP",), Metal=["Cu"]))
        self.assertEqual(ragsearch.facets(self.con, MODEL), [
            {"axis": "Metal", "value": "Cu", "n": 3},
            {"axis": "Metal", "value": "Ru", "n": 1},
            {"axis": "Patterning/scheme", "value": "SAQP", "n": 2},
            {"axis": "Patterning/scheme", "value": "SADP", "n": 1},
        ])
        self.assertEqual(ragsearch.count(self.con, MODEL), 3)


if __name__ == "__main__":
    unittest.main()
