"""라벨링 규칙 변경 감지: 기준 실행이 쓴 규칙과 지금 승인 파일(taxonomy/labeling_rules.json)의 규칙을 비교한다.

규칙 ID·종류·대상(축 이름, 질문 ID, 축=값)·건수만 다루고 규칙 문장은 내지 않는다.

- 기준(baseline): meta rules_applied:<run>. 없으면(옛 실행) 그 실행의 sheet_hashes.labeling_rules digest와 같은 승인 문서를
  rules_history.jsonl의 문서들 → git 이력의 승인 파일 → 지금 파일 순으로 찾는다(feedback.snapshot_of, 지금 taxonomy·설정으로
  다시 계산하므로 근사다). 규칙 없이 돈 실행(digest 없음, feedback_applied 있음)은 빈 기준이다. 못 찾으면 RULES_BASELINE_UNKNOWN.
  axis-update 실행은 대상 축만 그 실행 digest로 복원하고 나머지는 부모 기준을 이어받는다. 같은 digest인 후보가 여럿이면
  가장 오래된 것(이력 파일 앞쪽 → git 오래된 리비전 → 지금 파일)을 쓰고, 기록이 서로 다르면 source에 "~ambiguous"를 붙인다.
  부모 기준을 모른 채 끝난 axis-update는 rules_applied에 자기 범위만(partial) 남기고, 읽을 때 부모 기준을 다시 찾아 합친다.
- 변경 종류: added(새로 켜짐 포함)·edited(내용 해시가 다름)·disabled(파일에 있으나 이번 실행에 들어가지 않음)·removed(파일에서 사라짐).
  few-shot 사례 변경은 건수(examples_changed)만 낸다.
- 범위(scope): 1차 축 규칙 → classify.axes, ANSWER·3차 MANUAL 질문 ID → label.qids, GEN_ANSWER 축=값 → label.gen_targets,
  3차 MANUAL 축=값 → label.pairs, 축 없는 규칙(target classify/label) → stage_wide. 끄기·기각된 규칙은 이전 기록의 대상으로 범위를 낸다.
  범위에는 지금 taxonomy의 활성 축·승인 질문 ID·있는 축=값만 남긴다(삭제·비활성 축 규칙은 다시 라벨할 곳이 없다).
"""
import json
import os
import subprocess

from labelbot import feedback, ingest, runchain, store

RULES_BASELINE_UNKNOWN = "RULES_BASELINE_UNKNOWN"
NO_RULE_CHANGE, STAGE_WIDE_ONLY = "NO_RULE_CHANGE", "STAGE_WIDE_ONLY"
NO_PREVIOUS_RUN = "NO_PREVIOUS_RUN"
CHANGES = ("added", "edited", "disabled", "removed")
GIT_MAX_REVS = 200
GIT_TIMEOUT = 10


def history_path(ws):
    """Domain-Engr-bot 질문 반영이 남기는 이전 승인 문서 이력(workspaces/_domain_engrbot/questions/rules_history.jsonl)."""
    return os.path.join(feedback.examples_root(ws), "_domain_engrbot", "questions", "rules_history.jsonl")


def _doc(obj):
    """승인 문서 형식이면 {"rules", "examples"}, 아니면 None."""
    if not isinstance(obj, dict) or any(not isinstance(obj.get(k, []), list) for k in ("rules", "examples")):
        return None
    return {"rules": obj.get("rules") or [], "examples": obj.get("examples") or []}


def _history_docs(ws):
    p = history_path(ws)
    if not os.path.isfile(p):
        return
    try:
        lines = ingest.read_input(p, None, expect="text").splitlines()
    except (ingest.InputError, OSError, ValueError):
        return
    for line in lines:  # 오래된 이력부터
        try:
            d = _doc((json.loads(line) or {}).get("doc"))
        except (ValueError, AttributeError):
            continue
        if d is not None:
            yield "rules_history", d


