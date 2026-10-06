"""승인된 규칙 관리: 승인 화면(labeling_review.html)과 결정 반영(apply). 사용자 결정(2026-10-05, 2026-10-06 D5).

라벨링 규칙·사례의 승인은 Domain-Engr-bot(/BEOL-labeling-Domain-Engr-bot)에서만 한다. BEOL-labeling은 승인 파일
(taxonomy/labeling_rules.json)을 읽기만 한다. 새 규칙·사례 후보는 질문 루프(질문 화면 → answers.apply)에서 다루고,
이 화면에는 이미 승인된 규칙·사례의 관리만 남긴다(plan-question-loop.md 5.2·8.4절).

- review: 장부 폴더에 labeling_review.html을 쓴다. 서버 없이 파일로 열고, 승인된 규칙·사례마다 켜기·끄기,
  문장 수정, 승인 취소(기각)를 고른다. 승인 뒤 확정 라벨이 바뀐 사례(갱신 대기)는 승인(갱신)·기각만 고른다.
  화면은 결정 JSON(labeling_rules_decisions)을 내려받기만 한다. 판정 로직은 넣지 않는다.
- apply: 결정 JSON을 read_input으로 읽어 labeling_rules.apply_decision()으로 승인·기각하고, 문장·켜짐을 승인 파일에 적는다.
  결정 이력은 장부 폴더 labeling_decisions.jsonl에 ID·동작·결과만 남긴다(문장은 승인 파일에만 있다).
- 화면에는 사람이 검수 화면에서 남긴 근거 인용·이유(evidence.jsonl)가 들어간다(사용자 결정 E3). 그래서 화면 파일은
  장부 폴더(git 제외)에만 쓰고, 콘솔에는 건수만 낸다. 결정 파일과 승인 파일에는 본문·인용이 없다(ID·동작·규칙 문장만).
- 결정 파일은 그 화면에서 만든 것만 받는다: digest가 지금 화면과 같아야 하고(DECISIONS_STALE), 화면에 있던 ID에
  그 자리에서 고를 수 있던 동작만 받는다(DECISIONS_ID_NOT_ON_SCREEN). 어긋나면 파일 전체를 반영하지 않는다.
"""
import os
import re

from domain_engrbot import io, labeling_rules as lr, ledger, model, screen

TEMPLATE_PATH = os.path.join(screen.PKG_ROOT, "screens", "labeling_review.html")
SCREEN = "labeling_review.html"
LOG = "labeling_decisions.jsonl"
DECISIONS_KIND = "labeling_rules_decisions"
ACTIONS = ("approve", "reject", "enable", "disable", "edit")
MAX_DECISIONS = 2000
MAX_BYTES = 1024 * 1024   # 결정 파일 상한(읽기 전에 본다)
MAX_ID_LEN = 128
MAX_EVIDENCE_RECORDS = lr.MAX_REFS   # 규칙 카드에 보이는 근거 레코드 수
_ID = re.compile(r"[^\x00-\x1f\x7f]{1,%d}" % MAX_ID_LEN)
# 규칙 문장에 넣지 않는 글자: 줄바꿈·탭 밖의 제어 문자, 폭 없는 문자, 방향 제어 문자
_BAD_TEXT = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏‪-‮⁦-⁩]")


class ReviewError(Exception):
    def __init__(self, reason_code):
        Exception.__init__(self, reason_code)
        self.reason_code = reason_code


# ---- 화면 데이터 -----------------------------------------------------------------

def _evidence_view(row):
    """evidence.jsonl 행 → 화면 표시용 근거(위치 종류·슬라이드·인용·이유). 화면 안에서만 쓴다."""
    if not row:
        return None
    rid = row.get("record_id")
    items = [{"kind": ledger.evidence_kind(x, rid), "slide_no": x.get("slide_no"), "quote": x.get("quote") or ""}
             for x in row.get("evidence") or [] if isinstance(x, dict)]
    return {"record_id": rid, "field": row.get("field"), "items": items, "reason": row.get("reason")}


