"""Solar radiation on surfaces and direct-sun hours.

Incident irradiation (kWh/m2) on each sensor over a period = diffuse sky and ground (daylight
coefficients against the cumulative Perez solar sky, Reinhart MF 2 by default) + the sun traced
exactly hour by hour. Interreflections off the context are off by default (``bounces=0``, the usual
convention for radiation maps); turn them on to count light reflected by neighbours and the ground.

Direct-sun hours count the hours in which a sensor sees the sun, through clear glazing, while the
direct-normal irradiance is at least 120 W/m2 (the WMO definition of bright sunshine).
"""
from __future__ import annotations

import numpy as np

from . import sky as skymod
from .daylight import EPS, Quality, Tracer, compute_coefficients
from .scene import SensorGrid

WMO_SUNSHINE = 120.0   # W/m2


def hour_mask(weather, months=None, hours=None) -> np.ndarray:
    """Hours of the year to include: ``months`` like [6, 7, 8]; ``hours`` like [8, 18] (start, end,
    local standard time, interval starts) - both inclusive of start, exclusive of end."""
    mask = np.ones(len(weather.month), dtype=bool)
    if months:
        ms = [int(m) for m in months]
        if any(m < 1 or m > 12 for m in ms):
            raise ValueError("months must be 1..12")
        mask &= np.isin(weather.month, ms)
    if hours:
        if len(hours) != 2:
            raise ValueError("hours must be [start, end]")
        h0, h1 = float(hours[0]), float(hours[1])
        hod = weather.hour_of_day
        mask &= (hod >= h0) & (hod < h1) if h0 <= h1 else ((hod >= h0) | (hod < h1))
    return mask


def sun_exposure(tracer: Tracer, grid: SensorGrid, sun_dirs: np.ndarray, dni: np.ndarray, month: np.ndarray,
                 max_rays: int = 2_000_000) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(annual Wh/m2 (N,), monthly Wh/m2 (12, N), sunshine hours (N,)) from the exact sun."""
    N = grid.n
    total = np.zeros(N)
    monthly = np.zeros((12, N))
    hours = np.zeros(N)
    up = (dni > 0) & (sun_dirs[:, 2] > 0)
    idx = np.flatnonzero(up)
    step = max(1, max_rays // max(1, N))
    for a in range(0, len(idx), step):
        h = idx[a:a + step]
        cos = sun_dirs[h] @ grid.normals.T                       # (h, N)
        hi, si = np.nonzero(cos > 1e-6)
        if not hi.size:
            continue
        T, _ = tracer.transmit(grid.points[si] + grid.normals[si] * EPS, sun_dirs[h][hi])
        val = cos[hi, si] * T * dni[h][hi]
        total += np.bincount(si, weights=val, minlength=N)
        np.add.at(monthly, (month[h][hi] - 1, si), val)
        bright = (T > 0) & (dni[h][hi] >= WMO_SUNSHINE)
        hours += np.bincount(si[bright], minlength=N)
    return total, monthly, hours


def irradiation(scene, grid: SensorGrid, weather, q: Quality, mask: np.ndarray | None = None,
                ground_reflectance: float = 0.2, north_deg: float = 0.0, seed: int = 0) -> dict:
    """Incident solar irradiation on every sensor over the hours in ``mask`` (default: the year)."""
    mask = np.ones(len(weather.month), dtype=bool) if mask is None else mask
    tracer = Tracer(scene)
    coeff = compute_coefficients(tracer, grid, q, seed)
    hrs = np.flatnonzero(mask)
    sm = skymod.sky_matrix(weather, mf=q.mf, kind="solar", hours=hrs, north_deg=north_deg,
                           ground_reflectance=ground_reflectance)
    month = weather.month[hrs]
    tot = coeff.total.sum(axis=0).astype(np.float64)                # (N, P)
    diffuse = tot @ sm.sky.sum(axis=0)
    diff_monthly = np.stack([tot @ sm.sky[month == m].sum(axis=0) if (month == m).any() else np.zeros(grid.n)
                             for m in range(1, 13)])
    sun_total, sun_monthly, sun_hours = sun_exposure(tracer, grid, sm.sun_dir, sm.sun_normal, month)
    if q.bounces > 0:   # the sun's reflected part, through its patch
        refl = coeff.I.sum(axis=0).astype(np.float64) @ sm.sun_patch_sky().sum(axis=0)
    else:
        refl = np.zeros(grid.n)
    total = (diffuse + sun_total + refl) / 1000.0
    return {"kwh_m2": total, "monthly_kwh_m2": (diff_monthly + sun_monthly) / 1000.0,
            "direct_kwh_m2": sun_total / 1000.0, "diffuse_kwh_m2": (diffuse + refl) / 1000.0,
            "sun_hours": sun_hours, "hours": int(mask.sum()), "coefficients": coeff.info}
