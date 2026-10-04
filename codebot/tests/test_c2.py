"""C2 규칙 테스트."""
import unittest

from codebot.checks.c2_stack import C2Requirements, C2Stack
from codebot.model import Ctx
from codebot.scan import RepoIndex, SourceFile

CTX = Ctx()


def run_file(src, path="labelbot/x.py"):
    return C2Stack().run(SourceFile(path, src), CTX)


def rules(findings):
    return [f["rule"] for f in findings]


class SyntaxTest(unittest.TestCase):
    def test_violation(self):
        fs = run_file("def f(:\n    pass\n")
        self.assertEqual(rules(fs), ["C2_PY314_SYNTAX"])
        self.assertEqual(fs[0]["severity"], "critical")

    def test_ok(self):
        self.assertEqual(run_file("x = 1\n"), [])


class TransportTest(unittest.TestCase):
    def test_urlopen_call(self):
        src = "import urllib.request\nurllib.request.urlopen('u')\n"
        fs = run_file(src)
        self.assertEqual(rules(fs), ["C2_TRANSPORT_BYPASS"])
        self.assertEqual(fs[0]["line"], 2)

    def test_bare_urlopen_and_opener(self):
        src = "from urllib.request import urlopen, build_opener\nurlopen('u')\nbuild_opener()\n"
        self.assertEqual(rules(run_file(src)), ["C2_TRANSPORT_BYPASS"] * 2)

    def test_imports(self):
        for mod in ("http.client", "socket", "ftplib", "smtplib"):
            self.assertEqual(rules(run_file(f"import {mod}\n")), ["C2_TRANSPORT_BYPASS"], mod)
        self.assertEqual(rules(run_file("from http import client\n")), ["C2_TRANSPORT_BYPASS"])

    def test_http_server_ok(self):
        self.assertEqual(run_file("import http.server\nfrom http.server import HTTPServer\n"), [])

    def test_transport_module_and_tests_exempt(self):
        src = "import socket\nimport urllib.request\nurllib.request.urlopen('u')\n"
        self.assertEqual(run_file(src, "labelbot/llm.py"), [])
        self.assertEqual(run_file(src, "codebot/tests/test_x.py"), [])


class SecretTest(unittest.TestCase):
    def check(self, value):
        src = f"KEY = {value!r}\n"
        fs = run_file(src)
        self.assertEqual(rules(fs), ["C2_SECRET_LITERAL"])
        self.assertEqual(fs[0]["severity"], "critical")
        self.assertNotIn(value, fs[0]["message"])
        self.assertNotIn(value[3:], fs[0]["message"])
        return fs[0]

    def test_shapes(self):
        self.check("sk-" + "a" * 24)
        self.check("eyJ" + "a" * 12 + "." + "b" * 12 + "." + "c" * 8)
        self.check("AKIA" + "A1" * 8)
        self.check("ghp_" + "x" * 32)

    def test_real_key_formats(self):
        self.check("sk-ant-api03-" + "A" * 40)
        self.check("sk-proj-" + "A" * 40)

    def test_id_with_alnum_before_prefix_ok(self):
        self.assertEqual(run_file(f"A = {'disk-' + 'a' * 25!r}\n"), [])
        self.assertEqual(run_file(f"A = {'task-' + 'a1b2c3' * 4!r}\n"), [])

    def test_message_has_prefix_and_length_only(self):
        f = self.check("sk-" + "a" * 24)
        self.assertIn("sk-", f["message"])
        self.assertIn("27", f["message"])

    def test_ok(self):
        self.assertEqual(run_file("A = 'sk-short'\nB = 'AKIA123'\nC = 'ghp_abc'\n"), [])


class RequirementsTest(unittest.TestCase):
    def run_req(self, text):
        texts = {} if text is None else {"requirements.txt": text}
        return C2Requirements().run(RepoIndex(".", [], texts=texts), CTX)

    def test_violation(self):
        fs = self.run_req("# 주석\n\nrequests==2.0\n")
        self.assertEqual(rules(fs), ["C2_REQUIREMENTS_NOT_EMPTY"])
        self.assertEqual(fs[0]["path"], "requirements.txt")
        self.assertEqual(fs[0]["line"], 3)

    def test_ok(self):
        self.assertEqual(self.run_req("# 주석만\n\n"), [])

    def test_missing_file(self):
        self.assertEqual(self.run_req(None), [])


if __name__ == "__main__":
    unittest.main()
