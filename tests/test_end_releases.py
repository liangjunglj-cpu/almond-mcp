"""Member end releases: static condensation, closed forms, mechanisms, simple connections, tools."""
import json
import math

import numpy as np
import pytest

from almond_mcp import frame_solver as fs
from almond_mcp import native_structure as ns
from tests.test_capsules import _load_server
from tests.test_native_structure import CASES, model as ref_model

STEEL, SEC = fs.material("Steel"), fs.chs(114.3, 4.0)
EI = STEEL.E * SEC.Iy


def beam(n, L, rel_start, rel_end, w=0.0, supports="fixed"):
    f = fs.Frame()
    ids = [f.add_node((L * i / n, 0, 0)) for i in range(n + 1)]
    for i in range(n):
        f.add_element(ids[i], ids[i + 1], SEC, STEEL, releases=fs.release_mask(rel_start and i == 0, rel_end and i == n - 1))
        if w:
            f.udl(i, (0, 0, -w))
    if supports == "fixed":
        f.fix(ids[0]); f.fix(ids[-1])
    else:
        f.pin(ids[0]); f.pin(ids[-1])
    return f, ids


@pytest.mark.parametrize("n", [1, 3])
def test_pinned_both_ends_is_simply_supported(n):
    L, w = 6.0, 8.0
    f, ids = beam(n, L, True, True, w)
    r = fs.solve(f)
    assert min(np.min(er.disp[:, 2]) for er in r.elements) == pytest.approx(-5 * w * L ** 4 / (384 * EI), rel=1e-9)
    assert abs(r.elements[0].My[0]) < 1e-9 and abs(r.elements[-1].My[-1]) < 1e-9          # zero end moments
    assert abs(r.reactions[ids[0], 4]) < 1e-9 and r.reactions[ids[0], 2] == pytest.approx(w * L / 2)


def test_one_released_end_is_a_propped_cantilever():
    L, w = 4.0, 10.0
    f, ids = beam(1, L, False, True, w)
    r = fs.solve(f)
    assert r.reactions[ids[1], 2] == pytest.approx(3 * w * L / 8, rel=1e-9)
    assert abs(r.reactions[ids[0], 4]) == pytest.approx(w * L ** 2 / 8, rel=1e-9)


def test_splitting_keeps_releases_at_the_outer_ends():
    f, ids = beam(1, 6.0, True, True, 5.0)
    k = f.split_element(0, 0.4)
    a, b = f.elements
    assert a.releases[4] and not any(a.releases[6:]) and b.releases[10] and not any(b.releases[:6])
    r = fs.solve(f)
    x = 0.4 * 6.0
    exact = -5.0 * x * (6.0 ** 3 - 2 * 6.0 * x ** 2 + x ** 3) / (24 * EI)                    # simple-span curve
    assert r.displacements[k, 2] == pytest.approx(exact, rel=1e-9)


def test_torsion_released_at_both_ends_is_rejected():
    f, _ = beam(1, 3.0, False, False)
    rel = [False] * 12
    rel[3] = rel[9] = True
    f.elements[0].releases = tuple(rel)
    with pytest.raises(ValueError, match="unstable"):
        fs.solve(f)


def test_unloaded_twist_mode_is_suppressed_but_a_hinge_chain_is_a_mechanism():
    """Pinned supports + a pin-ended member split into pieces: the pieces could twist as a group
    (no load acts on that), which is pinned out; two pin-ended members in line with nothing
    under the shared node is a real mechanism."""
    f, ids = beam(1, 6.0, True, True, 4.0, supports="pinned")
    k1 = f.split_element(0, 0.3)
    k2 = f.split_element(1, 0.5)
    r = fs.solve(f)
    simple = lambda x: -4.0 * x * (6.0 ** 3 - 2 * 6.0 * x ** 2 + x ** 3) / (24 * EI)
    assert r.auto_restrained
    assert r.displacements[k1, 2] == pytest.approx(simple(1.8), rel=1e-9)
    assert r.displacements[k2, 2] == pytest.approx(simple(3.9), rel=1e-9)
    g = fs.Frame()
    n = [g.add_node((x, 0, 0)) for x in (0, 3, 6)]
    for i in range(2):
        g.add_element(n[i], n[i + 1], SEC, STEEL, releases=fs.release_mask(True, True))
    g.fix(n[0]); g.fix(n[2]); g.load(n[1], fz=-1.0)
    with pytest.raises(fs.MechanismError):
        fs.solve(g)


