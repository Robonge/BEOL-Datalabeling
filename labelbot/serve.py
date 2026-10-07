"""화면 서버: 작업 폴더 screens/를 보여 주고, 화면이 보낸 검수·대조 JSON을 inbox/에 쓴다.

브라우저는 내려받기 위치를 고를 수 없어 교정 파일이 Downloads로 가므로, 같은 서버가
inbox/<종류>_<실행 ID>.json을 직접 쓴다. 127.0.0.1에만 열고, 같은 출처(이 서버가 낸 화면)의
JSON 요청만 받는다. 쓰는 형식은 .json뿐이며, 내용을 읽어 반영하는 곳은 여전히
`apply`의 read_input 한 곳이다. 로그에는 요청 경로와 응답 코드만 남긴다.

검수 화면의 "검수 완료" 버튼은 POST /inbox/review/done을 보낸다. 서버는 같은 방식으로 교정
파일을 쓴 뒤 signals/review_done_<실행 ID>.json에 완료 신호(실행 ID, 시각, 건수만)를 쓰고,
BEOL-labeling-feedback 스킬이 이 신호를 보고 반영·적재로 넘어간다.

결과 대시보드의 "검수 시작" 버튼은 POST /signals/review_start를 보낸다. 서버는
signals/review_start_<실행 ID>.json에 시작 신호(실행 ID, 시각, 파싱 대조 여부만)를 쓰고,
BEOL-labeling이 걸어 둔 대기가 이 신호를 보고 BEOL-labeling-feedback을 시작한다.
"""
import datetime
import functools
import http.server
import json
import os
import re
import sys
import threading
import urllib.parse

from labelbot import util

KINDS = ("review", "compare")
MAX_BODY = 5 * 1024 * 1024
MAX_START_BODY = 4 * 1024
_RUN_ID = re.compile(r"^[0-9A-Za-z-]{1,64}$")


def done_signal_path(ws_root, run_id):
    """검수 완료 신호 파일 경로: <작업 폴더>/signals/review_done_<실행 ID>.json. feedback 스킬도 이 경로를 기다린다."""
    return os.path.join(ws_root, "signals", "review_done_%s.json" % run_id)


def start_signal_path(ws_root, run_id):
    """검수 시작 신호 파일 경로: <작업 폴더>/signals/review_start_<실행 ID>.json. BEOL-labeling의 대기가 이 경로를 본다."""
    return os.path.join(ws_root, "signals", "review_start_%s.json" % run_id)


