"""검토 화면 서버(serve 명령): 검수 실행의 review.html을 보여 주고, 화면의 결정 JSON을 qa/inbox/에 쓴다.

브라우저는 내려받기 위치를 고를 수 없어 결정 파일이 Downloads로 가므로, 같은 서버가
qa/inbox/qa_decisions_<QA>.json을 직접 쓴다(labelbot serve와 같은 방식). 127.0.0.1에만 열고,
같은 출처(이 서버가 낸 화면)의 JSON 요청만 받는다. 보여 주는 파일은 그 실행의 review.html 하나뿐이다.
받은 JSON은 고치지 않고 그대로 쓴다. 읽어 반영하는 곳은 여전히 golden·feedback의 read_inbox 한 곳이다.
콘솔에는 실행 ID, 저장한 파일 이름, 건수만 낸다. 결정 값과 근거 인용은 내지 않는다.

질문 화면 서버(questions serve, plan-question-loop.md 5.3절·8.5절)도 여기 있다. 질문 폴더의 engr_questions.html
하나를 보여 주고, 화면의 답 JSON을 qa/inbox/engr_answers_<set_id>.json에 그대로 쓰며, 자유 답의 초안을 만들어 준다
(drafter: 호출한 쪽이 넘기는 LLM 콜러블). 콘솔에는 set_id·파일 이름·건수·사유 코드만 낸다(질문·답 문장은 내지 않는다).
applier(호출한 쪽이 넘기는 반영 콜러블)가 있으면 '답변 완료 · 저장'이 곧 반영이다: 저장한 답 파일을 바로 반영하고,
반영이 끝나면 서버를 닫는다(사용자 결정, 2026-10-06. 백그라운드로 띄운 Claude는 서버가 끝나는 것으로 마무리를 안다).

역방향 프록시 뒤에서 쓸 때만 env로 넓힌다(labelbot serve와 같은 규칙, 둘 다 없으면 지금과 같다).
BEOL_ALLOWED_HOSTS(쉼표, 포트 무관)는 Host·Origin 허용 목록에 더하고, BEOL_PATH_PREFIX(예: /absproxy/8771)는
경로 매칭 전에 뗀다. 보드·편집기 서버(taxonomy_editor)도 _BaseHandler를 물려받아 같은 규칙을 쓴다.
"""
import hashlib
import http.server
import json
import os
import re
import sys
import tempfile
import threading

from domain_engrbot import io, qmodel, trace

KIND = "qa_decisions"
MAX_BODY = 5 * 1024 * 1024
PORT_BASE, PORT_SPAN = 8700, 200  # 실행마다 같은 포트를 써서 브라우저에 저장된 진행 상황을 이어 쓴다
Q_PORT_BASE, Q_PORT_SPAN = 8900, 200  # 질문 화면 서버(QA 검토 서버 포트와 겹치지 않게)
DRAFT_MAX_BODY = 8 * 1024
CLOSE_DELAY = 0.5  # 반영 뒤 응답이 브라우저에 닿을 틈을 두고 서버를 닫는다(초)
_CODE = re.compile(r"^[A-Z0-9_]{1,64}$")
# 화면은 인라인 스크립트·스타일과 data: 이미지만 쓰고, 같은 출처에만 요청한다(외부 주소·틀 넣기 금지).
CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
LOOPBACK = ("127.0.0.1", "localhost", "::1")


# ---- 프록시 대응(env). domain_engrbot은 labelbot을 정해진 모듈로만 가져오므로 labelbot.serve의 작은 도우미를 그대로 옮겨 둔다.

def _hostname(value):
    """'host[:port]'·'[IPv6]:port'에서 소문자 호스트 이름만 뗀다. 없으면 ''."""
    v = (value or "").strip().lower()
    if v.startswith("["):
        return v[1:].partition("]")[0]
    return v if v.count(":") > 1 else v.partition(":")[0]


def env_hosts():
    """env BEOL_ALLOWED_HOSTS(쉼표, 포트 무관)의 호스트 이름 집합. 미설정이면 빈 집합."""
    return {h for h in (_hostname(x) for x in os.environ.get("BEOL_ALLOWED_HOSTS", "").split(",")) if h}


