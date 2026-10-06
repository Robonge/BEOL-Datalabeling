"""교정 장부(ledger) 테스트: 위치, intake 산출물, 건너뜀 코드, 멱등성, 작업 폴더 교체, 규칙 후보, CLI, run 자동 intake.

작업 폴더는 코드 폴더 밖(tempfile.mkdtemp)에 만들고 work.sqlite에 runs·chunks·labels·corrections 등을 직접 넣는다.
taxonomy는 저장소의 taxonomy.xlsx를 pipeline.json으로 가리킨다. 네트워크는 쓰지 않는다.
"""
import contextlib
import hashlib
import io as std_io
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest import mock

from labelbot import store
from labelbot.workspace import CODE_ROOT

from domain_engrbot import cli, domain_rules, golden, io, ledger, model, runner
from domain_engrbot import policy as policy_mod
from domain_engrbot.adapters import labelbot_ws

TAXONOMY = os.path.join(CODE_ROOT, "taxonomy", "taxonomy.xlsx")
RUN = "20261001T000000-0001"
RUN2 = "20261002T000000-0002"
BODY = "본문표식XYZ"
FILE_NAME = "합성장부자료.pptx"
MEMO = "메모표식QWE"
GEN_QID = "Q-GEN-0001"
APPLIED = "2026-10-01T00:00:00Z"
# 사람이 검수 화면에서 남긴 근거 인용·이유 표식. evidence.jsonl과 최종 검수 화면 밖에는 나오면 안 된다
EV_QUOTE = "근거표식EVQ"
REASON = "이유표식RSN"


def _tax():
    tax = labelbot_ws.load_taxonomy(".", {"taxonomy_path": TAXONOMY})
    snap = labelbot_ws.snapshot(tax)
    axes = {a["name"]: [v["name"] for v in a["values"]] for a in snap["axes"]}

    def axis_with(v):
        return next(n for n, vals in axes.items() if v in vals)

    return axis_with("M1"), axis_with("CMP"), axis_with("Short"), snap


LAYER, MODULE, DEFECT, SNAP = _tax()
APPROVED_QID = SNAP["questions"][0]["qid"]
QHASH = model.sha256_text(SNAP["questions"][0]["text"])[:16]
LONG = "가" * 320
# 후보 규칙은 서로 다른 파일 수(min_files)를 보므로 chunk를 두 파일에 번갈아 둔다(홀수 → 0, 짝수 → 1)
FIDS = [hashlib.sha256(b"ledger-fixture-%d" % k).hexdigest() for k in (0, 1)]


def fid_of(n):
    return FIDS[(n + 1) % 2]


def cid_of(n):
    return "%s:slide%d" % (fid_of(n)[:16], n)


def _chunks():
    """chunk별 사양: (part, chunk_type, title, 축 {축: (값 목록, 인용)}, 답 {qid: (답, 인용)})."""
    base = {LAYER: (["M1"], "M1 배선 인용"), MODULE: (["CMP"], "CMP 공정 인용"), DEFECT: (["Short"], "Short 불량 인용")}
    ans = {APPROVED_QID: ("O", "승인 질문 인용"), GEN_QID: ("O", "검증 질문 인용")}
    out = {}
    for n in range(1, 16):
        out["slide%d" % n] = {"type": "내용", "title": "주간 보고 %d" % n, "axes": dict(base), "answers": dict(ans)}
    for n in (2, 3):
        out["slide%d" % n]["axes"][DEFECT] = (["Short", "Open"], "Short Open 인용 %d" % n)
    out["slide7"]["type"] = "표지"
    out["slide9"]["axes"][LAYER] = (["M1", "M2"], LONG)
    out["slide10"]["title"] = "M2 배선 보고"
    out["slide12"]["title"] = "M2 저항 정리"
    # CMP가 아닌 레코드에서는 Open이 맞다(forbid 후보가 무조건 금지가 되지 않게 한다)
    out["slide14"]["axes"][LAYER] = (["M3"], "M3 배선 인용")
    out["slide14"]["axes"][MODULE] = (["Etch"], "Etch 공정 인용")
    out["slide14"]["axes"][DEFECT] = (["Open"], "Open 불량 인용")
    # 봇 축 값이 깨진 JSON 문자열(목록이 아님)인 레코드. 글자 단위로 쪼개면 안 된다
    out["slide15"]["axes"][LAYER] = (["M3"], "M3 배선 인용")
    out["slide15"]["axes"][MODULE] = (["Etch"], "Etch 공정 인용")
    out["slide15"]["axes"][DEFECT] = ("Short,Open", "깨진 값 인용")
    return out


def _corrections():
    """(chunk 번호, target_kind, target_key, human_value, recheck[, question_hash])"""
    rows = [
        (1, "chunk", "status", "confirmed", 0),
        (2, "axis", DEFECT, ["Short"], 0),
        (3, "axis", DEFECT, ["Short"], 0),
        (4, "chunk", "status", "confirmed", 1),
        (5, "axis", DEFECT, ["판단 불가"], 0),
        (6, "chunk", "status", "undecidable_image", 0),
        (6, "axis", LAYER, ["M2"], 0),
        (7, "chunk", "status", "confirmed", 0),
        (8, "axis", DEFECT, ["없는값"], 0),
        (9, "chunk", "status", "confirmed", 0),
        (10, "chunk", "status", "confirmed", 0),
        (10, "axis", LAYER, ["M1", "M2"], 0),
        (11, "answer", GEN_QID, "X", 0),
        (12, "axis", LAYER, ["M1", "M2"], 0),
        (13, "chunk", "status", "confirmed", 0),
        (14, "chunk", "status", "confirmed", 0),
        (15, "axis", DEFECT, ["Open"], 0),
        (12, "answer", APPROVED_QID, "X", 0, "0" * 16),
        (13, "answer", APPROVED_QID, "X", 0, QHASH),
    ]
    return [(cid_of(r[0]),) + tuple(r[1:5]) + (r[5] if len(r) > 5 else None,) for r in rows]


def _evidence():
    """교정 근거 {(chunk_id, target_kind, target_key): (근거 목록 또는 None, 이유 또는 None)}.
    2: 같은 슬라이드 + 문서 제목 + 이유, 3: 이유만, 10: 같은 파일의 다른 슬라이드(12), 13: 파일명."""
    return {
        (cid_of(2), "axis", DEFECT): ([{"source": "chunk", "chunk_id": cid_of(2), "slide_no": 2,
                                        "quote": EV_QUOTE + " 같은 슬라이드"},
                                       {"source": "doc_title", "chunk_id": None, "slide_no": None,
                                        "quote": EV_QUOTE + " 문서 제목"}], REASON + " 2"),
        (cid_of(3), "axis", DEFECT): (None, REASON + " 3"),
        (cid_of(10), "axis", LAYER): ([{"source": "chunk", "chunk_id": cid_of(12), "slide_no": 12,
                                        "quote": EV_QUOTE + " 다른 슬라이드"}], None),
        (cid_of(13), "answer", APPROVED_QID): ([{"source": "file_name", "chunk_id": None, "slide_no": None,
                                                 "quote": EV_QUOTE + " 파일명"}], None),
    }


