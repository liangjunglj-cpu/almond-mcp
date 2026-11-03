"""Constructions library, code packs, SET*, user-defined rooms (enclosed / semi-open / open), diagrams and
the panel engine."""
from __future__ import annotations

import io
import json
import math
import re
import xml.dom.minidom
from pathlib import Path

import numpy as np
import pytest

from almond_mcp.environment import (codes, comfort, constructions as asm, diagrams, panel, rhino, rooms as rm,
                                    scene as S, studies, thermal)
from tests.env_weather import synthetic_epw, synthetic_weather
from tests.test_capsules import _call, _load_server
from tests.test_environment import ExportingBridge

ALLOWED_LICENCES = {"LicenseRef-EnergyPlus", "MIT", "LicenseRef-PublicDomain-DE-UrhG-5", "CC-BY-4.0", "OGL-UK-3.0",
                    "LicenseRef-Method-Cited", "LicenseRef-SG-ODL-1.0", "CC0-1.0"}


@pytest.fixture(autouse=True)
def _runs_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv(studies.RUNS_ENV, str(tmp_path / "runs"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))


@pytest.fixture(scope="module")
def tropical():
    return synthetic_weather(latitude=1.35, longitude=103.8, time_zone=8.0, mean_t=27.5, annual_amp=1.0, daily_amp=4.0,
                             rh=78.0, cloudiness=0.6)


@pytest.fixture(scope="module")
def tropical_epw(tmp_path_factory):
    return synthetic_epw(tmp_path_factory.mktemp("w") / "tropical.epw")


# ── constructions ────────────────────────────────────────────────────────────

def test_u_value_matches_hand_calculation():
    m = asm.materials()
    r = (0.13 + 0.01 / m["stucco"]["conductivity"] + 0.16 / m["insulation_eps"]["conductivity"]
         + 0.2 / m["concrete_2400"]["conductivity"] + 0.015 / m["plaster_lime_cement"]["conductivity"] + 0.04)
    p = asm.properties("ew_rc_etics")
    assert p["u_value"] == pytest.approx(1 / r, abs=0.002)
    assert 0.19 < p["u_value"] < 0.23
    # heat-flow direction changes the surface resistances: a roof uses R_si 0.10, a ground floor 0.17
    assert asm.properties("roof_rc_warm_flat")["r_si"] == 0.10
    assert asm.properties("floor_ground_rc_xps")["r_si"] == 0.17
    # internal elements have an internal film on both sides
    iw = asm.properties("iw_rc_exposed")
    assert iw["r_se"] == iw["r_si"] == 0.13


def test_air_layer_resistance_is_physical():
    r = asm._air_layer_r(0.05, "horizontal")
    assert 0.15 < r < 0.2                    # a 50 mm unventilated cavity: about 0.17-0.18 m2K/W
    assert asm._air_layer_r(0.05, "down") > asm._air_layer_r(0.05, "up")


def test_kappa_periodic_method():
    # exposed heavy concrete: ~70-90 kJ/m2K with the inner surface resistance; insulated side far less
    sandwich = asm.properties("ew_rc_sandwich_exposed")
    assert 70 < sandwich["kappa_inside_kj_m2k"] < 95
    etics = asm.properties("ew_rc_etics")
    assert etics["kappa_outside_kj_m2k"] < 25 < etics["kappa_inside_kj_m2k"]
    stud = asm.properties("iw_stud_gypsum")
    assert stud["kappa_inside_kj_m2k"] < 20
    # a floor seen from above (oak, screed, then impact insulation) holds less than its concrete soffit
    floor = asm.properties("floor_internal_rc_oak")
    assert floor["kappa_inside_kj_m2k"] < floor["kappa_outside_kj_m2k"]


def test_glazing_against_known_glass():
    single = asm.properties("win_single_clear_alu")
    assert single["u_g"] == pytest.approx(5.8, abs=0.15)
    assert single["g_value"] == pytest.approx(0.82, abs=0.03)
    assert single["tau_v"] == pytest.approx(0.88, abs=0.01)
    dbl = asm.properties("win_double_lowe_ar_timber")
    tri = asm.properties("win_triple_lowe_ar_timber")
    assert 1.0 < dbl["u_g"] < 1.5 and 0.6 < tri["u_g"] < 1.0
    assert tri["g_value"] < dbl["g_value"] < single["g_value"]
    sel = asm.properties("win_sg_double_selective_alu")
    assert sel["tau_v"] / sel["g_value"] > 1.4                 # spectrally selective: light without heat
    # U_w by the area-weighted method
    expect = (1 - dbl["frame_fraction"]) * dbl["u_g"] + dbl["frame_fraction"] * dbl["u_f"] + dbl["edge_m_per_m2"] * dbl["psi_g"]
    assert dbl["u_value"] == pytest.approx(expect, abs=0.002)


