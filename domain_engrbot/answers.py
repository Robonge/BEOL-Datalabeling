"""질문 루프의 답 반영(questions apply). 설계는 domain_engrbot/docs/plan-question-loop.md 5.2절과 8절이다.

질문 화면이 qa/inbox에 저장한 답 파일(engr_answers_<set_id>.json)을 읽어, 사람이 확정한 초안만 반영한다.
- rule 초안: pattern_id가 그 질문의 패턴이고 지금 후보·승인분이면 그 패턴(FR-)을 승인하고 문장을 확정 문장으로 바꾼다.
  그 밖에는 MANUAL 규칙(QR-)으로 승인 파일에 더한다. labelbot이 그대로 읽는다(labelbot.feedback._rules_for_run).
- taxonomy 초안: 질문 폴더 taxonomy_proposals.jsonl에 한 줄(taxonomy 수정 보드의 출처 S7). taxonomy.json 반영은 taxonomy 보드가 사람 확정 뒤에 한다.
- example 초안: 그 질문의 사례 후보(EX-)일 때만 승인한다.
- 답함·묻지 않음 질문의 패턴 중 승인 파일에 없는 것은 기각(종결)한다. 승인을 파일 전체에서 먼저 하고 종결은 나중에 한다.

답 파일은 질문 단위로 받는다(set_id가 달라도 거부하지 않는다). 지금 열려 있지 않은 질문은 not_open으로 건너뛴다.
쓰기는 장부 잠금 안에서 승인 파일 → taxonomy_proposals → answers.jsonl → asked.json → questions.json → 후보 리포트 순이다.
승인 파일 저장 전에 예외가 나면 아무 파일도 바꾸지 않는다. 반환은 건수·ID·코드만이고 출력은 하지 않는다.
"""
import copy
import os

from domain_engrbot import io, labeling_rules as lr, ledger, model, qmodel
from domain_engrbot.adapters import labelbot_ws

ORIGINS = ("llm", "edited", "human")   # 화면이 확정 초안에 넣는 출처(그 밖이면 llm)
DEFAULT_CAP = 30                        # labelbot pipeline.json feedback.max_rules 기본값
ANSWERS_PREFIX = "engr_answers_"


class AnswersError(Exception):
    def __init__(self, reason_code):
        Exception.__init__(self, reason_code)
        self.reason_code = reason_code


def _build_screen(qd, d, policy, roots=None):
    """질문 화면을 다시 만든다(question_screen이 늦게 import되게 이 한 곳에서만 부른다)."""
    from domain_engrbot import question_screen

    return question_screen.build(qd, d, policy=policy, roots=roots)


def _screen_errors():
    """화면 다시 만들기에서 받아 notes로 돌릴 예외(반영은 이미 끝났으므로 실패로 내지 않는다)."""
    from domain_engrbot import question_screen

    return (question_screen.QuestionScreenError, qmodel.QModelError, ledger.LedgerError, OSError, ValueError)


# ---- 답 파일 ---------------------------------------------------------------------

def latest_answers(inbox):
    """inbox의 engr_answers_*.json 중 수정 시각이 가장 늦은 것(같으면 이름이 큰 것). 없으면 ANSWERS_NOT_FOUND."""
    names = []
    if os.path.isdir(inbox):
        names = [n for n in os.listdir(inbox) if n.startswith(ANSWERS_PREFIX) and n.lower().endswith(".json")
                 and os.path.isfile(os.path.join(inbox, n))]
    if not names:
        raise AnswersError("ANSWERS_NOT_FOUND")
    return os.path.join(inbox, max((os.path.getmtime(os.path.join(inbox, n)), n) for n in names)[1])


def read_answers(path, snapshot_dir=None):
    """답 파일을 read_input으로 읽는다. 크기 상한은 읽기 전에 본다."""
    try:
        size = os.path.getsize(path)
    except OSError:
        raise AnswersError("ANSWERS_NOT_FOUND")
    if size > qmodel.MAX_ANSWER_BYTES:
        raise AnswersError("ANSWERS_TOO_LARGE")
    try:
        return io.read_json_input(path, snapshot_dir)
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise AnswersError("ANSWERS_JSON_INVALID")
    except OSError:
        raise AnswersError("ANSWERS_READ_FAILED")


