"""Day-timelapse video of the Atelier 07 daylight simulation (1920 x 1080, 24 fps, H.264)."""
import json, math, subprocess, sys, shutil
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
here = Path(__file__).parent
sys.path.insert(0, str(here))
from common import PAPER, INK, GREY, LIGHT, font, load_export, plan_lines, Plan, legend_bar, colour
from almond_mcp.environment import studies

OUT = Path(sys.argv[1])
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FPS = 24
W, H = 1920, 1080
frames_dir = here / "frames"
if frames_dir.exists():
    shutil.rmtree(frames_dir)
frames_dir.mkdir()

z = np.load(here / "anim.npz")
meta = json.loads(str(z["meta"]))
closed = {"ground": json.loads(str(z["ground_closed"])), "upper": json.loads(str(z["upper_closed"]))}
R = json.loads((here / "results.json").read_text())
objs = load_export()
LEVELS = (("ground", "Ground floor", 1.1), ("upper", "Upper floor", 3.224 + 1.1))
BOXES = {"ground": (60, 230, 880, 700), "upper": (980, 230, 880, 700)}
LO, HI = 50.0, 5000.0

# static layers: paper, plan linework, labels, legend
base = Image.new("RGB", (W, H), PAPER)
over = Image.new("RGBA", (W, H), (0, 0, 0, 0))
do = ImageDraw.Draw(over)
plans = {}
for key, label, zc in LEVELS:
    p = Plan(BOXES[key])
    plans[key] = p
    p.draw(do, None, None, plan_lines(objs, zc), {"wall": 5, "glass": 3, "detail": 1.4, "furniture": 1})
    do.text((BOXES[key][0], BOXES[key][1] - 46), label, fill=INK, font=font(30, True))
do.text((60, 40), "ATELIER 07", fill=INK, font=font(46, True))


def legend(d):
    legend_bar(d, 60, 990, 520, 18, LO, HI, "viridis", [100, 300, 1000, 3000], lambda v: f"{v:,.0f}",
               "Illuminance at desk height, lux", size=20, log=True)


def dial(d, alt, az, x=1760, y=110, r=70):
    d.ellipse([x - r, y - r, x + r, y + r], outline=LIGHT, width=2)
    d.text((x - 6, y - r - 26), "N", fill=GREY, font=font(18, True))
    if alt > 0:
        rr = r * math.tan(math.radians(90 - alt) / 2)
        sx, sy = x + rr * math.sin(math.radians(az)), y - rr * math.cos(math.radians(az))
        d.ellipse([sx - 11, sy - 11, sx + 11, sy + 11], fill=(232, 160, 40))
    d.ellipse([x - 3, y - 3, x + 3, y + 3], fill=GREY)


n_frames = 0


def emit(img):
    global n_frames
    img.save(frames_dir / f"f{n_frames:05d}.png")
    n_frames += 1


def frame_at(i):
    img = base.copy()
    d = ImageDraw.Draw(img)
    for key, _, _ in LEVELS:
        E = z[f"{key}_E"][i]
        plans[key].draw(d, z[f"{key}_cells"], colour(np.maximum(E, LO * 0.5), LO, HI, "viridis", log=True))
    img.paste(over, (0, 0), over)
    m = meta[i]
    hh = int(m["hour"]); mm = int(round((m["hour"] - hh) * 60))
    if mm == 60:
        hh, mm = hh + 1, 0
    date = "21 June" if m["month"] == 6 else "21 December"
    d.text((60, 104), f"Daylight through the day · {date}, clear sky", fill=GREY, font=font(30))
    t = f"{hh:02d}:{mm:02d}"
    d.text((1660 - d.textlength(t, font=font(64, True)), 64), t, fill=INK, font=font(64, True))
    shut = sorted(set(closed["ground"][i]) | set(closed["upper"][i]))
    status = ("blinds down: " + ", ".join(shut) + " facade") if shut else "blinds up"
    d.text((1660 - d.textlength(status, font=font(24)), 150), status, fill=GREY, font=font(24))
    dial(d, m["alt"], m["az"])
    legend(d)
    return img


# intro: the house in its street, then the plans fading in
ax = Image.open(here / "captures" / "axon_context.png").convert("RGB").crop((200, 120, 2300, 1440)).resize((W, int(W * 1320 / 2100)))
intro = Image.new("RGB", (W, H), PAPER)
intro.paste(ax.crop((0, (ax.height - H) // 2, W, (ax.height - H) // 2 + H)), (0, 0))
di = ImageDraw.Draw(intro)
di.rectangle([0, 0, 760, 230], fill=PAPER)
di.text((60, 50), "ATELIER 07", fill=INK, font=font(64, True))
di.text((60, 140), "daylight simulation · two days", fill=GREY, font=font(36))
for _ in range(int(2.0 * FPS)):
    emit(intro)
first = frame_at(0)
for k in range(int(0.75 * FPS)):
    emit(Image.blend(intro, first, (k + 1) / (0.75 * FPS)))

# the two days (crossfade between them)
june = [i for i, m in enumerate(meta) if m["month"] == 6]
dec = [i for i, m in enumerate(meta) if m["month"] == 12]
for i in june:
    emit(frame_at(i))
last = frame_at(june[-1])
nxt = frame_at(dec[0])
for k in range(int(0.6 * FPS)):
    emit(Image.blend(last, nxt, (k + 1) / (0.6 * FPS)))
for i in dec:
    emit(frame_at(i))

# end: the annual result
end = base.copy()
d = ImageDraw.Draw(end)
for key, label, _ in LEVELS:
    res, arr = studies.load_run(R[label]["annual"])
    plans[key].draw(d, arr["cells"], colour(arr["da"] * 100, 0, 100, "viridis"))
end.paste(over, (0, 0), over)
d.text((60, 104), "Over the year · daylight autonomy, 300 lux", fill=GREY, font=font(30))
for key, label, _ in LEVELS:
    sda = R[label]["metrics"]["sda_pct"]
    s = f"sDA {sda:.0f} %"
    bx = BOXES[key]
    d.text((bx[0] + bx[2] - d.textlength(s, font=font(30, True)), bx[1] - 46), s, fill=INK, font=font(30, True))
legend_bar(d, 60, 990, 520, 18, 0, 100, "viridis", [0, 50, 100], lambda v: f"{v:.0f}", "% of occupied hours above 300 lux", size=20)
lastdec = frame_at(dec[-1])
for k in range(int(0.75 * FPS)):
    emit(Image.blend(lastdec, end, (k + 1) / (0.75 * FPS)))
for _ in range(int(3.0 * FPS)):
    emit(end)

OUT.parent.mkdir(parents=True, exist_ok=True)
subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(frames_dir / "f%05d.png"),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "slow", "-movflags", "+faststart", str(OUT)],
               check=True)
end.save(OUT.with_name("A07-video-endframe.png"))
frame_at(june[len(june) // 3]).save(OUT.with_name("A07-video-still-june.png"))
print(n_frames, "frames,", round(n_frames / FPS, 1), "s ->", OUT)
