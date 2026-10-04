"""L0 파싱 충실도 단위 테스트(5.1절, QM3).

합성 pptx·docx는 pptx_writer가 메모리에서만 만든다. 파서 출력(ParsedUnit)은 fixturegen과 같은 방식으로 조립한다
(제목 + 본문 줄 + 표 행 'a | b' + 노트, 반복 바닥글 제외).
"""
import ast
import builtins
import hashlib
import os
import shutil
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

from qabot import engine, model, rawextract, runner
from qabot import policy as policy_mod
from qabot.adapters import bundle_files
from qabot.checks import l0_parse
from qabot.tests import fixturegen, pptx_writer

FOOTER = fixturegen.FOOTER
LINES = ["M2 배선층에서 저항 측정 진행", "CMP 공정 조건 재점검 진행", "Short 불량 발생 위치 분석",
         "다음 주 일정 재확인", "측정 장비 예약 현황 공유", "보고서 양식 변경 안내"]
TABLE = [["항목", "측정값"], ["Rs", "12.5"], ["Rc", "2.1"]]


def _pol(**l0):
    return policy_mod.validate_policy({"layers": ["L0"], "l0": l0} if l0 else {"layers": ["L0"]})


SCHEMA = policy_mod.validate_schema({})


def _unit_text(spec):
    lines = ([spec["title"]] if spec.get("title") else []) + list(spec.get("lines") or [])
    if spec.get("table"):
        lines += [" | ".join(r) for r in spec["table"]]
    if spec.get("notes"):
        lines += ["[노트]", spec["notes"]]
    return model.nfc("\n".join(lines))


def make_bundle(specs, ext=".pptx", data=None):
    """슬라이드 명세 → (Bundle, blobs, images). 파서 출력은 정상(결함 없음)으로 조립한다."""
    data = data if data is not None else pptx_writer.build_pptx(specs)
    fid = hashlib.sha256(data).hexdigest()
    blobs, images, units, records = {fid: data}, {}, {}, []
    sources = {fid: {"file_id": fid, "ext": ext, "status": "ok", "reason_code": None, "b64_ref": "b64/%s.b64" % fid}}
    if ext == ".pptx":
        img_slides = {}
        for spec in specs:
            for img in spec.get("images") or []:
                img_slides[hashlib.sha256(img).hexdigest()] = img_slides.get(hashlib.sha256(img).hexdigest(), 0) + 1
        for n, spec in enumerate(specs, 1):
            part = "ppt/slides/slide%d.xml" % n
            uid = "%s:%s" % (fid[:16], part)
            imgs = []
            for img in spec.get("images") or []:
                iid = hashlib.sha256(img).hexdigest()
                if len(img) < 2048 or img_slides[iid] > 1:
                    continue  # 파서처럼 작은 이미지와 반복 이미지는 뺀다
                rel = "images/%s.b64" % iid
                images[rel] = img
                imgs.append({"image_id": iid, "ext": "png", "size": len(img), "rel_file": rel})
            text = _unit_text(spec)
            units[uid] = {"unit_id": uid, "file_id": fid, "seq": n, "part_name": part, "title": spec.get("title") or "",
                          "text": text, "text_canonical": None, "text_hash": model.sha256_text(text),
                          "tables": [spec["table"]] if spec.get("table") else [], "notes": spec.get("notes") or "",
                          "charts": [], "images": imgs, "warnings": [], "dup_group": None}
            records.append({"record_id": uid, "file_id": fid, "labeler_run_id": "t", "chunk_type": "내용", "axes": {},
                            "answers": {}, "extracted": [], "failures": [], "duplicate_fields": [],
                            "labeler": {}, "human_reviewed": False})
    b = model.Bundle("t", sources, units, records, {"axes": []}, fixturegen.FixtureLoader(blobs, images))
    return b, blobs, images


def run_l0(bundle, pol=None):
    """L0 검사만 직접 돌린다. 반환: 이슈 목록(record 범위 이슈는 record_id를 단 그대로)."""
    pol = pol or _pol()
    ctx = engine.Ctx(bundle, pol, SCHEMA)
    check = l0_parse.ParseFidelityCheck()
    out = []
    for fid in sorted(bundle.sources):
        out += check.run(engine.FileTarget(bundle, fid), ctx)
    return out


