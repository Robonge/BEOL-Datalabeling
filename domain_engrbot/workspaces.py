"""작업 폴더 목록(workspaces 명령): 코드 폴더 workspaces/ 아래 labelbot 작업 폴더와 Domain-Engr-bot 질문 상태.

skill이 사람에게 어느 작업 폴더의 검수 결과로 도메인 질문을 만들지, 이미 질문에 쓴 폴더를 다시 할지 건너뛸지 묻는 데 쓴다.
질문 루프 상태(question_state, plan-question-loop.md 8.8절)는 작업 DB의 교정 유무와 장부 sources의 sha를 함께 본다.
- no_review : 작업 DB에 사람 교정이 없다
- new       : 교정이 있는데 장부에 그 작업 폴더가 없거나, 장부 sha가 질문 묶음(questions.json inputs)과 다르다
- asked     : 장부 sha가 질문 묶음 inputs와 같다(검수 결과가 질문에 쓰였다)
review_runs는 교정이 있는 라벨러 실행 수다.
옛 QA 상태(state)는 옛 QA 흐름용으로 남김(스킬은 쓰지 않는다). 가장 최근 라벨러 실행 기준이다.
- new     : 그 라벨러 실행을 검수한 실행(qa/runs)이 없다
- qa_done : 검수 실행은 있으나 그 실행의 결정 파일이 qa/inbox에 없다(사람 검토 전)
- applied : 결정 파일이 qa/inbox에 있다(feedback까지 했으면 feedback=true)
work.sqlite는 읽기 전용으로만 연다. 출력에는 폴더 이름, 실행 ID, 건수, 상태만 담는다.
"""
import json
import os
import re
import sqlite3

from domain_engrbot import io, ledger, model, paths, qmodel
from domain_engrbot import policy as policy_mod
from domain_engrbot.adapters import labelbot_ws

ROOT = os.path.join(io.CODE_ROOT, "workspaces")
_DECISION = re.compile(r"^qa_decisions_(QA-[0-9A-Za-z-]+?)(_[0-9-]+)?\.json$")


def _labeler_run(ws_root):
    try:
        con = labelbot_ws.connect_ro(ws_root)
    except model.BundleError as e:
        return None, e.reason_code
    try:
        return labelbot_ws.latest_labeler_run(con), None
    except Exception:  # 오래된·깨진 DB도 목록에는 사유 코드로 남긴다
        return None, "ADAPTER_DB_UNREADABLE"
    finally:
        con.close()


def _qa_runs(ws_root):
    runs_dir = os.path.join(ws_root, "qa", "runs")
    inbox = os.path.join(ws_root, "qa", "inbox")
    decided = set()
    if os.path.isdir(inbox):
        for fn in os.listdir(inbox):
            m = _DECISION.match(fn)
            if m:
                decided.add(m.group(1))
    out = []
    if not os.path.isdir(runs_dir):
        return out
    for qa in sorted(d for d in os.listdir(runs_dir) if d.startswith("QA-")):
        man = os.path.join(runs_dir, qa, "manifest.json")
        try:
            with open(man, encoding="utf-8") as f:
                m = json.load(f)
        except (OSError, ValueError):
            continue  # 끝나지 않은 실행
        c = m.get("counts") or {}
        out.append({"qa_run_id": qa, "labeler_run_id": m.get("labeler_run_id"),
                    "counts": {k: c.get(k, 0) for k in ("records", "PASS", "AUTO_FIX", "REVIEW", "REJECT")},
                    "decisions": qa in decided,
                    "feedback": os.path.isfile(os.path.join(runs_dir, qa, "feedback", "feedback.json"))})
    return out


def _review_runs(ws_root):
    try:
        return labelbot_ws.correction_runs(ws_root), None
    except model.BundleError as e:
        return None, e.reason_code
    except sqlite3.Error:
        return None, "ADAPTER_DB_UNREADABLE"


class _QuestionIndex(object):
    """장부 폴더별 sources·질문 묶음을 한 번만 읽는다. 깨진 파일은 사유 코드로 남긴다."""

    def __init__(self):
        self.pol = policy_mod.default_policy()
        self.cache = {}

    def get(self, ws_root):
        try:
            d = ledger.ledger_dir(ws_root, self.pol)
        except ledger.LedgerError as e:
            return None, None, e.reason_code
        if d not in self.cache:
            try:
                shas = {s["source_ws"]: s.get("corrections_sha") for s in ledger.read(d, ledger.SOURCES)}
                doc = qmodel.load_set(qmodel.qdir(d))
                self.cache[d] = (shas, (doc or {}).get("inputs") or {}, None)
            except ledger.LedgerError as e:
                self.cache[d] = (None, None, e.reason_code)
            except qmodel.QModelError as e:
                self.cache[d] = (None, None, e.reason_code)
        return self.cache[d]


def question_state(name, runs, shas, inputs):
    if not runs:
        return "no_review"
    sha = (shas or {}).get(name)
    if sha is None or (inputs or {}).get(name) != sha:
        return "new"
    return "asked"


def questions_summary(root=ROOT):
    """workspaces 출력의 최상위 questions 칸: 공용 질문 폴더(<root>/_domain_engrbot/questions)의 set_id·열린 질문 수·답한 누계."""
    qd = qmodel.qdir(paths.data_path(root, "ledger"))
    out = {"set_id": None, "open": 0, "answered_total": 0}
    if paths.legacy_exists(root):
        return dict(out, reason="LEGACY_DATA_DIR")
    try:
        doc = qmodel.load_set(qd)
        asked = qmodel.load_asked(qd)
    except qmodel.QModelError as e:
        return dict(out, reason=e.reason_code)
    qs = [q for q in (doc or {}).get("questions") or [] if not qmodel.is_closed(asked, q)]
    return {"set_id": (doc or {}).get("set_id"), "open": len(qs), "answered_total": len(asked["answered"])}


def scan(root=ROOT):
    """반환: 작업 폴더 dict 목록(work.sqlite가 최근에 바뀐 순). _·.으로 시작하는 폴더는 작업 폴더가 아니다."""
    rows = []
    if not os.path.isdir(root):
        return rows
    index = _QuestionIndex()
    for name in os.listdir(root):
        ws = os.path.join(root, name)
        db = os.path.join(ws, "work.sqlite")
        if name.startswith(("_", ".")) or not os.path.isfile(db):
            continue
        lrun, reason = _labeler_run(ws)
        qa_all = _qa_runs(ws)
        mine = [q for q in qa_all if lrun and q["labeler_run_id"] == lrun]
        last = mine[-1] if mine else None
        state = "new" if last is None else ("applied" if last["decisions"] else "qa_done")
        runs, q_reason = _review_runs(ws)
        qstate = "no_review" if runs == [] else None
        if q_reason is None and runs:
            shas, inputs, q_reason = index.get(ws)
            qstate = None if q_reason else question_state(name, runs, shas, inputs)
        rows.append({"workspace": name, "labeler_run_id": lrun, "reason": reason, "state": state,
                     "latest_qa": last, "qa_runs_for_labeler_run": len(mine), "qa_runs_total": len(qa_all),
                     "question_state": qstate, "question_reason": q_reason,
                     "review_runs": len(runs) if runs is not None else 0, "_mtime": os.path.getmtime(db)})
    rows.sort(key=lambda r: -r["_mtime"])
    for r in rows:
        del r["_mtime"]
    return rows
