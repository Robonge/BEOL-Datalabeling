"""2차 질문: 승인된 질문 매핑(규칙) + 1차 라벨 검증 질문 생성(LLM).

승인 질문은 공통 질문 전부와 chunk 축 값에 해당하는 카테고리 질문이다. 상한은 우선순위(작을수록 먼저), 같으면 질문 ID 순.
검증 질문은 1차 분류가 붙인 라벨(해당 없음·unknown 제외)마다 LLM이 하나씩 만드는 O/X 판정 질문이다.
본문이 라벨을 뒷받침하면 O, 반박하면 X가 되도록 출제한다. 질문은 gen_questions 표에 남는다.
대조 질문(Q-CTL-)은 이 chunk에 붙지 않은 taxonomy 라벨로 같은 호출에서 만든다. O가 나오지 않을 것으로 기대하는
대조군이라 답은 labels에 kind='control'로 따로 남고, 확정 라벨·label_hash·적재·N/A 알림에 들어가지 않는다.
남은 질문 상한 중 limits.control_ratio만큼을 대조 질문에 쓴다. 질문은 ctl_questions 표에 남는다.
"""
import math

from labelbot import prompts, util
from labelbot.llm import CallFailed
from labelbot.store import add_failure
from labelbot.taxonomy import Question

GEN_PREFIX = "Q-GEN-"
CTL_PREFIX = "Q-CTL-"
GEN_PRIORITY = 50
CTL_RATIO_MAX = 0.9
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


def ctl_qid(chunk_id, axis, value):
    return CTL_PREFIX + util.sha256_text("ctl|%s|%s|%s" % (chunk_id, axis, value))[:10]


def is_control(qid):
    return str(qid or "").startswith(CTL_PREFIX)


def control_ratio(cfg):
    """limits.control_ratio를 [0, CTL_RATIO_MAX]로 자른 값. 숫자가 아니거나 NaN이면 0(끔)."""
    try:
        r = float(cfg["limits"].get("control_ratio") or 0)
    except (TypeError, ValueError):
        return 0.0
    return min(max(r, 0.0), CTL_RATIO_MAX) if math.isfinite(r) else 0.0


def split_budget(n_targets, budget, ratio):
    """남은 질문 상한을 (검증 질문 수, 대조 질문 수)로 나눈다.

    대조 질문은 상한의 ratio만큼(반올림)을 넘지 않으면서 검증 대상 수와의 비율이 ratio에 가깝게 정하고
    (몫이 있으면 최소 1개), 검증 질문은 남은 칸을 대상 수만큼 채운다. 검증 대상이 없으면 대상 1개일 때만큼
    대조 질문만 낸다(2026-10-05 사용자 결정: 저확신·unknown이 없는 chunk도 대조 질문은 받는다).
    """
    budget, n_targets = max(0, int(budget)), max(0, int(n_targets))
    ratio = min(max(float(ratio or 0), 0.0), CTL_RATIO_MAX)
    reserve = int(budget * ratio + 0.5 + 1e-9)  # 1e-9: 0.6/0.4=1.4999… 같은 부동소수점 오차로 반올림이 내려가지 않게
    want = int(max(n_targets, 1) * ratio / (1 - ratio) + 0.5 + 1e-9) if ratio else 0
    n_ctl = min(reserve, max(1, want)) if reserve else 0
    return min(n_targets, budget - n_ctl), n_ctl


