"""QM6 완료 조건: L6 지표, 기준선, 드리프트, 용어 후보, 리포트 재현, 본문 없음, 추이, 판정 전이표(6.6절)."""
import copy
import math
import os
import shutil
import tempfile
import unittest

from engrbot import io, model, report, runner, stats
from engrbot import policy as policy_mod
from engrbot.adapters import bundle_files
from engrbot.tests import fixturegen

LAYERS = ["L1", "L2", "L6"]
SCHEMA = policy_mod.validate_schema({})


def _policy(**l6):
    user = {"layers": list(LAYERS), "l6": dict({"min_n": 10}, **l6)}
    return user, policy_mod.validate_policy(user)


def _qid(n):
    return "QA-20261004T%06d-%04x" % (n, n)


class Workspace(object):
    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="engrbot_l6_")
        self.paths = io.QaPaths(self.root)

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)


def make_run(bundle, pol, paths, qa_run_id, proposals=None, append_history=True):
    """runner.run 대신 쓴다: 검사 → verdicts·manifest·대기열 저장 → report.write."""
    res = runner.execute(bundle, pol, SCHEMA, paths=paths, qa_run_id=qa_run_id, layers=pol["layers"])
    res.run_dir = paths.run_dir(qa_run_id, create=True)
    res.manifest = {"qa_run_id": qa_run_id, "labeler_run_id": bundle.labeler_run_id, "versions": res.ctx.versions,
                    "input_fingerprint": bundle.fingerprint(), "layers": list(pol["layers"]), "judge_ran": False,
                    "judge_skip_reason": None, "judge": {"calls": 0, "cache_hits": 0, "failed": 0}}
    res.queue = [{"record_id": v["record_id"], "file_id": v["file_id"], "priority": 1, "score": v["score"],
                  "issue_codes": sorted({i["code"] for i in v["issues"]}), "fields": [], "group": None}
                 for v in res.verdicts if v["verdict"] == "REVIEW"]
    res.proposals = list(proposals or [])
    runner.write_verdicts(res)
    io.write_jsonl(res.path("file_issues.jsonl"), res.file_issues)
    io.write_jsonl(res.path("review_queue.jsonl"), res.queue)
    io.write_jsonl(res.path("proposals.jsonl"), res.proposals)
    io.write_json(res.path("manifest.json"), res.manifest)
    report.write(res, append_history=append_history)
    return res


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def codes_of(res):
    return [(i["code"], i.get("field")) for i in res.batch_issues]


# ---- 손으로 만든 작은 배치 ------------------------------------------------------

NA, UNK = model.NA, model.UNKNOWN


def _ax(vals):
    status = "na" if vals == [NA] else "unknown" if vals == [UNK] else "value"
    return {"values": list(vals), "status": status, "evidence": {"quote": "근거 문장" if status == "value" else ""},
            "confidence": 0.9}


def _ans(a):
    return {"Q1": {"answer": a, "evidence": {"quote": "근거 문장" if a in ("O", "X") else ""}, "confidence": 0.9}}


