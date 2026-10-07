// engine.js: renderer, composer + bloom, room, camera track, easing, seeded PRNG, shared
// materials/assets and the scene registry for the BEOL AX showreel.
// Everything that draws is a pure function of t: seek(t) may be called in any order.
import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js';

export { THREE };
export const W = 1920, H = 1080, DURATION = 15, FPS = 60;
export const S1 = 40.0, S2 = 50.4, S3 = 60.8, S4 = 71.2;
export const PS = new THREE.Vector3(-7.0, 1.30, 4.0);
export const FONT = {
  display: '"Segoe UI Variable Display", "Bahnschrift", sans-serif',
  text: '"Segoe UI Variable Text", "Segoe UI", sans-serif',
  mono: '"Cascadia Mono", "DejaVu Sans Mono", monospace',
};
export const C = {
  orange: '#FF6A1A', orangeSoft: '#E5682F', orangeWire: '#E8893A', glowCore: '#FFF35A',
  glowMid: '#FFC12E', white: '#FFFFFF', desc: '#D8DBE2', future: '#BFC2C9', track: '#4A4B53',
  card: '#26272C', cardBorder: '#53565D',
};

// ------------------------------------------------------------------ math, easing, PRNG
export const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
export const lerp = (a, b, u) => a + (b - a) * u;
export const seg = (t, a, b) => clamp((t - a) / (b - a));
export const smoothstep = (a, b, x) => { const u = clamp((x - a) / (b - a)); return u * u * (3 - 2 * u); };
export const E = {
  linear: (x) => x,
  inQuad: (x) => x * x,
  outQuad: (x) => 1 - (1 - x) * (1 - x),
  inCubic: (x) => x * x * x,
  outCubic: (x) => 1 - Math.pow(1 - x, 3),
  inOutCubic: (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2),
  inOutQuart: (x) => (x < 0.5 ? 8 * x ** 4 : 1 - Math.pow(-2 * x + 2, 4) / 2),
  inQuint: (x) => x ** 5,
  outQuint: (x) => 1 - Math.pow(1 - x, 5),
  inExpo: (x) => (x <= 0 ? 0 : Math.pow(2, 10 * x - 10)),
  outExpo: (x) => (x >= 1 ? 1 : 1 - Math.pow(2, -10 * x)),
  outSine: (x) => Math.sin((x * Math.PI) / 2),
  inOutSine: (x) => -(Math.cos(Math.PI * x) - 1) / 2,
  outBack: (x, s = 1.70158) => { const c = s + 1; return 1 + c * Math.pow(x - 1, 3) + s * Math.pow(x - 1, 2); },
  // asymmetric camera ease, cubic-bezier(0.35, 0, 0.15, 1): quick launch, velocity peak near u = 0.26
  // (2.9x mean, below inOutCubic's 3x), and the back half of the time is a soft settle (the reference's
  // truck profile). (0.5, 0, 0.1, 1) has the same shape but a spikier peak (3.7x, 2.5x the jerk).
  swift: (x) => bezierEase(0.35, 0, 0.15, 1, x),
  // truck ease, cubic-bezier(0.30, 0, 0.25, 1): same quick-launch / long-settle family as swift with a
  // rounder launch, so velocity peaks at 2.36x mean (~95-104 px/frame over a 0.70 s truck) and the
  // acceleration turns over without a cusp. Keeps the trucks well under the whip, the one violent move.
  glide: (x) => bezierEase(0.30, 0, 0.25, 1, x),
  // C2 rise ease, cubic-bezier(0.6, 0, 0.3, 1): a gentle launch out of the C1 cross-blend, single
  // velocity hump, and the same long settle into the whip's wind-up as before
  rise: (x) => bezierEase(0.6, 0, 0.3, 1, x),
  // critically-damped-ish spring settle (only for tiny objects)
  spring: (x, k = 9, z = 0.42) => 1 - Math.exp(-k * z * x) * Math.cos(k * Math.sqrt(1 - z * z) * x),
};
// CSS-style cubic-bezier: solve bx(s) = x by Newton (monotone in x for the curves used here), return by(s)
function bezierEase(x1, y1, x2, y2, x) {
  if (x <= 0) return 0;
  if (x >= 1) return 1;
  const bx = (s) => 3 * (1 - s) * (1 - s) * s * x1 + 3 * (1 - s) * s * s * x2 + s * s * s;
  const dbx = (s) => 3 * (1 - s) * (1 - s) * x1 + 6 * (1 - s) * s * (x2 - x1) + 3 * s * s * (1 - x2);
  let s = x;
  for (let i = 0; i < 8; i++) s = clamp(s - (bx(s) - x) / Math.max(dbx(s), 1e-4));
  return 3 * (1 - s) * (1 - s) * s * y1 + 3 * (1 - s) * s * s * y2 + s * s * s;
}
export function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
export function hash2(x, y, s = 0) {
  let h = Math.imul(x | 0, 374761393) + Math.imul(y | 0, 668265263) + Math.imul(s | 0, 2147483647);
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
}
const col = (hex) => new THREE.Color(hex); // sRGB hex -> linear (ColorManagement)
export { col };

