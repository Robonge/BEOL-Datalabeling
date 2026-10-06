"""axis-update 회귀: taxonomy 축이 바뀐 작업 폴더에서 바뀐 축만 1차 분류로 다시 라벨링한다.

합성 taxonomy(메모리 xlsx, 실제 taxonomy.xlsx는 열지 않는다)로 mock 실행 A를 돌리고 검수 교정을 넣은 뒤, taxonomy를
바꿔(축 추가·삭제, 값 추가만, 값 삭제) axis-update 실행 B를 돌린다. mock transport가 받은 작업 종류로 LLM 호출 수를 센다.
B의 부분 분류는 일부 chunk(본문 해시 버킷 6)에 잘못된 JSON을 돌려줘 부분 분류 실패를 만든다.
활성 토글(Y→N, N→Y), 멈춤 사유, 잠금, 적재 대기, 중단 뒤 재시도는 두 번째 작업 폴더에서 본다.
"""
import contextlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from labelbot import axisupdate, cli, embed, finals, pipeline, review, store, taxdiff, util, vectorpush
from labelbot.mock import MockChatTransport, MockEmbedTransport
from labelbot.workspace import Workspace
from tests.test_new_axis_flow import run_cli
from tests.test_pipeline import DUMMY_DIR, _bucket, responder
from tests.test_taxonomy import axis_row, base_sheets, build, tax_row

NEW, GONE, CHANGED, ONLY, KEEP = "평가 조건", "의사결정 상태", "불량 모드", "공정 단계", "구조/레이어"
PARTIAL_FAIL = 6  # test_pipeline.responder에서 정상 버킷. B의 부분 분류만 이 버킷을 실패시킨다
SUPABASE = {"enabled": True, "url": "https://example-proj.supabase.co"}


def before_sheets():
    s = base_sheets()
    s["taxonomy"] += [axis_row(ONLY), tax_row(ONLY, "Etch"), tax_row(ONLY, "CMP")]
    s["questions"].append(["Q-DS-001", "채택되었는가.", "%s=adopted" % GONE, 4])
    return s


def after_sheets():
    """축 추가(평가 조건)·삭제(의사결정 상태), 값 삭제(불량 모드 EM), 값 추가만(공정 단계 Clean)."""
    s = before_sheets()
    s["taxonomy"] = [r for r in s["taxonomy"] if r[0] != GONE and not (r[0] == CHANGED and r[1] == "EM")]
    s["questions"] = [q for q in s["questions"] if q[0] != "Q-DS-001"]  # 삭제 축의 질문 행은 taxonomy에 남을 수 없다
    s["taxonomy"] += [tax_row(ONLY, "Clean"), axis_row(NEW), tax_row(NEW, "POR"), tax_row(NEW, "Split")]
    s["questions"].append(["Q-NEW-001", "POR 조건 대비 평가인가.", "%s=POR" % NEW, 3])
    return s


class Counting:
    """mock 응답은 test_pipeline.responder 그대로, 작업 종류(classify·question_gen·label)만 센다.
    부분 분류(axis-update) 요청 중 버킷 PARTIAL_FAIL chunk에는 잘못된 JSON을 돌려준다."""

    def __init__(self):
        self.tasks = []
        self.bodies = []

    def __call__(self, body, hint):
        self.tasks.append((hint or {}).get("task"))
        self.bodies.append(json.dumps(body, ensure_ascii=False))
        if "## 분류할 축" in self.bodies[-1] and _bucket((hint or {}).get("text") or "") == PARTIAL_FAIL:
            return "{not json"
        return responder(body, hint)


class Sink:
    def __init__(self):
        self.rows = []

    def send(self, rows):
        self.rows += rows


def push_all(ws, con, run_id):
    """mock 임베딩 후 sink로 적재한다. supabase 설정은 이 호출 동안만 켠다."""
    embed.embed(ws, con, run_id, transport=MockEmbedTransport())
    sink = Sink()
    ws.config["supabase"].update(SUPABASE)
    try:
        vectorpush.push(ws, con, run_id, sink=sink)
    finally:
        ws.config["supabase"].update({"enabled": False, "url": ""})
    return sink.rows


def adopting_responder(body, hint):
    """base 실행 A 전용: 본문이 없는 mock이 GONE 축에 값을 못 고르므로, 일부 chunk(본문 해시 5분의 1)의 GONE 축을
    adopted로 분류해 승인 질문 Q-DS-001이 매핑·답변되게 한다. 근거는 본문 첫 줄(인용 검증 통과)."""
    out = responder(body, hint)
    if hint.get("task") != "classify":
        return out
    obj = json.loads(out)
    text = hint.get("text") or ""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    ax = obj["axes"].get(GONE)
    if ax and ax["values"] == ["해당 없음"] and lines and util.sha256_text(text)[0] in "01":
        obj["axes"][GONE] = {"values": ["adopted"], "evidence": lines[0], "confidence": 0.9}
    return json.dumps(obj, ensure_ascii=False)


