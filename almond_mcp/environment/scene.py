"""Scenes for environmental analysis: triangles, materials, sensor grids, and a parametric shoebox room.

A scene is a triangle soup in metres (+Z up, +Y north unless a north angle is given), where every
triangle carries a material and the index of the Rhino object (or generated part) it came from.
Materials are deliberately few and physical:

  opaque   Lambertian reflector, visible reflectance rho (both sides)
  glazing  specular transmitter with normal visible transmittance tau_n and Fresnel angular falloff
           (single-pane equivalent, n = 1.52), optional diffusing shade for "closed" states
  ignore   present in the model but not in the light simulation (e.g. annotation, a sensor plane)

Default reflectances follow IES LM-83-12 (ceiling 70 %, walls 50 %, floor 20 %, furniture 50 %,
ground 20 %); they matter as much as the geometry, so every result reports how each object was
classified and why.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, asdict

import numpy as np


@dataclass
class Material:
    name: str
    kind: str = "opaque"                 # "opaque" | "glazing" | "ignore"
    reflectance: float = 0.5             # visible, opaque only
    transmittance: float = 0.0           # visible normal transmittance, glazing only
    shade_transmittance: float = 0.15    # diffuse visible transmittance with the shade down (glazing)
    solar_reflectance: float | None = None   # solar (radiation) reflectance; default = visible
    g_value: float | None = None         # solar heat gain coefficient (glazing), for thermal
    u_value: float | None = None         # W/m2K (glazing), for thermal

    def __post_init__(self):
        if self.kind not in ("opaque", "glazing", "ignore"):
            raise ValueError(f"Material {self.name}: kind must be opaque, glazing or ignore")
        for attr in ("reflectance", "transmittance", "shade_transmittance"):
            v = getattr(self, attr)
            if not 0.0 <= v <= 1.0:
                raise ValueError(f"Material {self.name}: {attr} {v} must be between 0 and 1")
        if self.kind == "opaque" and self.reflectance > 0.95:
            raise ValueError(f"Material {self.name}: reflectance above 0.95 is not a real surface")
        if self.kind == "glazing" and self.transmittance <= 0.0:
            raise ValueError(f"Material {self.name}: glazing needs a transmittance above 0")


LIBRARY: dict[str, Material] = {m.name: m for m in (
    Material("ceiling", reflectance=0.70),
    Material("wall", reflectance=0.50),
    Material("floor", reflectance=0.20),
    Material("furniture", reflectance=0.50),
    Material("partition", reflectance=0.50),
    Material("roof", reflectance=0.35),
    Material("exterior_wall", reflectance=0.35),
    Material("ground", reflectance=0.20),
    Material("context", reflectance=0.35),
    Material("shading", reflectance=0.50),
    Material("black", reflectance=0.0),
    Material("frame", reflectance=0.30),
    Material("glazing_single_clear", kind="glazing", transmittance=0.88, g_value=0.86, u_value=5.8),
    Material("glazing_double_clear", kind="glazing", transmittance=0.80, g_value=0.76, u_value=2.8),
    Material("glazing_double_lowe", kind="glazing", transmittance=0.70, g_value=0.42, u_value=1.6),
    Material("glazing_triple_lowe", kind="glazing", transmittance=0.60, g_value=0.35, u_value=0.8),
    Material("glazing_tinted", kind="glazing", transmittance=0.40, g_value=0.35, u_value=1.6),
    Material("opening", kind="glazing", transmittance=1.0, shade_transmittance=0.15, g_value=1.0, u_value=5.8),
    Material("ignore", kind="ignore"),
)}
DEFAULT_GLAZING = "glazing_double_lowe"

# Keyword rules, first match wins (applied to the layer path, object name and render-material name).
_RULES = (
    (r"\b(ignore|annotation|sensor|grid|dim|text)\b", "ignore"),
    # glass inside the room is not a window (render materials are often just "Glass"): glassware and
    # shower screens are clear and small, so light passes them as if they were not there; mirrors,
    # oven doors and device screens are opaque fittings
    (r"(tumbler|glassware|drinking glass|wine ?glass|carafe|shower ?(screen|glass|door|enclosure)(?! ?(shoe|frame|handle|hinge|rail|seal)))", "ignore"),
    (r"(\bmirror\b(?![ _-]?glass)|\boven\b|microwave|laptop|television|\btv\b)", "furniture"),
    # curtains, drapes and blinds hang at the window but are textiles, not glass (a curtain wall is glazing)
    (r"(curtain(?![ _-]?wall)|\bdrape|\bblinds?\b(?![ _-]?(wall|fa[cç]ade))|\bsheers?\b)", "shading"),
    (r"low.?e", DEFAULT_GLAZING),
    (r"triple", "glazing_triple_lowe"),
    (r"tint", "glazing_tinted"),
    # a window's frame parts are named after the window but are not glass
    (r"(mullion|transom|\bsill|\bframe\b|jamb|lintel|reveal|handle|muntin)", "frame"),
    (r"(glass|glaz|window|curtain[ _-]?wall|skylight|fenestration|clerestor)", None),   # generic glazing
    (r"(opening|void|hole)", "opening"),
    (r"(ceiling|soffit)", "ceiling"),
    (r"(roof)", "roof"),                                  # before "slab": a roof slab is a roof
    (r"(floor|slab)", "floor"),
    (r"(ground|terrain|landscape|topo|site)", "ground"),
    (r"(context|neighbo|surrounding|existing|massing)", "context"),
    (r"(shad|louv|fin|overhang|brise|canopy|awning|screen)", "shading"),
    (r"(furni|desk|table|chair|shelf|cabinet|sofa)", "furniture"),
    (r"(partition)", "partition"),
    (r"(wall|column|beam)", "wall"),
)


def material_from_spec(name: str, spec: dict | str | None) -> Material:
    """A Material from a library name or a dict like {"reflectance": 0.6} / {"transmittance": 0.5}."""
    if spec is None or isinstance(spec, str):
        key = spec or name
        if key not in LIBRARY:
            raise ValueError(f"Unknown material '{key}'. Library: {', '.join(sorted(LIBRARY))}")
        return LIBRARY[key]
    if not isinstance(spec, dict):
        raise ValueError(f"Material '{name}' must be a library name or an object")
    spec = dict(spec)
    base = LIBRARY.get(spec.pop("base", ""), None)
    kind = spec.pop("kind", None) or (base.kind if base else ("glazing" if "transmittance" in spec else "opaque"))
    values = asdict(base) if base else {}
    values.update({"name": name, "kind": kind})
    allowed = {f for f in Material.__dataclass_fields__}
    unknown = set(spec) - allowed
    if unknown:
        raise ValueError(f"Material '{name}': unknown fields {sorted(unknown)}")
    values.update(spec)
    return Material(**values)


def classify(texts: list[str], user_material: str = "", transparency: float = 0.0) -> tuple[str | None, str]:
    """(library material name or None for "by orientation", reason)."""
    if user_material:
        return user_material, "user text almond:env_material"
    joined = " / ".join(t for t in texts if t).lower()
    for pattern, mat in _RULES:
        if re.search(pattern, joined):
            if mat is None:
                return DEFAULT_GLAZING, f"name matches '{pattern.strip('()')}'"
            return mat, f"name matches '{pattern.strip('()')}'"
    if transparency >= 0.3:
        return DEFAULT_GLAZING, f"render material is {transparency:.0%} transparent"
    return None, "by surface orientation (no matching layer/name)"


@dataclass
class Scene:
    vertices: np.ndarray                         # (V, 3) metres
    triangles: np.ndarray                        # (T, 3) int
    tri_material: np.ndarray                     # (T,) index into materials
    tri_object: np.ndarray                       # (T,) index into objects
    materials: list[Material]
    objects: list[dict] = field(default_factory=list)
    north_deg: float = 0.0

    def __post_init__(self):
        self.vertices = np.asarray(self.vertices, dtype=float).reshape(-1, 3)
        self.triangles = np.asarray(self.triangles, dtype=np.int64).reshape(-1, 3)
        self.tri_material = np.asarray(self.tri_material, dtype=np.int64).reshape(-1)
        self.tri_object = np.asarray(self.tri_object, dtype=np.int64).reshape(-1)
        if not np.isfinite(self.vertices).all():
            raise ValueError("Scene vertices contain NaN or infinite coordinates")
        n_t = len(self.triangles)
        if len(self.tri_material) != n_t or len(self.tri_object) != n_t:
            raise ValueError("Every triangle needs one material and one object index")
        if n_t and (self.triangles.min() < 0 or self.triangles.max() >= len(self.vertices)):
            raise ValueError("Triangle vertex index out of range")
        if n_t and (self.tri_material.min() < 0 or self.tri_material.max() >= len(self.materials)):
            raise ValueError("Triangle material index out of range")

    # derived geometry
    @property
    def v0(self) -> np.ndarray:
        return self.vertices[self.triangles[:, 0]]

    def corners(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        t = self.triangles
        return self.vertices[t[:, 0]], self.vertices[t[:, 1]], self.vertices[t[:, 2]]

    def normals(self) -> tuple[np.ndarray, np.ndarray]:
        a, b, c = self.corners()
        n = np.cross(b - a, c - a)
        area2 = np.linalg.norm(n, axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            unit = n / area2[:, None]
        return np.nan_to_num(unit), 0.5 * area2

    def clean(self, min_area: float = 1e-8) -> "Scene":
        """Drop degenerate triangles and ``ignore`` materials (returns a new scene)."""
        _, area = self.normals()
        kinds = np.array([m.kind for m in self.materials])
        keep = (area > min_area) & (kinds[self.tri_material] != "ignore")
        return Scene(self.vertices, self.triangles[keep], self.tri_material[keep], self.tri_object[keep],
                     self.materials, self.objects, self.north_deg)

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        if len(self.triangles) == 0:
            return np.zeros(3), np.zeros(3)
        used = self.vertices[np.unique(self.triangles)]
        return used.min(axis=0), used.max(axis=0)

    def material_table(self) -> list[dict]:
        _, area = self.normals()
        out = []
        for i, m in enumerate(self.materials):
            sel = self.tri_material == i
            if not sel.any():
                continue
            row = {"material": m.name, "kind": m.kind, "area_m2": round(float(area[sel].sum()), 3),
                   "triangles": int(sel.sum())}
            row.update({"reflectance": m.reflectance} if m.kind == "opaque" else
                       {"transmittance": m.transmittance, "shade_transmittance": m.shade_transmittance})
            out.append(row)
        return out

    def merged(self, other: "Scene") -> "Scene":
        names = [m.name for m in self.materials]
        mats = list(self.materials)
        remap = []
        for m in other.materials:
            if m.name in names:
                remap.append(names.index(m.name))
            else:
                remap.append(len(mats))
                mats.append(m)
                names.append(m.name)
        return Scene(np.vstack([self.vertices, other.vertices]),
                     np.vstack([self.triangles, other.triangles + len(self.vertices)]),
                     np.concatenate([self.tri_material, np.asarray(remap, dtype=np.int64)[other.tri_material]]),
                     np.concatenate([self.tri_object, other.tri_object + len(self.objects)]),
                     mats, self.objects + other.objects, self.north_deg)


def principal_normal(normals: np.ndarray, areas: np.ndarray) -> np.ndarray:
    """The dominant face direction of a set of triangles, sign-free (largest-eigenvalue axis of the
    area-weighted normal tensor). Works for a single surface and for a closed thin solid, whose
    normals cancel when simply summed."""
    n = np.asarray(normals, dtype=float)
    a = np.asarray(areas, dtype=float)
    tensor = (n * a[:, None]).T @ n
    vals, vecs = np.linalg.eigh(tensor)
    v = vecs[:, int(np.argmax(vals))]
    s = (n * a[:, None]).sum(axis=0)
    return v if float(s @ v) >= 0 else -v


def pane_faces(normals: np.ndarray, areas: np.ndarray) -> np.ndarray:
    """Mask of the triangles that make up one side of a glazing object: its faces parallel to the
    principal direction, and of a thin solid only the side facing that way (so its area is the pane's
    area, not twice it plus the edges)."""
    pn = principal_normal(normals, areas)
    d = np.asarray(normals) @ pn
    pos, neg = d > 0.9, d < -0.9
    a = np.asarray(areas)
    if a[pos].sum() > 0.3 * a.sum() and a[neg].sum() > 0.3 * a.sum():
        return pos
    return pos | neg


def thin_solid_panes(scene: "Scene", max_thickness: float = 0.1) -> np.ndarray:
    """Per triangle: True where the triangle is a face of a glazing object modelled as a closed thin
    solid (a pane with thickness, not a surface). Light crosses two faces of such a pane, so each
    face carries the square root of the pane's transmittance."""
    flags = np.zeros(len(scene.triangles), dtype=bool)
    kinds = np.array([m.kind for m in scene.materials])
    glass = kinds[scene.tri_material] == "glazing"
    if not glass.any():
        return flags
    normal, area = scene.normals()
    for obj in np.unique(scene.tri_object[glass]):
        sel = np.flatnonzero(glass & (scene.tri_object == obj))
        a = area[sel]
        if a.sum() <= 0:
            continue
        closure = np.linalg.norm((normal[sel] * a[:, None]).sum(axis=0)) / a.sum()
        pn = principal_normal(normal[sel], a)
        pts = scene.vertices[scene.triangles[sel]].reshape(-1, 3)
        thickness = float(np.ptp(pts @ pn))
        if closure < 0.1 and thickness <= max_thickness:
            flags[sel] = True
    return flags


