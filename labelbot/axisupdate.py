"""axis-update: taxonomy 축이 바뀐 작업 폴더에서 바뀐 축만 1차 분류로 다시 라벨링하는 실행.

plan()은 마지막 라벨 실행(기준)과 지금 taxonomy의 차이로 대상 축·삭제 축·값 추가만 된 축과 멈출 사유를 정한다.
start()는 command='axis-update' 실행을 만들고 기준 실행의 행을 SQL INSERT … SELECT로 옮긴다(본문을 읽지 않는다).
입력 폴더는 다시 읽지 않는다. 기준 실행이 본 파일 위치(file_locations)를 새 실행으로 옮겨 같은 chunk만 대상으로 한다.

- 대상 축: 추가 + 변경(종류·다중값·계층·값 구성, 비활성→활성) + 값 삭제 + 값 추가. 1차 분류만 다시 돈다(2·3차 없음).
- 삭제 축(활성→비활성 포함): LLM 없이 라벨에서 뺀다.
- 이전 답: 적용 대상이 대상 축·삭제 축인 승인 질문, 그 축의 검증(Q-GEN)·대조(Q-CTL) 질문 답은 버리고 나머지는 이어받는다.
- 이전 교정: 삭제·변경 축 교정은 이 실행에 적용하지 않는다. 값 추가만 된 축의 교정은 남긴다(finals.corrections).
- 확인 상태: 기준 실행에서 확인된 chunk는 대상 축을 뺀 축·남긴 답의 해시로 확인 상태를 이어받는다.
- 기준 실행에서 분류에 실패한 chunk: chunk_type·비대상 축이 없어 부분 분류로 채울 수 없다. 범위에서 빼고 실패 기록을
  옮겨 CLASSIFY_FAILED 불량으로 남긴다(전체 /BEOL-labeling 재실행 대상).
- 잠금: logs/axis_update.lock.json(실행 ID·시작 시각만). 있으면 AXIS_UPDATE_LOCKED, LOCK_STALE_SEC보다 오래되면 무시한다.
  rules-update도 같은 잠금을 쓴다. 실행 체인·기준 실행 조건은 runchain에 있다.
"""
import json
import os
import time

from labelbot import runchain, store, taxdiff, util

COMMAND = "axis-update"
NO_PREVIOUS_RUN, NO_AXIS_CHANGE = taxdiff.NO_PREVIOUS_RUN, "NO_AXIS_CHANGE"
PREV_NOT_REVIEWED, REVIEW_IN_PROGRESS = runchain.PREV_NOT_REVIEWED, runchain.REVIEW_IN_PROGRESS
PREV_PUSH_PENDING, AXIS_UPDATE_LOCKED = runchain.PREV_PUSH_PENDING, "AXIS_UPDATE_LOCKED"
AXIS_UPDATE_LOCK_LOST = "AXIS_UPDATE_LOCK_LOST"
LOCK_STALE_SEC = 6 * 3600
LOCK_GRACE_SEC = 600  # 잠금 주인이 아직 runs 행을 만들기 전인 유예
_PARENT = runchain.PARENT


def _q(names):
    return ",".join("?" * len(names))


def run_info(con, run_id):
    """axis-update 실행이면 {run_id, parent, target, removed, values_added_only, axes, confirmed, 건수…}, 아니면 None.

    axes는 그 실행이 라벨을 가진 활성 축, confirmed는 이어받은 확인 상태({chunk_id: 확인 해시})다.
    rules-update 실행까지 보려면 runchain.run_info를 쓴다.
    """
    info = runchain.run_info(con, run_id)
    return info if info and info["command"] == COMMAND else None


def target_axes(con, run_id):
    """axis-update 실행이면 대상 축 집합, 아니면 None."""
    info = run_info(con, run_id)
    return set(info["target"]) if info else None


# 실행 체인·기준 실행 조건은 runchain에 있다(rules-update와 같이 쓴다). 이름은 그대로 남긴다.
chain, dropped_axes, new_run_id = runchain.chain, runchain.dropped_axes, runchain.new_run_id
_reviewed, _push_pending = runchain.reviewed, runchain.push_pending


