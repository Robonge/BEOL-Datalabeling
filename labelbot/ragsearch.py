"""로컬 RAG 저장소 검색(labelbot.ragsrv가 부른다). 옛 SQL 함수 beol_rag_search·뷰 beol_rag_chunks·beol_rag_facets의 Python 판.

저장소는 labelbot/localstore.py가 만든 rag_store.sqlite의 표 beol_chunk_embeddings다
(embedding은 little-endian float32 BLOB, labels는 JSON 문자열). 함수는 모두 sqlite3 연결을 받고 쓰지 않는다. 네트워크 없음.

사양(이 모듈이 원본이다):
- 완전한 행(is_complete): model == 임베딩 모델 이름 그리고 labels.axes["Patterning/scheme"]가 비어 있지 않은 목록
  그리고 labels에 doc_meta 키가 있고 값이 null이 아님 그리고 slide_image_path가 null이 아님.
  검색·형제(siblings)·facets·count가 같이 쓴다.
- filters: dict가 아니거나 값이 목록이 아니면 RagSearchError("BAD_FILTER"). 축 안은 OR(값 하나라도 labels.axes[축]에
  있으면 통과, 문자열 완전 일치·대소문자 구분), 축끼리는 AND, 빈 목록 축은 무시, 그 축이 없는 행은 제외.
  순위를 매기기 전에 거른다.
- 벡터 순위: 코사인 거리(1 - cos) 오름차순, 동점은 chunk_id, 상위 200. 질의 벡터는 round(x, 7)로 맞춘다.
  문서 벡터의 노름은 행을 읽을 때(load_rows) 미리 계산한다. 노름이 0이면 거리는 NaN(맨 뒤, vector_similarity None).
- 단어 검색(Postgres 'simple' 사전 근사):
  1. 질의 전처리: '"'를 공백으로, 낱말 앞 '-'를 지우고((^|\\s)-+ → \\1), 앞뒤 공백 제거. 비면 단어 검색 없음.
  2. 토큰화(문서·질의 같은 함수): 소문자로 바꾸고 [0-9a-z가-힣_]+(?:-[0-9a-z가-힣_]+)*로 자른다. 하이픈 낱말은 전체와
     각 부분을 모두 토큰으로 넣는다. 어간 처리는 하지 않는다(저항이 ≠ 저항). 질의 토큰 'or'는 websearch_to_tsquery에서
     연산자이므로 뺀다.
  3. 질의 토큰은 모두 OR이다. 하나라도 문서 토큰에 있으면 후보.
  4. text_score = 문서에 나온 (서로 다른) 질의 토큰의 출현 수 합 ÷ (1 + 문서 토큰 수/100). 내림차순, 동점은 chunk_id, 상위 200.
  5. 알려진 차이(고치지 않는다): ts_rank_cd 값과 다르다(RRF에는 순위만 쓰인다), µ·Ω 같은 기호는 토큰에서 빠진다,
     하이픈 낱말을 구(phrase)가 아니라 OR로 본다.
- 결합: rrf = 1/(60+vector_pos) + 1/(60+text_pos)(없는 쪽은 0). 정렬 rrf 내림차순 → text_pos(없으면 뒤) →
  vector_pos(없으면 뒤) → chunk_id. 개수는 min(max(k, 1), 8), k가 None이면 5(SQL coalesce와 같게 0은 1로 본다).
- 반환 열: chunk_id, file_id, seq, content, labels(dict), slide_image_bucket, slide_image_path, slide_image_width,
  slide_image_height, vector_similarity(=1-거리), text_score, vector_pos, text_pos, rrf_score.
- siblings(con, file_ids, model): 그 파일들의 완전한 행 전체를 file_id, seq 순으로
  (열: chunk_id, file_id, seq, content, labels, slide_image_bucket, slide_image_path).
- facets(con, model): 완전한 행의 labels.axes에서 목록 값을 펼쳐 {axis, value, n=서로 다른 chunk 수},
  정렬 axis 오름차순 → n 내림차순(→ value 오름차순).
- count(con, model): 완전한 행 수.
- 질의 벡터 차원이 행과 다르면 RagSearchError("DIM_MISMATCH").
"""
import json
import math
import re