def glazing_transmittance(tau_n: float | np.ndarray, cos_incidence: np.ndarray, n_index: float = 1.52) -> np.ndarray:
    """Directional visible transmittance of a single-pane-equivalent glazing whose normal-incidence
    transmittance is ``tau_n``: Fresnel reflection at both faces (unpolarised) plus absorption along
    the refracted path, with internal multiple reflections. tau(0) == tau_n exactly; tau(90) == 0.
    ``tau_n == 1`` is an open hole and returns 1 at every angle."""
    cos_i = np.clip(np.abs(np.asarray(cos_incidence, dtype=float)), 1e-6, 1.0)
    tau_n_arr = np.broadcast_to(np.asarray(tau_n, dtype=float), cos_i.shape)
    out = np.ones_like(cos_i)
    hole = tau_n_arr >= 0.999
    if hole.all():
        return out
    sin_i = np.sqrt(1 - cos_i ** 2)
    sin_t = sin_i / n_index
    cos_t = np.sqrt(1 - sin_t ** 2)
    rs = ((cos_i - n_index * cos_t) / (cos_i + n_index * cos_t)) ** 2
    rp = ((n_index * cos_i - cos_t) / (n_index * cos_i + cos_t)) ** 2
    r0 = ((n_index - 1) / (n_index + 1)) ** 2
    # internal transmissivity a at normal incidence, from tau_n = a (1-r0)^2 / (1 - a^2 r0^2)
    tn = np.clip(tau_n_arr, 1e-6, (1 - r0) ** 2 / (1 - r0 ** 2) - 1e-9)
    qa, qb, qc = tn * r0 ** 2, (1 - r0) ** 2, -tn
    a = (-qb + np.sqrt(qb * qb - 4 * qa * qc)) / (2 * qa)
    a_t = a ** (1.0 / cos_t)
    t = 0.0
    for r in (rs, rp):
        t = t + 0.5 * a_t * (1 - r) ** 2 / (1 - (a_t * r) ** 2)
    # rescale so tau(0) equals tau_n even where it was clipped (very clear glass)
    t0 = a * (1 - r0) ** 2 / (1 - (a * r0) ** 2)
    t = t * (tau_n_arr / t0)
    return np.where(hole, 1.0, np.clip(t, 0.0, 1.0))


