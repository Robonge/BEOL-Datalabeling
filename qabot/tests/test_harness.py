"""QM1 이후 각 층의 완료 조건: fixture 결정성, 층별 탐지율 1.00·오탐률 0.00, AUTO_FIX 정확도, fail-safe."""
import os
import shutil
import tempfile
import unittest

from qabot import harness, io, policy
from qabot.tests import fixturegen

SCHEMA = policy.validate_schema({})
_FULL = {}


def full_result():
    """모든 층(L0~L3B, mock judge)으로 한 번만 돌린다."""
    if "res" not in _FULL:
        from qabot.llm import MockJudgeLLM

        fx = fixturegen.generate(seed=7)
        pol = policy.validate_policy({})
        _FULL["res"] = harness.evaluate(fx.bundle, pol, SCHEMA, llm=MockJudgeLLM(), per_mutator=10)
    return _FULL["res"]


class FixtureTest(unittest.TestCase):
    def test_same_seed_same_bundle(self):
        a, b = fixturegen.generate(seed=5), fixturegen.generate(seed=5)
        self.assertEqual(a.bundle_hash(), b.bundle_hash())
        self.assertNotEqual(a.bundle_hash(), fixturegen.generate(seed=6).bundle_hash())

    def test_scale_and_variety(self):
        fx = fixturegen.generate(seed=7)
        recs = fx.bundle.records
        self.assertEqual(len(fx.bundle.sources), 12)
        self.assertGreaterEqual(len(recs), 80)
        types = {r["chunk_type"] for r in recs}
        self.assertEqual(types, {"표지", "내용"})
        statuses = {a["status"] for r in recs for a in r["axes"].values()}
        self.assertEqual(statuses, {"value", "na", "unknown"})
        self.assertTrue(any(len(a["values"]) == 2 for r in recs for a in r["axes"].values()))
        self.assertTrue(any("EM" in a["values"] or "TDDB" in a["values"] or "Rs 산포" in a["values"]
                            for r in recs for a in r["axes"].values()))
        self.assertTrue(any(u["tables"] for u in fx.bundle.units.values()))
        self.assertTrue(any(u["images"] for u in fx.bundle.units.values()))
        self.assertTrue(any(u["text_canonical"] for u in fx.bundle.units.values()))
        self.assertTrue(any(s.get("hidden") for specs in fx.specs.values() for s in specs))


class DeterministicLayersTest(unittest.TestCase):
    """L1·L2·L3A는 judge 없이 잰다(QM1, QM2, QM4)."""

    @classmethod
    def setUpClass(cls):
        fx = fixturegen.generate(seed=7)
        pol = policy.validate_policy({"layers": ["L1", "L2", "L3A"]})
        names = [m for m, v in harness.MUTATORS.items() if v.layer in ("L1", "L1_AUTOFIX", "L2", "L3A")]
        cls.res = harness.evaluate(fx.bundle, pol, SCHEMA, per_mutator=10, mutators=names)

    def test_recall_and_false_positive(self):
        for layer in ("L1", "L1_AUTOFIX", "L2", "L3A"):
            self.assertEqual(self.res["layers"][layer]["recall"], 1.0, layer)
            self.assertGreaterEqual(self.res["layers"][layer]["injected"], 30, layer)
        self.assertEqual(self.res["false_positive_rate"], 0.0)
        for layer in ("L1", "L2", "L3A"):
            self.assertEqual(self.res["layer_false_positive"][layer], 0.0)

    def test_autofix_restores_truth(self):
        self.assertEqual(self.res["autofix_accuracy"], 1.0)

    def test_wrong_unit_reported(self):
        self.assertIn("L3_SPAN_WRONG_UNIT", self.res["confusion"]["span_other_slide"])


class FullHarnessTest(unittest.TestCase):
    """L0·L3B를 포함한 전체(mock judge). QM3, QM5 완료 조건."""

    def test_all_layers_recall_one(self):
        res = full_result()
        for layer in ("L0", "L1", "L1_AUTOFIX", "L2", "L3A", "L3B", "L3B_FAILSAFE"):
            self.assertEqual(res["layers"][layer]["recall"], 1.0, layer)
        self.assertEqual(res["false_positive_rate"], 0.0, res["false_positives"])
        self.assertEqual(res["autofix_accuracy"], 1.0)

    def test_failsafe_never_pass(self):
        res = full_result()
        for name in ("judge_timeout", "judge_bad_json", "judge_missing_item"):
            self.assertGreater(res["mutators"][name]["injected"], 0)
            self.assertEqual(res["mutators"][name]["pass_after"], 0, name)

    def test_write_report(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        base = os.path.join(tmp, "eval_x")
        harness.write_report(full_result(), base)
        self.assertTrue(os.path.isfile(base + ".json") and os.path.isfile(base + ".md"))
        md = io.read_own_json(base + ".json")
        self.assertIn("layers", md)


if __name__ == "__main__":
    unittest.main()
