"""전 단계 통합 테스트(mock LLM). 더미 폴더 전체를 입력으로 쓰고, 원본은 read_input으로만 읽힌다."""
import hashlib
import http.server
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import unittest

from labelbot import finals, llm, pipeline, review, store, util
from labelbot.ingest import read_input
from labelbot.mock import MockChatTransport, MockEmbedTransport
from labelbot.workspace import CODE_ROOT, Workspace, WorkspaceError

DUMMY_DIR = os.path.join(CODE_ROOT, "dummy pptx files")
TAXONOMY = os.path.join(CODE_ROOT, "taxonomy", "taxonomy.json")


def _bucket(text):
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16) % 7


def responder(body, hint):
    """chunk마다 결정적으로 정상/저확신/unknown/인용 불일치/분류 실패/라벨 실패를 만든다."""
    b = _bucket(hint["text"])
    if hint["task"] == "classify":
        obj = MockChatTransport._classify(hint)
        if b == 1:
            for a in obj["axes"].values():
                a["confidence"] = 0.5
        elif b == 2:
            obj["axes"] = {k: {"values": ["unknown"], "evidence": "", "confidence": 0.9} for k in obj["axes"]}
        elif b == 3:
            first = next(iter(obj["axes"]))
            obj["axes"][first]["evidence"] = "본문에 존재하지 않는 인용 문장 XYZ123"
        elif b == 4:
            obj["axes"].pop(next(iter(obj["axes"])))
        return json.dumps(obj, ensure_ascii=False)
    if hint.get("task") == "question_gen":
        return MockChatTransport().send(body, hint)
    obj = MockChatTransport._label(hint)
    if b == 5:
        obj["answers"] = {}
    return json.dumps(obj, ensure_ascii=False)


