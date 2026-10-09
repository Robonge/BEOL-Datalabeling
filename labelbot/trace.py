"""마일스톤 추적(L3c): 폐쇄망 터미널에서 "어느 단계가, 무슨 사유로, 왜" 실패했는지 보이게 한다.

출력은 모두 stderr다(stdout 계약 불변 — nightly_run.first_json·skill 스크립트가 stdout JSON을 읽는다).
Python 3.8 문법·표준 라이브러리만 쓰고, labelbot에서는 3.8 안전 모듈(milestones, reason_codes)만 import한다
(CODE_ROOT는 __file__로 계산). 배포판 python3에서 tools/verify_import.py·carry_state.py가 이 모듈을 쓴다.

공개 API (안정 — 이름·인자를 바꾸지 않는다)
- fail_block(milestone_id, reason_code, cause=None, action=None, detail_code=None, stream=None, trace_path=None)
    실패 블록만 출력한다(기록 없음). milestone_id는 "M19" 또는 "M19 IMPORT". cause·action이 None이면
    reason_codes 카탈로그에서 찾는다. 형식:
        [M19 IMPORT] 실패  사유=CODE_CHANGED
          원인: …
          조치: …
          추적: workspaces/<ws>/logs/trace_<run>.log  (사유=CODE_CHANGED)   ← trace_path가 있을 때만
- milestone(mid, run_id=None, workspace=None, quiet=False)  컨텍스트 매니저·데코레이터
    시작 "[M07 EMBED] 시작 run=<id>" / 완료 "[M07 EMBED] 완료 n=<건수> t=<초>s" / 예외면 stdout flush 뒤 실패 블록,
    traceback은 추적 파일에만(코드 위치·예외 이름·사유 코드만, str(exc)는 쓰지 않는다). BEOL_TRACE=1이면 전체
    traceback을 터미널에만 내고 저장하지 않는다. KeyboardInterrupt는 "[M07 EMBED] 중단(사용자)".
    사유 코드 = 예외의 .reason_code, 없으면 UNEXPECTED_<예외 이름>. quiet=True면 시작·완료 줄 없이 실패만 낸다.
    with 안에서 m.n = 건수, m.run_id = 실행 ID, m.workspace = 작업 폴더를 나중에 채울 수 있다.
- run(mid, fn, run_id=None, workspace=None, quiet=False) → 종료 코드
    명령 main 감싸기: SystemExit 통과, 잡히지 않은 예외는 블록 + 1, Ctrl+C는 130. fn()이 1·2를 돌려주면
    (fail_code로 사유를 남기지 않았으면) RC_<n>, 3·4는 건너뜀(skip)으로 기록한다. 반환값은 그대로 돌려준다.
- run_main(mid, fn, argv=None, quiet=False, defer=True)  스크립트 main 감싸기(-h/--help면 감싸지 않음,
    --workspace를 기록 위치로, 시작 줄은 begin() 또는 끝날 때)
- begin()  defer로 연 마일스톤의 시작 줄을 지금 낸다
- fail_code(code, detail=None)  지금 열린 마일스톤에 사유를 남긴다([오류]를 찍고 return 1/2 하는 곳). 반환값 불변.
- set_workspace(ws) / set_run(run_id)  열린 마일스톤들의 기록 위치·실행 ID
- serving(mid, url) / aborted(mid, workspace=None) / post_failed(mid, code, workspace=None)  화면 서버 줄
    (서버 스레드에서는 마일스톤 ID를 인자로 명시해 부른다 — contextvars를 쓰지 않는다)
- port_in_use(exc)  bind 실패가 '포트 사용 중'인가
- record(mid, status, ...)  logs/milestones.jsonl에 한 줄(잠금 + 줄당 한 번 쓰기)

기록: <작업 폴더>/logs/milestones.jsonl {ts, milestone, status, run_id, reason_code, detail_code, elapsed_s}
(status: ok·fail·skip·abort·post_fail). 작업 폴더가 없으면 workspaces/_trace/(env BEOL_TRACE_DIR로 바꿀 수 있다).
"""
import json
import os
import re
import sys
import threading
import time
import traceback

