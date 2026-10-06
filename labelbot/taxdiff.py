"""taxonomy 변경 감지: 실행 기록의 축 서명과 지금 taxonomy를 비교한다. 축·값 이름과 건수만 다루고 정의 문장은 다루지 않는다."""
import hashlib
import json

from labelbot import store

NO_PREVIOUS_RUN = "NO_PREVIOUS_RUN"
_FIELDS = ("kind", "multi", "hierarchy", "active")


def axes_signature(tax):
    """축마다 이름·종류·다중값·계층·활성·값 개수·값 이름 목록. 실행 meta의 axes_signature로 저장된다."""
    return [
        {"name": a.name, "kind": a.kind, "multi": bool(a.multi), "hierarchy": bool(a.hierarchical),
         "active": bool(a.active), "n_values": len(a.values), "values": sorted(v.name for v in a.values),
         "values_hash": hashlib.sha256("\n".join(sorted(v.name for v in a.values)).encode("utf-8")).hexdigest()[:12]}
        for a in tax.axes
    ]


def _normalize(prev):
    """(축 이름 → 서명 dict, partial 여부). 알아볼 수 없으면 (None, False)."""
    if isinstance(prev, dict):  # 옛 실행의 axis_kinds {이름: 종류}
        return {name: {"name": name, "kind": kind} for name, kind in prev.items()}, True
    if isinstance(prev, list) and all(isinstance(x, dict) and "name" in x for x in prev):
        return {x["name"]: x for x in prev}, False
    return None, False


def diff(prev, cur):
    """prev: 서명 목록 또는 옛 axis_kinds 매핑(이름·종류만 비교하고 partial=true). cur: 서명 목록."""
    if prev is None:
        return {"code": NO_PREVIOUS_RUN}
    old, partial = _normalize(prev)
    if old is None:
        return {"code": NO_PREVIOUS_RUN}
    new = {x["name"]: x for x in cur}
    fields = ("kind",) if partial else _FIELDS
    changed, values_added, values_removed = [], {}, {}
    for name in (n for n in new if n in old):
        diffs = [f for f in fields if old[name].get(f) != new[name].get(f)]
        if not partial and isinstance(old[name].get("values"), list) and isinstance(new[name].get("values"), list):
            # 값 이름 목록이 있으면 이름으로 비교한다. 이전 값이 모두 남고 새 값만 생긴 경우만 순수 추가다.
            plus = set(new[name]["values"]) - set(old[name]["values"])
            minus = set(old[name]["values"]) - set(new[name]["values"])
            if plus:
                values_added[name] = len(plus)
            if minus:
                values_removed[name] = len(minus)
                diffs.append("values")
        elif not partial:
            # 값 이름 목록이 없는 옛 서명: 개수·해시로만 본다. 순수 추가인지 알 수 없으므로 값 변화는 모두 values로 본다.
            delta = new[name]["n_values"] - old[name].get("n_values", 0)
            if delta > 0:
                values_added[name] = delta
            elif delta < 0:
                values_removed[name] = -delta
            old_hash, new_hash = old[name].get("values_hash"), new[name].get("values_hash")
            if delta or (old_hash and new_hash and old_hash != new_hash):
                diffs.append("values")
        if diffs:
            changed.append({"axis": name, "fields": diffs})
    out = {"added": [n for n in new if n not in old], "removed": [n for n in old if n not in new],
           "changed": changed, "values_added": values_added}
    if values_removed:
        out["values_removed"] = values_removed
    if partial:
        out["partial"] = True
    return out


def needs_rerun(d):
    return bool(d.get("added") or d.get("removed") or d.get("changed") or d.get("values_added")
                or d.get("values_removed"))


def summary_line(d):
    if d.get("code") == NO_PREVIOUS_RUN:
        return "[taxonomy] 지난 실행 기록이 없어 비교할 수 없다"

    def names(key, sign):
        n = len(d[key])
        return "%s%d(%s)" % (sign, n, ", ".join(d[key])) if n else "%s0" % sign

    removed_n = sum(d.get("values_removed", {}).values())
    head = "[taxonomy] 지난 실행 대비 축 %s %s · 값 +%d%s · 종류/설정 변경 %d" % (
        names("added", "+"), names("removed", "-"), sum(d["values_added"].values()),
        " 값 -%d" % removed_n if removed_n else "", len(d["changed"]))
    if d.get("partial"):
        head += " (이름·종류만 비교)"
    return head + (" → 전체 재실행 필요" if needs_rerun(d) else " → 변경 없음")


def previous_signature(con, run_id=None):
    """마지막 라벨 실행(run_id를 주면 그 실행) meta의 axes_signature, 없으면 axis_kinds. 둘 다 없거나 실행이 없으면 (None, run_id)."""
    run_id = run_id or store.latest_label_run(con)
    if not run_id:
        return None, None
    for key in ("axes_signature:" + run_id, "axes_signature", "axis_kinds"):
        raw = store.meta_get(con, key)
        if raw:
            try:
                return json.loads(raw), run_id
            except ValueError:
                continue
    return None, run_id


def compare_workspace(ws, tax):
    """(diff, run_id). work.sqlite의 마지막 실행과 지금 taxonomy를 비교한다."""
    con = store.connect(ws.work_db)
    try:
        prev, run_id = previous_signature(con)
    finally:
        con.close()
    return diff(prev, axes_signature(tax)), run_id
