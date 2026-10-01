"""Load cases and EN 1990 combinations: exact superposition, factors, envelopes, tools."""
import json

import numpy as np
import pytest

from almond_mcp import frame_solver as fs
from almond_mcp import native_structure as ns
from tests.test_capsules import _load_server
from tests.test_native_structure import CASES, model as ref_model

STEEL, SEC = fs.material("Steel"), fs.chs(114.3, 4.0)


def cantilever(g_kn=0.0, q_kn=0.0, gravity=False, n=2):
    f = fs.Frame()
    ids = [f.add_node((3.0 * i / n, 0, 0)) for i in range(n + 1)]
    for i in range(n):
        f.add_element(ids[i], ids[i + 1], SEC, STEEL)
    f.fix(ids[0])
    if g_kn:
        f.load(ids[-1], fz=-g_kn, case="G")
    if q_kn:
        f.load(ids[-1], fz=-q_kn, case="Q")
    if gravity:
        f.gravity = (0, 0, -1)
    return f, ids


def test_combination_equals_solving_prefactored_loads():
    f, ids = cantilever(2.0, 3.0, gravity=True)
    f.udl(0, (0, 0, -1.0), case="Q")
    combo = fs.solve_combinations(f, {"uls": {"G": 1.35, "Q": 1.5}})["uls"]
    g, _ = cantilever(1.35 * 2.0, 1.5 * 3.0)
    g.udl(0, (0, 0, -1.5), case="Q")
    g.udl(0, (0, 0, -1.35 * STEEL.gamma * SEC.A), case="G"); g.udl(1, (0, 0, -1.35 * STEEL.gamma * SEC.A), case="G")
    direct = fs.solve(g)
    assert np.allclose(combo.displacements, direct.displacements, rtol=1e-12, atol=1e-15)
    assert np.allclose(combo.reactions, direct.reactions, rtol=1e-12, atol=1e-12)
    assert [e.utilization for e in combo.elements] == pytest.approx([e.utilization for e in direct.elements], rel=1e-12)


def test_cases_are_reported_and_default_is_all_ones():
    f, _ = cantilever(1.0, 1.0, gravity=True)
    assert f.cases() == ["G", "Q"]
    assert fs.solve(f).combination == {"G": 1.0, "Q": 1.0}


@pytest.mark.parametrize("g,q,factor", [(0.0, 4.0, 1.5), (4.0, 0.0, 1.35)])
def test_uls_utilization_scales_by_the_partial_factor(g, q, factor):
    """Bending only (no compression): utilization is linear in load, so ULS / unfactored = factor."""
    model = {"members": [{"source_guids": ["c"], "points": [[0, 0, 0], [3, 0, 0]]}], "anchor_points": [[0, 0, 0]],
             "tolerance_m": 0.001, "max_member_span_m": 3, "max_span_m": 3}
    kw = dict(structure_type="beam", load_kn=q, self_weight=False,
              floor_loads=None, asset_loads=None)
    if g:          # a permanent point load: model it as the cantilever's own weight scaled up
        kw.update(load_kn=0.0, self_weight=True)
    en = ns.validate(model, design_basis="en1990", **kw)
    un = ns.validate(model, design_basis="unfactored", **kw)
    assert en["results"]["utilization_ratio"] == pytest.approx(factor * un["results"]["utilization_ratio"], rel=1e-3)
    assert en["results"]["max_deflection_mm"] == pytest.approx(un["results"]["max_deflection_mm"], rel=1e-12)  # SLS


def test_6_10ab_envelope_picks_the_governing_expression():
    """6.10a governs a G-dominated member, 6.10b a Q-dominated one."""
    f = fs.Frame()
    a, b, c = f.add_node((0, 0, 0)), f.add_node((3, 0, 0)), f.add_node((0, 4, 0))
    d = f.add_node((3, 4, 0))
    f.add_element(a, b, SEC, STEEL, tag=["g"]); f.add_element(c, d, SEC, STEEL, tag=["q"])
    f.fix(a); f.fix(c)
    f.load(b, fz=-5.0, case="G"); f.load(d, fz=-5.0, case="Q")
    _, ulss, env, stab = ns._solve_design(f, "en1990", "6.10ab")
    govern = {f.elements[i].tag[0]: n for i, (_, n, _) in enumerate(env)}
    assert govern == {"g": "ULS 6.10a", "q": "ULS 6.10b"}           # no columns: no sway variants
    assert stab["sway_imperfection"]["phi"] == 0


