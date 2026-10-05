"""Building typologies against independent closed forms (no third-party solver needed).

Each reference is worked here by a different method from the solver's stiffness method (method of
joints, virtual work, the force method, funicular statics), so a wrong formula in the engine cannot
also hide in the expected value. The OpenSees cross-checks of the same models live in benchmarks/."""
import math

import numpy as np
import pytest

from almond_mcp import frame_solver as fs
from tests import structural_typologies as T


def joint_forces(frame, loads_case="Q"):
    """Member forces (tension +) and reactions of a statically determinate planar (x-z) pin-jointed
    truss by the method of joints: 2 equilibrium equations per node, solved directly."""
    X = np.asarray(frame.nodes)[:, [0, 2]]
    els = [(e.n1, e.n2) for e in frame.elements]
    sup = [(n, k) for n, flags in frame.supports.items() for k, d in ((0, 0), (1, 2)) if flags[d]]
    A = np.zeros((2 * len(X), len(els) + len(sup)))
    b = np.zeros(2 * len(X))
    for j, (p, q) in enumerate(els):
        d = (X[q] - X[p]) / np.linalg.norm(X[q] - X[p])
        A[2 * p:2 * p + 2, j] += d
        A[2 * q:2 * q + 2, j] -= d
    for k, (n, row) in enumerate(sup):
        A[2 * n + row, len(els) + k] = 1.0
    for (n, case), v in frame.nodal_loads.items():
        if case == loads_case:
            b[2 * n] -= v[0]
            b[2 * n + 1] -= v[2]
    assert A.shape[0] == A.shape[1], "truss must be statically determinate"
    return np.linalg.solve(A, b)[:len(els)], A


def test_pratt_truss_member_forces_and_deflection():
    c = T.pratt_truss()
    f = c["frame"]
    N_ref, A = joint_forces(f)
    r = fs.solve(f, combination={"Q": 1.0})
    N = np.array([float(np.mean(er.N)) for er in r.elements])
    assert np.max(np.abs(N - N_ref)) < 1e-9 * np.max(np.abs(N_ref))
    # virtual work: unit downward load at the midspan bottom node
    unit = np.zeros(A.shape[0])
    unit[2 * c["mid_node"] + 1] = 1.0
    n_unit = np.linalg.solve(A, unit)[:len(f.elements)]
    E = T.S355.E
    vw = sum(N_ref[j] * n_unit[j] * er.length / (E * f.elements[j].section.A) for j, er in enumerate(r.elements))
    assert -r.displacements[c["mid_node"], 2] == pytest.approx(abs(vw), rel=1e-9)


def test_pinned_portal_thrust_by_the_force_method():
    """Release the horizontal reaction, integrate M0 m1 / EI and m1^2 / EI along the frame (bending only;
    the solver also has axial strain, worth well under 0.5 % here)."""
    c = T.portal_2d()
    g = c["geometry"]
    span, h, rise, w = g["span"], g["h"], g["rise"], g["w"]
    path = []
    for (p, q) in (((0, 0), (0, h)), ((0, h), (span / 2, h + rise)), ((span / 2, h + rise), (span, h)), ((span, h), (span, 0))):
        L = math.dist(p, q)
        for k in range(4000):
            t = (k + 0.5) / 4000
            path.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1]), L / 4000))
    M0 = lambda x: w * span / 2 * x - w * x * x / 2                 # pin + roller, UDL on plan
    d10 = sum(M0(x) * -z * ds for x, z, ds in path)
    d11 = sum(z * z * ds for x, z, ds in path)
    H = -d10 / d11
    r = fs.solve(c["frame"], combination={"Q": 1.0})
    A = c["nodes"][0]
    assert abs(r.reactions[A, 0]) == pytest.approx(H, rel=5e-3)
    assert abs(r.elements[0].My[-1]) == pytest.approx(H * h, rel=5e-3)                  # eaves moment
    assert abs(r.elements[1].My[-1]) == pytest.approx(abs(M0(span / 2) - H * (h + rise)), rel=2e-2)   # apex


@pytest.mark.parametrize("n", [8, 32])
def test_parabolic_arch_is_funicular(n):
    c = T.arch(n=n)
    r = fs.solve(c["frame"], combination={"Q": 1.0})
    assert abs(r.reactions[c["nodes"][0], 0]) == pytest.approx(c["thrust"], rel=1e-3)   # rib shortening ~0.06 %
    assert max(np.max(np.abs(er.My)) for er in r.elements) < 1e-3 * c["M0"]


def test_l_bracket_bending_and_torsion():
    c = T.l_bracket()
    r = fs.solve(c["frame"], combination={"Q": 1.0})
    assert -r.displacements[c["tip"], 2] == pytest.approx(c["tip_deflection"], rel=1e-9)
    assert abs(r.elements[0].T) == pytest.approx(c["torsion"], rel=1e-9)


def test_rigid_rotation_and_survey_offset_change_nothing():
    """A diagrid rotated 17 degrees about z and moved 31/41 km (SVY21-like coordinates)."""
    base = T.diagrid()
    moved = T.diagrid(rot_deg=17.0, offset=(31234.5, 41234.5, 12.0))
    combo = base["combos"]["ULS wind"]
    a, b = fs.solve(base["frame"], combination=combo), fs.solve(moved["frame"], combination=combo)
    assert b.max_displacement == pytest.approx(a.max_displacement, rel=1e-9)
    assert b.max_utilization == pytest.approx(a.max_utilization, rel=1e-9)
    assert np.linalg.norm(b.reactions[:, :3].sum(0)) == pytest.approx(np.linalg.norm(a.reactions[:, :3].sum(0)), rel=1e-9)


@pytest.mark.parametrize("name,combo", [("portal", "Q"), ("Vierendeel", "ULS")])
def test_alpha_cr_with_four_elements_per_member_is_within_one_percent(name, combo):
    """The stability check splits compressed members in four; the consistent geometric stiffness
    converges from above, so four elements may overstate alpha_cr slightly."""
    c = T.ALL[name]()
    a4, _ = fs.critical_load_factor(T.refined(c["frame"], 4), c["combos"][combo])
    a16, _ = fs.critical_load_factor(T.refined(c["frame"], 16), c["combos"][combo])
    assert a16 <= a4 <= 1.01 * a16


def test_second_order_amplification_near_buckling():
    """Arch at 1.6 x its funicular load plus a lateral load: P-Delta converges and amplifies sway."""
    c = T.arch()
    f = c["frame"]
    for nd in c["nodes"][1:-1]:
        f.load(nd, fx=2.0, case="W")
    combo = {"Q": 1.6, "W": 1.0}
    alpha, _ = fs.critical_load_factor(T.refined(f, 4), combo)
    assert 1.0 < alpha < 2.0
    first = fs.solve_linear(T.refined(f, 4), combo)
    second = fs.solve_second_order(T.refined(f, 4), combo)
    assert second.converged and second.max_displacement > 2.0 * first.max_displacement
