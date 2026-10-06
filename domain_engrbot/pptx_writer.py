"""합성 pptx·docx bytes를 io.BytesIO 안에서만 만든다. 디스크에 쓰지 않는다(CLAUDE.md).

슬라이드 명세(dict):
  title: 제목(제목 placeholder)
  lines: 본문 줄 목록(텍스트 상자 하나, 줄마다 단락)
  table: [[셀, ...], ...] 또는 None
  images: [bytes, ...]
  hidden: True면 숨김 슬라이드(show="0")
  footer: 반복 바닥글 문구 또는 None
  notes: 노트 문구 또는 None
"""
import hashlib
import io
import zipfile
from xml.sax.saxutils import escape

NS_DECL = (
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
    'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
)
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
RT = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
OLE_SIG = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def fake_png(seed, size=3000):
    """PNG 시그니처로 시작하는 결정론 bytes. 이미지 내용은 검사하지 않으므로 해시와 크기만 의미가 있다."""
    out = bytearray(b"\x89PNG\r\n\x1a\n")
    h = hashlib.sha256(str(seed).encode("utf-8")).digest()
    while len(out) < size:
        h = hashlib.sha256(h).digest()
        out += h
    return bytes(out[:size])


def _txbox(sid, y, lines, ph=None, sz=1400):
    nvpr = '<p:nvPr><p:ph type="%s"/></p:nvPr>' % ph if ph else "<p:nvPr/>"
    paras = "".join('<a:p><a:r><a:rPr lang="ko-KR" sz="%d"/><a:t>%s</a:t></a:r></a:p>' % (sz, escape(t)) for t in lines)
    return (
        '<p:sp><p:nvSpPr><p:cNvPr id="%d" name="t%d"/><p:cNvSpPr txBox="1"/>%s</p:nvSpPr>'
        '<p:spPr><a:xfrm><a:off x="457200" y="%d"/><a:ext cx="8229600" cy="914400"/></a:xfrm></p:spPr>'
        "<p:txBody><a:bodyPr/>%s</p:txBody></p:sp>" % (sid, sid, nvpr, y, paras)
    )


def _table(sid, y, rows):
    ncol = max(len(r) for r in rows)
    grid = "".join('<a:gridCol w="%d"/>' % (8229600 // ncol) for _ in range(ncol))
    trs = []
    for r in rows:
        tcs = "".join(
            '<a:tc><a:txBody><a:bodyPr/><a:p><a:r><a:t>%s</a:t></a:r></a:p></a:txBody><a:tcPr/></a:tc>' % escape(c)
            for c in list(r) + [""] * (ncol - len(r)))
        trs.append('<a:tr h="370840">%s</a:tr>' % tcs)
    return (
        '<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="%d" name="tbl%d"/><p:cNvGraphicFramePr/><p:nvPr/>'
        '</p:nvGraphicFramePr><p:xfrm><a:off x="457200" y="%d"/><a:ext cx="8229600" cy="1483360"/></p:xfrm>'
        '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table"><a:tbl>'
        "<a:tblGrid>%s</a:tblGrid>%s</a:tbl></a:graphicData></a:graphic></p:graphicFrame>"
        % (sid, sid, y, grid, "".join(trs))
    )


def _pic(sid, rid, n):
    return (
        '<p:pic><p:nvPicPr><p:cNvPr id="%d" name="pic%d"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr>'
        '<p:blipFill><a:blip r:embed="%s"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>'
        '<p:spPr><a:xfrm><a:off x="%d" y="4572000"/><a:ext cx="1828800" cy="1371600"/></a:xfrm></p:spPr></p:pic>'
        % (sid, sid, rid, 457200 + n * 1905000)
    )


def _slide_xml(spec, rids):
    shapes = []
    sid = 2
    if spec.get("title"):
        shapes.append(_txbox(sid, 228600, [spec["title"]], ph="title", sz=2800))
        sid += 1
    if spec.get("lines"):
        shapes.append(_txbox(sid, 1143000, spec["lines"]))
        sid += 1
    if spec.get("table"):
        shapes.append(_table(sid, 2743200, spec["table"]))
        sid += 1
    for n, rid in enumerate(rids):
        shapes.append(_pic(sid, rid, n))
        sid += 1
    if spec.get("footer"):
        shapes.append(_txbox(sid, 6400800, [spec["footer"]], sz=900))
        sid += 1
    show = ' show="0"' if spec.get("hidden") else ""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<p:sld %s%s><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        "<p:grpSpPr/>%s</p:spTree></p:cSld></p:sld>" % (NS_DECL, show, "".join(shapes))
    )


def _notes_xml(text):
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        "<p:notes %s><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id=\"1\" name=\"\"/><p:cNvGrpSpPr/><p:nvPr/>"
        "</p:nvGrpSpPr><p:grpSpPr/>%s</p:spTree></p:cSld></p:notes>" % (NS_DECL, _txbox(2, 0, text.split("\n"), ph="body"))
    )


