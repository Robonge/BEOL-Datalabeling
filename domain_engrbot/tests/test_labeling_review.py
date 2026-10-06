"""승인된 규칙 관리 테스트: 승인 화면(labeling_review.html) 데이터와 결정 JSON 반영(apply), CLI.

새 규칙·사례 후보는 질문 루프에서 다루므로 화면에는 승인된 규칙·사례와 갱신 대기 사례만 있다(plan-question-loop 8.4).
test_labeling_rules와 같은 합성 장부를 코드 폴더 밖 임시 폴더에 만든다. 승인 파일도 임시 경로에 쓴다
(코드 폴더의 taxonomy/labeling_rules.json을 건드리지 않는다). 네트워크·LLM은 쓰지 않는다.
"""
import contextlib
import io as std_io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from domain_engrbot import cli, labeling_review as rv, labeling_rules as lr, ledger
from domain_engrbot.tests.test_ledger import BODY, DEFECT, EV_QUOTE, FILE_NAME, LAYER, MEMO, REASON, _pol, build_ws, cid_of


class LabelingReviewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="domain_engrbot_lreview_")
        cls.root = build_ws(cls.tmp, "ws1")
        cls.pol = _pol()
        ledger.intake(cls.root, cls.pol)
        cls.d = ledger.ledger_dir(cls.root, cls.pol)
        cls.cfg = lr.config(cls.pol)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="domain_engrbot_lreview_out_")
        self.addCleanup(shutil.rmtree, self.out, True)
        self.path = os.path.join(self.out, "labeling_rules.json")
        self._clear_log()

    def _clear_log(self):
        log = os.path.join(self.d, rv.LOG)
        if os.path.isfile(log):
            os.remove(log)

    def _digest(self):
        return rv.data(self.d, self.cfg, self.path)["digest"]

    def _decisions(self, decisions, name="labeling_decisions_t.json", **extra):
        """결정 파일. digest를 따로 주지 않으면 지금 화면의 digest를 넣는다."""
        p = os.path.join(self.out, name)
        extra.setdefault("digest", self._digest())
        doc = dict({"kind": rv.DECISIONS_KIND, "version": 1, "decisions": decisions}, **extra)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)
        return p

    def _cands(self):
        return lr.candidates(self.d, lr.load_rules(self.path), self.cfg)

    def _log(self):
        return ledger.io.read_own_jsonl(os.path.join(self.d, rv.LOG))

    def _refused(self, p, code):
        before = lr.load_rules(self.path)
        with self.assertRaises(rv.ReviewError) as cm:
            rv.apply(self.d, self.cfg, p, self.path)
        self.assertEqual(cm.exception.reason_code, code)
        self.assertEqual(lr.load_rules(self.path), before, "파일 단위 거부는 아무것도 반영하지 않는다")
        self.assertEqual(self._log(), [])

    def _approve(self, ids):
        """승인은 이제 질문 루프(answers.apply)나 CLI(labeling-rules approve)로만 한다. 테스트는 CLI 경로(decide)를 쓴다."""
        lr.decide(self.d, "approve", self.cfg, ids=ids, path=self.path)

    def _stale(self, eid):
        """승인한 사례의 확정 라벨이 장부와 달라진 상태(갱신 대기)를 만든다."""
        self._approve([eid])
        doc = lr.load_rules(self.path)
        ex = [e for e in doc["examples"] if e["example_id"] == eid][0]
        ex["final_axes"] = dict(ex["final_axes"], **{DEFECT: ["Open"]})
        lr.save_rules(doc, self.path)

    # ---- 화면 ---------------------------------------------------------------

    def test_screen_data_and_no_body(self):
        """새 규칙·사례 후보는 화면에 없다(질문 화면에서 다룬다). 승인된 것과 갱신 대기 사례만 있다."""
        obj = rv.build(self.d, self.cfg, self.path)
        self.assertEqual(len(self._cands()["rules"]), 3)
        self.assertEqual((obj["pending_rules"], obj["pending_examples"], obj["approved_rules"]), ([], [], []))
        self.assertEqual(obj["digest"], rv.data(self.d, self.cfg, self.path)["digest"])
        with open(os.path.join(self.d, rv.SCREEN), encoding="utf-8") as f:
            html = f.read()
        self.assertNotIn(rv.screen.DATA_MARK, html)
        self.assertIn(obj["digest"], html)
        for bad in (BODY, FILE_NAME, MEMO, "http"):
            self.assertNotIn(bad, html)
        self.assertIn("규칙 문장에 본문을 붙여 넣지 마세요", html)
        self.assertIn("<title>승인된 규칙 관리</title>", html)
        self.assertIn("새 규칙·사례 후보는 Domain-Engr-bot 질문 화면에서 다룬다", html)
        for gone in ("규칙 후보", "pendingRuleCard", "DATA.pending_rules"):
            self.assertNotIn(gone, html)
        self.assertIn('var tab = "arules"', html)
        self.assertFalse([fn for fn in os.listdir(self.d) if ".tmp." in fn or fn == ledger.LOCK_NAME])

    def test_screen_shows_evidence(self):
        """승인된 규칙(지지 레코드별)·사례(고친 축별)와 갱신 대기 사례 카드에 근거 위치·슬라이드·인용·이유가 보인다."""
        c = self._cands()
        rules = {(r["kind"], r["target"]): r for r in c["rules"]}
        exs = {e["record_id"]: e for e in c["examples"]}
        rm, add = rules[("REMOVE", DEFECT)]["rule_id"], rules[("ADD", LAYER)]["rule_id"]
        self._approve([rm, add, exs[cid_of(10)]["example_id"]])
        self._stale(exs[cid_of(2)]["example_id"])
        obj = rv.build(self.d, self.cfg, self.path)
        ar = {r["rule_id"]: r for r in obj["approved_rules"]}
        ev = ar[rm]["evidence"]
        self.assertEqual([(v["record_id"], v["field"]) for v in ev], [(cid_of(2), "axis:" + DEFECT)])
        self.assertEqual([(x["kind"], x["slide_no"]) for x in ev[0]["items"]], [("chunk_same", 2), ("doc_title", None)])
        self.assertTrue(all(x["quote"].startswith(EV_QUOTE) for x in ev[0]["items"]))
        self.assertEqual(ev[0]["reason"], REASON + " 2")
        self.assertEqual(ar[rm]["evidence_count"], 1)
        self.assertEqual([(x["kind"], x["slide_no"]) for x in ar[add]["evidence"][0]["items"]], [("chunk_other", 12)])
        self.assertEqual([e["record_id"] for e in obj["approved_examples"]], [cid_of(10)])
        self.assertEqual(sorted(obj["approved_examples"][0]["evidence"]), [LAYER])
        # 갱신 대기 사례는 승인된 사례 목록에서 빠지고 pending_examples(갱신 대기)에만 있다
        self.assertEqual([(e["record_id"], e["update"]) for e in obj["pending_examples"]], [(cid_of(2), True)])
        self.assertEqual(obj["pending_examples"][0]["evidence"][DEFECT]["reason"], REASON + " 2")
        with open(os.path.join(self.d, rv.SCREEN), encoding="utf-8") as f:
            html = f.read()
        self.assertIn(EV_QUOTE, html)
        self.assertIn(REASON, html)
        self.assertIn("갱신 대기", html)

    # ---- 결정 반영 ----------------------------------------------------------

    def test_apply_exception_before_save_keeps_file(self):
        """apply 도중(저장 직전) 예외가 나면 승인 파일은 원래 내용 그대로이고, 결정 로그에 OK가 없다. 잠금도 풀린다."""
        r1, r2, r3 = [r["rule_id"] for r in self._cands()["rules"]]
        self._approve([r1, r2, r3])
        with open(self.path, encoding="utf-8") as f:
            raw_before = f.read()
        p = self._decisions([{"id": r1, "action": "edit", "text": "고친 문장이다."},
                             {"id": r2, "action": "disable"}, {"id": r3, "action": "reject"}], name="d2.json")
        with mock.patch.object(lr, "save_rules", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                rv.apply(self.d, self.cfg, p, self.path)
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(f.read(), raw_before)
        self.assertNotIn("OK", [x["result"] for x in self._log() if x["id"] in (r1, r2, r3)])
        self.assertFalse(os.path.exists(os.path.join(self.d, ledger.LOCK_NAME)))

    def test_apply_manage_approved(self):
        """승인된 규칙·사례: 끄기 + 문장 수정, 문장 수정만, 켜기, 승인 취소. 결정 이력에는 ID·동작·결과만 남는다."""
        c = self._cands()
        r1, r2, r3 = [r["rule_id"] for r in c["rules"]]
        eid = c["examples"][0]["example_id"]
        self._approve([r1, r2, eid])
        p = self._decisions([{"id": r1, "action": "disable", "text": "  사람이 고친\n규칙 문장이다.  "},
                             {"id": eid, "action": "disable"},
                             {"id": r2, "action": "edit", "text": "두 번째 규칙 문장이다."}])
        res = rv.apply(self.d, self.cfg, p, self.path)
        self.assertEqual((res["disabled"], res["edited"], res["approved_rules"]), (2, 2, 0))
        doc = lr.load_rules(self.path)
        rule = [r for r in doc["rules"] if r["rule_id"] == r1][0]
        self.assertEqual((rule["enabled"], rule["text"], rule["edited_by"]), (False, "사람이 고친 규칙 문장이다.", "screen"))
        self.assertFalse([e for e in doc["examples"] if e["example_id"] == eid][0]["enabled"])
        # 고르지 않은 후보(r3)는 화면에 없고 승인 파일에도 없다(질문 루프에서 다룬다)
        self.assertNotIn(r3, [r["rule_id"] for r in doc["rules"]] + doc["rejected"])
        p = self._decisions([{"id": r1, "action": "enable"}, {"id": eid, "action": "reject"}], name="d2.json")
        res = rv.apply(self.d, self.cfg, p, self.path)
        self.assertEqual((res["enabled"], res["rejected_examples"]), (1, 1))
        rv.apply(self.d, self.cfg, self._decisions([{"id": r1, "action": "reject"}], name="d3.json"), self.path)
        doc = lr.load_rules(self.path)
        self.assertNotIn(r1, [r["rule_id"] for r in doc["rules"]])
        self.assertIn(r1, doc["rejected"])
        self.assertIn(eid, doc["rejected_examples"])
        rows = self._log()
        self.assertEqual([(x["id"], x["action"], x["result"]) for x in rows][:3],
                         [(r1, "disable", "OK"), (eid, "disable", "OK"), (r2, "edit", "OK")])
        self.assertFalse([x for x in rows if "text" in x])
        # 승인 파일·결정 이력·후보 파일에는 본문·근거 인용·이유가 없다
        for fn in (self.path, os.path.join(self.d, rv.LOG), os.path.join(self.d, lr.CANDIDATES),
                   os.path.join(self.d, lr.CANDIDATES_MD)):
            with open(fn, encoding="utf-8") as f:
                t = f.read()
            for bad in (BODY, FILE_NAME, MEMO, EV_QUOTE, REASON):
                self.assertNotIn(bad, t, fn)

    def test_apply_updating_example(self):
        """갱신 대기 사례는 승인(갱신)하면 장부의 확정 라벨로 바뀌고, 기각하면 사례에서 빠진다. 켜기·끄기는 받지 않는다."""
        e1, e2 = [e["example_id"] for e in self._cands()["examples"]]
        self._stale(e1)
        self._stale(e2)
        self._refused(self._decisions([{"id": e1, "action": "disable"}]), "DECISIONS_ID_NOT_ON_SCREEN")
        res = rv.apply(self.d, self.cfg, self._decisions([{"id": e1, "action": "approve"},
                                                          {"id": e2, "action": "reject"}]), self.path)
        self.assertEqual((res["approved_examples"], res["rejected_examples"]), (1, 1))
        doc = lr.load_rules(self.path)
        got = [e for e in doc["examples"] if e["example_id"] == e1][0]
        self.assertEqual(got["final_axes"], lr.all_examples(self.d, lr._latest_cases(self.d))[e1]["final_axes"])
        self.assertEqual(doc["rejected_examples"], [e2])
        self.assertEqual(rv.data(self.d, self.cfg, self.path)["pending_examples"], [])

    def test_invalid_text_is_not_applied(self):
        rid = self._cands()["rules"][0]["rule_id"]
        self._approve([rid])
        before = lr.load_rules(self.path)
        for bad in ("가" * (lr.TEXT_MAX + 1), "   ", "규칙 {{body}} 문장", "규칙 }} 문장", "규칙‮문장",
                    "규칙​문장", "규칙\x00문장", "규칙\x1f문장"):
            res = rv.apply(self.d, self.cfg, self._decisions([{"id": rid, "action": "disable", "text": bad}]),
                           self.path)
            self.assertEqual(res["invalid_text"], [rid], repr(bad))
            self.assertEqual((res["disabled"], res["edited"]), (0, 0))
            self.assertEqual(lr.load_rules(self.path), before)
        # 줄바꿈·탭은 공백으로 바꿔 받는다
        self.assertEqual(rv._clean_text("가\t나\r\n다"), "가 나 다")

    def test_stale_digest_refused(self):
        rid = self._cands()["rules"][0]["rule_id"]
        self._approve([rid])
        for digest in ("0000000000000000", None, ""):
            self._refused(self._decisions([{"id": rid, "action": "disable"}], digest=digest), "DECISIONS_STALE")
        p = os.path.join(self.out, "nodigest.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"kind": rv.DECISIONS_KIND, "decisions": [{"id": rid, "action": "disable"}]}, f)
        self._refused(p, "DECISIONS_STALE")
        # 화면 이후 승인 상태가 바뀌면 그 전 화면의 결정 파일은 거부된다
        old = self._decisions([{"id": rid, "action": "disable"}], name="old.json")
        rv.apply(self.d, self.cfg, self._decisions([{"id": rid, "action": "reject"}], name="now.json"), self.path)
        self._clear_log()
        self._refused(old, "DECISIONS_STALE")

    def test_id_not_on_screen_refused(self):
        """새 규칙·사례 후보는 화면에 없으므로 승인·기각을 받지 않는다(질문 루프에서 다룬다)."""
        c = self._cands()
        r1, r2 = c["rules"][0]["rule_id"], c["rules"][1]["rule_id"]
        eid = c["examples"][0]["example_id"]
        for bad in ([{"id": "FR-nothere", "action": "reject"}],
                    [{"id": r1, "action": "approve"}],                        # 새 규칙 후보
                    [{"id": r1, "action": "reject"}],
                    [{"id": eid, "action": "approve"}],                       # 새 사례 후보(갱신 아님)
                    [{"id": r1, "action": "enable"}],
                    [{"id": r1, "action": "edit", "text": "문장이다."}],
                    [{"id": eid, "action": "disable"}]):
            self._refused(self._decisions(bad), "DECISIONS_ID_NOT_ON_SCREEN")
        # 승인된 규칙은 다시 승인할 수 없다(화면에 승인 버튼이 없다)
        self._approve([r1, r2])
        self._refused(self._decisions([{"id": r1, "action": "approve"}]), "DECISIONS_ID_NOT_ON_SCREEN")
        # 기각한 규칙은 화면에 없다
        rv.apply(self.d, self.cfg, self._decisions([{"id": r2, "action": "reject"}]), self.path)
        self._clear_log()
        self._refused(self._decisions([{"id": r2, "action": "reject"}]), "DECISIONS_ID_NOT_ON_SCREEN")

    def test_size_and_depth(self):
        p = os.path.join(self.out, "big.json")
        with open(p, "w", encoding="utf-8") as f:
            f.write(" " * (rv.MAX_BYTES + 1))
        self._refused(p, "DECISIONS_TOO_LARGE")
        with mock.patch.object(rv.io, "read_json_input", side_effect=AssertionError("읽으면 안 된다")):
            with self.assertRaises(rv.ReviewError) as cm:
                rv.read_decisions(p)
        self.assertEqual(cm.exception.reason_code, "DECISIONS_TOO_LARGE")
        deep = os.path.join(self.out, "deep.json")
        with open(deep, "w", encoding="utf-8") as f:
            f.write("[" * 200000 + "]" * 200000)
        self._refused(deep, "DECISIONS_JSON_INVALID")

    def test_format_errors(self):
        for doc, code in (({"kind": "x", "decisions": []}, "DECISIONS_FORMAT_INVALID"),
                          ({"kind": rv.DECISIONS_KIND, "decisions": [{"id": "FR-1", "action": "delete"}]},
                           "DECISIONS_FORMAT_INVALID"),
                          ({"kind": rv.DECISIONS_KIND, "decisions": [{"id": "FR-1\n", "action": "approve"}]},
                           "DECISIONS_FORMAT_INVALID"),
                          ({"kind": rv.DECISIONS_KIND, "decisions": [{"id": "FR-1", "action": "approve"},
                                                                    {"id": "FR-1", "action": "reject"}]},
                           "DECISIONS_DUPLICATE_ID")):
            with self.assertRaises(rv.ReviewError) as cm:
                rv.parse(doc)
            self.assertEqual(cm.exception.reason_code, code)
        p = os.path.join(self.out, "bad.json")
        with open(p, "w", encoding="utf-8") as f:
            f.write("{not json")
        self._refused(p, "DECISIONS_JSON_INVALID")

    # ---- CLI -------------------------------------------------------------

    def _cli(self, *argv):
        buf = std_io.StringIO()
        with mock.patch.object(lr, "RULES_PATH", self.path), contextlib.redirect_stdout(buf):
            code = cli.main(["labeling-rules"] + list(argv) + ["--workspace", self.root])
        return code, buf.getvalue()

    def test_cli(self):
        code, out = self._cli("review")
        self.assertEqual(code, 0)
        self.assertIn("[labeling-rules] 승인된 규칙 관리 화면: 승인 규칙 0개, 승인 사례 0개, 갱신 대기 사례 0개", out)
        self.assertIn(rv.SCREEN, out)
        for bad in (EV_QUOTE, REASON, BODY):
            self.assertNotIn(bad, out)
        self.assertEqual(self._cli("apply")[0], 2)
        self.assertEqual(self._cli("apply", "--decisions", os.path.join(self.out, "none.json"))[0], 1)
        # 후보 승인 CLI(approve)는 그대로 남는다
        rid = self._cands()["rules"][0]["rule_id"]
        self.assertEqual(self._cli("approve", "--ids", rid)[0], 0)
        code, out = self._cli("apply", "--decisions", self._decisions([{"id": rid, "action": "disable"}]))
        self.assertEqual(code, 0)
        self.assertIn("끔 1", out)
        self.assertFalse(lr.load_rules(self.path)["rules"][0]["enabled"])
        # 이미 반영한 결정 파일을 다시 주면 화면이 바뀌었으므로 거부(종료 코드 1)
        code, out = self._cli("apply", "--decisions", os.path.join(self.out, "labeling_decisions_t.json"))
        self.assertEqual((code, out.strip()), (1, "[오류] DECISIONS_STALE"))


if __name__ == "__main__":
    unittest.main()
