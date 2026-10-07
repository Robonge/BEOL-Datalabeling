"""rules-update 회귀: 라벨링 규칙이 바뀐 작업 폴더에서 바뀐 규칙이 닿는 범위만 다시 라벨링한다.

합성 taxonomy(임시 폴더의 taxonomy.json, 저장소 taxonomy.json은 열지 않는다)와 합성 승인 파일(임시 폴더의 rules.json, 실제
labeling_rules.json은 열지 않는다)로 mock 실행 A를 한 번 돌리고 검수 교정·확인을 넣는다. 시나리오마다 이 작업 폴더를
복사해 쓴다. mock transport는 프롬프트에 든 규칙 표지(MARK-…)를 보고 답을 바꾸고, 작업 종류로 LLM 호출 수를 센다.
"""
import contextlib
import io
import json
import os
import shutil
import sqlite3
import tempfile
import unittest

from labelbot import (axisupdate, embed, feedback, finals, pipeline, rulesdiff, rulesupdate, runchain, store,
                      taxdiff, util, vectorpush)
from labelbot.mock import MockChatTransport, MockEmbedTransport
from labelbot.taxonomy import Question
from labelbot.workspace import Workspace
from tests.test_axis_update import SUPABASE, Sink, apply_doc, labels, signal, write_tax
from tests.test_new_axis_flow import run_cli
from tests.test_pipeline import DUMMY_DIR, _bucket, responder
from tests.test_taxonomy import base_sheets, build, tax_row

KEEP, FM, DS = "구조/레이어", "불량 모드", "의사결정 상태"
FAIL = 6  # 다시 라벨할 때만 이 버킷 chunk에 잘못된 JSON을 돌려준다(이어받은 값 유지 확인)
R_AX = {"rule_id": "FR-AX", "kind": "REPLACE", "target": KEEP, "from": "M1", "to": "V1", "text": "구조 규칙"}
R_FM = {"rule_id": "FR-FM", "kind": "REPLACE", "target": FM, "from": "Short", "to": "Reliability", "text": "불량 규칙"}
R_ANS = {"rule_id": "FR-ANS", "kind": "ANSWER", "target": "Q-COM-001", "text": "공통 규칙"}
R_GEN = {"rule_id": "FR-GEN", "kind": "GEN_ANSWER", "target": "%s=Short" % FM, "text": "검증 규칙"}
R_WIDE = {"rule_id": "QR-WIDE", "kind": "MANUAL", "target": "classify", "text": "전체 규칙"}
R_DS = {"rule_id": "FR-DS", "kind": "ADD", "target": DS, "to": "adopted", "text": "결정 규칙"}
V1 = [R_AX, R_FM, R_ANS, R_GEN, R_WIDE]
BASE = {}


def edit(rule, mark):
    return dict(rule, text="%s %s" % (rule["text"], mark))


class Mock:
    """기본 응답은 MockChatTransport. 규칙 표지 MARK-V1이 프롬프트에 있으면 구조/레이어를 V1로, MARK-O가 있으면
    Q-COM-001 답을 O로 바꾼다. fail 버킷 chunk에는 잘못된 JSON을 돌려준다. 작업 종류와 질문 ID를 센다."""

    def __init__(self, fail=FAIL, on_first=None):
        self.tasks, self.qids, self.fail, self.on_first = [], [], fail, on_first

    def __call__(self, body, hint):
        if self.on_first and not self.tasks:
            self.on_first()  # 실행 도중 승인 파일이 바뀐다
        self.tasks.append(hint.get("task"))
        text = json.dumps(body, ensure_ascii=False)
        if self.fail is not None and _bucket(hint.get("text") or "") == self.fail:
            return "{not json"
        if hint.get("task") == "classify":
            obj = MockChatTransport._classify(hint)
            if "MARK-V1" in text and KEEP in obj["axes"]:
                obj["axes"][KEEP] = {"values": ["V1"], "evidence": "", "confidence": 0.9}
            return json.dumps(obj, ensure_ascii=False)
        if hint.get("task") == "label":
            self.qids.append(tuple(hint["qids"]))
            obj = MockChatTransport._label(hint)
            if "MARK-O" in text and "Q-COM-001" in obj["answers"]:
                line = next(ln for ln in hint["text"].splitlines() if ln.strip())
                obj["answers"]["Q-COM-001"] = {"answer": "O", "quote": line, "confidence": 0.9}
            return json.dumps(obj, ensure_ascii=False)
        return MockChatTransport().send(body, hint)


def relabel_failures(con, run_b):
    """rules-update에서 다시 라벨하다 실패한 호출 기록 [(chunk, 사유)] (stage='relabel')."""
    return [tuple(r) for r in con.execute("SELECT target_id, reason_code FROM failures WHERE run_id=? AND stage=?",
                                          (run_b, rulesupdate.RELABEL_STAGE))]


def write_rules(ws, rules, examples=()):
    with open(ws.config["feedback"]["rules_path"], "w", encoding="utf-8") as f:
        json.dump({"rules": list(rules), "examples": list(examples)}, f, ensure_ascii=False)


def _config(d):
    return {"taxonomy_path": os.path.join(d, "taxonomy.json"), "input_root": DUMMY_DIR,
            "llm": {"transport": "mock", "model": "mock", "max_retries": 1},
            "embedding": {"transport": "mock"}, "supabase": {"enabled": False},
            "feedback": {"rules_path": os.path.join(d, "rules.json"), "examples_root": os.path.join(d, "root")}}


def clone():
    """기준 작업 폴더(실행 A·검수 반영 끝)를 복사한다. 설정의 경로는 복사본을 가리키게 다시 쓴다."""
    d = tempfile.mkdtemp(prefix="labelbot_ws_")
    shutil.copytree(BASE["dir"], d, dirs_exist_ok=True)
    with open(os.path.join(d, "pipeline.json"), "w", encoding="utf-8") as f:
        json.dump(_config(d), f)
    return d, Workspace(d)


