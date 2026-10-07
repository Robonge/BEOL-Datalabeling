"""taxonomy.json 파싱·검증·저장(PRD 6.1·6.2·9.4).

원본은 taxonomy.json 하나다. 시트(taxonomy·questions·synonyms)마다 행 객체(열 이름 → 문자열) 목록을 두고,
기각한 후보는 rejected 목록에 둔다. 행 의미·검증 규칙·시트 해시는 예전 taxonomy.xlsx와 같다.

진입점:
- parse_bytes(b) / parse_doc(doc): JSON → Taxonomy. 오류는 모두 모아 TaxonomyError로 한 번에 낸다.
  메시지에는 시트 이름과 행 번호(머리글이 1행, 첫 행 객체가 2행)만 넣고 셀 내용은 넣지 않는다.
- xlsx_to_doc(b): 예전 taxonomy.xlsx bytes → doc(1회 변환 전용, taxonomy-migrate).
- load_doc / save_doc / diff_docs: 보드·편집기가 쓰는 읽기·원자적 저장(버전 확인·검증·이력)·변경 미리보기.
"""
import collections
import difflib
import json
import os
import re
import tempfile
import uuid

from labelbot import util, xlsx
from labelbot.xlsx import Issue, format_issue

HEADERS = collections.OrderedDict(
    [
        ("taxonomy", ["축", "값", "상위값", "다중값", "계층", "중복 알림 제외", "종류", "정의·판정 규칙", "포함 예", "제외 예", "사용 여부"]),
        ("questions", ["질문 ID", "문장", "적용 대상", "우선순위"]),
        ("synonyms", ["동의어", "표준어", "메모"]),
    ]
)
REJECTED_HEADER = ["종류", "내용", "기각일", "사유", "출처"]
DOC_VERSION = 1
HISTORY_NAME = "taxonomy_history.jsonl"

KINDS = ("분류", "상태")
COMMON_TARGET = "공통"
# rejected 종류. 값·동의어·질문은 labelbot 후보도 거르고, 나머지는 taxonomy 보드가 같은 제안을 다시 올리지 않게 쓴다.
# 내용은 "|"로 나눈 대상(예: 값 "축|값", 겹침 "축|값|값", 축 정의 "축", 질문 수정 "질문 ID", 용어 "용어")이다.
REJECTED_KINDS = ("값", "동의어", "질문", "값 끄기", "값 정의", "겹침", "축 정의", "질문 수정", "새 축", "용어", "기타")
RESERVED = ("해당없음", "unknown", "n/a", "na")
_SPACE = re.compile(r"\s+")

Value = collections.namedtuple("Value", "name parent definition include exclude row")
Question = collections.namedtuple("Question", "qid text target priority row")
Synonym = collections.namedtuple("Synonym", "alias canonical memo row")
Rejected = collections.namedtuple("Rejected", "kind content date reason row")


def norm_key(s):
    """같은 값 판정용: NFKC, 소문자, 공백 제거."""
    return _SPACE.sub("", util.nfkc(s)).lower()


def rejected_key(kind, content):
    """rejected 대조 키: (종류, "|"로 나눈 칸마다 norm_key). 띄어쓰기·대소문자·전각 차이는 같은 제안으로 본다."""
    return ((kind or "").strip(), "|".join(norm_key(p) for p in (content or "").split("|")))


def sheet_hash(rows):
    """시트 해시 입력: 머리글 행과 정의 열만 자른 원시 문자열 행(뒤쪽 빈 칸과 빈 행 제외).
    예전 xlsx 파서와 같은 입력이라 xlsx → JSON 변환 전후 해시가 같다."""
    return util.hash_obj(rows)


EMPTY_SHEET_HASH = sheet_hash([])


class TaxonomyError(Exception):
    def __init__(self, issues, warnings=None):
        self.issues = list(issues)
        self.warnings = list(warnings or [])
        Exception.__init__(self, "\n".join(format_issue(i) for i in self.issues))


