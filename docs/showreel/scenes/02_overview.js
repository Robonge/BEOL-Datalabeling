// 02_overview: crane-up to the whole pipeline: 5 plinths, blazing ground rings, thick glowing arcs,
// a comet packet hopping SLIDE -> LABEL -> VERIFY -> LEARN -> VAULT, then the whip.
import { THREE, E, seg, lerp, clamp, smoothstep, col, mulberry32, makeDecal, makeOrb, makeGlass, makeChip, makeVoxels, FONT } from '../engine.js';
import { el, Eyebrow, MaskedLine } from '../ui.js';

const XS = [-9.2, -4.6, 0.0, 4.6, 9.2];
const LAND = [1.50, 1.75, 2.00, 2.25, 2.50];
const NAMES = [['', 'SLIDE'], ['01', 'LABEL'], ['02', 'VERIFY'], ['03', 'LEARN'], ['04', 'VAULT']];
// build-in: each plinth grows 0.12 s ahead of the packet's landing. SLIDE waits for the shatter (1.50), so the
// overview set never shares the frame with the hook slab while it pixelates; the whole set is also held at
// opacity 0 until 1.50 and faded up 1.50 -> 1.70 (outQuad, SET_IN).
const T_IN = LAND.map((L, i) => (i === 0 ? 1.50 : L - 0.12));
const SET_IN = (t) => E.outQuad(seg(t, 1.50, 1.70));
const GROW = 0.30, STAG = 0.05;
const back12 = (x) => E.outBack(x, 1.2);
// u in [0,1] of a plinth's (or a sub-part's) build; d delays a sub-part left to right
const growU = (t, i, d = 0) => seg(t, T_IN[i] + d, T_IN[i] + d + GROW);
// packet hop easing: carry ~65% speed through each landing; ease in from rest at launch, ease out to park
const hopEase = (u, h) => {
  if (h === 0) { const v = 1 - u; return 1 - (0.65 * v + 1.7 * v * v - 1.35 * v * v * v); }
  if (h === 3) return 0.65 * u + 1.7 * u * u - 1.35 * u * u * u;
  return 0.65 * u + 0.35 * E.inOutSine(u);
};
let st = {};