def codes_of(issues, min_sev="info"):
    return sorted({i["code"] for i in issues if model.SEVERITY_RANK[i["severity"]] >= model.SEVERITY_RANK[min_sev]})


def find(issues, code):
    return [i for i in issues if i["code"] == code]


def content_specs(n=5, extra=None):
    specs = [{"title": "과제 보고", "lines": ["작성 부서 공정기술팀"], "footer": FOOTER}]
    for k in range(2, n + 1):
        s = {"title": "주간 보고 %d" % k, "lines": ["%s %d" % (l, k) for l in LINES], "footer": FOOTER}
        s.update((extra or {}).get(k, {}))
        specs.append(s)
    return specs


def uid_of(bundle, seq):
    return next(u["unit_id"] for u in bundle.units.values() if u["seq"] == seq)


def retext(unit, text):
    unit["text"] = text
    unit["text_hash"] = model.sha256_text(model.nfc(text).encode("utf-8", "surrogatepass").decode("utf-8", "replace"))


class CleanFixtureTest(unittest.TestCase):
    def test_clean_fixture_has_no_minor_or_higher(self):
        fx = fixturegen.generate(seed=7)
        issues = run_l0(fx.bundle)
        self.assertEqual(codes_of(issues, "minor"), [])
        res = runner.execute(fx.bundle, _pol(), SCHEMA, layers=["L0"])
        self.assertEqual({v["verdict"] for v in res.verdicts}, {"PASS"})
        self.assertEqual(res.file_issues, [])

    def test_repeated_footer_is_not_coverage_loss(self):
        b, _, _ = make_bundle(content_specs(6))
        self.assertEqual(find(run_l0(b), "L0_TEXT_COVERAGE_LOW"), [])
        # 파서가 바닥글을 지우지 않았어도 이슈가 아니다(파서 쪽 글자가 많은 것은 문제가 아니다)
        for u in b.units.values():
            retext(u, u["text"] + "\n" + FOOTER)
        self.assertEqual(codes_of(run_l0(b), "minor"), [])

    def test_notes_and_charts_only_on_parser_side(self):
        b, _, _ = make_bundle(content_specs(4, {3: {"notes": "발표자 메모 길게 적은 내용입니다"}}))
        u = b.units[uid_of(b, 3)]
        u["charts"] = [{"title": "차트", "series": ["A"], "categories": ["x"]}]
        retext(u, u["text"] + "\n[차트]\n제목: 차트")
        self.assertEqual(codes_of(run_l0(b), "minor"), [])


class MutationTest(unittest.TestCase):
    """하네스가 주입할 L0 뮤테이터 5종을 같은 방식으로 주입해 탐지를 확인한다. 주입하지 않은 레코드는 PASS여야 한다."""

    @classmethod
    def setUpClass(cls):
        cls.fx = fixturegen.generate(seed=7)
        cls.pol = _pol()

    def _run(self, mutate):
        b = self.fx.bundle.copy()
        rid, expect_file = mutate(b)
        res = runner.execute(b, self.pol, SCHEMA, layers=["L0"])
        return b, rid, expect_file, res

    def _pick(self, b, pred):
        for r in sorted(b.records, key=lambda r: r["record_id"]):
            if pred(b.units[r["record_id"]]):
                return r["record_id"]
        self.fail("대상 unit이 없다")

    def _assert(self, mutate, code, severity="major"):
        b, rid, file_scope, res = self._run(mutate)
        fid = rid.split(":")[0]
        for v in res.verdicts:
            hit = [i for i in v["issues"] if i["code"] == code]
            target = (v["file_id"][:16] == fid) if file_scope else (v["record_id"] == rid)
            if target:
                self.assertTrue(hit, (code, v["record_id"]))
                self.assertEqual(hit[0]["severity"], severity)
                self.assertEqual(v["verdict"], "REVIEW")
            else:
                self.assertEqual(v["verdict"], "PASS", (code, v["record_id"], v["issues"]))

    def test_drop_slide(self):
        def m(b):
            rid = sorted(r["record_id"] for r in b.records)[3]
            b.records = [r for r in b.records if r["record_id"] != rid]
            b.units.pop(rid)
            return rid, True

        self._assert(m, "L0_PAGE_COUNT_MISMATCH")

    def test_empty_text(self):
        def m(b):
            rid = self._pick(b, lambda u: len(u["text"]) >= 40)
            retext(b.units[rid], "")
            return rid, False

        self._assert(m, "L0_EMPTY_UNIT")

    def test_drop_table(self):
        def m(b):
            rid = self._pick(b, lambda u: u["tables"])
            b.units[rid]["tables"] = []
            return rid, False

        self._assert(m, "L0_TABLE_LOST")

    def test_garble(self):
        def m(b):
            rid = self._pick(b, lambda u: len(u["text"]) >= 40)
            chars = list(b.units[rid]["text"])
            for i in range(0, len(chars), 10):
                if not chars[i].isspace():
                    chars[i] = "�"
            retext(b.units[rid], "".join(chars))
            return rid, False

        self._assert(m, "L0_GARBLED_TEXT")

    def test_break_image_ref(self):
        def m(b):
            rid = self._pick(b, lambda u: u["images"])
            img = dict(b.units[rid]["images"][0])
            img["rel_file"] = "images/missing_%s.b64" % img["image_id"][:12]
            b.units[rid]["images"] = [img]
            return rid, False

        self._assert(m, "L0_IMAGE_REF_BROKEN")

    def test_garble_five_percent(self):
        b, _, _ = make_bundle(content_specs(3))
        rid = uid_of(b, 2)
        chars = list(b.units[rid]["text"])
        for i in range(0, len(chars), 20):
            chars[i] = "�"
        retext(b.units[rid], "".join(chars))
        hit = find(run_l0(b), "L0_GARBLED_TEXT")
        self.assertEqual([(i["record_id"], i["severity"]) for i in hit], [(rid, "major")])


