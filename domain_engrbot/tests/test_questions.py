"""질문 생성(질문 루프 A) 테스트: context 조립, LLM 응답 검증·정리, 이월·재사용, 오류 코드, CLI, status, 자유 답 초안, workspaces.

작업 폴더는 test_ledger의 합성 픽스처(build_ws)를 코드 폴더 밖 임시 폴더에 만든다. 임시 작업 폴더에서는 장부가
<작업 폴더>/qa/ledger, 질문 폴더가 <작업 폴더>/qa/questions다. 승인 파일도 임시 경로를 쓴다. LLM은 MockJudgeLLM(responder)이고,
질문 화면(작업 C)은 _build_screen을 mock으로 바꿔 끼운다. 네트워크는 쓰지 않는다.
"""
import contextlib
import io as std_io
import json
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

from domain_engrbot import cli, io, labeling_rules as lr, ledger, qmodel, questions, workspaces
from domain_engrbot import policy as policy_mod
from domain_engrbot.llm import MockJudgeLLM
from domain_engrbot.tests.test_ledger import (APPROVED_QID, BODY, DEFECT, EV_QUOTE, FILE_NAME, LAYER, MEMO, REASON, _pol,
                                       build_ws, cid_of)

QTEXT = "질문표식QQQ"   # LLM이 만든 질문·선택지 문장 표식. 콘솔·generate_log에 나오면 안 된다


def _context(messages):
    return json.loads(messages[1]["content"])


def _pattern(ctx, kind, target):
    return next(p["ref"] for p in ctx["patterns"] if p["kind"] == kind and p["target"] == target)


def _case(ctx, n, field):
    """chunk 번호 n 레코드의 그 필드 사례 ref(레코드 ref로 찾는다)."""
    return next(c["ref"] for c in ctx["cases"] if c["field"] == field and c.get("record")
                and ctx["records"][int(c["record"][1:]) - 1].get("text", "").endswith("slide%d 내용" % n))


def _q(goal="labeling", axis=DEFECT, values=("Open",), text=None, refs=(), options=None, why="교정이 갈렸다."):
    return {"goal": goal, "topic": {"type": "axis_value", "axis": axis, "values": list(values)},
            "text": text or "%s %s 값을 붙이는 기준은 무엇인가?" % (QTEXT, "/".join(values)), "why": why,
            "refs": list(refs), "options": options if options is not None else []}


def _rule(text, target=DEFECT, stage="classify", **kw):
    return dict({"type": "rule", "stage": stage, "target": target, "text": text}, **kw)


class Responder(object):
    """MockJudgeLLM responder. build(context) → 응답 dict(또는 문자열). 호출 수와 마지막 context를 남긴다."""

    def __init__(self, build):
        self.build = build
        self.calls = 0
        self.last = None

    def __call__(self, messages, file_ids, hint):
        self.calls += 1
        self.last = _context(messages)
        out = self.build(self.last)
        return out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)


def _normal(ctx):
    """승인 대기 패턴(REMOVE 불량 모드 Open)과 근거 사례를 쓰는 질문 둘."""
    fr = _pattern(ctx, "REMOVE", DEFECT)
    c2 = _case(ctx, 2, "axis:" + DEFECT)
    ex = next(r["example_id"] for r in ctx["records"] if r.get("example_id") and r["text"].endswith("slide2 내용"))
    q1 = _q(refs=[fr, c2], options=[
        {"label": QTEXT + " 본문에 Open 진술이 직접 있을 때만 붙인다.",
         "drafts": [_rule("본문이 단선(Open)을 직접 진술할 때만 Open을 붙인다.", pattern_ref=fr),
                    {"type": "example", "example_id": ex}]},
        {"label": QTEXT + " Short와 함께 나오면 Open을 뺀다.",
         "drafts": [_rule("Short와 Open이 함께 언급되면 원인 진술이 있는 값만 둔다."),
                    {"type": "taxonomy", "kind": "value_def", "axis": DEFECT, "value": "Open",
                     "definition": "배선이 끊어져 전기적으로 열린 불량."}]}])
    q2 = _q(goal="taxonomy", axis=LAYER, values=("M1", "M2"), refs=[_pattern(ctx, "ADD", LAYER)], options=[
        {"label": QTEXT + " 두 값의 범위가 겹친다.", "drafts": [
            {"type": "taxonomy", "kind": "overlap", "axis": LAYER, "values": ["M1", "M2"],
             "include": "M1은 첫 금속층", "exclude": "M2는 두 번째 금속층"}]}])
    return {"questions": [q1, q2]}


class QuestionsTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="domain_engrbot_questions_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = build_ws(self.tmp, "ws1")
        reports = os.path.join(self.root, "reports")
        os.makedirs(reports)
        io.write_jsonl(os.path.join(reports, "taxonomy_revisit.jsonl"), [
            {"review_run_id": "r", "chunk_id": cid_of(1), "target": "axis", "key": DEFECT, "reason": "NEW_VALUE",
             "proposed": {"value": "Via open", "parent": None}, "memo": MEMO}])
        self.pol = _pol()
        self.paths = io.QaPaths(self.root)
        self.rules = os.path.join(self.tmp, "labeling_rules.json")
        self.d = ledger.ledger_dir(self.root, self.pol)
        self.qd = qmodel.qdir(self.d)
        p = mock.patch("domain_engrbot.questions._build_screen", return_value=0)
        self.screen = p.start()
        self.addCleanup(p.stop)

    def gen(self, build=_normal, responder=None, **kw):
        resp = responder or Responder(build)
        out = questions.generate(self.paths, self.pol, llm=MockJudgeLLM(responder=resp), rules_path=self.rules, **kw)
        return out, resp

    def doc(self):
        return qmodel.load_set(self.qd)

    def write_asked(self, entries, key="answered"):
        """asked.json을 쓰고, answers.apply처럼 닫은 질문을 questions.json에서 뺀다."""
        doc = qmodel.empty_asked()
        doc[key] = entries
        qmodel.save_asked(self.qd, doc)
        cur = qmodel.load_set(self.qd)
        if cur is not None:
            qmodel.save_set(self.qd, dict(cur, questions=[q for q in cur["questions"] if q["fingerprint"] not in entries]))