def setUpModule():
    d = tempfile.mkdtemp(prefix="labelbot_ws_")
    with open(os.path.join(d, "taxonomy.json"), "wb") as f:
        f.write(build(base_sheets()))
    with open(os.path.join(d, "pipeline.json"), "w", encoding="utf-8") as f:
        json.dump(_config(d), f)
    ws = Workspace(d)
    write_rules(ws, V1)
    run_a, _ = pipeline.run_all(ws, DUMMY_DIR, transport=MockChatTransport(responder))
    con = store.connect(ws.work_db)
    try:
        tax, _ = pipeline.load_taxonomy(ws)
        has = "EXISTS(SELECT 1 FROM labels l WHERE l.run_id=f.run_id AND l.chunk_id=f.chunk_id AND l.key=?)"

        def pick(sql, args):
            return next(r[0] for r in con.execute(sql, args) if _bucket(r[1]) != FAIL)
        c_fix = pick("SELECT f.chunk_id, c.text FROM flagged_chunks f JOIN chunks c ON c.chunk_id=f.chunk_id"
                     " WHERE run_id=? AND %s AND %s ORDER BY f.chunk_id" % (has, has), (run_a, "Q-COM-001", KEEP))
        c_ok = pick("SELECT f.chunk_id, c.text FROM flagged_chunks f JOIN chunks c ON c.chunk_id=f.chunk_id"
                    " WHERE run_id=? AND %s AND %s AND f.chunk_id<>? ORDER BY f.chunk_id" % (has, has),
                    (run_a, "Q-COM-001", KEEP, c_fix))
        corr = [{"chunk_id": c_fix, "target": "axis", "key": KEEP, "value": ["M1"]},
                {"chunk_id": c_fix, "target": "axis", "key": FM, "value": ["Reliability"]},
                {"chunk_id": c_fix, "target": "answer", "key": "Q-COM-001", "value": "X"}]
        res = apply_doc(ws, con, tax, {"kind": "review", "run_id": run_a, "synonyms": [], "corrections": corr,
                                       "chunk_status": [{"chunk_id": c_ok, "status": "confirmed"}]}, "review_a.json")
        assert [r[1] for r in res] == ["OK"], res
    finally:
        con.close()
    signal(ws, "done", run_a)
    BASE.update(dir=d, run_a=run_a, c_fix=c_fix, c_ok=c_ok)


def tearDownModule():
    shutil.rmtree(BASE["dir"], ignore_errors=True)


class _Case(unittest.TestCase):
    @classmethod
    def open_clone(cls):
        cls.dir, cls.ws = clone()
        cls.con = store.connect(cls.ws.work_db)
        cls.tax, _ = pipeline.load_taxonomy(cls.ws)
        cls.run_a, cls.c_fix, cls.c_ok = BASE["run_a"], BASE["c_fix"], BASE["c_ok"]

    @classmethod
    def tearDownClass(cls):
        cls.con.close()
        shutil.rmtree(cls.dir, ignore_errors=True)