class FileStateTest(unittest.TestCase):
    def _one(self, source_patch=None, data=None, ext=".pptx"):
        b, blobs, _ = make_bundle(content_specs(3), ext=ext if ext == ".pptx" else ".pptx")
        fid = next(iter(b.sources))
        b.sources[fid]["ext"] = ext
        b.sources[fid].update(source_patch or {})
        if data is not None:
            blobs[fid] = data
        return run_l0(b)

    def test_signature_encrypted(self):
        issues = self._one(data=pptx_writer.encrypted_bytes())
        self.assertEqual([(i["code"], i["evidence"]["reason_code"]) for i in issues],
                         [("L0_SIGNATURE_MISMATCH", "ENCRYPTED")])
        self.assertEqual(issues[0]["severity"], "critical")
        self.assertNotIn("record_id", issues[0])

    def test_signature_not_ooxml(self):
        issues = self._one(data=b"%PDF-1.7 not a zip")
        self.assertEqual([(i["code"], i["evidence"]["reason_code"]) for i in issues],
                         [("L0_SIGNATURE_MISMATCH", "NOT_OOXML")])

    def test_failed_source_mapping(self):
        enc = self._one({"status": "failed", "reason_code": "ENCRYPTED"})
        self.assertEqual(codes_of(enc), ["L0_SIGNATURE_MISMATCH"])
        legacy = self._one({"status": "failed", "reason_code": "OLE_LEGACY"}, ext=".ppt")
        self.assertEqual(codes_of(legacy), ["L0_SIGNATURE_MISMATCH"])
        parse = self._one({"status": "failed", "reason_code": "PARSE_ERROR"})
        self.assertEqual(codes_of(parse), ["L0_PARSE_FAILED"])
        self.assertEqual(parse[0]["severity"], "critical")
        pdf = self._one({"status": "failed", "reason_code": "UNSUPPORTED_FORMAT"}, ext=".pdf")
        self.assertEqual([(i["code"], i["severity"]) for i in pdf], [("L0_FORMAT_UNSUPPORTED", "info")])

    def test_parse_failed_without_records_goes_to_file_issues(self):
        b, _, _ = make_bundle(content_specs(3))
        fid = next(iter(b.sources))
        b.sources[fid].update({"status": "failed", "reason_code": "PARSE_ERROR"})
        b.units, b.records = {}, []
        res = runner.execute(b, _pol(), SCHEMA, layers=["L0"])
        self.assertEqual(res.verdicts, [])
        self.assertEqual([(i["file_id"], i["code"]) for i in res.file_issues], [(fid, "L0_PARSE_FAILED")])

    def test_format_unsupported(self):
        issues = self._one(ext=".txt")
        self.assertEqual([(i["code"], i["severity"]) for i in issues], [("L0_FORMAT_UNSUPPORTED", "info")])

    def test_source_unreadable(self):
        b, blobs, _ = make_bundle(content_specs(3))
        blobs.clear()
        issues = run_l0(b)
        self.assertEqual([(i["code"], i["evidence"]["reason_code"]) for i in issues],
                         [("L0_SOURCE_UNREADABLE", "B64_MISSING")])
        broken = self._one(data=b"PK\x03\x04" + b"\x00" * 64)
        self.assertEqual([(i["code"], i["evidence"]["reason_code"]) for i in broken],
                         [("L0_SOURCE_UNREADABLE", "RAW_ZIP_INVALID")])
        empty = self._one(data=b"")
        self.assertEqual(codes_of(empty), ["L0_SOURCE_UNREADABLE"])

    def test_source_unreadable_from_missing_b64(self):
        fx = fixturegen.generate(seed=7, n_files=1)
        d = tempfile.mkdtemp(prefix="qabot_b64_")
        try:
            bundle_files.save(fx.bundle, d, blobs={}, images=fx.images)
            b = bundle_files.load(d)
            issues = run_l0(b)
            self.assertEqual([(i["code"], i["evidence"]["reason_code"]) for i in issues],
                             [("L0_SOURCE_UNREADABLE", "B64_MISSING")])
        finally:
            shutil.rmtree(d, ignore_errors=True)


