"""Studies: geometry + weather + options -> a saved, reproducible run.

Every run is written to ``<user data>/environment/runs/<run_id>/``:

  result.json   the summary returned to the caller (inputs, assumptions, metrics, warnings)
  arrays.npz    sensor points / normals / cells / areas and every per-sensor metric
  *.png         false-colour plans of the main metrics

so results can be listed, re-read, re-drawn in Rhino and compared without recomputing.
"""
from __future__ import annotations

import json
import math
import os
import time
import uuid
from datetime import datetime
from pathlib import Path

import numpy as np

from . import climate, daylight as dl, epw, radiation, raytrace, render, sky as skymod, thermal
from .scene import (LIBRARY, Material, Scene, SensorGrid, Shoebox, grid_from_points, grid_from_triangles,
                    material_from_spec, scene_from_export)

RUNS_ENV = "ALMOND_ENV_RUNS_DIR"
DISPLAY = {   # metric -> (unit, vmin, vmax, ramp, title)
    "da": ("%", 0, 100, "viridis", "Daylight autonomy DA300"),
    "cda": ("%", 0, 100, "viridis", "Continuous DA300"),
    "udi_useful": ("%", 0, 100, "viridis", "UDI 100-3000 lux"),
    "udi_exceeded": ("%", 0, 50, "magma", "UDI exceeded (> 3000 lux)"),
    "udi_fell_short": ("%", 0, 100, "magma", "UDI fell short (< 100 lux)"),
    "ase_hours": ("h", 0, 500, "magma", "Direct sun hours > 1000 lux (ASE)"),
    "mean_lux": ("lux", 0, None, "viridis", "Mean occupied-hour illuminance"),
    "df": ("%", 0, 5, "viridis", "Daylight factor"),
    "lux": ("lux", 0, None, "viridis", "Illuminance"),
    "kwh_m2": ("kWh/m2", None, None, "magma", "Incident solar irradiation"),
    "sun_hours": ("h", 0, None, "magma", "Direct sun hours"),
    "view_level": ("level", 0, 3, "viridis", "EN 17037 view out level (0 none, 1 min, 2 medium, 3 high)"),
    "sight_angle_deg": ("deg", 0, 90, "viridis", "EN 17037 horizontal sight angle"),
    "outside_distance_m": ("m", 0, 60, "viridis", "EN 17037 outside distance"),
}
# CIE skies whose luminance pattern does not depend on the sun (gradation only)
SUNLESS_SKIES = {"cie_overcast", "uniform", "cie_1", "cie_3", "cie_5"}
PERCENT_METRICS = {"da", "cda", "udi_useful", "udi_exceeded", "udi_fell_short", "udi_supplementary", "udi_autonomous"}


def runs_dir() -> Path:
    env = os.environ.get(RUNS_ENV)
    if env:
        d = Path(env)
    else:
        from .. import paths
        d = paths.user_data_dir() / "environment" / "runs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def new_run_id(kind: str) -> str:
    return f"{kind}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


def _jsonable(o):
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, np.ndarray):
        return _jsonable(o.tolist())
    if isinstance(o, (np.floating,)):
        v = float(o)
        return v if math.isfinite(v) else None
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, float) and not math.isfinite(o):
        return None
    return o


def save_run(run_id: str, result: dict, grid: SensorGrid | None, arrays: dict[str, np.ndarray]) -> Path:
    d = runs_dir() / run_id
    d.mkdir(parents=True, exist_ok=True)
    payload = {k: np.asarray(v, dtype=np.float32) for k, v in arrays.items()}
    if grid is not None:
        payload.update(points=grid.points.astype(np.float32), normals=grid.normals.astype(np.float32),
                       cells=grid.cells.astype(np.float32), area=grid.cell_area.astype(np.float32))
    np.savez_compressed(d / "arrays.npz", **payload)
    (d / "result.json").write_text(json.dumps(_jsonable(result), indent=1), encoding="utf-8")
    return d


def _safe_run_dir(run_id: str) -> Path:
    if not run_id or any(c in run_id for c in "/\\:") or run_id.startswith("."):
        raise ValueError("Invalid run id")
    d = runs_dir() / run_id
    if not (d / "result.json").is_file():
        raise ValueError(f"No environment run '{run_id}'. Use list_environment_runs.")
    return d


def load_run(run_id: str) -> tuple[dict, dict[str, np.ndarray]]:
    d = _safe_run_dir(run_id)
    result = json.loads((d / "result.json").read_text(encoding="utf-8"))
    arrays = {}
    if (d / "arrays.npz").is_file():
        with np.load(d / "arrays.npz") as z:
            arrays = {k: z[k] for k in z.files}
    return result, arrays


