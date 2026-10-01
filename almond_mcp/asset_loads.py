"""Gravity loads from placed library assets, applied to a native frame model.

An asset's load is its estimated self weight (dead) plus its in-use contents or occupants
(imposed), from ``GeneratedAssetfiles/structural-loads.json``. A placement is an asset id plus
its world bounding box (meters), read from tagged Rhino objects or from the scene ledger.

Placement onto the frame:
- floor / work-surface / ground assets are carried by the highest level of horizontal
  members at or below their base (within 1.6 m: a lamp on a desk still loads the floor);
- ceiling assets hang from the lowest level at or above their top (within 1.5 m);
- wall-mounted assets, ground-only items (trees, cars, street furniture) and structural
  elements are reported, not applied;
- loads are the nominal product's estimate: a placement whose plan size is far from the
  catalogue product (outside 0.67-1.5x) is flagged, not rescaled (Almond's placement scale
  usually corrects generated-mesh proportions rather than describing a different product);
- the load goes to the nearest member and, when the asset sits between two parallel
  members, is shared by the lever rule (a floor spanning one way between them). Members are
  split at the load points so the point loads are exact.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from . import frame_solver as fs

G = 9.81
FLOOR_PLANES = ("floor", "work_surface", "ground", "")
FLOOR_REACH_M = 1.6        # asset base may sit this far above the members that carry it
CEILING_REACH_M = 1.5      # pendant drop below the members that carry it
PLAN_MARGIN_M = 0.25


class LoadTable:
    def __init__(self, path: Path | str):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.path = str(path)
        self.basis = data.get("basis", "")
        self.assets = data.get("assets", {})
        self.categories = data.get("category_defaults", {})

    def lookup(self, asset_id: str, category: str = "") -> dict | None:
        """Load entry for an asset: its own entry, else its category default (marked)."""
        if asset_id in self.assets:
            return dict(self.assets[asset_id], source="asset")
        if category in self.categories:
            return dict(self.categories[category], source="category_default")
        return None


def placements_from_scene(instances: list[dict]) -> list[dict]:
    """Scene-ledger instances (bounding boxes in mm) -> placements in meters."""
    out = []
    for inst in instances:
        try:
            out.append({"id": inst.get("instance_id") or inst.get("rhino_guid") or "", "asset_id": inst["asset_id"],
                        "min": [inst["min_x"] / 1000, inst["min_y"] / 1000, inst["min_z"] / 1000],
                        "max": [inst["max_x"] / 1000, inst["max_y"] / 1000, inst["max_z"] / 1000],
                        "scale": float(inst.get("scale") or 1.0), "source": "scene"})
        except (KeyError, TypeError):
            continue
    return out


def _horizontal_levels(frame: fs.Frame, tol: float = 0.05) -> dict:
    """Group horizontal elements by elevation: {z: [element index, ...]}."""
    levels: dict[float, list[int]] = {}
    for ei, e in enumerate(frame.elements):
        a, b = frame.nodes[e.n1], frame.nodes[e.n2]
        L = math.dist(a, b)
        if L <= 0 or abs(a[2] - b[2]) > min(tol, 0.02 * L):
            continue
        z = (a[2] + b[2]) / 2
        key = next((k for k in levels if abs(k - z) <= tol), None)
        levels.setdefault(z if key is None else key, []).append(ei)
    return levels


def _plan_distance(frame, ei, p):
    """Clamped plan projection of point p onto element ei: (distance, t, signed offset, unit dir)."""
    a = np.asarray(frame.nodes[frame.elements[ei].n1][:2])
    b = np.asarray(frame.nodes[frame.elements[ei].n2][:2])
    d = b - a
    L2 = float(d @ d)
    t = float(np.clip((np.asarray(p) - a) @ d / L2, 0.0, 1.0))
    q = a + t * d
    u = d / math.sqrt(L2)
    signed = float(u[0] * (p[1] - a[1]) - u[1] * (p[0] - a[0]))
    return float(np.linalg.norm(np.asarray(p) - q)), t, signed, u


def _carriers(frame, members, c):
    """Nearest member, plus the nearest parallel member on the other side when c lies between."""
    ranked = sorted(members, key=lambda ei: _plan_distance(frame, ei, c)[0])
    m1 = ranked[0]
    d1, _, s1, u1 = _plan_distance(frame, m1, c)
    if d1 < 1e-6:
        return [(m1, 1.0)]
    for m2 in ranked[1:]:
        d2, t2, s2, u2 = _plan_distance(frame, m2, c)
        if abs(float(u1 @ u2)) < math.cos(math.radians(10)) or s1 * s2 >= 0 or not (0.0 < t2 < 1.0):
            continue
        return [(m1, d2 / (d1 + d2)), (m2, d1 / (d1 + d2))]
    return [(m1, 1.0)]


def _load_node(frame: fs.Frame, ei: int, c) -> int:
    """Node on element ei at the plan projection of c; splits the element when needed."""
    _, t, _, _ = _plan_distance(frame, ei, c)
    e = frame.elements[ei]
    if t < 0.02:
        return e.n1
    if t > 0.98:
        return e.n2
    return frame.split_element(ei, t)


def apply(frame: fs.Frame, placements: list[dict], table: LoadTable, catalogue: dict) -> dict:
    """Add asset loads to ``frame`` (mutates it). ``catalogue`` maps asset_id -> {category, support_plane, name}.

    Returns a report: per placement the load and the members that carry it, or why it was
    not applied, plus totals and the loaded node indices."""
    levels = _horizontal_levels(frame)
    rows, nodes = [], []
    tot = {"dead_kn": 0.0, "imposed_kn": 0.0}
    for pl in placements:
        meta = catalogue.get(pl["asset_id"], {})
        row = {"id": pl.get("id", ""), "asset_id": pl["asset_id"], "name": meta.get("name", ""),
               "category": meta.get("category", ""), "source": pl.get("source", "")}
        entry = table.lookup(pl["asset_id"], meta.get("category", ""))
        rows.append(row)
        if entry is None:
            row["skipped"] = "no load data for this asset"
            continue
        self_kg = float(entry.get("self_kg", 0))
        use_kg = float(entry.get("use_kg", 0))
        row.update({"self_kg": self_kg, "use_kg": use_kg, "use": entry.get("use", ""),
                    "load_basis": entry["source"]})
        nominal = meta.get("nominal_mm") or {}
        if nominal.get("width") and nominal.get("depth"):
            placed = max(pl["max"][0] - pl["min"][0], pl["max"][1] - pl["min"][1]) * 1000.0
            ratio = placed / max(nominal["width"], nominal["depth"])
            row["size_ratio"] = round(ratio, 2)
            if not 0.67 <= ratio <= 1.5:
                row["warning"] = ("placed size differs from the catalogue product; the load is the "
                                  "nominal product's estimate")
        if entry.get("structural_element"):
            row["skipped"] = "structural element: model it as a member, not a load"
            continue
        if entry.get("ground_only"):
            row["skipped"] = "ground-only item"
            continue
        plane = (meta.get("support_plane") or "floor").lower()
        if plane == "wall":
            row["skipped"] = "wall mounted: carried by the wall"
            continue
        lo, hi = pl["min"], pl["max"]
        c = ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2)
        if plane == "ceiling":
            cands = [z for z in levels if hi[2] - 0.05 <= z <= hi[2] + CEILING_REACH_M]
            z = min(cands) if cands else None
        else:
            cands = [z for z in levels if lo[2] - FLOOR_REACH_M <= z <= lo[2] + 0.05]
            z = max(cands) if cands else None
        if z is None:
            row["skipped"] = "no frame level " + ("above" if plane == "ceiling" else "below") + " this asset"
            continue
        members = levels[z]
        ends = [frame.nodes[getattr(frame.elements[ei], n)] for ei in members for n in ("n1", "n2")]
        xs, ys = [p[0] for p in ends], [p[1] for p in ends]
        if not (min(xs) - PLAN_MARGIN_M <= c[0] <= max(xs) + PLAN_MARGIN_M and
                min(ys) - PLAN_MARGIN_M <= c[1] <= max(ys) + PLAN_MARGIN_M):
            row["skipped"] = "outside the frame's plan at this level"
            continue
        dead, imposed = self_kg * G / 1000.0, use_kg * G / 1000.0
        carried = []
        for ei, share in _carriers(frame, members, c):
            tag = frame.elements[ei].tag
            n = _load_node(frame, ei, c)
            frame.load(n, fz=-(dead + imposed) * share)
            nodes.append(n)
            carried.append({"source_guids": tag or [], "share": round(share, 3)})
            levels = _horizontal_levels(frame)                 # splits renumber elements
            members = next(v for k, v in levels.items() if abs(k - z) <= 0.05)
        row.update({"dead_kn": round(dead, 3), "imposed_kn": round(imposed, 3), "level_m": round(z, 3),
                    "position_m": [round(c[0], 3), round(c[1], 3)], "carried_by": carried})
        tot["dead_kn"] += dead
        tot["imposed_kn"] += imposed
    applied = [r for r in rows if "carried_by" in r]
    return {"placements": rows, "applied": len(applied), "skipped": len(rows) - len(applied),
            "dead_kn": round(tot["dead_kn"], 3), "imposed_kn": round(tot["imposed_kn"], 3),
            "total_kn": round(tot["dead_kn"] + tot["imposed_kn"], 3),
            "basis": table.basis, "loaded_nodes": sorted(set(nodes))}