def build_ws(parent, name, runs=(RUN,), corrections=True, run_corrections=None, evidence=True):
    """반환: 작업 폴더 경로. 원본 파일은 쓰지 않고 work.sqlite와 pipeline.json만 만든다.
    run_corrections({실행: 교정 행 목록})를 주면 그 실행은 기본 교정 대신 그 행을 쓴다.
    evidence: True면 _evidence()를, dict면 그 근거를 corrections의 evidence·reason 열에 넣는다.
    None이면 근거 열을 더하지 않는다(근거 열이 없던 작업 DB)."""
    root = os.path.join(parent, name)
    os.makedirs(root)
    with open(os.path.join(root, "pipeline.json"), "w", encoding="utf-8") as f:
        json.dump({"taxonomy_path": TAXONOMY, "llm": {"transport": "mock"}}, f)
    con = store.connect(os.path.join(root, "work.sqlite"))
    evid = _evidence() if evidence is True else (evidence or {})
    try:
        if evidence is not None:
            cols = {r[1] for r in con.execute("PRAGMA table_info(corrections)")}
            for col, typ in (("evidence", "TEXT"), ("reason", "TEXT"), ("evidence_dropped", "INTEGER")):
                if col not in cols:
                    con.execute("ALTER TABLE corrections ADD COLUMN %s %s" % (col, typ))
        for fid in FIDS:
            con.execute("INSERT INTO files(file_id, file_name, rel_path, ext, size, status) VALUES(?,?,?,?,?,?)",
                        (fid, FILE_NAME, FILE_NAME, ".pptx", 10, "ok"))
        texts = {}
        for seq, (part, spec) in enumerate(sorted(_chunks().items(), key=lambda kv: int(kv[0][5:]))):
            fid = fid_of(int(part[5:]))
            c = cid_of(int(part[5:]))
            text = "%s %s 내용" % (BODY, part)
            texts[c] = model.sha256_text(text)
            con.execute("INSERT INTO chunks(chunk_id, file_id, seq, part_name, title, text, text_hash, warnings,"
                        " images, view) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (c, fid, seq, part, spec["title"], text, texts[c], "[]", "[]", "{}"))
        for run in runs:
            con.execute("INSERT INTO runs(run_id, command, sheet_hashes) VALUES(?,?,?)", (run, "run", "{}"))
            for part, spec in _chunks().items():
                c = cid_of(int(part[5:]))
                rows = [("chunk_type", "", spec["type"], None, "")]
                rows += [("axis", a, v if isinstance(v, str) else json.dumps(v, ensure_ascii=False), "value", q)
                         for a, (v, q) in spec["axes"].items()]
                rows += [("answer", qid, a, None, q) for qid, (a, q) in spec["answers"].items()]
                for kind, key, value, status, ev in rows:
                    con.execute("INSERT INTO labels(run_id, chunk_id, kind, key, value, status, evidence, confidence,"
                                " sheet_hashes, prompt_version, model, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                                (run, c, kind, key, value, status, ev, 0.9, "{}", "p1", "mock", APPLIED))
        con.execute("INSERT INTO gen_questions(qid, chunk_id, axis, value, text) VALUES(?,?,?,?,?)",
                    (GEN_QID, cid_of(11), DEFECT, "Short", "본문이 Short를 뒷받침하는가"))
        if corrections:
            for run in runs:
                for c, kind, key, hv, rc, qh in (run_corrections or {}).get(run, _corrections()):
                    con.execute("INSERT INTO corrections(review_run_id, chunk_id, target_kind, target_key, human_value,"
                                " bot_value, review_status, recheck, text_hash, question_hash, applied_at)"
                                " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                                (run, c, kind, key, json.dumps(hv, ensure_ascii=False), None, "corrected", rc,
                                 texts[c], qh, APPLIED))
                    items, reason = evid.get((c, kind, key), (None, None))
                    if items is not None or reason is not None:
                        con.execute("UPDATE corrections SET evidence=?, reason=?, evidence_dropped=0 WHERE rowid=?",
                                    (json.dumps(items, ensure_ascii=False) if items is not None else None, reason,
                                     con.execute("SELECT last_insert_rowid()").fetchone()[0]))
        con.execute("INSERT INTO candidates(run_id, kind, content, axis, source) VALUES(?,?,?,?,?)",
                    (RUN, "synonym", "단락|Short", "", "review"))
        con.execute("INSERT INTO candidates(run_id, kind, content, axis, source) VALUES(?,?,?,?,?)",
                    (RUN, "synonym", "모름|없는표준값", "", "review"))
        con.execute("INSERT INTO candidates(run_id, kind, content, axis, source) VALUES(?,?,?,?,?)",
                    (RUN, "synonym", "봇후보|Short", "", "bot"))
        for n in (1, 2):
            con.execute("INSERT INTO revisit_requests(review_run_id, chunk_id, target_kind, target_key, reason, memo,"
                        " proposed_value) VALUES(?,?,?,?,?,?,?)",
                        (RUN, cid_of(n), "axis", DEFECT, "NEW_VALUE", MEMO, MEMO))
        con.commit()
    finally:
        con.close()
    return root


def _pol(**ledger_over):
    return policy_mod.validate_policy({"ledger": ledger_over} if ledger_over else {})


def _read_all(d):
    out = {}
    for fn in sorted(os.listdir(d)):
        with open(os.path.join(d, fn), "rb") as f:
            out[fn] = f.read()
    return out


class LedgerTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="domain_engrbot_ledger_")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def ws(self, name="ws1", **kw):
        return build_ws(self.tmp, name, **kw)

    def shared(self, root=None):
        """임시 폴더를 workspaces/로 보게 해서 작업 폴더 여럿이 장부 하나(<임시>/_domain_engrbot/ledger)를 쓰게 한다."""
        root = root or self.tmp
        p = mock.patch.object(ledger, "WORKSPACES_DIR", root)
        p.start()
        self.addCleanup(p.stop)
        return os.path.join(root, "_domain_engrbot", "ledger")


class LedgerDirTest(LedgerTestBase):
    def test_policy_dir(self):
        """상대 경로는 workspaces/ 기준이다. 절대 경로는 workspaces/ 아래나 <작업 폴더>/qa/ 아래만 된다."""
        wsd = os.path.join(CODE_ROOT, "workspaces")
        self.assertEqual(ledger.ledger_dir(self.tmp, _pol(dir="led/x")), os.path.join(wsd, "led", "x"))
        self.assertEqual(ledger.ledger_dir(self.tmp, _pol(dir=os.path.join(wsd, "_domain_engrbot", "l2"))),
                         os.path.join(wsd, "_domain_engrbot", "l2"))
        inqa = os.path.join(self.tmp, "qa", "shared")
        self.assertEqual(ledger.ledger_dir(self.tmp, _pol(dir=inqa)), os.path.abspath(inqa))
        for bad in ("../outside", os.path.join(self.tmp, "shared"), os.path.join(CODE_ROOT, "domain_engrbot", "x"), "..",
                    os.path.join(self.tmp, "qa", "..", "x")):
            with self.assertRaises(ledger.LedgerError) as cm:
                ledger.ledger_dir(self.tmp, _pol(dir=bad))
            self.assertEqual(cm.exception.reason_code, "LEDGER_DIR_OUTSIDE_WORKSPACES", bad)

    def test_under_workspaces(self):
        ws = os.path.join(CODE_ROOT, "workspaces", "261004_BEOL_x")
        self.assertEqual(ledger.ledger_dir(ws, _pol()), os.path.join(CODE_ROOT, "workspaces", "_domain_engrbot", "ledger"))

    def test_other(self):
        self.assertEqual(ledger.ledger_dir(self.tmp, _pol()), os.path.join(os.path.abspath(self.tmp), "qa", "ledger"))
        self.assertEqual(ledger.dir_label(ledger.ledger_dir(self.tmp, _pol())), "qa/ledger")

    def test_dir_outside_refused(self):
        ws = self.ws()
        for name in ("rebuild", "intake"):
            with self.assertRaises(ledger.LedgerError) as cm:
                if name == "intake":
                    ledger.intake(ws, _pol(dir="../domain_engrbot/_ledger_test"))
                else:
                    ledger.rebuild(ledger.ledger_dir(ws, _pol(dir="../domain_engrbot/_ledger_test")), _pol())
            self.assertEqual(cm.exception.reason_code, "LEDGER_DIR_OUTSIDE_WORKSPACES")
        self.assertFalse(os.path.exists(os.path.join(CODE_ROOT, "domain_engrbot", "_ledger_test")))