def test_custom_assembly_and_validation():
    p = asm.properties({"kind": "wall_external", "layers": [{"material": "concrete_2400", "thickness_m": 0.25}]})
    assert p["id"] == "custom" and 3 < p["u_value"] < 4.5
    with pytest.raises(ValueError, match="unknown material"):
        asm.get({"kind": "wall_external", "layers": [{"material": "unobtainium", "thickness_m": 0.1}]})
    with pytest.raises(ValueError, match="kind"):
        asm.get({"kind": "bridge", "layers": [{"material": "concrete_2400", "thickness_m": 0.1}]})
    with pytest.raises(ValueError, match="Unknown construction"):
        asm.get("nope")


def test_library_provenance_and_licences():
    sources = asm.sources()
    for s in sources.values():
        assert s["licence"] in ALLOWED_LICENCES, s["id"]
    for m in asm.materials().values():
        assert m["source"] in sources, m["id"]
        if "optical_source" in m:
            assert m["optical_source"] in sources
    for p in asm.glass_panes().values():
        assert p["source"] in sources
    for f in asm.frames().values():
        assert f["source"] in sources
    for a in asm.library().values():
        asm.validate(a)
        asm.properties(a["id"])
    kinds = {a["id"]: a["kind"] for a in asm.library().values()}
    for s in asm._load("assemblies.json")["sets"]:
        for kind, cid in s["defaults"].items():
            assert cid in kinds, (s["id"], cid)
            assert kinds[cid] == kind or (kind == "floor_exposed" and kinds[cid].startswith("floor")), (s["id"], kind, cid)
    for p in codes.packs():
        assert p["licence"] in ALLOWED_LICENCES and p["relation"] in ("bundled", "method", "user-supplied")


# ── code packs ───────────────────────────────────────────────────────────────

def test_ettv_formula_worked_example():
    surfaces = [{"kind": "wall_external", "area": 70.0, "normal": (0, -1, 0), "u_value": 2.0},
                {"kind": "window", "area": 30.0, "normal": (0, -1, 0), "u_value": 5.0, "g_value": 0.87 * 0.5}]
    r = codes.envelope_transfer(surfaces, None, user_tables={"ETTV_walls": {"S": 1.0}})
    f = r["facades"][0]
    expect = 12 * 0.7 * 2.0 + 3.4 * 0.3 * 5.0 + 211 * 0.3 * 1.0 * 0.5
    assert f["value_w_m2"] == pytest.approx(expect, abs=0.01) and f["cf_source"] == "user table"
    assert r["passes"] is False and r["limit_w_m2"] == 50.0
    retv = codes.envelope_transfer(surfaces, None, residential=True, user_tables={"RETV_walls": {"S": 1.0}})
    assert retv["index"] == "RETV" and retv["facades"][0]["value_w_m2"] == pytest.approx(
        3.4 * 0.7 * 2.0 + 1.3 * 0.3 * 5.0 + 58.6 * 0.3 * 1.0 * 0.5, abs=0.01)


def test_solar_correction_factors_follow_the_sun(tropical):
    cf = codes.solar_correction_factors(tropical)["walls"]
    # near the equator east and west facades take the most sun, north and south the least
    assert min(cf["E"], cf["W"]) > max(cf["N"], cf["S"])
    assert np.mean(list(cf.values())) == pytest.approx(1.0, abs=1e-3)


def test_uk_de_eu_packs():
    surfaces = [{"kind": "wall_external", "area": 100, "u_value": 0.2}, {"kind": "window", "area": 20, "u_value": 1.8}]
    uk = codes.check_envelope(surfaces, "uk_adl_2021")
    by = {e["element"]: e for e in uk["elements"]}
    assert by["wall_external"]["passes"] and not by["window"]["passes"] and uk["passes"] is False
    assert uk["provenance"]["licence"] == "OGL-UK-3.0"
    de = codes.check_envelope([], "de_banz_2020", age_band="1958-1968")
    assert de["opaque"]["roof_solid"]["u"] == 1.3 and de["windows"]["timber_double"]["u_w"] == 2.7
    eu = codes.check_envelope([], "eu_hotmaps", country="de")
    assert eu["u_values_by_age"][">2010"]["wall"] < eu["u_values_by_age"]["<1945"]["wall"]
    with pytest.raises(ValueError):
        codes.check_envelope([], "nowhere")