def _git(args, cwd):
    try:
        r = subprocess.run(["git", "-C", cwd] + args, capture_output=True, timeout=GIT_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _git_docs(path):
    """git 이력의 승인 파일. git이 없거나 저장소 밖이면 아무것도 내지 않는다."""
    d, name = os.path.split(os.path.abspath(path))
    if not os.path.isdir(d):
        return
    out = _git(["log", "--format=%H", "-n", str(GIT_MAX_REVS), "--", name], d)
    for rev in reversed((out or b"").decode("ascii", "ignore").split()):  # 오래된 리비전부터
        raw = _git(["show", "%s:./%s" % (rev, name)], d)
        try:
            doc = _doc(json.loads(raw.decode("utf-8-sig"))) if raw else None
        except (ValueError, UnicodeDecodeError):
            doc = None
        if doc is not None:
            yield "git", doc


def _candidates(ws):
    yield from _history_docs(ws)
    yield from _git_docs(feedback.rules_path(ws))
    try:
        yield "current", feedback.load_rules(ws)
    except feedback.FeedbackError:
        return


def current(ws, tax):
    """지금 승인 파일로 전체 실행이 쓸 규칙 기록(feedback.snapshot_of). 파일 형식이 틀리면 FeedbackError."""
    return feedback.snapshot_of(ws, feedback.load_rules(ws), tax)[1]


def merge(parent, own, axes=(), keys=()):
    """부분 실행의 기록: axes(1차 축)·keys(3차 질문 ID·축=값) 범위만 own으로 바꾸고 나머지는 parent를 이어받는다."""
    out = json.loads(json.dumps(parent))
    for part, names in (("classify", axes), ("label", keys)):
        for k in names:
            if k in own[part]:
                out[part][k] = own[part][k]
            else:
                out[part].pop(k, None)
    return out


def _norm(rec):
    out = feedback.empty_record()
    if isinstance(rec, dict):
        for part in ("classify", "label", "stage_wide"):
            if isinstance(rec.get(part), dict):
                out[part] = rec[part]
        if isinstance(rec.get("examples"), list):
            out["examples"] = rec["examples"]
    return out


def _sheet_digest(con, run_id):
    r = con.execute("SELECT sheet_hashes FROM runs WHERE run_id=?", (run_id,)).fetchone()
    try:
        return (json.loads(r[0] or "{}") or {}).get("labeling_rules") if r else None
    except (ValueError, AttributeError):
        return None


def baseline(ws, con, run_id, tax, cache=None, beat=None):
    """{code(None 또는 RULES_BASELINE_UNKNOWN), record, source}. source: rules_applied·rules_history·git·current·no_rules.
    rules_applied가 없는 axis-update는 "<대상 축 출처>+<부모 출처>"(예: current+rules_history)다. 대상 축 밖의 규칙은
    부모 실행이 쓴 것이므로, 부모 뒤에 더해진 비대상 축 규칙은 변경으로 나온다.
    cache({}): 실행별 결과와 사례 해석을 다시 쓴다. beat(): 후보 문서를 하나 볼 때마다 부른다(잠금 갱신)."""
    cache = {} if cache is None else cache
    key = ("baseline", run_id)
    if key not in cache:
        cache[key] = _baseline(ws, con, run_id, tax, cache, beat)
    return cache[key]


def _baseline(ws, con, run_id, tax, cache, beat):
    unknown = {"code": RULES_BASELINE_UNKNOWN, "record": None, "source": None}
    rec = store.meta_json(con, "rules_applied:" + run_id)
    info = runchain.run_info(con, run_id)
    if isinstance(rec, dict) and not isinstance(rec.get("partial"), dict):
        return {"code": None, "record": _norm(rec), "source": "rules_applied"}
    if info and info["command"] != "axis-update":
        return unknown  # rules-update는 언제나 기준을 알고 rules_applied를 남긴다
    parent = baseline(ws, con, info["parent"], tax, cache, beat) if info and info["parent"] else None
    if info and (parent is None or parent["code"]):
        return unknown
    if isinstance(rec, dict):  # 부모 기준을 모른 채 끝난 axis-update: 자기 범위만 남겼다
        part = rec["partial"]
        return {"code": None, "record": merge(parent["record"], _norm(rec), part.get("axes") or [], part.get("keys") or []),
                "source": "rules_applied+%s" % parent["source"]}
    only = set(info["target"]) if info else None
    digest = _sheet_digest(con, run_id)
    if digest is None:
        if not isinstance(store.meta_json(con, "feedback_applied:" + run_id), dict):
            return unknown
        own, source = feedback.empty_record(), "no_rules"  # 규칙·사례 없이 돈 실행(--no-feedback 포함)
    else:
        found = []
        for src, doc in _candidates(ws):
            if beat:
                beat()
            d, rec_c = feedback.snapshot_of(ws, doc, tax, None, only, cache)
            if d == digest:
                found.append((src, rec_c))
        if not found:
            return unknown
        source, own = found[0]  # 가장 오래된 후보
        if any(r != own for _, r in found[1:]):
            source += "~ambiguous"
    if info:
        # axis-update: 대상 축만 그 실행의 규칙, 나머지 축은 부모 기준이다. source는 "대상 축 출처+부모 출처"다.
        src = source if parent["source"] == source else "%s+%s" % (source, parent["source"])
        return {"code": None, "record": merge(parent["record"], own, axes=only), "source": src}
    return {"code": None, "record": own, "source": source}


def _flat(rec):
    """{rule_id: (구역, 키, 항목)}."""
    out = {}
    for part in ("classify", "label"):
        for key, rules in (rec.get(part) or {}).items():
            for rid, ent in rules.items():
                out[rid] = (part, key, ent)
    for rid, ent in (rec.get("stage_wide") or {}).items():
        out[rid] = ("stage_wide", "", ent)
    return out


def diff(prev, cur, doc=None):
    """{added, edited, disabled, removed, examples_changed}. doc(지금 승인 문서)에 남은 규칙은 disabled, 없으면 removed."""
    p, c = _flat(prev), _flat(cur)
    in_file = {r.get("rule_id") for r in (doc or {}).get("rules") or [] if isinstance(r, dict)}
    gone = sorted(set(p) - set(c))
    return {"added": sorted(set(c) - set(p)),
            "edited": sorted(rid for rid in set(p) & set(c) if p[rid][2].get("h") != c[rid][2].get("h")),
            "disabled": [rid for rid in gone if rid in in_file],
            "removed": [rid for rid in gone if rid not in in_file],
            "examples_changed": len(set(prev.get("examples") or []) ^ set(cur.get("examples") or []))}


def rule_scopes(rid, prev, cur):
    """바뀐 규칙 하나의 범위: 이전·지금 기록의 (구역, 키, 항목) 목록(수정으로 대상이 옮겨 가면 둘 다)."""
    out = []
    for rec in (prev, cur):
        hit = _flat(rec).get(rid)
        if hit and hit not in out:
            out.append(hit)
    return out


def _known(tax, con=None):
    """범위 필터: (활성 축 이름, 질문 ID(승인 질문 + con의 gen_questions 검증 질문), 있는 축=값 판정 함수)."""
    active = {a.name: a for a in tax.active_axes()}
    qids = {q.qid for q in tax.questions}
    if con is not None:
        qids |= {r[0] for r in con.execute("SELECT qid FROM gen_questions")}

    def pair_ok(key):
        a, _, v = key.partition("=")
        return a in active and active[a].value(v) is not None
    return set(active), qids, pair_ok


def scope(d, prev, cur, tax=None, con=None):
    """{"classify": {"axes"}, "label": {"qids", "gen_targets", "pairs"}, "stage_wide": [rule_id]}.
    tax를 주면 지금 taxonomy의 활성 축·질문 ID(승인 질문, con을 주면 Q-GEN 검증 질문 포함)·있는 축=값만 남긴다."""
    axes, qids, gens, pairs, wide = set(), set(), set(), set(), set()
    for rid in [r for k in CHANGES for r in d[k]]:
        for part, key, ent in rule_scopes(rid, prev, cur):
            if part == "classify":
                axes.add(key)
            elif part == "stage_wide":
                wide.add(rid)
            elif "=" in key:
                (gens if ent.get("kind") == "GEN_ANSWER" else pairs).add(key)
            else:
                qids.add(key)
    if tax is not None:
        active, known_q, pair_ok = _known(tax, con)
        axes, qids = axes & active, qids & known_q
        gens, pairs = {k for k in gens if pair_ok(k)}, {k for k in pairs if pair_ok(k)}
    return {"classify": {"axes": sorted(axes)},
            "label": {"qids": sorted(qids), "gen_targets": _pairs(gens - pairs), "pairs": _pairs(pairs)},
            "stage_wide": sorted(wide)}


def _pairs(keys):
    return [list(k.split("=", 1)) for k in sorted(keys)]


def label_keys(sc):
    """범위의 3차 기록 키(질문 ID와 축=값)."""
    lab = sc["label"]
    return sorted(set(lab["qids"]) | {"%s=%s" % tuple(t) for t in lab["gen_targets"] + lab["pairs"]})


def compare(ws, con, tax, run_id=None, cache=None, beat=None):
    """기준 실행(기본: 끝난 최신 라벨 실행)과 지금 승인 파일의 차이.

    반환: {code, run_id, baseline, added, edited, disabled, removed, examples_changed, scope, prev, cur}.
    prev·cur는 기록(규칙 해시·대상)이며 CLI는 내지 않는다. code: None(다시 라벨링 필요)·NO_PREVIOUS_RUN·
    RULES_BASELINE_UNKNOWN·NO_RULE_CHANGE·STAGE_WIDE_ONLY. 범위가 지금 taxonomy에 없는 축·질문뿐이면 NO_RULE_CHANGE다.
    """
    run_id = run_id or store.latest_label_run(con, finished=True)
    out = {"code": None, "run_id": run_id, "baseline": None, "examples_changed": 0, "prev": None, "cur": None,
           "scope": {"classify": {"axes": []}, "label": {"qids": [], "gen_targets": [], "pairs": []}, "stage_wide": []}}
    out.update({k: [] for k in CHANGES})
    if not run_id:
        return dict(out, code=NO_PREVIOUS_RUN)
    b = baseline(ws, con, run_id, tax, cache, beat)
    if b["code"]:
        return dict(out, code=b["code"])
    doc = feedback.load_rules(ws)
    cur = feedback.snapshot_of(ws, doc, tax, None, None, cache)[1]
    d = diff(b["record"], cur, doc)
    sc = scope(d, b["record"], cur, tax, con)
    out.update(d, baseline=b["source"], scope=sc, prev=b["record"], cur=cur)
    if not any(d[k] for k in CHANGES):
        out["code"] = NO_RULE_CHANGE
    elif not (sc["classify"]["axes"] or label_keys(sc)):
        out["code"] = STAGE_WIDE_ONLY if sc["stage_wide"] else NO_RULE_CHANGE
    return out


def public(res):
    """CLI JSON 한 줄: 규칙 ID·축 이름·질문 ID·건수만(기록 본체는 뺀다)."""
    return {k: v for k, v in res.items() if k not in ("prev", "cur")}


def summary_line(res):
    if res["code"] in (NO_PREVIOUS_RUN, RULES_BASELINE_UNKNOWN):
        return "[rules] 기준 run_id=%s %s → 비교할 수 없다(전체 /BEOL-labeling 실행)" % (res["run_id"] or "-", res["code"])
    sc = res["scope"]
    head = "[rules] 기준 run_id=%s(%s) 대비 규칙 추가 %d·수정 %d·끔 %d·기각 %d, 사례 변경 %d · 범위 축 %d개, 질문 %d개, 축 없는 규칙 %d개" % (
        res["run_id"], res["baseline"], len(res["added"]), len(res["edited"]), len(res["disabled"]),
        len(res["removed"]), res["examples_changed"], len(sc["classify"]["axes"]), len(label_keys(sc)),
        len(sc["stage_wide"]))
    return head + (" → %s" % res["code"] if res["code"] else " → rules-update 필요")
