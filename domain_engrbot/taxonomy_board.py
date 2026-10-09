"""taxonomy 수정 보드(taxonomy-board 명령). 흩어진 taxonomy.json 수정 제안을 한 화면에 모으고, 사람이 고른 것만 반영한다.
LLM 0회.

출처(작업 폴더 <WS> 기준):
- S1 Domain-Engr-bot 승인 피드백: qa/runs/<QA>/feedback/feedback.json의 proposals[](모든 실행)
- S2 Domain-Engr-bot 제안: 가장 최근 실행의 proposals.jsonl. 기각 목록은 qa/feedback_rejected.jsonl
- S3 Domain-Engr-bot L6 지표: 가장 최근 실행의 taxonomy_candidates.jsonl(축 지표, 용어 후보)
- S4 labelbot 후보: reports/candidates.jsonl
- S5 재검토 요청: reports/taxonomy_revisit.jsonl(누적), taxonomy.json 옆 taxonomy_revisit_requests/*.json(재검토 파일)
- S6 교정 장부: 장부 폴더 synonyms.jsonl
- S7 엔지니어 답변: 질문 폴더(장부 폴더의 형제 questions) taxonomy_proposals.jsonl. 사람이 질문 화면에서 확정한 초안이다.
  같은 항목에 S7이 여럿이면 at이 가장 늦은 것의 문장(정의·포함 예·제외 예·질문 문장·동의어 메모)을 행 초안에 채운다.

- 제안을 시트 위치 키 하나로 묶고, 대상 시트 열 순서의 행 초안을 만든다. 봇은 문장을 지어내지 않는다
  (칸에 채우는 문장은 사람이 확정한 S7 문장뿐이다). 칸은 원문 그대로다(줄바꿈 유지, 수식 표시 없음).
- 지금 taxonomy.json(bytes)의 행 색인으로 상태(open·done·rejected·blocked·unknown)를 정한다.
- 반영: 사람이 카드에서 편집 칸을 고치고 반영함·기각을 표시한 뒤 '최종 완료'를 누르면 미리보기(/board/preview)를
  보여 주고, 확인하면(/board/finalize) 봇이 taxonomy.json을 고친다(plan_changes·apply_marks). 쓰기는
  labelbot.taxonomy.save_doc(버전 확인·검증·taxonomy_history.jsonl 이력·원자적 교체)으로만 한다.
- 출력은 out_dir의 taxonomy_board.html·.json, decisions.json(·cleared.json)뿐이다. 작업 폴더에는 아무것도 만들지 않는다.
- 항목마다 제안 이유(evidence.whys)와 근거 슬라이드(evidence.slides: 예시 레코드·재검토 chunk를 작업 폴더 work.sqlite에서
  읽기 전용으로 찾은 파일명·슬라이드 번호·제목·미리보기)를 붙인다(resolve_slides).
- 화면·json에는 용어·메모(본문 표현)·파일명·슬라이드 제목·미리보기가 들어간다. 콘솔에는 건수·코드·화면 상대 경로만 낸다.
"""
import base64
import collections
import datetime
import hashlib
import json
import os
import sqlite3
import webbrowser
from pathlib import Path

from domain_engrbot import feedback, io, ledger, model, paths, qmodel, screen, trace
from domain_engrbot import policy as policy_mod
from domain_engrbot import workspaces as ws_mod
from domain_engrbot.adapters import labelbot_ws as lb

OUT_DIR = paths.data_path(os.path.join(io.CODE_ROOT, "workspaces"), "taxonomy_board")
DEFAULT_TAXONOMY = os.path.join(io.CODE_ROOT, "taxonomy", "taxonomy.json")
REQUESTS_DIRNAME = "taxonomy_revisit_requests"  # labelbot.revisit.REQUESTS_DIRNAME와 같다
TEMPLATE_PATH = os.path.join(screen.PKG_ROOT, "screens", "taxonomy_board.html")
SCREEN, DOC, CLEARED = "taxonomy_board.html", "taxonomy_board.json", "cleared.json"
DECISIONS = "decisions.json"   # 사람이 보드에서 '최종 완료'로 확정한 처리 {항목 ID: {"decision", "at", "prints"}}
MARKS_MAX = 5000
CELL_MAX = 20000         # 사람이 고친 칸 하나의 글자 수 상한
EDIT_KINDS = ("value_def", "axis_def", "overlap", "q_edit")   # 문장을 고치는 항목: 쓸 문장이 있어야 반영한다
REJECT_REASON = "보드에서 기각"
DECISION_KINDS = ("applied", "rejected")
MARK_KINDS = DECISION_KINDS + ("reopen",)   # reopen: 기각 해제(rejected 목록 행과 기각 확정을 지운다)
DECISIONS_KIND = "taxonomy_board_decisions"

HEADERS = lb.taxonomy_headers()
TAX_COLS, SYN_COLS, Q_COLS, REJ_COLS = (HEADERS[k] for k in ("taxonomy", "synonyms", "questions", "rejected"))
H, I, J, K = 7, 8, 9, 10  # taxonomy 시트 정의·판정 규칙, 포함 예, 제외 예, 사용 여부
# 보드 화면 이름(JSON 키는 그대로). 축 속성 4열(다중값·계층·중복 알림 제외·종류)은 보드에서 숨기고 편집기에서만 고친다.
# 새 축은 보드에서 기본값(다중값 Y, 계층 Y, 중복 알림 제외 N, 종류 분류)으로만 만든다.
COLUMN_LABELS = {"taxonomy": {"축": "분류 기준", "값": "라벨", "상위값": "상위 라벨", "정의·판정 규칙": "라벨 설명"}}
COLUMN_HELP = {"taxonomy": {"축": "라벨을 넣는 서랍 이름",
                            "값": "자료에 실제로 붙는 말",
                            "상위값": "이 라벨이 속한 더 큰 라벨. 예: I1 → M1",
                            "정의·판정 규칙": "봇이 이 라벨을 고를 때 읽는 설명",
                            "포함 예": "자료에 이 말이 나오면 이 라벨이다",
                            "제외 예": "비슷해 보여도 이 라벨이 아니다(→ 갈 곳 적기)",
                            "사용 여부": "N이면 봇이 이 라벨을 더는 고르지 않는다(빈칸은 켜짐)"}}
AXIS_ATTRS = (3, 4, 5, 6)   # 다중값, 계층, 중복 알림 제외, 종류
HIDDEN_COLUMNS = {"taxonomy": list(AXIS_ATTRS)}
NEW_AXIS_DEFAULTS = {3: "Y", 4: "Y", 5: "N", 6: "분류"}
STATUSES = ("open", "done", "rejected", "blocked", "unknown")
GROUPS = ("taxonomy", "synonyms", "questions", "term", "outside")
SOURCE_CODES = ("S1", "S2", "S3", "S4", "S5", "S6", "S7")
SOURCE_LABELS = {"S1": "Domain-Engr-bot 승인", "S2": "Domain-Engr-bot 제안", "S3": "Domain-Engr-bot L6", "S4": "labelbot 후보",
                 "S4R": "labelbot 검수 등록", "S5": "재검토 요청", "S5F": "재검토 파일", "S6": "교정 장부",
                 "S7": "엔지니어 답변"}
OUTSIDE_KINDS = ("QUOTE_RULE", "FORMAT_RULE", "QA_POLICY")
HUMAN_SOURCES = ("S4R", "S5", "S5F", "S6", "S7")  # 사람이 올린 출처(검수 등록·재검토 요청·교정 장부·엔지니어 답변)
S7_LABEL = "엔지니어 답변 문장을 채운 행입니다"
OTHER_WHERE = "메모를 보고 사람이 정합니다(taxonomy 시트, 질문 문장, 라벨러 프롬프트 중)"
HIDE_HINT = "기각하면 결정만 남깁니다(원래 문장이 없어 rejected 목록에 행을 더하지 않습니다)"
REVISIT_FILE_NOTE = "재검토 파일은 apply 때의 스냅숏이라 화면에서 지운 요청도 남습니다."
# 제안이 올라온 이유(화면 표시용). 재검토 사유는 labelbot.revisit.REASON_LABELS와 같은 문구다.
PROPOSAL_WHY = {"TERM": "용어 후보", "UNUSED_VALUE": "미사용 값", "AXIS_DEFINITION": "축 정의 점검",
                "QUESTION_WORDING": "질문 문장 점검", "QUOTE_RULE": "인용 규칙", "FORMAT_RULE": "형식 규칙",
                "QA_POLICY": "검수 정책"}
REVISIT_WHY = {"NO_FIT_VALUE": "맞는 값이 없음", "AMBIGUOUS_DEF": "정의가 모호함", "VALUE_OVERLAP": "값 두 개가 겹침",
               "NEW_AXIS": "새 축이 필요함", "NEED_QUESTION": "필요한 질문이 없음", "OTHER": "기타"}
REFS_PER_ENTRY = 8      # 제안 하나에서 가져오는 근거 chunk 수
SLIDES_PER_ITEM = 12    # 항목마다 화면에 보이는 근거 슬라이드 수(나머지는 건수만)
PREVIEWS_MAX = 300      # 화면 파일 크기 상한: 미리보기 그림 장수(슬라이드마다 한 번만 넣는다)
PREVIEW_BYTES_MAX = 40 * 1024 * 1024  # 미리보기 그림 bytes 합 상한
_REF_READ_ERRORS = (model.BundleError, model.LoaderError, OSError, ValueError, sqlite3.Error)


# ---- 작은 도구 -------------------------------------------------------------------

def _s(v):
    return v.strip() if isinstance(v, str) else ""


def _nk(v):
    return lb.norm_key(_s(v))


def _low(v):
    """rejected·동의어 비교(labelbot과 같다): NFKC, trim, 소문자."""
    return lb.nfkc(_s(v)).strip().lower()


def _cell(v):
    """칸 값: 원문 그대로의 문자열(줄바꿈 유지, 수식 표시 없음). None은 빈칸."""
    return v if isinstance(v, str) else ("" if v is None else str(v))


def _ws(v):
    return " ".join(_s(v).split())


def _id(key):
    return model.sha256_text(key)[:16]


def _row_hash(rows):
    return model.hash_obj(rows)[:16]


class BoardRefused(Exception):
    """반영 요청 거절. code는 사유 코드, status는 HTTP 상태, issues는 검증 오류 [{"sheet", "row", "code"}],
    detail은 하위 사유 코드(읽기 실패 등, 없으면 None)."""

    def __init__(self, code, status=400, issues=None, detail=None):
        Exception.__init__(self, code)
        self.code, self.status, self.issues, self.detail = code, status, list(issues or []), detail


def _off(cells):
    return cells[K].strip().upper() == "N"


def _metric_text(m):
    if not isinstance(m, dict) or m.get("name") is None:
        return None
    parts = ["%s %s" % (m.get("name"), m.get("value"))]
    if m.get("n") is not None:
        parts.append("n=%s" % m["n"])
    if m.get("count"):
        parts.append("%s건" % m["count"])
    if m.get("threshold") is not None:
        parts.append("기준 %s" % m["threshold"])
    return ", ".join(parts)


class _Bad(object):
    """깨진 출처 행 수(코드만 센다)."""

    def __init__(self):
        self.n = 0


def _json_file(path, bad):
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        bad.n += 1
        return None


def _jsonl_file(path, bad):
    if not os.path.isfile(path):
        return []
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except (OSError, UnicodeDecodeError):
        bad.n += 1
        return []
    for line in lines:
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except ValueError:
            bad.n += 1
            continue
        if isinstance(r, dict):
            out.append(r)
        else:
            bad.n += 1
    return out


# ---- 수집 ----------------------------------------------------------------------

def _latest_run(ws_root, name):
    """qa/runs 아래 manifest.json과 name 파일이 있는 실행 중 이름순 마지막."""
    d = os.path.join(ws_root, "qa", "runs")
    if not os.path.isdir(d):
        return None
    runs = [r for r in sorted(os.listdir(d)) if os.path.isfile(os.path.join(d, r, "manifest.json"))
            and os.path.isfile(os.path.join(d, r, name))]
    return runs[-1] if runs else None


