"""EN 17037 view out and exposure to sunlight, by ray tracing on the analysis scene.

Our own implementation of the assessment principles of EN 17037:2018 (Annex A): no tables or text of
the standard are reproduced; the level thresholds are the published values, quoted by number. Results
are indicative design checks, not a certification.

View out, per viewpoint (default 1.2 m above the floor, looking out horizontally):
  * horizontal sight angle: the share of horizontal directions whose ray passes through glazing (or an
    unglazed opening) to the outside, in degrees;
  * outside distance: from the window to the first obstruction outside, median over those rays;
  * layers: sky (a ray through the window rises into open sky), landscape (the horizon band, within
    10 deg of horizontal, is visible through the window) and ground (a ray through the window comes down on
    the ground).
  Levels: sight angle >= 14 / 28 / 54 deg, outside distance >= 6 / 20 / 50 m, layers landscape / landscape +
  one more / all three, for minimum / medium / high; a viewpoint's level is the lowest of the three.

Exposure to sunlight, per reference point on the inside of a window: the time on a chosen day (the
standard uses a day between 1 February and 21 March) during which the sun is above a minimum altitude and
reaches the point unobstructed. Levels: >= 1.5 h minimum, 3 h medium, 4 h high. The minimum sun
altitude depends on the location in the standard; Almond defaults to 10 deg and you should set the value
that applies.
"""
from __future__ import annotations

import math

import numpy as np

from .raytrace import BVH
from .scene import principal_normal

SIGHT_LEVELS = (14.0, 28.0, 54.0)            # deg: minimum, medium, high
DISTANCE_LEVELS = (6.0, 20.0, 50.0)          # m
SUN_LEVELS_H = (1.5, 3.0, 4.0)               # hours
LEVEL_NAMES = ("none", "minimum", "medium", "high")
FAR = 1e4


def _level(value: float, steps: tuple[float, float, float]) -> int:
    return int(sum(value >= s for s in steps))


