"""docs/project_intro.html의 PILOT RESULT(id s7, 화면 번호 08)를 최신 작업 폴더의 실행 수치로 다시 채우고 사본을 남긴다.

표준 라이브러리만 쓴다(Python 3.14). LLM 호출 0회. 작업 폴더의 SQLite는 읽기 전용으로 연다.
원본 파일·.b64·chunk 본문은 열지 않고, HTML에는 건수·실행 ID·사유 코드 이름만 넣는다.

    python build_project_html.py [--workspace <WS>] [--run <RUN>] [--out <HTML>] [--snapshot-dir <DIR>] [--no-snapshot] [--dry-run]

출력: 한 줄 JSON (out, snapshot, workspace, run_id, reviewed, metrics, checks, error)
"""
import argparse
import datetime as dt
import html
import json
import math
import re
import sqlite3
import sys
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[4]
INTRO = CODE_ROOT / "docs" / "project_intro.html"
WS_ROOT = CODE_ROOT / "workspaces"

# 파일럿 슬라이드 문구(바꾸려면 여기만 고친다)
BADGE = "더미 데이터 기준"
LEAD = "전 과정이 끝까지 도는지 확인한 수치입니다."
NA_TH, DUP_TH = 30.0, 40.0                       # labelbot H5 기본 기준(%). alerts 표에 값이 있으면 그 값을 쓴다
PALETTE = ["#4A5FA8", "#E08A2E", "#2BA39A"]      # dataviz 검증 통과(남색·주황·청록). 4번째부터는 '기타'
OTHER = "#8A97AD"
REASON_KO = {"LOW_CONFIDENCE": "확신도 낮음", "UNKNOWN_HIGH": "\"모름\"이 많음", "QUOTE_NOT_FOUND": "인용문 없음",
             "PARSE_WARNING": "파싱 경고", "CLASSIFY_FAILED": "분류 실패", "LABEL_FAILED": "라벨 실패",
             "CONTROL_O": "대조 질문에 O", "UNKNOWN_O": "모름인데 O"}
# 한 chunk에 사유가 여럿이면 이 순서로 대표 사유 하나를 고른다(심각한 것 먼저)
PRIORITY = ["CLASSIFY_FAILED", "LABEL_FAILED", "PARSE_WARNING", "QUOTE_NOT_FOUND", "CONTROL_O", "UNKNOWN_O", "UNKNOWN_HIGH", "LOW_CONFIDENCE"]
E = html.escape


class BuildError(Exception):
    pass


def ro(path):
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def pick_workspace(arg):
    if arg:
        ws = Path(arg)
        if not (ws / "work.sqlite").exists():
            raise BuildError("WORKSPACE_NO_DB")
        return ws
    cands = [d for d in WS_ROOT.glob("261004_BEOL_*") if (d / "work.sqlite").exists()]
    if not cands:
        raise BuildError("WORKSPACE_NOT_FOUND")
    return max(cands, key=lambda d: (d / "work.sqlite").stat().st_mtime)