def list_runs(limit: int = 30) -> list[dict]:
    out = []
    for d in sorted(runs_dir().iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        f = d / "result.json"
        if not f.is_file():
            continue
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({"run_id": d.name, "study": r.get("study"), "label": r.get("label"),
                    "location": (r.get("weather") or {}).get("location"), "created": r.get("created"),
                    "headline": r.get("headline"), "metrics": r.get("display_metrics", [])})
        if len(out) >= limit:
            break
    return out


# ── geometry inputs ──────────────────────────────────────────────────────────

SHOEBOX_KEYS = set(Shoebox.__dataclass_fields__)


def shoebox_from_spec(spec: dict) -> Shoebox:
    if not isinstance(spec, dict):
        raise ValueError("shoebox must be an object, e.g. {\"width\": 6, \"depth\": 8, \"wwr\": 0.4}")
    unknown = set(spec) - SHOEBOX_KEYS
    if unknown:
        raise ValueError(f"Unknown shoebox fields {sorted(unknown)}; allowed: {sorted(SHOEBOX_KEYS)}")
    box = Shoebox(**spec)
    if box.glazing not in LIBRARY or LIBRARY[box.glazing].kind != "glazing":
        raise ValueError(f"shoebox glazing must be a glazing material: {[k for k, m in LIBRARY.items() if m.kind == 'glazing']}")
    box.validate()
    return box


def apply_ground_reflectance(scene: Scene, rho: float) -> None:
    """Give the library "ground" material the study's ground reflectance, so modelled ground and the
    ground patch beyond the model agree (and the parameter does what it says)."""
    if not 0.0 <= rho <= 0.95:
        raise ValueError("ground_reflectance must be 0..0.95")
    scene.materials = [Material(**{**m.__dict__, "reflectance": rho}) if m.name == "ground" else m for m in scene.materials]


def apply_shade_transmittance(scene: Scene, tau: float | None) -> None:
    if tau is None:
        return
    if not 0.0 <= tau <= 1.0:
        raise ValueError("shade_transmittance must be 0..1")
    scene.materials = [Material(**{**m.__dict__, "shade_transmittance": tau}) if m.kind == "glazing" else m
                       for m in scene.materials]


def scene_report(scene: Scene, max_objects: int = 40) -> dict:
    by_mat: dict[str, int] = {}
    for o in scene.objects:
        by_mat[o.get("material", "?")] = by_mat.get(o.get("material", "?"), 0) + 1
    lo, hi = scene.bounds()
    return {"triangles": int(len(scene.triangles)), "objects": len(scene.objects),
            "bounds_m": {"min": np.round(lo, 3).tolist(), "max": np.round(hi, 3).tolist()},
            "materials": scene.material_table(), "objects_per_material": by_mat,
            "classification": [{k: o.get(k) for k in ("guid", "layer", "name", "material", "reason") if o.get(k)}
                               for o in scene.objects[:max_objects]],
            "classification_truncated": len(scene.objects) > max_objects}


def grid_from_export(data: dict, scene: Scene, grid_guids: list[str], spacing: float, offset: float,
                     edge_offset: float, face_up: bool = True) -> SensorGrid:
    want = {g.lower() for g in grid_guids}
    scale = float(data.get("units_to_m", 1.0))
    verts, tris, n = [], [], 0
    for o in data.get("objects", []):
        if str(o.get("guid", "")).lower() not in want:
            continue
        v = np.asarray(o["vertices"], dtype=float).reshape(-1, 3) * scale
        f = np.asarray(o["faces"], dtype=np.int64).reshape(-1, 3)
        verts.append(v)
        tris.append(f + n)
        n += len(v)
    if not verts:
        raise ValueError("None of grid_guids produced a surface: pass the GUIDs of floor (or facade) surfaces, breps or meshes")
    return grid_from_triangles(np.vstack(verts), np.vstack(tris), spacing, offset, edge_offset, face_up)


def orient_outward(grid: SensorGrid, scene: Scene, offset: float) -> tuple[SensorGrid, int]:
    """Turn each planar sensor group to the side that sees more open sky (a facade drawn either way
    round still gets its sensors outside), then lift the points ``offset`` along that normal. Surfaces
    enclosed on both sides (a box's base on the ground, a wall against another) are dropped: returns
    (grid, number of sensors dropped). Expects a grid generated with zero offset."""
    tracer = dl.Tracer(scene)
    kinds = np.array([m.kind for m in tracer.scene.materials])[tracer.scene.tri_material]
    rng = np.random.default_rng(3)
    N = grid.normals.copy()
    keep = np.ones(grid.n, dtype=bool)
    for g in np.unique(grid.group):
        sel = np.flatnonzero(grid.group == g)
        if g < 0:                      # curved: decide per point with fewer rays
            groups = [[i] for i in sel]
        else:
            groups = [sel]
        for idx in groups:
            idx = np.asarray(idx)
            probe = idx[rng.choice(len(idx), size=min(len(idx), 8), replace=False)]
            esc, opaque = [], []
            for sgn in (1.0, -1.0):
                nn = np.repeat(sgn * N[probe], 24, axis=0)
                d = dl.cosine_directions(nn, rng.random(len(nn)), rng.random(len(nn)))
                o = np.repeat(grid.points[probe], 24, axis=0) + nn * dl.EPS   # tiny: a slab may sit 1 cm above the ground
                _, tri = tracer.bvh.intersect(o, d)
                esc.append(float((tri < 0).mean()))
                opaque.append(float(((tri >= 0) & (kinds[np.maximum(tri, 0)] != "glazing")).mean()))
            if max(esc) < 0.01:
                keep[idx] = False                                 # sees no sky from either side
            elif max(esc) > 0.02 and abs(esc[0] - esc[1]) > 0.01:
                if esc[1] > esc[0]:                               # the side that sees more sky is outside
                    N[idx] *= -1.0
            elif opaque[1] < opaque[0]:
                N[idx] *= -1.0
    if not keep.any():
        raise ValueError("Every grid surface is enclosed on both sides (no open sky): nothing to analyse")
    # the two faces of a thin solid (a 12 mm glass pane, a slab edge) give two stacked copies of the
    # same sensors once both face outwards: keep one of each pair facing the same way
    cell = max(0.25 * grid.spacing, 0.02)
    key = np.concatenate([np.round(grid.points / cell).astype(np.int64), np.round(N * 4).astype(np.int64)], axis=1)
    for axis in range(3):          # snap the along-normal coordinate coarsely so 12 mm apart is "the same place"
        along = np.abs(N[:, axis]) > 0.9
        key[along, axis] = np.round(grid.points[along, axis] / 0.1).astype(np.int64)
    _, first = np.unique(key, axis=0, return_index=True)
    unique = np.zeros(grid.n, dtype=bool)
    unique[first] = True
    keep &= unique
    pts = grid.points + N * offset
    cells = grid.cells + (N * offset)[:, None, :]
    out = SensorGrid(points=pts[keep], normals=N[keep], cell_area=grid.cell_area[keep], spacing=grid.spacing,
                     cells=cells[keep], group=grid.group[keep])
    return out, int((~keep).sum())


def drop_enclosed_sensors(scene: Scene, grid: SensorGrid, lid: float = 0.6, reach: float = 2.0,
                          rays: int = 48) -> tuple[SensorGrid, int]:
    """Remove sensors inside fixed joinery (a kitchen island, a wardrobe): every direction within 45 deg
    of the sensor's normal is blocked within ``lid`` metres - a ceiling never is - and every other
    direction hits opaque geometry within ``reach``. Counting them would add dark 'floor area' that
    nobody occupies. Returns (grid, number dropped)."""
    tracer = dl.Tracer(scene)
    kinds = np.array([m.kind for m in tracer.scene.materials])[tracer.scene.tri_material]
    rng = np.random.default_rng(11)
    nn = np.repeat(grid.normals, rays, axis=0)
    u1, u2 = dl.stratified_uniforms(grid.n, rays, rng)
    # uniform (not cosine) hemisphere directions, so grazing gaps under a worktop count too
    d = dl.cosine_directions(nn, 1.0 - (1.0 - u1) ** 2, u2)
    t, tri = tracer.bvh.intersect(np.repeat(grid.points, rays, axis=0) + nn * dl.EPS, d)
    opaque = (tri >= 0) & (kinds[np.maximum(tri, 0)] != "glazing")
    up = np.einsum("ij,ij->i", d, nn) >= math.cos(math.radians(45))
    ok = np.where(up, opaque & (t <= lid), opaque & (t <= reach))
    enclosed = ok.reshape(grid.n, rays).all(axis=1)
    if enclosed.all():
        raise ValueError("Every sensor is enclosed by nearby surfaces: check the grid surfaces and work-plane height")
    keep = ~enclosed
    return (SensorGrid(points=grid.points[keep], normals=grid.normals[keep], cell_area=grid.cell_area[keep],
                       spacing=grid.spacing, cells=grid.cells[keep], group=grid.group[keep]), int(enclosed.sum()))


def zones_from_export(data: dict, scene: Scene, zone_guids: list[str]) -> list[thermal.Zone]:
    """Zones from closed Rhino objects (one zone per GUID); glazing in the scene is attached to the
    zone face it lies on; faces shared between the listed zones are adiabatic."""
    scale = float(data.get("units_to_m", 1.0))
    by_guid: dict[str, list[dict]] = {}
    for o in data.get("objects", []):
        by_guid.setdefault(str(o.get("guid", "")).lower(), []).append(o)
    meshes = []
    for g in zone_guids:
        parts = by_guid.get(g.lower())
        if not parts:
            raise ValueError(f"Zone {g} was not exported (is it a closed polysurface, extrusion or mesh?)")
        verts, tris, n = [], [], 0
        for o in parts:
            v = np.asarray(o["vertices"], dtype=float).reshape(-1, 3) * scale
            f = np.asarray(o["faces"], dtype=np.int64).reshape(-1, 3)
            verts.append(v)
            tris.append(f + n)
            n += len(v)
        name = parts[0].get("name") or f"zone {g[:8]}"
        meshes.append((g, name, np.vstack(verts), np.vstack(tris)))
    zone_set = {g.lower() for g in zone_guids}
    windows = []
    kinds = {m.name: m for m in scene.materials}
    for o in scene.objects:
        mat = kinds.get(o.get("material", ""))
        if mat is None or mat.kind != "glazing" or str(o.get("guid", "")).lower() in zone_set:
            continue
        idx = scene.objects.index(o)
        sel = scene.tri_object == idx
        windows.append({"vertices": scene.vertices, "triangles": scene.triangles[sel], "name": o.get("name") or o.get("layer") or "window",
                        "g_value": mat.g_value, "u_value": mat.u_value})
    zones = []
    for i, (g, name, v, t) in enumerate(meshes):
        others = [(mv, mt) for j, (_, _, mv, mt) in enumerate(meshes) if j != i]
        z = thermal.zone_from_mesh(name, v, t, windows, others)
        z.source["guid"] = g
        zones.append(z)
    return zones


# ── daylight ─────────────────────────────────────────────────────────────────

def occupied_mask(weather, start: float = 8.0, end: float = 18.0, weekdays_only: bool = False) -> np.ndarray:
    if not 0 <= start < end <= 24:
        raise ValueError("occupied hours must satisfy 0 <= start < end <= 24")
    hod = weather.hour_of_day
    m = (hod >= start) & (hod < end)
    if weekdays_only:
        m &= weather.weekday() < 5
    return m


def _images(run_dir: Path, grid: SensorGrid, metrics: dict[str, np.ndarray], keys: list[str], label: str) -> list[str]:
    out = []
    for k in keys:
        if k not in metrics:
            continue
        unit, lo, hi, ramp, title = DISPLAY.get(k, ("", None, None, "viridis", k))
        vals = metrics[k] * (100.0 if k in PERCENT_METRICS else 1.0)
        try:
            r = render.render_grid_png(grid.cells, grid.normals, vals, run_dir / f"{k}.png", f"{title} - {label}", unit,
                                       lo, hi, ramp)
            out.append(r["path"])
        except Exception as exc:   # an image must never sink the analysis
            out.append(f"(image for {k} failed: {type(exc).__name__}: {exc})")
    return out


def run_daylight(scene: Scene, grid: SensorGrid, weather, study: str = "annual", quality: str = "medium",
                 label: str = "", occupied: tuple[float, float] = (8.0, 18.0), weekdays_only: bool = False,
                 dynamic_shading: bool = True, aperture_grouping: str = "orientation",
                 da_threshold: float = 300.0, en17037: bool = True,
                 point_time: dict | None = None, views: list[dict] | None = None,
                 ground_reflectance: float = 0.2, seed: int = 0, inputs: dict | None = None,
                 dropped: int = 0, probes: list | None = None) -> dict:
    if study not in ("annual", "daylight_factor", "point_in_time"):
        raise ValueError("study must be annual, daylight_factor or point_in_time")
    if study == "annual" and weather is None:
        raise ValueError("An annual study needs an EPW weather file (epw_path)")
    if study == "point_in_time" and weather is None and (point_time or {}).get("sky", "epw") not in SUNLESS_SKIES:
        raise ValueError("This point-in-time sky needs the site's weather or sun position: give epw_path "
                         f"(skies that need none: {', '.join(sorted(SUNLESS_SKIES))})")
    q = dl.quality(quality)
    t0 = time.time()
    warnings: list[str] = []
    apply_ground_reflectance(scene, ground_reflectance)
    groups, gdesc = dl.aperture_groups(scene, aperture_grouping)
    if not gdesc:
        warnings.append("No glazing in the model: light enters only through openings without glass. "
                        "Put windows on a layer named like 'Glazing' or set user text almond:env_material.")
    tracer = dl.Tracer(scene, groups)
    north = scene.north_deg
    coeff = dl.compute_coefficients(tracer, grid, q, seed)
    run_id = new_run_id("daylight")
    result: dict = {"run_id": run_id, "study": study, "label": label or study, "created": datetime.now().isoformat(timespec="seconds"),
                    "engine": {"method": "daylight coefficients: deterministic sky-patch sampling, interreflections by an "
                                         "irradiance-cache radiosity solve, sun traced exactly", "ray_backend": raytrace.backend(),
                               "quality": quality, "settings": q.__dict__, "coefficients": coeff.info},
                    "scene": scene_report(scene), "aperture_groups": gdesc,
                    "grid": {"sensors": grid.n, "area_m2": round(grid.area, 2), "spacing_m": grid.spacing},
                    "inputs": inputs or {}}
    if weather is not None:
        result["weather"] = {"location": weather.location.label(), "latitude": weather.location.latitude,
                             "longitude": weather.location.longitude, "file": weather.source_path,
                             "data_quality_warnings": weather.report.get("warnings", [])}
    arrays: dict[str, np.ndarray] = {}
    display: list[str] = []
    if study == "daylight_factor":
        df = dl.daylight_factor(coeff, ground_reflectance)
        v = df["df"]
        a = grid.cell_area
        arrays.update(df=v, df_direct=df["direct"], df_interreflected=df["interreflected"])
        summ = {"average_df_pct": round(float(np.average(v, weights=a)), 2), "median_df_pct": round(float(np.median(v)), 2),
                "min_df_pct": round(float(v.min()), 2), "max_df_pct": round(float(v.max()), 2),
                "uniformity_min_over_mean": round(float(v.min() / max(np.average(v, weights=a), 1e-9)), 2),
                "area_df_ge_2_pct": round(100 * float(a[v >= 2].sum() / a.sum()), 1),
                "area_df_ge_1_pct": round(100 * float(a[v >= 1].sum() / a.sum()), 1),
                "average_direct_sky_part_pct": round(float(np.average(df["direct"], weights=a)), 2),
                "average_interreflected_part_pct": round(float(np.average(df["interreflected"], weights=a)), 2),
                "sky": "CIE overcast (1955), ground reflectance %.2f" % ground_reflectance}
        if weather is not None:
            dh = weather["diffuse_illuminance"][skymod_up(weather)]
            med = float(np.median(dh)) if dh.size else 0.0
            if med > 0:
                summ["en17037_df_targets"] = {
                    "median_diffuse_illuminance_lux": round(med),
                    "df_for_300_lux_pct": round(300 / med * 100, 2), "df_for_100_lux_pct": round(100 / med * 100, 2),
                    "note": "EN 17037 Annex A: daylight factor targets for this location (target 300 lx on 50 % of the "
                            "area, minimum 100 lx on 95 %) - compare with the area shares above."}
        result["metrics"] = summ
        result["headline"] = f"average DF {summ['average_df_pct']} %, {summ['area_df_ge_2_pct']} % of area >= 2 %"
        display = ["df"]
    elif study == "point_in_time":
        pt = point_time or {}
        month, day, hour = int(pt.get("month", 6)), int(pt.get("day", 21)), float(pt.get("hour", 12))
        from .solar import hour_index, direction_vector, sun_position
        hi = hour_index(month, day, hour)
        sky_name = pt.get("sky", "epw")
        if sky_name == "epw":
            sm = skymod.sky_matrix(weather, mf=q.mf, hours=np.array([hi]), north_deg=north, ground_reflectance=ground_reflectance)
            sky_vec = sm.sky[0]
            sun_dir, sun_n = sm.sun_dir[0], float(sm.sun_normal[0])
            sky_desc = {"sky": "Perez all-weather from the EPW hour", "diffuse_horizontal_lux": round(float(sm.diffuse_horizontal[0])),
                        "direct_normal_lux": round(sun_n), "sun_altitude": round(float(sm.sun_altitude[0]), 2)}
        else:
            if weather is not None:
                loc = weather.location
                sp = sun_position(loc.latitude, loc.longitude, loc.time_zone, np.array([epw.MONTH_START[month - 1] + day]),
                                  np.array([hour]))
                alt, az = float(sp["altitude"][0]), float(sp["azimuth"][0])
            elif sky_name in SUNLESS_SKIES and not float(pt.get("direct_normal_illuminance", 0.0)):
                alt, az = 45.0, 180.0              # the sky's shape ignores the sun: no site needed
            else:
                raise ValueError(f"A point-in-time study with sky '{sky_name}' needs the site's sun position: give epw_path")
            e_h = float(pt.get("horizontal_illuminance", 10000.0))
            p = skymod.patches(q.mf)
            sky_vec = skymod.single_sky(p, e_h, e_h, ground_reflectance, sky_name, alt, (az - north) % 360)
            sun_dir, sun_n = direction_vector(alt, az, north), float(pt.get("direct_normal_illuminance", 0.0))
            sky_desc = {"sky": sky_name, "diffuse_horizontal_lux": e_h, "direct_normal_lux": sun_n, "sun_altitude": round(alt, 2)}
        E = dl.point_in_time(coeff, sky_vec, sun_dir, sun_n, tracer, grid)
        a = grid.cell_area
        arrays["lux"] = E
        result["metrics"] = {"time": {"month": month, "day": day, "hour": hour}, **sky_desc,
                             "mean_lux": round(float(np.average(E, weights=a))), "min_lux": round(float(E.min())),
                             "max_lux": round(float(E.max())), "area_ge_300_lux_pct": round(100 * float(a[E >= 300].sum() / a.sum()), 1),
                             "area_gt_3000_lux_pct": round(100 * float(a[E > 3000].sum() / a.sum()), 1)}
        result["headline"] = f"mean {result['metrics']['mean_lux']} lux at {month}/{day} {hour:g}h"
        display = ["lux"]
    else:
        occ = occupied_mask(weather, occupied[0], occupied[1], weekdays_only)
        sun_up = skymod_up(weather)
        hours = np.flatnonzero(occ | (sun_up if en17037 else np.zeros_like(occ)))
        sm = skymod.sky_matrix(weather, mf=q.mf, hours=hours, north_deg=north, ground_reflectance=ground_reflectance)
        S, Gs = dl.sun_coefficients(tracer, grid, sm.sun_dir)
        closed = {}
        if dynamic_shading:
            for g in gdesc:
                closed[g["group"]] = dl.compute_coefficients(dl.Tracer(scene, groups, closed={g["group"]}), grid, q, seed + g["group"])
        ann = dl.annual_illuminance(coeff, closed, sm, S, Gs, gdesc, dynamic_shading=dynamic_shading and bool(closed))
        occ_cols = occ[hours]
        summ, per = dl.annual_metrics(ann.illuminance[:, occ_cols], ann.direct_sun[:, occ_cols], grid.cell_area,
                                      da_threshold=da_threshold)
        arrays.update(per)
        if en17037:
            day_cols = sun_up[hours]
            summ["en17037"] = dl.en17037_provision(ann.illuminance[:, day_cols], grid.cell_area)
        if gdesc and dynamic_shading:
            summ["shades"] = [{"group": g["label"], "closed_occupied_hours_pct": round(100 * float(ann.shade_closed[g["group"]][occ_cols].mean()), 1),
                               "shade_transmittance": float(np.unique([m.shade_transmittance for m in scene.materials if m.kind == "glazing"]).max())}
                              for g in gdesc]
        summ["reference"] = {"leed_v4_eq_daylight_option_1": "sDA300/50% >= 55 % (2 points) or >= 75 % (3 points), with ASE1000,250 <= 10 % - check the rating version you are using",
                             "leed_v4_1": "sDA300/50% >= 40 % / 55 % / 75 % for 1 / 2 / 3 points; ASE reported",
                             "note": "Thresholds quoted for comparison only. LEED is a trademark of the U.S. Green Building "
                                     "Council; Almond is not affiliated with or endorsed by it, and this is not a LEED assessment."}
        if views:
            vp = np.array([v["position"] for v in views], dtype=float)
            vd = np.array([v["direction"] for v in views], dtype=float)
            vg = grid_from_points(vp, vd)
            vc = dl.compute_coefficients(tracer, vg, q, seed + 101)
            vS, vG = dl.sun_coefficients(tracer, vg, sm.sun_dir)
            vclosed = {g: dl.compute_coefficients(dl.Tracer(scene, groups, closed={g}), vg, q, seed + 101 + g) for g in closed}
            vann = dl.annual_illuminance(vc, vclosed, sm, vS, vG, gdesc, dynamic_shading=dynamic_shading and bool(closed),
                                         closed_override=ann.shade_closed)
            Ev = vann.illuminance[:, occ_cols]
            dgp = dl.dgp_simplified(Ev)
            # DGPs is not valid with the sun in view: find the hours direct sun reaches the eye (its
            # aperture group's shade open)
            edn = sm.sun_normal[occ_cols]
            closed_at = ann.shade_closed[:, occ_cols]                          # (G, h)
            vGo = vG[occ_cols].astype(np.int64)                                # (h, V)
            open_ = ~closed_at[vGo, np.arange(len(edn))[:, None]] | (vGo == 0)
            sun_eye = (vS[occ_cols] * edn[:, None] * open_).T > 50.0           # (V, h) lux of direct sun at the eye
            summ["glare_dgps"] = []
            for i in range(len(views)):
                ok = ~sun_eye[i]
                summ["glare_dgps"].append({"view": i, "position": views[i]["position"], "direction": views[i]["direction"],
                                           "sun_in_view_pct": round(100 * float(sun_eye[i].mean()), 1),
                                           **dl.glare_summary(dgp[i][ok]),
                                           "max_dgps": round(float(dgp[i][ok].max()), 3) if ok.any() else None})
            summ["glare_note"] = ("Simplified DGP (Wienold 2009) from vertical eye illuminance, occupied hours, same shade "
                                  "schedule. The classes cover only hours without direct sun at the eye: DGPs is not valid "
                                  "with the sun in view, and sun_in_view_pct counts those hours - treat them as glare.")
        result["metrics"] = summ
        result["headline"] = f"sDA {summ['sda_pct']} %, ASE {summ['ase_pct']} %, UDI 100-3000 {summ['udi_pct'][f'useful_100_3000']} %"
        result["occupancy"] = {"start": occupied[0], "end": occupied[1], "weekdays_only": weekdays_only, "hours": int(occ.sum())}
        display = ["da", "ase_hours", "udi_useful", "mean_lux"]
    result["timing_s"] = round(time.time() - t0, 2)
    result["display_metrics"] = [k for k in display if k in arrays] + [k for k in arrays if k not in display]
    if probes:
        result["probes"] = probe_values(grid, arrays, probes)
    if dropped:
        warnings.append(f"{dropped} sensors were dropped: they sit inside fixed joinery or furniture "
                        "(every direction blocked within 0.6 m), so they are not occupiable floor.")
    result["warnings"] = warnings + _scene_warnings(scene, grid)
    result["assumptions"] = [
        "Surfaces are Lambertian; glazing is a specular transmitter with Fresnel angular falloff (no reflection off glass).",
        f"Ground beyond the model: a uniform patch of reflectance {ground_reflectance:g}.",
        "Reflectances by material classification - check scene.classification; wrong layers give wrong results.",
    ]
    run_dir = save_run(run_id, result, grid, arrays)
    result["images"] = _images(run_dir, grid, arrays, display, result["label"])
    (run_dir / "result.json").write_text(json.dumps(_jsonable(result), indent=1), encoding="utf-8")
    result["run_dir"] = str(run_dir)
    return result


def probe_values(grid: SensorGrid, arrays: dict, probes: list) -> list[dict]:
    """Every metric at the sensor nearest (in plan) to each probe point [x, y] or [x, y, z], in metres."""
    out = []
    for p in probes:
        q = np.asarray(p, dtype=float).reshape(-1)
        if q.size not in (2, 3):
            raise ValueError("a probe is [x, y] or [x, y, z] in metres")
        d = np.linalg.norm(grid.points[:, :2] - q[:2], axis=1)
        if q.size == 3:
            d = d + np.abs(grid.points[:, 2] - q[2])
        k = int(np.argmin(d))
        row = {"probe": q.round(3).tolist(), "sensor": grid.points[k].round(3).tolist(), "offset_m": round(float(d[k]), 3)}
        for name, arr in arrays.items():
            v = np.asarray(arr)
            if v.ndim == 1 and len(v) == grid.n:
                row[name] = round(float(v[k]) * (100.0 if name in PERCENT_METRICS else 1.0), 2)
        out.append(row)
    return out


def skymod_up(weather) -> np.ndarray:
    from .solar import sun_positions_for
    return sun_positions_for(weather)["altitude"] > 0


def covered_glazing(scene: Scene, samples: int = 6) -> list[dict]:
    """Glazing objects that lie on an opaque surface (a window drawn over an uncut wall): light cannot
    pass them. Returns [{"object", "covered_pct"}] for those more than 20 % covered."""
    sc = scene.clean()
    kinds = np.array([m.kind for m in sc.materials])[sc.tri_material]
    opaque = kinds == "opaque"
    glass = kinds == "glazing"
    if not glass.any() or not opaque.any():
        return []
    a, b, c = sc.corners()
    from .raytrace import BVH
    bvh = BVH(a[opaque], b[opaque], c[opaque])
    normal, area = sc.normals()
    rng = np.random.default_rng(5)
    out = []
    for obj in np.unique(sc.tri_object[glass]):
        sel = np.flatnonzero(glass & (sc.tri_object == obj))
        pick = rng.choice(sel, size=min(len(sel) * samples, 48), p=area[sel] / area[sel].sum())
        r1, r2 = rng.random(len(pick)), rng.random(len(pick))
        s = np.sqrt(r1)
        pts = (1 - s)[:, None] * a[pick] + (s * (1 - r2))[:, None] * b[pick] + (s * r2)[:, None] * c[pick]
        n = normal[pick]
        hit = np.zeros(len(pick), dtype=bool)
        for sgn in (1.0, -1.0):          # a short probe through the pane from both sides
            o = pts + sgn * n * 0.003
            t, tri = bvh.intersect(o, -sgn * n, t_max=0.006)
            hit |= tri >= 0
        frac = float(hit.mean())
        if frac > 0.2:
            o = sc.objects[int(obj)] if int(obj) < len(sc.objects) else {}
            out.append({"object": o.get("guid") or o.get("name") or int(obj), "layer": o.get("layer", ""),
                        "covered_pct": round(100 * frac)})
    return out


def _scene_warnings(scene: Scene, grid: SensorGrid) -> list[str]:
    out = []
    for c in covered_glazing(scene):
        out.append(f"Glazing {c['object']} ({c['layer']}) lies on an opaque surface over {c['covered_pct']} % of its area, "
                   "so no light passes it: cut the opening in the wall (or move the wall to its own layer and exclude it).")
    lo, hi = scene.bounds()
    size = hi - lo
    if size.max() > 5000:
        out.append(f"The model spans {size.max():.0f} m: check the document units.")
    if size.max() < 1.0 and len(scene.triangles):
        out.append(f"The model spans only {size.max():.2f} m: check the document units.")
    if grid.n and len(scene.triangles):
        inside = ((grid.points >= lo - 0.5) & (grid.points <= hi + 0.5)).all(axis=1)   # sensors sit a little off surfaces
        if not inside.all():
            out.append(f"{int((~inside).sum())} sensors lie outside the model's bounding box.")
    return out


# ── radiation ────────────────────────────────────────────────────────────────

def run_radiation(scene: Scene, grid: SensorGrid, weather, quality: str = "draft", months=None, hours=None,
                  bounces: int = 1, label: str = "", ground_reflectance: float = 0.2, inputs: dict | None = None,
                  dropped: int = 0) -> dict:
    apply_ground_reflectance(scene, ground_reflectance)
    base = dl.quality(quality)
    q = dl.Quality(rays=base.rays, bounces=int(bounces), patch_samples=base.patch_samples, ground_samples=base.ground_samples,
                   cache_cell=base.cache_cell, mf=max(2, base.mf))
    t0 = time.time()
    mask = radiation.hour_mask(weather, months, hours)
    if not mask.any():
        raise ValueError("The months/hours filter selects no hours")
    res = radiation.irradiation(scene, grid, weather, q, mask, ground_reflectance, scene.north_deg)
    run_id = new_run_id("radiation")
    a = grid.cell_area
    k = res["kwh_m2"]
    result = {"run_id": run_id, "study": "radiation", "label": label or "radiation",
              "created": datetime.now().isoformat(timespec="seconds"),
              "weather": {"location": weather.location.label(), "file": weather.source_path,
                          "data_quality_warnings": weather.report.get("warnings", [])},
              "engine": {"method": "cumulative Perez solar sky (daylight coefficients) + sun traced hourly",
                         "ray_backend": raytrace.backend(), "quality": quality, "bounces": bounces, "sky_mf": q.mf},
              "scene": scene_report(scene), "grid": {"sensors": grid.n, "area_m2": round(grid.area, 2), "spacing_m": grid.spacing},
              "period": {"months": months or "all", "hours": hours or "all", "hours_count": res["hours"]},
              "metrics": {"mean_kwh_m2": round(float(np.average(k, weights=a)), 1), "min_kwh_m2": round(float(k.min()), 1),
                          "max_kwh_m2": round(float(k.max()), 1), "total_mwh": round(float((k * a).sum() / 1000), 2),
                          "mean_direct_share_pct": round(100 * float(np.average(res["direct_kwh_m2"], weights=a) / max(np.average(k, weights=a), 1e-9)), 1),
                          "mean_sun_hours": round(float(np.average(res["sun_hours"], weights=a)), 0),
                          "monthly_mean_kwh_m2": np.round(np.average(res["monthly_kwh_m2"], axis=1, weights=a), 1).tolist()},
              "inputs": inputs or {}}
    result["headline"] = f"mean {result['metrics']['mean_kwh_m2']} kWh/m2, max {result['metrics']['max_kwh_m2']} kWh/m2"
    result["timing_s"] = round(time.time() - t0, 2)
    arrays = {"kwh_m2": k, "sun_hours": res["sun_hours"], "direct_kwh_m2": res["direct_kwh_m2"], "diffuse_kwh_m2": res["diffuse_kwh_m2"]}
    result["display_metrics"] = list(arrays)
    result["warnings"] = _scene_warnings(scene, grid)
    if dropped:
        result["warnings"].append(f"{dropped} sensors were dropped: their surface faces no open sky on either side "
                                  "(the underside or inner face of a solid, a base resting on the ground, a wall against another).")
    run_dir = save_run(run_id, result, grid, arrays)
    result["images"] = _images(run_dir, grid, arrays, ["kwh_m2", "sun_hours"], result["label"])
    (run_dir / "result.json").write_text(json.dumps(_jsonable(result), indent=1), encoding="utf-8")
    result["run_dir"] = str(run_dir)
    return result


# ── thermal ──────────────────────────────────────────────────────────────────

def building_totals(summaries: list[dict]) -> dict:
    """Whole-building figures over the simulated zones: each energy summed, divided by their total floor area."""
    area = sum(s["floor_area_m2"] for s in summaries)
    out = {"zones": len(summaries), "floor_area_m2": round(area, 1)}
    if not area:
        return out
    for key in ("heating", "cooling", "lighting", "equipment"):
        if all(f"{key}_kwh_m2" in s for s in summaries):
            kwh = sum(s[f"{key}_kwh_m2"] * s["floor_area_m2"] for s in summaries)
            out[f"{key}_kwh"] = round(kwh, 0)
            out[f"{key}_kwh_m2"] = round(kwh / area, 1)
    return out


def prepare_lighting(zones: list[thermal.Zone], scene: Scene, weather, settings: thermal.Settings,
                     quality: str = "draft") -> dict | None:
    """For daylight-linked lighting: the daylight at every zone's control points, traced in one pass on
    ``scene`` (the daylight scene of the zones). Returns what was done, or None when the lights follow
    the schedule."""
    if settings.lighting_control is None:
        return None
    from . import lighting
    missing = [z.name for z in zones if z.daylight_points is None or not len(z.daylight_points)]
    if missing:
        raise ValueError(f"lighting_control needs control points on each zone's floor; none for {missing}. It works "
                         "for shoeboxes and for rooms (analyze_rooms); for Rhino zone volumes use analyze_rooms")
    t0 = time.time()
    pts = np.vstack([z.daylight_points for z in zones])
    lux = lighting.control_illuminance(scene, pts, weather, quality)
    k = 0
    for z in zones:
        n = len(z.daylight_points)
        z.daylight_lux = lux[k:k + n]
        k += n
    return {"control_points": int(len(pts)), "quality": quality, "timing_s": round(time.time() - t0, 1),
            "method": "daylight at the work plane (0.8 m) on a 1 m grid per zone (at most "
                      f"{lighting.MAX_POINTS} points), daylight coefficients with the Perez sky of every daylight "
                      "hour, dynamic shades as in the daylight study; each point controls an equal share of the luminaires"}


def run_thermal(zones: list[thermal.Zone], scene: Scene, weather, settings: thermal.Settings, label: str = "",
                inputs: dict | None = None, notes: list[str] | None = None) -> dict:
    settings.validate()
    t0 = time.time()
    lighting_info = prepare_lighting(zones, scene, weather, settings)
    solar_info = thermal.solar_on_surfaces(zones, scene, weather, scene.north_deg)
    run_id = new_run_id("thermal")
    summaries, arrays = [], {}
    all_notes = list(notes or [])
    for i, z in enumerate(zones):
        all_notes += [f"{z.name}: {n}" for n in thermal.apply_construction(z, settings)]
        if z.source.get("warning"):
            all_notes.append(f"{z.name}: {z.source['warning']}")
        if z.source.get("windows_given") and not z.source.get("windows_assigned"):
            all_notes.append(f"{z.name}: none of the glazing lies on this zone's faces (within 5 cm), so it has no windows")
        res = thermal.simulate(z, weather, settings)
        summaries.append(thermal.summarize(z, res, weather, settings))
        for k in ("t_op", "t_air", "heating_w", "cooling_w", "solar_w"):
            arrays[f"z{i}_{k}"] = res[k]
        if (inputs or {}).get("export_csv"):
            from . import cases
            d = runs_dir() / run_id
            d.mkdir(parents=True, exist_ok=True)
            safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in z.name)[:40] or f"zone{i}"
            summaries[-1]["hourly_csv"] = cases.write_csv(d / f"hourly-{i:02d}-{safe}.csv", cases.hourly_columns(weather, res))
        monthly = []
        for m in range(1, 13):
            sel = weather.month == m
            monthly.append({"month": epw.MONTH_NAMES[m - 1], "heating_kwh": round(float(res["heating_w"][sel].sum() / 1000), 1),
                            "cooling_kwh": round(float(res["cooling_w"][sel].sum() / 1000), 1),
                            "t_op_mean": round(float(res["t_op"][sel].mean()), 1), "t_op_max": round(float(res["t_op"][sel].max()), 1)})
        summaries[-1]["monthly"] = monthly
    free = settings.heating_setpoint is None and settings.cooling_setpoint is None
    building = building_totals(summaries) if len(summaries) > 1 else None
    if settings.cooling_setpoint is not None:
        all_notes.append("Set-points control the air temperature; comfort uses operative temperature, which sunlit "
                         "glass and warm surfaces can lift above the cooling set-point.")
    if any(z.source.get("type") == "shoebox" for z in zones):
        all_notes.append("Shoebox: one room with a single exposed facade, every other surface adiabatic - the result "
                         "is per room, not for a whole building.")
    result = {"run_id": run_id, "study": "thermal", "label": label or "thermal", "created": datetime.now().isoformat(timespec="seconds"),
              "weather": {"location": weather.location.label(), "file": weather.source_path,
                          "data_quality_warnings": weather.report.get("warnings", [])},
              "engine": {"method": "ISO 13790 hourly 5R1C per zone; solar gains ray traced on each window and wall",
                         "ray_backend": raytrace.backend(), "solar_sampling": solar_info,
                         **({"lighting_control": lighting_info} if lighting_info else {})},
              "settings": settings.__dict__, "zones": summaries, "building": building,
              "mode": "free-running" if free else "conditioned",
              "inputs": inputs or {}, "notes": all_notes,
              "assumptions": ["Zone boundaries between zones are adiabatic; no moisture balance (indoor absolute humidity = outdoor).",
                              "Schedules, U-values and gains are presets unless overridden - see settings.",
                              "A design-stage comparison model, not a compliance simulation."]}
    if free:
        result["headline"] = "; ".join(f"{s['zone']}: {s.get('adaptive_ashrae55', {}).get('comfortable_80_pct', '?')} % comfortable (ASHRAE 55 adaptive), TM52 {'pass' if s.get('tm52', {}).get('pass') else 'fail'}" for s in summaries)
    else:
        result["headline"] = "; ".join(f"{s['zone']}: heating {s['heating_kwh_m2']} / cooling {s['cooling_kwh_m2']} kWh/m2" for s in summaries)
    result["timing_s"] = round(time.time() - t0, 2)
    run_dir = save_run(run_id, result, None, arrays)
    result["run_dir"] = str(run_dir)
    return result


