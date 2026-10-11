"""labelbot.ragsrv: 임시 로컬 저장소 + 가짜 _chat·_embed로 서버를 스레드에 띄워 API·요청 검사를 본다.

실제 LLM·임베딩을 부르지 않는다. 환경변수 BEOL_RAG_STORE는 임시 폴더로 고정한다(실제 workspaces/_rag_store를 건드리지 않는다).
"""
import base64
import hashlib
import http.client
import io
import json
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from labelbot import llm, localstore, raglib, ragsrv
from labelbot.slideimg import object_path

EMB_MODEL = "text-embedding-3-small"
CHAT_MODEL = "chat-model-under-test"
KEY_ENV = "RAGSRV_TEST_KEY_ENV"
FILE_A = "a" * 64
FILE_B = "b" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\x00\x10JFIF" + bytes(range(64))
DOC_META = {"author": "kim", "date": "2026-10-01", "lots": [{"lot": "L1", "wf": ["01"]}]}
SECRET_Q = "비밀질문문구XYZ"


def labels(*scheme, **axes):
    return {"axes": dict({"Patterning/scheme": list(scheme)}, **axes), "doc_meta": DOC_META, "answers": {}}


def row(cid, file_id, seq, vec, content, lab):
    return {"chunk_id": cid, "model": EMB_MODEL, "file_id": file_id, "file_name": "x", "seq": seq,
            "embedding": list(vec), "content": content, "labels": lab, "run_id": "r1"}


class RagSrvCase(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.root = os.path.join(self.base, "store")
        self.page_dir = os.path.join(self.base, "rag")
        os.makedirs(self.page_dir)
        Path(self.page_dir, "beol_rag.html").write_text("<!doctype html><title>t</title>", encoding="utf-8")
        self.env = mock.patch.dict(os.environ, {"BEOL_RAG_STORE": self.root})
        self.env.start()
        os.environ.pop("RAG_MAX_COMPLETION_TOKENS", None)
        con = localstore.connect(self.root)
        try:
            localstore.upsert_rows(con, [
                row("a1", FILE_A, 1, (1.0, 0.0), "# Via 저항\nTaN barrier 저항 결과", labels("SAQP", 결과=["양호"])),
                row("a2", FILE_A, 2, (0.0, 1.0), "# 같은 파일\n두께 조건", labels("SAQP")),
                row("b1", FILE_B, 1, (0.7, 0.7), "# B 문서\nCu CMP 평가", labels("LELE")),
                row("x1", FILE_B, 2, (1.0, 0.0), "# 불완전 행", {"axes": {"Patterning/scheme": []}}),
            ])
            for cid, fid, seq in (("a1", FILE_A, 1), ("a2", FILE_A, 2), ("b1", FILE_B, 1)):
                localstore.patch_slide(con, cid, {
                    "slide_image_bucket": "local", "slide_image_path": object_path(fid, seq),
                    "slide_image_sha256": hashlib.sha256(JPG).hexdigest(), "slide_image_width": 1280,
                    "slide_image_height": 720})
        finally:
            con.close()
        localstore.put_slide(self.root, hashlib.sha256(JPG).hexdigest(), JPG)
        localstore.write_rag_config(self.root, {"model": CHAT_MODEL, "api_key_env": KEY_ENV},
                                    {"model": EMB_MODEL, "api_key_env": KEY_ENV})
        self.llm_cfg, self.emb_cfg = ragsrv.load_config(self.root)
        self.srv = ragsrv.make_server(self.root, self.page_dir, self.llm_cfg, self.emb_cfg, 0)
        self.port = self.srv.server_address[1]
        self.host = "127.0.0.1:%d" % self.port
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.thread.start()
        self.chat = mock.patch("labelbot.ragsrv._chat", return_value=("Via 저항은 기준 안이다[1][9].", "stop"))
        self.embed = mock.patch("labelbot.ragsrv._embed", return_value=[[1.0, 0.0]])
        self.chat_mock = self.chat.start()
        self.embed_mock = self.embed.start()

    def tearDown(self):
        self.chat.stop()
        self.embed.stop()
        self.srv.shutdown()
        self.srv.server_close()
        self.env.stop()
        shutil.rmtree(self.base, ignore_errors=True)

    def request(self, method, path, body=None, headers=None, raw=None):
        hdrs = {"Host": self.host}
        if method == "POST":
            hdrs.update({"Origin": "http://" + self.host, "Content-Type": "application/json"})
        hdrs.update(headers or {})
        hdrs = {k: v for k, v in hdrs.items() if v is not None}
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode("utf-8"))
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            c.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            for k, v in hdrs.items():
                c.putheader(k, v)
            if data is not None:
                c.putheader("Content-Length", str(len(data)))
            c.endheaders(data)
            r = c.getresponse()
            return r.status, r.getheader("Content-Type") or "", r.read(), r
        finally:
            c.close()

    def ask(self, body):
        status, ctype, data, _ = self.request("POST", "/api/ask", body)
        return status, json.loads(data.decode("utf-8"))

    def q(self, text="Via 저항", **extra):
        return dict({"messages": [{"role": "user", "content": text}]}, **extra)


