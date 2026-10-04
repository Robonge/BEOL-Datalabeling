"""bytes 기반 xlsx 읽기. 경로를 받지 않는다(CLAUDE.md): read_input이 넘긴 bytes를 io.BytesIO 위에서 연다.

Transitional과 Strict OOXML 네임스페이스를 모두 읽는다. 셀 값은 문자열로 돌려주며,
오류·경고에는 시트 이름과 행 번호만 넣고 셀 내용은 넣지 않는다.
"""
import collections
import datetime
import io
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET

Issue = collections.namedtuple("Issue", "sheet row code message")


def format_issue(issue):
    where = []
    if issue.sheet:
        where.append("%s 시트" % issue.sheet)
    if issue.row:
        where.append("%d행" % issue.row)
    prefix = " ".join(where)
    return "%s: %s" % (prefix, issue.message) if prefix else issue.message


class XlsxError(Exception):
    """파일 단위로 읽을 수 없는 경우(zip이 아님, 필수 part 누락, XML 오류)."""

    def __init__(self, code, message):
        Exception.__init__(self, "%s: %s" % (code, message))
        self.code = code
        self.message = message


FORMULA_NO_CACHE_MSG = "수식 결과 없음, Excel에서 저장 후 다시 실행"
HIDDEN_ROWS_MSG = "숨김 행도 읽는다. 제외는 사용 여부=N"

_ESCAPE = re.compile(r"_x([0-9A-Fa-f]{4})_")
_REF = re.compile(r"^([A-Za-z]{1,3})(\d+)$")


def unescape(s):
    """OOXML `_xHHHH_` 이스케이프를 푼다. `_x005F_`는 밑줄이므로 한 번의 왼쪽→오른쪽 치환으로 충분하다."""
    if "_x" not in s:
        return s
    s = _ESCAPE.sub(lambda m: chr(int(m.group(1), 16)), s)
    # 대리 쌍으로 적힌 문자(_xD83D__xDE00_)를 합친다.
    return s.encode("utf-16", "surrogatepass").decode("utf-16")


def col_index(letters):
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def col_letters(index):
    s = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        s = chr(65 + rem) + s
    return s


def split_ref(ref):
    """'B12' → (12, 1). 형식이 틀리면 None."""
    m = _REF.match(ref or "")
    if not m:
        return None
    return int(m.group(2)), col_index(m.group(1))


def format_number(text):
    """정수형 float는 정수 문자열로, 나머지는 가장 짧은 float 표기로."""
    text = text.strip()
    try:
        return str(int(text))
    except ValueError:
        pass
    try:
        f = float(text)
    except ValueError:
        return text
    if f.is_integer() and abs(f) < 1e15:
        return str(int(f))
    return repr(f)


def serial_to_date(text, date1904=False):
    """Excel 날짜 일련번호를 'YYYY-MM-DD'로. 숫자가 아니면 None."""
    try:
        serial = int(float(text))
    except ValueError:
        return None
    if date1904:
        base = datetime.date(1904, 1, 1)
    elif serial < 60:
        base = datetime.date(1899, 12, 31)  # 1900-02-29(없는 날) 이전
    else:
        base = datetime.date(1899, 12, 30)
    return (base + datetime.timedelta(days=serial)).isoformat()


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _parse_xml(data, part):
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        raise XlsxError("XML_PARSE", "XML을 읽을 수 없다(%s)" % part)
    for el in root.iter():
        el.tag = _local(el.tag)
    return root


def _attr(el, name):
    """네임스페이스와 무관하게 로컬 이름으로 속성을 찾는다(r:id는 Transitional·Strict가 다르다)."""
    if name in el.attrib:
        return el.attrib[name]
    for key, value in el.attrib.items():
        if _local(key) == name:
            return value
    return None


def _truthy(value):
    return (value or "").lower() in ("1", "true")


def _rich_text(el):
    """<si>나 <is>의 글자: 직접 <t> + run(<r>)의 <t>를 잇는다. 윗주(<rPh>)는 뺀다."""
    parts = []
    for child in el:
        if child.tag == "t":
            parts.append(child.text or "")
        elif child.tag == "r":
            for t in child:
                if t.tag == "t":
                    parts.append(t.text or "")
    return unescape("".join(parts))


class Sheet(object):
    """한 시트의 행. rows는 {행 번호: [셀 문자열]}이며 빈 행은 없고 각 행의 뒤쪽 빈 셀은 잘린다."""

    def __init__(self, name):
        self.name = name
        self.rows = {}
        self.numeric = set()  # 숫자 셀 (행 번호, 열 index)
        self.errors = []
        self.warnings = []

    def row(self, number):
        return self.rows.get(number, [])

    def cell(self, number, col):
        r = self.rows.get(number, [])
        return r[col] if col < len(r) else ""

    def iter_rows(self, start=1):
        for number in sorted(self.rows):
            if number >= start:
                yield number, self.rows[number]


