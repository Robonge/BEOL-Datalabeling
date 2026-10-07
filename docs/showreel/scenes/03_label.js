// 03_label: STEP 01. The LLM orb takes in slide fragments and streams five labels into a card.
import { THREE, E, seg, lerp, clamp, col, S1, mulberry32, makeOrb, makeDecal, makeVoxels } from '../engine.js';
import { el, TitleBlock, Counter, WorldLabel, Card, cardQuad, streamTokens, mixHex } from '../ui.js';

const T = 2.5, TN = 5.0;
const ORB = new THREE.Vector3(S1 - 2.28, 1.44, 0);
const CARD_C = new THREE.Vector3(S1 + 1.64, 1.41, 0.3), CARD_W = 864 / 178, CARD_H = 372 / 178;
const TOKENS_T = [3.50, 3.62, 3.74, 3.86, 3.98, 4.10, 4.22, 4.34];
let st = {};
// scene CSS: denser card body (28/48 mono, matches the reference card fill)
const CSS = '.scene-label-card .card .cbody { margin-top: 26px; font: 500 28px/48px var(--mono); }'
  + '.scene-label-world .wlabel { color: #EDEDED; }'
  + '.scene-label-card .csrc { position: absolute; right: -0.22em; top: -5px; font: 700 16px/48px var(--mono); letter-spacing: 0.22em; color: rgba(191, 194, 201, 0.46); text-transform: uppercase; }'
  + '.scene-label-card .csrc i { font-style: normal; font-size: 21px; color: rgba(255, 106, 26, 0.78); margin-right: 12px; letter-spacing: 0; vertical-align: -1px; }';
function injectCSS() {
  if (document.getElementById('css-03-label')) return;
  const s = document.createElement('style'); s.id = 'css-03-label'; s.textContent = CSS; document.head.appendChild(s);
}