class AskTest(RagSrvCase):
    def test_ok_answer_evidence_and_max_tokens(self):
        status, out = self.ask(self.q())
        self.assertEqual(status, 200)
        self.assertEqual(out["answer"], "Via 저항은 기준 안이다[1].")
        self.assertEqual(out["cited"], [1])
        self.assertEqual(out["rewritten_query"], "Via 저항")
        self.assertNotIn("warnings", out)
        ids = [(e["chunk_id"], e["kind"]) for e in out["evidence"]]
        self.assertEqual(ids[0], ("a1", "hit"))
        self.assertIn(("a2", "hit"), ids)
        self.assertNotIn("x1", [e["chunk_id"] for e in out["evidence"]])
        self.assertEqual(out["evidence"][0]["image_url"], "/slides/" + object_path(FILE_A, 1))
        self.assertEqual(self.chat_mock.call_count, 1)
        cfg, msgs, max_tokens, timeout = self.chat_mock.call_args[0]
        self.assertEqual(max_tokens, 6000)
        self.assertEqual(cfg["model"], CHAT_MODEL)
        self.assertLessEqual(timeout, ragsrv.TIMEOUT_ANSWER)
        self.assertEqual(msgs[0]["role"], "system")
        self.assertEqual(self.embed_mock.call_args[0][1], ["Via 저항"])

    def test_siblings_attached_when_k_is_one(self):
        status, out = self.ask(self.q(k=1))
        self.assertEqual(status, 200)
        self.assertEqual([(e["chunk_id"], e["kind"], e["sibling_of"]) for e in out["evidence"]],
                         [("a1", "hit", None), ("a2", "sibling", 1)])

    def test_no_evidence_with_filter(self):
        status, out = self.ask(self.q(filters={"Patterning/scheme": ["없는 값"]}))
        self.assertEqual(status, 200)
        self.assertEqual(out, {"answer": raglib.NO_EVIDENCE_FILTERED_ANSWER, "rewritten_query": "Via 저항",
                               "cited": [], "evidence": []})
        self.chat_mock.assert_not_called()

    def test_filter_and_or(self):
        status, out = self.ask(self.q(filters={"Patterning/scheme": ["LELE", "SAQP"], "결과": ["양호"]}))
        self.assertEqual(status, 200)
        self.assertEqual([e["chunk_id"] for e in out["evidence"] if e["kind"] == "hit"], ["a1"])

    def test_bad_input(self):
        self.assertEqual(self.ask({"messages": []}), (400, {"error": "BAD_INPUT"}))
        self.assertEqual(self.ask(self.q(filters={"축": "문자열"})), (400, {"error": "BAD_INPUT"}))
        status, _, data, _ = self.request("POST", "/api/ask", raw=b"{not json")
        self.assertEqual((status, json.loads(data)), (400, {"error": "BAD_REQUEST_JSON"}))
        status, _, data, _ = self.request("POST", "/api/ask", raw=b"x" * (raglib.MAX_BODY_BYTES + 1))
        self.assertEqual((status, json.loads(data)), (400, {"error": "BAD_REQUEST_JSON"}))

    def test_llm_truncated_empty_and_warning(self):
        self.chat_mock.return_value = ("", "length")
        self.assertEqual(self.ask(self.q()), (502, {"error": "LLM_TRUNCATED"}))
        self.chat_mock.return_value = ("  ", "stop")
        self.assertEqual(self.ask(self.q()), (502, {"error": "LLM_EMPTY"}))
        self.chat_mock.return_value = ("부분 답[1]", "length")
        status, out = self.ask(self.q())
        self.assertEqual(status, 200)
        self.assertEqual(out["warnings"], ["TRUNCATED"])

    def test_llm_and_embed_failures(self):
        self.chat_mock.side_effect = llm.CallFailed("HTTP_500")
        self.assertEqual(self.ask(self.q()), (502, {"error": "LLM_FAILED"}))
        self.embed_mock.side_effect = llm.CallFailed("TIMEOUT")
        self.assertEqual(self.ask(self.q()), (502, {"error": "EMBED_FAILED"}))
        self.embed_mock.side_effect = None
        self.embed_mock.return_value = [[1.0, float("nan")]]
        self.assertEqual(self.ask(self.q()), (502, {"error": "EMBED_FAILED"}))
        self.embed_mock.return_value = [[1.0, 0.0, 0.0]]
        self.assertEqual(self.ask(self.q()), (502, {"error": "EMBED_DIM_MISMATCH"}))

    def test_follow_up_rewrite(self):
        self.chat_mock.side_effect = [("  Cu CMP\n평가  결과 ", "stop"), ("CMP 답[1]", "stop")]
        msgs = [{"role": "user", "content": "첫 질문"}, {"role": "assistant", "content": "앞 답[1][2]"},
                {"role": "user", "content": "그건?"}]
        status, out = self.ask({"messages": msgs})
        self.assertEqual(status, 200)
        self.assertEqual(out["rewritten_query"], "Cu CMP 평가 결과")
        first, second = self.chat_mock.call_args_list
        self.assertEqual(first[0][2], 400)
        self.assertEqual(first[0][1][0], {"role": "system", "content": raglib.REWRITE_SYSTEM_PROMPT})
        self.assertEqual(first[0][1][2], {"role": "assistant", "content": "앞 답"})
        self.assertEqual(second[0][2], 6000)
        self.assertEqual(self.embed_mock.call_args[0][1], ["Cu CMP 평가 결과"])

    def test_rewrite_failure_warns_and_uses_question(self):
        self.chat_mock.side_effect = [llm.CallFailed("TIMEOUT"), ("답[1]", "stop")]
        msgs = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"},
                {"role": "user", "content": "Via 저항"}]
        status, out = self.ask({"messages": msgs})
        self.assertEqual(status, 200)
        self.assertEqual(out["rewritten_query"], "Via 저항")
        self.assertEqual(out["warnings"], ["REWRITE_FAILED"])

    def test_store_change_is_seen(self):
        self.assertEqual(self.ask(self.q())[1]["evidence"][0]["chunk_id"], "a1")
        con = localstore.connect(self.root)
        try:
            localstore.upsert_rows(con, [row("c1", "c" * 64, 1, (1.0, 0.0), "# 새 행\nVia 저항 저항", labels("SAQP"))])
            localstore.patch_slide(con, "c1", {"slide_image_bucket": "local", "slide_image_path": object_path("c" * 64, 1),
                                               "slide_image_sha256": hashlib.sha256(JPG).hexdigest(),
                                               "slide_image_width": 1, "slide_image_height": 1})
        finally:
            con.close()
        status, out = self.ask(self.q())
        self.assertIn("c1", [e["chunk_id"] for e in out["evidence"]])

    def test_log_line_has_no_question_text(self):
        buf = io.StringIO()
        with mock.patch("sys.stderr", buf):
            self.ask(self.q(SECRET_Q))
        log = buf.getvalue()
        self.assertRegex(log, r"\[ragsrv\] /api/ask OK \d+ k=5 n=\d+")
        self.assertNotIn(SECRET_Q, log)
        self.assertNotIn("기준 안", log)


