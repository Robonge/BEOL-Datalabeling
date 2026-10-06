# components.md - shared UI primitives

There is no component library, framework or build step. Every screen is a single-file vanilla HTML/CSS/JS template in `labelbot/screens/`.
"Components" are CSS classes plus tiny DOM/HTML-string helper functions copied into each template. `results.html` and `review.html` each define
their own copy of `.card`, `.chip`, `.ans`, `.legend`, `table` etc. with slightly different rules (both listed below). All colors are `var(--token)` (see theme.md).
Python fills the `DATA` JSON; nothing is imported at runtime. Never reference external URLs (screens are local files).

## A. results.html primitives (CSS, verbatim)

Tokens/base (`:root`, body, `.mono`, `.wrap`, headings) are in theme.md Part 2 and layouts.md. Primitive rules:

### card, kpi, donut, alert, legend, stack/seg bars, mini grid, bar-row, filters, table, chip, ans, flag, detail, tip

`labelbot/screens/results.html:34-98`
```css
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
```

### Big-KPI / big-card variants (`.bk`, `.bk.hero`, `.card.big`, `.qrow`, `.axrow`, `details.fold`)

`labelbot/screens/results.html:100-135`
```css
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
```

## B. results.html JS render helpers (verbatim)

Helpers return HTML strings (template literals) that are concatenated into `html` and assigned with `app.innerHTML`. `esc()` must wrap all data.
`stack(label, parts, total)` = stacked bar row (`.stack-row > .lbl + .stack > .seg* + .tot`); `donut(ratio, label)` = conic-gradient ring driven by `--p` and `--c`.
Bar-row (`.bar-row > .lbl + .track > .bar + .n`) and KPI (`.bk`) markup are inline in the main script (see layouts.md lines 170-216 equivalents).

`labelbot/screens/results.html:146-164`
```js
  const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  const pct = (n, d) => d ? (100 * n / d).toFixed(1) + '%' : '-';
  const donut = (ratio, label) => { const t = ratio == null ? '-' : (ratio * 100).toFixed(1) + '%';
    return `<div class="donut" style="--p:${ratio == null ? 0 : (ratio * 100).toFixed(1)}" role="img" aria-label="${esc(label)} ${t}"><b>${t}</b></div>`; };
  if (!DATA) { app.innerHTML = '<div class="card"><h2>표시할 결과가 없습니다</h2><p class="desc">python -m labelbot dashboard 로 생성하세요.</p></div>'; return; }

  function bindTips(root){
    root.querySelectorAll('[data-tip]').forEach(el => {
      el.addEventListener('mousemove', e => { tip.textContent = el.dataset.tip; tip.style.display = 'block';
        tip.style.left = Math.min(e.clientX + 12, innerWidth - 300) + 'px'; tip.style.top = (e.clientY + 14) + 'px'; });
      el.addEventListener('mouseleave', () => { tip.style.display = 'none'; });
    });
  }

  function stack(label, parts, total){
    const segs = parts.filter(p => p.n > 0).map(p =>
      `<div class="seg ${p.cls}" style="flex:${p.n};background:var(${p.color})" data-tip="${esc(label)} · ${esc(p.name)} ${p.n}건 (${pct(p.n,total)})"><span>${p.n / total >= 0.08 ? p.n : ''}</span></div>`).join('');
    return `<div class="stack-row"><div class="lbl" title="${esc(label)}">${esc(label)}</div><div class="stack">${segs || '<div class="empty">없음</div>'}</div><div class="tot mono">${total}</div></div>`;
  }
```

Chip/answer/flag/detail helpers (used by the chunk table):