class PptxCodeTest(unittest.TestCase):
    def test_page_count(self):
        b, _, _ = make_bundle(content_specs(4, {3: {"hidden": True}}))
        self.assertEqual(find(run_l0(b), "L0_PAGE_COUNT_MISMATCH"), [], "숨김 슬라이드도 슬라이드 수에 넣는다")
        rid = uid_of(b, 4)
        b.units.pop(rid)
        b.records = [r for r in b.records if r["record_id"] != rid]
        hit = find(run_l0(b), "L0_PAGE_COUNT_MISMATCH")
        self.assertEqual(len(hit), 1)
        self.assertEqual((hit[0]["evidence"]["raw_slides"], hit[0]["evidence"]["units"],
                          hit[0]["evidence"]["hidden_slides"]), (4, 3, 1))
        self.assertNotIn("record_id", hit[0])

    def test_coverage_major_and_minor(self):
        b, _, _ = make_bundle(content_specs(4))
        major, minor = uid_of(b, 2), uid_of(b, 3)
        u = b.units[major]
        retext(u, "\n".join(u["text"].split("\n")[:2]))  # 제목과 한 줄만 남긴다
        u = b.units[minor]
        retext(u, "\n".join(u["text"].split("\n")[:-2]))  # 마지막 두 줄을 뺀다
        hit = {i["record_id"]: i for i in find(run_l0(b), "L0_TEXT_COVERAGE_LOW")}
        self.assertEqual(set(hit), {major, minor})
        self.assertEqual(hit[major]["severity"], "major")
        self.assertEqual(hit[minor]["severity"], "minor")
        self.assertLess(hit[major]["evidence"]["coverage"], 0.6)
        self.assertTrue(0.6 <= hit[minor]["evidence"]["coverage"] < 0.85)
        # 임계값은 정책을 따른다
        loose = run_l0(b, _pol(coverage_major=0.1, coverage_minor=0.2))
        self.assertEqual(find(loose, "L0_TEXT_COVERAGE_LOW"), [])

    def test_coverage_order_independent(self):
        b, _, _ = make_bundle(content_specs(3, {2: {"table": TABLE}}))
        u = b.units[uid_of(b, 2)]
        retext(u, "\n".join(reversed(u["text"].split("\n"))))
        u["tables"] = [[list(reversed(r)) for r in TABLE]]
        self.assertEqual(codes_of(run_l0(b), "minor"), [])

    def test_short_raw_slide_skips_coverage(self):
        specs = [{"title": "짧은 제목", "footer": FOOTER}, {"title": "다른 제목", "lines": ["한 줄"], "footer": FOOTER}]
        b, _, _ = make_bundle(specs)
        for u in b.units.values():
            retext(u, "전혀 다른 본문으로 바뀐 내용")
        self.assertEqual(find(run_l0(b), "L0_TEXT_COVERAGE_LOW"), [])

    def test_empty_unit_and_image_only(self):
        img = pptx_writer.fake_png("only")
        specs = content_specs(3) + [{"images": [img]}]
        b, _, _ = make_bundle(specs)
        e = uid_of(b, 2)
        retext(b.units[e], "")
        issues = run_l0(b)
        self.assertEqual([i["record_id"] for i in find(issues, "L0_EMPTY_UNIT")], [e])
        self.assertEqual(find(issues, "L0_TEXT_COVERAGE_LOW"), [], "빈 unit은 커버리지를 따로 내지 않는다")
        only = find(issues, "L0_IMAGE_ONLY_UNIT")
        self.assertEqual([(i["record_id"], i["severity"]) for i in only], [(uid_of(b, 4), "info")])
        # 원본도 짧으면 빈 unit이 아니다
        retext(b.units[uid_of(b, 1)], "")
        self.assertNotIn(uid_of(b, 1), [i["record_id"] for i in find(run_l0(b), "L0_EMPTY_UNIT")])

    def test_labelbot_markers_do_not_count_as_body(self):
        b, _, _ = make_bundle(content_specs(3))
        rid = uid_of(b, 2)
        retext(b.units[rid], "#\n[표]\n[노트]")
        self.assertEqual([i["record_id"] for i in find(run_l0(b), "L0_EMPTY_UNIT")], [rid])

    def test_empty_ratio(self):
        b, _, _ = make_bundle(content_specs(5))
        retext(b.units[uid_of(b, 2)], "")
        self.assertEqual(find(run_l0(b), "L0_EMPTY_RATIO_HIGH"), [])
        for k in (3, 4):
            retext(b.units[uid_of(b, k)], "")
        hit = find(run_l0(b), "L0_EMPTY_RATIO_HIGH")
        self.assertEqual(len(hit), 1)
        self.assertEqual((hit[0]["severity"], hit[0]["evidence"]["empty_units"]), ("major", 3))
        self.assertNotIn("record_id", hit[0])

    def test_tables(self):
        b, _, _ = make_bundle(content_specs(3, {2: {"table": TABLE}}))
        rid = uid_of(b, 2)
        self.assertEqual(codes_of(run_l0(b), "minor"), [])
        u = b.units[rid]
        u["tables"] = [[["항목", ""], ["", ""], ["Rc", ""]]]
        hit = find(run_l0(b), "L0_TABLE_CELLS_LOST")
        self.assertEqual([(i["record_id"], i["severity"], i["evidence"]["raw_cells"], i["evidence"]["parsed_cells"])
                          for i in hit], [(rid, "minor", 6, 2)])
        self.assertEqual(find(run_l0(b), "L0_TABLE_LOST"), [])
        # 파서가 좌표로 복원한 표 때문에 표가 더 많은 것은 이슈가 아니다
        u["tables"] = [TABLE, [["a", "b", "c"], ["1", "2", "3"]]]
        other = b.units[uid_of(b, 3)]
        other["tables"] = [[["x", "y", "z"], ["1", "2", "3"]]]
        self.assertEqual(codes_of(run_l0(b), "minor"), [])

    def test_empty_raw_table_is_not_counted(self):
        b, _, _ = make_bundle(content_specs(3, {2: {"table": [["", ""], ["", ""]]}}))
        u = b.units[uid_of(b, 2)]
        u["tables"] = []
        retext(u, "\n".join(l for l in u["text"].split("\n") if l.strip() != "|"))
        self.assertEqual(codes_of(run_l0(b), "minor"), [])

    def test_image_codes(self):
        big = pptx_writer.fake_png("big")
        rep = pptx_writer.fake_png("rep")
        small = pptx_writer.fake_png("small", size=500)
        specs = content_specs(4, {2: {"images": [big]}, 3: {"images": [rep, small]}, 4: {"images": [rep]}})
        b, _, images = make_bundle(specs)
        self.assertEqual(codes_of(run_l0(b), "minor"), [], "반복 이미지와 작은 이미지는 빠져도 이슈가 아니다")
        r2 = uid_of(b, 2)
        b.units[r2]["images"] = []
        hit = find(run_l0(b), "L0_IMAGE_DROPPED")
        self.assertEqual([(i["record_id"], i["severity"]) for i in hit], [(r2, "minor")])
        # 다른 슬라이드의 이미지가 연결되면 링크 불일치다(저장은 정상이라 참조 깨짐은 아니다)
        r3 = uid_of(b, 3)
        img = {"image_id": hashlib.sha256(big).hexdigest(), "ext": "png", "size": len(big),
               "rel_file": "images/%s.b64" % hashlib.sha256(big).hexdigest()}
        b.units[r3]["images"] = [img]
        issues = run_l0(b)
        self.assertEqual([i["record_id"] for i in find(issues, "L0_IMAGE_LINK_MISMATCH")], [r3])
        self.assertEqual(find(issues, "L0_IMAGE_REF_BROKEN"), [])

    def test_image_ref_broken_variants(self):
        big = pptx_writer.fake_png("ref")
        b, _, images = make_bundle(content_specs(3, {2: {"images": [big]}}))
        rid = uid_of(b, 2)
        good = b.units[rid]["images"][0]
        self.assertEqual(find(run_l0(b), "L0_IMAGE_REF_BROKEN"), [])
        cases = {"REF_MISSING": dict(good, rel_file=None), "B64_MISSING": dict(good, rel_file="images/none.b64")}
        for reason, img in cases.items():
            b.units[rid]["images"] = [img]
            hit = find(run_l0(b), "L0_IMAGE_REF_BROKEN")
            self.assertEqual([(i["record_id"], i["evidence"]["reason_code"]) for i in hit], [(rid, reason)])
        b.units[rid]["images"] = [good]
        images[good["rel_file"]] = b""
        self.assertEqual([i["evidence"]["reason_code"] for i in find(run_l0(b), "L0_IMAGE_REF_BROKEN")], ["EMPTY"])
        images[good["rel_file"]] = big + b"x"
        self.assertEqual([i["evidence"]["reason_code"] for i in find(run_l0(b), "L0_IMAGE_REF_BROKEN")],
                         ["HASH_MISMATCH"])
        self.assertEqual(find(run_l0(b, _pol(verify_image_hash=False)), "L0_IMAGE_REF_BROKEN"), [])

    def test_garbled_levels_and_classes(self):
        b, _, _ = make_bundle(content_specs(3))
        rid = uid_of(b, 2)
        base = b.units[rid]["text"]
        self.assertEqual(find(run_l0(b), "L0_GARBLED_TEXT"), [])
        for bad in ("�", "\x07", "", "\ud800", "\U000e0080"):
            n = max(1, int(len(base) * 0.01))
            retext(b.units[rid], bad * n + base[n:])
            hit = find(run_l0(b), "L0_GARBLED_TEXT")
            self.assertEqual([(i["record_id"], i["severity"]) for i in hit], [(rid, "minor")], repr(bad))
        self.assertEqual(l0_parse.garbled_ratio("가\t나\n다\r"), 0.0)

    def test_parser_warnings(self):
        b, _, _ = make_bundle(content_specs(3))
        rid = uid_of(b, 2)
        b.units[rid]["warnings"] = ["TRUNCATED", "GROUP_SHAPE", "SMARTART", "GROUP_SHAPE"]
        hit = {(i["evidence"]["warning"], i["severity"]) for i in find(run_l0(b), "L0_PARSER_WARNING")}
        self.assertEqual(hit, {("TRUNCATED", "minor"), ("GROUP_SHAPE", "info"), ("SMARTART", "minor")})
        pol = _pol(warning_severity={"GROUP_SHAPE": "minor", "TRUNCATED": "info"})
        hit = {(i["evidence"]["warning"], i["severity"]) for i in find(run_l0(b, pol), "L0_PARSER_WARNING")}
        self.assertIn(("GROUP_SHAPE", "minor"), hit)
        self.assertIn(("TRUNCATED", "info"), hit)

    def test_evidence_has_no_text(self):
        fx = fixturegen.generate(seed=3, n_files=2)
        b = fx.bundle.copy()
        for u in list(b.units.values())[:6]:
            retext(u, "�" * 30)
            u["images"] = [{"image_id": "0" * 64, "rel_file": "images/x.b64"}]
        for i in run_l0(b):
            for v in i["evidence"].values():
                self.assertTrue(isinstance(v, (int, float)) or (isinstance(v, str) and len(v) <= 40
                                                                and v.replace("_", "").replace(".", "").isalnum()),
                                (i["code"], v))