def hand_bundle():
    tax = {"version": "tax-v1", "questions_version": "q-v1", "synonyms_version": "s-v1",
           "reserved": {"na": NA, "unknown": UNK},
           "axes": [{"name": "A", "kind": "분류", "multi": True, "hierarchical": False, "active": True,
                     "values": [{"name": n, "parent": None, "definition": ""} for n in ("a1", "a2", "a3")]},
                    {"name": "B", "kind": "분류", "multi": False, "hierarchical": False, "active": True,
                     "values": [{"name": n, "parent": None, "definition": ""} for n in ("b1", "b2")]}],
           "questions": [{"qid": "Q1", "text": "질문", "target": "공통"}],
           "synonyms": [{"alias": "알파", "canonical": "a1"}]}
    fid = "f" * 64
    spec = [  # (번호, chunk 유형, A, B, Q1)
        (1, "내용", ["a1", "a2"], ["b1"], "O"),
        (2, "내용", ["a1"], [UNK], "X"),
        (3, "내용", [UNK], [NA], "N/A"),
        (4, "내용", ["a1"], ["b1"], "O"),
        (5, "내용", [NA], ["b1"], "O"),
        (6, "표지", [NA], [NA], None),
        (7, None, None, None, None),  # 1차 분류 실패
    ]
    units, records = {}, []
    for n, ct, a, b, q in spec:
        rid = "%s:ppt/slides/slide%d.xml" % (fid[:16], n)
        text = "슬라이드 %d 본문 문장입니다" % n
        units[rid] = {"unit_id": rid, "file_id": fid, "seq": n, "title": "", "text": text, "text_canonical": None,
                      "text_hash": model.sha256_text(text), "tables": [], "notes": "", "charts": [], "images": [],
                      "warnings": []}
        rec = {"record_id": rid, "file_id": fid, "labeler_run_id": "LR-1", "chunk_type": ct,
               "axes": {"A": _ax(a), "B": _ax(b)} if a else {}, "answers": _ans(q) if q else {}, "extracted": [],
               "failures": [], "labeler": {"agent": "labelbot", "prompt_versions": {}}, "human_reviewed": False}
        if ct is None:
            rec["failures"] = [{"stage": "classify", "reason_code": "LLM_FAILED"}]
        records.append(rec)
    sources = {fid: {"file_id": fid, "ext": ".pptx", "status": "ok", "reason_code": None, "b64_ref": "b64/x.b64"}}
    return model.Bundle("LR-1", sources, units, records, tax, meta={"file_names": {fid: "손 배치 파일"}})


class StatsTest(unittest.TestCase):
    def test_jsd_values(self):
        self.assertEqual(stats.jsd({"x": 3}, {"x": 7}), 0.0)
        self.assertAlmostEqual(stats.jsd({"x": 1}, {"y": 1}), 1.0, places=12)
        # p=(.5,.5), q=(1,0), m=(.75,.25): ½(½log2(2/3)+½log2(2)) + ½log2(4/3)
        expect = 0.5 * (0.5 * math.log(0.5 / 0.75, 2) + 0.5 * 1.0) + 0.5 * math.log(1 / 0.75, 2)
        self.assertAlmostEqual(stats.jsd({"a": 1, "b": 1}, {"a": 2, "b": 0}), expect, places=12)
        self.assertAlmostEqual(expect, 0.3112781, places=6)
        self.assertIsNone(stats.jsd({}, {"a": 1}))

    def test_pareto_hand(self):
        def v(*cs):
            return {"issues": [{"code": c, "layer": "L2", "severity": "major"} for c in cs]}

        out = stats.pareto([v("X", "Y"), v("X"), v("X", "X"), v("Z"), v()])
        self.assertEqual([(p["code"], p["records"]) for p in out], [("X", 3), ("Y", 1), ("Z", 1)])
        self.assertAlmostEqual(out[0]["share"], 0.6)
        self.assertAlmostEqual(out[1]["cum_share"], 0.8)
        self.assertAlmostEqual(out[2]["cum_share"], 1.0)

    def test_term_candidates_hand(self):
        docs = {"r1": "Foo 공정", "r2": "foo 공정", "r3": "FOO 공정", "r4": "공정 bar", "r5": "공정 bar"}
        out = stats.term_candidates(docs, {"r1", "r2", "r3"}, stats.exclusion_keys(["bar"]), 3, 1.5, 10)
        self.assertEqual(len(out), 1)
        self.assertEqual((out[0]["df_u"], out[0]["df_all"]), (3, 3))
        self.assertAlmostEqual(out[0]["lift"], (3 / 3.0) / (3 / 5.0), places=6)
        self.assertEqual(out[0]["examples"], ["r1", "r2", "r3"])


