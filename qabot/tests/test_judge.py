"""QM5 완료 조건: L3(b) judge와 LLM adapter. 네트워크를 쓰지 않는다(전송 함수를 바꿔 끼운다)."""
import json
import os
import re
import shutil
import tempfile
import threading
import unittest
from unittest import mock

from qabot import io, judge, llm, model, policy, runner
from qabot.tests import fixturegen

REPO_ROOT = fixturegen.REPO_ROOT
LAYERS = ["L1", "L2", "L3A", "L3B"]
KEY_ENV = "QABOT_TEST_JUDGE_KEY"
KEY_VALUE = "sk-qabot-test-9f3a7c1e-DO-NOT-LEAK"
_ID_RE = re.compile(r"^- id: (\S+)$", re.M)
_TMPS = []


def _tmp():
    """코드 폴더 밖 임시 작업 폴더. 모듈이 끝나면 지운다."""
    d = tempfile.mkdtemp()
    _TMPS.append(d)
    return d


def tearDownModule():
    for d in _TMPS:
        shutil.rmtree(d, ignore_errors=True)


def _dummy_ids():
    with open(os.path.join(REPO_ROOT, "tests", "gold", "dummy_hashes.jsonl"), encoding="utf-8") as f:
        return [json.loads(l)["file_id"] for l in f if l.strip()]


def _policy(**judge_over):
    """temperature=None(미전송)은 정책 로더가 아직 받지 않으므로 검증 뒤에 넣는다."""
    null_temp = "temperature" in judge_over and judge_over["temperature"] is None
    if null_temp:
        judge_over.pop("temperature")
    pol = policy.validate_policy({"judge": judge_over} if judge_over else {})
    if null_temp:
        pol["judge"]["temperature"] = None
    return pol


SCHEMA = policy.validate_schema({})


def _run(bundle, pol=None, llm_obj=None, tmp=None, no_judge=False, log=None):
    tmp = tmp or _tmp()
    res = runner.execute(bundle, pol or _policy(), SCHEMA, paths=io.QaPaths(tmp), llm=llm_obj, no_judge=no_judge,
                         log=log, layers=LAYERS)
    return res, tmp


