"""chunk 텍스트 정리: 공백 정리, 항상 지울 문구, 파일 안 반복 문구(머리글·바닥글·고지) 제거."""
import re
import unicodedata

from labelbot import util

# 어느 chunk에도 남기지 않는 문구. 이 문구가 들어간 줄은 통째로 지운다.
ALWAYS_REMOVE = ("본 자료의 모든 데이터는 내부 테스트용 더미",)

# 반복 문구로 보려면 최소 이 수의 슬라이드에 나와야 한다.
BOILERPLATE_MIN_SLIDES = 3

# 이보다 짧은 노트는 버린다.
NOTE_MIN_CHARS = 10

_HSPACE = re.compile(r"[ \t  -​　]+")
_WS = re.compile(r"\s+")
_ALWAYS_KEYS = tuple(_WS.sub("", util.nfc(p)) for p in ALWAYS_REMOVE)


def clean_line(s):
    """NFC, 가로 공백 축약, 앞뒤 공백 제거. 세로 탭(a:br 대체 문자)은 공백으로 본다."""
    s = util.nfc(s).replace("\x0b", " ")
    return _HSPACE.sub(" ", s).strip()


def line_key(s):
    """반복 판정용 키: 모든 공백 축약."""
    return _WS.sub(" ", util.nfc(s)).strip()


def is_always_removed(s):
    compact = _WS.sub("", util.nfc(s))
    return any(k in compact for k in _ALWAYS_KEYS)


def keep_line(s):
    return bool(s) and not is_always_removed(s)


def boilerplate_keys(slides_lines, ratio):
    """슬라이드별 줄 목록에서, ratio 이상 슬라이드(최소 3장)에 반복되는 줄의 키 집합."""
    n = len(slides_lines)
    need = max(BOILERPLATE_MIN_SLIDES, ratio * n)
    counts = {}
    for lines in slides_lines:
        for k in set(line_key(s) for s in lines if s.strip()):
            counts[k] = counts.get(k, 0) + 1
    return set(k for k, c in counts.items() if c >= need)


def _is_meaningful_char(ch):
    cat = unicodedata.category(ch)
    return not (cat.startswith("N") or cat.startswith("P") or cat.startswith("S") or cat.startswith("Z"))


def is_trivial_note(text):
    """숫자·문장부호뿐이거나 매우 짧은 노트."""
    t = _WS.sub("", util.nfc(text))
    if len(t) < NOTE_MIN_CHARS:
        return True
    return not any(_is_meaningful_char(ch) for ch in t)


# ---------------------------------------------------------------- chunk 텍스트 조립(PRD 7.1)

TABLE_ROW_CAPS = (20, 10, 5, 2)
_DIGIT = re.compile(r"\d")


def _numeric_line(s):
    chars = [ch for ch in s if not ch.isspace()]
    return bool(chars) and len(_DIGIT.findall(s)) >= 0.5 * len(chars)


def render_chunk(title, blocks, charts=(), notes="", row_cap=None, drop_numeric=False):
    """'# 제목', 본문 블록(("lines", [str]) 또는 ("table", [[셀]])), [차트], [노트] 순서로 조립한다."""
    lines = ["# " + title if title else "#"]
    for kind, payload in blocks:
        if kind == "lines":
            lines.extend(x for x in payload if not (drop_numeric and _numeric_line(x)))
            continue
        rows = payload
        if row_cap and len(rows) > row_cap:
            rows = rows[:row_cap] + [["(%d행 생략)" % (len(payload) - row_cap)]]
        lines.append("[표]")
        lines.extend(" | ".join(r) for r in rows)
    for ch in charts:
        lines.extend(["", "[차트]"])
        if ch["title"]:
            lines.append("제목: " + ch["title"])
        if ch["series"]:
            lines.append("계열: " + ", ".join(ch["series"]))
        if ch["categories"]:
            lines.append("범주: " + ", ".join(ch["categories"]))
    if notes:
        lines.extend(["", "[노트]"])
        lines.extend(notes.split("\n"))
    return "\n".join(lines)


def fit_chunk(title, blocks, charts, notes, limit):
    """한도를 넘으면 표 행 → 숫자 나열 → 노트 순서로 줄이고, 그래도 넘으면 자른다. 반환: (텍스트, 줄였는지)."""
    text = render_chunk(title, blocks, charts, notes)
    if not limit or len(text) <= limit:
        return text, False
    for cap in TABLE_ROW_CAPS:
        text = render_chunk(title, blocks, charts, notes, row_cap=cap)
        if len(text) <= limit:
            return text, True
    cap = TABLE_ROW_CAPS[-1]
    text = render_chunk(title, blocks, charts, notes, row_cap=cap, drop_numeric=True)
    if len(text) > limit and notes:
        room = max(0, len(notes) - (len(text) - limit))
        text = render_chunk(title, blocks, charts, notes[:room].rstrip(), row_cap=cap, drop_numeric=True)
    return text[:limit], True
