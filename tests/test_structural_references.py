"""The structural reference library: catalogue, model conversion, explicit model loads, closed-form checks and
the MCP tools (no Rhino: the bridge socket is mocked)."""
import asyncio
import json
import math
from pathlib import Path

import numpy as np
import pytest

from almond_mcp import frame_solver as fs
from almond_mcp import native_structure as ns
from almond_mcp import paths
from almond_mcp import structural_references as sr
from tests.test_capsules import BridgeMock, _call, _load_server

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "StructuralReferences"
pytestmark = pytest.mark.skipif(not LIBRARY.is_dir(), reason="StructuralReferences not in this checkout")
lib = sr.ReferenceLibrary(LIBRARY)

SMALL = {                                   # parameters that keep every reference quick to solve in CI
    "moment-frame": {"bx": 1, "by": 1, "storeys": 2}, "braced-tower": {"n": 1, "storeys": 2},
    "pratt-truss": {"panels": 6}, "warehouse": {"frames": 2}, "space-grid": {"nx": 3}, "arch": {"n": 8},
    "canopy": {"n": 2}, "diagrid": {"nseg": 6, "levels": 2}, "vierendeel": {"panels": 4},
}


# ── catalogue and builders ───────────────────────────────────────────────────
def test_paths_resolve_the_library_like_the_others(monkeypatch):
    monkeypatch.delenv("RHINO_MCP_STRUCTURAL_REFERENCE_DIR", raising=False)
    assert Path(paths.resolve_dir("RHINO_MCP_STRUCTURAL_REFERENCE_DIR")) == LIBRARY
    assert "StructuralReferences" in paths.VERSIONED_LIBRARIES


def test_catalogue_covers_every_benchmarked_builder():
    ids = [e["id"] for e in lib.entries]
    assert len(ids) == len(set(ids)) == 12
    assert {e["builder"] for e in lib.entries} == set(sr.BUILDERS)
    for e in lib.entries:
        assert e["structure_type"] in ns.LINE_TYPES
        assert e["study"]["material"] and e["study"]["connections"] in ("rigid", "simple")
        assert e["teaching"] and e["summary"] and e["exercises"] and e["supports"]
        defaults = lib.parameters(e, None)
        assert set(defaults) == {p["name"] for p in e["parameters"]}
        if e["study"].get("span_parameter"):
            assert e["study"]["span_parameter"] in defaults
        for p in e["parameters"]:
            if p.get("type", "float") in ("int", "float"):
                assert p["min"] <= p["default"] <= p["max"]


def test_typology_shim_keeps_the_benchmark_interface():
    from tests import structural_typologies as T
    assert T.ALL is sr.ALL and T.refined is sr.refined
    assert len(T.ALL) == 12 and T.pratt_truss()["frame"].elements


def test_parameters_are_validated():
    e = lib.entry("moment-frame")
    assert lib.parameters(e, {"storeys": "3"})["storeys"] == 3
    with pytest.raises(ValueError, match="Unknown parameter"):
        lib.parameters(e, {"wind": 5})
    with pytest.raises(ValueError, match="between"):
        lib.parameters(e, {"storeys": 99})
    with pytest.raises(ValueError, match="whole number"):
        lib.parameters(e, {"bx": 2.5})
    with pytest.raises(ValueError, match="finite"):
        lib.parameters(e, {"bay": float("nan")})
    arch = lib.entry("arch")
    assert lib.parameters(arch, {"ends": "fixed"})["ends"] == "fixed"
    with pytest.raises(ValueError, match="one of"):
        lib.parameters(arch, {"ends": "roller"})
    tower = lib.entry("braced-tower")
    assert lib.parameters(tower, {"plan_bracing": "yes"})["plan_bracing"] is True
    with pytest.raises(KeyError):
        lib.entry("nope")


