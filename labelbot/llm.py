"""OpenAI 호환 호출과 외부 전송 안전장치.

리다이렉트 거부 opener, 키 읽기는 이 모듈의 공용 함수 하나씩이며
LLM과 임베딩이 모두 이것을 쓴다. 키 값은 로그·캐시 키·DB에 넣지 않는다.
"""
import http.client
import json
import os
import socket
import ssl
import urllib.error
import urllib.request

from labelbot import util
from labelbot.workspace import CODE_ROOT

# 테스트 fixture(더미 파일 해시 목록). PoC에서는 전송 판정에 쓰지 않는다.
DUMMY_HASHES_PATH = os.path.join(CODE_ROOT, "tests", "gold", "dummy_hashes.jsonl")


class CallFailed(Exception):
    def __init__(self, reason_code):
        Exception.__init__(self, reason_code)
        self.reason_code = reason_code


# ---- 공용 안전장치 -------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def build_opener(ca_file=None):
    ctx = ssl.create_default_context(cafile=ca_file) if ca_file else ssl.create_default_context()
    return urllib.request.build_opener(_NoRedirect(), urllib.request.HTTPSHandler(context=ctx))


def read_key(env_name):
    return os.environ.get(env_name or "", "")


def post_json(url, headers, payload, timeout, ca_file=None):
    """JSON POST. 3xx는 실패(새 호스트로 따라가지 않는다). 반환: (status, 파싱된 본문 또는 None)."""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    hdrs = {"Content-Type": "application/json"}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
    return _open(req, timeout, ca_file)


def _open(req, timeout, ca_file):
    try:
        with build_opener(ca_file).open(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw.decode("utf-8")) if raw.strip() else None)
    except urllib.error.HTTPError as e:
        if 300 <= e.code < 400:
            raise CallFailed("HTTP_REDIRECT_REFUSED")
        raise CallFailed("HTTP_%d" % e.code)
    except (socket.timeout, TimeoutError):
        raise CallFailed("TIMEOUT")
    except urllib.error.URLError as e:
        if isinstance(getattr(e, "reason", None), (socket.timeout, TimeoutError)):
            raise CallFailed("TIMEOUT")
        raise CallFailed("NETWORK_ERROR")
    except ValueError:
        raise CallFailed("RESPONSE_NOT_JSON")
    except (OSError, http.client.HTTPException):
        # 연결 끊김·불완전 응답 등. 실행 전체를 멈추지 않고 그 호출만 실패로 남긴다.
        raise CallFailed("NETWORK_ERROR")


def auth_headers(cfg, key):
    hdrs = {}
    header = cfg.get("auth_header") or "Authorization"
    if key:
        hdrs[header] = ("Bearer %s" % key) if header.lower() == "authorization" else key
    hdrs.update(cfg.get("extra_headers") or {})
    return hdrs


# ---- 응답 JSON 추출 -------------------------------------------------------

class DuplicateKey(ValueError):
    pass


