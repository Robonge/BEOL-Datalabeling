"""인용 매칭(5.4절). labelbot review.quote_found와 같은 뜻이지만 구현은 따로 둔다.

단계: 정확 일치 → 정규화 일치(NFKC, 대시 통일, 표 구분자·줄바꿈을 공백으로, 공백 축약, 소문자) → 생략 인용("A … B").
줄바꿈으로 나뉜 인용은 줄마다 따로 본문에 있어야 일치한다.
"""
import re
import unicodedata

_WS = re.compile(r"\s+")
_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−－﹣"), "-")
_ELLIPSIS = re.compile(r"\s*(?:…|\.{3,})\s*")
_HANGUL = re.compile(r"[가-힣]")
_ALNUM = re.compile(r"[0-9A-Za-z]")

TIERS = ("offset", "exact", "normalized", "ellipsis")


def norm(s):
    s = unicodedata.normalize("NFKC", s or "").translate(_DASHES).replace("|", " ")
    return _WS.sub(" ", s).strip().lower()


def _ellipsis_parts(quote):
    return [norm(p) for p in _ELLIPSIS.split(quote) if p.strip()]


def _match_line(line, text):
    if line in text:
        return "exact"
    q = norm(line)
    if not q:
        return "exact"
    hay = norm(text)
    if q in hay:
        return "normalized"
    parts = _ellipsis_parts(line)
    if len(parts) > 1:
        pos = 0
        for p in parts:
            i = hay.find(p, pos)
            if i < 0:
                return None
            pos = i + len(p)
        return "ellipsis"
    return None


def match(quote, text):
    """반환: 일치 단계("exact", "normalized", "ellipsis") 또는 None."""
    if not text:
        return None
    if quote in text:
        return "exact"
    lines = [l for l in quote.splitlines() if l.strip()]
    if len(lines) > 1:
        tiers = [_match_line(l, text) for l in lines]
        if any(t is None for t in tiers):
            return None
        return max(tiers, key=TIERS.index)
    return _match_line(quote, text)


def find(quote, texts):
    """texts 중 처음 일치하는 것. 반환: (단계, 인덱스) 또는 (None, None)."""
    for i, t in enumerate(texts):
        tier = match(quote, t)
        if tier:
            return tier, i
    return None, None


def check_offset(text, start, end, quote):
    """offset 검사. 맞으면 None, 아니면 사유 코드."""
    if not isinstance(start, int) or not isinstance(end, int) or isinstance(start, bool) or isinstance(end, bool):
        return "OFFSET_TYPE"
    if start < 0 or end > len(text):
        return "OFFSET_OUT_OF_RANGE"
    if start >= end:
        return "OFFSET_EMPTY"
    if text[start:end] != quote:
        return "OFFSET_TEXT_MISMATCH"
    return None


def is_short(quote, hangul_max=2, alnum_max=4):
    q = unicodedata.normalize("NFKC", quote or "")
    return len(_HANGUL.findall(q)) <= hangul_max and len(_ALNUM.findall(q)) <= alnum_max


def is_long(quote, text, chars=300, ratio=0.8):
    return len(quote) > chars and len(quote) > ratio * max(1, len(text or ""))
