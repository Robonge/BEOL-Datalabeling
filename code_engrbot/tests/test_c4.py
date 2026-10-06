"""C4 규칙 테스트."""
import unittest

from code_engrbot.checks.c4_hygiene import C4Hygiene
from code_engrbot.model import Ctx
from code_engrbot.scan import SourceFile

CTX = Ctx()


def run_src(src):
    return C4Hygiene().run(SourceFile("tests/x.py", src), CTX)


def rules(findings):
    return [f["rule"] for f in findings]


class SkipTest(unittest.TestCase):
    def test_decorators(self):
        for dec in ("@unittest.skip('r')", "@skip('r')", "@unittest.skipIf(True, 'r')",
                    "@unittest.skipUnless(False, 'r')", "@unittest.expectedFailure"):
            src = f"import unittest\n{dec}\ndef test_a():\n    assert 1\n"
            fs = run_src(src)
            self.assertEqual(rules(fs), ["C4_TEST_SKIP"], dec)
            self.assertEqual(fs[0]["line"], 2)
            self.assertEqual(fs[0]["severity"], "major")

    def test_pytest_skipif_lowercase(self):
        src = "import pytest\n@pytest.mark.skipif(True, reason='r')\ndef test_a():\n    assert 1\n"
        fs = run_src(src)
        self.assertEqual(rules(fs), ["C4_TEST_SKIP"])
        self.assertEqual(fs[0]["line"], 2)

    def test_skip_test_call_and_raise(self):
        src = "def t(self):\n    self.skipTest('r')\n"
        self.assertEqual(rules(run_src(src)), ["C4_TEST_SKIP"])
        src = "import unittest\ndef t():\n    raise unittest.SkipTest('r')\n"
        self.assertEqual(rules(run_src(src)), ["C4_TEST_SKIP"])

    def test_ok(self):
        self.assertEqual(run_src("def test_a():\n    assert 1\n"), [])


class PlaceholderTest(unittest.TestCase):
    def test_comment_markers(self):
        for mark in ("TODO", "FIXME", "XXX"):
            fs = run_src(f"x = 1  # {mark} 나중에\n")
            self.assertEqual(rules(fs), ["C4_PLACEHOLDER"], mark)
            self.assertEqual(fs[0]["severity"], "minor")

    def test_marker_in_string_ignored(self):
        self.assertEqual(run_src("s = 'TODO FIXME XXX'\nd = '''# TODO'''\n"), [])

    def test_empty_bodies(self):
        for body in ("pass", "...", "raise NotImplementedError", "raise NotImplementedError('x')"):
            fs = run_src(f"def f():\n    {body}\n")
            self.assertEqual(rules(fs), ["C4_PLACEHOLDER"], body)
            self.assertEqual(fs[0]["line"], 1)

    def test_docstring_then_pass(self):
        src = 'def f():\n    """설명이다."""\n    pass\n'
        self.assertEqual(rules(run_src(src)), ["C4_PLACEHOLDER"])

    def test_abstractmethod_exempt(self):
        src = ("import abc\nclass A:\n    @abc.abstractmethod\n    def run(self):\n        pass\n"
               "    @abstractmethod\n    def g(self):\n        raise NotImplementedError\n")
        self.assertEqual(run_src(src), [])

    def test_method_raise_not_implemented_exempt(self):
        for body in ("raise NotImplementedError", "raise NotImplementedError('x')"):
            for name in ("run", "complete"):
                src = f"class B:\n    def {name}(self):\n        {body}\n"
                self.assertEqual(run_src(src), [], f"{name} {body}")

    def test_concrete_run_pass_flagged(self):
        src = "class C:\n    def run(self):\n        pass\n"
        self.assertEqual(rules(run_src(src)), ["C4_PLACEHOLDER"])

    def test_module_function_raise_flagged(self):
        src = "def f():\n    raise NotImplementedError\n"
        self.assertEqual(rules(run_src(src)), ["C4_PLACEHOLDER"])

    def test_real_body_ok(self):
        self.assertEqual(run_src("def f():\n    '''설명이다.'''\n    return 1\n"), [])
        self.assertEqual(run_src("def f():\n    '''설명만 있다.'''\n"), [])


if __name__ == "__main__":
    unittest.main()
