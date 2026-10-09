"""상태·사유 코드 명령(labelbot/status.py, python -m labelbot status|codes, tools/beol_status.py)과 nightly 연동.

- fixture work.sqlite + milestones.jsonl → 표(✔/✖/—), 처음 실패 강조, 다음에 할 일(카탈로그 조치), 코드·ID만.
- milestones.jsonl이 없는 옛 실행도 runs·failures 표로 보인다.
- tools/beol_status.py와 python -m labelbot의 status·codes 출력이 같다.
- nightly_run: 실패 단계 사유 = milestones.jsonl 마지막 fail의 <코드>@<Mxx>(없으면 RC_<n>).
- 수락: dummy labelbot run(mock) → status M01–M04 ✔, 임베딩 401(loopback 가짜 서버) → 첫 ✖ M07 HTTP_401 + M07 조치.
"""
import contextlib
import http.server
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

from labelbot import status, store, trace
from labelbot.workspace import CODE_ROOT

FAKE_NAME = "260130_사내 비밀 자료.pptx"


def _env(trace_dir):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    env[trace.TRACE_DIR_ENV] = trace_dir
    return env


def _jsonl(ws, rows):
    os.makedirs(os.path.join(ws, "logs"), exist_ok=True)
    with open(os.path.join(ws, "logs", trace.JSONL), "a", encoding="utf-8") as f:
        for r in rows:
            base = {"ts": None, "milestone": None, "status": None, "run_id": None, "reason_code": None,
                    "detail_code": None, "elapsed_s": 0.1}
            base.update(r)
            f.write(json.dumps(base) + "\n")


class _WsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="status_test_")
        self.ws = os.path.join(self.tmp, "20261010_fixture")
        os.makedirs(self.ws)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        con = store.connect(os.path.join(self.ws, "work.sqlite"))
        con.execute("INSERT INTO runs(run_id, command, started_at, finished_at) VALUES(?,?,?,?)",
                    ("R1", "run", "2026-10-10T01:00:00Z", "2026-10-10T01:10:00Z"))
        for i in range(3):
            store.add_failure(con, "R1", "embed", "c%d" % i, "HTTP_401")
        store.add_failure(con, "R1", "parse", "f1", "ENCRYPTED")
        con.commit()
        con.close()

    def render(self):
        return status.render(self.ws)