def test_search_matches_text_and_family():
    assert lib.search()["total"] == 12
    hits = lib.search("truss")
    assert {"pratt-truss", "space-grid"} <= {c["id"] for c in hits["references"]}
    assert hits["references"][0]["matched_terms"] == ["truss"]
    assert all(c["family"] == "tower" for c in lib.search(family="tower")["references"])
    assert lib.search("zzzz-nothing")["total"] == 0


# ── model conversion ─────────────────────────────────────────────────────────
def test_section_and_release_words_round_trip():
    for sec in (fs.chs(219.1, 10), fs.rhs(400, 200, 12.5), fs.rect(300, 640)):
        back, notes = ns.section_from_spec(sr.section_spec(sec))
        assert not notes and back.A == pytest.approx(sec.A) and back.Iy == pytest.approx(sec.Iy)
    assert sr.section_text(fs.rhs(400, 200, 12.5)) == "box 200x400x12.5"      # width x depth x wall
    assert sr.section_text(fs.chs(114.3, 4)) == "chs 114.3x4"
    with pytest.raises(ValueError):
        sr.section_spec(fs.i_section(300, 300, 11, 19))
    bar = fs.Element(0, 1, fs.chs(100, 5), sr.S355, truss=True)
    assert sr.release_text(bar) == "bar"
    simple = fs.Element(0, 1, fs.chs(100, 5), sr.S355, releases=fs.release_mask(True, True, minor=False))
    assert sr.release_text(simple) == "hinged"
    one = fs.Element(0, 1, fs.chs(100, 5), sr.S355, releases=fs.release_mask(False, True))
    assert sr.release_text(one) == "pinned_end"
    assert sr.release_text(fs.Element(0, 1, fs.chs(100, 5), sr.S355)) is None


def test_support_spec_matches_the_parse_grammar():
    cases = [((True,) * 6, (0.0,) * 6), ((True, True, True, False, False, False), (0.0,) * 6),
             ((False, True, True, False, False, False), (0.0,) * 6), ((False, False, True, False, False, False), (0.0,) * 6),
             ((True, True, True, False, False, True), (0, 0, 0, 8000, 8000, 0)),
             ((False,) * 6, (1e5, 1e5, 5e4, 2e4, 2e4, 2e4)), ((False, True, False, False, False, False), (0.0,) * 6)]
    for restraint, springs in cases:
        text = sr.support_spec(restraint, springs)
        back_r, back_k, _ = ns.parse_support(text)
        assert back_r == tuple(restraint) and back_k == pytest.approx(tuple(float(k) for k in springs)), text
    assert sr.support_spec((True, True, True, False, False, True), (0, 0, 0, 8000, 8000, 0)) == "fixed rx=8000 ry=8000"
    assert sr.support_spec((False, True, False, False, False, False), (0.0,) * 6) == "lateral-y"
    with pytest.raises(ValueError):
        sr.support_spec((False, True, False, True, False, True), (0.0,) * 6)      # a planar in-plane restraint


def test_model_carries_members_supports_and_loads_and_drops_wind():
    built = sr.mixed_supports()
    model, report = sr.to_model(built["frame"], reference_id="mixed-supports")
    assert len(model["members"]) == 13 and model["units"] == "m" and "anchor_points" not in model
    assert sorted(report["supports"]) == ["fixed", "fixed rx=8000 ry=8000", "pinned", "roller", "roller-x",
                                          "spring kx=100000 ky=100000 kz=50000 rx=20000 ry=20000 rz=20000"]
    assert report["dropped_cases"] == {"W": 2} and any("wind" in n for n in report["notes"])
    assert report["loads"]["member"] == 8 and report["loads"]["nodal"] == 0
    assert report["loads"]["total_vertical_kn"]["G"] == pytest.approx(4 * 12 * 6) and \
        report["loads"]["total_vertical_kn"]["Q"] == pytest.approx(4 * 9 * 6)
    uniform, rep2 = sr.to_model(sr.canopy()["frame"])
    assert rep2["supports_mode"] == "anchor_points" and rep2["default_fixed"] is True and len(uniform["anchor_points"]) == 5


