"""Daylight-linked lighting control: how much electric light a zone needs each hour, given the daylight on
a grid of control points at the work plane.

Each control point stands for an equal share of the zone's luminaires, and each share is controlled by
the daylight at its own point (luminaires near the window dim first). The zone's lighting power each
hour is the mean over its points of the power fraction below, times the lighting schedule. The
illuminance comes from the daylight engine (daylight coefficients with the Perez sky of every daylight
hour and the sun traced, with the same dynamic shades as the daylight study), so lighting and daylight
results agree.

Control modes, Almond's own simple models (their parameters are returned with every result):
  continuous  each share dims to top up the daylight to the target. Light output L = 1 - E / target
              (0..1); power = min_power + (1 - min_power) * L while L > 0, off once daylight alone meets
              the target.
  stepped     output in `steps` equal steps (off, 1/n, ..., 1): the smallest step that, with the
              daylight, reaches the target; power follows the step.
  on_off      full power while daylight is below the target, off otherwise.
"""
from __future__ import annotations

import numpy as np

MODES = ("continuous", "stepped", "on_off")
HOURS = 8760
MAX_POINTS = 36                    # control points per zone; the grid spacing grows to stay under this


def power_fraction(E: np.ndarray, target: float, mode: str, steps: int = 3, min_power: float = 0.1) -> np.ndarray:
    """Lighting power as a fraction of full power, for daylight E (lux) at a control point."""
    if mode not in MODES:
        raise ValueError(f"lighting control must be one of {', '.join(MODES)}")
    need = np.clip(1.0 - np.asarray(E, float) / float(target), 0.0, 1.0)
    if mode == "continuous":
        return np.where(need > 0, min_power + (1.0 - min_power) * need, 0.0)
    if mode == "stepped":
        return np.ceil(need * steps - 1e-9) / steps
    return (need > 0).astype(float)


def control_points(floor_grid, max_points: int = MAX_POINTS) -> np.ndarray:
    """At most ``max_points`` evenly spread points of a work-plane grid (N, 3)."""
    pts = np.asarray(floor_grid.points, float)
    if len(pts) <= max_points:
        return pts
    idx = np.linspace(0, len(pts) - 1, max_points).round().astype(int)
    return pts[idx]


def floor_points(vertices: np.ndarray, triangles: np.ndarray, spacing: float = 1.0, height: float = 0.8,
                 edge: float = 0.3) -> np.ndarray:
    """Control points on the work plane over the downward-facing (floor) triangles of a closed zone mesh."""
    from .scene import grid_from_triangles
    v, f = np.asarray(vertices, float), np.asarray(triangles, int)
    a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    down = np.cross(b - a, c - a)[:, 2] < 0
    return control_points(grid_from_triangles(v, f[down], spacing, height, edge, True))


def control_illuminance(scene, points: np.ndarray, weather, quality: str = "draft", dynamic_shading: bool = True,
                        ground_reflectance: float = 0.2, seed: int = 0) -> np.ndarray:
    """(K, 8760) daylight illuminance in lux on the horizontal work plane at each control point; 0 at night."""
    from . import daylight as dl, sky as skymod
    from .scene import SensorGrid
    from .solar import sun_positions_for
    pts = np.asarray(points, float).reshape(-1, 3)
    if not len(pts):
        raise ValueError("no lighting control points: the zone has no floor to place them on")
    n = len(pts)
    grid = SensorGrid(pts, np.tile([0.0, 0.0, 1.0], (n, 1)), np.ones(n), 1.0, np.repeat(pts[:, None, :], 4, axis=1),
                      np.zeros(n, dtype=int))
    from .studies import apply_ground_reflectance
    apply_ground_reflectance(scene, ground_reflectance)
    q = dl.quality(quality)
    groups, gdesc = dl.aperture_groups(scene, "orientation")
    tracer = dl.Tracer(scene, groups)
    coeff = dl.compute_coefficients(tracer, grid, q, seed)
    hours = np.flatnonzero(sun_positions_for(weather)["altitude"] > 0)
    out = np.zeros((n, HOURS), dtype=np.float32)
    if not len(hours):
        return out
    sm = skymod.sky_matrix(weather, mf=q.mf, hours=hours, north_deg=scene.north_deg, ground_reflectance=ground_reflectance)
    S, G = dl.sun_coefficients(tracer, grid, sm.sun_dir)
    closed = {}
    if dynamic_shading:
        for g in gdesc:
            closed[g["group"]] = dl.compute_coefficients(dl.Tracer(scene, groups, closed={g["group"]}), grid, q, seed + g["group"])
    ann = dl.annual_illuminance(coeff, closed, sm, S, G, gdesc, dynamic_shading=dynamic_shading and bool(closed))
    out[:, hours] = np.maximum(ann.illuminance, 0.0)
    return out


def zone_fraction(lux: np.ndarray, target: float, mode: str, steps: int, min_power: float) -> np.ndarray:
    """(8760,) the zone's lighting power fraction: the mean of its control points' fractions."""
    return power_fraction(lux, target, mode, steps, min_power).mean(axis=0)
