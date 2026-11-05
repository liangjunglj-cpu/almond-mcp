"""Rooms: user-defined thermal zones, enclosed or open.

A room is whatever the user marks with ``almond:room`` user text in Rhino:
  * a closed volume (one polysurface / extrusion / closed mesh),
  * a set of surfaces (a roof and two walls of a pavilion, for example) - the room is the prism over the
    convex hull of their plan, from their lowest to their highest point,
  * a closed planar curve with ``almond:room_height`` - the room is the curve extruded upwards.

Rooms do not have to be enclosed. Every room gets an **enclosure check**: its boundary is sampled on a
~0.5 m mesh and each sample probes for a building element within ``tolerance`` (0.35 m) of the boundary,
inside or outside, so walls drawn as solids around a room volume are found wherever their faces are.
Uncovered boundary is an opening. The share of open area on the sides and top picks the method:

  enclosed   (< 5 % open)    ISO 13790 5R1C (thermal.py), unchanged; small gaps are reported, not modelled
  semi_open  (5-30 % open)   5R1C plus air change through the openings, from wind and stack
                             (single-sided: de Gids and Phaff 1982; cross ventilation: orifice flow
                             Q = C_d A_eff v sqrt(dCp) between openings on opposite sides)
  open       (>= 30 % open)  semi-outdoor comfort, no heating or cooling loads: air at outdoor dry-bulb;
                             mean radiant temperature from the long-wave exchange with sky, roof
                             underside and ground plus short-wave sun on the body (the SolarCal method,
                             Arens et al. 2015, with a cylindrical body for the projected area); SET*

and every result says which one was used and warns when a room is not enclosed. When nothing is modelled
around a closed room volume, its own faces are taken as the envelope (the classic zone workflow).

Construction of each boundary face comes from the element that covers it (its ``almond:construction``),
else from the room's construction set. Thermal mass comes from the constructions' areal heat capacity
(ISO 13790 12.3.1.2: C_m = sum kappa A, A_m = C_m^2 / sum kappa^2 A). Rooms that share a face exchange
heat through it (H = U A), coupled with the previous pass's air temperatures (three passes).
Room-use gains and schedules are Almond's own documented assumptions (ROOM_USES).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from . import comfort, constructions as asm, thermal
from .epw import HOURS

TOLERANCE = 0.35            # m: an element this close to a room boundary encloses it
CELL = 0.5                  # m: enclosure sampling
ENCLOSED_MAX = 0.05
SEMI_OPEN_MAX = 0.30
KAPPA_DEFAULT = 50_000.0    # J/m2K for opaque surfaces without a construction (a medium-weight finish)
SETPOINT_RANGE = (5.0, 40.0)    # degC accepted for room set-points
MAX_ROOM_HEIGHT_M = 100.0       # a taller 'room' is a unit mistake (heights are metres)
MAX_ROOM_PLAN_M = 300.0         # a wider one is usually two rooms sharing a name
INTERZONE_U_DEFAULT = 1.5   # W/m2K for a shared face neither room has a construction for (a light partition)
WIND_LOCAL = 0.5            # local wind / 10 m EPW wind (suburban, sheltered openings)

# Room uses: Almond assumptions for design-stage studies (people, equipment, lighting W/m2 at full use;
# set-points degC; fresh air l/s per m2). Check against the project brief.
ROOM_USES = {
    "living": {"schedule": "residential", "occupancy_w_m2": 4.0, "equipment_w_m2": 3.0, "lighting_w_m2": 3.0,
               "heating_setpoint": 20.0, "cooling_setpoint": 26.0, "ventilation_l_s_m2": 0.42},
    "bedroom": {"schedule": "bedroom", "occupancy_w_m2": 6.0, "equipment_w_m2": 1.0, "lighting_w_m2": 2.0,
                "heating_setpoint": 18.0, "cooling_setpoint": 26.0, "ventilation_l_s_m2": 0.42},
    "kitchen": {"schedule": "residential", "occupancy_w_m2": 3.0, "equipment_w_m2": 15.0, "lighting_w_m2": 4.0,
                "heating_setpoint": 20.0, "cooling_setpoint": 26.0, "ventilation_l_s_m2": 1.0},
    "bath": {"schedule": "residential", "occupancy_w_m2": 1.0, "equipment_w_m2": 2.0, "lighting_w_m2": 4.0,
             "heating_setpoint": 22.0, "cooling_setpoint": None, "ventilation_l_s_m2": 1.0},
    "circulation": {"schedule": "residential", "occupancy_w_m2": 0.5, "equipment_w_m2": 0.0, "lighting_w_m2": 2.0,
                    "heating_setpoint": 18.0, "cooling_setpoint": None, "ventilation_l_s_m2": 0.3},
    "office": {"schedule": "office", "occupancy_w_m2": 7.5, "equipment_w_m2": 10.0, "lighting_w_m2": 8.0,
               "heating_setpoint": 20.0, "cooling_setpoint": 26.0, "ventilation_l_s_m2": 1.4},
    "classroom": {"schedule": "school", "occupancy_w_m2": 20.0, "equipment_w_m2": 5.0, "lighting_w_m2": 8.0,
                  "heating_setpoint": 20.0, "cooling_setpoint": 26.0, "ventilation_l_s_m2": 4.0},
    "outdoor": {"schedule": "always", "occupancy_w_m2": 0.0, "equipment_w_m2": 0.0, "lighting_w_m2": 0.0,
                "heating_setpoint": None, "cooling_setpoint": None, "ventilation_l_s_m2": 0.0},
}
SURFACE_KIND_TO_ASSEMBLY = {"wall": "wall_external", "roof": "roof", "ground_floor": "floor_ground",
                            "exposed_floor": "floor_exposed", "window": "window"}


@dataclass
class Room:
    name: str
    use: str
    vertices: np.ndarray                 # metres
    triangles: np.ndarray
    guids: list[str] = field(default_factory=list)
    source: str = "volume"               # volume | surfaces | boundary
    construction_set: str = ""
    setpoints: dict = field(default_factory=dict)
    closed_input: bool = True

    @property
    def floor_z(self) -> float:
        return float(self.vertices[:, 2].min())

    @property
    def height(self) -> float:
        return float(np.ptp(self.vertices[:, 2]))


# ── geometry ─────────────────────────────────────────────────────────────────

def _polygon_area(p: np.ndarray) -> float:
    x, y = p[:, 0], p[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def _ear_clip(poly: np.ndarray) -> list[tuple[int, int, int]]:
    """Triangulate a simple polygon (counter-clockwise, (n, 2))."""
    idx = list(range(len(poly)))
    tris = []

    def inside(p, a, b, c):
        d1 = (p[0] - b[0]) * (a[1] - b[1]) - (a[0] - b[0]) * (p[1] - b[1])
        d2 = (p[0] - c[0]) * (b[1] - c[1]) - (b[0] - c[0]) * (p[1] - c[1])
        d3 = (p[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (p[1] - a[1])
        return (d1 >= 0 and d2 >= 0 and d3 >= 0) or (d1 <= 0 and d2 <= 0 and d3 <= 0)

    guard = 0
    while len(idx) > 3 and guard < 10000:
        guard += 1
        for k in range(len(idx)):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            a, b, c = poly[i0], poly[i1], poly[i2]
            if (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]) <= 1e-12:
                continue                                   # reflex or degenerate
            if any(inside(poly[j], a, b, c) for j in idx if j not in (i0, i1, i2)):
                continue
            tris.append((i0, i1, i2))
            idx.pop(k)
            break
        else:
            break
    if len(idx) == 3:
        tris.append(tuple(idx))
    return tris


def prism(boundary_xy: np.ndarray, z0: float, height: float) -> tuple[np.ndarray, np.ndarray]:
    """Closed triangle mesh of a vertical prism over a plan polygon (outward normals)."""
    p = np.asarray(boundary_xy, dtype=float)[:, :2]
    if len(p) > 3 and np.allclose(p[0], p[-1]):
        p = p[:-1]
    if len(p) < 3 or abs(_polygon_area(p)) < 1e-6:
        raise ValueError("A room boundary needs at least three points enclosing an area")
    if _polygon_area(p) < 0:
        p = p[::-1]
    n = len(p)
    v = np.vstack([np.column_stack([p, np.full(n, z0)]), np.column_stack([p, np.full(n, z0 + height)])])
    tri = _ear_clip(p)
    faces = [(c, b, a) for a, b, c in tri] + [(a + n, b + n, c + n) for a, b, c in tri]
    for i in range(n):
        j = (i + 1) % n
        faces += [(i, j, j + n), (i, j + n, i + n)]
    return v, np.asarray(faces, dtype=np.int64)


def _convex_hull(pts: np.ndarray) -> np.ndarray:
    pts = np.unique(np.round(pts[:, :2], 6), axis=0)
    if len(pts) < 3:
        return pts
    pts = pts[np.lexsort((pts[:, 1], pts[:, 0]))]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for q in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], q) <= 0:
            lower.pop()
        lower.append(q)
    for q in pts[::-1]:
        while len(upper) >= 2 and cross(upper[-2], upper[-1], q) <= 0:
            upper.pop()
        upper.append(q)
    return np.array(lower[:-1] + upper[:-1])


def _closed(v: np.ndarray, f: np.ndarray) -> bool:
    key = np.round(v / 0.001).astype(np.int64)
    _, vid = np.unique(key, axis=0, return_inverse=True)
    vid = vid.reshape(-1)[f]
    edges = np.sort(np.concatenate([vid[:, [0, 1]], vid[:, [1, 2]], vid[:, [2, 0]]]), axis=1)
    _, cnt = np.unique(edges, axis=0, return_counts=True)
    return bool(len(cnt) and (cnt == 2).all())


def parse_setpoints(heat, cool, where: str = "") -> dict:
    """Room set-points from tag or tool values ("", None = use default; "off"/"none" = no heating or cooling).
    Raises ValueError for text that is not a number, values outside 5-40 degC, or heating >= cooling."""
    out: dict[str, float | None] = {}
    for value, key in ((heat, "heating_setpoint"), (cool, "cooling_setpoint")):
        if value is None or str(value).strip() == "":
            continue
        if str(value).strip().lower() in ("none", "off"):
            out[key] = None
            continue
        try:
            t = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{where}{key.replace('_', ' ')} '{value}' is not a temperature in degC (or 'off')") from None
        if not math.isfinite(t) or not SETPOINT_RANGE[0] <= t <= SETPOINT_RANGE[1]:
            raise ValueError(f"{where}{key.replace('_', ' ')} {value} degC is outside {SETPOINT_RANGE[0]:g}-{SETPOINT_RANGE[1]:g} degC")
        out[key] = t
    h, c = out.get("heating_setpoint"), out.get("cooling_setpoint")
    if h is not None and c is not None and h >= c:
        raise ValueError(f"{where}heating set-point {h:g} degC must be below the cooling set-point {c:g} degC")
    return out


def check_height(h: float, where: str = "") -> float:
    if not math.isfinite(h) or h <= 0:
        raise ValueError(f"{where}room height {h:g} m must be positive (almond:room_height, metres)")
    if h > MAX_ROOM_HEIGHT_M:
        raise ValueError(f"{where}room height {h:g} m is over {MAX_ROOM_HEIGHT_M:g} m - heights are in metres, "
                         "not model units (3 m, not 3000)")
    return h


def rooms_from_export(data: dict, problems: list[str] | None = None) -> list[Room]:
    """Rooms from the export JSON (objects with a ``room`` field, see rhino.export_script).

    With ``problems`` (a list), a room that cannot be built is skipped and the reason appended, so one bad
    room does not stop the others; without it the first problem raises ValueError."""
    scale = float(data.get("units_to_m", 1.0))
    groups: dict[str, list[dict]] = {}
    for o in data.get("objects", []):
        name = str(o.get("room") or "").strip()
        if name:
            groups.setdefault(name, []).append(o)
    rooms = []
    for name, objs in groups.items():
        try:
            rooms.append(_room(name, objs, scale))
        except ValueError as exc:
            if problems is None:
                raise
            problems.append(f"Room {name} was skipped: {exc}")
    # tagged objects the export could not read (open curves, points, ...) carry no geometry
    tagged = {str(g) for g in data.get("skipped_rooms", [])}
    if tagged and problems is not None:
        problems.append(f"{len(tagged)} object(s) tagged as rooms have no usable geometry (open curves, points or "
                        "unsupported types) and were left out: give a room a closed volume, its bounding surfaces, "
                        "or a closed planar curve with a height")
    return rooms


def _room(name: str, objs: list[dict], scale: float) -> Room:
    metas = [o for o in objs if o.get("room_use") or o.get("room_set")]
    meta = metas[0] if metas else objs[0]
    use = str(meta.get("room_use") or "living").lower()
    if use not in ROOM_USES:
        raise ValueError(f"use '{use}' is not one of {', '.join(ROOM_USES)}")
    if len({str(o.get("room_use") or "").lower() for o in metas}) > 1:
        raise ValueError(f"its {len(objs)} objects disagree on the room use - two rooms with the same name? "
                         "Rename one (rooms are grouped by name)")
    setpoints = parse_setpoints(meta.get("room_heat_c"), meta.get("room_cool_c"))
    guids = list(dict.fromkeys(str(o.get("guid", "")) for o in objs))
    boundary = [o for o in objs if o.get("boundary")]
    if boundary:
        b = boundary[0]
        pts = np.asarray(b["boundary"], dtype=float).reshape(-1, 3) * scale
        if b.get("room_height") in (None, ""):
            raise ValueError("a boundary curve needs almond:room_height (metres)")
        h = float(b["room_height"]) * scale if b.get("room_height_units") == "model" else float(b["room_height"])
        v, f = prism(pts, float(pts[:, 2].min()), check_height(h))
        return Room(name, use, v, f, guids, "boundary", str(meta.get("room_set") or ""), setpoints, True)
    verts, tris, n = [], [], 0
    for o in objs:
        vv = np.asarray(o.get("vertices", []), dtype=float).reshape(-1, 3) * scale
        ff = np.asarray(o.get("faces", []), dtype=np.int64).reshape(-1, 3)
        if not len(ff):
            continue
        verts.append(vv)
        tris.append(ff + n)
        n += len(vv)
    if not verts:
        raise ValueError("no geometry exported")
    v, f = np.vstack(verts), np.vstack(tris)
    extent = np.ptp(v, axis=0)
    check_height(float(extent[2]))
    if max(extent[:2]) > MAX_ROOM_PLAN_M:
        raise ValueError(f"it spans {max(extent[:2]):.0f} m in plan - one room per name (rooms are grouped by name)")
    if len(objs) == 1 and _closed(v, f):
        return Room(name, use, v, f, guids, "volume", str(meta.get("room_set") or ""), setpoints, True)
    hull = _convex_hull(v)
    z0, z1 = float(v[:, 2].min()), float(v[:, 2].max())
    if z1 - z0 < 1.5:
        raise ValueError(f"its surfaces span only {z1 - z0:.2f} m in height - include the roof "
                         "or draw a boundary curve with almond:room_height")
    pv, pf = prism(hull, z0, z1 - z0)
    return Room(name, use, pv, pf, guids, "surfaces", str(meta.get("room_set") or ""), setpoints, False)


def _subdivide(v: np.ndarray, f: np.ndarray, cell: float = CELL) -> tuple[np.ndarray, np.ndarray]:
    """Triangles (k, 3, 3) of the mesh split until every edge is shorter than ``cell`` * 1.5."""
    tris = np.stack([v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]], axis=1)
    for _ in range(12):
        e = np.max(np.linalg.norm(tris - np.roll(tris, -1, axis=1), axis=2), axis=1)
        big = e > cell * 1.5
        if not big.any():
            break
        t = tris[big]
        a, b, c = t[:, 0], t[:, 1], t[:, 2]
        ab, bc, ca = (a + b) / 2, (b + c) / 2, (c + a) / 2
        new = np.concatenate([np.stack([a, ab, ca], 1), np.stack([ab, b, bc], 1), np.stack([ca, bc, c], 1),
                              np.stack([ab, bc, ca], 1)])
        tris = np.concatenate([tris[~big], new])
    return tris


# ── enclosure ────────────────────────────────────────────────────────────────

@dataclass
class Enclosure:
    state: str                           # enclosed | semi_open | open
    open_fraction: float                 # of side + top area
    open_area_m2: float
    boundary_area_m2: float
    self_enclosed: bool                  # nothing modelled around it: its own faces are the envelope
    tri_points: np.ndarray               # (k, 3, 3) sub-triangles of the room boundary
    tri_open: np.ndarray                 # (k,) bool
    tri_construction: np.ndarray         # (k,) object (assembly id or "")
    tri_element: np.ndarray              # (k,) object (layer / name of the covering element)
    openings: list[dict]                 # [{"orientation", "normal", "area_m2", "z_min", "z_max"}] to outside
    tri_internal: np.ndarray | None = None   # (k,) bool: open towards other parts of the building
    internal_openings: list[dict] = field(default_factory=list)
    warning: str = ""
    tri_glazing: np.ndarray | None = None    # (k,) bool: covered by a glazing element
    tri_ground_only: np.ndarray | None = None   # (k,) bool: floor on the ground with no element modelled

    def to_json(self) -> dict:
        return {"state": self.state, "open_fraction": round(self.open_fraction, 3), "open_area_m2": round(self.open_area_m2, 2),
                "boundary_area_m2": round(self.boundary_area_m2, 2), "self_enclosed": self.self_enclosed,
                "openings": self.openings, "internal_openings": self.internal_openings, "warning": self.warning,
                "thresholds": {"enclosed_below": ENCLOSED_MAX, "open_from": SEMI_OPEN_MAX, "tolerance_m": TOLERANCE}}


def enclosure(room: Room, scene, exclude_objects: set[int] | None = None, ground_z: float | None = None,
              tolerance: float = TOLERANCE, semi_open_max: float = SEMI_OPEN_MAX,
              neighbours: list["Room"] | None = None) -> Enclosure:
    """Which parts of a room's boundary are covered by building elements in ``scene`` or by
    neighbouring rooms (a face shared with another room is an internal boundary, not an opening)."""
    from .raytrace import BVH
    from .codes import orientation_of
    tris = _subdivide(room.vertices, room.triangles)
    a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
    cr = np.cross(b - a, c - a)
    area = 0.5 * np.linalg.norm(cr, axis=1)
    n = cr / np.maximum(2 * area[:, None], 1e-12)
    # outward normals: the room's signed volume must be positive
    if float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum()) < 0:
        n = -n
    cen = (a + b + c) / 3.0
    ex = exclude_objects or set()
    keep = np.flatnonzero(~np.isin(scene.tri_object, list(ex))) if ex else np.arange(len(scene.triangles))
    v = scene.vertices
    t = scene.triangles[keep]
    covered = np.zeros(len(cen), bool)
    hit_obj = np.full(len(cen), -1)
    opaque_hit = np.zeros(len(cen), bool)
    glazing_hit = np.zeros(len(cen), bool)
    if len(t):
        bvh = BVH(v[t[:, 0]], v[t[:, 1]], v[t[:, 2]])
        # three probes per sub-triangle (centroid and two points towards its corners), both directions
        probes = [cen, 0.6 * cen + 0.4 * a, 0.6 * cen + 0.4 * b]
        votes = np.zeros(len(cen), int)
        glass_votes = np.zeros(len(cen), int)
        for p in probes:
            got = np.zeros(len(cen), bool)
            glass = np.zeros(len(cen), bool)
            for sgn in (1.0, -1.0):
                o = p - sgn * n * tolerance
                tt, tri = bvh.intersect(o, sgn * n)
                h = (tri >= 0) & (tt <= 2 * tolerance)
                newly = h & ~got
                hit_obj[newly & (hit_obj < 0)] = scene.tri_object[keep[tri[newly & (hit_obj < 0)]]]
                kinds = np.array([scene.materials[int(m)].kind for m in scene.tri_material[keep[tri[h]]]]) if h.any() else np.array([])
                opaque_hit[np.flatnonzero(h)[kinds != "glazing"]] = True
                glass[np.flatnonzero(h)[kinds == "glazing"]] = True
                got |= h
            votes += got
            glass_votes += glass
        covered = votes >= 2
        glazing_hit = glass_votes >= 2          # mostly over the glass, as for the cover itself
    shared = np.zeros(len(cen), bool)
    for other in neighbours or []:
        if other is room:
            continue
        ov, ot = other.vertices, other.triangles
        nb = BVH(ov[ot[:, 0]], ov[ot[:, 1]], ov[ot[:, 2]])
        for sgn in (1.0, -1.0):
            tt, tri = nb.intersect(cen - sgn * n * tolerance, sgn * n)
            shared |= (tri >= 0) & (tt <= 2 * tolerance)
    covered |= shared
    gz = float(scene.vertices[:, 2].min()) if ground_z is None and len(scene.vertices) else (ground_z or 0.0)
    down = n[:, 2] < -0.7
    on_ground = down & (np.abs(cen[:, 2] - gz) < tolerance)
    ground_only = on_ground & ~covered          # resting on the ground with no floor element modelled
    covered |= on_ground
    sides_top = ~down
    total_st = float(area[sides_top].sum())
    open_mask = ~covered
    self_enclosed = False
    if room.closed_input and float(area[opaque_hit & sides_top & ~shared].sum()) < 0.01 * total_st:
        # no walls or roof modelled around a closed room volume (at most its windows and neighbouring
        # rooms): its own faces are the envelope (classic zones)
        open_mask[:] = False
        self_enclosed = True
    # an opening into the rest of the building (a double-height void, a stair, a gallery edge) is not open
    # to outside: the space beyond it is enclosed when rays from there hit the building in every direction
    internal = np.zeros(len(cen), bool)
    if open_mask.any() and len(t):
        idx = np.flatnonzero(open_mask)
        beyond = cen[idx] + n[idx] * (tolerance + 0.2)
        dirs = np.array([[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1],
                         [0.7, 0.7, 0.2], [-0.7, 0.7, 0.2], [0.7, -0.7, 0.2], [-0.7, -0.7, 0.2]], float)
        dirs /= np.linalg.norm(dirs, axis=1)[:, None]
        hits = np.zeros(len(idx), int)
        for d in dirs:
            tt, tri = bvh.intersect(beyond, np.repeat(d[None], len(idx), axis=0))
            hits += (tri >= 0) & (tt < 40.0)
        internal[idx] = hits >= len(dirs) - 1
    open_mask &= ~internal
    open_area = float(area[open_mask & sides_top].sum())
    frac = open_area / total_st if total_st > 0 else 0.0
    state = "enclosed" if frac < ENCLOSED_MAX else "semi_open" if frac < semi_open_max else "open"
    cons = np.full(len(cen), "", dtype=object)
    elem = np.full(len(cen), "", dtype=object)
    for i in np.flatnonzero(hit_obj >= 0):
        info = scene.objects[int(hit_obj[i])]
        cid = str(info.get("construction") or "")
        # a window's construction belongs to the window surface, not to the wall face it sits in
        cons[i] = "" if cid and asm.get(cid)["kind"] == "window" else cid
        elem[i] = str(info.get("name") or info.get("layer") or "")
    # the face behind a window belongs to the wall it sits in: take the construction of the opaque faces in
    # the same plane (by area), so the set default does not stand in for a wall that is modelled
    glazed = np.flatnonzero(glazing_hit & (cons == ""))
    walls = np.flatnonzero((cons != "") & ~glazing_hit)
    for i in glazed:
        same = walls[(n[walls] @ n[i] > 0.99) & (np.abs((cen[walls] - cen[i]) @ n[i]) < tolerance)]
        if len(same):
            by: dict[str, float] = {}
            for j in same:
                by[cons[j]] = by.get(cons[j], 0.0) + float(area[j])
            cons[i] = max(by, key=by.get)
    openings: dict[str, dict] = {}
    for i in np.flatnonzero(open_mask & sides_top):
        key = "roof" if n[i, 2] > 0.7 else orientation_of(n[i], scene.north_deg)
        g = openings.setdefault(key, {"orientation": key, "normal": [0.0, 0.0, 0.0], "area_m2": 0.0,
                                      "z_min": float("inf"), "z_max": float("-inf")})
        g["area_m2"] += float(area[i])
        g["normal"] = list(np.asarray(g["normal"]) + n[i] * area[i])
        g["z_min"] = min(g["z_min"], float(tris[i, :, 2].min()))
        g["z_max"] = max(g["z_max"], float(tris[i, :, 2].max()))
    inner: dict[str, float] = {}
    for i in np.flatnonzero(internal):
        key = "up" if n[i, 2] > 0.7 else "down" if n[i, 2] < -0.7 else orientation_of(n[i], scene.north_deg)
        inner[key] = inner.get(key, 0.0) + float(area[i])
    ops = []
    for g in openings.values():
        nn = np.asarray(g["normal"])
        g["normal"] = [round(float(x), 3) for x in nn / max(np.linalg.norm(nn), 1e-12)]
        g["area_m2"] = round(g["area_m2"], 2)
        g["z_min"], g["z_max"] = round(g["z_min"], 2), round(g["z_max"], 2)
        ops.append(g)
    warning = ""
    if state == "semi_open":
        warning = (f"Room {room.name} is not enclosed: {100 * frac:.0f} % of its sides and top are open. Its air change "
                   "is computed from the openings (wind and stack); heating and cooling figures are indicative.")
    elif state == "open":
        warning = (f"Room {room.name} is an open space ({100 * frac:.0f} % open): it is assessed as semi-outdoor comfort "
                   "(air at outdoor temperature, sun and sky on the occupants); no heating or cooling loads.")
    if state == "enclosed" and open_area > 0.5:
        warning = (f"Room {room.name}: {open_area:.1f} m2 of its boundary has no element within {tolerance:g} m (gaps in the "
                   "model, or small openings); treated as closed.")
    if inner:
        note = (f"Room {room.name} opens into other parts of the building ({sum(inner.values()):.0f} m2: "
                + ", ".join(f"{k} {v:.0f} m2" for k, v in sorted(inner.items(), key=lambda kv: -kv[1]))
                + "). Those openings are treated as adiabatic, with no air exchange; for open-plan spaces define one room.")
        warning = (warning + " " + note).strip()
    return Enclosure(state, frac, open_area, float(area.sum()), self_enclosed, tris, open_mask, cons, elem,
                     sorted(ops, key=lambda g: -g["area_m2"]), internal,
                     [{"orientation": k, "area_m2": round(v, 2)} for k, v in sorted(inner.items(), key=lambda kv: -kv[1])], warning,
                     tri_glazing=glazing_hit, tri_ground_only=ground_only)


# ── openings airflow ─────────────────────────────────────────────────────────

def opening_air_changes(openings: list[dict], volume: float, weather, delta_t: float = 2.0) -> np.ndarray:
    """Hourly air changes through permanent openings: single-sided per de Gids and Phaff (1982)
    Q = A/2 sqrt(0.001 v^2 + 0.0035 H dT + 0.01), cross ventilation by orifice flow
    Q = 0.61 A_eff v sqrt(0.5) between openings on opposite sides; the larger of the two."""
    v = np.maximum(np.asarray(weather["wind_speed"], dtype=float), 0.0) * WIND_LOCAL
    side = [o for o in openings if o["orientation"] != "roof"]
    if not side or volume <= 0:
        return np.zeros(HOURS)
    q_single = np.zeros(HOURS)
    for o in side:
        h = max(o["z_max"] - o["z_min"], 0.1)
        q_single += o["area_m2"] / 2.0 * np.sqrt(0.001 * v ** 2 + 0.0035 * h * delta_t + 0.01)
    q_cross = np.zeros(HOURS)
    for i in range(len(side)):
        for j in range(i + 1, len(side)):
            if np.dot(side[i]["normal"], side[j]["normal"]) < -0.2:
                a1, a2 = side[i]["area_m2"], side[j]["area_m2"]
                a_eff = 1.0 / math.sqrt(1.0 / a1 ** 2 + 1.0 / a2 ** 2)
                q_cross = np.maximum(q_cross, 0.61 * a_eff * v * math.sqrt(0.5))
    return np.maximum(q_single, q_cross) * 3600.0 / volume


# ── semi-outdoor comfort (open rooms) ────────────────────────────────────────

ALPHA_SW = 0.67             # short-wave absorptance of skin and clothing (SolarCal default)
F_EFF = 0.725               # effective radiating area fraction, standing
H_R = 6.012                 # W/m2K radiative heat transfer coefficient (SolarCal)
BODY_H, BODY_D, BODY_A = 1.75, 0.31, 1.8


def projected_area_factor(sun_alt_deg: np.ndarray) -> np.ndarray:
    """Projected area of a standing body (a cylinder) seen from the sun, over its total area."""
    b = np.radians(np.clip(sun_alt_deg, 0, 90))
    return (BODY_H * BODY_D * np.cos(b) + math.pi * BODY_D ** 2 / 4 * np.sin(b)) / BODY_A


def semi_outdoor(room: Room, enc: Enclosure, scene, weather, roof_construction: str = "",
                 met: float = 1.2, ground_reflectance: float = 0.2, occupied: tuple[float, float] = (7.0, 19.0),
                 hot_set: float = 30.0, very_hot_set: float = 34.0) -> dict:
    """Hourly air, mean radiant and SET* temperatures for an open room, averaged over occupant points."""
    from . import sky as skymod
    from .daylight import EPS, Tracer
    from .scene import grid_from_triangles
    from .solar import sun_positions_for
    floor = room.triangles[(np.cross(room.vertices[room.triangles[:, 1]] - room.vertices[room.triangles[:, 0]],
                                     room.vertices[room.triangles[:, 2]] - room.vertices[room.triangles[:, 0]])[:, 2] < 0)]
    spacing = max(0.5, math.sqrt(max(_floor_area(room), 1.0) / 30.0))
    grid = grid_from_triangles(room.vertices, floor, spacing, 1.1, 0.25, True)
    pts = grid.points
    if not len(pts):
        raise ValueError(f"Room {room.name}: could not place occupant points on its floor")
    tracer = Tracer(scene)
    p = skymod.patches(1)
    dirs = p.direction[:p.n_sky]
    up = dirs[:, 2] > 0
    vis = np.zeros((len(pts), p.n_sky))
    for k in np.flatnonzero(up):
        T, _ = tracer.transmit(pts + np.array([0, 0, EPS]), np.repeat(dirs[k][None], len(pts), axis=0))
        vis[:, k] = T
    svv = (vis * p.solid_angle[:p.n_sky]).sum(axis=1) / (2 * math.pi)         # sky vault view per point
    sun = sun_positions_for(weather)
    alt = sun["altitude"]
    from .solar import direction_vector
    sdir = direction_vector(alt, sun["azimuth"], scene.north_deg)
    dni = np.nan_to_num(np.asarray(weather["dni"], float))
    dhi = np.nan_to_num(np.asarray(weather["dhi"], float))
    ghi = np.nan_to_num(np.asarray(weather["ghi"], float))
    sunlit = np.zeros(HOURS)
    hrs = np.flatnonzero((alt > 0) & (dni > 0))
    for chunk in np.array_split(hrs, max(1, len(hrs) // 400)):
        if not len(chunk):
            continue
        o = np.repeat(pts[None], len(chunk), axis=0).reshape(-1, 3)
        d = np.repeat(sdir[chunk], len(pts), axis=0)
        T, _ = tracer.transmit(o + d * EPS, d)
        sunlit[chunk] = T.reshape(len(chunk), len(pts)).mean(axis=1)
    svv_m = float(svv.mean())
    f_p = projected_area_factor(alt)
    i_th_refl = ground_reflectance * (dhi * svv_m + dni * np.sin(np.radians(np.maximum(alt, 0))) * sunlit)
    erf = ALPHA_SW * (0.5 * F_EFF * (svv_m * dhi + i_th_refl) + f_p * sunlit * dni)
    d_mrt_sw = erf / (F_EFF * H_R)
    t_out = np.asarray(weather["dry_bulb"], float)
    ir = np.asarray(weather["horizontal_ir"], float)
    t_sky = np.where(np.isfinite(ir) & (ir > 0), (np.maximum(ir, 1.0) / 5.670374419e-8) ** 0.25 - 273.15,
                     0.0552 * (t_out + 273.15) ** 1.5 - 273.15)
    # roof underside: steady-state inner surface temperature under the sol-air excess of the roof top
    u_roof, a_roof = 5.9, 0.6
    if roof_construction:
        s = asm.summary(roof_construction)
        u_roof = s["u_value"]
        a_roof = s.get("outside_solar_absorptance") or 0.6
    t_ceil = t_out + u_roof * 0.13 * (a_roof * ghi * 0.04)
    covered_up = 1.0 - svv_m
    tk = lambda x: x + 273.15
    mrt_lw = (0.5 * (svv_m * tk(t_sky) ** 4 + covered_up * tk(t_ceil) ** 4) + 0.5 * tk(t_out) ** 4) ** 0.25 - 273.15
    mrt = mrt_lw + d_mrt_sw
    vel = np.clip(np.asarray(weather["wind_speed"], float) * WIND_LOCAL, 0.1, 5.0)
    rh = np.clip(np.asarray(weather["rel_humidity"], float), 1, 100)
    clo = np.where(t_out > 18.0, 0.5, 1.0)
    set_ = comfort.set_star(t_out, mrt, vel, rh, met, clo)
    hod = weather.hour_of_day
    occ = (hod >= occupied[0]) & (hod < occupied[1])
    hi = comfort.heat_index(t_out, rh)
    return {
        "method": "semi-outdoor: air = outdoor dry-bulb; MRT = long-wave (sky, roof underside, ground) + SolarCal short-wave; SET*",
        "points": int(len(pts)), "sky_view_mean": round(svv_m, 3),
        "occupied_hours": int(occ.sum()), "occupied_window": list(occupied),
        "sunlit_occupied_pct": round(100 * float((sunlit[occ] > 0.5).mean()), 1),
        "mrt_c": {"mean_occupied": round(float(mrt[occ].mean()), 1), "max": round(float(mrt.max()), 1)},
        "mrt_minus_air_occupied_mean_k": round(float((mrt - t_out)[occ].mean()), 1),
        "set_c": {"mean_occupied": round(float(set_[occ].mean()), 1), "p90_occupied": round(float(np.percentile(set_[occ], 90)), 1),
                  "max": round(float(set_.max()), 1)},
        "hours_set_above": {f"{hot_set:g}": int((set_[occ] > hot_set).sum()), f"{very_hot_set:g}": int((set_[occ] > very_hot_set).sum())},
        "heat_index_max_c": round(float(np.nanmax(hi)), 1),
        "assumptions": f"standing, met {met}, clo 0.5 above 18 degC outdoor else 1.0, local wind {WIND_LOCAL} x EPW wind, "
                       f"ground reflectance {ground_reflectance}, roof U {u_roof:.2f}; SET bands {hot_set:g} / {very_hot_set:g} degC "
                       "are reporting thresholds, not a standard",
        "_hourly": {"t_air": t_out, "mrt": mrt, "set": set_, "sunlit": sunlit},
        "_points": pts, "_svv": svv,
    }


def _floor_area(room: Room) -> float:
    v, f = room.vertices, room.triangles
    a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    cr = np.cross(b - a, c - a)
    return float(0.5 * np.linalg.norm(cr[cr[:, 2] < 0], axis=1).sum())


# ── thermal zones from rooms ─────────────────────────────────────────────────

def _set_default(room: Room, kind: str) -> str:
    if not room.construction_set:
        return ""
    sets = {s["id"]: s for s in asm._load("assemblies.json")["sets"]}
    if room.construction_set not in sets:
        raise ValueError(f"Room {room.name}: construction set '{room.construction_set}' is unknown")
    return sets[room.construction_set]["defaults"].get(kind, "")


def zone_mass(zone: thermal.Zone) -> tuple[float, float] | None:
    """(A_m, C_m) from the surfaces' constructions, or None when less than half the opaque area has one."""
    opaque = [s for s in zone.surfaces if s.kind not in ("window", "opening")]
    total = sum(s.area for s in opaque)
    known = sum(s.area for s in opaque if s.construction)
    if total <= 0 or known < 0.5 * total:
        return None
    c_m, k2a = 0.0, 0.0
    for s in opaque:
        if s.construction:
            p = asm.summary(s.construction)
            # a ceiling (normal up) sees the underside of the floor above: the assembly's outside layers
            face_up = s.normal[2] > 0.7 and p["kind"] in ("floor_internal", "ceiling_internal")
            kappa = 1000.0 * (p["kappa_outside_kj_m2k"] if face_up else p["kappa_inside_kj_m2k"])
        else:
            kappa = KAPPA_DEFAULT
        c_m += kappa * s.area
        k2a += kappa ** 2 * s.area
    if c_m <= 0:
        return None
    return c_m ** 2 / k2a, c_m


