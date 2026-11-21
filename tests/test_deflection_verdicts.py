"""The checked deflection is each member's deflection relative to what holds it, the overlay's verdict is
validate's, and sway is checked as storey drift (live test 2026-10-11: a 59.4 m twisted steel tower passed
validate_structure but visualize_structure drew "max d 176 mm FAIL" from the absolute displacement, and at
60 degrees of twist its gently helical columns read their full sway as deflection)."""
import json
import math

import pytest

from almond_mcp import design_codes as dc
from almond_mcp import frame_solver as fs
from almond_mcp import native_structure as ns
from almond_mcp import structure_study as st
from tests.test_capsules import _load_server
from tests.test_hand_calculations import model as one_member

FLOOR = {"imposed": 3.0, "dead": 4.0}


def leaning_frame(storeys, bay=6.0, h=3.5, lean=0.0, col=(0.3239, 0.0125), beam=(0.3239, 0.0125)):
    """A one-bay tower whose column lines lean ``lean`` (dx/dz): under gravity it sways sideways. Each
    column storey and each beam is its own curve; the column lines are straight (one member each)."""
    cs = {"shape": "circular_hollow", "diameter": col[0], "wall": col[1]}
    bs = {"shape": "circular_hollow", "diameter": beam[0], "wall": beam[1]}
    corners = [(0, 0), (bay, 0), (bay, bay), (0, bay)]
    members = []
    for s in range(storeys):
        for k, (x, y) in enumerate(corners):
            members.append({"source_guids": [f"c{k}_{s}"], "section": cs,
                            "points": [[x + lean * s * h, y, s * h], [x + lean * (s + 1) * h, y, (s + 1) * h]]})
        z = (s + 1) * h
        for k, ((x0, y0), (x1, y1)) in enumerate(zip(corners, corners[1:] + corners[:1])):
            members.append({"source_guids": [f"b{k}_{s}"], "section": bs,
                            "points": [[x0 + lean * z, y0, z], [x1 + lean * z, y1, z]]})
    return {"members": members, "anchor_points": [[x, y, 0] for x, y in corners], "tolerance_m": 0.001,
            "max_member_span_m": bay, "max_span_m": storeys * h, "warnings": [], "status": "ok", "shells": 0}


def twisted_tower(twist_deg, storeys=9, h=6.6, R=8.5, n=8):
    """Columns from node k on one floor to node k on the next, each floor turned twist/storeys: at 60 degrees
    the column pieces kink by ~1.3 degrees, within the collinearity tolerance, so each helical column line is
    one member from the foundation to the roof."""
    sec = {"shape": "circular_hollow", "diameter": 0.4064, "wall": 0.016}

    def p(k, s):
        a = 2 * math.pi * k / n + math.radians(twist_deg) * s / storeys
        return [R * math.cos(a), R * math.sin(a), s * h]
    lines = [(p(k, s), p(k, s + 1), f"col{k}_{s}") for s in range(storeys) for k in range(n)]
    for s in range(1, storeys + 1):
        lines += [(p(k, s), p((k + 1) % n, s), f"ring{k}_{s}") for k in range(n)]
        lines += [([0, 0, s * h], p(k, s), f"spoke{k}_{s}") for k in range(n)]
    members = [{"source_guids": [t], "points": [a, b], "section": sec} for a, b, t in lines]
    return {"members": members, "anchor_points": [p(k, 0) for k in range(n)], "tolerance_m": 0.001,
            "max_member_span_m": max(math.dist(a, b) for a, b, _ in lines), "max_span_m": storeys * h,
            "warnings": [], "status": "ok", "shells": 0}


@pytest.fixture(scope="module")
def tall():
    return leaning_frame(12, lean=0.02)


@pytest.fixture
def server(monkeypatch, tmp_path):
    cap = tmp_path / "capsules"
    cap.mkdir()
    return _load_server(monkeypatch, tmp_path, cap)


def old_bridge(server, monkeypatch, model_reply, status):
    """A bridge that judges the overlay itself, as almondbridge <= 0.7 does (absolute displacement vs the
    limit and utilization only), and always answers ``status``."""
    sent = []

    def fake(payload, timeout=60.0):
        msg = json.loads(payload.decode("utf-8"))
        sent.append(msg)
        if msg["type"] == "structure_model":
            return json.dumps(model_reply)
        res = msg.get("result") or {}
        return json.dumps({"status": status, "analysis_method": "native",
                           "max_displacement_mm": res.get("max_displacement_mm", 1.0), "deflection_limit_mm": 24.0})
    monkeypatch.setattr(server, "_send_and_receive", fake)
    return sent


