"""변경 대시보드 렌더러. data/<stamp>_facts.json(수집 사실)과 data/<stamp>_summary.json
(초보자용 설명)을 합쳐 reports/<stamp>.html과 index.html을 만든다.

- S4 팀 지도: docs/project_intro.html의 S4 SVG·CSS를 그대로 가져와 변경 배지만 덧씌운다. 노드를 누르면 변경 상세가 나온다.
- 마지막 섹션(전체 workflow): S5의 단계 데이터(ST)·CSS를 그대로 가져와 단계 줄과 입력·처리·출력을 보여 준다.
- 디자인은 design.md.md(BEOL AX 토큰, 48px 그리드, 인디고 그라디언트, 음수 자간, 400/700 굵기)를 따른다.
표준 라이브러리만 쓰고 .html만 쓴다. summary가 없으면 사실만으로 그린다.
"""
import argparse
import datetime as dt
import glob
import html
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DATA = os.path.join(HERE, "data")
REPORTS = os.path.join(HERE, "reports")
INTRO = os.path.join(REPO, "docs", "project_intro.html")

# S4 SVG의 data-n 키 ↔ collect.py의 역할 이름
ROLE_KEY = {"Orchestrator": "orch", "BEOL-labeling": "lab", "검수 엔지니어": "hum",
            "BEOL-labeling-feedback": "fb", "workspace": "ws", "Engr-bot": "engr", "code-bot": "code"}
NODE_INFO = {
    "orch": ("Orchestrator", "지휘자 · 메인 세션", "skill을 순서대로 부르고 관리한다"),
    "req": ("엔지니어", "요청자", "이 기간에 세션들에 보낸 요청"),
    "lab": ("BEOL-labeling", "skill", "자료를 읽고 label을 붙인다"),
    "hum": ("검수 엔지니어", "1차 검수", "사람이 의심 chunk를 확인하고 고친다"),
    "fb": ("BEOL-labeling-feedback", "skill", "교정을 반영하고 DB에 적재한다"),
    "ws": ("workspace", "공유 작업대", "코드 뼈대 · 데이터 · 문서"),
    "engr": ("Engr-bot", "감시 agent", "label을 도메인 지식으로 감시한다"),
    "code": ("code-bot", "감시 agent", "코드 · workflow 규칙을 감시한다"),
}
STAGE_DESC = {
    "수집 · 파싱": "자료를 모아 읽기", "1차 분류": "기준별로 나누기",
    "2차 검증 질문": "맞는지 물어볼 질문 만들기", "3차 라벨링": "질문마다 O/X로 답하기",
    "불량 목록": "의심 chunk 골라내기", "1차 검수": "엔지니어가 확인하고 고치기",
    "교정 반영": "사람 값으로 확정", "임베딩 · 적재": "DB에 올리기",
    "Engr-bot": "도메인 감시 · feedback", "code-bot": "코드 규칙 감시",
}
# 세션 구분색: design.md.md 인디고 계열 + 시맨틱 색(소면적 점에만 쓴다)
PALETTE = ["#4A5FA8", "#C99A3B", "#3B8A6E", "#C25450", "#6B82C4", "#7A9CC0"]
GIT, GIT_COLOR = "git 커밋", "#9DAABF"
SKIP_PROMPTS = ("This session is being continued", "/model", "/compact", "[Request interrupted")


