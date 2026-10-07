"""검수 피드백 소비: 승인 파일(taxonomy/labeling_rules.json)의 규칙·사례 → 1차 분류·3차 라벨링 프롬프트.

생산(교정 수집, 규칙·사례 후보, 사람 확정)은 Domain-Engr-bot이 맡는다(Domain-Engr-bot 질문 답변: `domain_engrbot/answers.py`, `python -m domain_engrbot questions apply`).
이 모듈은 승인 파일을 읽기만 하고 아무것도 쓰지 않는다.

- 규칙: 축·값·질문 ID·건수·문장만 있다(본문 없음). 사람이 문장(text)을 고치거나 enabled를 끄거나 MANUAL 규칙을 더할 수 있다.
- 사례: (source_ws, record_id=chunk_id, text_hash) 참조와 확정 라벨만 있다. 본문·임베딩은 실행할 때 원래 작업 폴더의
  work.sqlite에서 읽기 전용으로 읽는다. 그 작업 폴더가 없거나 본문이 바뀌었으면 그 사례는 쓰지 않는다(사유 코드로 센다).
- 같은 파일·같은 본문(text_hash, dup_hash)의
  사례는 그 chunk에 쓰지 않는다(자기 정답 누설 방지).
"""
import json
import math
import os
import re
import sqlite3
import threading

from labelbot import ingest, store, util
from labelbot.workspace import CODE_ROOT, is_inside

RULES_FILENAME = "labeling_rules.json"
NA, UNKNOWN = "해당 없음", "unknown"
SPECIAL = (NA, UNKNOWN)
AXIS_KINDS = ("REPLACE", "REMOVE", "ADD")
ANSWER_KINDS = ("ANSWER", "GEN_ANSWER")
STAGES = ("classify", "label")
GEN_PREFIX = "Q-GEN-"
NONE_TEXT = "(없음)"
TEXT_MAX = 300
SAFE_NAME = re.compile(r"^[^\\/:*?\"<>|]+$")


class FeedbackError(Exception):
    pass


# ---- 설정과 승인 파일 ---------------------------------------------------------

def _cfg(ws):
    return ws.config.get("feedback") or {}


def _path_cfg(ws, key, default):
    p = _cfg(ws).get(key)
    if p and not os.path.isabs(p):
        p = os.path.join(ws.root, p)
    return p or default


def rules_path(ws):
    """승인 파일. 기본은 코드 폴더 taxonomy/ 아래 한 곳(작업 폴더마다 갈라지지 않게)."""
    return _path_cfg(ws, "rules_path", os.path.join(CODE_ROOT, "taxonomy", RULES_FILENAME))


def examples_root(ws):
    """사례의 원래 작업 폴더를 찾는 곳. 기본은 코드 폴더 workspaces/."""
    return _path_cfg(ws, "examples_root", os.path.join(CODE_ROOT, "workspaces"))


def load_rules(ws):
    """승인 파일(사람이 고치는 입력)을 read_input으로 읽는다. 없으면 빈 문서. 형식이 틀리면 FeedbackError."""
    p = rules_path(ws)
    doc = {"rules": [], "examples": []}
    if not os.path.isfile(p):
        return doc
    try:
        got = json.loads(ingest.read_input(p, None, expect="text"))
    except ValueError:
        raise FeedbackError("RULES_JSON_INVALID")
    if not isinstance(got, dict) or any(not isinstance(got.get(k, []), list) for k in ("rules", "examples")):
        raise FeedbackError("RULES_FORMAT_INVALID")
    doc["rules"] = got.get("rules") or []
    doc["examples"] = got.get("examples") or []
    return doc


RULE_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


def _valid_rule(r):
    return (isinstance(r, dict) and isinstance(r.get("rule_id"), str) and bool(RULE_ID.match(r["rule_id"]))
            and isinstance(r.get("text"), str) and r["text"].strip() and len(r["text"]) <= TEXT_MAX
            and r.get("kind") in AXIS_KINDS + ANSWER_KINDS + ("MANUAL",)
            and isinstance(r.get("target", ""), str) and isinstance(r.get("from", ""), str)
            and isinstance(r.get("to", ""), str))


