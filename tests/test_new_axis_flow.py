"""새 축 E2E 회귀: taxonomy에 축 하나를 더하면 분류~내보내기·벡터 적재·검수·결과 화면·diff·selfcheck까지 따라간다.

합성 taxonomy(임시 폴더의 taxonomy.json, 저장소 taxonomy.json은 열지 않는다)에 새 축 "평가 조건"(값 POR, Split)과 그 질문 행을 더하고
mock LLM으로 run_all을 한 번 돌린다. 값 이름은 더미 본문에 실제로 나오는 낱말이라 mock 분류가 새 축 값을 붙인다.
"""
import contextlib
import io
import json
import os
import shutil
import sqlite3
import tempfile
import unittest

from labelbot import (classify, cli, dashboard, embed, pipeline, prompts, questions, review, selfcheck,
                      store, vectorpush)
from labelbot.mock import MockChatTransport, MockEmbedTransport
from labelbot.workspace import Workspace
from tests.test_pipeline import DUMMY_DIR, responder
from tests.test_taxonomy import axis_row, base_sheets, build, parse, tax_row

NEW = "평가 조건"
NEW_QID = "Q-NEW-001"


def sheets_with_new_axis():
    s = base_sheets()
    s["taxonomy"] += [axis_row(NEW, definition="평가 대조군·실험군을 가르는 조건"), tax_row(NEW, "POR"), tax_row(NEW, "Split")]
    s["questions"].append([NEW_QID, "POR 조건 대비 평가인가.", "%s=POR" % NEW, 3])
    return s


def page_data(path):
    with open(path, encoding="utf-8") as f:
        html = f.read()
    return json.JSONDecoder().raw_decode(html.split("const DATA = ", 1)[1])[0]


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue().splitlines(), err.getvalue()


class NewAxisFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="labelbot_ws_")
        cls.tax_path = os.path.join(cls.dir, "taxonomy.json")
        with open(cls.tax_path, "wb") as f:
            f.write(build(sheets_with_new_axis()))
        cfg = {"taxonomy_path": cls.tax_path, "input_root": DUMMY_DIR,
               "llm": {"transport": "mock", "model": "mock", "max_retries": 1},
               "embedding": {"transport": "mock"}, "supabase": {"enabled": False}}
        with open(os.path.join(cls.dir, "pipeline.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        cls.ws = Workspace(cls.dir)
        cls.transport = MockChatTransport(responder)
        cls.run_id, _ = pipeline.run_all(cls.ws, DUMMY_DIR, transport=cls.transport, use_feedback=False)
        cls.tax, _ = pipeline.load_taxonomy(cls.ws)
        cls.con = store.connect(cls.ws.work_db)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()
        shutil.rmtree(cls.dir, ignore_errors=True)

    # 1. 분류 프롬프트·검증기
    def test_classify_prompt_contains_new_axis(self):
        block = classify.taxonomy_block(self.tax)
        self.assertIn("### %s" % NEW, block)
        self.assertIn("평가 대조군·실험군을 가르는 조건", block)
        self.assertIn("- POR", block)
        sent = [b for b in self.transport.requests if "### %s" % NEW in json.dumps(b, ensure_ascii=False)]
        self.assertGreater(len(sent), 0, "실제 LLM 요청 본문에 새 축이 들어가야 한다")

    def test_validator_requires_new_axis(self):
        validate = classify._validator(self.tax)
        axes = {a.name: {"values": ["해당 없음"], "evidence": "", "confidence": 0.9} for a in self.tax.active_axes()}
        obj = {"chunk_type": "내용", "axes": axes}
        self.assertEqual(validate(obj), (True, None))
        del axes[NEW]
        self.assertEqual(validate(obj), (False, "AXIS_MISSING"))

    def test_classify_prompt_grows_with_new_axis(self):
        base = parse(base_sheets())
        base_block, new_block = classify.taxonomy_block(base), classify.taxonomy_block(self.tax)
        self.assertGreater(len(new_block), len(base_block))

        def prompt_len(tax):
            msgs = prompts.render("classify", {"taxonomy": classify.taxonomy_block(tax), "chunk_text": "본문",
                                               "response_format": classify.RESPONSE_FORMAT})
            return sum(len(m["content"]) for m in msgs)

        self.assertGreater(prompt_len(self.tax), prompt_len(base))

    # 2. labels
    def test_labels_have_new_axis_rows_for_content_chunks(self):
        n_content = self.con.execute(
            "SELECT COUNT(DISTINCT chunk_id) FROM labels WHERE run_id=? AND kind='axis' AND key='불량 모드'",
            (self.run_id,)).fetchone()[0]
        rows = self.con.execute(
            "SELECT chunk_id, value FROM labels WHERE run_id=? AND kind='axis' AND key=?", (self.run_id, NEW)).fetchall()
        self.assertGreater(n_content, 0)
        self.assertEqual(len({r[0] for r in rows}), n_content)
        vals = {v for r in rows for v in json.loads(r[1])}
        self.assertTrue({"POR", "Split"} & vals, "mock이 새 축 값을 하나는 붙여야 한다: %s" % vals)

    # 3. 질문 매핑
    def test_question_mapping_includes_new_axis_question(self):
        q = next(q for q in self.tax.questions if q.qid == NEW_QID)
        self.assertEqual(tuple(q.target), (NEW, "POR"))
        hit, _ = questions.map_questions(self.tax, {NEW: {"values": ["POR"]}}, 50)
        self.assertIn(NEW_QID, [x.qid for x in hit])
        miss, _ = questions.map_questions(self.tax, {NEW: {"values": ["Split"]}}, 50)
        self.assertNotIn(NEW_QID, [x.qid for x in miss])

    def test_new_axis_question_answered_for_chunks_with_value(self):
        por = {r[0] for r in self.con.execute(
            "SELECT chunk_id FROM labels WHERE run_id=? AND kind='axis' AND key=? AND value LIKE '%POR%'",
            (self.run_id, NEW))}
        answered = {r[0] for r in self.con.execute(
            "SELECT chunk_id FROM labels WHERE run_id=? AND kind='answer' AND key=?", (self.run_id, NEW_QID))}
        self.assertGreater(len(por), 0)
        self.assertTrue(answered & por, "POR가 붙은 chunk 중 일부는 새 축 질문 답이 있어야 한다")
        self.assertTrue(answered <= por, "POR가 없는 chunk에는 새 축 질문이 붙지 않는다")

    # 4. 화면 DATA
    def test_review_data_has_editable_new_axis(self):
        path, _ = review.build_review(self.ws, self.con, self.run_id, self.tax)
        by = {a["name"]: a for a in page_data(path)["axes"]}
        self.assertIn(NEW, by)
        self.assertTrue(by[NEW]["editable"])
        self.assertNotIn("pending", by[NEW])
        self.assertEqual([v["name"] for v in by[NEW]["values"]], ["POR", "Split"])

    def test_results_data_axis_status_has_new_axis_not_pending(self):
        path, _ = dashboard.build_results(self.ws, self.con, self.run_id, self.tax)
        data = page_data(path)
        by = {a["name"]: a for a in data["axes"]}
        self.assertIn(NEW, by)
        self.assertFalse(by[NEW]["pending"])
        self.assertGreater(by[NEW]["states"]["value"], 0)
        self.assertEqual(data["new_axes"], [])

    # 5. 교정
    def test_correction_on_new_axis_applies(self):
        cid = self.con.execute("SELECT chunk_id FROM flagged_chunks WHERE run_id=? ORDER BY chunk_id",
                               (self.run_id,)).fetchone()[0]
        doc = {"kind": "review", "run_id": self.run_id, "chunk_status": [], "synonyms": [],
               "corrections": [{"chunk_id": cid, "target": "axis", "key": NEW, "value": ["Split"], "status": "corrected"}]}
        path = self.ws.path("inbox", "review_new_axis.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)
        self.addCleanup(os.remove, path)
        res = review.apply_inbox(self.ws, self.con, self.tax, kind="review")
        codes = [r[1] for r in res]
        self.assertIn("OK", codes)
        self.assertNotIn(review.AXIS_NOT_IN_RUN, codes)
        keys = [r[0] for r in self.con.execute(
            "SELECT target_key FROM corrections WHERE review_run_id=? AND chunk_id=? AND target_kind='axis'",
            (self.run_id, cid))]
        self.assertEqual(keys, [NEW])

    # 6. 내보내기·벡터 적재
    def test_export_contains_new_axis(self):
        out = sqlite3.connect(os.path.join(self.dir, "out", "labeling.sqlite"))
        try:
            n_labels = out.execute("SELECT COUNT(*) FROM facet_labels WHERE axis=?", (NEW,)).fetchone()[0]
            values = {r[0] for r in out.execute("SELECT value FROM facet_values WHERE axis=?", (NEW,))}
            qs = {r[0] for r in out.execute("SELECT question_id FROM questions")}
        finally:
            out.close()
        self.assertGreater(n_labels, 0)
        self.assertEqual(values, {"POR", "Split"})
        self.assertIn(NEW_QID, qs)
        with open(os.path.join(self.dir, "out", "SCHEMA.md"), encoding="utf-8") as f:
            self.assertIn(NEW, f.read())

    def test_vector_payload_axes_include_new_axis(self):
        embed.embed(self.ws, self.con, self.run_id, transport=MockEmbedTransport())

        class Sink:
            def __init__(self):
                self.rows = []

            def send(self, rows):
                self.rows += rows

        sink = Sink()
        self.ws.config["supabase"].update({"enabled": True, "url": "https://example-proj.supabase.co"})
        try:
            vectorpush.push(self.ws, self.con, self.run_id, sink=sink)
        finally:
            self.ws.config["supabase"].update({"enabled": False, "url": ""})
        self.assertGreater(len(sink.rows), 0)
        self.assertTrue(all(NEW in r["labels"]["axes"] for r in sink.rows))
        self.assertTrue(any({"POR", "Split"} & set(r["labels"]["axes"][NEW]) for r in sink.rows))

    # 7. diff·selfcheck
    def test_run_meta_signature_has_new_axis(self):
        sig = {x["name"]: x for x in json.loads(store.meta_get(self.con, "axes_signature"))}
        self.assertEqual((sig[NEW]["n_values"], sig[NEW]["active"]), (2, True))

    def test_taxonomy_diff_reports_no_change_after_run(self):
        code, lines, _ = run_cli("taxonomy-diff", "--workspace", self.dir)
        self.assertEqual(code, 0)
        d = json.loads(lines[0])
        self.assertEqual((d["added"], d["removed"], d["changed"], d["values_added"]), ([], [], [], {}))
        self.assertTrue(lines[1].endswith("→ 변경 없음"))

    def test_selfcheck_axes_item_has_no_warn_for_new_axis(self):
        lines = []
        selfcheck.run(self.ws, out=lines.append)
        row = next(x for x in lines if x.startswith("taxonomy_axes"))
        self.assertNotIn(NEW, row)  # 정의·질문이 있어 어떤 WARN에도 이름이 나오지 않는다
        self.assertNotIn("정의·판정 규칙 없는", row)


if __name__ == "__main__":
    unittest.main()
