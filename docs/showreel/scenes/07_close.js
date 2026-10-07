// 07_close: "Slide -> knowledge." The vault voxels land as a yawed wall, the slide decodes crisp in front of
// a receding row of coarser frames (24 / 14 / 8 / 5 blocks), the row folds back into one card that turns to face
// the camera, five label chips attach to the exact things they describe, the "BEOL AX" slate and credit
// settle under the card, and the end card holds.
import { THREE, E, seg, lerp, clamp, col, S4, cameraAt, makeChip, makeDecal, makeSlideMaterial, makeCanvas, canvasTex, FONT } from '../engine.js';
import { el, MaskedLine, capOffset } from '../ui.js';

// 06_vault lays the voxel wall out around WALL0 (front-on); the close re-poses it around WALL_C
const WALL0 = new THREE.Vector3(S4, 1.96, 0);
const WALL_C = new THREE.Vector3(S4, 1.86, 0), SW = 5.40, SH = 3.04;
// end slate under the card: "BEOL AX" (Display 700, reference title style) over a muted mono credit line
const SLATE_TOP = 846, SLATE_SIZE = 46; // "BEOL AX" cap-top / size
const CREDIT_TOP = 910;                  // credit cap-top (mono 16), ~40 px above the rail ring
const YAW0 = THREE.MathUtils.degToRad(-28); // sharp card left, the coarser row recedes to the right
const SHIFT0 = -1.7;                          // the yawed row sits left so the ghosts have room
const DROP0 = -0.14;                          // ...and a little low, clear of the rising title while the camera is high
const GHOSTS = [{ n: 24, o: 0.92 }, { n: 14, o: 0.78 }, { n: 8, o: 0.62 }, { n: 5, o: 0.46 }]; // the slide is dark: keep the far frames legible
const G_STEP = new THREE.Vector3(0.95, 0, -1.1); // per-ghost offset in slab space (right and back)
const G_SCALE = 0.92;                            // each ghost 0.92^k of the card
// end card: the slide settles at ~53% of frame width (x 455..1465, y 238..805), between the title and the slate
const S_END = 1.02, Y_END = 0.09;
const CHIP_IN_L = 414, CHIP_IN_R = 1506; // chip inner edges (px), 40 px off the card
const CHIP_W_MAX = 284;                   // widest chip (px); chips keep their approved size
// chip anchors at pose C for an unscaled card centred on WALL0 (STORYBOARD 7.7); chip rows follow the anchors
const CHIPS = [
  { k: 'module', v: 'SAUP · TiN', side: -1, anchor: [541, 290] },
  { k: 'decision', v: 'pending', side: -1, anchor: [742, 587] },
  { k: 'lot_id', v: 'RDM8EA.62', side: 1, anchor: [1356, 374] },
  { k: 'open_risk', v: 'TDDB', side: 1, anchor: [1356, 464] },
  { k: 'tem_ref', v: 'APM-…6524', side: 1, anchor: [1305, 540], hot: true },
];
let st = {};

// slab pose: fully yawed (the decode row holds 12.85 -> 13.30), then turns to face the camera, settled by 13.60
const turnAt = (t) => E.inOutCubic(seg(t, 13.30, 13.60));
const poseAt = (t) => { const u = turnAt(t); return { yaw: YAW0 * (1 - u), x: SHIFT0 * (1 - u), y: DROP0 * (1 - u) + Y_END * u, s: lerp(1, S_END, u) }; };
// room grids dim to 60% from 12.9 so the image dominates the end card
const dimAt = (t) => lerp(1, 0.6, E.inOutSine(seg(t, 12.9, 13.4)));

// soft rounded-rect glow (inner rect = 1 / 1.15 of the texture), for the warm rim spill behind the card
function rimTexture() {
  const w = 640, h = Math.round(640 * SH / SW), c = makeCanvas(w, h), g = c.getContext('2d');
  const iw = w / 1.15, ih = h / 1.15;
  g.filter = 'blur(14px)';
  g.fillStyle = '#ffffff';
  g.fillRect((w - iw) / 2 + 4, (h - ih) / 2 + 4, iw - 8, ih - 8);
  return canvasTex(c);
}

