"""화면 서버(labelbot serve): screens/ 제공과 inbox/ 저장 (표준 라이브러리만 사용)."""
import http.client
import json
import os
import shutil
import tempfile
import threading
import unittest

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
        rv = {"chunk_id": "c1", "target": "axis", "key": "예시축", "reason": "OTHER", "proposed": None,
              "related_values": [], "memo": "가" * 500}
        doc = {"kind": "review", "run_id": RUN, "corrections": [], "chunk_status": [], "synonyms": [], "revisits": [rv]}
        code, body = self.req("POST", "/inbox/review", json.dumps(doc, ensure_ascii=False).encode("utf-8"))
        self.assertEqual(code, 200, body)
        self.assertTrue(os.path.isfile(self.inbox_file("review")))

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