def _rule_evidence(case_ids, ev):
    return [v for v in (_evidence_view(ev.get(c)) for c in (case_ids or [])[:MAX_EVIDENCE_RECORDS]) if v]


def _example_evidence(e, ev):
    """사례의 고친 축마다 근거(없으면 그 축은 뺀다). 사례 행의 (작업 폴더, 실행, 레코드, 축)으로 case_id를 다시 만든다."""
    out = {}
    for axis in sorted(e.get("corrected") or {}):
        cid = model.hash_obj([e.get("source_ws"), e.get("labeler_run_id"), e.get("record_id"), "axis:" + axis])[:16]
        v = _evidence_view(ev.get(cid))
        if v:
            out[axis] = v
    return out


def _approved_rule_view(r, now, ev):
    now = now or {}
    return {"rule_id": r.get("rule_id"), "kind": r.get("kind"), "target": r.get("target", ""),
            "from": r.get("from", ""), "to": r.get("to", ""), "count": r.get("count"), "count_now": now.get("count"),
            "evidence_count": now.get("evidence_count", 0), "evidence_mix": now.get("evidence_mix") or {},
            "evidence": _rule_evidence(now.get("evidence_cases"), ev),
            "text": r.get("text", ""), "enabled": bool(r.get("enabled", True)), "valid": bool(lr.valid_rule(r)),
            "approved_at": r.get("approved_at", ""), "edited_at": r.get("edited_at", "")}


def _approved_example_view(e, ev):
    return {"example_id": e.get("example_id"), "kind": e.get("kind"), "source_ws": e.get("source_ws"),
            "record_id": e.get("record_id"), "corrected": e.get("corrected") or {},
            "confirmed": e.get("confirmed") or [], "final_axes": e.get("final_axes") or {}, "enabled": bool(e.get("enabled", True)),
            "valid": bool(lr.valid_example(e)), "approved_at": e.get("approved_at", ""),
            "evidence": _example_evidence(e, ev)}


def data(d, cfg, path=None):
    """화면에 넣을 데이터. 근거 인용·이유가 들어간다(화면 파일만). digest는 승인 상태·갱신 대기·근거가 같으면 같다.

    pending_rules는 항상 빈 목록이다(새 규칙 후보는 질문 화면에서 다룬다). pending_examples는 승인 뒤 확정 라벨이
    바뀐 사례(update=True)만이다. 새 사례 후보(update=False)는 화면에 없다.
    """
    doc = lr.load_rules(path)
    cands = lr.candidates(d, doc, cfg)
    now = lr.all_rules(lr._latest_cases(d), cfg["min_count"])
    ev = {r["case_id"]: r for r in ledger.read_evidence(d)}
    pending_rules = []
    pending_examples = [dict(e, evidence=_example_evidence(e, ev)) for e in cands["examples"] if e.get("update")]
    approved_rules = [_approved_rule_view(r, now.get(r.get("rule_id")), ev) for r in doc["rules"] if isinstance(r, dict)]
    # 갱신 대기 사례는 승인된 사례 목록에서 빼고 갱신 대기 묶음에만 둔다(한 ID에 카드 하나, 결정 하나).
    updating = {e["example_id"] for e in pending_examples}
    approved_examples = [_approved_example_view(e, ev) for e in doc["examples"]
                         if isinstance(e, dict) and e.get("example_id") not in updating]
    body = {"pending_rules": pending_rules, "pending_examples": pending_examples,
            "approved_rules": approved_rules, "approved_examples": approved_examples,
            "rejected_rules": len(doc["rejected"]), "rejected_examples": len(doc["rejected_examples"])}
    out = dict(body, kind="labeling_review", min_count=cfg["min_count"], min_evidence=cfg["min_evidence"],
               text_max=lr.TEXT_MAX, ledger=ledger.dir_label(d), digest=model.hash_obj(body)[:16],
               made_at=model.now_iso())
    return out


