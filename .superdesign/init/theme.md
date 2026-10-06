# theme.md

## Part 1 - Token summary (compact)

Hand-written CSS custom properties per template (no shared stylesheet, no Tailwind, no dark mode). Light, blue-gray, "BEOL AX Design System".

### Color tokens (identical in results.html:8-18 and review.html:8-18 unless noted)
| Token | Value | Use |
|---|---|---|
| `--primary-deep` | `#354690` | strong indigo, gradient end, hover bar, `.ans.O` text |
| `--primary` | `#4A5FA8` | main indigo, active chip/opt, focus ring, value bars |
| `--primary-soft` | `#6B82C4` | soft indigo, group border, dashed boxes |
| `--primary-mid` | `#4A6BAF` | review.html only (declared) |
| `--bg-base` | `#EDF1F7` | page background, input bg in review |
| `--bg-grid` | `#C8D4E4` | borders and 48px grid lines |
| `--surface` | `#F6F8FC` | cards, buttons, KPI |
| `--surface-2` | `#E4EAF3` | row dividers, th bg (review), donut track |
| `--dot` / `--line` | `#A8BDD4` / `#7A9CC0` | review.html only; slide preview placeholders/borders |
| `--text-strong` | `#1E2D4A` | text, tooltip/toast bg |
| `--text-muted` | `#6F7F99` | secondary text |
| `--text-footer` | `#B0BCCC` | footer, empty |
| `--danger` | `#C25450` | flagged, hard tags, danger bars |
| `--warning` | `#C99A3B` | soft tags, quote highlight, revisit |
| `--success` | `#3B8A6E` | ok marks |
| `--s-value` / `--s-unknown` / `--s-none` | `#4A5FA8` / `#eb6834` / `#C9D2DF` | results.html only: stacked-bar states (value, unknown, N/A) |
Other literals in use: `#A9441A` (X answer text), `#8a6718` / `#A97C1F` (warning text), `#FBF6EC` (alert bg), `#FBFCFE` (slide bg), `#fff`, `#EDF1F7` text on indigo, `#e5484d` (flag dot), `#b42318` (control O).
Primary button gradient: `linear-gradient(148deg,#4A5FA8 0%,#354690 100%)`.

### Typography
- `--font`: `'Apple SD Gothic Neo','Noto Sans KR','Inter',sans-serif`; `--mono`: `'JetBrains Mono','Fira Code',Consolas,monospace`.
- Body: 13.5px / 1.55, `letter-spacing:-0.02em`. Headings letter-spacing `-0.03em`...`-0.055em`. Weights: 400 and 700 (results.html also uses 500/600/800 in `.bk`).
- Sizes in use, results.html: 10, 10.5, 11, 11.5, 12, 12.5, 13, 13.5, 15, 16, 18, 20 (h1 slim), 24 (h1), 26, 28, 56 (big KPI value).
- Sizes in use, review.html: 9.5, 10, 10.5, 11, 11.5, 12, 12.5, 13, 13.5, 14, 16, 18 (bar h1), 20 (detail h2), 22 (empty state).

### Radius / shadow / motion
- `--radius-sm:8px`, `--radius:12px`; also 999px (pills), 6px, 5px, 4px, 3px, 50% (donut).
- Shadows (review only): card `0 2px 8px rgba(53,70,144,.06)`; item active `0 5px 16px rgba(53,70,144,.14)`; btn hover `0 6px 16px rgba(53,70,144,.14)`. results.html uses none.
- `--ease-elastic: cubic-bezier(0.34,1.56,0.64,1)`; transitions `.28s` (chip/item/btn/opt), `.32s` (toast). `prefers-reduced-motion` disables transitions (review).
- Background: `--bg-base` + 48px x 48px grid (results: `linear-gradient(var(--bg-grid) 1px,transparent 1px)` x2 with `background-position:-1px -1px`; review: `rgba(200,212,228,.5) 0.5px` lines).

### Layout constants and breakpoints
- results: `.wrap` max-width 1280px, padding 28px 24px 64px; `.big-kpis` columns `1fr 1fr 1.6fr`; `.big-grid` `repeat(auto-fit,minmax(460px,1fr))`; `.grid` `minmax(290px,1fr)`; kpis `minmax(200px,1fr)`.
- review: `.cols` `344px 1fr`; `.two` `minmax(0,1fr) minmax(0,1.1fr)`; `.detail` padding 18px 24px 60px; dialog `min(640px,92vw)`.
- Breakpoints: results `@media (max-width:760px)` (detail grid 1 col, stack-row 90/1fr/48), `@media (max-width:900px)` (big-kpis 1 col, big bar-row 120/1fr/90); review `@media (max-width:1180px)` (`.two` 1 col), `@media (max-width:860px)` (cols 1 col, app height auto, items max-height 260px), `@media (prefers-reduced-motion:reduce)`.

