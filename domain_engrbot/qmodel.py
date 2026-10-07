"""질문 루프의 자료 형식(계약). questions·answers·question_screen·serve·taxonomy_board가 같이 쓴다.

설계는 domain_engrbot/docs/plan-question-loop.md 4절이다. 이 모듈은 형식과 파일 읽기·쓰기만 맡고 판단은 하지 않는다.
- 질문 묶음(questions.json), 답 파일(engr_answers_<set_id>.json), 초안(draft), taxonomy 제안 행의 형식.
- 초안은 check_draft 한 곳에서 정리·검증한다(LLM 응답, 화면이 보낸 답, 자유 답 초안이 모두 여기를 거친다).
- 규칙 문장은 labelbot 프롬프트에 들어가므로 금지 글자·치환 표식·길이를 labeling_review와 같은 기준으로 막는다.
"""
import datetime
import os
import re
import secrets

from domain_engrbot import io, ledger, model, paths

QUESTIONS_KIND = "engr_questions"
ANSWERS_KIND = "engr_answers"
VERSION = 1

QUESTIONS = "questions.json"
SCREEN = "engr_questions.html"
ANSWERS_LOG = "answers.jsonl"
PROPOSALS = "taxonomy_proposals.jsonl"
ASKED = "asked.json"
GENERATE_LOG = "generate_log.jsonl"
RULES_HISTORY = "rules_history.jsonl"   # 승인 파일을 바꾸기 전의 이전 본(커밋 사이의 변경을 되돌릴 때 쓴다)

GOALS = ("labeling", "taxonomy")
TOPIC_TYPES = ("axis_value", "axis", "question", "term", "general")
STAGES = ("classify", "label")
ACTIONS = ("answer", "dismiss", "skip")
# taxonomy 초안 kind → 필수 칸. taxonomy_board의 항목 kind와 같은 이름이다.
TAX_REQUIRED = {
    "value_add": ("axis", "value"), "value_def": ("axis", "value"), "axis_def": ("axis",),
    "overlap": ("axis", "values"), "value_off": ("axis", "value"), "new_axis": ("name",),
    "synonym": ("alias", "canonical"), "q_edit": ("qid",), "q_new": ("text",),
}
TAX_KINDS = tuple(TAX_REQUIRED)
NAME_KEYS = ("axis", "value", "parent", "name", "alias", "canonical", "qid")
LONG_KEYS = ("text", "definition", "include", "exclude")
# taxonomy 초안 kind → 쓰는 칸. 이 밖의 칸은 check_draft가 비운다. 질문 화면은 이 칸만 보여 주고 편집하게 하며,
# 보드도 이 칸만 행 초안에 채운다(사람이 보지 못한 문장이 확정되지 않게 한 곳에서 정한다).
TAX_FIELDS = {
    "value_add": ("axis", "value", "parent", "definition", "include", "exclude", "memo"),
    "value_def": ("axis", "value", "definition", "include", "exclude", "memo"),
    "axis_def": ("axis", "definition", "include", "exclude", "memo"),
    "overlap": ("axis", "values", "memo"),
    "value_off": ("axis", "value", "memo"),
    "new_axis": ("name", "definition", "include", "exclude", "memo"),
    "synonym": ("alias", "canonical", "memo"),
    "q_edit": ("qid", "text", "memo"),
    "q_new": ("text", "memo"),
}
# topic type → 지문에 꼭 있어야 하는 칸. 비면 general로 내려 문장 해시를 지문으로 쓴다.
TOPIC_REQUIRED = {"axis_value": ("axis", "values"), "axis": ("axis",), "question": ("qid",), "term": ("term",)}

RULE_TEXT_MAX = 300   # labeling_rules.TEXT_MAX, labelbot.feedback.TEXT_MAX와 같다
LONG_MAX = 500
MEMO_MAX = 300
NAME_MAX = 120
QUESTION_MAX = 400
WHY_MAX = 600
LABEL_MAX = 300
FREE_MAX = 2000
MAX_OPTIONS = 6
MAX_DRAFTS = 6
MAX_ANSWER_BYTES = 1024 * 1024