export default {
  id: 'close', start: 12.25, end: 15.0,
  setup(ctx) {
    const root = new THREE.Group();
    const slab = new THREE.Group(); slab.position.copy(WALL_C); root.add(slab);
    const mat = makeSlideMaterial(ctx.assets.slideTex, ctx.assets.cellsTex);
    const face = new THREE.Mesh(new THREE.PlaneGeometry(SW, SH), mat); face.position.z = 0.001; face.renderOrder = 2; slab.add(face);
    const back = new THREE.Mesh(new THREE.BoxGeometry(SW, SH, 0.05), new THREE.MeshBasicMaterial({ color: col('#1B1C20') })); back.position.z = -0.026; slab.add(back);
    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.PlaneGeometry(SW, SH)), new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.10 }));
    edges.position.z = 0.002; edges.renderOrder = 3; slab.add(edges);
    // warm rim spill behind the card (additive, faint)
    const rim = new THREE.Mesh(new THREE.PlaneGeometry(SW * 1.15, SH * 1.15), new THREE.MeshBasicMaterial({
      map: rimTexture(), color: col('#FF6A1A').multiplyScalar(0.25), transparent: true, opacity: 0.35,
      blending: THREE.AdditiveBlending, depthWrite: false,
    }));
    rim.position.z = -0.08; rim.renderOrder = -2; slab.add(rim);
    // receding ghost frames: progressively coarser copies of the slide, right and back of the card
    const ghosts = GHOSTS.map((gd, k) => {
      const gm = makeSlideMaterial(ctx.assets.slideTex, ctx.assets.cellsTex);
      gm.uniforms.n.value = gd.n; gm.depthWrite = false;
      const g = new THREE.Group();
      const gf = new THREE.Mesh(new THREE.PlaneGeometry(SW, SH), gm); gf.renderOrder = -1 - k;
      const ge = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.PlaneGeometry(SW, SH)), new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0, depthWrite: false }));
      ge.position.z = 0.001; ge.renderOrder = -1 - k;
      g.add(gf, ge); g.scale.setScalar(Math.pow(G_SCALE, k + 1)); slab.add(g);
      return { ...gd, g, gm, ge, k: k + 1 };
    });
    // soft contact shadow on the floor under the card
    const decal = makeDecal(6.5, 1.6, 0.45); decal.position.set(WALL_C.x, 0.004, 0.3); root.add(decal);

    // unproject chip/anchor screen positions at pose C onto the z = 0 plane
    const cam = ctx.camera.clone();
    const pc = cameraAt(14.4); cam.position.copy(pc.pos); cam.lookAt(pc.target); cam.updateMatrixWorld(); cam.updateProjectionMatrix();
    const toWorld = (x, y, z = 0) => {
      const ndc = new THREE.Vector3((x / 1920) * 2 - 1, 1 - (y / 1080) * 2, 0.5).unproject(cam);
      const dir = ndc.sub(cam.position).normalize();
      const k = (z - cam.position.z) / dir.z;
      return cam.position.clone().addScaledVector(dir, k);
    };
    const made = CHIPS.map((c) => makeChip(c.k, c.v, [c.hot ? 'queue' : 'neutral']));
    // one chip scale so the widest chip fits between the frame margin and its inner edge
    const sc = Math.min(0.92, CHIP_W_MAX / (Math.max(...made.map((m) => m.width)) * 178));
    const endC = new THREE.Vector3(WALL_C.x, WALL_C.y + Y_END, WALL_C.z);
    const chips = CHIPS.map((c, i) => {
      const chip = made[i];
      chip.group.scale.setScalar(sc); root.add(chip.group);
      // anchor in slab space (measured on a card centred on WALL0), so it rides the card while it turns
      const anchorLocal = toWorld(c.anchor[0], c.anchor[1], 0.012).sub(WALL0);
      // the chip sits level with where its anchor lands on the final (scaled) card: horizontal leaders
      const y = anchorLocal.clone().multiplyScalar(S_END).add(endC).project(cam).y * -540 + 540;
      const wPx = (chip.width * sc) * 178;
      const cx = c.side < 0 ? CHIP_IN_L - wPx / 2 : CHIP_IN_R + wPx / 2;
      const rest = toWorld(cx, y, 0.01);
      const edgeX = c.side < 0 ? CHIP_IN_L + 6 : CHIP_IN_R - 6;
      const lineStart = toWorld(edgeX, y, 0.01);
      const lg = new THREE.BufferGeometry().setFromPoints([lineStart, lineStart.clone()]);
      const line = new THREE.Line(lg, new THREE.LineBasicMaterial({ color: c.hot ? col('#FF6A1A').multiplyScalar(1.4) : 0xffffff, transparent: true, opacity: c.hot ? 0.9 : 0.35 }));
      root.add(line);
      const dot = new THREE.Mesh(new THREE.CircleGeometry(3.2 / 178, 20), new THREE.MeshBasicMaterial({ color: c.hot ? col('#FF6A1A').multiplyScalar(1.4) : 0xffffff, transparent: true }));
      root.add(dot);
      return { ...c, chip, rest, out: c.side * 24 / 178, lineStart, anchorLocal, anchor: new THREE.Vector3(), line, dot };
    });

    // room grid dimmer: master reads as (whatever was set) x dimAt(t). A getter keeps it a pure function of
    // the seek time even when the close is inactive (no stale value after seeking backwards).
    for (const m of [ctx.floor && ctx.floor.material, ctx.wall && ctx.wall.material]) {
      const u = m && m.uniforms && m.uniforms.master;
      if (!u || u.__closeDim) continue;
      let base = u.value;
      Object.defineProperty(u, 'value', { get: () => base * dimAt(ctx.t || 0), set: (v) => { base = v; }, configurable: true });
      u.__closeDim = true;
    }

    // overlay
    const tdom = el('div', 'scene-close layer', ctx.layers.titles);
    const titleLine = new MaskedLine(tdom, [{ text: 'Slide' }, { text: '→' }, { text: 'knowledge.', orange: true }],
      { size: 86, weight: 700, tracking: -0.02, capTop: 133, align: 'center' });
    const slate = new MaskedLine(tdom, [{ text: 'BEOL' }, { text: 'AX' }],
      { size: SLATE_SIZE, weight: 700, tracking: -0.01, capTop: SLATE_TOP, align: 'center' });
    const cap = el('div', 'caption', tdom);
    cap.style.font = `400 16px/20px ${FONT.mono}`; cap.style.letterSpacing = '0.04em';
    cap.style.top = `${CREDIT_TOP - capOffset(FONT.mono, 400, 16, 20)}px`;
    el('span', 'b', cap, 'synthetic example  ·  '); el('span', 'c', cap, 'Motion design — Claude');
    ctx.scene.add(root);
    st = { root, slab, face, back, mat, edges, rim, ghosts, decal, chips, titleLine, slate, cap };
    return { root, dom: tdom };
  },
  update(ctx, t) {
    const s = st;
    const pose = poseAt(t);
    s.slab.position.set(WALL_C.x + pose.x, WALL_C.y + pose.y, WALL_C.z);
    s.slab.rotation.set(0, pose.yaw, 0);
    s.slab.scale.setScalar(pose.s);
    s.slab.updateMatrixWorld(true);

    // voxel re-layout (06_vault): land the wall in the close's yawed pose instead of front-on at WALL0,
    // and keep the key light on it (relief reads) until 12.90. 06 rewrites every instance each seek and
    // updates first, so this post-transform is a pure function of t.
    poseVoxels(ctx, t);

    // decode 12.98 -> 13.28: the slide plane replaces the voxel wall in its 48x27 state, then de-pixelates
    // (the ghosts live in the slab too and slide out from behind the voxel wall before the hand-off)
    const decoded = t >= 12.98;
    s.face.visible = s.back.visible = s.edges.visible = s.rim.visible = decoded;
    const du = E.outQuad(seg(t, 12.98, 13.28));
    s.mat.uniforms.n.value = Math.exp(lerp(Math.log(48), Math.log(2560), du));
    s.mat.uniforms.map.value = t >= 13.45 ? ctx.assets.slideTexSolid : ctx.assets.slideTex;

    // ghost frames slide out of the wall (12.78 ->), hold as a receding row, then fold back in as the card turns
    const fold = turnAt(t);
    s.ghosts.forEach((g) => {
      const out = E.outCubic(seg(t, 12.66 + 0.04 * g.k, 12.90 + 0.04 * g.k));
      const a = out * (1 - fold);
      g.g.position.copy(G_STEP).multiplyScalar(g.k * a);
      g.g.position.z -= 0.004 * g.k; // never coplanar with the card
      g.gm.uniforms.opacity.value = g.o * a;
      g.ge.material.opacity = 0.30 * a * (1 - 0.22 * g.k);
      g.g.visible = a > 0.002;
    });

    // end card staging: warm rim, floor shadow
    const card = seg(t, 13.45, 13.85);
    s.rim.material.opacity = 0.35 * card;
    s.edges.material.opacity = 0.10;
    s.decal.visible = t >= 12.9;
    s.decal.material.opacity = 0.45 * E.inOutSine(seg(t, 12.9, 13.4));
    s.decal.position.x = WALL_C.x + pose.x * 0.6;
    s.decal.scale.x = pose.s;

    // chips + leaders (attach after the card has turned; anchors ride the card)
    s.chips.forEach((c, i) => {
      const t0 = 13.52 + i * 0.05, u = E.outQuint(seg(t, t0, t0 + 0.22));
      const g = c.chip.group;
      g.position.copy(c.rest); g.position.x += c.out * (1 - u);
      c.chip.set(c.hot ? 'queue' : 'neutral', t < t0 ? 0 : lerp(0.4, 1, u));
      g.visible = t >= t0;
      c.anchor.copy(c.anchorLocal); s.slab.localToWorld(c.anchor);
      const lu = E.outExpo(seg(t, t0 + 0.10, t0 + 0.25));
      const pos = c.line.geometry.getAttribute('position');
      const end = c.lineStart.clone().lerp(c.anchor, lu);
      pos.setXYZ(0, c.lineStart.x, c.lineStart.y, c.lineStart.z); pos.setXYZ(1, end.x, end.y, end.z); pos.needsUpdate = true;
      c.line.visible = lu > 0.001; c.dot.visible = lu > 0.98;
      c.dot.position.copy(c.anchor); c.dot.rotation.copy(s.slab.rotation);
    });
    // title; end slate: "BEOL AX" rises on the 13.50 beat (settled ~13.80), the credit follows (settled 13.92);
    // from 14.0 nothing new arrives, only the push-in and the dust move (calm final hold)
    s.titleLine.set(t, { riseAt: 12.75, riseDur: 0.45, stagger: 0.05, from: 110 });
    s.slate.set(t, { riseAt: 13.50, riseDur: 0.45, stagger: 0.06, from: 110 });
    const co = E.outQuint(seg(t, 13.62, 13.92));
    s.cap.style.opacity = co.toFixed(3); s.cap.style.display = co > 0 ? '' : 'none';
    s.cap.style.transform = `translate(0, ${(8 * (1 - co)).toFixed(2)}px)`;
  },
};

