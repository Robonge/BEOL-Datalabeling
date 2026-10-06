# layouts.md - page shells

Two shells exist. Both render client-side from the injected `DATA` object; there are no routes/templates beyond the HTML files.

## 1. results.html - single scrolling column (`.wrap`)

Markup shell (`labelbot/screens/results.html:138-140`): `<div class="wrap" id="app"></div><div class="tip" id="tip"></div>` then the script.
Shell CSS (base, header, wrap, big-KPI row, big-grid, responsive):

`labelbot/screens/results.html:19-33`
```css
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
```

`labelbot/screens/results.html:98-98`
```css
@media (max-width:760px){.det{grid-template-columns:1fr}.stack-row{grid-template-columns:90px 1fr 48px}}
```

`labelbot/screens/results.html:100-104`
```css
/* 핵심 지표 확대 레이아웃 */
header.slim{display:flex;align-items:baseline;gap:12px;margin-bottom:14px}
header.slim h1{font-size:20px;margin:0}
.big-kpis{display:grid;grid-template-columns:1fr 1fr 1.6fr;gap:16px;margin-bottom:12px}
.bk{background:var(--surface);border:1px solid var(--bg-grid);border-radius:var(--radius);padding:22px 26px}
```

`labelbot/screens/results.html:113-116`
```css
.alert-line{font-size:13px;color:var(--text-muted);margin:0 0 14px;padding:6px 10px;border-radius:8px;background:var(--surface)}
.big-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(460px,1fr));gap:16px;margin-bottom:16px}
.card.big{margin:0 0 16px;padding:22px 26px}
.big-grid .card.big{margin:0}
```

`labelbot/screens/results.html:135-135`
```css
@media (max-width:900px){.big-kpis{grid-template-columns:1fr}.card.big .bar-row{grid-template-columns:120px 1fr 90px}}
```

Section order rendered by the main IIFE (`header.slim` -> `.big-kpis` (3 `.bk`, last is `.hero` with donut) -> `.alert-line` -> `.big-grid` (불량 사유 bar card + 질문 답 분포 stack card) -> 축별 stack card -> collapsible `details.fold` 축별 값 분포 (`.grid` of `.mini`) -> collapsible chunk table with filters -> `footer`). Full script, verbatim:

