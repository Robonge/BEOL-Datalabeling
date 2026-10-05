import os
import tempfile
import unittest

from codebot import model, registry, review, scan


class _Fake(registry.Check):
    layer = "C5"
    scope = "file"
    rules = {
        "T_CRIT": {"severity": "critical", "desc": "치명"},
        "T_MAJOR": {"severity": "major", "desc": "주요"},
        "T_MINOR": {"severity": "minor", "desc": "경미"},
    }
    emit = []

    def run(self, target, ctx):
        return [self.finding(r, target.path, ln, "m") for r, ln in type(self).emit]


class _Boom(registry.Check):
    layer = "C5"
    scope = "repo"
    rules = {"T_BOOM": {"severity": "info", "desc": "예외"}}

    def run(self, target, ctx):
        raise RuntimeError("x")


def _index(text="a = 1\nb = 2  # codebot: allow T_CRIT\n"):
    return scan.RepoIndex(".", [scan.SourceFile("pkg/a.py", text)])


class DecideTest(unittest.TestCase):
    def test_table(self):
        f = lambda s, sup=False: {"severity": s, "suppressed": sup}
        self.assertEqual(model.decide([f("critical"), f("major")]), "REQUEST_CHANGES")
        self.assertEqual(model.decide([f("major"), f("minor")]), "COMMENT")
        self.assertEqual(model.decide([f("minor"), f("info")]), "APPROVE")
        self.assertEqual(model.decide([f("critical", True)]), "APPROVE")
        self.assertEqual(model.decide([]), "APPROVE")


class ReviewTest(unittest.TestCase):
    def setUp(self):
        registry.register(_Fake)

    def tearDown(self):
        registry.unregister(_Fake)
        _Fake.emit = []

    def _run(self, emit, policy=None, index=None):
        _Fake.emit = emit
        ctx = model.Ctx(policy=policy)
        return review.run(index or _index(), ctx, layers=["C5"])

    def test_verdicts(self):
        self.assertEqual(self._run([("T_CRIT", 1)])["verdict"], "REQUEST_CHANGES")
        self.assertEqual(self._run([("T_MAJOR", 1)])["verdict"], "COMMENT")
        self.assertEqual(self._run([("T_MINOR", 1)])["verdict"], "APPROVE")

    def test_line_comment_suppresses(self):
        r = self._run([("T_CRIT", 2)])
        self.assertTrue(r["findings"][0]["suppressed"])
        self.assertEqual(r["verdict"], "APPROVE")
        self.assertEqual(r["counts"]["suppressed"], 1)
        self.assertEqual(r["counts"]["critical"], 0)

    def test_policy_allow_suppresses(self):
        policy = model.default_policy()
        policy["allow"] = [{"rule": "T_CRIT", "path": "pkg/*.py", "reason": "시험"}]
        r = self._run([("T_CRIT", 1)], policy=policy)
        self.assertTrue(r["findings"][0]["suppressed"])

    def test_severity_override(self):
        policy = model.default_policy()
        policy["severity_overrides"] = {"T_CRIT": "minor"}
        r = self._run([("T_CRIT", 1)], policy=policy)
        self.assertEqual(r["findings"][0]["severity"], "minor")
        self.assertEqual(r["verdict"], "APPROVE")

    def test_sorted_by_severity(self):
        r = self._run([("T_MINOR", 1), ("T_CRIT", 1), ("T_MAJOR", 1)])
        self.assertEqual([f["severity"] for f in r["findings"]], ["critical", "major", "minor"])

    def test_check_exception_is_recorded(self):
        registry.register(_Boom)
        try:
            r = self._run([("T_MAJOR", 1)])
            self.assertEqual(len(r["errors"]), 1)
            self.assertEqual(r["errors"][0]["check"], "_Boom")
            self.assertEqual(r["verdict"], "COMMENT")
            # 오류가 있으면 finding이 없어도 APPROVE가 아니다
            self.assertEqual(self._run([("T_MINOR", 1)])["verdict"], "COMMENT")
            # REQUEST_CHANGES는 오류가 있어도 그대로다
            self.assertEqual(self._run([("T_CRIT", 1)])["verdict"], "REQUEST_CHANGES")
        finally:
            registry.unregister(_Boom)

    def test_unknown_rule_raises(self):
        with self.assertRaises(KeyError):
            _Fake().finding("NOPE", "a.py", 1, "m")