`labelbot/screens/results.html:236-262`
```js
  function chips(c){
    const out = [];
    axesActive.forEach(a => { const v = c.axes[a.name]; if (!v) return;
      if (v.status === 'unknown') out.push(`<span class="chip unk"><span class="ax">${esc(a.name)}</span>unknown</span>`);
      else if (v.status === 'value') v.values.forEach(x => out.push(`<span class="chip"><span class="ax">${esc(a.name)}</span>${esc(x)}</span>`)); });
    return out.join('') || '<span class="empty">값 없음</span>';
  }
  function highlight(text, quotes){
    let t = esc(text);
    quotes.filter(q => q && q.length >= 6).forEach(q => {
      q.split(/\s*(?:…|\.{3,})\s*|\n/).filter(p => p.trim().length >= 6).forEach(p => {
        const e = esc(p.trim()); const i = t.indexOf(e);
        if (i >= 0) t = t.slice(0, i) + '<mark>' + e + '</mark>' + t.slice(i + e.length);
      });
    });
    return t;
  }
  function detail(c){
    const evid = axesActive.map(a => { const v = c.axes[a.name]; if (!v || v.status === 'na') return '';
      return `<div class="ev"><div class="h"><b>${esc(a.name)}: ${esc(v.values.join(', '))}</b><span class="conf">확신도 ${v.confidence == null ? '-' : v.confidence.toFixed(2)}</span></div>${v.evidence ? `<div class="q">“${esc(v.evidence)}”</div>` : ''}</div>`; }).join('');
    const ans = Object.keys(c.answers).map(q => { const a = c.answers[q];
      return `<div class="ev"><div class="h"><b>${esc(q)}: <span class="ans ${a.answer === 'N/A' ? 'NA' : a.answer}">${esc(a.answer)}</span></b><span class="conf">확신도 ${a.confidence == null ? '-' : a.confidence.toFixed(2)}</span></div>${a.quote ? `<div class="q">“${esc(a.quote)}”</div>` : ''}</div>`; }).join('');
    const ext = c.extracted.length ? '<div class="ev"><b>추출 값</b>' + c.extracted.map(e => `<div class="q">${esc(e.item)}: ${esc(e.value)}</div>`).join('') + '</div>' : '';
    const quotes = Object.values(c.axes).filter(v => v.status === 'value').map(v => v.evidence).concat(Object.values(c.answers).map(a => a.quote));
    return `<tr class="detail"><td colspan="5"><div class="det"><div><h2 style="font-size:13px">본문</h2><pre>${highlight(c.text, quotes)}</pre></div>
      <div><h2 style="font-size:13px">분류 근거</h2>${evid || '<div class="empty">값이 붙은 축이 없다</div>'}<h2 style="font-size:13px;margin-top:12px">질문 답</h2>${ans || '<div class="empty">답 없음</div>'}${ext}</div></div></td></tr>`;
  }
```

## C. review.html primitives (CSS, verbatim)

Chips and list items (`.chips/.chip`, `.item`, `.tags/.tag`, `.mark`):

`labelbot/screens/review.html:47-54`
```css
.chips{display:flex;gap:5px;flex-wrap:wrap}
.chip{
  border:1px solid var(--bg-grid);background:transparent;border-radius:999px;padding:2px 10px;font-size:11.5px;cursor:pointer;
  transition:all .28s var(--ease-elastic);white-space:nowrap;
}
.chip:hover{transform:translateY(-1px);border-color:var(--primary)}
.chip.on{background:var(--primary);border-color:var(--primary);color:#EDF1F7}
.chip .n{font-family:var(--mono);margin-left:5px;opacity:.75}
```

`labelbot/screens/review.html:58-75`
```css
.item{
  display:block;width:100%;text-align:left;border:1px solid transparent;background:var(--surface);border-radius:var(--radius-sm);
  padding:8px 10px;margin:4px 0;cursor:pointer;transition:all .28s var(--ease-elastic);
}
.item:hover{transform:translateX(2px);border-color:var(--bg-grid)}
.item.on{border-color:var(--primary);box-shadow:0 5px 16px rgba(53,70,144,.14)}
.item .l1{display:flex;gap:8px;align-items:center;font-size:11px;color:var(--text-muted)}
.item .l1 .id{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.item .l2{font-weight:700;font-size:13px;margin:2px 0 4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tags{display:flex;gap:4px;flex-wrap:wrap}
.tag{font-family:var(--mono);font-size:9.5px;letter-spacing:-0.01em;border:1px solid var(--bg-grid);border-radius:5px;padding:0 5px;color:var(--text-muted)}
.tag.hard{border-color:var(--danger);color:var(--danger)}
.tag.soft{border-color:var(--warning);color:#A97C1F}
.mark{font-size:10.5px;font-weight:700;border-radius:999px;padding:0 7px;border:1px solid}
.mark.ok{color:var(--success);border-color:var(--success)}
.mark.img{color:var(--primary);border-color:var(--primary)}
.mark.fix{color:var(--primary-deep);border-color:var(--primary-soft);background:rgba(107,130,196,.14)}
.mark.rv{color:#8a6718;border-color:var(--warning);background:rgba(201,154,59,.1)}
```

