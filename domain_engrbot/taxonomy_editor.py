"""taxonomy 편집기(taxonomy-editor 명령): taxonomy.json의 taxonomy·questions·synonyms를 보고 고치는 로컬 서버.

화면(screens/taxonomy_editor.html) 하나를 127.0.0.1에서 보여 준다. 화면은 세 시트를 받아 고치고,
'저장' 전에 변경 미리보기(diff_docs)와 검증 오류를 받은 뒤 확인을 거쳐 저장한다.
- rejected(보드의 기각 목록)는 화면에 보내지 않고, 저장할 때 지금 파일의 rejected를 그대로 붙인다(화면은 못 고친다).
- 미리보기·저장은 보드와 같은 어댑터 commit_taxonomy(by="editor", labelbot save_doc)가 한다: 버전 확인(다르면 409
  TAXONOMY_CHANGED) → 검증(실패하면 400 TAXONOMY_INVALID, 파일은 그대로) → 이력(taxonomy_history.jsonl) → 원자적 교체.
  파일 없음 404 TAXONOMY_NOT_FOUND, 읽기 실패 500 TAXONOMY_READ_FAILED, 쓰기 실패 500 TAXONOMY_WRITE_FAILED.
- taxonomy.xlsx 경로는 열지 않는다(TAXONOMY_XLSX_NEEDS_MIGRATION). 변환은 labelbot taxonomy-migrate 몫이다.
콘솔에는 건수·사유 코드만 낸다. 셀 내용은 내지 않는다.
"""
import json
import os
import threading
import webbrowser

from domain_engrbot import io, model, serve, trace
from domain_engrbot.adapters import labelbot_ws as lb

EDITOR_PORT = 8796   # 고정 포트(보드 8795 옆). 쓰고 있으면 OS가 고른 빈 포트로 연다
MAX_BODY = 4 * 1024 * 1024
CELL_MAX = 20000   # 칸 하나의 글자 수 상한(보드 taxonomy_board.CELL_MAX와 같다)
SAVE_KIND = "taxonomy_editor_save"
SHEETS = ("taxonomy", "questions", "synonyms")
SCREEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screens", "taxonomy_editor.html")
DEFAULT_TAXONOMY = os.path.join(io.CODE_ROOT, "taxonomy", "taxonomy.json")
BY = "editor"
HEADERS = {s: h for s, h in lb.taxonomy_headers().items() if s in SHEETS}


class EditorError(Exception):
    """HTTP 상태·사유 코드와 응답에 더할 칸."""

    def __init__(self, status, code, **extra):
        Exception.__init__(self, code)
        self.status = status
        self.reason_code = code
        self.extra = extra

    def body(self):
        out = {"ok": False, "code": self.reason_code}
        out.update(self.extra)
        return out


def _check_path(tax_path):
    if str(tax_path).lower().endswith(".xlsx"):
        raise EditorError(400, "TAXONOMY_XLSX_NEEDS_MIGRATION")
    if not os.path.isfile(tax_path):
        raise EditorError(404, "TAXONOMY_NOT_FOUND")


def _load(tax_path):
    """지금 파일 → (doc, 버전). 읽기·JSON 오류는 EditorError."""
    _check_path(tax_path)
    try:
        return lb.load_taxonomy_doc(tax_path)
    except model.BundleError as e:   # 읽기 실패(사유 코드) 또는 JSON 형식 오류
        raise EditorError(500, e.reason_code, detail=e.detail)


def _sheets(doc):
    """화면에 보낼 세 시트(열 순서로 맞춘 행 객체). rejected는 넣지 않는다."""
    norm = lb.normalize_taxonomy_doc(doc)
    return {s: norm.get(s) or [] for s in SHEETS}


def doc_state(tax_path):
    """GET /editor/doc 응답 본문."""
    doc, version = _load(tax_path)
    errors, warnings = lb.check_taxonomy_doc(doc)
    return {"ok": True, "doc": _sheets(doc), "version": version, "headers": {s: HEADERS[s] for s in SHEETS},
            "issues": errors, "warnings": warnings}


