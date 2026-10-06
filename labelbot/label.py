"""3차 라벨링: 매핑된 질문마다 O/X/N/A, 근거 인용, 확신도. 같은 호출에서 날짜·담당자 추출."""
import datetime
import json
import re

from labelbot import prompts, util
from labelbot.llm import CallFailed
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


def _blind(questions):
    """대조 질문을 검증 질문과 같은 모양의 별칭 ID로 바꾸고 생성 질문을 ID 순으로 섞는다.

    반환: (프롬프트에 보일 질문 목록, {보일 ID: 원래 ID}). 라벨러가 ID나 순서로 대조 질문을 가려내지 못하게 한다.
    """
    from labelbot.questions import GEN_PREFIX, alias_qid, is_control

    back, shown = {}, []
    for q in questions:
        s = q._replace(qid=alias_qid(q.qid)) if is_control(q.qid) else q
        back[s.qid] = q.qid
        shown.append(s)
    gen = sorted((q for q in shown if q.qid.startswith(GEN_PREFIX)), key=lambda q: q.qid)
    return [q for q in shown if not q.qid.startswith(GEN_PREFIX)] + gen, back


def label_chunk(ctx, chunk, cls_res, questions):
    """성공하면 dict(답의 키는 원래 질문 ID), 실패하면 None."""
    con = ctx.con
    questions, back = _blind(questions)
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
        "feedback_rules": ctx.feedback.rules_text("label", questions),
        "chunk_text": chunk["text"],
        "response_format": RESPONSE_FORMAT,
    }
    messages = prompts.render("label", values)
    hint = {"task": "label", "qids": qids, "text": chunk["text"],
            "controls": [s for s, q in back.items() if s != q]}
    try:
        obj = ctx.chat.chat_json(messages, [chunk["file_id"]], _validator(qids), hint=hint)
    except CallFailed as e:
        ctx.fail("label", chunk["chunk_id"], e.reason_code)
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
        answers[back[q]] = {"answer": a["answer"], "quote": str(a.get("quote") or "")[:1000], "confidence": conf}
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
    """대조 질문(Q-CTL-) 답은 kind='control'로 남겨 확정 라벨(kind='answer')에 섞지 않는다."""
    from labelbot.questions import is_control

    con, base = ctx.con, ctx.label_base()
    for q, a in res["answers"].items():
        con.execute(
            "INSERT INTO labels(run_id, chunk_id, kind, key, value, status, evidence, confidence, sheet_hashes,"
            " prompt_version, model, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (ctx.run_id, chunk_id, "control" if is_control(q) else "answer", q, a["answer"], None, a["quote"],
             a["confidence"]) + base("label"),
        )
    for e in res["extracted"]:
        con.execute(
            "INSERT INTO labels(run_id, chunk_id, kind, key, value, status, evidence, confidence, sheet_hashes,"
            " prompt_version, model, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (ctx.run_id, chunk_id, "extract", e["item"], e["value"], e["flag"] or None, e["quote"], None) + base("label"),
        )
