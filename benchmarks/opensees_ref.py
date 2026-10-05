"""The same frame_solver model rebuilt in OpenSees (OpenSeesPy), as an independent reference.

Conventions mapped one to one: local z of every member = the vecxz of its geomTransf (Almond's
vertical-plane rule), Iy about local y, member end releases as zeroLength links in the member's
local axes with the released directions left out (stiff penalty springs elsewhere), support springs
as zeroLength springs to a fixed ground node (global axes), truss bars as
Truss elements (self weight lumped to their nodes), linearly varying member loads as 40 partial
uniform loads. Rotations of nodes that only bars reach are fixed (Almond restrains them too).

Buckling (alpha_cr) uses OpenSees' own tangent: K_G = (K_T(lam) - K_T(~0)) / lam at a small load
factor, PDelta transformations on a refined mesh. Bars must then be PDelta beams with negligible
bending stiffness (``bars_as_beams``): a corotational truss tangent also changes with the bars'
rotation, which pollutes that difference."""
from __future__ import annotations

import copy
import math

import numpy as np

import openseespy.opensees as ops

from almond_mcp import frame_solver as fs

K_RIGID = 1e12
_GROUND: dict = {}                                     # frame node -> its spring's ground node (last build)


def _member_w(frame, combo):
    w = [[np.zeros(3), np.zeros(3)] for _ in frame.elements]
    for (ei, wa, wb, c) in frame.member_loads:
        k = combo.get(c, 0.0)
        w[ei][0] = w[ei][0] + k * wa
        w[ei][1] = w[ei][1] + k * wb
    if frame.gravity is not None:
        k = combo.get(frame.gravity_case, 0.0)
        g = np.asarray(frame.gravity, float)
        for ei, e in enumerate(frame.elements):
            w[ei][0] = w[ei][0] + k * g * e.material.gamma * e.section.A
            w[ei][1] = w[ei][1] + k * g * e.material.gamma * e.section.A
    return w


def build(frame: fs.Frame, combo: dict, second_order: bool = False, scale: float = 1.0, extra=None) -> int:
    """(Re)build the OpenSees domain for one combination; returns the number of frame nodes."""
    ops.wipe()
    ops.model("basic", "-ndm", 3, "-ndf", 6)
    X = np.asarray(frame.nodes, float)
    for i, p in enumerate(X):
        ops.node(i + 1, *p)
    beam_nodes = {n for e in frame.elements if not e.truss for n in (e.n1, e.n2)}
    for i in range(len(X)):
        flags = list(frame.supports.get(i, (False,) * 6))
        if i not in beam_nodes:
            flags[3:] = [True, True, True]
        if any(flags):
            ops.fix(i + 1, *[int(v) for v in flags])
    ops.uniaxialMaterial("Elastic", 1, K_RIGID)
    dup = len(X) + 1
    ground = {}
    for n, ks in frame.springs.items():                 # support springs: zeroLength to a fixed ground node
        dirs = [d for d in range(6) if ks[d] and not frame.supports.get(n, (False,) * 6)[d]]
        if not dirs:
            continue
        ops.node(dup, *X[n])
        ops.fix(dup, 1, 1, 1, 1, 1, 1)
        for d in dirs:
            ops.uniaxialMaterial("Elastic", 10 ** 7 + 6 * n + d, ks[d])
        ops.element("zeroLength", 2 * 10 ** 6 + n, dup, n + 1, "-mat", *[10 ** 7 + 6 * n + d for d in dirs],
                    "-dir", *[d + 1 for d in dirs])
        ground[n] = dup
        dup += 1
    _GROUND.clear()
    _GROUND.update(ground)
    axes = {}
    for ei, e in enumerate(frame.elements):
        R, L = fs.local_axes(X[e.n1], X[e.n2], e.ref)
        axes[ei] = (R, L)
        s, m = e.section, e.material
        if e.truss:
            ops.uniaxialMaterial("Elastic", 10 + ei, m.E)
            ops.element("corotTruss" if second_order else "Truss", ei + 1, e.n1 + 1, e.n2 + 1, s.A, 10 + ei)
            continue
        ops.geomTransf("PDelta" if second_order else "Linear", ei + 1, *R[2])
        ends = [e.n1 + 1, e.n2 + 1]
        for side in (0, 1):
            rel = (e.releases or (False,) * 12)[6 * side:6 * side + 6]
            if any(rel):
                ops.node(dup, *X[e.n1 if side == 0 else e.n2])
                dirs = [d + 1 for d in range(6) if not rel[d]]
                ops.element("zeroLength", 10 ** 6 + 2 * ei + side, ends[side], dup, "-mat", *([1] * len(dirs)),
                            "-dir", *dirs, "-orient", *R[0], *R[1])
                ends[side] = dup
                dup += 1
        ops.element("elasticBeamColumn", ei + 1, *ends, s.A, m.E, m.G, s.J, s.Iy, s.Iz, ei + 1)
    ops.timeSeries("Linear", 1)
    ops.pattern("Plain", 1, 1)
    P = np.zeros((len(X), 6))
    for (n, c), v in frame.nodal_loads.items():
        P[n] += combo.get(c, 0.0) * np.asarray(v, float)
    if extra is not None:
        P += np.asarray(extra).reshape(-1, 6)
    for ei, (wa, wb) in enumerate(_member_w(frame, combo)):
        if not (np.any(wa) or np.any(wb)):
            continue
        e, (R, L) = frame.elements[ei], axes[ei]
        if e.truss:
            P[e.n1, :3] += (2 * wa + wb) * L / 6
            P[e.n2, :3] += (wa + 2 * wb) * L / 6
            continue
        la, lb = R @ wa * scale, R @ wb * scale
        if np.allclose(la, lb):
            ops.eleLoad("-ele", ei + 1, "-type", "-beamUniform", la[1], la[2], la[0])
        else:
            for j in range(40):
                v = la + (j + 0.5) / 40 * (lb - la)
                ops.eleLoad("-ele", ei + 1, "-type", "-beamUniform", v[1], v[2], v[0], j / 40, (j + 1) / 40)
    for n in range(len(X)):
        if np.any(P[n]):
            ops.load(n + 1, *(scale * P[n]))
    return len(X)


