"""반입·업그레이드 도구(L5) 테스트: make_import_manifest·verify_import·carry_state.

- manifest: 임시 git 저장소의 blob 기준, class와 우선순위(state > code), 자기 자신 제외, label 검사, 상태 동결
- test_modules: tests._dummy를 직접·간접(from-import, 상대 import 포함) import하는 모듈 제외
- verify_import: OK / CHANGED / MISSING / EXTRA / RENAMED_OK / DRM_ENCRYPTED, 종료 코드, 보고서에 office 이름 없음
- carry_state: 판정 하나씩 + NO_BASE_MANIFEST, CONFLICT 행 단위 차이와 --resolve
- verify_import.py·carry_state.py는 Python 3.8 문법·stdlib만
"""
import ast
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
MAKE = os.path.join(TOOLS, "make_import_manifest.py")
VERIFY = os.path.join(TOOLS, "verify_import.py")
CARRY = os.path.join(TOOLS, "carry_state.py")
OFFICE_NAME = "secret-plan-name.pptx"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mim = _load(MAKE, "make_import_manifest")
vi = _load(VERIFY, "verify_import")


def run(script, *args):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    p = subprocess.run([sys.executable, script] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def write(root, rel, data):
    path = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode("utf-8"))
    return path


def sha(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode("utf-8")).hexdigest()


def git(root, *args):
    subprocess.run(["git", "-C", root, "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                    "-c", "core.autocrlf=false"] + list(args), check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def head(root):
    return subprocess.run(["git", "-C", root, "rev-parse", "HEAD"], stdout=subprocess.PIPE, check=True).stdout.decode().strip()


TREE = {
    "taxonomy/taxonomy.json": '{"taxonomy": []}\n',
    "taxonomy/labeling_rules.json": '{"rules": []}\n',
    "taxonomy/other.json": "{}\n",
    "injested-file-list/a.json": "[]\n",
    "rag/beol_rag.html": "<html></html>\n",
    "labelbot/__init__.py": "",
    "labelbot/core.py": "X = 1\n",
    "docs/" + OFFICE_NAME: b"PK\x03\x04fake-ooxml-body",
    "docs/data.csv": "a,b\n",
    "docs/clip.mp4": b"\x00\x00mp4",
    "requirements.txt": "\n",
    "LICENSE": "x\n",
    "transfer/import_manifest.json": '{"old": true}\n',
    "tests/__init__.py": "",
    "tests/_dummy.py": "DUMMY_DIR = 'x'\n",
    "tests/helper.py": "from . import _dummy\n",
    "tests/test_direct.py": "from tests._dummy import DUMMY_DIR\n",
    "tests/test_via_test.py": "from tests.test_direct import DUMMY_DIR\n",
    "tests/test_via_pkg_attr.py": "from tests import test_via_test as t\n",
    "tests/test_via_relative_helper.py": "import tests.helper\n",
    "tests/test_clean.py": "import os\nfrom labelbot import core\n",
    "tests/contracts/__init__.py": "",
    "tests/contracts/test_nested.py": "def f():\n    import tests._dummy\n",
    "domain_engrbot/__init__.py": "",
    "domain_engrbot/tests/__init__.py": "",
    "domain_engrbot/tests/test_dom.py": "import json\n",
}


class RepoCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="l5_")
        self.repo = os.path.join(self.tmp, "repo")
        for rel, data in TREE.items():
            write(self.repo, rel, data)
        git(self.repo, "init", "-q")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "init")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make(self, label="beol-import-test-local", *extra):
        out = os.path.join(self.tmp, "m_%d.json" % len(os.listdir(self.tmp)))
        rc, so, se = run(MAKE, "--root", self.repo, "--label", label, "--out", out, *extra)
        manifest = None
        if rc == 0:
            with open(out, encoding="utf-8") as f:
                manifest = json.load(f)
        return rc, manifest, out, so + se

    def release_dir(self, manifest):
        """git archive 대신: 커밋 내용 그대로(.git 제외) 복사 + manifest를 transfer/에."""
        rel = os.path.join(self.tmp, manifest["release_label"])
        shutil.copytree(self.repo, rel, ignore=shutil.ignore_patterns(".git"))
        write(rel, "transfer/import_manifest.json", json.dumps(manifest))
        return rel


