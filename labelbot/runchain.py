"""실행 체인: 이전 실행을 이어받는 부분 재라벨링 실행(axis-update·rules-update)의 공용 부분.

- 부분 실행은 meta parent_run:<run>에 기준 실행을, <종류>:<run>에 run_info 형식의 정보를 남긴다.
  axis-update는 axis_update:<run>, rules-update는 rules_update:<run>(target·removed·values_added_only는 빈 목록).
- chain은 두 종류 모두 부모를 따라 올라간다. 보통 실행(run)을 만나면 멈춘다.
- 기준 실행 조건(사람 검수 끝남, 적재 끝남)과 기준보다 뒤에 정렬되는 실행 ID도 여기 둔다.
잠금(logs/axis_update.lock.json)은 axisupdate에 있고 rules-update도 같은 잠금을 쓴다.
"""
import os
import time

from labelbot import store, util

PARENT = "parent_run:"
PREV_NOT_REVIEWED, REVIEW_IN_PROGRESS = "PREV_NOT_REVIEWED", "REVIEW_IN_PROGRESS"
PREV_PUSH_PENDING = "PREV_PUSH_PENDING"
# (command, meta 접두어). 확인 상태는 <접두어>_confirmed:<run>이다.
KINDS = (("axis-update", "axis_update"), ("rules-update", "rules_update"))


def run_info(con, run_id):
    """부분 실행이면 {command, run_id, parent, target, removed, values_added_only, axes, confirmed, 건수…}, 아니면 None.

    axes는 그 실행이 라벨을 가진 활성 축, confirmed는 이어받은 확인 상태({chunk_id: 확인 해시})다.
    """
    if not run_id:
        return None
    for command, prefix in KINDS:
        info = store.meta_json(con, "%s:%s" % (prefix, run_id))
        if isinstance(info, dict):
            break
    else:
        return None
    info = dict(info, command=command, run_id=run_id, parent=store.meta_get(con, PARENT + run_id))
    for k in ("target", "removed", "values_added_only", "axes"):
        info[k] = list(info.get(k) or [])
    info["confirmed"] = store.meta_json(con, "%s_confirmed:%s" % (prefix, run_id)) or {}
    return info


def chain(con, run_id):
    """run_id부터 부모를 따라 올라가는 부분 실행 정보 목록(가까운 실행이 먼저). 보통 실행을 만나면 멈춘다."""
    out, seen = [], set()
    while run_id and run_id not in seen:
        seen.add(run_id)
        info = run_info(con, run_id)
        if info is None:
            break
        out.append(info)
        run_id = info["parent"]
    return out


def dropped_axes(info):
    """이전 교정을 적용하지 않는 축: 삭제 축과, 값 추가만 된 축을 뺀 대상 축(D5). rules-update는 없다."""
    return (set(info["target"]) - set(info["values_added_only"])) | set(info["removed"])


def reviewed(ws, con, prev):
    """기준 실행의 사람 검수 상태: None(끝남 또는 검수할 불량 없음), REVIEW_IN_PROGRESS, PREV_NOT_REVIEWED."""
    from labelbot.serve import done_signal_path, start_signal_path

    if os.path.isfile(done_signal_path(ws.root, prev)):
        return None
    if con.execute("SELECT 1 FROM corrections WHERE review_run_id=? LIMIT 1", (prev,)).fetchone():
        return None
    if not con.execute("SELECT 1 FROM flagged_chunks WHERE run_id=? LIMIT 1", (prev,)).fetchone():
        return None
    return REVIEW_IN_PROGRESS if os.path.isfile(start_signal_path(ws.root, prev)) else PREV_NOT_REVIEWED


def push_pending(ws, con, prev):
    """supabase를 쓰는데 기준 실행의 확정 라벨이 아직 다 적재되지 않았으면 PREV_PUSH_PENDING(vectorpush 기록 재사용).

    부분 실행은 file_locations를 새 실행으로 옮기므로, 그 뒤에는 기준 실행을 embed·push할 수 없다.
    """
    if not (ws.config.get("supabase") or {}).get("enabled"):
        return None
    from labelbot import vectorpush

    return PREV_PUSH_PENDING if vectorpush.unpushed(ws, con, prev) else None


def new_run_id(prev):
    """기준 실행보다 뒤에 정렬되는 실행 ID(최신 실행은 run_id 정렬로 고른다)."""
    run_id = util.new_run_id()
    while run_id <= prev:
        time.sleep(0.2)
        run_id = util.new_run_id()
    return run_id