def control_targets(tax, chunk_id, axes, n):
    """대조 라벨: 이 chunk에 붙지 않은 (축, 값) n개. 활성 축만 쓴다.

    참일 수 있는 값은 뺀다: 붙은 값과 그 상위·하위 값, 1차가 unknown이라 한 축의 값 전부.
    순위는 붙은 값이 있는 단일값 축(같은 축의 다른 값이 가장 헷갈리는 음성 대조군), 붙은 값이 있는 다중값 축,
    나머지 축 순이고, 같은 순위 안에서는 chunk별 해시 순이라 재실행해도 같다.
    """
    if n <= 0:
        return []
    direct, held, unknown_axes = set(), set(), set()
    for name, a in axes.items():
        for v in a["values"]:
            if v == "unknown":
                unknown_axes.add(name)
            if v in _SKIP:
                continue
            direct.add((name, v))
            held.update((name, anc) for anc in _ancestors(tax, name, v))
    used_axes = {name for name, _ in direct}
    pool = []
    for a in tax.axes:
        if not a.active or a.name in unknown_axes:
            continue
        rank = (1 if a.multi else 0) if a.name in used_axes else 2
        for v in a.values:
            if v.name in _SKIP or (a.name, v.name) in held:
                continue
            if any((a.name, anc) in direct for anc in _ancestors(tax, a.name, v.name)[1:]):
                continue
            pool.append((rank, util.sha256_text("%s|%s|%s" % (chunk_id, a.name, v.name)), (a.name, v.name)))
    pool.sort()
    return [t for _, _, t in pool[:n]]


def alias_qid(qid):
    """3차 프롬프트에 보이는 대조 질문 ID. 검증 질문과 같은 모양이라 라벨러가 대조 질문을 가려내지 못한다."""
    return GEN_PREFIX + util.sha256_text("alias|" + qid)[:10]


def verify_targets(tax, axes, limit, conf_min):
    """검증 대상: 1차가 unknown이라 한 활성 축과, 축 확신도가 conf_min 미만인 붙은 라벨(2026-10-05 사용자 결정).

    반환: [(축, 값)] 상한까지. unknown 축은 값이 None이며, 질문 생성 LLM이 그 축의 후보 값 중 하나를 골라 출제한다.
    순서는 확신도 낮은 순(unknown은 0으로 본다), 같으면 축 순서다. 확신도가 모두 conf_min 이상이면 빈 목록이다.
    """
    out = []
    for i, a in enumerate(tax.axes):
        got = axes.get(a.name)
        if not a.active or not got:
            continue
        conf = got.get("confidence")
        conf = conf if isinstance(conf, (int, float)) else None
        if "unknown" in got["values"]:
            out.append((0.0, i, (a.name, None)))
            continue
        if conf is None or conf >= conf_min - 1e-12:
            continue
        for v in got["values"]:
            if v not in _SKIP and (a.name, v) not in [t for _, _, t in out]:
                out.append((conf, i, (a.name, v)))
    out.sort(key=lambda r: (r[0], r[1]))
    return [t for _, _, t in out][:max(0, limit)]


def verify_max(cfg):
    """한 chunk의 검증 질문 최대 수(limits.verify_max, 기본 3)."""
    try:
        return max(0, int(cfg["limits"].get("verify_max", 3)))
    except (TypeError, ValueError):
        return 3


def conf_min(cfg):
    return float(cfg["flag"]["confidence_min"])


# 질문 다양화(2026-10-05): gpt-6-sol은 temperature를 받지 않아 프롬프트로 문형·관점을 정해 준다.
# 문형은 표현만 바꾸고 질문의 범위는 같다. 관점은 대조 질문에만 주며, 본문의 그 요소를 빌려 근접 오답을 만든다.
FRAMES = (
    "이 chunk는 ~을(를) 다루는가?",
    "본문에 ~에 해당하는 내용이 있는가?",
    "이 슬라이드의 내용은 ~에 관한 것인가?",
    "본문에서 ~이(가) 언급되는가?",
    "이 자료가 설명하는 대상은 ~인가?",
)
ANGLES = ("공정 조건·레시피", "측정 항목·수치", "불량·이상 현상", "평가 판정·결론", "구조·층·위치")


