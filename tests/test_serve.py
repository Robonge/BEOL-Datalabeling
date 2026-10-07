"""화면 서버(labelbot serve): screens/ 제공과 inbox/ 저장 (표준 라이브러리만 사용)."""
import http.client
import json
import os
import shutil
import tempfile
import threading
import unittest
import uuid

from labelbot import serve

RUN = "20261004T123310-72d8"


class ServeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp()
        os.makedirs(os.path.join(cls.root, "screens"))
        with open(os.path.join(cls.root, "screens", "review.html"), "w", encoding="utf-8") as f:
            f.write("<p>ok</p>")
        cls.srv = serve.make_server(cls.root, 0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        shutil.rmtree(cls.root, ignore_errors=True)

    def req(self, method, path, body=None, origin="self", host=None, ctype="application/json"):
        host = host or "127.0.0.1:%d" % self.port
        headers = {"Host": host}
        if origin == "self":
            headers["Origin"] = "http://" + host
        elif origin:
            headers["Origin"] = origin
        data = None
        if body is not None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
            headers["Content-Type"] = ctype
        con = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        con.request(method, path, body=data, headers=headers)
        r = con.getresponse()
        out = r.status, r.read()
        con.close()
        return out

    def inbox_file(self, kind):
        return os.path.join(self.root, "inbox", "%s_%s.json" % (kind, RUN))

    def test_serves_screens_and_status(self):
        self.assertEqual(self.req("GET", "/review.html"), (200, b"<p>ok</p>"))
        code, body = self.req("GET", "/inbox/status")
        self.assertEqual(code, 200)
        self.assertTrue(json.loads(body)["ok"])

    def test_post_writes_inbox_and_overwrites(self):
        for n in (1, 2):
            doc = {"kind": "review", "run_id": RUN, "corrections": [], "chunk_status": [{"chunk_id": "c%d" % n}]}
            code, body = self.req("POST", "/inbox/review", doc)
            self.assertEqual(code, 200, body)
        with open(self.inbox_file("review"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["chunk_status"], [{"chunk_id": "c2"}])
        names = [n for n in os.listdir(os.path.join(self.root, "inbox")) if n.startswith("review_")]
        self.assertEqual(names, ["review_%s.json" % RUN])

    def test_compare_kind(self):
        code, _ = self.req("POST", "/inbox/compare", {"kind": "compare", "run_id": RUN, "marks": []})
        self.assertEqual(code, 200)
        self.assertTrue(os.path.isfile(self.inbox_file("compare")))

    def test_post_review_with_revisits(self):
        # 다른 테스트와 파일이 겹치지 않도록 고유 실행 ID를 쓴다.
        rid = "rv-" + uuid.uuid4().hex[:12]
        path = os.path.join(self.root, "inbox", "review_%s.json" % rid)
        self.assertFalse(os.path.isfile(path))
        # test_post_writes_inbox_and_overwrites가 review_* 파일 목록을 보므로 끝나면 지운다.
        self.addCleanup(lambda: os.path.isfile(path) and os.remove(path))
        rv = {"chunk_id": "c1", "target": "axis", "key": "예시축", "reason": "OTHER", "proposed": None,
              "related_values": [], "memo": "가" * 500}
        doc = {"kind": "review", "run_id": rid, "corrections": [], "chunk_status": [], "synonyms": [],
               "revisits": [rv, dict(rv, chunk_id="c2")]}
        code, body = self.req("POST", "/inbox/review", json.dumps(doc, ensure_ascii=False).encode("utf-8"))
        self.assertEqual(code, 200, body)
        self.assertEqual(json.loads(body)["saved"], "inbox/review_%s.json" % rid)
        with open(path, encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved["run_id"], rid)
        self.assertEqual(len(saved["revisits"]), 2)
        self.assertEqual(saved["revisits"][0]["memo"], "가" * 500)

    def test_status_announces_done(self):
        _, body = self.req("GET", "/inbox/status")
        self.assertTrue(json.loads(body)["done"])

    def test_done_writes_review_then_signal(self):
        rid = "dn-" + uuid.uuid4().hex[:12]
        path = os.path.join(self.root, "inbox", "review_%s.json" % rid)
        sig = os.path.join(self.root, "signals", "review_done_%s.json" % rid)
        self.addCleanup(lambda: os.path.isfile(path) and os.remove(path))
        self.addCleanup(lambda: os.path.isfile(sig) and os.remove(sig))
        doc = {"kind": "review", "run_id": rid, "corrections": [{"chunk_id": "c1"}, {"chunk_id": "c2"}],
               "chunk_status": [{"chunk_id": "c3", "status": "confirmed"}], "synonyms": [],
               "revisits": [{"chunk_id": "c1", "memo": "본문일 수 있는 메모"}]}
        code, body = self.req("POST", "/inbox/review/done", json.dumps(doc, ensure_ascii=False).encode("utf-8"))
        self.assertEqual(code, 200, body)
        out = json.loads(body)
        self.assertEqual((out["saved"], out["signal"]), ("inbox/review_%s.json" % rid, "signals/review_done_%s.json" % rid))
        with open(path, encoding="utf-8") as f:
            self.assertEqual(len(json.load(f)["corrections"]), 2)
        with open(sig, encoding="utf-8") as f:
            raw = f.read()
        s = json.loads(raw)
        self.assertEqual(s["run_id"], rid)
        self.assertEqual(s["counts"], {"edits": 2, "status": 1, "syns": 0, "revisits": 1})
        # 신호에는 건수만 있고 교정 본문·메모는 없다.
        self.assertNotIn("메모", raw)
        self.assertNotIn("c1", raw)
        # 교정 파일이 신호보다 먼저 쓰였다.
        self.assertLessEqual(os.stat(path).st_mtime, os.stat(sig).st_mtime)

    def test_status_reports_done_signal_per_run(self):
        rid = "ds-" + uuid.uuid4().hex[:12]
        path = os.path.join(self.root, "inbox", "review_%s.json" % rid)
        sig = os.path.join(self.root, "signals", "review_done_%s.json" % rid)
        self.addCleanup(lambda: os.path.isfile(path) and os.remove(path))
        self.addCleanup(lambda: os.path.isfile(sig) and os.remove(sig))

        def status(query):
            code, body = self.req("GET", "/inbox/status" + query)
            self.assertEqual(code, 200)
            return json.loads(body)

        self.assertIs(status("?run=" + rid)["done_signal"], False)
        code, _ = self.req("POST", "/inbox/review/done", {"kind": "review", "run_id": rid, "corrections": []})
        self.assertEqual(code, 200)
        self.assertIs(status("?run=" + rid)["done_signal"], True)
        # run이 없거나 형식이 틀리면 키를 넣지 않는다.
        for q in ("", "?run=", "?run=..%2Fx", "?other=" + rid):
            out = status(q)
            self.assertTrue(out["done"], q)
            self.assertNotIn("done_signal", out, q)

    def test_done_rejects(self):
        cases = [
            (dict(path="/inbox/compare/done", body={"kind": "compare", "run_id": RUN}), 404),
            (dict(path="/inbox/review/done", body={"kind": "review", "run_id": RUN}, origin="https://evil.example"), 403),
            (dict(path="/inbox/review/done", body={"kind": "review", "run_id": "../x"}), 400),
            (dict(path="/inbox/review/done", body={"kind": "compare", "run_id": RUN}), 400),
        ]
        for kw, want in cases:
            code, _ = self.req("POST", kw.pop("path"), **kw)
            self.assertEqual(code, want, kw)
        self.assertFalse(os.path.isfile(os.path.join(self.root, "signals", "review_done_%s.json" % RUN)))

    def test_status_announces_start(self):
        _, body = self.req("GET", "/inbox/status")
        self.assertTrue(json.loads(body)["start"])

    def test_start_writes_signal(self):
        rid = "st-" + uuid.uuid4().hex[:12]
        sig = os.path.join(self.root, "signals", "review_start_%s.json" % rid)
        self.addCleanup(lambda: os.path.isfile(sig) and os.remove(sig))
        for compare in (True, False):
            code, body = self.req("POST", "/signals/review_start",
                                  {"kind": "review_start", "run_id": rid, "compare": compare})
            self.assertEqual(code, 200, body)
            self.assertEqual(json.loads(body)["signal"], "signals/review_start_%s.json" % rid)
            with open(sig, encoding="utf-8") as f:
                s = json.load(f)
            self.assertEqual((s["run_id"], s["compare"], sorted(s)), (rid, compare, ["compare", "run_id", "started_at"]))
        # compare가 없으면 검수만이다. inbox에는 아무것도 쓰지 않는다.
        self.assertEqual(self.req("POST", "/signals/review_start", {"kind": "review_start", "run_id": rid})[0], 200)
        with open(sig, encoding="utf-8") as f:
            self.assertFalse(json.load(f)["compare"])
        self.assertFalse([n for n in os.listdir(os.path.join(self.root, "inbox")) if rid in n])

    def test_start_rejects(self):
        good = {"kind": "review_start", "run_id": RUN}
        cases = [
            (dict(body=good, origin="https://evil.example"), 403),
            (dict(body=good, origin=None), 403),
            (dict(body=good, host="evil.example:80"), 403),
            (dict(body=good, ctype="text/plain"), 415),
            (dict(body=b"{not json"), 400),
            (dict(body={"kind": "review", "run_id": RUN}), 400),
            (dict(body={"kind": "review_start", "run_id": "../x"}), 400),
            (dict(body={"kind": "review_start", "run_id": RUN, "compare": "yes"}), 400),
            (dict(body=json.dumps(dict(good, pad="x" * 5000)).encode("utf-8")), 413),
        ]
        for kw, want in cases:
            code, _ = self.req("POST", "/signals/review_start", **kw)
            self.assertEqual(code, want, kw)
        self.assertFalse(os.path.isfile(os.path.join(self.root, "signals", "review_start_%s.json" % RUN)))

    def test_get_rejects_foreign_host(self):
        for host in ("evil.example", "evil.example:%d" % self.port, "127.0.0.1.evil.example:80"):
            for path in ("/review.html", "/inbox/status"):
                code, body = self.req("GET", path, host=host)
                self.assertEqual(code, 403, (host, path))
                self.assertEqual(json.loads(body)["code"], "HOST_REJECTED")
        for host in ("localhost:%d" % self.port, "127.0.0.1:1", "localhost", "LOCALHOST:%d" % self.port):
            self.assertEqual(self.req("GET", "/review.html", host=host), (200, b"<p>ok</p>"))
        # HEAD도 같은 규칙이다(헤더만으로도 파일 존재와 크기가 드러난다).
        self.assertEqual(self.req("HEAD", "/review.html", host="evil.example")[0], 403)
        self.assertEqual(self.req("HEAD", "/review.html", host="localhost:%d" % self.port)[0], 200)
        # Host 헤더가 없으면 POST와 같이 거절한다.
        con = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        con.putrequest("GET", "/review.html", skip_host=True)
        con.endheaders()
        r = con.getresponse()
        self.assertEqual((r.status, json.loads(r.read())["code"]), (403, "HOST_REJECTED"))
        con.close()

    def test_rejects(self):
        good = {"kind": "review", "run_id": RUN}
        cases = [
            (dict(path="/inbox/review", body=good, origin="https://evil.example"), 403),
            (dict(path="/inbox/review", body=good, origin=None), 403),
            (dict(path="/inbox/review", body=good, host="evil.example:80"), 403),
            (dict(path="/inbox/review", body=good, ctype="text/plain"), 415),
            (dict(path="/inbox/review", body=b"{not json"), 400),
            (dict(path="/inbox/compare", body=good), 400),
            (dict(path="/inbox/review", body={"kind": "review", "run_id": "../x"}), 400),
            (dict(path="/inbox/other", body=good), 404),
        ]
        for kw, want in cases:
            code, _ = self.req("POST", kw.pop("path"), **kw)
            self.assertEqual(code, want, kw)
        names = os.listdir(os.path.join(self.root, "inbox"))
        self.assertFalse([n for n in names if not n.startswith(("review_", "compare_"))], names)


if __name__ == "__main__":
    unittest.main()