`labelbot/screens/results.html:141-290`
```html
<script>
const DATA = /*__DATA__*/null;
(function(){
  const app = document.getElementById('app');
  const tip = document.getElementById('tip');
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

  const k = DATA.kpi;
  const QNAME = q => q === 'Q-COM-001' ? 'BEOL 연관 자료 여부' : q.startsWith('Q-GEN') ? '라벨 정합성' : q.startsWith('Q-CTL') ? '함정질문' : q;
  const ratio = (n, d) => d ? Math.round(100 * n / d) : 0;
  let html = `<header class="slim"><h1>라벨링 결과</h1><span class="sub mono">${esc(DATA.run_id)} · ${esc(DATA.model)}</span></header>`;
  const fr = k.chunks ? k.flagged / k.chunks : null;
  html += `<div class="big-kpis">
    <div class="bk"><div class="k">파싱한 pptx 파일</div><div class="v">${k.files}<small>개</small></div>${k.failed_files ? `<div class="note warn">실패 ${k.failed_files}</div>` : ''}</div>
    <div class="bk"><div class="k">전체 chunk</div><div class="v">${k.chunks}<small>개</small></div>${k.classify_failed + k.label_failed ? `<div class="note warn">분류 실패 ${k.classify_failed} · 라벨 실패 ${k.label_failed}</div>` : ''}</div>
    <div class="bk hero">${donut(fr, '불량 chunk 비율')}<div><div class="k">불량 chunk (검수 대상)</div><div class="v">${k.flagged}<small>/ ${k.chunks}</small></div><div class="v2">${pct(k.flagged, k.chunks)}</div></div></div>
  </div>`;
  if (DATA.alerts.length) html += `<div class="alert-line">⚠ ${DATA.alerts.map(a => `${esc(DATA.alert_labels[a.condition] || a.condition)} ${(a.value*100).toFixed(0)}%(기준 ${(a.threshold*100).toFixed(0)}%)`).join(' · ')}</div>`;

  // 불량 사유 + 질문 답 분포
  const rk = Object.keys(DATA.reasons).filter(c => DATA.reasons[c]).sort((a, b) => DATA.reasons[b] - DATA.reasons[a]);
  const rmax = Math.max(1, ...Object.values(DATA.reasons));
  html += '<div class="big-grid">';
  html += `<div class="card big"><h2>불량 사유</h2>` + (rk.length ? rk.map(c => `<div class="bar-row" data-tip="${esc(c)} · ${DATA.reasons[c]}건">
      <div class="lbl">${esc(DATA.reason_labels[c] || c)}</div><div class="track"><div class="bar danger" style="width:${(100*DATA.reasons[c]/rmax).toFixed(1)}%"></div></div>
      <div class="n">${DATA.reasons[c]}<small> · ${pct(DATA.reasons[c], k.chunks)}</small></div></div>`).join('') : '<div class="empty">불량 사유 없음</div>') + '</div>';
  html += `<div class="card big"><h2>질문 답 분포</h2>
    <div class="legend"><span><i style="background:var(--s-value)"></i>O</span><span><i style="background:var(--s-unknown)"></i>X</span><span><i style="background:var(--s-none)"></i>N/A</span></div>`;
  DATA.questions.forEach(q => {
    const t = q.O + q.X + q.NA;
    html += `<div class="qrow" title="${esc(q.qid)} · ${esc(q.text)}"><div class="qn">${esc(QNAME(q.qid))}<span class="mono">${esc(q.qid)}</span></div>` +
      stack(QNAME(q.qid), [{name:'O', n:q.O, color:'--s-value', cls:''}, {name:'X', n:q.X, color:'--s-unknown', cls:''}, {name:'N/A', n:q.NA, color:'--s-none', cls:'none'}], t) +
      `<div class="qp">O ${ratio(q.O,t)}% · X ${ratio(q.X,t)}% · N/A ${ratio(q.NA,t)}%</div></div>`;
  });
  html += '</div></div>';

  // 축별 값/unknown/해당 없음 비율
  html += `<div class="card big"><h2>축별 값 · unknown · 해당 없음 비율</h2>
    <div class="legend"><span><i style="background:var(--s-value)"></i>값</span><span><i style="background:var(--s-unknown)"></i>unknown</span><span><i style="background:var(--s-none)"></i>해당 없음</span></div>`;
  DATA.axes.filter(a => a.active).forEach(a => {
    const s = a.states, t = s.value + s.unknown + s.na;
    html += `<div class="axrow">` + stack(a.name, [
      {name:'값', n:s.value, color:'--s-value', cls:''},
      {name:'unknown', n:s.unknown, color:'--s-unknown', cls:''},
      {name:'해당 없음', n:s.na, color:'--s-none', cls:'none'}], t) +
      `<div class="qp">값 ${ratio(s.value,t)}% · unknown ${ratio(s.unknown,t)}% · 해당 없음 ${ratio(s.na,t)}%</div></div>`;
  });
  html += '</div>';

  // 축별 값 분포(접힘)
  html += `<details class="fold"><summary>축별 값 분포 (자세히)</summary><div class="grid">`;
  DATA.axes.filter(a => a.active).forEach(a => {
    const vals = a.values.filter(v => v.n).sort((x, y) => y.n - x.n);
    const max = Math.max(1, ...vals.map(v => v.n));
    html += `<div class="mini"><h3>${esc(a.name)}</h3>` + (vals.map(v => `<div class="bar-row" data-tip="${esc(a.name)} = ${esc(v.name)} · ${v.n}건">
        <div class="lbl" title="${esc(v.name)}">${esc(v.name)}</div><div class="track"><div class="bar" style="width:${(100*v.n/max).toFixed(1)}%"></div></div><div class="n">${v.n}</div></div>`).join('') || '<div class="empty">값 없음</div>') + '</div>';
  });
  html += '</div></details>';

  // chunk 목록
  const axesActive = DATA.axes.filter(a => a.active);
  html += `<details class="fold"><summary>chunk별 라벨 목록 (행을 누르면 본문·근거·답)</summary><div class="card" style="margin:8px 0 0">
    <div class="filters">
      <select id="fFile"><option value="">전체 파일</option>${DATA.files.map(f => `<option value="${esc(f.file_id)}">${esc(f.file_name)} (${f.chunks})</option>`).join('')}</select>
      <select id="fAxis"><option value="">축 값 전체</option>${axesActive.map(a => `<optgroup label="${esc(a.name)}">${a.values.filter(v => v.n).map(v => `<option value="${esc(a.name)}\u0001${esc(v.name)}">${esc(a.name)} = ${esc(v.name)} (${v.n})</option>`).join('')}<option value="${esc(a.name)}\u0001unknown">${esc(a.name)} = unknown</option></optgroup>`).join('')}</select>
      <select id="fAns"><option value="">BEOL 연관 전체</option><option>O</option><option>X</option><option>N/A</option></select>
      <label class="chk"><input type="checkbox" id="fFlag"> 불량만</label>
      <input type="search" id="fText" placeholder="제목·본문 검색">
      <span class="count" id="cnt"></span>
    </div>
    <div class="tbl-wrap"><table><thead><tr><th style="width:22%">파일 · 슬라이드</th><th style="width:20%">제목</th><th>축 값</th><th style="width:80px">BEOL 연관</th><th style="width:130px">불량 사유</th></tr></thead><tbody id="tb"></tbody></table></div></div></details>`;
  html += '<footer>로컬 파일 화면. 외부 주소를 참조하지 않는다. 표시용이며 교정은 검수 화면(review.html)에서 한다.</footer>';
  app.innerHTML = html;
  bindTips(app);

  const tb = document.getElementById('tb');
  const open = new Set();
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
  function render(){
    const ff = document.getElementById('fFile').value, fa = document.getElementById('fAxis').value,
      fq = document.getElementById('fAns').value, fl = document.getElementById('fFlag').checked,
      ft = document.getElementById('fText').value.trim().toLowerCase();
    const rows = DATA.chunks.filter(c => {
      if (ff && c.file_id !== ff) return false;
      if (fa) { const [ax, val] = fa.split('\u0001'); const v = c.axes[ax]; if (!v) return false;
        if (val === 'unknown' ? v.status !== 'unknown' : !v.values.includes(val)) return false; }
      if (fq && !(c.answers['Q-COM-001'] && c.answers['Q-COM-001'].answer === fq)) return false;
      if (fl && !c.reasons.length) return false;
      if (ft && !(c.title + '\n' + c.text).toLowerCase().includes(ft)) return false;
      return true;
    });
    document.getElementById('cnt').textContent = rows.length + ' / ' + DATA.chunks.length + ' chunk';
    tb.innerHTML = rows.map(c => {
      const a = c.answers['Q-COM-001'];
      const r = `<tr class="row${open.has(c.chunk_id) ? ' open' : ''}" data-id="${esc(c.chunk_id)}"><td>${esc(c.file_name)}<div class="sub mono">슬라이드 ${c.slide_no} · ${esc(c.chunk_type || '-')}</div></td>
        <td>${esc(c.title)}</td><td>${chips(c)}</td>
        <td>${a ? `<span class="ans ${a.answer === 'N/A' ? 'NA' : a.answer}">${esc(a.answer)}</span>` : '<span class="empty">-</span>'}</td>
        <td>${c.reasons.length ? c.reasons.map(x => `<span class="flag" title="${esc(DATA.reason_labels[x] || x)}">${esc(x)}</span>`).join('') : '<span class="ok">✓ 정상</span>'}</td></tr>`;
      return r + (open.has(c.chunk_id) ? detail(c) : '');
    }).join('') || '<tr><td colspan="5" class="empty">조건에 맞는 chunk가 없다</td></tr>';
  }
  tb.addEventListener('click', e => { const tr = e.target.closest('tr.row'); if (!tr) return;
    const id = tr.dataset.id; open.has(id) ? open.delete(id) : open.add(id); render(); });
  ['fFile', 'fAxis', 'fAns', 'fFlag', 'fText'].forEach(id => document.getElementById(id).addEventListener('input', render));
  render();
})();
```

