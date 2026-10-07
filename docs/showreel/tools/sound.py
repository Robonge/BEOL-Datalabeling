#!/usr/bin/env python3
"""sound.py: the original score for the BEOL AX showreel (stdlib only, Python 3.14).

Renders exactly 15.000 s (720000 frames) of 48 kHz / 16-bit stereo PCM. Every cue sits on the
STORYBOARD.md beat grid (120 BPM, beat = 0.5 s, bar = 2.0 s) and on the event times in scenes/*.js.
Nothing is sampled: every sound is synthesized here from a fixed seed, so two runs give the same bytes.

Score (minimal tech explainer, D minor -> D major resolve):
  0.00  cold open: Dm9 pad in, soft kick, sub pulse; parser row ticks at 0.50 / 0.75 / 1.00
  1.00  noise riser -> 1.50 shatter impact (kick + sub boom + noise burst + glass shimmer)
  1.75  packet plucks on every plinth landing (1.75, 2.00, 2.25, 2.50)
  2.70  whip whoosh into the cut (2.75); pad to Bbmaj9, kick grid starts at 3.00
  3.20  orb shimmer + glass tinks for the six slide fragments; token ticks 3.50 ... 4.34, DONE 4.46, accent 4.50
  5.25  truck whoosh; Gm9; offbeat hats; conveyor hum 5.35 - 7.55 with a swell on the first FLAG (6.25)
        chip snaps (FLAG / PASS) at 6.25 + 0.236 i, docks + two-stroke check ticks
  7.75  truck whoosh; Fmaj9/A; 16th arp; Q ticks + high blip (8.00), A ticks + low blip (8.50),
        RULE chime + ring shimmer (9.00), RULE tokens 9.10 ... 9.50
 10.25  truck whoosh; Asus4 -> A7 (11.75) building; granular voxel resolve 10.30 - 11.85; hero plucks 11.45+
 12.50  drums out, soft whoosh, suck-in swell -> 13.00 warm Dmaj9 resolve hit + long reverb tail,
        chip-attach glass ticks 13.05 ... 13.21, tem_ref link 13.45; fade to digital silence at 15.000

DSP: polyBLEP saws, phase-integrated sines, FM bell, raised-cosine / exponential envelopes (every edge
ramped), TPT state-variable filters with time-varying cutoff, RBJ biquads, kick-keyed sidechain duck,
ping-pong feedback delay, Schroeder/Freeverb reverb (6 damped combs + 2 allpasses per channel), linked
soft-knee look-ahead limiter, BS.1770-4 loudness normalisation (default -14 LUFS) and a 4x true-peak
estimate (ceiling -1 dBTP). Verify with ffmpeg: -af ebur128=peak=true.

Usage:
  python sound.py                      # writes the default scratch path below
  python sound.py --out OUT.wav --target -14 --stems
"""
import argparse
import array
import math
import os
import random
import sys
import time
import wave

SR = 48000
DUR = 15.0
N = 720000  # = DUR * SR, exact
TWO_PI = 2.0 * math.pi
SEED = 20261007
OUT_DEFAULT = ("C:/Users/dltkd/AppData/Local/Temp/claude/C--Users-dltkd-Desktop-261004-BEOL-AX-day2/"
               "f214b36d-cb92-47c8-b169-da688c088fca/scratchpad/motion/sound/reel.wav")

sin, cos, exp, tan, pi = math.sin, math.cos, math.exp, math.tan, math.pi


def S(t):
    return int(round(t * SR))


def mtof(m):
    return 440.0 * 2.0 ** ((m - 69) / 12.0)


def zeros(n):
    return array.array('d', bytes(8 * n))


# ------------------------------------------------------------------------------------------ oscillators
def sine(freq, n, phase=0.0):
    inc = TWO_PI * freq / SR
    return [sin(phase + inc * i) for i in range(n)]


def saw_blep(freq, n, phase=0.0):
    """Band-limited sawtooth (polyBLEP), phase in [0, 1)."""
    out = [0.0] * n
    dt = freq / SR
    p = phase % 1.0
    hi = 1.0 - dt
    for i in range(n):
        v = 2.0 * p - 1.0
        if p < dt:
            x = p / dt
            v -= x + x - x * x - 1.0
        elif p > hi:
            x = (p - 1.0) / dt
            v -= x * x + x + x + 1.0
        out[i] = v
        p += dt
        if p >= 1.0:
            p -= 1.0
    return out


def noise(n, rng):
    r = rng.random
    return [2.0 * r() - 1.0 for _ in range(n)]


# ------------------------------------------------------------------------------------------ filters
def svf(x, fc, q=0.707, mode='lp', t0=0.0, step=32):
    """TPT state-variable filter. fc is Hz or a callable of absolute time (re-evaluated every `step`)."""
    n = len(x)
    y = [0.0] * n
    k = 1.0 / q
    ic1 = ic2 = 0.0
    dyn = callable(fc)
    if not dyn:
        step = n if n else 1
    i = 0
    nyq = 0.45 * SR
    while i < n:
        f = fc(t0 + i / SR) if dyn else fc
        f = 20.0 if f < 20.0 else (nyq if f > nyq else f)
        g = tan(pi * f / SR)
        a1 = 1.0 / (1.0 + g * (g + k))
        a2 = g * a1
        a3 = g * a2
        end = min(n, i + step)
        if mode == 'lp':
            for j in range(i, end):
                v3 = x[j] - ic2
                v1 = a1 * ic1 + a2 * v3
                v2 = ic2 + a2 * ic1 + a3 * v3
                ic1 = 2.0 * v1 - ic1
                ic2 = 2.0 * v2 - ic2
                y[j] = v2
        elif mode == 'bp':
            for j in range(i, end):
                v3 = x[j] - ic2
                v1 = a1 * ic1 + a2 * v3
                v2 = ic2 + a2 * ic1 + a3 * v3
                ic1 = 2.0 * v1 - ic1
                ic2 = 2.0 * v2 - ic2
                y[j] = v1
        else:  # hp
            for j in range(i, end):
                xv = x[j]
                v3 = xv - ic2
                v1 = a1 * ic1 + a2 * v3
                v2 = ic2 + a2 * ic1 + a3 * v3
                ic1 = 2.0 * v1 - ic1
                ic2 = 2.0 * v2 - ic2
                y[j] = xv - k * v1 - v2
        i = end
    return y