def zones_from_rooms(rooms: list[Room], encs: list[Enclosure], scene, windows: list[dict],
                     problems: list[str] | None = None) -> list[thermal.Zone]:
    """Thermal zones for the enclosed and semi-open rooms. With ``problems`` (a list), a room that is not a
    valid zone (too small, implausible height) is left out with the reason appended instead of raising."""
    idx = [i for i, e in enumerate(encs) if e.state != "open"]
    # ground level: the lowest room floor, not each room's own lowest point - a room raised above it (an upper
    # storey with no room below, a cantilever, pilotis) has an exposed floor; one beside it (slab steps within
    # the enclosure tolerance) rests on the ground
    ground_z = min((rooms[i].floor_z for i in idx), default=0.0)
    zones = []
    for i in idx:
        r, e = rooms[i], encs[i]
        others = [(rooms[j].vertices, rooms[j].triangles) for j in idx if j != i]
        names = [rooms[j].name for j in idx if j != i]
        tp = e.tri_points
        v = tp.reshape(-1, 3)
        f = np.arange(len(v)).reshape(-1, 3)
        cons = list(e.tri_construction)
        # room set defaults fill unassigned faces, by orientation
        nz = np.cross(tp[:, 1] - tp[:, 0], tp[:, 2] - tp[:, 0])
        nz = nz[:, 2] / np.maximum(np.linalg.norm(nz, axis=1), 1e-12)
        for k in range(len(cons)):
            if not cons[k] and not e.tri_open[k]:
                kind = "roof" if nz[k] > 0.7 else "floor_ground" if nz[k] < -0.7 else "wall_external"
                cons[k] = _set_default(r, kind)
        # rooms drawn on floors are a slab apart: neighbours within the enclosure tolerance share a face
        on_ground = r.floor_z - ground_z < TOLERANCE
        z = thermal.zone_from_mesh(r.name, v, f, windows, others, ground_z=r.floor_z if on_ground else ground_z,
                                   face_construction=cons,
                                   face_open=e.tri_open, other_names=names, neighbour_gap=TOLERANCE,
                                   face_adiabatic=e.tri_internal)
        if problems is not None:
            try:
                z.validate()
            except ValueError as exc:
                problems.append(f"Room {r.name} was left out of the thermal study: {exc}")
                continue
        # internal faces between rooms use internal constructions where the element has an external one
        for s in z.surfaces:
            if s.kind == "interzone" and s.construction:
                kind = asm.get(s.construction)["kind"]
                if kind not in asm.INTERNAL:
                    s.construction = _set_default(r, "floor_internal" if abs(s.normal[2]) > 0.7 else "wall_internal") or s.construction
            elif s.kind == "interzone" and not s.construction:
                s.construction = _set_default(r, "floor_internal" if abs(s.normal[2]) > 0.7 else "wall_internal")
            elif s.kind == "window" and not s.construction:
                s.construction = _set_default(r, "window")
        z.mass = zone_mass(z)
        prof = dict(ROOM_USES[r.use])
        prof.update(r.setpoints)
        z.profile = prof
        if e.state == "semi_open":
            z.source["openings"] = e.openings
            # open to outside: no heating or cooling, comfort is judged free-running
            prof["heating_setpoint"] = None
            prof["cooling_setpoint"] = None
        z.source.update(room=r.name, use=r.use, enclosure=e.state, guids=r.guids)
        from .lighting import control_points
        z.daylight_points = control_points(daylight_grid(r, 1.0, 0.8, 0.3))
        zones.append(z)
    return zones


