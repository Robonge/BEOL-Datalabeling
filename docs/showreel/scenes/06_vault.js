// 06_vault: STEP 04. 1,296 noisy voxels (a warm mid-tone ellipsoid cloud) resolve into an ordered block,
// the vector DB. The block's front and top faces carry the slide (false-colored), so the vault visibly
// holds it. Hero cubes and links light up. In the close the same cubes fly into a 48x27 wall = the slide.
import { THREE, E, seg, lerp, clamp, col, S4, mulberry32, makeVoxels, makeDecal, cameraAt } from '../engine.js';
import { el, TitleBlock, Counter, WorldLabel } from '../ui.js';

const T = 10.0, TN = 12.5;
// 18 x 9 x 8 = 1,296 cubes (same count as the 48 x 27 slide wall); a deep block so its top face reads
const NX = 18, NY = 9, NZ = 8, N = NX * NY * NZ, PITCH = 0.23, CUBE = 0.207;
const BC = new THREE.Vector3(S4 + 0.30, 1.40, 0);
const HALF = new THREE.Vector3(NX * PITCH / 2, NY * PITCH / 2, NZ * PITCH / 2);
const WALL_C = new THREE.Vector3(S4, 1.96, 0), WP = 0.1125, WCUBE = 0.101;
const HEROES = [{ ix: 7, iz: 6, label: 'RDM8EA.62' }, { ix: 12, iz: 7, label: 'TiN spacer' }, { ix: 2, iz: 4, label: 'CMBSRP 100%' }, { ix: 16, iz: 3, label: 'APM-…6524' }];
const LINKS = [[0, 1], [0, 2], [1, 3]];
const YAW = -0.42;
// the block is seen from ~25 deg above: whatever elevation the camera track gives, the block pitches
// toward the camera for the rest (so a raised camera in the engine and this tilt never double up)
const VIEW_ELEV = 0.44, MAX_PITCH = 0.30;
// screen boxes the noise cloud must stay out of (title block, counter box), px at 1920x1080
// (the VECTOR DB label's box sits under the block, see VDB_DY)
const KEEP_OUT = [[90, 90, 760, 400], [1330, 820, 1830, 950], [830, 870, 1010, 900]];
// the noise cloud floats: its center rises LIFT world units during 10.0-10.9 (no flat bottom on the floor)
const LIFT = 0.35;
const liftAt = (t) => LIFT * E.inOutSine(seg(t, 10.0, 10.9));
// feed stream: NSTREAM outliers start on a ribbon running to screen (1500, 250) and fly in from 10.3; the
// near end lands by 10.55, the far end leaves at 10.70 and lands by 10.97, just before stream cubes start to resolve
const NSTREAM = 60, STREAM_PX = [1500, 250];
// resolve clock: 0 -> 1.35 (max delay 1.0 + 0.35 ramp) over 10.5-11.35, so the block stands early and the hero
// labels get ~0.75 s fully readable before the close
const ssAt = (t) => 1.35 * E.inOutSine(seg(t, 10.5, 11.35));
// hero beat: cubes pulse and links draw 11.20-11.45 (staggered), labels resolve 11.30-11.55, all out at 12.30-12.45
const HERO_T0 = 11.20, HERO_STAG = 0.04;
// hero label backing pill padding (px); VECTOR DB sits under the block like LLM and AGENT under their orbs
// (out of the title band): its cap band is centred VDB_DY px below the floor point under the block centre
const PILL_PX = 6, PILL_PY = 3, VDB_DY = 98;
// noise drift: velocity eases out from 10.0 and reaches zero at 11.5, under the resolve (no freeze at 10.5)
const driftAt = (t) => 0.9 * E.outSine(seg(t, 10.0, 11.5));
// false-color ramp for the slide on the block (sRGB): slate teal -> mauve -> terracotta -> orange -> peach
const RAMP = [[0.00, '#26363C'], [0.20, '#3F5C60'], [0.40, '#7C6A68'], [0.60, '#B9735A'], [0.78, '#DC8452'], [0.92, '#F2C29E'], [1.00, '#F8DDC6']];
let st = {};
const Y_AXIS = new THREE.Vector3(0, 1, 0), X_AXIS = new THREE.Vector3(1, 0, 0);

