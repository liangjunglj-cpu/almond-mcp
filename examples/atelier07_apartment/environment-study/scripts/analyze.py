"""Atelier 07 environmental study: daylight (annual + DF) per floor, envelope radiation, thermal zones,
plus per-frame illuminance for the day animation. Uses the almond_mcp.environment package as the tools do."""
import json, sys, time
from pathlib import Path
import numpy as np
here = Path(__file__).parent
REPO = Path(__file__).resolve().parents[4]   # the repository root
sys.path.insert(0, str(REPO)); sys.path.insert(0, str(REPO / "tests"))
from almond_mcp.environment import (scene as S, studies, daylight as dl, sky as skymod, solar, thermal, epw, raytrace)
from env_weather import synthetic_epw

EPW = here / "CHE_ZH_Zurich.Affoltern.066640_TMYx.2011-2025.epw"
if not EPW.exists():
    synthetic_epw(EPW, latitude=47.38, longitude=8.54, time_zone=1.0, elevation=556.0, mean_t=9.8, annual_amp=9.5,
                  daily_amp=4.5, rh=74.0, cloudiness=0.62, city="Synthetic Zurich-like 47N")
w = epw.read_epw(EPW)
print("weather", w.location.label(), "GHI", round(w["ghi"].sum() / 1000), "kWh/m2", "backend", raytrace.backend(), flush=True)

data = json.loads((here / "export.json").read_text(encoding="utf-8"))
REFL = {"Concrete": 0.35, "Oak": 0.30, "Ink": 0.05, "Skyglass": 0.15, "Terrazzo": 0.55, "Steel": 0.50, "Light": 0.60,
        "Paper": 0.75, "City": 0.30, "Stone": 0.50, "Plaster": 0.75, "Sage": 0.35, "Red": 0.15, "Linen": 0.60}
materials = {f"a07_{k.lower()}": {"reflectance": v} for k, v in REFL.items()}
materials["a07_glass"] = {"kind": "glazing", "transmittance": 0.70, "g_value": 0.50, "u_value": 0.7, "shade_transmittance": 0.10}
objs = []
for o in data["objects"]:
    if o["layer"] == "A07 / 07 Furniture":
        continue                                     # movable furniture: excluded, as IES LM-83 does
    m = o["material"].split("/ ")[-1]
    o = dict(o)
    o["env_material"] = "ignore" if o["name"] == "Shower screen" else f"a07_{m.lower()}"
    objs.append(o)
data = {**data, "objects": objs}
scene = S.scene_from_export(data, materials)
scene.north_deg = float(data["rhino_north_deg"]) - 90.0
print("scene", len(scene.triangles), "triangles", flush=True)

scale = data["units_to_m"]


def tris_of(pred):
    out = []
    for o in objs:
        if pred(o):
            v = np.asarray(o["vertices"], float).reshape(-1, 3) * scale
            f = np.asarray(o["faces"], np.int64).reshape(-1, 3)
            out.append(v[f])
    return np.concatenate(out) if out else np.zeros((0, 3, 3))


def grid_on(tris, offset, spacing):
    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    tris = tris[n[:, 2] / np.maximum(np.linalg.norm(n, axis=1), 1e-12) > 0.9]
    v = tris.reshape(-1, 3)
    return S.grid_from_triangles(v, np.arange(len(v)).reshape(-1, 3), spacing, offset, 0.0, True)


floors = tris_of(lambda o: o["layer"] == "A07 / 02 Floors")
zc = floors.mean(axis=1)[:, 2]
levels = {"Ground floor": floors[zc < 1.0], "Upper floor": floors[zc > 2.0]}
results = {"weather": {"label": w.location.label(), "epw": EPW.name, "synthetic": False, "source": "climate.onebuilding.org TMYx 2011-2025, MeteoSwiss 066640"}}
grids = {}
for name, tris in levels.items():
    g = grid_on(tris, 0.76, 0.5)
    g, dropped = studies.drop_enclosed_sensors(scene, g)
    grids[name] = g
    t0 = time.time()
    inp = {"model": "Atelier-07-Urban-Duplex.3dm", "level": name, "units_to_m": 1.0}
    ann = studies.run_daylight(scene, g, w, "annual", "medium", label=f"Atelier 07 {name}", dropped=dropped, inputs=inp)
    df = studies.run_daylight(scene, g, w, "daylight_factor", "medium", label=f"Atelier 07 {name} DF", dropped=dropped, inputs=inp)
    print(name, g.n, "sensors, dropped", dropped, "|", ann["headline"], "|", df["headline"], "|",
          round(time.time() - t0, 1), "s", ann["warnings"], flush=True)
    results[name] = {"annual": ann["run_id"], "df": df["run_id"], "sensors": g.n, "dropped": dropped,
                     "metrics": ann["metrics"], "df_metrics": df["metrics"], "warnings": ann["warnings"]}

# envelope radiation: roof, walls, facade (piers + glass)
env = tris_of(lambda o: o["layer"] in ("A07 / 01 Envelope", "A07 / 03 Facade", "A07 / 12 Roof / hide for cutaway")
              and o["name"] != "Concrete floor plate")
v = env.reshape(-1, 3)
g0 = S.grid_from_triangles(v, np.arange(len(v)).reshape(-1, 3), 0.5, 0.0, 0.0, face_up=False)
g, dropped = studies.orient_outward(g0, scene, 0.05)
rad = studies.run_radiation(scene, g, w, "draft", label="Atelier 07 envelope", dropped=dropped,
                            inputs={"model": "Atelier-07-Urban-Duplex.3dm", "units_to_m": 1.0})
print("radiation", g.n, "sensors", rad["headline"], rad["warnings"], flush=True)
results["radiation"] = {"run": rad["run_id"], "metrics": rad["metrics"]}


