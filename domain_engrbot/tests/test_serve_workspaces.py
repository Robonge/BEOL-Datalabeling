"""검토 화면 서버(serve: 결정 JSON을 qa/inbox/에 바로 쓴다)와 작업 폴더 목록(workspaces)."""
import http.client
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import unittest

from domain_engrbot import io, screen, serve, workspaces
from domain_engrbot.tests import reviewfix as rf


class ServeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res, _fx, _roles = rf.scenario()
        screen.build(cls.res)
        cls.qa = cls.res.qa_run_id
        cls.srv = serve.make_server(cls.res.paths, cls.qa, 0)
        cls.port = cls.srv.server_address[1]
        cls.th = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.th.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        for fn in os.listdir(self.res.paths.inbox):
            os.remove(os.path.join(self.res.paths.inbox, fn))

    def req(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": "127.0.0.1:%d" % self.port}
        h.update(headers or {})
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, data

    def post(self, doc, origin=True, raw=None):
        h = {"Content-Type": "application/json"}
        if origin:
            h["Origin"] = "http://127.0.0.1:%d" % self.port
        body = raw if raw is not None else json.dumps(doc, ensure_ascii=False, indent=2).encode("utf-8")
        st, data = self.req("POST", "/inbox/qa_decisions", body, h)
        return st, json.loads(data.decode("utf-8"))

    def test_get_serves_review_screen_only(self):
        st, data = self.req("GET", "/")
        self.assertEqual(st, 200)
        with open(self.res.path("review.html"), "rb") as f:
            self.assertEqual(data, f.read())
        self.assertEqual(self.req("GET", "/verdicts.jsonl")[0], 404)
        self.assertEqual(self.req("GET", "/../manifest.json")[0], 404)
        self.assertEqual(self.req("GET", "/", headers={"Host": "evil.example:%d" % self.port})[0], 403)

    def test_post_writes_inbox_unchanged(self):
        doc = rf.decisions_doc(self.qa, [{"record_id": "r1", "field": "axis:x", "decision": "confirm",
                                          "value": ["a"], "quote": "q"}])
        body = json.dumps(doc, ensure_ascii=False, indent=2).encode("utf-8")
        st, out = self.post(None, raw=body)
        self.assertEqual(st, 200)
        self.assertEqual(out["saved"], "qa/inbox/qa_decisions_%s.json" % self.qa)
        self.assertEqual(out["counts"]["confirm"], 1)
        path = os.path.join(self.res.paths.inbox, "qa_decisions_%s.json" % self.qa)
        with open(path, "rb") as f:
            self.assertEqual(f.read(), body)
        self.assertEqual(os.listdir(self.res.paths.inbox), [os.path.basename(path)])  # 임시 파일이 남지 않는다
        # 다시 저장하면 같은 이름을 덮어쓴다(가장 최근 결정)
        doc["decisions"] = []
        self.assertEqual(self.post(doc)[0], 200)
        with open(path, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["decisions"], [])

    def test_post_rejects_bad_requests(self):
        good = rf.decisions_doc(self.qa)
        self.assertEqual(self.post(good, origin=False), (403, {"ok": False, "code": "ORIGIN_REJECTED"}))
        self.assertEqual(self.post(None, raw=b"{bad")[1]["code"], "DECISIONS_JSON_INVALID")
        self.assertEqual(self.post({"kind": "review", "decisions": []})[1]["code"], "DECISIONS_FORMAT_INVALID")
        self.assertEqual(self.post(rf.decisions_doc("QA-20000101T000000-0000"))[1]["code"], "DECISIONS_OTHER_RUN")
        st, data = self.req("POST", "/inbox/qa_decisions", b"{}", {"Content-Type": "text/plain",
                                                                  "Origin": "http://127.0.0.1:%d" % self.port})
        self.assertEqual(st, 415)
        self.assertEqual(os.listdir(self.res.paths.inbox), [])

    def test_default_port_is_stable(self):
        p = serve.default_port(self.qa)
        self.assertEqual(p, serve.default_port(self.qa))
        self.assertTrue(serve.PORT_BASE <= p < serve.PORT_BASE + serve.PORT_SPAN)


class WorkspacesTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="domain_engrbot_wslist_")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def make_ws(self, name, labeler_run, qa_runs=(), decided=(), fed=()):
        ws = os.path.join(self.root, name)
        os.makedirs(ws)
        con = sqlite3.connect(os.path.join(ws, "work.sqlite"))
        con.execute("CREATE TABLE runs(run_id TEXT, command TEXT)")
        con.execute("INSERT INTO runs VALUES(?, 'run')", (labeler_run,))
        con.commit()
        con.close()
        for qa, lrun in qa_runs:
            d = os.path.join(ws, "qa", "runs", qa)
            os.makedirs(d)
            io.write_json(os.path.join(d, "manifest.json"), {"labeler_run_id": lrun, "counts": {"records": 3, "REVIEW": 2}})
            if qa in fed:
                io.write_json(os.path.join(d, "feedback", "feedback.json"), {})
        for qa in decided:
            io.write_json(os.path.join(ws, "qa", "inbox", "qa_decisions_%s.json" % qa), {})
        return ws

    def test_states(self):
        self.make_ws("ws_new", "20261005T010000-aaaa", [("QA-20261005T020000-0001", "20261004T000000-old0")])
        self.make_ws("ws_qa", "20261005T010000-bbbb", [("QA-20261005T020000-0002", "20261005T010000-bbbb")])
        self.make_ws("ws_done", "20261005T010000-cccc", [("QA-20261005T020000-0003", "20261005T010000-cccc")],
                     decided=["QA-20261005T020000-0003"], fed=["QA-20261005T020000-0003"])
        os.makedirs(os.path.join(self.root, "_domain_engrbot"))
        open(os.path.join(self.root, "_domain_engrbot", "work.sqlite"), "w").close()
        rows = {r["workspace"]: r for r in workspaces.scan(self.root)}
        self.assertEqual(sorted(rows), ["ws_done", "ws_new", "ws_qa"])
        self.assertEqual(rows["ws_new"]["state"], "new")
        self.assertEqual(rows["ws_new"]["qa_runs_total"], 1)
        self.assertEqual(rows["ws_qa"]["state"], "qa_done")
        self.assertEqual(rows["ws_qa"]["latest_qa"]["counts"]["REVIEW"], 2)
        self.assertEqual(rows["ws_done"]["state"], "applied")
        self.assertTrue(rows["ws_done"]["latest_qa"]["feedback"])

    def test_timestamped_decision_file_counts(self):
        self.make_ws("ws", "20261005T010000-dddd", [("QA-20261005T020000-0004", "20261005T010000-dddd")])
        io.write_json(os.path.join(self.root, "ws", "qa", "inbox",
                                   "qa_decisions_QA-20261005T020000-0004_20261005-120000.json"), {})
        self.assertEqual(workspaces.scan(self.root)[0]["state"], "applied")

    def test_question_state_columns(self):
        """질문 루프 상태(8.8절): 교정 없음 no_review, 장부에 없거나 질문 묶음 inputs와 sha가 다르면 new, 같으면 asked."""
        from domain_engrbot import qmodel

        self.make_ws("ws_plain", "20261005T010000-eeee")
        ws = self.make_ws("ws_rev", "20261005T010000-ffff")
        con = sqlite3.connect(os.path.join(ws, "work.sqlite"))
        con.execute("CREATE TABLE corrections(chunk_id TEXT, review_run_id TEXT)")
        con.execute("INSERT INTO corrections VALUES('c1', '20261005T010000-ffff')")
        con.commit()
        con.close()
        rows = {r["workspace"]: r for r in workspaces.scan(self.root)}
        self.assertEqual((rows["ws_plain"]["question_state"], rows["ws_plain"]["review_runs"]), ("no_review", 0))
        self.assertEqual((rows["ws_rev"]["question_state"], rows["ws_rev"]["review_runs"]), ("new", 1))
        self.assertEqual(rows["ws_plain"]["state"], "new")
        io.write_jsonl(os.path.join(ws, "qa", "ledger", "sources.jsonl"), [{"source_ws": "ws_rev", "corrections_sha": "s1"}])
        doc = qmodel.empty_set("ws_rev")
        io.write_json(os.path.join(ws, "qa", "questions", "questions.json"), dict(doc, inputs={"ws_rev": "s0"}))
        self.assertEqual({r["workspace"]: r for r in workspaces.scan(self.root)}["ws_rev"]["question_state"], "new")
        io.write_json(os.path.join(ws, "qa", "questions", "questions.json"), dict(doc, inputs={"ws_rev": "s1"}))
        self.assertEqual({r["workspace"]: r for r in workspaces.scan(self.root)}["ws_rev"]["question_state"], "asked")
        self.assertEqual(workspaces.questions_summary(self.root), {"set_id": None, "open": 0, "answered_total": 0})


def tearDownModule():
    rf.cleanup()


if __name__ == "__main__":
    unittest.main()