def biquad(x, b0, b1, b2, a1, a2):
    y = [0.0] * len(x)
    x1 = x2 = y1 = y2 = 0.0
    for i, v in enumerate(x):
        o = b0 * v + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        x2 = x1
        x1 = v
        y2 = y1
        y1 = o
        y[i] = o
    return y


def rbj_hp(f, q=0.707):
    w = TWO_PI * f / SR
    al = sin(w) / (2 * q)
    c = cos(w)
    a0 = 1 + al
    return ((1 + c) / 2 / a0, -(1 + c) / a0, (1 + c) / 2 / a0, -2 * c / a0, (1 - al) / a0)


def rbj_highshelf(f, gain_db, slope=0.8):
    A = 10 ** (gain_db / 40.0)
    w = TWO_PI * f / SR
    c, sn = cos(w), sin(w)
    al = sn / 2 * math.sqrt((A + 1 / A) * (1 / slope - 1) + 2)
    sa = 2 * math.sqrt(A) * al
    a0 = (A + 1) - (A - 1) * c + sa
    return (A * ((A + 1) + (A - 1) * c + sa) / a0, -2 * A * ((A - 1) + (A + 1) * c) / a0,
            A * ((A + 1) + (A - 1) * c - sa) / a0, 2 * ((A - 1) - (A + 1) * c) / a0,
            ((A + 1) - (A - 1) * c - sa) / a0)


def onepole_hp(x, fc):
    a = exp(-TWO_PI * fc / SR)
    y = [0.0] * len(x)
    lp = 0.0
    for i, v in enumerate(x):
        lp = v + a * (lp - v)
        y[i] = v - lp
    return y


# ------------------------------------------------------------------------------------------ envelopes
def env_asr(n, a, r):
    """Raised-cosine attack a s, flat, raised-cosine release r s ending at exactly 0."""
    e = [1.0] * n
    na = max(1, min(n, S(a)))
    for i in range(na):
        e[i] = 0.5 - 0.5 * cos(pi * i / na)
    nr = max(1, min(n, S(r)))
    for i in range(nr):
        k = n - nr + i
        e[k] *= 0.5 + 0.5 * cos(pi * (i + 1) / nr)
    return e


def env_perc(n, a, tau, tail=0.006):
    """Linear attack a s, exponential decay tau s, raised-cosine taper over the last `tail` s."""
    e = [0.0] * n
    na = max(1, S(a))
    m = exp(-1.0 / (tau * SR))
    v = 1.0
    for i in range(n):
        if i < na:
            e[i] = i / na
        else:
            e[i] = v
            v *= m
    nt = max(1, min(n, S(tail)))
    for i in range(nt):
        e[n - nt + i] *= 0.5 + 0.5 * cos(pi * (i + 1) / nt)
    return e


def mul(x, e):
    return [a * b for a, b in zip(x, e)]


def keys_curve(keys, n0, n):
    """Raised-cosine interpolation through (t, value) keys, sampled from frame n0 for n frames."""
    out = [keys[-1][1]] * n
    for (ta, va), (tb, vb) in zip(keys, keys[1:]):
        ia, ib = max(S(ta), n0), min(S(tb), n0 + n)
        span = S(tb) - S(ta)
        if ib <= ia or span <= 0:
            continue
        for i in range(ia, ib):
            u = (i - S(ta)) / span
            out[i - n0] = va + (vb - va) * (0.5 - 0.5 * cos(pi * u))
    if keys and S(keys[0][0]) > n0:
        for i in range(0, min(n, S(keys[0][0]) - n0)):
            out[i] = keys[0][1]
    return out


# ------------------------------------------------------------------------------------------ mixer
class Mixer:
    BUSES = ('dry', 'duck', 'rev', 'dly')

    def __init__(self, stems=False):
        self.bus = {k: (zeros(N), zeros(N)) for k in self.BUSES}
        self.stems = {} if stems else None
        self.stem = 'misc'
        self.kicks = []  # (t, depth) keys for the sidechain duck

    def emit(self, sig, t0, gain=1.0, pan=0.0, rev=0.0, dly=0.0, duck=False, right=None):
        i0 = S(t0)
        off = 0
        if i0 < 0:
            off, i0 = -i0, 0
        n = min(len(sig) - off, N - i0)
        if n <= 0:
            return
        a = (pan + 1.0) * pi / 4.0
        gl = cos(a) * math.sqrt(2.0) * gain
        gr = sin(a) * math.sqrt(2.0) * gain
        rs = right if right is not None else sig
        targets = [(self.bus['duck' if duck else 'dry'], 1.0)]
        if rev:
            targets.append((self.bus['rev'], rev))
        if dly:
            targets.append((self.bus['dly'], dly))
        if self.stems is not None:
            if self.stem not in self.stems:
                self.stems[self.stem] = (zeros(N), zeros(N))
            targets.append((self.stems[self.stem], 1.0))
        for (bl, br), s in targets:
            l, r = gl * s, gr * s
            for k in range(n):
                bl[i0 + k] += sig[off + k] * l
                br[i0 + k] += rs[off + k] * r


# ------------------------------------------------------------------------------------------ instruments
def kick(m, t, vel=1.0, rng=None, duck=0.55):
    m.stem = 'kick'
    n = S(0.36)
    out = [0.0] * n
    ph = 0.0
    for i in range(n):
        tt = i / SR
        f = 47.0 + 108.0 * exp(-tt / 0.021) + 22.0 * exp(-tt / 0.09)
        ph += TWO_PI * f / SR
        out[i] = sin(ph)
    out = mul(out, env_perc(n, 0.0008, 0.105, 0.03))
    d = math.tanh(1.7)
    out = [math.tanh(1.7 * v) / d for v in out]
    nc = S(0.006)
    click = svf(noise(nc, rng), 3500.0, 0.7, 'hp')
    click = mul(click, env_perc(nc, 0.0002, 0.0012, 0.002))
    for i in range(nc):
        out[i] += 0.22 * click[i]
    m.emit(out, t, 0.85 * vel)
    m.kicks.append((t, duck * min(1.0, vel)))


def hat(m, t, vel, pan, rng, open_=False):
    m.stem = 'hats'
    n = S(0.16 if open_ else 0.05)
    x = svf(noise(n, rng), 7800.0, 0.8, 'hp')
    x2 = svf(x, 11000.0, 1.2, 'bp')
    x = [0.6 * a + 0.8 * b for a, b in zip(x, x2)]
    x = mul(x, env_perc(n, 0.0004, 0.045 if open_ else 0.011, 0.008))
    m.emit(x, t, 0.28 * vel, pan, rev=0.06)