def _decide(d, tax):
    """taxdiff 결과 → (대상 축, 삭제 축, 값 추가만 된 축). 지금 비활성인 축은 대상이 아니다."""
    active = {a.name for a in tax.active_axes()}
    changed = {c["axis"]: c["fields"] for c in d.get("changed") or []}
    removed_vals = d.get("values_removed") or {}
    target, removed = set(), set(d.get("removed") or [])
    for name in d.get("added") or []:
        if name in active:
            target.add(name)
    for name, fields in changed.items():
        if name in active:
            target.add(name)
        elif "active" in fields:
            removed.add(name)  # 활성 Y→N은 삭제와 같게 본다
    for name in list(d.get("values_added") or {}) + list(removed_vals):
        if name in active:
            target.add(name)
    only = {n for n in d.get("values_added") or {} if n in target and n not in changed and n not in removed_vals}
    return target, removed, only


def _answer_filter(tax, target, removed=()):
    """버릴 답 행(kind answer·control)의 SQL 조건과 인자(D4). 대상 축과 삭제 축(활성 Y→N 포함)에 걸린 답이다.

    적용 대상이 그 축인 승인 질문, 그 축의 Q-GEN·Q-CTL. 삭제 축의 승인 질문은 지금 taxonomy에 남을 수 없으므로
    (적용 대상이 없는 축=값이면 QUESTION_TARGET_INVALID) 삭제 축이 있으면 지금 taxonomy에 없는 승인 질문 답도 버린다.
    """
    axes = sorted(set(target) | set(removed))
    if not axes:
        return "0", []
    qids = sorted(q.qid for q in tax.questions if isinstance(q.target, tuple) and q.target[0] in axes)
    known = sorted(q.qid for q in tax.questions) if removed else []
    gone = ""
    if removed:
        gone = " OR (substr(key, 1, 6) NOT IN ('Q-GEN-', 'Q-CTL-')%s)" % (
            " AND key NOT IN (%s)" % _q(known) if known else "")
    cond = ("(kind='answer' AND (key IN (SELECT qid FROM gen_questions WHERE axis IN (%s))%s%s))"
            " OR (kind='control' AND key IN (SELECT qid FROM ctl_questions WHERE axis IN (%s)))"
            % (_q(axes), " OR key IN (%s)" % _q(qids) if qids else "", gone, _q(axes)))
    return cond, axes + qids + known + axes


def _copy_where(tax, target, removed):
    """기준 실행 labels 중 새 실행으로 옮기지 않을 행의 조건: 대상·삭제 축의 축 행, D4로 버리는 답 행."""
    axes = sorted(set(target) | set(removed))
    ans, args = _answer_filter(tax, target, removed)
    axis_cond = "(kind='axis' AND key IN (%s))" % _q(axes) if axes else "0"
    return "NOT (%s OR %s)" % (axis_cond, ans), axes + args


def _lock_path(ws):
    return ws.path("logs", "axis_update.lock.json")


def _owner_done(con, owner, path):
    """잠금 주인 실행이 이미 끝났거나(finished_at), runs에 없는 채로 LOCK_GRACE_SEC이 지났으면 남은 잠금이다.

    주인은 잠금을 잡은 뒤 plan을 다시 계산하고 나서야 runs 행을 만들므로, 없는 실행은 짧은 유예를 둔다.
    """
    if con is None or not owner:
        return False
    r = con.execute("SELECT finished_at FROM runs WHERE run_id=?", (owner,)).fetchone()
    if r is not None:
        return r[0] is not None
    try:
        return time.time() - os.path.getmtime(path) >= LOCK_GRACE_SEC
    except OSError:
        return True


def _stale(path, con=None):
    """mtime이 LOCK_STALE_SEC보다 오래됐거나 주인 실행이 끝난(없는) 잠금. 실행 중에는 touch_lock이 mtime을 갱신한다."""
    try:
        if time.time() - os.path.getmtime(path) >= LOCK_STALE_SEC:
            return True
    except OSError:
        return True
    return _owner_done(con, _lock_owner(path), path)


def _lock_owner(path):
    try:
        with open(path, encoding="utf-8") as f:
            return (json.loads(f.read() or "{}") or {}).get("run_id")
    except (OSError, ValueError, AttributeError):
        return None


