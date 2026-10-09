"""마일스톤 추적(labelbot/trace.py): 줄 형식·기록·추적 파일·CLI 가드·화면 서버 중단(Ctrl+C).

- 출력은 stderr만(stdout 불변), 실패 블록 = 헤더·원인·조치(+추적), 사유 코드는 .reason_code 또는 UNEXPECTED_<이름>.
- 추적 파일·터미널에 str(exc)(사내 파일명이 섞일 수 있다)이 나오지 않는다. BEOL_TRACE=1은 터미널에만, 저장 안 함.
- milestones.jsonl 필드·두 스레드 동시 기록, --help는 마일스톤 줄 없이 0, 잡히지 않은 예외는 1, PipelineError str 불변.
"""
import contextlib
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

from labelbot import trace
from labelbot.workspace import CODE_ROOT

FAKE_NAME = "260122_비밀 공정 결과 보고.pptx"
FIELDS = {"ts", "milestone", "status", "run_id", "reason_code", "detail_code", "elapsed_s"}


class Boom(Exception):
    def __init__(self):
        Exception.__init__(self, "열 수 없음: " + FAKE_NAME)
        self.reason_code = "HTTP_401"


def _env():
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    env.pop("BEOL_TRACE", None)
    return env


class _TraceCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="trace_test_")
        self.ws = os.path.join(self.tmp, "ws")
        os.makedirs(self.ws)
        self.trace_dir = os.path.join(self.tmp, "_trace")
        p = mock.patch.dict(os.environ, {trace.TRACE_DIR_ENV: self.trace_dir})
        p.start()
        self.addCleanup(p.stop)
        os.environ.pop(trace.TRACE_ENV, None)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def capture(self, fn):
        err, out = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            res = fn()
        return res, out.getvalue(), err.getvalue()

    def rows(self, root=None):
        path = os.path.join(root or os.path.join(self.ws, "logs"), trace.JSONL)
        if not os.path.isfile(path):
            return []
        with open(path, encoding="utf-8") as f:
            return [json.loads(line) for line in f]