_PATTERN_ID = re.compile(r"^FR-[0-9a-f]{10}$")
_EXAMPLE_ID = re.compile(r"^EX-[0-9a-f]{12}$")
_SET_ID = re.compile(r"^QS-[0-9]{8}T[0-9]{6}-[0-9a-f]{4}$")
_QUESTION_ID = re.compile(r"^EQ-[0-9a-f]{10}$")
# 문장에 넣지 않는 글자: 줄바꿈·탭 밖의 제어 문자, 폭 없는 문자, 방향 제어 문자(labeling_review._BAD_TEXT와 같다)
_BAD_TEXT = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏‪-‮⁦-⁩]")


class QModelError(Exception):
    def __init__(self, reason_code):
        Exception.__init__(self, reason_code)
        self.reason_code = reason_code


# ---- 위치와 ID ------------------------------------------------------------------

def qdir(ledger_dir=None):
    """질문 폴더. 장부 폴더의 형제 "questions"다(장부가 workspaces/_domain_engrbot/ledger면 workspaces/_domain_engrbot/questions,
    테스트 임시 작업 폴더면 <작업 폴더>/qa/questions). ledger_dir가 없으면 코드 폴더의 기본 위치."""
    if ledger_dir:
        return os.path.join(os.path.dirname(os.path.abspath(ledger_dir)), "questions")
    return paths.data_path(os.path.join(io.CODE_ROOT, "workspaces"), "questions")


def dir_label(qd):
    """콘솔용 표시 이름 "<부모 이름>/<이름>"(경로 전체를 쓰지 않는다. ledger.dir_label과 같다)."""
    qd = os.path.abspath(qd)
    return "%s/%s" % (os.path.basename(os.path.dirname(qd)), os.path.basename(qd))


def new_set_id(now=None):
    ts = (now or datetime.datetime.now(datetime.timezone.utc)).strftime("%Y%m%dT%H%M%S")
    return "QS-%s-%s" % (ts, secrets.token_hex(2))


def valid_set_id(s):
    return isinstance(s, str) and bool(_SET_ID.match(s))


def valid_question_id(s):
    return isinstance(s, str) and bool(_QUESTION_ID.match(s))


def answers_name(set_id):
    return "engr_answers_%s.json" % set_id


# ---- 문장 정리 -------------------------------------------------------------------

def clean_text(text, limit):
    """사람·LLM이 쓴 문장. 줄바꿈·탭은 공백 하나로 바꾼다. 문자열이 아니거나, 비었거나, limit를 넘거나,
    금지 글자·프롬프트 치환 표식({{ }})이 있으면 None."""
    if not isinstance(text, str) or _BAD_TEXT.search(text):
        return None
    t = " ".join(text.split())
    if not t or len(t) > limit or "{{" in t or "}}" in t:
        return None
    return t


def soft_text(text, limit):
    """없어도 되는 문장 칸. 비었으면 "", 틀리면 None."""
    if text is None or (isinstance(text, str) and not text.strip()):
        return ""
    return clean_text(text, limit)


# ---- 지문과 질문 ID ---------------------------------------------------------------

def normalize_topic(topic):
    """topic 정리. type에 꼭 있어야 하는 칸(TOPIC_REQUIRED)이 비면 general로 내린다
    (열쇠 칸이 빈 질문끼리 지문이 겹쳐 서로를 닫지 않게)."""
    t = topic if isinstance(topic, dict) else {}
    kind = t.get("type") if t.get("type") in TOPIC_TYPES else "general"
    values = t.get("values") if isinstance(t.get("values"), list) else []
    out = {"type": kind, "axis": soft_text(t.get("axis"), NAME_MAX) or "",
           "values": [v for v in (soft_text(x, NAME_MAX) for x in values[:8]) if v],
           "qid": soft_text(t.get("qid"), NAME_MAX) or "", "term": soft_text(t.get("term"), NAME_MAX) or ""}
    if any(not out[k] for k in TOPIC_REQUIRED.get(kind, ())):
        out["type"] = "general"
    return out


