"""L4 도메인 규칙: 규칙 유형별 탐지·비탐지, draft·approved 판정 영향, 건너뛰기, 규칙 파일 검증, 엔진 실행."""
import json
import os
import shutil
import tempfile
import unittest

from domain_engrbot import domain_rules, engine, model, policy
from domain_engrbot.checks import l4_domain
from domain_engrbot.checks.l1_schema import ALL
from domain_engrbot import synthetic

TAX = model.TaxIndex(synthetic.taxonomy_snapshot())
SCHEMA = policy.validate_schema({})
LAYER = "구조/레이어"
MODE = "불량 모드"
PHYS = "물리 현상"
TITLE = "M1 RSBM 비밀 제목 문구"


def na_axes():
    return {a["name"]: {"values": [model.NA], "status": "na", "confidence": 0.9} for a in TAX.active_axes()}


def record(chunk_type="내용", **axes):
    r = {"record_id": "f:ppt/slides/slide2.xml", "file_id": "f", "chunk_type": chunk_type, "axes": na_axes()}
    for name, vals in axes.items():
        r["axes"][name] = {"values": vals, "status": "value", "confidence": 0.9}
    return r


def ax(**kw):
    """축 이름에 공백·슬래시가 있어 키워드 인자 대신 쓴다."""
    names = {"layer": LAYER, "mode": MODE, "phys": PHYS}
    return {names[k]: v for k, v in kw.items()}


def rules(*rs):
    return domain_rules.validate({"version": "t", "rules": list(rs)})


def combo(status="approved", severity="major", kind="expect"):
    r = {"id": "c1", "type": "axis_combo", "status": status, "severity": severity,
         "when": {"axis": MODE, "value_in": ["EM"]}}
    r[kind] = {"axis": PHYS, "value_in": ["Void"]}
    return r


def title_rule(status="approved", severity="minor"):
    return {"id": "t1", "type": "title_label", "status": status, "severity": severity,
            "title_pattern": "(?<![A-Za-z0-9])([MV][0-3])(?![A-Za-z0-9])", "axis": LAYER}


def syn_rule(status="approved", axis=MODE):
    r = {"id": "s1", "type": "synonym_suggest", "status": status, "severity": "minor"}
    if axis:
        r["axis"] = axis
    return r


def ev(rec, rs, title=TITLE, broken=()):
    return l4_domain.evaluate(rec, {"title": title}, rs, TAX, SCHEMA, set(broken))


def codes_of(issues):
    return sorted(i["code"] for i in issues)


class AxisComboTest(unittest.TestCase):
    def test_expect_violation_and_pass(self):
        out = ev(record(**ax(mode=["EM"], phys=["dishing"])), rules(combo()))
        self.assertEqual(codes_of(out), ["L4_AXIS_COMBO_VIOLATION"])
        self.assertEqual(out[0]["severity"], "major")
        self.assertEqual(out[0]["field"], "axis:%s" % PHYS)
        self.assertEqual(ev(record(**ax(mode=["EM"], phys=["Void"])), rules(combo())), [])
        self.assertEqual(ev(record(**ax(mode=["Open"], phys=["dishing"])), rules(combo())), [])

    def test_expect_reserved_only_is_not_violation(self):
        self.assertEqual(ev(record(**ax(mode=["EM"], phys=[model.UNKNOWN])), rules(combo())), [])
        self.assertEqual(ev(record(**ax(mode=["EM"])), rules(combo())), [])

    def test_forbid(self):
        rs = rules(combo(kind="forbid", severity="minor"))
        out = ev(record(**ax(mode=["EM"], phys=["Void"])), rs)
        self.assertEqual(codes_of(out), ["L4_AXIS_COMBO_VIOLATION"])
        self.assertEqual(out[0]["severity"], "minor")
        self.assertEqual(ev(record(**ax(mode=["EM"], phys=["dishing"])), rs), [])