class IntakeTest(LedgerTestBase):
    def setUp(self):
        LedgerTestBase.setUp(self)
        self.root = self.ws()
        self.pol = _pol()
        self.out = ledger.intake(self.root, self.pol)
        self.d = ledger.ledger_dir(self.root, self.pol)

    def cid(self, n):
        return cid_of(n)

    def rows(self, name):
        return io.read_own_jsonl(os.path.join(self.d, name))

    def test_outputs_exist(self):
        for fn in (ledger.SOURCES, ledger.CASES, ledger.RECORDS, ledger.GOLDEN, ledger.EXAMPLES, ledger.SYNONYMS,
                   ledger.REVISITS, ledger.CANDIDATES, ledger.CANDIDATES_MD):
            self.assertTrue(os.path.isfile(os.path.join(self.d, fn)), fn)
        self.assertFalse([fn for fn in os.listdir(self.d) if ".tmp." in fn])
        o = self.out
        self.assertEqual(o["runs"], [RUN])
        self.assertIsNone(o["reason"])
        self.assertTrue(o["changed"])
        self.assertEqual(o["cases"], o["confirmed"] + o["corrected"])
        self.assertGreater(o["corrected"], 0)
        self.assertGreater(o["golden"], 0)
        src = self.rows(ledger.SOURCES)
        self.assertEqual(len(src), 1)
        self.assertEqual(src[0]["source_ws"], "ws1")
        self.assertEqual(src[0]["labeler_runs"], [RUN])
        self.assertTrue(src[0]["corrections_sha"] and src[0]["intake_at"] and src[0]["taxonomy_version"])
        self.assertEqual(src[0]["counts"]["cases"], o["cases"])
        self.assertEqual(o["totals"]["golden"], o["golden"])

    def test_skip_codes(self):
        sk = self.out["skipped"]
        self.assertEqual(sk.get("SKIP_RECHECK"), 1)
        self.assertEqual(sk.get("SKIP_UNDECIDABLE"), 1)
        self.assertEqual(sk.get("SKIP_UNDECIDABLE_IMAGE"), 2)
        self.assertEqual(sk.get("SKIP_NOT_CONTENT"), 1)
        self.assertEqual(sk.get("SKIP_VALUE_UNKNOWN"), 1)
        self.assertEqual(sk.get("SKIP_LONG_QUOTE"), 1)
        recs = {c["record_id"] for c in self.rows(ledger.CASES)}
        for n in (4, 5, 6, 7, 8):
            self.assertNotIn(self.cid(n), recs, n)
        ex = self.rows(ledger.EXAMPLES)
        self.assertFalse([e for e in ex if len(e["quote"]) > 300])
        self.assertIn(self.cid(9), recs, "긴 인용은 예시만 빼고 사례는 남긴다")
        self.assertEqual(sk.get("SKIP_QUESTION_CHANGED"), 1)

    def test_question_changed(self):
        """승인 질문 답 교정의 question_hash가 지금 문장과 다르면 예시만 빼고 사례·골든은 남긴다."""
        cases = {(c["record_id"], c["field"]): c for c in self.rows(ledger.CASES)}
        for n in (12, 13):
            self.assertEqual(cases[(self.cid(n), "answer:" + APPROVED_QID)]["kind"], "corrected")
        ex = {e["record_id"]: e for e in self.rows(ledger.EXAMPLES)
              if e["kind"] == "answer" and e["qid"] == APPROVED_QID}
        self.assertNotIn(self.cid(12), ex)
        self.assertEqual((ex[self.cid(13)]["verdict"], ex[self.cid(13)]["generated"]), ("unsupported", False))
        g = next(g for g in self.rows(ledger.GOLDEN) if g["record_id"] == self.cid(12))
        self.assertEqual(g["labels"]["answers"][APPROVED_QID], "X")

    def test_non_list_bot_value(self):
        """봇 축 값이 목록이 아니면(깨진 JSON) 글자로 쪼개지 않는다."""
        rec = next(r for r in self.rows(ledger.RECORDS) if r["record_id"] == self.cid(15))
        self.assertEqual(rec["removed"], {})
        self.assertEqual(rec["added"], {DEFECT: ["Open"]})
        self.assertEqual(rec["final_axes"][DEFECT], ["Open"])
        self.assertFalse([e for e in self.rows(ledger.EXAMPLES) if e["record_id"] == self.cid(15)
                          and e["axis"] == DEFECT])

    def test_confirmed_expansion(self):
        cs = [c for c in self.rows(ledger.CASES) if c["record_id"] == self.cid(1)]
        fields = sorted(c["field"] for c in cs)
        self.assertEqual(fields, sorted(["axis:" + LAYER, "axis:" + MODULE, "axis:" + DEFECT,
                                         "answer:" + APPROVED_QID, "answer:" + GEN_QID]))
        self.assertTrue(all(c["kind"] == "confirmed" and c["bot_value"] == c["human_value"] for c in cs))
        g = next(g for g in self.rows(ledger.GOLDEN) if g["record_id"] == self.cid(1))
        self.assertEqual(g["labels"]["axes"][LAYER], ["M1"])
        self.assertEqual(g["evidence"]["axis:" + LAYER], "M1 배선 인용")

    def test_field_overrides_confirmed(self):
        cs = {c["field"]: c for c in self.rows(ledger.CASES) if c["record_id"] == self.cid(10)}
        self.assertEqual(cs["axis:" + LAYER]["kind"], "corrected")
        self.assertEqual(cs["axis:" + LAYER]["human_value"], ["M1", "M2"])
        self.assertEqual(cs["axis:" + MODULE]["kind"], "confirmed")
        rec = next(r for r in self.rows(ledger.RECORDS) if r["record_id"] == self.cid(10))
        self.assertEqual(rec["final_axes"][LAYER], ["M1", "M2"])
        self.assertEqual(rec["added"], {LAYER: ["M2"]})
        self.assertEqual(rec["title_hits"], {LAYER: ["M2"]})
        g = next(g for g in self.rows(ledger.GOLDEN) if g["record_id"] == self.cid(10))
        self.assertNotIn("axis:" + LAYER, g["evidence"], "교정 필드에는 인용을 넣지 않는다")
        self.assertIn("axis:" + MODULE, g["evidence"])

    def test_removed_and_examples(self):
        rec = next(r for r in self.rows(ledger.RECORDS) if r["record_id"] == self.cid(2))
        self.assertEqual(rec["removed"], {DEFECT: ["Open"]})
        self.assertEqual(rec["corrected_axes"], [DEFECT])
        ex = [e for e in self.rows(ledger.EXAMPLES) if e["record_id"] == self.cid(2) and e["axis"] == DEFECT]
        self.assertEqual({(e["value"], e["verdict"]) for e in ex}, {("Open", "unsupported"), ("Short", "supported")})
        self.assertTrue(all(e["origin"] == "corrected" and e["kind"] == "axis" for e in ex))

    def test_qgen(self):
        c = next(c for c in self.rows(ledger.CASES) if c["record_id"] == self.cid(11) and c["field"] == "answer:" + GEN_QID)
        self.assertEqual((c["gen_axis"], c["gen_value"], c["kind"]), (DEFECT, "Short", "corrected"))
        appr = next(c for c in self.rows(ledger.CASES) if c["record_id"] == self.cid(1)
                    and c["field"] == "answer:" + APPROVED_QID)
        self.assertEqual((appr["gen_axis"], appr["gen_value"]), (None, None))
        ex = [e for e in self.rows(ledger.EXAMPLES) if e["record_id"] == self.cid(11)]
        self.assertEqual(len(ex), 1)
        e = ex[0]
        self.assertEqual((e["kind"], e["generated"], e["axis"], e["value"], e["qid"], e["answer"], e["verdict"]),
                         ("answer", True, DEFECT, "Short", GEN_QID, "O", "unsupported"))
        conf = [e for e in self.rows(ledger.EXAMPLES) if e["record_id"] == self.cid(1) and e["kind"] == "answer"]
        self.assertTrue(conf and all(e["verdict"] == "supported" for e in conf))

    def test_no_evidence_is_unchanged(self):
        """근거 열이 없는 작업 DB와 근거 열이 비어 있는 작업 DB의 장부는 바이트가 같고, evidence.jsonl을 만들지 않는다."""
        outs = {}
        for name, ev in (("old", None), ("empty", {})):
            os.makedirs(os.path.join(self.tmp, name))
            root = build_ws(os.path.join(self.tmp, name), "wsx", evidence=ev)
            out = ledger.intake(root, self.pol)
            d = ledger.ledger_dir(root, self.pol)
            self.assertEqual(out["evidence"], 0)
            self.assertFalse(os.path.exists(os.path.join(d, ledger.EVIDENCE)))
            self.assertFalse([c for c in io.read_own_jsonl(os.path.join(d, ledger.CASES))
                              if "evidence_sources" in c or "has_reason" in c])
            outs[name] = {fn: data for fn, data in _read_all(d).items()
                          if fn in (ledger.CASES, ledger.RECORDS, ledger.GOLDEN, ledger.EXAMPLES)}
        self.assertEqual(outs["old"], outs["empty"])

    def test_idempotent(self):
        before = _read_all(self.d)
        again = ledger.intake(self.root, self.pol)
        self.assertFalse(again["changed"])
        self.assertEqual(_read_all(self.d), before)
        self.assertEqual({k: v for k, v in again.items() if k != "changed"},
                         {k: v for k, v in self.out.items() if k != "changed"})

    def test_sorted_and_ids(self):
        cases = self.rows(ledger.CASES)
        self.assertEqual([c["case_id"] for c in cases], sorted(c["case_id"] for c in cases))
        for c in cases:
            self.assertEqual(c["case_id"], model.hash_obj([c["source_ws"], c["labeler_run_id"], c["record_id"],
                                                           c["field"]])[:16])
        for g in self.rows(ledger.GOLDEN):
            self.assertEqual(g["golden_id"], model.hash_obj([g["record_id"], g["text_hash"]])[:32])
        ex = self.rows(ledger.EXAMPLES)
        self.assertEqual(len({e["example_id"] for e in ex}), len(ex))

    def test_no_body_or_file_names(self):
        for fn, data in _read_all(self.d).items():
            text = data.decode("utf-8")
            self.assertNotIn(FILE_NAME, text, fn)
            self.assertNotIn(MEMO, text, fn)
            self.assertNotIn(self.tmp, text, fn)
            if fn not in (ledger.GOLDEN, ledger.EXAMPLES):
                self.assertNotIn("인용", text, fn)
            if fn != ledger.EVIDENCE:
                self.assertNotIn(EV_QUOTE, text, fn)
                self.assertNotIn(REASON, text, fn)
            self.assertNotIn(BODY, text, fn)

    def test_evidence_cases(self):
        """cases에는 근거 위치 종류·이유 유무만, 인용·이유는 evidence.jsonl에만 있다."""
        cs = {(c["record_id"], c["field"]): c for c in self.rows(ledger.CASES)}
        c2 = cs[(self.cid(2), "axis:" + DEFECT)]
        self.assertEqual((c2["evidence_sources"], c2["has_reason"]), (["chunk_same", "doc_title"], True))
        c3 = cs[(self.cid(3), "axis:" + DEFECT)]
        self.assertEqual((c3["evidence_sources"], c3["has_reason"]), ([], True))
        c10 = cs[(self.cid(10), "axis:" + LAYER)]
        self.assertEqual((c10["evidence_sources"], c10["has_reason"]), (["chunk_other"], False))
        c13 = cs[(self.cid(13), "answer:" + APPROVED_QID)]
        self.assertEqual(c13["evidence_sources"], ["file_name"])
        # 근거·이유가 없는 사례(확인 확장 포함)에는 키가 없다
        for k in ((self.cid(1), "axis:" + LAYER), (self.cid(10), "axis:" + MODULE), (self.cid(12), "axis:" + LAYER)):
            self.assertNotIn("evidence_sources", cs[k], k)
            self.assertNotIn("has_reason", cs[k], k)
        ev = ledger.read_evidence(self.d)
        self.assertEqual(sorted((e["record_id"], e["field"]) for e in ev),
                         sorted([(self.cid(2), "axis:" + DEFECT), (self.cid(3), "axis:" + DEFECT),
                                 (self.cid(10), "axis:" + LAYER), (self.cid(13), "answer:" + APPROVED_QID)]))
        e2 = next(e for e in ev if e["record_id"] == self.cid(2))
        self.assertEqual(e2["case_id"], c2["case_id"])
        self.assertEqual([(x["source"], x["chunk_id"], x["slide_no"]) for x in e2["evidence"]],
                         [("chunk", self.cid(2), 2), ("doc_title", None, None)])
        self.assertTrue(all(x["quote"].startswith(EV_QUOTE) for x in e2["evidence"]))
        self.assertEqual(e2["reason"], REASON + " 2")
        self.assertEqual(next(e for e in ev if e["record_id"] == self.cid(3))["evidence"], [])
        self.assertEqual(self.out["evidence"], 3)
        self.assertEqual(ledger.status(self.d)["evidence"], 3)
        self.assertNotIn("SKIP_EVIDENCE_INVALID", self.out["skipped"])

    def test_evidence_item_checks(self):
        """버리는 근거 항목: 모르는 source, 빈·긴 인용, chunk_id 없는 chunk, 정수 아닌 slide_no, 3개 초과, JSON 아님."""
        ok = {"source": "doc_title", "quote": "q"}
        bad = [{"source": "web", "quote": "q"}, {"source": "chunk", "quote": "q"}, {"source": "file_name", "quote": " "},
               {"source": "file_name", "quote": "가" * 301}, {"source": "doc_title", "quote": "q", "slide_no": True}, "x"]
        row = {"target_kind": "axis", "evidence": json.dumps([ok] + bad + [ok, ok, ok]), "reason": "  "}
        items, reason, n_bad = ledger._evidence(row, 300)
        self.assertEqual((len(items), reason, n_bad), (3, None, len(bad) + 1))
        self.assertEqual(ledger._evidence({"target_kind": "axis", "evidence": "{깨짐"}, 300), ([], None, 1))
        self.assertEqual(ledger._evidence({"target_kind": "chunk", "evidence": json.dumps([ok]), "reason": "r"}, 300),
                         ([], None, 0))

    def test_synonyms_and_revisits(self):
        syn = self.rows(ledger.SYNONYMS)
        self.assertEqual([(s["alias"], s["canonical"], s["axis"], s["count"], s["sources"]) for s in syn],
                         [("단락", "Short", DEFECT, 1, ["ws1"]), ("모름", "없는표준값", "", 1, ["ws1"])])
        rev = self.rows(ledger.REVISITS)
        self.assertEqual(rev, [{"source_ws": "ws1", "reason": "NEW_VALUE", "target_kind": "axis",
                                "target_key": DEFECT, "count": 2}])
        self.assertEqual(self.out["revisits"], 2)

    def test_golden_to_bundle(self):
        base = labelbot_ws.load(self.root)
        b = golden.to_bundle(io.read_own_jsonl(ledger.golden_path(self.d)), base)
        self.assertTrue(b.records)
        rec = next(r for r in b.records if r["record_id"] == self.cid(1))
        self.assertEqual(rec["axes"][LAYER]["values"], ["M1"])
        self.assertTrue(rec["human_reviewed"])

    def test_candidates(self):
        doc = io.read_own_json(ledger.candidates_path(self.d))
        domain_rules.validate(doc)
        self.assertTrue(doc["version"].startswith("ledger-"))
        rules = doc["rules"]
        self.assertTrue(rules and all(r["status"] == "draft" and r["id"].startswith("cand-") for r in rules))
        self.assertTrue(all(len(r["note"]) <= 300 for r in rules))
        exp = [r for r in rules if r["type"] == "axis_combo" and "expect" in r
               and r["when"] == {"axis": MODULE, "value_in": ["CMP"]} and r["expect"]["axis"] == DEFECT]
        self.assertEqual(len(exp), 1)
        self.assertEqual(exp[0]["expect"]["value_in"], ["Short"])
        forb = [r for r in rules if r["type"] == "axis_combo" and "forbid" in r
                and r["when"] == {"axis": MODULE, "value_in": ["CMP"]}]
        self.assertEqual([r["forbid"] for r in forb], [{"axis": DEFECT, "value_in": ["Open"]}])
        title = [r for r in rules if r["type"] == "title_label"]
        self.assertEqual([r["axis"] for r in title], [LAYER])
        self.assertIn("M2", title[0]["title_pattern"])
        syn = [r for r in rules if r["type"] == "synonym_suggest"]
        self.assertEqual([r["axis"] for r in syn], [DEFECT])
        self.assertTrue(syn[0]["note"].startswith("검수 등록 동의어 1쌍(작업 폴더 1곳). 동의어 시트에 붙여넣은 뒤 효력이 있다."))
        self.assertTrue(title[0]["title_pattern"].startswith("(?i)"))
        self.assertTrue(title[0]["note"].startswith("제목 적중 2건(레코드 2건, 작업 폴더 1곳)."))
        self.assertEqual(ledger.build_candidates(self.d, self.pol), doc)
        with open(os.path.join(self.d, ledger.CANDIDATES_MD), encoding="utf-8") as f:
            md = f.read()
        self.assertIn(exp[0]["id"], md)

    def test_title_case_insensitive(self):
        """(?i) 제목 패턴이 domain_rules 검증과 L4 평가에서 소문자 제목에도 걸린다."""
        from domain_engrbot.checks import l4_domain

        doc = io.read_own_json(ledger.candidates_path(self.d))
        title = [r for r in doc["rules"] if r["type"] == "title_label"]
        rules = domain_rules.validate({"version": "t", "rules": title})
        rec = {"record_id": "r", "chunk_type": "내용", "axes": {LAYER: {"values": ["M1"]}}}
        tax = model.TaxIndex(SNAP)
        sch = policy_mod.validate_schema({})
        hits = l4_domain.evaluate(rec, {"title": "m2 배선 보고"}, rules, tax, sch)
        self.assertEqual([(i["code"], i["evidence"]["value"]) for i in hits], [("L4_RULE_DRAFT_HIT", "M2")])
        self.assertEqual(l4_domain.evaluate(rec, {"title": "am2x 보고"}, rules, tax, sch), [])

    def test_candidate_thresholds(self):
        strict = _pol(candidates={"min_support": 100, "min_forbid": 3, "min_title": 3, "max_rules": 30})
        rules = ledger.build_candidates(self.d, strict)["rules"]
        self.assertEqual([r["type"] for r in rules], ["synonym_suggest"])
        few = ledger.build_candidates(self.d, _pol(candidates={"max_rules": 2}))["rules"]
        self.assertEqual(len(few), 2)
        no_corr = ledger.build_candidates(self.d, _pol(candidates={"min_corrected": 50}))["rules"]
        self.assertFalse([r for r in no_corr if "expect" in r])
        only_tax = ledger.build_candidates(self.d, self.pol, tax_values={LAYER: {"M1"}})["rules"]
        self.assertFalse([r for r in only_tax if r["type"] == "title_label"])

    def test_status_and_rebuild(self):
        st = ledger.status(self.d)
        self.assertEqual((st["sources"], st["dir"]), (1, "qa/ledger"))
        self.assertEqual(st["candidates"], len(io.read_own_json(ledger.candidates_path(self.d))["rules"]))
        self.assertFalse(ledger.rebuild(self.d, self.pol))
        os.remove(os.path.join(self.d, ledger.CANDIDATES_MD))
        self.assertTrue(ledger.rebuild(self.d, self.pol))

    def test_run_filter(self):
        with self.assertRaises(ledger.LedgerError) as cm:
            ledger.intake(self.root, self.pol, labeler_run_id="20990101T000000-0000")
        self.assertEqual(cm.exception.reason_code, "LEDGER_RUN_NO_CORRECTIONS")
        out = ledger.intake(self.root, self.pol, labeler_run_id=RUN)
        self.assertEqual(out["runs"], [RUN])


