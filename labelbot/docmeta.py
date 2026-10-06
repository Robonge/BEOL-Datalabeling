"""파일 단위 문서 metadata(Lot ID·WF#·날짜·작성자)를 슬라이드 텍스트에서 정규식으로 뽑는다.

LLM을 쓰지 않는다. 날짜·작성자는 슬라이드 제목·본문에서만 찾고, 파일명·docprops·처리일은 쓰지 않는다.
Lot ID는 본문을 먼저 보고, 본문에 없을 때만 파일명을 본다.
"""
import re

from labelbot import util
from labelbot.label import _FULL_DATE, normalize_date

WF_MIN, WF_MAX = 1, 25
AUTHOR_MAX = 40

_STRICT_BASE = r"(?:R[QXND][A-Z](?:[A-Z][0-9]|[0-9][A-Z]|[0-9]{2})[A-C]?|Q[A-Z]{4}0[0-9]{2})"
_LOOSE_BASE = r"[RQ][A-Z]{3,5}[0-9]{0,3}[A-C]?"
STRICT_LOT = re.compile(r"(?<![A-Z0-9])" + _STRICT_BASE + r"\.(?:1|6[1-9]|6[A-D])(?![A-Z0-9])")
LOOSE_LOT = re.compile(r"(?<![A-Z0-9])" + _LOOSE_BASE + r"\.(?:1|6[0-9A-F])(?![A-Z0-9])")
_WF_NUMS = r"(\d{1,2}(?:\s*[~\-,]\s*\d{1,2})*)(?!\d)"
# 접미사를 뗀 Lot 뒤에 밑줄+번호(예: RQMD6_8 = RQMD6.66의 WF 8). 밑줄이 있을 때만 인정한다.
BASE_WF = re.compile(r"(?<![A-Z0-9])(" + _LOOSE_BASE + "|" + _STRICT_BASE + r")_" + _WF_NUMS)
_STRICT_BASE_FULL = re.compile(_STRICT_BASE)
WF_AFTER_LOT = re.compile(r"\s*(?:_|#|W/?F\s*#?)\s*" + _WF_NUMS)
WF_ALONE = re.compile(r"(?<![A-Z0-9/])(?:W/?F\s*#?|#)\s*" + _WF_NUMS)
AUTHOR_KEY = re.compile(
    r"(?:자료\s*작성자?|작성자|작성|담당자?|prepared\s+by)\s*[:：]\s*([^\n\r]+)", re.IGNORECASE
)


def _norm(text):
    return util.nfkc(text or "").upper()


def _lot_matches(text):
    """반환: [(start, end, lot, match)] 위치 순. 엄격 regex 우선, 남은 구간만 느슨한 regex."""
    s = _norm(text)
    found = [(m.start(), m.end(), m.group(0), "strict") for m in STRICT_LOT.finditer(s)]
    taken = [(a, b) for a, b, _, _ in found]
    for m in LOOSE_LOT.finditer(s):
        if not any(a < m.end() and m.start() < b for a, b in taken):
            found.append((m.start(), m.end(), m.group(0), "similar"))
    return s, sorted(found)


def find_lots(text):
    """반환: [(lot, match)] 처음 나온 순서, 중복 제거."""
    out, seen = [], set()
    for _, _, lot, match in _lot_matches(text)[1]:
        if lot not in seen:
            seen.add(lot)
            out.append((lot, match))
    return out


def parse_wf(spec):
    """'1~5', '1-5', '1,3,5', '3'을 펼쳐 1~25만 남긴다."""
    nums = set()
    for part in re.split(r"\s*,\s*", spec.strip()):
        m = re.fullmatch(r"(\d{1,2})\s*[~\-]\s*(\d{1,2})", part)
        if m:
            a, b = sorted((int(m.group(1)), int(m.group(2))))
            nums.update(range(a, b + 1))
        elif part.isdigit():
            nums.add(int(part))
    return sorted(n for n in nums if WF_MIN <= n <= WF_MAX)


