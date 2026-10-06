"""taxonomy 수정 보드 테스트: 출처 병합, 행 초안, 상태 판정, 파싱 오류, 결정성, 화면, CLI.

taxonomy는 tests/xlsx_writer로 메모리에서 만든 bytes를 주입한다(디스크에 .xlsx를 쓰지 않는다).
작업 폴더·장부·재검토 파일은 코드 폴더 밖 임시 폴더에 만든다. 저장소 taxonomy.xlsx는 연기 테스트 하나만 읽는다.
"""
import contextlib
import datetime
import io as std_io
import json
import os
import shutil
import re
import tempfile
import unittest
import zlib
from unittest import mock

from domain_engrbot import cli, io, ledger, taxonomy_board as tb
from domain_engrbot.adapters import labelbot_ws
from tests import xlsx_writer as xw

TAX_HEAD = ["축", "값", "상위값", "다중값", "계층", "중복 알림 제외", "종류", "정의·판정 규칙", "포함 예", "제외 예", "사용 여부"]
TAX_ROWS = [
    ["공정", "", "", "Y", "Y", "N", "분류", "공정 정의", "공정 포함", "공정 제외", ""],   # 2
    ["공정", "CMP", "", "", "", "", "", "CMP 정의", "", "", ""],                        # 3
    ["공정", "식각", "", "", "", "", "", "식각 정의\n둘째 줄", "식각 포함", "", ""],      # 4 (여러 줄 정의)
    ["공정", "옛값", "", "", "", "", "", "", "", "", "N"],                              # 5
    ["상태", "", "", "N", "N", "N", "상태", "상태 정의", "", "", ""],                     # 6
    ["상태", "정상", "", "", "", "", "", "", "", "", ""],                               # 7
    ["공정", "건식식각", "식각", "", "", "", "", "", "", "", ""],                       # 8 (식각의 하위값)
]
NOW = datetime.datetime(2026, 10, 5, 12, 0, 0, tzinfo=datetime.timezone.utc)


def tax_bytes(rows=None, questions_head=None):
    return xw.build([
        ("taxonomy", [TAX_HEAD] + (rows or TAX_ROWS)),
        ("questions", [questions_head or ["질문 ID", "문장", "적용 대상", "우선순위"], ["Q1", "결함이 있나?", "공통", "1"],
                       ["Q2", "CMP 공정인가?", "공정=CMP", "2"]]),
        ("synonyms", [["동의어", "표준어", "메모"], ["씨엠피", "CMP", ""]]),
        ("rejected", [["종류", "내용", "기각일", "사유"], ["값", "공정|거절값", "2026-10-01", ""],
                      ["질문", "거절할 질문?", "2026-10-01", ""]]),
    ])


def _jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


def _prop(pid, kind, target, subject, **kw):
    p = {"proposal_id": pid, "kind": kind, "target": target, "subject": subject,
         "metric": {"name": "비율", "value": 0.4, "n": 20, "count": 8, "threshold": 0.3}, "examples": ["r1", "r2"],
         "paste_row": None}
    p.update(kw)
    return p


def _revisit(cid, target, key, reason, proposed=None, related=None, memo=""):
    return {"review_run_id": "RUN-B", "chunk_id": cid, "target": target, "key": key, "reason": reason,
            "proposed": proposed, "related_values": related or [], "memo": memo}


def _cand(kind, content, parent="", source="bot"):
    return {"kind": kind, "content": content, "axis": "", "parent": parent, "evidence": "", "source": source,
            "freq": 2, "examples": ["c1"], "run_id": "RUN-A"}


def make_sources(tmp):
    """작업 폴더 둘(ws_a, ws_b), 장부, 재검토 파일 폴더. 반환: (작업 폴더 목록, 장부 폴더, 재검토 폴더)."""
    a, b = os.path.join(tmp, "ws_a"), os.path.join(tmp, "ws_b")
    run = os.path.join(a, "qa", "runs", "QA-1")
    _json(os.path.join(run, "manifest.json"), {})
    _jsonl(os.path.join(run, "proposals.jsonl"), [
        _prop("p-unused", "UNUSED_VALUE", "value:공정=식각", {"axis": "공정", "value": "식각"}),
        _prop("p-axis", "AXIS_DEFINITION", "axis:공정", {"axis": "공정"}),
        _prop("p-term", "TERM", "term:플라즈마", {"term": "플라즈마"}),
        _prop("p-quote", "QUOTE_RULE", "prompt:quote", {}),
        _prop("p-qw", "QUESTION_WORDING", "answer:Q1", {"qid": "Q1"}),
        _prop("p-q9", "QUESTION_WORDING", "answer:Q9", {"qid": "Q9"}),
        _prop("p-cmp", "UNUSED_VALUE", "value:공정=CMP", {"axis": "공정", "value": "CMP"}),
        _prop("p-ok", "UNUSED_VALUE", "value:상태=정상", {"axis": "상태", "value": "정상"}),
        _prop("p-old", "UNUSED_VALUE", "value:공정=옛값", {"axis": "공정", "value": "옛값"}),
    ])
    _jsonl(os.path.join(run, "taxonomy_candidates.jsonl"), [
        {"kind": "axis", "axis": "공정", "coverage": 0.5, "unknown_rate": 0.25, "unused": ["식각"], "unused_streak": []},
        {"kind": "term", "term": "플라즈마", "lift": 2.5, "df_u": 3, "df_all": 5, "examples": ["r3"]},
    ])
    _json(os.path.join(run, "feedback", "feedback.json"), {"proposals": [
        _prop("p-s1", "TERM", "term:증착", {"term": "증착"}, **{"as": "value", "sheet": "taxonomy",
                                                              "paste_row": "공정\t증착\t" + "\t" * 8}),
    ]})
    _jsonl(os.path.join(a, "qa", "feedback_rejected.jsonl"), [{"proposal_id": "p-quote"}])
    _jsonl(os.path.join(a, "reports", "candidates.jsonl"), [
        _cand("new_value", "공정|증착"),
        _cand("new_value", "공정|CMP"),
        _cand("new_value", "공정|거절값"),
        _cand("new_value", "없는축|값"),
        _cand("new_value", "공정|옛값"),
        _cand("new_value", "공정|=수식"),
        _cand("synonym", "식각기|식각"),
        _cand("synonym", "씨 엠피|CMP"),
        _cand("synonym", "씨엠피|cmp", source="review"),
        _cand("question", "거절할 질문?"),
    ])
    over = _revisit("c2", "axis", "공정", "VALUE_OVERLAP", related=["식각", "CMP"], memo="둘이 겹친다")
    _jsonl(os.path.join(b, "reports", "taxonomy_revisit.jsonl"), [
        _revisit("c1", "axis", "공정", "NO_FIT_VALUE", proposed={"value": "증착", "parent": None}, memo="맞는 값 없음"),
        over,
        _revisit("c3", "new_axis", "", "NEW_AXIS", proposed={"value": "장비", "parent": None}),
        _revisit("c4", "question", "", "NEED_QUESTION", memo="두께를 묻는 질문"),
        _revisit("c5", "axis", "공정", "OTHER", memo="</script><b>x</b>"),
    ])
    led = os.path.join(tmp, "ledger")
    _jsonl(os.path.join(led, "synonyms.jsonl"), [
        {"alias": "씨엠피", "canonical": "CMP", "sources": ["ws_a"]},
        {"alias": "식각기", "canonical": "에칭", "sources": ["ws_a", "ws_b"]},
    ])
    req = os.path.join(tmp, "taxonomy_revisit_requests")
    _json(os.path.join(req, "taxonomy_revisit_x.json"), {"requests": [dict(over, no=1, block="list")]})
    return [a, b], led, req