def read_text(p):
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def collect(ws, run_arg):
    w = ro(ws / "work.sqlite")
    try:
        if run_arg:
            run = run_arg
        else:
            row = w.execute("select run_id from runs where command='run' order by started_at desc limit 1").fetchone()
            if not row:
                raise BuildError("RUN_NOT_FOUND")
            run = row[0]
        files_ok, files_fail = w.execute("select coalesce(sum(status='ok'),0), coalesce(sum(status!='ok'),0) from files").fetchone()
        flagged = [json.loads(r[0] or "[]") for r in w.execute("select reason_codes from flagged_chunks where run_id=?", (run,))]
        corr = dict(w.execute("select target_kind, count(*) from corrections where review_run_id=? group by target_kind", (run,)).fetchall())
        ans_fix = [(json.loads(b), json.loads(h)) for b, h in w.execute(
            "select bot_value, human_value from corrections where review_run_id=? and target_kind='answer'", (run,))]
        alerts = {c: (v, t) for c, v, t in w.execute("select condition, value, threshold from alerts where run_id=?", (run,))}
        emb = w.execute("select count(*) from chunk_embeddings").fetchone()[0]
        push = w.execute("select count(distinct chunk_id) from vector_push_log where result_code='OK'").fetchone()[0]
        chunks_w = w.execute("select count(*) from chunks").fetchone()[0]
    finally:
        w.close()

    out_db = ws / "out" / "labeling.sqlite"
    chunks, bot = chunks_w, {}
    if out_db.exists():
        o = ro(out_db)
        try:
            chunks = o.execute("select count(*) from chunks").fetchone()[0]
            fin = {}
            for (a,) in o.execute("select answer from answers"):
                fin[a] = fin.get(a, 0) + 1
        finally:
            o.close()
        bot = dict(fin)
        for b, h in ans_fix:                      # 사람 교정을 되돌려 봇의 원래 답 분포를 구한다
            bot[h] = bot.get(h, 0) - 1
            bot[b] = bot.get(b, 0) + 1
        bot = {k: v for k, v in bot.items() if v > 0}

    base = read_text(ws / "reports" / f"baseline_{run}.md")
    m = re.search(r"N/A 비율:\s*([\d.]+)%.*?중복 라벨링 비율:\s*([\d.]+)%", base)
    na_ratio, dup = (float(m.group(1)), float(m.group(2))) if m else (None, None)
    cand = read_text(ws / "reports" / "candidates.md")
    syn = re.search(r"^## 동의어[^\n]*?(\d+)건", cand, re.M)
    newv = re.search(r"^## 새 값[^\n]*?(\d+)건", cand, re.M)

    done = None
    sig = ws / "signals" / f"review_done_{run}.json"
    if sig.exists():
        try:
            done = json.loads(sig.read_text(encoding="utf-8")).get("done_at")
        except (OSError, ValueError):
            done = None
    try:
        skipped = len(json.loads((ws / "pipeline.json").read_text(encoding="utf-8")).get("skip_file_names") or [])
    except (OSError, ValueError):
        skipped = 0

    na_th = round(alerts["NA_RATIO_LOW"][1] * 100, 1) if "NA_RATIO_LOW" in alerts else NA_TH
    dup_th = round(alerts["DUP_LABEL_HIGH"][1] * 100, 1) if "DUP_LABEL_HIGH" in alerts else DUP_TH
    return dict(run=run, done=done, reviewed=done is not None, files=files_ok, files_fail=files_fail, skipped=skipped,
                chunks=chunks, o=bot.get("O", 0), x=bot.get("X", 0), na=bot.get("N/A", 0), ans=sum(bot.values()),
                flagged=flagged, ax=corr.get("axis", 0), an=corr.get("answer", 0),
                na_ratio=na_ratio, dup=dup, na_th=na_th, dup_th=dup_th,
                na_alert="NA_RATIO_LOW" in alerts, dup_alert="DUP_LABEL_HIGH" in alerts,
                syn=int(syn.group(1)) if syn else 0, new_val=int(newv.group(1)) if newv else 0, emb=emb, push=push)


# ---------------- 파일럿 슬라이드(id s7) 렌더링 ----------------
def reasons(flagged):
    prim = []
    for codes in flagged:
        codes = codes or ["LOW_CONFIDENCE"]
        prim.append(min(codes, key=lambda c: PRIORITY.index(c) if c in PRIORITY else len(PRIORITY)))
    cnt = {}
    for c in prim:
        cnt[c] = cnt.get(c, 0) + 1
    order = sorted(cnt, key=lambda c: (-cnt[c], PRIORITY.index(c) if c in PRIORITY else 99))
    top, rest = order[:3], order[3:]
    rows = [(REASON_KO.get(c, c), cnt[c], PALETTE[i], c) for i, c in enumerate(top)]
    if rest:
        rows.append(("기타", sum(cnt[c] for c in rest), OTHER, ", ".join(rest)))
    return rows


def waffle(rows, chunks):
    per = 1 if chunks <= 60 else math.ceil(chunks / 60)
    cols = 5 if chunks <= 25 else 10
    cells = []
    for n, v, col, _ in rows:
        cells += [f'<i style="background:{col}" title="{E(n)}"></i>'] * math.ceil(v / per)
    flagged = sum(r[1] for r in rows)
    cells += ['<i title="이상 없음"></i>'] * max(0, math.ceil(chunks / per) - len(cells))
    lab = ", ".join(f"{n} {v}" for n, v, _, _ in rows)
    note = f" (한 칸 = chunk {per}개)" if per > 1 else ""
    return (f'<div class="pv-waf" style="grid-template-columns:repeat({cols},1fr)" role="img" '
            f'aria-label="chunk {chunks}개 중 {flagged}개 의심{": " + E(lab) if lab else ""}{note}">' + "".join(cells) + "</div>")


