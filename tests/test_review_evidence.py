"""검수 교정 근거(evidence·reason): apply 검증·저장, 열 추가 마이그레이션, 검수 화면 DATA.file_ctx.

모든 값은 가짜다. 사내 파일·작업 폴더를 읽지 않는다.
"""
import json
import os
import re
import shutil
import sqlite3
import tempfile
import unittest

from labelbot import finals, review, store, taxonomy
from labelbot.questions import all_questions

RUN = "20261005T010203-ev01"
SHA = "b" * 64
FILE_A, FILE_B = "fa" * 8, "fb" * 8


def _tax():
    tax = taxonomy.Taxonomy()
    a = taxonomy.Axis("예시축A", "분류", True, False, False, "", "", "")
    a.values = [taxonomy.Value("값-1", None, "", "", "", 2), taxonomy.Value("값-2", None, "", "", "", 3)]
    tax.axes = [a]
    tax.questions = [taxonomy.Question("Q-COM-001", "가짜 질문", "공통", "1", 2)]
    tax.sheet_hashes = {"taxonomy": "t" * 16, "questions": "q" * 16}
    return tax


class _FakeWs:
    def __init__(self, root):
        self.root = root
        self.config = {"limits": {"images_per_chunk": 0, "questions_per_chunk": 5},
                       "flag": {"unknown_ratio_min": 0.5, "confidence_min": 0.7}}

    def path(self, *parts):
        return os.path.join(self.root, *parts)


def _seed(con):
    con.execute("INSERT INTO runs(run_id, command) VALUES(?, 'run')", (RUN,))
    con.execute("INSERT INTO files(file_id, file_name, rel_path, title) VALUES(?,?,?,?)",
                (FILE_A, "가짜A SF1.0 평가.txt", "폴더/가짜A SF1.0 평가.txt", "가짜 문서 제목 SF1.0 세대"))
    con.execute("INSERT INTO files(file_id, file_name, rel_path, title) VALUES(?,?,?,?)",
                (FILE_B, "가짜B.txt", "폴더/가짜B.txt", None))
    rows = (("c1", FILE_A, 1, "첫 슬라이드 제목", "본문 첫 줄\n장비 조건  변경 평가"),
            ("c2", FILE_A, 2, "둘째 제목", "다른 슬라이드의 결론 문장"),
            ("c3", FILE_B, 1, "다른 파일", "다른 파일의 결론 문장"))
    for cid, fid, seq, title, text in rows:
        con.execute("INSERT INTO chunks(chunk_id, file_id, seq, title, text, text_hash, images, warnings)"
                    " VALUES(?,?,?,?,?,?,'[]','[]')", (cid, fid, seq, title, text, "h-" + cid))
    for cid in ("c1", "c3"):
        con.execute("INSERT INTO flagged_chunks(run_id, chunk_id, reason_codes, text_hash) VALUES(?,?,?,?)",
                    (RUN, cid, '["UNKNOWN_HIGH"]', "h-" + cid))
        con.execute("INSERT INTO labels(run_id, chunk_id, kind, key, value, status) VALUES(?,?,?,?,?,?)",
                    (RUN, cid, "chunk_type", "", "내용", "value"))
        con.execute("INSERT INTO labels(run_id, chunk_id, kind, key, value, status) VALUES(?,?,?,?,?,?)",
                    (RUN, cid, "axis", "예시축A", '["unknown"]', "unknown"))
    con.commit()


def _corr(cid="c1", **kw):
    d = {"chunk_id": cid, "target": "axis", "key": "예시축A", "value": ["값-1"], "status": "corrected"}
    d.update(kw)
    return d


