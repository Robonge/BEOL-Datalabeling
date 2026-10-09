"""역방향 프록시 대응(L2): BEOL_ALLOWED_HOSTS · X-Forwarded-Host · BEOL_PATH_PREFIX · BEOL_NO_BROWSER (표준 라이브러리만 사용).

labelbot 화면 서버와 domain_engrbot 서버(보드 서버로 대표, 질문·검토·편집기 서버도 같은 _BaseHandler)를 loopback으로만 띄워
env를 바꿔 가며 확인한다. env가 없으면 지금과 같아야 한다.
"""
import contextlib
import glob
import http.client
import io as std_io
import json
import os
import re
import shutil
import tempfile
import threading
import unittest
from unittest import mock

from domain_engrbot import serve as de_serve
from domain_engrbot import taxonomy_board as tb
from labelbot import serve as lb_serve

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN = "20261009T000000-0001"
PROXY = "proxy.corp.example"
PREFIX = "/absproxy/8771"


def _env(**kw):
    """테스트마다 env를 고정한다(밖에 설정된 값이 섞이지 않게 비우고 시작)."""
    env = {"BEOL_ALLOWED_HOSTS": "", "BEOL_PATH_PREFIX": ""}
    env.update(kw)
    return mock.patch.dict(os.environ, env)


class _ProxyCases:
    """두 서버 공통 사례. 하위 클래스가 srv·GET_PATH·POST_PATH·body()를 정한다."""
    GET_PATH = POST_PATH = None

    def body(self):
        raise NotImplementedError

    def req(self, method, path, host=None, origin="self", fwd=None, body=None):
        host = "127.0.0.1:%d" % self.port if host is None else host
        h = {"Host": host}
        if origin == "self":
            h["Origin"] = "http://" + host
        elif origin:
            h["Origin"] = origin
        if fwd:
            h["X-Forwarded-Host"] = fwd
        data = None
        if method == "POST":
            data = json.dumps(self.body() if body is None else body).encode("utf-8")
            h["Content-Type"] = "application/json"
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        raw = r.read()
        c.close()
        try:
            code = json.loads(raw.decode("utf-8")).get("code")
        except (UnicodeDecodeError, ValueError, AttributeError):
            code = None
        return r.status, code

    # ① env 미설정: 지금과 같다
    def test_env_unset_keeps_current_rules(self):
        with _env():
            self.assertEqual(self.req("GET", self.GET_PATH)[0], 200)
            self.assertEqual(self.req("GET", self.GET_PATH, host="localhost:%d" % self.port)[0], 200)
            self.assertEqual(self.req("GET", self.GET_PATH, host="[::1]:%d" % self.port)[0], 200)
            self.assertEqual(self.req("GET", self.GET_PATH, host="%s:443" % PROXY), (403, "HOST_REJECTED"))
            self.assertEqual(self.req("POST", self.POST_PATH)[0], 200)
            # 같은 loopback이라도 다른 포트의 Origin(다른 로컬 앱)·Origin 없음·외부 Origin은 거절
            for origin in ("http://127.0.0.1:1", "http://localhost:%d" % self.port, None, "https://" + PROXY):
                self.assertEqual(self.req("POST", self.POST_PATH, origin=origin), (403, "ORIGIN_REJECTED"), origin)
            # 접두어 경로는 env가 없으면 그대로 없는 경로다
            self.assertEqual(self.req("GET", PREFIX + self.GET_PATH)[0], 404)

    # ② 외부 Host + 같은 Origin
    def test_external_host_same_origin_allowed(self):
        with _env(BEOL_ALLOWED_HOSTS=" Other.example , %s:443" % PROXY.upper()):
            self.assertEqual(self.req("GET", self.GET_PATH, host=PROXY)[0], 200)
            self.assertEqual(self.req("POST", self.POST_PATH, host=PROXY, origin="https://" + PROXY)[0], 200)
            self.assertEqual(self.req("POST", self.POST_PATH, host=PROXY + ":8443")[0], 200)

    # ③ 프록시가 Host를 localhost로 바꾸고 Origin은 외부 호스트
    def test_host_rewritten_to_loopback_origin_external(self):
        with _env(BEOL_ALLOWED_HOSTS=PROXY):
            self.assertEqual(self.req("POST", self.POST_PATH, origin="https://%s:8443" % PROXY)[0], 200)
            self.assertEqual(self.req("POST", self.POST_PATH, host="localhost:%d" % self.port,
                                      origin="https://" + PROXY)[0], 200)
        with _env():
            self.assertEqual(self.req("POST", self.POST_PATH, origin="https://" + PROXY), (403, "ORIGIN_REJECTED"))

    def test_forwarded_host_only_when_allowed(self):
        with _env():
            # 허용 목록 안의 X-Forwarded-Host와 Origin이 같으면 허용
            self.assertEqual(self.req("POST", self.POST_PATH, origin="http://localhost:8080", fwd="localhost:8080")[0], 200)
            # 목록 밖의 X-Forwarded-Host는 보지 않는다
            self.assertEqual(self.req("POST", self.POST_PATH, origin="http://evil.example", fwd="evil.example"),
                             (403, "ORIGIN_REJECTED"))
            # X-Forwarded-Host로 Host 검사를 넘을 수 없다(DNS 재바인딩 방어)
            self.assertEqual(self.req("GET", self.GET_PATH, host="evil.example", fwd="localhost")[0], 403)
            self.assertEqual(self.req("POST", self.POST_PATH, host="evil.example", origin="http://localhost",
                                      fwd="localhost")[0], 403)

    # ④ 목록 밖 Origin·Host 거절(사유 코드는 지금과 같다)
    def test_outside_list_rejected(self):
        with _env(BEOL_ALLOWED_HOSTS=PROXY):
            for host in ("evil.example", "%s.evil.example" % PROXY, "evil.%s" % PROXY, ""):
                self.assertEqual(self.req("GET", self.GET_PATH, host=host)[0], 403, host)
            for origin in ("https://evil.example", "https://%s.evil.example" % PROXY, "null", None):
                self.assertEqual(self.req("POST", self.POST_PATH, origin=origin), (403, "ORIGIN_REJECTED"), origin)
            self.assertEqual(self.req("POST", self.POST_PATH, host="evil.example", origin="https://" + PROXY),
                             (403, "ORIGIN_REJECTED"))

    # ⑤ /absproxy/8771/ 접두어
    def test_path_prefix_stripped(self):
        for prefix in (PREFIX, PREFIX + "/", PREFIX.lstrip("/")):
            with _env(BEOL_PATH_PREFIX=prefix):
                self.assertEqual(self.req("GET", PREFIX + self.GET_PATH)[0], 200, prefix)
                self.assertEqual(self.req("POST", PREFIX + self.POST_PATH)[0], 200, prefix)
                # 접두어를 떼고 넘기는 프록시도 그대로 동작
                self.assertEqual(self.req("GET", self.GET_PATH)[0], 200, prefix)
                # 경로 조각이 다르면 떼지 않는다
                self.assertEqual(self.req("GET", PREFIX + "0" + self.GET_PATH)[0], 404, prefix)


