"""tools/rag_eval.py(L6 B0a 평가 기준선) 테스트. 실제 네트워크는 쓰지 않는다(labelbot.llm 함수를 바꿔 끼운다).

- 초안: 같은 입력 → 같은 qid·순서, 파일당 2개 + 모자라면 채우기, 길이 하한, 골든 파일에 파일명·본문 없음
- 지표: rank_of·recall@k·MRR 계산, 정확 코사인 순위와 동점 처리
- 용어 적중: 영숫자 경계·대소문자
- 캡처(가짜 네트워크) → --recompute가 같은 수치, 저장 임베딩을 바꾸면 불일치
- RPC·Edge Function 요청 모양(index.ts·beol_rag.html과 같은 인자·헤더), 답변 호출 예산 상한, anon 키 role 검사
- 저장소의 rag/eval/golden_questions.jsonl: 48문항, 필드 고정, 파일명 없음
"""
import base64
import importlib.util
import json
import os
import shutil
import struct
import tempfile
import unittest
from unittest import mock

from labelbot import llm, store

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("rag_eval", os.path.join(ROOT, "tools", "rag_eval.py"))
rag_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rag_eval)

MODEL = "text-embedding-3-small"
RUN = "20990101T000000-test"
FILE_NAMES = ["990101_ZZTOP1.6X M1 가짜 평가.pptx", "990102_ZZTOP2.6Y V1 가짜 평가.pptx",
              "990103_ZZTOP3.6Z M2 가짜 평가.pptx"]
LAYERS = ["M1", "V1", "M2"]
TEXTS = [
    "# M1 Rc 분포\nM1 trench Etch 후 Rc median 61.0, Short fail 3 die, Ru liner 적용 시 개선 경향이 보인다.",
    "# M1 CD\nM1 Etch ACI CD 9.8/8.3 (POR 8.8/8.3), edge 편차는 POR 수준이고 Open fail 없음. 추가 측정 예정이다.",
    "# M1 Rs\nM1 Etch Line Rs median 55.4, Ru liner 조건에서 -12.1% 감소, Void 없음을 TEM으로 확인했다고 보고한다.",
    "짧은 본문",
]
TAX = {
    "version": 1,
    "taxonomy": [
        {"축": "구조/레이어", "값": "M1", "포함 예": "Metal1(→M1), I1"},
        {"축": "구조/레이어", "값": "V1", "포함 예": ""},
        {"축": "구조/레이어", "값": "M2", "포함 예": ""},
        {"축": "공정 모듈", "값": "Etch", "포함 예": ""},
        {"축": "Material", "값": "BM/Liner", "포함 예": "Ru liner"},
    ],
    "questions": [],
    "synonyms": [{"동의어": "비아 바닥 보이드", "표준어": "Void", "메모": "후보"}],
    "rejected": [],
}


def fake_vec(seed, dim=8):
    return [((seed * 7 + i * 3) % 11 - 5) / 10.0 for i in range(dim)]