class DocxTest(unittest.TestCase):
    def _docx_bundle(self, unit_texts, tables=()):
        paras = [("개요", "Heading1"), ("M2 배선층에서 저항 측정 진행 결과를 정리한다", None),
                 ("결론", "Heading1"), ("CMP 공정 조건 재점검이 필요하다고 판단했다", None)]
        data = pptx_writer.build_docx(paras, tables=tables)
        b, _, _ = make_bundle([], ext=".docx", data=data)
        fid = next(iter(b.sources))
        for n, (text, tbls) in enumerate(unit_texts, 1):
            uid = "%s:sec%d" % (fid[:16], n)
            b.units[uid] = {"unit_id": uid, "file_id": fid, "seq": n, "part_name": "word/document.xml#%d" % n,
                            "title": "", "text": text, "text_canonical": None, "text_hash": model.sha256_text(text),
                            "tables": tbls, "notes": "", "charts": [], "images": [], "warnings": [], "dup_group": None}
        return b

    def test_docx_clean_and_no_page_count(self):
        table = [["항목", "값"], ["Rs", "12"]]
        b = self._docx_bundle([("# 개요\nM2 배선층에서 저항 측정 진행 결과를 정리한다", []),
                               ("# 결론\nCMP 공정 조건 재점검이 필요하다고 판단했다\n[표]\n항목 | 값\nRs | 12", [table])],
                              tables=[table])
        self.assertEqual(codes_of(run_l0(b), "minor"), [])
        self.assertEqual(find(run_l0(b), "L0_PAGE_COUNT_MISMATCH"), [])

    def test_docx_coverage_and_table_lost(self):
        table = [["항목", "값"], ["Rs", "12"]]
        b = self._docx_bundle([("# 개요", [])], tables=[table])
        issues = run_l0(b)
        self.assertIn("L0_TEXT_COVERAGE_LOW", codes_of(issues, "major"))
        self.assertIn("L0_TABLE_LOST", codes_of(issues, "major"))
        self.assertTrue(all("record_id" not in i for i in issues), "docx는 파일 단위로 계산한다")


