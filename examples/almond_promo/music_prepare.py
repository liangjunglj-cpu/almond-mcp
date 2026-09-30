"""Fit an ElevenLabs take to the edit: align kicks to the 150 BPM frame grid, filter-sweep breakdown for WORLD, tidy ending.

python music_prepare.py <input.wav>  -> music_final.wav
"""
import sys, wave, numpy as np
from scipy.signal import butter, sosfiltfilt

WORK = r"C:\Users\liang\Documents\almond_promo"
SR = 48000
BEAT = int(0.4 * SR)
BAR = 4 * BEAT
N = 42 * BAR

w = wave.open(sys.argv[1])
x = np.frombuffer(w.readframes(w.getnframes()), np.int16).reshape(-1, 2).astype(np.float32) / 32768

# --- kick phase: low band onset strength folded over one beat (1 ms bins)
low = sosfiltfilt(butter(4, 110, 'low', fs=SR, output='sos'), x.mean(1))
env = np.abs(low)
on = np.maximum(np.diff(env, prepend=0), 0)
# search only +-60 ms around the downbeat grid (the bassline sits on the off-beats and would win otherwise)
cands = list(range(-60, 61))
fold = [on[max(0, int(1.6 * SR * 2 + k * SR / 1000))::BEAT].sum() for k in cands]
off_ms = cands[int(np.argmax(fold))]
print('kick offset vs grid: %d ms' % off_ms)
lead = int((off_ms - 8) * SR / 1000)     # land kicks ~8 ms after each video frame boundary
if lead > 0: x = x[lead:]
elif lead < 0: x = np.concatenate([np.zeros((-lead, 2), np.float32), x])
x = np.concatenate([x, np.zeros((max(0, N - len(x)), 2), np.float32)])[:N]

# --- WORLD (bars 32-40): low-pass sweep down, float, sweep back up into the end card
t = np.arange(N) / SR
b0, b1 = 32 * 1.6, 40 * 1.6
seg = (t >= b0) & (t < b1)
u = (t[seg] - b0) / (b1 - b0)
down = np.clip(u / 0.12, 0, 1); up = np.clip((u - 0.9) / 0.1, 0, 1)
# click-free: crossfade between dry and a fully filtered copy, with the mix following the sweep
wet = sosfiltfilt(butter(2, 650, 'low', fs=SR, output='sos'), x, axis=0)
mix = np.zeros(N)
mix[seg] = down * (1 - up)
mix = np.convolve(mix, np.ones(2400) / 2400, 'same')[:, None]
gain = 1 - 0.25 * mix                     # breakdown sits a little lower
y = (x * (1 - mix) + wet * mix * 1.35) * gain

# --- end: last bar fades, final 0.3 s silent
fade = np.ones(N)
e0 = int(41 * 1.6 * SR); fade[e0:] = np.linspace(1, 0, N - e0) ** 1.5
y *= fade[:, None]
y = np.clip(y, -1, 1)
with wave.open(WORK + r"\music_final.wav", 'wb') as f:
    f.setnchannels(2); f.setsampwidth(2); f.setframerate(SR)
    f.writeframes((y * 32767).astype(np.int16).tobytes())
print('wrote music_final.wav', N / SR, 's')
