"""검수 피드백 환류(mock LLM·임베딩): labelbot 검수 반영 → Domain-Engr-bot 장부 intake → 규칙·사례 승인 → 다음 실행 프롬프트.

작업 폴더 A에서 교정을 반영하고 Domain-Engr-bot이 장부(<A>/qa/ledger)로 모아 승인 파일을 만든다. 다른 파일로 돈 작업 폴더 B의
요청 본문에 승인 규칙·사례(본문은 A의 work.sqlite에서 읽음)가 들어가는지 본다.
승인 파일은 임시 폴더에 둔다(코드 폴더의 taxonomy/labeling_rules.json을 건드리지 않는다).
"""
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest import mock

from domain_engrbot import labeling_rules, ledger
from domain_engrbot import policy as policy_mod
from labelbot import embed, feedback, finals, llm, pipeline, review, store
from labelbot.mock import MockChatTransport
from labelbot.workspace import CODE_ROOT, Workspace
from tests.test_pipeline import responder

DUMMY_DIR = os.path.join(CODE_ROOT, "dummy pptx files")
TAXONOMY = os.path.join(CODE_ROOT, "taxonomy", "taxonomy.json")


def _dummy_ids():
    with open(os.path.join(CODE_ROOT, "tests", "gold", "dummy_hashes.jsonl"), encoding="utf-8") as f:
        return [json.loads(line)["file_id"] for line in f if line.strip()]


