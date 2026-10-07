"""taxonomy 재검토 요청(revisit): 검증·반영·리포트 단위 테스트와 mock 파이프라인 통합 테스트.

모든 값은 가짜다. 원본 파일은 test_pipeline과 같이 read_input 경로로만 읽힌다.
"""
import contextlib
import datetime
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from unittest import mock

from labelbot import candidates, cli, finals, pipeline, review, revisit, store, taxonomy, util
from labelbot.mock import MockChatTransport
from labelbot.workspace import CODE_ROOT
from tests.test_pipeline import DUMMY_DIR, _Ws, responder

RUN = "20261004T010203-ab12"
RUN2 = "20260930T120000-cd34"
SHA = "a" * 64
SUMMARY = os.path.join(CODE_ROOT, ".claude", "skills", "BEOL-labeling", "scripts", "summary.py")


def _tax():
    tax = taxonomy.Taxonomy()
    a = taxonomy.Axis("예시축A", "분류", True, True, False, "", "", "")
    a.values = [taxonomy.Value("상위-1", None, "", "", "", 2), taxonomy.Value("값-1", "상위-1", "", "", "", 3),
                taxonomy.Value("값-2", None, "", "", "", 4)]
    b = taxonomy.Axis("예시축B", "상태", False, False, False, "", "", "")
    b.values = [taxonomy.Value("값-x", None, "", "", "", 6)]
    tax.axes = [a, b]
    tax.questions = [taxonomy.Question("Q-COM-001", "가짜 질문", "공통", "1", 2)]
    tax.sheet_hashes = {"taxonomy": "t" * 16, "questions": "q" * 16}
    return tax


class _FakeWs:
    def __init__(self, root):
        self.root = root

    def path(self, *parts):
        return os.path.join(self.root, *parts)


def _item(cid="c1", target="axis", key="예시축A", reason="NO_FIT_VALUE", value="새값-가", parent=None,
          related=None, memo=""):
    return {"chunk_id": cid, "target": target, "key": key, "reason": reason,
            "proposed": {"value": value, "parent": parent} if value is not None else None,
            "related_values": related or [], "memo": memo}


