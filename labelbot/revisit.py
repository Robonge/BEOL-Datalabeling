"""taxonomy 재검토 요청(revisit): 규칙 상수, 검증, 작업 DB 반영, 누적 리포트, 실행별 재검토 파일.

요청은 검수 교정 파일(review JSON)의 revisits 배열로 온다. 라벨·label_hash는 바꾸지 않는다.
메모와 제안 값은 revisit_requests 표, reports/taxonomy_revisit.md·.jsonl(누적), apply가 쓰는
taxonomy.xlsx 옆 taxonomy_revisit_requests/taxonomy_revisit_<연월일_시분초>.md·.html·.json(실행별)에만 쓴다.
반환값·예외 메시지에는 사유 코드와 건수만 넣는다.
"""
import datetime
import html
import json
import os
import re

from labelbot import candidates, taxonomy, util

REASONS = ("NO_FIT_VALUE", "AMBIGUOUS_DEF", "VALUE_OVERLAP", "NEW_AXIS", "NEED_QUESTION", "OTHER")
REASON_LABELS = {
    "NO_FIT_VALUE": "맞는 값이 없음",
    "AMBIGUOUS_DEF": "정의가 모호함",
    "VALUE_OVERLAP": "값 두 개가 겹침",
    "NEW_AXIS": "새 축이 필요함",
    "NEED_QUESTION": "필요한 질문이 없음",
    "OTHER": "기타",
}
# 화면 DATA로도 내려 준다. question_blank는 target "question" + key ""의 내부 키다(JSON target은 axis/question/new_axis).
TARGET_REASONS = {
    "axis": ["NO_FIT_VALUE", "AMBIGUOUS_DEF", "VALUE_OVERLAP", "OTHER"],
    "question": ["AMBIGUOUS_DEF", "OTHER"],
    "question_blank": ["NEED_QUESTION"],
    "new_axis": ["NEW_AXIS"],
}
TARGETS = ("axis", "question", "new_axis")
MEMO_REQUIRED = ("OTHER", "NEED_QUESTION")
MEMO_MAX = 500
SHORT_MAX = 60
KEY_MAX = 100
REVISITS_MAX = 5000  # 파일 하나의 요청 수 상한. 넘으면 파일 전체 FORMAT_INVALID.

NOT_FLAGGED = "REVISIT_CHUNK_NOT_FLAGGED"
REASON_INVALID = "REVISIT_REASON_INVALID"
FIELD_INVALID = "REVISIT_FIELD_INVALID"
DUPLICATE = "REVISIT_DUPLICATE"
MEMO_TRUNCATED = "REVISIT_MEMO_TRUNCATED"
DROP_CODES = (NOT_FLAGGED, REASON_INVALID, FIELD_INVALID, DUPLICATE, MEMO_TRUNCATED)

_WS = re.compile(r"\s+")
_TARGET_LABELS = {"axis": "축", "question": "질문", "new_axis": "새 축"}


class _Invalid(Exception):
    pass


def _squash(s):
    return _WS.sub(" ", s).strip()


def _short(v):
    """제안 값·관련 값: 공백 정규화 후 1~SHORT_MAX자 문자열."""
    if not isinstance(v, str):
        raise _Invalid(FIELD_INVALID)
    v = _squash(v)
    if not v or len(v) > SHORT_MAX:
        raise _Invalid(FIELD_INVALID)
    return v


def rule_key(target, key):
    if target == "question" and key == "":
        return "question_blank"
    return target