def _rec(n, ws, fid, final, corrected=(), removed=None):
    return {"source_ws": ws, "labeler_run_id": RUN, "record_id": "r%02d" % n, "file_id": fid,
            "text_hash": "h%02d" % n, "final_axes": final, "corrected_axes": sorted(corrected), "added": {},
            "removed": removed or {}, "title_hits": {}}


def _synthetic(elsewhere=True, one_file=False):
    """축 A·B만 쓰는 records 행. 기대 후보 2개(a1→b1: 작업 폴더 1곳, a2→b2: 2곳)와 금지 후보 1개(a2 금지 b3)."""
    f = (lambda k: "f1") if one_file else (lambda k: "f%d" % k)
    rows = [_rec(1, "wsA", f(1), {"A": ["a1"], "B": ["b1"]}, corrected=["B"]),
            _rec(2, "wsA", f(2), {"A": ["a1"], "B": ["b1"]}),
            _rec(3, "wsA", f(1), {"A": ["a1"], "B": ["b1"]}),
            _rec(4, "wsA", f(3), {"A": ["a2"], "B": ["b2"]}, corrected=["B"], removed={"B": ["b3"]}),
            _rec(5, "wsB", f(4), {"A": ["a2"], "B": ["b2"]}, corrected=["B"], removed={"B": ["b3"]}),
            _rec(6, "wsB", f(5), {"A": ["a2"], "B": ["b2"]})]
    if elsewhere:
        rows.append(_rec(7, "wsC", f(6), {"A": ["a3"], "B": ["b3"]}))
    return rows


