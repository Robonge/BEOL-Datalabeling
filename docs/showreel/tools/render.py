"""Offline renderer for the BEOL AX showreel (stdlib only, Python 3.14).

Serves the page's folder over a private HTTP server on 127.0.0.1 (ES modules + import maps do not load
from file://), drives headless Chrome (fallback Edge) over the DevTools protocol with WebGL on, calls
window.REEL.seek(t) for every frame and captures PNGs. Frames go to a folder, a contact sheet,
reference-vs-ours comparison sheets, or straight into ffmpeg's stdin (H.264 mp4, optional motion blur).

Examples (paths with spaces must be quoted; write outputs to the scratch dir, never into the repo):
  python render.py --times 0.5,3,7.25 --frames-dir OUT
  python render.py --start 0 --end 15 --every 30 --contact OUT/sheet.png --cols 6 --thumb-width 320
  python render.py --compare "REF.png:2.0,C:/Downloads/original.mp4@12.5:7.25" --compare-out OUT/cmp
  python render.py --mp4 OUT/reel.mp4 --workers 3
  python render.py --mp4 OUT/reel.mp4 --subframes 4 --shutter 0.5 --audio OUT/music.wav --workers 4
  python render.py --times 1,4,9 --verify-determinism --frames-dir OUT

Page contract: window.REEL = {duration, fps, width, height, ready: Promise, seek(t)}; seek must be pure
(state depends only on t) and must render the WebGL canvas synchronously (preserveDrawingBuffer: true).
The page is opened as http://127.0.0.1:<port>/<page>?render=1.

WebGL: --gl auto (default) tries the real GPU through ANGLE/D3D11 and falls back to SwiftShader
(software, slow) when the page reports no WebGL. --gl gpu / --gl swiftshader force one.
"""
import argparse
import base64
import functools
import hashlib
import http.client  # code_engrbot: allow C2_TRANSPORT_BYPASS 127.0.0.1 DevTools(CDP) only, never leaves the host
import http.server
import json
import os
import pathlib
import queue
import shutil
import socket  # code_engrbot: allow C2_TRANSPORT_BYPASS 127.0.0.1 DevTools websocket only
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse

HERE = pathlib.Path(__file__).resolve().parent
REEL_DIR = HERE.parent
DEFAULT_PAGE = REEL_DIR / "showreel.html"
DEFAULT_FFMPEG = r"C:\Users\dltkd\AppData\Local\CapCut\Apps\9.5.0.4050\ffmpeg.exe"
DEFAULT_TMP = (r"C:\Users\dltkd\AppData\Local\Temp\claude\C--Users-dltkd-Desktop-261004-BEOL-AX-day2"
               r"\f214b36d-cb92-47c8-b169-da688c088fca\scratchpad\lookdev\infra")
BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
GL_FLAGS = {
    # real GPU through ANGLE on Direct3D 11 (headless=new keeps the GPU process when asked to)
    "gpu": ["--enable-gpu", "--ignore-gpu-blocklist", "--use-gl=angle", "--use-angle=d3d11",
            "--enable-webgl", "--enable-accelerated-2d-canvas"],
    # CPU rasterised WebGL; slow but works everywhere
    "swiftshader": ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--enable-webgl"],
    # plain DOM pages (contact sheets, labels)
    "nogl": ["--disable-gpu"],
}
_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class RenderError(Exception):
    pass


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- private static HTTP server

MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
        ".mjs": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
        ".json": "application/json", ".wasm": "application/wasm", ".svg": "image/svg+xml",
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
        ".woff2": "font/woff2", ".woff": "font/woff", ".ttf": "font/ttf", ".otf": "font/otf",
        ".glb": "model/gltf-binary", ".gltf": "model/gltf+json", ".hdr": "application/octet-stream",
        ".ktx2": "image/ktx2", ".wav": "audio/wav", ".mp3": "audio/mpeg", ".txt": "text/plain; charset=utf-8",
        ".md": "text/markdown; charset=utf-8"}


class _Handler(http.server.SimpleHTTPRequestHandler):
    """Serves `directory`, plus aliases {"vendor": "/abs/dir"} for paths that start with that prefix."""
    extensions_map = dict(MIME, **{"": "application/octet-stream"})  # never trust the Windows registry for .js

    def __init__(self, *a, aliases=None, **kw):
        self.aliases = aliases or {}
        super().__init__(*a, **kw)

    def translate_path(self, path):
        clean = urllib.parse.unquote(urllib.parse.urlsplit(path).path).lstrip("/")
        head, _, rest = clean.partition("/")
        if head in self.aliases:
            base = pathlib.Path(self.aliases[head]).resolve()
            target = (base / rest).resolve()
            if target == base or base in target.parents:
                return str(target)
            return str(base / "__forbidden__")
        return super().translate_path(path)

    def do_GET(self):
        if self.path.split("?")[0] == "/favicon.ico" and not (self.directory and os.path.isfile(
                os.path.join(self.directory, "favicon.ico"))):
            self.send_response(204)  # keep the console clean; pages rarely ship a favicon
            self.end_headers()
            return
        super().do_GET()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def log_message(self, fmt, *a):  # quiet; 404s are surfaced by the page's console instead
        if a and len(a) > 1 and str(a[1]).startswith(("4", "5")):
            log("  [http] %s %s" % (a[1], a[0]))


