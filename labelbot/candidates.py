"""후보 집계와 reports/ 후보 리포트. taxonomy.json 반영은 taxonomy 보드(domain_engrbot)가 사람 확정 뒤에 한다."""
import json

from labelbot import util


def _add(ctx, kind, content, axis="", parent="", evidence="", chunk_id="", source="bot"):
    ctx.con.execute(
        "INSERT INTO candidates(run_id, kind, content, axis, parent, evidence, chunk_id, source) VALUES(?,?,?,?,?,?,?,?)",
        (ctx.run_id, kind, content, axis or "", parent or "", (evidence or "")[:300], chunk_id, source),
    )


def collect_from_classify(ctx, chunk_id, res):
    for nv in res["new_values"]:
        _add(ctx, "new_value", "%s|%s" % (nv["axis"], nv["value"]), nv["axis"], nv.get("parent"), nv.get("evidence"), chunk_id)
    for t in res["term_mappings"]:
        if t.get("expression") and t.get("canonical"):
            _add(ctx, "synonym", "%s|%s" % (t["expression"], t["canonical"]), t.get("axis"), "", t.get("evidence"), chunk_id)


def collect_from_label(ctx, chunk_id, res):
    for t in res["term_mappings"]:
        if t.get("expression") and t.get("canonical"):
            _add(ctx, "synonym", "%s|%s" % (t["expression"], t["canonical"]), t.get("axis"), "", t.get("evidence"), chunk_id)


# ---- 동의어 후보 기준(엄밀한 동의어만) ----------------------------------------------
# 동의어는 1차 분류 본문에서 표준어로 '치환'된다. 바꿔 써도 뜻이 완전히 같은 표현(약어·표기 차이·오타·한영 혼용)만
# 후보로 올린다. 상위·하위 개념, 관련어, 분류 체계에 없는 표준어는 올리지 않는다(사람 검수 등록은 예외).
SYN_SHORT_ASCII_ALLOW = ("JGV",)   # PRD 6.2: 3자 이하 영문 키는 이 목록만 허용
SYN_MIN_FREQ = 2                   # 봇 후보는 한 실행에서 2개 chunk 이상에서 나와야 올린다


def taxonomy_vocab(tax):
    """동의어 표준어로 쓸 수 있는 이름(축·값 이름, norm_key)."""
    from labelbot.taxonomy import norm_key

    out = set()
    for a in tax.axes:
        out.add(norm_key(a.name))
        out.update(norm_key(v.name) for v in a.values)
    return out


def synonym_reject_code(expression, canonical, vocab):
    """엄밀한 동의어가 아니면 사유 코드, 맞으면 None. vocab은 taxonomy_vocab 결과(None이면 그 검사는 건너뛴다)."""
    from labelbot.taxonomy import norm_key

    e, c = norm_key(expression or ""), norm_key(canonical or "")
    if not e or not c:
        return "SYN_EMPTY"
    if e == c:
        return "SYN_SAME"
    raw = (expression or "").strip()
    if len(raw) <= 3 and raw.isascii() and raw not in SYN_SHORT_ASCII_ALLOW:
        return "SYN_SHORT_ASCII"
    if vocab is not None and c not in vocab:
        return "SYN_CANONICAL_NOT_IN_TAXONOMY"
    if c in e:
        return "SYN_NARROWER"   # 표현이 표준어를 품는다: 더 좁은(구체적인) 개념이다
    return None


def _strict_synonyms(groups, tax):
    """봇 동의어 후보를 엄밀한 기준으로 거른다. 같은 표현에 표준어가 둘 이상이면 모두 뺀다(SYN_AMBIGUOUS)."""
    vocab = taxonomy_vocab(tax)
    canon = {}
    for g in groups:
        if g["kind"] == "synonym" and g["source"] != "review":
            a, _, b = g["content"].partition("|")
            canon.setdefault(util.nfkc(a).strip().lower(), set()).add(util.nfkc(b).strip().lower())
    out = []
    for g in groups:
        if g["kind"] == "synonym" and g["source"] != "review":
            a, _, b = g["content"].partition("|")
            if (synonym_reject_code(a, b, vocab) or len(canon[util.nfkc(a).strip().lower()]) > 1
                    or g["freq"] < SYN_MIN_FREQ):
                continue
        out.append(g)
    return out


REJECTED_KIND = {"new_value": "값", "synonym": "동의어", "question": "질문"}   # 후보 종류 → rejected 종류


def _rejected(tax):
    from labelbot.taxonomy import rejected_key

    return {rejected_key(r.kind, r.content) for r in tax.rejected if r.content}