def _valid_example(e):
    return (isinstance(e, dict) and isinstance(e.get("example_id"), str)
            and isinstance(e.get("source_ws"), str) and bool(SAFE_NAME.match(e["source_ws"]))
            and e["source_ws"] not in (".", "..") and isinstance(e.get("record_id"), str)
            and isinstance(e.get("text_hash"), str) and isinstance(e.get("final_axes"), dict))


QUOTE_MAX = 200
_BRACE_OPEN, _BRACE_CLOSE = re.compile(r"\{(?=\{)"), re.compile(r"\}(?=\})")


def _defang(text):
    """프롬프트 치환(prompts.py의 {{키}})이 피드백 블록 안을 펼치지 못하게 '{{'·'}}'를 '{ {'·'} }'로 바꾼다."""
    return _BRACE_CLOSE.sub("} ", _BRACE_OPEN.sub("{ ", text))


def _evidence_text(x, record_id):
    """근거 한 항목 → "[위치] '인용'". 인용은 QUOTE_MAX자에서 자른다."""
    if x["source"] == "chunk":
        where = "같은 슬라이드" if x["chunk_id"] == record_id else (
            "다른 슬라이드 %s" % x["slide_no"] if x["slide_no"] is not None else "다른 슬라이드")
    else:
        where = "파일명" if x["source"] == "file_name" else "문서 제목"
    q = x["quote"]
    if len(q) > QUOTE_MAX:
        q = q[:QUOTE_MAX].rstrip() + " …"
    return "[%s] '%s'" % (where, q)


def _as_list(v):
    if v is None:
        return []
    out = []
    for x in v if isinstance(v, list) else [v]:
        x = str(x).strip()
        if x and x not in out:
            out.append(x)
    return out


# ---- 유사도 ---------------------------------------------------------------------

def _ngrams(text, n=3):
    s = "".join(util.norm_for_match(text).split())
    if len(s) < n:
        return {s} if s else set()
    return {s[i : i + n] for i in range(len(s) - n + 1)}


def _jaccard(a, b):
    return len(a & b) / float(len(a | b)) if a and b else 0.0


def _cosine(a, b):
    num = sum(x * y for x, y in zip(a, b))
    da = math.sqrt(sum(x * x for x in a))
    db = math.sqrt(sum(y * y for y in b))
    return num / (da * db) if da and db else 0.0


# ---- 실행용 객체 ----------------------------------------------------------------

class NullFeedback(object):
    """피드백을 쓰지 않을 때. 프롬프트 블록은 '(없음)'."""

    enabled = False

    def __init__(self, reason="꺼짐"):
        self.reason = reason

    def prepare(self, ws, con, run_id, chunks, log=None):
        return None

    def rules_text(self, stage, questions=None):
        return NONE_TEXT

    def examples_for(self, chunk):
        return NONE_TEXT, []

    def digest(self):
        return None

    def applied(self):
        return {"enabled": False, "reason": self.reason}

    def applied_rules(self):
        return empty_record()

    def summary_line(self):
        return "[feedback] %s: 승인 규칙·사례를 넣지 않습니다." % self.reason


def _skipped_text(skipped):
    return ", ".join("%s %d" % kv for kv in sorted(skipped.items())) or "없음"