def test_planar_models_get_lateral_restraints_and_hinged_members():
    model, report = sr.to_model(sr.pratt_truss(panels=6)["frame"], planar=True)
    assert report["supports"] == {"pinned": 1, "roller-x": 1, "lateral-y": 10}
    assert all(m["release"] == "hinged" for m in model["members"])
    bare, report2 = sr.to_model(sr.pratt_truss(panels=6)["frame"], planar=True, lateral_restraints=False)
    assert report2["supports"] == {"pinned": 1, "roller-x": 1} and len(bare["supports"]) == 2
    assert any("without its out-of-plane" in n for n in report2["notes"])


@pytest.mark.parametrize("name", ["canopy", "mixed_supports", "vierendeel", "braced_tower"])
def test_model_path_reproduces_the_benchmark_frame(name):
    """The frame rebuilt from the model (the path validate_structure takes) gives the benchmark's displacements."""
    kwargs = {"vierendeel": {"panels": 4}, "braced_tower": {"n": 1, "storeys": 2}}.get(name, {})
    built = sr.BUILDERS[name](**kwargs)
    planar = name == "vierendeel"
    model, _ = sr.to_model(built["frame"], planar=planar)
    fixed = all(all(f) for f in built["frame"].supports.values())
    frame, info, notes = ns.build_frame(model, 0.0, "S355", fixed, self_weight=built["frame"].gravity is not None)
    a = fs.solve(built["frame"], combination={"G": 1.0, "Q": 1.0})
    b = fs.solve(frame, combination={"G": 1.0, "Q": 1.0})
    assert b.max_displacement == pytest.approx(a.max_displacement, rel=1e-6)
    assert float(b.reactions[:, 2].sum()) == pytest.approx(float(a.reactions[:, 2].sum()), rel=1e-6)
    assert info["model_loads"]["count"] == len(model["loads"])


# ── explicit loads in build_frame ────────────────────────────────────────────
def _beam_model(release=None):
    m = {"source_guids": ["b"], "points": [[0, 0, 0], [6, 0, 0]], "section": {"shape": "box", "height": 0.3, "width": 0.2, "wall": 0.01}}
    if release:
        m["release"] = release
    return {"members": [m], "anchor_points": [[0, 0, 0], [6, 0, 0]], "tolerance_m": 0.001, "max_member_span_m": 6.0,
            "max_span_m": 6.0, "warnings": []}


def test_model_loads_apply_udl_and_point_loads_with_their_cases():
    model = _beam_model("hinged")
    model["members"][0]["points"] = [[0, 0, 0], [3, 0, 0], [6, 0, 0]]          # a midspan node for the point load
    model["loads"] = [{"member": 0, "w_kn_m": [0, 0, -10], "case": "G"}, {"point_m": [3, 0, 0], "force_kn": [0, 0, -20]}]
    frame, info, notes = ns.build_frame(model, 0.0, "S355", True, self_weight=False)
    assert info["model_loads"] == {"count": 2, "nodal": 1, "member": 1}
    assert notes[-1:] == [] or all("ignored" not in n for n in notes)
    sec = fs.rhs(300, 200, 10)
    EI = sr.S355.E * sec.Iy
    g = fs.solve(frame, combination={"G": 1.0})
    assert g.max_displacement == pytest.approx(5 * 10 * 6 ** 4 / (384 * EI), rel=1e-9)        # simply supported UDL
    q = fs.solve(frame, combination={"Q": 1.0})
    assert q.max_displacement == pytest.approx(20 * 6 ** 3 / (48 * EI), rel=1e-9)             # midspan point load
    assert info["loaded_nodes"] == [frame.nodes.index((3.0, 0.0, 0.0))]


