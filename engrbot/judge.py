"""L3(b) LLM judge(5.5절, 7절). labelbot을 import하지 않는다.

흐름: 항목 조립 → 요청 조립 → 캐시 조회 → 전송 → JSON 추출 → 검증 → 실패하면 max_retries까지 재시도
→ 그래도 실패하면 그 호출의 모든 항목에 L3_JUDGE_FAILED.
- judge에는 인용, 라벨, 라벨 정의, 인용에 나온 동의어만 준다. chunk 본문, 확신도, 다른 축의 값은 주지 않는다.
- 교정 장부의 사람 검수 예시(set_examples)가 있으면 user 메시지 맨 앞에 붙이고, 예시 출처 file_id도 전송 판정에
  넣는다. 예시가 없으면 요청은 예시 기능이 없을 때와 바이트 단위로 같다.
- 캐시 키는 실제 전송한 요청 전체의 해시다. 검증을 통과한 응답만 캐시한다.
- 로그에는 단계, 레코드 ID, 사유 코드만 남긴다.
"""
import hashlib
import json
import os
import re
import threading

from engrbot import io, model
from engrbot.checks.l1_schema import ALL
from engrbot.llm import LLMError, MockJudgeLLM, term_in

PROMPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts", "qa_judge.md")
USER_MARK = "<!-- USER -->"
JUDGE_VERDICTS = ("supported", "partial", "unsupported")
LABEL_O = "해당하는 진술이 있다"
LABEL_X = "이 주제를 다루면서 해당하지 않는다고 밝혔다"
GEN_LABEL_O = '인용문이 축 "%s"의 값 "%s"를 뒷받침한다'
GEN_LABEL_X = '인용문이 축 "%s"의 값 "%s"를 반박한다'
EXAMPLE_HEADER = "## 사람 검수 사례 (판정 참고용. 판정 대상이 아니며 응답과 reason에 사례 인용을 옮기지 않는다)"
EXAMPLE_VERDICT = {"unsupported": "unsupported(사람이 이 라벨을 뺐다)",
                   "supported": "supported(사람이 이 라벨을 확인했다)"}
_WS = re.compile(r"\s+")


def read_prompt():
    """judge 프롬프트 파일(코드 폴더의 평문 자산) bytes."""
    with open(PROMPT_PATH, "rb") as f:
        return f.read()


def prompt_hash(raw=None):
    """judge 프롬프트 sha256. reviewer 버전 문자열(runner.versions)과 Judge.prompt_hash가 같은 값을 쓴다."""
    return hashlib.sha256(read_prompt() if raw is None else raw).hexdigest()


class JudgeUnavailable(Exception):
    def __init__(self, reason_code):
        Exception.__init__(self, reason_code)
        self.reason_code = reason_code


def create(policy, llm_cfg=None, cache_path=None, log=None, llm=None):
    """policy.judge와 pipeline llm 블록으로 Judge를 만든다. 설정이 없으면 JudgeUnavailable."""
    jc = policy["judge"]
    if llm is None:
        if jc["transport"] == "mock":
            llm = MockJudgeLLM()
        else:
            if not llm_cfg or not llm_cfg.get("base_url"):
                raise JudgeUnavailable("LLM_CONFIG_MISSING")
            cfg = dict(llm_cfg)
            if jc.get("model"):
                cfg["model"] = jc["model"]
            cfg["temperature"] = jc["temperature"]
            cfg["timeout"] = jc["timeout"]
            cfg["mode"] = jc["mode"]
            if not cfg.get("model"):
                raise JudgeUnavailable("LLM_MODEL_MISSING")
            from engrbot.llm_http import OpenAICompatJudgeLLM

            llm = OpenAICompatJudgeLLM(cfg)
    return Judge(policy, llm, cache_path=cache_path, log=log)


# ---- 응답 JSON ----------------------------------------------------------------

class DuplicateKey(ValueError):
    pass


