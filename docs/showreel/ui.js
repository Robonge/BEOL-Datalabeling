// ui.js: DOM overlay components (title block, masked headline, rail, counter, world label, card).
// Every component is driven by set(t) / update(t) and is a pure function of t.
import { E, clamp, seg, lerp, FONT } from './engine.js';

export function el(tag, cls, parent, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  if (parent) parent.appendChild(e);
  return e;
}
const fmCache = new Map();
const mctx = document.createElement('canvas').getContext('2d');
export function fontMetrics(family, weight, size) {
  const key = `${family}|${weight}|${size}`;
  if (fmCache.has(key)) return fmCache.get(key);
  mctx.font = `${weight} ${size}px ${family}`;
  const m = mctx.measureText('H');
  const r = { asc: m.fontBoundingBoxAscent, desc: m.fontBoundingBoxDescent, cap: m.actualBoundingBoxAscent };
  fmCache.set(key, r);
  return r;
}
// distance from the top of a line box of height L to the cap top of its text
export function capOffset(family, weight, size, L) {
  const m = fontMetrics(family, weight, size);
  return (L - (m.asc + m.desc)) / 2 + m.asc - m.cap;
}
const px = (v) => `${Math.round(v * 100) / 100}px`;
// Drawn arrow matched to the Display 700 stroke weight (the face has no U+2192; the fallback is hairline-thin)
export const ARROW = '<svg class="arr" viewBox="0 0 100 62" aria-hidden="true"><path d="M7 31 H88 M63 8 L90 31 L63 54" fill="none" stroke="currentColor" stroke-width="12" stroke-linecap="round" stroke-linejoin="round"/></svg>';
export function setArrowText(el, text) {
  if (el.dataset.txt === text) return;
  el.dataset.txt = text;
  el.innerHTML = text.split('→').map((s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;')).join(ARROW);
}

// ------------------------------------------------------------------ masked line of words
// words: [{ text, orange }]; each word rises through its own overflow:hidden mask
export class MaskedLine {
  constructor(parent, words, { family = FONT.display, weight = 700, size = 74, tracking = -0.02, capTop = 181, x = 118, align = 'left', cls = '' } = {}) {
    this.root = el('div', `mline ${cls}`, parent);
    const L = Math.round(size * 1.25);
    const s = this.root.style;
    s.font = `${weight} ${size}px ${family}`;
    s.letterSpacing = `${tracking}em`;
    s.lineHeight = `${L}px`;
    s.top = px(capTop - capOffset(family, weight, size, L));
    if (align === 'left') s.left = px(x);
    else { s.left = '0px'; s.width = '1920px'; s.textAlign = 'center'; }
    this.inner = [];
    words.forEach((w, i) => {
      const mask = el('span', 'mask', this.root);
      mask.style.height = `${L}px`; mask.style.paddingBottom = `${Math.round(size * 0.14)}px`;
      const span = el('span', `word${w.orange ? ' orange' : ''}`, mask);
      if (w.text === '→') span.innerHTML = ARROW; else span.textContent = w.text;
      this.inner.push(span);
      if (i < words.length - 1) this.root.appendChild(document.createTextNode(' '));
    });
  }
  // o: { riseAt, riseDur, stagger, ease, from (% below), exitAt, exitDur, exitStagger, exitEase (default inQuint), exitTo (-112 up, 112 down) }
  set(t, o) {
    let any = false;
    this.inner.forEach((span, i) => {
      const r = (o.ease || E.outExpo)(seg(t, o.riseAt + i * o.stagger, o.riseAt + i * o.stagger + o.riseDur));
      let y = lerp(o.from ?? 110, 0, r);
      if (o.exitAt != null) {
        const x0 = o.exitAt + i * (o.exitStagger ?? 0.04);
        const q = (o.exitEase || E.inQuint)(seg(t, x0, x0 + (o.exitDur ?? 0.22)));
        y = lerp(y, o.exitTo ?? -112, q);
      }
      const hidden = y >= 109.9 || y <= -111.9;
      if (!hidden) any = true;
      span.style.transform = Math.abs(y) < 0.001 ? 'none' : `translate(0, ${y.toFixed(3)}%)`;
      span.style.visibility = hidden ? 'hidden' : 'visible';
    });
    this.root.style.display = any ? '' : 'none';
  }
}

// ------------------------------------------------------------------ eyebrow ("■ STEP 01")
export class Eyebrow {
  constructor(parent, text, { x = 120, capTop = 138, align = 'left', size = 17 } = {}) {
    this.root = el('div', 'eyebrow', parent);
    const L = 20, s = this.root.style;
    s.font = `700 ${size}px ${FONT.mono}`; s.lineHeight = `${L}px`;
    const off = capOffset(FONT.mono, 700, size, L);
    s.top = px(capTop - off);
    const sq = el('i', 'sq', this.root);
    sq.style.top = px(off); // 12x12 square, top aligned to the cap top
    el('span', 'tx', this.root, text);
    if (align === 'left') s.left = px(x);
    else { s.left = '0px'; s.width = '1920px'; s.textAlign = 'center'; }
  }
  set(opacity) { this.root.style.opacity = opacity.toFixed(3); this.root.style.display = opacity > 0.001 ? '' : 'none'; }
}

// ------------------------------------------------------------------ step title block (STYLE §3, STORYBOARD §5)
export class TitleBlock {
  constructor(parent, { eyebrow, words, desc, T, Tn }) {
    this.T = T; this.Tn = Tn;
    this.root = el('div', 'titleblock', parent);
    this.eyebrow = new Eyebrow(this.root, eyebrow);
    this.line = new MaskedLine(this.root, words, { size: 74, weight: 700, tracking: -0.018, capTop: 181, x: 118 });
    this.rule = el('div', 'underline', this.root);
    this.desc = el('div', 'desc', this.root, desc);
    const L = 36; this.desc.style.top = px(282 - capOffset(FONT.text, 400, 23, L));
  }
  update(t) {
    const { T, Tn } = this;
    const vis = t >= T + 0.15 && t <= Tn + 0.4;
    this.root.style.display = vis ? '' : 'none';
    if (!vis) return;
    // The headline leaves as one unit just ahead of the camera truck (launch Tn-0.05): every word
    // starts within 0.015 s of the first (Tn-0.12, 0.18 s inCubic), so no lone word is left over the
    // next stage; a 3-word line is fully masked by Tn+0.09, before the incoming 3D enters at ~Tn+0.12.
    // Eyebrow and underline fade over the same window (Tn-0.12 -> Tn+0.03). Settled hold stays >= 1.6 s.
    const eIn = seg(t, T + 0.20, T + 0.40), eOut = 1 - seg(t, Tn - 0.12, Tn + 0.03);
    this.eyebrow.set(eIn * eOut);
    this.line.set(t, { riseAt: T + 0.25, riseDur: 0.45, stagger: 0.05, from: 110, exitAt: Tn - 0.12, exitDur: 0.18, exitStagger: 0.015, exitEase: E.inCubic });
    const u = E.outExpo(seg(t, T + 0.50, T + 0.85));
    this.rule.style.transform = `scaleX(${u.toFixed(4)})`;
    this.rule.style.opacity = (eOut).toFixed(3);
    const d = E.outQuint(seg(t, T + 0.50, T + 0.80)), dOut = 1 - seg(t, Tn - 0.30, Tn - 0.14);
    this.desc.style.opacity = (d * dOut).toFixed(3);
    this.desc.style.transform = `translate(0, ${(8 * (1 - d)).toFixed(2)}px)`;
  }
}

// ------------------------------------------------------------------ pipeline rail
export const STOPS = [200, 579, 960, 1340, 1719];
export class Rail {
  constructor(parent, labels) {
    this.root = el('div', 'rail', parent);
    this.track = el('div', 'track', this.root);
    this.fill = el('div', 'fill', this.root);
    this.dots = []; this.rings = []; this.labels = [];
    const L = 20, off = capOffset(FONT.mono, 700, 16, L);
    labels.forEach((name, i) => {
      const ring = el('div', 'ring', this.root); ring.style.left = px(STOPS[i]);
      const dot = el('div', 'dot', this.root); dot.style.left = px(STOPS[i]);
      const lab = el('div', 'stop', this.root, name);
      lab.style.left = px(STOPS[i] - 200); lab.style.top = px(1004 - off);
      this.dots.push(dot); this.rings.push(ring); this.labels.push(lab);
    });
    this.track.style.left = px(STOPS[0]); this.track.style.width = px(STOPS[4] - STOPS[0]);
    this.fill.style.left = px(STOPS[0]);
  }
  // steps: [{ k, T }] stop index k becomes active at T; finale: time the rail turns orange
  update(t, { steps, show = [2.6, 3.0], finale = 13.0 }) {
    const op = seg(t, show[0], show[1]);
    this.root.style.opacity = op.toFixed(3);
    this.root.style.display = op > 0 ? '' : 'none';
    if (op <= 0) return;
    // active step
    let a = 0;
    for (let i = 0; i < steps.length; i++) if (t >= steps[i].T) a = i;
    const cur = steps[a], next = steps[a + 1];
    const k = cur.k;
    // fill: completes the previous segment (0.88 -> 1) in T..T+0.30, then leads toward the next stop
    let fillX;
    const done = E.outQuint(seg(t, cur.T, cur.T + 0.30));
    if (t < cur.T + 0.30) fillX = k <= 1 ? STOPS[1] : lerp(STOPS[k - 1], STOPS[k], 0.88 + 0.12 * done);
    else if (k >= 4) fillX = STOPS[4];
    else fillX = lerp(STOPS[k], STOPS[k + 1], 0.88 * clamp((t - (cur.T + 0.30)) / 2.20));
    this.fill.style.width = px(Math.max(0, fillX - STOPS[0]));
    const fin = (i) => E.outQuad(seg(t, finale + i * 0.05, finale + i * 0.05 + 0.2));
    // Hand-off at a step boundary T (overlapping, so some stop is always lit on the downbeat):
    //  - outgoing stop: T -> T+0.20 outQuad, 15 -> 11 px, orange -> white (dot and label), ring and glow -> 0;
    //  - incoming stop: from T+0.15, grows 11 -> 15 px outBack(1.4) over 0.25 s, dot colour 0.10 s,
    //    label 0.20 s, ring and glow 0.30 s.
    // Each stop's state is a pure function of t and the T of its own step and of the step after it.
    for (let i = 0; i < 5; i++) {
      const dot = this.dots[i], ring = this.rings[i], lab = this.labels[i];
      let size = 11, color = RGB_FUTURE, lc = RGB_FUTURE_LAB, ringOp = 0, glow = 0;
      const j = steps.findIndex((s) => s.k === i);
      if (j < 0) {
        // never an active step (SLIDE): passed once the first step is on
        if (i < steps[0].k) { color = RGB_WHITE; lc = RGB_WHITE; }
      } else {
        const Ti = steps[j].T + 0.15;
        const g = E.outBack(seg(t, Ti, Ti + 0.25), 1.4);
        size = lerp(11, 15, g);
        color = mixRGB(RGB_FUTURE, RGB_ORANGE, seg(t, Ti, Ti + 0.10));
        lc = mixRGB(RGB_FUTURE_LAB, RGB_ORANGE, seg(t, Ti, Ti + 0.20));
        ringOp = 0.35 * seg(t, Ti, Ti + 0.30); glow = seg(t, Ti, Ti + 0.30);
        const nx = steps[j + 1];
        if (nx) {
          const o = E.outQuad(seg(t, nx.T, nx.T + 0.20));
          if (o > 0) {
            size = lerp(size, 11, o);
            color = mixRGB(color, RGB_WHITE, o); lc = mixRGB(lc, RGB_WHITE, o);
            ringOp *= 1 - o; glow *= 1 - o;
          }
        }
      }
      const f = fin(i);
      if (f > 0) {
        color = mixRGB(color, RGB_ORANGE, f); lc = mixRGB(lc, RGB_ORANGE, f);
        if (i === 4) { ringOp *= 1 - f; glow *= 1 - f; size = lerp(size, 11, f); }
      }
      dot.style.width = dot.style.height = px(size);
      dot.style.background = rgbCSS(color);
      dot.style.boxShadow = glow > 0.001 ? `0 0 18px 4px rgba(255,106,26,${(0.45 * glow).toFixed(3)})` : 'none';
      ring.style.opacity = ringOp.toFixed(3);
      lab.style.color = rgbCSS(lc);
    }
    this.fill.style.background = '#FF6A1A';
  }
}
const hexRGB = (h) => { const p = parseInt(h.slice(1), 16); return [p >> 16, (p >> 8) & 255, p & 255]; };
const RGB_FUTURE = hexRGB('#6A6D74'), RGB_FUTURE_LAB = hexRGB('#BFC2C9'), RGB_WHITE = hexRGB('#FFFFFF'), RGB_ORANGE = hexRGB('#FF6A1A');
const mixRGB = (a, b, u) => [lerp(a[0], b[0], u), lerp(a[1], b[1], u), lerp(a[2], b[2], u)];
const rgbCSS = (c) => `rgb(${Math.round(c[0])},${Math.round(c[1])},${Math.round(c[2])})`;
export function mixHex(a, b, u) {
  const pa = parseInt(a.slice(1), 16), pb = parseInt(b.slice(1), 16);
  const r = Math.round(lerp(pa >> 16, pb >> 16, u)), g = Math.round(lerp((pa >> 8) & 255, (pb >> 8) & 255, u)), bl = Math.round(lerp(pa & 255, pb & 255, u));
  return `rgb(${r},${g},${bl})`;
}

// ------------------------------------------------------------------ counter (bottom right)
const VW = 700; // counter value weight (reference counters are bold Display)
export class Counter {
  constructor(parent, { variant = 'A' } = {}) {
    this.root = el('div', `counter counter-${variant}`, parent);
    const L1 = 20, L2 = 50;
    if (variant === 'A') {
      this.label = el('div', 'clabel', this.root); this.label.style.top = px(855 - capOffset(FONT.mono, 700, 16, L1));
      this.value = el('div', 'cvalue', this.root); this.value.style.top = px(887 - capOffset(FONT.display, VW, 42, L2));
    } else {
      // variant B: left label+value (EMBEDDED NN / 73), right NOISE label, mini bar, small value
      this.label = el('div', 'clabel bl', this.root); this.label.style.top = px(855 - capOffset(FONT.mono, 700, 16, L1));
      this.value = el('div', 'cvalue bl', this.root); this.value.style.top = px(887 - capOffset(FONT.display, VW, 42, L2));
      this.nlabel = el('div', 'clabel br', this.root, 'NOISE'); this.nlabel.style.top = px(855 - capOffset(FONT.mono, 700, 16, L1));
      this.bar = el('div', 'nbar', this.root); this.barFill = el('div', 'nfill', this.bar);
      this.nval = el('div', 'nval', this.root); this.nval.style.top = px(931 - capOffset(FONT.mono, 400, 15, 18));
    }
    // value weight/tracking pinned inline so the cap-top math above always matches what paints
    this.value.style.fontWeight = String(VW); this.value.style.letterSpacing = '-0.02em';
  }
  // inT: entry start; outT: exit start
  update(t, inT, outT, labelText, valueText, noise) {
    const o = seg(t, inT, inT + 0.3) * (1 - seg(t, outT, outT + 0.15));
    this.root.style.display = o > 0.001 ? '' : 'none';
    if (o <= 0.001) return;
    this.root.style.opacity = o.toFixed(3);
    const b = lerp(0.45, 1, seg(t, inT + 0.2, inT + 0.32));
    this.root.style.filter = b < 1 ? `brightness(${b.toFixed(3)})` : 'none';
    if (this.label.textContent !== labelText) this.label.textContent = labelText;
    setArrowText(this.value, valueText);
    if (noise != null && this.barFill) {
      this.barFill.style.width = px(100 * noise);
      const s = noise.toFixed(2); if (this.nval.textContent !== s) this.nval.textContent = s;
    }
  }
}

// ------------------------------------------------------------------ world label (anchored to a projected 3D point)
export class WorldLabel {
  constructor(parent, text, { size = 24, tracking = 0.32, cls = '' } = {}) {
    this.root = el('div', `wlabel ${cls}`, parent, text);
    this.root.style.font = `700 ${size}px ${FONT.mono}`;
    this.root.style.letterSpacing = `${tracking}em`;
    this.size = size; this.track = tracking;
    this.capOff = capOffset(FONT.mono, 700, size, size + 4);
    this.root.style.lineHeight = `${size + 4}px`;
  }
  // (x, y) = centre of the label's cap band
  set(x, y, opacity, visible = true) {
    const ok = visible && opacity > 0.001;
    this.root.style.display = ok ? '' : 'none';
    if (!ok) return;
    const cap = fontMetrics(FONT.mono, 700, this.size).cap;
    this.root.style.transform = `translate(${Math.round(x)}px, ${Math.round(y - cap / 2 - this.capOff)}px) translateX(-50%) translateX(${(this.track * this.size / 2).toFixed(2)}px)`;
    this.root.style.opacity = opacity.toFixed(3);
  }
}

// ------------------------------------------------------------------ content card (DOM, placed by a 4-corner homography)
// Projective map of the card's border box (u, v in card px) onto the projected quad p = [TL, TR, BR, BL].
function homographyCoef(w, h, p) {
  const [x0, y0] = p[0], [x1, y1] = p[1], [x2, y2] = p[2], [x3, y3] = p[3];
  const dx1 = x1 - x2, dx2 = x3 - x2, dy1 = y1 - y2, dy2 = y3 - y2, sx = x0 - x1 + x2 - x3, sy = y0 - y1 + y2 - y3;
  const den = dx1 * dy2 - dx2 * dy1;
  const g = (sx * dy2 - dx2 * sy) / den, hh = (dx1 * sy - sx * dy1) / den;
  return { a: x1 - x0 + g * x1, b: x3 - x0 + hh * x3, c: x0, d: y1 - y0 + g * y1, e: y3 - y0 + hh * y3, f: y0, g, hh };
}
export function homographyCSS(w, h, p) {
  const { a, b, c, d, e, f, g, hh } = homographyCoef(w, h, p);
  const m = [a / w, d / w, 0, g / w, b / h, e / h, 0, hh / h, 0, 0, 1, 0, c, f, 0, 1];
  return `matrix3d(${m.map((v) => +v.toFixed(8)).join(',')})`;
}
export function homography(w, h, p) {
  const { a, b, c, d, e, f, g, hh } = homographyCoef(w, h, p);
  return (u, v) => { const x = u / w, y = v / h, W = g * x + hh * y + 1; return [(a * x + b * y + c) / W, (d * x + e * y + f) / W]; };
}
// Best-fit 2D affine of a projected w x h quad: [ex.x, ex.y, ey.x, ey.y, ox, oy] (local (0,0) -> (ox, oy)).
function fitAffine(w, h, p) {
  const ex = [((p[1][0] - p[0][0]) + (p[2][0] - p[3][0])) / 2 / w, ((p[1][1] - p[0][1]) + (p[2][1] - p[3][1])) / 2 / w];
  const ey = [((p[3][0] - p[0][0]) + (p[2][0] - p[1][0])) / 2 / h, ((p[3][1] - p[0][1]) + (p[2][1] - p[1][1])) / 2 / h];
  const cx = (p[0][0] + p[1][0] + p[2][0] + p[3][0]) / 4, cy = (p[0][1] + p[1][1] + p[2][1] + p[3][1]) / 4;
  return [ex[0], ex[1], ey[0], ey[1], cx - ex[0] * w / 2 - ey[0] * h / 2, cy - ex[1] * w / 2 - ey[1] * h / 2];
}
export function affineCSS(w, h, p) {
  const f = (v) => +v.toFixed(5);
  return `matrix(${fitAffine(w, h, p).map(f).join(',')})`;
}
// The card keeps the reference's perspective taper without a 3D (composited) transform: a matrix3d layer is
// rasterized at a scale that depends on frame history, which breaks seek(t) byte-determinism. Instead
//  - the glass frame (fill, gradient border, inner ring, shadow) is an SVG path through the exact homography;
//  - the label and every text row get their own 2D affine, fitted to that row's band of the homography, so
//    each line follows the taper (row slope and height change across the card) to a fraction of a pixel.
// Everything paints in the main layer and is a pure function of the quad.
const SVGNS = 'http://www.w3.org/2000/svg';
let cardSeq = 0;
function svgEl(tag, attrs, parent) {
  const e = document.createElementNS(SVGNS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (parent) parent.appendChild(e);
  return e;
}
const CARD_R = 21, CARD_BORDER = 2.5, CARD_RING = 4;
export class Card {
  constructor(parent, label, { w = 864, h = 438 } = {}) {
    this.w = w; this.h = h;
    this.root = el('div', 'card persp', parent);
    this.root.style.width = px(w); this.root.style.height = px(h);
    const id = `cardf${++cardSeq}`;
    this.svg = svgEl('svg', { class: 'cframe', width: 1920, height: 1080, viewBox: '0 0 1920 1080' }, this.root);
    const defs = svgEl('defs', {}, this.svg);
    const lg = svgEl('linearGradient', { id: `${id}g`, x1: 0, y1: 0, x2: 0, y2: 1 }, defs);
    svgEl('stop', { offset: 0, 'stop-color': '#5C5F66' }, lg); svgEl('stop', { offset: 1, 'stop-color': '#484B52' }, lg);
    const fl = svgEl('filter', { id: `${id}s`, x: '-0.3', y: '-0.5', width: '1.6', height: '2.0' }, defs);
    svgEl('feGaussianBlur', { stdDeviation: 20 }, fl);
    this.shadow = svgEl('path', { fill: '#000', 'fill-opacity': 0.28, filter: `url(#${id}s)`, transform: 'translate(0 12)' }, this.svg);
    this.fill = svgEl('path', { fill: 'rgb(38,39,44)', 'fill-opacity': 0.94 }, this.svg);
    this.ring = svgEl('path', { fill: 'none', stroke: '#20232A', 'stroke-width': CARD_RING }, this.svg);
    this.border = svgEl('path', { fill: 'none', stroke: `url(#${id}g)`, 'stroke-width': CARD_BORDER }, this.svg);
    this.label = el('div', 'clab', this.root);
    el('i', 'sq', this.label); el('span', '', this.label, label);
    this.body = el('div', 'cbody', this.root);
    this.rows = []; this.parts = null;
  }
  // rows: [{ key, tokens: [text...] }]; returns token spans grouped per row
  setRows(rows, keyCol = 11) {
    this.rows = rows.map((r) => {
      const line = el('div', 'crow', this.body);
      const key = el('span', 'ckey', line, r.key.padEnd(keyCol, ' '));
      const toks = r.tokens.map((tx, i) => {
        const s = el('span', `tok${r.cls ? ' ' + r.cls[i] : ''}`, line, tx);
        if (i < r.tokens.length - 1) line.appendChild(document.createTextNode(' '));
        return s;
      });
      if (r.gapAfter) line.style.marginBottom = `${r.gapAfter}px`;
      return { line, key, toks };
    });
    this.parts = null;
    return this.rows;
  }
  // untransformed layout boxes (card px) of the label and the rows; the text layout is static, so once
  measure() {
    const els = [this.label, ...this.rows.map((r) => r.line)];
    els.forEach((e) => { e.style.transform = 'none'; });
    const r0 = this.root.getBoundingClientRect();
    this.parts = els.map((e) => { const r = e.getBoundingClientRect(); return { e, x: r.left - r0.left, y: r.top - r0.top, w: r.width, h: r.height }; });
  }
  // the card's rounded rect inset by k (card px), mapped through the homography H, as an SVG path
  framePath(H, k) {
    const r = CARD_R - k, x0 = k, y0 = k, x1 = this.w - k, y1 = this.h - k, N = 8, pts = [];
    const corner = (cx, cy, a0) => { for (let i = 0; i <= N; i++) { const a = a0 + (i / N) * (Math.PI / 2); pts.push(H(cx + r * Math.cos(a), cy + r * Math.sin(a))); } };
    corner(x0 + r, y0 + r, Math.PI); corner(x1 - r, y0 + r, 1.5 * Math.PI); corner(x1 - r, y1 - r, 0); corner(x0 + r, y1 - r, 0.5 * Math.PI);
    return 'M' + pts.map(([x, y]) => `${x.toFixed(2)} ${y.toFixed(2)}`).join('L') + 'Z';
  }
  place(quad, opacity = 1) {
    const ok = opacity > 0.001 && quad;
    this.root.style.display = ok ? '' : 'none';
    if (!ok) return;
    this.root.style.opacity = opacity.toFixed(3);
    if (!this.parts) this.measure();
    const H = homography(this.w, this.h, quad), f = (v) => +v.toFixed(4);
    const outer = this.framePath(H, 0);
    this.fill.setAttribute('d', outer);
    this.shadow.setAttribute('d', outer);
    this.border.setAttribute('d', this.framePath(H, CARD_BORDER / 2));
    this.ring.setAttribute('d', this.framePath(H, CARD_BORDER + CARD_RING / 2));
    for (const pt of this.parts) {
      const q = [[pt.x, pt.y], [pt.x + pt.w, pt.y], [pt.x + pt.w, pt.y + pt.h], [pt.x, pt.y + pt.h]].map(([u, v]) => H(u, v));
      const [a, b, c, d, ox, oy] = fitAffine(pt.w, pt.h, q);
      pt.e.style.transform = `matrix(${f(a)},${f(b)},${f(c)},${f(d)},${f(ox - pt.x)},${f(oy - pt.y)})`;
    }
  }
}
// Project the 4 corners of a w x h px card that lives on a world plane (centre, yaw), at pxPerUnit scale.
export function cardQuad(ctx, center, yawDeg, wUnits, hUnits) {
  const THREE = ctx.THREE, yaw = (yawDeg * Math.PI) / 180;
  const ax = new THREE.Vector3(Math.cos(yaw), 0, -Math.sin(yaw));
  const pts = [[-1, 1], [1, 1], [1, -1], [-1, -1]].map(([sx, sy]) => {
    const v = center.clone().addScaledVector(ax, (sx * wUnits) / 2); v.y += (sy * hUnits) / 2;
    const p = ctx.project(v); return p;
  });
  if (pts.some((p) => p.z >= 1 || p.z <= -1)) return null;
  return pts.map((p) => [p.x, p.y]);
}

// streamed token state: newest token orange until the next lands
export function streamTokens(spans, times, t) {
  let newest = -1;
  spans.forEach((s, i) => { if (t >= times[i]) newest = i; });
  spans.forEach((s, i) => {
    const on = t >= times[i];
    s.style.visibility = on ? 'visible' : 'hidden';
    const orange = i === newest && (i < spans.length - 1 || t < times[i] + 0.12);
    s.classList.toggle('hot', on && orange);
  });
  return newest;
}
