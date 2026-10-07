// 04_verify: STEP 02. A deep diagonal queue of label chips steps through four oblique glass sheets.
// PASS chips become embedding rows; FLAG chips flip to their value, peel off and dock in the engineer's
// review panel, where each is ticked.
import { THREE, E, seg, lerp, clamp, col, S2, mulberry32, makeChip, chipCanvas, makeDecal, makeVoxels, makeCanvas, canvasTex, roundRect, trackText, FONT } from '../engine.js';
import { el, TitleBlock, Counter, WorldLabel } from '../ui.js';

const T = 5.0, TN = 7.5;
// queue: big chips in front (near the lens, lower left) -> small chips deep in the back (upper right)
const Q0 = new THREE.Vector3(S2 - 3.4, 0.9, 3.4), Q1 = new THREE.Vector3(S2 + 1.3, 2.4, -1.8);
const LP = Q0.distanceTo(Q1), DIR = Q1.clone().sub(Q0).normalize();
const SHEET_W = 1.7, SHEET_H = 2.9, SHEET_Y = 1.45, SHEET_GAP = 1.15;
const SHEET_U = [0, 1, 2, 3].map((j) => 0.40 + (j * SHEET_GAP) / LP), S_LAST = SHEET_U[3] * LP, V = 3.05, GAP = 0.72, CHIP_S = 0.88, DOCK_S = 1.0, T_LEAVE0 = 6.25;
const CHIPS = [
  ['decision', 'pending', 'flag'], ['module', 'SAUP', 'pass'], ['tem_ref', 'none', 'flag'], ['open_risk', 'TDDB', 'flag'],
  ['lot_id', 'RDM8EA.62', 'pass'], ['module', 'TiN spacer', 'pass'], ['decision', 'adopted', ''], ['tem_ref', 'APM-26-6524', ''],
  ['open_risk', 'none', ''], ['module', 'M1 Cu', ''], ['decision', 'hold', ''], ['open_risk', 'EM', ''],
];
// engineer review panel (dark glass card). Local units = world units; canvas at PPU px per unit.
const PANEL = new THREE.Vector3(S2 + 3.25, 1.55, 0.4), PANEL_YAW = (-18 * Math.PI) / 180, PW = 2.5, PH = 2.2, PPU = 340;
const SLOT_Y = [0.30, -0.20, -0.70], SLOT_H = 0.42, BOX = 0.22, DOCK_L = -PW / 2 + 0.15;
const TITLE_BAND = PH / 2 - 0.45; // nothing docks or flies above this line inside the panel
const ROW0 = new THREE.Vector3(S2 + 1.2, 3.3, -1.9), ROW_DX = 0.155, ROW_DY = 0.17, ROW_S = 1.5;
// the queue emerges at Q0 (lower left); behind it chips are faded out, and never dip under the floor
const pathPt = (s) => { const p = Q0.clone().addScaledVector(DIR, s); p.y = Math.max(p.y, 0.2); return p; };
function travelled(t) { const tau = t - 5.40; if (tau <= 0) return 0; if (tau < 0.15) return (V * tau * tau) / 0.30; return V * (tau - 0.075); }
const S0 = S_LAST - travelled(T_LEAVE0); // chip 0 leaves the last sheet at T_LEAVE0
const leaveT = (i) => T_LEAVE0 + (GAP * i) / V;
// handoff: chips start wider apart (no dense pile while the camera trucks in), settling to GAP well before T_LEAVE0
const gapAt = (t) => lerp(GAP * 1.375, GAP, E.inOutCubic(seg(t, 5.6, 6.0)));
// handoff: the whole rig starts 1.35 units left so the glass stack stays inside the frame mid-truck, then eases to rest
const rigX = (t) => -1.35 * (1 - E.inOutSine(seg(t, 5.15, 5.85)));
let st = {};

