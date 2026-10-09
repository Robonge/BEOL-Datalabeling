"""아침 대응 목록(nightly_run.py 결과)을 사람이 보는 daily report HTML 한 장으로 만든다.

실행: python daily_report.py [--run] [--days 7] [--open]
- 오늘 nightly 결과가 없으면 nightly_run.py를 먼저 한 번 돌린다(--run이면 있어도 다시 돌린다).
- 입력: workspaces/_nightly/<YYYYMMDD>/morning_queue.jsonl, steps.jsonl (최근 --days일)
- 출력: workspaces/_nightly/<YYYYMMDD>/daily_report.html, workspaces/_nightly/daily_report.html(최신본)
- 디자인은 docs/project_intro.html(design.md.md) 토큰·컴포넌트를 따른다. 외부 리소스 없음, 표준 라이브러리만.
"""
import argparse
import datetime
import html
import json
import os
import sys
import webbrowser
from pathlib import Path

import nightly_run
from labelbot import trace  # noqa: E402  nightly_run이 코드 폴더를 sys.path에 넣는다

ROOT = nightly_run.ROOT
OUT_DIR = nightly_run.OUT_DIR

SEV = {  # 순서 = 쌓는 순서(아래→위)
    "critical": ("바로 처리", "danger", "#C25450"),
    "action": ("조치 필요", "warn", "#C99A3B"),
    "info": ("참고", "info", "#4A6BAF"),
}
KIND = {
    "step_failed": "단계 실패",
    "questions_failed": "질문 생성 실패",
    "code_finding": "코드 검수 지적",
    "axis_relabel_needed": "축 변경 · 재라벨링",
    "rules_relabel_needed": "규칙 변경 · 재라벨링",
    "engr_questions_open": "도메인 질문 답변",
    "rule_candidate_pending": "규칙 후보 승인",
    "taxonomy_board": "taxonomy 제안 확인",
    "no_workspace": "작업 폴더 없음",
}
WEEKDAY = "월화수목금토일"


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


def load_day(day):
    d = os.path.join(OUT_DIR, day)
    return {"day": day,
            "queue": read_jsonl(os.path.join(d, "morning_queue.jsonl")),
            "steps": read_jsonl(os.path.join(d, "steps.jsonl")),
            "exists": os.path.isdir(d)}


def day_stats(rec):
    q = rec["queue"]
    s = {k: sum(1 for x in q if x["severity"] == k) for k in SEV}
    s["total"] = len(q)
    s["questions"] = sum(x.get("count", 0) for x in q if x["kind"] == "engr_questions_open")
    s["relabel"] = sum(1 for x in q if x["kind"] in ("axis_relabel_needed", "rules_relabel_needed"))
    s["candidates"] = sum(x.get("count", 0) for x in q if x["kind"] == "rule_candidate_pending")
    s["failed"] = sum(1 for x in rec["steps"] if x.get("status") == "failed")
    return s


def fmt_day(day, short=False):
    d = datetime.datetime.strptime(day, "%Y%m%d").date()
    if short:
        return "%d/%d" % (d.month, d.day)
    return "%s (%s)" % (d.isoformat(), WEEKDAY[d.weekday()])


def short_ws(ws):
    """작업 폴더 이름에서 끝의 실행 시각(YYYYMMDD-HHMMSS)만 남긴다."""
    if not ws:
        return ""
    tail = ws.rsplit("_", 1)[-1]
    return tail if len(tail) == 15 and tail[8] == "-" else ws


def delta(today, prev, key):
    if prev is None:
        return ""
    n = today[key] - prev[key]
    if n == 0:
        return '<small class="dl">어제와 같음</small>'
    return '<small class="dl %s">어제 %s%d</small>' % ("up" if n > 0 else "down", "+" if n > 0 else "−", abs(n))