class RulesUpdateTest(_Case):
    """축 규칙(FR-AX)·답 규칙(FR-ANS)·축 없는 규칙(QR-WIDE)을 고친 뒤 rules-update 실행 B."""

    @classmethod
    def setUpClass(cls):
        cls.open_clone()
        v2 = [edit(R_AX, "MARK-V1"), R_FM, edit(R_ANS, "MARK-O"), R_GEN, edit(R_WIDE, "새")]
        write_rules(cls.ws, v2)
        cls.mock = Mock(on_first=lambda: write_rules(cls.ws, v2 + [R_DS]))  # 실행 도중 FR-DS가 더해진다(M2)
        cls.plan, cls.run_b, cls.ctx = pipeline.run_rules_update(cls.ws, transport=MockChatTransport(cls.mock))
        cls.mid = rulesdiff.compare(cls.ws, cls.con, cls.tax)
        write_rules(cls.ws, v2)
        cls.info = rulesupdate.run_info(cls.con, cls.run_b)
        cls.final_a = finals.final_labels(cls.con, cls.run_a)
        cls.final_b = finals.final_labels(cls.con, cls.run_b)
        cls.stale = {(c["chunk_id"], c["key"]) for c in rulesupdate.changes(cls.con, cls.run_b) if c["stale"]}

    # AC1 규칙 기록
    def test_rules_applied_recorded(self):
        a = store.meta_json(self.con, "rules_applied:" + self.run_a)
        self.assertEqual(sorted(a["classify"]), [KEEP, FM])
        self.assertEqual(sorted(a["label"]), ["Q-COM-001", "%s=Short" % FM])
        self.assertEqual(list(a["stage_wide"]), ["QR-WIDE"])
        self.assertEqual(set(a["classify"][KEEP]["FR-AX"]), {"h", "kind", "target", "stage"})
        b = store.meta_json(self.con, "rules_applied:" + self.run_b)
        cur = rulesdiff.current(self.ws, self.tax)
        self.assertEqual((b["classify"], b["label"]), (cur["classify"], cur["label"]))
        self.assertEqual(b["stage_wide"], a["stage_wide"])  # 축 없는 규칙은 적용하지 않았으므로 부모 것을 잇는다
        self.assertNotIn("구조 규칙", json.dumps(b, ensure_ascii=False))  # 규칙 문장은 남기지 않는다

    def test_plan_and_meta(self):
        p = self.plan
        self.assertEqual((p["code"], p["prev_run"], p["edited"]), (None, self.run_a, ["FR-ANS", "FR-AX", "QR-WIDE"]))
        self.assertEqual(p["stage_wide"], ["QR-WIDE"])
        info = self.info
        self.assertEqual((info["parent"], info["target"], info["removed"]), (self.run_a, [], []))
        self.assertEqual(info["stage_wide"], 1)
        rules = {r["rule_id"]: r for r in info["rules"]}
        self.assertEqual((rules["FR-AX"]["axes"], rules["FR-ANS"]["keys"]), ([KEEP], ["Q-COM-001"]))
        self.assertGreater(rules["FR-AX"]["changed"], 0)
        self.assertGreater(rules["FR-ANS"]["changed"], 0)
        self.assertEqual(rules["QR-WIDE"]["relabeled"], 0)
        self.assertEqual(info["relabeled"], sum(r["relabeled"] for r in info["rules"]))
        self.assertEqual(axisupdate.run_info(self.con, self.run_b), None)  # axis-update 화면·검수는 이 실행을 보지 않는다
        r = self.con.execute("SELECT command, finished_at FROM runs WHERE run_id=?", (self.run_b,)).fetchone()
        self.assertEqual(r[0], "rules-update")
        self.assertIsNotNone(r[1])
        ch = rulesupdate.changes(self.con, self.run_b)
        self.assertTrue(ch)
        self.assertEqual(set(ch[0]), {"chunk_id", "kind", "key", "before", "after", "stale"})

    # AC4 축 규칙 범위: 그 축만 다시 분류, 나머지 행은 기준 실행과 같다
    def test_axis_scope_only(self):
        keep = "kind IN ('chunk_type','extract') OR (kind='axis' AND key<>?)"
        self.assertEqual(labels(self.con, self.run_b, keep, (KEEP,)), labels(self.con, self.run_a, keep, (KEEP,)))
        ans = "kind='answer' AND key<>'Q-COM-001'"
        self.assertEqual(labels(self.con, self.run_b, ans),
                         [r for r in labels(self.con, self.run_a, ans) if (r[0], r[2]) not in self.stale])
        changed = self.con.execute("SELECT COUNT(*) FROM labels WHERE run_id=? AND kind='axis' AND key=? AND value=?",
                                   (self.run_b, KEEP, '["V1"]')).fetchone()[0]
        self.assertGreater(changed, 0)

    def test_partial_prompt_and_calls(self):
        self.assertEqual(set(self.mock.tasks), {"classify", "label"})
        self.assertEqual(set(self.mock.qids), {("Q-COM-001",)})  # 3차는 대상 질문만 묻는다
        n_cls, n_lab = len(self.plan["axis_targets"]), len(self.plan["answer_targets"])
        failed = relabel_failures(self.con, self.run_b)
        self.assertTrue(failed)
        self.assertEqual({r for _, r in failed}, {rulesupdate.RELABEL_FAILED})
        # 대상 chunk당 1회, 형식 실패(호출 하나에 실패 기록 하나)는 재시도 1회 더
        self.assertEqual(self.ctx.chat.calls + self.ctx.chat.cache_hits, n_cls + n_lab + len(failed))

    # AC5 답 규칙 범위
    def test_answer_scope(self):
        rows = {r[0]: r[3] for r in labels(self.con, self.run_b, "kind='answer' AND key='Q-COM-001'")}
        targets = {c for c, qs in self.plan["answer_targets"].items() if "Q-COM-001" in qs}
        self.assertTrue(targets)
        ok = [c for c in targets if _bucket(self.con.execute("SELECT text FROM chunks WHERE chunk_id=?",
                                                             (c,)).fetchone()[0]) != FAIL]
        self.assertTrue(ok and all(rows[c] == "O" for c in ok))

    # AC6 사람 값 보호
    def test_human_values_protected(self):
        d = self.final_b[self.c_fix]
        self.assertEqual((d["axes"][KEEP]["values"], d["axes"][KEEP]["review"]), (["M1"], finals.CORRECTED))
        self.assertEqual((d["answers"]["Q-COM-001"]["answer"], d["answers"]["Q-COM-001"]["review"]),
                         ("X", finals.CORRECTED))
        a, b = self.final_a[self.c_ok], self.final_b[self.c_ok]
        self.assertEqual(finals.label_hash(a), finals.label_hash(b))
        self.assertTrue(all(x["review"] == finals.CONFIRMED for x in list(b["axes"].values()) + list(b["answers"].values())))
        self.assertNotIn(self.c_ok, self.plan["axis_targets"])
        self.assertNotIn(self.c_ok, self.plan["answer_targets"])
        self.assertNotIn(KEEP, self.plan["axis_targets"].get(self.c_fix, []))
        self.assertGreater(self.plan["skipped_human"], 0)
        self.assertGreater(self.plan["skipped_confirmed"], 0)

    # AC16 덮어쓰기: 실패하면 이어받은 값, 중복 행 없음, extract 다시 넣지 않음
    def test_failure_keeps_inherited_no_duplicates(self):
        # 답 대상이 아닌 축 대상 chunk의 relabel 실패는 1차 분류 실패다
        fail = sorted({c for c, _ in relabel_failures(self.con, self.run_b)} - set(self.plan["answer_targets"]))
        self.assertTrue(fail)
        self.assertLessEqual(set(fail), set(self.plan["axis_targets"]))
        # 다시 라벨한 chunk의 이어받은 분류 실패 기록은 지우고, 이번 실패는 분류 실패로 세지 않는다(m8)
        cls_failed = {r[0] for r in self.con.execute(
            "SELECT target_id FROM failures WHERE run_id=? AND stage='classify'", (self.run_b,))}
        self.assertFalse(cls_failed & set(self.plan["axis_targets"]))
        q = "kind='axis' AND key=? AND chunk_id IN (%s)" % ",".join("?" * len(fail))
        self.assertEqual(labels(self.con, self.run_b, q, [KEEP] + fail), labels(self.con, self.run_a, q, [KEEP] + fail))
        dup = self.con.execute("SELECT COUNT(*) FROM (SELECT 1 FROM labels WHERE run_id=? AND kind IN"
                               " ('chunk_type','axis','answer') GROUP BY chunk_id, kind, key HAVING COUNT(*) > 1)",
                               (self.run_b,)).fetchone()[0]
        self.assertEqual(dup, 0)
        n = "SELECT COUNT(*) FROM labels WHERE run_id=? AND kind='extract'"
        self.assertEqual(self.con.execute(n, (self.run_b,)).fetchone()[0], self.con.execute(n, (self.run_a,)).fetchone()[0])

    # AC9 무검수 반영
    def test_no_flags(self):
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM flagged_chunks WHERE run_id=?",
                                          (self.run_b,)).fetchone()[0], 0)

    # AC10 변경 비율 상한
    def test_ratio_blocks_push_force_sends(self):
        self.assertTrue(self.info["blocked"])
        self.assertGreater(self.info["change_ratio"], 0.3)
        embed.embed(self.ws, self.con, self.run_b, transport=MockEmbedTransport())
        self.ws.config["supabase"].update(SUPABASE)
        try:
            sink = Sink()
            self.assertEqual(vectorpush.push(self.ws, self.con, self.run_b, sink=sink)["reason"],
                             rulesupdate.RULES_CHANGE_RATIO_HIGH)
            self.assertEqual(sink.rows, [])
            self.assertEqual(runchain.push_pending(self.ws, self.con, self.run_b), runchain.PREV_PUSH_PENDING)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                vectorpush.push(self.ws, self.con, self.run_b, sink=sink, force=True)
            self.assertGreater(len(sink.rows), 0)
            self.assertIn("[push-vectors] FORCED RULES_CHANGE_RATIO_HIGH ratio=%.2f limit=0.30" % self.info["change_ratio"],
                          out.getvalue())
            self.assertTrue(rulesupdate.run_info(self.con, self.run_b)["forced_at"])
        finally:
            self.ws.config["supabase"].update({"enabled": False, "url": ""})
        cfg_path = os.path.join(self.dir, "pipeline.json")
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
        cfg["supabase"] = dict(SUPABASE)
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        try:
            code, lines, _ = run_cli("push-vectors", "--workspace", self.dir)
        finally:
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(_config(self.dir), f)
        self.assertEqual(code, 3)
        self.assertEqual(lines[-1], "[push-vectors] 차단 RULES_CHANGE_RATIO_HIGH ratio=%.2f limit=0.30"
                         % self.info["change_ratio"])

    # M2 rules_applied는 plan(잠금 안) 때의 승인 파일: 실행 도중 더해진 규칙은 다음 diff에 나온다
    def test_rule_added_mid_run_shows_next(self):
        self.assertEqual((self.mid["code"], self.mid["added"], self.mid["scope"]["classify"]["axes"]),
                         (None, ["FR-DS"], [DS]))
        self.assertNotIn(DS, store.meta_json(self.con, "rules_applied:" + self.run_b)["classify"])

    # AC11 해소·taxonomy-diff 그대로, AC7 축 없는 규칙만 남음
    def test_rules_diff_resolved_and_stage_wide_left(self):
        code, lines, _ = run_cli("rules-diff", "--workspace", self.dir)
        self.assertEqual(code, 0)
        d = json.loads(lines[0])
        self.assertEqual((d["code"], d["run_id"], d["edited"]), (rulesdiff.STAGE_WIDE_ONLY, self.run_b, ["QR-WIDE"]))
        self.assertEqual(d["scope"]["classify"]["axes"], [])
        self.assertNotIn("규칙", lines[0].replace("rules", ""))  # 규칙 문장(…규칙)은 내지 않는다
        code, lines, _ = run_cli("rules-update", "--workspace", self.dir)
        self.assertEqual((code, lines[-1]), (3, "[rules-update] 건너뜀 STAGE_WIDE_ONLY"))
        code, lines, _ = run_cli("taxonomy-diff", "--workspace", self.dir)
        d = json.loads(lines[0])
        self.assertEqual((d["run_id"], d["added"], d["removed"], d["changed"]), (self.run_b, [], [], []))
        self.assertEqual(store.meta_get(self.con, "axes_signature:" + self.run_b),
                         store.meta_get(self.con, "axes_signature:" + self.run_a))

    # AC12 최신 실행
    def test_latest_run(self):
        self.assertIn("rules-update", store.LABEL_COMMANDS)
        self.assertEqual(store.latest_label_run(self.con), self.run_b)
        self.assertEqual(store.latest_run(self.con), self.run_b)

    # 멱등
    def test_start_is_idempotent(self):
        c = rulesupdate.start(self.ws, self.con, self.plan, self.tax)
        try:
            copied = labels(self.con, c)
            self.assertEqual(copied, labels(self.con, self.run_a))
            self.assertEqual(rulesupdate.start(self.ws, self.con, self.plan, self.tax, run_id=c), c)
            self.assertEqual(labels(self.con, c), copied)
            self.assertGreater(self.con.execute("SELECT COUNT(*) FROM file_locations WHERE last_seen_run=?",
                                                (c,)).fetchone()[0], 0)
        finally:
            self.con.execute("UPDATE file_locations SET last_seen_run=? WHERE last_seen_run=?", (self.run_b, c))
            for table in ("labels", "failures", "runs"):
                self.con.execute("DELETE FROM %s WHERE run_id=?" % table, (c,))
            self.con.execute("DELETE FROM meta WHERE key LIKE ?", ("%:" + c,))
            self.con.commit()