def normalize(item, flagged):
    """항목 하나를 검증·정규화한다. 반환: (row, None) 또는 (None, 사유 코드).

    row의 "_truncated"는 메모를 잘랐는지 표시한다. 검사 순서: 형식 → flagged → 행렬 → 필드.
    """
    try:
        if not isinstance(item, dict):
            raise _Invalid(FIELD_INVALID)
        cid, target, key, reason = item.get("chunk_id"), item.get("target"), item.get("key", ""), item.get("reason")
        memo = item.get("memo")
        if memo is None:
            memo = ""
        if not all(isinstance(x, str) for x in (cid, target, key, reason, memo)) or not cid:
            raise _Invalid(FIELD_INVALID)
        if cid not in flagged:
            raise _Invalid(NOT_FLAGGED)
        key = key.strip()  # 키는 시트 이름과 그대로 맞춰야 하므로 안쪽 공백은 줄이지 않는다.
        if target not in TARGETS or reason not in TARGET_REASONS[rule_key(target, key)]:
            raise _Invalid(REASON_INVALID)
        if len(key) > KEY_MAX or "|" in key:
            raise _Invalid(FIELD_INVALID)
        if target == "axis" or (target == "question" and reason != "NEED_QUESTION"):
            if not key:
                raise _Invalid(FIELD_INVALID)
        elif key:
            raise _Invalid(FIELD_INVALID)
        value = parent = None
        related = []
        if reason in ("NO_FIT_VALUE", "NEW_AXIS"):
            prop = item.get("proposed")
            if not isinstance(prop, dict):
                raise _Invalid(FIELD_INVALID)
            value = _short(prop.get("value"))
            if taxonomy.norm_key(value) in taxonomy.RESERVED:
                raise _Invalid(FIELD_INVALID)
            if reason == "NO_FIT_VALUE" and prop.get("parent") not in (None, ""):
                parent = _short(prop.get("parent"))
        if target == "axis" and reason in ("AMBIGUOUS_DEF", "VALUE_OVERLAP"):
            rv = item.get("related_values")
            if rv is None and reason == "AMBIGUOUS_DEF":
                rv = []
            if not isinstance(rv, list):
                raise _Invalid(FIELD_INVALID)
            related = [_short(v) for v in rv]
            if reason == "AMBIGUOUS_DEF" and len(related) > 1:
                raise _Invalid(FIELD_INVALID)
            if reason == "VALUE_OVERLAP" and (
                    len(related) != 2 or taxonomy.norm_key(related[0]) == taxonomy.norm_key(related[1])):
                raise _Invalid(FIELD_INVALID)
        memo = memo.replace("\r\n", "\n").replace("\r", "\n").strip()
        if reason in MEMO_REQUIRED and not memo:
            raise _Invalid(FIELD_INVALID)
        truncated = len(memo) > MEMO_MAX
        if truncated:
            memo = memo[:MEMO_MAX]
    except _Invalid as e:
        return None, e.args[0]
    return {"chunk_id": cid, "target": target, "key": key, "reason": reason, "proposed_value": value,
            "proposed_parent": parent, "related_values": related, "memo": memo, "_truncated": truncated}, None


def _human_value(doc, cid, target, key):
    """같은 문서 corrections에서 같은 chunk·키의 사람 값. revisit의 question은 corrections의 answer다."""
    want = {"axis": "axis", "question": "answer"}.get(target)
    found = None
    if not want or not key:
        return None
    for c in doc.get("corrections") or []:
        if isinstance(c, dict) and c.get("chunk_id") == cid and c.get("target") == want and c.get("key") == key:
            found = c.get("value")
    return found


def _bot_value(bots, cid, target, key):
    bot = bots.get(cid) or {}
    if target == "axis":
        return ((bot.get("axes") or {}).get(key) or {}).get("values")
    if target == "question" and key:
        return ((bot.get("answers") or {}).get(key) or {}).get("answer")
    return None


