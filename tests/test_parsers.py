"""M1 파서 테스트: pptx·docx 파싱, chunk 텍스트 구성(PRD 7.1), probe.

더미 파일은 labelbot.ingest.read_input(path, None)으로만 읽고, 파일명이 아니라 sha256으로 찾는다.
합성 파일은 메모리(BytesIO)에서만 만들고 디스크에 쓰지 않는다(CLAUDE.md).
"""
import copy
import io
import json
import os
import re
import unittest
import xml.etree.ElementTree as ET
import zipfile

from labelbot import chunker, ooxml, probe, textnorm, util
from labelbot.docx_parser import parse_docx
from labelbot.ingest import read_input
from labelbot.pptx_parser import parse_pptx
from labelbot.workspace import DEFAULT_CONFIG

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DUMMY_DIR = os.path.join(ROOT, "dummy pptx files")
HASHES = os.path.join(ROOT, "tests", "gold", "dummy_hashes.jsonl")
SAMPLE1, SAMPLE2, NEAR_DUP = "1b275ae9efc9", "f073be9c9ade", "c3860dd2e378"
DISCLAIMER = "본 자료의 모든 데이터는 내부 테스트용 더미"

_DATA = {}


def setUpModule():
    with open(HASHES, encoding="utf-8") as f:
        ids = [json.loads(line)["file_id"] for line in f if line.strip()]
    wanted = {}
    for prefix in (SAMPLE1, SAMPLE2, NEAR_DUP):
        full = [i for i in ids if i.startswith(prefix)]
        assert len(full) == 1, prefix
        wanted[full[0]] = prefix
    for fn in sorted(os.listdir(DUMMY_DIR)):
        if not fn.lower().endswith(".pptx"):
            continue
        data = read_input(os.path.join(DUMMY_DIR, fn), None)
        prefix = wanted.get(util.sha256_bytes(data))
        if prefix:
            _DATA[prefix] = data
    missing = set(wanted.values()) - set(_DATA)
    assert not missing, "dummy samples not found: %s" % sorted(missing)


def _cfg(**limits):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["limits"].update(limits)
    return cfg


_PARSED = {}


def parsed(prefix):
    if prefix not in _PARSED:
        _PARSED[prefix] = chunker.parse_document(".pptx", _DATA[prefix], DEFAULT_CONFIG)
    return _PARSED[prefix]


def _section(text, header):
    """'[차트]' 같은 구간 머리 다음부터 빈 줄 전까지의 줄들."""
    out, inside = [], False
    for line in text.split("\n"):
        if line == header:
            inside = True
            continue
        if inside:
            if not line:
                break
            out.append(line)
    return out


# ---------------------------------------------------------------- 합성 pptx·docx (메모리 전용)

NS_DECL = (
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
    'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
)
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
RT = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"


def _txbox(sid, x, y, cx, cy, text, sz=1400, ph=None):
    nvpr = '<p:nvPr><p:ph type="%s"/></p:nvPr>' % ph if ph else "<p:nvPr/>"
    paras = "".join('<a:p><a:r><a:rPr sz="%d"/><a:t>%s</a:t></a:r></a:p>' % (sz, t) for t in text.split("\n"))
    return (
        '<p:sp><p:nvSpPr><p:cNvPr id="%d" name="t%d"/><p:cNvSpPr txBox="1"/>%s</p:nvSpPr>'
        '<p:spPr><a:xfrm><a:off x="%d" y="%d"/><a:ext cx="%d" cy="%d"/></a:xfrm></p:spPr>'
        "<p:txBody><a:bodyPr/>%s</p:txBody></p:sp>" % (sid, sid, nvpr, x, y, cx, cy, paras)
    )


def _slide(shapes, show=True):
    return (
        '<p:sld %s%s><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        "<p:grpSpPr/>%s</p:spTree></p:cSld></p:sld>" % (NS_DECL, "" if show else ' show="0"', "".join(shapes))
    )