def parse(doc):
    """답 파일 → 답 목록(형식만 본다). 형식이 틀리면 ANSWERS_FORMAT_INVALID, 같은 질문이 두 번이면 ANSWERS_DUPLICATE_ID."""
    if not isinstance(doc, dict) or doc.get("kind") != qmodel.ANSWERS_KIND or not isinstance(doc.get("answers"), list):
        raise AnswersError("ANSWERS_FORMAT_INVALID")
    out, seen = [], set()
    for a in doc["answers"]:
        if (not isinstance(a, dict) or not qmodel.valid_question_id(a.get("question_id"))
                or a.get("action") not in qmodel.ACTIONS or not isinstance(a.get("confirmed", []), list)):
            raise AnswersError("ANSWERS_FORMAT_INVALID")
        if a["question_id"] in seen:
            raise AnswersError("ANSWERS_DUPLICATE_ID")
        seen.add(a["question_id"])
        opt = a.get("option_id")
        out.append({"question_id": a["question_id"], "action": a["action"],
                    "option_id": opt if isinstance(opt, str) and len(opt) <= 8 else None,
                    "option_label": qmodel.soft_text(a.get("option_label"), qmodel.LABEL_MAX) or "",
                    "free_text": qmodel.soft_text(a.get("free_text"), qmodel.FREE_MAX) or "",
                    "confirmed": a.get("confirmed") or []})
    return out


def _drafts(answer, q, axes=None):
    """확정 초안 → (정리한 초안 목록(origin 포함), [사유 코드]). 그 질문의 사례가 아닌 example은 틀린 초안이다.
    rule은 범위(축 이름 · 축=값 · 질문 ID)가 없으면 RULE_SCOPE_MISSING이다."""
    good, bad = [], []
    for raw in answer["confirmed"]:
        d, code = qmodel.check_draft(raw, axes, require_scope=True)
        if d is not None and d["type"] == "example" and d["example_id"] not in (q.get("examples") or []):
            d, code = None, "EXAMPLE_NOT_IN_QUESTION"
        if d is None:
            bad.append(code)
            continue
        origin = raw.get("origin")
        d["origin"] = origin if origin in ORIGINS else "llm"
        good.append(d)
    return good, bad


# ---- 반영 ----------------------------------------------------------------------

def manual_rule_id(fingerprint, stage, target, text):
    """MANUAL 규칙 ID. 단계·대상도 넣는다(문장이 같고 단계가 다른 초안이 하나로 합쳐지지 않게)."""
    return "QR-" + model.sha256_text("\n".join((fingerprint, stage, target, text)))[:10]


def _rule_stage(r):
    """labelbot.feedback._rules_for_run과 같은 단계 판정."""
    if r.get("kind") in lr.ANSWER_KINDS:
        return "label"
    if r.get("kind") == "MANUAL":
        if r.get("stage") in qmodel.STAGES:
            return r["stage"]
        return "label" if r.get("target") == "label" else "classify"
    return "classify"


def enabled_rules(doc):
    """켜진 유효 규칙 수를 단계별로 센다."""
    out = {"classify": 0, "label": 0}
    for r in doc["rules"]:
        if lr.valid_rule(r) and r.get("enabled", True):
            out[_rule_stage(r)] += 1
    return out


def _cap(ws_root):
    try:
        return max(0, int((labelbot_ws.read_config(ws_root).get("feedback") or {}).get("max_rules") or DEFAULT_CAP))
    except (model.BundleError, ValueError, TypeError, AttributeError, OSError):
        return DEFAULT_CAP


def _axes(ws_root):
    """활성 축 이름 목록. taxonomy를 읽을 수 없으면(어떤 예외든) None(축 이름 존재 검사만 건너뛴다)."""
    try:
        snap = labelbot_ws.snapshot(labelbot_ws.load_taxonomy(ws_root, labelbot_ws.read_config(ws_root)))
    except Exception:  # noqa: BLE001 - 범위 검사만 건너뛴다. 본문·경로는 남기지 않는다
        return None
    return [a["name"] for a in snap["axes"] if a["active"]]


