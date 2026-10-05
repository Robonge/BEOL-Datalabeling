"""검수 피드백 소비: 승인 파일(taxonomy/labeling_rules.json)의 규칙·사례 → 1차 분류·3차 라벨링 프롬프트.

생산(교정 수집, 규칙·사례 후보, 사람 승인)은 Engr-bot이 맡는다(`python -m engrbot labeling-rules`, engrbot/labeling_rules.py).
이 모듈은 승인 파일을 읽기만 하고 아무것도 쓰지 않는다.

- 규칙: 축·값·질문 ID·건수·문장만 있다(본문 없음). 사람이 문장(text)을 고치거나 enabled를 끄거나 MANUAL 규칙을 더할 수 있다.
- 사례: (source_ws, record_id=chunk_id, text_hash) 참조와 확정 라벨만 있다. 본문·임베딩은 실행할 때 원래 작업 폴더의
  work.sqlite에서 읽기 전용으로 읽는다. 그 작업 폴더가 없거나 본문이 바뀌었으면 그 사례는 쓰지 않는다(사유 코드로 센다).
- 사례는 이번 LLM 호스트로 보낼 수 있는 파일(check_send 통과)에서만 고르고, 같은 파일·같은 본문(text_hash, dup_hash)의
  사례는 그 chunk에 쓰지 않는다(자기 정답 누설 방지).
"""
import json
import math
import os
import pathlib
import re
import sqlite3
import threading

from labelbot import ingest, util
from labelbot.llm import SendBlocked, check_send
from labelbot.workspace import CODE_ROOT, is_inside

RULES_FILENAME = "labeling_rules.json"
NA, UNKNOWN = "해당 없음", "unknown"
SPECIAL = (NA, UNKNOWN)
AXIS_KINDS = ("REPLACE", "REMOVE", "ADD")
ANSWER_KINDS = ("ANSWER", "GEN_ANSWER")
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


def _valid_rule(r):
    return (isinstance(r, dict) and isinstance(r.get("rule_id"), str) and r["rule_id"].strip()
            and isinstance(r.get("text"), str) and r["text"].strip() and len(r["text"]) <= TEXT_MAX
            and r.get("kind") in AXIS_KINDS + ANSWER_KINDS + ("MANUAL",)
            and isinstance(r.get("target", ""), str) and isinstance(r.get("from", ""), str)
            and isinstance(r.get("to", ""), str))


def _valid_example(e):
    return (isinstance(e, dict) and isinstance(e.get("example_id"), str)
            and isinstance(e.get("source_ws"), str) and bool(SAFE_NAME.match(e["source_ws"]))
            and e["source_ws"] not in (".", "..") and isinstance(e.get("record_id"), str)
            and isinstance(e.get("text_hash"), str) and isinstance(e.get("final_axes"), dict))


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
        return "\n\n".join(blocks), sorted({e["file_id"] for _, e in top})

    def rules_text(self, stage, questions=None):
        if stage == "classify":
            rules = self.classify_rules
        else:
            qids = {q.qid for q in questions or []}
            gens = {"%s=%s" % tuple(q.target) for q in questions or []
                    if q.qid.startswith(GEN_PREFIX) and isinstance(q.target, tuple) and len(q.target) == 2}
            rules = [r for r in self.label_rules
                     if r["kind"] == "MANUAL" or (r["kind"] == "ANSWER" and r.get("target") in qids)
                     or (r["kind"] == "GEN_ANSWER" and r.get("target") in gens)]
        return "\n".join("- [%s] %s" % (r["rule_id"], " ".join(r["text"].split())) for r in rules) or NONE_TEXT

    def digest(self):
        rules = [(r["rule_id"], " ".join(r["text"].split())) for r in self.classify_rules + self.label_rules]
        return util.hash_obj({"rules": rules, "examples": sorted(e["example_id"] for e in self.examples),
                              "k": self.k, "chars": self.chars})[:16]

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

