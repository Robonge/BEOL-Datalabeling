"""리눅스 클라우드(cdep-ver) 호환 검사. git 없이 돈다(반입 ZIP에도 .git이 없다) — 저장소 폴더를 직접 훑는다.

- 정적 검사: .py·.sh에 Windows 전용 구문(winreg·msvcrt·windll·os.startfile·cmd /c·powershell·shell=True·mbcs·
  드라이브 문자 경로·.exe·subprocess에 "python" 문자열)이 허용 목록(경로·구문·이유) 밖에 없다.
- .sh: LF, bash shebang, `bash -n` 통과. tools/cloud_setup.sh의 step 도우미 = CLOUD_SETUP.md 0절(바이트 단위).
- POSIX 경로: cloud_migrate_paths·init_workspace.stored_path를 posixpath로 돌려 상대경로가 맞는지.
- site_init: 없는 파일만 만들고 다시 돌려도 바꾸지 않는다. 예시는 placeholder만.
- crontab.example·launch.json·추적 문서: 절대 Windows 경로가 없다. 문서·스크립트의 인라인 python open(…json…)은 encoding='utf-8'.
- cdp: 리눅스 전용 headless 플래그는 리눅스에서만, BEOL_CHROME 후보.
"""
import importlib.util
import json
import os
import posixpath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SELF = "tests/test_linux_compat.py"
SKIP_DIRS = {".git", ".omc", "docs", "workspaces", "__pycache__", "node_modules", ".superdesign"}
SETUP_SH = os.path.join(ROOT, "tools", "cloud_setup.sh")
HELPER_START, HELPER_END = "# >>> step 도우미", "# <<< step 도우미"


def _load(rel, name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, *rel.split("/")))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _files(exts):
    out = []
    for base, dirs, files in os.walk(ROOT):
        rel_base = os.path.relpath(base, ROOT).replace(os.sep, "/")
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not (rel_base == "change-dashboard" and d in ("data", "reports"))]
        for fn in files:
            if fn.endswith(exts):
                rel = os.path.relpath(os.path.join(base, fn), ROOT).replace(os.sep, "/")
                out.append(rel)
    return sorted(out)


def _read(rel):
    with open(os.path.join(ROOT, *rel.split("/")), encoding="utf-8", errors="replace") as f:
        return f.read()


# 금지 구문(ID, 정규식)
FORBIDDEN = (
    ("winreg", re.compile(r"\bwinreg\b")),
    ("msvcrt", re.compile(r"\bmsvcrt\b")),
    ("windll", re.compile(r"\bwindll\b")),
    ("startfile", re.compile(r"os\.startfile")),
    ("cmd_c", re.compile(r"\bcmd(?:\.exe)?\s+/c\b", re.I)),
    ("powershell", re.compile(r"\bpowershell\b", re.I)),
    ("shell_true", re.compile(r"shell\s*=\s*True")),
    ("mbcs", re.compile(r"[\"']mbcs[\"']")),
    ("exe", re.compile(r"\.exe\b")),
    ("drive_path", re.compile(r"[\"'][A-Za-z]:(?:\\|/)")),  # 드라이브 문자로 시작하는 문자열 리터럴
    ("python_literal_argv", re.compile(r"\[\s*[\"']python3?[\"']\s*,")),
)
# (경로, 구문 ID, 이유) — 작게 유지한다. 새 항목은 이유와 함께만.
ALLOW = (
    (".claude/skills/BEOL-labeling-feedback/scripts/collect_inbox.py", "winreg",
     "try 안 import — 리눅스는 ImportError로 ~/Downloads를 쓴다"),
    ("labelbot/cdp.py", "exe", "Windows 후보(ProgramFiles 아래 Edge·Chrome) — 리눅스는 env가 없어 건너뛴다"),
    ("tools/beol_doctor.py", "exe", "Windows 후보(ProgramFiles 아래 Edge·Chrome) — 리눅스는 env가 없어 건너뛴다"),
    ("tests/test_slides.py", "exe", "가짜 브라우저 파일 이름(존재 여부만 본다)"),
    ("tests/contracts/_support.py", "exe", "python.exe 꼴도 python으로 읽는 정규식"),
    ("domain_engrbot/tests/test_golden_outputs.py", "drive_path", "Windows 경로 정규화 시험 입력"),
    ("tests/test_cloud_migrate_paths.py", "drive_path", "Windows 옛 루트 변환 시험 입력(X:/·Y:/)"),
    ("tests/test_prepush_scan.py", "drive_path", "사용자 경로 탐지 시험 입력"),
    ("code_engrbot/rules/c2_stack.py", "shell_true", "검수 규칙 자신(금지 패턴 문자열)"),
    ("change-dashboard/collect.py", "powershell", "세션 기록의 도구 이름 문자열(실행하지 않음, Claude 전용 도구)"),
)
# Windows 사용자 폴더 꼴이 남아도 되는 줄(자리표시·시험 입력만)
USER_PATH_ALLOW = (("CLOSED_NETWORK_RUNBOOK.md", "<업무 PC 사용자>"), ("tests/test_prepush_scan.py", "someone"))


