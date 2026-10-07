"""동의어 후보 엄밀 기준(candidates.synonym_reject_code, grouped의 봇 후보 거르기) 테스트."""
import unittest

from labelbot import candidates, store, taxonomy
from tests.test_taxonomy import base_sheets, build


def _tax():
    return taxonomy.parse_bytes(build(base_sheets()))


class RejectCodeTest(unittest.TestCase):
    def setUp(self):
        self.vocab = candidates.taxonomy_vocab(_tax())

    def check(self, expr, canon, code):
        self.assertEqual(candidates.synonym_reject_code(expr, canon, self.vocab), code, (expr, canon))

    def test_strict_synonym_passes(self):
        self.check("Metal1", "M1", None)       # 같은 대상의 다른 표기
        self.check("쇼트 불량", "Short", None)   # 한영 혼용

    def test_rejections(self):
        self.check("", "M1", "SYN_EMPTY")
        self.check("m 1", "M1", "SYN_SAME")
        self.check("EMX", "M1", "SYN_SHORT_ASCII")
        self.check("JGV", "M1", None)            # PRD 6.2 허용 목록
        self.check("메탈 라인", "배선", "SYN_CANONICAL_NOT_IN_TAXONOMY")
        self.check("M1 trench", "M1", "SYN_NARROWER")   # 더 좁은 개념
        self.check("Reliability 불량", "Reliability", "SYN_NARROWER")

    def test_vocab_none_skips_taxonomy_check(self):
        self.assertIsNone(candidates.synonym_reject_code("메탈 라인", "배선", None))


class GroupedFilterTest(unittest.TestCase):
    def setUp(self):
        self.con = store.connect(":memory:")
        self.tax = _tax()

    def add(self, content, chunk, source="bot", kind="synonym"):
        self.con.execute("INSERT INTO candidates(run_id, kind, content, axis, parent, evidence, chunk_id, source) "
                         "VALUES(?,?,?,?,?,?,?,?)", ("R1", kind, content, "", "", "", chunk, source))

    def contents(self):
        return sorted(g["content"] for g in candidates.grouped(self.con, self.tax, "R1") if g["kind"] == "synonym")

    def test_bot_candidates_need_strict_rule_and_two_chunks(self):
        for c in ("c1", "c2"):
            self.add("메탈원|M1", c)          # 통과(2회)
            self.add("M1 trench|M1", c)       # 좁은 개념
            self.add("메탈 라인|배선", c)        # 표준어가 분류 체계에 없음
        self.add("메탈1|M1", "c1")             # 1회뿐
        for c in ("c1", "c2"):                # 같은 표현에 표준어 둘 → 둘 다 뺀다
            self.add("비아원|V1", c)
            self.add("비아원|M1", c)
        self.assertEqual(self.contents(), ["메탈원|M1"])

    def test_review_registered_kept(self):
        self.add("메탈 라인|배선", "c1", source="review")
        self.assertEqual(self.contents(), ["메탈 라인|배선"])


if __name__ == "__main__":
    unittest.main()
