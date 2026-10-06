import unittest

import code_engrbot.checks.c1_governing  # noqa: F401  (등록)
from code_engrbot.checks.c1_governing import GoverningCheck
from code_engrbot.model import Ctx
from code_engrbot.scan import SourceFile


def run(src, path="labelbot/x.py"):
    return GoverningCheck().run(SourceFile(path, src), Ctx())


def rules(src, path="labelbot/x.py"):
    return [f["rule"] for f in run(src, path)]


class PathParserTest(unittest.TestCase):
    def test_flags_path_parsers(self):
        self.assertEqual(rules("from pptx import Presentation\nPresentation('a.pptx')\n").count("C1_PATH_PARSER"), 1)
        self.assertIn("C1_PATH_PARSER", rules("import openpyxl\nopenpyxl.load_workbook(p)\n"))
        self.assertIn("C1_PATH_PARSER", rules("import pandas as pd\npd.read_csv('a.csv')\n"))
        self.assertIn("C1_PATH_PARSER", rules("import csv\ncsv.reader(open(p))\n"))

    def test_zipfile_path_is_flagged(self):
        for arg in ("'a.zip'", "f'{d}/a.zip'", "os.path.join(d, 'a')", "Path(d)", "src_path", "file_name"):
            self.assertIn("C1_PATH_PARSER", rules(f"import zipfile\nzipfile.ZipFile({arg})\n"), arg)
        self.assertIn("C1_PATH_PARSER", rules("from zipfile import ZipFile\nZipFile('a.zip')\n"))

    def test_zipfile_bytesio_is_ok(self):
        self.assertEqual(rules("import io, zipfile\nzipfile.ZipFile(io.BytesIO(b))\n"), [])
        src = "import io, zipfile\ndef f(b):\n    file_buf = io.BytesIO(b)\n    return zipfile.ZipFile(file_buf)\n"
        self.assertEqual(rules(src), [])

    def test_zipfile_uncertain_arg_is_not_flagged(self):
        self.assertEqual(rules("import zipfile\ndef f(x):\n    return zipfile.ZipFile(x)\n"), [])
        self.assertEqual(rules("import zipfile\nzipfile.ZipFile(self.buf)\n"), [])

    def test_zipfile_name_tokens(self):
        for name in ("src_path", "file", "zip_path", "fname", "filename"):
            self.assertIn("C1_PATH_PARSER", rules(f"import zipfile\nzipfile.ZipFile({name})\n"), name)
        for name in ("profile", "fileobj", "buf"):
            self.assertEqual(rules(f"import zipfile\nzipfile.ZipFile({name})\n"), [], name)

    def test_memory_arg_for_other_parsers_is_ok(self):
        src = "from pptx import Presentation\nimport io\nPresentation(io.BytesIO(b))\n"
        self.assertEqual(rules(src).count("C1_PATH_PARSER"), 0)


class ImportTest(unittest.TestCase):
    def test_third_party_flagged(self):
        fs = run("import requests\nfrom numpy import array\n")
        self.assertEqual([f["rule"] for f in fs], ["C1_NONSTDLIB_IMPORT"] * 2)

    def test_stdlib_local_relative_ok(self):
        src = "import os, json\nfrom labelbot import store\nfrom . import x\nfrom .y import z\nimport domain_engrbot.model\n"
        self.assertEqual(rules(src), [])

    def test_sibling_py_is_local(self):
        self.assertEqual(rules("import cli\n", "labelbot/x.py"), [])


class WriteExtTest(unittest.TestCase):
    def test_flags_forbidden_ext(self):
        self.assertEqual(rules("open('a.csv', 'w')\n"), ["C1_WRITE_EXT_FORBIDDEN"])
        self.assertEqual(rules("open(os.path.join(d, 'out.XLSX'), mode='wb')\n"), ["C1_WRITE_EXT_FORBIDDEN"])
        self.assertEqual(rules("open(f'{d}/x.txt', 'a')\n"), ["C1_WRITE_EXT_FORBIDDEN"])

    def test_flags_joined_expr_and_path_methods(self):
        self.assertEqual(rules("open(Path('o') / 'a.csv', 'w')\n"), ["C1_WRITE_EXT_FORBIDDEN"])
        self.assertEqual(rules("open(d + '/a.txt', 'w')\n"), ["C1_WRITE_EXT_FORBIDDEN"])
        self.assertEqual(rules("Path('o/a.csv').write_text(s)\n"), ["C1_WRITE_EXT_FORBIDDEN"])
        self.assertEqual(rules("(Path('o') / 'a.docx').write_bytes(b)\n"), ["C1_WRITE_EXT_FORBIDDEN"])
        self.assertEqual(rules("open('a.csv', 'r+')\n"), ["C1_WRITE_EXT_FORBIDDEN"])

    def test_allowed_path_methods_ok(self):
        self.assertEqual(rules("Path('o/a.json').write_text(s)\nopen(Path('o') / 'a.md', 'w')\n"), [])
        self.assertEqual(rules("Path('o/a.csv').write_text(s)\n", "tests/test_a.py"), [])

    def test_allowed_and_read_ok(self):
        self.assertEqual(rules("open('a.jsonl', 'w')\nopen('a.csv', 'r')\nopen(p, 'w')\n"), [])

    def test_test_files_excluded(self):
        self.assertEqual(rules("open('a.csv', 'w')\n", "tests/test_a.py"), [])


class OpenOutsideIngestTest(unittest.TestCase):
    def test_flagged_outside_ingest(self):
        self.assertEqual(rules("open(p, 'rb')\n"), ["C1_OPEN_OUTSIDE_INGEST"])

    def test_ingest_and_tests_ok(self):
        self.assertEqual(rules("open(p, 'rb')\n", "labelbot/ingest.py"), [])
        self.assertEqual(rules("open(p, 'rb')\n", "domain_engrbot/tests/test_x.py"), [])

    def test_name_resolved_to_own_format_ok(self):
        src = "P = os.path.join(os.path.dirname(__file__), 'prompts', 'x.md')\nopen(P, 'rb')\n"
        self.assertEqual(rules(src), [])
        src = "def f():\n    q = 'a.json'\n    return open(q, 'rb')\n"
        self.assertEqual(rules(src), [])

    def test_name_unresolved_or_foreign_flagged(self):
        self.assertEqual(rules("P = get()\nopen(P, 'rb')\n"), ["C1_OPEN_OUTSIDE_INGEST"])
        self.assertEqual(rules("P = 'a.pptx'\nopen(P, 'rb')\n"), ["C1_OPEN_OUTSIDE_INGEST"])

    def test_own_format_ok(self):
        self.assertEqual(rules("open('a.b64', 'rb')\nopen(os.path.join(d, 'x.sqlite'), 'rb')\n"), [])


if __name__ == "__main__":
    unittest.main()