// Glass sheet: faint face with a vertical alpha gradient (top 1.6x, bottom 0.4x) + bright 1 px edges.
function makeSheet(w, h) {
  const group = new THREE.Group();
  const geo = new THREE.PlaneGeometry(w, h, 1, 1);
  const pos = geo.getAttribute('position'), rgba = new Float32Array(pos.count * 4);
  for (let i = 0; i < pos.count; i++) { const v = (pos.getY(i) + h / 2) / h; rgba.set([1, 1, 1, lerp(0.4, 1.6, v)], i * 4); }
  geo.setAttribute('color', new THREE.BufferAttribute(rgba, 4));
  const face = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color: 0xffffff, vertexColors: true, transparent: true, opacity: 0.05, depthWrite: false, side: THREE.DoubleSide }));
  const edges = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.PlaneGeometry(w, h)), new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.55, depthWrite: false }));
  group.add(face, edges);
  const cw = col('#FFFFFF'), ch = col('#F0A080'), ew = col('#FFFFFF'), eh = col('#FF7A40');
  return {
    group,
    setHot(hh) {
      face.material.color.copy(cw).lerp(ch, hh); face.material.opacity = lerp(0.05, 0.10, hh);
      edges.material.color.copy(ew).lerp(eh, hh).multiplyScalar(1 + 0.5 * hh); edges.material.opacity = lerp(0.55, 0.9, hh);
    },
  };
}

const SLOT_KEYS = ['decision', 'tem_ref', 'open_risk'], KEY_FONT = () => `500 30px ${FONT.mono}`;
const KEY_R = PW / 2 - 0.08 - 0.10 - BOX - 0.08; // right edge of the slot key label (local units)
function keyWidth(k) { const g = makeCanvas(8, 8).getContext('2d'); g.font = KEY_FONT(); return g.measureText(k).width / PPU; }
function panelCanvas(ticks) {
  const c = makeCanvas(Math.round(PW * PPU), Math.round(PH * PPU)), g = c.getContext('2d');
  const cw = c.width, mx = 0.12 * PPU;
  g.textBaseline = 'middle';
  // eyebrow-style title: orange square + tracked mono caps, count on the right
  const ty = 0.22 * PPU;
  g.fillStyle = '#FF6A1A'; g.fillRect(mx, ty - 11, 22, 22);
  g.font = `700 36px ${FONT.mono}`; g.fillStyle = '#EDEDED';
  trackText(g, 'ENGINEER REVIEW', mx + 44, ty + 1, 36 * 0.28, 'left');
  g.font = `500 32px ${FONT.mono}`; g.fillStyle = 'rgba(191,194,201,0.72)';
  trackText(g, `${ticks} / 3`, cw - mx, ty + 1, 32 * 0.12, 'right');
  g.fillStyle = 'rgba(255,255,255,0.12)'; g.fillRect(mx, 0.40 * PPU, cw - 2 * mx, 2);
  SLOT_Y.forEach((y, i) => {
    const cy = (PH / 2 - y) * PPU, h = SLOT_H * PPU, x0 = 0.08 * PPU;
    roundRect(g, x0, cy - h / 2, cw - 2 * x0, h, 18);
    g.fillStyle = 'rgba(255,255,255,0.025)'; g.fill();
    g.strokeStyle = 'rgba(255,255,255,0.18)'; g.lineWidth = 2; g.stroke();
    const sq = BOX * PPU, sx = cw - x0 - 0.10 * PPU - sq;
    g.font = KEY_FONT(); g.fillStyle = 'rgba(191,194,201,0.62)';
    trackText(g, SLOT_KEYS[i], (PW / 2 + KEY_R) * PPU, cy + 1, 0, 'right');
    roundRect(g, sx, cy - sq / 2, sq, sq, 10);
    if (i < ticks) {
      g.fillStyle = '#FF6A1A'; g.fill();
      g.strokeStyle = '#1C1E23'; g.lineWidth = 8; g.lineCap = 'round'; g.lineJoin = 'round';
      g.beginPath(); g.moveTo(sx + sq * 0.24, cy + sq * 0.02); g.lineTo(sx + sq * 0.43, cy + sq * 0.21); g.lineTo(sx + sq * 0.78, cy - sq * 0.22); g.stroke();
    } else { g.strokeStyle = 'rgba(255,255,255,0.42)'; g.lineWidth = 3; g.stroke(); }
  });
  return c;
}

const setOrder = (grp, o) => grp.traverse((m) => { m.renderOrder = o; });