class TaxonomyConflict(Exception):
    """저장하려는 사이 파일이 바뀌었다(읽은 버전과 지금 버전이 다르다)."""
    reason_code = "TAXONOMY_CHANGED"


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
        self.sheet_hashes = {}
        self.warnings = []

    def axis(self, name):
        for a in self.axes:
            if a.name == name:
                return a
        return None

    def active_axes(self):
        return [a for a in self.axes if a.active]


def _join_text(a, b):
    """같은 값 여러 행의 문장 합치기: 빈 칸·같은 문장(공백 무시)은 빼고 행 순서대로 줄바꿈으로 잇는다."""
    a, b = a or "", b or ""
    if not b.strip() or " ".join(b.split()) in [" ".join(x.split()) for x in a.split("\n")]:
        return a
    return (a.rstrip("\n") + "\n" + b.strip()) if a.strip() else b.strip()


# ---- 문서 ----------------------------------------------------------------------

def empty_doc():
    return {"version": DOC_VERSION, "taxonomy": [], "questions": [], "synonyms": [], "rejected": []}


def decode_doc(b):
    """JSON bytes → doc dict. 형식이 틀리면 TaxonomyError(TAXONOMY_JSON_INVALID)."""
    try:
        doc = json.loads(b.decode("utf-8-sig") if isinstance(b, bytes) else b)
    except (UnicodeDecodeError, ValueError):
        raise TaxonomyError([Issue(None, None, "TAXONOMY_JSON_INVALID", "JSON으로 읽을 수 없다")])
    if not isinstance(doc, dict):
        raise TaxonomyError([Issue(None, None, "TAXONOMY_JSON_INVALID", "최상위가 객체가 아니다")])
    return doc


def parse_bytes(b):
    """taxonomy.json bytes → Taxonomy. 오류가 하나라도 있으면 TaxonomyError."""
    return parse_doc(decode_doc(b))


def parse_doc(doc):
    """doc dict → Taxonomy. 오류가 하나라도 있으면 TaxonomyError."""
    p = _Parser(doc)
    p.run()
    if p.errors:
        raise TaxonomyError(p.errors, p.tax.warnings)
    return p.tax


def check_doc(doc):
    """저장 전 검증. 반환: (오류 [Issue], 경고 [Issue])."""
    try:
        tax = parse_doc(doc)
    except TaxonomyError as e:
        return e.issues, e.warnings
    return [], tax.warnings


def row_cells(obj, header):
    """행 객체 → 머리글 순서의 칸 리스트(없는 열은 "")."""
    return [obj.get(h, "") if isinstance(obj.get(h, ""), str) else "" for h in header]


def row_obj(cells, header):
    """칸 리스트 → 행 객체(머리글 순서, 모자란 칸은 "")."""
    cells = list(cells) + [""] * (len(header) - len(cells))
    return collections.OrderedDict((h, cells[i] if isinstance(cells[i], str) else "") for i, h in enumerate(header))


def sheet_rows(doc, sheet):
    """시트의 데이터 행 [(행 번호, 칸 리스트)]. 빈 행은 뺀다. 행 번호는 목록 index + 2(머리글이 1행)."""
    header = REJECTED_HEADER if sheet == "rejected" else HEADERS[sheet]
    items = (doc or {}).get(sheet)
    if not isinstance(items, list):
        return None
    out = []
    for i, obj in enumerate(items):
        if isinstance(obj, dict):
            cells = row_cells(obj, header)
            if any(c != "" for c in cells):
                out.append((i + 2, cells))
    return out