def _build_pptx(slides, order=None):
    """slides: 슬라이드 XML 목록(slide1.xml, slide2.xml, ...). order: sldIdLst에 넣을 슬라이드 번호 순서."""
    order = order or list(range(1, len(slides) + 1))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("_rels/.rels", '<Relationships xmlns="%s"><Relationship Id="rId1" Type="%sofficeDocument" '
                   'Target="ppt/presentation.xml"/></Relationships>' % (REL_NS, RT))
        ids = "".join('<p:sldId id="%d" r:id="rId%d"/>' % (255 + n, n) for n in order)
        z.writestr("ppt/presentation.xml", '<p:presentation %s><p:sldIdLst>%s</p:sldIdLst>'
                   '<p:sldSz cx="12192000" cy="6858000"/></p:presentation>' % (NS_DECL, ids))
        rels = "".join('<Relationship Id="rId%d" Type="%sslide" Target="slides/slide%d.xml"/>' % (n, RT, n)
                       for n in range(1, len(slides) + 1))
        z.writestr("ppt/_rels/presentation.xml.rels", '<Relationships xmlns="%s">%s</Relationships>' % (REL_NS, rels))
        for n, xml in enumerate(slides, 1):
            z.writestr("ppt/slides/slide%d.xml" % n, xml)
    return buf.getvalue()


W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _wp(text, style=None):
    ppr = '<w:pPr><w:pStyle w:val="%s"/></w:pPr>' % style if style else ""
    return "<w:p>%s<w:r><w:t>%s</w:t></w:r></w:p>" % (ppr, text)


def _wtbl(rows):
    cells = "".join("<w:tr>%s</w:tr>" % "".join("<w:tc>%s</w:tc>" % _wp(c) for c in r) for r in rows)
    return "<w:tbl>%s</w:tbl>" % cells


def _build_docx(body, styles=True):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", "<w:document %s><w:body>%s</w:body></w:document>" % (W_NS, body))
        if styles:
            z.writestr("word/styles.xml", (
                "<w:styles %s>"
                '<w:style w:type="paragraph" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
                '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/></w:style>'
                '<w:style w:type="paragraph" w:styleId="a5"><w:name w:val="제목 2"/></w:style>'
                "</w:styles>" % W_NS))
        z.writestr("docProps/core.xml", (
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/">'
            "<dc:creator>테스트팀</dc:creator><dcterms:created>2026-01-02T03:04:05Z</dcterms:created>"
            "</cp:coreProperties>"))
    return buf.getvalue()


# ---------------------------------------------------------------- 샘플 기준(plan.md M1)