def locked(ws, own=None, con=None):
    """다른 axis-update가 잠금을 잡고 있는지. own(자기 실행 ID)의 잠금과 남은 잠금(_stale)은 잡힌 것으로 보지 않는다."""
    path = _lock_path(ws)
    return os.path.exists(path) and not _stale(path, con) and (own is None or _lock_owner(path) != own)


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def acquire_lock(ws, run_id, con=None):
    """잠금 파일(실행 ID·시작 시각)을 배타적으로 만든다. 다른 실행이 잡고 있으면 False.

    남은 잠금은 고유 이름으로 옮긴 뒤 옮긴 파일이 여전히 남은 잠금인지 다시 보고 지운다. 그 사이 갱신된 잠금이면
    되돌리되, 그 자리에 다른 실행의 새 잠금이 이미 있으면 새 잠금은 두고 옮긴 파일만 정리한다.
    """
    path = _lock_path(ws)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        if not _stale(path, con):
            return False
        moved = "%s.stale-%s" % (path, util.new_run_id())
        try:
            os.rename(path, moved)
        except OSError:
            return False  # 다른 실행이 먼저 치웠거나 잡았다
        if not _stale(moved, con):
            if os.path.exists(path):
                _remove(moved)
            else:
                try:
                    os.rename(moved, path)  # 옮기는 사이 갱신된 잠금이었다
                except OSError:
                    _remove(moved)
            return False
        _remove(moved)
    try:
        with open(path, "x", encoding="utf-8") as f:
            f.write(util.dumps({"run_id": run_id, "started_at": util.now_iso()}))
    except FileExistsError:
        return False
    return True


def touch_lock(ws, run_id, new_run_id=None):
    """자기 잠금이면 mtime을 갱신한다(긴 실행이 남은 잠금으로 보이지 않게). new_run_id를 주면 실행 ID를 바꾼다.
    잠금을 잃었으면 False(호출한 실행은 AXIS_UPDATE_LOCK_LOST로 멈춘다)."""
    path = _lock_path(ws)
    if _lock_owner(path) != run_id:
        return False
    try:
        if new_run_id:
            with open(path, "w", encoding="utf-8") as f:
                f.write(util.dumps({"run_id": new_run_id, "started_at": util.now_iso()}))
        else:
            os.utime(path)
    except OSError:
        return False
    return True


def release_lock(ws, run_id, tries=5, wait=0.2):
    """파일의 실행 ID가 run_id일 때만 잠금을 지운다. Windows에서 다른 프로세스가 열고 있으면(PermissionError) 짧게 재시도한다."""
    path = _lock_path(ws)
    if _lock_owner(path) != run_id:
        return
    for i in range(tries):
        try:
            os.remove(path)
            return
        except PermissionError:
            if i + 1 < tries:
                time.sleep(wait)
        except OSError:
            return


def plan(ws, con, tax, own_lock=None):
    """반환: {code(멈출 사유 또는 None), prev_run, target, removed, values_added_only, chunks, dropped_answers,
    dropped_corrections, diff}. 축 이름·건수만 담는다. own_lock(자기 잠금의 실행 ID)은 잠금 검사에서 뺀다."""
    prev = store.latest_label_run(con, finished=True)
    out = {"code": None, "prev_run": prev, "target": [], "removed": [], "values_added_only": [], "chunks": 0,
           "dropped_answers": 0, "dropped_corrections": 0, "diff": None}
    if not prev:
        return dict(out, code=NO_PREVIOUS_RUN)
    sig, _ = taxdiff.previous_signature(con, prev)
    d = taxdiff.diff(sig, taxdiff.axes_signature(tax))
    if d.get("code"):
        return dict(out, code=d["code"])
    target, removed, only = _decide(d, tax)
    out.update(diff=d, target=sorted(target), removed=sorted(removed), values_added_only=sorted(only))
    if not (target or removed):
        return dict(out, code=NO_AXIS_CHANGE)  # 바뀐 축이 지금 비활성 축뿐이면 할 일이 없다
    out["code"] = _reviewed(ws, con, prev) or (AXIS_UPDATE_LOCKED if locked(ws, own_lock, con) else None) \
        or _push_pending(ws, con, prev)
    ans_cond, ans_args = _answer_filter(tax, target, removed)
    out["chunks"] = con.execute("SELECT COUNT(DISTINCT chunk_id) FROM labels WHERE run_id=? AND kind='chunk_type'",
                                (prev,)).fetchone()[0]
    out["dropped_answers"] = con.execute(
        "SELECT COUNT(*) FROM labels WHERE run_id=? AND (%s)" % ans_cond, [prev] + ans_args).fetchone()[0]
    gone = sorted(dropped_axes(out))
    if gone:
        out["dropped_corrections"] = con.execute(
            "SELECT COUNT(*) FROM corrections WHERE target_kind='axis' AND target_key IN (%s)"
            " AND chunk_id IN (SELECT chunk_id FROM labels WHERE run_id=?)" % _q(gone), gone + [prev]).fetchone()[0]
    return out


