"""Almond's native structural check: a conditioned line model -> frame_solver -> validation result.

The bridge's ``structure_model`` message exports the same conditioned geometry the Karamba
path analyses (welded nodes, members split at intersections, inferred sections, declared
support points). This module applies the same modelling conventions as the Karamba adapter
so the two engines are comparable:

- supports: declared anchor points (snapped to the nearest node), else every lowest-Z node;
  fully fixed, or pinned (translations only) when ``fixed_supports`` is False; a support point in
  the model's ``supports`` list may carry its own type (``parse_support``: fixed, pinned, roller,
  roller-x, roller-y, spring, with optional spring stiffnesses), e.g. from ``almond:support`` user text;
- connections: rigid joints by default; ``connections="simple"`` pins beams (major-axis bending)
  and braces (both axes) where they stop, i.e. where no other member carries on in line (pieces
  drawn along one line form a continuous member); columns stay continuous; a curve's user text
  ``almond:release``
  ("pinned" | "pinned_start" | "pinned_end" | "rigid") overrides either mode for that member;
  "bar" releases both bending axes at both ends whatever the orientation (a pin-jointed truss bar),
  "hinged" releases major-axis bending only at both ends (a planar truss member or simple beam that
  stays continuous in plan);
- imposed load: ``load_kn`` split equally over the free (unsupported) joints, acting -Z; the
  vertices along a curved member are not joints (a curve only between supports carries it as a
  uniform line load);
- explicit loads: ``model["loads"]`` nodal forces/moments and member line loads with their own case
  (G or Q), e.g. the structural reference library's benchmark loads (``_apply_model_loads``);
- self weight: gamma x A along every member, -Z;
- curved members: the bridge polylines curves to the document tolerance; each smooth run is analysed
  as equal chords within its length / CURVE_SAGITTA_RATIO of the curve, turning at most
  MAX_CURVE_TURN each, at most MAX_CURVE_SEGMENTS (``simplify_curve``), and is one member for the
  EN 1993 checks;
- size: the dense solver works within a fixed memory budget (DENSE_BUDGET_GB, so a model's verdict does
  not depend on what else is open). Before assembly the worst case (every bending member compressed
  and refined for stability) is estimated; over budget, curved members are coarsened, then the
  stability refinement is reduced, and only a model that still does not fit is refused with an
  error result (``check_size``);
- deflection limit: span / the design code's ratio (250 for the Eurocode profile); for beam/frame
  every member against its own span: the drawn member (one curve or line, however split at joints,
  and the pieces carrying on in line) between the points that support it, twice the overhang for a
  cantilever; a surface-like frame (vault, gridshell, arch: ``is_surface``) instead gets a global check
  (largest node displacement against the span between its supports) and a local one (each member's
  sag between its joints against its length), ``surface_deflections``; other types the overall
  extent; the caller's span overrides. The member deflection checked is each member's deflection
  relative to what supports it (``member_deflection_spans``),
  so column shortening in a tall frame or rigid-body sway does not count as beam deflection; the
  governing member (largest deflection / limit) is named in the verdict, the largest deflection and
  the absolute maximum displacement are reported alongside;
- joints: points closer than WELD_RATIO x the model's extent are welded into one node (a piece of a
  few mm beside members of many metres cannot be solved accurately);
- load cases: permanent G (self weight, floor build-up, the weight of placed items) and
  variable Q (load_kn, occupancy floor load, contents and occupants of placed items);
- combinations (EN 1990) with the factors of a design code profile (design_codes: "eurocode"
  recommended values by default, a National Annex profile, or "off"): deflection at SLS
  characteristic G + Q; member checks at ULS 6.10, gamma_G G + gamma_Q Q (or the worse of
  6.10a/6.10b), with the profile's gamma_M0 / gamma_M1; design_basis="unfactored" (= design code
  "off") checks both at G + Q (the Karamba route's basis);
- pass: SLS deflection within the limit and ULS member utilization <= 1.0.

The result dict has the same shape as the bridge's ``validate`` reply, with
``analysis_method`` "native".
"""
from __future__ import annotations

import math
import os
import sys
import time

import numpy as np

from . import asset_loads as al
from . import ec3
from . import design_codes as dc
from . import floor_loads as fl
from . import frame_solver as fs

METHOD_PREFIX = "[ALMOND NATIVE FEA (LINEAR 3D FRAME), HIGH CONFIDENCE] "


def method_prefix(confidence: str = "high") -> str:
    """Verdict prefix naming the method and the run's confidence (low for indicative materials)."""
    return f"[ALMOND NATIVE FEA (LINEAR 3D FRAME), {(confidence or 'high').upper()} CONFIDENCE] "
LINE_TYPES = ("beam", "frame", "truss", "canopy", "highrise")
ASSUMPTIONS = [
    "Linear-elastic 3D frame analysis (Almond native solver); second-order (P-Delta) where the stability "
    "check calls for it (see Stability).",
    "Joints as stated under Connections; supports as described in support_mode.",
    "Imposed load shared equally by the free joints, acting downward (along a curve between supports: a uniform "
    "line load); self weight included when enabled.",
    "Curved members analysed as equal straight chords close to the curve (a warning gives the tolerance when "
    "a curve was simplified).",
    "Deflection checked per member relative to its supports (beam ends on columns, a cantilever's root, a truss "
    "chord's end posts; a column or brace between the floors that hold it, from the chord through their "
    "displaced positions), not the absolute displacement: column shortening and rigid-body sway are excluded. "
    "For beam/frame each member is checked against its own span between those supports (a cantilever: twice "
    "its length; a column between floors: the storey height); a frame working as a surface (vault, gridshell, "
    "arch, no columns) is checked globally (largest displacement against the span between its supports) and "
    "locally (member sag between its joints). Sway is checked as storey drift instead (the horizontal "
    "displacement of each column line between consecutive floors over the storey height; not for "
    "structure_type truss).",
    "Member checks per member (EN 1993-1-1): section class from Table 5.2 for the actual stresses "
    "(Class 4 flagged as not covered); cross-section 6.2.1(7) with elastic moduli (plastic only for "
    "Class 1/2 when plastic design is requested); flexural buckling about both axes (6.3.1, curves "
    "from Table 6.2, L_cr = the member between its joints, 5.2.2(7)b); compression + bending by "
    "6.3.3 (6.61)/(6.62) with Annex B factors and Table B.3 Cm; shear 6.2.6 (V_pl,Rd with the 6.2.6(3) "
    "shear area, eta = 1.0; webs past hw/tw = 72 epsilon / eta flagged as not covered) and bending with "
    "high shear 6.2.8. Local bow imperfections (5.3.2(6), Table 5.1) where alpha_cr < 10. Lateral-torsional "
    "buckling of I-sections (6.3.2.2, Table 6.4 curves; M_cr from an eigen analysis of each segment between "
    "lateral restraints with gravity loads on the top flange; Annex B Table B.2), unless lateral_restraint is "
    "'continuous'; hollow sections are not susceptible. Not checked: torsion.",
    "Preliminary design check, not an engineer's sign-off.",
]


def section_from_spec(spec: dict | None, diameter_mm=None, wall_mm=None) -> tuple[fs.Section, list[str]]:
    """Section from the bridge's SectionSpec (meters) or an explicit CHS override (mm)."""
    notes = []
    if diameter_mm:
        return fs.chs(float(diameter_mm), float(wall_mm or diameter_mm / 20)), notes
    spec = spec or {}
    shape = (spec.get("shape") or "circular_hollow").lower()
    to_mm = 1000.0
    try:
        if shape in ("rect", "rectangular", "solid_rectangle") and spec.get("height") and spec.get("width"):
            return fs.rect(spec["width"] * to_mm, spec["height"] * to_mm), notes      # solid: concrete, timber
        if shape in ("i", "i_section", "wide_flange", "h") and spec.get("height") and spec.get("width"):
            web, flange = spec.get("web"), spec.get("flange")
            if not (web and flange):
                raise ValueError("an I-section needs web and flange thicknesses")
            return fs.i_section(spec["height"] * to_mm, spec["width"] * to_mm, web * to_mm, flange * to_mm), notes
        if shape == "box" and spec.get("height") and spec.get("width"):
            t = spec.get("wall") or min(spec["height"], spec["width"]) / 10
            return fs.rhs(spec["height"] * to_mm, spec["width"] * to_mm, t * to_mm), notes
        if spec.get("diameter"):
            d = spec["diameter"] * to_mm
            t = (spec.get("wall") or spec["diameter"] / 20) * to_mm
            return fs.chs(d, t), notes
    except ValueError as exc:
        notes.append(f"Section {spec} rejected ({exc}); default CHS 114.3x4 used.")
    return fs.chs(114.3, 4.0), notes


CONNECTIONS = ("rigid", "simple")
_T, _F = True, False
SUPPORT_TYPES = {                                       # restrained DOFs (ux uy uz rx ry rz), global axes
    "fixed": (_T, _T, _T, _T, _T, _T), "pinned": (_T, _T, _T, _F, _F, _F), "pin": (_T, _T, _T, _F, _F, _F),
    "roller": (_F, _F, _T, _F, _F, _F),                 # vertical only: slides in plan
    "roller-x": (_F, _T, _T, _F, _F, _F),               # slides along x
    "roller-y": (_T, _F, _T, _F, _F, _F),               # slides along y
    "lateral-x": (_T, _F, _F, _F, _F, _F),              # lateral restraint: holds x only (bracing, a deck)
    "lateral-y": (_F, _T, _F, _F, _F, _F),              # lateral restraint: holds y only
    "spring": (_F,) * 6,                                # only the listed springs
}
SPRING_KEYS = ("kx", "ky", "kz", "rx", "ry", "rz")       # kN/m (translations), kNm/rad (rotations)


def parse_support(text: str) -> tuple[tuple, tuple, str]:
    """A support specification -> (restrained DOFs, spring stiffnesses, label).

    ``"<type> [key=value ...]"``: type is one of SUPPORT_TYPES; keys kx ky kz (kN/m) and rx ry rz
    (kNm/rad) add springs to ground in global axes, and a sprung DOF is no longer rigid. Examples:
    ``fixed``, ``roller-x``, ``spring kz=50000``, ``fixed rx=8000 ry=8000`` (semi-rigid base); ``lateral-y``
    holds one horizontal direction only (the out-of-plane restraint a planar truss gets from its deck or bracing).
    Raises ValueError for anything else."""
    words = str(text or "").replace(",", " ").lower().split()
    if not words or words[0] not in SUPPORT_TYPES:
        raise ValueError(f"unknown support type {text!r}")
    restraint, springs = list(SUPPORT_TYPES[words[0]]), [0.0] * 6
    for w in words[1:]:
        key, sep, value = w.replace(":", "=").partition("=")
        if not sep or key not in SPRING_KEYS:
            raise ValueError(f"unknown support setting {w!r}")
        k = float(value)
        if not (math.isfinite(k) and k >= 0):
            raise ValueError(f"spring {key} must be a non-negative number")
        d = SPRING_KEYS.index(key)
        springs[d], restraint[d] = k, False
    if not any(restraint) and not any(springs):
        raise ValueError("a spring support needs at least one stiffness, e.g. 'spring kz=50000'")
    label = "pinned" if words[0] == "pin" else words[0]
    extra = [f"{SPRING_KEYS[d]}={springs[d]:g}" for d in range(6) if springs[d]]
    return tuple(restraint), tuple(springs), " ".join([label] + extra)
WELD_RATIO = 2e-4          # points closer than this x the model's diagonal extent are one node
COLLINEAR_COS = 0.9995     # pieces meeting within ~1.8 degrees of a straight line are one member
STEEP_SIN = 0.7            # members at least ~45 degrees from horizontal support what they meet
RELEASES = ("rigid", "pinned", "pinned_start", "pinned_end", "bar", "hinged")
CURVE_SAGITTA_RATIO = 500  # a curved piece is analysed as chords within its arc length / this of the curve
MAX_CURVE_SEGMENTS = 24    # ...and at most this many straight elements per curved piece
MAX_CURVE_TURN = 0.1       # rad: ...and each chord turns at most this much (long, strongly curved runs)
SMOOTH_COS = math.cos(0.15)  # a polyline turning more than ~8.6 degrees at a vertex has a corner there (the
                           # bridge polylines curves with at most 0.1 rad per vertex)
DENSE_BUDGET_GB = 6.0      # memory the dense matrices may take: fixed, so the verdict is the model's alone
DENSE_COPIES = {"linear": 6, "stability": 10}   # measured peaks in n x n float64 matrices: assembly (K, K_ff,
                           # factor, inverse, index copies) 5.9; alpha_cr (+ K_G and its eigenproblem) 9.7
CURVE_FALLBACK_SEGMENTS = (8, 4, 2, 1)   # coarser curves, tried in turn when a model exceeds the budget


class ModelTooLargeError(ValueError):
    """The model needs more memory or time than the dense solver can give it."""
    def __init__(self, message, size):
        super().__init__(message)
        self.size = size


