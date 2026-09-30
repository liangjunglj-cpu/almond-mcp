"""Re-cut the ElevenLabs track (150 BPM, drop at bar 8) onto the edit's 42-bar structure, splicing on bar lines."""
import wave, numpy as np

WORK = r"C:\Users\liang\Documents\almond_promo"
SR = 48000
BAR = int(1.6 * SR)
PRE = int(0.005 * SR)      # cut 5 ms after the bar line: beats sit ~20 ms after the grid, so splices fall before transients
XF = int(0.012 * SR)       # 12 ms equal-power crossfade at every splice
# (edit_bar_start, edit_bar_end, source_bar_start)
# physics OFF (section) rides the pre-drop build (18-20); the drop hits as physics switches ON (bar 20)
# breakdown carries the splat flythrough (bars 32-38); the track's own outro (final hit + tail) closes it (38-40)
MAP = [(0, 2, 6), (2, 10, 8), (10, 18, 16), (18, 20, 6), (20, 30, 8), (30, 36, 18), (36, 44, 24), (44, 50, 32), (50, 52, 40)]
NB = MAP[-1][1]

import sys
SRC = sys.argv[1] if len(sys.argv) > 1 else WORK + r"\music_el.wav"
SHIFT = int(float(sys.argv[2]) * SR / 1000) if len(sys.argv) > 2 else 0   # ms to pull the result earlier (downbeat latency)
w = wave.open(SRC)
src = np.frombuffer(w.readframes(w.getnframes()), np.int16).reshape(-1, 2).astype(np.float32) / 32768
out = np.zeros((NB * BAR + SR, 2), np.float32)
fade_in = np.sin(np.linspace(0, np.pi / 2, XF))[:, None]
fade_out = np.cos(np.linspace(0, np.pi / 2, XF))[:, None]
for i, (e0, e1, s0) in enumerate(MAP):
    n = (e1 - e0) * BAR
    a = s0 * BAR + PRE
    seg = src[a:a + n + XF].copy()
    if len(seg) < n + XF:
        seg = np.concatenate([seg, np.zeros((n + XF - len(seg), 2), np.float32)])
    if i > 0: seg[:XF] *= fade_in
    if i < len(MAP) - 1: seg[n:n + XF] *= fade_out
    else: seg[n:] = 0
    o = e0 * BAR + PRE
    out[o:o + n + XF] += seg
out = np.concatenate([out[SHIFT:], np.zeros((SHIFT, 2), np.float32)])[:NB * BAR] if SHIFT > 0 else out[:NB * BAR]
f0 = (NB - 1) * BAR   # clean fade across the last bar with the outro tail
out[f0:] *= (np.linspace(1, 0, len(out) - f0) ** 1.6)[:, None]
with wave.open(WORK + r"\music_final.wav", 'wb') as f:
    f.setnchannels(2); f.setsampwidth(2); f.setframerate(SR)
    f.writeframes((np.clip(out, -1, 1) * 32767).astype(np.int16).tobytes())
print('wrote music_final.wav', len(out) / SR, 's')