def build(d, cfg, path=None):
    """장부 폴더에 labeling_review.html을 쓴다. 반환: 화면 데이터(건수 보고용. 근거 인용이 있으니 콘솔에 내지 않는다)."""
    obj = data(d, cfg, path)
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        tpl = f.read()
    if screen.DATA_MARK not in tpl:
        raise ReviewError("TEMPLATE_MARK_MISSING")
    os.makedirs(d, exist_ok=True)
    ledger.replace_text(os.path.join(d, SCREEN), tpl.replace(screen.DATA_MARK, screen.embed(obj), 1))
    return obj


# ---- 결정 반영 -------------------------------------------------------------------

def read_decisions(decisions_path, snapshot_dir=None):
    """결정 JSON을 read_input으로 읽는다. MAX_BYTES를 넘으면 읽기 전에 DECISIONS_TOO_LARGE,
    JSON이 아니거나 너무 깊으면 DECISIONS_JSON_INVALID."""
    try:
        size = os.path.getsize(decisions_path)
    except OSError:
        raise ReviewError("DECISIONS_NOT_FOUND")
    if size > MAX_BYTES:
        raise ReviewError("DECISIONS_TOO_LARGE")
    try:
        return io.read_json_input(decisions_path, snapshot_dir)
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise ReviewError("DECISIONS_JSON_INVALID")


def parse(doc):
    """결정 JSON → [(id, action, text 또는 None)]. 형식이 틀리면 DECISIONS_FORMAT_INVALID.

    ID는 dict 키로만 비교하고 경로·SQL에 쓰지 않으므로 글자를 좁히지 않는다(사람이 쓴 MANUAL 규칙 ID도 받는다).
    길이 1~MAX_ID_LEN, 제어 문자 없음만 본다.
    """
    if not isinstance(doc, dict) or doc.get("kind") != DECISIONS_KIND or not isinstance(doc.get("decisions"), list):
        raise ReviewError("DECISIONS_FORMAT_INVALID")
    if len(doc["decisions"]) > MAX_DECISIONS:
        raise ReviewError("DECISIONS_TOO_MANY")
    out, seen = [], set()
    for x in doc["decisions"]:
        if (not isinstance(x, dict) or not isinstance(x.get("id"), str) or not _ID.fullmatch(x["id"])
                or x.get("action") not in ACTIONS):
            raise ReviewError("DECISIONS_FORMAT_INVALID")
        text = x.get("text")
        if text is not None and not isinstance(text, str):
            raise ReviewError("DECISIONS_FORMAT_INVALID")
        if x["id"] in seen:
            raise ReviewError("DECISIONS_DUPLICATE_ID")
        seen.add(x["id"])
        out.append((x["id"], x["action"], text))
    return out


def check_on_screen(items, screen_data):
    """화면에서 그 ID에 고를 수 있던 동작만 받는다. 승인은 갱신 대기 사례만, 기각은 갱신 대기나 승인된 것,
    켜기·끄기·문장 수정은 승인된 것만. 새 후보 ID는 화면에 없다. 하나라도 어긋나면 DECISIONS_ID_NOT_ON_SCREEN
    (파일 전체를 반영하지 않는다)."""
    pending = ({r["rule_id"] for r in screen_data["pending_rules"]}
               | {e["example_id"] for e in screen_data["pending_examples"]})
    approved = ({r["rule_id"] for r in screen_data["approved_rules"]}
                | {e["example_id"] for e in screen_data["approved_examples"]})
    for i, action, _ in items:
        allowed = pending if action == "approve" else (pending | approved) if action == "reject" else approved
        if i not in allowed:
            raise ReviewError("DECISIONS_ID_NOT_ON_SCREEN")


def _clean_text(text):
    """사람이 고친 규칙 문장. 줄바꿈·탭은 공백 하나로 바꾼다. 비었거나 TEXT_MAX를 넘거나, 그 밖의 제어 문자·폭 없는
    문자·방향 제어 문자가 있거나, 프롬프트 치환 표식({{·}})이 있으면 None."""
    if text is None or _BAD_TEXT.search(text):
        return None
    t = " ".join(text.split())
    if not t or len(t) > lr.TEXT_MAX or "{{" in t or "}}" in t:
        return None
    return t