def make_ws(sheets):
    d = tempfile.mkdtemp(prefix="labelbot_ws_")
    tax_path = os.path.join(d, "tax_fixture.xlsx")
    with open(tax_path, "wb") as f:
        f.write(build(sheets))
    cfg = {"taxonomy_path": tax_path, "input_root": DUMMY_DIR,
           "llm": {"transport": "mock", "model": "mock", "max_retries": 1},
           "embedding": {"transport": "mock"}, "supabase": {"enabled": False}}
    with open(os.path.join(d, "pipeline.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    return d, tax_path, Workspace(d)


def write_tax(path, sheets):
    with open(path, "wb") as f:
        f.write(build(sheets))


def apply_doc(ws, con, tax, doc, name):
    path = ws.path("inbox", name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    try:
        return review.apply_inbox(ws, con, tax, kind="review")
    finally:
        os.remove(path)


def signal(ws, kind, run_id):
    os.makedirs(ws.path("signals"), exist_ok=True)
    with open(ws.path("signals", "review_%s_%s.json" % (kind, run_id)), "w", encoding="utf-8") as f:
        f.write("{}")


def labels(con, run_id, where="1", args=()):
    return sorted(tuple(r) for r in con.execute(
        "SELECT chunk_id, kind, key, value FROM labels WHERE run_id=? AND %s" % where, (run_id,) + tuple(args)))


class AxisUpdateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir, cls.tax_path, cls.ws = make_ws(before_sheets())
        cls.run_a, _ = pipeline.run_all(cls.ws, DUMMY_DIR, transport=MockChatTransport(adopting_responder),
                                        use_feedback=False)
        cls.con = store.connect(cls.ws.work_db)
        tax_a, _ = pipeline.load_taxonomy(cls.ws)
        con, a = cls.con, cls.run_a
        # 교정할 chunk: 공통 질문 답과 Q-FM-001 답이 있는 불량 chunk 하나, 확인할 불량 chunk 하나
        # (B에서 부분 분류가 실패하는 버킷은 피한다)
        has = "EXISTS(SELECT 1 FROM labels l WHERE l.run_id=f.run_id AND l.chunk_id=f.chunk_id AND l.key=?)"

        def pick(sql, args):
            return next(r[0] for r in con.execute(sql, args) if _bucket(r[1]) != PARTIAL_FAIL)
        cls.c_fix = pick("SELECT f.chunk_id, c.text FROM flagged_chunks f JOIN chunks c ON c.chunk_id=f.chunk_id"
                         " WHERE run_id=? AND %s AND %s ORDER BY f.chunk_id" % (has, has), (a, "Q-COM-001", "Q-FM-001"))
        cls.c_ok = pick("SELECT f.chunk_id, c.text FROM flagged_chunks f JOIN chunks c ON c.chunk_id=f.chunk_id"
                        " WHERE run_id=? AND %s AND f.chunk_id<>? ORDER BY f.chunk_id" % has, (a, "Q-COM-001", cls.c_fix))
        corr = [{"chunk_id": cls.c_fix, "target": "axis", "key": KEEP, "value": ["V1"]},
                {"chunk_id": cls.c_fix, "target": "axis", "key": ONLY, "value": ["Etch"]},
                {"chunk_id": cls.c_fix, "target": "axis", "key": CHANGED, "value": ["Reliability"]},
                {"chunk_id": cls.c_fix, "target": "axis", "key": GONE, "value": ["adopted"]},
                {"chunk_id": cls.c_fix, "target": "answer", "key": "Q-COM-001", "value": "O"},
                {"chunk_id": cls.c_fix, "target": "answer", "key": "Q-FM-001", "value": "O"}]
        res = apply_doc(cls.ws, con, tax_a, {"kind": "review", "run_id": a, "synonyms": [], "corrections": corr,
                                             "chunk_status": [{"chunk_id": cls.c_ok, "status": "confirmed"}]},
                        "review_a.json")
        assert [r[1] for r in res] == ["OK"], res
        cls.n_corrections = con.execute("SELECT COUNT(*) FROM corrections").fetchone()[0]
        write_tax(cls.tax_path, after_sheets())
        cls.tax, _ = pipeline.load_taxonomy(cls.ws)
        cls.counting = Counting()
        cls.plan, cls.run_b, cls.ctx = pipeline.run_axis_update(cls.ws, transport=MockChatTransport(cls.counting),
                                                                use_feedback=False)
        cls.final_b = finals.final_labels(con, cls.run_b)
        # B에서 부분 분류가 실패한 chunk(chunk_type은 이어받음)와 A에서 분류가 실패한 chunk
        typed_b = {r[0] for r in con.execute("SELECT chunk_id FROM labels WHERE run_id=? AND kind='chunk_type'",
                                             (cls.run_b,))}
        failed_b = {r[0] for r in con.execute("SELECT target_id FROM failures WHERE run_id=? AND stage='classify'",
                                              (cls.run_b,))}
        cls.partial_failed = sorted(failed_b & typed_b)
        cls.prev_failed = sorted(failed_b - typed_b)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()
        shutil.rmtree(cls.dir, ignore_errors=True)

    # plan(D2)·최신 실행 선택
    def test_plan_axes(self):
        p = self.plan
        self.assertEqual((p["code"], p["prev_run"]), (None, self.run_a))
        self.assertEqual(p["target"], sorted([NEW, CHANGED, ONLY]))
        self.assertEqual((p["removed"], p["values_added_only"]), ([GONE], [ONLY]))
        self.assertGreater(p["dropped_answers"], 0)
        self.assertEqual(p["dropped_corrections"], 2)  # 불량 모드·의사결정 상태 교정

    def test_run_meta(self):
        info = axisupdate.run_info(self.con, self.run_b)
        self.assertEqual((info["parent"], info["target"], info["removed"]), (self.run_a, self.plan["target"], [GONE]))
        self.assertIsNone(axisupdate.run_info(self.con, self.run_a))
        r = self.con.execute("SELECT command, finished_at FROM runs WHERE run_id=?", (self.run_b,)).fetchone()
        self.assertEqual(r[0], "axis-update")
        self.assertIsNotNone(r[1])

    def test_latest_label_run_picks_axis_update(self):
        self.assertEqual(store.LABEL_COMMANDS, ("run", "axis-update"))
        self.assertEqual(store.latest_label_run(self.con), self.run_b)
        self.assertEqual(store.latest_run(self.con), self.run_b)  # cli 기본 --run

    # 상속
    def test_non_target_labels_inherited(self):
        keep = "kind IN ('chunk_type','extract') OR (kind='axis' AND key IN (?, '제품·세대'))"
        self.assertEqual(labels(self.con, self.run_b, keep, (KEEP,)), labels(self.con, self.run_a, keep, (KEEP,)))
        com = "kind='answer' AND key='Q-COM-001'"
        self.assertEqual(labels(self.con, self.run_b, com), labels(self.con, self.run_a, com))
        n_files = self.con.execute("SELECT COUNT(*) FROM file_locations WHERE last_seen_run=?", (self.run_b,)).fetchone()[0]
        self.assertGreater(n_files, 0)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM file_locations WHERE last_seen_run=?",
                                          (self.run_a,)).fetchone()[0], 0)

    def test_label_failures_copied(self):
        q = "SELECT target_id FROM failures WHERE run_id=? AND stage='label' ORDER BY target_id"
        self.assertEqual([r[0] for r in self.con.execute(q, (self.run_b,))], [r[0] for r in self.con.execute(q, (self.run_a,))])

    # 삭제 축
    def test_removed_axis_absent_everywhere(self):
        self.assertEqual(labels(self.con, self.run_b, "kind='axis' AND key=?", (GONE,)), [])
        self.assertNotIn(GONE, self.final_b[self.c_fix]["axes"])  # 옛 교정이 되살리지 않는다
        out = sqlite3.connect(self.ws.path("out", "labeling.sqlite"))
        try:
            self.assertEqual(out.execute("SELECT COUNT(*) FROM facet_labels WHERE axis=?", (GONE,)).fetchone()[0], 0)
            self.assertGreater(out.execute("SELECT COUNT(*) FROM facet_labels WHERE axis=?", (NEW,)).fetchone()[0], 0)
            self.assertEqual(out.execute("SELECT value FROM meta WHERE key='run_id'").fetchone()[0], self.run_b)
        finally:
            out.close()

    def test_vector_payload_axes(self):
        rows = push_all(self.ws, self.con, self.run_b)
        self.assertGreater(len(rows), 0)
        target = set(self.plan["target"])
        self.assertTrue(all(GONE not in r["labels"]["axes"] and target <= set(r["labels"]["axes"]) for r in rows))
        # 부분 분류가 실패한 chunk는 대상 축 없이 적재(기존 행 덮어쓰기)하지 않는다
        self.assertGreater(len(self.partial_failed), 0)
        self.assertFalse({r["chunk_id"] for r in rows} & set(self.partial_failed))

    # 부분 분류 실패(B1)
    def test_partial_failure_not_exported(self):
        self.assertEqual(finals.incomplete(self.con, self.run_b, self.final_b), set(self.partial_failed))
        out = sqlite3.connect(self.ws.path("out", "labeling.sqlite"))
        try:
            q = ",".join("?" * len(self.partial_failed))
            self.assertEqual(out.execute("SELECT COUNT(*) FROM facet_labels WHERE chunk_id IN (%s)" % q,
                                         self.partial_failed).fetchone()[0], 0)
        finally:
            out.close()

    def test_partial_failure_filled_by_human_is_complete(self):
        cid = next(c for c in self.partial_failed if self.con.execute(
            "SELECT 1 FROM flagged_chunks WHERE run_id=? AND chunk_id=?", (self.run_b, c)).fetchone())
        doc = {"kind": "review", "run_id": self.run_b, "chunk_status": [], "synonyms": [], "corrections": [
            {"chunk_id": cid, "target": "axis", "key": NEW, "value": ["POR"]},
            {"chunk_id": cid, "target": "axis", "key": CHANGED, "value": ["Short"]},
            {"chunk_id": cid, "target": "axis", "key": ONLY, "value": ["해당 없음"]}]}
        try:
            self.assertEqual({r[1] for r in apply_doc(self.ws, self.con, self.tax, doc, "review_fill.json")}, {"OK"})
            labels_b = finals.final_labels(self.con, self.run_b, [cid])
            self.assertEqual(finals.incomplete(self.con, self.run_b, labels_b), set())
        finally:
            self.con.execute("DELETE FROM corrections WHERE review_run_id=?", (self.run_b,))
            self.con.commit()

    # 기준 실행 분류 실패(M2): 범위에서 빼고 실패 기록을 옮겨 CLASSIFY_FAILED로 남긴다
    def test_prev_classify_failures_kept_flagged(self):
        self.assertGreater(len(self.prev_failed), 0)
        prev_a = {r[0] for r in self.con.execute(
            "SELECT target_id FROM failures WHERE run_id=? AND stage='classify' AND target_id NOT IN"
            " (SELECT chunk_id FROM labels WHERE run_id=? AND kind='chunk_type')", (self.run_a, self.run_a))}
        self.assertEqual(set(self.prev_failed), prev_a)
        scope = {c["chunk_id"] for c in axisupdate.scope_chunks(self.con, self.run_b)}
        self.assertFalse(scope & prev_a)
        flagged = {r[0]: json.loads(r[1]) for r in self.con.execute(
            "SELECT chunk_id, reason_codes FROM flagged_chunks WHERE run_id=?", (self.run_b,))}
        self.assertTrue(all("CLASSIFY_FAILED" in flagged.get(c, []) for c in prev_a))
        self.assertEqual(labels(self.con, self.run_b, "chunk_id IN (%s)" % ",".join("?" * len(prev_a)), sorted(prev_a)), [])

    # LLM 호출(D3): 1차 분류만, chunk당 1회(형식 실패 chunk는 재시도 1회 더)
    def test_llm_calls_classify_only(self):
        self.assertEqual(set(self.counting.tasks), {"classify"})
        n_chunks = len(axisupdate.scope_chunks(self.con, self.run_b))
        failed = len(self.partial_failed)  # 형식 실패는 재시도 1회 더
        self.assertEqual(self.ctx.chat.calls + self.ctx.chat.cache_hits, n_chunks + failed)
        self.assertEqual(len(self.counting.tasks), self.ctx.chat.calls)

    def test_partial_prompt_asks_target_axes_only(self):
        body = next(b for b in self.counting.bodies if "## 다른 축의 확정 값" in b and "- %s:" % KEEP in b)
        asked = body.split("## 분류할 축", 1)[1].split("## 다른 축의 확정 값", 1)[0]
        for name in (NEW, CHANGED, ONLY):
            self.assertIn("### %s" % name, asked)
        self.assertNotIn("### %s" % KEEP, asked)
        self.assertNotIn("chunk_type", body.split("## 응답 형식", 1)[1])
        versions = {r[0] for r in self.con.execute(
            "SELECT DISTINCT prompt_version FROM labels WHERE run_id=? AND kind='axis' AND key=?", (self.run_b, NEW))}
        self.assertEqual(versions, {"classify-partial-v1"})

    def test_target_axes_labeled_for_classified_chunks(self):
        n_type = self.con.execute("SELECT COUNT(*) FROM labels WHERE run_id=? AND kind='chunk_type'",
                                  (self.run_b,)).fetchone()[0]
        for name in (NEW, CHANGED, ONLY):
            n = self.con.execute("SELECT COUNT(*) FROM labels WHERE run_id=? AND kind='axis' AND key=?",
                                 (self.run_b, name)).fetchone()[0]
            self.assertEqual(n, n_type - len(self.partial_failed), name)

    # taxdiff 해소
    def test_taxonomy_diff_resolved(self):
        code, lines, _ = run_cli("taxonomy-diff", "--workspace", self.dir)
        self.assertEqual(code, 0)
        d = json.loads(lines[0])
        self.assertEqual((d["run_id"], d["added"], d["removed"], d["changed"], d["values_added"]),
                         (self.run_b, [], [], [], {}))
        self.assertNotIn("values_removed", d)
        self.assertEqual(axisupdate.plan(self.ws, self.con, self.tax)["code"], axisupdate.NO_AXIS_CHANGE)

    # D4 답 정리
    def test_dropped_answers(self):
        b = self.run_b
        target = self.plan["target"]
        q = ",".join("?" * len(target))
        self.assertEqual(labels(self.con, b, "kind='answer' AND key='Q-FM-001'"), [])
        self.assertGreater(len(labels(self.con, self.run_a, "kind='answer' AND key='Q-FM-001'")), 0)
        gen = "kind='answer' AND key IN (SELECT qid FROM gen_questions WHERE axis IN (%s))" % q
        ctl = "kind='control' AND key IN (SELECT qid FROM ctl_questions WHERE axis IN (%s))" % q
        self.assertGreater(len(labels(self.con, self.run_a, gen, target)), 0)
        self.assertEqual(labels(self.con, b, gen, target), [])
        self.assertEqual(labels(self.con, b, ctl, target), [])
        keep_gen = "kind='answer' AND key IN (SELECT qid FROM gen_questions WHERE axis=?)"
        self.assertEqual(labels(self.con, b, keep_gen, (KEEP,)), labels(self.con, self.run_a, keep_gen, (KEEP,)))
        self.assertGreater(len(labels(self.con, b, keep_gen, (KEEP,))), 0)

    def test_removed_axis_answers_dropped(self):
        gen = "kind='answer' AND key IN (SELECT qid FROM gen_questions WHERE axis=?)"
        ctl = "kind='control' AND key IN (SELECT qid FROM ctl_questions WHERE axis=?)"
        self.assertGreater(len(labels(self.con, self.run_a, gen, (GONE,))), 0)
        self.assertGreater(len(labels(self.con, self.run_a, ctl, (GONE,))), 0)
        for where in (gen, ctl):
            self.assertEqual(labels(self.con, self.run_b, where, (GONE,)), [])
        self.assertGreater(len(labels(self.con, self.run_a, "key='Q-DS-001'")), 0)
        self.assertEqual(labels(self.con, self.run_b, "key='Q-DS-001'"), [])
        n_a = len(labels(self.con, self.run_a, "kind IN ('answer','control')"))
        n_b = len(labels(self.con, self.run_b, "kind IN ('answer','control')"))
        self.assertEqual(n_a - n_b, self.plan["dropped_answers"])

    # D5 교정 필터
    def test_corrections_filtered(self):
        d = self.final_b[self.c_fix]
        bot = finals.bot_labels(self.con, self.run_b, [self.c_fix])[self.c_fix]
        self.assertEqual((d["axes"][KEEP]["values"], d["axes"][KEEP]["review"]), (["V1"], finals.CORRECTED))
        self.assertEqual((d["axes"][ONLY]["values"], d["axes"][ONLY]["review"]), (["Etch"], finals.CORRECTED))
        self.assertEqual(d["axes"][CHANGED]["values"], bot["axes"][CHANGED]["values"])
        self.assertNotEqual(d["axes"][CHANGED]["review"], finals.CORRECTED)
        self.assertEqual(d["answers"]["Q-COM-001"]["answer"], "O")
        self.assertNotIn("Q-FM-001", d["answers"])
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM corrections").fetchone()[0], self.n_corrections)
        # 기준 실행 A의 확정 라벨은 그대로다(교정 행은 지우지 않는다)
        a = finals.final_labels(self.con, self.run_a, [self.c_fix])[self.c_fix]
        self.assertEqual((a["axes"][CHANGED]["values"], a["axes"][GONE]["values"]), (["Reliability"], ["adopted"]))

    # D6 확인 유지
    def test_confirmed_kept_for_non_target(self):
        a = finals.final_labels(self.con, self.run_a, [self.c_ok])[self.c_ok]
        self.assertEqual(a["axes"][KEEP]["review"], finals.CONFIRMED)
        d = self.final_b[self.c_ok]
        self.assertEqual(d["axes"][KEEP]["review"], finals.CONFIRMED)
        self.assertEqual(d["answers"]["Q-COM-001"]["review"], finals.CONFIRMED)
        for name in (NEW, CHANGED, ONLY):
            self.assertEqual(d["axes"][name]["review"], finals.UNREVIEWED, name)

    # 이번 검수의 확인은 대상 축에만(m12)
    def test_own_confirm_applies_to_target_axes_only(self):
        cid = self.con.execute("SELECT chunk_id FROM flagged_chunks WHERE run_id=? AND chunk_id NOT IN (?, ?)"
                               " AND reason_codes NOT LIKE '%CLASSIFY_FAILED%' ORDER BY chunk_id",
                               (self.run_b, self.c_fix, self.c_ok)).fetchone()[0]
        doc = {"kind": "review", "run_id": self.run_b, "synonyms": [], "corrections": [],
               "chunk_status": [{"chunk_id": cid, "status": "confirmed"}]}
        try:
            self.assertEqual({r[1] for r in apply_doc(self.ws, self.con, self.tax, doc, "review_ok.json")}, {"OK"})
            d = finals.final_labels(self.con, self.run_b, [cid])[cid]
            for name in (NEW, CHANGED, ONLY):
                self.assertEqual(d["axes"][name]["review"], finals.CONFIRMED, name)
            self.assertEqual(d["axes"][KEEP]["review"], finals.UNREVIEWED)
            self.assertTrue(all(a["review"] == finals.UNREVIEWED for a in d["answers"].values()))
        finally:
            self.con.execute("DELETE FROM corrections WHERE review_run_id=?", (self.run_b,))
            self.con.commit()

    # D7 불량
    def test_flags_from_target_axes_only(self):
        rows = self.con.execute("SELECT reason_codes, reason_axes FROM flagged_chunks WHERE run_id=?",
                                (self.run_b,)).fetchall()
        self.assertGreater(len(rows), 0)
        allowed = {"UNKNOWN_HIGH", "LOW_CONFIDENCE", "QUOTE_NOT_FOUND", "CLASSIFY_FAILED"}
        target = set(self.plan["target"])
        for codes, ra in rows:
            self.assertLessEqual(set(json.loads(codes)), allowed)
            ra = json.loads(ra)
            self.assertLessEqual(set(ra), set(json.loads(codes)))
            self.assertTrue(all(set(v) <= target for v in ra.values()), ra)
        self.assertTrue(any(json.loads(ra) for _, ra in rows))
        old = self.con.execute("SELECT reason_axes FROM flagged_chunks WHERE run_id=? LIMIT 1", (self.run_a,)).fetchone()
        self.assertIsInstance(json.loads(old[0]), dict)

    def test_judge_ignores_non_target_low_confidence(self):
        chunk = {"text": "본문", "warnings": "[\"W\"]"}
        bot = {"axes": {KEEP: {"values": ["M1"], "status": "value", "evidence": "", "confidence": 0.1},
                        NEW: {"values": ["POR"], "status": "value", "evidence": "", "confidence": 0.95}},
               "answers": {"Q-COM-001": {"answer": "O", "quote": "", "confidence": 0.1}}}
        cfg = {"unknown_ratio_min": 0.5, "confidence_min": 0.7}
        ra = {}
        self.assertEqual(review.judge_chunk(chunk, bot, False, True, cfg, {}, axes={NEW}, reason_axes=ra)[0], [])
        reasons = review.judge_chunk(chunk, bot, False, False, cfg, {}, reason_axes=ra)[0]
        self.assertEqual(reasons, ["LOW_CONFIDENCE", "PARSE_WARNING"])
        self.assertEqual(ra, {"LOW_CONFIDENCE": [KEEP]})

    # 검수 잠금(AXIS_NOT_TARGET)
    def test_apply_skips_non_target(self):
        cid = self.con.execute("SELECT chunk_id FROM flagged_chunks WHERE run_id=? AND chunk_id NOT IN (?, ?)"
                               " AND reason_codes NOT LIKE '%CLASSIFY_FAILED%' ORDER BY chunk_id",
                               (self.run_b, self.c_fix, self.c_ok)).fetchone()[0]
        doc = {"kind": "review", "run_id": self.run_b, "chunk_status": [], "synonyms": [], "corrections": [
            {"chunk_id": cid, "target": "axis", "key": NEW, "value": ["Split"]},
            {"chunk_id": cid, "target": "axis", "key": KEEP, "value": ["M1"]},
            {"chunk_id": cid, "target": "answer", "key": "Q-COM-001", "value": "X"}]}
        try:
            res = {r[1]: r[2] for r in apply_doc(self.ws, self.con, self.tax, doc, "review_b.json")}
            self.assertEqual(res, {"OK": 1, review.AXIS_NOT_TARGET: 2})
            d = finals.final_labels(self.con, self.run_b, [cid])[cid]
            self.assertEqual((d["axes"][NEW]["values"], d["axes"][NEW]["review"]), (["Split"], finals.CORRECTED))
        finally:
            self.con.execute("DELETE FROM corrections WHERE review_run_id=?", (self.run_b,))
            self.con.commit()

    # 멱등
    def test_start_is_idempotent(self):
        c = axisupdate.start(self.ws, self.con, self.plan, self.tax)
        try:
            copied = labels(self.con, c)
            self.assertEqual(copied, labels(self.con, self.run_b, "NOT (kind='axis' AND key IN (?,?,?))",
                                            self.plan["target"]))
            self.assertEqual(axisupdate.start(self.ws, self.con, self.plan, self.tax, run_id=c), c)
            self.assertEqual(labels(self.con, c), copied)
            self.assertGreater(self.con.execute("SELECT COUNT(*) FROM file_locations WHERE last_seen_run=?",
                                                (c,)).fetchone()[0], 0)
        finally:
            self.con.execute("UPDATE file_locations SET last_seen_run=? WHERE last_seen_run=?", (self.run_b, c))
            for table in ("labels", "failures", "runs"):
                self.con.execute("DELETE FROM %s WHERE run_id=?" % table, (c,))
            self.con.execute("DELETE FROM meta WHERE key LIKE ?", ("%:" + c,))
            self.con.commit()


class AxisUpdateGateTest(unittest.TestCase):
    """멈춤 사유(NO_PREVIOUS_RUN·NO_AXIS_CHANGE·REVIEW_IN_PROGRESS·PREV_NOT_REVIEWED)와 활성 토글."""

    @classmethod
    def setUpClass(cls):
        cls.dir, cls.tax_path, cls.ws = make_ws(base_sheets())
        cls.run_a, _ = pipeline.run_all(cls.ws, DUMMY_DIR, transport=MockChatTransport(responder), use_feedback=False)
        cls.con = store.connect(cls.ws.work_db)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_gates_then_active_toggle(self):
        tax, _ = pipeline.load_taxonomy(self.ws)
        self.assertEqual(axisupdate.plan(self.ws, self.con, tax)["code"], axisupdate.NO_AXIS_CHANGE)
        s = base_sheets()
        # 구조/레이어: 값을 모두 빼 비활성(Y→N, 삭제와 같음). 제품·세대: 값을 넣어 활성(N→Y, 추가와 같음).
        s["taxonomy"] = [r for r in s["taxonomy"] if not (r[0] == KEEP and r[1] is not None)]
        s["taxonomy"] += [tax_row("제품·세대", "N3"), tax_row("제품·세대", "N2")]
        write_tax(self.tax_path, s)
        tax, _ = pipeline.load_taxonomy(self.ws)
        p = axisupdate.plan(self.ws, self.con, tax)
        self.assertEqual((p["code"], p["target"], p["removed"]),
                         (axisupdate.PREV_NOT_REVIEWED, ["제품·세대"], [KEEP]))
        code, lines, _ = run_cli("axis-update", "--workspace", self.dir)
        self.assertEqual((code, lines[-1]), (3, "[axis-update] 건너뜀 PREV_NOT_REVIEWED"))
        signal(self.ws, "start", self.run_a)
        self.assertEqual(axisupdate.plan(self.ws, self.con, tax)["code"], axisupdate.REVIEW_IN_PROGRESS)
        self.con.execute("DELETE FROM flagged_chunks WHERE run_id=?", (self.run_a,))
        try:  # 검수할 불량이 0건이면 검수가 끝난 것으로 본다(m5)
            self.assertIsNone(axisupdate.plan(self.ws, self.con, tax)["code"])
        finally:
            self.con.rollback()
        signal(self.ws, "done", self.run_a)
        self._check_lock(tax)
        self._check_push_pending(tax)
        code, lines, _ = run_cli("axis-update", "--workspace", self.dir, "--dry-run")
        self.assertEqual(code, 0)
        dry = json.loads(lines[-1])
        self.assertEqual((dry["code"], dry["prev_run"], dry["target"]), (None, self.run_a, ["제품·세대"]))
        self.assertEqual(store.latest_label_run(self.con), self.run_a)  # dry-run은 실행을 만들지 않는다
        self._check_replan_in_lock()
        self._check_lock_lost()
        crashed = self._crash_once(tax)
        self._check_unfinished_reported(crashed)
        p, run_b, _ = pipeline.run_axis_update(self.ws, transport=MockChatTransport(responder), use_feedback=False)
        self.assertIsNotNone(run_b)
        self.assertEqual(labels(self.con, run_b, "kind='axis' AND key=?", (KEEP,)), [])
        gen = "kind='answer' AND key IN (SELECT qid FROM gen_questions WHERE axis=?)"
        self.assertGreater(len(labels(self.con, self.run_a, gen, (KEEP,))), 0)
        self.assertEqual(labels(self.con, run_b, gen, (KEEP,)), [])  # 활성 Y→N 축의 답도 버린다
        self.assertGreater(dry["dropped_answers"], 0)
        self.assertGreater(len(labels(self.con, run_b, "kind='axis' AND key='제품·세대'")), 0)
        self.assertEqual(review.run_axes(self.con, run_b), {"불량 모드", GONE, "제품·세대"})
        self.assertEqual(p["prev_run"], self.run_a)  # 중단된 실행이 아니라 끝난 기준 실행을 다시 쓴다
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM file_locations WHERE last_seen_run=?",
                                          (crashed,)).fetchone()[0], 0)
        self.assertEqual(store.latest_run(self.con), run_b)

    def _check_lock(self, tax):
        path = self.ws.path("logs", "axis_update.lock.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write('{"run_id": "x", "started_at": "x"}')
        try:
            self.assertEqual(axisupdate.plan(self.ws, self.con, tax)["code"], axisupdate.AXIS_UPDATE_LOCKED)
            code, lines, _ = run_cli("axis-update", "--workspace", self.dir)
            self.assertEqual((code, lines[-1]), (3, "[axis-update] 건너뜀 AXIS_UPDATE_LOCKED"))
            old = os.path.getmtime(path) - axisupdate.LOCK_STALE_SEC - 60
            os.utime(path, (old, old))  # 오래된 잠금은 무시한다
            self.assertIsNone(axisupdate.plan(self.ws, self.con, tax)["code"])
        finally:
            os.remove(path)

    def _check_replan_in_lock(self):
        """잠금을 잡은 사이 기준 실행의 검수가 다시 열리면, 잠금 안에서 다시 계산한 사유로 끝나고 잠금을 푼다."""
        real = axisupdate.acquire_lock
        done = self.ws.path("signals", "review_done_%s.json" % self.run_a)

        def acquire_then_reopen(ws, run_id, con=None):
            ok = real(ws, run_id, con)
            os.rename(done, done + ".bak")
            return ok
        n_runs = self.con.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        try:
            with mock.patch.object(axisupdate, "acquire_lock", acquire_then_reopen):
                p, run_id, _ = pipeline.run_axis_update(self.ws, transport=MockChatTransport(responder),
                                                        use_feedback=False)
        finally:
            os.rename(done + ".bak", done)
        self.assertEqual((p["code"], run_id), (axisupdate.REVIEW_IN_PROGRESS, None))
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM runs").fetchone()[0], n_runs)
        self.assertFalse(os.path.exists(self.ws.path("logs", "axis_update.lock.json")))

    def _check_lock_lost(self):
        """실행 중 잠금을 잃으면 AXIS_UPDATE_LOCK_LOST로 멈추고(종료 코드 3) 실행은 끝나지 않은 채 남는다."""
        with mock.patch.object(axisupdate, "touch_lock", return_value=False):
            code, lines, _ = run_cli("axis-update", "--workspace", self.dir)
        self.assertEqual((code, lines[-1]), (3, "[axis-update] 건너뜀 AXIS_UPDATE_LOCK_LOST"))
        lost = store.latest_label_run(self.con)
        self.assertNotEqual(lost, self.run_a)
        self.assertIsNone(self.con.execute("SELECT finished_at FROM runs WHERE run_id=?", (lost,)).fetchone()[0])
        self.assertFalse(os.path.exists(self.ws.path("logs", "axis_update.lock.json")))

    def _check_unfinished_reported(self, crashed):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(cli._default_run(self.con), self.run_a)
        self.assertEqual(err.getvalue().strip(), "[run] LATEST_UNFINISHED_SKIPPED %s" % crashed)
        script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              ".claude", "skills", "BEOL-labeling", "scripts", "summary.py")
        out = subprocess.run([sys.executable, script, "--workspace", self.dir], capture_output=True, text=True,
                             encoding="utf-8", env=dict(os.environ, PYTHONIOENCODING="utf-8"), check=True).stdout
        obj = json.loads(out)
        self.assertEqual((obj["run_id"], obj["finished"], obj["newer_unfinished"]), (self.run_a, True, crashed))

    def _check_push_pending(self, tax):
        self.ws.config["supabase"].update(SUPABASE)
        try:
            self.assertEqual(axisupdate.plan(self.ws, self.con, tax)["code"], axisupdate.PREV_PUSH_PENDING)
        finally:
            self.ws.config["supabase"].update({"enabled": False, "url": ""})
        self.assertGreater(len(push_all(self.ws, self.con, self.run_a)), 0)
        self.ws.config["supabase"].update(SUPABASE)
        try:
            self.assertEqual(vectorpush.unpushed(self.ws, self.con, self.run_a), 0)
            self.assertIsNone(axisupdate.plan(self.ws, self.con, tax)["code"])
        finally:
            self.ws.config["supabase"].update({"enabled": False, "url": ""})

    def _crash_once(self, tax):
        """부분 분류 중 예외로 멈춘 실행: 잠금이 풀리고, 기본 최신 실행·전역 축 meta는 기준 실행 그대로다(m6)."""
        kinds = store.meta_get(self.con, "axis_kinds")

        def boom(body, hint):
            raise RuntimeError("transport down")
        with self.assertRaises(RuntimeError):
            pipeline.run_axis_update(self.ws, transport=MockChatTransport(boom), use_feedback=False)
        crashed = store.latest_label_run(self.con)
        self.assertNotEqual(crashed, self.run_a)
        self.assertIsNone(self.con.execute("SELECT finished_at FROM runs WHERE run_id=?", (crashed,)).fetchone()[0])
        self.assertFalse(os.path.exists(self.ws.path("logs", "axis_update.lock.json")))
        self.assertEqual(store.latest_run(self.con), self.run_a)
        self.assertEqual(store.latest_label_run(self.con, finished=True), self.run_a)
        self.assertEqual(store.meta_get(self.con, "axis_kinds"), kinds)
        self.assertTrue(taxdiff.needs_rerun(taxdiff.compare_workspace(self.ws, tax)[0]))
        return crashed

    def test_lock_ownership_and_stale(self):
        d, _, ws = make_ws(base_sheets())
        self.addCleanup(shutil.rmtree, d, True)
        path = ws.path("logs", "axis_update.lock.json")
        self.assertTrue(axisupdate.acquire_lock(ws, "r1"))
        self.assertFalse(axisupdate.acquire_lock(ws, "r2"))
        self.assertTrue(axisupdate.locked(ws))
        self.assertFalse(axisupdate.locked(ws, own="r1"))
        axisupdate.release_lock(ws, "r2")  # 남의 잠금은 지우지 않는다
        self.assertTrue(os.path.exists(path))
        self.assertFalse(axisupdate.touch_lock(ws, "r2"))
        old = time.time() - axisupdate.LOCK_STALE_SEC - 60
        os.utime(path, (old, old))
        self.assertTrue(axisupdate.touch_lock(ws, "r1"))  # 진행 중 갱신은 mtime 기준 오래된 잠금이 되지 않게 한다
        self.assertFalse(axisupdate.acquire_lock(ws, "r3"))
        os.utime(path, (old, old))  # 갱신이 멈춘 잠금(중단된 실행)은 새 실행이 넘겨받는다
        self.assertTrue(axisupdate.acquire_lock(ws, "r3"))
        self.assertEqual([f for f in os.listdir(os.path.dirname(path)) if "stale" in f], [])
        axisupdate.release_lock(ws, "r1")
        self.assertTrue(os.path.exists(path))
        axisupdate.release_lock(ws, "r3")
        self.assertFalse(os.path.exists(path))

    def test_lock_owner_run_finished_or_missing(self):
        d, _, ws = make_ws(base_sheets())
        self.addCleanup(shutil.rmtree, d, True)
        con = store.connect(ws.work_db)
        self.addCleanup(con.close)
        con.execute("INSERT INTO runs(run_id, command, finished_at) VALUES('r-done', 'axis-update', 'x')")
        con.execute("INSERT INTO runs(run_id, command) VALUES('r-live', 'axis-update')")
        con.commit()
        path = ws.path("logs", "axis_update.lock.json")
        self.assertTrue(axisupdate.acquire_lock(ws, "r-done"))
        self.assertFalse(axisupdate.locked(ws, con=con))  # 주인 실행이 끝났다
        self.assertTrue(axisupdate.acquire_lock(ws, "r-live", con))  # 끝난 실행의 잠금은 넘겨받는다
        self.assertTrue(axisupdate.locked(ws, con=con))  # 주인 실행이 진행 중이다
        axisupdate.release_lock(ws, "r-live")
        self.assertTrue(axisupdate.acquire_lock(ws, "r-missing"))
        self.assertTrue(axisupdate.locked(ws, con=con))  # runs에 없어도 유예 안에서는 잡힌 잠금이다
        old = time.time() - axisupdate.LOCK_GRACE_SEC - 60
        os.utime(path, (old, old))
        self.assertFalse(axisupdate.locked(ws, con=con))  # 유예가 지난 없는 실행의 잠금은 남은 잠금이다
        self.assertTrue(axisupdate.acquire_lock(ws, "r-new", con))
        axisupdate.release_lock(ws, "r-new")

    def test_release_lock_retries_permission_error(self):
        d, _, ws = make_ws(base_sheets())
        self.addCleanup(shutil.rmtree, d, True)
        self.assertTrue(axisupdate.acquire_lock(ws, "r1"))
        real, calls = os.remove, []

        def flaky(path):
            calls.append(path)
            if len(calls) < 3:
                raise PermissionError(path)
            real(path)
        with mock.patch.object(axisupdate.os, "remove", flaky), mock.patch.object(axisupdate.time, "sleep"):
            axisupdate.release_lock(ws, "r1")
        self.assertEqual(len(calls), 3)
        self.assertFalse(os.path.exists(ws.path("logs", "axis_update.lock.json")))

    def test_stale_revert_keeps_newer_lock(self):
        """옮기는 사이 다른 실행이 새 잠금을 만들었으면, 그 잠금은 두고 옮긴 파일만 정리한다."""
        d, _, ws = make_ws(base_sheets())
        self.addCleanup(shutil.rmtree, d, True)
        path = ws.path("logs", "axis_update.lock.json")
        self.assertTrue(axisupdate.acquire_lock(ws, "r-old"))
        answers = iter([True, False])  # 처음엔 남은 잠금, 옮긴 뒤 다시 보니 갱신된 잠금

        def stale(p, con=None):
            v = next(answers)
            if not v:
                with open(path, "w", encoding="utf-8") as f:  # 그 사이 다른 실행이 새 잠금을 잡았다
                    f.write('{"run_id": "r-other", "started_at": "x"}')
            return v
        with mock.patch.object(axisupdate, "_stale", stale):
            self.assertFalse(axisupdate.acquire_lock(ws, "r-me"))
        self.assertEqual(axisupdate._lock_owner(path), "r-other")
        self.assertEqual([f for f in os.listdir(os.path.dirname(path)) if "stale" in f], [])

    def test_no_previous_run(self):
        d, _, ws = make_ws(base_sheets())
        self.addCleanup(shutil.rmtree, d, True)
        con = store.connect(ws.work_db)
        try:
            tax, _ = pipeline.load_taxonomy(ws)
            self.assertEqual(axisupdate.plan(ws, con, tax)["code"], axisupdate.NO_PREVIOUS_RUN)
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