def fingerprint(goal, topic, text):
    """같은 질문 판정용 지문. 답함·묻지 않음·이월 중복을 이것으로 거른다."""
    t = normalize_topic(topic)
    if t["type"] == "general":
        return "%s|general|%s" % (goal, model.sha256_text(model.norm_key(text or ""))[:16])
    return "|".join([goal, t["type"], model.norm_key(t["axis"]),
                     ",".join(sorted(model.norm_key(v) for v in t["values"])), t["qid"], model.norm_key(t["term"])])


def question_id(fp):
    return "EQ-" + model.sha256_text(fp)[:10]


# ---- 초안 -----------------------------------------------------------------------

_QID = re.compile(r"^Q-[A-Za-z0-9_-]{1,60}$")   # labelbot 질문 ID(Q-001, Q-GEN-…, Q-CTL-…)


def clean_scope(stage, target, axes=None):
    """rule 초안의 범위 정리. classify는 축 이름, label은 "축=값" 또는 질문 ID. 맞지 않으면 빈칸.
    axes를 주면 축 이름이 그 안에 있어야 한다(값은 보지 않는다)."""
    if not target or target in STAGES:
        return ""
    if stage == "label":
        if _QID.match(target):
            return target
        axis, eq, value = target.partition("=")
        axis, value = axis.strip(), value.strip()
        ok = bool(eq and axis and value) and (axes is None or axis in axes)
        return "%s=%s" % (axis, value) if ok else ""
    return "" if axes is not None and target not in axes else target


def check_draft(d, axes=None, require_scope=False):
    """초안 하나 → (정리한 초안, None) 또는 (None, 사유 코드).

    axes: 활성 축 이름 모음(주면 rule의 target이 그 안에 없을 때 빈칸으로 바꾼다). taxonomy 초안의 축·값이 지금
    taxonomy에 있는지는 보지 않는다(보드가 '먼저 할 일'로 알린다).
    require_scope: rule의 범위(classify=축 이름, label="축=값"·질문 ID)가 비면 RULE_SCOPE_MISSING으로 거부한다.
    반영(answers)만 켠다. 화면·LLM 초안은 비워 둔 채 두어 사람이 채운다.
    """
    if not isinstance(d, dict):
        return None, "DRAFT_FORMAT_INVALID"
    kind = d.get("type")
    if kind == "rule":
        text = clean_text(d.get("text"), RULE_TEXT_MAX)
        if text is None:
            return None, "DRAFT_TEXT_INVALID"
        stage = d.get("stage") if d.get("stage") in STAGES else "classify"
        target = soft_text(d.get("target"), NAME_MAX)
        if target is None:
            return None, "DRAFT_TARGET_INVALID"
        target = clean_scope(stage, target, axes)
        out = {"type": "rule", "stage": stage, "target": target, "text": text}
        pid = d.get("pattern_id")
        if isinstance(pid, str) and _PATTERN_ID.match(pid):
            out["pattern_id"] = pid
        # 패턴(FR) 문장 교체는 단계·대상을 패턴이 정하므로 범위를 요구하지 않는다
        if require_scope and not target and "pattern_id" not in out:
            return None, "RULE_SCOPE_MISSING"
        return out, None
    if kind == "example":
        eid = d.get("example_id")
        if not (isinstance(eid, str) and _EXAMPLE_ID.match(eid)):
            return None, "DRAFT_EXAMPLE_INVALID"
        return {"type": "example", "example_id": eid}, None
    if kind == "taxonomy":
        tk = d.get("kind")
        if tk not in TAX_KINDS:
            return None, "DRAFT_KIND_INVALID"
        out = {"type": "taxonomy", "kind": tk}
        for k in NAME_KEYS:
            v = soft_text(d.get(k), NAME_MAX)
            if v is None:
                return None, "DRAFT_NAME_INVALID"
            out[k] = v
        for k in LONG_KEYS:
            v = soft_text(d.get(k), LONG_MAX)
            if v is None:
                return None, "DRAFT_TEXT_INVALID"
            out[k] = v
        memo = soft_text(d.get("memo"), MEMO_MAX)
        if memo is None:
            return None, "DRAFT_TEXT_INVALID"
        out["memo"] = memo
        values = d.get("values") if isinstance(d.get("values"), list) else []
        out["values"] = [v for v in (soft_text(x, NAME_MAX) for x in values[:4]) if v]
        # 이 kind가 쓰지 않는 칸은 비운다(화면에 보이지 않는 문장이 따라 들어오지 않게)
        for k in NAME_KEYS + LONG_KEYS + ("memo",):
            if k not in TAX_FIELDS[tk]:
                out[k] = ""
        if "values" not in TAX_FIELDS[tk]:
            out["values"] = []
        for k in TAX_REQUIRED[tk]:
            if k == "values":
                if len(out["values"]) != 2:
                    return None, "DRAFT_REQUIRED_MISSING"
            elif not out[k]:
                return None, "DRAFT_REQUIRED_MISSING"
        return out, None
    return None, "DRAFT_TYPE_INVALID"


