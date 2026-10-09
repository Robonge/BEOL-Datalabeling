"""selfcheck의 TAXONOMY_XLSX_NEWER 경고: 새 checkout·ZIP 해제로 xlsx가 json보다 몇 ms 늦게 써진 경우는 경고하지 않는다(2초 여유)."""
import os
import shutil
import tempfile
import time
import unittest

from labelbot import selfcheck
from labelbot.workspace import Workspace
from tests.test_taxonomy import base_sheets, build


class XlsxNewerToleranceTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="labelbot_selfcheck_")
        self.ws = Workspace(self.dir)
        with open(self.ws.taxonomy_path, "wb") as f:
            f.write(build(base_sheets()))
        self.legacy = os.path.splitext(self.ws.taxonomy_path)[0] + ".xlsx"
        with open(self.legacy, "wb"):
            pass  # 존재·mtime만 본다(내용 없음)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def detail(self, xlsx_offset_s):
        base = time.time() - 100
        os.utime(self.ws.taxonomy_path, (base, base))
        os.utime(self.legacy, (base + xlsx_offset_s, base + xlsx_offset_s))
        got = []
        selfcheck._check_taxonomy(self.ws, lambda name, ok, detail="": got.append((name, ok, detail)))
        return next(d for n, ok, d in got if n == "taxonomy.json")

    def test_xlsx_written_just_after_json_is_not_warned(self):
        self.assertNotIn("TAXONOMY_XLSX_NEWER", self.detail(0.05))
        self.assertNotIn("TAXONOMY_XLSX_NEWER", self.detail(1.9))

    def test_xlsx_clearly_newer_is_warned_with_same_text(self):
        d = self.detail(5)
        self.assertIn("WARN TAXONOMY_XLSX_NEWER: 예전 taxonomy.xlsx가 더 최근에 저장됐다(편집은 보드·편집기로)", d)


if __name__ == "__main__":
    unittest.main()
