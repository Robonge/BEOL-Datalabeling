"""동의어 치환 규칙(PRD 6.2) 테스트."""
import unittest

from labelbot import taxonomy
from labelbot.synonyms import SynonymTable
from tests import xlsx_writer as xw

DEFAULT = [
    ("단락", "Short"),
    ("단선", "Open"),
    ("보이드", "Void"),
    ("전자이동", "EM"),
    ("일렉트로마이그레이션", "EM"),
    ("짝짝이", "CD imbalance"),
    ("asymmetry", "CD imbalance"),
    ("JGV", "JHV"),
    ("Metal1", "M1"),
    ("1st metal", "M1"),
    ("Via1", "V1"),
    ("디싱", "dishing"),
    ("브릿지", "metal bridge"),
]


class SynonymRulesTest(unittest.TestCase):
    def setUp(self):
        self.table = SynonymTable(DEFAULT)

    def apply(self, text, table=None):
        return (table or self.table).apply(text)

    def test_basic_replacements(self):
        self.assertEqual(self.apply("M2 단락 발생"), ("M2 Short 발생", [("단락", "Short")]))
        self.assertEqual(self.apply("JGV 저항")[0], "JHV 저항")
        self.assertEqual(self.apply("Metal1 CD")[0], "M1 CD")
        self.assertEqual(self.apply("Metal1의 CD")[0], "M1의 CD")

    def test_case_insensitive_and_nfkc(self):
        self.assertEqual(self.apply("METAL1, metal1, Ｍｅｔａｌ１"), ("M1, M1, M1", [("Metal1", "M1")]))
        self.assertEqual(self.apply("jgv")[0], "JHV")

    def test_output_is_nfkc(self):
        self.assertEqual(self.apply("ＣＤ ① 단락")[0], "CD 1 Short")

    def test_digit_boundary(self):
        self.assertEqual(self.apply("Via12 Metal12"), ("Via12 Metal12", []))
        self.assertEqual(self.apply("Via1, Via1/Metal1")[0], "V1, V1/M1")
        self.assertEqual(self.apply("21st metal")[0], "21st metal")
        self.assertEqual(self.apply("1st metal 층")[0], "M1 층")

    def test_ascii_word_boundary(self):
        self.assertEqual(self.apply("XJGV JGVs")[0], "XJGV JGVs")
        self.assertEqual(self.apply("(JGV)")[0], "(JHV)")

    def test_longest_key_first(self):
        table = SynonymTable([("metal", "Metallization"), ("1st metal", "M1")])
        self.assertEqual(self.apply("1st metal", table), ("M1", [("1st metal", "M1")]))

    def test_canonical_protected_bridge(self):
        table = SynonymTable([("bridge", "metal bridge")])
        self.assertEqual(self.apply("metal bridge 발생", table), ("metal bridge 발생", []))
        self.assertEqual(self.apply("bridge 발생", table), ("metal bridge 발생", [("bridge", "metal bridge")]))
        self.assertEqual(self.apply("Metal Bridge와 bridge", table)[0], "Metal Bridge와 metal bridge")

    def test_canonical_protected_bm_liner(self):
        table = SynonymTable([("BM", "BM/Liner")])
        self.assertEqual(self.apply("RSBM 공정", table), ("RSBM 공정", []))
        self.assertEqual(self.apply("BM/Liner 두께", table), ("BM/Liner 두께", []))
        self.assertEqual(self.apply("ALD BM 두께", table), ("ALD BM/Liner 두께", [("BM", "BM/Liner")]))
        self.assertEqual(self.apply("BMs", table)[0], "BMs")

    def test_single_pass_no_chain(self):
        table = SynonymTable([("A1x", "B2y"), ("B2y", "C3z")])
        # 한 번에 치환하고, 표준어로 나온 B2y는 다시 바꾸지 않는다
        self.assertEqual(self.apply("A1x", table)[0], "B2y")

    def test_matches_ordered_unique(self):
        text, matches = self.apply("단선 뒤 단락, 다시 단선과 보이드")
        self.assertEqual(text, "Open 뒤 Short, 다시 Open과 Void")
        self.assertEqual(matches, [("단선", "Open"), ("단락", "Short"), ("보이드", "Void")])
        self.assertEqual(self.table.match("단선 뒤 단락, 다시 단선과 보이드"), matches)

    def test_korean_inside_word_matches(self):
        self.assertEqual(self.apply("브릿지성 불량")[0], "metal bridge성 불량")

    def test_first_duplicate_wins(self):
        table = SynonymTable([("Metal1", "M1"), ("metal1", "M2")])
        self.assertEqual(self.apply("Metal1", table)[0], "M1")

    def test_no_match(self):
        self.assertEqual(self.apply("관련 없는 문장"), ("관련 없는 문장", []))
        self.assertEqual(self.apply(""), ("", []))


class SynonymSheetIntegrationTest(unittest.TestCase):
    def test_table_from_parsed_sheet(self):
        H = taxonomy.HEADERS
        data = xw.build([
            ("taxonomy", [H["taxonomy"], ["불량 모드", None, None, "Y", "Y", "N", "분류"], ["불량 모드", "Short"]]),
            ("questions", [H["questions"]]),
            ("synonyms", [H["synonyms"], ["단락", "Short", None], ["JGV", "JHV", None], ["Metal1", "M1", None],
                          ["metal1", "M9", None]]),
            ("rejected", [H["rejected"]]),
        ])
        t = taxonomy.parse_bytes(data)
        table = SynonymTable(t.synonyms)
        text, matches = table.apply("Metal1 단락, JGV")
        self.assertEqual(text, "M1 Short, JHV")
        self.assertEqual(matches, [("Metal1", "M1"), ("단락", "Short"), ("JGV", "JHV")])


if __name__ == "__main__":
    unittest.main()
