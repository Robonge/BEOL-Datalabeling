"""taxonomy.json 파싱·검증·저장 테스트와 예전 taxonomy.xlsx 1회 변환(xlsx_to_doc) 테스트.
JSON 픽스처는 시트 행 목록(첫 행 머리글)을 행 객체로 바꾼 bytes이고, xlsx 픽스처는 tests/xlsx_writer가 메모리에서 만든 bytes다."""
import json
import os
import tempfile
import unittest

from labelbot import ingest, taxonomy, util, xlsx
from tests import xlsx_writer as xw
from tests.xlsx_writer import Err, FormulaNoCache, FormulaStr, Inline, Runs

H = taxonomy.HEADERS
REJ = taxonomy.REJECTED_HEADER[:4]   # 예전 rejected 시트 머리글(출처 열 없음)


def tax_row(axis, value=None, parent=None, multi=None, hier=None, dup=None, kind=None,
            definition=None, include=None, exclude=None, use=None):
    return [axis, value, parent, multi, hier, dup, kind, definition, include, exclude, use]


def axis_row(axis, multi="Y", hier="N", dup="N", kind="분류", definition="정의"):
    return tax_row(axis, None, None, multi, hier, dup, kind, definition)


def base_sheets():
    """유효한 최소 taxonomy 시트 구성(시트마다 첫 행은 머리글). 테스트마다 고쳐 쓴다."""
    return {
        "taxonomy": [
            H["taxonomy"],
            axis_row("구조/레이어"),
            tax_row("구조/레이어", "M1", definition="금속층"),
            tax_row("구조/레이어", "V1"),
            axis_row("불량 모드", hier="Y"),
            tax_row("불량 모드", "Short"),
            tax_row("불량 모드", "Reliability"),
            tax_row("불량 모드", "EM", "Reliability"),
            axis_row("제품·세대"),
            axis_row("의사결정 상태", multi="N", kind="상태"),
            tax_row("의사결정 상태", "adopted"),
        ],
        "questions": [H["questions"], ["Q-COM-001", "위험이 있는가.", "공통", 1], ["Q-FM-001", "단락인가.", "불량 모드=Short", 2]],
        "synonyms": [H["synonyms"], ["단락", "Short", "더미"], ["Metal1", "M1", None]],
        "rejected": [REJ],
    }


ORDER = ("taxonomy", "questions", "synonyms", "rejected", "files", "queries")


