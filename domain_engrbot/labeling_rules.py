"""라벨링 규칙 환류: 교정 장부(cases·records) → 라벨링 규칙·few-shot 사례 후보 → 사람 승인 → taxonomy/labeling_rules.json.

- 장부(ledger)가 생산자, labelbot은 승인 파일만 읽는 소비자다(labelbot/feedback.py). 둘 사이는 이 파일 계약뿐이다.
- 후보는 LLM 없이 교정 패턴을 센다(같은 장부면 같은 후보). L4 도메인 규칙 후보(rule_candidates.json)와는 소비처가 달라
  장부 폴더의 labeling_candidates.json·.md에 따로 쓴다. 본문은 넣지 않는다(축·값·질문 ID·레코드 ID·건수만).
- 사례는 (source_ws, record_id, text_hash) 참조만 둔다. 본문은 labelbot이 실행할 때 원래 작업 폴더 DB에서 읽기 전용으로
  가져온다. 그래서 장부의 "본문 발췌는 golden·judge_examples·evidence에만" 원칙이 그대로 지켜진다.
- 근거(사용자 결정 E2·E4, 2026-10-05): 지지 건수는 근거 유무와 관계없이 센다. 단 근거(사람이 드래그한 위치)가 있는 지지
  레코드가 min_evidence(기본 1) 이상인 규칙만 후보로 올리고, 규칙 문장 끝에 근거 위치 종류별 건수를 붙인다(인용은 넣지 않는다).
  사례 후보는 근거 있는 교정 축이 하나 이상인 레코드만이다(확인만 한 레코드는 사례가 아니다).
- 봇은 승인하지 않는다. approve·reject는 사람이 고른 ID(또는 사람이 고른 --all)로만 부르고, 사람이 승인 파일의 문장(text)을
  고치거나 enabled를 끌 수 있다(파일 편집이 곧 사람의 결정이다).

규칙 종류:
- REPLACE: 축에서 실제 값 x를 y로 바꿈(혼동 경향). '해당 없음'↔'unknown' 바꿈도 여기에 든다.
- REMOVE: 봇이 붙인 실제 값을 사람이 뺌(과잉 부여). ADD: 봇이 놓친 실제 값을 사람이 더함(누락).
- ANSWER: 승인 질문의 답 뒤집힘. GEN_ANSWER: 검증 질문(Q-GEN-)의 답 뒤집힘(대상 '축=값').
지지 건수는 서로 다른 레코드(chunk) 수다. 반대 방향 교정도 min_count건 이상이면 상충으로 표시하고 --all이 승인하지 않는다.
"""
import os
import re

from domain_engrbot import io, ledger, model

RULES_PATH = os.path.join(io.CODE_ROOT, "taxonomy", "labeling_rules.json")
CANDIDATES = "labeling_candidates.json"
CANDIDATES_MD = "labeling_candidates.md"
VERSION = 3   # v3: 규칙에 evidence_count·evidence_mix. v2 파일도 그대로 읽는다

NA, UNKNOWN = "해당 없음", "unknown"
SPECIAL = (NA, UNKNOWN)
AXIS_KINDS = ("REPLACE", "REMOVE", "ADD")
ANSWER_KINDS = ("ANSWER", "GEN_ANSWER")
KINDS = AXIS_KINDS + ANSWER_KINDS + ("MANUAL",)
ANSWERS = ("O", "X", "N/A")
TEXT_MAX = 300
MAX_REFS = 5
DEFAULTS = {"min_count": 2, "min_evidence": 1}
# 규칙 문장 끝 "근거 위치: …"의 순서와 이름(ledger.EVIDENCE_KINDS의 위치 종류)
MIX_ORDER = (("doc_title", "문서 제목"), ("chunk_other", "다른 슬라이드"), ("chunk_same", "같은 슬라이드"),
             ("file_name", "파일명"), ("typed", "직접 입력"))
