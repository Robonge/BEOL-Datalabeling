"""BEOL 슬라이드 RAG 화면 + API 서버(옛 클라우드 답변 함수와 읽기 창을 로컬 저장소로 대신한다).

실행(저장소 루트에서): python -m labelbot.ragsrv --port 8795 --bind 127.0.0.1 --directory <저장소>/rag
                      [--store <로컬 저장소>] [--chat-model <이름>]

- 저장소(labelbot/localstore.py)의 rag_config.json에서 llm·embedding 블록을 읽어 DEFAULT_CONFIG와 합친다.
  없으면 종료 코드 2. 키는 시작할 때 .env(load_env_file)에서 읽고, 없으면 종료 코드 2. 키 값은 출력하지 않는다.
- LLM·임베딩은 모듈 함수 _chat·_embed로만 부른다(테스트가 바꿔 끼운다). 네트워크 저수준 호출은 labelbot/llm.py에만 있다.
- 요청 검사: Host 이름이 127.0.0.1·localhost가 아니면 403. POST는 같은 출처 Origin과 application/json일 때만 받는다.
  CORS 허용 헤더는 보내지 않고, GET·HEAD·POST 말고는 405.
- API: POST /api/ask, GET /api/facets, GET /api/stats, GET /slides/<file_id16>/<seq4>.jpg, POST /api/feedback(201).
- /api/ask 순서·예산·오류 코드는 옛 index.ts와 같다(전체 80초, 단계 시간 = min(상한, 남은 시간), 남은 시간 3초 미만이면 그 단계 실패).
- 슬라이드 그림은 <store>/slides/<sha>.b64를 메모리에서 디코딩해 sha256·JPEG 시그니처를 확인한 뒤 보낸다. 디스크에 .jpg를 쓰지 않는다.
- 로그: 요청마다 "[ragsrv] <경로> <코드> <ms> k=<k> n=<근거 수>" 한 줄. 질문·답·본문·파일명은 쓰지 않는다.
"""
import argparse
import base64
import binascii
import copy
import functools
import hashlib
import http.server
import json
import math
import os
import pathlib
import re
import sqlite3
import sys
import threading
import time
import uuid

from labelbot import llm, localstore, raglib, ragsearch, util
from labelbot.workspace import CODE_ROOT, DEFAULT_CONFIG, load_env_file

DEFAULT_CHAT_MODEL = "gpt-6-sol"
# 추론형 모델은 이 한도에 추론 토큰까지 포함한다. 너무 낮으면 본문 없이 끝난다(LLM_TRUNCATED).
DEFAULT_MAX_COMPLETION_TOKENS = 6000
REWRITE_MAX_COMPLETION_TOKENS = 400

# 요청 전체 예산(화면은 90초에 끊는다). 각 단계 timeout은 min(단계 상한, 남은 시간)이다. 단위 초.
TOTAL_BUDGET = 80.0
MIN_STEP = 3.0
REWRITE_MIN_LEFT = 60.0
TIMEOUT_EMBED = 20.0
TIMEOUT_REWRITE = 20.0
TIMEOUT_SEARCH = 20.0
TIMEOUT_SIBLINGS = 10.0
TIMEOUT_ANSWER = 45.0

MAX_FEEDBACK_QUESTION = 2000
MAX_FEEDBACK_ANSWER = 8000
MAX_FEEDBACK_EVIDENCE = 9
MAX_FEEDBACK_EVIDENCE_BYTES = 16384
MAX_FEEDBACK_COMMENT = 1000
MAX_FEEDBACK_SESSION = 100

