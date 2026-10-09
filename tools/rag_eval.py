#!/usr/bin/env python3
"""B0a RAG 평가 기준선(L6, 마일스톤 M26 RAG_EVAL). 정상성 확인용이며 실제 기준은 폐쇄망 내부 세트다.

세 가지 일을 한다.
- --draft: 작업 폴더의 OK 적재 chunk로 골든 질문을 결정적으로 만든다(LLM 없음). 파일마다 chunk_id sha256
  오름차순으로 길이 하한(MIN_CHARS=80자)을 넘고 질문을 만들 수 있는 chunk 2개, 모자라면 남은 chunk를 파일 순서로
  돌아가며 채워 --total개. 질문은 라벨(축 값)과 그 chunk 본문에 실제로 있는 용어로만 만든다.
  골든 파일에는 파일명·chunk 본문을 넣지 않는다(file_id·chunk_id·질문·용어만).
- 캡처(기본): 질문 임베딩(질문마다 1회, 저장해 재현 가능) → (a) 로컬 chunk_embeddings 정확 코사인
  recall@5/@10·MRR, (b) Supabase beol_rag_search RPC(index.ts와 같은 인자, k 상한 8) recall@5/@8·MRR,
  (c) 배포된 Edge Function beol-rag-ask를 rag/beol_rag.html처럼(anon 키 헤더) 질문마다 N회 호출해
  답·인용 chunk·용어 적중률·지연. 실패는 사유 코드로 남기고 계속한다. 답변 호출 총수는 --max-answer-calls 이하.
- --recompute: 저장한 질문 임베딩과 RPC 순위로 검색 지표를 네트워크 없이 다시 계산해 요약과 같은지 본다.

네트워크는 labelbot.llm의 post_json(임베딩은 HttpEmbedTransport)으로만 한다(code_engrbot C2).
출력에는 키·호스트·서명 URL·파일명을 넣지 않는다(공개 저장소로 push된다). 쓰는 형식은 .jsonl·.json뿐이다.

사용:
  python tools/rag_eval.py --draft --workspace workspaces/<폴더> [--questions rag/eval/golden_questions.jsonl]
  python tools/rag_eval.py --workspace workspaces/<폴더> [--questions …] [--out rag/eval/baseline_openai_<날짜>.jsonl]
                           [--answers 3] [--retrieval-only] [--max-answer-calls 144] [--workers 4]
  python tools/rag_eval.py --recompute rag/eval/baseline_openai_<날짜>.jsonl --workspace workspaces/<폴더>
종료 코드: 0 성공, 1 실패(검사 불통과·재계산 불일치·설정 없음).
"""
import argparse
import base64
import datetime
import hashlib
import json
import math
import os
import re
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

CODE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if CODE_ROOT not in sys.path:
    sys.path.insert(0, CODE_ROOT)

from labelbot import finals, llm, store  # noqa: E402
from labelbot.embed import unpack  # noqa: E402
from labelbot.workspace import Workspace, load_env_file  # noqa: E402

MILESTONE = "M26"
DEFAULT_QUESTIONS = os.path.join(CODE_ROOT, "rag", "eval", "golden_questions.jsonl")
EVAL_DIR = os.path.join(CODE_ROOT, "rag", "eval")
RAG_HTML = os.path.join(CODE_ROOT, "rag", "beol_rag.html")
TAXONOMY = os.path.join(CODE_ROOT, "taxonomy", "taxonomy.json")

PER_FILE = 2
TOTAL = 48
MIN_CHARS = 80
EXACT_KS = (5, 10)
RPC_K = 8          # beol_rag_search가 k를 8로 자른다(least(greatest(k,1),8))
RPC_KS = (5, 8)
ASK_K = 5          # rag/beol_rag.html TOP_K
ANSWER_TIMEOUT = 100
RETRIEVAL_TIMEOUT = 60
TRANSIENT = frozenset(("TIMEOUT", "NETWORK_ERROR", "HTTP_429", "HTTP_500", "HTTP_502", "HTTP_503", "HTTP_504"))

