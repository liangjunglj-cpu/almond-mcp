"""Closed-form benchmarks for the native frame solver (Euler-Bernoulli, linear elastic).

Every case is a textbook result; tolerances are tight because the element is exact for
nodal loads and uniform member loads."""
import math

import numpy as np
import pytest

from almond_mcp import frame_solver as fs

STEEL = fs.material("Steel")
SEC = fs.chs(114.3, 4.0)
EI = STEEL.E * SEC.Iy
EA = STEEL.E * SEC.A
GJ = STEEL.G * SEC.J
REL = 1e-9


def line(frame, a, b, n, sec=SEC, mat=STEEL, **kw):
    """n elements from a to b; returns node ids along the line."""
    ids = [frame.add_node(np.asarray(a) + (np.asarray(b) - np.asarray(a)) * i / n) for i in range(n + 1)]
    for i in range(n):
        frame.add_element(ids[i], ids[i + 1], sec, mat, **kw)
    return ids


def disp(res, node, dof):
    return res.displacements[node, dof]


@pytest.mark.parametrize("n", [1, 4])
def test_cantilever_tip_point_load(n):
    f, L, P = fs.Frame(), 3.0, 10.0
    ids = line(f, (0, 0, 0), (L, 0, 0), n)
    f.fix(ids[0]); f.load(ids[-1], fz=-P)
    r = fs.solve(f)
    assert disp(r, ids[-1], 2) == pytest.approx(-P * L ** 3 / (3 * EI), rel=REL)
    assert disp(r, ids[-1], 4) == pytest.approx(P * L ** 2 / (2 * EI), rel=REL)   # ry = -duz/dx > 0
    assert r.reactions[ids[0], 2] == pytest.approx(P, rel=REL)
    assert abs(r.reactions[ids[0], 4]) == pytest.approx(P * L, rel=REL)
    assert max(np.max(np.abs(er.My)) for er in r.elements) == pytest.approx(P * L, rel=1e-6)


def test_cantilever_udl_single_element_exact():
    f, L, w = fs.Frame(), 4.0, 5.0
    ids = line(f, (0, 0, 0), (L, 0, 0), 1)
    f.fix(ids[0]); f.udl(0, (0, 0, -w))
    r = fs.solve(f)
    assert disp(r, ids[1], 2) == pytest.approx(-w * L ** 4 / (8 * EI), rel=REL)
    er = r.elements[0]
    x = np.linspace(0, L, len(er.disp))
    exact = -w * x ** 2 * (6 * L ** 2 - 4 * L * x + x ** 2) / (24 * EI)   # interior of the element
    assert np.allclose(er.disp[:, 2], exact, rtol=1e-9, atol=1e-12)
    assert np.max(np.abs(er.My)) == pytest.approx(w * L ** 2 / 2, rel=1e-9)


@pytest.mark.parametrize("n", [1, 2, 6])
def test_simply_supported_udl(n):
    f, L, w = fs.Frame(), 6.0, 8.0
    ids = line(f, (0, 0, 0), (L, 0, 0), n)
    f.fix(ids[0], (True, True, True, True, False, False))     # pin + torsion restraint
    f.fix(ids[-1], (False, True, True, False, False, False))   # roller
    for e in range(n):
        f.udl(e, (0, 0, -w))
    r = fs.solve(f)
    mid = min(np.min(er.disp[:, 2]) for er in r.elements)
    assert mid == pytest.approx(-5 * w * L ** 4 / (384 * EI), rel=1e-9)
    assert max(np.max(np.abs(er.My)) for er in r.elements) == pytest.approx(w * L ** 2 / 8, rel=1e-9)


def test_simply_supported_midspan_point_load():
    f, L, P = fs.Frame(), 5.0, 12.0
    ids = line(f, (0, 0, 0), (L, 0, 0), 2)
    f.fix(ids[0], (True, True, True, True, False, False))
    f.fix(ids[-1], (False, True, True, False, False, False))
    f.load(ids[1], fz=-P)
    r = fs.solve(f)
    assert disp(r, ids[1], 2) == pytest.approx(-P * L ** 3 / (48 * EI), rel=REL)
    assert np.max(np.abs(r.elements[0].My)) == pytest.approx(P * L / 4, rel=1e-9)


def test_fixed_fixed_udl():
    f, L, w = fs.Frame(), 5.0, 6.0
    ids = line(f, (0, 0, 0), (L, 0, 0), 2)
    f.fix(ids[0]); f.fix(ids[-1])
    f.udl(0, (0, 0, -w)); f.udl(1, (0, 0, -w))
    r = fs.solve(f)
    assert disp(r, ids[1], 2) == pytest.approx(-w * L ** 4 / (384 * EI), rel=REL)
    assert abs(r.reactions[ids[0], 4]) == pytest.approx(w * L ** 2 / 12, rel=REL)