def portal(simple=True, joist_pieces=1):
    """Fixed-base portal (6 m beam on 3 m columns) as an exported model."""
    beam_pts = [[6 * i / joist_pieces, 0, 3] for i in range(joist_pieces + 1)]
    members = [{"source_guids": ["c1"], "points": [[0, 0, 0], [0, 0, 3]]},
               {"source_guids": ["c2"], "points": [[6, 0, 0], [6, 0, 3]]}]
    members += [{"source_guids": [f"b{i}"], "points": [beam_pts[i], beam_pts[i + 1]]} for i in range(joist_pieces)]
    return {"members": members, "anchor_points": [[0, 0, 0], [6, 0, 0]], "tolerance_m": 0.001,
            "max_member_span_m": 6, "max_span_m": 6}


def test_simple_connections_make_the_beam_simply_supported():
    w = 6.0
    for pieces in (1, 3):            # a beam drawn in three collinear pieces is still one continuous beam
        f, info, _ = ns.build_frame(portal(joist_pieces=pieces), 0, self_weight=False, connections="simple")
        for ei, e in enumerate(f.elements):
            if e.tag[0].startswith("b"):
                f.udl(ei, (0, 0, -w))
        r = fs.solve(f)
        sag = -min(np.min(er.disp[:, 2]) for er in r.elements if f.elements[er.index].tag[0].startswith("b"))
        shorten = (w * 6 / 2) * 3 / (STEEL.E * SEC.A)                                       # column axial shortening
        assert sag == pytest.approx(5 * w * 6 ** 4 / (384 * EI) + shorten, rel=1e-6)
        assert info["connections"]["pinned_ends"] == 2                                       # only where the beam stops


def test_rigid_portal_deflects_less_than_simple():
    run = lambda c: ns.validate(portal(), "frame", 10, connections=c)["results"]["max_deflection_mm"]
    assert run("rigid") < run("simple")


def test_user_release_overrides_and_needs_curve_direction():
    m = portal()
    m["members"][2]["release"] = "pinned_end"
    m["members"][2]["curve_start_m"], m["members"][2]["curve_end_m"] = [0, 0, 3], [6, 0, 3]
    f, info, _ = ns.build_frame(m, 0, connections="rigid")
    beam_el = next(e for e in f.elements if e.tag[0] == "b0")
    assert not beam_el.releases[4] and beam_el.releases[10] and info["connections"]["user_released_members"] == 1
    del m["members"][2]["curve_start_m"], m["members"][2]["curve_end_m"]
    f, _, warnings = ns.build_frame(m, 0, connections="rigid")
    beam_el = next(e for e in f.elements if e.tag[0] == "b0")
    assert beam_el.releases[4] and beam_el.releases[10] and any("curve direction" in x for x in warnings)


def test_mezzanine_simple_connections_need_a_bigger_tube():
    kw = dict(structure_type="frame", load_kn=0, fixed_supports=False, span_m=6.2, floor_loads={"imposed": 2.0, "dead": 1.0})
    m = ref_model(CASES["mezzanine"])
    rigid = ns.validate(m, diameter_mm=219.1, wall_mm=8.0, connections="rigid", **kw)
    simple = ns.validate(m, diameter_mm=219.1, wall_mm=8.0, connections="simple", **kw)
    assert rigid["status"] == "pass" and simple["status"] == "fail"
    assert simple["results"]["connections"]["pinned_ends"] == 14 and simple["results"]["equilibrium_error_kn"] < 1e-6
    assert ns.validate(m, diameter_mm=244.5, wall_mm=10.0, connections="simple", **kw)["status"] == "pass"
    assert any("Connections: simple" in a for a in simple["assumptions"])


@pytest.fixture
def server(monkeypatch, tmp_path):
    cap = tmp_path / "capsules"
    cap.mkdir()
    srv = _load_server(monkeypatch, tmp_path, cap)
    sent = []

    def fake(payload, timeout=60.0):
        msg = json.loads(payload.decode("utf-8"))
        sent.append(msg)
        if msg["type"] == "structure_model":
            return json.dumps(dict(portal(), status="ok", shells=0))
        return json.dumps({"status": "pass", "analysis_method": "native"})
    monkeypatch.setattr(srv, "_send_and_receive", fake)
    srv._sent = sent
    return srv


def test_tools_take_connections(server):
    out = json.loads(server.validate_structure(guids=["x"], structure_type="frame", connections="simple"))
    assert out["results"]["connections"]["mode"] == "simple"
    server.visualize_structure(guids=["x"], connections="simple")
    hinges = [e["hinges"] for e in server._sent[-1]["result"]["elements"]]
    assert [True, True] in hinges and [False, False] in hinges
    assert "connections" in json.loads(server.validate_structure(guids=["x"], connections="welded"))["message"]
