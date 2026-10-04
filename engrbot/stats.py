"""L6 지표 계산(8.1절). 순수 함수만 둔다. 파일을 읽거나 쓰지 않는다.

- 분포는 {값: 건수} dict다. 다중값 축은 값마다 1로 센다.
- JSD는 로그 밑 2이고 0~1이다. 0이 있는 값도 계산된다.
- 비율은 소수 6자리로 반올림한다(리포트 재현용).
"""
import math
import re

from engrbot import model

EN_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9\-/]+")
KO_TOKEN = re.compile(r"[가-힣]{2,}")
ANSWER_KEYS = ("O", "X", "N/A")
PLACES = 6


def rnd(x):
    return None if x is None else round(float(x), PLACES)


def ratio(num, den):
    return rnd(num / float(den)) if den else None


# ---- 분포·JSD -----------------------------------------------------------------

def normalize_dist(counts, support=None):
    """건수 dict → 확률 dict. support를 주면 그 값만 남긴다. 합이 0이면 None."""
    keys = sorted(counts) if support is None else sorted(support)
    total = float(sum(counts.get(k, 0) for k in keys))
    if total <= 0:
        return None
    return {k: counts.get(k, 0) / total for k in keys}


def jsd(p_counts, q_counts, support=None):
    """JSD(p, q) = ½KL(p‖m) + ½KL(q‖m), m = ½(p + q), 밑 2. 한쪽이 비면 None."""
    keys = set(p_counts) | set(q_counts) if support is None else set(support)
    p = normalize_dist(p_counts, keys)
    q = normalize_dist(q_counts, keys)
    if p is None or q is None:
        return None
    total = 0.0
    for k in keys:
        pk, qk = p.get(k, 0.0), q.get(k, 0.0)
        mk = (pk + qk) / 2.0
        if pk > 0:
            total += 0.5 * pk * math.log(pk / mk, 2)
        if qk > 0:
            total += 0.5 * qk * math.log(qk / mk, 2)
    return min(1.0, max(0.0, total))


def drift_level(value, notice, alert, cap_notice=False):
    if value is None:
        return "표본 부족"
    if value >= alert - 1e-12:
        return "주의" if cap_notice else "경보"
    if value >= notice - 1e-12:
        return "주의"
    return "ok"


# ---- 레코드 집계 ----------------------------------------------------------------

def axis_distribution(records, axis_names):
    """records: L1 정규화 레코드 목록. 반환: {축: {값: 건수}}. 값에 예약어도 넣는다."""
    out = {a: {} for a in axis_names}
    for rec in records:
        axes = rec.get("axes") if isinstance(rec.get("axes"), dict) else {}
        for a in axis_names:
            lab = axes.get(a)
            if not isinstance(lab, dict) or not isinstance(lab.get("values"), list):
                continue
            for v in lab["values"]:
                if isinstance(v, str):
                    out[a][v] = out[a].get(v, 0) + 1
    return {a: dict(sorted(d.items())) for a, d in out.items()}


def answer_distribution(records, qids):
    out = {q: {k: 0 for k in ANSWER_KEYS} for q in qids}
    for rec in records:
        answers = rec.get("answers") if isinstance(rec.get("answers"), dict) else {}
        for qid, ans in answers.items():
            val = ans.get("answer") if isinstance(ans, dict) else None
            if val in ANSWER_KEYS:
                out.setdefault(qid, {k: 0 for k in ANSWER_KEYS})[val] += 1
    return dict(sorted(out.items()))


def _axis_values(rec, axis):
    axes = rec.get("axes") if isinstance(rec.get("axes"), dict) else {}
    lab = axes.get(axis)
    if not isinstance(lab, dict) or not isinstance(lab.get("values"), list):
        return None
    return lab["values"]


def is_unknown(rec, axis, unknown=model.UNKNOWN):
    vals = _axis_values(rec, axis)
    return bool(vals) and unknown in vals


def is_na(rec, axis, na=model.NA):
    return _axis_values(rec, axis) == [na]


def unknown_rate(records, axis_names, na=model.NA, unknown=model.UNKNOWN):
    """축 a가 unknown인 레코드 수 / (|R| − 축 a가 해당 없음인 레코드 수)."""
    out = {}
    for a in axis_names:
        unk = sum(1 for r in records if is_unknown(r, a, unknown))
        nas = sum(1 for r in records if is_na(r, a, na))
        out[a] = ratio(unk, len(records) - nas)
    return out