# 작업 폴더 이름(경로 구분자·상위 경로 없음). labelbot이 이 이름으로 workspaces/ 아래 DB를 찾는다.
SAFE_NAME = re.compile(r"^[^\\/:*?\"<>|]+$")


class LabelingRulesError(Exception):
    def __init__(self, reason_code):
        Exception.__init__(self, reason_code)
        self.reason_code = reason_code


def config(policy):
    cfg = dict(DEFAULTS)
    cfg.update(((policy or {}).get("ledger") or {}).get("labeling") or {})
    cfg["min_count"] = max(1, int(cfg.get("min_count") or 1))
    cfg["min_evidence"] = max(0, int(cfg.get("min_evidence") or 0))
    return cfg


# ---- 값 도우미 -----------------------------------------------------------------

def _as_list(v):
    if v is None:
        return []
    out = []
    for x in v if isinstance(v, list) else [v]:
        x = str(x).strip()
        if x and x not in out:
            out.append(x)
    return out


def _latest_cases(d):
    """같은 (record_id, text_hash, field)는 (labeler_run_id, source_ws)가 큰 행 하나."""
    return ledger.latest(ledger.read(d, ledger.CASES), lambda r: (r["record_id"], r.get("text_hash") or "", r["field"]))


# ---- 규칙 후보 -----------------------------------------------------------------

def rule_id(kind, target, frm, to):
    return "FR-" + model.hash_obj({"kind": kind, "target": target, "from": frm, "to": to})[:10]


def axis_keys(axis, bot, human):
    """축 교정 하나 → 규칙 키 목록.

    실제 값끼리 1:1로 바뀌면 REPLACE(혼동). 특수값('해당 없음'·'unknown')끼리 바뀌어도 REPLACE.
    그 밖에는 빠진 실제 값마다 REMOVE(과잉), 더해진 실제 값마다 ADD(누락). 특수값 자체는 규칙 대상이 아니다.
    """
    b, h = set(_as_list(bot)), set(_as_list(human))
    removed, added = sorted(b - h), sorted(h - b)
    real_r = [v for v in removed if v not in SPECIAL]
    real_a = [v for v in added if v not in SPECIAL]
    if len(real_r) == 1 and len(real_a) == 1 and len(removed) == 1 and len(added) == 1:
        return [("REPLACE", axis, real_r[0], real_a[0])]
    if not real_r and not real_a:
        if len(removed) == 1 and len(added) == 1:
            return [("REPLACE", axis, removed[0], added[0])]
        return []
    return [("REMOVE", axis, v, "") for v in real_r] + [("ADD", axis, "", v) for v in real_a]


def _pattern_cases(cases):
    """교정 사례 → [(규칙 키, 사례)]. 확인(confirmed) 사례는 세지 않는다."""
    out = []
    for c in cases:
        if c["kind"] != ledger.CORRECTED:
            continue
        kind, _, key = c["field"].partition(":")
        bot, human = c.get("bot_value"), c.get("human_value")
        if kind == "axis":
            # 봇 값이 목록이 아닌 레코드(깨진 JSON 문자열 등)는 규칙 근거로 쓰지 않는다.
            if not isinstance(bot, list) or not isinstance(human, list):
                continue
            keys = axis_keys(key, bot, human)
        elif kind == "answer":
            # O·X·N/A가 아닌 사람 값(검수 상태 등)은 판정 지침이 될 수 없으므로 세지 않는다.
            if not isinstance(bot, str) or not isinstance(human, str) or bot == human or human not in ANSWERS:
                continue
            if c.get("gen_axis"):
                keys = [("GEN_ANSWER", "%s=%s" % (c["gen_axis"], c.get("gen_value")), bot, human)]
            else:
                keys = [("ANSWER", key, bot, human)]
        else:
            continue
        out += [(k, c) for k in keys]
    return out