# ── SET* ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("args, expect", [
    ((25, 25, 0.15, 50, 1.0, 0.5), 23.8), ((25, 25, 0.15, 10, 1.0, 0.5), 23.3), ((25, 25, 0.15, 90, 1.0, 0.5), 24.9),
    ((25, 25, 0.15, 50, 1.0, 1.0), 27.3), ((25, 25, 0.15, 50, 1.0, 2.0), 32.5), ((25, 40, 0.15, 50, 1.0, 0.5), 31.8)])
def test_set_star_reference_cases(args, expect):
    assert float(comfort.set_star(*args)) == pytest.approx(expect, abs=0.3)


# ── rooms ────────────────────────────────────────────────────────────────────

def _box(x0, y0, z0, x1, y1, z1):
    v = [[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0], [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]]
    f = [[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]]
    return np.array(v, float).ravel().tolist(), np.array(f).ravel().tolist()


def _model() -> dict:
    objs = []

    def add(name, layer, geo, **kw):
        v, f = geo
        objs.append({"guid": f"{len(objs):08d}-0000-0000-0000-000000000000", "layer": layer, "name": name, "material": "",
                     "transparency": 0, "env_material": "", "vertices": v, "faces": f, **kw})
    add("Living", "Rooms", _box(0, 0, 0, 5, 4, 3), room="Living", room_use="living", room_set="eu_new_build")
    add("Bed", "Rooms", _box(5, 0, 0, 9, 4, 3), room="Bed", room_use="bedroom", room_set="eu_new_build")
    add("Window S", "Glazing", ([1, -0.01, 0.8, 4, -0.01, 0.8, 4, -0.01, 2.4, 1, -0.01, 2.4], [0, 1, 2, 0, 2, 3]),
        construction="win_triple_lowe_ar_timber")
    X = 12
    add("Loggia", "Rooms", _box(X, 0, 0, X + 3, 3, 3), room="Loggia", room_use="living")
    for name, geo in (("N", _box(X, 3, 0, X + 3, 3.2, 3)), ("E", _box(X + 3, 0, 0, X + 3.2, 3.2, 3)), ("W", _box(X - 0.2, 0, 0, X, 3.2, 3))):
        add(f"Loggia wall {name}", "Walls", geo, construction="ew_sg_rc_plastered")
    add("Loggia roof", "Roof", _box(X - 0.2, 0, 3, X + 3.2, 3.2, 3.2), construction="roof_sg_rc_insulated")
    P = 20
    add("Pavilion roof", "Pavilion", _box(P, 0, 3, P + 4, 4, 3.1), room="Pavilion", room_use="outdoor", construction="roof_sg_metal_insulated")
    for i, (x, y) in enumerate([(0, 0), (3.8, 0), (0, 3.8), (3.8, 3.8)]):
        add(f"Post {i}", "Pavilion", _box(P + x, y, 0, P + x + 0.2, y + 0.2, 3), room="Pavilion")
    # a room drawn as an L-shaped boundary curve, 2.8 m high, in open space
    objs.append({"guid": f"{len(objs):08d}-0000-0000-0000-000000000000", "layer": "Rooms", "name": "Study",
                 "room": "Study", "room_use": "office", "room_height": "2.8",
                 "boundary": [30, 0, 0, 34, 0, 0, 34, 2, 0, 32, 2, 0, 32, 4, 0, 30, 4, 0], "vertices": [], "faces": []})
    return {"units_to_m": 1.0, "rhino_north_deg": 90.0, "objects": objs, "missing": [], "skipped": []}


def test_enclosure_states():
    rooms, encs, scene, notes = studies.prepare_rooms(_model())
    state = {r.name: e for r, e in zip(rooms, encs)}
    assert state["Living"].state == "enclosed" and state["Living"].self_enclosed      # window + neighbour only
    assert state["Bed"].state == "enclosed"
    loggia = state["Loggia"]
    assert loggia.state == "semi_open" and [o["orientation"] for o in loggia.openings] == ["S"]
    assert loggia.open_fraction == pytest.approx(0.2, abs=0.03)
    assert state["Pavilion"].state == "open" and {r.source for r in rooms if r.name == "Pavilion"} == {"surfaces"}
    assert any("not enclosed" in n for n in notes) and any("open space" in n for n in notes)
    study = next(r for r in rooms if r.name == "Study")
    assert study.source == "boundary" and rm._floor_area(study) == pytest.approx(12.0, abs=0.01)
    assert study.height == pytest.approx(2.8)
    # the loggia picked up the wall and roof constructions of the elements around it
    assert {"ew_sg_rc_plastered", "roof_sg_rc_insulated"} <= set(loggia.tri_construction)