## 2. review.html - full-viewport app grid (`.app`)

Structure: `.app` (grid rows `auto 1fr`, 100vh) > `header.bar` (title, meta, spacer, stat, inbox status, buttons) + `.cols` (grid `344px 1fr`) > `aside.list` (`.filters` + `.items`) + `main.detail` (`.dh` header, `.actions`, `.two` columns). Below 860px it collapses to one column; below 1180px `.two` is one column.

Static markup (`review.html:222-234`) and shell CSS:

`labelbot/screens/review.html:222-234`
```html
<body>
<div id="root"></div>
<div class="zoom" id="zoom" aria-hidden="true"></div>
<div class="toast" id="toast" role="status"></div>
<dialog id="dlg">
  <h3>JSON 텍스트</h3>
  <p id="dlgP"></p>
  <textarea id="dlgTa" readonly aria-label="내보내기 JSON"></textarea>
  <div class="row" style="margin-top:10px;display:flex;gap:8px;justify-content:flex-end">
    <button class="btn" id="dlgSel" type="button">전체 선택</button>
    <button class="btn primary" id="dlgClose" type="button">닫기</button>
  </div>
</dialog>
```

`labelbot/screens/review.html:20-46`
```css
html,body{margin:0;height:100%}
body{
  font-family:var(--font); font-size:13.5px; line-height:1.55; letter-spacing:-0.02em; font-weight:400;
  color:var(--text-strong); background-color:var(--bg-base);
  background-image:
    linear-gradient(to right, rgba(200,212,228,.5) 0.5px, transparent 0.5px),
    linear-gradient(to bottom, rgba(200,212,228,.5) 0.5px, transparent 0.5px);
  background-size:48px 48px;
}
b,strong,h1,h2,h3,h4{font-weight:700}
h1,h2,h3,h4{margin:0}
button,input,textarea,select{font:inherit;letter-spacing:inherit;color:inherit}
.mono{font-family:var(--mono);letter-spacing:-0.01em}
.muted{color:var(--text-muted)}
.warnc{color:#A97C1F}

.app{display:grid;grid-template-rows:auto 1fr;height:100vh}
.bar{display:flex;align-items:center;gap:18px;padding:10px 20px;border-bottom:1px solid var(--bg-grid);background:rgba(237,241,247,.92);flex-wrap:wrap}
.bar h1{font-size:18px;letter-spacing:-0.055em}
.bar .meta{font-size:11.5px;color:var(--text-muted)}
.bar .sp{flex:1}
.bar .stat{font-size:12px;color:var(--text-muted)}
.bar .stat b{color:var(--text-strong)}
.cols{display:grid;grid-template-columns:344px 1fr;min-height:0}
.list{border-right:1px solid var(--bg-grid);display:flex;flex-direction:column;min-height:0;background:rgba(237,241,247,.7)}
.filters{padding:10px 12px;border-bottom:1px solid var(--bg-grid)}
.filters .lbl{font-size:11px;color:var(--text-muted);margin-bottom:6px}
```

