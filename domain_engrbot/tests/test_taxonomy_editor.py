"""taxonomy 편집기(taxonomy_editor): 읽기(rejected 숨김)·미리보기(쓰지 않음)·저장(rejected 보존, 이력)·
버전 충돌 409·검증 실패 400·xlsx 거절·같은 출처 확인. 임시 폴더의 JSON 테스트 데이터만 쓴다."""
import argparse
import contextlib
import copy
import http.client
import io as std_io
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest import mock

from domain_engrbot import taxonomy_editor as te
from labelbot import taxonomy as lb_taxonomy

H = {s: list(h) for s, h in lb_taxonomy.HEADERS.items()}


def _row(sheet, **kw):
    return {h: kw.get(h, "") for h in H[sheet]}


def fixture_doc():
    tx = [
        _row("taxonomy", **{"축": "공정", "다중값": "N", "계층": "Y", "중복 알림 제외": "N", "종류": "분류", "사용 여부": "Y"}),
        _row("taxonomy", **{"축": "공정", "값": "식각", "정의·판정 규칙": "패턴을 깎는다", "사용 여부": "Y"}),
        _row("taxonomy", **{"축": "공정", "값": "건식 식각", "상위값": "식각", "사용 여부": "Y"}),
        _row("taxonomy", **{"축": "공정", "값": "증착", "사용 여부": "N"}),
    ]
    return {"version": 1, "taxonomy": tx,
            "questions": [_row("questions", **{"질문 ID": "Q1", "문장": "식각 조건이 있나?", "적용 대상": "공통", "우선순위": "1"})],
            "synonyms": [_row("synonyms", **{"동의어": "에칭", "표준어": "식각"})],
            "rejected": [{"종류": "값", "내용": "애싱", "기각일": "2026-10-01", "사유": "범위 밖", "출처": "abcd1234"}]}


def _read(path):
    with open(path, "rb") as f:
        return f.read()