class HandBatchTest(unittest.TestCase):
    def setUp(self):
        self.ws = Workspace()

    def tearDown(self):
        self.ws.close()

    def test_hand_computed_metrics(self):
        _, pol = _policy(min_n=1, unused_runs=1)
        res = runner.execute(hand_bundle(), pol, SCHEMA, paths=None, qa_run_id=_qid(1), layers=LAYERS)
        m = res.metrics
        self.assertEqual(sorted(m), sorted([
            "records", "content_records", "counts", "pass_rate", "pareto", "layer_issue_rate", "distribution",
            "answer_distribution", "unknown_rate", "coverage", "unused_labels", "unused_streak", "terms", "drift",
            "judge"]))
        # r2·r3: unknown 비율 ≥ 0.5 → L2_UNKNOWN_OVERUSE(major) → REVIEW. r7: 분류 실패 → REJECT.
        self.assertEqual(m["records"], 7)
        self.assertEqual(m["content_records"], 5)  # 표지와 분류 실패 제외
        self.assertEqual(m["counts"], {"PASS": 4, "AUTO_FIX": 0, "REVIEW": 2, "REJECT": 1})
        self.assertAlmostEqual(m["pass_rate"], 4 / 7.0, places=6)
        self.assertEqual([(p["code"], p["records"]) for p in m["pareto"]],
                         [("L2_UNKNOWN_OVERUSE", 2), ("L1_LABELER_FAILED", 1)])
        self.assertAlmostEqual(m["pareto"][0]["share"], 2 / 3.0, places=6)
        self.assertAlmostEqual(m["pareto"][1]["cum_share"], 1.0, places=6)
        self.assertAlmostEqual(m["layer_issue_rate"]["L1"], 1 / 7.0, places=6)
        self.assertAlmostEqual(m["layer_issue_rate"]["L2"], 2 / 7.0, places=6)
        self.assertEqual(m["distribution"]["A"], {"a1": 3, "a2": 1, UNK: 1, NA: 1})
        self.assertEqual(m["distribution"]["B"], {"b1": 3, UNK: 1, NA: 1})
        self.assertEqual(m["answer_distribution"]["Q1"], {"O": 3, "X": 1, "N/A": 1})
        self.assertAlmostEqual(m["unknown_rate"]["A"], 1 / 4.0)  # 1 / (5 − 해당 없음 1)
        self.assertAlmostEqual(m["unknown_rate"]["B"], 1 / 4.0)
        self.assertAlmostEqual(m["coverage"]["A"], 2 / 3.0, places=6)
        self.assertAlmostEqual(m["coverage"]["B"], 0.5)
        self.assertEqual(m["unused_labels"], {"A": ["a3"], "B": ["b2"]})
        self.assertEqual(m["unused_streak"], {"A": ["a3"], "B": ["b2"]})  # unused_runs=1이면 이번 실행만 본다
        self.assertEqual(m["judge"], {"items": 0, "supported": 0, "partial": 0, "unsupported": 0, "failed": 0})
        self.assertIsNone(m["drift"]["baseline_qa_run_id"])
        self.assertIn("L6_UNUSED_LABELS", [c for c, _ in codes_of(res)])
        self.assertNotIn("L6_UNKNOWN_RATE_HIGH", [c for c, _ in codes_of(res)])  # 0.25 < 0.3
        for v in res.verdicts:  # 배치 이슈는 판정을 바꾸지 않는다
            self.assertFalse([i for i in v["issues"] if i["layer"] == "L6"])

    def test_unknown_rate_alert(self):
        _, pol = _policy(min_n=1, unknown_rate_alert=0.25)
        res = runner.execute(hand_bundle(), pol, SCHEMA, qa_run_id=_qid(1), layers=LAYERS)
        self.assertIn(("L6_UNKNOWN_RATE_HIGH", "axis:A"), codes_of(res))
        self.assertIn(("L6_UNKNOWN_RATE_HIGH", "axis:B"), codes_of(res))

    def test_judge_not_run_is_on_top(self):
        _, pol = _policy(min_n=1)
        res = make_run(hand_bundle(), pol, self.ws.paths, _qid(1))
        head = read(res.path("report.md")).splitlines()[:20]
        self.assertTrue(any("judge 미실행" in l for l in head[:4]))
        joined = "\n".join(head)
        self.assertIn("통과율: 57.1%", joined)
        self.assertIn("PASS 4, AUTO_FIX 0, REVIEW 2, REJECT 1", joined)
        self.assertIn("배치 이슈", joined)
        md = read(res.path("report.md"))
        self.assertIn("누락 라벨", md)
        for n in range(1, 9):
            self.assertIn("## %d. " % n, md)
        rep = io.read_own_json(res.path("report.json"))
        self.assertEqual(rep["review_queue"], {"count": 2, "codes": {"L2_UNKNOWN_OVERUSE": 2}})
        self.assertFalse(rep["judge"]["ran"])