def legend(rows):
    if not rows:
        return '<div class="pv-lg"><span>의심 chunk 없음</span></div>'
    return '<div class="pv-lg">' + "".join(
        f'<span title="{E(c)}"><i style="background:{col}"></i>{E(n)}<b>{v}</b></span>' for n, v, col, c in rows) + "</div>"


def gauge(name, val, th, rule, alert):
    if val is None:
        return f'<figure><figcaption><b>{name}</b><br>기록 없음</figcaption></figure>'
    def pt(p, r):
        a = math.pi * (1 - min(max(p, 0), 100) / 100)
        return 60 + r * math.cos(a), 60 - r * math.sin(a)
    x0, y0 = pt(0, 46); x1, y1 = pt(100, 46); xv, yv = pt(val, 46)
    t0x, t0y = pt(th, 38); t1x, t1y = pt(th, 56)
    col = "#C99A3B" if alert else "#4A5FA8"
    return (f'<figure title="{name} {val}% · {rule}"><svg viewBox="0 0 120 70" role="img" aria-label="{name} {val}%, {rule}{", 알림" if alert else ""}">'
            f'<path d="M{x0:.1f} {y0:.1f} A46 46 0 0 1 {x1:.1f} {y1:.1f}" fill="none" stroke="#EDF1F7" stroke-width="11" stroke-linecap="round"/>'
            f'<path d="M{x0:.1f} {y0:.1f} A46 46 0 0 1 {xv:.1f} {yv:.1f}" fill="none" stroke="{col}" stroke-width="11" stroke-linecap="round"/>'
            f'<path d="M{t0x:.1f} {t0y:.1f}L{t1x:.1f} {t1y:.1f}" stroke="#1E2D4A" stroke-width="2"/>'
            f'<text x="60" y="56" text-anchor="middle" font-size="17" font-weight="700" fill="#1E2D4A" font-family="monospace">{val:.0f}%</text>'
            f'</svg><figcaption><b>{name}</b><br>{rule}</figcaption></figure>')


def quad(D):
    def c(v, t):
        return f'<div><b class="{"z" if v == 0 else ""}">{v}</b><span>{t}</span></div>'
    return ('<div class="pv-q">' + c(D["ax"], "labeling 교정") + c(D["an"], "LLM O/X 퀴즈 오답 교정")
            + c(D["new_val"], "새로운 label 후보") + c(D["syn"], "동의어 후보") + "</div>")


def fix_block(rows, D):
    n = sum(r[1] for r in rows)
    sq = []
    for _, v, col, _ in rows:
        sq += [f'<i style="background:{col}"></i>'] * v
    sq = sq[:10]
    if D["reviewed"]:
        hd, after_lbl, after_n, cls = ("불량 chunk · 사람 검수로 모두 해결" if n else "불량 chunk 없음"), "검수 후", 0, "g"
        after_sq = '<i></i>' * len(sq)
        ok = " ok"
    else:
        hd, after_lbl, after_n, cls = "불량 chunk · 사람 검수 대기", "검수 대기", n, "w"
        after_sq, ok = "", ""
    aria = f"불량 chunk가 검수 전 {n}개에서 {after_lbl} {after_n}개" if D["reviewed"] else f"불량 chunk {n}개가 사람 검수를 기다린다"
    return (f'<div class="pv-fix" role="img" aria-label="{aria}"><span class="hd">{hd}</span>'
            f'<div><small>검수 전</small><span class="sq">{"".join(sq)}</span><b class="w">{n}</b></div>'
            f'<span class="ar">→</span>'
            f'<div><small>{after_lbl}</small><span class="sq{ok}">{after_sq}</span><b class="{cls}">{after_n}</b></div></div>')


def fmt_done(s):
    if not s:
        return "검수 대기"
    try:
        return "검수 완료 " + dt.datetime.fromisoformat(s).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return "검수 완료 " + E(s)