class _Scene:
    def __init__(self, scene):
        sc = scene.clean()
        a, b, c = sc.corners()
        mats = sc.materials
        self.kind = np.array([m.kind for m in mats])[sc.tri_material]
        self.ground = np.array([m.name == "ground" for m in mats])[sc.tri_material]
        self.all = BVH(a, b, c)
        op = self.kind == "opaque"
        self.solid = BVH(a[op], b[op], c[op])
        self.zmin = float(sc.vertices[:, 2].min()) if len(sc.vertices) else 0.0

    def through(self, o: np.ndarray, d: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """For rays from inside: (passes out through glazing or an opening, distance from the window to the next
        opaque hit outside (FAR = none), that hit is ground). Glass panes are crossed; the first opaque hit stops."""
        n = len(o)
        out = np.zeros(n, dtype=bool)
        dist = np.full(n, FAR)
        ground = np.zeros(n, dtype=bool)
        t, tri = self.all.intersect(o, d)
        miss = tri < 0
        out[miss] = True                                     # an unglazed opening straight to the outside
        glass = ~miss & (self.kind[np.maximum(tri, 0)] == "glazing")
        if glass.any():
            p = o[glass] + d[glass] * t[glass, None]
            t2, tri2 = self.solid.intersect(p + d[glass] * 1e-3, d[glass])
            out[glass] = True
            hit = tri2 >= 0
            idx = np.flatnonzero(glass)
            dist[idx[hit]] = t2[hit]
            ground[idx[hit]] = self.ground[tri2[hit]] | ((p[hit] + d[glass][hit] * t2[hit, None])[:, 2] < self.zmin + 0.3)
        return out, dist, ground


def view_out(scene, points: np.ndarray, step_deg: float = 1.0, elevation_step_deg: float = 5.0) -> dict:
    """EN 17037 view out at each viewpoint (N, 3) in metres. Returns per-point arrays and summaries."""
    S = _Scene(scene)
    pts = np.asarray(points, dtype=float).reshape(-1, 3)
    az = np.radians(np.arange(0.0, 360.0, step_deg))
    hdir = np.stack([np.sin(az), np.cos(az), np.zeros_like(az)], axis=1)
    els = np.radians(np.arange(-60.0, 60.0 + 1e-9, elevation_step_deg))
    n = len(pts)
    sight = np.zeros(n)
    dist = np.zeros(n)
    sky = np.zeros(n, dtype=bool)
    land = np.zeros(n, dtype=bool)
    grd = np.zeros(n, dtype=bool)
    for i, p in enumerate(pts):
        o = np.repeat(p[None], len(hdir), axis=0)
        ok, dd, _ = S.through(o, hdir)
        sight[i] = ok.sum() * step_deg
        dist[i] = float(np.median(dd[ok])) if ok.any() else 0.0
        if not ok.any():
            continue
        az_ok = az[ok][:: max(1, int(round(4.0 / step_deg)))]          # every ~4 deg across the window
        E, A = np.meshgrid(els, az_ok, indexing="ij")
        d = np.stack([np.cos(E) * np.sin(A), np.cos(E) * np.cos(A), np.sin(E)], axis=-1).reshape(-1, 3)
        oo = np.repeat(p[None], len(d), axis=0)
        ok2, d2, g2 = S.through(oo, d)
        e = E.ravel()
        sky[i] = bool((ok2 & (e > 0) & (d2 >= FAR)).any())
        land[i] = bool((ok2 & (np.abs(e) <= math.radians(10.0))).any())
        grd[i] = bool((ok2 & (e < 0) & g2).any())
    layers = land.astype(int) + (land & (sky | grd)).astype(int) + (land & sky & grd).astype(int)
    lv_sight = np.array([_level(v, SIGHT_LEVELS) for v in sight])
    lv_dist = np.array([_level(v, DISTANCE_LEVELS) for v in dist])
    lv = np.minimum(np.minimum(lv_sight, lv_dist), layers)
    return {"sight_angle_deg": sight, "outside_distance_m": np.minimum(dist, FAR), "layers": layers,
            "sky": sky, "landscape": land, "ground": grd, "level": lv,
            "level_sight": lv_sight, "level_distance": lv_dist}


def view_summary(v: dict, area: np.ndarray) -> dict:
    a = np.asarray(area, float)
    tot = a.sum() or 1.0
    shares = {LEVEL_NAMES[k]: round(100 * float(a[v["level"] >= k].sum() / tot), 1) for k in (1, 2, 3)}
    d = v["outside_distance_m"]
    return {"area_at_least_pct": shares, "sight_angle_deg": {"min": round(float(v["sight_angle_deg"].min()), 1),
                                                             "mean": round(float(np.average(v["sight_angle_deg"], weights=a)), 1),
                                                             "max": round(float(v["sight_angle_deg"].max()), 1)},
            "outside_distance_m_median": round(float(np.median(np.minimum(d, 999.0))), 1),
            "layers_seen_pct": {k: round(100 * float(a[v[k]].sum() / tot), 1) for k in ("sky", "landscape", "ground")},
            "thresholds": {"sight_angle_deg": SIGHT_LEVELS, "outside_distance_m": DISTANCE_LEVELS,
                           "layers": ["landscape", "landscape + one more", "sky + landscape + ground"]},
            "level_of_most_points": LEVEL_NAMES[int(np.median(v["level"]))] if len(v["level"]) else None}


def window_objects(scene, guids: list[str] | None = None) -> tuple[list[int], str]:
    """The glazing objects to assess as windows: ``guids`` when given; otherwise those that carry a window
    construction (assign_construction), when the model has any; otherwise every glazing object."""
    sc = scene.clean()
    kinds = np.array([m.kind for m in sc.materials])[sc.tri_material]
    glazed = [int(o) for o in np.unique(sc.tri_object[kinds == "glazing"])]
    if guids:
        want = {str(g).lower() for g in guids}
        pick = [o for o in glazed if str(sc.objects[o].get("guid", "")).lower() in want]
        return pick, "window_guids"
    with_c = [o for o in glazed if sc.objects[o].get("construction")]
    if with_c:
        return with_c, "glazing with a window construction"
    return glazed, "every glazing object"


def window_reference_points(scene, inset_m: float = 0.05, objects: list[int] | None = None) -> list[dict]:
    """The centre of each glazing object (or of ``objects``), moved inset_m to its inside: the side from which
    a view through the pane reaches open sky (from the outside, the view through the pane meets the room)."""
    sc = scene.clean()
    kinds = np.array([m.kind for m in sc.materials])[sc.tri_material]
    a, b, c = sc.corners()
    nrm, area = sc.normals()
    S = _Scene(scene)
    out = []
    rng = np.random.default_rng(3)
    for obj in (objects if objects is not None else np.unique(sc.tri_object[kinds == "glazing"])):
        sel = (kinds == "glazing") & (sc.tri_object == obj)
        w = area[sel]
        if w.sum() <= 0:
            continue
        cen = ((a[sel] + b[sel] + c[sel]) / 3.0 * w[:, None]).sum(axis=0) / w.sum()
        n = principal_normal(nrm[sel], w)                 # also for a pane drawn as a thin solid (normals cancel)
        n = n / max(np.linalg.norm(n), 1e-12)
        half = 0.5 * float(np.ptp(np.concatenate([a[sel], b[sel], c[sel]]) @ n))   # half the pane thickness
        best = None
        for sgn in (1.0, -1.0):
            p = cen - sgn * n * (inset_m + half)              # candidate inside point, clear of the pane
            d = rng.normal(size=(64, 3))
            d /= np.linalg.norm(d, axis=1)[:, None]
            d[:, 2] = np.abs(d[:, 2])
            d = d[(d @ (-sgn * n)) < 0]                       # look away from the candidate's own side, through the glass
            t, tri = S.solid.intersect(np.repeat(p[None], len(d), axis=0), d)
            open_ = float((tri < 0).mean()) if len(d) else 0.0
            if best is None or open_ > best[0]:
                best = (open_, p, sgn * n)
        o = sc.objects[int(obj)] if int(obj) < len(sc.objects) else {}
        face = float((w * np.abs(nrm[sel] @ n)).sum())
        solid = np.linalg.norm((nrm[sel] * w[:, None]).sum(axis=0)) < 0.05 * w.sum()
        out.append({"object": o.get("name") or o.get("layer") or f"glazing {int(obj)}", "guid": o.get("guid", ""),
                    "point": best[1], "outward_normal": best[2], "area_m2": round(face / (2.0 if solid else 1.0), 2)})
    return out


def sunlight_hours(scene, points: np.ndarray, normals: np.ndarray, latitude: float, longitude: float, time_zone: float,
                   north_deg: float, day_of_year: int, min_altitude_deg: float = 10.0, step_min: float = 5.0) -> np.ndarray:
    """Hours of direct sun on each reference point (N, 3) on the day: sun above min_altitude_deg, in front
    of the window (outward_normal . sun > 0), and not blocked by opaque surfaces."""
    from .solar import direction_vector, sun_position
    S = _Scene(scene)
    t = np.arange(0.0, 24.0, step_min / 60.0) + step_min / 120.0
    sp = sun_position(latitude, longitude, time_zone, np.full_like(t, day_of_year), t)
    up = sp["altitude"] >= min_altitude_deg
    if not up.any():
        return np.zeros(len(points))
    dirs = direction_vector(sp["altitude"][up], sp["azimuth"][up], north_deg)
    pts = np.asarray(points, float).reshape(-1, 3)
    nrm = np.asarray(normals, float).reshape(-1, 3)
    hours = np.zeros(len(pts))
    for i, (p, nv) in enumerate(zip(pts, nrm)):
        front = dirs @ nv > 0
        if not front.any():
            continue
        d = dirs[front]
        o = np.repeat(p[None], len(d), axis=0)            # from the inside reference point; glazing does not block
        _, tri = S.solid.intersect(o, d)
        hours[i] = float((tri < 0).sum()) * step_min / 60.0
    return hours


def sunlight_level(hours: float) -> str:
    return LEVEL_NAMES[_level(hours, SUN_LEVELS_H)]


def sunlight_study(scene, location, month: int, day: int, out_dir, date_range: list | None = None,
                   min_altitude_deg: float = 10.0, window_guids: list[str] | None = None) -> dict:
    """Exposure to sunlight per window on month/day, and with ``date_range`` = [[m0, d0], [m1, d1]] every day
    of the range (hours per day, the best day and a chart in ``out_dir``). Shared by the MCP tool and the
    Rhino panel. Raises ValueError when the model has no windows."""
    from pathlib import Path

    from . import charts, epw, solar
    from .climate import _date
    if not 0 <= min_altitude_deg < 60:
        raise ValueError("min_altitude_deg must be 0..60")
    solar.hour_index(month, day, 12)
    objs, chosen_by = window_objects(scene, window_guids)
    wins = window_reference_points(scene, objects=objs)
    if not wins:
        raise ValueError("No windows found: give window_guids, or put windows on glazing (a layer named like 'Glazing', "
                         "almond:env_material, or a window construction).")
    P = np.array([w["point"] for w in wins])
    N = np.array([w["outward_normal"] for w in wins])
    loc = location

    def hours(doy: int) -> np.ndarray:
        return sunlight_hours(scene, P, N, loc.latitude, loc.longitude, loc.time_zone, scene.north_deg, doy, min_altitude_deg)

    h = hours(int(epw.MONTH_START[month - 1] + day))
    rows = [{"window": f"{k + 1}. {w['object']}", "guid": w["guid"], "area_m2": w["area_m2"],
             "sun_hours": round(float(x), 2), "level": sunlight_level(float(x))} for k, (w, x) in enumerate(zip(wins, h))]
    out = {"site": loc.label(), "date": f"{epw.MONTH_NAMES[month - 1]} {day}", "min_altitude_deg": min_altitude_deg,
           "windows_chosen_by": chosen_by, "windows": rows,
           "levels_h": {"minimum": SUN_LEVELS_H[0], "medium": SUN_LEVELS_H[1], "high": SUN_LEVELS_H[2]},
           "headline": "; ".join(f"{r['window']}: {r['sun_hours']} h ({r['level']})" for r in rows[:8]),
           "notes": ["Reference point: the centre of each window, 5 cm inside the pane; sun steps of 5 min, local "
                     "standard time. Indicative, by Almond's implementation of EN 17037 Annex A; levels quoted by value."]}
    if date_range:
        (m0, d0), (m1, d1) = date_range
        a, b = int(epw.MONTH_START[m0 - 1] + d0), int(epw.MONTH_START[m1 - 1] + d1)
        if not 1 <= a <= b <= 365 or b - a > 120:
            raise ValueError("date_range must run forwards within one year and span at most 120 days")
        days = list(range(a, b + 1))
        per = np.array([hours(dd) for dd in days])          # (days, windows)
        best = int(np.argmax(per.max(axis=1)))
        out["range"] = {"from": _date(a - 1), "to": _date(b - 1), "best_day": _date(days[best] - 1),
                        "best_day_hours": {r["window"]: round(float(x), 2) for r, x in zip(rows, per[best])},
                        "per_day": [{"date": _date(dd - 1), **{r["window"]: round(float(x), 2) for r, x in zip(rows, hh)}}
                                    for dd, hh in zip(days, per)]}
        series = [{"label": r["window"][:24], "y": per[:, k], "colour": charts.SERIES[k % len(charts.SERIES)], "width": 1.4}
                  for k, r in enumerate(rows[:8])]
        for lvl, col in zip(SUN_LEVELS_H, (charts.MUTED, charts.AMBER, charts.GREEN)):
            series.append({"label": f"{lvl:g} h level", "y": np.full(len(days), lvl), "colour": col, "width": 1.0, "dash": "5 3"})
        ticks = [(k / max(len(days) - 1, 1), _date(dd - 1)) for k, dd in enumerate(days) if (dd - a) % 7 == 0]
        c = charts.line_chart(series, ticks, f"Direct sunlight on the windows per day ({loc.label()})", "Hours",
                              width=860, height=380, y_range=(0.0, max(5.0, float(per.max()) + 0.5)))
        out["files"] = {"chart": charts.save(c, Path(out_dir) / "sunlight-per-day")}
        out["chart_svg"] = c.svg("Direct sunlight per day")
    return out