// ------------------------------------------------------------------ camera track (STORYBOARD §4)
const V = (x, y, z) => new THREE.Vector3(x, y, z);
const K = {
  // cold open: 4% push toward PS plus a 0.08 lateral truck (+x) for parallax
  c0a: V(-7.0, 1.30, 7.294), c0b: V(-6.92, 1.30, 7.162),
  A: V(-7.84, 1.78, 8.75), B: V(0.0, 10.2, 24.0), Bw: V(14.0, 10.2, 24.0),
  tB: V(0.0, -1.0, 0.0), tBw: V(14.0, -1.0, 0.0),
  C: V(S4, 2.05, 10.60), tC: V(S4, 1.85, 0),
};
const PIV2 = V(S2 - 0.3, 1.5, 0), PIV4 = V(S4 + 0.55, 1.5, 0);
function orbit(pos, pivot, deg) {
  const a = (deg * Math.PI) / 180, dx = pos.x - pivot.x, dz = pos.z - pivot.z;
  return V(pivot.x + dx * Math.cos(a) + dz * Math.sin(a), pos.y, pivot.z - dx * Math.sin(a) + dz * Math.cos(a));
}
// orbit angle (deg) after tau seconds: angular velocity ramps 0 -> rate over the first 0.4 s
const orbitDeg = (rate, tau) => rate * (tau < 0.4 ? (tau * tau) / 0.8 : tau - 0.2);
// step-hold orbit: ORBIT_RATE deg/s about the pivot plus a slow push (radius shrinks by `push`
// with inOutSine over [a, b]), so the holds breathe instead of locking off
const ORBIT_RATE = 2.5;
function holdOrbit(pos, pivot, t, a, b, push) {
  const p = orbit(pos, pivot, orbitDeg(ORBIT_RATE, t - a));
  return pivot.clone().lerp(p, 1 - push * E.inOutSine(seg(t, a, b)));
}
// truck: glide ease (fast launch, long soft settle); the crane bump rides the eased value so
// its vertical velocity is zero at both ends. Trucks aim straight at the next framing's target.
function truck(from, to, fromT, toT, u) {
  const e = E.glide(u);
  const p = from.clone().lerp(to, e);
  p.y += 0.06 * Math.sin(Math.PI * e);
  return { pos: p, target: fromT.clone().lerp(toT, e) };
}
export function cameraAt(t) {
  // C0 0 -> 0.85: push with a mild ease-in, u = s(1+s)/2, so it exits at the speed C1 launches with
  if (t < 0.85) { const s = seg(t, 0, 0.85), u = (s * (1 + s)) / 2; return { pos: K.c0a.clone().lerp(K.c0b, u), target: PS.clone() }; }
  // C1 0.85 -> 1.50 (then holds K.A): the push carries a beat further in, reverses near 0.9 and becomes the pull-back
  // C2 1.30 -> 2.38: rise to the overview, settling straight into the whip's wind-up (no hold)
  // 1.30 -> 1.75: C1 cross-blends into C2, so the pull-back flows into the rise through the 1.50 shatter
  // (never below ~5 px/frame, no dead hitch; peak acceleration half of the old butt join)
  if (t < 2.38) {
    const s1 = seg(t, 0.85, 1.5), u1 = E.inOutCubic(s1) - 0.03 * Math.sin(Math.PI * s1) * (1 - s1);
    const c1 = K.c0b.clone().lerp(K.A, u1);
    if (t < 1.30) return { pos: c1, target: PS.clone() };
    const u2 = E.rise(seg(t, 1.30, 2.38));
    const c2 = K.A.clone().lerp(K.B, u2), tg2 = PS.clone().lerp(K.tB, u2);
    if (t >= 1.75) return { pos: c2, target: tg2 };
    const b = E.inOutSine(seg(t, 1.30, 1.75));
    return { pos: c1.lerp(c2, b), target: PS.clone().lerp(tg2, b) };
  }
  // C3 2.38 -> 2.75: whip with anticipation, u^3 (2.6u - 1.6) dips back (about -0.55 units, -40 px) before it accelerates
  if (t < 2.75) {
    const s = seg(t, 2.38, 2.75), u = s * s * s * (2.6 * s - 1.6);
    return { pos: K.B.clone().lerp(K.Bw, u), target: K.tB.clone().lerp(K.tBw, u) };
  }
  // C4 2.75 -> 3.25: lands from further back at the whip's exit speed, settles before the 3.25 label
  if (t < 3.25) {
    const u = E.outQuint(seg(t, 2.75, 3.25));
    return { pos: V(S1 - 6.4, 3.62, 11).lerp(V(S1, 3.55, 11), u), target: V(S1 - 6.4, 1.65, 0).lerp(V(S1, 1.65, 0), u) };
  }
  if (t < 4.90) return { pos: V(S1, 3.55, lerp(11.0, 10.78, seg(t, 3.25, 4.90))), target: V(S1, 1.65, 0) };
  // trucks (0.70 s) start 0.10 s before each headline beat so they overlap the headline exit
  if (t < 5.60) return truck(V(S1, 3.55, 10.78), V(S2, 3.55, 11), V(S1, 1.65, 0), PIV2, seg(t, 4.90, 5.60));
  // C7 5.60 -> 7.40: orbit + 3% push about PIV2
  if (t < 7.40) return { pos: holdOrbit(V(S2, 3.55, 11), PIV2, t, 5.60, 7.40, 0.03), target: PIV2.clone() };
  if (t < 8.10) return truck(holdOrbit(V(S2, 3.55, 11), PIV2, 7.40, 5.60, 7.40, 0.03), V(S3, 3.55, 11), PIV2, V(S3, 1.65, 0), seg(t, 7.40, 8.10));
  if (t < 9.90) return { pos: V(S3, 3.55, lerp(11.0, 10.78, seg(t, 8.10, 9.90))), target: V(S3, 1.65, 0) };
  if (t < 10.60) return truck(V(S3, 3.55, 10.78), V(S4, 3.55, 11), V(S3, 1.65, 0), PIV4, seg(t, 9.90, 10.60));
  // C11 10.60 -> 12.50: orbit + 3% push about PIV4 (the orbit keeps running under the C12 blend)
  const orb4 = holdOrbit(V(S4, 3.55, 11), PIV4, t, 10.60, 12.5, 0.03);
  if (t < 12.5) return { pos: orb4, target: PIV4.clone() };
  // C12: blend off the still-running orbit, so velocity is continuous at 12.5
  if (t < 13.2) { const u = E.inOutCubic(seg(t, 12.5, 13.2)); return { pos: orb4.lerp(K.C, u), target: PIV4.clone().lerp(K.tC, u) }; }
  // C13: end-card push, 6% toward the card, starting from rest
  const u = E.inOutSine(seg(t, 13.2, 15.0));
  return { pos: K.C.clone().lerp(K.tC, 0.06 * u), target: K.tC.clone() };
}

// ------------------------------------------------------------------ shaders
const OUTPUT_SHADER = {
  uniforms: { tDiffuse: { value: null }, fade: { value: 0 } },
  vertexShader: `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }`,
  fragmentShader: `
    uniform sampler2D tDiffuse; varying vec2 vUv;
    // identity below the knee (exact palette match for room, slide, UI-like objects),
    // soft filmic shoulder above it (emissives roll off to warm white instead of clipping)
    vec3 shoulder(vec3 c){
      const float k = 0.86;
      vec3 over = max(c - k, 0.0);
      return min(c, vec3(k)) + (1.0 - k) * (1.0 - exp(-over / (1.0 - k)));
    }
    vec3 toSRGB(vec3 c){
      return mix(c * 12.92, 1.055 * pow(c, vec3(1.0/2.4)) - 0.055, step(0.0031308, c));
    }
    float hash(vec2 p){ return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }
    void main(){
      vec3 c = texture2D(tDiffuse, vUv).rgb;
      // hot cores desaturate toward warm white like film
      c = toSRGB(shoulder(max(c, 0.0)));
      c += (hash(gl_FragCoord.xy) - 0.5) / 255.0; // static dither against vignette banding
      gl_FragColor = vec4(c, 1.0);
    }`,
};

const BG_VERT = `varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.99999, 1.0); }`;
const BG_FRAG = `
  uniform vec3 cCenter, cMid, cEdge; varying vec2 vUv;
  void main(){
    vec2 p = vUv - vec2(0.5, 0.55);
    p.y *= 0.58;                                   // mostly horizontal falloff
    float d = length(p) / length(vec2(0.5, 0.45 * 0.58));
    vec3 c = mix(cCenter, cMid, smoothstep(0.10, 0.74, d));
    c = mix(c, cEdge, smoothstep(0.70, 1.05, d));
    gl_FragColor = vec4(c, 1.0);
  }`;

const GRID_VERT = `varying vec3 vW; void main(){ vec4 w = modelMatrix * vec4(position,1.0); vW = w.xyz; gl_Position = projectionMatrix * viewMatrix * w; }`;
const GRID_FRAG = `
  uniform vec3 camPos; uniform float aMinor, aMajor, aSeam, cell, majorEvery, isWall, fadeNear, fadeFar, master;
  varying vec3 vW;
  float line(float c){
    float w = fwidth(c);
    float d = abs(fract(c - 0.5) - 0.5);
    float a = 1.0 - smoothstep(0.0, w * 1.15, d - w * 0.15);
    return a * (1.0 - smoothstep(0.18, 0.42, w));   // fade lines that get denser than ~3 px (no moire)
  }
  void main(){
    vec2 c = isWall > 0.5 ? vW.xy : vW.xz;
    vec2 g = c / cell;
    float minor = max(line(g.x), line(g.y));
    float major = max(line(g.x / majorEvery), line(g.y / majorEvery));
    float a = max(minor * aMinor, major * aMajor);
    float seam = 0.0;
    if (isWall < 0.5) {
      float dz = abs(vW.z + 5.5);
      seam = 1.0 - smoothstep(0.0, fwidth(vW.z) * 1.2, dz);
      if (vW.z < -5.5) a = 0.0;
      a = max(a, seam * aSeam);
    } else {
      a *= 1.0 - smoothstep(3.5, 12.0, vW.y);
    }
    float dist = distance(vW, camPos);
    a *= 1.0 - smoothstep(fadeNear, fadeFar, dist);
    a *= master;
    if (a < 0.002) discard;
    gl_FragColor = vec4(vec3(1.0), a);
  }`;

