"""tools/cloud_migrate_paths.py: 옛 절대경로 → 작업 폴더 기준 상대경로 변환(가짜 저장소, 임시 폴더)."""
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(REPO, "tools", "cloud_migrate_paths.py")
INIT_WS = os.path.join(REPO, ".claude", "skills", "BEOL-labeling", "scripts", "init_workspace.py")
OLD_WIN = "X:/old/repo"
OLD_POSIX = "/old/rel-1"


def run_tool(*args):
    # 마일스톤 줄(한글)이 stderr로 나오므로 하위 프로세스 출력 인코딩을 UTF-8로 맞춘다(Windows 기본 cp949)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    p = subprocess.run([sys.executable, TOOL] + list(args), capture_output=True, text=True, encoding="utf-8", env=env)
    out = json.loads(p.stdout.strip().splitlines()[-1]) if p.stdout.strip() else None
    return p.returncode, out, p.stderr


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class CloudMigratePathsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.tmp.name)
        self.ws = os.path.join(self.root, "workspaces")
        write_json(os.path.join(self.ws, "w1", "pipeline.json"), {
            "taxonomy_path": OLD_WIN + "/taxonomy/taxonomy.json",
            "input_root": OLD_WIN.replace("/", "\\") + "\\parshing test files",
            "llm": {"model": "m"}})
        write_json(os.path.join(self.ws, "w2", "pipeline.json"), {
            "taxonomy_path": OLD_POSIX.upper() + "/taxonomy/taxonomy.json",   # 대소문자 무시
            "input_root": "Y:/elsewhere/docs"})                               # 저장소 밖 → 그대로
        write_json(os.path.join(self.root, "injested-file-list", "w1.json"), {
            "run_id": "r1", "workspace": OLD_WIN + "/workspaces/w1",
            "input": OLD_WIN + "/parshing test files", "files": ["a.pptx"]})
        os.makedirs(os.path.join(self.ws, "_nightly"))   # pipeline.json 없는 폴더는 세지 않는다
        self.args = ["--root", self.root, "--old-root", OLD_WIN, "--old-root", OLD_POSIX]

    def tearDown(self):
        self.tmp.cleanup()

    def cfg(self, name):
        return read_json(os.path.join(self.ws, name, "pipeline.json"))

    def test_relative_conversion_and_idempotent(self):
        rc, out, err = run_tool(*self.args, "--apply")
        self.assertEqual(rc, 0, err)
        self.assertEqual((out["files_scanned"], out["files_converted"], out["fields_converted"],
                          out["fields_already_ok"], out["fields_outside_repo"], out["errors"]), (2, 2, 3, 0, 1, 0))
        self.assertEqual(self.cfg("w1")["taxonomy_path"], "../../taxonomy/taxonomy.json")
        self.assertEqual(self.cfg("w1")["input_root"], "../../parshing test files")
        self.assertEqual(self.cfg("w1")["llm"], {"model": "m"})
        self.assertEqual(self.cfg("w2")["input_root"], "Y:/elsewhere/docs")
        with open(os.path.join(self.ws, "w1", "pipeline.json"), encoding="utf-8", newline="") as f:
            text = f.read()
        self.assertTrue(text.endswith("}\n") and "\r" not in text and text.startswith('{\n  "taxonomy_path"'))
        # 두 번째 실행: 바꿀 것이 없다
        rc, out, _ = run_tool(*self.args, "--apply")
        self.assertEqual((rc, out["files_converted"], out["fields_converted"], out["fields_already_ok"],
                          out["fields_outside_repo"], out["backup"]), (0, 0, 0, 3, 1, None))
        # 목록 파일은 플래그가 없으면 손대지 않는다
        lst = read_json(os.path.join(self.root, "injested-file-list", "w1.json"))
        self.assertEqual(lst["workspace"], OLD_WIN + "/workspaces/w1")

    def test_posix_drive_letter_value_is_converted(self):
        """POSIX에서도 X:/… 는 os.path.isabs가 False지만 상대경로(ALREADY_OK)로 보지 않고 변환한다."""
        rc, out, _ = run_tool(*self.args)
        self.assertEqual(rc, 0)
        self.assertEqual(out["fields_converted"], 3)
        self.assertEqual(out["fields_already_ok"], 0)

    def test_dry_run_writes_nothing(self):
        before = {n: self.cfg(n) for n in ("w1", "w2")}
        rc, out, _ = run_tool(*self.args)
        self.assertEqual((rc, out["files_converted"], out["backup"]), (0, 2, None))
        self.assertEqual({n: self.cfg(n) for n in ("w1", "w2")}, before)
        self.assertEqual(sorted(os.listdir(self.ws)), ["_nightly", "w1", "w2"])

    def test_new_root(self):
        rc, out, _ = run_tool(*self.args, "--new-root", "/config/work/repo", "--apply")
        self.assertEqual((rc, out["fields_converted"]), (0, 3))
        self.assertEqual(self.cfg("w1")["taxonomy_path"], "/config/work/repo/taxonomy/taxonomy.json")
        self.assertEqual(self.cfg("w2")["taxonomy_path"], "/config/work/repo/taxonomy/taxonomy.json")
        rc, out, _ = run_tool(*self.args, "--new-root", "/config/work/repo", "--apply")
        self.assertEqual((out["files_converted"], out["fields_already_ok"], out["fields_outside_repo"]), (0, 3, 1))

    def test_ingested_list(self):
        rc, out, _ = run_tool(*self.args, "--include-ingested-list", "--apply")
        self.assertEqual((rc, out["files_scanned"], out["files_converted"], out["fields_converted"]), (0, 3, 3, 5))
        lst = read_json(os.path.join(self.root, "injested-file-list", "w1.json"))
        self.assertEqual((lst["workspace"], lst["input"]), ("workspaces/w1", "../../parshing test files"))
        self.assertEqual(lst["files"], ["a.pptx"])

    def test_backup_log_and_restore(self):
        before = {n: self.cfg(n) for n in ("w1", "w2")}
        rc, out, _ = run_tool(*self.args, "--apply")
        self.assertEqual(rc, 0)
        bdir = os.path.join(self.root, *out["backup"].split("/"))
        self.assertTrue(os.path.basename(bdir).startswith("_migrate_backup_"))
        self.assertEqual(read_json(os.path.join(bdir, "workspaces", "w1", "pipeline.json")), before["w1"])
        with open(os.path.join(bdir, "migrate.jsonl"), encoding="utf-8") as f:
            recs = [json.loads(line) for line in f]
        self.assertTrue(recs)
        for r in recs:   # 사유 코드·순번만, 경로 값은 남기지 않는다
            self.assertLessEqual(set(r), {"ts", "kind", "index", "field", "reason"})
            self.assertNotIn("old", json.dumps(r))
        rc, res, _ = run_tool("--root", self.root, "--restore", out["backup"])
        self.assertEqual((rc, res["restored"], res["errors"]), (0, 2, 0))
        self.assertEqual({n: self.cfg(n) for n in ("w1", "w2")}, before)

    def test_missing_old_root_exits_2(self):
        rc, out, err = run_tool("--root", self.root)
        self.assertEqual(rc, 2)
        self.assertIn("--old-root", err)

    def test_unreadable_config_counts_error(self):
        os.makedirs(os.path.join(self.ws, "w3"))
        with open(os.path.join(self.ws, "w3", "pipeline.json"), "w", encoding="utf-8") as f:
            f.write("{깨진")
        rc, out, _ = run_tool(*self.args)
        self.assertEqual((rc, out["errors"], out["files_scanned"]), (1, 1, 3))

    def test_init_workspace_output_is_already_ok(self):
        """새 init_workspace가 쓴 pipeline.json은 도구에서 ALREADY_OK다."""
        spec = importlib.util.spec_from_file_location("_iw_for_migrate_test", INIT_WS)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        inp = os.path.join(self.root, "parshing test files")
        os.makedirs(inp)
        os.makedirs(os.path.join(self.root, "taxonomy"))
        ws = os.path.join(self.ws, "w9")
        argv = ["init_workspace.py", "--input", inp, "--workspace", ws]
        buf = io.StringIO()
        with mock.patch.object(mod, "CODE_ROOT", self.root), \
                mock.patch.object(mod, "LIST_DIR", os.path.join(self.root, "injested-file-list")), \
                mock.patch.object(mod, "upsert_launch", lambda name, port, w: port), \
                mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(buf):
            self.assertEqual(mod.main(), 0)
        self.assertEqual(json.loads(buf.getvalue())["path_notes"], {})
        cfg = self.cfg("w9")
        self.assertEqual((cfg["taxonomy_path"], cfg["input_root"]),
                         ("../../taxonomy/taxonomy.json", "../../parshing test files"))
        rc, out, _ = run_tool(*self.args)
        self.assertEqual(rc, 0)
        self.assertEqual((out["files_scanned"], out["fields_converted"], out["fields_already_ok"]), (3, 3, 2))


if __name__ == "__main__":
    unittest.main()
