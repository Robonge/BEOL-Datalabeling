"""L5: 중복 묶음 일관성."""
import json
import unittest

from domain_engrbot import policy
from domain_engrbot.tests.helpers import run, small_bundle

CODE = "L5_DUP_GROUP_DISAGREE"


def _setup(groups):
    """내용 chunk 레코드에 dup_group을 붙인다. groups: [묶음 키 또는 None …]. 반환: (번들, 대상 레코드 ID 목록, 축 이름)."""
    b = small_bundle()
    ct = policy.validate_schema({})["content_chunk_type"]
    recs = sorted((r for r in b.records if r["chunk_type"] == ct), key=lambda r: r["record_id"])
    ids = [r["record_id"] for r in recs[:len(groups)]]
    for rid, g in zip(ids, groups):
        b.units[rid]["dup_group"] = g
    names = [a["name"] for a in b.taxonomy["axes"] if a.get("active") and a.get("kind", "분류") == "분류"]
    for rid in ids:  # 다른 축은 모두 같은 값으로 맞춰 둔다
        for n in names:
            _set_values(b, rid, n, ["M0"])
    return b, ids, names[0]


def _set_values(b, rid, axis, values):
    for r in b.records:
        if r["record_id"] == rid:
            r["axes"][axis] = {"values": list(values), "status": "value", "evidence": {"quote": "", "unit_id": None,
                                                                                    "start": None, "end": None},
                               "confidence": 0.9}


def _l5(b):
    out, _ = run(b, ["L5"])
    return out


def _hits(out, rid):
    v = next(v for v in out["verdicts"] if v["record_id"] == rid)
    return v, [i for i in v["issues"] if i["code"] == CODE]


class DupGroupTest(unittest.TestCase):
    def test_disagree_flags_both_and_reviews(self):
        b, ids, axis = _setup(["G1", "G1"])
        _set_values(b, ids[0], axis, ["M0"])
        _set_values(b, ids[1], axis, ["M1"])
        out = _l5(b)
        for rid in ids:
            v, hits = _hits(out, rid)
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0]["field"], "axis:%s" % axis)
            self.assertEqual(hits[0]["evidence"], {"group_size": 2, "variants": 2})
            self.assertEqual(v["verdict"], "REVIEW")

    def test_same_values_no_issue(self):
        b, ids, axis = _setup(["G1", "G1"])
        for rid in ids:
            _set_values(b, rid, axis, ["M0"])
        out = _l5(b)
        for rid in ids:
            self.assertEqual(_hits(out, rid)[1], [])

    def test_no_group_or_single_member_ignored(self):
        b, ids, axis = _setup([None, "", "S1", "S2"])
        for n, rid in enumerate(ids):
            _set_values(b, rid, axis, ["M%d" % n])
        out = _l5(b)
        for rid in ids:
            self.assertEqual(_hits(out, rid)[1], [])

    def test_only_group_members_get_issue(self):
        b, ids, axis = _setup(["G1", "G1", "G2"])
        _set_values(b, ids[0], axis, ["M0"])
        _set_values(b, ids[1], axis, ["M1"])
        _set_values(b, ids[2], axis, ["M2"])
        out = _l5(b)
        self.assertEqual(len(_hits(out, ids[0])[1]), 1)
        self.assertEqual(_hits(out, ids[2])[1], [])

    def test_critical_record_excluded(self):
        b, ids, axis = _setup(["G1", "G1"])
        _set_values(b, ids[0], axis, ["M0"])
        _set_values(b, ids[1], axis, ["M1"])
        # 판정이 REJECT인 레코드는 비교에서 빠진다. 단독이 된 묶음은 이슈가 없다.
        b.records[[r["record_id"] for r in b.records].index(ids[1])]["axes"][axis]["values"] = ["M1", "M0", "M2"]
        out, _ = run(b, ["L1", "L2", "L5"])
        crit = [v["record_id"] for v in out["verdicts"] if v["verdict"] == "REJECT"]
        self.assertIn(ids[1], crit)
        self.assertEqual(_hits(out, ids[0])[1], [])

    def test_l5_only_layers_runs_batch_check(self):
        b, ids, axis = _setup(["G1", "G1"])
        _set_values(b, ids[0], axis, ["M0"])
        _set_values(b, ids[1], axis, ["M1"])
        out, ctx = run(b, ["L5"])
        self.assertEqual(ctx.policy["layers"], ["L5"])
        self.assertEqual(len(_hits(out, ids[0])[1]), 1)

    def test_evidence_has_no_raw_text(self):
        b, ids, axis = _setup(["G1", "G1"])
        _set_values(b, ids[0], axis, ["M0"])
        _set_values(b, ids[1], axis, ["M1"])
        out = _l5(b)
        for rid in ids:
            for i in _hits(out, rid)[1]:
                blob = json.dumps(i["evidence"], ensure_ascii=False)
                self.assertNotIn("M0", blob)
                self.assertNotIn("M1", blob)
                self.assertEqual(set(i["evidence"]), {"group_size", "variants"})


if __name__ == "__main__":
    unittest.main()
