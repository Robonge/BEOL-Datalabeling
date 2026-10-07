"""화면이 실행 기준 축을 따르는지(pending·removed 축, AXIS_NOT_IN_RUN)와 첫 공통 질문 ID 도출 테스트.

합성 taxonomy(임시 폴더의 taxonomy.json)로 mock 실행을 한 번 돌린 뒤, taxonomy에 축을 더하고 빼서 화면 DATA와 apply를 본다.
"""
import json
import os
import shutil
import tempfile
import unittest

from labelbot import dashboard, pipeline, review, store
from labelbot.mock import MockChatTransport
from labelbot.workspace import Workspace
from tests.test_pipeline import DUMMY_DIR, responder
from tests.test_taxonomy import axis_row, base_sheets, build, parse, tax_row

NEW_AXIS, GONE_AXIS = "신규 축", "의사결정 상태"


def page_data(path):
    with open(path, encoding="utf-8") as f:
        html = f.read()
    return json.JSONDecoder().raw_decode(html.split("const DATA = ", 1)[1])[0]


def after_sheets():
    """실행 뒤 taxonomy: 새 축 하나를 더하고 상태 축 하나를 뺀다."""
    s = base_sheets()
    s["taxonomy"] = [r for r in s["taxonomy"] if r[0] != GONE_AXIS]
    s["taxonomy"] += [axis_row(NEW_AXIS), tax_row(NEW_AXIS, "A1"), tax_row(NEW_AXIS, "A2")]
    return s


class RunAxesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="labelbot_ws_")
        cls.tax_path = os.path.join(cls.dir, "taxonomy.json")
        with open(cls.tax_path, "wb") as f:
            f.write(build(base_sheets()))
        cfg = {"taxonomy_path": cls.tax_path, "input_root": DUMMY_DIR,
               "llm": {"transport": "mock", "model": "mock", "max_retries": 1},
               "embedding": {"transport": "mock"}, "supabase": {"enabled": False}}
        with open(os.path.join(cls.dir, "pipeline.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        cls.ws = Workspace(cls.dir)
        cls.run_id, _ = pipeline.run_all(cls.ws, DUMMY_DIR, transport=MockChatTransport(responder), use_feedback=False)
        with open(cls.tax_path, "wb") as f:
            f.write(build(after_sheets()))
        cls.tax, _ = pipeline.load_taxonomy(cls.ws)
        cls.con = store.connect(cls.ws.work_db)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_run_axes_are_the_labeled_axes(self):
        expect = {"구조/레이어", "불량 모드", GONE_AXIS}  # 비활성 축(제품·세대)은 라벨링하지 않은 축이다
        self.assertEqual(review.run_axes(self.con, self.run_id), expect)  # 마지막 run: meta
        later = pipeline.start_run(self.con, self.ws, "run")  # 더 나중 run이 생기면 labels 축 행으로 본다
        try:
            self.assertEqual(review.run_axes(self.con, self.run_id), expect)
        finally:
            self.con.execute("DELETE FROM runs WHERE run_id=?", (later,))
            self.con.commit()

    def test_pipeline_writes_per_run_signature(self):
        self.assertEqual(store.meta_get(self.con, "axes_signature:" + self.run_id),
                         store.meta_get(self.con, "axes_signature"))

    def test_per_run_signature_preferred_over_labels(self):
        """비마지막 실행의 활성 축은 값이 전부 na여도(라벨 행만 보면 '대기') 실행별 서명이 있으면 라벨링한 축이다."""
        later = pipeline.start_run(self.con, self.ws, "run")
        self.con.execute("UPDATE labels SET status='na', confidence=NULL WHERE run_id=? AND kind='axis' AND key=?",
                         (self.run_id, "불량 모드"))
        try:
            self.assertIn("불량 모드", review.run_axes(self.con, self.run_id))
        finally:
            self.con.rollback()
            self.con.execute("DELETE FROM runs WHERE run_id=?", (later,))
            self.con.commit()

    def test_inactive_axis_gets_inactive_flag(self):
        s = after_sheets()
        s["taxonomy"] = [r for r in s["taxonomy"] if not (r[0] == "구조/레이어" and r[1] is not None)]  # 값 없는 축 = 비활성
        data_tax = parse(s)
        axes = review.review_axes(self.con, self.run_id, data_tax, [])
        by = {a["name"]: a for a in axes}
        self.assertTrue(by["구조/레이어"].get("inactive"))
        self.assertFalse(by["구조/레이어"].get("removed"))
        self.assertTrue(by[GONE_AXIS].get("removed"))
        self.assertFalse(by[GONE_AXIS].get("inactive"))

    def test_review_data_marks_pending_and_removed(self):
        path, n = review.build_review(self.ws, self.con, self.run_id, self.tax)
        self.assertGreater(n, 0)
        data = page_data(path)
        by = {a["name"]: a for a in data["axes"]}
        self.assertEqual(set(by), {"구조/레이어", "불량 모드", NEW_AXIS, GONE_AXIS})
        self.assertTrue(by["구조/레이어"]["editable"])
        self.assertNotIn("pending", by["구조/레이어"])
        self.assertEqual((by[NEW_AXIS]["editable"], by[NEW_AXIS]["pending"]), (False, True))
        self.assertEqual([v["name"] for v in by[NEW_AXIS]["values"]], ["A1", "A2"])
        self.assertEqual((by[GONE_AXIS]["editable"], by[GONE_AXIS]["removed"]), (False, True))
        self.assertEqual(by[GONE_AXIS]["kind"], "상태")
        self.assertEqual(data["primary_qid"], "Q-COM-001")

    def test_apply_skips_axis_not_in_run(self):
        cid = self.con.execute("SELECT chunk_id FROM flagged_chunks WHERE run_id=? ORDER BY chunk_id",
                               (self.run_id,)).fetchone()[0]
        doc = {"kind": "review", "run_id": self.run_id, "chunk_status": [], "synonyms": [],
               "corrections": [
                   {"chunk_id": cid, "target": "axis", "key": NEW_AXIS, "value": ["A1"], "status": "corrected"},
                   {"chunk_id": cid, "target": "axis", "key": "구조/레이어", "value": ["M1"], "status": "corrected"}]}
        path = self.ws.path("inbox", "review_axes.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)
        self.addCleanup(os.remove, path)
        res = review.apply_inbox(self.ws, self.con, self.tax, kind="review")
        codes = {r[1]: r[2] for r in res}
        self.assertEqual(codes.get("OK"), 1)
        self.assertEqual(codes.get(review.AXIS_NOT_IN_RUN), 1)
        keys = [r[0] for r in self.con.execute(
            "SELECT target_key FROM corrections WHERE review_run_id=? AND target_kind='axis'", (self.run_id,))]
        self.assertEqual(keys, ["구조/레이어"])

    def test_results_data_new_axes(self):
        path, _ = dashboard.build_results(self.ws, self.con, self.run_id, self.tax)
        data = page_data(path)
        self.assertEqual(data["new_axes"], [NEW_AXIS])
        by = {a["name"]: a for a in data["axes"]}
        self.assertTrue(by[NEW_AXIS]["pending"])
        self.assertFalse(by["구조/레이어"]["pending"])
        self.assertEqual(data["primary_qid"], "Q-COM-001")
        self.assertEqual(data["kpi"]["answers"], sum(1 for c in data["chunks"] if "Q-COM-001" in c["answers"]))

    def test_old_run_without_axis_info_is_all_editable(self):
        old = pipeline.start_run(self.con, self.ws, "ingest")  # 라벨 없는 실행, 마지막 run도 아니다
        try:
            self.assertIsNone(review.run_axes(self.con, old))
            axes = review.review_axes(self.con, old, self.tax, [])
            self.assertTrue(all(a["editable"] for a in axes))
            self.assertFalse(any(a.get("pending") or a.get("removed") for a in axes))
        finally:
            self.con.execute("DELETE FROM runs WHERE run_id=?", (old,))
            self.con.commit()


class PrimaryQidTest(unittest.TestCase):
    def test_first_common_question(self):
        self.assertEqual(review.primary_qid(parse(base_sheets())), "Q-COM-001")

    def test_order_is_priority_then_id(self):
        s = base_sheets()
        s["questions"] += [["Q-COM-000", "나중 공통 질문.", "공통", 5], ["Q-COM-009", "먼저 공통 질문.", "공통", 0],
                           ["Q-COM-002", "같은 우선순위.", "공통", 0]]
        self.assertEqual(review.primary_qid(parse(s)), "Q-COM-002")

    def test_no_common_question(self):
        s = base_sheets()
        s["questions"] = [r for r in s["questions"] if r[2] != "공통"]
        self.assertIsNone(review.primary_qid(parse(s)))


if __name__ == "__main__":
    unittest.main()