GOLDEN_FIELDS = ("qid", "question", "expected_chunk_ids", "expected_terms", "source_workspace", "file_id")
NA_VALUES = frozenset(("해당 없음", "unknown", "판단 불가", ""))
CTX_AXES = ("구조/레이어", "공정 모듈")
# 질문의 핵심 용어를 고르는 축 순서(구체적인 것 먼저). 결과·의사결정 상태는 본문 용어가 아니라 뺀다.
TERM_AXES = ("Patterning/scheme", "물리 현상", "불량 모드", "Material", "Main step", "제품·세대", "REMSPC")
# 측정 항목 어휘(고정 목록, 본문에서 찾은 첫 항목을 질문에 쓴다).
METRICS = ("Rc", "Rs", "CD", "TDDB", "EM", "leakage", "yield", "수율", "저항", "wafer map", "fail", "TEM", "SEM",
           "profile", "두께", "thickness", "void", "Vbd")
TEMPLATES = (
    "{ctx} 평가에서 {term} 관련 {metric}결과는 어떻게 나왔나요?",
    "{ctx}에서 {term} 조건에 따른 {metric}변화는 어땠나요?",
    "{ctx} {term} 평가의 {metric}결과를 요약해 주세요.",
    "{ctx} 공정에서 {term} 관련 {metric}데이터는 무엇을 보여 주나요?",
)
_B64_RE = re.compile(r"[A-Za-z0-9+/=]{40,}")
_LOT_RE = re.compile(r"\b[A-Z][A-Z0-9]{3,}\.[0-9A-Z]{1,3}\b")


class EvalError(Exception):
    def __init__(self, reason_code):
        Exception.__init__(self, reason_code)
        self.reason_code = reason_code


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---- 용어 판정 ---------------------------------------------------------------

def _term_re(term):
    esc = re.escape(term)
    if re.match(r"^[A-Za-z0-9]", term):
        esc = r"(?<![A-Za-z0-9])" + esc
    if re.search(r"[A-Za-z0-9]$", term):
        esc += r"(?![A-Za-z0-9])"
    return re.compile(esc, re.IGNORECASE)


def term_in(term, text):
    """용어가 본문에 있는가. 영숫자 경계는 지킨다("VA"가 "VAL"에 걸리지 않게), 대소문자는 무시한다."""
    return bool(term) and bool(text) and bool(_term_re(term).search(text))


def term_hits(answer, terms):
    """(맞은 용어 목록, 적중률). 용어가 없으면 (빈 목록, None)."""
    if not terms:
        return [], None
    hit = [t for t in terms if term_in(t, answer or "")]
    return hit, round(len(hit) / len(terms), 6)


def load_taxonomy(path=TAXONOMY):
    """{표준어(소문자): [동의어…]}와 {(축, 값): [포함 예 별칭…]}."""
    with open(path, encoding="utf-8") as f:
        tax = json.load(f)
    syn = {}
    for r in tax.get("synonyms") or []:
        a, b = (r.get("동의어") or "").strip(), (r.get("표준어") or "").strip()
        if a and b:
            syn.setdefault(b.lower(), []).append(a)
            syn.setdefault(a.lower(), []).append(b)
    alias = {}
    for r in tax.get("taxonomy") or []:
        axis, val = r.get("축") or "", r.get("값") or ""
        if not val:
            continue
        for item in re.split(r"[,;]", r.get("포함 예") or ""):
            item = re.sub(r"\(→[^)]*\)", "", item).strip()
            if item and item != val:
                alias.setdefault((axis, val), []).append(item)
    return {"synonyms": syn, "alias": alias}


def _values(d, axis):
    a = (d.get("axes") or {}).get(axis) or {}
    return [v for v in a.get("values") or [] if isinstance(v, str) and v not in NA_VALUES]


def chunk_terms(d, text, tax):
    """expected_terms: 라벨 값·그 별칭·taxonomy 동의어 중 이 chunk 본문에 실제로 있는 것(순서 고정, 중복 없음)."""
    out = []

    def add(t):
        if t and t.lower() not in {x.lower() for x in out} and term_in(t, text):
            out.append(t)

    for axis in CTX_AXES + TERM_AXES:
        for v in _values(d, axis):
            add(v)
            for a in tax["alias"].get((axis, v), []):
                add(a)
            for s in tax["synonyms"].get(v.lower(), []):
                add(s)
    for key in sorted(tax["synonyms"]):  # 양방향 사전이라 값만 돌아도 두 쪽 용어가 모두 나온다
        for s in tax["synonyms"][key]:
            add(s)
    return out