def e(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def kst(iso):
    if not iso:
        return ""
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%m-%d %H:%M")


def load(stamp):
    with open(os.path.join(DATA, stamp + "_facts.json"), encoding="utf-8") as f:
        facts = json.load(f)
    sp = os.path.join(DATA, stamp + "_summary.json")
    summary = {}
    if os.path.exists(sp):
        with open(sp, encoding="utf-8") as f:
            summary = json.load(f)
    return facts, summary


def _between(text, start, end, start_at=0):
    i = text.find(start, start_at)
    if i < 0:
        return ""
    j = text.find(end, i + len(start))
    return text[i:j + len(end)] if j >= 0 else ""


def intro_parts():
    """project_intro.html에서 clawd 심볼, S4 SVG·CSS, S5 CSS·단계 데이터(ST)를 원문 그대로 꺼낸다."""
    try:
        with open(INTRO, encoding="utf-8") as f:
            src = f.read()
    except OSError:
        return {}
    sym_at = src.find('<symbol id="clawd"')
    symbol = _between(src, '<svg width="0"', "</svg>", max(0, src.rfind("<svg", 0, sym_at))) if sym_at >= 0 else ""
    svg = _between(src, '<svg class="orch', "</svg>", src.find('id="s4"'))
    svg = svg.replace('class="orch rv"', 'class="orch"').replace('style="--d:300ms" ', "")
    s4css = _between(src, "/* ---------- S4 ---------- */", "/* ---------- S5").rsplit("/* ---------- S5", 1)[0]
    s5css = _between(src, "/* ---------- S5 ---------- */", "/* ---------- S6").rsplit("/* ---------- S6", 1)[0]
    st = _between(src, "var ST=[", "\n  ];")
    st = st[len("var ST="):] if st else "[]"
    return {"symbol": symbol, "svg": svg, "s4css": s4css, "s5css": s5css, "st": st}


def build_data(facts, summary):
    sessions = facts["sessions"]
    color = {s["title"]: PALETTE[i % len(PALETTE)] for i, s in enumerate(sessions)}
    order = list(color)
    nodes = {k: {"files": [], "changes": [], "sessions": []} for k in NODE_INFO}
    stages = {st: {"files": [], "changes": [], "sessions": []} for st in facts["stages"]}
    common = {}
    ssum = summary.get("sessions", {})

    def mark(bucket, t):
        if t not in bucket["sessions"]:
            bucket["sessions"].append(t)

    for s in sessions:
        t = s["title"]
        for f in s["files"]:
            item = {"path": f["path"], "where": f["stage"] or f["area"], "session": t, "edits": f["edits"]}
            n = nodes[ROLE_KEY.get(f["role"], "ws")]
            n["files"].append(item)
            mark(n, t)
            if f["stage"]:
                stages[f["stage"]]["files"].append(item)
                mark(stages[f["stage"]], t)
            else:
                common.setdefault(f["area"], {}).setdefault(t, 0)
                common[f["area"]][t] += 1
        for c in ssum.get(t, {}).get("changes", []):
            ch = {"session": t, "title": c.get("title"), "why": c.get("why"), "stage": c.get("stage")}
            k = ROLE_KEY.get(c.get("role"))
            if k:
                nodes[k]["changes"].append(ch)
                mark(nodes[k], t)
            if c.get("stage") in stages:
                stages[c["stage"]]["changes"].append(ch)
                mark(stages[c["stage"]], t)
    # 커밋으로 바뀐 파일: 세션 편집 기록과 별도로 'git 커밋'으로 붙인다(경로당 한 번, 커밋 ID 목록)
    by_path = {}
    for cf in facts["git"].get("commit_files", []):
        d = by_path.setdefault(cf["path"], dict(cf, commits=[]))
        d["commits"].append(cf["commit"])
    if by_path:
        color[GIT] = GIT_COLOR
    for cf in by_path.values():
        item = {"path": cf["path"], "where": cf["stage"] or cf["area"], "session": GIT, "commits": cf["commits"]}
        n = nodes[ROLE_KEY.get(cf["role"], "ws")]
        n["files"].append(item)
        mark(n, GIT)
        if cf["stage"]:
            stages[cf["stage"]]["files"].append(item)
            mark(stages[cf["stage"]], GIT)
        else:
            common.setdefault(cf["area"], {}).setdefault(GIT, 0)
            common[cf["area"]][GIT] += 1
    prompts = [{"session": s["title"], "ts": kst(p["ts"]), "text": p["text"][:240]}
               for s in sessions for p in s["prompts"] if not p["text"].startswith(SKIP_PROMPTS)]
    nodes["req"]["prompts"] = prompts
    nodes["req"]["sessions"] = sorted({p["session"] for p in prompts}, key=order.index)
    info = {k: {"name": v[0], "sub": v[1], "desc": v[2]} for k, v in NODE_INFO.items()}
    return {"color": color, "nodes": nodes, "stages": stages, "info": info, "common": common,
            "stageDesc": STAGE_DESC}


def build(facts, summary, history):
    parts = intro_parts()
    data = build_data(facts, summary)
    sessions = facts["sessions"]
    color = data["color"]
    ssum = summary.get("sessions", {})
    nfiles = len({f["path"] for s in sessions for f in s["files"]} | {c["path"] for c in facts["git"].get("commit_files", [])})

    def dots(names):
        return "".join('<i class="dot" style="background:%s" title="%s"></i>' % (color[n], e(n)) for n in names)

    chips = []
    for i, st in enumerate(facts["stages"]):
        d = data["stages"][st]
        n = len(d["files"]) + len(d["changes"])
        watch = st in ("Engr-bot", "code-bot")
        chips.append('<button class="sc%s%s" data-st="%s" type="button"><small>%s</small><b>%s</b><span>%s</span><em>%s</em><i>%s</i></button>'
                     % (" hot" if n else "", " w" if watch else "", e(st), "감시" if watch else "%02d" % (i + 1),
                        e(st), e(STAGE_DESC.get(st, "")), ("변경 %d" % n) if n else "–", dots(d["sessions"])))
    common_html = "".join('<span class="pill">%s <b>%d</b>%s</span>' % (e(k), sum(v.values()), dots(v))
                          for k, v in sorted(data["common"].items())) or '<span class="muted">없음</span>'

    cards = []
    for s in sessions:
        info = ssum.get(s["title"], {})
        changes = "".join(
            '<li><b>%s</b><span class="tag">%s</span><p>%s</p></li>'
            % (e(c.get("title")), e(" · ".join(x for x in (c.get("role"), c.get("stage")) if x)), e(c.get("why")))
            for c in info.get("changes", []))
        files = "".join('<tr><td class="mono">%s</td><td>%s</td><td>%s</td><td class="mono">%d</td></tr>'
                        % (e(f["path"]), e(f["stage"] or f["area"]), e(f["role"]), f["edits"]) for f in s["files"])
        prompts = "".join('<li><time class="mono">%s</time>%s</li>' % (kst(p["ts"]), e(p["text"][:220]))
                          for p in s["prompts"] if not p["text"].startswith(SKIP_PROMPTS))
        cards.append(
            '<article class="card panel" style="--c:%s"><header><i class="dot big" style="background:%s"></i>'
            '<h3>%s</h3><span class="when mono">%s ~ %s · 파일 %d · 명령 %d</span></header>'
            '<p class="plain">%s</p>%s'
            '<details><summary>바뀐 파일 %d개</summary><div class="tw"><table><tr><th>파일</th><th>S5 단계/영역</th><th>S4 역할</th><th>편집</th></tr>%s</table></div></details>'
            '<details><summary>사용자 요청</summary><ul class="pr">%s</ul></details></article>'
            % (color[s["title"]], color[s["title"]], e(s["title"]), kst(s["first_ts"]), kst(s["last_ts"]),
               len(s["files"]), s["shell_commands"],
               e(info.get("plain", "이 세션의 초보자용 설명은 아직 작성되지 않았습니다.")),
               ('<ul class="chg">%s</ul>' % changes) if changes else "",
               len(s["files"]), files, prompts or "<li>없음</li>"))

    gloss = "".join('<div class="panel"><dt>%s</dt><dd>%s</dd></div>' % (e(g["term"]), e(g["meaning"]))
                    for g in summary.get("glossary", []))
    hist = "".join('<a href="%s"%s>%s</a>' % (e(h["href"]), ' class="cur"' if h["cur"] else "", e(h["label"]))
                   for h in history)
    commits = "".join('<li class="mono">%s</li>' % e(c) for c in facts["git"]["commits"]) or "<li>이 기간 커밋 없음</li>"
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    missing = '<p class="muted">docs/project_intro.html을 찾지 못해 그림을 그리지 못했습니다.</p>'

    rep = {
        "%%TITLE%%": "세션 변경 대시보드 " + e(facts["stamp"]),
        "%%S4CSS%%": parts.get("s4css", ""), "%%S5CSS%%": parts.get("s5css", ""),
        "%%SYMBOL%%": parts.get("symbol", ""), "%%SVG%%": parts.get("svg") or missing,
        "%%ST%%": parts.get("st", "[]"),
        "%%PERIOD%%": "%s ~ %s KST" % (kst(facts["since"]), kst(facts["until"])),
        "%%BRANCH%%": e(facts["git"]["branch"]),
        "%%HEADLINE%%": e(summary.get("headline", "이 기간에 세션별로 바뀐 내용을 workflow 위에 표시했습니다.")),
        "%%NSESS%%": str(len(sessions)), "%%NFILES%%": str(nfiles),
        "%%NCOMMIT%%": str(len(facts["git"]["commits"])), "%%NUNC%%": str(facts["git"]["uncommitted"]),
        "%%LEGEND%%": "".join('<span><i class="dot" style="background:%s"></i>%s</span>' % (color[t], e(t)) for t in color),
        "%%CHIPS%%": "".join(chips), "%%COMMON%%": common_html, "%%CARDS%%": "".join(cards),
        "%%GLOSS%%": gloss, "%%COMMITS%%": commits, "%%HIST%%": hist, "%%DATA%%": payload,
    }
    out = TEMPLATE
    for k, v in rep.items():
        out = out.replace(k, v)
    return out


TEMPLATE = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>%%TITLE%%</title>
<style>
:root{
  --primary-deep:#354690; --primary:#4A5FA8; --primary-soft:#6B82C4; --primary-mid:#4A6BAF;
  --bg-base:#EDF1F7; --bg-grid:#C8D4E4; --surface:#FFFFFF; --dot:#A8BDD4; --line:#7A9CC0;
  --text-strong:#1E2D4A; --text-muted:#9DAABF; --text-footer:#B0BCCC; --text-body:rgba(30,45,74,.74);
  --danger:#C25450; --warning:#C99A3B; --success:#3B8A6E;
  --ease-elastic:cubic-bezier(0.34,1.56,0.64,1);
  --grad-main:linear-gradient(148deg,#4A5FA8 0%,#354690 100%);
  --grad-soft:linear-gradient(148deg,#6B82C4 0%,#4A6BAF 100%);
  --mono:'JetBrains Mono','Fira Code','Cascadia Mono',Consolas,'SF Mono',Menlo,monospace;
}
*{box-sizing:border-box;margin:0;padding:0;min-width:0}
html{background:var(--bg-base)}
body{font-family:'Apple SD Gothic Neo','Pretendard','Noto Sans KR','Inter',sans-serif;color:var(--text-strong);letter-spacing:-0.02em;
  -webkit-font-smoothing:antialiased;background-color:var(--bg-base);
  background-image:linear-gradient(var(--bg-grid) 0.4px,transparent 0.4px),linear-gradient(90deg,var(--bg-grid) 0.4px,transparent 0.4px);
  background-size:48px 48px;word-break:keep-all;overflow-wrap:anywhere;font-size:15px;line-height:1.6}
button{font:inherit;letter-spacing:inherit;color:inherit}
.mono{font-family:var(--mono);letter-spacing:-0.01em}
.wrap{max-width:1180px;margin:0 auto;padding:32px 16px 72px}
.eyebrow{font-family:var(--mono);font-size:12px;color:var(--primary);letter-spacing:.02em}
h1{font-size:30px;font-weight:700;letter-spacing:-0.055em;line-height:1.25;margin-top:6px}
h2{font-size:21px;font-weight:700;letter-spacing:-0.048em;margin:48px 0 4px}
.sub{color:var(--text-body);font-size:13.5px;margin-bottom:14px}
.muted{color:var(--text-muted)}
.panel{background:var(--surface);border:1px solid var(--bg-grid);border-radius:14px;box-shadow:0 2px 8px rgba(53,70,144,.06)}
.headline{background:var(--grad-main);color:#fff;border-radius:14px;padding:18px 20px;margin:18px 0 12px;box-shadow:0 12px 28px -8px rgba(53,70,144,.45);font-size:15.5px}
.headline b{display:block;font-family:var(--mono);font-size:11.5px;font-weight:400;opacity:.8;margin-bottom:4px}
.kpi{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(160px,100%),1fr));gap:10px}
.kpi div{padding:12px 16px}.kpi b{display:block;font-family:var(--mono);font-size:26px;font-weight:700;letter-spacing:-0.04em}.kpi span{color:var(--text-body);font-size:13px}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;margin:12px 2px;color:var(--text-body);font-size:13px}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin:0 3px;vertical-align:middle}.dot.big{width:13px;height:13px}
.tag{font-family:var(--mono);font-size:11px;margin-left:8px;padding:1px 8px;border-radius:999px;background:var(--bg-base);border:1px solid var(--bg-grid);color:var(--primary)}

