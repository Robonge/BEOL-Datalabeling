"""2차 대조 질문(Q-CTL-): 이 chunk에 붙지 않은 라벨로 만든 질문. 답은 품질 신호일 뿐 확정 라벨에 들어가지 않는다."""
import hashlib
import json

import shutil
import types
import unittest

from labelbot import alerts, dashboard, export, finals, label, pipeline, questions, review, store
from labelbot.mock import MockChatTransport
from labelbot.taxonomy import Question
from tests.test_pipeline import DUMMY_DIR, _Ws


def _o_chunk(text):
    """대조 질문에 O를 내는 chunk(결정적으로 절반쯤)."""
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16) % 2 == 0


LABEL_PROMPTS = []
GEN_PROMPTS = []


def responder(body, hint):
    if hint["task"] == "question_gen":
        GEN_PROMPTS.append(body)
    if hint["task"] == "classify" and _o_chunk(hint["text"]):
        # 절반쯤의 chunk는 첫 축을 unknown, 둘째 축을 저확신으로 만들어 검증 대상이 생기게 한다
        obj = MockChatTransport._classify(hint)
        names = list(obj["axes"])
        obj["axes"][names[0]] = {"values": ["unknown"], "evidence": "", "confidence": 0.9}
        obj["axes"][names[1]]["confidence"] = 0.5
        return json.dumps(obj, ensure_ascii=False)
    if hint["task"] in ("classify", "question_gen"):
        return MockChatTransport().send(body, hint)
    LABEL_PROMPTS.append(body)
    obj = MockChatTransport._label(hint)
    if _o_chunk(hint["text"]):
        line = next(l for l in hint["text"].splitlines() if l.strip()).strip()
        for q in hint["qids"]:  # 생성 질문(검증·대조)은 모두 O
            if q.startswith(questions.GEN_PREFIX):
                obj["answers"][q] = {"answer": "O", "quote": line, "confidence": 0.9}
    return json.dumps(obj, ensure_ascii=False)


def _fake_tax():
    V = lambda name, parent=None: types.SimpleNamespace(name=name, parent=parent, definition="")
    axes = [
        types.SimpleNamespace(name="L", active=True, multi=False, values=[V("M1"), V("M2"), V("M3")]),
        types.SimpleNamespace(name="P", active=True, multi=True,
                              values=[V("CMP"), V("Cu CMP", "CMP"), V("Ru CMP", "CMP"), V("Etch")]),
        types.SimpleNamespace(name="S", active=True, multi=False, values=[V("A"), V("B")]),
        types.SimpleNamespace(name="Off", active=False, multi=False, values=[V("Z")]),
    ]
    return types.SimpleNamespace(axes=axes, axis=lambda n: next((a for a in axes if a.name == n), None))


class SplitBudgetTest(unittest.TestCase):
    def test_split(self):
        cases = [
            # (라벨 수, 남은 상한, 비율) → (검증, 대조)
            ((5, 7, 0.3), (5, 2)),
            ((3, 7, 0.3), (3, 1)),
            ((4, 5, 0.3), (3, 2)),  # 남는 칸 없이 채운다
            ((9, 7, 0.3), (5, 2)),
            ((0, 7, 0.3), (0, 1)),  # 검증 대상이 없어도 대조 질문은 낸다
            ((0, 7, 0.6), (0, 2)),
            ((3, 7, 0.6), (3, 4)),
            ((5, 7, 0), (5, 0)),
            ((1, 1, 0.3), (1, 0)),
            ((5, 0, 0.3), (0, 0)),
            ((3, 3, 0.5), (1, 2)),
            ((5, 7, 0.6), (3, 4)),  # 기본값 0.6, 상한 8에서 승인 질문 1개를 뺀 7칸
            ((2, 7, 0.6), (2, 3)),
            ((1, 7, 0.6), (1, 2)),
            ((5, 7, 5), (1, 6)),  # 비율은 0.9로 자른다
        ]
        for args, want in cases:
            got = questions.split_budget(*args)
            self.assertEqual(got, want, args)
            self.assertLessEqual(sum(got), max(0, args[1]))

    def test_control_ratio_config(self):
        for raw, want in ((0.3, 0.3), (None, 0.0), ("x", 0.0), (float("nan"), 0.0), (-1, 0.0), (5, 0.9)):
            self.assertEqual(questions.control_ratio({"limits": {"control_ratio": raw}}), want, raw)
        self.assertEqual(questions.control_ratio({"limits": {}}), 0.0)


