"""QM1·QM2·QM4: 정규화기, 인용 매칭, L1·L2·L3(a) 단위 테스트와 엣지 케이스."""
import copy
import unittest

from labelbot import review as lb_review

from domain_engrbot import model, normalize, policy, textmatch
from domain_engrbot.checks import l1_schema, l2_taxonomy, l3a_span
from domain_engrbot import synthetic

TAX = model.TaxIndex(synthetic.taxonomy_snapshot())
SCHEMA = policy.validate_schema({})
POLICY = policy.validate_policy({})


def ev(q, **kw):
    d = {"quote": q, "unit_id": None, "start": None, "end": None}
    d.update(kw)
    return d


def na_axes():
    return {a["name"]: {"values": [model.NA], "status": "na", "evidence": ev(""), "confidence": 0.9}
            for a in TAX.active_axes()}


def record(**kw):
    r = {"record_id": "f:ppt/slides/slide2.xml", "file_id": "f", "labeler_run_id": "r", "chunk_type": "내용",
         "axes": na_axes(), "answers": {}, "extracted": [], "failures": [],
         "labeler": {"sheet_hashes": {"taxonomy": TAX.version}}, "human_reviewed": False, "duplicate_fields": []}
    r.update(kw)
    return r


def with_axis(r, name, values, quote="", status="value", conf=0.9):
    r["axes"][name] = {"values": values, "status": status, "evidence": ev(quote), "confidence": conf}
    return r


def codes_of(issues):
    return sorted(i["code"] for i in issues)


class NormalizerTest(unittest.TestCase):
    def test_examples(self):
        self.assertEqual(normalize.strip_ws("  M1  "), "M1")
        self.assertEqual(normalize.nfkc_ascii("Ｍ１"), "M1")
        self.assertEqual(normalize.enum_case("n/a", ["O", "X", "N/A"]), "N/A")
        self.assertEqual(normalize.enum_case("o", ["O", "X", "N/A"]), "O")
        self.assertEqual(normalize.taxonomy_case("short", "불량 모드", TAX), "Short")
        self.assertEqual(normalize.date_iso("2026.9.3"), "2026-09-03")
        self.assertEqual(normalize.date_iso("2026년 9월 3일"), "2026-09-03")
        self.assertEqual(normalize.date_iso("2026.9"), "2026-09")
        self.assertEqual(normalize.pattern_case("m 1", r"^(M|V)(\d{1,2}|x)$|^JHV$"), "M1")
        self.assertEqual(normalize.pattern_case("mx", r"^(M|V)(\d{1,2}|x)$|^JHV$"), "Mx")
        self.assertEqual(normalize.pattern_case("rdabcd.01", SCHEMA["formats"]["lot_id"]["pattern"]), "RDABCD.01")

    def test_must_not_fix(self):
        self.assertEqual(normalize.date_value("26/09/03", SCHEMA["formats"]["date"]["pattern"]), ("26/09/03", []))
        self.assertEqual(normalize.date_value("2026.2.30", SCHEMA["formats"]["date"]["pattern"]), ("2026.2.30", []))
        self.assertEqual(normalize.axis_value("구조/레이어", "Metal1", TAX), ("Metal1", []))
        self.assertEqual(normalize.axis_value("불량 모드", "Shrt", TAX), ("Shrt", []))

    def test_chain_records_rules(self):
        v, rules = normalize.axis_value("불량 모드", " ｓｈｏｒｔ ", TAX)
        self.assertEqual(v, "Short")
        self.assertEqual(rules, ["strip_ws", "nfkc_ascii", "taxonomy_case"])
        self.assertTrue(normalize.is_approved(normalize.fix_entry("f", "a", "b", rules), set(rules)))
        self.assertFalse(normalize.is_approved(normalize.fix_entry("f", "a", "b", rules), {"strip_ws"}))