// ------------------------------------------------------------------ voxel wall re-pose (06_vault's InstancedMesh)
const _m = new THREE.Matrix4(), _p = new THREE.Vector3(), _q = new THREE.Quaternion(), _s = new THREE.Vector3();
const _qy = new THREE.Quaternion(), _qw = new THREE.Quaternion(), _id = new THREE.Quaternion(), _w = new THREE.Vector3();
const _Y = new THREE.Vector3(0, 1, 0);
function poseVoxels(ctx, t) {
  const v = ctx.vault;
  if (!v || !v.vox || !v.data || !v.data.length || !v.data[0].wall || t < 12.5 || t >= 12.98) return;
  const pose = poseAt(12.98); // the wall lands fully yawed; the slab starts from the same pose
  const center = new THREE.Vector3(WALL_C.x + pose.x, WALL_C.y + pose.y, WALL_C.z);
  _qy.setFromAxisAngle(_Y, pose.yaw);
  const mesh = v.vox;
  v.data.forEach((d, i) => {
    // same per-cube landing weight as 06_vault's re-layout
    const w = E.outQuint(seg(t, 12.5 + d.wd, 12.5 + d.wd + 0.30));
    if (w <= 0) return;
    mesh.getMatrixAt(i, _m); _m.decompose(_p, _q, _s);
    _w.copy(d.wall).sub(WALL0).applyQuaternion(_qy).add(center); // target in the new pose
    _p.addScaledVector(_w.sub(d.wall), w);
    _q.premultiply(_qw.copy(_id).slerp(_qy, w));
    mesh.setMatrixAt(i, _m.compose(_p, _q, _s));
  });
  mesh.instanceMatrix.needsUpdate = true;
  // key light: 1 -> 0.55 while flying, hold 0.55 so the relief reads, unlit only for the hand-off to the plane
  mesh.material.uniforms.lit.value = t < 12.9 ? lerp(1, 0.55, seg(t, 12.62, 12.8)) : 0.55 * (1 - seg(t, 12.9, 12.98));
}