class MilestoneTest(_TraceCase):
    def test_success_lines_and_record(self):
        def body():
            with trace.milestone("M07", run_id="R1", workspace=self.ws) as m:
                print("stdout 그대로")
                m.n = 5
        _, out, err = self.capture(body)
        self.assertEqual("stdout 그대로\n", out)
        lines = err.splitlines()
        self.assertEqual("[M07 EMBED] 시작 run=R1", lines[0])
        self.assertRegex(lines[1], r"^\[M07 EMBED\] 완료 n=5 t=\d+\.\ds$")
        (row,) = self.rows()
        self.assertEqual(FIELDS, set(row))
        self.assertEqual(("M07", "ok", "R1", None), (row["milestone"], row["status"], row["run_id"], row["reason_code"]))

    def test_failure_block_trace_file_and_no_message_leak(self):
        def body():
            with trace.milestone("M07", run_id="R2", workspace=self.ws):
                raise Boom()
        with self.assertRaises(Boom):
            self.capture(body)
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(Boom):
            body()
        text = err.getvalue()
        self.assertIn("[M07 EMBED] 실패  사유=HTTP_401\n  원인: 임베딩 API 인증 거부\n  조치: ", text)
        self.assertIn("추적: ", text)
        self.assertIn("(사유=HTTP_401)", text)  # 블록 안에서 사유 코드 반복
        self.assertNotIn(FAKE_NAME, text)
        self.assertNotIn("Traceback", text)
        path = os.path.join(self.ws, "logs", "trace_R2.log")
        with open(path, encoding="utf-8") as f:
            body_text = f.read()
        self.assertIn("exception=Boom", body_text)
        self.assertIn("tests/test_trace.py:", body_text)
        self.assertIn("reason=HTTP_401", body_text)
        self.assertNotIn(FAKE_NAME, body_text)
        self.assertNotIn("열 수 없음", body_text)
        fails = [r for r in self.rows() if r["status"] == "fail"]
        self.assertEqual(["HTTP_401"], sorted(set(r["reason_code"] for r in fails)))

    def test_unexpected_code_and_stdout_flushed_first(self):
        order = []

        class Out(io.StringIO):
            def flush(self):
                order.append("flush")

        class Err(io.StringIO):
            def write(self, s):
                if "실패" in s:
                    order.append("block")
                return io.StringIO.write(self, s)

        err = Err()
        with contextlib.redirect_stdout(Out()), contextlib.redirect_stderr(err), self.assertRaises(KeyError):
            with trace.milestone("M02", workspace=self.ws):
                raise KeyError(FAKE_NAME)
        self.assertIn("사유=UNEXPECTED_KeyError", err.getvalue())
        self.assertNotIn(FAKE_NAME, err.getvalue())
        self.assertLess(order.index("flush"), order.index("block"))

    def test_beol_trace_prints_traceback_only_to_terminal(self):
        err = io.StringIO()
        with mock.patch.dict(os.environ, {trace.TRACE_ENV: "1"}), contextlib.redirect_stderr(err):
            with self.assertRaises(Boom):
                with trace.milestone("M07", run_id="R3", workspace=self.ws):
                    raise Boom()
        self.assertIn("Traceback", err.getvalue())
        self.assertIn("터미널에만", err.getvalue())
        self.assertFalse(os.path.exists(os.path.join(self.ws, "logs", "trace_R3.log")))

    def test_keyboard_interrupt(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(KeyboardInterrupt):
            with trace.milestone("M05", workspace=self.ws):
                raise KeyboardInterrupt()
        self.assertIn("[M05 REVIEW_SERVE] 중단(사용자)", err.getvalue())
        self.assertEqual("abort", self.rows()[-1]["status"])

    def test_nested_failure_is_reported_once(self):
        def body():
            with trace.milestone("M01", workspace=self.ws, quiet=True):
                with trace.milestone("M02", workspace=self.ws):
                    raise Boom()
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(Boom):
            body()
        self.assertEqual(1, err.getvalue().count("실패  사유="))
        self.assertIn("[M02 CLASSIFY] 실패", err.getvalue())

    def test_decorator(self):
        @trace.milestone("M21", workspace=self.ws)
        def build():
            return 7
        res, _, err = self.capture(build)
        self.assertEqual(7, res)
        self.assertIn("[M21 PROJECT_HTML] 완료", err)

    def test_concurrent_jsonl_writes(self):
        def work(i):
            for j in range(100):
                trace.record("M08", "ok", run_id="T%d-%d" % (i, j), workspace=self.ws)
        ts = [threading.Thread(target=work, args=(i,)) for i in range(2)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        rows = self.rows()
        self.assertEqual(200, len(rows))
        self.assertEqual(200, len({r["run_id"] for r in rows}))
        for r in rows:
            self.assertEqual(FIELDS, set(r))

    def test_no_workspace_goes_to_trace_dir(self):
        self.capture(lambda: trace.run("M20", lambda: 1))
        (row,) = self.rows(self.trace_dir)
        self.assertEqual(("M20", "fail", "RC_1"), (row["milestone"], row["status"], row["reason_code"]))

    def test_record_never_writes_free_text(self):
        trace.record("M07", "fail", reason_code="열 수 없음 " + FAKE_NAME, detail_code=FAKE_NAME, workspace=self.ws)
        (row,) = self.rows()
        self.assertEqual(("INVALID_CODE", None), (row["reason_code"], row["detail_code"]))


class FailBlockApiTest(_TraceCase):
    def test_four_positional_args(self):
        """tools/verify_import.py·carry_state.py 방식: fail_block(MILESTONE, code, cause, action)."""
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            trace.fail_block("M19 IMPORT", "CODE_CHANGED", "code 파일이 바뀌었다", "이 릴리스를 쓰지 않는다")
        self.assertEqual("[M19 IMPORT] 실패  사유=CODE_CHANGED\n  원인: code 파일이 바뀌었다\n  조치: 이 릴리스를 쓰지 않는다\n",
                         err.getvalue())

    def test_catalog_lookup_and_stream(self):
        s = io.StringIO()
        trace.fail_block("M07", "HTTP_401", stream=s)
        self.assertTrue(s.getvalue().startswith("[M07 EMBED] 실패  사유=HTTP_401\n  원인: 임베딩 API 인증 거부\n  조치: "))
        s = io.StringIO()
        trace.fail_block("M00", "RC_2", detail_code="X_Y", stream=s, trace_path="workspaces/w/logs/trace_r.log")
        self.assertIn("세부=X_Y", s.getvalue())
        self.assertIn("  추적: workspaces/w/logs/trace_r.log  (사유=RC_2)", s.getvalue())


class RunGuardTest(_TraceCase):
    def test_exit_codes(self):
        self.assertEqual(0, self.capture(lambda: trace.run("M04", lambda: 0, workspace=self.ws))[0])
        rc, _, err = self.capture(lambda: trace.run("M04", lambda: 2, workspace=self.ws))
        self.assertEqual(2, rc)
        self.assertIn("사유=RC_2", err)
        rc, _, err = self.capture(lambda: trace.run("M23", lambda: 3, workspace=self.ws))
        self.assertEqual(3, rc)
        self.assertIn("건너뜀 사유=RC_3", err)

        def boom():
            raise Boom()
        rc, _, err = self.capture(lambda: trace.run("M07", boom, workspace=self.ws))
        self.assertEqual(1, rc)  # 3이 아니다
        self.assertIn("사유=HTTP_401", err)

        def interrupt():
            raise KeyboardInterrupt()
        self.assertEqual(130, self.capture(lambda: trace.run("M07", interrupt, workspace=self.ws))[0])

    def test_fail_code_keeps_return_value(self):
        def body():
            print("[오류] something")
            trace.fail_code("INPUT_DIR_NOT_FOUND")
            return 1
        rc, out, err = self.capture(lambda: trace.run("M00", body, workspace=self.ws))
        self.assertEqual(1, rc)
        self.assertEqual("[오류] something\n", out)
        self.assertIn("사유=INPUT_DIR_NOT_FOUND", err)

    def test_system_exit_passes_through(self):
        def body():
            raise SystemExit(2)
        with self.assertRaises(SystemExit):
            self.capture(lambda: trace.run("M00", body, workspace=self.ws))
        self.assertEqual([], self.rows())

    def test_run_main_skips_help(self):
        calls = []
        res, _, err = self.capture(lambda: trace.run_main("M24", lambda: calls.append(1) or 0, argv=["--help"]))
        self.assertEqual("", err)
        res, _, err = self.capture(lambda: trace.run_main("M24", lambda: 0, argv=["--workspace", self.ws]))
        self.assertIn("[M24 WORKSPACE_INIT] 완료", err)
        self.assertEqual("ok", self.rows()[-1]["status"])


class PipelineErrorTest(unittest.TestCase):
    def test_str_unchanged_and_code(self):
        from labelbot.pipeline import PipelineError
        e = PipelineError("입력 폴더가 없습니다(--input).", reason_code="INPUT_DIR_NOT_FOUND")
        self.assertEqual("입력 폴더가 없습니다(--input).", str(e))
        self.assertEqual(("INPUT_DIR_NOT_FOUND", None), (e.reason_code, e.detail))
        self.assertEqual("x", str(PipelineError("x")))

    def test_load_taxonomy_missing_code(self):
        from labelbot import pipeline

        class W:
            taxonomy_path = os.path.join(tempfile.gettempdir(), "no_such_taxonomy_%d.json" % os.getpid())
        with self.assertRaises(pipeline.PipelineError) as cm:
            pipeline.load_taxonomy(W())
        self.assertEqual("TAXONOMY_MISSING", cm.exception.reason_code)
        self.assertEqual("taxonomy.json이 없습니다(TAXONOMY_MISSING). pipeline.json의 taxonomy_path를 확인하세요.",
                         str(cm.exception))


class CliGuardTest(unittest.TestCase):
    def run_cli(self, args):
        env = _env()
        env[trace.TRACE_DIR_ENV] = tempfile.mkdtemp(prefix="trace_cli_")
        self.addCleanup(shutil.rmtree, env[trace.TRACE_DIR_ENV], True)
        p = subprocess.run([sys.executable] + args, cwd=CODE_ROOT, env=env, capture_output=True, timeout=120)
        return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")

    def test_help_has_no_milestone_lines(self):
        for args in (["-m", "labelbot", "--help"], ["-m", "labelbot", "embed", "-h"], ["-m", "domain_engrbot", "-h"],
                     ["-m", "code_engrbot", "review", "-h"], ["nightly_run.py", "-h"],
                     [".claude/skills/BEOL-labeling/scripts/init_workspace.py", "--help"]):
            rc, out, err = self.run_cli(args)
            with self.subTest(args=args):
                self.assertEqual(0, rc, err)
                self.assertNotIn("[M", err)
                self.assertTrue(out.startswith("usage:"))

    def test_argparse_error_is_2_without_milestone(self):
        rc, out, err = self.run_cli(["-m", "labelbot", "embed"])
        self.assertEqual(2, rc)
        self.assertNotIn("[M07", err)

    def test_workspace_error_exit_2_recorded_in_trace_dir(self):
        rc, out, err = self.run_cli(["-m", "labelbot", "embed", "--workspace", os.path.join(CODE_ROOT, "labelbot")])
        self.assertEqual(2, rc)
        self.assertIn("[오류] 작업 폴더는 코드 폴더의 workspaces/ 아래에만", err)
        self.assertIn("[M07 EMBED] 실패  사유=WORKSPACE_INSIDE_CODE", err)
        self.assertEqual("", out)


def _load_script(rel, name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(CODE_ROOT, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ServerInterruptTest(_TraceCase):
    """화면 서버 4종 + wait_review_done.py: Ctrl+C → '[Mxx …] 중단(사용자)', 종료 코드 0."""

    def assertAborted(self, rc, err, label):
        self.assertEqual(0, rc)
        self.assertIn("[%s] 중단(사용자)" % label, err)

    def test_labelbot_serve(self):
        import http.server
        from labelbot import serve

        class W:
            root = self.ws
        with mock.patch.object(http.server.ThreadingHTTPServer, "serve_forever", side_effect=KeyboardInterrupt):
            rc, _, err = self.capture(lambda: serve.serve(W(), 0))
        self.assertIn("[M05 REVIEW_SERVE] 대기 중 URL=http://127.0.0.1:", err)
        self.assertAborted(rc, err, "M05 REVIEW_SERVE")
        self.assertEqual("abort", self.rows()[-1]["status"])

    def test_domain_review_and_question_servers(self):
        from domain_engrbot import qmodel
        from domain_engrbot import serve as dserve

        class P:
            inbox = qa = self.ws

            def run_dir(self, qa_run):
                return self_ws
        self_ws = self.ws
        with mock.patch.object(dserve._Server, "serve_forever", side_effect=KeyboardInterrupt):
            rc, _, err = self.capture(lambda: dserve.serve(P(), "QA-1", 0))
            self.assertAborted(rc, err, "M11 DOMAIN_QA")
            with open(os.path.join(self.ws, qmodel.SCREEN), "w", encoding="utf-8") as f:
                f.write("<html></html>")
            with mock.patch.object(qmodel, "load_set", return_value={"set_id": "S1"}):
                rc, _, err = self.capture(lambda: dserve.serve_questions(P(), self.ws, 0))
            self.assertAborted(rc, err, "M11 DOMAIN_QA")

    def test_taxonomy_editor_and_board(self):
        from domain_engrbot import taxonomy_board, taxonomy_editor
        tax = os.path.join(CODE_ROOT, "taxonomy", "taxonomy.json")
        with mock.patch.object(threading.Thread, "join", side_effect=KeyboardInterrupt):
            rc, _, err = self.capture(lambda: taxonomy_editor.serve_editor(tax, print, port=0))
            self.assertAborted(rc, err, "M12 TAXONOMY_BOARD")
            html = os.path.join(self.ws, "board.html")
            with open(html, "w", encoding="utf-8") as f:
                f.write("<html></html>")
            rc, _, err = self.capture(lambda: taxonomy_board.serve_board(html, self.ws, lambda: {}, tax, False, print, port=0))
            self.assertAborted(rc, err, "M12 TAXONOMY_BOARD")

    def test_wait_review_done(self):
        mod = _load_script(".claude/skills/BEOL-labeling-feedback/scripts/wait_review_done.py", "wait_review_done_t")
        argv = ["wait_review_done.py", "--workspace", self.ws, "--run", "R1", "--interval", "0.01"]
        with mock.patch.object(sys, "argv", argv), mock.patch.object(mod.time, "sleep", side_effect=KeyboardInterrupt):
            rc, out, err = self.capture(mod.main)
        self.assertAborted(rc, err, "M05 REVIEW_SERVE")
        self.assertEqual("", out)

    def test_post_failure_line(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            trace.post_failed("M05", "ORIGIN_REJECTED", workspace=self.ws)
        self.assertEqual("[M05 REVIEW_SERVE] POST 실패  사유=ORIGIN_REJECTED\n", err.getvalue())
        self.assertEqual("post_fail", self.rows()[-1]["status"])

    def test_port_in_use(self):
        import errno
        from labelbot import serve

        class W:
            root = self.ws
        exc = OSError(errno.EADDRINUSE, "in use")
        with mock.patch.object(serve, "make_server", side_effect=exc):
            rc, _, err = self.capture(lambda: trace.run("M05", lambda: serve.serve(W(), 8771), workspace=self.ws))
        self.assertEqual(1, rc)
        self.assertIn("[오류] PORT_IN_USE 포트 8771 사용 중 (--port", err)
        self.assertIn("[M05 REVIEW_SERVE] 실패  사유=PORT_IN_USE", err)
        self.assertIn("--port", err.split("사유=PORT_IN_USE")[1])


if __name__ == "__main__":
    unittest.main()
