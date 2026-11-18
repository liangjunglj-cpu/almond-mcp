"""The Environment panel's coursework workflow: climate, PMV set-points, thermal settings with charts,
view out, sunlight, shadow plans and kept cases compared, through the panel engine (almond-mcp environment)."""
from __future__ import annotations

import io
import json
import xml.dom.minidom

import numpy as np
import pytest

from almond_mcp.environment import panel, rooms as rm, studies, thermal
from tests.env_weather import synthetic_epw
from tests.test_rooms_constructions import _model


@pytest.fixture(scope="module")
def temperate(tmp_path_factory):
    return synthetic_epw(tmp_path_factory.mktemp("w") / "temperate.epw", latitude=47.0, longitude=8.0, time_zone=1.0,
                         mean_t=10.0, annual_amp=10.0, daily_amp=5.0, rh=70.0, cloudiness=0.5, city="Temperate")


@pytest.fixture(autouse=True)
def _runs_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv(studies.RUNS_ENV, str(tmp_path / "runs"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))


def _panel(req: dict) -> dict:
    out = io.StringIO()
    panel.main(io.StringIO(json.dumps(req)), out)
    reply = json.loads(out.getvalue())
    assert reply["status"] == "ok", reply.get("message")
    return reply


def _svg(s: str) -> None:
    assert s.startswith("<svg")
    xml.dom.minidom.parseString(s)


def _run(epw_path: str, study: str, **settings) -> dict:
    return _panel({"action": "run", "study": study, "export": _model(), "epw_path": epw_path, "settings": settings})


def test_climate_and_setpoints(temperate):
    c = _panel({"action": "climate", "epw_path": temperate.source_path})
    assert {"warmest_week", "coldest_week", "file_periods"} <= set(c["weeks"])
    _svg(c["svg"])
    assert c["files"]["csv"].endswith(".csv")
    sp = _panel({"action": "setpoints", "met": 1.2, "clo_heating": 1.0, "clo_cooling": 0.5, "category": "II"})["setpoints"]
    assert 18 < sp["heating_setpoint_c"] < sp["cooling_setpoint_c"] < 30
    out = io.StringIO()
    panel.main(io.StringIO(json.dumps({"action": "setpoints", "met": 9})), out)
    assert json.loads(out.getvalue())["status"] == "error"


def test_panel_thermal_settings_reach_the_rooms(temperate):
    """The panel's course-style inputs (people, fresh air per person, setbacks, seasons, all-room set-points,
    CSV) change the result, and the reply carries the week and balance charts."""
    base = _run(temperate.source_path, "thermal")
    brief = _run(temperate.source_path, "thermal", people_per_m2=0.11, metabolic_rate=1.2, ventilation_l_s_person=5.0,
                 ventilation_l_s_m2=1.0, heating_setpoint=21, cooling_setpoint=26, heating_setback=18,
                 heating_months=[11, 12, 1, 2, 3, 4], natural_ventilation_months=[5, 6, 7, 8, 9, 10],
                 natural_ventilation_ach=2.0, shading_on_above_w_m2=150, comfort_months=[5, 6, 7, 8, 9, 10],
                 export_csv=True, balance_room="Bed")
    b0 = {r["room"]: r["thermal"] for r in base["result"]["rooms"] if r.get("thermal")}
    b1 = {r["room"]: r["thermal"] for r in brief["result"]["rooms"] if r.get("thermal")}
    assert b1["Living"]["heating_kwh_m2"] != b0["Living"]["heating_kwh_m2"]
    assert b1["Living"]["adaptive_en16798_hours"]["months"] == [5, 6, 7, 8, 9, 10]
    assert brief["result"]["building"]["floor_area_m2"] > 0
    ch = brief["charts"]
    assert ch["room"] == "Bed" and "Living" in ch["rooms"]
    for key in ("warmest_week", "coldest_week", "balance_hottest_day", "balance_coldest_day"):
        _svg(ch[key])
    lit = _run(temperate.source_path, "thermal", lighting_control="stepped", lighting_target_lux=300, lighting_steps=3)
    assert "LIGHTING SAVED" in lit["tiles_svg"]
    assert all(r["thermal"]["lighting_control"]["mode"] == "stepped" for r in lit["result"]["rooms"] if r.get("thermal"))
    assert brief["csv_dir"] and any(r["thermal"].get("hourly_csv") for r in brief["result"]["rooms"] if r.get("thermal"))
    # another room's charts from the saved run, without simulating again
    again = _panel({"action": "charts", "run_id": brief["result"]["run_id"], "epw_path": temperate.source_path, "room": "Living"})
    assert again["charts"]["room"] == "Living"
    out = io.StringIO()
    panel.main(io.StringIO(json.dumps({"action": "run", "study": "thermal", "export": _model(), "epw_path": temperate.source_path,
                                       "settings": {"heating_setpoint": 27, "cooling_setpoint": 24}})), out)
    assert "below the cooling" in json.loads(out.getvalue())["message"]