// unlit voxel shader with explicit three-tone faces (display: top ~+12%, front base, sides ~-30%),
// a faint bevel darkening at each face border and a depth falloff. Multipliers are linear-light.
const VOXEL_VERT = `
  attribute vec3 aColor; attribute float aAlpha; attribute float aEmis;
  varying vec3 vColor; varying float vAlpha; varying float vEmis; varying vec3 vN; varying vec3 vW; varying vec2 vUv;
  void main(){
    mat4 m = modelMatrix * instanceMatrix;
    vN = normalize(mat3(m) * normal);
    vec4 w = m * vec4(position, 1.0); vW = w.xyz;
    vColor = aColor; vAlpha = aAlpha; vEmis = aEmis; vUv = uv;
    gl_Position = projectionMatrix * viewMatrix * w;
  }`;
const VOXEL_FRAG = `
  uniform float lit; uniform vec3 keyDir; uniform vec3 camPos;
  varying vec3 vColor; varying float vAlpha; varying float vEmis; varying vec3 vN; varying vec3 vW; varying vec2 vUv;
  void main(){
    vec3 n = normalize(vN), w = n * n;            // axis weights (exact on axis-aligned faces, smooth when tumbling)
    float shade = w.y * (n.y > 0.0 ? 1.28 : 0.42) + w.x * 0.50 + w.z * 0.92;
    vec2 e2 = abs(vUv - 0.5);
    shade *= 1.0 - 0.10 * smoothstep(0.42, 0.5, max(e2.x, e2.y));   // bevel
    vec3 c = vColor * mix(1.0, shade, lit);
    float dist = distance(vW, camPos);
    c *= mix(1.0, 0.78, smoothstep(8.0, 15.0, dist) * lit); // depth falloff
    c = mix(c, vec3(1.0), vEmis * 0.6) * (1.0 + vEmis * 0.45);
    gl_FragColor = vec4(c, vAlpha);
  }`;

// slide face: pixelate by block count n with box-filtered (mip) colors; at 48x27 the exact cell colors
const SLIDE_VERT = `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }`;
const SLIDE_FRAG = `
  uniform sampler2D map; uniform sampler2D cells; uniform float n; uniform float opacity; uniform float bright;
  varying vec2 vUv;
  void main(){
    vec2 grid = vec2(n, n * 27.0 / 48.0);
    vec2 q = (floor(vUv * grid) + 0.5) / grid;
    float lod = max(log2(2560.0 / n), 0.0);
    vec3 c = textureLod(map, n > 2000.0 ? vUv : q, n > 2000.0 ? 0.0 : lod).rgb;
    float w = clamp((log2(96.0) - log2(n)) / 1.0, 0.0, 1.0);
    c = mix(c, texture2D(cells, q).rgb, w);
    gl_FragColor = vec4(c * bright, opacity);
  }`;

// ------------------------------------------------------------------ canvas helpers
export function makeCanvas(w, h) { const c = document.createElement('canvas'); c.width = w; c.height = h; return c; }
export function canvasTex(canvas, mip = true) {
  const t = new THREE.CanvasTexture(canvas);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 8;
  if (!mip) { t.generateMipmaps = false; t.minFilter = THREE.LinearFilter; }
  return t;
}
export function roundRect(g, x, y, w, h, r) {
  g.beginPath();
  g.moveTo(x + r, y); g.lineTo(x + w - r, y); g.arcTo(x + w, y, x + w, y + r, r);
  g.lineTo(x + w, y + h - r); g.arcTo(x + w, y + h, x + w - r, y + h, r);
  g.lineTo(x + r, y + h); g.arcTo(x, y + h, x, y + h - r, r);
  g.lineTo(x, y + r); g.arcTo(x, y, x + r, y, r); g.closePath();
}
export function trackText(g, text, x, y, tracking, align = 'left') {
  // canvas letterSpacing (Chrome) with manual alignment so trailing tracking does not offset centering
  g.letterSpacing = `${tracking}px`;
  const w = g.measureText(text).width - tracking;
  const sx = align === 'left' ? x : align === 'right' ? x - w : x - w / 2;
  g.textAlign = 'left';
  g.fillText(text, sx, y);
  g.letterSpacing = '0px';
  return w;
}
function radialTex(size, stops) {
  const c = makeCanvas(size, size), g = c.getContext('2d');
  const gr = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  for (const [o, s] of stops) gr.addColorStop(o, s);
  g.fillStyle = gr; g.fillRect(0, 0, size, size);
  const t = canvasTex(c); return t;
}

