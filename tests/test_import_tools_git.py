"""make_import_manifest의 실제 저장소 dummy import 그래프(git blob을 읽는다 — git 체크아웃 필요).

폐쇄망 반입본(GitHub ZIP)에는 .git이 없으므로 manifest test_modules에서 뺀다(CLOSED_NETWORK_EXCLUDE).
"""
import importlib.util
import os
import unittest

CLOSED_NETWORK_EXCLUDE = "git 체크아웃(.git) 필요 — 반입 ZIP에는 .git이 없다"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAKE = os.path.join(ROOT, "tools", "make_import_manifest.py")


def _load():
    spec = importlib.util.spec_from_file_location("make_import_manifest_git", MAKE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class RealRepoGraphTest(unittest.TestCase):
    def test_real_repo_dummy_graph(self):
        mim = _load()
        blobs = mim.read_blobs(ROOT, "HEAD")
        tests, excluded = mim.compute_test_modules(blobs)
        self.assertIn("tests/test_pipeline.py", excluded)
        self.assertIn("tests/test_rules_board.py", excluded)  # test_rules_update → test_pipeline 경유
        self.assertIn("tests/test_taxonomy.py", tests)
        self.assertFalse(set(tests) & set(excluded))
        reasons = dict((r["path"], r["excluded_reason"]) for r in mim.excluded_reasons(blobs, excluded))
        self.assertEqual(reasons["tests/test_pipeline.py"], mim.DUMMY_REASON)


if __name__ == "__main__":
    unittest.main()