class _Parser(object):
    def __init__(self, doc):
        self.doc = doc
        self.tax = Taxonomy()
        self.errors = []

    def error(self, sheet, row, code, message):
        self.errors.append(Issue(sheet, row, code, message))

    def warn(self, sheet, row, code, message):
        self.tax.warnings.append(Issue(sheet, row, code, message))

    def run(self):
        if not isinstance(self.doc, dict):
            self.error(None, None, "TAXONOMY_JSON_INVALID", "최상위가 객체가 아니다")
            return
        sheets = {}
        for name, header in HEADERS.items():
            sheets[name] = self._load(name, header)
        self._taxonomy(sheets["taxonomy"])
        self._questions(sheets["questions"])
        self._synonyms(sheets["synonyms"])
        self._rejected(self._load_list("rejected", REJECTED_HEADER))

    def _load_list(self, name, header):
        """행 객체 목록을 [(행 번호, 정의 열 칸)]으로 바꾼다. 형식 오류는 모아 둔다. 반환: (행들, 해시 입력)."""
        items = self.doc.get(name)
        if items is None:
            return None
        if not isinstance(items, list):
            self.error(name, None, "TAXONOMY_JSON_INVALID", "행 목록이 아니다")
            return None
        rows, extra_row = [], None
        for i, obj in enumerate(items):
            number = i + 2
            if not isinstance(obj, dict):
                self.error(name, number, "TAXONOMY_JSON_INVALID", "행이 객체가 아니다")
                continue
            if extra_row is None and any(k not in header for k in obj):
                extra_row = number
            bad = [h for h in header if obj.get(h) is not None and not isinstance(obj.get(h), str)]
            if bad:
                self.error(name, number, "TAXONOMY_JSON_INVALID", "칸 값은 문자열이어야 한다")
                continue
            defined = trim_cells([obj.get(h) or "" for h in header])
            if defined:
                rows.append((number, defined + [""] * (len(header) - len(defined))))
        if extra_row is not None:
            self.warn(name, extra_row, "EXTRA_COLUMNS", "정의 열이 아닌 키는 무시한다")
        return rows

    def _load(self, name, header):
        """시트를 찾아 해시를 낸다. 데이터 행 [(행 번호, 정의 열 칸)]을 돌려준다."""
        rows = self._load_list(name, header)
        if rows is None:
            self.tax.sheet_hashes[name] = EMPTY_SHEET_HASH
            if name not in self.doc:
                self.error(name, None, "SHEET_MISSING", "필수 시트(목록)가 없다. 기대 열: %s" % " | ".join(header))
            return []
        self.tax.sheet_hashes[name] = sheet_hash([list(header)] + [trim_cells(c) for _n, c in rows])
        return rows

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
        value_rows = []
        for number, c in rows:
            axis_name, value = c[0].strip(), c[1].strip()
            enabled = self._yn("taxonomy", number, c[10], "사용 여부", False) is not False
            if not axis_name:
                self.error("taxonomy", number, "AXIS_NOT_DEFINED", "축 열이 비어 있다")
                continue
            if value:
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
        seen = {}
        for number, c in rows:
            alias, canonical = c[0].strip(), c[1].strip()
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

    # --- rejected (보드의 '기각'이 채운다) ---
    def _rejected(self, rows):
        for number, c in rows or []:
            kind = c[0].strip()
            if kind not in REJECTED_KINDS:
                self.error("rejected", number, "REJECTED_KIND_INVALID", "종류는 %s 중 하나여야 한다" % "/".join(REJECTED_KINDS))
            self.tax.rejected.append(Rejected(kind, c[1], c[2].strip(), c[3], number))


def trim_cells(cells):
    """뒤쪽 빈 칸을 자른다(시트 해시 입력 규칙)."""
    cells = list(cells)
    while cells and cells[-1] == "":
        cells.pop()
    return cells


# ---- 예전 taxonomy.xlsx → doc (1회 변환 전용) ------------------------------------------