def _available_memory() -> float:
    """Free physical memory in bytes (0 when unknown)."""
    try:
        if sys.platform == "win32":
            import ctypes

            class _Status(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                    (k, ctypes.c_ulonglong) for k in ("total", "avail", "page_total", "page_avail", "virt_total",
                                                      "virt_avail", "ext")]
            s = _Status()
            s.length = ctypes.sizeof(_Status)
            return float(s.avail) if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s)) else 0.0
        return float(os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE"))
    except (AttributeError, OSError, ValueError):
        return 0.0


def max_dof(stage: str = "linear") -> int:
    """The most DOF a dense ``stage`` ("linear" or "stability") fits in DENSE_BUDGET_GB."""
    return int(math.sqrt(DENSE_BUDGET_GB * 1e9 / (8.0 * DENSE_COPIES[stage])))


def check_size(nodes: int, elements: int, stage: str = "linear", added: int = 0) -> dict:
    """Refuse a model the dense solver cannot handle within its budget, before assembling it: ``stage``
    "linear" (one stiffness factorisation) or "stability" (also geometric stiffness and its eigenvalues;
    ``added`` of the nodes come from refining the compressed members). Raises ModelTooLargeError
    carrying the size; returns the size, with the free memory for a warning, otherwise."""
    dof = 6 * int(nodes)
    need = DENSE_COPIES[stage] * 8.0 * dof ** 2
    free = _available_memory()
    size = {"nodes": int(nodes), "elements": int(elements), "dof": dof, "stage": stage,
            "memory_gb": round(need / 1e9, 2), "budget_gb": DENSE_BUDGET_GB, "max_dof": max_dof(stage),
            "free_memory_gb": round(free / 1e9, 2) if free else None}
    if dof <= max_dof(stage):
        return size
    what = f" ({added} added to refine compressed members for the stability check)" if added else ""
    hint = " or run with stability='off'" if stage == "stability" else ""
    raise ModelTooLargeError(
        f"Model too large for the dense solver: {nodes} nodes / {elements} elements{what} = {dof} DOF, needing about "
        f"{need / 1e9:.1f} GB against its {DENSE_BUDGET_GB:g} GB budget (at most {max_dof(stage)} DOF for the "
        f"{stage} analysis). Analyse fewer members at a time{hint}.", size)


def _memory_warning(size: dict) -> list[str]:
    free = size.get("free_memory_gb")
    if free and size["memory_gb"] > 0.8 * free:
        return [f"The analysis needs about {size['memory_gb']:.1f} GB and {free:.1f} GB is free now: it may be slow "
                "(swapping). Close other programs if it takes long."]
    return []


def _turns(P: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(cos, sin) of the turning angle at every interior vertex of a polyline (zero-length legs: straight)."""
    d = np.diff(P, axis=0)
    seg = np.linalg.norm(d, axis=1)
    u = d / np.where(seg > 0, seg, 1.0)[:, None]
    cos = np.einsum("ij,ij->i", u[:-1], u[1:])
    sin = np.linalg.norm(np.cross(u[:-1], u[1:]), axis=1)
    flat = (seg[:-1] == 0) | (seg[1:] == 0)
    return np.where(flat, 1.0, cos), np.where(flat, 0.0, sin)


def _resample(P: np.ndarray, eps: float, max_segments: int) -> np.ndarray | None:
    """Points at equal arc length along the polyline P: the fewest chords (at most max_segments) that keep
    every vertex of P within eps and turn at most MAX_CURVE_TURN each; None when that needs as many
    chords as P already has."""
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    total = float(s[-1])
    if total <= 0:
        return None
    cos, sin = _turns(P)
    turn = float(np.sum(np.arctan2(sin, cos)))
    for n in range(min(max(1, math.ceil(turn / MAX_CURVE_TURN - 1e-9)), max_segments), max_segments + 1):
        if n >= len(P) - 1:
            return None
        Q = np.stack([np.interp(np.linspace(0.0, total, n + 1), s, P[:, k]) for k in range(3)], axis=1)
        j = np.minimum((s / (total / n)).astype(int), n - 1)    # the chord each vertex lies along
        a, c = Q[j], Q[j + 1] - Q[j]
        L2 = np.einsum("ij,ij->i", c, c)
        t = np.clip(np.einsum("ij,ij->i", P - a, c) / np.where(L2 > 0, L2, 1.0), 0.0, 1.0)
        if float(np.max(np.linalg.norm(P - a - t[:, None] * c, axis=1))) <= eps or n == max_segments:
            return Q
    return None


def simplify_curve(points: list, keep=(), ratio: float | None = CURVE_SAGITTA_RATIO,
                   max_segments: int = MAX_CURVE_SEGMENTS) -> tuple[list, set]:
    """The analysis discretisation of one polylined member piece: (points, joints), joints = the indices
    in the returned points where one smooth run ends (besides the two ends).

    The polyline is cut into smooth runs at the vertex indices in ``keep`` (other members, supports),
    at corners (turning more than ~8.6 degrees, SMOOTH_COS: a polyline drawn with corners) and where it runs straight
    on (a node drawn on purpose; a polylined smooth curve turns at every vertex). Each smooth run is
    resampled at equal arc length into the fewest chords, at most ``max_segments``, that stay within its
    arc length / ``ratio`` of the drawn polyline. Equal chords keep loads and stiffness evenly spread.
    The ends and run boundaries are the original point objects. ``ratio`` 0 or None keeps every vertex."""
    n = len(points)
    if n <= 2:
        return list(points), set()
    P = np.asarray(points, float)
    cos, sin = _turns(P)
    cuts = sorted({0, n - 1} | {int(k) for k in keep}
                  | {int(i) + 1 for i in np.flatnonzero((sin < 1e-6) | (cos < SMOOTH_COS))})
    out, joints = [points[0]], set()
    for i, j in zip(cuts, cuts[1:]):
        Q = _resample(P[i:j + 1], float(np.sum(np.linalg.norm(np.diff(P[i:j + 1], axis=0), axis=1))) / ratio,
                      max_segments) if ratio and j - i > 1 else None
        out += [points[k] for k in range(i + 1, j)] if Q is None else [[float(v) for v in q] for q in Q[1:-1]]
        out.append(points[j])
        if j != n - 1:
            joints.add(len(out) - 1)
    return out, joints


class _Grid:
    """Points by cell of side ``h``: the points within h of a query are in the 27 cells around it."""
    def __init__(self, h: float):
        self.h, self.cells = float(h), {}

    def _cell(self, p):
        return tuple(int(math.floor(v / self.h)) for v in p)

    def add(self, p, item):
        self.cells.setdefault(self._cell(p), []).append((p, item))

    def near(self, p, r=None):
        """Items whose point lies within r (default h) of p, in insertion order."""
        r = self.h if r is None else r
        cx, cy, cz = self._cell(p)
        reach = max(1, int(math.ceil(r / self.h)))
        found = []
        for dx in range(-reach, reach + 1):
            for dy in range(-reach, reach + 1):
                for dz in range(-reach, reach + 1):
                    found += [(q, it) for q, it in self.cells.get((cx + dx, cy + dy, cz + dz), ()) if math.dist(p, q) <= r]
        return found


def _member_ends(model: dict, tol: float) -> list:
    """Per member: (start point, end point) of its drawn curve. Uses the bridge's curve_start_m /
    curve_end_m; otherwise the endpoints that occur once among the pieces sharing its first GUID
    (start/end order unknown then: None)."""
    counts: dict = {}
    for m in model.get("members", []):
        pts = m.get("points") or []
        g = (m.get("source_guids") or [""])[0]
        for q in (pts[0], pts[-1]) if pts else ():
            key = (g, tuple(round(v / max(tol, 1e-6)) for v in q))
            counts[key] = counts.get(key, 0) + 1
    ends = []
    for m in model.get("members", []):
        if m.get("curve_start_m") and m.get("curve_end_m"):
            ends.append((m["curve_start_m"], m["curve_end_m"], True))
            continue
        pts = m.get("points") or []
        g = (m.get("source_guids") or [""])[0]
        free = [q for q in ((pts[0], pts[-1]) if pts else ())
                if counts[(g, tuple(round(v / max(tol, 1e-6)) for v in q))] == 1]
        ends.append((free[0] if free else None, free[1] if len(free) > 1 else None, False))
    return ends


def _continued(model: dict, tol: float) -> dict:
    """{(member index, 0 start | 1 end): True} where another member carries on in line (within 5
    degrees) from that end, i.e. the drawn pieces form one continuous member."""
    ends = []
    for i, m in enumerate(model.get("members", [])):
        pts = m.get("points") or []
        if len(pts) < 2:
            continue
        for which, (a, b) in ((0, (pts[0], pts[1])), (1, (pts[-1], pts[-2]))):
            d = np.subtract(b, a)
            n = float(np.linalg.norm(d))
            if n > 0:
                ends.append((i, which, np.asarray(a, float), d / n))
    reach = max(tol, 1e-3)
    grid = _Grid(reach)
    for i, _, p, d in ends:
        grid.add(tuple(p), (i, d))
    return {(i, w): any(j != i and float(d @ e) < -0.996 for _, (j, e) in grid.near(tuple(p)))
            for (i, w, p, d) in ends}


def _group(frame, run: list) -> None:
    """The chords of one smooth curved run are one member (EN 1993 checks, stability refinement)."""
    if len(run) > 1:
        for ei in run:
            frame.elements[ei].group = run[0]


def _orientation(m: dict) -> str:
    pts = m.get("points") or []
    if len(pts) < 2:
        return "beam"
    d = np.subtract(pts[-1], pts[0])
    L = float(np.linalg.norm(d))
    slope = abs(d[2]) / L if L > 0 else 0.0
    return "column" if slope > 0.98 else ("beam" if slope < 0.05 else "brace")


def _release_ends(m: dict, connections: str) -> tuple[bool, bool, str, bool]:
    """(release at curve start, at curve end, source, release minor axis too) for one member.
    Beams release major-axis bending only; braces both axes; columns stay continuous."""
    kind = _orientation(m)
    minor = kind != "beam"
    user = (m.get("release") or "").strip().lower()
    if user == "bar":                                   # pin-jointed bar: axial only (both axes released)
        return True, True, "user", True
    if user == "hinged":                                # in-plane hinges: major axis only, plan bending continuous
        return True, True, "user", False
    if user in RELEASES:
        return user in ("pinned", "pinned_start"), user in ("pinned", "pinned_end"), "user", minor
    if connections == "simple" and kind != "column":
        return True, True, "simple", minor
    return False, False, "rigid", minor


def _finite_parameter(value, label, *, positive=False, nonnegative=False):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be a finite number.") from exc
    if isinstance(value, bool) or not math.isfinite(number) or (positive and number <= 0) or (nonnegative and number < 0):
        qualifier = "positive " if positive else "non-negative " if nonnegative else ""
        raise ValueError(f"{label} must be a finite {qualifier}number.")
    return number


MODEL_LOAD_CASES = ("G", "Q")


def _apply_model_loads(frame: fs.Frame, model: dict, member_elements: dict, tol: float) -> tuple[dict, list[str]]:
    """Explicit loads carried by the model (``model["loads"]``): the structural reference library's
    benchmark loads today, point loads declared in Rhino tomorrow. Each entry is one of

    - ``{"point_m": [x, y, z], "force_kn": [fx, fy, fz], "moment_knm": [mx, my, mz], "case": "Q"}``:
      a nodal load at the nearest node (within 50 mm, else ignored with a warning);
    - ``{"member": i, "w_start_kn_m": [wx, wy, wz], "w_end_kn_m": [...], "case": "G"}``: a line load
      (global kN/m) along model member ``i``, uniform when ``w_end`` is omitted, otherwise varying
      linearly from the member's first drawn point to its last; applied to every piece of the member.

    ``case`` is G (permanent) or Q (variable; the default). Returns ({"count", "nodal", "member",
    "nodes"}, warnings)."""
    out = {"count": 0, "nodal": 0, "member": 0, "nodes": []}
    notes = []
    loads = model.get("loads") or []
    if not isinstance(loads, list):
        raise ValueError("model['loads'] must be a list of load entries.")
    X = np.asarray(frame.nodes, float) if frame.nodes else np.zeros((0, 3))
    members = model.get("members") or []
    for k, load in enumerate(loads):
        if not isinstance(load, dict):
            raise ValueError(f"Load {k} must be an object.")
        case = str(load.get("case") or "Q").strip().upper()
        if case not in MODEL_LOAD_CASES:
            raise ValueError(f"Load {k}: case must be G (permanent) or Q (variable), not {load.get('case')!r}.")
        if load.get("point_m") is not None:
            p = np.asarray(load["point_m"], float)
            if p.shape != (3,) or not np.all(np.isfinite(p)):
                raise ValueError(f"Load {k}: point_m must be three finite coordinates in metres.")
            d = np.linalg.norm(X - p, axis=1)
            i = int(np.argmin(d))
            if d[i] > max(tol, 0.05):
                notes.append(f"Load {k} at {tuple(round(v, 3) for v in p)} is {d[i]:.3f} m from the nearest node "
                             "and was ignored.")
                continue
            force = load.get("force_kn") or (0.0, 0.0, 0.0)
            moment = load.get("moment_knm") or (0.0, 0.0, 0.0)
            if len(force) != 3 or len(moment) != 3:
                raise ValueError(f"Load {k}: force_kn and moment_knm must have three components.")
            frame.load(i, *[float(v) for v in force], *[float(v) for v in moment], case=case)
            out["nodes"].append(i)
            out["nodal"] += 1
        elif load.get("member") is not None:
            try:
                mi = int(load["member"])
            except (TypeError, ValueError):
                raise ValueError(f"Load {k}: member must be a model member index.") from None
            if mi not in member_elements:
                notes.append(f"Load {k}: member {mi} has no analysed piece; the load was ignored.")
                continue
            wa = load.get("w_start_kn_m", load.get("w_kn_m"))
            if wa is None:
                raise ValueError(f"Load {k}: a member load needs w_start_kn_m (or w_kn_m) in kN/m.")
            wb = load.get("w_end_kn_m", wa)
            wa, wb = np.asarray(wa, float), np.asarray(wb, float)
            if wa.shape != (3,) or wb.shape != (3,) or not (np.all(np.isfinite(wa)) and np.all(np.isfinite(wb))):
                raise ValueError(f"Load {k}: member loads are three finite components (global kN/m).")
            pts = members[mi].get("points") or []
            p0, p1 = np.asarray(pts[0], float), np.asarray(pts[-1], float)
            chord = float(np.linalg.norm(p1 - p0))
            for ei in member_elements[mi]:
                e = frame.elements[ei]
                if chord <= tol or np.allclose(wa, wb):
                    frame.udl(ei, wa, case)
                    continue
                ta = float(np.dot(X[e.n1] - p0, p1 - p0) / chord ** 2)
                tb = float(np.dot(X[e.n2] - p0, p1 - p0) / chord ** 2)
                frame.linear_load(ei, wa + ta * (wb - wa), wa + tb * (wb - wa), case)
            out["member"] += 1
        else:
            raise ValueError(f"Load {k}: give point_m (nodal load) or member (line load).")
        out["count"] += 1
    out["nodes"] = sorted(set(out["nodes"]))
    return out, notes


def build_frame(model: dict, load_kn: float, material: str = "Steel", fixed_supports: bool = True,
                self_weight: bool = True, diameter_mm=None, wall_mm=None, asset_loads: dict | None = None,
                floor_loads: dict | None = None, connections: str = "rigid",
                curve_ratio: float | None = CURVE_SAGITTA_RATIO, max_curve_segments: int = MAX_CURVE_SEGMENTS):
    """``asset_loads``: {"placements": [...], "table": LoadTable, "catalogue": {...}} adds the
    gravity loads of placed library assets (see asset_loads.apply); its report is info["asset_loads"].
    ``floor_loads``: {"imposed": kN/m2, "dead": kN/m2, "levels": [z m] | None} loads every enclosed
    floor bay (see floor_loads.apply); its report is info["floor_loads"].
    ``connections``: "rigid" or "simple" (see module notes); per-member ``release`` overrides.
    ``curve_ratio`` / ``max_curve_segments``: a curved member piece (the bridge polylines curves to the
    document tolerance, often dozens of vertices) is analysed as at most that many chords within its
    arc length / curve_ratio of the curve (see simplify_curve); None keeps every vertex. The chords of
    one smooth run form one member for the EN 1993 checks (buckling length = the run between joints).
    All coordinates in meters (the bridge's exported conditioned model)."""
    load_kn = _finite_parameter(load_kn, "load_kn", nonnegative=True)
    if diameter_mm is not None:
        diameter_mm = _finite_parameter(diameter_mm, "diameter_mm", positive=True)
    if wall_mm is not None:
        wall_mm = _finite_parameter(wall_mm, "wall_mm", positive=True)
    for key in ("tolerance_m", "max_span_m", "max_member_span_m"):
        if model.get(key) is not None:
            _finite_parameter(model[key], key, nonnegative=True)
    connections = (connections or "rigid").lower()
    if connections not in CONNECTIONS:
        raise ValueError("connections must be 'rigid' or 'simple'.")
    mat = fs.material(material)
    tol = max(float(model.get("tolerance_m") or 0.0), 1e-6)
    frame = fs.Frame()
    warnings = []
    # weld points closer than a small fraction of the model size: a member piece of a few mm next to
    # members of many metres leaves the stiffness matrix too ill-conditioned to solve (false mechanism)
    pts_all = [p for m in model.get("members", []) for p in (m.get("points") or [])]
    extent = float(np.linalg.norm(np.ptp(np.asarray(pts_all, float), axis=0))) if pts_all else 0.0
    weld = max(tol, WELD_RATIO * extent)
    grid = _Grid(weld)

    def node(p):                                        # the first node within the weld distance, else a new one
        near = grid.near(p)
        if near:
            return min(i for _, i in near)
        i = frame.add_node(p)
        grid.add(frame.nodes[i], i)
        return i

    # vertices a curve simplification must keep: other members' ends and declared supports on a curve
    joints = _Grid(weld)
    for m in model.get("members", []):
        pts = m.get("points") or []
        for q in pts[:1] + pts[-1:]:
            joints.add(q, None)
    declared_points = [s.get("point_m") or s.get("point") for s in model.get("supports") or []]
    load_points = [ld["point_m"] for ld in (model.get("loads") or []) if isinstance(ld, dict)
                   and isinstance(ld.get("point_m"), (list, tuple)) and len(ld["point_m"]) == 3
                   and all(isinstance(v, (int, float)) and math.isfinite(v) for v in ld["point_m"])]
    for p in declared_points + list(model.get("anchor_points") or []) + load_points:   # explicit point loads too
        if p is not None:
            joints.add(p, None)
    drawn_vertices, curved_pieces = 0, 0
    joint_nodes, curve_nodes = set(), set()

    lineage = []
    member_elements: dict = {}                              # model member index -> its elements
    pinned_ends, user_members, unordered, welded = 0, 0, 0, 0
    cont = _continued(model, tol) if connections == "simple" else {}
    for mi, (m, (c0, c1, ordered)) in enumerate(zip(model.get("members", []), _member_ends(model, tol))):
        sec, notes = section_from_spec(m.get("section"), diameter_mm, wall_mm)
        warnings += notes
        rel0, rel1, source, minor = _release_ends(m, connections)
        user_members += source == "user"
        if source == "user" and rel0 != rel1 and not ordered:
            unordered += 1
            rel0 = rel1 = True                                  # direction unknown: pin both ends
        pts = m.get("points") or []
        breaks = set()                                          # vertices where one smooth run ends
        if len(pts) > 2:
            drawn = len(pts)
            pts, breaks = simplify_curve(pts, {k for k in range(1, drawn - 1) if joints.near(pts[k])},
                                         curve_ratio, max_curve_segments)
            if len(pts) < drawn:
                drawn_vertices += drawn
                curved_pieces += 1
        run = []                                                # elements of the current smooth run
        for v, (a, b) in enumerate(zip(pts, pts[1:])):
            if v in breaks:
                _group(frame, run)
                run = []
            if math.dist(a, b) <= tol:
                continue
            at = lambda q, c: c is not None and math.dist(q, c) <= max(tol, 1e-3)
            if source == "simple":
                # pin only where the member stops: not at a joint where it carries on in line
                ra = a is pts[0] and not cont.get((mi, 0), False)
                rb = b is pts[-1] and not cont.get((mi, 1), False)
            else:
                ra = (rel0 and at(a, c0)) or (rel1 and at(a, c1))
                rb = (rel0 and at(b, c0)) or (rel1 and at(b, c1))
            na, nb = node(a), node(b)
            for n_, at_ in ((na, v), (nb, v + 1)):             # drawn joints vs vertices along a curve
                (joint_nodes if at_ in (0, len(pts) - 1) or at_ in breaks else curve_nodes).add(n_)
            if na == nb:                                        # shorter than the weld distance
                welded += 1
                continue
            ei = frame.add_element(na, nb, sec, mat, tag=list(m.get("source_guids", [])),
                                   releases=fs.release_mask(ra, rb, minor))
            pinned_ends += int(ra) + int(rb)
            lineage.append(ei)
            run.append(ei)
            member_elements.setdefault(mi, []).append(ei)
        _group(frame, run)
    if curved_pieces:
        warnings.append(f"{curved_pieces} curved member piece(s) drawn with {drawn_vertices} polyline vertices were "
                        f"analysed as chords within 1/{curve_ratio:g} of their length (at most {max_curve_segments} "
                        "per piece).")
    if welded:
        warnings.append(f"{welded} member piece(s) shorter than {weld * 1000:.1f} mm were collapsed into a single "
                        "joint (points this close are one node for the analysis).")
    if unordered:
        warnings.append(f"{unordered} member(s) asked for a one-sided release but the curve direction is "
                        "unknown (update almondbridge); both ends were pinned.")
    if not frame.elements:
        raise ValueError("No line members to analyse.")

    default = "fixed" if fixed_supports else "pinned"
    # typed support points first, then plain anchor points that no typed point already covers
    declared = [(s.get("point_m") or s.get("point"), s.get("spec")) for s in model.get("supports") or []]
    declared = [(p, spec) for p, spec in declared if p is not None]
    declared += [(p, None) for p in model.get("anchor_points") or []
                 if not any(math.dist(p, q) <= max(tol, 1e-6) for q, _ in declared)]
    chosen: dict = {}                                   # node -> (restraint, springs, label)
    X = np.asarray(frame.nodes)
    for p, spec in declared:
        d = np.linalg.norm(X - np.asarray(p), axis=1)
        i = int(np.argmin(d))
        if d[i] > max(tol, 0.05):
            warnings.append(f"Support point {tuple(round(v, 3) for v in p)} is {d[i]:.3f} m from "
                            "the nearest node and was ignored.")
            continue
        try:
            sup = parse_support(spec or default)
        except ValueError as exc:
            warnings.append(f"Support '{spec}' at {tuple(round(v, 3) for v in p)} not understood ({exc}); the default "
                            f"({default}) was used. Types: fixed, pinned, roller, roller-x, roller-y, lateral-x, lateral-y, "
                            "spring kz=...")
            sup = parse_support(default)
        if i in chosen and chosen[i][2] != sup[2]:
            warnings.append(f"Two supports ({chosen[i][2]}, {sup[2]}) land on the node at "
                            f"{tuple(round(v, 3) for v in frame.nodes[i])}; both restraints apply.")
            old = chosen[i]
            sup = (tuple(a or b for a, b in zip(old[0], sup[0])), tuple(max(a, b) for a, b in zip(old[1], sup[1])),
                   f"{old[2]} + {sup[2]}")
        chosen[i] = sup
    if not chosen:
        zmin = min(p[2] for p in frame.nodes)
        chosen = {i: parse_support(default) for i, p in enumerate(frame.nodes) if p[2] <= zmin + tol}
        warnings.append(f"No anchor points declared; supporting {len(chosen)} lowest-Z node(s).")
    support_nodes = sorted(chosen)
    for n in support_nodes:
        restraint, springs, _ = chosen[n]
        frame.fix(n, restraint)                         # all False for a pure spring: still a support node
        if any(springs):
            frame.spring(n, *springs)

    # load_kn: equal shares at the free joints (where members meet or end, not the vertices along a curve,
    # whose number is only a matter of discretisation); only curves between supports (a lone arch): spread
    # evenly along the members; nothing free: every node
    free = [i for i in range(len(frame.nodes)) if i not in support_nodes]
    joints_free = [n for n in free if n not in curve_nodes - joint_nodes]
    if joints_free or not free:
        free = joints_free or list(range(len(frame.nodes)))
        if load_kn > 0:
            for n in free:
                frame.load(n, fz=-load_kn / len(free), case="Q")
    elif load_kn > 0:
        X = np.asarray(frame.nodes, float)
        lengths = [float(np.linalg.norm(X[e.n2] - X[e.n1])) for e in frame.elements]
        for ei in range(len(frame.elements)):
            frame.udl(ei, (0.0, 0.0, -load_kn / sum(lengths)), case="Q")
    explicit, explicit_notes = _apply_model_loads(frame, model, member_elements, tol)
    warnings += explicit_notes
    if self_weight:
        frame.gravity = (0.0, 0.0, -1.0)
    loaded = sorted(set(free if load_kn > 0 else []) | set(explicit["nodes"]))
    info = {"support_nodes": support_nodes, "support_labels": {n: chosen[n][2] for n in support_nodes},
            "curved_pieces": curved_pieces,
            "loaded_nodes": loaded, "material": mat,
            "connections": {"mode": connections, "pinned_ends": pinned_ends, "user_released_members": user_members}}
    if explicit["count"]:
        info["model_loads"] = {k: v for k, v in explicit.items() if k != "nodes"}
    if floor_loads and (floor_loads.get("imposed") or floor_loads.get("dead")):
        info["floor_loads"] = fl.apply(frame, floor_loads.get("imposed", 0.0), floor_loads.get("dead", 0.0),
                                       floor_loads.get("levels"))
        warnings += info["floor_loads"]["warnings"]
    if asset_loads:
        report = al.apply(frame, asset_loads["placements"], asset_loads["table"], asset_loads.get("catalogue") or {})
        info["asset_loads"] = report
        info["loaded_nodes"] = sorted(set(info["loaded_nodes"]) | set(report["loaded_nodes"]))
    return frame, info, warnings


SLS = ("SLS characteristic", {"G": 1.0, "Q": 1.0})


def design_profile(design_basis: str = "en1990", design_code=None) -> dc.Profile:
    """The design code profile in force: design_basis="unfactored" means no code ("off")."""
    basis = (design_basis or "en1990").lower()
    if basis not in ("en1990", "unfactored"):
        raise ValueError("design_basis must be 'en1990' or 'unfactored'.")
    return dc.OFF_PROFILE if basis == "unfactored" else dc.load(design_code)


def combinations(design_basis: str = "en1990", uls: str | None = None, design_code=None) -> tuple[tuple, list]:
    """(SLS combination, [ULS combinations]) as (name, {case: factor}), factors from the design code profile."""
    if uls not in (None, "", "6.10", "6.10ab"):
        raise ValueError("uls_combination must be '6.10' or '6.10ab'.")
    code = design_profile(design_basis, design_code)
    if not code.factored:
        return SLS, [("Unfactored", {"G": 1.0, "Q": 1.0})]
    expression, _ = code.uls(uls or None)
    gG, gQ = code.gamma_G, code.gamma_Q
    if expression == "6.10":
        return SLS, [("ULS 6.10", {"G": gG, "Q": gQ})]
    return SLS, [("ULS 6.10a", {"G": gG, "Q": round(code.psi_0 * gQ, 6)}),
                 ("ULS 6.10b", {"G": round(code.xi * gG, 6), "Q": gQ})]


INDICATIVE_FAMILIES = {
    "timber": "EN 1995 (k_mod, gamma_M, creep)",
    "concrete": "EN 1992 (cracking, reinforcement, gamma_c / gamma_s)",
    "aluminium": "EN 1999 (alloy buckling classes, gamma_M1 = 1.1)",
}


def _class4_hint(shape: str, mat) -> str:
    """How to get a section of this family out of Class 4 (EN 1993-1-1 Table 5.2, Class 3 limits)."""
    eps = ec3.epsilon(mat.fy)
    grade = f"{mat.name}, epsilon = {eps:.2f}"
    if shape == "chs":
        return f"Use thicker walls: a CHS is Class 4 beyond d/t = 90 x 235/fy = {90 * eps ** 2:.1f} ({grade})."
    if shape == "rhs":
        return (f"Use thicker walls or a narrower box: an RHS wall is Class 4 beyond c/t = 42 epsilon = "
                f"{42 * eps:.1f} in compression, up to 124 epsilon = {124 * eps:.1f} in pure bending "
                f"(c = side - 3t; {grade}).")
    if shape == "i":
        return (f"Use a stockier I section: Class 4 beyond a flange outstand c/tf = 14 epsilon = {14 * eps:.1f}, or a "
                f"web c/tw = 42 epsilon = {42 * eps:.1f} in compression, up to 124 epsilon = {124 * eps:.1f} in "
                f"bending ({grade}).")
    return "Use a stockier section: thicker plates make the section Class 3 or better."


def _code_warnings(code: dc.Profile, uls, info: dict) -> list[str]:
    """Honest notes about the design basis: unverified profile values, overridden choices, materials
    the member checks do not cover."""
    out = []
    if code.unverified:
        out.append(f"Design code '{code.name}': {len(code.unverified)} value(s) not yet verified against the "
                   f"published document ({', '.join(code.unverified)}). Treat the results as provisional.")
    if code.factored:
        note = code.uls(uls or None)[1]
        if note:
            out.append(note)
    family = info["material"].family
    if family in INDICATIVE_FAMILIES:
        out.append(f"{info['material'].name} results are indicative only: {INDICATIVE_FAMILIES[family]} is not "
                   "applied, and utilization uses the characteristic strength without material factors.")
    return out


DOF_NAMES = ("Fx", "Fy", "Fz", "Mx", "My", "Mz")


def _r(v, digits):
    return None if v is None else round(float(v), digits)


def _fabrication(value) -> str:
    v = (value or "cold_formed").lower().replace("-", "_").replace(" ", "_")
    if v not in ec3.FABRICATION:
        raise ValueError("fabrication must be 'cold_formed' or 'hot_finished'.")
    return v


def _lateral_restraint(value) -> str:
    v = (value or "joints").lower()
    if v not in ec3.LATERAL_RESTRAINT:
        raise ValueError("lateral_restraint must be 'joints' or 'continuous'.")
    return v


def _role(a, b) -> str:
    d = np.asarray(b, float) - np.asarray(a, float)
    L = float(np.linalg.norm(d)) or 1.0
    vertical = abs(d[2]) / L
    return "column" if vertical > 0.9 else "beam" if vertical < 0.1 else "brace"


def _member_groups(frame) -> list[list[int]]:
    """Elements forming one structural member: the pieces of one drawn curve (same source GUIDs) and
    pieces that carry on in a straight line through a joint (a beam drawn bay by bay, a column drawn
    storey by storey)."""
    X = np.asarray(frame.nodes, float)
    parent = list(range(len(frame.elements)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    by_tag, at = {}, {}
    for i, e in enumerate(frame.elements):
        if e.tag:
            j = by_tag.setdefault(tuple(e.tag), i)
            parent[find(i)] = find(j)
        d = X[e.n2] - X[e.n1]
        d = d / (np.linalg.norm(d) or 1.0)
        at.setdefault(e.n1, []).append((i, d))
        at.setdefault(e.n2, []).append((i, -d))
    for ends in at.values():
        for k, (i, di) in enumerate(ends):
            for j, dj in ends[k + 1:]:
                if float(di @ dj) < -COLLINEAR_COS:
                    parent[find(i)] = find(j)
    groups: dict = {}
    for i in range(len(frame.elements)):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def _support_paths(frame):
    """(steep, supported, reach): steep[node] = [(lower node, element)] along members at least ~45 degrees
    from horizontal; the vertically supported nodes; and every node with a path down such members to one
    of them (a column stack on its foundation, a diagrid node)."""
    X = np.asarray(frame.nodes, float)
    down: dict = {}
    for i, e in enumerate(frame.elements):
        d = X[e.n2] - X[e.n1]
        L = float(np.linalg.norm(d))
        if L > 0 and abs(d[2]) / L >= STEEP_SIN:
            hi, lo = (e.n1, e.n2) if d[2] < 0 else (e.n2, e.n1)
            down.setdefault(hi, []).append((lo, i))
    supported = {n for n in frame.supports if frame.vertically_supported(n)}
    reach = set(supported)
    for n in sorted(range(len(X)), key=lambda k: X[k, 2]):   # lower nodes first
        if any(lo in reach for lo, _ in down.get(n, [])):
            reach.add(n)
    return down, supported, reach


def _group_geometry(frame, groups, down, reach):
    """Per member group: its elements, nodes, end point a, unit axis a -> b, its extent along that axis
    (``t``), whether it is steep, and the nodes where it is held in place by the rest of the structure: a
    support; a steep member of another group leading down to a support (a brace, the column below); or a
    joint whose floor (the network of non-steep members through it) reaches another member's support path
    (a floor tying the columns together). A cantilever arm on a lone post does not hold the post."""
    X = np.asarray(frame.nodes, float)
    els = frame.elements
    parent = list(range(len(X)))                        # components of the non-steep (floor) network

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k
    for e in els:
        d = X[e.n2] - X[e.n1]
        L = float(np.linalg.norm(d))
        if L > 0 and abs(d[2]) / L < STEEP_SIN:
            parent[find(e.n1)] = find(e.n2)
    anchored: dict = {}                                 # floor component -> its nodes on a support path
    for n in reach:
        anchored.setdefault(find(n), set()).add(n)
    out = []
    for g in groups:
        members = set(g)
        nodes = sorted({n for i in g for n in (els[i].n1, els[i].n2)})
        P = X[nodes]
        a = P[int(np.argmax(np.linalg.norm(P - P[0], axis=1)))]
        b = P[int(np.argmax(np.linalg.norm(P - a, axis=1)))]
        axis = (b - a) / (np.linalg.norm(b - a) or 1.0)
        tn = (P - a) @ axis
        mine = set(nodes)
        held = [n for n in nodes if n in frame.supports
                or any(lo in reach and i not in members for lo, i in down.get(n, []))
                or anchored.get(find(n), set()) - mine]
        out.append({"els": g, "members": members, "nodes": nodes, "a": a, "axis": axis, "held": held,
                    "steep": abs(float(axis[2])) >= STEEP_SIN, "t": (float(tn.min()), float(tn.max()))})
    return out


def member_deflections(frame, res) -> list[np.ndarray]:
    """Deflection at every station of every element (m); see member_deflection_spans."""
    return member_deflection_spans(frame, res)[0]


def member_deflection_spans(frame, res) -> tuple[list[np.ndarray], list[np.ndarray]]:
    """(deflections, spans): at every station of every element (m), the deflection and the span it is
    checked against.

    The deflection is the displacement across the member relative to what supports it, which is what a
    span/limit check reads (not the absolute displacement, which in a tall frame is mostly column
    shortening and sway). A member is supported where it meets a support or a steep member (about 45
    degrees or more) that leads down to one: a beam on columns, a truss chord at its end posts, a floor
    beam on a diagrid. Between supporting points the reference displacement is interpolated, beyond the
    last one (a cantilever) it is that point's translation, so root rotation counts as deflection. A
    member resting on other members (a secondary beam on girders) is measured from their deflected
    positions, so their deflection adds to its own. Movement along the member's axis is not deflection.
    A steep member (column, brace, diagrid bar) held at two or more points (supports or joints with
    other members, e.g. the floors along a column) bends between them: its deflection is measured from
    the chord through those points' actual displacements, so the storey's sway (rigid-body translation
    and rotation of the column) is not deflection; it is the storey drift (``storey_drift``). Only a
    steep member held at one point (a free-standing post) is measured as a cantilever from its root.

    The span is the member's own: the distance between the two points it is measured from on either side
    of the station, along the member (one drawn curve or line and the pieces that carry on in line from
    it, however it was split at joints; for a column between floors, the storey height); beyond its last
    one (a cantilever) twice the overhang; a member supported nowhere: its length."""
    X = np.asarray(frame.nodes, float)
    U = res.displacements[:, :3]
    els = frame.elements
    down, supported, reach = _support_paths(frame)
    groups = _member_groups(frame)
    info = _group_geometry(frame, groups, down, reach)
    for g in info:
        g["own"] = [n for n in g["nodes"]
                    if n in supported or any(lo in reach and i not in g["members"] for lo, i in down.get(n, []))]
    base = {n: U[n] for n in reach}                     # supported points move with their support path
    out = [np.zeros(len(res.elements[i].stations)) for i in range(len(els))]
    spans = [np.zeros(len(res.elements[i].stations)) for i in range(len(els))]
    done = [False] * len(groups)

    def measure(gi, refs, chord=False):
        g = info[gi]
        ts = np.array([(X[n] - g["a"]) @ g["axis"] for n in refs])
        order = np.argsort(ts)
        ts = ts[order]
        vs = np.array([U[refs[k]] if chord else base[refs[k]] for k in order])
        u = np.unique(np.round(ts, 9))
        # span per interval: left overhang (x2), the gaps between supports, right overhang (x2)
        gaps = np.concatenate([[2 * (u[0] - g["t"][0])], np.diff(u), [2 * (g["t"][1] - u[-1])]])
        cand = {}
        for i in g["els"]:
            er = res.elements[i]
            t = (er.stations - g["a"]) @ g["axis"]
            ref = np.stack([np.interp(t, ts, vs[:, k]) for k in range(3)], axis=1)   # clamped beyond the ends
            rel = er.disp - ref
            ax = g["axis"]
            if chord:                                    # the piece's own axis: a gently curved column line
                d = X[els[i].n2] - X[els[i].n1]
                ax = d / (np.linalg.norm(d) or 1.0)
            perp = rel - np.outer(rel @ ax, ax)
            out[i] = np.linalg.norm(perp, axis=1)
            k = np.searchsorted(u, t, side="right")     # a station on a support: the span after it, except
            k = np.where((k == len(u)) & (t <= u[-1] + 1e-9), len(u) - 1, k)    # on the last support
            spans[i] = gaps[k]
            for n, s in ((els[i].n1, 0), (els[i].n2, -1)):
                if n not in base and (n not in cand or out[i][s] > np.linalg.norm(U[n] - cand[n])):
                    cand[n] = er.disp[s] - perp[s]
        return cand

    first = True
    while True:
        new = {}
        for gi, g in enumerate(info):
            if done[gi]:
                continue
            chord = first and g["steep"] and len(g["held"]) >= 2
            refs = g["held"] if chord else g["own"] if first else [n for n in g["nodes"] if n in base]
            if not refs:
                continue
            done[gi] = True
            for n, v in measure(gi, refs, chord).items():
                if n not in new or np.linalg.norm(U[n] - v) > np.linalg.norm(U[n] - new[n]):
                    new[n] = v                           # the larger deflection governs a shared point
        if not new and not first:
            break
        base.update(new)
        first = False
    for gi, g in enumerate(info):                        # not connected to any support path: absolute
        if not done[gi]:
            for i in g["els"]:
                out[i] = np.linalg.norm(res.elements[i].disp, axis=1)
                spans[i] = np.full(len(out[i]), g["t"][1] - g["t"][0])
    return out, spans


DRIFT_EXEMPT_TYPES = ("truss",)   # a spanning truss's posts turn with it: that is bending, not storey sway


def storey_drift(frame, res, limit_ratio: float) -> dict:
    """Storey drift (EN 1990 A1.4.3, Figure A1.2: u_i over the storey height H_i): the horizontal
    displacement of the top of every steep member line (columns, braces, diagrid bars on a support path)
    relative to its bottom, between consecutive points where the rest of the structure holds it (the
    floors), against height / ``limit_ratio``. Reported per storey (pair of levels), governing first.
    This is the sway that ``member_deflections`` leaves out of the column deflection."""
    X = np.asarray(frame.nodes, float)
    U = res.displacements[:, :3]
    down, _, reach = _support_paths(frame)
    storeys: dict = {}
    for g in _group_geometry(frame, _member_groups(frame), down, reach):
        if not g["steep"] or len(g["held"]) < 2:
            continue
        held = sorted(g["held"], key=lambda n: X[n, 2])
        for lo, hi in zip(held, held[1:]):
            h = float(X[hi, 2] - X[lo, 2])
            if h < 1e-3 or lo not in reach:
                continue
            drift = float(np.linalg.norm((U[hi] - U[lo])[:2]))
            key = (round(float(X[lo, 2]), 2), round(float(X[hi, 2]), 2))
            entry = {"z_bottom_m": key[0], "z_top_m": key[1], "height_m": round(h, 3),
                     "drift_mm": round(drift * 1000.0, 3), "limit_mm": round(h * 1000.0 / limit_ratio, 3),
                     "utilization": round(drift * limit_ratio / h, 4),
                     "drift_ratio": round(h / drift) if drift > 1e-9 else None,
                     "at_m": [round(float(v), 4) for v in X[hi]],
                     "source_guids": sorted({t for i in g["els"] for t in (frame.elements[i].tag or [])})}
            if key not in storeys or entry["utilization"] > storeys[key]["utilization"]:
                storeys[key] = entry
    rows = sorted(storeys.values(), key=lambda s: (s["z_bottom_m"], s["z_top_m"]))
    worst = max(rows, key=lambda s: s["utilization"]) if rows else None
    return {"limit_ratio": float(limit_ratio), "storeys": rows, "governing": worst,
            "max_drift_mm": worst["drift_mm"] if worst else 0.0,
            "utilization": worst["utilization"] if worst else 0.0}


def _drawn_members(model: dict, frame) -> dict:
    """{source GUIDs: (id, element indices)} per drawn member, in element order; id = the curve's name or Mn
    (the ids member_table and the deflection verdict use)."""
    names = {tuple(m.get("source_guids") or []): m.get("name") for m in model.get("members") or []}
    return {key: (names.get(key) or f"M{n}", idx) for n, (key, idx) in enumerate(_tag_groups(frame).items(), start=1)}


SPAN_FLOOR = 1e-3           # m: a span shorter than this (a station on a cantilever's root) checks nothing


def governing_deflection(deflections, spans, span: float | None = None) -> tuple[int, int, float]:
    """(element, station, span m) with the largest deflection / span: each station against its own span,
    or every station against ``span`` when given."""
    best = (-1.0, 0, 0, float(span or 0.0))
    for i, d in enumerate(deflections):
        L = np.full(len(d), float(span)) if span else np.maximum(spans[i], SPAN_FLOOR)
        r = np.where(L > SPAN_FLOOR, d / L, 0.0)
        k = int(np.argmax(r))
        if r[k] > best[0]:
            best = (float(r[k]), i, k, float(L[k]))
    return best[1:]


def is_surface(frame) -> bool:
    """A frame carried as a surface, not by a beam/column hierarchy (a vault, gridshell, arch or curved roof):
    no straight near-vertical member, no taller than it is wide (not a tower), and at least half the member
    length curved or inclined."""
    X = np.asarray(frame.nodes, float)
    if not len(X) or np.ptp(X[:, 2]) > max(np.ptp(X[:, 0]), np.ptp(X[:, 1])):
        return False
    total = shaped = 0.0
    for idx in _tag_groups(frame).values():
        nodes = sorted({n for i in idx for n in (frame.elements[i].n1, frame.elements[i].n2)})
        P = X[nodes]
        a = P[int(np.argmax(np.linalg.norm(P - P[0], axis=1)))]
        b = P[int(np.argmax(np.linalg.norm(P - a, axis=1)))]
        chord = float(np.linalg.norm(b - a))
        length = sum(float(np.linalg.norm(X[frame.elements[i].n2] - X[frame.elements[i].n1])) for i in idx)
        if chord <= 0:
            continue
        d = (b - a) / chord
        off = P - a - np.outer((P - a) @ d, d)
        straight = float(np.max(np.linalg.norm(off, axis=1))) <= 0.01 * chord
        slope = abs(float(d[2]))
        if straight and slope > 0.9:
            return False                                # a column: the frame has a load path hierarchy
        total += length
        shaped += length if (not straight or 0.1 < slope) else 0.0
    return total > 0 and shaped >= 0.5 * total


def _tag_groups(frame) -> dict:
    groups: dict = {}
    for i, e in enumerate(frame.elements):
        groups.setdefault(tuple(e.tag or []), []).append(i)
    return groups


def surface_deflections(frame, res) -> dict:
    """Deflection of a surface-like frame, in two parts.

    Global: the largest node displacement against the structure's span, twice the largest plan distance
    from any node to its nearest support (the crown of a vault or arch: the distance between its supports;
    an overhang: twice its reach). Local: every member's sag between its own joints (relative to the chord
    through its displaced ends) against its length between them. Returns {"global": (node, displacement m,
    span m), "local": (element, station, sag m, length m)}, the local one with the largest sag / length."""
    X = np.asarray(frame.nodes, float)
    U = res.displacements[:, :3]
    sup = [n for n in frame.supports if frame.vertically_supported(n)] or list(frame.supports)
    free = [n for n in range(len(X)) if n not in frame.supports]
    best_g = (None, 0.0, 0.0)
    if sup and free:
        reach = np.min(np.linalg.norm(X[free][:, None, :2] - X[sup][None, :, :2], axis=2), axis=1)
        u = np.linalg.norm(U[free], axis=1)
        k = int(np.argmax(u))
        best_g = (free[k], float(u[k]), 2.0 * float(np.max(reach)))
    best_l = (-1.0, None, 0, 0.0, 0.0)
    for idx in ec3.groups(frame).values():              # the member between its joints, however refined
        ends = [frame.elements[i].n1 for i in idx] + [frame.elements[i].n2 for i in idx]
        A = max(ends, key=lambda n: np.linalg.norm(X[n] - X[ends[0]]))
        B = max(ends, key=lambda n: np.linalg.norm(X[n] - X[A]))
        c = X[B] - X[A]
        L = float(np.linalg.norm(c))
        if L <= SPAN_FLOOR:
            continue
        axis = c / L
        for i in idx:
            er = res.elements[i]
            t = np.clip((er.stations - X[A]) @ axis / L, 0.0, 1.0)
            rel = er.disp - (np.outer(1 - t, U[A]) + np.outer(t, U[B]))
            sag = np.linalg.norm(rel - np.outer(rel @ axis, axis), axis=1)
            k = int(np.argmax(sag))
            if sag[k] / L > best_l[0]:
                best_l = (float(sag[k] / L), i, k, float(sag[k]), L)
    return {"global": best_g, "local": best_l[1:]}


def deflection_check(model: dict, frame, res, structure_type: str = "frame", span_m: float | None = None) -> dict:
    """What the SLS deflection is checked against, and the governing deflection.

    span_m given: every member's deflection against it ("user"). beam/frame: a surface-like frame
    (is_surface) gets the global and local checks of surface_deflections ("surface"); otherwise each
    member against its own span (member_deflection_spans, "member"). Other types: the overall extent.
    Returns {basis, kind (member | global | local), span, deflection (m), largest (m), element, node,
    deflections, spans}."""
    deflections, spans = member_deflection_spans(frame, res)
    largest = max(float(np.max(d)) for d in deflections)
    out = {"deflections": deflections, "spans": spans, "largest": largest, "node": None, "kind": "member"}
    if not span_m and structure_type in ("beam", "frame") and is_surface(frame):
        sd = surface_deflections(frame, res)
        gn, gu, gspan = sd["global"]
        le, lk, lsag, llen = sd["local"]
        gspan = gspan if gspan > SPAN_FLOOR else 0.0
        out["surface"] = {"global": {"node_m": [round(float(v), 4) for v in frame.nodes[gn]] if gn is not None else None,
                                     "deflection_mm": round(gu * 1000, 3), "span_m": round(gspan, 3)},
                          "local": {"element": le, "deflection_mm": round(lsag * 1000, 3), "span_m": round(llen, 3)}}
        out["largest"] = max(gu, lsag)
        if gn is not None and gspan and (le is None or gu / gspan >= lsag / llen):
            el = next((i for i, e in enumerate(frame.elements) if gn in (e.n1, e.n2)), 0)
            out.update(basis="surface", kind="global", span=gspan, deflection=gu, element=el, node=gn)
        elif le is not None:
            out.update(basis="surface", kind="local", span=llen, deflection=lsag, element=le)
        if "basis" in out:
            return out
    if span_m:
        span, basis = float(span_m), "user"
    elif structure_type in ("beam", "frame"):
        span, basis = 0.0, "member"
    else:
        span, basis = float(model.get("max_span_m") or 0.0), "extent"
    if basis != "member" and span < 0.001:
        span, basis = 5.0, "default"
    gi, gk, span = governing_deflection(deflections, spans, None if basis == "member" else span)
    if span <= SPAN_FLOOR:                                  # nothing deflects (or no measurable span)
        span = float(model.get("max_member_span_m") or model.get("max_span_m") or 5.0)
    out.update(basis=basis, span=span, deflection=float(deflections[gi][gk]), element=gi)
    return out


def member_table(model: dict, frame, sls, envelope, deflections=None, spans=None) -> list[dict]:
    """Every member (one per source curve), aggregated over its analysis elements: geometry, section,
    ULS design forces and checks from each piece's governing combination, and SLS displacements.
    ``spans`` (member_deflection_spans): each member's deflection ratio is against its own span."""
    names = {tuple(m.get("source_guids") or []): m for m in model.get("members") or []}
    rows = []
    for key, (mid, idx) in _drawn_members(model, frame).items():
        src = names.get(key, {})
        ends = [frame.nodes[frame.elements[i].n1] for i in idx] + [frame.nodes[frame.elements[i].n2] for i in idx]
        A, B = max(((p, q) for p in ends for q in ends), key=lambda pq: math.dist(*pq))
        A, B = np.asarray(A), np.asarray(B)
        chord = B - A
        span = float(np.linalg.norm(chord)) or 1e-9
        # SLS: deflection relative to the member's own displaced end points (what a span/limit check reads)
        pts = np.vstack([sls.elements[i].stations for i in idx])
        disp = np.vstack([sls.elements[i].disp for i in idx])
        t = np.clip((pts - A) @ chord / span ** 2, 0.0, 1.0)
        dA, dB = disp[int(np.argmin(np.linalg.norm(pts - A, axis=1)))], disp[int(np.argmin(np.linalg.norm(pts - B, axis=1)))]
        sag = float(np.max(np.linalg.norm(disp - (np.outer(1 - t, dA) + np.outer(t, dB)), axis=1)))
        dspan = span
        if deflections is not None:                     # relative to what supports the member (cantilevers too)
            sag = max(float(np.max(deflections[i])) for i in idx)
        if deflections is not None and spans is not None:   # at its worst point against its own span
            gi, gk, dspan = governing_deflection([deflections[i] for i in idx], [spans[i] for i in idx])
            if dspan > SPAN_FLOOR:
                sag = float(deflections[idx[gi]][gk])
            else:
                dspan = span
        # ULS: the governing piece and the design forces of every piece's governing combination
        gi = max(idx, key=lambda i: envelope[i][0])
        u, comb, ger = envelope[gi]
        det = ger.util_detail
        check = det.get("governing_check") or (
            "flexural buckling" if det.get("buckling", -1.0) >= det.get("cross_section", 0.0) else "cross-section")
        N = np.concatenate([envelope[i][2].N for i in idx])
        M = np.concatenate([np.hypot(envelope[i][2].My, envelope[i][2].Mz) for i in idx])
        V = max(max(math.hypot(ef[1], ef[2]), math.hypot(ef[7], ef[8])) for ef in (envelope[i][2].end_forces for i in idx))
        e0 = frame.elements[idx[0]]
        pinned = {"start": False, "end": False}
        for i in idx:
            el = frame.elements[i]
            rel = el.releases or (False,) * 12
            for node, flag in ((el.n1, rel[4] or rel[5]), (el.n2, rel[10] or rel[11])):
                if flag:
                    p = np.asarray(frame.nodes[node])
                    if np.linalg.norm(p - A) < 1e-6:
                        pinned["start"] = True
                    elif np.linalg.norm(p - B) < 1e-6:
                        pinned["end"] = True
        rows.append({
            "id": mid, "source_guids": list(key), "layer": src.get("layer"),
            "role": _role(A, B), "start_m": [round(float(v), 4) for v in A], "end_m": [round(float(v), 4) for v in B],
            "length_m": round(span, 4), "elements": len(idx),
            "section": e0.section.name, "material": e0.material.name, "pinned_ends": pinned,
            "utilization": round(float(u), 4),
            "status": "fail" if u > 1.0 or det.get("class") == 4 or det.get("shear_buckling") else
                      "warn" if u > 0.8 else "ok",
            "governing_combination": comb, "governing_check": check,
            "cross_section_utilization": round(float(det["cross_section"]), 4) if "cross_section" in det else None,
            "buckling_utilization": round(float(det["buckling"]), 4) if "buckling" in det else None,
            "slenderness": round(float(det["slenderness"]), 3) if "slenderness" in det else None,
            "chi": round(float(det["chi"]), 3) if "chi" in det else None,
            "moduli": det.get("moduli"), "section_class": det.get("class"),
            "buckling_curves": [det["curve_y"], det["curve_z"]] if "curve_y" in det else None,
            "chi_y": _r(det.get("chi_y"), 3), "chi_z": _r(det.get("chi_z"), 3),
            "lambda_y": _r(det.get("lambda_y"), 3), "lambda_z": _r(det.get("lambda_z"), 3),
            "cm_y": _r(det.get("cm_y"), 3), "cm_z": _r(det.get("cm_z"), 3),
            "cm_y_basis": det.get("cm_y_basis"), "cm_z_basis": det.get("cm_z_basis"),
            "kyy": _r(det.get("kyy"), 3), "kzz": _r(det.get("kzz"), 3),
            "eq_6_61": _r(det.get("eq_6_61"), 4), "eq_6_62": _r(det.get("eq_6_62"), 4),
            "shear_utilization": _r(det.get("shear"), 4),
            "v_pl_rd_kn": [_r(det["v_pl_rd_y_kn"], 3), _r(det["v_pl_rd_z_kn"], 3)] if "v_pl_rd_y_kn" in det else None,
            "shear_rho": _r(det.get("rho"), 4), "shear_buckling": det.get("shear_buckling"),
            "ltb_utilization": _r(det.get("ltb"), 4), "m_cr_knm": _r(det.get("m_cr_knm"), 3),
            "lambda_lt": _r(det.get("lambda_lt"), 3), "chi_lt": _r(det.get("chi_lt"), 3),
            "ltb_curve": det.get("curve_lt"), "cm_lt": _r(det.get("cm_lt"), 3),
            "ltb_length_m": _r(det.get("length_lt_m"), 3), "ltb_ends": det.get("ltb_ends"),
            "buckling_length_m": _r(det.get("length_cr_m"), 3),
            "max_stress_mpa": round(float(det.get("max_stress_mpa", 0.0)), 2),
            "n_tension_kn": round(max(float(N.max()), 0.0), 3), "n_compression_kn": round(max(-float(N.min()), 0.0), 3),
            "v_max_kn": round(float(V), 3), "m_max_knm": round(float(M.max()), 3),
            "t_max_knm": round(max(abs(float(envelope[i][2].T)) for i in idx), 3),
            "max_displacement_mm": round(float(np.max(np.linalg.norm(disp, axis=1))) * 1000.0, 3),
            "deflection_mm": round(sag * 1000.0, 3), "deflection_span_m": round(dspan, 4),
            "deflection_ratio": round(dspan / sag) if sag > 1e-9 else None,
        })
    return rows


def support_table(frame, info: dict, sls, ulss, fixed: bool) -> list[dict]:
    """Reactions at every support: SLS characteristic and each ULS combination (its governing variant).
    A spring's reaction is its force on the structure."""
    def forces(r, n):
        return {k: round(float(v), 3) + 0.0 for k, v in zip(DOF_NAMES, r.reactions[n])}
    labels = info.get("support_labels") or {}
    return [{"node": int(n), "position_m": [round(float(v), 4) for v in frame.nodes[n]],
             "restraint": labels.get(n, "fixed" if fixed else "pinned"), "sls": forces(sls, n),
             "uls": {name: forces(r_, n) for name, _, r_ in ulss}} for n in info["support_nodes"]]


def _support_mode(info: dict, fixed_supports: bool) -> str:
    """The one support type every support has ("fixed", "pinned", ...), else "mixed"."""
    kinds = set((info.get("support_labels") or {}).values())
    return kinds.pop() if len(kinds) == 1 else ("mixed" if kinds else ("fixed" if fixed_supports else "pinned"))


def _support_counts(info: dict) -> dict:
    counts: dict = {}
    for k in (info.get("support_labels") or {}).values():
        counts[k] = counts.get(k, 0) + 1
    return counts


def _label(factors: dict) -> str:
    return " + ".join(f"{v:g}{k}" for k, v in factors.items())


PHI_0 = 1 / 200            # EN 1993-1-1 5.3.2(3) basic sway imperfection
STABILITY_SUBDIVISION = 4   # elements per member for geometric stiffness (alpha_cr error ~0.05 %; 1 element: +22 %)
ALPHA_CR_FIRST_ORDER = 10.0  # 5.2.1(3): first-order analysis suffices at or above this (elastic)


class InstabilityError(ValueError):
    """The frame buckles below the ULS loads (alpha_cr <= 1 or second-order divergence)."""
    def __init__(self, message, report):
        super().__init__(message)
        self.report = report


def _split_plan(frame, parts: int, only: set | None = None) -> dict:
    """{element: equal pieces} for subdivide: ``parts`` per bending member; a curved run already drawn as
    k chords (one member, ``group``) gets ceil(parts / k) per chord."""
    if parts < 2:
        return {}
    X = np.asarray(frame.nodes, float)
    lengths = [float(np.linalg.norm(X[e.n2] - X[e.n1])) for e in frame.elements]
    short = 0.01 * max(lengths, default=0.0)                   # stubs: splitting them only worsens conditioning
    chords: dict = {}
    for e in frame.elements:
        if e.group is not None:
            chords[e.group] = chords.get(e.group, 0) + 1
    plan = {}
    for ei, e in enumerate(frame.elements):
        if e.truss or (only is not None and ei not in only) or lengths[ei] < short:
            continue
        k = math.ceil(parts / chords[e.group]) if e.group is not None else parts
        if k > 1:
            plan[ei] = k
    return plan


def subdivide(frame, parts: int, only: set | None = None) -> None:
    """Split bending members (all, or the element indices in ``only``) into ``parts`` equal elements
    (in place; loads, releases and lineage follow). Geometric stiffness is only accurate with interior
    nodes; first-order results are exact either way."""
    for ei, k in _split_plan(frame, parts, only).items():
        tail = ei
        for j in range(1, k):
            frame.split_element(tail, 1.0 / (k - j + 1))
            tail = len(frame.elements) - 1


def _refine_compressed(frame, compressed: set | None) -> tuple[int, dict]:
    """Subdivide the compressed members (None: every bending member) for the geometric stiffness, into
    STABILITY_SUBDIVISION elements per member, fewer (down to 2) if that would exceed the budget.
    Returns (elements per member, size); raises ModelTooLargeError if even 2 do not fit."""
    for parts in range(STABILITY_SUBDIVISION, 1, -1):
        added = sum(k - 1 for k in _split_plan(frame, parts, compressed).values())
        if 6 * (len(frame.nodes) + added) <= max_dof("stability") or parts == 2:
            size = check_size(len(frame.nodes) + added, len(frame.elements) + added, "stability", added)
            subdivide(frame, parts, compressed)
            return parts, size


def _worst_dof(frame, parts: int) -> int:
    """DOF of the analysis if every bending member were compressed and refined into ``parts`` (0: as built)."""
    return 6 * (len(frame.nodes) + sum(k - 1 for k in _split_plan(frame, parts).values()))


def build_within_budget(model: dict, *args, stability: bool = True, curve_ratio=CURVE_SAGITTA_RATIO,
                        max_curve_segments: int = MAX_CURVE_SEGMENTS):
    """build_frame (``args`` as there, after model) with curved members coarsened (CURVE_FALLBACK_SEGMENTS chords
    per piece at most) until the worst case of the analysis fits the dense solver's budget: every bending
    member compressed and refined into STABILITY_SUBDIVISION elements, else 3, else 2 (a run of k chords
    needs no more than that refinement, so curves are not coarsened below it). Deterministic: the same
    model always gets the same discretisation. Raises ModelTooLargeError when even the first-order
    analysis cannot fit."""
    caps = [max_curve_segments] + [c for c in CURVE_FALLBACK_SEGMENTS if c < max_curve_segments]
    built: dict = {}

    def build(cap):
        if cap not in built:
            built[cap] = build_frame(model, *args, curve_ratio=curve_ratio, max_curve_segments=cap)
        return built[cap]

    chosen = None
    for parts in range(STABILITY_SUBDIVISION, 1, -1) if stability else (0,):
        for cap in [c for c in caps if c >= parts] or caps[:1]:
            frame, info, _ = build(cap)
            if _worst_dof(frame, parts) <= max_dof("stability" if parts else "linear"):
                chosen = cap
                break
            if not info["curved_pieces"]:
                break
        if chosen is not None:
            break
    if chosen is None:              # the worst case never fits: the refinement of what is actually compressed decides
        fallback = [c for c in caps if c <= 2] or caps[-1:]
        chosen = next((c for c in fallback if 6 * len(build(c)[0].nodes) <= max_dof("linear")), fallback[-1])
    frame, info, warnings = build(chosen)
    if chosen != max_curve_segments and info["curved_pieces"]:
        warnings = warnings + [f"Curved members were coarsened to at most {chosen} chord(s) per piece so the analysis "
                               f"fits the dense solver's {DENSE_BUDGET_GB:g} GB budget ({len(frame.nodes)} nodes)."]
    check_size(len(frame.nodes), len(frame.elements))
    return frame, info, warnings


ROW_TOL = 0.05              # m: column lines this close across the sway direction stand in one plane


def _rows(coords: list, tol: float = ROW_TOL) -> list[list[int]]:
    """Indices of ``coords`` grouped into clusters no wider than consecutive gaps of ``tol``."""
    order = sorted(range(len(coords)), key=lambda k: coords[k])
    rows: list[list[int]] = []
    for k in order:
        if rows and coords[k] - coords[rows[-1][-1]] <= tol:
            rows[-1].append(k)
        else:
            rows.append([k])
    return rows


def sway_imperfection(frame, axial: np.ndarray | None = None) -> dict:
    """EN 1993-1-1 5.3.2(3): phi = phi_0 * alpha_h * alpha_m, alpha_h = 2/sqrt(h) in [2/3, 1],
    alpha_m = sqrt(0.5 (1 + 1/m)), h = height of the structure.

    m per sway direction (5.3.2(3)b): the columns in a row, i.e. the column lines standing in one
    vertical plane parallel to the sway, counting only those that carry a vertical load N_Ed of at least
    50 % of the average column load in that plane. A column line's load is its largest compression in
    ``axial`` (element axial forces, tension +); without ``axial`` every column counts. A frame with
    several rows takes the smallest m (the largest alpha_m: on the safe side for every row).
    No columns (or no height): no sway imperfection."""
    X = np.asarray(frame.nodes, float)
    lines: dict = {}
    for i, e in enumerate(frame.elements):
        d = X[e.n2] - X[e.n1]
        L = float(np.linalg.norm(d))
        if L > 0 and abs(d[2]) / L > 0.98:
            lines.setdefault((round(float(X[e.n1][0]), 2), round(float(X[e.n1][1]), 2)), []).append(i)
    h = float(X[:, 2].max() - X[:, 2].min()) if len(X) else 0.0
    if not lines or h < 0.1:
        return {"phi": 0.0, "phi_x": 0.0, "phi_y": 0.0, "h_m": round(h, 3), "columns": len(lines),
                "basis": "no columns: no sway imperfection"}
    a_h = min(1.0, max(2 / 3, 2 / math.sqrt(h)))
    keys = list(lines)
    load = [1.0 if axial is None else max(0.0, -float(min(axial[i] for i in lines[k]))) for k in keys]
    out = {"h_m": round(h, 3), "columns": len(lines), "alpha_h": round(a_h, 4)}
    for name, axis in (("x", 0), ("y", 1)):
        ms = []
        for row in _rows([k[1 - axis] for k in keys]):          # sway along x: rows share y
            avg = sum(load[k] for k in row) / len(row)
            ms.append(sum(1 for k in row if load[k] >= 0.5 * avg) if avg > 0 else len(row))
        m = min(ms)
        a_m = math.sqrt(0.5 * (1 + 1 / m))
        out.update({f"phi_{name}": PHI_0 * a_h * a_m, f"m_{name}": m, f"alpha_m_{name}": round(a_m, 4)})
    gov = "x" if out["phi_x"] >= out["phi_y"] else "y"
    out.update({"phi": out[f"phi_{gov}"], "alpha_m": out[f"alpha_m_{gov}"],
                "basis": "EN 1993-1-1 5.3.2(3), phi_0 = 1/200; m per sway direction: columns in a row with "
                         "N_Ed >= 50 % of the row's average"})
    return out


def _imperfection_loads(asm, frame, combo, phi) -> dict:
    """Equivalent horizontal forces phi * V at every loaded free node, in +x, -x, +y, -y. ``phi`` is
    one value or {"x": phi_x, "y": phi_y}."""
    px, py = (phi.get("x", 0.0), phi.get("y", 0.0)) if isinstance(phi, dict) else (phi, phi)
    if px <= 0 and py <= 0:
        return {"": None}
    F = fs.load_vector(asm, combo).reshape(-1, fs.DOF)
    V = np.where(F[:, 2] < 0, -F[:, 2], 0.0)
    for n in frame.supports:
        if frame.vertically_supported(n):                  # the load goes straight into the support
            V[n] = 0.0
    out = {}
    for label, axis, sign in (("+x", 0, 1), ("-x", 0, -1), ("+y", 1, 1), ("-y", 1, -1)):
        H = np.zeros_like(F)
        H[:, axis] = sign * (px if axis == 0 else py) * V
        out[label] = H.reshape(-1)
    return out


SWAY_DIRECTIONS = {"+x": (1.0, 0.0, 0.0), "-x": (-1.0, 0.0, 0.0), "+y": (0.0, 1.0, 0.0), "-y": (0.0, -1.0, 0.0)}


def _moment_resistant(frame, at: dict, node: int, own: set, el, axis: str) -> bool:
    """5.3.2(6) first condition at one member end: the member's own end is not released about the
    buckling axis ("y": ry, "z": rz), and the joint resists rotation: a rotationally restrained (or
    sprung) support, or another bending member framing in without releases at that node."""
    if el.truss:
        return False
    rel = el.releases or (False,) * 12
    if rel[(4 if axis == "y" else 5) + (0 if el.n1 == node else 6)]:
        return False
    sup, spr = frame.supports.get(node), frame.springs.get(node)
    if (sup and any(sup[3:])) or (spr and any(v > 0 for v in spr[3:])):
        return True
    for j in at.get(node, ()):
        if j in own:
            continue
        other = frame.elements[j]
        r = other.releases or (False,) * 12
        o = 0 if other.n1 == node else 6
        if not other.truss and not (r[o + 4] and r[o + 5]):
            return True
    return False


def bow_plan(frame, members: dict, axial: np.ndarray, fabrication: str = "cold_formed") -> tuple[list, dict]:
    """Members that need a local bow imperfection under one combination (EN 1993-1-1 5.3.2(6)), for a
    frame sensitive to second-order effects: per compressed steel member and buckling axis, at least
    one moment-resistant end and lambda_bar > 0.5 sqrt(A fy / N_Ed) (lambda_bar for the member hinged
    at its ends, L = the member between its joints). e0 from Table 5.1 (elastic analysis) with the
    member's Table 6.2 curve. Returns (bows, {reason skipped: count})."""
    X = np.asarray(frame.nodes, float)
    at: dict = {}
    for i, e in enumerate(frame.elements):
        at.setdefault(e.n1, []).append(i)
        at.setdefault(e.n2, []).append(i)
    bows, skipped = [], {}

    def skip(reason):
        skipped[reason] = skipped.get(reason, 0) + 1

    for g, idx in members.items():
        e0 = frame.elements[idx[0]]
        n_ed = max(0.0, -float(min(axial[i] for i in idx)))
        if n_ed <= 0:
            continue                                            # not compressed: nothing to imperfect
        if e0.material.family not in ec3.STEEL_FAMILIES:
            skip("not steel (Table 5.1 curves are for steel)")
            continue
        if any(frame.elements[i].truss for i in idx):
            skip("truss bar: no moment-resistant end")
            continue
        nodes = sorted({n for i in idx for n in (frame.elements[i].n1, frame.elements[i].n2)})
        A, B = max(((p, q) for p in nodes for q in nodes), key=lambda pq: float(np.linalg.norm(X[pq[0]] - X[pq[1]])))
        L = float(np.linalg.norm(X[B] - X[A]))
        if L <= 0:
            continue
        R, _ = fs.local_axes(X[e0.n1], X[e0.n2], e0.ref)
        cy, cz = ec3.buckling_curves(e0.section, e0.material.fy, fabrication)
        own, axes = set(idx), []
        ends = [next(frame.elements[i] for i in idx if n in (frame.elements[i].n1, frame.elements[i].n2))
                for n in (A, B)]
        for axis, curve, vec in (("y", cy, R[2]), ("z", cz, R[1])):   # about y: bows along local z
            if not any(_moment_resistant(frame, at, n, own, el, axis) for n, el in zip((A, B), ends)):
                skip("no moment-resistant end")
                continue
            need, lam, limit = ec3.bow_required(e0.section, e0.material.fy, e0.material.E, L, n_ed, axis)
            if not need:
                skip("lambda_bar <= 0.5 sqrt(A fy / N_Ed)")
                continue
            axes.append({"axis": axis, "curve": curve, "e0": ec3.bow_imperfection(curve, L), "dir": np.asarray(vec),
                         "lambda_bar": lam, "limit": limit})
        if axes:
            bows.append({"member": g, "elements": list(idx), "ends": (A, B), "length": L, "n_ed": n_ed,
                         "tag": list(e0.tag or []), "axes": axes})
    return bows, skipped


def bow_loads(bows: list, direction, ndof: int) -> tuple[np.ndarray, dict]:
    """Equivalent loads of the bows (Figure 5.4) bulging towards ``direction`` (global unit vector, the
    sway's): a uniform load 8 N_Ed e0 / L^2 along the member and 4 N_Ed e0 / L against it at each end
    (self-equilibrating). Returns (global nodal vector, {element: global uniform load kN/m})."""
    d = np.asarray(direction, float)
    H, w = np.zeros(ndof), {}
    for b in bows:
        L, N = b["length"], b["n_ed"]
        for ax in b["axes"]:
            c = float(d @ ax["dir"])
            if abs(c) < 1e-9:
                continue
            v = c * ax["dir"]
            for ei in b["elements"]:
                w[ei] = w.get(ei, np.zeros(3)) + 8 * N * ax["e0"] / L ** 2 * v
            for n in b["ends"]:
                H[n * fs.DOF:n * fs.DOF + 3] -= 4 * N * ax["e0"] / L * v
    return H, w


def _solve_design(frame, design_basis, uls, plastic=False, stations=11, stability="auto", design_code=None,
                  fabrication="cold_formed", lateral_restraint="joints"):
    """Solve SLS + ULS combinations; per-element ULS envelope. Returns (sls, uls_results, envelope,
    stability report) with envelope[i] = (utilization, governing name, element result).

    stability="auto": alpha_cr per ULS combination; sway imperfections (5.3.2) in every ULS check;
    alpha_cr < 10 -> second-order (P-Delta) ULS analysis; alpha_cr <= 1 -> InstabilityError.
    stability="off": first-order, no imperfections."""
    code = design_profile(design_basis, design_code)
    frame.gamma_m = (code.gamma_M0, code.gamma_M1)
    sls, ulss = combinations(design_basis, uls, code)
    size = check_size(len(frame.nodes), len(frame.elements))
    if (stability or "auto").lower() == "off":
        res = fs.solve_combinations(frame, {sls[0]: sls[1], **dict(ulss)}, stations=stations, plastic=plastic)
        members = ec3.groups(frame)
        for r_ in res.values():
            ec3.apply(frame, r_, members, plastic, fabrication, lateral_restraint)
        envelope = []
        for i in range(len(frame.elements)):
            best = max(((res[n].elements[i].utilization, n) for n, _ in ulss), key=lambda t: t[0])
            envelope.append((best[0], best[1], res[best[1]].elements[i]))
        return res[sls[0]], [(n, f, res[n]) for n, f in ulss], envelope, {"mode": "off", "method": "first-order",
                                                                          "dense_size": size,
                                                                          "warnings": _memory_warning(size)}
    if (stability or "").lower() != "auto":
        raise ValueError("stability must be 'auto' or 'off'.")
    # buckling needs interior nodes in the compression members: refine those (in place), then re-assemble
    asm = fs.prepare(frame)
    compressed = set()
    for _, factors in ulss:
        N = fs.axial_forces(asm, factors)
        if N.size and N.min() < 0:
            compressed |= {i for i in range(len(N)) if N[i] < 0.01 * N.min()}
    parts, notes = STABILITY_SUBDIVISION, []
    if compressed:
        parts, size = _refine_compressed(frame, compressed)
        asm = fs.prepare(frame)
        if parts < STABILITY_SUBDIVISION:
            notes.append(f"Compressed members were refined into {parts} elements each for alpha_cr (not "
                         f"{STABILITY_SUBDIVISION}) to fit the dense solver's budget: alpha_cr may be ~1 % high.")
    members = ec3.groups(frame)
    sls_res = fs.solve_linear(asm, sls[1], stations=stations, plastic=plastic)
    ec3.apply(frame, sls_res, members, plastic, fabrication, lateral_restraint)
    report = {"mode": "auto", "alpha_cr": {}, "sway_imperfection": None, "sway_imperfections": {},
              "second_order": [], "iterations": 0, "elements_per_member": parts,
              "dense_size": size, "warnings": notes + _memory_warning(size),
              "bow_imperfection": {"basis": "EN 1993-1-1 5.3.2(6): frames with alpha_cr < 10, compressed members with "
                                            "a moment-resistant end and lambda_bar > 0.5 sqrt(A fy / N_Ed); e0/L "
                                            "from Table 5.1 (elastic)", "applied": [], "skipped": {}}}
    variants = []                                           # (name, factors, result)
    for name, factors in ulss:
        axial = fs.axial_forces(asm, factors)
        imp = sway_imperfection(frame, axial)
        report["sway_imperfections"][name] = imp
        if report["sway_imperfection"] is None or imp["phi"] > report["sway_imperfection"]["phi"]:
            report["sway_imperfection"] = imp
        alpha, _ = fs.critical_load_factor(asm, factors)
        report["alpha_cr"][name] = None if math.isinf(alpha) else round(alpha, 3)
        if alpha <= 1.0:
            report["method"] = "unstable"
            raise InstabilityError(f"Instability: elastic critical load factor alpha_cr = {alpha:.2f} <= 1 under "
                                   f"{name}: the frame buckles before reaching the design loads.", report)
        second = alpha < ALPHA_CR_FIRST_ORDER
        bows = []
        if second:
            report["second_order"].append(name)
            bows, skipped = bow_plan(frame, members, axial, fabrication)
            bi = report["bow_imperfection"]
            for k, v in skipped.items():
                bi["skipped"][k] = bi["skipped"].get(k, 0) + v
            bi["applied"] += [{"combination": name, "source_guids": b["tag"], "length_m": round(b["length"], 3),
                               "n_ed_kn": round(b["n_ed"], 3), "axis": ax["axis"], "curve": ax["curve"],
                               "e0_over_l": f"1/{ec3.BOW_ELASTIC[ax['curve']]}", "e0_mm": round(ax["e0"] * 1000, 2),
                               "lambda_bar": round(ax["lambda_bar"], 3), "lambda_limit": round(ax["limit"], 3)}
                              for b in bows for ax in b["axes"]]
        loads = _imperfection_loads(asm, frame, factors, {"x": imp["phi_x"], "y": imp["phi_y"]})
        kind = "sway"
        if bows and "" in loads:                                # no sway imperfection: bows alone, each way
            loads, kind = {label: None for label in SWAY_DIRECTIONS}, "bow"
        for label, H in loads.items():
            vname = f"{name} {label} {kind}".strip() if label else name
            w = None
            if bows and label:                                  # bows bulge the way the frame sways
                Hb, w = bow_loads(bows, SWAY_DIRECTIONS[label], asm.ndof)
                H = Hb if H is None else H + Hb
            try:
                r_ = (fs.solve_second_order(asm, factors, extra=H, stations=stations, plastic=plastic, member_loads=w)
                      if second else fs.solve_linear(asm, factors, extra=H, stations=stations, plastic=plastic))
            except fs.MechanismError as exc:
                report["method"] = "unstable"
                raise InstabilityError(f"Instability under {vname}: {exc}", report) from None
            ec3.apply(frame, r_, members, plastic, fabrication, lateral_restraint)
            report["iterations"] = max(report["iterations"], r_.iterations)
            variants.append((vname, factors, r_))
    report["method"] = "second-order (P-Delta)" if report["second_order"] else "first-order"
    if not report["second_order"]:
        report["bow_imperfection"]["skipped"] = {"alpha_cr >= 10: first-order, 5.3.2(6) needs no bows": len(ulss)}
    finite = [a for a in report["alpha_cr"].values() if a is not None]
    report["min_alpha_cr"] = min(finite) if finite else None
    envelope = []
    for i in range(len(frame.elements)):
        best = max(((v[2].elements[i].utilization, v[0]) for v in variants), key=lambda t: t[0])
        envelope.append((best[0], best[1], next(v[2] for v in variants if v[0] == best[1]).elements[i]))
    # one representative per ULS combination (base name): its worst imperfection variant
    reps = []
    for name, factors in ulss:
        mine = [v for v in variants if v[0] == name or v[0].startswith(name + " ")]
        worst = max(mine, key=lambda v: v[2].max_utilization)
        worst[2].variant = worst[0][len(name):].strip()
        reps.append((name, factors, worst[2]))
    return sls_res, reps, envelope, report


def view_result(model: dict, load_kn: float = 10.0, material: str = "Steel", fixed_supports: bool = True,
                self_weight: bool = True, diameter_mm=None, wall_mm=None, span_m: float | None = None,
                stations: int = 13, asset_loads: dict | None = None,
                floor_loads: dict | None = None, design_basis: str = "en1990",
                uls: str | None = None, connections: str = "rigid", stability: str = "auto",
                view: str = "deflection", design_code=None, fabrication: str = "cold_formed",
                lateral_restraint: str = "joints", structure_type: str | None = None,
                limit_ratio: float | None = None, curve_ratio: float | None = CURVE_SAGITTA_RATIO,
                max_curve_segments: int = MAX_CURVE_SEGMENTS) -> tuple[dict, float]:
    """Solve and package the result for the bridge's ``structure_draw`` overlay.

    Returns (result, span_m): per-element start/end points and sampled global displacements in
    meters (SLS characteristic), ULS utilization envelope, supports, loaded nodes, the absolute max
    displacement (which scales the drawing) and, for the deflected shape, the checked deflection
    (``max_deflection_mm``: the governing member's, as validate() measures it), the storey drift and
    ``verdict``: the same checks and pass/fail as validate() with the same inputs (each member's
    deflection against its own span / ``limit_ratio``, or the surface checks; Class 4 sections and
    webs past the shear buckling limit, utilization, storey drift). span_m is the caller's or the span
    of the governing deflection. Raises frame_solver.MechanismError for unstable models,
    ModelTooLargeError (a ValueError) for a model beyond the dense solver."""
    args = {k: v for k, v in locals().items() if k != "model"}
    try:
        return _view_result(model, **args)
    except MemoryError:
        raise ModelTooLargeError("Model too large for the dense solver: it ran out of memory. Show fewer members "
                                 "at a time.", {}) from None


def _view_result(model, load_kn, material, fixed_supports, self_weight, diameter_mm, wall_mm, span_m, stations,
                 asset_loads, floor_loads, design_basis, uls, connections, stability, view, design_code, fabrication,
                 lateral_restraint, structure_type, limit_ratio, curve_ratio, max_curve_segments):
    want_mode = (view or "deflection").lower() == "buckling"
    frame, info, warnings = build_within_budget(model, load_kn, material, fixed_supports, self_weight, diameter_mm,
                                                wall_mm, asset_loads, floor_loads, connections,
                                                stability=want_mode or (stability or "auto").lower() != "off",
                                                curve_ratio=curve_ratio, max_curve_segments=max_curve_segments)
    if (view or "deflection").lower() not in ("deflection", "buckling"):
        raise ValueError("view must be 'deflection' or 'buckling'.")
    code = design_profile(design_basis, design_code)
    res, ulss, envelope, stab = _solve_design(frame, design_basis, uls, stations=stations,
                                              stability="off" if want_mode else stability, design_code=code,
                                              fabrication=_fabrication(fabrication),
                                              lateral_restraint=_lateral_restraint(lateral_restraint))
    warnings += stab.pop("warnings", [])
    span = float(span_m or 0.0)
    buckling = None
    verdict = None
    if not want_mode:
        kind = (structure_type or "beam").lower()
        ratio = float(limit_ratio or code.deflection_limit_ratio)
        dc_ = deflection_check(model, frame, res, kind, span_m)
        span = dc_["span"]                                  # the governing deflection's span
        limit_mm = span * 1000.0 / ratio
        dmax_mm = dc_["deflection"] * 1000.0
        gov, where = _governing_deflection(model, frame, dc_, limit_mm)
        drift = _storey_drift_check(frame, res, code, kind)
        umax, governing = max(((u, n) for u, n, _ in envelope), key=lambda t: t[0])
        unc = _uncovered_members(frame, envelope, info["material"])
        slender, thin_webs = unc["class4"], unc["thin_webs"]
        indicative = INDICATIVE_FAMILIES.get(info["material"].family)
        failures, _ = check_failures(dmax_mm, limit_mm, ratio, umax, governing, len(slender), indicative, drift,
                                     where, len(thin_webs), unc["hints"])
        status = "fail" if failures else "indicative" if indicative else "pass"
        verdict = {"status": status, "passed": None if status == "indicative" else not failures,
                   "failures": failures, "max_deflection_mm": round(dmax_mm, 3),
                   "largest_deflection_mm": round(dc_["largest"] * 1000.0, 3),
                   "deflection_measure": _deflection_measure(dc_["basis"]), "governing_deflection": gov,
                   "deflection_limit_mm": round(limit_mm, 3), "deflection_limit_ratio": ratio,
                   "span_m": round(span, 3), "span_basis": dc_["basis"],
                   "max_utilization": round(float(umax), 4), "utilization_combination": governing,
                   "class4_members": len(slender), "shear_buckling_members": len(thin_webs), "storey_drift": drift}
    if span <= SPAN_FLOOR:
        span = float(model.get("max_member_span_m") or model.get("max_span_m") or 5.0)
    if want_mode:
        asm = fs.prepare(frame)
        N = fs.axial_forces(asm, combinations(design_basis, uls, code)[1][0][1])
        if N.size and N.min() < 0:
            _refine_compressed(frame, {i for i in range(len(N)) if N[i] < 0.01 * N.min()})
            asm = fs.prepare(frame)
        name, factors = combinations(design_basis, uls, code)[1][0]
        alpha, mode = fs.critical_load_factor(asm, factors)
        if math.isinf(alpha):
            raise ValueError("Nothing is in compression under " + name + ": there is no buckling mode to show.")
        res = fs.mode_result(asm, mode, stations=stations)
        buckling = {"combination": name, "alpha_cr": round(alpha, 3)}
    elements = []
    # a buckling mode has no magnitude: no utilization, coloured by shape (and its own, refined elements)
    utils = [None] * len(res.elements) if buckling else [round(u, 4) for u, _, _ in envelope]
    if len(utils) != len(res.elements):
        raise RuntimeError("Element results and utilization envelope do not line up.")
    for er, u in zip(res.elements, utils):
        e = frame.elements[er.index]
        rel = e.releases or (False,) * 12
        elements.append({"source_guids": e.tag or [], "start_m": list(frame.nodes[e.n1]), "end_m": list(frame.nodes[e.n2]),
                         "samples_m": np.round(er.disp, 9).tolist(), "utilization": u,
                         "hinges": [bool(rel[4] or rel[5]), bool(rel[10] or rel[11])]})
    result = {"elements": elements,
              "support_points_m": [list(frame.nodes[n]) for n in info["support_nodes"]],
              "support_types": [info["support_labels"][n] for n in info["support_nodes"]],
              "loaded_points_m": [list(frame.nodes[n]) for n in info["loaded_nodes"]],
              "max_displacement_mm": round(res.max_displacement * 1000.0, 3),
              "connections": info["connections"], "stability": stab,
              "combinations": {"deflection": SLS[0],
                               "utilization": [f"{n} ({_label(f)})" for n, f, _ in ulss]},
              "design_code": code.summary(), "deflection_limit_ratio": code.deflection_limit_ratio,
              "indicative": INDICATIVE_FAMILIES.get(info["material"].family),
              "warnings": list(model.get("warnings") or []) + warnings + _code_warnings(code, uls, info)}
    for key in ("asset_loads", "floor_loads"):
        if key in info:
            result[key] = info[key]
    if buckling:
        result["buckling"] = buckling
    if verdict:
        result["verdict"] = verdict
        result["max_deflection_mm"] = verdict["max_deflection_mm"]          # the bridge's legend and verdict
        result["deflection_limit_mm"] = verdict["deflection_limit_mm"]
        worst = verdict["storey_drift"]["governing"]
        result["storey_drift"] = {"checked": verdict["storey_drift"]["checked"],
                                  "limit_ratio": verdict["storey_drift"]["limit_ratio"],
                                  "max_drift_mm": worst["drift_mm"] if worst else 0.0,
                                  "limit_mm": worst["limit_mm"] if worst else None,
                                  "utilization": worst["utilization"] if worst else 0.0}
    return result, span


def _deflection_measure(basis: str) -> str:
    return ("surface: node displacement against the span between supports (global) and member sag between its "
            "joints (local)" if basis == "surface" else "member, relative to its supports")


def _governing_deflection(model: dict, frame, dc: dict, limit_mm: float) -> tuple[dict, str]:
    """(governing_deflection report, where-text for the verdict) of a deflection_check result."""
    gi, span, basis = dc["element"], dc["span"], dc["basis"]
    drawn = _drawn_members(model, frame)
    gtag = tuple(frame.elements[gi].tag or [])
    gname = drawn.get(gtag, (None,))[0] or f"element {gi}"
    if dc["kind"] == "global":
        at = ", ".join(f"{v:.2f}" for v in frame.nodes[dc["node"]])
        where = f" at ({at}) on member {gname} (global, span {span:.2f} m between the supports either side)"
    elif dc["kind"] == "local":
        where = f" in member {gname} (local sag over its {span:.2f} m between joints)"
    else:
        where = f" in member {gname}" + (f" (span {span:.2f} m)" if basis == "member" else "")
    dmm = dc["deflection"] * 1000.0
    report = {"member": gname, "source_guids": list(gtag), "kind": dc["kind"],
              "node_m": [round(float(v), 4) for v in frame.nodes[dc["node"]]] if dc["node"] is not None else None,
              "deflection_mm": round(dmm, 3), "span_m": round(span, 3), "limit_mm": round(limit_mm, 3),
              "utilization": round(dmm / limit_mm, 4) if limit_mm > 0 else None}
    return report, where


def _storey_drift_check(frame, res, code, structure_type: str) -> dict:
    drift = storey_drift(frame, res, code.storey_drift_limit_ratio)
    drift["checked"] = (structure_type or "beam") not in DRIFT_EXEMPT_TYPES
    drift["basis"] = ("project default" if "storey_drift_limit_ratio" in code.project_defaults
                      else "design code profile")
    return drift


def _uncovered_members(frame, envelope, mat) -> dict:
    """Members outside these checks: "class4" (Class 4 sections) and "thin_webs" (webs that need the
    EN 1993-1-5 shear buckling check), by source GUIDs; "elements", their analysis elements; "hints",
    how to get each failing section family out of Class 4 for the actual steel grade."""
    slender_idx = [i for i, (_, _, er) in enumerate(envelope) if er.util_detail.get("class") == 4]
    web_idx = [i for i, (_, _, er) in enumerate(envelope) if er.util_detail.get("shear_buckling")]
    return {"class4": sorted({tuple(frame.elements[i].tag or [str(i)]) for i in slender_idx}),
            "thin_webs": sorted({tuple(frame.elements[i].tag or [str(i)]) for i in web_idx}),
            "elements": sorted(set(slender_idx) | set(web_idx)),
            "hints": [_class4_hint(shape, mat) for shape in sorted({frame.elements[i].section.shape
                                                                   for i in slender_idx})]}


def check_failures(dmax_mm, limit_mm, limit_ratio, umax, governing, slender: int, indicative, drift: dict | None,
                   where: str = "", thin_webs: int = 0, class4_hints: list | None = None):
    """(failures, suggestions) of the native checks: deflection (``where`` names the governing member),
    Class 4 sections, webs past the shear buckling limit, utilization (not for indicative materials) and
    storey drift (where checked). ``class4_hints``: the Class 4 suggestions per failing section family.
    validate() and the overlay verdict (view_result) share it, so both judge a model the same way."""
    failures, sug = [], []
    if dmax_mm > limit_mm:
        failures.append(f"Deflection {dmax_mm:.1f}mm ({SLS[0]}){where} exceeds L/{limit_ratio:g} limit "
                        f"({limit_mm:.1f}mm)")
        sug += ["Increase member depth or use a stiffer cross-section", "Add intermediate supports to reduce effective span"]
    if slender:
        failures.append(f"{slender} member(s) have Class 4 (slender) sections, which these checks do not "
                        "cover (EN 1993-1-5/-1-6 effective sections)")
        sug += class4_hints or ["Use thicker walls: Class 4 starts at d/t = 90 x 235/fy for CHS (59.6 for S355)"]
    if thin_webs:
        failures.append(f"{thin_webs} member(s) have webs with hw/tw > 72 epsilon / eta, which need the shear "
                        "buckling check of EN 1993-1-5 (not covered)")
        sug.append("Use thicker webs or walls (hw/tw <= 72 epsilon), or add web stiffeners and check to EN 1993-1-5")
    if umax > 1.0 and not indicative:
        failures.append(f"Utilization ratio {umax:.2f} ({governing}) exceeds 1.0")
        sug.append("Use a larger cross-section or higher-grade material")
    worst = (drift or {}).get("governing")
    if worst and drift.get("checked") and worst["utilization"] > 1.0:
        failures.append(f"Storey drift {worst['drift_mm']:.1f}mm over h = {worst['height_m']:g} m (z {worst['z_bottom_m']:g}"
                        f"-{worst['z_top_m']:g} m, {SLS[0]}) exceeds h/{drift['limit_ratio']:g} ({worst['limit_mm']:.1f}mm, "
                        f"{drift.get('basis', 'project default')})")
        sug.append("Stiffen the lateral system: bracing, a core, rigid joints or stiffer columns (or agree a "
                   "project-specific drift limit in the design code profile)")
    return failures, sug


def _drift_note(drift: dict, deflection_utilization: float) -> str:
    """The storey drift, for a verdict, when it governs the serviceability checks."""
    worst = drift.get("governing")
    if not worst or not drift.get("checked") or worst["utilization"] <= deflection_utilization:
        return ""
    return (f", storey drift {worst['drift_mm']:.1f}mm (z {worst['z_bottom_m']:g}-{worst['z_top_m']:g} m, "
            f"limit h/{drift['limit_ratio']:g} = {worst['limit_mm']:.1f}mm)")


def validate(model: dict, structure_type: str = "beam", load_kn: float = 10.0, material: str = "Steel",
             fixed_supports: bool = True, self_weight: bool = True, diameter_mm=None, wall_mm=None,
             limit_ratio: float | None = None, plastic: bool = False, span_m: float | None = None,
             asset_loads: dict | None = None, floor_loads: dict | None = None,
             design_basis: str = "en1990", uls: str | None = None, connections: str = "rigid",
             stability: str = "auto", design_code=None, detail: bool = False,
             fabrication: str = "cold_formed", lateral_restraint: str = "joints",
             curve_ratio: float | None = CURVE_SAGITTA_RATIO, max_curve_segments: int = MAX_CURVE_SEGMENTS) -> dict:
    """Run the native check and return a bridge-compatible validation result.

    ``detail``: add "members" (every member's geometry, section, ULS design forces and checks, SLS
    deflection) and "supports" (reactions per combination); the panel's results page reads them.

    The design code profile (``design_code``, default the Eurocode recommended values) sets the
    combination factors, gamma_M0/gamma_M1 and, unless ``limit_ratio`` is given, the deflection limit."""
    result = {"status": "error", "passed": False, "structure_type": structure_type, "material": material,
              "confidence": "high", "suggestions": [], "worst_member_guids": [],
              "warnings": list(model.get("warnings") or []), "assumptions": ASSUMPTIONS,
              "results": {"analysis_method": "native"}}
    t0 = time.perf_counter()
    try:
        if span_m is not None:
            span_m = _finite_parameter(span_m, "span_m", positive=True)
        if limit_ratio is not None:
            limit_ratio = _finite_parameter(limit_ratio, "limit_ratio", positive=True)
        frame, info, notes = build_within_budget(model, load_kn, material, fixed_supports, self_weight, diameter_mm,
                                                 wall_mm, asset_loads, floor_loads, connections,
                                                 stability=(stability or "auto").lower() != "off",
                                                 curve_ratio=curve_ratio, max_curve_segments=max_curve_segments)
        result["warnings"] += notes
        code = design_profile(design_basis, design_code)
        result["design_code"] = code.summary()
        result["warnings"] += _code_warnings(code, uls, info)
        if info["material"].family in INDICATIVE_FAMILIES:
            result["confidence"] = "low"
        res, ulss, envelope, stab = _solve_design(frame, design_basis, uls, plastic=plastic, stability=stability,
                                                  design_code=code, fabrication=_fabrication(fabrication),
                                                  lateral_restraint=_lateral_restraint(lateral_restraint))
        result["warnings"] += stab.pop("warnings", [])
    except InstabilityError as exc:
        result["verdict"] = method_prefix(result["confidence"]) + f"FAILED: {exc}"
        result["status"] = "fail"
        result["results"]["stability"] = exc.report
        result["suggestions"] = ["Brace the frame, fix the column bases, or use stiffer columns: it buckles "
                                 "before reaching the design loads."]
        return result
    except fs.MechanismError as exc:
        result["verdict"] = method_prefix(result["confidence"]) + f"FAILED: {exc}"
        result["status"] = "fail"
        result["suggestions"] = ["Add supports or bracing so every part of the structure is restrained."]
        labels = set(((locals().get("info") or {}).get("support_labels") or {}).values())
        if any(k.startswith(("roller", "spring")) for k in labels):
            result["suggestions"].append("Rollers and springs leave directions free: at least one support must hold "
                                         "each horizontal direction (x, y) and the frame against turning in plan.")
        if (connections or "").lower() == "simple":
            result["suggestions"].append("With simple (pinned) connections the frame needs bracing, fixed column "
                                         "bases or rigid joints for stability.")
        result["results"]["mechanism_nodes_m"] = [list(frame.nodes[n]) for n in exc.nodes] if "frame" in locals() else []
        return result
    except ModelTooLargeError as exc:
        result["verdict"] = str(exc)
        result["results"]["model_size"] = exc.size
        result["suggestions"] = ["Validate a part of the model (fewer members)" + (
            " or use stability='off' (no refinement of compressed members)." if exc.size.get("stage") == "stability"
            else ".")]
        return result
    except MemoryError:
        nodes = len(frame.nodes) if "frame" in locals() else None
        result["verdict"] = (f"Model too large for the dense solver: it ran out of memory ({nodes} nodes, "
                             f"{6 * nodes if nodes else '?'} DOF). Validate fewer members at a time.")
        result["results"]["model_size"] = {"nodes": nodes, "dof": 6 * nodes if nodes else None}
        return result
    except ValueError as exc:
        result["verdict"] = str(exc)
        return result

    mat = info["material"]
    limit_ratio = float(limit_ratio or code.deflection_limit_ratio)
    if mat.family in INDICATIVE_FAMILIES:
        result["confidence"] = "low"
    dc = deflection_check(model, frame, res, structure_type, span_m)
    deflections, spans, span, basis = dc["deflections"], dc["spans"], dc["span"], dc["basis"]
    dmax_mm, dcheck_mm = dc["largest"] * 1000.0, dc["deflection"] * 1000.0
    limit_mm = span * 1000.0 / limit_ratio
    gov, where = _governing_deflection(model, frame, dc, limit_mm)
    drift = _storey_drift_check(frame, res, code, structure_type)
    umax = max(u for u, _, _ in envelope)
    governing = max(envelope, key=lambda t: t[0])[1]
    stress = max(er.util_detail.get("max_stress_mpa", 0.0) for _, _, er in envelope)
    per_member: dict = {}                                   # one entry per drawn member (max over its pieces)
    for i, (u, n, _) in enumerate(envelope):
        key = tuple(frame.elements[i].tag or [])
        if key not in per_member or u > per_member[key]["utilization"]:
            per_member[key] = {"source_guids": list(key), "utilization": round(u, 4), "combination": n}
    elem_util = list(per_member.values())
    r = result["results"]
    r.update({
        "max_deflection_mm": round(dcheck_mm, 3), "largest_deflection_mm": round(dmax_mm, 3),
        "deflection_measure": _deflection_measure(basis), "governing_deflection": gov,
        "max_displacement_mm": round(res.max_displacement * 1000.0, 3),
        "displacement_available": True, "utilization_available": True,
        "deflection_limit_mm": round(limit_mm, 3), "utilization_ratio": round(umax, 4),
        "max_stress_mpa": round(stress, 2), "yield_stress_mpa": mat.fy / 1000.0, "span_m": round(span, 3),
        "span_basis": basis, **({"surface_deflection": dc["surface"]} if "surface" in dc else {}),
        "reactions_kn": round(float(res.reactions[:, 2].sum()), 3),
        "design_basis": (design_basis or "en1990").lower(),
        "deflection_combination": SLS[0], "utilization_combination": governing,
        "combinations": [{"name": SLS[0], "factors": SLS[1], "max_deflection_mm": round(dmax_mm, 3),
                          "reactions_kn": round(float(res.reactions[:, 2].sum()), 3)}] +
                        [{"name": n, "factors": f, "max_utilization": round(r_.max_utilization, 4),
                          "governing_variant": getattr(r_, "variant", ""),
                          "max_deflection_mm": round(max(float(np.max(d)) for d in member_deflections(frame, r_)) * 1000.0, 3),
                          "max_displacement_mm": round(r_.max_displacement * 1000.0, 3),
                          "reactions_kn": round(float(r_.reactions[:, 2].sum()), 3)} for n, f, r_ in ulss],
        "support_points_m": [list(frame.nodes[n]) for n in info["support_nodes"]],
        "loaded_points_m": [list(frame.nodes[n]) for n in info["loaded_nodes"]],
        "per_element_utilization": elem_util,
        "max_member_sag_mm": round(max(er.max_sag for er in res.elements) * 1000.0, 3),
        "storey_drift": drift,
        "support_mode": _support_mode(info, fixed_supports),
        "support_types": [info["support_labels"][n] for n in info["support_nodes"]],
        "connections": info["connections"],
        "stability": stab,
        "nodes": len(frame.nodes), "elements": len(frame.elements),
        "equilibrium_error_kn": round(res.equilibrium_error(), 9),
        "solve_ms": round((time.perf_counter() - t0) * 1000.0, 1),
    })
    uls_used = code.uls(uls or None)[0] if code.factored else "unfactored"
    r["fabrication"] = _fabrication(fabrication)
    r["lateral_restraint"] = _lateral_restraint(lateral_restraint)
    result["design_code"]["uls_expression"] = uls_used
    result["assumptions"] = result["assumptions"] + [
        ("Hollow sections: cold-formed (EN 10219), buckling curve c" if _fabrication(fabrication) == "cold_formed"
         else "Hollow sections: hot-finished (EN 10210), buckling curve a (a0 for S460)") + ".",
        ("I-section beams: unrestrained laterally between their joints (lateral-torsional buckling checked)."
         if _lateral_restraint(lateral_restraint) == "joints" else
         "I-section beams: compression flange held continuously (lateral_restraint='continuous'): no "
         "lateral-torsional buckling check."),
        f"Design code: {code.name} ({code.basis}); gamma_M0 = {code.gamma_M0:g}, gamma_M1 = {code.gamma_M1:g}; "
        f"deflection limit span/{limit_ratio:g}; storey drift limit h/{code.storey_drift_limit_ratio:g}"
        + (" (project default: no Eurocode clause fixes it; agree it for the project)"
           if "storey_drift_limit_ratio" in code.project_defaults else "")
        + (f"; unverified values: {', '.join(code.unverified)}." if code.unverified else "."),
        ("Connections: rigid joints." if info["connections"]["mode"] == "rigid" and not info["connections"]["pinned_ends"]
         else f"Connections: {info['connections']['mode']} ({info['connections']['pinned_ends']} pinned member ends; "
              "beams release major-axis bending, braces both axes; torsion released at one end of "
              "members pinned at both)."),
        "Supports: " + ", ".join(f"{n} {k}" for k, n in sorted(_support_counts(info).items())) + " (global axes; "
        "rollers restrain vertical movement and the named horizontal direction, springs in kN/m and kNm/rad).",
        (f"Stability (EN 1993-1-1 5.2): alpha_cr {stab.get('min_alpha_cr')} -> {stab['method']}; sway imperfection "
         f"phi_x = {stab['sway_imperfection'].get('phi_x', 0.0):.5f} (m = {stab['sway_imperfection'].get('m_x', 0)}), "
         f"phi_y = {stab['sway_imperfection'].get('phi_y', 0.0):.5f} (m = {stab['sway_imperfection'].get('m_y', 0)}) "
         f"in +/-x, +/-y; local bow imperfections on {len(stab['bow_imperfection']['applied'])} member axis(es); "
         "member buckling length = member length"
         if stab.get("mode") == "auto" else "Stability check off: first-order, no sway or bow imperfections."),
        f"Load combinations ({r['design_basis']}): deflection at {SLS[0]} ({_label(SLS[1])}); member checks at "
        + ", ".join(f"{n} ({_label(f)})" for n, f, _ in ulss) + ". G = self weight, floor build-up and the weight "
        "of placed items; Q = load_kn, occupancy floor load, contents and occupants."]
    if "floor_loads" in info:
        result["floor_loads"] = info["floor_loads"]
        result["assumptions"] = result["assumptions"] + [
            "Floor loads: every bay enclosed by beams on a level carries the area load; 45-degree two-way "
            "distribution (above 2:1 one-way onto the long beams, with triangular end strips on the short "
            "beams), centroid fan for non-rectangular bays."]
    if "asset_loads" in info:
        result["asset_loads"] = info["asset_loads"]
        if info["asset_loads"]["applied"]:
            result["assumptions"] = result["assumptions"] + [
                "Asset loads: estimated self weight + in-use load per placed asset (structural-loads.json), "
                "carried by the nearest member or shared by the lever rule between two parallel members."]
    unc = _uncovered_members(frame, envelope, mat)
    slender, thin_webs = unc["class4"], unc["thin_webs"]
    indicative = INDICATIVE_FAMILIES.get(mat.family)
    failures, sug = check_failures(dcheck_mm, limit_mm, limit_ratio, umax, governing, len(slender), indicative, drift,
                                   where, len(thin_webs), unc["hints"])
    if indicative and not failures:
        # no capacity verdict without the material's own design code; deflection and stability still decide fail
        result["passed"] = None
        result["status"] = "indicative"
        result["verdict"] = method_prefix(result["confidence"]) + (
            f"INDICATIVE ONLY ({mat.name}): forces, deflection and stability are computed, but member capacity "
            f"is not checked to {indicative}, so there is no pass/fail. Deflection {dcheck_mm:.1f}mm ({SLS[0]}, "
            f"limit {limit_mm:.1f}mm){where}; utilization {umax:.2f} against the characteristic strength, for comparison only.")
        sug.append(f"Have the members designed to {indicative.split(' (')[0]} (an engineer); use the forces "
                   "in the results as the starting point.")
    else:
        result["passed"] = not failures
        result["status"] = "pass" if not failures else "fail"
        result["verdict"] = method_prefix(result["confidence"]) + (
            f"PASSED: Configured checks satisfied. Deflection {dcheck_mm:.1f}mm ({SLS[0]}, limit {limit_mm:.1f}mm){where}, "
            f"Utilization {umax:.2f} ({governing})" + _drift_note(drift, dcheck_mm / limit_mm)
            if not failures else "FAILED: " + "; ".join(failures))
    result["suggestions"] = sug
    # failing members first (over capacity, or outside the checks at any utilization), then by utilization
    failing = {tuple(frame.elements[i].tag or []) for i in unc["elements"]}
    if not indicative:
        failing |= {tuple(frame.elements[i].tag or []) for i, (u, _, _) in enumerate(envelope) if u > 1.0}
    worst = sorted(elem_util, key=lambda e: (tuple(e["source_guids"]) not in failing, -e["utilization"]))
    seen = []
    for e in worst:
        for g in e["source_guids"]:
            if g not in seen:
                seen.append(g)
    result["worst_member_guids"] = seen[:5]
    if detail:
        result["members"] = member_table(model, frame, res, envelope, deflections, spans)
        result["supports"] = support_table(frame, info, res, ulss, fixed_supports)
    if res.auto_restrained:
        result["warnings"].append(f"{len(res.auto_restrained)} unstiffened rotation(s) at pin-jointed nodes were restrained.")
    return result