def test_propped_cantilever_udl():
    f, L, w = fs.Frame(), 4.0, 10.0
    ids = line(f, (0, 0, 0), (L, 0, 0), 1)
    f.fix(ids[0]); f.fix(ids[1], (False, True, True, False, False, False))
    f.udl(0, (0, 0, -w))
    r = fs.solve(f)
    assert r.reactions[ids[1], 2] == pytest.approx(3 * w * L / 8, rel=REL)
    assert abs(r.reactions[ids[0], 4]) == pytest.approx(w * L ** 2 / 8, rel=REL)


def test_axial_bar_and_torsion():
    f, L = fs.Frame(), 2.5
    ids = line(f, (0, 0, 0), (L, 0, 0), 3)
    f.fix(ids[0]); f.load(ids[-1], fx=50.0, mx=2.0)
    r = fs.solve(f)
    assert disp(r, ids[-1], 0) == pytest.approx(50.0 * L / EA, rel=REL)
    assert disp(r, ids[-1], 3) == pytest.approx(2.0 * L / GJ, rel=REL)
    assert r.elements[0].N[0] == pytest.approx(50.0, rel=REL)


def test_weak_axis_bending_rhs():
    sec = fs.rhs(200, 100, 6)
    f, L, P = fs.Frame(), 3.0, 4.0
    ids = line(f, (0, 0, 0), (L, 0, 0), 2, sec=sec)
    f.fix(ids[0]); f.load(ids[-1], fy=P)        # horizontal load bends about local z (Iz, weak)
    r = fs.solve(f)
    assert disp(r, ids[-1], 1) == pytest.approx(P * L ** 3 / (3 * STEEL.E * sec.Iz), rel=REL)


def test_bent_cantilever_l_frame():
    """Column h then horizontal arm a, vertical tip load P: dz = P a^3/3EI + P a^2 h/EI."""
    f, h, a, P = fs.Frame(), 3.0, 2.0, 5.0
    col = line(f, (0, 0, 0), (0, 0, h), 3)
    arm = [col[-1]] + [f.add_node((a * i / 2, 0, h)) for i in (1, 2)]
    for i in range(2):
        f.add_element(arm[i], arm[i + 1], SEC, STEEL)
    f.fix(col[0]); f.load(arm[-1], fz=-P)
    r = fs.solve(f)
    assert disp(r, arm[-1], 2) == pytest.approx(-(P * a ** 3 / (3 * EI) + P * a ** 2 * h / EI) - P * h / EA, rel=1e-9)


def test_orientation_invariance():
    """The same cantilever along an arbitrary 3D direction gives the same tip deflection."""
    L, P = 3.0, 7.0
    base = fs.Frame(); ids = line(base, (0, 0, 0), (L, 0, 0), 2); base.fix(ids[0]); base.load(ids[-1], fz=-P)
    ref = fs.solve(base).displacements[ids[-1], 2]
    d = np.array([1.0, 2.0, 0.0]); d /= np.linalg.norm(d)
    f = fs.Frame(); ids = line(f, (1, 1, 1), np.array([1, 1, 1]) + L * d, 2); f.fix(ids[0]); f.load(ids[-1], fz=-P)
    assert fs.solve(f).displacements[ids[-1], 2] == pytest.approx(ref, rel=1e-9)


def test_two_bar_truss():
    """Symmetric pin-jointed truss, apex load P: N = P/(2 sin a), dz = P L/(2 EA sin^2 a)."""
    f, span, rise, P = fs.Frame(), 4.0, 1.5, 20.0
    a0, a1, top = f.add_node((0, 0, 0)), f.add_node((span, 0, 0)), f.add_node((span / 2, 0, rise))
    f.add_element(a0, top, SEC, STEEL, truss=True); f.add_element(top, a1, SEC, STEEL, truss=True)
    f.pin(a0); f.pin(a1); f.fix(top, (False, True, False, False, False, False))
    f.load(top, fz=-P)
    r = fs.solve(f)
    L = math.hypot(span / 2, rise); sa = rise / L
    assert r.elements[0].N[0] == pytest.approx(-P / (2 * sa), rel=REL)
    assert disp(r, top, 2) == pytest.approx(-P * L / (2 * EA * sa ** 2), rel=REL)
    assert r.auto_restrained   # truss-only apex rotations restrained, reported


