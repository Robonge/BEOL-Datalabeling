"""1차 분류: chunk당 1회 호출로 활성 축 전부, 근거, 확신도, chunk 유형을 받는다."""
import json

from labelbot import prompts, util
from labelbot.llm import CallFailed, SendBlocked
from labelbot.store import add_failure

NA = "해당 없음"
UNKNOWN = "unknown"
SPECIAL = (NA, UNKNOWN)
CHUNK_TYPES = ("내용", "표지", "목차", "참고문헌")

RESPONSE_FORMAT = json.dumps(
    {
        "chunk_type": "내용 | 표지 | 목차 | 참고문헌",
        "axes": {"<축 이름>": {"values": ["<값 또는 해당 없음 또는 unknown>"], "evidence": "<본문 인용>", "confidence": 0.0}},
        "term_mappings": [{"expression": "<본문 표현>", "canonical": "<표준어>", "axis": "<축>", "evidence": "<인용>"}],
        "new_values": [{"axis": "<축>", "value": "<제안 값>", "parent": "<상위값 또는 빈칸>", "evidence": "<인용>"}],
    },
    ensure_ascii=False,
    indent=1,
)


def taxonomy_block(tax):
    out = []
    for ax in tax.active_axes():
        out.append(
            "### %s (종류: %s, 다중값: %s, 계층: %s)" % (ax.name, ax.kind, "Y" if ax.multi else "N", "Y" if ax.hierarchical else "N")
        )
        if ax.definition:
            out.append("정의: %s" % ax.definition)
        if ax.include:
            out.append("포함 예: %s" % ax.include)
        if ax.exclude:
            out.append("제외 예: %s" % ax.exclude)
        for v in ax.values:
            parts = ["- %s" % v.name]
            if v.parent:
                parts.append("(상위: %s)" % v.parent)
            if v.definition:
                parts.append(": %s" % v.definition)
            extra = []
            if v.include:
                extra.append("포함 예 %s" % v.include)
            if v.exclude:
                extra.append("제외 예 %s" % v.exclude)
            if extra:
                parts.append(" [%s]" % "; ".join(extra))
            out.append(" ".join(parts))
        out.append("")
    return "\n".join(out).strip()


def synonym_lines(matches):
    return "\n".join("- %s → %s" % (a, c) for a, c in matches) or "(없음)"


def file_context(ctx, file_id):
    """분류 맥락. 처음 본 위치와 그때의 파일명을 고정해 넣는다(파일을 옮겨도 프롬프트가 같다)."""
    con = ctx.con
    f = con.execute("SELECT file_name, title FROM files WHERE file_id=?", (file_id,)).fetchone()
    loc = con.execute(
        "SELECT rel_path FROM file_locations WHERE file_id=? ORDER BY first_seen_run, rel_path LIMIT 1", (file_id,)
    ).fetchone()
    titles = [r[0] for r in con.execute("SELECT title FROM chunks WHERE file_id=? ORDER BY seq", (file_id,))]
    memo = ctx.file_memos.get(file_id, "")
    return {
        "file_name": f["file_name"] if f else "",
        "rel_path": loc[0] if loc else "",
        "doc_title": (f["title"] if f else "") or "",
        "slide_titles": " / ".join(t for t in titles if t) or "(없음)",
        "file_memo": memo or "(없음)",
    }


def _validator(tax):
    active = {a.name: a for a in tax.active_axes()}

    def validate(obj):
        if not isinstance(obj, dict):
            return False, "FORMAT_INVALID"
        if obj.get("chunk_type") not in CHUNK_TYPES:
            return False, "BAD_CHUNK_TYPE"
        axes = obj.get("axes")
        if not isinstance(axes, dict):
            return False, "FORMAT_INVALID"
        if set(active) - set(axes):
            return False, "AXIS_MISSING"
        for name, ax in active.items():
            e = axes[name]
            if not isinstance(e, dict) or not isinstance(e.get("values"), list) or not e["values"]:
                return False, "AXIS_VALUES_INVALID"
            if not all(isinstance(v, str) for v in e["values"]):
                return False, "AXIS_VALUES_INVALID"
            if not ax.multi and len(set(e["values"])) > 1:
                return False, "SINGLE_AXIS_MULTI"
        return True, None

    return validate