def fake_jwt(role):
    def seg(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
    return seg({"alg": "HS256", "typ": "JWT"}) + "." + seg({"role": role}) + ".sig"


def axis(con, cid, key, values):
    con.execute("INSERT INTO labels(run_id, chunk_id, kind, key, value, status) VALUES(?,?,?,?,?,?)",
                (RUN, cid, "axis", key, json.dumps(values, ensure_ascii=False), "value"))


def make_workspace(tmp):
    ws = os.path.join(tmp, "ws_fixture")
    os.makedirs(ws)
    with open(os.path.join(ws, "pipeline.json"), "w", encoding="utf-8") as f:
        json.dump({"embedding": {"model": MODEL}, "supabase": {"table": "beol_chunk_embeddings"}}, f)
    con = store.connect(os.path.join(ws, "work.sqlite"))
    con.execute("INSERT INTO runs(run_id, command, started_at) VALUES(?,?,?)", (RUN, "run", "2099-01-01T00:00:00Z"))
    seed = 0
    for fi, name in enumerate(FILE_NAMES):
        fid = ("%x" % (fi + 10)) * 64
        fid = fid[:64]
        con.execute("INSERT INTO files(file_id, file_name, rel_path, status) VALUES(?,?,?,?)", (fid, name, name, "ok"))
        layer = LAYERS[fi]
        for si, text in enumerate(TEXTS):
            text = text.replace("M1", layer)
            cid = "%s:ppt/slides/slide%d.xml" % (fid[:16], si + 1)
            con.execute("INSERT INTO chunks(chunk_id, file_id, seq, text, text_hash) VALUES(?,?,?,?,?)",
                        (cid, fid, si + 1, text, "h%d" % si))
            con.execute("INSERT INTO labels(run_id, chunk_id, kind, key, value) VALUES(?,?,?,?,?)",
                        (RUN, cid, "chunk_type", "", "내용"))
            axis(con, cid, "구조/레이어", [layer])
            axis(con, cid, "공정 모듈", ["Etch"])
            axis(con, cid, "Material", ["BM/Liner"])
            axis(con, cid, "불량 모드", ["Short"] if si == 0 else ["해당 없음"])
            vec = fake_vec(seed)
            seed += 1
            con.execute("INSERT INTO chunk_embeddings(chunk_id, model, dim, text_hash, vector, run_id) VALUES(?,?,?,?,?,?)",
                        (cid, MODEL, len(vec), "h%d" % si, struct.pack("<%df" % len(vec), *vec), RUN))
            con.execute("INSERT INTO vector_push_log(chunk_id, model, text_hash, label_hash, target_host_hash, result_code)"
                        " VALUES(?,?,?,?,?,?)", (cid, MODEL, "h%d" % si, "lh", "t", "OK"))
    con.commit()
    con.close()
    tax_path = os.path.join(tmp, "taxonomy.json")
    with open(tax_path, "w", encoding="utf-8") as f:
        json.dump(TAX, f, ensure_ascii=False)
    return ws, tax_path


class RagEvalTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rag_eval_")
        self.ws, self.tax = make_workspace(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- 초안 ----
    def test_draft_deterministic_and_selection(self):
        a, names, texts = rag_eval.draft(self.ws, self.tax, total=7)
        b, _, _ = rag_eval.draft(self.ws, self.tax, total=7)
        self.assertEqual([i["qid"] for i in a], [i["qid"] for i in b])
        self.assertEqual(a, b)
        self.assertEqual(len(a), 7)  # 3파일 × 2 + 채우기 1
        per_file = {}
        for it in a:
            per_file[it["file_id"]] = per_file.get(it["file_id"], 0) + 1
            self.assertEqual(set(it), set(rag_eval.GOLDEN_FIELDS))
            self.assertEqual(it["source_workspace"], "ws_fixture")
            text = texts[it["expected_chunk_ids"][0]]
            self.assertGreaterEqual(len(text), rag_eval.MIN_CHARS)  # "짧은 본문"은 뽑히지 않는다
            self.assertTrue(it["expected_terms"])
            self.assertTrue(all(rag_eval.term_in(t, text) for t in it["expected_terms"]))
        self.assertEqual(sorted(per_file.values()), [2, 2, 3])
        self.assertEqual(rag_eval.check_golden(a, names, texts, total=7), [])
        # 파일 안 순서 = sha256(chunk_id) 오름차순
        first = [it for it in a if it["file_id"] == a[0]["file_id"]][:2]
        shas = [rag_eval.sha(it["expected_chunk_ids"][0]) for it in first]
        self.assertEqual(shas, sorted(shas))

    def test_golden_has_no_file_names_or_chunk_text(self):
        items, names, texts = rag_eval.draft(self.ws, self.tax, total=6)
        rag_eval.write_jsonl(os.path.join(self.tmp, "g.jsonl"), items)
        with open(os.path.join(self.tmp, "g.jsonl"), encoding="utf-8") as f:
            raw = f.read()
        for n in names:
            self.assertNotIn(os.path.splitext(n)[0], raw)
            self.assertNotIn(n.split()[0].split("_")[1], raw)  # lot 꼴 토큰
        for t in texts.values():
            self.assertNotIn(t, raw)
        bad = dict(items[0], question=items[0]["question"] + " " + os.path.splitext(FILE_NAMES[0])[0])
        self.assertIn("FILE_NAME:" + bad["qid"], rag_eval.check_golden([bad] + items[1:], names, texts, total=6))
        cid = items[1]["expected_chunk_ids"][0]
        leak = dict(items[1], question=texts[cid][:40])
        self.assertIn("CHUNK_TEXT:" + leak["qid"], rag_eval.check_golden([items[0], leak] + items[2:], names, texts, 6))
        b64 = dict(items[2], expected_terms=items[2]["expected_terms"] + ["QUJD" * 12])
        self.assertIn("BASE64:" + b64["qid"], rag_eval.check_golden(items[:2] + [b64] + items[3:], names, texts, 6))

    # ---- 지표 ----
    def test_metrics_math(self):
        self.assertEqual(rag_eval.rank_of(["a", "b", "c"], ["c"]), 3)
        self.assertIsNone(rag_eval.rank_of(["a"], ["z"]))
        self.assertIsNone(rag_eval.rank_of(None, ["z"]))
        m = rag_eval.retrieval_metrics([1, 3, None, 7], (5, 10))
        self.assertEqual(m["n"], 4)
        self.assertEqual(m["recall@5"], 0.5)
        self.assertEqual(m["recall@10"], 0.75)
        self.assertEqual(m["mrr"], round((1 + 1 / 3 + 1 / 7) / 4, 6))
        self.assertEqual(rag_eval.retrieval_metrics([], (5,)), {})

    def test_exact_ranking_cosine_and_ties(self):
        matrix = [("b", rag_eval.norm([1, 0])), ("a", rag_eval.norm([1, 0])), ("c", rag_eval.norm([0, 1])),
                  ("d", rag_eval.norm([-1, 0]))]
        self.assertEqual(rag_eval.exact_ranking([2, 0.1], matrix), ["a", "b", "c", "d"])

    def test_term_hits(self):
        hit, rate = rag_eval.term_hits("VA via Rc는 개선되었고 ru liner 적용", ["VA", "rc", "Short", "Ru liner"])
        self.assertEqual(hit, ["VA", "rc", "Ru liner"])
        self.assertEqual(rate, 0.75)
        self.assertEqual(rag_eval.term_hits("VALUE", ["VA"]), ([], 0.0))
        self.assertEqual(rag_eval.term_hits("계면 산화 억제", ["계면 산화"])[1], 1.0)
        self.assertEqual(rag_eval.term_hits("x", []), ([], None))

    # ---- 캡처·재계산(가짜 네트워크) ----
    def _capture(self, answers=2, budget=None):
        items, _, _ = rag_eval.draft(self.ws, self.tax, total=6)
        qpath = os.path.join(self.tmp, "golden.jsonl")
        rag_eval.write_jsonl(qpath, items)
        out = os.path.join(self.tmp, "out", "baseline_openai_20990101.jsonl")
        calls = {"rpc": [], "ask": []}
        ids = [it["expected_chunk_ids"][0] for it in items]

        def fake_post(url, headers, payload, timeout, ca_file=None):
            if url.endswith("/rest/v1/rpc/beol_rag_search"):
                calls["rpc"].append((url, headers, payload))
                return 200, [{"chunk_id": c} for c in ids[:8]]
            if url.endswith("/functions/v1/beol-rag-ask"):
                calls["ask"].append((url, headers, payload))
                q = payload["messages"][0]["content"]
                if len(calls["ask"]) == 1:
                    raise llm.CallFailed("HTTP_502")
                return 200, {"answer": "M1 Etch 결과: " + q + " [1]", "cited": [1],
                             "evidence": [{"n": 1, "chunk_id": ids[0], "kind": "hit", "image_url": "https://x.invalid/s"},
                                          {"n": 2, "chunk_id": ids[1], "kind": "sibling"}]}
            raise AssertionError("unexpected url")

        class FakeEmbed:
            def __init__(self, cfg):
                self.cfg = cfg

            def embed(self, texts):
                calls.setdefault("embed", []).append(list(texts))
                return [fake_vec(i + 3) for i in range(len(texts))]

        env = {"SUPABASE_URL": "https://example.invalid", "SUPABASE_SERVICE_KEY": "svc-test",
               "SUPABASE_ANON_KEY": fake_jwt("anon"), "OPENAI_API_KEY": "test"}
        argv = ["--workspace", self.ws, "--questions", qpath, "--out", out, "--answers", str(answers), "--workers", "2"]
        if budget is not None:
            argv += ["--max-answer-calls", str(budget)]
        with mock.patch.dict(os.environ, env), mock.patch.object(rag_eval, "load_env_file", lambda: []), \
                mock.patch.object(llm, "post_json", fake_post), mock.patch.object(llm, "HttpEmbedTransport", FakeEmbed):
            rc = rag_eval._main(argv)
        self.assertEqual(rc, 0)
        return items, qpath, out, calls

    def test_capture_then_recompute_identical(self):
        items, qpath, out, calls = self._capture()
        self.assertEqual(len(calls["embed"]), 1)                 # 질문 임베딩은 한 번에 한 번씩
        self.assertEqual(len(calls["embed"][0]), len(items))
        url, hdrs, payload = calls["rpc"][0]                     # index.ts search()와 같은 인자
        self.assertEqual(set(payload), {"query_embedding", "query_text", "filters", "k"})
        self.assertEqual(payload["k"], 8)
        self.assertEqual(payload["filters"], {})
        self.assertTrue(payload["query_embedding"].startswith("["))
        self.assertEqual(hdrs["Authorization"], "Bearer " + hdrs["apikey"])
        url, hdrs, payload = calls["ask"][0]                     # beol_rag.html ask()와 같은 요청
        self.assertEqual(set(payload), {"messages", "filters", "k"})
        self.assertEqual(payload["k"], 5)
        self.assertEqual(payload["messages"][0]["role"], "user")
        self.assertEqual(hdrs["Authorization"], "Bearer " + hdrs["apikey"])
        lines = rag_eval.read_jsonl(out)
        ret = [r for r in lines if r["kind"] == "retrieval"]
        ans = [r for r in lines if r["kind"] == "answer"]
        self.assertEqual(len(ret), len(items))
        self.assertEqual(len(ans), len(items) * 2)
        self.assertEqual(len(calls["ask"]), len(items) * 2 + 1)  # 일시 오류 1건 재시도
        raw = open(out, encoding="utf-8").read()
        self.assertNotIn("x.invalid", raw)                       # 서명 URL·호스트를 저장하지 않는다
        self.assertNotIn("example.invalid", raw)
        self.assertNotIn("svc-test", raw)
        with open(rag_eval.summary_path(out), encoding="utf-8") as f:
            summary = json.load(f)
        self.assertEqual(summary["errors"]["answer_retried"], {"HTTP_502": 1})
        self.assertEqual(summary["answer_calls"], len(items) * 2 + 1)
        self.assertEqual(summary["retrieval"]["rpc"]["recall@8"], 1.0)
        self.assertNotIn("example.invalid", json.dumps(summary))
        # 재계산: 네트워크 없이 같은 수치
        with mock.patch.object(llm, "post_json", side_effect=AssertionError("network")):
            self.assertEqual(rag_eval._main(["--workspace", self.ws, "--questions", qpath, "--recompute", out]), 0)
        # 저장 임베딩을 바꾸면 불일치
        ret[0]["query_embedding"] = [-x for x in ret[0]["query_embedding"]]
        rag_eval.write_jsonl(out, ret + ans)
        self.assertEqual(rag_eval._main(["--workspace", self.ws, "--questions", qpath, "--recompute", out]), 1)

    def test_answer_budget_cap(self):
        items = [{"qid": "q%d" % i, "question": "질문 %d" % i, "expected_chunk_ids": ["c"], "expected_terms": ["M1"]}
                 for i in range(4)]
        n = [0]

        def always_transient(q):
            n[0] += 1
            raise llm.CallFailed("TIMEOUT")

        errors = {}
        recs, used = rag_eval.run_answers(items, 3, 5, always_transient, workers=2, errors=errors)
        self.assertEqual(used, 5)
        self.assertEqual(n[0], 5)
        self.assertEqual(len(recs), 12)
        self.assertEqual(sum(errors["answer"].values()), 12)
        self.assertIn("BUDGET_EXHAUSTED", errors["answer"])

    def test_anon_key_role(self):
        with mock.patch.dict(os.environ, {"SUPABASE_ANON_KEY": fake_jwt("service_role")}):
            with self.assertRaises(rag_eval.EvalError) as cm:
                rag_eval.anon_key_from_html()
        self.assertEqual(cm.exception.reason_code, "ANON_KEY_NOT_ANON")
        with mock.patch.dict(os.environ, {"SUPABASE_ANON_KEY": fake_jwt("anon")}):
            self.assertTrue(rag_eval.anon_key_from_html())

    # ---- 저장소 골든 파일 ----
    def test_repo_golden_file(self):
        path = os.path.join(ROOT, "rag", "eval", "golden_questions.jsonl")
        items = rag_eval.read_jsonl(path)
        self.assertEqual(len(items), 48)
        self.assertEqual(len({i["qid"] for i in items}), 48)
        self.assertEqual(len({i["question"] for i in items}), 48)
        self.assertEqual(len({i["file_id"] for i in items}), 24)
        names = os.listdir(os.path.join(ROOT, "parshing test files"))
        raw = open(path, encoding="utf-8").read().lower()
        for n in names:
            self.assertNotIn(os.path.splitext(n)[0].lower(), raw)
            for m in rag_eval._LOT_RE.finditer(n):
                self.assertNotIn(m.group(0).lower(), raw)
        for it in items:
            self.assertEqual(set(it), set(rag_eval.GOLDEN_FIELDS))
            self.assertTrue(it["expected_terms"])
            self.assertIsNone(rag_eval._B64_RE.search(json.dumps(it, ensure_ascii=False).replace(it["file_id"], "")
                                                      .replace(it["expected_chunk_ids"][0], "")))


if __name__ == "__main__":
    unittest.main()