def test_model_loads_validate_and_warn():
    model = _beam_model()
    model["loads"] = [{"point_m": [3, 2, 0], "force_kn": [0, 0, -1]}, {"member": 7, "w_kn_m": [0, 0, -1]}]
    frame, info, notes = ns.build_frame(model, 0.0, "S355", True, self_weight=False)
    assert "model_loads" not in info and len([n for n in notes if "ignored" in n]) == 2
    for bad in ([{"member": 0, "w_kn_m": [0, 0, -1], "case": "W"}], [{"case": "Q"}], [{"member": 0}], "nope"):
        model["loads"] = bad
        with pytest.raises(ValueError):
            ns.build_frame(model, 0.0, "S355", True, self_weight=False)


def test_linearly_varying_member_load_is_split_over_pieces():
    model = _beam_model()
    model["members"][0]["points"] = [[0, 0, 0], [2, 0, 0], [6, 0, 0]]
    model["loads"] = [{"member": 0, "w_start_kn_m": [0, 0, 0], "w_end_kn_m": [0, 0, -12]}]
    frame, info, _ = ns.build_frame(model, 0.0, "S355", True, self_weight=False)
    pieces = [(e, wa, wb) for (e, wa, wb, case) in frame.member_loads]
    assert len(pieces) == 2
    assert pieces[0][1][2] == pytest.approx(0) and pieces[0][2][2] == pytest.approx(-4)
    assert pieces[1][1][2] == pytest.approx(-4) and pieces[1][2][2] == pytest.approx(-12)
    r = fs.solve(frame, combination={"Q": 1.0})
    assert float(r.reactions[:, 2].sum()) == pytest.approx(12 * 6 / 2, rel=1e-9)


def test_bar_and_hinged_release_words():
    for word, minor in (("bar", True), ("hinged", False)):
        start, end, source, m = ns._release_ends({"points": [[0, 0, 0], [0, 0, 4]], "release": word}, "rigid")
        assert (start, end, source, m) == (True, True, "user", minor)
    assert ns._release_ends({"points": [[0, 0, 0], [0, 0, 4]], "release": "pinned"}, "rigid")[3] is True  # column: both


def test_lateral_support_types_parse():
    r, k, label = ns.parse_support("lateral-y")
    assert r == (False, True, False, False, False, False) and not any(k) and label == "lateral-y"
    assert ns.parse_support("lateral-x")[0] == (True, False, False, False, False, False)


# ── analysis and closed forms ────────────────────────────────────────────────
@pytest.mark.parametrize("rid", [e["id"] for e in lib.entries])
def test_every_reference_analyses_without_rhino(rid):
    r = sr.analyze(lib, rid, SMALL.get(rid), stability="off")
    assert r["status"] in ("pass", "fail"), r.get("verdict")
    assert r["results"]["analysis_method"] == "native"
    ref = r["reference"]
    assert ref["id"] == rid and ref["members"] == r["results"]["elements"] or ref["members"] <= r["results"]["elements"]
    assert ref["study"]["stability"] == "off" and ref["loads"]["total_vertical_kn"]["Q"] > 0
    assert all(c.get("ok", False) for c in ref["checks"]), ref["checks"]
    if lib.entry(rid).get("planar"):
        assert "lateral-y" in ref["supports"]


def test_closed_forms_hold_through_the_model_protocol():
    checks = {c["quantity"]: c for c in sr.analyze(lib, "pratt-truss", stability="off")["reference"]["checks"]}
    assert checks["midspan deflection"]["rel_error"] < 1e-6 and checks["largest member force error"]["almond"] < 1e-8
    checks = {c["quantity"]: c for c in sr.analyze(lib, "portal", stability="off")["reference"]["checks"]}
    assert checks["horizontal thrust at a base"]["rel_error"] < 5e-3
    checks = {c["quantity"]: c for c in sr.analyze(lib, "arch", {"n": 16}, stability="off")["reference"]["checks"]}
    assert checks["horizontal thrust"]["rel_error"] < 1e-3 and checks["largest bending moment / M0 (funicular: ~0)"]["almond"] < 1e-3
    r = sr.analyze(lib, "l-bracket", stability="off")
    checks = {c["quantity"]: c for c in r["reference"]["checks"]}
    assert checks["tip deflection"]["rel_error"] < 1e-6 and checks["torsion in the first arm"]["rel_error"] < 1e-6
    assert r["results"]["max_deflection_mm"] == pytest.approx(checks["tip deflection"]["almond"], rel=1e-3)


