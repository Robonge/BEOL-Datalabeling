"""결정적 mock LLM·임베딩. 배관 검증용이며 정확도를 흉내 내지 않는다.

단계가 넘기는 hint(작업 종류, 활성 축과 값, 매핑된 질문, 본문)로 응답을 만든다. 실제 요청 본문은 보지 않는다.
"""
import hashlib
import json
import struct


def _first_line_with(text, needle):
    low = needle.lower()
    for line in text.splitlines():
        if low in line.lower():
            return line.strip()[:200]
    return ""


class MockChatTransport:
    def __init__(self, responder=None):
        self.responder = responder
        self.requests = []

    def send(self, body, hint=None):
        self.requests.append(body)
        if self.responder:
            return self.responder(body, hint)
        hint = hint or {}
        if hint.get("task") == "classify":
            return json.dumps(self._classify(hint), ensure_ascii=False)
        if hint.get("task") == "question_gen":
            return json.dumps({"questions": [{"axis": a, "value": v, "text": "이 chunk는 %s=%s 라벨에 해당하는가?" % (a, v)}
                                             for a, v in hint["targets"]]}, ensure_ascii=False)
        if hint.get("task") == "label":
            return json.dumps(self._label(hint), ensure_ascii=False)
        return json.dumps({"ok": True})

    @staticmethod
    def _classify(hint):
        text = hint.get("text") or ""
        axes = {}
        for name, spec in hint["axes"].items():
            hits = [v for v in spec["values"] if v.lower() in text.lower()]
            if not spec.get("multi"):
                hits = hits[:1]
            if hits:
                axes[name] = {"values": hits, "evidence": _first_line_with(text, hits[0]), "confidence": 0.9}
            else:
                axes[name] = {"values": ["해당 없음"], "evidence": "", "confidence": 0.8}
        return {"chunk_type": "내용", "axes": axes, "term_mappings": [], "new_values": []}

    @staticmethod
    def _label(hint):
        return {
            "answers": {q: {"answer": "N/A", "quote": "", "confidence": 0.8} for q in hint["qids"]},
            "extracted": [],
            "term_mappings": [],
        }


class MockEmbedTransport:
    def __init__(self, dim=8):
        self.dim = dim
        self.batches = []

    def embed(self, texts):
        self.batches.append(list(texts))
        out = []
        for t in texts:
            h = hashlib.sha256(t.encode("utf-8")).digest()
            vals = struct.unpack("<%dB" % self.dim, (h * ((self.dim // 32) + 1))[: self.dim])
            out.append([v / 255.0 for v in vals])
        return out
