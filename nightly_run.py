"""Code-Engr-bot과 Domain-Engr-bot을 사람 없이 한 번 돌리고, 사람이 볼 일을 아침 목록으로 남긴다.

실행: python nightly_run.py [--recent 3] [--dry-run]
예약(작업 스케줄러 등)은 사람이 따로 건다. 이 파일은 실행만 한다.

- 되돌릴 수 있는 일만 한다: 코드 검수, 축·규칙 점검(읽기), 교정 장부, 규칙 후보, 도메인 질문 생성.
- 재라벨링·적재·승인·taxonomy.json 쓰기는 하지 않고 morning.md에 할 일로 올린다.
- 한 단계가 실패해도 다음 단계로 넘어간다. 기록에는 단계 이름·종료 코드·건수만 남긴다.
- 출력: workspaces/_nightly/<YYYYMMDD>/steps.jsonl, morning_queue.jsonl, morning.md
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
WS_DIR = os.path.join(ROOT, "workspaces")
OUT_DIR = os.path.join(WS_DIR, "_nightly")
TIMEOUT = 15 * 60
SEVERITY_ORDER = {"critical": 0, "action": 1, "info": 2}


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def run(step, args, dry_run, steps):
    """python -m <args>를 돌리고 (rc, stdout)을 돌려준다. 실패해도 예외를 밖으로 내지 않는다."""
    cmd = [sys.executable, "-m"] + args
    row = {"step": step, "cmd": " ".join(args[:3]), "started": _now()}
    if dry_run:
        print("[dry-run] " + " ".join(args))
        row.update(rc=None, status="dry_run", ended=_now())
        steps.append(row)
        return None, ""
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        p = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, timeout=TIMEOUT)
        rc, out = p.returncode, p.stdout.decode("utf-8", "replace")
        status = "ok" if rc == 0 else "failed"
        reason = None if rc == 0 else "RC_%d" % rc
    except subprocess.TimeoutExpired:
        rc, out, status, reason = None, "", "failed", "TIMEOUT"
    except OSError:
        rc, out, status, reason = None, "", "failed", "SPAWN_FAILED"
    row.update(rc=rc, status=status, reason=reason, ended=_now())
    steps.append(row)
    print("[%s] %s%s" % (status, step, " " + reason if reason else ""))
    return rc, out


def first_json(text):
    """출력에서 처음 나오는 JSON 객체 한 줄을 읽는다. 없으면 None."""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                continue
    return None


def recent_workspaces(n):
    if not os.path.isdir(WS_DIR):
        return []
    names = [d for d in os.listdir(WS_DIR)
             if not d.startswith("_") and os.path.isdir(os.path.join(WS_DIR, d))]
    return sorted(names, reverse=True)[:n]


def nightly(recent, dry_run):
    steps, queue = [], []

    def todo(kind, severity, summary, action, workspace=None, count=1):
        queue.append({"kind": kind, "severity": severity, "workspace": workspace,
                      "count": count, "summary": summary, "action": action})

    # 1. Code-Engr-bot: 코드 검수
    rc, out = run("code_review", ["code_engrbot", "review", "--root", "."], dry_run, steps)
    m = re.search(r"(CR-\S+) (\S+) critical=(\d+) major=(\d+)", out)
    if m:
        crit, major = int(m.group(3)), int(m.group(4))
        if crit or major:
            todo("code_finding", "critical" if crit else "action",
                 "코드 검수 %s %s: critical %d, major %d" % (m.group(1), m.group(2), crit, major),
                 "code_engrbot/out/%s/review.md 확인 후 수정 요청" % m.group(1), count=crit + major)

    workspaces = recent_workspaces(recent)
    if not workspaces:
        todo("no_workspace", "info", "작업 폴더 없음", "/BEOL-labeling 실행")

    # 2. Code-Engr-bot 몫: 최근 작업 폴더의 축·규칙 점검(읽기만)
    for ws in workspaces:
        wsp = os.path.join("workspaces", ws)
        _, out = run("taxonomy_diff:" + ws, ["labelbot", "taxonomy-diff", "--workspace", wsp], dry_run, steps)
        d = first_json(out)
        if d and (d.get("added") or d.get("removed") or d.get("changed") or d.get("values_added")):
            todo("axis_relabel_needed", "action",
                 "축 변경: 추가 %d, 삭제 %d, 변경 %d, 값 추가 축 %d" % (
                     len(d.get("added") or []), len(d.get("removed") or []),
                     len(d.get("changed") or []), len(d.get("values_added") or {})),
                 "/BEOL-labeling-axis-update " + wsp, ws,
                 sum(len(d.get(k) or []) for k in ("added", "removed", "changed", "values_added")))
        _, out = run("rules_diff:" + ws, ["labelbot", "rules-diff", "--workspace", wsp], dry_run, steps)
        d = first_json(out)
        if d and any(d.get(k) for k in ("added", "edited", "disabled", "removed")):
            todo("rules_relabel_needed", "action",
                 "규칙 변경: 추가 %d, 수정 %d, 끔 %d, 삭제 %d (재라벨링은 적재까지 가므로 사람이 확인 후 실행)" % tuple(
                     len(d.get(k) or []) for k in ("added", "edited", "disabled", "removed")),
                 "/BEOL-labeling-rules-update " + wsp, ws,
                 sum(len(d.get(k) or []) for k in ("added", "edited", "disabled", "removed")))

    # 3. Domain-Engr-bot: 가장 최근 작업 폴더로 장부·후보·질문 준비
    if workspaces:
        ws = workspaces[0]
        wsp = os.path.join("workspaces", ws)
        w = ["--workspace", wsp]
        run("intake", ["domain_engrbot", "intake"] + w, dry_run, steps)
        run("ledger_rebuild", ["domain_engrbot", "ledger", "rebuild"] + w, dry_run, steps)
        run("rule_candidates", ["domain_engrbot", "labeling-rules", "candidates"] + w, dry_run, steps)
        _, out = run("rule_status", ["domain_engrbot", "labeling-rules", "status"] + w, dry_run, steps)
        d = first_json(out)
        if d and (d.get("candidates") or d.get("examples_pending")):
            todo("rule_candidate_pending", "info", "규칙 후보 %d(상충 %d), 사례 후보 %d 승인 대기" % (
                d.get("candidates") or 0, d.get("candidates_conflict") or 0, d.get("examples_pending") or 0),
                 "python -m domain_engrbot labeling-rules review --workspace " + wsp, ws,
                 (d.get("candidates") or 0) + (d.get("examples_pending") or 0))
        rc, _ = run("questions_generate", ["domain_engrbot", "questions", "generate"] + w, dry_run, steps)
        if rc not in (0, None) or (rc is None and not dry_run):
            todo("questions_failed", "critical", "도메인 질문 생성 실패(LLM 키·네트워크 확인)",
                 "python -m domain_engrbot questions generate --workspace " + wsp, ws)
        _, out = run("questions_status", ["domain_engrbot", "questions", "status"] + w, dry_run, steps)
        d = first_json(out)
        if d and d.get("open"):
            todo("engr_questions_open", "action", "도메인 질문 %d개 답변 대기 (%s)" % (d["open"], d.get("set_id")),
                 "python -m domain_engrbot questions serve --workspace " + wsp, ws, d["open"])
        todo("taxonomy_board", "info", "taxonomy 수정 제안 확인",
             "python -m domain_engrbot taxonomy-board --serve --open")

    for s in steps:
        if s["status"] == "failed":
            todo("step_failed", "critical", "단계 실패: %s (%s)" % (s["step"], s["reason"]),
                 "로그 steps.jsonl 확인 후 해당 명령 수동 실행")
    queue.sort(key=lambda q: SEVERITY_ORDER[q["severity"]])
    return steps, queue


def write(steps, queue, day):
    out = os.path.join(OUT_DIR, day)
    os.makedirs(out, exist_ok=True)
    for name, rows in (("steps.jsonl", steps), ("morning_queue.jsonl", queue)):
        with open(os.path.join(out, name), "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    failed = sum(1 for s in steps if s["status"] == "failed")
    md = ["# 아침 대응 목록 %s" % day, "",
          "단계 %d개 중 실패 %d개 · 할 일 %d건" % (len(steps), failed, len(queue)), ""]
    for i, q in enumerate(queue, 1):
        where = " [%s]" % q["workspace"] if q["workspace"] else ""
        md.append("%d. **%s**%s %s  " % (i, q["severity"], where, q["summary"]))
        md.append("   → `%s`" % q["action"])
    with open(os.path.join(out, "morning.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")
    with open(os.path.join(OUT_DIR, "latest.json"), "w", encoding="utf-8") as fh:
        json.dump({"date": day, "steps": len(steps), "failed": failed, "todo": len(queue)}, fh)
    return out, failed


def main(argv=None):
    p = argparse.ArgumentParser(description="Code-Engr-bot·Domain-Engr-bot 야간 실행")
    p.add_argument("--recent", type=int, default=3, help="축·규칙 점검할 최근 작업 폴더 수(기본 3)")
    p.add_argument("--dry-run", action="store_true", help="명령만 출력하고 실행·기록하지 않는다")
    args = p.parse_args(argv)
    steps, queue = nightly(args.recent, args.dry_run)
    if args.dry_run:
        return 0
    out, failed = write(steps, queue, datetime.date.today().strftime("%Y%m%d"))
    print("done: %s/morning.md todo=%d failed=%d" % (os.path.relpath(out, ROOT), len(queue), failed))
    return 2 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