Buttons (`.btn`, `.btn.primary`, `.btn.sm`, `.btn.on-ok`, `.btn.on-img`) and focus ring:

`labelbot/screens/review.html:85-94`
```css
.btn{
  border:1px solid var(--bg-grid);background:var(--surface);border-radius:var(--radius-sm);padding:6px 12px;cursor:pointer;font-weight:700;font-size:12.5px;
  transition:all .28s var(--ease-elastic);
}
.btn:hover{transform:translateY(-2px);border-color:var(--primary);box-shadow:0 6px 16px rgba(53,70,144,.14)}
.btn:focus-visible,.chip:focus-visible,.item:focus-visible,.opt:focus-visible,textarea:focus-visible,select:focus-visible,input:focus-visible{outline:2px solid var(--primary);outline-offset:2px}
.btn.primary{background:linear-gradient(148deg,#4A5FA8 0%,#354690 100%);color:#EDF1F7;border-color:var(--primary-deep)}
.btn.sm{padding:3px 9px;font-size:11.5px}
.btn.on-ok{border-color:var(--success);color:var(--success);background:rgba(59,138,110,.1)}
.btn.on-img{border-color:var(--primary);color:var(--primary-deep);background:rgba(74,95,168,.12)}
```

Cards, section label, body text, `mark.q` (quote highlight) / `mark.s` (synonym), legend, image strip, slide header:

`labelbot/screens/review.html:97-113`
```css
.card{background:var(--surface);border:1px solid var(--bg-grid);border-radius:var(--radius);padding:13px 15px;margin-bottom:14px;box-shadow:0 2px 8px rgba(53,70,144,.06)}
.card h3{font-size:14px;letter-spacing:-0.048em;margin-bottom:8px;display:flex;align-items:center;gap:8px}
.sec{font-size:11px;color:var(--text-muted);margin:0 0 6px}
.text{white-space:pre-wrap;word-break:break-word;line-height:1.7;max-height:420px;overflow:auto;padding-right:4px}
mark{background:none;color:inherit;border-radius:3px;padding:0 1px}
mark.q{background:rgba(201,154,59,.28);box-shadow:inset 0 -2px 0 var(--warning)}
mark.s{background:rgba(74,95,168,.16);box-shadow:inset 0 -2px 0 var(--primary);cursor:help}
.legend{display:flex;gap:12px;font-size:11px;color:var(--text-muted);margin-top:8px}
.legend mark{padding:0 6px}
.imgs{display:flex;gap:8px;flex-wrap:wrap}
.imgs img{height:92px;max-width:170px;object-fit:contain;border:1px solid var(--bg-grid);border-radius:var(--radius-sm);background:var(--bg-base);cursor:zoom-in;transition:transform .28s var(--ease-elastic)}
.imgs img:hover{transform:scale(1.04)}
.slide-h{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px}
.slide-h h3{margin:0}
/*__SLIDE_PREVIEW_CSS__*/
.slide.big{width:min(94vw,150vh);max-height:92vh;cursor:zoom-out}
.slide-note{font-size:11px;color:var(--text-muted);margin-top:6px}
```

Axis editor card primitives (`.axis`, `.badge`, `.v` value chip, `.ev` evidence quote, `.conf`, `.defs`, `.edit`, `.opt` toggle button, `.changed`, `.qhead`, `.ans`, `.note`, table, empty state):

