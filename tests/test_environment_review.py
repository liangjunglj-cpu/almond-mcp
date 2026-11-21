"""Regression tests for the environmental-analysis code review (2026-11-03): layer-name rules that
matched inside words, the TM52 season in the southern hemisphere, ground floors of upper zones,
the window tolerance message, shoebox material overrides, and background-job docs."""
from pathlib import Path

import numpy as np
import pytest

from almond_mcp.environment import comfort, epw, scene as S, studies, thermal
from tests.env_weather import synthetic_epw
from tests.test_capsules import _call, _load_server


@pytest.fixture(autouse=True)
def _runs_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv(studies.RUNS_ENV, str(tmp_path / "runs"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))


@pytest.fixture(scope="module")
def temperate(tmp_path_factory):
    return synthetic_epw(tmp_path_factory.mktemp("w") / "temperate.epw", latitude=40.0, longitude=-75.0, time_zone=-5.0,
                         mean_t=12.0, annual_amp=12.0, daily_amp=5.0, rh=65.0, cloudiness=0.5, city="Temperate")


# ── 1. layer-name classification ─────────────────────────────────────────────

LOWE, TRIPLE = "glazing_double_lowe", "glazing_triple_lowe"


@pytest.mark.parametrize("layer,expected", [
    # matched inside a longer word before the fix
    ("Lower floor", "floor"),
    ("Lower ground", "ground"),
    ("Flower beds", None),
    ("Slab below entrance", "floor"),
    ("Glowering", None),
    ("Whole building", None),
    ("WholeBuilding", None),
    ("Composite wall", "wall"),
    ("Opposite block", None),
    ("Website", None),
    ("Wall finish", "wall"),
    ("Final scheme", None),
    ("Fine gravel", None),
    ("Shadow study", None),
    ("Background", None),
    ("Underground parking::Walls", "wall"),
    ("Fibreglass panel", None),
    ("Vegetable garden", None),
    ("Triple height atrium", None),
    # a parent layer counts only when the object's own names match nothing
    ("Lower Level::Floor", "floor"),
    ("Lower Level::Walls", "wall"),
    ("Lower Level::Misc", None),
    ("Ground Floor::Walls", "wall"),
    ("Whole building::Walls", "wall"),
    ("Curtain wall::Spandrel panels", "wall"),
    ("Glazing::South", LOWE),
    ("Building::Shading::East", "shading"),
    ("Ignore::Glazing", "ignore"),                 # an ignore parent still excludes everything under it
    ("Annotations::Site::Walls", "ignore"),
    # legitimate matches that must survive
    ("LowE", LOWE),
    ("low-e glazing", LOWE),
    ("Low E", LOWE),
    ("LOW_E", LOWE),
    ("Glazing::LowE_South", LOWE),
    ("LowEGlass", LOWE),
    ("Low-emissivity glass", LOWE),
    ("Triple glazing", TRIPLE),
    ("Triple-glazed low-e", TRIPLE),
    ("TripleGlazing", TRIPLE),
    ("glazing_triple_lowe", TRIPLE),
    ("Tinted glass", "glazing_tinted"),
    ("Fins", "shading"),
    ("fin_01", "shading"),
    ("Vertical fin", "shading"),
    ("Sunshades", "shading"),
    ("Shading", "shading"),
    ("Louvres", "shading"),
    ("site_terrain", "ground"),
    ("Site", "ground"),
    ("Site::Context", "context"),
    ("Topography", "ground"),
    ("Holes", "opening"),
    ("hole_01", "opening"),
    ("Void", "opening"),
    ("Openings", "opening"),
    ("Window_frame", "frame"),
    ("Windowsill", "frame"),
    ("Glass", LOWE),
    ("Tables", "furniture"),
    ("Armchair", "furniture"),
    ("Sensors", "ignore"),
    ("Grid_A", "ignore"),
])
def test_layer_names_match_whole_words(layer, expected):
    assert S.classify([layer, "", ""])[0] == expected


def test_parent_layer_reason_names_the_parent():
    mat, reason = S.classify(["Glazing::South", "", ""])
    assert mat == LOWE and "parent layer 'Glazing'" in reason
    mat, reason = S.classify(["Lower Level::Floor", "", ""])
    assert mat == "floor" and "parent" not in reason


