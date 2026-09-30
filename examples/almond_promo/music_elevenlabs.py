"""Compose the promo soundtrack with ElevenLabs Music, sections locked to the edit's structure.

python music_elevenlabs.py [style] [seed]   -> ~/Documents/almond_promo/music_el[_seed].mp3
Reads ELEVENLABS_API_KEY from the promo .env (never printed).
"""
import json, sys, urllib.request, urllib.error
from pathlib import Path

WORK = Path(r"C:\Users\liang\Documents\almond_promo")
BAR_MS = 1600  # 150 BPM, 4/4


def key():
    for line in (WORK / '.env').read_text(encoding='utf-8').splitlines():
        if line.strip().startswith('ELEVENLABS_API_KEY='):
            v = line.split('=', 1)[1].strip().strip('"').strip("'")
            if v: return v
    raise SystemExit('ELEVENLABS_API_KEY is empty')


STYLES = {
 'cyber': (["cybercore", "instrumental electronic", "150 BPM", "4/4", "F minor", "glossy detuned supersaw chords",
            "punchy 808 kick", "tight crisp hi-hats", "sidechain pumping", "clean modern mix", "futuristic, sleek, neo-tokyo"], None),
 'antidote': (["dreamy darkwave electronic", "sped-up TikTok edit feel", "150 BPM", "4/4", "minor key",
                "ethereal reverb-drenched synth pads", "crystalline bit-crushed arpeggios", "lo-fi chiptune lead melody",
                "punchy trap drums with rolling hi-hats", "deep 808 sub bass", "melancholic yet euphoric", "hazy, nocturnal, emotional"], None),
 'y2k': (["Y2K cyberpunk", "early 2000s techno-thriller soundtrack", "instrumental", "150 BPM", "4/4", "E minor",
          "big beat breakbeats", "distorted acid 303 bassline", "hard trance supersaw stabs", "industrial metallic percussion",
          "gritty analog synths", "dial-up modem and data-stream sound effects", "dark, fast, adrenaline, hacker aesthetic",
          "wide punchy club mix"], None),
}
NEG = ["vocals", "singing", "spoken word", "acoustic guitar", "lo-fi", "jazz", "orchestral", "tempo changes", "slow build"]
SECTIONS = [
    ("Boot", 2, ["short 2-bar intro", "modem handshake noise", "rising filter sweep", "snare roll into the drop"], ["long intro"]),
    ("Generate", 8, ["the drop hits on the very first beat of this section", "full breakbeat and acid bassline from bar one",
                     "driving, relentless"], ["build-up", "intro"]),
    ("Library", 8, ["chopped breakbeat variation", "acid bass squelch", "arpeggiated synth leads", "bouncy"], []),
    ("Light and material", 8, ["second drop on the first beat", "hard trance stabs", "full energy", "euphoric and dark"], ["build-up"]),
    ("Render", 6, ["intense", "stutter edits", "rising tension", "riser into a breakdown at the end"], []),
    ("World", 8, ["breakdown", "half-time", "huge airy cyberpunk pads", "slow shimmering arpeggios", "cinematic, spacious"], ["aggressive drums"]),
    ("Outro", 2, ["final impact hit", "short reverb tail"], ["fade in"]),
]


def main():
    style = sys.argv[1] if len(sys.argv) > 1 else 'y2k'
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else None
    plan = {"positive_global_styles": STYLES[style][0], "negative_global_styles": NEG,
            "sections": [{"section_name": n, "positive_local_styles": p, "negative_local_styles": ng,
                          "duration_ms": bars * BAR_MS, "lines": []} for n, bars, p, ng in SECTIONS]}
    model = sys.argv[3] if len(sys.argv) > 3 else 'music_v1'
    if model == 'music_v1':
        body = {"composition_plan": plan, "model_id": "music_v1", "respect_sections_durations": True}
    else:  # v2 / v2.5: chunk plan, global styles folded into every chunk
        chunks = [{"text": "", "duration_ms": bars * BAR_MS, "positive_styles": STYLES[style][0][:6] + p,
                   "negative_styles": NEG + ng, "context_adherence": "high"} for n, bars, p, ng in SECTIONS]
        body = {"composition_plan": {"chunks": chunks}, "model_id": model}
    if seed is not None: body["seed"] = seed
    req = urllib.request.Request('https://api.elevenlabs.io/v1/music?output_format=mp3_48000_192',
                                 data=json.dumps(body).encode(), method='POST',
                                 headers={'xi-api-key': key(), 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            audio = r.read()
    except urllib.error.HTTPError as e:
        raise SystemExit(f'HTTP {e.code}: {e.read().decode()[:1500]}')
    out = WORK / f'music_el_{style}_{seed}_{model}.mp3'
    out.write_bytes(audio)
    print('wrote', out, len(audio), 'bytes; total planned', sum(b for _, b, _, _ in SECTIONS) * BAR_MS, 'ms')


if __name__ == '__main__':
    main()