def _client_doc(payload):
    """요청 본문 → (base_version, 세 시트 dict). 형식이 틀리면 EditorError(400, EDITOR_FORMAT_INVALID).
    행은 정의 열만 남기고(모르는 열은 버린다) 칸 값은 문자열만 받는다. 문장은 고치지 않는다(공백·줄바꿈 그대로).
    빈 행도 자리를 지킨다(행 번호 = 목록 index + 2)."""
    if not isinstance(payload, dict) or payload.get("kind") != SAVE_KIND:
        raise EditorError(400, "EDITOR_FORMAT_INVALID")
    base = payload.get("base_version")
    doc = payload.get("doc")
    if not isinstance(base, str) or not base or not isinstance(doc, dict):
        raise EditorError(400, "EDITOR_FORMAT_INVALID")
    out = {}
    for s in SHEETS:
        rows = doc.get(s)
        if not isinstance(rows, list):
            raise EditorError(400, "EDITOR_FORMAT_INVALID", sheet=s)
        header = HEADERS[s]
        clean = []
        for r in rows:
            if not isinstance(r, dict) or any(r.get(h) is not None and (not isinstance(r.get(h), str)
                                                                        or len(r.get(h)) > CELL_MAX) for h in header):
                raise EditorError(400, "EDITOR_FORMAT_INVALID", sheet=s)
            clean.append(dict(lb.row_obj(lb.row_cells(r, header), header)))
        out[s] = clean
    return base, out


def _merge(current, sheets):
    """화면의 세 시트 + 지금 파일의 version·rejected(화면은 rejected를 못 고친다)."""
    doc = {"version": current.get("version") or 1}
    doc.update(sheets)
    doc["rejected"] = current.get("rejected") if isinstance(current.get("rejected"), list) else []
    return doc


def _op_counts(diff):
    n = {"add": 0, "edit": 0, "delete": 0}
    for d in diff:
        n[d["op"]] = n.get(d["op"], 0) + 1
    return n


def _commit(tax_path, payload, preview):
    """어댑터 commit_taxonomy(보드와 같은 절차·사유 코드)로 미리보기·저장. 반환: (세 시트, 결과, 시트 diff)."""
    base, sheets = _client_doc(payload)
    try:
        res = lb.commit_taxonomy(tax_path, base, lambda current: _merge(current, sheets), BY, preview=preview)
    except lb.TaxonomyCommitError as e:
        extra = {"issues": e.issues} if e.issues else {}
        if e.detail:
            extra["detail"] = e.detail
        raise EditorError(e.status, e.code, **extra)
    return sheets, res, [d for d in res["diff"] if d["sheet"] in SHEETS]


def preview(tax_path, payload):
    """POST /editor/preview: 쓰지 않고 변경 행과 검증 결과만 돌려준다. 읽은 버전이 낡았으면 409."""
    _, res, diff = _commit(tax_path, payload, True)
    return {"ok": True, "diff": diff, "counts": _op_counts(diff), "issues": res["issues"], "warnings": res["warnings"]}


def save(tax_path, payload, lock=None):
    """POST /editor/save: 지금 파일의 rejected를 붙여 save_doc(by="editor")로 저장한다. 바뀐 행이 없으면 쓰지 않는다."""
    with lock or threading.Lock():
        sheets, res, diff = _commit(tax_path, payload, False)
    ops = _op_counts(diff)
    counts = dict({s: sum(1 for r in sheets[s] if any(v for v in r.values())) for s in SHEETS}, **ops)
    if not res["saved"]:
        return {"ok": True, "version": res["version"], "counts": counts, "saved": False}
    print("[taxonomy-editor] 저장: 추가 %d · 수정 %d · 삭제 %d행 (taxonomy %d · questions %d · synonyms %d)" % (
        ops["add"], ops["edit"], ops["delete"], counts["taxonomy"], counts["questions"], counts["synonyms"]), flush=True)
    return {"ok": True, "version": res["version"], "counts": counts, "saved": True}


# ---- 서버 ---------------------------------------------------------------------------

