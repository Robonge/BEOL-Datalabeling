// 05_learn: STEP 03. The agent asks, the engineer answers, the answer becomes a rule (a new ring).
// Hero orb on the left; a tilted Q/A orbit carries a comet out to the engineer node and back.
import { THREE, E, seg, lerp, clamp, col, S3, makeOrb, makeChip, makeDecal, makeCanvas, canvasTex, trackText, roundRect, FONT } from '../engine.js';
import { el, TitleBlock, WorldLabel, Card, cardQuad, streamTokens } from '../ui.js';

const T = 7.5, TN = 10.0;
const ORB = new THREE.Vector3(S3 - 2.5, 1.44, 0);
const OA = 2.25, OB = 0.78, TILT = (62 * Math.PI) / 180, ROLL = (9 * Math.PI) / 180;           // Q/A orbit: semi-axes and tilt from flat
const CARD_PX = { w: 680, h: 286 }, CARD_C = new THREE.Vector3(S3 + 2.78, 1.50, 0.3);
const CARD_W = CARD_PX.w / 178, CARD_H = CARD_PX.h / 178;
const EW = 1.1, EH = 0.8, EPX = 400, ES = 0.85;                       // engineer node (world units, canvas px/unit, scale)
// orbit hidden inside the engineer panel: |phi| below GATE_A is fully gated, above GATE_B fully drawn
const GATE_A = 0.28, GATE_B = 0.40;
// engineer node sits just in front of the orbit's right extreme (orbit = tilt about x, then roll about z)
const ENG = new THREE.Vector3(OA, 0, 0).applyEuler(new THREE.Euler(TILT, 0, ROLL, 'ZYX')).add(ORB).add(new THREE.Vector3(0, 0, 0.2));
const TAU = Math.PI * 2;
let st = {};

// closed ellipse in the local xz plane; u = 0 at the agent-side (left) extreme
class Ellipse3 extends THREE.Curve {
  constructor(a, b) { super(); this.a = a; this.b = b; }
  getPoint(u, target = new THREE.Vector3()) { const p = Math.PI + 2 * Math.PI * u; return target.set(this.a * Math.cos(p), 0, this.b * Math.sin(p)); }
}
// orbit line: far half (local z < 0, behind the orb) dims to 25%, near half full; gated where it enters the engineer panel
function orbitMat(color) {
  return new THREE.ShaderMaterial({
    uniforms: { color: { value: color }, opacity: { value: 1 } },
    vertexShader: 'varying float vZ; varying float vU; void main(){ vZ = position.z; vU = uv.x; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
    fragmentShader: `uniform vec3 color; uniform float opacity; varying float vZ; varying float vU;
      void main(){ float depth = mix(0.25, 1.0, smoothstep(-0.3, 0.3, vZ / ${OB.toFixed(3)}));
        float gate = smoothstep(${GATE_A.toFixed(3)}, ${GATE_B.toFixed(3)}, abs(vU - 0.5) * 6.2831853);
        gl_FragColor = vec4(color, depth * gate * opacity); }`,
    transparent: true, blending: THREE.AdditiveBlending, depthWrite: false,
  });
}
// comet angle on the orbit (0 = engineer, PI = agent side); Q over the far arc, A back over the near arc
function phiAt(t) {
  if (t < 8.0) { const d = Math.min(8.0 - t, 0.8); return Math.PI - 0.55 * d * d; }
  if (t < 8.45) return Math.PI + Math.PI * E.inOutCubic(seg(t, 8.0, 8.45));
  if (t < 8.5) return 2 * Math.PI;
  if (t < 8.95) return 2 * Math.PI + Math.PI * E.inOutCubic(seg(t, 8.5, 8.95));
  const tau = t - 8.95;
  return 3 * Math.PI + (tau < 0.5 ? 1.2 * tau * tau : 1.2 * (tau - 0.25));
}

