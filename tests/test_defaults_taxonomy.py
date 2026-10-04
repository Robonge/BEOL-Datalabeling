"""커밋된 taxonomy/taxonomy.xlsx 회귀 테스트. xlsx가 기준이고 jsonl은 xlsx에서 만든 기대 행이다."""
import json
import os
import unittest

from labelbot import taxonomy, util, xlsx
from labelbot.ingest import read_input
from labelbot.synonyms import SynonymTable

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
XLSX_PATH = os.path.join(ROOT, "taxonomy", "taxonomy.xlsx")
ROWS_PATH = os.path.join(ROOT, "tests", "fixtures", "default_taxonomy_rows.jsonl")


def load_rows():
    with open(ROWS_PATH, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


class DefaultTaxonomyTest(unittest.TestCase):
    def setUp(self):
        self.data = read_input(XLSX_PATH, None, expect=".xlsx")

    def test_rows_match_jsonl(self):
        wb = xlsx.read_workbook(self.data)
        rows = []
        for name in wb.sheet_names:
            sheet, _ = wb.find(name)
            self.assertEqual((sheet.errors, sheet.warnings), ([], []))
            rows.extend({"sheet": name, "row": n, "cells": cells} for n, cells in sheet.iter_rows())
        self.assertEqual(rows, load_rows())

    def test_parses_without_errors(self):
        t = taxonomy.parse_bytes(self.data)
        self.assertEqual(len(t.axes), 10)
        self.assertEqual(t.warnings, [])
        self.assertEqual(sorted(t.sheet_hashes), sorted(taxonomy.HEADERS))
        self.assertEqual(t.sheet_hashes["files"], taxonomy.EMPTY_SHEET_HASH)
        self.assertTrue(t.synonyms)
        self.assertTrue(t.questions)

    def test_file_bytes_unchanged_after_parsing(self):
        before = util.sha256_bytes(self.data)
        taxonomy.parse_bytes(self.data)
        self.assertEqual(util.sha256_bytes(read_input(XLSX_PATH, None, expect=".xlsx")), before)

    def test_default_synonyms_have_no_short_ascii_keys(self):
        """허용 목록(JGV) 밖의 3자 이하 영문 키가 없다(PRD 6.2)."""
        t = taxonomy.parse_bytes(self.data)
        short = [s.row for s in t.synonyms if len(s.alias) <= 3 and s.alias.isascii() and s.alias != "JGV"]
        self.assertEqual(short, [])

    def test_default_synonym_normalization(self):
        table = SynonymTable(taxonomy.parse_bytes(self.data).synonyms)
        self.assertEqual(table.apply("단락")[0], "Short")
        self.assertEqual(table.apply("JGV")[0], "JHV")
        self.assertEqual(table.apply("Metal1")[0], "M1")
        self.assertEqual(table.apply("Via12 Metal12")[0], "Via12 Metal12")


if __name__ == "__main__":
    unittest.main()