from labelbot import milestones, reason_codes

CODE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRACE_ENV = "BEOL_TRACE"
TRACE_DIR_ENV = "BEOL_TRACE_DIR"
JSONL = "milestones.jsonl"

_CODE_RE = re.compile(r"^(?=.{3,64}$)[A-Z][A-Z0-9]*(?:_[A-Za-z0-9]+)*$")  # CONFLICT·TIMEOUT 같은 한 단어 코드 포함
_RUN_RE = re.compile(r"[^0-9A-Za-z-]")
_LOCK = threading.Lock()
_STACK = []      # 메인 흐름에서 열린 마일스톤(안쪽이 끝). 작업 스레드는 쓰지 않는다.
_SEQ = [0]       # 기록한 실패·중단 수. 바깥 마일스톤이 안쪽에서 이미 낸 실패를 다시 내지 않게 한다.


# ---- 기본 도구 -------------------------------------------------------------

def _mid(milestone_id):
    return str(milestone_id).split()[0] if milestone_id else "M00"


def _label(milestone_id):
    s = str(milestone_id or "M00")
    return s if " " in s else milestones.label(s)


def safe_code(code):
    """사유 코드 모양(대문자_…)이면 그대로, 아니면 None. 로그·출력에 문장이 섞이지 않게 한다."""
    return code if isinstance(code, str) and _CODE_RE.match(code) else None


def _err(text):
    try:
        sys.stderr.write(text)
        sys.stderr.flush()
    except (OSError, ValueError):
        pass


def _flush_stdout():
    try:
        sys.stdout.flush()
    except (OSError, ValueError):
        pass


def trace_root():
    return os.environ.get(TRACE_DIR_ENV) or os.path.join(CODE_ROOT, "workspaces", "_trace")


def _ws_root(workspace):
    ws = getattr(workspace, "root", workspace)
    return ws if isinstance(ws, str) and ws and os.path.isdir(ws) else None


def logs_dir(workspace=None):
    ws = _ws_root(workspace)
    return os.path.join(ws, "logs") if ws else trace_root()


def display_path(path):
    """저장소 안이면 저장소 기준 상대경로(/), 밖이면 그대로."""
    p = os.path.abspath(path)
    try:
        rel = os.path.relpath(p, CODE_ROOT)
    except ValueError:
        return p
    return p if rel.startswith("..") else rel.replace("\\", "/")


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())  # util.now_iso와 같은 형식(UTC)


def record(mid, status, run_id=None, reason_code=None, detail_code=None, elapsed_s=None, workspace=None):
    """milestones.jsonl에 한 줄. 기록 실패는 명령을 멈추지 않는다."""
    row = {"ts": _now(), "milestone": _mid(mid), "status": status, "run_id": run_id,
           "reason_code": safe_code(reason_code) or (None if reason_code is None else "INVALID_CODE"),
           "detail_code": safe_code(detail_code), "elapsed_s": elapsed_s}
    line = json.dumps(row, ensure_ascii=False) + "\n"
    d = logs_dir(workspace)
    try:
        with _LOCK:
            if not os.path.isdir(d):
                os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, JSONL), "a", encoding="utf-8", newline="\n") as f:
                f.write(line)
    except OSError:
        pass


# ---- 실패 블록 ---------------------------------------------------------------