# ── building scenes ──────────────────────────────────────────────────────────

class SceneBuilder:
    """Accumulates named parts (quads, triangles, meshes) into a Scene."""

    def __init__(self, materials: dict[str, Material] | None = None):
        self.verts: list[np.ndarray] = []
        self.tris: list[np.ndarray] = []
        self.mats: list[np.ndarray] = []
        self.objs: list[np.ndarray] = []
        self.materials: list[Material] = []
        self.objects: list[dict] = []
        self._n = 0
        self._lib = dict(LIBRARY)
        if materials:
            self._lib.update(materials)

    def material_index(self, name: str | Material) -> int:
        m = name if isinstance(name, Material) else self._lib.get(name)
        if m is None:
            raise ValueError(f"Unknown material '{name}'")
        for i, existing in enumerate(self.materials):
            if existing.name == m.name:
                return i
        self.materials.append(m)
        return len(self.materials) - 1

    def add_mesh(self, vertices, triangles, material: str | Material, info: dict, tri_materials=None) -> int:
        v = np.asarray(vertices, dtype=float).reshape(-1, 3)
        t = np.asarray(triangles, dtype=np.int64).reshape(-1, 3)
        oid = len(self.objects)
        self.objects.append(info)
        mi = self.material_index(material)
        self.verts.append(v)
        self.tris.append(t + self._n)
        self.mats.append(np.full(len(t), mi) if tri_materials is None else np.asarray(tri_materials))
        self.objs.append(np.full(len(t), oid))
        self._n += len(v)
        return oid

    def add_quad(self, corners, material, info: dict) -> int:
        c = np.asarray(corners, dtype=float).reshape(4, 3)
        return self.add_mesh(c, [[0, 1, 2], [0, 2, 3]], material, info)

    def build(self, north_deg: float = 0.0) -> Scene:
        if not self.tris:
            return Scene(np.zeros((0, 3)), np.zeros((0, 3), int), np.zeros(0, int), np.zeros(0, int),
                         self.materials or [LIBRARY["wall"]], self.objects, north_deg)
        return Scene(np.vstack(self.verts), np.vstack(self.tris), np.concatenate(self.mats),
                     np.concatenate(self.objs), self.materials, self.objects, north_deg)