def sub_track(m, roots, keys):
    """Continuous sub sine (+2nd/3rd harmonic), phase-continuous root glides, beat pulse, ducked."""
    m.stem = 'sub'
    amp = keys_curve(keys, 0, N)
    out = [0.0] * N
    ph = 0.0
    f = mtof(roots[0][1])
    glide = 1.0 - exp(-1.0 / (0.035 * SR))
    ri = 0
    for i in range(N):
        a = amp[i]
        if ri + 1 < len(roots) and i >= S(roots[ri + 1][0]):
            ri += 1
        ft = mtof(roots[ri][1])
        f += (ft - f) * glide
        ph += TWO_PI * f / SR
        if ph > TWO_PI:
            ph -= TWO_PI
        if a == 0.0:
            continue
        pulse = 0.86 + 0.14 * cos(TWO_PI * (i / SR) / 0.5)
        out[i] = a * pulse * (sin(ph) + 0.24 * sin(2.0 * ph) + 0.07 * sin(3.0 * ph))
    m.emit(out, 0.0, 0.42, duck=True)


def pad(m, t0, t1, notes, gain, cutoff, rng, atk=0.08, rel=0.35, rev=0.32):
    m.stem = 'pad'
    n = S(t1 - t0 + rel)
    L = [0.0] * n
    R = [0.0] * n
    w = 1.0 / len(notes)
    for note in notes:
        f = mtof(note)
        a = saw_blep(f * 2 ** (-7 / 1200), n, rng.random())
        b = saw_blep(f * 2 ** (6 / 1200), n, rng.random())
        for i in range(n):
            av, bv = a[i], b[i]
            L[i] += (0.8 * av + 0.3 * bv) * w
            R[i] += (0.8 * bv + 0.3 * av) * w
    L = svf(L, cutoff, 0.62, 'lp', t0)
    R = svf(R, cutoff, 0.62, 'lp', t0)
    e = env_asr(n, atk, rel)
    m.emit(mul(L, e), t0, gain, right=mul(R, e), duck=True, rev=rev)


def pluck(m, t, midi, gain, pan=0.0, bright=5200.0, tau=0.22, dly=0.3, rev=0.2, duck=False, stem='pluck'):
    m.stem = stem
    n = S(min(0.9, tau * 4.0 + 0.05))
    f = mtof(midi)
    a = saw_blep(f, n, 0.0)
    s = sine(f, n)
    s2 = sine(2.0 * f, n)
    x = [0.5 * a[i] + 0.55 * s[i] + 0.18 * s2[i] for i in range(n)]
    x = svf(x, lambda tt: 380.0 + bright * exp(-(tt - t) / 0.055), 0.9, 'lp', t)
    x = mul(x, env_perc(n, 0.0015, tau, 0.02))
    m.emit(x, t, gain, pan, rev=rev, dly=dly, duck=duck)


def tick(m, t, f=3800.0, vel=1.0, pan=0.0, rng=None, rev=0.07, tau=0.0032):
    m.stem = 'ticks'
    n = S(0.03)
    x = mul(sine(f, n), env_perc(n, 0.0003, tau, 0.004))
    nc = S(0.004)
    c = mul(svf(noise(nc, rng), 6000.0, 0.7, 'hp'), env_perc(nc, 0.0001, 0.0007, 0.001))
    for i in range(nc):
        x[i] += 0.55 * c[i]
    m.emit(x, t, 0.30 * vel, pan, rev=rev)


def blip(m, t, f0, f1, dur, gain, pan=0.0):
    m.stem = 'blips'
    n = S(dur)
    out = [0.0] * n
    ph = 0.0
    tg = dur * 0.45
    for i in range(n):
        u = min(1.0, (i / SR) / tg)
        f = f0 * (f1 / f0) ** (1.0 - (1.0 - u) ** 2)
        ph += TWO_PI * f / SR
        out[i] = sin(ph) + 0.18 * sin(2.0 * ph)
    out = mul(out, env_perc(n, 0.0012, dur / 3.2, 0.01))
    m.emit(out, t, gain, pan, rev=0.22, dly=0.18)


def chime(m, t, f, gain, pan=0.0, dur=1.9):
    m.stem = 'shimmer'
    n = S(dur)
    out = [0.0] * n
    wc = TWO_PI * f / SR
    wm = wc * 3.5
    w2 = wc * 2.756
    for i in range(n):
        tt = i / SR
        ind = 2.2 * exp(-tt / 0.32)
        out[i] = sin(wc * i + ind * sin(wm * i)) + 0.32 * sin(w2 * i) * exp(-tt / 0.22)
    out = mul(out, env_perc(n, 0.0015, 0.62, 0.05))
    m.emit(out, t, gain, pan, rev=0.55, dly=0.15)


def shimmer(m, t0, dur, base, gain, rng, atk=0.25, rel=0.6, rev=0.6):
    m.stem = 'shimmer'
    n = S(dur)
    L = [0.0] * n
    R = [0.0] * n
    ratios = (1.0, 1.498, 2.013, 2.997, 4.03, 5.11)
    amps = (1.0, 0.7, 0.55, 0.38, 0.26, 0.18)
    for k, (rt, am) in enumerate(zip(ratios, amps)):
        inc = TWO_PI * base * rt / SR
        ph = rng.random() * TWO_PI
        linc = TWO_PI * rng.uniform(1.5, 6.5) / SR
        lph = rng.random() * TWO_PI
        main, other = (L, R) if k % 2 == 0 else (R, L)
        for i in range(n):
            v = am * sin(ph + inc * i) * (0.6 + 0.4 * sin(lph + linc * i))
            main[i] += v
            other[i] += 0.3 * v
    e = env_asr(n, atk, rel)
    m.emit(mul(L, e), t0, gain / 3.0, right=mul(R, e), rev=rev)


def glass_tink(m, t, f, gain, pan, rng):
    m.stem = 'shimmer'
    n = S(0.35)
    x = [0.0] * n
    for rt, am, tau in ((1.0, 1.0, 0.09), (2.32, 0.5, 0.05), (4.25, 0.25, 0.03)):
        inc = TWO_PI * f * rt / SR
        md = exp(-1.0 / (tau * SR))
        v = am
        for i in range(n):
            x[i] += v * sin(inc * i)
            v *= md
    x = mul(x, env_perc(n, 0.0004, 10.0, 0.02))
    m.emit(x, t, gain, pan, rev=0.45)