def _entry(src, ws, run, kind, **kw):
    e = {"src": src, "ws": ws, "run": run or "", "kind": kind, "pid": None, "n": 1, "metric": None, "memo": None,
         "examples": 0, "why": None, "refs": []}
    e.update(kw)
    return e


def _refs(v):
    """근거 chunk ID 목록(예시 레코드 = labelbot chunk_id "<파일ID 16자>:<part_name>"). 문자열만, 앞에서 REFS_PER_ENTRY개."""
    out = []
    for x in v if isinstance(v, list) else []:
        if isinstance(x, str) and ":" in x and x.strip() not in out:
            out.append(x.strip())
    return out[:REFS_PER_ENTRY]


def _from_proposal(p, src, ws, run):
    """Domain-Engr-bot 제안(proposals.jsonl 행 또는 feedback.json 승인 항목) → 원시 제안 하나 또는 None."""
    if not isinstance(p, dict):
        return None
    kind, subj = p.get("kind"), p.get("subject") if isinstance(p.get("subject"), dict) else {}
    base = {"pid": p.get("proposal_id"), "metric": _metric_text(p.get("metric")),
            "examples": len(p.get("examples") or []), "refs": _refs(p.get("examples")),
            "why": PROPOSAL_WHY.get(kind) or (kind if isinstance(kind, str) else None)}
    if kind == "TERM":
        cells = p.get("paste_row").split("\t") if isinstance(p.get("paste_row"), str) else []
        cells += [""] * (3 - len(cells))
        if p.get("as") == "value" and _s(cells[0]) and _s(cells[1]):
            return _entry(src, ws, run, "value_add", axis=cells[0], value=cells[1], parent=cells[2], **base)
        if p.get("as") == "synonym" and _s(cells[0]) and _s(cells[1]):
            return _entry(src, ws, run, "synonym", alias=cells[0], canonical=cells[1], memo=cells[2] or None, **base)
        return _entry(src, ws, run, "term", term=subj.get("term"), **base) if _s(subj.get("term")) else None
    if kind == "UNUSED_VALUE" and _s(subj.get("axis")) and _s(subj.get("value")):
        return _entry(src, ws, run, "value_off", axis=subj["axis"], value=subj["value"], **base)
    if kind == "AXIS_DEFINITION" and _s(subj.get("axis")):
        return _entry(src, ws, run, "axis_def", axis=subj["axis"], **base)
    if kind == "QUESTION_WORDING" and _s(subj.get("qid")):
        return _entry(src, ws, run, "q_edit", qid=subj["qid"], **base)
    if kind in OUTSIDE_KINDS:
        return _entry(src, ws, run, "outside", okind=kind, target=_s(p.get("target")), **base)
    return None


def _from_revisit(r, src, ws):
    """재검토 요청 행 → 원시 제안 하나 또는 None."""
    target, key, reason = r.get("target"), _s(r.get("key")), r.get("reason")
    prop = r.get("proposed") if isinstance(r.get("proposed"), dict) else {}
    rel = [_s(v) for v in r.get("related_values") or [] if _s(v)]
    why = REVISIT_WHY.get(reason) or (reason if isinstance(reason, str) else None)
    bot = r.get("bot_value")
    if why and isinstance(bot, (str, list)) and bot:
        why += " (봇 값: %s)" % (", ".join(_s(b) for b in bot if _s(b)) if isinstance(bot, list) else _s(bot))
    kw = {"memo": _s(r.get("memo")) or None, "why": why, "refs": _refs([r.get("chunk_id")])}
    run = r.get("review_run_id")
    if target == "axis" and key:
        if reason == "NO_FIT_VALUE" and _s(prop.get("value")):
            return _entry(src, ws, run, "value_add", axis=key, value=prop["value"], parent=_s(prop.get("parent")), **kw)
        if reason == "AMBIGUOUS_DEF":
            if len(rel) == 1:
                return _entry(src, ws, run, "value_def", axis=key, value=rel[0], **kw)
            return _entry(src, ws, run, "axis_def", axis=key, **kw)
        if reason == "VALUE_OVERLAP" and len(rel) == 2:
            return _entry(src, ws, run, "overlap", axis=key, values=rel, **kw)
    if target == "new_axis" and reason == "NEW_AXIS" and _s(prop.get("value")):
        return _entry(src, ws, run, "new_axis", name=prop["value"], **kw)
    if target == "question" and reason == "NEED_QUESTION":
        return _entry(src, ws, run, "q_new", text="", **kw)
    if target == "question" and reason == "AMBIGUOUS_DEF" and key:
        return _entry(src, ws, run, "q_edit", qid=key, **kw)
    if reason == "OTHER":
        return _entry(src, ws, run, "outside", okind="OTHER", target=("%s:%s" % (target, key)) if key else _s(target),
                      **kw)
    return None


def _revisit_key(r):
    return (r.get("review_run_id"), r.get("chunk_id"), r.get("target"), r.get("key"), r.get("reason"))


def _from_answer(r):
    """taxonomy_proposals.jsonl 행(엔지니어 답변) → 원시 제안 하나 또는 None(kind별 필수 칸이 없으면 깨진 행).
    사람이 확정한 문장은 s7에 따로 들고 merge가 묶음마다 가장 늦은 것을 고른다."""
    kind = r.get("kind")
    if kind not in qmodel.TAX_REQUIRED:
        return None
    values = [_s(v) for v in r.get("values") or [] if _s(v)] if isinstance(r.get("values"), list) else []
    for k in qmodel.TAX_REQUIRED[kind]:
        if (len(values) != 2) if k == "values" else not _s(r.get(k)):
            return None
    fields = {"value_add": ("axis", "value", "parent"), "value_def": ("axis", "value"), "axis_def": ("axis",),
              "overlap": ("axis",), "value_off": ("axis", "value"), "new_axis": ("name",),
              "synonym": ("alias", "canonical"), "q_edit": ("qid",), "q_new": ("text",)}[kind]
    kw = {k: _s(r.get(k)) for k in fields}
    if kind == "overlap":
        kw["values"] = values
    # 종류가 쓰지 않는 칸은 버린다(손으로 고친 행이나 예전 형식 행에서 숨은 문장이 들어오지 않게)
    allowed = qmodel.TAX_FIELDS[kind]
    s7 = {k: _ws(r.get(k)) if k in allowed else ""
          for k in ("definition", "include", "exclude", "text", "memo", "parent")}
    s7["at"] = r.get("at") if isinstance(r.get("at"), str) else ""
    return _entry("S7", "", r.get("set_id") if isinstance(r.get("set_id"), str) else "", kind,
                  memo=s7["memo"] or None, s7=s7, **kw)


def collect(ws_roots, ledger_dir, requests_dir, questions_dir=None):
    """반환: (원시 제안 목록, 축 L6 지표 {축: [지표]}, Domain-Engr-bot 기각 ID {작업 폴더: set}, 깨진 행 수).
    questions_dir가 있으면 그 폴더의 taxonomy_proposals.jsonl(S7 엔지니어 답변)도 읽는다."""
    raw, metrics, rejected, bad = [], {}, {}, _Bad()
    seen_revisit = set()

    def add(e):
        if e is not None:
            raw.append(e)

    for root in ws_roots:
        ws = os.path.basename(os.path.normpath(root))
        runs_dir = os.path.join(root, "qa", "runs")
        rejected[ws] = {r.get("proposal_id") for r in _jsonl_file(os.path.join(root, "qa", "feedback_rejected.jsonl"),
                                                                    bad) if r.get("proposal_id")}
        # S1: 모든 실행의 승인 피드백
        if os.path.isdir(runs_dir):
            for qa in sorted(os.listdir(runs_dir)):
                fb = _json_file(os.path.join(runs_dir, qa, "feedback", "feedback.json"), bad)
                for p in (fb.get("proposals") if isinstance(fb, dict) else None) or []:
                    add(_from_proposal(p, "S1", ws, qa))
        # S2: 가장 최근 실행의 제안
        qa = _latest_run(root, "proposals.jsonl")
        if qa:
            for p in _jsonl_file(os.path.join(runs_dir, qa, "proposals.jsonl"), bad):
                add(_from_proposal(p, "S2", ws, qa))
        # S3: 가장 최근 실행의 L6 지표
        qa = _latest_run(root, "taxonomy_candidates.jsonl")
        if qa:
            for r in _jsonl_file(os.path.join(runs_dir, qa, "taxonomy_candidates.jsonl"), bad):
                if r.get("kind") == "axis" and _s(r.get("axis")):
                    metrics.setdefault(_s(r["axis"]), []).append(
                        {"ws": ws, "run": qa, "coverage": r.get("coverage"), "unknown_rate": r.get("unknown_rate"),
                         "unused": [_s(v) for v in r.get("unused") or [] if _s(v)]})
                    raw.append(_entry("S3", ws, qa, "axis_metric"))
                elif r.get("kind") == "term" and _s(r.get("term")):
                    m = "lift %s, df(unknown) %s, df(전체) %s" % (r.get("lift"), r.get("df_u"), r.get("df_all"))
                    add(_entry("S3", ws, qa, "term", term=r["term"], metric=m, examples=len(r.get("examples") or []),
                               refs=_refs(r.get("examples")), why="unknown 축 chunk에 몰린 용어"))
        # S4: labelbot 후보
        for r in _jsonl_file(os.path.join(root, "reports", "candidates.jsonl"), bad):
            a, sep, b = _s(r.get("content")).partition("|")
            src = "S4R" if r.get("source") == "review" else "S4"
            n = r.get("freq") if isinstance(r.get("freq"), int) and r.get("freq") > 0 else 1
            ev = _s(r.get("evidence"))
            kw = {"n": n, "examples": len(r.get("examples") or []), "refs": _refs(r.get("examples")),
                  "why": ("근거 문구: " + ev) if ev else None}
            if r.get("kind") == "new_value" and sep and _s(a) and _s(b):
                add(_entry(src, ws, r.get("run_id"), "value_add", axis=a, value=b, parent=_s(r.get("parent")), **kw))
            elif r.get("kind") == "synonym" and sep and _s(a) and _s(b):
                add(_entry(src, ws, r.get("run_id"), "synonym", alias=a, canonical=b,
                           memo="검수 등록" if src == "S4R" else "후보", **kw))
            elif r.get("kind") == "question" and _s(r.get("content")):
                add(_entry(src, ws, r.get("run_id"), "q_new", text=_s(r["content"]), **kw))
        # S5: 누적 재검토 요청
        for r in _jsonl_file(os.path.join(root, "reports", "taxonomy_revisit.jsonl"), bad):
            k = _revisit_key(r)
            if k not in seen_revisit:
                seen_revisit.add(k)
                add(_from_revisit(r, "S5", ws))
    # S5: 실행별 재검토 파일(작업 폴더 누적과 겹치는 요청은 뺀다)
    if requests_dir and os.path.isdir(requests_dir):
        for fn in sorted(os.listdir(requests_dir)):
            if not fn.lower().endswith(".json"):
                continue
            doc = _json_file(os.path.join(requests_dir, fn), bad)
            for r in (doc.get("requests") or []) if isinstance(doc, dict) else []:
                if not isinstance(r, dict):
                    bad.n += 1
                    continue
                k = _revisit_key(r)
                if k not in seen_revisit:
                    seen_revisit.add(k)
                    add(_from_revisit(r, "S5F", ""))
    # S6: 교정 장부 동의어
    if ledger_dir:
        for r in _jsonl_file(os.path.join(ledger_dir, "synonyms.jsonl"), bad):
            if _s(r.get("alias")) and _s(r.get("canonical")):
                srcs = r.get("sources") if isinstance(r.get("sources"), list) else []
                add(_entry("S6", "", "", "synonym", alias=r["alias"], canonical=r["canonical"], memo="검수 등록",
                           n=max(1, len(srcs))))
    # S7: 엔지니어 답변(질문 화면에서 사람이 확정한 taxonomy 초안)
    if questions_dir:
        q_refs = None
        for r in _jsonl_file(os.path.join(questions_dir, qmodel.PROPOSALS), bad):
            e = _from_answer(r)
            if e is None:
                bad.n += 1
                continue
            if q_refs is None:
                q_refs = _question_slides(questions_dir, ledger_dir)
            refs = q_refs.get(r.get("question_id")) or []
            if refs:
                e["refs"] = refs[:REFS_PER_ENTRY]
                e["why"] = "검수 교정 사례(근거 슬라이드 %d장)를 보고 엔지니어가 답함" % len(refs)
            raw.append(e)
    return raw, metrics, rejected, bad.n


