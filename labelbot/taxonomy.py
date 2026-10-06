"""taxonomy.xlsx 파싱과 검증(PRD 6.1·6.2·9.4).

진입점은 parse_bytes(b)다. 파일은 ingest.read_input이 읽어 bytes로 넘긴다.
오류는 모두 모아 TaxonomyError로 한 번에 낸다. 메시지에는 시트 이름과 행 번호만 넣고 셀 내용은 넣지 않는다.
"""
import collections
import re

from labelbot import util, xlsx
from labelbot.xlsx import Issue, format_issue

HEADERS = collections.OrderedDict(
    [
        ("taxonomy", ["축", "값", "상위값", "다중값", "계층", "중복 알림 제외", "종류", "정의·판정 규칙", "포함 예", "제외 예", "사용 여부"]),
        ("questions", ["질문 ID", "문장", "적용 대상", "우선순위"]),
        ("synonyms", ["동의어", "표준어", "메모"]),
        ("rejected", ["종류", "내용", "기각일", "사유"]),
        ("files", ["파일 ID", "파일명", "제외", "맥락 메모"]),
        ("queries", ["조회 ID", "문장", "기대 정답", "채택"]),
    ]
)
REQUIRED = ("taxonomy", "questions", "synonyms", "rejected")

KINDS = ("분류", "상태")
COMMON_TARGET = "공통"
REJECTED_KINDS = ("값", "동의어", "질문")
RESERVED = ("해당없음", "unknown", "n/a", "na")
_QUERY_ID = re.compile(r"^QRY-[0-9A-Fa-f]{8}$")
_SPACE = re.compile(r"\s+")

Value = collections.namedtuple("Value", "name parent definition include exclude row")
Question = collections.namedtuple("Question", "qid text target priority row")
Synonym = collections.namedtuple("Synonym", "alias canonical memo row")
Rejected = collections.namedtuple("Rejected", "kind content date reason row")
FileNote = collections.namedtuple("FileNote", "file_id file_name exclude memo row")
Query = collections.namedtuple("Query", "qid text expected adopted row")


def norm_key(s):
    """같은 값 판정용: NFKC, 소문자, 공백 제거."""
    return _SPACE.sub("", util.nfkc(s)).lower()


def sheet_hash(rows):
    """시트 해시 입력: 정의 열만 자른 원시 문자열 행(뒤쪽 빈 셀과 빈 행 제외)."""
    return util.hash_obj(rows)


EMPTY_SHEET_HASH = sheet_hash([])


class TaxonomyError(Exception):
    def __init__(self, issues, warnings=None):
        self.issues = list(issues)
        self.warnings = list(warnings or [])
        Exception.__init__(self, "\n".join(format_issue(i) for i in self.issues))


class Axis(object):
    def __init__(self, name, kind, multi, hierarchical, dup_alert_exclude, definition, include, exclude,
                 enabled=True, row=None):
        self.name = name
        self.kind = kind
        self.multi = multi
        self.hierarchical = hierarchical
        self.dup_alert_exclude = dup_alert_exclude
        self.definition = definition
        self.include = include
        self.exclude = exclude
        self.enabled = enabled
        self.row = row
        self.values = []  # 사용 여부=N인 값은 넣지 않는다

    @property
    def active(self):
        return self.enabled and bool(self.values)

    def value(self, name):
        key = norm_key(name)
        for v in self.values:
            if norm_key(v.name) == key:
                return v
        return None

    def __repr__(self):
        return "Axis(%r, %d values)" % (self.name, len(self.values))


class Taxonomy(object):
    def __init__(self):
        self.axes = []
        self.questions = []
        self.synonyms = []
        self.rejected = []
        self.files = []
        self.queries = []
        self.sheet_hashes = {}
        self.warnings = []
        self.date1904 = False

    def axis(self, name):
        for a in self.axes:
            if a.name == name:
                return a
        return None

    def active_axes(self):
        return [a for a in self.axes if a.active]

    def unknown_file_warnings(self, known_file_ids):
        """수집 목록에 없는 files 시트의 파일 ID는 경고만 한다(PRD 6.1)."""
        known = set(known_file_ids)
        return [
            Issue("files", f.row, "FILE_ID_UNKNOWN", "수집 목록에 없는 파일 ID다")
            for f in self.files
            if f.file_id not in known
        ]