def patterns(cases):
    """교정 사례 → {(kind, target, from, to): 지지 레코드 ID 집합}. 확인(confirmed) 사례는 세지 않는다."""
    out = {}
    for k, c in _pattern_cases(cases):
        out.setdefault(k, set()).add(c["record_id"])
    return out


def pattern_evidence(cases):
    """교정 사례 → {규칙 키: {근거 있는 지지 레코드 ID: (위치 종류 집합, case_id 목록)}}. 근거 없는 사례는 뺀다."""
    out = {}
    for k, c in _pattern_cases(cases):
        kinds = set(c.get("evidence_sources") or [])
        if not kinds:
            continue
        got = out.setdefault(k, {}).setdefault(c["record_id"], (set(), []))
        got[0].update(kinds)
        got[1].append(c["case_id"])
    return out


def evidence_mix(by_record):
    """{레코드: (위치 종류 집합, …)} → {위치 종류: 레코드 수}(MIX_ORDER 순, 0은 뺀다)."""
    out = {}
    for kind, _ in MIX_ORDER:
        n = sum(1 for kinds, _ in by_record.values() if kind in kinds)
        if n:
            out[kind] = n
    return out


def mix_text(mix, short=False):
    """근거 위치 문장(건수만). short면 "근거: 문서 제목 n·…" 꼴로 줄인다."""
    parts = [(label, mix[k]) for k, label in MIX_ORDER if mix.get(k)]
    if not parts:
        return ""
    if short:
        return "근거: " + "·".join("%s %d" % p for p in parts) + "."
    return "근거 위치: " + ", ".join("%s %d건" % p for p in parts) + "."


def with_mix(text, mix):
    """규칙 문장 끝에 근거 위치를 붙인다. TEXT_MAX를 넘으면 짧은 꼴, 그래도 넘으면 앞 문장 뒤를 줄여 맞춘다."""
    tail = mix_text(mix)
    if not tail:
        return text
    if len(text) + 1 + len(tail) <= TEXT_MAX:
        return text + " " + tail
    tail = mix_text(mix, short=True)
    if len(text) + 1 + len(tail) <= TEXT_MAX:
        return text + " " + tail
    return text[:TEXT_MAX - len(tail) - 2].rstrip() + "… " + tail


def rule_text(kind, target, frm, to, n):
    """규칙 문장(축·값·질문 ID·건수만). 경향을 알리는 조건부 지침이며 분류 체계 정의가 우선한다."""
    if kind == "REPLACE":
        if frm == UNKNOWN and to == NA:
            return ("「%s」 축: 봇이 'unknown'으로 둔 것을 사람이 '해당 없음'으로 고친 사례가 %d건 있다. "
                    "본문이 이 축을 다루지 않으면 'unknown'이 아니라 '해당 없음'으로 둔다." % (target, n))
        if frm == NA and to == UNKNOWN:
            return ("「%s」 축: 봇이 '해당 없음'으로 둔 것을 사람이 'unknown'으로 고친 사례가 %d건 있다. "
                    "본문이 이 축과 관련은 있으나 맞는 값이 없으면 'unknown'으로 둔다." % (target, n))
        return ("「%s」 축: 봇이 '%s'(으)로 판정한 것을 사람이 '%s'(으)로 고친 사례가 %d건 있다(혼동 경향). "
                "두 값의 정의를 대조해 본문에 맞는 값을 고른다." % (target, frm, to, n))
    if kind == "REMOVE":
        return ("「%s」 축: 봇이 붙인 '%s'을(를) 사람이 뺀 사례가 %d건 있다(과잉 부여 경향). "
                "본문이 '%s'의 정의를 직접 뒷받침할 때만 붙인다." % (target, frm, n, frm))
    if kind == "ADD":
        return ("「%s」 축: 봇이 놓친 '%s'을(를) 사람이 더한 사례가 %d건 있다(누락 경향). "
                "본문에 '%s'의 정의에 맞는 진술이 있는지 확인하고, 있으면 빠뜨리지 않는다." % (target, to, n, to))
    if kind == "ANSWER":
        return ("질문 %s: 봇이 '%s'(으)로 답한 것을 사람이 '%s'(으)로 고친 사례가 %d건 있다. "
                "'%s'(으)로 답하기 전에 판정 규칙과 본문 근거를 다시 확인한다." % (target, frm, to, n, frm))
    return ("검증 질문(Q-GEN-) 「%s」 라벨: 봇이 '%s'(으)로 답한 것을 사람이 '%s'(으)로 고친 사례가 %d건 있다. "
            "본문이 그 라벨을 직접 뒷받침하는지 다시 확인하고 답한다." % (target, frm, to, n))