class CandidateRulesTest(LedgerTestBase):
    def build(self, rows, **cand):
        d = os.path.join(self.tmp, "led")
        os.makedirs(d, exist_ok=True)
        io.write_jsonl(os.path.join(d, ledger.RECORDS), rows)
        doc = ledger.build_candidates(d, _pol(candidates=cand) if cand else _pol())
        domain_rules.validate(doc)
        return doc["rules"]

    @staticmethod
    def sig(r):
        c = r.get("expect") or r.get("forbid")
        return ("expect" if "expect" in r else "forbid", r["when"]["value_in"][0], c["value_in"])

    def test_order_and_support(self):
        rules = self.build(_synthetic())
        self.assertEqual([self.sig(r) for r in rules],
                         [("expect", "a2", ["b2"]), ("forbid", "a2", ["b3"]), ("expect", "a1", ["b1"])])
        forb = rules[1]
        self.assertTrue(forb["note"].startswith("사람이 뺀 레코드 2건(모수 3, 작업 폴더 2곳)."))
        self.assertTrue(rules[0]["note"].startswith("지지 3/3건(작업 폴더 2곳), 근거 교정 2건."))
        self.assertTrue(rules[2]["note"].startswith("지지 3/3건(작업 폴더 1곳), 근거 교정 1건."))

    def test_forbid_needs_elsewhere(self):
        rules = self.build(_synthetic(elsewhere=False))
        self.assertFalse([r for r in rules if "forbid" in r], "R 밖에서도 맞지 않는 값은 무조건 금지라 후보가 아니다")
        self.assertEqual(len([r for r in rules if "expect" in r]), 2)

    def test_forbid_min_count(self):
        rules = self.build(_synthetic(), min_forbid=3)
        self.assertFalse([r for r in rules if "forbid" in r])

    def test_lift(self):
        """어디서나 흔한 값(bc)은 lift가 0이라 expect 값에서 빠진다. min_lift=0이면 남는다."""
        rows = _synthetic()
        for r in rows:
            r["final_axes"]["B"] = r["final_axes"]["B"] + ["bc"]

        def a1(rules):
            return [r["expect"]["value_in"] for r in rules if "expect" in r and r["when"]["value_in"] == ["a1"]]

        self.assertEqual(a1(self.build(rows)), [["b1"]])
        self.assertEqual(a1(self.build(rows, min_lift=0)), [["b1", "bc"]])

    def test_min_files(self):
        self.assertEqual(self.build(_synthetic(one_file=True)), [])
        rules = self.build(_synthetic(one_file=True), min_files=1)
        self.assertEqual(len(rules), 3)


