"""taxonomy.json 저장(save_doc: 버전 확인·검증·이력·잠금)·변경 미리보기(diff_docs)·xlsx 1회 변환(taxmigrate) 테스트."""
import json
import os
import shutil
import tempfile
import unittest

from labelbot import taxmigrate, taxonomy, util, workspace
from tests.test_taxonomy import base_sheets, build_xlsx, tax_row, to_doc


class SaveDocTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "taxonomy.json")
        util.write_text(self.path, taxonomy.dump_doc(to_doc(base_sheets())))
        self.doc, self.version, _b = taxonomy.load_doc(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_dump_is_one_row_per_line_and_round_trips(self):
        with open(self.path, encoding="utf-8") as f:
            text = f.read()
        self.assertEqual(json.loads(text), self.doc)
        self.assertEqual(text.count("\n"), 2 + sum(len(self.doc[k]) + 2 for k in taxonomy.HEADERS) + 1 + 1)
        self.assertEqual(taxonomy.doc_version(text.encode("utf-8")), self.version)

    def test_save_writes_history_and_returns_new_version(self):
        doc = json.loads(json.dumps(self.doc))
        doc["synonyms"].append(taxonomy.row_obj(["비아", "V1", "줄\n바꿈 = 유지"], taxonomy.HEADERS["synonyms"]))
        v = taxonomy.save_doc(self.path, doc, self.version, "editor", now="2026-10-07T00:00:00Z")
        new, v2, _b = taxonomy.load_doc(self.path)
        self.assertEqual(v, v2)
        self.assertEqual(new["synonyms"][-1]["메모"], "줄\n바꿈 = 유지")
        hist = os.path.join(self.tmp.name, taxonomy.HISTORY_NAME)
        with open(hist, encoding="utf-8") as f:
            recs = [json.loads(line) for line in f]
        self.assertEqual([(r["by"], r["version"]) for r in recs], [("editor", self.version)])
        self.assertEqual(recs[0]["doc"], self.doc)
        self.assertEqual(sorted(os.listdir(self.tmp.name)), sorted(["taxonomy.json", taxonomy.HISTORY_NAME]))

    def test_version_conflict(self):
        with self.assertRaises(taxonomy.TaxonomyConflict) as cm:
            taxonomy.save_doc(self.path, self.doc, "0" * 64, "board")
        self.assertEqual(cm.exception.reason_code, "TAXONOMY_CHANGED")

    def test_invalid_doc_leaves_file(self):
        doc = json.loads(json.dumps(self.doc))
        doc["taxonomy"].append(taxonomy.row_obj(tax_row("불량 모드", "TDDB", "없는값"), taxonomy.HEADERS["taxonomy"]))
        with open(self.path, "rb") as f:
            before = f.read()
        with self.assertRaises(taxonomy.TaxonomyError) as cm:
            taxonomy.save_doc(self.path, doc, self.version, "board")
        self.assertEqual([i.code for i in cm.exception.issues], ["PARENT_NOT_FOUND"])
        with open(self.path, "rb") as f:
            self.assertEqual(f.read(), before)
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, taxonomy.HISTORY_NAME)))

    def test_stale_lock_is_cleared(self):
        lock = taxonomy._FileLock(self.path).path
        with open(lock, "w") as f:
            f.write("{}")
        old = os.path.getmtime(lock) - taxonomy.LOCK_STALE_SEC - 5
        os.utime(lock, (old, old))
        taxonomy.save_doc(self.path, self.doc, self.version, "board")
        self.assertFalse(os.path.exists(lock))


class DiffDocsTest(unittest.TestCase):
    def test_add_edit_delete(self):
        old = to_doc(base_sheets())
        new = json.loads(json.dumps(old))
        new["synonyms"][0]["메모"] = "바뀜"
        del new["questions"][1]
        new["rejected"].append({"종류": "값", "내용": "구조/레이어|M9", "기각일": "2026-10-07", "사유": "", "출처": "x"})
        got = [(d["sheet"], d["op"], d["row"]) for d in taxonomy.diff_docs(old, new)]
        self.assertEqual(got, [("questions", "delete", 3), ("synonyms", "edit", 2), ("rejected", "add", 2)])
        self.assertEqual(taxonomy.diff_docs(old, old), [])


class MigrateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.xlsx = os.path.join(self.root, "tax_fixture.b64")   # 확장자와 무관하게 시그니처로 판정한다
        s = base_sheets()
        s["files"] = [["파일 ID", "파일명", "제외", "맥락 메모"], ["a" * 64, "a.pptx", "Y", "메모"]]
        with open(self.xlsx, "wb") as f:
            f.write(build_xlsx(s))
        self.ws = os.path.join(self.root, "workspaces")
        for name, path in (("w1", self.xlsx), ("w2", "다른.xlsx")):
            os.makedirs(os.path.join(self.ws, name))
            util.write_text(os.path.join(self.ws, name, "pipeline.json"), json.dumps({"taxonomy_path": path}))
        os.makedirs(os.path.join(self.ws, "w3"))   # 지정 없이 작업 폴더에 예전 xlsx만 있음
        with open(os.path.join(self.ws, "w3", "taxonomy.xlsx"), "wb") as f:
            f.write(b"PK")
        os.makedirs(os.path.join(self.ws, "w4"))
        util.write_text(os.path.join(self.ws, "w4", "pipeline.json"), "{깨진")

    def tearDown(self):
        self.tmp.cleanup()

    def test_migrate_keeps_hashes_and_rewrites_matching_workspaces(self):
        out = os.path.join(self.root, "taxonomy.json")
        res = taxmigrate.migrate(self.xlsx, out, self.ws)
        self.assertEqual(res["skipped"], [("w3", "XLSX_LOCAL_NEEDS_MIGRATION"), ("w4", "CONFIG_UNREADABLE")])
        self.assertEqual(res["rows"], {"taxonomy": 10, "questions": 2, "synonyms": 2})
        self.assertEqual(res["dropped"], {"files": 1, "files_excluded": 1, "queries": 0})
        self.assertEqual(res["workspaces"], ["w1"])
        with open(os.path.join(self.ws, "w1", "pipeline.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["taxonomy_path"], out.replace("\\", "/"))
        with open(self.xlsx, "rb") as f:
            xb = f.read()
        self.assertEqual(taxonomy.parse_bytes(open(out, "rb").read()).sheet_hashes,
                         {k: v for k, v in taxmigrate.xlsx_sheet_hashes(xb).items()})
        with self.assertRaises(taxmigrate.MigrateError) as cm:
            taxmigrate.migrate(self.xlsx, out, self.ws)
        self.assertEqual(cm.exception.reason_code, "OUT_EXISTS")

    def test_migrate_inside_repo_writes_relative_path(self):
        """JSON과 작업 폴더가 저장소 안(workspaces/ 아래 임시 폴더)이면 작업 폴더 기준 상대경로로 쓴다."""
        os.makedirs(workspace.WORKSPACES_DIR, exist_ok=True)
        base = tempfile.mkdtemp(prefix="_test_taxmigrate_", dir=workspace.WORKSPACES_DIR)
        try:
            xlsx_path = os.path.join(base, "tax_fixture.b64")
            shutil.copyfile(self.xlsx, xlsx_path)
            wsroot = os.path.join(base, "ws")
            os.makedirs(os.path.join(wsroot, "w1"))
            util.write_text(os.path.join(wsroot, "w1", "pipeline.json"), json.dumps({"taxonomy_path": xlsx_path}))
            res = taxmigrate.migrate(xlsx_path, os.path.join(base, "taxonomy.json"), wsroot)
            self.assertEqual(res["workspaces"], ["w1"])
            with open(os.path.join(wsroot, "w1", "pipeline.json"), encoding="utf-8") as f:
                self.assertEqual(json.load(f)["taxonomy_path"], "../../taxonomy.json")
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_migrate_refuses_invalid_xlsx(self):
        s = base_sheets()
        s["taxonomy"].append(tax_row("불량 모드", "TDDB", "없는값"))
        with open(self.xlsx, "wb") as f:
            f.write(build_xlsx(s))
        out = os.path.join(self.root, "taxonomy.json")
        with self.assertRaises(taxmigrate.MigrateError) as cm:
            taxmigrate.migrate(self.xlsx, out)
        self.assertEqual((cm.exception.reason_code, cm.exception.detail), ("TAXONOMY_INVALID", "taxonomy:12:PARENT_NOT_FOUND"))
        self.assertFalse(os.path.exists(out))

    def test_migrate_refuses_merged_cells(self):
        s = base_sheets()
        s["taxonomy"] = {"name": "taxonomy", "rows": s["taxonomy"], "merge": ["A2:A4"]}
        with open(self.xlsx, "wb") as f:
            f.write(build_xlsx(s))
        with self.assertRaises(taxmigrate.MigrateError) as cm:
            taxmigrate.migrate(self.xlsx, os.path.join(self.root, "t.json"))
        self.assertEqual(cm.exception.reason_code, "XLSX_UNUSABLE")


if __name__ == "__main__":
    unittest.main()