def whoosh(m, tp, tin, tout, f0, f1, f2, pan0, pan1, gain, rng, q=0.95, rev=0.22, shape_in=2.2):
    m.stem = 'whoosh'
    t0 = tp - tin
    n = S(tin + tout)

    def fc(tt):
        u = tt - t0
        if u < tin:
            return f0 * (f1 / f0) ** ((u / tin) ** 1.3)
        return f1 * (f2 / f1) ** (((u - tin) / tout) ** 0.8)

    nl, nr = noise(n, rng), noise(n, rng)
    bl, br = svf(nl, fc, q, 'bp', t0), svf(nr, fc, q, 'bp', t0)
    ll, lr = svf(nl, fc, 0.6, 'lp', t0), svf(nr, fc, 0.6, 'lp', t0)
    nin = S(tin)
    L = [0.0] * n
    R = [0.0] * n
    for i in range(n):
        if i < nin:
            e = (i / nin) ** shape_in
        else:
            e = (1.0 - (i - nin) / (n - nin)) ** 1.7
        u = i / n
        u = u * u * (3.0 - 2.0 * u)
        p = pan0 + (pan1 - pan0) * u
        a = (p + 1.0) * pi / 4.0
        L[i] = (bl[i] + 0.35 * ll[i]) * e * cos(a) * 1.4142
        R[i] = (br[i] + 0.35 * lr[i]) * e * sin(a) * 1.4142
    tail = env_asr(n, 0.004, 0.012)
    m.emit(mul(L, tail), t0, gain, right=mul(R, tail), rev=rev)


def riser(m, t0, t1, gain, rng):
    m.stem = 'whoosh'
    n = S(t1 - t0)
    d = t1 - t0
    fc = lambda tt: 320.0 * (6500.0 / 320.0) ** ((tt - t0) / d)
    nl, nr = noise(n, rng), noise(n, rng)
    bl, br = svf(nl, fc, 1.6, 'bp', t0), svf(nr, fc, 1.6, 'bp', t0)
    ph = 0.0
    L = [0.0] * n
    R = [0.0] * n
    for i in range(n):
        u = i / n
        f = 190.0 * 4.0 ** u
        ph += TWO_PI * f / SR
        trem = 0.75 + 0.25 * sin(TWO_PI * (8.0 + 18.0 * u) * u * d)
        tone = 0.22 * sin(ph) * trem
        e = u ** 2.0
        L[i] = (bl[i] + tone) * e
        R[i] = (br[i] + tone) * e
    tail = env_asr(n, 0.004, 0.014)
    m.emit(mul(L, tail), t0, gain, right=mul(R, tail), rev=0.3)


def boom(m, t, f, gain, dur=1.2, tau=0.55):
    m.stem = 'sub'
    n = S(dur)
    out = [0.0] * n
    ph = 0.0
    for i in range(n):
        tt = i / SR
        ff = f * (1.0 + 0.6 * exp(-tt / 0.05))
        ph += TWO_PI * ff / SR
        out[i] = sin(ph) + 0.2 * sin(2.0 * ph)
    out = mul(out, env_perc(n, 0.002, tau, 0.08))
    m.emit(out, t, gain)


def noise_burst(m, t, gain, rng, dur=0.8):
    m.stem = 'whoosh'
    n = S(dur)
    fc = lambda tt: 250.0 + 8500.0 * exp(-(tt - t) / 0.11)
    L = svf(noise(n, rng), fc, 0.7, 'lp', t)
    R = svf(noise(n, rng), fc, 0.7, 'lp', t)
    e = env_perc(n, 0.001, 0.16, 0.05)
    m.emit(mul(L, e), t, gain, right=mul(R, e), rev=0.4)


def hum(m, t0, t1, swell_t, rng):
    m.stem = 'hum'
    n = S(t1 - t0)
    a = saw_blep(mtof(43), n, rng.random())
    b = saw_blep(mtof(50) * 1.003, n, rng.random())
    c = saw_blep(mtof(43) * 0.997, n, rng.random())
    L = [0.5 * a[i] + 0.35 * b[i] for i in range(n)]
    R = [0.5 * c[i] + 0.35 * b[i] for i in range(n)]
    fc = lambda tt: 170.0 + 900.0 * exp(-((tt - swell_t) / 0.28) ** 2) + 40.0 * sin(TWO_PI * 0.9 * tt)
    L, R = svf(L, fc, 1.1, 'lp', t0), svf(R, fc, 1.1, 'lp', t0)
    sw = keys_curve([(t0, 0.0), (t0 + 0.35, 0.7), (swell_t - 0.3, 0.75), (swell_t, 1.0),
                     (swell_t + 0.45, 0.7), (t1 - 0.3, 0.6), (t1, 0.0)], S(t0), n)
    m.emit(mul(L, sw), t0, 0.42, right=mul(R, sw), duck=True, rev=0.2)


def grains(m, t0, t1, count, rng, gain=0.09, fmin=1300.0, fmax=5600.0, bump=True):
    m.stem = 'grains'
    for _ in range(count):
        u = (rng.random() + rng.random() + rng.random()) / 3.0 if bump else rng.random()
        t = t0 + u * (t1 - t0)
        f = rng.uniform(fmin, fmax)
        dur = rng.uniform(0.006, 0.016)
        n = S(dur)
        x = [sin(TWO_PI * f * i / SR) * (0.5 - 0.5 * cos(TWO_PI * i / n)) for i in range(n)]
        m.emit(x, t, gain * rng.uniform(0.5, 1.0), rng.uniform(-0.8, 0.8), rev=0.25)