class ScanTest(unittest.TestCase):
    def test_syntax_error_kept(self):
        s = scan.SourceFile("a.py", "def (:\n")
        self.assertIsNone(s.tree)
        self.assertEqual(s.syntax_error[0], 1)

    def test_parent_attribute(self):
        s = scan.SourceFile("a.py", "x = f(1)\n")
        self.assertIsNone(s.tree.parent)
        call = s.tree.body[0].value
        self.assertIs(call.parent, s.tree.body[0])

    def test_allowed_only_that_rule_and_line(self):
        s = scan.SourceFile("a.py", "x = 1  # codebot: allow R_A\ny = 2\n")
        self.assertTrue(s.allowed("R_A", 1))
        self.assertFalse(s.allowed("R_B", 1))
        self.assertFalse(s.allowed("R_A", 2))

    def test_allowed_multiline_call_second_line(self):
        s = scan.SourceFile("a.py", "x = f(\n    1,  # codebot: allow R_A\n)\ny = 2\n")
        self.assertTrue(s.allowed("R_A", 1))
        self.assertFalse(s.allowed("R_A", 4))

    def test_allowed_decorator_line(self):
        s = scan.SourceFile("a.py", "@deco  # codebot: allow R_A\ndef f():\n    pass\n")
        self.assertTrue(s.allowed("R_A", 2))
        self.assertTrue(s.allowed("R_A", 1))

    def test_allowed_first_body_line_of_def(self):
        s = scan.SourceFile("a.py", "def f():\n    a = 1  # codebot: allow R_A\n    b = 2\n    c = 3\n")
        self.assertTrue(s.allowed("R_A", 1))
        self.assertFalse(s.allowed("R_A", 3))

    def test_allowed_out_of_range_not_suppressed(self):
        s = scan.SourceFile("a.py", "def f():\n    a = 1\n    b = 2  # codebot: allow R_A\n")
        self.assertFalse(s.allowed("R_A", 1))
        self.assertFalse(s.allowed("R_A", 2))
        s2 = scan.SourceFile("a.py", "x = 1\ny = 2  # codebot: allow R_A\n")
        self.assertFalse(s2.allowed("R_A", 1))

    def test_texts_take_precedence_over_disk(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "x.md"), "w", encoding="utf-8") as fh:
                fh.write("disk")
            idx = scan.RepoIndex(d, [], texts={"x.md": "memory", "y.md": "only"})
            self.assertEqual(idx.read_text("x.md"), "memory")
            self.assertEqual(idx.read_text("y.md"), "only")
            self.assertIsNone(idx.read_text("none.md"))
            self.assertEqual(idx.glob("*.md"), ["x.md", "y.md"])

    def test_build_marks_unreadable_file(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "pkg"))
            with open(os.path.join(d, "pkg", "bad.py"), "wb") as fh:
                fh.write(b"\xff\xfe\x00bad")
            with open(os.path.join(d, "pkg", "ok.py"), "w", encoding="utf-8") as fh:
                fh.write("x = 1\n")
            idx = scan.build(d, ["pkg"], [])
            self.assertEqual([f.path for f in idx.files], ["pkg/bad.py", "pkg/ok.py"])
            self.assertIsNotNone(idx.get("pkg/bad.py").syntax_error)
            self.assertIsNone(idx.get("pkg/ok.py").syntax_error)

    def test_build_exclude(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "pkg", "out"))
            for rel in ("pkg/a.py", "pkg/out/b.py"):
                with open(os.path.join(d, rel), "w", encoding="utf-8") as fh:
                    fh.write("x = 1\n")
            idx = scan.build(d, ["pkg"], ["pkg/out/**"])
            self.assertEqual([f.path for f in idx.files], ["pkg/a.py"])


class ScanHelpersTest(unittest.TestCase):
    def test_dotted_and_leaf_name(self):
        import ast
        expr = lambda src: ast.parse(src, mode="eval").body
        self.assertEqual(scan.dotted(expr("a.b.c")), "a.b.c")
        self.assertEqual(scan.dotted(expr("f().b")), "")
        self.assertEqual(scan.leaf_name(expr("a.b.c")), "c")
        self.assertEqual(scan.leaf_name(expr("f().b")), "b")
        self.assertEqual(scan.leaf_name(expr("pkg.NotImplementedError()")), "NotImplementedError")
        self.assertIsNone(scan.leaf_name(expr("1")))

    def test_read_file_utf8_sig_and_errors(self):
        with tempfile.TemporaryDirectory() as d:
            ok = os.path.join(d, "ok.md")
            with open(ok, "wb") as fh:
                fh.write(b"\xef\xbb\xbf" + "가나".encode("utf-8"))
            bad = os.path.join(d, "bad.md")
            with open(bad, "wb") as fh:
                fh.write(b"\xff\xfe\x80")
            self.assertEqual(scan.read_file(ok), ("가나", None))
            self.assertEqual(scan.read_file(bad), ("", "READ_DECODE_FAILED"))
            self.assertEqual(scan.read_file(os.path.join(d, "none")), ("", "READ_FAILED"))
            self.assertIsNone(scan.RepoIndex(d, []).read_text("bad.md"))
            self.assertEqual(scan.RepoIndex(d, []).read_text("ok.md"), "가나")


if __name__ == "__main__":
    unittest.main()