`labelbot/screens/review.html:151-189`
```css
.axis{padding:10px 0;border-top:1px dashed var(--bg-grid)}
.axis:first-of-type{border-top:0;padding-top:0}
.axhead{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
.axhead b{font-size:13.5px}
.badge{font-size:10px;border:1px solid var(--bg-grid);border-radius:5px;padding:0 5px;color:var(--text-muted)}
.axdef{font-size:11.5px;color:var(--text-muted);margin:1px 0 6px}
.botline{display:flex;gap:6px;align-items:center;flex-wrap:wrap;font-size:12px;margin-bottom:3px}
.botline .k{color:var(--text-muted);font-size:11px}
.v{display:inline-block;font-size:12px;border-radius:6px;padding:0 8px;border:1px solid var(--primary);background:rgba(74,95,168,.12);color:var(--primary-deep);cursor:help}
.v.na{border-color:var(--line);background:transparent;color:var(--text-muted)}
.v.unk{border:1px dashed var(--warning);background:rgba(201,154,59,.1);color:#8a6718}
.ev{font-size:12px;color:var(--text-strong);border-left:2px solid var(--warning);padding-left:8px;margin:3px 0;word-break:break-word}
.conf{font-family:var(--mono);font-size:11px}
.defs{margin:4px 0 6px;font-size:11.5px}
.defs summary{cursor:pointer;color:var(--primary)}
.defs dl{margin:6px 0 0;display:grid;grid-template-columns:auto 1fr;gap:3px 10px}
.defs dt{font-weight:700}
.defs dd{margin:0;color:var(--text-muted)}
.defs dt.botv{color:var(--primary-deep)}
.edit{display:flex;gap:5px;flex-wrap:wrap;margin-top:6px;align-items:center}
.edit .k{font-size:11px;color:var(--text-muted);margin-right:2px}
.opt{
  border:1px solid var(--bg-grid);background:transparent;border-radius:var(--radius-sm);padding:2px 10px;cursor:pointer;font-size:12px;
  transition:all .28s var(--ease-elastic);
}
.opt:hover{transform:translateY(-1px);border-color:var(--primary)}
.opt[aria-pressed="true"]{background:var(--primary);border-color:var(--primary);color:#EDF1F7;font-weight:700}
.opt.sp{border-style:dashed}
.opt.sp[aria-pressed="true"]{background:var(--text-strong);border-color:var(--text-strong)}
.changed{font-size:10.5px;color:var(--primary-deep);font-weight:700;border:1px solid var(--primary-soft);background:rgba(107,130,196,.14);border-radius:999px;padding:0 7px}
.qhead{display:flex;gap:8px;align-items:baseline}
.qhead .qid{font-size:11px;color:var(--primary)}
.ans{font-family:var(--mono);font-size:12px;font-weight:700;border:1px solid var(--primary);border-radius:6px;padding:0 8px;background:rgba(74,95,168,.12);color:var(--primary-deep)}
.note{font-size:12px;color:var(--text-muted);border:1px dashed var(--bg-grid);border-radius:var(--radius-sm);padding:5px 9px;margin-bottom:8px}
table{border-collapse:collapse;width:100%;font-size:12px}
th,td{border:1px solid var(--bg-grid);padding:4px 8px;text-align:left;vertical-align:top;word-break:break-word}
th{background:var(--surface-2);font-weight:700}
.emptystate{max-width:520px;margin:14vh auto;text-align:center;color:var(--text-muted)}
.emptystate h2{color:var(--text-strong);font-size:22px;letter-spacing:-0.055em;margin-bottom:8px}
```

Dialog, zoom overlay, sibling-slide strip (`.sibs/.sib`), toast:

