"""QM7 골든셋 경로와 QM8 규칙 제안·피드백 묶음."""
import hashlib
import json
import os
import sqlite3
import unittest

from engrbot import feedback, golden, io, proposals, queue, runner, screen
from engrbot.tests import reviewfix as rf

AXIS = "불량 모드"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def tree_hash(root, skip=()):
    out = {}
    for d, dirs, files in os.walk(root):
        rel = os.path.relpath(d, root)
        if rel.split(os.sep)[0] in skip:
            dirs[:] = []
            continue
        for fn in files:
            p = os.path.join(d, fn)
            out[os.path.relpath(p, root)] = hashlib.sha256(read_bytes(p)).hexdigest()
    return out


def bot(res, rid, field):
    rec = [r for r in res.bundle.records if r["record_id"] == rid][0]
    return golden.bot_value(rec, field)


class GoldenTest(unittest.TestCase):
    def setUp(self):
        self.res, self.fx, self.roles = rf.scenario()
        self.res.queue, self.res.rework = queue.write(self.res)

    def _doc(self):
        a, b, c = self.roles["review"]
        fa = "axis:%s" % rf._value_axis([r for r in self.res.bundle.records if r["record_id"] == a][0])
        fb = "axis:%s" % rf._value_axis([r for r in self.res.bundle.records if r["record_id"] == b][0])
        fc = "axis:%s" % rf._value_axis([r for r in self.res.bundle.records if r["record_id"] == c][0])
        va, qa = bot(self.res, a, fa)
        decisions = [
            {"record_id": a, "field": fa, "decision": "confirm", "value": va, "quote": qa},
            {"record_id": b, "field": fb, "decision": "correct", "value": ["unknown"], "quote": None},
            {"record_id": c, "field": fc, "decision": "cannot_judge", "value": None, "quote": None},
        ]
        return rf.decisions_doc(self.res.qa_run_id, decisions), (a, fa, va, qa), (b, fb), (c, fc)

    def test_add_from_screen_format_decisions(self):
        doc, (a, fa, va, qa), (b, fb), (c, _fc) = self._doc()
        rf.put_inbox(self.res, doc)
        out = golden.add(self.res)
        self.assertEqual(out["added"], 2)
        rows = {g["record_id"]: g for g in io.read_own_jsonl(self.res.paths.golden)}
        self.assertEqual(set(rows), {a, b})
        self.assertNotIn(c, rows)  # cannot_judge는 넣지 않는다
        key = fa.split(":", 1)[1]
        self.assertEqual(rows[a]["labels"]["axes"][key], va)
        self.assertEqual(rows[a]["evidence"][fa], qa)
        self.assertEqual(rows[b]["labels"]["axes"][fb.split(":", 1)[1]], ["unknown"])
        g = rows[a]
        unit = self.res.bundle.units[a]
        self.assertEqual(g["text_hash"], unit["text_hash"])
        self.assertEqual(g["source"], "review:%s" % self.res.qa_run_id)
        self.assertEqual(g["taxonomy_version"], self.res.bundle.taxonomy["version"])
        self.assertEqual(len(g["golden_id"]), 32)

    def test_idempotent_twice_and_duplicate_file(self):
        doc, *_ = self._doc()
        rf.put_inbox(self.res, doc)
        golden.add(self.res)
        first = read_bytes(self.res.paths.golden)
        out = golden.add(self.res)
        self.assertEqual(out["added"], 0)
        self.assertEqual(read_bytes(self.res.paths.golden), first)
        rf.put_inbox(self.res, doc, "qa_decisions_copy.json")
        golden.add(self.res)
        self.assertEqual(read_bytes(self.res.paths.golden), first)

    def test_unknown_qa_run_is_rejected(self):
        doc, *_ = self._doc()
        doc["qa_run_id"] = "QA-20990101T000000-dead"
        rf.put_inbox(self.res, doc)
        out = golden.add(self.res)
        self.assertEqual((out["added"], out["rejected"]), (0, 1))
        self.assertEqual(io.read_own_jsonl(self.res.paths.golden), [])
        self.assertIn("QA_RUN_NOT_FOUND", rf.read_log(self.res))

    def test_other_existing_run_is_skipped(self):
        other = "QA-20261004T999999-beef"
        self.res.paths.run_dir(other, create=True)
        doc, *_ = self._doc()
        doc["qa_run_id"] = other
        rf.put_inbox(self.res, doc)
        out = golden.add(self.res)
        self.assertEqual((out["added"], out["rejected"]), (0, 0))
        self.assertIn("DECISIONS_OTHER_RUN", rf.read_log(self.res))

    def test_text_changed_is_skipped_with_reason(self):
        doc, (a, *_r), (b, _fb), _c = self._doc()
        self.res.bundle.units[a]["text_hash"] = "0" * 64  # 검수 실행 뒤 본문이 바뀌었다
        rf.put_inbox(self.res, doc)
        out = golden.add(self.res)
        rows = {g["record_id"] for g in io.read_own_jsonl(self.res.paths.golden)}
        self.assertEqual(rows, {b})
        self.assertGreaterEqual(out["skipped"], 1)
        log = rf.read_log(self.res)
        self.assertIn("%s\tTEXT_CHANGED" % a, log)
        self.assertNotIn(rf.MISSING_QUOTE, log)

    def test_corrections_table_values_are_added(self):
        rid = self.roles["review"][2]
        unit = self.res.bundle.units[rid]
        self.res.bundle.meta["corrections"] = {rid: [
            {"target_kind": "axis", "target_key": AXIS, "human_value": json.dumps(["unknown"]),
             "review_status": "사람이 교정", "text_hash": unit["text_hash"]},
            {"target_kind": "answer", "target_key": "Q-COM-001", "human_value": json.dumps("판단 불가"),
             "review_status": "사람이 교정", "text_hash": unit["text_hash"]},
        ]}
        out = golden.add(self.res)  # 결정 파일 없이도 corrections 표의 사람 값을 넣는다
        self.assertEqual(out["added"], 1)
        rows = {g["record_id"]: g for g in io.read_own_jsonl(self.res.paths.golden)}
        self.assertEqual(rows[rid]["labels"]["axes"], {AXIS: ["unknown"]})
        self.assertEqual(rows[rid]["labels"]["answers"], {})  # 판단 불가는 넣지 않는다

    def test_golden_is_evaluable_via_to_bundle(self):
        doc, (a, *_r), (b, _fb), _c = self._doc()
        rf.put_inbox(self.res, doc)
        golden.add(self.res)
        rows = io.read_own_jsonl(self.res.paths.golden)
        stale = dict(rows[0], record_id=rows[0]["record_id"], text_hash="f" * 64, golden_id="x" * 32)
        b2 = golden.to_bundle(rows + [stale], self.res.bundle)
        self.assertEqual(sorted(r["record_id"] for r in b2.records), sorted([a, b]))
        for r in b2.records:
            self.assertTrue(r["human_reviewed"])
        rb = [r for r in b2.records if r["record_id"] == b][0]
        self.assertTrue(all(x["status"] in ("value", "na", "unknown") for x in rb["axes"].values()))
        out = runner.execute(b2, self.res.policy, self.res.schema, layers=rf.LAYERS)
        self.assertEqual(len(out.verdicts), 2)
        for v in out.verdicts:
            self.assertFalse([i for i in v["issues"] if i["layer"] in ("L2", "L3A")], v["issues"])

    def test_golden_has_no_file_names(self):
        doc, *_ = self._doc()
        rf.put_inbox(self.res, doc)
        golden.add(self.res)
        text = read_bytes(self.res.paths.golden).decode("utf-8")
        for name in self.res.bundle.meta["file_names"].values():
            self.assertNotIn(name, text)
        self.assertNotIn(self.res.paths.root, text)


