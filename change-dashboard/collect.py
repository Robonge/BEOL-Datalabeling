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
          "1차 검수", "교정 반영", "임베딩 · 적재", "Domain-Engr-bot", "Code-Engr-bot"]
# S4 역할 (docs/project_intro.html 의 S4 AG 객체와 같은 이름)
ROLES = ["Orchestrator", "BEOL-labeling", "검수 엔지니어", "BEOL-labeling-feedback",
         "workspace", "Domain-Engr-bot", "Code-Engr-bot"]
# 2026-10-06 이전 역할 · 단계 이름. 지난 회차 facts · summary는 render.py가 읽을 때 새 이름으로 바꾼다.
OLD_NAMES = {"Engr-bot": "Domain-Engr-bot", "code-bot": "Code-Engr-bot"}

STAGE_ROLE = {
    "수집 · 파싱": "BEOL-labeling", "1차 분류": "BEOL-labeling", "2차 검증 질문": "BEOL-labeling",
    "3차 라벨링": "BEOL-labeling", "불량 목록": "BEOL-labeling", "1차 검수": "검수 엔지니어",
    "교정 반영": "BEOL-labeling-feedback", "임베딩 · 적재": "BEOL-labeling-feedback",
    "Domain-Engr-bot": "Domain-Engr-bot", "Code-Engr-bot": "Code-Engr-bot",
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
    "BEOL-labeling-Domain-Engr-bot": "Domain-Engr-bot", "BEOL-labeling-Code-Engr-bot": "Code-Engr-bot",
    "BEOL-labeling-Engr-bot": "Domain-Engr-bot", "BEOL-labeling-code-bot": "Code-Engr-bot",  # 2026-10-06 이전 이름
    "labeling-Engr-bot": "Domain-Engr-bot", "labeling-codebot": "Code-Engr-bot",  # 2026-10-05 이전 이름(지난 세션 기록용)
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
    if parts[0] in ("domain_engrbot", "engrbot"):  # engrbot: 2026-10-06 이전 경로
        return "Domain-Engr-bot", "Domain-Engr-bot", "Domain-Engr-bot 코드"
    # 승인 파일과 그 계약 테스트는 Domain-Engr-bot 질문 답변(questions apply)이 만든다(2026-10-06)
    if p == "taxonomy/labeling_rules.json":
        return "Domain-Engr-bot", "Domain-Engr-bot", "승인 규칙"
    if p == "tests/test_question_rules_contract.py":
        return "Domain-Engr-bot", "Domain-Engr-bot", "테스트"
    if parts[0] in ("code_engrbot", "codebot"):  # codebot: 2026-10-06 이전 경로
        return "Code-Engr-bot", "Code-Engr-bot", "Code-Engr-bot 코드"
    if parts[:2] == [".claude", "skills"] and len(parts) > 2:
        role = SKILL_ROLE.get(parts[2], "Orchestrator")
        st = {"BEOL-labeling-feedback": "교정 반영"}.get(parts[2]) or \
            (role if role in ("Domain-Engr-bot", "Code-Engr-bot") else None)
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
    title, prompts, edits, bash, stamps = sid[:8], [], [], [], set()
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
            stamps.add(ts)
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
                        bash.append(ts)
    return {"session_id": sid, "title": title, "prompts": prompts, "edits": edits, "bash": bash, "stamps": stamps}


def drop_fork_copy(fork, origin):
    """fork transcript 앞부분은 원본 세션 기록의 복사본이다. 원본과 같은 시각의 기록을 빼고 fork가 새로 한 일만 남긴다."""
    seen = origin["stamps"]
    fork["prompts"] = [p for p in fork["prompts"] if p["ts"] not in seen]
    fork["edits"] = [e for e in fork["edits"] if e["ts"] not in seen]
    fork["bash"] = [t for t in fork["bash"] if t not in seen]
    fork["stamps"] = fork["stamps"] - seen


def finalize(s):
    ts = sorted(s.pop("stamps"))
    s["first_ts"] = parse_ts(ts[0]).isoformat() if ts else None
    s["last_ts"] = parse_ts(ts[-1]).isoformat() if ts else None
    s["shell_commands"] = len(s.pop("bash"))
    s["files"] = summarize_files(s.pop("edits"))
    return s


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


DATA_PATHS = ("parshing test files/", "dummy pptx files", "injested-file-list/", "workspaces/")


def commit_files(since):
    """기간 안 커밋이 바꾼 파일. 셸 스크립트로 고쳐 transcript 편집 기록에 안 잡힌 변경을 보완한다(입력 데이터 폴더 제외)."""
    out, cur = [], None
    for line in git("log", "--since=" + since.isoformat(), "--name-only",
                    "--pretty=format:@@%h	%ad	%s", "--date=format:%m-%d %H:%M").splitlines():
        if line.startswith("@@"):
            h, when, subj = (line[2:].split("	", 2) + ["", ""])[:3]
            cur = {"commit": h, "when": when, "subject": subj}
        elif line.strip() and cur and not line.startswith(DATA_PATHS):
            st, role, area = classify_path(line.strip())
            out.append(dict(cur, path=line.strip(), stage=st, role=role, area=area))
    return out


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
        sessions.append(scan_session(n[:-6], since, until))
    by_title = {s["title"]: s for s in sessions}
    for s in sessions:
        if s["title"].endswith(" (fork)") and s["title"][:-7] in by_title:
            drop_fork_copy(s, by_title[s["title"][:-7]])
    sessions = [finalize(s) for s in sessions if s["prompts"] or s["edits"]]
    stamp = until.astimezone().strftime("%Y%m%d-%H%M")
    facts = {
        "stamp": stamp, "since": since.isoformat(), "until": until.isoformat(),
        "stages": STAGES, "roles": ROLES, "sessions": sessions,
        "git": {"branch": git("rev-parse", "--abbrev-ref", "HEAD").strip(),
                "commits": [l for l in git("log", "--since=" + since.isoformat(), "--pretty=%h %ad %s",
                                           "--date=format:%m-%d %H:%M").splitlines() if l],
                "uncommitted": len([l for l in git("status", "--porcelain").splitlines() if l]),
                "commit_files": commit_files(since)},
    }
    os.makedirs(os.path.join(HERE, "data"), exist_ok=True)
    out = os.path.join(HERE, "data", stamp + "_facts.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(facts, f, ensure_ascii=False, indent=1)
    print("[collect] %s sessions=%d -> %s" % (stamp, len(sessions), os.path.relpath(out, REPO)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