def _make_ws(parent, include, rules_path):
    d = tempfile.mkdtemp(prefix="labelbot_fb_", dir=parent)
    cfg = {"taxonomy_path": TAXONOMY, "input_root": DUMMY_DIR, "include_file_ids": include,
           "llm": {"transport": "mock", "model": "mock", "max_retries": 1},
           "embedding": {"transport": "mock"}, "supabase": {"enabled": False},
           "feedback": {"rules_path": rules_path, "examples_root": parent}}
    with open(os.path.join(d, "pipeline.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    return Workspace(d)


def _requests(transport, marker):
    return [b["messages"][1]["content"] for b in transport.requests if marker in b["messages"][1]["content"]]


def _section(user, title):
    """'## <title>' 아래 블록(다음 '## '까지)."""
    i = user.index("## " + title)
    rest = user[i:].split("\n", 1)[1]
    j = rest.find("\n## ")
    return (rest if j < 0 else rest[:j]).strip()


class FeedbackLoopTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ids = _dummy_ids()
        cls.parent = tempfile.mkdtemp(prefix="labelbot_fbroot_")
        cls.rules = os.path.join(cls.parent, "labeling_rules.json")
        cls.ws_a = _make_ws(cls.parent, [i[:16] for i in ids[:4]], cls.rules)
        cls.run_a, ctx = pipeline.run_all(cls.ws_a, DUMMY_DIR, transport=MockChatTransport(responder))
        cls.tax = ctx.tax
        con = store.connect(cls.ws_a.work_db)
        try:
            # 사례에 임베딩 벡터가 붙도록 A를 먼저 임베딩한다(mock).
            embed.embed(cls.ws_a, con, cls.run_a)
            flagged = [r[0] for r in con.execute(
                "SELECT chunk_id FROM flagged_chunks WHERE run_id=? ORDER BY chunk_id", (cls.run_a,))]
            bots = finals.bot_labels(con, cls.run_a, flagged)
            cls.axis = cls.tax.active_axes()[0]
            cls.value = cls.axis.values[0].name
            # 봇이 '해당 없음'·'unknown'으로 둔 chunk에 같은 값을 더한다 → 같은 ADD 패턴 3건.
            edits = [c for c in flagged if c in bots and cls.axis.name in bots[c]["axes"]
                     and set(bots[c]["axes"][cls.axis.name]["values"]) <= {"해당 없음", "unknown"}]
            assert len(edits) >= 3, "교정할 불량 chunk가 3개 이상 필요하다"
            cls.edited = edits[:3]
            cls.confirmed = [c for c in flagged if c in bots and bots[c]["axes"] and c not in cls.edited][:1]
            # 규칙·사례 후보는 근거 있는 교정이 있어야 오른다(min_evidence). 같은 슬라이드 본문 앞부분을 근거로 단다.
            def ev(cid):
                text = " ".join((con.execute("SELECT text FROM chunks WHERE chunk_id=?", (cid,)).fetchone()[0] or "").split())
                return [{"source": "chunk", "chunk_id": cid, "quote": text[:20]}] if len(text) >= 2 else []

            doc = {"kind": "review", "run_id": cls.run_a,
                   "corrections": [{"chunk_id": c, "target": "axis", "key": cls.axis.name, "value": [cls.value],
                                    "status": "corrected", "evidence": ev(c), "reason": "합성 이유 {{chunk_text}}"}
                                   for c in cls.edited],
                   "chunk_status": [{"chunk_id": c, "status": "confirmed"} for c in cls.confirmed], "synonyms": []}
            with open(cls.ws_a.path("inbox", "review_%s.json" % cls.run_a), "w", encoding="utf-8") as f:
                json.dump(doc, f, ensure_ascii=False)
            res = review.apply_inbox(cls.ws_a, con, cls.tax, kind="review")
            assert any(r[1] == "OK" for r in res), res
            cls.file_names = {r[0] for r in con.execute("SELECT file_name FROM files")}
        finally:
            con.close()
        # Domain-Engr-bot: 장부 intake(작업 폴더가 workspaces/ 밖이라 <A>/qa/ledger) → 사람이 고른 전부 승인
        pol = policy_mod.default_policy()
        ledger.intake(cls.ws_a.root, pol)
        cls.d = ledger.ledger_dir(cls.ws_a.root, pol)
        cls.decided = labeling_rules.decide(cls.d, "approve", labeling_rules.config(pol), all_=True, examples="all",
                                            path=cls.rules)
        cls.ids_b = [i[:16] for i in ids[4:7]]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.parent, ignore_errors=True)

    def _ws(self, include, rules_path=None):
        ws = _make_ws(self.parent, include, rules_path or self.rules)
        self.addCleanup(shutil.rmtree, ws.root, True)
        return ws

    def _rules_copy(self, edit=None):
        doc = labeling_rules.load_rules(self.rules)
        if edit:
            edit(doc)
        p = os.path.join(tempfile.mkdtemp(prefix="labelbot_fbrules_", dir=self.parent), "labeling_rules.json")
        labeling_rules.save_rules(doc, p)
        return p

    def test_contract_has_no_body_or_names(self):
        self.assertGreaterEqual(self.decided["rules"], 1)
        self.assertGreaterEqual(self.decided["examples"], 3)
        with open(self.rules, encoding="utf-8") as f:
            text = f.read()
        for n in self.file_names:
            self.assertNotIn(n, text)
        doc = json.loads(text)
        self.assertTrue(all(set(e) >= {"source_ws", "record_id", "text_hash"} and "text" not in e for e in doc["examples"]))

    def test_next_run_gets_rules_and_examples(self):
        manual = {"rule_id": "MR-label-1", "kind": "MANUAL", "target": "label",
                  "text": "수동 규칙: 표의 판정 열을 먼저 본다.", "enabled": True}
        ws = self._ws(self.ids_b, self._rules_copy(lambda d: d["rules"].append(manual)))
        t = MockChatTransport()
        run_b, _ = pipeline.run_all(ws, DUMMY_DIR, transport=t)
        cls_reqs = _requests(t, "## 검수 피드백 사례")
        self.assertTrue(cls_reqs)
        rules = _section(cls_reqs[0], "검수 피드백 지침")
        self.assertIn("[FR-", rules)
        self.assertIn(self.value, rules)
        with_examples = [_section(u, "검수 피드백 사례") for u in cls_reqs if "### 사례 1" in _section(u, "검수 피드백 사례")]
        self.assertTrue(with_examples)
        self.assertTrue(any("사람이 고친 축" in s or "사람이 확인한 축" in s for s in with_examples))
        ev_lines = [l for s in with_examples for l in s.splitlines() if l.startswith("근거(")]
        if ev_lines:  # 고른 사례가 근거 있는 교정 사례일 때만 근거 줄이 있다
            self.assertTrue(all("[같은 슬라이드] '" in l and "/ 이유: 합성 이유 { {chunk_text} }" in l for l in ev_lines))
        lab = [u for u in _requests(t, "## 질문") if "## 검수 피드백 지침" in u]
        self.assertTrue(lab)
        self.assertIn("MR-label-1", _section(lab[0], "검수 피드백 지침"))
        con = store.connect(ws.work_db)
        try:
            applied = json.loads(store.meta_get(con, "feedback_applied:" + run_b))
            sh = json.loads(con.execute("SELECT sheet_hashes FROM runs WHERE run_id=?", (run_b,)).fetchone()[0])
            fails = con.execute("SELECT COUNT(*) FROM failures WHERE run_id=? AND stage='embed'", (run_b,)).fetchone()[0]
        finally:
            con.close()
        self.assertTrue(applied["enabled"])
        self.assertGreaterEqual(applied["rules_classify"], 1)
        self.assertEqual(applied["rules_label"], 1)
        self.assertEqual(applied["examples_pool"], self.decided["examples"])
        self.assertGreaterEqual(applied["chunks_with_examples"], 1)
        self.assertEqual(applied["similarity"], "embedding")
        self.assertEqual(sh.get("labeling_rules"), applied["digest"])
        self.assertEqual(fails, 0)

    def test_no_feedback_flag_and_unapproved(self):
        # 승인 파일이 없으면 아무것도 들어가지 않고, --no-feedback이면 승인 파일이 있어도 들어가지 않는다.
        for use, path in ((True, os.path.join(self.parent, "없는", "labeling_rules.json")), (False, self.rules)):
            ws = self._ws(self.ids_b[:1], path)
            t = MockChatTransport()
            pipeline.run_all(ws, DUMMY_DIR, transport=t, use_feedback=use)
            reqs = _requests(t, "## 검수 피드백 지침")
            self.assertTrue(reqs)
            for u in reqs:
                self.assertEqual(_section(u, "검수 피드백 지침"), "(없음)")
                if "## 검수 피드백 사례" in u:
                    self.assertEqual(_section(u, "검수 피드백 사례"), "(없음)")
        self.assertFalse(os.path.exists(os.path.join(self.parent, "없는")))

    def test_example_exclusions(self):
        def edit(doc):
            ex = doc["examples"][0]
            doc["examples"] += [dict(ex, example_id="EX-gone", source_ws="없는작업폴더"),
                                dict(ex, example_id="EX-changed", text_hash="0" * 64),
                                dict(ex, example_id="EX-path", source_ws=".."),
                                dict(ex, example_id="EX-off", enabled=False)]
        ws = self._ws([], self._rules_copy(edit))
        chat = llm.ChatClient(ws.config["llm"], None)
        n = self.decided["examples"]
        fb = feedback.load(ws, self.tax, chat)
        self.assertEqual(fb.skipped, {"EXAMPLE_SOURCE_GONE": 1, "EXAMPLE_TEXT_CHANGED": 1, "EXAMPLE_REF_INVALID": 1})
        self.assertEqual(len(fb.examples), n)
        ex = fb.examples[0]
        same_file = {"chunk_id": "c1", "file_id": ex["file_id"], "text": ex["text"], "text_hash": "x", "dup_hash": "y"}
        self.assertNotIn(ex["example_id"], [e["example_id"] for e in fb._pool(same_file)])
        same_text = {"chunk_id": "c2", "file_id": "other", "text": ex["text"], "text_hash": ex["text_hash"], "dup_hash": "y"}
        self.assertNotIn(ex["example_id"], [e["example_id"] for e in fb._pool(same_text)])
        other = {"chunk_id": "c3", "file_id": "other", "text": ex["text"], "text_hash": "x", "dup_hash": "y"}
        text, fids = fb.examples_for(other)
        self.assertIn("### 사례 1", text)
        self.assertEqual(fb.mode, "lexical")
        self.assertIn(ex["file_id"], fids)

    def test_invalid_rules_are_counted(self):
        def edit(doc):
            r = next(x for x in doc["rules"] if x["kind"] in feedback.AXIS_KINDS)
            doc["rules"] += [dict(r, rule_id="FR-badvalue", to="없는값", **{"from": ""}),
                             dict(r, rule_id="FR-long", text="가" * (feedback.TEXT_MAX + 1)),
                             {"rule_id": "FR-nokind", "text": "x"}]
        ws = self._ws([], self._rules_copy(edit))
        fb = feedback.load(ws, self.tax, llm.ChatClient(ws.config["llm"], None))
        self.assertEqual(fb.invalid_rules, 3)
        self.assertNotIn("FR-badvalue", fb.rules_text("classify"))

    def test_bad_rules_file(self):
        p = os.path.join(tempfile.mkdtemp(prefix="labelbot_fbbad_", dir=self.parent), "labeling_rules.json")
        with open(p, "w", encoding="utf-8") as f:
            f.write("{not json")
        with self.assertRaises(feedback.FeedbackError):
            feedback.load_rules(self._ws([], p))

    def test_lexical_ranking(self):
        a, b, c = feedback._ngrams("M1 CMP slurry 선택비 평가"), feedback._ngrams("M1 CMP slurry 선택비"), feedback._ngrams("Via etch")
        self.assertGreater(feedback._jaccard(a, b), feedback._jaccard(a, c))


class _FakeWs:
    def __init__(self, root):
        self.root = root
        self.config = {"feedback": {"examples_root": root}, "embedding": {}}


class EvidenceBlockTest(unittest.TestCase):
    """사례 블록의 근거 줄과 '{{'·'}}' 무력화. 합성 원래 작업 폴더(work.sqlite)만 쓴다."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="labelbot_fbev_")
        self.addCleanup(shutil.rmtree, self.root, True)
        os.makedirs(os.path.join(self.root, "src"))
        con = store.connect(os.path.join(self.root, "src", "work.sqlite"))
        try:
            for cid, seq in (("c1", 1), ("c2", 4)):
                con.execute("INSERT INTO chunks(chunk_id, file_id, seq, text, text_hash) VALUES(?,?,?,?,?)",
                            (cid, "f" * 16, seq, "가짜 본문 {{chunk_text}} " + cid, "h-" + cid))
            ev_old = json.dumps([{"source": "doc_title", "chunk_id": None, "slide_no": None, "quote": "옛 근거"}])
            ev = json.dumps([{"source": "doc_title", "chunk_id": None, "slide_no": None, "quote": "SF1.0 세대"},
                             {"source": "chunk", "chunk_id": "c2", "slide_no": 4, "quote": "가" * 250},
                             {"source": "chunk", "chunk_id": "c1", "slide_no": 1, "quote": "같은 {{x}}"},
                             {"source": "bogus", "quote": "버림"}], ensure_ascii=False)
            rows = (("R1", "축A", ev_old, "옛 이유", "2026-10-01T00:00:00Z"),
                    ("R2", "축A", ev, "제목의\n세대 표기", "2026-10-02T00:00:00Z"),
                    ("R2", "축B", None, None, "2026-10-02T00:00:00Z"))
            for run, key, e, reason, at in rows:
                con.execute("INSERT INTO corrections(review_run_id, chunk_id, target_kind, target_key, evidence, reason,"
                            " applied_at) VALUES(?,?,?,?,?,?,?)", (run, "c1", "axis", key, e, reason, at))
            con.commit()
        finally:
            con.close()
        self.entry = {"example_id": "EX-1", "source_ws": "src", "record_id": "c1", "text_hash": "h-c1",
                      "final_axes": {"축A": ["값2"], "축B": ["값3"]},
                      "corrected": {"축A": {"bot": ["값1"], "human": ["값2"]}, "축B": {"bot": [], "human": ["값3"]}},
                      "confirmed": []}

    def test_example_block_has_evidence_and_defang(self):
        examples, skipped = feedback._resolve_examples(_FakeWs(self.root), [self.entry], None, {"축A", "축B"})
        self.assertEqual(skipped, {})
        ex = examples[0]
        self.assertEqual(sorted(ex["evidence"]), ["축A", "축B"])
        self.assertEqual(len(ex["evidence"]["축A"]["items"]), 3)  # 형식이 틀린 항목은 건너뛴다
        self.assertEqual(ex["evidence"]["축B"], {"items": [], "reason": None})
        fb = feedback.Feedback({"examples_k": 1, "min_similarity": {"lexical": 0.0}}, [], examples, {}, 0)
        text, fids = fb.examples_for({"chunk_id": "z", "file_id": "other", "text": "가짜 본문", "text_hash": "x",
                                      "dup_hash": "y"})
        self.assertEqual(fids, ["f" * 16])
        lines = [l for l in text.splitlines() if l.startswith("근거(")]
        self.assertEqual(len(lines), 1)  # 근거 없는 축B는 줄이 없다
        line = lines[0]
        self.assertTrue(line.startswith("근거(축A): [문서 제목] 'SF1.0 세대' · [다른 슬라이드 4] '" + "가" * 200 + " …'"))
        self.assertIn(" · [같은 슬라이드] '같은 { {x} }'", line)
        self.assertTrue(line.endswith(" / 이유: 제목의 세대 표기"))
        self.assertNotIn("옛 근거", text)
        self.assertNotIn("{{", text)
        self.assertNotIn("}}", text)
        self.assertIn("{ {chunk_text} }", text)

    def test_rules_text_defang(self):
        rule = {"rule_id": "MR-1", "kind": "MANUAL", "target": "", "text": "중괄호 {{{x}}} 규칙", "_stage": "classify"}
        fb = feedback.Feedback({}, [rule], [], {}, 0)
        out = fb.rules_text("classify")
        self.assertEqual(out, "- [MR-1] 중괄호 { { {x} } } 규칙")

    def test_old_source_db_without_columns(self):
        db = os.path.join(self.root, "src", "work.sqlite")
        con = sqlite3.connect(db)
        try:
            con.execute("DROP TABLE corrections")
            con.execute("CREATE TABLE corrections (review_run_id TEXT, chunk_id TEXT, target_kind TEXT, target_key TEXT)")
            con.commit()
        finally:
            con.close()
        examples, skipped = feedback._resolve_examples(_FakeWs(self.root), [self.entry], None, {"축A", "축B"})
        self.assertEqual((skipped, examples[0]["evidence"]), ({}, {}))


if __name__ == "__main__":
    unittest.main()