def resolve_chord(m, t, rng):
    """Warm Dmaj9 hit: detuned saws through a closing low-pass + soft additive keys, long reverb send."""
    m.stem = 'resolve'
    n = N - S(t)
    notes = (38, 45, 54, 61, 64, 69)  # D2 A2 F#3 C#4 E4 A4
    L = [0.0] * n
    R = [0.0] * n
    w = 1.0 / len(notes)
    for note in notes:
        f = mtof(note)
        a = saw_blep(f * 2 ** (-6 / 1200), n, rng.random())
        b = saw_blep(f * 2 ** (6 / 1200), n, rng.random())
        for i in range(n):
            av, bv = a[i], b[i]
            L[i] += (0.8 * av + 0.3 * bv) * w
            R[i] += (0.8 * bv + 0.3 * av) * w
    fc = lambda tt: 620.0 + 2600.0 * exp(-(tt - t) / 0.75)
    L, R = svf(L, fc, 0.7, 'lp', t), svf(R, fc, 0.7, 'lp', t)
    # keys body (additive, decaying partials)
    K = [0.0] * n
    for note in (66, 69, 73, 76):  # F#4 A4 C#5 E5
        f = mtof(note)
        for h, am, tau in ((1, 1.0, 1.6), (2, 0.38, 0.7), (3, 0.16, 0.4), (4, 0.08, 0.25)):
            inc = TWO_PI * f * h / SR
            md = exp(-1.0 / (tau * SR))
            v = am * 0.25
            for i in range(n):
                K[i] += v * sin(inc * i)
                v *= md
    e = [0.0] * n
    na = S(0.006)
    for i in range(n):
        tt = i / SR
        body = 0.55 + 0.45 * exp(-tt / 0.35)
        e[i] = (i / na if i < na else 1.0) * body * exp(-tt / 2.4)
    tail = env_asr(n, 0.0005, 0.01)
    L = [(L[i] + 0.45 * K[i]) * e[i] * tail[i] for i in range(n)]
    R = [(R[i] + 0.45 * K[i]) * e[i] * tail[i] for i in range(n)]
    m.emit(L, t, 1.5, right=R, rev=0.5)


# ------------------------------------------------------------------------------------------ effects
def reverb(xl, xr):
    """Freeverb-style: HP 180 Hz, 18 ms predelay, 6 damped combs + 2 allpasses per channel."""
    pre = S(0.018)
    hl = onepole_hp(xl, 180.0)
    hr = onepole_hp(xr, 180.0)
    hl = [0.0] * pre + hl[:len(hl) - pre]
    hr = [0.0] * pre + hr[:len(hr) - pre]
    combs = ((1687, 1601, 1867, 1777, 1949, 1523), (1709, 1627, 1889, 1801, 1973, 1549))
    aps = ((607, 487), (631, 503))
    fb, damp = 0.86, 0.32
    outs = []
    for ch, x in enumerate((hl, hr)):
        n = len(x)
        acc = [0.0] * n
        for Lc in combs[ch]:
            buf = [0.0] * Lc
            idx = 0
            f = 0.0
            d1 = 1.0 - damp
            for i in range(n):
                o = buf[idx]
                f = o * d1 + f * damp
                buf[idx] = x[i] + f * fb
                acc[i] += o
                idx += 1
                if idx == Lc:
                    idx = 0
        y = acc
        for La in aps[ch]:
            buf = [0.0] * La
            idx = 0
            z = [0.0] * n
            for i in range(n):
                bo = buf[idx]
                v = y[i]
                z[i] = bo - v
                buf[idx] = v + bo * 0.5
                idx += 1
                if idx == La:
                    idx = 0
            y = z
        outs.append([v * (1.0 / 6.0) for v in y])
    return outs


def pingpong(xl, xr, dt=0.375, fb=0.36, lp=3600.0):
    D = S(dt)
    bl = [0.0] * D
    br = [0.0] * D
    a = 1.0 - exp(-TWO_PI * lp / SR)
    fl = fr = 0.0
    n = len(xl)
    yl = [0.0] * n
    yr = [0.0] * n
    idx = 0
    for i in range(n):
        ol = bl[idx]
        orr = br[idx]
        fl += a * (ol - fl)
        fr += a * (orr - fr)
        bl[idx] = 0.5 * (xl[i] + xr[i]) + fr * fb
        br[idx] = fl * fb
        yl[i] = ol
        yr[i] = orr
        idx += 1
        if idx == D:
            idx = 0
    return yl, yr


def duck_curve(kicks):
    d = [1.0] * N
    na, nh, nr = S(0.004), S(0.03), S(0.22)
    for t, depth in kicks:
        i0 = S(t)
        for k in range(na + nh + nr):
            i = i0 + k
            if i >= N:
                break
            if k < na:
                s = k / na
            elif k < na + nh:
                s = 1.0
            else:
                s = 0.5 + 0.5 * cos(pi * (k - na - nh) / nr)
            v = 1.0 - depth * s
            if v < d[i]:
                d[i] = v
    return d


# ------------------------------------------------------------------------------------------ metering
def k_weight(x):
    y = biquad(x, 1.53512485958697, -2.69169618940638, 1.19839281085285, -1.69065929318241, 0.73248077421585)
    return biquad(y, 1.0, -2.0, 1.0, -1.99004745483398, 0.99007225036621)


def lufs(L, R, short_term=False):
    """BS.1770-4 integrated loudness (and optional 3 s short-term values every 0.5 s)."""
    kl, kr = k_weight(L), k_weight(R)
    n = len(kl)
    cs = [0.0] * (n + 1)
    acc = 0.0
    for i in range(n):
        a, b = kl[i], kr[i]
        acc += a * a + b * b
        cs[i + 1] = acc
    blk, hop = S(0.4), S(0.1)
    blocks = []
    for s0 in range(0, n - blk + 1, hop):
        blocks.append((cs[s0 + blk] - cs[s0]) / blk)
    ld = lambda z: -0.691 + 10.0 * math.log10(z) if z > 0 else -200.0
    g1 = [z for z in blocks if ld(z) > -70.0]
    if not g1:
        return -200.0, []
    rel = ld(sum(g1) / len(g1)) - 10.0
    g2 = [z for z in g1 if ld(z) > rel]
    I = ld(sum(g2) / len(g2))
    st = []
    if short_term:
        w = S(3.0)
        for e in range(S(0.5), n + 1, S(0.5)):
            s0 = max(0, e - w)
            st.append((e / SR, ld((cs[e] - cs[s0]) / max(1, e - s0))))
    return I, st


def true_peak_est(L, R, thr):
    """4x windowed-sinc oversampled peak, evaluated only around samples above `thr` (linear)."""
    taps = 12
    phases = (0.25, 0.5, 0.75)
    kern = []
    for ph in phases:
        row = []
        for k in range(-taps + 1, taps + 1):
            x = k - ph
            w = 0.5 + 0.5 * cos(pi * x / taps)
            row.append((sin(pi * x) / (pi * x)) * w)
        kern.append(row)
    peak = 0.0
    n = len(L)
    for X in (L, R):
        for i in range(n):
            v = abs(X[i])
            if v > peak:
                peak = v
            if v < thr or i < taps or i >= n - taps - 1:
                continue
            for row in kern:
                s = 0.0
                for j, c in enumerate(row):
                    s += X[i + j - taps + 1] * c
                if abs(s) > peak:
                    peak = abs(s)
                # also between i-1 and i
                s = 0.0
                for j, c in enumerate(row):
                    s += X[i - 1 + j - taps + 1] * c
                if abs(s) > peak:
                    peak = abs(s)
    return 20.0 * math.log10(peak) if peak > 0 else -200.0


