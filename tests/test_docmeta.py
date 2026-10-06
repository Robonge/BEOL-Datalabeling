"""파일 단위 문서 metadata(Lot ID·WF#·날짜·작성자) 추출 테스트."""
import unittest

from labelbot import docmeta


def unit(seq, text, title=""):
    return {"seq": seq, "title": title, "text": text}


class LotTest(unittest.TestCase):
    def test_strict(self):
        self.assertEqual(docmeta.find_lots("결과 QDKZS029.63 요약"), [("QDKZS029.63", "strict")])

    def test_similar(self):
        for lot in ("QXSZC.1", "RDSVK070.6C", "RXFKJ.6C", "QQZRY.6A", "QQLWB.65"):
            with self.subTest(lot=lot):
                self.assertEqual(docmeta.find_lots("Lot %s 평가" % lot), [(lot, "similar")])

    def test_lowercase_normalized(self):
        self.assertEqual(docmeta.find_lots("qdkzs029.63"), [("QDKZS029.63", "strict")])

    def test_no_false_positive(self):
        for text in ("M0.6 layer", "V1 via", "pH 10.6", "ABCD12.63", "RSBM.1X", "QDKZS029.633"):
            with self.subTest(text=text):
                self.assertEqual(docmeta.find_lots(text), [])

    def test_dedup_keeps_order(self):
        self.assertEqual(
            docmeta.find_lots("QQZRY.6A, QDKZS029.63, QQZRY.6A"),
            [("QQZRY.6A", "similar"), ("QDKZS029.63", "strict")],
        )


class WfTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(docmeta.parse_wf("1~5"), [1, 2, 3, 4, 5])
        self.assertEqual(docmeta.parse_wf("1,3,30"), [1, 3])
        self.assertEqual(docmeta.parse_wf("24-27"), [24, 25])
        self.assertEqual(docmeta.parse_wf("0"), [])

    def test_after_lot(self):
        self.assertEqual(docmeta.find_wf("QDKZS029.63_3"), [("QDKZS029.63", [3])])
        self.assertEqual(docmeta.find_wf("QDKZS029.63 #1~5"), [("QDKZS029.63", [1, 2, 3, 4, 5])])
        self.assertEqual(docmeta.find_wf("QQZRY.6A WF 7"), [("QQZRY.6A", [7])])

    def test_alone(self):
        self.assertEqual(docmeta.find_wf("split WF 7, W/F#9"), [(None, [7]), (None, [9])])

    def test_out_of_range_dropped(self):
        self.assertEqual(docmeta.find_wf("QDKZS029.63_30"), [])

    def test_base_lot_underscore(self):
        self.assertEqual(
            docmeta.find_base_wf("WAFER | POR (RXD3I_10) | RQMD6_19 | RSBM 공정"),
            [("RXD3I", "strict", [10]), ("RQMD6", "strict", [19])],
        )
        self.assertEqual(docmeta.find_base_wf("RQMD6.66 RSBM TaN"), [])


class AuthorDateTest(unittest.TestCase):
    def test_author_as_written(self):
        self.assertEqual(docmeta.find_author("자료작성: 홍길동 책임"), "홍길동 책임")
        self.assertEqual(docmeta.find_author("자료 작성 ： 홍길동/CMP기술팀\n다음 줄"), "홍길동/CMP기술팀")
        self.assertEqual(docmeta.find_author("Prepared by: Kim"), "Kim")
        self.assertEqual(docmeta.find_author("담당자: 이순신"), "이순신")

    def test_author_needs_colon(self):
        self.assertIsNone(docmeta.find_author("작성일 2026.07.27, 담당 공정 CMP"))

    def test_signature_last_line(self):
        self.assertEqual(docmeta.find_signature("- TEM 확인 예정\nLogicTD 홍길동\n"), "LogicTD 홍길동")
        self.assertEqual(docmeta.find_signature("본문\nLogicTD 홍길동\n[노트]\n발표 메모"), "LogicTD 홍길동")
        self.assertIsNone(docmeta.find_signature("LogicTD 홍길동\n결론: 적용 가능"))
        self.assertIsNone(docmeta.find_signature("Rc 개선 확인됨"))

    def test_date(self):
        self.assertEqual(docmeta.find_date("평가일 2026.07.27"), "2026-07-27")
        self.assertEqual(docmeta.find_date("2026년 7월 3일 회의"), "2026-07-03")
        self.assertIsNone(docmeta.find_date("26.07.27"))
        self.assertIsNone(docmeta.find_date("QDKZS029.63"))


class FileMetaTest(unittest.TestCase):
    FNAME = "260727_QXSZC.1 V0 CMP 평가.pptx"

    def test_body_first_and_first_slide_date(self):
        units = [
            unit(2, "결과 2026.08.01"),
            unit(1, "QDKZS029.63_3 split, WF 5\n자료작성: 홍길동 책임", title="표지 2026.07.27"),
        ]
        meta = docmeta.extract_file_meta(units, self.FNAME)
        self.assertEqual(meta["lots"], [{"lot": "QDKZS029.63", "match": "strict", "source": "slide", "wf": [3, 5]}])
        self.assertEqual((meta["date"], meta["date_source"]), ("2026-07-27", "slide"))
        self.assertEqual((meta["author"], meta["author_source"]), ("홍길동 책임", "slide"))

    def test_filename_fallback_ignores_filename_date(self):
        meta = docmeta.extract_file_meta([unit(1, "본문 #4")], self.FNAME)
        self.assertEqual(meta["lots"], [{"lot": "QXSZC.1", "match": "similar", "source": "filename", "wf": [4]}])
        self.assertIsNone(meta["date"])
        self.assertIsNone(meta["author"])

    def test_base_wf_joins_full_lot_and_keeps_por_lot(self):
        units = [unit(1, "RQMD6.66 평가"), unit(2, "WAFER | POR (RNG7TB_20) | RQMD6_19 | RQMD6_7")]
        meta = docmeta.extract_file_meta(units, "x.pptx")
        self.assertEqual(meta["lots"], [
            {"lot": "RQMD6.66", "match": "strict", "source": "slide", "wf": [7, 19]},
            {"lot": "RNG7TB", "match": "strict", "source": "slide", "wf": [20]},
        ])

    def test_keyword_author_beats_signature(self):
        units = [unit(1, "본문\nLogicTD 홍길동"), unit(2, "자료작성: 이순신 책임")]
        self.assertEqual(docmeta.extract_file_meta(units, "x.pptx")["author"], "이순신 책임")
        self.assertEqual(docmeta.extract_file_meta(units[:1], "x.pptx")["author"], "LogicTD 홍길동")

    def test_nothing_found(self):
        meta = docmeta.extract_file_meta([unit(1, "내용 없음")], "report.pptx")
        self.assertEqual(meta, {"lots": [], "date": None, "date_source": None, "author": None, "author_source": None})


if __name__ == "__main__":
    unittest.main()
