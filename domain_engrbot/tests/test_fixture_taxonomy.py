"""합성 fixture가 최신 taxonomy/taxonomy.xlsx를 따라가고, taxonomy가 바뀌어도 깨끗한 레코드가 L2를 통과하는지 본다."""
import copy
import unittest
from unittest import mock

from domain_engrbot import model, policy
from domain_engrbot.adapters import labelbot_ws
from domain_engrbot.checks import l2_taxonomy
from domain_engrbot import synthetic

SCHEMA = policy.validate_schema({})
POLICY = policy.validate_policy({})
L2_CLEAN_CODES = {"L2_UNKNOWN_OVERUSE", "L2_ALL_NOT_APPLICABLE", "L2_AXIS_UNKNOWN", "L2_LABEL_NOT_IN_TAXONOMY",
                  "L2_TAXONOMY_STALE"}


def l2_codes(fx):
    tax = model.TaxIndex(fx.bundle.taxonomy)
    out = []
    for rec in fx.bundle.records:
        if rec["chunk_type"] == "내용":
            out += [(rec["record_id"], i["code"]) for i in l2_taxonomy.evaluate(rec, tax, SCHEMA, POLICY)
                    if i["code"] in L2_CLEAN_CODES]
    return out


def changed_snapshot():
    """엑셀 수정 흉내: 새 분류 축 추가, 빈(비활성) 축 추가, 기존 축 값 줄이기."""
    snap = copy.deepcopy(synthetic.taxonomy_snapshot())
    snap["axes"].append({"name": "신규 축", "kind": "분류", "multi": True, "hierarchical": False, "active": True,
                         "definition": "", "values": [{"name": "새값%d" % i, "parent": None, "definition": ""}
                                                      for i in range(3)]})
    snap["axes"].append({"name": "빈 축", "kind": "분류", "multi": False, "hierarchical": False, "active": False,
                         "definition": "", "values": []})
    flat = next(a for a in snap["axes"] if a["kind"] == "분류" and not a["hierarchical"] and len(a["values"]) > 1)
    flat["values"] = flat["values"][:1]
    snap["version"] = model.hash_obj(snap["axes"])
    return snap


class FixtureTaxonomyTest(unittest.TestCase):
    def test_snapshot_is_current_xlsx(self):
        tax = labelbot_ws.load_taxonomy(synthetic.REPO_ROOT, {"taxonomy_path": synthetic.TAXONOMY_XLSX})
        snap = synthetic.taxonomy_snapshot()
        self.assertEqual(snap["version"], tax.sheet_hashes["taxonomy"])
        self.assertEqual(snap, labelbot_ws.snapshot(tax))

    def test_clean_records_pass_l2_across_seeds(self):
        for seed in (1, 2, 3, 7, 11):
            self.assertEqual(l2_codes(synthetic.generate(seed=seed, n_files=3)), [], seed)

    def test_changed_taxonomy_still_generates_clean(self):
        snap = changed_snapshot()
        used = set()
        with mock.patch.object(synthetic, "taxonomy_snapshot", return_value=snap):
            for seed in (1, 7):
                fx = synthetic.generate(seed=seed, n_files=3)
                self.assertEqual(l2_codes(fx), [], seed)
                content = [r for r in fx.bundle.records if r["chunk_type"] == "내용"]
                self.assertTrue(all("빈 축" not in r["axes"] for r in content))
                used |= {v for r in content for v in r["axes"]["신규 축"]["values"]}
        self.assertTrue(used & {"새값0", "새값1", "새값2"})  # 새 축도 기본 문장 틀로 값을 받는다

    def test_same_seed_same_bundle(self):
        self.assertEqual(synthetic.generate(seed=5, n_files=2).bundle_hash(),
                         synthetic.generate(seed=5, n_files=2).bundle_hash())


if __name__ == "__main__":
    unittest.main()