`labelbot/screens/review.html:55-57`
```css
.items{overflow:auto;padding:8px 10px 30px;flex:1}
.grp{border-left:3px solid var(--primary-soft);margin:6px 0;padding-left:6px;border-radius:2px;background:rgba(107,130,196,.06)}
.grp .gh{font-size:10.5px;color:var(--primary);padding:3px 4px 1px}
```

`labelbot/screens/review.html:77-84`
```css
.detail{overflow:auto;min-height:0;padding:18px 24px 60px}
.dh{margin-bottom:12px}
.dh h2{font-size:20px;letter-spacing:-0.055em;word-break:break-all}
.dh .path{font-size:11.5px;color:var(--text-muted);word-break:break-all}
.dh .metrics{display:flex;gap:16px;flex-wrap:wrap;margin-top:8px;align-items:center}
.metric{font-size:12px}
.metric .k{color:var(--text-muted);margin-right:5px}
.actions{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0 14px}
```

`labelbot/screens/review.html:96-96`
```css
.two{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.1fr);gap:18px;align-items:start}
```

`labelbot/screens/review.html:211-219`
```css
@media (max-width:1180px){ .two{grid-template-columns:1fr} }
@media (max-width:860px){
  .app{height:auto}
  .cols{grid-template-columns:1fr}
  .list{border-right:0;border-bottom:1px solid var(--bg-grid)}
  .items{max-height:260px}
  .detail{padding:14px 14px 60px}
}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
```

### Top bar + app shell build (`init`)

`labelbot/screens/review.html:1559-1588`
```js
  function init(){
    load();
    statEl = h("div");
    filtersEl = h("div", {class:"filters"});
    itemsEl = h("div", {class:"items", role:"list", "aria-label":"불량 chunk 목록"});
    listEl = h("aside", {class:"list"}, [filtersEl, itemsEl]);
    detailEl = h("main", {class:"detail"});
    root.appendChild(h("div", {class:"app"}, [
      h("header", {class:"bar"}, [
        h("h1", {text:"검수"}),
        h("div", {class:"meta mono", text:"실행 " + DATA.run_id + "  ·  생성 " + (DATA.generated_at || "-") + "  ·  기준 unknown ≥ " + (flag.unknown_ratio_min !== undefined ? flag.unknown_ratio_min : "-") + ", 확신도 < " + (flag.confidence_min !== undefined ? flag.confidence_min : "-")}),
        h("div", {class:"sp", style:"flex:1"}),
        statEl,
        inboxEl = h("span", {class:"meta", role:"status"}),
        doneBtn = h("button", {class:"btn primary", type:"button", text:"검수 완료", hidden:true,
          title:"마지막 교정을 저장하고 반영·적재로 넘깁니다", onclick:reviewDone}),
        h("button", {class:"btn", type:"button", text:"JSON 저장", onclick:download}),
        h("button", {class:"btn", type:"button", text:"텍스트로 복사", onclick:copyText})
      ]),
      h("div", {class:"cols"}, [listEl, detailEl])
    ]));
    var f = flat(visibleChunks());
    selId = f.length ? f[0].chunk_id : null;
    renderList(); renderDetail();
    inboxCheck();
  }
  init();
})();
</script>
</body>
```