class RulesDiffTest(_Case):
    """실행을 만들지 않는 검사: 변경 종류·범위, 기준 복원, 멈춤 사유."""

    @classmethod
    def setUpClass(cls):
        cls.open_clone()

    def tearDown(self):
        write_rules(self.ws, V1)

    def compare(self):
        return rulesdiff.compare(self.ws, self.con, self.tax)

    # AC2
    def test_change_kinds_and_scope(self):
        self.assertEqual(self.compare()["code"], rulesdiff.NO_RULE_CHANGE)
        code, lines, _ = run_cli("rules-diff", "--workspace", self.dir)
        self.assertEqual((code, json.loads(lines[0])["code"]), (3, rulesdiff.NO_RULE_CHANGE))  # 변경 없음은 3
        code, lines, _ = run_cli("rules-update", "--workspace", self.dir, "--dry-run")
        self.assertEqual((code, json.loads(lines[-1])["code"]), (3, rulesdiff.NO_RULE_CHANGE))
        new = {"rule_id": "FR-NEW", "kind": "ADD", "target": DS, "to": "adopted", "text": "새 규칙"}
        write_rules(self.ws, [R_AX, dict(R_FM, enabled=False), edit(R_ANS, "고침"), R_WIDE, new])
        res = self.compare()
        self.assertEqual((res["code"], res["baseline"]), (None, "rules_applied"))
        self.assertEqual((res["added"], res["edited"], res["disabled"], res["removed"]),
                         (["FR-NEW"], ["FR-ANS"], ["FR-FM"], ["FR-GEN"]))
        sc = res["scope"]
        self.assertEqual(sc["classify"]["axes"], [FM, DS])
        self.assertEqual((sc["label"]["qids"], sc["label"]["gen_targets"]), (["Q-COM-001"], [[FM, "Short"]]))
        self.assertEqual(sc["stage_wide"], [])
        code, lines, _ = run_cli("rules-diff", "--workspace", self.dir)
        self.assertEqual(code, 0)
        self.assertNotIn("text", json.loads(lines[0]))
        self.assertNotIn("새 규칙", lines[0] + lines[1])
        self.assertTrue(lines[1].startswith("[rules] 기준 run_id=%s" % self.run_a))

    # 대상이 모두 없으면(답한 chunk 없음) 실행을 만들지 않는다
    def test_no_relabel_target(self):
        write_rules(self.ws, [R_AX, R_FM, R_ANS, R_GEN, R_WIDE,
                              {"rule_id": "FR-Q", "kind": "ANSWER", "target": "Q-FM-001", "text": "단락 규칙"}])
        self.con.execute("DELETE FROM labels WHERE run_id=? AND key='Q-FM-001'", (self.run_a,))
        try:
            p = rulesupdate.plan(self.ws, self.con, self.tax)
            self.assertEqual((p["code"], p["added"], p["chunks"]), (rulesupdate.NO_RELABEL_TARGET, ["FR-Q"], 0))
        finally:
            self.con.rollback()

    # 보안: rule_id는 영문·숫자·_-만, 40자 이하. scope는 지금 taxonomy에 있는 축·질문만
    def test_rule_id_and_scope_filtered(self):
        base = {"kind": "MANUAL", "target": KEEP, "text": "x"}
        self.assertFalse(feedback._valid_rule(dict(base, rule_id="../x")))
        self.assertFalse(feedback._valid_rule(dict(base, rule_id="A" * 41)))
        self.assertTrue(feedback._valid_rule(dict(base, rule_id="QR-a_1")))
        write_rules(self.ws, V1 + [{"rule_id": "FR-Z", "kind": "ANSWER", "target": "Q-NONE-999", "text": "z"},
                                   {"rule_id": "QR-Z", "kind": "MANUAL", "stage": "label", "target": "%s=없는값" % FM,
                                    "text": "z"}])
        res = self.compare()
        self.assertEqual((res["added"], res["code"]), (["FR-Z", "QR-Z"], rulesdiff.NO_RULE_CHANGE))
        self.assertEqual(rulesdiff.label_keys(res["scope"]), [])

    # AC15 기각된 규칙은 이전 기록의 대상으로 범위를 낸다
    def test_removed_rule_scope(self):
        write_rules(self.ws, [R_FM, R_ANS, R_GEN, R_WIDE])
        res = self.compare()
        self.assertEqual((res["removed"], res["scope"]["classify"]["axes"]), (["FR-AX"], [KEEP]))

    # AC7 축 없는 규칙만
    def test_stage_wide_only(self):
        write_rules(self.ws, [R_AX, R_FM, R_ANS, R_GEN, edit(R_WIDE, "고침")])
        self.assertEqual(self.compare()["code"], rulesdiff.STAGE_WIDE_ONLY)
        n = self.con.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        code, lines, _ = run_cli("rules-update", "--workspace", self.dir)
        self.assertEqual((code, lines[-1]), (3, "[rules-update] 건너뜀 STAGE_WIDE_ONLY"))
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM runs").fetchone()[0], n)

    # AC3 옛 실행 기준 복원: rules_history 문서, 지금 파일, 실패
    def test_baseline_reconstruction(self):
        key = "rules_applied:" + self.run_a
        saved = store.meta_get(self.con, key)
        hist = rulesdiff.history_path(self.ws)
        self.con.execute("DELETE FROM meta WHERE key=?", (key,))
        self.con.commit()
        try:
            res = self.compare()  # 같은 문서로 기준과 지금 기록을 만들면 차이가 없다
            self.assertEqual((res["code"], res["baseline"], res["prev"]), (rulesdiff.NO_RULE_CHANGE, "current", res["cur"]))
            write_rules(self.ws, [edit(R_AX, "고침"), R_FM, R_ANS, R_GEN, R_WIDE])
            self.assertEqual(self.compare()["code"], rulesdiff.RULES_BASELINE_UNKNOWN)
            os.makedirs(os.path.dirname(hist), exist_ok=True)
            with open(hist, "w", encoding="utf-8") as f:
                f.write(json.dumps({"at": "x", "doc": {"rules": [R_AX], "examples": []}}, ensure_ascii=False) + "\n")
                f.write(json.dumps({"at": "y", "doc": {"rules": V1, "examples": []}}, ensure_ascii=False) + "\n")
            res = self.compare()
            self.assertEqual((res["code"], res["baseline"], res["edited"]), (None, "rules_history", ["FR-AX"]))
            self.assertEqual(res["prev"], json.loads(saved))
            code, lines, _ = run_cli("rules-update", "--workspace", self.dir, "--dry-run")
            dry = json.loads(lines[-1])
            self.assertEqual((code, dry["code"], dry["baseline"], dry["edited"]), (0, None, "rules_history", ["FR-AX"]))
            self.assertEqual(store.latest_label_run(self.con), self.run_a)  # dry-run은 실행을 만들지 않는다
        finally:
            store.meta_set(self.con, key, saved)
            self.con.commit()
            if os.path.exists(hist):
                os.remove(hist)

    def test_digest_of_matches_run(self):
        digest = json.loads(self.con.execute("SELECT sheet_hashes FROM runs WHERE run_id=?",
                                             (self.run_a,)).fetchone()[0])["labeling_rules"]
        self.assertEqual(feedback.digest_of(self.ws, feedback.load_rules(self.ws), self.tax), digest)
        write_rules(self.ws, [])
        self.assertIsNone(feedback.digest_of(self.ws, feedback.load_rules(self.ws), self.tax))

    # 멈춤 사유: PREV_NOT_REVIEWED, AXIS_UPDATE_LOCKED(axis-update와 같은 잠금), AXIS_CHANGE_PENDING, NO_RULE_CHANGE
    def test_gates(self):
        write_rules(self.ws, [edit(R_AX, "고침"), R_FM, R_ANS, R_GEN, R_WIDE])
        self.assertIsNone(rulesupdate.plan(self.ws, self.con, self.tax)["code"])
        done = self.ws.path("signals", "review_done_%s.json" % self.run_a)
        os.rename(done, done + ".bak")
        self.con.execute("DELETE FROM corrections WHERE review_run_id=?", (self.run_a,))
        try:
            self.assertEqual(rulesupdate.plan(self.ws, self.con, self.tax)["code"], runchain.PREV_NOT_REVIEWED)
        finally:
            self.con.rollback()
            os.rename(done + ".bak", done)
        self.assertTrue(axisupdate.acquire_lock(self.ws, "r-other"))
        try:
            self.assertEqual(rulesupdate.plan(self.ws, self.con, self.tax)["code"], axisupdate.AXIS_UPDATE_LOCKED)
            code, lines, _ = run_cli("rules-update", "--workspace", self.dir)
            self.assertEqual((code, lines[-1]), (3, "[rules-update] 건너뜀 AXIS_UPDATE_LOCKED"))
        finally:
            axisupdate.release_lock(self.ws, "r-other")
        s = base_sheets()
        s["taxonomy"].append(tax_row(KEEP, "V2"))
        write_tax(self.ws.taxonomy_path, s)
        try:
            tax, _ = pipeline.load_taxonomy(self.ws)
            self.assertEqual(rulesupdate.plan(self.ws, self.con, tax)["code"], rulesupdate.AXIS_CHANGE_PENDING)
            # 꺼진 축(사용 여부 N)의 값만 바뀌면 axis-update 대상이 없으므로 막지 않는다(B2)
            s = base_sheets()
            s["taxonomy"] = [tax_row(r[0], None, None, "Y", "N", "N", "분류", "정의", use="N")
                             if r[0] == "제품·세대" and r[1] is None else r for r in s["taxonomy"]]
            s["taxonomy"].append(tax_row("제품·세대", "N3"))
            write_tax(self.ws.taxonomy_path, s)
            tax, _ = pipeline.load_taxonomy(self.ws)
            self.assertTrue(taxdiff.needs_rerun(taxdiff.compare_workspace(self.ws, tax)[0]))
            self.assertIsNone(rulesupdate.plan(self.ws, self.con, tax)["code"])
        finally:
            write_tax(self.ws.taxonomy_path, base_sheets())
        write_rules(self.ws, V1)
        self.assertEqual(rulesupdate.plan(self.ws, self.con, self.tax)["code"], rulesdiff.NO_RULE_CHANGE)

    # 3차 MANUAL 규칙의 stage·대상(질문 ID, 축=값). stage 없는 옛 규칙은 그대로
    def test_manual_label_stage_targets(self):
        rules = [{"rule_id": "QR-Q", "kind": "MANUAL", "stage": "label", "target": "Q-FM-001", "text": "a"},
                 {"rule_id": "QR-P", "kind": "MANUAL", "stage": "label", "target": "%s=Short" % FM, "text": "b"},
                 {"rule_id": "QR-OLD", "kind": "MANUAL", "target": "label", "text": "c"},
                 {"rule_id": "QR-C", "kind": "MANUAL", "stage": "classify", "target": KEEP, "text": "d"}]
        write_rules(self.ws, rules)
        fb = feedback.load(self.ws, self.tax, None)
        self.assertEqual([r["rule_id"] for r in fb.classify_rules], ["QR-C"])
        com = [Question("Q-COM-001", "t", "공통", 1, None)]
        fm = com + [Question("Q-FM-001", "t", (FM, "Short"), 2, None)]
        self.assertEqual(fb.rules_text("label", com), "- [QR-OLD] c")
        self.assertEqual(fb.rules_text("label", fm), "- [QR-OLD] c\n- [QR-P] b\n- [QR-Q] a")
        rec = fb.applied_rules()
        self.assertEqual((sorted(rec["label"]), list(rec["classify"]), list(rec["stage_wide"])),
                         (["Q-FM-001", "%s=Short" % FM], [KEEP], ["QR-OLD"]))
        write_rules(self.ws, V1 + rules)
        res = rulesdiff.compare(self.ws, self.con, self.tax)
        sc = res["scope"]
        self.assertEqual(res["added"], ["QR-C", "QR-OLD", "QR-P", "QR-Q"])
        self.assertEqual((sc["classify"]["axes"], sc["label"]["qids"], sc["label"]["pairs"], sc["label"]["gen_targets"]),
                         ([KEEP], ["Q-FM-001"], [[FM, "Short"]], []))
        self.assertEqual(sc["stage_wide"], ["QR-OLD"])