class Feedback(object):
    """승인 규칙·사례를 프롬프트 블록으로 만든다. prepare() 뒤에는 메모리만 쓰므로 병렬 분류에서 불러도 된다."""

    enabled = True

    def __init__(self, cfg, rules, examples, skipped, invalid_rules):
        self.cfg = cfg
        self.classify_rules = [r for r in rules if r["_stage"] == "classify"]
        self.label_rules = [r for r in rules if r["_stage"] == "label"]
        self.examples = examples
        self.skipped = skipped
        self.invalid_rules = invalid_rules
        self.k = int(cfg.get("examples_k") or 0)
        self.chars = int(cfg.get("example_chars") or 800)
        self.same_file = bool(cfg.get("exclude_same_file", True))
        ms = cfg.get("min_similarity") or {}
        self.min_sim = {"embedding": float(ms.get("embedding", 0.5)), "lexical": float(ms.get("lexical", 0.05))}
        self.chunk_vecs = {}
        self.mode = "none" if not examples else "lexical"
        self.lock = threading.Lock()
        self.used = {"chunks_with_examples": 0, "examples_used": 0, "scored_embedding": 0, "scored_lexical": 0}
        for e in self.examples:
            e["_grams"] = _ngrams(e["text"])

    def prepare(self, ws, con, run_id, chunks, log=None):
        """유사도 준비. 임베딩을 쓸 수 있으면 이번 실행 chunk를 임베딩한다.

        기존 embed(가드·멱등)를 출력·실패 기록 없이 부르고, 저장된 벡터는 검수 뒤 embed 단계가 다시 쓴다(호출 0회).
        """
        if not self.examples or self.k <= 0:
            self.mode = "none"
            return
        want = (self.cfg.get("similarity") or "auto").lower()
        emb = ws.config.get("embedding") or {}
        if want in ("auto", "embedding") and emb.get("enabled") and any(e["vec"] for e in self.examples):
            from labelbot import embed

            embed.embed(ws, con, run_id, log=log, quiet=True)
            ids = [c["chunk_id"] for c in chunks]
            for i in range(0, len(ids), 500):
                part = ids[i : i + 500]
                for r in con.execute(
                    "SELECT e.chunk_id, e.vector FROM chunk_embeddings e JOIN chunks c ON c.chunk_id=e.chunk_id "
                    "WHERE e.model=? AND e.text_hash=c.text_hash AND e.chunk_id IN (%s)" % ",".join("?" * len(part)),
                    [emb.get("model")] + part):
                    self.chunk_vecs[r[0]] = embed.unpack(r[1])
            self.mode = "embedding" if self.chunk_vecs else "lexical"
        else:
            self.mode = "lexical"

    def _pool(self, chunk):
        th, dh = chunk.get("text_hash"), chunk.get("dup_hash")
        out = []
        for e in self.examples:
            if self.same_file and e["file_id"] == chunk.get("file_id"):
                continue
            if (th and e["text_hash"] == th) or (dh and e["dup_hash"] == dh):
                continue
            out.append(e)
        return out

    def _score(self, chunk):
        """한 chunk 안에서는 한 방식으로만 순위를 낸다. 반환: (방식, [(유사도, 사례)])."""
        pool = self._pool(chunk)
        vec = self.chunk_vecs.get(chunk.get("chunk_id"))
        if vec is not None and any(e["vec"] for e in pool):
            return "embedding", [(_cosine(vec, e["vec"]), e) for e in pool if e["vec"]]
        grams = _ngrams(chunk.get("text") or "")
        return "lexical", [(_jaccard(grams, e["_grams"]), e) for e in pool]

    @staticmethod
    def _block(i, e, body):
        fixed, seen = e["corrected"], set(e["confirmed"])
        lines = ["### 사례 %d (%s)" % (i, "사람이 교정" if fixed else "사람이 확인"), "본문 앞부분:", body]
        if fixed:
            lines.append("사람이 고친 축: %s" % "; ".join(
                "%s 봇[%s]→사람[%s]" % (k, ",".join(v["bot"]), ",".join(v["human"])) for k, v in sorted(fixed.items())))
            for k in sorted(fixed):
                ev = (e.get("evidence") or {}).get(k)
                if ev and ev["items"]:
                    line = "근거(%s): %s" % (k, " · ".join(_evidence_text(x, e.get("record_id")) for x in ev["items"]))
                    if ev["reason"]:
                        line += " / 이유: %s" % ev["reason"]
                    lines.append(line)
        ok = [(k, v) for k, v in e["final_axes"].items() if k in seen and k not in fixed]
        if ok:
            lines.append("사람이 확인한 축: %s" % "; ".join("%s=%s" % (k, ",".join(v)) for k, v in ok))
        rest = [(k, v) for k, v in e["final_axes"].items() if k not in seen and k not in fixed]
        if rest:
            lines.append("검수하지 않은 축(봇 값, 참고만): %s" % "; ".join("%s=%s" % (k, ",".join(v)) for k, v in rest))
        return "\n".join(lines)

    def examples_for(self, chunk):
        """chunk에 넣을 사례 블록과 그 사례들의 파일 ID. 고를 사례가 없으면 ('(없음)', [])."""
        if not self.examples or self.k <= 0:
            return NONE_TEXT, []
        how, scored = self._score(chunk)
        floor = self.min_sim[how]
        top = sorted((s for s in scored if s[0] >= floor), key=lambda s: (-s[0], s[1]["example_id"]))[: self.k]
        with self.lock:
            self.used["scored_" + how] += 1
            if top:
                self.used["chunks_with_examples"] += 1
                self.used["examples_used"] += len(top)
        if not top:
            return NONE_TEXT, []
        blocks = []
        for i, (_, e) in enumerate(top, 1):
            body = (e["text"] or "").strip()
            if len(body) > self.chars:
                body = body[: self.chars].rstrip() + " …"
            blocks.append(self._block(i, e, body))
        return _defang("\n\n".join(blocks)), sorted({e["file_id"] for _, e in top})

    def rules_text(self, stage, questions=None):
        if stage == "classify":
            rules = self.classify_rules
        else:
            qids = {q.qid for q in questions or []}
            gens = {"%s=%s" % tuple(q.target) for q in questions or []
                    if q.qid.startswith(GEN_PREFIX) and isinstance(q.target, tuple) and len(q.target) == 2}
            pairs = {"%s=%s" % tuple(q.target) for q in questions or []
                     if isinstance(q.target, tuple) and len(q.target) == 2}
            rules = [r for r in self.label_rules
                     if (r["kind"] == "MANUAL" and _manual_label_hit(r, qids, pairs))
                     or (r["kind"] == "ANSWER" and r.get("target") in qids)
                     or (r["kind"] == "GEN_ANSWER" and r.get("target") in gens)]
        return _defang("\n".join("- [%s] %s" % (r["rule_id"], " ".join(r["text"].split())) for r in rules)) or NONE_TEXT

    def digest(self):
        return _digest(self.classify_rules + self.label_rules, [e["example_id"] for e in self.examples],
                       self.k, self.chars)

    def applied_rules(self):
        """meta rules_applied:<run>에 남길 기록(규칙 해시·종류·대상, 사례 ID). 실제로 프롬프트에 들어간 규칙이다."""
        return _record(self.classify_rules + self.label_rules, [e["example_id"] for e in self.examples])

    def applied(self):
        out = {"enabled": True, "rules_classify": len(self.classify_rules), "rules_label": len(self.label_rules),
               "rules_invalid": self.invalid_rules, "examples_pool": len(self.examples),
               "examples_skipped": dict(sorted(self.skipped.items())), "similarity": self.mode, "digest": self.digest()}
        out.update(self.used)
        return out

    def summary_line(self):
        return "[feedback] 승인 규칙 분류 %d·라벨 %d개, 사례 풀 %d개(제외 %s), 유사도 %s" % (
            len(self.classify_rules), len(self.label_rules), len(self.examples), _skipped_text(self.skipped), self.mode)