def render_s7(D, eyebrow, h2, pg):
    rows = reasons(D["flagged"])
    nfl = len(D["flagged"])
    skip = f" 이미 처리한 {D['skipped']}개 파일은 건너뛰었습니다." if D["skipped"] else ""
    nalerts = int(D["na_alert"]) + int(D["dup_alert"])
    gauges = (gauge("N/A 비율", D["na_ratio"], D["na_th"], f"{D['na_th']:g}% 아래면 알림", D["na_alert"])
              + gauge("중복 label", D["dup"], D["dup_th"], f"{D['dup_th']:g}% 넘으면 알림", D["dup_alert"]))
    return f'''<section class="slide" id="s7"><div class="stage"><div class="in">
  {eyebrow}
  {h2}
  <p class="meta rv" style="--d:100ms"><span class="badge b-warn"><i></i>{BADGE}</span>{LEAD}{skip} <span class="mono">run {E(D['run'])} · {fmt_done(D['done'])}</span></p>
  <div class="tiles rv" style="--d:200ms">
    <div class="tile"><b data-n="{D['files']}">0</b><span>{"새 " if D['skipped'] else ""}pptx 파일<br>(실패 {D['files_fail']})</span></div>
    <div class="tile"><b data-n="{D['chunks']}">0</b><span>chunk<br>(슬라이드 단위)</span></div>
    <div class="tile"><b data-n="{D['ans']}">0</b><span>LLM의 답<br>O {D['o']} · X {D['x']} · N/A {D['na']}</span></div>
    <div class="tile warn"><b data-n="{nfl}">0</b><span>불량 chunk<br>(의심 조각)</span></div>
    <div class="tile hum"><b data-n="{D['ax'] + D['an']}">0</b><span>사람 교정<br>축 {D['ax']} · 답 {D['an']}</span></div>
    <div class="tile"><b data-n="{D['push']}">0</b><span>DB 적재 chunk<br>embedding {D['emb']}</span></div>
  </div>
  <div class="grid3">
    <div class="pn rv" style="--d:350ms">
      <h3>왜 의심했나<small>{D['chunks']}개 중 {nfl}개</small></h3>
      <div class="pv-body"><div class="pv-wl">{waffle(rows, D['chunks'])}{legend(rows)}</div></div>
    </div>
    <div class="pn rv" style="--d:500ms">
      <h3>분포 알림 {nalerts}건<small>멈추지 않고 알리기만</small></h3>
      <div class="pv-body"><div class="pv-gauges">{gauges}</div></div>
    </div>
    <div class="pn rv" style="--d:650ms">
      <h3>사람 검수와 다음 실행</h3>
      <div class="pv-body">{quad(D)}{fix_block(rows, D)}</div>
    </div>
  </div>
  {pg}
</div></div></section>'''


# ---------------- 반영 · 검사 ----------------
S7_RE = re.compile(r'<section class="slide" id="s7">.*?</section>', re.S)


def apply(src, D):
    m = S7_RE.search(src)
    if not m:
        raise BuildError("S7_NOT_FOUND")
    old = m.group(0)
    eb = re.search(r'<div class="eyebrow">.*?</div>', old)
    h2 = re.search(r'<h2 class="h[^"]*">.*?</h2>', old, re.S)
    pg = re.search(r'<span class="pg">.*?</span>', old)
    if not (eb and h2 and pg):
        raise BuildError("S7_PARTS_NOT_FOUND")
    for need in (".pv-waf", ".pv-gauges", ".pv-fix", ".pv-q"):
        if need not in src:
            raise BuildError("S7_CSS_MISSING")
    return src[:m.start()] + render_s7(D, eb.group(0), h2.group(0), pg.group(0)) + src[m.end():]


# ---------------- Appendix · 스킬 지도(id sA) ----------------
SKILL_MAP = Path(__file__).resolve().parents[1] / "assets" / "skill_map.json"
SKILLS_DIR = CODE_ROOT / ".claude" / "skills"
SA_RE = re.compile(r'\n*<!-- =+ APPENDIX SKILL MAP =+ -->\n<section class="slide" id="sA">.*?</section>', re.S)
SA_NAV = '<a href="#sA" data-s="sA"><b>A</b><span>Appendix · Skill map</span></a>'
SA_CSS = """<style>
#sA .sk-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.8em;margin-top:.9em}
#sA .sk-g{background:var(--surface);border:1px solid var(--bg-grid);border-top:.3em solid var(--c);border-radius:.75em;padding:.85em 1em;display:flex;flex-direction:column;gap:.5em}
#sA .sk-g h3{font-size:.95em;font-weight:700;letter-spacing:-0.04em}
#sA .sk-g h3 b{font-family:var(--mono);color:var(--c);margin-right:.35em}
#sA .sk-g>p{font-size:.72em;color:#5A6B85;line-height:1.45}
#sA .sk{font-size:.78em;line-height:1.4;padding:.45em .6em;border-radius:.5em;background:var(--bg-base)}
#sA .sk code{font-family:var(--mono);font-size:.92em;font-weight:600;color:var(--primary-deep);word-break:break-all}
#sA .sk span{display:block;color:#4A5568;font-size:.92em}
#sA .sk.ch{margin-left:1.1em;position:relative;background:transparent;border:1px dashed var(--bg-grid)}
#sA .sk.ch::before{content:"";position:absolute;left:-.8em;top:-.35em;bottom:50%;width:.6em;border-left:1px solid var(--line);border-bottom:1px solid var(--line)}
#sA .sk-bridge{margin-top:.8em;font-size:.78em;color:#4A5568}
@media (max-width:900px){
  #sA{height:auto;min-height:100vh}
  #sA .stage{aspect-ratio:auto;width:100%}
  #sA .in{position:relative;font-size:14px;padding:1.4em 1.1em}
  #sA .sk-grid{grid-template-columns:1fr}
}
</style>"""