def _manual_rule(doc, q, draft, set_id, at, by, res):
    """rule 초안 하나 → MANUAL 규칙(QR-). stage는 classify|label, target은 그 범위(1차는 축 이름, 3차는 축=값 또는 질문 ID)."""
    target = draft["target"]
    if not target:   # 사라진 패턴(PATTERN_GONE)의 문장은 범위가 없으면 규칙으로 만들지 않는다
        res["rule_scope_missing"] += 1
        res["invalid"].append({"question_id": q["question_id"], "code": "RULE_SCOPE_MISSING"})
        return
    rid = manual_rule_id(q.get("fingerprint") or q["question_id"], draft["stage"], target, draft["text"])
    if any(isinstance(r, dict) and r.get("rule_id") == rid for r in doc["rules"]):
        # 이미 같은 규칙이 있다(같은 질문·단계·대상·문장을 다시 확정). ID에 문장이 들어가므로 고칠 것이 없고,
        # 사람이 꺼 둔 규칙이어도 켜지 않고 그대로 둔다.
        return
    impact = q.get("impact") if isinstance(q.get("impact"), dict) else {}
    count = impact.get("records") if isinstance(impact.get("records"), int) else 0
    rule = {"rule_id": rid, "kind": "MANUAL", "stage": draft["stage"], "target": target, "from": "", "to": "", "count": count,
            "text": draft["text"], "enabled": True, "approved_at": at, "approved_by": by,
            "question_id": q["question_id"], "set_id": set_id, "origin": draft["origin"]}
    if rid in doc["rejected"]:
        doc["rejected"].remove(rid)   # 승인 취소했던 규칙을 사람이 다시 확정했다
    doc["rules"].append(rule)
    doc["rules"].sort(key=lambda r: str(r.get("rule_id")) if isinstance(r, dict) else "")
    res["rules"] += 1


def _proposal(draft, set_id, qid, at):
    row = {k: draft[k] for k in ("kind",) + qmodel.NAME_KEYS + qmodel.LONG_KEYS + ("memo", "values", "origin")}
    row.update(proposal_id=qmodel.proposal_id(draft), set_id=set_id, question_id=qid, at=at)
    return row


def _history_row(a, q, drafts, set_id, answers_set_id, reviewer, at, by):
    return {"at": at, "by": by, "set_id": set_id, "answers_set_id": answers_set_id, "reviewer": reviewer,
            "question_id": q["question_id"], "fingerprint": q.get("fingerprint"), "goal": q.get("goal"),
            "topic": q.get("topic"), "text": q.get("text"), "action": a["action"],
            "option_id": a["option_id"], "option_label": a["option_label"], "free_text": a["free_text"],
            "confirmed": drafts}


def apply(paths, policy, answers_path=None, qd=None, rules_path=None, by="screen", now=None):
    """답 파일을 반영한다. 반환(건수·ID·코드만):
    {"answered", "dismissed", "skipped", "rules", "patterns_approved", "patterns_closed", "taxonomy", "examples",
     "rule_scope_missing"(범위가 없어 거부한 rule 초안 수), "invalid": [{"question_id", "code"}], "not_open": [ID], "remaining", "enabled_rules": {"classify", "label"},
     "cap", "notes": [코드]}

    오류는 AnswersError(reason_code): ANSWERS_NOT_FOUND · ANSWERS_TOO_LARGE · ANSWERS_JSON_INVALID ·
    ANSWERS_FORMAT_INVALID · ANSWERS_DUPLICATE_ID · ANSWERS_READ_FAILED · QUESTIONS_NOT_FOUND · PROPOSALS_INVALID와,
    장부·질문 묶음·승인 파일의 코드(QUESTIONS_INVALID · ASKED_INVALID · RULES_JSON_INVALID · LEDGER_LOCKED 등).
    """
    try:
        return _apply(paths, policy, answers_path, qd, rules_path, by, now)
    except (qmodel.QModelError, lr.LabelingRulesError, ledger.LedgerError) as e:
        raise AnswersError(e.reason_code)


