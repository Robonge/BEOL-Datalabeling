"""sqlite 스키마 동결: 작업 DB(work.sqlite)와 산출 DB(out/labeling.sqlite).

- work.sqlite: 임시 Workspace에 store.connect로 만든 빈 DB의 sqlite_master와 meta.
- labeling.sqlite: 빈 작업 DB와 빈 분류 체계로 export.export를 실제로 돌려 만든 DB의 sqlite_master, meta 키, SCHEMA.md.
실제 사내 파일·데이터는 쓰지 않는다. 임시 폴더는 tempfile 아래에 두고 지운다.
"""
import os
import sqlite3
import tempfile
import types
import unittest

from engrbot.adapters import labelbot_ws
from labelbot import export, store
from labelbot.workspace import Workspace

from tests.contracts import _support


def _master(con):
    return [list(r) for r in con.execute("SELECT type, name, sql FROM sqlite_master ORDER BY type, name")]


def _empty_tax():
    return types.SimpleNamespace(files=[], axes=[], synonyms=[], questions=[], sheet_hashes={})


class SchemaContract(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="contract_ws_", ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.ws = Workspace(os.path.join(self._tmp.name, "ws"))

    def _work_con(self):
        con = store.connect(self.ws.work_db)
        self.addCleanup(con.close)
        return con

    def test_work_sqlite_schema(self):
        con = self._work_con()
        data = {
            "sqlite_master": _master(con),
            "meta": [list(r) for r in con.execute("SELECT key, value FROM meta ORDER BY key")],
            "workspace_entries": sorted(os.listdir(self.ws.root)),
        }
        _support.check(self, "schema_work_sqlite", data)

    def test_work_sqlite_has_engrbot_required_columns(self):
        """engrbot 어댑터가 읽기 전용으로 기대하는 표·열(labelbot_ws.REQUIRED)이 실제 work.sqlite에 있다."""
        con = self._work_con()
        missing = []
        for table, cols in labelbot_ws.REQUIRED.items():
            have = {r[1] for r in con.execute("PRAGMA table_info(%s)" % table)}
            missing += ["%s.%s" % (table, c) for c in cols if c not in have]
        self.assertEqual([], missing)

    def test_labeling_sqlite_schema(self):
        con = self._work_con()
        db_path = export.export(self.ws, con, "RUN-CONTRACT", _empty_tax())
        self.assertEqual(os.path.join(self.ws.root, "out", "labeling.sqlite"), db_path)
        out = sqlite3.connect(db_path)
        try:
            master = _master(out)
            meta_keys = [r[0] for r in out.execute("SELECT key FROM meta ORDER BY key")]
            counts = {r[1]: out.execute("SELECT COUNT(*) FROM %s" % r[1]).fetchone()[0]
                      for r in out.execute("SELECT type, name FROM sqlite_master WHERE type='table'")}
        finally:
            out.close()
        with open(os.path.join(self.ws.root, "out", "SCHEMA.md"), encoding="utf-8") as f:
            schema_md = _support.normalize(f.read())
        data = {
            "sqlite_master": master,
            "meta_keys": meta_keys,
            "empty_row_counts": counts,
            "out_entries": sorted(os.listdir(os.path.join(self.ws.root, "out"))),
            "schema_md_empty_taxonomy": schema_md,
            "export_SCHEMA_columns": [[name, [[c, t] for c, t, _ in cols]] for name, _, cols in export.SCHEMA],
        }
        _support.check(self, "schema_labeling_sqlite", data)


if __name__ == "__main__":
    unittest.main()