# ---- fixture 배치: 기준선, 드리프트, 용어 -----------------------------------------

def shifted(bundle, axis="불량 모드", value="Short"):
    b = bundle.copy()
    for r in b.records:
        if r["chunk_type"] == "내용":
            r["axes"][axis] = {"values": [value], "status": "value", "evidence": {"quote": value}, "confidence": 0.9}
    return b


class BaselineDriftTest(unittest.TestCase):
    def setUp(self):
        self.ws = Workspace()
        self.fx = fixturegen.generate(seed=11, n_files=5)

    def tearDown(self):
        self.ws.close()

    def test_no_baseline_then_set_gives_zero(self):
        _, pol = _policy()
        r1 = make_run(self.fx.bundle, pol, self.ws.paths, _qid(1))
        d = r1.metrics["drift"]
        self.assertIsNone(d["baseline_qa_run_id"])
        self.assertEqual((d["axes"], d["answers"]), ({}, {}))
        self.assertIn("기준선 없음", d["note"])
        self.assertIn("baseline set", d["note"])
        self.assertFalse([c for c, _ in codes_of(r1) if c in ("L6_DRIFT_HIGH", "L6_SAMPLE_TOO_SMALL", "L6_PASS_RATE_DROP")])
        self.assertIn("기준선 없음", read(r1.path("report.md")))

        doc = report.set_baseline(r1)
        self.assertEqual(io.read_own_json(self.ws.paths.baseline)["qa_run_id"], _qid(1))
        self.assertEqual(doc["taxonomy_version"], self.fx.bundle.taxonomy["version"])
        r2 = make_run(self.fx.bundle, pol, self.ws.paths, _qid(2))
        d2 = r2.metrics["drift"]
        self.assertEqual(d2["baseline_qa_run_id"], _qid(1))
        self.assertFalse(d2["taxonomy_changed"])
        self.assertTrue(d2["axes"])
        for e in list(d2["axes"].values()) + list(d2["answers"].values()):
            self.assertEqual(e["jsd"], 0.0)
            self.assertEqual(e["level"], "ok")
        self.assertFalse([c for c, _ in codes_of(r2) if c.startswith("L6_DRIFT") or c == "L6_PASS_RATE_DROP"])

        # 새 기준선을 올리면 이전 것은 baseline_<이전 ID>.json으로 남는다
        report.set_baseline(r2)
        self.assertEqual(io.read_own_json(self.ws.paths.q("baseline_%s.json" % _qid(1)))["qa_run_id"], _qid(1))
        self.assertEqual(io.read_own_json(self.ws.paths.baseline)["qa_run_id"], _qid(2))

    def test_shifted_axis_raises_drift_high(self):
        _, pol = _policy()
        report.set_baseline(make_run(self.fx.bundle, pol, self.ws.paths, _qid(1)))
        r2 = make_run(shifted(self.fx.bundle), pol, self.ws.paths, _qid(2))
        e = r2.metrics["drift"]["axes"]["불량 모드"]
        self.assertGreaterEqual(e["jsd"], pol["l6"]["jsd_alert"])
        self.assertEqual(e["level"], "경보")
        self.assertIn(("L6_DRIFT_HIGH", "axis:불량 모드"), codes_of(r2))
        self.assertEqual(r2.metrics["drift"]["axes"]["공정 모듈"]["level"], "ok")
        self.assertNotIn(("L6_DRIFT_HIGH", "axis:공정 모듈"), codes_of(r2))
        rep = io.read_own_json(r2.path("report.json"))
        self.assertIn("L6_DRIFT_HIGH", [i["code"] for i in rep["batch_issues"]])

    def test_sample_too_small(self):
        _, pol = _policy(min_n=100000)
        report.set_baseline(make_run(self.fx.bundle, pol, self.ws.paths, _qid(1)))
        r2 = make_run(shifted(self.fx.bundle), pol, self.ws.paths, _qid(2))
        got = codes_of(r2)
        self.assertIn(("L6_SAMPLE_TOO_SMALL", "axis:불량 모드"), got)
        self.assertIn(("L6_SAMPLE_TOO_SMALL", "answer:Q-COM-001"), got)
        self.assertNotIn("L6_DRIFT_HIGH", [c for c, _ in got])
        for e in r2.metrics["drift"]["axes"].values():
            self.assertIsNone(e["jsd"])
            self.assertEqual(e["level"], "표본 부족")

    def test_taxonomy_changed_baseline(self):
        _, pol = _policy()
        report.set_baseline(make_run(self.fx.bundle, pol, self.ws.paths, _qid(1)))
        base = io.read_own_json(self.ws.paths.baseline)
        base["taxonomy_version"] = "old-taxonomy"
        base["taxonomy_values"]["불량 모드"] = [v for v in base["taxonomy_values"]["불량 모드"] if v != "Open"]
        io.write_json(self.ws.paths.baseline, base)
        r2 = make_run(shifted(self.fx.bundle), pol, self.ws.paths, _qid(2))
        d = r2.metrics["drift"]
        self.assertTrue(d["taxonomy_changed"])
        self.assertIn("taxonomy 변경됨", d["note"])
        self.assertEqual(d["axes"]["불량 모드"]["level"], "주의")  # 경보는 주의로 낮춘다
        self.assertNotIn("L6_DRIFT_HIGH", [c for c, _ in codes_of(r2)])
        # 공통 값만 센다: Open은 기준선 taxonomy에 없으므로 n에서 빠진다
        dist = r2.metrics["distribution"]["불량 모드"]
        self.assertEqual(d["axes"]["불량 모드"]["n"], sum(n for v, n in dist.items() if v != "Open"))
        md = read(r2.path("report.md"))
        self.assertIn("taxonomy 변경됨", md)

    def test_pass_rate_drop(self):
        _, pol = _policy()
        report.set_baseline(make_run(self.fx.bundle, pol, self.ws.paths, _qid(1)))
        b = self.fx.bundle.copy()
        for r in b.records:
            if r["chunk_type"] == "내용":
                r["axes"]["불량 모드"] = {"values": ["없는값"], "status": "value", "evidence": {"quote": "x"},
                                       "confidence": 0.9}
        r2 = make_run(b, pol, self.ws.paths, _qid(2))
        self.assertIn(("L6_PASS_RATE_DROP", None), codes_of(r2))