def start(ws, con, p, tax, run_id=None):
    """새 axis-update 실행을 만들고 기준 실행의 행을 옮긴다. run_id를 주면 그 실행의 행을 지우고 다시 만든다(멱등).
    run_id가 아직 runs에 없으면 그 ID로 실행을 만든다(잠금을 잡을 때 정한 ID).

    반환: 실행 ID. 옮기는 행: file_locations(기준 실행이 본 위치), labels(비대상 축·chunk_type·남는 답·추출),
    failures(stage='label' 적재 가드, 기준 실행에서 분류에 실패한 chunk의 stage='classify'). meta: parent_run:<run>, axis_update:<run>, axis_update_confirmed:<run>.
    """
    from labelbot import finals
    from labelbot.pipeline import start_run

    prev, target = p["prev_run"], set(p["target"])
    if run_id is None or not con.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone():
        r = con.execute("SELECT input_root FROM runs WHERE run_id=?", (prev,)).fetchone()
        run_id = start_run(con, ws, COMMAND, r[0] if r else None, run_id=run_id or new_run_id(prev))
    for table, cond in (("labels", "run_id=?"), ("failures", "run_id=?"), ("flagged_chunks", "run_id=?"),
                        ("candidates", "run_id=? AND source<>'review'")):
        con.execute("DELETE FROM %s WHERE %s" % (table, cond), (run_id,))
    # 같은 기준으로 먼저 만든 axis-update 실행(중단 등)이 가져간 위치도 이 실행으로 옮긴다.
    con.execute(
        "UPDATE file_locations SET last_seen_run=? WHERE last_seen_run=? OR last_seen_run IN"
        " (SELECT substr(key, %d) FROM meta WHERE substr(key, 1, %d)=? AND value=?)" % (len(_PARENT) + 1, len(_PARENT)),
        (run_id, prev, _PARENT, prev))
    cond, args = _copy_where(tax, target, p["removed"])
    con.execute(
        "INSERT INTO labels(run_id, chunk_id, kind, key, value, status, evidence, confidence, sheet_hashes,"
        " prompt_version, model, created_at) SELECT ?, chunk_id, kind, key, value, status, evidence, confidence,"
        " sheet_hashes, prompt_version, model, created_at FROM labels WHERE run_id=? AND %s ORDER BY id" % cond,
        [run_id, prev] + args)
    con.execute(
        "INSERT INTO failures(run_id, stage, target_id, reason_code, created_at)"
        " SELECT ?, stage, target_id, reason_code, created_at FROM failures WHERE run_id=? AND (stage='label'"
        " OR (stage='classify' AND target_id NOT IN (SELECT chunk_id FROM labels WHERE run_id=? AND kind='chunk_type')))",
        (run_id, prev, prev))
    store.meta_set(con, _PARENT + run_id, prev)
    info = {k: p[k] for k in ("target", "removed", "values_added_only", "dropped_answers", "dropped_corrections")}
    info["axes"] = sorted(a.name for a in tax.active_axes())
    store.meta_set(con, "axis_update:" + run_id, util.dumps(info))
    # 기준 실행에서 확인된 chunk: 대상 축을 뺀 축과 남긴 답으로 확인 해시를 남긴다(D6).
    prev_final = finals.final_labels(con, prev)
    ok = sorted(cid for cid, d in prev_final.items()
                if any(a.get("review") == finals.CONFIRMED for a in list(d["axes"].values()) + list(d["answers"].values())))
    bots = finals.bot_labels(con, run_id, ok)
    store.meta_set(con, "axis_update_confirmed:" + run_id,
                   util.dumps({cid: finals.confirm_hash(bots[cid], target) for cid in ok if cid in bots}))
    con.commit()
    return run_id


def scope_chunks(con, run_id):
    """이 실행이 다시 분류할 chunk: 실행이 본 정상 파일의 chunk 중 chunk_type을 이어받은 것(파일 경로·순서대로).

    기준 실행에서 분류에 실패한 chunk는 빼고 실패 기록(start가 옮긴다)으로 CLASSIFY_FAILED 불량에 남긴다.
    """
    from labelbot.pipeline import content_chunks

    ids = [r[0] for r in con.execute("SELECT DISTINCT file_id FROM file_locations WHERE last_seen_run=?", (run_id,))]
    typed = {r[0] for r in con.execute("SELECT chunk_id FROM labels WHERE run_id=? AND kind='chunk_type'", (run_id,))}
    return [c for c in content_chunks(con, ids) if c["chunk_id"] in typed]
