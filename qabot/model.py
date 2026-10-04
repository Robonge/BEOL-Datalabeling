"""중립 계약(4절): Issue, Verdict, 입력 번들, taxonomy 색인. labelbot을 import하지 않는다."""
import copy
import datetime
import hashlib
import json
import re
import secrets
import unicodedata

LAYERS = ("L0", "L1", "L2", "L3A", "L3B", "L4", "L5", "L6")
SEVERITIES = ("critical", "major", "fixable", "minor", "info")  # 높은 것부터
SEVERITY_RANK = {s: i for i, s in enumerate(reversed(SEVERITIES))}  # info=0 … critical=4
VERDICTS = ("REJECT", "REVIEW", "AUTO_FIX", "PASS")
DEFAULT_SEVERITY_TO_VERDICT = {"critical": "REJECT", "major": "REVIEW", "fixable": "AUTO_FIX",
                               "minor": "PASS", "info": "PASS"}
SCOPES = ("file", "record", "batch")

NA = "해당 없음"
UNKNOWN = "unknown"
RESERVED = (NA, UNKNOWN)

_WS = re.compile(r"\s+")


class BundleError(Exception):
    def __init__(self, reason_code, detail=None):
        Exception.__init__(self, reason_code if not detail else "%s: %s" % (reason_code, detail))
        self.reason_code = reason_code
        self.detail = detail


# ---- 공통 해시·정규화 -----------------------------------------------------

