"""질문 루프 답 반영 테스트(answers.apply): MANUAL 규칙, 패턴 승인·종결 순서, taxonomy 제안(S7 입력), 사례,
묻지 않음·건너뜀, 틀린 초안, not_open과 멱등, rules_history, 오류 코드, 규칙 상한, 저장 전 예외.

작업 폴더·장부는 test_ledger의 합성 픽스처(build_ws)를 코드 폴더 밖 임시 폴더에 만든다. 질문 폴더는 장부의 형제
<작업 폴더>/qa/questions이고, 승인 파일은 테스트마다 임시 경로다(코드 폴더의 taxonomy/labeling_rules.json과
workspaces/_domain_engrbot을 건드리지 않는다). 질문 화면 만들기(_build_screen)는 mock으로 바꿔 끼운다. 네트워크·LLM은 쓰지 않는다.
"""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from domain_engrbot import answers, io, labeling_rules as lr, ledger, model, qmodel
from domain_engrbot.tests.test_ledger import APPROVED_QID, DEFECT, LAYER, _pol, build_ws, cid_of

SET_ID = "QS-20261006T010203-ab12"
OTHER_SET = "QS-20261005T000000-cd34"
AT = "2026-10-06T01:02:03Z"
QTEXT = "질문문장표식QTX"   # 질문 문장 표식. 결과 dict에는 나오면 안 된다


def make_question(text, goal="labeling", topic=None, patterns=(), examples=(), records=2):
    """qmodel 형식의 질문 하나(지문·질문 ID는 qmodel이 만든다)."""
    topic = qmodel.normalize_topic(topic or {"type": "general"})
    fp = qmodel.fingerprint(goal, topic, text)
    return {"question_id": qmodel.question_id(fp), "fingerprint": fp, "goal": goal, "topic": topic, "text": text,
            "why": "왜 묻는지", "carried": False, "evidence": [], "patterns": list(patterns), "examples": list(examples),
            "revisits": [], "impact": {"records": records}, "options": []}


def save_questions(qd, questions, set_id=SET_ID):
    doc = qmodel.empty_set("ws1", set_id, now=AT)
    doc["questions"] = list(questions)
    qmodel.save_set(qd, doc)
    return doc


def write_answers(inbox, items, set_id=SET_ID, name=None, reviewer="검수자"):
    os.makedirs(inbox, exist_ok=True)
    p = os.path.join(inbox, name or qmodel.answers_name(set_id))
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"kind": qmodel.ANSWERS_KIND, "set_id": set_id, "reviewer": reviewer, "answers": items}, f,
                  ensure_ascii=False)
    return p


def answer(q, *drafts, option_id="A"):
    return {"question_id": q["question_id"], "action": "answer", "option_id": option_id, "option_label": "선택지",
            "free_text": "", "confirmed": list(drafts)}


def rule(text, stage="classify", target="", pattern_id=None, origin="llm"):
    d = {"type": "rule", "stage": stage, "target": target, "text": text, "origin": origin}
    if pattern_id:
        d["pattern_id"] = pattern_id
    return d


def tax(kind, **kw):
    return dict({"type": "taxonomy", "kind": kind, "origin": "edited"}, **kw)


def snapshot(*dirs_or_files):
    """폴더·파일 내용(이름 → 글) 스냅숏. 멱등·무변경 확인용."""
    out = {}
    for p in dirs_or_files:
        files = [os.path.join(dp, f) for dp, _, fs in os.walk(p) for f in fs] if os.path.isdir(p) else [p]
        for f in files:
            if os.path.isfile(f):
                with open(f, encoding="utf-8") as fh:
                    out[f] = fh.read()
    return out


class QuestionAnswersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="domain_engrbot_qanswers_")
        cls.root = build_ws(cls.tmp, "ws1")
        cls.pol = _pol()
        ledger.intake(cls.root, cls.pol)
        cls.paths = io.QaPaths(cls.root)
        cls.d = ledger.ledger_dir(cls.root, cls.pol)
        cls.qd = qmodel.qdir(cls.d)
        cls.cfg = lr.config(cls.pol)
        c = lr.candidates(cls.d, lr.empty_rules(), cls.cfg)
        by = {(r["kind"], r["target"]): r["rule_id"] for r in c["rules"]}
        cls.fr_rm, cls.fr_add, cls.fr_ans = by[("REMOVE", DEFECT)], by[("ADD", LAYER)], by[("ANSWER", APPROVED_QID)]
        exs = {e["record_id"]: e["example_id"] for e in c["examples"]}
        cls.ex1, cls.ex2 = exs[cid_of(2)], exs[cid_of(10)]
        # 후보 기준(min_count) 아래인 패턴: 검증 질문 답 뒤집힘 1건
        cls.fr_low = [r["rule_id"] for r in lr.all_rules(lr._latest_cases(cls.d), cls.cfg["min_count"]).values()
                      if r["kind"] == "GEN_ANSWER"][0]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="domain_engrbot_qanswers_out_")
        self.addCleanup(shutil.rmtree, self.out, True)
        self.rules = os.path.join(self.out, "labeling_rules.json")
        shutil.rmtree(self.qd, ignore_errors=True)
        for fn in os.listdir(self.paths.inbox):
            os.remove(os.path.join(self.paths.inbox, fn))
        p = mock.patch("domain_engrbot.answers._build_screen", return_value=0)
        self.screen = p.start()
        self.addCleanup(p.stop)

    def apply(self, **kw):
        kw.setdefault("rules_path", self.rules)
        kw.setdefault("now", AT)
        return answers.apply(self.paths, self.pol, **kw)

    def doc(self):
        return lr.load_rules(self.rules)

    def rule_of(self, rid):
        found = [r for r in self.doc()["rules"] if r["rule_id"] == rid]
        return found[0] if found else None

    def qfile(self, name):
        return os.path.join(self.qd, name)

    def refused(self, code, **kw):
        before = snapshot(self.qd)
        with self.assertRaises(answers.AnswersError) as cm:
            self.apply(**kw)
        self.assertEqual(cm.exception.reason_code, code)
        self.assertFalse(os.path.exists(self.rules), code)
        self.assertEqual(snapshot(self.qd), before, code)
        self.assertFalse(os.path.exists(os.path.join(self.d, ledger.LOCK_NAME)))

    # ---- 규칙 -------------------------------------------------------------

    def test_manual_rules(self):
        """pattern_id 없는 rule 초안 → MANUAL 규칙. 단계별 target, origin, 두 승인 파일 검사 통과, 이력·asked·묶음."""
        q = make_question(QTEXT)
        save_questions(self.qd, [q])
        write_answers(self.paths.inbox, [answer(q, rule("분류 규칙 문장이다.", target=LAYER, origin="edited"),
                                              rule("라벨 규칙 문장이다.", stage="label", target=LAYER, origin="human"),
                                              rule("대상 없는 분류 규칙이다.", origin="bogus"))])
        res = self.apply()
        self.assertEqual((res["answered"], res["rules"], res["remaining"]), (1, 3, 0))
        self.assertEqual(res["enabled_rules"], {"classify": 2, "label": 1})
        self.assertEqual((res["cap"], res["notes"], res["invalid"], res["not_open"]), (30, [], [], []))
        fp = q["fingerprint"]
        got = {r["text"]: r for r in self.doc()["rules"]}
        cl, lb, plain = got["분류 규칙 문장이다."], got["라벨 규칙 문장이다."], got["대상 없는 분류 규칙이다."]
        self.assertEqual(cl["rule_id"], answers.manual_rule_id(fp, "classify", LAYER, "분류 규칙 문장이다."))
        self.assertTrue(cl["rule_id"].startswith("QR-") and len(cl["rule_id"]) == 13)
        self.assertEqual((cl["kind"], cl["target"], cl["origin"]), ("MANUAL", LAYER, "edited"))
        self.assertEqual((lb["target"], lb["origin"]), ("label", "human"))
        self.assertEqual((plain["target"], plain["origin"]), ("classify", "llm"))
        for r in (cl, lb, plain):
            self.assertTrue(lr.valid_rule(r))
            self.assertEqual((r["from"], r["to"], r["count"], r["enabled"]), ("", "", 2, True))
            self.assertEqual((r["question_id"], r["set_id"], r["approved_by"], r["approved_at"]),
                             (q["question_id"], SET_ID, "screen", AT))
        hist = io.read_own_jsonl(self.qfile(qmodel.ANSWERS_LOG))
        self.assertEqual(len(hist), 1)
        self.assertEqual((hist[0]["text"], hist[0]["action"], hist[0]["reviewer"], hist[0]["option_id"]),
                         (QTEXT, "answer", "검수자", "A"))
        self.assertEqual([d["origin"] for d in hist[0]["confirmed"]], ["edited", "human", "llm"])
        asked = qmodel.load_asked(self.qd)
        with open(os.path.join(self.paths.inbox, qmodel.answers_name(SET_ID)), encoding="utf-8") as f:
            sha = model.hash_obj(json.load(f))
        # seen_at: 질문에 created_at이 없으면 묶음의 generated_at(다시 열기의 기준 시각)
        self.assertEqual(asked["answered"][fp], qmodel.asked_entry(q, SET_ID, AT, sha, seen_at=AT))
        self.assertEqual(qmodel.load_set(self.qd)["questions"], [])
        self.screen.assert_called_once_with(self.qd, self.d, self.pol, roots={"ws1": self.root})
        # 결과 dict에는 건수·ID·코드만(질문 문장·규칙 문장 없음)
        self.assertNotIn(QTEXT, json.dumps(res, ensure_ascii=False))
        self.assertNotIn("규칙 문장", json.dumps(res, ensure_ascii=False))

    def test_pattern_approve_and_text(self):
        """pattern_id가 그 질문의 후보면 승인하고 문장을 확정 문장으로 바꾼다. 나머지 패턴은 종결(기각)한다."""
        q = make_question(QTEXT, patterns=[self.fr_rm, self.fr_add])
        save_questions(self.qd, [q])
        write_answers(self.paths.inbox, [answer(q, rule("확정한 패턴 문장이다.", stage="label", target=LAYER,
                                                     pattern_id=self.fr_rm))])
        res = self.apply()
        self.assertEqual((res["patterns_approved"], res["patterns_closed"], res["rules"]), (1, 1, 0))
        r = self.rule_of(self.fr_rm)
        self.assertEqual((r["kind"], r["text"], r["edited_by"], r["edited_at"]),
                         ("REMOVE", "확정한 패턴 문장이다.", "screen", AT))
        self.assertEqual(self.doc()["rejected"], [self.fr_add])
        self.assertEqual(res["enabled_rules"], {"classify": 1, "label": 0})   # 단계는 패턴 kind가 정한다

    def test_approve_first_then_close(self):
        """한 FR이 두 질문에 걸리면: 앞의 질문은 묻지 않음, 뒤의 질문이 승인해도 승인이 먼저라 종결되지 않는다."""
        q1 = make_question(QTEXT + " 1", patterns=[self.fr_rm])
        q2 = make_question(QTEXT + " 2", patterns=[self.fr_rm])
        save_questions(self.qd, [q1, q2])
        write_answers(self.paths.inbox, [{"question_id": q1["question_id"], "action": "dismiss"},
                                         answer(q2, rule("승인할 패턴 문장이다.", pattern_id=self.fr_rm))])
        res = self.apply()
        self.assertEqual((res["dismissed"], res["answered"], res["patterns_approved"], res["patterns_closed"]),
                         (1, 1, 1, 0))
        self.assertIsNotNone(self.rule_of(self.fr_rm))
        self.assertEqual(self.doc()["rejected"], [])

    def test_already_approved_pattern(self):
        """이미 승인된 FR은 종결하지 않는다. pattern_id가 이미 승인분이면 문장만 바꾼다."""
        lr.decide(self.d, "approve", self.cfg, ids=[self.fr_add, self.fr_ans], path=self.rules)
        q1 = make_question(QTEXT + " 1", patterns=[self.fr_add])
        q2 = make_question(QTEXT + " 2", patterns=[self.fr_ans])
        save_questions(self.qd, [q1, q2])
        write_answers(self.paths.inbox, [answer(q1, rule("수동 규칙만 확정한다.")),
                                         answer(q2, rule("이미 승인된 패턴의 새 문장이다.", pattern_id=self.fr_ans))])
        res = self.apply()
        self.assertEqual((res["patterns_approved"], res["patterns_closed"], res["rules"]), (0, 0, 1))
        self.assertEqual(self.doc()["rejected"], [])
        self.assertIsNotNone(self.rule_of(self.fr_add))
        self.assertEqual(self.rule_of(self.fr_ans)["text"], "이미 승인된 패턴의 새 문장이다.")

    def test_pattern_gone_becomes_manual(self):
        """pattern_id가 지금 후보도 승인분도 아니거나 그 질문의 패턴이 아니면 MANUAL 규칙으로 넣고 PATTERN_GONE."""
        gone = "FR-0000000000"
        q1 = make_question(QTEXT + " 1", patterns=[gone])
        q2 = make_question(QTEXT + " 2")
        save_questions(self.qd, [q1, q2])
        write_answers(self.paths.inbox, [answer(q1, rule("사라진 패턴의 문장이다.", pattern_id=gone)),
                                         answer(q2, rule("남의 패턴 문장이다.", pattern_id=self.fr_rm))])
        res = self.apply()
        self.assertEqual((res["rules"], res["patterns_approved"], res["notes"]), (2, 0, ["PATTERN_GONE"]))
        kinds = {r["text"]: r["kind"] for r in self.doc()["rules"]}
        self.assertEqual(kinds, {"사라진 패턴의 문장이다.": "MANUAL", "남의 패턴 문장이다.": "MANUAL"})
        self.assertIsNone(self.rule_of(self.fr_rm))
        self.assertEqual(self.doc()["rejected"], [])   # 장부에 없는 FR은 종결할 것이 없다

    def test_rejected_or_low_pattern_not_revived(self):
        """기각한 FR(승인 → 승인 취소)과 후보 기준 아래 FR은 pattern_id 초안으로 되살리지 않고 MANUAL로 넣는다."""
        lr.decide(self.d, "approve", self.cfg, ids=[self.fr_rm], path=self.rules)
        lr.decide(self.d, "reject", self.cfg, ids=[self.fr_rm], path=self.rules)
        q1 = make_question(QTEXT + " 1", patterns=[self.fr_rm])
        q2 = make_question(QTEXT + " 2", patterns=[self.fr_low])
        save_questions(self.qd, [q1, q2])
        write_answers(self.paths.inbox, [answer(q1, rule("기각된 패턴의 문장이다.", pattern_id=self.fr_rm)),
                                         answer(q2, rule("기준 아래 패턴의 문장이다.", pattern_id=self.fr_low))])
        res = self.apply()
        self.assertEqual((res["patterns_approved"], res["rules"], res["notes"]), (0, 2, ["PATTERN_GONE"]))
        doc = self.doc()
        self.assertIsNone(self.rule_of(self.fr_rm))
        self.assertIsNone(self.rule_of(self.fr_low))
        self.assertIn(self.fr_rm, doc["rejected"])
        self.assertEqual({r["kind"] for r in doc["rules"]}, {"MANUAL"})

    def test_same_text_other_stage(self):
        """문장이 같아도 단계·대상이 다르면 다른 MANUAL 규칙이다. 같은 규칙을 다시 확정하면 그대로 둔다(꺼져 있어도)."""
        q = make_question(QTEXT)
        save_questions(self.qd, [q])
        write_answers(self.paths.inbox, [answer(q, rule("같은 문장이다."), rule("같은 문장이다.", stage="label"),
                                              rule("같은 문장이다."))])
        res = self.apply()
        self.assertEqual((res["rules"], res["enabled_rules"]), (2, {"classify": 1, "label": 1}))
        doc = self.doc()
        doc["rules"][0]["enabled"] = False
        lr.save_rules(doc, self.rules)
        q["reopened"] = True
        save_questions(self.qd, [q])
        write_answers(self.paths.inbox, [answer(q, rule("같은 문장이다."), rule("같은 문장이다.", stage="label"))],
                      reviewer="다른 검수자")
        res = self.apply()
        self.assertEqual((res["answered"], res["rules"]), (1, 0))
        self.assertEqual(self.doc(), doc)

    def test_reopened_question_same_answers_file(self):
        """다시 열린 질문에 그 질문을 닫았던 답 파일을 또 주면 not_open(새 패턴도 종결하지 않음). 새 답 파일이면 반영."""
        q = make_question(QTEXT, topic={"type": "axis", "axis": LAYER}, patterns=[self.fr_rm])
        save_questions(self.qd, [q])
        path = write_answers(self.paths.inbox, [answer(q, rule("처음 답한 규칙이다."))])
        self.assertEqual(self.apply()["patterns_closed"], 1)
        entry = qmodel.load_asked(self.qd)["answered"][q["fingerprint"]]
        self.assertTrue(entry["answers_sha"])
        reopened = dict(q, patterns=[self.fr_rm, self.fr_add], reopened=True)
        save_questions(self.qd, [reopened])
        before = snapshot(self.qd, self.rules)
        res = self.apply(answers_path=path)
        self.assertEqual((res["not_open"], res["answered"], res["patterns_closed"]), ([q["question_id"]], 0, 0))
        self.assertEqual(snapshot(self.qd, self.rules), before)
        self.assertNotIn(self.fr_add, self.doc()["rejected"])
        write_answers(self.paths.inbox, [answer(q, rule("다시 답한 규칙이다."))], name="engr_answers_new.json")
        res = self.apply(answers_path=os.path.join(self.paths.inbox, "engr_answers_new.json"))
        self.assertEqual((res["answered"], res["rules"], res["patterns_closed"]), (1, 1, 1))
        self.assertIn(self.fr_add, self.doc()["rejected"])

    def test_reopened_question_needs_current_set_answers(self):
        """다시 열린 질문은 지금 묶음에서 저장한 답 파일만 받는다(내용이 조금 다른 옛 묶음의 답 파일도 not_open)."""
        q = make_question(QTEXT, topic={"type": "axis", "axis": LAYER}, patterns=[self.fr_rm])
        save_questions(self.qd, [q])
        write_answers(self.paths.inbox, [answer(q, rule("처음 답한 규칙이다."))])
        self.assertEqual(self.apply()["answered"], 1)
        new_set = "QS-20261007T010203-cd34"
        save_questions(self.qd, [dict(q, patterns=[self.fr_rm, self.fr_add], reopened=True)], set_id=new_set)
        # 옛 묶음 화면에서 다시 저장한 파일(검토자 칸이 달라 해시는 다르다)
        stale = write_answers(self.paths.inbox, [answer(q, rule("처음 답한 규칙이다."))], reviewer="다른 사람",
                              name="engr_answers_stale.json")
        before = snapshot(self.qd, self.rules)
        res = self.apply(answers_path=stale)
        self.assertEqual((res["not_open"], res["answered"]), ([q["question_id"]], 0))
        self.assertEqual(snapshot(self.qd, self.rules), before)
        self.assertNotIn(self.fr_add, self.doc()["rejected"])
        fresh = write_answers(self.paths.inbox, [answer(q, rule("새로 답한 규칙이다."))], set_id=new_set)
        self.assertEqual(self.apply(answers_path=fresh)["answered"], 1)

    def test_rejected_example_not_revived(self):
        """사람이 기각한 사례는 답에 딸려 와도 승인하지 않는다(EXAMPLE_REJECTED). 기각 목록은 그대로다."""
        q = make_question(QTEXT, examples=[self.ex1, self.ex2])
        save_questions(self.qd, [q])
        lr.save_rules(dict(lr.empty_rules(), rejected_examples=[self.ex1]), self.rules)
        write_answers(self.paths.inbox, [answer(q, rule("규칙 문장이다."),
                                                {"type": "example", "example_id": self.ex1},
                                                {"type": "example", "example_id": self.ex2})])
        res = self.apply()
        self.assertEqual((res["answered"], res["examples"]), (1, 1))
        self.assertIn("EXAMPLE_REJECTED", res["notes"])
        self.assertEqual([e["example_id"] for e in self.doc()["examples"]], [self.ex2])
        self.assertEqual(self.doc()["rejected_examples"], [self.ex1])

    # ---- taxonomy·사례 ------------------------------------------------------

    def test_make_applier_for_question_server(self):
        """질문 서버가 저장 직후 부르는 반영 콜러블(사용자 결정, 2026-10-06): 반영 줄과 건수·ID·코드만 돌려주고,
        taxonomy 제안이 새로 생긴 때만 수정 보드를 다시 만든다. 질문·답 문장은 결과에 없다."""
        from domain_engrbot import questions

        q1 = make_question(QTEXT + " 1", goal="taxonomy")
        q2 = make_question(QTEXT + " 2")
        save_questions(self.qd, [q1, q2])
        path = write_answers(self.paths.inbox, [answer(q1, tax("synonym", alias="엠투", canonical="M2", memo="메모")),
                                                answer(q2, rule("규칙 문장이다."))])
        board = {"code": 0, "lines": ["[taxonomy-board] 항목 1 (미반영 1)", "[taxonomy-board] 화면: x.html"]}
        with mock.patch.object(lr, "RULES_PATH", self.rules), \
                mock.patch.object(questions, "refresh_board", return_value=board) as rb:
            run = questions.make_applier(self.paths, self.pol, self.qd)
            out = run(path)
            self.assertEqual(rb.call_count, 1)
            r = out["result"]
            self.assertEqual((r["answered"], r["rules"], r["taxonomy"], r["remaining"]), (2, 1, 1, 0))
            self.assertTrue(out["lines"][0].startswith("[questions] 반영: 답 2(규칙 1 · taxonomy 제안 1 · 사례 0)"))
            self.assertEqual(out["lines"][-2:], board["lines"])
            self.assertEqual(out["board"], board["lines"][0])
            self.assertNotIn(QTEXT, json.dumps(out, ensure_ascii=False))
            self.assertEqual(len(self.doc()["rules"]), 1)   # 승인 파일은 RULES_PATH(여기서는 임시 경로)에 쓴다
            # 같은 파일을 다시 반영하면 모두 not_open이고, 새 taxonomy 제안이 없으니 보드는 다시 만들지 않는다
            again = run(path)
            self.assertEqual(rb.call_count, 1)
            self.assertEqual((again["result"]["answered"], again["board"]), (0, None))
            self.assertEqual(sorted(again["result"]["not_open"]), sorted([q1["question_id"], q2["question_id"]]))
        with mock.patch.object(lr, "RULES_PATH", self.rules):
            with self.assertRaises(answers.AnswersError) as cm:
                run(os.path.join(self.out, "missing.json"))
        self.assertEqual(cm.exception.reason_code, "ANSWERS_NOT_FOUND")

    def test_taxonomy_proposals(self):
        """taxonomy 초안 → taxonomy_proposals.jsonl 행(4.4절). 같은 제안(proposal_id)은 두 번 쓰지 않는다."""
        d1 = tax("value_def", axis=LAYER, value="M2", definition="M2 정의 문장", include="포함 예", memo="메모")
        d2 = tax("synonym", alias="엠투", canonical="M2", memo="동의어 메모")
        q1 = make_question(QTEXT + " 1", goal="taxonomy")
        q2 = make_question(QTEXT + " 2", goal="taxonomy")
        save_questions(self.qd, [q1, q2])
        write_answers(self.paths.inbox, [answer(q1, d1, d2), answer(q2, dict(d1, origin="llm"))])
        res = self.apply()
        self.assertEqual((res["taxonomy"], res["answered"], res["rules"]), (2, 2, 0))
        rows = io.read_own_jsonl(self.qfile(qmodel.PROPOSALS))
        self.assertEqual([r["kind"] for r in rows], ["value_def", "synonym"])
        norm = qmodel.normalize_draft(d1)
        self.assertEqual(rows[0]["proposal_id"], qmodel.proposal_id(norm))
        self.assertEqual((rows[0]["set_id"], rows[0]["question_id"], rows[0]["at"], rows[0]["origin"]),
                         (SET_ID, q1["question_id"], AT, "edited"))
        self.assertEqual((rows[0]["axis"], rows[0]["value"], rows[0]["definition"], rows[0]["include"]),
                         (LAYER, "M2", "M2 정의 문장", "포함 예"))
        # 다음 묶음에서 같은 제안이 다시 확정돼도 행을 더하지 않는다
        q3 = make_question(QTEXT + " 3", goal="taxonomy")
        save_questions(self.qd, [q3])
        write_answers(self.paths.inbox, [answer(q3, d2)])
        self.assertEqual(self.apply()["taxonomy"], 0)
        self.assertEqual(len(io.read_own_jsonl(self.qfile(qmodel.PROPOSALS))), 2)
        self.assertFalse(os.path.exists(self.rules))   # taxonomy만 확정하면 승인 파일은 그대로다

    def test_example_approve(self):
        """사례 초안은 그 질문의 사례 후보일 때만 승인한다. 다른 사례 ID는 틀린 초안이다.
        사례만 확정한 답은 확정이 아니다(rule·taxonomy 초안이 1개 이상 필요, NO_CONFIRMED_DRAFT)."""
        q = make_question(QTEXT, examples=[self.ex1])
        save_questions(self.qd, [q])
        ex1, ex2 = {"type": "example", "example_id": self.ex1}, {"type": "example", "example_id": self.ex2}
        write_answers(self.paths.inbox, [answer(q, ex1)])
        res = self.apply()
        self.assertEqual((res["answered"], res["examples"], res["remaining"]), (0, 0, 1))
        self.assertEqual(res["invalid"], [{"question_id": q["question_id"], "code": "NO_CONFIRMED_DRAFT"}])
        self.assertFalse(os.path.exists(self.rules))
        write_answers(self.paths.inbox, [answer(q, ex1, ex2, tax("new_axis", name="새축"))])
        res = self.apply()
        self.assertEqual((res["examples"], res["answered"]), (1, 1))
        self.assertEqual(res["invalid"], [{"question_id": q["question_id"], "code": "EXAMPLE_NOT_IN_QUESTION"}])
        self.assertEqual([e["example_id"] for e in self.doc()["examples"]], [self.ex1])
        self.assertTrue(lr.valid_example(self.doc()["examples"][0]))

    # ---- 묻지 않음·건너뜀·틀린 초안 --------------------------------------------

    def test_dismiss_and_skip(self):
        q1 = make_question(QTEXT + " 1", patterns=[self.fr_rm])
        q2 = make_question(QTEXT + " 2", patterns=[self.fr_add])
        save_questions(self.qd, [q1, q2])
        write_answers(self.paths.inbox, [{"question_id": q1["question_id"], "action": "dismiss"},
                                         {"question_id": q2["question_id"], "action": "skip"}])
        res = self.apply()
        self.assertEqual((res["dismissed"], res["skipped"], res["patterns_closed"], res["remaining"]), (1, 1, 1, 1))
        self.assertEqual(self.doc()["rejected"], [self.fr_rm])
        asked = qmodel.load_asked(self.qd)
        self.assertEqual((list(asked["dismissed"]), asked["answered"]), ([q1["fingerprint"]], {}))
        self.assertEqual([x["question_id"] for x in qmodel.load_set(self.qd)["questions"]], [q2["question_id"]])
        hist = io.read_own_jsonl(self.qfile(qmodel.ANSWERS_LOG))
        self.assertEqual([(h["question_id"], h["action"], h["confirmed"]) for h in hist],
                         [(q1["question_id"], "dismiss", [])])

    def test_no_confirmed_draft(self):
        """유효한 확정 초안이 없는 답은 NO_CONFIRMED_DRAFT로 열린 채 둔다(아무것도 쓰지 않는다)."""
        q1 = make_question(QTEXT + " 1", patterns=[self.fr_rm])
        q2 = make_question(QTEXT + " 2")
        save_questions(self.qd, [q1, q2])
        write_answers(self.paths.inbox, [answer(q1), answer(q2, rule("{{chunk_text}} 넣은 문장"))])
        before = snapshot(self.qd)
        res = self.apply()
        self.assertEqual(res["answered"], 0)
        self.assertEqual(res["invalid"], [{"question_id": q1["question_id"], "code": "NO_CONFIRMED_DRAFT"},
                                          {"question_id": q2["question_id"], "code": "DRAFT_TEXT_INVALID"},
                                          {"question_id": q2["question_id"], "code": "NO_CONFIRMED_DRAFT"}])
        self.assertEqual((res["remaining"], res["patterns_closed"]), (2, 0))
        self.assertEqual(snapshot(self.qd), before)
        self.assertFalse(os.path.exists(self.rules))
        self.screen.assert_not_called()

    def test_bad_draft_only_is_invalid(self):
        """틀린 초안만 invalid에 넣고 나머지 초안은 반영한다."""
        q = make_question(QTEXT)
        save_questions(self.qd, [q])
        write_answers(self.paths.inbox, [answer(q, rule("가" * (qmodel.RULE_TEXT_MAX + 1)), {"type": "nope"},
                                              tax("value_add", axis=LAYER), rule("살아남는 문장이다."))])
        res = self.apply()
        self.assertEqual([x["code"] for x in res["invalid"]],
                         ["DRAFT_TEXT_INVALID", "DRAFT_TYPE_INVALID", "DRAFT_REQUIRED_MISSING"])
        self.assertEqual((res["answered"], res["rules"]), (1, 1))
        self.assertEqual([r["text"] for r in self.doc()["rules"]], ["살아남는 문장이다."])

    # ---- 열림·멱등·이력 --------------------------------------------------------

    def test_not_open_and_idempotent(self):
        """두 번째 apply는 이미 닫힌 질문이라 not_open이 되고 아무 파일도 바꾸지 않는다."""
        q1 = make_question(QTEXT + " 1", patterns=[self.fr_rm, self.fr_add])
        q2 = make_question(QTEXT + " 2", goal="taxonomy")
        ghost = make_question("묶음에 없는 질문")
        save_questions(self.qd, [q1, q2])
        write_answers(self.paths.inbox, [answer(q1, rule("문장이다.", pattern_id=self.fr_rm)),
                                         answer(q2, tax("axis_def", axis=LAYER, definition="축 정의")),
                                         answer(ghost, rule("열리지 않은 질문의 문장이다."))])
        res = self.apply()
        self.assertEqual((res["answered"], res["not_open"]), (2, [ghost["question_id"]]))
        before = snapshot(self.qd, self.rules, self.d)
        again = self.apply(now="2026-10-07T00:00:00Z")
        self.assertEqual(sorted(again["not_open"]), sorted([q1["question_id"], q2["question_id"], ghost["question_id"]]))
        for k in ("answered", "dismissed", "skipped", "rules", "patterns_approved", "patterns_closed", "taxonomy",
                  "examples", "remaining"):
            self.assertEqual(again[k], 0, k)
        self.assertEqual(again["enabled_rules"], res["enabled_rules"])
        self.assertEqual(snapshot(self.qd, self.rules, self.d), before)
        self.assertEqual(len(io.read_own_jsonl(self.qfile(qmodel.ANSWERS_LOG))), 2)
        self.assertEqual(self.screen.call_count, 1)

    def test_other_set_id_still_applies(self):
        """답 파일의 set_id가 지금 묶음과 달라도 열려 있는 질문이면 반영한다(ANSWERS_OTHER_SET 없음)."""
        q = make_question(QTEXT)
        save_questions(self.qd, [q])
        write_answers(self.paths.inbox, [answer(q, rule("다른 묶음의 답이다."))], set_id=OTHER_SET)
        res = self.apply()
        self.assertEqual(res["answered"], 1)
        hist = io.read_own_jsonl(self.qfile(qmodel.ANSWERS_LOG))[0]
        self.assertEqual((hist["set_id"], hist["answers_set_id"]), (SET_ID, OTHER_SET))

    def test_rules_history(self):
        """승인 파일을 바꾸기 직전 이전 문서를 rules_history.jsonl에 한 줄 남긴다. 바뀌지 않으면 남기지 않는다."""
        lr.decide(self.d, "approve", self.cfg, ids=[self.fr_ans], path=self.rules)
        old = self.doc()
        q1 = make_question(QTEXT + " 1")
        q2 = make_question(QTEXT + " 2", goal="taxonomy")
        save_questions(self.qd, [q1, q2])
        write_answers(self.paths.inbox, [answer(q1, rule("새 규칙 문장이다."))])
        self.apply()
        hist = io.read_own_jsonl(self.qfile(qmodel.RULES_HISTORY))
        self.assertEqual([(h["at"], h["set_id"]) for h in hist], [(AT, SET_ID)])
        self.assertEqual(hist[0]["doc"], json.loads(io.dumps(old)))
        write_answers(self.paths.inbox, [answer(q2, tax("new_axis", name="새축"))])
        self.apply()
        self.assertEqual(len(io.read_own_jsonl(self.qfile(qmodel.RULES_HISTORY))), 1)

    def test_latest_answers_file(self):
        """--answers가 없으면 inbox의 engr_answers_*.json 중 수정 시각이 가장 늦은 것을 쓴다."""
        q = make_question(QTEXT)
        save_questions(self.qd, [q])
        old = write_answers(self.paths.inbox, [{"question_id": q["question_id"], "action": "skip"}], set_id=OTHER_SET)
        new = write_answers(self.paths.inbox, [answer(q, rule("늦은 파일의 답이다."))])
        os.utime(old, (2000000000, 2000000000))
        os.utime(new, (2000000100, 2000000100))
        self.assertEqual(answers.latest_answers(self.paths.inbox), new)
        self.assertEqual(self.apply()["answered"], 1)
        # 수정 시각이 바뀌면 고르는 파일도 바뀐다
        os.utime(old, (2000000200, 2000000200))
        self.assertEqual(answers.latest_answers(self.paths.inbox), old)

    # ---- 오류·상한·예외 --------------------------------------------------------

    def test_error_codes(self):
        q = make_question(QTEXT)
        save_questions(self.qd, [q])
        self.refused("ANSWERS_NOT_FOUND")
        self.refused("ANSWERS_NOT_FOUND", answers_path=os.path.join(self.out, "none.json"))
        big = os.path.join(self.out, "big.json")
        with open(big, "w", encoding="utf-8") as f:
            f.write(" " * (qmodel.MAX_ANSWER_BYTES + 1))
        with mock.patch.object(answers.io, "read_json_input", side_effect=AssertionError("읽으면 안 된다")):
            self.refused("ANSWERS_TOO_LARGE", answers_path=big)
        bad = os.path.join(self.out, "bad.json")
        with open(bad, "w", encoding="utf-8") as f:
            f.write("{not json")
        self.refused("ANSWERS_JSON_INVALID", answers_path=bad)
        qid = q["question_id"]
        for doc in ({"kind": "x", "answers": []}, {"kind": qmodel.ANSWERS_KIND, "answers": {}}, [],
                    {"kind": qmodel.ANSWERS_KIND, "answers": [{"question_id": qid, "action": "delete"}]},
                    {"kind": qmodel.ANSWERS_KIND, "answers": [{"question_id": "EQ-x", "action": "skip"}]},
                    {"kind": qmodel.ANSWERS_KIND, "answers": [{"question_id": qid, "action": "answer",
                                                               "confirmed": "rule"}]}):
            with open(bad, "w", encoding="utf-8") as f:
                json.dump(doc, f)
            self.refused("ANSWERS_FORMAT_INVALID", answers_path=bad)
        dup = write_answers(self.out, [{"question_id": qid, "action": "skip"}, {"question_id": qid, "action": "dismiss"}])
        self.refused("ANSWERS_DUPLICATE_ID", answers_path=dup)
        ok = write_answers(self.out, [answer(q, rule("문장이다."))], name="ok.json")
        with open(self.qfile(qmodel.ASKED), "w", encoding="utf-8") as f:
            f.write("{broken")
        self.refused("ASKED_INVALID", answers_path=ok)
        os.remove(self.qfile(qmodel.ASKED))
        with open(self.qfile(qmodel.PROPOSALS), "w", encoding="utf-8") as f:
            f.write("{broken\n")
        self.refused("PROPOSALS_INVALID", answers_path=ok)
        os.remove(self.qfile(qmodel.PROPOSALS))
        with open(self.rules, "w", encoding="utf-8") as f:
            f.write("{broken")
        with self.assertRaises(answers.AnswersError) as cm:
            self.apply(answers_path=ok)
        self.assertEqual(cm.exception.reason_code, "RULES_JSON_INVALID")
        os.remove(self.rules)
        with open(self.qfile(qmodel.QUESTIONS), "w", encoding="utf-8") as f:
            f.write("{broken")
        self.refused("QUESTIONS_INVALID", answers_path=ok)
        os.remove(self.qfile(qmodel.QUESTIONS))
        self.refused("QUESTIONS_NOT_FOUND", answers_path=ok)

    def test_screen_failure_is_note(self):
        """저장 뒤 화면 다시 만들기가 실패해도 반영 결과는 정상으로 돌려주고 notes에 SCREEN_REBUILD_FAILED만 남긴다."""
        q = make_question(QTEXT)
        save_questions(self.qd, [q])
        write_answers(self.paths.inbox, [answer(q, rule("화면 실패와 무관한 규칙이다."))])
        self.screen.side_effect = OSError("disk")
        res = self.apply()
        self.assertEqual((res["answered"], res["rules"], res["notes"]), (1, 1, ["SCREEN_REBUILD_FAILED"]))
        self.assertEqual(len(self.doc()["rules"]), 1)

    def test_read_failed(self):
        q = make_question(QTEXT)
        save_questions(self.qd, [q])
        write_answers(self.paths.inbox, [answer(q, rule("문장이다."))])
        with mock.patch.object(answers.io, "read_json_input", side_effect=PermissionError("locked")):
            self.refused("ANSWERS_READ_FAILED")

    def test_rules_over_cap(self):
        """켜진 유효 규칙이 단계별 상한(pipeline.json feedback.max_rules)을 넘으면 RULES_OVER_CAP. 못 읽으면 30."""
        q = make_question(QTEXT)
        save_questions(self.qd, [q])
        write_answers(self.paths.inbox, [answer(q, rule("첫째 규칙이다."), rule("둘째 규칙이다."))])
        with mock.patch.object(answers.labelbot_ws, "read_config", return_value={"feedback": {"max_rules": 1}}):
            res = self.apply()
        self.assertEqual((res["cap"], res["enabled_rules"], res["notes"]),
                         (1, {"classify": 2, "label": 0}, ["RULES_OVER_CAP"]))
        with mock.patch.object(answers.labelbot_ws, "read_config", side_effect=model.BundleError("ADAPTER_CONFIG_INVALID")):
            self.assertEqual(answers._cap(self.root), answers.DEFAULT_CAP)
        # 꺼진 규칙·형식이 틀린 규칙은 세지 않는다
        doc = self.doc()
        doc["rules"][0]["enabled"] = False
        doc["rules"].append({"rule_id": "QR-bad", "kind": "MANUAL", "text": ""})
        self.assertEqual(answers.enabled_rules(doc), {"classify": 1, "label": 0})

    def test_exception_before_save_changes_nothing(self):
        """승인 파일 저장 전에 예외가 나면 승인 파일·질문 폴더의 어떤 파일도 바뀌지 않고 잠금이 풀린다."""
        lr.decide(self.d, "approve", self.cfg, ids=[self.fr_ans], path=self.rules)
        q = make_question(QTEXT, patterns=[self.fr_rm], examples=[self.ex1])
        save_questions(self.qd, [q])
        write_answers(self.paths.inbox, [answer(q, rule("문장이다."), {"type": "example", "example_id": self.ex1},
                                              tax("new_axis", name="새축"))])
        before = snapshot(self.qd, self.rules)
        with mock.patch.object(answers.lr, "apply_decision", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.apply()
        self.assertEqual(snapshot(self.qd, self.rules), before)
        with mock.patch.object(answers.lr, "save_rules", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                self.apply()
        after = snapshot(self.qd, self.rules)
        # 저장 직전에 남긴 이전 본(rules_history) 한 줄 밖에는 그대로다
        self.assertEqual(json.loads(after.pop(self.qfile(qmodel.RULES_HISTORY)))["doc"], json.loads(io.dumps(self.doc())))
        self.assertEqual(after, before)
        self.assertFalse(os.path.exists(os.path.join(self.d, ledger.LOCK_NAME)))
        self.screen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