### Left list: filters, items, stat (item/tag builders are in components.md section D)

`labelbot/screens/review.html:695-728`
```js
  function reasonCodes(){
    var order = Object.keys(reasonLabels), cnt = {};
    chunks.forEach(function(c){ (c.reason_codes || []).forEach(function(r){ cnt[r] = (cnt[r] || 0) + 1; if (order.indexOf(r) < 0) order.push(r); }); });
    return order.map(function(r){ return {code:r, n:cnt[r] || 0}; });
  }
  function isTouched(c){
    return !!status[c.chunk_id] || chunkCorrections(c).length > 0;
  }
  function visibleChunks(){
    var codes = Object.keys(activeReasons).filter(function(k){ return activeReasons[k]; });
    var arr = chunks.filter(function(c){
      if (onlyTodo && isTouched(c)) return false;
      if (onlyRevisit && !rvFor(c).length) return false;
      if (!codes.length) return true;
      return (c.reason_codes || []).some(function(r){ return codes.indexOf(r) >= 0; });
    });
    arr.sort(function(a, b){
      var d = (b.reason_codes || []).length - (a.reason_codes || []).length;
      if (d) return d;
      return a.chunk_id < b.chunk_id ? -1 : a.chunk_id > b.chunk_id ? 1 : 0;
    });
    // cluster dup groups at the position of their first member
    var out = [], used = {};
    arr.forEach(function(c){
      if (used[c.chunk_id]) return;
      if (c.dup_group){
        var members = arr.filter(function(x){ return x.dup_group === c.dup_group; });
        members.forEach(function(m){ used[m.chunk_id] = 1; });
        out.push({group:c.dup_group, items:members});
      } else { used[c.chunk_id] = 1; out.push({group:null, items:[c]}); }
    });
    return out;
  }
  function flat(blocks){ var f = []; blocks.forEach(function(b){ b.items.forEach(function(c){ f.push(c); }); }); return f; }
```

`labelbot/screens/review.html:753-821`
```js
  function renderFilters(){
    filtersEl.textContent = "";
    filtersEl.appendChild(h("div", {class:"lbl", text:"사유 코드로 거르기 (여러 개 선택 시 하나라도 해당)"}));
    var chips = h("div", {class:"chips", role:"group", "aria-label":"사유 코드 필터"});
    var anyOn = Object.keys(activeReasons).some(function(k){ return activeReasons[k]; });
    chips.appendChild(h("button", {class:"chip" + (!anyOn ? " on" : ""), type:"button", "aria-pressed":String(!anyOn),
      onclick:function(){ activeReasons = {}; renderList(); ensureSel(); renderDetail(); }}, ["전체", h("span", {class:"n", text:String(chunks.length)})]));
    reasonCodes().forEach(function(r){
      var on = !!activeReasons[r.code];
      chips.appendChild(h("button", {class:"chip" + (on ? " on" : ""), type:"button", title:reasonLabels[r.code] || r.code, "aria-pressed":String(on),
        onclick:function(){ activeReasons[r.code] = !activeReasons[r.code]; renderList(); ensureSel(); renderDetail(); }},
        [r.code, h("span", {class:"n", text:String(r.n)})]));
    });
    filtersEl.appendChild(chips);
    filtersEl.appendChild(h("div", {class:"chips", style:"margin-top:8px"}, [
      h("button", {class:"chip" + (onlyTodo ? " on" : ""), type:"button", "aria-pressed":String(onlyTodo),
        onclick:function(){ onlyTodo = !onlyTodo; renderList(); ensureSel(); renderDetail(); }, text:"처리 전만 보기"}),
      rvOn ? h("button", {class:"chip" + (onlyRevisit ? " on" : ""), type:"button", "aria-pressed":String(onlyRevisit),
        onclick:function(){ onlyRevisit = !onlyRevisit; renderList(); ensureSel(); renderDetail(); }},
        ["재검토 요청 있음", h("span", {class:"n", text:String(chunks.filter(function(c){ return rvFor(c).length > 0; }).length)})]) : null
    ]));
  }
  function renderList(){
    var y = itemsEl.scrollTop;
    rvByChunk = null; // 렌더마다 한 번만 다시 묶는다
    renderFilters();
    itemsEl.textContent = "";
    var blocks = visibleChunks(), total = 0;
    blocks.forEach(function(b){
      total += b.items.length;
      if (b.group && b.items.length > 1){
        var g = h("div", {class:"grp"}, [h("div", {class:"gh mono", text:"중복 묶음 " + b.group + " · " + b.items.length + "건 (교정은 chunk별)"})]);
        b.items.forEach(function(c){ g.appendChild(itemEl(c)); });
        itemsEl.appendChild(g);
      } else b.items.forEach(function(c){ itemsEl.appendChild(itemEl(c)); });
    });
    if (!total) itemsEl.appendChild(h("div", {class:"note", text:"조건에 맞는 chunk가 없습니다."}));
    itemsEl.scrollTop = y;
    renderStat();
  }
  function renderStat(){
    var nCorr = 0, nStat = 0;
    chunks.forEach(function(c){ nCorr += chunkCorrections(c).length; if (status[c.chunk_id]) nStat++; });
    statEl.textContent = "";
    statEl.appendChild(h("span", {class:"stat"}, ["불량 ", h("b", {text:String(chunks.length)}), " · 교정 ", h("b", {text:String(nCorr)}),
      " · 판정 ", h("b", {text:String(nStat)}), " · 동의어 ", h("b", {text:String(syns.length)}),
      rvOn ? " · 재검토 " : null, rvOn ? h("b", {text:String(rvOutput().length)}) : null]));
  }
  function ensureSel(){
    var f = flat(visibleChunks());
    if (!f.length){ selId = null; return; }
    if (!selId || !f.some(function(c){ return c.chunk_id === selId; })) selId = f[0].chunk_id;
    renderList2();
  }
  function renderList2(){ // refresh highlighting only
    var items = itemsEl.querySelectorAll(".item");
    for (var i = 0; i < items.length; i++){
      var on = items[i].getAttribute("data-id") === selId;
      items[i].classList.toggle("on", on);
    }
  }
  function select(id){
    if (rvDraft && rvDraft.chunk_id !== id){
      if (rvDraft.dirty) toast("저장하지 않은 재검토 요청 초안을 닫았습니다");
      rvDraft = null;
    }
    selId = id; pendingAlias = ""; evMode = null;
    renderList2(); renderDetail(true);
  }
```

