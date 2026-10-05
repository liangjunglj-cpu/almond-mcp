"""Support types per support point (fixed, pinned, rollers, springs) against closed forms.

Each expected value is a textbook result worked here, not taken from the solver."""
import math

import pytest

from almond_mcp import frame_solver as fs
from almond_mcp import native_structure as ns

STEEL = fs.material("Steel")
SEC = fs.chs(219.1, 8.0)
EI = STEEL.E * SEC.Iy
SPEC = {"shape": "circular_hollow", "diameter": 0.2191, "wall": 0.008}


@pytest.mark.parametrize("text,restraint,springs,label", [
    ("fixed", (1, 1, 1, 1, 1, 1), (0,) * 6, "fixed"),
    ("Pinned", (1, 1, 1, 0, 0, 0), (0,) * 6, "pinned"),
    ("pin", (1, 1, 1, 0, 0, 0), (0,) * 6, "pinned"),
    ("roller", (0, 0, 1, 0, 0, 0), (0,) * 6, "roller"),
    ("roller-x", (0, 1, 1, 0, 0, 0), (0,) * 6, "roller-x"),
    ("roller-y", (1, 0, 1, 0, 0, 0), (0,) * 6, "roller-y"),
    ("spring kz=50000", (0,) * 6, (0, 0, 50000, 0, 0, 0), "spring kz=50000"),
    ("fixed rx=8000, ry:8000", (1, 1, 1, 0, 0, 1), (0, 0, 0, 8000, 8000, 0), "fixed rx=8000 ry=8000"),
])
def test_parse_support(text, restraint, springs, label):
    r, k, name = ns.parse_support(text)
    assert r == tuple(bool(v) for v in restraint) and k == pytest.approx(springs) and name == label


@pytest.mark.parametrize("text", ["", "hinge", "fixed kq=5", "spring", "spring kz=-1", "pinned kz"])
def test_parse_support_rejects(text):
    with pytest.raises(ValueError):
        ns.parse_support(text)


def test_cantilever_on_a_tip_spring():
    """Tip load P shared by the cantilever (3EI/L^3) and the spring k in parallel."""
    L, P, k = 4.0, 20.0, 2000.0
    f = fs.Frame()
    a, b = f.add_node((0, 0, 0)), f.add_node((L, 0, 0))
    f.add_element(a, b, SEC, STEEL)
    f.fix(a)
    f.spring(b, kz=k)
    f.load(b, fz=-P)
    r = fs.solve(f)
    d = P / (k + 3 * EI / L ** 3)
    assert -r.displacements[b, 2] == pytest.approx(d, rel=1e-9)
    assert r.reactions[b, 2] == pytest.approx(k * d, rel=1e-9)               # the spring pushes up
    assert r.equilibrium_error() < 1e-9


def test_semi_rigid_column_base():
    """Lateral load H at the top of a column on a rotational base spring k_r: bending plus base rotation,
    d = H h^3 / 3EI + H h^2 / k_r."""
    h, H, kr = 4.0, 5.0, 8000.0
    f = fs.Frame()
    a, b = f.add_node((0, 0, 0)), f.add_node((0, 0, h))
    f.add_element(a, b, SEC, STEEL)
    f.fix(a, ns.parse_support("fixed ry=8000")[0])
    f.spring(a, ry=kr)
    f.load(b, fx=H)
    r = fs.solve(f)
    assert r.displacements[b, 0] == pytest.approx(H * h ** 3 / (3 * EI) + H * h ** 2 / kr, rel=1e-9)
    assert r.reactions[a, 4] == pytest.approx(-H * h, rel=1e-9)               # the spring's moment


def test_a_restrained_dof_stays_rigid_with_a_spring():
    f = fs.Frame()
    a, b = f.add_node((0, 0, 0)), f.add_node((3, 0, 0))
    f.add_element(a, b, SEC, STEEL)
    f.fix(a)
    f.fix(b, (False, False, True, False, False, False))
    f.spring(b, kz=10.0)
    f.load(b, fz=-5.0)
    r = fs.solve(f)
    assert r.displacements[b, 2] == 0.0 and r.reactions[b, 2] == pytest.approx(5.0)


def model(lines, supports=(), anchors=()):
    members = [{"source_guids": [f"m{i}"], "points": [list(a), list(b)], "section": SPEC} for i, (a, b) in enumerate(lines)]
    spans = [math.dist(a, b) for a, b in lines]
    return {"members": members, "anchor_points": [list(p) for p in anchors], "tolerance_m": 0.001,
            "supports": [{"point_m": list(p), "spec": spec} for p, spec in supports],
            "max_member_span_m": max(spans), "max_span_m": max(spans), "warnings": []}


def run(m, **kw):
    kw = {"structure_type": "beam", "load_kn": 0.0, "self_weight": False, "stability": "off",
          "design_basis": "unfactored", "detail": True, **kw}
    return ns.validate(m, **kw)


