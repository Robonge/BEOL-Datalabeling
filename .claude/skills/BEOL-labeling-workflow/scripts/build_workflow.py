"""BEOL 라벨링 워크플로 HTML 생성: 템플릿에 최신 실행의 건수를 채워 docs/workflow.html로 쓴다.

work.sqlite를 읽기 전용으로 열고 건수·사유 코드·답 분포만 넣는다. 본문·파일명·경로·재검토 메모는 넣지 않는다.
작업 폴더를 주지 않으면 코드 폴더 옆 261004_BEOL_* 중 work.sqlite가 가장 최근에 바뀐 폴더를 쓴다.

사용: python build_workflow.py [--workspace "<작업 폴더>"] [--run <실행 ID>] [--out "<html 경로>"]
출력: JSON 한 줄(out, workspace, run_id, 채운 항목 수).
"""
import argparse
import datetime
import glob
import json
import os
import sqlite3
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CODE_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
TEMPLATE = os.path.join(HERE, "..", "assets", "workflow_template.html")
SUMMARY = os.path.join(CODE_ROOT, ".claude", "skills", "BEOL-labeling", "scripts", "summary.py")
PLACEHOLDER = "/*__LIVE__*/null"


def latest_workspace():
    cands = [d for d in glob.glob(os.path.join(os.path.dirname(CODE_ROOT), "261004_BEOL_*"))
             if os.path.isfile(os.path.join(d, "work.sqlite"))]
    return max(cands, key=lambda d: os.path.getmtime(os.path.join(d, "work.sqlite"))) if cands else None


def live_data(ws, run):
    args = [sys.executable, SUMMARY, "--workspace", ws] + (["--run", run] if run else [])
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    summ = json.loads(subprocess.run(args, capture_output=True, text=True, encoding="utf-8", env=env, check=True).stdout)
    run = summ.get("run_id")
    con = sqlite3.connect("file:%s?mode=ro" % os.path.join(ws, "work.sqlite").replace("\\", "/"), uri=True)
    q = lambda sql, *p: con.execute(sql, p).fetchall()
    ext = {e or "(없음)": n for e, n in q(
        "SELECT f.ext, COUNT(DISTINCT f.file_id) FROM files f JOIN file_locations l ON l.file_id=f.file_id"
        " WHERE l.last_seen_run=? GROUP BY 1", run)}
    ans = {"com": {}, "gen": {}}
    for key, val, n in q("SELECT key, value, COUNT(*) FROM labels WHERE run_id=? AND kind='answer' GROUP BY 1, 2", run):
        d = ans["gen" if (key or "").startswith("Q-GEN-") else "com"]
        d[val] = d.get(val, 0) + n
    gen_q = q("SELECT COUNT(DISTINCT key) FROM labels WHERE run_id=? AND kind='answer' AND key LIKE 'Q-GEN-%'", run)[0][0]
    stages = {s: n for s, n in q(
        "SELECT stage, COUNT(DISTINCT target_id) FROM failures WHERE run_id=? GROUP BY 1", run)}
    con.close()
    fails = summ.get("failures") or {}
    return {
        "run_id": run,
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "ext": ext,
        "files_ok": (summ.get("files") or {}).get("ok"),
        "files_failed": sum(((summ.get("files") or {}).get("failed") or {}).values()),
        "chunks": summ.get("chunks"),
        "extract_codes": {k.split(":", 1)[1]: n for k, n in fails.items() if k.startswith("extract:")},
        "extract_warn": sum(n for k, n in fails.items() if k.startswith("extract:")),
        "classify_failed": stages.get("classify", 0),
        "question_failed": stages.get("question_gen", 0),
        "label_failed": stages.get("label", 0),
        "gen_q": gen_q,
        "com": ans["com"],
        "gen": ans["gen"],
        "alerts": summ.get("alerts") or [],
        "flagged_total": (summ.get("flagged") or {}).get("total"),
        "flagged_by": (summ.get("flagged") or {}).get("by_reason") or {},
        "cand_new": (summ.get("candidates") or {}).get("new_value", 0),
        "cand_syn": (summ.get("candidates") or {}).get("synonym", 0),
        "revisits_total": (summ.get("revisits") or {}).get("total", 0),
        "pushed_ok": summ.get("pushed_ok"),
        "embeddings": summ.get("embeddings"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace")
    ap.add_argument("--run")
    ap.add_argument("--out", default=os.path.join(CODE_ROOT, "docs", "workflow.html"))
    a = ap.parse_args()
    with open(TEMPLATE, encoding="utf-8") as f:
        tpl = f.read()
    if tpl.count(PLACEHOLDER) != 1:
        print(json.dumps({"error": "TEMPLATE_PLACEHOLDER"}))
        return 2
    ws = a.workspace or latest_workspace()
    live = {}
    if ws and os.path.isfile(os.path.join(ws, "work.sqlite")):
        live = live_data(ws, a.run)
    payload = json.dumps(live, ensure_ascii=False).replace("</", "<\\/")
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(tpl.replace(PLACEHOLDER, payload))
    print(json.dumps({"out": a.out.replace("\\", "/"), "workspace": (ws or "").replace("\\", "/") or None,
                      "run_id": live.get("run_id"), "fields": len(live)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