def build_question(chunk_id, d, text, tax):
    """(질문, 핵심 용어) 또는 (None, None). 맥락(층·모듈)은 라벨, 핵심 용어·측정 항목은 본문에 있는 것만 쓴다."""
    ctx = " ".join(v for axis in CTX_AXES for v in _values(d, axis)[:1]) or "BEOL"
    term = None
    for axis in TERM_AXES:
        for v in _values(d, axis):
            if term_in(v, text) and v not in ctx.split():
                term = v
                break
            al = next((a for a in tax["alias"].get((axis, v), []) + tax["synonyms"].get(v.lower(), [])
                       if term_in(a, text) and a not in ctx.split()), None)
            if al:
                term = al  # 본문에 실제로 있는 별칭을 질문에 쓴다
                break
        if term:
            break
    metric = next((m for m in METRICS if term_in(m, text) and (term is None or m.lower() != term.lower())), None)
    if term is None:
        if metric is None:
            return None, None
        term, metric = metric, None
    tpl = TEMPLATES[int(sha(chunk_id), 16) % len(TEMPLATES)]
    return tpl.format(ctx=ctx, term=term, metric=(metric + " ") if metric else ""), term


# ---- 골든 질문 초안 ------------------------------------------------------------

def open_ro(ws_root):
    con = store.connect_ro(os.path.join(ws_root, "work.sqlite"))
    con.row_factory = sqlite3.Row
    return con


def latest_run(con):
    r = con.execute("SELECT run_id FROM runs WHERE run_id IN (SELECT DISTINCT run_id FROM labels)"
                    " ORDER BY started_at DESC, run_id DESC LIMIT 1").fetchone()
    if not r:
        raise EvalError("NO_LABELED_RUN")
    return r[0]


def ok_chunks(con, model):
    """OK 적재 기록이 있는 chunk(그 모델). [{chunk_id, file_id, text}]"""
    return [dict(r) for r in con.execute(
        "SELECT DISTINCT c.chunk_id, c.file_id, c.text FROM vector_push_log v JOIN chunks c ON c.chunk_id=v.chunk_id"
        " WHERE v.result_code='OK' AND v.model=? ORDER BY c.chunk_id", (model,))]


def select_items(chunks, labels, tax, per_file=PER_FILE, total=TOTAL, min_chars=MIN_CHARS):
    """결정적 선택. 파일 순서 = file_id 오름차순, 파일 안 = sha256(chunk_id) 오름차순.
    길이 하한 미만·질문 불가·이미 나온 질문과 같은 chunk는 건너뛰고 다음 chunk를 쓴다."""
    by_file = {}
    for c in chunks:
        by_file.setdefault(c["file_id"], []).append(c)
    queues = {}
    for fid in sorted(by_file):
        q = []
        for c in sorted(by_file[fid], key=lambda c: sha(c["chunk_id"])):
            d = labels.get(c["chunk_id"])
            text = c.get("text") or ""
            if d is None or len(text) < min_chars:
                continue
            question, _term = build_question(c["chunk_id"], d, text, tax)
            terms = chunk_terms(d, text, tax)
            if question and terms:
                q.append((c, question, terms))
        queues[fid] = q
    picked, seen = {fid: [] for fid in queues}, set()

    def take(fid):
        while queues[fid]:
            c, question, terms = queues[fid].pop(0)
            if question in seen:
                continue
            seen.add(question)
            picked[fid].append((c, question, terms))
            return True
        return False

    count = 0
    for fid in sorted(queues):
        for _ in range(per_file):
            if count < total and take(fid):
                count += 1
    while count < total and any(queues.values()):
        for fid in sorted(queues):
            if count < total and take(fid):
                count += 1
    items = []
    for fid in sorted(picked):
        for c, question, terms in picked[fid]:
            items.append({"qid": "b0a-" + sha(c["chunk_id"])[:12], "question": question,
                          "expected_chunk_ids": [c["chunk_id"]], "expected_terms": terms, "file_id": fid})
    return items