def _swap(rows, n, new_rows):
    """기본 교정 행에서 chunk n의 행을 new_rows로 바꾼다."""
    cid = cid_of(n)
    return [r for r in rows if r[0] != cid] + [(cid,) + tuple(x) + (None,) for x in new_rows]


class MultiWorkspaceTest(LedgerTestBase):
    def _file(self, d, name):
        with open(os.path.join(d, name), "rb") as f:
            return f.read()

    def test_replace_only_source(self):
        shared = self.shared()
        pol = _pol()
        w1 = self.ws("ws1")
        w2 = self.ws("ws2", runs=(RUN, RUN2))
        self.assertEqual(ledger.ledger_dir(w1, pol), shared)
        ledger.intake(w1, pol)
        out2 = ledger.intake(w2, pol)
        self.assertEqual(out2["runs"], [RUN, RUN2])
        cases = io.read_own_jsonl(os.path.join(shared, ledger.CASES))
        w1_rows = [c for c in cases if c["source_ws"] == "ws1"]
        self.assertTrue(w1_rows and [c for c in cases if c["source_ws"] == "ws2"])
        gold = ledger.read_golden(shared)
        self.assertEqual(len({g["golden_id"] for g in gold}), len(gold))
        self.assertTrue(all(g["labeler_run_id"] == RUN2 for g in gold), "labeler_run_id가 큰 쪽이 이긴다")
        raw = io.read_own_jsonl(ledger.golden_path(shared))
        self.assertEqual({g["source_ws"] for g in raw}, {"ws1", "ws2"}, "행은 작업 폴더별로 둔다")
        self.assertEqual(ledger.status(shared)["golden"], len(gold), "누적 골든은 고유 ID 수다")
        syn = {(s["alias"], s["canonical"]): s for s in io.read_own_jsonl(os.path.join(shared, ledger.SYNONYMS))}
        self.assertEqual(syn[("단락", "Short")]["sources"], ["ws1", "ws2"])
        self.assertEqual(syn[("단락", "Short")]["count"], 2)
        # ws2의 교정을 모두 지우면 ws2 행만 빠진다(NO_CORRECTIONS)
        con = sqlite3.connect(os.path.join(w2, "work.sqlite"))
        con.execute("DELETE FROM corrections")
        con.commit()
        con.close()
        out = ledger.intake(w2, pol)
        self.assertEqual(out["reason"], "NO_CORRECTIONS")
        self.assertTrue(out["changed"])
        again = ledger.intake(w2, pol)
        self.assertFalse(again["changed"])
        after = io.read_own_jsonl(os.path.join(shared, ledger.CASES))
        self.assertEqual(after, w1_rows)
        self.assertEqual([s["source_ws"] for s in io.read_own_jsonl(os.path.join(shared, ledger.SOURCES))], ["ws1"])
        syn = {(s["alias"], s["canonical"]): s for s in io.read_own_jsonl(os.path.join(shared, ledger.SYNONYMS))}
        self.assertEqual(syn[("단락", "Short")]["sources"], ["ws1"])
        self.assertFalse([r for r in io.read_own_jsonl(os.path.join(shared, ledger.REVISITS))
                          if r["source_ws"] == "ws2"])

    def test_overlap_then_clear_restores(self):
        """ws1·ws2가 같은 레코드를 갖다가 ws2를 지우면, ws1 골든·예시가 ws1만 넣었을 때와 바이트까지 같다."""
        alone_root = os.path.join(self.tmp, "alone")
        both_root = os.path.join(self.tmp, "both")
        os.makedirs(alone_root)
        os.makedirs(both_root)
        pol = _pol()
        with mock.patch.object(ledger, "WORKSPACES_DIR", alone_root):
            ledger.intake(build_ws(alone_root, "ws1"), pol)
        alone = os.path.join(alone_root, "_domain_engrbot", "ledger")
        with mock.patch.object(ledger, "WORKSPACES_DIR", both_root):
            w1 = build_ws(both_root, "ws1")
            w2 = build_ws(both_root, "ws2", runs=(RUN2,))
            ledger.intake(w1, pol)
            ledger.intake(w2, pol)
            both = os.path.join(both_root, "_domain_engrbot", "ledger")
            self.assertTrue(all(e["source_ws"] == "ws2" for e in ledger.read_examples(both)))
            con = sqlite3.connect(os.path.join(w2, "work.sqlite"))
            con.execute("DELETE FROM corrections")
            con.commit()
            con.close()
            ledger.intake(w2, pol)
        for name in (ledger.GOLDEN, ledger.EXAMPLES, ledger.CASES, ledger.RECORDS, ledger.EVIDENCE):
            self.assertEqual(self._file(both, name), self._file(alone, name), name)

    def test_latest_verdict_wins(self):
        """example_id에는 판정이 없다. 두 실행의 사람 판정이 다르면 최근 실행의 판정을 읽는다."""
        d = self.shared()
        rows2 = _swap(_corrections(), 2, [("chunk", "status", "confirmed", 0)])
        w = self.ws("ws1", runs=(RUN, RUN2), run_corrections={RUN2: rows2})
        ledger.intake(w, _pol())

        def open_ex(rows):
            return [e for e in rows if e["record_id"] == cid_of(2) and e.get("value") == "Open"]

        raw = open_ex(io.read_own_jsonl(ledger.examples_path(d)))
        self.assertEqual(sorted((e["labeler_run_id"], e["verdict"]) for e in raw),
                         [(RUN, "unsupported"), (RUN2, "supported")])
        got = open_ex(ledger.read_examples(d))
        self.assertEqual([(e["labeler_run_id"], e["verdict"]) for e in got], [(RUN2, "supported")])

    def test_run_filter_replaces_only_that_run(self):
        d = self.shared()
        pol = _pol()
        w = self.ws("ws1", runs=(RUN, RUN2))
        ledger.intake(w, pol)

        def rows_of(name, run):
            return [r for r in io.read_own_jsonl(os.path.join(d, name)) if r["labeler_run_id"] == run]

        before = {name: rows_of(name, RUN) for name in (ledger.CASES, ledger.RECORDS, ledger.GOLDEN, ledger.EXAMPLES,
                                                        ledger.EVIDENCE)}
        syn_before = io.read_own_jsonl(os.path.join(d, ledger.SYNONYMS))
        rev_before = io.read_own_jsonl(os.path.join(d, ledger.REVISITS))
        con = sqlite3.connect(os.path.join(w, "work.sqlite"))
        con.execute("DELETE FROM corrections WHERE review_run_id=? AND chunk_id=?", (RUN2, cid_of(2)))
        con.commit()
        con.close()
        out = ledger.intake(w, pol, labeler_run_id=RUN2)
        self.assertEqual(out["runs"], [RUN2])
        for name, rows in before.items():
            self.assertEqual(rows_of(name, RUN), rows, name)
        self.assertFalse([c for c in rows_of(ledger.CASES, RUN2) if c["record_id"] == cid_of(2)])
        self.assertTrue([c for c in rows_of(ledger.CASES, RUN) if c["record_id"] == cid_of(2)])
        self.assertEqual(io.read_own_jsonl(os.path.join(d, ledger.SYNONYMS)), syn_before)
        self.assertEqual(io.read_own_jsonl(os.path.join(d, ledger.REVISITS)), rev_before)
        src = io.read_own_jsonl(os.path.join(d, ledger.SOURCES))[0]
        cases = io.read_own_jsonl(os.path.join(d, ledger.CASES))
        self.assertEqual(src["labeler_runs"], [RUN, RUN2])
        self.assertEqual(src["counts"]["cases"], len(cases))
        self.assertEqual(src["counts"]["corrected"], sum(1 for c in cases if c["kind"] == "corrected"))
        self.assertEqual(set(src["runs"]), {RUN, RUN2})

    def test_changed_corrections_update_intake_at(self):
        shared = self.shared()
        pol = _pol()
        w1 = self.ws("ws1")
        ledger.intake(w1, pol)
        src = io.read_own_jsonl(os.path.join(shared, ledger.SOURCES))[0]
        con = sqlite3.connect(os.path.join(w1, "work.sqlite"))
        con.execute("UPDATE corrections SET applied_at='2026-10-02T00:00:00Z'")
        con.commit()
        con.close()
        with mock.patch.object(model, "now_iso", return_value="2099-01-01T00:00:00Z"):
            ledger.intake(w1, pol)
        src2 = io.read_own_jsonl(os.path.join(shared, ledger.SOURCES))[0]
        self.assertNotEqual(src["corrections_sha"], src2["corrections_sha"])
        self.assertEqual(src2["intake_at"], "2099-01-01T00:00:00Z")