class TextMatchTest(unittest.TestCase):
    TEXT = "제목\nM2 라인 간 단락이 Center 영역에서 확인됨\n항목 | 측정값\nRs | 12.3"

    def test_tiers(self):
        self.assertEqual(textmatch.match("M2 라인 간 단락이", self.TEXT), "exact")
        self.assertEqual(textmatch.match("m2  라인 간 단락이 center", self.TEXT), "normalized")
        self.assertEqual(textmatch.match("M2 라인 … Center 영역", self.TEXT), "ellipsis")
        self.assertEqual(textmatch.match("Ｍ２ 라인 간", self.TEXT), "normalized")
        self.assertEqual(textmatch.match("항목 측정값", self.TEXT), "normalized")  # 표 구분자는 공백으로 본다
        self.assertIsNone(textmatch.match("Center … M2 라인", self.TEXT))
        self.assertIsNone(textmatch.match("없는 문장", self.TEXT))

    def test_offset(self):
        i = self.TEXT.find("단락")
        self.assertIsNone(textmatch.check_offset(self.TEXT, i, i + 2, "단락"))
        self.assertEqual(textmatch.check_offset(self.TEXT, i + 1, i + 3, "단락"), "OFFSET_TEXT_MISMATCH")
        self.assertEqual(textmatch.check_offset(self.TEXT, 5, 5, ""), "OFFSET_EMPTY")
        self.assertEqual(textmatch.check_offset(self.TEXT, 0, 9999, "x"), "OFFSET_OUT_OF_RANGE")

    def test_parity_with_labelbot_quote_found(self):
        """구현은 따로, 결과는 같아야 한다(표 구분자가 없는 입력 집합)."""
        fx = synthetic.generate(seed=11, n_files=4)
        cases = []
        units = fx.bundle.units
        for r in fx.bundle.records:
            text = units[r["record_id"]]["text"]
            for a in r["axes"].values():
                q = a["evidence"]["quote"]
                if q:
                    cases.append((q, text))
                    cases.append((q.replace(" ", "  "), text))
                    cases.append((q[:6] + " … " + q[-6:], text))
                    cases.append((q + " 추가", text))
                    cases.append((q.replace("-", "–"), text))
        self.assertGreater(len(cases), 200)
        for q, text in cases:
            self.assertEqual(bool(textmatch.match(q, text)), lb_review.quote_found(q, [text]), q)