def bar_path(x, y, w, h, r):
    """위쪽 두 모서리만 둥근 막대(바닥에 붙는다)."""
    r = min(r, h, w / 2)
    return ("M%.1f %.1f V%.1f Q%.1f %.1f %.1f %.1f H%.1f Q%.1f %.1f %.1f %.1f V%.1f Z"
            % (x, y + h, y + r, x, y, x + r, y, x + w - r, x + w, y, x + w, y + r, y + h))


def chart_svg(days):
    W, H, PL, PB, PT = 560, 230, 30, 28, 14
    vmax = max([s["total"] for _, s in days if s] + [4])
    vmax = vmax + (-vmax % 2)
    ih, iw = H - PB - PT, W - PL - 10
    slot = iw / len(days)
    bw = min(34, slot * 0.5)
    out = ['<svg viewBox="0 0 %d %d" class="chart" role="img" aria-label="최근 %d일 할 일 건수">' % (W, H, len(days))]
    for i in range(0, vmax + 1, max(1, vmax // 4)):
        y = PT + ih - ih * i / vmax
        out.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" class="gl"/>' % (PL, W - 10, y, y))
        out.append('<text x="%d" y="%.1f" class="ax" text-anchor="end">%d</text>' % (PL - 6, y + 3.5, i))
    for n, (day, s) in enumerate(days):
        cx = PL + slot * n + slot / 2
        x = cx - bw / 2
        out.append('<text x="%.1f" y="%d" class="ax%s" text-anchor="middle">%s</text>'
                   % (cx, H - 8, " today" if n == len(days) - 1 else "", fmt_day(day, True)))
        if s is None:
            out.append('<text x="%.1f" y="%.1f" class="ax" text-anchor="middle">–</text>' % (cx, PT + ih - 4))
            continue
        tip = "%s · 할 일 %d건 · 바로 처리 %d · 조치 필요 %d · 참고 %d" % (
            fmt_day(day), s["total"], s["critical"], s["action"], s["info"])
        out.append('<g class="bar" data-tip="%s">' % html.escape(tip))
        out.append('<rect x="%.1f" y="%d" width="%.1f" height="%d" fill="transparent"/>' % (cx - slot / 2, PT, slot, ih))
        segs = [(k, s[k]) for k in SEV if s[k]]
        y = PT + ih
        for j, (k, v) in enumerate(segs):
            h = ih * v / vmax
            top = j == len(segs) - 1
            seg_h = h - (0 if top else 2)  # 조각 사이 2px 틈
            y -= h
            if top:
                out.append('<path d="%s" fill="%s"/>' % (bar_path(x, y, bw, seg_h, 4), SEV[k][2]))
            else:
                out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s"/>'
                           % (x, y + 2, bw, seg_h, SEV[k][2]))
        if s["total"] and n == len(days) - 1:
            out.append('<text x="%.1f" y="%.1f" class="vl" text-anchor="middle">%d</text>' % (cx, y - 6, s["total"]))
        out.append('</g>')
    out.append('</svg>')
    return "".join(out)


def render(day, history):
    today = history[-1][1]
    rec = load_day(day)
    prev = next((s for d, s in reversed(history[:-1]) if s is not None), None)
    e = html.escape

    tiles = [("total", "할 일", ""), ("critical", "바로 처리", "danger"), ("action", "조치 필요", "warn"),
             ("questions", "답변 대기 질문", ""), ("candidates", "승인 대기 후보", ""), ("relabel", "재라벨링 대상 폴더", "")]
    tile_html = "".join('<div class="tile %s"><b>%d</b><span>%s</span>%s</div>'
                        % (cls, today[k], lab, delta(today, prev, k)) for k, lab, cls in tiles)

    cards = []
    for i, q in enumerate(rec["queue"]):
        lab, cls, _ = SEV.get(q["severity"], SEV["info"])
        ws = short_ws(q.get("workspace"))
        cards.append(
            '<article class="todo sev-%s" data-key="%s:%d">'
            '<header><span class="badge b-%s"><i></i>%s</span><span class="k">%s</span>%s'
            '<label class="chk"><input type="checkbox"> 완료</label></header>'
            '<p>%s</p>'
            '<div class="cmd"><code>%s</code><button type="button" class="cp">복사</button></div>'
            '</article>' % (q["severity"], day, i, cls, lab, e(KIND.get(q["kind"], q["kind"])),
                            '<span class="ws mono">%s</span>' % e(ws) if ws else "",
                            e(q["summary"]), e(q["action"])))
    if not cards:
        cards.append('<p class="empty">오늘은 사람이 처리할 일이 없습니다.</p>')

    rows = "".join('<tr><td>%s</td>%s</tr>' % (
        fmt_day(d, True),
        "".join("<td>%s</td>" % ("–" if s is None else s[k])
                for k in ("total", "critical", "action", "info", "questions", "failed")))
        for d, s in reversed(history))

    steps = rec["steps"]
    ok = sum(1 for s in steps if s.get("status") == "ok")
    failed = [s for s in steps if s.get("status") == "failed"]
    groups = {}  # 작업 폴더마다 도는 단계는 하나로 묶는다(taxonomy_diff ×3)
    for s in steps:
        g = groups.setdefault(s["step"].split(":")[0], [0, 0])
        g[0] += 1
        g[1] += s.get("status") == "failed"
    step_line = " · ".join('<span class="%s">%s %s%s</span>' % (
        "bad" if bad else "", "✕" if bad else "✓", e(name), " ×%d" % n if n > 1 else "")
        for name, (n, bad) in groups.items())
    run_badge = ('<span class="badge b-ok"><i></i>밤 실행 정상 · 단계 %d개</span>' % len(steps) if not failed else
                 '<span class="badge b-danger"><i></i>단계 실패 %d개 / %d</span>' % (len(failed), len(steps)))
    started = steps[0]["started"][11:16] if steps and steps[0].get("started") else "–"
    legend = "".join('<span><i style="background:%s"></i>%s</span>' % (c, lab) for lab, _, c in SEV.values())

    return PAGE.format(
        title="Daily Report " + fmt_day(day, True), day=fmt_day(day), total=today["total"],
        run_badge=run_badge, started=started, ok=ok, n_steps=len(steps), tiles=tile_html,
        cards="".join(cards), chart=chart_svg(history), legend=legend, rows=rows,
        n_days=len(history), step_line=step_line,
        generated=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))