class ChainTest(_Case):
    """axis-update → rules-update → axis-update에서 조상이 버린 교정(D5)이 되살아나지 않고 확인(D6)이 유지된다."""

    @classmethod
    def setUpClass(cls):
        cls.open_clone()

    def _axis_update(self, sheets):
        write_tax(self.ws.taxonomy_path, sheets)
        tax, _ = pipeline.load_taxonomy(self.ws)
        p, run_id, _ = pipeline.run_axis_update(self.ws, transport=MockChatTransport(Mock(fail=None)))
        self.assertIsNotNone(run_id, p["code"])
        signal(self.ws, "done", run_id)  # 검수할 불량은 그대로 두고 끝낸 것으로 본다
        return run_id, p, tax

    def _rules_update(self, rules):
        write_rules(self.ws, rules)
        p, run_id, _ = pipeline.run_rules_update(self.ws, transport=MockChatTransport(Mock(fail=None)))
        self.assertIsNotNone(run_id, p["code"])
        return run_id

    def _check(self, run_id):
        """c_fix의 불량 모드 교정은 버려졌고(D5), 구조/레이어 교정은 남고, c_ok의 확인이 이어진다(D6)."""
        chain = runchain.chain(self.con, run_id)
        self.assertEqual(axisupdate.chain(self.con, run_id), chain)  # domain_engrbot 어댑터가 쓰는 이름
        self.assertEqual(chain[-1]["parent"], self.run_a)
        d = finals.final_labels(self.con, run_id, [self.c_fix, self.c_ok])
        fix, ok = d[self.c_fix], d[self.c_ok]
        self.assertNotEqual(fix["axes"][FM]["review"], finals.CORRECTED)
        self.assertEqual((fix["axes"][KEEP]["values"], fix["axes"][KEEP]["review"]), (["M1"], finals.CORRECTED))
        self.assertEqual(ok["axes"][KEEP]["review"], finals.CONFIRMED)
        corr = finals.corrections(self.con, {self.c_fix}, run_id)[self.c_fix]
        self.assertNotIn(("axis", FM), corr)
        self.assertIn(("axis", KEEP), corr)

    def test_chain_both_orders(self):
        no_em = base_sheets()
        no_em["taxonomy"] = [r for r in no_em["taxonomy"] if not (r[0] == FM and r[1] == "EM")]
        # 순서 1: axis-update(불량 모드 값 삭제) → rules-update → axis-update(값 추가만).
        # b는 A 뒤에 비대상 축(의사결정 상태) 규칙 FR-DS가 더해진 승인 파일로 돈다.
        write_rules(self.ws, V1 + [R_DS])
        b, pb, tax_b = self._axis_update(no_em)
        # axis-update 기준의 digest 복원(대상 축만): rules_applied를 지워도 같은 기록이 나온다
        sh = json.loads(self.con.execute("SELECT sheet_hashes FROM runs WHERE run_id=?", (b,)).fetchone()[0])
        self.assertEqual(feedback.digest_of(self.ws, feedback.load_rules(self.ws), tax_b, only_axes=set(pb["target"])),
                         sh["labeling_rules"])
        saved = store.meta_get(self.con, "rules_applied:" + b)
        kept = rulesdiff.compare(self.ws, self.con, tax_b, b)
        self.con.execute("DELETE FROM meta WHERE key=?", ("rules_applied:" + b,))
        try:
            got = rulesdiff.baseline(self.ws, self.con, b, tax_b)
            self.assertEqual((got["code"], got["record"], got["source"]),
                             (None, json.loads(saved), "current+rules_applied"))
            # 기준(대상 축은 b, 나머지는 A)과 지금 기록의 차이는 b가 적용하지 않은 비대상 축 규칙뿐이다
            res = rulesdiff.compare(self.ws, self.con, tax_b, b)
            self.assertEqual((res["added"], res["edited"], res["removed"], res["scope"]["classify"]["axes"]),
                             (["FR-DS"], [], [], [DS]))
            self.assertEqual(rulesdiff.public(res), dict(rulesdiff.public(kept), baseline=res["baseline"]))
            write_rules(self.ws, V1)  # 대상 축(불량 모드) 밖의 규칙만 빼면 A·b 기준과 같아진다
            self.assertEqual(rulesdiff.compare(self.ws, self.con, tax_b, b)["code"], rulesdiff.NO_RULE_CHANGE)
        finally:
            write_rules(self.ws, V1 + [R_DS])
            store.meta_set(self.con, "rules_applied:" + b, saved)
            self.con.commit()
        c = self._rules_update([R_AX, R_FM, edit(R_ANS, "MARK-O"), R_GEN, R_WIDE, R_DS])
        self._check(c)
        more = no_em["taxonomy"] + [tax_row(DS, "rejected")]  # 값 추가만: 교정을 버리지 않는다
        d, pd, _ = self._axis_update(dict(no_em, taxonomy=more))
        self.assertEqual((pd["prev_run"], pd["target"], pd["values_added_only"]), (c, [DS], [DS]))
        self._check(d)
        self.assertEqual([i["run_id"] for i in runchain.chain(self.con, d)], [d, c, b])
        # 순서 2(역순): rules-update → axis-update(값 추가만) → rules-update
        e = self._rules_update([R_AX, R_FM, edit(R_ANS, "MARK-O 둘"), R_GEN, R_WIDE, R_DS])
        self._check(e)
        f, pf, _ = self._axis_update(dict(no_em, taxonomy=more + [tax_row(DS, "pending")]))
        self.assertEqual((pf["prev_run"], pf["target"]), (e, [DS]))
        g = self._rules_update([R_AX, R_FM, edit(R_ANS, "MARK-O 셋"), R_GEN, R_WIDE, R_DS])
        self._check(g)
        self.assertEqual([i["command"] for i in runchain.chain(self.con, g)],
                         ["rules-update", "axis-update", "rules-update", "axis-update", "rules-update", "axis-update"])
        out = sqlite3.connect(self.ws.path("out", "labeling.sqlite"))
        try:
            self.assertEqual(out.execute("SELECT value FROM meta WHERE key='run_id'").fetchone()[0], g)
        finally:
            out.close()