class L1Test(unittest.TestCase):
    def ev1(self, r):
        return l1_schema.evaluate(r, TAX, SCHEMA)

    def test_clean_record_no_issue(self):
        r = with_axis(record(), "불량 모드", ["Short"], "단락 불량이 Center 영역에서 확인됨")
        r["answers"] = {"Q-COM-001": {"answer": "O", "evidence": ev("재발 여부는 미확인"), "confidence": 0.8}}
        self.assertEqual(self.ev1(r)["issues"], [])

    def test_labeler_failed(self):
        r = record(chunk_type=None, axes={}, failures=[{"stage": "classify", "reason_code": "TIMEOUT"}])
        out = self.ev1(r)
        self.assertEqual(codes_of(out["issues"]), ["L1_LABELER_FAILED"])
        self.assertIn("*", out["broken"])
        r = record(failures=[{"stage": "label", "reason_code": "QUESTION_MISSING"}])
        self.assertEqual(codes_of(self.ev1(r)["issues"]), ["L1_LABELER_FAILED"])
        r = record(failures=[{"stage": "label", "reason_code": "UNMAPPED_QUESTION"}],
                   answers={"Q-COM-001": {"answer": "N/A", "evidence": ev(""), "confidence": 0.8}})
        self.assertEqual(self.ev1(r)["issues"], [])

    def test_required_missing(self):
        r = record()
        del r["axes"]["불량 모드"]
        self.assertEqual(codes_of(self.ev1(r)["issues"]), ["L1_REQUIRED_MISSING"])
        r = record(chunk_type="표지", axes={})
        self.assertEqual(self.ev1(r)["issues"], [])  # 내용이 아닌 chunk는 축이 없어도 된다
        self.assertEqual(codes_of(self.ev1(record(chunk_type=None))["issues"]), ["L1_REQUIRED_MISSING"])

    def test_inactive_axis_not_required(self):
        # 축 이름은 taxonomy.json에서 바뀔 수 있으므로 마지막 분류 축을 고른다.
        name = TAX.classification_axes()[-1]["name"]
        snap = copy.deepcopy(TAX.snapshot)
        for a in snap["axes"]:
            if a["name"] == name:
                a["active"] = False
        tax = model.TaxIndex(snap)
        r = record()
        del r["axes"][name]
        self.assertEqual(l1_schema.evaluate(r, tax, SCHEMA)["issues"], [])

    def test_type_and_enum(self):
        r = with_axis(record(), "불량 모드", "Short", "단락 불량")
        out = self.ev1(r)
        self.assertEqual(codes_of(out["issues"]), ["L1_TYPE_INVALID"])
        self.assertIn("axis:불량 모드", out["broken"])
        r = record(chunk_type="슬라이드")
        self.assertEqual(codes_of(self.ev1(r)["issues"]), ["L1_ENUM_INVALID"])
        r = record(answers={"Q-COM-001": {"answer": "Y", "evidence": ev("x"), "confidence": 0.8}})
        self.assertEqual(codes_of(self.ev1(r)["issues"]), ["L1_ENUM_INVALID"])
        r = record()
        r["axes"]["불량 모드"]["confidence"] = "high"
        self.assertEqual(codes_of(self.ev1(r)["issues"]), ["L1_TYPE_INVALID"])

    def test_confidence_range(self):
        r = with_axis(record(), "불량 모드", ["Short"], "단락 불량이 확인됨", conf=1.4)
        out = self.ev1(r)
        self.assertEqual([(i["code"], i["severity"]) for i in out["issues"]], [("L1_CONFIDENCE_RANGE", "major")])
        r = with_axis(record(), "불량 모드", ["Short"], "단락 불량이 확인됨", conf=None)
        self.assertEqual([(i["code"], i["severity"]) for i in self.ev1(r)["issues"]], [("L1_CONFIDENCE_RANGE", "minor")])

    def test_evidence_missing(self):
        r = with_axis(record(), "불량 모드", ["Short"], "")
        self.assertEqual(codes_of(self.ev1(r)["issues"]), ["L1_EVIDENCE_MISSING"])
        r = record(answers={"Q-COM-001": {"answer": "X", "evidence": ev(""), "confidence": 0.8}})
        self.assertEqual(codes_of(self.ev1(r)["issues"]), ["L1_EVIDENCE_MISSING"])
        r = record(answers={"Q-COM-001": {"answer": "N/A", "evidence": ev(""), "confidence": 0.8}})
        self.assertEqual(self.ev1(r)["issues"], [])

    def test_dates_and_patterns(self):
        r = record(extracted=[{"item": "date", "value": "2026.9.3", "evidence": {"quote": "2026.9.3 회의"}, "flag": ""}])
        out = self.ev1(r)
        self.assertEqual(codes_of(out["issues"]), ["L1_FORMAT_NORMALIZED"])
        self.assertEqual(out["record"]["extracted"][0]["value"], "2026-09-03")
        self.assertEqual(out["fixes"][0]["rule"], "date_iso")
        r = record(extracted=[{"item": "date", "value": "26/09/03", "evidence": {"quote": "26/09/03 회의"}, "flag": ""}])
        self.assertEqual(codes_of(self.ev1(r)["issues"]), ["L1_DATE_FORMAT"])
        for lot, want in (("RDABCD", []), ("RXABC.01", []), ("QABCD012.03", []), ("rdabcd.01", ["L1_FORMAT_NORMALIZED"]),
                          ("RAABCD", ["L1_LOT_ID_UNCOMMON"]), ("RAB", ["L1_PATTERN_MISMATCH"]),
                          ("QABCD112", ["L1_PATTERN_MISMATCH"])):
            r = record(extracted=[{"item": "lot_id", "value": lot, "evidence": {"quote": "lot " + lot}, "flag": ""}])
            self.assertEqual(codes_of(self.ev1(r)["issues"]), want, lot)
        r = with_axis(record(), "구조/레이어", ["Metal1"], "Metal1 배선층")
        self.assertEqual(codes_of(self.ev1(r)["issues"]), ["L1_PATTERN_MISMATCH"])

    def test_autofix_values(self):
        r = with_axis(record(), "불량 모드", [" short "], "단락 불량")
        r["chunk_type"] = " 내용"
        r["answers"] = {"Q-COM-001": {"answer": "o", "evidence": ev("재발 여부는 미확인"), "confidence": 0.8}}
        out = self.ev1(r)
        self.assertEqual(codes_of(out["issues"]), ["L1_FORMAT_NORMALIZED"] * 3)
        self.assertEqual(out["record"]["axes"]["불량 모드"]["values"], ["Short"])
        self.assertEqual(out["record"]["answers"]["Q-COM-001"]["answer"], "O")
        self.assertEqual(out["record"]["chunk_type"], "내용")
        self.assertEqual(r["axes"]["불량 모드"]["values"], [" short "])  # 원본은 그대로

    def test_duplicate_and_unknown(self):
        r = record(duplicate_fields=["axis:불량 모드"], extra=1,
                   answers={"Q-XXX-999": {"answer": "N/A", "evidence": ev(""), "confidence": 0.5}})
        self.assertEqual(codes_of(self.ev1(r)["issues"]), ["L1_DUPLICATE_FIELD", "L1_UNKNOWN_FIELD", "L1_UNKNOWN_FIELD"])