def _pairs_no_dup(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise DuplicateKey(k)
        out[k] = v
    return out


def extract_json(content):
    """코드 블록으로 감싼 응답도 읽는다. 키가 중복되면 DuplicateKey, 못 읽으면 None."""
    if not isinstance(content, str):
        return None
    s = content.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else ""
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(s[start:end + 1], object_pairs_hook=_pairs_no_dup)
    except DuplicateKey:
        raise
    except ValueError:
        return None


def parse_response(content, ids):
    """반환: ({id: (verdict, reason)}, None) 또는 (None, 사유 코드)."""
    try:
        obj = extract_json(content)
    except DuplicateKey:
        return None, "DUPLICATE_KEY"
    if obj is None:
        return None, "JSON_PARSE"
    if not isinstance(obj, dict) or not isinstance(obj.get("items"), list):
        return None, "FORMAT_INVALID"
    out = {}
    for it in obj["items"]:
        if not isinstance(it, dict) or not isinstance(it.get("id"), str):
            return None, "FORMAT_INVALID"
        if it["id"] not in ids:
            return None, "ITEM_UNKNOWN"
        if it["id"] in out:
            return None, "ITEM_DUPLICATE"
        if it.get("verdict") not in JUDGE_VERDICTS:
            return None, "VERDICT_INVALID"
        if not isinstance(it.get("reason"), str):
            return None, "FORMAT_INVALID"
        out[it["id"]] = (it["verdict"], it["reason"])
    if len(out) != len(ids):
        return None, "ITEM_MISSING"
    return out, None


# ---- 항목 ------------------------------------------------------------------

def _quote(entry):
    ev = entry.get("evidence") if isinstance(entry, dict) else None
    q = ev.get("quote") if isinstance(ev, dict) else None
    return q if isinstance(q, str) else ""


def build_items(target, tax):
    """(축, 값) 쌍마다, O·X 답마다 항목 하나. id는 정렬한 축 이름·값 순서로 a1.., 정렬한 질문 ID로 q1..이다."""
    rec, broken = target.record, target.broken
    items = []
    if ALL in broken:
        return items
    axes = rec.get("axes") if isinstance(rec.get("axes"), dict) else {}
    if "axes" not in broken:
        for name in sorted(axes):
            a = axes[name]
            field = "axis:%s" % name
            if field in broken or not isinstance(a, dict) or a.get("status") != "value":
                continue
            quote = _quote(a)
            if not quote.strip():
                continue
            for v in a.get("values") or []:
                if not isinstance(v, str) or tax.is_reserved(v):
                    continue
                items.append({"id": "a%d" % (len(items) + 1), "kind": "axis", "field": field, "axis": name,
                              "value": v, "aliases": tax.synonyms_for(v), "qid": None, "answer": None, "quote": quote})
    answers = rec.get("answers") if isinstance(rec.get("answers"), dict) else {}
    if "answers" not in broken:
        n = 0
        for qid in sorted(answers):
            a = answers[qid]
            field = "answer:%s" % qid
            if field in broken or not isinstance(a, dict) or a.get("answer") not in ("O", "X"):
                continue
            quote = _quote(a)
            if not quote.strip():
                continue
            n += 1
            q = tax.questions.get(qid) or {}
            target = q.get("target") if q.get("generated") else None
            gen_axis, gen_value = (target[0], target[1]) if isinstance(target, (list, tuple)) and len(target) == 2 \
                else (None, None)
            items.append({"id": "q%d" % n, "kind": "answer", "field": field, "axis": gen_axis, "value": gen_value,
                          "aliases": tax.synonyms_for(gen_value) if gen_value else [], "qid": qid,
                          "answer": a["answer"], "quote": quote, "generated": bool(gen_value)})
    return items


def render_item(it, tax):
    lines = ["- id: %s" % it["id"]]
    if it["kind"] == "axis":
        lines.append('  라벨: 축 "%s"의 값 "%s"' % (it["axis"], it["value"]))
        d = _WS.sub(" ", tax.definition(it["axis"], it["value"])).strip()
        if d:
            lines.append("  라벨 정의: %s" % d)
        syn = [a for a in it["aliases"] if term_in(a, it["quote"])]
        if syn:
            lines.append("  동의어: %s" % ", ".join("%s → %s" % (a, it["value"]) for a in syn))
    elif it.get("generated"):
        # labelbot 검증 질문: O는 라벨을 뒷받침, X는 라벨을 반박한다는 뜻이다
        q = tax.questions.get(it["qid"]) or {}
        text = _WS.sub(" ", q.get("text") or "").strip()
        meaning = GEN_LABEL_O if it["answer"] == "O" else GEN_LABEL_X
        lines.append('  라벨: 검증 질문 "%s"의 답 "%s"(%s)' % (text, it["answer"], meaning % (it["axis"], it["value"])))
        d = _WS.sub(" ", tax.definition(it["axis"], it["value"])).strip()
        if d:
            lines.append("  라벨 정의: %s" % d)
    else:
        q = tax.questions.get(it["qid"]) or {}
        text = _WS.sub(" ", q.get("text") or it["qid"]).strip()
        lines.append('  라벨: 질문 "%s"의 답 "%s"(%s)' % (text, it["answer"], LABEL_O if it["answer"] == "O" else LABEL_X))
    lines.append('  인용문: """%s"""' % it["quote"].replace('"""', '" " "'))
    return "\n".join(lines)


# ---- 사람 검수 예시(교정 장부 judge_examples.jsonl) ---------------------------------

def item_key(it):
    """판정 항목의 예시 색인 키. 축 ("axis", 축, 값), 승인 질문 ("answer", qid, 답), Q-GEN ("gen", 축, 값, 답)."""
    if it["kind"] == "axis":
        return ("axis", it["axis"], it["value"])
    if it.get("generated"):
        return ("gen", it["axis"], it["value"], it["answer"])
    return ("answer", it["qid"], it["answer"])


def example_key(row):
    """장부 예시 행의 색인 키. 형식이 어긋난 행은 None."""
    if not isinstance(row, dict) or row.get("verdict") not in EXAMPLE_VERDICT:
        return None
    if not all(isinstance(row.get(k), str) and row.get(k) for k in ("example_id", "file_id", "quote")):
        return None
    if row.get("kind") == "axis":
        key = ("axis", row.get("axis"), row.get("value"))
    elif row.get("kind") == "answer" and row.get("generated"):
        key = ("gen", row.get("axis"), row.get("value"), row.get("answer"))
    elif row.get("kind") == "answer":
        key = ("answer", row.get("qid"), row.get("answer"))
    else:
        return None
    return key if all(isinstance(k, str) and k for k in key) else None


def _one_line(s):
    return _WS.sub(" ", s or "").strip()


def render_example(ex, tax):
    """예시 한 건. 장부 값은 데이터로만 다룬다. 축·값·질문은 한 줄로 접고, 인용은 한 줄 JSON 문자열로 넣어
    줄바꿈·제목·"- id:" 줄로 가짜 항목이나 절을 만들 수 없게 한다."""
    if ex["kind"] == "axis":
        label = '축 "%s"의 값 "%s"' % (_one_line(ex["axis"]), _one_line(ex["value"]))
    elif ex.get("generated"):
        meaning = GEN_LABEL_O if ex["answer"] == "O" else GEN_LABEL_X
        label = '검증 질문의 답 "%s"(%s)' % (_one_line(ex["answer"]),
                                         meaning % (_one_line(ex["axis"]), _one_line(ex["value"])))
    else:
        q = tax.questions.get(ex["qid"]) or {}
        label = '질문 "%s"의 답 "%s"' % (_one_line(q.get("text") or ex["qid"]), _one_line(ex["answer"]))
    return "\n".join(["- 라벨: %s" % label,
                      "  인용문(JSON 문자열): %s" % json.dumps(_one_line(ex["quote"]), ensure_ascii=False),
                      "  사람 판정: %s" % EXAMPLE_VERDICT[ex["verdict"]]])


def render_examples(examples, tax):
    return "\n".join([EXAMPLE_HEADER] + [render_example(ex, tax) for ex in examples])


def _hint_item(it):
    out = {k: it[k] for k in ("id", "kind", "axis", "value", "aliases", "qid", "answer", "quote")}
    out["generated"] = bool(it.get("generated"))
    return out


# ---- judge -----------------------------------------------------------------

class Judge(object):
    """calls는 실제로 보낸 요청 수, failed는 재시도 뒤에도 실패한 호출 수다.

    example_stats(사람 검수 예시):
    - loaded: set_examples로 색인한 고유 예시 수
    - calls_with_examples: 예시를 넣은 요청 수(캐시 적중 요청 포함, 재시도는 세지 않는다)
    - used: 요청마다 넣은 예시 수의 누적(같은 예시가 여러 요청에 들어가면 그만큼 센다)
    - excluded_same_source, excluded_external: 요청마다 뺀 예시 수의 누적(한 요청 안에서는 예시당 한 번)
    """

    def __init__(self, policy, llm, cache_path=None, log=None):
        jc = policy["judge"]
        self.llm = llm
        self.name = getattr(llm, "name", None) or type(llm).__name__
        self.max_retries = int(jc["max_retries"])
        self.max_items = int(jc["max_items_per_call"])
        self.cache_path = cache_path
        self.log = log or io.null_log
        raw = read_prompt()
        self.prompt_hash = prompt_hash(raw)
        system, _, user = raw.decode("utf-8").partition(USER_MARK)
        self.system_prompt = system.strip()
        self.user_template = user.strip()
        self.calls = 0
        self.cache_hits = 0
        self.failed = 0
        self._lock = threading.Lock()
        self._cache = {}
        # 사람 검수 예시. set_examples를 부르지 않으면 비어 있고 요청은 예시 없는 것과 같다
        self._examples = {}
        self.k_per_item = 2
        self.max_per_call = 6
        self.example_stats = {"loaded": 0, "calls_with_examples": 0, "used": 0, "excluded_same_source": 0,
                              "excluded_external": 0}
        if cache_path:
            for row in io.read_own_jsonl(cache_path):
                if isinstance(row, dict) and isinstance(row.get("key"), str) and isinstance(row.get("response"), str):
                    self._cache[row["key"]] = row["response"]

    def sent_params(self):
        return self.llm.sent_params()

    def _count(self, attr):
        with self._lock:
            setattr(self, attr, getattr(self, attr) + 1)

    def set_examples(self, rows, k_per_item=2, max_per_call=6):
        """장부 예시 행을 키별로 색인한다. 같은 example_id는 하나로 합치고, 키마다 unsupported를 먼저,
        그다음 supported를 example_id 순으로 둔다. 형식이 어긋난 행은 버린다."""
        index = {}
        for row in rows or []:
            key = example_key(row)
            if key is not None:
                index.setdefault(key, {}).setdefault(row["example_id"], row)
        self._examples = {k: sorted(v.values(), key=lambda r: (r["verdict"] != "unsupported", r["example_id"]))
                          for k, v in index.items()}
        self.k_per_item = max(1, int(k_per_item))
        self.max_per_call = max(1, int(max_per_call))
        with self._lock:
            self.example_stats["loaded"] = len({r["example_id"] for v in self._examples.values() for r in v})

    def select_examples(self, items, target):
        """이 호출에 넣을 예시. 대상과 같은 파일·같은 본문(SAME_SOURCE)과 전송이 허용되지 않는 출처
        (EXTERNAL_BLOCKED)는 뺀다. 항목당 k_per_item개, 호출당 max_per_call개, 중복 없음."""
        if not self._examples:
            return []
        own_hash = (target.unit or {}).get("text_hash")
        chosen, seen, same, blocked = [], set(), set(), set()
        for it in items:
            if len(chosen) >= self.max_per_call:
                break
            n = 0
            for ex in self._examples.get(item_key(it), []):
                if n >= self.k_per_item or len(chosen) >= self.max_per_call:
                    break
                eid = ex["example_id"]
                if eid in seen:
                    n += 1
                    continue
                if eid in same or eid in blocked:
                    continue
                if ex["file_id"] == target.file_id or (own_hash and ex.get("text_hash") == own_hash):
                    same.add(eid)
                    continue
                if not self.llm.allows(ex["file_id"]):
                    blocked.add(eid)
                    continue
                seen.add(eid)
                chosen.append(ex)
                n += 1
        with self._lock:
            st = self.example_stats
            st["excluded_same_source"] += len(same)
            st["excluded_external"] += len(blocked)
            if chosen:
                st["calls_with_examples"] += 1
                st["used"] += len(chosen)
        return chosen

    def messages(self, items, tax, examples=None):
        body = "\n".join(render_item(it, tax) for it in items)
        user = self.user_template.replace("{{items}}", body)
        if examples:
            user = render_examples(examples, tax) + "\n\n" + user
        return [{"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user}]

    def _call(self, items, target, tax):
        """반환: ({id: (verdict, reason)}, None) 또는 (None, 사유 코드)."""
        ids = {it["id"] for it in items}
        examples = self.select_examples(items, target)
        messages = self.messages(items, tax, examples)
        file_ids = [target.file_id] + sorted({ex["file_id"] for ex in examples} - {target.file_id})
        key = model.hash_obj(self.llm.request_identity(messages))
        with self._lock:
            cached = self._cache.get(key)
        if cached is not None:
            res, _ = parse_response(cached, ids)
            if res is not None:
                self._count("cache_hits")
                return res, None
        hint = {"record_id": target.record_id, "items": [_hint_item(it) for it in items]}
        last = "FORMAT_INVALID"
        for _ in range(1 + self.max_retries):
            try:
                content = self.llm.complete(messages, file_ids, hint)
            except LLMError as e:
                last = e.reason_code
                if not e.sent:
                    break
                self._count("calls")
                continue
            self._count("calls")
            res, reason = parse_response(content, ids)
            if res is not None:
                with self._lock:
                    self._cache[key] = content
                if self.cache_path:
                    io.append_jsonl(self.cache_path, {"key": key, "response": content, "created_at": model.now_iso()})
                return res, None
            last = reason
        return None, last

    def evaluate(self, target, ctx):
        items = build_items(target, ctx.tax)
        stats = {"items": len(items), "supported": 0, "partial": 0, "unsupported": 0, "failed": 0}
        issues = []
        for k in range(0, len(items), self.max_items):
            chunk = items[k:k + self.max_items]
            results, reason_code = self._call(chunk, target, ctx.tax)
            if results is None:
                self._count("failed")
                self.log("judge", target.record_id, reason_code)
                stats["failed"] += len(chunk)
                for it in chunk:
                    issues.append(model.issue(
                        "L3_JUDGE_FAILED", field=it["field"], evidence={"reason_code": reason_code, "item": it["id"]},
                        suggested_fix="judge 설정과 전송 허용 여부를 확인하고 다시 돌린다."))
                continue
            for it in chunk:
                verdict, reason = results[it["id"]]
                stats[verdict] += 1
                if verdict == "supported":
                    continue
                evidence = {"item": it["id"], "label": it["value"] if it["kind"] == "axis" else it["answer"],
                            "judge_reason": reason[:200],
                            "quote_sha256": hashlib.sha256(it["quote"].encode("utf-8")).hexdigest()}
                if verdict == "unsupported":
                    issues.append(model.issue("L3_NOT_SUPPORTED", field=it["field"], evidence=evidence, reason=reason,
                                              suggested_fix="인용이 이 라벨을 직접 말하는지 확인하고, 아니면 라벨이나 근거를 고친다."))
                else:
                    issues.append(model.issue("L3_PARTIALLY_SUPPORTED", field=it["field"], evidence=evidence,
                                              reason=reason, suggested_fix="라벨을 붙이는 데 필요한 내용이 인용에 들어가는지 확인한다."))
        target.judge = stats
        return issues
