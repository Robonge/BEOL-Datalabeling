"""taxonomy 수정 보드 테스트: 출처 병합, 행 초안, 상태 판정, 검증 오류, 결정성, 화면, CLI, 반영(미리보기·쓰기).

taxonomy는 메모리에서 만든 taxonomy.json bytes를 주입하거나, 반영 테스트에서는 임시 폴더에 쓴 taxonomy.json을 쓴다.
작업 폴더·장부·재검토 파일은 코드 폴더 밖 임시 폴더에 만든다. 저장소 taxonomy.json은 읽지 않는다.
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
from unittest import mock

from domain_engrbot import cli, io, ledger, taxonomy_board as tb

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


Q_HEAD = ["질문 ID", "문장", "적용 대상", "우선순위"]
REJ_HEAD = ["종류", "내용", "기각일", "사유", "출처"]


def _objs(head, rows):
    return [dict(zip(head, r + [""] * (len(head) - len(r)))) for r in rows]


def tax_doc(rows=None, questions_head=None):
    """테스트용 taxonomy.json 문서(행 객체 목록). 행 번호 = index + 2."""
    return {"version": 1,
            "taxonomy": _objs(TAX_HEAD, rows or TAX_ROWS),
            "questions": _objs(questions_head or Q_HEAD, [["Q1", "결함이 있나?", "공통", "1"],
                                                          ["Q2", "CMP 공정인가?", "공정=CMP", "2"]]),
            "synonyms": _objs(["동의어", "표준어", "메모"], [["씨엠피", "CMP", ""]]),
            "rejected": _objs(REJ_HEAD, [["값", "공정|거절값", "2026-10-01", ""], ["질문", "거절할 질문?", "2026-10-01", ""]])}


def tax_bytes(rows=None, questions_head=None):
    return json.dumps(tax_doc(rows, questions_head), ensure_ascii=False, indent=1).encode("utf-8")


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
        _cand("synonym", "식각기|식각", source="review"),  # 사람 등록(봇 후보면 엄밀 기준에서 빠진다)
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
        """대상 행이 있으면 엔지니어 답변이 없어도 늘 '새 행으로 추가'와 '덮어쓰기' 둘을 준다(R2)."""
        it = self.item(self.build(), "tax.axis.def|공정")
        self.assertEqual((it["pick"], [r["target"]["mode"] for r in it["rows"]]), ("one", ["append", "overwrite"]))
        self.assertEqual(it["rows"][0]["cells"], ["공정"] + [""] * 10)
        row = it["rows"][1]
        self.assertEqual(row["editable"], [7, 8, 9])
        self.assertEqual(row["cells"], TAX_ROWS[0])
        self.assertEqual(row["target"], {"mode": "overwrite", "row": 2})
        self.assertTrue(any("비율" in m for m in it["context"]["metrics"]))

    def test_value_definition_offers_both_without_answer(self):
        """값 정의 보완도 엔지니어 답변(S7) 없이 대상 행이 있으면 '새 행으로 추가'·'덮어쓰기' 둘을 준다."""
        path = os.path.join(self.roots[1], "reports", "taxonomy_revisit.jsonl")
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(_revisit("c6", "axis", "공정", "AMBIGUOUS_DEF", related=["식각"]), ensure_ascii=False) + "\n")
        it = self.item(self.build(), "tax.value.def|공정|식각")
        self.assertEqual((it["pick"], [r["target"]["mode"] for r in it["rows"]]), ("one", ["append", "overwrite"]))
        self.assertEqual(it["rows"][0]["cells"], ["공정", "식각"] + [""] * 9)
        self.assertEqual(it["rows"][1]["target"]["row"], 4)
        self.assertIn("4행", it["rows"][0]["label"])

    def test_status_sheet(self):
        doc = self.build()
        self.assertEqual(self.item(doc, "tax.value.add|공정|cmp")["status"], "done")
        self.assertEqual(self.item(doc, "tax.value.add|공정|거절값")["status"], "rejected")
        self.assertEqual(self.item(doc, "tax.value.add|없는축|값")["status"], "blocked")
        off = self.item(doc, "tax.value.add|공정|옛값")
        self.assertEqual((off["status"], off["status_note"]), ("open", "꺼진 값을 다시 켭니다(5행)"))
        self.assertEqual(off["action"], "overwrite")
        self.assertEqual(off["rows"][0]["target"], {"mode": "overwrite", "row": 5})
        self.assertEqual(off["rows"][0]["cells"][10], "")
        self.assertEqual(self.item(doc, "syn|씨엠피|cmp")["status"], "done")

    def test_edit_items_open_until_board_decision(self):
        """문장 수정 항목은 행이 바뀌어도 추측하지 않는다(seen.json 지문 없음). 보드 확정으로만 반영됨이 된다."""
        doc = self.build()
        self.assertEqual(self.item(doc, "tax.axis.def|공정")["status"], "open")
        rows = [list(r) for r in TAX_ROWS]
        rows[0][7] = "공정 정의를 고쳤다"
        doc = self.build(tax_bytes(rows))
        self.assertEqual(self.item(doc, "tax.axis.def|공정")["status"], "open")
        self.assertFalse(os.path.exists(os.path.join(self.out, "seen.json")))

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

    def test_cells_are_raw_text(self):
        """Excel 붙여넣기용 표시(수식 앞 ')는 없다. 칸은 원문 그대로다."""
        it = self.item(self.build(), "tax.value.add|공정|=수식")
        self.assertEqual(it["rows"][0]["cells"][1], "=수식")
        self.assertEqual(it["reject_row"], ["값", "공정|=수식", "", ""])

    def test_parse_error_unknown(self):
        doc = self.build(b"not json")
        self.assertFalse(doc["taxonomy"]["readable"])
        self.assertEqual(doc["taxonomy"]["read_code"], "TAXONOMY_PARSE_ERROR TAXONOMY_JSON_INVALID")
        self.assertEqual(doc["taxonomy"]["issues"], [{"sheet": None, "row": None, "code": "TAXONOMY_JSON_INVALID"}])
        self.assertTrue(doc["items"])
        self.assertEqual({it["status"] for it in doc["items"]}, {"unknown"})
        self.assertEqual(doc["taxonomy"]["version"], tb.hashlib.sha256(b"not json").hexdigest())

    def test_validation_error_still_judged(self):
        doc = self.build(tax_bytes(questions_head=["질문", "문장", "적용 대상", "우선순위"]))
        self.assertTrue(doc["taxonomy"]["readable"])
        self.assertIn("QUESTION_ID_EMPTY", {i["code"] for i in doc["taxonomy"]["issues"]})
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
        with open(os.path.join(self.out, tb.CLEARED), encoding="utf-8") as f:
            cleared = json.load(f)
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
        self.assertEqual(sorted(os.listdir(self.out)), [tb.SCREEN, tb.DOC])
        with open(os.path.join(self.out, tb.SCREEN), encoding="utf-8") as f:
            html = f.read()
        self.assertNotIn("/*__DATA__*/null", html)
        self.assertNotIn("http", html.lower().replace("http-equiv", ""))   # 외부 주소 없음(CSP meta 속성 이름만 뺀다)
        self.assertEqual(html.count("</script>"), 1)
        self.assertIn("taxonomy_board", html)
        with open(tb.TEMPLATE_PATH, encoding="utf-8") as f:
            tpl = f.read()
        self.assertEqual(tpl.count("/*__DATA__*/null"), 1)
        self.assertNotIn("http", tpl.lower().replace("http-equiv", ""))

    def test_cli_unreadable_taxonomy_exit_0(self):
        bad = os.path.join(self.tmp, "bad.json")
        with open(bad, "w", encoding="utf-8") as f:
            f.write("not json")
        buf = std_io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cli.main(["taxonomy-board", "--workspace", self.roots[0], "--workspace", self.roots[1],
                             "--taxonomy", bad, "--out-dir", self.out])
        text = buf.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("TAXONOMY_PARSE_ERROR TAXONOMY_JSON_INVALID", text)
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

    def test_open_board_uses_browser(self):
        with mock.patch.object(tb.webbrowser, "open", return_value=True) as op:
            self.assertIsNone(tb.open_board("http://127.0.0.1:8795/"))
            self.assertIsNone(tb.open_board(os.path.join(self.tmp, "taxonomy_board.html")))
        self.assertEqual(op.call_args_list[0][0][0], "http://127.0.0.1:8795/")
        self.assertTrue(op.call_args_list[1][0][0].startswith("file:"))
        with mock.patch.object(tb.webbrowser, "open", return_value=False):
            self.assertEqual(tb.open_board("http://127.0.0.1:1/"), "BROWSER_NOT_FOUND")
        self.assertFalse(hasattr(tb, "open_side_by_side"))

    def test_default_taxonomy_is_json(self):
        self.assertEqual(os.path.basename(tb.DEFAULT_TAXONOMY), "taxonomy.json")
        self.assertEqual(tb.load_taxonomy(os.path.join(self.tmp, "none.json"))[2], "TAXONOMY_MISSING")


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
        self.assertIn('it.status !== "open"', tpl)          # 반영함은 미반영만
        self.assertIn('it.status === "blocked"', tpl)       # 먼저 할 일은 기각만

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
        for gone in ("tsvRow", "copyText", "행 복사", "기각 행 복사", "Excel", "xlsx", "시트 미확인"):
            self.assertNotIn(gone, tpl)
        for need in ("board/preview", "board/finalize", "base_version", "prefers-color-scheme:dark", 'type = "radio"'):
            self.assertIn(need, tpl)

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

    def test_11_corrupt_json(self):
        good = bytearray(tax_bytes())
        for k in range(len(good) // 3, len(good) // 3 + 40):
            good[k] ^= 0x5A
        doc = self.build(bytes(good))  # 손상 bytes도 예외 없이 끝난다
        self.assertFalse(doc["taxonomy"]["readable"])
        self.assertEqual({it["status"] for it in doc["items"]}, {"unknown"})
        doc = self.build(json.dumps({"taxonomy": "x"}).encode("utf-8"))   # 구조 오류: 행 목록이 아님
        self.assertIn("TAXONOMY_JSON_INVALID", {i["code"] for i in doc["taxonomy"]["issues"]})

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
    """출처 S7(엔지니어 답변): 질문 폴더 taxonomy_proposals.jsonl → 항목과 행 초안의 문장 칸."""

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
        self.assertEqual((ad["status"], ad["status_note"]), ("done", "답변 문장이 taxonomy에 있음(6행)"))
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
        self.assertEqual((by[a["id"]]["status"], by[a["id"]]["status_note"]), ("done", "보드에서 반영함"))
        self.assertNotIn("unverified", by[a["id"]]["human"])
        self.assertEqual(by[r["id"]]["status"], "rejected")
        self.assertEqual(doc2["counts"]["open"], doc["counts"]["open"] - 2, "표시 안 한 항목은 미반영으로 남는다")
        tb.record_decisions(self.out, {a["id"]: None})   # 확정 취소 → 다시 판정
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


def _prints_minus_one(it):
    """확정 당시에는 지금 출처 하나가 없었던 것처럼(= 새 출처가 붙음) 지문 목록을 만든다."""
    return tb._prints(it)[1:]


class ApplyTest(unittest.TestCase):
    """반영: 카드 편집·반영함·기각 → 미리보기(/board/preview) → taxonomy.json 쓰기(/board/finalize)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="domain_engrbot_tboard_apply_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.roots, self.led, self.req = make_sources(self.tmp)
        self.out = os.path.join(self.tmp, "out")
        self.tax = os.path.join(self.tmp, "tax", "taxonomy.json")
        self.hist = os.path.join(self.tmp, "tax", "taxonomy_history.jsonl")
        self.write_tax()

    def write_tax(self, rows=None, data=None):
        os.makedirs(os.path.dirname(self.tax), exist_ok=True)
        with open(self.tax, "wb") as f:
            f.write(data if data is not None else tax_bytes(rows))

    def file_bytes(self):
        with open(self.tax, "rb") as f:
            return f.read()

    def file_doc(self):
        return json.loads(self.file_bytes().decode("utf-8"))

    def build(self, qd=None):
        return tb.build(self.roots, self.tax, self.out, ledger_dir=self.led, requests_dir=self.req, now=NOW,
                        questions_dir=qd)

    def item(self, doc, key):
        found = [it for it in doc["items"] if it["key"] == key]
        self.assertEqual(len(found), 1, key)
        return found[0]

    def payload(self, doc, marks, edits=None, base=None):
        return {"kind": tb.DECISIONS_KIND, "base_version": doc["taxonomy"]["version"] if base is None else base,
                "marks": marks, "edits": edits or {}}

    def apply(self, doc, marks, edits=None, preview=False, base=None):
        return tb.apply_marks(self.out, self.tax, self.payload(doc, marks, edits, base), preview, now=NOW)

    def refused(self, code, doc, marks, edits=None, preview=True, base=None):
        with self.assertRaises(tb.BoardRefused) as cm:
            self.apply(doc, marks, edits, preview, base)
        self.assertEqual(cm.exception.code, code)
        return cm.exception

    def standard(self, doc):
        """값 추가 1, 끄기 1, 용어(동의어 행 선택) 1, 동의어 기각 1."""
        add, off = self.item(doc, "tax.value.add|공정|증착"), self.item(doc, "tax.value.off|상태|정상")
        syn, term = self.item(doc, "syn|씨 엠피|cmp"), self.item(doc, "term|플라즈마")
        marks = {add["id"]: "applied", off["id"]: "applied", term["id"]: "applied", syn["id"]: "rejected"}
        edits = {term["id"]: {"choice": 0, "rows": [["플라즈마", "CMP", "후보"], [""] * 11]}}
        return marks, edits, syn

    def test_preview_lists_rows_and_writes_nothing(self):
        doc = self.build()
        before = self.file_bytes()
        marks, edits, syn = self.standard(doc)
        res = self.apply(doc, marks, edits, preview=True)
        self.assertEqual((res["ok"], res["issues"], res["version"]), (True, [], doc["taxonomy"]["version"]))
        got = {(d["sheet"], d["op"], d["row"]) for d in res["diff"]}
        self.assertEqual(got, {("taxonomy", "add", 9), ("taxonomy", "edit", 7), ("synonyms", "add", 3),
                               ("rejected", "add", 4)})
        by = {(d["sheet"], d["op"]): d for d in res["diff"]}
        self.assertEqual((by[("taxonomy", "add")]["after"]["축"], by[("taxonomy", "add")]["after"]["값"]), ("공정", "증착"))
        self.assertEqual((by[("taxonomy", "edit")]["before"]["사용 여부"], by[("taxonomy", "edit")]["after"]["사용 여부"]),
                         ("", "N"))
        self.assertEqual(by[("rejected", "add")]["after"], {"종류": "동의어", "내용": "씨 엠피|CMP", "기각일": "2026-10-05",
                                                           "사유": "보드에서 기각", "출처": syn["id"]})
        self.assertEqual(self.file_bytes(), before)
        self.assertFalse(os.path.exists(self.hist))
        self.assertFalse(os.path.exists(os.path.join(self.out, tb.DECISIONS)))

    def test_finalize_writes_history_and_rebuild_shows_status(self):
        doc = self.build()
        old = self.file_doc()
        marks, edits, syn = self.standard(doc)
        res = self.apply(doc, marks, edits)
        self.assertEqual((res["ok"], res["changed"], res["written"]), (True, 4, 4))
        self.assertEqual(res["version"], tb.hashlib.sha256(self.file_bytes()).hexdigest())
        new = self.file_doc()
        self.assertEqual((new["taxonomy"][-1]["축"], new["taxonomy"][-1]["값"]), ("공정", "증착"))
        self.assertEqual(new["taxonomy"][5]["사용 여부"], "N")
        self.assertEqual(new["synonyms"][-1], {"동의어": "플라즈마", "표준어": "CMP", "메모": "후보"})
        with open(self.hist, encoding="utf-8") as f:
            lines = [json.loads(x) for x in f.read().splitlines() if x.strip()]
        self.assertEqual(len(lines), 1)
        self.assertEqual((lines[0]["by"], lines[0]["version"]), ("board", doc["taxonomy"]["version"]))
        self.assertEqual(lines[0]["doc"]["taxonomy"], old["taxonomy"])
        doc2 = self.build()
        self.assertEqual(doc2["taxonomy"]["version"], res["version"])
        self.assertEqual(self.item(doc2, "tax.value.add|공정|증착")["status"], "done")
        self.assertEqual(self.item(doc2, "tax.value.off|상태|정상")["status"], "done")
        self.assertEqual(self.item(doc2, "term|플라즈마")["status"], "done")
        self.assertEqual(self.item(doc2, "syn|씨 엠피|cmp")["status"], "rejected")
        # 새 버전으로 다시 반영할 수 있다(두 번째 최종 완료가 늘 409가 되지 않는다)
        ax = self.item(doc2, "tax.axis.def|공정")
        self.assertTrue(self.apply(doc2, {ax["id"]: "rejected"})["ok"])

    def test_version_conflict_409_and_board_rebuilt(self):
        doc = self.build()
        marks, edits, _syn = self.standard(doc)
        e = self.refused("TAXONOMY_CHANGED", doc, marks, edits, base="0" * 64)
        self.assertEqual(e.status, 409)
        # 다른 화면이 저장해 파일이 바뀌면 보드의 버전도 맞지 않는다
        rows = [list(r) for r in TAX_ROWS]
        rows[0][7] = "편집기가 고친 정의"
        self.write_tax(rows)
        before = self.file_bytes()
        self.refused("TAXONOMY_CHANGED", doc, marks, edits, preview=False)
        self.assertEqual(self.file_bytes(), before)
        preview, _finalize = tb.board_handlers(self.out, self.tax, lambda: self.build()["counts"], now=NOW)
        st, body = preview(self.payload(doc, marks, edits))
        self.assertEqual((st, body["ok"], body["code"]), (409, False, "TAXONOMY_CHANGED"))
        with open(os.path.join(self.out, tb.DOC), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["taxonomy"]["version"], tb.hashlib.sha256(before).hexdigest())

    def test_validation_refusal_leaves_file_unchanged(self):
        doc = self.build()
        qn = [it for it in doc["items"] if it["kind"] == "q_new" and it["status"] == "open"][0]
        marks, edits = {qn["id"]: "applied"}, {qn["id"]: {"rows": [["Q1", "두께가 있나?", "공통", "3"]]}}
        res = self.apply(doc, marks, edits, preview=True)
        self.assertIn("QUESTION_ID_DUPLICATE", {i["code"] for i in res["issues"]})
        before = self.file_bytes()
        e = self.refused("TAXONOMY_INVALID", doc, marks, edits, preview=False)
        self.assertEqual(e.status, 400)
        self.assertIn({"sheet": "questions", "row": 4, "code": "QUESTION_ID_DUPLICATE"}, e.issues)
        self.assertEqual(self.file_bytes(), before)
        self.assertFalse(os.path.exists(self.hist))
        self.assertFalse(os.path.exists(os.path.join(self.out, tb.DECISIONS)))

    def test_blank_text_refused_for_edit_items(self):
        doc = self.build()
        ov = self.item(doc, "tax.value.overlap|공정|cmp|식각")
        self.assertEqual(ov["pick"], "all")
        self.refused("ITEM_NOT_APPLICABLE", doc, {ov["id"]: "applied"})     # 메모만 있고 고친 문장 없음
        cmp_row = list(ov["rows"][0]["cells"])
        blank = list(cmp_row)
        blank[7] = ""
        self.refused("ITEM_NOT_APPLICABLE", doc, {ov["id"]: "applied"}, {ov["id"]: {"rows": [blank, None]}})
        cmp_row[7] = "CMP와 식각을 가르는 새 정의"
        res = self.apply(doc, {ov["id"]: "applied"}, {ov["id"]: {"rows": [cmp_row]}}, preview=True)
        self.assertEqual([(d["op"], d["row"]) for d in res["diff"]], [("edit", 3)])
        self.assertEqual(res["diff"][0]["after"]["정의·판정 규칙"], "CMP와 식각을 가르는 새 정의")
        ax = self.item(doc, "tax.axis.def|공정")
        self.refused("ITEM_NOT_APPLICABLE", doc, {ax["id"]: "applied"})      # 빈 새 행: 쓸 문장 없음
        self.refused("ITEM_NOT_APPLICABLE", doc, {ax["id"]: "applied"}, {ax["id"]: {"choice": 1}})   # 지금 행과 같음
        new_def = list(ax["rows"][1]["cells"])
        new_def[7] = "여러 줄 정의\n둘째 줄"
        res = self.apply(doc, {ax["id"]: "applied"}, {ax["id"]: {"choice": 1, "rows": [None, new_def]}}, preview=True)
        self.assertEqual([(d["op"], d["row"]) for d in res["diff"]], [("edit", 2)])
        self.assertEqual(res["diff"][0]["after"]["정의·판정 규칙"], "여러 줄 정의\n둘째 줄")   # 줄바꿈 유지
        res = self.apply(doc, {ax["id"]: "applied"}, {ax["id"]: {"choice": 0, "rows": [new_def]}}, preview=True)
        self.assertEqual([(d["op"], d["row"]) for d in res["diff"]], [("add", 9)])        # 새 행으로 추가

    def test_duplicate_rows_overwrite_and_disable_all(self):
        rows = TAX_ROWS + [["공정", "CMP", "", "", "", "", "", "CMP 둘째 정의", "CMP 둘째 포함", "", ""],   # 9
                           ["상태", "정상", "", "", "", "", "", "정상 둘째", "", "", ""]]                    # 10
        self.write_tax(rows)
        doc = self.build()
        ov = self.item(doc, "tax.value.overlap|공정|cmp|식각")
        self.assertEqual(ov["rows"][0]["target"], {"mode": "overwrite", "row": 3, "dups": [9],
                                                   "dup_patch": {"7": "", "8": "", "9": ""}})
        self.assertIn("9행", ov["rows"][0]["place"])
        off = self.item(doc, "tax.value.off|상태|정상")
        self.assertEqual(off["rows"][0]["target"]["dups"], [10])
        cmp_row = list(ov["rows"][0]["cells"])
        cmp_row[7] = "새 CMP 정의"
        marks = {ov["id"]: "applied", off["id"]: "applied"}
        res = self.apply(doc, marks, {ov["id"]: {"rows": [cmp_row]}}, preview=True)
        edits = {d["row"]: d for d in res["diff"]}
        self.assertEqual(sorted(edits), [3, 7, 9, 10])
        self.assertEqual((edits[9]["after"]["정의·판정 규칙"], edits[9]["after"]["포함 예"]), ("", ""))
        self.assertEqual((edits[7]["after"]["사용 여부"], edits[10]["after"]["사용 여부"]), ("N", "N"))
        self.apply(doc, marks, {ov["id"]: {"rows": [cmp_row]}})
        new = self.file_doc()["taxonomy"]
        self.assertEqual((new[1]["정의·판정 규칙"], new[7]["정의·판정 규칙"], new[7]["값"]), ("새 CMP 정의", "", "CMP"))

    def test_same_cell_two_items_conflict(self):
        qd = os.path.join(self.tmp, "questions")
        _jsonl(os.path.join(qd, "taxonomy_proposals.jsonl"), S7_ROWS)
        doc = self.build(qd)
        vd, ov = self.item(doc, "tax.value.def|공정|cmp"), self.item(doc, "tax.value.overlap|공정|cmp|식각")
        self.assertEqual((vd["pick"], [r["target"]["mode"] for r in vd["rows"]]), ("one", ["append", "overwrite"]))
        cmp_row = list(ov["rows"][0]["cells"])
        cmp_row[7] = "다른 정의"
        marks = {vd["id"]: "applied", ov["id"]: "applied"}
        self.refused("ITEM_CONFLICT", doc, marks, {vd["id"]: {"choice": 1}, ov["id"]: {"rows": [cmp_row]}})
        # 새 행으로 추가를 고르면 같은 칸을 건드리지 않는다
        res = self.apply(doc, marks, {vd["id"]: {"choice": 0}, ov["id"]: {"rows": [cmp_row]}}, preview=True)
        self.assertEqual(sorted((d["op"], d["row"]) for d in res["diff"]), [("add", 9), ("edit", 3)])

    def test_synonym_alias_conflict_refused(self):
        """같은 동의어를 다른 표준어로 붙이는 두 행, 또는 doc에 이미 다른 표준어로 있는 동의어는 ITEM_CONFLICT."""
        doc = self.build()
        a, b = self.item(doc, "syn|식각기|식각"), self.item(doc, "syn|식각기|에칭")
        self.assertEqual((a["status"], b["status"]), ("open", "open"))
        before = self.file_bytes()
        self.refused("ITEM_CONFLICT", doc, {a["id"]: "applied", b["id"]: "applied"}, preview=False)
        self.assertEqual(self.file_bytes(), before)
        self.assertTrue(self.apply(doc, {a["id"]: "applied", b["id"]: "rejected"}, preview=True)["ok"])
        # doc의 동의어와 부딪치는 행(용어 후보의 동의어 행): 표준어가 다르면 거절, 대소문자만 다르면 통과
        term = self.item(doc, "term|플라즈마")
        cur = tax_doc()
        cur["synonyms"].append({"동의어": "플라즈마", "표준어": "식각", "메모": ""})
        marks = {term["id"]: "applied"}
        with self.assertRaises(tb.BoardRefused) as cm:
            tb.plan_changes(cur, doc["items"], marks, {term["id"]: {"choice": 0, "rows": [["플라즈마", "CMP", ""]]}},
                            "2026-10-05")
        self.assertEqual(cm.exception.code, "ITEM_CONFLICT")
        cur["synonyms"][-1]["표준어"] = "cmp"
        new = tb.plan_changes(cur, doc["items"], marks, {term["id"]: {"choice": 0, "rows": [["플라즈마", "CMP", ""]]}},
                              "2026-10-05")
        self.assertEqual(new["synonyms"][-1]["표준어"], "CMP")
        # 이미 다른 표준어로 있는 동의어 항목은 판정에서 막힌다(반영함은 ITEM_NOT_APPLICABLE)
        self.write_tax(data=json.dumps(dict(tax_doc(), synonyms=tax_doc()["synonyms"] + [
            {"동의어": "식각기", "표준어": "건식식각", "메모": ""}]), ensure_ascii=False).encode("utf-8"))
        doc2 = self.build()
        a2 = self.item(doc2, "syn|식각기|식각")
        self.assertEqual(a2["status"], "blocked")
        self.refused("ITEM_NOT_APPLICABLE", doc2, {a2["id"]: "applied"})

    def test_decisions_failure_after_save_is_ok_with_warning(self):
        doc = self.build()
        marks, edits, _syn = self.standard(doc)
        _preview, finalize = tb.board_handlers(self.out, self.tax, lambda: self.build()["counts"], now=NOW)
        with mock.patch.object(tb, "record_decisions", side_effect=PermissionError("잠김")):
            st, body = finalize(self.payload(doc, marks, edits))
        self.assertEqual((st, body["ok"], body["written"], body["changed"], body["decisions_failed"]),
                         (200, True, 4, 0, "PermissionError"))
        self.assertEqual(body["version"], tb.hashlib.sha256(self.file_bytes()).hexdigest(), "저장은 그대로 남는다")
        self.assertFalse(os.path.exists(os.path.join(self.out, tb.DECISIONS)))

    def test_reject_appends_rejected_row_only_for_values_synonyms_questions(self):
        doc = self.build()
        add, ax = self.item(doc, "tax.value.add|공정|증착"), self.item(doc, "tax.axis.def|공정")
        out = self.item(doc, "out|OTHER|axis:공정")
        res = self.apply(doc, {add["id"]: "rejected", ax["id"]: "rejected", out["id"]: "rejected"})
        self.assertEqual(res["written"], 1)
        rej = self.file_doc()["rejected"][-1]
        self.assertEqual(rej, {"종류": "값", "내용": "공정|증착", "기각일": "2026-10-05", "사유": "보드에서 기각",
                               "출처": add["id"]})
        doc2 = self.build()
        self.assertEqual(self.item(doc2, "tax.value.add|공정|증착")["status_note"], "rejected 목록에 있음")
        self.assertEqual(self.item(doc2, "tax.axis.def|공정")["status_note"], "보드에서 기각함")
        self.assertEqual(self.item(doc2, "out|OTHER|axis:공정")["status"], "rejected")

    def test_decision_cancel(self):
        doc = self.build()
        ax = self.item(doc, "tax.axis.def|공정")
        cells = list(ax["rows"][1]["cells"])
        cells[7] = "새 공정 정의"
        self.apply(doc, {ax["id"]: "applied"}, {ax["id"]: {"choice": 1, "rows": [None, cells]}})
        doc2 = self.build()
        self.assertEqual(self.item(doc2, "tax.axis.def|공정")["status_note"], "보드에서 반영함")
        res = self.apply(doc2, {ax["id"]: None})
        self.assertEqual((res["changed"], res["written"]), (1, 0))
        doc3 = self.build()
        self.assertEqual(self.item(doc3, "tax.axis.def|공정")["status"], "open")
        self.assertEqual(self.file_doc()["taxonomy"][0]["정의·판정 규칙"], "새 공정 정의")   # 쓴 내용은 그대로

    def test_server_trusts_only_editable_cells_and_refuses_bad_items(self):
        doc = self.build()
        add = self.item(doc, "tax.value.add|공정|증착")
        res = self.apply(doc, {add["id"]: "applied"}, {add["id"]: {"rows": [["다른축", "증착X", "", "Y"] + [""] * 7]}},
                         preview=True)
        after = res["diff"][0]["after"]
        self.assertEqual((after["축"], after["값"], after["다중값"]), ("공정", "증착", ""))
        blocked = self.item(doc, "tax.value.add|없는축|값")
        self.assertEqual(blocked["status"], "blocked")
        self.refused("ITEM_NOT_APPLICABLE", doc, {blocked["id"]: "applied"})
        self.assertTrue(self.apply(doc, {blocked["id"]: "rejected"}, preview=True)["ok"])   # 먼저 할 일도 기각은 된다
        self.refused("ITEM_NOT_APPLICABLE", doc, {"0" * 16: "applied"})
        done = self.item(doc, "tax.value.add|공정|cmp")
        self.refused("ITEM_NOT_APPLICABLE", doc, {done["id"]: "rejected"})
        out = self.item(doc, "out|OTHER|axis:공정")
        res = self.apply(doc, {out["id"]: "applied"}, preview=True)     # taxonomy 밖: 결정만 남긴다
        self.assertEqual(res["diff"], [])
        self.refused("DECISIONS_ITEM_INVALID", doc, {add["id"]: "maybe"})
        with self.assertRaises(tb.BoardRefused) as cm:
            tb.apply_marks(self.out, self.tax, {"kind": tb.DECISIONS_KIND, "marks": {}}, True)
        self.assertEqual(cm.exception.code, "DECISIONS_FORMAT_INVALID")
        term = self.item(doc, "term|플라즈마")
        self.refused("EDIT_INVALID", doc, {term["id"]: "applied"}, {term["id"]: {"choice": 5}})
        self.refused("EDIT_INVALID", doc, {add["id"]: "applied"}, {add["id"]: {"rows": [[1] * 11]}})
        # 용어의 값 행을 고르면 축이 필수다
        self.refused("ITEM_NOT_APPLICABLE", doc, {term["id"]: "applied"}, {term["id"]: {"choice": 1}})

    def test_board_server_endpoints(self):
        import http.client
        import threading
        from domain_engrbot import serve
        doc = self.build()
        preview, finalize = tb.board_handlers(self.out, self.tax, lambda: self.build()["counts"], now=NOW)
        srv = serve.make_board_server(os.path.join(self.out, tb.SCREEN), preview, finalize, 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        port = srv.server_address[1]
        host = "127.0.0.1:%d" % port

        def post(path, body, origin=True, ctype="application/json", length=None):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            raw = json.dumps(body).encode("utf-8")
            hdr = {"Content-Type": ctype, "Host": host, "Content-Length": str(length or len(raw))}
            if origin:
                hdr["Origin"] = "http://" + host
            c.request("POST", path, raw, hdr)
            r = c.getresponse()
            return r.status, json.loads(r.read().decode("utf-8"))

        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        c.request("GET", "/", headers={"Host": host})
        self.assertEqual(c.getresponse().status, 200)
        marks, edits, _syn = self.standard(doc)
        body = self.payload(doc, marks, edits)
        self.assertEqual(post("/board/preview", body, origin=False)[0], 403)
        self.assertEqual(post("/board/finalize", body, ctype="text/plain")[0], 415)
        self.assertEqual(post("/board/preview", body, length=serve.BOARD_MAX_BODY + 1)[0], 413)
        self.assertEqual(post("/board/preview", dict(body, kind="x"))[0], 400)
        self.assertEqual(post("/board/other", body)[0], 404)
        st, res = post("/board/preview", body)
        self.assertEqual((st, res["ok"], len(res["diff"])), (200, True, 4))
        st, res = post("/board/finalize", body)
        self.assertEqual((st, res["ok"], res["written"]), (200, True, 4))
        self.assertEqual(res["counts"]["open"], doc["counts"]["open"] - 4)
        st, res = post("/board/finalize", body)               # 옛 버전으로 다시 보내면 거절
        self.assertEqual((st, res["code"]), (409, "TAXONOMY_CHANGED"))
        qn = [it for it in doc["items"] if it["kind"] == "q_new" and it["status"] == "open"][0]
        with open(os.path.join(self.out, tb.DOC), encoding="utf-8") as f:
            fresh = json.load(f)
        bad = self.payload(fresh, {qn["id"]: "applied"}, {qn["id"]: {"rows": [["Q1", "두께?", "공통", "3"]]}})
        st, res = post("/board/finalize", bad)
        self.assertEqual((st, res["code"]), (400, "TAXONOMY_INVALID"))
        self.assertTrue(res["issues"])

    def test_shared_commit_error_codes(self):
        """편집기와 같은 commit_taxonomy 거절 코드: 쓰기 실패 500, 읽기 실패 500(detail), 파일 없음 404."""
        doc = self.build()
        marks, edits, _syn = self.standard(doc)
        _preview, finalize = tb.board_handlers(self.out, self.tax, lambda: self.build()["counts"], now=NOW)
        before = self.file_bytes()
        with mock.patch.object(tb.lb, "save_taxonomy_doc", side_effect=PermissionError("잠김")):
            st, body = finalize(self.payload(doc, marks, edits))
        self.assertEqual((st, body["ok"], body["code"]), (500, False, "TAXONOMY_WRITE_FAILED"))
        self.assertEqual(self.file_bytes(), before)
        self.assertFalse(os.path.exists(os.path.join(self.out, tb.DECISIONS)), "쓰기 실패면 결정도 남기지 않는다")
        self.write_tax(data=b"{not json")
        e = self.refused("TAXONOMY_READ_FAILED", doc, marks, edits)
        self.assertEqual((e.status, e.detail), (500, "TAXONOMY_JSON_INVALID"))
        os.remove(self.tax)
        st, body = finalize(self.payload(doc, marks, edits))
        self.assertEqual((st, body["code"]), (404, "TAXONOMY_NOT_FOUND"))

    def test_rebuild_failure_after_save_is_200(self):
        doc = self.build()
        marks, edits, _syn = self.standard(doc)

        def broken():
            raise RuntimeError("셀 내용이 든 문장")
        _preview, finalize = tb.board_handlers(self.out, self.tax, broken, now=NOW)
        st, body = finalize(self.payload(doc, marks, edits))
        self.assertEqual((st, body["ok"], body["written"], body["counts"], body["rebuild_failed"]),
                         (200, True, 4, None, "RuntimeError"))
        self.assertEqual(body["version"], tb.hashlib.sha256(self.file_bytes()).hexdigest(), "저장은 그대로 남는다")

    def test_board_server_bad_bodies_and_catch_all(self):
        import http.client
        import threading
        from domain_engrbot import serve

        def boom(_payload):
            raise ValueError("셀 내용이 든 문장")
        srv = serve.make_board_server(os.path.join(self.out, tb.SCREEN), boom, boom, 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        host = "127.0.0.1:%d" % srv.server_address[1]

        def post(raw):
            c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
            c.request("POST", "/board/preview", raw, {"Content-Type": "application/json", "Host": host,
                                                      "Origin": "http://" + host})
            r = c.getresponse()
            out = r.status, json.loads(r.read().decode("utf-8"))
            c.close()
            return out
        deep = b"[" * 200000   # 아주 깊은 중첩: json.loads가 RecursionError
        self.assertEqual(post(deep), (400, {"ok": False, "code": "DECISIONS_JSON_INVALID"}))
        buf = std_io.StringIO()
        with contextlib.redirect_stdout(buf):
            st, body = post(json.dumps({"kind": serve.BOARD_KIND}).encode("utf-8"))
        self.assertEqual((st, body["code"], body["detail"]), (500, "BOARD_FAILED", "ValueError"))
        self.assertNotIn("셀 내용", buf.getvalue())

    def test_index_has_axis_rows(self):
        self.assertEqual(tb._index({"taxonomy": [], "questions": [], "synonyms": [], "rejected": []})["axis_rows"], {})

    def test_screens_carry_csp_meta(self):
        """file://로 열어도 CSP가 걸린다: 헤더(serve.CSP)와 같은 정책(meta가 무시하는 frame-ancestors만 뺀다)."""
        from domain_engrbot import serve, taxonomy_editor
        want = "; ".join(d for d in serve.CSP.split("; ") if not d.startswith("frame-ancestors"))
        for path in (tb.TEMPLATE_PATH, taxonomy_editor.SCREEN):
            with open(path, encoding="utf-8") as f:
                text = f.read()
            m = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]*)">', text)
            self.assertIsNotNone(m, path)
            self.assertEqual(m.group(1), want)


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