def all_rules(cases, min_count):
    """모든 패턴(건수 1 이상) → {rule_id: 규칙}. 상충: 반대 방향 교정도 min_count건 이상.

    evidence_count는 근거 있는 지지 레코드 수, evidence_mix는 위치 종류별 레코드 수, evidence_cases는 근거 있는
    지지 레코드의 사례 ID(레코드마다 하나, 최대 MAX_REFS개. 최종 검수 화면이 evidence.jsonl에서 인용을 찾는 열쇠)다.
    모두 본문이 없다.
    """
    pats = patterns(cases)
    ev = pattern_evidence(cases)
    out = {}
    for (kind, target, frm, to), recs in pats.items():
        n = len(recs)
        rid = rule_id(kind, target, frm, to)
        rev = (kind, target, to, frm) if kind in ("REPLACE", "ANSWER", "GEN_ANSWER") else \
            ("ADD", target, "", frm) if kind == "REMOVE" else ("REMOVE", target, to, "")
        n_rev = len(pats.get(rev, ()))
        by_rec = ev.get((kind, target, frm, to)) or {}
        mix = evidence_mix(by_rec)
        out[rid] = {"rule_id": rid, "kind": kind, "target": target, "from": frm, "to": to, "count": n,
                    "conflict": n_rev >= min_count, "reverse_count": n_rev, "records": sorted(recs)[:MAX_REFS],
                    "evidence_count": len(by_rec), "evidence_mix": mix,
                    "evidence_cases": [min(by_rec[r][1]) for r in sorted(by_rec)[:MAX_REFS]],
                    "text": with_mix(rule_text(kind, target, frm, to, n), mix)}
    return out


# ---- few-shot 사례 후보 ----------------------------------------------------------

def example_id(record_id, text_hash):
    return "EX-" + model.hash_obj([record_id, text_hash or ""])[:12]


def all_examples(d, cases):
    """근거 있는 축 교정이 있는 레코드 → {example_id: 사례}. 근거 없는 교정·확인만 있는 레코드는 뺀다(사용자 결정 E2).

    final_axes는 사람 값이 덮인 확정 라벨이고, corrected는 고친 축의 봇→사람 값, confirmed는 사람이 그대로 확인한 축이다.
    나머지 축은 사람이 보지 않은 봇 값이다(labelbot이 사례를 보여 줄 때 이 셋을 나눠 쓴다).
    """
    by_rec = {}
    for c in cases:
        kind, _, key = c["field"].partition(":")
        if kind == "axis":
            by_rec.setdefault((c["record_id"], c.get("text_hash") or ""), []).append((key, c))
    out = {}
    for r in ledger.latest_records(d):
        k = (r["record_id"], r.get("text_hash") or "")
        axis_cases = by_rec.get(k) or []
        if not any(c["kind"] == ledger.CORRECTED and c.get("evidence_sources") for _, c in axis_cases):
            continue
        corrected, confirmed = {}, []
        for key, c in sorted(axis_cases, key=lambda x: x[0]):
            if c["kind"] == ledger.CORRECTED:
                corrected[key] = {"bot": _as_list(c.get("bot_value")), "human": _as_list(c.get("human_value"))}
            else:
                confirmed.append(key)
        eid = example_id(*k)
        out[eid] = {"example_id": eid, "source_ws": r["source_ws"], "labeler_run_id": r["labeler_run_id"],
                    "record_id": r["record_id"], "file_id": r.get("file_id"), "text_hash": r.get("text_hash"),
                    "kind": "corrected" if corrected else "confirmed",
                    "final_axes": {a: _as_list(v) for a, v in sorted((r.get("final_axes") or {}).items())},
                    "corrected": corrected, "confirmed": confirmed}
    return out