def test_study_span_follows_the_parameter_and_overrides_apply():
    r = sr.analyze(lib, "pratt-truss", {"span": 24.0, "panels": 6}, stability="off")
    assert r["results"]["span_m"] == 24.0 and r["results"]["span_basis"] == "user"
    assert r["reference"]["study"]["self_weight"] is False
    r2 = sr.analyze(lib, "pratt-truss", {"span": 24.0, "panels": 6}, stability="off", self_weight=True, material="S235")
    assert r2["reference"]["study"]["self_weight"] is True and r2["results"]["reactions_kn"] > r["results"]["reactions_kn"]
    assert r2["results"]["yield_stress_mpa"] == 235


def test_stability_runs_and_the_arch_goes_unstable_when_overloaded():
    ok = sr.analyze(lib, "arch", {"n": 8, "w": 5.0}, checks=False)
    assert ok["status"] == "pass" and ok["results"]["stability"]["min_alpha_cr"] > 1
    bad = sr.analyze(lib, "arch", {"n": 8, "w": 60.0}, checks=False)
    assert bad["status"] == "fail" and "Instability" in bad["verdict"]


def test_rhino_study_names_the_nearest_validate_call():
    entry, params, model, report = sr.reference_model(lib, "canopy", {"n": 2})
    study = sr.study_settings(entry)
    rs = sr.rhino_study(entry, report, study)
    args = rs["validate_structure"]
    assert args["structure_type"] == "canopy" and args["fixed_supports"] is True
    assert args["load_kn"] == pytest.approx(report["loads"]["total_vertical_kn"]["Q"], abs=0.1)
    assert any("permanent" in n for n in rs["notes"])


# ── Rhino placement script ───────────────────────────────────────────────────
def test_place_script_carries_user_text_and_counts():
    entry, params, model, report = sr.reference_model(lib, "mixed-supports")
    script = sr.place_script(entry, model, report["built"], 1000, 2000, 0, "Refs")
    assert "public static List<Guid> Run(RhinoDoc doc)" in script
    assert script.count("{") > 13 and '"box 200x400x12.5"' in script and '"box 250x250x10"' in script
    assert '"fixed rx=8000 ry=8000"' in script and '"roller-x"' in script and "const int Supports = 6;" in script
    assert 'SetUserString("almond:section"' in script and 'SetUserString("almond:support"' in script
    assert 'FindByFullPath("Refs"' in script and "UnitScale(UnitSystem.Meters" in script
    with pytest.raises(ValueError):
        sr.place_script(entry, model, report["built"], float("inf"), 0, 0)
    with pytest.raises(ValueError):
        sr.place_script(entry, model, report["built"], 0, 0, 0, "A::B")
    tower = sr.reference_model(lib, "braced-tower", {"n": 1, "storeys": 1})
    script = sr.place_script(tower[0], tower[2], tower[3]["built"])
    assert '"bar"' in script and '"hinged"' in script and "Almond Reference braced-tower" in script


# ── MCP tools ────────────────────────────────────────────────────────────────
@pytest.fixture
def server(monkeypatch, tmp_path):
    cap = tmp_path / "capsules"
    cap.mkdir()
    monkeypatch.setenv("RHINO_MCP_STRUCTURAL_REFERENCE_DIR", str(LIBRARY))
    return _load_server(monkeypatch, tmp_path, cap)