def apply_revisits(con, tax, doc, sha, run_id, flagged, bots, now):
    """그 실행의 요청 전체를 doc["revisits"]로 바꾼다. 반환: (저장 수, {사유 코드: 건수}).

    revisits 키가 없으면(예전 화면 파일) 기존 행을 건드리지 않는다. list가 아니거나 REVISITS_MAX건을 넘으면
    ValueError(파일 전체 FORMAT_INVALID). tax는 계층 없는 축의 상위값을 버릴 때만 본다(키가 시트에 있는지는 보지 않는다).
    """
    if "revisits" not in doc:
        return 0, {}
    items = doc["revisits"]
    if not isinstance(items, list):
        raise ValueError("REVISITS_NOT_LIST")
    if len(items) > REVISITS_MAX:
        raise ValueError("REVISITS_TOO_MANY")
    drops = {}

    def drop(code, n=1):
        drops[code] = drops.get(code, 0) + n

    keep = {}
    for item in items:
        try:
            row, code = normalize(item, flagged)
            if row is not None:
                row["bot_value"] = _bot_value(bots, row["chunk_id"], row["target"], row["key"])
                row["human_value"] = _human_value(doc, row["chunk_id"], row["target"], row["key"])
        except (TypeError, KeyError, AttributeError, ValueError):
            row, code = None, FIELD_INVALID
        if row is None:
            drop(code)
            continue
        if row["proposed_parent"] is not None and row["target"] == "axis":
            ax = tax.axis(row["key"])
            if ax is not None and not ax.hierarchical:
                row["proposed_parent"] = None  # 계층 없는 축의 상위값은 시트에 넣을 수 없다.
        k = (row["chunk_id"], row["target"], row["key"])
        if k in keep:
            drop(DUPLICATE)
            del keep[k]
        keep[k] = row
    con.execute("DELETE FROM revisit_requests WHERE review_run_id=?", (run_id,))
    for row in keep.values():
        if row["_truncated"]:
            drop(MEMO_TRUNCATED)
        f = con.execute("SELECT file_id FROM chunks WHERE chunk_id=?", (row["chunk_id"],)).fetchone()
        con.execute(
            "INSERT OR REPLACE INTO revisit_requests(review_run_id, chunk_id, target_kind, target_key, reason,"
            " proposed_value, proposed_parent, related_values, memo, bot_value, human_value, file_id, file_sha256,"
            " applied_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, row["chunk_id"], row["target"], row["key"], row["reason"], row["proposed_value"],
             row["proposed_parent"], util.dumps(row["related_values"]), row["memo"], util.dumps(row["bot_value"]),
             util.dumps(row["human_value"]), f[0] if f else None, sha, now),
        )
    return len(keep), drops


# ---- 조회 ------------------------------------------------------------------

def count(con):
    return con.execute("SELECT COUNT(*) FROM revisit_requests").fetchone()[0]


def rows(con):
    """정렬 고정: 검수 실행 ID 내림차순, chunk ID, 대상, 키."""
    out = []
    for r in con.execute(
            "SELECT * FROM revisit_requests ORDER BY review_run_id DESC, chunk_id, target_kind, target_key").fetchall():
        prop = None
        if r["proposed_value"] is not None:
            prop = {"value": r["proposed_value"], "parent": r["proposed_parent"]}
        out.append({
            "review_run_id": r["review_run_id"], "chunk_id": r["chunk_id"], "file_id": r["file_id"],
            "target": r["target_kind"], "key": r["target_key"], "reason": r["reason"], "proposed": prop,
            "related_values": json.loads(r["related_values"] or "[]"), "memo": r["memo"] or "",
            "bot_value": json.loads(r["bot_value"]) if r["bot_value"] else None,
            "human_value": json.loads(r["human_value"]) if r["human_value"] else None,
            "file_sha256": r["file_sha256"], "applied_at": r["applied_at"],
        })
    return out


# ---- 리포트 ----------------------------------------------------------------

_MD_SPECIAL = re.compile(r"([\\`\[\]!])")


def _html(s):
    """HTML 특수문자를 이스케이프하고, md 링크·이미지·코드 표기 문자(\\ ` [ ] !) 앞에 \\를 붙인다."""
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return _MD_SPECIAL.sub(r"\\\1", s)


def _cell(v):
    """md 표 칸: HTML·md 특수문자 이스케이프, |는 /, 줄바꿈은 공백."""
    if v is None or v == "":
        return "-"
    if isinstance(v, list):
        v = ", ".join(str(x) for x in v) if v else "-"
    return _html(str(v)).replace("|", "/").replace("\r", " ").replace("\n", " ")