class ControlTargetsTest(unittest.TestCase):
    def setUp(self):
        self.tax = _fake_tax()

    def test_excludes_ancestors_descendants_unknown_inactive(self):
        axes = {"L": {"values": ["unknown"]}, "P": {"values": ["Cu CMP"]}, "S": {"values": ["A"]}}
        got = questions.control_targets(self.tax, "c1", axes, 99)
        self.assertNotIn(("P", "Cu CMP"), got)
        self.assertNotIn(("P", "CMP"), got)  # 상위 값
        self.assertFalse([t for t in got if t[0] in ("L", "Off")])  # unknown 축, 비활성 축
        self.assertIn(("P", "Ru CMP"), got)
        axes = {"P": {"values": ["CMP"]}}
        got = questions.control_targets(self.tax, "c1", axes, 99)
        self.assertFalse({("P", "Cu CMP"), ("P", "Ru CMP")} & set(got))  # 하위 값

    def test_single_value_siblings_first(self):
        axes = {"L": {"values": ["M1"]}, "P": {"values": ["Etch"]}}
        got = questions.control_targets(self.tax, "c9", axes, 3)
        self.assertEqual(set(got[:2]), {("L", "M2"), ("L", "M3")})
        self.assertEqual(got[2][0], "P")
        self.assertEqual(got, questions.control_targets(self.tax, "c9", axes, 3))


class VerifyOrderTest(unittest.TestCase):
    def test_only_unknown_and_low_confidence(self):
        tax = _fake_tax()
        axes = {"L": {"values": ["M1"], "confidence": 0.95}, "P": {"values": ["CMP", "Etch"], "confidence": 0.4},
                "S": {"values": ["unknown"], "confidence": 0.9}, "Off": {"values": ["unknown"], "confidence": 0.1}}
        self.assertEqual(questions.verify_targets(tax, axes, 9, 0.7), [("S", None), ("P", "CMP"), ("P", "Etch")])
        self.assertEqual(questions.verify_targets(tax, axes, 2, 0.7), [("S", None), ("P", "CMP")])
        self.assertEqual(questions.verify_targets(tax, {"L": {"values": ["M1"], "confidence": 0.7}}, 3, 0.7), [])
        self.assertEqual(questions.verify_max({"limits": {}}), 3)


class VariationTest(unittest.TestCase):
    def test_frames_distinct_within_chunk_and_deterministic(self):
        g, c = questions.variation("c1", 3, 2)
        self.assertEqual(len(set(g + [f for f, _ in c])), 5)
        self.assertEqual((g, c), questions.variation("c1", 3, 2))
        self.assertTrue(all(a in questions.ANGLES for _, a in c))
        self.assertEqual(len({a for _, a in c}), 2)

    def test_spread_across_chunks(self):
        firsts = [questions.variation("chunk-%d" % i, 1, 1) for i in range(500)]
        for i, n in enumerate([sum(1 for g, _ in firsts if g[0] == k) for k in range(1, len(questions.FRAMES) + 1)]):
            self.assertGreater(n, 60, i)  # 균등이면 100
        self.assertEqual(len({c[0][1] for _, c in firsts}), len(questions.ANGLES))