def _rules_for_run(doc, tax, cap):
    """켜진 유효 규칙 → 단계(_stage) 붙인 목록과 형식 오류 수. 축 규칙은 활성 축과 taxonomy 값만 받는다."""
    axes = {a.name: a for a in tax.active_axes()}
    rules, invalid = [], 0
    for r in doc["rules"]:
        if not _valid_rule(r):
            invalid += 1
            continue
        if not r.get("enabled", True):
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
        else:
            # MANUAL: target이 'label'이면 3차 라벨링, 그 밖(축 이름·'classify'·빈칸)은 1차 분류에 넣는다.
            r["_stage"] = "label" if r.get("target") == "label" else "classify"
        rules.append(r)
    rules.sort(key=lambda r: (r["kind"] != "MANUAL", -int(r.get("count") or 0), r["rule_id"]))
    return ([r for r in rules if r["_stage"] == "classify"][:cap]
            + [r for r in rules if r["_stage"] == "label"][:cap]), invalid


def _resolve_examples(ws, entries, chat, active):
    """승인 사례 참조 → 본문·벡터를 붙인 사례 목록과 제외 사유 건수. 원래 작업 폴더 DB는 읽기 전용으로 연다."""
    from labelbot import embed

    root = examples_root(ws)
    model = (ws.config.get("embedding") or {}).get("model")
    suffixes = chat.cfg.get("internal_host_suffixes")
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
            con = sqlite3.connect(pathlib.Path(db).resolve().as_uri() + "?mode=ro", uri=True)
        except sqlite3.Error:
            skip("EXAMPLE_SOURCE_UNREADABLE", len(group))
            continue
        try:
            con.row_factory = sqlite3.Row
            has_emb = bool(con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunk_embeddings'").fetchone())
            for e in sorted(group, key=lambda x: x["example_id"]):
                c = con.execute("SELECT file_id, text, text_hash, dup_hash FROM chunks WHERE chunk_id=?",
                                (e["record_id"],)).fetchone()
                if c is None or c["text_hash"] != e["text_hash"]:
                    skip("EXAMPLE_TEXT_CHANGED")
                    continue
                try:
                    check_send(chat.url, [c["file_id"]], suffixes)
                except SendBlocked:
                    skip("EXAMPLE_EXTERNAL_BLOCKED")
                    continue
                vec = None
                if has_emb and model:
                    v = con.execute("SELECT vector FROM chunk_embeddings WHERE chunk_id=? AND model=? AND text_hash=?",
                                    (e["record_id"], model, e["text_hash"])).fetchone()
                    vec = embed.unpack(v[0]) if v else None
                corrected = {k: {"bot": _as_list(v.get("bot")), "human": _as_list(v.get("human"))}
                             for k, v in (e.get("corrected") or {}).items() if k in active and isinstance(v, dict)}
                out.append({
                    "example_id": e["example_id"], "file_id": c["file_id"], "text_hash": c["text_hash"],
                    "dup_hash": c["dup_hash"], "text": c["text"] or "", "vec": vec,
                    "final_axes": {k: _as_list(v) for k, v in sorted(e["final_axes"].items()) if k in active},
                    "corrected": corrected,
                    "confirmed": [k for k in e.get("confirmed") or [] if k in active],
                })
        except sqlite3.Error:
            skip("EXAMPLE_SOURCE_UNREADABLE", len(group))
        finally:
            con.close()
    return out, skipped


def load(ws, tax, chat, enabled=True):
    """승인 파일을 읽어 실행용 객체를 만든다. 꺼져 있거나 쓸 것이 없으면 NullFeedback. 아무것도 쓰지 않는다."""
    cfg = _cfg(ws)
    if not enabled:
        return NullFeedback("이번 실행 끔(--no-feedback)")
    if not cfg.get("enabled", True):
        return NullFeedback("feedback.enabled=false")
    doc = load_rules(ws)
    rules, invalid = _rules_for_run(doc, tax, max(0, int(cfg.get("max_rules") or 30)))
    active = {a.name for a in tax.active_axes()}
    entries, bad = [], 0
    for e in doc["examples"]:
        if not _valid_example(e):
            bad += 1
        elif e.get("enabled", True):
            entries.append(e)
    examples, skipped = _resolve_examples(ws, entries, chat, active)
    if bad:
        skipped["EXAMPLE_REF_INVALID"] = bad
    if not rules and not examples:
        nf = NullFeedback("승인된 규칙·사례 없음")
        if skipped or invalid:
            nf.reason += "(사례 제외 %s, 형식 오류 규칙 %d)" % (_skipped_text(skipped), invalid)
        return nf
    return Feedback(cfg, rules, examples, skipped, invalid)