def _proposal(r):
    p, rel = r["proposed"], r["related_values"]
    if r["reason"] == "NO_FIT_VALUE" and p:
        return p["value"] + (" (상위 %s)" % p["parent"] if p.get("parent") else "")
    if r["reason"] == "NEW_AXIS" and p:
        return p["value"]
    if rel:
        return " ↔ ".join(rel)
    return None


def _paste_groups(rs, tax):
    """NO_FIT_VALUE 제안을 (축, 값)으로 묶는다. 반환: [(axis, value, parent, n, run_ids, 생략 사유 또는 None)]."""
    groups, order = {}, []
    for r in rs:
        if r["reason"] != "NO_FIT_VALUE" or not r["proposed"]:
            continue
        k = (r["key"], taxonomy.norm_key(r["proposed"]["value"]))
        g = groups.get(k)
        if g is None:
            g = groups[k] = {"axis": r["key"], "value": r["proposed"]["value"], "parent": r["proposed"].get("parent"),
                             "n": 0, "runs": []}
            order.append(k)
        if not g["parent"] and r["proposed"].get("parent"):
            g["parent"] = r["proposed"]["parent"]
        g["n"] += 1
        if r["review_run_id"] not in g["runs"]:
            g["runs"].append(r["review_run_id"])
    out = []
    for k in order:
        g = groups[k]
        ax, skip, parent = tax.axis(g["axis"]), None, g["parent"]
        if ax is None:
            skip = "시트에 없는 축"
        elif ax.value(g["value"]) is not None:
            skip = "시트에 이미 있는 값"
        elif parent:
            pv = ax.value(parent)
            if pv is None:
                skip = "시트에 없는 상위값"
            else:
                parent = pv.name
        out.append((g["axis"], g["value"], parent, g["n"], g["runs"], skip))
    return out


def write_reports(ws, con, tax):
    """reports/taxonomy_revisit.jsonl·md를 전 실행 누적으로 다시 쓴다. 0건이어도 쓴다. 반환: 누적 건수."""
    rs = rows(con)
    util.write_jsonl(ws.path("reports", "taxonomy_revisit.jsonl"), rs)
    runs = []
    for r in rs:
        if r["review_run_id"] not in runs:
            runs.append(r["review_run_id"])
    by_reason = {}
    for r in rs:
        by_reason[r["reason"]] = by_reason.get(r["reason"], 0) + 1
    lines = ["# taxonomy 재검토 요청", "", "- 생성: %s" % util.now_iso(),
             "- 누적 요청: %d건 (검수 실행 %d개)" % (len(rs), len(runs)),
             "- 사유별: %s" % (", ".join("%s %d" % (c, by_reason[c]) for c in REASONS if c in by_reason) or "-"),
             "- 처리됨 판정을 하지 않는다. 시트에 반영한 요청도 그대로 남는다. "
             "요청을 지우려면 그 실행의 검수 화면에서 요청을 삭제하고 다시 apply한다.",
             "- 이 파일과 taxonomy_revisit.jsonl은 사람이 적은 메모를 담는다. 작업 폴더 밖으로 내지 않는다.", ""]
    if not rs:
        lines += ["요청이 없다.", ""]
        util.write_text(ws.path("reports", "taxonomy_revisit.md"), "\n".join(lines) + "\n")
        return 0
    groups = _paste_groups(rs, tax)
    lines += ["## taxonomy 시트 붙여넣기 행 (NO_FIT_VALUE 제안 값, A~K 탭 구분)", ""]
    if groups:
        lines += ["| 축 | 제안 값 | 상위값 | 요청 수 | 검수 실행 |", "|---|---|---|---|---|"]
        paste = []
        for axis, value, parent, n, rids, skip in groups:
            note = _cell(", ".join(rids)) + (" (%s: 붙여넣기 행 생략)" % skip if skip else "")
            lines.append("| %s | %s | %s | %d | %s |" % (_cell(axis), _cell(value), _cell(parent), n, note))
            if not skip:
                row = candidates.paste_row({"kind": "new_value", "content": "%s|%s" % (axis, value),
                                            "parent": parent, "source": "review"})
                paste.append(row.replace("```", ""))
        lines.append("")
        lines += (["```"] + paste + ["```"]) if paste else ["붙여넣기 행 없음."]
    else:
        lines.append("NO_FIT_VALUE 제안 값이 없다.")
    lines += ["", "새 축(NEW_AXIS) 제안은 축 정의 행의 D~G(다중값·계층·중복 알림 제외·종류)를 사람이 정해야 하므로 "
                  "붙여넣기 행을 내지 않는다.", ""]
    for rid in runs:
        rr = [r for r in rs if r["review_run_id"] == rid]
        lines += ["## 검수 실행 %s: %d건" % (rid, len(rr)), ""] + _request_lines(rr)
    util.write_text(ws.path("reports", "taxonomy_revisit.md"), "\n".join(lines).rstrip("\n") + "\n")
    return len(rs)