def find_wf(text):
    """반환: [(lot 또는 None, [WF 번호])]. Lot 바로 뒤 표기는 그 Lot에, 단독 표기는 None에 붙인다."""
    s, lots = _lot_matches(text)
    out, used = [], []
    for start, end, lot, _ in lots:
        m = WF_AFTER_LOT.match(s, end)
        if m:
            used.append((start, m.end()))
            nums = parse_wf(m.group(1))
            if nums:
                out.append((lot, nums))
    for m in WF_ALONE.finditer(s):
        if any(a <= m.start() < b for a, b in used):
            continue
        nums = parse_wf(m.group(1))
        if nums:
            out.append((None, nums))
    return out


def find_base_wf(text):
    """반환: [(접미사 없는 Lot, match, [WF 번호])]. 예: 'RQMD6_8' → ('RQMD6', 'strict', [8])."""
    out = []
    for m in BASE_WF.finditer(_norm(text)):
        nums = parse_wf(m.group(2))
        if nums:
            match = "strict" if _STRICT_BASE_FULL.fullmatch(m.group(1)) else "similar"
            out.append((m.group(1), match, nums))
    return out


def find_author(text):
    m = AUTHOR_KEY.search(util.nfkc(text or ""))
    if not m:
        return None
    val = m.group(1).strip().strip("|/·").strip()[:AUTHOR_MAX].strip()
    return val or None


# 키워드 없이 본문 마지막 줄에 '<영문·숫자 부서명> <한글 이름>'만 적는 서명(예: 'LogicTD 홍길동').
SIGNATURE = re.compile(r"[A-Za-z][A-Za-z0-9&/\-]{1,20}\s+[가-힣]{2,4}")


def find_signature(text):
    """[노트] 앞 본문의 마지막 비지 않은 줄이 서명 형태면 그 줄을 그대로 돌려준다."""
    lines = []
    for line in util.nfkc(text or "").splitlines():
        if line.startswith("[노트]"):
            break
        if line.strip():
            lines.append(line.strip())
    return lines[-1] if lines and SIGNATURE.fullmatch(lines[-1]) else None


def find_date(text):
    for m in _FULL_DATE.finditer(util.nfkc(text or "")):
        val, reason = normalize_date(m.group(0))
        if val and len(val) == 10 and not reason:
            return val
    return None


def extract_file_meta(units, file_name):
    """units: seq·title·text를 가진 chunk 목록. 반환: doc_meta dict(JSON으로 저장)."""
    texts = ["%s\n%s" % (u.get("title") or "", u.get("text") or "") for u in sorted(units, key=lambda u: u["seq"])]
    lots, source = [], "slide"
    for t in texts:
        lots += find_lots(t)
    wf_pairs = [p for t in texts for p in find_wf(t)]
    if not lots:
        lots, source = find_lots(file_name or ""), "filename"
        wf_pairs += find_wf(file_name or "")
    entries = {}
    for lot, match in lots:
        entries.setdefault(lot, {"lot": lot, "match": match, "source": source, "wf": set()})
    rep = lots[0][0] if lots else None
    for lot, nums in wf_pairs:
        key = lot or rep
        if key not in entries:  # Lot이 하나도 없을 때 단독 WF
            entries[key] = {"lot": key, "match": None, "source": "slide", "wf": set()}
        entries[key]["wf"].update(nums)
    for t in texts:
        for base, match, nums in find_base_wf(t):
            key = next((k for k in entries if k and k.split(".")[0] == base), base)
            entries.setdefault(key, {"lot": key, "match": match, "source": "slide", "wf": set()})["wf"].update(nums)
    date = next((d for d in map(find_date, texts) if d), None)
    author = next((a for a in map(find_author, texts) if a), None)
    if not author:  # 키워드 표기가 어디에도 없을 때만 마지막 줄 서명을 본다(제목 제외)
        bodies = [u.get("text") or "" for u in sorted(units, key=lambda u: u["seq"])]
        author = next((a for a in map(find_signature, bodies) if a), None)
    return {
        "lots": [dict(e, wf=sorted(e["wf"])) for e in entries.values()],
        "date": date,
        "date_source": "slide" if date else None,
        "author": author,
        "author_source": "slide" if author else None,
    }