export default {
  id: 'label', start: 2.70, end: 5.65,
  setup(ctx) {
    const root = new THREE.Group();
    const orb = makeOrb({});
    orb.group.position.copy(ORB); root.add(orb.group);
    const decal = makeDecal(3.2, 2.0, 0.32); decal.position.set(ORB.x, 0.004, 0.2); root.add(decal);
    // slide fragments (cells from the slide: 2 light callout, 3 micrograph grays, 1 annotation orange)
    const frag = makeVoxels(6, 0.22); root.add(frag);
    const fc = ['#DCDDE2', '#D4D5DA', '#8F9197', '#5E6066', '#B3B5BB', '#FF6A1A'];
    const fA = frag.geometry.getAttribute('aColor'), r = mulberry32(303), c = new THREE.Color();
    const fr = fc.map((h, i) => { c.set(h); fA.setXYZ(i, c.r, c.g, c.b);
      return { start: new THREE.Vector3(S1 - 7.6 - r() * 0.6, 0.8 + r() * 1.6, 0.4 + r() * 1.4), lift: 0.4 + r() * 0.5, ax: new THREE.Vector3(r() - .5, r() - .5, r() - .5).normalize(), t0: 2.90 + i * 0.05 }; });
    fA.needsUpdate = true;
    // particle stream orb -> card
    const PN = 50, pp = new Float32Array(PN * 3), pc = new Float32Array(PN * 3);
    const pg = new THREE.BufferGeometry(); pg.setAttribute('position', new THREE.BufferAttribute(pp, 3)); pg.setAttribute('color', new THREE.BufferAttribute(pc, 3));
    const pts = new THREE.Points(pg, new THREE.PointsMaterial({ size: 3, sizeAttenuation: false, vertexColors: true, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false }));
    pts.frustumCulled = false; root.add(pts);
    const pr = mulberry32(77);
    const parts = Array.from({ length: PN }, (_, i) => ({ b: 3.45 + (i / PN) * 0.62 + pr() * 0.05, sy: (pr() - 0.5) * 1.1, sz: (pr() - 0.5) * 0.6, ey: (pr() - 0.5) * 1.3, arc: 0.15 + pr() * 0.35, hue: pr(), sz2: pr() }));

    // overlay
    injectCSS();
    const cardDom = el('div', 'scene-label-card layer', ctx.layers.cards);
    const card = new Card(cardDom, 'LABELS', { h: 372 });
    const rows = card.setRows([
      { key: 'module', tokens: ['SAUP', '·', 'TiN', 'spacer'] },
      { key: 'lot_id', tokens: ['RDM8EA.62'] },
      { key: 'decision', tokens: ['pending'] },
      { key: 'open_risk', tokens: ['TDDB'] },
      { key: 'tem_ref', tokens: ['APM-26-6524'] },
    ]);
    const pulse = el('div', 'pulse', rows[4].line);
    Object.assign(pulse.style, { position: 'absolute', left: '-14px', right: '-14px', top: '2px', bottom: '2px', background: 'rgba(255,106,26,0.12)', borderLeft: '2px solid #FF6A1A', opacity: 0, borderRadius: '2px' });
    rows[4].line.style.position = 'relative';
    // provenance: which slide region each label was read from (right column, arrives with the row's value)
    const srcs = ['title', 'callout', 'callout', 'callout', 'image'].map((tx, i) => {
      const d = el('span', 'csrc', rows[i].line); el('i', '', d, '←'); d.appendChild(document.createTextNode(tx)); return d; });
    const wdom = el('div', 'scene-label-world layer', ctx.layers.world);
    const llm = new WorldLabel(wdom, 'LLM', { size: 17, tracking: 0.32 });
    const tdom = el('div', 'scene-label-title layer', ctx.layers.titles);
    const title = new TitleBlock(tdom, { eyebrow: 'STEP 01', words: [{ text: 'Context' }, { text: 'labeling' }], desc: 'An LLM labels the slide.', T, Tn: TN });
    const counter = new Counter(tdom);
    ctx.scene.add(root);
    st = { root, orb, frag, fr, pts, parts, card, rows, srcs, pulse, llm, title, counter };
    return { root, dom: [cardDom, wdom, tdom] };
  },
  update(ctx, t) {
    const s = st;
    // fragments fly into the core; each absorption boosts the shell
    let boost = 1;
    const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), p = new THREE.Vector3(), sc = new THREE.Vector3();
    const fAl = s.frag.geometry.getAttribute('aAlpha');
    s.fr.forEach((f, i) => {
      const u = seg(t, f.t0, f.t0 + 0.30), e = E.outQuint(u);
      p.copy(f.start).lerp(ORB, e); p.y += Math.sin(Math.PI * e) * f.lift;
      q.setFromAxisAngle(f.ax, 2.2 * e); sc.setScalar(lerp(1, 0.2, e));
      s.frag.setMatrixAt(i, m4.compose(p, q, sc));
      fAl.setX(i, u > 0 && u < 1 ? 1 : 0);
      if (t >= f.t0 + 0.30) boost += 0.6 * (1 - seg(t, f.t0 + 0.30, f.t0 + 0.50));
    });
    s.frag.instanceMatrix.needsUpdate = true; fAl.needsUpdate = true;
    s.frag.material.uniforms.camPos.value.copy(ctx.camera.position);
    // streaming glow while tokens arrive
    boost += 0.18 * seg(t, 3.45, 3.6) * (1 - seg(t, 4.4, 4.7));
    s.orb.update(t, boost);
    // particles
    const pos = s.pts.geometry.getAttribute('position'), colA = s.pts.geometry.getAttribute('color');
    const cA = col('#FF8A3A'), cB = col('#FFC12E'), cc = new THREE.Color();
    const end = new THREE.Vector3(CARD_C.x - CARD_W / 2 + 0.05, CARD_C.y, CARD_C.z - 0.05);
    s.parts.forEach((pa, i) => {
      const u = (t - pa.b) / 0.8;
      if (u <= 0 || u >= 1 || t > 4.45 + 0.8) { pos.setXYZ(i, 0, -50, 0); colA.setXYZ(i, 0, 0, 0); return; }
      const a = new THREE.Vector3(ORB.x + 1.05, ORB.y + pa.sy * 0.8, ORB.z + 0.25 + pa.sz);
      const b = new THREE.Vector3(end.x, end.y + pa.ey * 0.9, end.z);
      const e = u;
      p.copy(a).lerp(b, e); p.y += Math.sin(Math.PI * e) * pa.arc;
      pos.setXYZ(i, p.x, p.y, p.z);
      const fade = Math.min(1, u / 0.15) * Math.min(1, (1 - u) / 0.25) * 1.8;
      cc.copy(cA).lerp(cB, pa.hue).multiplyScalar(fade);
      colA.setXYZ(i, cc.r, cc.g, cc.b);
    });
    pos.needsUpdate = true; colA.needsUpdate = true;
    // card
    const quad = cardQuad(ctx, CARD_C, -4, CARD_W, CARD_H);
    s.card.place(quad, 1);
    const toks = s.rows.flatMap((r) => r.toks);
    streamTokens(toks, TOKENS_T, t);
    const firstIdx = [0, 4, 5, 6, 7];
    s.rows.forEach((r, i) => { r.key.style.visibility = t >= TOKENS_T[firstIdx[i]] ? 'visible' : 'hidden'; });
    const lastIdx = [3, 4, 5, 6, 7];
    s.srcs.forEach((d, i) => { const a = E.outQuint(seg(t, TOKENS_T[lastIdx[i]] + 0.04, TOKENS_T[lastIdx[i]] + 0.34)); d.style.opacity = a.toFixed(3); d.style.transform = `translateX(${((1 - a) * 10).toFixed(2)}px)`; });
    toks[toks.length - 1].classList.toggle('hot', t >= 4.34 && t < 4.46);
    // tem_ref pulse 4.50 -> 4.90
    const pu = t < 4.5 ? 0 : 1 - E.outQuint(seg(t, 4.5, 4.9));
    s.pulse.style.opacity = pu.toFixed(3);
    toks[toks.length - 1].style.color = pu > 0.002 ? mixHex('#FFFFFF', '#FF6A1A', Math.min(1, pu * 1.4)) : '';
    // world label under the orb
    const op = ctx.project(ORB);
    s.llm.set(op.x, op.y + 272, t >= 3.25 ? lerp(0.4, 1, E.outQuint(seg(t, 3.25, 3.55))) : 0, op.visible);
    // title + counter
    s.title.update(t);
    s.counter.update(t, 3.30, 4.80, t >= 4.46 ? 'DONE' : 'LABELING', '1 slide → 5 labels');
  },
};