# -- (a) tall frame: the absolute displacement exceeds span/250, the member deflection does not ---------

def test_tall_frame_passes_on_member_deflection(tall):
    out = ns.validate(tall, "frame", 0, floor_loads=FLOOR, stability="off")
    r = out["results"]
    assert out["status"] == "pass", out["verdict"]
    assert r["max_displacement_mm"] > 2 * r["deflection_limit_mm"] > 2 * r["max_deflection_mm"]
    assert r["storey_drift"]["checked"] and 0 < r["storey_drift"]["utilization"] < 1.0


def test_visualize_reports_validates_verdict_even_from_an_old_bridge(server, monkeypatch, tall):
    """The bridge's own legend judged the absolute displacement (FAIL); the server's verdict is validate's."""
    sent = old_bridge(server, monkeypatch, tall, "fail")
    ref = ns.validate(tall, "frame", 0, floor_loads=FLOOR, stability="off")["results"]
    out = json.loads(server.visualize_structure(guids=["x"], load_kn=0, floor_load_kn_m2=3.0, floor_dead_kn_m2=4.0,
                                                stability="off", structure_type="frame"))
    assert out["status"] == "pass" and out["passed"] is True and out["failures"] == []
    assert out["max_deflection_mm"] == pytest.approx(ref["max_deflection_mm"], rel=1e-9)
    assert out["deflection_limit_mm"] == pytest.approx(ref["deflection_limit_mm"])
    assert out["max_displacement_mm"] > out["deflection_limit_mm"]           # absolute: still reported
    assert out["deflection_measure"].startswith("member")
    assert out["storey_drift"]["max_drift_mm"] == pytest.approx(ref["storey_drift"]["max_drift_mm"])
    draw = sent[-1]
    assert draw["verdict_status"] == "pass"                                  # a new bridge shows this verdict
    assert draw["result"]["max_deflection_mm"] == pytest.approx(ref["max_deflection_mm"], rel=1e-9)
    assert draw["result"]["max_displacement_mm"] > draw["result"]["deflection_limit_mm"]
    # a display-only update keeps the native verdict too
    again = json.loads(server.visualize_structure(guids=["x"], reanalyze=False, reveal=0.5))
    assert again["status"] == "pass" and sent[-1]["verdict_status"] == "pass" and "result" not in sent[-1]


def test_panel_overlay_verdict_matches_its_validation(tall):
    out = st.run({"protocol": 1, "model": tall, "settings": {
        "structure": "frame", "load_kn": 0, "floor_imposed_kn_m2": 3.0, "floor_dead_kn_m2": 4.0, "stability": "off"}})
    assert out["status"] == "pass" and out["draw"]["verdict_status"] == "pass"
    v = out["validation"]["results"]
    assert out["draw"]["result"]["max_deflection_mm"] == pytest.approx(v["max_deflection_mm"], rel=1e-9)
    assert out["draw"]["result"]["deflection_limit_mm"] == pytest.approx(v["deflection_limit_mm"])


# -- the overlay verdict reflects every check validate fails on ------------------------------------

def test_visualize_fails_class_4_members_like_validate(server, monkeypatch):
    """A slender section (CHS 219.1x2.9 in S355 is Class 4) fails validate at a tiny utilization; an old
    bridge's legend sees only displacement and utilization and says PASS."""
    m = one_member([[0, 0, 3], [6, 0, 3]], [[0, 0, 3], [6, 0, 3]], 6.0)
    m["members"][0]["section"] = {"shape": "circular_hollow", "diameter": 0.2191, "wall": 0.0029}
    ref = ns.validate(m, "beam", 0.0, material="S355", fixed_supports=False)
    assert ref["status"] == "fail" and "Class 4" in ref["verdict"] and ref["results"]["utilization_ratio"] < 1
    sent = old_bridge(server, monkeypatch, m, "pass")
    out = json.loads(server.visualize_structure(guids=["x"], load_kn=0, material="S355", fixed_supports=False))
    assert out["status"] == "fail" and out["passed"] is False and out["class4_members"] == 1
    assert any("Class 4" in f for f in out["failures"])
    assert sent[-1]["verdict_status"] == "fail"