class StaticScanTest(unittest.TestCase):
    def test_no_windows_only_constructs(self):
        allowed = set((p, c) for p, c, _ in ALLOW)
        hits = []
        for rel in _files((".py", ".sh")):
            if rel == SELF:
                continue
            text = _read(rel)
            for cid, rx in FORBIDDEN:
                if rx.search(text) and (rel, cid) not in allowed:
                    line = text[:rx.search(text).start()].count("\n") + 1
                    hits.append("%s:%d %s" % (rel, line, cid))
        self.assertEqual([], hits, "Windows 전용 구문(고치거나 ALLOW에 이유와 함께 넣는다)")

    def test_allowlist_entries_still_needed(self):
        rx = dict(FORBIDDEN)
        for path, cid, reason in ALLOW:
            with self.subTest(path=path, construct=cid):
                self.assertTrue(reason)
                full = os.path.join(ROOT, *path.split("/"))
                if os.path.isfile(full):
                    self.assertTrue(rx[cid].search(_read(path)), "허용 목록 항목이 더는 필요 없다 — 지운다")

    def test_no_windows_user_paths_outside_docs(self):
        hits = []
        rx = re.compile(r"[A-Za-z]:[\\/]+Users[\\/]", re.I)
        for rel in _files((".py", ".sh", ".md", ".json", ".jsonl", ".html", ".js", ".css", ".txt", ".example", ".toml")):
            if rel == SELF:
                continue
            for n, line in enumerate(_read(rel).splitlines(), 1):
                if rx.search(line) and not any(rel == p and mark in line for p, mark in USER_PATH_ALLOW):
                    hits.append("%s:%d" % (rel, n))
        self.assertEqual([], hits)

    def test_shell_scripts_lf_and_shebang(self):
        for rel in _files((".sh",)):
            with self.subTest(script=rel):
                with open(os.path.join(ROOT, *rel.split("/")), "rb") as f:
                    data = f.read()
                self.assertNotIn(b"\r\n", data)
                self.assertTrue(data.startswith(b"#!/usr/bin/env bash\n") or data.startswith(b"#!/bin/bash\n"))
                if os.name == "posix":
                    self.assertTrue(os.stat(os.path.join(ROOT, *rel.split("/"))).st_mode & stat.S_IXUSR, "exec 비트")

    def test_inline_python_open_json_has_encoding(self):
        """문서·Roo skill·셸 스크립트의 인라인 python에서 .json(또는 os-release)을 텍스트로 여는 open(…)은 encoding='utf-8'."""
        rels = [r for r in _files((".md",)) if "/" not in r or r.startswith(".roo/")] + _files((".sh",))
        bad = []
        for rel in rels:
            for n, line in enumerate(_read(rel).splitlines(), 1):
                for m in re.finditer(r"\bopen\(", line):
                    depth, i = 1, m.end()
                    while i < len(line) and depth:
                        depth += {"(": 1, ")": -1}.get(line[i], 0)
                        i += 1
                    args = line[m.end():i - 1]
                    if (".json" in args or "os-release" in args) and not re.search(r"[\"']r?[wa]?b[\"']", args) \
                            and "encoding=" not in args:
                        bad.append("%s:%d" % (rel, n))
        self.assertEqual([], bad)


