"""Course-workflow tools: extreme weeks and diurnal averages, shadow plans, brief-style thermal inputs, the
hourly energy balance and case comparisons, PMV set-points, adaptive hour counts, EN 17037 view out and
sunlight, daylight probes and the report charts."""
from __future__ import annotations

import csv
import xml.dom.minidom

import numpy as np
import pytest

from almond_mcp.environment import (cases, charts, climate, comfort, en17037, epw, rhino, scene as S, shadows, solar,
                                    studies, thermal)
from tests.env_weather import synthetic_epw
from tests.test_capsules import _call, _load_server

BOX = {"width": 3.6, "depth": 4.8, "height": 3.0, "orientation": 180, "wwr": 0.3, "sill": 0.9, "overhang": 0.5}


@pytest.fixture(scope="module")
def temperate(tmp_path_factory):
    return synthetic_epw(tmp_path_factory.mktemp("w") / "temperate.epw", latitude=47.0, longitude=8.0, time_zone=1.0,
                         mean_t=10.0, annual_amp=10.0, daily_amp=5.0, rh=70.0, cloudiness=0.5, city="Temperate")


@pytest.fixture(autouse=True)
def _runs_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv(studies.RUNS_ENV, str(tmp_path / "runs"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))


@pytest.fixture()
def server(monkeypatch, tmp_path):
    caps = tmp_path / "capsules"
    caps.mkdir()
    return _load_server(monkeypatch, tmp_path, caps)


def _box_zone(spec=None, **st):
    box = studies.shoebox_from_spec({**BOX, **(spec or {})})
    sc = box.build()
    z = thermal.zone_from_shoebox(box, sc, S.LIBRARY[box.glazing])
    return z, sc


def _simulate(weather, spec=None, **kw):
    z, sc = _box_zone(spec)
    st = thermal.Settings(**kw)
    thermal.solar_on_surfaces([z], sc, weather, 0.0)
    thermal.apply_construction(z, st)
    return z, st, thermal.simulate(z, weather, st)


# ── climate ──────────────────────────────────────────────────────────────────

def test_extreme_weeks_and_file_periods(temperate):
    ext = climate.extreme_weeks(temperate)
    t = temperate["dry_bulb"].reshape(365, 24).mean(axis=1)
    roll = np.convolve(t, np.ones(7) / 7, mode="valid")
    assert ext["warmest_week"]["start_day_of_year"] == int(np.argmax(roll)) + 1
    assert ext["coldest_week"]["start_day_of_year"] == int(np.argmin(roll)) + 1
    hot = ext["warmest_week"]["hottest_day"]
    k = ext["warmest_week"]["start_day_of_year"] - 1
    assert hot["day_of_year"] - 1 == k + int(np.argmax(temperate["dry_bulb"].reshape(365, 24)[k:k + 7].max(axis=1)))
    # an EPW 'week' across the year end is 15 days, and is flagged
    assert climate._period_days("12/22", "1/ 5") == 15 and climate._period_days("8/ 3", "8/ 9") == 7
    temperate.typical_periods = [{"name": "Winter - Week Nearest Min Temperature For Period", "type": "Extreme",
                                  "start": "12/22", "end": "1/ 5"}]
    p = climate.extreme_weeks(temperate)["file_periods"][0]
    assert p["days"] == 15 and "15 days" in p["note"]
    temperate.typical_periods = []


def test_diurnal_averages_and_chart(temperate, tmp_path):
    d = climate.diurnal_averages(temperate)
    assert len(d["months"]) == 12 and all(len(m[k]) == 24 for m in d["months"] for k in ("dry_bulb", "wet_bulb", "ghi", "dhi", "dni"))
    jul = d["months"][6]
    sel = (temperate.month == 7) & (temperate.hour_of_day == 13)
    assert jul["dry_bulb"][13] == pytest.approx(float(temperate["dry_bulb"][sel].mean()), abs=0.051)
    assert all(w <= t + 1e-6 for w, t in zip(jul["wet_bulb"], jul["dry_bulb"]))
    assert max(jul["ghi"][:4]) == 0 and max(jul["ghi"]) > 200
    out = studies.climate_charts(temperate)
    for k in ("png", "svg", "csv"):
        assert out["files"][k] and __import__("pathlib").Path(out["files"][k]).is_file()
    xml.dom.minidom.parse(out["files"]["svg"])
    rows = list(csv.reader(open(out["files"]["csv"], encoding="utf-8")))
    assert rows[0][:3] == ["month", "hour_ending", "dry_bulb_C"] and len(rows) == 1 + 12 * 24