class _EditorHandler(serve._BaseHandler):
    milestone = "M12"
    tax_path = None
    screen = None
    lock = None

    def do_GET(self):
        if not self._local_host():
            return self._json(403, {"ok": False, "code": "HOST_REJECTED"})
        path = self.path.split("?")[0]
        if path == "/editor/doc":
            return self._run(lambda: doc_state(self.tax_path))
        if path not in ("/", "/taxonomy_editor.html"):
            return self._json(404, {"ok": False, "code": "NOT_FOUND"})
        body = self._screen_text(self.screen)
        if body is None:
            return self._json(404, {"ok": False, "code": "EDITOR_SCREEN_MISSING"})
        self._send(200, body, "text/html; charset=utf-8")

    do_HEAD = do_GET

    def do_POST(self):
        path = self.path.split("?")[0]
        if path not in ("/editor/preview", "/editor/save"):
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
            return self._json(413, {"ok": False, "code": "EDITOR_TOO_LARGE"})
        try:
            payload = json.loads(self.rfile.read(n).decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            return self._json(400, {"ok": False, "code": "EDITOR_JSON_INVALID"})
        if path == "/editor/preview":
            return self._run(lambda: preview(self.tax_path, payload))
        return self._run(lambda: save(self.tax_path, payload, self.lock))

    def _run(self, fn):
        try:
            return self._json(200, fn())
        except EditorError as e:
            if e.status >= 409 or e.status == 400:
                print("[taxonomy-editor] %s %s" % (e.status, e.reason_code), flush=True)
            return self._json(e.status, e.body())
        except Exception as e:   # 예상 못 한 실패: 예외 이름만 낸다(문장·traceback에 셀 내용이 들어갈 수 있다)
            print("[taxonomy-editor] 500 EDITOR_FAILED %s" % type(e).__name__, flush=True)
            return self._json(500, {"ok": False, "code": "EDITOR_FAILED", "detail": type(e).__name__})


def make_editor_server(tax_path, port, host="127.0.0.1", screen=None):
    handler = type("EditorHandler", (_EditorHandler,), {
        "tax_path": os.path.abspath(tax_path), "screen": screen or SCREEN, "lock": threading.Lock()})
    return serve._Server((host, port), handler)


def serve_editor(tax_path, say, port=None, open_browser=False):
    """편집기 서버(127.0.0.1)를 열고 Ctrl+C까지 기다린다. 반환: 종료 코드(열지 못하면 [오류] 줄과 1)."""
    tax_path = os.path.abspath(tax_path)
    try:
        state = doc_state(tax_path)
    except EditorError as e:
        say("[오류] %s" % e.reason_code)
        return 1
    if not os.path.isfile(SCREEN):
        say("[오류] EDITOR_SCREEN_MISSING")
        return 1
    try:
        srv = make_editor_server(tax_path, EDITOR_PORT if port is None else port)
    except OSError as e:
        if port is not None:
            if trace.port_in_use(e):
                return trace.port_fail("M12", port)
            raise
        srv = make_editor_server(tax_path, 0)
    d = state["doc"]
    say("[taxonomy-editor] taxonomy %d행 · questions %d · synonyms %d, 오류 %d · 경고 %d" % (
        len(d["taxonomy"]), len(d["questions"]), len(d["synonyms"]), len(state["issues"]), len(state["warnings"])))
    url = "http://127.0.0.1:%d/" % srv.server_address[1]
    say("[taxonomy-editor] 편집기: %s (저장 → taxonomy.json, 끝내려면 Ctrl+C)" % url)
    trace.serving("M12", url)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    if open_browser and serve.no_browser():
        # BEOL_NO_BROWSER=1이거나 디스플레이가 없으면 열지 않고 주소만 낸다.
        say("[taxonomy-editor] NO_BROWSER 브라우저로 직접 여세요: %s" % url)
    elif open_browser:
        try:
            webbrowser.open(url)
        except Exception:   # 브라우저를 못 열어도 서버는 계속 연다
            say("[taxonomy-editor] OPEN_FAILED")
    try:
        while th.is_alive():
            th.join(0.5)
    except KeyboardInterrupt:
        trace.aborted("M12")
    finally:
        srv.shutdown()
        srv.server_close()
    return 0


def add_arguments(parser):
    parser.add_argument("--taxonomy", help="taxonomy.json 경로(기본: 저장소 taxonomy/taxonomy.json)")
    parser.add_argument("--port", type=int, help="포트(기본 %d, 쓰고 있으면 빈 포트)" % EDITOR_PORT)
    parser.add_argument("--open", action="store_true", help="브라우저로 편집기를 연다")


def main_cli(args, say):
    tax_path = os.path.abspath(args.taxonomy) if getattr(args, "taxonomy", None) else DEFAULT_TAXONOMY
    return serve_editor(tax_path, say, port=getattr(args, "port", None), open_browser=getattr(args, "open", False))