class RawExtractTest(unittest.TestCase):
    def test_pptx_structure(self):
        img = pptx_writer.fake_png("raw")
        specs = content_specs(3, {2: {"table": TABLE, "images": [img], "notes": "노트 문장"}, 3: {"hidden": True}})
        raw = rawextract.extract(".pptx", pptx_writer.build_pptx(specs))
        self.assertEqual([s["part"] for s in raw["slides"]], ["ppt/slides/slide%d.xml" % n for n in (1, 2, 3)])
        s2 = raw["slides"][1]
        self.assertEqual((s2["tables"], s2["cells"]), (1, 6))
        self.assertEqual(s2["pictures"], [{"sha256": hashlib.sha256(img).hexdigest(), "size": len(img)}])
        self.assertTrue(raw["slides"][2]["hidden"])
        self.assertFalse(any("노트 문장" in l for sh in s2["shapes"] for l in sh), "노트는 원본 슬라이드 텍스트가 아니다")
        self.assertTrue(any(FOOTER in sh for sh in s2["shapes"]))

    def test_merged_cells_and_placeholders(self):
        a = "http://schemas.openxmlformats.org/drawingml/2006/main"
        tbl = ET.fromstring(
            '<a:tbl xmlns:a="%s"><a:tr><a:tc gridSpan="2"><a:txBody><a:p><a:r><a:t>머리</a:t></a:r></a:p></a:txBody></a:tc>'
            '<a:tc hMerge="1"><a:txBody><a:p><a:r><a:t>머리</a:t></a:r></a:p></a:txBody></a:tc></a:tr>'
            '<a:tr><a:tc rowSpan="2"><a:txBody><a:p><a:r><a:t>A</a:t></a:r></a:p></a:txBody></a:tc>'
            '<a:tc><a:txBody><a:p><a:r><a:t>1</a:t></a:r></a:p></a:txBody></a:tc></a:tr>'
            '<a:tr><a:tc vMerge="1"><a:txBody><a:p><a:r><a:t>A</a:t></a:r></a:p></a:txBody></a:tc>'
            '<a:tc><a:txBody><a:p/></a:txBody></a:tc></a:tr></a:tbl>' % a)
        lines, cells = rawextract._table(tbl)
        self.assertEqual(cells, 3)
        self.assertEqual(lines, ["머리", "A", "1"])
        p = ET.fromstring('<a:p xmlns:a="%s"><a:r><a:t>쪽 </a:t></a:r><a:fld type="slidenum"><a:t>7</a:t></a:fld>'
                          '<a:br/><a:r><a:t>둘째 줄</a:t></a:r></a:p>' % a)
        self.assertEqual(rawextract._para_lines(p), (["쪽", "둘째 줄"], ["7"]))

    def test_alternate_content_counted_once(self):
        ns = ('xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
              'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"')
        body = ET.fromstring('<a:txBody %s><mc:AlternateContent><mc:Choice><a:p><a:r><a:t>본문</a:t></a:r></a:p>'
                             '</mc:Choice><mc:Fallback><a:p><a:r><a:t>본문</a:t></a:r></a:p></mc:Fallback>'
                             '</mc:AlternateContent></a:txBody>' % ns)
        self.assertEqual(rawextract._body_lines(body), (["본문"], []))

    def test_docx_structure(self):
        data = pptx_writer.build_docx([("제목", "Heading1"), ("본문 문장", None)], tables=[[["a", "b"]], [["", ""]]])
        raw = rawextract.extract(".docx", data)
        self.assertEqual(raw["tables"], 1)
        self.assertIn("본문 문장", raw["lines"])

    def test_signature_and_registry(self):
        self.assertIsNone(rawextract.signature_reason(b"PK\x03\x04rest", ".pptx"))
        self.assertEqual(rawextract.signature_reason(pptx_writer.encrypted_bytes(), ".docx"), "ENCRYPTED")
        self.assertEqual(rawextract.signature_reason(b"abc", ".xlsx"), "NOT_OOXML")
        self.assertEqual(rawextract.signature_reason(b"abc", ".ppt"), "OLE_LEGACY")
        self.assertTrue(rawextract.supported(".PPTX"))
        self.assertFalse(rawextract.supported(".txt"))
        with self.assertRaises(rawextract.RawError):
            rawextract.extract(".txt", b"x")
        saved = dict(rawextract.EXTRACTORS)
        try:
            rawextract.register(".txt", lambda data: {"kind": "txt"})
            self.assertTrue(rawextract.supported(".txt"))
        finally:
            rawextract.EXTRACTORS.clear()
            rawextract.EXTRACTORS.update(saved)