# ── shadows ──────────────────────────────────────────────────────────────────

def test_shadow_plan_falls_away_from_the_sun():
    box = S.Shoebox(width=6, depth=6, height=6, ground=True)
    sc = box.build().clean()
    sun = solar.direction_vector(30.0, 180.0)                     # from the south
    img, info = shadows.shadow_plan(sc, sun, pixels=200)
    shade = np.all(img == shadows.SHADE_GROUND, axis=2)
    top = np.all(img == shadows.LIT_TOP, axis=2) | np.all(img == shadows.SHADE_TOP, axis=2)
    assert shade.any() and top.any() and info["shadow_share_of_ground_pct"] > 0
    rows = np.flatnonzero(shade.any(axis=1))
    assert rows.mean() < np.flatnonzero(top.any(axis=1)).mean()      # image rows run north to south: shadow to the north
    # longer shadow at a lower sun
    img2, _ = shadows.shadow_plan(sc, solar.direction_vector(15.0, 180.0), pixels=200,
                                  extent=shadows.extent_for(sc, [solar.direction_vector(15.0, 180.0)]))
    assert np.all(img2 == shadows.SHADE_GROUND, axis=2).sum() > 0


def test_sun_views_script_checks_its_inputs(tmp_path):
    s = rhino.sun_views_script([(20.0, 135.0, str(tmp_path / "a.png"))], "Perspective", 800, 500)
    assert "135.000000" in s and "Perspective" in s and "sun.ManualControl = manual" in s
    with pytest.raises(ValueError):
        rhino.sun_views_script([(20.0, 135.0, str(tmp_path / "a.png"))], 'Persp"; x', 800, 500)
    with pytest.raises(ValueError):
        rhino.sun_views_script([], "", 800, 500)


# ── thermal inputs, balance, cases ──────────────────────────────────────────

def test_energy_balance_closes_every_hour(temperate):
    z, st, res = _simulate(temperate, heating_setpoint=21, cooling_setpoint=26, natural_ventilation_ach=3.0,
                           heat_recovery=0.6, shading_g_factor=0.3)
    total = sum(res["balance_w"].values())
    assert np.abs(total).max() < 1e-3
    s = thermal.summarize(z, res, temperate, st)
    assert s["energy_balance_closure_w"] < 1e-3
    assert s["energy_balance_kwh_m2"]["heating"]["gains"] == pytest.approx(s["heating_kwh_m2"], abs=0.05)
    assert s["lighting_kwh_m2"] > 0


def test_brief_style_gains_ventilation_and_setbacks(temperate):
    _, _, base = _simulate(temperate, heating_setpoint=21, cooling_setpoint=None)
    _, st, setb = _simulate(temperate, heating_setpoint=21, cooling_setpoint=None, heating_setback=18)
    unocc = ~setb["occupied"]
    assert base["heating_w"][unocc].sum() == 0 and setb["heating_w"][unocc].sum() > 0
    assert setb["t_air"][unocc].min() >= 18 - 0.05
    z, st, ppl = _simulate(temperate, people_per_m2=0.11, metabolic_rate=1.2, ventilation_l_s_person=5.0,
                           ventilation_l_s_m2=1.0)
    assert ppl["model"]["people_w_m2_at_full_occupancy"] == pytest.approx(0.11 * 1.2 * 58.15 * 1.8 * 0.6, abs=0.01)
    assert ppl["model"]["ventilation_l_s_m2_occupied"] == pytest.approx(0.11 * 5 + 1.0, abs=1e-3)
    _, _, season = _simulate(temperate, heating_setpoint=21, cooling_setpoint=None, heating_months=[11, 12, 1, 2, 3, 4])
    summer = np.isin(temperate.month, [5, 6, 7, 8, 9, 10])
    assert season["heating_w"][summer].sum() == 0 and season["heating_w"][~summer].sum() > 0
    _, _, nv = _simulate(temperate, heating_setpoint=None, cooling_setpoint=None, natural_ventilation_ach=4.0,
                         natural_ventilation_months=[6, 7, 8])
    assert nv["natural_ventilation"][~np.isin(temperate.month, [6, 7, 8])].sum() == 0