def _request_lines(rr):
    """한 실행의 요청 표와 메모 인용(md). 번호는 rr 순서로 1부터 매긴다."""
    lines = ["| # | chunk ID | 파일 ID | 대상 | 키 | 사유 | 봇 값 | 사람 교정 | 제안·관련 값 |",
             "|---|---|---|---|---|---|---|---|---|"]
    memos = []
    for i, r in enumerate(rr, 1):
        lines.append("| %d | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            i, _cell(r["chunk_id"]), _cell((r["file_id"] or "")[:16]), _TARGET_LABELS.get(r["target"], r["target"]),
            _cell(r["key"]), _cell("%s %s" % (r["reason"], REASON_LABELS.get(r["reason"], ""))),
            _cell(r["bot_value"]), _cell(r["human_value"]), _cell(_proposal(r))))
        if r["memo"]:
            memos.append((i, r["memo"]))
    lines.append("")
    if memos:
        lines.append("메모")
        for i, memo in memos:
            lines.append("- #%d" % i)
            for ln in memo.split("\n"):
                ln = _html(ln).replace("|", "&#124;").rstrip()
                lines.append("  > %s" % ln if ln else "  >")
        lines.append("")
    return lines


# ---- 실행별 재검토 파일(apply 전용) -------------------------------------------

REQUESTS_DIRNAME = "taxonomy_revisit_requests"
SHEET_COLUMNS = taxonomy.HEADERS["taxonomy"]  # A~K 11열
BLOCK_LABELS = {"paste": "바로 붙여넣기", "check": "확인 필요", "list": "목록만"}
NEW_AXIS_CHECK = "축 정의 행의 D~G(다중값·계층·중복 알림 제외·종류)를 정해야 한다"
_HTTP = re.compile(r"h(?=ttp)", re.I)
_CTRL = re.compile(r"[\t\r\n]+")


def requests_dir(ws):
    """실행별 재검토 파일 폴더: taxonomy.xlsx가 있는 폴더 아래 taxonomy_revisit_requests/."""
    return os.path.join(os.path.dirname(os.path.abspath(ws.taxonomy_path)), REQUESTS_DIRNAME)


def _sheet_cells(values):
    """taxonomy 시트 11칸. 앞 칸만 채우고 나머지(사용 여부 K 포함)는 비운다. 수식 시작 문자는 '로 막는다."""
    return [candidates._safe(v or "") for v in list(values) + [""] * (len(SHEET_COLUMNS) - len(values))]


