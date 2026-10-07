"""커밋된 taxonomy/taxonomy.json 회귀 테스트. json이 기준이고 jsonl은 json에서 만든 기대 행이다
(tests/tools/dump_taxonomy_fixture.py가 만든다)."""
import json
import os
import unittest

from labelbot import taxonomy, util
from labelbot.ingest import read_input

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JSON_PATH = os.path.join(ROOT, "taxonomy", "taxonomy.json")
ROWS_PATH = os.path.join(ROOT, "tests", "fixtures", "default_taxonomy_rows.jsonl")


def load_rows():
    with open(ROWS_PATH, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def doc_rows(doc):
    """doc → 시트별 [머리글 행(1행)] + 데이터 행(행 번호, 뒤쪽 빈 칸을 뺀 정의 열 칸). 빈 행은 뺀다."""
    rows = []
    for name in list(taxonomy.HEADERS) + ["rejected"]:
        header = taxonomy.REJECTED_HEADER if name == "rejected" else taxonomy.HEADERS[name]
        rows.append({"sheet": name, "row": 1, "cells": list(header)})
        for n, cells in taxonomy.sheet_rows(doc, name) or []:
            while cells and cells[-1] == "":
                cells = cells[:-1]
            rows.append({"sheet": name, "row": n, "cells": cells})
    return rows


def axis_count_from_rows(rows):
    """taxonomy 시트에서 축 열은 있고 값 열이 빈 행이 축 정의 행이다(머리글 행 제외)."""
    cells = [(r["cells"] + ["", ""])[:2] for r in rows if r["sheet"] == "taxonomy" and r["row"] > 1]
    # 같은 축의 정의 행이 내용까지 같으면 파서가 하나로 합치므로 축 이름 수를 센다.
    return len({axis.strip() for axis, value in cells if axis.strip() and not value.strip()})


class DefaultTaxonomyTest(unittest.TestCase):
    def setUp(self):
        self.data = read_input(JSON_PATH, None)

    def test_rows_match_jsonl(self):
        self.assertEqual(doc_rows(taxonomy.decode_doc(self.data)), load_rows())

    def test_parses_without_errors(self):
        t = taxonomy.parse_bytes(self.data)
        self.assertEqual(len(t.axes), axis_count_from_rows(load_rows()))
        self.assertEqual(t.warnings, [])
        self.assertEqual(sorted(t.sheet_hashes), sorted(taxonomy.HEADERS))
        self.assertTrue(t.questions)

    def test_file_bytes_unchanged_after_parsing(self):
        before = util.sha256_bytes(self.data)
        taxonomy.parse_bytes(self.data)
        self.assertEqual(util.sha256_bytes(read_input(JSON_PATH, None)), before)

    def test_default_synonyms_have_no_short_ascii_keys(self):
        """허용 목록(JGV) 밖의 3자 이하 영문 키가 없다(PRD 6.2)."""
        t = taxonomy.parse_bytes(self.data)
        short = [s.row for s in t.synonyms if len(s.alias) <= 3 and s.alias.isascii() and s.alias != "JGV"]
        self.assertEqual(short, [])


if __name__ == "__main__":
    unittest.main()
