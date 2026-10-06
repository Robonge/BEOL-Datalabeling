"""질문 생성(질문 루프 A): 검수 결과 + 누적 교정 장부 → LLM → 엔지니어에게 물을 질문 묶음(questions.json).

설계는 domain_engrbot/docs/plan-question-loop.md 5.1절과 8절이다. 형식은 qmodel이 정한다.
- 무엇을 물을지·문장·선택지·초안은 LLM이 만든다. 이 모듈은 재료(context)를 모으고 응답을 검증·정리할 뿐 결정하지 않는다.
- LLM에는 파싱한 텍스트(제목·본문 앞부분·사람이 남긴 인용·이유·메모)만 넣는다. 전송은 llm_http(labelbot 공용 경로)만 거친다.
- 질문 문장·본문·인용은 questions.json과 화면에만 들어간다. 콘솔·generate_log에는 set_id·건수·사유 코드만 쓴다.
- 입력(context)이 지난 묶음과 같으면 LLM을 부르지 않고 그 묶음을 다시 쓴다. LLM이 실패하면 기존 묶음·화면을 그대로 둔다.
- 저장은 장부 잠금 안에서 asked.json·questions.json을 다시 읽어, 그사이 답한 질문을 빼고 쓴다(8.7절).
"""
import datetime
import glob
import json
import os
import random
import sqlite3

from domain_engrbot import io, ledger, model, qmodel
from domain_engrbot import labeling_rules as lr
from domain_engrbot.adapters import labelbot_ws
from domain_engrbot.llm import LLMError

PKG_ROOT = os.path.dirname(os.path.abspath(__file__))
QUESTIONS_PROMPT = os.path.join(PKG_ROOT, "prompts", "engr_questions.md")
DRAFT_PROMPT = os.path.join(PKG_ROOT, "prompts", "engr_draft.md")
DEFAULTS = {"max": 10, "model": None, "temperature": None, "timeout": 180, "max_retries": 1,
            "context": {"max_records": 40, "recent_percent": 60, "text_chars": 600, "max_cases": 120, "max_patterns": 60,
                        "max_history": 40}}
SYNONYMS_MAX = 200    # context에 넣는 taxonomy 동의어 최대 수(동의어 시트가 길어도 요청이 너무 커지지 않게)
REVISIT_MEMOS = 5     # 재검토 요청 하나에 붙이는 메모 최대 수
REASON_MAX = 300      # 사례 이유·메모 한 건의 최대 글자 수
INBOX_GLOB = "engr_answers_*.json"


class QuestionError(Exception):
    def __init__(self, reason_code):
        Exception.__init__(self, reason_code)
        self.reason_code = reason_code


# ---- 설정과 LLM ------------------------------------------------------------------

def config(policy):
    """기본값 위에 policy["questions"]를 병합한다(context는 칸 단위). 형식이 틀리면 QUESTIONS_CONFIG_INVALID."""
    user = (policy or {}).get("questions") or {}
    if not isinstance(user, dict) or not isinstance(user.get("context", {}), dict):
        raise QuestionError("QUESTIONS_CONFIG_INVALID")
    cfg = dict(DEFAULTS, **{k: v for k, v in user.items() if k != "context"})
    cfg["context"] = dict(DEFAULTS["context"], **(user.get("context") or {}))
    ints = [cfg["max"], cfg["timeout"], cfg["max_retries"]] + list(cfg["context"].values())
    if (any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in ints) or cfg["max"] < 1
            or cfg["context"]["recent_percent"] > 100):
        raise QuestionError("QUESTIONS_CONFIG_INVALID")
    if cfg["model"] is not None and not isinstance(cfg["model"], str):
        raise QuestionError("QUESTIONS_CONFIG_INVALID")
    if cfg["temperature"] is not None and (isinstance(cfg["temperature"], bool)
                                           or not isinstance(cfg["temperature"], (int, float))):
        raise QuestionError("QUESTIONS_CONFIG_INVALID")
    return cfg


def make_llm(ws_root, cfg, llm=None):
    """pipeline.json llm 블록에 questions 설정(model·temperature·timeout)을 덮어 OpenAI 호환 LLM을 만든다(judge.create와 같은 방식).
    questions 설정이 None(또는 빈 model)인 칸은 pipeline 값을 그대로 쓴다.
    base_url·model이 없으면 LLM_CONFIG_MISSING. 키 확인은 호출할 때 한다(KEY_MISSING)."""
    if llm is not None:
        return llm
    base = labelbot_ws.read_config(ws_root).get("llm") or {}
    c = dict(base)
    if cfg.get("model"):
        c["model"] = cfg["model"]
    for k in ("temperature", "timeout"):
        if cfg.get(k) is not None:
            c[k] = cfg[k]
    c["mode"] = "json"
    if not c.get("base_url") or not c.get("model"):
        raise QuestionError("LLM_CONFIG_MISSING")
    from domain_engrbot.llm_http import OpenAICompatJudgeLLM

    # 실제 전송 경로를 만들 때만 .env의 키를 읽는다(labelbot CLI는 시작할 때 읽는다)
    io.load_env()
    return OpenAICompatJudgeLLM(c)


def _prompt(path):
    """프롬프트 파일(코드 폴더의 평문 자산). 치환 없이 system 메시지로 그대로 넣는다."""
    with open(path, encoding="utf-8") as f:
        return f.read()