class StatusRenderTest(_WsCase):
    def test_without_jsonl_old_run(self):
        out = self.render()
        self.assertIn("milestones.jsonl 없음", out)
        self.assertIn("최근 실행: R1 (run, 끝남)", out)
        for mid in ("M01 INGEST", "M02 CLASSIFY", "M03 LABEL", "M04 REPORT"):
            self.assertRegex(out, r"%s\s+✔" % mid)
        self.assertRegex(out, r"M07 EMBED\s+—.*3건\(HTTP_401\)")
        self.assertRegex(out, r"M01 INGEST\s+✔.*1건\(ENCRYPTED\)")
        self.assertIn("처음 실패: 없음", out)
        self.assertIn("다음 단계 M05 REVIEW_SERVE", out)

    def test_first_failure_highlight_and_next_step(self):
        _jsonl(self.ws, [
            {"ts": "2026-10-10T01:05:00Z", "milestone": "M01", "status": "ok", "run_id": "R1"},
            {"ts": "2026-10-10T02:00:00Z", "milestone": "M07", "status": "fail", "run_id": "R1", "reason_code": "HTTP_401"},
            {"ts": "2026-10-10T03:00:00Z", "milestone": "M09", "status": "fail", "run_id": "R1", "reason_code": "RENDERER_MISSING"},
            {"ts": "2026-10-10T03:30:00Z", "milestone": "M05", "status": "post_fail", "reason_code": "ORIGIN_REJECTED"},
            {"ts": "2026-10-10T03:40:00Z", "milestone": "M05", "status": "abort", "reason_code": "USER_ABORT"},
        ])
        out = self.render()
        self.assertNotIn("milestones.jsonl 없음", out)
        self.assertRegex(out, r"▶ M07 EMBED\s+✖\s+HTTP_401\s+2026-10-10T02:00:00Z\s+3건\(HTTP_401\)")
        self.assertRegex(out, r"  M09 SLIDE_IMAGES\s+✖\s+RENDERER_MISSING")
        self.assertRegex(out, r"M05 REVIEW_SERVE\s+✔\s+USER_ABORT.*POST 실패 1")
        self.assertIn("처음 실패: M07 EMBED  사유=HTTP_401", out)
        self.assertIn("원인: 임베딩 API 인증 거부", out)
        self.assertIn("다음에 할 일: workspaces/_site/beol.env의 임베딩 키 확인", out)
        self.assertIn("codes --milestone M07", out)
        self.assertNotIn(FAKE_NAME, out)

    def test_unfinished_run(self):
        con = store.connect(os.path.join(self.ws, "work.sqlite"))
        con.execute("INSERT INTO runs(run_id, command, started_at) VALUES(?,?,?)", ("R2", "run", "2026-10-10T05:00:00Z"))
        con.commit()
        con.close()
        out = self.render()
        self.assertIn("최근 실행: R2 (run, 미완료)", out)
        self.assertRegex(out, r"▶ M01 INGEST\s+✖\s+RUN_UNFINISHED")

    def test_cli_status_missing_workspace(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = status.main(["status", "--workspace", os.path.join(self.tmp, "nope")])
        self.assertEqual(1, rc)
        self.assertIn("WORKSPACE_NOT_FOUND", err.getvalue())

    def test_codes(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(0, status.main(["codes", "--milestone", "m07"]))
        text = out.getvalue()
        self.assertTrue(text.startswith("M07 EMBED"))
        self.assertIn("HTTP_401  [", text)
        self.assertIn("원인: 임베딩 API 인증 거부", text)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(0, status.main(["codes", "--entrypoints"]))
        self.assertIn("labelbot rules-diff", out.getvalue())
        self.assertIn(".claude/skills/BEOL-labeling/scripts/init_workspace.py", out.getvalue())


class SameOutputTest(_WsCase):
    """배포판 python3용 tools/beol_status.py와 python -m labelbot이 같은 모듈·같은 출력."""

    def run_both(self, args):
        td = os.path.join(self.tmp, "_trace")
        a = subprocess.run([sys.executable, "-m", "labelbot"] + args, cwd=CODE_ROOT, env=_env(td),
                           capture_output=True, timeout=120)
        b = subprocess.run([sys.executable, os.path.join("tools", "beol_status.py")] + args, cwd=CODE_ROOT,
                           env=_env(td), capture_output=True, timeout=120)
        return a, b

    def test_status_and_codes_match(self):
        _jsonl(self.ws, [{"ts": "2026-10-10T02:00:00Z", "milestone": "M07", "status": "fail", "run_id": "R1",
                          "reason_code": "HTTP_401"}])
        for args in (["status", "--workspace", self.ws], ["codes"], ["codes", "--milestone", "M02"],
                     ["codes", "--entrypoints"]):
            a, b = self.run_both(args)
            with self.subTest(args=args[:2]):
                self.assertEqual(0, a.returncode, a.stderr.decode("utf-8", "replace"))
                self.assertEqual(a.returncode, b.returncode)
                self.assertEqual(a.stdout, b.stdout)
                self.assertNotIn(b"[M00", a.stderr)  # 읽기 전용: 시작·완료 줄 없음


class NightlyReasonTest(unittest.TestCase):
    def test_failed_step_reason_from_milestones_jsonl(self):
        spec = importlib.util.spec_from_file_location("nightly_run_t", os.path.join(CODE_ROOT, "nightly_run.py"))
        nightly_run = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(nightly_run)
        tmp = tempfile.mkdtemp(prefix="nightly_test_")
        self.addCleanup(shutil.rmtree, tmp, True)
        wsp = os.path.join("workspaces", "w1")

        def fake_run(cmd, **kw):
            _jsonl(os.path.join(tmp, wsp), [{"ts": "2026-10-10T02:00:00Z", "milestone": "M07", "status": "fail",
                                             "reason_code": "HTTP_401"}])
            return subprocess.CompletedProcess(cmd, 1, b"", b"")

        steps = []
        with mock.patch.object(nightly_run, "ROOT", tmp), \
                mock.patch.dict(os.environ, {trace.TRACE_DIR_ENV: os.path.join(tmp, "_trace")}), \
                contextlib.redirect_stdout(io.StringIO()):
            with mock.patch.object(nightly_run.subprocess, "run", side_effect=fake_run):
                nightly_run.run("embed", ["labelbot", "embed", "--workspace", wsp], False, steps)
            with mock.patch.object(nightly_run.subprocess, "run",
                                   return_value=subprocess.CompletedProcess([], 2, b"", b"")):
                nightly_run.run("code_review", ["code_engrbot", "review", "--root", "."], False, steps)
        self.assertEqual(["HTTP_401@M07", "RC_2"], [s["reason"] for s in steps])
        self.assertEqual(["failed", "failed"], [s["status"] for s in steps])


class _Deny401(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.send_response(401)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *a):
        pass


class AcceptanceTest(unittest.TestCase):
    """dummy run(mock) → M01–M04 ✔ / 임베딩 401 → 첫 ✖ M07 HTTP_401(+조치), 경계마다 시작·완료 한 줄."""

    def test_run_then_embed_401(self):
        from labelbot import cli
        from tests._dummy import DUMMY_DIR
        tmp = tempfile.mkdtemp(prefix="status_accept_")
        self.addCleanup(shutil.rmtree, tmp, True)
        ws = os.path.join(tmp, "ws")
        os.makedirs(ws)
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Deny401)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        cfg = {"taxonomy_path": os.path.join(CODE_ROOT, "taxonomy", "taxonomy.json"), "input_root": DUMMY_DIR,
               "llm": {"transport": "mock", "model": "mock", "max_retries": 1},
               "embedding": {"transport": "http", "base_url": "http://127.0.0.1:%d" % srv.server_address[1],
                             "path": "/embeddings", "model": "fake", "api_key_env": "BEOL_TEST_FAKE_EMBED_KEY"},
               "supabase": {"enabled": False}}
        with open(os.path.join(ws, "pipeline.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        env = {trace.TRACE_DIR_ENV: os.path.join(tmp, "_trace"), "BEOL_TEST_FAKE_EMBED_KEY": "test-only"}
        with mock.patch.dict(os.environ, env):
            err = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, cli.main(["run", "--workspace", ws, "--no-feedback"]))
            lines = err.getvalue().splitlines()
            for mid in ("M01 INGEST", "M02 CLASSIFY", "M03 LABEL", "M04 REPORT"):
                self.assertEqual(1, sum(1 for l in lines if l.startswith("[%s] 시작 run=" % mid)), mid)
                self.assertEqual(1, sum(1 for l in lines if l.startswith("[%s] 완료" % mid)), mid)
            self.assertFalse([l for l in lines if "실패" in l])
            out = status.render(ws)
            for mid in ("M01 INGEST", "M02 CLASSIFY", "M03 LABEL", "M04 REPORT"):
                self.assertRegex(out, r"%s\s+✔" % mid)
            self.assertIn("처음 실패: 없음", out)

            err = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, cli.main(["embed", "--workspace", ws]))  # 종료 코드는 그대로(대상별 실패)
            self.assertRegex(err.getvalue(), r"\[M07 EMBED\] 시작 run=\S+")
            self.assertIn("[M07 EMBED] 실패  사유=HTTP_401\n  원인: 임베딩 API 인증 거부", err.getvalue())
            out = status.render(ws)
        self.assertRegex(out, r"▶ M07 EMBED\s+✖\s+HTTP_401")
        self.assertIn("처음 실패: M07 EMBED  사유=HTTP_401", out)
        self.assertIn("다음에 할 일: workspaces/_site/beol.env의 임베딩 키 확인", out)


if __name__ == "__main__":
    unittest.main()