def xlsx_to_doc(b):
    """taxonomy.xlsx bytes → (doc, 오류 [Issue], 경고 [Issue]). 행은 예전 파서와 같이 정의 열만 자르고 빈 행을 뺀다.
    files·queries 시트는 버리고 rejected 시트는 rejected 목록으로 옮긴다. 오류가 있어도 읽은 만큼 doc를 만든다
    (검증은 parse_doc이 따로 한다). 워크북 자체를 못 읽으면 (None, [오류], [])."""
    try:
        wb = xlsx.read_workbook(b)
    except xlsx.XlsxError as e:
        return None, [Issue(None, None, e.code, e.message)], []
    doc, errors, warnings = empty_doc(), [], []
    sheets = list(HEADERS.items()) + [("rejected", REJECTED_HEADER[:4])]
    for name, header in sheets:
        width = len(header)
        try:
            sheet, case_mismatch = wb.find(name)
        except xlsx.XlsxError as e:
            errors.append(Issue(name, None, e.code, e.message))
            continue
        if sheet is None:
            if name != "rejected":
                errors.append(Issue(name, None, "SHEET_MISSING", "필수 시트가 없다"))
            continue
        if case_mismatch:
            warnings.append(Issue(name, None, "SHEET_NAME_CASE", "시트 이름의 대소문자가 다르다. 찾아서 읽는다"))
        errors.extend(sheet.errors)
        warnings.extend(sheet.warnings)
        if trim_cells(sheet.row(1)[:width]) != header:
            errors.append(Issue(name, 1, "HEADER_MISMATCH", "머리글이 다르다. 기대 머리글: %s" % " | ".join(header)))
            continue
        extra_row = next((n for n, cells in sheet.iter_rows() if any(c != "" for c in cells[width:])), None)
        if extra_row is not None:
            warnings.append(Issue(name, extra_row, "EXTRA_COLUMNS", "정의 열 오른쪽에 추가한 열은 버린다"))
        out_header = REJECTED_HEADER if name == "rejected" else header
        for number, cells in sheet.iter_rows(2):
            defined = trim_cells(cells[:width])
            if not defined:
                continue
            defined = defined + [""] * (width - len(defined))
            for col in range(width):
                if (number, col) in sheet.numeric:
                    if name == "rejected" and col == 2:
                        defined[col] = xlsx.serial_to_date(defined[col], wb.date1904) or defined[col]
                    elif name in ("taxonomy", "synonyms") and col in (0, 1):
                        warnings.append(Issue(name, number, "NUMERIC_CELL", "숫자 셀이다(Excel 자동 변환 의심)"))
            doc[name].append(row_obj(defined, out_header))
    return doc, errors, warnings


# ---- 읽기·저장·미리보기 ------------------------------------------------------------

def doc_version(b):
    return util.sha256_bytes(b)


def dump_doc(doc):
    """doc → 저장 문자열. 행 하나를 한 줄로 써 diff가 행 단위로 보인다. 키는 열 순서를 지킨다."""
    lines = ["{", '  "version": %d,' % int(doc.get("version") or DOC_VERSION)]
    names = list(HEADERS) + ["rejected"]
    for i, name in enumerate(names):
        header = REJECTED_HEADER if name == "rejected" else HEADERS[name]
        rows = [row_obj(row_cells(r, header), header) for r in doc.get(name) or [] if isinstance(r, dict)]
        tail = "," if i < len(names) - 1 else ""
        if not rows:
            lines.append('  "%s": []%s' % (name, tail))
            continue
        lines.append('  "%s": [' % name)
        for j, r in enumerate(rows):
            lines.append("    " + json.dumps(r, ensure_ascii=False) + ("," if j < len(rows) - 1 else ""))
        lines.append("  ]" + tail)
    lines.append("}")
    return "\n".join(lines) + "\n"


def normalize_doc(doc):
    """저장 형식으로 맞춘 doc(키·열 순서, 모자란 칸 채움, 객체가 아닌 행 버림)."""
    return json.loads(dump_doc(doc))


def load_doc(path):
    """taxonomy.json → (doc, 버전, bytes). 읽기는 ingest.read_input(사람 입력을 여는 유일한 함수)으로 한다."""
    from labelbot import ingest

    b = ingest.read_input(path, None)
    return decode_doc(b), doc_version(b), b


LOCK_STALE_SEC = 30.0
LOCK_WAIT_SEC = 5.0