def _is_closed(v: np.ndarray, f: np.ndarray) -> bool:
    """True when a triangle mesh is a closed solid (area-weighted normals cancel)."""
    a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    cr = np.cross(b - a, c - a)
    total = np.linalg.norm(cr, axis=1).sum()
    return bool(total > 0 and np.linalg.norm(cr.sum(axis=0)) < 0.05 * total)


def _add_construction(b: "SceneBuilder", v: np.ndarray, f: np.ndarray, info: dict) -> None:
    """An element with an ``almond:construction``: glazing optics from the window assembly; opaque finishes
    from the assembly's layers - the top of a roof shows its outside finish, the underside of a floor its
    soffit, everything else the inside finish."""
    from . import constructions as asm
    cid = info["construction"]
    try:
        p = asm.summary(cid)
    except ValueError as exc:
        raise ValueError(f"Object {info['guid']}: {exc}") from None
    if p["kind"] == "window":
        mat = Material(f"c:{cid}", kind="glazing", transmittance=max(min(p["tau_v"], 1.0), 0.01),
                       g_value=p["g_value"], u_value=p["u_value"])
        info.update(material=mat.name, reason=f"construction {cid}")
        b.add_mesh(v, f, mat, info)
        return
    inside = p.get("inside_reflectance")
    outside = p.get("outside_reflectance")
    m_in = Material(f"c:{cid}:in", reflectance=min(inside if inside is not None else 0.5, 0.95))
    m_out = Material(f"c:{cid}:out", reflectance=min(outside if outside is not None else 0.35, 0.95))
    a, bb, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    n = np.cross(bb - a, c - a)
    nz = n[:, 2] / np.maximum(np.linalg.norm(n, axis=1), 1e-30)
    i_in, i_out = b.material_index(m_in), b.material_index(m_out)
    if p["kind"] == "roof":
        idx = np.where(nz > 0.7, i_out, i_in)
    elif p["kind"].startswith("floor"):
        idx = np.where(nz < -0.7, i_out, i_in)
    else:
        idx = np.full(len(f), i_in)
    info.update(material=f"construction {cid}", reason=f"construction {cid}")
    b.add_mesh(v, f, m_in, info, tri_materials=idx)


