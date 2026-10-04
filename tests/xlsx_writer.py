"""테스트 픽스처용 xlsx bytes를 메모리에서만 만든다(io.BytesIO + zipfile). 디스크에 쓰지 않는다.

build(sheets, shared=True, strict=False, date1904=False, pad_empty=False)
- sheets: [(이름, 행 목록)] 또는 [{"name", "rows", "merge", "hidden_rows", "autofilter"}]
- 행 목록의 각 행은 셀 목록이고, 행이 None이면 그 행을 생략한다. 셀이 None이면 그 셀을 생략한다.
- 셀 값: str(shared=True면 sharedStrings, 아니면 inlineStr), int/float(숫자), bool(t="b"),
  또는 아래 셀 클래스.
"""
import io
import zipfile
from xml.sax.saxutils import escape, quoteattr

TRANSITIONAL = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel_type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/",
}
STRICT = {
    "main": "http://purl.oclc.org/ooxml/spreadsheetml/main",
    "r": "http://purl.oclc.org/ooxml/officeDocument/relationships",
    "rel_type": "http://purl.oclc.org/ooxml/officeDocument/relationships/",
}
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"


class Runs(object):
    """sharedStrings의 rich text run. phonetic은 <rPh> 윗주 글자(읽을 때 빠져야 한다)."""

    def __init__(self, *runs, **kw):
        self.runs = runs
        self.phonetic = kw.get("phonetic")


class Inline(object):
    def __init__(self, text):
        self.text = text


class FormulaStr(object):
    """t="str" 수식 결과."""

    def __init__(self, text, formula="A1"):
        self.text = text
        self.formula = formula


class Err(object):
    def __init__(self, code="#REF!"):
        self.code = code


class FormulaNoCache(object):
    def __init__(self, formula="1+1"):
        self.formula = formula


def _col(index):
    s = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        s = chr(65 + rem) + s
    return s


def _t(text):
    space = ' xml:space="preserve"' if text != text.strip() else ""
    return "<t%s>%s</t>" % (space, escape(text))


class _Strings(object):
    def __init__(self):
        self.items = []
        self.index = {}

    def add(self, xml):
        if xml not in self.index:
            self.index[xml] = len(self.items)
            self.items.append(xml)
        return self.index[xml]


def _cell(ref, value, shared, strings):
    if value is None:
        return ""
    if isinstance(value, bool):
        return '<c r="%s" t="b"><v>%d</v></c>' % (ref, int(value))
    if isinstance(value, (int, float)):
        return '<c r="%s"><v>%r</v></c>' % (ref, value)
    if isinstance(value, Runs):
        body = "".join("<r><rPr><b/></rPr>%s</r>" % _t(r) for r in value.runs)
        if value.phonetic:
            body += '<rPh sb="0" eb="1">%s</rPh>' % _t(value.phonetic)
        return '<c r="%s" t="s"><v>%d</v></c>' % (ref, strings.add(body))
    if isinstance(value, Inline):
        return '<c r="%s" t="inlineStr"><is>%s</is></c>' % (ref, _t(value.text))
    if isinstance(value, FormulaStr):
        return '<c r="%s" t="str"><f>%s</f><v>%s</v></c>' % (ref, escape(value.formula), escape(value.text))
    if isinstance(value, Err):
        return '<c r="%s" t="e"><f>1/0</f><v>%s</v></c>' % (ref, escape(value.code))
    if isinstance(value, FormulaNoCache):
        return '<c r="%s"><f>%s</f></c>' % (ref, escape(value.formula))
    if shared:
        return '<c r="%s" t="s"><v>%d</v></c>' % (ref, strings.add(_t(value)))
    return '<c r="%s" t="inlineStr"><is>%s</is></c>' % (ref, _t(value))


def _sheet_xml(spec, ns, shared, strings, pad_empty):
    hidden = set(spec.get("hidden_rows") or ())
    rows_xml = []
    for i, row in enumerate(spec["rows"]):
        if row is None:
            continue
        number = i + 1
        cells = []
        for j, value in enumerate(row):
            ref = "%s%d" % (_col(j), number)
            if value is None and pad_empty:
                cells.append('<c r="%s" s="1"/>' % ref)
            else:
                cells.append(_cell(ref, value, shared, strings))
        attrs = ' r="%d"' % number
        if number in hidden:
            attrs += ' hidden="1"'
        rows_xml.append("<row%s>%s</row>" % (attrs, "".join(cells)))
    parts = ['<worksheet xmlns="%s" xmlns:r="%s">' % (ns["main"], ns["r"])]
    parts.append("<sheetData>%s</sheetData>" % "".join(rows_xml))
    if spec.get("autofilter"):
        parts.append("<autoFilter ref=%s/>" % quoteattr(spec["autofilter"]))
    merges = spec.get("merge") or []
    if merges:
        parts.append(
            '<mergeCells count="%d">%s</mergeCells>'
            % (len(merges), "".join("<mergeCell ref=%s/>" % quoteattr(m) for m in merges))
        )
    parts.append("</worksheet>")
    return "".join(parts)


def build(sheets, shared=True, strict=False, date1904=False, pad_empty=False):
    ns = STRICT if strict else TRANSITIONAL
    specs = []
    for s in sheets:
        if isinstance(s, dict):
            specs.append(s)
        else:
            specs.append({"name": s[0], "rows": s[1]})

    strings = _Strings()
    sheet_xml = [_sheet_xml(s, ns, shared, strings, pad_empty) for s in specs]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        overrides = "".join(
            '<Override PartName="/xl/worksheets/sheet%d.xml" ContentType='
            '"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' % (i + 1)
            for i in range(len(specs))
        )
        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType='
            '"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/sharedStrings.xml" ContentType='
            '"application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
            "%s</Types>" % overrides,
        )
        z.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="%s"><Relationship Id="rId1" Type="%sofficeDocument" '
            'Target="xl/workbook.xml"/></Relationships>' % (PKG_REL, ns["rel_type"]),
        )
        sheets_xml = "".join(
            '<sheet name=%s sheetId="%d" r:id="rId%d"/>' % (quoteattr(s["name"]), i + 1, i + 1)
            for i, s in enumerate(specs)
        )
        z.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="%s" xmlns:r="%s"><workbookPr%s/><sheets>%s</sheets></workbook>'
            % (ns["main"], ns["r"], ' date1904="1"' if date1904 else "", sheets_xml),
        )
        rels = "".join(
            '<Relationship Id="rId%d" Type="%sworksheet" Target="worksheets/sheet%d.xml"/>'
            % (i + 1, ns["rel_type"], i + 1)
            for i in range(len(specs))
        )
        rels += '<Relationship Id="rIdSST" Type="%ssharedStrings" Target="sharedStrings.xml"/>' % ns["rel_type"]
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="%s">%s</Relationships>' % (PKG_REL, rels),
        )
        for i, xml in enumerate(sheet_xml):
            z.writestr(
                "xl/worksheets/sheet%d.xml" % (i + 1),
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + xml,
            )
        z.writestr(
            "xl/sharedStrings.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<sst xmlns="%s" count="%d" uniqueCount="%d">%s</sst>'
            % (ns["main"], len(strings.items), len(strings.items), "".join("<si>%s</si>" % x for x in strings.items)),
        )
    return buf.getvalue()