def test_custom_schedule_and_validation(temperate):
    day = [0.0] * 8 + [1.0] * 10 + [0.0] * 6
    _, _, r = _simulate(temperate, custom_schedule={"occupancy": {"weekday": day, "weekend": [0.0] * 24}})
    wk = temperate.weekday() < 5
    assert r["occupancy"][wk & (temperate.hour_of_day == 9)].min() == 1.0
    assert r["occupancy"][~wk].max() == 0.0
    bad = [dict(custom_schedule={"occupancy": {"weekday": [1] * 23}}), dict(custom_schedule={"heat": {"weekday": day}}),
           dict(heating_months=[13]), dict(ventilation_l_s_person=5.0), dict(heating_setback=22, cooling_setback=20),
           dict(ventilation_ach=1.0, ventilation_l_s_person=5.0, people_per_m2=0.1)]
    for kw in bad:
        with pytest.raises(ValueError):
            thermal.Settings(**kw).validate()


def test_adaptive_hours_count_the_season(temperate):
    z, st, res = _simulate(temperate, heating_setpoint=None, cooling_setpoint=None, comfort_months=[5, 6, 7, 8, 9, 10])
    h = thermal.summarize(z, res, temperate, st)["adaptive_en16798_hours"]
    season = res["occupied"] & np.isin(temperate.month, [5, 6, 7, 8, 9, 10])
    assert h["occupied_hours"] == int(season.sum())
    for cat in ("I", "II", "III"):
        assert h[cat]["too_warm_h"] + h[cat]["too_cool_h"] + h[cat]["comfortable_h"] == h["occupied_hours"]
    assert h["I"]["comfortable_h"] <= h["II"]["comfortable_h"] <= h["III"]["comfortable_h"]


def test_thermal_cases_compare_and_write_files(temperate, tmp_path):
    base = {"shoebox": BOX, "settings": {"heating_setpoint": 21, "heating_setback": 18, "cooling_setpoint": 26,
                                         "people_per_m2": 0.11, "ventilation_l_s_person": 5, "ventilation_l_s_m2": 1}}
    cs = [{"id": "A"}, {"id": "B", "settings": {"free_running": True}}, {"id": "C", "shoebox": {"wwr": 0.7, "overhang": 0}}]

    def make(m):
        box = studies.shoebox_from_spec(m["shoebox"])
        sc = box.build()
        return [thermal.zone_from_shoebox(box, sc, S.LIBRARY[box.glazing])], sc
    out = cases.run_thermal_cases(temperate, base, cs, make, tmp_path / "cases", balance_case="A")
    rows = {r["id"]: r for r in out["cases"]}
    assert rows["B"]["heating_kwh_m2"] == 0 and rows["A"]["heating_kwh_m2"] > 0
    assert rows["C"]["cooling_kwh_m2"] > rows["A"]["cooling_kwh_m2"]
    assert rows["C"]["shoebox_changed"] == {"wwr": 0.7, "overhang": 0}
    hdr = next(csv.reader(open(out["files"]["cases"]["A"], encoding="utf-8")))
    assert {"operative_temperature_c", "outdoor_dry_bulb_c", "heating_w", "thermal_mass_w", "window_solar_w"} <= set(hdr)
    allc = list(csv.reader(open(out["files"]["operative_all_cases_csv"], encoding="utf-8")))
    assert allc[0] == ["month", "day", "hour_ending", "outdoor_dry_bulb_c", "operative_A_c", "operative_B_c", "operative_C_c"]
    assert len(allc) == 8761
    for k in ("warmest_week", "coldest_week", "balance_hottest_day", "balance_coldest_day"):
        xml.dom.minidom.parse(out["files"][k]["svg"])
    day = list(csv.reader(open(out["files"]["balance_coldest_day_csv"], encoding="utf-8")))
    assert len(day) == 25 and "heating_kwh_m2" in day[0]
    with pytest.raises(ValueError):
        cases.settings_from({"heating_setpont": 20})
    with pytest.raises(ValueError):
        cases.run_thermal_cases(temperate, base, [{"id": "A"}, {"id": "A"}], make, tmp_path / "dup")