class AxisRemovedTest(_Case):
    """FR 규칙이 걸린 축을 끄고(값 모두 삭제) axis-update를 돌리면 rules-diff는 NO_RULE_CHANGE다(B1)."""

    @classmethod
    def setUpClass(cls):
        cls.open_clone()

    def test_rule_on_removed_axis_does_not_loop(self):
        s = base_sheets()
        s["taxonomy"] = [r for r in s["taxonomy"] if not (r[0] == KEEP and r[1] is not None)]
        write_tax(self.ws.taxonomy_path, s)
        tax, _ = pipeline.load_taxonomy(self.ws)
        p, run_b, _ = pipeline.run_axis_update(self.ws, transport=MockChatTransport(Mock(fail=None)))
        self.assertEqual((p["removed"], run_b is not None), ([KEEP], True))
        self.assertNotIn(KEEP, store.meta_json(self.con, "rules_applied:" + run_b)["classify"])
        signal(self.ws, "done", run_b)
        res = rulesdiff.compare(self.ws, self.con, tax)
        self.assertEqual((res["code"], res["run_id"]), (rulesdiff.NO_RULE_CHANGE, run_b))
        # 비활성 축 규칙이 기록에 남아 있어도(옛 기록) 범위에 들어가지 않는다
        rec = store.meta_json(self.con, "rules_applied:" + run_b)
        rec["classify"][KEEP] = store.meta_json(self.con, "rules_applied:" + self.run_a)["classify"][KEEP]
        store.meta_set(self.con, "rules_applied:" + run_b, util.dumps(rec))
        self.con.commit()
        res = rulesdiff.compare(self.ws, self.con, tax)
        self.assertEqual((res["disabled"], res["code"]), (["FR-AX"], rulesdiff.NO_RULE_CHANGE))
        self.assertEqual(rulesupdate.plan(self.ws, self.con, tax)["code"], rulesdiff.NO_RULE_CHANGE)