def _example_core(e):
    return [e.get("final_axes"), e.get("corrected"), e.get("confirmed")]


# ---- 승인 파일 -------------------------------------------------------------------

def empty_rules():
    return {"version": VERSION, "rules": [], "rejected": [], "examples": [], "rejected_examples": []}


def valid_rule(r):
    return (isinstance(r, dict) and isinstance(r.get("rule_id"), str) and r["rule_id"].strip()
            and isinstance(r.get("text"), str) and r["text"].strip() and len(r["text"]) <= TEXT_MAX
            and r.get("kind") in KINDS and isinstance(r.get("target", ""), str))


def valid_example(e):
    return (isinstance(e, dict) and isinstance(e.get("example_id"), str)
            and isinstance(e.get("source_ws"), str) and SAFE_NAME.match(e["source_ws"])
            and e["source_ws"] not in (".", "..") and isinstance(e.get("record_id"), str)
            and isinstance(e.get("text_hash"), str) and isinstance(e.get("final_axes"), dict))


def load_rules(path=None):
    """승인 파일(사람이 고치는 입력)을 read_input으로 읽는다. 없으면 빈 문서. 형식이 틀리면 RULES_JSON_INVALID·RULES_FORMAT_INVALID."""
    path = path or RULES_PATH
    if not os.path.isfile(path):
        return empty_rules()
    try:
        doc = io.read_json_input(path)
    except (ValueError, UnicodeDecodeError):
        raise LabelingRulesError("RULES_JSON_INVALID")
    if not isinstance(doc, dict) or any(not isinstance(doc.get(k, []), list)
                                        for k in ("rules", "rejected", "examples", "rejected_examples")):
        raise LabelingRulesError("RULES_FORMAT_INVALID")
    out = empty_rules()
    out.update(doc)
    out["version"] = VERSION
    for k in ("rejected", "rejected_examples"):
        out[k] = [x for x in out[k] if isinstance(x, str)]
    return out


def save_rules(doc, path=None):
    """원자 교체(tmp 파일 → os.replace): 쓰다 실패해도 기존 승인 파일은 그대로다."""
    ledger.replace_text(path or RULES_PATH, io.dumps(doc, indent=2) + "\n")


# ---- 후보·결정·상태 -------------------------------------------------------------

def candidates(d, doc, cfg):
    """승인 대기: 규칙(건수 ≥ min_count, 근거 있는 지지 ≥ min_evidence, 미결정)과
    사례(근거 있는 축 교정이 있고 미결정이거나, 승인했는데 확정 라벨이 바뀐 것)."""
    cases = _latest_cases(d)
    decided = {r.get("rule_id") for r in doc["rules"] if isinstance(r, dict)} | set(doc["rejected"])
    rules = [r for r in all_rules(cases, cfg["min_count"]).values()
             if r["count"] >= cfg["min_count"] and r["evidence_count"] >= cfg["min_evidence"]
             and r["rule_id"] not in decided]
    rules.sort(key=lambda r: (-r["count"], r["rule_id"]))
    have = {e.get("example_id"): e for e in doc["examples"] if isinstance(e, dict)}
    examples = []
    for eid, e in sorted(all_examples(d, cases).items()):
        if eid in doc["rejected_examples"]:
            continue
        old = have.get(eid)
        if old is None:
            examples.append(dict(e, update=False))
        elif _example_core(old) != _example_core(e):
            examples.append(dict(e, update=True))
    return {"rules": rules, "examples": examples}


def _md(s):
    return str(s if s is not None else "").replace("|", "/").replace("\n", " ")