# ---- 읽기 ------------------------------------------------------------------------

def _rules_for_run(doc, tax, cap, only_axes=None):
    """켜진 유효 규칙 → 단계(_stage) 붙인 목록과 형식 오류 수. 축 규칙은 활성 축과 taxonomy 값만 받는다.
    only_axes(axis-update 대상 축)를 주면 다른 축을 겨냥한 축 규칙·MANUAL 규칙은 뺀다."""
    axes = {a.name: a for a in tax.active_axes()}
    rules, invalid = [], 0
    for r in doc["rules"]:
        if not _valid_rule(r):
            invalid += 1
            continue
        if not r.get("enabled", True):
            continue
        if only_axes is not None and tax.axis(r.get("target")) is not None and r["target"] not in only_axes:
            continue
        r = dict(r)
        if r["kind"] in AXIS_KINDS:
            ax = axes.get(r.get("target"))
            if ax is None:
                continue
            if any(v and v not in SPECIAL and ax.value(v) is None for v in (r.get("from"), r.get("to"))):
                invalid += 1
                continue
            r["_stage"] = "classify"
        elif r["kind"] in ANSWER_KINDS:
            r["_stage"] = "label"
        elif r.get("stage") in STAGES:
            r["_stage"] = r["stage"]  # MANUAL: stage가 있으면 그것(1차는 축 이름, 3차는 축=값 또는 질문 ID target)
        else:
            # stage 없는 옛 MANUAL: target이 'label'이면 3차 라벨링, 그 밖(축 이름·'classify'·빈칸)은 1차 분류에 넣는다.
            r["_stage"] = "label" if r.get("target") == "label" else "classify"
        r["_scope"] = _scope(r, axes)
        rules.append(r)
    rules.sort(key=lambda r: (r["kind"] != "MANUAL", -int(r.get("count") or 0), r["rule_id"]))
    return ([r for r in rules if r["_stage"] == "classify"][:cap]
            + [r for r in rules if r["_stage"] == "label"][:cap]), invalid