def normalize_draft(d, axes=None):
    return check_draft(d, axes)[0]


def proposal_id(draft):
    """taxonomy 초안 → 제안 ID. 대상과 문장이 같으면 같은 ID다(같은 제안을 두 번 쓰지 않는다)."""
    core = {k: draft.get(k) for k in ("kind",) + NAME_KEYS + LONG_KEYS + ("memo",)}
    core["values"] = sorted(draft.get("values") or [])
    return "QP-" + model.hash_obj(core)[:12]


# ---- 질문 묶음 -------------------------------------------------------------------

def empty_set(workspace="", set_id=None, now=None):
    return {"kind": QUESTIONS_KIND, "version": VERSION, "set_id": set_id or new_set_id(),
            "generated_at": now or model.now_iso(), "workspace": workspace, "model": "", "context_digest": "",
            "inputs": {}, "questions": []}


def valid_set(doc):
    return (isinstance(doc, dict) and doc.get("kind") == QUESTIONS_KIND and valid_set_id(doc.get("set_id"))
            and isinstance(doc.get("questions"), list)
            and all(isinstance(q, dict) and valid_question_id(q.get("question_id"))
                    and isinstance(q.get("fingerprint"), str) and q["fingerprint"] for q in doc["questions"]))


def load_set(qd):
    """지금 질문 묶음. 파일이 없으면 None. 있는데 깨졌으면 QModelError("QUESTIONS_INVALID")로 멈춘다
    (조용히 비우면 이월 질문이 사라진다)."""
    path = os.path.join(qd, QUESTIONS)
    if not os.path.isfile(path):
        return None
    try:
        doc = io.read_own_json(path)
    except (ValueError, UnicodeDecodeError, OSError):
        raise QModelError("QUESTIONS_INVALID")
    if not valid_set(doc):
        raise QModelError("QUESTIONS_INVALID")
    return doc


def save_set(qd, doc):
    """원자 교체. 내용이 같으면 쓰지 않는다. 반환: 썼으면 True."""
    os.makedirs(qd, exist_ok=True)
    return ledger.write_json(os.path.join(qd, QUESTIONS), doc)


def digest(doc):
    """질문 묶음의 내용 해시(시각 제외). 화면과 답 파일이 같은 묶음을 보고 있는지 확인하는 데 쓴다."""
    return model.hash_obj({"set_id": doc.get("set_id"), "questions": doc.get("questions")})[:16]


def question_map(doc):
    return {q["question_id"]: q for q in (doc or {}).get("questions") or []}


# ---- 답함·묻지 않음 지문 -----------------------------------------------------------

def empty_asked():
    return {"version": VERSION, "answered": {}, "dismissed": {}}


