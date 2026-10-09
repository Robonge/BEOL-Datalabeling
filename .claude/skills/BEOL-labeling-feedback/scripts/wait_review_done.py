"""검수 화면의 **검수 완료** 버튼 신호(또는 결과 대시보드의 **검수 시작** 신호)를 기다린다(JSON 출력).

화면 서버(`labelbot serve`)는 검수 완료를 누르면 마지막 교정을 inbox/review_<RUN>.json에 쓰고,
완료 신호를 signals/review_done_<RUN>.json에 쓴다. 신호 파일에는 실행 ID, 시각, 건수만 있고
교정 본문은 없다. 교정 내용을 읽는 곳은 여전히 `labelbot apply`의 read_input 한 곳뿐이다.
결과 대시보드의 검수 시작 버튼은 signals/review_start_<RUN>.json(실행 ID, 시각, 파싱 대조 여부)을 쓴다.

- 기본(대기): 이 스크립트가 시작된 뒤에 갱신된 신호가 생길 때까지 기다린다. 예전에 누른 신호로
  바로 넘어가지 않게 하려는 것이다. 그래서 검수 탭을 열기 **전에** 백그라운드로 시작한다.
- --signal start: 완료 대신 검수 시작 신호를 기다린다(BEOL-labeling이 끝날 때 건다).
- --after-start: 완료 신호의 기준 시각을 이 스크립트 시작 대신 검수 시작 신호 시각으로 둔다. 대시보드에서
  검수 화면이 먼저 열린 경우(feedback이 시작 신호로 깨어난 경우)에 쓴다. 그사이 누른 완료도 놓치지 않는다.
- --check: 기다리지 않고 지금 신호가 있는지만 알려 준다. --signal start이면 `pending`(완료 신호보다
  새 시작 신호가 있음)도 알려 준다.

사용: python wait_review_done.py --workspace "<작업 폴더>" --run <실행 ID> [--signal done|start] [--after-start]
      [--check] [--timeout 7000]
"""
import argparse
import datetime
import json
import os
import re
import sys
import time

CODE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, CODE_ROOT)
from labelbot.serve import done_signal_path, start_signal_path  # noqa: E402  신호 경로 규칙은 화면 서버와 하나로 둔다.

_RUN_ID = re.compile(r"^[0-9A-Za-z-]{1,64}$")
COUNT_KEYS = ("edits", "status", "syns", "revisits")


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


def read_start(path):
    """시작 신호에서 파싱 대조 여부만 꺼낸다. 형식이 맞지 않으면 compare는 None."""
    st = os.stat(path)
    out = {"started": True,
           "started_at": datetime.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"), "compare": None}
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        c = doc.get("compare") if isinstance(doc, dict) else None
        if isinstance(c, bool):
            out["compare"] = c
    except (OSError, ValueError, TypeError):
        out["code"] = "SIGNAL_UNREADABLE"
    return out, st.st_mtime


def _mtime(path):
    return os.stat(path).st_mtime if os.path.isfile(path) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--signal", choices=("done", "start"), default="done")
    ap.add_argument("--after-start", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--timeout", type=int, default=7000)
    ap.add_argument("--interval", type=float, default=3.0)
    a = ap.parse_args()
    if not _RUN_ID.match(a.run):
        print(json.dumps({"error": "RUN_ID_INVALID"}))
        return 2
    done_path, start_path = done_signal_path(a.workspace, a.run), start_signal_path(a.workspace, a.run)
    is_start = a.signal == "start"
    path, read = (start_path, read_start) if is_start else (done_path, read_signal)
    if a.check:
        if os.path.isfile(path):
            out, _ = read(path)
        else:
            out = {"started": False} if is_start else {"done": False}
        if is_start:
            st, dn = _mtime(start_path), _mtime(done_path)
            out["pending"] = st is not None and (dn is None or st > dn)
        out["run_id"] = a.run
        print(json.dumps(out, ensure_ascii=False))
        return 0
    start = time.time()
    # 파일 시스템 시각 해상도 차이로 방금 쓴 신호를 놓치지 않도록 1초 여유를 둔다.
    since = start - 1.0
    if os.path.isfile(path):
        since = max(since, os.stat(path).st_mtime)
    if a.after_start and not is_start and _mtime(start_path) is not None:
        # 대시보드에서 시작한 검수: 시작 신호 뒤에 눌린 완료면 이 스크립트보다 먼저 눌렸어도 받는다.
        since = _mtime(start_path)
    print("[wait] 검수 %s 신호 대기 시작 run_id=%s" % ("시작" if is_start else "완료", a.run), file=sys.stderr, flush=True)
    try:
        while time.time() - start < a.timeout:
            if os.path.isfile(path) and os.stat(path).st_mtime > since:
                time.sleep(0.5)  # 서버가 이름 바꾸기를 끝낼 시간
                out, _ = read(path)
                out.update({"run_id": a.run, "waited_s": int(time.time() - start)})
                print(json.dumps(out, ensure_ascii=False))
                return 0
            time.sleep(a.interval)
    except KeyboardInterrupt:
        # 사람이 대기를 끊었다: 실패가 아니다(종료 코드 0, stdout JSON 없음)
        from labelbot import trace

        trace.aborted("M05", a.workspace)
        return 0
    print(json.dumps({"started" if is_start else "done": False, "run_id": a.run, "code": "WAIT_TIMEOUT",
                      "waited_s": int(time.time() - start)}))
    return 0


if __name__ == "__main__":
    from labelbot import trace  # noqa: E402  마일스톤 M05(stderr 줄, stdout JSON 불변)

    sys.exit(trace.run_main("M05", main))