def limiter(L, R, ceil_db, knee_db=4.0, att=0.0015, relt=0.07):
    """Linked soft-knee brick-wall limiter with look-ahead (backward attack smoothing)."""
    n = len(L)
    T = ceil_db
    W = knee_db
    lo = 10 ** ((T - W / 2) / 20.0)
    gr = [1.0] * n
    for i in range(n):
        a = abs(L[i])
        b = abs(R[i])
        x = a if a > b else b
        if x <= lo:
            continue
        xd = 20.0 * math.log10(x)
        if xd < T + W / 2:
            red = -((xd - T + W / 2) ** 2) / (2 * W)
        else:
            red = T - xd
        gr[i] = 10 ** (red / 20.0)
    aa = 1.0 - exp(-1.0 / (att * SR))
    ar = 1.0 - exp(-1.0 / (relt * SR))
    g = 1.0
    for i in range(n - 1, -1, -1):  # backward: ramp down ahead of every peak
        g = g + (1.0 - g) * aa
        if gr[i] < g:
            g = gr[i]
        gr[i] = g
    g = 1.0
    for i in range(n):  # forward: smooth release
        g = g + (1.0 - g) * ar
        if gr[i] < g:
            g = gr[i]
        gr[i] = g
    return [L[i] * gr[i] for i in range(n)], [R[i] * gr[i] for i in range(n)], min(gr)


# ------------------------------------------------------------------------------------------ score
T_STEPS = (2.5, 5.0, 7.5, 10.0, 12.5)


