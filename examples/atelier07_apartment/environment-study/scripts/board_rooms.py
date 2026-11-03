"""Board 04 of the Atelier 07 study: rooms and constructions, drawn with the environment workspace's own
diagram system (almond_mcp.environment.diagrams) so the board and the Rhino panel share one language.

    python board_rooms.py <out_dir> <thermal_run_id> <thermal_blinds_run_id> <daylight_run_id>

Room outlines come from rooms.json (the boundaries the rooms were defined with); results from the saved runs.
"""
import json, sys
from pathlib import Path
from PIL import Image, ImageDraw
here = Path(__file__).parent
REPO = Path(__file__).resolve().parents[4]   # the repository root
sys.path.insert(0, str(REPO))
from almond_mcp.environment import constructions as asm, diagrams as D, studies

OUT = Path(sys.argv[1])
RUN_T, RUN_TB, RUN_D = sys.argv[2:5]
OUT.mkdir(parents=True, exist_ok=True)
W, H, M = 4961, 3508, 220
SCALE = 3.4                                       # diagram units -> board pixels
PAPER, INK, MUTED, LINE, RED = (D._hex(c) for c in (D.PAPER, D.INK, D.MUTED, D.LINE, D.RED))
ROOMS = json.loads((here / "rooms.json").read_text())


def font(px, bold=False, mono=False):
    return D._font(px, mono, bold)


def paste(im, canvas, x, y, scale=SCALE):
    tmp = OUT / "_tmp.png"
    canvas.png(str(tmp), scale)
    tile = Image.open(tmp).convert("RGB")
    im.paste(tile, (int(x), int(y)))
    tmp.unlink()
    return tile.size


res_t, _ = studies.load_run(RUN_T)
res_b, _ = studies.load_run(RUN_TB)
res_d, _ = studies.load_run(RUN_D)
by_t = {r["room"]: r for r in res_t["rooms"]}
by_b = {r["room"]: r for r in res_b["rooms"]}
by_d = {r["room"]: r for r in res_d["rooms"]}

im = Image.new("RGB", (W, H), PAPER)
d = ImageDraw.Draw(im)
d.text((M, M - 40), "ATELIER 07", fill=INK, font=font(96, True))
d.text((M, M + 80), "Rooms, constructions and how each room performs", fill=MUTED, font=font(56))
title = "04  Rooms · Constructions"
d.text((W - M - d.textlength(title, font=font(56)), M - 10), title, fill=INK, font=font(56))
d.line([(M, H - M + 10), (W - M, H - M + 10)], fill=LINE, width=3)
d.text((M, H - M + 40), "Rooms defined in the Almond panel; constructions from the Almond library (EnergyPlus / ASHRAE HOF material data). "
       "Zurich-Affoltern TMYx 2011–2025. Thermal: coupled ISO 13790 rooms, no mechanical cooling. Almond environmental engine.",
       fill=MUTED, font=font(34))

# step strip, as in the panel
paste(im, D.step_strip("results", ("site", "rooms", "constructions", "study")), M, 440, 3.0)

# plans: hours above 26 degC with summer blinds, per level
values = {n: (by_b[n]["thermal"]["hours_above_26c_occupied"] if n in by_b and by_b[n]["method"] != "semi_outdoor" else None) for n in ROOMS}
outlines = [{"name": n, "outline": r["outline"], "level": r["z0"], "area": r["area"], "use": r["use"], "state": r.get("state", "enclosed")}
            for n, r in ROOMS.items() if n != "Garden pavilion"]
top = max([v for v in values.values() if v is not None] or [100])
plan = D.room_plan(outlines, "Hours above 26 °C, occupied · external blinds in summer", values, "h", (0, max(100, top)), "heat", width=640)
pw, ph = paste(im, plan, M, 720, 2.05)

# construction details
details = ["ew_rc_sandwich_exposed", "floor_internal_rc_exposed_oak", "roof_rc_warm_flat_exposed", "win_triple_lowe_steel_slim"]
x0 = M + pw + 120
cw = (W - M - x0 - 60) // 2
for i, cid in enumerate(details):
    c = D.construction_section(asm.properties(cid), width=520, height=300)
    sc = cw / 520
    paste(im, c, x0 + (i % 2) * (cw + 60), 720 + (i // 2) * int(300 * sc + 60), sc)

# per-room table, under the details
ty = 720 + 2 * int(300 * cw / 520 + 60) + 40
TX = x0
cols = [("Room", 0), ("Use", 430), ("Area", 720), ("Heating kWh/m²", 930), ("h > 26 °C", 1330), ("with blinds", 1600), ("sDA", 1900), ("ASE", 2100)]
for label, dx in cols:
    d.text((TX + dx, ty), label.upper(), fill=MUTED, font=font(30, mono=True))
d.line([(TX, ty + 48), (W - M, ty + 48)], fill=INK, width=3)
y = ty + 70
for n, r in ROOMS.items():
    t = by_t.get(n, {})
    b = by_b.get(n, {})
    dl = by_d.get(n, {})
    if t.get("method") == "semi_outdoor":
        cells = [n, r["use"], f"{r['area']:.0f} m²", "open", f"SET* {t['comfort']['set_c']['mean_occupied']} °C", "—", "—", "—"]
    else:
        th, tb = t.get("thermal", {}), b.get("thermal", {})
        cells = [n, r["use"], f"{r['area']:.0f} m²", f"{th.get('heating_kwh_m2', '—')}", f"{th.get('hours_above_26c_occupied', '—')}",
                 f"{tb.get('hours_above_26c_occupied', '—')}", f"{dl.get('sda_pct', '—')} %", f"{dl.get('ase_pct', '—')} %"]
    for (label, dx), v in zip(cols, cells):
        d.text((TX + dx, y), str(v), fill=INK, font=font(34, bold=(dx == 0)))
    d.line([(TX, y + 50), (W - M, y + 50)], fill=LINE, width=2)
    y += 62
im.save(OUT / "A07-board-04-rooms-constructions.png", dpi=(300, 300))
im.resize((1600, int(1600 * H / W)), Image.LANCZOS).save(OUT / "A07-board-04-rooms-constructions_preview.jpg", quality=88)
print("board 04 ->", OUT)