class SamplePptxTest(unittest.TestCase):
    def test_chunk_counts_and_presentation_order(self):
        for prefix, n in ((SAMPLE1, 9), (SAMPLE2, 4)):
            units = parsed(prefix)["units"]
            self.assertEqual(len(units), n)
            self.assertEqual([u["seq"] for u in units], list(range(1, n + 1)))
            zf = zipfile.ZipFile(io.BytesIO(_DATA[prefix]))
            pres = ET.fromstring(zf.read("ppt/presentation.xml"))
            rels = ooxml.read_rels(zf, "ppt/presentation.xml")
            expected = [rels[s.get(ooxml.R + "id")]["target"] for s in pres.iter(ooxml.P + "sldId")]
            self.assertEqual([u["part_name"] for u in units], expected)

    def test_chart_and_group_counts(self):
        charts1 = sum(len(u["view"]["charts"]) for u in parsed(SAMPLE1)["units"])
        charts2 = sum(len(u["view"]["charts"]) for u in parsed(SAMPLE2)["units"])
        self.assertEqual((charts1, charts2), (0, 1))
        p2 = probe.probe_bytes(_DATA[SAMPLE2], ".pptx")
        self.assertEqual((p2["charts"], p2["group_shapes"], p2["slides"]), (1, 0, 4))
        self.assertEqual(probe.probe_bytes(_DATA[SAMPLE1], ".pptx")["charts"], 0)

    def test_coordinate_table_row_restored(self):
        lines = parsed(SAMPLE1)["units"][5]["text"].split("\n")
        self.assertIn("W01 | Center | 13 | 9.62 | 0.18 | 1.87%", lines)

    def test_real_table_row_keeps_verdict(self):
        lines = [x for x in parsed(SAMPLE2)["units"][2]["text"].split("\n") if "브릿지 저항" in x]
        self.assertTrue(lines)
        self.assertTrue(all("FAIL" in x for x in lines), lines)

    def test_disclaimer_removed_everywhere(self):
        for prefix in (SAMPLE1, SAMPLE2, NEAR_DUP):
            for u in parsed(prefix)["units"]:
                self.assertNotIn(DISCLAIMER, u["text"])
                self.assertNotIn(DISCLAIMER, json.dumps(u["view"], ensure_ascii=False))

    def test_notes_section(self):
        self.assertTrue(all("\n[노트]\n" in u["text"] for u in parsed(SAMPLE1)["units"]))
        self.assertFalse(any("[노트]" in u["text"] for u in parsed(SAMPLE2)["units"]))

    def test_images(self):
        min_bytes = DEFAULT_CONFIG["parse"]["image_min_bytes"]
        self.assertEqual(sum(len(u["images"]) for u in parsed(SAMPLE2)["units"]), 0)
        imgs = [i for u in parsed(SAMPLE1)["units"] for i in u["images"]]
        # 고유 17개 중 최소 크기(2048 bytes) 이상이고 한 슬라이드에만 나오는 이미지는 1개다.
        self.assertEqual(len(imgs), 1)
        self.assertEqual(len(set(i["sha256"] for i in imgs)), len(imgs))
        for i in imgs:
            self.assertGreaterEqual(len(i["data"]), min_bytes)
            self.assertEqual(util.sha256_bytes(i["data"]), i["sha256"])

    def test_doc_props(self):
        doc = parsed(SAMPLE2)["doc"]
        self.assertEqual(doc["author"], "공정 AI팀")
        self.assertRegex(doc["created"], r"^\d{4}-\d{2}-\d{2}$")

    def test_chart_section_names_only(self):
        units = [u for u in parsed(SAMPLE2)["units"] if u["view"]["charts"]]
        self.assertEqual(len(units), 1)
        u = units[0]
        self.assertNotIn("UNHANDLED_GRAPHIC", u["warnings"])
        section = _section(u["text"], "[차트]")
        cats = u["view"]["charts"][0]["categories"]
        self.assertTrue(cats)
        self.assertIn("범주: " + ", ".join(cats), section)
        # 수치 값(numCache)은 [차트] 구간에 넣지 않는다.
        zf = zipfile.ZipFile(io.BytesIO(_DATA[SAMPLE2]))
        values = set()
        for name in zf.namelist():
            if name.startswith("ppt/charts/chart") and name.endswith(".xml"):
                root = ET.fromstring(zf.read(name))
                for nc in root.iter(ooxml.C + "numCache"):
                    values.update(v.text for v in nc.iter(ooxml.C + "v"))
        self.assertTrue(values)
        tokens = set(re.findall(r"[\w.]+", "\n".join(section)))
        self.assertFalse(values & tokens, values & tokens)

    def test_near_duplicate_identical_slides_identical_chunks(self):
        za = zipfile.ZipFile(io.BytesIO(_DATA[SAMPLE1]))
        zb = zipfile.ZipFile(io.BytesIO(_DATA[NEAR_DUP]))
        same = [n for n in za.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)
                and n in zb.namelist() and za.read(n) == zb.read(n)]
        self.assertEqual(len(same), 9)
        ta = dict((u["part_name"], u["text"]) for u in parsed(SAMPLE1)["units"])
        tb = dict((u["part_name"], u["text"]) for u in parsed(NEAR_DUP)["units"])
        for n in same:
            self.assertEqual(ta[n], tb[n], n)

    def test_deterministic(self):
        again = parse_pptx(_DATA[SAMPLE1], DEFAULT_CONFIG)
        self.assertEqual([u["text"] for u in again["units"]], [u["text"] for u in parsed(SAMPLE1)["units"]])

    def test_chunk_starts_with_title(self):
        for u in parsed(SAMPLE2)["units"]:
            self.assertTrue(u["title"])
            self.assertEqual(u["text"].split("\n")[0], "# " + u["title"])

    def test_probe_has_no_body_text(self):
        for prefix in (SAMPLE1, SAMPLE2):
            out = json.dumps(probe.probe_bytes(_DATA[prefix], ".pptx"), ensure_ascii=False)
            units = parsed(prefix)["units"]
            needles = [u["title"] for u in units] + [u["view"]["body"][0] for u in units if u["view"]["body"]]
            hits = [n for n in needles if n and n in out]
            self.assertEqual(hits, [])


# ---------------------------------------------------------------- 합성 pptx