class _Handler(http.server.SimpleHTTPRequestHandler):
    inbox = None
    ws_root = None
    tmp_dir = None
    lock = None

    def log_message(self, fmt, *args):
        sys.stderr.write("[serve] %s %s %s\n" % (self.command, self.path.split("?")[0], args[1] if len(args) > 1 else ""))

    def end_headers(self):
        # 다시 만든 화면이 바로 보이도록 캐시하지 않는다.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._local_host():
            return self._json(403, {"ok": False, "code": "HOST_REJECTED"})
        if self.path.split("?")[0] == "/inbox/status":
            # done: 검수 완료 버튼(POST /inbox/review/done)을 받는 서버라는 표시. 예전 서버에는 없어 버튼이 숨는다.
            # start: 검수 시작 신호(POST /signals/review_start)를 받는 서버라는 표시.
            out = {"ok": True, "kinds": list(KINDS), "done": True, "start": True}
            # ?run=<실행 ID>이면 그 실행의 완료 신호가 있는지 알려 준다(검수 화면이 잠금 여부를 정한다).
            run = urllib.parse.parse_qs(self.path.partition("?")[2]).get("run", [None])[0]
            if run is not None and _RUN_ID.match(run):
                out["done_signal"] = os.path.isfile(done_signal_path(self.ws_root, run))
            return self._json(200, out)
        return super().do_GET()

    def do_HEAD(self):
        if not self._local_host():
            # HEAD 응답에는 본문을 쓰지 않는다.
            self.send_response(403)
            self.send_header("Content-Length", "0")
            return self.end_headers()
        return super().do_HEAD()

    def _local_host(self):
        # Host를 로컬 이름(포트 무관)으로 묶어 DNS 재바인딩으로 들어온 요청을 막는다. Host가 없으면 거절한다.
        return (self.headers.get("Host") or "").rsplit(":", 1)[0].lower() in ("127.0.0.1", "localhost")

    def _same_origin(self):
        if not self._local_host():
            return False
        origin = self.headers.get("Origin")
        return bool(origin) and origin.split("://", 1)[-1] == self.headers.get("Host")

    def _read_json(self, limit):
        """같은 출처·JSON·크기 검사를 거친 요청 본문. 반환: (dict 또는 None, 오류 응답 인자 또는 None)."""
        if not self._same_origin():
            return None, (403, {"ok": False, "code": "ORIGIN_REJECTED"})
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return None, (415, {"ok": False, "code": "CONTENT_TYPE"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        if n <= 0 or n > limit:
            return None, (413, {"ok": False, "code": "BODY_SIZE"})
        try:
            doc = json.loads(self.rfile.read(n).decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return None, (400, {"ok": False, "code": "JSON_INVALID"})
        if not isinstance(doc, dict):
            return None, (400, {"ok": False, "code": "KIND_MISMATCH"})
        run_id = doc.get("run_id")
        if not isinstance(run_id, str) or not _RUN_ID.match(run_id):
            return None, (400, {"ok": False, "code": "RUN_ID_INVALID"})
        return doc, None

    def do_POST(self):
        if self.path.split("?")[0] == "/signals/review_start":
            return self._post_start()
        m = re.match(r"^/inbox/(review|compare)(/done)?$", self.path.split("?")[0])
        if not m or (m.group(2) and m.group(1) != "review"):
            return self._json(404, {"ok": False, "code": "NOT_FOUND"})
        kind, done = m.group(1), bool(m.group(2))
        doc, err = self._read_json(MAX_BODY)
        if err:
            return self._json(*err)
        if doc.get("kind") != kind:
            return self._json(400, {"ok": False, "code": "KIND_MISMATCH"})
        run_id = doc["run_id"]
        name = "%s_%s.json" % (kind, run_id)
        # 임시 파일은 inbox 밖에 써서 apply가 쓰다 만 파일을 집지 않게 한다.
        tmp = os.path.join(self.tmp_dir, ".inbox_%s.json" % kind)
        with self.lock:
            util.write_text(tmp, json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
            os.replace(tmp, os.path.join(self.inbox, name))
            if done:
                signal = self._write_done_signal(run_id, doc)
        if done:
            return self._json(200, {"ok": True, "saved": "inbox/" + name, "signal": "signals/" + signal})
        return self._json(200, {"ok": True, "saved": "inbox/" + name})

    def _post_start(self):
        """검수 시작 신호. 본문은 {"kind": "review_start", "run_id", "compare": bool}이고 신호에는 이 셋과 시각만 쓴다."""
        doc, err = self._read_json(MAX_START_BODY)
        if err:
            return self._json(*err)
        if doc.get("kind") != "review_start":
            return self._json(400, {"ok": False, "code": "KIND_MISMATCH"})
        if not isinstance(doc.get("compare", False), bool):
            return self._json(400, {"ok": False, "code": "COMPARE_INVALID"})
        run_id = doc["run_id"]
        sig = {"run_id": run_id, "started_at": datetime.datetime.now().isoformat(timespec="seconds"),
               "compare": bool(doc.get("compare", False))}
        path = start_signal_path(self.ws_root, run_id)
        tmp = os.path.join(self.tmp_dir, ".signal_review_start.json")
        with self.lock:
            util.write_text(tmp, json.dumps(sig, ensure_ascii=False) + "\n")
            os.replace(tmp, path)
        return self._json(200, {"ok": True, "signal": "signals/" + os.path.basename(path)})

    def _write_done_signal(self, run_id, doc):
        """검수 완료 신호. feedback 스킬이 이 파일을 기다린다. 본문 없이 건수만 쓴다(교정 파일을 쓴 뒤에 쓴다)."""
        def n(key):
            v = doc.get(key)
            return len(v) if isinstance(v, list) else 0
        sig = {"run_id": run_id, "done_at": datetime.datetime.now().isoformat(timespec="seconds"),
               "counts": {"edits": n("corrections"), "status": n("chunk_status"), "syns": n("synonyms"),
                          "revisits": n("revisits")}}
        path = done_signal_path(self.ws_root, run_id)
        tmp = os.path.join(self.tmp_dir, ".signal_review_done.json")
        util.write_text(tmp, json.dumps(sig, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
        return os.path.basename(path)


def make_server(ws_root, port, host="127.0.0.1"):
    inbox = os.path.join(ws_root, "inbox")
    os.makedirs(inbox, exist_ok=True)
    os.makedirs(os.path.dirname(done_signal_path(ws_root, "")), exist_ok=True)
    handler = type("Handler", (_Handler,), {"inbox": inbox, "ws_root": ws_root, "tmp_dir": ws_root,
                                            "lock": threading.Lock()})
    handler = functools.partial(handler, directory=os.path.join(ws_root, "screens"))
    return http.server.ThreadingHTTPServer((host, port), handler)


def serve(ws, port):
    srv = make_server(ws.root, port)
    print("[serve] 127.0.0.1:%d screens/ 제공, 교정 JSON은 inbox/에 저장" % srv.server_address[1], flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0