class ReadApiTest(RagSrvCase):
    def test_facets_and_stats(self):
        status, ctype, data, _ = self.request("GET", "/api/facets")
        self.assertEqual(status, 200)
        self.assertTrue(ctype.startswith("application/json"))
        facets = json.loads(data)
        self.assertIn({"axis": "Patterning/scheme", "value": "SAQP", "n": 2}, facets)
        self.assertIn({"axis": "결과", "value": "양호", "n": 1}, facets)
        status, _, data, _ = self.request("GET", "/api/stats")
        self.assertEqual((status, json.loads(data)), (200, {"count": 3}))

    def test_slide_ok_and_not_written_to_disk(self):
        status, ctype, data, _ = self.request("GET", "/slides/" + object_path(FILE_A, 1))
        self.assertEqual((status, ctype, data), (200, "image/jpeg", JPG))
        for _dirpath, _dirs, files in os.walk(self.root):
            self.assertFalse([f for f in files if f.endswith(".jpg")])

    def test_slide_bad_paths_404(self):
        for path in ("/slides/" + object_path(FILE_A, 9), "/slides/zz/0001.jpg", "/slides/../rag_store.sqlite",
                     "/slides/%2e%2e/rag_store.sqlite", "/slides/" + "a" * 16 + "/0001.png",
                     "/slides/" + object_path("x" * 64, 2)):
            self.assertEqual(self.request("GET", path)[0], 404, path)

    def test_slide_corrupt_b64_404(self):
        Path(localstore.slide_path(self.root, hashlib.sha256(JPG).hexdigest())).write_text(
            base64.b64encode(b"not a jpeg").decode("ascii"), encoding="ascii")
        self.assertEqual(self.request("GET", "/slides/" + object_path(FILE_A, 1))[0], 404)

    def test_static_root_and_traversal(self):
        status, ctype, data, _ = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"<title>t</title>", data)
        for path in ("/../store/rag_store.sqlite", "/%2e%2e/store/rag_store.sqlite", "/nope.html"):
            self.assertEqual(self.request("GET", path)[0], 404, path)