def _manual_label_hit(r, qids, pairs):
    """3차 MANUAL 규칙이 이 chunk의 질문에 걸리는지. target이 'label'·빈칸이면 모든 chunk, 질문 ID면 그 질문,
    축=값이면 적용 대상이 그 축=값인 질문(승인·검증 질문)이 있을 때."""
    t = r.get("target") or ""
    return t in ("", "label") or t in qids or t in pairs


def _scope(r, axes):
    """규칙의 기록 범위 (구역, 키). 1차는 축 이름, 3차는 질문 ID 또는 축=값. 그 밖은 단계 전체(stage_wide)."""
    t = r.get("target") or ""
    if r["_stage"] == "classify":
        return ("classify", t) if t in axes else ("stage_wide", "")
    if r["kind"] in ANSWER_KINDS or t not in ("", "label"):
        return ("label", t)
    return ("stage_wide", "")


def rule_hash(r):
    """규칙 내용 해시(앞 16자): 종류·대상·from·to·정규화 문장·켜짐·단계. 문장의 공백 차이는 무시한다."""
    return util.hash_obj({"kind": r.get("kind"), "target": r.get("target") or "", "from": r.get("from") or "",
                          "to": r.get("to") or "", "text": " ".join(str(r.get("text") or "").split()),
                          "enabled": bool(r.get("enabled", True)), "stage": r.get("stage") or ""})[:16]


def empty_record():
    return {"classify": {}, "label": {}, "stage_wide": {}, "examples": []}


def _record(rules, example_ids):
    """{"classify": {축: {rule_id: {h, kind, target, stage}}}, "label": {질문 ID 또는 축=값: {...}},
    "stage_wide": {rule_id: {...}}, "examples": [사례 ID]}. 규칙 문장은 넣지 않는다."""
    out = empty_record()
    for r in rules:
        ent = {"h": rule_hash(r), "kind": r["kind"], "target": r.get("target") or "", "stage": r["_stage"]}
        part, key = r["_scope"]
        if part == "stage_wide":
            out[part][r["rule_id"]] = ent
        else:
            out[part].setdefault(key, {})[r["rule_id"]] = ent
    out["examples"] = sorted(set(example_ids))
    return out


def _digest(rules, example_ids, k, chars):
    """실행의 sheet_hashes.labeling_rules. Feedback.digest와 digest_of가 같이 쓴다."""
    pairs = [(r["rule_id"], " ".join(r["text"].split())) for r in rules]
    return util.hash_obj({"rules": pairs, "examples": sorted(example_ids), "k": k, "chars": chars})[:16]