PAGE = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
:root{{
  --primary-deep:#354690; --primary:#4A5FA8; --primary-soft:#6B82C4; --primary-mid:#4A6BAF;
  --bg-base:#EDF1F7; --bg-grid:#C8D4E4; --surface:#FFFFFF; --dot:#A8BDD4; --line:#7A9CC0;
  --text-strong:#1E2D4A; --text-muted:#9DAABF; --text-footer:#B0BCCC; --text-body:rgba(30,45,74,.74);
  --danger:#C25450; --warning:#C99A3B; --success:#3B8A6E;
  --ease-elastic:cubic-bezier(0.34,1.56,0.64,1);
  --grad-main:linear-gradient(148deg,#4A5FA8 0%,#354690 100%);
  --mono:'JetBrains Mono','Fira Code','Cascadia Mono',Consolas,'SF Mono',Menlo,monospace;
}}
*{{box-sizing:border-box;margin:0;padding:0}}
html{{background:var(--bg-base)}}
body{{font-family:'Apple SD Gothic Neo','Pretendard','Noto Sans KR','Inter',sans-serif;color:var(--text-strong);letter-spacing:-0.02em;
  -webkit-font-smoothing:antialiased;background-color:var(--bg-base);
  background-image:linear-gradient(var(--bg-grid) 0.4px,transparent 0.4px),linear-gradient(90deg,var(--bg-grid) 0.4px,transparent 0.4px);
  background-size:48px 48px;word-break:keep-all;overflow-wrap:break-word;font-size:15px}}
button{{font:inherit;letter-spacing:inherit;color:inherit}}
.mono,code{{font-family:var(--mono)}}
.wrap{{max-width:1240px;margin:0 auto;padding:40px 28px 48px}}
.stage{{border:1px solid var(--bg-grid);border-radius:14px;background:rgba(255,255,255,.42);box-shadow:0 2px 8px rgba(53,70,144,.06);padding:36px 40px 28px}}
.eyebrow{{font-family:var(--mono);font-size:12px;color:var(--primary);display:flex;align-items:center;gap:.8em}}
.eyebrow::after{{content:'';width:3em;border-top:1.2px solid var(--line)}}
.h{{font-size:34px;font-weight:700;letter-spacing:-0.055em;line-height:1.24;margin-top:.3em}}
.h em{{font-style:normal;background:var(--grad-main);-webkit-background-clip:text;background-clip:text;color:transparent}}
.sub{{font-size:15px;line-height:1.6;color:var(--text-body);margin-top:.5em}}
.meta{{display:flex;align-items:center;gap:.6em;flex-wrap:wrap;font-size:12.5px;color:var(--text-body);margin-top:.9em}}
.meta .mono{{color:var(--text-muted)}}
.badge{{display:inline-flex;align-items:center;gap:.45em;background:var(--surface);border:1px solid;border-radius:999px;padding:.28em .8em;font-size:11.5px;font-weight:700;white-space:nowrap}}
.badge i{{width:.5em;height:.5em;border-radius:50%;background:currentColor}}
.b-ok{{color:var(--success)}} .b-danger{{color:var(--danger)}} .b-warn{{color:var(--warning)}} .b-info{{color:var(--primary)}}
.tiles{{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin-top:22px}}
.tile{{background:var(--surface);border:1px solid var(--bg-grid);border-radius:10px;padding:12px 8px;text-align:center}}
.tile b{{display:block;font-family:var(--mono);font-size:30px;color:var(--primary-deep);letter-spacing:-0.04em;line-height:1.15}}
.tile span{{font-size:12px;color:var(--text-body);line-height:1.35;display:block}}
.tile.danger b{{color:var(--danger)}} .tile.warn b{{color:var(--warning)}}
.dl{{display:block;margin-top:.3em;font-family:var(--mono);font-size:10.5px;color:var(--text-muted)}}
.dl.up{{color:var(--danger)}} .dl.down{{color:var(--success)}}
.grid{{display:grid;grid-template-columns:1.35fr 1fr;gap:14px;margin-top:18px;align-items:start}}
.grid>*,.todo{{min-width:0}}
.pn{{background:var(--surface);border:1px solid var(--bg-grid);border-radius:12px;padding:16px 18px;display:flex;flex-direction:column;gap:10px;box-shadow:0 2px 8px rgba(53,70,144,.06)}}
.pn h3{{font-size:15px;font-weight:700;letter-spacing:-0.048em}}
.pn h3 small{{font-family:var(--mono);font-weight:400;font-size:11px;color:var(--primary);margin-left:.4em}}
.todo{{border:1px solid var(--bg-grid);border-left:2px solid var(--primary-mid);border-radius:10px;padding:11px 13px;display:flex;flex-direction:column;gap:7px;
  background:var(--surface);transition:transform .28s var(--ease-elastic),border-color .28s,box-shadow .28s,opacity .3s}}
.todo:hover{{transform:translateY(-2px);border-color:var(--primary);box-shadow:0 12px 26px rgba(53,70,144,.16)}}
.todo.sev-critical{{border-left-color:var(--danger)}} .todo.sev-action{{border-left-color:var(--warning)}}
.todo header{{display:flex;align-items:center;gap:.6em;flex-wrap:wrap}}
.todo .k{{font-size:13.5px;font-weight:700;letter-spacing:-0.048em}}
.todo .ws{{font-size:11px;color:var(--text-muted)}}
.todo p{{font-size:13.5px;line-height:1.55;color:var(--text-body)}}
.chk{{margin-left:auto;font-size:12px;color:var(--text-muted);display:flex;align-items:center;gap:.3em;cursor:pointer}}
.chk input{{accent-color:var(--success)}}
.todo.done{{opacity:.45}} .todo.done p{{text-decoration:line-through}}
.cmd{{display:flex;align-items:center;gap:8px;background:var(--bg-base);border:1px solid var(--bg-grid);border-radius:8px;padding:6px 6px 6px 10px}}
.cmd code{{font-size:11.5px;color:var(--primary-deep);flex:1;min-width:0;overflow-x:auto;white-space:nowrap}}
.cp{{flex:none;background:var(--surface);border:1px solid var(--bg-grid);border-radius:999px;padding:.2em .8em;font-size:11.5px;font-weight:700;color:var(--primary);cursor:pointer;transition:all .24s var(--ease-elastic)}}
.cp:hover{{border-color:var(--primary);transform:scale(1.05)}}
.cp.ok{{color:var(--success);border-color:var(--success)}}
.empty{{font-size:14px;color:var(--text-body);padding:12px 0}}
.chart{{width:100%;height:auto;display:block}}
.chart .gl{{stroke:var(--bg-grid);stroke-width:.6}}
.chart .ax{{font-family:var(--mono);font-size:10px;fill:var(--text-muted)}}
.chart .ax.today{{fill:var(--primary);font-weight:700}}
.chart .vl{{font-family:var(--mono);font-size:11px;font-weight:700;fill:var(--text-strong)}}
.chart .bar{{cursor:default}} .chart .bar:hover path,.chart .bar:hover rect[fill^="#"]{{opacity:.85}}
.legend{{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--text-body)}}
.legend i{{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:5px;vertical-align:-1px}}
.tip{{position:fixed;pointer-events:none;background:var(--surface);border:1px solid var(--bg-grid);border-radius:8px;padding:6px 10px;font-size:12px;color:var(--text-strong);
  box-shadow:0 8px 20px rgba(53,70,144,.16);opacity:0;transition:opacity .15s;z-index:9}}