def load_asked(qd):
    """답함·묻지 않음 지문. 파일이 없으면 빈 문서. 있는데 깨졌으면 QModelError("ASKED_INVALID")로 멈춘다
    (조용히 비우면 답한 질문을 다시 묻게 된다).

    값은 {"question_id", "set_id", "at", "refs": [그때의 근거 ID(FR-·case_id)], "answers_sha": 그 답 파일의 해시}다.
    """
    path = os.path.join(qd, ASKED)
    if not os.path.isfile(path):
        return empty_asked()
    try:
        doc = io.read_own_json(path)
    except (ValueError, UnicodeDecodeError, OSError):
        raise QModelError("ASKED_INVALID")
    if not isinstance(doc, dict) or any(not isinstance(doc.get(k, {}), dict) for k in ("answered", "dismissed")):
        raise QModelError("ASKED_INVALID")
    out = empty_asked()
    for k in ("answered", "dismissed"):
        out[k] = {fp: v for fp, v in (doc.get(k) or {}).items() if isinstance(fp, str) and isinstance(v, dict)}
    return out


def save_asked(qd, doc):
    os.makedirs(qd, exist_ok=True)
    return ledger.write_json(os.path.join(qd, ASKED), doc)


def question_refs(q):
    """질문의 근거 ID(승인 대기 패턴 FR-와 교정 사례 case_id). asked.json에 함께 남긴다."""
    return sorted(set(q.get("patterns") or []) | set(q.get("evidence") or []))


def closed_by(asked, q):
    """이 질문의 지문을 닫았던 asked 값(답함·묻지 않음). 없으면 None."""
    fp = q.get("fingerprint")
    return (asked.get("answered") or {}).get(fp) or (asked.get("dismissed") or {}).get(fp)


def is_closed(asked, q, case_times=None):
    """이 질문을 다시 묻지 않는가. 지문이 답함·묻지 않음에 있으면 닫힌 것이다.

    다시 여는 것은 generate만 정한다: general이 아닌 질문에 **그때 없던 근거**가 붙었을 때다.
    - 그때 근거(refs)에 없던 승인 대기 패턴(FR-)이 붙었다(닫을 때의 패턴은 승인·종결돼 다시 대기에 오지 않는다).
    - case_times({case_id: 교정 반영 시각})를 주면, 그때 근거에 없고 그 질문을 만든 시각(seen_at. 없으면 닫은 시각 at)보다
      늦게 반영된 교정 사례가 붙었다. 질문을 만든 뒤 답하기 전에 들어온 교정은 엔지니어가 보지 못한 근거라 새것으로 친다.
      그때도 있던 사례를 이번에 새로 인용한 것만으로는 다시 열지 않는다.
    generate는 다시 연 질문에 "reopened": true를 적는다. 그 표시가 있으면 case_times 없이도 열린 것으로 본다
    (apply·status·이월이 같은 판정을 하게).
    """
    old = closed_by(asked, q)
    if old is None or q.get("reopened") is True:
        return False
    if (q.get("topic") or {}).get("type") == "general":
        return True
    seen = set(old.get("refs") or [])
    if set(q.get("patterns") or []) - seen:
        return False
    if case_times is not None:
        at = old.get("seen_at") or old.get("at") or ""
        for cid in q.get("evidence") or []:
            if cid not in seen and (case_times.get(cid) or "") > at:
                return False
    return True


def asked_entry(q, set_id, at, answers_sha=None, seen_at=None):
    """asked.json 값. answers_sha는 이 질문을 닫은 답 파일의 해시다(다시 열린 질문에 예전 답 파일이
    또 반영되지 않게 answers.apply가 비교한다). seen_at은 그 질문을 만든 시각이다(is_closed의 기준 시각)."""
    out = {"question_id": q.get("question_id"), "set_id": set_id, "at": at, "refs": question_refs(q)}
    if answers_sha:
        out["answers_sha"] = answers_sha
    if seen_at:
        out["seen_at"] = seen_at
    return out
