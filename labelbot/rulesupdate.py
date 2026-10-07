"""rules-update: 라벨링 규칙(taxonomy/labeling_rules.json)이 바뀐 작업 폴더에서 바뀐 규칙이 닿는 범위만 다시 라벨링하는 실행.

plan()은 마지막 라벨 실행(기준)과 지금 승인 파일의 차이(rulesdiff)로 다시 라벨할 (chunk, 축)·(chunk, 질문)과 멈출 사유를 정한다.
start()는 command='rules-update' 실행을 만들고 기준 실행의 labels·failures를 모두 옮긴다(본문을 읽지 않는다).
다시 라벨하는 본체는 pipeline.run_rules_update다. 사람 검수 없이 바로 반영한다(불량 목록을 만들지 않는다).

- 축 대상(R3): 바뀐 1차 규칙의 축마다 기준 실행에서 그 축 행이 있는 chunk 전부. 1차 분류를 그 축만 다시 돈다.
- 답 대상(R5): 바뀐 3차 규칙의 질문(질문 ID, 축=값)에 답했던 (chunk, 질문). 3차 라벨링을 그 질문만 다시 돈다.
- 사람 값(R2): 기준 실행 확정 값에서 그 축·답의 검수 상태가 '검수하지 않음'이 아니면 뺀다. 확인된 chunk는 chunk 전체를 뺀다
  (답 하나만 바꿔도 확인 해시가 깨진다).
- 축 없는 규칙(R4)과 사례 변경은 다시 라벨하지 않고 건수만 남긴다.
- 덮어쓰기: LLM 호출이 성공한 (chunk, 축·질문) 행만 지우고 새로 넣는다. 실패하면 이어받은 값이 남고, 실패 기록은
  stage='relabel'·RELABEL_FAILED로 남긴다(이어받은 값이 유효하므로 분류·라벨 실패 chunk로 세지 않는다). 다시 라벨한
  (chunk, 단계)의 이어받은 실패 기록은 먼저 지우고 이번 결과로 다시 쓴다.
- 축 값이 바뀐 chunk: 옛 값에 묶인 답(그 축 옛 값의 승인·검증 질문, 새 값이 붙은 대조 질문)은 버린다(stale_answers).
  새 값에 걸리는 승인 질문 중 답이 없는 것은 다시 묻지 않고 건수(unasked_questions)만 남긴다.
- 변경 비율: 다시 라벨한 (chunk, 축·질문) 중 값이 바뀐 비율(다중값은 집합 비교). 버린 낡은 답은 분모·분자에 넣지 않는다.
  실행 때 rules_update.max_change_ratio를 넘으면 push-vectors가 적재를 멈춘다(실행 때 저장한 상한을 쓴다).
- 대상이 하나도 없으면(모두 사람 값·확인, 질문 없음) 실행을 만들지 않고 NO_RELABEL_TARGET으로 건너뛴다.
- 잠금은 axis-update와 같은 파일(axisupdate.acquire_lock)이고, 실행 체인은 runchain이 따라간다.
"""
from labelbot import axisupdate, finals, questions, rulesdiff, runchain, store, taxdiff, util

COMMAND = "rules-update"
NO_PREVIOUS_RUN, AXIS_CHANGE_PENDING = taxdiff.NO_PREVIOUS_RUN, "AXIS_CHANGE_PENDING"
RULES_CHANGE_RATIO_HIGH, NO_RELABEL_TARGET = "RULES_CHANGE_RATIO_HIGH", "NO_RELABEL_TARGET"
RELABEL_STAGE, RELABEL_FAILED = "relabel", "RELABEL_FAILED"
META, CHANGES_META = "rules_update:", "rules_update_changes:"


def _q(names):
    return ",".join("?" * len(names))


def _empty(prev):
    return {"code": None, "prev_run": prev, "baseline": None, "added": [], "edited": [], "disabled": [], "removed": [],
            "examples_changed": 0, "scope": None, "rules": [], "axis_targets": {}, "answer_targets": {}, "answer_keys": {},
            "scope_stats": {}, "skipped_human": 0, "skipped_confirmed": 0, "skipped_missing": 0,
            "stage_wide": [], "chunks": 0, "prev_record": None, "cur_record": None}


