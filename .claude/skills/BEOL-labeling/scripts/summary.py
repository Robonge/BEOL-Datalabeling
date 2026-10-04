"""작업 폴더 상태 요약(JSON). work.sqlite만 읽고 본문·파일명은 출력하지 않는다.

사용: python summary.py --workspace "<작업 폴더>" [--run <실행 ID>]
"""
import argparse
import json
import os
import sqlite3
import sys

CODE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--run")
    a = ap.parse_args()
    db = os.path.join(a.workspace, "work.sqlite")
    if not os.path.isfile(db):
        print(json.dumps({"error": "NO_WORK_DB"}))
        return 2
    con = sqlite3.connect("file:%s?mode=ro" % db.replace("\\", "/"), uri=True)
    q = lambda sql, *p: con.execute(sql, p).fetchall()
    run = a.run or (q("SELECT run_id FROM runs WHERE command='run' ORDER BY run_id DESC LIMIT 1") or [[None]])[0][0]
    out = {"run_id": run}
    if run:
        files = q("SELECT f.status, f.reason_code, COUNT(DISTINCT f.file_id) FROM files f JOIN file_locations l "
                  "ON l.file_id=f.file_id WHERE l.last_seen_run=? GROUP BY 1,2", run)
        out["files"] = {"ok": sum(n for s, _, n in files if s == "ok"),
                        "failed": {r or "?": n for s, r, n in files if s != "ok"}}
        out["chunks"] = q("SELECT COUNT(DISTINCT chunk_id) FROM labels WHERE run_id=? AND kind='chunk_type'", run)[0][0]
        out["failures"] = {"%s:%s" % (s, r): n for s, r, n in q(
            "SELECT stage, reason_code, COUNT(*) FROM failures WHERE run_id=? GROUP BY 1,2", run)}
        flagged = [json.loads(r[0]) for r in q("SELECT reason_codes FROM flagged_chunks WHERE run_id=?", run)]
        reasons = {}
        for codes in flagged:
            for c in codes:
                reasons[c] = reasons.get(c, 0) + 1
        out["flagged"] = {"total": len(flagged), "by_reason": reasons}
        out["alerts"] = [{"condition": c, "value": v, "threshold": t}
                         for c, v, t in q("SELECT condition, value, threshold FROM alerts WHERE run_id=?", run)]
        out["answers"] = {v: n for v, n in q(
            "SELECT value, COUNT(*) FROM labels WHERE run_id=? AND kind='answer' GROUP BY 1", run)}
        out["candidates"] = {k: n for k, n in q(
            "SELECT kind, COUNT(DISTINCT content) FROM candidates WHERE run_id=? GROUP BY 1", run)}
        corr = q("SELECT target_kind, human_value, recheck FROM corrections WHERE review_run_id=?", run)
        out["corrections"] = {
            "axis": sum(1 for k, _, _ in corr if k == "axis"),
            "answer": sum(1 for k, _, _ in corr if k == "answer"),
            "confirmed": sum(1 for k, v, _ in corr if k == "chunk" and v == '"confirmed"'),
            "undecidable_image": sum(1 for k, v, _ in corr if k == "chunk" and v == '"undecidable_image"'),
            "recheck": sum(1 for k, _, r in corr if k in ("axis", "answer") and r),
        }
        out["review_synonyms"] = q(
            "SELECT COUNT(DISTINCT content) FROM candidates WHERE source='review' AND run_id=?", run)[0][0]
        out["embeddings"] = q("SELECT COUNT(*) FROM chunk_embeddings WHERE run_id=?", run)[0][0]
    out["compare_marks"] = {s: n for s, n in q("SELECT status, COUNT(*) FROM compare_marks GROUP BY 1")}
    out["pushed_ok"] = q("SELECT COUNT(DISTINCT chunk_id) FROM vector_push_log WHERE result_code='OK'")[0][0]
    # taxonomy 재검토 요청: 건수만 낸다(메모·제안 값은 읽지 않는다). 읽기 전용이라 마이그레이션 전 DB면 표가 없다.
    out["revisits"] = {"run": 0, "total": 0, "runs": 0, "by_reason": {}}
    if q("SELECT 1 FROM sqlite_master WHERE type='table' AND name='revisit_requests'"):
        out["revisits"] = {
            "run": q("SELECT COUNT(*) FROM revisit_requests WHERE review_run_id=?", run)[0][0] if run else 0,
            "total": q("SELECT COUNT(*) FROM revisit_requests")[0][0],
            "runs": q("SELECT COUNT(DISTINCT review_run_id) FROM revisit_requests")[0][0],
            "by_reason": {k: n for k, n in q(
                "SELECT reason, COUNT(*) FROM revisit_requests WHERE review_run_id=? GROUP BY 1", run)} if run else {},
        }
    try:
        # 사람이 고치는 입력 파일은 labelbot의 read_input으로만 연다(CLAUDE.md).
        sys.path.insert(0, CODE_ROOT)
        from labelbot.ingest import read_input

        cfg = json.loads(read_input(os.path.join(a.workspace, "pipeline.json"), None, expect="text"))
        out["supabase_enabled"] = bool(cfg.get("supabase", {}).get("enabled"))
    except (OSError, ValueError, ImportError):
        out["supabase_enabled"] = None
    inbox = os.path.join(a.workspace, "inbox")
    names = sorted(os.listdir(inbox)) if os.path.isdir(inbox) else []
    out["inbox"] = {"review": [n for n in names if n.lower().startswith("review_") and n.lower().endswith(".json")],
                    "compare": [n for n in names if n.lower().startswith("compare_") and n.lower().endswith(".json")]}
    con.close()
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
