"""Three A3 landscape boards for the Atelier 07 environmental study: site & climate, daylight, energy & comfort."""
import json, math, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
here = Path(__file__).parent
sys.path.insert(0, str(here))
from common import (PAPER, INK, GREY, LIGHT, GLASS, font, load_export, plan_lines, Plan, legend_bar, colour)
from almond_mcp.environment import studies, epw, solar, climate

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else here / "boards"
OUT.mkdir(parents=True, exist_ok=True)
W, H = 4961, 3508                     # A3 landscape at 300 dpi
M = 220                               # margin
R = json.loads((here / "results.json").read_text())
w = epw.read_epw(here / R["weather"]["epw"])
objs = load_export()
CUT = {"Ground floor": 1.1, "Upper floor": 3.224 + 1.1}
LINES = {k: plan_lines(objs, z) for k, z in CUT.items()}


def board(title, subtitle):
    im = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(im)
    d.text((M, M - 40), "ATELIER 07", fill=INK, font=font(96, True))
    d.text((M, M + 80), subtitle, fill=GREY, font=font(56))
    d.text((W - M - d.textlength(title, font=font(56)), M - 10), title, fill=INK, font=font(56))
    foot = ("Neo-Swiss urban duplex, 12.8 × 10 m, two levels.  Weather: Zurich-Affoltern (MeteoSwiss 066640), "
            "typical year TMYx 2011–2025, climate.onebuilding.org.  Almond environmental engine.")
    d.text((M, H - M + 40), foot, fill=GREY, font=font(34))
    d.line([(M, H - M + 10), (W - M, H - M + 10)], fill=LIGHT, width=3)
    return im, d


def run(run_id):
    return studies.load_run(run_id)


def plan_panel(d, box, level, values, cells, lo, hi, ramp, label, value_text, log=False):
    p = Plan(box)
    cols = colour(values, lo, hi, ramp, log)
    p.draw(d, cells, cols, LINES[level])
    x, y = box[0], box[1] - 80
    d.text((x, y), label, fill=INK, font=font(48, True))
    d.text((x + d.textlength(label, font=font(48, True)) + 36, y + 6), value_text, fill=GREY, font=font(44))
    return p


def north(d, x, y, s=60):
    d.polygon([(x, y - s), (x - s * 0.35, y + s * 0.4), (x, y + s * 0.15), (x + s * 0.35, y + s * 0.4)], fill=INK)
    d.text((x - 14, y - s - 60), "N", fill=INK, font=font(40, True))


# ── Board 1: site, sun, climate ─────────────────────────────────────────────
im, d = board("01  Site · Sun · Climate", "Climate and sun at the site")
ax = Image.open(here / "captures" / "axon_context.png").convert("RGB")
ax = ax.crop((200, 250, 2300, 1500))
ax = ax.resize((2600, int(2600 * ax.height / ax.width)))
im.paste(ax, (M, 520))
# sun path (stereographic)
cx, cy, Rr = 3650, 1250, 640
sp = solar.sun_path(w.location.latitude, w.location.longitude, w.location.time_zone)
def stereo(alt, az):
    r = Rr * np.tan(np.radians(90 - np.asarray(alt)) / 2) / math.tan(math.pi / 4)
    a = np.radians(np.asarray(az))
    return cx + r * np.sin(a), cy - r * np.cos(a)
for alt in (0, 30, 60):
    r = Rr * math.tan(math.radians(90 - alt) / 2)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=LIGHT if alt else INK, width=3 if alt else 4)
    if alt:
        d.text((cx + 8, cy - r - 36), f"{alt}°", fill=GREY, font=font(30))
for az, lab in ((0, "N"), (90, "E"), (180, "S"), (270, "W")):
    x, y = stereo(-8, az)
    d.text((float(x) - 14, float(y) - 22), lab, fill=INK, font=font(40, True))
for h, a in sp["analemmas"].items():
    x, y = stereo(a["altitude"], a["azimuth"])
    d.line(list(zip(x, y)), fill=LIGHT, width=2)
for mth, col in ((6, (214, 94, 40)), (3, GREY), (12, (60, 100, 160))):
    m = sp["months"][mth]
    x, y = stereo(m["altitude"], m["azimuth"])
    d.line(list(zip(x, y)), fill=col, width=7)
    lab = {6: "21 Jun", 3: "21 Mar / Sep", 12: "21 Dec"}[mth]
    d.text((float(x[-1]) + 24, float(y[-1]) - 20), lab, fill=col, font=font(34))