def climate_report(weather, hdd_base: float = 18.0, cdd_base: float = 18.0, thresholds: dict | None = None,
                   include_psychrometric_bins: bool = False) -> dict:
    out = climate.summarize(weather, hdd_base, cdd_base, thresholds)
    if include_psychrometric_bins:
        out["psychrometric_bins"] = climate.psychrometric_bins(weather)
    return out


def climate_charts(weather) -> dict:
    """Monthly diurnal averages as data, a chart (SVG + PNG) and a CSV, saved as a run folder."""
    from . import charts
    run_id = new_run_id("climate")
    d = runs_dir() / run_id
    d.mkdir(parents=True, exist_ok=True)
    diurnal = climate.diurnal_averages(weather)
    files = charts.save(climate.diurnal_chart(weather), d / "monthly-diurnal-averages")
    rows = ["month,hour_ending," + ",".join(f"{k}_{u.replace('/', '_per_')}" for k, _, u in climate.DIURNAL_VARIABLES)]
    for m in diurnal["months"]:
        for h in range(24):
            rows.append(f"{m['month']},{h + 1}," + ",".join(f"{m[k][h]:g}" for k, _, _ in climate.DIURNAL_VARIABLES))
    csv = d / "monthly-diurnal-averages.csv"
    csv.write_text("\n".join(rows) + "\n", encoding="utf-8")
    files["csv"] = str(csv)
    result = {"run_id": run_id, "study": "climate_charts", "label": weather.location.label(), "files": files,
              "diurnal": diurnal}
    save_run(run_id, result, None, {})
    return result