def _conf(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if 0.0 <= x <= 1.0 else None


def normalize_axes(tax, axes_obj):
    """허용 밖 값 제거(→ 새 값 후보), 3상태 정리, 계층 축은 하위만, 단일값 축은 1개."""
    result, new_values = {}, []
    for ax in tax.active_axes():
        e = axes_obj[ax.name]
        names = {v.name: v for v in ax.values}
        vals = []
        for v in e["values"]:
            v = v.strip()
            if v in names or v in SPECIAL:
                if v not in vals:
                    vals.append(v)
            elif v:
                new_values.append({"axis": ax.name, "value": v, "parent": "", "evidence": e.get("evidence") or ""})
        real = [v for v in vals if v in names]
        if real:
            if ax.hierarchical:
                parents = {names[v].parent for v in real if names[v].parent}
                real = [v for v in real if v not in parents]
            vals = real
        elif not vals:
            vals = [UNKNOWN]
        else:
            vals = [UNKNOWN] if UNKNOWN in vals else [NA]
        if not ax.multi:
            vals = vals[:1]
        status = "value" if vals[0] in names else ("na" if vals[0] == NA else "unknown")
        result[ax.name] = {
            "values": vals,
            "status": status,
            "evidence": (e.get("evidence") or "")[:1000],
            "confidence": _conf(e.get("confidence")),
        }
    for ax in tax.axes:
        if not ax.active:
            result[ax.name] = {"values": [NA], "status": "na", "evidence": "", "confidence": None, "inactive": True}
    return result, new_values


def classify_chunk(ctx, chunk):
    """성공하면 결과 dict, 실패하면 None(failures에 사유 코드)."""
    tax = ctx.tax
    replaced, matches = ctx.syn.apply(chunk["text"])
    values = dict(file_context(ctx, chunk["file_id"]))
    # 검수 피드백: 승인 규칙과 유사한 승인 사례. 사례 본문도 LLM에 가므로 사례 파일 ID를 가드에 함께 넘긴다.
    fb_examples, fb_files = ctx.feedback.examples_for(chunk)
    values.update(
        {
            "synonym_matches": synonym_lines(matches),
            "taxonomy": ctx.taxonomy_text,
            "feedback_rules": ctx.feedback.rules_text("classify"),
            "feedback_examples": fb_examples,
            "chunk_text": replaced,
            "response_format": RESPONSE_FORMAT,
        }
    )
    messages = prompts.render("classify", values)
    hint = {
        "task": "classify",
        "text": replaced,
        "axes": {a.name: {"values": [v.name for v in a.values], "multi": a.multi} for a in tax.active_axes()},
    }
    try:
        obj = ctx.chat.chat_json(messages, sorted({chunk["file_id"]} | set(fb_files)), _validator(tax), hint=hint)
    except (CallFailed, SendBlocked) as e:
        ctx.fail("classify", chunk["chunk_id"], e.reason_code)
        return None
    active_names = {a.name for a in tax.active_axes()}
    for k in obj["axes"]:
        if k not in active_names:
            add_failure(ctx.con, ctx.run_id, "classify", chunk["chunk_id"], "UNKNOWN_AXIS_KEY")
            break
    axes, new_values = normalize_axes(tax, obj["axes"])
    for nv in obj.get("new_values") or []:
        if isinstance(nv, dict) and nv.get("axis") in active_names and nv.get("value"):
            new_values.append(nv)
    return {
        "chunk_type": obj["chunk_type"],
        "axes": axes,
        "matches": matches,
        "term_mappings": [t for t in obj.get("term_mappings") or [] if isinstance(t, dict)],
        "new_values": new_values,
    }


def store_result(ctx, chunk_id, res):
    con, base = ctx.con, ctx.label_base()
    con.execute(
        "INSERT INTO labels(run_id, chunk_id, kind, key, value, status, evidence, confidence, sheet_hashes,"
        " prompt_version, model, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (ctx.run_id, chunk_id, "chunk_type", "", res["chunk_type"], None, None, None) + base("classify"),
    )
    for name, a in res["axes"].items():
        con.execute(
            "INSERT INTO labels(run_id, chunk_id, kind, key, value, status, evidence, confidence, sheet_hashes,"
            " prompt_version, model, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (ctx.run_id, chunk_id, "axis", name, util.dumps(a["values"]), a["status"], a["evidence"], a["confidence"])
            + base("classify"),
        )
