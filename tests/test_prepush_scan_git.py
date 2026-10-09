"""tools/prepush_scan.py: 지금 저장소(추적 파일 전체)는 허용 목록으로 통과한다(git ls-files — git 체크아웃 필요).

폐쇄망 반입본(GitHub ZIP)에는 .git이 없으므로 manifest test_modules에서 뺀다(CLOSED_NETWORK_EXCLUDE).
"""
import os
import subprocess
import sys
import unittest

CLOSED_NETWORK_EXCLUDE = "git 체크아웃(.git) 필요 — 반입 ZIP에는 .git이 없다"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN = os.path.join(ROOT, "tools", "prepush_scan.py")


class CurrentTreeTest(unittest.TestCase):
    def test_current_tree_passes(self):
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        p = subprocess.run([sys.executable, SCAN], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        out = p.stdout.decode("utf-8", "replace") + p.stderr.decode("utf-8", "replace")
        self.assertEqual(p.returncode, 0, out)
        self.assertIn("hits=0", out)


if __name__ == "__main__":
    unittest.main()