class FeedbackTest(RagSrvCase):
    GOOD = {"session_id": "s1", "question": "q", "answer": "a", "evidence": [{"n": 1, "chunk_id": "a1"}],
            "verdict": "good", "comment": None}

    def count(self):
        con = sqlite3.connect(localstore.db_path(self.root))
        try:
            return con.execute("SELECT COUNT(*) FROM beol_rag_feedback").fetchone()[0]
        finally:
            con.close()

    def test_created(self):
        status, _, data, _ = self.request("POST", "/api/feedback", self.GOOD)
        self.assertEqual((status, json.loads(data)), (201, {}))
        self.assertEqual(self.count(), 1)

    def test_bad_input(self):
        bad = [dict(self.GOOD, verdict="meh"), dict(self.GOOD, question=""), dict(self.GOOD, question="x" * 2001),
               dict(self.GOOD, answer="x" * 8001), dict(self.GOOD, evidence=[{}] * 10),
               dict(self.GOOD, evidence=[{"t": "x" * 17000}]), dict(self.GOOD, comment="x" * 1001),
               dict(self.GOOD, session_id="x" * 101), dict(self.GOOD, evidence="[]")]
        for body in bad:
            status, _, data, _ = self.request("POST", "/api/feedback", body)
            self.assertEqual((status, json.loads(data)), (400, {"error": "BAD_INPUT"}))
        self.assertEqual(self.count(), 0)