def draft(ws_root, tax_path=TAXONOMY, total=TOTAL):
    ws = Workspace(ws_root, create=False)
    con = open_ro(ws.root)
    try:
        model = ws.config["embedding"]["model"]
        chunks = ok_chunks(con, model)
        run_id = latest_run(con)
        labels = finals.final_labels(con, run_id, [c["chunk_id"] for c in chunks])
        items = select_items(chunks, labels, load_taxonomy(tax_path), total=total)
        name = os.path.basename(os.path.normpath(ws.root))
        out = [dict((k, dict(it, source_workspace=name)[k]) for k in GOLDEN_FIELDS) for it in items]
        file_names = [r[0] for r in con.execute("SELECT file_name FROM files UNION SELECT file_name FROM file_locations")]
        texts = {c["chunk_id"]: c["text"] or "" for c in chunks}
        return out, file_names, texts
    finally:
        con.close()


def check_golden(items, file_names, texts, total=TOTAL):
    """자체 점검. 문제 사유 코드 목록(빈 목록이면 통과)."""
    problems = []
    if len(items) != total:
        problems.append("COUNT_%d" % len(items))
    if len({it["qid"] for it in items}) != len(items):
        problems.append("QID_DUP")
    if len({it["question"] for it in items}) != len(items):
        problems.append("QUESTION_DUP")
    stems = set()
    for n in file_names:
        stem = os.path.splitext(n)[0].strip()
        if stem:
            stems.add(stem.lower())
        stems.update(m.group(0).lower() for m in _LOT_RE.finditer(n))
    for it in items:
        if set(it) != set(GOLDEN_FIELDS):
            problems.append("FIELDS:" + it["qid"])
        blob = json.dumps({k: it[k] for k in ("question", "expected_terms")}, ensure_ascii=False)
        low = blob.lower()
        if any(s in low for s in stems):
            problems.append("FILE_NAME:" + it["qid"])
        if _B64_RE.search(blob):
            problems.append("BASE64:" + it["qid"])
        text = texts.get(it["expected_chunk_ids"][0], "")
        if not it["expected_terms"] or not all(term_in(t, text) for t in it["expected_terms"]):
            problems.append("TERM_NOT_IN_CHUNK:" + it["qid"])
        if len(it["question"]) >= 20 and it["question"] in text:
            problems.append("CHUNK_TEXT:" + it["qid"])
    return problems


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path, rows):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")


def write_json(path, obj):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


# ---- 지표 ---------------------------------------------------------------------

def rank_of(ranked, expected):
    """기대 chunk 중 가장 앞의 1부터 센 순위. 없으면 None."""
    exp = set(expected)
    for i, cid in enumerate(ranked or []):
        if cid in exp:
            return i + 1
    return None


def retrieval_metrics(ranks, ks):
    """ranks: 질문별 순위(None=못 찾음, 순위 목록 길이 = 질문 수). recall@k = 순위 ≤ k 비율, MRR = 1/순위 평균."""
    n = len(ranks)
    if n == 0:
        return {}
    out = {"n": n}
    for k in ks:
        out["recall@%d" % k] = round(sum(1 for r in ranks if r is not None and r <= k) / n, 6)
    out["mrr"] = round(sum(1.0 / r for r in ranks if r is not None) / n, 6)
    return out


def norm(vec):
    s = math.sqrt(sum(x * x for x in vec))
    return [x / s for x in vec] if s else list(vec)


def exact_ranking(qvec, matrix):
    """matrix: [(chunk_id, 정규화 벡터)]. 코사인 내림차순, 동점은 chunk_id 오름차순."""
    q = norm(qvec)
    scored = [(-sum(a * b for a, b in zip(q, v)), cid) for cid, v in matrix]
    scored.sort()
    return [cid for _, cid in scored]