def test_rooms_thermal_coupled_and_open(tropical):
    res = studies.run_rooms_thermal(_model(), tropical, thermal.Settings(schedule="residential"),
                                    envelope_pack="sg_bca", pack_options={"residential": True})
    by = {r["room"]: r for r in res["rooms"]}
    assert by["Living"]["method"] == "5R1C" and by["Loggia"]["method"] == "5R1C + openings"
    assert by["Pavilion"]["method"] == "semi_outdoor"
    # neighbours exchange heat, and the exchange balances
    ie = res["engine"]["interzone"]
    assert ie["links"] == 2 and abs(ie["net_interzone_kwh"]) < 0.01 * max(ie["gross_interzone_kwh"], 1.0)
    living = by["Living"]["thermal"]
    assert living["model"]["mass_class"] == "from constructions"
    surf = {(c["surface"], c["construction"]) for c in living["constructions"]}
    assert ("interzone", "iw_stud_gypsum") in surf and ("window", "win_triple_lowe_ar_timber") in surf
    # open to outside: no heating or cooling, air through the opening
    loggia = by["Loggia"]["thermal"]
    assert loggia["heating_kwh"] == 0 and loggia["cooling_kwh"] == 0 and loggia["model"]["opening_ach_mean"] > 1
    pav = by["Pavilion"]["comfort"]
    assert 0.3 < pav["sky_view_mean"] < 0.9 and pav["mrt_minus_air_occupied_mean_k"] > 0
    assert pav["set_c"]["mean_occupied"] > 20
    assert res["envelope_check"]["index"] == "RETV" and res["envelope_check"]["provenance"]["relation"] == "method"
    _, arrays = studies.load_run(res["run_id"])
    assert any(k.endswith("_set") for k in arrays) and any(k.endswith("_t_op") for k in arrays)


def test_opening_air_changes(tropical):
    one = [{"orientation": "S", "normal": [0, -1, 0], "area_m2": 4.0, "z_min": 0.0, "z_max": 2.0}]
    two = one + [{"orientation": "N", "normal": [0, 1, 0], "area_m2": 4.0, "z_min": 0.0, "z_max": 2.0}]
    a1 = rm.opening_air_changes(one, 60.0, tropical)
    a2 = rm.opening_air_changes(two, 60.0, tropical)
    assert a1.min() > 0 and a2.mean() > a1.mean()              # cross ventilation beats single-sided
    assert rm.opening_air_changes([], 60.0, tropical).sum() == 0


def test_scene_uses_construction_finishes():
    data = _model()
    sc = S.scene_from_export(data)
    names = {m.name for m in sc.materials}
    assert "c:win_triple_lowe_ar_timber" in names
    glass = next(m for m in sc.materials if m.name == "c:win_triple_lowe_ar_timber")
    assert glass.kind == "glazing" and glass.transmittance == pytest.approx(asm.summary("win_triple_lowe_ar_timber")["tau_v"])
    roof = next(m for m in sc.materials if m.name == "c:roof_sg_rc_insulated:out")
    assert roof.reflectance == asm.summary("roof_sg_rc_insulated")["outside_reflectance"]


def test_prism_concave_boundary():
    v, f = rm.prism(np.array([[0, 0], [4, 0], [4, 2], [2, 2], [2, 4], [0, 4]], float), 0.0, 3.0)
    a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    vol = float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6)
    assert vol == pytest.approx(12.0 * 3.0, abs=1e-6)
    with pytest.raises(ValueError):
        rm.prism(np.array([[0, 0], [1, 0]], float), 0, 3)


def test_tag_script_validation():
    s = rhino.tag_script({"0b6e3f1e-1111-2222-3333-444455556666": {"room": "Living", "room_use": "living"}})
    assert '"room_use", "living"' in s and "BeginUndoRecord" in s
    with pytest.raises(ValueError, match="Unknown tag"):
        rhino.tag_script({"0b6e3f1e-1111-2222-3333-444455556666": {"colour": "red"}})
    with pytest.raises(ValueError, match="plain text"):
        rhino.tag_script({"0b6e3f1e-1111-2222-3333-444455556666": {"room": 'a"b'}})
    with pytest.raises(ValueError, match="GUID"):
        rhino.tag_script({"not-a-guid": {"room": "x"}})
    e = rhino.export_script([], "C:/tmp/x.json")
    assert "almond:construction" not in e and '"construction", "room"' in e and "EmitBoundary" in e


# ── diagrams and the panel engine ───────────────────────────────────────────

def test_diagrams_render(tmp_path):
    svgs = [diagrams.step_strip("rooms", ("site",)).svg(), diagrams.construction_section(asm.properties("ew_clt")).svg(),
            diagrams.construction_section(asm.properties("win_curtain_wall_selective")).svg(),
            diagrams.site_diagram(1.35, 103.8, 8.0).svg(), diagrams.study_section("thermal").svg(),
            diagrams.room_plan([{"name": "A", "outline": [(0, 0), (4, 0), (4, 3), (0, 3)], "state": "open", "area": 12}]).svg(),
            diagrams.results_tiles([("12", "heating", "kWh/m²")]).svg()]
    for s in svgs:
        xml.dom.minidom.parseString(s)
        assert diagrams.PAPER not in s or True
        assert diagrams.INK in s
    out = diagrams.construction_section(asm.properties("ew_rc_etics")).png(str(tmp_path / "s.png"))
    from PIL import Image
    assert Image.open(out).size == (1040, 600)