class LabelbotProxyTest(_ProxyCases, unittest.TestCase):
    GET_PATH, POST_PATH = "/review.html", "/signals/review_start"

    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp()
        os.makedirs(os.path.join(cls.root, "screens"))
        with open(os.path.join(cls.root, "screens", "review.html"), "w", encoding="utf-8") as f:
            f.write("<p>ok</p>")
        cls.srv = lb_serve.make_server(cls.root, 0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        shutil.rmtree(cls.root, ignore_errors=True)

    def body(self):
        return {"kind": "review_start", "run_id": RUN}

    def test_status_under_prefix(self):
        with _env(BEOL_PATH_PREFIX=PREFIX):
            self.assertEqual(self.req("GET", PREFIX + "/inbox/status?run=" + RUN)[0], 200)
            self.assertEqual(self.req("GET", PREFIX)[0], 200)   # 접두어만 오면 화면 폴더 루트


class DomainBoardProxyTest(_ProxyCases, unittest.TestCase):
    GET_PATH, POST_PATH = "/board/status", "/board/preview"

    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp()
        screen = os.path.join(cls.root, "taxonomy_board.html")
        with open(screen, "w", encoding="utf-8") as f:
            f.write("<p>board</p>")
        ok = (lambda doc: (200, {"ok": True}))
        cls.srv = de_serve.make_board_server(screen, ok, ok, 0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        shutil.rmtree(cls.root, ignore_errors=True)

    def body(self):
        return {"kind": de_serve.BOARD_KIND}


class HelperTest(unittest.TestCase):
    def test_helpers_match_between_packages(self):
        # domain_engrbot은 labelbot을 정해진 모듈로만 가져오므로 도우미를 옮겨 두었다. 두 벌이 같게 동작해야 한다.
        hosts = ["127.0.0.1:80", "LOCALHOST", "[::1]:8771", "::1", "", None, "evil.example:1", "127.0.0.1.evil.example",
                 PROXY, PROXY + ":443"]
        paths = ["/", PREFIX, PREFIX + "/", PREFIX + "?a=1", PREFIX + "/inbox/status", PREFIX + "0/x", "/other"]
        for env in ({}, {"BEOL_ALLOWED_HOSTS": PROXY, "BEOL_PATH_PREFIX": PREFIX + "/"}):
            with _env(**env):
                for h in hosts:
                    self.assertEqual(lb_serve.host_allowed(h), de_serve.host_allowed(h), (env, h))
                    for o in ("http://%s" % h, "https://" + PROXY, None):
                        self.assertEqual(lb_serve.origin_allowed(o, h, "localhost:9"),
                                         de_serve.origin_allowed(o, h, "localhost:9"), (env, h, o))
                for p in paths:
                    self.assertEqual(lb_serve.strip_prefix(p), de_serve.strip_prefix(p), (env, p))
        with _env(BEOL_PATH_PREFIX=PREFIX):
            self.assertEqual([lb_serve.strip_prefix(p) for p in paths],
                             ["/", "/", "/", "/?a=1", "/inbox/status", PREFIX + "0/x", "/other"])

    def test_no_browser(self):
        with mock.patch.dict(os.environ, {"BEOL_NO_BROWSER": "1"}):
            self.assertTrue(de_serve.no_browser())
        with mock.patch.dict(os.environ, {"BEOL_NO_BROWSER": "", "DISPLAY": "", "WAYLAND_DISPLAY": ""}):
            with mock.patch.object(de_serve.sys, "platform", "linux"):
                self.assertTrue(de_serve.no_browser())
            with mock.patch.dict(os.environ, {"DISPLAY": ":0"}), mock.patch.object(de_serve.sys, "platform", "linux"):
                self.assertFalse(de_serve.no_browser())
            for plat in ("win32", "darwin"):
                with mock.patch.object(de_serve.sys, "platform", plat):
                    self.assertFalse(de_serve.no_browser())

    def test_open_board_prints_url_without_browser(self):
        buf = std_io.StringIO()
        with mock.patch.dict(os.environ, {"BEOL_NO_BROWSER": "1"}), \
                mock.patch.object(tb.webbrowser, "open") as op, contextlib.redirect_stdout(buf):
            self.assertIsNone(tb.open_board("http://127.0.0.1:8795/"))
        op.assert_not_called()
        self.assertIn("http://127.0.0.1:8795/", buf.getvalue())


# ⑥ 화면이 루트 절대 주소를 쓰면 접두어 아래에서 깨진다
_ROOT_ABS = re.compile(r"""(?:fetch|api|post)\(\s*['"`]/(?!/)"""
                       r"""|(?:href|src|action)\s*=\s*['"]/(?!/)"""
                       r"""|location(?:\.href)?\s*=\s*['"`]/(?!/)"""
                       r"""|url\(\s*['"]?/(?!/)""")


class RelativeUrlTest(unittest.TestCase):
    def test_served_screens_have_no_root_absolute_urls(self):
        files = sorted(glob.glob(os.path.join(ROOT, "labelbot", "screens", "*.html"))
                       + glob.glob(os.path.join(ROOT, "domain_engrbot", "screens", "*.html")))
        self.assertGreaterEqual(len(files), 10)
        hits = []
        for path in files:
            with open(path, encoding="utf-8") as f:
                for n, line in enumerate(f, 1):
                    if _ROOT_ABS.search(line):
                        hits.append("%s:%d" % (os.path.relpath(path, ROOT), n))
        self.assertEqual(hits, [])

    def test_pattern_catches_root_absolute(self):
        for s in ('fetch("/inbox/status")', "fetch('/x'", 'href="/a"', "src='/b.png'", 'location.href = "/r"',
                  "url(/img.png)"):
            self.assertTrue(_ROOT_ABS.search(s), s)
        for s in ('fetch("inbox/status")', 'href="https://x/"', 'src="//cdn/x.js"', 'href="#top"', "url(data:x)"):
            self.assertFalse(_ROOT_ABS.search(s), s)


if __name__ == "__main__":
    unittest.main()