def test_mezzanine_floor_loads_reported_with_combinations():
    case = CASES["mezzanine"]
    kw = dict(structure_type="frame", load_kn=0, fixed_supports=False, diameter_mm=219.1, wall_mm=8.0, span_m=6.2,
              floor_loads={"imposed": 2.0, "dead": 1.0})
    en = ns.validate(ref_model(case), design_basis="en1990", **kw)
    un = ns.validate(ref_model(case), design_basis="unfactored", **kw)
    r = en["results"]
    assert r["deflection_combination"] == "SLS characteristic" and r["utilization_combination"].startswith("ULS 6.10")
    assert [c["name"] for c in r["combinations"]] == ["SLS characteristic", "ULS 6.10"]
    assert r["max_deflection_mm"] == pytest.approx(un["results"]["max_deflection_mm"], rel=1e-12)
    # G = 62 m2 x 1.0 + steel, Q = 62 m2 x 2.0: the ULS factor on utilization sits between 1.35 and 1.5
    ratio = r["utilization_ratio"] / un["results"]["utilization_ratio"]
    assert 1.35 < ratio < 1.5
    uls_reaction = r["combinations"][1]["reactions_kn"]
    steel = r["combinations"][0]["reactions_kn"] - 186.0
    assert uls_reaction == pytest.approx(1.35 * (62.0 + steel) + 1.5 * 124.0, abs=0.01)   # reported to 3 decimals
    assert any("Load combinations" in a for a in en["assumptions"])


def test_view_result_draws_sls_shape_with_uls_colours():
    case = CASES["mezzanine"]
    res, _ = ns.view_result(ref_model(case), load_kn=0, fixed_supports=False, diameter_mm=219.1, wall_mm=8.0,
                            floor_loads={"imposed": 2.0, "dead": 1.0})
    un, _ = ns.view_result(ref_model(case), load_kn=0, fixed_supports=False, diameter_mm=219.1, wall_mm=8.0,
                           floor_loads={"imposed": 2.0, "dead": 1.0}, design_basis="unfactored")
    assert res["max_displacement_mm"] == pytest.approx(un["max_displacement_mm"], rel=1e-12)
    assert max(e["utilization"] for e in res["elements"]) > 1.35 * max(e["utilization"] for e in un["elements"])
    assert res["combinations"]["utilization"] == ["ULS 6.10 (1.35G + 1.5Q)"]
    assert res["stability"]["method"] in ("first-order", "second-order (P-Delta)")


@pytest.fixture
def server(monkeypatch, tmp_path):
    cap = tmp_path / "capsules"
    cap.mkdir()
    srv = _load_server(monkeypatch, tmp_path, cap)
    m = dict(ref_model(CASES["mezzanine"]), status="ok", shells=0)
    sent = []

    def fake(payload, timeout=60.0):
        msg = json.loads(payload.decode("utf-8"))
        sent.append(msg)
        if msg["type"] == "structure_model":
            return json.dumps(m)
        if msg["type"] == "structure_draw":
            return json.dumps({"status": "pass", "analysis_method": "native"})
        return json.dumps({"status": "pass", "results": {"analysis_method": "api"}, "warnings": []})
    monkeypatch.setattr(srv, "_send_and_receive", fake)
    srv._sent = sent
    return srv


def test_tools_take_design_basis(server):
    out = json.loads(server.validate_structure(guids=["x"], structure_type="frame", load_kn=0, fixed_supports=False,
                                               floor_load_kn_m2=2.0, uls_combination="6.10ab"))
    assert [c["name"] for c in out["results"]["combinations"]] == ["SLS characteristic", "ULS 6.10a", "ULS 6.10b"]
    server.visualize_structure(guids=["x"], load_kn=0, fixed_supports=False, floor_load_kn_m2=2.0)
    assert "u: ULS 6.10 (1.35G + 1.5Q)" in server._sent[-1]["title"]
    assert "design_basis" in json.loads(server.validate_structure(guids=["x"], design_basis="lrfd"))["message"]
    assert "uls_combination" in json.loads(server.visualize_structure(guids=["x"], uls_combination="6.11"))["message"]
    kar = json.loads(server.validate_structure(guids=["x"], engine="karamba"))     # explicit Karamba: untouched
    assert not any("unfactored" in w for w in kar["warnings"])
