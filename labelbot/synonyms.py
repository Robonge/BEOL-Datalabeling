"""동의어 치환(PRD 6.2).

본문과 시트 항목을 NFKC·소문자로 대조하고, 한 번에 긴 키부터 치환한다.
표준어가 이미 적힌 구간은 보호하므로 `bridge→metal bridge`가 "metal metal bridge"를 만들지 않는다.
ASCII 영숫자로 시작·끝나는 키는 붙은 글자가 ASCII 영문자면 일치로 보지 않고(`BM`이 "RSBM"에 맞지 않는다),
숫자로 시작·끝나는 키는 붙은 글자가 숫자면 일치로 보지 않는다(`Via1`이 "Via12"에 맞지 않는다).
"""
from labelbot import util


def _is_ascii_letter(ch):
    return "a" <= ch <= "z" or "A" <= ch <= "Z"


def _is_ascii_alnum(ch):
    return _is_ascii_letter(ch) or "0" <= ch <= "9"


def _is_digit(ch):
    return "0" <= ch <= "9"


def _blocked(key_ch, neighbor):
    if not neighbor:
        return False
    if _is_ascii_alnum(key_ch) and _is_ascii_letter(neighbor):
        return True
    return _is_digit(key_ch) and _is_digit(neighbor)


def _lower_same_length(text):
    """글자 수가 바뀌는 소문자 변환(예: 'İ')은 원래 글자를 둬서 위치를 맞춘다."""
    out = []
    for ch in text:
        low = ch.lower()
        out.append(low if len(low) == 1 else ch)
    return "".join(out)


def _key(s):
    return _lower_same_length(util.nfkc(s).strip())


class SynonymTable(object):
    def __init__(self, synonyms):
        """synonyms: taxonomy.Synonym 목록 또는 (동의어, 표준어, ...) 튜플. 같은 동의어는 첫 항목을 쓴다."""
        self.entries = {}  # 키 → (동의어, 표준어)
        self.canonical_keys = set()
        for s in synonyms:
            alias, canonical = s[0], s[1]
            key = _key(alias)
            if not key or key in self.entries:
                continue
            self.entries[key] = (alias, canonical)
            self.canonical_keys.add(_key(canonical))
        self.canonical_keys.discard("")

    def _find(self, low, key):
        start = low.find(key)
        while start >= 0:
            end = start + len(key)
            before = low[start - 1] if start > 0 else ""
            after = low[end] if end < len(low) else ""
            if not _blocked(key[0], before) and not _blocked(key[-1], after):
                yield start, end
            start = low.find(key, start + 1)

    def _select(self, text):
        """겹치지 않는 일치 구간 [(시작, 끝, 동의어 키 또는 None)]. 길이가 같으면 표준어 보호가 먼저다."""
        low = _lower_same_length(text)
        candidates = []
        for key in self.canonical_keys:
            for start, end in self._find(low, key):
                candidates.append((-(end - start), start, 0, end, None))
        for key in self.entries:
            for start, end in self._find(low, key):
                candidates.append((-(end - start), start, 1, end, key))
        candidates.sort(key=lambda c: c[:3])
        taken = []
        for _, start, _, end, key in candidates:
            if all(end <= s or start >= e for s, e, _ in taken):
                taken.append((start, end, key))
        return sorted(taken)

    def apply(self, text):
        """(치환한 NFKC 본문, 일치 목록). 일치 목록은 처음 나온 순서의 고유한 (동의어, 표준어)다."""
        text = util.nfkc(text)
        out = []
        matches = []
        pos = 0
        for start, end, key in self._select(text):
            if key is None:
                continue
            alias, canonical = self.entries[key]
            out.append(text[pos:start])
            out.append(util.nfkc(canonical))
            pos = end
            if (alias, canonical) not in matches:
                matches.append((alias, canonical))
        out.append(text[pos:])
        return "".join(out), matches

    def match(self, text):
        return self.apply(text)[1]
