"""Original cybercore soundtrack for the Almond promo, synthesized from scratch (numpy only).

150 BPM -> 1 beat = 0.4 s = 12 frames @30 fps; 1 bar = 48 frames. 42 bars = 67.2 s.
Structure (bars): 0-2 boot/riser | 2-10 GENERATE | 10-18 LIBRARY | 18-26 LIGHT+MATERIAL |
26-32 RENDER (glitch) | 32-40 WORLD (half-time, pads) | 40-42 outro hit.
Writes a 48 kHz 16-bit stereo WAV.
"""
import numpy as np, wave, sys

SR = 48000
BPM = 150
BEAT = 60 / BPM
BAR = 4 * BEAT
NBARS = 42
N = int(SR * BAR * NBARS) + SR * 2
rng = np.random.default_rng(7)
L = np.zeros(N); R = np.zeros(N)


def t_of(n): return np.arange(n) / SR
def at(bar, beat=0.0): return int(round((bar * 4 + beat) * BEAT * SR))
def midi(m): return 440.0 * 2 ** ((m - 69) / 12)


def add(sig, start, gain=1.0, pan=0.0):
    s = max(0, start); e = min(N, start + len(sig))
    if e <= s: return
    seg = sig[s - start:e - start] * gain
    L[s:e] += seg * np.sqrt(0.5 * (1 - pan)) * 1.414
    R[s:e] += seg * np.sqrt(0.5 * (1 + pan)) * 1.414


def add_st(l, r, start, gain=1.0):
    s = max(0, start); e = min(N, start + len(l))
    if e <= s: return
    L[s:e] += l[s - start:e - start] * gain
    R[s:e] += r[s - start:e - start] * gain


def onepole_lp(x, fc):
    fc = np.broadcast_to(np.asarray(fc, float), x.shape)
    a = np.exp(-2 * np.pi * fc / SR)
    y = np.empty_like(x); z = 0.0
    for i in range(len(x)):
        z = (1 - a[i]) * x[i] + a[i] * z; y[i] = z
    return y


def svf_lp(x, fc, q=0.7):
    """Chamberlin state-variable lowpass with per-sample cutoff (resonant)."""
    fc = np.broadcast_to(np.asarray(fc, float), x.shape)
    f = 2 * np.sin(np.pi * np.clip(fc, 20, SR / 6) / SR)
    damp = 1 / q
    low = band = 0.0
    y = np.empty_like(x)
    for i in range(len(x)):
        low += f[i] * band
        high = x[i] - low - damp * band
        band += f[i] * high
        y[i] = low
    return y


def hp(x, fc):
    return x - onepole_lp(x, fc)


def saw(freq, n, phase=0.0):
    ph = (phase + np.cumsum(np.broadcast_to(freq, (n,)) / SR)) % 1.0
    return 2 * ph - 1


def env_adsr(n, a=0.005, d=0.1, s=0.6, r=0.1):
    t = t_of(n); e = np.ones(n) * s
    na, nd, nr = int(a * SR), int(d * SR), int(r * SR)
    e[:na] = np.linspace(0, 1, max(na, 1))[:len(e[:na])]
    e[na:na + nd] = np.linspace(1, s, max(nd, 1))[:len(e[na:na + nd])]
    if nr: e[-nr:] *= np.linspace(1, 0, nr)
    return e


# ------------------------------------------------------------------ drums
def kick(dur=0.45, punch=1.0):
    n = int(dur * SR); t = t_of(n)
    f = 45 + 160 * np.exp(-t * 38)
    ph = 2 * np.pi * np.cumsum(f) / SR
    body = np.sin(ph) * np.exp(-t * 7.5)
    click = rng.standard_normal(n) * np.exp(-t * 400) * 0.35
    return np.tanh((body + click) * 2.2 * punch) * 0.9


def snare(dur=0.28):
    n = int(dur * SR); t = t_of(n)
    tone = np.sin(2 * np.pi * 190 * t) * np.exp(-t * 30) * 0.5
    nz = hp(rng.standard_normal(n), 1200) * np.exp(-t * 18)
    return np.tanh((tone + nz * 0.8) * 1.6) * 0.7


