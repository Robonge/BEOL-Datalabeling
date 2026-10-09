"""상태·사유 코드 명령(L3c): python -m labelbot status|codes, python3 tools/beol_status.py status|codes(같은 출력).

- status: 작업 폴더의 work.sqlite(runs·failures, 읽기 전용)와 logs/milestones.jsonl(없어도 된다 — 옛 실행)을 읽어
  마일스톤 표(✔/✖/—, 마지막 사유 코드·시각, 대상 실패 건수)와 처음 실패한 마일스톤, "다음에 할 일"을 낸다.
  ID·사유 코드·건수·시각만 낸다(본문·파일명·경로 없음 — 반출 가능).
- codes: 사유 코드 카탈로그(--milestone Mxx면 그 단계용 원인·조치), --entrypoints면 진입점 → 마일스톤 표.
- Python 3.8 문법·표준 라이브러리만, labelbot에서는 3.8 안전 모듈(milestones, reason_codes, trace)만 import한다
  (sqlite3를 직접 연다. labelbot.store·workspace를 거치지 않는다).
"""
import argparse
import json
import os
import pathlib
import sqlite3
import sys

from labelbot import milestones, reason_codes, trace

CODE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACES = os.path.join(CODE_ROOT, "workspaces")
OK, FAIL, NONE = "✔", "✖", "—"
CORE = ("M01", "M02", "M03", "M04", "M05", "M06", "M07", "M08", "M09", "M10")
RUN_COMMANDS = ("run", "ingest", "axis-update", "rules-update")


def _out(text):
    """콘솔 인코딩이 ✔를 못 쓰면 바꿔 쓴다(출력이 깨져도 명령은 끝까지 간다)."""
    try:
        sys.stdout.write(text)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        sys.stdout.write(text.encode(enc, "replace").decode(enc, "replace"))
    sys.stdout.flush()


# ---- 읽기 -------------------------------------------------------------------------

def read_jsonl(ws_root):
    path = os.path.join(ws_root, "logs", trace.JSONL)
    rows = []
    if not os.path.isfile(path):
        return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if isinstance(r, dict) and r.get("milestone") in milestones.NAMES:
                rows.append(r)
    return rows


