"""검수 화면의 **검수 완료** 버튼 신호를 기다린다(JSON 출력).

화면 서버(`labelbot serve`)는 검수 완료를 누르면 마지막 교정을 inbox/review_<RUN>.json에 쓰고,
완료 신호를 signals/review_done_<RUN>.json에 쓴다. 신호 파일에는 실행 ID, 시각, 건수만 있고
교정 본문은 없다. 교정 내용을 읽는 곳은 여전히 `labelbot apply`의 read_input 한 곳뿐이다.

- 기본(대기): 이 스크립트가 시작된 뒤에 갱신된 신호가 생길 때까지 기다린다. 예전에 누른 신호로
  바로 넘어가지 않게 하려는 것이다. 그래서 검수 탭을 열기 **전에** 백그라운드로 시작한다.
- --check: 기다리지 않고 지금 신호가 있는지만 알려 준다.

사용: python wait_review_done.py --workspace "<작업 폴더>" --run <실행 ID> [--check] [--timeout 7000]
"""
import argparse
import datetime
import json
import os
import re
import sys
import time

_RUN_ID = re.compile(r"^[0-9A-Za-z-]{1,64}$")
COUNT_KEYS = ("edits", "status", "syns", "revisits")


def signal_path(ws, run):
    return os.path.join(ws, "signals", "review_done_%s.json" % run)


def read_signal(path):
    """건수만 꺼낸다. 형식이 맞지 않으면 counts는 None."""
    st = os.stat(path)
    out = {"done": True, "done_at": datetime.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
           "counts": None}
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        c = doc.get("counts") if isinstance(doc, dict) else None
        if isinstance(c, dict):
            out["counts"] = {k: int(c.get(k) or 0) for k in COUNT_KEYS}
    except (OSError, ValueError, TypeError):
        out["code"] = "SIGNAL_UNREADABLE"
    return out, st.st_mtime


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--timeout", type=int, default=7000)
    ap.add_argument("--interval", type=float, default=3.0)
    a = ap.parse_args()
    if not _RUN_ID.match(a.run):
        print(json.dumps({"error": "RUN_ID_INVALID"}))
        return 2
    path = signal_path(a.workspace, a.run)
    if a.check:
        if os.path.isfile(path):
            out, _ = read_signal(path)
        else:
            out = {"done": False}
        out["run_id"] = a.run
        print(json.dumps(out, ensure_ascii=False))
        return 0
    start = time.time()
    # 파일 시스템 시각 해상도 차이로 방금 쓴 신호를 놓치지 않도록 1초 여유를 둔다.
    since = start - 1.0
    if os.path.isfile(path):
        since = max(since, os.stat(path).st_mtime)
    print("[wait] 검수 완료 신호 대기 시작 run_id=%s" % a.run, file=sys.stderr, flush=True)
    while time.time() - start < a.timeout:
        if os.path.isfile(path) and os.stat(path).st_mtime > since:
            time.sleep(0.5)  # 서버가 이름 바꾸기를 끝낼 시간
            out, _ = read_signal(path)
            out.update({"run_id": a.run, "waited_s": int(time.time() - start)})
            print(json.dumps(out, ensure_ascii=False))
            return 0
        time.sleep(a.interval)
    print(json.dumps({"done": False, "run_id": a.run, "code": "WAIT_TIMEOUT", "waited_s": int(time.time() - start)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