// ------------------------------------------------------------------ the engineer's slide (synthetic)
function smoothNoise1(seed, n, step) {
  // value noise sampled every `step` px, cosine-interpolated
  const r = mulberry32(seed), k = Math.ceil(n / step) + 2, v = new Float32Array(k);
  for (let i = 0; i < k; i++) v[i] = r() * 2 - 1;
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const f = i / step, i0 = Math.floor(f), u = f - i0, s = (1 - Math.cos(u * Math.PI)) / 2;
    out[i] = v[i0] * (1 - s) + v[i0 + 1] * s;
  }
  return out;
}
// Slide layout (2560x1440 canvas px). Anchors used elsewhere: hook parser rows at y 330/440/550 across
// x 1560..2337 (callout rows), close chips at the title (x~245,y~114), the defect (731,900), callout rows 1/3
// (x~2314, y~333/567) and the first table row (x~2181, y~764).
const SL = {
  W: 2560, H: 1440, M: 223,
  panel: { x: 223, y: 250, w: 1257, h: 1080, r: 18 },
  col: { x: 1560, w: 777 },
  defect: { x: 731, y: 900 },
};
// SEM micrograph (false color), panel-local pixels; computed once, shared by every slide variant
function drawSEM() {
  const { x: PX, y: PY, w: PW, h: PH } = SL.panel;
  const cv = makeCanvas(PW, PH), g = cv.getContext('2d');
  const img = g.createImageData(PW, PH), d = img.data;
  // 22 Cu lines, pitch 58 (line 30 / space 28); line 8 / 9 straddle the defect at x 731
  const NL = 22, pitch = 58, half = 15, X0 = SL.defect.x - pitch / 2 - 8 * pitch;
  const jl = [], jr = [], bodyN = [];
  for (let k = 0; k < NL; k++) {
    const a = smoothNoise1(101 + k, PH, 30), b = smoothNoise1(201 + k, PH, 7);
    const c2 = smoothNoise1(301 + k, PH, 34), e = smoothNoise1(401 + k, PH, 6);
    jl.push(a.map((v, i) => v * 2.0 + b[i] * 0.7));
    jr.push(c2.map((v, i) => v * 2.0 + e[i] * 0.7));
    bodyN.push(smoothNoise1(501 + k, PH, 80));
  }
  const vn = (cell, seed) => {
    const gw = Math.ceil(PW / cell) + 2, gh = Math.ceil(PH / cell) + 2, r = mulberry32(seed), grid = new Float32Array(gw * gh);
    for (let i = 0; i < grid.length; i++) grid[i] = r() * 2 - 1;
    return (x, y) => {
      const fx = x / cell, fy = y / cell, ix = fx | 0, iy = fy | 0, u = fx - ix, v = fy - iy;
      const su = u * u * (3 - 2 * u), sv = v * v * (3 - 2 * v), o = iy * gw + ix;
      return (grid[o] * (1 - su) + grid[o + 1] * su) * (1 - sv) + (grid[o + gw] * (1 - su) + grid[o + gw + 1] * su) * sv;
    };
  };
  const g1 = vn(7, 61), g2 = vn(23, 62), g3 = vn(140, 63);
  const rowN = smoothNoise1(77, PH, 3);
  // vias (landing pads wider than the line), one tip-to-tip gap, the bridge defect
  const VIAS = [{ k: 6, y: 420 }, { k: 11, y: 1010 }, { k: 17, y: 640 }];
  const GAP = { k: 14, y: 560, h: 24 };
  const BX = SL.defect.x, BY = SL.defect.y;
  const bTop = smoothNoise1(91, 120, 7), bBot = smoothNoise1(92, 120, 9);
  const ramp = (stops) => (u) => {
    u = clamp(u);
    let i = 0; while (i < stops.length - 2 && u > stops[i + 1][0]) i++;
    const [a, ca] = stops[i], [b, cb] = stops[i + 1], s = clamp((u - a) / (b - a));
    return [lerp(ca[0], cb[0], s), lerp(ca[1], cb[1], s), lerp(ca[2], cb[2], s)];
  };
  const teal = ramp([[0.0, [12, 21, 28]], [0.5, [18, 32, 42]], [1.0, [30, 55, 66]]]);
  const copper = ramp([[0.0, [62, 30, 16]], [0.32, [118, 60, 28]], [0.72, [212, 134, 76]], [1.0, [255, 211, 160]]]);
  const KEY = [255, 176, 112], GLOW = [255, 138, 58];
  const DOF = 0.2 * PH;
  for (let py = 0; py < PH; py++) {
    const gy = py + PY;
    // depth of field: top and bottom 20% of the panel go soft and 30% darker
    const dof = Math.max(1 - smoothstep(0, DOF, py), smoothstep(PH - DOF, PH, py));
    const soft = 1.5 + 9 * dof;
    const scan = rowN[py] * 0.006;
    for (let px = 0; px < PW; px++) {
      const gx = px + PX;
      const k = Math.min(NL - 1, Math.max(0, Math.round((gx - X0) / pitch)));
      const cx = X0 + k * pitch;
      const L = cx - half + jl[k][py] * (1 + dof), R = cx + half + jr[k][py] * (1 + dof);
      let inside = Math.min(gx - L, R - gx);
      if (k === GAP.k) {
        const dx = gx - cx, cap = half - Math.sqrt(Math.max(0, half * half - dx * dx));
        inside = Math.min(inside, Math.abs(gy - GAP.y) - GAP.h - cap);
      }
      // bridge defect: a jagged copper neck across the space between lines 8 and 9, unioned with the lines
      // (max of the signed distances) so it reads as one copper shape with one continuous SEM rim
      const dxb = gx - BX, dyb = gy - BY;
      let hot = 0;
      if (Math.abs(dxb) < 46 && Math.abs(dyb) < 50) {
        const ix = Math.max(0, Math.min(119, dxb + 60));
        const top = BY - 13 + bTop[ix] * 5, bot = BY + 12 + bBot[ix] * 5;
        const insB = Math.min(gy - top, bot - gy, 40 - Math.abs(dxb));
        hot = smoothstep(-1.5, 1.5, insB) * (1 - smoothstep(0, 1.5, inside));
        inside = Math.max(inside, insB);
      }
      let m = smoothstep(-soft, soft, inside);
      let rim = Math.exp(-Math.max(inside, 0) / 3.2) * m;
      const grain = 0.07 * g1(px, py) + 0.045 * g2(px, py);
      const big = 0.03 * g3(px, py);
      let vc = 0.45 + 0.03 * bodyN[k][py] + 0.55 * grain + big;
      for (const v of VIAS) {
        const vx = X0 + v.k * pitch, dist = Math.hypot(gx - vx, gy - v.y);
        if (dist > 40) continue;
        const vin = 22 - dist, mv = smoothstep(-soft, soft, vin);
        if (mv > 0) {
          const vr = Math.exp(-Math.max(vin, 0) / 4.5) * mv;
          // bright ring, slightly darker core (charging contrast of a landed via)
          vc = lerp(vc, 0.56 + 0.4 * grain - 0.10 * (1 - smoothstep(0, 14, dist)), mv);
          rim = Math.max(rim, vr * 1.25); m = Math.max(m, mv);
        }
      }
      vc += 0.30 * rim;
      // per-material color, then exposure (charging, DOF darkening, scan, in-panel vignette)
      const n1 = (hash2(gx, gy, 7) - 0.5) * 0.045 + (hash2(gx >> 1, gy >> 1, 9) - 0.5) * 0.025;
      const vd = 0.16 + 0.012 * bodyN[(k + 3) % NL][py] + 0.02 * g2(px + 999, py) + big * 0.5;
      const ct = teal((vd + n1 - 0.08) / 0.2);
      const cc = copper((vc + 0.7 * n1 - 0.28) / 0.50);
      const ux = (px - PW / 2) / (PW / 2), uy = (py - PH / 2) / (PH / 2);
      const vig = 1 - 0.30 * clamp(ux * ux * 0.55 + uy * uy * 0.75);
      const charge = 0.96 + 0.06 * (1 - py / PH);
      const ex = 1.05 * charge * vig * (1 - 0.30 * dof) + scan * 2;
      // warm key on the defect (r 380, +18%) and a soft glow in the dielectric right around it (r 160)
      const dk = Math.hypot(dxb, dyb);
      const kd = Math.max(0, 1 - dk / 380), key = 0.10 * kd * kd, lift = 1 + 0.18 * kd;
      const gl = 0.35 * Math.pow(Math.max(0, 1 - dk / 160), 2) * (1 - m);
      const o = (py * PW + px) * 4;
      for (let ch = 0; ch < 3; ch++) {
        let v = lerp(ct[ch], cc[ch], m) * ex * lift;
        v = lerp(v, KEY[ch], key);
        v = lerp(v, GLOW[ch], gl);
        v += hot * 14 * (ch === 0 ? 1 : ch === 1 ? 0.6 : 0.3);
        d[o + ch] = clamp(v, 0, 255);
      }
      d[o + 3] = 255;
    }
  }
  g.putImageData(img, 0, 0);
  return cv;
}
// variant 'full' (hook, overview, decode) or 'clean' (end card: no micro text, skeleton rows instead)
function drawSlide(sem, variant) {
  const clean = variant === 'clean';
  const { W: SW, H: SH, M } = SL, P = SL.panel, Cx = SL.col.x, Cw = SL.col.w;
  const cv = makeCanvas(SW, SH), g = cv.getContext('2d');
  const bgG = g.createLinearGradient(0, 0, 0, SH);
  bgG.addColorStop(0, '#191B21'); bgG.addColorStop(1, '#131519');
  g.fillStyle = bgG; g.fillRect(0, 0, SW, SH);
  g.textBaseline = 'alphabetic';
  const skel = (x, y, w, c, h = 22) => { g.fillStyle = c; roundRect(g, x, y - h / 2, w, h, h / 2); g.fill(); };

  // title band
  g.fillStyle = 'rgba(14,15,18,0.82)'; g.fillRect(0, 0, SW, 190);
  g.fillStyle = 'rgba(255,255,255,0.08)'; g.fillRect(0, 189, SW, 2);
  g.fillStyle = `rgba(191,194,201,${clean ? 0.45 : 0.72})`;
  g.font = `600 70px ${FONT.display}`; g.letterSpacing = '-1.4px';
  g.fillText('M1 SAUP spacer TiO2 → TiN', M, 128); g.letterSpacing = '0px';
  g.fillStyle = '#FF6A1A'; g.fillRect(M, 156, 64, 4);
  if (!clean) { g.font = `700 34px ${FONT.mono}`; g.fillStyle = 'rgba(191,194,201,0.62)'; trackText(g, 'ENGINEER SLIDE · SYNTHETIC', M + P.w + 80 + Cw, 122, 34 * 0.16, 'right'); }

  // SEM panel
  g.save(); roundRect(g, P.x, P.y, P.w, P.h, P.r); g.clip(); g.drawImage(sem, P.x, P.y); g.restore();
  g.strokeStyle = 'rgba(255,255,255,0.14)'; g.lineWidth = 2; roundRect(g, P.x + 1, P.y + 1, P.w - 2, P.h - 2, P.r); g.stroke();
  if (!clean) {
    g.font = `700 34px ${FONT.mono}`;
    const lw = trackText(g, 'SEM TOP VIEW', -9999, 0, 2) + 48;
    g.fillStyle = 'rgba(12,13,16,0.78)'; roundRect(g, P.x + 24, P.y + 24, lw, 62, 10); g.fill();
    g.fillStyle = '#C9CCD3'; trackText(g, 'SEM TOP VIEW', P.x + 48, P.y + 67, 2);
    // scale bar
    g.fillStyle = 'rgba(237,237,237,0.85)'; g.fillRect(P.x + P.w - 24 - 174, P.y + P.h - 44, 174, 6);
    g.font = `700 34px ${FONT.mono}`; trackText(g, '50 nm', P.x + P.w - 24 - 87, P.y + P.h - 62, 1, 'center');
  }
  // defect annotation: the slide's one orange accent
  const { x: bx, y: by } = SL.defect;
  g.strokeStyle = '#FF6A1A'; g.lineWidth = 4;
  g.beginPath(); g.ellipse(bx, by, 64, 44, 0, 0, Math.PI * 2); g.stroke();
  if (!clean) {
    g.lineWidth = 3; g.beginPath(); g.moveTo(bx + 46, by - 31); g.lineTo(bx + 120, by - 112); g.lineTo(bx + 150, by - 112); g.stroke();
    g.font = `700 32px ${FONT.mono}`;
    const tw = trackText(g, 'open/short', -9999, 0, 1);
    g.fillStyle = 'rgba(12,13,16,0.86)'; roundRect(g, bx + 150, by - 142, tw + 40, 60, 10); g.fill();
    g.strokeStyle = 'rgba(255,106,26,0.7)'; g.lineWidth = 2; roundRect(g, bx + 151, by - 141, tw + 38, 58, 10); g.stroke();
    g.fillStyle = '#FF6A1A'; trackText(g, 'open/short', bx + 170, by - 100, 1);
  }

  // right column: callout (rows centred at y 330 / 440 / 550 for the hook's parser sweep)
  g.fillStyle = 'rgba(22,24,29,0.92)'; roundRect(g, Cx, 260, Cw, 400, 16); g.fill();
  g.strokeStyle = 'rgba(255,255,255,0.18)'; g.lineWidth = 2; roundRect(g, Cx + 1, 261, Cw - 2, 398, 16); g.stroke();
  g.fillStyle = 'rgba(255,255,255,0.06)'; g.fillRect(Cx + 16, 262, Cw - 32, 1);
  if (!clean) {
    g.font = `700 40px ${FONT.mono}`;
    const row = (y, parts) => { let x = Cx + 46; for (const [s, c] of parts) { g.fillStyle = c; g.fillText(s, x, y); x += g.measureText(s).width; } };
    row(344, [['RDM8EA.62', '#FF6A1A'], ['   WF#9', '#9EA2AA']]);
    row(454, [['CMBSRP open/short 100%', '#EDEDED']]);
    row(564, [['TDDB: ', '#9EA2AA'], ['still to check', '#FF8A3A']]);
  } else {
    skel(Cx + 46, 330, 230, 'rgba(255,106,26,0.62)'); skel(Cx + 300, 330, 110, 'rgba(158,162,170,0.32)');
    skel(Cx + 46, 440, 520, 'rgba(237,237,237,0.30)');
    skel(Cx + 46, 550, 130, 'rgba(158,162,170,0.32)'); skel(Cx + 200, 550, 330, 'rgba(255,138,58,0.45)');
  }

  // table: 3 rows (row 1 = the missing TEM evidence the end card links)
  const TY = [764, 852, 940];
  g.fillStyle = 'rgba(255,255,255,0.10)';
  for (const y of [TY[0] - 44, TY[1] - 44, TY[2] - 44, TY[2] + 44]) g.fillRect(Cx, y, Cw, 2);
  if (clean) {
    g.fillStyle = 'rgba(255,106,26,0.10)'; g.fillRect(Cx, TY[0] - 42, Cw, 84);
    g.fillStyle = '#FF6A1A'; g.fillRect(Cx, TY[0] - 42, 6, 84);
  }
  const rows = [['TEM', 'messenger only', clean ? 0.9 : 0.5], ['Rs', '+4.1 %   WF#9', 1], ['Vbd', '11.2 V', 1]];
  rows.forEach(([k, v, a], i) => {
    if (clean) {
      skel(Cx + 30, TY[i], 70, `rgba(125,130,139,${0.40 * a})`, 18);
      skel(Cx + 200, TY[i], i === 0 ? 300 : i === 1 ? 240 : 150, i === 0 ? 'rgba(255,138,58,0.55)' : 'rgba(191,194,201,0.30)', 18);
    } else {
      g.font = `500 40px ${FONT.mono}`; g.globalAlpha = a;
      g.fillStyle = '#7D828B'; g.fillText(k, Cx + 30, TY[i] + 14);
      g.fillStyle = '#BFC2C9'; g.fillText(v, Cx + 200, TY[i] + 14);
      g.globalAlpha = 1;
    }
  });

  // line chart: Rs by wafer, 5 points, the last one is the outlier
  const cx0 = Cx + 40, cx1 = Cx + Cw - 30, cy0 = 1060, cy1 = 1300;
  g.fillStyle = 'rgba(255,255,255,0.05)';
  for (let i = 0; i < 4; i++) g.fillRect(cx0, cy0 + (i * (cy1 - cy0)) / 4, cx1 - cx0, 2);
  g.fillStyle = '#5A5E66'; g.fillRect(cx0, cy0 - 10, 3, cy1 - cy0 + 10); g.fillRect(cx0, cy1, cx1 - cx0, 3);
  const vals = [0.30, 0.36, 0.27, 0.40, 0.86];
  const pts = vals.map((v, i) => [cx0 + 60 + (i * (cx1 - cx0 - 110)) / 4, cy1 - 20 - v * (cy1 - cy0 - 40)]);
  g.strokeStyle = '#FF6A1A'; g.lineWidth = 6; g.lineJoin = 'round'; g.lineCap = 'round';
  g.beginPath(); pts.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y))); g.stroke();
  pts.forEach(([x, y], i) => {
    g.beginPath(); g.arc(x, y, i === 4 ? 13 : 9, 0, Math.PI * 2); g.fillStyle = '#16181D'; g.fill();
    g.lineWidth = 4; g.strokeStyle = i === 4 ? '#FFB070' : '#FF6A1A'; g.stroke();
  });
  if (!clean) {
    g.font = `700 34px ${FONT.mono}`; g.fillStyle = '#8A8E96'; trackText(g, 'Rs BY WAFER', cx0, cy0 - 26, 2);
  }
  return cv;
}
function cellsFrom(canvas) {
  const g = canvas.getContext('2d'), { data } = g.getImageData(0, 0, 2560, 1440);
  const cells = new Uint8Array(48 * 27 * 4), out = [];
  const lin = (v) => { v /= 255; return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
  const enc = (v) => { const s = v <= 0.0031308 ? v * 12.92 : 1.055 * Math.pow(v, 1 / 2.4) - 0.055; return Math.round(clamp(s) * 255); };
  for (let cy = 0; cy < 27; cy++) for (let cx = 0; cx < 48; cx++) {
    let r = 0, gg = 0, b = 0, n = 0;
    const x0 = Math.floor(cx * 2560 / 48), x1 = Math.floor((cx + 1) * 2560 / 48);
    const y0 = Math.floor(cy * 1440 / 27), y1 = Math.floor((cy + 1) * 1440 / 27);
    for (let y = y0; y < y1; y += 2) for (let x = x0; x < x1; x += 2) {
      const o = (y * 2560 + x) * 4; r += lin(data[o]); gg += lin(data[o + 1]); b += lin(data[o + 2]); n++;
    }
    const R = enc(r / n), G = enc(gg / n), B = enc(b / n);
    // DataTexture rows go bottom-up (flipY=false): row 0 = bottom of the slide
    const o = ((26 - cy) * 48 + cx) * 4; cells[o] = R; cells[o + 1] = G; cells[o + 2] = B; cells[o + 3] = 255;
    out.push({ cx, cy, hex: (R << 16) | (G << 8) | B });
  }
  const tex = new THREE.DataTexture(cells, 48, 27, THREE.RGBAFormat);
  tex.colorSpace = THREE.SRGBColorSpace; tex.magFilter = THREE.NearestFilter; tex.minFilter = THREE.NearestFilter;
  tex.needsUpdate = true;
  return { cells: out, tex };
}

// ------------------------------------------------------------------ token chips (CanvasTexture planes)
export const CHIP_PX = 340; // canvas px per world unit (2x of ~170 screen px/unit)
const CHIP_H = 118;
const chipCache = new Map();
export function chipCanvas(key, value, state) {
  const id = `${key}|${value}|${state}`;
  if (chipCache.has(id)) return chipCache.get(id);
  const meas = makeCanvas(8, 8).getContext('2d');
  const kF = `600 44px ${FONT.mono}`, vF = `600 66px ${FONT.mono}`, bF = `700 32px ${FONT.mono}`;
  meas.font = kF; const kw = key ? meas.measureText(key + '  ').width : 0;
  meas.font = vF; const vw = meas.measureText(value).width;
  const badge = state === 'pass' ? 'PASS' : state === 'flag' ? 'FLAG' : '';
  meas.font = bF; meas.letterSpacing = '5px'; const bw = badge ? meas.measureText(badge).width + 38 : 0;
  const h = CHIP_H, pad = 44, w = Math.ceil(pad + kw + vw + bw + pad);
  const c = makeCanvas(w + 8, h + 8), g = c.getContext('2d');
  g.translate(4, 4);
  roundRect(g, 0, 0, w, h, 26); g.fillStyle = '#23242A'; g.fill();
  roundRect(g, 7, 7, w - 14, h - 14, 20); g.strokeStyle = 'rgba(32,35,42,0.9)'; g.lineWidth = 7; g.stroke();
  const border = state === 'pass' ? 'rgba(255,255,255,0.45)' : state === 'neutral' ? 'rgba(255,255,255,0.30)' : '#E5682F';
  roundRect(g, 3.5, 3.5, w - 7, h - 7, 23); g.strokeStyle = border; g.lineWidth = 7; g.stroke();
  g.textBaseline = 'alphabetic';
  let x = pad;
  if (key) { g.font = kF; g.fillStyle = 'rgba(191,194,201,0.85)'; g.fillText(key, x, 74); x += kw; }
  g.font = vF; g.fillStyle = '#F2F2F2'; g.fillText(value, x, 81); x += vw; // value sits just under the bloom threshold
  if (badge) {
    g.font = bF; g.letterSpacing = '5px';
    g.fillStyle = state === 'flag' ? '#FF6A1A' : 'rgba(255,255,255,0.70)';
    g.fillText(badge, x + 34, 72); g.letterSpacing = '0px';
  }
  const res = { canvas: c, w: (w + 8) / CHIP_PX, h: (h + 8) / CHIP_PX };
  chipCache.set(id, res);
  return res;
}
const chipGlowCache = new Map();
function chipGlowCanvas(wPx) {
  if (chipGlowCache.has(wPx)) return chipGlowCache.get(wPx);
  const h = CHIP_H, c = makeCanvas(wPx, h + 8), g = c.getContext('2d');
  g.translate(4, 4); roundRect(g, 3.5, 3.5, wPx - 15, h - 7, 23); g.strokeStyle = '#E5682F'; g.lineWidth = 7; g.stroke();
  chipGlowCache.set(wPx, c); return c;
}
// A chip is a group holding one plane per state (textures prebuilt) + an additive border glow for FLAG.
export function makeChip(key, value, states = ['queue']) {
  const group = new THREE.Group(), planes = {};
  let maxW = 0;
  for (const s of states) {
    const cc = chipCanvas(key, value, s);
    const mat = new THREE.MeshBasicMaterial({ map: canvasTex(cc.canvas), transparent: true, depthWrite: false, side: THREE.DoubleSide });
    const m = new THREE.Mesh(new THREE.PlaneGeometry(cc.w, cc.h), mat);
    m.visible = false; group.add(m); planes[s] = m; maxW = Math.max(maxW, cc.w);
  }
  let glow = null;
  if (states.includes('flag') || states.includes('glow')) {
    const cc = chipCanvas(key, value, 'flag');
    const gc = chipGlowCanvas(cc.canvas.width);
    glow = new THREE.Mesh(new THREE.PlaneGeometry(cc.w, cc.h),
      new THREE.MeshBasicMaterial({ map: canvasTex(gc), transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, color: new THREE.Color(2.2, 2.2, 2.2) }));
    glow.position.z = 0.002; glow.visible = false; group.add(glow);
  }
  const api = {
    group, planes, glow, width: maxW,
    set(state, opacity = 1, glowAmt = 0) {
      for (const s in planes) { planes[s].visible = s === state && opacity > 0.001; planes[s].material.opacity = opacity; }
      if (glow) { glow.visible = glowAmt > 0.001 && opacity > 0.001; glow.material.opacity = glowAmt * opacity; }
    },
  };
  return api;
}

// ------------------------------------------------------------------ shared object factories
export function makeDecal(w, d, strength = 0.25) {
  const m = new THREE.Mesh(new THREE.PlaneGeometry(w, d), new THREE.MeshBasicMaterial({
    map: decalTex, transparent: true, depthWrite: false, opacity: strength, color: 0x000000,
  }));
  m.rotation.x = -Math.PI / 2; m.position.y = 0.004; m.renderOrder = -5;
  return m;
}
let decalTex = null;
export function makeGlass(w, h) {
  const group = new THREE.Group();
  const face = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({
    color: 0xffffff, transparent: true, opacity: 0.09, depthWrite: false, side: THREE.DoubleSide,
  }));
  const edges = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.PlaneGeometry(w, h)), new THREE.LineBasicMaterial({
    color: 0xffffff, transparent: true, opacity: 0.45, depthWrite: false,
  }));
  group.add(face, edges);
  const cw = col('#FFFFFF'), ch = col('#F0A080'), ew = col('#FFFFFF'), eh = col('#FF7A40');
  return {
    group, face, edges,
    setHot(h, alpha = 1) {
      face.material.color.copy(cw).lerp(ch, h); face.material.opacity = lerp(0.09, 0.14, h) * alpha;
      edges.material.color.copy(ew).lerp(eh, h).multiplyScalar(1 + 0.6 * h); edges.material.opacity = lerp(0.45, 0.75, h) * alpha;
    },
  };
}
// LLM orb: radial sun core, low-poly single wire shell, wide red-orange atmosphere, small orbiters
const orbRegistry = [];
export function makeOrb({ core = 0.42, shell = 1.18, atmos = 2.6, orbiters = 8, ringR = [1.8, 2.15], detail = 1, seed = 5 } = {}) {
  const group = new THREE.Group();
  const coreMat = new THREE.ShaderMaterial({
    uniforms: { cA: { value: col('#FFF52C') }, cB: { value: col('#FFC12E') }, cC: { value: col('#FF8A2A') }, gain: { value: 1.0 } },
    vertexShader: `varying vec3 vN; varying vec3 vV; void main(){ vec4 mv = modelViewMatrix*vec4(position,1.0); vN = normalize(normalMatrix*normal); vV = normalize(-mv.xyz); gl_Position = projectionMatrix*mv; }`,
    fragmentShader: `uniform vec3 cA,cB,cC; uniform float gain; varying vec3 vN; varying vec3 vV;
      void main(){ float f = clamp(dot(normalize(vN), normalize(vV)), 0.0, 1.0);
        vec3 c = mix(cC, cB, smoothstep(0.0, 0.70, f)); c = mix(c, cA, smoothstep(0.70, 1.0, f));
        gl_FragColor = vec4(c * gain, smoothstep(0.0, 0.55, f)); }`,
    transparent: true, depthWrite: false,
  });
  const coreM = new THREE.Mesh(new THREE.SphereGeometry(core, 48, 32), coreMat);
  const shellGroup = new THREE.Group();
  const ico = new THREE.IcosahedronGeometry(shell, detail);
  // single thin shell, normal blending: reads as a dim orange cage over the atmosphere, not a lacy glow
  const wireMat = new THREE.LineBasicMaterial({ color: col('#C85A26'), transparent: true, opacity: 0.45, depthWrite: false });
  const wire = new THREE.LineSegments(new THREE.WireframeGeometry(ico), wireMat);
  shellGroup.add(wire);
  // atmosphere: wide, red-orange, tints the room around the hero (about 2.2x the shell)
  const atm = new THREE.Sprite(new THREE.SpriteMaterial({ map: atmosTex, color: col('#E04A18'), transparent: true, opacity: 0.62, blending: THREE.AdditiveBlending, depthWrite: false }));
  atm.scale.setScalar(atmos * 2);
  const orbs = [], r = mulberry32(seed);
  const orbMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(1.7, 1.7, 1.7) });
  for (let i = 0; i < orbiters; i++) {
    const m = new THREE.Mesh(new THREE.SphereGeometry(0.042 * (shell / 1.18) ** 0.5, 12, 8), orbMat);
    // every orbiter on its own plane (seeded -55..+55 deg), evenly phased so they never pair up
    const ring = i % 2, tilt = -55 + 110 * ((i * 0.618034 + r() * 0.35) % 1);
    const yaw = r() * Math.PI, phase = (i * Math.PI * 2) / orbiters + 0.15 * r();
    orbs.push({ m, R: ringR[ring] * (0.97 + 0.06 * r()), tilt, yaw, phase, speed: 0.22 });
    group.add(m);
  }
  // interior fill: dense red-orange body that fills the shell (drawn between atmosphere and cage)
  const fill = new THREE.Sprite(new THREE.SpriteMaterial({ map: fillTex, color: col('#C23A16').multiplyScalar(1.6), transparent: true, opacity: 0.7, blending: THREE.AdditiveBlending, depthWrite: false }));
  fill.scale.setScalar(shell * 2.05);
  const corona = new THREE.Sprite(new THREE.SpriteMaterial({ map: atmosTex, color: col('#FF5A14').multiplyScalar(1.05), transparent: true, opacity: 0.9, blending: THREE.AdditiveBlending, depthWrite: false }));
  corona.scale.setScalar(core * 3.4);
  group.add(atm, fill, corona, shellGroup, coreM);
  const ax = new THREE.Vector3(0.3, 1, 0.1).normalize();
  const api = {
    group, core: coreM, coreMat, wireMat, shellGroup, atm, fill, corona, shell,
    update(t, boost = 1) {
      shellGroup.quaternion.setFromAxisAngle(ax, 0.12 * t + 0.4);
      wireMat.opacity = Math.min(0.45 * boost, 0.8);
      coreMat.uniforms.gain.value = 1.0 * (0.85 + 0.15 * boost);
      for (const o of orbs) {
        const a = o.phase + o.speed * t, tl = (o.tilt * Math.PI) / 180;
        const x = Math.cos(a) * o.R, z = Math.sin(a) * o.R;
        const y = z * Math.sin(tl), zz = z * Math.cos(tl);
        o.m.position.set(x * Math.cos(o.yaw) + zz * Math.sin(o.yaw), y, zz * Math.cos(o.yaw) - x * Math.sin(o.yaw));
      }
    },
  };
  orbRegistry.push(api);
  return api;
}
let atmosTex = null, fillTex = null;