`labelbot/screens/review.html:191-209`
```css
dialog{border:1px solid var(--bg-grid);border-radius:var(--radius);background:var(--surface);color:var(--text-strong);width:min(640px,92vw);padding:18px}
dialog::backdrop{background:rgba(30,45,74,.35)}
dialog textarea{width:100%;height:240px;border:1px solid var(--bg-grid);border-radius:var(--radius-sm);padding:10px;font-family:var(--mono);font-size:12px;background:var(--bg-base);letter-spacing:-0.01em}
dialog h3{margin-bottom:6px;font-size:16px}
dialog p{margin:0 0 10px;font-size:12.5px;color:var(--text-muted)}
.zoom{position:fixed;inset:0;background:rgba(30,45,74,.7);display:none;align-items:center;justify-content:center;z-index:50;cursor:zoom-out}
.zoom.on{display:flex}
.zoom img{max-width:92vw;max-height:92vh;border-radius:var(--radius-sm);background:var(--bg-base)}
.zoom .zcap{position:fixed;bottom:14px;left:50%;transform:translateX(-50%);color:#fff;font-size:12px;background:rgba(0,0,0,.45);padding:3px 10px;border-radius:var(--radius-sm)}
.sibs{display:flex;gap:8px;overflow-x:auto;padding-bottom:4px}
.sib-view{display:block;width:100%;max-height:360px;object-fit:contain;border:1px solid var(--bg-grid);border-radius:var(--radius-sm);background:var(--bg-base);cursor:zoom-in}
.sib-cap{font-size:11.5px;color:var(--text-muted);margin:4px 0 8px}
.sib{flex:0 0 auto;position:relative;padding:0;border:2px solid var(--bg-grid);border-radius:var(--radius-sm);background:var(--bg-base);cursor:pointer}
.sib img{display:block;height:72px;border-radius:var(--radius-sm)}
.sib.cur{border-color:var(--primary)}
.sib .no{position:absolute;left:3px;bottom:3px;font-size:10px;color:#fff;background:rgba(0,0,0,.55);padding:0 4px;border-radius:3px}
.sib .fl{position:absolute;right:3px;top:3px;width:8px;height:8px;border-radius:50%;background:#e5484d}
.toast{position:fixed;right:20px;bottom:20px;background:var(--text-strong);color:#EDF1F7;padding:8px 14px;border-radius:var(--radius-sm);font-size:12.5px;opacity:0;transform:translateY(8px);transition:all .32s var(--ease-elastic);pointer-events:none;z-index:60}
.toast.on{opacity:1;transform:none}
```

Feature-specific boxes not repeated here (synonym `.syn`, revisit `.rvbox`, evidence `.evbox`, context `.ctxs`): `labelbot/screens/review.html:114-149`.

## D. review.html JS helpers (verbatim)

`h(tag, attrs, kids)` is the DOM builder used everywhere in review.html (`class`->className, `text`->textContent, `onXxx`->addEventListener, falsy attrs skipped, null kids skipped, string kids -> text nodes).

`labelbot/screens/review.html:244-259`
```js
  function h(tag, attrs, kids){
    var e = document.createElement(tag);
    if (attrs) for (var k in attrs){
      if (k === "class") e.className = attrs[k];
      else if (k === "text") e.textContent = attrs[k];
      else if (k.slice(0,2) === "on") e.addEventListener(k.slice(2), attrs[k]);
      else if (attrs[k] !== null && attrs[k] !== undefined && attrs[k] !== false) e.setAttribute(k, attrs[k]);
    }
    (kids || []).forEach(function(c){ if (c) e.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return e;
  }
  function toast(msg){
    var t = document.getElementById("toast");
    t.textContent = msg; t.classList.add("on");
    clearTimeout(toast._t); toast._t = setTimeout(function(){ t.classList.remove("on"); }, 2200);
  }
```

Dialog (JSON text) + zoom overlay JS:

`labelbot/screens/review.html:589-595`
```js
  function showText(text, msg){
    var dlg = document.getElementById("dlg"), ta = document.getElementById("dlgTa");
    document.getElementById("dlgP").textContent = msg || "";
    ta.value = text;
    try { dlg.showModal(); } catch(e){ dlg.setAttribute("open", ""); }
    ta.focus(); ta.select();
  }
```

`labelbot/screens/review.html:619-632`
```js
  document.getElementById("dlgClose").addEventListener("click", function(){
    var d = document.getElementById("dlg"); try { d.close(); } catch(e){ d.removeAttribute("open"); }
  });
  document.getElementById("dlgSel").addEventListener("click", function(){
    var ta = document.getElementById("dlgTa"); ta.focus(); ta.select();
  });
  var zoom = document.getElementById("zoom");
  var sibZoom = null;  // 같은 파일 슬라이드 확대 중이면 {list, i}
  var sibNav = null;   // 지금 검수 중인 chunk의 같은 파일 슬라이드 뷰어 {list, i, show}
  function closeZoom(){
    if (sibZoom && sibNav && sibNav.list === sibZoom.list) sibNav.show(sibZoom.i);
    zoom.classList.remove("on"); zoom.textContent = ""; sibZoom = null;
  }
  zoom.addEventListener("click", closeZoom);
```

Reason tag + list item (`.item > .l1 + .l2 + .tags`, `.mark` badges):