class L2Test(unittest.TestCase):
    def ev2(self, r):
        out = l1_schema.evaluate(r, TAX, SCHEMA)
        return l2_taxonomy.evaluate(out["record"], TAX, SCHEMA, POLICY, out["broken"])

    def test_clean(self):
        r = with_axis(record(), "불량 모드", ["EM"], "전자이동 불량")  # 하위값만
        r = with_axis(r, "결과", ["improved", "degraded"], "개선과 악화")  # 결과 축은 여러 값
        r = with_axis(r, "구조/레이어", ["M1"], "M1 배선층")
        self.assertEqual(self.ev2(r), [])
        r = with_axis(record(), "불량 모드", ["Reliability"], "신뢰성")  # 상위값만
        self.assertEqual(self.ev2(r), [])

    def test_not_in_taxonomy_and_axis_unknown(self):
        r = with_axis(record(), "불량 모드", ["Crack"], "crack")
        self.assertIn("L2_LABEL_NOT_IN_TAXONOMY", codes_of(self.ev2(r)))
        r = with_axis(record(), "없는 축", ["x"], "x")
        self.assertIn("L2_AXIS_UNKNOWN", codes_of(self.ev2(r)))

    def test_hierarchy(self):
        r = with_axis(record(), "불량 모드", ["Reliability", "EM"], "신뢰성 EM")
        self.assertEqual(codes_of(self.ev2(r)), ["L2_HIERARCHY_INCONSISTENT"])
        snap = copy.deepcopy(TAX.snapshot)
        for a in snap["axes"]:
            if a["name"] == "불량 모드":
                a["hierarchical"] = False
        tax = model.TaxIndex(snap)
        r = with_axis(record(), "불량 모드", ["EM"], "EM")
        self.assertEqual(codes_of(l2_taxonomy.evaluate(r, tax, SCHEMA, POLICY)), ["L2_HIERARCHY_INCONSISTENT"])

    def test_mutex(self):
        r = with_axis(record(), "불량 모드", ["Short", "unknown"], "단락")
        out = self.ev2(r)
        self.assertIn(("L2_MUTEX_VIOLATION", "critical"), [(i["code"], i["severity"]) for i in out])
        r = with_axis(record(), "의사결정 상태", ["adopted", "pending"], "채택 미결")
        r = with_axis(r, "불량 모드", ["Short"], "단락")
        self.assertEqual([(i["code"], i["severity"]) for i in self.ev2(r)], [("L2_MUTEX_VIOLATION", "critical")])
        pol = policy.validate_policy({"l2": {"mutex_groups": [{"axis": "결과", "values": ["improved", "neutral"]}]}})
        r = with_axis(record(), "결과", ["improved", "neutral"], "개선 차이없음")
        r = with_axis(r, "불량 모드", ["Short"], "단락")
        out = l2_taxonomy.evaluate(r, TAX, SCHEMA, pol)
        self.assertEqual([(i["code"], i["severity"]) for i in out], [("L2_MUTEX_VIOLATION", "major")])

    def test_status_mismatch(self):
        r = with_axis(record(), "불량 모드", ["unknown"], "", status="value")
        self.assertIn("L2_STATUS_MISMATCH", codes_of(self.ev2(r)))
        r = with_axis(record(), "불량 모드", ["Short"], "단락", status="na")
        self.assertIn("L2_STATUS_MISMATCH", codes_of(self.ev2(r)))

    def _unknown_record(self, n_unknown, n_na):
        r = record()
        cls = [a["name"] for a in TAX.classification_axes()]
        for i, name in enumerate(cls):
            if i < n_unknown:
                r["axes"][name] = {"values": ["unknown"], "status": "unknown", "evidence": ev(""), "confidence": 0.5}
            elif i < n_unknown + n_na:
                pass  # 해당 없음
            else:
                r["axes"][name] = {"values": [TAX.axes[name]["values"][0]["name"]], "status": "value",
                                   "evidence": ev("근거 문장 있음"), "confidence": 0.9}
        return r

    def test_unknown_overuse_boundary(self):
        # 분류 축 수는 taxonomy.json을 따른다. 기준(기본 0.5) 바로 위·아래 unknown 수로 경계를 본다.
        n_cls = len(TAX.classification_axes())
        self.assertGreaterEqual(n_cls, 4)
        half = (n_cls + 1) // 2  # unknown/n >= 0.5가 되는 가장 작은 수
        self.assertIn("L2_UNKNOWN_OVERUSE", codes_of(self.ev2(self._unknown_record(half, 0))))
        self.assertNotIn("L2_UNKNOWN_OVERUSE", codes_of(self.ev2(self._unknown_record(half - 1, 0))))
        # 해당 없음은 분모에서 빠진다: (half-1) / (n - na) >= 0.5가 되도록 na를 고른다.
        na = n_cls - 2 * (half - 1)
        self.assertIn("L2_UNKNOWN_OVERUSE", codes_of(self.ev2(self._unknown_record(half - 1, na))))
        pol = policy.validate_policy({"l2": {"unknown_ratio_major": half / n_cls + 0.01}})
        out = l1_schema.evaluate(self._unknown_record(half, 0), TAX, SCHEMA)
        self.assertNotIn("L2_UNKNOWN_OVERUSE", codes_of(l2_taxonomy.evaluate(out["record"], TAX, SCHEMA, pol)))
        self.assertNotIn("L2_UNKNOWN_OVERUSE", codes_of(self.ev2(self._unknown_record(0, 8))))  # 분모 0

    def test_ratio_050_flagged_049_not(self):
        """분류 축 100개짜리 taxonomy에서 unknown 50개(0.50)는 걸리고 49개(0.49)는 걸리지 않는다."""
        snap = {"version": "v", "reserved": {"na": model.NA, "unknown": model.UNKNOWN}, "questions": [], "synonyms": [],
                "axes": [{"name": "축%d" % i, "kind": "분류", "multi": False, "hierarchical": False, "active": True,
                          "values": [{"name": "값", "parent": None}]} for i in range(100)]}
        tax = model.TaxIndex(snap)

        def rec(n_unknown):
            axes = {}
            for i in range(100):
                if i < n_unknown:
                    axes["축%d" % i] = {"values": ["unknown"], "status": "unknown", "evidence": ev("")}
                else:
                    axes["축%d" % i] = {"values": ["값"], "status": "value", "evidence": ev("근거")}
            return {"chunk_type": "내용", "axes": axes}

        self.assertIn("L2_UNKNOWN_OVERUSE", codes_of(l2_taxonomy.evaluate(rec(50), tax, SCHEMA, POLICY)))
        self.assertNotIn("L2_UNKNOWN_OVERUSE", codes_of(l2_taxonomy.evaluate(rec(49), tax, SCHEMA, POLICY)))

    def test_all_na_and_stale(self):
        self.assertEqual(codes_of(self.ev2(record())), ["L2_ALL_NOT_APPLICABLE"])
        r = with_axis(record(), "불량 모드", ["Short"], "단락")
        r["labeler"]["sheet_hashes"]["taxonomy"] = "old"
        self.assertEqual(codes_of(self.ev2(r)), ["L2_TAXONOMY_STALE"])


