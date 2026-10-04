"""QM0: 판정 엔진, 정책 로더, 카탈로그, 쓰기 확장자, 독립성 경계."""
import ast
import copy
import os
import shutil
import tempfile
import unittest

from qabot import codes, engine, io, model, policy, registry
from qabot.registry import Check
from qabot.tests import fixturegen

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LABELBOT_ALLOWED = {"adapters/labelbot_ws.py", "io.py", "llm_http.py"}


def small_bundle():
    return fixturegen.generate(seed=3, n_files=3, slides_range=(3, 4)).bundle


def run(bundle, layers, **pol):
    p = policy.validate_policy(dict(pol, layers=layers))
    s = policy.validate_schema({})
    ctx = engine.Ctx(bundle, p, s, qa_run_id="QA-test")
    return engine.run(bundle, ctx), ctx


class _Fake(object):
    """테스트에서만 등록하는 가짜 검사들."""

    registered = []

    @classmethod
    def add(cls, check_cls):
        registry.register(check_cls)
        cls.registered.append(check_cls.id)
        return check_cls

    @classmethod
    def clear(cls):
        for cid in cls.registered:
            registry.unregister(cid)
        cls.registered = []


class EngineTest(unittest.TestCase):
    def tearDown(self):
        _Fake.clear()

    def test_no_checks_all_pass(self):
        b = small_bundle()
        out, _ = run(b, [])
        self.assertEqual(len(out["verdicts"]), len(b.records))
        self.assertTrue(all(v["verdict"] == "PASS" and v["score"] == 100 for v in out["verdicts"]))

    def test_severity_to_verdict_table(self):
        plan = {}

        class Sev(Check):
            id = "test.sev"
            layer = "L4"
            scope = "record"

            def run(self, target, ctx):
                return [model.issue(c, field="x") for c in plan.get(target.record_id, [])]

        _Fake.add(Sev)
        b = small_bundle()
        rids = sorted(r["record_id"] for r in b.records)
        cases = [
            (["L3_SPAN_NOT_FOUND"], "REJECT"),
            (["L3_NOT_SUPPORTED"], "REVIEW"),
            (["L1_FORMAT_NORMALIZED"], "AUTO_FIX"),
            (["L1_UNKNOWN_FIELD"], "PASS"),
            (["L1_LOT_ID_UNCOMMON"], "PASS"),
            (["L1_FORMAT_NORMALIZED", "L3_NOT_SUPPORTED"], "REVIEW"),
            (["L1_FORMAT_NORMALIZED", "L1_UNKNOWN_FIELD"], "AUTO_FIX"),
            (["L3_NOT_SUPPORTED", "L3_SPAN_NOT_FOUND", "L1_FORMAT_NORMALIZED"], "REJECT"),
        ]
        for rid, (cs, _) in zip(rids, cases):
            plan[rid] = cs
        out, _ = run(b, ["L4"])
        vm = {v["record_id"]: v for v in out["verdicts"]}
        for rid, (cs, want) in zip(rids, cases):
            self.assertEqual(vm[rid]["verdict"], want, cs)
        self.assertEqual(vm[rids[7]]["score"], 0)
        self.assertEqual(vm[rids[1]]["score"], 70)

    def test_l4_extension_runs_without_engine_change(self):
        class Domain(Check):
            id = "test.l4_domain"
            layer = "L4"
            scope = "record"

            def run(self, target, ctx):
                return [model.issue("L2_TAXONOMY_STALE", field="axes")]

        _Fake.add(Domain)
        out, _ = run(small_bundle(), ["L1", "L4"])
        self.assertTrue(all(any(i["code"] == "L2_TAXONOMY_STALE" for i in v["issues"]) for v in out["verdicts"]))

    def test_severity_override_applies(self):
        class Rej(Check):
            id = "test.rej"
            layer = "L4"
            scope = "record"

            def run(self, target, ctx):
                return [model.issue("L3_SPAN_NOT_FOUND", field="x")]

        _Fake.add(Rej)
        out, _ = run(small_bundle(), ["L4"], severity_overrides={"L3_SPAN_NOT_FOUND": "major"})
        self.assertTrue(all(v["verdict"] == "REVIEW" for v in out["verdicts"]))

    def test_file_scope_issue_propagates_to_all_records(self):
        class FileCheck(Check):
            id = "test.file"
            layer = "L4"
            scope = "file"

            def run(self, target, ctx):
                if target.file_id == min(ctx.bundle.sources):
                    return [model.issue("L0_PAGE_COUNT_MISMATCH", field="file")]
                return []

        _Fake.add(FileCheck)
        b = small_bundle()
        out, _ = run(b, ["L4"])
        fid = min(b.sources)
        for v in out["verdicts"]:
            self.assertEqual(v["verdict"], "REVIEW" if v["file_id"] == fid else "PASS")
        self.assertEqual([(i["file_id"], i["code"]) for i in out["file_issues"]], [(fid, "L0_PAGE_COUNT_MISMATCH")])

    def test_file_check_record_issue_goes_to_one_record(self):
        class Unit(Check):
            id = "test.unit"
            layer = "L4"
            scope = "file"

            def run(self, target, ctx):
                return [model.issue("L0_EMPTY_UNIT", field="unit", record_id=target.records[0]["record_id"])]

        _Fake.add(Unit)
        b = small_bundle()
        out, _ = run(b, ["L4"])
        self.assertEqual(sum(v["verdict"] == "REVIEW" for v in out["verdicts"]), len(b.sources))
        self.assertEqual(out["file_issues"], [])

    def test_l3b_skipped_for_critical_records(self):
        calls = []

        class CritL3A(Check):
            id = "test.crit_l3a"
            layer = "L3A"
            scope = "record"

            def run(self, target, ctx):
                if target.record_id.endswith("slide2.xml"):
                    return [model.issue("L3_SPAN_NOT_FOUND", field="x")]
                return []

        class Judge(Check):
            id = "test.judge"
            layer = "L3B"
            scope = "record"

            def run(self, target, ctx):
                calls.append(target.record_id)
                return []

        for c in (CritL3A, Judge):
            _Fake.add(c)
        b = small_bundle()
        p = policy.validate_policy({"layers": ["L3A", "L3B"]})
        engine.run(b, engine.Ctx(b, p, policy.validate_schema({})))
        self.assertTrue(calls)
        self.assertFalse([r for r in calls if r.endswith("slide2.xml")])

    def test_verdict_has_versions_and_input_hash(self):
        b = small_bundle()
        p = policy.validate_policy({"layers": ["L1"]})
        s = policy.validate_schema({})
        ctx = engine.Ctx(b, p, s, qa_run_id="QA-x", versions={"taxonomy": "t", "schema": "s", "reviewer": "r", "policy": "p"})
        v = engine.run(b, ctx)["verdicts"][0]
        self.assertEqual(set(v["versions"]), {"taxonomy", "schema", "reviewer", "policy", "labeler_prompt"})
        self.assertEqual(len(v["input_hash"]), 64)

    def test_fingerprint_stable_and_label_sensitive(self):
        b1, b2 = small_bundle(), small_bundle()
        self.assertEqual(b1.fingerprint(), b2.fingerprint())
        b2.records[1]["labeler"]["created_at"] = "2030-01-01T00:00:00Z"
        self.assertEqual(b1.fingerprint(), b2.fingerprint())
        b2.records[1]["chunk_type"] = "목차"
        self.assertNotEqual(b1.fingerprint(), b2.fingerprint())