def load_matrix(ws_root, model):
    con = open_ro(ws_root)
    try:
        rows = con.execute("SELECT chunk_id, vector FROM chunk_embeddings WHERE model=? ORDER BY chunk_id", (model,))
        return [(r["chunk_id"], norm(unpack(r["vector"]))) for r in rows]
    finally:
        con.close()


def stored_vector(vec):
    """저장·RPC 전송에 쓰는 벡터(소수 7자리, index.ts toVectorLiteral과 같은 자릿수). 재계산은 이 값만 쓴다."""
    return [round(float(x), 7) for x in vec]


def vector_literal(vec):
    return "[" + ",".join("%.7f" % x for x in vec) + "]"


# ---- 네트워크(labelbot.llm만) --------------------------------------------------------

def with_retry(fn, errors, stage):
    """한 번 호출, 일시 오류(TRANSIENT)면 한 번 더. 실패는 errors[stage][code]에 세고 CallFailed를 다시 낸다."""
    for attempt in (0, 1):
        try:
            return fn()
        except llm.CallFailed as e:
            code = e.reason_code
            if attempt == 0 and code in TRANSIENT:
                errors.setdefault(stage + "_retried", {}).setdefault(code, 0)
                errors[stage + "_retried"][code] += 1
                continue
            errors.setdefault(stage, {}).setdefault(code, 0)
            errors[stage][code] += 1
            raise


def embed_questions(cfg, texts, transport=None):
    transport = transport or llm.HttpEmbedTransport(cfg)
    vecs = transport.embed(list(texts))
    if len(vecs) != len(texts):
        raise llm.CallFailed("RESPONSE_SHAPE")
    return vecs


def rpc_search(base_url, key, vec, query_text, k=RPC_K):
    """index.ts search()와 같은 인자({query_embedding, query_text, filters, k}). 반환: 순위대로 chunk_id 목록."""
    _status, rows = llm.post_json(
        base_url.rstrip("/") + "/rest/v1/rpc/beol_rag_search",
        {"apikey": key, "Authorization": "Bearer " + key},
        {"query_embedding": vector_literal(vec), "query_text": query_text, "filters": {}, "k": k},
        RETRIEVAL_TIMEOUT)
    if not isinstance(rows, list):
        raise llm.CallFailed("RESPONSE_SHAPE")
    return [r.get("chunk_id") for r in rows[:k] if isinstance(r, dict)]


def ask(function_url, anon_key, question, k=ASK_K):
    """rag/beol_rag.html ask()와 같은 요청(anon 키 두 헤더, {messages, filters, k}). 반환: 응답 dict."""
    _status, d = llm.post_json(
        function_url, {"apikey": anon_key, "Authorization": "Bearer " + anon_key},
        {"messages": [{"role": "user", "content": question}], "filters": {}, "k": k}, ANSWER_TIMEOUT)
    if not isinstance(d, dict):
        raise llm.CallFailed("BAD_RESPONSE")
    if d.get("error") or not isinstance(d.get("answer"), str):
        raise llm.CallFailed(d.get("error") if isinstance(d.get("error"), str) else "BAD_RESPONSE")
    return d


def anon_key_from_html(path=RAG_HTML):
    """브라우저 화면이 쓰는 공개 anon 키(env SUPABASE_ANON_KEY 우선). role=anon이 아니면 거부한다."""
    key = os.environ.get("SUPABASE_ANON_KEY", "")
    if not key and os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            m = re.search(r'const\s+ANON_KEY\s*=\s*"([^"]+)"', f.read())
        key = m.group(1) if m else ""
    if not key:
        raise EvalError("ANON_KEY_MISSING")
    try:
        part = key.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)).decode("utf-8"))
    except (IndexError, ValueError, UnicodeDecodeError):
        raise EvalError("ANON_KEY_INVALID")
    if claims.get("role") != "anon":
        raise EvalError("ANON_KEY_NOT_ANON")
    return key