def test_site_diagram_keeps_the_name_away_from_the_north_mark():
    """Live panel run: a long site name at the top ran into the 'N' of a north-up compass."""
    name = "Zurich.Affoltern, ZH, CHE"
    for north, top in ((0.0, False), (200.0, True)):
        doc = xml.dom.minidom.parseString(diagrams.site_diagram(47.43, 8.52, 1.0, north, name).svg())
        texts = {t.firstChild.data: float(t.getAttribute("y")) for t in doc.getElementsByTagName("text") if t.firstChild}
        assert (texts[name] < 150) is top and (texts["N"] < 150) is not top


def test_panel_diagrams_sit_on_paper_in_a_dark_panel():
    """Live panel run: in Rhino's dark theme --paper turns dark and the engine's ink drawings vanished."""
    ui = Path(diagrams.__file__).resolve().parents[1] / "library_ui"
    css = (ui / "environment.css").read_text(encoding="utf-8")
    assert re.search(r"\.env-diagram svg\{[^}]*background:var\(--sheet\)", css)
    assert re.search(r"\.env-strip svg\{[^}]*background:var\(--sheet\)", css)
    assert f"--sheet:{diagrams.PAPER}" in css.lower()
    assert "Climate, Rooms <br>&amp; Comfort" in (ui / "index.html").read_text(encoding="utf-8")   # panel hides the <br>


def _panel(req: dict) -> dict:
    out = io.StringIO()
    panel.main(io.StringIO(json.dumps(req)), out)
    return json.loads(out.getvalue())


def test_panel_engine(tropical_epw):
    cat = _panel({"action": "catalogue"})
    assert cat["status"] == "ok" and set(cat["steps"]) == {"site", "rooms", "constructions", "study", "results"}
    assert any(c["id"] == "ew_rc_etics" for c in cat["constructions"]) and cat["packs"]
    con = _panel({"action": "construction", "id": "roof_rc_warm_flat"})
    assert con["status"] == "ok" and con["svg"].startswith("<svg") and con["construction"]["u_value"] < 0.2
    rooms = _panel({"action": "rooms", "export": _model()})
    assert rooms["status"] == "ok" and {r["room"] for r in rooms["rooms"]} >= {"Living", "Loggia", "Pavilion"}
    site = _panel({"action": "site", "epw_path": tropical_epw.source_path})
    assert site["status"] == "ok" and abs(site["site"]["latitude"] - 1.35) < 0.01
    run = _panel({"action": "run", "study": "thermal", "export": _model(), "epw_path": tropical_epw.source_path,
                  "settings": {"schedule": "residential"}})
    assert run["status"] == "ok" and run["svg"].startswith("<svg") and run["draw"].startswith("Q,")
    bad = _panel({"action": "nope"})
    assert bad["status"] == "error"


# ── MCP tools ────────────────────────────────────────────────────────────────

@pytest.fixture()
def server(monkeypatch, tmp_path):
    caps = tmp_path / "capsules"
    caps.mkdir()
    return _load_server(monkeypatch, tmp_path, caps)


def test_tools_constructions_and_rooms(server, monkeypatch, tropical_epw):
    lib = _call(server.list_constructions, region="sg")
    assert lib["status"] == "success" and all("sg" in c["regions"] or "any" in c["regions"] for c in lib["constructions"])
    one = _call(server.get_construction, construction="win_sg_double_selective_alu")
    assert one["status"] == "success" and one["section_svg"].startswith("<svg")
    custom = _call(server.get_construction, custom={"kind": "roof", "layers": [{"material": "concrete_2400", "thickness_m": 0.2}]},
                   diagram=False)
    assert custom["status"] == "success" and "section_svg" not in custom
    packs = _call(server.list_code_packs)
    assert {p["pack"] for p in packs["packs"]} == {"sg_bca", "uk_adl_2021", "de_banz_2020", "eu_hotmaps"}
    bridge = ExportingBridge(_model())
    monkeypatch.setattr(server, "_send_and_receive", bridge)
    listed = _call(server.list_rooms)
    assert listed["status"] == "success" and {r["enclosure"]["state"] for r in listed["rooms"]} == {"enclosed", "semi_open", "open"}
    r = _call(server.analyze_rooms, epw_path=tropical_epw.source_path, study="thermal", envelope_pack="uk_adl_2021")
    assert r["status"] == "success" and r["envelope_check"]["pack"] == "uk_adl_2021"
    tag = _call(server.define_room, name="Hall", guids=["0b6e3f1e-1111-2222-3333-444455556666"], use="circulation")
    assert tag["status"] == "success" and "BeginUndoRecord" in bridge.payloads[-1][0]["script"]
    bad = _call(server.define_room, name="Hall", guids=["0b6e3f1e-1111-2222-3333-444455556666"], use="ballroom")
    assert bad["status"] == "error"
    asg = _call(server.assign_construction, guids=["0b6e3f1e-1111-2222-3333-444455556666"], construction="ew_clt")
    assert asg["status"] == "success" and asg["summary"]["kind"] == "wall_external"
    nope = _call(server.assign_construction, guids=["0b6e3f1e-1111-2222-3333-444455556666"], construction="ew_nope")
    assert nope["status"] == "error"