def scene_from_export(data: dict, overrides: dict | None = None, default_glazing: str = DEFAULT_GLAZING) -> Scene:
    """Build a Scene from the JSON the Rhino export script writes (see rhino.py):

    {"units_to_m": 0.001, "objects": [{"guid", "layer", "name", "material", "transparency",
      "env_material", "vertices": [x,y,z,...], "faces": [i,j,k,...]}, ...]}

    ``overrides`` maps a GUID, a layer path (exact, case-insensitive) or a library material name
    to a material spec, and takes precedence over user text and names.
    """
    overrides = {str(k).lower(): v for k, v in (overrides or {}).items()}
    scale = float(data.get("units_to_m", 1.0))
    if not (scale > 0 and math.isfinite(scale)):
        raise ValueError("Export has an invalid unit scale")
    b = SceneBuilder()
    for o in data.get("objects", []):
        v = np.asarray(o.get("vertices", []), dtype=float).reshape(-1, 3) * scale
        f = np.asarray(o.get("faces", []), dtype=np.int64).reshape(-1, 3)
        if len(f) == 0:
            continue
        texts = [o.get("layer", ""), o.get("name", ""), o.get("material", "")]
        guid = str(o.get("guid", ""))
        spec = overrides.get(guid.lower()) or overrides.get(str(o.get("layer", "")).lower())
        info = {"guid": guid, "layer": o.get("layer", ""), "name": o.get("name", ""),
                "construction": str(o.get("construction") or ""), "room": str(o.get("room") or "")}
        if spec is not None:
            mat = material_from_spec(f"{info['layer'] or guid}", spec)
            info.update(material=mat.name, reason="override")
            b.add_mesh(v, f, mat, info)
            continue
        if info["construction"]:
            _add_construction(b, v, f, info)
            continue
        name, reason = classify(texts, str(o.get("env_material", "") or ""), float(o.get("transparency", 0) or 0))
        if name is not None and name in overrides:
            mat = material_from_spec(name, overrides[name])
        elif name is not None:
            mat = material_from_spec(name, None) if name in LIBRARY else None
            if mat is None:
                raise ValueError(f"Object {guid}: almond:env_material '{name}' is not a library material")
            if mat.kind == "glazing" and name == DEFAULT_GLAZING and default_glazing != DEFAULT_GLAZING:
                mat = material_from_spec(default_glazing, overrides.get(default_glazing))
        else:
            mat = None
        if mat is not None:
            info.update(material=mat.name, reason=reason)
            if mat.name in ("floor", "roof") and _is_closed(v, f):
                # a slab modelled as a solid: its underside is the ceiling of the room below
                a, bb, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
                n = np.cross(bb - a, c - a)
                nz = n[:, 2] / np.maximum(np.linalg.norm(n, axis=1), 1e-30)
                under = b.material_index(material_from_spec("ceiling", overrides.get("ceiling")))
                idx = np.where(nz < -0.7, under, b.material_index(mat))
                info.update(material=f"{mat.name} (underside: ceiling)")
                b.add_mesh(v, f, mat, info, tri_materials=idx)
                continue
            b.add_mesh(v, f, mat, info)
            continue
        # by orientation, triangle by triangle
        a, bb, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
        n = np.cross(bb - a, c - a)
        nz = n[:, 2] / np.maximum(np.linalg.norm(n, axis=1), 1e-30)
        names = np.where(nz > 0.7, "floor", np.where(nz < -0.7, "ceiling", "wall"))
        idx = np.array([b.material_index(material_from_spec(nm, overrides.get(nm))) for nm in names], dtype=np.int64)
        info.update(material="by orientation (floor/ceiling/wall)", reason=reason)
        b.add_mesh(v, f, LIBRARY["wall"], info, tri_materials=idx)
    return b.build(float(data.get("north_deg", 0.0)))


# ── sensor grids ─────────────────────────────────────────────────────────────

@dataclass
class SensorGrid:
    points: np.ndarray            # (N, 3)
    normals: np.ndarray           # (N, 3)
    cell_area: np.ndarray         # (N,) m2 each point represents
    spacing: float
    cells: np.ndarray             # (N, 4, 3) the square each point stands for (for drawing)
    group: np.ndarray             # (N,) source surface group
    source: list[dict] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.points)

    @property
    def area(self) -> float:
        return float(self.cell_area.sum())

    def to_json(self) -> dict:
        return {"points": np.round(self.points, 4).tolist(), "normals": np.round(self.normals, 4).tolist(),
                "spacing": self.spacing}


def _plane_frame(n: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    ref = np.array([0.0, 0.0, 1.0]) if abs(n[2]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = np.cross(ref, n)
    u /= np.linalg.norm(u)
    v = np.cross(n, u)
    if abs(n[2]) >= 0.9:          # horizontal plane: u = +X, v = +Y for tidy plan grids
        u, v = np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0]) * (1 if n[2] > 0 else 1)
    return u, v