function makePlinth() {
  const g = new THREE.Group();
  // the body fades in with its build, so it is always transparent (one shader program whatever the seek order).
  // renderOrder -4 draws it after the floor grid (-900) and its decal (-5) but before rings/arcs (0): once it
  // is solid and writes depth it occludes exactly as an opaque slab would.
  const body = (c) => new THREE.MeshBasicMaterial({ color: col(c), transparent: true, depthWrite: false, opacity: 0 });
  const top = body('#2A2B30'), side = body('#202126');
  const box = new THREE.Mesh(new THREE.BoxGeometry(3.0, 0.12, 2.2), [side, side, top, side, side, side]);
  box.position.y = 0.06; box.renderOrder = -4; g.add(box);
  const P = (x, y, z) => new THREE.Vector3(x, y, z);
  const orange = new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints([P(-1.5, 0.0, 1.1), P(1.5, 0.0, 1.1), P(1.5, 0.0, 1.1), P(1.5, 0.0, -1.1)]),
    new THREE.LineBasicMaterial({ color: col('#FF6A1A').multiplyScalar(1.5), transparent: true, opacity: 0.9 }));
  const white = new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints([
    P(-1.5, 0.12, 1.1), P(1.5, 0.12, 1.1), P(1.5, 0.12, 1.1), P(1.5, 0.12, -1.1), P(1.5, 0.12, -1.1), P(-1.5, 0.12, -1.1), P(-1.5, 0.12, -1.1), P(-1.5, 0.12, 1.1)]),
    new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.20 }));
  g.add(orange, white);
  const d = makeDecal(3.0 * 1.25, 2.2 * 1.25, 0.25); g.add(d);
  g.userData = { box, top, side, orange, white, decal: d };
  return g;
}
const arcMat = () => new THREE.ShaderMaterial({
  uniforms: { color: { value: col('#FF6A1A') }, level: { value: 0 }, reveal: { value: 1 } },
  vertexShader: `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }`,
  // reveal: the arc draws itself from its left plinth toward the next one (soft, slightly hot leading edge)
  fragmentShader: `uniform vec3 color; uniform float level; uniform float reveal; varying vec2 vUv;
    void main(){ float a = smoothstep(0.0, 0.12, vUv.x) * smoothstep(1.0, 0.88, vUv.x);
      float r = reveal * 1.1;  float m = 1.0 - smoothstep(r - 0.1, r, vUv.x);
      float head = 1.0 + 0.8 * smoothstep(r - 0.14, r - 0.04, vUv.x) * m * (1.0 - step(1.0, reveal));
      gl_FragColor = vec4(color * level * a * m * head, 1.0); }`,
  transparent: true, blending: THREE.AdditiveBlending, depthWrite: false,
});
function arcCurve(i) {
  const xa = XS[i] + 1.5, xb = XS[i + 1] - 1.5, xm = (xa + xb) / 2, a = (xb - xa) / 2;
  const pts = [];
  for (let k = 0; k <= 40; k++) { const th = Math.PI - (k / 40) * Math.PI; pts.push(new THREE.Vector3(xm + a * Math.cos(th), 0.12 + 0.78 * Math.sin(th), 0)); }
  return new THREE.CatmullRomCurve3(pts);
}
function hopCurve(i) {
  const pts = [new THREE.Vector3(XS[i], 0.30, 0), new THREE.Vector3(XS[i] + 0.9, 0.24, 0)];
  const ac = arcCurve(i);
  for (let k = 0; k <= 20; k++) { const p = ac.getPoint(k / 20); pts.push(new THREE.Vector3(p.x, p.y + 0.02, p.z)); }
  pts.push(new THREE.Vector3(XS[i + 1] - 0.9, 0.24, 0), new THREE.Vector3(XS[i + 1], 0.30, 0));
  return new THREE.CatmullRomCurve3(pts, false, 'centripetal');
}
// SLIDE's ring flares late (1.60): until the hook headline has cleared (gone 1.58) it only glows at a low
// simmer, so the white 108 px line never sits on yellow-white bloom.
const RING0_SIMMER = 0.55, RING0_FLARE = 1.60;
export function ringLevel(i, t) {
  const L = LAND[i], N = LAND[i + 1];
  if (t < L) return { level: 0, scale: 0.85 };
  if (i === 0 && t < RING0_FLARE) {
    const w = E.outQuad(seg(t, L, RING0_FLARE));
    return { level: RING0_SIMMER * w, scale: lerp(0.85, 0.9, w) };
  }
  const F = i === 0 ? RING0_FLARE : L, u = E.outQuint(seg(t, F, F + 0.3));
  let level = lerp(3.6, 2.4, u);
  if (N != null && t > N) level = lerp(2.4, 0.35, E.outCubic(seg(t, N, N + 0.6)));
  return { level, scale: lerp(i === 0 ? 0.9 : 0.85, 1.0, u) };
}