def _join_text(a, b):
    """같은 값 여러 행의 문장 합치기: 빈 칸·같은 문장(공백 무시)은 빼고 행 순서대로 줄바꿈으로 잇는다."""
    a, b = a or "", b or ""
    if not b.strip() or " ".join(b.split()) in [" ".join(x.split()) for x in a.split("\n")]:
        return a
    return (a.rstrip("\n") + "\n" + b.strip()) if a.strip() else b.strip()


def parse_bytes(b):
    """taxonomy.xlsx bytes → Taxonomy. 오류가 하나라도 있으면 TaxonomyError."""
    try:
        wb = xlsx.read_workbook(b)
    except xlsx.XlsxError as e:
        raise TaxonomyError([Issue(None, None, e.code, e.message)])
    p = _Parser(wb)
    p.run()
    if p.errors:
        raise TaxonomyError(p.errors, p.tax.warnings)
    return p.tax


class _Parser(object):
    def __init__(self, wb):
        self.wb = wb
        self.tax = Taxonomy()
        self.tax.date1904 = wb.date1904
        self.errors = []

    def error(self, sheet, row, code, message):
        self.errors.append(Issue(sheet, row, code, message))

    def warn(self, sheet, row, code, message):
        self.tax.warnings.append(Issue(sheet, row, code, message))

    def run(self):
        sheets = {}
        for name, header in HEADERS.items():
            sheets[name] = self._load(name, header)
        self._taxonomy(sheets["taxonomy"])
        self._questions(sheets["questions"])
        self._synonyms(sheets["synonyms"])
        self._rejected(sheets["rejected"])
        self._files(sheets["files"])
        self._queries(sheets["queries"])

    def _load(self, name, header):
        """시트를 찾아 해시를 내고 머리글을 확인한다. 데이터 행 [(행 번호, 정의 열 셀)]을 돌려준다."""
        width = len(header)
        expected = " | ".join(header)
        try:
            sheet, case_mismatch = self.wb.find(name)
        except xlsx.XlsxError as e:
            self.error(name, None, e.code, e.message)
            return []
        if sheet is None:
            self.tax.sheet_hashes[name] = EMPTY_SHEET_HASH
            if name in REQUIRED:
                self.error(name, None, "SHEET_MISSING", "필수 시트가 없다. 기대 머리글: %s" % expected)
            return []
        if case_mismatch:
            self.warn(name, None, "SHEET_NAME_CASE", "시트 이름의 대소문자가 다르다. 찾아서 읽는다")
        self.errors.extend(sheet.errors)
        self.tax.warnings.extend(sheet.warnings)

        rows = []
        hashed = []
        extra_row = None
        for number, cells in sheet.iter_rows():
            if extra_row is None and any(c != "" for c in cells[width:]):
                extra_row = number
            defined = _trim(cells[:width])
            if defined:
                hashed.append(defined)
                rows.append((number, defined + [""] * (width - len(defined))))
        self.tax.sheet_hashes[name] = sheet_hash(hashed)
        if extra_row is not None:
            self.warn(name, extra_row, "EXTRA_COLUMNS", "정의 열 오른쪽에 추가한 열은 무시한다")

        if _trim(sheet.row(1)[:width]) != header:
            self.error(name, 1, "HEADER_MISMATCH", "머리글이 다르다. 기대 머리글: %s" % expected)
            return []
        return [(n, cells) for n, cells in rows if n > 1]

    def _yn(self, sheet, number, value, label, required):
        v = value.strip().upper()
        if v in ("Y", "N"):
            return v == "Y"
        if v == "" and not required:
            return None
        self.error(sheet, number, "YN_INVALID", "%s 열은 Y/N이어야 한다" % label)
        return None

    # --- taxonomy ---
    def _taxonomy(self, rows):
        numeric = self._numeric_snapshot("taxonomy")
        value_rows = []
        for number, c in rows:
            axis_name, value = c[0].strip(), c[1].strip()
            enabled = self._yn("taxonomy", number, c[10], "사용 여부", False) is not False
            if not axis_name:
                self.error("taxonomy", number, "AXIS_NOT_DEFINED", "축 열이 비어 있다")
                continue
            if value:
                if (number, 1) in numeric:
                    self.warn("taxonomy", number, "NUMERIC_CELL", "값 열이 숫자 셀이다(Excel 자동 변환 의심)")
                if any(x.strip() for x in c[3:7]):
                    self.error("taxonomy", number, "AXIS_ATTR_ON_VALUE", "축 속성(다중값·계층·중복 알림 제외·종류)이 값 행에 적혀 있다")
                if enabled:
                    value_rows.append((number, axis_name, value, c))
                continue
            self._axis_row(number, axis_name, c, enabled)

        for number, axis_name, value, c in value_rows:
            axis = self.tax.axis(axis_name)
            if axis is None:
                self.error("taxonomy", number, "AXIS_NOT_DEFINED", "축 정의 행이 없는 값이다")
                continue
            if norm_key(value) in RESERVED:
                self.error("taxonomy", number, "RESERVED_VALUE", "예약어(해당 없음, unknown 및 변형)는 값으로 쓸 수 없다")
                continue
            old = axis.value(value)
            if old is not None:
                # 같은 값 행이 여럿이면 정의·포함 예·제외 예를 모두 모아 함께 쓴다(라벨러 LLM이 전부 참고한다).
                # 상위값이 서로 다르게 적혀 있으면 계층이 모호하므로 오류다.
                parent = c[2].strip() or None
                if parent and old.parent and norm_key(parent) != norm_key(old.parent):
                    self.error("taxonomy", number, "DUPLICATE_VALUE_PARENT_CONFLICT",
                               "%d행과 같은 값인데 상위값이 다르다" % old.row)
                    continue
                axis.values[axis.values.index(old)] = old._replace(
                    parent=old.parent or parent, definition=_join_text(old.definition, c[7]),
                    include=_join_text(old.include, c[8]), exclude=_join_text(old.exclude, c[9]))
                continue
            axis.values.append(Value(value, c[2].strip() or None, c[7], c[8], c[9], number))

        for axis in self.tax.axes:
            resolved = []
            for v in axis.values:
                if v.parent is not None:
                    parent = axis.value(v.parent)
                    if parent is None or parent is v:
                        self.error("taxonomy", v.row, "PARENT_NOT_FOUND", "같은 축에 없는 상위값이다")
                    else:
                        v = v._replace(parent=parent.name)
                resolved.append(v)
            axis.values = resolved

    def _axis_row(self, number, name, c, enabled):
        old = self.tax.axis(name)
        if old is not None:
            # 같은 축 정의 행이 여럿이면 정의·포함 예·제외 예를 모두 모아 함께 쓴다(값 행과 같은 규칙).
            # 축 속성(다중값·계층·중복 알림 제외·종류)을 서로 다르게 적었으면 어느 쪽인지 정할 수 없어 오류다.
            attrs = ((c[3], "Y" if old.multi else "N"), (c[4], "Y" if old.hierarchical else "N"),
                     (c[5], "Y" if old.dup_alert_exclude else "N"), (c[6], old.kind))
            if any(new.strip() and new.strip().upper() != cur.upper() for new, cur in attrs):
                self.error("taxonomy", number, "DUPLICATE_AXIS_ATTR_CONFLICT",
                           "%d행과 같은 축인데 축 속성(다중값·계층·중복 알림 제외·종류)이 다르다" % old.row)
                return
            if enabled:
                old.definition = _join_text(old.definition, c[7])
                old.include = _join_text(old.include, c[8])
                old.exclude = _join_text(old.exclude, c[9])
                old.enabled = True
            return
        multi = self._yn("taxonomy", number, c[3], "다중값", True)
        hier = self._yn("taxonomy", number, c[4], "계층", True)
        dup = self._yn("taxonomy", number, c[5], "중복 알림 제외", True)
        kind = c[6].strip()
        if kind not in KINDS:
            self.error("taxonomy", number, "AXIS_KIND_INVALID", "종류 열은 분류/상태여야 한다")
        self.tax.axes.append(
            Axis(name, kind, bool(multi), bool(hier), bool(dup), c[7], c[8], c[9], enabled=enabled, row=number)
        )

    # --- questions ---
    def _questions(self, rows):
        seen = set()
        for number, c in rows:
            qid, text, target, priority = c[0].strip(), c[1].strip(), c[2].strip(), c[3].strip()
            if not qid:
                self.error("questions", number, "QUESTION_ID_EMPTY", "질문 ID가 비어 있다")
                continue
            if qid in seen:
                self.error("questions", number, "QUESTION_ID_DUPLICATE", "중복된 질문 ID다")
                continue
            seen.add(qid)
            if not text:
                self.error("questions", number, "QUESTION_TEXT_EMPTY", "문장이 비어 있다")
            parsed_target = self._target(number, target)
            try:
                prio = int(priority)
            except ValueError:
                self.error("questions", number, "QUESTION_PRIORITY_INVALID", "우선순위는 정수여야 한다")
                prio = None
            self.tax.questions.append(Question(qid, text, parsed_target, prio, number))

    def _target(self, number, target):
        if target == COMMON_TARGET:
            return COMMON_TARGET
        if "=" in target:
            axis_name, value = [x.strip() for x in target.split("=", 1)]
            axis = self.tax.axis(axis_name)
            v = axis.value(value) if axis is not None else None
            if v is not None:
                return (axis.name, v.name)
        self.error("questions", number, "QUESTION_TARGET_INVALID", "적용 대상은 공통 또는 있는 축=값이어야 한다")
        return None

    # --- synonyms ---
    def _synonyms(self, rows):
        numeric = self._numeric_snapshot("synonyms")
        seen = {}
        for number, c in rows:
            alias, canonical = c[0].strip(), c[1].strip()
            for col, label in ((0, "동의어"), (1, "표준어")):
                if (number, col) in numeric:
                    self.warn("synonyms", number, "NUMERIC_CELL", "%s 열이 숫자 셀이다(Excel 자동 변환 의심)" % label)
            if not canonical:
                self.error("synonyms", number, "SYNONYM_NO_CANONICAL", "표준어가 비어 있다")
                continue
            if not alias:
                self.error("synonyms", number, "SYNONYM_NO_ALIAS", "동의어가 비어 있다")
                continue
            key = util.nfkc(alias).lower()
            if key in seen:
                self.warn("synonyms", number, "DUPLICATE_SYNONYM", "%d행과 같은 동의어다. 첫 행을 쓴다" % seen[key])
                continue
            seen[key] = number
            self.tax.synonyms.append(Synonym(alias, canonical, c[2], number))

    # --- rejected ---
    def _rejected(self, rows):
        numeric = self._numeric_snapshot("rejected")
        for number, c in rows:
            kind = c[0].strip()
            if kind not in REJECTED_KINDS:
                self.error("rejected", number, "REJECTED_KIND_INVALID", "종류는 값/동의어/질문이어야 한다")
            date = c[2].strip()
            if (number, 2) in numeric:
                date = xlsx.serial_to_date(date, self.tax.date1904) or date
            self.tax.rejected.append(Rejected(kind, c[1], date, c[3], number))

    # --- files ---
    def _files(self, rows):
        seen = set()
        for number, c in rows:
            fid = c[0].strip()
            if not fid:
                self.error("files", number, "FILE_ID_EMPTY", "파일 ID가 비어 있다")
                continue
            if fid in seen:
                self.error("files", number, "FILE_ID_DUPLICATE", "중복된 파일 ID다")
                continue
            seen.add(fid)
            exclude = self._yn("files", number, c[2], "제외", False)
            self.tax.files.append(FileNote(fid, c[1], bool(exclude), c[3], number))

    # --- queries ---
    def _queries(self, rows):
        seen = set()
        for number, c in rows:
            qid = c[0].strip()
            if not _QUERY_ID.match(qid):
                self.error("queries", number, "QUERY_ID_INVALID", "조회 ID는 QRY- + 16진수 8자리여야 한다")
                continue
            if qid in seen:
                self.error("queries", number, "QUERY_ID_DUPLICATE", "중복된 조회 ID다")
                continue
            seen.add(qid)
            expected = [x.strip() for x in c[2].split(";") if x.strip()]
            adopted = self._yn("queries", number, c[3], "채택", False)
            self.tax.queries.append(Query(qid, c[1], expected, bool(adopted), number))

    def _numeric_snapshot(self, name):
        try:
            sheet, _ = self.wb.find(name)
        except xlsx.XlsxError:
            return set()
        return sheet.numeric if sheet is not None else set()


def _trim(cells):
    cells = list(cells)
    while cells and cells[-1] == "":
        cells.pop()
    return cells