class TitleLabelTest(unittest.TestCase):
    def test_title_value_missing_and_present(self):
        out = ev(record(**ax(layer=["V1"])), rules(title_rule()))
        self.assertEqual(codes_of(out), ["L4_TITLE_LABEL_MISMATCH"])
        self.assertEqual(out[0]["severity"], "minor")
        self.assertEqual(out[0]["evidence"], {"rule_id": "t1", "value": "M1"})
        self.assertEqual(ev(record(**ax(layer=["M1"])), rules(title_rule())), [])

    def test_title_value_not_in_taxonomy_or_no_match(self):
        self.assertEqual(ev(record(**ax(layer=["V1"])), rules(title_rule()), title="주간 보고 1-2"), [])
        self.assertEqual(ev(record(**ax(layer=["V1"])), rules(title_rule()), title="QM1 보고"), [])
        self.assertEqual(l4_domain.evaluate(record(**ax(layer=["V1"])), None, rules(title_rule()), TAX, SCHEMA), [])


class SynonymTest(unittest.TestCase):
    def test_alias_suggests_canonical(self):
        out = ev(record(**ax(mode=["단락"])), rules(syn_rule()))
        self.assertEqual(codes_of(out), ["L4_SYNONYM_SUGGEST"])
        self.assertEqual(out[0]["severity"], "info")
        self.assertIn("Short", out[0]["suggested_fix"])
        self.assertFalse(out[0]["auto_fixed"])

    def test_norm_key_and_axis_scope(self):
        out = ev(record(**ax(layer=["metal 1"])), rules(syn_rule(axis=None)))
        self.assertEqual(codes_of(out), ["L4_SYNONYM_SUGGEST"])
        self.assertIn("M1", out[0]["suggested_fix"])
        # 표준값이 그 축의 값이 아니거나, 값이 이미 taxonomy 안이면 내지 않는다
        self.assertEqual(ev(record(**ax(mode=["보이드"])), rules(syn_rule())), [])
        self.assertEqual(ev(record(**ax(mode=["Short"])), rules(syn_rule())), [])
        self.assertEqual(ev(record(**ax(mode=["없는값"])), rules(syn_rule())), [])


class StatusAndSkipTest(unittest.TestCase):
    def test_draft_only_info_hit(self):
        rs = rules(combo(status="draft"), title_rule(status="draft"), syn_rule(status="draft"))
        rec = record(**ax(mode=["EM", "단락"], phys=["dishing"], layer=["V1"]))
        out = ev(rec, rs)
        self.assertEqual(codes_of(out), ["L4_RULE_DRAFT_HIT"] * 3)
        self.assertTrue(all(i["severity"] == "info" and i["suggested_fix"] is None for i in out))
        self.assertEqual(model.decide(out, policy.validate_policy({}))[0], "PASS")

    def test_approved_changes_verdict(self):
        out = ev(record(**ax(mode=["EM"], phys=["dishing"])), rules(combo()))
        self.assertEqual(model.decide(out, policy.validate_policy({}))[0], "REVIEW")

    def test_broken_fields_skipped(self):
        rec = record(**ax(mode=["EM", "단락"], phys=["dishing"], layer=["V1"]))
        rs = rules(combo(), title_rule(), syn_rule())
        self.assertEqual(len(ev(rec, rs)), 3)
        self.assertEqual(ev(rec, rs, broken={ALL}), [])
        self.assertEqual(ev(rec, rs, broken={"axes"}), [])
        out = ev(rec, rs, broken={"axis:%s" % PHYS, "axis:%s" % LAYER})
        self.assertEqual(codes_of(out), ["L4_SYNONYM_SUGGEST"])
        self.assertEqual(ev(rec, rs, broken={"axis:%s" % MODE}), ev(rec, rules(title_rule())))

    def test_non_content_chunk_skips_combo_and_title(self):
        rec = record("표지", **ax(mode=["EM", "단락"], phys=["dishing"], layer=["V1"]))
        out = ev(rec, rules(combo(), title_rule(), syn_rule()))
        self.assertEqual(codes_of(out), ["L4_SYNONYM_SUGGEST"])

    def test_evidence_has_no_title_or_body(self):
        rec = record(**ax(mode=["EM", "단락"], phys=["dishing"], layer=["V1"]))
        for status in ("approved", "draft"):
            out = ev(rec, rules(combo(status=status), title_rule(status=status), syn_rule(status=status)))
            self.assertEqual(len(out), 3)
            for i in out:
                self.assertEqual(set(i["evidence"]), {"rule_id", "value"})
                dumped = json.dumps(i, ensure_ascii=False)
                self.assertNotIn("RSBM", dumped)
                self.assertNotIn("비밀", dumped)
                self.assertTrue(all(len(v) <= 40 for v in i["evidence"].values()))