class StrictSynonymTest(unittest.TestCase):
    """봇(S4)만 올린 동의어는 엄밀 기준(labelbot과 같은 규칙)으로 거르고, 사람 출처가 섞이면 둔다."""

    @staticmethod
    def group(alias, canonical, srcs, n=2):
        return {"e": {"kind": "synonym", "alias": alias, "canonical": canonical},
                "chips": [{"src": s, "n": n} for s in srcs]}

    def test_filters_bot_only(self):
        idx = {"axes": {"구조": 1}, "values": {("구조", "m1"): 1, ("구조", "v1"): 1}}
        groups = [self.group("메탈원", "M1", ["S4"]),             # 통과
                  self.group("메탈일", "M1", ["S4"], n=1),        # 1회뿐
                  self.group("M1 trench", "M1", ["S4"]),          # 좁은 개념
                  self.group("메탈 라인", "배선", ["S4"]),          # 분류 체계에 없는 표준어
                  self.group("비아원", "V1", ["S4"]), self.group("비아원", "M1", ["S4"]),   # 표준어 둘
                  self.group("메탈 라인", "배선", ["S4", "S6"])]    # 사람 출처가 섞임
        keep, n = tb.strict_synonyms(groups, idx)
        self.assertEqual([(g["e"]["alias"], [c["src"] for c in g["chips"]]) for g in keep],
                         [("메탈원", ["S4"]), ("메탈 라인", ["S4", "S6"])])
        self.assertEqual(n, 5)