class SyntheticPptxTest(unittest.TestCase):
    def test_order_follows_sldIdLst_not_filename(self):
        s1 = _slide([_txbox(2, 0, 0, 5000000, 500000, "첫 파일", ph="title")])
        s2 = _slide([_txbox(2, 0, 0, 5000000, 500000, "둘째 파일", ph="title")])
        units = parse_pptx(_build_pptx([s1, s2], order=[2, 1]), DEFAULT_CONFIG)["units"]
        self.assertEqual([u["part_name"] for u in units], ["ppt/slides/slide2.xml", "ppt/slides/slide1.xml"])
        self.assertEqual([u["title"] for u in units], ["둘째 파일", "첫 파일"])

    def test_group_shape_offsets_and_reading_order(self):
        # 그룹 자식 좌표(chOff/chExt)는 2배 축소된다: 자식 y=4000000 → 슬라이드 y=1000000+2000000.
        group = (
            '<p:grpSp><p:nvGrpSpPr><p:cNvPr id="10" name="g"/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
            '<p:grpSpPr><a:xfrm><a:off x="0" y="1000000"/><a:ext cx="4000000" cy="2000000"/>'
            '<a:chOff x="0" y="0"/><a:chExt cx="8000000" cy="4000000"/></a:xfrm></p:grpSpPr>'
            + _txbox(11, 0, 3000000, 4000000, 300000, "그룹 아래")
            + _txbox(12, 0, 0, 4000000, 300000, "그룹 위")
            + "</p:grpSp>"
        )
        slide = _slide([
            _txbox(2, 0, 0, 8000000, 500000, "제목", ph="title"),
            _txbox(3, 0, 2000000, 4000000, 300000, "중간"),
            group,
        ])
        u = parse_pptx(_build_pptx([slide]), DEFAULT_CONFIG)["units"][0]
        self.assertEqual(u["text"].split("\n"), ["# 제목", "그룹 위", "중간", "그룹 아래"])
        self.assertIn("GROUP_SHAPE", u["warnings"])

    def test_title_from_largest_top_text_when_no_placeholder(self):
        slide = _slide([
            _txbox(2, 0, 100000, 4000000, 200000, "SECTION LABEL", sz=900),
            _txbox(3, 0, 400000, 8000000, 500000, "실제 제목", sz=2800),
            _txbox(4, 0, 2000000, 8000000, 500000, "본문", sz=1400),
        ])
        u = parse_pptx(_build_pptx([slide]), DEFAULT_CONFIG)["units"][0]
        self.assertEqual(u["title"], "실제 제목")
        self.assertEqual(u["text"].split("\n"), ["# 실제 제목", "SECTION LABEL", "본문"])

    def test_boilerplate_and_hidden_slide(self):
        def slide(body, show=True):
            return _slide([
                _txbox(2, 0, 0, 8000000, 500000, body, ph="title"),
                _txbox(3, 0, 1000000, 8000000, 300000, body + " 본문"),
                _txbox(4, 0, 6000000, 8000000, 300000, "CONFIDENTIAL · 바닥글"),
            ], show)
        units = parse_pptx(_build_pptx([slide("A"), slide("B"), slide("C", show=False)]), DEFAULT_CONFIG)["units"]
        self.assertFalse(any("바닥글" in u["text"] for u in units))
        self.assertIn("A 본문", units[0]["text"])
        self.assertIn("HIDDEN_SLIDE", units[2]["warnings"])

    def test_truncation_shrinks_tables_first(self):
        cells = [_txbox(100 + r * 3 + c, c * 2000000, 1000000 + r * 150000, 1900000, 140000, "r%dc%d 값" % (r, c), sz=800)
                 for r in range(30) for c in range(3)]
        slide = _slide([_txbox(2, 0, 0, 8000000, 500000, "큰 표", ph="title")] + cells)
        u = parse_pptx(_build_pptx([slide]), _cfg(chunk_char_limit=200))["units"][0]
        self.assertIn("TRUNCATED", u["warnings"])
        self.assertLessEqual(len(u["text"]), 200)
        self.assertIn("r0c0 값 | r0c1 값 | r0c2 값", u["text"])
        self.assertIn("행 생략", u["text"])

    def test_low_text_warning(self):
        u = parse_pptx(_build_pptx([_slide([_txbox(2, 0, 0, 1000, 1000, "표지", ph="title")])]), DEFAULT_CONFIG)["units"][0]
        self.assertEqual(u["warnings"], ["LOW_TEXT"])


# ---------------------------------------------------------------- docx