def test_compare_thermal_cases_tool_without_rhino(server, temperate, monkeypatch):
    monkeypatch.setattr(server, "_send_and_receive", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no Rhino")))
    r = _call(server.compare_thermal_cases, epw_path=temperate.source_path,
              base={"shoebox": BOX, "settings": {"heating_setpoint": 20}},
              cases=[{"id": "ID0"}, {"id": "ID1", "settings": {"free_running": True}}])
    assert r["status"] == "success" and [c["id"] for c in r["cases"]] == ["ID0", "ID1"]
    bad = _call(server.compare_thermal_cases, epw_path=temperate.source_path, base={"shoebox": BOX},
                cases=[{"id": "X", "setting": {}}])
    assert bad["status"] == "error"


def test_building_totals_are_area_weighted():
    tot = studies.building_totals([{"floor_area_m2": 10, "heating_kwh_m2": 50, "cooling_kwh_m2": 0, "lighting_kwh_m2": 10},
                                   {"floor_area_m2": 30, "heating_kwh_m2": 10, "cooling_kwh_m2": 4, "lighting_kwh_m2": 2}])
    assert tot["floor_area_m2"] == 40 and tot["heating_kwh_m2"] == 20.0 and tot["lighting_kwh_m2"] == 4.0
    assert tot["cooling_kwh_m2"] == 3.0


# ── comfort ──────────────────────────────────────────────────────────────────

def test_pmv_setpoints_sit_on_the_category_limits():
    s = comfort.pmv_setpoints(1.2, 1.0, 0.5, 50, 0.1, "II")
    assert s["heating_setpoint_c"] < s["cooling_setpoint_c"]
    for t, clo, lim in ((s["heating_setpoint_c"], 1.0, -0.5), (s["cooling_setpoint_c"], 0.5, 0.5)):
        assert float(comfort.pmv_ppd(t, t, 0.1, 50, 1.2, clo)["pmv"]) == pytest.approx(lim, abs=0.03)
    tighter = comfort.pmv_setpoints(1.2, 1.0, 0.5, 50, 0.1, "I")
    assert tighter["heating_setpoint_c"] > s["heating_setpoint_c"] and tighter["cooling_setpoint_c"] < s["cooling_setpoint_c"]
    sleeping = comfort.pmv_setpoints(0.8, 2.0, 1.0, 50, 0.1, "II")
    assert sleeping["heating_setpoint_c"] != s["heating_setpoint_c"]
    with pytest.raises(ValueError):
        comfort.pmv_setpoints(1.2, category="V")


# ── EN 17037 and daylight probes ─────────────────────────────────────────────

def test_view_out_and_sunlight_see_the_obstruction(temperate):
    open_box = S.Shoebox(**{**BOX, "wwr": 0.35})
    blocked = S.Shoebox(**{**BOX, "wwr": 0.35, "obstruction_height": 20, "obstruction_distance": 10})
    res = {}
    for name, box in (("open", open_box), ("blocked", blocked)):
        sc = box.build()
        grid = box.floor_grid(sc, 0.8, 1.2, 0.5)
        v = en17037.view_out(sc, grid.points, step_deg=2.0)
        res[name] = (v, en17037.view_summary(v, grid.cell_area))
        wins = en17037.window_reference_points(sc)
        assert len(wins) == 1
        p, n = wins[0]["point"], wins[0]["outward_normal"]
        assert n[1] < -0.9 and p[1] > 0                              # facade faces -Y (south); the point is inside
        loc = temperate.location
        h = en17037.sunlight_hours(sc, p[None], n[None], loc.latitude, loc.longitude, loc.time_zone, 0.0, 80, 10.0)
        res[name] += (float(h[0]),)
    vo, so, ho = res["open"]
    vb, sb, hb = res["blocked"]
    assert so["layers_seen_pct"]["sky"] > 0 and sb["layers_seen_pct"]["sky"] == 0
    assert np.allclose(vo["sight_angle_deg"], vb["sight_angle_deg"])
    assert sb["outside_distance_m_median"] == pytest.approx(10.0, abs=1.5)
    assert sb["area_at_least_pct"]["medium"] <= so["area_at_least_pct"]["medium"]
    assert ho > 4.0 and hb < ho and en17037.sunlight_level(ho) == "high"
    assert en17037.sunlight_level(1.4) == "none" and en17037.sunlight_level(1.5) == "minimum"


def test_en17037_and_daylight_case_tools(server, temperate, monkeypatch):
    monkeypatch.setattr(server, "_send_and_receive", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no Rhino")))
    v = _call(server.en17037_view_out, shoebox=BOX, grid_spacing_m=0.8)
    assert v["status"] == "success" and "view_level" in v["display_metrics"] and v["images"]
    s = _call(server.en17037_sunlight, epw_path=temperate.source_path, shoebox=BOX, date_range=[[2, 1], [3, 21]])
    assert s["status"] == "success" and len(s["range"]["per_day"]) == 49 and s["files"]["chart"]["png"]
    d = _call(server.analyze_daylight, epw_path=temperate.source_path, study="daylight_factor", shoebox=BOX, quality="draft",
              grid_spacing_m=0.6, probe_distance_from_window_m=2.0)
    p = d["probes"][0]
    assert d["status"] == "success" and p["offset_m"] < 0.5 and p["df"] > 0
    c = _call(server.compare_daylight_cases, epw_path=temperate.source_path, base={"shoebox": BOX}, quality="draft",
              cases=[{"id": "A"}, {"id": "B", "static_shade_transmittance": 0.2}], view_out=False, grid_spacing_m=0.8)
    assert c["status"] == "success"
    a, b = c["cases"]
    assert b["mean_df_pct"] < a["mean_df_pct"] * 0.5 and b["sda_pct"] <= a["sda_pct"]


def test_probe_values_pick_the_nearest_sensor():
    g = S.grid_from_points(np.array([[0.0, 0.0, 0.8], [1.0, 0.0, 0.8], [2.0, 0.0, 0.8]]))
    out = studies.probe_values(g, {"da": np.array([0.1, 0.5, 0.9]), "lux": np.array([100.0, 200.0, 300.0])}, [[1.2, 0.1]])
    assert out[0]["sensor"][0] == 1.0 and out[0]["da"] == 50.0 and out[0]["lux"] == 200.0
    with pytest.raises(ValueError):
        studies.probe_values(g, {}, [[1.0]])


# ── charts ───────────────────────────────────────────────────────────────────

def test_chart_labels_follow_the_tick_spacing():
    labels = lambda lo, hi: [charts._fmt(v, t[1] - t[0]) for t in [charts._ticks(lo, hi)] for v in t]
    assert labels(0, 108) == ["0", "25", "50", "75", "100"]
    assert "0.025" in labels(-0.06, 0.05) and "0" in labels(-0.06, 0.05)
    assert labels(0, 2.4) == ["0", "0.5", "1.0", "1.5", "2.0"]
    c = charts.stacked_bars(["1", "2"], [{"label": "a", "values": [1, -2], "colour": charts.RED}], "t", "u")
    xml.dom.minidom.parseString(c.svg())