def coverage(dist, active_values):
    """active_values: {축: [활성 값(예약어 제외)]}. 반환: (커버리지, 미사용 값)."""
    cov, unused = {}, {}
    for a, vals in active_values.items():
        d = dist.get(a) or {}
        used = [v for v in vals if d.get(v, 0) > 0]
        cov[a] = ratio(len(used), len(vals))
        unused[a] = [v for v in vals if d.get(v, 0) == 0]
    return cov, unused


def pareto(verdicts):
    """코드 c의 건수 = c가 하나 이상 붙은 레코드 수. 비율은 코드 건수 합에 대한 비율이다."""
    counts = {}
    for v in verdicts:
        for code in {i["code"] for i in v.get("issues") or []}:
            counts[code] = counts.get(code, 0) + 1
    total = sum(counts.values())
    out, cum = [], 0
    for code, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        cum += n
        out.append({"code": code, "records": n, "share": ratio(n, total), "cum_share": ratio(cum, total)})
    return out


def layer_issue_rate(verdicts, layers):
    """그 층의 minor 이상 이슈가 하나 이상 붙은 레코드 수 / 전체 레코드 수."""
    floor = model.SEVERITY_RANK["minor"]
    hit = {l: 0 for l in layers}
    for v in verdicts:
        seen = {i["layer"] for i in v.get("issues") or [] if model.SEVERITY_RANK.get(i["severity"], 0) >= floor}
        for l in seen:
            if l in hit:
                hit[l] += 1
    return {l: ratio(hit[l], len(verdicts)) if verdicts else 0.0 for l in layers}


def verdict_counts(verdicts):
    out = {k: 0 for k in model.VERDICTS}
    for v in verdicts:
        out[v["verdict"]] = out.get(v["verdict"], 0) + 1
    return out


def pass_rate(counts, total):
    return ratio(counts.get("PASS", 0) + counts.get("AUTO_FIX", 0), total) if total else 0.0


# ---- 용어 후보 -----------------------------------------------------------------

def tokens(text):
    return EN_TOKEN.findall(text or "") + KO_TOKEN.findall(text or "")


def exclusion_keys(expressions, stoplist=()):
    """taxonomy 값, 동의어 표현·표준어, stoplist. 표현 전체와 그 토큰을 소문자로 뺀다."""
    out = set()
    for e in list(expressions) + list(stoplist):
        if not isinstance(e, str):
            continue
        out.add(e.casefold())
        out.update(t.casefold() for t in tokens(e))
    return out


def term_candidates(docs, unknown_ids, excluded, min_df, min_lift, top_k, max_examples=5):
    """docs: {record_id: 본문}(R 전체). unknown_ids: unknown 축이 있는 레코드 ID 집합.

    lift = (df_u / |U|) / (df_all / |R|). df_u ≥ min_df이고 lift ≥ min_lift인 토큰을 lift 내림차순으로 top_k개.
    """
    n_all, n_u = len(docs), len(unknown_ids)
    if not n_all or not n_u:
        return []
    df_all, df_u, surface, examples = {}, {}, {}, {}
    for rid in sorted(docs):
        seen = {}
        for t in tokens(docs[rid]):
            k = t.casefold()
            if k in excluded:
                continue
            seen.setdefault(k, {})
            seen[k][t] = seen[k].get(t, 0) + 1
        for k, forms in seen.items():
            df_all[k] = df_all.get(k, 0) + 1
            sf = surface.setdefault(k, {})
            for t, c in forms.items():
                sf[t] = sf.get(t, 0) + c
            if rid in unknown_ids:
                df_u[k] = df_u.get(k, 0) + 1
                if len(examples.setdefault(k, [])) < max_examples:
                    examples[k].append(rid)
    out = []
    for k, du in df_u.items():
        if du < min_df:
            continue
        lift = (du / float(n_u)) / (df_all[k] / float(n_all))
        if lift < min_lift - 1e-12:
            continue
        forms = surface[k]
        term = sorted(forms, key=lambda t: (-forms[t], t))[0]
        out.append({"term": term, "df_u": du, "df_all": df_all[k], "lift": rnd(lift), "examples": examples[k]})
    out.sort(key=lambda r: (-r["lift"], -r["df_u"], r["term"]))
    return out[:top_k]