def answer_record(item, run, d, latency_ms):
    evidence = d.get("evidence") if isinstance(d.get("evidence"), list) else []
    by_n = {e.get("n"): e.get("chunk_id") for e in evidence if isinstance(e, dict)}
    cited = [by_n.get(n) for n in (d.get("cited") or []) if by_n.get(n)]
    hits = [e.get("chunk_id") for e in evidence if isinstance(e, dict) and e.get("kind") != "sibling"]
    terms_hit, rate = term_hits(d["answer"], item["expected_terms"])
    exp = set(item["expected_chunk_ids"])
    return {"kind": "answer", "qid": item["qid"], "run": run, "code": "OK", "latency_ms": latency_ms,
            "answer": d["answer"], "cited_chunk_ids": cited, "hit_chunk_ids": hits,
            "expected_in_hits": bool(exp & set(hits)), "expected_cited": bool(exp & set(cited)),
            "term_hits": terms_hit, "term_hit_rate": rate,
            "warnings": [w for w in d.get("warnings") or [] if isinstance(w, str)]}


def run_answers(items, n_runs, budget, call, workers=4, errors=None):
    """질문마다 n_runs회. 일시 오류는 남은 예산(budget - 사용)이 있을 때만 한 번 더. 반환: (기록 목록, 사용 호출 수)."""
    errors = {} if errors is None else errors
    lock = threading.Lock()
    used = [0]

    def spend():
        with lock:
            if used[0] >= budget:
                return False
            used[0] += 1
            return True

    def one(item, run):
        code = "BUDGET_EXHAUSTED"
        for attempt in (0, 1):
            if not spend():
                break
            t0 = time.monotonic()
            try:
                d = call(item["question"])
                return answer_record(item, run, d, int((time.monotonic() - t0) * 1000))
            except llm.CallFailed as e:
                code = e.reason_code
                if attempt == 0 and code in TRANSIENT:
                    with lock:
                        errors.setdefault("answer_retried", {}).setdefault(code, 0)
                        errors["answer_retried"][code] += 1
                    continue
                break
        with lock:
            errors.setdefault("answer", {}).setdefault(code, 0)
            errors["answer"][code] += 1
        return {"kind": "answer", "qid": item["qid"], "run": run, "code": code, "latency_ms": None, "answer": None,
                "cited_chunk_ids": [], "hit_chunk_ids": [], "expected_in_hits": False, "expected_cited": False,
                "term_hits": [], "term_hit_rate": None, "warnings": []}

    jobs = [(it, r) for r in range(1, n_runs + 1) for it in items]
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        recs = list(ex.map(lambda j: one(*j), jobs))
    order = {it["qid"]: i for i, it in enumerate(items)}
    recs.sort(key=lambda r: (order[r["qid"]], r["run"]))
    return recs, used[0]


# ---- 요약 ---------------------------------------------------------------------

def retrieval_summary(ret_lines, matrix=None):
    """retrieval 줄에서 지표. matrix를 주면 정확 순위를 저장 임베딩으로 다시 계산한다(재계산 모드)."""
    exact_ranks, rpc_ranks, mismatch = [], [], 0
    for r in ret_lines:
        exp = r["expected_chunk_ids"]
        if matrix is not None:
            ranked = exact_ranking(r["query_embedding"], matrix)
            if ranked[:max(EXACT_KS)] != r["exact_top"]:
                mismatch += 1
            exact_ranks.append(rank_of(ranked, exp))
        else:
            exact_ranks.append(r["exact_rank"])
        if r.get("rpc_code") == "OK":
            rpc_ranks.append(rank_of(r["rpc_top"], exp))
    out = {"exact": retrieval_metrics(exact_ranks, EXACT_KS),
           "rpc": dict(retrieval_metrics(rpc_ranks, RPC_KS), n_failed=len(ret_lines) - len(rpc_ranks))}
    if matrix is not None:
        out["exact_top_mismatch"] = mismatch
    return out