def fail_block(milestone_id, reason_code, cause=None, action=None, detail_code=None, stream=None, trace_path=None):
    """실패 블록을 stderr(또는 stream)에 낸다. 기록은 하지 않는다(record·milestone이 한다)."""
    _flush_stdout()
    code = safe_code(reason_code) or "INVALID_CODE"
    if cause is None or action is None:
        d = reason_codes.describe(code, _mid(milestone_id))
        cause = d["원인"] if cause is None else cause
        action = d["조치"] if action is None else action
    head = "[%s] 실패  사유=%s" % (_label(milestone_id), code)
    detail = safe_code(detail_code)
    if detail:
        head += "  세부=%s" % detail
    lines = [head, "  원인: %s" % cause, "  조치: %s" % action]
    if trace_path:
        lines.append("  추적: %s  (사유=%s)" % (trace_path, code))
    text = "\n".join(lines) + "\n"
    if stream is None:
        _err(text)
    else:
        stream.write(text)
        try:
            stream.flush()
        except (AttributeError, OSError, ValueError):
            pass


def exc_code(exc):
    return safe_code(getattr(exc, "reason_code", None)) or "UNEXPECTED_%s" % type(exc).__name__


def _frame_path(filename):
    p = os.path.abspath(filename)
    try:
        rel = os.path.relpath(p, CODE_ROOT)
    except ValueError:
        rel = ".."
    if rel.startswith(".."):
        return "<lib>/" + os.path.basename(p)
    return rel.replace("\\", "/")


def _trace_lines(exc):
    """코드 위치(파일:줄 함수)와 예외 이름만. str(exc)·지역 변수는 쓰지 않는다."""
    out, seen, e = [], set(), exc
    while e is not None and id(e) not in seen:
        seen.add(id(e))
        out.append("exception=%s" % type(e).__name__)
        for fs in traceback.extract_tb(e.__traceback__):
            out.append("  %s:%d %s" % (_frame_path(fs.filename), fs.lineno, fs.name))
        e = e.__cause__ or e.__context__
        if e is not None:
            out.append("caused_by:")
    return out