class ContextTest(QuestionsTestBase):
    def test_context_has_patterns_cases_evidence(self):
        ledger.intake(self.root, self.pol)
        ctx = questions.build_context(self.paths, self.pol, self.d, self.qd, [], 7, rules_path=self.rules)
        data = ctx.data
        pend = {p["ref"] for p in data["patterns"] if p["pending"]}
        self.assertEqual(pend, {lr.rule_id("REMOVE", DEFECT, "Open", ""), lr.rule_id("ADD", LAYER, "", "M2"),
                                lr.rule_id("ANSWER", APPROVED_QID, "O", "X")})
        self.assertEqual(data["patterns"][0]["pending"], True)   # 승인 대기 패턴이 앞
        quotes = [x["quote"] for c in data["cases"] for x in c.get("evidence") or []]
        self.assertTrue(any(EV_QUOTE in q for q in quotes))
        self.assertTrue(any(REASON in (c.get("reason") or "") for c in data["cases"]))
        self.assertEqual(data["cases"][0]["kind"], "corrected")
        self.assertTrue(all(BODY in r["text"] for r in data["records"]))
        self.assertTrue(any(r.get("example_id") for r in data["records"]))
        self.assertEqual(data["revisits"][0]["memos"], [MEMO])
        self.assertEqual(data["revisits"][0]["proposed"], ["Via open"])
        self.assertTrue(data["taxonomy"]["axes"])
        self.assertEqual(data["synonyms_registered"][0]["alias"], "단락")
        self.assertEqual(data["axis_stats"][DEFECT]["corrected"], 3)
        self.assertEqual(data["limits"], {"max_new": 7})
        self.assertTrue(ctx.has_input)
        self.assertNotIn(FILE_NAME, json.dumps(data, ensure_ascii=False))

    def evidence_cases(self, ctx):
        """context에 든 사례 중 장부에 근거 인용·이유가 있는 것의 수."""
        ev = {e["case_id"] for e in ledger.read_evidence(self.d) if e.get("evidence") or e.get("reason")}
        return len(ev & {c["case_id"] for c in ctx.cases.values()})

    def test_body_dropped_when_text_changed_or_ws_missing(self):
        ledger.intake(self.root, self.pol)
        with mock.patch.object(questions.labelbot_ws, "chunk_context",
                               side_effect=lambda root, ids: {c: {"title": "t", "text": "x", "text_hash": "다름"}
                                                              for c in ids}):
            ctx = questions.build_context(self.paths, self.pol, self.d, self.qd, [], 5, rules_path=self.rules)
        self.assertFalse(any("text" in r for r in ctx.data["records"]))
        self.assertEqual(ctx.counts["body_missing"], {"TEXT_CHANGED": len(ctx.data["records"])})
        other = io.QaPaths(os.path.join(self.tmp, "다른폴더"))
        shutil.copy(os.path.join(self.root, "pipeline.json"), other.root)   # taxonomy 위치만 같게 둔다
        with mock.patch.object(questions.ledger, "WORKSPACES_DIR", self.tmp + "_없음"):
            ctx = questions.build_context(other, self.pol, self.d, self.qd, [], 5, rules_path=self.rules)
        # 출처 작업 폴더를 확인할 수 없으면 본문뿐 아니라 근거 인용·이유도 보내지 않는다(교정 값은 그대로)
        self.assertEqual(ctx.counts["body_missing"], {"SOURCE_WS_MISSING": len(ctx.data["records"]),
                                                      "EVIDENCE_WS_MISSING": self.evidence_cases(ctx)})
        self.assertFalse(any("evidence" in c or "reason" in c for c in ctx.data["cases"]))
        self.assertTrue(all("bot" in c and "human" in c for c in ctx.data["cases"]))
        # 출처 단위로 센 사유는 레코드마다 CHUNK_MISSING으로 또 세지 않는다
        with mock.patch.object(questions.labelbot_ws, "chunk_context",
                               side_effect=questions.model.BundleError("ADAPTER_DB_MISSING")):
            ctx = questions.build_context(self.paths, self.pol, self.d, self.qd, [], 5, rules_path=self.rules)
        self.assertEqual(ctx.counts["body_missing"], {"SOURCE_DB_UNREADABLE": len(ctx.data["records"])})

    def other_ws(self, base_url):
        """명령에 준 작업 폴더(ws_cmd)가 장부 출처(ws1)와 다른 경우. ws1은 <임시>/ws1에서 찾는다."""
        other = io.QaPaths(os.path.join(self.tmp, "ws_cmd"))
        with open(os.path.join(self.root, "pipeline.json"), encoding="utf-8") as f:
            pipe = json.load(f)
        pipe["llm"] = dict(pipe.get("llm") or {}, base_url=base_url)
        io.write_json(os.path.join(other.root, "pipeline.json"), pipe)
        p = mock.patch.object(questions.ledger, "WORKSPACES_DIR", self.tmp)
        p.start()
        self.addCleanup(p.stop)
        return other

    def test_other_source_body_only_with_same_endpoint(self):
        """다른 작업 폴더의 본문·재검토 메모는 그 폴더의 llm.base_url이 명령에 준 작업 폴더와 같을 때만 넣는다(보안 M2)."""
        ledger.intake(self.root, self.pol)
        same = self.other_ws(" HTTPS://api.openai.com/v1/ ")   # ws1은 기본값(공백·끝 /·대소문자만 다름)
        ctx = questions.build_context(same, self.pol, self.d, self.qd, [], 5, rules_path=self.rules)
        self.assertTrue(all(BODY in r["text"] for r in ctx.data["records"]))
        self.assertEqual(ctx.data["revisits"][0]["memos"], [MEMO])
        self.assertEqual(ctx.counts["body_missing"], {})
        diff = self.other_ws("https://다른곳.invalid/v1")
        ctx = questions.build_context(diff, self.pol, self.d, self.qd, [], 5, rules_path=self.rules)
        self.assertFalse(any("text" in r or "title" in r for r in ctx.data["records"]))
        self.assertEqual(ctx.data["revisits"][0]["memos"], [])
        self.assertEqual(ctx.counts["body_missing"], {"SOURCE_ENDPOINT_DIFFERS": len(ctx.data["records"]),
                                                      "REVISIT_ENDPOINT_DIFFERS": 1,
                                                      "EVIDENCE_ENDPOINT_DIFFERS": self.evidence_cases(ctx)})
        self.assertFalse(any("evidence" in c or "reason" in c for c in ctx.data["cases"]))
        text = json.dumps(ctx.data, ensure_ascii=False)
        for bad in (BODY, MEMO):
            self.assertNotIn(bad, text)
        with mock.patch.object(questions.labelbot_ws, "read_config",
                               side_effect=questions.model.BundleError("ADAPTER_CONFIG_INVALID")):
            self.assertIsNone(questions._endpoint(self.root))