def host_allowed(host):
    """Host 헤더(포트 무관)가 loopback 또는 BEOL_ALLOWED_HOSTS인가. DNS 재바인딩으로 들어온 요청을 막는다."""
    name = _hostname(host)
    return bool(name) and (name in LOOPBACK or name in env_hosts())


def origin_allowed(origin, host, fwd_host=None):
    """POST의 Origin 확인. Origin이 없으면 거절한다. Origin의 host:port가 Host(또는 허용 목록 안의
    X-Forwarded-Host)와 같거나, Origin의 호스트가 BEOL_ALLOWED_HOSTS에 있으면(포트·Host 무관) 허용한다.
    loopback의 다른 포트는 다른 앱이라 지금처럼 거절한다."""
    if not origin:
        return False
    hp = origin.split("://", 1)[-1]
    if hp == host:
        return True
    fwd = (fwd_host or "").split(",")[0].strip()
    if fwd and host_allowed(fwd) and hp == fwd:
        return True
    return _hostname(hp) in env_hosts()


def strip_prefix(path):
    """env BEOL_PATH_PREFIX(예: /absproxy/8771)를 요청 경로 앞에서 뗀다. 접두어가 없는 경로는 그대로 둔다."""
    p = os.environ.get("BEOL_PATH_PREFIX", "").strip().rstrip("/")
    if not p:
        return path
    if not p.startswith("/"):
        p = "/" + p
    if path != p and not path.startswith((p + "/", p + "?")):
        return path
    rest = path[len(p):]
    return rest if rest.startswith("/") else "/" + rest


def no_browser():
    """브라우저를 열지 않을 때: env BEOL_NO_BROWSER=1이거나 디스플레이가 없을 때(Windows·macOS가 아니고
    DISPLAY·WAYLAND_DISPLAY가 없음). 이때는 주소만 출력한다."""
    if os.environ.get("BEOL_NO_BROWSER") == "1":
        return True
    return sys.platform not in ("win32", "darwin") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def default_port(qa_run_id):
    return PORT_BASE + int(hashlib.sha256(qa_run_id.encode("utf-8")).hexdigest()[:8], 16) % PORT_SPAN


def decision_name(qa_run_id):
    return "%s_%s.json" % (KIND, qa_run_id)


def counts(doc):
    n = {}
    for d in doc.get("decisions") or []:
        if isinstance(d, dict):
            n[d.get("decision")] = n.get(d.get("decision"), 0) + 1

    def ln(key):
        v = doc.get(key)
        return len(v) if isinstance(v, list) else 0
    return {"confirm": n.get("confirm", 0), "correct": n.get("correct", 0), "cannot_judge": n.get("cannot_judge", 0),
            "reject_decisions": ln("reject_decisions"), "autofix_decisions": ln("autofix_decisions"),
            "proposal_decisions": ln("proposal_decisions")}


class _Server(http.server.ThreadingHTTPServer):
    """이미 쓰는 포트에 다시 bind하지 않는다(Windows의 SO_REUSEADDR는 쓰는 포트에도 bind를 허용해 빈 포트 대체가
    동작하지 않는다). QA 검토 서버와 질문 서버가 같이 쓴다."""
    allow_reuse_address = False