def render_md(doc, cands):
    rules, exs = cands["rules"], cands["examples"]
    approved = [r for r in doc["rules"] if isinstance(r, dict)]
    lines = [
        "# 라벨링 규칙·사례 후보 (승인 대기)",
        "",
        "- 규칙 후보 %d개(상충 %d) · 승인 규칙 %d개(켜짐 %d) · 기각 %d개" % (
            len(rules), sum(1 for r in rules if r["conflict"]), len(approved),
            sum(1 for r in approved if r.get("enabled", True) and valid_rule(r)), len(doc["rejected"])),
        "- 사례 후보 %d개(갱신 %d) · 승인 사례 %d개 · 기각 %d개" % (
            len(exs), sum(1 for e in exs if e["update"]), len(doc["examples"]), len(doc["rejected_examples"])),
        "",
        "승인한 규칙·사례만 다음 `labelbot run`의 1차 분류·3차 라벨링 프롬프트에 들어간다(`taxonomy/labeling_rules.json`).",
        "그 파일에서 규칙 문장(text, %d자 이내)을 고치거나 enabled를 끌 수 있다." % TEXT_MAX,
        "",
        "```bash",
        "python -m domain_engrbot labeling-rules approve --workspace <작업 폴더> --ids FR-xxxx,EX-yyyy   # 골라서 승인",
        "python -m domain_engrbot labeling-rules approve --workspace <작업 폴더> --all --examples all     # 상충 없는 규칙·사례 전부",
        "python -m domain_engrbot labeling-rules reject --workspace <작업 폴더> --ids FR-xxxx            # 기각(다시 올리지 않음)",
        "```",
        "",
        "## 규칙 후보",
        "",
        "| 규칙 ID | 종류 | 대상 | 봇 | 사람 | 건수 | 근거 | 상충 | 규칙 문장 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rules:
        lines.append("| %s | %s | %s | %s | %s | %d | %d | %s | %s |" % (
            r["rule_id"], r["kind"], _md(r["target"]), _md(r["from"]), _md(r["to"]), r["count"], r["evidence_count"],
            "상충(반대 %d)" % r["reverse_count"] if r["conflict"] else "", _md(r["text"])))
    if not rules:
        lines.append("| (후보 없음) | | | | | | | | |")
    lines += ["", "## 사례 후보 (본문은 labelbot 실행 때 원래 작업 폴더에서 읽는다)", "",
              "| 사례 ID | 종류 | 작업 폴더 | 레코드 | 고친 축 | 확인한 축 | 갱신 |", "|---|---|---|---|---|---|---|"]
    for e in exs:
        lines.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            e["example_id"], e["kind"], _md(e["source_ws"]), _md(e["record_id"]),
            _md(", ".join("%s %s→%s" % (k, "/".join(v["bot"]), "/".join(v["human"])) for k, v in e["corrected"].items())),
            _md(", ".join(e["confirmed"])), "예" if e["update"] else ""))
    if not exs:
        lines.append("| (후보 없음) | | | | | | |")
    lines += ["", "상충: 같은 대상에서 반대 방향 교정도 있다. `--all`은 상충 후보를 승인하지 않는다.", ""]
    return "\n".join(lines)


def write_candidates(d, doc, cfg):
    """장부 폴더에 labeling_candidates.json·.md를 쓴다(장부 잠금 안, 원자 교체). 반환: 후보 dict."""
    with ledger.locked(d):
        return write_candidates_unlocked(d, doc, cfg)


def write_candidates_unlocked(d, doc, cfg):
    """write_candidates의 본체. 호출자가 ledger.locked(d)를 이미 쥐고 있어야 한다(재진입 불가)."""
    cands = candidates(d, doc, cfg)
    ledger.write_json(os.path.join(d, CANDIDATES), {"version": VERSION, "min_count": cfg["min_count"],
                                                    "min_evidence": cfg["min_evidence"],
                                                    "rules": cands["rules"], "examples": cands["examples"]})
    ledger.replace_text(os.path.join(d, CANDIDATES_MD), render_md(doc, cands))
    return cands


