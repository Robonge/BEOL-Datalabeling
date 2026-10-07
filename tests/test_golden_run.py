"""labelbot 실행 산출물 golden(동작 무변경 리팩터링 안전망). mock LLM, 더미 파일 3개.

CLI 명령(run, review, compare, report, dashboard, apply, embed, push-vectors, push-slides, selfcheck)을 차례로 돌리고
작업 폴더에 생긴 파일 목록, failures (stage, reason_code) 건수, labels 행 수·열, out/labeling.sqlite 표별 행 수·내용 해시,
명령별 stdout을 tests/golden_run/snapshot.json으로, reports/baseline_<run>.md와 out/SCHEMA.md를 .md로 고정한다.
실행 ID, 시각, 임시 경로, Python·SQLite 버전만 정규화한다. GOLDEN_UPDATE=1이면 golden을 다시 쓴다.
"""
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import tempfile
import unittest
from unittest import mock

from labelbot import cli, llm, pipeline, store
from labelbot.mock import MockChatTransport
from labelbot.workspace import CODE_ROOT
from tests.test_pipeline import responder

from tests._dummy import DUMMY_DIR  # noqa: E402  저장소 밖 더미 폴더(tests/_dummy.py)
TAXONOMY = os.path.join(CODE_ROOT, "taxonomy", "taxonomy.json")
GOLDEN_DIR = os.path.join(CODE_ROOT, "tests", "golden_run")
N_FILES = 3
COMMANDS = ["review", "compare", "report", "dashboard", "apply", "embed", "push-vectors", "push-slides", "selfcheck"]

_RUN_ID = re.compile(r"\d{8}T\d{6}-[0-9a-f]{4}")
_ISO = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_STAMP = re.compile(r"\d{8}_\d{6}")


def _include_ids():
    with open(llm.DUMMY_HASHES_PATH, encoding="utf-8") as f:
        ids = [json.loads(line)["file_id"] for line in f if line.strip()]
    return ids[:N_FILES]


class _Norm:
    def __init__(self, root):
        self.roots = sorted({root, os.path.realpath(root), root.replace("\\", "/"),
                             os.path.realpath(root).replace("\\", "/")}, key=len, reverse=True)

    def __call__(self, s):
        for r in self.roots:
            s = s.replace(r, "<WS>")
        s = _RUN_ID.sub("<RUN>", s)
        s = _ISO.sub("<TS>", s)
        s = _STAMP.sub("<STAMP>", s)
        s = s.replace(sqlite3.sqlite_version, "<SQLITE>")
        return re.sub(r"(python\s+PASS )\S+", r"\1<PY>", s)


def _rowhash(rows, norm):
    h = hashlib.sha256()
    for r in sorted(norm(json.dumps(list(r), ensure_ascii=False, default=str)) for r in rows):
        h.update(r.encode("utf-8") + b"\n")
    return h.hexdigest()


def _chat_client(real):
    def make(cfg, con, transport=None, log=None):
        return real(cfg, con, transport=transport or MockChatTransport(responder), log=log)
    return make


class GoldenRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="labelbot_golden_")
        cfg = {"taxonomy_path": TAXONOMY, "input_root": DUMMY_DIR, "include_file_ids": _include_ids(),
               "llm": {"transport": "mock", "model": "mock", "max_retries": 1},
               "embedding": {"transport": "mock"}, "supabase": {"enabled": False},
               "feedback": {"rules_path": os.path.join(cls.dir, "no_rules.json"), "examples_root": cls.dir}}
        cls.ws_dir = os.path.join(cls.dir, "ws")
        os.makedirs(cls.ws_dir)
        with open(os.path.join(cls.ws_dir, "pipeline.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        cls.norm = _Norm(cls.ws_dir)
        cls.stdout, cls.codes = {}, {}
        with mock.patch.object(pipeline, "ChatClient", _chat_client(pipeline.ChatClient)):
            cls._cli("run", "--input", DUMMY_DIR)
            cls.files_after_run = cls._files()
            cls.baseline_run = cls._baseline()
            for c in COMMANDS:
                cls._cli(c)
                if c == "report":
                    cls.baseline_report = cls._baseline()
        cls.files_after_all = cls._files()
        con = store.connect(os.path.join(cls.ws_dir, "work.sqlite"))
        try:
            cls.run_id = store.latest_run(con, ("run",))
            cls.failures = sorted("%s %s %d" % tuple(r) for r in con.execute(
                "SELECT stage, reason_code, COUNT(*) FROM failures WHERE run_id=? GROUP BY stage, reason_code",
                (cls.run_id,)))
            cls.labels = {"rows": con.execute("SELECT COUNT(*) FROM labels WHERE run_id=?", (cls.run_id,)).fetchone()[0],
                          "columns": [r[1] for r in con.execute("PRAGMA table_info(labels)")]}
        finally:
            con.close()
        out = sqlite3.connect(os.path.join(cls.ws_dir, "out", "labeling.sqlite"))
        try:
            cls.out_tables = {}
            for (t,) in out.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
                q = "SELECT * FROM %s" % t
                if t == "meta":
                    q += " WHERE key NOT IN ('created_at')"
                rows = out.execute(q).fetchall()
                cls.out_tables[t] = {"rows": len(rows), "sha256": _rowhash(rows, cls.norm)}
        finally:
            out.close()

    @classmethod
    def _cli(cls, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cli.main([argv[0], "--workspace", cls.ws_dir] + list(argv[1:]))
        cls.stdout[argv[0]] = [cls.norm(line) for line in buf.getvalue().splitlines()]
        cls.codes[argv[0]] = code

    @classmethod
    def _baseline(cls):
        con = store.connect(os.path.join(cls.ws_dir, "work.sqlite"))
        try:
            rid = store.latest_run(con, ("run",))
        finally:
            con.close()
        with open(os.path.join(cls.ws_dir, "reports", "baseline_%s.md" % rid), encoding="utf-8") as f:
            return cls.norm(f.read())

    @classmethod
    def _files(cls):
        out = []
        for sub in ("reports", "screens", "out"):
            base = os.path.join(cls.ws_dir, sub)
            for root, _, files in os.walk(base):
                for f in files:
                    out.append(cls.norm(os.path.relpath(os.path.join(root, f), cls.ws_dir).replace("\\", "/")))
        return sorted(out)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def _read(self, *parts):
        with open(os.path.join(self.ws_dir, *parts), encoding="utf-8") as f:
            return self.norm(f.read())

    def _golden(self, name, actual):
        path = os.path.join(GOLDEN_DIR, name)
        if os.environ.get("GOLDEN_UPDATE") == "1" or not os.path.isfile(path):
            os.makedirs(GOLDEN_DIR, exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(actual)
            if os.environ.get("GOLDEN_UPDATE") != "1":
                self.fail("golden이 없어 새로 만들었다: %s (다시 실행하라)" % name)
            return
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), actual, name)

    def test_snapshot(self):
        snap = {"exit_codes": self.codes, "stdout": self.stdout, "files_after_run": self.files_after_run,
                "files_after_all": self.files_after_all, "failures": self.failures, "labels": self.labels,
                "out_labeling_sqlite": self.out_tables}
        self._golden("snapshot.json", json.dumps(snap, ensure_ascii=False, indent=1, sort_keys=True) + "\n")

    def test_baseline_report(self):
        self._golden("baseline_run.md", self.baseline_run)
        self._golden("baseline_report_cmd.md", self.baseline_report)

    def test_schema_md(self):
        self._golden("SCHEMA.md", self._read("out", "SCHEMA.md"))


if __name__ == "__main__":
    unittest.main()