def _rule_rows(res):
    """바뀐 규칙마다 {rule_id, change, kind, target, stage, axes, keys}. 지금 기록이 있으면 그 종류·대상을 쓴다."""
    out = []
    for change in rulesdiff.CHANGES:
        for rid in res[change]:
            hits = rulesdiff.rule_scopes(rid, res["prev"], res["cur"])
            ent = hits[-1][2]
            out.append({"rule_id": rid, "change": change, "kind": ent.get("kind"), "target": ent.get("target"),
                        "stage": ent.get("stage"), "axes": sorted({k for p, k, _ in hits if p == "classify"}),
                        "keys": sorted({k for p, k, _ in hits if p == "label"}),
                        "stage_wide": any(p == "stage_wide" for p, _, _ in hits)})
    return out


def question_index(con, tax):
    """({승인 질문 ID: Question}, {검증 질문 ID: Question})."""
    gens = {}
    for r in con.execute("SELECT qid, axis, value, text FROM gen_questions"):
        gens[r["qid"]] = questions.Question(r["qid"], r["text"], (r["axis"], r["value"]), questions.GEN_PRIORITY, None)
    return {q.qid: q for q in tax.questions}, gens


def _answer_keys(key, q, sc):
    """(chunk, 질문) 답 하나가 걸리는 3차 범위 키 목록."""
    hit = [key] if key in sc["qids"] else []
    if q is not None and isinstance(q.target, tuple) and len(q.target) == 2:
        pair = "%s=%s" % tuple(q.target)
        if pair in sc["pairs"] or (key.startswith(questions.GEN_PREFIX) and pair in sc["gens"]):
            hit.append(pair)
    return hit


def plan(ws, con, tax, own_lock=None, cache=None, beat=None):
    """반환: {code, prev_run, baseline, added, edited, disabled, removed, examples_changed, rules, axis_targets
    {chunk: [축]}, answer_targets {chunk: [질문 ID]}, answer_keys {chunk: {질문 ID: [범위 키]}}, scope_stats {범위 키: 건수},
    skipped_*, stage_wide, chunks, …}.
    own_lock(자기 잠금의 실행 ID)은 잠금 검사에서 뺀다. summary(plan)이 건수만 담은 dict를 준다.
    cache·beat는 rulesdiff.baseline으로 넘긴다(잠금 밖·안 두 번 계산할 때 기준 복원을 다시 하지 않는다)."""
    prev = store.latest_label_run(con, finished=True)
    out = _empty(prev)
    if not prev:
        return dict(out, code=NO_PREVIOUS_RUN)
    sig, _ = taxdiff.previous_signature(con, prev)
    d = taxdiff.diff(sig, taxdiff.axes_signature(tax))
    if d.get("code"):
        return dict(out, code=d["code"])
    target, removed, _ = axisupdate._decide(d, tax)
    if target or removed:
        return dict(out, code=AXIS_CHANGE_PENDING)  # axis-update가 먼저다(비활성 축만의 변경은 막지 않는다)
    res = rulesdiff.compare(ws, con, tax, prev, cache, beat)
    out.update({k: res[k] for k in rulesdiff.CHANGES + ("baseline", "examples_changed", "scope")})
    if res["code"]:
        return dict(out, code=res["code"])
    out.update(rules=_rule_rows(res), stage_wide=res["scope"]["stage_wide"], prev_record=res["prev"],
               cur_record=res["cur"])
    out["code"] = runchain.reviewed(ws, con, prev) or (
        axisupdate.AXIS_UPDATE_LOCKED if axisupdate.locked(ws, own_lock, con) else None) \
        or runchain.push_pending(ws, con, prev)
    _targets(con, tax, prev, res["scope"], out)
    if out["code"] is None and not out["chunks"]:
        out["code"] = NO_RELABEL_TARGET  # 모두 사람 값·확인이거나 질문이 없다. rules_applied가 안 바뀌어 다음에도 건너뛴다
    return out