def _split_ids(ids):
    out = []
    for part in ids or []:
        out += [x.strip() for x in str(part).split(",") if x.strip()]
    return list(dict.fromkeys(out))


def decide(d, action, cfg, ids=None, all_=False, examples=None, path=None, by="cli"):
    """사람이 고른 결정을 승인 파일에 적는다. action: approve | reject.

    ids는 규칙 ID(FR-)·사례 ID(EX-) 목록, all_이면 지금 규칙 후보 전부(승인은 상충 제외), examples='all'이면 사례 후보 전부.
    승인한 규칙이 이미 있으면 사람이 고친 text·enabled를 그대로 두고 건수(count·evidence_count·evidence_mix)만 새로 쓴다.
    반환: {"rules", "examples", "unknown_ids", "skipped_conflict", "changed"}
    """
    if action not in ("approve", "reject"):
        raise LabelingRulesError("ACTION_INVALID")
    with ledger.locked(d):
        doc = load_rules(path)
        out = apply_decision(d, doc, action, cfg, ids=ids, all_=all_, examples=examples, by=by)
        if out["changed"]:
            save_rules(doc, path)
        write_candidates_unlocked(d, doc, cfg)
    return out


def apply_decision(d, doc, action, cfg, ids=None, all_=False, examples=None, by="cli"):
    """메모리의 doc만 고친다(저장 없음). 호출자가 잠금·저장을 맡는다. decide의 본체."""
    cases = _latest_cases(d)
    rules_all = all_rules(cases, cfg["min_count"])
    ex_all = all_examples(d, cases)
    cands = candidates(d, doc, cfg)
    want = _split_ids(ids)
    skipped = 0
    if all_:
        for r in cands["rules"]:
            if action == "approve" and r["conflict"]:
                skipped += 1
                continue
            want.append(r["rule_id"])
    if examples == "all":
        want += [e["example_id"] for e in cands["examples"]]
    want = list(dict.fromkeys(want))
    have_r = {r.get("rule_id"): r for r in doc["rules"] if isinstance(r, dict)}
    have_e = {e.get("example_id"): e for e in doc["examples"] if isinstance(e, dict)}
    unknown = [i for i in want if i not in rules_all and i not in have_r and i not in ex_all and i not in have_e]
    now, n_r, n_e, changed = model.now_iso(), 0, 0, False
    for i in want:
        if i in unknown:
            continue
        is_ex = i in ex_all or i in have_e
        if action == "approve":
            if is_ex:
                if i in doc["rejected_examples"]:
                    doc["rejected_examples"].remove(i)
                    changed = True
                e = ex_all.get(i)
                old = have_e.get(i)
                if e is not None and (old is None or _example_core(old) != _example_core(e)):
                    new = {k: e[k] for k in ("example_id", "source_ws", "labeler_run_id", "record_id", "file_id",
                                             "text_hash", "kind", "final_axes", "corrected", "confirmed")}
                    new.update(enabled=(old or {}).get("enabled", True), approved_at=now, approved_by=by)
                    doc["examples"] = [x for x in doc["examples"] if not (isinstance(x, dict) and x.get("example_id") == i)]
                    doc["examples"].append(new)
                    have_e[i] = new
                    n_e += 1
                    changed = True
            else:
                if i in doc["rejected"]:
                    doc["rejected"].remove(i)
                    changed = True
                p = rules_all.get(i)
                if i not in have_r and p is not None:
                    rule = {k: p[k] for k in ("rule_id", "kind", "target", "from", "to", "count", "evidence_count",
                                              "evidence_mix", "text")}
                    rule.update(enabled=True, approved_at=now, approved_by=by)
                    doc["rules"].append(rule)
                    have_r[i] = rule
                    n_r += 1
                    changed = True
                elif p is not None:
                    for k in ("count", "evidence_count", "evidence_mix"):
                        if have_r[i].get(k) != p[k]:
                            have_r[i][k] = p[k]
                            changed = True
        else:
            lst, key, have = ("rejected_examples", "examples", have_e) if is_ex else ("rejected", "rules", have_r)
            id_key = "example_id" if is_ex else "rule_id"
            if i in have:
                doc[key] = [x for x in doc[key] if not (isinstance(x, dict) and x.get(id_key) == i)]
                del have[i]
                changed = True
            if i not in doc[lst]:
                doc[lst].append(i)
                changed = True
            if is_ex:
                n_e += 1
            else:
                n_r += 1
    doc["rules"].sort(key=lambda r: str(r.get("rule_id")) if isinstance(r, dict) else "")
    doc["examples"].sort(key=lambda e: str(e.get("example_id")) if isinstance(e, dict) else "")
    doc["rejected"].sort()
    doc["rejected_examples"].sort()
    return {"rules": n_r, "examples": n_e, "unknown_ids": unknown, "skipped_conflict": skipped, "changed": changed}