def _is_rejected(rej, kind, content):
    from labelbot.taxonomy import rejected_key

    return kind in REJECTED_KIND and rejected_key(REJECTED_KIND[kind], content) in rej


def grouped(con, tax, run_id):
    """같은 후보는 빈도와 예시 chunk로 묶는다. taxonomy.json rejected 목록에 있는 후보와 이미 있는 동의어는 뺀다."""
    rej = _rejected(tax)
    have_syn = {util.nfkc(s.alias).lower() for s in tax.synonyms}
    rows = con.execute(
        "SELECT kind, content, axis, parent, evidence, chunk_id, source FROM candidates "
        "WHERE run_id=? OR source='review' ORDER BY id",
        (run_id,),
    ).fetchall()
    groups = {}
    for r in rows:
        key = (r["kind"], r["content"], r["source"])
        if _is_rejected(rej, r["kind"], r["content"]):
            continue
        if r["kind"] == "synonym" and util.nfkc(r["content"].split("|", 1)[0]).lower() in have_syn:
            continue
        g = groups.setdefault(
            key, {"kind": r["kind"], "content": r["content"], "axis": r["axis"], "parent": r["parent"],
                  "evidence": r["evidence"], "source": r["source"], "freq": 0, "examples": []}
        )
        g["freq"] += 1
        if r["chunk_id"] and r["chunk_id"] not in g["examples"] and len(g["examples"]) < 3:
            g["examples"].append(r["chunk_id"])
    out = _strict_synonyms(list(groups.values()), tax)
    out.sort(key=lambda g: (g["source"] != "review", g["kind"], -g["freq"], g["content"]))
    return out


_FORMULA_START = ("=", "+", "-", "@")


def _safe(v):
    """탭 구분 행 초안에서 수식 시작 문자 앞에 '를 붙인다(표 프로그램에 옮겨도 수식으로 읽히지 않게)."""
    return "'" + v if v.startswith(_FORMULA_START) else v


def paste_row(g):
    a, _, b = g["content"].partition("|")
    if g["kind"] == "new_value":
        # taxonomy 시트 A~K: 축, 값, 상위값, (D~G 비움), 정의, 포함 예, 제외 예, 사용 여부
        return "\t".join(_safe(v) for v in [a, b, g["parent"] or "", "", "", "", "", "", "", "", ""])
    if g["kind"] == "synonym":
        return "\t".join(_safe(v) for v in [a, b, "검수 등록" if g["source"] == "review" else "후보"])
    return _safe(g["content"])


def write_reports(ctx):
    from labelbot import revisit  # revisit이 paste_row를 쓰므로 함수 안에서 import한다(순환 회피).

    groups = grouped(ctx.con, ctx.tax, ctx.run_id)
    util.write_jsonl(ctx.ws.path("reports", "candidates.jsonl"), [dict(g, run_id=ctx.run_id) for g in groups])
    n_rv = revisit.write_reports(ctx.ws, ctx.con, ctx.tax)
    rv_line = ("- taxonomy 재검토 요청: 누적 %d건 → [taxonomy_revisit.md](taxonomy_revisit.md)" % n_rv
               if n_rv else "- taxonomy 재검토 요청: 0건")
    labels = {"new_value": "새 값 (taxonomy 시트)", "synonym": "동의어 (synonyms 시트)", "question": "질문 (questions 시트)"}
    lines = ["# 후보 리포트", rv_line, "", "- 실행 ID: %s" % ctx.run_id, "- 후보 수: %d" % len(groups), ""]
    for kind in ("synonym", "new_value", "question"):
        gs = [g for g in groups if g["kind"] == kind]
        lines += ["## %s: %d건" % (labels[kind], len(gs)), ""]
        if not gs:
            continue
        lines += ["| 출처 | 후보 | 빈도 | 제안 축 | 예시 chunk | 근거 |", "|---|---|---|---|---|---|"]
        for g in gs:
            lines.append("| %s | %s | %d | %s | %s | %s |" % (
                "검수 등록" if g["source"] == "review" else "봇", g["content"].replace("|", " → "), g["freq"],
                g["axis"] or "", ", ".join(g["examples"]), (g["evidence"] or "").replace("|", "/").replace("\n", " ")[:80]))
        lines += ["", "행 초안(탭 구분, taxonomy 보드가 같은 후보를 카드로 보여 준다):", "", "```"] + [paste_row(g) for g in gs] + ["```", ""]
    util.write_text(ctx.ws.path("reports", "candidates.md"), "\n".join(lines) + "\n")
    return groups