def _targets(con, tax, prev, scope, out):
    """R2·R3·R5 대상 계산. out에 axis_targets·answer_targets·scope_stats·skipped_*·chunks를 채운다."""
    final = finals.final_labels(con, prev)
    confirmed = {cid for cid, d in final.items()
                 if any(a.get("review") == finals.CONFIRMED for a in list(d["axes"].values()) + list(d["answers"].values()))}
    stats = {}

    def stat(key, field, n=1):
        s = stats.setdefault(key, {"targets": 0, "skipped_human": 0, "skipped_missing": 0})
        s[field] += n

    def protected(cid, item, key):
        if cid in confirmed:
            out["skipped_confirmed"] += 1
        elif item.get("review", finals.UNREVIEWED) != finals.UNREVIEWED:
            out["skipped_human"] += 1
        else:
            return False
        stat(key, "skipped_human")
        return True

    active = {a.name for a in tax.active_axes()}
    axes = [a for a in scope["classify"]["axes"] if a in active]
    if axes:
        for r in con.execute("SELECT chunk_id, key FROM labels WHERE run_id=? AND kind='axis' AND key IN (%s)"
                             " ORDER BY chunk_id, key" % _q(axes), [prev] + axes):
            cid, ax = r[0], r[1]
            if not protected(cid, final.get(cid, {}).get("axes", {}).get(ax, {}), ax):
                out["axis_targets"].setdefault(cid, []).append(ax)
                stat(ax, "targets")
    lab = scope["label"]
    sc = {"qids": set(lab["qids"]), "gens": {"%s=%s" % tuple(t) for t in lab["gen_targets"]},
          "pairs": {"%s=%s" % tuple(t) for t in lab["pairs"]}}
    if any(sc.values()):
        approved, gens = question_index(con, tax)
        for r in con.execute("SELECT chunk_id, key FROM labels WHERE run_id=? AND kind='answer' ORDER BY chunk_id, key",
                             (prev,)):
            cid, key = r[0], r[1]
            q = gens.get(key) if key.startswith(questions.GEN_PREFIX) else approved.get(key)
            keys = _answer_keys(key, q, sc)
            if not keys:
                continue
            item = final.get(cid, {}).get("answers", {}).get(key, {})
            if protected(cid, item, keys[0]):
                for k in keys[1:]:
                    stat(k, "skipped_human")
                continue
            if q is None:  # QUESTION_MISSING: 지금 taxonomy·gen_questions에 없는 질문은 건너뛰고 센다
                out["skipped_missing"] += 1
                for k in keys:
                    stat(k, "skipped_missing")
                continue
            out["answer_targets"].setdefault(cid, []).append(key)
            out["answer_keys"].setdefault(cid, {})[key] = keys
            for k in keys:
                stat(k, "targets")
    out["scope_stats"] = stats
    out["chunks"] = len(set(out["axis_targets"]) | set(out["answer_targets"]))


def summary(p):
    """dry-run·로그용: 실행 ID·규칙 ID·축 이름·건수만."""
    axes = {}
    for ax_list in p["axis_targets"].values():
        for a in ax_list:
            axes[a] = axes.get(a, 0) + 1
    qids = {q for lst in p["answer_targets"].values() for q in lst}
    return {"code": p["code"], "prev_run": p["prev_run"], "baseline": p["baseline"],
            "added": p["added"], "edited": p["edited"], "disabled": p["disabled"], "removed": p["removed"],
            "examples_changed": p["examples_changed"], "classify_axes": axes,
            "answer_questions": len(qids), "answer_chunks": len(p["answer_targets"]),
            "answer_targets": sum(len(v) for v in p["answer_targets"].values()),
            "chunks": p["chunks"], "skipped_human": p["skipped_human"], "skipped_confirmed": p["skipped_confirmed"],
            "skipped_missing": p["skipped_missing"], "stage_wide": len(p["stage_wide"])}


def skip_reason(p):
    """건너뜀 줄 뒤에 붙일 사유(NO_RELABEL_TARGET만): 건수만."""
    if p["code"] != NO_RELABEL_TARGET:
        return ""
    return " 사람 값 %d건, 확인 chunk %d건, 질문 없음 %d건" % (p["skipped_human"], p["skipped_confirmed"], p["skipped_missing"])