// Voxel InstancedMesh with the custom three-tone shader
export function makeVoxels(count, size) {
  const geo = new THREE.BoxGeometry(size, size, size);
  geo.setAttribute('aColor', new THREE.InstancedBufferAttribute(new Float32Array(count * 3), 3));
  geo.setAttribute('aAlpha', new THREE.InstancedBufferAttribute(new Float32Array(count).fill(1), 1));
  geo.setAttribute('aEmis', new THREE.InstancedBufferAttribute(new Float32Array(count), 1));
  const mat = new THREE.ShaderMaterial({
    uniforms: { lit: { value: 1 }, keyDir: { value: new THREE.Vector3(-0.5, 1.0, 0.6).normalize() }, camPos: { value: new THREE.Vector3() } },
    vertexShader: VOXEL_VERT, fragmentShader: VOXEL_FRAG, transparent: true,
  });
  const mesh = new THREE.InstancedMesh(geo, mat, count);
  mesh.frustumCulled = false;
  mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  return mesh;
}
export function makeSlideMaterial(tex, cellsTex) {
  return new THREE.ShaderMaterial({
    uniforms: { map: { value: tex }, cells: { value: cellsTex }, n: { value: 2560 }, opacity: { value: 1 }, bright: { value: 1 } },
    vertexShader: SLIDE_VERT, fragmentShader: SLIDE_FRAG, transparent: true,
  });
}