class L3ATest(unittest.TestCase):
    UNIT = {"unit_id": "f:ppt/slides/slide2.xml", "file_id": "f", "seq": 2,
            "text": "주간 보고 2\n단락 불량이 Center 영역에서 확인됨\nHTOL 500h 이후 재발 여부는 미확인\n"
                    "2026.9.3 회의에서 일정 확정\n담당 김민수 책임이 후속 일정 관리",
            "text_canonical": "주간 보고 2\nShort 불량이 Center 영역에서 확인됨\nHTOL 500h 이후 재발 여부는 미확인\n"
                              "2026.9.3 회의에서 일정 확정\n담당 김민수 책임이 후속 일정 관리"}
    OTHER = {"unit_id": "f:ppt/slides/slide3.xml", "file_id": "f", "seq": 3,
             "text": "주간 보고 3\nVoid 현상이 단면 분석에서 관찰됨", "text_canonical": None}

    def ev3(self, r):
        return l3a_span.evaluate(r, self.UNIT, [self.UNIT, self.OTHER], POLICY)

    def test_found_in_text_and_canonical(self):
        r = with_axis(record(), "불량 모드", ["Short"], "단락 불량이 Center 영역에서 확인됨")
        self.assertEqual(self.ev3(r), [])
        r = with_axis(record(), "불량 모드", ["Short"], "Short 불량이 Center 영역에서 확인됨")  # 동의어 치환본
        self.assertEqual(self.ev3(r), [])

    def test_answer_quote_only_in_original(self):
        r = record(answers={"Q-COM-001": {"answer": "O", "evidence": ev("Short 불량이 Center 영역에서 확인됨"),
                                          "confidence": 0.8}})
        self.assertEqual(codes_of(self.ev3(r)), ["L3_SPAN_NOT_FOUND"])

    def test_wrong_unit_and_not_found(self):
        r = with_axis(record(), "물리 현상", ["Void"], "Void 현상이 단면 분석에서 관찰됨")
        out = self.ev3(r)
        self.assertEqual(codes_of(out), ["L3_SPAN_WRONG_UNIT"])
        self.assertEqual(out[0]["evidence"]["found_in_unit"], self.OTHER["unit_id"])
        self.assertEqual(out[0]["severity"], "critical")
        r = with_axis(record(), "물리 현상", ["Void"], "존재하지 않는 문장으로 근거를 대체함")
        self.assertEqual(codes_of(self.ev3(r)), ["L3_SPAN_NOT_FOUND"])
        r = with_axis(record(), "물리 현상", ["Void"], "주간 보고 3")  # 다른 슬라이드 제목에서 가져온 인용
        self.assertEqual(codes_of(self.ev3(r)), ["L3_SPAN_WRONG_UNIT"])

    def test_title_quote_passes(self):
        r = with_axis(record(), "불량 모드", ["Short"], "주간 보고 2")
        self.assertEqual(self.ev3(r), [])

    def test_offsets(self):
        text = self.UNIT["text"]
        q = "단락 불량이 Center 영역에서 확인됨"
        i = text.find(q)
        r = record()
        r["axes"]["불량 모드"] = {"values": ["Short"], "status": "value", "evidence": ev(q, start=i, end=i + len(q)),
                              "confidence": 0.9}
        self.assertEqual(self.ev3(r), [])
        r["axes"]["불량 모드"]["evidence"] = ev(q, start=i + 1, end=i + 1 + len(q))
        self.assertEqual(codes_of(self.ev3(r)), ["L3_SPAN_OFFSET_INVALID"])
        r["axes"]["불량 모드"]["evidence"] = ev(q, start=10, end=10)
        self.assertEqual(codes_of(self.ev3(r)), ["L3_SPAN_OFFSET_INVALID"])

    def test_short_and_long(self):
        r = with_axis(record(), "불량 모드", ["Short"], "단락")
        self.assertEqual([(i["code"], i["severity"]) for i in self.ev3(r)], [("L3_SPAN_TOO_SHORT", "minor")])
        long_unit = dict(self.UNIT, text="가" * 400, text_canonical=None)
        r = with_axis(record(), "불량 모드", ["Short"], "가" * 350)
        out = l3a_span.evaluate(r, long_unit, [long_unit], POLICY)
        self.assertEqual(codes_of(out), ["L3_SPAN_TOO_LONG"])

    def test_extract_in_quote(self):
        r = record(extracted=[{"item": "date", "value": "2026-09-03", "evidence": {"quote": "2026.9.3 회의에서 일정 확정"}},
                              {"item": "person", "value": "김민수", "evidence": {"quote": "담당 김민수 책임이 후속 일정 관리"}}])
        self.assertEqual(self.ev3(r), [])
        r["extracted"][0]["value"] = "2026-09-04"
        r["extracted"][1]["value"] = "이서연"
        self.assertEqual(codes_of(self.ev3(r)), ["L3_EXTRACT_NOT_IN_QUOTE", "L3_EXTRACT_NOT_IN_QUOTE"])

    def test_broken_fields_skipped(self):
        r = with_axis(record(), "불량 모드", ["Short"], "없는 인용 문장입니다")
        self.assertEqual(l3a_span.evaluate(r, self.UNIT, [self.UNIT], POLICY, {"axis:불량 모드"}), [])
        self.assertEqual(l3a_span.evaluate(r, self.UNIT, [self.UNIT], POLICY, {"*"}), [])


if __name__ == "__main__":
    unittest.main()