def _question_slides(questions_dir, ledger_dir):
    """엔지니어 답변(S7)의 근거 슬라이드. 질문 ID → [(작업 폴더, chunk_id)].

    asked.json에 남은 질문의 근거 ID(교정 사례 case_id)를 장부 cases에서 찾아 record_id(= chunk_id)와 source_ws로 바꾼다.
    승인 대기 패턴(FR-)은 슬라이드가 아니라서 뺀다. 파일이 없거나 깨졌으면 빈 dict(근거 슬라이드 없음)."""
    if not ledger_dir:
        return {}
    try:
        asked = qmodel.load_asked(questions_dir)
        cases = ledger.read(ledger_dir, ledger.CASES) if os.path.isfile(os.path.join(ledger_dir, ledger.CASES)) else []
    except (qmodel.QModelError, ledger.LedgerError, OSError):
        return {}
    where = {}
    for c in cases:
        if isinstance(c.get("record_id"), str) and c.get("record_id"):
            where[c.get("case_id")] = (_s(c.get("source_ws")), c["record_id"])
    out = {}
    for v in list((asked.get("answered") or {}).values()) + list((asked.get("dismissed") or {}).values()):
        qid = v.get("question_id")
        for ref in v.get("refs") or []:
            hit = where.get(ref)
            if qid and hit and hit not in out.setdefault(qid, []):
                out[qid].append(hit)
    return out


# ---- taxonomy.json 행 색인 -------------------------------------------------------

def _code(e):
    return "%s %s" % (e.reason_code, e.detail) if e.detail else e.reason_code


def read_bytes(path):
    """taxonomy.json bytes. 반환: (bytes 또는 None, 읽기 코드 또는 None)."""
    if not path or not os.path.isfile(path):
        return None, "TAXONOMY_MISSING"
    try:
        return lb.read_taxonomy_bytes(path), None
    except model.BundleError as e:
        return None, _code(e)


def load_taxonomy(path=None, data=None):
    """반환: (색인 또는 None, 파싱 오류 목록, 읽기 코드 또는 None). 색인은 JSON 행 목록으로 만든다.

    검증 오류가 있어도 행 목록을 읽으면 색인으로 판정한다. JSON 자체를 못 읽으면 색인은 None(상태 unknown)이다.
    """
    if data is None:
        data, code = read_bytes(path)
        if data is None:
            return None, [], code
    _tax, issues = lb.parse_taxonomy_bytes(data)
    try:
        sheets = {k: lb.taxonomy_raw_rows(data, k) for k in ("taxonomy", "questions", "synonyms", "rejected")}
    except model.BundleError as e:
        return None, issues, _code(e)
    return _index(sheets), issues, None


def _index(sheets):
    idx = {"axes": {}, "axis_order": [], "axis_rows": {}, "values": {}, "value_rows": {}, "questions": {},
           "q_texts": set(), "synonyms": {}, "rejected": set(), "hashes": {}}
    for name, rows in sheets.items():
        idx["hashes"][name] = _row_hash(rows or [])[:12]
    for n, c in sheets["taxonomy"] or []:
        a, v = _nk(c[0]), _nk(c[1])
        if not a:
            continue
        if v:
            old = idx["values"].get((a, v))
            if old is None or (_off(old[1]) and not _off(c)):
                idx["values"][(a, v)] = (n, c)
            if not _off(c):   # 같은 값 여러 행(labelbot이 정의·예를 합쳐 쓴다)
                idx["value_rows"].setdefault((a, v), []).append((n, c))
        else:
            if a not in idx["axes"]:
                idx["axes"][a] = (n, c)
                idx["axis_order"].append(a)
            if not _off(c):   # 같은 축 정의 여러 행(labelbot이 정의·예를 합쳐 쓴다)
                idx["axis_rows"].setdefault(a, []).append((n, c))
    for n, c in sheets["questions"] or []:
        qid = _s(c[0])
        if qid and qid not in idx["questions"]:
            idx["questions"][qid] = (n, c)
        if _s(c[1]):
            idx["q_texts"].add(_low(c[1]))
    for n, c in sheets["synonyms"] or []:
        k = _low(c[0])
        if k and _s(c[1]) and k not in idx["synonyms"]:
            idx["synonyms"][k] = (n, c)
    for _n, c in sheets["rejected"] or []:
        if c[1]:
            idx["rejected"].add(lb.rejected_key(c[0], c[1]))
    return idx


def _axis_row(idx, axis):
    return idx["axes"].get(_nk(axis)) if idx else None


def _value_row(idx, axis, value):
    return idx["values"].get((_nk(axis), _nk(value))) if idx else None


def _axis_name(idx, axis):
    r = _axis_row(idx, axis)
    return _s(r[1][0]) if r else _s(axis)


def _value_name(idx, axis, value):
    r = _value_row(idx, axis, value)
    return _s(r[1][1]) if r else _s(value)


# ---- 병합 ----------------------------------------------------------------------

def _key(e):
    k = e["kind"]
    if k == "value_add":
        return "tax.value.add|%s|%s" % (_nk(e["axis"]), _nk(e["value"]))
    if k == "value_off":
        return "tax.value.off|%s|%s" % (_nk(e["axis"]), _nk(e["value"]))
    if k == "value_def":
        return "tax.value.def|%s|%s" % (_nk(e["axis"]), _nk(e["value"]))
    if k == "overlap":
        return "tax.value.overlap|%s|%s" % (_nk(e["axis"]), "|".join(sorted(_nk(v) for v in e["values"])))
    if k == "axis_def":
        return "tax.axis.def|%s" % _nk(e["axis"])
    if k == "new_axis":
        return "tax.axis.new|%s" % _nk(e["name"])
    if k == "synonym":
        return "syn|%s|%s" % (_low(e["alias"]), _low(e["canonical"]))  # 상태 판정·상충과 같은 정규화
    if k == "q_edit":
        return "q.edit|%s" % _s(e["qid"])
    if k == "q_new":
        return "q.new|%s" % model.sha256_text(_low(e["text"] or e["memo"] or ""))[:16]
    if k == "term":
        return "term|%s" % _nk(e["term"])
    return "out|%s|%s" % (e["okind"], e["target"])


def strict_synonyms(groups, idx):
    """봇(S4)만 올린 동의어 묶음을 엄밀한 기준으로 거른다. 반환: (남은 묶음, 뺀 수).

    labelbot 후보와 같은 규칙(lb.synonym_reject_code)이다. 같은 표현에 표준어가 둘 이상이면 모두 빼고,
    모든 실행을 합친 빈도가 SYN_MIN_FREQ 미만이어도 뺀다. 사람·엔지니어 출처가 하나라도 있으면 그대로 둔다.
    idx가 없으면(taxonomy를 못 읽음) 표준어가 분류 체계에 있는지는 보지 않는다."""
    vocab = None
    if idx is not None:
        vocab = set(idx["axes"]) | {v for (_a, v) in idx["values"]}

    def bot_only(g):
        return g["e"]["kind"] == "synonym" and all(c["src"] == "S4" for c in g["chips"])

    canon = {}
    for g in groups:
        if bot_only(g):
            canon.setdefault(_low(g["e"]["alias"]), set()).add(_low(g["e"]["canonical"]))
    keep = []
    for g in groups:
        if bot_only(g):
            e = g["e"]
            if (lb.synonym_reject_code(e["alias"], e["canonical"], vocab) or len(canon[_low(e["alias"])]) > 1
                    or sum(c["n"] for c in g["chips"]) < lb.SYN_MIN_FREQ):
                continue
        keep.append(g)
    return keep, len(groups) - len(keep)


def _chip(e, rejected):
    return {"src": e["src"], "label": SOURCE_LABELS[e["src"]], "ws": e["ws"], "run": e["run"], "n": e["n"],
            "pid": e["pid"], "rejected": bool(e["pid"] and e["pid"] in rejected.get(e["ws"], ())),
            "metric": e["metric"], "examples": e["examples"]}


def merge(raw, rejected):
    """원시 제안 → 키별 묶음 {key: {"e": 첫 제안, "chips", "memos", "s7"}}. 용어는 같은 값·동의어 항목에 합친다.
    s7은 묶음의 엔지니어 답변 중 at이 가장 늦은 것의 문장이다(없으면 None, 같은 at이면 나중 행)."""
    groups, order = {}, []
    for e in raw:
        if e["kind"] == "axis_metric":
            continue
        k = _key(e)
        g = groups.get(k)
        if g is None:
            g = groups[k] = {"key": k, "e": e, "chips": [], "memos": [], "s7": None, "whys": [], "refs": []}
            order.append(k)
        if e.get("s7") is not None and (g["s7"] is None or e["s7"]["at"] >= g["s7"]["at"]):
            g["s7"] = e["s7"]
        g["chips"].append(_chip(e, rejected))
        if e["memo"] and e["kind"] not in ("synonym",) and e["memo"] not in g["memos"]:
            g["memos"].append(e["memo"])
            g.setdefault("memo_labels", []).append("엔지니어 메모" if e["src"] == "S7" else "재검토 메모")
        _add_evidence(g, e)
    by_term = {}
    for k in order:
        g = groups[k]
        if g["e"]["kind"] == "value_add":
            by_term.setdefault(_nk(g["e"]["value"]), []).append(k)
        elif g["e"]["kind"] == "synonym":
            by_term.setdefault(_nk(g["e"]["alias"]), []).append(k)
    out = []
    for k in order:
        g = groups[k]
        if g["e"]["kind"] == "term" and by_term.get(_nk(g["e"]["term"])):
            for other in by_term[_nk(g["e"]["term"])]:
                groups[other]["chips"].extend(g["chips"])
                for w in g["whys"]:
                    if w not in groups[other]["whys"]:
                        groups[other]["whys"].append(w)
                for r in g["refs"]:
                    if r not in groups[other]["refs"]:
                        groups[other]["refs"].append(r)
            continue
        out.append(g)
    for g in out:
        g["chips"] = _fold_chips(g["chips"])
    return out


def _add_evidence(g, e):
    """묶음에 제안 이유 {"label", "text"}와 근거 chunk {"ws", "chunk_id", "label"}를 겹치지 않게 붙인다."""
    label = SOURCE_LABELS[e["src"]]
    if e.get("why"):
        w = {"label": label, "text": e["why"]}
        if w not in g["whys"]:
            g["whys"].append(w)
    have = {(r["ws"], r["chunk_id"]) for r in g["refs"]}
    for ref in e.get("refs") or []:
        ws, cid = ref if isinstance(ref, tuple) else (e["ws"], ref)   # S7은 근거마다 작업 폴더가 있다
        if (ws, cid) not in have:
            have.add((ws, cid))
            g["refs"].append({"ws": ws, "chunk_id": cid, "label": label})


def _fold_chips(chips):
    """같은 (출처, 작업 폴더, 실행, 제안 ID) 칩은 건수를 더해 하나로."""
    out = {}
    for c in chips:
        k = (c["src"], c["ws"], c["run"], c["pid"] or "")
        if k in out:
            out[k]["n"] += c["n"]
        else:
            out[k] = dict(c)
    return [out[k] for k in sorted(out)]


# ---- 행 초안 --------------------------------------------------------------------