class _BaseHandler(http.server.BaseHTTPRequestHandler):
    """QA 검토 서버와 질문 서버의 공통 부분: 응답 도우미, Host·Origin 확인, 실패 응답만 남기는 로그.
    milestone: POST 실패 줄에 쓰는 마일스톤 ID(보드·편집기 핸들러는 M12). 서버 스레드에 명시로 넘긴다."""
    milestone = "M11"

    def log_message(self, fmt, *args):
        # 성공 요청은 내지 않는다(저장했을 때만 한 줄). 실패 응답만 경로와 코드를 남긴다.
        code = str(args[1]) if len(args) > 1 else ""
        if not code.startswith(("2", "3")):
            sys.stderr.write("[serve] %s %s %s\n" % (self.command, self.path.split("?")[0], code))

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", CSP)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code, obj):
        if code >= 400 and self.command == "POST":
            trace.post_failed(self.milestone, obj.get("code") if isinstance(obj, dict) else None)
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def parse_request(self):
        # 경로 매칭(do_GET·do_POST) 전에 프록시 접두어를 뗀다.
        ok = super().parse_request()
        if ok:
            self.path = strip_prefix(self.path)
        return ok

    def _local_host(self):
        # Host를 로컬 이름이나 BEOL_ALLOWED_HOSTS로 묶어 DNS 재바인딩으로 들어온 요청을 막는다. Host가 없으면 거절한다.
        return host_allowed(self.headers.get("Host"))

    def _same_origin(self):
        return self._local_host() and origin_allowed(self.headers.get("Origin"), self.headers.get("Host"),
                                                     self.headers.get("X-Forwarded-Host"))

    def _save_inbox(self, text, name):
        """inbox/<name>에 원자 교체로 쓴다. 임시 파일은 inbox 밖(qa/)에 고유 이름으로 써서 반영 단계가 쓰다 만
        파일을 집지 않고, 같은 작업 폴더의 서버 둘이 섞이지 않게 한다. 반환: 썼으면 True(실패는 False)."""
        tmp = None
        try:
            with self.lock:
                fd, tmp = tempfile.mkstemp(dir=self.tmp_dir, prefix=".inbox_", suffix=".json")
                os.close(fd)
                io.write_text(tmp, text)
                os.replace(tmp, os.path.join(self.inbox, name))
            return True
        except OSError:
            if tmp and os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            return False

    def _screen_text(self, path):
        """화면 파일(이 봇이 쓴 HTML, 사내 파일 아님)을 텍스트로 읽어 utf-8 bytes로. 없으면 None."""
        try:
            with open(path, encoding="utf-8") as f:
                return f.read().encode("utf-8")
        except OSError:
            return None