class GenerateTest(QuestionsTestBase):
    def test_normal_response(self):
        out, resp = self.gen()
        self.assertEqual((out["questions"], out["labeling"], out["taxonomy"], out["carried"], out["llm_calls"]),
                         (2, 1, 1, 0, 1))
        self.assertFalse(out["reused"])
        doc = self.doc()
        self.assertTrue(qmodel.valid_set_id(doc["set_id"]))
        self.assertEqual(out["set_id"], doc["set_id"])
        self.assertEqual(doc["model"], "mock")
        self.assertEqual(doc["workspace"], "ws1")
        self.assertIn("ws1", doc["inputs"])
        q1, q2 = doc["questions"]
        self.assertEqual(q1["fingerprint"], qmodel.fingerprint("labeling", q1["topic"], q1["text"]))
        self.assertEqual(q1["question_id"], qmodel.question_id(q1["fingerprint"]))
        fr = lr.rule_id("REMOVE", DEFECT, "Open", "")
        self.assertEqual(q1["patterns"], [fr])
        self.assertEqual(q1["options"][0]["drafts"][0]["pattern_id"], fr)
        self.assertEqual([o["option_id"] for o in q1["options"]], ["A", "B"])
        ledger_cases = {c["case_id"]: c for c in ledger.read(self.d, ledger.CASES)}
        self.assertEqual({ledger_cases[c]["record_id"] for c in q1["evidence"]}, {cid_of(2)})
        self.assertEqual(len(q1["examples"]), 1)
        self.assertTrue(q1["examples"][0].startswith("EX-"))
        self.assertEqual(q1["impact"], {"records": 2})   # 근거 레코드 1, 패턴 지지 2 중 큰 값
        self.assertFalse(q1["carried"])
        self.assertEqual(q2["options"][0]["drafts"][0]["kind"], "overlap")
        self.assertEqual(self.screen.call_count, 1)
        log = io.read_own_jsonl(os.path.join(self.qd, qmodel.GENERATE_LOG))
        self.assertEqual(log[-1]["set_id"], doc["set_id"])
        with open(os.path.join(self.qd, qmodel.GENERATE_LOG), encoding="utf-8") as f:
            text = f.read()
        for bad in (QTEXT, BODY, EV_QUOTE, MEMO, FILE_NAME):
            self.assertNotIn(bad, text)
        self.assertFalse([fn for fn in os.listdir(self.d) if fn == ledger.LOCK_NAME])

    def test_drops_bad_drafts_refs_and_long_text(self):
        def build(ctx):
            fr = _pattern(ctx, "REMOVE", DEFECT)
            return {"questions": [
                _q(refs=[fr, "C999", "FR-0000000000"], options=[
                    {"label": QTEXT + " 좋은 선택지", "drafts": [
                        _rule("{{치환}} 표식이 있는 규칙"), _rule("가" * 301), {"type": "example", "example_id": "EX-" + "0" * 12},
                        {"type": "taxonomy", "kind": "value_add", "axis": DEFECT}, _rule("정상 규칙 문장이다.")]},
                    {"label": "나" * 301, "drafts": []}]),
                _q(values=("Short",), text="다" * 401),
                _q(goal="엉뚱함", values=("Void",)),
                "질문이 아님"]}

        out, _ = self.gen(build)
        self.assertEqual(out["questions"], 1)
        self.assertEqual(out["dropped"], 10)   # 모르는 ref 2, 초안 4, 선택지 1, 질문 3
        q = self.doc()["questions"][0]
        self.assertEqual(len(q["options"]), 1)
        self.assertEqual([d["text"] for d in q["options"][0]["drafts"]], ["정상 규칙 문장이다."])
        log = io.read_own_jsonl(os.path.join(self.qd, qmodel.GENERATE_LOG))[-1]
        self.assertEqual(log["dropped"]["REF_UNKNOWN"], 2)
        self.assertEqual(log["dropped"]["QUESTION_TEXT_INVALID"], 1)

    def test_dup_in_set(self):
        out, _ = self.gen(lambda ctx: {"questions": [_q(text=QTEXT + " 첫 질문"), _q(text=QTEXT + " 같은 주제 다른 문장")]})
        self.assertEqual((out["questions"], out["dup_in_set"]), (1, 1))
        self.assertTrue(self.doc()["questions"][0]["text"].endswith("첫 질문"))

    def test_closed_and_reopened_by_new_evidence(self):
        ref = {}

        def build(ctx):
            ref["fr"] = _pattern(ctx, "REMOVE", DEFECT)
            return {"questions": [_q(refs=[ref["fr"]])]}

        out, _ = self.gen(build)
        q = self.doc()["questions"][0]
        after, before = "2026-10-05T00:00:00Z", "2026-09-01T00:00:00Z"   # 픽스처 교정 반영 시각은 2026-10-01
        self.write_asked({q["fingerprint"]: qmodel.asked_entry(q, "QS-20261001T000000-0000", after)})
        out, _ = self.gen(build, force=True)
        self.assertEqual((out["questions"], out["closed"]), (0, 1))

        def with_case(ctx):
            return {"questions": [_q(refs=[ref["fr"], _case(ctx, 2, "axis:" + DEFECT)])]}

        # 그때도 있던 사례(닫은 시각보다 먼저 반영)를 새로 인용한 것만으로는 닫힌 채다
        out, _ = self.gen(with_case, force=True)
        self.assertEqual((out["questions"], out["closed"]), (0, 1))
        # 닫은 시각보다 늦게 반영된 교정 사례가 붙으면 다시 열고 reopened를 적는다
        self.write_asked({q["fingerprint"]: qmodel.asked_entry(q, "QS-20261001T000000-0000", before)})
        out, _ = self.gen(with_case, force=True)
        self.assertEqual((out["questions"], out["closed"]), (1, 0))
        got = self.doc()["questions"][0]
        self.assertEqual((got["question_id"], got.get("reopened")), (q["question_id"], True))
        self.assertFalse(qmodel.is_closed(qmodel.load_asked(self.qd), got))   # 이월·status도 열린 것으로 본다
        st = questions.status(self.paths, self.pol, rules_path=self.rules)
        self.assertEqual(st["open"], 1)

    def test_reopen_by_new_pending_pattern_and_general(self):
        ref = {}

        def build(ctx):
            ref["fr"] = _pattern(ctx, "REMOVE", DEFECT)
            gen = dict(_q(text=QTEXT + " 일반 질문", refs=[ref["fr"]]), topic={"type": "general"})
            return {"questions": [_q(refs=[ref["fr"]]), gen]}

        self.gen(build)
        q, g = self.doc()["questions"]
        self.assertEqual(g["topic"]["type"], "general")
        at = "2026-10-05T00:00:00Z"
        # 닫을 때 근거에 없던 승인 대기 패턴이 붙으면 다시 연다. general은 근거가 새로 붙어도 닫힌 채다
        self.write_asked({q["fingerprint"]: qmodel.asked_entry(dict(q, patterns=[]), "s", at),
                          g["fingerprint"]: qmodel.asked_entry(dict(g, patterns=[]), "s", at)})
        out, _ = self.gen(build, force=True)
        self.assertEqual((out["questions"], out["closed"]), (1, 1))
        got = self.doc()["questions"][0]
        self.assertEqual((got["question_id"], got["reopened"]), (q["question_id"], True))

    def test_carried_and_max(self):
        three = {"questions": [_q(values=(v,)) for v in ("Open", "Short", "Void")]}
        self.gen(lambda ctx: three)
        first = [q["question_id"] for q in self.doc()["questions"]]
        more = {"questions": [_q(values=(v,)) for v in ("Open", "Bridge", "Crack")]}
        out, resp = self.gen(lambda ctx: more, force=True, max_n=4)
        self.assertEqual(resp.last["limits"], {"max_new": 1})
        self.assertEqual(len(resp.last["open"]), 3)
        self.assertEqual((out["questions"], out["carried"], out["dup_in_set"]), (4, 3, 1))
        qs = self.doc()["questions"]
        self.assertEqual([q["question_id"] for q in qs[:3]], first)
        self.assertTrue(all(q["carried"] for q in qs[:3]))
        self.assertEqual(qs[3]["topic"]["values"], ["Bridge"])
        set_id = self.doc()["set_id"]
        generated_at = self.doc()["generated_at"]
        out, resp = self.gen(lambda ctx: more, force=True, max_n=3)
        self.assertEqual((out["llm_calls"], resp.calls, out["questions"]), (0, 0, 4))
        # 새 질문이 더해지지 않으면 set_id·generated_at을 유지한다
        self.assertEqual((self.doc()["set_id"], self.doc()["generated_at"]), (set_id, generated_at))
        # 답한 질문은 이월하지 않는다(LLM이 새 질문을 0개 내도 set_id 유지)
        q = qs[0]
        self.write_asked({q["fingerprint"]: qmodel.asked_entry(q, "s", "t")})
        out, _ = self.gen(lambda ctx: {"questions": []}, force=True, max_n=5)
        self.assertEqual((out["questions"], out["carried"], out["llm_calls"], out["set_id"]), (3, 2, 1, set_id))
        self.assertNotIn(q["question_id"], [x["question_id"] for x in self.doc()["questions"]])
        # 새 질문이 더해지면 새 set_id
        out, _ = self.gen(lambda ctx: {"questions": [_q(values=("Void2",))]}, force=True, max_n=5)
        self.assertEqual(out["questions"], 4)
        self.assertNotEqual(out["set_id"], set_id)
        with self.assertRaises(questions.QuestionError) as cm:
            self.gen(force=True, max_n=0)
        self.assertEqual(cm.exception.reason_code, "QUESTIONS_CONFIG_INVALID")

    def test_reuse_and_force(self):
        out, resp = self.gen()
        set_id = out["set_id"]
        out, _ = self.gen(responder=resp)
        self.assertTrue(out["reused"])
        self.assertEqual((out["llm_calls"], resp.calls, out["set_id"], out["questions"]), (0, 1, set_id, 2))
        self.assertEqual(self.screen.call_count, 2)
        out, _ = self.gen(responder=resp, force=True)
        self.assertFalse(out["reused"])
        self.assertEqual(resp.calls, 2)

    def test_invalid_json_keeps_old_set(self):
        self.gen()
        path = os.path.join(self.qd, qmodel.QUESTIONS)
        with open(path, encoding="utf-8") as f:
            before = f.read()
        bad = Responder(lambda ctx: "JSON이 아니다")
        with self.assertRaises(questions.QuestionError) as cm:
            self.gen(responder=bad, force=True)
        self.assertEqual(cm.exception.reason_code, "LLM_RESPONSE_INVALID")
        self.assertEqual(bad.calls, 2)   # max_retries 1
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), before)
        self.assertEqual(self.screen.call_count, 1)
        log = io.read_own_jsonl(os.path.join(self.qd, qmodel.GENERATE_LOG))[-1]
        self.assertEqual((log["reason"], log["llm_calls"]), ("LLM_RESPONSE_INVALID", 2))
        # questions 배열이 없어도 다시 부른다
        no_list = Responder(lambda ctx: {"items": []})
        with self.assertRaises(questions.QuestionError):
            self.gen(responder=no_list, force=True)
        self.assertEqual(no_list.calls, 2)

    def test_no_review_input(self):
        root = build_ws(self.tmp, "ws_empty", corrections=False)
        paths = io.QaPaths(root)
        resp = Responder(_normal)
        out = questions.generate(paths, self.pol, llm=MockJudgeLLM(responder=resp), rules_path=self.rules)
        self.assertEqual((out["reason"], out["questions"], out["llm_calls"], resp.calls), ("NO_REVIEW_INPUT", 0, 0, 0))
        qd = qmodel.qdir(ledger.ledger_dir(root, self.pol))
        self.assertEqual(qmodel.load_set(qd)["questions"], [])

    def test_asked_invalid(self):
        os.makedirs(self.qd, exist_ok=True)
        io.write_text(os.path.join(self.qd, qmodel.ASKED), "{깨짐")
        with self.assertRaises(qmodel.QModelError) as cm:
            self.gen()
        self.assertEqual(cm.exception.reason_code, "ASKED_INVALID")

    def test_reopen_baseline_is_when_question_was_made(self):
        """다시 열기의 기준 시각은 답을 반영한 시각(at)이 아니라 그 질문을 만든 시각(seen_at)이다.
        09:00 질문 생성 → 10:00 새 교정 → 11:00 답 반영이면, 10:00 교정은 엔지니어가 못 본 새 근거다."""
        q = {"fingerprint": "fp", "topic": {"type": "axis", "axis": "축"}, "patterns": [], "evidence": ["c-old"]}
        entry = qmodel.asked_entry(q, "QS-20261001T000000-0000", "2026-10-01T11:00:00Z",
                                   seen_at="2026-10-01T09:00:00Z")
        asked = {"answered": {"fp": entry}, "dismissed": {}}
        again = dict(q, evidence=["c-old", "c-new"])
        times = {"c-old": "2026-10-01T08:00:00Z", "c-new": "2026-10-01T10:00:00Z"}
        self.assertFalse(qmodel.is_closed(asked, again, times))
        self.assertTrue(qmodel.is_closed(asked, again, dict(times, **{"c-new": "2026-10-01T08:30:00Z"})))
        # seen_at이 없는 예전 값은 닫은 시각(at)으로 본다
        old = {"answered": {"fp": qmodel.asked_entry(q, "s", "2026-10-01T11:00:00Z")}, "dismissed": {}}
        self.assertTrue(qmodel.is_closed(old, again, times))
        # 새 질문에는 만든 시각이 적힌다
        self.gen()
        self.assertTrue(all(x.get("created_at") for x in self.doc()["questions"]))

    def test_llm_config_missing(self):
        with self.assertRaises(questions.QuestionError) as cm:
            questions.generate(self.paths, self.pol, rules_path=self.rules)
        self.assertEqual(cm.exception.reason_code, "LLM_CONFIG_MISSING")
        self.assertIsNone(self.doc())

    def test_make_llm_reads_env_only_for_real_transport(self):
        """실제 전송 경로를 만들 때만 .env 키를 읽는다(주입한 LLM이나 설정이 없을 때는 읽지 않는다)."""
        cfg = questions.config(self.pol)
        with mock.patch.object(io, "load_env") as load:
            self.assertEqual(questions.make_llm(self.paths.root, cfg, llm="주입"), "주입")
            with self.assertRaises(questions.QuestionError):
                questions.make_llm(self.paths.root, cfg)
            self.assertEqual(load.call_count, 0)
            with mock.patch.object(questions.labelbot_ws, "read_config",
                                   return_value={"llm": {"base_url": "https://llm.invalid/v1", "model": "m"}}):
                llm = questions.make_llm(self.paths.root, cfg)
            self.assertEqual(load.call_count, 1)
            self.assertEqual(llm.name, "m")

    def test_make_llm_overrides_only_set_values(self):
        """questions 설정이 None인 칸은 pipeline 값을 그대로 쓴다."""
        pipe = {"llm": {"base_url": "https://llm.invalid/v1", "model": "pm", "temperature": 0.3, "timeout": 60}}
        with mock.patch.object(io, "load_env"), mock.patch.object(questions.labelbot_ws, "read_config",
                                                                  return_value=pipe):
            llm = questions.make_llm(self.root, dict(questions.config({}), timeout=None))
            self.assertEqual((llm.cfg["model"], llm.cfg["temperature"], llm.cfg["timeout"], llm.cfg["mode"]),
                             ("pm", 0.3, 60, "json"))
            llm = questions.make_llm(self.root, questions.config({"questions": {"model": "qm", "temperature": 0.7}}))
            self.assertEqual((llm.cfg["model"], llm.cfg["temperature"], llm.cfg["timeout"]), ("qm", 0.7, 180))

    def test_pending_pattern_cut_by_max_patterns(self):
        """승인 대기 FR이 max_patterns에서 잘리면 pattern_id를 붙이지 않는다(KeyError 없이 질문은 남는다)."""
        pol = policy_mod.validate_policy({"questions": {"context": {"max_patterns": 1}}})
        cut = {}

        def build(ctx):
            shown = {p["ref"] for p in ctx["patterns"]}
            cut["fr"] = next(r for r in (lr.rule_id("REMOVE", DEFECT, "Open", ""), lr.rule_id("ADD", LAYER, "", "M2"))
                             if r not in shown)
            return {"questions": [_q(refs=[cut["fr"]], options=[
                {"label": QTEXT + " 선택지", "drafts": [_rule("잘린 패턴을 다듬은 규칙이다.", pattern_ref=cut["fr"])]}])]}

        out = questions.generate(self.paths, pol, llm=MockJudgeLLM(responder=Responder(build)), rules_path=self.rules)
        self.assertEqual(out["questions"], 1)
        q = self.doc()["questions"][0]
        self.assertEqual(q["patterns"], [])
        self.assertNotIn("pattern_id", q["options"][0]["drafts"][0])

    def test_reuse_updates_inputs(self):
        """context가 같아 재사용해도 장부 sha가 바뀌었으면 inputs를 맞춘다(workspaces의 question_state)."""
        out, resp = self.gen()
        path = os.path.join(self.qd, qmodel.QUESTIONS)
        doc = self.doc()
        qmodel.save_set(self.qd, dict(doc, inputs={"ws1": "옛 sha"}))
        again, _ = self.gen(responder=resp)
        self.assertTrue(again["reused"])
        self.assertEqual((self.doc()["inputs"], self.doc()["set_id"]), (doc["inputs"], doc["set_id"]))
        self.assertTrue(os.path.isfile(path))
        # 화면에는 작업 폴더 경로(roots)를 넘긴다
        self.assertEqual(self.screen.call_args[0][3], {"ws1": self.root})

    def test_config(self):
        cfg = questions.config({"questions": {"max": 5, "context": {"max_cases": 3}}})
        self.assertEqual((cfg["max"], cfg["context"]["max_cases"], cfg["context"]["text_chars"]), (5, 3, 600))
        for bad in ({"max": 0}, {"max": "5"}, {"context": []}, {"temperature": "높게"}):
            with self.assertRaises(questions.QuestionError):
                questions.config({"questions": bad})