def apply(d, cfg, decisions_path, path=None, snapshot_dir=None, by="screen"):
    """결정 JSON을 승인 파일에 반영한다. 반환: 건수·ID만 있는 요약.

    파일 단위로 먼저 거른다: 크기·JSON·형식, digest가 지금 화면과 다르면 DECISIONS_STALE, 화면에 없던 ID나
    그 자리에서 고를 수 없던 동작이 있으면 DECISIONS_ID_NOT_ON_SCREEN(아무것도 반영하지 않는다).
    그다음 결정마다 결과 코드 하나(OK, INVALID_TEXT, UNKNOWN_ID, NOT_APPROVED, NOT_APPLIED)를 정하고,
    결정 순서대로 labeling_decisions.jsonl에 남긴다(중간에 실패해도 finally에서 남긴다).
    - 문장이 비었거나 TEXT_MAX를 넘거나 금지 글자가 있으면 그 결정 전체를 하지 않는다(승인·켜기·끄기 모두).
    - 사례(EX-)와 기각에 붙은 문장은 무시한다.
    - UNKNOWN_ID·NOT_APPROVED는 화면 검사 뒤에는 나오지 않아야 하는 방어 코드다(반영 도중 승인 파일이 바뀐 경우).
    """
    raw = read_decisions(decisions_path, snapshot_dir)
    items = parse(raw)
    now = model.now_iso()
    result, texts = {}, {}
    # digest 확인부터 저장까지 같은 장부 잠금 안에서 한다(그 사이에 승인 파일이 바뀌지 않게).
    # 결정은 메모리의 doc 하나에 모두 적용하고 마지막에 한 번만 저장한다(중간 예외면 파일은 그대로다).
    with ledger.locked(d):
        before = lr.load_rules(path)
        now_data = data(d, cfg, path)
        if raw.get("digest") != now_data["digest"]:
            raise ReviewError("DECISIONS_STALE")
        check_on_screen(items, now_data)
        pending_ids = {r["rule_id"] for r in now_data["pending_rules"]} | {e["example_id"] for e in now_data["pending_examples"]}
        had_r = {r.get("rule_id") for r in before["rules"] if isinstance(r, dict)}
        had_e = {e.get("example_id"): e for e in before["examples"] if isinstance(e, dict)}
        had_rej = set(before["rejected"]) | set(before["rejected_examples"])
        res = {"approved_rules": 0, "approved_examples": 0, "rejected_rules": 0, "rejected_examples": 0,
               "edited": 0, "enabled": 0, "disabled": 0, "unknown_ids": [], "invalid_text": [], "not_approved": []}
        for i, action, text in items:
            if action == "reject" or i.startswith("EX-"):
                text = None
            if text is not None:
                texts[i] = _clean_text(text)
                if texts[i] is None:
                    result[i] = "INVALID_TEXT"
                    continue
            if action == "edit" and text is None:
                result[i] = "INVALID_TEXT"
        try:
            doc = lr.load_rules(path)
            changed = False
            # 1) 승인·기각은 labeling_rules.apply_decision 한 곳으로(후보 계산·기존 승인 보존 규칙을 그대로 쓴다).
            for action in ("approve", "reject"):
                ids = [i for i, a, _ in items if a == action and i not in result]
                if not ids:
                    continue
                r = lr.apply_decision(d, doc, action, cfg, ids=ids, by=by)
                changed = changed or r["changed"]
                for i in ids:
                    result[i] = "UNKNOWN_ID" if i in r["unknown_ids"] else "OK"
            has_r = {r.get("rule_id"): r for r in doc["rules"] if isinstance(r, dict)}
            has_e = {e.get("example_id"): e for e in doc["examples"] if isinstance(e, dict)}
            # 2) 문장 수정·켜짐은 승인 파일의 해당 항목에 직접 적는다(사람의 결정을 그대로 옮길 뿐이다).
            for i, action, _ in items:
                if action == "approve" and result.get(i) == "OK":
                    if i in has_e and has_e[i] != had_e.get(i):
                        res["approved_examples"] += 1
                    elif i in has_r and i not in had_r:
                        res["approved_rules"] += 1
                elif action == "reject" and result.get(i) == "OK" and i not in had_rej:
                    res["rejected_examples" if i in doc["rejected_examples"] else "rejected_rules"] += 1
                if action == "reject" or i in result and result[i] != "OK":
                    continue
                target = has_r.get(i) or has_e.get(i)
                if target is None:
                    result[i] = "NOT_APPROVED" if i in pending_ids else "UNKNOWN_ID"
                    continue
                t = texts.get(i)
                if t is not None and t != target.get("text"):
                    target.update(text=t, edited_at=now, edited_by=by)
                    res["edited"] += 1
                    changed = True
                if action in ("enable", "disable"):
                    want = action == "enable"
                    if bool(target.get("enabled", True)) != want:
                        target["enabled"] = want
                        res["enabled" if want else "disabled"] += 1
                        changed = True
                result[i] = "OK"
            if changed:
                lr.save_rules(doc, path)
            lr.write_candidates_unlocked(d, doc, cfg)
            build(d, cfg, path)
        except BaseException:
            # 저장 전 예외면 아무것도 반영되지 않았다: 결정 로그에 OK를 남기지 않는다.
            for i in [i for i, c in result.items() if c != "INVALID_TEXT"]:
                del result[i]
            raise
        finally:
            for i, action, _ in items:
                io.append_jsonl(os.path.join(d, LOG), {"at": now, "by": by, "id": i, "action": action,
                                                       "result": result.get(i, "NOT_APPLIED")})
    for code, key in (("UNKNOWN_ID", "unknown_ids"), ("INVALID_TEXT", "invalid_text"), ("NOT_APPROVED", "not_approved")):
        res[key] = sorted(i for i, c in result.items() if c == code)
    return res