details summary{{font-size:12.5px;color:var(--primary);cursor:pointer;font-weight:700}}
table{{width:100%;border-collapse:collapse;margin-top:8px;font-size:12px}}
th,td{{text-align:right;padding:5px 6px;border-bottom:1px solid var(--bg-grid)}}
th{{color:var(--text-muted);font-weight:400}} th:first-child,td:first-child{{text-align:left}}
td{{font-family:var(--mono);color:var(--text-strong)}}
.foot{{font-size:12px;color:var(--text-body);margin-top:18px;border-top:1px solid var(--bg-grid);padding-top:10px;line-height:1.8}}
.foot .bad{{color:var(--danger);font-weight:700}}
.foot .mono{{color:var(--text-footer)}}
@media (max-width:900px){{.grid{{grid-template-columns:1fr}} .tiles{{grid-template-columns:repeat(3,1fr)}} .stage{{padding:24px 18px}} .wrap{{padding:16px}}}}
</style></head>
<body><div class="wrap"><section class="stage">
<div class="eyebrow">DAILY REPORT · {day}</div>
<h1 class="h">오늘 아침 할 일 <em>{total}건</em></h1>
<p class="sub">밤사이 Code-Engr-bot과 Domain-Engr-bot이 돌고 남긴, 사람 판단이 필요한 일입니다. 위에서부터 처리하세요.</p>
<div class="meta">{run_badge}<span class="mono">시작 {started} · 성공 {ok}/{n_steps}</span></div>
<div class="tiles">{tiles}</div>
<div class="grid">
  <div class="pn"><h3>할 일<small>심각도 순 · 명령 복사 · 완료 체크</small></h3>{cards}</div>
  <div class="pn"><h3>최근 {n_days}일 추이<small>할 일 건수</small></h3>
    <div class="legend">{legend}</div>{chart}
    <details><summary>표로 보기</summary><table>
      <tr><th>날짜</th><th>할 일</th><th>바로 처리</th><th>조치 필요</th><th>참고</th><th>질문 대기</th><th>실패 단계</th></tr>{rows}
    </table></details>
  </div>
