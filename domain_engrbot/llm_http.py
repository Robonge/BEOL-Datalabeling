"""OpenAI 호환 judge adapter(7.1절).

PoC에서는 사외·사내를 구분하지 않는다(2026-10-05 사용자 결정). 키 값은 환경변수에서만 읽고 어디에도 쓰지 않는다.
"""
from labelbot import llm as lb_llm

from domain_engrbot.llm import JudgeLLM, LLMError

TOOL_NAME = "submit_verdicts"
TOOL_PARAMETERS = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "string"},
                       "verdict": {"type": "string", "enum": ["supported", "partial", "unsupported"]},
                       "reason": {"type": "string"}},
        "required": ["id", "verdict", "reason"]}}},
    "required": ["items"],
}


class OpenAICompatJudgeLLM(JudgeLLM):
    """cfg: pipeline llm 블록에 judge 설정(model, temperature, timeout, mode)을 덮은 것. post는 테스트에서 바꿔 끼운다."""

    def __init__(self, cfg, post=None):
        self.cfg = cfg
        self.post = post or lb_llm.post_json
        self.name = cfg.get("model") or ""
        self.mode = cfg.get("mode") or "json"

    @property
    def url(self):
        return (self.cfg.get("base_url") or "").rstrip("/") + (self.cfg.get("chat_path") or "/chat/completions")

    def build_body(self, messages):
        cfg = self.cfg
        body = {"model": cfg.get("model"), "messages": messages}
        if cfg.get("temperature") is not None:
            body["temperature"] = cfg["temperature"]
        if cfg.get("max_tokens"):
            body[cfg.get("max_tokens_param") or "max_tokens"] = cfg["max_tokens"]
        if self.mode == "tool":
            body["tools"] = [{"type": "function", "function": {
                "name": TOOL_NAME, "description": "항목별 판정을 제출한다.", "parameters": TOOL_PARAMETERS}}]
            body["tool_choice"] = {"type": "function", "function": {"name": TOOL_NAME}}
        elif cfg.get("response_format_json"):
            body["response_format"] = {"type": "json_object"}
        return body

    def request_identity(self, messages):
        """실제 전송하는 요청 전체(주소, 경로, 모델, messages, 파라미터). 헤더와 키는 넣지 않는다."""
        return {"url": self.url, "body": self.build_body(messages)}

    def allows(self, file_id):
        """PoC에서는 사외·사내를 구분하지 않으므로 예시 출처 파일을 모두 허용한다."""
        return True

    def complete(self, messages, file_ids, hint=None):
        cfg = self.cfg
        key =lb_llm.read_key(cfg.get("api_key_env"))
        if not key:
            raise LLMError("KEY_MISSING", sent=False)
        try:
            _, resp = self.post(self.url, lb_llm.auth_headers(cfg, key), self.build_body(messages),
                                cfg.get("timeout") or 60, cfg.get("ca_file"))
        except lb_llm.CallFailed as e:
            raise LLMError(e.reason_code)
        try:
            msg = resp["choices"][0]["message"]
            out = msg["tool_calls"][0]["function"]["arguments"] if self.mode == "tool" else msg["content"]
        except (TypeError, KeyError, IndexError):
            raise LLMError("RESPONSE_SHAPE")
        if not isinstance(out, str):
            raise LLMError("RESPONSE_SHAPE")
        return out

    def sent_params(self):
        cfg = self.cfg
        return {
            "transport": "http",
            "base_url": cfg.get("base_url"),
            "chat_path": cfg.get("chat_path") or "/chat/completions",
            "model": cfg.get("model"),
            "mode": self.mode,
            "temperature": cfg["temperature"] if cfg.get("temperature") is not None else "미전송",
            "max_tokens": cfg.get("max_tokens") or "미전송",
            "response_format": "json_object" if cfg.get("response_format_json") and self.mode == "json" else "미전송",
        }