def test_internal_openings_are_not_outdoor(tropical):
    """A double-height hall open to a gallery inside a closed shell: the opening is internal, not to outside."""
    objs = []

    def add(name, geo, **kw):
        v, f = geo
        objs.append({"guid": f"{len(objs):08d}-1111-0000-0000-000000000000", "layer": "B", "name": name, "material": "",
                     "transparency": 0, "env_material": "", "vertices": v, "faces": f, **kw})
    # shell 8 x 6 x 6 m with 0.2 m walls, roof and slab
    for name, geo in (("S", _box(0, -0.2, 0, 8, 0, 6)), ("N", _box(0, 6, 0, 8, 6.2, 6)), ("W", _box(-0.2, -0.2, 0, 0, 6.2, 6)),
                      ("E", _box(8, -0.2, 0, 8.2, 6.2, 6)), ("Roof", _box(-0.2, -0.2, 6, 8.2, 6.2, 6.2)),
                      ("Slab", _box(-0.2, -0.2, -0.2, 8.2, 6.2, 0)), ("Gallery", _box(4, 0, 2.8, 8, 6, 3.0))):
        add(name, geo, construction="ew_rc_etics" if len(name) == 1 else "roof_rc_warm_flat" if name == "Roof"
            else "floor_ground_rc_xps" if name == "Slab" else "floor_internal_rc_oak")
    # hall: west half, full height; its east face above the gallery opens onto the gallery space (no room there)
    objs.append({"guid": "hall0000-1111-0000-0000-000000000000", "layer": "R", "name": "Hall", "room": "Hall",
                 "room_use": "living", "room_height": "6", "boundary": [0, 0, 0, 4, 0, 0, 4, 6, 0, 0, 6, 0], "vertices": [], "faces": []})
    data = {"units_to_m": 1.0, "rhino_north_deg": 90.0, "objects": objs}
    rooms, encs, scene, notes = studies.prepare_rooms(data)
    e = encs[0]
    assert e.state == "enclosed" and not e.openings
    assert e.internal_openings and e.internal_openings[0]["orientation"] == "E" and e.internal_openings[0]["area_m2"] > 10
    assert any("adiabatic" in n for n in notes)
    res = studies.run_rooms_thermal(data, tropical, thermal.Settings(), cooling=False)
    t = res["rooms"][0]["thermal"]
    assert t["cooling_kwh"] == 0 and res["rooms"][0]["method"] == "5R1C"
    assert any(c["surface"] == "adiabatic" for c in t["constructions"])


