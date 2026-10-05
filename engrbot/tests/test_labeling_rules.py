"""라벨링 규칙 환류 테스트: 교정 장부 → 라벨링 규칙·사례 후보, 사람 승인 파일, CLI.

작업 폴더는 test_ledger의 합성 픽스처(build_ws)를 코드 폴더 밖 임시 폴더에 만든다. 승인 파일도 임시 경로에 쓴다
(코드 폴더의 taxonomy/labeling_rules.json을 건드리지 않는다). 네트워크·LLM은 쓰지 않는다.
"""
import contextlib
import io as std_io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from engrbot import cli, labeling_rules as lr, ledger
from engrbot.tests.test_ledger import APPROVED_QID, BODY, DEFECT, FILE_NAME, LAYER, MEMO, _pol, build_ws, cid_of


class LabelingRulesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="engrbot_lrules_")
        cls.root = build_ws(cls.tmp, "ws1")
        cls.pol = _pol()
        ledger.intake(cls.root, cls.pol)
        cls.d = ledger.ledger_dir(cls.root, cls.pol)
        cls.cfg = lr.config(cls.pol)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="engrbot_lrules_out_")
        self.addCleanup(shutil.rmtree, self.out, True)
        self.path = os.path.join(self.out, "labeling_rules.json")

    # ---- 후보 -------------------------------------------------------------

    def test_rule_candidates(self):
        c = lr.candidates(self.d, lr.empty_rules(), self.cfg)
        got = {(r["kind"], r["target"], r["from"], r["to"]): r["count"] for r in c["rules"]}
        self.assertEqual(got.get(("REMOVE", DEFECT, "Open", "")), 2)
        self.assertEqual(got.get(("ADD", LAYER, "", "M2")), 2)
        self.assertEqual(got.get(("ANSWER", APPROVED_QID, "O", "X")), 2)
        # 검증 질문 답 뒤집힘은 1건이라 후보가 아니고, 깨진 봇 값(목록 아님)은 규칙 근거가 되지 않는다.
        self.assertFalse([r for r in c["rules"] if r["kind"] == "GEN_ANSWER"])
        self.assertFalse([r for r in c["rules"] if "," in r["from"]])
        for r in c["rules"]:
            self.assertLessEqual(len(r["text"]), lr.TEXT_MAX)
        again = lr.candidates(self.d, lr.empty_rules(), self.cfg)
        self.assertEqual([r["rule_id"] for r in c["rules"]], [r["rule_id"] for r in again["rules"]])
        self.assertEqual(lr.candidates(self.d, lr.empty_rules(), dict(self.cfg, min_count=3))["rules"], [])

    def test_example_candidates(self):
        exs = {e["record_id"]: e for e in lr.candidates(self.d, lr.empty_rules(), self.cfg)["examples"]}
        self.assertEqual(exs[cid_of(2)]["kind"], "corrected")
        self.assertEqual(exs[cid_of(2)]["corrected"][DEFECT], {"bot": ["Short", "Open"], "human": ["Short"]})
        self.assertEqual(exs[cid_of(2)]["final_axes"][DEFECT], ["Short"])
        self.assertEqual(exs[cid_of(1)]["kind"], "confirmed")
        self.assertIn(LAYER, exs[cid_of(1)]["confirmed"])
        # 축 사례 없이 답만 고친 레코드, 재검수·판단 불가·이미지 판단 불가·내용 아님 레코드는 사례가 아니다.
        for n in (4, 5, 6, 7, 11):
            self.assertNotIn(cid_of(n), exs, n)

    def test_axis_keys(self):
        k = lr.axis_keys
        self.assertEqual(k("A", ["x"], ["y"]), [("REPLACE", "A", "x", "y")])
        self.assertEqual(k("A", ["해당 없음"], ["y"]), [("ADD", "A", "", "y")])
        self.assertEqual(k("A", ["x"], ["unknown"]), [("REMOVE", "A", "x", "")])
        self.assertEqual(k("A", ["unknown"], ["해당 없음"]), [("REPLACE", "A", "unknown", "해당 없음")])
        self.assertEqual(k("A", ["x", "z"], ["y"]),
                         [("REMOVE", "A", "x", ""), ("REMOVE", "A", "z", ""), ("ADD", "A", "", "y")])
        self.assertEqual(k("A", ["x"], ["x"]), [])

    def test_conflict(self):
        cases = [{"kind": "corrected", "field": "axis:A", "record_id": "r%d" % i, "bot_value": ["x"], "human_value": ["y"]}
                 for i in range(2)]
        cases += [{"kind": "corrected", "field": "axis:A", "record_id": "s%d" % i, "bot_value": ["y"], "human_value": ["x"]}
                  for i in range(2)]
        rules = lr.all_rules(cases, 2)
        self.assertTrue(all(r["conflict"] for r in rules.values()))
        self.assertFalse(any(r["conflict"] for r in lr.all_rules(cases, 3).values()))

    # ---- 승인 파일 --------------------------------------------------------

    def test_approve_reject_and_preserve_edits(self):
        r = lr.decide(self.d, "approve", self.cfg, all_=True, examples="all", path=self.path)
        self.assertEqual(r["rules"], 3)
        self.assertGreaterEqual(r["examples"], 5)
        self.assertEqual(lr.candidates(self.d, lr.load_rules(self.path), self.cfg),
                         {"rules": [], "examples": []})
        doc = lr.load_rules(self.path)
        rid = doc["rules"][0]["rule_id"]
        doc["rules"][0].update(text="사람이 고친 문장이다.", enabled=False)
        lr.save_rules(doc, self.path)
        lr.decide(self.d, "approve", self.cfg, ids=[rid], path=self.path)
        again = lr.load_rules(self.path)
        self.assertEqual(again["rules"][0]["text"], "사람이 고친 문장이다.")
        self.assertFalse(again["rules"][0]["enabled"])
        st = lr.status(self.d, self.cfg, self.path)
        self.assertEqual(st["rules"]["enabled"], 2)
        self.assertEqual(st["candidates"], 0)
        eid = again["examples"][0]["example_id"]
        r = lr.decide(self.d, "reject", self.cfg, ids=["%s,%s" % (rid, eid), "FR-없는것"], path=self.path)
        self.assertEqual(r["unknown_ids"], ["FR-없는것"])
        doc = lr.load_rules(self.path)
        self.assertIn(rid, doc["rejected"])
        self.assertIn(eid, doc["rejected_examples"])
        self.assertNotIn(rid, [x["rule_id"] for x in doc["rules"]])
        self.assertNotIn(eid, [x["example_id"] for x in doc["examples"]])
        # 기각한 것은 후보로 다시 올라오지 않는다
        c = lr.candidates(self.d, doc, self.cfg)
        self.assertNotIn(rid, [x["rule_id"] for x in c["rules"]])
        self.assertNotIn(eid, [x["example_id"] for x in c["examples"]])

    def test_reject_only_is_saved(self):
        rid = lr.candidates(self.d, lr.empty_rules(), self.cfg)["rules"][0]["rule_id"]
        lr.decide(self.d, "reject", self.cfg, ids=[rid], path=self.path)
        self.assertEqual(lr.load_rules(self.path)["rejected"], [rid])

    def test_outputs_have_no_body_or_names(self):
        lr.decide(self.d, "approve", self.cfg, all_=True, examples="all", path=self.path)
        texts = []
        for p in (self.path, os.path.join(self.d, lr.CANDIDATES), os.path.join(self.d, lr.CANDIDATES_MD)):
            with open(p, encoding="utf-8") as f:
                texts.append(f.read())
        for t in texts:
            for bad in (BODY, FILE_NAME, MEMO, "인용"):
                self.assertNotIn(bad, t)
        self.assertFalse([fn for fn in os.listdir(self.d) if ".tmp." in fn or fn == ledger.LOCK_NAME])

    def test_bad_rules_file(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{not json")
        with self.assertRaises(lr.LabelingRulesError) as cm:
            lr.load_rules(self.path)
        self.assertEqual(cm.exception.reason_code, "RULES_JSON_INVALID")
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"rules": {}}, f)
        with self.assertRaises(lr.LabelingRulesError):
            lr.load_rules(self.path)

    def test_valid_example_refuses_paths(self):
        base = {"example_id": "EX-1", "record_id": "r", "text_hash": "t", "final_axes": {}}
        self.assertTrue(lr.valid_example(dict(base, source_ws="261004_BEOL_x_20261005-113123")))
        for bad in ("..", "../x", "a\\b", "C:x"):
            self.assertFalse(lr.valid_example(dict(base, source_ws=bad)), bad)

    # ---- CLI -------------------------------------------------------------

    def _cli(self, *argv):
        buf = std_io.StringIO()
        with mock.patch.object(lr, "RULES_PATH", self.path), contextlib.redirect_stdout(buf):
            code = cli.main(["labeling-rules"] + list(argv) + ["--workspace", self.root])
        return code, buf.getvalue()

    def test_cli(self):
        code, out = self._cli("candidates")
        self.assertEqual(code, 0)
        self.assertIn("[labeling-rules] 규칙 후보 3개", out)
        self.assertEqual(self._cli("approve")[0], 2)
        code, out = self._cli("approve", "--all")
        self.assertEqual(code, 0)
        self.assertIn("승인 규칙 3개, 사례 0개", out)
        code, out = self._cli("status")
        st = json.loads(out)
        self.assertEqual(st["rules"]["approved"], 3)
        self.assertGreater(st["examples_pending"], 0)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{not json")
        code, out = self._cli("status")
        self.assertEqual(code, 1)
        self.assertIn("[오류] RULES_JSON_INVALID", out)


if __name__ == "__main__":
    unittest.main()