def compose(m, rng):
    # --- pad chords: change on the cut / headline rise (T + 0.25), resolve at 13.00
    def cut_fc(base, top, t_a, t_b):
        return lambda tt: base + (top - base) * min(1.0, max(0.0, (tt - t_a) / (t_b - t_a)))

    hook_fc = lambda tt: 650.0 + 500.0 * min(1.0, tt / 1.5) + 700.0 * exp(-((tt - 1.55) / 0.25) ** 2)
    pad(m, 0.0, 2.75, (50, 57, 64, 69, 72), 0.38, hook_fc, rng, atk=0.22, rel=0.25)        # Dm9
    pad(m, 2.72, 5.25, (46, 53, 57, 60, 62), 0.46, cut_fc(850, 1100, 2.75, 5.0), rng)       # Bbmaj9
    pad(m, 5.22, 7.75, (43, 50, 57, 58, 65), 0.54, cut_fc(1050, 1400, 5.25, 7.5), rng)      # Gm9
    pad(m, 7.72, 10.25, (45, 53, 60, 64, 67), 0.56, cut_fc(1350, 1800, 7.75, 10.0), rng)    # Fmaj9/A
    pad(m, 10.22, 11.75, (45, 52, 55, 62, 64), 0.66, cut_fc(1700, 2300, 10.25, 11.75), rng)  # A7sus4
    pad(m, 11.72, 12.95, (45, 52, 55, 61, 64), 0.72, cut_fc(2300, 3200, 11.75, 12.5), rng, rel=0.12)  # A7

    # --- sub: roots follow the pad; ducked by the kick grid
    roots = [(0.0, 38), (2.75, 34), (5.25, 31), (7.75, 33), (10.25, 33)]
    keys = [(0.0, 0.0), (0.12, 0.36), (0.95, 0.36), (1.45, 0.15), (1.7, 0.15), (1.95, 0.36), (2.45, 0.36),
            (2.62, 0.15), (2.85, 0.8), (5.0, 0.8), (5.12, 0.6), (5.35, 0.85), (7.5, 0.85), (7.62, 0.6),
            (7.85, 0.9), (10.0, 0.9), (10.12, 0.65), (10.35, 0.95), (12.3, 1.0), (12.55, 0.35), (12.92, 0.0),
            (15.0, 0.0)]
    sub_track(m, roots, keys)

    # --- kick grid
    kick(m, 0.0, 0.55, rng, duck=0.25)
    kick(m, 1.5, 1.2, rng, duck=0.7)
    t = 3.0
    while t <= 12.0 + 1e-9:
        base = 0.62 if t < 5.0 else 0.8 if t < 7.5 else 0.86 if t < 10.0 else 0.94
        acc = 0.08 if abs(t - round(t / 2.0) * 2.0) < 1e-6 else 0.0
        kick(m, t, base + acc, rng)
        t += 0.5
    kick(m, 13.0, 0.85, rng, duck=0.0)

    # --- hats: offbeat 8ths from STEP 02, 16ths from STEP 03, denser and louder in STEP 04
    t = 5.25
    j = 0
    while t < 12.4:
        v = 0.55 if t < 7.5 else 0.65 if t < 10.0 else 0.75 + 0.15 * (t - 10.0) / 2.4
        hat(m, t, v, 0.22 if j % 2 else -0.22, rng, open_=(t > 7.5 and abs((t - 0.75) % 2.0) < 1e-6))
        t += 0.5
        j += 1
    t = 7.875
    while t < 12.45:
        v = 0.26 if t < 10.0 else 0.32 + 0.2 * (t - 10.0) / 2.4
        hat(m, t, v, rng.uniform(-0.45, 0.45), rng)
        t += 0.25

    # --- arp: building per step (8ths -> 16ths, filter opening)
    def arp(t0, t1, step, notes, gain, bright, dly=0.32):
        k = 0
        tt = t0
        while tt < t1 - 1e-9:
            pluck(m, tt, notes[k % len(notes)], gain, pan=(-0.35 if k % 2 == 0 else 0.35), bright=bright,
                  tau=0.10 if step < 0.2 else 0.14, dly=dly, rev=0.15, duck=True, stem='arp')
            k += 1
            tt += step
    arp(2.75, 4.95, 0.25, (70, 74, 77, 81, 84, 81, 77, 74), 0.40, 1900.0)
    arp(5.25, 7.45, 0.25, (67, 70, 74, 77, 81, 77, 74, 70, 79, 74), 0.44, 2500.0)
    arp(7.75, 9.95, 0.125, (69, 72, 76, 79, 81, 79, 76, 72), 0.38, 3000.0)
    arp(10.25, 11.75, 0.125, (69, 74, 76, 79, 81, 79, 76, 74), 0.43, 3800.0)
    arp(11.75, 12.45, 0.125, (69, 73, 76, 79, 81, 85, 81, 79), 0.48, 4800.0)

    # --- HOOK: parser row ticks, riser, shatter
    for i, tr in enumerate((0.5, 0.75, 1.0)):
        tick(m, tr, 2700.0 + 450.0 * i, 0.9, -0.15 + 0.15 * i, rng)
    riser(m, 1.0, 1.5, 0.55, rng)
    boom(m, 1.5, 55.0, 0.55)
    noise_burst(m, 1.5, 0.40, rng)
    whoosh(m, 1.56, 0.06, 0.75, 7000.0, 3500.0, 450.0, -0.2, 0.2, 0.55, rng, q=0.7, rev=0.35)
    shimmer(m, 1.5, 1.05, 1480.0, 0.30, rng, atk=0.03, rel=0.7)

    # --- OVERVIEW: packet plucks on each landing (ascending)
    for tl, note in zip((1.75, 2.0, 2.25, 2.5), (74, 76, 81, 84)):
        pluck(m, tl, note, 0.40, pan=-0.5 + 0.33 * (tl - 1.75) / 0.25, bright=6000.0, tau=0.2, dly=0.35)

    # --- transitions: whip and trucks (content exits left, so the air moves right -> left)
    whoosh(m, 2.70, 0.42, 0.42, 380.0, 5200.0, 800.0, 0.75, -0.75, 0.85, rng)
    for T in (5.0, 7.5, 10.0):
        whoosh(m, T + 0.25, 0.62, 0.52, 300.0, 4200.0, 650.0, 0.65, -0.65, 0.78, rng)
    # STEP 01 orb: low glass bed + six fragment tinks (absorbed 3.20 ... 3.45)
    shimmer(m, 2.80, 1.9, 1108.7, 0.13, rng, atk=0.4, rel=0.6, rev=0.5)
    for i in range(6):
        glass_tink(m, 3.20 + 0.05 * i, 5200.0 + 380.0 * i, 0.07, -0.6 + 0.08 * i, rng)

    # --- STEP 01 tokens (03_label TOKENS_T), DONE, tem_ref accent
    for i, tt in enumerate((3.50, 3.62, 3.74, 3.86, 3.98, 4.10, 4.22, 4.34)):
        tick(m, tt, 3600.0 + (230.0 if i % 2 else 0.0) + 40.0 * i, 0.75, 0.25 + 0.03 * i, rng)
    tick(m, 4.46, 5200.0, 0.85, 0.35, rng)
    tick(m, 4.49, 6300.0, 0.7, 0.35, rng)
    pluck(m, 4.50, 81, 0.34, pan=0.3, bright=4500.0, tau=0.25, dly=0.35, rev=0.3)

    # --- STEP 02: conveyor hum + flag swell, chip snaps, docks and two-stroke checks (04_verify)
    hum(m, 5.35, 7.55, 6.25, rng)
    whoosh(m, 6.25, 0.55, 0.12, 900.0, 2600.0, 1800.0, -0.1, 0.1, 0.22, rng, q=1.4, rev=0.3, shape_in=3.0)
    leave = [6.25 + 0.72 * i / 3.05 for i in range(6)]
    kinds = ('flag', 'pass', 'flag', 'flag', 'pass', 'pass')
    for tl, kd in zip(leave, kinds):
        if kd == 'flag':
            tick(m, tl, 2900.0, 0.9, -0.1, rng)
            blip(m, tl, 990.0, 660.0, 0.09, 0.13, 0.1)
        else:
            tick(m, tl, 4800.0, 0.55, 0.2, rng)
            grains(m, tl + 0.098, tl + 0.16, 8, rng, gain=0.05, fmin=4200.0, fmax=7000.0, bump=False)
    for td in (6.70, 6.70 + 0.472, 6.70 + 0.708):
        blip(m, td, 600.0, 470.0, 0.07, 0.18, 0.45)
        tick(m, td + 0.10, 5000.0, 0.7, 0.5, rng)
        tick(m, td + 0.135, 6100.0, 0.55, 0.5, rng)

    # --- STEP 03: Q ticks + Q blip, A ticks + lower blip, RULE chime + ring shimmer + RULE tokens
    for tt in (7.85, 7.95, 8.05, 8.15):
        tick(m, tt, 4000.0, 0.65, -0.3, rng)
    blip(m, 8.00, 1320.0, 1980.0, 0.11, 0.22, -0.35)
    for tt in (8.44, 8.52, 8.60):
        tick(m, tt, 3300.0, 0.6, 0.3, rng)
    blip(m, 8.50, 990.0, 740.0, 0.12, 0.22, 0.35)
    chime(m, 9.00, mtof(88), 0.12, 0.0)
    shimmer(m, 9.00, 0.95, 1318.5, 0.22, rng, atk=0.04, rel=0.6)
    for i, tt in enumerate((9.10, 9.20, 9.30, 9.40, 9.50)):
        tick(m, tt, 3800.0 + 120.0 * i, 0.7, 0.1, rng)

    # --- STEP 04: granular voxel resolve (density follows the inOutSine resolve clock), hero plucks
    grains(m, 10.30, 11.85, 90, rng, gain=0.085)
    grains(m, 10.30, 11.22, 25, rng, gain=0.05, fmin=2500.0, fmax=7500.0, bump=False)
    for k, note in enumerate((81, 85, 88, 93)):
        pluck(m, 11.45 + 0.05 * k, note, 0.26, pan=-0.3 + 0.2 * k, bright=6500.0, tau=0.22, dly=0.3, rev=0.3)
    shimmer(m, 11.45, 0.95, 1760.0, 0.16, rng, atk=0.05, rel=0.55)
    tick(m, 11.70, 5600.0, 0.6, 0.45, rng)

    # --- CLOSE: soft whoosh (block flies apart), suck-in swell, warm resolve + tail, chip attach ticks
    whoosh(m, 12.85, 0.35, 0.25, 500.0, 3000.0, 1200.0, -0.4, 0.4, 0.38, rng)
    whoosh(m, 12.985, 0.48, 0.02, 1500.0, 9000.0, 9000.0, 0.0, 0.0, 0.28, rng, q=0.8, rev=0.1, shape_in=3.2)
    resolve_chord(m, 13.0, rng)
    boom(m, 13.0, 36.71, 0.55, dur=1.9, tau=0.8)
    boom(m, 13.0, 73.42, 0.22, dur=1.6, tau=0.6)
    shimmer(m, 13.0, 1.99, 1174.66, 0.30, rng, atk=0.06, rel=1.2, rev=0.65)
    for i, tt in enumerate((13.05, 13.09, 13.13, 13.17, 13.21)):
        glass_tink(m, tt, 4400.0 + 260.0 * i, 0.05, (-0.6, -0.4, 0.5, 0.6, 0.7)[i], rng)
    glass_tink(m, 13.45, 3520.0, 0.06, 0.55, rng)