def test_all_room_setpoints_keep_a_rooms_own_tag(temperate):
    data = _model()
    for o in data["objects"]:
        if o.get("room") == "Bed":
            o["room_heat_c"] = "16"
    res = studies.run_rooms_thermal(data, temperate, thermal.Settings(), setpoints={"heating_setpoint": 23.0})
    by = {r["room"]: r for r in res["rooms"]}
    assert by["Living"]["thermal"]["heating_kwh_m2"] > 0
    rooms, encs, scene, _ = studies.prepare_rooms(data)
    assert next(r for r in rooms if r.name == "Bed").setpoints == {"heating_setpoint": 16.0}
    # a semi-open room stays free-running whatever the all-room set-points say
    assert by["Loggia"]["method"].startswith("5R1C") and by["Loggia"]["thermal"]["heating_kwh_m2"] == 0


def test_people_per_m2_beats_the_room_use_default(temperate):
    from tests.test_course_tools import _box_zone
    z, sc = _box_zone()
    z.profile = dict(rm.ROOM_USES["office"])
    thermal.solar_on_surfaces([z], sc, temperate, 0.0)
    thermal.apply_construction(z, thermal.Settings())
    low = thermal.simulate(z, temperate, thermal.Settings(people_per_m2=0.01))
    high = thermal.simulate(z, temperate, thermal.Settings(people_per_m2=0.5))
    assert high["balance_w"]["people_w"].sum() > 10 * low["balance_w"]["people_w"].sum()


def test_view_out_sunlight_and_shadows_in_the_panel(temperate):
    v = _run(temperate.source_path, "view_out", view_height_m=1.2, spacing_m=0.8)
    rooms = {r["room"]: r for r in v["result"]["rooms"]}
    assert rooms["Living"]["minimum"] > 0 and v["draw"].startswith("Q,")
    _svg(v["svg"])
    s = _run(temperate.source_path, "sunlight", month=3, day=21, date_range=[[2, 1], [2, 20]])
    assert s["result"]["windows"] and "range" in s["result"]
    assert s["result"]["windows"][0]["sun_hours"] > 3          # the south window of a room drawn as a closed volume
    _svg(s["charts"]["sunlight"])
    sh = _run(temperate.source_path, "shadows", month=3, day=20, times=["09:00", "12:00", "15:00"])
    assert sh["image"].startswith("data:image/png;base64,") and len(sh["result"]["shots"]) == 3


def test_compare_kept_cases(temperate):
    a = _run(temperate.source_path, "thermal")
    b = _run(temperate.source_path, "thermal", natural_ventilation_ach=4.0, natural_ventilation_months=[5, 6, 7, 8, 9])
    cmp = _panel({"action": "compare", "epw_path": temperate.source_path, "room": "Living",
                  "cases": [{"name": "ID0", "run_id": a["result"]["run_id"]}, {"name": "ID1 vent", "run_id": b["result"]["run_id"]}]})
    assert [r["case"] for r in cmp["rows"]] == ["ID0", "ID1 vent"] and cmp["study"] == "rooms_thermal"
    for key in ("heating_kwh_m2", "hours_above_26c"):
        _svg(cmp["bars"][key])
    _svg(cmp["warmest_week"])
    v = _run(temperate.source_path, "view_out", spacing_m=1.0)
    out = io.StringIO()
    panel.main(io.StringIO(json.dumps({"action": "compare", "cases": [{"name": "a", "run_id": a["result"]["run_id"]},
                                                                      {"name": "v", "run_id": v["result"]["run_id"]}]})), out)
    assert "one study type" in json.loads(out.getvalue())["message"]
    assert np.isfinite([r.get("heating_kwh_m2", 0) for r in cmp["rows"]]).all()


def test_panel_routes_every_action_the_page_sends():
    """The Rhino panel only forwards /almond-action/<session>/environment/<action> for actions on its
    allow-list. An action the page sends but the list lacks is dropped silently and the page stays busy
    (climate, setpoints, charts, compare and open_folder were missing)."""
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    js = (root / "almond_mcp/library_ui/environment.js").read_text(encoding="utf-8")
    html = (root / "almond_mcp/library_ui/index.html").read_text(encoding="utf-8")
    cs_panel = (root / "RhinoAlmondBridge/LibraryPanel.cs").read_text(encoding="utf-8")
    cs_ws = (root / "RhinoAlmondBridge/EnvironmentWorkspace.cs").read_text(encoding="utf-8")
    allowed = set(re.search(r'/environment/\(([a-z_|]+)\)\$', cs_panel).group(1).split("|"))
    handled = set(re.findall(r'case "([a-z_]+)":', cs_ws))
    local = {"keep", "clear_cases", "shadows"}                    # handled in the page (shadows sends "run")
    sent = set(re.findall(r"request\('([a-z_]+)'", js)) | (set(re.findall(r'data-env="([a-z_]+)"', html)) - local)
    assert sent <= allowed, f"page actions the panel drops: {sorted(sent - allowed)}"
    assert allowed <= handled, f"allowed actions the workspace does not handle: {sorted(allowed - handled)}"