class ProposalTest(unittest.TestCase):
    def flooded(self, policy_over=None, ratio=0.5):
        res, fx, roles = rf.scenario(policy_over=policy_over)
        cands = sorted(r["record_id"] for r in res.bundle.records
                       if (r["axes"].get(AXIS) or {}).get("status") in ("value", "unknown"))
        status = {r["record_id"]: (r["axes"].get(AXIS) or {}).get("status") for r in res.bundle.records}
        for rid in cands[:int(len(cands) * ratio) + 1]:
            if status[rid] == "value":
                rf.inject(res, rid, "L3_NOT_SUPPORTED", "axis:%s" % AXIS, "인용이 라벨을 지지하지 않는다.")
        return res, len(cands)

    def test_axis_definition_when_flooded(self):
        res, n = self.flooded()
        rows = proposals.write(res)
        axdef = [p for p in rows if p["kind"] == "AXIS_DEFINITION"]
        self.assertEqual([p["target"] for p in axdef], ["axis:%s" % AXIS])
        p = axdef[0]
        self.assertEqual(p["metric"]["n"], n)
        self.assertGreaterEqual(p["metric"]["value"], 0.3)
        self.assertTrue(p["examples"])
        self.assertIsNone(p["paste_row"])
        self.assertEqual(io.read_own_jsonl(res.path("proposals.jsonl")), rows)

    def test_axis_definition_respects_min_n(self):
        _res, n = self.flooded()
        res_hi, _ = self.flooded(policy_over={"feedback": {"min_n": n + 1}})
        self.assertFalse([p for p in proposals.compute(res_hi) if p["kind"] == "AXIS_DEFINITION"])
        res_eq, _ = self.flooded(policy_over={"feedback": {"min_n": n}})
        self.assertTrue([p for p in proposals.compute(res_eq) if p["kind"] == "AXIS_DEFINITION"])

    def test_no_axis_definition_without_signal(self):
        res, _fx, _roles = rf.scenario()
        self.assertFalse([p for p in proposals.compute(res) if p["kind"] == "AXIS_DEFINITION"])

    def test_other_kinds(self):
        res, _fx, roles = rf.scenario(policy_over={"feedback": {"format_rule_min_count": 3, "quote_issue_rate": 0.01}})
        res.metrics = {"terms": [{"term": "EMX", "df_u": 5, "df_all": 6, "lift": 3.0, "examples": roles["review"][:1]}],
                       "unused_streak": {AXIS: ["EM"]}}
        for rid in roles["review"]:
            rf.inject(res, rid, "L3_NOT_SUPPORTED", "answer:Q-COM-001")
        kinds = {p["kind"]: p for p in proposals.compute(res)}
        self.assertEqual(kinds["TERM"]["target"], "term:EMX")
        self.assertEqual(kinds["UNUSED_VALUE"]["subject"], {"axis": AXIS, "value": "EM"})
        self.assertEqual(kinds["FORMAT_RULE"]["target"], "date_iso")
        self.assertEqual(kinds["QUOTE_RULE"]["metric"]["count"], 2)
        self.assertNotIn("QUESTION_WORDING", kinds)  # 3건으로는 질문 이슈율 0.3에 못 미친다

    def test_question_wording_when_flooded(self):
        res, _fx, _roles = rf.scenario()
        qid = sorted({q for r in res.bundle.records for q in r["answers"]})[0]
        ox = sorted(r["record_id"] for r in res.bundle.records if (r["answers"].get(qid) or {}).get("answer") in ("O", "X"))
        for rid in ox[:len(ox) // 2]:
            rf.inject(res, rid, "L3_NOT_SUPPORTED", "answer:%s" % qid)
        qw = [p for p in proposals.compute(res) if p["kind"] == "QUESTION_WORDING"]
        self.assertEqual([(p["target"], p["metric"]["n"]) for p in qw], [("answer:%s" % qid, len(ox))])

    def test_ids_stable_and_rejected_not_reproposed(self):
        res1, _ = self.flooded()
        res2, _ = self.flooded()
        res2.qa_run_id = "QA-20261005T000000-0001"
        ids1 = [p["proposal_id"] for p in proposals.compute(res1)]
        self.assertEqual(ids1, [p["proposal_id"] for p in proposals.compute(res2)])
        res1.proposals = proposals.write(res1)
        pid = [p for p in res1.proposals if p["kind"] == "AXIS_DEFINITION"][0]["proposal_id"]
        rf.put_inbox(res1, rf.decisions_doc(res1.qa_run_id, props=[{"proposal_id": pid, "decision": "reject", "as": None, "note": ""}]))
        fb = feedback.build(res1)
        self.assertEqual(fb["rejected_proposals"], [pid])
        # 같은 작업 폴더의 다음 실행
        res3, _ = self.flooded()
        res3.paths, res3.run_dir = res1.paths, res1.paths.run_dir("QA-20261006T000000-0002", create=True)
        self.assertNotIn(pid, [p["proposal_id"] for p in proposals.write(res3)])
        feedback.build(res1)
        lines = io.read_own_jsonl(res1.paths.feedback_rejected)
        self.assertEqual([l["proposal_id"] for l in lines], [pid])  # 중복 없이 한 줄


class FeedbackTest(unittest.TestCase):
    def setUp(self):
        self.res, self.fx, self.roles = rf.scenario()
        self.res.metrics = {"terms": [
            {"term": "EMX", "df_u": 5, "df_all": 6, "lift": 3.0, "examples": self.roles["review"][:1]},
            {"term": "갈라짐", "df_u": 4, "df_all": 5, "lift": 2.0, "examples": self.roles["review"][1:2]},
            {"term": "보류어", "df_u": 4, "df_all": 5, "lift": 2.0, "examples": []},
            {"term": "기각어", "df_u": 4, "df_all": 5, "lift": 2.0, "examples": []},
        ]}
        self.res.queue, self.res.rework = queue.write(self.res)
        self.res.proposals = proposals.write(self.res)
        self.pid = {p["subject"]["term"]: p["proposal_id"] for p in self.res.proposals if p["kind"] == "TERM"}

    def field_of(self, rid):
        return "axis:%s" % rf._value_axis([r for r in self.res.bundle.records if r["record_id"] == rid][0])

    def full_doc(self, autofix=()):
        a, b, c = self.roles["review"]
        r1, r2 = self.roles["reject"]
        fa, fb_, fc = self.field_of(a), self.field_of(b), self.field_of(c)
        va, qa = bot(self.res, a, fa)
        return rf.decisions_doc(
            self.res.qa_run_id,
            decisions=[
                {"record_id": a, "field": fa, "decision": "confirm", "value": va, "quote": qa},
                {"record_id": b, "field": fb_, "decision": "correct", "value": ["unknown"], "quote": None},
                {"record_id": c, "field": fc, "decision": "cannot_judge", "value": None, "quote": None},
            ],
            rejects=[
                {"record_id": r1, "decision": "rework", "corrections": []},
                {"record_id": r2, "decision": "false_positive", "corrections": []},
            ],
            autofix=list(autofix),
            props=[
                {"proposal_id": self.pid["EMX"], "decision": "approve", "as": "synonym", "canonical": "EM", "note": ""},
                {"proposal_id": self.pid["갈라짐"], "decision": "approve", "as": "value", "axis": AXIS, "parent": "", "note": ""},
                {"proposal_id": self.pid["보류어"], "decision": "hold", "as": None, "note": ""},
                {"proposal_id": self.pid["기각어"], "decision": "reject", "as": None, "note": ""},
            ])

    def test_only_approved_items(self):
        rf.put_inbox(self.res, self.full_doc())
        fb = feedback.build(self.res)
        a, b, c = self.roles["review"]
        review_corr = [x for x in fb["corrections"] if x["source"] == "REVIEW"]
        self.assertEqual([(x["record_id"], x["value"]) for x in review_corr], [(b, ["unknown"])])
        self.assertNotIn(c, {x["record_id"] for x in fb["corrections"]})
        got = {p["proposal_id"] for p in fb["proposals"] if p["kind"] == "TERM"}
        self.assertEqual(got, {self.pid["EMX"], self.pid["갈라짐"]})
        self.assertEqual(fb["rejected_proposals"], [self.pid["기각어"]])
        self.assertNotIn(self.pid["보류어"], {p["proposal_id"] for p in fb["proposals"]})
        self.assertEqual(fb["decisions_sha256"], golden.decisions_sha256(self.full_doc()))
        self.assertTrue(os.path.isfile(self.res.path("feedback", "feedback.md")))

    def test_false_positive_and_rework(self):
        rf.put_inbox(self.res, self.full_doc())
        fb = feedback.build(self.res)
        r1, r2 = self.roles["reject"]
        self.assertEqual([r["record_id"] for r in fb["rework"]], [r1])
        self.assertEqual(fb["rework"][0]["issues"][0]["code"], "L3_SPAN_NOT_FOUND")
        self.assertTrue(fb["rework"][0]["fields"])
        self.assertEqual(fb["qa_false_positives"], [{"code": "L3_SPAN_NOT_FOUND", "records": 1}])
        qp = [p for p in fb["proposals"] if p["kind"] == "QA_POLICY"]
        self.assertEqual([(p["target"], p["examples"]) for p in qp], [("L3_SPAN_NOT_FOUND", [r2])])

    def test_reject_direct_correction(self):
        r1 = self.roles["reject"][0]
        f = self.field_of(r1)
        doc = rf.decisions_doc(self.res.qa_run_id, rejects=[
            {"record_id": r1, "decision": "correct", "corrections": [{"field": f, "value": ["unknown"], "quote": ""}]}])
        rf.put_inbox(self.res, doc)
        fb = feedback.build(self.res)
        self.assertEqual([(c["record_id"], c["field"], c["source"]) for c in fb["corrections"]], [(r1, f, "REJECT")])
        self.assertEqual(fb["rework"], [])

    def test_term_paste_rows(self):
        rf.put_inbox(self.res, self.full_doc())
        fb = feedback.build(self.res)
        with open(self.res.path("feedback", "feedback.md"), encoding="utf-8") as f:
            md = f.read()
        self.assertIn("EMX\tEM\t", md.splitlines())
        rows = [l for l in md.splitlines() if l.startswith(AXIS + "\t갈라짐")]
        self.assertEqual(len(rows), 1)
        cells = rows[0].split("\t")
        self.assertEqual(len(cells), len(feedback.TAXONOMY_COLUMNS))
        self.assertEqual(cells[:3], [AXIS, "갈라짐", ""])
        self.assertEqual(len("EMX\tEM\t".split("\t")), len(feedback.SYNONYM_COLUMNS))
        sheets = {p["proposal_id"]: p["sheet"] for p in fb["proposals"] if p["kind"] == "TERM"}
        self.assertEqual(sheets, {self.pid["EMX"]: "synonyms", self.pid["갈라짐"]: "taxonomy"})

    def test_autofix_rule_approval_and_except(self):
        case, date = self.roles["autofix_case"], self.roles["autofix_date"]
        fb = feedback.build(self.res)  # 결정 없음, 승인된 규칙 없음
        self.assertEqual([c for c in fb["corrections"] if c["source"] == "AUTO_FIX"], [])
        rf.put_inbox(self.res, rf.decisions_doc(self.res.qa_run_id, autofix=[
            {"rule": "date_iso", "decision": "approve", "except": [date[0]]},
            {"rule": "taxonomy_case", "decision": "reject", "except": []}]))
        fb = feedback.build(self.res)
        auto = [c for c in fb["corrections"] if c["source"] == "AUTO_FIX"]
        self.assertEqual(sorted(c["record_id"] for c in auto), sorted(date[1:]))
        self.assertTrue(all(c["rule"] == "date_iso" and c["value"].count("-") == 2 for c in auto))

    def test_autofix_policy_approved_rules_without_decision(self):
        res, _fx, roles = rf.scenario(policy_over={"autofix": {"approved_rules": ["taxonomy_case"]}})
        res.proposals = []
        fb = feedback.build(res)
        auto = [c for c in fb["corrections"] if c["source"] == "AUTO_FIX"]
        self.assertEqual(sorted(c["record_id"] for c in auto), sorted(roles["autofix_case"]))
        data = screen.data(res)
        groups = {g["rule"]: g["approved"] for g in data["autofix"]}
        self.assertEqual(groups, {"taxonomy_case": True, "date_iso": False})  # 화면에서 이미 승인된 규칙은 접는다

    def test_deterministic(self):
        rf.put_inbox(self.res, self.full_doc())
        feedback.build(self.res)
        a = read_bytes(self.res.path("feedback", "feedback.json"))
        m = read_bytes(self.res.path("feedback", "feedback.md"))
        feedback.build(self.res)
        self.assertEqual(read_bytes(self.res.path("feedback", "feedback.json")), a)
        self.assertEqual(read_bytes(self.res.path("feedback", "feedback.md")), m)
        self.assertEqual(len(io.read_own_jsonl(self.res.paths.feedback_rejected)), 1)

    def test_no_file_names_or_paths(self):
        rf.put_inbox(self.res, self.full_doc())
        feedback.build(self.res)
        for fn in ("feedback.json", "feedback.md"):
            text = read_bytes(self.res.path("feedback", fn)).decode("utf-8")
            for name in self.res.bundle.meta["file_names"].values():
                self.assertNotIn(name, text)
            self.assertNotIn(self.res.paths.root, text)
            self.assertNotIn(self.res.paths.root.replace("\\", "/"), text)
            for banned in (".pptx", ".docx", ".xlsx", "inbox"):
                self.assertNotIn(banned, text)

    def test_labelbot_inputs_untouched(self):
        root = self.res.paths.root
        db = os.path.join(root, "work.sqlite")
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE labels(id INTEGER)")
        con.commit()
        con.close()
        before_ws = tree_hash(root, skip=("qa", "logs", "inputs"))
        before_prompts = tree_hash(os.path.join(REPO_ROOT, "prompts"))
        rf.put_inbox(self.res, self.full_doc())
        queue.write(self.res)
        proposals.write(self.res)
        screen.build(self.res, pass_sample=5)
        golden.add(self.res)
        feedback.build(self.res)
        self.assertEqual(tree_hash(root, skip=("qa", "logs", "inputs")), before_ws)
        self.assertEqual(tree_hash(os.path.join(REPO_ROOT, "prompts")), before_prompts)
        self.assertFalse(os.path.exists(os.path.join(root, "taxonomy.xlsx")))
        for d, _dirs, files in os.walk(root):
            for fn in files:
                self.assertTrue(fn.lower().endswith(io.ALLOWED_EXT), fn)



def tearDownModule():
    rf.cleanup()


if __name__ == "__main__":
    unittest.main()
