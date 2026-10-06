"""계약 테스트: Domain-Engr-bot 질문 루프(answers.apply)가 쓴 승인 파일을 labelbot이 실제 읽기 경로로 읽는다.

domain_engrbot 쪽은 합성 작업 폴더(domain_engrbot.tests.test_ledger.build_ws)와 장부를 임시 폴더에 만들고, 질문 묶음·답 파일을
qmodel 형식으로 직접 둔다. 승인 파일은 임시 경로다(코드 폴더의 taxonomy/labeling_rules.json을 건드리지 않는다).
labelbot 쪽은 feedback.load_rules·_valid_rule·_rules_for_run·load(실행 때 프롬프트에 넣는 객체)로 읽는다.
네트워크·LLM은 쓰지 않는다(사례 본문은 원래 작업 폴더 work.sqlite에서 읽기 전용으로 읽는다).
"""
import os
import shutil
import tempfile
import unittest
from unittest import mock

from domain_engrbot import answers, io, labeling_rules as lr, ledger, qmodel
from domain_engrbot.adapters import labelbot_ws
from domain_engrbot.tests.test_ledger import DEFECT, LAYER, TAXONOMY, _pol, build_ws, cid_of
from domain_engrbot.tests.test_question_answers import answer, make_question, rule, save_questions, write_answers
from labelbot import feedback


class _Ws:
    """feedback이 쓰는 작업 폴더 속성만 가진 객체(root, config)."""

    def __init__(self, root, rules_path, examples_root):
        self.root = root
        self.config = {"feedback": {"rules_path": rules_path, "examples_root": examples_root}, "embedding": {}}


class QuestionRulesContractTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="contract_qrules_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = build_ws(self.tmp, "ws1")
        self.pol = _pol()
        ledger.intake(self.root, self.pol)
        self.paths = io.QaPaths(self.root)
        self.d = ledger.ledger_dir(self.root, self.pol)
        self.qd = qmodel.qdir(self.d)
        self.rules = os.path.join(self.tmp, "labeling_rules.json")
        cands = lr.candidates(self.d, lr.empty_rules(), lr.config(self.pol))
        by = {(r["kind"], r["target"]): r["rule_id"] for r in cands["rules"]}
        self.fr_rm, self.fr_add = by[("REMOVE", DEFECT)], by[("ADD", LAYER)]
        self.ex = {e["record_id"]: e["example_id"] for e in cands["examples"]}[cid_of(2)]
        self.tax = labelbot_ws.load_taxonomy(".", {"taxonomy_path": TAXONOMY})

    def _apply(self):
        q1 = make_question("분류 질문", patterns=[self.fr_rm, self.fr_add], examples=[self.ex])
        q2 = make_question("라벨 질문")
        save_questions(self.qd, [q1, q2])
        write_answers(self.paths.inbox, [
            answer(q1, rule("패턴을 확정한 문장이다.", stage="label", target=LAYER, pattern_id=self.fr_rm),
                   rule("사람이 쓴 1차 분류 규칙이다.", target=LAYER, origin="human"),
                   {"type": "example", "example_id": self.ex, "origin": "llm"}),
            answer(q2, rule("사람이 쓴 3차 라벨링 규칙이다.", stage="label", origin="edited"))])
        with mock.patch("domain_engrbot.answers._build_screen", return_value=0):
            return answers.apply(self.paths, self.pol, rules_path=self.rules)

    def test_labelbot_reads_rules_by_stage(self):
        res = self._apply()
        ws = _Ws(self.root, self.rules, self.tmp)
        doc = feedback.load_rules(ws)
        self.assertTrue(doc["rules"])
        self.assertTrue(all(feedback._valid_rule(r) for r in doc["rules"]))
        rules, invalid = feedback._rules_for_run(doc, self.tax, 30)
        self.assertEqual(invalid, 0)
        stage = {r["text"]: (r["kind"], r["_stage"]) for r in rules}
        self.assertEqual(stage, {"패턴을 확정한 문장이다.": ("REMOVE", "classify"),
                                 "사람이 쓴 1차 분류 규칙이다.": ("MANUAL", "classify"),
                                 "사람이 쓴 3차 라벨링 규칙이다.": ("MANUAL", "label")})
        # 종결한 패턴은 승인 파일 rules에 없다(기각 목록에만 있다)
        self.assertNotIn(self.fr_add, [r["rule_id"] for r in rules])
        # Domain-Engr-bot이 알려 주는 단계별 수는 labelbot이 실제로 넣는 수와 같다
        self.assertEqual(res["enabled_rules"], {"classify": sum(1 for r in rules if r["_stage"] == "classify"),
                                                "label": sum(1 for r in rules if r["_stage"] == "label")})
        # 실행 객체: MANUAL이 앞에 오고, 3차 라벨링에는 MANUAL 라벨 규칙이 들어가며, 사례도 원래 작업 폴더에서 읽는다
        fb = feedback.load(ws, self.tax, None)
        self.assertTrue(fb.enabled)
        classify = fb.rules_text("classify")
        self.assertIn("사람이 쓴 1차 분류 규칙이다.", classify)
        self.assertIn("패턴을 확정한 문장이다.", classify)
        self.assertLess(classify.index("사람이 쓴 1차 분류 규칙이다."), classify.index("패턴을 확정한 문장이다."))
        self.assertNotIn("3차 라벨링 규칙", classify)
        label = fb.rules_text("label", [])
        self.assertIn("사람이 쓴 3차 라벨링 규칙이다.", label)
        self.assertNotIn("1차 분류 규칙", label)
        self.assertEqual([e["example_id"] for e in fb.examples], [self.ex])
        self.assertEqual(fb.applied()["rules_invalid"], 0)

    def test_cap_matches_labelbot(self):
        """labelbot은 단계별 max_rules에서 자른다. Domain-Engr-bot 결과의 cap·RULES_OVER_CAP은 같은 기준이다."""
        with mock.patch.object(answers.labelbot_ws, "read_config", return_value={"feedback": {"max_rules": 1}}):
            res = self._apply()
        self.assertEqual((res["cap"], res["enabled_rules"]["classify"]), (1, 2))
        self.assertIn("RULES_OVER_CAP", res["notes"])
        rules, _ = feedback._rules_for_run(feedback.load_rules(_Ws(self.root, self.rules, self.tmp)), self.tax, 1)
        self.assertEqual([r["kind"] for r in rules if r["_stage"] == "classify"], ["MANUAL"])


if __name__ == "__main__":
    unittest.main()
