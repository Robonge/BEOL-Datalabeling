"""화면 서버: 작업 폴더 screens/를 보여 주고, 화면이 보낸 검수·대조 JSON을 inbox/에 쓴다.

브라우저는 내려받기 위치를 고를 수 없어 교정 파일이 Downloads로 가므로, 같은 서버가
inbox/<종류>_<실행 ID>.json을 직접 쓴다. 127.0.0.1에만 열고, 같은 출처(이 서버가 낸 화면)의
JSON 요청만 받는다. 쓰는 형식은 .json뿐이며, 내용을 읽어 반영하는 곳은 여전히
`apply`의 read_input 한 곳이다. 로그에는 요청 경로와 응답 코드만 남긴다.
"""
import functools
import http.server
import json
import os
import re
import sys
import threading

from labelbot import util

KINDS = ("review", "compare")
MAX_BODY = 5 * 1024 * 1024
_RUN_ID = re.compile(r"^[0-9A-Za-z-]{1,64}$")


class _Handler(http.server.SimpleHTTPRequestHandler):
    inbox = None
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
        if self.path.split("?")[0] == "/inbox/status":
            return self._json(200, {"ok": True, "kinds": list(KINDS)})
        return super().do_GET()

    def _same_origin(self):
        # Host까지 로컬 이름으로 묶어 DNS 재바인딩으로 들어온 요청도 막는다.
        origin, host = self.headers.get("Origin"), self.headers.get("Host") or ""
        if host.rsplit(":", 1)[0] not in ("127.0.0.1", "localhost"):
            return False
        return bool(origin) and origin.split("://", 1)[-1] == host

    def do_POST(self):
        m = re.match(r"^/inbox/(review|compare)$", self.path.split("?")[0])
        if not m:
            return self._json(404, {"ok": False, "code": "NOT_FOUND"})
        kind = m.group(1)
        if not self._same_origin():
            return self._json(403, {"ok": False, "code": "ORIGIN_REJECTED"})
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self._json(415, {"ok": False, "code": "CONTENT_TYPE"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        if n <= 0 or n > MAX_BODY:
            return self._json(413, {"ok": False, "code": "BODY_SIZE"})
        try:
            doc = json.loads(self.rfile.read(n).decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return self._json(400, {"ok": False, "code": "JSON_INVALID"})
        if not isinstance(doc, dict) or doc.get("kind") != kind:
            return self._json(400, {"ok": False, "code": "KIND_MISMATCH"})
        run_id = doc.get("run_id")
        if not isinstance(run_id, str) or not _RUN_ID.match(run_id):
            return self._json(400, {"ok": False, "code": "RUN_ID_INVALID"})
        name = "%s_%s.json" % (kind, run_id)
        # 임시 파일은 inbox 밖에 써서 apply가 쓰다 만 파일을 집지 않게 한다.
        tmp = os.path.join(self.tmp_dir, ".inbox_%s.json" % kind)
        with self.lock:
            util.write_text(tmp, json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
            os.replace(tmp, os.path.join(self.inbox, name))
        return self._json(200, {"ok": True, "saved": "inbox/" + name})


def make_server(ws_root, port, host="127.0.0.1"):
    inbox = os.path.join(ws_root, "inbox")
    os.makedirs(inbox, exist_ok=True)
    handler = type("Handler", (_Handler,), {"inbox": inbox, "tmp_dir": ws_root, "lock": threading.Lock()})
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
