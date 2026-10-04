"""H5 라벨 분포 알림. 콘솔과 reports/alerts.json에 실행 ID, 조건, 수치, 기준값만 남긴다(본문 없음)."""
import json

from labelbot import util


def na_ratio(con, run_id):
    rows = con.execute(
        "SELECT value FROM labels WHERE run_id=? AND kind='answer'", (run_id,)
    ).fetchall()
    if not rows:
        return None, 0
    na = sum(1 for r in rows if r[0] == "N/A")
    return na / len(rows), len(rows)


def dup_ratio(con, run_id, tax):
    """다중값=Y이고 중복 알림 제외=N인 활성 분류 축만. unknown·해당 없음은 분모·분자에서 뺀다."""
    axes = [a.name for a in tax.axes if a.active and a.kind == "분류" and a.multi and not a.dup_alert_exclude]
    if not axes:
        return None, 0
    q = ("SELECT l.value, l.status FROM labels l WHERE l.run_id=? AND l.kind='axis' AND l.key IN (%s) AND EXISTS("
         "SELECT 1 FROM labels t WHERE t.run_id=l.run_id AND t.chunk_id=l.chunk_id AND t.kind='chunk_type' AND t.value='내용')"
         % ",".join("?" * len(axes)))
    total = multi = 0
    for value, status in con.execute(q, [run_id] + axes):
        if status != "value":
            continue
        vals = [v for v in json.loads(value) if v not in ("해당 없음", "unknown")]
        if not vals:
            continue
        total += 1
        if len(vals) >= 2:
            multi += 1
    return (multi / total if total else None), total


def evaluate(ctx):
    con, run_id, cfg = ctx.con, ctx.run_id, ctx.cfg["alerts"]
    out = []
    r, n = na_ratio(con, run_id)
    if r is not None and r <= cfg["na_ratio_max"] + 1e-12:
        out.append({"condition": "NA_RATIO_LOW", "value": round(r, 4), "threshold": cfg["na_ratio_max"]})
    r, n = dup_ratio(con, run_id, ctx.tax)
    if r is not None and r >= cfg["dup_ratio_min"] - 1e-12:
        out.append({"condition": "DUP_LABEL_HIGH", "value": round(r, 4), "threshold": cfg["dup_ratio_min"]})
    con.execute("DELETE FROM alerts WHERE run_id=?", (run_id,))
    for a in out:
        con.execute(
            "INSERT INTO alerts(run_id, condition, value, threshold) VALUES(?,?,?,?)",
            (run_id, a["condition"], a["value"], a["threshold"]),
        )
        print("[알림] %s 값=%s 기준=%s" % (a["condition"], a["value"], a["threshold"]))
    con.commit()
    path = ctx.ws.path("reports", "alerts.json")
    data = {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    data[run_id] = out
    util.write_text(path, json.dumps(data, ensure_ascii=False, indent=1))
    return out