// engineer node face: a miniature of the DOM content card (dark fill, gradient hairline, inset), lit orange while hot
function drawEngineer(g, w, h, state, dots, hot) {
  g.clearRect(0, 0, w, h);
  const r = 40, bw = 6;
  const border = g.createLinearGradient(0, 0, 0, h);
  border.addColorStop(0, `rgb(${Math.round(92 + 163 * hot)},${Math.round(95 + 27 * hot)},${Math.round(102 - 38 * hot)})`);
  border.addColorStop(1, `rgb(${Math.round(72 + 183 * hot)},${Math.round(75 + 31 * hot)},${Math.round(82 - 26 * hot)})`);
  roundRect(g, 0, 0, w, h, r); g.fillStyle = border; g.fill();
  roundRect(g, bw, bw, w - 2 * bw, h - 2 * bw, r - bw); g.fillStyle = '#20232A'; g.fill();
  roundRect(g, bw + 8, bw + 8, w - 2 * bw - 16, h - 2 * bw - 16, r - bw - 8);
  g.fillStyle = `rgba(${Math.round(38 + 14 * hot)},${Math.round(39 + 4 * hot)},44,1)`; g.fill();
  g.textBaseline = 'middle';
  // header: orange square + tracked white title, centred as a group
  g.font = `700 44px ${FONT.mono}`;
  const tt = 44 * 0.24, tw = g.measureText('ENGINEER').width + 7 * tt, sq = 22, gx = w / 2 - (sq + 22 + tw) / 2;
  g.fillStyle = '#FF6A1A'; g.fillRect(gx, 77 - sq / 2, sq, sq);
  g.fillStyle = '#F2F2F2'; trackText(g, 'ENGINEER', gx + sq + 22, 78, tt, 'left');
  g.fillStyle = 'rgba(255,255,255,0.14)'; g.fillRect(40, 128, w - 80, 2);
  const cy = 216;
  if (state === 0) {
    g.font = `600 40px ${FONT.mono}`; g.fillStyle = 'rgba(191,194,201,0.70)';
    trackText(g, 'STANDBY', w / 2, cy, 40 * 0.18, 'center');
  } else if (state === 1) {
    for (let i = 0; i < 3; i++) {
      g.beginPath(); g.arc(w / 2 + (i - 1) * 54, cy, 14, 0, Math.PI * 2);
      g.fillStyle = i === dots ? '#FF6A1A' : 'rgba(237,237,237,0.5)'; g.fill();
    }
  } else {
    const label = 'ANSWERED';
    g.font = `700 40px ${FONT.mono}`;
    const lt = 40 * 0.12, lw = g.measureText(label).width + (label.length - 1) * lt, gw = 42, x0 = w / 2 - (lw + gw + 16) / 2;
    g.strokeStyle = '#FF6A1A'; g.lineWidth = 8; g.lineCap = 'round'; g.lineJoin = 'round';
    g.beginPath(); g.moveTo(x0 + 3, cy + 1); g.lineTo(x0 + 15, cy + 14); g.lineTo(x0 + gw, cy - 15); g.stroke();
    g.fillStyle = '#F2F2F2';
    trackText(g, label, x0 + gw + 16, cy + 2, lt, 'left');
  }
}