def _place(sheet, mode, row, readable=True, dups=()):
    if mode == "append":
        return "%s 시트 끝에 새 행 추가" % sheet
    if row is None:
        return "%s 시트 (%s)" % (sheet, "대상 행 없음" if readable else "행 번호 모름: taxonomy.json 확인 불가")
    if dups:
        return "%s 시트 %d행 덮어쓰기 (같은 값·축의 %s도 함께 고침)" % (sheet, row, ", ".join("%d행" % n for n in dups))
    return "%s 시트 %d행 덮어쓰기" % (sheet, row)


def _row(sheet, cells, mode, row=None, editable=(), required=(), label=None, checks=None, changes=None,
         readable=True, dups=(), dup_patch=None):
    """행 초안. cells는 원문 그대로다. checks {열: yn|yn_blank|kind|int|target|qid_new|axis|axis_new|value_new|parent}는
    화면이 반영 전에 보는 형식 규칙이다(axis_new·value_new는 서버도 _check_new_keys로 본다). 덮어쓰기 행의 dups는 같은 값·축의 다른 켜진 행 번호, dup_patch {열: 값}은 대상 행을 고칠 때
    그 행들에도 함께 쓰는 칸이다(labelbot이 같은 값 행의 문장을 합쳐 쓰므로 예전 문장이 남지 않게 한다)."""
    target = {"mode": mode, "row": row}
    if dups:
        target["dups"] = list(dups)
        target["dup_patch"] = {str(k): v for k, v in sorted((dup_patch or {}).items())}
    return {"sheet": sheet, "cells": [_cell(c) for c in cells], "editable": list(editable),
            "required": list(required), "checks": {str(k): v for k, v in sorted((checks or {}).items())},
            "changes": changes or [], "target": target,
            "place": _place(sheet, mode, row, readable, dups), "label": label}


def _over(sheet, found, fallback, readable, editable=(), change=None, dups=(), dup_patch=None, checks=None):
    """덮어쓰기 행: 지금 행 칸 그대로에 change {열: 값}만 바꾼다. 대상 행이 없으면 fallback 칸.
    dups [(행 번호, 칸)]는 같은 값·축의 켜진 행들이다(대상 행은 뺀다).
    열쇠 칸(축·값·질문 ID)은 editable에 넣지 않는다: 이름을 바꾸면 붙은 라벨·질문 적용 대상·동의어가 어긋난다."""
    cells = list(found[1]) if found else [_cell(c) for c in fallback]
    changes = []
    for col, v in sorted((change or {}).items()):
        if found and cells[col] != _cell(v):
            changes.append({"col": col, "from": cells[col], "to": _cell(v)})
        cells[col] = _cell(v)
    others = [n for n, _c in dups if n != found[0]] if found and dup_patch else []
    return _row(sheet, cells, "overwrite", found[0] if found else None, editable, checks=checks, changes=changes,
                readable=readable, dups=others, dup_patch=dup_patch)


def _value_dups(idx, axis, value):
    return (idx["value_rows"].get((_nk(axis), _nk(value))) or []) if idx else []


def _axis_dups(idx, axis):
    return ((idx.get("axis_rows") or {}).get(_nk(axis)) or []) if idx else []


BLANK_DEF = {H: "", I: "", J: ""}
VALUE_OVER_EDIT = (2, H, I, J, K)   # 있는 값 행 덮어쓰기: 상위값·정의·예·사용 여부(축·값 이름은 잠근다)
VALUE_OVER_CHECKS = {2: "parent", K: "yn_blank"}
DUP_FOLLOW = (2, K)   # 대상 행에서 바꾸면 같은 값의 다른 켜진 행에도 같이 쓰는 칸(상위값이 엇갈리거나 한 행만 꺼지지 않게)


def _parent(g):
    """value_add의 상위값. 엔지니어 답변(S7)에 있으면 그것을 쓴다."""
    return (g.get("s7") or {}).get("parent") or _s(g["e"].get("parent"))


def _s7_change(g):
    """엔지니어 답변(S7)이 채우는 칸 {열: 문장}. 정의 행은 H·I·J, 질문 수정은 B(문장). 빈 문장은 뺀다."""
    s7, k = g.get("s7") or {}, g["e"]["kind"]
    if k in ("value_add", "value_def", "axis_def", "new_axis"):
        return {c: s7[n] for c, n in ((H, "definition"), (I, "include"), (J, "exclude")) if s7.get(n)}
    if k == "q_edit" and s7.get("text"):
        return {1: s7["text"]}
    return {}


def draft(g, idx):
    """묶음 → 항목(제목, 그룹, 동작, 행 초안, 기각 행). 상태는 judge가 정한다."""
    e, k = g["e"], g["e"]["kind"]
    s7, fill = g.get("s7") or {}, _s7_change(g)
    it = {"id": _id(g["key"]), "key": g["key"], "kind": k, "group": "taxonomy", "action": "edit", "axis": "",
          "title": "", "rows": [], "reject_row": None, "reject_hint": None, "where": None, "conflict": False,
          "sources": g["chips"], "context": {"metrics": [], "memos": list(g["memos"]),
                                             "memo_labels": list(g.get("memo_labels") or [])},
          "evidence": {"whys": list(g.get("whys") or []), "refs": list(g.get("refs") or []), "slides": [],
                       "more": 0}}
    for c in g["chips"]:
        if c["metric"]:
            it["context"]["metrics"].append("%s: %s" % (c["label"], c["metric"]))
        if c["examples"] and not g.get("refs"):
            it["context"]["metrics"].append("%s: 예시 레코드·chunk %d건" % (c["label"], c["examples"]))
    if k in ("value_add", "value_off", "value_def", "axis_def", "overlap"):
        it["axis"] = _axis_name(idx, e["axis"])
    ax, rd = it["axis"], idx is not None
    if k == "value_add":
        value = _value_name(idx, e["axis"], e["value"])
        parent = _value_name(idx, e["axis"], _parent(g)) if _parent(g) else ""
        found = _value_row(idx, e["axis"], e["value"])
        it["title"] = "새 라벨: %s = %s" % (ax, value)
        if found and _off(found[1]):
            it["action"] = "overwrite"
            it["rows"] = [_over("taxonomy", found, [], rd, change={**fill, K: ""})]
        else:
            it["action"] = "add"
            cells = [ax, value, parent] + [""] * 8
            for col, v in fill.items():
                cells[col] = v
            it["rows"] = [_row("taxonomy", cells, "append", editable=(0, 1, 2, H, I, J), required=(0, 1),
                               checks={0: "axis", 1: "value_new", 2: "parent"})]
        fill = fill or ({2: parent} if s7.get("parent") else {})
        it["reject_row"] = ["값", "%s|%s" % (ax, value), "", ""]
    elif k == "value_off":
        value = _value_name(idx, e["axis"], e["value"])
        it["action"], it["title"] = "disable", "끄기: %s = %s" % (ax, value)
        # 같은 값의 켜진 행이 여럿이면 모두 끈다(하나라도 켜져 있으면 값이 살아 있다). 라벨 설명에 끄는 이유를 남길 수 있다
        it["rows"] = [_over("taxonomy", _value_row(idx, e["axis"], e["value"]), [ax, value] + [""] * 8 + ["N"],
                            rd, editable=(H,), change={K: "N"}, dups=_value_dups(idx, e["axis"], e["value"]),
                            dup_patch={K: "N"})]
    elif k == "value_def":
        value = _value_name(idx, e["axis"], e["value"])
        found = _value_row(idx, e["axis"], e["value"])
        it["title"] = "라벨 설명 보완: %s = %s" % (ax, value)
        # 덮어쓰기는 예전 정의를 버린다: 같은 값의 다른 켜진 행 H~J도 비운다
        over = _over("taxonomy", found, [ax, value] + [""] * 9, rd, editable=VALUE_OVER_EDIT, change=fill or None,
                     dups=_value_dups(idx, e["axis"], e["value"]), dup_patch=BLANK_DEF, checks=VALUE_OVER_CHECKS)
        it["rows"] = [over]
        if found:
            # 대상 행이 있으면 늘 두 길을 준다(빈 새 행은 반영 때 '쓸 문장 없음'으로 막는다).
            # 같은 값 행을 하나 더 붙이면 labelbot이 두 행의 정의·예를 합쳐 라벨러에 함께 준다
            cells = [ax, value] + [""] * 9
            for col, v in fill.items():
                cells[col] = v
            add = _row("taxonomy", cells, "append", editable=(2, H, I, J), checks={2: "parent"},
                       label="새 행으로 추가: %d행 정의와 함께 라벨러에 들어갑니다" % found[0])
            over["label"] = "또는 덮어쓰기: %d행의 예전 정의를 버릴 때" % found[0]
            it["rows"] = [add, over]
    elif k == "overlap":
        names = sorted((_value_name(idx, e["axis"], v) for v in e["values"]), key=_nk)
        it["title"] = "겹치는 라벨 설명: %s = %s ↔ %s" % (ax, names[0], names[1])
        it["rows"] = [_over("taxonomy", _value_row(idx, e["axis"], v), [ax, v] + [""] * 9, rd,
                            editable=VALUE_OVER_EDIT, dups=_value_dups(idx, e["axis"], v), dup_patch=BLANK_DEF,
                            checks=VALUE_OVER_CHECKS) for v in names]
    elif k == "axis_def":
        found = _axis_row(idx, e["axis"])
        it["title"] = "분류 기준 설명 보완: %s" % ax
        over = _over("taxonomy", found, [ax] + [""] * 10, rd, editable=(H, I, J), change=fill or None,
                     dups=_axis_dups(idx, e["axis"]), dup_patch=BLANK_DEF)
        it["rows"] = [over]
        if found:
            # 축 정의 행을 하나 더 붙이면(속성 칸은 비움) labelbot이 두 행의 정의·예를 합쳐 쓴다
            cells = [ax] + [""] * 10
            for col, v in fill.items():
                cells[col] = v
            add = _row("taxonomy", cells, "append", editable=(H, I, J),
                       label="새 행으로 추가: %d행 축 정의와 함께 라벨러에 들어갑니다" % found[0])
            over["label"] = "또는 덮어쓰기: %d행의 예전 정의를 버릴 때" % found[0]
            it["rows"] = [add, over]
    elif k == "new_axis":
        name = _axis_name(idx, e["name"])
        it["action"], it["title"], it["axis"] = "new_axis", "새 분류 기준: %s" % name, ""
        cells = [name] + [""] * 10
        for col, v in NEW_AXIS_DEFAULTS.items():
            cells[col] = v
        for col, v in fill.items():
            cells[col] = v
        # 축 속성은 기본값으로만 만든다(보드에서 숨김·편집 불가, 화면은 fixed로 읽기 전용 표시). 바꾸려면 편집기
        row = _row("taxonomy", cells, "append", editable=(0, H, I, J), required=(0,), checks={0: "axis_new"})
        row["fixed"] = [3, 4, 5]
        it["rows"] = [row]
    elif k == "synonym":
        memo = s7.get("memo") or e["memo"] or ""
        fill = {2: memo} if s7.get("memo") else {}
        it["group"], it["action"] = "synonyms", "add"
        it["title"] = "동의어: %s → %s" % (_s(e["alias"]), _s(e["canonical"]))
        it["rows"] = [_row("synonyms", [_s(e["alias"]), _s(e["canonical"]), memo], "append", editable=(0, 1, 2),
                           required=(0, 1))]
        it["reject_row"] = ["동의어", "%s|%s" % (_s(e["alias"]), _s(e["canonical"])), "", ""]
    elif k == "q_edit":
        qid = _s(e["qid"])
        found = idx["questions"].get(qid) if idx else None
        it["group"], it["title"] = "questions", "질문 문장 수정: %s" % qid
        it["rows"] = [_over("questions", found, [qid, "", "", ""], rd, editable=(1, 2, 3), change=fill or None,
                            checks={2: "target", 3: "int"})]
    elif k == "q_new":
        text = _s(e["text"])
        it["group"], it["action"], it["title"] = "questions", "add", "새 질문" + (": %s" % text if text else "")
        fill = {1: s7["text"]} if s7.get("text") else {}
        it["rows"] = [_row("questions", ["", fill.get(1, text), "", ""], "append", editable=(0, 1, 2, 3),
                           required=(0, 1, 2, 3), checks={0: "qid_new", 2: "target", 3: "int"})]
        # 기각 행 내용은 항상 원래 문장이다. 원래 문장이 없으면(NEED_QUESTION) 기각 행을 달지 않는다.
        if text:
            it["reject_row"] = ["질문", text, "", ""]
        else:
            it["reject_hint"] = HIDE_HINT
    elif k == "term":
        term = _s(e["term"])
        it["group"], it["action"], it["title"] = "term", "term", "용어 후보: %s" % term
        it["rows"] = [_row("synonyms", [term, "", "후보"], "append", editable=(0, 1, 2), required=(0, 1),
                           label="동의어 행 초안(표준어를 채웁니다)"),
                      _row("taxonomy", ["", term] + [""] * 9, "append", editable=(0, 1, 2, H, I, J), required=(0, 1),
                           checks={0: "axis", 1: "value_new", 2: "parent"}, label="라벨 행 초안(분류 기준을 채웁니다)")]
    else:
        it["group"], it["action"] = "outside", "outside"
        it["title"] = "%s: %s" % (e["okind"], e["target"] or "-")
        it["where"] = feedback.WHERE.get(e["okind"], OTHER_WHERE)
    if it["reject_row"] is None and k != "q_new":   # 기각하면 rejected 목록에 남겨 같은 제안이 다시 올라와도 묻지 않는다
        it["reject_row"] = [REJECT_KINDS[k], _reject_content(k, e, idx, ax), "", ""]
    if fill:
        for r in it["rows"]:
            r["label"] = r["label"] or S7_LABEL
    # 행이 둘이면서 서로 대안인 항목(새 행 추가 ↔ 덮어쓰기, 동의어 행 ↔ 값 행)은 하나를 고른다. 나머지는 모두 쓴다
    it["pick"] = "one" if len(it["rows"]) > 1 and k != "overlap" else "all"
    return it