def _pairs_no_dup(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise DuplicateKey(k)
        out[k] = v
    return out


def extract_json(content):
    """코드 블록으로 감싼 응답도 읽는다. 키 중복은 DuplicateKey."""
    if not isinstance(content, str):
        return None
    s = content.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else ""
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(s[start : end + 1], object_pairs_hook=_pairs_no_dup)
    except DuplicateKey:
        raise
    except ValueError:
        return None


# ---- 전송 계층 -------------------------------------------------------------

class HttpChatTransport:
    def __init__(self, cfg):
        self.cfg = cfg

    def send(self, body, hint=None):
        cfg = self.cfg
        key = read_key(cfg.get("api_key_env"))
        if not key:
            raise CallFailed("KEY_MISSING")
        url = cfg["base_url"].rstrip("/") + cfg["chat_path"]
        status, resp = post_json(url, auth_headers(cfg, key), body, cfg.get("timeout") or 60, cfg.get("ca_file"))
        try:
            return resp["choices"][0]["message"]["content"]
        except (TypeError, KeyError, IndexError):
            raise CallFailed("RESPONSE_SHAPE")


def chat_once(cfg, messages, max_tokens, timeout):
    """RAG 답변용 단발 채팅 호출(labelbot.ragsrv). (본문, finish_reason)을 돌려준다. 캐시·재시도·temperature 없음."""
    key = read_key(cfg.get("api_key_env"))
    if not key:
        raise CallFailed("KEY_MISSING")
    url = cfg["base_url"].rstrip("/") + cfg["chat_path"]
    body = {"model": cfg["model"], "messages": messages, "max_completion_tokens": max_tokens}
    status, resp = post_json(url, auth_headers(cfg, key), body, timeout, cfg.get("ca_file"))
    try:
        choice = resp["choices"][0]
        text = choice["message"].get("content") or ""
        reason = choice.get("finish_reason")
    except (TypeError, KeyError, IndexError, AttributeError):
        raise CallFailed("RESPONSE_SHAPE")
    return text, (reason if isinstance(reason, str) else None)


class ChatClient:
    """chat_json(messages, file_ids, validate)로 검증된 JSON을 돌려준다. 성공 응답만 캐시한다."""

    def __init__(self, cfg, con, transport=None, log=None):
        self.cfg = cfg
        self.con = con
        self.log = log
        if transport is None:
            if cfg.get("transport") == "mock":
                from labelbot.mock import MockChatTransport

                transport = MockChatTransport()
            else:
                transport = HttpChatTransport(cfg)
        self.transport = transport
        self.calls = 0
        self.cache_hits = 0

    @property
    def url(self):
        return self.cfg["base_url"].rstrip("/") + self.cfg["chat_path"]

    def build_body(self, messages):
        cfg = self.cfg
        body = {"model": cfg["model"], "messages": messages}
        if cfg.get("temperature") is not None:
            body["temperature"] = cfg["temperature"]
        if cfg.get("max_tokens"):
            body[cfg.get("max_tokens_param") or "max_tokens"] = cfg["max_tokens"]
        if cfg.get("response_format_json"):
            body["response_format"] = {"type": "json_object"}
        return body

    def sent_params(self):
        cfg = self.cfg
        return {
            "base_url": cfg["base_url"],
            "chat_path": cfg["chat_path"],
            "model": cfg["model"],
            "temperature": cfg["temperature"] if cfg.get("temperature") is not None else "미전송",
            "max_tokens": cfg.get("max_tokens") or "미전송",
            "max_tokens_param": cfg.get("max_tokens_param") or "max_tokens",
            "response_format": "json_object" if cfg.get("response_format_json") else "미전송",
        }

    def cache_key(self, body):
        """실제 전송한 요청 전체(base_url, chat_path, body)의 해시. 헤더와 키는 넣지 않는다."""
        key = {"base_url": self.cfg["base_url"], "chat_path": self.cfg["chat_path"], "body": body}
        transport = self.cfg.get("transport") or "http"
        if transport != "http" or not isinstance(self.transport, HttpChatTransport):
            key["transport"] = transport if transport != "http" else type(self.transport).__name__
        return util.hash_obj(key)

    def chat_json(self, messages, file_ids, validate, hint=None, probe=False):
        body = self.build_body(messages)
        key = self.cache_key(body)
        row = self.con.execute("SELECT response FROM llm_cache WHERE cache_key=?", (key,)).fetchone()
        if row:
            obj = extract_json(row[0])
            if obj is not None and validate(obj)[0]:
                self.cache_hits += 1
                return obj
        last = "FORMAT_INVALID"
        for _ in range(1 + int(self.cfg.get("max_retries") or 0)):
            self.calls += 1
            content = self.transport.send(body, hint)
            try:
                obj = extract_json(content)
            except DuplicateKey:
                last = "DUPLICATE_KEY"
                continue
            if obj is None:
                last = "JSON_PARSE"
                continue
            ok, reason = validate(obj)
            if ok:
                self.con.execute(
                    "INSERT OR REPLACE INTO llm_cache(cache_key, response, created_at) VALUES(?,?,?)",
                    (key, content, util.now_iso()),
                )
                self.con.commit()
                return obj
            last = reason or "FORMAT_INVALID"
        raise CallFailed(last)


# ---- 임베딩 --------------------------------------------------------------

class HttpEmbedTransport:
    def __init__(self, cfg):
        self.cfg = cfg

    def embed(self, texts):
        cfg = self.cfg
        key = read_key(cfg.get("api_key_env"))
        if not key:
            raise CallFailed("KEY_MISSING")
        url = cfg["base_url"].rstrip("/") + cfg["path"]
        status, resp = post_json(
            url, auth_headers(cfg, key), {"model": cfg["model"], "input": texts},
            cfg.get("timeout") or 60, cfg.get("ca_file"),
        )
        try:
            data = sorted(resp["data"], key=lambda d: d["index"])
            return [d["embedding"] for d in data]
        except (TypeError, KeyError):
            raise CallFailed("RESPONSE_SHAPE")