export default {
  id: 'learn', start: 7.45, end: 10.65,
  setup(ctx) {
    const root = new THREE.Group();
    // hero agent orb (same build as the LABEL orb, slightly smaller)
    const agent = makeOrb({ core: 0.34, shell: 0.95, atmos: 2.2, orbiters: 6, detail: 1, ringR: [1.34, 1.54], seed: 11 });
    agent.group.position.copy(ORB); root.add(agent.group);
    const decal = makeDecal(3.6, 2.2, 0.32); decal.position.set(ORB.x, 0.004, 0.2); root.add(decal);
    // Q/A orbit, tilted 62 degrees from the floor so it passes behind the orb (far arc) and in front (near arc)
    const ringG = new THREE.Group(); ringG.position.copy(ORB); ringG.rotation.set(TILT, 0, ROLL, 'ZYX'); root.add(ringG);
    const curve = new Ellipse3(OA, OB);
    const ringGeo = new THREE.TubeGeometry(curve, 400, 0.010, 8, true);
    const ringMat = orbitMat(col('#E8893A').multiplyScalar(1.1));
    const ring = new THREE.Mesh(ringGeo, ringMat); ringG.add(ring);
    const ringCount = ringGeo.index.count;
    // the rule ring born from the answer
    const ring2Mat = orbitMat(col('#FF6A1A')); ring2Mat.uniforms.opacity.value = 0;
    const ring2 = new THREE.Mesh(new THREE.TubeGeometry(curve, 400, 0.008, 8, true), ring2Mat); ringG.add(ring2);
    // comet: hot head and glow sprite; its tail is the shader trail below
    const glowMap = agent.atm.material.map;
    const comet = new THREE.Group(); root.add(comet);
    const head = new THREE.Mesh(new THREE.SphereGeometry(0.05, 20, 14), new THREE.MeshBasicMaterial({ color: col('#FFC79A').multiplyScalar(2.0) }));
    const halo = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowMap, color: col('#FF6A1A').multiplyScalar(1.6), transparent: true, opacity: 0.9, blending: THREE.AdditiveBlending, depthWrite: false }));
    halo.scale.setScalar(0.62);
    comet.add(halo, head);
    // continuous tail: a thicker tube on the same curve, lit only just behind the head (uv.x = curve u)
    const trailMat = new THREE.ShaderMaterial({
      uniforms: { head: { value: 0 }, len: { value: 0.02 }, amt: { value: 0 }, cHot: { value: col('#FFB070').multiplyScalar(2.2) }, cTail: { value: col('#FF6A1A').multiplyScalar(0.9) } },
      vertexShader: 'varying float vU; varying float vZ; void main(){ vU = uv.x; vZ = position.z; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
      fragmentShader: `uniform float head, len, amt; uniform vec3 cHot, cTail; varying float vU; varying float vZ;
        void main(){ float d = fract(head - vU + 1.0); if (d > len) discard; float k = 1.0 - d / len;
          float gate = smoothstep(${GATE_A.toFixed(3)}, ${GATE_B.toFixed(3)}, abs(vU - 0.5) * 6.2831853);
          float depth = mix(0.55, 1.0, smoothstep(-0.3, 0.3, vZ / ${OB.toFixed(3)}));
          gl_FragColor = vec4(mix(cTail, cHot, k * k) * k * k * amt * gate * depth, 1.0); }`,
      transparent: true, blending: THREE.AdditiveBlending, depthWrite: false,
    });
    const trail = new THREE.Mesh(new THREE.TubeGeometry(curve, 720, 0.019, 8, true), trailMat); ringG.add(trail);
    // engineer node: a canvas-drawn mini card; status reads STANDBY / typing dots / ANSWERED; a soft halo pulses as Q lands
    const eng = new THREE.Group(); eng.position.copy(ENG); eng.rotation.y = (-6 * Math.PI) / 180; eng.scale.setScalar(ES); root.add(eng);
    const ehalo = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowMap, color: col('#FF6A1A'), transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false }));
    ehalo.scale.set(EW * 2.0, EH * 2.4, 1); ehalo.position.z = -0.03; eng.add(ehalo);
    const ec = makeCanvas(Math.round(EW * EPX), Math.round(EH * EPX)), etex = canvasTex(ec, false);
    const eface = new THREE.Mesh(new THREE.PlaneGeometry(EW, EH), new THREE.MeshBasicMaterial({ map: etex, transparent: true, depthWrite: false }));
    eng.add(eface);
    const edecal = makeDecal(1.5 * ES, 0.9 * ES, 0.28); edecal.position.set(ENG.x, 0.004, ENG.z); root.add(edecal);
    // key tags carried by the comet
    const qChip = makeChip('', 'Q', ['queue']); root.add(qChip.group);
    const aChip = makeChip('', 'A', ['queue']); root.add(aChip.group);
    // overlay
    const cardDom = el('div', 'scene-learn-card layer', ctx.layers.cards);
    const card = new Card(cardDom, 'DOMAIN-ENGR-BOT', CARD_PX);
    const rows = card.setRows([
      { key: 'Q', tokens: ['Why', 'is', 'TDDB', 'pending?'] },
      { key: 'A', tokens: ['TDDB', 'not', 'run'], gapAfter: 18 },
      { key: '+', tokens: ['RULE', 'TDDB', 'open', '→', 'pending'], cls: ['acc', '', '', '', ''] },
    ], 4);
    const wdom = el('div', 'scene-learn-world layer', ctx.layers.world);
    const wa = new WorldLabel(wdom, 'AGENT', { size: 15 });
    const tdom = el('div', 'scene-learn-title layer', ctx.layers.titles);
    const title = new TitleBlock(tdom, { eyebrow: 'STEP 03', words: [{ text: 'Agents' }, { text: 'ask' }, { text: 'engineers' }], desc: 'Answers become rules.', T, Tn: TN });
    ctx.scene.add(root);
    st = { root, ringG, ring, ringGeo, ringCount, ringMat, ring2, ring2Mat, agent, comet, head, halo, trail, eng, ehalo, ec, etex, qChip, aChip, card, rows, wa, title, lastKey: '' };
    return { root, dom: [cardDom, wdom, tdom] };
  },
  update(ctx, t) {
    const s = st, cam = ctx.camera.position;
    s.root.updateMatrixWorld(true);
    // RULE: agent flare + rule-ring birth at 9.00
    const flare = t >= 9.0 ? 1 - E.outQuad(seg(t, 9.0, 9.35)) : 0;
    s.agent.update(t, 1 + flare * 0.9);
    // orbit draws on from the agent side while the camera trucks in
    const draw = E.outCubic(seg(t, 7.62, 8.05));
    const n = Math.floor((draw * s.ringCount) / 3) * 3;
    s.ringGeo.setDrawRange(0, n); s.ring.visible = n > 0;
    s.ringMat.uniforms.color.value.copy(col('#E8893A')).multiplyScalar(1.1 * (1 + 0.6 * flare));
    const rb = E.outQuint(seg(t, 9.0, 9.6));
    s.ring2.scale.setScalar(lerp(1.0, 1.12, rb)); s.ring2Mat.uniforms.opacity.value = 0.6 * rb; s.ring2.visible = rb > 0;
    s.ring2Mat.uniforms.color.value.copy(col('#FF6A1A')).multiplyScalar(1.1 * (1 + 0.8 * flare));
    // comet
    const onOrbit = (phi, out = new THREE.Vector3()) => s.ringG.localToWorld(out.set(OA * Math.cos(phi), 0, OB * Math.sin(phi)));
    const cOn = E.outCubic(seg(t, 7.85, 8.05));
    const ph = phiAt(t);
    onOrbit(ph, s.comet.position);
    s.comet.visible = cOn > 0.001;
    // the head slips behind the engineer panel at phi = 0 (mod 2pi); fade it there instead of ghosting through the glass
    const dEng = Math.abs(((ph % TAU) + TAU + Math.PI) % TAU - Math.PI);
    const hv = cOn * E.inOutSine(clamp((dEng - GATE_A + 0.04) / (GATE_B - GATE_A + 0.04)));
    const hd = lerp(0.55, 1, E.inOutSine(clamp((Math.sin(ph) + 0.3) / 0.6)));   // dimmer on the far arc
    s.halo.material.opacity = 0.9 * hv * hd * (1 + 0.4 * flare);
    s.head.scale.setScalar(Math.max(hv, 0.001)); s.head.visible = hv > 0.01;
    const tm = s.trail.material.uniforms, speed = Math.abs(ph - phiAt(t - 0.05)) / 0.05 / TAU; // loops per second
    tm.head.value = ((((ph - Math.PI) / TAU) % 1) + 1) % 1;
    tm.len.value = clamp(0.035 + speed * 0.075, 0.035, 0.30);
    tm.amt.value = cOn; s.trail.visible = cOn > 0.001;
    // key tags ride just above the comet head
    const place = (chip, op) => {
      const g = chip.group; g.position.copy(s.comet.position).add(new THREE.Vector3(0, 0.24, 0));
      g.rotation.set(0, Math.atan2(cam.x - g.position.x, cam.z - g.position.z), 0); g.scale.setScalar(0.74);
      chip.set('queue', op); g.visible = op > 0.001;
    };
    place(s.qChip, t < 8.0 ? 0 : E.outCubic(seg(t, 8.0, 8.1)) * (1 - seg(t, 8.22, 8.30)));   // gone before the head enters the panel
    place(s.aChip, t < 8.66 ? 0 : E.outCubic(seg(t, 8.66, 8.76)) * (1 - seg(t, 8.9, 9.0)));
    // engineer node: lights as Q lands, types 8.47 -> 8.66, then ANSWERED
    const hot = seg(t, 8.36, 8.45) * (1 - seg(t, 8.7, 9.1));
    s.ehalo.material.opacity = 0.55 * hot;
    const state = t < 8.47 ? 0 : t < 8.66 ? 1 : 2;
    const dots = state === 1 ? Math.floor((t - 8.47) / 0.065) % 3 : -1;
    const hq = Math.round(hot * 12) / 12;                           // quantised so the canvas redraws only on visible steps
    const key = `${state}|${dots}|${hq}`;
    if (key !== s.lastKey) {
      s.lastKey = key;
      drawEngineer(s.ec.getContext('2d'), s.ec.width, s.ec.height, state, dots, hq);
      s.etex.needsUpdate = true;
    }
    // card
    s.card.place(cardQuad(ctx, CARD_C, -4, CARD_W, CARD_H), 1);
    const [r0, r1, r2] = s.rows;
    r0.key.style.visibility = t >= 7.85 ? 'visible' : 'hidden';
    r1.key.style.visibility = t >= 8.42 ? 'visible' : 'hidden';
    r2.key.style.visibility = t >= 9.0 ? 'visible' : 'hidden';
    streamTokens(r0.toks, [7.85, 7.95, 8.05, 8.15], t);
    streamTokens(r1.toks, [8.44, 8.52, 8.60], t);
    streamTokens(r2.toks, [9.10, 9.20, 9.30, 9.40, 9.50], t);
    r2.toks[4].classList.toggle('hot', t >= 9.5 && t < 9.62);
    // world label under the orb
    const a = ctx.project(ORB);
    const wo = t >= 7.9 ? lerp(0.4, 1, E.outQuint(seg(t, 7.9, 8.2))) * (1 - seg(t, 9.95, 10.1)) : 0;
    s.wa.set(a.x, a.y + 214, wo, a.visible);
    s.title.update(t);
  },
};