def _requests(res, per_call=12):
    """judge 요청 수(레코드마다 항목을 per_call개씩 나눈 수의 합)."""
    return sum(-(-(v.get("judge") or {}).get("items", 0) // per_call) for v in res.verdicts if v.get("judge"))


def _issues(res, code=None):
    return [(v["record_id"], i) for v in res.verdicts for i in v["issues"] if code is None or i["code"] == code]


def _mock_obj(messages, file_ids, hint):
    return json.loads(llm.MockJudgeLLM().complete(messages, file_ids, hint))


class Recorder(object):
    """responder 래퍼: 호출을 레코드 ID별로 센다."""

    def __init__(self, fn=None):
        self.fn = fn
        self.lock = threading.Lock()
        self.calls = []

    def __call__(self, messages, file_ids, hint):
        with self.lock:
            self.calls.append((hint["record_id"], messages, list(file_ids)))
        if self.fn is None:
            return llm.MockJudgeLLM().complete(messages, file_ids, hint)
        return self.fn(messages, file_ids, hint)


class FakePost(object):
    """labelbot post_json 자리. 사용자 메시지의 항목 id를 모두 supported로 답한다."""

    def __init__(self, tool=False, fail=None):
        self.tool = tool
        self.fail = fail
        self.lock = threading.Lock()
        self.sent = []

    def __call__(self, url, headers, payload, timeout, ca_file=None):
        with self.lock:
            self.sent.append({"url": url, "headers": dict(headers), "payload": payload, "timeout": timeout})
        if self.fail:
            from qabot.llm_http import lb_llm

            raise lb_llm.CallFailed(self.fail)
        ids = _ID_RE.findall(payload["messages"][1]["content"])
        content = json.dumps({"items": [{"id": i, "verdict": "supported", "reason": "인용문이 라벨을 직접 말한다."}
                                        for i in ids]}, ensure_ascii=False)
        if self.tool:
            msg = {"content": None, "tool_calls": [{"type": "function", "function": {
                "name": "submit_verdicts", "arguments": content}}]}
        else:
            msg = {"content": content}
        return 200, {"choices": [{"message": msg}]}


def _http_cfg(base_url="https://api.openai.com/v1", suffixes=()):
    return {"transport": "http", "base_url": base_url, "chat_path": "/chat/completions", "model": "pipeline-model",
            "api_key_env": KEY_ENV, "auth_header": "Authorization", "extra_headers": {}, "ca_file": None,
            "timeout": 60, "temperature": 0, "max_tokens": None, "max_tokens_param": "max_tokens",
            "response_format_json": False, "max_retries": 2, "workers": 4,
            "internal_host_suffixes": list(suffixes)}


def _http_llm(pol, cfg, post):
    j = judge.create(pol, llm_cfg=cfg)
    j.llm.post = post
    return j.llm


class JudgeTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fx = fixturegen.generate(seed=7)
        cls.tax = model.TaxIndex(cls.fx.bundle.taxonomy)
        fids = sorted(cls.fx.bundle.sources)
        cls.small = cls.fx.bundle.subset(fids[:3])

    def bundle(self, small=False):
        return (self.small if small else self.fx.bundle).copy()

    def as_dummy(self, bundle):
        """한 파일의 번들을 더미 해시 파일 ID로 바꾼다(사외 전송 허용 확인용)."""
        fid = sorted(bundle.sources)[0]
        b = bundle.subset([fid]).copy()
        new = _dummy_ids()[0]
        b.sources = {new: dict(b.sources[fid], file_id=new)}
        b.units = {k: dict(u, file_id=new) for k, u in b.units.items()}
        b.records = [dict(r, file_id=new) for r in b.records]
        return b

    def judged_records(self, res):
        return [v for v in res.verdicts if (v.get("judge") or {}).get("items")]


class CleanAndMutationTest(JudgeTestBase):
    def test_clean_fixture_all_pass_with_mock(self):
        res, _ = _run(self.bundle())
        self.assertEqual({v["verdict"] for v in res.verdicts}, {"PASS"})
        self.assertGreater(sum(v["judge"]["items"] for v in res.verdicts), 100)
        self.assertGreater(res.ctx.judge.calls, 0)
        self.assertEqual(res.ctx.judge.failed, 0)
        self.assertEqual(res.ctx.judge.name, "mock")

    def test_label_swap_detected(self):
        b = self.bundle()
        injected = {}
        for r in b.records:
            if r["chunk_type"] != "내용":
                continue
            for name in sorted(r["axes"]):
                a = r["axes"][name]
                if a["status"] != "value":
                    continue
                quote = a["evidence"]["quote"]
                cands = [v for v in sorted(self.tax.values[name]) if v not in a["values"]
                         and not any(llm.term_in(t, quote) for t in [v] + self.tax.synonyms_for(v))]
                if cands:
                    a["values"] = [cands[0]] + a["values"][1:]
                    injected[r["record_id"]] = ("axis:%s" % name, cands[0])
                    break
        self.assertGreaterEqual(len(injected), 30)
        res, _ = _run(b)
        found = {rid for rid, i in _issues(res, "L3_NOT_SUPPORTED")
                 if rid in injected and (i["field"], i["evidence"]["label"]) == injected[rid]}
        self.assertEqual(len(found) / len(injected), 1.0)
        other = [(rid, i) for rid, i in _issues(res) if rid not in injected]
        self.assertEqual(other, [])
        for v in res.verdicts:
            if v["record_id"] in injected:
                self.assertEqual(v["verdict"], "REVIEW")

    def test_answer_flip_detected(self):
        b = self.bundle()
        injected = {}
        for r in b.records:
            for qid in sorted(r["answers"]):
                a = r["answers"][qid]
                if a["answer"] in ("O", "X"):
                    a["answer"] = "X" if a["answer"] == "O" else "O"
                    injected[r["record_id"]] = "answer:%s" % qid
                    break
        self.assertGreaterEqual(len(injected), 30)
        res, _ = _run(b)
        found = {rid for rid, i in _issues(res, "L3_NOT_SUPPORTED") if injected.get(rid) == i["field"]}
        self.assertEqual(found, set(injected))
        self.assertEqual([x for x in _issues(res) if x[0] not in injected], [])

    def test_partial_is_minor_and_reason_verbatim(self):
        def partial(messages, file_ids, hint):
            return json.dumps({"items": [{"id": it["id"], "verdict": "partial", "reason": "인용문에 위치 정보만 있다 %s" % it["id"]}
                                         for it in hint["items"]]}, ensure_ascii=False)

        res, _ = _run(self.bundle(small=True), llm_obj=llm.MockJudgeLLM(partial))
        iss = _issues(res, "L3_PARTIALLY_SUPPORTED")
        self.assertTrue(iss)
        for _, i in iss:
            self.assertEqual(i["severity"], "minor")
            self.assertEqual(i["reason"], "인용문에 위치 정보만 있다 %s" % i["evidence"]["item"])
            self.assertNotIn("reason", io.strip_text(i)["evidence"])
            self.assertNotIn("judge_reason", io.strip_text(i)["evidence"])
            self.assertNotEqual(io.strip_text(i)["reason"], i["reason"])
        self.assertEqual({v["verdict"] for v in res.verdicts}, {"PASS"})
        for v in self.judged_records(res):
            self.assertEqual(v["judge"]["partial"], v["judge"]["items"])

    def test_items_split_and_ids(self):
        rec = Recorder()
        res, _ = _run(self.bundle(small=True), pol=_policy(max_items_per_call=3), llm_obj=llm.MockJudgeLLM(rec))
        self.assertEqual({v["verdict"] for v in res.verdicts}, {"PASS"})
        self.assertEqual(res.ctx.judge.calls + res.ctx.judge.cache_hits, _requests(res, 3))
        for rid, messages, file_ids in rec.calls:
            self.assertLessEqual(len(_ID_RE.findall(messages[1]["content"])), 3)
            self.assertEqual(file_ids, [res.targets[rid].file_id])
        for v in res.verdicts:
            ids = [it["id"] for it in judge.build_items(res.targets[v["record_id"]], res.ctx.tax)]
            self.assertEqual(len(ids), v["judge"]["items"])
            a = [i for i in ids if i.startswith("a")]
            q = [i for i in ids if i.startswith("q")]
            self.assertEqual(ids, a + q)
            self.assertEqual(a, ["a%d" % n for n in range(1, len(a) + 1)])
            self.assertEqual(q, ["q%d" % n for n in range(1, len(q) + 1)])


class FailSafeTest(JudgeTestBase):
    def _corrupt(self, kind):
        def fn(messages, file_ids, hint):
            if kind == "timeout":
                raise llm.LLMError("TIMEOUT")
            obj = _mock_obj(messages, file_ids, hint)
            if kind == "bad_json":
                return '{"items": [{"id": "a1", "verdict": '
            if kind == "missing_item":
                obj["items"] = obj["items"][:-1]
            elif kind == "duplicate_item":
                obj["items"].append(dict(obj["items"][0]))
            elif kind == "invalid_verdict":
                obj["items"][0]["verdict"] = "maybe"
            elif kind == "duplicate_key":
                return '{"items": [], "items": %s}' % json.dumps(obj["items"], ensure_ascii=False)
            return json.dumps(obj, ensure_ascii=False)
        return fn

    def test_injected_failures_retry_then_judge_failed(self):
        expect = {"timeout": "TIMEOUT", "bad_json": "JSON_PARSE", "missing_item": "ITEM_MISSING",
                  "duplicate_item": "ITEM_DUPLICATE", "invalid_verdict": "VERDICT_INVALID",
                  "duplicate_key": "DUPLICATE_KEY"}
        pol = _policy(max_retries=2)
        for kind, code in sorted(expect.items()):
            with self.subTest(kind=kind):
                rec = Recorder(self._corrupt(kind))
                res, tmp = _run(self.bundle(small=True), pol=pol, llm_obj=llm.MockJudgeLLM(rec))
                affected = self.judged_records(res)
                self.assertTrue(affected)
                counts = {}
                for rid, _, _ in rec.calls:
                    counts[rid] = counts.get(rid, 0) + 1
                for v in affected:
                    # 요청마다 1회 + 재시도 2회
                    self.assertEqual(counts[v["record_id"]], 3 * -(-v["judge"]["items"] // 12))
                    self.assertNotEqual(v["verdict"], "PASS")
                    self.assertEqual(v["verdict"], "REVIEW")
                    failed = [i for i in v["issues"] if i["code"] == "L3_JUDGE_FAILED"]
                    self.assertEqual(len(failed), v["judge"]["items"])
                    self.assertEqual(v["judge"]["failed"], v["judge"]["items"])
                    self.assertEqual({i["evidence"]["reason_code"] for i in failed}, {code})
                    self.assertEqual({i["severity"] for i in failed}, {"major"})
                self.assertEqual(res.ctx.judge.failed, _requests(res))
                self.assertEqual(res.ctx.judge.calls, 3 * _requests(res))
                self.assertEqual(io.read_own_jsonl(io.QaPaths(tmp).judge_cache), [])

    def test_retry_recovers(self):
        state = {}
        lock = threading.Lock()

        def flaky(messages, file_ids, hint):
            key = json.dumps(messages, ensure_ascii=False)
            with lock:
                n = state[key] = state.get(key, 0) + 1
            if n == 1:
                raise llm.LLMError("TIMEOUT")
            return llm.MockJudgeLLM().complete(messages, file_ids, hint)

        res, _ = _run(self.bundle(small=True), llm_obj=llm.MockJudgeLLM(flaky))
        self.assertEqual({v["verdict"] for v in res.verdicts}, {"PASS"})
        self.assertEqual(res.ctx.judge.failed, 0)
        j = res.ctx.judge
        self.assertEqual(j.calls, 2 * (_requests(res) - j.cache_hits))

    def test_no_judge_zero_pass(self):
        res, _ = _run(self.bundle(), no_judge=True)
        self.assertEqual(sum(v["verdict"] == "PASS" for v in res.verdicts), 0)
        for v in res.verdicts:
            skipped = [i for i in v["issues"] if i["code"] == "L3_JUDGE_SKIPPED"]
            self.assertEqual(len(skipped), 1)
            self.assertIsNone(skipped[0]["field"])
            self.assertEqual(skipped[0]["evidence"], {"reason_code": "NO_JUDGE"})
            self.assertIsNone(v["judge"])

    def test_http_without_llm_config_is_skipped(self):
        res, _ = _run(self.bundle(small=True), pol=_policy(transport="http"))
        self.assertIsNone(res.ctx.judge)
        self.assertEqual(res.ctx.judge_skip_reason, "LLM_CONFIG_MISSING")
        self.assertEqual(sum(v["verdict"] == "PASS" for v in res.verdicts), 0)

    def test_critical_records_get_no_judge_call(self):
        b = self.bundle()
        bad = set()
        for r in b.records:
            if r["chunk_type"] == "내용" and len(bad) < 15:
                name = next(n for n in sorted(r["axes"]) if r["axes"][n]["status"] == "value")
                r["axes"][name]["values"] = ["택소노미에없는값"]
                bad.add(r["record_id"])
        rec = Recorder()
        res, _ = _run(b, llm_obj=llm.MockJudgeLLM(rec))
        called = {rid for rid, _, _ in rec.calls}
        self.assertEqual(called & bad, set())
        self.assertTrue(called)
        for v in res.verdicts:
            if v["record_id"] in bad:
                self.assertEqual(v["verdict"], "REJECT")
                self.assertIsNone(v["judge"])
                self.assertFalse([i for i in v["issues"] if i["layer"] == "L3B"])


class SendGateTest(JudgeTestBase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {KEY_ENV: KEY_VALUE})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_create_merges_judge_overrides(self):
        pol = _policy(transport="http", model="judge-model", temperature=None, timeout=17, mode="tool")
        j = judge.create(pol, llm_cfg=_http_cfg())
        self.assertEqual(j.name, "judge-model")
        self.assertEqual(j.llm.cfg["timeout"], 17)
        sp = j.sent_params()
        self.assertEqual(sp["temperature"], "미전송")
        self.assertEqual(sp["mode"], "tool")
        self.assertEqual(judge.create(_policy(transport="http"), llm_cfg=_http_cfg()).name, "pipeline-model")
        with self.assertRaises(judge.JudgeUnavailable) as cm:
            judge.create(_policy(transport="http"), llm_cfg={"base_url": ""})
        self.assertEqual(cm.exception.reason_code, "LLM_CONFIG_MISSING")

    def test_external_host_non_dummy_blocked(self):
        pol = _policy(transport="http")
        post = FakePost()
        res, _ = _run(self.bundle(small=True), pol=pol, llm_obj=_http_llm(pol, _http_cfg(), post))
        self.assertEqual(post.sent, [])
        self.assertEqual(res.ctx.judge.calls, 0)
        affected = self.judged_records(res)
        self.assertTrue(affected)
        for v in affected:
            codes = {i["evidence"]["reason_code"] for i in v["issues"] if i["code"] == "L3_JUDGE_FAILED"}
            self.assertEqual(codes, {"EXTERNAL_NON_DUMMY"})
            self.assertEqual(v["verdict"], "REVIEW")

    def test_external_host_dummy_file_is_sent(self):
        pol = _policy(transport="http")
        post = FakePost()
        b = self.as_dummy(self.bundle(small=True))
        res, _ = _run(b, pol=pol, llm_obj=_http_llm(pol, _http_cfg(), post))
        self.assertGreater(len(post.sent), 0)
        self.assertEqual(len(post.sent), res.ctx.judge.calls)
        self.assertEqual({s["url"] for s in post.sent}, {"https://api.openai.com/v1/chat/completions"})
        self.assertEqual({s["headers"]["Authorization"] for s in post.sent}, {"Bearer " + KEY_VALUE})
        for s in post.sent:
            self.assertEqual(set(s["payload"]), {"model", "messages", "temperature"})
            self.assertEqual(s["payload"]["temperature"], 0)
        self.assertEqual({v["verdict"] for v in res.verdicts}, {"PASS"})
        self.assertFalse(_issues(res, "L3_JUDGE_FAILED"))

    def test_uncertain_hosts_blocked(self):
        pol = _policy(transport="http")
        b = self.as_dummy(self.bundle(small=True))
        for url in ("https://10.0.0.5/v1", "https://[::1]/v1", "ftp://llm.corp.example/v1", "https:///v1"):
            with self.subTest(url=url):
                post = FakePost()
                res, _ = _run(b.copy(), pol=pol, llm_obj=_http_llm(pol, _http_cfg(url, ["corp.example", "10.0.0.5"]), post))
                self.assertEqual(post.sent, [])
                codes = {i["evidence"]["reason_code"] for _, i in _issues(res, "L3_JUDGE_FAILED")}
                self.assertEqual(codes, {"HOST_UNCERTAIN"})
                self.assertEqual(sum(v["verdict"] == "PASS" for v in self.judged_records(res)), 0)

    def test_internal_host_sends_any_file(self):
        pol = _policy(transport="http")
        post = FakePost()
        res, _ = _run(self.bundle(small=True), pol=pol,
                      llm_obj=_http_llm(pol, _http_cfg("https://llm.corp.example/v1", ["corp.example"]), post))
        self.assertGreater(len(post.sent), 0)
        self.assertEqual({v["verdict"] for v in res.verdicts}, {"PASS"})

    def test_key_missing_not_sent(self):
        pol = _policy(transport="http")
        post = FakePost()
        with mock.patch.dict(os.environ, {KEY_ENV: ""}):
            res, _ = _run(self.bundle(small=True), pol=pol,
                          llm_obj=_http_llm(pol, _http_cfg("https://llm.corp.example/v1", ["corp.example"]), post))
        self.assertEqual(post.sent, [])
        self.assertEqual({i["evidence"]["reason_code"] for _, i in _issues(res, "L3_JUDGE_FAILED")}, {"KEY_MISSING"})

    def test_tool_mode_and_null_temperature(self):
        pol = _policy(transport="http", mode="tool", temperature=None)
        post = FakePost(tool=True)
        res, _ = _run(self.bundle(small=True), pol=pol,
                      llm_obj=_http_llm(pol, _http_cfg("https://llm.corp.example/v1", ["corp.example"]), post))
        self.assertGreater(len(post.sent), 0)
        for s in post.sent:
            self.assertNotIn("temperature", s["payload"])
            self.assertEqual(s["payload"]["tool_choice"]["function"]["name"], "submit_verdicts")
        self.assertEqual({v["verdict"] for v in res.verdicts}, {"PASS"})

    def test_http_call_failed_retried_and_not_cached(self):
        pol = _policy(transport="http", max_retries=1)
        post = FakePost(fail="TIMEOUT")
        res, tmp = _run(self.bundle(small=True), pol=pol,
                        llm_obj=_http_llm(pol, _http_cfg("https://llm.corp.example/v1", ["corp.example"]), post))
        self.assertEqual(len(post.sent), 2 * _requests(res))
        self.assertEqual({i["evidence"]["reason_code"] for _, i in _issues(res, "L3_JUDGE_FAILED")}, {"TIMEOUT"})
        self.assertEqual(io.read_own_jsonl(io.QaPaths(tmp).judge_cache), [])

    def test_api_key_never_written(self):
        pol = _policy(transport="http")
        tmp = _tmp()
        paths = io.QaPaths(tmp)
        log = io.Logger(paths.log_path)
        cfg = _http_cfg("https://llm.corp.example/v1", ["corp.example"])
        ok = _http_llm(pol, cfg, FakePost())
        res, _ = _run(self.bundle(small=True), pol=pol, llm_obj=ok, tmp=tmp, log=log)
        _run(self.bundle(small=True), pol=_policy(transport="http", max_retries=0),
             llm_obj=_http_llm(pol, cfg, FakePost(fail="HTTP_500")), tmp=_tmp(), log=log)
        _run(self.bundle(small=True), pol=pol, llm_obj=_http_llm(pol, _http_cfg(), FakePost()), tmp=tmp, log=log)
        runner.write_verdicts(type(res)(policy=res.policy, verdicts=res.verdicts, run_dir=paths.run_dir("QA-test", True)))
        io.write_json(os.path.join(paths.run_dir("QA-test"), "manifest.json"),
                      {"judge": runner._judge_stats(res.ctx.judge), "versions": res.ctx.versions})
        self.assertTrue(io.read_own_jsonl(paths.judge_cache))
        self.assertTrue(os.path.isfile(paths.log_path))
        n = 0
        for root, _, files in os.walk(tmp):
            for name in files:
                with open(os.path.join(root, name), "rb") as f:
                    data = f.read()
                n += 1
                self.assertNotIn(KEY_VALUE.encode("utf-8"), data, name)
        self.assertGreaterEqual(n, 3)
        self.assertNotIn(KEY_VALUE, json.dumps(ok.sent_params(), ensure_ascii=False))


class RequestContentAndCacheTest(JudgeTestBase):
    def test_request_has_no_chunk_text_confidence_or_labeler_prompt(self):
        rec = Recorder()
        b = self.bundle()
        k = 0
        for r in b.records:  # 본문에 우연히 나올 수 없는 확신도 값으로 바꾼다
            for a in list(r["axes"].values()) + list(r["answers"].values()):
                k += 1
                a["confidence"] = float("0.7%06d3" % k)
        _run(b, llm_obj=llm.MockJudgeLLM(rec))
        records = {r["record_id"]: r for r in b.records}
        labeler_lines = []
        for name in ("classify.md", "label.md"):
            with open(os.path.join(REPO_ROOT, "prompts", name), encoding="utf-8") as f:
                for line in f:
                    s = line.strip().lstrip("-").strip()
                    # 제목 줄(#)은 문장이 아니다. qa_judge.md와 겹치는 제목은 리드에게 따로 알린다.
                    if len(s) >= 12 and not s.startswith("#"):
                        labeler_lines.append(s)
        self.assertGreater(len(labeler_lines), 10)
        self.assertTrue(rec.calls)
        for rid, messages, _ in rec.calls:
            whole = "\n".join(m["content"] for m in messages)
            user = messages[1]["content"]
            unit = b.units[rid]
            r = records[rid]
            quotes = {a["evidence"]["quote"] for a in r["axes"].values()} | {
                a["evidence"]["quote"] for a in r["answers"].values()}
            self.assertNotIn(unit["text"], whole)
            self.assertNotIn(unit["title"], user)
            for line in unit["text"].split("\n"):
                if line.strip() and not any(line in q or q in line for q in quotes if q):
                    self.assertNotIn(line, user)
            self.assertNotIn("confidence", whole)
            self.assertNotIn("확신도", whole)
            for a in list(r["axes"].values()) + list(r["answers"].values()):
                self.assertNotIn(repr(a["confidence"]), user)
            for s in labeler_lines:
                self.assertNotIn(s, whole)

    def test_rerun_uses_cache(self):
        b = self.bundle()
        res1, tmp = _run(b)
        self.assertGreater(res1.ctx.judge.calls, 0)
        rows = io.read_own_jsonl(io.QaPaths(tmp).judge_cache)
        self.assertEqual(len(rows), res1.ctx.judge.calls)
        res2, _ = _run(b.copy(), tmp=tmp)
        self.assertEqual(res2.ctx.judge.calls, 0)
        self.assertEqual(res2.ctx.judge.cache_hits, res1.ctx.judge.calls + res1.ctx.judge.cache_hits)
        strip = lambda vs: [{k: v[k] for k in ("record_id", "verdict", "issues", "judge")} for v in vs]
        self.assertEqual(strip(res1.verdicts), strip(res2.verdicts))

    def test_failed_responses_not_cached(self):
        b = self.bundle(small=True)

        def timeout(messages, file_ids, hint):
            raise llm.LLMError("TIMEOUT")

        res1, tmp = _run(b, llm_obj=llm.MockJudgeLLM(timeout))
        self.assertGreater(res1.ctx.judge.failed, 0)
        self.assertEqual(io.read_own_jsonl(io.QaPaths(tmp).judge_cache), [])
        res2, _ = _run(b.copy(), tmp=tmp)
        self.assertEqual(res2.ctx.judge.calls + res2.ctx.judge.cache_hits, _requests(res2))
        self.assertEqual(len(io.read_own_jsonl(io.QaPaths(tmp).judge_cache)), res2.ctx.judge.calls)
        self.assertEqual({v["verdict"] for v in res2.verdicts}, {"PASS"})


class UnitTest(unittest.TestCase):
    def test_term_in_word_boundary(self):
        self.assertFalse(llm.term_in("EM", "system 점검"))
        self.assertFalse(llm.term_in("M1", "M12 배선층"))
        self.assertTrue(llm.term_in("M1", "M1 배선층"))
        self.assertTrue(llm.term_in("M1", "M1배선층"))
        self.assertTrue(llm.term_in("em", "ＥＭ 불량"))
        self.assertTrue(llm.term_in("단락", "M2 라인 간 단락이 확인됨"))
        self.assertFalse(llm.term_in("", "아무 문장"))

    def test_mock_answer_rules(self):
        self.assertEqual(llm.judge_item({"kind": "answer", "answer": "O", "quote": "재발 여부는 미확인"})[0], "supported")
        self.assertEqual(llm.judge_item({"kind": "answer", "answer": "O", "quote": "추가 확인 불필요"})[0], "unsupported")
        self.assertEqual(llm.judge_item({"kind": "answer", "answer": "X", "quote": "추가 확인 불필요"})[0], "supported")
        self.assertEqual(llm.judge_item({"kind": "answer", "answer": "X", "quote": "후속 평가 필요"})[0], "unsupported")

    def test_parse_response(self):
        ids = {"a1", "q1"}
        good = '```json\n{"items": [{"id": "a1", "verdict": "supported", "reason": "r"},' \
               ' {"id": "q1", "verdict": "partial", "reason": "r"}]}\n```'
        self.assertEqual(judge.parse_response(good, ids)[0], {"a1": ("supported", "r"), "q1": ("partial", "r")})
        self.assertEqual(judge.parse_response("not json", ids), (None, "JSON_PARSE"))
        self.assertEqual(judge.parse_response('{"items": {}}', ids), (None, "FORMAT_INVALID"))
        self.assertEqual(judge.parse_response(
            '{"items": [{"id": "zz", "verdict": "supported", "reason": "r"}]}', ids), (None, "ITEM_UNKNOWN"))
        self.assertEqual(judge.parse_response(
            '{"items": [{"id": "a1", "verdict": "supported", "reason": 3},'
            ' {"id": "q1", "verdict": "supported", "reason": "r"}]}', ids), (None, "FORMAT_INVALID"))



class GeneratedQuestionTest(unittest.TestCase):
    """labelbot 검증 질문(Q-GEN-*): O는 라벨을 뒷받침, X는 반박한다는 뜻으로 judge에 보낸다."""

    def setUp(self):
        fx = fixturegen.generate(seed=7, n_files=2)
        self.bundle = fx.bundle.copy()
        snap = dict(fx.bundle.taxonomy)
        snap["questions"] = list(snap["questions"]) + [
            {"qid": "Q-GEN-aaaaaaaaaa", "text": "이 슬라이드는 단락 불량을 다루는가?", "target": ["불량 모드", "Short"],
             "generated": True}]
        self.bundle.taxonomy = snap
        self.rec = next(r for r in self.bundle.records if r["chunk_type"] == "내용")
        self.rid = self.rec["record_id"]

    def _answer(self, ans, quote):
        self.rec["answers"]["Q-GEN-aaaaaaaaaa"] = {"answer": ans, "confidence": 0.8,
                                                  "evidence": {"quote": quote, "unit_id": None, "start": None,
                                                               "end": None}}
        self.bundle.units[self.rid]["text"] += "\n" + quote
        self.bundle.units[self.rid]["text_canonical"] = None

    def _verdict(self):
        res, _ = _run(self.bundle.subset([self.rec["file_id"]]))
        return res.verdict_map()[self.rid]

    def test_render_uses_question_text_and_meaning(self):
        self._answer("O", "Center 영역 단락 불량 재현 확인")
        tax = model.TaxIndex(self.bundle.taxonomy)
        from qabot.engine import RecordTarget

        items = [it for it in judge.build_items(RecordTarget(self.rec, None), tax) if it["qid"] == "Q-GEN-aaaaaaaaaa"]
        self.assertEqual(len(items), 1)
        text = judge.render_item(items[0], tax)
        self.assertIn("이 슬라이드는 단락 불량을 다루는가?", text)
        self.assertIn('값 "Short"를 뒷받침한다', text)
        self.assertNotIn("Q-GEN-aaaaaaaaaa", text)

    def test_mock_supports_and_refutes(self):
        self._answer("O", "Center 영역 단락 불량 재현 확인")
        v = self._verdict()
        self.assertFalse([i for i in v["issues"] if i.get("field") == "answer:Q-GEN-aaaaaaaaaa"], v["issues"])
        self.setUp()
        self._answer("X", "Center 영역 단락 불량 재현 확인")
        v = self._verdict()
        self.assertIn("L3_NOT_SUPPORTED", [i["code"] for i in v["issues"] if i.get("field") == "answer:Q-GEN-aaaaaaaaaa"])
        self.setUp()
        self._answer("X", "Center 영역 단락 불량은 관찰되지 않음")
        v = self._verdict()
        self.assertFalse([i for i in v["issues"] if i.get("field") == "answer:Q-GEN-aaaaaaaaaa"], v["issues"])

    def test_no_unknown_field_for_generated(self):
        from qabot.checks import l1_schema

        self._answer("O", "Center 영역 단락 불량 재현 확인")
        out = l1_schema.evaluate(self.rec, model.TaxIndex(self.bundle.taxonomy), policy.validate_schema({}))
        self.assertNotIn("L1_UNKNOWN_FIELD", [i["code"] for i in out["issues"]])

if __name__ == "__main__":
    unittest.main()
