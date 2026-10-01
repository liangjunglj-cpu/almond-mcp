"""Linear-elastic 3D frame solver (direct stiffness method), numpy only.

Units are SI with kN: lengths m, forces kN, moments kNm, moduli and strengths kN/m2,
specific weight kN/m3. Written from the textbook stiffness method (Euler-Bernoulli
beams with axial, torsion and biaxial bending, 6 DOF per node); no third-party solver
code is used or wrapped.

Scope, stated so results are never over-read:
- first-order (geometrically linear), linear-elastic, static;
- straight prismatic members, rigid joints (optional axial-only truss members);
- point loads at nodes and uniform member loads (self weight is one), exact within
  each member (Hermite interpolation + the fixed-fixed particular solution);
- member checks follow EN 1993-1-1 in simplified form (see ``member_utilization``).
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


@dataclass
class Frame:
    nodes: list = field(default_factory=list)            # (x, y, z) m
    elements: list = field(default_factory=list)
    supports: dict = field(default_factory=dict)         # node -> 6 bools (True = restrained)
    nodal_loads: dict = field(default_factory=dict)      # node -> 6-vector kN / kNm, global
    member_loads: list = field(default_factory=list)     # (element index, global w vector kN/m)
    gravity: tuple | None = None                         # unit vector for self weight, e.g. (0, 0, -1)

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

    def load(self, node, fx=0.0, fy=0.0, fz=0.0, mx=0.0, my=0.0, mz=0.0):
        cur = np.asarray(self.nodal_loads.get(node, np.zeros(6)), float)
        self.nodal_loads[node] = cur + np.array([fx, fy, fz, mx, my, mz], float)

    def udl(self, element, w):
        self.member_loads.append((element, np.asarray(w, float)))


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


def fixed_end_forces(wl: np.ndarray, L: float, truss: bool) -> np.ndarray:
    """Equivalent nodal loads (local) of a uniform member load wl = (wx, wy, wz) kN/m."""
    wx, wy, wz = wl
    f = np.zeros(12)
    f[0] = f[6] = wx * L / 2
    f[1] = f[7] = wy * L / 2
    f[2] = f[8] = wz * L / 2
    if not truss:
        f[5], f[11] = wy * L ** 2 / 12, -wy * L ** 2 / 12
        f[4], f[10] = -wz * L ** 2 / 12, wz * L ** 2 / 12
    return f


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
def solve(frame: Frame, stations: int = 11, plastic: bool = False) -> FrameResult:
    """Solve and check every member; ``plastic`` uses plastic moduli (class 1/2), the
    default elastic moduli are conservative and match Karamba's elastic design check."""
    nn, ne = len(frame.nodes), len(frame.elements)
    if nn == 0 or ne == 0:
        raise ValueError("The frame has no nodes or no elements.")
    X = np.asarray(frame.nodes, float)
    ndof = nn * DOF
    K = np.zeros((ndof, ndof))
    F = np.zeros(ndof)
    geo, feq_local = [], [np.zeros(12) for _ in range(ne)]

    member_w = [np.zeros(3) for _ in range(ne)]
    for (ei, w) in frame.member_loads:
        member_w[ei] = member_w[ei] + w
    if frame.gravity is not None:
        g = np.asarray(frame.gravity, float)
        for ei, e in enumerate(frame.elements):
            member_w[ei] = member_w[ei] + g * e.material.gamma * e.section.A

    applied = np.zeros(6)
    for ei, e in enumerate(frame.elements):
        R, L = local_axes(X[e.n1], X[e.n2], e.ref)
        T = _t12(R)
        kg = T.T @ local_stiffness(e, L) @ T
        idx = np.r_[e.n1 * DOF:e.n1 * DOF + 6, e.n2 * DOF:e.n2 * DOF + 6]
        K[np.ix_(idx, idx)] += kg
        wl = R @ member_w[ei]
        fe = fixed_end_forces(wl, L, e.truss)
        feq_local[ei] = fe
        F[idx] += T.T @ fe
        applied[:3] += member_w[ei] * L
        geo.append((R, L, T, idx, wl))
    for n, v in frame.nodal_loads.items():
        F[n * DOF:n * DOF + 6] += np.asarray(v, float)
        applied[:3] += np.asarray(v, float)[:3]

    restrained = np.zeros(ndof, bool)
    for n, flags in frame.supports.items():
        restrained[n * DOF:n * DOF + 6] = flags
    # DOFs no element stiffens (rotations at truss-only nodes) carry no load: restrain them
    diag = np.abs(np.diag(K))
    scale = float(diag.max()) if diag.size else 1.0
    auto = [(i // DOF, i % DOF) for i in range(ndof) if not restrained[i] and diag[i] <= 1e-12 * scale]
    for (n, d) in auto:
        if abs(F[n * DOF + d]) > 1e-9:
            raise MechanismError(f"Load on node {n} DOF {d} that no member can carry.", [n])
        restrained[n * DOF + d] = True

    free = np.flatnonzero(~restrained)
    u = np.zeros(ndof)
    if free.size:
        Kff = K[np.ix_(free, free)]
        try:
            Lc = np.linalg.cholesky(Kff)
            if np.min(np.diag(Lc)) ** 2 < 1e-10 * np.max(np.diag(Kff)):
                raise np.linalg.LinAlgError
        except np.linalg.LinAlgError:
            raise _mechanism(Kff, free) from None
        y = np.linalg.solve(Lc, F[free])
        u[free] = np.linalg.solve(Lc.T, y)
    Rv = K @ u - F
    Rv[~restrained] = 0.0

    ers = []
    s = np.linspace(0.0, 1.0, max(2, stations))
    for ei, e in enumerate(frame.elements):
        R, L, T, idx, wl = geo[ei]
        ul = T @ u[idx]
        fl = local_stiffness(e, L) @ ul - feq_local[ei]
        ers.append(_element_result(ei, e, X, R, L, ul, fl, wl, s))
        member_utilization(ers[-1], e, plastic=plastic)
    return FrameResult(u.reshape(nn, DOF), Rv.reshape(nn, DOF), ers, applied, auto)


def _mechanism(Kff, free):
    w, v = np.linalg.eigh(Kff)
    mode = v[:, int(np.argmin(w))]
    nodes = sorted({int(free[i] // DOF) for i in np.argsort(-np.abs(mode))[:6]})
    return MechanismError("Mechanism: the structure is unstable (insufficient supports, "
                          "or a hinged chain) and cannot carry load.", nodes)


def _element_result(ei, e, X, R, L, ul, fl, wl, s):
    x = s * L
    E, s_ = e.material.E, e.section
    # axial: linear + particular solution of the uniform axial load
    u_ax = ul[0] + (ul[6] - ul[0]) * s + wl[0] * x * (L - x) / (2 * E * s_.A)
    N = E * s_.A * (ul[6] - ul[0]) / L + wl[0] * (L - 2 * x) / 2
    if e.truss:
        v = ul[1] + (ul[7] - ul[1]) * s
        w = ul[2] + (ul[8] - ul[2]) * s
        My = Mz = np.zeros_like(s)
        tors = 0.0
    else:
        h1, h2, h3, h4 = 1 - 3 * s ** 2 + 2 * s ** 3, L * (s - 2 * s ** 2 + s ** 3), 3 * s ** 2 - 2 * s ** 3, L * (-s ** 2 + s ** 3)
        d1, d2, d3, d4 = (-6 + 12 * s) / L ** 2, (-4 + 6 * s) / L, (6 - 12 * s) / L ** 2, (-2 + 6 * s) / L
        # local y: slope = rz; local z: slope = -ry. Plus fixed-fixed particular solutions.
        v = h1 * ul[1] + h2 * ul[5] + h3 * ul[7] + h4 * ul[11] + wl[1] * x ** 2 * (L - x) ** 2 / (24 * E * s_.Iz)
        w = h1 * ul[2] - h2 * ul[4] + h3 * ul[8] - h4 * ul[10] + wl[2] * x ** 2 * (L - x) ** 2 / (24 * E * s_.Iy)
        kv = d1 * ul[1] + d2 * ul[5] + d3 * ul[7] + d4 * ul[11] + wl[1] * (L ** 2 - 6 * L * x + 6 * x ** 2) / (12 * E * s_.Iz)
        kw = d1 * ul[2] - d2 * ul[4] + d3 * ul[8] - d4 * ul[10] + wl[2] * (L ** 2 - 6 * L * x + 6 * x ** 2) / (12 * E * s_.Iy)
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