from labelbot.embed import unpack

TOP_N = 200
RRF_K = 60
SCHEME_AXIS = "Patterning/scheme"

_COLS = ("chunk_id, model, file_id, seq, dim, embedding, content, labels, "
         "slide_image_bucket, slide_image_path, slide_image_width, slide_image_height")
_TOKEN = re.compile(r"[0-9a-z가-힣_]+(?:-[0-9a-z가-힣_]+)*")
_NEG = re.compile(r"(^|\s)-+")


class RagSearchError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _labels(text):
    if text is None:
        return None
    try:
        v = json.loads(text)
    except (TypeError, ValueError):
        return None
    return v if isinstance(v, dict) else None


def is_complete(row, model):
    """row: model, labels(dict 또는 JSON 문자열), slide_image_path를 가진 dict."""
    labels = row.get("labels")
    if isinstance(labels, str):
        labels = _labels(labels)
    if row.get("model") != model or not isinstance(labels, dict):
        return False
    axes = labels.get("axes")
    scheme = axes.get(SCHEME_AXIS) if isinstance(axes, dict) else None
    return (isinstance(scheme, list) and len(scheme) > 0
            and labels.get("doc_meta") is not None
            and row.get("slide_image_path") is not None)


def _complete_rows(con, model, where="", params=()):
    sql = ("SELECT " + _COLS + " FROM beol_chunk_embeddings WHERE model = ? AND slide_image_path IS NOT NULL" + where)
    out = []
    for r in con.execute(sql, (model,) + tuple(params)):
        row = {
            "chunk_id": r[0], "model": r[1], "file_id": r[2], "seq": r[3], "dim": r[4], "embedding": r[5],
            "content": r[6], "labels": _labels(r[7]), "slide_image_bucket": r[8], "slide_image_path": r[9],
            "slide_image_width": r[10], "slide_image_height": r[11],
        }
        if is_complete(row, model):
            out.append(row)
    return out


def tokens(text):
    """문서·질의 공통 토큰화. 하이픈 낱말은 전체와 각 부분을 모두 넣는다."""
    out = []
    for m in _TOKEN.finditer((text or "").lower()):
        w = m.group(0)
        out.append(w)
        if "-" in w:
            out.extend(w.split("-"))
    return out


def query_tokens(query_text):
    q = _NEG.sub(r"\1", (query_text or "").replace('"', " ")).strip()
    if not q:
        return []
    seen = []
    for t in tokens(q):
        if t != "or" and t not in seen:
            seen.append(t)
    return seen


def load_rows(con, model):
    """검색용 완전한 행. 벡터(vec)와 노름(norm), 단어 토큰 빈도(tf)·토큰 수(ntok)를 미리 계산한다."""
    rows = _complete_rows(con, model)
    for r in rows:
        vec = unpack(r.pop("embedding"))
        r["vec"] = vec
        r["norm"] = math.sqrt(sum(x * x for x in vec))
        toks = tokens(r["content"])
        tf = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        r["tf"] = tf
        r["ntok"] = len(toks)
    return rows


def _filter_values(values):
    out = set()
    for v in values:
        if v is None:
            continue
        if isinstance(v, str):
            out.add(v)
        elif isinstance(v, bool):
            out.add("true" if v else "false")
        else:
            out.add(json.dumps(v, ensure_ascii=False))
    return out


def _check_filters(filters):
    if filters is None:
        return {}
    if not isinstance(filters, dict) or any(not isinstance(v, list) for v in filters.values()):
        raise RagSearchError("BAD_FILTER")
    return {axis: _filter_values(vals) for axis, vals in filters.items() if len(vals) > 0}


def _passes(labels, flt):
    axes = labels.get("axes")
    if not isinstance(axes, dict):
        return not flt
    for axis, wanted in flt.items():
        have = axes.get(axis)
        if isinstance(have, list):
            have = {v for v in have if isinstance(v, str)}
        elif isinstance(have, dict):
            have = set(have)
        elif isinstance(have, str):
            have = {have}
        else:
            return False
        if not (have & wanted):
            return False
    return True


def _distance(q, qnorm, r):
    if qnorm == 0 or r["norm"] == 0:
        return float("nan")
    dot = sum(a * b for a, b in zip(q, r["vec"]))
    return 1.0 - dot / (qnorm * r["norm"])