def snapshot_of(ws, doc, tax, cfg=None, only_axes=None, cache=None):
    """승인 문서 하나로 (digest, 기록)을 다시 계산한다. load()와 같은 입력(필터·정렬·cap 뒤 규칙, 실제 해석된 사례 ID,
    k, chars)을 쓰고 네트워크를 부르지 않는다(사례 본문은 원래 작업 폴더 DB를 읽기 전용으로 본다).
    피드백이 꺼져 있거나 쓸 것이 없으면 digest는 None(실행의 sheet_hashes에 labeling_rules 키가 없다).
    cache({}): 같은 사례 참조 목록의 해석 결과를 다시 쓴다(여러 이력 문서를 비교할 때)."""
    cfg = _cfg(ws) if cfg is None else cfg
    if not cfg.get("enabled", True):
        return None, empty_record()
    rules, _ = _rules_for_run(doc, tax, max(0, int(cfg.get("max_rules") or 30)), only_axes)
    active = {a.name for a in tax.active_axes() if only_axes is None or a.name in only_axes}
    entries = [e for e in doc["examples"] if _valid_example(e) and e.get("enabled", True)]
    key = util.hash_obj([entries, sorted(active)])
    if cache is not None and key in cache:
        examples = cache[key]
    else:
        examples, _ = _resolve_examples(ws, entries, None, active)
        if cache is not None:
            cache[key] = examples
    if only_axes is not None:
        examples = [e for e in examples if e["final_axes"]]
    ids = [e["example_id"] for e in examples]
    if not rules and not examples:
        return None, empty_record()
    return _digest(rules, ids, int(cfg.get("examples_k") or 0), int(cfg.get("example_chars") or 800)), _record(rules, ids)


def digest_of(ws, doc, tax, cfg=None, only_axes=None):
    """Feedback.digest()와 같은 값을 승인 문서에서 다시 계산한다(옛 실행의 규칙 기준 복원). 없으면 None."""
    return snapshot_of(ws, doc, tax, cfg, only_axes)[0]


def _read_evidence(con, record_id, keys):
    """사례 chunk의 축 교정 근거 {축: {"items": [...], "reason": str 또는 None}}. 원래 작업 DB(읽기 전용)에서 읽는다.

    finals.corrections와 같이 applied_at·review_run_id 순으로 읽어 축마다 가장 나중 교정의 근거만 남긴다.
    근거 열이 없는 예전 DB이거나 형식이 틀린 항목은 건너뛴다.
    """
    out = {}
    if not keys:
        return out
    for r in con.execute("SELECT target_key, evidence, reason FROM corrections WHERE chunk_id=? AND target_kind='axis'"
                         " ORDER BY applied_at, review_run_id", (record_id,)):
        if r["target_key"] not in keys:
            continue
        try:
            raw = json.loads(r["evidence"]) if r["evidence"] else []
        except ValueError:
            raw = []
        items = []
        for x in raw if isinstance(raw, list) else []:
            if (isinstance(x, dict) and x.get("source") in ("chunk", "file_name", "doc_title")
                    and isinstance(x.get("quote"), str) and x["quote"].strip()):
                items.append({"source": x["source"], "chunk_id": x.get("chunk_id"),
                              "slide_no": x.get("slide_no") if isinstance(x.get("slide_no"), int) else None,
                              "quote": " ".join(x["quote"].split())})
        reason = " ".join(r["reason"].split())[:TEXT_MAX] if isinstance(r["reason"], str) else ""
        out[r["target_key"]] = {"items": items, "reason": reason or None}
    return out