</div>
<div class="foot">밤 실행 단계 · {step_line}<br><span class="mono">생성 {generated} · python daily_report.py</span></div>
</section></div>
<div class="tip" id="tip"></div>
<script>
(function(){{
  function get(k){{try{{return localStorage.getItem(k)}}catch(e){{return null}}}}
  function set(k,v){{try{{v?localStorage.setItem(k,'1'):localStorage.removeItem(k)}}catch(e){{}}}}
  document.querySelectorAll('.todo').forEach(function(c){{
    var k='beol-daily:'+c.dataset.key, cb=c.querySelector('input');
    if(get(k)){{cb.checked=true;c.classList.add('done')}}
    cb.addEventListener('change',function(){{c.classList.toggle('done',cb.checked);set(k,cb.checked)}});
    var b=c.querySelector('.cp'), t=c.querySelector('code').textContent;
    b.addEventListener('click',function(){{
      function ok(){{b.textContent='복사됨';b.classList.add('ok');setTimeout(function(){{b.textContent='복사';b.classList.remove('ok')}},1400)}}
      if(navigator.clipboard){{navigator.clipboard.writeText(t).then(ok,function(){{}})}}
      else{{var a=document.createElement('textarea');a.value=t;document.body.appendChild(a);a.select();try{{document.execCommand('copy');ok()}}catch(e){{}}a.remove()}}
    }});
  }});
  var tip=document.getElementById('tip');
  document.querySelectorAll('.chart .bar').forEach(function(g){{
    g.addEventListener('mousemove',function(ev){{tip.textContent=g.dataset.tip;tip.style.opacity=1;
      tip.style.left=Math.min(ev.clientX+14,innerWidth-tip.offsetWidth-8)+'px';tip.style.top=(ev.clientY+14)+'px'}});
    g.addEventListener('mouseleave',function(){{tip.style.opacity=0}});
  }});
}})();
</script>
</body></html>
"""


def main(argv=None):
    p = argparse.ArgumentParser(description="아침 대응 목록 → daily report HTML")
    p.add_argument("--run", action="store_true", help="오늘 결과가 있어도 nightly_run을 다시 돌린다")
    p.add_argument("--days", type=int, default=7, help="추이에 보일 일수(기본 7)")
    p.add_argument("--recent", type=int, default=3, help="nightly_run을 돌릴 때 점검할 최근 작업 폴더 수")
    p.add_argument("--open", action="store_true", help="만든 HTML을 브라우저로 연다")
    args = p.parse_args(argv)
    return trace.run("M18", lambda: _main(args))  # M18 NIGHTLY_REPORT(stderr 줄)


def _main(args):

    day = datetime.date.today().strftime("%Y%m%d")
    if args.run or not os.path.exists(os.path.join(OUT_DIR, day, "morning_queue.jsonl")):
        print("오늘 nightly 결과를 만듭니다(두 봇 실행, 1분 남짓)...")
        steps, queue = nightly_run.nightly(args.recent, False)
        nightly_run.write(steps, queue, day)

    base = datetime.date.today()
    history = []
    for i in range(args.days - 1, -1, -1):
        d = (base - datetime.timedelta(days=i)).strftime("%Y%m%d")
        rec = load_day(d)
        history.append((d, day_stats(rec) if rec["exists"] else None))

    page = render(day, history)
    paths = [os.path.join(OUT_DIR, day, "daily_report.html"), os.path.join(OUT_DIR, "daily_report.html")]
    for path in paths:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(page)
    print("daily report: %s" % os.path.relpath(paths[1], ROOT))
    if args.open:
        url = Path(paths[1]).resolve().as_uri()
        # BEOL_NO_BROWSER=1이거나 디스플레이가 없으면(Windows·macOS가 아니고 DISPLAY·WAYLAND_DISPLAY 없음) 주소만 낸다.
        headless = sys.platform not in ("win32", "darwin") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
        if os.environ.get("BEOL_NO_BROWSER") == "1" or headless:
            print("브라우저로 직접 여세요: %s" % url)
        else:
            webbrowser.open(url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