def _blocks(rs, tax):
    """한 실행의 요청을 시트 배치로 나눈다.

    반환: (paste, check, block). paste는 [(11칸, 요청 번호 목록)], check는 [(11칸, 사유, 요청 번호 목록)],
    block은 {요청 번호: "paste"|"check"|"list"}. 요청 번호는 rs 순서로 1부터.
    NO_FIT_VALUE는 (축, 값)으로 묶어 값 행 하나로 낸다(_paste_groups와 같은 판정).
    NEW_AXIS는 축 정의 행의 D~G가 빈칸이면 파서가 YN_INVALID·AXIS_KIND_INVALID를 내므로 항상 확인 필요다.
    """
    paste, check, block = [], [], {}

    def place(cells, why, nos):
        if any(ch in c for c in cells for ch in "\t\r\n"):
            cells = [_CTRL.sub(" ", c) for c in cells]
            why = why or "칸에 탭·줄바꿈이 있다"
        if why:
            check.append((cells, why, nos))
        else:
            paste.append((cells, nos))
        for n in nos:
            block[n] = "check" if why else "paste"

    for axis, value, parent, _, _, skip in _paste_groups(rs, tax):
        k = taxonomy.norm_key(value)
        nos = [i for i, r in enumerate(rs, 1) if r["reason"] == "NO_FIT_VALUE" and r["proposed"]
               and r["key"] == axis and taxonomy.norm_key(r["proposed"]["value"]) == k]
        place(_sheet_cells([axis, value, parent]), skip, nos)
    names, order = {}, []
    for i, r in enumerate(rs, 1):
        if r["reason"] == "NEW_AXIS" and r["proposed"]:
            k = taxonomy.norm_key(r["proposed"]["value"])
            if k not in names:
                names[k] = (r["proposed"]["value"], [])
                order.append(k)
            names[k][1].append(i)
    have = {taxonomy.norm_key(a.name) for a in tax.axes}
    for k in order:
        name, nos = names[k]
        place(_sheet_cells([name]), "시트에 이미 있는 축" if k in have else NEW_AXIS_CHECK, nos)
    for i in range(1, len(rs) + 1):
        block.setdefault(i, "list")
    return paste, check, block


def _h(v):
    """HTML 칸: 이스케이프하고, 화면 제약(http 문자열 0건)에 맞춰 'http'의 h를 문자 참조로 쓴다."""
    if v is None:
        v = ""
    elif isinstance(v, list):
        v = ", ".join(str(x) for x in v)
    return _HTTP.sub("&#104;", html.escape(str(v), quote=True))


def _code_rows(cells_list):
    return [("\t".join(cells)).replace("```", "") for cells in cells_list]


def _run_md(rid, gen, rs, paste, check, block):
    by_reason = {}
    for r in rs:
        by_reason[r["reason"]] = by_reason.get(r["reason"], 0) + 1
    n_list = sum(1 for b in block.values() if b == "list")
    lines = ["# taxonomy 재검토 요청: 검수 실행 %s" % rid, "", "- 생성: %s" % gen,
             "- 요청: %d건 (바로 붙여넣기 행 %d, 확인 필요 행 %d, 목록만 %d건)" % (len(rs), len(paste), len(check), n_list),
             "- 사유별: %s" % ", ".join("%s %d" % (c, by_reason[c]) for c in REASONS if c in by_reason),
             "- 붙이는 법: 코드 블록의 행(머리글 없음, A열부터 탭 구분 11칸)을 복사해 taxonomy 시트 A열의 빈 행에 붙인다. "
             "같은 이름의 .html에서 표를 드래그 복사해도 된다. 사용 여부(K)는 빈칸(바로 켜짐)이다.",
             "- 붙인 뒤에 다음 apply를 한다. 붙이기 전에 다음 apply를 하면 같은 값이 다음 파일에도 나와, 두 번 붙이면 값 중복 오류로 시트 전체를 읽지 못한다.",
             "- 이 파일은 사람이 적은 메모를 담는다.", "",
             "## 바로 붙여넣기 (taxonomy 시트 A~K)", ""]
    if paste:
        lines += ["```"] + _code_rows(c for c, _ in paste) + ["```", "",
                  "| 행 | 축 | 값 | 상위값 | 요청 # |", "|---|---|---|---|---|"]
        for j, (c, nos) in enumerate(paste, 1):
            lines.append("| %d | %s | %s | %s | %s |" % (j, _cell(c[0]), _cell(c[1]), _cell(c[2]),
                                                       ", ".join("#%d" % n for n in nos)))
    else:
        lines.append("바로 붙여넣을 행이 없다.")
    lines += ["", "## 확인 필요 (고친 뒤 붙여넣기)", ""]
    if check:
        lines += ["```"] + _code_rows(c for c, _, _ in check) + ["```", "",
                  "| 행 | 축 | 값 | 상위값 | 사유 | 요청 # |", "|---|---|---|---|---|---|"]
        for j, (c, why, nos) in enumerate(check, 1):
            lines.append("| %d | %s | %s | %s | %s | %s |" % (j, _cell(c[0]), _cell(c[1]), _cell(c[2]), _cell(why),
                                                            ", ".join("#%d" % n for n in nos)))
    else:
        lines.append("확인할 행이 없다.")
    lines += ["", "## 요청 목록", "",
              "- 시트 배치: %s" % ", ".join("#%d %s" % (i, BLOCK_LABELS[block[i]]) for i in range(1, len(rs) + 1)),
              "- AMBIGUOUS_DEF·VALUE_OVERLAP·OTHER·NEED_QUESTION은 엑셀 행을 내지 않는다(질문은 questions 시트에 직접 쓴다).",
              ""] + _request_lines(rs)
    return "\n".join(lines).rstrip("\n") + "\n"