def variation(chunk_id, n_gen, n_ctl):
    """반환: (검증 질문 문형 번호 목록, 대조 질문 (문형 번호, 관점) 목록). 번호는 1부터.

    chunk마다 해시로 시작점을 정하고 차례로 돌려, 한 chunk 안에서는 문형이 겹치지 않고(5개까지)
    chunk끼리는 시작점이 달라진다. 재실행하면 같다.
    """
    h = int(util.sha256_text("var|" + chunk_id), 16)
    start, angle0 = h % len(FRAMES), (h // len(FRAMES)) % len(ANGLES)
    frames = [(start + i) % len(FRAMES) + 1 for i in range(n_gen + n_ctl)]
    return frames[:n_gen], [(frames[n_gen + j], ANGLES[(angle0 + j) % len(ANGLES)]) for j in range(n_ctl)]


def _yes_no(text):
    return text.endswith("?") and not any(w in text for w in _OPEN_WORDS)


def _candidates(tax, axis):
    ax = tax.axis(axis)
    return [v for v in (ax.values if ax else []) if v.name not in _SKIP]


def _gen_validator(targets, tax):
    """검증 질문만 엄격히 본다(틀리면 재시도). 대조 질문은 _valid_controls가 따로 골라 검증 질문을 잃지 않게 한다.

    값이 정해진 대상은 (축, 값)이 그대로, unknown 축 대상은 그 축의 후보 값 중 하나로 정확히 한 번씩 나와야 한다.
    """
    fixed = {t for t in targets if t[1] is not None}
    open_axes = {a: {v.name for v in _candidates(tax, a)} for a, v in targets if v is None}

    def validate(obj):
        if not isinstance(obj, dict) or not isinstance(obj.get("questions"), list):
            return False, "FORMAT_INVALID"
        seen, seen_open = set(), set()
        for q in obj["questions"]:
            if not isinstance(q, dict):
                return False, "FORMAT_INVALID"
            key, text = (q.get("axis"), q.get("value")), str(q.get("text") or "").strip()
            if key in fixed and key not in seen:
                seen.add(key)
            elif key[0] in open_axes and key[1] in open_axes[key[0]] and key[0] not in seen_open:
                seen_open.add(key[0])
            else:
                return False, "UNKNOWN_TARGET"
            if not _yes_no(text):
                return False, "NOT_YES_NO"
        if seen != fixed or seen_open != set(open_axes):
            return False, "QUESTION_MISSING"
        return True, None

    return validate


def _valid_controls(items, want):
    """반환: ({(축, 값): 문구}, 버린 사유 코드 또는 None). 형식에 맞는 대조 질문만 남긴다."""
    if not want:
        return {}, None
    if not isinstance(items, list):
        return {}, "CONTROL_FORMAT_INVALID"
    out = {}
    for q in items:
        if not isinstance(q, dict):
            continue
        key, text = (q.get("axis"), q.get("value")), str(q.get("text") or "").strip()
        if key in want and key not in out and _yes_no(text):
            out[key] = text
    return out, (None if len(out) == len(want) else "CONTROL_DROPPED")


def _target_lines(targets, defs, tags, tax=None):
    lines = []
    for (a, v), tag in zip(targets, tags):
        if v is None:  # unknown 축: 후보 값 중 본문에 가장 가까운 하나를 골라 출제한다
            cands = ", ".join("%s(%s)" % (c.name, (c.definition or "")[:40]) if c.definition else c.name
                              for c in _candidates(tax, a))
            lines.append("- %s = ? (1차 unknown. 아래 후보 중 본문에 가장 가까운 값 하나를 골라 value에 쓴다) 후보: %s [%s]"
                         % (a, cands, tag))
        else:
            lines.append("- %s = %s : %s [%s]" % (a, v, defs.get((a, v)) or "(정의 없음)", tag))
    return "\n".join(lines) or "(없음)"


def generate_questions(ctx, chunk, axes, limit):
    """unknown 축과 확신도 낮은 1차 라벨(최대 limits.verify_max개)에 O/X 검증 질문을, 붙지 않은 라벨로 대조 질문을
    한 호출에서 만든다. 검증 대상이 없으면 대조 질문만 만든다.

    반환: Question 목록(검증 질문 뒤에 대조 질문. 실패하면 빈 목록, failures에 기록).
    """
    all_targets = verify_targets(ctx.tax, axes, min(limit, verify_max(ctx.cfg)), conf_min(ctx.cfg))
    n_gen, n_ctl = split_budget(len(all_targets), limit, control_ratio(ctx.cfg))
    targets = all_targets[:n_gen]
    controls = control_targets(ctx.tax, chunk["chunk_id"], axes, n_ctl)
    if not targets and not controls:
        return []
    gen_frames, ctl_vars = variation(chunk["chunk_id"], len(targets), len(controls))
    defs = {}
    for a in ctx.tax.axes:
        for v in a.values:
            defs[(a.name, v.name)] = v.definition or ""
    f = ctx.con.execute("SELECT title FROM files WHERE file_id=?", (chunk["file_id"],)).fetchone()
    values = {
        "doc_title": (f["title"] if f else "") or "(없음)",
        "slide_title": chunk["title"] or "(없음)",
        "frames": "\n".join("%d. %s" % (i + 1, f) for i, f in enumerate(FRAMES)),
        "targets": _target_lines(targets, defs, ["문형 %d" % n for n in gen_frames], ctx.tax),
        "controls": _target_lines(controls, defs, ["문형 %d · 관점: %s" % fa for fa in ctl_vars]),
        "chunk_text": chunk["text"],
    }
    messages = prompts.render("question_gen", values)
    hint = {"task": "question_gen", "targets": [list(t) for t in targets], "controls": [list(t) for t in controls],
            "candidates": {a: [c.name for c in _candidates(ctx.tax, a)] for a, v in targets if v is None},
            "text": chunk["text"]}
    try:
        obj = ctx.chat.chat_json(messages, [chunk["file_id"]], _gen_validator(targets, ctx.tax), hint=hint)
    except CallFailed as e:
        ctx.fail("question_gen", chunk["chunk_id"], e.reason_code)
        return []
    by_ctl, dropped = _valid_controls(obj.get("controls"), set(controls))
    if dropped:
        add_failure(ctx.con, ctx.run_id, "question_ctl", chunk["chunk_id"], dropped)
    out, now, ver = [], util.now_iso(), prompts.version("question_gen")
    by_gen = {(q["axis"], q["value"]): str(q["text"]).strip() for q in obj["questions"]}
    chosen = {a: v for a, v in by_gen if (a, None) in targets}  # unknown 축에 LLM이 고른 값
    targets = [(a, chosen[a] if v is None else v) for a, v in targets]
    for table, make_qid, by_key, want in (("gen_questions", gen_qid, by_gen, targets),
                                         ("ctl_questions", ctl_qid, by_ctl, [t for t in controls if t in by_ctl])):
        for a, v in want:
            qid = make_qid(chunk["chunk_id"], a, v)
            ctx.con.execute(
                "INSERT OR REPLACE INTO %s(qid, chunk_id, axis, value, text, prompt_version, created_at)"
                " VALUES(?,?,?,?,?,?,?)" % table, (qid, chunk["chunk_id"], a, v, by_key[(a, v)], ver, now))
            out.append(Question(qid, by_key[(a, v)], (a, v), GEN_PRIORITY, None))
    return out


def all_questions(con, tax):
    """승인 질문 + 생성된 검증 질문(화면·산출에서 질문 문구를 찾을 때 쓴다). 대조 질문은 넣지 않는다."""
    out = list(tax.questions)
    for r in con.execute("SELECT qid, axis, value, text FROM gen_questions ORDER BY qid"):
        out.append(Question(r["qid"], r["text"], (r["axis"], r["value"]), GEN_PRIORITY, None))
    return out


def control_answers(con, run_id, chunk_ids=None):
    """{chunk_id: [{qid, axis, value, text, answer, quote, confidence}]}. 대조 질문 답(labels kind='control')."""
    q = ("SELECT l.chunk_id, l.key, l.value, l.evidence, l.confidence, c.axis, c.value AS target, c.text"
         " FROM labels l LEFT JOIN ctl_questions c ON c.qid=l.key WHERE l.run_id=? AND l.kind='control'")
    out = {}
    for r in con.execute(q + " ORDER BY l.id", (run_id,)):
        if chunk_ids is not None and r["chunk_id"] not in chunk_ids:
            continue
        out.setdefault(r["chunk_id"], []).append({
            "qid": r["key"], "axis": r["axis"], "value": r["target"], "text": r["text"] or "",
            "answer": r["value"], "quote": r["evidence"] or "", "confidence": r["confidence"]})
    return out
