"""L1 포맷 정규화기(AUTO_FIX 허용 목록). 목록은 코드에 있고 설정으로 늘릴 수 없다(5.2절).

동의어 치환, 가장 가까운 값으로 맞추기, 모호한 날짜 해석은 하지 않는다.
각 함수는 고친 값이 허용 집합·패턴에 들어갈 때만 바꾼 값을 돌려준다. 못 고치면 원래 값과 빈 규칙 목록이다.
"""
import datetime
import re

_WS = re.compile(r"\s+")
_FULL_DATE = re.compile(r"^(\d{4})\s*(?:[.\-/]|년)\s*(\d{1,2})\s*(?:[.\-/]|월)\s*(\d{1,2})\s*일?\.?$")
_YEAR_MONTH = re.compile(r"^(\d{4})\s*(?:[.\-/]|년)\s*(\d{1,2})\s*월?\.?$")
_ISO_FULL = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_MONTH = re.compile(r"^\d{4}-\d{2}$")


def strip_ws(s):
    return _WS.sub(" ", s).strip()


def nfkc_ascii(s):
    """전각 영숫자·기호(U+FF01~FF5E)와 전각 공백만 반각으로."""
    out = []
    for ch in s:
        o = ord(ch)
        if 0xFF01 <= o <= 0xFF5E:
            out.append(chr(o - 0xFEE0))
        elif o == 0x3000:
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


def enum_case(s, allowed):
    for a in allowed:
        if a.lower() == s.lower():
            return a
    return s


def taxonomy_case(s, axis, tax):
    return tax.canonical_value(axis, s) or s


def date_iso(s):
    """연월일 순서가 확정되는 날짜만 ISO로. 못 고치면 원래 값."""
    if _ISO_FULL.match(s) or _ISO_MONTH.match(s):
        return s
    m = _FULL_DATE.match(s)
    if m:
        try:
            return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            return s
    m = _YEAR_MONTH.match(s)
    if m and 1 <= int(m.group(2)) <= 12:
        return "%s-%02d" % (m.group(1), int(m.group(2)))
    return s


def pattern_case(s, pattern):
    """패턴 필드의 대소문자·공백만 맞춘다. 원래 값, 대문자, 첫 글자만 대문자 순으로 맞는 것을 쓴다."""
    nows = _WS.sub("", s)
    for cand in (nows, nows.upper(), nows[:1].upper() + nows[1:].lower()):
        if re.fullmatch(pattern, cand):
            return cand
    return s


RULES = ("strip_ws", "nfkc_ascii", "enum_case", "taxonomy_case", "date_iso", "pattern_case")


def _chain(value, steps, valid):
    """steps: [(규칙 이름, 함수)]. 최종 값이 valid일 때만 (값, 바뀐 규칙들)을 돌려준다."""
    if not isinstance(value, str) or valid(value):
        return value, []
    cur, used = value, []
    for name, fn in steps:
        nxt = fn(cur)
        if nxt != cur:
            used.append(name)
            cur = nxt
    if used and valid(cur):
        return cur, used
    return value, []


def _base_steps():
    return [("strip_ws", strip_ws), ("nfkc_ascii", nfkc_ascii)]


def enum_value(value, allowed):
    allowed = list(allowed)
    return _chain(value, _base_steps() + [("enum_case", lambda s: enum_case(s, allowed))], lambda s: s in allowed)


def axis_value(axis, value, tax):
    def valid(s):
        return tax.canonical_value(axis, s) == s

    return _chain(value, _base_steps() + [("taxonomy_case", lambda s: taxonomy_case(s, axis, tax))], valid)


def date_value(value, pattern):
    return _chain(value, _base_steps() + [("date_iso", date_iso)], lambda s: bool(re.fullmatch(pattern, s)))


def pattern_value(value, pattern):
    return _chain(value, _base_steps() + [("pattern_case", lambda s: pattern_case(s, pattern))],
                  lambda s: bool(re.fullmatch(pattern, s)))


def text_value(value):
    return _chain(value, [("strip_ws", strip_ws)], lambda s: s == strip_ws(s))


def fix_entry(field, before, after, rules):
    return {"field": field, "before": before, "after": after, "rule": "+".join(rules), "rules": list(rules)}


def rules_of(fix):
    return fix.get("rules") or fix["rule"].split("+")


def is_approved(fix, approved):
    return all(r in approved for r in rules_of(fix))