/* ===== S4: docs/project_intro.html 원문 CSS ===== */
%%S4CSS%%
.s4box{padding:14px 14px 10px;overflow:hidden}
.orch{display:block;height:auto;margin:0}
.orch .nd.chg .hit{fill:rgba(201,154,59,.10);stroke:var(--warning);stroke-width:1.4}
.orch .bdg circle{fill:var(--warning)}.orch .bdg text{fill:#fff;font-size:11px;font-weight:700;font-family:var(--mono)}
.orch .sdot{stroke:#fff;stroke-width:1.2}
.orch .nd.sel .hit{fill:rgba(107,130,196,.16);stroke:var(--primary);stroke-width:1.6}
.hint{font-size:12.5px;color:var(--text-muted);margin:6px 2px 0}
.detail{margin-top:12px;padding:16px 18px;min-height:96px}
.detail .hd{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 10px;margin-bottom:8px}
.detail .hd b{font-size:17px;font-weight:700;letter-spacing:-0.048em}
.detail .hd small{font-family:var(--mono);color:var(--primary);font-size:11.5px}
.detail .hd span{color:var(--text-body);font-size:13px}
.detail h4{font-size:12px;font-family:var(--mono);font-weight:400;color:var(--primary);margin:10px 0 4px}
.detail ul{list-style:none;display:grid;grid-template-columns:minmax(0,1fr);gap:6px}
.detail li{border:1px solid var(--bg-grid);border-radius:10px;padding:8px 11px;background:rgba(237,241,247,.5)}
.detail li p{color:var(--text-body);font-size:13.5px;margin-top:2px}
.detail .fl li{display:flex;flex-wrap:wrap;gap:2px 10px;align-items:baseline;padding:5px 10px;font-size:13px}
.detail .fl code{font-family:var(--mono);font-size:12px}
.who{font-size:12px;color:var(--text-body)}

/* ===== 변경 칩 (S5 단계별 변경 수) ===== */
.chips{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(150px,100%),1fr));gap:8px}
.sc{background:var(--surface);border:1px solid var(--bg-grid);border-radius:12px;padding:10px 12px;display:flex;flex-direction:column;text-align:left;cursor:pointer;transition:all .28s var(--ease-elastic)}
.sc:hover{transform:translateY(-2px);border-color:var(--primary)}
.sc small{font-family:var(--mono);color:var(--text-muted);font-size:11px}.sc b{font-weight:700;letter-spacing:-0.048em}.sc span{color:var(--text-body);font-size:12px}
.sc em{font-style:normal;font-family:var(--mono);font-size:13px;margin-top:4px;color:var(--text-muted)}.sc i{font-style:normal}
.sc.w{border-style:dashed}.sc.hot{border-color:var(--warning)}.sc.hot em{color:var(--warning);font-weight:700}
.sc.sel{background:var(--grad-main);border-color:transparent;color:#fff;box-shadow:0 12px 28px -6px rgba(53,70,144,.4)}
.sc.sel small,.sc.sel span,.sc.sel em{color:rgba(255,255,255,.85)}
.pill{display:inline-block;background:var(--surface);border:1px solid var(--bg-grid);border-radius:999px;padding:3px 11px;margin:3px;font-size:13px}

/* ===== 세션 카드 ===== */
.card{padding:16px 18px;margin:12px 0;border-top:3px solid var(--c)}
.card header{display:flex;flex-wrap:wrap;gap:6px 10px;align-items:center}.card h3{font-size:18px;font-weight:700;letter-spacing:-0.048em}.when{color:var(--text-muted);font-size:12px}
.plain{margin:8px 0}.chg{list-style:none;display:grid;grid-template-columns:minmax(0,1fr);gap:8px;margin:8px 0}
.chg li{border:1px solid var(--bg-grid);border-radius:10px;padding:9px 12px}.chg p{color:var(--text-body);font-size:13.5px;margin-top:2px}
details{margin-top:8px}summary{cursor:pointer;color:var(--primary);font-size:13.5px}
.tw{overflow-x:auto}table{border-collapse:collapse;font-size:12.5px;margin-top:6px;min-width:100%}td,th{border-bottom:1px solid var(--bg-grid);padding:4px 8px;text-align:left;white-space:nowrap}th{font-weight:700;color:var(--text-body)}
.pr{list-style:none;font-size:13px;color:var(--text-body);display:grid;gap:4px;margin-top:6px}.pr time{margin-right:8px;color:var(--primary)}
dl{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(260px,100%),1fr));gap:8px}dl div{padding:10px 14px}dt{font-weight:700}dd{color:var(--text-body);font-size:13.5px}
.hist a{display:inline-block;margin:3px;padding:3px 11px;border:1px solid var(--bg-grid);background:var(--surface);border-radius:999px;color:var(--text-strong);text-decoration:none;font-family:var(--mono);font-size:12px}
.hist a.cur{background:var(--grad-main);color:#fff;border-color:transparent}

/* ===== 전체 workflow: docs/project_intro.html S5 원문 CSS ===== */
#wf{font-size:17px;padding:18px 16px 16px}
%%S5CSS%%
#wf .track{margin-top:.6em}
#wf .st{position:relative}
#wf .st .bd{position:absolute;top:-.55em;right:-.35em;min-width:1.5em;height:1.5em;border-radius:999px;background:var(--warning);color:#fff;font-family:var(--mono);font-size:.62em;font-weight:700;display:grid;place-items:center;padding:0 .35em}
#wf .stt .by{margin-left:auto}
#wf .ipo{grid-template-columns:repeat(auto-fit,minmax(min(220px,100%),1fr))}
#wf .io.chgs{grid-column:1/-1}
#wf .io.chgs ul{list-style:none;display:grid;gap:.35em;margin-top:.45em;font-size:.82em}
#wf .io.chgs li{border:1px solid var(--bg-grid);border-radius:.5em;padding:.4em .7em;background:rgba(237,241,247,.5)}
#wf .io.chgs li p{color:var(--text-body);margin-top:.1em;font-size:.95em}
@media (max-width:720px){#wf .stations{flex-wrap:wrap}#wf .stations .st{flex:1 1 30%}#wf .watch{flex-direction:column;align-items:stretch}#wf .wrow{flex-wrap:wrap}#wf .wrow .st{flex:1 1 45%}#wf .st .t{word-break:keep-all;overflow-wrap:normal}}
footer{margin-top:40px;color:var(--text-footer);font-size:12px}
</style></head><body>
%%SYMBOL%%
<div class="wrap">
<div class="eyebrow">CHANGE DASHBOARD · %%PERIOD%% · <span>%%BRANCH%%</span></div>
<h1>세션 변경 대시보드</h1>
<div class="headline"><b>이번 회차 요약</b>%%HEADLINE%%</div>
<div class="kpi"><div class="panel"><b>%%NSESS%%</b><span>활동한 세션</span></div><div class="panel"><b>%%NFILES%%</b><span>바뀐 파일</span></div><div class="panel"><b>%%NCOMMIT%%</b><span>이 기간 커밋</span></div><div class="panel"><b>%%NUNC%%</b><span>아직 커밋 안 된 변경</span></div></div>
<div class="legend">%%LEGEND%%</div>

<h2>S4 · 팀 지도에서 본 변화</h2>
<p class="sub">소개서 S4와 같은 그림입니다. 노란 테두리와 숫자 배지가 이번 기간에 바뀐 역할이고, 작은 점은 어느 세션이 바꿨는지를 나타냅니다.</p>
<div class="panel s4box">%%SVG%%</div>
<p class="hint">bot · skill · 작업대 · 엔지니어를 누르면 연결선이 켜지고 아래에 그 대상의 변경 사항이 나옵니다. 빈 곳을 누르면 처음으로 돌아갑니다.</p>
<div class="panel detail" id="detail"></div>

<h2>S5 단계별 변경 수</h2>
<p class="sub">단계를 누르면 위 상세 칸에 그 단계의 변경이 나옵니다. 여러 단계에 걸친 공통 코드 · 문서는 아래에 따로 모았습니다.</p>
<div class="chips">%%CHIPS%%</div>
<p class="sub" style="margin-top:10px">공통 영역: %%COMMON%%</p>

<h2>세션별로 무엇을 했나</h2>
%%CARDS%%
<h2>용어 풀이</h2><dl>%%GLOSS%%</dl>
<h2>이 기간 커밋</h2><ul class="pr">%%COMMITS%%</ul>

<h2>전체 작업공간 workflow</h2>
<p class="sub">소개서 S5와 같은 단계 줄입니다. 단계를 누르면 입력 · 처리 · 출력과 이번 기간에 그 단계에서 바뀐 것이 나옵니다. 노란 배지는 변경 수입니다.</p>
<div class="panel" id="wf">
  <div class="track"><div class="stations" id="stations"></div></div>
  <div class="watch" id="watchLane"><span class="wl">상시 감시 · 같은 층</span><div class="wrow" id="watch"></div></div>
  <p class="stt" id="stt"></p>
  <div class="ipo">
    <div class="io"><small>입력 · INPUT</small><p id="ioI"></p></div>
    <div class="io proc" id="ioProc"><small>처리 · PROCESS <button class="dt" id="detBtn" type="button">세부 단계 ▾</button></small><p id="ioP"></p><ul id="ioD"></ul></div>
    <div class="io"><small>출력 · OUTPUT</small><p id="ioO"></p><span class="num" id="ioN"></span></div>
    <div class="io chgs"><small>이번 기간 변경 · CHANGES</small><div id="ioC"></div></div>
  </div>
</div>

<h2>지난 대시보드</h2><div class="hist">%%HIST%%</div>
<footer>change-dashboard · collect.py → render.py · S4 · S5 그림 출처 docs/project_intro.html · 디자인 design.md.md</footer>
</div>
<script>
(function(){
  var D=%%DATA%%;
  var ST=%%ST%%;
  var NS='http://www.w3.org/2000/svg';
  function esc(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
  function dot(t){return '<i class="dot" style="background:'+(D.color[t]||'#9DAABF')+'" title="'+esc(t)+'"></i>';}
  function count(n){return n?n.files.length+n.changes.length+((n.prompts||[]).length):0;}
  function el(tag,attrs){var x=document.createElementNS(NS,tag);for(var k in attrs)x.setAttribute(k,attrs[k]);return x;}
  function listChanges(arr){
    if(!arr.length) return '';
    return '<h4>무엇이 바뀌었나</h4><ul>'+arr.map(function(c){return '<li>'+dot(c.session)+'<b>'+esc(c.title)+'</b>'+(c.stage?' <span class="tag">'+esc(c.stage)+'</span>':'')+'<p>'+esc(c.why)+'</p></li>';}).join('')+'</ul>';
  }
  function listFiles(arr){
    if(!arr.length) return '';
    return '<h4>바뀐 파일 '+arr.length+'개</h4><ul class="fl">'+arr.map(function(f){return '<li>'+dot(f.session)+'<code>'+esc(f.path)+'</code><span class="who">'+esc(f.where)+' · '+(f.commits?'커밋 '+f.commits.join(', '):'편집 '+f.edits+'회')+'</span></li>';}).join('')+'</ul>';
  }
  function listPrompts(arr){
    if(!arr||!arr.length) return '';
    return '<h4>요청 '+arr.length+'건</h4><ul>'+arr.map(function(p){return '<li>'+dot(p.session)+'<span class="mono who">'+esc(p.ts)+'</span><p>'+esc(p.text)+'</p></li>';}).join('')+'</ul>';
  }

  /* ---- S4: 원본 도형은 그대로 두고 배지·세션 점만 덧씌운다 ---- */
  var svg=document.getElementById('orch'), box=document.getElementById('detail');
  if(svg){
    svg.querySelectorAll('.nd[data-n]').forEach(function(g){
      var k=g.getAttribute('data-n'), n=D.nodes[k], c=count(n); if(!c) return;
      g.classList.add('chg');
      var r=g.querySelector('.hit'), x=+r.getAttribute('x')+(+r.getAttribute('width')), y=+r.getAttribute('y');
      var b=el('g',{'class':'bdg'}); b.appendChild(el('circle',{cx:x-4,cy:y+4,r:11}));
      var t=el('text',{x:x-4,y:y+8,'text-anchor':'middle'}); t.textContent=c>99?'99+':c; b.appendChild(t); g.appendChild(b);
      n.sessions.forEach(function(s,i){g.appendChild(el('circle',{'class':'sdot',cx:x-22-i*11,cy:y+4,r:4.5,fill:D.color[s]||'#9DAABF'}));});
    });
  }
  function show(title,sub,desc,n){
    var body=listChanges(n.changes)+listFiles(n.files)+listPrompts(n.prompts);
    box.innerHTML='<div class="hd"><b>'+esc(title)+'</b><small>'+esc(sub)+'</small><span>'+esc(desc)+'</span></div>'+(body||'<p class="muted">이 기간에는 바뀐 것이 없습니다.</p>');
  }
  function idle(){
    var hot=Object.keys(D.nodes).filter(function(k){return count(D.nodes[k]);});
    box.innerHTML='<div class="hd"><b>상세 보기</b><small>click</small><span>그림의 노드나 아래 단계를 누르면 여기에 변경 사항이 나옵니다</span></div>'+
      '<p class="muted">바뀐 역할: '+(hot.length?hot.map(function(k){return esc(D.info[k].name)+' '+count(D.nodes[k]);}).join(' · '):'없음')+'</p>';
  }
  function clearSel(){
    if(svg){svg.classList.remove('focus');svg.querySelectorAll('.hi,.sel').forEach(function(x){x.classList.remove('hi');x.classList.remove('sel');});}
    document.querySelectorAll('.sc.sel').forEach(function(x){x.classList.remove('sel');});
  }
  if(svg) svg.addEventListener('click',function(ev){
    var g=ev.target.closest&&ev.target.closest('.nd'), k=g&&g.getAttribute('data-n');
    clearSel();
    if(!k||!D.nodes[k]){idle();return;}
    svg.classList.add('focus');
    svg.querySelectorAll('[data-k]').forEach(function(x){x.classList.toggle('hi',x.getAttribute('data-k').split(' ').indexOf(k)>=0);});
    g.classList.add('sel');
    var i=D.info[k]; show(i.name,i.sub,i.desc,D.nodes[k]);
  });
  document.querySelectorAll('.sc[data-st]').forEach(function(b){
    b.addEventListener('click',function(){
      var st=b.getAttribute('data-st'); clearSel(); b.classList.add('sel');
      show(st,'S5 단계',D.stageDesc[st]||'',D.stages[st]);
      box.scrollIntoView({behavior:'smooth',block:'nearest'});
    });
  });
  idle();

  /* ---- 전체 workflow: S5 단계 데이터(ST)를 그대로 쓴다 ---- */
  var sbox=document.getElementById('stations'), wbox=document.getElementById('watch'), all=[], cur=0;
  if(!ST.length){document.getElementById('wf').innerHTML='<p class="muted">S5 단계 데이터를 찾지 못했습니다.</p>';return;}
  var main=0;
  ST.forEach(function(s,k){
    var b=document.createElement('button'); b.type='button';
    var n=count(D.stages[s.t]);
    b.className='st'+(s.wt?' wt':'');
    b.innerHTML=(s.wt?'':'<span class="n">'+String(++main).padStart(2,'0')+'</span>')+'<span class="t">'+esc(s.t)+'</span>'+(s.wt?'':'<span class="r">'+esc(s.r||s.g)+'</span>')+(n?'<span class="bd">'+n+'</span>':'');
    b.addEventListener('click',function(){pick(k);});
    (s.wt?wbox:sbox).appendChild(b); all.push(b);
  });
  var proc=document.getElementById('ioProc');
  document.getElementById('detBtn').addEventListener('click',function(){proc.classList.toggle('det');});
  function pick(k){
    cur=k; var s=ST[k];
    all.forEach(function(b,j){b.classList.toggle('on',j===k);b.classList.toggle('done',!s.wt&&!ST[j].wt&&j<k);});
    document.getElementById('stt').innerHTML='<span class="n">'+(s.wt?'감시':'STEP')+'</span><b>'+esc(s.t)+'</b><span>'+esc(s.g)+'</span><span class="by">담당 <b>'+esc(s.w)+'</b></span>';
    document.getElementById('ioI').textContent=s.i||'';
    document.getElementById('ioP').textContent=s.p||'';
    document.getElementById('ioD').innerHTML=(s.d||[]).map(function(x){return '<li>'+esc(x)+'</li>';}).join('');
    document.getElementById('ioO').textContent=s.o||'';
    document.getElementById('ioN').textContent=s.n||'';
    var n=D.stages[s.t]||{files:[],changes:[]};
    var c=n.changes.map(function(x){return '<li>'+dot(x.session)+'<b>'+esc(x.title)+'</b><p>'+esc(x.why)+'</p></li>';}).join('')+
          n.files.map(function(f){return '<li>'+dot(f.session)+'<code class="mono">'+esc(f.path)+'</code> <span class="who">'+(f.commits?'커밋 '+f.commits.join(', '):'편집 '+f.edits+'회')+'</span></li>';}).join('');
    document.getElementById('ioC').innerHTML=c?'<ul>'+c+'</ul>':'<p class="muted" style="margin-top:.4em;font-size:.85em">이번 기간에는 이 단계에서 바뀐 것이 없습니다.</p>';
  }
  var first=ST.findIndex(function(s){return count(D.stages[s.t]);});
  pick(first<0?0:first);
})();
</script>
</body></html>
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description="변경 대시보드 렌더")
    ap.add_argument("--stamp", help="data/<stamp>_facts.json 의 stamp (기본 최신)")
    a = ap.parse_args(argv)
    stamps = sorted(os.path.basename(p)[:-11] for p in glob.glob(os.path.join(DATA, "*_facts.json")))
    if not stamps:
        print("[render] 오류: facts 없음")
        return 2
    stamp = a.stamp or stamps[-1]
    facts, summary = load(stamp)
    os.makedirs(REPORTS, exist_ok=True)
    rendered = [s for s in stamps if s == stamp or os.path.exists(os.path.join(REPORTS, s + ".html"))]

    def history(prefix):
        return [{"href": prefix + s + ".html", "label": s, "cur": s == stamp} for s in reversed(rendered)]

    with open(os.path.join(REPORTS, stamp + ".html"), "w", encoding="utf-8") as f:
        f.write(build(facts, summary, history("")))
    if stamp == stamps[-1]:
        with open(os.path.join(HERE, "index.html"), "w", encoding="utf-8") as f:
            f.write(build(facts, summary, history("reports/")))
    print("[render] %s -> change-dashboard/reports/%s.html%s" % (stamp, stamp, " + index.html" if stamp == stamps[-1] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