class _Ws:
    def __init__(self, extra=None):
        self.dir = tempfile.mkdtemp(prefix="labelbot_ws_")
        cfg = {"taxonomy_path": TAXONOMY, "input_root": DUMMY_DIR,
               "llm": {"transport": "mock", "model": "mock", "max_retries": 1},
               "embedding": {"transport": "mock"}, "supabase": {"enabled": False}}
        cfg.update(extra or {})
        with open(os.path.join(self.dir, "pipeline.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        self.ws = Workspace(self.dir)


class PipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w = _Ws()
        cls.ws = cls.w.ws
        cls.before = set()
        for root, _, files in os.walk(cls.ws.root):
            cls.before |= {os.path.join(root, f) for f in files}
        cls.tax_sha = util.sha256_bytes(read_input(TAXONOMY, None))
        cls.transport = MockChatTransport(responder)
        cls.run_id, cls.ctx = pipeline.run_all(cls.ws, DUMMY_DIR, transport=cls.transport, use_feedback=False)
        cls.first_calls = cls.ctx.chat.calls
        cls.con = store.connect(cls.ws.work_db)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()
        shutil.rmtree(cls.w.dir, ignore_errors=True)

    def test_flag_reason_codes(self):
        rows = self.con.execute("SELECT reason_codes FROM flagged_chunks WHERE run_id=?", (self.run_id,)).fetchall()
        seen = {c for r in rows for c in json.loads(r[0])}
        expect = {"UNKNOWN_HIGH", "LOW_CONFIDENCE", "QUOTE_NOT_FOUND", "CLASSIFY_FAILED", "LABEL_FAILED"}
        if self.con.execute("SELECT COUNT(*) FROM chunks WHERE warnings <> '[]'").fetchone()[0]:
            expect.add("PARSE_WARNING")
        self.assertTrue(expect <= seen, expect - seen)

    def test_flag_reports_have_no_text_or_names(self):
        for ext in ("jsonl", "md"):
            with open(self.ws.path("reports", "flagged_%s.%s" % (self.run_id, ext)), encoding="utf-8") as f:
                body = f.read()
            self.assertNotIn(".pptx", body)
            self.assertNotIn("dummy pptx files", body)
        n = self.con.execute("SELECT COUNT(*) FROM flagged_chunks WHERE run_id=?", (self.run_id,)).fetchone()[0]
        with open(self.ws.path("reports", "flagged_%s.jsonl" % self.run_id), encoding="utf-8") as f:
            self.assertEqual(n, sum(1 for _ in f))

    def test_failed_chunks_have_no_label_rows(self):
        failed = [r[0] for r in self.con.execute(
            "SELECT target_id FROM failures WHERE run_id=? AND stage='classify' AND reason_code='AXIS_MISSING'", (self.run_id,))]
        self.assertTrue(failed)
        n = self.con.execute("SELECT COUNT(*) FROM labels WHERE run_id=? AND chunk_id=?", (self.run_id, failed[0])).fetchone()[0]
        self.assertEqual(n, 0)

    def test_rerun_only_retries_failures(self):
        t = MockChatTransport(responder)
        run2, ctx2 = pipeline.run_all(self.ws, DUMMY_DIR, transport=t, use_feedback=False)
        fails = self.con.execute(
            "SELECT COUNT(DISTINCT target_id) FROM failures WHERE run_id=? AND stage IN ('classify','label')", (self.run_id,)).fetchone()[0]
        self.assertGreater(ctx2.chat.calls, 0)
        self.assertLessEqual(ctx2.chat.calls, fails * 3)
        self.assertLess(ctx2.chat.calls, self.first_calls)

    def test_apply_review(self):
        cid = self.con.execute("SELECT chunk_id FROM flagged_chunks f WHERE run_id=? AND EXISTS("
                               "SELECT 1 FROM labels l WHERE l.run_id=f.run_id AND l.chunk_id=f.chunk_id AND l.kind='answer')",
                               (self.run_id,)).fetchone()[0]
        tax, _ = pipeline.load_taxonomy(self.ws)
        doc = {"kind": "review", "run_id": self.run_id,
               "corrections": [{"chunk_id": cid, "target": "answer", "key": "Q-COM-001", "value": "O", "status": "corrected"}],
               "chunk_status": [], "synonyms": [{"chunk_id": cid, "alias": "메탈쇼트", "canonical": "Short"}]}
        bad = dict(doc, run_id="19990101T000000-0000")
        with open(self.ws.path("inbox", "review_ok.json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)
        with open(self.ws.path("inbox", "review_bad.json"), "w", encoding="utf-8") as f:
            json.dump(bad, f, ensure_ascii=False)
        only_compare = review.apply_inbox(self.ws, self.con, tax, kind="compare")
        self.assertFalse([r for r in only_compare if r[3] == "review"])
        res1 = review.apply_inbox(self.ws, self.con, tax)
        snap1 = self.con.execute("SELECT chunk_id, target_key, human_value, bot_value FROM corrections").fetchall()
        res2 = review.apply_inbox(self.ws, self.con, tax)
        snap2 = self.con.execute("SELECT chunk_id, target_key, human_value, bot_value FROM corrections").fetchall()
        self.assertIn("NO_FLAGGED_FOR_RUN", [r[1] for r in res1])
        self.assertEqual([tuple(r) for r in snap1], [tuple(r) for r in snap2])
        final = finals.final_labels(self.con, self.run_id, [cid])[cid]
        self.assertEqual(final["answers"]["Q-COM-001"]["answer"], "O")
        self.assertEqual(final["answers"]["Q-COM-001"]["review"], finals.CORRECTED)
        self.assertEqual(json.loads(snap1[0]["bot_value"]), "N/A")
        n = self.con.execute("SELECT COUNT(*) FROM candidates WHERE source='review'").fetchone()[0]
        self.assertEqual(n, 1)
        self.assertEqual(util.sha256_bytes(read_input(TAXONOMY, None)), self.tax_sha)

    def test_export_integrity(self):
        out = sqlite3.connect(self.ws.path("out", "labeling.sqlite"))
        try:
            for t, col in (("facet_labels", "chunk_id"), ("answers", "chunk_id")):
                n = out.execute("SELECT COUNT(*) FROM %s WHERE %s NOT IN (SELECT chunk_id FROM chunks)" % (t, col)).fetchone()[0]
                self.assertEqual(n, 0, t)
            n = out.execute("SELECT COUNT(*) FROM facet_labels fl WHERE state='value' AND NOT EXISTS("
                            "SELECT 1 FROM facet_values v WHERE v.axis=fl.axis AND v.value=fl.value)").fetchone()[0]
            self.assertEqual(n, 0)
            n = out.execute("SELECT COUNT(*) FROM (SELECT axis, value FROM facet_values GROUP BY axis, value HAVING COUNT(*)>1)").fetchone()[0]
            self.assertEqual(n, 0)
            self.assertEqual(out.execute("SELECT COUNT(*) FROM files WHERE file_name='' OR rel_path=''").fetchone()[0], 0)
            tables = {r[0] for r in out.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            out.close()
        with open(self.ws.path("out", "SCHEMA.md"), encoding="utf-8") as f:
            schema = f.read()
        for t in tables:
            self.assertIn("## %s" % t, schema)
        for root, _, files in os.walk(self.ws.path("out")):
            for fn in files:
                with open(os.path.join(root, fn), "rb") as f:
                    self.assertNotIn(DUMMY_DIR.encode("utf-8"), f.read())

    def test_dashboard(self):
        from labelbot import dashboard

        tax, _ = pipeline.load_taxonomy(self.ws)
        path, n = dashboard.build_results(self.ws, self.con, self.run_id, tax)
        with open(path, encoding="utf-8") as f:
            html = f.read()
        self.assertGreater(n, 0)
        self.assertNotIn("/*__DATA__*/null", html)
        with open(os.path.join(CODE_ROOT, "labelbot", "screens", "results.html"), encoding="utf-8") as f:
            self.assertNotIn("http", f.read().lower())
        low = html.lower()
        for ref in ('src="http', "src='http", 'href="http', "url(http", "@import"):
            self.assertNotIn(ref, low)
        self.assertNotIn("</script>", html.split("const DATA =", 1)[1].split("\n", 1)[0])

    def test_new_files_have_allowed_extensions(self):
        new = []
        for root, _, files in os.walk(self.ws.root):
            new += [os.path.join(root, f) for f in files if os.path.join(root, f) not in self.before]
        bad = [p for p in new if not p.lower().endswith(util.ALLOWED_EXT)]
        self.assertEqual(bad, [])
        self.assertFalse([p for p in new if p.endswith(("-journal", "-wal"))])

    def test_logs_have_no_names(self):
        with open(self.ws.path("logs", "labelbot.log"), encoding="utf-8") as f:
            body = f.read()
        self.assertNotIn(".pptx", body)
        self.assertNotIn("dummy pptx files", body)

    def test_embed_and_push_idempotent(self):
        from labelbot import embed, vectorpush

        et = MockEmbedTransport()
        r1 = embed.embed(self.ws, self.con, self.run_id, transport=et)
        r2 = embed.embed(self.ws, self.con, self.run_id, transport=et)
        self.assertGreater(r1["stored"], 0)
        self.assertEqual(r2["called"], 0)

        class Sink:
            def __init__(self):
                self.rows = []

            def send(self, rows):
                self.rows += rows

        self.ws.config["supabase"].update({"enabled": True, "url": "https://example-proj.supabase.co"})
        try:
            s1 = Sink()
            vectorpush.push(self.ws, self.con, self.run_id, sink=s1)
            s2 = Sink()
            vectorpush.push(self.ws, self.con, self.run_id, sink=s2)
        finally:
            self.ws.config["supabase"].update({"enabled": False, "url": ""})
        self.assertGreater(len(s1.rows), 0)
        self.assertEqual(len(s2.rows), 0)
        names = {r[0]: r[1] for r in self.con.execute("SELECT file_id, file_name FROM files")}
        self.assertTrue(all(r["file_name"] == names[r["file_id"]] and "rel_path" not in r for r in s1.rows))


class SafetyTest(unittest.TestCase):

    def test_body_params(self):
        con = sqlite3.connect(":memory:")
        store.migrate(con)
        base = {"base_url": "https://x.example.com", "chat_path": "/c", "model": "m", "temperature": None,
                "max_tokens": 100, "max_tokens_param": "max_completion_tokens", "response_format_json": False}
        b = llm.ChatClient(base, con, transport=MockChatTransport()).build_body([])
        self.assertNotIn("temperature", b)
        self.assertNotIn("response_format", b)
        self.assertEqual(b["max_completion_tokens"], 100)
        b2 = llm.ChatClient(dict(base, temperature=0), con, transport=MockChatTransport()).build_body([])
        self.assertEqual(b2["temperature"], 0)
        c = llm.ChatClient(base, con, transport=MockChatTransport())
        self.assertNotEqual(c.cache_key(b), c.cache_key(b2))

    def test_redirect_refused(self):
        hits = {"b": 0}

        class B(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                hits["b"] += 1
                self.send_response(200)
                self.end_headers()

            def log_message(self, *a):  # code_engrbot: allow C4_PLACEHOLDER 테스트 서버 접속 로그를 끄려고 비운 오버라이드
                pass

        sb = http.server.HTTPServer(("localhost", 0), B)

        class A(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(302)
                self.send_header("Location", "http://localhost:%d/x" % sb.server_port)
                self.end_headers()

            def log_message(self, *a):  # code_engrbot: allow C4_PLACEHOLDER 테스트 서버 접속 로그를 끄려고 비운 오버라이드
                pass

        sa = http.server.HTTPServer(("localhost", 0), A)
        for s in (sa, sb):
            threading.Thread(target=s.serve_forever, daemon=True).start()
        try:
            with self.assertRaises(llm.CallFailed) as cm:
                llm.post_json("http://localhost:%d/v1" % sa.server_port, {}, {"a": 1}, 5)
            self.assertEqual(cm.exception.reason_code, "HTTP_REDIRECT_REFUSED")
            self.assertEqual(hits["b"], 0)
        finally:
            sa.shutdown()
            sb.shutdown()

    def test_connection_drop_is_call_failed(self):
        class Drop(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.connection.close()

            def log_message(self, *a):  # code_engrbot: allow C4_PLACEHOLDER 테스트 서버 접속 로그를 끄려고 비운 오버라이드
                pass

        s = http.server.HTTPServer(("localhost", 0), Drop)
        threading.Thread(target=s.serve_forever, daemon=True).start()
        try:
            with self.assertRaises(llm.CallFailed) as cm:
                llm.post_json("http://localhost:%d/v1" % s.server_port, {}, {"a": 1}, 5)
            self.assertEqual(cm.exception.reason_code, "NETWORK_ERROR")
        finally:
            s.shutdown()

    def test_mock_cache_key_differs_from_http(self):
        con = sqlite3.connect(":memory:")
        store.migrate(con)
        base = {"base_url": "https://x.example.com", "chat_path": "/c", "model": "m", "temperature": None}
        body = {"model": "m", "messages": []}
        k_http = llm.ChatClient(dict(base, transport="http"), con).cache_key(body)
        k_mock = llm.ChatClient(dict(base, transport="mock"), con).cache_key(body)
        k_custom = llm.ChatClient(dict(base, transport="http"), con, transport=MockChatTransport()).cache_key(body)
        self.assertEqual(len({k_http, k_mock, k_custom}), 3)

    def test_workspace_inside_code_rejected(self):
        with self.assertRaises(WorkspaceError):
            Workspace(os.path.join(CODE_ROOT, "ws_inside"), create=False)

    def test_quote_rules(self):
        self.assertTrue(review.quote_found("Ta−N 0.5µm", ["Ta-N 0.5μm 두께"]))
        self.assertTrue(review.quote_found("A 조건 … B 결과", ["A 조건에서 측정한 뒤 B 결과를 얻었다"]))
        self.assertFalse(review.quote_found("B 결과 … A 조건", ["A 조건에서 측정한 뒤 B 결과를 얻었다"]))
        self.assertTrue(review.is_short_quote("Cu"))
        self.assertFalse(review.is_short_quote("하드마스크 침식"))

    def test_flag_thresholds(self):
        cfg = {"unknown_ratio_min": 0.5, "confidence_min": 0.7}
        chunk = {"warnings": "[]", "text": "본문"}

        def bot(unk, n, conf):
            axes = {"a%d" % i: {"values": ["unknown" if i < unk else "x"], "status": "unknown" if i < unk else "value",
                                "evidence": "", "confidence": conf} for i in range(n)}
            return {"chunk_type": "내용", "axes": axes, "answers": {}, "extracted": []}

        self.assertNotIn("UNKNOWN_HIGH", review.judge_chunk(chunk, bot(49, 100, 0.9), False, False, cfg, {})[0])
        self.assertIn("UNKNOWN_HIGH", review.judge_chunk(chunk, bot(50, 100, 0.9), False, False, cfg, {})[0])
        self.assertIn("LOW_CONFIDENCE", review.judge_chunk(chunk, bot(0, 2, 0.69), False, False, cfg, {})[0])
        self.assertNotIn("LOW_CONFIDENCE", review.judge_chunk(chunk, bot(0, 2, 0.7), False, False, cfg, {})[0])


if __name__ == "__main__":
    unittest.main()
