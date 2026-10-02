"""Independent hand calculations for the native engine and its results tables (validate(detail=True)).

Each case is a textbook closed form worked here from first principles, not from the solver's own
code, so a wrong formula in the engine cannot also hide in the expected value."""
import math

import pytest

from almond_mcp import frame_solver as fs
from almond_mcp import native_structure as ns
from tests.test_stability import portal_model

E, FY, GAM = 210e6, 235e3, 78.5                       # kN/m2, kN/m2, kN/m3 (S235)
SEC = {"shape": "circular_hollow", "diameter": 0.2191, "wall": 0.008}
S = fs.chs(219.1, 8.0)
A, I, WEL = S.A, S.Iy, S.Wel_y
W = GAM * A                                           # self weight per metre, kN/m


def model(points, anchors, span):
    return {"status": "ok", "shells": 0, "tolerance_m": 0.001, "max_member_span_m": span, "max_span_m": span,
            "warnings": [], "anchor_points": anchors,
            "members": [{"source_guids": ["m"], "points": points, "section": SEC}]}


def simply_supported(L=6.0, **kw):
    m = model([[0, 0, 3], [L, 0, 3]], [[0, 0, 3], [L, 0, 3]], L)
    return ns.validate(m, "beam", 0.0, fixed_supports=False, self_weight=True, stability="off", detail=True, **kw)


def test_simply_supported_beam_under_self_weight():
    L = 6.0
    r = simply_supported(L)
    b = r["members"][0]
    assert b["m_max_knm"] == pytest.approx(1.35 * W * L ** 2 / 8, rel=2e-3)
    assert b["v_max_kn"] == pytest.approx(1.35 * W * L / 2, rel=2e-3)
    assert b["deflection_mm"] == pytest.approx(5 * W * L ** 4 / (384 * E * I) * 1000, rel=2e-3)
    assert b["deflection_ratio"] == pytest.approx(L / (5 * W * L ** 4 / (384 * E * I)), rel=5e-3)
    assert b["utilization"] == pytest.approx(1.35 * W * L ** 2 / 8 / (WEL * FY), rel=5e-3)
    assert sum(s["sls"]["Fz"] for s in r["supports"]) == pytest.approx(W * L, rel=2e-3)
    assert sum(s["uls"]["ULS 6.10"]["Fz"] for s in r["supports"]) == pytest.approx(1.35 * W * L, rel=2e-3)


def test_cantilever_tip_load():
    L, P = 3.0, 10.0
    r = ns.validate(model([[0, 0, 3], [L, 0, 3]], [[0, 0, 3]], L), "beam", P, fixed_supports=True,
                    self_weight=False, stability="off", detail=True)
    c = r["members"][0]
    tip = P * L ** 3 / (3 * E * I)
    assert c["m_max_knm"] == pytest.approx(1.5 * P * L, rel=1e-3)
    assert c["v_max_kn"] == pytest.approx(1.5 * P, rel=1e-3)
    assert c["max_displacement_mm"] == pytest.approx(tip * 1000, rel=1e-3)
    # deflection relative to the member's own (displaced) ends: max of xi - xi^2 (3 - xi) / 2 = 0.1925 x tip
    assert c["deflection_mm"] == pytest.approx(0.19245 * tip * 1000, rel=0.01)
    assert abs(r["supports"][0]["uls"]["ULS 6.10"]["My"]) == pytest.approx(1.5 * P * L, rel=1e-3)


def test_shear_is_read_at_both_member_ends():
    """A cantilever drawn from its tip to its base: zero shear at the start, 1.35 wL at the end."""
    L = 3.0
    r = ns.validate(model([[L, 0, 3], [0, 0, 3]], [[0, 0, 3]], L), "beam", 0.0, fixed_supports=True,
                    self_weight=True, stability="off", detail=True)
    assert r["members"][0]["v_max_kn"] == pytest.approx(1.35 * W * L, rel=2e-3)


def test_column_flexural_buckling_curve_a():
    L, P = 4.0, 300.0
    r = ns.validate(model([[0, 0, 0], [0, 0, L]], [[0, 0, 0]], L), "frame", P, fixed_supports=True,
                    self_weight=False, stability="off", detail=True)
    k = r["members"][0]
    lam = math.sqrt(A * FY / (math.pi ** 2 * E * I / L ** 2))
    phi = 0.5 * (1 + 0.21 * (lam - 0.2) + lam ** 2)
    chi = 1 / (phi + math.sqrt(phi ** 2 - lam ** 2))
    assert k["n_compression_kn"] == pytest.approx(1.5 * P, rel=1e-6)
    assert k["slenderness"] == pytest.approx(lam, abs=2e-3)
    assert k["chi"] == pytest.approx(chi, abs=2e-3)
    assert k["buckling_utilization"] == pytest.approx(1.5 * P / (chi * A * FY), rel=5e-3)


def test_en1990_6_10a_and_6_10b_totals():
    L, Q = 6.0, 10.0
    m = model([[0, 0, 3], [L / 2, 0, 3], [L, 0, 3]], [[0, 0, 3], [L, 0, 3]], L)
    r = ns.validate(m, "beam", Q, fixed_supports=False, self_weight=True, stability="off", uls="6.10ab", detail=True)
    G = W * L
    total = {k: sum(s["uls"][k]["Fz"] for s in r["supports"]) for k in r["supports"][0]["uls"]}
    assert total["ULS 6.10a"] == pytest.approx(1.35 * G + 0.7 * 1.5 * Q, rel=2e-3)
    assert total["ULS 6.10b"] == pytest.approx(0.85 * 1.35 * G + 1.5 * Q, rel=2e-3)


def test_sway_imperfection_four_columns():
    f = fs.Frame()
    for x, y in ((0, 0), (6, 0), (0, 5), (6, 5)):
        a, t = f.add_node((x, y, 0)), f.add_node((x, y, 3.085))
        f.add_element(a, t, S, fs.material("Steel"))
    assert ns.sway_imperfection(f)["phi"] == pytest.approx(1 / 200 * math.sqrt(0.5 * (1 + 1 / 4)), rel=1e-9)


def test_second_order_between_alpha_cr_1_and_10():
    """EN 1993-1-1 5.2.1(3): alpha_cr = 6.7 (< 10) must switch the ULS analysis to second order."""
    r = ns.validate(portal_model(139.7, 5.0), "frame", 40, fixed_supports=False, self_weight=False)
    st = r["results"]["stability"]
    assert 5 < st["min_alpha_cr"] < 10 and st["method"] == "second-order (P-Delta)"
    stiff = ns.validate(portal_model(168.3, 5.0), "frame", 40, fixed_supports=False, self_weight=False)
    assert stiff["results"]["stability"]["min_alpha_cr"] >= 10
    assert stiff["results"]["stability"]["method"] == "first-order"