def _resolve_examples(ws, entries, chat, active):
    """승인 사례 참조 → 본문·벡터를 붙인 사례 목록과 제외 사유 건수. 원래 작업 폴더 DB는 읽기 전용으로 연다."""
    from labelbot import embed

    root = examples_root(ws)
    model = (ws.config.get("embedding") or {}).get("model")
    skipped, out = {}, []

    def skip(code, n=1):
        skipped[code] = skipped.get(code, 0) + n

    by_src = {}
    for e in entries:
        by_src.setdefault(e["source_ws"], []).append(e)
    for src in sorted(by_src):
        group = by_src[src]
        db = os.path.join(root, src, "work.sqlite")
        if not is_inside(db, root) or not os.path.isfile(db):
            skip("EXAMPLE_SOURCE_GONE", len(group))
            continue
        try:
            con = store.connect_ro(db)
        except sqlite3.Error:
            skip("EXAMPLE_SOURCE_UNREADABLE", len(group))
            continue
        try:
            con.row_factory = sqlite3.Row
            has_emb = bool(con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunk_embeddings'").fetchone())
            has_ev = {"evidence", "reason"} <= {r[1] for r in con.execute("PRAGMA table_info(corrections)")}
            for e in sorted(group, key=lambda x: x["example_id"]):
                c = con.execute("SELECT file_id, text, text_hash, dup_hash FROM chunks WHERE chunk_id=?",
                                (e["record_id"],)).fetchone()
                if c is None or c["text_hash"] != e["text_hash"]:
                    skip("EXAMPLE_TEXT_CHANGED")
                    continue
                vec = None
                if has_emb and model:
                    v = con.execute("SELECT vector FROM chunk_embeddings WHERE chunk_id=? AND model=? AND text_hash=?",
                                    (e["record_id"], model, e["text_hash"])).fetchone()
                    vec = embed.unpack(v[0]) if v else None
                corrected = {k: {"bot": _as_list(v.get("bot")), "human": _as_list(v.get("human"))}
                             for k, v in (e.get("corrected") or {}).items() if k in active and isinstance(v, dict)}
                out.append({
                    "example_id": e["example_id"], "record_id": e["record_id"], "file_id": c["file_id"],
                    "text_hash": c["text_hash"], "dup_hash": c["dup_hash"], "text": c["text"] or "", "vec": vec,
                    "final_axes": {k: _as_list(v) for k, v in sorted(e["final_axes"].items()) if k in active},
                    "corrected": corrected,
                    # 근거 인용은 같은 파일(같은 file_id)의 본문·파일명·문서 제목이라 송신 검사(file_id 기준)는 그대로다.
                    "evidence": _read_evidence(con, e["record_id"], set(corrected)) if has_ev else {},
                    "confirmed": [k for k in e.get("confirmed") or [] if k in active],
                })
        except sqlite3.Error:
            skip("EXAMPLE_SOURCE_UNREADABLE", len(group))
        finally:
            con.close()
    return out, skipped


def load(ws, tax, chat, enabled=True, only_axes=None):
    """승인 파일을 읽어 실행용 객체를 만든다. 꺼져 있거나 쓸 것이 없으면 NullFeedback. 아무것도 쓰지 않는다.

    only_axes(axis-update 대상 축)를 주면 규칙은 그 축 것만, 사례는 그 축 값만 남기고 그 축 값이 없는 사례는 뺀다.
    """
    cfg = _cfg(ws)
    if not enabled:
        return NullFeedback("이번 실행 끔(--no-feedback)")
    if not cfg.get("enabled", True):
        return NullFeedback("feedback.enabled=false")
    doc = load_rules(ws)
    rules, invalid = _rules_for_run(doc, tax, max(0, int(cfg.get("max_rules") or 30)), only_axes)
    active = {a.name for a in tax.active_axes() if only_axes is None or a.name in only_axes}
    entries, bad = [], 0
    for e in doc["examples"]:
        if not _valid_example(e):
            bad += 1
        elif e.get("enabled", True):
            entries.append(e)
    examples, skipped = _resolve_examples(ws, entries, chat, active)
    if only_axes is not None:
        n = len(examples)
        examples = [e for e in examples if e["final_axes"]]
        if n > len(examples):
            skipped["EXAMPLE_NO_TARGET_AXIS"] = n - len(examples)
    if bad:
        skipped["EXAMPLE_REF_INVALID"] = bad
    if not rules and not examples:
        nf = NullFeedback("승인된 규칙·사례 없음")
        if skipped or invalid:
            nf.reason += "(사례 제외 %s, 형식 오류 규칙 %d)" % (_skipped_text(skipped), invalid)
        return nf
    return Feedback(cfg, rules, examples, skipped, invalid)