# ---- CLI ---------------------------------------------------------------------

def main_cli(args, paths, say):
    """review·apply. 건수·ID·코드만 낸다(근거 인용은 화면 파일에만). 파일 단위 오류는 [오류] <코드>, 종료 코드 1.

    apply에서 일부 결정이 반영되지 않아도(문장 오류 등) 종료 코드는 0이고, 줄에 건수와 결과 JSON(ID·코드)으로 알린다.
    """
    from domain_engrbot import policy as policy_mod

    try:
        pol, _ = policy_mod.load(paths)
        cfg = lr.config(pol)
        d = ledger.ledger_dir(paths.root, pol)
        if args.action == "review":
            obj = build(d, cfg)
            say("[labeling-rules] 승인된 규칙 관리 화면: 승인 규칙 %d개, 승인 사례 %d개, 갱신 대기 사례 %d개 → %s/%s" % (
                len(obj["approved_rules"]), len(obj["approved_examples"]), len(obj["pending_examples"]),
                ledger.dir_label(d), SCREEN))
            return 0
        if not args.decisions:
            say("[오류] DECISIONS_REQUIRED (--decisions <결정 JSON>)")
            return 2
        if not os.path.isfile(args.decisions):
            say("[오류] DECISIONS_NOT_FOUND")
            return 1
        r = apply(d, cfg, args.decisions, snapshot_dir=paths.inputs_dir)
        say("[labeling-rules] 반영: 승인 규칙 %d·사례 %d, 기각 규칙 %d·사례 %d, 문장 수정 %d, 켬 %d, 끔 %d%s%s" % (
            r["approved_rules"], r["approved_examples"], r["rejected_rules"], r["rejected_examples"], r["edited"],
            r["enabled"], r["disabled"],
            ", 모르는 ID %d개" % len(r["unknown_ids"]) if r["unknown_ids"] else "",
            ", 문장 오류 %d개" % len(r["invalid_text"]) if r["invalid_text"] else ""))
        say(io.dumps(r))
        return 0
    except (ReviewError, lr.LabelingRulesError, ledger.LedgerError) as e:
        say("[오류] %s" % e.reason_code)
        return 1
