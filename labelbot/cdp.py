"""표준 라이브러리 DevTools(CDP) 클라이언트. headless Edge/Chrome을 띄워 로컬 화면을 JPEG으로 캡처한다.

디버깅 포트는 127.0.0.1에만 열고, 프로필은 임시 폴더에 두었다가 닫을 때 지운다. 캡처 결과는
CDP가 돌려준 base64 문자열 그대로 넘긴다(디코딩한 bytes를 파일로 쓰지 않는다).
"""
import base64
import hashlib
import http.client
import json
import os
import shutil
import socket
import struct
import subprocess
import tempfile
import time
import urllib.parse

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class CdpError(Exception):
    def __init__(self, reason_code):
        super().__init__(reason_code)
        self.reason_code = reason_code


def browser_candidates():
    pf = [os.environ.get(k) for k in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
    out = []
    for base in [p for p in pf if p]:
        out.append(os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"))
    for base in [p for p in pf if p]:
        out.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
    out += ["/usr/bin/microsoft-edge", "/usr/bin/google-chrome", "/usr/bin/chromium",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    return out


def find_browser(path=None):
    for p in ([path] if path else browser_candidates()):
        if p and os.path.isfile(p):
            return p
    raise CdpError("RENDERER_MISSING")


# ---- WebSocket(RFC 6455) 최소 구현 ----------------------------------------------

def encode_frame(payload, opcode=1, mask_key=None):
    """클라이언트 프레임(항상 마스킹). FIN=1 단일 프레임."""
    mask_key = mask_key or os.urandom(4)
    n = len(payload)
    if n < 126:
        hdr = struct.pack("!BB", 0x80 | opcode, 0x80 | n)
    elif n < 65536:
        hdr = struct.pack("!BBH", 0x80 | opcode, 0x80 | 126, n)
    else:
        hdr = struct.pack("!BBQ", 0x80 | opcode, 0x80 | 127, n)
    masked = bytes(b ^ mask_key[i & 3] for i, b in enumerate(payload))
    return hdr + mask_key + masked


def read_frame(recv):
    """recv(n)은 정확히 n바이트를 돌려준다. 반환: (fin, opcode, payload)."""
    b1, b2 = recv(2)
    n = b2 & 0x7F
    if n == 126:
        n = struct.unpack("!H", recv(2))[0]
    elif n == 127:
        n = struct.unpack("!Q", recv(8))[0]
    mask = recv(4) if b2 & 0x80 else None
    data = recv(n)
    if mask:
        data = bytes(b ^ mask[i & 3] for i, b in enumerate(data))
    return bool(b1 & 0x80), b1 & 0x0F, data


def read_message(recv, send=None):
    """조각 프레임을 이어 붙인 메시지 하나. ping에는 pong으로 답한다."""
    parts, op = [], None
    while True:
        fin, opcode, data = read_frame(recv)
        if opcode == 8:
            raise CdpError("WS_CLOSED")
        if opcode == 9:
            if send:
                send(encode_frame(data, opcode=10))
            continue
        if opcode == 10:
            continue
        if opcode != 0:
            op = opcode
        parts.append(data)
        if fin:
            return op, b"".join(parts)


def accept_key(key):
    return base64.b64encode(hashlib.sha1((key + _WS_GUID).encode("ascii")).digest()).decode("ascii")


class WebSocket:
    def __init__(self, url, timeout):
        u = urllib.parse.urlsplit(url)
        if u.hostname not in ("127.0.0.1", "localhost"):
            raise CdpError("WS_HOST_REJECTED")
        try:
            self.sock = socket.create_connection((u.hostname, u.port or 80), timeout=timeout)
        except OSError:
            raise CdpError("WS_CONNECT_FAILED")
        self.buf = b""
        self.broken = False
        try:
            self._handshake(u)
        except BaseException:
            self.close()
            raise

    def _handshake(self, u):
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        path = u.path + ("?" + u.query if u.query else "")
        req = ("GET %s HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % (path, u.hostname, u.port or 80, key))
        self.sock.sendall(req.encode("ascii"))
        while b"\r\n\r\n" not in self.buf:
            self.buf += self._recv_some()
        head, self.buf = self.buf.split(b"\r\n\r\n", 1)
        lines = head.decode("latin-1").split("\r\n")
        hdrs = {k.strip().lower(): v.strip() for k, v in (l.split(":", 1) for l in lines[1:] if ":" in l)}
        if " 101 " not in lines[0] + " " or hdrs.get("sec-websocket-accept") != accept_key(key):
            raise CdpError("WS_HANDSHAKE_FAILED")

    def _recv_some(self):
        # 프레임 중간에 끊기면 남은 바이트로 다음 프레임을 읽을 수 없으므로 이 연결은 더 쓰지 않는다.
        if self.broken:
            raise CdpError("WS_CLOSED")
        try:
            chunk = self.sock.recv(65536)
        except (socket.timeout, TimeoutError):
            self.broken = True
            raise CdpError("RENDER_TIMEOUT")
        except OSError:
            self.broken = True
            raise CdpError("WS_CLOSED")
        if not chunk:
            self.broken = True
            raise CdpError("WS_CLOSED")
        return chunk

    def recv_exact(self, n):
        while len(self.buf) < n:
            self.buf += self._recv_some()
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def send_text(self, text):
        if self.broken:
            raise CdpError("WS_CLOSED")
        try:
            self.sock.sendall(encode_frame(text.encode("utf-8")))
        except OSError:
            self.broken = True
            raise CdpError("WS_CLOSED")

    def recv_text(self):
        _, data = read_message(self.recv_exact, self.sock.sendall)
        return data.decode("utf-8")

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


# ---- 브라우저와 페이지 ------------------------------------------------------------

class Page:
    def __init__(self, ws, timeout):
        self.ws = ws
        self.timeout = timeout
        self._id = 0

    def call(self, method, params=None):
        self._id += 1
        mid = self._id
        self.ws.send_text(json.dumps({"id": mid, "method": method, "params": params or {}}))
        while True:
            try:
                msg = json.loads(self.ws.recv_text())
            except (ValueError, UnicodeDecodeError):
                self.ws.broken = True
                raise CdpError("CDP_BAD_MESSAGE")
            if not isinstance(msg, dict):
                continue
            if msg.get("id") == mid:  # 이벤트(id 없음)는 버린다
                if "error" in msg:
                    raise CdpError("CDP_ERROR")
                return msg.get("result") or {}

    def evaluate(self, expr):
        r = self.call("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
        if "exceptionDetails" in r:
            raise CdpError("JS_ERROR")
        return (r.get("result") or {}).get("value")

    def open(self, url, width, height, ready_expr):
        self.call("Emulation.setDeviceMetricsOverride",
                  {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False})
        self.call("Page.navigate", {"url": url})
        end = time.monotonic() + self.timeout
        while time.monotonic() < end:
            try:
                if self.evaluate(ready_expr) is True:
                    return
            except CdpError as e:
                # 이동 중에는 실행 컨텍스트가 바뀌어 CDP 오류가 날 수 있다. 연결 오류만 올린다.
                if e.reason_code not in ("JS_ERROR", "CDP_ERROR"):
                    raise
            time.sleep(0.1)
        raise CdpError("RENDER_TIMEOUT")

    def capture_jpeg(self, rect, quality):
        """rect: {x, y, width, height}(CSS px). 반환: JPEG base64 문자열."""
        clip = {"x": rect["x"], "y": rect["y"], "width": rect["width"], "height": rect["height"], "scale": 1}
        r = self.call("Page.captureScreenshot", {"format": "jpeg", "quality": int(quality), "clip": clip,
                                                 "captureBeyondViewport": True, "fromSurface": True})
        data = r.get("data")
        if not data:
            raise CdpError("CAPTURE_EMPTY")
        return data


class Browser:
    def __init__(self, exe, timeout=30):
        self.timeout = timeout
        self._sockets = []
        self.proc = None
        self.profile = tempfile.mkdtemp(prefix="labelbot_cdp_")
        args = [exe, "--headless=new", "--remote-debugging-port=0", "--remote-debugging-address=127.0.0.1",
                "--user-data-dir=" + self.profile, "--no-first-run", "--no-default-browser-check",
                "--disable-extensions", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                "--disable-background-networking", "--disable-sync", "--disable-component-update", "about:blank"]
        try:
            self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                         stdin=subprocess.DEVNULL)
        except OSError:
            shutil.rmtree(self.profile, ignore_errors=True)
            raise CdpError("RENDERER_START_FAILED")
        try:
            self.port = self._wait_port()
            self.version = (self._http("GET", "/json/version") or {}).get("Browser", "")
        except BaseException:
            self.close()  # 띄운 브라우저와 임시 프로필을 남기지 않는다
            raise

    def _wait_port(self):
        p = os.path.join(self.profile, "DevToolsActivePort")
        end = time.monotonic() + self.timeout
        while time.monotonic() < end:
            if self.proc.poll() is not None:
                raise CdpError("RENDERER_START_FAILED")
            try:
                with open(p, encoding="ascii") as f:
                    first = f.readline().strip()
                if first.isdigit():
                    return int(first)
            except OSError:
                pass
            time.sleep(0.1)
        raise CdpError("RENDER_TIMEOUT")

    def _http(self, method, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=self.timeout)
        try:
            conn.request(method, path)
            resp = conn.getresponse()
            body = resp.read()
            if resp.status != 200:
                raise CdpError("CDP_HTTP_%d" % resp.status)
            return json.loads(body.decode("utf-8")) if body.strip() else None
        except (OSError, ValueError):
            raise CdpError("CDP_HTTP_FAILED")
        finally:
            conn.close()

    def new_page(self):
        info = self._http("PUT", "/json/new?about:blank") or {}
        url = info.get("webSocketDebuggerUrl")
        if not url:
            raise CdpError("CDP_NO_TARGET")
        ws = WebSocket(url, self.timeout)
        self._sockets.append(ws)
        return Page(ws, self.timeout)

    def close(self):
        for ws in getattr(self, "_sockets", []):
            ws.close()
        proc = getattr(self, "proc", None)
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
        # 브라우저가 파일 잠금을 늦게 푸는 경우가 있어 몇 번 다시 지운다.
        for _ in range(10):
            shutil.rmtree(self.profile, ignore_errors=True)
            if not os.path.exists(self.profile):
                break
            time.sleep(0.3)