def test_object_name_and_render_material_still_count():
    assert S.classify(["Lower Level", "Pane 3", "Glass_clear"])[0] == LOWE
    assert S.classify(["Lower Level", "Oak window sill", ""])[0] == "frame"
    assert S.classify(["Lower Level", "", ""], transparency=0.5)[0] == LOWE


def test_listed_rules_are_the_rules_used():
    """list_environment_materials shows _RULES; each must compile and match on normalised text."""
    for pattern, _ in S._RULES:
        S.re.compile(pattern)
    assert S._normalise("LowE_Glass::Site-Terrain") == "low e glass site terrain"


# ── 2. TM52 season ───────────────────────────────────────────────────────────

def _month():
    return np.repeat(np.repeat(np.arange(1, 13), epw.MONTH_DAYS), 24)


def test_tm52_season_follows_the_hemisphere():
    month, occ, t_rm = _month(), np.ones(8760, dtype=bool), np.full(365, 20.0)
    hot_jan = np.full(8760, 26.0)
    hot_jan[month == 1] = 31.0
    north = comfort.tm52(hot_jan, t_rm, occ, month, latitude=51.5)
    south = comfort.tm52(hot_jan, t_rm, occ, month, latitude=-33.9)
    assert north["pass"] and north["season_months"] == [5, 6, 7, 8, 9]
    assert not south["pass"] and south["season_months"] == [11, 12, 1, 2, 3]
    assert "southern" in south["season"]
    hot_jul = np.full(8760, 26.0)
    hot_jul[month == 7] = 31.0
    assert comfort.tm52(hot_jul, t_rm, occ, month, latitude=-33.9)["pass"]
    assert not comfort.tm52(hot_jul, t_rm, occ, month, latitude=51.5)["pass"]


def test_tm52_season_can_be_given():
    month, occ, t_rm = _month(), np.ones(8760, dtype=bool), np.full(365, 20.0)
    hot = np.full(8760, 26.0)
    hot[month == 2] = 31.0
    r = comfort.tm52(hot, t_rm, occ, month, latitude=51.5, season_months=[1, 2, 3])
    assert not r["pass"] and r["season_months"] == [1, 2, 3]
    with pytest.raises(ValueError):
        comfort.tm52(hot, t_rm, occ, month, season_months=[0, 13])
    with pytest.raises(ValueError, match="tm52_months"):
        thermal.Settings(tm52_months=[13]).validate()


def test_thermal_summary_uses_site_latitude(tmp_path):
    south = synthetic_epw(tmp_path / "south.epw", latitude=-33.9, longitude=151.2, time_zone=10.0, mean_t=18.0,
                          annual_amp=6.0, city="South")
    box = S.Shoebox()
    sc = box.build()
    z = thermal.zone_from_shoebox(box, sc, S.LIBRARY[box.glazing])
    free = thermal.Settings(heating_setpoint=None, cooling_setpoint=None)
    r = studies.run_thermal([z], sc, south, free)
    assert r["zones"][0]["tm52"]["season_months"] == [11, 12, 1, 2, 3]
    free.tm52_months = [12, 1, 2]
    r = studies.run_thermal([z], sc, south, free)
    assert r["zones"][0]["tm52"]["season_months"] == [12, 1, 2]


# ── 3. ground floors of zones from an export ─────────────────────────────────

def _box(x0, y0, z0, x1, y1, z1):
    v = np.array([[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0], [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]], float)
    f = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]])
    return v, f


def _obj(guid, layer, v, f, name=""):
    return {"guid": guid, "layer": layer, "name": name, "material": "", "transparency": 0.0, "env_material": "",
            "vertices": v.reshape(-1).tolist(), "faces": f.reshape(-1).tolist()}


def _export(*objs):
    return {"units_to_m": 1.0, "objects": list(objs)}


LO = _obj("lo", "Analysis::Zones", *_box(0, 0, 0, 4, 5, 3))
UP = _obj("up", "Analysis::Zones", *_box(0, 0, 3, 4, 5, 6))
# terrain below the building, on a slope: lower than the ground slab at one end
TERRAIN = _obj("t", "Site::Terrain", np.array([[-20, -20, -2], [20, -20, -2], [20, 20, 0], [-20, 20, 0]], float),
               np.array([[0, 1, 2], [0, 2, 3]]))


def _zones(data, guids, **kw):
    return {z.source["guid"]: z for z in studies.zones_from_export(data, S.scene_from_export(data), guids, **kw)}