class SafetyTest(unittest.TestCase):
    def test_no_labelbot_import(self):
        pkg = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for rel in ("rawextract.py", os.path.join("checks", "l0_parse.py")):
            with open(os.path.join(pkg, rel), encoding="utf-8") as f:
                tree = ast.parse(f.read())
            names = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
            names += [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
            self.assertFalse([m for m in names if m.split(".")[0] == "labelbot"], rel)

    def test_no_path_open_of_originals(self):
        """L0은 원본 경로를 열지 않는다. 열리는 파일은 작업 폴더의 .b64뿐이다."""
        fx = fixturegen.generate(seed=5, n_files=2)
        d = tempfile.mkdtemp(prefix="qabot_open_")
        try:
            bundle_files.save(fx.bundle, d, blobs=fx.blobs, images=fx.images)
            b = bundle_files.load(d)
            pol = _pol()
            from qabot import codes
            codes.catalog()
            opened = []
            real_open = builtins.open

            def spy(file, *a, **kw):
                opened.append(str(file))
                return real_open(file, *a, **kw)

            with mock.patch("builtins.open", spy):
                issues = run_l0(b, pol)
                # 메모리 loader는 파일을 하나도 열지 않는다
                n_before = len(opened)
                run_l0(fx.bundle, pol)
                self.assertEqual(len(opened), n_before)
            self.assertEqual(codes_of(issues, "minor"), [])
            self.assertTrue(opened)
            self.assertTrue(all(p.lower().endswith(".b64") for p in opened), opened)
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