class Workbook(object):
    def __init__(self, zf, sheet_parts, shared_strings, date1904):
        self._zf = zf
        self._parts = sheet_parts  # [(이름, part 경로)] 통합 문서 순서
        self._shared = shared_strings
        self._cache = {}
        self.date1904 = date1904

    @property
    def sheet_names(self):
        return [name for name, _ in self._parts]

    def find(self, name):
        """(Sheet 또는 None, 대소문자 불일치 여부). 정확히 같은 이름이 우선이다."""
        for actual, _ in self._parts:
            if actual == name:
                return self._sheet(actual), False
        for actual, _ in self._parts:
            if actual.lower() == name.lower():
                return self._sheet(actual), True
        return None, False

    def _sheet(self, name):
        if name not in self._cache:
            part = dict(self._parts)[name]
            try:
                data = self._zf.read(part)
            except KeyError:
                raise XlsxError("PART_MISSING", "시트 part가 없다(%s)" % name)
            self._cache[name] = _read_sheet(name, _parse_xml(data, part), self._shared)
        return self._cache[name]


def _rels(zf, part):
    """part의 관계 {Id: (type, 대상 part 경로)}."""
    folder, base = posixpath.split(part)
    rels_part = posixpath.join(folder, "_rels", base + ".rels")
    try:
        root = _parse_xml(zf.read(rels_part), rels_part)
    except KeyError:
        return {}
    out = {}
    for rel in root.iter("Relationship"):
        target = rel.get("Target") or ""
        if rel.get("TargetMode") == "External":
            continue
        if target.startswith("/"):
            path = target.lstrip("/")
        else:
            path = posixpath.normpath(posixpath.join(folder, target))
        out[rel.get("Id")] = (rel.get("Type") or "", path)
    return out


def read_workbook(data):
    """xlsx bytes → Workbook. 시트는 처음 찾을 때 읽는다."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise XlsxError("NOT_XLSX", "xlsx(zip) 형식이 아니다")
    workbook_part = "xl/workbook.xml"
    for _, (rtype, path) in _rels(zf, "").items():
        if rtype.endswith("/officeDocument"):
            workbook_part = path
    try:
        wb = _parse_xml(zf.read(workbook_part), workbook_part)
    except KeyError:
        raise XlsxError("PART_MISSING", "workbook.xml이 없다")
    rels = _rels(zf, workbook_part)

    date1904 = False
    pr = wb.find("workbookPr")
    if pr is not None:
        date1904 = _truthy(pr.get("date1904"))

    shared = []
    for rtype, path in rels.values():
        if rtype.endswith("/sharedStrings") and path in zf.namelist():
            sst = _parse_xml(zf.read(path), path)
            shared = [_rich_text(si) for si in sst.findall("si")]

    parts = []
    sheets = wb.find("sheets")
    for s in sheets.findall("sheet") if sheets is not None else []:
        rel = rels.get(_attr(s, "id"))
        if rel and rel[0].endswith("/worksheet"):
            parts.append((s.get("name") or "", rel[1]))
    return Workbook(zf, parts, shared, date1904)


def _read_sheet(name, root, shared):
    sheet = Sheet(name)
    cells = {}  # 행 번호 → {열 index: 값}
    hidden_row = None
    data = root.find("sheetData")
    row_no = 0
    for row in data.findall("row") if data is not None else []:
        r = row.get("r")
        row_no = int(r) if r else row_no + 1
        if _truthy(row.get("hidden")) and hidden_row is None:
            hidden_row = row_no
        col = -1
        for c in row.findall("c"):
            ref = split_ref(c.get("r"))
            if ref:
                row_no_c, col = ref
            else:
                row_no_c, col = row_no, col + 1
            value = _cell_value(sheet, c, row_no_c, col, shared)
            if value:
                cells.setdefault(row_no_c, {})[col] = value

    for number in sorted(cells):
        by_col = cells[number]
        width = max(by_col) + 1
        sheet.rows[number] = [by_col.get(i, "") for i in range(width)]

    merges = root.find("mergeCells")
    for m in merges.findall("mergeCell") if merges is not None else []:
        ref = m.get("ref") or ""
        start = split_ref(ref.split(":")[0])
        sheet.errors.append(
            Issue(name, start[0] if start else None, "MERGED_CELLS", "병합 셀 %s, 병합을 풀고 다시 실행" % ref)
        )

    if hidden_row is not None:
        sheet.warnings.append(Issue(name, hidden_row, "HIDDEN_ROWS", HIDDEN_ROWS_MSG))
    elif root.find("autoFilter") is not None:
        sheet.warnings.append(Issue(name, None, "AUTOFILTER", HIDDEN_ROWS_MSG))
    return sheet


def _cell_value(sheet, c, row_no, col, shared):
    t = c.get("t") or "n"
    v = c.find("v")
    f = c.find("f")
    if t == "inlineStr":
        el = c.find("is")
        return _rich_text(el) if el is not None else ""
    if v is None:
        if f is not None:
            sheet.errors.append(Issue(sheet.name, row_no, "FORMULA_NO_CACHE", FORMULA_NO_CACHE_MSG))
        return ""
    text = v.text or ""
    if t == "s":
        try:
            return shared[int(text)]
        except (ValueError, IndexError):
            sheet.errors.append(Issue(sheet.name, row_no, "BAD_SHARED_STRING", "공유 문자열 참조가 잘못됐다"))
            return ""
    if t in ("str", "d"):
        return unescape(text)
    if t == "b":
        return "TRUE" if text.strip() in ("1", "true") else "FALSE"
    if t == "e":
        sheet.errors.append(
            Issue(sheet.name, row_no, "CELL_ERROR", "%s열 셀이 오류 값이다" % col_letters(col))
        )
        return ""
    if text.strip() == "":
        return ""
    sheet.numeric.add((row_no, col))
    return format_number(text)