def test_list_and_get_tools(server):
    listing = _call(server.list_structural_references)
    assert listing["status"] == "success" and listing["total"] == 12
    assert _call(server.list_structural_references, family="truss")["total"] == 2
    got = _call(server.get_structural_reference, reference_id="mixed-supports")
    assert got["status"] == "success" and "builder" not in got
    assert got["model"]["members"] == 13 and got["rhino"]["validate_structure"]["structure_type"] == "frame"
    assert got["parameters_used"] == {"bay": 6.0, "h": 4.0}
    assert _call(server.get_structural_reference, reference_id="nope")["status"] == "error"
    assert _call(server.get_structural_reference, reference_id="arch", parameters={"n": 999})["status"] == "error"
    pratt = _call(server.get_structural_reference, reference_id="pratt-truss", parameters={"span": 20.0})
    assert pratt["study_resolved"]["span_m"] == 20.0


def test_analyze_tool_returns_the_validation_contract(server):
    r = _call(server.analyze_structural_reference, reference_id="l-bracket", stability="off")
    assert r["status"] == "pass" and r["results"]["analysis_method"] == "native" and r["reference"]["checks"]
    assert r["verdict"].startswith(ns.METHOD_PREFIX)
    bad = _call(server.analyze_structural_reference, reference_id="l-bracket", parameters={"a": 50})
    assert bad["status"] == "error" and "between" in bad["message"]
    assert _call(server.analyze_structural_reference, reference_id="zzz")["status"] == "error"


def test_place_tool_sends_the_script_and_maps_guids(server, monkeypatch):
    guids = [f"0000000{i:x}-0000-0000-0000-000000000000"[:36] for i in range(19)]
    mock = BridgeMock(json.dumps({"status": "success", "guids": guids}))
    monkeypatch.setattr(server, "_send_and_receive", mock)
    r = _call(server.place_structural_reference, reference_id="mixed-supports", x_mm=500)
    assert r["status"] == "success" and r["members"] == 13 and r["supports"] == 6
    assert r["member_guids"] == guids[:13] and r["support_guids"] == guids[13:]
    (payload, _), = mock.payloads
    assert payload["type"] == "execute" and 'almond:support' in payload["script"] and "500.0 * mm" in payload["script"]
    assert r["rhino"]["validate_structure"]["load_kn"] == pytest.approx(216.0)
    assert _call(server.place_structural_reference, reference_id="nope")["status"] == "error"
    assert len(mock.payloads) == 1
    planar = _call(server.place_structural_reference, reference_id="portal")
    assert planar["supports"] == 2 and any("lateral" in n for n in planar["rhino"]["notes"])
    (_, _), (payload2, _) = mock.payloads
    assert "const int Supports = 2;" in payload2["script"]
    laterals = _call(server.place_structural_reference, reference_id="portal", lateral_restraints=True)
    assert "const int Supports = 5;" in mock.payloads[-1][0]["script"]


def test_bridge_failure_is_reported(server, monkeypatch):
    monkeypatch.setattr(server, "_send_and_receive", BridgeMock(json.dumps({"status": "compile_error", "message": "x"})))
    r = _call(server.place_structural_reference, reference_id="l-bracket")
    assert r["status"] == "error" and r["bridge"]["status"] == "compile_error"


def test_resources_and_annotations(server):
    from fastmcp import Client

    async def check():
        async with Client(server.mcp) as client:
            tools = {t.name: t for t in await client.list_tools()}
            assert tools["list_structural_references"].annotations.readOnlyHint
            assert tools["analyze_structural_reference"].annotations.readOnlyHint
            assert not tools["place_structural_reference"].annotations.destructiveHint
            catalogue = await client.read_resource("almond://structural/catalogue")
            assert json.loads(catalogue[0].text)["total"] == 12
            model = await client.read_resource("almond://structural/l-bracket/model")
            data = json.loads(model[0].text)
            assert len(data["members"]) == 2 and data["loads"][0]["force_kn"][2] == pytest.approx(-0.8)
    asyncio.run(check())
