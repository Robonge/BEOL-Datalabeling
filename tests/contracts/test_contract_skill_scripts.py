"""스킬 스크립트(.claude/skills/*/scripts/*.py)의 --help 동결.

argparse를 import하는 스크립트만 `--help`로 실행한다(파싱 단계에서 끝나므로 부수 효과가 없다).
argparse가 없는 스크립트는 실행하지 않고 skipped로 기록한다.
"""
import ast
import glob
import os
import unittest

from tests.contracts import _support

SKILLS_GLOB = os.path.join(_support.REPO_ROOT, ".claude", "skills", "*", "scripts", "*.py")


def _uses_argparse(path):
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(a.name == "argparse" for a in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and node.module == "argparse":
            return True
    return False


class SkillScriptsHelpContract(unittest.TestCase):
    def test_skill_scripts_help(self):
        data = {}
        for path in sorted(glob.glob(SKILLS_GLOB)):
            rel = os.path.relpath(path, _support.REPO_ROOT).replace("\\", "/")
            if not _uses_argparse(path):
                data[rel] = {"status": "skipped", "reason": "NO_ARGPARSE"}
                continue
            rc, stdout, stderr = _support.run_help([path, "--help"])
            with self.subTest(script=rel):
                self.assertEqual(0, rc, stderr[-500:])
            data[rel] = {"status": "ok", "help": stdout}
        self.assertTrue(data, "스킬 스크립트를 찾지 못했다")
        _support.check(self, "skill_scripts_help", data)


if __name__ == "__main__":
    unittest.main()