def load_skill_map():
    """skill_map.json과 .claude/skills/ 폴더를 맞춰 본다. 지도에 없는 폴더는 '미분류' 그룹으로 붙인다."""
    m = json.loads(SKILL_MAP.read_text(encoding="utf-8"))
    on_disk = sorted(p.parent.name for p in SKILLS_DIR.glob("*/SKILL.md"))
    mapped = [s["name"] for g in m["groups"] for top in g["skills"] for s in [top] + top.get("children", [])]
    unmapped = [n for n in on_disk if n not in mapped]
    if unmapped:
        m["groups"].append({"title": "미분류", "lead": "skill_map.json에 아직 넣지 않은 스킬", "color": OTHER,
                            "skills": [{"name": n, "role": ""} for n in unmapped]})
    return m, {"skills_total": len(on_disk), "skills_unmapped": unmapped,
               "skills_missing": [n for n in mapped if n not in on_disk]}


def render_sA(m, total):
    def card(s, child=False):
        role = f'<span>{E(s["role"])}</span>' if s.get("role") else ""
        return f'<div class="sk{" ch" if child else ""}"><code>{E(s["name"].removeprefix("BEOL-labeling-"))}</code>{role}</div>'
    cols = []
    for i, g in enumerate(m["groups"], 1):
        items = "".join(card(top) + "".join(card(c, True) for c in top.get("children", [])) for top in g["skills"])
        cols.append(f'<div class="sk-g rv" style="--c:{g["color"]};--d:{150 + 150 * i}ms"><h3><b>{i:02d}</b>{E(g["title"])}</h3>'
                    f'<p>{E(g["lead"])}</p>{items}</div>')
    n = sum(1 + len(top.get("children", [])) for g in m["groups"] for top in g["skills"])
    bridge = f'<p class="sk-bridge rv" style="--d:800ms"><span class="badge b-info"><i></i>연결</span>{E(m["bridge"])}</p>' if m.get("bridge") else ""
    return f'''

<!-- ================= APPENDIX SKILL MAP ================= -->
<section class="slide" id="sA"><div class="stage"><div class="in">
  {SA_CSS}
  <div class="eyebrow">APPENDIX — SKILL MAP</div>
  <h2 class="h md rv">이 프로젝트를 움직이는 <em>스킬 {n}개</em></h2>
  <p class="meta rv" style="--d:100ms">들여 쓴 칸은 위 스킬이 부르는 하위 스킬입니다. 이름의 <span class="mono">BEOL-labeling-</span>은 줄여 썼습니다.</p>
  <div class="sk-grid">{"".join(cols)}</div>
  {bridge}
  <span class="pg">A / {total}</span>
</div></div></section>'''


def apply_sA(src):
    m, info = load_skill_map()
    totals = re.findall(r'<span class="pg">[0-9+]+ / (\d+)</span>', src)
    sec = render_sA(m, totals[0] if totals else "?")
    src = SA_RE.sub("", src)
    end = src.rfind("</section>")
    if end < 0:
        raise BuildError("SA_ANCHOR_NOT_FOUND")
    end += len("</section>")
    src = src[:end] + sec + src[end:]
    if 'data-s="sA"' not in src:
        nav_end = src.find("</div>", src.find('id="navlinks"'))
        if nav_end < 0:
            raise BuildError("SA_NAV_NOT_FOUND")
        src = src[:nav_end] + "  " + SA_NAV + "\n  " + src[nav_end:]
    return src, info