def build_pptx(slides):
    """슬라이드 명세 목록 → pptx bytes. 같은 입력이면 같은 bytes를 만든다."""
    buf = io.BytesIO()
    media = {}  # sha256 → 파일 이름(같은 이미지는 한 번만 넣는다)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        def put(name, data):
            zi = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(zi, data)

        overrides = ['<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-'
                     'officedocument.presentationml.presentation.main+xml"/>']
        for n in range(1, len(slides) + 1):
            overrides.append('<Override PartName="/ppt/slides/slide%d.xml" ContentType="application/vnd.'
                             'openxmlformats-officedocument.presentationml.slide+xml"/>' % n)
        put("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="%s">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/>'
            "%s</Types>" % (CT_NS, "".join(overrides)))
        put("_rels/.rels", '<Relationships xmlns="%s"><Relationship Id="rId1" Type="%sofficeDocument" '
            'Target="ppt/presentation.xml"/></Relationships>' % (REL_NS, RT))
        ids = "".join('<p:sldId id="%d" r:id="rId%d"/>' % (255 + n, n) for n in range(1, len(slides) + 1))
        put("ppt/presentation.xml", '<?xml version="1.0" encoding="UTF-8"?><p:presentation %s><p:sldIdLst>%s'
            '</p:sldIdLst><p:sldSz cx="12192000" cy="6858000"/></p:presentation>' % (NS_DECL, ids))
        rels = "".join('<Relationship Id="rId%d" Type="%sslide" Target="slides/slide%d.xml"/>' % (n, RT, n)
                       for n in range(1, len(slides) + 1))
        put("ppt/_rels/presentation.xml.rels", '<Relationships xmlns="%s">%s</Relationships>' % (REL_NS, rels))
        for n, spec in enumerate(slides, 1):
            srels, rids = [], []
            for k, img in enumerate(spec.get("images") or [], 1):
                h = hashlib.sha256(img).hexdigest()
                if h not in media:
                    media[h] = "image%d.png" % (len(media) + 1)
                    put("ppt/media/" + media[h], img)
                rid = "rId%d" % (k + 10)
                rids.append(rid)
                srels.append('<Relationship Id="%s" Type="%simage" Target="../media/%s"/>' % (rid, RT, media[h]))
            if spec.get("notes"):
                srels.append('<Relationship Id="rId99" Type="%snotesSlide" Target="../notesSlides/notesSlide%d.xml"/>'
                             % (RT, n))
                put("ppt/notesSlides/notesSlide%d.xml" % n, _notes_xml(spec["notes"]))
            put("ppt/slides/slide%d.xml" % n, _slide_xml(spec, rids))
            if srels:
                put("ppt/slides/_rels/slide%d.xml.rels" % n,
                    '<Relationships xmlns="%s">%s</Relationships>' % (REL_NS, "".join(srels)))
    return buf.getvalue()


W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def build_docx(paragraphs, tables=()):
    """paragraphs: [(텍스트, 스타일 또는 None)], tables: [[[셀]]] → docx bytes."""
    body = []
    for text, style in paragraphs:
        ppr = '<w:pPr><w:pStyle w:val="%s"/></w:pPr>' % style if style else ""
        body.append("<w:p>%s<w:r><w:t>%s</w:t></w:r></w:p>" % (ppr, escape(text)))
    for rows in tables:
        trs = "".join("<w:tr>%s</w:tr>" % "".join("<w:tc><w:p><w:r><w:t>%s</w:t></w:r></w:p></w:tc>" % escape(c)
                                                    for c in r) for r in rows)
        body.append("<w:tbl>%s</w:tbl>" % trs)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(zipfile.ZipInfo("word/document.xml", date_time=(2026, 1, 1, 0, 0, 0)),
                   "<w:document %s><w:body>%s</w:body></w:document>" % (W_NS, "".join(body)))
        z.writestr(zipfile.ZipInfo("word/styles.xml", date_time=(2026, 1, 1, 0, 0, 0)), (
            "<w:styles %s><w:style w:type=\"paragraph\" w:styleId=\"Heading1\"><w:name w:val=\"heading 1\"/>"
            "</w:style></w:styles>" % W_NS))
    return buf.getvalue()


def encrypted_bytes(seed="enc"):
    """OLE 시그니처로 시작하는 bytes(암호가 걸린 OOXML을 흉내 낸다)."""
    return OLE_SIG + hashlib.sha256(seed.encode("utf-8")).digest() * 8