# ---- 상태 ----------------------------------------------------------------------

def _runs(it):
    return sorted({c["run"] for c in it["sources"] if c["run"]})


def _prints(it):
    """출처 지문(출처 종류|작업 폴더|실행 ID). 초기화 뒤 새 지문이 붙은 항목만 다시 보인다."""
    return sorted({"%s|%s|%s" % (c["src"], c["ws"], c["run"]) for c in it["sources"]})


def apply_cleared(items, cleared, reset=False):
    """초기화(--reset)한 항목을 화면에서 뺀다. 반환: (남은 항목, 새 cleared, 뺀 수).

    reset이면 지금 항목 전부의 출처 지문을 cleared에 더한다. 그 뒤 실행에서는 cleared에 없던 출처 지문이
    생긴 항목(같은 제안이 새 실행·새 작업 폴더에서 다시 올라옴)만 다시 보인다. cleared.json을 지우면 되돌린다."""
    cleared = {k: list(v) for k, v in (cleared or {}).items() if isinstance(v, list)}
    if reset:
        for it in items:
            cleared[it["id"]] = sorted(set(cleared.get(it["id"], [])) | set(_prints(it)))
    keep = [it for it in items if it["id"] not in cleared or set(_prints(it)) - set(cleared[it["id"]])]
    return keep, cleared, len(items) - len(keep)


def apply_decisions(items, decisions):
    """사람이 보드에서 확정한 처리(최종 완료)를 상태에 얹는다. 반환: 남길 decisions.

    - 반영함: done("보드에서 반영함"). 시트로 이미 반영됨이면 그 판정을 그대로 둔다.
    - 기각함: 반영됨·기각됨(rejected 목록 등)으로 이미 판정한 항목이 아니면 rejected("보드에서 기각함").
    - 반영함 확정 뒤 새 출처 지문이 붙은 항목(같은 제안이 새 실행에서 다시 올라옴)은 확정을 버리고 다시 판정한다.
      기각함은 새 출처가 붙어도 유지한다(풀려면 '기각 해제'). 기각 뒤 사람·엔지니어 출처(HUMAN_SOURCES)가 새로 붙으면
      fresh_human으로 표시만 한다. 지금 목록에 없는 항목의 반영함 확정은 버리고, 기각함은 남긴다(초기화·일부 작업 폴더만 본 실행)."""
    ids = {it["id"] for it in items}
    keep = {iid: d for iid, d in (decisions or {}).items()
            if iid not in ids and isinstance(d, dict) and d.get("decision") == "rejected"}
    for it in items:
        d = (decisions or {}).get(it["id"])
        if not isinstance(d, dict) or d.get("decision") not in DECISION_KINDS:
            continue
        new = set(_prints(it)) - set(d.get("prints") or [])
        if d["decision"] == "applied" and new:
            continue
        keep[it["id"]] = d
        it["human"] = {"decision": d["decision"], "at": d.get("at") or ""}
        if d["decision"] == "rejected":
            if any(p.split("|", 1)[0] in HUMAN_SOURCES for p in new):
                it["fresh_human"] = True
            if it["status"] == "done":
                continue
            if it["status"] != "rejected":
                it["status"], it["status_note"] = "rejected", "보드에서 기각함"
            it["reopen"] = not _engr_rejected(it)
            continue
        if it["status"] != "done":
            it["status"], it["status_note"] = "done", "보드에서 반영함"
    return keep


def record_decisions(out_dir, marks, now=None):
    """'최종 완료' 요청 {항목 ID: "applied"|"rejected"|"reopen"(기각 해제)|None(확정 취소)}을 decisions.json에 더한다.
    지금 보드(taxonomy_board.json)에 있는 항목만 받는다. 반환: 바뀐 수. 잘못된 요청은 ValueError(사유 코드)."""
    if not isinstance(marks, dict) or len(marks) > MARKS_MAX:
        raise ValueError("DECISIONS_FORMAT_INVALID")
    doc = _json_file(os.path.join(out_dir, DOC), _Bad())
    items = {it["id"]: it for it in (doc or {}).get("items") or [] if isinstance(it, dict) and it.get("id")}
    path = os.path.join(out_dir, DECISIONS)
    cur = _json_file(path, _Bad()) or {}
    cur = cur if isinstance(cur, dict) else {}
    at = (now or datetime.datetime.now().astimezone()).isoformat(timespec="seconds")
    n = 0
    for iid, kind in marks.items():
        if iid not in items or (kind is not None and kind not in MARK_KINDS):
            raise ValueError("DECISIONS_ITEM_INVALID")
        if kind is None or kind == "reopen":
            n += 1 if cur.pop(iid, None) is not None else 0
        else:
            cur[iid] = {"decision": kind, "at": at, "prints": _prints(items[iid])}
            n += 1
    io.write_json(path, cur)
    return n


def _target_status(targets):
    """문장 수정 항목: 대상 행이 하나라도 없으면 blocked. 반영 여부는 보드 확정(decisions)으로만 정한다."""
    if any(t is None for t in targets):
        return "blocked", "대상 행 없음"
    return "open", None


def _sheet_status(it, g, idx):
    e, k = g["e"], g["e"]["kind"]
    if k in ("value_add", "value_off", "value_def", "axis_def", "overlap"):
        ax = _axis_row(idx, e["axis"])
        if ax is None:
            return "blocked", "taxonomy에 없는 축(먼저 축 정의 행을 더합니다)"
        if _off(ax[1]):
            return "blocked", "꺼진 축(축 정의 행의 사용 여부가 N)"
    if k == "value_add":
        found = _value_row(idx, e["axis"], e["value"])
        if _nk(e["value"]) in lb.TAXONOMY_RESERVED:
            return "blocked", "예약어는 값으로 쓸 수 없습니다"
        if found and not _off(found[1]):
            return "done", "taxonomy에 있음(%d행)" % found[0]
        if _parent(g):
            p = _value_row(idx, e["axis"], _parent(g))
            if p is None or _off(p[1]):
                return "blocked", "taxonomy에 없는 상위값(먼저 상위값 행을 더합니다)"
        return "open", ("꺼진 값을 다시 켭니다(%d행)" % found[0]) if found else None
    if k == "value_off":
        found = _value_row(idx, e["axis"], e["value"])
        if found is None:
            return "blocked", "taxonomy에 없는 값"
        if _off(found[1]):
            return "done", "이미 꺼짐(%d행)" % found[0]
        return _users(idx, e["axis"], e["value"])
    if k == "value_def":
        found = _value_row(idx, e["axis"], e["value"])
        for row in idx["value_rows"].get((_nk(e["axis"]), _nk(e["value"]))) or [found]:
            st = _s7_status(g, row)
            if st:
                return st
        return _target_status([found])
    if k == "overlap":
        return _target_status([_value_row(idx, e["axis"], v) for v in e["values"]])
    if k == "axis_def":
        found = _axis_row(idx, e["axis"])
        for row in (idx.get("axis_rows") or {}).get(_nk(e["axis"])) or [found]:
            st = _s7_status(g, row)
            if st:
                return st
        return _target_status([found])
    if k == "q_edit":
        found = idx["questions"].get(_s(e["qid"]))
        return _s7_status(g, found) or _target_status([found])
    if k == "new_axis":
        found = _axis_row(idx, e["name"])
        return ("done", "taxonomy에 있는 축(%d행)" % found[0]) if found else ("open", None)
    if k == "synonym":
        found = idx["synonyms"].get(_low(e["alias"]))
        if found is None:
            return "open", None
        if _low(found[1][1]) == _low(e["canonical"]):
            return "done", "taxonomy에 있음(%d행)" % found[0]
        return "blocked", "같은 동의어가 다른 표준어로 이미 있음(%d행)" % found[0]
    if k == "q_new":
        if _s(e["text"]) and _low(e["text"]) in idx["q_texts"]:
            return "done", "같은 문장의 질문이 taxonomy에 있음"
        return "open", None
    if k == "term":
        t = _nk(e["term"])
        if any(v == t and not _off(r[1]) for (_a, v), r in idx["values"].items()):
            return "done", "값으로 taxonomy에 있음"
        if any(_nk(r[1][0]) == t for r in idx["synonyms"].values()):
            return "done", "동의어로 taxonomy에 있음"
        return "open", None
    return "open", None


def _s7_status(g, found):
    """엔지니어 답변(S7)이 채운 칸이 지금 행과 모두 같으면(공백 정규화) 반영됨. 아니면 None(기존 판정을 따른다)."""
    fill = _s7_change(g)
    if not fill or found is None:
        return None
    if all(_ws(found[1][col]) == _ws(v) for col, v in fill.items()):
        return "done", "답변 문장이 taxonomy에 있음(%d행)" % found[0]
    return None


def _users(idx, axis, value):
    """끄려는 값을 쓰는 곳: 켜진 하위값(C열)과 questions 적용 대상(축=값). 있으면 blocked(끄면 검증이 깨짐)."""
    a, v = _nk(axis), _nk(value)
    kids = sum(1 for (ka, _kv), (_n, c) in idx["values"].items() if ka == a and not _off(c) and _nk(c[2]) == v)
    qs = []
    for qid, (_n, c) in sorted(idx["questions"].items()):
        ta, sep, tv = c[2].partition("=")
        if sep and _nk(ta) == a and _nk(tv) == v:
            qs.append(qid)
    if not kids and not qs:
        return "open", None
    parts = (["하위값 %d개" % kids] if kids else []) + (["질문 %s" % ", ".join(qs)] if qs else [])
    return "blocked", "%s가 이 값을 씀" % "·".join(parts)


def _reject_content(k, e, idx, ax):
    """기각 행 내용: 항목 대상을 "|"로 이은 원래 표기(편집과 무관). 대조는 lb.rejected_key(칸마다 norm_key)로 한다."""
    if k in ("value_off", "value_def"):
        return "%s|%s" % (ax, _value_name(idx, e["axis"], e["value"]))
    if k == "overlap":
        return "|".join([ax] + sorted((_value_name(idx, e["axis"], v) for v in e["values"]), key=_nk))
    if k == "axis_def":
        return ax
    if k == "q_edit":
        return _s(e["qid"])
    if k == "new_axis":
        return _axis_name(idx, e["name"])
    if k == "term":
        return _s(e["term"])
    return "%s|%s" % (_s(e["okind"]), _s(e["target"]))