def start(ws, con, p, tax, run_id=None):
    """새 rules-update 실행을 만들고 기준 실행의 labels·failures를 모두 옮긴다. run_id를 주면 그 실행의 행을 지우고
    다시 만든다(멱등). run_id가 아직 runs에 없으면 그 ID로 실행을 만든다(잠금을 잡을 때 정한 ID).

    meta: parent_run:<run>, rules_update:<run>(run_info 형식: target·removed·values_added_only 빈 목록, axes 활성 축),
    rules_update_confirmed:<run>(기준 실행에서 확인된 chunk의 확인 해시), axes_signature:<run>(기준 실행 서명 복사).
    """
    from labelbot.pipeline import start_run

    prev = p["prev_run"]
    if run_id is None or not con.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone():
        r = con.execute("SELECT input_root FROM runs WHERE run_id=?", (prev,)).fetchone()
        run_id = start_run(con, ws, COMMAND, r[0] if r else None, run_id=run_id or runchain.new_run_id(prev))
    for table, cond in (("labels", "run_id=?"), ("failures", "run_id=?"), ("flagged_chunks", "run_id=?"),
                        ("candidates", "run_id=? AND source<>'review'")):
        con.execute("DELETE FROM %s WHERE %s" % (table, cond), (run_id,))
    # 같은 기준으로 먼저 만든 부분 실행(중단 등)이 가져간 위치도 이 실행으로 옮긴다.
    con.execute(
        "UPDATE file_locations SET last_seen_run=? WHERE last_seen_run=? OR last_seen_run IN"
        " (SELECT substr(key, %d) FROM meta WHERE substr(key, 1, %d)=? AND value=?)"
        % (len(runchain.PARENT) + 1, len(runchain.PARENT)), (run_id, prev, runchain.PARENT, prev))
    con.execute(
        "INSERT INTO labels(run_id, chunk_id, kind, key, value, status, evidence, confidence, sheet_hashes,"
        " prompt_version, model, created_at) SELECT ?, chunk_id, kind, key, value, status, evidence, confidence,"
        " sheet_hashes, prompt_version, model, created_at FROM labels WHERE run_id=? ORDER BY id", (run_id, prev))
    con.execute("INSERT INTO failures(run_id, stage, target_id, reason_code, created_at)"
                " SELECT ?, stage, target_id, reason_code, created_at FROM failures WHERE run_id=? ORDER BY id",
                (run_id, prev))
    store.meta_set(con, runchain.PARENT + run_id, prev)
    sig, _ = taxdiff.previous_signature(con, prev)
    if sig is not None:
        store.meta_set(con, "axes_signature:" + run_id, util.dumps(sig))  # taxonomy-diff 결과가 바뀌지 않게
    info = {"target": [], "removed": [], "values_added_only": [], "axes": sorted(a.name for a in tax.active_axes())}
    info.update(summary(p))
    store.meta_set(con, META + run_id, util.dumps(info))
    store.meta_set(con, CHANGES_META + run_id, "[]")
    # 기준 실행에서 확인된 chunk: 모든 축·답으로 확인 해시를 남긴다(D6). 확인된 chunk는 다시 라벨하지 않는다.
    prev_final = finals.final_labels(con, prev)
    ok = sorted(cid for cid, d in prev_final.items()
                if any(a.get("review") == finals.CONFIRMED for a in list(d["axes"].values()) + list(d["answers"].values())))
    bots = finals.bot_labels(con, run_id, ok)
    store.meta_set(con, "rules_update_confirmed:" + run_id,
                   util.dumps({cid: finals.confirm_hash(bots[cid], ()) for cid in ok if cid in bots}))
    con.commit()
    return run_id


def chunks(con, ids):
    """다시 라벨할 chunk 행(dict, 파일 경로·순서대로). 정상 파일의 chunk만."""
    ids, out = sorted(ids), []
    for i in range(0, len(ids), 500):
        part = ids[i : i + 500]
        out += [dict(r) for r in con.execute(
            "SELECT c.*, f.rel_path AS _rel FROM chunks c JOIN files f ON f.file_id=c.file_id"
            " WHERE f.status='ok' AND c.chunk_id IN (%s)" % _q(part), part)]
    out.sort(key=lambda c: (c.pop("_rel") or "", c["seq"] or 0))
    return out