class StaticServer:
    def __init__(self, root, aliases=None):
        self.root = pathlib.Path(root).resolve()
        handler = functools.partial(_Handler, directory=str(self.root), aliases=aliases or {})
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
        self.thread.start()

    def url_for(self, path, query=""):
        rel = pathlib.Path(path).resolve().relative_to(self.root).as_posix()
        return "http://127.0.0.1:%d/%s%s" % (self.port, urllib.parse.quote(rel), ("?" + query) if query else "")

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


# ---------------------------------------------------------------- minimal websocket + CDP session

class CDP:
    """One websocket to one page target. Buffered reader; events are kept only if they are errors."""

    def __init__(self, ws_url, timeout=120):
        u = urllib.parse.urlsplit(ws_url)
        if u.hostname not in ("127.0.0.1", "localhost"):
            raise RenderError("refusing non-local websocket " + ws_url)
        self.sock = socket.create_connection((u.hostname, u.port), timeout=timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 << 20)
        self.rf = self.sock.makefile("rb", buffering=1 << 20)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        path = u.path + ("?" + u.query if u.query else "")
        req = ("GET %s HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % (path, u.hostname, u.port, key))
        self.sock.sendall(req.encode("ascii"))
        status = self.rf.readline().decode("latin-1")
        hdrs = {}
        while True:
            line = self.rf.readline().decode("latin-1").strip()
            if not line:
                break
            k, _, v = line.partition(":")
            hdrs[k.strip().lower()] = v.strip()
        want = base64.b64encode(hashlib.sha1((key + _WS_GUID).encode()).digest()).decode()
        if " 101 " not in status or hdrs.get("sec-websocket-accept") != want:
            raise RenderError("websocket handshake failed: " + status.strip())
        self._id = 0
        self.errors = []  # console errors / uncaught exceptions from the page

    def _send(self, payload, opcode=1):
        mask = os.urandom(4)
        n = len(payload)
        if n < 126:
            hdr = struct.pack("!BB", 0x80 | opcode, 0x80 | n)
        elif n < 65536:
            hdr = struct.pack("!BBH", 0x80 | opcode, 0x80 | 126, n)
        else:
            hdr = struct.pack("!BBQ", 0x80 | opcode, 0x80 | 127, n)
        w = ((n + 3) // 4) * 4
        masked = (int.from_bytes(payload.ljust(w, b"\0"), "big") ^ int.from_bytes(mask * (w // 4), "big")
                  ).to_bytes(w, "big")[:n] if n else b""
        self.sock.sendall(hdr + mask + masked)

    def _read_exact(self, n):
        b = self.rf.read(n)
        if b is None or len(b) != n:
            raise RenderError("websocket closed by browser")
        return b

    def _recv(self):
        parts = []
        while True:
            b1, b2 = self._read_exact(2)
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack("!H", self._read_exact(2))[0]
            elif n == 127:
                n = struct.unpack("!Q", self._read_exact(8))[0]
            if b2 & 0x80:
                self._read_exact(4)  # servers never mask; ignore defensively
            data = self._read_exact(n)
            op = b1 & 0x0F
            if op == 8:
                raise RenderError("websocket closed by browser")
            if op == 9:
                self._send(data, 10)
                continue
            if op == 10:
                continue
            parts.append(data)
            if b1 & 0x80:
                return b"".join(parts)

    def call(self, method, params=None):
        self._id += 1
        mid = self._id
        self._send(json.dumps({"id": mid, "method": method, "params": params or {}}).encode("utf-8"))
        while True:
            msg = json.loads(self._recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RenderError("%s failed: %s" % (method, msg["error"].get("message")))
                return msg.get("result") or {}
            self._event(msg)

    def _event(self, msg):
        m, p = msg.get("method"), msg.get("params") or {}
        if m == "Runtime.exceptionThrown":
            d = p.get("exceptionDetails") or {}
            ex = (d.get("exception") or {}).get("description") or d.get("text")
            self.errors.append("uncaught: %s (%s:%s)" % (ex, d.get("url", ""), d.get("lineNumber")))
        elif m == "Runtime.consoleAPICalled" and p.get("type") in ("error", "warning", "assert"):
            args = " ".join(str(a.get("value", a.get("description", ""))) for a in p.get("args", []))
            self.errors.append("console.%s: %s" % (p.get("type"), args))
        elif m == "Log.entryAdded":
            e = p.get("entry") or {}
            if e.get("level") in ("error", "warning") and "GPU stall" not in (e.get("text") or ""):
                self.errors.append("log.%s: %s %s" % (e.get("level"), e.get("text"), e.get("url", "")))

    def evaluate(self, expr):
        r = self.call("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
        if "exceptionDetails" in r:
            d = r["exceptionDetails"]
            raise RenderError("JS error: %s" % ((d.get("exception") or {}).get("description") or d.get("text")))
        return (r.get("result") or {}).get("value")

    def flush_errors(self, prefix=""):
        seen = set()
        for e in self.errors:
            if e not in seen:
                seen.add(e)
                log("  [page] " + prefix + e)
        n = len(seen)
        self.errors.clear()
        return n

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


class Browser:
    def __init__(self, exe=None, tmp_root=None, gl="nogl", timeout=60, width=1920, height=1080):
        cands = [exe] if exe else BROWSERS
        self.exe = next((p for p in cands if p and os.path.isfile(p)), None)
        if not self.exe:
            raise RenderError("no Chrome/Edge found (use --browser)")
        os.makedirs(tmp_root, exist_ok=True)
        self.profile = tempfile.mkdtemp(prefix="chrome_profile_", dir=tmp_root)
        self.timeout = timeout
        self.gl = gl
        self.cdps = []
        args = [self.exe, "--headless=new", "--remote-debugging-port=0", "--remote-debugging-address=127.0.0.1",
                "--user-data-dir=" + self.profile, "--no-first-run", "--no-default-browser-check",
                "--disable-extensions", "--hide-scrollbars", "--force-device-scale-factor=1",
                "--window-size=%d,%d" % (width, height), "--disable-lcd-text", "--force-color-profile=srgb",
                "--run-all-compositor-stages-before-draw", "--allow-file-access-from-files",
                "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
                "--disable-backgrounding-occluded-windows", "--disable-background-networking",
                "--disable-sync", "--disable-component-update", "--mute-audio", "--no-pings",
                "--disable-features=Translate,MediaRouter,OptimizationHints,CalculateNativeWinOcclusion"]
        args += GL_FLAGS[gl] + ["about:blank"]
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     stdin=subprocess.DEVNULL)
        try:
            self.port = self._wait_port()
            self.version = self._http("GET", "/json/version").get("Browser", "?")
        except BaseException:
            self.close()
            raise

    def _wait_port(self):
        p = os.path.join(self.profile, "DevToolsActivePort")
        end = time.monotonic() + self.timeout
        while time.monotonic() < end:
            if self.proc.poll() is not None:
                raise RenderError("browser exited during startup")
            try:
                with open(p, encoding="ascii") as f:
                    first = f.readline().strip()
                if first.isdigit():
                    return int(first)
            except OSError:
                pass
            time.sleep(0.05)
        raise RenderError("browser did not open a DevTools port")

    def _http(self, method, path):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=self.timeout)
        try:
            c.request(method, path)
            r = c.getresponse()
            body = r.read()
            if r.status != 200:
                raise RenderError("DevTools HTTP %d on %s" % (r.status, path))
            return json.loads(body) if body.strip() else {}
        finally:
            c.close()

    def new_page(self):
        info = self._http("PUT", "/json/new?about:blank")
        cdp = CDP(info["webSocketDebuggerUrl"], self.timeout)
        self.cdps.append(cdp)
        for dom in ("Runtime.enable", "Log.enable", "Page.enable"):
            cdp.call(dom)
        return cdp

    def close(self):
        for c in self.cdps:
            c.close()
        self.cdps = []
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=10)
        for _ in range(20):
            shutil.rmtree(self.profile, ignore_errors=True)
            if not os.path.exists(self.profile):
                break
            time.sleep(0.25)


_LIVE = []  # every Browser / ffmpeg / server we started, torn down in main()'s finally


# ---------------------------------------------------------------- reel page driver

GL_PROBE_JS = """(()=>{const c=document.createElement('canvas');const g=c.getContext('webgl2')||c.getContext('webgl');
  if(!g) return {ok:false};const d=g.getExtension('WEBGL_debug_renderer_info');
  return {ok:true,version:g.getParameter(g.VERSION),
          renderer:d?g.getParameter(d.UNMASKED_RENDERER_WEBGL):g.getParameter(g.RENDERER),
          maxSamples:g.getParameter(g.MAX_SAMPLES||0x8D57)};})()"""

LOAD_INFO_JS = """(async()=>{await window.REEL.ready; await document.fonts.ready;
  // document.fonts.check() is true for ANY local family name, so probe by measuring against generic fallbacks
  const fams=['Segoe UI Variable','Segoe UI Variable Display','Segoe UI Variable Text','Bahnschrift',
              'Cascadia Mono','Cascadia Code','DejaVu Sans Mono','Liberation Mono'];
  const cx=document.createElement('canvas').getContext('2d'), s='BEOL ax 0123 WMil -> {}';
  const has=f=>['monospace','serif','sans-serif'].every(g=>{cx.font='40px '+g;const a=cx.measureText(s).width;
      cx.font='40px "'+f+'", '+g;return Math.abs(cx.measureText(s).width-a)>0.5;});
  const txt=document.body?document.body.innerText+' '+document.title:'';
  const hangul=(txt.match(/[\\u1100-\\u11FF\\u3130-\\u318F\\uAC00-\\uD7AF]/g)||[]).length;
  return {duration:REEL.duration,fps:REEL.fps,width:REEL.width,height:REEL.height,
          fonts:Object.fromEntries(fams.map(f=>[f,has(f)])), hangul,
          sw:document.documentElement.scrollWidth, sh:document.documentElement.scrollHeight};})()"""


def open_reel(cdp, url, width, height, dsf, timeout):
    cdp.call("Emulation.setDeviceMetricsOverride",
             {"width": width, "height": height, "deviceScaleFactor": dsf, "mobile": False})
    cdp.call("Emulation.setDefaultBackgroundColorOverride", {"color": {"r": 0, "g": 0, "b": 0, "a": 1}})
    cdp.call("Page.navigate", {"url": url})
    end = time.monotonic() + timeout
    while True:
        try:
            if cdp.evaluate("document.readyState==='complete' && !!(window.REEL && window.REEL.ready)"):
                break
        except RenderError:
            pass  # context swapped during navigation
        if time.monotonic() > end:
            cdp.flush_errors()
            raise RenderError("window.REEL.ready never appeared (page error? see [page] lines)")
        time.sleep(0.05)
    info = cdp.evaluate(LOAD_INFO_JS)
    info["gl"] = cdp.evaluate(GL_PROBE_JS)
    cdp.flush_errors()
    return info


SEEK_JS = "(async()=>{const r=window.REEL.seek(%r); if(r&&r.then) await r; return 1;})()"


def capture(cdp, t, fmt="png"):
    cdp.evaluate(SEEK_JS % float(t))
    params = {"format": fmt, "fromSurface": True, "captureBeyondViewport": False, "optimizeForSpeed": True}
    if fmt == "jpeg":
        params["quality"] = 95
    data = cdp.call("Page.captureScreenshot", params).get("data")
    if not data:
        raise RenderError("empty screenshot at t=%.4f" % t)
    return base64.b64decode(data)


def boot_worker(args, url, gl):
    b = Browser(args.browser, args.tmp_dir, gl=gl, width=args.width, height=args.height)
    _LIVE.append(b)
    c = b.new_page()
    info = open_reel(c, url, args.width, args.height, args.dsf, args.load_timeout)
    return b, c, info


def gl_usable(info, gl):
    g = info.get("gl") or {}
    if not g.get("ok"):
        return False
    if gl == "gpu" and "swiftshader" in (g.get("renderer") or "").lower():
        return False  # asked for the GPU, silently got the software path
    return True


class Pool:
    """K browsers; job i goes to worker i % K, so reading worker queues round-robin yields frames in order."""

    def __init__(self, args, url, k):
        self.k = k
        self.workers = []
        self.url = url
        self.args = args
        modes = ["gpu", "swiftshader"] if args.gl == "auto" else [args.gl]
        last = None
        for gl in modes:  # decide the GL mode on worker 0, then boot the rest in parallel with it
            b, c, info = boot_worker(args, url, gl)
            if gl_usable(info, gl) or gl == modes[-1]:
                self.gl = gl
                break
            last = info.get("gl")
            log("  GL mode %s unusable (%s); falling back" % (gl, last))
            b.close()
        self.workers.append((0, b, c, info))
        errs = []

        def boot(i):
            try:
                bb, cc, ii = boot_worker(args, url, self.gl)
                self.workers.append((i, bb, cc, ii))
            except Exception as e:  # noqa: BLE001 - report every boot failure
                errs.append(e)

        ths = [threading.Thread(target=boot, args=(i,)) for i in range(1, k)]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        if errs:
            raise errs[0]
        self.workers.sort(key=lambda w: w[0])
        for _, _, c, _ in self.workers:
            capture(c, 0.0)  # warm-up: shader compile + first raster are slow and occasionally incomplete
            c.flush_errors("warm-up ")
        self.browser_version = self.workers[0][1].version
        self.info = self.workers[0][3]

    def run(self, times, fmt="png"):
        """Generator of (index, t, bytes) in order."""
        k = self.k
        qs = [queue.Queue(maxsize=6) for _ in range(k)]
        stop = threading.Event()

        def work(w):
            _, _, c, _ = self.workers[w]
            try:
                for i in range(w, len(times), k):
                    if stop.is_set():
                        return
                    qs[w].put((i, times[i], capture(c, times[i], fmt)))
                    if c.errors:
                        c.flush_errors("t=%.3f " % times[i])
            except Exception as e:  # noqa: BLE001 - forwarded to the consumer
                qs[w].put(e)

        ths = [threading.Thread(target=work, args=(w,), daemon=True) for w in range(k)]
        for t in ths:
            t.start()
        try:
            for i in range(len(times)):
                item = qs[i % k].get()
                if isinstance(item, Exception):
                    raise item
                yield item
        finally:
            stop.set()
            for q in qs:  # unblock producers
                while not q.empty():
                    q.get_nowait()

    def close(self):
        for _, b, _, _ in self.workers:
            b.close()
        self.workers = []


# ---------------------------------------------------------------- ffmpeg

def ffmpeg_exe(args):
    for p in (args.ffmpeg, DEFAULT_FFMPEG, shutil.which("ffmpeg")):
        if p and os.path.isfile(p):
            return p
    raise RenderError("ffmpeg not found (use --ffmpeg)")


def encoder_args(name, q, fps):
    gop = ["-g", str(int(fps * 2)), "-bf", "2"]
    if name == "h264_qsv":
        # global_quality alone = ICQ (constant quality); 16 ~ visually lossless for flat motion graphics.
        return ["-c:v", "h264_qsv", "-preset", "veryslow", "-global_quality", str(q), "-look_ahead", "0",
                "-profile:v", "high"] + gop
    if name == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p7", "-tune", "hq", "-rc", "vbr", "-cq", str(q),
                "-b:v", "0", "-maxrate", "60M", "-bufsize", "120M", "-profile:v", "high"] + gop
    if name == "h264_amf":
        return ["-c:v", "h264_amf", "-quality", "quality", "-rc", "cqp", "-qp_i", str(q), "-qp_p", str(q + 2),
                "-qp_b", str(q + 4), "-profile:v", "high"] + gop
    if name == "h264_mf":  # software MediaFoundation: Constrained Baseline only, so give it bits
        return ["-c:v", "h264_mf", "-rate_control", "cbr", "-b:v", "40M", "-scenario", "archive"] + gop[:2]
    raise RenderError("unknown encoder " + name)


ENCODER_ORDER = ["h264_qsv", "h264_nvenc", "h264_amf", "h264_mf"]  # this PC: Intel Arc 140V -> qsv; mf = software fallback
COLOR_TAGS = ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv"]


def pick_encoder(ff, want, q, fps, verbose=False):
    order = ENCODER_ORDER if want == "auto" else [want]
    for name in order:
        cmd = [ff, "-hide_banner", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=1920x1080:r=60:d=0.2",
               "-pix_fmt", "yuv420p"] + encoder_args(name, q, fps) + ["-f", "null", "-"]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if verbose:
            log("  encoder probe %-10s %s" % (name, "OK" if r.returncode == 0 else
                                              "fail: " + r.stderr.decode("utf-8", "replace").strip()[-120:]))
        if r.returncode == 0:
            return name
    raise RenderError("no working H.264 encoder among %s" % order)


def start_ffmpeg(args, ff, enc, in_rate, n_sub):
    vf = []
    if n_sub > 1:
        # average N consecutive subframes, keep the last of each group, retime to the output rate
        vf += ["format=gbrp", "tmix=frames=%d:weights=%s" % (n_sub, " ".join(["1"] * n_sub)),
               "select=eq(mod(n\\,%d)\\,%d)" % (n_sub, n_sub - 1), "setpts=N/(%s*TB)" % fmt_num(args.fps)]
    if args.out_width:
        vf.append("scale=%d:-2:flags=lanczos" % args.out_width)
    vf.append("scale=out_color_matrix=bt709:out_range=tv:flags=accurate_rnd+full_chroma_int,format=yuv420p")
    cmd = [ff, "-hide_banner", "-v", "warning", "-nostats", "-y",
           "-f", "image2pipe", "-c:v", "png", "-framerate", fmt_num(in_rate), "-i", "-"]
    if args.audio:
        cmd += ["-i", args.audio]
    cmd += ["-vf", ",".join(vf), "-r", fmt_num(args.fps)] + encoder_args(enc, args.quality, args.fps) + COLOR_TAGS
    cmd += ["-map", "0:v:0"]
    if args.audio:
        cmd += ["-map", "1:a:0", "-c:a", "aac", "-b:a", "320k", "-ar", "48000", "-shortest"]
    cmd += ["-movflags", "+faststart", args.mp4]
    log("ffmpeg: " + " ".join('"%s"' % c if " " in c else c for c in cmd))
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    _LIVE.append(p)
    return p


def fmt_num(x):
    return ("%d" % x) if float(x).is_integer() else ("%.6f" % x)


def verify_mp4(ff, path):
    r = subprocess.run([ff, "-hide_banner", "-v", "error", "-i", path, "-f", "null", "-"], capture_output=True)
    info = subprocess.run([ff, "-hide_banner", "-i", path], capture_output=True, text=True, errors="replace").stderr
    lines = [l.strip() for l in info.splitlines() if "Duration" in l or "Stream" in l]
    ok = r.returncode == 0 and not r.stderr.strip()
    return ok, lines, r.stderr.decode("utf-8", "replace")[-800:]


def run_ff(ff, cmd):
    r = subprocess.run([ff, "-hide_banner", "-v", "error", "-y"] + cmd, capture_output=True)
    if r.returncode != 0:
        raise RenderError("ffmpeg failed: %s" % r.stderr.decode("utf-8", "replace").strip()[-600:])


# ---------------------------------------------------------------- DOM-rendered helpers (this ffmpeg has no drawtext)

SHEET_CSS = """body{margin:0;background:#0d0d0d;color:#c9c9c9;font:13px 'Cascadia Mono',monospace}
h1{font:600 14px 'Cascadia Mono',monospace;margin:0 0 12px;color:#ff7a1a;letter-spacing:.06em}"""


def screenshot_html(args, html, w, h, out_png):
    """Render a small static HTML string at w x h and save a PNG (labels, contact sheets)."""
    out_png = pathlib.Path(out_png).resolve()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    tmp_html = out_png.with_name(out_png.stem + ".tmp.html")
    tmp_html.write_text(html, encoding="utf-8")
    b = Browser(args.browser, args.tmp_dir, gl="nogl", width=w, height=h)
    _LIVE.append(b)
    try:
        c = b.new_page()
        c.call("Emulation.setDeviceMetricsOverride", {"width": w, "height": h, "deviceScaleFactor": 1, "mobile": False})
        c.call("Page.navigate", {"url": tmp_html.as_uri()})
        c.evaluate("""new Promise(r=>{const go=()=>Promise.all([...document.images].map(i=>i.decode().catch(()=>0)))
            .then(()=>document.fonts.ready).then(()=>r(1)); document.readyState==='complete'?go():addEventListener('load',go)})""")
        data = c.call("Page.captureScreenshot", {"format": "png", "fromSurface": True})["data"]
        out_png.write_bytes(base64.b64decode(data))
    finally:
        b.close()
        tmp_html.unlink(missing_ok=True)
    return out_png


def contact_sheet(args, frames):
    """frames: list of (t, png_path). Lays them out in an HTML grid and screenshots it."""
    cols = max(1, args.cols)
    tw = args.thumb_width
    th = round(tw * args.height / args.width)
    gap, pad, label = 10, 16, 26
    rows = (len(frames) + cols - 1) // cols
    W = pad * 2 + cols * tw + (cols - 1) * gap
    H = pad * 2 + rows * (th + label) + (rows - 1) * gap + 34
    cells = "".join(
        '<figure><img src="%s"><figcaption><b>%.3fs</b><span>f%d</span></figcaption></figure>'
        % (pathlib.Path(p).resolve().as_uri(), t, round(t * args.fps)) for t, p in frames)
    title = "%s  |  %d frames  |  %s" % (pathlib.Path(args.page).name, len(frames), time.strftime("%Y-%m-%d %H:%M"))
    html = """<!doctype html><meta charset=utf-8><style>%s
body{padding:%dpx;width:%dpx;box-sizing:border-box}
main{display:grid;grid-template-columns:repeat(%d,%dpx);gap:%dpx}
figure{margin:0}img{display:block;width:%dpx;height:%dpx;background:#000;outline:1px solid #2a2a2a}
figcaption{height:%dpx;display:flex;justify-content:space-between;align-items:center;padding:0 2px}
b{color:#fff;font-weight:600}span{color:#8a8a8a}</style><h1>%s</h1><main>%s</main>""" % (
        SHEET_CSS, pad, W, cols, tw, gap, tw, th, label, title, cells)
    out = screenshot_html(args, html, W, H, args.contact)
    log("contact sheet: %s (%dx%d, %d frames)" % (out, W, H, len(frames)))


def parse_compare(spec):
    """'REF:T,REF2:T2' -> [(ref, ref_time_or_None, t)]. REF is an image, or 'video.mp4@seconds'."""
    out = []
    for item in [s.strip() for s in spec.split(",") if s.strip()]:
        ref, sep, t = item.rpartition(":")
        if not sep or not ref:
            raise RenderError("bad --compare item %r (want REF:T)" % item)
        ref_t = None
        base, at, rt = ref.rpartition("@")
        if at and base.lower().endswith((".mp4", ".mov", ".webm", ".mkv")):
            ref, ref_t = base, float(rt)
        if not os.path.isfile(ref):
            raise RenderError("compare reference not found: %s" % ref)
        out.append((ref, ref_t, float(t)))
    return out


def compare_sheets(args, ff, pairs, ours):
    """pairs: [(ref, ref_t, t)]; ours: {t: png_path}. Writes cmp_NN_tT.png = label bar over [ref | ours]."""
    out_dir = pathlib.Path(args.compare_out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    W, H, LB = 960, 540, 44
    results = []
    for n, (ref, ref_t, t) in enumerate(pairs):
        stem = "cmp_%02d_t%06.3f" % (n, t)
        ref_png = out_dir / (stem + ".ref.tmp.png")
        if ref_t is not None:
            run_ff(ff, ["-ss", "%.4f" % ref_t, "-i", ref, "-frames:v", "1", str(ref_png)])
        else:
            shutil.copyfile(ref, ref_png)
        ref_label = "REFERENCE" + ("  %s @ %.2fs" % (pathlib.Path(ref).name, ref_t) if ref_t is not None
                                   else "  " + pathlib.Path(ref).name)
        html = """<!doctype html><meta charset=utf-8><style>%s
body{width:%dpx;height:%dpx;display:flex;background:#0d0d0d}
div{flex:1;display:flex;align-items:center;gap:12px;padding:0 18px;font:600 16px 'Cascadia Mono',monospace;
letter-spacing:.08em;color:#fff;border-bottom:2px solid #1f1f1f}
div+div{border-left:2px solid #1f1f1f}i{width:10px;height:10px;background:#8a8a8a}div+div i{background:#ff7a1a}
small{font-weight:400;color:#8a8a8a;letter-spacing:0}</style>
<div><i></i>%s</div><div><i></i>OURS t=%.3fs <small>f%d</small></div>""" % (
            SHEET_CSS, 2 * W, LB, ref_label.replace("&", "&amp;").replace("<", "&lt;"), t, round(t * args.fps))
        label_png = screenshot_html(args, html, 2 * W, LB, out_dir / (stem + ".label.tmp.png"))
        out_png = out_dir / (stem + ".png")
        fc = ("[0:v]scale=%d:%d:flags=lanczos,setsar=1,format=rgb24[a];"
              "[1:v]scale=%d:%d:flags=lanczos,setsar=1,format=rgb24[b];"
              "[a][b]hstack=inputs=2[ab];[2:v]format=rgb24[l];[l][ab]vstack=inputs=2" % (W, H, W, H))
        run_ff(ff, ["-i", str(ref_png), "-i", str(ours[t]), "-i", str(label_png),
                    "-filter_complex", fc, "-frames:v", "1", str(out_png)])
        ref_png.unlink(missing_ok=True)
        label_png.unlink(missing_ok=True)
        results.append(out_png)
        log("compare: %s" % out_png)
    return results


# ---------------------------------------------------------------- main

def build_times(args, duration):
    if args.times:
        return [float(x) for x in args.times.split(",") if x.strip()]
    end = duration if args.end is None else args.end
    n = int(round((end - args.start) * args.fps))
    return [args.start + i / args.fps for i in range(0, n, max(1, args.every))]


def resolve_server(args):
    page = pathlib.Path(args.page).resolve()
    if not page.is_file():
        raise RenderError("page not found: %s" % page)
    root = pathlib.Path(args.root).resolve() if args.root else page.parent
    aliases = {}
    for a in args.alias or []:
        k, _, v = a.partition("=")
        aliases[k.strip("/")] = str(pathlib.Path(v).resolve())
    if "vendor" not in aliases and not (root / "vendor").is_dir() and (REEL_DIR / "vendor").is_dir():
        aliases["vendor"] = str(REEL_DIR / "vendor")  # test pages outside the repo still get three.js
    srv = StaticServer(root, aliases)
    _LIVE.append(srv)
    return srv, srv.url_for(page, "render=1" + (("&" + args.query) if getattr(args, "query", "") else ""))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--page", default=str(DEFAULT_PAGE), help="reel HTML (default: ../showreel.html)")
    ap.add_argument("--query", default="", help="extra URL query appended after render=1 (look-dev switches, e.g. bloom=0)")
    ap.add_argument("--root", help="HTTP server root (default: the page's folder)")
    ap.add_argument("--alias", action="append", help="extra served folder PREFIX=DIR (repeatable); "
                    "'vendor' is auto-mapped to docs/showreel/vendor when the root has none")
    ap.add_argument("--frames-dir", help="write PNG frames here (f_00000.png by frame number, or t_1.250.png for --times)")
    ap.add_argument("--fps", type=float, default=None, help="default: REEL.fps (60)")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float, default=None, help="exclusive; default: REEL.duration")
    ap.add_argument("--every", type=int, default=1, help="keep every Nth frame (frames-dir/contact only)")
    ap.add_argument("--times", help="comma list of seconds, e.g. 0.5,1.2,7")
    ap.add_argument("--contact", help="contact sheet PNG path")
    ap.add_argument("--cols", type=int, default=6)
    ap.add_argument("--thumb-width", type=int, default=320)
    ap.add_argument("--compare", help="REF:T,... reference image (or video.mp4@sec) vs our frame at T")
    ap.add_argument("--compare-out", help="folder for comparison sheets (default: next to --frames-dir or tmp-dir)")
    ap.add_argument("--mp4", help="encode H.264 1080p mp4 (frames piped to ffmpeg)")
    ap.add_argument("--audio", help="wav/aac to mux (AAC 320k, -shortest)")
    ap.add_argument("--subframes", type=int, default=1, help="motion blur: N subframes averaged per output frame")
    ap.add_argument("--shutter", type=float, default=0.5, help="shutter as fraction of a frame (0.5 = 180 deg), centred on t")
    ap.add_argument("--workers", type=int, default=1, help="parallel headless browsers")
    ap.add_argument("--encoder", default="auto", help="auto|h264_nvenc|h264_qsv|h264_amf|h264_mf")
    ap.add_argument("--quality", type=int, default=16, help="ICQ/CQ value (lower = better; 14-20 sensible)")
    ap.add_argument("--out-width", type=int, default=None, help="downscale mp4 (e.g. 960 for previews)")
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--dsf", type=float, default=1.0, help="deviceScaleFactor; 0.5 = fast half-res preview with 1080p layout")
    ap.add_argument("--gl", default="auto", choices=["auto", "gpu", "swiftshader"],
                    help="WebGL backend: real GPU via ANGLE/D3D11, or SwiftShader (software)")
    ap.add_argument("--gpu", action="store_true", help=argparse.SUPPRESS)  # old flag; same as --gl gpu
    ap.add_argument("--hash", action="store_true", help="print sha256 of every captured frame")
    ap.add_argument("--verify-determinism", action="store_true",
                    help="capture the frame list forwards, then backwards, and require identical PNG bytes")
    ap.add_argument("--browser", help="browser exe (default: Chrome, then Edge)")
    ap.add_argument("--ffmpeg", help="ffmpeg exe (default: CapCut build)")
    ap.add_argument("--tmp-dir", default=os.environ.get("SHOWREEL_TMP") or DEFAULT_TMP,
                    help="where temporary Chrome profiles live (env SHOWREEL_TMP)")
    ap.add_argument("--load-timeout", type=float, default=60)
    args = ap.parse_args(argv)
    if args.gpu:
        args.gl = "gpu"
    if not (args.frames_dir or args.contact or args.mp4 or args.compare):
        ap.error("nothing to do: give --frames-dir, --contact, --compare and/or --mp4")
    if args.mp4 and args.times:
        ap.error("--mp4 renders a contiguous range; use --start/--end, not --times")
    pairs = parse_compare(args.compare) if args.compare else []
    if pairs and not args.compare_out:
        args.compare_out = os.path.join(args.frames_dir or args.tmp_dir, "compare")

    t0 = time.monotonic()
    pool = None
    tmp_frames = None
    page_errors = 0
    try:
        srv, url = resolve_server(args)
        k = max(1, args.workers)
        pool = Pool(args, url, k)
        info = pool.info
        g = info.get("gl") or {}
        log("browser: %s x%d | GL mode %s | %s" % (pool.browser_version, k, pool.gl,
                                                   g.get("renderer") if g.get("ok") else "NO WEBGL"))
        log("page: %s" % url)
        log("REEL: duration=%s fps=%s %sx%s" % (info["duration"], info["fps"], info["width"], info["height"]))
        log("fonts: " + ", ".join("%s=%s" % (f, "yes" if v else "NO") for f, v in info["fonts"].items()))
        if info.get("hangul"):
            log("  WARNING: %d Hangul characters in the page text (on-screen text must be English)" % info["hangul"])
        if info.get("sw", 0) > args.width or info.get("sh", 0) > args.height:
            log("  WARNING: document is %sx%s (> viewport) - check overflow:hidden" % (info["sw"], info["sh"]))
        if args.fps is None:
            args.fps = float(info.get("fps") or 60)
        duration = float(info.get("duration") or 15)
        log("boot %.1fs" % (time.monotonic() - t0))

        if args.mp4:
            render_mp4(args, pool, duration)

        if args.frames_dir or args.contact or pairs:
            out_dir = args.frames_dir
            if not out_dir:
                base = pathlib.Path(args.contact or args.compare_out).resolve()
                base = base.parent if args.contact else base
                base.mkdir(parents=True, exist_ok=True)
                tmp_frames = tempfile.mkdtemp(prefix="frames_", dir=str(base))
                out_dir = tmp_frames
            os.makedirs(out_dir, exist_ok=True)
            times = build_times(args, duration) if (args.frames_dir or args.contact) else []
            n_main = len(times)  # frames for --frames-dir/--contact; compare-only times are appended after
            for _, _, t in pairs:
                if t not in times:
                    times.append(t)
            saved, hashes = [], {}
            t1 = time.monotonic()
            for i, t, png in pool.run(times):
                name = ("t_%07.3f.png" % t) if args.times or i >= n_main else ("f_%05d.png" % round(t * args.fps))
                p = os.path.join(out_dir, name)
                with open(p, "wb") as f:
                    f.write(png)
                saved.append((t, p))
                hashes[i] = hashlib.sha256(png).hexdigest()
                if args.hash:
                    log("  t=%.4f sha256=%s %s" % (t, hashes[i][:16], name))
                progress(i + 1, len(times), t1)
            el = time.monotonic() - t1
            log("frames: %d in %.1fs = %.0f ms/frame -> %s" % (len(times), el, 1000 * el / max(1, len(times)), out_dir))

            if args.verify_determinism:
                rev = list(reversed(times))
                bad = 0
                t2 = time.monotonic()
                for j, t, png in pool.run(rev):
                    i = len(times) - 1 - j
                    h = hashlib.sha256(png).hexdigest()
                    if h != hashes[i]:
                        bad += 1
                        log("  NONDETERMINISTIC t=%.4f  %s != %s" % (t, h[:16], hashes[i][:16]))
                log("determinism: %d/%d frames identical when re-rendered in reverse order (%.1fs)" % (
                    len(times) - bad, len(times), time.monotonic() - t2))
                if bad:
                    raise RenderError("seek(t) is not deterministic (%d frames differ)" % bad)

            for _, _, c, _ in pool.workers:
                page_errors += c.flush_errors()
            pool.close()
            pool = None
            if args.contact:
                contact_sheet(args, saved[:n_main])
            if pairs:
                compare_sheets(args, ffmpeg_exe(args), pairs, {t: p for t, p in saved})
        log("total %.1fs%s" % (time.monotonic() - t0, "" if not page_errors else " | %d page errors" % page_errors))
        return 0
    finally:
        if pool:
            pool.close()
        for x in reversed(_LIVE):
            try:
                if isinstance(x, subprocess.Popen) and x.poll() is None:
                    x.kill()
                elif isinstance(x, (Browser, StaticServer)):
                    x.close()
            except Exception:  # noqa: BLE001 - best-effort teardown
                pass
        if tmp_frames:
            shutil.rmtree(tmp_frames, ignore_errors=True)


_last = [0.0]


def progress(done, total, t1, every=2.0):
    now = time.monotonic()
    if done == total or now - _last[0] >= every:
        _last[0] = now
        el = now - t1
        rate = done / el if el > 0 else 0
        eta = (total - done) / rate if rate else 0
        log("  %5d/%d  %5.1f%%  %6.1f ms/frame  eta %5.1fs" % (done, total, 100 * done / total, 1000 / rate if rate else 0, eta))


def render_mp4(args, pool, duration):
    ff = ffmpeg_exe(args)
    enc = pick_encoder(ff, args.encoder, args.quality, args.fps, verbose=True)
    end = duration if args.end is None else args.end
    n_out = int(round((end - args.start) * args.fps))
    n_sub = max(1, args.subframes)
    times = []
    for i in range(n_out):
        t = args.start + i / args.fps
        for k in range(n_sub):
            off = ((k + 0.5) / n_sub - 0.5) * args.shutter / args.fps if n_sub > 1 else 0.0
            times.append(min(max(t + off, 0.0), max(0.0, duration - 1e-6)))
    log("mp4: %d frames x %d subframes = %d captures, encoder %s q%d -> %s" % (n_out, n_sub, len(times), enc,
                                                                               args.quality, args.mp4))
    os.makedirs(os.path.dirname(os.path.abspath(args.mp4)) or ".", exist_ok=True)
    proc = start_ffmpeg(args, ff, enc, args.fps * n_sub, n_sub)
    t1 = time.monotonic()
    try:
        for i, t, png in pool.run(times):
            proc.stdin.write(png)
            progress(i + 1, len(times), t1)
        proc.stdin.close()
    except (BrokenPipeError, OSError) as e:
        raise RenderError("ffmpeg stopped accepting frames (%s); see its messages above" % e)
    rc = proc.wait()
    el = time.monotonic() - t1
    if rc != 0:
        raise RenderError("ffmpeg exited %d" % rc)
    log("captured+encoded %d captures in %.1fs = %.0f ms/capture, %.0f ms/output frame" % (
        len(times), el, 1000 * el / len(times), 1000 * el / n_out))
    ok, lines, err = verify_mp4(ff, args.mp4)
    for l in lines:
        log("  " + l)
    log("  decode check: %s %s" % ("OK" if ok else "FAILED", err.strip()))
    if not ok:
        raise RenderError("output did not decode cleanly")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RenderError as e:
        log("render.py: error: %s" % e)
        sys.exit(2)
    except KeyboardInterrupt:
        log("render.py: interrupted")
        sys.exit(130)
