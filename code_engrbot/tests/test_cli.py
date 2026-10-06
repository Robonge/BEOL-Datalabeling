import contextlib
import io
import json
import os
import tempfile
import unittest

from code_engrbot import cli, registry


class _Crit(registry.Check):
    layer = "C5"
    scope = "file"
    rules = {"T_CLI_CRIT": {"severity": "critical", "desc": "치명"}}

    def run(self, target, ctx):
        return [self.finding("T_CLI_CRIT", target.path, 1, "m", suggested_fix="고친다")]


def _snapshot(root):
    out = set()
    for dp, _, names in os.walk(root):
        for n in names:
            out.add(os.path.relpath(os.path.join(dp, n), root).replace(os.sep, "/"))
    return out


class CliTest(unittest.TestCase):
    def _review(self, root, out, layers):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cli.main(["review", "--root", root, "--paths", "pkg", "--layers", layers, "--out", out])
        return code, buf.getvalue()

    def _make_repo(self, d):
        os.makedirs(os.path.join(d, "pkg"))
        with open(os.path.join(d, "pkg", "a.py"), "w", encoding="utf-8") as fh:
            fh.write("x = 1\n")

    def test_request_changes_exit_1_and_three_reports_only(self):
        registry.register(_Crit)
        try:
            with tempfile.TemporaryDirectory() as d:
                self._make_repo(d)
                before = _snapshot(d)
                out = os.path.join(d, "out")
                code, text = self._review(d, out, "C5")
                self.assertEqual(code, 1)
                self.assertIn("REQUEST_CHANGES", text)
                self.assertEqual(len(text.strip().splitlines()), 1)
                after = _snapshot(d)
                added = after - before
                ids = os.listdir(out)
                self.assertEqual(len(ids), 1)
                self.assertTrue(ids[0].startswith("CR-"))
                self.assertEqual(added, {"out/%s/%s" % (ids[0], n) for n in ("findings.jsonl", "review.md", "manifest.json")})
                with open(os.path.join(out, ids[0], "manifest.json"), encoding="utf-8") as fh:
                    manifest = json.load(fh)
                self.assertEqual(manifest["verdict"], "REQUEST_CHANGES")
                self.assertEqual(manifest["review_id"], ids[0])
                with open(os.path.join(out, ids[0], "findings.jsonl"), encoding="utf-8") as fh:
                    rows = [json.loads(line) for line in fh]
                self.assertEqual(rows[0]["rule"], "T_CLI_CRIT")
                with open(os.path.join(out, ids[0], "review.md"), encoding="utf-8") as fh:
                    self.assertIn("pkg/a.py:1", fh.read())
        finally:
            registry.unregister(_Crit)

    def test_approve_exit_0(self):
        with tempfile.TemporaryDirectory() as d:
            self._make_repo(d)
            code, text = self._review(d, os.path.join(d, "out"), "C6")
            self.assertEqual(code, 0)
            self.assertIn("APPROVE", text)

    def _review_paths(self, root, paths):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cli.main(["review", "--root", root, "--paths"] + paths + ["--layers", "C6", "--out", os.path.join(root, "out")])
        return code, buf.getvalue()

    def test_paths_space_and_comma_forms(self):
        with tempfile.TemporaryDirectory() as d:
            self._make_repo(d)
            os.makedirs(os.path.join(d, "pkg2"))
            with open(os.path.join(d, "pkg2", "b.py"), "w", encoding="utf-8") as fh:
                fh.write("y = 1\n")
            for paths in (["pkg", "pkg2"], ["pkg,pkg2"]):
                code, text = self._review_paths(d, paths)
                self.assertEqual(code, 0)
                self.assertIn("APPROVE", text)
            self.assertEqual(cli._split_paths(["pkg", "pkg2,pkg3"]), ["pkg", "pkg2", "pkg3"])

    def test_check_error_exit_2_and_errors_in_line(self):
        class _Boom(registry.Check):
            layer = "C5"
            scope = "repo"
            rules = {"T_CLI_BOOM": {"severity": "info", "desc": "예외"}}

            def run(self, target, ctx):
                raise RuntimeError("x")

        registry.register(_Boom)
        try:
            with tempfile.TemporaryDirectory() as d:
                self._make_repo(d)
                code, text = self._review(d, os.path.join(d, "out"), "C5")
                self.assertEqual(code, 2)
                self.assertIn("COMMENT", text)
                self.assertTrue(text.strip().endswith("errors=1"))
        finally:
            registry.unregister(_Boom)

    def test_policy_deep_merge(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "p.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"c1": {"ingest_modules": ["x/y.py"]}}, fh)
            policy = cli._load_policy(path)
            self.assertEqual(policy["c1"]["ingest_modules"], ["x/y.py"])
            self.assertIn("forbidden_write_exts", policy["c1"])
            self.assertIn("local_packages", policy["c1"])

    def test_rules_command_writes_catalog(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "docs", "rules.md")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(["rules", "--out", path]), 0)
            with open(path, encoding="utf-8") as fh:
                self.assertIn("| 규칙 |", fh.read())


if __name__ == "__main__":
    unittest.main()