def clap(dur=0.3):
    n = int(dur * SR); t = t_of(n)
    nz = hp(rng.standard_normal(n), 900)
    e = np.zeros(n)
    for k, o in enumerate([0, 0.011, 0.022, 0.034]):
        i = int(o * SR); e[i:] += np.exp(-(t[:n - i]) * (60 if k < 3 else 14))
    return nz * e * 0.5


def hat(dur=0.05, open_=False):
    n = int((0.25 if open_ else dur) * SR); t = t_of(n)
    nz = hp(hp(rng.standard_normal(n), 7000), 7000)
    return nz * np.exp(-t * (14 if open_ else 90)) * 0.35


def glitch_tick(n=None):
    n = n or int(0.03 * SR)
    t = t_of(n)
    f = rng.uniform(1500, 6000)
    return np.sign(np.sin(2 * np.pi * f * t)) * np.exp(-t * 120) * 0.18


# ------------------------------------------------------------------ synths
def supersaw(notes, dur, cutoff_fn=None, voices=7, detune=0.18, gain=0.12):
    n = int(dur * SR)
    l = np.zeros(n); r = np.zeros(n)
    for m in notes:
        f0 = midi(m)
        for v in range(voices):
            d = (v - (voices - 1) / 2) / ((voices - 1) / 2) * detune
            s = saw(f0 * 2 ** (d / 12), n, rng.random())
            pan = (v / (voices - 1)) * 2 - 1
            l += s * np.sqrt(0.5 * (1 - pan)); r += s * np.sqrt(0.5 * (1 + pan))
    fc = cutoff_fn(t_of(n)) if cutoff_fn else 4000
    l = svf_lp(l, fc, 0.9); r = svf_lp(r, fc, 0.9)
    e = env_adsr(n, 0.01, 0.2, 0.8, 0.08)
    return l * e * gain, r * e * gain


def reese(m, dur, gain=0.35):
    n = int(dur * SR); f0 = midi(m)
    s = saw(f0, n) + saw(f0 * 1.007, n, 0.3) + np.sin(2 * np.pi * f0 * t_of(n)) * 1.2
    s = svf_lp(s, 380 + 250 * np.sin(2 * np.pi * 0.9 * t_of(n)) ** 2, 1.2)
    return np.tanh(s * 1.5) * env_adsr(n, 0.004, 0.05, 0.9, 0.03) * gain


def pluck(m, dur=0.22, gain=0.16, bright=6000):
    n = int(dur * SR); t = t_of(n)
    s = saw(midi(m), n) * 0.6 + np.sign(np.sin(2 * np.pi * midi(m) * t)) * 0.4
    s = svf_lp(s, 300 + bright * np.exp(-t * 22), 1.4)
    return s * np.exp(-t * 11) * gain


def pad(notes, dur, gain=0.07):
    n = int(dur * SR); t = t_of(n)
    l = np.zeros(n); r = np.zeros(n)
    for m in notes:
        for d, p in [(-0.09, -0.8), (0.0, 0.0), (0.09, 0.8), (12.03, 0.3)]:
            s = saw(midi(m + d) if d < 12 else midi(m) * 2.003, n, rng.random())
            l += s * (1 - p) * 0.5; r += s * (1 + p) * 0.5
    fc = 900 + 700 * np.sin(np.pi * t / dur)
    e = np.minimum(1, t / 1.2) * np.minimum(1, (dur - t) / 1.0).clip(0, 1)
    return svf_lp(l, fc) * e * gain, svf_lp(r, fc) * e * gain


def riser(dur, gain=0.25):
    n = int(dur * SR); t = t_of(n)
    nz = rng.standard_normal(n)
    fc = 300 * (40 ** (t / dur))
    s = svf_lp(nz, fc, 3.0) * (t / dur) ** 2
    sweep = np.sin(2 * np.pi * np.cumsum(200 * 12 ** (t / dur)) / SR) * (t / dur) ** 3 * 0.3
    return (s + sweep) * gain


def downlift(dur, gain=0.25):
    return riser(dur, gain)[::-1]