def _engr_rejected(it):
    """출처가 모두 Domain-Engr-bot에서 기각된 항목(보드의 기각 해제로는 풀리지 않는다)."""
    return bool(it["sources"]) and all(c["rejected"] for c in it["sources"])


def _reject_key(it):
    """rejected 목록 대조 키(종류, 정규화 내용). 기각 행이 없으면 None."""
    rr = it.get("reject_row")
    return lb.rejected_key(rr[0], rr[1]) if rr and _s(rr[1]) else None


def judge(groups, items, idx):
    """항목마다 status·status_note를 채운다."""
    for g, it in zip(groups, items):
        if idx is None:
            it["status"], it["status_note"] = "unknown", "taxonomy.json을 읽지 못해 판정하지 않습니다"
            continue
        st, note = _sheet_status(it, g, idx)
        key = _reject_key(it)
        it["reject_key"] = list(key) if key else None
        if st != "done":
            if key in idx["rejected"]:
                st, note = "rejected", "rejected 목록에 있음"
                it["reopen"] = not _engr_rejected(it)
            elif it["sources"] and all(c["rejected"] for c in it["sources"]):
                st, note = "rejected", "Domain-Engr-bot에서 기각"
        it["status"], it["status_note"] = st, note
    syn = {}
    for it in items:
        if it["kind"] == "synonym":
            syn.setdefault(it["key"].split("|")[1], []).append(it)
    for lst in syn.values():
        if len(lst) > 1:
            for it in lst:
                it["conflict"] = True


# ---- 반영(최종 완료: 미리보기 → taxonomy.json 쓰기) ------------------------------------
# 요청: {"kind": "taxonomy_board_decisions", "base_version", "marks": {ID: "applied"|"rejected"|null},
#        "edits": {ID: {"choice": 고른 행 번호(pick=one일 때), "rows": [[칸...], ...]}}}
# 칸은 서버의 행 초안에서 다시 만들고, 사람이 고친 값은 그 행의 editable 열에만 얹는다(나머지 칸은 받지 않는다).
# 덮어쓰기는 열 단위 패치다: 지금 행과 다른 칸만 바꾸고, 같은 행·열을 두 항목이 다르게 고치면 ITEM_CONFLICT.

# 항목 종류 → rejected 종류. 기각하면 모든 종류가 rejected 목록에 행을 남긴다(원래 문장이 없는 새 질문만 결정만 남긴다)
REJECT_KINDS = {"value_add": "값", "synonym": "동의어", "q_new": "질문", "value_off": "값 끄기", "value_def": "값 정의",
                "overlap": "겹침", "axis_def": "축 정의", "q_edit": "질문 수정", "new_axis": "새 축", "term": "용어",
                "outside": "기타"}


def _check_payload(payload):
    """반환: (marks, edits, base_version). 형식이 틀리면 BoardRefused(DECISIONS_FORMAT_INVALID)."""
    if not isinstance(payload, dict) or payload.get("kind") != DECISIONS_KIND:
        raise BoardRefused("DECISIONS_FORMAT_INVALID")
    marks, edits = payload.get("marks"), payload.get("edits") or {}
    if not isinstance(marks, dict) or len(marks) > MARKS_MAX or not isinstance(edits, dict) \
            or len(edits) > MARKS_MAX or not isinstance(payload.get("base_version"), str):
        raise BoardRefused("DECISIONS_FORMAT_INVALID")
    for kind in marks.values():
        if kind is not None and kind not in MARK_KINDS:
            raise BoardRefused("DECISIONS_ITEM_INVALID")
    return marks, edits, payload["base_version"]


def _chosen(it, edit):
    """반영할 행 index 목록. pick=one이면 고른 행 하나(기본 0)."""
    if it.get("pick") != "one":
        return list(range(len(it["rows"])))
    choice = edit.get("choice", 0) if isinstance(edit, dict) else 0
    if not isinstance(choice, int) or isinstance(choice, bool) or not 0 <= choice < len(it["rows"]):
        raise BoardRefused("EDIT_INVALID")
    return [choice]


def _final_cells(r, client):
    """서버 행 초안 칸에 사람이 고친 editable 열 값만 얹는다."""
    cells = list(r["cells"])
    if client is None:
        return cells
    if not isinstance(client, list) or len(client) > len(cells):
        raise BoardRefused("EDIT_INVALID")
    for c in r["editable"]:
        if c < len(client):
            v = client[c]
            if not isinstance(v, str) or len(v) > CELL_MAX:
                raise BoardRefused("EDIT_INVALID")
            cells[c] = v.replace("\r\n", "\n").replace("\r", "\n")
    return cells


def _current(doc, sheet, row):
    """doc의 행(번호 = index + 2) 칸 리스트. 없거나 객체가 아니면 None."""
    rows = doc.get(sheet)
    if not isinstance(rows, list) or row is None or not 2 <= row < len(rows) + 2 or not isinstance(rows[row - 2], dict):
        return None
    return lb.row_cells(rows[row - 2], HEADERS[sheet])


def _base_cells(r):
    """행 초안을 만들 때의 지금 행(초안이 바꾼 칸을 되돌린 칸)."""
    cells = list(r["cells"])
    for ch in r["changes"]:
        cells[ch["col"]] = ch["from"]
    return cells


def _add_patch(patches, sheet, row, patch, iid):
    cur = patches.setdefault((sheet, row), {})
    for col, v in patch.items():
        if col in cur and cur[col][0] != v:
            raise BoardRefused("ITEM_CONFLICT")
        cur[col] = (v, iid)


def _check_synonyms(doc, appends):
    """붙일 동의어 행끼리, 또는 doc의 동의어와 같은 동의어(_low 비교)가 다른 표준어를 가리키면 ITEM_CONFLICT.
    파서는 같은 동의어의 첫 행만 쓰므로 둘째 행은 쓰여도 효과가 없다."""
    seen = {}
    rows = doc.get("synonyms")
    for r in rows if isinstance(rows, list) else []:
        if isinstance(r, dict):
            c = lb.row_cells(r, HEADERS["synonyms"])
            if _low(c[0]) and _s(c[1]):
                seen.setdefault(_low(c[0]), _low(c[1]))
    for sheet, cells in appends:
        if sheet != "synonyms" or not _low(cells[0]):
            continue
        a, canon = _low(cells[0]), _low(cells[1])
        if seen.setdefault(a, canon) != canon:
            raise BoardRefused("ITEM_CONFLICT")


def _check_new_keys(doc, appends):
    """붙일 taxonomy 행의 열쇠 칸 검사(사람이 바꿀 수 있는 칸이라 서버에서도 본다). 어기면 ITEM_NOT_APPLICABLE.
    - 축 정의 행(값 빈칸): 이미 있는 축 이름이면 안 된다(속성이 다른 같은 축 행이 생긴다).
    - 값 행: 예약어이거나, 같은 축에 켜진 같은 값이 있으면 안 된다(파서가 조용히 두 행을 합친다)."""
    axes, on = set(), set()
    rows = doc.get("taxonomy")
    for r in rows if isinstance(rows, list) else []:
        if isinstance(r, dict):
            c = lb.row_cells(r, TAX_COLS)
            if not _s(c[1]):
                axes.add(_nk(c[0]))
            elif not _off(c):
                on.add((_nk(c[0]), _nk(c[1])))
    for sheet, cells, rule in appends:
        if sheet != "taxonomy":
            continue
        if rule.get("0") == "axis_new" and _nk(cells[0]) in axes:
            raise BoardRefused("ITEM_NOT_APPLICABLE")
        if rule.get("1") == "value_new" and (_nk(cells[1]) in lb.TAXONOMY_RESERVED
                                             or (_nk(cells[0]), _nk(cells[1])) in on):
            raise BoardRefused("ITEM_NOT_APPLICABLE")
        if _s(cells[1]):   # 같은 확정 안에서 같은 축·값을 두 번 붙이는 것도 막는다
            on.add((_nk(cells[0]), _nk(cells[1])))
        else:
            axes.add(_nk(cells[0]))


def plan_changes(doc, items, marks, edits, today):
    """확정 표시와 편집으로 새 doc를 만든다(원래 doc는 그대로). 반환: 새 doc.
    거절: 모르는 항목·반영할 수 없는 상태·필수 칸 빈칸·쓸 문장 없음은 ITEM_NOT_APPLICABLE,
    같은 칸을 다르게 고치는 두 항목·같은 동의어를 다른 표준어로 붙이는 행은 ITEM_CONFLICT,
    대상 행이 초안과 다르면 TAXONOMY_CHANGED(409)."""
    by_id = {it["id"]: it for it in items}
    for iid in marks:
        if iid not in by_id:
            raise BoardRefused("ITEM_NOT_APPLICABLE")
    patches, appends, rejects, reopen, new_keys = {}, [], [], set(), []
    for it in items:
        kind = marks.get(it["id"])
        if kind is None:
            continue
        iid = it["id"]
        if kind == "reopen":   # 기각 해제: rejected 목록의 같은 키 행을 지운다(보드 기각 확정은 record_decisions가 지운다)
            if it["status"] != "rejected" or not it.get("reopen"):
                raise BoardRefused("ITEM_NOT_APPLICABLE")
            if it.get("reject_key"):
                reopen.add(tuple(it["reject_key"]))
            continue
        if kind == "rejected":
            if it["status"] not in ("open", "blocked"):
                raise BoardRefused("ITEM_NOT_APPLICABLE")
            rr = it.get("reject_row")
            if rr and _s(rr[1]):
                rejects.append([rr[0], rr[1], today, REJECT_REASON, iid])
            continue
        if it["status"] != "open":
            raise BoardRefused("ITEM_NOT_APPLICABLE")
        if not it["rows"]:
            continue   # taxonomy 밖 항목: 결정만 남긴다
        edit = edits.get(iid) if isinstance(edits.get(iid), dict) else {}
        client_rows = edit.get("rows") if isinstance(edit.get("rows"), list) else []
        wrote = False
        for ri in _chosen(it, edit):
            r = it["rows"][ri]
            cells = _final_cells(r, client_rows[ri] if ri < len(client_rows) else None)
            if any(not cells[c].strip() for c in r["required"]):
                raise BoardRefused("ITEM_NOT_APPLICABLE")
            no_text = it["kind"] in EDIT_KINDS and r["editable"] and not any(cells[c].strip() for c in r["editable"])
            if r["target"]["mode"] == "append":
                if no_text:
                    raise BoardRefused("ITEM_NOT_APPLICABLE")
                appends.append((r["sheet"], cells))
                new_keys.append((r["sheet"], cells, r.get("checks") or {}))
                wrote = True
                continue
            row = r["target"]["row"]
            cur = _current(doc, r["sheet"], row)
            if row is None:
                raise BoardRefused("ITEM_NOT_APPLICABLE")
            if cur is None or cur != _base_cells(r):
                raise BoardRefused("TAXONOMY_CHANGED", 409)
            patch = {c: v for c, v in enumerate(cells) if v != cur[c]}
            if not patch:
                continue   # 고치지 않은 행(겹치는 값 정의의 한쪽 등)은 쓰지 않는다
            if no_text:
                raise BoardRefused("ITEM_NOT_APPLICABLE")
            _add_patch(patches, r["sheet"], row, patch, iid)
            dup_patch = {int(c): v for c, v in (r["target"].get("dup_patch") or {}).items()}
            if r["sheet"] == "taxonomy":
                dup_patch.update({c: patch[c] for c in DUP_FOLLOW if c in patch})
            for d in r["target"].get("dups") or []:
                dcur = _current(doc, r["sheet"], d)
                if dcur is None or [_nk(x) for x in dcur[:2]] != [_nk(x) for x in cur[:2]]:
                    raise BoardRefused("TAXONOMY_CHANGED", 409)
                dp = {c: v for c, v in dup_patch.items() if dcur[c] != v}
                if dp:
                    _add_patch(patches, r["sheet"], d, dp, iid)
            wrote = True
        if not wrote:
            raise BoardRefused("ITEM_NOT_APPLICABLE")
    _check_synonyms(doc, appends)
    _check_new_keys(doc, new_keys)
    new = json.loads(json.dumps(doc, ensure_ascii=False))
    for (sheet, row), patch in sorted(patches.items()):
        cells = _current(new, sheet, row)
        for col, (v, _iid) in patch.items():
            cells[col] = v
        new[sheet][row - 2] = dict(lb.row_obj(cells, HEADERS[sheet]))
    for sheet, cells in appends:     # 덮어쓰기(원래 행 번호)를 모두 한 뒤 끝에 붙인다
        if not isinstance(new.get(sheet), list):
            new[sheet] = []
        new[sheet].append(dict(lb.row_obj(cells, HEADERS[sheet])))
    if not isinstance(new.get("rejected"), list):
        new["rejected"] = []
    if reopen:
        new["rejected"] = [r for r in new["rejected"] if not (
            isinstance(r, dict) and lb.rejected_key(*lb.row_cells(r, lb.REJECTED_HEADER)[:2]) in reopen)]
    have = {lb.rejected_key(*lb.row_cells(r, lb.REJECTED_HEADER)[:2]) for r in new["rejected"] if isinstance(r, dict)}
    for cells in rejects:
        key = lb.rejected_key(cells[0], cells[1])
        if key not in have:   # 같은 키(띄어쓰기·대소문자만 다른 두 카드 등)는 한 행만 남긴다
            have.add(key)
            new["rejected"].append(dict(lb.row_obj(cells, lb.REJECTED_HEADER)))
    return new