export default {
  id: 'overview', start: 1.40, end: 2.80,
  setup(ctx) {
    const root = new THREE.Group();
    const plinths = XS.map((x) => { const p = makePlinth(); p.position.x = x; root.add(p); return p; });
    // ground rings
    const ringGeo = new THREE.TorusGeometry(2.0, 0.04, 12, 200);
    const rings = XS.map((x) => {
      const m = new THREE.Mesh(ringGeo, new THREE.MeshBasicMaterial({ color: col('#FF8A3A'), transparent: true, blending: THREE.AdditiveBlending, depthWrite: false }));
      m.rotation.x = -Math.PI / 2; m.position.set(x, 0.02, 0); root.add(m); return m;
    });
    // arcs
    const arcs = [0, 1, 2, 3].map((i) => { const m = new THREE.Mesh(new THREE.TubeGeometry(arcCurve(i), 80, 0.06, 12, false), arcMat()); root.add(m); return m; });
    const hops = [0, 1, 2, 3].map(hopCurve);
    // packet + comet trail
    const glowTex = ctx.assets.glowTex || (ctx.assets.glowTex = (() => {
      const c = document.createElement('canvas'); c.width = c.height = 128; const g = c.getContext('2d');
      const gr = g.createRadialGradient(64, 64, 0, 64, 64, 64);
      gr.addColorStop(0, 'rgba(255,255,255,1)'); gr.addColorStop(0.3, 'rgba(255,255,255,0.45)'); gr.addColorStop(1, 'rgba(255,255,255,0)');
      g.fillStyle = gr; g.fillRect(0, 0, 128, 128); const tx = new THREE.CanvasTexture(c); tx.colorSpace = THREE.SRGBColorSpace; return tx;
    })());
    const packet = new THREE.Group();
    const pcore = new THREE.Mesh(new THREE.SphereGeometry(0.12, 24, 16), new THREE.MeshBasicMaterial({ color: col('#FFF35A').multiplyScalar(2.6) }));
    const pglow = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex, color: col('#FF6A1A').multiplyScalar(1.5), blending: THREE.AdditiveBlending, depthWrite: false, transparent: true }));
    pcore.material.transparent = true;
    pglow.scale.setScalar(1.3); packet.add(pglow, pcore); root.add(packet);
    const trail = [];
    for (let k = 1; k <= 10; k++) {
      const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex, color: col('#FFB060').multiplyScalar(2.0), blending: THREE.AdditiveBlending, depthWrite: false, transparent: true }));
      root.add(s); trail.push(s);
    }
    // mini heroes
    const heroes = [];
    {
      const g = new THREE.Group();
      const ms = new THREE.Mesh(new THREE.PlaneGeometry(1.6, 0.9), new THREE.MeshBasicMaterial({ map: ctx.assets.slideTex }));
      const back = new THREE.Mesh(new THREE.BoxGeometry(1.6, 0.9, 0.02), new THREE.MeshBasicMaterial({ color: col('#1B1C20') })); back.position.z = -0.012;
      const ed = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.PlaneGeometry(1.6, 0.9)), new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.45 }));
      g.add(back, ms, ed); g.rotation.x = -0.21; g.position.set(XS[0], 0.12 + 0.55 + 0.45, 0); root.add(g);
      const fades = [[ms.material, 1], [back.material, 1], [ed.material, 0.45]];
      fades.forEach(([m]) => { m.transparent = true; });
      heroes.push({ g, boost: (b) => { ms.material.color.setScalar(lerp(1, 1.12, b - 1)); },
        fade: (t, a) => fades.forEach(([m, o]) => { m.opacity = o * a; }) });
    }
    {
      const orb = makeOrb({ core: 0.22, shell: 0.6, atmos: 0.9, orbiters: 4, ringR: [0.82, 0.95], detail: 2 });
      orb.group.position.set(XS[1], 0.12 + 0.55 + 0.6, 0); root.add(orb.group);
      const glows = [[orb.atm.material, orb.atm.material.opacity], [orb.fill.material, orb.fill.material.opacity], [orb.corona.material, orb.corona.material.opacity]];
      heroes.push({ g: orb.group, orb, boost: (b) => orb.update(ctx.t, b),
        // the orb's glow (and its bloom) is held dark until 1.62, then ramps outQuad over 0.2 s
        fade: (t, a) => {
          const o = a * E.outQuad(seg(t, 1.62, 1.82));
          glows.forEach(([m, base]) => { m.opacity = base * o; });
          orb.wireMat.opacity *= o; orb.coreMat.uniforms.gain.value *= o; orb.core.visible = o > 0.02;
        } });
    }
    {
      const g = new THREE.Group(); const gl = [];
      for (let k = 0; k < 3; k++) { const gs = makeGlass(0.55, 0.95); gs.group.position.set(-0.3 + k * 0.3, 0, 0); gs.group.rotation.y = 1.05; g.add(gs.group); gl.push(gs); }
      const chipsTxt = [['', 'module'], ['', 'lot_id'], ['', 'risk'], ['', 'tem']];
      const chips = chipsTxt.map(([k, v], i) => { const c = makeChip(k, v); c.set('queue'); c.group.scale.setScalar(0.42); c.group.position.set(-0.75 + i * 0.4, -0.3 + i * 0.18, 0.15 - i * 0.12); g.add(c.group); return c; });
      g.position.set(XS[2], 0.12 + 0.55 + 0.48, 0); root.add(g);
      let hot = 0;
      heroes.push({ g, boost: (b) => { hot = clamp((b - 1) / 0.8) * 0.8; },
        // sheets then chips fill in left to right, STAG apart
        fade: (t) => {
          gl.forEach((s, k) => s.setHot(hot, clamp(growU(t, 2, k * STAG) * 1.6)));
          chips.forEach((c, k) => { const u = growU(t, 2, (k + 1) * STAG); c.set('queue', clamp(u * 1.6)); c.group.scale.setScalar(0.42 * lerp(0.6, 1, back12(u))); });
        } });
    }
    {
      const g = new THREE.Group();
      const ring = new THREE.Mesh(new THREE.TorusGeometry(0.6, 0.012, 8, 120), new THREE.MeshBasicMaterial({ color: col('#E8893A').multiplyScalar(3), blending: THREE.AdditiveBlending, transparent: true, depthWrite: false }));
      ring.rotation.x = -Math.PI / 2 + (38 * Math.PI) / 180; g.add(ring);
      const dot = new THREE.Mesh(new THREE.SphereGeometry(0.045, 12, 8), new THREE.MeshBasicMaterial({ color: new THREE.Color(2.6, 2.6, 2.6) })); g.add(dot);
      g.position.set(XS[3], 0.12 + 0.55 + 0.35, 0); root.add(g);
      dot.material.transparent = true;
      heroes.push({ g, ring, dot, boost: (b) => ring.material.color.copy(col('#E8893A')).multiplyScalar(3 * b),
        fade: (t, a) => { ring.material.opacity = a; dot.material.opacity = a; } });
    }
    {
      const vx = makeVoxels(9 * 4 * 3, 0.11); const cA = vx.geometry.getAttribute('aColor'); const r = mulberry32(55);
      const m4 = new THREE.Matrix4(); let i = 0; const c = new THREE.Color();
      for (let z = 0; z < 3; z++) for (let y = 0; y < 4; y++) for (let x = 0; x < 9; x++) {
        m4.makeTranslation((x - 4) * 0.125, y * 0.125, (z - 1) * 0.125); vx.setMatrixAt(i, m4);
        const v = r(); c.set(v < 0.1 ? '#FF6A1A' : v < 0.16 ? '#2A2A2E' : '#8A8C92').lerp(col('#D2D3D7'), v < 0.16 ? 0 : r() * 0.8);
        cA.setXYZ(i, c.r, c.g, c.b); i++;
      }
      vx.position.set(XS[4], 0.12 + 0.3, 0); root.add(vx);
      // cubes stack in column by column, left to right (stagger spread over STAG * 2)
      const vm = new THREE.Matrix4(), vs = new THREE.Vector3(), vq = new THREE.Quaternion(), vp = new THREE.Vector3();
      heroes.push({ g: vx, boost: (b) => { vx.material.uniforms.lit.value = 1; vx.material.uniforms.camPos.value.copy(ctx.camera.position); },
        scaleSelf: true,
        fade: (t) => {
          let n = 0;
          for (let z = 0; z < 3; z++) for (let y = 0; y < 4; y++) for (let x = 0; x < 9; x++) {
            const u = growU(t, 4, (x / 8) * STAG * 2 + y * 0.012), k = Math.max(1e-4, back12(u));
            vp.set((x - 4) * 0.125, y * 0.125 * k, (z - 1) * 0.125); vs.setScalar(k);
            vm.compose(vp, vq, vs); vx.setMatrixAt(n++, vm);
          }
          vx.instanceMatrix.needsUpdate = true;
        } });
    }
    // overlay
    const dom = el('div', 'scene-overview layer', ctx.layers.world);
    const labels = NAMES.map(([n, w]) => { const d = el('div', 'floorlabel', dom); if (n) { el('span', 'n', d, n); d.appendChild(document.createTextNode('  ')); } el('span', 'w', d, w); return d; });
    const tdom = el('div', 'scene-overview-t layer', ctx.layers.titles);
    // soft backing for the headline band: an ellipse 900x260 px centred (960, 175), charcoal 0.55 -> 0, so the
    // first readable frames never sit on the bare voxel mosaic of the shattering hook slab
    const scrim = el('div', '', tdom);
    Object.assign(scrim.style, { position: 'absolute', left: '0px', top: '0px', width: '1920px', height: '1080px', pointerEvents: 'none',
      background: 'radial-gradient(ellipse 450px 130px at 960px 175px, rgba(30, 31, 35, 0.55) 0%, rgba(30, 31, 35, 0.42) 40%, rgba(30, 31, 35, 0.16) 75%, rgba(30, 31, 35, 0) 100%)' });
    const eyebrow = new Eyebrow(tdom, 'THE WHOLE PIPELINE', { capTop: 114, align: 'center' });
    // section title (STYLE §3 "Section title (centered)"): 58 px, centered, cap-top 162, under the eyebrow
    const headline = new MaskedLine(tdom, [{ text: 'Everything' }, { text: 'in' }, { text: 'between.' }],
      { size: 58, weight: 700, tracking: -0.02, capTop: 162, align: 'center' });
    ctx.scene.add(root);
    st = { root, plinths, rings, arcs, hops, packet, pcore, pglow, trail, heroes, labels, eyebrow, headline, scrim, dom, tdom };
    return { root, dom: [dom, tdom] };
  },
  update(ctx, t) {
    const s = st;
    // plinth build-in: the slab rises from the floor (scale y, outBack 1.2) and spreads its footprint
    // (0.6 -> 1, same overshoot) while the body fades up over the first third and its edge lines and decal follow
    const setA = SET_IN(t);
    const base = s.plinths.map((p, i) => {
      const u = growU(t, i), a = clamp(u * 2.5) * setA, d = p.userData, k = back12(u), xz = lerp(0.6, 1, k);
      p.visible = u > 0;
      p.scale.set(xz, Math.max(1e-3, k), xz);
      const bodyA = clamp(u * 3) * setA, solid = bodyA > 0.95;
      for (const m of [d.top, d.side]) { m.opacity = bodyA; m.depthWrite = solid; }
      d.orange.material.opacity = 0.9 * a; d.white.material.opacity = 0.20 * a; d.decal.material.opacity = 0.25 * a;
      return u;
    });
    // rings
    s.rings.forEach((m, i) => { const { level, scale } = ringLevel(i, t); m.visible = level > 0.001; m.material.color.copy(col('#FF8A3A')).multiplyScalar(level * setA); m.scale.setScalar(scale); });
    // arcs draw out of each plinth just ahead of the packet (LAND[i]-0.10 -> +0.12), so the road
    // reaches the next plinth as it rises (T_IN[i+1]); full level as in the approved look once drawn
    s.arcs.forEach((m, i) => {
      const r = E.outCubic(seg(t, Math.max(1.52, LAND[i] - 0.10), LAND[i] + 0.12));
      const lv = 2.1 * clamp(r * 4) * setA;
      m.material.uniforms.reveal.value = r; m.material.uniforms.level.value = lv; m.visible = lv > 0.001;
    });
    // packet
    const posAt = (tt) => {
      if (tt < 1.5) return null;
      const h = Math.min(3, Math.floor((tt - 1.5) / 0.25));
      const u = tt >= 2.5 ? 1 : hopEase(clamp((tt - 1.5 - h * 0.25) / 0.25), h);
      return s.hops[h].getPointAt(u);
    };
    const p = posAt(t);
    s.packet.visible = !!p && setA > 0.001;
    s.pglow.material.opacity = setA; s.pcore.material.opacity = setA;
    if (p) s.packet.position.copy(p);
    s.trail.forEach((sp, k0) => {
      const k = k0 + 1, q = posAt(t - 0.02 * k);
      const fo = 1 - E.inOutSine(seg(t, 2.50, 2.60));  // trail fades as the packet parks, instead of a hard cut
      sp.visible = !!q && fo > 0.001;
      if (q) { sp.position.copy(q); sp.scale.setScalar(0.62 * Math.pow(0.9, k)); sp.material.opacity = 0.55 * Math.pow(0.78, k) * fo * setA; }
    });
    // heroes: landing boost x1.8 decaying over 0.3 s
    s.heroes.forEach((h, i) => {
      const b = 1 + 0.8 * (t >= LAND[i] ? 1 - E.outQuad(seg(t, LAND[i], LAND[i] + 0.3)) : 0);
      h.boost(b);
      if (h.orb) h.orb.update(t, b);
      // hero builds with its plinth: opacity 0 -> 1 plus a small outBack scale (0.6 -> 1)
      const u = base[i], a = clamp(u * 2.5) * setA;
      h.g.visible = u > 0 && setA > 0.001;
      if (!h.scaleSelf) h.g.scale.setScalar(lerp(0.6, 1, back12(u)));
      if (h.fade) h.fade(t, a);
      if (h.dot) { const a = t * 1.4; h.dot.position.set(Math.cos(a) * 0.6, Math.sin(a) * 0.6 * Math.sin((38 * Math.PI) / 180), Math.sin(a) * 0.6 * Math.cos((38 * Math.PI) / 180)); }
    });
    // floor labels
    const v = new THREE.Vector3();
    s.labels.forEach((d, i) => {
      v.set(XS[i], 2.15, -0.9);
      // labels ride down through the frame during the crane: keep them out of the headline band (y < ~230)
      // a label never shows over an empty spot: it waits for its plinth's build. They hold back until the
      // headline has settled (2.15 -> 2.35, 70%), so "Everything in between." is the only text read first.
      const pr = ctx.project(v), o = 0.7 * seg(t, 2.15 + i * 0.02, 2.35 + i * 0.02) * smoothstep(236, 266, pr.y) * clamp(base[i] * 2.5);
      const ok = pr.visible && o > 0 && pr.x > -200 && pr.x < 2120;
      d.style.display = ok ? '' : 'none';
      if (ok) { d.style.opacity = o.toFixed(3); d.style.transform = `translate(${Math.round(pr.x)}px, ${Math.round(pr.y - 11)}px) translateX(-50%)`; }
    });
    // section card: rises only after the hook line has cleared (hook exit 1.38 -> 1.58), over a scrim faded up
    // 1.55 -> 1.70. Eyebrow 1.58 -> 1.72 (outQuad); words rise from 1.62 (0.30 s outExpo, 0.025 stagger, settled
    // ~1.97) and then hold at 100% through the packet's run and the whip. No animated exit: the 2.75 hard cut
    // (camera C3 -> C4) is the exit, so the line reads settled for ~0.78 s with nothing else written.
    const cut = t >= 2.75;
    s.tdom.style.display = cut ? 'none' : s.tdom.style.display;
    if (cut) return;
    const sa = E.outQuad(seg(t, 1.55, 1.70));
    s.scrim.style.opacity = sa.toFixed(3); s.scrim.style.display = sa > 0.001 ? '' : 'none';
    s.eyebrow.set(E.outQuad(seg(t, 1.58, 1.72)));
    s.headline.set(t, { riseAt: 1.62, riseDur: 0.30, stagger: 0.025, from: 110 });
  },
};