class DocxTest(unittest.TestCase):
    def test_split_by_heading_styles(self):
        body = (
            _wp("개요", "Heading1") + _wp("배경 설명 문단입니다.")
            + _wp("결과", "a5") + _wp("결과 문단입니다.") + _wtbl([["항목", "판정"], ["누설", "FAIL"]])
            + _wp("※ " + DISCLAIMER + "(가상) 데이터입니다.")
        )
        doc = chunker.parse_document(".docx", _build_docx(body), DEFAULT_CONFIG)
        units = doc["units"]
        self.assertEqual([u["part_name"] for u in units], ["section-001", "section-002"])
        self.assertEqual([u["title"] for u in units], ["개요", "결과"])
        self.assertEqual(units[0]["text"], "# 개요\n배경 설명 문단입니다.")
        self.assertIn("[표]\n항목 | 판정\n누설 | FAIL", units[1]["text"])
        self.assertNotIn(DISCLAIMER, units[1]["text"])
        self.assertEqual(doc["doc"]["author"], "테스트팀")
        self.assertEqual(doc["doc"]["created"], "2026-01-02")

    def test_fixed_length_split_without_headings(self):
        body = "".join(_wp("문단%02d " % i + "가" * 990) for i in range(10))
        units = parse_docx(_build_docx(body, styles=False), DEFAULT_CONFIG)["units"]
        self.assertGreater(len(units), 1)
        self.assertTrue(all(len(u["text"]) <= 3200 for u in units))
        joined = "\n".join(u["text"] for u in units)
        self.assertEqual(len(re.findall(r"문단\d\d", joined)), 10 + len(units))  # 본문 10개 + 제목 줄
        self.assertTrue(units[0]["title"].startswith("문단00"))

    def test_probe_heading_usage_without_text(self):
        data = _build_docx(_wp("비밀 제목", "Heading1") + _wp("비밀 본문"))
        out = probe.probe_bytes(data, ".docx")
        self.assertEqual(out["heading_style_usage"], {"Heading1": 1})
        self.assertNotIn("비밀", json.dumps(out, ensure_ascii=False))


# ---------------------------------------------------------------- chunker·textnorm


class ChunkerTest(unittest.TestCase):
    def assertReason(self, code, ext, data, cfg=DEFAULT_CONFIG):
        with self.assertRaises(Exception) as ctx:
            chunker.parse_document(ext, data, cfg)
        self.assertEqual(getattr(ctx.exception, "reason_code", None), code)

    def test_reason_codes(self):
        self.assertReason("UNSUPPORTED_FORMAT", ".xlsx", b"PK\x03\x04")
        self.assertReason("ENCRYPTED", ".pptx", b"\xd0\xcf\x11\xe0" + b"\0" * 20)
        self.assertReason("NOT_OOXML", ".docx", b"plain text")
        self.assertReason("PARSE_ERROR", ".pptx", b"PK\x03\x04broken")
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["chunking"]["method"] = "window"
        self.assertReason("UNSUPPORTED_CHUNK_METHOD", ".pptx", _DATA[SAMPLE2], cfg)

    def test_missing_presentation_is_parse_error(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("ppt/slides/slide1.xml", _slide([]))
        self.assertReason("PARSE_ERROR", ".pptx", buf.getvalue())


class TextnormTest(unittest.TestCase):
    def test_boilerplate_needs_ratio_and_three_slides(self):
        slides = [["머리글", "a"], ["머리글", "b"], ["머리글 ", "c"], ["d"]]
        self.assertEqual(textnorm.boilerplate_keys(slides, 0.6), {"머리글"})
        self.assertEqual(textnorm.boilerplate_keys([["x"], ["x"]], 0.6), set())

    def test_always_removed_ignores_spacing(self):
        self.assertTrue(textnorm.is_always_removed("※ 본 자료의  모든 데이터는 내부 테스트용 더미(가상)"))
        self.assertFalse(textnorm.is_always_removed("본 자료의 데이터"))

    def test_trivial_notes(self):
        self.assertTrue(textnorm.is_trivial_note("3"))
        self.assertTrue(textnorm.is_trivial_note("12, 34. 56 - 78 / 90"))
        self.assertTrue(textnorm.is_trivial_note("짧은 노트"))
        self.assertFalse(textnorm.is_trivial_note("이 슬라이드는 누설 전류 결과를 정리했습니다."))


if __name__ == "__main__":
    unittest.main()