def test_visualize_fails_utilization_and_deflection_like_validate(server, monkeypatch):
    m = one_member([[0, 0, 3], [6, 0, 3]], [[0, 0, 3]], 6.0)              # a cantilever, load at the tip
    ref = ns.validate(m, "beam", 60.0)
    assert ref["status"] == "fail" and "Utilization" in ref["verdict"] and "Deflection" in ref["verdict"]
    old_bridge(server, monkeypatch, m, "pass")
    out = json.loads(server.visualize_structure(guids=["x"], load_kn=60.0))
    assert out["status"] == "fail" and len(out["failures"]) == len(ref["verdict"].split("; "))


def test_view_result_verdict_equals_validate_status(tall):
    for lean, kind in ((0.02, "frame"), (0.2, "frame"), (0.2, "truss")):
        m = leaning_frame(1 if lean > 0.1 else 12, lean=lean)
        kw = dict(floor_loads=FLOOR, stability="off")
        res, _ = ns.view_result(m, 0.0, structure_type=kind, **kw)
        assert res["verdict"]["status"] == ns.validate(m, kind, 0.0, **kw)["status"]


# -- (b) columns that sway but bend little --------------------------------------------------------

def test_helical_columns_sway_is_not_deflection():
    m = twisted_tower(60)
    frame, _, _ = ns.build_frame(m, 0.0, "Steel", True, True, floor_loads=FLOOR)
    col = next(i for i, e in enumerate(frame.elements) if e.tag == ["col0_8"])
    group = next(g for g in ns._member_groups(frame) if col in g)
    assert len(group) == 9                              # the regime of the bug: one member foundation -> roof
    out = ns.validate(m, "frame", 0.0, floor_loads=FLOOR, stability="off", span_m=12.0, detail=True)
    straight = ns.validate(twisted_tower(0), "frame", 0.0, floor_loads=FLOOR, stability="off", span_m=12.0, detail=True)
    for o in (out, straight):
        top = [r for r in o["members"] if r["source_guids"][0].endswith("_8") and r["source_guids"][0].startswith("col")]
        assert len(top) == 8
        for r in top:
            assert r["deflection_mm"] < 0.05 * r["max_displacement_mm"] or r["max_displacement_mm"] < 20
            assert r["deflection_mm"] < 12.0                # bends a few mm between the floors
    # the sway is reported where it belongs: as storey drift (this tower unwinds under gravity)
    drift = out["results"]["storey_drift"]
    assert drift["max_drift_mm"] > 20 * straight["results"]["storey_drift"]["max_drift_mm"]
    assert len(drift["storeys"]) == 9


def test_lone_post_with_an_arm_stays_a_cantilever():
    """Nothing but its root holds a free-standing post (its arm is not a floor): the post's deflection
    includes its sway, measured from the root as for any cantilever."""
    f = fs.Frame()
    s, mat = fs.chs(219.1, 8), fs.material("S355")
    base, top, tip = f.add_node((0, 0, 0)), f.add_node((0, 0, 4)), f.add_node((2, 0, 4))
    f.fix(base)
    f.add_element(base, top, s, mat, tag=["post"])
    f.add_element(top, tip, s, mat, tag=["arm"])
    f.load(tip, fz=-10)
    r = fs.solve(f)
    d = ns.member_deflections(f, r)
    assert float(d[0].max()) == pytest.approx(math.hypot(*r.displacements[top, :2]), rel=1e-6)
    assert ns.storey_drift(f, r, 300)["storeys"] == []


def test_braced_column_deflection_is_measured_between_its_floors():
    """A column held by floors at both ends: the chord through its displaced ends is the reference, so a
    storey sway of the whole frame adds nothing to the column's own deflection."""
    m = leaning_frame(1, lean=0.2)
    out = ns.validate(m, "frame", 400, fixed_supports=False, stability="off", detail=True)
    cols = [r for r in out["members"] if r["source_guids"][0].startswith("c")]
    for r in cols:
        assert r["max_displacement_mm"] > 10 and r["deflection_mm"] < 0.2 * r["max_displacement_mm"]


# -- (c) storey drift -------------------------------------------------------------------------------