class PartialFailThenRulesUpdateTest(_Case):
    """axis-update에서 부분 분류에 실패한 chunk(대상 축 없음)는 rules-update를 거쳐도 적재·내보내기에서 빠진다."""

    @classmethod
    def setUpClass(cls):
        cls.open_clone()
        s = base_sheets()
        s["taxonomy"].append(tax_row(DS, "rejected"))  # 의사결정 상태 값 추가 → 대상 축
        write_tax(cls.ws.taxonomy_path, s)
        cls.tax, _ = pipeline.load_taxonomy(cls.ws)
        _, cls.run_b, _ = pipeline.run_axis_update(cls.ws, transport=MockChatTransport(Mock()))
        signal(cls.ws, "done", cls.run_b)
        final_b = finals.final_labels(cls.con, cls.run_b)
        flagged = {r[0] for r in cls.con.execute("SELECT chunk_id FROM flagged_chunks WHERE run_id=?", (cls.run_b,))}
        cls.unfilled = finals.incomplete(cls.con, cls.run_b, final_b)
        write_rules(cls.ws, [edit(R_AX, "MARK-V1"), R_FM, R_ANS, R_GEN, R_WIDE])
        cls.plan, cls.run_r, _ = pipeline.run_rules_update(cls.ws, transport=MockChatTransport(Mock(fail=None)))
        cls.c = sorted(cls.unfilled & set(cls.plan["axis_targets"]) & flagged)[0]

    def push(self):
        embed.embed(self.ws, self.con, self.run_r, transport=MockEmbedTransport())
        sink = Sink()
        self.ws.config["supabase"].update(SUPABASE)
        try:
            vectorpush.push(self.ws, self.con, self.run_r, sink=sink, force=True)
        finally:
            self.ws.config["supabase"].update({"enabled": False, "url": ""})
        return {r["chunk_id"] for r in sink.rows}

    def test_unfilled_chunk_not_pushed_until_human_fills(self):
        c, r = self.c, self.run_r
        self.assertIsNotNone(r)
        self.assertIn(KEEP, self.plan["axis_targets"][c])  # rules-update가 이 chunk를 다시 라벨했다
        final_r = finals.final_labels(self.con, r)
        self.assertNotIn(DS, final_r[c]["axes"])
        self.assertIn(c, finals.incomplete(self.con, r, final_r))
        self.assertTrue(self.con.execute("SELECT 1 FROM failures WHERE run_id=? AND stage='classify' AND target_id=?",
                                         (r, c)).fetchone())  # 이어받은 분류 실패 기록이 남는다
        out = sqlite3.connect(self.ws.path("out", "labeling.sqlite"))
        try:
            self.assertEqual(out.execute("SELECT COUNT(*) FROM facet_labels WHERE chunk_id=?", (c,)).fetchone()[0], 0)
        finally:
            out.close()
        self.assertNotIn(c, self.push())
        doc = {"kind": "review", "run_id": self.run_b, "chunk_status": [], "synonyms": [],
               "corrections": [{"chunk_id": c, "target": "axis", "key": DS, "value": ["adopted"]}]}
        self.assertEqual({x[1] for x in apply_doc(self.ws, self.con, self.tax, doc, "review_fill.json")}, {"OK"})
        self.assertNotIn(c, finals.incomplete(self.con, r, finals.final_labels(self.con, r)))
        self.assertIn(c, self.push())


if __name__ == "__main__":
    unittest.main()