class UseToggleTest(unittest.TestCase):
    """'사용 여부' 토글: 끄고 다시 켜면 원래 값으로 돌아간다(원래 ""이면 "", 뜻이 같은데 해시가 바뀌지 않게)."""

    def setUp(self):
        with open(te.SCREEN, encoding="utf-8") as f:
            self.html = f.read()

    def fn(self, name):
        m = re.search(r"^  function %s\(.*}$" % name, self.html, re.M)   # 한 줄 함수
        if m is None:
            m = re.search(r"^  function %s\(.*?^  }$" % name, self.html, re.S | re.M)
        self.assertIsNotNone(m, name)
        return m.group(0)

    def test_toggle_restores_original_value(self):
        self.assertIn('e.data["사용 여부"] = toggledUse(sheet, e)', self.html)
        self.assertNotIn('isOff(e) ? "Y" : "N"', self.html)
        node = shutil.which("node")
        if node is None:   # node가 없으면 위 정적 확인만 한다
            return
        js = "\n".join([self.fn("str"), self.fn("isOff"), self.fn("toggledUse"), """
var S = {orig: {taxonomy: [{"사용 여부": ""}, {"사용 여부": "Y"}, {"사용 여부": "N"}]}};
var out = [];
[0, 1, 2, null].forEach(function(i){
  var e = {orig: i, data: {"사용 여부": i === null ? "" : S.orig.taxonomy[i]["사용 여부"]}};
  e.data["사용 여부"] = toggledUse("taxonomy", e); var a = e.data["사용 여부"];
  e.data["사용 여부"] = toggledUse("taxonomy", e); out.push([a, e.data["사용 여부"]]);
});
console.log(JSON.stringify(out));"""])
        got = subprocess.run([node, "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertEqual(json.loads(got.stdout), [["N", ""], ["N", "Y"], ["Y", "N"], ["N", ""]])


class EditorLogicTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="domain_engrbot_teditor_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = os.path.join(self.tmp, "taxonomy.json")
        with open(self.path, "w", encoding="utf-8", newline="\n") as f:
            f.write(lb_taxonomy.dump_doc(fixture_doc()))
        self.hist = os.path.join(self.tmp, lb_taxonomy.HISTORY_NAME)

    def state(self):
        return te.doc_state(self.path)

    def payload(self, state=None, mutate=None):
        st = state or self.state()
        doc = copy.deepcopy(st["doc"])
        if mutate:
            mutate(doc)
        return {"kind": te.SAVE_KIND, "base_version": st["version"], "doc": doc}

    def test_get_doc_hides_rejected(self):
        st = self.state()
        self.assertTrue(st["ok"])
        self.assertEqual(sorted(st["doc"]), ["questions", "synonyms", "taxonomy"])
        self.assertNotIn("rejected", st["doc"])
        self.assertNotIn("애싱", json.dumps(st, ensure_ascii=False))
        self.assertEqual((st["issues"], len(st["doc"]["taxonomy"])), ([], 4))
        self.assertEqual(st["headers"]["taxonomy"], H["taxonomy"])

    def test_preview_returns_diff_without_writing(self):
        before = _read(self.path)

        def mutate(doc):
            doc["taxonomy"][1]["정의·판정 규칙"] = "패턴을 깎는다\n  둘째 줄"
            doc["synonyms"].append(_row("synonyms", **{"동의어": "etch", "표준어": "식각"}))
        out = te.preview(self.path, self.payload(mutate=mutate))
        self.assertEqual(_read(self.path), before, "미리보기는 파일을 쓰지 않는다")
        self.assertFalse(os.path.exists(self.hist))
        self.assertEqual(out["counts"], {"add": 1, "edit": 1, "delete": 0})
        edit = next(d for d in out["diff"] if d["op"] == "edit")
        self.assertEqual((edit["sheet"], edit["row"]), ("taxonomy", 3))
        self.assertEqual(edit["after"]["정의·판정 규칙"], "패턴을 깎는다\n  둘째 줄")
        self.assertEqual(out["issues"], [])

    def test_save_writes_history_and_keeps_rejected(self):
        st = self.state()
        text = "  앞 공백\n=수식처럼 보이는 문장\n"

        def mutate(doc):
            doc["taxonomy"][2]["포함 예"] = text
            doc["taxonomy"][3]["사용 여부"] = "Y"   # 사용 여부 켜기
            del doc["questions"][0]
            doc["rejected"] = []                       # 화면이 rejected를 보내도 무시한다
        p = self.payload(st, mutate)
        p["rejected"] = [{"종류": "값", "내용": "x"}]
        out = te.save(self.path, p)
        self.assertTrue(out["ok"] and out["saved"])
        self.assertEqual(out["counts"]["questions"], 0)
        doc, version, _b = lb_taxonomy.load_doc(self.path)
        self.assertEqual(out["version"], version)
        self.assertEqual(doc["rejected"], fixture_doc()["rejected"], "rejected는 지금 파일 것을 그대로 둔다")
        self.assertEqual(doc["taxonomy"][2]["포함 예"], text, "문장은 공백·줄바꿈·수식 문자까지 그대로")
        self.assertEqual(doc["taxonomy"][3]["사용 여부"], "Y")
        self.assertEqual(doc["questions"], [])
        lb_taxonomy.parse_doc(doc)   # 저장한 JSON을 labelbot이 그대로 읽는다
        with open(self.hist, encoding="utf-8") as f:
            lines = [json.loads(x) for x in f if x.strip()]
        self.assertEqual(len(lines), 1)
        self.assertEqual((lines[0]["by"], lines[0]["version"]), ("editor", st["version"]))
        self.assertEqual(len(lines[0]["doc"]["questions"]), 1, "이력에는 바꾸기 전 문서가 남는다")

    def test_save_without_change_does_not_write(self):
        before = _read(self.path)
        out = te.save(self.path, self.payload())
        self.assertEqual((out["ok"], out["saved"]), (True, False))
        self.assertEqual(_read(self.path), before)
        self.assertFalse(os.path.exists(self.hist))

    def test_version_conflict_409(self):
        old = self.state()
        te.save(self.path, self.payload(mutate=lambda d: d["synonyms"][0].__setitem__("메모", "다른 화면")))
        for fn in (te.preview, te.save):
            with self.assertRaises(te.EditorError) as cm:
                fn(self.path, self.payload(old, lambda d: d["synonyms"][0].__setitem__("메모", "늦은 저장")))
            self.assertEqual((cm.exception.status, cm.exception.reason_code), (409, "TAXONOMY_CHANGED"))
        self.assertEqual(lb_taxonomy.load_doc(self.path)[0]["synonyms"][0]["메모"], "다른 화면")

    def test_invalid_doc_400_and_file_unchanged(self):
        before = _read(self.path)

        def mutate(doc):
            doc["taxonomy"][2]["상위값"] = "없는 값"
        p = self.payload(mutate=mutate)
        pv = te.preview(self.path, p)
        self.assertIn({"sheet": "taxonomy", "row": 4, "code": "PARENT_NOT_FOUND"}, pv["issues"])
        with self.assertRaises(te.EditorError) as cm:
            te.save(self.path, p)
        e = cm.exception
        self.assertEqual((e.status, e.reason_code), (400, "TAXONOMY_INVALID"))
        self.assertIn({"sheet": "taxonomy", "row": 4, "code": "PARENT_NOT_FOUND"}, e.body()["issues"])
        self.assertEqual(_read(self.path), before)
        self.assertFalse(os.path.exists(self.hist))

    def test_format_invalid_400(self):
        st = self.state()
        bad = [{"kind": "x"}, {"kind": te.SAVE_KIND, "base_version": st["version"], "doc": {"taxonomy": []}},
               {"kind": te.SAVE_KIND, "base_version": st["version"],
                "doc": dict(st["doc"], synonyms=[{"동의어": 3, "표준어": "식각"}])}]
        for p in bad:
            with self.assertRaises(te.EditorError) as cm:
                te.preview(self.path, p)
            self.assertEqual((cm.exception.status, cm.exception.reason_code), (400, "EDITOR_FORMAT_INVALID"))

    def test_shared_commit_error_codes(self):
        """보드와 같은 commit_taxonomy 거절 코드: 쓰기 실패 500, 읽기 실패 500(detail), 파일 없음 404."""
        p = self.payload(mutate=lambda d: d["synonyms"][0].__setitem__("메모", "바꿈"))
        before = _read(self.path)
        with mock.patch.object(te.lb, "save_taxonomy_doc", side_effect=OSError("잠김")):
            with self.assertRaises(te.EditorError) as cm:
                te.save(self.path, p)
        self.assertEqual((cm.exception.status, cm.exception.reason_code), (500, "TAXONOMY_WRITE_FAILED"))
        self.assertEqual(_read(self.path), before)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{not json")
        with self.assertRaises(te.EditorError) as cm:
            te.preview(self.path, p)
        self.assertEqual((cm.exception.status, cm.exception.body()),
                         (500, {"ok": False, "code": "TAXONOMY_READ_FAILED", "detail": "TAXONOMY_JSON_INVALID"}))
        os.remove(self.path)
        for fn in (te.preview, te.save):
            with self.assertRaises(te.EditorError) as cm:
                fn(self.path, p)
            self.assertEqual((cm.exception.status, cm.exception.reason_code), (404, "TAXONOMY_NOT_FOUND"))

    def test_cell_too_long_400(self):
        p = self.payload(mutate=lambda d: d["synonyms"][0].__setitem__("메모", "가" * (te.CELL_MAX + 1)))
        for fn in (te.preview, te.save):
            with self.assertRaises(te.EditorError) as cm:
                fn(self.path, p)
            self.assertEqual((cm.exception.status, cm.exception.reason_code), (400, "EDITOR_FORMAT_INVALID"))
        ok = self.payload(mutate=lambda d: d["synonyms"][0].__setitem__("메모", "가" * te.CELL_MAX))
        self.assertTrue(te.preview(self.path, ok)["ok"])

    def test_xlsx_path_refused(self):
        x = os.path.join(self.tmp, "taxonomy.xlsx")
        with self.assertRaises(te.EditorError) as cm:
            te.doc_state(x)
        self.assertEqual(cm.exception.reason_code, "TAXONOMY_XLSX_NEEDS_MIGRATION")
        said = []
        self.assertEqual(te.serve_editor(x, said.append), 1)
        self.assertEqual(said, ["[오류] TAXONOMY_XLSX_NEEDS_MIGRATION"])
        said = []
        self.assertEqual(te.serve_editor(os.path.join(self.tmp, "none.json"), said.append), 1)
        self.assertEqual(said, ["[오류] TAXONOMY_NOT_FOUND"])

    def test_cli_arguments(self):
        p = argparse.ArgumentParser()
        te.add_arguments(p)
        a = p.parse_args(["--taxonomy", self.path, "--port", "0", "--open"])
        self.assertEqual((a.taxonomy, a.port, a.open), (self.path, 0, True))
        self.assertTrue(te.DEFAULT_TAXONOMY.replace("\\", "/").endswith("taxonomy/taxonomy.json"))


class EditorServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="domain_engrbot_teditor_srv_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = os.path.join(self.tmp, "taxonomy.json")
        with open(self.path, "w", encoding="utf-8", newline="\n") as f:
            f.write(lb_taxonomy.dump_doc(fixture_doc()))
        self.srv = te.make_editor_server(self.path, 0)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.port = self.srv.server_address[1]
        self.host = "127.0.0.1:%d" % self.port

    def req(self, method, path, body=None, origin=True, ctype="application/json", host=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        hdr = {"Host": host or self.host}
        raw = None
        if body is not None:
            raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
            hdr["Content-Type"] = ctype
            if origin:
                hdr["Origin"] = "http://" + self.host
        c.request(method, path, raw, hdr)
        r = c.getresponse()
        data = r.read()
        ct = r.getheader("Content-Type") or ""
        csp = r.getheader("Content-Security-Policy") or ""
        c.close()
        return r.status, (json.loads(data.decode("utf-8")) if ct.startswith("application/json") else data), csp

    def test_roundtrip_and_guards(self):
        st, body, csp = self.req("GET", "/")
        self.assertEqual(st, 200)
        self.assertIn("script-src 'unsafe-inline'", csp)
        self.assertIn("taxonomy 편집기".encode("utf-8"), body)
        self.assertNotIn(b"<script src", body)
        self.assertEqual(self.req("GET", "/editor/doc", host="evil.example:80")[0], 403)
        st, doc, _ = self.req("GET", "/editor/doc")
        self.assertEqual(st, 200)
        self.assertNotIn("rejected", doc["doc"])
        d = copy.deepcopy(doc["doc"])
        d["synonyms"][0]["메모"] = "편집기에서"
        p = {"kind": te.SAVE_KIND, "base_version": doc["version"], "doc": d}
        self.assertEqual(self.req("POST", "/editor/save", p, origin=False)[0], 403)
        self.assertEqual(self.req("POST", "/editor/save", p, ctype="text/plain")[0], 415)
        st, pv, _ = self.req("POST", "/editor/preview", p)
        self.assertEqual((st, pv["counts"]["edit"]), (200, 1))
        st, sv, _ = self.req("POST", "/editor/save", p)
        self.assertEqual((st, sv["ok"], sv["saved"]), (200, True, True))
        st, again, _ = self.req("POST", "/editor/save", p)
        self.assertEqual((st, again["code"]), (409, "TAXONOMY_CHANGED"))
        d2 = copy.deepcopy(d)
        d2["questions"][0]["적용 대상"] = "없는축=값"
        st, bad, _ = self.req("POST", "/editor/save", {"kind": te.SAVE_KIND, "base_version": sv["version"], "doc": d2})
        self.assertEqual((st, bad["code"]), (400, "TAXONOMY_INVALID"))
        self.assertIn({"sheet": "questions", "row": 2, "code": "QUESTION_TARGET_INVALID"}, bad["issues"])
        saved = lb_taxonomy.load_doc(self.path)[0]
        self.assertEqual((saved["synonyms"][0]["메모"], saved["rejected"]), ("편집기에서", fixture_doc()["rejected"]))
        self.assertEqual(self.req("GET", "/nope")[0], 404)

    def test_server_error_codes_and_catch_all(self):
        st, doc, _ = self.req("GET", "/editor/doc")
        d = copy.deepcopy(doc["doc"])
        d["synonyms"][0]["메모"] = "바꿈"
        p = {"kind": te.SAVE_KIND, "base_version": doc["version"], "doc": d}
        with mock.patch.object(te.lb, "save_taxonomy_doc", side_effect=OSError("잠김")):
            st, body, _ = self.req("POST", "/editor/save", p)
        self.assertEqual((st, body["code"]), (500, "TAXONOMY_WRITE_FAILED"))
        buf = std_io.StringIO()
        with mock.patch.object(te, "preview", side_effect=RuntimeError("셀 내용이 든 문장")), \
                contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            st, body, _ = self.req("POST", "/editor/preview", p)
        self.assertEqual((st, body), (500, {"ok": False, "code": "EDITOR_FAILED", "detail": "RuntimeError"}))
        self.assertNotIn("셀 내용", buf.getvalue())
        self.assertNotIn("Traceback", buf.getvalue())
        os.remove(self.path)
        st, body, _ = self.req("POST", "/editor/preview", p)
        self.assertEqual((st, body["code"]), (404, "TAXONOMY_NOT_FOUND"))


if __name__ == "__main__":
    unittest.main()
