"""Daylight-linked lighting control (environment/lighting.py) in the thermal model."""
from __future__ import annotations

import numpy as np
import pytest

from almond_mcp.environment import lighting, scene as S, studies, thermal
from tests.env_weather import synthetic_epw
from tests.test_rooms_constructions import _model

BOX = {"width": 3.6, "depth": 4.8, "height": 3.0, "orientation": 180, "wwr": 0.4, "sill": 0.9}


@pytest.fixture(scope="module")
def temperate(tmp_path_factory):
    return synthetic_epw(tmp_path_factory.mktemp("w") / "temperate.epw", latitude=47.0, longitude=8.0, time_zone=1.0,
                         mean_t=10.0, annual_amp=10.0, daily_amp=5.0, rh=70.0, cloudiness=0.5, city="Temperate")


@pytest.fixture(autouse=True)
def _runs_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv(studies.RUNS_ENV, str(tmp_path / "runs"))


def test_power_fraction_by_hand():
    E = np.array([0.0, 150.0, 299.0, 300.0, 1000.0])
    cont = lighting.power_fraction(E, 300, "continuous", min_power=0.1)
    assert cont == pytest.approx([1.0, 0.1 + 0.9 * 0.5, 0.1 + 0.9 / 300, 0.0, 0.0])
    step = lighting.power_fraction(E, 300, "stepped", steps=3)
    assert step == pytest.approx([1.0, 2 / 3, 1 / 3, 0.0, 0.0])
    assert lighting.power_fraction(E, 300, "on_off").tolist() == [1.0, 1.0, 1.0, 0.0, 0.0]
    with pytest.raises(ValueError, match="lighting control"):
        lighting.power_fraction(E, 300, "dim")


def _run(weather, wwr=0.4, **st):
    box = studies.shoebox_from_spec({**BOX, "wwr": wwr})
    sc = box.build()
    z = thermal.zone_from_shoebox(box, sc, S.LIBRARY[box.glazing])
    return studies.run_thermal([z], sc, weather, thermal.Settings(schedule="office", **st))["zones"][0]


def test_shoebox_lighting_saving_and_balance(temperate):
    base = _run(temperate)
    dim = _run(temperate, lighting_control="continuous")
    lc = dim["lighting_control"]
    assert "lighting_control" not in base
    assert lc["lighting_kwh_m2_without_control"] == pytest.approx(base["lighting_kwh_m2"], abs=0.05)
    assert 0 < dim["lighting_kwh_m2"] < base["lighting_kwh_m2"] and 0 < lc["saving_pct"] < 100
    assert 0 < lc["daylight_meets_target_pct"] < 100 and lc["control_points"] > 4
    # less electric light is less internal gain: more heating, less cooling, and the balance still closes
    assert dim["heating_kwh_m2"] >= base["heating_kwh_m2"] and dim["cooling_kwh_m2"] <= base["cooling_kwh_m2"]
    assert dim["energy_balance_closure_w"] < 1.0
    onoff = _run(temperate, lighting_control="on_off")
    step = _run(temperate, lighting_control="stepped", lighting_steps=3)
    # on/off saves only when daylight alone meets the target, so it saves least
    assert onoff["lighting_kwh_m2"] >= step["lighting_kwh_m2"] >= dim["lighting_kwh_m2"] - 0.2


def test_a_bigger_window_saves_more(temperate):
    small = _run(temperate, wwr=0.15, lighting_control="continuous")
    big = _run(temperate, wwr=0.7, lighting_control="continuous")
    assert big["lighting_control"]["saving_pct"] > small["lighting_control"]["saving_pct"] + 5


def test_rooms_get_lighting_control(temperate):
    res = studies.run_rooms_thermal(_model(), temperate, thermal.Settings(lighting_control="stepped"))
    rooms = {r["room"]: r for r in res["rooms"]}
    lc = rooms["Living"]["thermal"]["lighting_control"]
    assert lc["mode"] == "stepped" and lc["control_points"] > 4 and lc["saving_pct"] > 0
    assert res["engine"]["lighting_control"]["control_points"] >= lc["control_points"]


def test_settings_validation():
    for bad in ({"lighting_control": "dim"}, {"lighting_control": "stepped", "lighting_steps": 0},
                {"lighting_control": "continuous", "lighting_target_lux": 5}):
        with pytest.raises(ValueError):
            thermal.Settings(**bad).validate()
    with pytest.raises(ValueError, match="control points"):
        z = thermal.Zone("plain", 20.0, 60.0)
        studies.prepare_lighting([z], None, None, thermal.Settings(lighting_control="on_off"))