class RobustnessTest(LedgerTestBase):
    def test_lock_busy_and_stale(self):
        root = self.ws()
        d = ledger.ledger_dir(root, _pol())
        os.makedirs(d)
        lock = os.path.join(d, ledger.LOCK_NAME)
        io.write_json(lock, {"pid": 0})
        with mock.patch.object(ledger, "LOCK_WAIT", 0.2):
            with self.assertRaises(ledger.LedgerError) as cm:
                ledger.intake(root, _pol())
        self.assertEqual(cm.exception.reason_code, "LEDGER_LOCKED")
        self.assertFalse(os.path.exists(ledger.golden_path(d)))
        old = os.path.getmtime(lock) - ledger.LOCK_STALE - 10
        os.utime(lock, (old, old))
        out = ledger.intake(root, _pol())
        self.assertGreater(out["cases"], 0)
        self.assertFalse(os.path.exists(lock), "끝나면 잠금을 푼다")

    def test_tmp_name_has_pid(self):
        self.assertTrue(ledger._tmp(os.path.join(self.tmp, "golden.jsonl")).endswith(
            ".%d.tmp.jsonl" % os.getpid()))

    def test_invalid_rows(self):
        d = os.path.join(self.tmp, "qa", "ledger")
        io.write_jsonl(ledger.examples_path(d), [{"example_id": "x"}])
        with self.assertRaises(ledger.LedgerError) as cm:
            ledger.read_examples(d)
        self.assertEqual(cm.exception.reason_code, "LEDGER_FILE_INVALID")
        io.write_text(ledger.golden_path(d), "{깨진\n")
        with self.assertRaises(ledger.LedgerError):
            ledger.read_golden(d)

    def test_schema_content_type(self):
        root = self.ws()
        sch = policy_mod.validate_schema({"content_chunk_type": "표지"})
        out = ledger.intake(root, _pol(), schema=sch)
        cases = io.read_own_jsonl(os.path.join(ledger.ledger_dir(root, _pol()), ledger.CASES))
        self.assertEqual({c["record_id"] for c in cases}, {cid_of(7)})
        self.assertGreater(out["skipped"]["SKIP_NOT_CONTENT"], 1)


class CliTest(LedgerTestBase):
    def _cli(self, *argv):
        buf = std_io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cli.main(list(argv))
        return code, buf.getvalue()

    def test_intake_and_status(self):
        root = self.ws()
        code, out = self._cli("intake", "--workspace", root)
        self.assertEqual(code, 0)
        self.assertIn("[intake] 교정", out)
        self.assertIn("SKIP_RECHECK 1", out)
        self.assertIn("[ledger] 누적 작업 폴더 1", out)
        self.assertIn("근거 있음 3", out)
        code, out2 = self._cli("ledger", "--workspace", root, "status")
        self.assertEqual(code, 0)
        self.assertIn("[ledger] ws1:", out2)
        code, out3 = self._cli("ledger", "--workspace", root, "rebuild")
        self.assertEqual(code, 0)
        for text in (out, out2, out3):
            for bad in (BODY, FILE_NAME, MEMO, self.tmp, "인용", EV_QUOTE, REASON):
                self.assertNotIn(bad, text)

    def test_no_corrections_message(self):
        root = self.ws(corrections=False)
        code, out = self._cli("intake", "--workspace", root)
        self.assertEqual(code, 0)
        self.assertIn("NO_CORRECTIONS: 장부에 이 작업 폴더 행이 없다(그대로).", out)
        self.assertFalse(os.path.exists(os.path.join(root, "qa", "ledger", ledger.SOURCES)))

    def test_codes_does_not_import_ledger(self):
        import subprocess
        import sys

        out_md = os.path.join(self.tmp, "codes.md")
        code = ("import sys; from domain_engrbot import cli; cli.main(['codes', '--out', sys.argv[1]]);"
                " print('domain_engrbot.ledger' in sys.modules)")
        res = subprocess.run([sys.executable, "-c", code, out_md], cwd=CODE_ROOT, capture_output=True, text=True, encoding="utf-8",
                             env=dict(os.environ, PYTHONIOENCODING="utf-8"), timeout=120)
        self.assertEqual(res.stdout.strip().splitlines()[-1], "False")

    def test_error_code(self):
        root = self.ws()
        code, out = self._cli("intake", "--workspace", root, "--run", "20990101T000000-0000")
        self.assertEqual(code, 1)
        self.assertEqual(out.strip(), "[오류] LEDGER_RUN_NO_CORRECTIONS")

    def test_eval_golden_ledger(self):
        root = self.ws()
        self._cli("intake", "--workspace", root)
        code, out = self._cli("eval", "--workspace", root, "--golden", "ledger", "--per-mutator", "1")
        self.assertEqual(code, 0)
        self.assertIn("[eval]", out)