### Project design system (`design.md.md` at repo root, "BEOL AX - Unified Design System & Figure Guide")
Concept "Calm Canvas, Vivid Details": quiet blue-gray canvas, precise interactions. Tokens above are its tokens (`--primary-deep/primary/primary-soft/primary-mid`, `--bg-base #EDF1F7`, `--bg-grid #C8D4E4` 48px grid, semantic danger/warning/success used only on small areas: dots/badges/lines).
Rules: card gradient angle always `148deg` (main `#4A5FA8->#354690`, secondary `#6B82C4->#4A6BAF`); pure white page backgrounds are forbidden; negative letter-spacing everywhere (logo/header `-0.055em`, card titles `-0.048em`, body `-0.02em`, captions `-0.015..-0.02em`); only font-weight 400 and 700 (avoid 500/600);
all hover/transition animations use `cubic-bezier(0.34,1.56,0.64,1)` for 0.24-0.32s; card radius 8px (`--radius-sm`), card shadow `0 2px 8px rgba(53,70,144,.06)`, hover shadow `0 8px 20px rgba(53,70,144,.16)`; no external CDN at runtime (offline/intranet).

## Part 2 - Raw CSS

### results.html `:root` block

`labelbot/screens/results.html:8-18`
```css
:root{
  --primary-deep:#354690; --primary:#4A5FA8; --primary-soft:#6B82C4;
  --bg-base:#EDF1F7; --bg-grid:#C8D4E4; --surface:#F6F8FC; --surface-2:#E4EAF3;
  --text-strong:#1E2D4A; --text-muted:#6F7F99; --text-footer:#B0BCCC;
  --danger:#C25450; --warning:#C99A3B; --success:#3B8A6E;
  --s-value:#4A5FA8; --s-unknown:#eb6834; --s-none:#C9D2DF;
  --radius-sm:8px; --radius:12px;
  --ease-elastic:cubic-bezier(0.34,1.56,0.64,1);
  --font:'Apple SD Gothic Neo','Noto Sans KR','Inter',sans-serif;
  --mono:'JetBrains Mono','Fira Code',Consolas,monospace;
}
```

### review.html `:root` block

`labelbot/screens/review.html:8-18`
```css
:root{
  --primary-deep:#354690; --primary:#4A5FA8; --primary-soft:#6B82C4; --primary-mid:#4A6BAF;
  --bg-base:#EDF1F7; --bg-grid:#C8D4E4; --surface:#F6F8FC; --surface-2:#E4EAF3;
  --dot:#A8BDD4; --line:#7A9CC0;
  --text-strong:#1E2D4A; --text-muted:#6F7F99; --text-footer:#B0BCCC;
  --danger:#C25450; --warning:#C99A3B; --success:#3B8A6E;
  --radius-sm:8px; --radius:12px;
  --ease-elastic:cubic-bezier(0.34,1.56,0.64,1);
  --font:'Apple SD Gothic Neo','Noto Sans KR','Inter',sans-serif;
  --mono:'JetBrains Mono','Fira Code',Consolas,monospace;
}
```

### results.html full `<style>` block (lines 7-136)