# ── rooms ────────────────────────────────────────────────────────────────────

def prepare_rooms(data: dict, overrides: dict | None = None) -> tuple[list, list, Scene, list[str]]:
    """Rooms, their enclosure checks and the analysis scene. Room volumes drawn as zones are left out of
    the scene unless nothing is modelled around them (then their faces are the envelope)."""
    from . import rooms as rm
    problems: list[str] = []
    rooms = rm.rooms_from_export(data, problems)
    if not rooms:
        raise ValueError(" ".join(problems) if problems else
                         "No rooms in the model: tag closed volumes, surfaces or boundary curves with almond:room "
                         "(define_room) first")
    base = scene_from_export(data, overrides)
    if data.get("rhino_north_deg") is not None:
        base.north_deg = float(data["rhino_north_deg"]) - 90.0      # Rhino Sun panel: counter-clockwise from +X
    volume_guids = {g.lower() for r in rooms if r.source in ("volume", "boundary") for g in r.guids}
    exclude = {i for i, o in enumerate(base.objects) if str(o.get("guid", "")).lower() in volume_guids}
    ground_z = min(r.floor_z for r in rooms)         # as zones_from_rooms: the lowest room floor
    encs = [rm.enclosure(r, base, exclude, ground_z=ground_z, neighbours=rooms) for r in rooms]
    ignore = dict(overrides or {})
    for r, e in zip(rooms, encs):
        if r.source in ("volume", "boundary") and not e.self_enclosed:
            for g in r.guids:
                ignore[g.lower()] = "ignore"
    scene = scene_from_export(data, ignore) if ignore != (overrides or {}) else base
    scene.north_deg = base.north_deg
    notes = problems + [e.warning for e in encs if e.warning]
    return rooms, encs, scene, notes