def _call_json(llm, system, user_obj, key, retries, stats, file_ids=()):
    """LLM을 불러 key 목록이 있는 JSON 객체를 받는다. 응답 전체가 JSON이 아니거나 key가 목록이 아니면 retries번 다시 부른다.
    전송 실패는 다시 부르지 않고 그 사유 코드로, 끝까지 틀리면 LLM_RESPONSE_INVALID로 QuestionError를 낸다."""
    from domain_engrbot.judge import extract_json

    messages = [{"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user_obj, ensure_ascii=False, sort_keys=True)}]
    for _ in range(retries + 1):
        stats["llm_calls"] += 1
        try:
            content = llm.complete(messages, sorted(set(file_ids)), None)
        except LLMError as e:
            raise QuestionError(e.reason_code)
        try:
            obj = extract_json(content)
        except ValueError:
            obj = None
        if isinstance(obj, dict) and isinstance(obj.get(key), list):
            return obj
    raise QuestionError("LLM_RESPONSE_INVALID")


# ---- 재료(context) -----------------------------------------------------------------

def _source_root(paths, source):
    """원래 작업 폴더 경로. 명령에 준 작업 폴더가 그 이름이면 그 경로, 아니면 <코드 폴더>/workspaces/<이름>. 없으면 None."""
    if os.path.basename(os.path.abspath(paths.root).rstrip("\\/")) == source:
        return paths.root
    if not isinstance(source, str) or not lr.SAFE_NAME.match(source) or source in (".", ".."):
        return None
    p = os.path.join(ledger.WORKSPACES_DIR, source)
    return p if os.path.isfile(os.path.join(p, "work.sqlite")) else None


def _endpoint(ws_root):
    """작업 폴더 pipeline.json의 llm.base_url(앞뒤 공백·끝 / 제거, 소문자). 못 읽거나 없으면 None."""
    try:
        url = (labelbot_ws.read_config(ws_root).get("llm") or {}).get("base_url")
    except (model.BundleError, OSError):
        return None
    url = url.strip().rstrip("/").lower() if isinstance(url, str) else ""
    return url or None


class _Sources(object):
    """출처 작업 폴더 → (경로, 사유 코드). 다른 작업 폴더의 본문·메모는 그 폴더의 LLM 전송처(llm.base_url)가 명령에 준
    작업 폴더와 같을 때만 context에 넣는다(보안 M2: 그 폴더가 정하지 않은 곳으로 본문을 보내지 않는다)."""

    def __init__(self, paths):
        self.paths = paths
        self.own = os.path.basename(os.path.abspath(paths.root).rstrip("\\/"))
        self.mine = None
        self.cache = {}

    def get(self, source):
        if source not in self.cache:
            root = _source_root(self.paths, source)
            if root is None:
                self.cache[source] = (None, "SOURCE_WS_MISSING")
            elif source == self.own:
                self.cache[source] = (root, None)
            else:
                if self.mine is None:
                    self.mine = _endpoint(self.paths.root) or ""
                same = bool(self.mine) and _endpoint(root) == self.mine
                self.cache[source] = (root, None) if same else (None, "SOURCE_ENDPOINT_DIFFERS")
        return self.cache[source]


def _plus(counter, code, n=1):
    counter[code] = counter.get(code, 0) + n


def _clip(s, n):
    s = " ".join(s.split()) if isinstance(s, str) else ""
    return s if len(s) <= n else s[:n].rstrip() + "…"


def _stage(rule):
    """승인 규칙의 단계(labelbot.feedback과 같은 기준). MANUAL은 target이 label이면 label, 아니면 classify."""
    kind = rule.get("kind")
    if kind in lr.ANSWER_KINDS or (kind == "MANUAL" and rule.get("target") == "label"):
        return "label"
    return "classify"


def _taxonomy(paths):
    snap = labelbot_ws.snapshot(labelbot_ws.load_taxonomy(paths.root, labelbot_ws.read_config(paths.root)))
    axes = [{"name": a["name"], "kind": a["kind"], "multi": a["multi"], "definition": a["definition"],
             "values": [{"name": v["name"], "parent": v["parent"], "definition": v["definition"]} for v in a["values"]]}
            for a in snap["axes"] if a["active"]]
    return {"axes": axes, "questions": [{"qid": q["qid"], "text": q["text"]} for q in snap["questions"]],
            "synonyms": snap["synonyms"][:SYNONYMS_MAX]}


def _answered(qd, n):
    """answers.jsonl 최근 n건 → 질문 문장·답(LLM이 겹치는 질문을 내지 않게)."""
    try:
        rows = io.read_own_jsonl(os.path.join(qd, qmodel.ANSWERS_LOG))
    except (ValueError, UnicodeDecodeError):
        raise QuestionError("ANSWERS_LOG_INVALID")
    out = []
    for r in rows[-n:] if n else []:
        if not isinstance(r, dict):
            continue
        drafts = [d.get("text") or d.get("definition") or "" for d in r.get("confirmed") or [] if isinstance(d, dict)]
        out.append({"question": _clip(r.get("text") or r.get("question_text") or "", qmodel.QUESTION_MAX),
                    "action": r.get("action") or "", "answer": _clip(r.get("option_label") or "", qmodel.LABEL_MAX),
                    "free_text": _clip(r.get("free_text") or "", qmodel.LABEL_MAX),
                    "drafts": [_clip(t, qmodel.RULE_TEXT_MAX) for t in drafts if t]})
    return out


class Context(object):
    """LLM 입력(data)과 ref 풀이표. ref: 패턴은 rule_id, 사례 C1…, 레코드 R1…, 재검토 V1…."""

    def __init__(self):
        self.data = {}
        self.patterns = {}      # rule_id → 패턴(지금 승인 대기만이 질문의 patterns가 된다)
        self.pending = set()
        self.cases = {}         # C ref → 장부 사례
        self.records = {}       # R ref → 장부 레코드
        self.revisits = {}      # V ref → 질문의 revisits 칸
        self.examples = {}      # (record_id, text_hash) → 승인 대기 사례 ID(EX-)
        self.case_times = {}    # case_id → 교정 반영 시각(닫힌 질문을 다시 열지 판정할 때 쓴다)
        self.axes = []
        self.file_ids = set()
        self.counts = {}
        self.has_input = False


def _rec_key(r):
    return (r["record_id"], r.get("text_hash") or "")


def pick_records(recs, recent_ws, max_n, percent, seed):
    """레코드 표본(사용자 결정 D11): 가장 최근 작업 폴더에서 percent%(recs 순서 = 교정 많은 순), 나머지는 전체 기간에서
    결정적 무작위(random.Random(seed)). 한쪽이 모자라면 다른 쪽으로 채워 합이 min(max_n, len(recs))가 된다.
    반환: (최근 몫, 무작위 몫). 무작위 몫도 recs 순서로 둔다."""
    total = min(max_n, len(recs))
    mine = [r for r in recs if r["source_ws"] == recent_ws]
    recent = mine[:min(len(mine), round(max_n * percent / 100), total)]
    taken = {id(r) for r in recent}
    rest = [r for r in recs if id(r) not in taken]
    # 최근 폴더의 남은 레코드도 무작위 풀에 든다. 그래서 다른 폴더가 모자라면 최근 폴더에서 더 뽑힌다
    chosen = random.Random(seed).sample(range(len(rest)), total - len(recent))
    return recent, [rest[i] for i in sorted(chosen)]


def build_context(paths, policy, d, qd, carried, max_new, rules_path=None, cfg=None):
    """누적 장부와 작업 폴더에서 context를 모은다. 본문을 못 읽은 레코드는 본문을 빼고 사유 코드만 센다."""
    cfg = cfg or config(policy)
    cc = cfg["context"]
    lrcfg = lr.config(policy)
    rules_doc = lr.load_rules(rules_path)
    cases = lr._latest_cases(d)
    cands = lr.candidates(d, rules_doc, lrcfg)
    syn_rows = ledger.read(d, ledger.SYNONYMS)
    rev_rows = ledger.read(d, ledger.REVISITS)
    ctx = Context()
    ctx.has_input = bool(cases or syn_rows or rev_rows)
    ctx.pending = {r["rule_id"] for r in cands["rules"]}
    ctx.examples = {(e["record_id"], e.get("text_hash") or ""): e["example_id"] for e in cands["examples"]}
    tax = _taxonomy(paths)
    ctx.axes = [a["name"] for a in tax["axes"]]
    ctx.case_times = {c["case_id"]: c.get("applied_at") or "" for c in cases}
    body_missing = {}
    sources = _Sources(paths)

    # 레코드: 교정이 있는 것만(교정이 많은 순). 최근 작업 폴더 몫과 전체 기간 무작위 몫으로 나눠 뽑는다
    n_corr = {}
    for c in cases:
        if c["kind"] == ledger.CORRECTED:
            _plus(n_corr, (c["record_id"], c.get("text_hash") or ""))
    recs = [r for r in ledger.latest_records(d) if (r["record_id"], r.get("text_hash") or "") in n_corr]
    recs.sort(key=lambda r: (-n_corr[(r["record_id"], r.get("text_hash") or "")], r["record_id"]))
    # 시드는 장부 입력(작업 폴더별 corrections_sha)에서 만든다: 같은 장부면 같은 표본(재사용 판정 유지), 새 검수가 들어오면 바뀐다
    seed = int(model.hash_obj(sorted([s["source_ws"], s.get("corrections_sha") or ""]
                                     for s in ledger.read(d, ledger.SOURCES)))[:16], 16)
    recent_ws = os.path.basename(os.path.abspath(paths.root).rstrip("\\/"))
    recent, sampled = pick_records(recs, recent_ws, cc["max_records"], cc["recent_percent"], seed)
    recs = recent + sampled
    picked = {_rec_key(r) for r in recs}
    by_source = {}
    for r in recs:
        by_source.setdefault(r["source_ws"], []).append(r["record_id"])
    chunks = {}
    skipped = set()   # 출처 단위로 이미 사유를 센 작업 폴더(레코드마다 CHUNK_MISSING으로 또 세지 않는다)
    for source, ids in sorted(by_source.items()):
        root, why = sources.get(source)
        if root is None:
            _plus(body_missing, why, len(ids))
            skipped.add(source)
            continue
        try:
            got = labelbot_ws.chunk_context(root, ids)
        except (model.BundleError, sqlite3.Error):
            _plus(body_missing, "SOURCE_DB_UNREADABLE", len(ids))
            skipped.add(source)
            continue
        for cid, v in got.items():
            chunks[(source, cid)] = v
    rec_ref = {}
    records = []
    for i, r in enumerate(recs, 1):
        ref = "R%d" % i
        ctx.records[ref] = r
        rec_ref.setdefault(r["record_id"], ref)
        rec_ref[(r["record_id"], r.get("text_hash") or "")] = ref
        ctx.file_ids.add(r.get("file_id") or "")
        item = {"ref": ref, "final_axes": r.get("final_axes") or {}, "corrected_axes": r.get("corrected_axes") or []}
        eid = ctx.examples.get((r["record_id"], r.get("text_hash") or ""))
        if eid:
            item["example_id"] = eid
        ch = chunks.get((r["source_ws"], r["record_id"]))
        if ch is None:
            if r["source_ws"] not in skipped:
                _plus(body_missing, "CHUNK_MISSING")
        elif ch.get("text_hash") != r.get("text_hash"):
            _plus(body_missing, "TEXT_CHANGED")
        else:
            item.update(title=ch.get("title") or "", text=_clip(ch.get("text") or "", cc["text_chars"]))
        records.append(item)

    # 사례: 뽑힌 레코드의 사례 → (그 안에서) 근거·이유가 있는 교정 → 교정 → 확인 순
    ev = {e["case_id"]: e for e in ledger.read_evidence(d)}
    order = sorted(cases, key=lambda c: (_rec_key(c) not in picked, c["kind"] != ledger.CORRECTED,
                                         c["case_id"] not in ev, c["case_id"]))
    case_ref = {}
    out_cases = []
    for i, c in enumerate(order[:cc["max_cases"]], 1):
        ref = "C%d" % i
        ctx.cases[ref] = c
        case_ref[c["case_id"]] = ref
        e = ev.get(c["case_id"]) or {}
        item = {"ref": ref, "field": c["field"], "kind": c["kind"], "bot": c.get("bot_value"),
                "human": c.get("human_value"),
                "record": rec_ref.get((c["record_id"], c.get("text_hash") or ""))}
        # 인용·이유도 문서 조각이다: 본문과 같은 조건(출처 작업 폴더의 전송처가 같음)일 때만 넣는다. 교정 값은 그대로 간다.
        if (e.get("evidence") or e.get("reason")) and sources.get(c["source_ws"])[0] is None:
            _plus(body_missing, "EVIDENCE_" + sources.get(c["source_ws"])[1][len("SOURCE_"):])
            e = {}
        if e.get("evidence"):
            item["evidence"] = [{"kind": ledger.evidence_kind(x, c["record_id"]), "slide_no": x.get("slide_no"),
                                 "quote": x.get("quote")} for x in e["evidence"]]
        if e.get("reason"):
            item["reason"] = _clip(e["reason"], REASON_MAX)
        out_cases.append(item)

    # 패턴: 미결정(승인·기각하지 않은) 것, 승인 대기·상충·건수 순
    decided = {r.get("rule_id") for r in rules_doc["rules"] if isinstance(r, dict)} | set(rules_doc["rejected"])
    pats = [p for p in lr.all_rules(cases, 1).values() if p["rule_id"] not in decided]
    pats.sort(key=lambda p: (p["rule_id"] not in ctx.pending, not p["conflict"], -p["count"], p["rule_id"]))
    out_pats = []
    for p in pats[:cc["max_patterns"]]:
        ctx.patterns[p["rule_id"]] = p
        out_pats.append({"ref": p["rule_id"], "kind": p["kind"], "target": p["target"], "from": p["from"],
                         "to": p["to"], "count": p["count"], "reverse_count": p["reverse_count"],
                         "conflict": p["conflict"], "pending": p["rule_id"] in ctx.pending,
                         "evidence_count": p["evidence_count"],
                         "cases": [case_ref[x] for x in p["evidence_cases"] if x in case_ref],
                         "records": sorted({rec_ref[x] for x in p["records"] if x in rec_ref})})

    # 축별 확인·교정 수(전체 사례 기준)
    stats = {}
    for c in cases:
        kind, _, key = c["field"].partition(":")
        if kind == "axis":
            _plus(stats.setdefault(key, {"confirmed": 0, "corrected": 0}), c["kind"])

    # 재검토 요청: 장부 건수 + 각 작업 폴더 reports/taxonomy_revisit.jsonl의 메모·제안 값
    memo_rows = {}
    for source in sorted({r["source_ws"] for r in rev_rows}):
        root, why = sources.get(source)
        if root is None:
            if why == "SOURCE_ENDPOINT_DIFFERS":
                _plus(body_missing, "REVISIT_ENDPOINT_DIFFERS")
            continue
        try:
            rows = io.read_own_jsonl(os.path.join(root, "reports", "taxonomy_revisit.jsonl"))
        except (ValueError, UnicodeDecodeError):
            _plus(body_missing, "REVISIT_FILE_INVALID")
            continue
        for x in rows:
            if isinstance(x, dict):
                memo_rows.setdefault((source, x.get("reason"), x.get("target"), x.get("key")), []).append(x)
    out_rev = []
    for i, r in enumerate(rev_rows, 1):
        ref = "V%d" % i
        rows = memo_rows.get((r["source_ws"], r["reason"], r["target_kind"], r["target_key"]), [])
        memos = list(dict.fromkeys(_clip(x.get("memo"), REASON_MAX) for x in rows if x.get("memo")))[:REVISIT_MEMOS]
        proposed = sorted({(x.get("proposed") or {}).get("value") for x in rows
                           if isinstance(x.get("proposed"), dict) and isinstance(x["proposed"].get("value"), str)})
        ctx.revisits[ref] = {"reason": r["reason"], "target": r["target_kind"], "key": r["target_key"],
                             "memo": _clip(" / ".join(memos), qmodel.MEMO_MAX), "count": r["count"]}
        out_rev.append({"ref": ref, "reason": r["reason"], "target": r["target_kind"], "key": r["target_key"],
                        "count": r["count"], "memos": memos, "proposed": proposed})

    approved = [{"stage": _stage(r), "target": r.get("target") or "", "text": r["text"]}
                for r in rules_doc["rules"] if lr.valid_rule(r) and r.get("enabled", True)]
    ctx.data = {
        "taxonomy": tax, "patterns": out_pats, "cases": out_cases, "records": records, "axis_stats": stats,
        "revisits": out_rev,
        "synonyms_registered": [{"alias": s["alias"], "canonical": s["canonical"], "axis": s.get("axis") or "",
                                 "count": s.get("count", 1)} for s in syn_rows],
        "approved_rules": approved, "answered": _answered(qd, cc["max_history"]),
        "open": [{"goal": q.get("goal"), "topic": q.get("topic"), "text": q.get("text")} for q in carried],
        "limits": {"max_new": max_new},
    }
    ctx.counts = {"cases": len(out_cases), "patterns": len(out_pats), "records": len(records),
                  "records_recent": len(recent), "records_random": len(sampled),
                  "revisits": len(out_rev), "body_missing": dict(sorted(body_missing.items()))}
    return ctx


# ---- 응답 정리 ------------------------------------------------------------------

def _clean_drafts(raw, ctx, axes, patterns, examples, drop):
    """초안 목록 정리. rule의 pattern_ref가 지금 승인 대기 패턴이면 pattern_id로 옮기고 그 패턴을 patterns에 더한다.
    example은 그 질문의 사례 후보(examples)만 받는다. 틀린 초안은 버리고 drop에 센다."""
    out = []
    for d in raw if isinstance(raw, list) else []:
        if isinstance(d, dict) and d.get("type") == "rule":
            ref = d.get("pattern_ref") or d.get("pattern_id")
            d = {k: v for k, v in d.items() if k not in ("pattern_ref", "pattern_id")}
            if ref in ctx.pending and ref in ctx.patterns:
                d["pattern_id"] = ref
        got, code = qmodel.check_draft(d, axes)
        if got is not None and got["type"] == "example" and got["example_id"] not in examples:
            got, code = None, "DRAFT_EXAMPLE_UNKNOWN"
        if got is None:
            _plus(drop, code)
            continue
        if got.get("pattern_id") and got["pattern_id"] not in patterns:
            patterns.append(got["pattern_id"])
        out.append(got)
        if len(out) >= qmodel.MAX_DRAFTS:
            break
    return out


def clean_question(raw, ctx, drop):
    """LLM 질문 하나 → 정리한 질문 또는 None(사유는 drop에 센다)."""
    if not isinstance(raw, dict) or raw.get("goal") not in qmodel.GOALS:
        _plus(drop, "QUESTION_FORMAT_INVALID")
        return None
    text = qmodel.clean_text(raw.get("text"), qmodel.QUESTION_MAX)
    why = qmodel.soft_text(raw.get("why"), qmodel.WHY_MAX)
    if text is None or why is None:
        _plus(drop, "QUESTION_TEXT_INVALID")
        return None
    topic = qmodel.normalize_topic(raw.get("topic"))
    refs = [r for r in raw.get("refs") or [] if isinstance(r, str)] if isinstance(raw.get("refs"), list) else []
    known = [r for r in dict.fromkeys(refs) if r in ctx.patterns or r in ctx.cases or r in ctx.records
             or r in ctx.revisits]
    if len(known) < len(refs):
        _plus(drop, "REF_UNKNOWN", len(refs) - len(known))
    evidence, patterns, revisits = [], [], []
    for r in known:
        if r in ctx.cases:
            evidence.append(ctx.cases[r]["case_id"])
        elif r in ctx.records:
            rec = ctx.records[r]
            evidence += [c["case_id"] for c in ctx.cases.values()
                         if c["kind"] == ledger.CORRECTED and c["record_id"] == rec["record_id"]
                         and (c.get("text_hash") or "") == (rec.get("text_hash") or "")]
        elif r in ctx.revisits:
            revisits.append(dict(ctx.revisits[r]))
        elif r in ctx.pending:
            patterns.append(r)
    evidence = list(dict.fromkeys(evidence))
    by_case = {c["case_id"]: c for c in ctx.cases.values()}
    examples = []
    for cid in evidence:
        c = by_case[cid]
        eid = ctx.examples.get((c["record_id"], c.get("text_hash") or ""))
        if eid and eid not in examples:
            examples.append(eid)
    options = []
    raw_opts = raw.get("options") if isinstance(raw.get("options"), list) else []
    for o in raw_opts:
        label = qmodel.clean_text(o.get("label"), qmodel.LABEL_MAX) if isinstance(o, dict) else None
        if label is None:
            _plus(drop, "OPTION_INVALID")
            continue
        drafts = _clean_drafts(o.get("drafts"), ctx, ctx.axes, patterns, examples, drop)
        options.append({"option_id": chr(ord("A") + len(options)), "label": label, "drafts": drafts})
        if len(options) >= qmodel.MAX_OPTIONS:
            break
    n_recs = len({(by_case[c]["record_id"], by_case[c].get("text_hash") or "") for c in evidence})
    n_pat = max([ctx.patterns[p]["count"] for p in patterns] or [0])
    fp = qmodel.fingerprint(raw["goal"], topic, text)
    return {"question_id": qmodel.question_id(fp), "fingerprint": fp, "goal": raw["goal"], "topic": topic,
            "text": text, "why": why, "carried": False, "evidence": evidence, "patterns": patterns,
            "examples": examples, "revisits": revisits, "impact": {"records": max(n_recs, n_pat)},
            "options": options}


def _open_questions(doc, asked):
    """지난 묶음에서 아직 열린 질문(답함·묻지 않음이 아닌 것). carried=True로 둔다."""
    return [dict(q, carried=True) for q in (doc or {}).get("questions") or [] if not qmodel.is_closed(asked, q)]


def _drop_closed(qs, asked, case_times):
    """새 질문 중 닫힌 것을 뺀다. 지문이 닫혀 있어도 그때 없던 근거(새 승인 대기 패턴, 닫은 뒤 반영된 교정 사례)가
    붙었으면 다시 열고 "reopened": true를 적는다(8.3절, qmodel.is_closed). 반환: (남긴 질문, 뺀 수)."""
    keep, closed = [], 0
    for q in qs:
        q = {k: v for k, v in q.items() if k != "reopened"}
        if qmodel.closed_by(asked, q) is not None:
            if qmodel.is_closed(asked, q, case_times):
                closed += 1
                continue
            q["reopened"] = True
        keep.append(q)
    return keep, closed


# ---- 화면·이력 ------------------------------------------------------------------

def _build_screen(qd, d, policy, roots=None):
    """질문 화면(작업 C). 늦게 import한다. roots({작업 폴더 이름: 경로})는 workspaces/ 밖 작업 폴더의 축·미리보기용이다."""
    from domain_engrbot import question_screen

    return question_screen.build(qd, d, policy=policy, roots=roots)


def _roots(paths):
    return {os.path.basename(paths.root.rstrip("\\/")): paths.root}


def screen_label(qd):
    return "%s/%s" % (qmodel.dir_label(qd), qmodel.SCREEN)


def _iso(now):
    return now.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log(qd, row):
    os.makedirs(qd, exist_ok=True)
    io.append_jsonl(os.path.join(qd, qmodel.GENERATE_LOG), row)


def _summary(doc, llm_calls, reused, reason):
    qs = (doc or {}).get("questions") or []
    return {"set_id": (doc or {}).get("set_id"), "questions": len(qs),
            "labeling": sum(1 for q in qs if q.get("goal") == "labeling"),
            "taxonomy": sum(1 for q in qs if q.get("goal") == "taxonomy"),
            "carried": sum(1 for q in qs if q.get("carried")), "llm_calls": llm_calls, "reused": reused,
            "reason": reason}


# ---- 생성 -----------------------------------------------------------------------

def generate(paths, policy, llm=None, qd=None, rules_path=None, now=None, force=False, max_n=None):
    """질문 묶음을 만든다. 반환은 건수만: {"set_id", "questions", "labeling", "taxonomy", "carried", "llm_calls",
    "reused", "reason", "dropped", "dup_in_set", "closed"}."""
    cfg = config(policy)
    if not ledger.config(policy).get("enabled"):
        raise QuestionError("LEDGER_DISABLED")
    limit = cfg["max"] if max_n is None else max_n
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise QuestionError("QUESTIONS_CONFIG_INVALID")
    now = now or datetime.datetime.now(datetime.timezone.utc)
    ledger.intake(paths.root, policy)
    d = ledger.ledger_dir(paths.root, policy)
    qd = qd or qmodel.qdir(d)
    prev = qmodel.load_set(qd)
    asked = qmodel.load_asked(qd)
    carried = _open_questions(prev, asked)
    need = max(0, limit - len(carried))
    ctx = build_context(paths, policy, d, qd, carried, need, rules_path=rules_path, cfg=cfg)
    # 이월 질문(open)과 그에 따른 max_new는 지난 묶음에서 나오므로 재사용 판정에서 빼고 요청 상한(limit)만 넣는다
    core = {k: v for k, v in ctx.data.items() if k not in ("open", "limits")}
    digest = model.hash_obj({"context": core, "limit": limit, "prompt": model.sha256_text(_prompt(QUESTIONS_PROMPT))})
    inputs = {s["source_ws"]: s.get("corrections_sha") for s in ledger.read(d, ledger.SOURCES)}
    stats = {"llm_calls": 0}
    log = {"at": _iso(now), "context": ctx.counts, "dropped": {}, "dup_in_set": 0, "closed": 0}

    if not ctx.has_input:
        if carried:
            # 이월 질문이 있으면 0건 묶음으로 덮지 않는다(8.9절)
            out = _summary(prev, 0, False, "NO_REVIEW_INPUT")
        else:
            doc = qmodel.empty_set(os.path.basename(paths.root.rstrip("\\/")), qmodel.new_set_id(now), _iso(now))
            doc.update(context_digest=digest, inputs=inputs)
            with ledger.locked(d):
                qmodel.save_set(qd, doc)
            out = _summary(doc, 0, False, "NO_REVIEW_INPUT")
        _build_screen(qd, d, policy, _roots(paths))
        _log(qd, dict(log, **out))
        return dict(out, dropped=0, dup_in_set=0, closed=0)

    if prev is not None and prev.get("context_digest") == digest and not force:
        if prev.get("inputs") != inputs:
            # 장부 sha만 바뀐 경우(context는 같음)에도 inputs를 맞춰 workspaces의 question_state가 new로 남지 않게 한다
            with ledger.locked(d):
                cur = qmodel.load_set(qd)
                if cur is not None:
                    prev = dict(cur, inputs=inputs)
                    qmodel.save_set(qd, prev)
        _build_screen(qd, d, policy, _roots(paths))
        out = _summary(prev, 0, True, None)
        _log(qd, dict(log, **out))
        return dict(out, dropped=0, dup_in_set=0, closed=0)

    fresh, drop, dup, closed = [], {}, 0, 0
    name = ""
    if need > 0:
        try:
            llm = make_llm(paths.root, cfg, llm)
            name = getattr(llm, "name", "") or ""
            resp = _call_json(llm, _prompt(QUESTIONS_PROMPT), ctx.data, "questions", cfg["max_retries"], stats,
                              ctx.file_ids - {""})
        except QuestionError as e:
            _log(qd, dict(log, set_id=None, llm_calls=stats["llm_calls"], reused=False, reason=e.reason_code))
            raise
        seen = {q["fingerprint"] for q in carried}
        for raw in resp["questions"]:
            q = clean_question(raw, ctx, drop)
            if q is None:
                continue
            if q["fingerprint"] in seen:
                dup += 1
                continue
            seen.add(q["fingerprint"])
            fresh.append(q)
        fresh, n = _drop_closed(fresh, asked, ctx.case_times)
        closed += n
    with ledger.locked(d):
        # 그사이 답한 질문이 있을 수 있으므로 잠금 안에서 다시 읽는다(8.7절)
        asked = qmodel.load_asked(qd)
        cur = qmodel.load_set(qd)
        carried = _open_questions(cur, asked)
        fps = {q["fingerprint"] for q in carried}
        keep, n = _drop_closed([q for q in fresh if q["fingerprint"] not in fps], asked, ctx.case_times)
        closed += n
        keep = keep[:max(0, limit - len(carried))]
        for q in keep:
            q["created_at"] = _iso(now)   # 이 시각 뒤에 반영된 교정만 "그때 없던 근거"다(qmodel.is_closed)
        model_name = name or (cur or prev or {}).get("model") or ""
        if keep or cur is None:
            doc = qmodel.empty_set(os.path.basename(paths.root.rstrip("\\/")), qmodel.new_set_id(now), _iso(now))
            doc.update(questions=carried + keep)
        else:
            # 새 질문이 없으면(이월만 남음) set_id·generated_at을 유지한다(포트와 화면의 진행 상황이 이어지게)
            doc = dict(cur, questions=[q for q in cur["questions"] if not qmodel.is_closed(asked, q)])
        doc.update(model=model_name, context_digest=digest, inputs=inputs)
        qmodel.save_set(qd, doc)
    _build_screen(qd, d, policy, _roots(paths))
    out = _summary(doc, stats["llm_calls"], False, None)
    n_drop = sum(drop.values())
    _log(qd, dict(log, dropped=dict(sorted(drop.items())), dup_in_set=dup, closed=closed, **out))
    return dict(out, dropped=n_drop, dup_in_set=dup, closed=closed)


# ---- 자유 답 → 초안 ---------------------------------------------------------------

def draft_for_answer(question, answer_text, llm, axes, retries=1):
    """엔지니어의 자유 답 → 초안 목록(qmodel.check_draft를 통과한 것만, 최대 MAX_DRAFTS).
    답 문장이 틀리면 ANSWER_TEXT_INVALID, 응답이 틀리면 LLM_RESPONSE_INVALID, 유효한 초안이 없으면 DRAFT_EMPTY."""
    if not isinstance(question, dict):
        raise QuestionError("QUESTION_NOT_OPEN")
    text = qmodel.clean_text(answer_text, qmodel.FREE_MAX)
    if text is None:
        raise QuestionError("ANSWER_TEXT_INVALID")
    if llm is None:
        raise QuestionError("DRAFT_UNAVAILABLE")
    q = {k: question.get(k) for k in ("goal", "topic", "text", "why", "patterns", "examples")}
    resp = _call_json(llm, _prompt(DRAFT_PROMPT), {"question": q, "answer": text, "axes": sorted(axes or [])},
                      "drafts", retries, {"llm_calls": 0})
    ctx = Context()
    ctx.pending = set(question.get("patterns") or [])
    ctx.patterns = {p: {} for p in ctx.pending}
    patterns = list(question.get("patterns") or [])
    drafts = _clean_drafts(resp["drafts"], ctx, axes, patterns, set(question.get("examples") or []), {})
    if not drafts:
        raise QuestionError("DRAFT_EMPTY")
    return drafts


def make_drafter(paths, policy, qd, cfg=None):
    """질문 서버에 넘길 drafter(question_id, answer_text) 또는 None(LLM 설정이 없을 때). 반환: (drafter, 사유 코드)."""
    cfg = cfg or config(policy)
    try:
        llm = make_llm(paths.root, cfg)
        axes = [a["name"] for a in _taxonomy(paths)["axes"]]
    except (QuestionError, model.BundleError) as e:
        return None, e.reason_code

    def drafter(question_id, answer_text):
        try:
            doc = qmodel.load_set(qd)
        except qmodel.QModelError as e:
            raise QuestionError(e.reason_code)
        q = qmodel.question_map(doc).get(question_id)
        if q is None:
            raise QuestionError("QUESTION_NOT_OPEN")
        return draft_for_answer(q, answer_text, llm, axes, cfg["max_retries"])

    return drafter, None


# ---- 상태 -----------------------------------------------------------------------

def _inbox(paths, open_ids):
    """<WS>/qa/inbox/engr_answers_*.json 목록(최근 것부터). 답 파일은 사람 입력이므로 read_json_input으로 읽고 건수만 낸다."""
    out = []
    files = glob.glob(os.path.join(paths.inbox, INBOX_GLOB))
    for p in sorted(files, key=lambda x: (-os.path.getmtime(x), os.path.basename(x))):
        row = {"name": os.path.basename(p),
               "saved_at": datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M:%S"),
               "set_id": None, "answer": 0, "dismiss": 0, "skip": 0, "open_matches": 0, "reason": None}
        if os.path.getsize(p) > qmodel.MAX_ANSWER_BYTES:
            row["reason"] = "ANSWERS_TOO_LARGE"
            out.append(row)
            continue
        try:
            doc = io.read_json_input(p)
        except (ValueError, UnicodeDecodeError, OSError, RecursionError):
            row["reason"] = "ANSWERS_JSON_INVALID"
            out.append(row)
            continue
        if not (isinstance(doc, dict) and doc.get("kind") == qmodel.ANSWERS_KIND and isinstance(doc.get("answers"), list)):
            row["reason"] = "ANSWERS_FORMAT_INVALID"
            out.append(row)
            continue
        row["set_id"] = doc.get("set_id") if qmodel.valid_set_id(doc.get("set_id")) else None
        for a in doc["answers"]:
            if isinstance(a, dict) and a.get("action") in qmodel.ACTIONS:
                row[a["action"]] += 1
                # 반영할 것이 있는 답만 센다(나중에는 반영할 내용이 없다)
                row["open_matches"] += a["action"] != "skip" and a.get("question_id") in open_ids
        out.append(row)
    return out


def status(paths, policy, rules_path=None):
    """건수만(본문 없음): 지금 묶음, 답함·묻지 않음 누계, 승인 대기 후보, inbox의 답 파일."""
    d = ledger.ledger_dir(paths.root, policy)
    qd = qmodel.qdir(d)
    doc = qmodel.load_set(qd)
    asked = qmodel.load_asked(qd)
    qs = _open_questions(doc, asked)
    cands = lr.candidates(d, lr.load_rules(rules_path), lr.config(policy))
    return {"dir": qmodel.dir_label(qd), "set_id": (doc or {}).get("set_id"), "open": len(qs),
            "labeling": sum(1 for q in qs if q.get("goal") == "labeling"),
            "taxonomy": sum(1 for q in qs if q.get("goal") == "taxonomy"),
            "carried": sum(1 for q in (doc or {}).get("questions") or [] if q.get("carried")),
            "answered_total": len(asked["answered"]), "dismissed_total": len(asked["dismissed"]),
            "pending_patterns": len(cands["rules"]), "pending_examples": len(cands["examples"]),
            "inbox": _inbox(paths, {q["question_id"] for q in qs})}


# ---- CLI ------------------------------------------------------------------------

def _apply_line(r):
    return ("[questions] 반영: 답 %d(규칙 %d · taxonomy 제안 %d · 사례 %d), 후보 승인 %d · 종결 %d, 묻지 않음 %d, "
            "건너뜀 %d, 남은 질문 %d" % (r["answered"], r["rules"], r["taxonomy"], r["examples"],
                                     r["patterns_approved"], r["patterns_closed"], r["dismissed"], r["skipped"],
                                     r["remaining"]))


RESULT_KEYS = ("answered", "dismissed", "skipped", "rules", "taxonomy", "examples", "patterns_approved",
               "patterns_closed", "remaining", "invalid", "not_open", "notes")


def refresh_board():
    """taxonomy 수정 보드를 다시 만든다(LLM 0회, 기본 대상). 반환: {"code", "lines"}. 실패해도 반영은 그대로다."""
    from types import SimpleNamespace

    from domain_engrbot import taxonomy_board

    lines = []
    try:
        code = taxonomy_board.main_cli(SimpleNamespace(workspace=None, taxonomy=None, out_dir=None, reset=False,
                                                       open=False), lines.append)
    except Exception as e:  # 보드는 부가 단계다. 코드만 남긴다
        code = getattr(e, "reason_code", None) or "BOARD_FAILED"
        lines.append("[taxonomy-board] 갱신 실패: %s" % code)
    return {"code": code, "lines": lines}


def make_applier(paths, pol, qd):
    """질문 서버의 '답변 완료 · 저장' 직후 부르는 반영 콜러블(사용자 결정, 2026-10-06: 저장 버튼이 반영의 승인이다).
    반환 콜러블(path) → {"lines": 콘솔 줄, "result": 건수·ID·코드, "board": 보드 건수 줄 또는 None}.
    반영 오류는 answers.AnswersError(reason_code)로 올린다. taxonomy 제안이 생기면 보드도 다시 만든다."""
    from domain_engrbot import answers

    def run(path):
        r = answers.apply(paths, pol, answers_path=path, qd=qd)
        lines = [_apply_line(r)]
        extra = {k: r[k] for k in ("invalid", "not_open", "notes") if r.get(k)}
        if extra:
            lines.append(io.dumps(extra))
        board = None
        if r["taxonomy"]:
            b = refresh_board()
            lines += b["lines"]
            board = next((x for x in b["lines"] if x.startswith("[taxonomy-board] 항목")), None)
        return {"lines": lines, "result": {k: r[k] for k in RESULT_KEYS if k in r}, "board": board}
    return run


def _cli(args, paths, say):
    from domain_engrbot import policy as policy_mod

    pol, _ = policy_mod.load(paths)
    d = ledger.ledger_dir(paths.root, pol)
    qd = qmodel.qdir(d)
    act = args.action
    if act == "generate":
        r = generate(paths, pol, force=args.force, max_n=args.max)
        if r["reason"] == "NO_REVIEW_INPUT" and r["questions"]:
            say("[questions] 질문 재료 없음(NO_REVIEW_INPUT). 남은 질문 %d건 대기 → %s" % (r["questions"], screen_label(qd)))
        elif r["reason"] == "NO_REVIEW_INPUT":
            say("[questions] 질문 재료 없음(NO_REVIEW_INPUT)")
        elif r["reused"]:
            say("[questions] 재사용: 입력이 그대로다(LLM 0회). 질문 %d건 대기 → %s" % (r["questions"], screen_label(qd)))
        else:
            say("[questions] set_id=%s 질문 %d건(라벨링 %d · taxonomy %d, 이월 %d), LLM 호출 %d회 → %s" % (
                r["set_id"], r["questions"], r["labeling"], r["taxonomy"], r["carried"], r["llm_calls"],
                screen_label(qd)))
        return 0
    if act == "status":
        say(io.dumps(status(paths, pol)))
        return 0
    if qmodel.load_set(qd) is None and act in ("screen", "serve"):
        say("[오류] QUESTIONS_NOT_FOUND (questions generate로 먼저 만든다)")
        return 1
    if act == "screen":
        n = _build_screen(qd, d, pol, _roots(paths))
        say("[questions] 화면을 다시 만들었다(질문 %d건) → %s" % (n, screen_label(qd)))
        return 0
    if act == "serve":
        from domain_engrbot import serve

        drafter, why = (None, "NO_DRAFT") if args.no_draft else make_drafter(paths, pol, qd)
        if drafter is None:
            say("[questions] 초안 만들기 없이 띄운다(%s)" % why)
        applier = None if args.no_apply else make_applier(paths, pol, qd)
        return serve.serve_questions(paths, qd, port=args.port, drafter=drafter, applier=applier)
    from domain_engrbot import answers

    try:
        r = answers.apply(paths, pol, answers_path=args.answers, qd=qd)
    except answers.AnswersError as e:
        say("[오류] %s" % e.reason_code)
        return 1
    say(_apply_line(r))
    extra = {k: r[k] for k in ("invalid", "not_open", "notes") if r.get(k)}
    if extra:
        say(io.dumps(extra))
    return 0


def main_cli(args, paths, say):
    """questions generate|status|screen|serve|apply. 건수·ID·코드만 낸다. 오류는 [오류] <코드>, 종료 코드 1."""
    from domain_engrbot.question_screen import QuestionScreenError

    try:
        return _cli(args, paths, say)
    except (QuestionError, qmodel.QModelError, ledger.LedgerError, lr.LabelingRulesError, model.BundleError,
            QuestionScreenError) as e:
        say("[오류] %s" % e.reason_code)
        return 1