class SetupScriptTest(unittest.TestCase):
    def test_step_helper_identical_to_doc(self):
        def block(text):
            return text[text.index(HELPER_START):text.index(HELPER_END) + len(HELPER_END)]
        self.assertEqual(block(_read("CLOUD_SETUP.md")).encode("utf-8"), block(_read("tools/cloud_setup.sh")).encode("utf-8"))

    def test_bash_syntax_and_dry_run(self):
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("bash 없음")
        p = subprocess.run([bash, "-n", SETUP_SH], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual(p.returncode, 0, p.stdout.decode("utf-8", "replace"))
        p = subprocess.run([bash, SETUP_SH, "--dry-run"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=ROOT)
        out = p.stdout.decode("utf-8", "replace")
        self.assertEqual(p.returncode, 0, out)
        ids = re.findall(r"^\s+(\S+)\s", out, re.M)
        self.assertEqual(ids, ["S01", "E00", "E08", "E11", "E09", "E13", "S02", "S03", "C3"])
        p = subprocess.run([bash, SETUP_SH, "--dry-run", "--from", "S02"], stdout=subprocess.PIPE, cwd=ROOT)
        self.assertEqual(re.findall(r"^\s+(\S+)\s", p.stdout.decode("utf-8", "replace"), re.M), ["S02", "S03", "C3"])
        p = subprocess.run([bash, SETUP_SH, "--only", "NOPE"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=ROOT)
        self.assertEqual(p.returncode, 2)
        self.assertIn("STEP_UNKNOWN", p.stdout.decode("utf-8", "replace"))

    def test_script_installs_nothing(self):
        text = _read("tools/cloud_setup.sh")
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("echo") or s.startswith("#") or s.startswith("build:") or s.startswith("chrome:"):
                continue
            self.assertNotRegex(s, r"\b(sudo|apt-get|dnf|yum|pip install)\b", s)


class PosixPathTest(unittest.TestCase):
    """Windows에서도 posixpath로 리눅스 경로 계산을 재현한다."""
    REPO = "/config/work/beol/r2"

    def test_cloud_migrate_paths_posix(self):
        cmp = _load("tools/cloud_migrate_paths.py", "_cmp_posix")
        fake_os = types.SimpleNamespace(path=posixpath, sep="/")
        with mock.patch.object(cmp, "os", fake_os):
            code, suffix = cmp.classify("X:\\old\\repo\\parshing test files", ["X:/old/repo"])
            self.assertEqual((code, suffix), ("CONVERT", "parshing test files"))
            self.assertEqual(cmp.classify("/config/work/beol/r1/taxonomy/taxonomy.json", ["/config/work/beol/r1"]),
                             ("CONVERT", "taxonomy/taxonomy.json"))
            self.assertEqual(cmp.classify("../../taxonomy/taxonomy.json", ["/config/work/beol/r1"])[0], "ALREADY_OK")
            self.assertEqual(cmp.classify("/srv/other/docs", ["/config/work/beol/r1"])[0], "OUTSIDE_REPO")
            ws = self.REPO + "/workspaces/261004_BEOL_x_20261010-000000"
            self.assertEqual(cmp._target("parshing test files", ws, self.REPO, None), "../../parshing test files")
            changes, reasons = cmp._plan_file(
                "ingested_list", self.REPO + "/injested-file-list/261004_BEOL_x_20261010-000000.json",
                {"workspace": "X:/old/repo/workspaces/261004_BEOL_x_20261010-000000", "input": "X:/old/repo/parshing test files"},
                ["X:/old/repo"], self.REPO, None)
            self.assertEqual(changes, {"workspace": "workspaces/261004_BEOL_x_20261010-000000",
                                       "input": "../../parshing test files"})
            self.assertEqual(reasons, [("workspace", "CONVERTED"), ("input", "CONVERTED")])

    def test_init_workspace_stored_path_posix(self):
        iw = _load(".claude/skills/BEOL-labeling/scripts/init_workspace.py", "_iw_posix")
        fake_os = types.SimpleNamespace(path=posixpath, sep="/")
        ws = self.REPO + "/workspaces/261004_BEOL_x_20261010-000000"
        with mock.patch.object(iw, "os", fake_os), mock.patch.object(iw, "CODE_ROOT", self.REPO), \
                mock.patch.object(posixpath, "realpath", lambda p, **kw: posixpath.normpath(p)):
            self.assertEqual(iw.stored_path(self.REPO + "/taxonomy/taxonomy.json", ws), ("../../taxonomy/taxonomy.json", None))
            self.assertEqual(iw.stored_path(self.REPO + "/parshing test files", ws), ("../../parshing test files", None))
            self.assertEqual(iw.stored_path("/srv/docs", ws), ("/srv/docs", "OUTSIDE_REPO"))


class SiteInitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="site_init_")
        self.si = _load("tools/site_init.py", "_site_init_t")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_creates_missing_only_and_is_idempotent(self):
        site = os.path.join(self.tmp, "_site")
        created, kept = self.si.init_site(ROOT, site)
        names = [dst for _, dst, _ in self.si.FILES]
        self.assertEqual((created, kept), (names, []))
        with open(os.path.join(site, "beol.env"), "a", encoding="utf-8") as f:
            f.write("export BEOL_LLM_API_KEY=local-edit\n")  # 사용자가 채운 값
        before = {n: open(os.path.join(site, n), "rb").read() for n in names}
        created, kept = self.si.init_site(ROOT, site)
        self.assertEqual((created, kept), ([], names))
        self.assertEqual(before, {n: open(os.path.join(site, n), "rb").read() for n in names})
        if os.name == "posix":
            for src, dst, secret in self.si.FILES:
                if secret:
                    self.assertEqual(stat.S_IMODE(os.stat(os.path.join(site, dst)).st_mode), 0o600, dst)

    def test_missing_templates(self):
        self.assertIsNone(self.si.init_site(self.tmp, os.path.join(self.tmp, "_site")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "_site")))

    def test_registered_m00(self):
        from labelbot import milestones
        self.assertEqual(milestones.ENTRYPOINTS["tools/site_init.py"], ("M00",))


class SiteTemplatesTest(unittest.TestCase):
    TDIR = "config/site.example"

    def test_doctor_targets_copy_identical(self):
        self.assertEqual(_read("config/doctor_targets.example.json"), _read(self.TDIR + "/doctor_targets.example.json"))

    def test_json_templates_parse(self):
        for name in ("profile.example.json", "doctor_targets.example.json", "scan_denylist.example.json"):
            with self.subTest(name=name):
                json.loads(_read(self.TDIR + "/" + name))

    def test_env_template_has_no_values_for_secrets(self):
        names = set()
        for line in _read(self.TDIR + "/beol.env.example").splitlines():
            m = re.match(r"^export ([A-Z_]+)=(.*)$", line)
            if not m:
                continue
            names.add(m.group(1))
            if re.search("KEY|SECRET|TOKEN|PASSWORD", m.group(1)):
                self.assertEqual(m.group(2), "", m.group(1))
        for need in ("BEOL_ALLOWED_HOSTS", "BEOL_PATH_PREFIX", "BEOL_NO_BROWSER", "BEOL_ALLOWED_HOST_SUFFIXES", "TZ",
                     "PYTHONIOENCODING", "BEOL_LLM_API_KEY", "BEOL_EMBED_API_KEY", "BEOL_CHROME"):
            self.assertIn(need, names)

    def test_crontab_uses_relative_or_env_paths(self):
        text = _read(self.TDIR + "/crontab.example")
        jobs = [l for l in text.splitlines() if l.strip() and not l.startswith("#") and not re.match(r"^[A-Z_]+=", l)]
        self.assertEqual(2, len(jobs))
        for job in jobs:
            with self.subTest(job=job):
                cmd = job.split(None, 5)[5]
                self.assertIn('cd "$B"', cmd)
                self.assertIn("workspaces/_site/beol.env", cmd)
                self.assertIn(">> workspaces/_nightly/cron.log 2>&1", cmd)
                for tok in re.findall(r"[^\s;&|<>\"']+", cmd):
                    self.assertFalse(tok.startswith("/") or re.match(r"^[A-Za-z]:", tok), tok)
        self.assertIn("TZ=Asia/Seoul", text)
        self.assertNotRegex(text, r"[A-Za-z]:[\\/]")

    def test_launch_json_has_no_absolute_paths(self):
        with open(os.path.join(ROOT, ".claude", "launch.json"), encoding="utf-8") as f:
            doc = json.load(f)
        for conf in doc["configurations"]:
            for arg in conf.get("runtimeArgs", []):
                with self.subTest(name=conf["name"], arg=arg):
                    self.assertNotRegex(arg, r"^(?:[A-Za-z]:|/)")


class CdpLinuxTest(unittest.TestCase):
    def setUp(self):
        from labelbot import cdp
        self.cdp = cdp

    def test_flags_only_on_linux(self):
        big = 2 * 1024 ** 3
        with mock.patch.dict(os.environ, {"BEOL_CHROME_NO_SANDBOX": "", "BEOL_CHROME_DISABLE_DEV_SHM": ""}):
            self.assertEqual(self.cdp.linux_flags("win32", euid=0, shm_bytes=0), [])
            self.assertEqual(self.cdp.linux_flags("darwin", euid=0, shm_bytes=0), [])
            self.assertEqual(self.cdp.linux_flags("linux", euid=1000, shm_bytes=big), [])
            self.assertEqual(self.cdp.linux_flags("linux", euid=0, shm_bytes=big), ["--no-sandbox"])
            self.assertEqual(self.cdp.linux_flags("linux", euid=1000, shm_bytes=64 * 1024 ** 2), ["--disable-dev-shm-usage"])
        with mock.patch.dict(os.environ, {"BEOL_CHROME_NO_SANDBOX": "1", "BEOL_CHROME_DISABLE_DEV_SHM": "1"}):
            self.assertEqual(self.cdp.linux_flags("linux", euid=1000, shm_bytes=big),
                             ["--no-sandbox", "--disable-dev-shm-usage"])

    def test_beol_chrome_env_first(self):
        tmp = tempfile.mkdtemp(prefix="cft_")
        try:
            with mock.patch.dict(os.environ, {"BEOL_CHROME": tmp}):
                c = self.cdp.browser_candidates()
            self.assertEqual(c[:2], [os.path.join(tmp, "chrome-linux64", "chrome"), os.path.join(tmp, "chrome")])
            exe = os.path.join(tmp, "my-chrome")
            with mock.patch.dict(os.environ, {"BEOL_CHROME": exe}):
                self.assertEqual(self.cdp.browser_candidates()[0], exe)
            with mock.patch.dict(os.environ, {"BEOL_CHROME": ""}):
                c = self.cdp.browser_candidates()
            self.assertNotIn(tmp, " ".join(c))
            if sys.platform == "win32":  # Windows 후보 순서는 그대로(Edge가 먼저)
                self.assertTrue(c[0].endswith("msedge.exe"))
            if sys.platform.startswith("linux"):
                self.assertIn("/usr/bin/chromium-browser", c)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