def test_upper_zone_alone_is_not_on_the_ground():
    data = _export(LO, UP, TERRAIN)
    up = _zones(data, ["up"])["up"]
    a = up.areas()
    assert "ground_floor" not in a and a["exposed_floor"] == pytest.approx(20)
    assert "exposed to outside air" in up.source["note"]
    both = _zones(data, ["lo", "up"])
    assert both["lo"].areas()["ground_floor"] == pytest.approx(20)
    assert "ground_floor" not in both["up"].areas() and both["up"].areas()["adiabatic"] == pytest.approx(20)
    lo = _zones(data, ["lo"])["lo"]
    assert lo.areas()["ground_floor"] == pytest.approx(20)       # terrain is not a storey below


def test_perimeter_foundations_do_not_lift_the_ground():
    footing = _obj("fw", "Structure::Foundation walls", *_box(-0.3, -0.3, -1.2, 4.3, 0.0, 0.0))
    lo = _zones(_export(LO, footing), ["lo"])["lo"]
    assert lo.areas()["ground_floor"] == pytest.approx(20)


def test_ground_z_can_be_given():
    only_up = _export(UP)
    assert _zones(only_up, ["up"])["up"].areas()["ground_floor"] == pytest.approx(20)   # nothing says otherwise
    up = _zones(only_up, ["up"], ground_z=0.0)["up"]
    assert "ground_floor" not in up.areas() and up.source["ground_z_m"] == 0.0


# ── 4. window tolerance message ──────────────────────────────────────────────

def test_window_tolerance_message_matches_the_tolerance(temperate):
    def pane(y):
        return {"vertices": [[1, y, 1], [3, y, 1], [3, y, 2], [1, y, 2]], "triangles": [[0, 1, 2], [0, 2, 3]],
                "name": "w", "g_value": 0.4, "u_value": 1.4}
    v, f = _box(0, 0, 0, 4, 5, 3)
    near = thermal.zone_from_mesh("near", v, f, [pane(-0.2)])
    assert near.areas().get("window") == pytest.approx(2.0)
    far = thermal.zone_from_mesh("far", v, f, [pane(-0.5)])
    assert "window" not in far.areas() and far.source["window_tolerance_m"] == pytest.approx(0.3)
    r = studies.run_thermal([far], _empty_scene(), temperate, thermal.Settings())
    note = [n for n in r["notes"] if "none of the glazing" in n][0]
    assert "within 30 cm" in note and "5 cm" not in note


def _empty_scene():
    b = S.SceneBuilder()
    b.add_quad([[1000, 1000, -50], [1001, 1000, -50], [1001, 1001, -50], [1000, 1001, -50]], "black", {"name": "far"})
    return b.build()


# ── 5. shoebox material overrides ────────────────────────────────────────────

@pytest.fixture()
def server(monkeypatch, tmp_path):
    caps = tmp_path / "capsules"
    caps.mkdir()
    s = _load_server(monkeypatch, tmp_path, caps)
    monkeypatch.setattr(s, "_send_and_receive", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no bridge")))
    return s


def test_radiation_shoebox_uses_materials(server, temperate):
    r = _call(server.analyze_solar_radiation, epw_path=temperate.source_path, shoebox={"orientation": 180},
              grid_spacing_m=1.5, materials={"wall": {"reflectance": 0.8}})
    assert r["status"] == "success", r
    walls = [m for m in r["scene"]["materials"] if m["material"] == "wall"]
    assert walls and walls[0]["reflectance"] == 0.8


def test_thermal_shoebox_uses_glazing_override(server, temperate):
    base = _call(server.analyze_thermal, epw_path=temperate.source_path, shoebox={"orientation": 180})
    low_g = _call(server.analyze_thermal, epw_path=temperate.source_path, shoebox={"orientation": 180},
                  materials={"glazing_double_lowe": {"base": "glazing_double_lowe", "g_value": 0.2}})
    assert base["status"] == low_g["status"] == "success"
    assert low_g["zones"][0]["solar_gain_kwh_m2"] < 0.7 * base["zones"][0]["solar_gain_kwh_m2"]


# ── 6. background jobs ───────────────────────────────────────────────────────

def test_docs_do_not_promise_job_progress():
    doc = (Path(__file__).resolve().parents[1] / "docs" / "environmental-analysis.md").read_text(encoding="utf-8")
    assert "reports progress" not in doc and "memory" in doc