class ManifestTest(RepoCase):
    def test_classes_precedence_and_self_exclusion(self):
        rc, m, _, out = self.make()
        self.assertEqual(rc, 0, out)
        cls = dict((f["path"], f["class"]) for f in m["files"])
        self.assertNotIn("transfer/import_manifest.json", cls)
        self.assertEqual(cls["taxonomy/taxonomy.json"], "state")  # .json이지만 state가 먼저
        self.assertEqual(cls["taxonomy/labeling_rules.json"], "state")
        self.assertEqual(cls["injested-file-list/a.json"], "state")
        self.assertEqual(cls["rag/beol_rag.html"], "state")
        self.assertEqual(cls["taxonomy/other.json"], "code")
        self.assertEqual(cls["labelbot/core.py"], "code")
        self.assertEqual(cls["docs/" + OFFICE_NAME], "office")
        self.assertEqual(cls["docs/data.csv"], "office")
        self.assertEqual(cls["docs/clip.mp4"], "media")
        self.assertEqual(cls["requirements.txt"], "text-other")
        self.assertEqual(cls["LICENSE"], "text-other")
        f = [x for x in m["files"] if x["path"] == "labelbot/core.py"][0]
        self.assertEqual((f["size"], f["sha256"]), (6, sha("X = 1\n")))
        self.assertEqual(m["source_commit"], head(self.repo))
        self.assertEqual(m["state_overrides"], [])
        self.assertIsNone(m["download_list_sha256"])
        globs = dict((e["glob"], e["tracked"]) for e in m["state_paths"])
        self.assertTrue(globs["taxonomy/taxonomy.json"])
        self.assertFalse(globs["workspaces/"])
        self.assertFalse(globs["docs/snapshots/*"])
        for key in ("release_label", "created_at", "test_modules"):
            self.assertIn(key, m)

    def test_test_modules_exclude_dummy_importers(self):
        rc, m, _, out = self.make()
        self.assertEqual(rc, 0, out)
        self.assertEqual(m["test_modules"], ["domain_engrbot/tests/test_dom.py", "tests/test_clean.py"])
        self.assertIn("test_modules=2 excluded_dummy=5", out)

    def test_label_rules(self):
        sha7 = head(self.repo)[:7]
        self.assertEqual(self.make("beol-import-20261010-%s" % sha7)[0], 0)
        rc, _, _, out = self.make("beol-import-20261010-0000000")
        self.assertEqual(rc, 1)
        self.assertIn("LABEL_SHA_MISMATCH", out)
        rc, _, _, out = self.make("Release 1")
        self.assertEqual(rc, 1)
        self.assertIn("LABEL_INVALID", out)

    def test_state_freeze(self):
        rc, base, base_path, _ = self.make()
        self.assertEqual(rc, 0)
        write(self.repo, "taxonomy/taxonomy.json", '{"taxonomy": [1]}\n')
        write(self.repo, "labelbot/core.py", "X = 2\n")  # code 변경은 동결 대상이 아니다
        git(self.repo, "commit", "-q", "-am", "change")
        rc, _, _, out = self.make("beol-import-test-local", "--base-manifest", base_path)
        self.assertEqual(rc, 1)
        self.assertIn("STATE_FROZEN", out)
        self.assertIn("taxonomy/taxonomy.json", out)
        rc, m, _, out = self.make("beol-import-test-local", "--base-manifest", base_path,
                                  "--override", "taxonomy/taxonomy.json=B6 축 추가")
        self.assertEqual(rc, 0, out)
        self.assertEqual(m["state_overrides"], [{"path": "taxonomy/taxonomy.json", "reason": "B6 축 추가"}])
        rc, _, _, out = self.make("beol-import-test-local", "--override", "labelbot/core.py=x")
        self.assertEqual(rc, 1)
        self.assertIn("OVERRIDE_NOT_STATE", out)

    def test_real_repo_dummy_graph(self):
        blobs = mim.read_blobs(ROOT, "HEAD")
        tests, excluded = mim.compute_test_modules(blobs)
        self.assertIn("tests/test_pipeline.py", excluded)
        self.assertIn("tests/test_rules_board.py", excluded)  # test_rules_update → test_pipeline 경유
        self.assertIn("tests/test_taxonomy.py", tests)
        self.assertFalse(set(tests) & set(excluded))