def _html_table(cells_list, cls):
    head = "".join("<th>%s %s</th>" % (chr(65 + i), _h(c)) for i, c in enumerate(SHEET_COLUMNS))
    body = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % _h(c) for c in cells) for cells in cells_list)
    return '<table class="%s"><thead><tr>%s</tr></thead><tbody>%s</tbody></table>' % (cls, head, body)


def _run_html(rid, gen, rs, paste, check, block):
    p = ['<!DOCTYPE html>', '<html lang="ko"><head><meta charset="utf-8">',
         "<title>taxonomy 재검토 요청 %s</title>" % _h(rid),
         "<style>body{font-family:sans-serif;margin:16px;color:#222;background:#fff}"
         "table{border-collapse:collapse;margin:8px 0 16px}th,td{border:1px solid #bbb;padding:3px 6px;"
         "vertical-align:top;font-size:13px}thead th{background:#eee;user-select:none;-webkit-user-select:none}"
         "table.sheet td{min-width:48px;white-space:nowrap}td.memo{white-space:pre-wrap;max-width:480px}"
         "p.note{color:#555;font-size:13px}</style></head><body>",
         "<h1>taxonomy 재검토 요청: 검수 실행 %s</h1>" % _h(rid),
         '<p class="note">생성 %s. 요청 %d건. 표의 첫 데이터 칸(A)부터 마지막 칸(K)까지 드래그해 복사하고 '
         "taxonomy 시트 A열의 빈 행에 붙인다. 머리글 행은 선택되지 않는다. 사용 여부(K)는 빈칸(바로 켜짐)이다. "
         "붙인 뒤에 다음 apply를 한다. 같은 값을 두 번 붙이면 값 중복 오류로 시트 전체를 읽지 못한다. "
         "이 파일은 사람이 적은 메모를 담는다.</p>" % (_h(gen), len(rs)),
         "<h2>바로 붙여넣기 (%d행)</h2>" % len(paste)]
    if paste:
        p.append(_html_table([c for c, _ in paste], "sheet paste"))
        p.append("<table><thead><tr><th>행</th><th>요청 #</th></tr></thead><tbody>%s</tbody></table>" % "".join(
            "<tr><td>%d</td><td>%s</td></tr>" % (j, ", ".join("#%d" % n for n in nos))
            for j, (_, nos) in enumerate(paste, 1)))
    else:
        p.append('<p class="note">바로 붙여넣을 행이 없다.</p>')
    p.append("<h2>확인 필요: 고친 뒤 붙여넣기 (%d행)</h2>" % len(check))
    if check:
        p.append(_html_table([c for c, _, _ in check], "sheet check"))
        p.append("<table><thead><tr><th>행</th><th>사유</th><th>요청 #</th></tr></thead><tbody>%s</tbody></table>" % "".join(
            "<tr><td>%d</td><td>%s</td><td>%s</td></tr>" % (j, _h(why), ", ".join("#%d" % n for n in nos))
            for j, (_, why, nos) in enumerate(check, 1)))
    else:
        p.append('<p class="note">확인할 행이 없다.</p>')
    p.append("<h2>요청 목록 (%d건)</h2>" % len(rs))
    p.append('<p class="note">AMBIGUOUS_DEF·VALUE_OVERLAP·OTHER·NEED_QUESTION은 엑셀 행을 내지 않는다'
             "(질문은 questions 시트에 직접 쓴다).</p>")
    head = ["#", "chunk ID", "파일 ID", "대상", "키", "사유", "시트 배치", "봇 값", "사람 교정", "제안·관련 값", "메모"]
    p.append("<table><thead><tr>%s</tr></thead><tbody>" % "".join("<th>%s</th>" % _h(x) for x in head))
    for i, r in enumerate(rs, 1):
        cells = [i, r["chunk_id"], (r["file_id"] or "")[:16], _TARGET_LABELS.get(r["target"], r["target"]), r["key"],
                 "%s %s" % (r["reason"], REASON_LABELS.get(r["reason"], "")), BLOCK_LABELS[block[i]],
                 r["bot_value"], r["human_value"], _proposal(r)]
        p.append("<tr>%s<td class=\"memo\">%s</td></tr>" % ("".join("<td>%s</td>" % _h(c) for c in cells), _h(r["memo"])))
    p.append("</tbody></table></body></html>")
    return "\n".join(p) + "\n"