class RunnerTest(LedgerTestBase):
    def test_auto_intake_manifest(self):
        root = self.ws()
        paths = io.QaPaths(root)
        res = runner.run(paths, layers=["L1"], no_judge=True)
        led = res.manifest["ledger"]
        self.assertEqual(led["dir"], "qa/ledger")
        self.assertIsNone(led["intake_error"])
        self.assertGreater(led["intake"]["cases"], 0)
        self.assertEqual(led["intake"]["runs"], 1)
        self.assertNotIn("totals", led["intake"])
        self.assertGreater(led["golden_total"], 0)
        self.assertEqual(led["candidates_loaded"], 0, "L4가 꺼져 있으면 후보를 읽지 않는다")
        self.assertEqual(res.ctx.ledger_dir, ledger.ledger_dir(root, res.policy))
        self.assertIn("examples", res.manifest["judge"])
        self.assertTrue(os.path.isfile(ledger.golden_path(res.ctx.ledger_dir)))

    def test_intake_failure_does_not_stop_run(self):
        root = self.ws()
        paths = io.QaPaths(root)
        with mock.patch.object(ledger, "intake", side_effect=ledger.LedgerError("LEDGER_FILE_INVALID")):
            res = runner.run(paths, layers=["L1"], no_judge=True)
        self.assertEqual(res.manifest["ledger"]["intake_error"], "LEDGER_FILE_INVALID")
        self.assertIsNone(res.manifest["ledger"]["intake"])
        self.assertEqual(res.manifest["counts"]["records"], len(res.verdicts))

    def test_disabled(self):
        root = self.ws()
        paths = io.QaPaths(root)
        io.write_json(paths.policy, {"ledger": {"enabled": False}})
        res = runner.run(paths, layers=["L1"], no_judge=True)
        self.assertNotIn("ledger", res.manifest)
        self.assertIsNone(res.ctx.ledger_dir)
        self.assertFalse(os.path.exists(os.path.join(root, "qa", "ledger")))

    def test_make_judge_sets_examples(self):
        from domain_engrbot import judge as judge_mod

        root = self.ws()
        paths = io.QaPaths(root)
        pol = _pol(judge_examples={"enabled": True, "k_per_item": 3, "max_per_call": 5})
        ledger.intake(root, pol)

        class FakeJudge(object):
            def set_examples(self, rows, k_per_item=2, max_per_call=6):
                self.got = (len(rows), k_per_item, max_per_call)

        b = labelbot_ws.load(root)
        with mock.patch.object(judge_mod, "create", side_effect=lambda *a, **k: FakeJudge()):
            j, skip = runner.make_judge(pol, b, paths)
            self.assertIsNone(skip)
            self.assertEqual(j.got, (len(ledger.read_examples(ledger.ledger_dir(root, pol))), 3, 5))
            self.assertGreater(j.got[0], 0)
            off = _pol(judge_examples={"enabled": False})
            j2, _ = runner.make_judge(off, b, paths)
            self.assertFalse(hasattr(j2, "got"))

    def test_manifest_l4_and_examples(self):
        root = self.ws()
        paths = io.QaPaths(root)
        res = runner.run(paths, layers=["L1", "L3B", "L4"])
        led = res.manifest["ledger"]
        doc = ledger.read_candidates(ledger.ledger_dir(root, res.policy))
        self.assertEqual(led["candidates_version"], doc["version"])
        self.assertEqual(led["candidates_loaded"], len(doc["rules"]))
        self.assertGreater(led["candidates_loaded"], 0)
        ids = sorted(e["example_id"] for e in ledger.read_examples(ledger.ledger_dir(root, res.policy)))
        self.assertEqual(led["examples_sha"], model.hash_obj(ids)[:12])
        self.assertEqual(led["examples_loaded"], len(ids))

    def test_dir_error_does_not_stop_run(self):
        root = self.ws()
        paths = io.QaPaths(root)
        io.write_json(paths.policy, {"ledger": {"dir": "../outside"}})
        res = runner.run(paths, layers=["L1"], no_judge=True)
        led = res.manifest["ledger"]
        self.assertEqual((led["dir"], led["intake_error"]), (None, "LEDGER_DIR_OUTSIDE_WORKSPACES"))
        self.assertIsNone(res.ctx.ledger_dir)
        self.assertEqual(res.manifest["counts"]["records"], len(res.verdicts))

    def test_io_errors_do_not_stop_run(self):
        root = self.ws()
        paths = io.QaPaths(root)
        with mock.patch.object(ledger, "intake", side_effect=sqlite3.OperationalError("x")):
            res = runner.run(paths, layers=["L1"], no_judge=True)
        self.assertEqual(res.manifest["ledger"]["intake_error"], "LEDGER_IO_FAILED")

    def test_make_judge_bad_examples(self):
        from domain_engrbot import judge as judge_mod

        root = self.ws()
        paths = io.QaPaths(root)
        pol = _pol()
        io.write_jsonl(ledger.examples_path(ledger.ledger_dir(root, pol)), [{"example_id": "x"}])

        class FakeJudge(object):
            def set_examples(self, rows, k_per_item=2, max_per_call=6):
                self.got = list(rows)

        logged = []
        with mock.patch.object(judge_mod, "create", side_effect=lambda *a, **k: FakeJudge()):
            j, _ = runner.make_judge(pol, labelbot_ws.load(root), paths, log=lambda *a: logged.append(a))
        self.assertEqual(j.got, [])
        self.assertIn(("ledger", "-", "LEDGER_FILE_INVALID"), logged)

    def test_execute_without_paths(self):
        b = labelbot_ws.load(self.ws())
        res = runner.execute(b, _pol(), policy_mod.validate_schema({}), layers=["L1"])
        self.assertIsNone(res.ctx.ledger_dir)


class PolicyTest(unittest.TestCase):
    def test_defaults(self):
        pol = policy_mod.validate_policy({})
        self.assertEqual(pol["ledger"]["quote_chars"], 300)
        self.assertIsNone(pol["ledger"]["dir"])
        self.assertEqual(policy_mod.validate_policy({"ledger": {"dir": None}})["ledger"]["dir"], None)

    def test_bad_values(self):
        for bad, code in (({"quote_chars": 0}, "OUT_OF_RANGE:ledger.quote_chars"),
                          ({"candidates": {"min_confidence": 1.5}}, "OUT_OF_RANGE:ledger.candidates.min_confidence"),
                          ({"judge_examples": {"k_per_item": 0}}, "OUT_OF_RANGE:ledger.judge_examples.k_per_item"),
                          ({"candidates": {"max_rules": 0}}, "OUT_OF_RANGE:ledger.candidates.max_rules"),
                          ({"candidates": {"min_files": 0}}, "OUT_OF_RANGE:ledger.candidates.min_files"),
                          ({"candidates": {"min_lift": 2}}, "OUT_OF_RANGE:ledger.candidates.min_lift"),
                          ({"dir": 3}, "TYPE_INVALID:ledger.dir"),
                          ({"unknown": 1}, "UNKNOWN_KEY:ledger.unknown"),
                          ({"enabled": "yes"}, "TYPE_INVALID:ledger.enabled")):
            with self.assertRaises(policy_mod.PolicyError) as cm:
                policy_mod.validate_policy({"ledger": bad})
            self.assertIn(code, cm.exception.problems)


if __name__ == "__main__":
    unittest.main()
