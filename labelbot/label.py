"""3차 라벨링: 매핑된 질문마다 O/X/N/A, 근거 인용, 확신도. 같은 호출에서 날짜·담당자 추출."""
import datetime
import json
import re

from labelbot import prompts, util
from labelbot.llm import CallFailed, SendBlocked
from labelbot.store import add_failure

ANSWERS = ("O", "X", "N/A")

RESPONSE_FORMAT = json.dumps(
    {
        "answers": {"<질문 ID>": {"answer": "O | X | N/A", "quote": "<본문 그대로 인용>", "confidence": 0.0}},
        "extracted": [{"item": "date | person", "value": "<본문 표기>", "quote": "<본문 인용>"}],
        "term_mappings": [{"expression": "<본문 표현>", "canonical": "<표준어>", "evidence": "<인용>"}],
    },
    ensure_ascii=False,
    indent=1,
)

_FULL_DATE = re.compile(r"(\d{4})\s*(?:[.\-/]|년)\s*(\d{1,2})\s*(?:[.\-/]|월)\s*(\d{1,2})\s*일?")
_YEAR_MONTH = re.compile(r"^(\d{4})\s*(?:[.\-/]|년)\s*(\d{1,2})\s*월?$")
_SHORT_DATE = re.compile(r"^\d{1,2}\s*[./\-]\s*\d{1,2}\s*[./\-]\s*\d{1,2}$")


def normalize_date(raw, today=None):
    """반환: (값, 사유 코드). 연월일 순서가 확정되지 않으면 값 None, 사유 AMBIGUOUS_DATE."""
    s = util.nfkc(raw).strip()
    m = _FULL_DATE.search(s)
    if m:
        try:
            d = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None, "INVALID_DATE"
        today = today or datetime.date.today()
        return d.isoformat(), ("FUTURE_DATE" if d > today else None)
    m = _YEAR_MONTH.match(s)
    if m and 1 <= int(m.group(2)) <= 12:
        return "%s-%02d" % (m.group(1), int(m.group(2))), None
    if _SHORT_DATE.match(s):
        return None, "AMBIGUOUS_DATE"
    return None, "UNPARSED_DATE"


def quote_in_text(quote, text):
    q = util.norm_for_match(quote)
    return bool(q) and q in util.norm_for_match(text)


def _validator(qids):
    want = set(qids)

    def validate(obj):
        if not isinstance(obj, dict) or not isinstance(obj.get("answers"), dict):
            return False, "FORMAT_INVALID"
        ans = obj["answers"]
        if want - set(ans):
            return False, "QUESTION_MISSING"
        for q in want:
            a = ans[q]
            if not isinstance(a, dict) or a.get("answer") not in ANSWERS:
                return False, "BAD_ANSWER"
            if a["answer"] in ("O", "X") and not str(a.get("quote") or "").strip():
                return False, "QUOTE_MISSING"
        return True, None

    return validate


def _axis_summary(axes):
    parts = []
    for name, a in axes.items():
        if a.get("inactive"):
            continue
        parts.append("%s=%s" % (name, ",".join(a["values"])))
    return "; ".join(parts)


def neighbor_titles(con, chunk):
    rows = con.execute(
        "SELECT seq, title FROM chunks WHERE file_id=? AND seq IN (?, ?)",
        (chunk["file_id"], chunk["seq"] - 1, chunk["seq"] + 1),
    ).fetchall()
    by = {r["seq"]: r["title"] or "" for r in rows}
    return by.get(chunk["seq"] - 1) or "(없음)", by.get(chunk["seq"] + 1) or "(없음)"


def label_chunk(ctx, chunk, cls_res, questions):
    """성공하면 dict, 실패하면 None."""
    con = ctx.con
    qids = [q.qid for q in questions]
    _, matches = ctx.syn.apply(chunk["text"])
    prev_t, next_t = neighbor_titles(con, chunk)
    f = con.execute("SELECT title FROM files WHERE file_id=?", (chunk["file_id"],)).fetchone()
    values = {
        "doc_title": (f["title"] if f else "") or "(없음)",
        "slide_title": chunk["title"] or "(없음)",
        "prev_title": prev_t,
        "next_title": next_t,
        "axis_values": _axis_summary(cls_res["axes"]),
        "synonym_matches": "\n".join("- %s → %s" % (a, c) for a, c in matches) or "(없음)",
        "questions": "\n".join("- %s: %s" % (q.qid, q.text) for q in questions),
        "chunk_text": chunk["text"],
        "response_format": RESPONSE_FORMAT,
    }
    messages = prompts.render("label", values)
    hint = {"task": "label", "qids": qids, "text": chunk["text"]}
    try:
        obj = ctx.chat.chat_json(messages, [chunk["file_id"]], _validator(qids), hint=hint)
    except (CallFailed, SendBlocked) as e:
        add_failure(con, ctx.run_id, "label", chunk["chunk_id"], e.reason_code)
        ctx.log("label", chunk["chunk_id"], e.reason_code)
        return None
    if set(obj["answers"]) - set(qids):
        add_failure(con, ctx.run_id, "label", chunk["chunk_id"], "UNMAPPED_QUESTION")
    answers = {}
    for q in qids:
        a = obj["answers"][q]
        conf = a.get("confidence")
        try:
            conf = float(conf)
            conf = conf if 0 <= conf <= 1 else None
        except (TypeError, ValueError):
            conf = None
        answers[q] = {"answer": a["answer"], "quote": str(a.get("quote") or "")[:1000], "confidence": conf}
    extracted = []
    for e in obj.get("extracted") or []:
        if not isinstance(e, dict):
            continue
        item, raw, quote = e.get("item"), str(e.get("value") or ""), str(e.get("quote") or "")
        if not raw or not quote_in_text(quote, chunk["text"]):
            add_failure(con, ctx.run_id, "extract", chunk["chunk_id"], "QUOTE_NOT_IN_TEXT")
            continue
        if item == "date":
            val, reason = normalize_date(raw)
            if val is None:
                add_failure(con, ctx.run_id, "extract", chunk["chunk_id"], reason)
                continue
            extracted.append({"item": "date", "value": val, "quote": quote, "flag": reason or ""})
        elif item == "person":
            if util.norm_for_match(raw) not in util.norm_for_match(quote):
                add_failure(con, ctx.run_id, "extract", chunk["chunk_id"], "PERSON_NOT_IN_QUOTE")
                continue
            extracted.append({"item": "person", "value": raw.strip(), "quote": quote, "flag": ""})
    return {
        "answers": answers,
        "extracted": extracted,
        "term_mappings": [t for t in obj.get("term_mappings") or [] if isinstance(t, dict)],
    }


def store_result(ctx, chunk_id, res):
    con, base = ctx.con, ctx.label_base()
    for q, a in res["answers"].items():
        con.execute(
            "INSERT INTO labels(run_id, chunk_id, kind, key, value, status, evidence, confidence, sheet_hashes,"
            " prompt_version, model, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (ctx.run_id, chunk_id, "answer", q, a["answer"], None, a["quote"], a["confidence"]) + base("label"),
        )
    for e in res["extracted"]:
        con.execute(
            "INSERT INTO labels(run_id, chunk_id, kind, key, value, status, evidence, confidence, sheet_hashes,"
            " prompt_version, model, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (ctx.run_id, chunk_id, "extract", e["item"], e["value"], e["flag"] or None, e["quote"], None) + base("label"),
        )
