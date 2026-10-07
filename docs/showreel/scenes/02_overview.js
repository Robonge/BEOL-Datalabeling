// 02_overview: crane-up to the whole pipeline: 5 plinths, blazing ground rings, thick glowing arcs,
// a comet packet hopping SLIDE -> LABEL -> VERIFY -> LEARN -> VAULT, then the whip.
import { THREE, E, seg, lerp, clamp, smoothstep, col, mulberry32, makeDecal, makeOrb, makeGlass, makeChip, makeVoxels, FONT } from '../engine.js';
import { el, Eyebrow, MaskedLine } from '../ui.js';

const XS = [-9.2, -4.6, 0.0, 4.6, 9.2];
const LAND = [1.50, 1.75, 2.00, 2.25, 2.50];
const NAMES = [['', 'SLIDE'], ['01', 'LABEL'], ['02', 'VERIFY'], ['03', 'LEARN'], ['04', 'VAULT']];
let st = {};

function makePlinth() {
  const g = new THREE.Group();
  const top = new THREE.MeshBasicMaterial({ color: col('#2A2B30') }), side = new THREE.MeshBasicMaterial({ color: col('#202126') });
  const box = new THREE.Mesh(new THREE.BoxGeometry(3.0, 0.12, 2.2), [side, side, top, side, side, side]);
  box.position.y = 0.06; g.add(box);
  const P = (x, y, z) => new THREE.Vector3(x, y, z);
  const orange = new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints([P(-1.5, 0.0, 1.1), P(1.5, 0.0, 1.1), P(1.5, 0.0, 1.1), P(1.5, 0.0, -1.1)]),
    new THREE.LineBasicMaterial({ color: col('#FF6A1A').multiplyScalar(1.5), transparent: true, opacity: 0.9 }));
  const white = new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints([
    P(-1.5, 0.12, 1.1), P(1.5, 0.12, 1.1), P(1.5, 0.12, 1.1), P(1.5, 0.12, -1.1), P(1.5, 0.12, -1.1), P(-1.5, 0.12, -1.1), P(-1.5, 0.12, -1.1), P(-1.5, 0.12, 1.1)]),
    new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.20 }));
  g.add(orange, white);
  const d = makeDecal(3.0 * 1.25, 2.2 * 1.25, 0.25); g.add(d);
  return g;
}
const arcMat = () => new THREE.ShaderMaterial({
  uniforms: { color: { value: col('#FF6A1A') }, level: { value: 0 } },
  vertexShader: `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }`,
  fragmentShader: `uniform vec3 color; uniform float level; varying vec2 vUv;
    void main(){ float a = smoothstep(0.0, 0.12, vUv.x) * smoothstep(1.0, 0.88, vUv.x); gl_FragColor = vec4(color * level * a, 1.0); }`,
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
export function ringLevel(i, t) {
  const L = LAND[i], N = LAND[i + 1];
  if (t < L) return { level: 0, scale: 0.85 };
  const u = E.outQuint(seg(t, L, L + 0.3));
  let level = lerp(3.6, 2.4, u);
  if (N != null && t > N) level = lerp(2.4, 0.35, E.outCubic(seg(t, N, N + 0.6)));
  return { level, scale: lerp(0.85, 1.0, u) };
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
      g.add(back, ms, ed); g.rotation.x = -0.21; g.position.set(XS[0], 0.12 + 0.55 + 0.45, 0); root.add(g); heroes.push({ g, boost: (b) => { ms.material.color.setScalar(lerp(1, 1.12, b - 1)); } });
    }
    {
      const orb = makeOrb({ core: 0.22, shell: 0.6, atmos: 0.9, orbiters: 4, ringR: [0.82, 0.95], detail: 2 });
      orb.group.position.set(XS[1], 0.12 + 0.55 + 0.6, 0); root.add(orb.group);
      heroes.push({ g: orb.group, orb, boost: (b) => orb.update(ctx.t, b) });
    }
    {
      const g = new THREE.Group(); const gl = [];
      for (let k = 0; k < 3; k++) { const gs = makeGlass(0.55, 0.95); gs.group.position.set(-0.3 + k * 0.3, 0, 0); gs.group.rotation.y = 1.05; g.add(gs.group); gl.push(gs); }
      const chipsTxt = [['', 'module'], ['', 'lot_id'], ['', 'risk'], ['', 'tem']];
      chipsTxt.forEach(([k, v], i) => { const c = makeChip(k, v); c.set('queue'); c.group.scale.setScalar(0.42); c.group.position.set(-0.75 + i * 0.4, -0.3 + i * 0.18, 0.15 - i * 0.12); g.add(c.group); });
      g.position.set(XS[2], 0.12 + 0.55 + 0.48, 0); root.add(g);
      heroes.push({ g, boost: (b) => gl.forEach((s) => s.setHot(clamp((b - 1) / 0.8) * 0.8)) });
    }
    {
      const g = new THREE.Group();
      const ring = new THREE.Mesh(new THREE.TorusGeometry(0.6, 0.012, 8, 120), new THREE.MeshBasicMaterial({ color: col('#E8893A').multiplyScalar(3), blending: THREE.AdditiveBlending, transparent: true, depthWrite: false }));
      ring.rotation.x = -Math.PI / 2 + (38 * Math.PI) / 180; g.add(ring);
      const dot = new THREE.Mesh(new THREE.SphereGeometry(0.045, 12, 8), new THREE.MeshBasicMaterial({ color: new THREE.Color(2.6, 2.6, 2.6) })); g.add(dot);
      g.position.set(XS[3], 0.12 + 0.55 + 0.35, 0); root.add(g);
      heroes.push({ g, ring, dot, boost: (b) => ring.material.color.copy(col('#E8893A')).multiplyScalar(3 * b) });
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
      heroes.push({ g: vx, boost: (b) => { vx.material.uniforms.lit.value = 1; vx.material.uniforms.camPos.value.copy(ctx.camera.position); } });
    }
    // overlay
    const dom = el('div', 'scene-overview layer', ctx.layers.world);
    const labels = NAMES.map(([n, w]) => { const d = el('div', 'floorlabel', dom); if (n) { el('span', 'n', d, n); d.appendChild(document.createTextNode('  ')); } el('span', 'w', d, w); return d; });
    const tdom = el('div', 'scene-overview-t layer', ctx.layers.titles);
    const eyebrow = new Eyebrow(tdom, 'THE WHOLE PIPELINE', { capTop: 114, align: 'center' });
    // section title (STYLE §3 "Section title (centered)"): 58 px, centered, cap-top 162, under the eyebrow
    const headline = new MaskedLine(tdom, [{ text: 'Everything' }, { text: 'in' }, { text: 'between.' }],
      { size: 58, weight: 700, tracking: -0.02, capTop: 162, align: 'center' });
    ctx.scene.add(root);
    st = { root, rings, arcs, hops, packet, pcore, pglow, trail, heroes, labels, eyebrow, headline, dom, tdom };
    return { root, dom: [dom, tdom] };
  },
  update(ctx, t) {
    const s = st;
    // rings
    s.rings.forEach((m, i) => { const { level, scale } = ringLevel(i, t); m.visible = level > 0.001; m.material.color.copy(col('#FF8A3A')).multiplyScalar(level); m.scale.setScalar(scale); });
    // arcs ramp in 1.50 -> 1.80
    const ar = E.outCubic(seg(t, 1.5, 1.8)) * 2.1;
    s.arcs.forEach((m) => { m.material.uniforms.level.value = ar; m.visible = ar > 0.001; });
    // packet
    const posAt = (tt) => {
      if (tt < 1.5) return null;
      const h = Math.min(3, Math.floor((tt - 1.5) / 0.25));
      const u = tt >= 2.5 ? 1 : E.inOutSine(clamp((tt - 1.5 - h * 0.25) / 0.25));
      return s.hops[h].getPointAt(u);
    };
    const p = posAt(t);
    s.packet.visible = !!p;
    if (p) s.packet.position.copy(p);
    s.trail.forEach((sp, k0) => {
      const k = k0 + 1, q = posAt(t - 0.02 * k);
      sp.visible = !!q && t < 2.55;
      if (q) { sp.position.copy(q); sp.scale.setScalar(0.62 * Math.pow(0.9, k)); sp.material.opacity = 0.55 * Math.pow(0.78, k); }
    });
    // heroes: landing boost x1.8 decaying over 0.3 s
    s.heroes.forEach((h, i) => {
      const b = 1 + 0.8 * (t >= LAND[i] ? 1 - E.outQuad(seg(t, LAND[i], LAND[i] + 0.3)) : 0);
      h.boost(b);
      if (h.orb) h.orb.update(t, b);
      if (h.dot) { const a = t * 1.4; h.dot.position.set(Math.cos(a) * 0.6, Math.sin(a) * 0.6 * Math.sin((38 * Math.PI) / 180), Math.sin(a) * 0.6 * Math.cos((38 * Math.PI) / 180)); }
    });
    // floor labels
    const v = new THREE.Vector3();
    s.labels.forEach((d, i) => {
      v.set(XS[i], 2.15, -0.9);
      // labels ride down through the frame during the crane: keep them out of the headline band (y < ~230)
      const pr = ctx.project(v), o = seg(t, 1.55 + i * 0.03, 1.75 + i * 0.03) * smoothstep(236, 266, pr.y);
      const ok = pr.visible && o > 0 && pr.x > -200 && pr.x < 2120;
      d.style.display = ok ? '' : 'none';
      if (ok) { d.style.opacity = o.toFixed(3); d.style.transform = `translate(${Math.round(pr.x)}px, ${Math.round(pr.y - 11)}px) translateX(-50%)`; }
    });
    // section card: eyebrow in 1.62 -> 1.80, words rise on the LABEL landing (1.75, 8th), settled ~2.0;
    // out on the whip beat (2.50, mask-up), gone by 2.75 when STEP 01 rises
    s.eyebrow.set(seg(t, 1.62, 1.80) * (1 - seg(t, 2.50, 2.62)));
    s.headline.set(t, { riseAt: 1.75, riseDur: 0.45, stagger: 0.05, from: 110, exitAt: 2.50, exitDur: 0.20, exitStagger: 0.03 });
  },
};
