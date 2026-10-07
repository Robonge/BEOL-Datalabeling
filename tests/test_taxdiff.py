"""taxonomy 변경 감지(taxdiff), taxonomy-diff 명령, selfcheck 축 품질 WARN 테스트. 픽스처 taxonomy.json은 임시 폴더에 만든다."""
import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest

from labelbot import cli, selfcheck, store, taxdiff, taxonomy, util
from labelbot.pipeline import start_run
from labelbot.workspace import Workspace
from tests.test_taxonomy import axis_row, base_sheets, build, tax_row


def parse(sheets):
    return taxonomy.parse_bytes(build(sheets))


def with_new_axis(sheets, name="신규 축", with_question=False, definition="정의"):
    sheets["taxonomy"] += [axis_row(name, definition=definition), tax_row(name, "A1"), tax_row(name, "A2")]
    if with_question:
        sheets["questions"].append(["Q-NEW-001", "새 축 질문", "%s=A1" % name, 3])
    return sheets


class SignatureDiffTest(unittest.TestCase):
    def test_signature_shape(self):
        sig = taxdiff.axes_signature(parse(base_sheets()))
        by = {s["name"]: s for s in sig}
        self.assertEqual(set(by["불량 모드"]), {"name", "kind", "multi", "hierarchy", "active", "n_values", "values",
                                                "values_hash"})
        self.assertEqual(by["불량 모드"]["values"], ["EM", "Reliability", "Short"])
        self.assertEqual(len(by["불량 모드"]["values_hash"]), 12)
        self.assertEqual((by["불량 모드"]["hierarchy"], by["불량 모드"]["n_values"], by["불량 모드"]["active"]),
                         (True, 3, True))
        self.assertEqual((by["제품·세대"]["active"], by["제품·세대"]["n_values"]), (False, 0))
        self.assertEqual(by["의사결정 상태"]["kind"], "상태")
        self.assertNotIn("정의", json.dumps(sig, ensure_ascii=False))

    def test_no_previous_run(self):
        self.assertEqual(taxdiff.diff(None, []), {"code": "NO_PREVIOUS_RUN"})

    def test_added_removed_changed_values(self):
        prev = taxdiff.axes_signature(parse(base_sheets()))
        s = base_sheets()
        s["taxonomy"].append(tax_row("불량 모드", "Open"))  # 값 +1
        s["taxonomy"] = [r for r in s["taxonomy"] if r[0] != "의사결정 상태"]  # 축 삭제
        with_new_axis(s)
        for r in s["taxonomy"]:
            if r[0] == "구조/레이어" and r[1] is None:
                r[3] = "N"  # 다중값 변경
        d = taxdiff.diff(prev, taxdiff.axes_signature(parse(s)))
        self.assertEqual(d["added"], ["신규 축"])
        self.assertEqual(d["removed"], ["의사결정 상태"])
        self.assertEqual(d["changed"], [{"axis": "구조/레이어", "fields": ["multi"]}])
        self.assertEqual(d["values_added"], {"불량 모드": 1})
        self.assertNotIn("partial", d)
        self.assertTrue(taxdiff.needs_rerun(d))
        self.assertIn("전체 재실행 필요", taxdiff.summary_line(d))

    def test_values_removed_and_renamed(self):
        s = base_sheets()
        s["taxonomy"].append(tax_row("불량 모드", "Open"))
        prev = taxdiff.axes_signature(parse(s))  # 지난 실행에는 값이 하나 더 있었다
        d = taxdiff.diff(prev, taxdiff.axes_signature(parse(base_sheets())))  # 값 -1
        self.assertEqual(d["values_removed"], {"불량 모드": 1})
        self.assertIn({"axis": "불량 모드", "fields": ["values"]}, d["changed"])
        self.assertTrue(taxdiff.needs_rerun(d))
        self.assertIn("값 -1", taxdiff.summary_line(d))
        s2 = base_sheets()  # 개수는 같고 값 이름만 바뀜(이름 목록으로 +1·-1)
        s2["taxonomy"].append(tax_row("불량 모드", "Closed"))
        d2 = taxdiff.diff(prev, taxdiff.axes_signature(parse(s2)))
        self.assertEqual((d2["values_added"], d2["values_removed"]), ({"불량 모드": 1}, {"불량 모드": 1}))
        self.assertIn({"axis": "불량 모드", "fields": ["values"]}, d2["changed"])

    def test_add_and_rename_in_same_edit_is_not_pure_addition(self):
        prev = taxdiff.axes_signature(parse(base_sheets()))
        s = base_sheets()
        s["taxonomy"] = [tax_row("구조/레이어", "V2") if (r[0] == "구조/레이어" and r[1] == "V1") else r
                         for r in s["taxonomy"]]
        s["taxonomy"].append(tax_row("구조/레이어", "M2"))  # 값 +1과 이름 변경(V1→V2)을 한 번에
        d = taxdiff.diff(prev, taxdiff.axes_signature(parse(s)))
        self.assertEqual((d["values_added"], d["values_removed"]), ({"구조/레이어": 2}, {"구조/레이어": 1}))
        self.assertIn({"axis": "구조/레이어", "fields": ["values"]}, d["changed"])
        s = base_sheets()
        s["taxonomy"].append(tax_row("구조/레이어", "M2"))  # 순수 추가
        d = taxdiff.diff(prev, taxdiff.axes_signature(parse(s)))
        self.assertEqual((d["values_added"], d["changed"]), ({"구조/레이어": 1}, []))
        self.assertTrue(taxdiff.needs_rerun(d))

    def test_old_signature_without_value_names_marks_addition_changed(self):
        old = [{k: v for k, v in x.items() if k != "values"} for x in taxdiff.axes_signature(parse(base_sheets()))]
        s = base_sheets()
        s["taxonomy"].append(tax_row("구조/레이어", "M2"))
        d = taxdiff.diff(old, taxdiff.axes_signature(parse(s)))
        self.assertEqual(d["values_added"], {"구조/레이어": 1})
        self.assertIn({"axis": "구조/레이어", "fields": ["values"]}, d["changed"])  # 순수 추가인지 알 수 없다

    def test_old_signature_without_values_hash_skips_values_compare(self):
        cur = taxdiff.axes_signature(parse(base_sheets()))
        old = [{k: v for k, v in x.items() if k not in ("values_hash", "values")} for x in cur]
        self.assertEqual(taxdiff.diff(old, cur)["changed"], [])

    def test_unchanged(self):
        sig = taxdiff.axes_signature(parse(base_sheets()))
        d = taxdiff.diff(sig, sig)
        self.assertEqual(d, {"added": [], "removed": [], "changed": [], "values_added": {}})
        self.assertTrue(taxdiff.summary_line(d).endswith("변경 없음"))

    def test_partial_from_axis_kinds(self):
        tax = parse(with_new_axis(base_sheets()))
        old = {a.name: a.kind for a in parse(base_sheets()).axes}
        old["불량 모드"] = "상태"
        d = taxdiff.diff(old, taxdiff.axes_signature(tax))
        self.assertTrue(d["partial"])
        self.assertEqual(d["added"], ["신규 축"])
        self.assertEqual(d["changed"], [{"axis": "불량 모드", "fields": ["kind"]}])
        self.assertEqual(d["values_added"], {})


class WorkspaceCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="labelbot_ws_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.tax_path = os.path.join(self.dir, "taxonomy.json")
        with open(self.tax_path, "wb") as f:
            f.write(build(base_sheets()))
        cfg = {"taxonomy_path": self.tax_path, "llm": {"transport": "mock", "model": "mock"},
               "embedding": {"transport": "mock"}, "supabase": {"enabled": False}}
        with open(os.path.join(self.dir, "pipeline.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        self.ws = Workspace(self.dir)

    def write_taxonomy(self, sheets):
        with open(self.tax_path, "wb") as f:
            f.write(build(sheets))

    def record_run(self, meta):
        con = store.connect(self.ws.work_db)
        try:
            run_id = start_run(con, self.ws, "run")
            for k, v in meta.items():
                store.meta_set(con, k, util.dumps(v))
            con.commit()
        finally:
            con.close()
        return run_id

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue().splitlines(), err.getvalue()


class TaxonomyDiffCliTest(WorkspaceCase):
    def test_no_previous_run(self):
        code, lines, _ = self.cli("taxonomy-diff", "--workspace", self.dir)
        self.assertEqual(code, 0)
        obj = json.loads(lines[0])
        self.assertEqual((obj["code"], obj["run_id"]), ("NO_PREVIOUS_RUN", None))

    def test_new_axis_after_run(self):
        run_id = self.record_run({"axes_signature": taxdiff.axes_signature(parse(base_sheets()))})
        self.write_taxonomy(with_new_axis(base_sheets()))
        code, lines, _ = self.cli("taxonomy-diff", "--workspace", self.dir)
        self.assertEqual(code, 0)
        obj = json.loads(lines[0])
        self.assertEqual(obj["run_id"], run_id)
        self.assertEqual(obj["added"], ["신규 축"])
        self.assertEqual(lines[1], "[taxonomy] 지난 실행 대비 축 +1(신규 축) -0 · 값 +0 · 종류/설정 변경 0 → 전체 재실행 필요")

    def test_old_run_with_axis_kinds_only(self):
        self.record_run({"axis_kinds": {a.name: a.kind for a in parse(base_sheets()).axes}})
        self.write_taxonomy(with_new_axis(base_sheets()))
        _, lines, _ = self.cli("taxonomy-diff", "--workspace", self.dir)
        obj = json.loads(lines[0])
        self.assertTrue(obj["partial"])
        self.assertEqual(obj["added"], ["신규 축"])

    def test_per_run_signature_preferred(self):
        base = taxdiff.axes_signature(parse(base_sheets()))
        run_id = self.record_run({"axes_signature": []})  # 마지막 실행 meta는 비어 있고
        con = store.connect(self.ws.work_db)
        try:  # 실행별 키만 진짜 서명을 가진다
            store.meta_set(con, "axes_signature:" + run_id, util.dumps(base))
            con.commit()
            prev, rid = taxdiff.previous_signature(con)
        finally:
            con.close()
        self.assertEqual((prev, rid), (base, run_id))

    def test_unchanged(self):
        self.record_run({"axes_signature": taxdiff.axes_signature(parse(base_sheets()))})
        _, lines, _ = self.cli("taxonomy-diff", "--workspace", self.dir)
        self.assertTrue(lines[1].endswith("→ 변경 없음"))

    def test_invalid_workspace(self):
        code, _, err = self.cli("taxonomy-diff", "--workspace", os.path.dirname(os.path.abspath(taxdiff.__file__)))
        self.assertEqual(code, 2)
        self.assertIn("[오류]", err)


class SelfcheckAxisTest(WorkspaceCase):
    def run_selfcheck(self):
        lines = []
        ok, _ = selfcheck.run(self.ws, out=lines.append)
        return ok, lines

    def line(self, lines, name):
        return next(x for x in lines if x.startswith(name))

    def test_taxonomy_item_has_diff_and_stays_pass(self):
        self.record_run({"axes_signature": taxdiff.axes_signature(parse(base_sheets()))})
        self.write_taxonomy(with_new_axis(base_sheets()))
        ok, lines = self.run_selfcheck()
        row = self.line(lines, "taxonomy.json")
        self.assertIn("PASS", row)
        self.assertIn("축 +1(신규 축)", row)
        self.assertTrue(ok)

    def test_diff_failure_keeps_taxonomy_pass(self):
        self.record_run({"axes_signature": taxdiff.axes_signature(parse(base_sheets()))})
        orig = taxdiff.compare_workspace
        taxdiff.compare_workspace = lambda ws, tax: (_ for _ in ()).throw(RuntimeError("db"))
        self.addCleanup(setattr, taxdiff, "compare_workspace", orig)
        ok, lines = self.run_selfcheck()
        row = self.line(lines, "taxonomy.json")
        self.assertIn("PASS", row)
        self.assertIn("diff 알 수 없음", row)
        self.assertTrue(ok)

    def test_warn_items(self):
        s = base_sheets()
        s["taxonomy"].append(axis_row("정의없음", definition=None))
        s["taxonomy"].append(tax_row("정의없음", "X"))
        with_new_axis(s)  # 질문 없는 새 축
        self.record_run({"axes_signature": taxdiff.axes_signature(parse(base_sheets()))})
        self.write_taxonomy(s)
        ok, lines = self.run_selfcheck()
        row = self.line(lines, "taxonomy_axes")
        self.assertIn("PASS", row)
        self.assertTrue(ok)
        self.assertIn("WARN 정의·판정 규칙 없는 활성 축 1(정의없음)", row)
        # 기존 축(질문 없음)은 알리지 않고 새 축만 알린다.
        self.assertIn("WARN 질문 적용 대상에 없는 새 축 2(정의없음, 신규 축)", row)
        self.assertIn("WARN 값 행이 없어 비활성인 축 1(제품·세대)", row)

    def test_warn_question_present_clears_new_axis_warning(self):
        s = with_new_axis(base_sheets(), with_question=True)
        self.write_taxonomy(s)
        _, lines = self.run_selfcheck()
        row = self.line(lines, "taxonomy_axes")
        self.assertNotIn("신규 축", row)
        self.assertNotIn("정의·판정 규칙 없는", row)


if __name__ == "__main__":
    unittest.main()