def reaction(out, x, dof="Fz"):
    return next(s["sls"][dof] for s in out["supports"] if math.isclose(s["position_m"][0], x, abs_tol=1e-6))


def test_propped_cantilever_fixed_and_roller():
    """Point load P at midspan of a beam fixed at one end, on a roller at the other: R_roller = 5P/16."""
    L, P = 6.0, 32.0
    beam = [((0, 0, 3), (L / 2, 0, 3)), ((L / 2, 0, 3), (L, 0, 3))]
    out = run(model(beam, supports=[((0, 0, 3), "fixed"), ((L, 0, 3), "roller")]), load_kn=P)
    assert reaction(out, L) == pytest.approx(5 * P / 16, rel=1e-6)
    assert reaction(out, 0) == pytest.approx(11 * P / 16, rel=1e-6)
    assert abs(next(s["sls"]["My"] for s in out["supports"] if s["position_m"][0] == 0)) == pytest.approx(3 * P * L / 16, rel=1e-6)
    assert out["results"]["support_mode"] == "mixed"
    assert sorted(out["results"]["support_types"]) == ["fixed", "roller"]
    assert {s["restraint"] for s in out["supports"]} == {"fixed", "roller"}


def portal(right):
    lines = [((0, 0, 0), (0, 0, 4)), ((0, 0, 4), (3, 0, 4)), ((3, 0, 4), (6, 0, 4)), ((6, 0, 4), (6, 0, 0))]
    return model(lines, supports=[((0, 0, 0), "fixed"), ((6, 0, 0), right)])


def test_a_sliding_bearing_carries_no_thrust():
    """A portal fixed at one base: on a second fixed base the frame pushes outward (horizontal thrust);
    on a roller sliding along the span the thrust is zero and the roller end moves outward."""
    tied = run(portal("fixed"), load_kn=40.0)
    free = run(portal("roller-x"), load_kn=40.0)
    assert abs(reaction(tied, 6, "Fx")) > 1.0
    assert reaction(free, 6, "Fx") == pytest.approx(0.0, abs=1e-9)
    assert reaction(free, 0, "Fx") == pytest.approx(0.0, abs=1e-9)
    assert sum(s["sls"]["Fz"] for s in free["supports"]) == pytest.approx(40.0, rel=1e-9)


def test_only_rollers_is_a_mechanism_with_a_hint():
    beam = [((0, 0, 3), (3, 0, 3)), ((3, 0, 3), (6, 0, 3))]
    out = run(model(beam, supports=[((0, 0, 3), "roller"), ((6, 0, 3), "roller")]), load_kn=10.0)
    assert out["status"] == "fail" and "Mechanism" in out["verdict"]
    assert any("Rollers and springs" in s for s in out["suggestions"])


def test_untyped_and_unknown_supports_use_the_default():
    beam = [((0, 0, 3), (3, 0, 3)), ((3, 0, 3), (6, 0, 3))]
    out = run(model(beam, supports=[((6, 0, 3), "hinge")], anchors=[(0, 0, 3), (6, 0, 3)]), load_kn=10.0,
              fixed_supports=False)
    assert out["results"]["support_types"] == ["pinned", "pinned"]
    assert any("'hinge'" in w and "not understood" in w for w in out["warnings"])


def test_anchor_points_alone_behave_as_before():
    beam = [((0, 0, 3), (3, 0, 3)), ((3, 0, 3), (6, 0, 3))]
    plain = run(model(beam, anchors=[(0, 0, 3), (6, 0, 3)]), load_kn=10.0)
    typed = run(model(beam, supports=[((0, 0, 3), "fixed"), ((6, 0, 3), "fixed")]), load_kn=10.0)
    assert plain["results"]["max_deflection_mm"] == pytest.approx(typed["results"]["max_deflection_mm"], rel=1e-12)
    assert plain["results"]["support_mode"] == "fixed" and plain["supports"][0]["restraint"] == "fixed"


def test_spring_support_settles_and_reports_its_force():
    """Simply supported beam (pin + vertical spring), midspan load P: the spring takes P/2 and settles P/2k."""
    L, P, k = 6.0, 20.0, 5000.0
    beam = [((0, 0, 3), (L / 2, 0, 3)), ((L / 2, 0, 3), (L, 0, 3))]
    out = run(model(beam, supports=[((0, 0, 3), "pinned"), ((L, 0, 3), f"roller-x kz={k:g}")]), load_kn=P)
    assert reaction(out, L) == pytest.approx(P / 2, rel=1e-9)
    assert out["results"]["equilibrium_error_kn"] < 1e-6
    r = out["results"]
    assert r["max_displacement_mm"] > r["max_deflection_mm"]                 # the settlement is not beam deflection