`labelbot/screens/review.html:730-749`
```js
  function tagFor(code){
    var hard = code === "CLASSIFY_FAILED" || code === "LABEL_FAILED";
    return h("span", {class:"tag" + (hard ? " hard" : (code === "UNKNOWN_HIGH" || code === "LOW_CONFIDENCE" ? " soft" : "")), title:reasonLabels[code] || code, text:code});
  }
  function itemEl(c){
    var fix = chunkCorrections(c).length;
    var mk = [];
    if (status[c.chunk_id] === "confirmed") mk.push(h("span", {class:"mark ok", text:"확인"}));
    if (status[c.chunk_id] === "undecidable_image") mk.push(h("span", {class:"mark img", text:"이미지"}));
    if (fix) mk.push(h("span", {class:"mark fix", text:"교정 " + fix}));
    var nrv = rvFor(c).length;
    if (nrv) mk.push(h("span", {class:"mark rv", text:"재검토 " + nrv}));
    var b = h("button", {class:"item" + (c.chunk_id === selId ? " on" : ""), type:"button", "data-id":c.chunk_id, "aria-current": c.chunk_id === selId ? "true" : false,
      onclick:function(){ select(c.chunk_id); }}, [
      h("div", {class:"l1"}, [h("span", {class:"id mono", text:c.chunk_id}), h("span", {class:"mono", text:"p." + c.slide_no})].concat(mk)),
      h("div", {class:"l2", text:c.title || c.file_name}),
      h("div", {class:"tags"}, (c.reason_codes || []).map(tagFor))
    ]);
    return b;
  }
```

Value chip (`.v`, `.v.na`, `.v.unk`), confidence (`.conf`), definition text:

`labelbot/screens/review.html:1094-1116`
```js
  function valueDef(ax, name){
    var v = null;
    (ax.values || []).forEach(function(x){ if (x.name === name) v = x; });
    return v;
  }
  function defText(v){
    if (!v) return "";
    var t = v.definition || "";
    if (v.include) t += (t ? "\n" : "") + "포함: " + v.include;
    if (v.exclude) t += (t ? "\n" : "") + "제외: " + v.exclude;
    return t;
  }
  function confEl(x){
    if (x === null || x === undefined) return h("span", {class:"conf muted", text:"확신도 -"});
    var low = flag.confidence_min !== undefined && x < flag.confidence_min;
    return h("span", {class:"conf" + (low ? " warnc" : ""), title: low ? "기준 " + flag.confidence_min + " 미만" : "", text:"확신도 " + Number(x).toFixed(2)});
  }
  function botChip(ax, name){
    var cls = "v" + (name === "해당 없음" ? " na" : name === "unknown" ? " unk" : "");
    var d = defText(valueDef(ax, name));
    var tip = name === "unknown" ? "unknown: 본문에서 판단할 근거를 찾지 못함" : name === "해당 없음" ? "해당 없음: 이 축이 이 chunk에 적용되지 않음" : d;
    return h("span", {class:cls, title:tip, text:name});
  }
```

Axis card (`.axis`: head + badges, bot line, definitions `<details>`, `.edit` of `.opt` toggles):