def checks(h):
    slides = len(re.findall(r'<section class="slide" id="', h))
    links = len(re.findall(r'<a href="#[^"]+" data-s="', h))
    totals = set(re.findall(r'<span class="pg">[0-9+]+ / (\d+)</span>', h))
    external = bool(re.search(r'<script[^>]+src=|<link[^>]+href=|(?:src|href)="https?:', h))
    return {"slides": slides, "nav_links": links, "nav_matches": slides == links,
            "pg_totals": sorted(totals), "pg_consistent": len(totals) == 1, "external_resources": external}


# ---------------- 사용자 흐름도(docs/user_flow.html) ----------------
FLOW = CODE_ROOT / "docs" / "user_flow.html"


def flow_checks(h):
    """user_flow.html은 손으로 쓴 안내 페이지(화면 그림 내장)라 내용은 고치지 않고 검사만 한다."""
    steps = re.findall(r'<article class="step [^"]*" id="(s\d+)"', h)
    links = re.findall(r'<a class="node[^"]*" href="#(s\d+)"', h)
    plain = re.sub(r'data:[a-z]+/[a-z0-9.+-]+;base64,[A-Za-z0-9+/=]+', "data:", h)
    return {"steps": len(steps), "map_links": len(links), "map_matches": sorted(steps) == sorted(links),
            "images": len(re.findall(r'src="data:image/', h)),
            "external_resources": bool(re.search(r'<script[^>]+src=|<link[^>]+href=|(?:src|href)="https?:', plain))}


def build_flow(a):
    f = Path(a.flow)
    if not f.exists():
        raise BuildError("USER_FLOW_NOT_FOUND")
    h = f.read_text(encoding="utf-8")
    res = {"out": str(f), "snapshot": None, "checks": flow_checks(h)}
    if not a.dry_run and not a.no_snapshot:
        sd = Path(a.snapshot_dir)
        sd.mkdir(parents=True, exist_ok=True)
        snap = sd / f"user_flow_{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.html"
        snap.write_text(h, encoding="utf-8", newline="")
        res["snapshot"] = str(snap)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace")
    ap.add_argument("--run")
    ap.add_argument("--out", default=str(INTRO))
    ap.add_argument("--snapshot-dir", default=str(CODE_ROOT / "docs" / "snapshots"))
    ap.add_argument("--flow", default=str(FLOW))
    ap.add_argument("--no-flow", action="store_true")
    ap.add_argument("--no-snapshot", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    res = {"out": None, "snapshot": None, "workspace": None, "run_id": None, "reviewed": None, "metrics": None, "checks": None, "flow": None, "error": None}
    try:
        ws = pick_workspace(a.workspace)
        res["workspace"] = str(ws)
        D = collect(ws, a.run)
        res.update(run_id=D["run"], reviewed=D["reviewed"])
        res["metrics"] = {k: D[k] for k in ("files", "files_fail", "skipped", "chunks", "ans", "o", "x", "na", "ax", "an",
                                            "na_ratio", "dup", "na_alert", "dup_alert", "new_val", "syn", "emb", "push")}
        res["metrics"]["flagged"] = len(D["flagged"])
        res["metrics"]["reasons"] = {c: v for _, v, _, c in reasons(D["flagged"])}
        src = INTRO.read_text(encoding="utf-8")
        out_html, sa = apply_sA(apply(src, D))
        res["checks"] = checks(out_html) | sa
        if not a.dry_run:
            out = Path(a.out)
            out.write_text(out_html, encoding="utf-8", newline="")
            res["out"] = str(out)
            if not a.no_snapshot:
                sd = Path(a.snapshot_dir)
                sd.mkdir(parents=True, exist_ok=True)
                snap = sd / f"project_intro_{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.html"
                snap.write_text(out_html, encoding="utf-8", newline="")
                res["snapshot"] = str(snap)
        if not a.no_flow:
            res["flow"] = build_flow(a)
    except BuildError as e:
        res["error"] = str(e)
    except (sqlite3.Error, OSError) as e:
        res["error"] = type(e).__name__
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False))
    return 1 if res["error"] else 0


if __name__ == "__main__":
    sys.path.insert(0, str(CODE_ROOT))
    from labelbot import trace  # noqa: E402  마일스톤 M21(stderr 줄, stdout JSON 불변)

    sys.exit(trace.run_main("M21", main))