`labelbot/screens/results.html:7-136`
```html
<style>
:root{
  --primary-deep:#354690; --primary:#4A5FA8; --primary-soft:#6B82C4;
  --bg-base:#EDF1F7; --bg-grid:#C8D4E4; --surface:#F6F8FC; --surface-2:#E4EAF3;
  --text-strong:#1E2D4A; --text-muted:#6F7F99; --text-footer:#B0BCCC;
  --danger:#C25450; --warning:#C99A3B; --success:#3B8A6E;
  --s-value:#4A5FA8; --s-unknown:#eb6834; --s-none:#C9D2DF;
  --radius-sm:8px; --radius:12px;
  --ease-elastic:cubic-bezier(0.34,1.56,0.64,1);
  --font:'Apple SD Gothic Neo','Noto Sans KR','Inter',sans-serif;
  --mono:'JetBrains Mono','Fira Code',Consolas,monospace;
}
*{box-sizing:border-box}
html,body{margin:0}
body{
  background-color:var(--bg-base);
  background-image:linear-gradient(var(--bg-grid) 1px,transparent 1px),linear-gradient(90deg,var(--bg-grid) 1px,transparent 1px);
  background-size:48px 48px;background-position:-1px -1px;
  font-family:var(--font);font-size:13.5px;line-height:1.55;letter-spacing:-0.02em;color:var(--text-strong);
}
.mono{font-family:var(--mono);letter-spacing:-0.01em}
.wrap{max-width:1280px;margin:0 auto;padding:28px 24px 64px}
header{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:20px}
h1{font-size:24px;font-weight:700;letter-spacing:-0.04em;margin:0}
.sub{color:var(--text-muted);font-size:12px}
h2{font-size:15px;font-weight:700;letter-spacing:-0.03em;margin:0 0 4px}
.desc{color:var(--text-muted);font-size:12px;margin:0 0 14px}
.card{background:var(--surface);border:1px solid var(--bg-grid);border-radius:var(--radius);padding:18px 20px;margin-bottom:16px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:16px}
.kpi{background:var(--surface);border:1px solid var(--bg-grid);border-radius:var(--radius);padding:14px 16px}
.kpi .k{color:var(--text-muted);font-size:12px}
.kpi .v{font-size:28px;font-weight:700;letter-spacing:-0.04em;line-height:1.2}
.kpi .v small{font-size:13px;font-weight:400;color:var(--text-muted);margin-left:4px}
.kpi .note{font-size:11.5px;color:var(--text-muted)}
.kpi.hero{display:flex;gap:14px;align-items:center;border-left:4px solid var(--c)}
.donut{--p:0;width:64px;height:64px;flex:0 0 64px;border-radius:50%;background:conic-gradient(var(--c) calc(var(--p)*1%),var(--surface-2) 0);display:grid;place-items:center}
.donut::before{content:"";grid-area:1/1;width:46px;height:46px;border-radius:50%;background:var(--surface)}
.donut b{grid-area:1/1;z-index:1;font-size:12px;font-family:var(--mono);letter-spacing:-0.03em}
.alert{display:flex;gap:8px;align-items:flex-start;border-left:3px solid var(--warning);background:#FBF6EC;border-radius:var(--radius-sm);padding:8px 12px;margin-top:8px;font-size:12.5px}
.alert b{font-weight:700}
.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:12px;color:var(--text-muted);margin-bottom:10px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px}
.stack-row{display:grid;grid-template-columns:120px 1fr 64px;gap:12px;align-items:center;padding:5px 0}
.stack-row .lbl{font-size:12.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.stack-row .tot{font-size:11.5px;color:var(--text-muted);text-align:right}
.stack{display:flex;gap:2px;height:18px}
.seg{height:100%;min-width:2px;position:relative;cursor:default}
.seg:first-child{border-radius:4px 0 0 4px}.seg:last-child{border-radius:0 4px 4px 0}.seg:only-child{border-radius:4px}
.seg span{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:10.5px;font-family:var(--mono);color:#fff}
.seg.none span{color:var(--text-strong)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:12px}
.mini{border:1px solid var(--surface-2);border-radius:var(--radius-sm);padding:12px 14px;background:#fff}
.mini h3{font-size:13px;font-weight:700;margin:0 0 8px;display:flex;justify-content:space-between}
.mini h3 .sub{font-weight:400}
.bar-row{display:grid;grid-template-columns:110px 1fr 30px;gap:8px;align-items:center;padding:2px 0;cursor:default}
.bar-row .lbl{font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bar-row .n{font-family:var(--mono);font-size:11px;color:var(--text-muted);text-align:right}
.track{height:10px}
.bar{height:100%;background:var(--s-value);border-radius:0 4px 4px 0;min-width:2px}
.bar-row:hover .bar{background:var(--primary-deep)}
.empty{color:var(--text-footer);font-size:12px}
.filters{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
select,input[type=search]{font-family:var(--font);font-size:12.5px;border:1px solid var(--bg-grid);border-radius:var(--radius-sm);padding:6px 10px;background:#fff;color:var(--text-strong)}
label.chk{font-size:12.5px;display:flex;gap:6px;align-items:center}
.count{color:var(--text-muted);font-size:12px;margin-left:auto}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{text-align:left;font-weight:700;color:var(--text-muted);font-size:11.5px;border-bottom:1px solid var(--bg-grid);padding:8px 6px;position:sticky;top:0;background:var(--surface)}
td{border-bottom:1px solid var(--surface-2);padding:8px 6px;vertical-align:top}
tr.row{cursor:pointer;transition:background .15s}
tr.row:hover{background:#fff}
tr.row.open{background:#fff}
.chip{display:inline-block;border:1px solid var(--bg-grid);border-radius:999px;padding:0 8px;margin:1px 3px 1px 0;font-size:11px;background:#fff;white-space:nowrap}
.chip .ax{color:var(--text-muted);margin-right:3px}
.chip.unk{border-color:var(--s-unknown);color:#A9441A}
.ans{font-family:var(--mono);font-weight:700;font-size:11.5px;border-radius:6px;padding:0 7px;border:1px solid}
.ans.O{color:var(--primary-deep);border-color:var(--s-value);background:rgba(74,95,168,.10)}
.ans.X{color:#A9441A;border-color:var(--s-unknown);background:rgba(235,104,52,.10)}
.ans.NA{color:var(--text-muted);border-color:var(--bg-grid)}
.flag{display:inline-block;font-family:var(--mono);font-size:10px;border-radius:5px;padding:0 5px;margin:1px 2px 1px 0;border:1px solid var(--danger);color:var(--danger)}
.ok{color:var(--success);font-size:11.5px}
.detail td{background:#fff;padding:14px 16px}
.det{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,1fr);gap:18px}
.det pre{white-space:pre-wrap;word-break:break-word;font-family:var(--font);font-size:12.5px;background:var(--surface);border:1px solid var(--surface-2);border-radius:var(--radius-sm);padding:10px 12px;margin:0;max-height:420px;overflow:auto}
.det mark{background:rgba(74,95,168,.18);color:inherit;border-radius:3px;padding:0 1px}
.ev{border-bottom:1px solid var(--surface-2);padding:6px 0;font-size:12px}
.ev .h{display:flex;justify-content:space-between;gap:8px}
.ev .q{color:var(--text-muted);margin-top:2px}
.conf{font-family:var(--mono);font-size:11px;color:var(--text-muted)}
.tip{position:fixed;pointer-events:none;background:var(--text-strong);color:#fff;font-size:11.5px;padding:6px 9px;border-radius:6px;z-index:10;display:none;max-width:280px}
.tbl-wrap{max-height:720px;overflow:auto;border:1px solid var(--surface-2);border-radius:var(--radius-sm)}
footer{color:var(--text-footer);font-size:11px;margin-top:20px}
@media (max-width:760px){.det{grid-template-columns:1fr}.stack-row{grid-template-columns:90px 1fr 48px}}

/* 핵심 지표 확대 레이아웃 */
header.slim{display:flex;align-items:baseline;gap:12px;margin-bottom:14px}
header.slim h1{font-size:20px;margin:0}
.big-kpis{display:grid;grid-template-columns:1fr 1fr 1.6fr;gap:16px;margin-bottom:12px}
.bk{background:var(--surface);border:1px solid var(--bg-grid);border-radius:var(--radius);padding:22px 26px}
.bk .k{font-size:15px;color:var(--text-muted);font-weight:600}
.bk .v{font-size:56px;font-weight:800;letter-spacing:-0.04em;line-height:1.1}
.bk .v small{font-size:20px;font-weight:500;color:var(--text-muted);margin-left:6px}
.bk .v2{font-size:26px;font-weight:700;color:var(--danger)}
.bk .note.warn{color:var(--danger);font-size:13px;margin-top:4px}
.bk.hero{display:flex;gap:24px;align-items:center;border-left:6px solid var(--danger)}
.bk.hero .donut{width:120px;height:120px}
.bk.hero .donut b{font-size:18px}
.alert-line{font-size:13px;color:var(--text-muted);margin:0 0 14px;padding:6px 10px;border-radius:8px;background:var(--surface)}
.big-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(460px,1fr));gap:16px;margin-bottom:16px}
.card.big{margin:0 0 16px;padding:22px 26px}
.big-grid .card.big{margin:0}
.card.big h2{font-size:18px;margin-bottom:12px}
.card.big .legend{font-size:13px;margin-bottom:10px}
.card.big .bar-row{grid-template-columns:200px 1fr 110px;font-size:15px;margin:10px 0}
.card.big .bar-row .track{height:22px}
.card.big .bar-row .bar{height:100%}
.card.big .bar.danger{background:var(--danger)}
.card.big .bar-row .n{font-weight:700;font-size:16px}
.card.big .bar-row .n small{font-weight:400;color:var(--text-muted);font-size:13px}
.card.big .stack-row{font-size:15px}
.card.big .stack{height:28px}
.qrow,.axrow{margin:4px 0 14px}
.qn{font-size:16px;font-weight:700;margin-bottom:2px}
.qn .mono{font-size:11px;font-weight:400;color:var(--text-muted);margin-left:8px}
.qrow .stack-row .lbl{display:none}
.qrow .stack-row{grid-template-columns:1fr 50px}
.qp{font-size:13px;color:var(--text-muted);margin-top:2px}
details.fold{margin:0 0 12px}
details.fold>summary{cursor:pointer;font-size:13px;color:var(--text-muted);padding:6px 2px}
@media (max-width:900px){.big-kpis{grid-template-columns:1fr}.card.big .bar-row{grid-template-columns:120px 1fr 90px}}
</style>
```
