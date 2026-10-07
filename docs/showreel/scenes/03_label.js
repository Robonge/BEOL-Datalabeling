// 03_label: STEP 01. The LLM orb takes in slide fragments and streams five labels into a card.
import { THREE, E, seg, lerp, clamp, col, S1, W, H, mulberry32, makeOrb, makeDecal, makeVoxels, cameraAt } from '../engine.js';
import { el, TitleBlock, Counter, WorldLabel, Card, cardQuad, streamTokens, mixHex } from '../ui.js';

const T = 2.5, TN = 5.0;
const ORB = new THREE.Vector3(S1 - 2.28, 1.44, 0);
const CARD_C = new THREE.Vector3(S1 + 1.64, 1.41, 0.3), CARD_W = 864 / 178, CARD_H = 372 / 178;
// beats: fragments 2.80 (+0.035 stagger, 0.38 s flights) -> tokens 3.15..3.85 (0.10 s pitch) -> DONE 3.95
// -> tem_ref pulse 4.05..4.45 -> provenance column 4.20..4.50 -> static card -> fade 4.98..5.16 (outQuad) inside the 4.95 truck
const TOKENS_T = [3.15, 3.25, 3.35, 3.45, 3.55, 3.65, 3.75, 3.85];
const T_DONE = 3.95, T_PULSE = 4.05, T_SRC = 4.20, FLIGHT = 0.38;
const P_BIRTH0 = 3.08, P_BIRTHS = 0.58, P_LIFE = 0.42;
let st = {};
// scene CSS: denser card body (28/48 mono, matches the reference card fill)
const CSS = '.scene-label-card .card .cbody { margin-top: 26px; font: 500 28px/48px var(--mono); }'
  + '.scene-label-world .wlabel { color: #EDEDED; }'
  + '.scene-label-card .csrc { position: absolute; right: -0.22em; top: -5px; font: 700 16px/48px var(--mono); letter-spacing: 0.22em; color: rgba(191, 194, 201, 0.46); text-transform: uppercase; }'
  + '.scene-label-card .csrc i { font-style: normal; font-size: 21px; color: rgba(191, 194, 201, 0.46); margin-right: 12px; letter-spacing: 0; vertical-align: -1px; }';
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
    const frag = makeVoxels(6, 0.34); root.add(frag);
    const fc = ['#DCDDE2', '#D4D5DA', '#8F9197', '#5E6066', '#B3B5BB', '#FF6A1A'];
    const fA = frag.geometry.getAttribute('aColor'), r = mulberry32(303), c = new THREE.Color();
    // each fragment starts in frame (x 180..320 px, y 420..600 px, under the title band) as seen by the camera at
    // its own launch time; the whip is still settling at 2.80, so the start is unprojected through cameraAt(t0)
    const cam = new THREE.PerspectiveCamera(32, W / H, 0.1, 200), dir = new THREE.Vector3();
    const fr = fc.map((h, i) => { c.set(h); fA.setXYZ(i, c.r, c.g, c.b);
      const t0 = 2.80 + i * 0.035, sx = 180 + r() * 140, sy = 420 + r() * 180, sz = 0.4 + r() * 1.0;
      const k = cameraAt(t0); cam.position.copy(k.pos); cam.lookAt(k.target); cam.updateMatrixWorld();
      dir.set((sx / W) * 2 - 1, 1 - (sy / H) * 2, 0.5).unproject(cam).sub(cam.position);
      const start = cam.position.clone().addScaledVector(dir, (sz - cam.position.z) / dir.z);
      return { start, lift: 0.12 + r() * 0.16, ax: new THREE.Vector3(r() - .5, r() - .5, r() - .5).normalize(), t0 }; });
    fA.needsUpdate = true;
    // particle stream orb -> card
    const PN = 50, pp = new Float32Array(PN * 3), pc = new Float32Array(PN * 3);
    const pg = new THREE.BufferGeometry(); pg.setAttribute('position', new THREE.BufferAttribute(pp, 3)); pg.setAttribute('color', new THREE.BufferAttribute(pc, 3));
    const pts = new THREE.Points(pg, new THREE.PointsMaterial({ size: 3, sizeAttenuation: false, vertexColors: true, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false }));
    pts.frustumCulled = false; root.add(pts);
    const pr = mulberry32(77);
    const parts = Array.from({ length: PN }, (_, i) => ({ b: P_BIRTH0 + (i / PN) * P_BIRTHS + pr() * 0.04, sy: (pr() - 0.5) * 1.1, sz: (pr() - 0.5) * 0.6, ey: (pr() - 0.5) * 1.3, arc: 0.15 + pr() * 0.35, hue: pr(), sz2: pr() }));

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
    // provenance: which slide region each label was read from (right column, fades in once after DONE)
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
      const u = seg(t, f.t0, f.t0 + FLIGHT), e = E.outQuint(u);
      p.copy(f.start).lerp(ORB, e); p.y += Math.sin(Math.PI * e) * f.lift;
      q.setFromAxisAngle(f.ax, 2.2 * e); sc.setScalar(lerp(1, 0.2, e));
      s.frag.setMatrixAt(i, m4.compose(p, q, sc));
      fAl.setX(i, u > 0 && u < 1 ? 1 : 0);
      if (t >= f.t0 + FLIGHT) boost += 0.6 * (1 - seg(t, f.t0 + FLIGHT, f.t0 + FLIGHT + 0.20));
    });
    s.frag.instanceMatrix.needsUpdate = true; fAl.needsUpdate = true;
    s.frag.material.uniforms.camPos.value.copy(ctx.camera.position);
    // streaming glow while tokens arrive
    boost += 0.18 * seg(t, 3.08, 3.23) * (1 - seg(t, 3.85, 4.15));
    s.orb.update(t, boost);
    // particles
    const pos = s.pts.geometry.getAttribute('position'), colA = s.pts.geometry.getAttribute('color');
    const cA = col('#FF8A3A'), cB = col('#FFC12E'), cc = new THREE.Color();
    const end = new THREE.Vector3(CARD_C.x - CARD_W / 2 + 0.05, CARD_C.y, CARD_C.z - 0.05);
    // fast launch off the orb, decelerating into the card's left edge (births 3.08 -> 3.70, stream gone by about 4.1)
    const LIFE = P_LIFE;
    s.parts.forEach((pa, i) => {
      const u = (t - pa.b) / LIFE;
      if (u <= 0 || u >= 1) { pos.setXYZ(i, 0, -50, 0); colA.setXYZ(i, 0, 0, 0); return; }
      const a = new THREE.Vector3(ORB.x + 1.05, ORB.y + pa.sy * 0.8, ORB.z + 0.25 + pa.sz);
      const b = new THREE.Vector3(end.x, end.y + pa.ey * 0.9, end.z);
      const e = E.outCubic(u);
      p.copy(a).lerp(b, e); p.y += Math.sin(Math.PI * e) * pa.arc;
      pos.setXYZ(i, p.x, p.y, p.z);
      // quick pop-in at launch; dim out while settling against the card
      const fade = Math.min(1, u / 0.06) * Math.min(1, (1 - u) / 0.35) * 1.8;
      cc.copy(cA).lerp(cB, pa.hue).multiplyScalar(fade);
      colA.setXYZ(i, cc.r, cc.g, cc.b);
    });
    pos.needsUpdate = true; colA.needsUpdate = true;
    // card
    const quad = cardQuad(ctx, CARD_C, -4, CARD_W, CARD_H);
    // front-loaded exit inside the truck: the DOM card (always above WebGL) drops fast while it still slides left,
    // under 25% by 5.10 and gone by 5.16, so the VERIFY chips never repeat its values next to it
    s.card.place(quad, 1 - E.outQuad(seg(t, 4.98, 5.16)));
    const toks = s.rows.flatMap((r) => r.toks);
    streamTokens(toks, TOKENS_T, t);
    const firstIdx = [0, 4, 5, 6, 7];
    s.rows.forEach((r, i) => { r.key.style.visibility = t >= TOKENS_T[firstIdx[i]] ? 'visible' : 'hidden'; });
    // provenance column: one fade for the whole column once the pulse has spent itself (one card animation at a time)
    const sa = E.outQuint(seg(t, T_SRC, T_SRC + 0.30));
    s.srcs.forEach((d) => { d.style.opacity = sa.toFixed(3); d.style.transform = `translateX(${((1 - sa) * 10).toFixed(2)}px)`; });
    // the last token stays orange from landing into the pulse (no white blink between the two)
    toks[toks.length - 1].classList.toggle('hot', t >= TOKENS_T[TOKENS_T.length - 1] && t < T_PULSE);
    // tem_ref pulse 4.05 -> 4.45
    const pu = t < T_PULSE ? 0 : 1 - E.outQuint(seg(t, T_PULSE, T_PULSE + 0.40));
    s.pulse.style.opacity = pu.toFixed(3);
    toks[toks.length - 1].style.color = pu > 0.002 ? mixHex('#FFFFFF', '#FF6A1A', Math.min(1, pu * 1.4)) : '';
    // world label under the orb
    const op = ctx.project(ORB);
    s.llm.set(op.x, op.y + 272, t >= 3.25 ? lerp(0.4, 1, E.outQuint(seg(t, 3.25, 3.55))) : 0, op.visible);
    // title + counter
    s.title.update(t);
    s.counter.update(t, 3.10, 4.80, t >= T_DONE ? 'DONE' : 'LABELING', '1 slide → 5 labels');
  },
};
