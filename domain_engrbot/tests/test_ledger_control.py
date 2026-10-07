"""대조 질문(Q-CTL-) 답 교정과 직접 입력(typed) 근거 테스트.

labelbot 검수 화면이 corrections에 target_kind='control'(target_key = 대조 질문 qid) 행과 source='typed' 근거를 쓴다.
장부는 대조 교정을 field "control:<qid>" 사례로만 남기고(골든·레코드·judge 예시·규칙 패턴에는 넣지 않는다),
도메인 질문 context와 질문 화면에는 대조 대상 (축, 값)과 함께 근거 자료로 넣는다.
"""
import json
import os
import sqlite3

from domain_engrbot import io, labeling_rules as lr, ledger, qmodel, question_screen, questions
from domain_engrbot.tests.test_ledger import (APPLIED, DEFECT, EV_QUOTE, LAYER, REASON, RUN, LedgerTestBase, _pol,
                                              build_ws, cid_of)

CTL1, CTL2, CTL3, CTL_GONE = "Q-CTL-0001", "Q-CTL-0002", "Q-CTL-0003", "Q-CTL-9999"
TYPED = EV_QUOTE + " 직접 입력"


def _typed(quote=TYPED):
    # 직접 입력 근거는 chunk_id·slide_no가 없다(slide_no를 잘못 넣어도 장부는 null로 둔다)
    return {"source": "typed", "chunk_id": None, "slide_no": 3, "quote": quote}


def build_control_ws(parent, name="ws1"):
    """axis 교정 둘(2: typed 근거, 4: 근거 없음)과 대조 답 교정 다섯 행을 둔 작업 폴더.

    대조 교정: 2 CTL1 O→X(typed 근거+이유), 2 CTL2 X→X(확인), 5 CTL3 X→O(대조 교정만 있는 레코드),
    6 CTL_GONE(ctl_questions에 없음), 2 CTL3 O→"판단 불가".
    """
    rows = [(cid_of(2), "axis", DEFECT, ["Short"], 0, None), (cid_of(4), "axis", LAYER, ["M1", "M2"], 0, None)]
    evidence = {(cid_of(2), "axis", DEFECT): ([_typed()], None)}
    root = build_ws(parent, name, run_corrections={RUN: rows}, evidence=evidence)
    con = sqlite3.connect(os.path.join(root, "work.sqlite"))
    try:
        hashes = dict(con.execute("SELECT chunk_id, text_hash FROM chunks"))
        for qid, axis, value in ((CTL1, LAYER, "M3"), (CTL2, DEFECT, "Open"), (CTL3, LAYER, "M4")):
            con.execute("INSERT INTO ctl_questions(qid, chunk_id, axis, value, text) VALUES(?,?,?,?,?)",
                        (qid, cid_of(2), axis, value, "본문이 %s=%s를 뒷받침하는가" % (axis, value)))
        ctl = [(2, CTL1, "O", "X", [_typed()], REASON + " 대조"), (2, CTL2, "X", "X", None, None),
               (5, CTL3, "X", "O", None, None), (6, CTL_GONE, "O", "X", None, None),
               (3, CTL3, "O", "판단 불가", None, None)]
        for n, qid, bot, human, items, reason in ctl:
            c = cid_of(n)
            con.execute("INSERT INTO corrections(review_run_id, chunk_id, target_kind, target_key, human_value,"
                        " bot_value, review_status, recheck, text_hash, question_hash, applied_at, evidence, reason,"
                        " evidence_dropped) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (RUN, c, "control", qid, json.dumps(human, ensure_ascii=False), json.dumps(bot), "corrected",
                         0, hashes[c], "0" * 16, APPLIED,
                         json.dumps(items, ensure_ascii=False) if items is not None else None, reason, 0))
        con.commit()
    finally:
        con.close()
    return root


