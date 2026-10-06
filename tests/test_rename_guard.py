"""2026-10-06 봇 이름 변경(Engr-bot → Domain-Engr-bot, code-bot → Code-Engr-bot) 뒤 옛 이름이 다시 들어오지 않게 막는다.

살아 있는 소스만 본다. 이력 문서(머리말에 "2026-10-06 이름 변경"이 있는 파일)와 아래 허용 줄은 뺀다.
"""
import os
import re
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCAN = ["labelbot", "domain_engrbot", "code_engrbot", "tests", ".claude/skills", "change-dashboard", "docs",
        "README.md", "PRD.md", "plan.md", "CLAUDE.md"]
SKIP_DIRS = {"__pycache__", ".omc", "out", "data", "reports", "golden_outputs"}
SKIP_FILES = {"change-dashboard/index.html", "tests/test_rename_guard.py"}
EXTS = {".py", ".md", ".html", ".json", ".jsonl"}
A = "A-Za-z0-9"
OLD = [
    re.compile(r"(?<![%s])(?<!domain_)(?<!code_)engrbot(?![%s])(?!_questions_)(?!_review_)" % (A, A)),
    re.compile(r"(?<![%s])codebot(?![%s])" % (A, A)),
    re.compile(r"(?<![A-Za-z-])Engr-[Bb]ot"),
    re.compile(r"(?<![A-Za-z-])[Cc]ode-[Bb]ot"),
    # JSON 문자열 속 줄바꿈(\n) 바로 뒤는 앞 글자가 n이라 위 규칙에 걸리지 않으므로 따로 본다.
    re.compile(r"(?<=\\n)(?:Engr-[Bb]ot|[Cc]ode-[Bb]ot)"),
]
# 이력 문서는 맨 앞에 rename_apply.py가 붙인 머리말로만 가린다(본문에 같은 말이 있는 코드는 계속 검사한다).
HISTORY_BANNER = re.compile(r"\A(?:---\n.*?\n---\n\s*)?> 2026-10-06 이름 변경:", re.S)
DOUBLE = re.compile(r"Domain-Domain|Code-Domain|Code-Code|domain_domain|code_code|code_domain")
# 옛 이름을 일부러 남긴 줄: 지난 기록과 맞추는 역할 키, 옛 이름 트리거 별칭, 옛 경로·마커 호환.
ALLOW_LINE = re.compile(
    r'"Engr-bot"|"code-bot"|`Engr-bot`|`code-bot`|\(옛 이름\)|이전 이름|이전 경로|이름 변경 전|'
    r'labeling-codebot|LEGACY_DIRNAME = "_engrbot"|'
    r'\(\?:code_engrbot\|codebot\)|\("domain_engrbot", "engrbot"\)|\("code_engrbot", "codebot"\)')


def living_files():
    for top in SCAN:
        p = os.path.join(ROOT, top)
        if os.path.isfile(p):
            yield top
            continue
        for dirpath, dirnames, filenames in os.walk(p):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                rel = os.path.relpath(os.path.join(dirpath, fn), ROOT).replace("\\", "/")
                if os.path.splitext(fn)[1] in EXTS and rel not in SKIP_FILES:
                    yield rel


class RenameGuardTest(unittest.TestCase):
    def test_no_old_names_in_living_sources(self):
        hits = []
        for rel in living_files():
            with open(os.path.join(ROOT, rel), encoding="utf-8", errors="replace") as f:
                text = f.read()
            if HISTORY_BANNER.match(text):
                continue  # 이력 문서
            for n, line in enumerate(text.splitlines(), 1):
                if ALLOW_LINE.search(line):
                    continue
                if any(rx.search(line) for rx in OLD):
                    hits.append("%s:%d" % (rel, n))
        self.assertEqual(hits, [])

    def test_no_double_rename(self):
        hits = []
        for rel in living_files():
            with open(os.path.join(ROOT, rel), encoding="utf-8", errors="replace") as f:
                if DOUBLE.search(f.read()):
                    hits.append(rel)
        self.assertEqual(hits, [])

    def test_old_paths_gone(self):
        for p in ("engrbot", "codebot", ".claude/skills/BEOL-labeling-Engr-bot", ".claude/skills/BEOL-labeling-code-bot"):
            self.assertFalse(os.path.exists(os.path.join(ROOT, p)), p)


class LegacyDataDirTest(unittest.TestCase):
    def test_ledger_dir_stops_on_legacy_folder(self):
        from domain_engrbot import ledger, paths
        with tempfile.TemporaryDirectory() as root:
            ws = os.path.join(root, "WS1")
            os.makedirs(ws)
            orig = ledger.WORKSPACES_DIR
            ledger.WORKSPACES_DIR = root
            self.addCleanup(setattr, ledger, "WORKSPACES_DIR", orig)
            self.assertEqual(ledger.ledger_dir(ws, {}), paths.data_path(root, "ledger"))
            os.makedirs(os.path.join(root, paths.LEGACY_DIRNAME))
            with self.assertRaises(ledger.LedgerError) as cm:
                ledger.ledger_dir(ws, {})
            self.assertIn("LEGACY_DATA_DIR", str(cm.exception))

    def test_board_and_summary_do_not_fall_back_silently(self):
        from domain_engrbot import ledger, paths, taxonomy_board, workspaces
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, paths.LEGACY_DIRNAME))
            orig = ledger.WORKSPACES_DIR
            ledger.WORKSPACES_DIR = root
            self.addCleanup(setattr, ledger, "WORKSPACES_DIR", orig)
            with self.assertRaises(ledger.LedgerError):
                taxonomy_board._ledger_dir([])
            self.assertEqual(workspaces.questions_summary(root).get("reason"), "LEGACY_DATA_DIR")


if __name__ == "__main__":
    unittest.main()
