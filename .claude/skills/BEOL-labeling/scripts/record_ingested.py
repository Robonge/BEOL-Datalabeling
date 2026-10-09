"""이번 실행에서 처리를 마친 파일명을 injested-file-list/<작업 폴더 이름>.json에 남긴다.

work.sqlite만 읽는다(원본은 열지 않는다). 다음 실행의 init_workspace.py가 이 목록으로 중복을 확인한다.

사용: python record_ingested.py --workspace "<작업 폴더>" [--run <실행 ID>]
출력: JSON 한 줄(list_file, count). 파일명은 출력하지 않는다.

목록 파일의 workspace와 input은 기준이 다르다(정보용 필드, 읽는 곳은 init_workspace.py의 files뿐이다).
- workspace: 저장소 루트 기준 상대경로(저장소 밖 작업 폴더면 절대경로).
- input: pipeline.json의 input_root 값 그대로(작업 폴더 기준 상대경로이거나 저장소 밖 절대경로).
"""
import argparse
import datetime
import json
import os
import sys

CODE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, CODE_ROOT)
from labelbot.store import LABEL_COMMANDS, connect_ro, latest_run  # noqa: E402
from labelbot.workspace import is_inside  # noqa: E402

LIST_DIR = os.path.join(CODE_ROOT, "injested-file-list")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--run")
    a = ap.parse_args()
    ws = os.path.abspath(a.workspace)
    db = os.path.join(ws, "work.sqlite")
    if not os.path.isfile(db):
        print(json.dumps({"error": "NO_WORK_DB"}))
        return 2
    con = connect_ro(db)
    q = lambda sql, *p: con.execute(sql, p).fetchall()
    run = a.run or latest_run(con, LABEL_COMMANDS)
    if not run:
        print(json.dumps({"error": "NO_RUN"}))
        return 2
    names = sorted({r[0] for r in q("SELECT l.file_name FROM file_locations l JOIN files f ON f.file_id=l.file_id "
                                    "WHERE l.last_seen_run=? AND f.status='ok'", run)})
    cfg = {}
    try:
        with open(os.path.join(ws, "pipeline.json"), encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        pass
    os.makedirs(LIST_DIR, exist_ok=True)
    out = os.path.join(LIST_DIR, os.path.basename(ws.rstrip("\\/")) + ".json")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        rel = os.path.relpath(ws, CODE_ROOT) if is_inside(ws, CODE_ROOT) else ws
        json.dump({"run_id": run, "workspace": rel.replace("\\", "/"), "input": cfg.get("input_root"),
                   "recorded_at": datetime.datetime.now().isoformat(timespec="seconds"), "files": names},
                  f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps({"list_file": out.replace("\\", "/"), "count": len(names)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    from labelbot import trace  # noqa: E402  마일스톤 M01(stderr 줄, stdout JSON 불변)

    sys.exit(trace.run_main("M01", main))