def grid_from_triangles(vertices: np.ndarray, triangles: np.ndarray, spacing: float = 0.5,
                        offset: float = 0.76, edge_offset: float = 0.0, face_up: bool = True,
                        max_points: int = 20000) -> SensorGrid:
    """A regular sensor grid on the planar regions of a mesh (floors, facades, roofs).

    Triangles are grouped by plane; each plane's footprint is unioned, inset by ``edge_offset``, and
    sampled on a square grid of ``spacing``. Points are lifted ``offset`` along the normal (for a
    horizontal floor with ``face_up``: straight up, whichever way the surface was drawn). Curved
    surfaces fall back to one point per (subdivided) triangle.
    """
    import shapely
    import shapely.affinity
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    if not spacing > 0:
        raise ValueError("Grid spacing must be positive")
    v = np.asarray(vertices, dtype=float)
    t = np.asarray(triangles, dtype=np.int64)
    a, b, c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
    n = np.cross(b - a, c - a)
    area = 0.5 * np.linalg.norm(n, axis=1)
    keep = area > 1e-9
    a, b, c, n, area = a[keep], b[keep], c[keep], n[keep], area[keep]
    n = n / (2 * area[:, None])
    if face_up:
        # a work plane lies over floors: of a slab modelled as a solid only its horizontal faces count
        # (its edges would put sensors outside the building)
        horiz = np.abs(n[:, 2]) >= 0.7
        if not horiz.any():
            raise ValueError("A work-plane grid needs horizontal floor surfaces; these are all vertical or steep. "
                             "Use analyze_solar_radiation for facades.")
        a, b, c, n, area = a[horiz], b[horiz], c[horiz], n[horiz], area[horiz]
        flip = n[:, 2] < -0.9
        n[flip] *= -1
    d = np.einsum("ij,ij->i", n, a)
    key_n = np.round(n * 200).astype(int)          # ~0.3 deg bins
    key_d = np.round(d / 0.005).astype(int)        # 5 mm
    keys = np.concatenate([key_n, key_d[:, None]], axis=1)
    _, group_id = np.unique(keys, axis=0, return_inverse=True)
    group_id = group_id.reshape(-1)

    pts, nrm, cell, grp, cells = [], [], [], [], []
    curved_tris = []
    for g in range(group_id.max() + 1 if len(group_id) else 0):
        sel = np.flatnonzero(group_id == g)
        g_area = area[sel].sum()
        if g_area < 0.25 * spacing * spacing:
            curved_tris.extend(sel.tolist())
            continue
        nn = n[sel].mean(axis=0)
        nn /= np.linalg.norm(nn)
        u, w = _plane_frame(nn)
        origin = a[sel[0]]
        polys = []
        for i in sel:
            tri = np.stack([a[i], b[i], c[i]]) - origin
            polys.append(Polygon(np.stack([tri @ u, tri @ w], axis=1)))
        shape = unary_union([p.buffer(1e-6) for p in polys if p.is_valid and p.area > 0])
        # a floor laid as separate boards or tiles has hairline seams: close gaps up to 10 cm so they
        # are one surface (otherwise the edge clearance below opens a no-sensor strip at every seam)
        shape = shape.buffer(0.05).buffer(-0.05)
        if edge_offset > 0:
            shape = shape.buffer(-edge_offset)
        if shape.is_empty:
            continue
        # Align the grid with the surface's own principal direction (the longest side of its minimum
        # rotated rectangle), so a room drawn at an angle gets rows parallel to its walls instead of a
        # staircase of part cells, some of them millimetres from a wall.
        mrr = np.asarray(shape.minimum_rotated_rectangle.exterior.coords)
        if len(mrr) >= 4:
            edges = np.diff(mrr[:4], axis=0)
            e = edges[np.argmax(np.linalg.norm(edges, axis=1))]
            phi = math.atan2(e[1], e[0])
            phi = (phi + math.pi / 4) % (math.pi / 2) - math.pi / 4      # smallest rotation to an axis
            if abs(phi) > 1e-6:
                cu, su = math.cos(phi), math.sin(phi)
                u, w = cu * u + su * w, -su * u + cu * w
                shape = shapely.affinity.rotate(shape, -phi, origin=(0, 0), use_radians=True)
        # keep sensors off the very edge: a point millimetres from a wall measures the wall, not the room
        clear = min(0.1, 0.25 * spacing)
        inner = shape.buffer(-clear)
        if not inner.is_empty:
            shape_for_points = inner
        else:
            shape_for_points = shape
        x0, y0, x1, y1 = shape.bounds
        nx = max(1, int(math.floor((x1 - x0) / spacing)))
        ny = max(1, int(math.floor((y1 - y0) / spacing)))
        if nx * ny > max_points * 4:
            raise ValueError(f"Grid of {nx * ny} candidate points on one surface: increase the spacing")
        mx = x0 + 0.5 * ((x1 - x0) - (nx - 1) * spacing)
        my = y0 + 0.5 * ((y1 - y0) - (ny - 1) * spacing)
        gx, gy = np.meshgrid(mx + spacing * np.arange(nx), my + spacing * np.arange(ny))
        gx, gy = gx.ravel(), gy.ravel()
        inside = shapely.contains_xy(shape_for_points, gx, gy)
        gx, gy = gx[inside], gy[inside]
        if gx.size == 0:              # a strip narrower than the spacing: use its centroid
            cpt = shape.representative_point()
            gx, gy = np.array([cpt.x]), np.array([cpt.y])
        p3 = origin + gx[:, None] * u + gy[:, None] * w + offset * nn
        h = 0.5 * spacing
        sq = np.stack([origin + (gx + sx)[:, None] * u + (gy + sy)[:, None] * w + offset * nn
                       for sx, sy in ((-h, -h), (h, -h), (h, h), (-h, h))], axis=1)
        pts.append(p3)
        nrm.append(np.repeat(nn[None], len(p3), axis=0))
        cell.append(np.full(len(p3), spacing * spacing))
        grp.append(np.full(len(p3), g))
        cells.append(sq)
    if curved_tris:
        ct = np.asarray(curved_tris)
        cen = (a[ct] + b[ct] + c[ct]) / 3.0
        pts.append(cen + offset * n[ct])
        nrm.append(n[ct])
        cell.append(area[ct])
        grp.append(np.full(len(ct), -1))
        cells.append(np.stack([a[ct], b[ct], c[ct], c[ct]], axis=1) + offset * n[ct][:, None, :])
    if not pts:
        raise ValueError("No sensor points: the grid surfaces are empty or smaller than the spacing")
    P = np.vstack(pts)
    N_, A_, C_, G_ = np.vstack(nrm), np.concatenate(cell), np.vstack(cells), np.concatenate(grp)
    if face_up and len(P) > 1:
        # the top and underside of a slab both turned up give two stacked copies of the grid: keep the
        # upper one wherever two sensors share a plan position less than 15 cm apart in height
        key = np.round(P[:, :2] / max(0.25 * spacing, 0.02)).astype(np.int64)
        order = np.lexsort((-P[:, 2], key[:, 1], key[:, 0]))
        keep = np.ones(len(P), dtype=bool)
        last_key, last_z = None, None
        for i in order:
            k = (key[i, 0], key[i, 1])
            if k == last_key and last_z - P[i, 2] < 0.15:
                keep[i] = False
                continue
            last_key, last_z = k, P[i, 2]
        P, N_, A_, C_, G_ = P[keep], N_[keep], A_[keep], C_[keep], G_[keep]
    if len(P) > max_points:
        raise ValueError(f"{len(P)} sensor points exceeds the limit of {max_points}: increase the spacing")
    return SensorGrid(points=P, normals=N_, cell_area=A_, spacing=spacing, cells=C_, group=G_)


