"""세션 변경 사실 수집기. 이 저장소에서 일한 Claude 세션의 transcript를 읽어
기간 안의 파일 편집·사용자 요청을 모으고, 파일마다 S4 역할과 S5 단계를 붙인다.

표준 라이브러리만 쓴다. 사내 파일은 열지 않는다(transcript와 git 출력만 읽는다).
출력: change-dashboard/data/<stamp>_facts.json
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PROJECTS = os.path.join(os.path.expanduser("~"), ".claude", "projects")
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")

# S5 단계 (docs/project_intro.html 의 S5 ST 배열과 같은 이름)
STAGES = ["수집 · 파싱", "1차 분류", "2차 검증 질문", "3차 라벨링", "불량 목록",
          "1차 검수", "교정 반영", "임베딩 · 적재", "Engr-bot", "code-bot"]
# S4 역할 (docs/project_intro.html 의 S4 AG 객체와 같은 이름)
ROLES = ["Orchestrator", "BEOL-labeling", "검수 엔지니어", "BEOL-labeling-feedback",
         "workspace", "Engr-bot", "code-bot"]

STAGE_ROLE = {
    "수집 · 파싱": "BEOL-labeling", "1차 분류": "BEOL-labeling", "2차 검증 질문": "BEOL-labeling",
    "3차 라벨링": "BEOL-labeling", "불량 목록": "BEOL-labeling", "1차 검수": "검수 엔지니어",
    "교정 반영": "BEOL-labeling-feedback", "임베딩 · 적재": "BEOL-labeling-feedback",
    "Engr-bot": "Engr-bot", "code-bot": "code-bot",
}

LABELBOT_STAGE = {
    "ingest": "수집 · 파싱", "pptx_parser": "수집 · 파싱", "docx_parser": "수집 · 파싱",
    "ooxml": "수집 · 파싱", "xlsx": "수집 · 파싱", "chunker": "수집 · 파싱", "textnorm": "수집 · 파싱",
    "classify": "1차 분류", "taxonomy": "1차 분류", "synonyms": "1차 분류", "candidates": "1차 분류",
    "questions": "2차 검증 질문",
    "label": "3차 라벨링", "llm": "3차 라벨링", "finals": "3차 라벨링", "mock": "3차 라벨링",
    "alerts": "불량 목록", "dashboard": "불량 목록", "report": "불량 목록",
    "review": "1차 검수", "serve": "1차 검수", "slideimg": "1차 검수", "cdp": "1차 검수",
    "feedback": "교정 반영", "revisit": "교정 반영",
    "embed": "임베딩 · 적재", "vectorpush": "임베딩 · 적재", "slidepush": "임베딩 · 적재",
    "export": "임베딩 · 적재",
}
SKILL_ROLE = {
    "BEOL-labeling": "BEOL-labeling", "BEOL-labeling-feedback": "BEOL-labeling-feedback",
    "labeling-Engr-bot": "Engr-bot", "labeling-codebot": "code-bot",
    "BEOL-labeling-workflow": "Orchestrator",
}


def classify_path(rel):
    """저장소 상대 경로 → (S5 단계 또는 None, S4 역할, 영역 이름)."""
    p = rel.replace("\\", "/")
    parts = p.split("/")
    name = os.path.splitext(parts[-1])[0]
    if parts[0] == "labelbot":
        st = LABELBOT_STAGE.get(name)
        return st, STAGE_ROLE[st] if st else "workspace", "labelbot 코드"
    if parts[0] == "engrbot":
        return "Engr-bot", "Engr-bot", "engrbot 코드"
    if parts[0] == "codebot":
        return "code-bot", "code-bot", "codebot 코드"
    if parts[:2] == [".claude", "skills"] and len(parts) > 2:
        role = SKILL_ROLE.get(parts[2], "Orchestrator")
        st = {"BEOL-labeling-feedback": "교정 반영", "labeling-Engr-bot": "Engr-bot",
              "labeling-codebot": "code-bot"}.get(parts[2])
        return st, role, "skill 절차"
    if parts[0] == "prompts":
        st = "1차 분류" if "classify" in name else "2차 검증 질문" if "question" in name else "3차 라벨링"
        return st, "BEOL-labeling", "LLM 프롬프트"
    if parts[0] == "taxonomy":
        return "1차 분류", "BEOL-labeling", "분류표"
    if parts[0] == "tests":
        for key, st in LABELBOT_STAGE.items():
            if key in name:
                return st, STAGE_ROLE[st], "테스트"
        return None, "workspace", "테스트"
    if parts[0] == "workspaces":
        return None, "workspace", "작업대 데이터"
    if parts[0] == "change-dashboard":
        return None, "Orchestrator", "변경 대시보드"
    return None, "Orchestrator", "문서·설정"


def parse_ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def iter_jsonl(path):
    try:
        f = open(path, encoding="utf-8")
    except OSError:
        return
    with f:
        for line in f:
            try:
                yield json.loads(line)
            except ValueError:
                continue


def prompt_text(msg):
    c = msg.get("content")
    if isinstance(c, list):
        c = " ".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    if not isinstance(c, str):
        return None
    c = c.strip()
    if not c or c.startswith(("<system-reminder", "<task-notification", "<local-command", "Base directory")):
        return None
    if "<command-name>" in c:
        s = c.find("<command-name>") + len("<command-name>")
        cmd = c[s:c.find("</command-name>")]
        a = c.find("<command-args>")
        args = c[a + 14:c.find("</command-args>")] if a >= 0 else ""
        c = (cmd + " " + args).strip()
    return c[:400]


def scan_session(sid, since, until):
    base = os.path.join(PROJECTS, PROJECT_KEY)
    main = os.path.join(base, sid + ".jsonl")
    files = [main]
    sub = os.path.join(base, sid, "subagents")
    if os.path.isdir(sub):
        files += [os.path.join(sub, n) for n in os.listdir(sub) if n.endswith(".jsonl")]
    title, prompts, edits, bash = sid[:8], [], [], 0
    first_ts = last_ts = None
    for fp in files:
        is_main = fp == main
        for o in iter_jsonl(fp):
            if is_main and o.get("type") == "custom-title" and o.get("customTitle"):
                title = o["customTitle"]
            ts = o.get("timestamp")
            if not ts:
                continue
            t = parse_ts(ts)
            if not (since <= t <= until):
                continue
            first_ts = min(first_ts or t, t)
            last_ts = max(last_ts or t, t)
            if is_main and o.get("type") == "user" and not o.get("isMeta"):
                txt = prompt_text(o.get("message", {}))
                if txt:
                    prompts.append({"ts": ts, "text": txt})
            if o.get("type") == "assistant":
                for b in o.get("message", {}).get("content") or []:
                    if not isinstance(b, dict) or b.get("type") != "tool_use":
                        continue
                    if b.get("name") in EDIT_TOOLS:
                        fpth = (b.get("input") or {}).get("file_path") or (b.get("input") or {}).get("notebook_path")
                        if fpth:
                            edits.append({"ts": ts, "tool": b["name"], "path": fpth, "by": "main" if is_main else "subagent"})
                    elif b.get("name") in ("Bash", "PowerShell"):
                        bash += 1
    return {"session_id": sid, "title": title, "prompts": prompts, "edits": edits,
            "shell_commands": bash, "first_ts": first_ts and first_ts.isoformat(),
            "last_ts": last_ts and last_ts.isoformat()}


def summarize_files(edits):
    out = {}
    for e in edits:
        p = os.path.normpath(e["path"])
        try:
            rel = os.path.relpath(p, REPO)
        except ValueError:
            continue
        if rel.startswith(".."):
            continue
        rel = rel.replace("\\", "/")
        st, role, area = classify_path(rel)
        d = out.setdefault(rel, {"path": rel, "stage": st, "role": role, "area": area, "edits": 0, "last_ts": ""})
        d["edits"] += 1
        d["last_ts"] = max(d["last_ts"], e["ts"])
    return sorted(out.values(), key=lambda d: (-d["edits"], d["path"]))


def git(*args):
    try:
        r = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, encoding="utf-8")
        return r.stdout
    except OSError:
        return ""


def project_key(path):
    return "".join(ch if ch.isalnum() else "-" for ch in path)


PROJECT_KEY = project_key(REPO)


def main(argv=None):
    ap = argparse.ArgumentParser(description="세션 변경 사실 수집")
    ap.add_argument("--hours", type=float, default=3.0, help="지금부터 거슬러 올라갈 시간(기본 3)")
    ap.add_argument("--since", help="시작 시각 ISO(주면 --hours 무시)")
    ap.add_argument("--until", help="끝 시각 ISO(기본 지금)")
    a = ap.parse_args(argv)
    until = parse_ts(a.until) if a.until else dt.datetime.now(dt.timezone.utc)
    since = parse_ts(a.since) if a.since else until - dt.timedelta(hours=a.hours)
    base = os.path.join(PROJECTS, PROJECT_KEY)
    sessions = []
    for n in sorted(os.listdir(base)):
        if not n.endswith(".jsonl"):
            continue
        fp = os.path.join(base, n)
        if dt.datetime.fromtimestamp(os.path.getmtime(fp), dt.timezone.utc) < since:
            continue
        s = scan_session(n[:-6], since, until)
        if not (s["prompts"] or s["edits"]):
            continue
        s["files"] = summarize_files(s["edits"])
        del s["edits"]
        sessions.append(s)
    # fork transcript는 원본 세션 기록을 복사하므로 원본이 있으면 뺀다
    titles = {s["title"] for s in sessions}
    sessions = [s for s in sessions
                if not (s["title"].endswith(" (fork)") and s["title"][:-7] in titles)]
    stamp = until.astimezone().strftime("%Y%m%d-%H%M")
    facts = {
        "stamp": stamp, "since": since.isoformat(), "until": until.isoformat(),
        "stages": STAGES, "roles": ROLES, "sessions": sessions,
        "git": {"branch": git("rev-parse", "--abbrev-ref", "HEAD").strip(),
                "commits": [l for l in git("log", "--since=" + since.isoformat(), "--pretty=%h %ad %s",
                                           "--date=format:%m-%d %H:%M").splitlines() if l],
                "uncommitted": len([l for l in git("status", "--porcelain").splitlines() if l])},
    }
    os.makedirs(os.path.join(HERE, "data"), exist_ok=True)
    out = os.path.join(HERE, "data", stamp + "_facts.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(facts, f, ensure_ascii=False, indent=1)
    print("[collect] %s sessions=%d -> %s" % (stamp, len(sessions), os.path.relpath(out, REPO)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