class RevisitUnitTest(unittest.TestCase):
    def setUp(self):
        self.con = store.connect(":memory:")
        self.tax = _tax()
        for run in (RUN, RUN2):
            self.con.execute("INSERT INTO runs(run_id, command) VALUES(?, 'run')", (run,))
        for cid, fid in (("c1", "f1"), ("c2", "f1"), ("c3", "f2"), ("c9", "f2")):
            self.con.execute("INSERT INTO chunks(chunk_id, file_id, seq, text, text_hash) VALUES(?,?,1,'가짜',?)",
                             (cid, fid * 8, "h-" + cid))
        for run in (RUN, RUN2):
            for cid in ("c1", "c2", "c3"):
                self.con.execute("INSERT INTO flagged_chunks(run_id, chunk_id, reason_codes, text_hash) VALUES(?,?,?,?)",
                                 (run, cid, '["UNKNOWN_HIGH"]', "h-" + cid))
            for cid in ("c1", "c2"):  # c3는 분류·라벨 실패(labels 행 없음)
                self.con.execute("INSERT INTO labels(run_id, chunk_id, kind, key, value, status) VALUES(?,?,?,?,?,?)",
                                 (run, cid, "chunk_type", "", "내용", "value"))
                self.con.execute("INSERT INTO labels(run_id, chunk_id, kind, key, value, status) VALUES(?,?,?,?,?,?)",
                                 (run, cid, "axis", "예시축A", '["unknown"]', "unknown"))
                self.con.execute("INSERT INTO labels(run_id, chunk_id, kind, key, value, status) VALUES(?,?,?,?,?,?)",
                                 (run, cid, "answer", "Q-COM-001", "N/A", "value"))
        self.con.commit()
        self.dir = tempfile.mkdtemp(prefix="labelbot_rv_")
        self.ws = _FakeWs(self.dir)

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def apply(self, revisits, run=RUN, corrections=None, sha=SHA, legacy=False):
        doc = {"kind": "review", "run_id": run, "corrections": corrections or [], "chunk_status": [], "synonyms": []}
        if not legacy:
            doc["revisits"] = revisits
        return review._apply_review(self.con, self.tax, doc, sha)

    def rows(self, run=RUN):
        return self.con.execute("SELECT * FROM revisit_requests WHERE review_run_id=? ORDER BY chunk_id, target_kind,"
                                " target_key", (run,)).fetchall()

    def test_matrix_allowed_and_denied(self):
        flagged = {"c1"}
        for target in ("axis", "question", "new_axis", "bogus"):
            for key in ("K1", ""):
                for reason in revisit.REASONS + ("BOGUS",):
                    item = _item(target=target, key=key, reason=reason, related=["값-1", "값-2"] if reason == "VALUE_OVERLAP" else [],
                                 memo="가짜 메모")
                    row, code = revisit.normalize(item, flagged)
                    allowed = target in revisit.TARGETS and reason in revisit.TARGET_REASONS[revisit.rule_key(target, key)]
                    if not allowed:
                        want = revisit.REASON_INVALID
                    elif (target == "axis" and not key) or (target == "new_axis" and key):
                        want = revisit.FIELD_INVALID
                    else:
                        want = None
                    self.assertEqual(code, want, (target, key, reason))
                    self.assertEqual(row is None, want is not None)
        # 명시 확인: 질문 빈 키는 NEED_QUESTION만, QID 질문에는 NEED_QUESTION 불가
        self.assertIsNone(revisit.normalize(_item(target="question", key="", reason="NEED_QUESTION", memo="m"), flagged)[1])
        self.assertEqual(revisit.normalize(_item(target="question", key="Q-1", reason="NEED_QUESTION", memo="m"), flagged)[1],
                         revisit.REASON_INVALID)
        self.assertEqual(revisit.normalize(_item(target="axis", key="K", reason="NEW_AXIS"), flagged)[1], revisit.REASON_INVALID)

    def test_required_fields(self):
        f = {"c1"}
        bad = [
            "문자열 항목", None, 3,
            _item(value=None),                                                    # NO_FIT_VALUE proposed 없음
            dict(_item(), proposed={"value": "  "}),                              # 빈 값
            dict(_item(), proposed={"value": "가" * 61}),                         # 60자 초과
            dict(_item(), proposed={"value": 3}),                                 # 문자열 아님
            _item(value="UnKnown"),                                               # 예약어
            _item(value="해당 없음"),                                              # 예약어(공백 변형)
            _item(parent="가" * 61),                                              # 상위값 60자 초과
            _item(target="new_axis", key="", reason="NEW_AXIS", value=None),      # NEW_AXIS 이름 없음
            _item(reason="VALUE_OVERLAP", value=None, related=["값-1"]),           # 1개
            _item(reason="VALUE_OVERLAP", value=None, related=["값-1", " 값-1 "]),  # 같은 값 2개
            _item(reason="VALUE_OVERLAP", value=None, related=["a", "b", "c"]),   # 3개
            dict(_item(reason="VALUE_OVERLAP", value=None), related_values="값-1"),  # list 아님
            _item(reason="AMBIGUOUS_DEF", value=None, related=["값-1", "값-2"]),  # 2개
            _item(reason="OTHER", value=None, memo="  \r\n "),                    # 메모 필수
            _item(target="question", key="", reason="NEED_QUESTION", value=None),  # 메모 필수
            _item(target="question", key="Q-COM-001", reason="OTHER", value=None),  # 메모 필수
            _item(key="축|값"),                                                   # 키에 |
            _item(key="가" * 101),                                                # 키 100자 초과
            dict(_item(), memo=5),                                                # 메모 문자열 아님
            dict(_item(), chunk_id=None),
        ]
        for it in bad:
            self.assertEqual(revisit.normalize(it, f), (None, revisit.FIELD_INVALID), it)
        row, code = revisit.normalize(_item(reason="AMBIGUOUS_DEF", value=None), f)
        self.assertIsNone(code)
        self.assertEqual(row["related_values"], [])
        row, code = revisit.normalize(dict(_item(value="  새  값\t가 ", parent=""), key=" 예시축A "), f)
        self.assertEqual((row["proposed_value"], row["proposed_parent"], row["key"]), ("새 값 가", None, "예시축A"))

    def test_key_strip_only(self):
        f = {"c1"}
        row, code = revisit.normalize(_item(key=" \t예시  축\tA \n"), f)
        self.assertIsNone(code)
        self.assertEqual(row["key"], "예시  축\tA")  # 안쪽 공백은 그대로
        row, code = revisit.normalize(_item(target="question", key="  Q-COM-001 ", reason="AMBIGUOUS_DEF", value=None), f)
        self.assertEqual(row["key"], "Q-COM-001")
        self.assertEqual(revisit.normalize(_item(target="question", key="   ", reason="NEED_QUESTION", value=None,
                                                 memo="m"), f)[1], None)  # 공백뿐인 키는 빈 키
        self.assertEqual(revisit.normalize(_item(key=" 축 | 값 "), f), (None, revisit.FIELD_INVALID))
        self.assertIsNone(revisit.normalize(_item(key=" " + "가" * 100 + " "), f)[1])  # 자른 뒤 100자는 허용
        self.assertEqual(revisit.normalize(_item(key="가 " * 50 + "가"), f), (None, revisit.FIELD_INVALID))  # 101자

    def test_revisits_max(self):
        code, n, drops = self.apply([7] * revisit.REVISITS_MAX)
        self.assertEqual((code, n, drops), ("OK", 0, {revisit.FIELD_INVALID: revisit.REVISITS_MAX}))
        with self.assertRaises(ValueError):
            self.apply([_item()] * (revisit.REVISITS_MAX + 1))

    def test_non_hierarchical_parent_dropped(self):
        self.apply([_item(key="예시축B", value="새값-b", parent="상위-1"),     # 계층 없는 축: 상위값 버림
                    _item(cid="c2", value="새값-a", parent="상위-1"),          # 계층 축: 유지
                    _item(cid="c3", key="사라진축", value="새값-z", parent="상위-z")])  # 시트에 없는 축: 유지
        parents = {r["chunk_id"]: r["proposed_parent"] for r in self.rows()}
        self.assertEqual(parents, {"c1": None, "c2": "상위-1", "c3": "상위-z"})
        n, md, jl = self._report()
        code = md.split("```\n", 1)[1].split("```", 1)[0].strip("\n").split("\n")
        self.assertIn("\t".join(["예시축B", "새값-b"] + [""] * 9), code)
        self.assertIn("\t".join(["예시축A", "새값-a", "상위-1"] + [""] * 8), code)
        self.assertEqual(len(code), 2)
        self.assertIn("| 예시축B | 새값-b | - | 1 |", md)
        self.assertEqual({r["chunk_id"]: (r["proposed"] or {}).get("parent") for r in jl}["c1"], None)

    def test_paste_row_formula_quoted(self):
        self.apply([_item(value="=1+2"), _item(cid="c2", value="@합계", parent="상위-1")])
        n, md, jl = self._report()
        code = md.split("```\n", 1)[1].split("```", 1)[0].strip("\n").split("\n")
        self.assertEqual(sorted(c.split("\t")[1] for c in code), ["'=1+2", "'@합계"])

    def test_not_flagged_dropped(self):
        code, n, drops = self.apply([_item(cid="c9"), _item(cid="없는chunk")])
        self.assertEqual((code, n), ("OK", 0))
        self.assertEqual(drops, {revisit.NOT_FLAGGED: 2})
        self.assertEqual(self.rows(), [])

    def test_idempotent(self):
        items = [_item(), _item(cid="c2", reason="VALUE_OVERLAP", value=None, related=["값-1", "값-2"], memo="m")]
        self.apply(items)
        snap1 = [dict(r) for r in self.rows()]
        self.apply(items)
        snap2 = [dict(r) for r in self.rows()]
        for r in snap1 + snap2:
            r.pop("applied_at")
        self.assertEqual(snap1, snap2)
        self.assertEqual(len(snap1), 2)

    def test_snapshot_replace_and_cancel(self):
        self.apply([_item(), _item(cid="c2")])
        self.apply([_item(cid="c3", target="new_axis", key="", reason="NEW_AXIS", value="새축")], run=RUN2)
        self.apply([_item(cid="c2")])
        self.assertEqual([r["chunk_id"] for r in self.rows()], ["c2"])
        self.assertEqual(len(self.rows(RUN2)), 1)
        self.assertEqual(revisit.count(self.con), 2)

    def test_legacy_doc_keeps_rows(self):
        self.apply([_item()])
        code, n, drops = self.apply(None, legacy=True)
        self.assertEqual((code, drops), ("OK", {}))
        self.assertEqual(len(self.rows()), 1)
        self.apply([])
        self.assertEqual(self.rows(), [])

    def test_not_list_is_format_error(self):
        doc = {"kind": "review", "run_id": RUN, "revisits": {"chunk_id": "c1"}}
        with self.assertRaises(ValueError):
            review._apply_review(self.con, self.tax, doc, SHA)

    def test_memo_truncated(self):
        memo = "가\r\n" + "나" * 600
        code, n, drops = self.apply([_item(memo=memo)])
        self.assertEqual(drops, {revisit.MEMO_TRUNCATED: 1})
        stored = self.rows()[0]["memo"]
        self.assertEqual(len(stored), 500)
        self.assertTrue(stored.startswith("가\n나"))

    def test_duplicate_last_wins(self):
        code, n, drops = self.apply([_item(value="앞값"), _item(value="뒤값"), _item(value="unknown")])
        self.assertEqual(drops, {revisit.DUPLICATE: 1, revisit.FIELD_INVALID: 1})
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["proposed_value"], "뒤값")  # 무효한 뒤 항목은 앞의 유효 항목을 지우지 않는다

    def test_snapshots(self):
        corr = [{"chunk_id": "c1", "target": "axis", "key": "예시축A", "value": ["값-2"]},
                {"chunk_id": "c1", "target": "answer", "key": "Q-COM-001", "value": "O"}]
        self.apply([_item(),
                    _item(target="question", key="Q-COM-001", reason="AMBIGUOUS_DEF", value=None),
                    _item(target="new_axis", key="", reason="NEW_AXIS", value="새축")], corrections=corr)
        rows = {(r["target_kind"], r["target_key"]): r for r in self.rows()}
        ax = rows[("axis", "예시축A")]
        self.assertEqual(json.loads(ax["bot_value"]), ["unknown"])
        self.assertEqual(json.loads(ax["human_value"]), ["값-2"])
        self.assertEqual(ax["file_id"], "f1" * 8)
        self.assertEqual(ax["file_sha256"], SHA)
        q = rows[("question", "Q-COM-001")]
        self.assertEqual((json.loads(q["bot_value"]), json.loads(q["human_value"])), ("N/A", "O"))
        na = rows[("new_axis", "")]
        self.assertEqual((json.loads(na["bot_value"]), json.loads(na["human_value"])), (None, None))

    def test_failed_chunk_revisit(self):
        code, n, drops = self.apply([_item(cid="c3")])
        self.assertEqual((code, n, drops), ("OK", 1, {}))
        self.assertIsNone(json.loads(self.rows()[0]["bot_value"]))

    def test_bad_revisit_does_not_block_corrections(self):
        corr = [{"chunk_id": "c1", "target": "answer", "key": "Q-COM-001", "value": "O"}]
        code, n, drops = self.apply(["깨진 항목", 7, {"chunk_id": ["x"]}, _item(cid="c2")], corrections=corr)
        self.assertEqual(code, "OK")
        self.assertEqual(n, 2)
        self.assertEqual(drops, {revisit.FIELD_INVALID: 3})
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM corrections").fetchone()[0], 1)

    def test_labels_unchanged(self):
        corr = [{"chunk_id": "c1", "target": "answer", "key": "Q-COM-001", "value": "O"}]
        self.apply([], corrections=corr)
        before = finals.final_labels(self.con, RUN, ["c1", "c2", "c3"])
        hashes = {c: finals.label_hash(d) for c, d in before.items()}
        n_corr = self.con.execute("SELECT COUNT(*) FROM corrections").fetchone()[0]
        self.apply([_item(), _item(cid="c2", reason="OTHER", value=None, memo="m"),
                    _item(cid="c1", target="question", key="Q-COM-001", reason="AMBIGUOUS_DEF", value=None)],
                   corrections=corr)
        after = finals.final_labels(self.con, RUN, ["c1", "c2", "c3"])
        self.assertEqual(before, after)
        self.assertEqual(hashes, {c: finals.label_hash(d) for c, d in after.items()})
        self.assertEqual(n_corr, self.con.execute("SELECT COUNT(*) FROM corrections").fetchone()[0])
        kinds = {k for items in finals.corrections(self.con).values() for k, _ in items}
        self.assertEqual(kinds, {"answer"})

    def _report(self):
        n = revisit.write_reports(self.ws, self.con, self.tax)
        with open(self.ws.path("reports", "taxonomy_revisit.md"), encoding="utf-8") as f:
            md = f.read()
        with open(self.ws.path("reports", "taxonomy_revisit.jsonl"), encoding="utf-8") as f:
            jl = [json.loads(l) for l in f if l.strip()]
        return n, md, jl

    def test_reports_format(self):
        self.apply([_item(value="새값-가", parent="상위-1",
                          memo="첫 줄 | 파이프 <script>\n둘째 줄 & 끝\n[링크](u) ![그림](v) `코드` a\\b"),
                    _item(cid="c2", value="값-1"),  # 시트에 이미 있는 값
                    _item(cid="c3", reason="VALUE_OVERLAP", value=None, related=["값-1", "값-2"]),
                    _item(cid="c3", target="new_axis", key="", reason="NEW_AXIS", value="새축|이름 ![i](w) `c`")])
        self.apply([_item(value="새값-가", parent="상위-1")], run=RUN2)
        n, md, jl = self._report()
        self.assertEqual(n, 5)
        self.assertEqual(len(jl), revisit.count(self.con))
        order = [(r["review_run_id"], r["chunk_id"], r["target"], r["key"]) for r in jl]
        self.assertEqual(order, sorted(sorted(order, key=lambda t: t[1:]), key=lambda t: t[0], reverse=True))
        self.assertEqual(jl[0]["review_run_id"], RUN)
        self.assertNotIn("taxonomy_hash", jl[0])
        self.assertIn("## 검수 실행 %s: 4건" % RUN, md)
        self.assertIn("## 검수 실행 %s: 1건" % RUN2, md)
        self.assertIn("누적 요청: 5건 (검수 실행 2개)", md)
        code = md.split("```\n", 1)[1].split("```", 1)[0].strip("\n").split("\n")
        want = candidates.paste_row({"kind": "new_value", "content": "예시축A|새값-가", "parent": "상위-1", "source": "review"})
        self.assertEqual(code, [want])
        self.assertEqual(code[0].count("\t"), 10)
        self.assertIn("| 예시축A | 새값-가 | 상위-1 | 2 | %s, %s |" % (RUN, RUN2), md)
        self.assertIn("시트에 이미 있는 값: 행 초안 생략", md)
        self.assertIn("  > 첫 줄 &#124; 파이프 &lt;script&gt;", md)
        self.assertIn("  > 둘째 줄 &amp; 끝", md)
        self.assertNotIn("<script>", md)
        self.assertIn("새축/이름", md)  # 표 칸의 |는 /
        self.assertIn("값-1 ↔ 값-2", md)
        # md 링크·이미지·코드 표기는 \로 무력화한다(메모 인용과 표 칸 모두, 이중 이스케이프 없이).
        self.assertIn("  > \\[링크\\](u) \\!\\[그림\\](v) \\`코드\\` a\\\\b", md)
        self.assertIn("| 새축/이름 \\!\\[i\\](w) \\`c\\` |", md)
        self.assertNotIn("[링크](u)", md)
        self.assertNotIn("![i](w)", md)
        self.assertNotIn("\\\\[", md)
        self.assertNotIn("\\&", md)

    def test_report_missing_axis_or_parent(self):
        self.apply([_item(key="사라진축", value="새값-나"), _item(cid="c2", value="새값-다", parent="없는상위")])
        n, md, jl = self._report()
        self.assertIn("시트에 없는 축: 행 초안 생략", md)
        self.assertIn("시트에 없는 상위값: 행 초안 생략", md)
        self.assertNotIn("```", md)
        self.assertIn("행 초안 없음.", md)
        self.assertEqual(n, 2)

    def test_zero_requests_report(self):
        n, md, jl = self._report()
        self.assertEqual((n, jl), (0, []))
        self.assertIn("누적 요청: 0건", md)

    # ---- 실행별 재검토 파일 ----

    NOW = datetime.datetime(2026, 10, 5, 9, 8, 7)

    def _run_files(self, runs=(RUN,), now=NOW):
        out = os.path.join(self.dir, "taxonomy", revisit.REQUESTS_DIRNAME)
        paths = revisit.write_run_files(out, self.con, self.tax, list(runs), now=now)
        return out, paths

    def _load_one(self, p):
        with open(p, encoding="utf-8") as f:
            return f.read()

    def _load(self, paths):
        got = {}
        for p in paths:
            with open(p, encoding="utf-8") as f:
                got[os.path.splitext(p)[1]] = f.read()
        return got[".md"], got[".html"], json.loads(got[".json"])

    def test_requests_dir_next_to_taxonomy(self):
        ws = _FakeWs(self.dir)
        ws.taxonomy_path = os.path.join(self.dir, "어딘가", "taxonomy.json")
        self.assertEqual(revisit.requests_dir(ws), os.path.join(self.dir, "어딘가", "taxonomy_revisit_requests"))

    def test_run_files_created_and_named(self):
        self.apply([_item()])
        out, paths = self._run_files()
        names = sorted(os.listdir(out))
        self.assertEqual(names, ["taxonomy_revisit_20261005_090807.%s" % e for e in ("html", "json", "md")])
        for fn in names:
            self.assertRegex(fn, r"^taxonomy_revisit_\d{8}_\d{6}(_\d+)?\.(md|html|json)$")
        self.assertEqual(sorted(paths), [os.path.join(out, fn) for fn in names])

    def test_run_files_zero_requests(self):
        self.apply([])
        self.apply([_item(cid="c9")])  # NOT_FLAGGED로 버려져 0건
        out, paths = self._run_files()
        self.assertEqual(paths, [])
        self.assertFalse(os.path.exists(out))
        out, paths = self._run_files(runs=())
        self.assertEqual(paths, [])

    def test_run_files_only_this_run(self):
        self.apply([_item(value="이번값-가", memo="이번 메모")])
        self.apply([_item(value="다른실행값", memo="다른 실행 메모"), _item(cid="c2", reason="OTHER", value=None,
                                                                   memo="다른 실행 메모")], run=RUN2)
        out, paths = self._run_files()
        md, page, doc = self._load(paths)
        self.assertEqual({r["review_run_id"] for r in doc["requests"]}, {RUN})
        self.assertEqual(doc["review_run_id"], RUN)
        for body in (md, page, json.dumps(doc, ensure_ascii=False)):
            self.assertIn("이번값-가", body)
            self.assertIn("이번 메모", body)
            self.assertNotIn("다른실행값", body)
            self.assertNotIn("다른 실행 메모", body)
            self.assertNotIn(RUN2, body)

    def test_run_files_paste_rows(self):
        self.apply([_item(value="새값-가", parent="상위-1", memo="붙여넣기 메모"),
                    _item(cid="c2", value=" 새값-가 "),                # 같은 (축, 값)은 한 행으로 묶는다
                    _item(cid="c3", key="예시축B", value="=1+2")])
        out, paths = self._run_files()
        md, page, doc = self._load(paths)
        want = [candidates.paste_row({"kind": "new_value", "content": "예시축A|새값-가", "parent": "상위-1",
                                      "source": "review"}).split("\t"),
                candidates.paste_row({"kind": "new_value", "content": "예시축B|=1+2", "parent": None,
                                      "source": "review"}).split("\t")]
        self.assertEqual(doc["paste_rows"], want)
        self.assertEqual(doc["paste_rows"][1][1], "'=1+2")
        for row in doc["paste_rows"]:
            self.assertEqual(len(row), 11)
            self.assertEqual(row[10], "")
            self.assertEqual(row[3:], [""] * 8)
        self.assertEqual(doc["paste_requests"], [[1, 2], [3]])
        self.assertEqual(doc["check_rows"], [])
        self.assertEqual(doc["columns"], taxonomy.HEADERS["taxonomy"])
        code = md.split("```\n", 1)[1].split("```", 1)[0].strip("\n").split("\n")
        self.assertEqual(code, ["\t".join(r) for r in want])
        self.assertTrue(all(c.count("\t") == 10 for c in code))
        self.assertIn("확인할 행이 없다.", md)
        tbody = re.search(r'<table class="sheet paste">.*?<tbody>(.*?)</tbody>', page, re.S).group(1)
        cells = re.findall(r"<tr>(.*?)</tr>", tbody)
        self.assertEqual(len(cells), 2)
        self.assertEqual([len(re.findall(r"<td>", c)) for c in cells], [11, 11])
        self.assertNotIn("붙여넣기 메모", "".join(code) + tbody)  # 메모는 붙여넣기 칸 밖에만

    def test_run_files_check_block(self):
        self.tax.axes.append(taxonomy.Axis("탭\t축", "분류", False, False, False, "", "", ""))
        self.apply([_item(value="값-1"),                                          # 1 시트에 이미 있는 값
                    _item(cid="c2", value="새값-다", parent="없는상위"),           # 2 시트에 없는 상위값
                    _item(cid="c3", key="사라진축", value="새값-나"),              # 3 시트에 없는 축
                    _item(cid="c1", target="new_axis", key="", reason="NEW_AXIS", value="새축"),
                    _item(cid="c2", target="new_axis", key="", reason="NEW_AXIS", value="예시축B"),
                    _item(cid="c3", key="탭\t축", value="탭값")])
        out, paths = self._run_files()
        md, page, doc = self._load(paths)
        self.assertEqual(doc["paste_rows"], [])
        got = {(c["row"][0], c["row"][1]): c["reason"] for c in doc["check_rows"]}
        self.assertEqual(got, {
            ("예시축A", "값-1"): "시트에 이미 있는 값",
            ("예시축A", "새값-다"): "시트에 없는 상위값",
            ("사라진축", "새값-나"): "시트에 없는 축",
            ("새축", ""): revisit.NEW_AXIS_CHECK,
            ("예시축B", ""): "시트에 이미 있는 축",
            ("탭 축", "탭값"): "칸에 탭·줄바꿈이 있다",
        })
        for c in doc["check_rows"]:
            self.assertEqual(len(c["row"]), 11)
            self.assertEqual(c["row"][10], "")
            self.assertTrue(c["requests"])
        self.assertEqual({r["block"] for r in doc["requests"]}, {"check"})
        self.assertIn("바로 반영할 행이 없다.", md)
        code = md.split("```\n", 1)[1].split("```", 1)[0].strip("\n").split("\n")
        self.assertEqual(len(code), 6)
        self.assertTrue(all(c.count("\t") == 10 for c in code))
        self.assertIn("| 시트에 없는 상위값 |", md)
        self.assertEqual(len(re.findall(r"<tr>", re.search(r'<table class="sheet check">.*?<tbody>(.*?)</tbody>',
                                                           page, re.S).group(1))), 6)

    def test_run_files_list_only(self):
        self.apply([_item(reason="AMBIGUOUS_DEF", value=None, related=["값-2"], memo="목록메모A"),
                    _item(cid="c2", reason="VALUE_OVERLAP", value=None, related=["값-1", "값-2"]),
                    _item(cid="c3", reason="OTHER", value=None, memo="목록메모B"),
                    _item(cid="c1", target="question", key="", reason="NEED_QUESTION", value=None, memo="목록메모C"),
                    _item(cid="c2", target="question", key="Q-COM-001", reason="AMBIGUOUS_DEF", value=None)])
        out, paths = self._run_files()
        md, page, doc = self._load(paths)
        self.assertEqual((doc["paste_rows"], doc["check_rows"]), ([], []))
        self.assertEqual([r["block"] for r in doc["requests"]], ["list"] * 5)
        self.assertEqual(sorted(r["reason"] for r in doc["requests"]),
                         sorted(["AMBIGUOUS_DEF", "VALUE_OVERLAP", "OTHER", "NEED_QUESTION", "AMBIGUOUS_DEF"]))
        self.assertNotIn("```\n", md.split("## 요청 목록", 1)[0])
        self.assertNotIn('class="sheet', page)
        for m in ("목록메모A", "목록메모B", "목록메모C"):
            self.assertIn(m, md)
            self.assertIn(m, page)
        self.assertIn("값-1 ↔ 값-2", md)

    def test_run_files_html_escape_and_no_http(self):
        self.apply([_item(value="<b>값&", memo="<script>alert(1)</script> HTTP://x.example hTtPs ftp"),
                    _item(cid="c2", target="new_axis", key="", reason="NEW_AXIS", value="축\"<i>http")])
        out, paths = self._run_files()
        md, page, doc = self._load(paths)
        self.assertIsNone(re.search("http", page, re.I))
        self.assertNotIn("<script", page.lower())
        self.assertNotIn("<b>", page)
        self.assertNotIn("<i>", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        self.assertIn("&lt;b&gt;값&amp;", page)
        self.assertIn("축&quot;&lt;i&gt;", page)
        self.assertIn('<meta charset="utf-8">', page)
        self.assertNotIn("src=", page)
        self.assertNotIn("<link", page)
        self.assertIn("&lt;script&gt;", md)  # md 메모 인용은 기존 이스케이프 규칙
        self.assertNotIn("<script>", md)
        self.assertEqual(doc["requests"][0]["memo"], "<script>alert(1)</script> HTTP://x.example hTtPs ftp")

    def test_run_files_json(self):
        self.apply([_item(memo="json 메모"), _item(cid="c2", target="new_axis", key="", reason="NEW_AXIS", value="새축")])
        out, paths = self._run_files()
        md, page, doc = self._load(paths)
        self.assertEqual(set(doc), {"kind", "review_run_id", "generated_at", "sheet", "columns", "paste_rows",
                                    "paste_requests", "check_rows", "requests"})
        self.assertEqual((doc["kind"], doc["sheet"]), ("taxonomy_revisit", "taxonomy"))
        self.assertRegex(doc["generated_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertEqual(len(doc["requests"]), 2)
        self.assertEqual([r["no"] for r in doc["requests"]], [1, 2])
        self.assertEqual(doc["requests"][0]["memo"], "json 메모")
        self.assertEqual(doc["check_rows"][0]["requests"], [2])

    def test_run_files_same_second_no_overwrite(self):
        self.apply([_item(value="첫값")])
        out, first = self._run_files()
        before = {p: self._load_one(p) for p in first}
        self.apply([_item(value="둘째값")])
        out, second = self._run_files()
        self.apply([_item(value="RUN2값")], run=RUN2)
        out, both = self._run_files(runs=(RUN, RUN2, RUN))
        for p, body in before.items():
            with open(p, encoding="utf-8") as f:
                self.assertEqual(f.read(), body)
        stems = lambda ps: sorted({os.path.splitext(os.path.basename(p))[0] for p in ps})
        self.assertEqual(stems(second), ["taxonomy_revisit_20261005_090807_2"])
        self.assertEqual(stems(both), ["taxonomy_revisit_20261005_090807_3", "taxonomy_revisit_20261005_090807_4"])
        self.assertEqual(len(os.listdir(out)), 12)
        self.assertIn("둘째값", self._load(second)[0])
        self.assertNotIn("둘째값", before[first[0]] + before[first[1]] + before[first[2]])


class RevisitIntegrationTest(unittest.TestCase):
    """mock 파이프라인 1회. PipelineTest와 작업 폴더를 공유하지 않는다."""

    @classmethod
    def setUpClass(cls):
        cls.w = _Ws()
        cls.ws = cls.w.ws
        # 이 작업 폴더의 taxonomy_path는 저장소 taxonomy/taxonomy.json다. 실행별 재검토 파일이 저장소에 남지 않도록
        # 파일 폴더만 임시 작업 폴더 안으로 돌린다(위치 규칙 자체는 단위 테스트가 본다).
        cls.rv_dir = os.path.join(cls.w.dir, "rvtax", revisit.REQUESTS_DIRNAME)
        cls._rv_patch = mock.patch.object(revisit, "requests_dir", lambda ws: cls.rv_dir)
        cls._rv_patch.start()
        cls.addClassCleanup(cls._rv_patch.stop)
        cls.before = set()
        for root, _, files in os.walk(cls.ws.root):
            cls.before |= {os.path.join(root, f) for f in files}
        with contextlib.redirect_stdout(io.StringIO()):
            cls.run_id, _ = pipeline.run_all(cls.ws, DUMMY_DIR, transport=MockChatTransport(responder))
        cls.rv_after_run_all = os.path.exists(cls.rv_dir)
        cls.con = store.connect(cls.ws.work_db)
        cls.tax, _ = pipeline.load_taxonomy(cls.ws)
        row = cls.con.execute(
            "SELECT f.chunk_id, l.key FROM flagged_chunks f JOIN labels l ON l.run_id=f.run_id AND l.chunk_id=f.chunk_id"
            " AND l.kind='axis' WHERE f.run_id=? ORDER BY f.chunk_id LIMIT 1", (cls.run_id,)).fetchone()
        cls.cid, cls.axis = row[0], row[1]
        cls.other = cls.con.execute(
            "SELECT chunk_id FROM flagged_chunks WHERE run_id=? AND chunk_id<>? ORDER BY chunk_id LIMIT 1",
            (cls.run_id, cls.cid)).fetchone()[0]
        cls.unflagged = cls.con.execute(
            "SELECT chunk_id FROM chunks WHERE chunk_id NOT IN (SELECT chunk_id FROM flagged_chunks WHERE run_id=?)"
            " LIMIT 1", (cls.run_id,)).fetchone()[0]

    @classmethod
    def tearDownClass(cls):
        cls.con.close()
        shutil.rmtree(cls.w.dir, ignore_errors=True)

    def setUp(self):
        inbox = self.ws.path("inbox")
        for fn in os.listdir(inbox):
            if fn.endswith(".json"):
                os.remove(os.path.join(inbox, fn))
        shutil.rmtree(self.rv_dir, ignore_errors=True)

    def rv_files(self):
        return sorted(os.listdir(self.rv_dir)) if os.path.isdir(self.rv_dir) else []

    def doc(self, revisits, **kw):
        d = {"kind": "review", "run_id": self.run_id, "corrections": [], "chunk_status": [], "synonyms": [],
             "revisits": revisits}
        d.update(kw)
        return d

    def put(self, name, doc, age=0):
        p = self.ws.path("inbox", name)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)
        if age:
            t = time.time() - age
            os.utime(p, (t, t))
        return p

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(list(argv) + ["--workspace", self.ws.root])
        self.assertEqual(rc, 0, err.getvalue())
        return out.getvalue() + err.getvalue()

    def read(self, *parts):
        with open(self.ws.path(*parts), encoding="utf-8") as f:
            return f.read()

    def rv_rows(self):
        return self.con.execute("SELECT chunk_id, target_kind, target_key, proposed_value FROM revisit_requests"
                                " WHERE review_run_id=? ORDER BY chunk_id", (self.run_id,)).fetchall()

    def test_review_data_has_rules(self):
        path, n = review.build_review(self.ws, self.con, self.run_id, self.tax)
        with open(path, encoding="utf-8") as f:
            html = f.read()
        self.assertNotIn("/*__DATA__*/null", html)
        self.assertIn('"revisit_rules": {"axis": ["NO_FIT_VALUE", "AMBIGUOUS_DEF", "VALUE_OVERLAP", "OTHER"]', html)
        self.assertIn('"question_blank": ["NEED_QUESTION"]', html)
        self.assertIn('"revisit_memo_max": 500', html)
        self.assertIn('"revisit_short_max": 60', html)
        self.assertIn('"NO_FIT_VALUE": "맞는 값이 없음"', html)
        self.assertIn('"hierarchical": ', html)

    def test_apply_via_inbox(self):
        self.put("review_x.json", self.doc([_item(cid=self.cid, key=self.axis, value="새값-가"),
                                            _item(cid=self.unflagged, key=self.axis)]))
        res = review.apply_inbox(self.ws, self.con, self.tax)
        self.assertTrue(all(len(r) == 5 for r in res))
        codes = {r[1]: r for r in res}
        self.assertEqual(codes["OK"][2], 1)
        self.assertEqual(codes["REVISIT_CHUNK_NOT_FLAGGED"][2:], (1, "review", self.run_id))
        self.assertEqual(codes["OK"][0], codes["REVISIT_CHUNK_NOT_FLAGGED"][0])
        self.assertEqual(len(self.rv_rows()), 1)

    def test_not_list_format_invalid(self):
        self.put("review_x.json", self.doc("목록 아님"))
        res = review.apply_inbox(self.ws, self.con, self.tax)
        self.assertEqual([r[1] for r in res], ["FORMAT_INVALID"])

    def test_superseded_still_applies(self):
        self.put("review_old.json", self.doc([_item(cid=self.cid, key=self.axis, value="옛값")]), age=100)
        self.put("review_new.json", self.doc([_item(cid=self.other, key=self.axis, value="새값")]))
        res = review.apply_inbox(self.ws, self.con, self.tax)
        self.assertEqual(sorted(r[1] for r in res), ["OK", "SUPERSEDED"])
        self.assertEqual([(r[0], r[3]) for r in self.rv_rows()], [(self.other, "새값")])

    def test_savepoint_isolation(self):
        corr = [{"chunk_id": self.cid, "target": "axis", "key": self.axis, "value": ["unknown"]}]
        self.put("review_ok.json", self.doc([_item(cid=self.cid, key=self.axis, value="격리값")], corrections=corr), age=100)
        self.put("compare_bad.json", {"kind": "compare", "run_id": self.run_id, "marks": 5})
        res = review.apply_inbox(self.ws, self.con, self.tax)
        self.assertEqual(sorted(r[1] for r in res), ["FORMAT_INVALID", "OK"])
        self.assertEqual([r[3] for r in self.rv_rows()], ["격리값"])
        n = self.con.execute("SELECT COUNT(*) FROM corrections WHERE review_run_id=? AND target_kind='axis'",
                             (self.run_id,)).fetchone()[0]
        self.assertEqual(n, 1)

    def _snapshot(self):
        corr = [tuple(r) for r in self.con.execute(
            "SELECT * FROM corrections WHERE review_run_id=? ORDER BY chunk_id, target_kind, target_key", (self.run_id,))]
        rv = [tuple(r) for r in self.con.execute(
            "SELECT * FROM revisit_requests WHERE review_run_id=? ORDER BY chunk_id, target_kind, target_key",
            (self.run_id,))]
        return corr, rv

    def test_savepoint_rollback_keeps_previous(self):
        # 첫 문서(교정 + 요청)를 먼저 반영한다.
        corr = [{"chunk_id": self.cid, "target": "axis", "key": self.axis, "value": ["unknown"]}]
        self.put("review_ok.json", self.doc([_item(cid=self.cid, key=self.axis, value="롤백전값")], corrections=corr),
                 age=100)
        self.assertEqual([r[1] for r in review.apply_inbox(self.ws, self.con, self.tax)], ["OK"])
        before = self._snapshot()
        self.assertEqual(len(before[0]), 1)
        self.assertEqual(len(before[1]), 1)
        # 같은 실행의 더 새 문서: 교정은 다르고 revisits가 형식 오류다. 첫 문서는 SUPERSEDED, 새 문서만 반영 시도된다.
        corr2 = [{"chunk_id": self.other, "target": "axis", "key": self.axis, "value": ["다른값"]},
                 {"chunk_id": self.cid, "target": "axis", "key": self.axis, "value": ["또다른값"]}]
        self.put("review_bad.json", self.doc("x", corrections=corr2))
        res = review.apply_inbox(self.ws, self.con, self.tax)
        self.assertEqual(sorted(r[1] for r in res), ["FORMAT_INVALID", "SUPERSEDED"])
        self.assertEqual(self._snapshot(), before)

    def test_too_many_revisits_format_invalid(self):
        self.put("review_x.json", self.doc([None] * (revisit.REVISITS_MAX + 1)))
        res = review.apply_inbox(self.ws, self.con, self.tax)
        self.assertEqual([r[1] for r in res], ["FORMAT_INVALID"])

    def test_run_id_invalid(self):
        mark = "ZZRID-%s" % uuid.uuid4().hex[:8]
        self.put("review_dict.json", self.doc([], run_id={"id": mark}), age=300)
        self.put("review_space.json", self.doc([], run_id=mark + " x"), age=200)
        self.put("review_nl.json", self.doc([], run_id=self.run_id + "\n"), age=100)
        self.put("review_ok.json", self.doc([_item(cid=self.cid, key=self.axis, value="정상값")]))
        res = review.apply_inbox(self.ws, self.con, self.tax)
        self.assertTrue(all(len(r) == 5 for r in res))
        self.assertEqual(sorted(r[1] for r in res), ["OK"] + ["RUN_ID_INVALID"] * 3)
        for r in res:
            if r[1] == "RUN_ID_INVALID":
                self.assertEqual(r[2:], (0, "review", ""))
        self.assertEqual([(r[0], r[3]) for r in self.rv_rows()], [(self.cid, "정상값")])
        console = self.cli("apply")
        self.assertEqual(console.count("RUN_ID_INVALID"), 3)
        self.assertNotIn(mark, console)

    def test_data_lt_escaped(self):
        evil = "앞 <!--<script>x</script> </SCRIPT 뒤"
        self.con.execute("UPDATE chunks SET text=? WHERE chunk_id=?", (evil, self.cid))
        try:
            path, _ = review.build_review(self.ws, self.con, self.run_id, self.tax)
        finally:
            self.con.rollback()
        html = self.read("screens", "review.html")
        self.assertEqual(len(re.findall(r"<script\b", html, re.I)), 1)
        self.assertNotIn("<!--", html)
        m = re.search(r"const DATA = (.*);\n", html)
        data = json.loads(m.group(1))
        self.assertEqual([c["text"] for c in data["chunks"] if c["chunk_id"] == self.cid], [evil])
        # 같은 직렬화를 쓰는 다른 화면도 확인한다.
        for name in ("compare.html", "results.html"):
            out = review.fill_template(name, {"text": evil})
            self.assertEqual(len(re.findall(r"<script\b", out, re.I)), 1, name)
            self.assertNotIn("<!--", out, name)

    def test_cli_apply_no_memo_leak(self):
        mark = "ZZMEMO-%s" % uuid.uuid4().hex
        prop = "ZZPROP-%s" % uuid.uuid4().hex[:8]
        self.put("review_x.json", self.doc([
            _item(cid=self.cid, key=self.axis, value=prop, memo=mark + " <script>|"),
            _item(cid=self.other, target="question", key="", reason="NEED_QUESTION", value=None, memo=mark),
            _item(cid=self.unflagged, key=self.axis, memo=mark),
            dict(_item(cid=self.cid, key="다른축", reason="OTHER", value=None), memo=mark * 20)]))
        console = self.cli("apply")
        self.assertIn("[apply] taxonomy 재검토 요청 누적 3건 → reports/taxonomy_revisit.md", console)
        self.assertIn("REVISIT_CHUNK_NOT_FLAGGED (1건)", console)
        self.assertIn("REVISIT_MEMO_TRUNCATED (1건)", console)
        leak = [console]
        rdir = self.ws.path("reports")
        for fn in os.listdir(rdir):
            if not fn.startswith("taxonomy_revisit."):
                with open(os.path.join(rdir, fn), encoding="utf-8") as f:
                    leak.append(f.read())
        log = self.ws.path("logs", "labelbot.log")
        if os.path.isfile(log):
            leak.append(self.read("logs", "labelbot.log"))
        for body in leak:
            self.assertNotIn(mark, body)
            self.assertNotIn(prop, body)
        self.assertIn(mark, self.read("reports", "taxonomy_revisit.md"))
        self.assertIn(mark, self.read("reports", "taxonomy_revisit.jsonl"))
        self.assertIn(prop, self.read("reports", "taxonomy_revisit.md"))
        n = self.con.execute("SELECT COUNT(*) FROM revisit_requests WHERE memo LIKE ?", ("%" + mark + "%",)).fetchone()[0]
        self.assertEqual(n, 3)

    def test_candidates_top_line(self):
        self.put("review_x.json", self.doc([_item(cid=self.cid, key=self.axis), _item(cid=self.other, key=self.axis)]))
        self.cli("apply")
        lines = self.read("reports", "candidates.md").split("\n")
        n = revisit.count(self.con)
        self.assertEqual(n, 2)
        self.assertEqual(lines[1], "- taxonomy 재검토 요청: 누적 2건 → [taxonomy_revisit.md](taxonomy_revisit.md)")
        self.put("review_y.json", self.doc([]))
        self.cli("apply")
        self.assertEqual(self.read("reports", "candidates.md").split("\n")[1], "- taxonomy 재검토 요청: 0건")

    def test_report_command_writes(self):
        self.put("review_x.json", self.doc([_item(cid=self.cid, key=self.axis)]))
        self.cli("apply")
        for ext in ("md", "jsonl"):
            os.remove(self.ws.path("reports", "taxonomy_revisit.%s" % ext))
        console = self.cli("report")
        self.assertIn("taxonomy 재검토 요청 누적 1건", console)
        for ext in ("md", "jsonl"):
            self.assertTrue(os.path.isfile(self.ws.path("reports", "taxonomy_revisit.%s" % ext)))

    def test_reports_no_names(self):
        self.put("review_x.json", self.doc([_item(cid=self.cid, key=self.axis, memo="가짜 메모"),
                                            _item(cid=self.other, target="new_axis", key="", reason="NEW_AXIS",
                                                  value="가짜축")]))
        self.cli("apply")
        for ext in ("md", "jsonl"):
            body = self.read("reports", "taxonomy_revisit.%s" % ext)
            self.assertIn(self.cid, body)
            self.assertNotIn(".pptx", body)
            self.assertNotIn("dummy pptx files", body)
            self.assertNotIn(DUMMY_DIR, body)
            self.assertNotIn(DUMMY_DIR.replace("\\", "\\\\"), body)

    def test_new_files_allowed_ext(self):
        self.put("review_x.json", self.doc([_item(cid=self.cid, key=self.axis)]))
        self.cli("apply")
        self.cli("report")
        new = []
        for root, _, files in os.walk(self.ws.root):
            new += [os.path.join(root, f) for f in files if os.path.join(root, f) not in self.before]
        self.assertTrue([p for p in new if p.endswith("taxonomy_revisit.md")])
        self.assertEqual([p for p in new if not p.lower().endswith(util.ALLOWED_EXT)], [])
        self.assertFalse([p for p in new if p.endswith(("-journal", "-wal"))])

    def test_run_files_via_cli_apply(self):
        self.assertFalse(self.rv_after_run_all)  # run_all은 실행별 파일을 쓰지 않는다
        mark = "ZZRVF-%s" % uuid.uuid4().hex
        self.put("review_x.json", self.doc([_item(cid=self.cid, key=self.axis, value="새값-파일", memo=mark),
                                            _item(cid=self.other, reason="OTHER", key=self.axis, value=None, memo=mark)]))
        console = self.cli("apply")
        names = self.rv_files()
        self.assertEqual(len(names), 3)
        self.assertEqual({os.path.splitext(n)[1] for n in names}, {".md", ".html", ".json"})
        for n in names:
            self.assertRegex(n, r"^taxonomy_revisit_\d{8}_\d{6}(_\d+)?\.(md|html|json)$")
        self.assertIn("[apply] taxonomy 재검토 요청 파일 3개 → rvtax/taxonomy_revisit_requests/", console)
        self.assertNotIn(mark, console)
        self.assertNotIn("새값-파일", console)
        log = self.ws.path("logs", "labelbot.log")
        if os.path.isfile(log):
            self.assertNotIn(mark, self.read("logs", "labelbot.log"))
        with open(os.path.join(self.rv_dir, [n for n in names if n.endswith(".json")][0]), encoding="utf-8") as f:
            doc = json.load(f)
        self.assertEqual(doc["review_run_id"], self.run_id)
        self.assertEqual([r["memo"] for r in doc["requests"]], [mark, mark])
        # 같은 파일을 다시 apply하면 같은 초여도 덮어쓰지 않고 새 이름으로 쓴다.
        self.cli("apply")
        self.assertEqual(len(self.rv_files()), 6)

    def test_run_files_not_written(self):
        self.put("review_x.json", self.doc([_item(cid=self.cid, key=self.axis)]))
        self.cli("apply")
        self.setUp()  # inbox·파일 폴더 비우기
        # 레거시 문서(revisits 키 없음): 기존 요청은 그대로지만 파일은 쓰지 않는다.
        legacy = self.doc([])
        del legacy["revisits"]
        self.put("review_y.json", legacy)
        console = self.cli("apply")
        self.assertEqual(revisit.count(self.con), 1)
        self.assertEqual(self.rv_files(), [])
        self.assertNotIn("재검토 요청 파일", console)
        self.setUp()
        # 요청 0건
        self.put("review_z.json", self.doc([_item(cid=self.unflagged, key=self.axis)]))
        self.cli("apply")
        self.assertEqual(self.rv_files(), [])
        self.setUp()
        # report 명령
        self.put("review_w.json", self.doc([_item(cid=self.cid, key=self.axis)]))
        review.apply_inbox(self.ws, self.con, self.tax)
        console = self.cli("report")
        self.assertEqual(self.rv_files(), [])
        self.assertNotIn("재검토 요청 파일", console)

    def _summary(self, ws_dir):
        r = subprocess.run([sys.executable, SUMMARY, "--workspace", ws_dir], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace"))
        return json.loads(r.stdout.decode("utf-8"))

    def test_summary_counts(self):
        self.put("review_x.json", self.doc([_item(cid=self.cid, key=self.axis, memo="ZZSUM"),
                                            _item(cid=self.other, key=self.axis, reason="OTHER", value=None, memo="m")]))
        review.apply_inbox(self.ws, self.con, self.tax)
        out = self._summary(self.ws.root)
        self.assertEqual(out["revisits"]["total"], revisit.count(self.con))
        self.assertEqual(out["revisits"]["run"], 2)
        self.assertEqual(out["revisits"]["by_reason"], {"NO_FIT_VALUE": 1, "OTHER": 1})
        self.assertNotIn("ZZSUM", json.dumps(out, ensure_ascii=False))
        # v1 DB 흉내: 현재 스키마로 만든 DB 사본에서 revisit_requests만 지운다.
        old = tempfile.mkdtemp(prefix="labelbot_v1_")
        try:
            dst = sqlite3.connect(os.path.join(old, "work.sqlite"))
            self.con.backup(dst)
            dst.execute("DROP TABLE revisit_requests")
            dst.execute("UPDATE meta SET value='1' WHERE key='schema_version'")
            dst.commit()
            dst.close()
            out = self._summary(old)
            self.assertEqual(out["revisits"], {"run": 0, "total": 0, "runs": 0, "by_reason": {}})
            self.assertEqual(out["run_id"], self.run_id)
        finally:
            shutil.rmtree(old, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