class ControlIntakeTest(LedgerTestBase):
    def setUp(self):
        LedgerTestBase.setUp(self)
        self.root = build_control_ws(self.tmp)
        self.pol = _pol()
        self.out = ledger.intake(self.root, self.pol)
        self.d = ledger.ledger_dir(self.root, self.pol)
        self.cases = {(c["record_id"], c["field"]): c for c in ledger.read(self.d, ledger.CASES)}

    def test_control_cases(self):
        c1 = self.cases[(cid_of(2), "control:" + CTL1)]
        self.assertEqual((c1["kind"], c1["bot_value"], c1["human_value"]), (ledger.CORRECTED, "O", "X"))
        self.assertEqual((c1["ctl_axis"], c1["ctl_value"]), (LAYER, "M3"))
        self.assertEqual((c1["evidence_sources"], c1["has_reason"]), (["typed"], True))
        c2 = self.cases[(cid_of(2), "control:" + CTL2)]
        self.assertEqual((c2["kind"], c2["ctl_axis"], c2["ctl_value"]), (ledger.CONFIRMED, DEFECT, "Open"))
        self.assertNotIn("evidence_sources", c2)
        c3 = self.cases[(cid_of(5), "control:" + CTL3)]
        self.assertEqual((c3["kind"], c3["human_value"]), (ledger.CORRECTED, "O"))
        # 판단 불가도 대조 답의 품질 신호로 남긴다
        self.assertEqual(self.cases[(cid_of(3), "control:" + CTL3)]["human_value"], "판단 불가")
        self.assertNotIn((cid_of(6), "control:" + CTL_GONE), self.cases)
        self.assertEqual(self.out["skipped"].get("SKIP_CONTROL_UNRESOLVED"), 1)
        self.assertNotIn("SKIP_TARGET_OTHER", self.out["skipped"])

    def test_control_not_in_golden_records_examples(self):
        for g in ledger.read(self.d, ledger.GOLDEN):
            self.assertFalse([k for k in g["labels"]["answers"] if k.startswith("Q-CTL")])
            self.assertFalse([k for k in g["evidence"] if k.startswith("control:")])
        recs = {r["record_id"] for r in ledger.read(self.d, ledger.RECORDS)}
        # 대조 교정만 있는 레코드는 레코드(final_axes)·골든을 만들지 않는다(규칙 후보 모수가 바뀌지 않는다)
        self.assertEqual(recs, {cid_of(2), cid_of(4)})
        self.assertNotIn(cid_of(5), {g["record_id"] for g in ledger.read(self.d, ledger.GOLDEN)})
        self.assertFalse([e for e in ledger.read(self.d, ledger.EXAMPLES) if (e.get("qid") or "").startswith("Q-CTL")])

    def test_control_not_in_patterns(self):
        rules = lr.all_rules(lr._latest_cases(self.d), 1)
        self.assertTrue(rules)
        self.assertFalse([r for r in rules.values() if "Q-CTL" in r["target"]])

    def test_typed_evidence(self):
        ev = {(e["record_id"], e["field"]): e for e in ledger.read_evidence(self.d)}
        for field in ("axis:" + DEFECT, "control:" + CTL1):
            self.assertEqual([(x["source"], x["chunk_id"], x["slide_no"], x["quote"]) for x in ev[(cid_of(2), field)]["evidence"]],
                             [("typed", None, None, TYPED)], field)
        self.assertEqual(ev[(cid_of(2), "control:" + CTL1)]["reason"], REASON + " 대조")
        self.assertEqual(ledger.evidence_kind(_typed(), cid_of(2)), "typed")
        self.assertEqual(self.cases[(cid_of(2), "axis:" + DEFECT)]["evidence_sources"], ["typed"])
        # 규칙 문장의 근거 위치에 직접 입력이 나온다
        rule = next(r for r in lr.all_rules(lr._latest_cases(self.d), 1).values() if r["target"] == DEFECT)
        self.assertEqual(rule["evidence_mix"], {"typed": 1})
        self.assertIn("직접 입력 1건", rule["text"])

    def test_typed_item_checks(self):
        row = {"target_kind": "control", "evidence": json.dumps([_typed(), _typed(""), _typed("가" * 301)])}
        items, reason, bad = ledger._evidence(row, 300)
        self.assertEqual((len(items), reason, bad), (1, None, 2))

    def test_idempotent(self):
        before = {fn: open(os.path.join(self.d, fn), "rb").read() for fn in sorted(os.listdir(self.d))}
        again = ledger.intake(self.root, self.pol)
        self.assertFalse(again["changed"])
        self.assertEqual(before, {fn: open(os.path.join(self.d, fn), "rb").read() for fn in sorted(os.listdir(self.d))})


class ControlContextTest(LedgerTestBase):
    def setUp(self):
        LedgerTestBase.setUp(self)
        self.root = build_control_ws(self.tmp)
        self.pol = _pol()
        self.paths = io.QaPaths(self.root)
        self.rules = os.path.join(self.tmp, "labeling_rules.json")
        self.d = ledger.ledger_dir(self.root, self.pol)
        self.qd = qmodel.qdir(self.d)
        ledger.intake(self.root, self.pol)

    def test_context_and_screen(self):
        ctx = questions.build_context(self.paths, self.pol, self.d, self.qd, [], 5, rules_path=self.rules)
        items = {c["field"]: c for c in ctx.data["cases"] if c["field"].startswith("control:")}
        c1 = items["control:" + CTL1]
        self.assertEqual(c1["control"], {"axis": LAYER, "value": "M3"})
        self.assertEqual((c1["bot"], c1["human"], c1["kind"]), ("O", "X", ledger.CORRECTED))
        self.assertEqual(c1["evidence"], [{"kind": "typed", "slide_no": None, "quote": TYPED}])
        self.assertEqual(c1["reason"], REASON + " 대조")
        self.assertEqual(items["control:" + CTL3]["control"], {"axis": LAYER, "value": "M4"})
        self.assertNotIn("control", next(c for c in ctx.data["cases"] if c["field"].startswith("axis:")))
        # 질문의 근거 ref로 대조 사례를 쓰면 질문 화면에 대조 대상과 직접 입력 근거가 보인다
        ref = c1["ref"]
        q = questions.clean_question({"goal": "taxonomy", "topic": {"type": "axis_value", "axis": LAYER, "values": ["M3"]},
                                      "text": "M3 판정 기준은?", "why": "대조 답이 갈렸다.", "refs": [ref],
                                      "options": []}, ctx, {})
        self.assertEqual(q["evidence"], [ctx.cases[ref]["case_id"]])
        view = question_screen.data({"questions": [q]}, self.d)["questions"][0]["evidence"][0]
        self.assertEqual(view["field"], "control:" + CTL1)
        self.assertEqual(view["control"], {"axis": LAYER, "value": "M3"})
        self.assertEqual(view["items"], [{"kind": "typed", "slide_no": None, "quote": TYPED}])