_SLIDE = re.compile(r"^[0-9a-f]{16}/\d{4}\.jpg$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_HEX = re.compile(r"^[0-9a-f]+$", re.I)
_LLM_ERRORS = (llm.CallFailed, OSError, ValueError, KeyError, TypeError)


def _chat(llm_cfg, messages, max_tokens, timeout):
    return llm.chat_once(llm_cfg, messages, max_tokens, timeout)          # (text, finish_reason)


def _embed(emb_cfg, texts, timeout):
    return llm.HttpEmbedTransport(dict(emb_cfg, timeout=timeout)).embed(texts)


class StepError(Exception):
    def __init__(self, code, status=502):
        super().__init__(code)
        self.code = code
        self.status = status


def _step_timeout(deadline, cap, code):
    """남은 예산 안의 단계 timeout(초). 남은 시간이 MIN_STEP 미만이면 그 단계 실패."""
    left = deadline - time.monotonic()
    if left < MIN_STEP:
        raise StepError(code)
    return min(cap, left)


def _positive_int(raw, fallback):
    try:
        n = int((raw or "").strip())
    except ValueError:
        return fallback
    return n if n > 0 else fallback


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = v
    return out


class Store:
    """저장소 읽기. 연결은 요청마다 읽기 전용으로 열고, 검색용 행(벡터·노름·토큰)은 파일이 바뀔 때만 다시 읽는다."""

    def __init__(self, root, model):
        self.root = root
        self.model = model
        self.db = localstore.db_path(root)
        self._lock = threading.Lock()
        self._key = None
        self._rows = []

    def connect_ro(self):
        con = sqlite3.connect(pathlib.Path(self.db).as_uri() + "?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        return con

    def _stat_key(self):
        key = []
        for p in (self.db, self.db + "-wal"):
            try:
                st = os.stat(p)
                key.append((st.st_mtime_ns, st.st_size))
            except OSError:
                key.append(None)
        return tuple(key)

    def rows(self, con):
        with self._lock:
            key = self._stat_key()
            if key != self._key:
                self._rows = ragsearch.load_rows(con, self.model)
                self._key = key
            return self._rows

    def slide(self, path):
        """완전한 행의 slide_image_path → JPG bytes. 없거나 검사 실패면 None."""
        con = self.connect_ro()
        try:
            found = None
            for r in con.execute("SELECT model, labels, slide_image_path, slide_image_sha256 FROM beol_chunk_embeddings"
                                 " WHERE slide_image_path = ? AND model = ?", (path, self.model)):
                if ragsearch.is_complete(dict(r), self.model) and r["slide_image_sha256"]:
                    found = r["slide_image_sha256"]
                    break
        finally:
            con.close()
        if not found or not _SHA.match(found):
            return None
        try:
            with open(localstore.slide_path(self.root, found), encoding="ascii") as f:
                data = base64.b64decode(f.read(), validate=True)
        except (OSError, ValueError, binascii.Error):
            return None
        if hashlib.sha256(data).hexdigest() != found or not data.startswith(b"\xff\xd8\xff"):
            return None
        return data


class _Handler(http.server.SimpleHTTPRequestHandler):
    store = None
    llm_cfg = None
    emb_cfg = None
    max_tokens = DEFAULT_MAX_COMPLETION_TOKENS
    write_lock = None

    # ---- 로그 -------------------------------------------------------------
    def log_message(self, fmt, *args):
        pass

    def log_request(self, code="-", size="-"):
        ctx = getattr(self, "_ctx", None) or {}
        ms = int((time.monotonic() - ctx.get("t0", time.monotonic())) * 1000)
        sys.stderr.write("[ragsrv] %s %s %d k=%d n=%d\n" % (
            self.path.split("?")[0], ctx.get("code") or code, ms, ctx.get("k", 0), ctx.get("n", 0)))

    def _start(self):
        self._ctx = {"t0": time.monotonic(), "code": None, "k": 0, "n": 0}

    # ---- 응답 -------------------------------------------------------------
    def _json(self, status, obj, code=None):
        self._ctx["code"] = code or (obj.get("error") if isinstance(obj, dict) else None)
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _fail(self, status, code):
        self._json(status, {"error": code})

    # ---- 요청 검사 --------------------------------------------------------
    def _local_host(self):
        # Host를 로컬 이름(포트 무관)으로 묶어 DNS 재바인딩으로 들어온 요청을 막는다. Host가 없으면 거절한다.
        return (self.headers.get("Host") or "").rsplit(":", 1)[0].lower() in ("127.0.0.1", "localhost")

    def _same_origin(self):
        origin = self.headers.get("Origin")
        return bool(origin) and origin.split("://", 1)[-1] == self.headers.get("Host")

    def _read_body(self, limit):
        """본문 bytes. 길이가 없거나 limit를 넘으면 None(읽지 않고 연결을 닫는다)."""
        try:
            n = int(self.headers.get("Content-Length") or -1)
        except ValueError:
            n = -1
        if n < 0 or n > limit:
            self.close_connection = True
            return None
        return self.rfile.read(n)

    # ---- 메서드 -----------------------------------------------------------
    def do_GET(self):
        self._start()
        if not self._local_host():
            return self._fail(403, "HOST_REJECTED")
        path = self.path.split("?", 1)[0]
        try:
            if path == "/api/facets":
                return self._facets()
            if path == "/api/stats":
                return self._stats()
            if path.startswith("/slides/"):
                return self._slide(path[len("/slides/"):])
        except sqlite3.Error:
            return self._fail(500, "INTERNAL")
        if path == "/":
            self.path = "/beol_rag.html"
        return super().do_GET()

    def do_HEAD(self):
        self._start()
        if not self._local_host():
            self.send_response(403)
            self.send_header("Content-Length", "0")
            return self.end_headers()
        if self.path.split("?", 1)[0] == "/":
            self.path = "/beol_rag.html"
        return super().do_HEAD()

    def do_POST(self):
        self._start()
        if not self._local_host():
            return self._fail(403, "HOST_REJECTED")
        if not self._same_origin():
            return self._fail(403, "ORIGIN_REJECTED")
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self._fail(403, "CONTENT_TYPE_REJECTED")
        path = self.path.split("?", 1)[0]
        if path == "/api/ask":
            return self._guard(self._ask)
        if path == "/api/feedback":
            return self._guard(self._feedback)
        return self._fail(404, "NOT_FOUND")

    def _not_allowed(self):
        self._start()
        if not self._local_host():
            return self._fail(403, "HOST_REJECTED")
        return self._fail(405, "METHOD_NOT_ALLOWED")

    do_OPTIONS = do_PUT = do_PATCH = do_DELETE = _not_allowed

    def list_directory(self, path):
        self.send_error(404)
        return None

    def _guard(self, fn):
        try:
            return fn()
        except Exception:  # 그 밖의 예외는 500 INTERNAL(본문·사유는 로그에 쓰지 않는다)
            return self._fail(500, "INTERNAL")

    # ---- GET API ---------------------------------------------------------
    def _facets(self):
        con = self.store.connect_ro()
        try:
            return self._json(200, ragsearch.facets(con, self.store.model), code="OK")
        finally:
            con.close()

    def _stats(self):
        con = self.store.connect_ro()
        try:
            return self._json(200, {"count": ragsearch.count(con, self.store.model)}, code="OK")
        finally:
            con.close()

    def _slide(self, rel):
        if not _SLIDE.match(rel):
            return self._fail(404, "NOT_FOUND")
        data = self.store.slide(rel)
        if data is None:
            return self._fail(404, "NOT_FOUND")
        self._ctx["code"] = "OK"
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    # ---- POST /api/feedback ----------------------------------------------
    def _feedback(self):
        raw = self._read_body(raglib.MAX_BODY_BYTES)
        try:
            doc = json.loads(raw.decode("utf-8")) if raw is not None else None
        except (UnicodeDecodeError, ValueError):
            doc = None
        if not isinstance(doc, dict):
            return self._fail(400, "BAD_REQUEST_JSON")
        q, a, ev = doc.get("question"), doc.get("answer"), doc.get("evidence", [])
        verdict, comment, sid = doc.get("verdict"), doc.get("comment"), doc.get("session_id")
        ok = (isinstance(q, str) and 1 <= len(q) <= MAX_FEEDBACK_QUESTION
              and isinstance(a, str) and 1 <= len(a) <= MAX_FEEDBACK_ANSWER
              and isinstance(ev, list) and len(ev) <= MAX_FEEDBACK_EVIDENCE
              and verdict in ("good", "bad")
              and (comment is None or (isinstance(comment, str) and len(comment) <= MAX_FEEDBACK_COMMENT))
              and (sid is None or (isinstance(sid, str) and len(sid) <= MAX_FEEDBACK_SESSION)))
        ev_text = json.dumps(ev, ensure_ascii=False) if ok else ""
        if not ok or len(ev_text.encode("utf-8")) > MAX_FEEDBACK_EVIDENCE_BYTES:
            return self._fail(400, "BAD_INPUT")
        with self.write_lock:
            con = localstore.connect(self.store.root)
            try:
                con.execute("INSERT INTO beol_rag_feedback(id, created_at, session_id, question, answer, evidence,"
                            " verdict, comment) VALUES(?,?,?,?,?,?,?,?)",
                            (str(uuid.uuid4()), util.now_iso(), sid, q, a, ev_text, verdict, comment))
                con.commit()
            finally:
                con.close()
        return self._json(201, {}, code="OK")

    # ---- POST /api/ask ---------------------------------------------------
    def _ask(self):
        deadline = time.monotonic() + TOTAL_BUDGET
        raw = self._read_body(raglib.MAX_BODY_BYTES)
        try:
            body = json.loads(raw.decode("utf-8")) if raw is not None else None
        except (UnicodeDecodeError, ValueError):
            raw = None
        if raw is None:
            return self._fail(400, "BAD_REQUEST_JSON")
        try:
            inp = raglib.validate_input(body)
        except raglib.RagInputError as e:
            return self._fail(400, e.code)
        messages, filters, k, question = inp["messages"], inp["filters"], inp["k"], inp["question"]
        self._ctx["k"] = k
        try:
            return self._answer(messages, filters, k, question, deadline)
        except StepError as e:
            return self._fail(e.status, e.code)

    def _rewrite(self, messages, deadline):
        convo = [{"role": m["role"],
                  "content": (raglib.strip_citations(m["content"])[:raglib.MAX_CONTEXT_ASSISTANT_CHARS]
                              if m["role"] == "assistant" else m["content"])} for m in messages]
        try:
            text = _chat(self.llm_cfg, [{"role": "system", "content": raglib.REWRITE_SYSTEM_PROMPT}] + convo,
                         REWRITE_MAX_COMPLETION_TOKENS, _step_timeout(deadline, TIMEOUT_REWRITE, "LLM_FAILED"))[0]
        except (StepError,) + _LLM_ERRORS:
            return None
        q = re.sub(r"\s+", " ", text if isinstance(text, str) else "").strip()
        if not q or len(q) > raglib.MAX_REWRITE_CHARS:
            return None
        return q

    def _query_vec(self, text, deadline):
        timeout = _step_timeout(deadline, TIMEOUT_EMBED, "EMBED_FAILED")
        try:
            vecs = _embed(self.emb_cfg, [text], timeout)
        except _LLM_ERRORS:
            raise StepError("EMBED_FAILED")
        vec = vecs[0] if isinstance(vecs, list) and len(vecs) == 1 else None
        if not isinstance(vec, list) or not vec:
            raise StepError("EMBED_FAILED")
        if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in vec):
            raise StepError("EMBED_FAILED")
        return vec

    def _answer(self, messages, filters, k, question, deadline):
        warnings = []
        search_query = question
        # 남은 시간이 REWRITE_MIN_LEFT 미만이면 고쳐 쓰기를 건너뛰고 원문으로 검색한다.
        if raglib.needs_rewrite(messages) and deadline - time.monotonic() >= REWRITE_MIN_LEFT:
            rewritten = self._rewrite(messages, deadline)
            if rewritten:
                search_query = rewritten
            else:
                warnings.append("REWRITE_FAILED")

        vec = self._query_vec(search_query, deadline)

        _step_timeout(deadline, TIMEOUT_SEARCH, "SEARCH_FAILED")
        con = self.store.connect_ro()
        try:
            try:
                cached = self.store.rows(con)
                if any(len(r["vec"]) != len(vec) for r in cached):
                    raise StepError("EMBED_DIM_MISMATCH")
                rows = ragsearch.search(con, vec, search_query, filters, k, self.store.model, rows=cached)
            except ragsearch.RagSearchError as e:
                raise StepError("EMBED_DIM_MISMATCH" if e.code == "DIM_MISMATCH" else "SEARCH_FAILED")
            except sqlite3.Error:
                raise StepError("SEARCH_FAILED")

            if not rows:
                out = {"answer": raglib.no_evidence_answer(filters), "rewritten_query": search_query,
                       "cited": [], "evidence": []}
                if warnings:
                    out["warnings"] = warnings
                return self._json(200, out, code="NO_EVIDENCE")

            # 같은 파일의 다른 chunk도 근거로 붙인다. 못 불러오면 검색된 행만으로 답하고 경고를 남긴다.
            sibling_rows = None
            ids = [r["file_id"] for r in rows if isinstance(r.get("file_id"), str) and _HEX.match(r["file_id"])]
            try:
                _step_timeout(deadline, TIMEOUT_SIBLINGS, "SIBLINGS_FAILED")
                sibling_rows = ragsearch.siblings(con, ids, self.store.model)
            except (StepError, sqlite3.Error):
                warnings.append("SIBLINGS_FAILED")
        finally:
            con.close()
        hit_ids = {r["chunk_id"] for r in rows}
        extra = [r for r in (sibling_rows or []) if r["chunk_id"] not in hit_ids]

        urls = {r["slide_image_path"]: "/slides/" + r["slide_image_path"]
                for r in rows + extra if isinstance(r.get("slide_image_path"), str)}
        evidence = raglib.attach_siblings(raglib.build_evidence(rows, urls), extra, urls)
        self._ctx["n"] = len(evidence)

        msgs = raglib.build_answer_messages(messages, evidence, question, search_query, raglib.ask_confirm())
        timeout = _step_timeout(deadline, TIMEOUT_ANSWER, "LLM_FAILED")
        try:
            text, finish = _chat(self.llm_cfg, msgs, self.max_tokens, timeout)
        except _LLM_ERRORS:
            raise StepError("LLM_FAILED")
        text = text if isinstance(text, str) else ""
        # 한도를 다 써서 본문이 비면 빈 답과 구분한다.
        if not text.strip():
            raise StepError("LLM_TRUNCATED" if finish == "length" else "LLM_EMPTY")
        if finish == "length":
            warnings.append("TRUNCATED")
        fixed = raglib.finalize_answer(text, len(evidence))
        out = {"answer": fixed["text"], "rewritten_query": search_query, "cited": fixed["cited"], "evidence": evidence}
        if warnings:
            out["warnings"] = warnings
        return self._json(200, out, code="OK")


def load_config(root, chat_model=None):
    """rag_config.json → (llm_cfg, emb_cfg). 파일이 없으면 FileNotFoundError, JSON이 깨졌으면 ValueError."""
    with open(os.path.join(root, localstore.CONFIG_NAME), encoding="utf-8") as f:
        cfg = json.load(f)
    if not isinstance(cfg, dict):
        raise ValueError("RAG_CONFIG_SHAPE")
    llm_cfg = _merge(DEFAULT_CONFIG["llm"], cfg.get("llm") if isinstance(cfg.get("llm"), dict) else {})
    emb_cfg = _merge(DEFAULT_CONFIG["embedding"], cfg.get("embedding") if isinstance(cfg.get("embedding"), dict) else {})
    model = ((chat_model or "").strip() or os.environ.get("RAG_CHAT_MODEL", "").strip()
             or (llm_cfg.get("model") or "").strip() or DEFAULT_CHAT_MODEL)
    return dict(llm_cfg, model=model), emb_cfg


def make_server(root, directory, llm_cfg, emb_cfg, port, host="127.0.0.1"):
    handler = type("Handler", (_Handler,), {
        "store": Store(root, emb_cfg["model"]), "llm_cfg": llm_cfg, "emb_cfg": emb_cfg,
        "max_tokens": _positive_int(os.environ.get("RAG_MAX_COMPLETION_TOKENS"), DEFAULT_MAX_COMPLETION_TOKENS),
        "write_lock": threading.Lock()})
    handler = functools.partial(handler, directory=directory)
    return http.server.ThreadingHTTPServer((host, port), handler)


def _parser():
    p = argparse.ArgumentParser(prog="labelbot.ragsrv", description="BEOL 슬라이드 RAG 화면 + API 서버(로컬 저장소)")
    p.add_argument("--port", type=int, default=8795)
    p.add_argument("--bind", default="127.0.0.1")
    p.add_argument("--directory", default=os.path.join(CODE_ROOT, "rag"), help="화면 폴더(beol_rag.html)")
    p.add_argument("--store", help="로컬 저장소 폴더(기본: 환경변수 BEOL_RAG_STORE → workspaces/_rag_store)")
    p.add_argument("--chat-model", help="답변 모델(기본: 환경변수 RAG_CHAT_MODEL → rag_config.json llm.model → %s)"
                   % DEFAULT_CHAT_MODEL)
    return p


def main(argv=None):
    args = _parser().parse_args(argv)
    load_env_file()
    root = localstore.store_root({"path": args.store} if args.store else None)
    try:
        llm_cfg, emb_cfg = load_config(root, args.chat_model)
    except FileNotFoundError:
        print("[ragsrv] rag_config.json 없음: 먼저 push-vectors를 실행하세요", file=sys.stderr)
        return 2
    except ValueError:
        print("[ragsrv] rag_config.json 읽기 실패", file=sys.stderr)
        return 2
    missing = sorted({c.get("api_key_env") or "" for c in (llm_cfg, emb_cfg) if not llm.read_key(c.get("api_key_env"))})
    if missing:
        for name in missing:
            print("[ragsrv] %s 없음" % (name or "api_key_env"), file=sys.stderr)
        return 2
    srv = make_server(root, os.path.abspath(args.directory), llm_cfg, emb_cfg, args.port, args.bind)
    print("[ragsrv] %s:%d 제공(모델 %s)" % (args.bind, srv.server_address[1], llm_cfg["model"]), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