def _files(root):
    return sorted(os.path.relpath(os.path.join(d, f), root) for d, _, fs in os.walk(root) for f in fs)


class TaxonomyBoardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="domain_engrbot_tboard_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.roots, self.led, self.req = make_sources(self.tmp)
        self.out = os.path.join(self.tmp, "out")

    def build(self, data=None):
        return tb.build(self.roots, None, self.out, ledger_dir=self.led, requests_dir=self.req, now=NOW,
                        taxonomy_bytes=tax_bytes() if data is None else data)

    def item(self, doc, key):
        found = [it for it in doc["items"] if it["key"] == key]
        self.assertEqual(len(found), 1, key)
        return found[0]

    def test_fixture_taxonomy_parses(self):
        idx, issues, code = tb.load_taxonomy(data=tax_bytes())
        self.assertIsNotNone(idx)
        self.assertEqual(issues, [])
        self.assertIsNone(code)

    def test_merge_three_sources(self):
        it = self.item(self.build(), "tax.value.add|공정|증착")
        self.assertEqual({c["src"] for c in it["sources"]}, {"S1", "S4", "S5"})
        self.assertEqual(len(it["sources"]), 3)
        self.assertEqual(it["status"], "open")
        self.assertEqual(it["rows"][0]["cells"], ["공정", "증착"] + [""] * 9)
        self.assertEqual(it["rows"][0]["target"]["mode"], "append")
        self.assertEqual(it["reject_row"], ["값", "공정|증착", "", ""])

    def test_unused_value_row(self):
        it = self.item(self.build(), "tax.value.off|공정|식각")
        row = it["rows"][0]
        self.assertEqual(len(row["cells"]), 11)
        self.assertEqual(row["cells"][10], "N")
        self.assertEqual(row["cells"][:10], TAX_ROWS[2][:10])
        self.assertEqual(row["target"], {"mode": "overwrite", "row": 4})
        self.assertIn("4행 덮어쓰기", row["place"])
        self.assertEqual(it["action"], "disable")

    def test_axis_definition_row(self):
        it = self.item(self.build(), "tax.axis.def|공정")
        row = it["rows"][0]
        self.assertEqual(row["editable"], [7, 8, 9])
        self.assertEqual(row["cells"], TAX_ROWS[0])
        self.assertEqual(row["target"], {"mode": "overwrite", "row": 2})
        self.assertTrue(any("비율" in m for m in it["context"]["metrics"]))

    def test_status_sheet(self):
        doc = self.build()
        self.assertEqual(self.item(doc, "tax.value.add|공정|cmp")["status"], "done")
        self.assertEqual(self.item(doc, "tax.value.add|공정|거절값")["status"], "rejected")
        self.assertEqual(self.item(doc, "tax.value.add|없는축|값")["status"], "blocked")
        off = self.item(doc, "tax.value.add|공정|옛값")
        self.assertEqual(off["status"], "blocked")
        self.assertEqual(off["action"], "overwrite")
        self.assertEqual(off["rows"][0]["target"], {"mode": "overwrite", "row": 5})
        self.assertEqual(off["rows"][0]["cells"][10], "")
        self.assertEqual(self.item(doc, "syn|씨엠피|cmp")["status"], "done")

    def test_edit_row_hash_change_is_done(self):
        doc = self.build()
        self.assertEqual(self.item(doc, "tax.axis.def|공정")["status"], "open")
        rows = [list(r) for r in TAX_ROWS]
        rows[0][7] = "공정 정의를 고쳤다"
        doc = self.build(tax_bytes(rows))
        it = self.item(doc, "tax.axis.def|공정")
        self.assertEqual((it["status"], it["status_note"]), ("done", "행이 바뀜"))
        self.assertEqual(self.item(doc, "tax.value.overlap|공정|cmp|식각")["status"], "open")
        # 같은 제안이 새 실행에서 다시 올라오면 기준 해시를 다시 잡고 미반영으로 돌린다.
        run2 = os.path.join(self.roots[0], "qa", "runs", "QA-2")
        _json(os.path.join(run2, "manifest.json"), {})
        _jsonl(os.path.join(run2, "proposals.jsonl"), [_prop("p-axis", "AXIS_DEFINITION", "axis:공정", {"axis": "공정"})])
        doc = self.build(tax_bytes(rows))
        self.assertEqual(self.item(doc, "tax.axis.def|공정")["status"], "open")

    def test_missing_axis_and_engr_rejected(self):
        doc = self.build()
        out = self.item(doc, "out|QUOTE_RULE|prompt:quote")
        self.assertEqual((out["group"], out["status"]), ("outside", "rejected"))
        self.assertTrue(out["where"])
        other = self.item(doc, "out|OTHER|axis:공정")
        self.assertEqual(other["status"], "open")
        self.assertEqual(other["where"], tb.OTHER_WHERE)

    def test_overlap_new_axis_question_rows(self):
        doc = self.build()
        ov = self.item(doc, "tax.value.overlap|공정|cmp|식각")
        self.assertEqual([r["target"]["row"] for r in ov["rows"]], [3, 4])
        self.assertTrue(all(r["editable"] == [7, 8, 9] for r in ov["rows"]))
        self.assertEqual(sum(1 for c in ov["sources"] if c["src"] in ("S5", "S5F")), 1)  # 재검토 파일 중복은 뺀다
        na = self.item(doc, "tax.axis.new|장비")
        self.assertEqual(na["rows"][0]["required"], [3, 4, 5, 6])
        self.assertEqual(na["status"], "open")
        qn = [it for it in doc["items"] if it["kind"] == "q_new" and not it["rows"][0]["cells"][1]]
        self.assertEqual(len(qn), 1)
        self.assertEqual(qn[0]["rows"][0]["required"], [0, 1, 2, 3])
        self.assertEqual(qn[0]["context"]["memos"], ["두께를 묻는 질문"])
        qe = self.item(doc, "q.edit|Q1")
        self.assertEqual((qe["rows"][0]["editable"], qe["rows"][0]["target"]["row"]), ([1], 2))

    def test_synonym_conflict_and_term_merge(self):
        doc = self.build()
        a = self.item(doc, "syn|식각기|식각")
        b = self.item(doc, "syn|식각기|에칭")
        self.assertTrue(a["conflict"] and b["conflict"])
        self.assertEqual(b["rows"][0]["cells"], ["식각기", "에칭", "검수 등록"])
        term = self.item(doc, "term|플라즈마")
        self.assertEqual({c["src"] for c in term["sources"]}, {"S2", "S3"})
        self.assertEqual([r["sheet"] for r in term["rows"]], ["synonyms", "taxonomy"])
        self.assertEqual(term["rows"][0]["required"], [1])
        self.assertEqual(self.item(doc, "tax.value.add|공정|증착")["group"], "taxonomy")

    def test_formula_escaped(self):
        it = self.item(self.build(), "tax.value.add|공정|=수식")
        self.assertEqual(it["rows"][0]["cells"][1], "'=수식")

    def test_parse_error_unknown(self):
        doc = self.build(b"not a zip file")
        self.assertFalse(doc["taxonomy"]["readable"])
        self.assertTrue(doc["taxonomy"]["issues"])
        self.assertTrue(all(set(i) == {"sheet", "row", "code"} for i in doc["taxonomy"]["issues"]))
        self.assertTrue(doc["items"])
        self.assertEqual({it["status"] for it in doc["items"]}, {"unknown"})
        self.assertFalse(os.path.exists(os.path.join(self.out, tb.SEEN)))  # 읽지 못한 실행은 seen을 쓰지 않는다

    def test_header_error_still_judged(self):
        doc = self.build(tax_bytes(questions_head=["질문", "문장", "적용 대상", "우선순위"]))
        self.assertTrue(doc["taxonomy"]["readable"])
        self.assertIn("HEADER_MISMATCH", {i["code"] for i in doc["taxonomy"]["issues"]})
        self.assertEqual(self.item(doc, "tax.value.add|공정|cmp")["status"], "done")

    def test_reset_clears_until_new_source(self):
        before = self.build()
        self.assertTrue(before["items"])
        doc = tb.build(self.roots, None, self.out, ledger_dir=self.led, requests_dir=self.req, now=NOW,
                       taxonomy_bytes=tax_bytes(), reset=True)
        self.assertEqual((doc["items"], doc["cleared"]), ([], len(before["items"])))
        self.assertEqual(self.build()["items"], [])           # 다시 실행해도 비어 있다
        # 같은 제안이 새 QA 실행에서 다시 올라오면 그 항목만 다시 보인다
        it = before["items"][0]
        cleared = json.load(open(os.path.join(self.out, tb.CLEARED), encoding="utf-8"))
        cleared[it["id"]] = cleared[it["id"]][1:] if len(cleared[it["id"]]) > 1 else []
        _json(os.path.join(self.out, tb.CLEARED), cleared)
        self.assertEqual([x["id"] for x in self.build()["items"]], [it["id"]])
        os.remove(os.path.join(self.out, tb.CLEARED))         # 되돌리기
        self.assertEqual(len(self.build()["items"]), len(before["items"]))

    def test_deterministic(self):
        first = self.build()
        with open(os.path.join(self.out, tb.DOC), encoding="utf-8") as f:
            a = json.load(f)
        second = tb.build(self.roots, None, self.out, ledger_dir=self.led, requests_dir=self.req,
                          taxonomy_bytes=tax_bytes())
        with open(os.path.join(self.out, tb.DOC), encoding="utf-8") as f:
            b = json.load(f)
        self.assertNotEqual(first["generated_at"], second["generated_at"])
        a.pop("generated_at")
        b.pop("generated_at")
        self.assertEqual(a, b)
        self.assertTrue(all(len(it["id"]) == 16 for it in a["items"]))
        self.assertEqual(len({it["id"] for it in a["items"]}), len(a["items"]))

    def test_html_and_no_workspace_writes(self):
        before = [_files(r) for r in self.roots]
        self.build()
        self.assertEqual([_files(r) for r in self.roots], before)
        self.assertEqual(sorted(os.listdir(self.out)), [tb.SEEN, tb.SCREEN, tb.DOC])
        with open(os.path.join(self.out, tb.SCREEN), encoding="utf-8") as f:
            html = f.read()
        self.assertNotIn("/*__DATA__*/null", html)
        self.assertNotIn("http", html.lower())
        self.assertEqual(html.count("</script>"), 1)
        self.assertIn("taxonomy_board", html)
        with open(tb.TEMPLATE_PATH, encoding="utf-8") as f:
            tpl = f.read()
        self.assertEqual(tpl.count("/*__DATA__*/null"), 1)
        self.assertNotIn("http", tpl.lower())

    def test_cli_unreadable_taxonomy_exit_0(self):
        bad = os.path.join(self.tmp, "bad.json")
        with open(bad, "w", encoding="utf-8") as f:
            f.write("{}")
        buf = std_io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cli.main(["taxonomy-board", "--workspace", self.roots[0], "--workspace", self.roots[1],
                             "--taxonomy", bad, "--out-dir", self.out])
        text = buf.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("TAXONOMY_READ_FAILED", text)
        self.assertIn("작업 폴더 2", text)
        self.assertNotIn(self.tmp, text)
        with open(os.path.join(self.out, tb.DOC), encoding="utf-8") as f:
            doc = json.load(f)
        self.assertEqual({it["status"] for it in doc["items"]}, {"unknown"})

    def test_cli_unknown_workspace(self):
        buf = std_io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cli.main(["taxonomy-board", "--workspace", os.path.join(self.tmp, "nope"), "--out-dir", self.out])
        self.assertEqual(code, 1)
        self.assertIn("WORKSPACE_NOT_FOUND", buf.getvalue())

    def test_open_unsupported(self):
        self.assertEqual(tb.open_side_by_side("a.html", "b.xlsx", platform="linux"), "OPEN_UNSUPPORTED")

    def test_repo_taxonomy_smoke(self):
        idx, _issues, code = tb.load_taxonomy(tb.DEFAULT_TAXONOMY)
        if not os.path.isfile(tb.DEFAULT_TAXONOMY):
            self.assertEqual(code, "TAXONOMY_MISSING")
            return
        self.assertIsNone(code)
        self.assertTrue(idx["axis_order"])