# the building's facades on the sun path: the glazed south facade
fx0, fy0 = stereo(0, 90)
d.text((2920, 520), "Sun path", fill=INK, font=font(48, True))
# monthly climate strip
cs = climate.summarize(w)
mx, my, mw, mh = 3050, 2260, 1690, 760
months = cs["monthly"]
tmin = min(m["daily_min_mean"] for m in months) - 4
tmax = max(m["daily_max_mean"] for m in months) + 4
gmax = max(m["ghi_kwh_m2"] for m in months) * 1.15
bw = mw / 12
d.line([(mx, my + mh), (mx + mw, my + mh)], fill=INK, width=2)
for i, m in enumerate(months):
    x = mx + i * bw
    gh = m["ghi_kwh_m2"] / gmax * mh
    d.rectangle([x + bw * 0.18, my + mh - gh, x + bw * 0.82, my + mh], fill=(226, 216, 190))
    def ty(t):
        return my + mh - (t - tmin) / (tmax - tmin) * mh
    d.line([(x + bw / 2, ty(m["daily_min_mean"])), (x + bw / 2, ty(m["daily_max_mean"]))], fill=INK, width=10)
    d.ellipse([x + bw / 2 - 9, ty(m["dry_bulb_mean"]) - 9, x + bw / 2 + 9, ty(m["dry_bulb_mean"]) + 9], fill=PAPER, outline=INK, width=4)
    d.text((x + bw / 2 - d.textlength(m["month"][0], font=font(32)) / 2, my + mh + 14), m["month"][0], fill=GREY, font=font(32))
d.text((mx, my - 90), "Temperature range and solar radiation by month", fill=INK, font=font(48, True))
d.text((mx, my - 30), "bars: global horizontal kWh/m²   lines: daily min–max °C", fill=GREY, font=font(32))
a = cs["annual"]
facts = [(f"{a['dry_bulb_mean']} °C", "mean air temperature"), (f"{int(a['hdd_18'])}", "heating degree days (18 °C)"),
         (f"{int(a['ghi_kwh_m2'])}", "kWh/m² global radiation"),
         (f"{a['design_conditions_from_file'].get('heating_99_6_c', a['heating_design_99_6_c'])} °C", "winter design temperature (99.6 %)")]
for i, (big, small) in enumerate(facts):
    x = M + i * 650
    d.text((x, 2840), big, fill=INK, font=font(84, True))
    d.text((x, 2950), small, fill=GREY, font=font(34))
im.save(OUT / "A07-board-01-site-climate.png", dpi=(300, 300))

# ── Board 2: daylight ───────────────────────────────────────────────────────
im, d = board("02  Daylight", "Annual daylight, both floors, 08:00–18:00")
big = {}
for i, level in enumerate(("Ground floor", "Upper floor")):
    res, arr = run(R[level]["annual"])
    m = res["metrics"]
    box = (M + i * 2300, 620, 2150, 1700)
    plan_panel(d, box, level, arr["da"] * 100, arr["cells"], 0, 100, "viridis", level,
               f"sDA {m['sda_pct']:.0f} %   ASE {m['ase_pct']:.0f} %   UDI {m['udi_pct']['useful_100_3000']:.0f} %")
north(d, W - M - 60, 760)
legend_bar(d, M, 2440, 900, 36, 0, 100, "viridis", [0, 50, 100], lambda v: f"{v:.0f}", "Daylight autonomy DA300  (% of occupied hours)")
# small multiples: direct sun and daylight factor
small = [("Ground floor", "ase_hours", "annual", 0, 500, "magma", "Direct sun > 1000 lux (h)"),
         ("Upper floor", "ase_hours", "annual", 0, 500, "magma", ""),
         ("Ground floor", "df", "df", 0, 8, "viridis", "Daylight factor (%)"),
         ("Upper floor", "df", "df", 0, 8, "viridis", "")]
for i, (level, key, kind, lo, hi, ramp, head) in enumerate(small):
    res, arr = run(R[level][kind])
    box = (1500 + i * 840, 2440, 760, 600)
    p = Plan(box)
    p.draw(d, arr["cells"], colour(arr[key], lo, hi, ramp), LINES[level], {"wall": 2.5, "glass": 1.5, "detail": 0.7, "furniture": 0.5})
    txt = (f"{res['metrics']['average_df_pct']:.1f} % avg" if kind == "df" else f"ASE {res['metrics']['ase_pct']:.0f} %")
    d.text((box[0], box[1] - 54), ("G  " if level == "Ground floor" else "U  ") + txt, fill=INK, font=font(34, True))
    if head:
        d.text((box[0], box[1] - 104), head, fill=GREY, font=font(32))
legend_bar(d, 1500, 3140, 700, 22, 0, 500, "magma", [0, 250, 500], lambda v: f"{v:.0f}", "", size=26)
legend_bar(d, 3180, 3140, 700, 22, 0, 8, "viridis", [0, 2, 4, 8], lambda v: f"{v:.0f}", "", size=26)
im.save(OUT / "A07-board-02-daylight.png", dpi=(300, 300))