def write_run_files(out_dir, con, tax, run_ids, now=None):
    """apply가 반영한 검수 실행마다 그 실행의 요청만 담은 .md·.html·.json을 out_dir에 쓴다. 반환: 쓴 파일 경로 목록.

    요청이 0건인 실행은 쓰지 않는다. 파일 이름은 taxonomy_revisit_<로컬 연월일_시분초>이고, 같은 이름이 이미 있거나
    한 apply에서 실행이 여럿이면 _2, _3 … 을 붙여 덮어쓰지 않는다(세 확장자가 같은 이름을 쓴다).
    """
    stamp = (now or datetime.datetime.now()).strftime("%Y%m%d_%H%M%S")
    gen = util.now_iso()
    allrs = rows(con)
    written = []
    for rid in sorted(set(run_ids)):
        rs = [r for r in allrs if r["review_run_id"] == rid]
        if not rs:
            continue
        k = 1
        while True:
            stem = os.path.join(out_dir, "taxonomy_revisit_%s%s" % (stamp, "_%d" % k if k > 1 else ""))
            if not any(os.path.exists(stem + ext) for ext in (".md", ".html", ".json")):
                break
            k += 1
        paste, check, block = _blocks(rs, tax)
        doc = {"kind": "taxonomy_revisit", "review_run_id": rid, "generated_at": gen, "sheet": "taxonomy",
               "columns": list(SHEET_COLUMNS), "paste_rows": [c for c, _ in paste],
               "paste_requests": [nos for _, nos in paste],
               "check_rows": [{"row": c, "reason": why, "requests": nos} for c, why, nos in check],
               "requests": [dict(r, no=i, block=block[i]) for i, r in enumerate(rs, 1)]}
        util.write_text(stem + ".md", _run_md(rid, gen, rs, paste, check, block))
        util.write_text(stem + ".html", _run_html(rid, gen, rs, paste, check, block))
        util.write_text(stem + ".json", json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
        written += [stem + ".md", stem + ".html", stem + ".json"]
    return written