class RoundOneFixTest(unittest.TestCase):
    """검증 라운드 1 지적 사항."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="domain_engrbot_tboard_r1_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.roots, self.led, self.req = make_sources(self.tmp)
        self.out = os.path.join(self.tmp, "out")

    def build(self, data=None):
        return tb.build(self.roots, None, self.out, ledger_dir=self.led, requests_dir=self.req, now=NOW,
                        taxonomy_bytes=tax_bytes() if data is None else data)

    def item(self, doc, key):
        return [it for it in doc["items"] if it["key"] == key][0]

    def test_1_unused_value_in_use_is_blocked(self):
        doc = self.build()
        kid = self.item(doc, "tax.value.off|공정|식각")
        self.assertEqual((kid["status"], kid["status_note"]), ("blocked", "하위값 1개가 이 값을 씀"))
        q = self.item(doc, "tax.value.off|공정|cmp")
        self.assertEqual((q["status"], q["status_note"]), ("blocked", "질문 Q2가 이 값을 씀"))
        self.assertEqual(self.item(doc, "tax.value.off|상태|정상")["status"], "open")
        self.assertEqual(self.item(doc, "tax.value.off|공정|옛값")["status"], "done")

    def test_2_3_checks_and_valid_lists(self):
        doc = self.build()
        na = self.item(doc, "tax.axis.new|장비")["rows"][0]
        self.assertEqual(na["checks"], {"3": "yn", "4": "yn", "5": "yn", "6": "kind"})
        qn = [it for it in doc["items"] if it["kind"] == "q_new"]
        self.assertTrue(all(it["rows"][0]["checks"] == {"0": "qid_new", "2": "target", "3": "int"} for it in qn))
        self.assertEqual(doc["question_ids"], ["Q1", "Q2"])
        self.assertIn(["공정", "cmp"], doc["targets"])
        self.assertNotIn(["공정", "옛값"], doc["targets"])  # 꺼진 값은 적용 대상이 될 수 없다
        with open(tb.TEMPLATE_PATH, encoding="utf-8") as f:
            tpl = f.read()
        self.assertIn('it.status !== "open"', tpl)          # 묶음 복사는 미반영만(먼저 할 일·확인 불가 제외)
        self.assertIn('it.status === "blocked"', tpl)       # 먼저 할 일 행 복사는 확인 창

    def test_parent_axis_checks_and_bulk_qid_dedup(self):
        doc = self.build()
        adds = [it for it in doc["items"] if it["kind"] == "value_add" and it["action"] == "add"]
        self.assertTrue(adds and all(it["rows"][0]["checks"] == {"2": "parent"} for it in adds))
        terms = [it for it in doc["items"] if it["kind"] == "term"]
        self.assertTrue(all(it["rows"][1]["checks"] == {"0": "axis", "2": "parent"} for it in terms))
        self.assertEqual(doc["axis_names"], ["공정", "상태"])
        self.assertTrue(all(isinstance(a, dict) for a in doc["axes"]))  # 축 카드 지표는 덮이지 않는다
        with open(tb.TEMPLATE_PATH, encoding="utf-8") as f:
            tpl = f.read()
        self.assertIn('rule === "parent"', tpl)
        self.assertIn('rule === "axis"', tpl)
        self.assertIn("qids[q]", tpl)                        # 묶음 복사에서 같은 새 질문 ID는 한 번만

    def test_4_reject_rows_use_original(self):
        doc = self.build()
        need = [it for it in doc["items"] if it["kind"] == "q_new" and not it["rows"][0]["cells"][1]][0]
        self.assertIsNone(need["reject_row"])
        self.assertEqual(need["reject_hint"], tb.HIDE_HINT)
        cand = self.item(doc, "q.new|%s" % tb.model.sha256_text("거절할 질문?")[:16])
        self.assertEqual(cand["reject_row"], ["질문", "거절할 질문?", "", ""])
        self.assertEqual(cand["status"], "rejected")
        with open(tb.TEMPLATE_PATH, encoding="utf-8") as f:
            self.assertNotIn("content_cell", f.read())

    def test_5_seen_hash_uses_edit_cells_whitespace_normalized(self):
        self.build()
        rows = [list(r) for r in TAX_ROWS]
        rows[0][7] = "  공정   정의 "   # 공백만 바뀜
        rows[0][3] = "N"                  # 편집 칸 밖(D)
        doc = self.build(tax_bytes(rows))
        self.assertEqual(self.item(doc, "tax.axis.def|공정")["status"], "open")
        rows[0][8] = "공정 포함을 고쳤다"
        doc = self.build(tax_bytes(rows))
        self.assertEqual(self.item(doc, "tax.axis.def|공정")["status"], "done")

    def test_6_overwrite_keeps_original_cells(self):
        doc = self.build()
        row = self.item(doc, "tax.value.off|공정|식각")["rows"][0]
        self.assertEqual(row["cells"][7], "식각 정의\n둘째 줄")
        self.assertEqual(row["changes"], [{"col": 10, "from": "", "to": "N"}])
        with open(os.path.join(self.out, tb.SCREEN), encoding="utf-8") as f:
            html = f.read()
        m = re.search(r"var DATA = (\{.*?\});\n", html, re.S)
        data = json.loads(m.group(1))
        cells = [it for it in data["items"] if it["key"] == "tax.value.off|공정|식각"][0]["rows"][0]["cells"]
        self.assertEqual(cells[7], "식각 정의\n둘째 줄")
        with open(tb.TEMPLATE_PATH, encoding="utf-8") as f:
            tpl = f.read()
        self.assertIn("function tsvCell", tpl)
        self.assertEqual(tpl.count("tsvRow("), 4)  # 정의 1 + 행 복사·기각 행·묶음 복사

    def test_7_missing_row_place(self):
        doc = self.build()
        q9 = self.item(doc, "q.edit|Q9")
        self.assertEqual(q9["status"], "blocked")
        self.assertIn("대상 행 없음", q9["rows"][0]["place"])
        unread = self.build(b"broken")
        self.assertIn("확인 불가", self.item(unread, "q.edit|Q9")["rows"][0]["place"])

    def test_8_synonym_normalization_single(self):
        doc = self.build()
        same = self.item(doc, "syn|씨엠피|cmp")
        self.assertEqual(same["status"], "done")
        self.assertEqual({c["src"] for c in same["sources"]}, {"S4R", "S6"})
        spaced = self.item(doc, "syn|씨 엠피|cmp")
        self.assertEqual(spaced["status"], "open")
        self.assertFalse(spaced["conflict"])

    def test_9_ledger_dir_from_default_policy(self):
        pol = {"ledger": {"dir": "_domain_engrbot/ledger_alt"}}
        with mock.patch.object(tb.policy_mod, "default_policy", return_value=pol):
            d = tb._ledger_dir([os.path.join(ledger.WORKSPACES_DIR, "x")])
        self.assertEqual(os.path.normcase(d), os.path.normcase(os.path.join(ledger.WORKSPACES_DIR, "_domain_engrbot",
                                                                            "ledger_alt")))

    def test_10_open_requires_readable_xlsx(self):
        self.assertEqual(tb.open_side_by_side("a.html", "b.json", readable=True), "NOT_XLSX")
        self.assertEqual(tb.open_side_by_side("a.html", "b.xlsx", readable=False), "NOT_XLSX")

    def test_11_corrupt_xlsx(self):
        with mock.patch.object(labelbot_ws, "parse_taxonomy_bytes", side_effect=zlib.error("x")), \
                mock.patch.object(labelbot_ws, "taxonomy_raw_rows", side_effect=KeyError("x")):
            doc = self.build()
            bad = os.path.join(self.tmp, "bad.json")
            with open(bad, "w", encoding="utf-8") as f:
                f.write("{}")
            buf = std_io.StringIO()
            with mock.patch.object(labelbot_ws, "read_taxonomy_bytes", return_value=b"PK"), \
                    contextlib.redirect_stdout(buf):
                code = cli.main(["taxonomy-board", "--workspace", self.roots[0], "--taxonomy", bad,
                                 "--out-dir", self.out])
        self.assertEqual(doc["taxonomy"]["read_code"], "TAXONOMY_PARSE_ERROR XLSX_CORRUPT")
        self.assertEqual(doc["taxonomy"]["issues"], [{"sheet": None, "row": None, "code": "XLSX_CORRUPT"}])
        self.assertEqual({it["status"] for it in doc["items"]}, {"unknown"})
        self.assertEqual(code, 0)
        self.assertIn("TAXONOMY_PARSE_ERROR XLSX_CORRUPT", buf.getvalue())
        self.assertNotIn("Traceback", buf.getvalue())
        good = bytearray(tax_bytes())
        for k in range(len(good) // 3, len(good) // 3 + 40):
            good[k] ^= 0x5A
        doc = self.build(bytes(good))  # 실제 손상 bytes도 예외 없이 끝난다
        self.assertIn(doc["taxonomy"]["readable"], (True, False))

    def test_12_out_dir_warning(self):
        self.assertEqual(tb.out_dir_warning(os.path.join(io.CODE_ROOT, "domain_engrbot", "x")), "OUT_DIR_NOT_IGNORED")
        self.assertIsNone(tb.out_dir_warning(tb.OUT_DIR))
        self.assertIsNone(tb.out_dir_warning(self.tmp))

    def test_13_15_axis_order_human_first_disable_last(self):
        doc = self.build()
        kinds = [(it["kind"], tb._rank(it)) for it in doc["items"] if it["group"] == "taxonomy" and it["axis"] == "공정"]
        ranks = [r for _k, r in kinds]
        self.assertEqual(ranks, sorted(ranks))
        self.assertEqual(kinds[-1][0], "value_off")
        self.assertEqual(kinds[0][1], 0)
        with open(tb.TEMPLATE_PATH, encoding="utf-8") as f:
            tpl = f.read()
        self.assertIn("덮어쓰기 전체", tpl)
        self.assertIn("바뀌는 칸: ", tpl)
        self.assertIn("scrollTables()", tpl)

    def test_16_polite_tone(self):
        doc = self.build()
        texts = [doc["notes"]["revisit_file"], tb.OTHER_WHERE, tb.ENGR_REJECT_HINT, tb.HIDE_HINT]
        for it in doc["items"]:
            texts += [it["status_note"] or "", it["reject_hint"] or ""] + [r["label"] or "" for r in it["rows"]]
        plain = re.compile(r"(?<!니)다(\)|\.|$)")
        self.assertEqual([t for t in texts if plain.search(t)], [])


def _s7(kind, at, **kw):
    """taxonomy_proposals.jsonl 행(answers.apply가 쓰는 4.4절 형식)."""
    row = {"proposal_id": "QP-%012d" % len(kw), "set_id": "QS-20261006T010203-ab12", "question_id": "EQ-0123456789",
           "at": at, "kind": kind, "axis": "", "value": "", "values": [], "parent": "", "name": "", "alias": "",
           "canonical": "", "qid": "", "text": "", "definition": "", "include": "", "exclude": "", "memo": "",
           "origin": "edited"}
    row.update(kw)
    return row


S7_ROWS = [
    _s7("value_def", "2026-10-06T01:00:00Z", axis="공정", value="CMP", definition="옛 CMP 정의"),
    _s7("value_def", "2026-10-06T03:00:00Z", axis="공정", value="CMP", definition="새 CMP 정의", include="CMP 포함 새"),
    _s7("value_def", "2026-10-06T02:00:00Z", axis="공정", value="CMP", definition="중간 CMP 정의"),
    _s7("value_add", "2026-10-06T01:00:00Z", axis="공정", value="증착", parent="식각", definition="증착 정의",
        exclude="증착 제외"),
    _s7("q_edit", "2026-10-06T01:00:00Z", qid="Q1", text="결함이 보입니까?"),
    _s7("synonym", "2026-10-06T01:00:00Z", alias="엠씨", canonical="CMP", memo="답변 메모"),
    _s7("overlap", "2026-10-06T01:00:00Z", axis="공정", values=["식각", "CMP"], definition="쓰지 않는 정의",
        memo="겹침 메모"),
    _s7("new_axis", "2026-10-06T01:00:00Z", name="장비", definition="장비 정의", include="장비 포함"),
    _s7("q_new", "2026-10-06T01:00:00Z", text="새 질문입니까?"),
    _s7("axis_def", "2026-10-06T01:00:00Z", axis="상태", definition="상태 정의"),
    _s7("bogus", "2026-10-06T01:00:00Z"),
    _s7("value_def", "2026-10-06T01:00:00Z", axis="공정"),                 # 필수 칸(value) 없음
    _s7("overlap", "2026-10-06T01:00:00Z", axis="공정", values=["식각"]),  # values 2개가 아님
]


class S7Test(unittest.TestCase):
    """출처 S7(엔지니어 답변): 질문 폴더 taxonomy_proposals.jsonl → 항목과 붙여넣기 행의 문장 칸."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="domain_engrbot_tboard_s7_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.roots, self.led, self.req = make_sources(self.tmp)
        self.out = os.path.join(self.tmp, "out")
        self.qd = os.path.join(self.tmp, "questions")
        _jsonl(os.path.join(self.qd, "taxonomy_proposals.jsonl"), S7_ROWS)

    def build(self, qd="default", out=None):
        return tb.build(self.roots, None, out or self.out, ledger_dir=self.led, requests_dir=self.req, now=NOW,
                        taxonomy_bytes=tax_bytes(), questions_dir=self.qd if qd == "default" else qd)

    def item(self, doc, key):
        found = [it for it in doc["items"] if it["key"] == key]
        self.assertEqual(len(found), 1, key)
        return found[0]

    def test_s7_items_and_latest_sentence(self):
        doc = self.build()
        vd = self.item(doc, "tax.value.def|공정|cmp")
        self.assertEqual([c["src"] for c in vd["sources"]], ["S7"])
        self.assertEqual((vd["sources"][0]["label"], vd["sources"][0]["n"]), ("엔지니어 답변", 3))
        add_row, row = vd["rows"]   # 같은 값 행 추가(정의를 합쳐 씀)가 먼저, 덮어쓰기가 대안
        self.assertEqual(add_row["cells"], ["공정", "CMP", "", "", "", "", "", "새 CMP 정의", "CMP 포함 새", "", ""])
        self.assertEqual(add_row["target"], {"mode": "append", "row": None})
        self.assertIn("3행 정의와 함께", add_row["label"])
        self.assertEqual((row["cells"][7], row["cells"][8], row["cells"][9]), ("새 CMP 정의", "CMP 포함 새", ""))
        self.assertEqual(row["changes"], [{"col": 7, "from": "CMP 정의", "to": "새 CMP 정의"},
                                          {"col": 8, "from": "", "to": "CMP 포함 새"}])
        self.assertEqual(row["target"], {"mode": "overwrite", "row": 3})
        self.assertIn("덮어쓰기", row["label"])
        self.assertEqual(vd["status"], "open")
        # 추가 행을 붙이면(같은 값 둘째 행) 시트가 그대로 읽히고 반영됨이 된다
        rows = TAX_ROWS + [add_row["cells"]]
        done = tb.build(self.roots, None, os.path.join(self.tmp, "out_add"), ledger_dir=self.led,
                        requests_dir=self.req, now=NOW, taxonomy_bytes=tax_bytes(rows), questions_dir=self.qd)
        self.assertEqual(done["taxonomy"]["issues"], [])
        self.assertEqual(self.item(done, "tax.value.def|공정|cmp")["status"], "done")
        add = self.item(doc, "tax.value.add|공정|증착")
        self.assertEqual({c["src"] for c in add["sources"]}, {"S1", "S4", "S5", "S7"})
        self.assertEqual(add["rows"][0]["cells"], ["공정", "증착", "식각", "", "", "", "", "증착 정의", "", "증착 제외", ""])
        self.assertEqual(tb._rank(add), 0)
        qe = self.item(doc, "q.edit|Q1")
        self.assertEqual(qe["rows"][0]["cells"][1], "결함이 보입니까?")
        self.assertEqual(qe["rows"][0]["changes"], [{"col": 1, "from": "결함이 있나?", "to": "결함이 보입니까?"}])
        self.assertEqual(self.item(doc, "syn|엠씨|cmp")["rows"][0]["cells"], ["엠씨", "CMP", "답변 메모"])
        ov = self.item(doc, "tax.value.overlap|공정|cmp|식각")
        self.assertIn("겹침 메모", ov["context"]["memos"])
        self.assertEqual([r["changes"] for r in ov["rows"]], [[], []])   # overlap은 칸을 채우지 않는다
        self.assertIsNone(ov["rows"][0]["label"])
        na = self.item(doc, "tax.axis.new|장비")
        self.assertEqual((na["rows"][0]["cells"][7], na["rows"][0]["cells"][8]), ("장비 정의", "장비 포함"))
        qn = self.item(doc, "q.new|%s" % tb.model.sha256_text("새 질문입니까?")[:16])
        self.assertEqual(qn["rows"][0]["cells"][1], "새 질문입니까?")
        # 답변 문장이 이미 시트와 같으면 반영됨
        ad = self.item(doc, "tax.axis.def|상태")
        self.assertEqual((ad["status"], ad["status_note"]), ("done", "답변 문장이 시트에 있음(6행)"))
        self.assertEqual(doc["sources"]["S7"], 10)
        self.assertEqual(doc["source_rows_invalid"], 3)
        plain = re.compile(r"(?<!니)다(\)|\.|$)")
        texts = [it["status_note"] or "" for it in doc["items"]] + [r["label"] or "" for it in doc["items"]
                                                                    for r in it["rows"]]
        self.assertEqual([t for t in texts if plain.search(t)], [])

    def test_s7_pasted_is_done(self):
        """S7 문장을 시트에 붙여 넣으면 반영됨으로 본다."""
        rows = [list(r) for r in TAX_ROWS]
        rows[1][7], rows[1][8] = "새 CMP 정의", "CMP 포함 새"
        doc = tb.build(self.roots, None, self.out, ledger_dir=self.led, requests_dir=self.req, now=NOW,
                       taxonomy_bytes=tax_bytes(rows), questions_dir=self.qd)
        it = self.item(doc, "tax.value.def|공정|cmp")
        self.assertEqual((it["status"], it["rows"][0]["changes"]), ("done", []))

    def test_without_s7_output_unchanged(self):
        """S7이 없으면(질문 폴더 없음·빈 질문 폴더) 출력은 questions_dir를 주지 않은 것과 같다."""
        base = self.build(qd=None, out=os.path.join(self.tmp, "o1"))
        empty = os.path.join(self.tmp, "empty_q")
        os.makedirs(empty)
        for qd, out in ((empty, "o2"), (os.path.join(self.tmp, "nope"), "o3")):
            got = self.build(qd=qd, out=os.path.join(self.tmp, out))
            self.assertEqual(got, base)
            with open(os.path.join(self.tmp, "o1", tb.SCREEN), encoding="utf-8") as f1, \
                    open(os.path.join(self.tmp, out, tb.SCREEN), encoding="utf-8") as f2:
                self.assertEqual(f1.read(), f2.read())
        self.assertEqual(base["sources"]["S7"], 0)

    def test_cli_reads_default_questions_dir(self):
        """main_cli는 장부 폴더의 형제 questions에서 S7을 읽고 콘솔 출처 건수에 S7을 낸다."""
        qd = tb.qmodel.qdir(tb._ledger_dir(self.roots))
        _jsonl(os.path.join(qd, "taxonomy_proposals.jsonl"), S7_ROWS[:2])
        bad = os.path.join(self.tmp, "bad.json")
        with open(bad, "w", encoding="utf-8") as f:
            f.write("{}")
        buf = std_io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cli.main(["taxonomy-board", "--workspace", self.roots[0], "--workspace", self.roots[1],
                             "--taxonomy", bad, "--out-dir", self.out])
        self.assertEqual(code, 0)
        self.assertRegex(buf.getvalue(), r"출처 S1 \d+·S2 \d+·S3 \d+·S4 \d+·S5 \d+·S6 \d+·S7 2\n")
        for t in ("옛 CMP 정의", "새 CMP 정의"):
            self.assertNotIn(t, buf.getvalue())