class ValidatorTest(unittest.TestCase):
    def test_controls_do_not_fail_verification(self):
        v = questions._gen_validator([("L", "M1")], _fake_tax())
        q = [{"axis": "L", "value": "M1", "text": "M1을 다루는가?"}]
        for extra in ({}, {"controls": None}, {"controls": [{"axis": "X", "value": "Y", "text": "?"}]}):
            self.assertEqual(v(dict({"questions": q}, **extra)), (True, None), extra)
        self.assertEqual(v({"questions": []})[1], "QUESTION_MISSING")
        self.assertEqual(questions._gen_validator([], _fake_tax())({"questions": []}), (True, None))

    def test_unknown_axis_value_chosen_from_candidates(self):
        v = questions._gen_validator([("S", None), ("P", "CMP")], _fake_tax())
        cmp_q = {"axis": "P", "value": "CMP", "text": "CMP를 다루는가?"}
        self.assertEqual(v({"questions": [cmp_q, {"axis": "S", "value": "B", "text": "B인가?"}]}), (True, None))
        self.assertEqual(v({"questions": [cmp_q, {"axis": "S", "value": "Q", "text": "Q인가?"}]})[1], "UNKNOWN_TARGET")
        self.assertEqual(v({"questions": [cmp_q]})[1], "QUESTION_MISSING")
        two = [cmp_q, {"axis": "S", "value": "A", "text": "A인가?"}, {"axis": "S", "value": "B", "text": "B인가?"}]
        self.assertEqual(v({"questions": two})[1], "UNKNOWN_TARGET")

    def test_valid_controls(self):
        want = {("L", "M2"), ("L", "M3")}
        ok = [{"axis": "L", "value": "M2", "text": "M2를 다루는가?"}, {"axis": "L", "value": "M3", "text": "M3를 다루는가?"}]
        self.assertEqual(questions._valid_controls(ok, want), ({("L", "M2"): "M2를 다루는가?",
                                                               ("L", "M3"): "M3를 다루는가?"}, None))
        self.assertEqual(questions._valid_controls(None, want), ({}, "CONTROL_FORMAT_INVALID"))
        bad = [ok[0], {"axis": "L", "value": "M3", "text": "왜 M3인가?"}]
        self.assertEqual(questions._valid_controls(bad, want)[1], "CONTROL_DROPPED")
        self.assertEqual(questions._valid_controls(None, set()), ({}, None))


class BlindTest(unittest.TestCase):
    def test_labeler_cannot_see_control_ids(self):
        qs = [Question("Q-COM-001", "a?", "공통", 1, None),
              Question(questions.ctl_qid("c", "L", "M2"), "b?", ("L", "M2"), 50, None),
              Question(questions.gen_qid("c", "L", "M1"), "c?", ("L", "M1"), 50, None)]
        shown, back = label._blind(qs)
        self.assertEqual(shown[0].qid, "Q-COM-001")
        self.assertFalse([q for q in shown if questions.is_control(q.qid)])
        self.assertEqual(sorted(back.values()), sorted(q.qid for q in qs))
        self.assertEqual([q.qid for q in shown[1:]], sorted(q.qid for q in shown[1:]))


class ControlPipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        LABEL_PROMPTS.clear()
        GEN_PROMPTS.clear()
        cls.w = _Ws()
        cls.ws = cls.w.ws
        cls.run_id, cls.ctx = pipeline.run_all(cls.ws, DUMMY_DIR, transport=MockChatTransport(responder),
                                               use_feedback=False)
        cls.con = store.connect(cls.ws.work_db)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()
        shutil.rmtree(cls.w.dir, ignore_errors=True)

    def _first_labels(self, cid):
        out = set()
        for r in self.con.execute("SELECT key, value FROM labels WHERE run_id=? AND chunk_id=? AND kind='axis'",
                                  (self.run_id, cid)):
            out |= {(r["key"], v) for v in json.loads(r["value"])}
        return out

    def test_controls_are_unassigned_labels(self):
        rows = self.con.execute("SELECT qid, chunk_id, axis, value FROM ctl_questions").fetchall()
        self.assertTrue(rows)
        for r in rows:
            self.assertTrue(r["qid"].startswith(questions.CTL_PREFIX))
            self.assertNotIn((r["axis"], r["value"]), self._first_labels(r["chunk_id"]))
            self.assertNotIn(r["value"], ("해당 없음", "unknown"))

    def test_question_prompt_has_frames_and_angles(self):
        text = json.dumps(GEN_PROMPTS, ensure_ascii=False)
        self.assertIn("[문형 ", text)
        self.assertIn("· 관점: ", text)
        self.assertIn(questions.FRAMES[0], text)

    def test_label_prompt_hides_control_ids(self):
        self.assertTrue(LABEL_PROMPTS)
        self.assertFalse([b for b in LABEL_PROMPTS if questions.CTL_PREFIX in json.dumps(b, ensure_ascii=False)])

    def test_answers_kept_apart_from_final_labels(self):
        ctl = self.con.execute("SELECT key FROM labels WHERE run_id=? AND kind='control'", (self.run_id,)).fetchall()
        self.assertTrue(ctl)
        self.assertTrue(all(questions.is_control(r[0]) for r in ctl))
        self.assertFalse(self.con.execute(
            "SELECT 1 FROM labels WHERE run_id=? AND kind='answer' AND key LIKE 'Q-CTL-%'", (self.run_id,)).fetchone())
        for d in finals.final_labels(self.con, self.run_id).values():
            self.assertFalse([k for k in d["answers"] if questions.is_control(k)])
        self.assertFalse([q for q in questions.all_questions(self.con, self.ctx.tax) if questions.is_control(q.qid)])

    def test_export_has_no_controls(self):
        with open(self.ws.path("out", "labeling.sqlite"), "rb") as f:
            self.assertNotIn(questions.CTL_PREFIX.encode(), f.read())

    def test_na_ratio_ignores_controls(self):
        n = self.con.execute("SELECT COUNT(*) FROM labels WHERE run_id=? AND kind='answer'", (self.run_id,)).fetchone()[0]
        self.assertEqual(alerts.na_ratio(self.con, self.run_id)[1], n)

    def test_control_o_flagged(self):
        o = {r[0] for r in self.con.execute(
            "SELECT DISTINCT chunk_id FROM labels WHERE run_id=? AND kind='control' AND value='O'", (self.run_id,))}
        self.assertTrue(o)
        flagged = {r[0]: json.loads(r[1]) for r in self.con.execute(
            "SELECT chunk_id, reason_codes FROM flagged_chunks WHERE run_id=?", (self.run_id,))}
        for cid, codes in flagged.items():
            self.assertEqual("CONTROL_O" in codes, cid in o, cid)

    def test_verification_only_for_unknown_or_low_confidence(self):
        cmin = questions.conf_min(self.ws.config)
        rows = self.con.execute("SELECT chunk_id, axis, value FROM gen_questions").fetchall()
        self.assertTrue(rows)
        per_chunk = {}
        for r in rows:
            per_chunk[r["chunk_id"]] = per_chunk.get(r["chunk_id"], 0) + 1
            a = self.con.execute("SELECT status, confidence FROM labels WHERE run_id=? AND chunk_id=? AND kind='axis'"
                                 " AND key=?", (self.run_id, r["chunk_id"], r["axis"])).fetchone()
            self.assertTrue(a["status"] == "unknown" or a["confidence"] < cmin, dict(r))
        self.assertLessEqual(max(per_chunk.values()), 3)

    def test_unknown_o_flagged(self):
        flagged = {r[0]: json.loads(r[1]) for r in self.con.execute(
            "SELECT chunk_id, reason_codes FROM flagged_chunks WHERE run_id=?", (self.run_id,))}
        hits = [cid for cid, codes in flagged.items() if "UNKNOWN_O" in codes]
        self.assertTrue(hits)
        for cid in hits:
            self.assertTrue(self.con.execute("SELECT 1 FROM labels WHERE run_id=? AND chunk_id=? AND kind='axis'"
                                             " AND status='unknown'", (self.run_id, cid)).fetchone())

    def test_control_o_needs_quote_in_text(self):
        chunk = {"text": "M1 배선 CD 측정 결과", "warnings": "[]"}
        cfg = {"unknown_ratio_min": 0.5, "confidence_min": 0.7}
        self.assertIn("CONTROL_O", review.judge_chunk(chunk, None, False, False, cfg, {}, None, ["M1 배선 CD"])[0])
        codes = review.judge_chunk(chunk, None, False, False, cfg, {}, None, ["본문에 없는 긴 인용 문장 ABCDE"])[0]
        self.assertEqual(codes, ["QUOTE_NOT_FOUND"])

    def test_review_screen_shows_controls(self):
        review.build_review(self.ws, self.con, self.run_id, self.ctx.tax)
        with open(self.ws.path("screens", "review.html"), encoding="utf-8") as f:
            html = f.read()
        start = html.index("const DATA = ") + len("const DATA = ")
        data = json.JSONDecoder().raw_decode(html, start)[0]
        ctl = [x for c in data["chunks"] for x in c["controls"]]
        self.assertTrue(ctl)
        self.assertTrue(all(questions.is_control(x["qid"]) and x["text"] for x in ctl))

    def test_dashboard_row(self):
        dashboard.build_results(self.ws, self.con, self.run_id, self.ctx.tax)
        with open(self.ws.path("screens", "results.html"), encoding="utf-8") as f:
            self.assertIn('"qid": "Q-CTL-*"', f.read())

    def test_dashboard_before_after_review(self):
        def data():
            dashboard.build_results(self.ws, self.con, self.run_id, self.ctx.tax)
            with open(self.ws.path("screens", "results.html"), encoding="utf-8") as f:
                html = f.read()
            start = html.index("const DATA = ") + len("const DATA = ")
            return json.JSONDecoder().raw_decode(html, start)[0]

        flagged = [r[0] for r in self.con.execute("SELECT chunk_id FROM flagged_chunks WHERE run_id=? ORDER BY chunk_id",
                                                  (self.run_id,))]
        self.assertGreater(len(flagged), 2)
        self.assertFalse(data()["review"]["applied"])
        cid = flagged[0]
        key, raw = self.con.execute("SELECT key, value FROM labels WHERE run_id=? AND chunk_id=? AND kind='axis' ORDER BY id",
                                    (self.run_id, cid)).fetchone()
        new = next(v.name for v in self.ctx.tax.axis(key).values if v.name not in json.loads(raw))
        doc = {"kind": "review", "run_id": self.run_id,
               "corrections": [{"chunk_id": cid, "target": "axis", "key": key, "value": [new]}],
               "chunk_status": [{"chunk_id": flagged[1], "status": "undecidable_image"},
                                {"chunk_id": flagged[2], "status": "confirmed"}]}
        try:
            review._apply_review(self.con, self.ctx.tax, doc, "e" * 64)
            d = data()
        finally:
            self.con.rollback()
        r = d["review"]
        self.assertTrue(r["applied"])
        self.assertEqual(r["before"]["flagged"], len(flagged))
        self.assertEqual(r["after"]["remaining"], len(flagged) - 3)  # 교정·판단 불가·확인은 처리됨
        self.assertEqual([r["outcomes"][o] for o in ("corrected", "undecidable", "confirmed")], [1, 1, 1])
        self.assertEqual((r["labels"]["changed"], r["labels"]["axis"], r["labels"]["wrong"]), (1, 1, 1))
        self.assertEqual(r["labels"]["judged_chunks"], 2)  # 판단 불가는 봇 정답률 분모에 넣지 않는다
        self.assertEqual(r["handoff"]["pushed"], 0)
        self.assertEqual(r["top_changed"], [{"kind": "axis", "key": key, "text": "", "n": 1}])
        rows = {c["chunk_id"]: c for c in d["chunks"]}
        self.assertEqual((rows[cid]["outcome"], rows[cid]["changes"]), ("corrected", 1))
        self.assertEqual(rows[flagged[1]]["outcome"], "undecidable")
        self.assertEqual(rows[flagged[2]]["outcome"], "confirmed")
        self.assertTrue(all(rows[c]["outcome"] == "unreviewed" for c in flagged[3:]))
        self.assertTrue(all("outcome" not in c for c in d["chunks"] if c["chunk_id"] not in flagged))

    def test_control_answer_correction_ignored(self):
        cid = self.con.execute("SELECT chunk_id FROM flagged_chunks WHERE run_id=? AND reason_codes LIKE '%CONTROL_O%'",
                               (self.run_id,)).fetchone()[0]
        key = self.con.execute("SELECT key FROM labels WHERE run_id=? AND chunk_id=? AND kind='control'",
                               (self.run_id, cid)).fetchone()[0]
        doc = {"kind": "review", "run_id": self.run_id,
               "corrections": [{"chunk_id": cid, "target": "answer", "key": key, "value": "X"}]}
        res = review._apply_review(self.con, self.ctx.tax, doc, "f" * 64)
        self.con.rollback()
        self.assertEqual(res[1], 0)


class RatioOffTest(unittest.TestCase):
    def test_ratio_zero_makes_no_controls(self):
        w = _Ws({"limits": {"control_ratio": 0}})
        try:
            run_id, _ = pipeline.run_all(w.ws, DUMMY_DIR, transport=MockChatTransport(responder), use_feedback=False)
            con = store.connect(w.ws.work_db)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM ctl_questions").fetchone()[0], 0)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM labels WHERE kind='control'").fetchone()[0], 0)
            con.close()
        finally:
            shutil.rmtree(w.dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
