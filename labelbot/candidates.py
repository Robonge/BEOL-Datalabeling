"""후보 집계와 reports/ 후보 리포트. 봇은 taxonomy.xlsx를 고치지 않고 붙여넣기 행만 낸다."""
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


def _rejected(tax):
    return {util.nfkc(r[1]).strip().lower() for r in tax.rejected if len(r) > 1 and r[1]}


def grouped(con, tax, run_id):
    """같은 후보는 빈도와 예시 chunk로 묶는다. rejected 시트에 있는 후보와 이미 시트에 있는 동의어는 뺀다."""
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
        if util.nfkc(r["content"]).strip().lower() in rej:
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
    out = list(groups.values())
    out.sort(key=lambda g: (g["source"] != "review", g["kind"], -g["freq"], g["content"]))
    return out


def paste_row(g):
    a, _, b = g["content"].partition("|")
    if g["kind"] == "new_value":
        # taxonomy 시트 A~K: 축, 값, 상위값, (D~G 비움), 정의, 포함 예, 제외 예, 사용 여부
        return "\t".join([a, b, g["parent"] or "", "", "", "", "", "", "", "", ""])
    if g["kind"] == "synonym":
        return "\t".join([a, b, "검수 등록" if g["source"] == "review" else "후보"])
    return g["content"]


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
        lines += ["", "붙여넣기 행(탭 구분):", "", "```"] + [paste_row(g) for g in gs] + ["```", ""]
    util.write_text(ctx.ws.path("reports", "candidates.md"), "\n".join(lines) + "\n")
    _write_file_list(ctx)
    return groups


def _write_file_list(ctx):
    rows = ctx.con.execute("SELECT file_id, file_name FROM files WHERE status='ok' ORDER BY rel_path").fetchall()
    known = {f.file_id for f in ctx.tax.files}
    lines = ["# 파일 목록 (files 시트 붙여넣기 행: 파일 ID, 파일명, 제외, 맥락 메모)", "", "```"]
    for r in rows:
        if r["file_id"] not in known:
            lines.append("\t".join([r["file_id"], r["file_name"], "N", ""]))
    lines.append("```")
    util.write_text(ctx.ws.path("reports", "file_list.md"), "\n".join(lines) + "\n")