def _recs(new, old):
    """가짜 장부 레코드(교정 많은 순으로 이미 정렬됐다고 본다). new는 최근 작업 폴더, old는 이전 작업 폴더."""
    return ([{"record_id": "n%02d" % i, "text_hash": "h", "source_ws": "ws_new"} for i in range(new)]
            + [{"record_id": "o%02d" % i, "text_hash": "h", "source_ws": "ws_old"} for i in range(old)])


class PickRecordsTest(unittest.TestCase):
    """레코드 표본: 최근 작업 폴더 recent_percent% + 전체 기간 결정적 무작위(사용자 결정 D11)."""

    def ids(self, rows):
        return [r["record_id"] for r in rows]

    def test_split_60_40(self):
        recs = _recs(20, 20)
        recent, rnd = questions.pick_records(recs, "ws_new", 10, 60, 7)
        self.assertEqual(self.ids(recent), ["n%02d" % i for i in range(6)])   # 최근 폴더에서 교정 많은 순
        self.assertEqual(len(rnd), 4)
        self.assertFalse(set(self.ids(recent)) & set(self.ids(rnd)))
        order = {r["record_id"]: i for i, r in enumerate(recs)}
        self.assertEqual(self.ids(rnd), sorted(self.ids(rnd), key=order.get))
        # 같은 시드면 같은 표본, 시드가 바뀌면 표본이 바뀐다
        self.assertEqual(questions.pick_records(recs, "ws_new", 10, 60, 7), (recent, rnd))
        others = {tuple(self.ids(questions.pick_records(recs, "ws_new", 10, 60, s)[1])) for s in range(1, 9)}
        self.assertGreater(len(others), 1)

    def test_fill_when_short(self):
        recent, rnd = questions.pick_records(_recs(2, 20), "ws_new", 10, 60, 1)   # 최근 폴더가 모자람
        self.assertEqual((len(recent), len(rnd)), (2, 8))
        recent, rnd = questions.pick_records(_recs(20, 1), "ws_new", 10, 60, 1)   # 다른 폴더가 모자람
        self.assertEqual((len(recent), len(rnd)), (6, 4))
        self.assertGreaterEqual(sum(r["source_ws"] == "ws_new" for r in rnd), 3)
        recent, rnd = questions.pick_records(_recs(3, 4), "ws_new", 10, 60, 1)    # 풀이 상한보다 작음
        self.assertEqual((len(recent), len(rnd)), (3, 4))
        self.assertEqual(questions.pick_records([], "ws_new", 10, 60, 1), ([], []))

    def test_percent_edges(self):
        recs = _recs(20, 20)
        recent, rnd = questions.pick_records(recs, "ws_new", 10, 0, 3)
        self.assertEqual((len(recent), len(rnd)), (0, 10))
        recent, rnd = questions.pick_records(recs, "ws_new", 10, 100, 3)
        self.assertEqual((self.ids(recent), rnd), (["n%02d" % i for i in range(10)], []))
        self.assertEqual(questions.config({"questions": {"context": {"recent_percent": 0}}})["context"]["recent_percent"], 0)
        self.assertEqual(questions.config({})["context"]["recent_percent"], 60)
        for bad in (101, -1, True, 50.5):
            with self.assertRaises(questions.QuestionError) as cm:
                questions.config({"questions": {"context": {"recent_percent": bad}}})
            self.assertEqual(cm.exception.reason_code, "QUESTIONS_CONFIG_INVALID")