def test_self_weight_matches_udl():
    f, L = fs.Frame(), 3.0
    ids = line(f, (0, 0, 0), (L, 0, 0), 1)
    f.fix(ids[0]); f.gravity = (0, 0, -1)
    w = STEEL.gamma * SEC.A
    assert fs.solve(f).displacements[ids[1], 2] == pytest.approx(-w * L ** 4 / (8 * EI), rel=REL)


def test_equilibrium_random_space_frame():
    rng = np.random.default_rng(7)
    f = fs.Frame()
    pts = [f.add_node(p) for p in rng.uniform(0, 5, (8, 3))]
    for i in range(8):
        for j in range(i + 1, 8):
            if rng.random() < 0.45:
                f.add_element(pts[i], pts[j], SEC, STEEL)
    for i in range(3): f.fix(pts[i])
    for i in range(3, 8): f.load(pts[i], *rng.normal(0, 5, 3))
    f.gravity = (0, 0, -1)
    r = fs.solve(f)
    assert r.equilibrium_error() < 1e-6


def test_superposition():
    def run(fz, fy):
        f = fs.Frame(); ids = line(f, (0, 0, 0), (0, 0, 3), 2)
        f.fix(ids[0]); f.load(ids[-1], fy=fy, fz=fz)
        return fs.solve(f).displacements
    assert np.allclose(run(-5, 0) + run(0, 3), run(-5, 3), atol=1e-14)


def test_mechanism_is_reported():
    f = fs.Frame(); ids = line(f, (0, 0, 0), (4, 0, 0), 2)
    f.pin(ids[0])                            # rotates freely about the pin: unstable
    f.load(ids[-1], fz=-1)
    with pytest.raises(fs.MechanismError):
        fs.solve(f)


@pytest.mark.parametrize("span,piece", [(3.0, 1e-3), (12.0, 1e-3), (12.0, 2e-3)])
def test_millimetre_piece_is_not_a_mechanism(span, piece):
    """A piece of a millimetre between members of metres is very stiff, not singular: the pivot test
    compares each pivot with its own diagonal, so it is not mistaken for a mechanism."""
    f = fs.Frame()
    sec = fs.chs(219.1, 8)
    n = [f.add_node((0, 0, 0)), f.add_node((span / 2, 0, 0)), f.add_node((span / 2 + piece, 0, 0)), f.add_node((span, 0, 0))]
    for a, b in zip(n, n[1:]):
        f.add_element(a, b, sec, STEEL)
    f.fix(n[0])
    f.load(n[-1], fz=-10)
    tip = -fs.solve(f).displacements[n[-1], 2]
    assert tip == pytest.approx(10 * span ** 3 / (3 * STEEL.E * sec.Iy), rel=1e-3)


def test_section_properties_chs_rhs_i():
    s = fs.chs(114.3, 4.0)
    assert s.A == pytest.approx(1.3858e-3, rel=1e-3)            # 13.9 cm2 (EN 10210 table)
    assert s.Iy == pytest.approx(2.11e-6, rel=3e-3)             # 211 cm4 (EN 10210 table)
    r = fs.rhs(200, 100, 6)
    assert r.A == pytest.approx(0.2 * 0.1 - 0.188 * 0.088, rel=1e-12)
    i = fs.i_section(300, 150, 7.1, 10.7)                        # IPE 300 without root radii
    assert i.Iy == pytest.approx(8.356e-5 * 0.96, rel=0.05)


def test_utilization_pure_bending_and_buckling():
    """Cantilever at exactly its elastic (default) / plastic moment reads 1.0; a pinned strut
    matches EN 1993 chi."""
    L = 2.0
    for W, plastic in ((SEC.Wel_y, False), (SEC.Wpl_y, True)):
        P = W * STEEL.fy / L
        f = fs.Frame(); ids = line(f, (0, 0, 0), (L, 0, 0), 1); f.fix(ids[0]); f.load(ids[-1], fz=-P)
        assert fs.solve(f, plastic=plastic).elements[0].utilization == pytest.approx(1.0, rel=1e-9)
    Lc, N = 4.0, 100.0
    f = fs.Frame(); ids = line(f, (0, 0, 0), (Lc, 0, 0), 1)
    f.fix(ids[0], (True, True, True, True, False, False)); f.fix(ids[1], (False, True, True, False, False, False))
    f.load(ids[1], fx=-N)
    er = fs.solve(f).elements[0]
    lam = math.sqrt(SEC.A * STEEL.fy / (math.pi ** 2 * STEEL.E * SEC.Iy / Lc ** 2))
    phi = 0.5 * (1 + 0.21 * (lam - 0.2) + lam ** 2)
    chi = 1 / (phi + math.sqrt(phi ** 2 - lam ** 2))
    assert er.utilization == pytest.approx(N / (chi * SEC.A * STEEL.fy), rel=1e-9)