class PolicyTest(unittest.TestCase):
    def test_defaults_valid(self):
        policy.validate_policy({})
        policy.validate_schema({})

    def test_rejects_unknown_key(self):
        with self.assertRaises(policy.PolicyError) as cm:
            policy.validate_policy({"l0": {"coverage_majr": 0.5}})
        self.assertIn("UNKNOWN_KEY:l0.coverage_majr", cm.exception.problems)

    def test_rejects_out_of_range(self):
        for user, code in (({"l0": {"coverage_major": 1.5}}, "OUT_OF_RANGE:l0.coverage_major"),
                           ({"judge": {"workers": 0}}, "OUT_OF_RANGE:judge.workers"),
                           ({"judge": {"transport": "smtp"}}, "OUT_OF_RANGE:judge.transport"),
                           ({"layers": ["L9"]}, "LAYER_UNKNOWN:L9"),
                           ({"l0": {"coverage_major": "high"}}, "TYPE_INVALID:l0.coverage_major")):
            with self.assertRaises(policy.PolicyError) as cm:
                policy.validate_policy(user)
            self.assertIn(code, cm.exception.problems)

    def test_rejects_fail_safe_downgrade(self):
        for code in ("L3_JUDGE_FAILED", "L3_JUDGE_SKIPPED"):
            for sev in ("minor", "info"):
                with self.assertRaises(policy.PolicyError) as cm:
                    policy.validate_policy({"severity_overrides": {code: sev}})
                self.assertIn("FAIL_SAFE_DOWNGRADE:%s" % code, cm.exception.problems)
        policy.validate_policy({"severity_overrides": {"L3_JUDGE_FAILED": "critical"}})

    def test_rejects_mapping_that_lets_critical_pass(self):
        with self.assertRaises(policy.PolicyError):
            policy.validate_policy({"verdict": {"severity_to_verdict": {"critical": "PASS", "major": "REVIEW",
                                                                        "fixable": "AUTO_FIX", "minor": "PASS",
                                                                        "info": "PASS"}}})

    def test_auto_fix_only_from_fixable(self):
        base = {"critical": "REJECT", "major": "REVIEW", "fixable": "AUTO_FIX", "minor": "PASS", "info": "PASS"}
        for sev in ("minor", "info"):
            with self.assertRaises(policy.PolicyError) as cm:
                policy.validate_policy({"verdict": {"severity_to_verdict": dict(base, **{sev: "AUTO_FIX"})}})
            self.assertIn("AUTO_FIX_ONLY_FOR_FIXABLE:%s" % sev, cm.exception.problems)
        with self.assertRaises(policy.PolicyError):
            policy.validate_policy({"verdict": {"severity_to_verdict": dict(base, fixable="PASS")}})
        policy.validate_policy({"verdict": {"severity_to_verdict": dict(base, fixable="REVIEW", minor="REVIEW")}})

    def test_temperature_nullable(self):
        self.assertIsNone(policy.validate_policy({"judge": {"temperature": None}})["judge"]["temperature"])

    def test_rejects_unknown_autofix_rule_and_code(self):
        with self.assertRaises(policy.PolicyError):
            policy.validate_policy({"autofix": {"approved_rules": ["synonym_replace"]}})
        with self.assertRaises(policy.PolicyError):
            policy.validate_policy({"severity_overrides": {"L9_NOPE": "major"}})

    def test_schema_rejects_bad_pattern(self):
        with self.assertRaises(policy.PolicyError):
            policy.validate_schema({"formats": {"x": {"pattern": "(", "applies_to": {"axis": "a"}}}})
        with self.assertRaises(policy.PolicyError):
            policy.validate_schema({"oops": 1})

    def test_load_writes_defaults_and_snapshots_inputs(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        paths = io.QaPaths(tmp)
        pol, sch = policy.load(paths)
        self.assertTrue(os.path.isfile(paths.policy) and os.path.isfile(paths.schema))
        self.assertTrue(any(n.endswith(".b64") for n in os.listdir(paths.inputs_dir)))
        self.assertEqual(pol["version"], policy.default_policy()["version"])


class CatalogTest(unittest.TestCase):
    def test_every_emitted_code_is_in_catalog(self):
        """검사 모듈 소스의 모든 코드 문자열이 카탈로그에 있다."""
        import re

        cat = codes.catalog()
        found = set()
        for root, _, files in os.walk(os.path.join(PKG, "checks")):
            for fn in files:
                if fn.endswith(".py"):
                    with open(os.path.join(root, fn), encoding="utf-8") as f:
                        found |= set(re.findall(r'"(L[0-6]A?B?_[A-Z_]+)"', f.read()))
        self.assertTrue(found)
        self.assertEqual(sorted(found - set(cat)), [])

    def test_every_catalog_code_is_emitted(self):
        """카탈로그의 코드는 모두 어떤 검사가 낸다(6.4절). judge 코드는 judge.py가 낸다."""
        import re

        found = set()
        sources = [os.path.join(PKG, "checks", f) for f in os.listdir(os.path.join(PKG, "checks")) if f.endswith(".py")]
        for p in sources + [os.path.join(PKG, "judge.py")]:
            with open(p, encoding="utf-8") as f:
                found |= set(re.findall(r'"(L[0-6]A?B?_[A-Z_]+)"', f.read()))
        self.assertEqual(sorted(set(codes.catalog()) - found), [])

    def test_catalog_entries_valid(self):
        for code, c in codes.catalog().items():
            self.assertIn(c["layer"], model.LAYERS, code)
            self.assertIn(c["severity"], model.SEVERITIES, code)
            self.assertIn(c["scope"], model.SCOPES, code)
            self.assertIn(c["severity"], codes.allowed_severities(code), code)
            self.assertTrue(code.startswith(c["layer"][:2]), code)

    def test_render_md(self):
        md = codes.render_md()
        self.assertIn("L3_JUDGE_FAILED", md)
        self.assertIn("fail-safe", md)

    def test_doc_in_sync_with_catalog(self):
        with open(codes.DOC_PATH, encoding="utf-8") as f:
            self.assertEqual(f.read(), codes.render_md() + "\n", "python -m qabot codes로 문서를 다시 만든다")


class WriteRuleTest(unittest.TestCase):
    def test_forbidden_extension_raises(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        for ext in (".txt", ".csv", ".pptx", ".xlsx", ".docx"):
            with self.assertRaises(ValueError):
                io.write_text(os.path.join(tmp, "x" + ext), "a")
            with self.assertRaises(ValueError):
                io.append_jsonl(os.path.join(tmp, "x" + ext), {})
        io.write_json(os.path.join(tmp, "ok.json"), {"a": 1})

    def test_workspace_inside_code_refused(self):
        with self.assertRaises(io.QaPathError):
            io.QaPaths(os.path.join(PKG, "tmp_ws"), create=False)

    def test_strip_text(self):
        v = {"issues": [{"code": "L3_NOT_SUPPORTED", "reason": "본문 조각", "evidence": {"text": "x", "judge_reason": "y",
                                                                                      "quote_len": 3}}]}
        s = io.strip_text(v)
        self.assertEqual(s["issues"][0]["evidence"], {"quote_len": 3})
        self.assertNotEqual(s["issues"][0]["reason"], "본문 조각")


class BoundaryTest(unittest.TestCase):
    def test_only_adapter_io_llm_http_import_labelbot(self):
        bad = []
        for root, dirs, files in os.walk(PKG):
            dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__")]
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, PKG).replace(os.sep, "/")
                with open(full, encoding="utf-8") as f:
                    tree = ast.parse(f.read())
                for node in ast.walk(tree):
                    names = []
                    if isinstance(node, ast.Import):
                        names = [a.name for a in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        names = [node.module]
                    if any(n == "labelbot" or n.startswith("labelbot.") for n in names) and rel not in LABELBOT_ALLOWED:
                        bad.append(rel)
        self.assertEqual(sorted(set(bad)), [])


if __name__ == "__main__":
    unittest.main()