class SampleContextTest(QuestionsTestBase):
    def ctx(self, paths=None, **context):
        pol = policy_mod.validate_policy({"questions": {"context": context}} if context else {})
        return questions.build_context(paths or self.paths, pol, self.d, self.qd, [], 5, rules_path=self.rules)

    def test_counts_and_cases_first(self):
        ledger.intake(self.root, self.pol)
        ctx = self.ctx(max_records=5, max_cases=3)
        self.assertEqual((ctx.counts["records_recent"], ctx.counts["records_random"], ctx.counts["records"]), (3, 2, 5))
        # 최근 몫(교정 많은 순)이 R1~R3
        full = self.ctx()
        self.assertEqual([r["final_axes"] for r in ctx.data["records"][:3]],
                         [r["final_axes"] for r in full.data["records"][:3]])
        # max_cases에서 잘려도 뽑힌 레코드의 사례가 먼저 남는다
        self.assertEqual(len(ctx.data["cases"]), 3)
        self.assertTrue(all(c["record"] for c in ctx.data["cases"]))
        tiny = self.ctx(max_records=1, max_cases=40)
        recs = {c["record"] for c in tiny.data["cases"][:1]}
        self.assertEqual(recs, {"R1"})
        self.gen()
        log_counts = io.read_own_jsonl(os.path.join(self.qd, qmodel.GENERATE_LOG))[-1]["context"]
        self.assertEqual((log_counts["records_recent"], log_counts["records_random"]), (7, 0))

    def test_other_workspace_is_all_random(self):
        """명령에 준 작업 폴더가 장부에 없으면(최근 폴더 레코드 0) 무작위 몫이 전부를 채운다."""
        ledger.intake(self.root, self.pol)
        other = io.QaPaths(os.path.join(self.tmp, "ws_other"))
        shutil.copy(os.path.join(self.root, "pipeline.json"), other.root)
        with mock.patch.object(questions.ledger, "WORKSPACES_DIR", self.tmp):
            ctx = self.ctx(paths=other, max_records=5)
        self.assertEqual((ctx.counts["records_recent"], ctx.counts["records_random"]), (0, 5))

    def test_seed_follows_ledger(self):
        ledger.intake(self.root, self.pol)
        seeds = []
        real = questions.random.Random

        def spy(seed):
            seeds.append(seed)
            return real(seed)

        with mock.patch.object(questions.random, "Random", side_effect=spy):
            self.ctx(max_records=5)
            self.ctx(max_records=5)
            path = os.path.join(self.d, ledger.SOURCES)
            rows = io.read_own_jsonl(path)
            io.write_jsonl(path, [dict(r, corrections_sha="바뀐 검수") for r in rows])
            self.ctx(max_records=5)
        self.assertEqual(seeds[0], seeds[1])
        self.assertNotEqual(seeds[1], seeds[2])

    def test_reuse_with_sampling(self):
        pol = policy_mod.validate_policy({"questions": {"context": {"max_records": 4}}})
        resp = Responder(_normal)
        llm = MockJudgeLLM(responder=resp)
        first = questions.generate(self.paths, pol, llm=llm, rules_path=self.rules)
        again = questions.generate(self.paths, pol, llm=llm, rules_path=self.rules)
        self.assertEqual((again["reused"], again["set_id"], resp.calls), (True, first["set_id"], 1))