def apply_marks(out_dir, tax_path, payload, preview, now=None):
    """미리보기(preview=True) 또는 반영. 보드 문서(taxonomy_board.json)의 항목과 지금 taxonomy.json으로 새 doc를 만든다.

    미리보기 반환: {"ok", "diff", "issues", "version"}(아무것도 쓰지 않는다).
    반영 반환: {"ok", "changed"(확정 수), "written"(바뀐 행 수), "version"(새 버전)}. 쓰기는 save_doc(by="board")만 한다.
    저장한 뒤 확정 기록(decisions.json)이 실패하면 ok 그대로 decisions_failed(사유 코드)를 붙인다(쓴 것은 그대로다).
    읽기·비교·검증·저장은 편집기와 같은 어댑터 commit_taxonomy가 하고 거절 코드도 같다: 파일 없음 TAXONOMY_NOT_FOUND(404),
    읽기 실패 TAXONOMY_READ_FAILED(500, detail), 버전이 다르면 TAXONOMY_CHANGED(409), 검증 실패 TAXONOMY_INVALID(400, issues,
    파일 그대로), 쓰기 실패 TAXONOMY_WRITE_FAILED(500). 모두 BoardRefused로 올린다."""
    marks, edits, base = _check_payload(payload)
    board = _json_file(os.path.join(out_dir, DOC), _Bad())
    if not isinstance(board, dict):
        raise BoardRefused("BOARD_DOC_MISSING", 500)
    items = [it for it in board.get("items") or [] if isinstance(it, dict) and it.get("id")]
    if (board.get("taxonomy") or {}).get("version") != base:
        raise BoardRefused("TAXONOMY_CHANGED", 409)
    today = (now or datetime.datetime.now().astimezone()).date().isoformat()
    try:
        res = lb.commit_taxonomy(tax_path, base, lambda doc: plan_changes(doc, items, marks, edits, today), "board",
                                 preview=preview)
    except lb.TaxonomyCommitError as e:
        raise BoardRefused(e.code, e.status, e.issues, e.detail)
    diff = res["diff"]
    if preview:
        return {"ok": True, "diff": diff, "issues": res["issues"] if diff else [], "version": res["version"]}
    out = {"ok": True, "changed": 0, "written": len(diff), "version": res["version"]}
    try:
        out["changed"] = record_decisions(out_dir, marks, now)
    except (ValueError, OSError) as e:   # taxonomy.json은 이미 썼다: 거절 대신 경고 코드를 붙인다
        out["decisions_failed"] = str(e) if isinstance(e, ValueError) else type(e).__name__
    return out


# ---- 문서·화면 --------------------------------------------------------------------

_KIND_ORDER = ("new_axis", "axis_def", "value_add", "value_def", "overlap", "value_off", "synonym", "q_edit", "q_new",
               "term", "outside")


def _rank(it):
    """축 묶음 안 순서: 사람 출처(재검토·검수 등록) → 추가·수정 → 끄기."""
    if it["kind"] == "value_off":
        return 2
    return 0 if any(c["src"] in HUMAN_SOURCES for c in it["sources"]) else 1


def _sort(items, idx):
    order = {a: i for i, a in enumerate(idx["axis_order"])} if idx else {}
    return sorted(items, key=lambda it: (GROUPS.index(it["group"]), order.get(_nk(it["axis"]), len(order)),
                                         _nk(it["axis"]), _rank(it), _KIND_ORDER.index(it["kind"]), it["key"]))


def _slide_no(cid, seq):
    """pptx chunk(part ppt/slides/slideN.xml)는 N, 아니면 chunk 순번(seq)."""
    part = cid.split(":", 1)[1] if ":" in cid else ""
    tail = part.rsplit("/", 1)[-1]
    if part.startswith("ppt/slides/") and tail.startswith("slide") and tail.endswith(".xml") and tail[5:-4].isdigit():
        return int(tail[5:-4]), True
    return (seq if isinstance(seq, int) else None), False


def resolve_slides(items, ws_roots):
    """항목마다 근거 chunk를 작업 폴더 work.sqlite(읽기 전용)에서 찾아 evidence.slides를 채운다.

    slides[]: {"label", "file", "slide_no", "is_slide", "title", "preview"(미리보기 키 "<작업 폴더>|<chunk>" 또는 None)}.
    재검토 파일(S5F)처럼 작업 폴더를 모르는 근거는 모든 작업 폴더에서 찾는다. 못 찾은 근거도 chunk ID로 남긴다.
    반환: 미리보기 {키: data URL}. 같은 슬라이드는 한 번만 넣고(여러 항목이 같이 쓴다) PREVIEWS_MAX장·
    PREVIEW_BYTES_MAX까지. 읽기 실패는 조용히 건너뛴다(미리보기 없음)."""
    roots = {}
    for r in ws_roots:
        roots.setdefault(os.path.basename(os.path.normpath(r)), r)
    want = {}
    for it in items:
        for ref in it["evidence"]["refs"][:SLIDES_PER_ITEM]:
            for ws in ([ref["ws"]] if ref["ws"] in roots else sorted(roots)):
                want.setdefault(ws, set()).add(ref["chunk_id"])
    ctx, names, loaders = {}, {}, {}
    for ws in sorted(want):
        try:
            got = lb.chunk_context(roots[ws], want[ws])
            names[ws] = lb.file_names(roots[ws], {c["file_id"] for c in got.values()})
        except _REF_READ_ERRORS:
            continue
        loaders[ws] = lb.WsLoader(roots[ws])
        for cid, c in got.items():
            ctx[(ws, cid)] = c
    previews, used, failed = {}, 0, set()
    for it in items:
        ev = it["evidence"]
        for ref in ev["refs"][:SLIDES_PER_ITEM]:
            hit = None
            for ws in ([ref["ws"]] if ref["ws"] in roots else sorted(roots)):
                if (ws, ref["chunk_id"]) in ctx:
                    hit = ws
                    break
            c = ctx.get((hit, ref["chunk_id"])) if hit else None
            no, is_slide = _slide_no(ref["chunk_id"], c.get("seq") if c else None)
            s = {"label": ref["label"], "chunk_id": ref["chunk_id"], "ws": hit or ref["ws"],
                 "file": names.get(hit, {}).get(c["file_id"], "") if c else "", "slide_no": no, "is_slide": is_slide,
                 "title": (c.get("title") or "") if c else "", "found": c is not None, "preview": None}
            pk = "%s|%s" % (hit, ref["chunk_id"])
            if c and c.get("preview_rel") and pk not in previews and pk not in failed and len(previews) < PREVIEWS_MAX:
                try:
                    b = loaders[hit].image_bytes({"rel_file": c["preview_rel"]})
                except _REF_READ_ERRORS:
                    b = None
                if b and used + len(b) <= PREVIEW_BYTES_MAX:
                    previews[pk] = "data:image/jpeg;base64," + base64.b64encode(b).decode("ascii")
                    used += len(b)
                else:
                    failed.add(pk)
            s["preview"] = pk if pk in previews else None
            ev["slides"].append(s)
        ev["more"] = max(0, len(ev["refs"]) - SLIDES_PER_ITEM)
        del ev["refs"]
    return previews


def _axes_on(idx):
    """값 행의 A열로 쓸 수 있는 켜진 축 이름(정확한 표기). 화면의 형식 검사용."""
    if not idx:
        return []
    return sorted(_s(c[0]) for _r, c in idx["axes"].values() if not _off(c))


def _targets(idx):
    """질문 적용 대상으로 쓸 수 있는 [축 이름, 값 norm_key](켜진 축의 켜진 값). 화면의 형식 검사용."""
    if not idx:
        return []
    out = []
    for (a, v), (_n, c) in sorted(idx["values"].items()):
        ax = idx["axes"].get(a)
        if ax and not _off(ax[1]) and not _off(c):
            out.append([_s(ax[1][0]), v])
    return out


def _axes(items, metrics, idx):
    names = []
    for a in (idx["axis_order"] if idx else []):
        names.append(_s(idx["axes"][a][1][0]))
    for name in sorted(set(metrics) | {it["axis"] for it in items if it["group"] == "taxonomy" and it["axis"]},
                       key=_nk):
        if _nk(name) not in {_nk(n) for n in names}:
            names.append(name)
    out = []
    for name in names:
        m = [x for a, lst in sorted(metrics.items()) if _nk(a) == _nk(name) for x in lst]
        r = _axis_row(idx, name)
        out.append({"name": name, "row": r[0] if r else None, "off": bool(r and _off(r[1])),
                    "metrics": sorted(m, key=lambda x: (x["ws"], x["run"]))})
    return out