### Detail pane: header, actions, two-column body (`renderDetail`)

`labelbot/screens/review.html:1385-1523`
```js
  function renderDetail(keep){
    var y = detailEl.scrollTop;
    var ctxEl = document.getElementById("ctxtext"), ctxY = ctxEl ? ctxEl.scrollTop : 0;
    detailEl.textContent = "";
    var c = byId[selId];
    // 교정을 되돌려 근거 대상이 사라졌으면 근거 지정을 끝낸다.
    if (evMode && (!c || evMode.chunk_id !== c.chunk_id || evKeys(c).indexOf(evMode.key) < 0)) evMode = null;
    if (!c){
      detailEl.appendChild(h("div", {class:"emptystate"}, [h("h2", {text:"검수할 chunk가 없습니다"}), h("p", {text:"필터를 바꾸거나 해제해 보세요."})]));
      return;
    }
    var unkWarn = c.unknown_ratio !== null && c.unknown_ratio !== undefined && flag.unknown_ratio_min !== undefined && c.unknown_ratio >= flag.unknown_ratio_min;
    var confWarn = c.min_confidence !== null && c.min_confidence !== undefined && flag.confidence_min !== undefined && c.min_confidence < flag.confidence_min;
    function num(x){ return x === null || x === undefined ? "-" : Number(x).toFixed(2); }
    detailEl.appendChild(h("div", {class:"dh"}, [
      h("h2", {text:c.file_name}),
      h("div", {class:"path mono", text:c.rel_path + "  ·  슬라이드 " + c.slide_no + "  ·  " + c.chunk_id + (c.dup_group ? "  ·  중복 묶음 " + c.dup_group : "")}),
      h("div", {class:"metrics"}, [
        h("div", {class:"tags"}, (c.reason_codes || []).map(function(r){
          var t = tagFor(r); t.textContent = r + " · " + (reasonLabels[r] || ""); t.style.fontSize = "10.5px"; return t;
        })),
        h("span", {class:"metric"}, [h("span", {class:"k", text:"unknown 비율"}), h("b", {class:"mono" + (unkWarn ? " warnc" : ""), text:num(c.unknown_ratio)})]),
        h("span", {class:"metric"}, [h("span", {class:"k", text:"최소 확신도"}), h("b", {class:"mono" + (confWarn ? " warnc" : ""), text:num(c.min_confidence)})])
      ])
    ]));

    var st = status[c.chunk_id];
    var nSame = sameFileFlagged(c).length;
    detailEl.appendChild(h("div", {class:"actions"}, [
      nSame ? h("button", {class:"btn", type:"button", text:"같은 파일 " + nSame + "장에 이 라벨 적용",
        title:"검수 목록에 있는 같은 파일 슬라이드에 이 슬라이드의 분류 축 값과 공통 질문 답을 똑같이 넣습니다",
        onclick:function(){ applyToSameFile(c); }}) : null,
      h("button", {class:"btn" + (st === "confirmed" ? " on-ok" : ""), type:"button", "aria-pressed":String(st === "confirmed"), text:"확인, 이상 없음",
        onclick:function(){ setStatus(c, "confirmed"); }}),
      h("button", {class:"btn" + (st === "undecidable_image" ? " on-img" : ""), type:"button", "aria-pressed":String(st === "undecidable_image"), text:"판단 불가: 정보가 이미지에만 있음",
        onclick:function(){ setStatus(c, "undecidable_image"); }}),
      h("button", {class:"btn", type:"button", text:"다음 ▸ (j)", onclick:function(){ step(1); }}),
      h("button", {class:"btn", type:"button", text:"◂ 이전 (k)", onclick:function(){ step(-1); }})
    ]));

    // left column
    var left = h("div");
    var sp = slidePreview(c);
    if (sp){
      var sc = h("div", {class:"card"}, [
        h("div", {class:"slide-h"}, [
          h("h3", {text:"슬라이드 미리보기 (근사 배치)"}),
          h("button", {class:"btn", type:"button", text:"크게 보기", onclick:function(){ openSlideZoom(c); }})
        ]),
        sp,
        h("div", {class:"slide-note", text:"텍스트·표·삽입 그림을 원래 위치에 놓은 근사 화면입니다. 글꼴·색·도형·차트 그래프는 원본과 다릅니다."})
      ]);
      left.appendChild(sc);
    }
    left.appendChild(sibCard(c));
    var bodyCard = h("div", {class:"card"}, [h("h3", {text:"본문"})]);
    var bodyEl = textNode(c);
    if (evMode) bodyEl.classList.add("evon");
    bodyCard.appendChild(bodyEl);
    bodyCard.appendChild(h("div", {class:"legend"}, [
      h("span", {}, [h("mark", {class:"q", text:"근거"}), " 근거 인용"]),
      h("span", {}, [h("mark", {class:"s", text:"동의어"}), " 동의어 일치 (마우스를 올리면 표준어)"])
    ]));
    synBox = h("div", {class:"syn"});
    bodyCard.appendChild(synBox);
    left.appendChild(bodyCard);
    var cc = evOn ? ctxCard(c) : null;
    if (cc) left.appendChild(cc);

    if (c.images && c.images.length){
      var ic = h("div", {class:"card"}, [h("h3", {text:"이미지 " + c.images.length + "개"})]);
      var box = h("div", {class:"imgs"});
      c.images.forEach(function(u, i){
        var im = document.createElement("img"); im.src = u; im.alt = "이미지 " + (i + 1);
        im.addEventListener("click", function(){ openZoom(u); });
        box.appendChild(im);
      });
      ic.appendChild(box); left.appendChild(ic);
    }
    if (!c.label_failed && c.extracted && c.extracted.length){
      var tb = h("table"), thead = h("thead"), tr0 = h("tr");
      ["항목", "값", "근거"].forEach(function(t){ tr0.appendChild(h("th", {text:t})); });
      thead.appendChild(tr0); tb.appendChild(thead);
      var tbody = h("tbody");
      c.extracted.forEach(function(x){
        var tr = h("tr"); tr.appendChild(h("td", {text:x.item})); tr.appendChild(h("td", {text:x.value})); tr.appendChild(h("td", {text:x.quote || ""}));
        tbody.appendChild(tr);
      });
      tb.appendChild(tbody);
      left.appendChild(h("div", {class:"card"}, [h("h3", {text:"추출된 날짜·담당자"}), tb]));
    }
    // 대조 질문(Q-CTL-): 이 chunk에 붙지 않은 라벨로 만든 질문. 읽기 전용이며 확정 라벨에 들어가지 않는다.
    if (!c.label_failed && c.controls && c.controls.length){
      var ctb = h("table"), cth = h("thead"), ctr0 = h("tr");
      ["대조 라벨", "질문", "답", "근거"].forEach(function(t){ ctr0.appendChild(h("th", {text:t})); });
      cth.appendChild(ctr0); ctb.appendChild(cth);
      var ctbody = h("tbody");
      c.controls.forEach(function(x){
        var tr = h("tr");
        tr.appendChild(h("td", {text:(x.axis || "") + " = " + (x.value || "")}));
        tr.appendChild(h("td", {text:x.text || x.qid}));
        tr.appendChild(h("td", {text:x.answer, style:x.answer === "O" ? "font-weight:700;color:#b42318" : ""}));
        tr.appendChild(h("td", {text:x.quote || ""}));
        ctbody.appendChild(tr);
      });
      ctb.appendChild(ctbody);
      left.appendChild(h("div", {class:"card"}, [h("h3", {text:"대조 질문 (붙지 않은 라벨)"}),
        h("div", {class:"note", text:"O가 나온 라벨은 1차 분류가 놓쳤거나 3차가 과하게 판정한 것입니다. 맞으면 오른쪽 축에서 값을 더해 교정하세요."}),
        ctb]));
    }

    // right column
    var right = h("div");
    var axCard = h("div", {class:"card"}, [h("h3", {}, ["분류 · 상태 축",
      rvOn ? rvButton(c, "new_axis", "", "새 축 제안", "margin-left:auto") : null])]);
    var naPanel = rvOn ? rvPanel(c, "new_axis", "", null, true) : null;
    if (naPanel) axCard.appendChild(naPanel);
    if (c.classify_failed) axCard.appendChild(h("div", {class:"note", text:"1차 분류가 실패했습니다. 봇 값 없이 판정 칸만 표시합니다."}));
    axes.forEach(function(ax){ axCard.appendChild(axisCard(c, ax)); });
    if (!axes.length) axCard.appendChild(h("div", {class:"muted", text:"축 정의가 없습니다."}));
    right.appendChild(axCard);

    var qids = questionIds(c);
    var qCard = h("div", {class:"card"}, [h("h3", {}, ["질문별 답",
      rvOn ? rvButton(c, "question", "", "필요한 질문 제안", "margin-left:auto") : null])]);
    var nqPanel = rvOn ? rvPanel(c, "question", "", null, true) : null;
    if (nqPanel) qCard.appendChild(nqPanel);
    if (c.classify_failed) qCard.appendChild(h("div", {class:"note", text:"분류 실패 chunk는 질문 " + COM_Q + "만 판정합니다."}));
    if (c.label_failed) qCard.appendChild(h("div", {class:"note", text:"3차 라벨링이 실패했습니다. 봇 답 없이 판정 칸만 표시합니다."}));
    qids.forEach(function(q){ qCard.appendChild(questionCard(c, q)); });
    if (!qids.length) qCard.appendChild(h("div", {class:"muted", text:"이 chunk에 매핑된 질문이 없습니다."}));
    right.appendChild(qCard);

    detailEl.appendChild(h("div", {class:"two"}, [left, right]));
    renderSynBox();
    if (keep) detailEl.scrollTop = y; else detailEl.scrollTop = 0;
    var ctxNew = document.getElementById("ctxtext");
    if (ctxNew && keep) ctxNew.scrollTop = ctxY;
  }
```

