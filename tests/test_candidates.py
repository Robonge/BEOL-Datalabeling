"""후보 붙여넣기 행(candidates.paste_row): 엑셀 수식 주입 차단. 모든 값은 가짜다."""
import unittest

from labelbot import candidates


class PasteRowTest(unittest.TestCase):
    def test_new_value_formula_cells_quoted(self):
        for ch in ("=", "+", "-", "@"):
            row = candidates.paste_row({"kind": "new_value", "content": "%s축|%s값" % (ch, ch), "parent": ch + "상위",
                                        "source": "bot"})
            cells = row.split("\t")
            self.assertEqual(len(cells), 11)
            self.assertEqual(cells[:3], ["'%s축" % ch, "'%s값" % ch, "'%s상위" % ch])
            self.assertEqual(cells[3:], [""] * 8)

    def test_synonym_and_other_kinds(self):
        row = candidates.paste_row({"kind": "synonym", "content": "=HYPERLINK(\"x\")|@정식", "source": "review"})
        self.assertEqual(row.split("\t"), ["'=HYPERLINK(\"x\")", "'@정식", "검수 등록"])
        self.assertEqual(candidates.paste_row({"kind": "question", "content": "-질문", "source": "bot"}), "'-질문")

    def test_plain_values_unchanged(self):
        row = candidates.paste_row({"kind": "new_value", "content": "축|값-1=2", "parent": None, "source": "bot"})
        self.assertEqual(row, "\t".join(["축", "값-1=2"] + [""] * 9))
        row = candidates.paste_row({"kind": "synonym", "content": "별칭 -1|정식", "source": "bot"})
        self.assertEqual(row, "별칭 -1\t정식\t후보")


if __name__ == "__main__":
    unittest.main()