# thermal: two stacked zones on the structural lines; the glass sits 4-6 cm outside them
def box(z0, z1, x0=0.0, x1=12.8, y0=0.0, y1=10.0):
    p = np.array([[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0], [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]])
    f = [[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]]
    return {"guid": f"zone-{z0}", "layer": "zones", "name": "", "material": "", "transparency": 0, "env_material": "ignore",
            "vertices": (p / scale).reshape(-1).tolist(), "faces": np.array(f).reshape(-1).tolist()}


zl, zu = box(0.0, 3.224), box(3.224, 6.25)
zl["name"], zu["name"] = "Ground floor", "Upper floor"
zones = studies.zones_from_export({**data, "objects": objs + [zl, zu]}, scene, [zl["guid"], zu["guid"]])
for z in zones:
    print("zone", z.name, z.areas(), "floor", z.floor_area, flush=True)
common = dict(construction="insulated", u_values={"wall": 0.17, "roof": 0.15, "ground_floor": 0.25, "window": 0.7},
              mass="heavy", heating_setpoint=20.0, cooling_setpoint=None, schedule="residential", infiltration_ach=0.3,
              ventilation_ach=0.1, natural_ventilation_ach=3.0, natural_ventilation_on_above=24.0,
              occupancy_w_m2=3.0, equipment_w_m2=3.0, lighting_w_m2=2.0, window_g=0.50)
th = {}
for tag, g_factor in (("blinds", 0.15), ("no_blinds", 1.0)):
    st = thermal.Settings(**common, shading_g_factor=g_factor, shading_on_above_w_m2=200.0, shading_min_outdoor_c=12.0)
    r = studies.run_thermal(zones, scene, w, st, label=f"Atelier 07 thermal {tag}", inputs={"model": "Atelier-07"})
    th[tag] = r
    print("thermal", tag, r["headline"], flush=True)
    for s in r["zones"]:
        print("   ", s["zone"], "heat", s["heating_kwh_m2"], "op max", s["operative_temperature_c"]["max"], ">26h",
              s["hours_above_26c_occupied"], "TM52", s["tm52"].get("pass"), s["tm52"].get("failed_criteria"),
              "adaptive80", s["adaptive_ashrae55"]["comfortable_80_pct"], flush=True)
results["thermal"] = {k: {"run": v["run_id"], "zones": v["zones"]} for k, v in th.items()}
(here / "results.json").write_text(json.dumps(studies._jsonable(results), indent=1))

# ── day animation: clear-sky illuminance every 4 min on 21 June and 21 December, LM-83 blinds ──
groups, gdesc = dl.aperture_groups(scene)
print("aperture groups", [d["label"] for d in gdesc], flush=True)
store = {}
meta = []
for li, (name, g) in enumerate(grids.items()):
    tr = dl.Tracer(scene, groups)
    q = dl.quality("medium")
    c_open = dl.compute_coefficients(tr, g, q, 3)
    c_closed = {d["group"]: dl.compute_coefficients(dl.Tracer(scene, groups, closed={d["group"]}), g, q, 4 + d["group"])
                for d in gdesc}
    p = c_open.patches
    frames, closed_log = [], []
    for month, day, h0, h1 in ((6, 21, 4.5, 21.0), (12, 21, 7.5, 16.75)):
        doy = int(epw.MONTH_START[month - 1] + day)
        hours = np.arange(h0, h1 + 1e-9, 4 / 60)
        sp = solar.sun_position(w.location.latitude, w.location.longitude, w.location.time_zone, np.full_like(hours, doy), hours)
        for hh, alt, az in zip(hours, sp["altitude"], sp["azimuth"]):
            E = np.zeros(g.n)
            shut_labels = []
            if alt > 0:
                m = float(skymod.air_mass(90 - alt))
                e_dn = 127500.0 * np.exp(-0.21 * m)                        # IES clear-sky direct normal (lux)
                e_dh = 800.0 + 15500.0 * np.sin(np.radians(alt)) ** 0.5     # IES clear-sky diffuse horizontal
                az_m = (az - scene.north_deg) % 360
                sky_vec = skymod.single_sky(p, e_dh, e_dh + e_dn * np.sin(np.radians(alt)), 0.2, "cie_12", alt, az_m)
                sun_dir = solar.direction_vector(np.array([alt]), np.array([az]), scene.north_deg)
                Ssun, Gsun = dl.sun_coefficients(tr, g, sun_dir)
                sunsky = np.zeros(p.n)
                idx = int(p.index(sun_dir)[0])
                sunsky[idx] = e_dn / p.solid_angle[idx]
                for gi in range(c_open.D.shape[0]):
                    direct = np.where(Gsun[0] == gi, Ssun[0], 0.0) * e_dn
                    shut = gi > 0 and gi in c_closed and (direct > 1000).mean() > 0.02
                    c = c_closed[gi] if shut else c_open
                    E += c.total[gi] @ sky_vec + c.I[gi] @ sunsky + (0.0 if shut else direct)
                    if shut:
                        shut_labels.append(next(d["label"] for d in gdesc if d["group"] == gi))
            frames.append(E.astype(np.float32))
            closed_log.append(shut_labels)
            if li == 0:
                meta.append({"month": month, "day": day, "hour": float(hh), "alt": float(alt), "az": float(az)})
    key = "ground" if li == 0 else "upper"
    store[f"{key}_points"] = g.points
    store[f"{key}_cells"] = g.cells
    store[f"{key}_E"] = np.stack(frames)
    store[f"{key}_closed"] = np.array(json.dumps(closed_log))
    print("animation", name, len(frames), "frames", flush=True)
store["meta"] = np.array(json.dumps(meta))
np.savez_compressed(here / "anim.npz", **store)
print("done", flush=True)
