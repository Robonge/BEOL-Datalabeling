"""외부 전송 가드(BEOL_ALLOWED_HOST_SUFFIXES)와 범용 request(). 네트워크는 127.0.0.1 로컬 서버만 쓴다."""
import http.server
import os
import threading
import unittest
from unittest import mock

from labelbot import llm

ENV = llm.ALLOWED_HOSTS_ENV


def _serve(handler):
    srv = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class _Echo(http.server.BaseHTTPRequestHandler):
    seen = []

    def _reply(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        _Echo.seen.append((self.command, body))
        self.send_response(200)
        self.send_header("X-Echo-Method", self.command)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true, "n": %d}' % len(body))

    do_GET = do_POST = do_PUT = _reply

    def log_message(self, *a):  # code_engrbot: allow C4_PLACEHOLDER 테스트 서버 접속 로그를 끄려고 비운 오버라이드
        pass


class HostAllowedTest(unittest.TestCase):
    def test_env_unset_or_empty_is_off(self):
        for spec in ("", "   "):
            self.assertTrue(llm._host_allowed("api.anywhere.example", spec))
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(ENV, None)
            self.assertTrue(llm._host_allowed("api.anywhere.example"))

    def test_loopback_always_allowed(self):
        for h in ("127.0.0.1", "localhost", "::1", "LOCALHOST"):
            self.assertTrue(llm._host_allowed(h, ".corp.example"))

    def test_suffix_edges(self):
        spec = ".corp.example,api.internal"
        self.assertTrue(llm._host_allowed("a.corp.example", spec))
        self.assertTrue(llm._host_allowed("A.B.corp.example", spec))
        self.assertTrue(llm._host_allowed("corp.example", spec))
        self.assertTrue(llm._host_allowed("api.internal", spec))
        self.assertTrue(llm._host_allowed("x.api.internal", spec))
        self.assertTrue(llm._host_allowed("a.corp.example.", spec))
        self.assertFalse(llm._host_allowed("evilcorp.example", spec))
        self.assertFalse(llm._host_allowed("corp.example.evil.com", spec))
        self.assertFalse(llm._host_allowed("example", spec))
        self.assertFalse(llm._host_allowed("", spec))
        self.assertFalse(llm._host_allowed(None, spec))

    def test_undotted_suffix_rule_same_as_dotted(self):
        self.assertTrue(llm._host_allowed("a.corp.example", "corp.example"))
        self.assertFalse(llm._host_allowed("evilcorp.example", "corp.example"))

    def test_blank_entries_fail_closed(self):
        self.assertFalse(llm._host_allowed("api.anywhere.example", ","))


class GuardOpenTest(unittest.TestCase):
    def setUp(self):
        _Echo.seen.clear()
        self.srv = _serve(_Echo)
        self.base = "http://127.0.0.1:%d" % self.srv.server_port

    def tearDown(self):
        self.srv.shutdown()

    def test_env_unset_loopback_works(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(ENV, None)
            status, body = llm.post_json(self.base + "/v1", {}, {"a": 1}, 5)
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])

    def test_env_set_loopback_still_works(self):
        with mock.patch.dict(os.environ, {ENV: ".corp.example"}):
            status, _ = llm.get_json(self.base + "/v1", {}, 5)
        self.assertEqual(status, 200)

    def test_env_set_blocks_before_socket(self):
        with mock.patch.dict(os.environ, {ENV: ".corp.example"}):
            with mock.patch.object(llm, "build_opener", side_effect=AssertionError("opener reached")):
                for call in (
                    lambda: llm.post_json("https://api.other.example/v1", {}, {}, 1),
                    lambda: llm.post_bytes("https://api.other.example/v1", {}, b"x", "text/plain", 1),
                    lambda: llm.patch_json("https://api.other.example/v1", {}, {}, 1),
                    lambda: llm.get_json("https://evilcorp.example/v1", {}, 1),
                    lambda: llm.request("PUT", "https://api.other.example/o", data=b"x", timeout=1),
                ):
                    with self.assertRaises(llm.CallFailed) as cm:
                        call()
                    self.assertEqual(cm.exception.reason_code, "EXTERNAL_BLOCKED")
                    self.assertNotIn("other.example", str(cm.exception))

    def test_env_set_matching_host_reaches_opener(self):
        with mock.patch.dict(os.environ, {ENV: ".corp.example"}):
            with mock.patch.object(llm, "build_opener", side_effect=AssertionError("opener reached")):
                with self.assertRaises(AssertionError):
                    llm.get_json("https://a.corp.example/v1", {}, 1)


class RequestTest(unittest.TestCase):
    def setUp(self):
        _Echo.seen.clear()
        self.srv = _serve(_Echo)
        self.base = "http://127.0.0.1:%d" % self.srv.server_port

    def tearDown(self):
        self.srv.shutdown()

    def test_put_round_trip_returns_headers_and_bytes(self):
        status, headers, body = llm.request("put", self.base + "/obj", {"Content-Type": "application/octet-stream"}, b"\x00\x01\x02", 5)
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("X-Echo-Method"), "PUT")
        self.assertEqual(body, b'{"ok": true, "n": 3}')
        self.assertEqual(_Echo.seen, [("PUT", b"\x00\x01\x02")])

    def test_get_and_post(self):
        status, headers, _ = llm.request("GET", self.base + "/x")
        self.assertEqual((status, headers.get("X-Echo-Method")), (200, "GET"))
        status, headers, _ = llm.request("POST", self.base + "/x", data=b"ab")
        self.assertEqual((status, headers.get("X-Echo-Method")), (200, "POST"))

    def test_request_goes_through_guard(self):
        with mock.patch.dict(os.environ, {ENV: ".corp.example"}):
            status, _, _ = llm.request("GET", self.base + "/x")
            self.assertEqual(status, 200)
            with self.assertRaises(llm.CallFailed) as cm:
                llm.request("GET", "https://api.other.example/x")
            self.assertEqual(cm.exception.reason_code, "EXTERNAL_BLOCKED")


if __name__ == "__main__":
    unittest.main()