class _FileLock(object):
    """보드·편집기 서버(다른 프로세스)가 같은 taxonomy.json을 동시에 저장하지 못하게 하는 잠금 파일."""

    def __init__(self, path):
        self.path = os.path.join(os.path.dirname(os.path.abspath(path)), "." + os.path.basename(path) + ".lock.json")

    def __enter__(self):
        import time

        end = time.monotonic() + LOCK_WAIT_SEC
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                return self
            except (FileExistsError, PermissionError):   # Windows: 지우는 중인 잠금 파일은 PermissionError
                try:
                    if time.time() - os.path.getmtime(self.path) > LOCK_STALE_SEC:
                        # 죽은 서버가 남긴 잠금. 고유 이름으로 옮기는 데 성공한 쪽만 지운다(둘이 동시에 지우지 않는다).
                        gone = "%s.%s.stale.json" % (self.path, uuid.uuid4().hex)
                        os.replace(self.path, gone)
                        os.remove(gone)
                        continue
                except OSError:
                    continue
                if time.monotonic() > end:
                    raise TaxonomyConflict()
                time.sleep(0.05)

    def __exit__(self, *exc):
        try:
            os.remove(self.path)
        except OSError:
            pass


def save_doc(path, doc, base_version, by, history_path=None, now=None):
    """doc를 원자적으로 저장한다. 반환: 새 버전.

    1) 지금 파일 버전이 base_version과 다르면 TaxonomyConflict(사이에 다른 화면이 저장했다).
    2) parse_doc 검증이 실패하면 TaxonomyError(파일은 그대로).
    3) 바꾸기 전 문서를 이력(taxonomy_history.jsonl)에 한 줄 더한다.
    4) tmp에 쓰고 os.replace로 바꾼다."""
    with _FileLock(path):
        return _save_locked(path, doc, base_version, by, history_path, now)


def _save_locked(path, doc, base_version, by, history_path, now):
    from labelbot import ingest

    old_b = ingest.read_input(path, None) if os.path.isfile(path) else None
    old_version = doc_version(old_b) if old_b is not None else None
    if old_version != base_version:
        raise TaxonomyConflict()
    text = dump_doc(doc)
    parse_doc(json.loads(text))
    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".", suffix=".tmp.json",
                               dir=os.path.dirname(os.path.abspath(path)))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        if old_b is not None:   # 새 내용을 다 쓴 뒤에 이력을 남기고 바로 교체한다
            hist = history_path or os.path.join(os.path.dirname(os.path.abspath(path)), HISTORY_NAME)
            util.check_ext(hist)
            rec = {"at": now or util.now_iso(), "by": by, "version": old_version,
                   "doc": json.loads(old_b.decode("utf-8-sig"))}
            with open(hist, "a", encoding="utf-8", newline="\n") as f:
                f.write(util.dumps(rec) + "\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return util.sha256_text(text)


def diff_docs(old, new):
    """두 doc의 행 변경 [{"sheet", "op": add|edit|delete, "row", "before", "after"}].
    row는 delete·edit이면 예전 행 번호, add면 새 행 번호다. before·after는 열 이름 → 문자열."""
    out = []
    for name in list(HEADERS) + ["rejected"]:
        header = REJECTED_HEADER if name == "rejected" else HEADERS[name]
        a = [tuple(row_cells(r, header)) for r in (old or {}).get(name) or [] if isinstance(r, dict)]
        b = [tuple(row_cells(r, header)) for r in (new or {}).get(name) or [] if isinstance(r, dict)]
        sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                continue
            pairs = min(i2 - i1, j2 - j1) if tag == "replace" else 0
            for k in range(pairs):
                out.append({"sheet": name, "op": "edit", "row": i1 + k + 2,
                            "before": dict(row_obj(a[i1 + k], header)), "after": dict(row_obj(b[j1 + k], header))})
            for i in range(i1 + pairs, i2):
                out.append({"sheet": name, "op": "delete", "row": i + 2, "before": dict(row_obj(a[i], header)),
                            "after": None})
            for j in range(j1 + pairs, j2):
                out.append({"sheet": name, "op": "add", "row": j + 2, "before": None,
                            "after": dict(row_obj(b[j], header))})
    return out
