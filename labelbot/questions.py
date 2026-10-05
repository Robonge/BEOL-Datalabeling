"""2차 질문: 승인된 질문 매핑(규칙) + 1차 라벨 검증 질문 생성(LLM).

승인 질문은 공통 질문 전부와 chunk 축 값에 해당하는 카테고리 질문이다. 상한은 우선순위(작을수록 먼저), 같으면 질문 ID 순.
검증 질문은 1차 분류가 붙인 라벨(해당 없음·unknown 제외)마다 LLM이 하나씩 만드는 O/X 판정 질문이다.
본문이 라벨을 뒷받침하면 O, 반박하면 X가 되도록 출제한다. 질문은 gen_questions 표에 남는다.
"""
from labelbot import prompts, util
from labelbot.llm import CallFailed, SendBlocked
from labelbot.taxonomy import Question

GEN_PREFIX = "Q-GEN-"
GEN_PRIORITY = 50
_SKIP = ("해당 없음", "unknown")
_OPEN_WORDS = ("왜", "어떻게", "무엇", "얼마나", "어느 정도")


def _ancestors(tax, axis_name, value):
    ax = tax.axis(axis_name)
    names = {v.name: v for v in ax.values} if ax else {}
    out, cur = [], value
    while cur in names:
        out.append(cur)
        cur = names[cur].parent
        if cur in out:
            break
    return out


def map_questions(tax, axes, limit):
    """반환: (매핑된 질문 목록, 상한으로 잘린 질문 목록)."""
    held = set()
    for name, a in axes.items():
        for v in a["values"]:
            for anc in _ancestors(tax, name, v):
                held.add((name, anc))
    mapped = []
    for q in tax.questions:
        if q.target == "공통" or (isinstance(q.target, tuple) and tuple(q.target) in held):
            mapped.append(q)
    mapped.sort(key=lambda q: (q.priority, q.qid))
    return mapped[:limit], mapped[limit:]


def gen_qid(chunk_id, axis, value):
    return GEN_PREFIX + util.sha256_text("%s|%s|%s" % (chunk_id, axis, value))[:10]


def verify_targets(tax, axes, limit):
    """검증 대상 라벨: (축, 값) 목록. 분류 축 순서대로, 상한까지."""
    out = []
    for a in tax.axes:
        got = axes.get(a.name)
        if not a.active or not got:
            continue
        for v in got["values"]:
            if v not in _SKIP and (a.name, v) not in out:
                out.append((a.name, v))
    return out[:max(0, limit)]


def _gen_validator(targets):
    want = set(targets)

    def validate(obj):
        if not isinstance(obj, dict) or not isinstance(obj.get("questions"), list):
            return False, "FORMAT_INVALID"
        seen = set()
        for q in obj["questions"]:
            if not isinstance(q, dict):
                return False, "FORMAT_INVALID"
            key, text = (q.get("axis"), q.get("value")), str(q.get("text") or "").strip()
            if key not in want or key in seen:
                return False, "UNKNOWN_TARGET"
            if not text.endswith("?") or any(w in text for w in _OPEN_WORDS):
                return False, "NOT_YES_NO"
            seen.add(key)
        if seen != want:
            return False, "QUESTION_MISSING"
        return True, None

    return validate


def generate_questions(ctx, chunk, axes, limit):
    """1차 라벨마다 O/X 검증 질문을 만든다. 반환: Question 목록(실패하면 빈 목록, failures에 기록)."""
    targets = verify_targets(ctx.tax, axes, limit)
    if not targets:
        return []
    defs = {}
    for a in ctx.tax.axes:
        for v in a.values:
            defs[(a.name, v.name)] = v.definition or ""
    f = ctx.con.execute("SELECT title FROM files WHERE file_id=?", (chunk["file_id"],)).fetchone()
    values = {
        "doc_title": (f["title"] if f else "") or "(없음)",
        "slide_title": chunk["title"] or "(없음)",
        "targets": "\n".join("- %s = %s : %s" % (a, v, defs.get((a, v)) or "(정의 없음)") for a, v in targets),
        "chunk_text": chunk["text"],
    }
    messages = prompts.render("question_gen", values)
    hint = {"task": "question_gen", "targets": [list(t) for t in targets], "text": chunk["text"]}
    try:
        obj = ctx.chat.chat_json(messages, [chunk["file_id"]], _gen_validator(targets), hint=hint)
    except (CallFailed, SendBlocked) as e:
        ctx.fail("question_gen", chunk["chunk_id"], e.reason_code)
        return []
    by_key = {(q["axis"], q["value"]): str(q["text"]).strip() for q in obj["questions"]}
    out, now, ver = [], util.now_iso(), prompts.version("question_gen")
    for a, v in targets:
        qid = gen_qid(chunk["chunk_id"], a, v)
        ctx.con.execute(
            "INSERT OR REPLACE INTO gen_questions(qid, chunk_id, axis, value, text, prompt_version, created_at)"
            " VALUES(?,?,?,?,?,?,?)", (qid, chunk["chunk_id"], a, v, by_key[(a, v)], ver, now))
        out.append(Question(qid, by_key[(a, v)], (a, v), GEN_PRIORITY, None))
    return out


def all_questions(con, tax):
    """승인 질문 + 생성된 검증 질문(화면·산출에서 질문 문구를 찾을 때 쓴다)."""
    out = list(tax.questions)
    for r in con.execute("SELECT qid, axis, value, text FROM gen_questions ORDER BY qid"):
        out.append(Question(r["qid"], r["text"], (r["axis"], r["value"]), GEN_PRIORITY, None))
    return out