class TermCandidateTest(unittest.TestCase):
    def setUp(self):
        self.ws = Workspace()

    def tearDown(self):
        self.ws.close()

    def test_planted_term_ranks_top_and_taxonomy_excluded(self):
        fx = fixturegen.generate(seed=5, n_files=6)
        b = fx.bundle.copy()
        unk = []
        for r in b.records:
            if r["chunk_type"] == "내용" and any(model.UNKNOWN in a["values"] for a in r["axes"].values()):
                unk.append(r["record_id"])
                u = b.units[r["record_id"]]
                u["text"] += "\nZeta-Probe 브릿지 dishing METAL1 sHoRt 단락 Rs"
                u["text_hash"] = model.sha256_text(u["text"])
        n_content = sum(1 for r in b.records if r["chunk_type"] == "내용")
        self.assertGreaterEqual(len(unk), 3)
        expect_lift = n_content / float(len(unk))
        _, pol = _policy(terms={"min_df": 3, "min_lift": min(1.5, expect_lift - 0.01), "top_k": 50, "stoplist": []})
        res = make_run(b, pol, self.ws.paths, _qid(1))
        terms = res.metrics["terms"]
        self.assertEqual(terms[0]["term"], "Zeta-Probe")
        self.assertEqual(terms[0]["df_u"], len(unk))
        self.assertAlmostEqual(terms[0]["lift"], expect_lift, places=5)
        self.assertEqual(terms[0]["examples"], sorted(unk)[:5])
        got = {t["term"].casefold() for t in terms}
        for banned in ("브릿지", "dishing", "metal1", "short", "단락", "rs", "unknown"):
            self.assertNotIn(banned, got)
        self.assertIn(("L6_UNMAPPED_TERMS", None), codes_of(res))
        issue = [i for i in res.batch_issues if i["code"] == "L6_UNMAPPED_TERMS"][0]
        self.assertEqual(issue["evidence"], {"count": len(terms)})
        # 후보는 taxonomy_candidates.*에만 있고 리포트에는 건수만 있다
        self.assertIn("Zeta-Probe", read(res.path("taxonomy_candidates.jsonl")))
        self.assertIn("Zeta-Probe", read(res.path("taxonomy_candidates.md")))
        for name in ("report.md", "report.json"):
            self.assertNotIn("Zeta-Probe", read(res.path(name)))
        rep = io.read_own_json(res.path("report.json"))
        self.assertEqual(rep["unmapped_terms"], {"count": len(terms), "file": "taxonomy_candidates.jsonl"})

    def test_stoplist_removes_term(self):
        fx = fixturegen.generate(seed=5, n_files=6)
        b = fx.bundle.copy()
        for r in b.records:
            if r["chunk_type"] == "내용" and any(model.UNKNOWN in a["values"] for a in r["axes"].values()):
                b.units[r["record_id"]]["text"] += "\nZeta-Probe"
        _, pol = _policy(terms={"min_df": 3, "min_lift": 1.0, "top_k": 50, "stoplist": ["zeta-probe"]})
        res = runner.execute(b, pol, SCHEMA, qa_run_id=_qid(1), layers=LAYERS)
        self.assertNotIn("zeta-probe", {t["term"].casefold() for t in res.metrics["terms"]})


