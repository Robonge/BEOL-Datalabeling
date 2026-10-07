// 01_hook: "This started as one slide." (drops out 1.38 -> 1.62, clear before the overview card) Full-bleed engineer slide, parser sweep, then a pull-back
// (the slide shrinks to ~40% of the frame and lifts clear of the headline band) while it pixelates
// to the 48x27 cell grid. At release only a checkerboard half of the cells takes flight, drifting
// outward and back into the room while shrinking and fading; the other half dissolves in place.
// Nothing is drawn below y = 700 px, so the headline stays the one thing to read.
import { THREE, E, seg, lerp, clamp, smoothstep, PS, mulberry32, col, makeDecal, makeVoxels, makeSlideMaterial, makeCanvas, canvasTex, FONT } from '../engine.js';
import { el, MaskedLine, Eyebrow } from '../ui.js';

const SW = 3.56, SH = 2.0, DEPTH = 0.035, NX = 48, NY = 27, CELL = SW / NX;
const SLAB_END = 0.56, LIFT = 0.42, FLIGHT = 0.45;  // pull-back scale/lift at release, flyer flight time (s)
const sx = (px) => (px / 2560 - 0.5) * SW;           // slide px -> local x
const sy = (py) => (0.5 - py / 1440) * SH;           // slide px -> local y