def couple(zones: list[thermal.Zone], weather, settings: thermal.Settings, passes: int = 3) -> tuple[list[dict], dict]:
    """Simulate the zones with heat exchange through shared faces. Returns (results per zone, balance)."""
    by_name = {z.name: i for i, z in enumerate(zones)}
    # one conductance per pair of rooms: both rooms see the same element, so each side's estimate of it
    # (its own construction over its own share of the face) is pooled; an explicit construction beats the
    # unassigned fallback. Symmetric links make the exchange conserve energy.
    sides: dict[tuple[int, int], dict[int, list[tuple[float, float, bool]]]] = {}
    for i, z in enumerate(zones):
        for s in z.surfaces:
            if s.kind == "interzone" and s.neighbor in by_name and by_name[s.neighbor] != i:
                j = by_name[s.neighbor]
                u = asm.summary(s.construction)["u_value"] if s.construction else INTERZONE_U_DEFAULT
                sides.setdefault((min(i, j), max(i, j)), {}).setdefault(i, []).append((u * s.area, s.area, bool(s.construction)))
    links = []                                            # (i, j, H W/K), both directions
    for (i, j), per in sides.items():
        estimates = []
        for side in per.values():
            explicit = [h for h, _, e in side if e]
            area = sum(a for _, a, _ in side)
            exp_area = sum(a for _, a, e in side if e)
            # a side's U over the face: its explicit constructions where it has them, scaled to the whole face
            u = (sum(explicit) / exp_area) if exp_area > 0 else INTERZONE_U_DEFAULT
            estimates.append((u, area, exp_area > 0))
        known = [e for e in estimates if e[2]] or estimates
        u = sum(e[0] for e in known) / len(known)
        area = sum(e[1] for e in estimates) / len(estimates)
        links += [(i, j, u * area), (j, i, u * area)]
    results = [None] * len(zones)
    t_air = [None] * len(zones)
    for _ in range(passes if links else 1):
        for i, z in enumerate(zones):
            if t_air[i] is not None:
                q = np.zeros(HOURS)
                for a, b, h in links:
                    if a == i:
                        q += h * (t_air[b] - t_air[i])
                z.coupling_w = q
            results[i] = thermal.simulate(z, weather, settings)
        t_air = [r["t_air"] for r in results]
    flows = np.zeros(HOURS)
    for a, b, h in links:
        flows += h * (t_air[b] - t_air[a])
    balance = {"links": len(links), "net_interzone_kwh": round(float(flows.sum() / 1000), 2),
               "gross_interzone_kwh": round(float(sum(abs(h * (t_air[b] - t_air[a])).sum() for a, b, h in links) / 1000), 1)}
    return results, balance


def daylight_grid(room: Room, spacing: float = 0.5, height: float = 0.8, edge: float = 0.3):
    """A work-plane sensor grid over a room's floor."""
    from .scene import grid_from_triangles
    v, f = room.vertices, room.triangles
    a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    down = np.cross(b - a, c - a)[:, 2] < 0
    return grid_from_triangles(v, f[down], spacing, height, edge, True)