export default {
  id: 'verify', start: 4.95, end: 8.15,
  setup(ctx) {
    const root = new THREE.Group();
    // glass sheets: centred on the path, yawed so they read obliquely (~50-60 deg off face-on)
    const hz = new THREE.Vector3(DIR.x, 0, DIR.z).normalize(), yaw = Math.atan2(hz.x, hz.z) - 0.35;
    const sheets = SHEET_U.map((u) => {
      const g = makeSheet(SHEET_W, SHEET_H); const p = pathPt(u * LP);
      g.group.position.set(p.x, SHEET_Y, p.z); g.group.rotation.y = yaw; root.add(g.group);
      const d = makeDecal(SHEET_W * 1.35, 0.45, 0.22); d.position.set(p.x, 0.004, p.z); d.rotation.z = yaw; root.add(d);
      return { g, s: u * LP };
    });
    // chips; FLAG chips also get a value-only twin that flips in and docks in the panel
    const chips = CHIPS.map(([k, v, o], i) => {
      const states = o === 'pass' ? ['queue', 'pass'] : ['queue'];
      const c = makeChip(k, v, states); root.add(c.group);
      let dock = null;
      let ds = DOCK_S, dh = 0;
      if (o === 'flag') {
        dock = makeChip('', v, ['flag']); root.add(dock.group); dock.set('flag', 0, 0);
        // dock as large as the slot allows: chip left edge at DOCK_L, a gap before the slot's key label
        const ti = SLOT_KEYS.indexOf(k), kw = keyWidth(SLOT_KEYS[ti]);
        ds = Math.min(DOCK_S, (KEY_R - kw - 0.08 - DOCK_L) / dock.width); dh = chipCanvas('', v, 'flag').h;
      }
      return { c, dock, ds, dh, o, i };
    });
    // embedding rows (3 PASS chips -> 3 rows of 8 cubes)
    const emb = makeVoxels(24, 0.075); root.add(emb);
    const r = mulberry32(808), eA = emb.geometry.getAttribute('aColor'), cc = new THREE.Color();
    const embData = [];
    for (let row = 0; row < 3; row++) {
      const salmon = Math.floor(r() * 8);
      for (let k = 0; k < 8; k++) {
        if (k === salmon) cc.set('#F0A080'); else cc.set('#8A8C92').lerp(col('#D2D3D7'), r());
        eA.setXYZ(row * 8 + k, cc.r, cc.g, cc.b);
        embData.push({ row, k, d: r() * 0.08, ax: new THREE.Vector3(r() - .5, r() - .5, r() - .5).normalize() });
      }
    }
    eA.needsUpdate = true;
    // engineer review panel: dark backing, 1 px edge, canvas face (title, slots, keys, checkboxes)
    const panel = new THREE.Group(); panel.position.copy(PANEL); panel.rotation.y = PANEL_YAW; root.add(panel);
    const back = new THREE.Mesh(new THREE.PlaneGeometry(PW, PH), new THREE.MeshBasicMaterial({ color: col('#1C1E23'), transparent: true, opacity: 0.86, depthWrite: false }));
    const edge = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.PlaneGeometry(PW, PH)), new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.14, depthWrite: false }));
    panel.add(back, edge);
    const ptex = [0, 1, 2, 3].map((k) => canvasTex(panelCanvas(k)));
    const pface = new THREE.Mesh(new THREE.PlaneGeometry(PW, PH), new THREE.MeshBasicMaterial({ map: ptex[0], transparent: true, depthWrite: false }));
    pface.position.z = 0.004; panel.add(pface);
    const slotHot = SLOT_Y.map((y) => {
      const m = new THREE.Mesh(new THREE.PlaneGeometry(PW - 0.16, SLOT_H), new THREE.MeshBasicMaterial({ color: col('#FF6A1A'), transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending }));
      m.position.set(0, y, 0.006); panel.add(m); return m;
    });
    back.renderOrder = 1; edge.renderOrder = 2; pface.renderOrder = 2; slotHot.forEach((m) => { m.renderOrder = 3; });
    chips.forEach(({ dock }) => { if (dock) setOrder(dock.group, 4); });
    const pdecal = makeDecal(PW * 1.2, 1.0, 0.26); pdecal.position.set(PANEL.x, 0.004, PANEL.z); pdecal.rotation.z = PANEL_YAW; root.add(pdecal);

    // overlay
    const wdom = el('div', 'scene-verify-world layer', ctx.layers.world);
    const wl = new WorldLabel(wdom, 'VERIFIER', { size: 24 });
    const tdom = el('div', 'scene-verify-title layer', ctx.layers.titles);
    const title = new TitleBlock(tdom, { eyebrow: 'STEP 02', words: [{ text: 'Self-check' }], desc: 'Doubts go to an engineer.', T, Tn: TN });
    const counter = new Counter(tdom);
    ctx.scene.add(root);
    st = { root, sheets, chips, emb, embData, panel, pface, ptex, slotHot, wl, title, counter, yaw };
    return { root, dom: [wdom, tdom] };
  },
  update(ctx, t) {
    const s = st, cam = ctx.camera.position;
    s.root.position.x = rigX(t);
    s.root.updateMatrixWorld(true);
    s.slotHot.forEach((m) => { m.material.opacity = 0; });
    const D = travelled(t);
    const hot = s.sheets.map(() => 0), bobAt = (sc) => {
      let b = 0; for (const sh of s.sheets) { const d = sc - sh.s; if (d > -0.13 && d < 0.13) b = Math.max(b, Math.sin(Math.PI * (d + 0.13) / 0.26)); } return 0.03 * b;
    };
    const flagOrder = { 0: 0, 2: 1, 3: 2 }, passOrder = { 1: 0, 4: 1, 5: 2 };
    let ticks = 0;
    const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), p = new THREE.Vector3(), sc = new THREE.Vector3();
    const embProg = [0, 0, 0], embFrom = [null, null, null];
    s.chips.forEach(({ c, dock, ds, dh, o, i }) => {
      const sPos = S0 - gapAt(t) * i + D;
      const tl = leaveT(i);
      s.sheets.forEach((sh, j) => {
        const d = sPos - sh.s;
        const h = d < 0 ? smooth01((d + 0.33) / 0.33) : 1 - clamp((d - 0.15) / 0.88);
        hot[j] = Math.max(hot[j], clamp(h));
      });
      const g = c.group;
      const billboard = (grp) => { grp.rotation.set(0, Math.atan2(cam.x - grp.position.x, cam.z - grp.position.z), 0); };
      if (t < tl || !o) {
        // queued / travelling
        g.position.copy(pathPt(sPos)); g.position.y += bobAt(sPos); billboard(g);
        g.scale.setScalar(CHIP_S);
        const fadeOut = o ? 1 : 1 - seg(sPos, S_LAST + 0.1, S_LAST + 0.5);
        const fadeIn = E.outQuad(seg(sPos, -0.45, 0.15));
        c.set('queue', fadeOut * fadeIn, 0);
        g.visible = fadeOut * fadeIn > 0.001;
        if (dock) { dock.group.visible = false; dock.set('flag', 0, 0); }
        return;
      }
      if (o === 'pass') {
        const k = seg(t, tl, tl + 0.15);
        const sp = Math.min(sPos, S_LAST + 0.3);
        g.position.copy(pathPt(sp)); billboard(g); g.scale.setScalar(CHIP_S);
        const tDis = tl + 0.3 / V;
        const op = 1 - seg(t, tDis, tDis + 0.1);
        c.set(k < 0.5 ? 'queue' : 'pass', op, 0); g.visible = op > 0.001;
        const row = passOrder[i];
        embProg[row] = seg(t, tDis, tDis + 0.30);
        embFrom[row] = pathPt(S_LAST + 0.3);
        return;
      }
      // FLAG: flip (keyed chip -> value chip with FLAG badge), then fly in panel space and dock.
      const ti = flagOrder[i], tDock = tl + 0.45;
      const kf = seg(t, tl, tl + 0.18), flipX = Math.max(0.02, Math.abs(Math.cos(Math.PI * kf)));
      const u = E.inOutCubic(seg(t, tl, tDock));
      const L = s.panel.worldToLocal(pathPt(S_LAST));
      const cw = dock.width, chH = dh;
      const P3 = new THREE.Vector3(DOCK_L + (cw * ds) / 2, SLOT_Y[ti], 0.03);
      const P2 = new THREE.Vector3(P3.x - 0.95, P3.y, 0.45);   // approach horizontally at slot height
      const P1 = new THREE.Vector3(L.x + 0.5, P3.y, L.z + 0.5);
      const a = 1 - u;
      p.copy(L).multiplyScalar(a * a * a).addScaledVector(P1, 3 * a * a * u).addScaledVector(P2, 3 * a * u * u).addScaledVector(P3, u * u * u);
      // never above the title band where the chip overlaps the panel horizontally
      const scl = lerp(CHIP_S, ds, u);
      const over = smooth01((p.x + cw * scl / 2 - (-PW / 2 - 0.2)) / 0.4);
      p.y = Math.min(p.y, TITLE_BAND - (chH * scl) / 2 + (1 - over) * 3);
      const wp = s.panel.localToWorld(p.clone());
      g.visible = kf < 0.5; dock.group.visible = kf >= 0.5;
      const yawB = Math.atan2(cam.x - wp.x, cam.z - wp.z);
      for (const grp of [g, dock.group]) {
        grp.position.copy(wp);
        grp.rotation.set(0, lerp(yawB, PANEL_YAW, u), 0);
        grp.scale.set(scl * flipX, scl, scl);
      }
      c.set('queue', 1, 0);
      const glow = kf < 0.5 ? 0 : 1 - 0.55 * seg(t, tDock, tDock + 0.5);
      dock.set('flag', 1, glow);
      if (t >= tDock + 0.10) ticks = Math.max(ticks, ti + 1);
      s.slotHot[ti].material.opacity = t >= tDock ? 0.16 * (1 - seg(t, tDock, tDock + 0.4)) : 0;
    });
    // one shared hot level for the whole stack while the conveyor runs; each sheet varies by at most 0.15
    const hotAll = Math.max(...hot);
    s.sheets.forEach((sh, j) => sh.g.setHot(clamp(0.85 * hotAll + 0.15 * hot[j])));
    s.pface.material.map = s.ptex[ticks];
    // embedding rows
    const eAl = s.emb.geometry.getAttribute('aAlpha');
    s.embData.forEach((e, idx) => {
      const pr = embProg[e.row], from = embFrom[e.row];
      const target = ROW0.clone().add(new THREE.Vector3(e.k * ROW_DX, -e.row * ROW_DY, 0));
      if (!from || pr <= 0) { eAl.setX(idx, 0); s.emb.setMatrixAt(idx, m4.makeScale(0, 0, 0)); return; }
      const u = E.outQuint(clamp((pr - e.d) / (1 - e.d)));
      const start = from.clone().add(new THREE.Vector3((e.k - 3.5) * 0.11, 0, 0));
      p.copy(start).lerp(target, u);
      q.setFromAxisAngle(e.ax, (1 - u) * 1.2); sc.setScalar(ROW_S * lerp(0.5, 1, u));
      s.emb.setMatrixAt(idx, m4.compose(p, q, sc)); eAl.setX(idx, 1);
    });
    s.emb.instanceMatrix.needsUpdate = true; eAl.needsUpdate = true;
    s.emb.material.uniforms.camPos.value.copy(cam);
    // world label above the middle of the sheet stack
    const top = pathPt((SHEET_U[1] + SHEET_U[2]) * 0.5 * LP); top.y = SHEET_Y + SHEET_H / 2 + 0.38;
    top.x += s.root.position.x;
    const pr = ctx.project(top);
    s.wl.set(pr.x, pr.y, t >= 5.75 ? lerp(0.4, 1, E.outQuint(seg(t, 5.75, 6.05))) * (1 - seg(t, 7.45, 7.6)) : 0, pr.visible);
    s.title.update(t);
    s.counter.update(t, 5.80, 7.30, 'PILOT RUN · 24 DECKS', '73 chunks → 35 flagged');
  },
};
function smooth01(x) { const u = clamp(x); return u * u * (3 - 2 * u); }
