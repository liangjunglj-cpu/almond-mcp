"""Linear-elastic 3D frame solver (direct stiffness method), numpy only.

Units are SI with kN: lengths m, forces kN, moments kNm, moduli and strengths kN/m2,
specific weight kN/m3. Written from the textbook stiffness method (Euler-Bernoulli
beams with axial, torsion and biaxial bending, 6 DOF per node); no third-party solver
code is used or wrapped.

Scope, stated so results are never over-read:
- first-order (geometrically linear), linear-elastic, static;
- straight prismatic members, rigid joints unless a member end is released (pinned or
  partly released ends by static condensation; optional axial-only truss members);
- point loads at nodes and uniform or linearly varying member loads (self weight is one),
  exact within each member (Hermite interpolation + the fixed-fixed particular solution);
- member checks follow EN 1993-1-1 in simplified form (see ``member_utilization``);
- loads carry a case label (e.g. "G" permanent, "Q" variable); each case is solved once with
  the same factorised stiffness and combinations are exact superpositions (``solve_combinations``);
- stability: consistent geometric stiffness, elastic critical load factor alpha_cr
  (``critical_load_factor``) and an iterative second-order P-Delta analysis (``solve_second_order``).
Not covered: shells, second-order / P-delta, lateral-torsional buckling, dynamics,
connections, and national annexes. Results are a preliminary design check.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

DOF = 6   # ux uy uz rx ry rz per node


# ------------------------------------------------------------------ materials
@dataclass(frozen=True)
class Material:
    name: str
    E: float          # kN/m2
    G: float          # kN/m2
    gamma: float      # kN/m3
    fy: float         # kN/m2, characteristic strength used in the checks
    family: str       # "steel" | "aluminium" | "concrete" | "timber"


# Same property table as the Karamba adapter (kN/cm2 there, x1e4 here) so both engines
# analyse the same material.
MATERIALS = {
    "S235": Material("S235", 210e6, 80.76e6, 78.5, 235e3, "steel"),
    "S355": Material("S355", 210e6, 80.76e6, 78.5, 355e3, "steel"),
    "C30/37": Material("C30/37", 33e6, 13.75e6, 25.0, 30e3, "concrete"),
    "C24": Material("C24", 11e6, 0.69e6, 4.2, 24e3, "timber"),
    "AlMgSi": Material("AlMgSi", 70e6, 27e6, 27.0, 270e3, "aluminium"),
}
_ALIASES = {"steel": "S235", "s235": "S235", "s355": "S355", "concrete": "C30/37", "c30/37": "C30/37",
            "wood": "C24", "timber": "C24", "c24": "C24", "aluminium": "AlMgSi", "aluminum": "AlMgSi",
            "almgsi": "AlMgSi"}


def material(name: str) -> Material:
    key = _ALIASES.get((name or "steel").strip().lower())
    if key is None:
        raise ValueError(f"Unknown material {name!r}; use one of {sorted(set(_ALIASES))}.")
    return MATERIALS[key]


# ------------------------------------------------------------------ sections
@dataclass(frozen=True)
class Section:
    """Cross-section properties about the member's local axes (strong axis = local y,
    i.e. depth measured along local z)."""
    name: str
    shape: str
    A: float
    Iy: float
    Iz: float
    J: float
    Wel_y: float
    Wel_z: float
    Wpl_y: float
    Wpl_z: float
    buckling_curve: str      # EN 1993-1-1 Table 6.2 curve for flexural buckling
    slender: bool = False    # class 4-ish: use elastic moduli
    dims_mm: tuple = ()


def chs(d_mm: float, t_mm: float) -> Section:
    """Circular hollow section, outer diameter and wall in mm."""
    D, t = d_mm / 1000, t_mm / 1000
    if not (0 < t < D / 2):
        raise ValueError(f"CHS {d_mm}x{t_mm}: wall must be between 0 and D/2.")
    d = D - 2 * t
    A = math.pi / 4 * (D ** 2 - d ** 2)
    I = math.pi / 64 * (D ** 4 - d ** 4)
    Wel = I / (D / 2)
    Wpl = (D ** 3 - d ** 3) / 6
    return Section(f"CHS {d_mm:g}x{t_mm:g}", "chs", A, I, I, 2 * I, Wel, Wel, Wpl, Wpl, "a",
                   slender=d_mm / t_mm > 90, dims_mm=(d_mm, t_mm))


def rhs(h_mm: float, b_mm: float, t_mm: float) -> Section:
    """Rectangular hollow section (depth h along local z, width b), mm."""
    h, b, t = h_mm / 1000, b_mm / 1000, t_mm / 1000
    if not (0 < 2 * t < min(h, b)):
        raise ValueError(f"RHS {h_mm}x{b_mm}x{t_mm}: wall too thick.")
    hi, bi = h - 2 * t, b - 2 * t
    A = b * h - bi * hi
    Iy = (b * h ** 3 - bi * hi ** 3) / 12
    Iz = (h * b ** 3 - hi * bi ** 3) / 12
    Am, p = (b - t) * (h - t), 2 * ((b - t) + (h - t))
    J = 4 * Am ** 2 * t / p                     # Bredt, thin-walled closed section
    Wpl_y = (b * h ** 2 - bi * hi ** 2) / 4
    Wpl_z = (h * b ** 2 - hi * bi ** 2) / 4
    return Section(f"RHS {h_mm:g}x{b_mm:g}x{t_mm:g}", "rhs", A, Iy, Iz, J, Iy / (h / 2), Iz / (b / 2),
                   Wpl_y, Wpl_z, "a", slender=max(h_mm, b_mm) / t_mm - 3 > 42 * 1.25, dims_mm=(h_mm, b_mm, t_mm))


def rect(b_mm: float, h_mm: float) -> Section:
    """Solid rectangle (timber, concrete), width b and depth h in mm."""
    b, h = b_mm / 1000, h_mm / 1000
    a, c = max(b, h), min(b, h)
    J = a * c ** 3 * (1 / 3 - 0.21 * c / a * (1 - c ** 4 / (12 * a ** 4)))
    return Section(f"RECT {b_mm:g}x{h_mm:g}", "rect", b * h, b * h ** 3 / 12, h * b ** 3 / 12, J,
                   b * h ** 2 / 6, h * b ** 2 / 6, b * h ** 2 / 4, h * b ** 2 / 4, "c", dims_mm=(b_mm, h_mm))


def i_section(h_mm: float, b_mm: float, tw_mm: float, tf_mm: float) -> Section:
    """Doubly symmetric I-section (no root radii), depth along local z, mm."""
    h, b, tw, tf = h_mm / 1000, b_mm / 1000, tw_mm / 1000, tf_mm / 1000
    hw = h - 2 * tf
    A = 2 * b * tf + hw * tw
    Iy = (b * h ** 3 - (b - tw) * hw ** 3) / 12
    Iz = (2 * tf * b ** 3 + hw * tw ** 3) / 12
    J = (2 * b * tf ** 3 + (h - tf) * tw ** 3) / 3
    Wpl_y = b * tf * (h - tf) + tw * hw ** 2 / 4
    Wpl_z = tf * b ** 2 / 2 + hw * tw ** 2 / 4
    return Section(f"I {h_mm:g}x{b_mm:g}x{tw_mm:g}x{tf_mm:g}", "i", A, Iy, Iz, J, Iy / (h / 2), Iz / (b / 2),
                   Wpl_y, Wpl_z, "b" if h / b > 1.2 else "c", dims_mm=(h_mm, b_mm, tw_mm, tf_mm))


# ------------------------------------------------------------------ model
@dataclass
class Element:
    n1: int
    n2: int
    section: Section
    material: Material
    truss: bool = False                 # axial force only (pin-jointed bar)
    ref: tuple | None = None            # optional vector fixing local z (default: vertical plane)
    tag: object = None                  # caller's lineage (e.g. Rhino GUIDs)
    releases: tuple | None = None       # 12 bools, local DOF order (ux uy uz rx ry rz at n1, then n2)


def release_mask(start: bool = False, end: bool = False, minor: bool = True) -> tuple | None:
    """Pinned member ends: major-axis bending (ry) released at the chosen ends, and minor-axis
    bending (rz) too unless ``minor`` is False (a simple beam connection keeps plan-rotation
    continuity, which also stops pin-ended columns spinning). When both ends are pinned, torsion
    is released at the start so the member cannot twist as a rigid body."""
    m = [False] * 12
    if start:
        m[4] = True
        m[5] = minor
    if end:
        m[10] = True
        m[11] = minor
    if start and end:
        m[3] = True
    return tuple(m) if any(m) else None


@dataclass
class Frame:
    nodes: list = field(default_factory=list)            # (x, y, z) m
    elements: list = field(default_factory=list)
    supports: dict = field(default_factory=dict)         # node -> 6 bools (True = restrained)
    nodal_loads: dict = field(default_factory=dict)      # (node, case) -> 6-vector kN / kNm, global
    member_loads: list = field(default_factory=list)     # (element, global w at n1, at n2 kN/m, case)
    gravity: tuple | None = None                         # unit vector for self weight, e.g. (0, 0, -1)
    gravity_case: str = "G"                              # self weight is permanent

    def add_node(self, xyz) -> int:
        self.nodes.append(tuple(float(v) for v in xyz))
        return len(self.nodes) - 1

    def add_element(self, n1, n2, section, mat, **kw) -> int:
        self.elements.append(Element(n1, n2, section, mat, **kw))
        return len(self.elements) - 1

    def fix(self, node, dofs=(True,) * 6):
        self.supports[node] = tuple(bool(v) for v in dofs)

    def pin(self, node):
        self.fix(node, (True, True, True, False, False, False))

    def load(self, node, fx=0.0, fy=0.0, fz=0.0, mx=0.0, my=0.0, mz=0.0, case="Q"):
        cur = np.asarray(self.nodal_loads.get((node, case), np.zeros(6)), float)
        self.nodal_loads[(node, case)] = cur + np.array([fx, fy, fz, mx, my, mz], float)

    def udl(self, element, w, case="Q"):
        """Uniform member load, global vector kN/m."""
        w = np.asarray(w, float)
        self.member_loads.append((element, w, w, case))

    def linear_load(self, element, w_start, w_end, case="Q"):
        """Member load varying linearly from w_start at n1 to w_end at n2 (global vectors, kN/m)."""
        self.member_loads.append((element, np.asarray(w_start, float), np.asarray(w_end, float), case))

    def cases(self) -> list:
        found = {c for (_, c) in self.nodal_loads} | {m[3] for m in self.member_loads}
        if self.gravity is not None:
            found.add(self.gravity_case)
        return sorted(found)

    def split_element(self, ei: int, t: float) -> int:
        """Insert a node at fraction t along element ei, splitting it in two (same section,
        material and lineage; member loads follow both halves). Returns the new node."""
        e = self.elements[ei]
        p1, p2 = np.asarray(self.nodes[e.n1]), np.asarray(self.nodes[e.n2])
        k = self.add_node(p1 + t * (p2 - p1))
        n2 = e.n2
        e.n2 = k
        rel_end = None
        if e.releases:                                          # end releases move to the new outer part
            rel_end = tuple([False] * 6 + list(e.releases[6:])) if any(e.releases[6:]) else None
            e.releases = tuple(list(e.releases[:6]) + [False] * 6) if any(e.releases[:6]) else None
        new = self.add_element(k, n2, e.section, e.material, truss=e.truss, ref=e.ref, tag=e.tag,
                               releases=rel_end)
        kept, added = [], []
        for (j, wa, wb, case) in self.member_loads:
            if j != ei:
                kept.append((j, wa, wb, case))
                continue
            wm = wa + t * (wb - wa)                             # linear loads split at the new node
            kept.append((ei, wa, wm, case))
            added.append((new, wm, wb, case))
        self.member_loads = kept + added
        return k


class MechanismError(ValueError):
    """The stiffness matrix is singular: the structure (or part of it) can move freely."""
    def __init__(self, message, nodes=()):
        super().__init__(message)
        self.nodes = list(nodes)


# ------------------------------------------------------------------ element maths
def local_axes(p1, p2, ref=None):
    """Rotation matrix whose rows are the local x, y, z axes in global coordinates.
    x runs n1 -> n2; z lies in the vertical plane through the member (up for a horizontal
    member), so gravity bends a horizontal member about its strong local y axis."""
    x = np.subtract(p2, p1, dtype=float)
    L = float(np.linalg.norm(x))
    if L <= 0:
        raise ValueError("Zero-length element.")
    x /= L
    if ref is not None:
        z = np.asarray(ref, float) - np.dot(ref, x) * x
    elif abs(x[2]) < 0.999999:
        z = np.array([0.0, 0.0, 1.0]) - x[2] * x
    else:                                   # vertical member: local z along global X
        z = np.array([1.0, 0.0, 0.0]) - x[0] * x
    z /= np.linalg.norm(z)
    y = np.cross(z, x)
    return np.vstack([x, y, z]), L


def local_stiffness(e: Element, L: float) -> np.ndarray:
    E, G, s = e.material.E, e.material.G, e.section
    k = np.zeros((12, 12))
    ea = E * s.A / L
    k[0, 0] = k[6, 6] = ea
    k[0, 6] = k[6, 0] = -ea
    if e.truss:
        return k
    gj = G * s.J / L
    k[3, 3] = k[9, 9] = gj
    k[3, 9] = k[9, 3] = -gj
    # bending in the local x-y plane (uy, rz) about local z: Iz
    a, b, c, d = 12 * E * s.Iz / L ** 3, 6 * E * s.Iz / L ** 2, 4 * E * s.Iz / L, 2 * E * s.Iz / L
    for (i, j, v) in ((1, 1, a), (1, 5, b), (1, 7, -a), (1, 11, b), (5, 5, c), (5, 7, -b), (5, 11, d),
                      (7, 7, a), (7, 11, -b), (11, 11, c)):
        k[i, j] = k[j, i] = v
    # bending in the local x-z plane (uz, ry) about local y: Iy (ry = -duz/dx)
    a, b, c, d = 12 * E * s.Iy / L ** 3, 6 * E * s.Iy / L ** 2, 4 * E * s.Iy / L, 2 * E * s.Iy / L
    for (i, j, v) in ((2, 2, a), (2, 4, -b), (2, 8, -a), (2, 10, -b), (4, 4, c), (4, 8, b), (4, 10, d),
                      (8, 8, a), (8, 10, b), (10, 10, c)):
        k[i, j] = k[j, i] = v
    return k


def fixed_end_forces(wa: np.ndarray, wb: np.ndarray, L: float, truss: bool) -> np.ndarray:
    """Equivalent nodal loads (local) of a member load varying linearly from wa at n1 to wb
    at n2 (local (wx, wy, wz) kN/m). Uniform loads are wa == wb."""
    f = np.zeros(12)
    f[0], f[6] = L * (2 * wa[0] + wb[0]) / 6, L * (wa[0] + 2 * wb[0]) / 6
    for k in (1, 2):
        f[k], f[k + 6] = L * (7 * wa[k] + 3 * wb[k]) / 20, L * (3 * wa[k] + 7 * wb[k]) / 20
    if not truss:
        m1y, m2y = L ** 2 * (3 * wa[1] + 2 * wb[1]) / 60, L ** 2 * (2 * wa[1] + 3 * wb[1]) / 60
        m1z, m2z = L ** 2 * (3 * wa[2] + 2 * wb[2]) / 60, L ** 2 * (2 * wa[2] + 3 * wb[2]) / 60
        f[5], f[11] = m1y, -m2y
        f[4], f[10] = -m1z, m2z
    return f


def condense(kl: np.ndarray, fes: list, rel) -> tuple:
    """Static condensation of released local DOFs: (k, [f per case], recovery | None).

    Released DOFs carry no end force, so u_r = K_rr^-1 (f_r - K_rc u_c); the kept part is
    K_cc - K_cr K_rr^-1 K_rc with equivalent loads f_c - K_cr K_rr^-1 f_r."""
    if not rel or not any(rel):
        return kl, fes, None
    r = np.flatnonzero(rel)
    c = np.flatnonzero(~np.asarray(rel, bool))
    Krr = kl[np.ix_(r, r)]
    if np.linalg.cond(Krr) > 1e12:
        raise ValueError("Released end DOFs leave the member unstable (e.g. torsion released at both ends).")
    inv = np.linalg.inv(Krr)
    Kcr, Krc = kl[np.ix_(c, r)], kl[np.ix_(r, c)]
    kc = np.zeros_like(kl)
    kc[np.ix_(c, c)] = kl[np.ix_(c, c)] - Kcr @ inv @ Krc
    out = []
    for fe in fes:
        f = np.zeros(12)
        f[c] = fe[c] - Kcr @ inv @ fe[r]
        out.append(f)
    return kc, out, (r, c, inv, Krc)


def _t12(R):
    T = np.zeros((12, 12))
    for i in range(4):
        T[3 * i:3 * i + 3, 3 * i:3 * i + 3] = R
    return T


# ------------------------------------------------------------------ results
@dataclass
class ElementResult:
    index: int
    length: float
    end_forces: np.ndarray          # local, member-end forces: k u - f_eq (12)
    stations: np.ndarray            # (n, 3) global station points (undeformed), m
    disp: np.ndarray                # (n, 3) global translations at stations, m
    N: np.ndarray                   # (n,) axial force, tension positive, kN
    My: np.ndarray                  # (n,) moment about local y, kNm
    Mz: np.ndarray                  # (n,) moment about local z, kNm
    T: float                        # torsion, kNm
    max_sag: float                  # max deflection relative to the displaced chord, m
    utilization: float = float("nan")
    util_detail: dict = field(default_factory=dict)


@dataclass
class FrameResult:
    displacements: np.ndarray       # (n_nodes, 6) global
    reactions: np.ndarray           # (n_nodes, 6) global, nonzero at supports only
    elements: list                  # ElementResult per element
    applied: np.ndarray             # total applied load vector (6) incl. member loads, about origin
    auto_restrained: list           # (node, dof) restrained because no element provides stiffness
    combination: dict = field(default_factory=dict)   # case -> factor this result represents
    iterations: int = 0                                 # second-order iterations (0 = first order)
    converged: bool = True

    @property
    def max_displacement(self) -> float:
        best = float(np.max(np.linalg.norm(self.displacements[:, :3], axis=1))) if len(self.displacements) else 0.0
        for er in self.elements:
            best = max(best, float(np.max(np.linalg.norm(er.disp, axis=1))))
        return best

    @property
    def max_utilization(self) -> float:
        vals = [er.utilization for er in self.elements if not math.isnan(er.utilization)]
        return max(vals) if vals else float("nan")

    def equilibrium_error(self) -> float:
        """|sum of reactions + applied loads| in force terms (kN): should be ~0."""
        return float(np.linalg.norm(self.reactions[:, :3].sum(axis=0) + self.applied[:3]))


# ------------------------------------------------------------------ solve
def solve(frame: Frame, stations: int = 11, plastic: bool = False, combination: dict | None = None) -> FrameResult:
    """Solve and check every member; ``plastic`` uses plastic moduli (class 1/2), the
    default elastic moduli are conservative and match Karamba's elastic design check.
    ``combination`` maps load case -> factor (default: every case x 1.0)."""
    combo = combination or {c: 1.0 for c in frame.cases()}
    return solve_combinations(frame, {"result": combo}, stations, plastic)["result"]


class _Assembly:
    """Everything one factorisation gives: stiffness, per-case loads and displacements, restraints."""


def _assemble(frame: Frame) -> _Assembly:
    nn, ne = len(frame.nodes), len(frame.elements)
    if nn == 0 or ne == 0:
        raise ValueError("The frame has no nodes or no elements.")
    m = _Assembly()
    m.frame, m.X, m.ndof = frame, np.asarray(frame.nodes, float), nn * DOF
    m.cases = cases = frame.cases() or ["-"]
    ndof = m.ndof
    K = np.zeros((ndof, ndof))
    F = {c: np.zeros(ndof) for c in cases}
    member_w = {c: [[np.zeros(3), np.zeros(3)] for _ in range(ne)] for c in cases}    # global (at n1, at n2)
    for (ei, wa, wb, c) in frame.member_loads:
        member_w[c][ei][0] = member_w[c][ei][0] + wa
        member_w[c][ei][1] = member_w[c][ei][1] + wb
    if frame.gravity is not None:
        g = np.asarray(frame.gravity, float)
        for ei, e in enumerate(frame.elements):
            sw = g * e.material.gamma * e.section.A
            member_w[frame.gravity_case][ei][0] = member_w[frame.gravity_case][ei][0] + sw
            member_w[frame.gravity_case][ei][1] = member_w[frame.gravity_case][ei][1] + sw

    applied = {c: np.zeros(6) for c in cases}
    geo, kloc = [], []
    wl = {c: [] for c in cases}
    feq = {c: [] for c in cases}
    for ei, e in enumerate(frame.elements):
        R, L = local_axes(m.X[e.n1], m.X[e.n2], e.ref)
        T = _t12(R)
        kl = local_stiffness(e, L)
        idx = np.r_[e.n1 * DOF:e.n1 * DOF + 6, e.n2 * DOF:e.n2 * DOF + 6]
        fes = []
        for c in cases:
            w = (R @ member_w[c][ei][0], R @ member_w[c][ei][1])
            fe = fixed_end_forces(w[0], w[1], L, e.truss)
            wl[c].append(w)
            feq[c].append(fe)
            fes.append(fe)
            applied[c][:3] += (member_w[c][ei][0] + member_w[c][ei][1]) * L / 2
        kc, fcs, rec = condense(kl, fes, None if e.truss else e.releases)
        K[np.ix_(idx, idx)] += T.T @ kc @ T
        for c, fc in zip(cases, fcs):
            F[c][idx] += T.T @ fc
        geo.append((R, L, T, idx))
        kloc.append((kl, rec))
    for (n, c), v in frame.nodal_loads.items():
        F[c][n * DOF:n * DOF + 6] += np.asarray(v, float)
        applied[c][:3] += np.asarray(v, float)[:3]

    restrained = np.zeros(ndof, bool)
    for n, flags in frame.supports.items():
        restrained[n * DOF:n * DOF + 6] = flags
    # DOFs no element stiffens (rotations at truss-only nodes) carry no load: restrain them
    diag = np.abs(np.diag(K))
    scale = float(diag.max()) if diag.size else 1.0
    auto = [(i // DOF, i % DOF) for i in range(ndof) if not restrained[i] and diag[i] <= 1e-12 * scale]
    for (n, d) in auto:
        if any(abs(F[c][n * DOF + d]) > 1e-9 for c in cases):
            raise MechanismError(f"Load on node {n} DOF {d} that no member can carry.", [n])
        restrained[n * DOF + d] = True

    Lc, free = None, np.flatnonzero(~restrained)
    for _attempt in range(64):
        free = np.flatnonzero(~restrained)
        if not free.size:
            break
        Kff = K[np.ix_(free, free)]
        try:
            Lc = np.linalg.cholesky(Kff)
            if np.min(np.diag(Lc)) ** 2 < 1e-10 * np.max(np.diag(Kff)):
                raise np.linalg.LinAlgError
            break
        except np.linalg.LinAlgError:
            spurious = _spurious_rotation_dofs(Kff, free, [F[c][free] for c in cases])
            if not spurious:
                raise _mechanism(Kff, free) from None
            for i in spurious:                                  # unloaded, rotation-only: pin one DOF per mode
                restrained[i] = True
                auto.append((int(i // DOF), int(i % DOF)))
    u = {c: np.zeros(ndof) for c in cases}
    Linv = None
    if free.size:
        # numpy has no triangular solver: invert the Cholesky factor once, then every solve is two
        # matrix-vector products (many right-hand sides: cases, imperfections, buckling)
        Linv = np.linalg.inv(Lc)
        for c in cases:
            u[c][free] = Linv.T @ (Linv @ F[c][free])
    m.K, m.F, m.u, m.geo, m.kloc, m.wl, m.feq, m.applied = K, F, u, geo, kloc, wl, feq, applied
    m.restrained, m.auto, m.free, m.Lc, m.Linv = restrained, auto, free, Lc, Linv
    return m


def _factors(m: _Assembly, combo: dict) -> dict:
    return {c: float(combo.get(c, 0.0)) for c in m.cases}


def _solve_linear(m: _Assembly, rhs: np.ndarray) -> np.ndarray:
    u = np.zeros(m.ndof)
    if m.free.size:
        u[m.free] = m.Linv.T @ (m.Linv @ rhs[m.free])
    return u


def load_vector(frame_or_assembly, combination: dict) -> np.ndarray:
    """Global load vector (nodal + equivalent member loads) of a combination."""
    m = frame_or_assembly if isinstance(frame_or_assembly, _Assembly) else _assemble(frame_or_assembly)
    f = _factors(m, combination)
    return sum(f[c] * m.F[c] for c in m.cases)


def _local_end_displacements(m, ei, uc, fe):
    R, L, T, idx = m.geo[ei]
    kl, rec = m.kloc[ei]
    ul = T @ uc[idx]
    if rec is not None:                                         # recover the member's own released rotations
        r, cc, inv, Krc = rec
        ul[r] = inv @ (fe[r] - Krc @ ul[cc])
    return ul


def _axial_forces(m: _Assembly, f: dict, uc: np.ndarray) -> np.ndarray:
    """Mean axial force per member (tension positive) for displacements uc: EA * elongation / L."""
    N = np.zeros(len(m.frame.elements))
    for ei, e in enumerate(m.frame.elements):
        fe = sum(f[c] * m.feq[c][ei] for c in m.cases)
        ul = _local_end_displacements(m, ei, uc, fe)
        N[ei] = e.material.E * e.section.A * (ul[6] - ul[0]) / m.geo[ei][1]
    return N


def _results(m: _Assembly, combo: dict, uc: np.ndarray, Fc: np.ndarray, stations: int, plastic: bool,
             Kt: np.ndarray | None = None, N: np.ndarray | None = None) -> "FrameResult":
    frame, f = m.frame, _factors(m, combo)
    s = np.linspace(0.0, 1.0, max(2, stations))
    Rv = (m.K if Kt is None else Kt) @ uc - Fc
    Rv[~m.restrained] = 0.0
    ers = []
    for ei, e in enumerate(frame.elements):
        R, L, T, idx = m.geo[ei]
        kl, _ = m.kloc[ei]
        fe = sum(f[c] * m.feq[c][ei] for c in m.cases)
        ul = _local_end_displacements(m, ei, uc, fe)
        k_end = kl if N is None else kl + geometric_stiffness(e, L, N[ei])
        fl = k_end @ ul - fe
        w = (sum(f[c] * m.wl[c][ei][0] for c in m.cases), sum(f[c] * m.wl[c][ei][1] for c in m.cases))
        ers.append(_element_result(ei, e, m.X, R, L, ul, fl, w, s))
        member_utilization(ers[-1], e, plastic=plastic)
    return FrameResult(uc.reshape(len(frame.nodes), DOF), Rv.reshape(len(frame.nodes), DOF), ers,
                       sum(f[c] * m.applied[c] for c in m.cases), m.auto, dict(combo))


def solve_combinations(frame: Frame, combinations: dict, stations: int = 11, plastic: bool = False,
                       extra: dict | None = None) -> dict:
    """Solve every load case once (one factorisation) and return {name: FrameResult} for each
    combination {case: factor}; cases a combination does not name get factor 0. ``extra`` adds
    a global load vector to named combinations (e.g. sway imperfections)."""
    m = _assemble(frame)
    out = {}
    for name, combo in combinations.items():
        f = _factors(m, combo)
        uc = sum(f[c] * m.u[c] for c in m.cases)
        Fc = sum(f[c] * m.F[c] for c in m.cases)
        if extra and name in extra:
            uc = uc + _solve_linear(m, extra[name])
            Fc = Fc + extra[name]
        out[name] = _results(m, combo, uc, Fc, stations, plastic)
    return out


# ------------------------------------------------------------------ stability
def geometric_stiffness(e: Element, L: float, N: float) -> np.ndarray:
    """Consistent geometric stiffness (local, 12x12) of a member under axial force N (tension
    positive): N/30L [36 3L -36 3L; 3L 4L^2 -3L -L^2; ...] in each bending plane, plus the
    Wagner term N*Ip/(A*L) in torsion. Truss bars carry the string term N/L laterally."""
    kg = np.zeros((12, 12))
    if e.truss:
        for a, b in ((1, 7), (2, 8)):
            kg[a, a] = kg[b, b] = N / L
            kg[a, b] = kg[b, a] = -N / L
        return kg
    c = N / (30 * L)
    v = c * np.array([[36, 3 * L, -36, 3 * L], [3 * L, 4 * L ** 2, -3 * L, -L ** 2],
                      [-36, -3 * L, 36, -3 * L], [3 * L, -L ** 2, -3 * L, 4 * L ** 2]])
    for dofs, sgn in (((1, 5, 7, 11), 1.0), ((2, 4, 8, 10), -1.0)):     # x-z plane: ry = -dw/dx
        S = np.diag([1.0, sgn, 1.0, sgn])
        kg[np.ix_(dofs, dofs)] += S @ v @ S
    s = e.section
    t = N * (s.Iy + s.Iz) / (s.A * L)
    kg[3, 3] += t
    kg[9, 9] += t
    kg[3, 9] -= t
    kg[9, 3] -= t
    return kg


def _kg_global(m: _Assembly, N: np.ndarray) -> np.ndarray:
    KG = np.zeros((m.ndof, m.ndof))
    for ei, e in enumerate(m.frame.elements):
        R, L, T, idx = m.geo[ei]
        kg = geometric_stiffness(e, L, N[ei])
        _, rec = m.kloc[ei]
        if rec is not None:                                     # same condensation as the elastic stiffness
            r, cc, inv, Krc = rec
            Tc = np.eye(12)
            Tc[np.ix_(r, r)] = 0.0
            Tc[np.ix_(r, cc)] = -inv @ Krc
            kg = Tc.T @ kg @ Tc
        KG[np.ix_(idx, idx)] += T.T @ kg @ T
    return KG


def critical_load_factor(frame_or_assembly, combination: dict, extra: np.ndarray | None = None) -> tuple:
    """Elastic critical load factor alpha_cr of a combination (EN 1993-1-1 5.2.1) and its buckling
    mode (global displacement vector, max translation 1): smallest alpha with det(K + alpha K_G) = 0,
    K_G from the first-order axial forces. inf when nothing is in compression."""
    m = frame_or_assembly if isinstance(frame_or_assembly, _Assembly) else _assemble(frame_or_assembly)
    f = _factors(m, combination)
    uc = sum(f[c] * m.u[c] for c in m.cases)
    if extra is not None:
        uc = uc + _solve_linear(m, extra)
    N = _axial_forces(m, f, uc)
    if not m.free.size or np.min(N) >= -1e-9 * max(1.0, float(np.max(np.abs(N)))):
        return math.inf, np.zeros(m.ndof)
    KG = _kg_global(m, N)[np.ix_(m.free, m.free)]
    Li = m.Linv
    A = Li @ (-KG) @ Li.T                                       # K phi = -alpha KG phi  ->  A y = (1/alpha) y
    mu, Y = np.linalg.eigh((A + A.T) / 2)
    k = int(np.argmax(mu))
    if mu[k] <= 1e-12:
        return math.inf, np.zeros(m.ndof)
    mode = np.zeros(m.ndof)
    mode[m.free] = Li.T @ Y[:, k]
    trans = np.abs(mode.reshape(-1, DOF)[:, :3]).max()
    return float(1.0 / mu[k]), mode / (trans if trans > 0 else 1.0)


def solve_second_order(frame_or_assembly, combination: dict, extra: np.ndarray | None = None, stations: int = 11,
                       plastic: bool = False, max_iter: int = 50, tol: float = 1e-6) -> "FrameResult":
    """Second-order (P-Delta) analysis: solve (K + K_G(N)) u = F, updating the axial forces N until
    they settle. Raises MechanismError if the frame loses stability under the combination."""
    m = frame_or_assembly if isinstance(frame_or_assembly, _Assembly) else _assemble(frame_or_assembly)
    f = _factors(m, combination)
    Fc = sum(f[c] * m.F[c] for c in m.cases) + (extra if extra is not None else 0.0)
    uc = sum(f[c] * m.u[c] for c in m.cases) + (_solve_linear(m, extra) if extra is not None else 0.0)
    N = _axial_forces(m, f, uc)
    it, converged, Kt = 0, False, m.K
    for it in range(1, max_iter + 1):
        Kt = m.K + _kg_global(m, N)
        Kff = Kt[np.ix_(m.free, m.free)]
        try:
            np.linalg.cholesky(Kff)                             # positive definite: still stable
        except np.linalg.LinAlgError:
            raise MechanismError("Instability: the frame buckles under this combination (second-order "
                                 "stiffness not positive definite).") from None
        uc = np.zeros(m.ndof)
        uc[m.free] = np.linalg.solve(Kff, Fc[m.free])
        N_new = _axial_forces(m, f, uc)
        change = float(np.max(np.abs(N_new - N))) if N.size else 0.0
        N = N_new
        if change <= tol * max(1.0, float(np.max(np.abs(N)))):
            converged = True
            break
    res = _results(m, combination, uc, Fc, stations, plastic, Kt=Kt, N=N)
    res.iterations, res.converged = it, converged
    return res


def _spurious_rotation_dofs(Kff, free, loads) -> list:
    """Zero-energy modes that move only rotations and that no load acts on (e.g. a member split
    into pieces whose torsion is released at its far end twisting as a group). Such modes do not
    affect the solution; returns one global DOF per mode to restrain, or [] if any zero-energy
    mode moves a translation or is loaded (a real mechanism)."""
    w, v = np.linalg.eigh(Kff)
    tol = 1e-9 * max(float(np.max(np.abs(w))), 1e-30)
    picks = []
    for k in np.flatnonzero(np.abs(w) <= tol):
        mode = v[:, k]
        trans = np.abs(mode[(free % DOF) < 3])
        if trans.size and trans.max() > 1e-6 * np.abs(mode).max():
            return []
        if any(abs(float(f @ mode)) > 1e-9 * max(float(np.abs(f).max()), 1.0) for f in loads):
            return []
        i = int(free[int(np.argmax(np.abs(mode)))])
        if i not in picks:
            picks.append(i)
    return picks


def _mechanism(Kff, free):
    w, v = np.linalg.eigh(Kff)
    mode = v[:, int(np.argmin(w))]
    nodes = sorted({int(free[i] // DOF) for i in np.argsort(-np.abs(mode))[:6]})
    return MechanismError("Mechanism: the structure is unstable (insufficient supports, "
                          "or a hinged chain) and cannot carry load.", nodes)


def _particular(wa, wb, x, L):
    """Fixed-fixed deflection x EI under a load varying linearly wa -> wb, and its 2nd derivative:
    v = x^2 (L-x)^2 [wa (3L - x) + wb (x + 2L)] / (120 L)."""
    a, b = 3 * L * wa + 2 * L * wb, wb - wa
    p = x ** 2 * (L - x) ** 2
    dp, ddp = 4 * x ** 3 - 6 * L * x ** 2 + 2 * L ** 2 * x, 12 * x ** 2 - 12 * L * x + 2 * L ** 2
    return p * (a + b * x) / (120 * L), (ddp * (a + b * x) + 2 * b * dp) / (120 * L)


def _element_result(ei, e, X, R, L, ul, fl, wl, s):
    x = s * L
    E, s_ = e.material.E, e.section
    wa, wb = wl
    # axial: linear + particular solution of the (linearly varying) axial load
    u_ax = ul[0] + (ul[6] - ul[0]) * s + (L * (2 * wa[0] + wb[0]) * x / 6 - wa[0] * x ** 2 / 2
                                          - (wb[0] - wa[0]) * x ** 3 / (6 * L)) / (E * s_.A)
    N = E * s_.A * (ul[6] - ul[0]) / L + L * (2 * wa[0] + wb[0]) / 6 - wa[0] * x - (wb[0] - wa[0]) * x ** 2 / (2 * L)
    if e.truss:
        v = ul[1] + (ul[7] - ul[1]) * s
        w = ul[2] + (ul[8] - ul[2]) * s
        My = Mz = np.zeros_like(s)
        tors = 0.0
    else:
        h1, h2, h3, h4 = 1 - 3 * s ** 2 + 2 * s ** 3, L * (s - 2 * s ** 2 + s ** 3), 3 * s ** 2 - 2 * s ** 3, L * (-s ** 2 + s ** 3)
        d1, d2, d3, d4 = (-6 + 12 * s) / L ** 2, (-4 + 6 * s) / L, (6 - 12 * s) / L ** 2, (-2 + 6 * s) / L
        # local y: slope = rz; local z: slope = -ry. Plus fixed-fixed particular solutions.
        pv, ppv = _particular(wa[1], wb[1], x, L)
        pw, ppw = _particular(wa[2], wb[2], x, L)
        v = h1 * ul[1] + h2 * ul[5] + h3 * ul[7] + h4 * ul[11] + pv / (E * s_.Iz)
        w = h1 * ul[2] - h2 * ul[4] + h3 * ul[8] - h4 * ul[10] + pw / (E * s_.Iy)
        kv = d1 * ul[1] + d2 * ul[5] + d3 * ul[7] + d4 * ul[11] + ppv / (E * s_.Iz)
        kw = d1 * ul[2] - d2 * ul[4] + d3 * ul[8] - d4 * ul[10] + ppw / (E * s_.Iy)
        Mz = E * s_.Iz * kv
        My = -E * s_.Iy * kw
        tors = float(fl[9])
    loc = np.stack([u_ax, v, w], axis=1)
    disp = loc @ R                                   # back to global
    pts = X[e.n1] + np.outer(s, X[e.n2] - X[e.n1])
    chord = np.outer(1 - s, disp[0]) + np.outer(s, disp[-1])
    sag = float(np.max(np.linalg.norm(disp - chord, axis=1)))
    return ElementResult(ei, L, fl, pts, disp, N, My, Mz, tors, sag)


# ------------------------------------------------------------------ member checks
_ALPHA = {"a0": 0.13, "a": 0.21, "b": 0.34, "c": 0.49, "d": 0.76}


def member_utilization(er: ElementResult, e: Element, gamma_m0: float = 1.0, gamma_m1: float = 1.0,
                       plastic: bool = False) -> None:
    """EN 1993-1-1, simplified, for steel/aluminium (strength checks only for the others):
    - cross-section 6.2.1(7): |N|/N_Rd + |My|/M_Rd,y + |Mz|/M_Rd,z (CHS: resultant moment),
      elastic moduli by default (conservative, any class but 4), plastic when ``plastic`` and
      the section is compact;
    - flexural buckling 6.3.1 for compression members with L_cr = member length and the
      section's buckling curve; combined linearly with bending (k = 1, conservative).
    Lateral-torsional buckling and shear/torsion interaction are not checked."""
    s, m = e.section, e.material
    fy = m.fy
    elastic = not plastic or s.slender or m.family in ("timber", "concrete")
    Wy, Wz = (s.Wel_y, s.Wel_z) if elastic else (s.Wpl_y, s.Wpl_z)
    Npl = s.A * fy / gamma_m0
    if s.shape == "chs":
        mterm = np.hypot(er.My, er.Mz) / (Wy * fy / gamma_m0)
    else:
        mterm = np.abs(er.My) / (Wy * fy / gamma_m0) + np.abs(er.Mz) / (Wz * fy / gamma_m0)
    cs = np.abs(er.N) / Npl + mterm
    detail = {"cross_section": float(np.max(cs)), "moduli": "elastic" if elastic else "plastic"}
    util = float(np.max(cs))
    ncomp = float(max(0.0, -np.min(er.N)))
    if ncomp > 0 and m.family in ("steel", "aluminium"):
        imin = min(s.Iy, s.Iz)
        ncr = math.pi ** 2 * m.E * imin / er.length ** 2
        lam = math.sqrt(s.A * fy / ncr)
        phi = 0.5 * (1 + _ALPHA[s.buckling_curve] * (lam - 0.2) + lam ** 2)
        chi = min(1.0, 1.0 / (phi + math.sqrt(max(phi ** 2 - lam ** 2, 0.0))))
        buck = ncomp / (chi * s.A * fy / gamma_m1) + float(np.max(mterm)) * gamma_m1 / gamma_m0
        detail.update({"buckling": buck, "slenderness": lam, "chi": chi})
        util = max(util, buck)
    sig = np.abs(er.N) / s.A + (np.hypot(er.My, er.Mz) / s.Wel_y if s.shape == "chs"
                                else np.abs(er.My) / s.Wel_y + np.abs(er.Mz) / s.Wel_z)
    detail["max_stress_mpa"] = float(np.max(sig)) / 1000.0
    er.utilization = util
    er.util_detail = detail


def prepare(frame: Frame) -> "_Assembly":
    """Assemble and factorise once; pass the result to the analysis functions to reuse it."""
    return _assemble(frame)


def solve_linear(frame_or_assembly, combination: dict, extra: np.ndarray | None = None, stations: int = 11,
                 plastic: bool = False) -> "FrameResult":
    """First-order result of one combination, plus an optional extra global load vector."""
    m = frame_or_assembly if isinstance(frame_or_assembly, _Assembly) else _assemble(frame_or_assembly)
    f = _factors(m, combination)
    uc = sum(f[c] * m.u[c] for c in m.cases)
    Fc = sum(f[c] * m.F[c] for c in m.cases)
    if extra is not None:
        uc = uc + _solve_linear(m, extra)
        Fc = Fc + extra
    return _results(m, combination, uc, Fc, stations, plastic)


def mode_result(frame_or_assembly, mode: np.ndarray, stations: int = 13) -> "FrameResult":
    """Element shapes of a displacement vector (e.g. a buckling mode) with no member loads."""
    m = frame_or_assembly if isinstance(frame_or_assembly, _Assembly) else _assemble(frame_or_assembly)
    return _results(m, {}, mode, np.zeros(m.ndof), stations, False)


def axial_forces(frame_or_assembly, combination: dict) -> np.ndarray:
    """First-order mean axial force per element (tension positive) for a combination."""
    m = frame_or_assembly if isinstance(frame_or_assembly, _Assembly) else _assemble(frame_or_assembly)
    f = _factors(m, combination)
    return _axial_forces(m, f, sum(f[c] * m.u[c] for c in m.cases))