def _apply(paths, policy, answers_path, qd, rules_path, by, now):
    d = ledger.ledger_dir(paths.root, policy)
    qd = qd or qmodel.qdir(d)
    rules_path = rules_path or lr.RULES_PATH
    cfg = lr.config(policy)
    at = now or model.now_iso()
    path = answers_path or latest_answers(paths.inbox)
    raw = read_answers(path, paths.inputs_dir)
    items = parse(raw)
    answers_sha = model.hash_obj(raw)   # 다시 열린 질문에 같은 답 파일이 또 반영되지 않게 asked에 남긴다
    answers_set_id = raw.get("set_id") if isinstance(raw.get("set_id"), str) else ""
    reviewer = qmodel.soft_text(raw.get("reviewer"), qmodel.NAME_MAX) or ""
    cap = _cap(paths.root)
    axes = _axes(paths.root)
    res = {"answered": 0, "dismissed": 0, "skipped": 0, "rules": 0, "patterns_approved": 0, "patterns_closed": 0,
           "taxonomy": 0, "examples": 0, "rule_scope_missing": 0, "invalid": [], "not_open": [], "remaining": 0,
           "enabled_rules": {"classify": 0, "label": 0}, "cap": cap, "notes": []}
    rebuilt = False
    with ledger.locked(d):
        qset = qmodel.load_set(qd)
        if qset is None:
            raise AnswersError("QUESTIONS_NOT_FOUND")
        asked = qmodel.load_asked(qd)
        before = lr.load_rules(rules_path)
        doc = copy.deepcopy(before)
        set_id = qset["set_id"]
        qmap = qmodel.question_map(qset)
        prop_path = os.path.join(qd, qmodel.PROPOSALS)
        try:
            have_props = {r.get("proposal_id") for r in io.read_own_jsonl(prop_path) if isinstance(r, dict)}
        except (ValueError, UnicodeDecodeError):
            raise AnswersError("PROPOSALS_INVALID")
        # 질문 단위로 거른다: 열려 있지 않음 → not_open, 유효한 확정 초안이 없는 답 → invalid(열린 채).
        # 다시 열린 질문은 예전 답이 또 반영되지 않게 한다: 그 질문을 닫았던 답 파일과 같은 파일이거나,
        # 다시 열린 묶음(지금 set_id)에서 저장한 답 파일이 아니면 not_open이다.
        done = []   # (답, 질문, 확정 초안)
        for a in items:
            q = qmap.get(a["question_id"])
            old = qmodel.closed_by(asked, q) if q is not None else None
            stale = old is not None and (old.get("answers_sha") == answers_sha
                                         or (q.get("reopened") is True and answers_set_id != set_id))
            if q is None or qmodel.is_closed(asked, q) or stale:
                res["not_open"].append(a["question_id"])
                continue
            if a["action"] == "skip":
                res["skipped"] += 1
                continue
            drafts = []
            if a["action"] == "answer":
                drafts, bad = _drafts(a, q, axes)
                res["rule_scope_missing"] += bad.count("RULE_SCOPE_MISSING")
                res["invalid"] += [{"question_id": q["question_id"], "code": c} for c in bad]
                # 확정은 rule·taxonomy 초안이 1개 이상 있어야 한다(사례만으로는 답이 아니다. 화면도 같은 기준)
                if not any(dr["type"] in ("rule", "taxonomy") for dr in drafts):
                    res["invalid"].append({"question_id": q["question_id"], "code": "NO_CONFIRMED_DRAFT"})
                    continue
            done.append((a, q, drafts))
        # (1) 승인을 파일 전체에서 먼저 한다: 패턴 승인·문장 교체, MANUAL 규칙, 사례.
        # 쓸 수 있는 패턴은 그 질문의 패턴이면서 지금 승인분이거나 승인 대기 후보인 FR뿐이다. 기각했거나 후보 기준
        # 아래로 내려간 FR은 되살리지 않고 MANUAL 규칙으로 넣는다(PATTERN_GONE).
        have = {r.get("rule_id") for r in doc["rules"] if isinstance(r, dict)}
        cand_ids = {r["rule_id"] for r in lr.candidates(d, doc, cfg)["rules"]} if done else set()
        fr_text, ex_ids, new_props = {}, [], []
        for a, q, drafts in done:
            for dr in drafts:
                pid = dr.get("pattern_id")
                if dr["type"] == "rule" and pid and pid in (q.get("patterns") or []) and (pid in have or pid in cand_ids):
                    fr_text[pid] = dr["text"]   # 한 FR에 확정 문장이 여럿이면 파일에서 뒤에 온 것을 쓴다
                elif dr["type"] == "rule":
                    if pid:
                        res["notes"].append("PATTERN_GONE")
                    _manual_rule(doc, q, dr, set_id, at, by, res)
                elif dr["type"] == "example":
                    if dr["example_id"] not in ex_ids:
                        ex_ids.append(dr["example_id"])
                else:
                    row = _proposal(dr, set_id, q["question_id"], at)
                    if row["proposal_id"] not in have_props:
                        have_props.add(row["proposal_id"])
                        new_props.append(row)
        # 승인은 FR·EX 각각 한 번에 부른다(잠금 안에서 장부를 여러 번 다시 읽지 않게)
        to_approve = [p for p in fr_text if p not in have]
        if to_approve:
            r = lr.apply_decision(d, doc, "approve", cfg, ids=to_approve, by=by)
            res["patterns_approved"] = len(to_approve) - len(r["unknown_ids"])
        rules = {r.get("rule_id"): r for r in doc["rules"] if isinstance(r, dict)}
        for pid, text in fr_text.items():
            if pid in rules and rules[pid].get("text") != text:
                rules[pid].update(text=text, edited_at=at, edited_by=by)
        # 사람이 기각한 사례는 답에 딸려 와도 되살리지 않는다(apply_decision은 기각 목록에서도 지운다)
        if any(i in doc["rejected_examples"] for i in ex_ids):
            ex_ids = [i for i in ex_ids if i not in doc["rejected_examples"]]
            res["notes"].append("EXAMPLE_REJECTED")
        if ex_ids:
            r = lr.apply_decision(d, doc, "approve", cfg, ids=ex_ids, by=by)
            res["examples"] = r["examples"]
            if r["unknown_ids"]:
                res["notes"].append("EXAMPLE_GONE")
        # (2) 종결: 답함·묻지 않음 질문의 패턴 중 지금 승인 파일에 없는 것만 기각한다(이미 승인된 FR은 그대로)
        approved = {r.get("rule_id") for r in doc["rules"] if isinstance(r, dict)}
        close = []
        for _a, q, _ds in done:
            close += [p for p in q.get("patterns") or [] if p not in approved and p not in doc["rejected"]
                      and p not in close]
        if close:
            r = lr.apply_decision(d, doc, "reject", cfg, ids=close, by=by)
            res["patterns_closed"] = len(close) - len(r["unknown_ids"])
        if done:
            if io.dumps(doc) != io.dumps(before):
                io.append_jsonl(os.path.join(qd, qmodel.RULES_HISTORY), {"at": at, "set_id": set_id, "doc": before})
                lr.save_rules(doc, rules_path)
            for row in new_props:
                io.append_jsonl(prop_path, row)
            res["taxonomy"] = len(new_props)
            closed = set()
            for a, q, drafts in done:
                io.append_jsonl(os.path.join(qd, qmodel.ANSWERS_LOG),
                                _history_row(a, q, drafts, set_id, answers_set_id, reviewer, at, by))
                bucket, other = ("answered", "dismissed") if a["action"] == "answer" else ("dismissed", "answered")
                asked[other].pop(q["fingerprint"], None)
                asked[bucket][q["fingerprint"]] = qmodel.asked_entry(
                    q, set_id, at, answers_sha, seen_at=q.get("created_at") or qset.get("generated_at"))
                res["answered" if a["action"] == "answer" else "dismissed"] += 1
                closed.add(q["question_id"])
            qmodel.save_asked(qd, asked)
            qset["questions"] = [q for q in qset["questions"] if q["question_id"] not in closed]
            qmodel.save_set(qd, qset)
            lr.write_candidates_unlocked(d, doc, cfg)
            rebuilt = True
        res["remaining"] = len(qset["questions"])
    # 화면은 잠금을 푼 뒤 다시 만든다(화면 모듈이 장부를 읽어도 잠금이 겹치지 않게).
    # 반영은 이미 저장됐으므로 화면 실패는 notes로만 알린다.
    if rebuilt:
        try:
            _build_screen(qd, d, policy, roots={os.path.basename(paths.root.rstrip("\\/")): paths.root})
        except _screen_errors():
            res["notes"].append("SCREEN_REBUILD_FAILED")
    res["enabled_rules"] = enabled_rules(doc)
    if any(n > cap for n in res["enabled_rules"].values()):
        res["notes"].append("RULES_OVER_CAP")
    res["notes"] = list(dict.fromkeys(res["notes"]))
    return res