`labelbot/screens/review.html:1254-1302`
```js
  function axisCard(c, ax){
    var wrap = h("div", {class:"axis"});
    var multi = !!ax.multi;
    var cur = curAxis(c, ax.name);
    var bot = botAxis(c, ax.name);
    var edited = edits[c.chunk_id] && edits[c.chunk_id]["a:" + ax.name];
    var changed = edited && edited.length && (!bot || !sameSet(bot.values, edited));
    wrap.appendChild(h("div", {class:"axhead"}, [
      h("b", {text:ax.name}), h("span", {class:"badge", text:ax.kind}), h("span", {class:"badge", text:multi ? "복수 선택" : "단일 선택"}),
      changed ? h("span", {class:"changed", text:"교정됨"}) : null, rvBadge(c, "axis", ax.name)
    ]));
    if (ax.definition) wrap.appendChild(h("div", {class:"axdef", text:ax.definition}));

    if (!c.classify_failed){
      var line = h("div", {class:"botline"}, [h("span", {class:"k", text:"봇"})]);
      if (bot){
        bot.values.forEach(function(v){ line.appendChild(botChip(ax, v)); });
        line.appendChild(confEl(bot.confidence));
      } else line.appendChild(h("span", {class:"muted", text:"봇 값 없음"}));
      wrap.appendChild(line);
      if (bot && bot.evidence) wrap.appendChild(h("div", {class:"ev", text:bot.evidence}));
    }

    if ((ax.values || []).length){
      var botSet = bot ? bot.values : [];
      var dl = h("dl");
      ax.values.forEach(function(v){
        dl.appendChild(h("dt", {class:botSet.indexOf(v.name) >= 0 ? "botv" : "", text:(v.parent ? v.parent + " › " : "") + v.name}));
        dl.appendChild(h("dd", {text:defText(v).replace(/\n/g, " / ")}));
      });
      wrap.appendChild(h("details", {class:"defs"}, [h("summary", {text:"값 정의·판정 규칙 보기 (" + ax.values.length + ")"}), dl]));
    }

    var ed = h("div", {class:"edit", role:"group", "aria-label":ax.name + " 교정"}, [h("span", {class:"k", text:"교정"})]);
    function opt(name, special){
      var on = cur.indexOf(name) >= 0;
      var v = valueDef(ax, name);
      return h("button", {class:"opt" + (special ? " sp" : ""), type:"button", "aria-pressed":String(on),
        title: special ? "" : defText(v), text:(v && v.parent ? v.parent + " › " : "") + name,
        onclick:function(){ toggleAxis(c, ax, name, special); }});
    }
    (ax.values || []).forEach(function(v){ ed.appendChild(opt(v.name, false)); });
    SPECIAL.forEach(function(s){ ed.appendChild(opt(s, true)); });
    wrap.appendChild(ed);
    var eb = changed ? evBox(c, "a:" + ax.name) : null;
    if (eb) wrap.appendChild(eb);
    if (rvOn) wrap.appendChild(h("div", {class:"rvwrap"}, [rvButton(c, "axis", ax.name, "taxonomy 재검토 요청"), rvPanel(c, "axis", ax.name, ax, false)]));
    return wrap;
  }
```

Question card (`.axis` reused with `.qhead`, `.ans`, `.opt` buttons O/X/N/A/판단 불가):

`labelbot/screens/review.html:1349-1382`
```js
  function questionCard(c, qid){
    var wrap = h("div", {class:"axis"});
    var bot = botAnswer(c, qid), cur = curAnswer(c, qid);
    var edited = edits[c.chunk_id] && edits[c.chunk_id]["q:" + qid];
    var changed = edited && (!bot || bot.answer !== edited);
    wrap.appendChild(h("div", {class:"qhead"}, [
      h("span", {class:"qid mono", text:qid}), changed ? h("span", {class:"changed", text:"교정됨"}) : null, rvBadge(c, "question", qid)
    ]));
    wrap.appendChild(h("div", {style:"margin:2px 0 6px", text:qtext[qid] || "(질문 문장 없음)"}));
    if (!c.label_failed){
      var line = h("div", {class:"botline"}, [h("span", {class:"k", text:"봇"})]);
      if (bot){ line.appendChild(h("span", {class:"ans", text:bot.answer})); line.appendChild(confEl(bot.confidence)); }
      else line.appendChild(h("span", {class:"muted", text:"봇 답 없음"}));
      wrap.appendChild(line);
      if (bot && bot.quote) wrap.appendChild(h("div", {class:"ev", text:bot.quote}));
    }
    var ed = h("div", {class:"edit", role:"group", "aria-label":qid + " 교정"}, [h("span", {class:"k", text:"교정"})]);
    ANSWERS.forEach(function(a){
      ed.appendChild(h("button", {class:"opt" + (a === "판단 불가" ? " sp" : ""), type:"button", "aria-pressed":String(cur === a), text:a,
        onclick:function(){
          var e = edits[c.chunk_id] || (edits[c.chunk_id] = {});
          var b = botAnswer(c, qid);
          var next = cur === a ? "" : a;
          if (!next || (b && b.answer === next)) delete e["q:" + qid]; else e["q:" + qid] = next;
          if (!Object.keys(e).length) delete edits[c.chunk_id];
          save(); renderList(); renderDetail(true);
        }}));
    });
    wrap.appendChild(ed);
    var eb = changed ? evBox(c, "q:" + qid) : null;
    if (eb) wrap.appendChild(eb);
    if (rvOn) wrap.appendChild(h("div", {class:"rvwrap"}, [rvButton(c, "question", qid, "taxonomy 재검토 요청"), rvPanel(c, "question", qid, null, false)]));
    return wrap;
  }
```