def status(d, cfg, path=None):
    """건수만(본문 없음). 장부가 비어 있으면 후보 0."""
    doc = load_rules(path)
    cands = candidates(d, doc, cfg)
    rules = [r for r in doc["rules"] if isinstance(r, dict)]
    exs = [e for e in doc["examples"] if isinstance(e, dict)]
    return {
        "rules": {"approved": len(rules), "enabled": sum(1 for r in rules if r.get("enabled", True) and valid_rule(r)),
                  "manual": sum(1 for r in rules if r.get("kind") == "MANUAL"),
                  "invalid": sum(1 for r in rules if not valid_rule(r)), "rejected": len(doc["rejected"])},
        "examples": {"approved": len(exs), "enabled": sum(1 for e in exs if e.get("enabled", True) and valid_example(e)),
                     "invalid": sum(1 for e in exs if not valid_example(e)), "rejected": len(doc["rejected_examples"])},
        "candidates": len(cands["rules"]), "candidates_conflict": sum(1 for r in cands["rules"] if r["conflict"]),
        "examples_pending": len(cands["examples"]),
    }


# ---- CLI ---------------------------------------------------------------------

def main_cli(args, paths, say):
    """건수·ID·코드만 낸다. 오류는 [오류] <코드>, 종료 코드 1."""
    from domain_engrbot import policy as policy_mod

    try:
        pol, _ = policy_mod.load(paths)
        cfg = config(pol)
        d = ledger.ledger_dir(paths.root, pol)
        if args.action == "status":
            say(io.dumps(status(d, cfg)))
            return 0
        if args.action == "candidates":
            c = write_candidates(d, load_rules(), cfg)
            say("[labeling-rules] 규칙 후보 %d개(상충 %d), 사례 후보 %d개 → %s/%s" % (
                len(c["rules"]), sum(1 for r in c["rules"] if r["conflict"]), len(c["examples"]),
                ledger.dir_label(d), CANDIDATES_MD))
            return 0
        if not args.ids and not args.all and args.examples != "all":
            say("[오류] IDS_REQUIRED (--ids, --all, --examples all 중 하나)")
            return 2
        r = decide(d, args.action, cfg, ids=args.ids, all_=args.all,
                   examples="all" if args.examples == "all" else None)
        say("[labeling-rules] %s 규칙 %d개, 사례 %d개%s%s" % (
            "승인" if args.action == "approve" else "기각", r["rules"], r["examples"],
            ", 상충이라 건너뜀 %d개" % r["skipped_conflict"] if r["skipped_conflict"] else "",
            ", 모르는 ID %d개" % len(r["unknown_ids"]) if r["unknown_ids"] else ""))
        say(io.dumps(r))
        return 0
    except (LabelingRulesError, ledger.LedgerError) as e:
        say("[오류] %s" % e.reason_code)
        return 1
