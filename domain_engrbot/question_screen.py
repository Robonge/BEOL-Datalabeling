"""질문 화면(engr_questions.html) 생성. 설계는 domain_engrbot/docs/plan-question-loop.md 5.3절·8절이다.

- 템플릿 screens/engr_questions.html의 `/*__DATA__*/null` 자리에 질문 묶음과 근거 풀이(JSON)를 넣는다(screen.embed).
- 근거 풀이: 질문의 evidence(case_id)를 장부 cases·evidence에서 찾아 봇 값 → 사람 값, 검수자가 남긴 인용·이유를 붙이고,
  patterns(FR-)는 교정 패턴 요약(kind·대상·전후 값·건수·상충), examples(EX-)는 그 레코드의 근거 카드에 붙인다.
- 슬라이드 미리보기는 원래 작업 폴더의 chunk_context → WsLoader.image_bytes로 읽어 data URL로 넣는다(레코드마다 한 번,
  전체 PREVIEWS_MAX장). 작업 폴더가 없거나 읽기에 실패하면 preview는 null이다(화면은 "미리보기 없음").
- 화면에는 근거 인용·질문 문장이 들어간다. 그래서 화면 파일은 질문 폴더(git 제외)에만 쓰고, 콘솔에는 건수만 낸다.
- 시각을 넣지 않아 같은 입력이면 같은 HTML이다. 화면은 표시·편집·저장만 하고 판정 로직은 넣지 않는다.
"""
import base64
import os
import sqlite3

from domain_engrbot import labeling_rules as lr, ledger, model, qmodel, screen
from domain_engrbot.adapters import labelbot_ws

TEMPLATE_PATH = os.path.join(screen.PKG_ROOT, "screens", "engr_questions.html")
SCREEN_KIND = "engr_questions_screen"
PREVIEWS_MAX = 40   # 화면 파일 크기 상한: 슬라이드 미리보기 장수
_READ_ERRORS = (model.BundleError, model.LoaderError, sqlite3.Error, OSError, ValueError)


class QuestionScreenError(Exception):
    def __init__(self, reason_code):
        Exception.__init__(self, reason_code)
        self.reason_code = reason_code


# ---- 작업 폴더 찾기 ---------------------------------------------------------------

def _plain_name(name):
    return isinstance(name, str) and name not in ("", ".", "..") and os.path.basename(name) == name \
        and "/" not in name and "\\" not in name


def _ws_root(name, d, roots):
    """작업 폴더 이름 → 경로(work.sqlite가 있는 곳) 또는 None. roots에 있으면 그것을 쓴다.

    없으면 장부 위치에서 짐작한다: <workspaces>/<이름>, 공용 장부(<폴더>/_domain_engrbot/ledger)의 <폴더>/<이름>,
    작업 폴더 장부(<작업 폴더>/qa/ledger)면 그 작업 폴더.
    """
    if roots and name in roots:
        cands = [roots[name]]
    elif not _plain_name(name):
        return None
    else:
        d = os.path.abspath(d)
        up2 = os.path.dirname(os.path.dirname(d))
        cands = [os.path.join(ledger.WORKSPACES_DIR, name), os.path.join(up2, name)]
        if os.path.basename(up2) == name:
            cands.append(up2)
    for p in cands:
        if p and os.path.isfile(os.path.join(p, "work.sqlite")):
            return os.path.abspath(p)
    return None


# ---- 근거 풀이 -------------------------------------------------------------------

def _case_view(case_id, case, ev):
    rid = case.get("record_id")
    row = ev.get(case_id) or {}
    items = [{"kind": ledger.evidence_kind(x, rid), "slide_no": x.get("slide_no"), "quote": x.get("quote") or ""}
             for x in row.get("evidence") or [] if isinstance(x, dict)]
    return {"case_id": case_id, "record_id": rid, "source_ws": case.get("source_ws"), "field": case.get("field"),
            "kind": case.get("kind"), "bot": case.get("bot_value"), "human": case.get("human_value"),
            "items": items, "reason": row.get("reason"),
            "slide_key": "%s|%s|%s" % (case.get("source_ws"), rid, case.get("text_hash") or ""),
            "examples": []}


def _pattern_view(pid, rules):
    r = rules.get(pid)
    if r is None:
        return {"rule_id": pid, "missing": True}
    return {"rule_id": pid, "kind": r["kind"], "target": r["target"], "from": r["from"], "to": r["to"],
            "count": r["count"], "conflict": bool(r["conflict"]), "reverse_count": r["reverse_count"]}


def _split_key(key):
    """slide_key "<작업 폴더>|<레코드>|<사례의 text_hash>" → (작업 폴더, 레코드, text_hash)."""
    ws, _, rest = key.partition("|")
    rid, _, th = rest.rpartition("|")
    return ws, rid, th