def test_storey_drift_matches_a_sway_portal_closed_form():
    """Fixed-base portal with a rigid beam, horizontal load H: drift = H h^3 / (12 E I n)."""
    f = fs.Frame()
    col, mat, h, H = fs.chs(219.1, 8), fs.material("S355"), 4.0, 20.0
    beam = fs.chs(1500, 60)                                     # practically rigid
    a, b = f.add_node((0, 0, 0)), f.add_node((6, 0, 0))
    c, d = f.add_node((0, 0, h)), f.add_node((6, 0, h))
    f.fix(a)
    f.fix(b)
    f.add_element(a, c, col, mat, tag=["c1"])
    f.add_element(b, d, col, mat, tag=["c2"])
    f.add_element(c, d, beam, mat, tag=["b"])
    f.load(c, fx=H)
    for n in (a, b, c, d):                                      # planar: no out-of-plane sway or twist
        old = f.supports.get(n, (False,) * 6)
        f.fix(n, (old[0], True, old[2], True, old[4], True))
    r = fs.solve(f)
    out = ns.storey_drift(f, r, 300)
    expected = H * h ** 3 / (12 * 210e6 * col.Iy * 2)
    assert out["governing"]["drift_mm"] == pytest.approx(expected * 1000, rel=0.02)
    assert out["governing"]["limit_mm"] == pytest.approx(h * 1000 / 300, abs=1e-3)
    assert out["governing"]["utilization"] == pytest.approx(expected * 300 / h, rel=0.02)
    assert [(s["z_bottom_m"], s["z_top_m"]) for s in out["storeys"]] == [(0.0, 4.0)]
    # column deflection excludes the drift: only the double-curvature bending between the ends remains
    defl = ns.member_deflections(f, r)
    assert float(defl[0].max()) < 0.2 * expected


def test_storey_drift_fails_the_verdict_and_is_reported():
    m = leaning_frame(1, lean=0.2)
    out = ns.validate(m, "frame", 400, fixed_supports=False, stability="off")
    drift = out["results"]["storey_drift"]
    assert out["status"] == "fail" and "Storey drift" in out["verdict"] and "h/300" in out["verdict"]
    assert drift["checked"] and drift["utilization"] > 1 and drift["basis"] == "project default"
    assert drift["governing"]["drift_mm"] > drift["governing"]["limit_mm"]
    assert any("Stiffen the lateral system" in s for s in out["suggestions"])
    assert any("storey drift limit h/300 (project default" in a for a in out["assumptions"])
    # a truss's posts turn with the truss: drift is reported but not judged
    truss = ns.validate(m, "truss", 400, fixed_supports=False, stability="off")
    assert truss["results"]["storey_drift"]["checked"] is False and "Storey drift" not in truss["verdict"]
    # when the drift governs a pass, the verdict names it
    mild = ns.validate(leaning_frame(1, lean=0.1), "frame", 400, fixed_supports=False, stability="off")
    assert mild["status"] == "pass" and "storey drift" in mild["verdict"]


def test_drift_limit_is_a_project_default_in_the_profile(tmp_path, monkeypatch):
    code = dc.load("eurocode")
    assert code.storey_drift_limit_ratio == 300.0 and code.project_defaults == ("storey_drift_limit_ratio",)
    assert not code.unverified and dc.load("eurocode").listing()["verified"] is True
    raw = json.loads((dc.BUILT_IN / "eurocode.json").read_text(encoding="utf-8"))["parameters"]["storey_drift_limit_ratio"]
    assert raw["verified"] is False and raw["project_default"] is True and "not a code value" in raw["source"]
    assert dc.load("off").storey_drift_limit_ratio == 300.0
    # a practice sets its own (verified or not) limit; a profile without one falls back to the default
    doc = json.loads((dc.BUILT_IN / "eurocode.json").read_text(encoding="utf-8"))
    doc.update(id="strict-drift", name="Strict drift", basis="Test")
    doc["parameters"]["storey_drift_limit_ratio"] = {"value": 500, "source": "Project brief 4.2", "verified": True}
    (tmp_path / "strict-drift.json").write_text(json.dumps(doc), encoding="utf-8")
    old = dict(doc, id="old-profile")
    old["parameters"] = {k: v for k, v in doc["parameters"].items() if k != "storey_drift_limit_ratio"}
    (tmp_path / "old-profile.json").write_text(json.dumps(old), encoding="utf-8")
    monkeypatch.setenv("ALMOND_DESIGN_CODE_DIR", str(tmp_path))
    strict = dc.load("strict-drift")
    assert strict.storey_drift_limit_ratio == 500.0 and not strict.project_defaults
    assert dc.load("old-profile").project_defaults == ("storey_drift_limit_ratio",)
    m = leaning_frame(1, lean=0.1)
    out = ns.validate(m, "frame", 400, fixed_supports=False, stability="off", design_code="strict-drift")
    drift = out["results"]["storey_drift"]
    assert drift["limit_ratio"] == 500.0 and drift["basis"] == "design code profile" and out["status"] == "fail"