# ------------------------------------------------------------------------------------------ master
def master(m, target, log):
    b = m.bus
    log('effects: duck, delay, reverb')
    dk = duck_curve(m.kicks)
    dl, dr = pingpong(b['dly'][0], b['dly'][1])
    rin_l = [b['rev'][0][i] + 0.35 * dl[i] for i in range(N)]
    rin_r = [b['rev'][1][i] + 0.35 * dr[i] for i in range(N)]
    rl, rr = reverb(rin_l, rin_r)
    L = [0.0] * N
    R = [0.0] * N
    dryl, dryr = b['dry']
    dul, dur_ = b['duck']
    for i in range(N):
        d = dk[i]
        L[i] = dryl[i] + dul[i] * d + 0.42 * dl[i] + 0.55 * rl[i]
        R[i] = dryr[i] + dur_[i] * d + 0.42 * dr[i] + 0.55 * rr[i]
    hp = rbj_hp(24.0, 0.6)
    L, R = biquad(L, *hp), biquad(R, *hp)
    air = rbj_highshelf(5000.0, 2.5)
    L, R = biquad(L, *air), biquad(R, *air)
    fade = master_fade()
    L, R = mul(L, fade), mul(R, fade)

    I0, _ = lufs(L, R)
    log(f'pre-master loudness {I0:.2f} LUFS')
    gain_db = target - I0
    ceil = -1.3
    for it in range(5):
        g = 10 ** (gain_db / 20.0)
        Lg = [v * g for v in L]
        Rg = [v * g for v in R]
        Lo, Ro, gmin = limiter(Lg, Rg, ceil)
        Lo, Ro = mul(Lo, fade), mul(Ro, fade)
        I1, _ = lufs(Lo, Ro)
        tp = true_peak_est(Lo, Ro, 10 ** ((ceil - 2.5) / 20.0))
        log(f'pass {it}: gain {gain_db:+.2f} dB, limiter max GR {-20 * math.log10(gmin):.2f} dB, '
            f'{I1:.2f} LUFS, true peak ~{tp:.2f} dBTP (ceiling {ceil:.2f})')
        ok_l = abs(I1 - target) <= 0.1
        ok_p = tp <= -1.05
        if ok_l and ok_p:
            break
        if not ok_p:
            ceil -= (tp + 1.05) + 0.05
        gain_db += target - I1
    return Lo, Ro


def master_fade():
    """3 ms fade-in at 0; raised-cosine fade 13.95 -> 14.996 s, digital zero after."""
    f = [1.0] * N
    ni = S(0.003)
    for i in range(ni):
        f[i] = 0.5 - 0.5 * cos(pi * i / ni)
    a, z = S(13.95), S(14.996)
    for i in range(a, N):
        if i >= z:
            f[i] = 0.0
        else:
            u = (i - a) / (z - a)
            f[i] = 0.5 + 0.5 * cos(pi * u)
    return f


def write_wav(path, L, R):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    pcm = array.array('h', bytes(4 * N))
    for i in range(N):
        l = int(round(L[i] * 32767.0))
        r = int(round(R[i] * 32767.0))
        pcm[2 * i] = -32767 if l < -32767 else (32767 if l > 32767 else l)
        pcm[2 * i + 1] = -32767 if r < -32767 else (32767 if r > 32767 else r)
    if sys.byteorder != 'little':
        pcm.byteswap()
    with wave.open(path, 'wb') as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return pcm


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=OUT_DEFAULT, help='output wav path')
    ap.add_argument('--target', type=float, default=-14.0, help='integrated loudness target (LUFS)')
    ap.add_argument('--seed', type=int, default=SEED)
    ap.add_argument('--stems', action='store_true', help='print per-stem loudness (slower, more memory)')
    ap.add_argument('--curve', action='store_true', help='print the 3 s short-term loudness every 0.5 s')
    args = ap.parse_args()
    t_start = time.time()
    log = lambda s: print(f'[{time.time() - t_start:6.1f}s] {s}', flush=True)

    rng = random.Random(args.seed)
    m = Mixer(stems=args.stems)
    log('composing')
    compose(m, rng)
    if m.stems is not None:
        for name, (sl, sr_) in sorted(m.stems.items()):
            I, _ = lufs(sl, sr_)
            pk = max(max(abs(v) for v in sl), max(abs(v) for v in sr_))
            print(f'  stem {name:8s} {I:7.2f} LUFS (unnormalised)  peak {20 * math.log10(pk + 1e-12):6.2f} dBFS')
    L, R = master(m, args.target, log)
    pcm = write_wav(args.out, L, R)
    # report from the quantised samples
    Lq = [pcm[2 * i] / 32767.0 for i in range(N)]
    Rq = [pcm[2 * i + 1] / 32767.0 for i in range(N)]
    I, st = lufs(Lq, Rq, short_term=args.curve)
    peak = max(abs(v) for v in pcm) / 32767.0
    tz = 0
    for i in range(N - 1, -1, -1):
        if pcm[2 * i] or pcm[2 * i + 1]:
            break
        tz += 1
    log(f'wrote {args.out}')
    print(f'  frames {len(pcm) // 2} ({len(pcm) / 2 / SR:.6f} s), integrated {I:.2f} LUFS, '
          f'sample peak {20 * math.log10(peak):.2f} dBFS, trailing digital silence {tz} frames '
          f'({tz / SR * 1000:.1f} ms), first frame {pcm[0]},{pcm[1]}')
    if args.curve:
        print('  short-term (3 s):', ' '.join(f'{t:.1f}:{v:.1f}' for t, v in st))


if __name__ == '__main__':
    main()
