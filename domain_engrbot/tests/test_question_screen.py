"""질문 화면(question_screen)과 질문 화면 서버(serve.make_question_server·serve_questions) 테스트.

작업 폴더는 test_ledger의 합성 작업 폴더를 코드 폴더 밖 임시 폴더에 만들고, 장부는 <작업 폴더>/qa/ledger,
질문 폴더는 그 형제 <작업 폴더>/qa/questions다. 질문 묶음은 qmodel.save_set으로 직접 만든다. 네트워크·LLM은 쓰지 않는다
(서버는 127.0.0.1 임시 포트, 초안은 가짜 drafter).
"""
import base64
import contextlib
import http.client
import io as std_io
import json
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import unittest
from unittest import mock

from domain_engrbot import io, labeling_rules as lr, ledger, qmodel, question_screen as qs, serve
from domain_engrbot.tests.test_ledger import BODY, DEFECT, EV_QUOTE, FILE_NAME, LAYER, REASON, _pol, build_ws, cid_of

SET_ID = "QS-20261006T010203-ab12"
JPG = b"\xff\xd8\xff\xe0 preview-bytes \xff\xd9"
FREE_MARK = "자유답표식FRQ"


def _question(goal, topic, text, **kw):
    fp = qmodel.fingerprint(goal, topic, text)
    q = {"question_id": qmodel.question_id(fp), "fingerprint": fp, "goal": goal, "topic": qmodel.normalize_topic(topic),
         "text": text, "why": "왜 묻는지 설명", "carried": False, "evidence": [], "patterns": [], "examples": [],
         "revisits": [], "impact": {"records": 0}, "options": []}
    q.update(kw)
    return q


def build_fixture(parent):
    """반환: (작업 폴더, 장부 폴더, 질문 폴더, 질문 묶음). 슬라이드 2에는 미리보기(.b64)를 넣는다."""
    root = build_ws(parent, "ws1")
    con = sqlite3.connect(os.path.join(root, "work.sqlite"))
    try:
        fid, seq, th = con.execute("SELECT file_id, seq, text_hash FROM chunks WHERE chunk_id=?", (cid_of(2),)).fetchone()
        con.execute("INSERT INTO slide_images(chunk_id, file_id, seq, jpg_sha256, rel_file, text_hash) VALUES(?,?,?,?,?,?)",
                    (cid_of(2), fid, seq, "p2", "slide_images/p2.b64", th))
        con.commit()
    finally:
        con.close()
    io.write_text(os.path.join(root, "slide_images", "p2.b64"), base64.b64encode(JPG).decode("ascii"))
    pol = _pol()
    ledger.intake(root, pol)
    d = ledger.ledger_dir(root, pol)
    cases = {(c["record_id"], c["field"]): c["case_id"] for c in ledger.read(d, ledger.CASES)}
    latest = lr._latest_cases(d)
    rules = lr.all_rules(latest, 1)
    fr = next(r["rule_id"] for r in rules.values() if (r["kind"], r["target"], r["from"]) == ("REMOVE", DEFECT, "Open"))
    ex = next(e["example_id"] for e in lr.all_examples(d, latest).values() if e["record_id"] == cid_of(2))
    q1 = _question("labeling", {"type": "axis_value", "axis": DEFECT, "values": ["Open"]}, "Open은 언제 붙이나요?",
                   evidence=[cases[(cid_of(2), "axis:" + DEFECT)], cases[(cid_of(10), "axis:" + LAYER)], "0" * 16],
                   patterns=[fr], examples=[ex], impact={"records": 2},
                   revisits=[{"reason": "NEW_VALUE", "target": "axis", "key": DEFECT, "memo": "재검토 메모", "count": 2}],
                   options=[{"option_id": "A", "label": "Short만 있으면 Open을 붙이지 않는다", "drafts": [
                       {"type": "rule", "stage": "classify", "target": DEFECT, "text": "Open은 단선이 보일 때만 붙인다.",
                        "pattern_id": fr},
                       {"type": "taxonomy", "kind": "value_def", "axis": DEFECT, "value": "Open", "definition": "단선 불량"}]},
                            {"option_id": "B", "label": "상황에 따라 다르다", "drafts": []}])
    q2 = _question("taxonomy", {"type": "general"}, "새 축이 필요한가요?", carried=True)
    doc = qmodel.empty_set(workspace="ws1", set_id=SET_ID, now="2026-10-06T00:00:00Z")
    doc["questions"] = [q1, q2]
    qd = qmodel.qdir(d)
    qmodel.save_set(qd, doc)
    return root, d, qd, doc