def build(ws_roots, taxonomy_path, out_dir, ledger_dir=None, requests_dir=None, now=None, taxonomy_bytes=None,
          reset=False, questions_dir=None):
    """화면·json(·cleared.json)을 쓴다. reset이면 지금 항목을 모두 초기화한다. 반환: 문서 dict.
    questions_dir는 S7(엔지니어 답변)을 읽을 질문 폴더다(없으면 S7 없음). 문서의 taxonomy.version은 읽은
    taxonomy.json bytes의 sha256이다(반영할 때 이 버전과 지금 파일이 같아야 쓴다)."""
    if requests_dir is None and taxonomy_path:
        requests_dir = os.path.join(os.path.dirname(os.path.abspath(taxonomy_path)), REQUESTS_DIRNAME)
    raw, metrics, rejected, bad = collect(ws_roots, ledger_dir, requests_dir, questions_dir)
    data, read_code = (taxonomy_bytes, None) if taxonomy_bytes is not None else read_bytes(taxonomy_path)
    idx, issues = None, []
    if data is not None:
        idx, issues, read_code = load_taxonomy(data=data)
    groups, n_syn_filtered = strict_synonyms(merge(raw, rejected), idx)
    items = [draft(g, idx) for g in groups]
    judge(groups, items, idx)
    cleared_path = os.path.join(out_dir, CLEARED)
    cleared = _json_file(cleared_path, _Bad()) or {}
    items, cleared, n_cleared = apply_cleared(items, cleared if isinstance(cleared, dict) else {}, reset)
    items = _sort(items, idx)
    dec_path = os.path.join(out_dir, DECISIONS)
    decisions = _json_file(dec_path, _Bad()) if os.path.isfile(dec_path) else None
    if isinstance(decisions, dict):
        kept = apply_decisions(items, decisions)
        if kept != decisions:
            io.write_json(dec_path, kept)
    previews = resolve_slides(items, ws_roots)
    counts = {s: sum(1 for it in items if it["status"] == s) for s in STATUSES}
    sources = {c: 0 for c in SOURCE_CODES}
    for e in raw:
        sources[e["src"][:2]] += 1
    doc = {
        "kind": "taxonomy_board",
        "generated_at": (now or datetime.datetime.now().astimezone()).isoformat(timespec="seconds"),
        "taxonomy": {"file": os.path.basename(taxonomy_path or "") or "taxonomy.json", "read_code": read_code,
                     "readable": idx is not None, "issues": issues,
                     "version": hashlib.sha256(data).hexdigest() if data is not None else None,
                     "sheet_hashes": dict(sorted(idx["hashes"].items())) if idx else {}},
        "columns": {"taxonomy": TAX_COLS, "synonyms": SYN_COLS, "questions": Q_COLS, "rejected": REJ_COLS},
        "column_labels": COLUMN_LABELS, "column_help": COLUMN_HELP, "hidden_columns": HIDDEN_COLUMNS,
        "counts": counts, "sources": sources, "source_rows_invalid": bad,
        "workspaces": [os.path.basename(os.path.normpath(r)) for r in ws_roots],
        "axes": _axes(items, metrics, idx), "items": items,
        "targets": _targets(idx), "axis_names": _axes_on(idx), "question_ids": sorted(idx["questions"]) if idx else [],
        "notes": {"revisit_file": REVISIT_FILE_NOTE}, "cleared": n_cleared, "synonyms_filtered": n_syn_filtered, "previews": previews,
    }
    if reset:
        io.write_json(cleared_path, cleared)
    io.write_json(os.path.join(out_dir, DOC), doc)
    io.write_text(os.path.join(out_dir, SCREEN), render(doc))
    return doc


def render(doc):
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        tpl = f.read()
    if screen.DATA_MARK not in tpl:
        raise ValueError("TEMPLATE_MARK_MISSING")
    return tpl.replace(screen.DATA_MARK, screen.embed(doc), 1)


# ---- 브라우저로 열기(--open) ----------------------------------------------------------

def open_board(target):
    """보드(서버 주소 또는 html 파일)를 기본 브라우저로 연다. 반환: None 또는 사유 코드.
    BEOL_NO_BROWSER=1이거나 디스플레이가 없으면 열지 않고 주소만 출력한다(None)."""
    from domain_engrbot import serve as serve_mod

    url = target if "://" in str(target) else Path(os.path.abspath(target)).as_uri()
    if serve_mod.no_browser():
        print("[taxonomy-board] NO_BROWSER 브라우저로 직접 여세요: %s" % url, flush=True)
        return None
    try:
        return None if webbrowser.open(url) else "BROWSER_NOT_FOUND"
    except webbrowser.Error:
        return "OPEN_FAILED"


# ---- 명령 ----------------------------------------------------------------------

def workspace_roots(names=None, root=ws_mod.ROOT):
    """대상 작업 폴더(절대 경로, 이름순). names가 없으면 root 아래 work.sqlite가 있고 _·.으로 시작하지 않는 폴더 전부."""
    if names:
        out = []
        for n in names:
            p = n if os.path.isdir(n) else os.path.join(root, n)
            if not os.path.isdir(p):
                raise model.BundleError("WORKSPACE_NOT_FOUND")
            out.append(os.path.abspath(p))
        return sorted(set(out), key=lambda p: os.path.basename(os.path.normpath(p)))
    if not os.path.isdir(root):
        return []
    return [os.path.join(root, n) for n in sorted(os.listdir(root))
            if not n.startswith(("_", ".")) and os.path.isfile(os.path.join(root, n, "work.sqlite"))]


def _ledger_dir(ws_roots):
    """domain_engrbot 기본 policy(defaults/policy.json)의 ledger.dir을 반영한다. QaPaths는 만들지 않는다."""
    default = paths.data_path(ledger.WORKSPACES_DIR, "ledger")
    try:
        return ledger.ledger_dir(ws_roots[0] if ws_roots else default, policy_mod.default_policy())
    except ledger.LedgerError as e:
        if e.reason_code == "LEGACY_DATA_DIR":
            raise  # 옛 폴더가 남았는데 새 폴더(비어 있을 수 있음)로 조용히 넘어가지 않는다
        return default


def out_dir_warning(out_dir):
    """출력 폴더가 저장소 안이면서 workspaces/ 밖이면 OUT_DIR_NOT_IGNORED(git에 올라갈 수 있다)."""
    def inside(child, parent):
        try:
            return os.path.commonpath([os.path.normcase(os.path.abspath(child)),
                                       os.path.normcase(os.path.abspath(parent))]) == os.path.normcase(
                os.path.abspath(parent))
        except ValueError:
            return False
    if inside(out_dir, io.CODE_ROOT) and not inside(out_dir, os.path.join(io.CODE_ROOT, "workspaces")):
        return "OUT_DIR_NOT_IGNORED"
    return None


def _label(path):
    p = os.path.abspath(path)
    try:
        rel = os.path.relpath(p, io.CODE_ROOT)
    except ValueError:
        return os.path.basename(p)
    return os.path.basename(p) if rel.startswith("..") else rel.replace("\\", "/")


def main_cli(args, say):
    """건수·코드·화면 상대 경로만 낸다. taxonomy.json을 못 읽어도 종료 코드는 0이다(상태 unknown)."""
    try:
        roots = workspace_roots(getattr(args, "workspace", None))
    except model.BundleError as e:
        say("[오류] %s" % e.reason_code)
        return 1
    tax_path = os.path.abspath(args.taxonomy) if getattr(args, "taxonomy", None) else DEFAULT_TAXONOMY
    out_dir = os.path.abspath(args.out_dir) if getattr(args, "out_dir", None) else OUT_DIR
    if out_dir_warning(out_dir):
        say("[taxonomy-board] %s" % out_dir_warning(out_dir))
    reset = bool(getattr(args, "reset", False))
    try:
        led = _ledger_dir(roots)
    except ledger.LedgerError as e:
        say("[오류] %s" % e.reason_code)
        return 1
    doc = build(roots, tax_path, out_dir, ledger_dir=led, reset=reset, questions_dir=qmodel.qdir(led))
    if reset:
        say("[taxonomy-board] 초기화: %d건을 화면에서 뺐다. 새 실행에서 다시 올라오는 제안만 다시 보인다(되돌리기: %s 삭제)."
            % (doc["cleared"], CLEARED))
    elif doc["cleared"]:
        say("[taxonomy-board] 초기화로 숨긴 항목 %d" % doc["cleared"])
    if doc.get("synonyms_filtered"):
        say("[taxonomy-board] 엄밀한 동의어 기준으로 뺀 봇 동의어 후보 %d" % doc["synonyms_filtered"])
    rej = collections.Counter(it["status_note"] for it in doc["items"] if it["status"] == "rejected")
    if rej:
        say("[taxonomy-board] 기각으로 검토에서 뺀 제안 %d (rejected 목록 %d · 보드에서 기각 %d · Domain-Engr-bot 기각 %d)" % (
            sum(rej.values()), rej["rejected 목록에 있음"], rej["보드에서 기각함"], rej["Domain-Engr-bot에서 기각"]))
        fresh = sum(1 for it in doc["items"] if it["status"] == "rejected" and it.get("fresh_human"))
        if fresh:
            say("[taxonomy-board] 기각한 제안 중 새 사람·엔지니어 출처가 붙은 것 %d (기각 구역에 '새 사람 출처' 배지)" % fresh)
    c, s = doc["counts"], doc["sources"]
    say("[taxonomy-board] 항목 %d (미반영 %d · 반영됨 %d · 기각 %d · 먼저 할 일 %d · 확인 불가 %d), 작업 폴더 %d, 출처 %s" % (
        len(doc["items"]), c["open"], c["done"], c["rejected"], c["blocked"], c["unknown"], len(roots),
        "·".join("%s %d" % (k, s[k]) for k in SOURCE_CODES)))
    t = doc["taxonomy"]
    if t["read_code"]:
        say("[taxonomy-board] %s (상태 확인 불가)" % t["read_code"])
    if t["issues"]:
        say("[taxonomy-board] TAXONOMY_PARSE_ERROR %d건(화면 맨 위에 시트·행·코드)" % len(t["issues"]))
    if doc["source_rows_invalid"]:
        say("[taxonomy-board] SOURCE_ROW_INVALID %d" % doc["source_rows_invalid"])
    html_path = os.path.join(out_dir, SCREEN)
    say("[taxonomy-board] 화면: %s" % _label(html_path))
    if getattr(args, "serve", False):
        def rebuild():
            return build(roots, tax_path, out_dir, ledger_dir=led, questions_dir=qmodel.qdir(led))["counts"]
        return serve_board(html_path, out_dir, rebuild, tax_path, getattr(args, "open", False), say)
    if getattr(args, "open", False):
        code = open_board(html_path)
        if code:
            say("[taxonomy-board] OPEN_FAILED %s" % code)
    return 0


def board_handlers(out_dir, tax_path, rebuild, now=None):
    """보드 서버의 미리보기·반영 처리. 반환: (preview(payload), finalize(payload)) → (HTTP 상태, 응답 dict).
    버전이 달라 거절하면 보드를 다시 만들어 둔다(화면을 새로고침하면 새 버전으로 이어 한다).
    저장한 뒤 보드 다시 만들기가 실패하면 200에 counts None, rebuild_failed(예외 이름)를 붙인다(쓴 것은 그대로다)."""
    def run(payload, preview):
        try:
            res = apply_marks(out_dir, tax_path, payload, preview, now=now)
        except BoardRefused as e:
            if e.code == "TAXONOMY_CHANGED":
                try:
                    rebuild()
                except Exception:   # 다시 만들기 실패는 거절 응답을 바꾸지 않는다
                    pass
            body = {"ok": False, "code": e.code, "issues": e.issues}
            if e.detail:
                body["detail"] = e.detail
            return e.status, body
        if not preview:
            try:
                res["counts"] = rebuild()
            except Exception as e:   # 이미 저장했으니 실패 응답으로 바꾸지 않는다. 사유는 예외 이름만
                res["counts"], res["rebuild_failed"] = None, type(e).__name__
        return 200, res
    return (lambda payload: run(payload, True)), (lambda payload: run(payload, False))


def serve_board(html_path, out_dir, rebuild, tax_path, open_browser, say, port=None):
    """보드 서버(127.0.0.1)를 열고 Ctrl+C까지 기다린다. 화면의 '최종 완료'가 미리보기(/board/preview)를 거쳐
    taxonomy.json에 쓰고(/board/finalize) 보드를 새로 만든다. open_browser면 서버 주소를 브라우저로 연다."""
    import threading
    from domain_engrbot import serve as serve_mod

    preview, finalize = board_handlers(out_dir, tax_path, rebuild)
    try:
        srv = serve_mod.make_board_server(html_path, preview, finalize,
                                          serve_mod.BOARD_PORT if port is None else port)
    except OSError as e:
        if port is not None:
            if trace.port_in_use(e):
                return trace.port_fail("M12", port)
            raise
        srv = serve_mod.make_board_server(html_path, preview, finalize, 0)
    url = "http://127.0.0.1:%d/" % srv.server_address[1]
    say("[taxonomy-board] 보드 서버: %s (최종 완료 → 미리보기 → %s에 쓰기, 끝내려면 Ctrl+C)"
        % (url, os.path.basename(tax_path)))
    trace.serving("M12", url)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    if open_browser:
        code = open_board(url)
        if code:
            say("[taxonomy-board] OPEN_FAILED %s" % code)
    try:
        while th.is_alive():
            th.join(0.5)
    except KeyboardInterrupt:
        trace.aborted("M12")
    finally:
        srv.shutdown()
        srv.server_close()
    return 0