# ── Board 3: energy and comfort ─────────────────────────────────────────────
im, d = board("03  Energy · Comfort", "Solar exposure, heating demand and summer comfort")
rad = Image.open(here / "captures" / "axon_radiation.png").convert("RGBA")
bg = Image.new("RGBA", rad.size, PAPER + (255,))
rad = Image.alpha_composite(bg, rad).convert("RGB")
bbox = Image.eval(rad.convert("L"), lambda v: 255 if v < 236 else 0).getbbox()
rad = rad.crop((max(0, bbox[0] - 40), max(0, bbox[1] - 40), min(rad.width, bbox[2] + 40), min(rad.height, bbox[3] + 40)))
scale = min(2300 / rad.width, 2000 / rad.height)
rad = rad.resize((int(rad.width * scale), int(rad.height * scale)), Image.LANCZOS)
im.paste(rad, (M, 600))
rres, _ = run(R["radiation"]["run"])
d.text((M, 480), "Solar exposure of the envelope", fill=INK, font=font(48, True))
d.text((M + 760, 486), f"roof {rres['metrics']['max_kwh_m2']:.0f} kWh/m² · year", fill=GREY, font=font(44))
th = R["thermal"]
tb = {z["zone"]: z for z in th["blinds"]["zones"]}
tn = {z["zone"]: z for z in th["no_blinds"]["zones"]}
# monthly heating, both floors (with blinds)
mx, my, mw, mh = 2700, 760, 2040, 700
d.text((mx, my - 120), "Heating demand by month", fill=INK, font=font(48, True))
peak = max(max(m["heating_kwh"] for m in tb[z]["monthly"]) for z in tb)
bw = mw / 12
for zi, (zname, col) in enumerate((("Ground floor", INK), ("Upper floor", GREY))):
    for i, m in enumerate(tb[zname]["monthly"]):
        x = mx + i * bw + bw * (0.15 + 0.36 * zi)
        h = m["heating_kwh"] / peak * mh
        d.rectangle([x, my + mh - h, x + bw * 0.32, my + mh], fill=col)
for i, m in enumerate(tb["Ground floor"]["monthly"]):
    d.text((mx + i * bw + bw / 2 - 9, my + mh + 14), m["month"][0], fill=GREY, font=font(32))
d.line([(mx, my + mh), (mx + mw, my + mh)], fill=INK, width=2)
d.text((mx, my - 54), f"ground {tb['Ground floor']['heating_kwh_m2']:.0f} · upper {tb['Upper floor']['heating_kwh_m2']:.0f} kWh/m² · year",
       fill=GREY, font=font(36))
# carpet plots: upper floor operative temperature without / with summer blinds
_, arr_n = run(th["no_blinds"]["run"])
_, arr_b = run(th["blinds"]["run"])
zi = [z["zone"] for z in th["no_blinds"]["zones"]].index("Upper floor")
cy0 = 1840
d.text((mx, cy0 - 120), "Upper floor, operative temperature", fill=INK, font=font(48, True))
for k, (arr, lab, zs) in enumerate(((arr_n, "no blinds", tn), (arr_b, "external blinds, summer mode", tb))):
    t = arr[f"z{zi}_t_op"].reshape(365, 24).T                    # hours x days
    cols = colour(t.ravel(), 16, 30, "coolwarm").reshape(24, 365, 3).astype(np.uint8)
    img = Image.fromarray(cols, "RGB").resize((mw, 300), Image.NEAREST)
    y = cy0 + k * 470
    im.paste(img, (mx, y))
    hrs = zs["Upper floor"]["hours_above_26c_occupied"]
    d.text((mx, y - 56), f"{lab}", fill=INK, font=font(36, True))
    d.text((mx + mw - d.textlength(f"{hrs} h above 26 °C", font=font(36)), y - 56), f"{hrs} h above 26 °C", fill=GREY, font=font(36))
for i, mo in enumerate(epw.MONTH_NAMES):
    x = mx + epw.MONTH_START[i] / 365 * mw
    d.text((x + 6, cy0 + 470 + 310), mo[0], fill=GREY, font=font(30))
legend_bar(d, mx, 2900, 900, 30, 16, 30, "coolwarm", [16, 20, 26, 30], lambda v: f"{v:.0f}", "°C   (rows: hour of day, columns: day of year)", size=28)
legend_bar(d, M, 2700, 900, 30, rres["metrics"]["min_kwh_m2"], rres["metrics"]["max_kwh_m2"], "magma",
           [round(rres["metrics"]["min_kwh_m2"] + f * (rres["metrics"]["max_kwh_m2"] - rres["metrics"]["min_kwh_m2"]), -2)
            for f in (0.1, 0.5, 0.9)], lambda v: f"{v:.0f}", "kWh/m² · year", size=28)
up_n, up_b = tn["Upper floor"]["hours_above_26c_occupied"], tb["Upper floor"]["hours_above_26c_occupied"]
facts = [(f"{tb['Ground floor']['heating_kwh_m2']:.0f} / {tb['Upper floor']['heating_kwh_m2']:.0f}", "kWh/m² heating, ground / upper"),
         (f"{up_n} → {up_b} h", "above 26 °C upstairs, blinds added"),
         (f"{rres['metrics']['max_kwh_m2']:.0f}", "kWh/m² on the roof each year")]
for i, (bigt, small) in enumerate(facts):
    x = M + i * 800
    d.text((x, 2950), bigt, fill=INK, font=font(76, True))
    d.text((x, 3050), small, fill=GREY, font=font(32))
im.save(OUT / "A07-board-03-energy-comfort.png", dpi=(300, 300))
print("boards in", OUT)