def read_db(ws_root):
    """(runs 목록 최신순, 최신 라벨·ingest 실행의 failures [(stage, reason_code, 건수)]). DB가 없으면 ([], [])."""
    db = os.path.join(ws_root, "work.sqlite")
    if not os.path.isfile(db):
        return [], []
    con = sqlite3.connect(pathlib.Path(db).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(runs)")]
        if not cols:
            return [], []
        runs = [dict(zip(("run_id", "command", "started_at", "finished_at"), r)) for r in con.execute(
            "SELECT run_id, command, started_at, finished_at FROM runs ORDER BY started_at DESC, run_id DESC")]
        fails = []
        latest = next((r["run_id"] for r in runs if r["command"] in RUN_COMMANDS), None)
        if latest and [r for r in con.execute("PRAGMA table_info(failures)")]:
            fails = [tuple(r) for r in con.execute(
                "SELECT stage, reason_code, COUNT(*) FROM failures WHERE run_id=? GROUP BY stage, reason_code "
                "ORDER BY COUNT(*) DESC, stage, reason_code", (latest,))]
        return runs, fails
    except sqlite3.Error:
        return [], []
    finally:
        con.close()


def events(ws_root):
    """마일스톤별 마지막 상태 {mid: {status, code, ts, run_id}}, POST 실패 수 {mid: n}.
    milestones.jsonl과 runs 표(옛 실행: 끝남 = ✔, 미완료 = RUN_UNFINISHED)를 시각순으로 합친다."""
    evs = []
    runs, fails = read_db(ws_root)
    rows = read_jsonl(ws_root)
    traced = set((r.get("milestone"), r.get("run_id")) for r in rows)
    for r in runs:
        for mid in milestones.RUN_COMMAND_MILESTONES.get(r["command"], ()):
            if (mid, r["run_id"]) in traced:
                continue  # milestones.jsonl에 그 실행의 기록이 있으면 그것을 쓴다
            if r["finished_at"]:
                evs.append({"milestone": mid, "status": "ok", "ts": r["finished_at"], "run_id": r["run_id"],
                            "reason_code": None, "src": 0})
            else:
                evs.append({"milestone": mid, "status": "fail", "ts": r["started_at"] or "", "run_id": r["run_id"],
                            "reason_code": "RUN_UNFINISHED", "src": 0})
    posts = {}
    for r in rows:
        if r.get("status") == "post_fail":
            posts[r["milestone"]] = posts.get(r["milestone"], 0) + 1
            continue
        evs.append(dict(r, src=1))
    # 같은 시각이면 jsonl(src=1)이 runs보다 뒤(우선)
    evs.sort(key=lambda e: (e.get("ts") or "", e["src"]))
    last = {}
    for e in evs:
        last[e["milestone"]] = e
    return last, posts, runs, fails


# ---- status ------------------------------------------------------------------------

def _mark(e):
    if e is None:
        return NONE
    return FAIL if e.get("status") == "fail" else OK  # abort(Ctrl+C)는 실패가 아니다


def render(ws_root, name=None):
    last, posts, runs, fails = events(ws_root)
    per_ms = {}
    for stage, code, n in fails:
        mid = milestones.STAGE_MILESTONE.get(stage)
        if mid:
            c = per_ms.setdefault(mid, [0, code])
            c[0] += n
    lines = ["작업 폴더: %s" % (name or os.path.basename(os.path.abspath(ws_root).rstrip("\\/")))]
    rr = next((r for r in runs if r["command"] in RUN_COMMANDS), None)
    if rr:
        lines.append("최근 실행: %s (%s, %s)" % (rr["run_id"], rr["command"], "끝남" if rr["finished_at"] else "미완료"))
    else:
        lines.append("최근 실행: 없음")
    if not os.path.isfile(os.path.join(ws_root, "logs", trace.JSONL)):
        lines.append("milestones.jsonl 없음 — runs·failures 표로만 표시")
    lines.append("%-22s %-4s %-24s %-21s %s" % ("마일스톤", "상태", "마지막 사유", "시각(UTC)", "대상 실패"))
    shown = [m for m in milestones.IDS if m in last or m in per_ms or m in posts or m in CORE]
    first = None
    for mid in shown:
        e = last.get(mid)
        mark = _mark(e)
        if mark == FAIL and first is None:
            first = (mid, e)
        code = (e or {}).get("reason_code") or ("-" if e else "")
        if e and e.get("status") == "skip":
            code = "건너뜀 %s" % code
        extra = []
        if mid in per_ms:
            extra.append("%d건(%s)" % (per_ms[mid][0], per_ms[mid][1]))
        if mid in posts:
            extra.append("POST 실패 %d" % posts[mid])
        row = "%-22s %-4s %-24s %-21s %s" % (milestones.label(mid), mark, code, (e or {}).get("ts") or "", " ".join(extra))
        lines.append(("▶ " if first and first[0] == mid else "  ") + row.rstrip())
    if first:
        mid, e = first
        d = reason_codes.describe(e.get("reason_code") or "", mid)
        lines.append("처음 실패: %s  사유=%s" % (milestones.label(mid), e.get("reason_code")))
        lines.append("  원인: %s" % d["원인"])
        lines.append("다음에 할 일: %s" % d["조치"])
        lines.append("  사유 코드 목록: python -m labelbot codes --milestone %s" % mid)
    else:
        nxt = next((m for m in CORE if m not in last), None)
        lines.append("처음 실패: 없음")
        if nxt:
            lines.append("다음에 할 일: 다음 단계 %s — %s" % (milestones.label(nxt), milestones.DESCRIPTIONS[nxt]))
        else:
            lines.append("다음에 할 일: 없음")
    return "\n".join(lines) + "\n"


def _workspace_dirs():
    if not os.path.isdir(WORKSPACES):
        return []
    return sorted(d for d in os.listdir(WORKSPACES)
                  if not d.startswith("_") and os.path.isdir(os.path.join(WORKSPACES, d)))


def add_status_args(p):
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--workspace", help="작업 폴더")
    g.add_argument("--all-workspaces", action="store_true", help="코드 폴더 workspaces/ 아래 전부(+ 작업 폴더 밖 명령 기록)")


def cmd_status(args):
    if args.workspace:
        ws = os.path.abspath(args.workspace)
        if not os.path.isdir(ws):
            sys.stderr.write("[오류] WORKSPACE_NOT_FOUND\n")
            trace.fail_code("WORKSPACE_NOT_FOUND")
            return 1
        _out(render(ws))
        return 0
    names = _workspace_dirs()
    blocks = [render(os.path.join(WORKSPACES, n), n) for n in names]
    tr = trace.trace_root()
    if os.path.isfile(os.path.join(tr, trace.JSONL)):
        blocks.append(_render_trace(tr))
    if not blocks:
        blocks = ["작업 폴더 없음\n"]
    _out("\n".join(blocks))
    return 0


def _render_trace(trace_dir):
    """작업 폴더 밖 명령(code_engrbot·nightly·작업 폴더 오류)의 마지막 상태."""
    rows = []
    path = os.path.join(trace_dir, trace.JSONL)
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if isinstance(r, dict) and r.get("milestone") in milestones.NAMES and r.get("status") != "post_fail":
                rows.append(r)
    last = {}
    for r in sorted(rows, key=lambda r: r.get("ts") or ""):
        last[r["milestone"]] = r
    lines = ["작업 폴더 밖 명령(workspaces/_trace)"]
    for mid in milestones.IDS:
        if mid in last:
            e = last[mid]
            lines.append("  %-22s %-4s %-24s %s" % (milestones.label(mid), _mark(e), e.get("reason_code") or "-",
                                                     e.get("ts") or ""))
    return "\n".join(lines) + "\n"


# ---- codes -------------------------------------------------------------------------

def add_codes_args(p):
    p.add_argument("--milestone", help="이 마일스톤(Mxx)의 사유 코드와 그 단계용 원인·조치만")
    p.add_argument("--entrypoints", action="store_true", help="진입점(명령·스크립트) → 마일스톤 표")


def cmd_codes(args):
    if args.entrypoints:
        lines = ["마일스톤:"]
        lines += ["  %-20s %s" % (milestones.label(m), milestones.DESCRIPTIONS[m]) for m in milestones.IDS]
        lines.append("진입점 → 마일스톤:")
        for key in sorted(milestones.ENTRYPOINTS):
            ms = milestones.ENTRYPOINTS[key]
            note = " (읽기 전용: 실패 블록만)" if key in milestones.QUIET else ""
            lines.append("  %-62s %s%s" % (key, ",".join(ms), note))
        _out("\n".join(lines) + "\n")
        return 0
    mid = args.milestone
    if mid:
        mid = mid.upper()
        if mid not in milestones.NAMES:
            sys.stderr.write("[오류] MILESTONE_UNKNOWN\n")
            trace.fail_code("MILESTONE_UNKNOWN")
            return 1
        keys = reason_codes.for_milestone(mid) + sorted(
            k for k, e in reason_codes.CODES.items() if reason_codes.ANY in e["milestones"] and mid not in e["milestones"])
        lines = ["%s — %s" % (milestones.label(mid), milestones.DESCRIPTIONS[mid])]
    else:
        keys = sorted(reason_codes.CODES)
        lines = []
    for k in keys:
        e = reason_codes.CODES[k]
        ov = e["by_milestone"].get(mid) or {}
        cause, action = ov.get("원인", e["원인"]), ov.get("조치", e["조치"])
        ms = " ".join(e["milestones"])
        lines.append("%s  [%s]" % (k, ms))
        lines.append("  원인: %s" % cause)
        lines.append("  조치: %s" % action)
        if e["담당자"]:
            lines.append("  담당자에게: %s" % e["담당자"])
    _out("\n".join(lines) + "\n")
    return 0


def main(argv=None):
    """tools/beol_status.py 진입점: status|codes (python -m labelbot status|codes와 같은 출력)."""
    p = argparse.ArgumentParser(prog="beol_status", description="마일스톤 상태·사유 코드(배포판 python3 3.8+)")
    sub = p.add_subparsers(dest="cmd")
    sub.required = True
    add_status_args(sub.add_parser("status", help="마일스톤 표·처음 실패·다음에 할 일"))
    add_codes_args(sub.add_parser("codes", help="사유 코드 카탈로그·진입점 표"))
    args = p.parse_args(argv)
    return cmd_status(args) if args.cmd == "status" else cmd_codes(args)