function ramp(u) {
  for (let k = 1; k < RAMP.length; k++) {
    if (u <= RAMP[k][0]) {
      const a = RAMP[k - 1], b = RAMP[k];
      return col(a[1]).lerp(col(b[1]), (u - a[0]) / (b[0] - a[0]));
    }
  }
  return col(RAMP[RAMP.length - 1][1]);
}
function lum(hex) {
  const f = (v) => { v /= 255; return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
  return 0.2126 * f((hex >> 16) & 255) + 0.7152 * f((hex >> 8) & 255) + 0.0722 * f(hex & 255);
}

export default {
  id: 'vault', start: 9.95, end: 15.0,
  setup(ctx) {
    const root = new THREE.Group();
    const vox = makeVoxels(N, CUBE); vox.material.transparent = false; root.add(vox);
    const r = mulberry32(2024);

    // block orientation: yaw, then pitch toward the camera (adaptive to the camera track's elevation)
    const camC = cameraAt(11.2);
    const elev = Math.atan2(camC.pos.y - BC.y, Math.hypot(camC.pos.x - BC.x, camC.pos.z - BC.z));
    const PITCHA = clamp(VIEW_ELEV - elev, 0, MAX_PITCH);
    const qB = new THREE.Quaternion().setFromAxisAngle(X_AXIS, PITCHA).multiply(new THREE.Quaternion().setFromAxisAngle(Y_AXIS, YAW));

    // slide -> block surface: unfold top (NZ rows, back to front) + front (NY rows, top to bottom) = 17 rows
    // over the slide's 27 rows; box-average the cells, then rank-normalize so the ramp is used evenly
    const cells = ctx.assets.slideCells, cellAt = new Map();
    cells.forEach((c) => cellAt.set(c.cy * 48 + c.cx, c));
    const UR = NZ + NY, surf = [];
    for (let row = 0; row < UR; row++) for (let ix = 0; ix < NX; ix++) {
      const x0 = Math.floor(ix * 48 / NX), x1 = Math.max(x0 + 1, Math.floor((ix + 1) * 48 / NX));
      const y0 = Math.floor(row * 27 / UR), y1 = Math.max(y0 + 1, Math.floor((row + 1) * 27 / UR));
      let s = 0, n = 0;
      for (let cy = y0; cy < y1; cy++) for (let cx = x0; cx < x1; cx++) { const c = cellAt.get(cy * 48 + cx); if (c) { s += lum(c.hex); n++; } }
      surf.push({ row, ix, l: n ? s / n : 0 });
    }
    const ranked = surf.slice().sort((a, b) => (a.l - b.l) || (a.row - b.row) || (a.ix - b.ix));
    ranked.forEach((p, k) => { p.u = k / (ranked.length - 1); });
    const surfColor = surf.map((p) => {
      const band = 1 + 0.04 * Math.sin(p.row * 1.7 + 0.6);
      return ramp(clamp(0.06 + 0.90 * p.u)).multiplyScalar(band);
    });

    // noise palette (sRGB): mid-tone warm gray / pink / brown, sparse burnt accent, a few darks
    const nGray = col('#5E5A5C'), nLight = col('#A0918E'), nAcc = col('#D8652F').multiplyScalar(0.8), nWarm = col('#C28472'), nDark = col('#2A2A2E');

    // projection at the key poses, to keep the cloud out of the title and counter boxes
    const pcam = ctx.camera.clone();
    const poses = [10.85, 11.1, 11.4].map((tt) => ({ ...cameraAt(tt), t: tt }));
    const blocked = (w) => poses.some((pc) => {
      pcam.position.copy(pc.pos); pcam.lookAt(pc.target); pcam.updateMatrixWorld(); pcam.updateProjectionMatrix();
      const v = w.clone().setY(w.y + liftAt(pc.t)).project(pcam), x = (v.x + 1) * 960, y = (1 - v.y) * 540;
      return KEEP_OUT.some(([a, b, c, d]) => x > a - 20 && x < c + 20 && y > b - 20 && y < d + 20);
    });

    const data = [];
    const tmp = new THREE.Vector3();
    const nc0 = new THREE.Vector3(BC.x - 0.05, BC.y + 0.06, BC.z);
    for (let iz = 0; iz < NZ; iz++) for (let iy = 0; iy < NY; iy++) for (let ix = 0; ix < NX; ix++) {
      // resolved: a ragged grid (small x/y jitter, a little front-back stagger), rotated by qB about BC
      tmp.set((ix - (NX - 1) / 2) * PITCH + (r() - 0.5) * 0.05, (iy - (NY - 1) / 2) * PITCH + (r() - 0.5) * 0.04, (iz - (NZ - 1) / 2) * PITCH + (r() - 0.5) * 0.08);
      const res = tmp.clone().applyQuaternion(qB).add(BC);
      // noise: soft ellipsoid (semi-axes 0.95 / 1.0 / 1.6 of the block's half size: a rounder blob than the
      // block, like the reference's), 12% outliers out to 1.6x
      const th = r() * Math.PI * 2, cz = r() * 2 - 1, sz = Math.sqrt(1 - cz * cz);
      const outlier = r() < 0.12;
      let rad = outlier ? lerp(1.0, 1.6, r()) : Math.pow(r(), 0.45);
      const dir = new THREE.Vector3(sz * Math.cos(th) * 0.95 * HALF.x, cz * 1.0 * HALF.y, sz * Math.sin(th) * 1.6 * HALF.z);
      let nz = nc0.clone().addScaledVector(dir, rad);
      for (let k = 0; k < 8 && (blocked(nz) || nz.y + LIFT < 0.30); k++) { rad *= 0.82; nz = nc0.clone().addScaledVector(dir, rad); }
      const roll = r();
      const nc = roll < 0.06 ? nAcc.clone() : roll < 0.18 ? nWarm.clone().multiplyScalar(0.85 + 0.15 * r())
        : roll < 0.24 ? nDark.clone() : nGray.clone().lerp(nLight, Math.pow(r(), 0.8)).lerp(nWarm, 0.18 * r());
      // resolved color: top layer from the top rows of the unfolded slide, everything else from the front
      // rows (extruded back, 4% darker per layer so the side faces read as depth)
      const top = iy === NY - 1;
      const sIdx = top ? iz * NX + ix : (NZ + (NY - 1 - iy)) * NX + ix;
      const rc = surfColor[sIdx].clone().multiplyScalar((top ? 1 : Math.pow(0.96, NZ - 1 - iz)) * (0.95 + 0.10 * r()));
      // resolve delay: mostly random, slightly center-first, so the whole volume sharpens together
      // (not built up from the floor)
      const dn = Math.hypot((ix - (NX - 1) / 2) / ((NX - 1) / 2), (iy - (NY - 1) / 2) / ((NY - 1) / 2), (iz - (NZ - 1) / 2) / ((NZ - 1) / 2)) / Math.sqrt(3);
      const d = 0.55 * r() + 0.45 * dn;
      data.push({ ix, iy, iz, res, nz, nc, rc, d, outlier, stream: null, jit: (r() - 0.5) * 0.18, jax: new THREE.Vector3(r() - .5, r() - .5, r() - .5).normalize(), ax: new THREE.Vector3(r() - .5, r() - .5, r() - .5).normalize(), rot: (r() - 0.5) * 5, vel: new THREE.Vector3((r() - .5) * 0.08, (r() - .5) * 0.05, (r() - .5) * 0.08), nscale: lerp(0.62, 0.92, r()), hero: -1 });
    }
    // feed stream: the NSTREAM outliers lying furthest toward the stream's screen anchor start on a ribbon
    // that runs from the cloud's edge out to that anchor (world point at the cloud's depth, pose 10.75)
    const sp = cameraAt(10.75);
    pcam.position.copy(sp.pos); pcam.lookAt(sp.target); pcam.updateMatrixWorld(); pcam.updateProjectionMatrix();
    const ray = new THREE.Vector3(STREAM_PX[0] / 960 - 1, 1 - STREAM_PX[1] / 540, 0.5).unproject(pcam).sub(sp.pos).normalize();
    const cl = nc0.clone().setY(nc0.y + LIFT);
    const W = sp.pos.clone().addScaledVector(ray, sp.pos.distanceTo(cl));
    const sdir = W.clone().sub(cl).normalize();
    const E0 = cl.clone().addScaledVector(sdir, HALF.x * 1.35);
    const side = new THREE.Vector3().crossVectors(sdir, ray).normalize(), lift3 = new THREE.Vector3().crossVectors(side, sdir).normalize();
    const cand = data.filter((v) => v.outlier).sort((a, b) => b.nz.clone().sub(nc0).dot(sdir) - a.nz.clone().sub(nc0).dot(sdir)).slice(0, NSTREAM);
    cand.forEach((v, k) => {
      const s = (k + r()) / NSTREAM;
      const w = 0.06 + 0.16 * s;
      const start = E0.clone().lerp(W, s).addScaledVector(side, (r() - 0.5) * 2 * w).addScaledVector(lift3, (r() - 0.5) * 1.2 * w);
      v.stream = { s, start };
      v.d = Math.max(v.d, 0.86); // resolve starts ~11.0, after the far end has landed (10.97)
    });
    const stream = data.filter((v) => v.stream);
    HEROES.forEach((h, k) => { const idx = h.iz * NX * NY + (NY - 1) * NX + h.ix; data[idx].hero = k; data[idx].d = 0.12 + 0.03 * k; });
    // wall mapping for the close: block columns (sorted by x) -> wall columns (sorted by x)
    const order = data.map((_, k) => k).sort((a, b) => (data[a].res.x - data[b].res.x) || (data[b].res.y - data[a].res.y) || (data[a].res.z - data[b].res.z));
    const wcells = cells.slice().sort((a, b) => (a.cx - b.cx) || (a.cy - b.cy));
    order.forEach((k, j) => {
      const c = wcells[j];
      data[k].wall = new THREE.Vector3(WALL_C.x + (c.cx - 23.5) * WP, WALL_C.y + (13 - c.cy) * WP, WALL_C.z - WCUBE / 2);
      data[k].wc = new THREE.Color().setHex(c.hex);
      data[k].wd = 0.10 * (c.cx / 47) + 0.05 * r();
    });
    // stream trails: one short additive segment per stream cube, bright orange at the head, black at the tail
    const trailGeo = new THREE.BufferGeometry();
    trailGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(NSTREAM * 6), 3));
    const tcol = new Float32Array(NSTREAM * 6), tc = col('#FF7A2E');
    for (let k = 0; k < NSTREAM; k++) { tcol.set([tc.r, tc.g, tc.b, 0, 0, 0], k * 6); }
    trailGeo.setAttribute('color', new THREE.BufferAttribute(tcol, 3));
    const trails = new THREE.LineSegments(trailGeo, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, opacity: 0 }));
    trails.frustumCulled = false; root.add(trails);
    const decal = makeDecal(5.6, 3.2, 0.34); decal.position.set(BC.x, 0.004, 0.1); root.add(decal);
    // hero outlines and links
    const upB = new THREE.Vector3(0, CUBE / 2, 0).applyQuaternion(qB);
    const outlineGeo = new THREE.EdgesGeometry(new THREE.BoxGeometry(CUBE * 1.04, CUBE * 1.04, CUBE * 1.04));
    const outlines = HEROES.map(() => { const l = new THREE.LineSegments(outlineGeo, new THREE.LineBasicMaterial({ color: col('#FF6A1A').multiplyScalar(2.2), transparent: true, opacity: 0 })); root.add(l); return l; });
    const heroIdx = HEROES.map((h) => h.iz * NX * NY + (NY - 1) * NX + h.ix);
    const links = LINKS.map(([a, b]) => {
      const A = data[heroIdx[a]].res.clone().add(upB), B = data[heroIdx[b]].res.clone().add(upB);
      const M = A.clone().lerp(B, 0.5); M.y += 0.25 + 0.04 * A.distanceTo(B);
      const curve = new THREE.QuadraticBezierCurve3(A, M, B);
      const geo = new THREE.TubeGeometry(curve, 64, 0.012, 6, false);
      const m = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color: col('#FF8A3A').multiplyScalar(2.0), transparent: true, blending: THREE.AdditiveBlending, depthWrite: false }));
      root.add(m); return m;
    });
    // overlay
    const wdom = el('div', 'scene-vault-world layer', ctx.layers.world);
    const wl = new WorldLabel(wdom, 'VECTOR DB', { size: 17, tracking: 0.32 });
    // hero labels sit on bright cube tops and bloomed links: each gets a dark backing pill (6 x 3 px; the
    // right pad drops the 0.22em trailing tracking so the text reads centered in the pill)
    const hl = HEROES.map((h) => {
      const d = el('div', 'herolabel', wdom, h.label);
      Object.assign(d.style, { background: 'rgba(20,21,25,0.72)', borderRadius: '4px', padding: `${PILL_PY}px ${(PILL_PX - 0.22 * 15).toFixed(1)}px ${PILL_PY}px ${PILL_PX}px` });
      return d;
    });
    const tdom = el('div', 'scene-vault-title layer', ctx.layers.titles);
    const title = new TitleBlock(tdom, { eyebrow: 'STEP 04', words: [{ text: 'Knowledge' }, { text: 'Vault' }], desc: 'Chunks become searchable.', T, Tn: TN });
    const counter = new Counter(tdom, { variant: 'B' });
    // the right column reads INDEXED with a bar that fills left to right (not the reference's NOISE)
    if (counter.nlabel) counter.nlabel.textContent = 'INDEXED';
    if (counter.barFill) { counter.barFill.style.right = 'auto'; counter.barFill.style.left = '0px'; }
    ctx.scene.add(root);
    st = { root, vox, data, stream, trails, decal, outlines, links, heroIdx, wl, hl, title, counter, qB, upB };
    ctx.vault = st;
    return { root, dom: [wdom, tdom] };
  },
  update(ctx, t) {
    const s = st, m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), q0 = new THREE.Quaternion(), qI = new THREE.Quaternion(), qBu = new THREE.Quaternion(), p = new THREE.Vector3(), sc = new THREE.Vector3();
    const cA = s.vox.geometry.getAttribute('aColor'), eA = s.vox.geometry.getAttribute('aEmis'), aA = s.vox.geometry.getAttribute('aAlpha');
    const ss = ssAt(t);
    const drift = driftAt(t);
    // stream cube position before the resolve (fly-in from the ribbon, far ones arrive last)
    const flyF = (v, tt) => E.inOutCubic(seg(tt, 10.3 + 0.40 * v.stream.s, 10.55 + 0.42 * v.stream.s));
    const noisePos = (v, tt, out) => {
      out.copy(v.nz).addScaledVector(v.vel, driftAt(tt)); out.y += liftAt(tt);
      if (v.stream) out.lerp(v.stream.start, 1 - flyF(v, tt));
      return out;
    };
    const pPrev = new THREE.Vector3();
    const relayout = t >= 12.5;
    const heroOn = E.outQuad(seg(t, HERO_T0, HERO_T0 + 0.15)) * (1 - seg(t, 12.45, 12.6));
    let P = 0;
    const c = new THREE.Color();
    s.data.forEach((v, i) => {
      const pi = clamp((ss - v.d) / 0.35); P += pi;
      const u = E.outCubic(pi);
      noisePos(v, t, p).lerp(v.res, u);
      q.setFromAxisAngle(v.ax, v.rot * (1 - u) + 0.08 * drift * (1 - u));
      q.multiply(q0.setFromAxisAngle(v.jax, v.jit * u)).premultiply(qBu.copy(qI).slerp(s.qB, u));
      let scale = lerp(v.nscale, 1, u), emis = 0;
      if (v.stream) scale *= lerp(0.55, 1, flyF(v, t));
      c.copy(v.nc).lerp(v.rc, u);
      if (v.hero >= 0) {
        const k = v.hero, hp = seg(t, HERO_T0 + HERO_STAG * k, HERO_T0 + 0.25 + HERO_STAG * k);
        scale *= 1 + 0.15 * Math.sin(Math.PI * hp);
        emis = 0.6 * heroOn;
      }
      if (relayout) {
        const w = E.outQuint(seg(t, 12.5 + v.wd, 12.5 + v.wd + 0.30));
        p.lerp(v.wall, w); q.slerp(qI, w); scale = lerp(scale, WCUBE / CUBE, w);
        c.lerp(v.wc, w);
      }
      sc.setScalar(scale);
      s.vox.setMatrixAt(i, m4.compose(p, q, sc));
      cA.setXYZ(i, c.r, c.g, c.b); eA.setX(i, emis); aA.setX(i, 1);
    });
    P /= s.data.length;
    // stream trails: from each flying cube back along its path (where it was 0.08 s ago)
    const tpos = s.trails.geometry.getAttribute('position');
    let tmax = 0;
    s.stream.forEach((v, k) => {
      noisePos(v, t, p); noisePos(v, t - 0.08, pPrev);
      const f = flyF(v, t), a = Math.sin(Math.PI * f);
      pPrev.sub(p).multiplyScalar(a).add(p);
      tpos.setXYZ(2 * k, p.x, p.y, p.z); tpos.setXYZ(2 * k + 1, pPrev.x, pPrev.y, pPrev.z);
      tmax = Math.max(tmax, a);
    });
    tpos.needsUpdate = true;
    s.trails.material.opacity = 0.75 * tmax;
    s.trails.visible = tmax > 0.002;
    s.vox.instanceMatrix.needsUpdate = true; cA.needsUpdate = true; eA.needsUpdate = true; aA.needsUpdate = true;
    s.vox.material.uniforms.lit.value = 1 - seg(t, 12.62, 12.95);
    s.vox.material.uniforms.camPos.value.copy(ctx.camera.position);
    s.vox.visible = t < 12.98;
    s.decal.material.opacity = 0.30 * (1 - seg(t, 12.5, 12.8));
    // hero outlines + links
    s.outlines.forEach((l, k) => {
      const v = s.data[s.heroIdx[k]], hp = seg(t, HERO_T0 + HERO_STAG * k, HERO_T0 + 0.25 + HERO_STAG * k);
      l.position.copy(v.res); l.quaternion.copy(s.qB); l.scale.setScalar(1 + 0.15 * Math.sin(Math.PI * hp));
      l.material.opacity = heroOn; l.visible = heroOn > 0.001 && !relayout;
    });
    s.links.forEach((m, k) => {
      const u = E.outQuad(seg(t, HERO_T0 + HERO_STAG * k, HERO_T0 + 0.20 + HERO_STAG * k));
      const cnt = m.geometry.index.count;
      m.geometry.setDrawRange(0, Math.floor((cnt * u) / 6) * 6);
      m.visible = u > 0 && heroOn > 0.001; m.material.opacity = heroOn;
    });
    // labels
    const tp = ctx.project(new THREE.Vector3(BC.x, 0, BC.z));
    // fade in from 0 (no opacity floor) and settle 6 px upward into place
    const wu = E.outQuad(seg(t, 10.75, 10.97));
    s.wl.set(tp.x, tp.y + VDB_DY + 6 * (1 - wu), wu * (1 - seg(t, 12.3, 12.45)), tp.visible);
    s.hl.forEach((d, k) => {
      const v = s.data[s.heroIdx[k]];
      const hp = ctx.project(v.res.clone().add(s.upB));
      const hu = E.outQuad(seg(t, HERO_T0 + 0.10 + 0.03 * k, HERO_T0 + 0.35));
      const o = hu * (1 - seg(t, 12.30, 12.45));
      d.style.display = o > 0.001 && hp.visible ? '' : 'none';
      d.style.opacity = o.toFixed(3);
      d.style.transform = `translate(${Math.round(hp.x + 10 - PILL_PX)}px, ${Math.round(hp.y - 74 - PILL_PY + 6 * (1 - hu))}px)`;
    });
    s.title.update(t);
    const nn = Math.round(73 * P);
    s.counter.update(t, 10.55, 12.30, 'EMBEDDED', `${String(nn).padStart(2, '0')} / 73`, P);
  },
};