def _limit(k):
    return min(max(5 if k is None else int(k), 1), 8)


def search(con, query_vec, query_text, filters, k, model, rows=None):
    """hybrid 검색. rows를 주면(load_rows 결과 캐시) 저장소를 다시 읽지 않는다."""
    flt = _check_filters(filters)
    lim = _limit(k)
    q = [round(float(x), 7) for x in query_vec]
    qnorm = math.sqrt(sum(x * x for x in q))
    if rows is None:
        rows = load_rows(con, model)
    cand = [r for r in rows if _passes(r["labels"], flt)]
    for r in cand:
        if len(r["vec"]) != len(q):
            raise RagSearchError("DIM_MISMATCH")

    dist = {r["chunk_id"]: _distance(q, qnorm, r) for r in cand}
    by_vec = sorted(cand, key=lambda r: (math.isnan(dist[r["chunk_id"]]), dist[r["chunk_id"]], r["chunk_id"]))
    vector_pos = {r["chunk_id"]: i + 1 for i, r in enumerate(by_vec[:TOP_N])}

    text_score, text_pos = {}, {}
    qt = query_tokens(query_text)
    if qt:
        scored = []
        for r in cand:
            hits = sum(r["tf"].get(t, 0) for t in qt)
            if hits:
                scored.append((hits / (1 + r["ntok"] / 100), r["chunk_id"]))
        scored.sort(key=lambda s: (-s[0], s[1]))
        for i, (score, cid) in enumerate(scored[:TOP_N]):
            text_score[cid] = score
            text_pos[cid] = i + 1

    by_id = {r["chunk_id"]: r for r in cand}
    fused = []
    for cid in set(vector_pos) | set(text_pos):
        vp, tp = vector_pos.get(cid), text_pos.get(cid)
        rrf = (1.0 / (RRF_K + vp) if vp is not None else 0) + (1.0 / (RRF_K + tp) if tp is not None else 0)
        fused.append((rrf, vp, tp, cid))
    fused.sort(key=lambda f: (-f[0], f[2] is None, f[2] or 0, f[1] is None, f[1] or 0, f[3]))

    out = []
    for rrf, vp, tp, cid in fused[:lim]:
        r = by_id[cid]
        d = dist[cid]
        out.append({
            "chunk_id": cid, "file_id": r["file_id"], "seq": r["seq"], "content": r["content"],
            "labels": r["labels"], "slide_image_bucket": r["slide_image_bucket"],
            "slide_image_path": r["slide_image_path"], "slide_image_width": r["slide_image_width"],
            "slide_image_height": r["slide_image_height"],
            "vector_similarity": None if math.isnan(d) else 1.0 - d,
            "text_score": text_score.get(cid), "vector_pos": vp, "text_pos": tp, "rrf_score": rrf,
        })
    return out


def siblings(con, file_ids, model):
    """같은 파일의 완전한 행 전체(file_id, seq 순)."""
    ids = sorted({f for f in file_ids if isinstance(f, str)})
    if not ids:
        return []
    rows = _complete_rows(con, model, " AND file_id IN (%s)" % ",".join("?" * len(ids)), ids)
    rows.sort(key=lambda r: (r["file_id"], r["seq"] is None, r["seq"] or 0))
    keep = ("chunk_id", "file_id", "seq", "content", "labels", "slide_image_bucket", "slide_image_path")
    return [{c: r[c] for c in keep} for r in rows]


def facets(con, model):
    """[{axis, value, n}] — 완전한 행의 축 값별 chunk 수."""
    seen = {}
    for r in _complete_rows(con, model):
        axes = r["labels"].get("axes")
        for axis, values in (axes.items() if isinstance(axes, dict) else ()):
            if not isinstance(values, list):
                continue
            for v in _filter_values(values):
                seen.setdefault((axis, v), set()).add(r["chunk_id"])
    out = [{"axis": a, "value": v, "n": len(ids)} for (a, v), ids in seen.items()]
    out.sort(key=lambda f: (f["axis"], -f["n"], f["value"]))
    return out


def count(con, model):
    return len(_complete_rows(con, model))