def stale_keys(con, tax, run_id, chunk_id, axis, old, new):
    """축 값이 old → new로 바뀐 chunk에서 버릴 답·대조 행의 (kind, key) 목록.

    그 축 옛 값(상위 값 포함)에만 걸리던 승인 질문, 옛 값에서 빠진 값의 검증 질문(Q-GEN), 새로 붙은 값의 대조 질문(Q-CTL)."""
    def mapped(vals):
        return {q.qid for q in questions.map_questions(tax, {axis: {"values": list(vals)}}, 10 ** 6)[0]
                if isinstance(q.target, tuple)}
    gone_q = mapped(old) - mapped(new)
    gone_v, new_v = set(old) - set(new), set(new) - set(old)
    out = []
    for r in con.execute(
            "SELECT l.kind, l.key, g.axis AS gax, g.value AS gval, c.axis AS cax, c.value AS cval FROM labels l"
            " LEFT JOIN gen_questions g ON g.qid=l.key LEFT JOIN ctl_questions c ON c.qid=l.key"
            " WHERE l.run_id=? AND l.chunk_id=? AND l.kind IN ('answer','control')", (run_id, chunk_id)):
        if r["kind"] == "answer" and (r["key"] in gone_q or (r["gax"] == axis and r["gval"] in gone_v)):
            out.append(("answer", r["key"]))
        elif r["kind"] == "control" and r["cax"] == axis and r["cval"] in new_v:
            out.append(("control", r["key"]))
    return out


def unasked(tax, axis, old, new, answered):
    """축 값이 old → new로 바뀐 chunk에서 새 값에 걸리는데 답이 없는 승인 질문 수(다시 묻지 않고 센다)."""
    def mapped(vals):
        return {q.qid for q in questions.map_questions(tax, {axis: {"values": list(vals)}}, 10 ** 6)[0]
                if isinstance(q.target, tuple)}
    return len((mapped(new) - mapped(old)) - set(answered))


def blocked(ws, info):
    """적재를 멈출지: (막힘 여부, 비율, 상한). 실행 때 저장한 상한·최소 건수를 쓰고(없으면 지금 설정),
    다시 라벨한 수가 min_relabels 미만이면 막지 않는다."""
    cfg = ws.config.get("rules_update") or {}
    limit = float(info.get("max_change_ratio", cfg.get("max_change_ratio", 0.3)))
    least = int(info.get("min_relabels", cfg.get("min_relabels", 10)))
    ratio = float(info.get("change_ratio") or 0.0)
    return int(info.get("relabeled") or 0) >= least and ratio > limit, ratio, limit


def mark_forced(con, run_id):
    """push-vectors --force가 변경 비율 막힘을 넘겼을 때 meta rules_update:<run>에 forced_at을 남긴다."""
    info = store.meta_json(con, META + run_id)
    if isinstance(info, dict):
        info["forced_at"] = util.now_iso()
        store.meta_set(con, META + run_id, util.dumps(info))
        con.commit()


def run_info(con, run_id):
    """rules-update 실행이면 meta rules_update:<run> 내용(+ run_id·parent), 아니면 None.

    키: prev_run, baseline, added·edited·disabled·removed(규칙 ID), rules([{rule_id, change, kind, target, stage, axes,
    keys, stage_wide, relabeled, changed, skipped_human, skipped_missing}]), classify_axes({축: 대상 chunk 수}),
    relabeled, changed, failed, skipped_human, skipped_confirmed, skipped_missing, stale_answers, stage_wide(건수),
    examples_changed, change_ratio, max_change_ratio, min_relabels, blocked, unasked_questions, forced_at(--force로 보낸 때).
    """
    info = runchain.run_info(con, run_id)
    return info if info and info["command"] == COMMAND else None


def changes(con, run_id):
    """값이 바뀐 (chunk, 키) 목록: [{chunk_id, kind(axis|answer), key, before, after, stale}]. after None은 버린 답(stale)."""
    got = store.meta_json(con, CHANGES_META + run_id)
    return got if isinstance(got, list) else []
