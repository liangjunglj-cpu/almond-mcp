"""Code packs: regional envelope requirements, reference values and methods.

Every pack declares its relation to its source:
  bundled        values shipped in data/codes/, under a licence that allows it (recorded in sources.json)
  method         Almond's own implementation of a published method; the source's tables are not reproduced
  user-supplied  values the user loads from their own licensed copy at run time (never bundled)

Packs: uk_adl_2021 (OGL v3), de_banz_2020 (public domain, Section 5 UrhG), eu_hotmaps (CC BY 4.0) and
sg_bca (method: ETTV / RETV / RTTV from the BCA Code on Envelope Thermal Performance, with solar correction
factors derived from the site weather file and shading from the model). Results are indicative design
checks, not certification: no pack here performs a jurisdiction's whole-building compliance calculation.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

import numpy as np

from . import constructions

CODES = constructions.DATA / "codes"
ORIENTATIONS = {"N": 0.0, "NE": 45.0, "E": 90.0, "SE": 135.0, "S": 180.0, "SW": 225.0, "W": 270.0, "NW": 315.0}
SC_REFERENCE_G = 0.87          # g of 3 mm clear glass: SC = g / 0.87


@lru_cache(maxsize=None)
def pack(name: str) -> dict:
    path = CODES / f"{name}.json"
    if not path.is_file():
        raise ValueError(f"Unknown code pack '{name}'. Available: {', '.join(p['pack'] for p in packs())}")
    return json.loads(path.read_text(encoding="utf-8"))


def packs() -> list[dict]:
    src = constructions.sources()
    out = []
    for path in sorted(CODES.glob("*.json")):
        p = json.loads(path.read_text(encoding="utf-8"))
        s = src.get(p["source"], {})
        out.append({"pack": p["pack"], "relation": p["relation"], "description": p["description"],
                    "source": s.get("title", p["source"]), "licence": s.get("licence"), "attribution": s.get("attribution")})
    return out


def orientation_of(normal) -> str:
    """Nearest of the eight principal orientations for a wall normal (model axes, +Y = north)."""
    az = (math.degrees(math.atan2(normal[0], normal[1])) + 360.0) % 360.0
    return min(ORIENTATIONS, key=lambda k: min(abs(az - ORIENTATIONS[k]), 360 - abs(az - ORIENTATIONS[k])))


def plane_irradiance(weather, normal, hours=None, ground_reflectance: float = 0.2) -> np.ndarray:
    """Hourly irradiance W/m2 on an unobstructed plane (Perez sky, direct sun and ground reflection)."""
    from . import sky as skymod
    sm = skymod.sky_matrix(weather, 1, "solar", hours=hours, ground_reflectance=ground_reflectance)
    n = np.asarray(normal, dtype=float)
    n = n / np.linalg.norm(n)
    p = sm.patches
    d = p.direction[:p.n_sky]
    w = np.maximum(d @ n, 0.0) * p.solid_angle[:p.n_sky]
    diffuse = sm.sky[:, :p.n_sky] @ w
    ground = sm.sky[:, p.n_sky] * math.pi * (1 - n[2]) / 2.0
    direct = sm.sun_normal * np.maximum(sm.sun_dir @ n, 0.0)
    return diffuse + ground + direct


def solar_correction_factors(weather, north_deg: float = 0.0) -> dict:
    """CF per orientation: mean daytime irradiance on that vertical orientation / mean over all eight.
    Re-derived from the weather file (the BCA tables are not used)."""
    from .solar import sun_positions_for
    day = np.flatnonzero(sun_positions_for(weather)["altitude"] > 0)
    means = {}
    for k, az in ORIENTATIONS.items():
        a = math.radians(az - north_deg)
        means[k] = float(plane_irradiance(weather, (math.sin(a), math.cos(a), 0.0), hours=day).mean())
    ref = sum(means.values()) / len(means)
    roof = float(plane_irradiance(weather, (0.0, 0.0, 1.0), hours=day).mean())
    return {"walls": {k: round(v / ref, 3) for k, v in means.items()}, "roof": round(roof / ref, 3),
            "mean_daytime_w_m2": {k: round(v, 1) for k, v in means.items()} | {"roof": round(roof, 1)},
            "method": pack("sg_bca")["cf_method"]}


def _user_cf(user_tables: dict | None, key: str, orient: str) -> float | None:
    if not user_tables:
        return None
    v = user_tables.get(key, {}).get(orient) if isinstance(user_tables.get(key), dict) else None
    return float(v) if v is not None else None


def envelope_transfer(surfaces: list[dict], weather=None, residential: bool = False, north_deg: float = 0.0,
                      user_tables: dict | None = None) -> dict:
    """ETTV (or RETV) per facade orientation and overall, and RTTV for roofs with skylights.

    ``surfaces``: [{"kind": wall_external|window|roof|skylight, "area": m2, "normal": (x,y,z),
    "u_value": W/m2K, "g_value": (glazing), "shading_factor": SC_external 0..1 (default 1)}]."""
    p = pack("sg_bca")
    f = p["formulas"]["RETV" if residential else "ETTV"]
    c = f["coefficients"]
    cf_info = solar_correction_factors(weather, north_deg) if weather is not None else None
    if cf_info is None and not user_tables:
        raise ValueError("ETTV/RETV need a weather file (to derive the solar correction factors) or user_tables")
    facades: dict[str, dict] = {}
    roof = {"opaque": 0.0, "ua_opaque": 0.0, "sky": 0.0, "ua_sky": 0.0, "sa_sky": 0.0}
    for s in surfaces:
        kind, area = s["kind"], float(s["area"])
        if area <= 0:
            continue
        if kind in ("roof", "skylight"):
            if kind == "roof":
                roof["opaque"] += area
                roof["ua_opaque"] += area * s["u_value"]
            else:
                sc = float(s.get("g_value", 0.0)) / SC_REFERENCE_G * float(s.get("shading_factor", 1.0))
                roof["sky"] += area
                roof["ua_sky"] += area * s["u_value"]
                roof["sa_sky"] += area * sc
            continue
        if kind not in ("wall_external", "window"):
            continue
        o = orientation_of(s["normal"])
        fa = facades.setdefault(o, {"wall": 0.0, "ua_wall": 0.0, "fen": 0.0, "ua_fen": 0.0, "sa_fen": 0.0})
        if kind == "window":
            sc = float(s.get("g_value", 0.0)) / SC_REFERENCE_G * float(s.get("shading_factor", 1.0))
            fa["fen"] += area
            fa["ua_fen"] += area * s["u_value"]
            fa["sa_fen"] += area * sc
        else:
            fa["wall"] += area
            fa["ua_wall"] += area * s["u_value"]
    rows, total_q, total_a = [], 0.0, 0.0
    key = "RETV_walls" if residential else "ETTV_walls"
    for o, fa in sorted(facades.items(), key=lambda kv: ORIENTATIONS[kv[0]]):
        ao = fa["wall"] + fa["fen"]
        if ao <= 0:
            continue
        cf = _user_cf(user_tables, key, o)
        cf_source = "user table"
        if cf is None:
            cf = cf_info["walls"][o]
            cf_source = "derived from weather file"
        q = (c["opaque"] * fa["ua_wall"] + c["fenestration_conduction"] * fa["ua_fen"] + c["solar"] * cf * fa["sa_fen"]) / ao
        rows.append({"orientation": o, "gross_area_m2": round(ao, 2), "wwr": round(fa["fen"] / ao, 3),
                     "u_wall": round(fa["ua_wall"] / fa["wall"], 3) if fa["wall"] else None,
                     "u_fen": round(fa["ua_fen"] / fa["fen"], 3) if fa["fen"] else None,
                     "sc": round(fa["sa_fen"] / fa["fen"], 3) if fa["fen"] else None,
                     "cf": cf, "cf_source": cf_source, "value_w_m2": round(q, 2)})
        total_q += q * ao
        total_a += ao
    name = "RETV" if residential else "ETTV"
    out = {"index": name, "expression": f["expression"], "limit_w_m2": f["max_w_m2"], "facades": rows,
           "overall_w_m2": round(total_q / total_a, 2) if total_a else None,
           "cf": cf_info, "source": "bca-envelope-code",
           "note": "Indicative: formulas from the BCA Code on Envelope Thermal Performance; CF derived by Almond from "
                   "the weather file and SC from the glazing g-value and modelled shading. Not a BCA Green Mark assessment."}
    if out["overall_w_m2"] is not None:
        out["passes"] = out["overall_w_m2"] <= f["max_w_m2"]
    if roof["sky"] > 0:
        r = p["formulas"]["RTTV"]
        rc = r["coefficients"]
        cf = _user_cf(user_tables, "RTTV", "roof") or (cf_info["roof"] if cf_info else 1.0)
        a = roof["opaque"] + roof["sky"]
        rttv = (rc["opaque"] * roof["ua_opaque"] + rc["fenestration_conduction"] * roof["ua_sky"] + rc["solar"] * cf * roof["sa_sky"]) / a
        out["rttv"] = {"value_w_m2": round(rttv, 2), "limit_w_m2": r["max_w_m2"], "skr": round(roof["sky"] / a, 3),
                       "cf": cf, "passes": rttv <= r["max_w_m2"], "expression": r["expression"]}
    return out


UK_ELEMENT = {"wall_external": "wall_external", "window": "window", "door": "door", "floor_ground": "floor",
              "floor_exposed": "floor", "roof": "roof"}


def uk_limits(by_kind: dict[str, tuple[float, float]], dwelling: bool = True, flat_roof: bool = True) -> dict:
    """Area-weighted U per element against Approved Document L limiting values.
    ``by_kind``: {kind: (area m2, area-weighted U)}."""
    p = pack("uk_adl_2021")
    lim = p["limits"]["dwellings" if dwelling else "non_dwellings"]
    rows = []
    for kind, (area, u) in by_kind.items():
        el = UK_ELEMENT.get(kind)
        if el is None or area <= 0:
            continue
        key = el if el in lim else ("roof_flat" if flat_roof else "roof_pitched") if el == "roof" else el
        if key not in lim:
            continue
        rows.append({"element": kind, "area_m2": round(area, 2), "u_value": round(u, 3), "limit": lim[key],
                     "passes": u <= lim[key] + 1e-9})
    notional = p["notional_dwelling"] if dwelling else None
    return {"pack": "uk_adl_2021", "table": lim["table"], "elements": rows, "passes": all(r["passes"] for r in rows),
            "notional_dwelling": notional, "note": p["description"]}


def de_reference(age_band: str) -> dict:
    p = pack("de_banz_2020")
    if age_band not in p["age_bands"]:
        raise ValueError(f"age_band must be one of {', '.join(p['age_bands'])}")
    w_band = next((b for b in p["window_age_bands"] if _band_contains(b, age_band)), p["window_age_bands"][-1])
    return {"pack": "de_banz_2020", "age_band": age_band,
            "opaque": {k: {"name": v["name"], "kind": v["kind"], "u": v["u_values"][age_band]} for k, v in p["opaque"].items()
                       if v["u_values"][age_band] is not None},
            "windows": {k: {"name": v["name"], "u_w": v["u_w"][w_band], "u_g": v["u_g"][w_band]} for k, v in p["windows"].items()
                        if v["u_w"][w_band] is not None},
            "window_age_band": w_band, "note": p["description"]}


def _band_years(b: str) -> tuple[int, int]:
    if b.startswith("<="):
        return 0, int(b[2:])
    if b.startswith(">="):
        return int(b[2:]), 9999
    lo, hi = b.split("-")
    return int(lo), int(hi)


def _band_contains(window_band: str, opaque_band: str) -> bool:
    lo, hi = _band_years(opaque_band)
    wlo, whi = _band_years(window_band)
    return wlo <= lo and hi <= whi or (wlo <= hi <= whi)


def eu_reference(country: str, sector: str = "residential") -> dict:
    p = pack("eu_hotmaps")
    v = p["values"].get(country.lower())
    if not v:
        raise ValueError(f"No Hotmaps values for '{country}'. Countries: {', '.join(sorted(p['values']))}")
    if sector not in v:
        raise ValueError(f"sector must be one of {', '.join(v)}")
    return {"pack": "eu_hotmaps", "country": country.lower(), "sector": sector, "u_values_by_age": v[sector],
            "note": p["description"]}


def check_envelope(surfaces: list[dict], pack_name: str, weather=None, **options) -> dict:
    """Run a pack's check on a list of envelope surfaces (see envelope_transfer for the fields)."""
    src = constructions.sources()
    if pack_name == "sg_bca":
        res = envelope_transfer(surfaces, weather, residential=bool(options.get("residential", False)),
                                north_deg=float(options.get("north_deg", 0.0)), user_tables=options.get("user_tables"))
    elif pack_name == "uk_adl_2021":
        acc: dict[str, list[float]] = {}
        for s in surfaces:
            a = acc.setdefault(s["kind"], [0.0, 0.0])
            a[0] += float(s["area"])
            a[1] += float(s["area"]) * float(s["u_value"])
        res = uk_limits({k: (a, ua / a) for k, (a, ua) in acc.items() if a > 0},
                        dwelling=bool(options.get("dwelling", True)), flat_roof=bool(options.get("flat_roof", True)))
    elif pack_name == "de_banz_2020":
        res = de_reference(options.get("age_band", ">=2002"))
    elif pack_name == "eu_hotmaps":
        res = eu_reference(options.get("country", "de"), options.get("sector", "residential"))
    else:
        raise ValueError(f"Unknown code pack '{pack_name}'")
    p = pack(pack_name)
    s = src.get(p["source"], {})
    res["provenance"] = {"relation": p["relation"], "source": s.get("title"), "licence": s.get("licence"),
                         "attribution": s.get("attribution")}
    return res