def impact(dur=2.5, gain=0.8):
    n = int(dur * SR); t = t_of(n)
    boom = np.sin(2 * np.pi * np.cumsum(30 + 90 * np.exp(-t * 6)) / SR) * np.exp(-t * 1.6)
    nz = svf_lp(rng.standard_normal(n), 2500 * np.exp(-t * 2) + 100) * np.exp(-t * 3)
    return np.tanh((boom + nz * 0.6) * 1.8) * gain


def bitcrush(x, bits=6, down=6):
    y = np.repeat(x[::down], down)[:len(x)]
    q = 2 ** bits
    return np.round(y * q) / q


def data_blips(start_bar, bars, density=0.35, gain=0.08):
    for s in range(bars * 16):
        if rng.random() < density:
            n = int(rng.uniform(0.01, 0.05) * SR); t = t_of(n)
            f = rng.choice([880, 1320, 1760, 2640, 3520])
            b = np.sign(np.sin(2 * np.pi * f * t)) * np.exp(-t * 60) * gain
            add(b, at(start_bar, s / 4), 1.0, rng.uniform(-0.9, 0.9))


# ------------------------------------------------------------------ harmony: F minor, cyber
# i - VI - III - VII  : Fm  Db  Ab  Eb
CHORDS = [[53, 56, 60, 65], [49, 53, 56, 61], [56, 60, 63, 68], [51, 55, 58, 63]]
ROOTS = [29, 25, 32, 27]  # bass (F1, Db1, Ab1, Eb1)
ARP = [[65, 68, 72, 77, 72, 68], [61, 65, 68, 73, 68, 65], [68, 72, 75, 80, 75, 72], [63, 67, 70, 75, 70, 67]]


def chord_for(bar): return bar % 4


# ---- 0-2 boot: data blips, riser, sub drone
data_blips(0, 2, 0.5, 0.06)
add(riser(2 * BAR, 0.3), at(0))
dl, dr = pad(CHORDS[0], 2 * BAR, 0.05); add_st(dl, dr, at(0))
for b in (0, 1):
    add(glitch_tick(), at(b, 3.5), 1.5)

# ---- main groove helper
def groove(bar0, bars, style='four', hats=True, snare_on=True, bass=True, saws=True, arp=True, crush=False):
    for b in range(bar0, bar0 + bars):
        c = chord_for(b)
        if style == 'four':
            for q in range(4): add(kick(), at(b, q), 0.95)
        elif style == 'break':
            for q in [0, 1.5, 2.5, 3.25]: add(kick(0.35), at(b, q), 0.85)
        elif style == 'half':
            add(kick(0.6), at(b, 0), 0.9)
        if snare_on:
            if style == 'half':
                add(snare(), at(b, 2), 0.6); add(clap(), at(b, 2), 0.4)
            else:
                add(snare(), at(b, 1), 0.55); add(snare(), at(b, 3), 0.55); add(clap(), at(b, 3), 0.35)
                if style == 'break': add(snare(0.12), at(b, 3.75), 0.3)
        if hats:
            for s in range(8 if style != 'half' else 4):
                off = s / 2 + (0.25 if style != 'half' else 0.5)
                add(hat(open_=(s % 4 == 3)), at(b, off), 0.6, 0.35)
            if style == 'break':
                for s in range(16):
                    if rng.random() < 0.3: add(hat(0.02), at(b, s / 4), 0.35, -0.4)
        if bass:
            for q in range(8):
                if style == 'half' and q % 2: continue
                add(reese(ROOTS[c] + (12 if q in (3, 7) and style != 'half' else 0), BEAT / 2 * 0.95), at(b, q / 2), 0.9)
        if saws:
            l, r = supersaw(CHORDS[c], BAR * 0.98, lambda t: 1200 + 3200 * np.exp(-t * 2.5), gain=0.05)
            if crush: l, r = bitcrush(l, 7, 3), bitcrush(r, 7, 3)
            add_st(l, r, at(b))
        if arp:
            seq = ARP[c]
            for s in range(16):
                m = seq[s % len(seq)] + (12 if s % 8 == 7 else 0)
                add(pluck(m, 0.16, 0.07), at(b, s / 4), 1.0, 0.5 if s % 2 else -0.5)