## E. Slide preview partials (inlined by `review.fill_template`; shared by review.html and slides.html)

Depends on tokens `--bg-grid --radius-sm --text-strong --warning --line --dot --text-muted`. Usage: `SlidePreview.build(layout, image_map)` returns a `.slide` element (container-query font sizes in `cqw`).

### slide_preview.css (full)

`labelbot/screens/slide_preview.css:1-9`
```css
.slide{position:relative;width:100%;container-type:inline-size;background:#FBFCFE;border:1px solid var(--bg-grid);border-radius:var(--radius-sm);overflow:hidden}
.slide .sb{position:absolute;overflow:hidden;line-height:1.18;color:var(--text-strong);white-space:pre-wrap;word-break:break-word;letter-spacing:-0.02em}
.slide .sb.ttl{font-weight:700}
.slide .sb.chart{border:1px dashed var(--warning);background:rgba(201,154,59,.06);padding:.4cqw}
.slide .sb.tbl{border:1px dashed var(--line)}
.slide .sb.tbl table{border-collapse:collapse;width:100%}
.slide .sb.tbl td{border:1px solid var(--bg-grid);padding:.15cqw .3cqw;vertical-align:top}
.slide img.sp{position:absolute;object-fit:contain}
.slide .sp-ph{position:absolute;display:flex;align-items:center;justify-content:center;border:1px dashed var(--dot);background:rgba(168,189,212,.15);color:var(--text-muted);font-size:1.2cqw}
```

### slide_preview.js (full)

`labelbot/screens/slide_preview.js:1-56`
```js
// 슬라이드 미리보기(근사 배치). review.html과 slides.html이 같이 쓴다(fill_template이 그 자리에 넣는다).
// 파서가 읽은 좌표(EMU)에 텍스트·표·차트 요약·삽입 그림을 놓는다. 글꼴·색·도형 모양은 원본과 다르다.
// 글자 크기는 컨테이너 너비 기준 단위(cqw)로 잡아 미리보기 크기가 바뀌어도 비율이 유지된다.
var SlidePreview = (function(){
  "use strict";
  function el(tag, cls, text){
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }
  function build(L, imap){
    if (!L || !L.w || !L.h || (!(L.items || []).length && !(L.pics || []).length)) return null;
    imap = imap || {};
    var wPt = L.w / 12700;
    function pct(v, base){ return (v / base * 100).toFixed(3) + "%"; }
    function place(e, b){
      e.style.left = pct(b[0], L.w); e.style.top = pct(b[1], L.h);
      e.style.width = pct(b[2], L.w); e.style.height = pct(b[3], L.h);
      return e;
    }
    function fs(pt){ return (pt / wPt * 100).toFixed(3) + "cqw"; }
    var slide = el("div", "slide");
    slide.setAttribute("style", "aspect-ratio:" + L.w + " / " + L.h);
    slide.setAttribute("role", "img");
    slide.setAttribute("aria-label", "슬라이드 근사 미리보기");
    (L.pics || []).forEach(function(p){
      var url = imap[p.sha];
      if (url){
        var im = el("img", "sp"); im.src = url; im.alt = "슬라이드 그림";
        slide.appendChild(place(im, p.b));
      } else {
        slide.appendChild(place(el("div", "sp-ph", "그림"), p.b));
      }
    });
    (L.items || []).forEach(function(it){
      var e;
      if (it.k === "table"){
        e = el("div", "sb tbl");
        var tb = el("table");
        (it.rows || []).forEach(function(r){
          var tr = el("tr");
          r.forEach(function(cell){ tr.appendChild(el("td", null, cell)); });
          tb.appendChild(tr);
        });
        e.appendChild(tb); e.style.fontSize = fs(9);
      } else {
        e = el("div", "sb " + (it.k === "chart" ? "chart" : "") + (it.ph === "title" || it.ph === "ctrTitle" ? " ttl" : ""), it.t || "");
        e.style.fontSize = fs(it.k === "chart" ? 10 : Math.max(6, (it.sz || 1400) / 100));
      }
      slide.appendChild(place(e, it.b));
    });
    return slide;
  }
  return {build: build};
})();
```