class CliStatusTest(QuestionsTestBase):
    def cli(self, *argv):
        buf = std_io.StringIO()
        llm = MockJudgeLLM(responder=Responder(_normal))
        with mock.patch.object(lr, "RULES_PATH", self.rules), \
                mock.patch.object(questions, "make_llm", lambda root, cfg, llm_=None: llm), \
                contextlib.redirect_stdout(buf):
            code = cli.main(["questions"] + list(argv) + ["--workspace", self.root])
        return code, buf.getvalue()

    def test_cli_output_has_no_text(self):
        code, out = self.cli("generate")
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"^\[questions\] set_id=QS-\S+ 질문 2건\(라벨링 1 · taxonomy 1, 이월 0\), LLM 호출 1회 → "
                              r"qa/questions/engr_questions\.html\n$")
        code, out2 = self.cli("generate")
        self.assertIn("[questions] 재사용: 입력이 그대로다(LLM 0회). 질문 2건 대기", out2)
        code, out3 = self.cli("status")
        st = json.loads(out3)
        self.assertEqual((st["open"], st["labeling"], st["taxonomy"], st["answered_total"]), (2, 1, 1, 0))
        self.assertEqual(st["pending_patterns"], 3)
        for text in (out, out2, out3):
            for bad in (QTEXT, BODY, EV_QUOTE, MEMO, REASON, FILE_NAME):
                self.assertNotIn(bad, text)

    def test_cli_errors(self):
        os.makedirs(self.qd, exist_ok=True)
        io.write_text(os.path.join(self.qd, qmodel.QUESTIONS), "{깨짐")
        code, out = self.cli("status")
        self.assertEqual((code, out), (1, "[오류] QUESTIONS_INVALID\n"))
        os.remove(os.path.join(self.qd, qmodel.QUESTIONS))
        code, out = self.cli("screen")
        self.assertEqual(code, 1)
        self.assertIn("[오류] QUESTIONS_NOT_FOUND", out)
        with mock.patch.object(lr, "RULES_PATH", self.rules),                 mock.patch.object(questions, "make_llm", side_effect=questions.QuestionError("LLM_CONFIG_MISSING")):
            buf = std_io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = cli.main(["questions", "generate", "--workspace", self.root])
        self.assertEqual((code, buf.getvalue()), (1, "[오류] LLM_CONFIG_MISSING\n"))

    def test_cli_no_input_with_carried_and_screen_error(self):
        self.cli("generate")
        n = len(self.doc()["questions"])
        empty = build_ws(self.tmp, "ws_empty", corrections=False)
        qd = qmodel.qdir(ledger.ledger_dir(empty, self.pol))
        os.makedirs(qd)
        shutil.copy(os.path.join(self.qd, qmodel.QUESTIONS), qd)
        buf = std_io.StringIO()
        with mock.patch.object(lr, "RULES_PATH", self.rules), contextlib.redirect_stdout(buf):
            code = cli.main(["questions", "generate", "--workspace", empty])
        self.assertEqual(code, 0)
        self.assertEqual(buf.getvalue(), "[questions] 질문 재료 없음(NO_REVIEW_INPUT). 남은 질문 %d건 대기 → "
                                         "qa/questions/engr_questions.html\n" % n)
        from domain_engrbot.question_screen import QuestionScreenError

        self.screen.side_effect = QuestionScreenError("SCREEN_TEMPLATE_INVALID")
        code, out = self.cli("screen")
        self.assertEqual((code, out), (1, "[오류] SCREEN_TEMPLATE_INVALID\n"))

    def test_cli_apply_line(self):
        fake = mock.Mock()
        fake.AnswersError = type("AnswersError", (Exception,), {})
        fake.apply.return_value = {"answered": 2, "dismissed": 1, "skipped": 1, "rules": 1, "patterns_approved": 1,
                                   "patterns_closed": 1, "taxonomy": 1, "examples": 0, "invalid": [
                                       {"question_id": "EQ-0000000000", "code": "NO_CONFIRMED_DRAFT"}],
                                   "not_open": [], "remaining": 3, "enabled_rules": {}, "cap": 30, "notes": []}
        with mock.patch.dict("sys.modules", {"domain_engrbot.answers": fake}), mock.patch("domain_engrbot.answers", fake, create=True):
            code, out = self.cli("apply")
        self.assertEqual(code, 0)
        lines = out.splitlines()
        self.assertEqual(lines[0], "[questions] 반영: 답 2(규칙 1 · taxonomy 제안 1 · 사례 0), 후보 승인 1 · 종결 1, "
                                   "묻지 않음 1, 건너뜀 1, 남은 질문 3")
        self.assertEqual(json.loads(lines[1]), {"invalid": [{"question_id": "EQ-0000000000",
                                                              "code": "NO_CONFIRMED_DRAFT"}]})

    def test_status_inbox(self):
        self.gen()
        qid = self.doc()["questions"][0]["question_id"]
        set_id = self.doc()["set_id"]
        good = os.path.join(self.paths.inbox, qmodel.answers_name(set_id))
        io.write_json(good, {"kind": qmodel.ANSWERS_KIND, "set_id": set_id, "answers": [
            {"question_id": qid, "action": "answer", "confirmed": []},
            {"question_id": "EQ-0000000000", "action": "dismiss"}, {"question_id": qid, "action": "skip"}]})
        bad = os.path.join(self.paths.inbox, "engr_answers_QS-20261001T000000-0000.json")
        io.write_text(bad, "{깨짐")
        old = time.time() - 100
        os.utime(bad, (old, old))
        st = questions.status(self.paths, self.pol, rules_path=self.rules)
        self.assertEqual([x["name"] for x in st["inbox"]], [os.path.basename(good), os.path.basename(bad)])
        g, b = st["inbox"]
        # open_matches는 반영할 것이 있는 답(답·묻지 않음)만 센다. 나중에(skip)는 세지 않는다
        self.assertEqual((g["set_id"], g["answer"], g["dismiss"], g["skip"], g["open_matches"], g["reason"]),
                         (set_id, 1, 1, 1, 1, None))
        self.assertRegex(g["saved_at"], r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$")
        self.assertEqual((b["reason"], b["set_id"], b["answer"]), ("ANSWERS_JSON_INVALID", None, 0))
        self.assertNotIn(QTEXT, json.dumps(st, ensure_ascii=False))


class DraftTest(QuestionsTestBase):
    def test_draft_for_answer(self):
        self.gen()
        q = self.doc()["questions"][0]
        fr = q["patterns"][0]
        resp = Responder(lambda ctx: {"drafts": [
            _rule("자유 답에서 옮긴 규칙이다.", pattern_ref=fr), _rule("{{깨짐}}"),
            {"type": "example", "example_id": "EX-" + "1" * 12}, {"type": "example", "example_id": q["examples"][0]},
            _rule("없는 축 규칙이다.", target="없는축")]})
        axes = [LAYER, DEFECT]
        drafts = questions.draft_for_answer(q, "단선 진술이 직접 있을 때만 Open이다.", MockJudgeLLM(responder=resp), axes)
        self.assertEqual(drafts[0], {"type": "rule", "stage": "classify", "target": DEFECT,
                                     "text": "자유 답에서 옮긴 규칙이다.", "pattern_id": fr})
        self.assertEqual(drafts[1], {"type": "example", "example_id": q["examples"][0]})
        self.assertEqual(drafts[2]["target"], "")
        self.assertEqual(len(drafts), 3)
        self.assertEqual(resp.last["answer"], "단선 진술이 직접 있을 때만 Open이다.")
        self.assertEqual(resp.last["axes"], sorted(axes))
        for build, code in ((lambda ctx: "아님", "LLM_RESPONSE_INVALID"), (lambda ctx: {"drafts": []}, "DRAFT_EMPTY")):
            with self.assertRaises(questions.QuestionError) as cm:
                questions.draft_for_answer(q, "답", MockJudgeLLM(responder=Responder(build)), axes)
            self.assertEqual(cm.exception.reason_code, code)
        with self.assertRaises(questions.QuestionError) as cm:
            questions.draft_for_answer(q, "가" * (qmodel.FREE_MAX + 1), MockJudgeLLM(responder=resp), axes)
        self.assertEqual(cm.exception.reason_code, "ANSWER_TEXT_INVALID")

    def test_make_drafter(self):
        self.gen()
        drafter, why = questions.make_drafter(self.paths, self.pol, self.qd)
        self.assertEqual((drafter, why), (None, "LLM_CONFIG_MISSING"))
        llm = MockJudgeLLM(responder=Responder(lambda ctx: {"drafts": [_rule("규칙 문장이다.")]}))
        with mock.patch.object(questions, "make_llm", return_value=llm):
            drafter, why = questions.make_drafter(self.paths, self.pol, self.qd)
        q = self.doc()["questions"][0]
        self.assertEqual(drafter(q["question_id"], "자유 답")[0]["text"], "규칙 문장이다.")
        with self.assertRaises(questions.QuestionError) as cm:
            drafter("EQ-0000000000", "자유 답")
        self.assertEqual(cm.exception.reason_code, "QUESTION_NOT_OPEN")


class WorkspacesQuestionStateTest(QuestionsTestBase):
    def test_question_state(self):
        empty = build_ws(self.tmp, "ws_empty", corrections=False)
        rows = {r["workspace"]: r for r in workspaces.scan(self.tmp)}
        self.assertEqual((rows["ws1"]["question_state"], rows["ws1"]["review_runs"]), ("new", 1))
        self.assertEqual((rows["ws_empty"]["question_state"], rows["ws_empty"]["review_runs"]), ("no_review", 0))
        self.assertEqual(rows["ws1"]["state"], "new")   # 기존 QA 상태 칸은 그대로
        self.gen()
        rows = {r["workspace"]: r for r in workspaces.scan(self.tmp)}
        self.assertEqual(rows["ws1"]["question_state"], "asked")
        self.assertIsNone(rows["ws1"]["question_reason"])
        self.assertTrue(os.path.isdir(empty))
        io.write_text(os.path.join(self.qd, qmodel.QUESTIONS), "{깨짐")
        row = {r["workspace"]: r for r in workspaces.scan(self.tmp)}["ws1"]
        self.assertEqual((row["question_state"], row["question_reason"]), (None, "QUESTIONS_INVALID"))


if __name__ == "__main__":
    unittest.main()