def _text(v):
    """xlsx 읽기와 같은 문자열(None → "", 정수 값 float → "2")."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def to_doc(sheets):
    """시트 행 목록 dict → taxonomy.json doc. 머리글 행은 빼고 행 객체로 바꾼다. 빈 행도 자리를 지킨다."""
    doc = {"version": 1}
    for name, rows in sheets.items():
        if name not in H and name != "rejected":
            continue
        header = taxonomy.REJECTED_HEADER if name == "rejected" else H[name]
        doc[name] = [dict(zip(header, [_text(c) for c in (r or [])] + [""] * (len(header) - len(r or []))))
                     for r in rows[1:]]
    return doc


def build(sheets):
    """taxonomy.json bytes."""
    return json.dumps(to_doc(sheets), ensure_ascii=False).encode("utf-8")


def build_xlsx(sheets, **kw):
    specs = []
    for name in ORDER:
        if name in sheets:
            v = sheets[name]
            specs.append(v if isinstance(v, dict) else (name, v))
    for name, v in sheets.items():
        if name not in ORDER:
            specs.append(v if isinstance(v, dict) else (name, v))
    return xw.build(specs, **kw)


def parse(sheets, xlsx_path=False, **kw):
    """JSON으로 파싱한다. xlsx_path나 xlsx 옵션(kw)을 주면 예전 xlsx를 변환(xlsx_to_doc)한 뒤 파싱한다."""
    if not (xlsx_path or kw):
        return taxonomy.parse_bytes(build(sheets))
    doc, errors, warnings = taxonomy.xlsx_to_doc(build_xlsx(sheets, **kw))
    if errors:
        raise taxonomy.TaxonomyError(errors, warnings)
    t = taxonomy.parse_doc(doc)
    t.warnings = list(warnings) + t.warnings
    return t


class Helpers(unittest.TestCase):
    def assertRejected(self, sheets, code, sheet, row, forbidden=(), **kw):
        with self.assertRaises(taxonomy.TaxonomyError) as cm:
            parse(sheets, **kw)
        err = cm.exception
        hits = [i for i in err.issues if i.code == code]
        self.assertTrue(hits, "expected %s in %r" % (code, err.issues))
        self.assertEqual((hits[0].sheet, hits[0].row), (sheet, row))
        msg = str(err)
        self.assertIn("%s 시트" % sheet, msg)
        if row:
            self.assertIn("%d행" % row, msg)
        for word in forbidden:
            self.assertNotIn(word, msg)
        return err


class ValidTaxonomyTest(Helpers):
    def test_parses_model(self):
        t = parse(base_sheets())
        self.assertEqual([a.name for a in t.axes], ["구조/레이어", "불량 모드", "제품·세대", "의사결정 상태"])
        layer = t.axis("구조/레이어")
        self.assertEqual((layer.kind, layer.multi, layer.hierarchical, layer.dup_alert_exclude), ("분류", True, False, False))
        self.assertEqual([v.name for v in layer.values], ["M1", "V1"])
        self.assertEqual(layer.values[0].definition, "금속층")
        self.assertEqual(layer.values[0].row, 3)
        fm = t.axis("불량 모드")
        self.assertTrue(fm.hierarchical)
        self.assertEqual(fm.value("EM").parent, "Reliability")
        decision = t.axis("의사결정 상태")
        self.assertEqual((decision.kind, decision.multi), ("상태", False))
        self.assertEqual(t.questions[0].target, "공통")
        self.assertEqual(t.questions[0].priority, 1)
        self.assertEqual(t.questions[1].target, ("불량 모드", "Short"))
        self.assertEqual([(s.alias, s.canonical) for s in t.synonyms], [("단락", "Short"), ("Metal1", "M1")])
        self.assertEqual(t.rejected, [])
        self.assertEqual(t.warnings, [])

    def test_axis_without_values_is_inactive(self):
        t = parse(base_sheets())
        self.assertFalse(t.axis("제품·세대").active)
        self.assertNotIn("제품·세대", [a.name for a in t.active_axes()])
        self.assertEqual(len(t.active_axes()), 3)

    def test_disabled_values_are_nonexistent(self):
        s = base_sheets()
        s["taxonomy"][3][10] = "N"  # V1 사용 여부=N
        s["taxonomy"].append(tax_row("구조/레이어", "m1", use="N"))  # 꺼진 값은 중복 판정에서도 빠진다
        s["taxonomy"].append(tax_row("구조/레이어", "unknown", use="N"))
        t = parse(s)
        self.assertEqual([v.name for v in t.axis("구조/레이어").values], ["M1"])

    def test_axis_with_only_disabled_values_is_inactive(self):
        s = base_sheets()
        s["taxonomy"][10][10] = "N"
        self.assertFalse(parse(s).axis("의사결정 상태").active)

    def test_value_added_in_sheet_appears_without_code_change(self):
        s = base_sheets()
        s["taxonomy"].append(tax_row("구조/레이어", "M9"))
        self.assertIn("M9", [v.name for v in parse(s).axis("구조/레이어").values])


class FiveErrorsTest(Helpers):
    def test_duplicate_value_rows_are_merged(self):
        # 같은 값 행이 여럿이면 오류가 아니라 정의·예를 행 순서대로 모두 모은다(라벨러 LLM이 함께 참고)
        s = base_sheets()
        first = tax_row("구조/레이어", "Fx", definition="첫 정의", include="포함 A")
        s["taxonomy"].append(first)
        s["taxonomy"].append(tax_row("구조/레이어", " fx ", definition="둘째 정의", include="포함 A", exclude="제외 B"))
        s["taxonomy"].append(tax_row("구조/레이어", "FX", definition="  첫   정의 "))  # 같은 문장은 한 번만
        t = parse(s)
        vals = [v for v in t.axis("구조/레이어").values if v.name == "Fx"]
        self.assertEqual(len(vals), 1)
        v = vals[0]
        self.assertEqual((v.definition, v.include, v.exclude), ("첫 정의\n둘째 정의", "포함 A", "제외 B"))
        self.assertEqual(v.row, 12)
        self.assertEqual(t.warnings, [], "같은 값 여러 행은 정상 입력이라 경고도 내지 않는다")

    def test_duplicate_value_with_other_parent_is_rejected(self):
        s = base_sheets()
        s["taxonomy"].append(tax_row("불량 모드", "em", "Short"))   # 7행 EM의 상위값은 Reliability
        self.assertRejected(s, "DUPLICATE_VALUE_PARENT_CONFLICT", "taxonomy", 12, forbidden=["Short"])

    def test_duplicate_value_same_or_blank_parent_is_fine(self):
        s = base_sheets()
        s["taxonomy"].append(tax_row("불량 모드", "EM", "reliability", definition="전자 이동"))
        s["taxonomy"].append(tax_row("불량 모드", "EM", definition="EM 수명"))
        v = parse(s).axis("불량 모드").value("EM")
        self.assertEqual((v.parent, v.definition), ("Reliability", "전자 이동\nEM 수명"))

    def test_duplicate_axis_rows_are_merged(self):
        s = base_sheets()
        s["taxonomy"].append(tax_row("구조/레이어", definition="둘째 축 정의", include="축 포함"))   # 속성 칸 비움
        s["taxonomy"].append(axis_row("구조/레이어", definition="셋째 축 정의"))                     # 같은 속성
        t = parse(s)
        ax = t.axis("구조/레이어")
        self.assertEqual((ax.definition, ax.include), ("정의\n둘째 축 정의\n셋째 축 정의", "축 포함"))
        self.assertEqual((ax.multi, ax.kind, ax.row), (True, "분류", 2))
        self.assertEqual(t.warnings, [])

    def test_duplicate_axis_with_other_attrs_is_rejected(self):
        s = base_sheets()
        s["taxonomy"].append(axis_row("구조/레이어", multi="N", definition="다른 속성"))
        self.assertRejected(s, "DUPLICATE_AXIS_ATTR_CONFLICT", "taxonomy", 12, forbidden=["다른 속성"])

    def test_duplicate_disabled_row_is_ignored(self):
        s = base_sheets()
        s["taxonomy"].append(tax_row("구조/레이어", "m1", definition="꺼진 정의", use="N"))
        t = parse(s)
        self.assertNotIn("꺼진 정의", t.axis("구조/레이어").value("M1").definition or "")

    def test_same_value_in_other_axis_is_fine(self):
        s = base_sheets()
        s["taxonomy"].append(tax_row("불량 모드", "M1"))
        parse(s)

    def test_parent_not_found(self):
        s = base_sheets()
        s["taxonomy"].append(tax_row("불량 모드", "TDDB", "Reliabilty"))
        self.assertRejected(s, "PARENT_NOT_FOUND", "taxonomy", 12, forbidden=["Reliabilty", "TDDB"])

    def test_parent_in_other_axis(self):
        s = base_sheets()
        s["taxonomy"].append(tax_row("불량 모드", "Open", "M1"))
        self.assertRejected(s, "PARENT_NOT_FOUND", "taxonomy", 12)

    def test_value_without_axis_definition(self):
        s = base_sheets()
        s["taxonomy"].append(tax_row("공정 모듈", "Etch"))
        self.assertRejected(s, "AXIS_NOT_DEFINED", "taxonomy", 12, forbidden=["공정 모듈", "Etch"])

    def test_axis_attribute_on_value_row(self):
        for col in (3, 4, 5, 6):
            s = base_sheets()
            s["taxonomy"][2][col] = "Y" if col < 6 else "분류"
            self.assertRejected(s, "AXIS_ATTR_ON_VALUE", "taxonomy", 3)

    def test_synonym_without_canonical(self):
        s = base_sheets()
        s["synonyms"].append(["비아원", None, "메모"])
        self.assertRejected(s, "SYNONYM_NO_CANONICAL", "synonyms", 4, forbidden=["비아원"])


class AxisDefinitionTest(Helpers):
    def test_axis_attributes_required_and_y_n(self):
        s = base_sheets()
        s["taxonomy"][1][3] = None
        self.assertRejected(s, "YN_INVALID", "taxonomy", 2)
        s = base_sheets()
        s["taxonomy"][1][4] = "예"
        self.assertRejected(s, "YN_INVALID", "taxonomy", 2)

    def test_axis_kind(self):
        s = base_sheets()
        s["taxonomy"][1][6] = "기타"
        self.assertRejected(s, "AXIS_KIND_INVALID", "taxonomy", 2)

    def test_use_flag_must_be_y_n(self):
        s = base_sheets()
        s["taxonomy"][2][10] = "X"
        self.assertRejected(s, "YN_INVALID", "taxonomy", 3)


class ReservedWordTest(Helpers):
    def test_reserved_variants_rejected(self):
        for word in ("해당 없음", "해당없음", "unknown", "Unknown", "N/A", "NA", "n / a", "ＵＮＫＮＯＷＮ"):
            s = base_sheets()
            s["taxonomy"].append(tax_row("구조/레이어", word))
            err = self.assertRejected(s, "RESERVED_VALUE", "taxonomy", 12)
            # 메시지는 고정 문구이며 셀에 적힌 표기를 옮기지 않는다
            self.assertEqual({i.message for i in err.issues}, {"예약어(해당 없음, unknown 및 변형)는 값으로 쓸 수 없다"})


class SheetStructureTest(Helpers):
    def test_missing_required_sheet(self):
        for name in H:
            s = base_sheets()
            del s[name]
            err = self.assertRejected(s, "SHEET_MISSING", name, None)
            self.assertIn(" | ".join(H[name]), str(err))

    def test_rejected_list_is_optional(self):
        s = base_sheets()
        del s["rejected"]
        self.assertEqual(parse(s).rejected, [])

    def test_rejected_kinds_and_key(self):
        s = base_sheets()
        s["rejected"] = [REJ] + [[k, "x", "", ""] for k in taxonomy.REJECTED_KINDS]
        self.assertEqual(len(parse(s).rejected), len(taxonomy.REJECTED_KINDS))
        s["rejected"] = [REJ, ["모름", "x", "", ""]]
        self.assertRejected(s, "REJECTED_KIND_INVALID", "rejected", 2)
        self.assertEqual(taxonomy.rejected_key(" 값 ", "물리 현상 | Line 단면적"), ("값", "물리현상|line단면적"))

    def test_only_three_sheets_hashed(self):
        self.assertEqual(sorted(parse(base_sheets()).sheet_hashes), sorted(H))

    def test_unknown_keys_warn(self):
        doc = to_doc(base_sheets())
        doc["synonyms"][0]["담당자"] = "홍길동"
        t = taxonomy.parse_doc(doc)
        warn = [w for w in t.warnings if w.code == "EXTRA_COLUMNS"]
        self.assertEqual([(w.sheet, w.row) for w in warn], [("synonyms", 2)])
        self.assertNotIn("홍길동", warn[0].message)

    def test_non_text_cell_rejected(self):
        doc = to_doc(base_sheets())
        doc["questions"][0]["우선순위"] = 1
        with self.assertRaises(taxonomy.TaxonomyError) as cm:
            taxonomy.parse_doc(doc)
        self.assertEqual([(i.sheet, i.row, i.code) for i in cm.exception.issues],
                         [("questions", 2, "TAXONOMY_JSON_INVALID")])

    def test_not_json(self):
        for data in (b"not json", b"[1, 2]"):
            with self.assertRaises(taxonomy.TaxonomyError) as cm:
                taxonomy.parse_bytes(data)
            self.assertEqual(cm.exception.issues[0].code, "TAXONOMY_JSON_INVALID")

    def test_empty_rows_keep_row_numbers(self):
        s = base_sheets()
        s["synonyms"].insert(2, [None, None, None])
        t = parse(s)
        self.assertEqual([x.row for x in t.synonyms], [2, 4])
        self.assertEqual(t.sheet_hashes, parse(base_sheets()).sheet_hashes)


class MigrateSheetStructureTest(Helpers):
    """예전 taxonomy.xlsx 변환(xlsx_to_doc)의 시트 구조 검사."""

    def test_header_mismatch(self):
        s = base_sheets()
        s["synonyms"][0] = ["동의어", "표준 어", "메모"]
        err = self.assertRejected(s, "HEADER_MISMATCH", "synonyms", 1, xlsx_path=True)
        self.assertIn("동의어 | 표준어 | 메모", str(err))

    def test_header_column_order(self):
        s = base_sheets()
        s["questions"][0] = ["질문 ID", "적용 대상", "문장", "우선순위"]
        self.assertRejected(s, "HEADER_MISMATCH", "questions", 1, xlsx_path=True)

    def test_files_queries_sheets_are_dropped(self):
        s = base_sheets()
        s["files"] = [["파일 ID", "파일명", "제외", "맥락 메모"], ["a" * 64, "a.pptx", "Y", "메모"]]
        s["queries"] = [["조회 ID", "문장", "기대 정답", "채택"], ["QRY-0123abcd", "질문", None, "Y"]]
        doc, errors, _w = taxonomy.xlsx_to_doc(build_xlsx(s))
        self.assertEqual(errors, [])
        self.assertEqual(sorted(doc), sorted(["version", "taxonomy", "questions", "synonyms", "rejected"]))

    def test_extra_right_columns_ignored_with_warning(self):
        s = base_sheets()
        s["synonyms"][0] = H["synonyms"] + ["담당자"]
        s["synonyms"][1] = ["단락", "Short", "더미", "홍길동"]
        t = parse(s, xlsx_path=True)
        self.assertEqual(t.synonyms[0].memo, "더미")
        warn = [w for w in t.warnings if w.code == "EXTRA_COLUMNS"]
        self.assertEqual([(w.sheet, w.row) for w in warn], [("synonyms", 1)])
        self.assertNotIn("홍길동", warn[0].message)

    def test_sheet_name_case_mismatch_warns(self):
        s = base_sheets()
        specs = [("Taxonomy", s["taxonomy"])] + [(n, s[n]) for n in ("questions", "synonyms", "rejected")]
        doc, errors, warnings = taxonomy.xlsx_to_doc(xw.build(specs))
        self.assertEqual(errors, [])
        self.assertEqual(len(taxonomy.parse_doc(doc).axes), 4)
        self.assertIn(("taxonomy", "SHEET_NAME_CASE"), [(w.sheet, w.code) for w in warnings])

    def test_not_a_zip(self):
        doc, errors, _w = taxonomy.xlsx_to_doc(b"not a zip")
        self.assertIsNone(doc)
        self.assertEqual(errors[0].code, "NOT_XLSX")


class SynonymSheetTest(Helpers):
    def test_duplicate_synonym_warns_and_keeps_first(self):
        s = base_sheets()
        s["synonyms"].append(["metal1", "M2", None])
        t = parse(s)
        self.assertEqual([(x.alias, x.canonical) for x in t.synonyms], [("단락", "Short"), ("Metal1", "M1")])
        warn = [w for w in t.warnings if w.code == "DUPLICATE_SYNONYM"]
        self.assertEqual([(w.sheet, w.row) for w in warn], [("synonyms", 4)])
        text = xlsx.format_issue(warn[0])
        self.assertIn("synonyms 시트", text)
        self.assertIn("4행", text)
        for word in ("metal1", "Metal1", "M2", "M1"):
            self.assertNotIn(word, text)

    def test_synonym_without_alias(self):
        s = base_sheets()
        s["synonyms"].append([None, "Short", None])
        self.assertRejected(s, "SYNONYM_NO_ALIAS", "synonyms", 4)


class QuestionsTest(Helpers):
    def test_target_must_exist(self):
        for target in ("불량 모드=Open", "없는 축=Short", "Short", "", "공통 "):
            s = base_sheets()
            s["questions"].append(["Q-X", "문장", target or None, 1])
            if target == "공통 ":
                parse(s)  # 앞뒤 공백은 무시한다
                continue
            self.assertRejected(s, "QUESTION_TARGET_INVALID", "questions", 4)

    def test_target_disabled_value_invalid(self):
        s = base_sheets()
        s["taxonomy"][5][10] = "N"  # Short 끔
        self.assertRejected(s, "QUESTION_TARGET_INVALID", "questions", 3)

    def test_priority_int(self):
        s = base_sheets()
        s["questions"][1][3] = "높음"
        self.assertRejected(s, "QUESTION_PRIORITY_INVALID", "questions", 2)
        s = base_sheets()
        s["questions"][1][3] = 2.0
        self.assertEqual(parse(s).questions[0].priority, 2)

    def test_duplicate_question_id(self):
        s = base_sheets()
        s["questions"].append(["Q-COM-001", "다른 문장", "공통", 3])
        self.assertRejected(s, "QUESTION_ID_DUPLICATE", "questions", 4)


class SheetHashTest(Helpers):
    def test_json_hash_equals_xlsx_hash(self):
        # 변환 전후 시트 해시가 같아야 taxonomy-diff·L2 stale·axis-update가 변환을 '바뀜'으로 보지 않는다
        s = base_sheets()
        h_json = parse(s).sheet_hashes
        for kw in ({}, {"shared": False, "pad_empty": True}, {"strict": True}):
            self.assertEqual(parse(s, xlsx_path=True, **kw).sheet_hashes, h_json, kw)

    def test_hash_ignores_right_columns_in_xlsx(self):
        s2 = base_sheets()
        for name in ("taxonomy", "synonyms"):
            s2[name] = [row + [None] * (len(H[name]) - len(row)) + ["추가"] for row in s2[name]]
        self.assertEqual(parse(s2, xlsx_path=True).sheet_hashes, parse(base_sheets()).sheet_hashes)

    def test_hash_changes_with_content_including_use_flag(self):
        h1 = parse(base_sheets()).sheet_hashes
        s = base_sheets()
        s["taxonomy"][3][10] = "N"
        h2 = parse(s).sheet_hashes
        self.assertNotEqual(h1["taxonomy"], h2["taxonomy"])
        self.assertEqual(h1["synonyms"], h2["synonyms"])

    def test_hash_uses_raw_strings_before_nfkc(self):
        s = base_sheets()
        s2 = base_sheets()
        s2["synonyms"][2][0] = "Ｍｅｔａｌ１"  # NFKC 후에는 Metal1과 같다
        self.assertNotEqual(parse(s).sheet_hashes["synonyms"], parse(s2).sheet_hashes["synonyms"])

    def test_hash_after_escape_unescape(self):
        s = base_sheets()
        s["synonyms"][2][2] = "a\nb"
        s2 = base_sheets()
        s2["synonyms"][2][2] = "a_x000A_b"
        self.assertEqual(parse(s).sheet_hashes["synonyms"], parse(s2, xlsx_path=True).sheet_hashes["synonyms"])


class XlsxReaderTest(Helpers):
    """R2: 셀 위치와 값."""

    def read(self, rows, **kw):
        wb = xlsx.read_workbook(xw.build([("S", rows)], **kw))
        sheet, _ = wb.find("S")
        return sheet

    def test_runs_phonetic_inline_str_bool(self):
        sheet = self.read([
            [Runs("Metal", "1 ", "단락", phonetic="ダンラク"), Inline("인라인"), FormulaStr("수식 결과"), True, False],
        ])
        self.assertEqual(sheet.row(1), ["Metal1 단락", "인라인", "수식 결과", "TRUE", "FALSE"])
        self.assertEqual(sheet.errors, [])

    def test_missing_cells_and_rows_keep_position(self):
        sheet = self.read([["a", None, "c"], None, None, [None, None, None, "d"]])
        self.assertEqual(sheet.row(1), ["a", "", "c"])
        self.assertEqual(sheet.row(2), [])
        self.assertEqual(sheet.row(4), ["", "", "", "d"])
        self.assertEqual(sheet.cell(4, 3), "d")
        self.assertEqual(sorted(sheet.rows), [1, 4])

    def test_escapes(self):
        sheet = self.read([["a_x000D_b", "_x005F_x0041_", "x_x0041_y", Inline("t_x000A_u")]])
        self.assertEqual(sheet.row(1), ["a\rb", "_x0041_", "xAy", "t\nu"])

    def test_numbers(self):
        sheet = self.read([[3, 3.0, 2.5, 45292.0]])
        self.assertEqual(sheet.row(1), ["3", "3", "2.5", "45292"])
        self.assertEqual(sheet.numeric, {(1, 0), (1, 1), (1, 2), (1, 3)})

    def test_strict_namespace(self):
        for shared in (True, False):
            sheet = self.read([["a", None, Runs("b", "c")], [1, Inline("d")]], strict=True, shared=shared)
            self.assertEqual(sheet.row(1), ["a", "", "bc"])
            self.assertEqual(sheet.row(2), ["1", "d"])

    def test_strict_taxonomy_parses(self):
        t = parse(base_sheets(), strict=True)
        self.assertEqual(len(t.axes), 4)
        self.assertEqual(t.sheet_hashes, parse(base_sheets()).sheet_hashes)

    def test_error_cell(self):
        s = base_sheets()
        s["taxonomy"][2][7] = Err("#REF!")
        err = self.assertRejected(s, "CELL_ERROR", "taxonomy", 3, xlsx_path=True)
        self.assertNotIn("#REF!", str(err))

    def test_r3_formula_without_cached_value(self):
        s = base_sheets()
        s["synonyms"][1][2] = FormulaNoCache()
        err = self.assertRejected(s, "FORMULA_NO_CACHE", "synonyms", 2, xlsx_path=True)
        self.assertIn("수식 결과 없음, Excel에서 저장 후 다시 실행", str(err))

    def test_r4_hidden_rows_warn_and_are_read(self):
        s = base_sheets()
        s["synonyms"] = {"name": "synonyms", "rows": s["synonyms"], "hidden_rows": [3]}
        t = parse(s, xlsx_path=True)
        self.assertIn("Metal1", [x.alias for x in t.synonyms])
        warn = [w for w in t.warnings if w.code == "HIDDEN_ROWS"]
        self.assertEqual([(w.sheet, w.row) for w in warn], [("synonyms", 3)])
        self.assertEqual(warn[0].message, "숨김 행도 읽는다. 제외는 사용 여부=N")

    def test_r4_autofilter_warns(self):
        s = base_sheets()
        s["taxonomy"] = {"name": "taxonomy", "rows": s["taxonomy"], "autofilter": "A1:K11"}
        t = parse(s, xlsx_path=True)
        self.assertIn(("taxonomy", "숨김 행도 읽는다. 제외는 사용 여부=N"), [(w.sheet, w.message) for w in t.warnings])

    def test_r5_merge_cells_rejected(self):
        s = base_sheets()
        s["taxonomy"] = {"name": "taxonomy", "rows": s["taxonomy"], "merge": ["A2:A4"]}
        err = self.assertRejected(s, "MERGED_CELLS", "taxonomy", 2, xlsx_path=True)
        self.assertIn("A2:A4", str(err))

    def test_errors_in_unrelated_sheet_ignored(self):
        s = base_sheets()
        s["메모"] = {"name": "메모", "rows": [["x"]], "merge": ["A1:B1"]}
        parse(s, xlsx_path=True)

    def test_r7_numeric_cells_warn(self):
        s = base_sheets()
        s["taxonomy"].append(tax_row("구조/레이어", 12.0))
        s["synonyms"].append([1, "M1", None])
        s["synonyms"].append(["일번", 2, None])
        t = parse(s, xlsx_path=True)
        self.assertIn("12", [v.name for v in t.axis("구조/레이어").values])
        warn = [(w.sheet, w.row) for w in t.warnings if w.code == "NUMERIC_CELL"]
        self.assertEqual(warn, [("taxonomy", 12), ("synonyms", 4), ("synonyms", 5)])

    def test_r7_rejected_date_uses_date1904(self):
        s = base_sheets()
        s["rejected"] = [REJ, ["값", "물리 현상|erosion", 45292, "중복"], ["동의어", "a|b", "2024-02-01", None]]
        t = parse(s, xlsx_path=True)
        self.assertEqual(t.rejected[0].date, "2024-01-01")
        self.assertEqual(t.rejected[0].content, "물리 현상|erosion")
        self.assertEqual(t.rejected[1].date, "2024-02-01")
        s["rejected"][1][2] = 45292 - 1462
        self.assertEqual(parse(s, date1904=True).rejected[0].date, "2024-01-01")

    def test_rejected_kind(self):
        s = base_sheets()
        s["rejected"] = [REJ, ["축", "a|b", None, None]]
        self.assertRejected(s, "REJECTED_KIND_INVALID", "rejected", 2)

    def test_serial_to_date_before_leap_bug(self):
        self.assertEqual(xlsx.serial_to_date("1"), "1900-01-01")
        self.assertEqual(xlsx.serial_to_date("61"), "1900-03-01")
        self.assertIsNone(xlsx.serial_to_date("abc"))


class ReadInputTest(unittest.TestCase):
    """R1: DRM이 풀리지 않은 파일과 xlsx가 아닌 파일은 read_input이 사유 코드로 거부한다."""

    def check(self, data, reason):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "input.b64")  # 확장자와 무관하게 expect로 판정한다(office 확장자는 쓰지 않는다)
            with open(p, "wb") as f:
                f.write(data)
            with self.assertRaises(ingest.InputError) as cm:
                ingest.read_input(p, None, expect=".xlsx")
            self.assertEqual(cm.exception.reason_code, reason)
            self.assertEqual(str(cm.exception), reason)
            self.assertEqual(os.listdir(d), ["input.b64"])

    def test_encrypted(self):
        self.check(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 64, "ENCRYPTED")

    def test_not_ooxml(self):
        self.check(b"axis,value\n", "NOT_OOXML")

    def test_valid_bytes_pass(self):
        data = build_xlsx(base_sheets())
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "input.b64")
            with open(p, "wb") as f:
                f.write(data)
            self.assertEqual(ingest.read_input(p, None, expect=".xlsx"), data)


if __name__ == "__main__":
    unittest.main()