### Navigation helpers and keyboard (j/k, arrows)

`labelbot/screens/review.html:1524-1557`
```js
  function setStatus(c, s){
    if (status[c.chunk_id] === s) delete status[c.chunk_id]; else status[c.chunk_id] = s;
    save(); renderList(); renderDetail(true);
  }
  function step(d){
    var f = flat(visibleChunks());
    var i = -1;
    f.forEach(function(c, k){ if (c.chunk_id === selId) i = k; });
    var n = f[i + d];
    if (n){
      select(n.chunk_id);
      var el = itemsEl.querySelector('.item[data-id="' + n.chunk_id.replace(/"/g, '\\"') + '"]');
      if (el && el.scrollIntoView) el.scrollIntoView({block:"nearest"});
    }
  }
  document.addEventListener("keydown", function(ev){
    var t = ev.target && ev.target.tagName;
    if (t === "INPUT" || t === "TEXTAREA" || t === "SELECT" || ev.ctrlKey || ev.metaKey || ev.altKey) return;
    if (zoom.classList.contains("on")){
      // 확대 중에는 검수 이동(j/k)을 막는다. 같은 파일 슬라이드면 ←/→로 넘긴다.
      if (ev.key === "Escape") closeZoom();
      else if (sibZoom && ev.key === "ArrowRight") openSibZoom(sibZoom.list, sibZoom.i + 1);
      else if (sibZoom && ev.key === "ArrowLeft") openSibZoom(sibZoom.list, sibZoom.i - 1);
      else return;
      ev.preventDefault();
      return;
    }
    if (sibNav && (ev.key === "ArrowRight" || ev.key === "ArrowLeft")){
      sibNav.show(sibNav.i + (ev.key === "ArrowRight" ? 1 : -1));
      ev.preventDefault();
      return;
    }
    if (ev.key === "j") step(1); else if (ev.key === "k") step(-1);
  });
```