def grid_from_points(points, normals=None, area: float = 1.0) -> SensorGrid:
    P = np.asarray(points, dtype=float).reshape(-1, 3)
    if normals is None:
        N = np.tile([0.0, 0.0, 1.0], (len(P), 1))
    else:
        N = np.asarray(normals, dtype=float).reshape(-1, 3)
        if len(N) == 1:
            N = np.repeat(N, len(P), axis=0)
        N = N / np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
    h = math.sqrt(area) / 2
    cells = np.stack([P + np.array([sx, sy, 0.0]) for sx, sy in ((-h, -h), (h, -h), (h, h), (-h, h))], axis=1)
    return SensorGrid(points=P, normals=N, cell_area=np.full(len(P), area), spacing=math.sqrt(area),
                      cells=cells, group=np.zeros(len(P), dtype=int))


# ── shoebox ──────────────────────────────────────────────────────────────────

@dataclass
class Shoebox:
    """A rectangular room with one glazed facade, for quick studies without Rhino."""
    width: float = 6.0                   # along the facade, m
    depth: float = 8.0                   # perpendicular to the facade, m
    height: float = 3.0
    orientation: float = 180.0           # azimuth the facade faces, deg clockwise from north
    wwr: float = 0.4                     # window-to-wall ratio of the facade
    sill: float = 0.8
    glazing: str = DEFAULT_GLAZING
    overhang: float = 0.0                # depth of a horizontal overhang at the window head, m
    fins: float = 0.0                    # depth of vertical fins at the window jambs, m
    obstruction_height: float = 0.0      # an opposite building: height above floor, m
    obstruction_distance: float = 10.0   # its distance from the facade, m
    ground: bool = True
    ceiling: str = "ceiling"
    walls: str = "wall"
    floor: str = "floor"

    def validate(self) -> None:
        for name in ("width", "depth", "height"):
            v = getattr(self, name)
            if not 0.5 <= v <= 200:
                raise ValueError(f"{name} must be between 0.5 and 200 m")
        if not 0.0 < self.wwr <= 0.95:
            raise ValueError("wwr must be in (0, 0.95]")
        if not 0 <= self.sill < self.height:
            raise ValueError("sill must be between 0 and the room height")
        if self.overhang < 0 or self.fins < 0 or self.obstruction_height < 0:
            raise ValueError("overhang, fins and obstruction_height cannot be negative")
        if self.obstruction_height > 0 and self.obstruction_distance <= 0:
            raise ValueError("obstruction_distance must be positive")

    def window_rect(self) -> tuple[float, float, float, float]:
        """(x0, x1, z0, z1) of the window on the facade in local coordinates."""
        W, H = self.width, self.height
        area = self.wwr * W * H
        margin = min(0.1, 0.05 * W)
        width = W - 2 * margin
        height = area / width
        sill = self.sill
        if sill + height > H - 0.02:
            sill = max(0.0, H - 0.02 - height)
        if sill + height > H - 0.02:
            height = H - 0.02 - sill
            width = min(W, area / height)
        x0 = 0.5 * (W - width)
        return x0, x0 + width, sill, sill + height

    def build(self, materials: dict[str, Material] | None = None) -> Scene:
        self.validate()
        W, D, H = self.width, self.depth, self.height
        b = SceneBuilder(materials)
        x0, x1, z0, z1 = self.window_rect()
        # local frame: facade on y = 0 facing -Y (south when orientation = 180); room spans y 0..D
        def q(*pts):
            return np.array(pts, dtype=float)
        b.add_quad(q([0, 0, 0], [W, 0, 0], [W, D, 0], [0, D, 0]), self.floor, {"name": "floor", "part": "floor"})
        b.add_quad(q([0, 0, H], [0, D, H], [W, D, H], [W, 0, H]), self.ceiling, {"name": "ceiling", "part": "ceiling"})
        b.add_quad(q([0, D, 0], [W, D, 0], [W, D, H], [0, D, H]), self.walls, {"name": "back wall", "part": "wall"})
        b.add_quad(q([0, 0, 0], [0, D, 0], [0, D, H], [0, 0, H]), self.walls, {"name": "left wall", "part": "wall"})
        b.add_quad(q([W, 0, 0], [W, 0, H], [W, D, H], [W, D, 0]), self.walls, {"name": "right wall", "part": "wall"})
        facade = []
        if z0 > 1e-6:
            facade.append(q([0, 0, 0], [0, 0, z0], [W, 0, z0], [W, 0, 0]))
        if z1 < H - 1e-6:
            facade.append(q([0, 0, z1], [0, 0, H], [W, 0, H], [W, 0, z1]))
        if x0 > 1e-6:
            facade.append(q([0, 0, z0], [0, 0, z1], [x0, 0, z1], [x0, 0, z0]))
            facade.append(q([x1, 0, z0], [x1, 0, z1], [W, 0, z1], [W, 0, z0]))
        for f in facade:
            b.add_quad(f, self.walls, {"name": "facade wall", "part": "facade"})
        b.add_quad(q([x0, 0, z0], [x1, 0, z0], [x1, 0, z1], [x0, 0, z1]), self.glazing,
                   {"name": "window", "part": "window"})
        if self.overhang > 0:
            b.add_quad(q([x0 - 0.1, 0, z1], [x1 + 0.1, 0, z1], [x1 + 0.1, -self.overhang, z1], [x0 - 0.1, -self.overhang, z1]),
                       "shading", {"name": "overhang", "part": "shading"})
        if self.fins > 0:
            for x in (x0, x1):
                b.add_quad(q([x, 0, z0], [x, -self.fins, z0], [x, -self.fins, z1], [x, 0, z1]),
                           "shading", {"name": "fin", "part": "shading"})
        if self.obstruction_height > 0:
            yd = -self.obstruction_distance
            span = max(4 * W, 60.0)
            b.add_quad(q([W / 2 - span, yd, 0], [W / 2 + span, yd, 0], [W / 2 + span, yd, self.obstruction_height],
                         [W / 2 - span, yd, self.obstruction_height]), "context", {"name": "obstruction", "part": "context"})
        if self.ground:
            r = 200.0
            b.add_quad(q([W / 2 - r, -r, -0.001], [W / 2 + r, -r, -0.001], [W / 2 + r, r, -0.001], [W / 2 - r, r, -0.001]),
                       "ground", {"name": "ground", "part": "ground"})
        scene = b.build()
        theta = math.radians(180.0 - self.orientation)
        rot = np.array([[math.cos(theta), -math.sin(theta), 0], [math.sin(theta), math.cos(theta), 0], [0, 0, 1]])
        centre = np.array([W / 2, 0.0, 0.0])
        scene.vertices = (scene.vertices - centre) @ rot.T
        return scene

    def floor_grid(self, scene: Scene, spacing: float = 0.5, work_plane: float = 0.76, edge_offset: float = 0.0) -> SensorGrid:
        sel = np.array([o.get("part") == "floor" for o in scene.objects])[scene.tri_object]
        return grid_from_triangles(scene.vertices, scene.triangles[sel], spacing, work_plane, edge_offset)

    def part_mask(self, scene: Scene, part: str) -> np.ndarray:
        return np.array([o.get("part") == part for o in scene.objects])[scene.tri_object]