def _slides(keys, d, roots):
    """{slide_key: {"slide_no", "title", "preview"}}. 작업 폴더마다 chunk_context를 한 번 부른다.

    미리보기는 사례의 text_hash가 chunk의 지금 text_hash와 같을 때만 넣는다(검수 뒤 본문이 바뀐 슬라이드를
    그 교정의 근거로 보여 주지 않는다).
    """
    by_ws = {}
    for key in keys:
        ws, rid, _ = _split_key(key)
        by_ws.setdefault(ws, []).append(rid)
    ctx, loaders = {}, {}
    for ws in sorted(by_ws):
        root = _ws_root(ws, d, roots)
        if root is None:
            continue
        try:
            got = labelbot_ws.chunk_context(root, by_ws[ws])
        except _READ_ERRORS:
            continue
        loaders[ws] = labelbot_ws.WsLoader(root)
        for rid, c in got.items():
            ctx["%s|%s" % (ws, rid)] = c
    out, shown = {}, 0
    for key in keys:   # 질문 순서대로 미리보기를 넣는다(앞 질문의 근거가 먼저)
        ws, rid, th = _split_key(key)
        c = ctx.get("%s|%s" % (ws, rid))
        if c is None:
            out[key] = {"slide_no": None, "title": "", "preview": None}
            continue
        preview = None
        if c.get("preview_rel") and th and th == c.get("text_hash") and shown < PREVIEWS_MAX:
            try:
                b = loaders[ws].image_bytes({"rel_file": c["preview_rel"]})
            except _READ_ERRORS:
                b = None
            if b:
                preview = "data:image/jpeg;base64," + base64.b64encode(b).decode("ascii")
                shown += 1
        out[key] = {"slide_no": c.get("seq"), "title": c.get("title") or "", "preview": preview}
    return out


def _axes(workspace, d, roots):
    """초안 편집용 활성 축 이름과 값 이름. taxonomy를 못 읽으면 빈 목록."""
    root = _ws_root(workspace, d, roots)
    if root is None:
        return []
    try:
        snap = labelbot_ws.snapshot(labelbot_ws.load_taxonomy(root, labelbot_ws.read_config(root)))
    except _READ_ERRORS:
        return []
    return [{"name": a["name"], "values": [v["name"] for v in a["values"]]} for a in snap["axes"] if a["active"]]


def data(doc, d, roots=None):
    """화면에 넣을 데이터. 근거 인용·이유·슬라이드 미리보기가 들어간다(화면 파일만).

    doc: 질문 묶음(qmodel 4.1). d: 장부 폴더. roots: {source_ws 이름: 작업 폴더 경로}(없으면 장부 위치에서 짐작).
    """
    cases = {c["case_id"]: c for c in ledger.latest(ledger.read(d, ledger.CASES), "case_id")}
    ev = {r["case_id"]: r for r in ledger.read_evidence(d)}
    latest = lr._latest_cases(d)
    rules = lr.all_rules(latest, 1)
    ex_of = {}   # EX- ID → (작업 폴더, 레코드)
    for c in latest:
        ex_of.setdefault(lr.example_id(c["record_id"], c.get("text_hash")), (c["source_ws"], c["record_id"]))
    questions, keys = [], []
    for rank, q in enumerate(doc.get("questions") or [], 1):
        evid = [_case_view(cid, cases[cid], ev) for cid in q.get("evidence") or [] if cid in cases]
        by_rec = {}
        for v in evid:
            by_rec.setdefault((v["source_ws"], v["record_id"]), []).append(v)
            if v["slide_key"] not in keys:
                keys.append(v["slide_key"])
        examples = []
        for eid in q.get("examples") or []:
            ws, rid = ex_of.get(eid, (None, None))
            examples.append({"example_id": eid, "source_ws": ws, "record_id": rid})
            for v in by_rec.get((ws, rid), [])[:1]:
                v["examples"].append(eid)
        questions.append({
            "question_id": q["question_id"], "rank": rank, "goal": q.get("goal"), "topic": q.get("topic") or {},
            "text": q.get("text") or "", "why": q.get("why") or "", "carried": bool(q.get("carried")),
            "reopened": bool(q.get("reopened")),
            "impact": q.get("impact") or {}, "revisits": q.get("revisits") or [],
            "options": q.get("options") or [], "evidence": evid,
            "evidence_missing": sum(1 for cid in q.get("evidence") or [] if cid not in cases),
            "patterns": [_pattern_view(p, rules) for p in q.get("patterns") or []], "examples": examples})
    return {
        "kind": SCREEN_KIND, "set_id": doc.get("set_id"), "digest": qmodel.digest(doc),
        "workspace": doc.get("workspace") or "", "answers_kind": qmodel.ANSWERS_KIND,
        "answers_name": qmodel.answers_name(doc.get("set_id")), "questions": questions,
        "slides": _slides(keys, d, roots), "axes": _axes(doc.get("workspace") or "", d, roots),
        "tax_required": {k: list(v) for k, v in qmodel.TAX_REQUIRED.items()},
        "tax_fields": {k: list(v) for k, v in qmodel.TAX_FIELDS.items()},
        "limits": {"rule_text": qmodel.RULE_TEXT_MAX, "long": qmodel.LONG_MAX, "memo": qmodel.MEMO_MAX,
                   "name": qmodel.NAME_MAX, "free": qmodel.FREE_MAX, "drafts": qmodel.MAX_DRAFTS},
    }


def render(obj):
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        tpl = f.read()
    if screen.DATA_MARK not in tpl:
        raise QuestionScreenError("TEMPLATE_MARK_MISSING")
    return tpl.replace(screen.DATA_MARK, screen.embed(obj), 1)


def build(qd, d, policy=None, roots=None):
    """질문 폴더에 engr_questions.html을 쓴다. 반환: 질문 수. 질문 묶음이 없으면 QUESTIONS_NOT_FOUND.

    policy는 호출 계약(questions·answers가 같은 꼴로 부른다)을 맞추려고 받는다. 화면 내용은 정책에 따라 바뀌지 않는다.
    """
    doc = qmodel.load_set(qd)
    if doc is None:
        raise QuestionScreenError("QUESTIONS_NOT_FOUND")
    obj = data(doc, d, roots)
    os.makedirs(qd, exist_ok=True)
    ledger.replace_text(os.path.join(qd, qmodel.SCREEN), render(obj))
    return len(obj["questions"])