class EvidenceApplyTest(unittest.TestCase):
    def setUp(self):
        self.con = store.connect(":memory:")
        _seed(self.con)
        self.tax = _tax()

    def tearDown(self):
        self.con.close()

    def apply(self, corrections):
        doc = {"kind": "review", "run_id": RUN, "corrections": corrections, "chunk_status": [], "synonyms": []}
        return review._apply_review(self.con, self.tax, doc, SHA)

    def row(self, cid="c1"):
        return self.con.execute("SELECT * FROM corrections WHERE review_run_id=? AND chunk_id=? AND target_kind='axis'",
                                (RUN, cid)).fetchone()

    def test_valid_same_and_other_chunk_and_file_context(self):
        ev = [{"source": "chunk", "chunk_id": "c1", "quote": "장비 조건\n 변경"},
              {"source": "chunk", "chunk_id": "c2", "quote": "결론 문장"},
              {"source": "doc_title", "quote": "SF1.0 세대"}]
        code, n, drops = self.apply([_corr(evidence=ev, reason="  문서 제목의\n세대   표기로 판단 ")])
        self.assertEqual((code, n, drops), ("OK", 1, {}))
        r = self.row()
        self.assertEqual(json.loads(r["evidence"]), [
            {"source": "chunk", "chunk_id": "c1", "slide_no": 1, "quote": "장비 조건 변경"},
            {"source": "chunk", "chunk_id": "c2", "slide_no": 2, "quote": "결론 문장"},
            {"source": "doc_title", "chunk_id": None, "slide_no": None, "quote": "SF1.0 세대"}])
        self.assertEqual(r["reason"], "문서 제목의 세대 표기로 판단")
        self.assertEqual(r["evidence_dropped"], 0)

    def test_file_name_and_title_quote(self):
        ev = [{"source": "file_name", "quote": "SF1.0 평가"}, {"source": "chunk", "chunk_id": "c2", "quote": "둘째 제목"}]
        self.apply([_corr(evidence=ev)])
        self.assertEqual([x["source"] for x in json.loads(self.row()["evidence"])], ["file_name", "chunk"])

    def test_invalid_items_dropped_and_counted(self):
        ev = [{"source": "chunk", "chunk_id": "c3", "quote": "결론 문장"},      # 다른 파일
              {"source": "chunk", "chunk_id": "없는chunk", "quote": "결론 문장"},  # 이 DB에 없음
              {"source": "chunk", "chunk_id": "c1", "quote": "본문에 없는 문장"},
              {"source": "slide", "quote": "형식 오류"},
              {"source": "chunk", "chunk_id": "c1", "quote": "가" * 301},
              "문자열"]
        code, n, drops = self.apply([_corr(evidence=ev, reason=7)])
        self.assertEqual(code, "OK")
        self.assertEqual(drops, {"EVIDENCE_OTHER_FILE": 2, "EVIDENCE_QUOTE_NOT_FOUND": 1, "EVIDENCE_FORMAT": 3})
        r = self.row()
        self.assertIsNone(r["evidence"])
        self.assertIsNone(r["reason"])
        self.assertEqual(r["evidence_dropped"], 6)

    def test_doc_title_missing_and_max_items(self):
        code, _, drops = self.apply([_corr(cid="c3", evidence=[{"source": "doc_title", "quote": "제목"}])])
        self.assertEqual(drops, {"EVIDENCE_QUOTE_NOT_FOUND": 1})
        ev = [{"source": "chunk", "chunk_id": "c1", "quote": "본문 첫 줄"}] * 4
        _, _, drops = self.apply([_corr(evidence=ev)])
        self.assertEqual(drops, {"EVIDENCE_FORMAT": 1})
        self.assertEqual(len(json.loads(self.row()["evidence"])), 3)
        _, _, drops = self.apply([_corr(evidence={"source": "chunk"})])
        self.assertEqual(drops, {"EVIDENCE_FORMAT": 1})
        self.assertEqual(self.row()["evidence_dropped"], 1)

    def test_reason_trimmed_and_capped(self):
        self.apply([_corr(reason="이유 " * 200)])
        r = self.row()
        self.assertEqual(r["reason"], ("이유 " * 100).strip())  # 300자에서 자르고 끝 공백을 지운다
        self.assertIsNone(r["evidence"])
        self.assertIsNone(r["evidence_dropped"])

    def test_no_evidence_path_unchanged(self):
        code, n, drops = self.apply([_corr()])
        self.assertEqual((code, n, drops), ("OK", 1, {}))
        r = self.row()
        self.assertEqual((r["evidence"], r["reason"], r["evidence_dropped"]), (None, None, None))
        self.assertEqual(json.loads(r["human_value"]), ["값-1"])

    def test_generated_question_correction_not_recheck(self):
        # 생성 질문(Q-GEN) 교정도 export와 같은 질문 문구 출처로 해시를 저장해야 재검수로 뜨지 않는다.
        self.con.execute("INSERT INTO gen_questions(qid, chunk_id, axis, value, text, prompt_version, created_at)"
                         " VALUES('Q-GEN-1','c1','예시축A','값-1','생성된 가짜 질문','v','t')")
        self.con.execute("INSERT INTO labels(run_id, chunk_id, kind, key, value, status) VALUES(?,?,?,?,?,?)",
                         (RUN, "c1", "answer", "Q-GEN-1", "아니오", "value"))
        self.con.commit()
        self.apply([{"chunk_id": "c1", "target": "answer", "key": "Q-GEN-1", "value": "예", "status": "corrected"}])
        texts = {q.qid: q.text for q in all_questions(self.con, self.tax)}
        a = finals.final_labels(self.con, RUN, ["c1"], texts)["c1"]["answers"]["Q-GEN-1"]
        self.assertEqual((a["answer"], a["review"]), ("예", finals.CORRECTED))

    def test_drop_codes_reach_apply_inbox(self):
        d = tempfile.mkdtemp(prefix="labelbot_ev_")
        self.addCleanup(shutil.rmtree, d, True)
        ws = _FakeWs(d)
        os.makedirs(ws.path("inbox"))
        os.makedirs(ws.path("inputs"))
        doc = {"kind": "review", "run_id": RUN, "chunk_status": [], "synonyms": [],
               "corrections": [_corr(evidence=[{"source": "chunk", "chunk_id": "c3", "quote": "결론 문장"}])]}
        with open(ws.path("inbox", "review_x.json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)
        res = review.apply_inbox(ws, self.con, self.tax)
        self.assertEqual([(r[1], r[2]) for r in res], [("OK", 1), ("EVIDENCE_OTHER_FILE", 1)])


class EvidenceMigrationTest(unittest.TestCase):
    def test_old_db_gets_columns(self):
        d = tempfile.mkdtemp(prefix="labelbot_evmig_")
        self.addCleanup(shutil.rmtree, d, True)
        p = os.path.join(d, "work.sqlite")
        old = sqlite3.connect(p)
        old.execute("CREATE TABLE corrections (review_run_id TEXT, chunk_id TEXT, target_kind TEXT, target_key TEXT,"
                    " human_value TEXT, bot_value TEXT, review_status TEXT, recheck INTEGER, text_hash TEXT,"
                    " question_hash TEXT, file_sha256 TEXT, applied_at TEXT,"
                    " PRIMARY KEY(review_run_id, chunk_id, target_kind, target_key))")
        old.execute("INSERT INTO corrections(review_run_id, chunk_id, target_kind, target_key, human_value)"
                    " VALUES('R', 'c1', 'axis', 'k', '[\"v\"]')")
        old.commit()
        old.close()
        con = store.connect(p)
        try:
            cols = {r[1] for r in con.execute("PRAGMA table_info(corrections)")}
            row = con.execute("SELECT human_value, evidence, reason, evidence_dropped FROM corrections").fetchone()
        finally:
            con.close()
        self.assertTrue({"evidence", "reason", "evidence_dropped"} <= cols)
        self.assertEqual(tuple(row), ('["v"]', None, None, None))


class EvidenceScreenDataTest(unittest.TestCase):
    def test_review_data_has_file_ctx(self):
        d = tempfile.mkdtemp(prefix="labelbot_evscr_")
        self.addCleanup(shutil.rmtree, d, True)
        con = store.connect(":memory:")
        self.addCleanup(con.close)
        _seed(con)
        path, n = review.build_review(_FakeWs(d), con, RUN, _tax())
        with open(path, encoding="utf-8") as f:
            html = f.read()
        data = json.loads(re.search(r"const DATA = (.*);\n", html).group(1))
        self.assertEqual(n, 2)
        self.assertEqual(sorted(data["file_ctx"]), sorted([FILE_A, FILE_B]))
        a = data["file_ctx"][FILE_A]
        self.assertEqual((a["file_name"], a["rel_path"], a["doc_title"]),
                         ("가짜A SF1.0 평가.txt", "폴더/가짜A SF1.0 평가.txt", "가짜 문서 제목 SF1.0 세대"))
        # 불량이 아닌 c2도 같은 파일 슬라이드로 들어간다(순서대로).
        self.assertEqual([(s["chunk_id"], s["slide_no"], s["title"]) for s in a["slides"]],
                         [("c1", 1, "첫 슬라이드 제목"), ("c2", 2, "둘째 제목")])
        self.assertEqual(data["file_ctx"][FILE_B]["doc_title"], "")
        self.assertEqual((data["evidence_max"], data["evidence_quote_max"], data["evidence_reason_max"]), (3, 300, 300))
        # 기존 키는 그대로다.
        for k in ("chunks", "file_slides", "axes", "questions", "revisit_rules"):
            self.assertIn(k, data)


if __name__ == "__main__":
    unittest.main()