def _windows(scene: Scene) -> list[dict]:
    out = []
    for i, o in enumerate(scene.objects):
        sel = scene.tri_object == i
        if not sel.any():
            continue
        mat = scene.materials[int(scene.tri_material[sel][0])]
        if mat.kind != "glazing":
            continue
        out.append({"vertices": scene.vertices, "triangles": scene.triangles[sel], "name": o.get("name") or o.get("layer") or "window",
                    "g_value": mat.g_value, "u_value": mat.u_value, "construction": o.get("construction", "")})
    return out


def envelope_surfaces(zones: list[thermal.Zone]) -> list[dict]:
    """The exterior surfaces of the zones in the form codes.check_envelope expects."""
    kinds = {"wall": "wall_external", "window": "window", "roof": "roof", "ground_floor": "floor_ground",
             "exposed_floor": "floor_exposed"}
    out = []
    for z in zones:
        for s in z.surfaces:
            if s.kind in kinds:
                out.append({"kind": kinds[s.kind], "area": s.area, "normal": list(s.normal), "u_value": s.u_value,
                            "g_value": s.g_value, "room": z.name, "construction": s.construction})
    return out


def run_rooms_thermal(data: dict, weather, settings: thermal.Settings, label: str = "", inputs: dict | None = None,
                      overrides: dict | None = None, envelope_pack: str = "", pack_options: dict | None = None,
                      cooling: bool = True, setpoints: dict | None = None) -> dict:
    """Thermal study of user-defined rooms: enclosed and semi-open rooms by coupled 5R1C zones with their
    constructions, open rooms by semi-outdoor comfort. ``setpoints`` ({"heating_setpoint", "cooling_setpoint"})
    replaces the room uses' defaults in every room that has no set-point of its own. inputs["export_csv"]
    writes one hourly CSV per room (named columns, energy balance included)."""
    from . import codes, rooms as rm
    settings.validate()
    t0 = time.time()
    rooms, encs, scene, notes = prepare_rooms(data, overrides)
    zones = rm.zones_from_rooms(rooms, encs, scene, _windows(scene), problems=notes)
    own = {r.name: r.setpoints for r in rooms}
    for z in zones:
        if setpoints and z.source.get("enclosure") != "semi_open":
            z.profile.update({k: v for k, v in setpoints.items() if k not in own.get(z.name, {})})
        z.source.pop("warning", None)                      # the room mesh is re-sampled, not a modelling error
        if not cooling:
            z.profile["cooling_setpoint"] = None
        if z.source.get("openings"):
            z.opening_ach = rm.opening_air_changes(z.source["openings"], z.volume, weather)
    solar_info = thermal.solar_on_surfaces(zones, scene, weather, scene.north_deg) if zones else {"surfaces": 0}
    lighting_info = None
    if settings.lighting_control is not None and zones:
        shells, _ = _daylight_shells(data, rooms, encs, scene, overrides)
        lighting_info = prepare_lighting(zones, shells, weather, settings)
    for z in zones:
        notes += [f"{z.name}: {n}" for n in thermal.apply_construction(z, settings)]
    results, balance = rm.couple(zones, weather, settings) if zones else ([], {"links": 0})
    run_id = new_run_id("rooms")
    arrays: dict[str, np.ndarray] = {}
    out_rooms = []
    zi = {z.name: (z, r) for z, r in zip(zones, results)}
    for k, (room, enc) in enumerate(zip(rooms, encs)):
        entry = {"room": room.name, "use": room.use, "defined_by": room.source, "enclosure": enc.to_json(),
                 "construction_set": room.construction_set or None}
        if enc.state == "open":
            roof = next((c for c, op, p in zip(enc.tri_construction, enc.tri_open, enc.tri_points)
                         if c and not op and np.cross(p[1] - p[0], p[2] - p[0])[2] > 0), "")
            so = rm.semi_outdoor(room, enc, scene, weather, roof_construction=str(roof))
            for key, arr in so.pop("_hourly").items():
                arrays[f"r{k}_{key}"] = arr
            so.pop("_points", None)
            so.pop("_svv", None)
            entry.update(method="semi_outdoor", comfort=so)
        else:
            z, res = zi[room.name]
            summ = thermal.summarize(z, res, weather, settings)
            summ["constructions"] = _construction_table(z)
            entry.update(method="5R1C" + (" + openings" if enc.state == "semi_open" else ""), thermal=summ)
            for key in ("t_op", "t_air", "heating_w", "cooling_w"):
                arrays[f"r{k}_{key}"] = res[key]
            for key, v in res["balance_w"].items():
                arrays[f"r{k}_bal_{key}"] = v
            if (inputs or {}).get("export_csv"):
                from . import cases
                d = runs_dir() / run_id
                d.mkdir(parents=True, exist_ok=True)
                safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in room.name)[:40] or f"room{k}"
                summ["hourly_csv"] = cases.write_csv(d / f"hourly-{k:02d}-{safe}.csv", cases.hourly_columns(weather, res))
        out_rooms.append(entry)
    notes.append("Mechanical cooling to the room set-points." if cooling else "No mechanical cooling: rooms run free in warm weather.")
    result = {"run_id": run_id, "study": "rooms_thermal", "label": label or "rooms", "created": datetime.now().isoformat(timespec="seconds"),
              "weather": {"location": weather.location.label(), "file": weather.source_path},
              "engine": {"method": "rooms: enclosure check per room; enclosed / semi-open rooms as ISO 13790 5R1C zones with "
                                   "constructions, thermal mass from areal heat capacity and heat exchange through shared faces; "
                                   "open rooms as semi-outdoor comfort (SolarCal MRT, SET*)",
                         "ray_backend": raytrace.backend(), "solar_sampling": solar_info, "interzone": balance,
                         **({"lighting_control": lighting_info} if lighting_info else {})},
              "settings": settings.__dict__, "rooms": out_rooms, "inputs": inputs or {}, "notes": notes,
              "assumptions": ["Room-use gains, schedules and set-points: Almond assumptions (rooms.ROOM_USES), overridable per room.",
                              "Faces with no construction use the preset U-values of the settings; mass falls back to the preset "
                              "class when less than half the opaque area has a construction.",
                              "No moisture balance; a design-stage comparison model, not a compliance simulation."]}
    if envelope_pack:
        result["envelope_check"] = codes.check_envelope(envelope_surfaces(zones), envelope_pack, weather,
                                                        **({"north_deg": scene.north_deg} | (pack_options or {})))
    result["building"] = building_totals([e["thermal"] for e in out_rooms if e.get("thermal")])
    heads = []
    for e in out_rooms:
        if e["method"] == "semi_outdoor":
            heads.append(f"{e['room']}: open, SET* mean {e['comfort']['set_c']['mean_occupied']} degC")
        else:
            t = e["thermal"]
            heads.append(f"{e['room']}: heating {t['heating_kwh_m2']} / cooling {t['cooling_kwh_m2']} kWh/m2, "
                         f"{t['hours_above_26c_occupied']} h > 26 degC")
    result["headline"] = "; ".join(heads)
    result["timing_s"] = round(time.time() - t0, 2)
    run_dir = save_run(run_id, result, None, arrays)
    result["run_dir"] = str(run_dir)
    return result