let st = {};
export default {
  id: 'hook', start: 0.0, end: 2.7,
  setup(ctx) {
    const root = new THREE.Group();
    const slab = new THREE.Group(); slab.position.copy(PS); root.add(slab);
    const faceMat = makeSlideMaterial(ctx.assets.slideTex, ctx.assets.cellsTex);
    const face = new THREE.Mesh(new THREE.PlaneGeometry(SW, SH), faceMat);
    face.position.z = DEPTH / 2 + 0.0005; slab.add(face);
    const body = new THREE.Mesh(new THREE.BoxGeometry(SW, SH, DEPTH), new THREE.MeshBasicMaterial({ color: col('#1B1C20') }));
    slab.add(body);
    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(SW, SH, DEPTH)),
      new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.45 }));
    slab.add(edges);
    const decal = makeDecal(SW * 1.25, 1.1, 0.30); decal.position.set(PS.x, 0.004, PS.z); root.add(decal);

    // parser sweep + row flashes (thin planes just in front of the face)
    const flashMat = () => new THREE.MeshBasicMaterial({ color: col('#FF6A1A'), transparent: true, opacity: 0, depthWrite: false });
    const rows = [330, 440, 550].map((cy) => {
      const g = new THREE.Group();
      const bgm = new THREE.Mesh(new THREE.PlaneGeometry(sx(2337) - sx(1560), (100 / 1440) * SH), flashMat());
      bgm.position.set((sx(1560) + sx(2337)) / 2, sy(cy), DEPTH / 2 + 0.002);
      const bar = new THREE.Mesh(new THREE.PlaneGeometry((6 / 2560) * SW, (100 / 1440) * SH), flashMat());
      bar.position.set(sx(1563), sy(cy), DEPTH / 2 + 0.003);
      g.add(bgm, bar); slab.add(g); return { bgm, bar };
    });
    const sc = makeCanvas(16, 64), sg = sc.getContext('2d');
    const gr = sg.createLinearGradient(0, 0, 0, 64);
    gr.addColorStop(0, 'rgba(255,255,255,0)'); gr.addColorStop(0.5, 'rgba(255,255,255,1)'); gr.addColorStop(1, 'rgba(255,255,255,0)');
    sg.fillStyle = gr; sg.fillRect(0, 0, 16, 64);
    const sweep = new THREE.Mesh(new THREE.PlaneGeometry(sx(2337) - sx(1560) + 0.04, (22 / 1440) * SH),
      new THREE.MeshBasicMaterial({ map: canvasTex(sc), color: col('#FF6A1A').multiplyScalar(1.6), transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending }));
    sweep.position.set((sx(1560) + sx(2337)) / 2, 0, DEPTH / 2 + 0.004); slab.add(sweep);

    // shatter voxels: the 48x27 cell grid of the last pixelated frame. Only a checkerboard half
    // (648 cells) takes flight; the other half dissolves in place, so the release reads as a calm,
    // sparse veil instead of a wall of debris.
    const vox = makeVoxels(NX * NY, CELL); vox.material.depthWrite = false; root.add(vox);
    const r = mulberry32(911), cells = ctx.assets.slideCells, cA = vox.geometry.getAttribute('aColor');
    const vd = [];
    const c = new THREE.Color();
    cells.forEach((cell, i) => {
      c.setHex(cell.hex); cA.setXYZ(i, c.r, c.g, c.b);
      const lx = -SW / 2 + (cell.cx + 0.5) * CELL, ly = SH / 2 - (cell.cy + 0.5) * CELL;
      const fly = (cell.cx + cell.cy) % 2 === 0;
      const dir = new THREE.Vector3(lx, ly * 1.2, 0); const len = dir.length() || 1; dir.divideScalar(len);
      const ax = new THREE.Vector3(r() - 0.5, r() - 0.5, r() - 0.5).normalize();
      // release sweeps diagonally (top-right first) with a little jitter; flyers drift outward,
      // up and back into the room (never toward the lens or down onto the floor)
      const nx = cell.cx / (NX - 1), ny = cell.cy / (NY - 1);
      const sweep = 0.55 * (1 - nx) + 0.45 * ny;
      const rad = 0.18 + 0.30 * r();
      // near-black background cells read as grime on the charcoal floor: they leave sooner
      const lum = 0.2126 * c.r + 0.7152 * c.g + 0.0722 * c.b;
      vd.push({
        lx, ly, fly, fadeEnd: lerp(0.6, 0.3, 1 - smoothstep(0.015, 0.08, lum)),
        delay: fly ? 0.24 * sweep + 0.05 * r() : 0.05 * sweep + 0.03 * r(),
        vel: new THREE.Vector3(dir.x * rad, Math.max(dir.y, -0.2) * rad * 0.6 + 0.10 + 0.12 * r(), -0.35 - 0.55 * r()),
        ax, rot: 0.8 * r(),
      });
    });
    cA.needsUpdate = true;

    // overlay
    const dom = el('div', 'scene-hook layer', ctx.layers.titles);
    const scrim = el('div', 'scrim', dom);
    const eyebrow = new Eyebrow(dom, 'BEOL AX, EXPLAINED', { capTop: 792 });
    const line = new MaskedLine(dom, [{ text: 'This' }, { text: 'started' }, { text: 'as' }, { text: 'one', orange: true }, { text: 'slide.', orange: true }],
      { size: 108, tracking: -0.025, capTop: 843, x: 117 });
    ctx.scene.add(root);
    st = { root, slab, face, faceMat, body, edges, decal, rows, sweep, vox, vd, dom, scrim, eyebrow, line };
    return { root, dom };
  },
  update(ctx, t) {
    const s = st;
    s.slab.visible = t < 1.5; s.decal.visible = t < 2.15;
    // pull-back: the full-bleed slide shrinks to ~half the frame and lifts clear of the headline
    // band while it pixelates, so by the release it is a small object in the room, not a wall
    const pb = E.inOutCubic(seg(t, 1.0, 1.5));
    const S = lerp(1, SLAB_END, pb);
    s.slab.scale.setScalar(S);
    s.slab.position.set(PS.x, PS.y + LIFT * pb, PS.z);
    s.decal.scale.set(S, 1, 1);
    // decal fades as the slide lifts and the cells leave
    s.decal.material.opacity = 0.30 * (1 - 0.5 * pb) * (1 - seg(t, 1.5, 1.9));
    // parser sweep 0.50 -> 1.00, rows flash at 0.50 / 0.75 / 1.00
    const sweepY = 330 + (t - 0.5) * 440;
    s.sweep.position.y = sy(clamp(sweepY, 280, 600));
    s.sweep.material.opacity = 0.35 * seg(t, 0.42, 0.5) * (1 - seg(t, 1.0, 1.12));
    [0.5, 0.75, 1.0].forEach((tr, i) => {
      const a = t < tr - 0.03 ? 0 : t < tr ? seg(t, tr - 0.03, tr) : 1 - E.outQuad(seg(t, tr, tr + 0.25));
      s.rows[i].bgm.material.opacity = 0.14 * a;
      s.rows[i].bar.material.opacity = 0.95 * a;
    });
    // pixelate 1.00 -> 1.50 (block count in log space)
    const pu = E.inQuad(seg(t, 1.0, 1.5));
    s.faceMat.uniforms.n.value = Math.exp(lerp(Math.log(2560), Math.log(48), pu));
    s.edges.material.opacity = 0.45;

    // release 1.50 -> ~2.15: flyers shrink 0.8 -> 0.25 and are fully faded by 60% of their flight;
    // the stay-behind half dissolves in place within ~0.2 s; nothing is drawn below y = 700 px
    s.vox.visible = t >= 1.5 && t < 2.2;
    if (s.vox.visible) {
      const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), p = new THREE.Vector3(), sc = new THREE.Vector3(), pr = new THREE.Vector3();
      const aA = s.vox.geometry.getAttribute('aAlpha');
      s.vox.material.uniforms.lit.value = 0.35 * seg(t, 1.5, 1.7);
      s.vox.material.uniforms.camPos.value.copy(ctx.camera.position);
      const zf = PS.z + (DEPTH / 2 - CELL / 2) * SLAB_END;
      const k0 = lerp(0.96, 0.8, E.outQuad(seg(t, 1.5, 1.6))); // tiles open from the solid mosaic, no pop
      s.vd.forEach((v, i) => {
        let a, k;
        p.set(PS.x + v.lx * SLAB_END, PS.y + LIFT + v.ly * SLAB_END, zf);
        if (v.fly) {
          const u = seg(t, 1.5 + v.delay, 1.5 + v.delay + FLIGHT);
          const m = E.outCubic(u);
          p.addScaledVector(v.vel, m);
          q.setFromAxisAngle(v.ax, v.rot * m);
          k = lerp(k0, 0.25, m);
          a = 1 - smoothstep(0.0, v.fadeEnd, u);
        } else {
          const u = seg(t, 1.5 + v.delay, 1.5 + v.delay + 0.10);
          q.identity();
          k = lerp(k0, 0.45, E.inQuad(u));
          a = 1 - u;
        }
        // keep the headline band clean: fade anything whose screen y approaches 700 px
        pr.copy(p).project(ctx.camera);
        const ypx = (1 - pr.y) * 0.5 * 1080;
        a *= 1 - smoothstep(640, 700, ypx);
        if (a <= 0.002) { k = 0; a = 0; }
        sc.set(k * SLAB_END, k * SLAB_END, 0.3 * SLAB_END); // thin pixel tiles, not dice
        s.vox.setMatrixAt(i, m4.compose(p, q, sc));
        aA.setX(i, a);
      });
      s.vox.instanceMatrix.needsUpdate = true; aA.needsUpdate = true;
    }
    // overlay
    // hand-off: the eyebrow fades 1.36 -> 1.46, the words drop into their masks from 1.38 (inCubic, so they
    // ease off the hold instead of sitting still like inQuint) and the last one is gone by 1.62. Settled
    // read 0.33 -> 1.38. "Everything in between." rises from 1.62 (02_overview), so the two headlines never
    // share a frame and the bottom-left band is empty while the SLIDE ring flares.
    s.scrim.style.opacity = (1 - seg(t, 1.45, 1.75)).toFixed(3);
    s.scrim.style.display = t < 1.75 ? '' : 'none';
    s.eyebrow.set(1 - seg(t, 1.36, 1.46));
    s.line.set(t, { riseAt: 0, riseDur: 0.33, stagger: 0.03, from: 12, ease: E.outQuint, exitAt: 1.38, exitDur: 0.16, exitStagger: 0.02, exitTo: 112, exitEase: E.inCubic });
  },
};