def test_licence_scan_is_clean():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("license_scan", Path(__file__).resolve().parents[1] / "tools" / "license_scan.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    report = mod.scan()
    assert report["ok"], report["denied_or_unknown"]
    assert mod.classify("AGPL-3.0") == "deny" and mod.classify("CC-BY-SA-4.0") == "deny" and mod.classify("MIT") == "allow"
    assert mod.classify("MPL-2.0") == "review" and mod.classify("Apache-2.0 OR BSD-3-Clause") == "allow"


# ── test-drive regressions (2026-11-03) ─────────────────────────────────────

def _guid(n: int) -> str:
    return f"{n:08d}-0000-0000-0000-00000000ffff"


def _add(m: dict, name: str, layer: str, geo, **kw) -> None:
    v, f = geo
    m["objects"].append({"guid": _guid(len(m["objects"])), "layer": layer, "name": name, "material": "",
                         "transparency": 0, "env_material": "", "vertices": v, "faces": f, **kw})


def test_north_rotation_maps_facades_to_true_orientations(tropical):
    assert codes.orientation_of((0, 1, 0)) == "N"
    assert codes.orientation_of((0, 1, 0), 90.0) == "E"           # true azimuth = model azimuth + north
    assert codes.orientation_of((1, 0, 0), -90.0) == "N"
    cf = codes.solar_correction_factors(tropical)["walls"]          # per true orientation, independent of the model
    win = {"kind": "window", "area": 10.0, "normal": (0, 1, 0), "u_value": 1.0, "g_value": 0.5}
    for north, orient in ((0.0, "N"), (90.0, "E")):
        row = codes.envelope_transfer([win], tropical, north_deg=north)["facades"][0]
        assert row["orientation"] == orient and row["cf"] == cf[orient]


def test_interzone_exchange_conserves_heat_with_mixed_constructions(tropical):
    m = _model()
    for o in m["objects"]:
        if o.get("room") == "Bed":
            o["room_set"] = ""             # its side of the shared wall has no construction, Living's has one
    res = studies.run_rooms_thermal(m, tropical, thermal.Settings(schedule="residential"))
    ie = res["engine"]["interzone"]
    assert ie["gross_interzone_kwh"] > 1 and ie["net_interzone_kwh"] == 0.0


def test_room_inputs_are_checked():
    with pytest.raises(ValueError, match="metres"):
        rm.check_height(3000)
    with pytest.raises(ValueError, match="positive"):
        rm.check_height(-3)
    with pytest.raises(ValueError, match="below the cooling"):
        rm.parse_setpoints(26, 20)
    with pytest.raises(ValueError, match="outside"):
        rm.parse_setpoints(float("nan"), None)
    with pytest.raises(ValueError, match="not a temperature"):
        rm.parse_setpoints("warm", None)
    assert rm.parse_setpoints("off", "24") == {"heating_setpoint": None, "cooling_setpoint": 24.0}


def test_one_bad_room_does_not_stop_the_others():
    m = _model()
    m["objects"].append({"guid": _guid(90), "layer": "Rooms", "name": "Tall", "room": "Tall", "room_height": "3000",
                         "boundary": [40, 0, 0, 44, 0, 0, 44, 4, 0, 40, 4, 0], "vertices": [], "faces": []})
    _add(m, "Cupboard", "Rooms", _box(50, 0, 0, 51, 1, 1), room="Cupboard")
    _add(m, "Annex", "Rooms", _box(60, 0, 0, 63, 3, 3), room="Living", room_use="kitchen")   # a second "Living"
    m["skipped_rooms"] = [_guid(99)]
    rooms, encs, scene, notes = studies.prepare_rooms(m)
    names = {r.name for r in rooms}
    assert {"Bed", "Loggia", "Pavilion", "Study", "Cupboard"} <= names and not {"Tall", "Living"} & names
    assert any("Tall was skipped" in n and "metres" in n for n in notes)
    assert any("Living was skipped" in n and "disagree" in n for n in notes)
    assert any("no usable geometry" in n for n in notes)
    zones = rm.zones_from_rooms(rooms, encs, scene, studies._windows(scene), problems=notes)
    assert "Cupboard" not in {z.name for z in zones} and any("Cupboard was left out" in n for n in notes)


def test_raised_room_has_an_exposed_floor():
    m = _model()
    _add(m, "Studio", "Rooms", _box(50, 0, 3, 54, 4, 6), room="Studio", room_use="office")
    rooms, encs, scene, _ = studies.prepare_rooms(m)
    zones = {z.name: z for z in rm.zones_from_rooms(rooms, encs, scene, studies._windows(scene))}
    assert "exposed_floor" in zones["Studio"].areas() and "ground_floor" not in zones["Studio"].areas()
    assert "ground_floor" in zones["Bed"].areas()


def test_face_behind_a_window_takes_the_wall_construction():
    m = {"units_to_m": 1.0, "rhino_north_deg": 90.0, "objects": [], "missing": [], "skipped": []}
    _add(m, "Room", "Rooms", _box(0, 0, 0, 4, 4, 3), room="Room", room_use="living", room_set="eu_new_build")
    wall = "ew_timber_frame"
    for name, geo in (("N", _box(-0.2, 4, 0, 4.2, 4.2, 3)), ("E", _box(4, -0.2, 0, 4.2, 4.2, 3)),
                      ("W", _box(-0.2, -0.2, 0, 0, 4.2, 3)), ("S1", _box(0, -0.2, 0, 1, 0, 3)), ("S2", _box(3, -0.2, 0, 4, 0, 3))):
        _add(m, f"Wall {name}", "Walls", geo, construction=wall)
    _add(m, "Roof", "Roof", _box(-0.2, -0.2, 3, 4.2, 4.2, 3.2), construction="roof_rc_warm_flat_exposed")
    _add(m, "Window", "Glazing", ([1, -0.1, 0, 3, -0.1, 0, 3, -0.1, 3, 1, -0.1, 3], [0, 1, 2, 0, 2, 3]),
         construction="win_triple_lowe_ar_timber")
    rooms, encs, scene, _ = studies.prepare_rooms(m)
    assert encs[0].state == "enclosed"
    z = rm.zones_from_rooms(rooms, encs, scene, studies._windows(scene))[0]
    walls = {s.construction for s in z.surfaces if s.kind == "wall"}
    assert walls == {wall}                     # not the set's default wall standing in behind the window


def test_daylight_scene_keeps_own_windows_clear_and_closes_missing_floors():
    m = _model()
    rooms, encs, scene, _ = studies.prepare_rooms(m)
    dscene, notes = studies._daylight_shells(m, rooms, encs, scene, None)
    shells = {o.get("room_shell") for o in dscene.objects if o.get("room_shell")}
    assert "Living" in shells                     # the self-enclosed volume became its boundary without the glass
    living = next(i for i, o in enumerate(dscene.objects) if o.get("room_shell") == "Living")
    _, area = dscene.normals()
    box = 2 * (5 * 4 + 5 * 3 + 4 * 3)
    assert box - 6.0 < float(area[dscene.tri_object == living].sum()) < box - 3.0       # 4.8 m2 window left open
    vol = [i for i, o in enumerate(dscene.objects) if str(o.get("guid")) == m["objects"][0]["guid"]]
    kinds = {dscene.materials[int(k)].kind for k in dscene.tri_material[np.isin(dscene.tri_object, vol)]}
    assert kinds <= {"ignore"}                    # the volume itself no longer blocks its window
    assert any("Loggia" in n and "no floor element" in n for n in notes)


def test_point_in_time_reports_per_room(tropical):
    res = studies.run_rooms_daylight(_model(), tropical, "point_in_time", "draft", spacing=1.0,
                                     point_time={"month": 3, "day": 21, "hour": 10, "sky": "cie_overcast",
                                                 "horizontal_illuminance": 10000})
    rows = {r["room"]: r for r in res["rooms"]}
    assert rows["Living"]["mean_lux"] > 0 and "None" not in res["headline"]
    assert rows["Living"]["floor_area_m2"] == pytest.approx(20.0, abs=0.1)
    assert rows["Living"]["grid_area_m2"] <= rows["Living"]["floor_area_m2"]


def test_custom_builds_reject_impossible_values():
    for bad in ({"kind": "wall_external", "layers": "concrete"}, {"kind": "wall_external", "layers": ["concrete"]},
                {"kind": "wall_external", "layers": [{"material": "concrete_2400", "thickness_m": 0.2},
                                                     {"material": "air_layer", "thickness_m": 0}]},
                {"kind": "wall_external", "layers": [{"material": "concrete_2400", "thickness_m": "thick"}]}):
        with pytest.raises(ValueError):
            asm.properties(bad)
    win = asm.get("win_triple_lowe_ar_timber")
    for frame in ({"u_f": -5, "fraction": 0.2}, {"u_f": 1.3, "fraction": 1.5}):
        with pytest.raises(ValueError, match="frame"):
            asm.properties({**win, "id": "custom", "frame": frame})
    with pytest.raises(ValueError, match="gap"):
        asm.properties({**win, "id": "custom", "glazing": {**win["glazing"], "gaps": ["argon"] * len(win["glazing"]["gaps"])}})


def test_pack_options_are_parsed_strictly(tropical):
    assert codes.flag("false", "x") is False and codes.flag("yes", "x") is True and codes.flag(1, "x") is True
    with pytest.raises(ValueError):
        codes.flag("maybe", "residential")
    with pytest.raises(ValueError, match="Unknown code pack"):
        codes.check_options("xx", {})
    with pytest.raises(ValueError, match="Unknown option"):
        codes.check_options("sg_bca", {"residental": True})
    with pytest.raises(ValueError, match="Hotmaps"):
        codes.check_options("eu_hotmaps", {"country": "zz"})
    win = {"kind": "window", "area": 10.0, "normal": (0, -1, 0), "u_value": 1.0, "g_value": 0.5}
    assert codes.check_envelope([win], "sg_bca", tropical, residential="false")["index"] == "ETTV"
    with pytest.raises(ValueError, match="no ETTV_walls value"):
        codes.envelope_transfer([win], None, user_tables={"ETTV_walls": {"N": 0.8}})


def test_tag_script_checks_everything_first():
    s = rhino.tag_script({"0b6e3f1e-1111-2222-3333-444455556666": {"room": "Living"}}, unique_room="Living")
    assert "nothing was tagged" in s and 'uniqueRoom = "Living"' in s
    assert s.index("already exists") < s.index("BeginUndoRecord")