class FinalizeTest(unittest.TestCase):
    """'최종 완료': 반영함·기각함 확정(decisions.json) → 상태 갱신, 표시 안 한 항목은 그대로, 보드 서버 왕복."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="domain_engrbot_tboard_fin_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.roots, self.led, self.req = make_sources(self.tmp)
        self.out = os.path.join(self.tmp, "out")

    def build(self):
        return tb.build(self.roots, None, self.out, ledger_dir=self.led, requests_dir=self.req, now=NOW,
                        taxonomy_bytes=tax_bytes())

    def test_decisions_update_status_and_keep_the_rest(self):
        doc = self.build()
        opens = [it for it in doc["items"] if it["status"] == "open"]
        a, r = opens[0], opens[1]
        self.assertEqual(tb.record_decisions(self.out, {a["id"]: "applied", r["id"]: "rejected"}), 2)
        doc2 = self.build()
        by = {it["id"]: it for it in doc2["items"]}
        self.assertEqual((by[a["id"]]["status"], by[a["id"]]["human"]["unverified"]), ("done", True))
        self.assertEqual(by[r["id"]]["status"], "rejected")
        self.assertEqual(doc2["counts"]["open"], doc["counts"]["open"] - 2, "표시 안 한 항목은 미반영으로 남는다")
        tb.record_decisions(self.out, {a["id"]: None})   # 확정 취소 → 시트 기준으로 다시 판정
        self.assertEqual({it["id"]: it for it in self.build()["items"]}[a["id"]]["status"], "open")
        with self.assertRaises(ValueError):
            tb.record_decisions(self.out, {"0" * 16: "applied"})
        with self.assertRaises(ValueError):
            tb.record_decisions(self.out, {a["id"]: "maybe"})

    def test_new_source_reopens_decided_item(self):
        doc = self.build()
        it = next(i for i in doc["items"] if i["status"] == "open")
        decisions = {it["id"]: {"decision": "rejected", "at": "t", "prints": _prints_minus_one(it)}}
        items = [dict(it, status="open")]
        self.assertEqual(tb.apply_decisions(items, decisions), {})
        self.assertEqual(items[0]["status"], "open")

    def test_board_server_finalize_roundtrip(self):
        import http.client
        import threading
        from domain_engrbot import serve
        doc = self.build()
        target = next(it for it in doc["items"] if it["status"] == "open")

        def rebuild():
            return self.build()["counts"]
        srv = serve.make_board_server(os.path.join(self.out, tb.SCREEN), lambda m: tb.record_decisions(self.out, m),
                                      rebuild, 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        port = srv.server_address[1]
        host = "127.0.0.1:%d" % port

        def post(body, origin=True):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            raw = json.dumps(body).encode("utf-8")
            hdr = {"Content-Type": "application/json", "Host": host}
            if origin:
                hdr["Origin"] = "x://" + host
            c.request("POST", "/board/finalize", raw, hdr)
            r = c.getresponse()
            return r.status, json.loads(r.read().decode("utf-8"))

        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        c.request("GET", "/", headers={"Host": host})
        self.assertEqual(c.getresponse().status, 200)
        self.assertEqual(post({"kind": "taxonomy_board_decisions", "marks": {target["id"]: "applied"}}, origin=False)[0], 403)
        self.assertEqual(post({"kind": "x", "marks": {}})[0], 400)
        st, body = post({"kind": "taxonomy_board_decisions", "marks": {target["id"]: "applied"}})
        self.assertEqual((st, body["ok"], body["changed"]), (200, True, 1))
        self.assertEqual(body["counts"]["open"], doc["counts"]["open"] - 1)
        with open(os.path.join(self.out, tb.DECISIONS), encoding="utf-8") as f:
            self.assertEqual(json.load(f)[target["id"]]["decision"], "applied")


def _prints_minus_one(it):
    """확정 당시에는 지금 출처 하나가 없었던 것처럼(= 새 출처가 붙음) 지문 목록을 만든다."""
    return tb._prints(it)[1:]


class EvidenceTest(unittest.TestCase):
    """제안 이유(whys)와 근거 슬라이드(slides): 작업 폴더 work.sqlite에서 파일명·슬라이드·미리보기를 찾는다."""

    def setUp(self):
        import base64
        import sqlite3
        from domain_engrbot.tests import test_ledger as tl
        self.tl = tl
        self.tmp = tempfile.mkdtemp(prefix="domain_engrbot_tboard_ev_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = tl.build_ws(self.tmp, "wsE")
        con = sqlite3.connect(os.path.join(self.root, "work.sqlite"))
        try:
            fid, seq, th = con.execute("SELECT file_id, seq, text_hash FROM chunks WHERE chunk_id=?",
                                       (tl.cid_of(2),)).fetchone()
            con.execute("INSERT INTO slide_images(chunk_id, file_id, seq, jpg_sha256, rel_file, text_hash)"
                        " VALUES(?,?,?,?,?,?)", (tl.cid_of(2), fid, seq, "p2", "slide_images/p2.b64", th))
            con.commit()
        finally:
            con.close()
        self.seq2 = seq
        self.jpg = b"\xff\xd8\xff\xe0 ev-preview \xff\xd9"
        io.write_text(os.path.join(self.root, "slide_images", "p2.b64"), base64.b64encode(self.jpg).decode("ascii"))
        _jsonl(os.path.join(self.root, "reports", "candidates.jsonl"), [
            {"kind": "new_value", "content": "공정|증착", "freq": 2, "run_id": "RUN-A", "source": "bot",
             "evidence": "TaN 증착 조건", "examples": [tl.cid_of(2), "0000000000000000:slide99"]}])
        _jsonl(os.path.join(self.root, "reports", "taxonomy_revisit.jsonl"), [
            {"review_run_id": "RUN-A", "chunk_id": tl.cid_of(10), "target": "axis", "key": "공정",
             "reason": "NO_FIT_VALUE", "proposed": {"value": "증착"}, "bot_value": ["CMP"], "memo": ""}])
        self.out = os.path.join(self.tmp, "out")

    def test_whys_and_slides(self):
        doc = tb.build([self.root], None, self.out, now=NOW, taxonomy_bytes=tax_bytes())
        it = next(i for i in doc["items"] if i["key"] == "tax.value.add|공정|증착")
        ev = it["evidence"]
        self.assertIn({"label": "labelbot 후보", "text": "근거 문구: TaN 증착 조건"}, ev["whys"])
        self.assertIn({"label": "재검토 요청", "text": "맞는 값이 없음 (봇 값: CMP)"}, ev["whys"])
        self.assertNotIn("refs", ev)
        by = {s["chunk_id"]: s for s in ev["slides"]}
        self.assertEqual(set(by), {self.tl.cid_of(2), "0000000000000000:slide99", self.tl.cid_of(10)})
        s2 = by[self.tl.cid_of(2)]
        self.assertTrue(s2["found"])
        self.assertEqual(s2["file"], self.tl.FILE_NAME)
        self.assertEqual(s2["slide_no"], self.seq2)
        self.assertEqual(s2["preview"], "wsE|" + self.tl.cid_of(2))
        self.assertTrue(doc["previews"][s2["preview"]].startswith("data:image/jpeg;base64,"))
        self.assertEqual(list(doc["previews"]), [s2["preview"]], "같은 슬라이드 미리보기는 한 번만 넣는다")
        self.assertIsNone(by[self.tl.cid_of(10)]["preview"], "미리보기 파일이 없는 chunk")
        self.assertFalse(by["0000000000000000:slide99"]["found"])
        self.assertEqual(it["context"]["metrics"], [], "근거 슬라이드가 있으면 예시 건수 줄을 내지 않는다")

    def test_s7_slides_from_question_refs(self):
        led = os.path.join(self.tmp, "_domain_engrbot", "ledger")
        qd = os.path.join(self.tmp, "_domain_engrbot", "questions")
        _jsonl(os.path.join(led, ledger.CASES), [
            {"case_id": c, "record_id": self.tl.cid_of(2), "source_ws": "wsE", "labeler_run_id": "RUN-A", "field": f,
             "kind": "CHANGE"} for c, f in (("c1", "axis:공정"), ("c2", "axis:상태"))])
        _json(os.path.join(qd, "asked.json"), {"version": 1, "dismissed": {}, "answered": {
            "fp1": {"question_id": "EQ-1", "set_id": "QS-x", "at": "t", "refs": ["c1", "c2", "FR-9"]}}})
        _jsonl(os.path.join(qd, "taxonomy_proposals.jsonl"), [
            {"kind": "axis_def", "axis": "상태", "definition": "새 정의", "memo": "엔지니어 설명",
             "question_id": "EQ-1", "set_id": "QS-x", "at": "2026-10-05T00:00:00Z"}])
        doc = tb.build([self.root], None, self.out, ledger_dir=led, now=NOW, taxonomy_bytes=tax_bytes(),
                       questions_dir=qd)
        it = next(i for i in doc["items"] if i["key"].startswith("tax.axis.def|"))
        self.assertEqual([s["chunk_id"] for s in it["evidence"]["slides"]], [self.tl.cid_of(2)])
        self.assertTrue(it["evidence"]["slides"][0]["preview"])
        self.assertEqual(it["context"]["memo_labels"], ["엔지니어 메모"])

    def test_ppt_part_slide_number_and_missing_db(self):
        self.assertEqual(tb._slide_no("abc:ppt/slides/slide12.xml", 3), (12, True))
        self.assertEqual(tb._slide_no("abc:section-002", 4), (4, False))
        os.remove(os.path.join(self.root, "work.sqlite"))
        doc = tb.build([self.root], None, self.out, now=NOW, taxonomy_bytes=tax_bytes())
        it = next(i for i in doc["items"] if i["key"] == "tax.value.add|공정|증착")
        self.assertTrue(it["evidence"]["slides"])
        self.assertTrue(all(not s["found"] and s["preview"] is None for s in it["evidence"]["slides"]))


if __name__ == "__main__":
    unittest.main()