class _Handler(_BaseHandler):
    qa_run_id = None
    screen = None
    inbox = None
    tmp_dir = None
    lock = None

    def do_GET(self):
        if not self._local_host():
            return self._json(403, {"ok": False, "code": "HOST_REJECTED"})
        path = self.path.split("?")[0]
        if path == "/inbox/status":
            return self._json(200, {"ok": True, "qa_run_id": self.qa_run_id})
        if path not in ("/", "/review.html"):
            return self._json(404, {"ok": False, "code": "NOT_FOUND"})
        body = self._screen_text(self.screen)
        if body is None:
            return self._json(404, {"ok": False, "code": "REVIEW_SCREEN_MISSING"})
        self._send(200, body, "text/html; charset=utf-8")

    do_HEAD = do_GET

    def do_POST(self):
        if self.path.split("?")[0] != "/inbox/qa_decisions":
            return self._json(404, {"ok": False, "code": "NOT_FOUND"})
        if not self._same_origin():
            return self._json(403, {"ok": False, "code": "ORIGIN_REJECTED"})
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self._json(415, {"ok": False, "code": "CONTENT_TYPE"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        if n <= 0 or n > MAX_BODY:
            return self._json(413, {"ok": False, "code": "DECISIONS_TOO_LARGE"})
        raw = self.rfile.read(n)
        try:
            doc = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError):
            return self._json(400, {"ok": False, "code": "DECISIONS_JSON_INVALID"})
        if not isinstance(doc, dict) or doc.get("kind") != KIND or not isinstance(doc.get("decisions"), list):
            return self._json(400, {"ok": False, "code": "DECISIONS_FORMAT_INVALID"})
        if doc.get("qa_run_id") != self.qa_run_id:
            return self._json(400, {"ok": False, "code": "DECISIONS_OTHER_RUN"})
        name = decision_name(self.qa_run_id)
        if not self._save_inbox(raw.decode("utf-8-sig"), name):
            return self._json(500, {"ok": False, "code": "DECISIONS_WRITE_FAILED"})
        c = counts(doc)
        print("[serve] 결정 저장: qa/inbox/%s (확정 %d, 교정 %d, 판단 불가 %d, REJECT %d, AUTO_FIX %d, 제안 %d)" % (
            name, c["confirm"], c["correct"], c["cannot_judge"], c["reject_decisions"], c["autofix_decisions"],
            c["proposal_decisions"]), flush=True)
        return self._json(200, {"ok": True, "saved": "qa/inbox/" + name, "counts": c})


def make_server(paths, qa_run_id, port, host="127.0.0.1"):
    handler = type("Handler", (_Handler,), {
        "qa_run_id": qa_run_id, "screen": os.path.join(paths.run_dir(qa_run_id), "review.html"),
        "inbox": paths.inbox, "tmp_dir": paths.qa, "lock": threading.Lock()})
    return _Server((host, port), handler)


def serve(paths, qa_run_id, port=None):
    """반환: 종료 코드. 포트를 쓰고 있으면 OS가 고른 빈 포트로 연다."""
    try:
        srv = make_server(paths, qa_run_id, default_port(qa_run_id) if port is None else port)
    except OSError as e:
        if port is not None:
            if trace.port_in_use(e):
                return trace.port_fail("M11", port)
            raise
        srv = make_server(paths, qa_run_id, 0)
    print("[serve] 검토 화면: http://127.0.0.1:%d/ (검수 완료 → qa/inbox/%s, 끝내려면 Ctrl+C)" % (
        srv.server_address[1], decision_name(qa_run_id)), flush=True)
    trace.serving("M11", "http://127.0.0.1:%d/" % srv.server_address[1])
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        trace.aborted("M11")
    finally:
        srv.server_close()
    return 0


# ---- 질문 화면 서버 -----------------------------------------------------------------

def question_port(set_id):
    """질문 묶음마다 같은 포트(8900~9099)를 써서 브라우저에 저장된 진행 상황을 이어 쓴다."""
    return Q_PORT_BASE + int(hashlib.sha256(set_id.encode("utf-8")).hexdigest()[:8], 16) % Q_PORT_SPAN


def answer_counts(doc):
    n = {"answer": 0, "dismiss": 0, "skip": 0}
    for a in doc.get("answers") or []:
        if isinstance(a, dict) and a.get("action") in n:
            n[a["action"]] += 1
    return n


class _QuestionHandler(_BaseHandler):
    set_id = None
    qd = None
    screen = None
    inbox = None
    tmp_dir = None
    lock = None
    drafter = None
    draft_lock = None
    applier = None
    apply_lock = None

    def do_GET(self):
        if not self._local_host():
            return self._json(403, {"ok": False, "code": "HOST_REJECTED"})
        path = self.path.split("?")[0]
        if path == "/inbox/status":
            return self._json(200, {"ok": True, "set_id": self.set_id, "draft": self.drafter is not None,
                                    "apply": self.applier is not None and not self.server.applied})
        if path not in ("/", "/" + qmodel.SCREEN):
            return self._json(404, {"ok": False, "code": "NOT_FOUND"})
        body = self._screen_text(self.screen)
        if body is None:
            return self._json(404, {"ok": False, "code": "QUESTION_SCREEN_MISSING"})
        self._send(200, body, "text/html; charset=utf-8")

    do_HEAD = do_GET

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/inbox/engr_answers":
            return self._answers()
        if path == "/draft":
            return self._draft()
        return self._json(404, {"ok": False, "code": "NOT_FOUND"})

    def _body(self, limit, prefix):
        """같은 출처·JSON·크기 상한을 확인하고 (원문 텍스트, 문서)를 돌려준다. 거절하면 응답을 보내고 None."""
        if not self._same_origin():
            self._json(403, {"ok": False, "code": "ORIGIN_REJECTED"})
            return None
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            self._json(415, {"ok": False, "code": "CONTENT_TYPE"})
            return None
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        if n <= 0 or n > limit:
            self._json(413, {"ok": False, "code": prefix + "_TOO_LARGE"})
            return None
        try:
            text = self.rfile.read(n).decode("utf-8-sig")
            return text, json.loads(text)
        except (UnicodeDecodeError, ValueError, RecursionError):
            self._json(400, {"ok": False, "code": prefix + "_JSON_INVALID"})
            return None

    def _answers(self):
        got = self._body(qmodel.MAX_ANSWER_BYTES, "ANSWERS")
        if got is None:
            return None
        text, doc = got
        if not isinstance(doc, dict) or doc.get("kind") != qmodel.ANSWERS_KIND or not isinstance(doc.get("answers"), list):
            return self._json(400, {"ok": False, "code": "ANSWERS_FORMAT_INVALID"})
        # 다른 묶음 화면의 답을 이 서버의 이름으로 저장하지 않는다(반영 단계는 묶음이 달라도 질문 단위로 받는다)
        if doc.get("set_id") != self.set_id:
            return self._json(400, {"ok": False, "code": "ANSWERS_OTHER_SET"})
        name = qmodel.answers_name(self.set_id)
        if self.applier is not None and not self.apply_lock.acquire(blocking=False):
            return self._json(409, {"ok": False, "code": "APPLY_BUSY"})
        try:
            # 이미 반영하고 닫히는 중이면 같은 이름의 파일을 다시 쓰지 않는다(반영한 파일은 inputs/에 사본이 있다)
            if self.server.applied:
                return self._json(409, {"ok": False, "code": "ALREADY_APPLIED"})
            if not self._save_inbox(text, name):
                return self._json(500, {"ok": False, "code": "ANSWERS_WRITE_FAILED"})
            c = answer_counts(doc)
            print("[serve] 답 저장: qa/inbox/%s (답 %d, 묻지 않음 %d, 나중에 %d)" % (
                name, c["answer"], c["dismiss"], c["skip"]), flush=True)
            out = {"ok": True, "saved": "qa/inbox/" + name, "counts": c}
            if self.applier is not None:
                out.update(self._apply(os.path.join(self.inbox, name)))
            return self._json(200, out)
        finally:
            if self.applier is not None:
                self.apply_lock.release()

    def _apply(self, path):
        """저장한 답 파일을 반영한다. 반환: 응답에 더할 칸. 반영하면 서버를 닫고, 실패하면 열어 둔다(다시 저장할 수 있게)."""
        try:
            r = self.applier(path)
        except Exception as e:  # 장부 잠금·파일 오류 등은 사유 코드로만 알린다
            code = getattr(e, "reason_code", None)
            code = code if isinstance(code, str) and _CODE.match(code) else "APPLY_FAILED"
            print("[serve] 반영 실패: %s (답 파일은 저장돼 있다)" % code, flush=True)
            return {"applied": False, "apply_code": code}
        for line in r.get("lines") or []:
            print(line, flush=True)
        self.server.applied = True
        threading.Timer(CLOSE_DELAY, self.server.shutdown).start()
        return {"applied": True, "apply": r.get("result") or {}, "board": r.get("board")}

    def _draft(self):
        got = self._body(DRAFT_MAX_BODY, "DRAFT")
        if got is None:
            return None
        _, doc = got
        if self.drafter is None:
            return self._json(404, {"ok": False, "code": "DRAFT_UNAVAILABLE"})
        if not isinstance(doc, dict):
            return self._json(400, {"ok": False, "code": "DRAFT_FORMAT_INVALID"})
        qid = doc.get("question_id")
        try:
            current = qmodel.question_map(qmodel.load_set(self.qd))
        except qmodel.QModelError as e:
            return self._json(500, {"ok": False, "code": e.reason_code})
        if not isinstance(qid, str) or qid not in current:
            return self._json(404, {"ok": False, "code": "QUESTION_NOT_FOUND"})
        text = qmodel.clean_text(doc.get("answer_text"), qmodel.FREE_MAX)
        if text is None:
            return self._json(400, {"ok": False, "code": "ANSWER_TEXT_INVALID"})
        if not self.draft_lock.acquire(blocking=False):
            return self._json(409, {"ok": False, "code": "DRAFT_BUSY"})
        try:
            raw = self.drafter(qid, text)
        except Exception as e:  # LLM·전송 실패는 사유 코드로만 알린다(예외 문장에 답 원문이 들어갈 수 있다)
            code = getattr(e, "reason_code", None)
            code = code if isinstance(code, str) and _CODE.match(code) else "DRAFT_FAILED"
            print("[serve] 초안 요청 %s → %s" % (qid, code), flush=True)
            return self._json(502, {"ok": False, "code": code})
        finally:
            self.draft_lock.release()
        drafts = [x for x in (qmodel.normalize_draft(r) for r in (raw if isinstance(raw, list) else [])) if x]
        drafts = drafts[:qmodel.MAX_DRAFTS]
        print("[serve] 초안 요청 %s → %d건" % (qid, len(drafts)), flush=True)
        return self._json(200, {"ok": True, "drafts": drafts})


def make_question_server(paths, qd, set_id, port, drafter=None, host="127.0.0.1", applier=None):
    handler = type("QuestionHandler", (_QuestionHandler,), {
        "set_id": set_id, "qd": qd, "screen": os.path.join(qd, qmodel.SCREEN), "inbox": paths.inbox,
        "tmp_dir": paths.qa, "lock": threading.Lock(), "drafter": staticmethod(drafter) if drafter else None,
        "draft_lock": threading.Lock(), "applier": staticmethod(applier) if applier else None,
        "apply_lock": threading.Lock()})
    srv = _Server((host, port), handler)
    srv.applied = False
    return srv


def serve_questions(paths, qd, port=None, drafter=None, applier=None):
    """반환: 종료 코드. 질문 묶음이나 화면이 없으면 [오류] 줄과 1. 포트를 쓰고 있으면 OS가 고른 빈 포트로 연다.
    applier가 있으면 답을 저장하자마자 반영하고, 반영이 끝나면 서버를 닫고 0을 돌려준다."""
    try:
        doc = qmodel.load_set(qd)
    except qmodel.QModelError as e:
        print("[오류] %s" % e.reason_code, flush=True)
        trace.fail_code(e.reason_code)
        return 1
    if doc is None:
        print("[오류] QUESTIONS_NOT_FOUND", flush=True)
        trace.fail_code("QUESTIONS_NOT_FOUND")
        return 1
    if not os.path.isfile(os.path.join(qd, qmodel.SCREEN)):
        print("[오류] QUESTION_SCREEN_MISSING", flush=True)
        trace.fail_code("QUESTION_SCREEN_MISSING")
        return 1
    set_id = doc["set_id"]
    try:
        srv = make_question_server(paths, qd, set_id, question_port(set_id) if port is None else port, drafter,
                                   applier=applier)
    except OSError as e:
        if port is not None:
            if trace.port_in_use(e):
                return trace.port_fail("M11", port)
            raise
        srv = make_question_server(paths, qd, set_id, 0, drafter, applier=applier)
    print("[serve] 질문 화면: http://127.0.0.1:%d/ (답변 완료 → qa/inbox/%s%s, 끝내려면 Ctrl+C)" % (
        srv.server_address[1], qmodel.answers_name(set_id), " → 바로 반영" if applier else ""), flush=True)
    trace.serving("M11", "http://127.0.0.1:%d/" % srv.server_address[1])
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        trace.aborted("M11")
    finally:
        srv.server_close()
    if srv.applied:
        print("[serve] 반영을 마쳐 질문 화면 서버를 닫았다", flush=True)
    return 0


# ---- taxonomy 수정 보드 서버 ----------------------------------------------------------
# 보드 화면(taxonomy_board.html) 하나를 보여 주고, '최종 완료' 요청을 받는다. /board/preview는 바뀔 행과 검증 오류를
# 돌려주고(아무것도 쓰지 않는다), /board/finalize는 taxonomy.json에 쓰고 보드를 새로 만든다. 처리는 호출한 쪽
# (taxonomy_board.board_handlers)이 넘기는 콜러블이 한다. 콘솔에는 건수·사유 코드만 낸다.

BOARD_PORT = 8795   # 고정 포트: 브라우저에 저장한 편집·표시(localStorage)를 같은 출처로 이어 쓴다
BOARD_MAX_BODY = 1024 * 1024
BOARD_KIND = "taxonomy_board_decisions"


class _BoardHandler(_BaseHandler):
    milestone = "M12"
    screen = None
    preview = None
    finalize = None
    lock = None

    def do_GET(self):
        if not self._local_host():
            return self._json(403, {"ok": False, "code": "HOST_REJECTED"})
        path = self.path.split("?")[0]
        if path == "/board/status":
            return self._json(200, {"ok": True})
        if path not in ("/", "/taxonomy_board.html"):
            return self._json(404, {"ok": False, "code": "NOT_FOUND"})
        body = self._screen_text(self.screen)
        if body is None:
            return self._json(404, {"ok": False, "code": "BOARD_SCREEN_MISSING"})
        self._send(200, body, "text/html; charset=utf-8")

    do_HEAD = do_GET

    def do_POST(self):
        path = self.path.split("?")[0]
        if path not in ("/board/preview", "/board/finalize"):
            return self._json(404, {"ok": False, "code": "NOT_FOUND"})
        if not self._same_origin():
            return self._json(403, {"ok": False, "code": "ORIGIN_REJECTED"})
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self._json(415, {"ok": False, "code": "CONTENT_TYPE"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        if n <= 0 or n > BOARD_MAX_BODY:
            return self._json(413, {"ok": False, "code": "DECISIONS_TOO_LARGE"})
        try:
            doc = json.loads(self.rfile.read(n).decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError, RecursionError):   # 아주 깊게 중첩된 JSON도 형식 오류로
            return self._json(400, {"ok": False, "code": "DECISIONS_JSON_INVALID"})
        if not isinstance(doc, dict) or doc.get("kind") != BOARD_KIND:
            return self._json(400, {"ok": False, "code": "DECISIONS_FORMAT_INVALID"})
        final = path == "/board/finalize"
        with self.lock:
            try:
                status, body = (self.finalize if final else self.preview)(doc)
            except Exception as e:   # 처리 실패도 화면에 사유 코드로 알린다(서버는 계속 연다). 예외 문장은 내지 않는다
                code = getattr(e, "reason_code", None)
                if not (isinstance(code, str) and _CODE.match(code)):
                    code = type(e).__name__
                print("[serve] 보드 처리 실패: %s" % code, flush=True)
                return self._json(500, {"ok": False, "code": "BOARD_FAILED", "detail": code})
        if final and status == 200:
            c = body.get("counts") or {}
            print("[serve] 최종 완료: 확정 %d건 · 바뀐 행 %d · 미반영 %d · 반영됨 %d · 기각 %d · 먼저 할 일 %d" % (
                body.get("changed", 0), body.get("written", 0), c.get("open", 0), c.get("done", 0),
                c.get("rejected", 0), c.get("blocked", 0)), flush=True)
            if body.get("rebuild_failed"):
                print("[serve] 저장은 했지만 보드 다시 만들기 실패: %s" % body["rebuild_failed"], flush=True)
            if body.get("decisions_failed"):
                print("[serve] 저장은 했지만 확정 기록 실패: %s" % body["decisions_failed"], flush=True)
        elif status != 200:
            print("[serve] %s 거절: %s" % ("최종 완료" if final else "미리보기", body.get("code")), flush=True)
        return self._json(status, body)


def make_board_server(screen_path, preview, finalize, port, host="127.0.0.1"):
    """preview(요청 dict)·finalize(요청 dict) → (HTTP 상태, 응답 dict). 둘 다 호출한 쪽(taxonomy_board)이 넘긴다."""
    handler = type("BoardHandler", (_BoardHandler,), {
        "screen": screen_path, "preview": staticmethod(preview), "finalize": staticmethod(finalize),
        "lock": threading.Lock()})
    return _Server((host, port), handler)
