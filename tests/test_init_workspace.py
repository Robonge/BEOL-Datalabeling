"""init_workspace.py: pipeline.json의 taxonomy_path·input_root는 저장소 안이면 작업 폴더 기준 상대경로로 쓴다."""
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INIT_WS = os.path.join(REPO, ".claude", "skills", "BEOL-labeling", "scripts", "init_workspace.py")


def load():
    spec = importlib.util.spec_from_file_location("_iw_test", INIT_WS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class InitWorkspacePathsTest(unittest.TestCase):
    def setUp(self):
        self.mod = load()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.tmp.name)   # 가짜 저장소 루트
        os.makedirs(os.path.join(self.root, "taxonomy"))
        self.other = tempfile.TemporaryDirectory()  # 저장소 밖 입력 폴더

    def tearDown(self):
        self.tmp.cleanup()
        self.other.cleanup()

    def run_main(self, inp, ws):
        buf = io.StringIO()
        with mock.patch.object(self.mod, "CODE_ROOT", self.root), \
                mock.patch.object(self.mod, "LIST_DIR", os.path.join(self.root, "injested-file-list")), \
                mock.patch.object(self.mod, "upsert_launch", lambda name, port, w: port), \
                mock.patch.object(sys, "argv", ["init_workspace.py", "--input", inp, "--workspace", ws]), \
                contextlib.redirect_stdout(buf):
            self.assertEqual(self.mod.main(), 0)
        with open(os.path.join(ws, "pipeline.json"), encoding="utf-8") as f:
            return json.loads(buf.getvalue()), json.load(f)

    def test_two_levels_deep_workspace_gets_relative_paths(self):
        inp = os.path.join(self.root, "parshing test files")
        os.makedirs(inp)
        out, cfg = self.run_main(inp, os.path.join(self.root, "workspaces", "a", "b"))
        self.assertEqual(cfg["taxonomy_path"], "../../../taxonomy/taxonomy.json")
        self.assertEqual(cfg["input_root"], "../../../parshing test files")
        self.assertEqual(out["path_notes"], {})

    def test_input_outside_repo_stays_absolute(self):
        inp = os.path.realpath(self.other.name)
        out, cfg = self.run_main(inp, os.path.join(self.root, "workspaces", "w"))
        self.assertEqual(cfg["input_root"], inp.replace("\\", "/"))
        self.assertEqual(cfg["taxonomy_path"], "../../taxonomy/taxonomy.json")
        self.assertEqual(out["path_notes"], {"input_root": "OUTSIDE_REPO"})


if __name__ == "__main__":
    unittest.main()
