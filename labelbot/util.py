"""공통 유틸: 해시, 정규화, JSON, 시각, 실행 ID."""
import datetime
import hashlib
import json
import os
import re
import secrets
import unicodedata

_WS = re.compile(r"\s+")
_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−－﹣"), "-")


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_text(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def nfc(s):
    return unicodedata.normalize("NFC", s or "")


def nfkc(s):
    return unicodedata.normalize("NFKC", s or "")


def canonical_json(obj):
    """키 정렬, 구분자 고정, ensure_ascii=False. 해시 입력용."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def hash_obj(obj):
    return sha256_text(canonical_json(obj))


def text_hash(text):
    return sha256_text(nfc(text))


def dup_hash(text):
    return sha256_text(_WS.sub(" ", nfc(text)).strip().lower())


def norm_for_match(s):
    """인용 비교용 정규화: NFKC, 대시 통일, 공백 축약, 소문자. NFKC가 µ(U+00B5)를 μ(U+03BC)로 바꾼다."""
    s = nfkc(s).translate(_DASHES)
    return _WS.sub(" ", s).strip().lower()


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_run_id():
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S")
    return "%s-%s" % (ts, secrets.token_hex(2))


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False)


def write_text(path, text):
    """허용 확장자만 쓴다(CLAUDE.md 쓰기 규칙)."""
    check_ext(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def write_jsonl(path, rows):
    write_text(path, "".join(dumps(r) + "\n" for r in rows))


ALLOWED_EXT = (".b64", ".sqlite", ".json", ".jsonl", ".html", ".md", ".log")


def check_ext(path):
    low = path.lower()
    if not low.endswith(ALLOWED_EXT):
        raise ValueError("FORBIDDEN_EXTENSION")