class GuardTest(RagSrvCase):
    def test_other_host_403(self):
        self.assertEqual(self.request("GET", "/api/stats", headers={"Host": "evil.example:%d" % self.port})[0], 403)
        self.assertEqual(self.request("GET", "/", headers={"Host": None})[0], 403)
        status, _, data, _ = self.request("POST", "/api/ask", self.q(), headers={"Host": "evil.example"})
        self.assertEqual(status, 403)
        self.chat_mock.assert_not_called()

    def test_post_needs_same_origin_and_json(self):
        self.assertEqual(self.request("POST", "/api/ask", self.q(), headers={"Origin": None})[0], 403)
        self.assertEqual(self.request("POST", "/api/ask", self.q(), headers={"Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.request("POST", "/api/feedback", FeedbackTest.GOOD,
                                      headers={"Content-Type": "text/plain"})[0], 403)
        self.embed_mock.assert_not_called()

    def test_options_and_other_methods_405_without_cors(self):
        for method in ("OPTIONS", "PUT", "DELETE"):
            status, _, data, r = self.request(method, "/api/ask")
            self.assertEqual((status, json.loads(data)), (405, {"error": "METHOD_NOT_ALLOWED"}), method)
            self.assertIsNone(r.getheader("Access-Control-Allow-Origin"))

    def test_unknown_post_404(self):
        self.assertEqual(self.request("POST", "/api/other", {})[0], 404)


class StartupTest(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def run_main(self, env, argv):
        err = io.StringIO()
        with mock.patch.dict(os.environ, env), mock.patch("labelbot.ragsrv.load_env_file"), \
                mock.patch("sys.stderr", err), mock.patch.object(ragsrv, "make_server") as ms:
            code = ragsrv.main(argv)
        ms.assert_not_called()
        return code, err.getvalue()

    def test_missing_rag_config_exits_2(self):
        code, err = self.run_main({"BEOL_RAG_STORE": os.path.join(self.base, "none")}, [])
        self.assertEqual(code, 2)
        self.assertIn("[ragsrv] rag_config.json 없음: 먼저 push-vectors를 실행하세요", err)

    def test_missing_key_exits_2(self):
        localstore.write_rag_config(self.base, {"model": "", "api_key_env": "OPENAI_API_KEY"},
                                    {"model": EMB_MODEL, "api_key_env": "OPENAI_API_KEY"})
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            os.environ.pop("OPENAI_API_KEY")
            code, err = self.run_main({}, ["--store", self.base])
        self.assertEqual(code, 2)
        self.assertEqual(err.strip(), "[ragsrv] OPENAI_API_KEY 없음")

    def test_chat_model_order(self):
        localstore.write_rag_config(self.base, {"model": "from-config"}, {"model": EMB_MODEL})
        with mock.patch.dict(os.environ, {"RAG_CHAT_MODEL": ""}):
            self.assertEqual(ragsrv.load_config(self.base, "from-arg")[0]["model"], "from-arg")
            self.assertEqual(ragsrv.load_config(self.base)[0]["model"], "from-config")
            os.environ["RAG_CHAT_MODEL"] = "from-env"
            self.assertEqual(ragsrv.load_config(self.base)[0]["model"], "from-env")
        localstore.write_rag_config(self.base, {"model": ""}, {"model": EMB_MODEL})
        with mock.patch.dict(os.environ, {"RAG_CHAT_MODEL": ""}):
            llm_cfg, emb_cfg = ragsrv.load_config(self.base)
        self.assertEqual(llm_cfg["model"], "gpt-6-sol")
        self.assertEqual(llm_cfg["chat_path"], "/chat/completions")
        self.assertEqual(emb_cfg["path"], "/embeddings")


class SourceTest(unittest.TestCase):
    def test_no_low_level_network_imports(self):
        text = Path(ragsrv.__file__).read_text(encoding="utf-8")
        for name in ("urllib", "http.client", "socket"):
            self.assertIsNone(re.search(r"^\s*(?:import|from)\s+%s\b" % re.escape(name), text, re.M), name)
        self.assertNotIn("temperature", text)


if __name__ == "__main__":
    unittest.main()