def sha256_text(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def canonical_json(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def hash_obj(obj):
    return sha256_text(canonical_json(obj))


def nfc(s):
    return unicodedata.normalize("NFC", s or "")


def nfkc(s):
    return unicodedata.normalize("NFKC", s or "")


def norm_key(s):
    """같은 값 판정용: NFKC, 소문자, 공백 제거(labelbot taxonomy.norm_key와 같은 뜻)."""
    return _WS.sub("", nfkc(s)).lower()


def new_qa_run_id():
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S")
    return "QA-%s-%s" % (ts, secrets.token_hex(2))


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- Issue ---------------------------------------------------------------

def issue(code, field=None, evidence=None, reason=None, suggested_fix=None, severity=None, record_id=None):
    """카탈로그에서 층·기본 severity·범위를 채운다. record_id는 file 범위 검사가 레코드 이슈를 낼 때만 쓴다."""
    from qabot import codes

    c = codes.get(code)
    sev = severity or c["severity"]
    if sev not in codes.allowed_severities(code):
        raise ValueError("SEVERITY_NOT_ALLOWED:%s:%s" % (code, sev))
    out = {
        "code": code,
        "layer": c["layer"],
        "severity": sev,
        "scope": c["scope"],
        "field": field,
        "evidence": evidence or {},
        "reason": reason or c["desc"],
        "suggested_fix": suggested_fix,
        "auto_fixed": code == "L1_FORMAT_NORMALIZED",
    }
    if record_id is not None:
        out["record_id"] = record_id
    return out


def issue_sort_key(i):
    return (LAYERS.index(i["layer"]) if i["layer"] in LAYERS else 99, i["code"], i.get("field") or "",
            canonical_json(i.get("evidence") or {}))


def max_severity(issues):
    best = None
    for i in issues:
        if best is None or SEVERITY_RANK[i["severity"]] > SEVERITY_RANK[best]:
            best = i["severity"]
    return best


def decide(issues, policy):
    """가장 높은 severity로 판정한다(6.1절). 점수는 정렬용이다."""
    vc = policy["verdict"]
    sev = max_severity(issues)
    verdict = vc["severity_to_verdict"][sev] if sev else "PASS"
    weights = vc["score_weights"]
    score = max(0, 100 - sum(weights.get(i["severity"], 0) for i in issues))
    return verdict, score


# ---- taxonomy 색인 --------------------------------------------------------

class TaxIndex(object):
    """taxonomy 스냅샷(dict) 조회용."""

    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.version = snapshot.get("version")
        reserved = snapshot.get("reserved") or {}
        self.na = reserved.get("na", NA)
        self.unknown = reserved.get("unknown", UNKNOWN)
        self.axes = {a["name"]: a for a in snapshot.get("axes") or []}
        self.values = {}   # 축 → {값 이름: 값 dict}
        self.value_keys = {}  # 축 → {norm_key: 표준 표기}
        for a in self.axes.values():
            vals = {v["name"]: v for v in a.get("values") or []}
            self.values[a["name"]] = vals
            self.value_keys[a["name"]] = {norm_key(n): n for n in vals}
        self.questions = {q["qid"]: q for q in snapshot.get("questions") or []}
        self.synonyms = list(snapshot.get("synonyms") or [])

    def active_axes(self):
        return [a for a in self.axes.values() if a.get("active")]

    def classification_axes(self):
        return [a for a in self.active_axes() if a.get("kind", "분류") == "분류"]

    def is_reserved(self, v):
        return v in (self.na, self.unknown)

    def canonical_value(self, axis, v):
        """NFKC·대소문자·공백만 다른 표기를 표준 표기로. 없으면 None."""
        k = norm_key(v)
        if k == norm_key(self.na):
            return self.na
        if k == norm_key(self.unknown):
            return self.unknown
        return self.value_keys.get(axis, {}).get(k)

    def definition(self, axis, v):
        val = self.values.get(axis, {}).get(v)
        return (val or {}).get("definition") or ""

    def synonyms_for(self, canonical):
        return [s["alias"] for s in self.synonyms if s.get("canonical") == canonical]


# ---- 번들 ----------------------------------------------------------------

class Bundle(object):
    """adapter가 만드는 입력 번들.

    sources: {file_id: SourceRef}, units: {unit_id: ParsedUnit}, records: [LabelRecord], taxonomy: 스냅샷 dict.
    loader: source_bytes(SourceRef dict) → bytes, image_bytes(이미지 dict) → bytes. 실패하면 LoaderError.
    meta: 화면용 파일 표시 이름(file_names), 사람 교정(corrections) 등. 리포트에는 넣지 않는다.
    """

    def __init__(self, labeler_run_id, sources, units, records, taxonomy, loader=None, meta=None):
        self.labeler_run_id = labeler_run_id
        self.sources = sources
        self.units = units
        self.records = records
        self.taxonomy = taxonomy
        self.loader = loader
        self.meta = meta or {}

    def units_of(self, file_id):
        return sorted((u for u in self.units.values() if u["file_id"] == file_id), key=lambda u: (u["seq"], u["unit_id"]))

    def records_of(self, file_id):
        return [r for r in self.records if r.get("file_id") == file_id]

    def subset(self, file_ids):
        fids = set(file_ids)
        return Bundle(
            self.labeler_run_id,
            {k: v for k, v in self.sources.items() if k in fids},
            {k: v for k, v in self.units.items() if v["file_id"] in fids},
            [r for r in self.records if r.get("file_id") in fids],
            self.taxonomy, self.loader, self.meta,
        )

    def copy(self):
        return Bundle(self.labeler_run_id, copy.deepcopy(self.sources), copy.deepcopy(self.units),
                      copy.deepcopy(self.records), self.taxonomy, self.loader, self.meta)

    def fingerprint(self):
        """정렬한 (레코드 ID, text_hash, 라벨 내용 해시) 목록의 해시(6.5절)."""
        rows = sorted((r["record_id"], (self.units.get(r["record_id"]) or {}).get("text_hash"), label_hash(r))
                      for r in self.records)
        return hash_obj(rows)


class LoaderError(Exception):
    def __init__(self, reason_code):
        Exception.__init__(self, reason_code)
        self.reason_code = reason_code


def label_hash(record):
    """라벨 내용 해시. 생성 시각처럼 실행마다 바뀌는 값은 뺀다."""
    keep = {k: v for k, v in record.items() if k not in ("labeler", "human_reviewed")}
    lab = dict(record.get("labeler") or {})
    lab.pop("created_at", None)
    keep["labeler"] = lab
    return hash_obj(keep)


def check_bundle(bundle):
    """adapter 출력의 최소 구조 확인. 어긋나면 BundleError."""
    if not isinstance(bundle.taxonomy, dict) or "axes" not in bundle.taxonomy:
        raise BundleError("BUNDLE_TAXONOMY_INVALID")
    seen = set()
    for r in bundle.records:
        rid = r.get("record_id")
        if not rid or rid in seen:
            raise BundleError("BUNDLE_RECORD_ID_INVALID", rid)
        seen.add(rid)
        if rid not in bundle.units:
            raise BundleError("BUNDLE_UNIT_MISSING", rid)
        if r.get("file_id") != bundle.units[rid]["file_id"]:
            raise BundleError("BUNDLE_FILE_MISMATCH", rid)
    for u in bundle.units.values():
        if u["file_id"] not in bundle.sources:
            raise BundleError("BUNDLE_SOURCE_MISSING", u["file_id"][:16])