class VerifyImportTest(RepoCase):
    def setUp(self):
        RepoCase.setUp(self)
        rc, self.manifest, _, out = self.make()
        self.assertEqual(rc, 0, out)
        self.rel = self.release_dir(self.manifest)
        self.report = os.path.join(self.tmp, "_import", "r.json")

    def verify(self):
        rc, so, se = run(VERIFY, "--root", self.rel, "--report", self.report)
        with open(self.report, encoding="utf-8") as f:
            rep = json.load(f)
        return rc, rep, so + se

    def statuses(self, rep):
        return sorted((e["status"], e["class"], e.get("reason")) for e in rep["entries"])

    def test_all_ok(self):
        rc, rep, out = self.verify()
        self.assertEqual(rc, 0, out)
        self.assertEqual(rep["verdict"], "OK")
        self.assertEqual(rep["entries"], [])
        self.assertTrue(rep["root_name_matches_label"])
        self.assertEqual(sum(rep["counts"]["OK"].values()), len(self.manifest["files"]))
        self.assertIn("[M19 IMPORT] 완료", out)

    def test_default_report_location(self):
        rc, so, se = run(VERIFY, "--root", self.rel)
        self.assertEqual(rc, 0, so + se)
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "_import", "beol-import-test-local.json")))

    def test_code_changed_blocks(self):
        write(self.rel, "labelbot/core.py", "X = 666\n")
        rc, rep, out = self.verify()
        self.assertEqual(rc, 2)
        self.assertEqual(rep["verdict"], "BLOCKED")
        self.assertIn({"path": "labelbot/core.py", "status": "CHANGED", "class": "code"}, rep["entries"])
        self.assertIn("[M19 IMPORT] 실패  사유=CODE_CHANGED", out)

    def test_code_missing_blocks(self):
        os.remove(os.path.join(self.rel, "labelbot", "core.py"))
        rc, rep, _ = self.verify()
        self.assertEqual(rc, 2)
        self.assertEqual(self.statuses(rep), [("MISSING", "code", None)])

    def test_state_and_extra_do_not_block(self):
        write(self.rel, "taxonomy/taxonomy.json", '{"taxonomy": []}\r\n')
        write(self.rel, "notes/new.md", "x")
        write(self.rel, "labelbot/__pycache__/core.cpython-38.pyc", b"\x00")
        write(self.rel, "workspaces/ws1/work.sqlite", b"\x00")  # 비추적 state는 EXTRA 아님
        rc, rep, out = self.verify()
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.statuses(rep), [("CHANGED", "state", "EOL_CRLF"), ("EXTRA", None, None)])
        self.assertIn({"path": "notes/new.md", "status": "EXTRA", "class": None}, rep["entries"])
        self.assertEqual(rep["ignored_untracked"], 1)

    def test_office_renamed_ok_and_no_office_names_in_report(self):
        os.rename(os.path.join(self.rel, "docs", OFFICE_NAME), os.path.join(self.rel, "docs", "깨진이름.pptx"))
        rc, rep, out = self.verify()
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.statuses(rep), [("RENAMED_OK", "office", None)])
        idx = [f["path"] for f in self.manifest["files"]].index("docs/" + OFFICE_NAME)
        self.assertEqual(rep["entries"][0]["index"], idx)
        with open(self.report, encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn(OFFICE_NAME, text)
        self.assertNotIn("깨진이름", text)

    def test_drm_encrypted_and_not_ooxml(self):
        write(self.rel, "docs/" + OFFICE_NAME, b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1rest")
        write(self.rel, "docs/extra.docx", b"plain text")
        rc, rep, out = self.verify()
        self.assertEqual(rc, 0, out)  # office 변경은 차단하지 않는다
        self.assertEqual(self.statuses(rep), [("CHANGED", "office", "DRM_ENCRYPTED"), ("EXTRA", None, "NOT_OOXML")])
        extra = [e for e in rep["entries"] if e["status"] == "EXTRA"][0]
        self.assertNotIn("path", extra)
        self.assertEqual(extra["ext"], ".docx")

    def test_manifest_invalid(self):
        write(self.rel, "transfer/import_manifest.json", "not json")
        rc, so, se = run(VERIFY, "--root", self.rel, "--report", self.report)
        self.assertEqual(rc, 1)
        self.assertIn("[M19 IMPORT] 실패  사유=MANIFEST_INVALID", se)
        self.assertIn("  원인: ", se)
        self.assertIn("  조치: ", se)


def _manifest(label, files, state_paths):
    return {"release_label": label, "source_commit": "0" * 40, "files": [
        {"path": p, "size": len(d), "sha256": sha(d), "class": "state"} for p, d in sorted(files.items())],
        "state_paths": state_paths, "state_overrides": [], "test_modules": []}


class CarryStateTest(unittest.TestCase):
    STATE_PATHS = [{"glob": "st/*.json", "tracked": True}, {"glob": "taxonomy/taxonomy.json", "tracked": True},
                   {"glob": "workspaces/", "tracked": False}, {"glob": "workspaces/_site/", "tracked": False}]
    TAX_BASE = {"taxonomy": [{"축": "공정", "값": "etch", "상위값": ""}], "synonyms": []}

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="l5c_")
        self.old = os.path.join(self.tmp, "beol-import-r1")
        self.new = os.path.join(self.tmp, "beol-import-r2")
        X, Y, Z = '{"v": "x"}', '{"v": "y"}', '{"v": "z"}'
        tax = json.dumps(self.TAX_BASE, ensure_ascii=False)
        base = {"st/keep.json": X, "st/take.json": X, "st/conf.json": X, "st/reldel.json": X,
                "st/flag.json": X, "st/deldel.json": X, "taxonomy/taxonomy.json": tax}
        release = {"st/keep.json": X, "st/take.json": Z, "st/conf.json": Z, "st/flag.json": Z,
                   "st/deldel.json": X, "st/newrel.json": Z, "taxonomy/taxonomy.json": tax}
        closed = {"st/keep.json": Y, "st/take.json": X, "st/conf.json": Y, "st/reldel.json": X,
                  "st/added.json": Y, "taxonomy/taxonomy.json": tax}
        for rel, d in release.items():
            write(self.new, rel, d)
        for rel, d in closed.items():
            write(self.old, rel, d)
        write(self.old, "workspaces/ws1/work.sqlite", b"db")
        write(self.old, "workspaces/_site/beol.env", "TZ=Asia/Seoul\n")
        write(self.old, "transfer/import_manifest.json", json.dumps(_manifest("beol-import-r1", base, self.STATE_PATHS)))
        write(self.new, "transfer/import_manifest.json", json.dumps(_manifest("beol-import-r2", release, self.STATE_PATHS)))
        self.report = os.path.join(self.tmp, "carry_report.json")
        self.X, self.Y, self.Z = X, Y, Z

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def carry(self, *extra):
        rc, so, se = run(CARRY, "--old", self.old, "--new", self.new, "--report", self.report, *extra)
        rep = None
        if os.path.isfile(self.report):
            with open(self.report, encoding="utf-8") as f:
                rep = json.load(f)
        return rc, rep, so + se

    def read(self, rel):
        path = os.path.join(self.new, *rel.split("/"))
        if not os.path.isfile(path):
            return None
        with open(path, encoding="utf-8") as f:
            return f.read()

    def decisions(self, rep):
        return dict((r.get("path") or r["glob"], r["decision"]) for r in rep["rows"])

    def test_decisions_and_conflict_stop(self):
        rc, rep, out = self.carry()
        self.assertEqual(rc, 1, out)
        self.assertEqual(self.decisions(rep), {
            "st/keep.json": "KEEP_CLOSED", "st/take.json": "TAKE_RELEASE", "st/conf.json": "CONFLICT",
            "st/reldel.json": "FLAG_RELEASE_DELETED", "st/flag.json": "FLAG", "st/deldel.json": "KEEP_CLOSED",
            "st/added.json": "ADDED_CLOSED", "st/newrel.json": "TAKE_RELEASE", "taxonomy/taxonomy.json": "KEEP_CLOSED",
            "workspaces/": "COPIED_UNTRACKED", "workspaces/_site/": "COPIED_UNTRACKED"})
        self.assertEqual(rep["unresolved_conflicts"], ["st/conf.json"])
        self.assertIn("[M19 IMPORT] 실패  사유=CONFLICT", out)
        conf = [r for r in rep["rows"] if r.get("path") == "st/conf.json"][0]
        self.assertEqual(conf["diff"], {"kind": "json", "changes": [{"op": "changed", "key": "v"}]})
        self.assertEqual(self.read("st/keep.json"), self.X)  # dry-run(그리고 CONFLICT)이라 아무것도 안 씀

    def test_dry_run_writes_nothing(self):
        rc, rep, out = self.carry("--resolve", "st/conf.json=release")
        self.assertEqual(rc, 0, out)
        self.assertEqual(rep["mode"], "dry-run")
        self.assertIsNone(self.read("st/added.json"))
        self.assertFalse(os.path.exists(os.path.join(self.new, "workspaces")))
        self.assertIn("cloud_migrate_paths.py --old-root %s --apply" % self.old, out)

    def test_apply_with_resolve(self):
        rc, rep, out = self.carry("--apply", "--resolve", "st/conf.json=closed")
        self.assertEqual(rc, 0, out)
        self.assertEqual(rep["mode"], "apply")
        self.assertEqual(self.read("st/keep.json"), self.Y)       # KEEP_CLOSED: 폐쇄망 사본
        self.assertEqual(self.read("st/take.json"), self.Z)       # TAKE_RELEASE
        self.assertEqual(self.read("st/conf.json"), self.Y)       # CONFLICT → closed
        self.assertEqual(self.read("st/added.json"), self.Y)      # ADDED_CLOSED
        self.assertEqual(self.read("st/flag.json"), self.Z)       # FLAG: 손대지 않음
        self.assertIsNone(self.read("st/deldel.json"))            # 폐쇄망 삭제 유지
        self.assertIsNone(self.read("st/reldel.json"))            # FLAG_RELEASE_DELETED: 복사 안 함
        self.assertEqual(self.read("workspaces/_site/beol.env"), "TZ=Asia/Seoul\n")
        self.assertTrue(os.path.isfile(os.path.join(self.new, "workspaces", "ws1", "work.sqlite")))
        untracked = [r for r in rep["rows"] if r["decision"] == "COPIED_UNTRACKED"]
        self.assertEqual([(r["glob"], r["files"]) for r in untracked], [("workspaces/", 2), ("workspaces/_site/", 0)])

    def test_apply_refused_while_conflict(self):
        rc, rep, _ = self.carry("--apply")
        self.assertEqual(rc, 1)
        self.assertEqual(rep["mode"], "dry-run")
        self.assertIsNone(self.read("st/added.json"))

    def test_taxonomy_row_level_conflict(self):
        doc = json.loads(json.dumps(self.TAX_BASE))
        closed = json.loads(json.dumps(doc))
        closed["taxonomy"].append({"축": "공정", "값": "cmp", "상위값": ""})
        release = json.loads(json.dumps(doc))
        release["taxonomy"][0]["다중값"] = "Y"
        release["synonyms"].append({"동의어": "식각", "표준어": "etch"})
        write(self.old, "taxonomy/taxonomy.json", json.dumps(closed, ensure_ascii=False))
        write(self.new, "taxonomy/taxonomy.json", json.dumps(release, ensure_ascii=False))
        rc, rep, out = self.carry("--resolve", "st/conf.json=release")
        self.assertEqual(rc, 1, out)
        row = [r for r in rep["rows"] if r.get("path") == "taxonomy/taxonomy.json"][0]
        self.assertEqual(row["decision"], "CONFLICT")
        ops = sorted((c["op"], c["key"]) for c in row["diff"]["changes"])
        self.assertEqual(ops, [("added", "taxonomy[공정|etch|].다중값"), ("row_added", "synonyms[식각]"),
                               ("row_removed", "taxonomy[공정|cmp|]")])

    def test_text_conflict_line_ranges(self):
        write(self.old, "st/conf.json", "line1\nclosed\nline3\n")  # JSON이 아니면 줄 범위로
        rc, rep, _ = self.carry()
        row = [r for r in rep["rows"] if r.get("path") == "st/conf.json"][0]
        self.assertEqual(row["diff"]["kind"], "lines")
        self.assertTrue(row["diff"]["changes"])

    def test_no_base_manifest(self):
        os.remove(os.path.join(self.old, "transfer", "import_manifest.json"))
        rc, rep, out = self.carry()
        self.assertEqual(rc, 1)
        self.assertIsNone(rep)
        self.assertIn("[M19 IMPORT] 실패  사유=NO_BASE_MANIFEST", out)

    def test_bad_resolve(self):
        rc, _, out = self.carry("--resolve", "st/conf.json=mine")
        self.assertEqual(rc, 1)
        self.assertIn("RESOLVE_INVALID", out)


class StepHelperTest(unittest.TestCase):
    """CLOUD_SETUP.md 맨 위 step 도우미: 시작·완료·실패 rc·마지막 20줄·doctor 안내·값 가림·실패 뒤 다음 단계 막힘."""

    def test_step_helper(self):
        with open(os.path.join(ROOT, "CLOUD_SETUP.md"), encoding="utf-8") as f:
            md = f.read()
        block = md[md.index("# >>> step 도우미"):md.index("# <<< step 도우미")]
        secret = "stepsecret" + "9" * 8
        script = block + "\n".join([
            "step E01 'ok' -- sh -c 'echo token=$MY_API_KEY; echo hello'; echo rc1=$?",
            "step E06 'bad' -- sh -c 'for i in $(seq 1 30); do echo line$i; done; exit 3'; echo rc2=$?",
            "step E08 'next' -- echo should-not-run; echo rc3=$?",
            "step E06 'retry' -- true; echo rc4=$?",
            "step E08 'next' -- echo now-runs; echo rc5=$?", ""])
        tmp = tempfile.mkdtemp(prefix="l5s_")
        try:
            with open(os.path.join(tmp, "run.sh"), "w", encoding="utf-8", newline="\n") as f:
                f.write(script)
            p = subprocess.run(["bash", "run.sh"], cwd=tmp, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               env=dict(os.environ, MY_API_KEY=secret, PYTHONIOENCODING="utf-8"))
            out = p.stdout.decode("utf-8", "replace")
            logs = [n for n in os.listdir(os.path.join(tmp, "workspaces", "_site")) if n.startswith("setup_")]
            with open(os.path.join(tmp, "workspaces", "_site", logs[0]), encoding="utf-8") as f:
                log = f.read()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        for want in ("[M00 ENV/E01] 시작", "[M00 ENV/E01] 완료", "rc1=0", "[M00 ENV/E06] 실패 rc=3", "rc2=3",
                     "python3 tools/beol_doctor.py --step E06", "[M00 ENV/E08] 건너뜀", "rc3=1", "rc4=0", "now-runs", "rc5=0"):
            self.assertIn(want, out)
        self.assertNotIn("should-not-run", out)
        tail = out[out.index("마지막 20줄"):]
        self.assertIn("line11", tail)
        self.assertNotIn("line10\n", tail)
        self.assertNotIn(secret, out + log)
        self.assertIn("token=***", log)


# Python 3.8에 있는 표준 라이브러리 중 두 도구가 쓸 수 있는 것(+ 실패 출력기용 labelbot.trace)
PY38_ALLOWED = {"argparse", "difflib", "fnmatch", "hashlib", "json", "os", "shutil", "sys", "time", "unicodedata", "labelbot"}


class Py38Test(unittest.TestCase):
    def check(self, path):
        with open(path, encoding="utf-8") as f:
            src = f.read()
        tree = ast.parse(src, feature_version=(3, 8))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [(node.module or "").split(".")[0]]
            else:
                continue
            for n in names:
                self.assertIn(n, PY38_ALLOWED, "%s: %s" % (os.path.basename(path), n))
        attrs = set(n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute))
        self.assertFalse(attrs & {"removeprefix", "removesuffix"})  # 3.9+ 메서드

    def test_verify_import_py38(self):
        self.check(VERIFY)

    def test_carry_state_py38(self):
        self.check(CARRY)

    def test_fallback_printer_format(self):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            vi.fail_block("X_CODE", "원인 문장", "조치 문장")
        lines = buf.getvalue().splitlines()
        self.assertEqual(lines[0], "[M19 IMPORT] 실패  사유=X_CODE")
        self.assertEqual(lines[1:3], ["  원인: 원인 문장", "  조치: 조치 문장"])


if __name__ == "__main__":
    unittest.main()