def _construction_table(z: thermal.Zone) -> list[dict]:
    from . import constructions as asm, rooms as rm
    rows: dict[tuple, dict] = {}
    for s in z.surfaces:
        if s.kind == "opening":
            continue
        key = (s.kind, s.construction)
        # an unassigned shared face exchanges heat at the coupling default (rooms.couple), not the preset's 0
        unassigned_shared = s.kind == "interzone" and not s.construction
        r = rows.setdefault(key, {"surface": s.kind, "construction": s.construction or "(preset)",
                                  "name": asm.get(s.construction)["name"] if s.construction else
                                  ("shared face, default partition" if unassigned_shared else "settings preset"),
                                  "area_m2": 0.0, "u_value": rm.INTERZONE_U_DEFAULT if unassigned_shared else s.u_value})
        r["area_m2"] = round(r["area_m2"] + s.area, 2)
    return sorted(rows.values(), key=lambda r: (r["surface"], -r["area_m2"]))


def _daylight_shells(data: dict, rooms, encs, scene: Scene, overrides: dict | None) -> tuple[Scene, list[str]]:
    """The daylight scene for room studies. A self-enclosed room volume is its own envelope, but as one opaque
    object it would also cover the window in it: it is replaced by its boundary without the glazed parts.
    A room resting on the ground with no floor element gets a floor, so the sky's ground does not shine in."""
    from .scene import LIBRARY
    notes: list[str] = []
    ignore = dict(overrides or {})
    v_parts, mats, objs = [], [], []
    names = ["wall", "floor", "ceiling"]
    for r, e in zip(rooms, encs):
        keep = np.zeros(len(e.tri_points), bool)
        if e.self_enclosed and r.source == "volume":
            for g in r.guids:
                ignore[g.lower()] = "ignore"
            keep |= ~(e.tri_glazing if e.tri_glazing is not None else np.zeros(len(keep), bool))
        if e.tri_ground_only is not None and e.tri_ground_only.any():
            keep |= e.tri_ground_only
            if not e.self_enclosed:
                notes.append(f"Room {r.name}: no floor element under it - the daylight study adds an opaque floor "
                             f"(reflectance {LIBRARY['floor'].reflectance:g}) at its boundary")
        if not keep.any():
            continue
        t = e.tri_points[keep]
        nz = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])[:, 2]
        nz = nz / np.maximum(np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1), 1e-12)
        # the boundary faces point out of the room: down is the floor, up the ceiling
        mats.append(np.where(nz < -0.7, 1, np.where(nz > 0.7, 2, 0)))
        v_parts.append(t.reshape(-1, 3))
        objs.append({"name": f"{r.name} (room boundary)", "room_shell": r.name, "guid": ""})
    base = scene_from_export(data, ignore) if ignore != (overrides or {}) else scene
    base.north_deg = scene.north_deg
    if not v_parts:
        return base, notes
    counts = [len(p) // 3 for p in v_parts]
    shell = Scene(np.vstack(v_parts), np.arange(sum(counts) * 3).reshape(-1, 3), np.concatenate(mats),
                  np.repeat(np.arange(len(objs)), counts), [LIBRARY[n] for n in names], objs, scene.north_deg)
    return base.merged(shell), notes


def run_rooms_daylight(data: dict, weather, study: str = "annual", quality: str = "medium", label: str = "",
                       spacing: float = 0.5, height: float = 0.8, overrides: dict | None = None, **kw) -> dict:
    """Daylight per room: one work-plane grid per room, one simulation, metrics per room."""
    from . import rooms as rm
    rooms, encs, scene, notes = prepare_rooms(data, overrides)
    scene, shell_notes = _daylight_shells(data, rooms, encs, scene, overrides)
    notes = notes + shell_notes
    grids, owner = [], []
    for k, r in enumerate(rooms):
        g = rm.daylight_grid(r, spacing, height)
        if g.n:
            grids.append(g)
            owner.append(np.full(g.n, k))
    if not grids:
        raise ValueError("Could not place sensors on any room floor")
    owner = np.concatenate(owner)
    grid = SensorGrid(np.vstack([g.points for g in grids]), np.vstack([g.normals for g in grids]),
                      np.concatenate([g.cell_area for g in grids]), spacing, np.vstack([g.cells for g in grids]), owner)
    res = run_daylight(scene, grid, weather, study, quality, label or f"rooms {study}", **kw)
    _, arrays = load_run(res["run_id"])
    per = []
    for k, r in enumerate(rooms):
        m = owner == k
        if not m.any():
            continue
        a = grid.cell_area[m]
        row = {"room": r.name, "use": r.use, "enclosure": encs[k].state, "sensors": int(m.sum()),
               "floor_area_m2": round(rm._floor_area(r), 1), "grid_area_m2": round(float(a.sum()), 1)}
        if "df" in arrays:
            v = arrays["df"][m]
            row.update(average_df_pct=round(float(np.average(v, weights=a)), 2),
                       area_df_ge_2_pct=round(100 * float(a[v >= 2].sum() / a.sum()), 1))
        if "da" in arrays:
            da = arrays["da"][m]
            row["sda_pct"] = round(100 * float(a[da >= 0.5].sum() / a.sum()), 1)
        if "ase_hours" in arrays:
            ase = arrays["ase_hours"][m]
            row["ase_pct"] = round(100 * float(a[ase > 250].sum() / a.sum()), 1)
        if "udi_useful" in arrays:
            row["udi_useful_mean_pct"] = round(100 * float(np.average(arrays["udi_useful"][m], weights=a)), 1)
        if "lux" in arrays:
            e = arrays["lux"][m]
            row.update(mean_lux=round(float(np.average(e, weights=a))), min_lux=round(float(e.min())),
                       area_ge_300_lux_pct=round(100 * float(a[e >= 300].sum() / a.sum()), 1))
        per.append(row)
    res["rooms"] = per
    res["room_names"] = [r.name for r in rooms]
    res["notes"] = notes + res.get("notes", [])
    def head(p: dict) -> str:
        if "sda_pct" in p:
            return f"sDA {p['sda_pct']} %"
        if "mean_lux" in p:
            return f"mean {p['mean_lux']} lx"
        return f"DF {p.get('average_df_pct')} %"
    res["headline"] = "; ".join(f"{p['room']}: {head(p)}" for p in per)
    result_path = Path(res["run_dir"]) / "result.json"
    if result_path.is_file():
        saved = json.loads(result_path.read_text(encoding="utf-8"))
        saved.update(rooms=per, room_names=res["room_names"], headline=res["headline"], notes=res["notes"])
        result_path.write_text(json.dumps(_jsonable(saved), indent=1), encoding="utf-8")
    np.save(Path(res["run_dir"]) / "room_owner.npy", owner)
    return res


def run_rooms_view_out(data: dict, view_height_m: float = 1.2, spacing: float = 0.6, edge: float = 0.3,
                       label: str = "", overrides: dict | None = None) -> dict:
    """EN 17037 view out per room: viewpoints on a grid view_height_m above each room's floor, traced on the
    room-study scene (en17037.view_out). Returns each room's share of floor at each level, and saves the
    level, sight-angle and outside-distance maps as a run."""
    from . import en17037 as en, rooms as rm
    if not 0.2 <= spacing <= 5:
        raise ValueError("grid spacing must be 0.2..5 m")
    if not 0.3 <= view_height_m <= 3:
        raise ValueError("view height must be 0.3..3 m")
    t0 = time.time()
    rooms, encs, scene, notes = prepare_rooms(data, overrides)
    scene, shell_notes = _daylight_shells(data, rooms, encs, scene, overrides)
    grids, owner = [], []
    for k, r in enumerate(rooms):
        g = rm.daylight_grid(r, spacing, view_height_m, edge)
        if g.n:
            grids.append(g)
            owner.append(np.full(g.n, k))
    if not grids:
        raise ValueError("Could not place viewpoints on any room floor")
    owner = np.concatenate(owner)
    grid = SensorGrid(np.vstack([g.points for g in grids]), np.vstack([g.normals for g in grids]),
                      np.concatenate([g.cell_area for g in grids]), spacing, np.vstack([g.cells for g in grids]), owner)
    v = en.view_out(scene, grid.points)
    per = []
    for k, r in enumerate(rooms):
        m = owner == k
        if not m.any():
            continue
        s = en.view_summary({key: val[m] for key, val in v.items()}, grid.cell_area[m])
        per.append({"room": r.name, "use": r.use, "viewpoints": int(m.sum()), **s["area_at_least_pct"],
                    "sight_angle_mean_deg": s["sight_angle_deg"]["mean"], "outside_distance_m_median": s["outside_distance_m_median"],
                    "layers_seen_pct": s["layers_seen_pct"], "level_of_most_points": s["level_of_most_points"]})
    run_id = new_run_id("viewout")
    arrays = {"view_level": v["level"].astype(float), "sight_angle_deg": v["sight_angle_deg"],
              "outside_distance_m": np.minimum(v["outside_distance_m"], 999.0)}
    whole = en.view_summary(v, grid.cell_area)
    result = {"run_id": run_id, "study": "rooms_view_out", "label": label or "view out", "created": datetime.now().isoformat(timespec="seconds"),
              "rooms": per, "metrics": whole, "display_metrics": list(arrays),
              "inputs": {"view_height_m": view_height_m, "grid_spacing_m": spacing, "edge_offset_m": edge, "units_to_m": data.get("units_to_m")},
              "grid": {"sensors": grid.n, "area_m2": round(grid.area, 2), "spacing_m": grid.spacing},
              "headline": "; ".join(f"{p['room']}: medium on {p['medium']} %, high on {p['high']} %" for p in per),
              "notes": notes + shell_notes + ["Indicative, by Almond's implementation of the EN 17037 Annex A view-out principles; "
                                              "thresholds quoted by value. Glazing is treated as clear."],
              "timing_s": round(time.time() - t0, 2)}
    run_dir = save_run(run_id, result, grid, arrays)
    np.save(run_dir / "room_owner.npy", owner)
    result["run_dir"] = str(run_dir)
    return result