def _analyse(nonlinear: bool):
    ops.system("UmfPack")
    ops.numberer("RCM")
    ops.constraints("Plain")
    if nonlinear:
        ops.test("NormDispIncr", 1e-10, 100)
        ops.algorithm("Newton")
        ops.integrator("LoadControl", 0.1)
        ops.analysis("Static")
        ok = ops.analyze(10)
    else:
        ops.algorithm("Linear")
        ops.integrator("LoadControl", 1.0)
        ops.analysis("Static")
        ok = ops.analyze(1)
    if ok != 0:
        raise RuntimeError("OpenSees analysis failed")
    ops.reactions()


def _results(frame, nn):
    U = np.array([ops.nodeDisp(i + 1) for i in range(nn)])
    R = np.zeros((nn, 6))
    for n in frame.supports:
        R[n] = ops.nodeReaction(n + 1)
    for n, g in _GROUND.items():                        # a spring's reaction is found at its ground node
        R[n] += np.array(ops.nodeReaction(g))
    forces = []
    for ei, e in enumerate(frame.elements):
        if e.truss:
            N = ops.eleResponse(ei + 1, "axialForce")
            N = N[0] if isinstance(N, (list, tuple)) else N
            forces.append(np.array([-N, 0, 0, 0, 0, 0, N, 0, 0, 0, 0, 0], float))
        else:
            forces.append(np.array(ops.eleResponse(ei + 1, "localForce"), float))
    return {"U": U, "R": R, "EF": np.array(forces)}


def linear(frame, combo, extra=None) -> dict:
    nn = build(frame, combo, extra=extra)
    _analyse(False)
    return _results(frame, nn)


def p_delta(frame, combo, extra=None) -> dict:
    nn = build(frame, combo, second_order=True, extra=extra)
    _analyse(True)
    return _results(frame, nn)


def bars_as_beams(frame: fs.Frame) -> fs.Frame:
    """Copy with every truss bar replaced by a beam of negligible bending/torsion stiffness."""
    f = copy.deepcopy(frame)
    for e in f.elements:
        if e.truss:
            s, tiny = e.section, e.section.A * 1e-9
            e.section = fs.Section(s.name, s.shape, s.A, tiny, tiny, tiny, 1, 1, 1, 1, s.buckling_curve)
            e.truss = False
    return f


def alpha_cr(frame, combo) -> float:
    """Smallest positive alpha with det(K + alpha K_G) = 0 from OpenSees tangents (refine the mesh first)."""
    mats = []
    for lam in (1e-9, 1e-3):
        build(frame, combo, second_order=True, scale=lam)
        ops.system("FullGeneral")
        ops.numberer("Plain")
        ops.constraints("Plain")
        ops.test("NormDispIncr", 1e-12, 50)
        ops.algorithm("Newton")
        ops.integrator("LoadControl", 1.0)
        ops.analysis("Static")
        ops.analyze(1)
        A = np.array(ops.printA("-ret"))
        n = int(round(math.sqrt(A.size)))
        mats.append(A.reshape(n, n))
    K0, K1 = mats
    mu = np.linalg.eigvals(np.linalg.solve(K0, -(K1 - K0) / 1e-3))
    mu = mu.real[(np.abs(mu.imag) <= 1e-6 * np.abs(mu).max()) & (mu.real > 0)]
    return 1.0 / mu.max() if mu.size else math.inf


def almond_linear(frame, combo, extra=None) -> dict:
    r = fs.solve_linear(frame, combo, extra=extra)
    return {"U": r.displacements, "R": r.reactions, "EF": np.array([er.end_forces for er in r.elements]), "result": r}


def compare(a: dict, o: dict, frame: fs.Frame) -> dict:
    """Largest difference of each quantity, relative to the reference's largest magnitude."""
    def rel(x, y):
        d = float(np.max(np.abs(y))) if np.size(y) else 0.0
        return float(np.max(np.abs(x - y)) / d) if d > 0 else float(np.max(np.abs(x), initial=0.0))
    beams = [i for i, e in enumerate(frame.elements) if not e.truss]
    sup = sorted(frame.supports)
    # bars: mean axial force (OpenSees lumps the bars' own axial weight to the nodes)
    mean_n = lambda EF: (EF[:, 6] - EF[:, 0]) / 2
    return {
        "displacement": rel(a["U"][:, :3], o["U"][:, :3]),
        "rotation": rel(a["U"][:, 3:], o["U"][:, 3:]),
        "reactions": rel(a["R"][sup, :3], o["R"][sup, :3]),
        "axial": rel(mean_n(a["EF"]), mean_n(o["EF"])),
        "shear": rel(a["EF"][beams][:, [1, 2, 7, 8]], o["EF"][beams][:, [1, 2, 7, 8]]) if beams else 0.0,
        "moment": rel(a["EF"][beams][:, [4, 5, 10, 11]], o["EF"][beams][:, [4, 5, 10, 11]]) if beams else 0.0,
    }