def screen_data(html):
    m = re.search(r"const DATA = (.*?);\n\n\(function", html, re.S)
    return json.loads(m.group(1))


class QuestionScreenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="domain_engrbot_qscreen_")
        cls.root, cls.d, cls.qd, cls.doc = build_fixture(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def html(self):
        with open(os.path.join(self.qd, qmodel.SCREEN), encoding="utf-8") as f:
            return f.read()

    def test_data_resolves_evidence_patterns_examples(self):
        obj = qs.data(self.doc, self.d, {"ws1": self.root})
        self.assertEqual((obj["kind"], obj["set_id"], obj["digest"]), (qs.SCREEN_KIND, SET_ID, qmodel.digest(self.doc)))
        self.assertEqual(obj["answers_name"], "engr_answers_%s.json" % SET_ID)
        q1, q2 = obj["questions"]
        self.assertEqual((q1["rank"], q2["rank"], q2["carried"], q1["impact"]), (1, 2, True, {"records": 2}))
        self.assertEqual(q1["evidence_missing"], 1, "장부에 없는 case_id는 뺀다")
        cards = {v["record_id"]: v for v in q1["evidence"]}
        c2 = cards[cid_of(2)]
        self.assertEqual((c2["field"], c2["kind"], c2["bot"], c2["human"]),
                         ("axis:" + DEFECT, "corrected", ["Short", "Open"], ["Short"]))
        self.assertEqual([(x["kind"], x["slide_no"]) for x in c2["items"]], [("chunk_same", 2), ("doc_title", None)])
        self.assertTrue(all(x["quote"].startswith(EV_QUOTE) for x in c2["items"]))
        self.assertEqual(c2["reason"], REASON + " 2")
        self.assertEqual(c2["examples"], self.doc["questions"][0]["examples"], "사례 후보는 그 레코드의 근거 카드에 붙는다")
        self.assertEqual([x["kind"] for x in cards[cid_of(10)]["items"]], ["chunk_other"])
        # 슬라이드 미리보기: 레코드마다 한 번, data URL
        s2 = obj["slides"][c2["slide_key"]]
        self.assertTrue(s2["preview"].startswith("data:image/jpeg;base64,"))
        self.assertEqual(base64.b64decode(s2["preview"].split(",", 1)[1]), JPG)
        self.assertEqual(s2["title"], "주간 보고 2")
        s10 = obj["slides"][cards[cid_of(10)]["slide_key"]]
        self.assertIsNone(s10["preview"])
        self.assertIsInstance(s10["slide_no"], int)
        self.assertEqual(len(obj["slides"]), 2)
        pat = q1["patterns"][0]
        self.assertEqual((pat["kind"], pat["target"], pat["from"], pat["to"], pat["count"]), ("REMOVE", DEFECT, "Open", "", 2))
        self.assertEqual(q1["examples"][0]["record_id"], cid_of(2))
        self.assertEqual(q1["revisits"][0]["memo"], "재검토 메모")
        axes = {a["name"]: a["values"] for a in obj["axes"]}
        self.assertIn("Short", axes[DEFECT])
        self.assertEqual(obj["limits"]["rule_text"], qmodel.RULE_TEXT_MAX)
        self.assertEqual(obj["tax_required"]["overlap"], ["axis", "values"])

    def test_preview_cap(self):
        with mock.patch.object(qs, "PREVIEWS_MAX", 0):
            obj = qs.data(self.doc, self.d, {"ws1": self.root})
        self.assertTrue(all(s["preview"] is None for s in obj["slides"].values()))

    def test_build_writes_screen_and_is_deterministic(self):
        self.assertEqual(qs.build(self.qd, self.d), 2)
        a = self.html()
        self.assertEqual(qs.build(self.qd, self.d, policy={}), 2)
        self.assertEqual(self.html(), a, "같은 입력이면 같은 HTML")
        self.assertNotIn(qs.screen.DATA_MARK, a)
        self.assertEqual(screen_data(a), json.loads(json.dumps(qs.data(self.doc, self.d))))
        self.assertIn(EV_QUOTE, a)
        self.assertIn("data:image/jpeg;base64,", a, "장부 위치에서 작업 폴더를 찾아 미리보기를 넣는다")
        for bad in (BODY, FILE_NAME):
            self.assertNotIn(bad, a, "chunk 본문·파일 이름은 화면에 넣지 않는다")
        self.assertFalse([fn for fn in os.listdir(self.qd) if ".tmp" in fn])

    def test_screen_without_workspace(self):
        gone = os.path.join(self.tmp, "없는_작업폴더")
        self.assertEqual(qs.build(self.qd, self.d, roots={"ws1": gone}), 2)
        obj = screen_data(self.html())
        self.assertEqual(obj["axes"], [])
        self.assertTrue(all(s["preview"] is None for s in obj["slides"].values()))
        self.assertEqual(len(obj["questions"][0]["evidence"]), 2, "근거 카드는 장부만으로 만든다")
        qs.build(self.qd, self.d)

    def test_build_without_set(self):
        empty = os.path.join(self.tmp, "empty_q")
        with self.assertRaises(qs.QuestionScreenError) as cm:
            qs.build(empty, self.d)
        self.assertEqual(cm.exception.reason_code, "QUESTIONS_NOT_FOUND")

    def test_template_and_screen_safety(self):
        qs.build(self.qd, self.d)
        with open(qs.TEMPLATE_PATH, encoding="utf-8") as f:
            tpl = f.read()
        for name, text in (("template", tpl), ("screen", self.html())):
            self.assertIsNone(re.search(r"(?i)http", text), name)
            self.assertNotIn("innerHTML", text, name)
            # localStorage는 try 블록 안에서만 쓴다(마지막 try 이후에 catch가 없어야 한다)
            for m in re.finditer(r"localStorage", text):
                before = text[:m.start()]
                self.assertGreater(before.rfind("try {"), before.rfind("catch("), name)
            # 서버 요청은 상대 주소만
            for m in re.finditer(r"fetch\(\"([^\"]*)\"", text):
                self.assertIn(m.group(1), ("inbox/status", "inbox/engr_answers", "draft"), name)

    def test_tax_fields_come_from_qmodel(self):
        """taxonomy 초안의 칸 표는 qmodel.TAX_FIELDS 한 곳에서 온다(화면에 따로 적은 표가 없다)."""
        obj = qs.data(self.doc, self.d, {"ws1": self.root})
        self.assertEqual(obj["tax_fields"], {k: list(v) for k, v in qmodel.TAX_FIELDS.items()})
        with open(qs.TEMPLATE_PATH, encoding="utf-8") as f:
            tpl = f.read()
        self.assertIsNone(re.search(r"\b(value_add|overlap|new_axis|q_edit)\s*:\s*\[", tpl))
        self.assertIn("TAX_FIELDS = DATA.tax_fields", tpl)
        # 금지 글자 검사는 qmodel과 같은 범위를 \u 이스케이프로 쓴다(실제 문자를 소스에 넣지 않는다)
        self.assertIn(r"\u200b-\u200f\u202a-\u202e\u2066-\u2069", tpl)
        self.assertIsNone(re.search("[\u200b-\u200f\u202a-\u202e\u2066-\u2069]", tpl))

    def test_reopened_flag(self):
        doc = json.loads(json.dumps(self.doc))
        doc["questions"][1]["reopened"] = True
        obj = qs.data(doc, self.d, {"ws1": self.root})
        self.assertEqual([q["reopened"] for q in obj["questions"]], [False, True])

    def test_preview_only_when_text_unchanged(self):
        """검수 뒤 본문이 바뀐 슬라이드(chunk text_hash ≠ 사례 text_hash)는 미리보기를 넣지 않는다."""
        db = os.path.join(self.root, "work.sqlite")
        con = sqlite3.connect(db)
        try:
            con.execute("UPDATE chunks SET text_hash='changed' WHERE chunk_id=?", (cid_of(2),))
            con.execute("UPDATE slide_images SET text_hash='changed' WHERE chunk_id=?", (cid_of(2),))
            con.commit()
            obj = qs.data(self.doc, self.d, {"ws1": self.root})
            self.assertTrue(all(s["preview"] is None for s in obj["slides"].values()))
            self.assertIn("주간 보고 2", [s["title"] for s in obj["slides"].values()], "제목·번호는 그대로 보인다")
        finally:
            th = ledger.read(self.d, ledger.RECORDS)
            orig = next(r["text_hash"] for r in th if r["record_id"] == cid_of(2))
            con.execute("UPDATE chunks SET text_hash=? WHERE chunk_id=?", (orig, cid_of(2)))
            con.execute("UPDATE slide_images SET text_hash=? WHERE chunk_id=?", (orig, cid_of(2)))
            con.commit()
            con.close()
        obj = qs.data(self.doc, self.d, {"ws1": self.root})
        self.assertEqual(sum(1 for s in obj["slides"].values() if s["preview"]), 1)


class _FakeDrafter(object):
    """가짜 초안 콜러블. mode: ok · raise_code · raise_plain · block."""

    def __init__(self):
        self.mode = "ok"
        self.calls = []
        self.entered = threading.Event()
        self.release = threading.Event()

    def __call__(self, question_id, answer_text):
        self.calls.append((question_id, answer_text))
        if self.mode == "raise_code":
            e = RuntimeError("LLM 실패 " + FREE_MARK)
            e.reason_code = "LLM_TIMEOUT"
            raise e
        if self.mode == "raise_plain":
            raise ValueError("본문 " + FREE_MARK)
        if self.mode == "block":
            self.entered.set()
            self.release.wait(10)
        return [{"type": "rule", "stage": "label", "target": "", "text": "  규칙\n문장  ", "extra": 1},
                {"type": "rule", "text": ""},
                {"type": "taxonomy", "kind": "overlap", "axis": DEFECT, "values": ["Short"]},
                "문자열"]


class QuestionServeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="domain_engrbot_qserve_")
        cls.root, cls.d, cls.qd, cls.doc = build_fixture(cls.tmp)
        qs.build(cls.qd, cls.d)
        cls.paths = io.QaPaths(cls.root)
        cls.qid = cls.doc["questions"][0]["question_id"]
        cls.drafter = _FakeDrafter()
        cls.srv = serve.make_question_server(cls.paths, cls.qd, SET_ID, 0, drafter=cls.drafter)
        cls.plain = serve.make_question_server(cls.paths, cls.qd, SET_ID, 0)
        for s in (cls.srv, cls.plain):
            threading.Thread(target=s.serve_forever, daemon=True).start()
        cls.port = cls.srv.server_address[1]

    @classmethod
    def tearDownClass(cls):
        for s in (cls.srv, cls.plain):
            s.shutdown()
            s.server_close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        for fn in os.listdir(self.paths.inbox):
            os.remove(os.path.join(self.paths.inbox, fn))
        self.drafter.mode = "ok"
        self.drafter.calls = []

    def req(self, method, path, body=None, headers=None, port=None):
        port = port or self.port
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        h = {"Host": "127.0.0.1:%d" % port}
        h.update(headers or {})
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, data

    def post(self, path, doc=None, raw=None, origin=None, ctype="application/json", length=None, port=None):
        port = port or self.port
        h = {"Content-Type": ctype}
        if origin is not False:
            h["Origin"] = origin or "http://127.0.0.1:%d" % port
        if length is not None:
            h["Content-Length"] = str(length)
        body = raw if raw is not None else json.dumps(doc, ensure_ascii=False, indent=2).encode("utf-8")
        st, data = self.req("POST", path, body, h, port)
        return st, json.loads(data.decode("utf-8"))

    def answers_doc(self, set_id=SET_ID):
        return {"kind": qmodel.ANSWERS_KIND, "set_id": set_id, "reviewer": "",
                "answers": [{"question_id": self.qid, "action": "answer", "option_id": None, "option_label": "",
                             "free_text": FREE_MARK, "confirmed": [{"type": "rule", "stage": "classify", "target": "",
                                                                    "text": "규칙", "origin": "human"}]},
                            {"question_id": self.doc["questions"][1]["question_id"], "action": "dismiss"},
                            {"question_id": "EQ-0000000000", "action": "skip"}]}

    def inbox(self):
        return sorted(os.listdir(self.paths.inbox))

    # ---- GET ---------------------------------------------------------------

    def test_get_screen_and_status(self):
        with open(os.path.join(self.qd, qmodel.SCREEN), encoding="utf-8") as f:
            want = f.read().encode("utf-8")
        for p in ("/", "/" + qmodel.SCREEN):
            st, data = self.req("GET", p)
            self.assertEqual((st, data), (200, want))
        st, data = self.req("GET", "/inbox/status")
        self.assertEqual((st, json.loads(data)), (200, {"ok": True, "set_id": SET_ID, "draft": True, "apply": False}))
        st, data = self.req("GET", "/inbox/status", port=self.plain.server_address[1])
        self.assertFalse(json.loads(data)["draft"])
        for p in ("/questions.json", "/../questions.json", "/review.html", "/inbox/engr_answers"):
            self.assertEqual(self.req("GET", p)[0], 404, p)
        self.assertEqual(self.req("GET", "/", headers={"Host": "evil.example:%d" % self.port})[0], 403)

    # ---- 답 저장 -------------------------------------------------------------

    def test_post_answers_saves_body_unchanged(self):
        body = json.dumps(self.answers_doc(), ensure_ascii=False, indent=2).encode("utf-8")
        out_buf = std_io.StringIO()
        with contextlib.redirect_stdout(out_buf):
            st, out = self.post("/inbox/engr_answers", raw=body)
        name = qmodel.answers_name(SET_ID)
        self.assertEqual(st, 200)
        self.assertEqual(out, {"ok": True, "saved": "qa/inbox/" + name, "counts": {"answer": 1, "dismiss": 1, "skip": 1}})
        with open(os.path.join(self.paths.inbox, name), "rb") as f:
            self.assertEqual(f.read(), body)
        self.assertEqual(self.inbox(), [name])
        self.assertFalse([fn for fn in os.listdir(self.paths.qa) if fn.startswith(".inbox")], "임시 파일이 남지 않는다")
        line = out_buf.getvalue()
        self.assertIn("[serve] 답 저장: qa/inbox/%s (답 1, 묻지 않음 1, 나중에 1)" % name, line)
        self.assertNotIn(FREE_MARK, line)
        # 다시 저장하면 같은 이름을 덮어쓴다
        doc = self.answers_doc()
        doc["answers"] = []
        self.assertEqual(self.post("/inbox/engr_answers", doc)[0], 200)
        with open(os.path.join(self.paths.inbox, name), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["answers"], [])

    def test_post_answers_rejects(self):
        p = "/inbox/engr_answers"
        good = self.answers_doc()
        cases = [
            (self.post(p, self.answers_doc("QS-20000101T000000-0000")), 400, "ANSWERS_OTHER_SET"),
            (self.post(p, good, origin=False), 403, "ORIGIN_REJECTED"),
            (self.post(p, good, origin="http://evil.example:%d" % self.port), 403, "ORIGIN_REJECTED"),
            (self.post(p, good, ctype="text/plain"), 415, "CONTENT_TYPE"),
            (self.post(p, raw=b"{}", length=qmodel.MAX_ANSWER_BYTES + 1), 413, "ANSWERS_TOO_LARGE"),
            (self.post(p, raw=b"", length=0), 413, "ANSWERS_TOO_LARGE"),
            (self.post(p, raw=b"{bad"), 400, "ANSWERS_JSON_INVALID"),
            (self.post(p, {"kind": "qa_decisions", "set_id": SET_ID, "answers": []}), 400, "ANSWERS_FORMAT_INVALID"),
            (self.post(p, {"kind": qmodel.ANSWERS_KIND, "set_id": SET_ID, "answers": {}}), 400, "ANSWERS_FORMAT_INVALID"),
            (self.post(p, ["x"]), 400, "ANSWERS_FORMAT_INVALID"),
            (self.post("/inbox/qa_decisions", good), 404, "NOT_FOUND"),
        ]
        for (st, out), want_st, code in cases:
            self.assertEqual((st, out), (want_st, {"ok": False, "code": code}))
        st, data = self.req("POST", p, json.dumps(good).encode("utf-8"),
                            {"Host": "evil.example", "Origin": "http://evil.example", "Content-Type": "application/json"})
        self.assertEqual(st, 403)
        self.assertEqual(self.inbox(), [])

    # ---- 초안 ---------------------------------------------------------------

    def test_draft_ok_filters_invalid(self):
        buf = std_io.StringIO()
        with contextlib.redirect_stdout(buf):
            st, out = self.post("/draft", {"question_id": self.qid, "answer_text": "  " + FREE_MARK + "\n둘째 줄 "})
        self.assertEqual(st, 200)
        self.assertEqual(out, {"ok": True, "drafts": [{"type": "rule", "stage": "label", "target": "", "text": "규칙 문장"}]})
        self.assertEqual(self.drafter.calls, [(self.qid, FREE_MARK + " 둘째 줄")])
        self.assertIn("[serve] 초안 요청 %s → 1건" % self.qid, buf.getvalue())
        self.assertNotIn(FREE_MARK, buf.getvalue())

    def test_draft_rejects(self):
        good = {"question_id": self.qid, "answer_text": "답"}
        cases = [
            (self.post("/draft", good, port=self.plain.server_address[1]), 404, "DRAFT_UNAVAILABLE"),
            (self.post("/draft", good, origin=False), 403, "ORIGIN_REJECTED"),
            (self.post("/draft", good, origin="http://evil.example"), 403, "ORIGIN_REJECTED"),
            (self.post("/draft", good, ctype="text/plain"), 415, "CONTENT_TYPE"),
            (self.post("/draft", raw=b"{}", length=serve.DRAFT_MAX_BODY + 1), 413, "DRAFT_TOO_LARGE"),
            (self.post("/draft", raw=b"{bad"), 400, "DRAFT_JSON_INVALID"),
            (self.post("/draft", ["x"]), 400, "DRAFT_FORMAT_INVALID"),
            (self.post("/draft", {"question_id": "EQ-0000000000", "answer_text": "답"}), 404, "QUESTION_NOT_FOUND"),
            (self.post("/draft", {"question_id": 3, "answer_text": "답"}), 404, "QUESTION_NOT_FOUND"),
            (self.post("/draft", {"question_id": self.qid, "answer_text": "   "}), 400, "ANSWER_TEXT_INVALID"),
            (self.post("/draft", {"question_id": self.qid, "answer_text": "가" * (qmodel.FREE_MAX + 1)}), 400,
             "ANSWER_TEXT_INVALID"),
            (self.post("/draft", {"question_id": self.qid, "answer_text": ["답"]}), 400, "ANSWER_TEXT_INVALID"),
            (self.post("/draft", {"question_id": self.qid, "answer_text": "{{x}}"}), 400, "ANSWER_TEXT_INVALID"),
        ]
        for (st, out), want_st, code in cases:
            self.assertEqual((st, out), (want_st, {"ok": False, "code": code}))
        self.assertEqual(self.drafter.calls, [])

    def test_draft_failures_return_code_only(self):
        for mode, code in (("raise_code", "LLM_TIMEOUT"), ("raise_plain", "DRAFT_FAILED")):
            self.drafter.mode = mode
            buf = std_io.StringIO()
            with contextlib.redirect_stdout(buf):
                st, out = self.post("/draft", {"question_id": self.qid, "answer_text": "답"})
            self.assertEqual((st, out), (502, {"ok": False, "code": code}))
            self.assertIn("[serve] 초안 요청 %s → %s" % (self.qid, code), buf.getvalue())
            self.assertNotIn(FREE_MARK, buf.getvalue())
        self.drafter.mode = "ok"
        self.assertEqual(self.post("/draft", {"question_id": self.qid, "answer_text": "답"})[0], 200, "실패 뒤에도 잠금이 풀린다")

    def test_draft_busy(self):
        self.drafter.mode = "block"
        self.drafter.entered.clear()
        self.drafter.release.clear()
        first = {}

        def run():
            first["r"] = self.post("/draft", {"question_id": self.qid, "answer_text": "첫째"})
        th = threading.Thread(target=run)
        th.start()
        try:
            self.assertTrue(self.drafter.entered.wait(10))
            self.assertEqual(self.post("/draft", {"question_id": self.qid, "answer_text": "둘째"}),
                             (409, {"ok": False, "code": "DRAFT_BUSY"}))
        finally:
            self.drafter.release.set()
            th.join(10)
        self.assertEqual(first["r"][0], 200)
        self.assertEqual([c[1] for c in self.drafter.calls], ["첫째"])

    # ---- 포트와 시작 ----------------------------------------------------------

    def test_question_port_is_stable_and_apart_from_qa(self):
        p = serve.question_port(SET_ID)
        self.assertEqual(p, serve.question_port(SET_ID))
        self.assertTrue(serve.Q_PORT_BASE <= p < serve.Q_PORT_BASE + serve.Q_PORT_SPAN)
        self.assertGreaterEqual(serve.Q_PORT_BASE, serve.PORT_BASE + serve.PORT_SPAN)

    def test_serve_questions_errors(self):
        qd = os.path.join(self.tmp, "q_err")
        runs = []
        for setup, code in ((None, "QUESTIONS_NOT_FOUND"), ("set", "QUESTION_SCREEN_MISSING"), ("broken", "QUESTIONS_INVALID")):
            if setup == "set":
                qmodel.save_set(qd, self.doc)
            elif setup == "broken":
                io.write_text(os.path.join(qd, qmodel.QUESTIONS), "{broken")
            buf = std_io.StringIO()
            with contextlib.redirect_stdout(buf):
                runs.append(serve.serve_questions(self.paths, qd))
            self.assertEqual(buf.getvalue().strip(), "[오류] %s" % code)
        self.assertEqual(runs, [1, 1, 1])

    def test_busy_port_falls_back_to_free_port(self):
        """기본 포트를 다른 서버가 쓰고 있으면 두 번째 bind가 실패하고 빈 포트로 연다(QA 검토 서버도 같다)."""
        busy = self.srv.server_address[1]
        with self.assertRaises(OSError):
            serve.make_question_server(self.paths, self.qd, SET_ID, busy)
        with self.assertRaises(OSError):
            serve.make_server(self.paths, "QA-20261006T000000-0000", busy)
        for patch_name, call in (("question_port", lambda: serve.serve_questions(self.paths, self.qd)),
                                 ("default_port", lambda: serve.serve(self.paths, "QA-20261006T000000-0000"))):
            buf = std_io.StringIO()
            with mock.patch.object(serve, patch_name, return_value=busy), \
                    mock.patch.object(serve._Server, "serve_forever", side_effect=KeyboardInterrupt), \
                    contextlib.redirect_stdout(buf):
                self.assertEqual(call(), 0)
            port = int(re.search(r"127\.0\.0\.1:(\d+)/", buf.getvalue()).group(1))
            self.assertNotEqual(port, busy, patch_name)

    # ---- 보안 헤더와 저장 실패 ------------------------------------------------------

    def headers_of(self, method, path, port, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        h = {"Host": "127.0.0.1:%d" % port}
        h.update(headers or {})
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        r.read()
        c.close()
        return r.status, r

    def test_security_headers(self):
        qa = serve.make_server(self.paths, "QA-20261006T000000-0000", 0)
        threading.Thread(target=qa.serve_forever, daemon=True).start()
        try:
            got = [self.headers_of("GET", "/", self.port), self.headers_of("GET", "/inbox/status", self.port),
                   self.headers_of("GET", "/nope", self.port),
                   self.headers_of("POST", "/draft", self.port, b"{}", {"Content-Type": "application/json"}),
                   self.headers_of("GET", "/", qa.server_address[1]),
                   self.headers_of("GET", "/inbox/status", qa.server_address[1])]
        finally:
            qa.shutdown()
            qa.server_close()
        for st, r in got:
            self.assertEqual(r.getheader("X-Frame-Options"), "DENY", st)
            self.assertEqual(r.getheader("X-Content-Type-Options"), "nosniff")
            self.assertEqual(r.getheader("Content-Security-Policy"), serve.CSP)
            self.assertEqual(r.getheader("Cache-Control"), "no-store")
        csp = serve.CSP
        for part in ("default-src 'none'", "script-src 'unsafe-inline'", "img-src data:", "connect-src 'self'",
                     "frame-ancestors 'none'", "form-action 'none'"):
            self.assertIn(part, csp)

    # ---- 저장 즉시 반영(applier) ---------------------------------------------

    def start(self, applier):
        srv = serve.make_question_server(self.paths, self.qd, SET_ID, 0, applier=applier)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        self.addCleanup(srv.server_close)
        return srv, t, srv.server_address[1]

    def test_save_applies_and_closes_server(self):
        """'답변 완료 · 저장'이 곧 반영이다(사용자 결정, 2026-10-06): 저장한 답 파일로 applier를 부르고, 건수만 돌려준 뒤
        서버를 닫는다(백그라운드로 띄운 Claude는 서버가 끝나는 것으로 마무리를 안다)."""
        calls = []
        result = {"answered": 1, "rules": 1, "taxonomy": 0, "invalid": [], "notes": []}

        def applier(path):
            calls.append(path)
            return {"lines": ["[questions] 반영: 답 1"], "result": result, "board": None}
        srv, t, port = self.start(applier)
        self.assertTrue(json.loads(self.req("GET", "/inbox/status", port=port)[1])["apply"])
        buf = std_io.StringIO()
        with contextlib.redirect_stdout(buf):
            st, out = self.post("/inbox/engr_answers", self.answers_doc(), port=port)
            t.join(10)
        name = qmodel.answers_name(SET_ID)
        self.assertEqual(st, 200)
        self.assertEqual((out["applied"], out["apply"], out["board"]), (True, result, None))
        self.assertEqual(calls, [os.path.join(self.paths.inbox, name)])
        self.assertFalse(t.is_alive(), "반영하면 서버가 닫힌다")
        self.assertTrue(srv.applied)
        self.assertIn("[questions] 반영: 답 1", buf.getvalue())
        self.assertNotIn(FREE_MARK, buf.getvalue())

    def test_apply_failure_keeps_server_open(self):
        """반영이 실패하면 답 파일은 저장된 채 서버를 열어 둔다(다시 저장하면 다시 반영). 응답에는 사유 코드만."""
        class Locked(Exception):
            reason_code = "LEDGER_LOCKED"
        mode = {"n": 0}

        def applier(path):
            mode["n"] += 1
            if mode["n"] == 1:
                raise Locked("본문이 섞일 수 있는 문장")
            if mode["n"] == 2:
                raise ValueError(FREE_MARK)
            return {"lines": [], "result": {"answered": 1}, "board": None}
        srv, t, port = self.start(applier)
        with contextlib.redirect_stdout(std_io.StringIO()) as buf:
            first = self.post("/inbox/engr_answers", self.answers_doc(), port=port)
            second = self.post("/inbox/engr_answers", self.answers_doc(), port=port)
            self.assertTrue(t.is_alive())
            self.assertEqual(self.inbox(), [qmodel.answers_name(SET_ID)])
            third = self.post("/inbox/engr_answers", self.answers_doc(), port=port)
            t.join(10)
        self.assertEqual((first[0], first[1]["applied"], first[1]["apply_code"]), (200, False, "LEDGER_LOCKED"))
        self.assertEqual((second[1]["applied"], second[1]["apply_code"]), (False, "APPLY_FAILED"))
        self.assertTrue(third[1]["applied"])
        self.assertFalse(t.is_alive())
        self.assertNotIn(FREE_MARK, buf.getvalue())
        self.assertIn("[serve] 반영 실패: LEDGER_LOCKED", buf.getvalue())

    def test_no_resave_after_apply(self):
        """반영하고 닫히는 중인 서버는 답 파일을 다시 쓰지 않는다(ALREADY_APPLIED)."""
        srv, t, port = self.start(lambda path: {"lines": [], "result": {}, "board": None})
        srv.applied = True
        self.assertEqual(self.post("/inbox/engr_answers", self.answers_doc(), port=port),
                         (409, {"ok": False, "code": "ALREADY_APPLIED"}))
        self.assertEqual(self.inbox(), [])
        self.assertFalse(json.loads(self.req("GET", "/inbox/status", port=port)[1])["apply"])
        srv.shutdown()

    def test_write_failure_returns_code(self):
        qa_id = "QA-20261006T000000-0000"
        qa = serve.make_server(self.paths, qa_id, 0)
        threading.Thread(target=qa.serve_forever, daemon=True).start()
        try:
            with mock.patch.object(serve.io, "write_text", side_effect=OSError("disk")):
                ans = self.post("/inbox/engr_answers", self.answers_doc())
                dec = self.post("/inbox/qa_decisions", {"kind": "qa_decisions", "qa_run_id": qa_id, "decisions": []},
                                port=qa.server_address[1])
        finally:
            qa.shutdown()
            qa.server_close()
        self.assertEqual(ans, (500, {"ok": False, "code": "ANSWERS_WRITE_FAILED"}))
        self.assertEqual(dec, (500, {"ok": False, "code": "DECISIONS_WRITE_FAILED"}))
        self.assertEqual(self.inbox(), [])
        self.assertFalse([fn for fn in os.listdir(self.paths.qa) if fn.startswith(".inbox")], "임시 파일이 남지 않는다")


if __name__ == "__main__":
    unittest.main()