// ------------------------------------------------------------------ engine
export function createEngine({ canvas, overlay }) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true, powerPreference: 'high-performance' });
  renderer.setPixelRatio(1);
  renderer.setSize(W, H, false);
  renderer.toneMapping = THREE.NoToneMapping; // tone mapping happens in the output pass (linear HDR until then)
  renderer.setClearColor(col('#25272C'), 1);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(32, W / H, 0.1, 200);

  decalTex = radialTex(256, [[0, 'rgba(255,255,255,1)'], [0.45, 'rgba(255,255,255,0.55)'], [1, 'rgba(255,255,255,0)']]);
  atmosTex = radialTex(256, [[0, 'rgba(255,255,255,1)'], [0.25, 'rgba(255,255,255,0.55)'], [0.6, 'rgba(255,255,255,0.14)'], [1, 'rgba(255,255,255,0)']]);
  // orb interior: holds density out to the shell, then drops (fills the cage instead of a centre-only haze)
  fillTex = radialTex(256, [[0, 'rgba(255,255,255,1)'], [0.45, 'rgba(255,255,255,0.62)'], [0.80, 'rgba(255,255,255,0.30)'], [0.95, 'rgba(255,255,255,0.06)'], [1, 'rgba(255,255,255,0)']]);

  // background vignette
  const bg = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), new THREE.ShaderMaterial({
    uniforms: { cCenter: { value: col('#363940') }, cMid: { value: col('#2E3137') }, cEdge: { value: col('#25272C') } },
    vertexShader: BG_VERT, fragmentShader: BG_FRAG, depthTest: false, depthWrite: false,
  }));
  bg.frustumCulled = false; bg.renderOrder = -1000; scene.add(bg);

  // room grids
  const gridUniforms = (o) => ({
    camPos: { value: new THREE.Vector3() }, aMinor: { value: o.minor }, aMajor: { value: o.major }, aSeam: { value: 0.05 },
    cell: { value: o.cell }, majorEvery: { value: 4 }, isWall: { value: o.wall ? 1 : 0 }, fadeNear: { value: 10 }, fadeFar: { value: 34 }, master: { value: 1 },
  });
  const gridMat = (o) => new THREE.ShaderMaterial({ uniforms: gridUniforms(o), vertexShader: GRID_VERT, fragmentShader: GRID_FRAG, transparent: true, depthWrite: false, extensions: {} });
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(260, 90), gridMat({ minor: 0.022, major: 0.036, cell: 1 }));
  floor.rotation.x = -Math.PI / 2; floor.position.set(35, 0, 39.4); floor.renderOrder = -900; scene.add(floor);
  const wall = new THREE.Mesh(new THREE.PlaneGeometry(260, 40), gridMat({ minor: 0.018, major: 0.026, cell: 2, wall: true }));
  wall.position.set(35, 20, -5.5); wall.renderOrder = -901; scene.add(wall);

  // dust: screen-space motes with slight parallax against camera x; motes near the active hero turn warm
  const DN = 60, NSPECK = 6, dr = mulberry32(4242), dpos = new Float32Array(DN * 3), dattr = new Float32Array(DN * 4);
  for (let i = 0; i < DN; i++) {
    const speck = i >= DN - NSPECK;
    dpos.set([dr() * 1960 - 20, dr() * 1100 - 10, 0], i * 3);
    dattr.set([speck ? 2.0 + dr() * 0.6 : 1.2 + dr() * 1.2, speck ? 0.10 : 0.12 + dr() * 0.18, speck ? 1 : 0, 0.3 + dr() * 0.7], i * 4);
  }
  const dgeo = new THREE.BufferGeometry();
  dgeo.setAttribute('position', new THREE.BufferAttribute(dpos, 3));
  dgeo.setAttribute('aD', new THREE.BufferAttribute(dattr, 4));
  const dust = new THREE.Points(dgeo, new THREE.ShaderMaterial({
    uniforms: { t: { value: 0 }, camX: { value: 0 }, camY: { value: 0 }, master: { value: 1 }, heroXY: { value: new THREE.Vector2(-9999, -9999) }, heroR: { value: 420 } },
    vertexShader: `attribute vec4 aD; uniform float t, camX, camY; uniform vec2 heroXY; uniform float heroR; varying float vA; varying float vSq; varying float vWarm;
      void main(){
        float ph = position.x * 0.013 + position.y * 0.021;
        vec2 p = position.xy + vec2(sin(t*0.35 + ph) * 4.0 + t * 2.2 * aD.w, cos(t*0.27 + ph*1.3) * 3.0 - t * 1.4 * aD.w);
        p.x -= camX * 9.0 * aD.w; p.y += camY * 6.0 * aD.w;
        p = mod(p + 20.0, vec2(1960.0, 1120.0)) - 20.0;
        gl_Position = vec4(p.x / 960.0 - 1.0, 1.0 - p.y / 540.0, 0.0, 1.0);
        vWarm = 1.0 - smoothstep(0.0, heroR, distance(p, heroXY));
        gl_PointSize = aD.x * (1.0 + 0.35 * vWarm); vA = aD.y * (1.0 + 0.6 * vWarm); vSq = aD.z; }`,
    fragmentShader: `uniform float master; varying float vA; varying float vSq; varying float vWarm;
      void main(){ vec2 q = gl_PointCoord - 0.5; float a = vSq > 0.5 ? 1.0 : 1.0 - smoothstep(0.25, 0.5, length(q));
        vec3 c = mix(vec3(0.85), vec3(1.0, 0.62, 0.38), vWarm);
        gl_FragColor = vec4(c, a * vA * master); }`,
    transparent: true, depthTest: false, depthWrite: false,
  }));
  dust.frustumCulled = false; dust.renderOrder = 900; scene.add(dust);

  // lights (for the few MeshStandard objects; voxels use their own key shading)
  scene.add(new THREE.HemisphereLight(col('#C9CCD6'), col('#1A1B1F'), 0.55 * Math.PI));
  const key = new THREE.DirectionalLight(col('#FFF4EA'), 1.4 * Math.PI); key.position.set(-0.5, 1.0, 0.6); scene.add(key);
  const rim = new THREE.DirectionalLight(col('#FF8A50'), 0.35 * Math.PI); rim.position.set(1, 0.6, -1); scene.add(rim);

  // composer: MSAA HalfFloat target -> render -> bloom -> output (tone shoulder + sRGB)
  const rt = new THREE.WebGLRenderTarget(W, H, { type: THREE.HalfFloatType, samples: 4 });
  const composer = new EffectComposer(renderer, rt);
  composer.setPixelRatio(1); composer.setSize(W, H);
  composer.addPass(new RenderPass(scene, camera));
  const bloom = new UnrealBloomPass(new THREE.Vector2(W, H), 0.55, 0.85, 0.95);
  composer.addPass(bloom);
  const dbg = new URLSearchParams(location.search);
  if (dbg.has('bloom')) bloom.strength = +dbg.get('bloom'); // look-dev override
  const out = new ShaderPass(OUTPUT_SHADER);
  composer.addPass(out);

  // slide assets
  // slideTex: the full engineer slide. slideTexClean (also exported as slideTexSolid, which 07_close swaps in
  // at 13.45): same silhouette, no micro text (skeleton rows), TEM row linked in orange.
  const sem = drawSEM();
  const slideCanvas = drawSlide(sem, 'full'), slideCanvasClean = drawSlide(sem, 'clean');
  const { cells, tex: cellsTex } = cellsFrom(slideCanvas);
  const slideTex = canvasTex(slideCanvas), slideTexClean = canvasTex(slideCanvasClean), slideTexSolid = slideTexClean;
  slideTex.minFilter = slideTexClean.minFilter = THREE.LinearMipmapLinearFilter;

  const tmp = new THREE.Vector3();
  function project(v) {
    tmp.copy(v).project(camera);
    const x = (tmp.x + 1) * 0.5 * W, y = (1 - tmp.y) * 0.5 * H;
    const vis = tmp.z < 1 && tmp.z > -1 && x > -400 && x < W + 400 && y > -400 && y < H + 400;
    return { x, y, z: tmp.z, visible: vis };
  }

  // warm dust follows the most prominent visible orb (screen px, y down)
  const hv = new THREE.Vector3(), he = new THREE.Vector3(), hs = new THREE.Vector3(), camUp = new THREE.Vector3();
  function shown(o) { for (let n = o; n; n = n.parent) if (!n.visible) return false; return true; }
  function trackHero() {
    scene.updateMatrixWorld();
    let best = null, bestR = 0;
    for (const orb of orbRegistry) {
      if (!shown(orb.group)) continue;
      orb.group.getWorldPosition(hv);
      const p = project(hv);
      if (!p.visible || p.z >= 1) continue;
      camUp.setFromMatrixColumn(camera.matrixWorld, 1);
      he.copy(hv).addScaledVector(camUp, orb.shell * orb.group.getWorldScale(hs).x);
      const q = project(he), rPx = Math.hypot(q.x - p.x, q.y - p.y);
      if (rPx > bestR) { bestR = rPx; best = p; }
    }
    const u = dust.material.uniforms;
    if (best) { u.heroXY.value.set(best.x, best.y); u.heroR.value = clamp(bestR * 2.1, 160, 520); }
    else u.heroXY.value.set(-9999, -9999);
  }

  const scenes = [];
  const ctx = {
    THREE, renderer, scene, camera, overlay, composer, bloom, floor, wall, dust, project,
    assets: { slideCanvas, slideCanvasClean, slideTex, slideTexSolid, slideTexClean, slideCells: cells, cellsTex },
    register(s) { scenes.push(s); },
  };

  let uiUpdate = () => {};
  ctx.setUI = (fn) => { uiUpdate = fn; };

  function seek(tIn) {
    const t = clamp(+tIn || 0, 0, DURATION);
    const cam = cameraAt(t);
    camera.position.copy(cam.pos); camera.lookAt(cam.target); camera.updateMatrixWorld(); camera.updateProjectionMatrix();
    // grid fade follows the framing: dissolve into haze from just past the subject
    const fn = 0.85 * cam.pos.distanceTo(cam.target);
    for (const gm of [floor, wall]) {
      const u = gm.material.uniforms; u.camPos.value.copy(camera.position);
      u.fadeNear.value = Math.max(10, fn); u.fadeFar.value = Math.max(10, fn) + 24;
    }
    dust.material.uniforms.t.value = t; dust.material.uniforms.master.value = seg(t, 1.0, 1.5); dust.material.uniforms.camX.value = camera.position.x; dust.material.uniforms.camY.value = camera.position.y;
    ctx.t = t;
    for (const s of scenes) {
      const active = t >= s.start && t <= s.end;
      if (s.root) s.root.visible = active;
      if (s.dom) for (const d of [].concat(s.dom)) d.style.display = active ? '' : 'none';
      if (active) s.update(ctx, t, t - s.start, (t - s.start) / (s.end - s.start));
    }
    uiUpdate(t);
    trackHero();
    composer.render();
  }
  ctx.seek = seek;
  return ctx;
}