# ---- 리포트: 재현, 본문 없음, 추이, 전이표 -------------------------------------------

class ReportTest(unittest.TestCase):
    def setUp(self):
        self.ws = Workspace()
        self.fx = fixturegen.generate(seed=3, n_files=4)

    def tearDown(self):
        self.ws.close()

    def test_report_regenerated_identically_without_llm(self):
        user, pol = _policy()
        io.write_json(self.ws.paths.policy, user)
        bdir = os.path.join(self.ws.root, "bundle")
        bundle_files.save(self.fx.bundle, bdir)
        b = bundle_files.load(bdir)
        report.set_baseline(make_run(b, pol, self.ws.paths, _qid(1)))
        res = make_run(shifted(b), pol, self.ws.paths, _qid(2))
        # 다른 bundle_dir에 바뀐 번들을 저장해 reload가 같은 입력을 읽게 한다
        bdir2 = os.path.join(self.ws.root, "bundle2")
        bundle_files.save(shifted(b), bdir2)
        names = ("report.json", "report.md", "taxonomy_candidates.jsonl", "taxonomy_candidates.md")
        before = {n: read(res.path(n)) for n in names}
        hist_before = read(self.ws.paths.history)
        # 기준선을 바꿔도(l6_inputs.json 덕분에) 같은 리포트가 나와야 한다
        report.set_baseline(res)
        again = runner.reload(self.ws.paths, _qid(2), bundle_dir=bdir2)
        self.assertIsNone(again.ctx.judge)
        report.write(again, append_history=False)
        for n in names:
            self.assertEqual(read(res.path(n)), before[n], n)
        self.assertEqual(read(self.ws.paths.history), hist_before)
        self.assertNotIn("finished_at", before["report.json"])
        self.assertNotIn("started_at", before["report.json"])

    def test_no_body_filenames_paths(self):
        _, pol = _policy()
        b = self.fx.bundle.copy()
        victim = sorted(r["record_id"] for r in b.records if r["chunk_type"] == "내용")[0]
        rec = [r for r in b.records if r["record_id"] == victim][0]
        rec["axes"]["불량 모드"] = {"values": ["없는값"], "status": "value", "evidence": {"quote": "본문 인용"},
                                 "confidence": 0.9}
        res = make_run(b, pol, self.ws.paths, _qid(1),
                       proposals=[{"proposal_id": "p1", "kind": "TERM", "target": "term:Zeta"}])
        files = [res.path("report.md"), res.path("report.json"), self.ws.paths.history]
        texts = [read(p) for p in files]
        lines = set()
        for u in b.units.values():
            lines.update(l.strip() for l in u["text"].split("\n") if len(l.strip()) >= 6)
            if len(u.get("title") or "") >= 6:
                lines.add(u["title"])
        self.assertTrue(lines)
        names = list((b.meta.get("file_names") or {}).values())
        self.assertTrue(names)
        for path, text in zip(files, texts):
            for l in lines:
                self.assertNotIn(l, text, (os.path.basename(path), l))
            for n in names:
                self.assertNotIn(n, text)
            for frag in (self.ws.root, self.ws.root.replace("\\", "/"), res.run_dir, ".pptx", ".b64", "본문 인용",
                         "없는값"):
                self.assertNotIn(frag, text)

    def test_history_grows_and_report_shows_last_six(self):
        _, pol = _policy(unused_runs=2)
        b = self.fx.bundle.copy()
        for r in b.records:
            ax = r["axes"].get("구조/레이어")
            if ax and "JHV" in ax["values"]:
                ax["values"] = ["M1"]
        runs = []
        for n in range(1, 8):
            runs.append(make_run(b, pol, self.ws.paths, _qid(n)))
            self.assertEqual(len(io.read_own_jsonl(self.ws.paths.history)), n)
        hist = io.read_own_jsonl(self.ws.paths.history)
        self.assertEqual([h["qa_run_id"] for h in hist], [_qid(n) for n in range(1, 8)])
        for key in ("pass_rate", "counts", "unknown_rate", "coverage", "top_codes", "unused_labels", "taxonomy_version"):
            self.assertIn(key, hist[0])
        rep = io.read_own_json(runs[-1].path("report.json"))
        self.assertEqual([h["qa_run_id"] for h in rep["history"]], [_qid(n) for n in range(2, 8)])
        md = read(runs[-1].path("report.md"))
        for n in range(2, 8):
            self.assertIn(_qid(n), md)
        self.assertNotIn(_qid(1), md)
        # 연속 미사용: 첫 실행은 이력이 없어 표시하지 않고, 두 번째부터 JHV가 연속 미사용이다
        self.assertEqual(runs[0].metrics["unused_streak"]["구조/레이어"], [])
        self.assertIn("JHV", runs[1].metrics["unused_streak"]["구조/레이어"])
        self.assertEqual(runs[1].metrics["unused_streak"], runs[1].metrics["unused_labels"])
        self.assertIn(("L6_UNUSED_LABELS", "axis:구조/레이어"), codes_of(runs[1]))
        self.assertNotIn("L6_UNUSED_LABELS", [c for c, _ in codes_of(runs[0])])

    def test_transition_table_matches_hand_count(self):
        _, pol = _policy()
        b1 = self.fx.bundle
        r1 = make_run(b1, pol, self.ws.paths, _qid(1))
        content = sorted(r["record_id"] for r in b1.records if r["chunk_type"] == "내용")
        bad, changed, removed = content[0], content[1], content[2]
        b2 = b1.copy()
        for r in b2.records:
            if r["record_id"] == bad:
                r["axes"]["불량 모드"] = {"values": ["없는값"], "status": "value", "evidence": {"quote": "x"},
                                       "confidence": 0.9}
        u = b2.units[changed]
        u["text"] += "\n추가 문장"
        u["text_hash"] = model.sha256_text(u["text"])
        b2.records = [r for r in b2.records if r["record_id"] != removed]
        src = copy.deepcopy([r for r in b2.records if r["record_id"] == content[3]][0])
        new_id = src["record_id"].split(":")[0] + ":ppt/slides/slide99.xml"
        src["record_id"] = new_id
        nu = copy.deepcopy(b2.units[content[3]])
        nu.update(unit_id=new_id, seq=99)
        b2.units[new_id] = nu
        b2.records.append(src)
        io.write_json(os.path.join(r1.run_dir, "feedback", "feedback.json"), {
            "qa_run_id": _qid(1), "proposals": [
                {"proposal_id": "p-axis", "kind": "AXIS_DEFINITION", "target": "axis:불량 모드"},
                {"proposal_id": "p-code", "kind": "QUOTE_RULE", "target": "L2_LABEL_NOT_IN_TAXONOMY"},
                {"proposal_id": "p-term", "kind": "TERM", "target": "term:Zeta-Probe 측정"}]})
        r2 = make_run(b2, pol, self.ws.paths, _qid(2))
        t = io.read_own_json(r2.path("report.json"))["transitions"]

        v1, v2 = r1.verdict_map(), r2.verdict_map()
        hand = {p: {c: 0 for c in model.VERDICTS} for p in model.VERDICTS}
        for rid in set(v1) & set(v2):
            if v1[rid]["text_hash"] == v2[rid]["text_hash"]:
                hand[v1[rid]["verdict"]][v2[rid]["verdict"]] += 1
        self.assertEqual(t["previous_qa_run_id"], _qid(1))
        self.assertEqual(t["matrix"], hand)
        self.assertEqual(t["matrix"]["PASS"]["REJECT"], 1)
        self.assertEqual((t["text_changed"], t["only_previous"], t["only_current"]), (1, 1, 1))
        self.assertEqual(t["matched"], len(set(v1) & set(v2)) - 1)

        effects = {e["proposal_id"]: e for e in t["proposal_effects"]}
        self.assertEqual(sorted(effects), ["p-axis", "p-code"])
        self.assertEqual(effects["p-axis"]["issue_rate"], {"before": 0.0, "after": round(1 / float(len(v2)), 6)})
        self.assertEqual(effects["p-code"]["issue_rate"], {"before": 0.0, "after": round(1 / float(len(v2)), 6)})
        self.assertEqual(effects["p-axis"]["unknown_rate"]["before"], r1.metrics["unknown_rate"]["불량 모드"])
        self.assertEqual(t["proposals_skipped"], 1)
        md = read(r2.path("report.md"))
        self.assertIn("직전 실행: %s" % _qid(1), md)
        for text in (md, read(r2.path("report.json"))):
            self.assertNotIn("Zeta-Probe", text)

    def test_first_run_has_no_transition(self):
        _, pol = _policy()
        res = make_run(self.fx.bundle, pol, self.ws.paths, _qid(1))
        t = io.read_own_json(res.path("report.json"))["transitions"]
        self.assertIsNone(t["previous_qa_run_id"])
        self.assertIn("직전 검수 실행이 없어", read(res.path("report.md")))

    def test_metrics_computed_when_l6_layer_off(self):
        user, _ = _policy()
        pol = policy_mod.validate_policy(dict(user, layers=["L1", "L2"]))
        res = make_run(self.fx.bundle, pol, self.ws.paths, _qid(1))
        rep = io.read_own_json(res.path("report.json"))
        self.assertEqual(rep["counts"]["records"], len(self.fx.bundle.records))
        self.assertEqual(rep["batch_issues"], [])
        self.assertTrue(rep["coverage"])


if __name__ == "__main__":
    unittest.main()