class RulesFileTest(unittest.TestCase):
    def bad(self, doc):
        with self.assertRaises(policy.PolicyError):
            domain_rules.validate(doc)

    def test_validation_failures(self):
        self.bad([])
        self.bad({"version": "v"})
        self.bad({"version": "v", "rules": {}})
        self.bad({"version": "v", "rules": [combo(), combo()]})
        self.bad({"version": "v", "rules": [dict(combo(), status="live")]})
        self.bad({"version": "v", "rules": [dict(combo(), severity="critical")]})
        self.bad({"version": "v", "rules": [dict(combo(), type="answer_dependency")]})
        self.bad({"version": "v", "rules": [dict(combo(), forbid={"axis": PHYS, "value_in": ["Void"]})]})
        self.bad({"version": "v", "rules": [dict(combo(), when={"axis": MODE, "value_in": []})]})
        self.bad({"version": "v", "rules": [dict(title_rule(), title_pattern="[MV][0-3]")]})
        self.bad({"version": "v", "rules": [dict(title_rule(), title_pattern="(")]})
        self.bad({"version": "v", "rules": [dict(syn_rule(), extra=1)]})

    def test_default_file_is_all_draft_and_covers_types(self):
        rs = domain_rules.load(domain_rules.DEFAULT_RULES_PATH)
        self.assertEqual(sorted(r["type"] for r in rs), sorted(domain_rules.TYPES))
        self.assertTrue(all(r["status"] == "draft" for r in rs))
        for r in rs:
            for c in (r.get("when"), r.get("expect"), r.get("forbid")):
                if c:
                    self.assertIn(c["axis"], TAX.values)
                    self.assertTrue(set(c["value_in"]) <= set(TAX.values[c["axis"]]))
            if r.get("axis"):
                self.assertIn(r["axis"], TAX.values)

    def test_policy_rules_path(self):
        d = tempfile.mkdtemp()
        try:
            good = os.path.join(d, "rules.json")
            with open(good, "w", encoding="utf-8") as f:
                json.dump({"version": "v", "rules": [combo()]}, f, ensure_ascii=False)
            self.assertEqual([r["id"] for r in l4_domain.rules_for({"l4": {"rules_path": good}})], ["c1"])
            self.assertEqual(domain_rules.rules_path({}), domain_rules.DEFAULT_RULES_PATH)
            bad = os.path.join(d, "bad.json")
            with open(bad, "w", encoding="utf-8") as f:
                json.dump({"version": "v", "rules": [dict(combo(), status="x")]}, f)
            with self.assertRaises(policy.PolicyError):
                l4_domain.rules_for({"l4": {"rules_path": bad}})
            with self.assertRaises(policy.PolicyError):
                l4_domain.rules_for({"l4": {"rules_path": os.path.join(d, "none.json")}})
        finally:
            shutil.rmtree(d, ignore_errors=True)


class EngineTest(unittest.TestCase):
    def run_layers(self, bundle, layers):
        p = policy.validate_policy({"layers": layers})
        ctx = engine.Ctx(bundle, p, SCHEMA, qa_run_id="QA-test")
        return engine.run(bundle, ctx)

    def test_default_draft_rules_keep_verdicts(self):
        bundle = synthetic.generate(seed=3, n_files=3, slides_range=(3, 4)).bundle.copy()
        content = [r for r in bundle.records if r.get("chunk_type") == SCHEMA["content_chunk_type"]]
        self.assertTrue(content)
        content[0]["axes"][MODE] = {"values": ["EM"], "status": "value", "confidence": 0.9}
        content[0]["axes"][PHYS] = {"values": ["dishing"], "status": "value", "confidence": 0.9}
        base = ["L0", "L1", "L2", "L3A"]
        off = self.run_layers(bundle, base)
        on = self.run_layers(bundle, base + ["L4"])
        self.assertEqual([(v["record_id"], v["verdict"]) for v in off["verdicts"]],
                         [(v["record_id"], v["verdict"]) for v in on["verdicts"]])
        l4 = [i for v in on["verdicts"] for i in v["issues"] if i["layer"] == "L4"]
        self.assertTrue(l4)
        self.assertEqual({i["code"] for i in l4}, {"L4_RULE_DRAFT_HIT"})

    def test_l4_not_in_default_layers(self):
        self.assertNotIn("L4", policy.validate_policy({})["layers"])


if __name__ == "__main__":
    unittest.main()