def answer_summary(ans_lines, n_runs):
    ok = [a for a in ans_lines if a["code"] == "OK"]
    rates = [a["term_hit_rate"] for a in ok if a["term_hit_rate"] is not None]
    per_run = []
    for run in range(1, n_runs + 1):
        rr = [a["term_hit_rate"] for a in ok if a["run"] == run and a["term_hit_rate"] is not None]
        per_run.append(round(sum(rr) / len(rr), 6) if rr else None)
    spreads = []
    by_q = {}
    for a in ok:
        if a["term_hit_rate"] is not None:
            by_q.setdefault(a["qid"], []).append(a["term_hit_rate"])
    for v in by_q.values():
        if len(v) > 1:
            spreads.append(max(v) - min(v))
    lat = sorted(a["latency_ms"] for a in ok if a["latency_ms"] is not None)
    valid = [x for x in per_run if x is not None]
    return {
        "calls_ok": len(ok), "calls_failed": len(ans_lines) - len(ok),
        "term_hit_mean": round(sum(rates) / len(rates), 6) if rates else None,
        "term_hit_run_means": per_run,
        "term_hit_run_min": min(valid) if valid else None, "term_hit_run_max": max(valid) if valid else None,
        "term_hit_question_spread_mean": round(sum(spreads) / len(spreads), 6) if spreads else None,
        "expected_in_hits_rate": round(sum(a["expected_in_hits"] for a in ok) / len(ok), 6) if ok else None,
        "expected_cited_rate": round(sum(a["expected_cited"] for a in ok) / len(ok), 6) if ok else None,
        "latency_ms_median": lat[len(lat) // 2] if lat else None,
        "latency_ms_max": lat[-1] if lat else None,
    }


# ---- 명령 ---------------------------------------------------------------------

def cmd_draft(args):
    items, file_names, texts = draft(args.workspace, total=args.total)
    problems = check_golden(items, file_names, texts, args.total)
    write_jsonl(args.questions, items)
    print(json.dumps({"questions": len(items), "files": len({i["file_id"] for i in items}),
                      "problems": problems}, ensure_ascii=False))
    return 1 if problems else 0


def cmd_capture(args):
    load_env_file()
    ws = Workspace(args.workspace, create=False)
    items = read_jsonl(args.questions)
    cfg = ws.config["embedding"]
    model = cfg["model"]
    errors = {}
    try:
        vecs = with_retry(lambda: embed_questions(cfg, [it["question"] for it in items]), errors, "embed")
    except llm.CallFailed as e:
        print(json.dumps({"error": e.reason_code, "stage": "embed"}))
        return 1
    matrix = load_matrix(ws.root, model)
    base = ws.supabase_url()
    skey = llm.read_key(ws.config["supabase"].get("key_env"))
    ret = []
    for it, v in zip(items, vecs):
        qv = stored_vector(v)
        ranked = exact_ranking(qv, matrix)
        line = {"kind": "retrieval", "qid": it["qid"], "model": model, "dim": len(qv),
                "expected_chunk_ids": it["expected_chunk_ids"], "query_embedding": qv,
                "exact_top": ranked[:max(EXACT_KS)], "exact_rank": rank_of(ranked, it["expected_chunk_ids"]),
                "rpc_top": None, "rpc_rank": None, "rpc_code": "CONFIG_MISSING"}
        if base and skey:
            try:
                top = with_retry(lambda: rpc_search(base, skey, qv, it["question"]), errors, "rpc")
                line.update(rpc_top=top, rpc_rank=rank_of(top, it["expected_chunk_ids"]), rpc_code="OK")
            except llm.CallFailed as e:
                line["rpc_code"] = e.reason_code
        else:
            errors.setdefault("rpc", {}).setdefault("CONFIG_MISSING", 0)
            errors["rpc"]["CONFIG_MISSING"] += 1
        ret.append(line)
    answers, used = [], 0
    if not args.retrieval_only and args.answers > 0:
        if not base:
            print(json.dumps({"error": "CONFIG_MISSING", "stage": "answer"}))
            return 1
        anon = anon_key_from_html()
        fn_url = base.rstrip("/") + "/functions/v1/beol-rag-ask"
        answers, used = run_answers(items, args.answers, args.max_answer_calls,
                                    lambda q: ask(fn_url, anon, q), args.workers, errors)
    write_jsonl(args.out, ret + answers)
    with open(args.questions, "rb") as f:
        q_sha = hashlib.sha256(f.read()).hexdigest()
    summary = {
        "date": args.date, "workspace": os.path.basename(os.path.normpath(ws.root)),
        "questions_file": os.path.relpath(os.path.abspath(args.questions), CODE_ROOT).replace("\\", "/"),
        "questions_sha256": q_sha, "n_questions": len(items), "embedding_model": model,
        "exact_ks": list(EXACT_KS), "rpc_ks": list(RPC_KS), "ask_k": ASK_K, "n_local_chunks": len(matrix),
        "answers_per_question": 0 if args.retrieval_only else args.answers, "answer_calls": used,
        "retrieval": retrieval_summary(ret),
        "answers": answer_summary(answers, args.answers) if answers else None,
        "errors": errors,
    }
    write_json(summary_path(args.out), summary)
    print(json.dumps({"out": os.path.basename(args.out), "retrieval": summary["retrieval"],
                      "answer_calls": used, "errors": errors}, ensure_ascii=False))
    return 0


def summary_path(out):
    return re.sub(r"\.jsonl$", "", out) + "_summary.json"


def cmd_recompute(args):
    ws = Workspace(args.workspace, create=False)
    lines = read_jsonl(args.recompute)
    ret = [r for r in lines if r.get("kind") == "retrieval"]
    if not ret:
        print(json.dumps({"error": "NO_RETRIEVAL_LINES"}))
        return 1
    matrix = load_matrix(ws.root, ret[0]["model"])
    again = retrieval_summary(ret, matrix)
    mismatch = again.pop("exact_top_mismatch")
    with open(summary_path(args.recompute), encoding="utf-8") as f:
        saved = json.load(f)
    same = again == saved["retrieval"] and mismatch == 0
    answers = [r for r in lines if r.get("kind") == "answer" and r.get("code") == "OK"]
    golden = {it["qid"]: it for it in read_jsonl(args.questions)} if os.path.isfile(args.questions) else {}
    term_same = all(term_hits(a["answer"], golden[a["qid"]]["expected_terms"])[1] == a["term_hit_rate"]
                    for a in answers if a["qid"] in golden)
    print(json.dumps({"identical": same, "term_hit_identical": term_same, "exact_top_mismatch": mismatch,
                      "retrieval": again}, ensure_ascii=False))
    return 0 if same and term_same else 1


def _main(argv):
    for s in (sys.stdout, sys.stderr):  # Windows 콘솔(cp949)에서도 한글 출력이 죽지 않게
        try:
            s.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    today = datetime.date.today().strftime("%Y%m%d")
    ap = argparse.ArgumentParser(description="B0a RAG 평가 기준선(검색 recall·MRR, 답변 용어 적중)")
    ap.add_argument("--workspace", required=True, help="작업 폴더(workspaces/<폴더>)")
    ap.add_argument("--questions", default=DEFAULT_QUESTIONS, help="골든 질문 jsonl")
    ap.add_argument("--out", default=os.path.join(EVAL_DIR, "baseline_openai_%s.jsonl" % today))
    ap.add_argument("--answers", type=int, default=3, help="질문마다 답변 호출 횟수")
    ap.add_argument("--max-answer-calls", type=int, default=144, help="답변 호출 총 상한(재시도 포함)")
    ap.add_argument("--workers", type=int, default=4, help="답변 동시 호출 수")
    ap.add_argument("--retrieval-only", action="store_true", help="검색 지표만(답변 호출 없음)")
    ap.add_argument("--total", type=int, default=TOTAL, help="--draft 질문 수")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--draft", action="store_true", help="골든 질문 초안 쓰기(네트워크 없음)")
    mode.add_argument("--recompute", metavar="JSONL", help="저장 임베딩으로 검색 지표 재계산(네트워크 없음)")
    args = ap.parse_args(argv)
    args.date = today
    try:
        if args.draft:
            return cmd_draft(args)
        if args.recompute:
            return cmd_recompute(args)
        return cmd_capture(args)
    except EvalError as e:
        print(json.dumps({"error": e.reason_code}))
        return 1


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    try:
        from labelbot import trace
    except (ImportError, SyntaxError):
        trace = None
    if trace is None or not hasattr(trace, "run_main"):
        return _main(argv)
    return trace.run_main(MILESTONE, lambda: _main(argv), argv)


if __name__ == "__main__":
    sys.exit(main())
