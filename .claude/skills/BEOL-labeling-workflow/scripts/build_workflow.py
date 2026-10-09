"""BEOL 라벨링 워크플로 HTML 생성: 템플릿에 최신 실행의 건수를 채워 docs/workflow.html로 쓴다.

work.sqlite를 읽기 전용으로 열고 건수·사유 코드·답 분포만 넣는다. 본문·파일명·경로·재검토 메모는 넣지 않는다.
Domain-Engr-bot 건수는 domain_engrbot 명령 출력과 질문 폴더 파일의 건수(질문 문장·답은 넣지 않는다)에서만 얻고, S4 팀 지도는
docs/project_intro.html에서 마스코트 심볼·SVG·agent 설명(AG)을 가져와 넣는다.
작업 폴더를 주지 않으면 workspaces/261004_BEOL_*(실행마다 _YYYYMMDD-HHMMSS가 붙은 새 폴더) 중
work.sqlite가 가장 최근에 바뀐 폴더를 쓴다.

사용: python build_workflow.py [--workspace "<작업 폴더>"] [--run <실행 ID>] [--out "<html 경로>"]
출력: JSON 한 줄(out, workspace, run_id, 채운 항목 수, s4 추출 여부, 도메인 질문 건수).
"""
import argparse
import datetime
import glob
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CODE_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, CODE_ROOT)
from domain_engrbot import paths  # noqa: E402
from labelbot.store import connect_ro  # noqa: E402

TEMPLATE = os.path.join(HERE, "..", "assets", "workflow_template.html")
SUMMARY = os.path.join(CODE_ROOT, ".claude", "skills", "BEOL-labeling", "scripts", "summary.py")
INTRO = os.path.join(CODE_ROOT, "docs", "project_intro.html")
PLACEHOLDER = "/*__LIVE__*/null"
S4_SVG = "<!--__S4_SVG__-->"
S4_AG = "/*__S4_AG__*/null"
QDIR = paths.data_path(os.path.join(CODE_ROOT, "workspaces"), "questions")
LEDGER_LINE = re.compile(r"\[ledger\] 누적 작업 폴더 (\d+), 사례 (\d+)\(근거 있음 (\d+)\), 골든 (\d+), judge 예시 (\d+), L4 후보 (\d+)")


def latest_workspace():
    cands = [d for d in glob.glob(os.path.join(CODE_ROOT, "workspaces", "261004_BEOL_*"))
             if os.path.isfile(os.path.join(d, "work.sqlite"))]
    return max(cands, key=lambda d: os.path.getmtime(os.path.join(d, "work.sqlite"))) if cands else None


def live_data(ws, run):
    args = [sys.executable, SUMMARY, "--workspace", ws] + (["--run", run] if run else [])
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    summ = json.loads(subprocess.run(args, capture_output=True, text=True, encoding="utf-8", env=env, check=True).stdout)
    run = summ.get("run_id")
    con = connect_ro(os.path.join(ws, "work.sqlite"))
    q = lambda sql, *p: con.execute(sql, p).fetchall()
    ext = {e or "(없음)": n for e, n in q(
        "SELECT f.ext, COUNT(DISTINCT f.file_id) FROM files f JOIN file_locations l ON l.file_id=f.file_id"
        " WHERE l.last_seen_run=? GROUP BY 1", run)}
    ans = {"com": {}, "gen": {}}
    for key, val, n in q("SELECT key, value, COUNT(*) FROM labels WHERE run_id=? AND kind='answer' GROUP BY 1, 2", run):
        d = ans["gen" if (key or "").startswith("Q-GEN-") else "com"]
        d[val] = d.get(val, 0) + n
    gen_q = q("SELECT COUNT(DISTINCT key) FROM labels WHERE run_id=? AND kind='answer' AND key LIKE 'Q-GEN-%'", run)[0][0]
    from labelbot.review import run_axes  # 그 실행이 실제로 라벨링한 활성 축(실행별 axes_signature 우선)
    axis_count = len(run_axes(con, run) or ())
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
        "axis_count": axis_count,
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
        "skipped": skipped_count(ws),
        "ingested_lists": len(glob.glob(os.path.join(CODE_ROOT, "injested-file-list", "*.json"))),
        "engr": engr_data(ws),
    }


