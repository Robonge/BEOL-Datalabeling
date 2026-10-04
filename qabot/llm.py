"""judge용 LLM adapter 인터페이스와 mock(7.1절). labelbot을 import하지 않는다.

- complete(messages, file_ids, hint)는 응답 본문 문자열을 돌려준다. 재시도는 judge.py가 한다.
- 실패는 LLMError(사유 코드)다. 보내기 전에 막힌 실패(전송 차단, 키 없음)는 sent=False이고 재시도하지 않는다.
"""
import json

from qabot import model

RISK = ("미확인", "추가 확인 필요", "후속 평가 필요", "미검증")
CLEAR = ("해소됨", "검증 완료", "추가 확인 불필요")


class LLMError(Exception):
    def __init__(self, reason_code, sent=True):
        Exception.__init__(self, reason_code)
        self.reason_code = reason_code
        self.sent = sent


def _ascii_alnum(ch):
    return bool(ch) and ch.isascii() and ch.isalnum()


def term_in(term, text):
    """NFKC·소문자로 term이 text에 있는지 본다. 영숫자 끝은 단어 경계를 지킨다("EM"은 "system"에 없다)."""
    t = model.nfkc(term).lower().strip()
    s = model.nfkc(text).lower()
    if not t:
        return False
    start = 0
    while True:
        i = s.find(t, start)
        if i < 0:
            return False
        before = s[i - 1] if i > 0 else ""
        after = s[i + len(t)] if i + len(t) < len(s) else ""
        if not (_ascii_alnum(t[0]) and _ascii_alnum(before)) and not (_ascii_alnum(t[-1]) and _ascii_alnum(after)):
            return True
        start = i + 1


class JudgeLLM(object):
    """judge adapter의 기반. name은 reviewer 버전에 들어간다."""

    name = "base"

    def complete(self, messages, file_ids, hint=None):
        raise NotImplementedError

    def request_identity(self, messages):
        """캐시 키에 넣을 요청 전체. HTTP 구현은 주소·모델·파라미터를 더한다."""
        return {"llm": type(self).__name__, "name": self.name, "messages": messages}

    def sent_params(self):
        return {"transport": self.name}


def judge_item(item):
    """mock 결정론 규칙. 반환: (verdict, reason)."""
    quote = item.get("quote") or ""
    if item.get("kind") == "axis":
        terms = [item.get("value") or ""] + list(item.get("aliases") or [])
        if any(term_in(t, quote) for t in terms if t):
            return "supported", "인용문에 라벨 값이나 그 동의어가 나온다."
        return "unsupported", "인용문에 라벨 값과 그 동의어가 나오지 않는다."
    if item.get("answer") == "O":
        if any(p in quote for p in RISK):
            return "supported", "인용문에 아직 해결되지 않은 위험을 밝히는 표현이 있다."
        return "unsupported", "인용문에 해결되지 않은 위험을 밝히는 표현이 없다."
    if item.get("answer") == "X":
        if any(p in quote for p in CLEAR):
            return "supported", "인용문에 위험이 해소됐다고 밝히는 표현이 있다."
        return "unsupported", "인용문에 위험이 해소됐다고 밝히는 표현이 없다."
    return "unsupported", "인용문으로 이 답을 확인할 수 없다."


class MockJudgeLLM(JudgeLLM):
    """개발·테스트용. responder(messages, file_ids, hint)를 주면 그 반환 문자열을 응답으로 쓴다(예외 주입 가능)."""

    name = "mock"

    def __init__(self, responder=None):
        self.responder = responder

    def complete(self, messages, file_ids, hint=None):
        if self.responder is not None:
            return self.responder(messages, file_ids, hint)
        if not hint or not isinstance(hint.get("items"), list):
            raise LLMError("MOCK_HINT_MISSING", sent=False)
        out = []
        for it in hint["items"]:
            verdict, reason = judge_item(it)
            out.append({"id": it["id"], "verdict": verdict, "reason": reason})
        return json.dumps({"items": out}, ensure_ascii=False)

    def sent_params(self):
        return {"transport": "mock", "model": self.name}