# ---- 2-10 GENERATE: drop, four-on-floor, data blips over it
add(impact(2.0, 0.55), at(2))
groove(2, 8, 'four', arp=False)
data_blips(2, 8, 0.18, 0.05)
for b in range(3, 10, 2): add(glitch_tick(), at(b, 3.75), 1.4, 0.6)
add(riser(BAR, 0.18), at(9))

# ---- 10-18 LIBRARY: breakbeat, arps in (placements land on the "1"s)
groove(10, 8, 'break', arp=True)
for b in range(10, 18):
    add(glitch_tick(int(0.02 * SR)), at(b, 0), 2.0, -0.6)
add(riser(BAR, 0.22), at(17))

# ---- 18-26 LIGHT + MATERIAL: full energy, crushed saws on second half
add(impact(2.0, 0.6), at(18))
groove(18, 4, 'four', arp=True)
groove(22, 4, 'four', arp=True, crush=True)
for b in range(18, 26):
    for q in range(4): add(hat(0.03), at(b, q + 0.75), 0.4, 0.7)
add(riser(BAR, 0.25), at(25))

# ---- 26-32 RENDER: glitch section -- stutter kicks, crushed everything, tape stops later in edit
add(impact(1.5, 0.6), at(26))
groove(26, 6, 'break', arp=True, crush=True)
for b in range(26, 32):
    if b % 2 == 1:
        for k in range(8): add(kick(0.08), at(b, 3 + k / 8), 0.5 + k * 0.05)  # stutter roll
    data_blips(b, 1, 0.3, 0.06)
add(riser(2 * BAR, 0.3), at(30))

# ---- 32-40 WORLD: half-time, huge pads, slow arps -- the splat flythrough floats
add(impact(3.0, 0.75), at(32))
for b in range(32, 40, 2):
    c = chord_for(b // 2)
    l, r = pad([m + 12 for m in CHORDS[c]] + [CHORDS[c][0]], 2 * BAR, 0.06); add_st(l, r, at(b))
groove(32, 8, 'half', hats=True, saws=False, arp=False)
for b in range(32, 40):
    seq = ARP[chord_for(b // 2)]
    for s in range(8):
        add(pluck(seq[s % len(seq)] + 12, 0.35, 0.05, 3500), at(b, s / 2), 1.0, np.sin(s) * 0.7)
add(riser(BAR, 0.2), at(39))

# ---- 40-42 OUTRO: final hit + tail
add(impact(4.0, 0.9), at(40))
add(kick(0.8, 1.2), at(40), 1.0)
l, r = supersaw(CHORDS[0] + [77], 2 * BAR, lambda t: 5000 * np.exp(-t * 1.2) + 300, gain=0.07); add_st(l, r, at(40))
data_blips(40, 2, 0.15, 0.04)

# ------------------------------------------------------------------ sidechain + master
side = np.ones(N)
for b in list(range(2, 10)) + list(range(18, 26)):
    for q in range(4):
        i = at(b, q); n = int(0.28 * SR); t = t_of(n)
        side[i:i + n] = np.minimum(side[i:i + n], 0.35 + 0.65 * (1 - np.exp(-t * 18)))
# keep drums un-ducked is complex; duck whole mix gently -> pumping cyber feel
L *= side ** 0.6; R *= side ** 0.6

# stereo width on highs, glue saturation, limiter
mid, sid = (L + R) / 2, (L - R) / 2
sid = sid * 1.25
L, R = mid + sid, mid - sid
peak = max(np.abs(L).max(), np.abs(R).max())
L, R = L / peak * 1.6, R / peak * 1.6
L, R = np.tanh(L) * 0.95, np.tanh(R) * 0.95
end = at(NBARS) + SR // 2
fade = np.ones(end); fade[-SR // 2:] = np.linspace(1, 0, SR // 2)
L, R = L[:end] * fade, R[:end] * fade

out = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\liang\Documents\almond_promo\music.wav"
data = (np.stack([L, R], 1) * 32767).astype(np.int16)
with wave.open(out, 'wb') as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(data.tobytes())
print('wrote', out, len(L) / SR, 's')