def domain_engrbot(*args):
    """python -m domain_engrbot 출력(stdout). 실패하면 None. 건수 줄만 쓴다."""
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        p = subprocess.run([sys.executable, "-m", "domain_engrbot", *args], capture_output=True, text=True,
                           encoding="utf-8", env=env, cwd=CODE_ROOT, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout if p.returncode == 0 else None


def questions_data():
    """Domain-Engr-bot 질문 폴더의 건수만: 열린 질문(목표별·이월), 답함·묻지 않음 지문, taxonomy 제안 행.
    질문 문장·답·제안 문장은 넣지 않는다. 파일이 없으면 0, 깨졌으면 그 칸을 None("—")으로 둔다."""
    out = {"set_id": None, "open": 0, "labeling": 0, "taxonomy": 0, "carried": 0,
           "answered": 0, "dismissed": 0, "proposals": 0}
    try:
        with open(os.path.join(QDIR, "questions.json"), encoding="utf-8") as f:
            qs = json.load(f)
        items = [q for q in qs.get("questions") or [] if isinstance(q, dict)]
        out.update(set_id=qs.get("set_id"), open=len(items),
                   labeling=sum(1 for q in items if q.get("goal") == "labeling"),
                   taxonomy=sum(1 for q in items if q.get("goal") == "taxonomy"),
                   carried=sum(1 for q in items if q.get("carried")))
    except FileNotFoundError:
        pass
    except (OSError, ValueError, AttributeError):
        out.update(open=None, labeling=None, taxonomy=None, carried=None)
    try:
        with open(os.path.join(QDIR, "asked.json"), encoding="utf-8") as f:
            asked = json.load(f)
        out.update(answered=len(asked.get("answered") or {}), dismissed=len(asked.get("dismissed") or {}))
    except FileNotFoundError:
        pass
    except (OSError, ValueError, AttributeError, TypeError):
        out.update(answered=None, dismissed=None)
    try:
        with open(os.path.join(QDIR, "taxonomy_proposals.jsonl"), encoding="utf-8") as f:
            out["proposals"] = sum(1 for line in f if line.strip())
    except FileNotFoundError:
        pass
    except (OSError, ValueError):
        out["proposals"] = None
    return out


def engr_data(ws):
    """Domain-Engr-bot 활동 건수: 승인 규칙 상태, 교정 장부, 도메인 질문, 도메인 규칙, 재검토 요청 파일 수."""
    out = {}
    s = domain_engrbot("labeling-rules", "status", "--workspace", ws)
    if s:
        try:
            out["rules"] = json.loads(s)
        except ValueError:
            pass
    m = LEDGER_LINE.search(domain_engrbot("ledger", "--workspace", ws, "status") or "")
    if m:
        out["ledger"] = dict(zip(("workspaces", "cases", "evidence", "golden", "judge_examples", "l4_candidates"),
                                 map(int, m.groups())))
    out["questions"] = questions_data()
    try:
        with open(os.path.join(CODE_ROOT, "domain_engrbot", "defaults", "domain_rules.json"), encoding="utf-8") as f:
            rules = json.load(f).get("rules") or []
        out["domain_rules"] = {st: sum(1 for r in rules if r.get("status") == st) for st in ("draft", "approved")}
    except (OSError, ValueError):
        pass
    out["revisit_files"] = len(glob.glob(os.path.join(CODE_ROOT, "taxonomy", "taxonomy_revisit_requests", "*.md")))
    return out


def s4_parts():
    """docs/project_intro.html S4 팀 지도에서 마스코트 심볼, SVG, agent 설명(AG)을 꺼낸다. 없으면 None."""
    try:
        with open(INTRO, encoding="utf-8") as f:
            h = f.read()
    except OSError:
        return None
    sym = re.search(r'<symbol id="clawd".*?</symbol>', h, re.S)
    svg = re.search(r'<svg class="orch[^"]*".*?</svg>', h, re.S)
    ag = re.search(r"var AG=(\{.*?\n  \});", h, re.S)
    if not (sym and svg and ag) or "</script" in ag.group(1).lower():
        return None
    defs = '<svg width="0" height="0" style="position:absolute" aria-hidden="true">' + sym.group(0) + "</svg>"
    return {"svg": defs + svg.group(0).replace("orch rv", "orch"), "ag": ag.group(1)}


def skipped_count(ws):
    """pipeline.json skip_file_names 건수(중복이라 건너뛴 파일). 파일명은 넣지 않는다."""
    try:
        with open(os.path.join(ws, "pipeline.json"), encoding="utf-8") as f:
            return len(json.load(f).get("skip_file_names") or [])
    except (OSError, ValueError):
        return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace")
    ap.add_argument("--run")
    ap.add_argument("--out", default=os.path.join(CODE_ROOT, "docs", "workflow.html"))
    a = ap.parse_args()
    with open(TEMPLATE, encoding="utf-8") as f:
        tpl = f.read()
    if any(tpl.count(p) != 1 for p in (PLACEHOLDER, S4_SVG, S4_AG)):
        print(json.dumps({"error": "TEMPLATE_PLACEHOLDER"}))
        return 2
    ws = a.workspace or latest_workspace()
    live = {}
    if ws and os.path.isfile(os.path.join(ws, "work.sqlite")):
        live = live_data(ws, a.run)
    payload = json.dumps(live, ensure_ascii=False).replace("</", "<\\/")
    s4 = s4_parts()
    html = tpl.replace(PLACEHOLDER, payload)
    html = html.replace(S4_SVG, s4["svg"] if s4 else '<p class="sm">S4 팀 지도를 docs/project_intro.html에서 찾지 못했습니다.</p>')
    html = html.replace(S4_AG, s4["ag"] if s4 else "null")
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)
    engr = live.get("engr") or {}
    print(json.dumps({"out": a.out.replace("\\", "/"), "workspace": (ws or "").replace("\\", "/") or None,
                      "run_id": live.get("run_id"), "fields": len(live), "s4": bool(s4),
                      "questions": engr.get("questions")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    from labelbot import trace  # noqa: E402  마일스톤 M22(stderr 줄, stdout JSON 불변)

    sys.exit(trace.run_main("M22", main))