def _write_trace(mid, run_id, code, exc, workspace):
    """BEOL_TRACE=1이면 전체 traceback을 터미널에만 내고 None. 아니면 추적 파일에 쓰고 표시 경로를 돌려준다."""
    if os.environ.get(TRACE_ENV) == "1":
        _err("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
        return "BEOL_TRACE=1 — 터미널에만 출력(저장 안 함)"
    rid = _RUN_RE.sub("", run_id or "") or "%s-p%d" % (time.strftime("%Y%m%d-%H%M%S"), os.getpid())
    d = logs_dir(workspace)
    path = os.path.join(d, "trace_%s.log" % rid)
    body = ["ts=%s milestone=%s run=%s reason=%s" % (_now(), _mid(mid), run_id or "-", code)] + _trace_lines(exc)
    try:
        with _LOCK:
            if not os.path.isdir(d):
                os.makedirs(d, exist_ok=True)
            with open(path, "a", encoding="utf-8", newline="\n") as f:
                f.write("\n".join(body) + "\n\n")
    except OSError:
        return None
    return display_path(path)


# ---- 마일스톤 -------------------------------------------------------------------

class Milestone(object):
    """컨텍스트 매니저·데코레이터. trace.milestone(...)로 만든다."""

    def __init__(self, mid, run_id=None, workspace=None, quiet=False, defer=False):
        self.mid = _mid(mid)
        self.defer = defer
        self._begun = False
        self.run_id = run_id
        self.workspace = workspace
        self.quiet = quiet
        self.n = None
        self.code = None
        self.detail = None
        self.skipped = False
        self._t0 = None
        self._seq0 = None

    def __call__(self, fn):
        def wrapper(*a, **kw):
            with Milestone(self.mid, self.run_id, self.workspace, self.quiet, self.defer):
                return fn(*a, **kw)
        wrapper.__name__ = getattr(fn, "__name__", "wrapper")
        wrapper.__doc__ = getattr(fn, "__doc__", None)
        return wrapper

    def fail_code(self, code, detail=None):
        self.code = safe_code(code) or "INVALID_CODE"
        self.detail = safe_code(detail)
        self.skipped = False

    def skip(self, code):
        self.code = safe_code(code) or "INVALID_CODE"
        self.skipped = True

    def result(self, rc):
        """명령 종료 코드를 마일스톤 상태로: 3·4=건너뜀(사유가 없으면 RC_<n>), 그 밖의 0 아닌 값=실패(RC_<n>)."""
        if not isinstance(rc, int) or isinstance(rc, bool) or rc == 0:
            return
        if rc in (3, 4):
            if not self.code:
                self.skip("RC_%d" % rc)
            return
        if not self.code or self.skipped:
            self.fail_code("RC_%d" % rc)

    def begin(self):
        """시작 줄(한 번만). defer=True면 실행 ID를 안 뒤(set_run)나 일을 시작할 때 부른다. 안 부르면 끝날 때 낸다."""
        if not self._begun and not self.quiet:
            _err("[%s] 시작%s\n" % (milestones.label(self.mid), " run=%s" % self.run_id if self.run_id else ""))
        self._begun = True

    def _elapsed(self):
        return round(time.time() - self._t0, 1)

    def __enter__(self):
        self._t0 = time.time()
        self._seq0 = _SEQ[0]
        _STACK.append(self)
        if not self.defer:
            self.begin()
        return self

    def __exit__(self, et, ev, tb):
        if self in _STACK:
            _STACK.remove(self)
        el = self._elapsed()
        label = milestones.label(self.mid)
        if _SEQ[0] != self._seq0:
            return False  # 안쪽 마일스톤·화면 서버가 이미 실패·중단을 냈다
        if not (et is not None and issubclass(et, SystemExit)):
            self.begin()
        if et is None:
            if self.code and not self.skipped:
                fail_block(self.mid, self.code, detail_code=self.detail)
                record(self.mid, "fail", self.run_id, self.code, self.detail, el, self.workspace)
                _SEQ[0] += 1
            elif self.code:
                if not self.quiet:
                    _err("[%s] 건너뜀 사유=%s t=%.1fs\n" % (label, self.code, el))
                record(self.mid, "skip", self.run_id, self.code, self.detail, el, self.workspace)
            elif not self.quiet:
                part = "  부분 실패 사유=%s" % self.detail if self.detail else ""
                _err("[%s] 완료%s%s t=%.1fs\n" % (label, " n=%s" % self.n if self.n is not None else "", part, el))
                record(self.mid, "ok", self.run_id, None, self.detail, el, self.workspace)
            return False
        if issubclass(et, KeyboardInterrupt):
            _flush_stdout()
            _err("[%s] 중단(사용자)\n" % label)
            record(self.mid, "abort", self.run_id, "USER_ABORT", None, el, self.workspace)
            _SEQ[0] += 1
            return False
        if issubclass(et, SystemExit) or not issubclass(et, Exception):
            return False
        code = exc_code(ev)
        detail = safe_code(getattr(ev, "detail", None))
        _flush_stdout()
        path = _write_trace(self.mid, self.run_id, code, ev, self.workspace)
        fail_block(self.mid, code, detail_code=detail, trace_path=path)
        record(self.mid, "fail", self.run_id, code, detail, el, self.workspace)
        _SEQ[0] += 1
        return False


def milestone(mid, run_id=None, workspace=None, quiet=False, defer=False):
    return Milestone(mid, run_id=run_id, workspace=workspace, quiet=quiet, defer=defer)


def current():
    return _STACK[-1] if _STACK else None


def begin():
    """defer로 연 마일스톤의 시작 줄을 지금 낸다(이미 냈으면 아무 일도 하지 않는다)."""
    m = current()
    if m is not None:
        m.begin()


def fail_code(code, detail=None):
    """지금 열린(가장 안쪽) 마일스톤에 사유를 남긴다. 열린 것이 없으면 아무 일도 하지 않는다."""
    m = current()
    if m is not None:
        m.fail_code(code, detail)


def skip_code(code):
    """지금 열린 마일스톤을 건너뜀(skip)으로 끝낸다(멈출 사유가 있어 실행하지 않은 경우)."""
    m = current()
    if m is not None:
        m.skip(code)


def note_partial(code):
    """대상 일부만 실패했다(마일스톤은 완료). 완료 줄과 기록의 detail_code에 사유를 남긴다."""
    m = current()
    if m is not None and not m.detail:
        m.detail = safe_code(code)


def set_workspace(workspace):
    for m in _STACK:
        m.workspace = workspace


def set_run(run_id):
    for m in _STACK:
        if not m.run_id:
            m.run_id = run_id


def run(mid, fn, run_id=None, workspace=None, quiet=False, defer=False):
    """명령 main 감싸기. 반환: 종료 코드(fn의 값 그대로, 잡히지 않은 예외 1, Ctrl+C 130).
    defer=True면 시작 줄을 fn 안의 begin()(또는 끝날 때)까지 미룬다(실행 ID를 시작 줄에 넣으려고)."""
    try:
        with milestone(mid, run_id=run_id, workspace=workspace, quiet=quiet, defer=defer) as m:
            rc = fn()
            m.result(rc)
        return rc
    except KeyboardInterrupt:
        return 130
    except Exception:  # 블록·추적 파일은 milestone이 이미 냈다
        return 1


def _argv_workspace(argv):
    for i, a in enumerate(argv):
        if a == "--workspace" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--workspace="):
            return a.split("=", 1)[1]
    return None


def run_main(mid, fn, argv=None, quiet=False, defer=True):
    """스크립트 main() 감싸기. -h/--help면 감싸지 않는다(마일스톤 줄 없음). --workspace가 있으면 그 logs/에 기록.
    defer=True(기본): 시작 줄은 main 안의 begin() 또는 끝날 때 낸다 — argparse 오류(SystemExit)에는 줄이 없다."""
    argv = sys.argv[1:] if argv is None else argv
    if "-h" in argv or "--help" in argv:
        return fn()
    return run(mid, fn, workspace=_argv_workspace(argv), quiet=quiet, defer=defer)


# ---- 화면 서버 -------------------------------------------------------------------

def serving(mid, url):
    begin()
    _err("[%s] 대기 중 URL=%s (끝내려면 Ctrl+C)\n" % (_label(mid), url))


def aborted(mid, workspace=None):
    """화면 서버·대기 루프의 Ctrl+C: 중단 줄 + 기록. 바깥 마일스톤은 같은 일을 다시 내지 않는다(종료 코드는 0)."""
    _flush_stdout()
    _err("[%s] 중단(사용자)\n" % _label(mid))
    m = current()
    ws = workspace if workspace is not None else (m.workspace if m is not None else None)
    record(mid, "abort", m.run_id if m is not None else None, "USER_ABORT", None, None, ws)
    _SEQ[0] += 1


def post_failed(mid, code, workspace=None):
    """POST 실패 한 줄(마일스톤 + 사유). 서버는 계속 돈다(마일스톤을 실패로 바꾸지 않는다)."""
    c = safe_code(code) or "INVALID_CODE"
    _err("[%s] POST 실패  사유=%s\n" % (_label(mid), c))
    record(mid, "post_fail", None, c, None, None, workspace)


def port_in_use(exc):
    """bind 실패가 포트 사용 중(EADDRINUSE, Windows 10048·10013)인가."""
    import errno
    return isinstance(exc, OSError) and (
        exc.errno in (errno.EADDRINUSE, 98, 48, 10048) or getattr(exc, "winerror", None) in (10048, 10013))


def port_fail(mid, port):
    """PORT_IN_USE: [오류] 줄 + 사유(--port 안내). 열린 마일스톤이 없으면 블록도 바로 낸다. 반환: 종료 코드 1."""
    _flush_stdout()
    _err("[오류] PORT_IN_USE 포트 %s 사용 중 (--port로 다른 포트를 주세요)\n" % port)
    if current() is None:
        fail_block(mid, "PORT_IN_USE")
    else:
        fail_code("PORT_IN_USE")
    return 1
