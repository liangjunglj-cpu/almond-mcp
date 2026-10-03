"""Analysis input boundaries and honest presentation without a Rhino licence."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOST = os.environ.get("ALMOND_ARCHIVE_TEST_HOST")


@pytest.mark.skipif(not HOST, reason="Build the standalone .NET archive host")
@pytest.mark.parametrize("settings,valid", [
    ({}, True),
    ({"load_kn": 0, "self_weight": False, "fixed_rotations": False}, True),
    ({"engine": "karamba", "structure": "shell", "material": "Concrete", "explicit_supports": True}, True),
    ({"structure": "shell"}, False),                                   # the native engine is line members only
    ({"engine": "native", "connections": "simple", "floor_imposed_kn_m2": 2.0, "floor_dead_kn_m2": 1.0,
      "asset_loads": True, "design_basis": "unfactored", "uls_combination": "6.10ab", "stability": "off",
      "view": "buckling", "span_m": 6.2}, True),
    ({"engine": "ansys"}, False), ({"connections": "welded"}, False), ({"view": "stress"}, False),
    ({"floor_imposed_kn_m2": -1}, False), ({"floor_dead_kn_m2": "Infinity"}, False),
    ({"span_m": 0}, False), ({"stability": "maybe"}, False),
    ({"design_code": "sg-na", "uls_combination": "", "deflection_limit_ratio": 360}, True),
    ({"design_code": "off"}, True),
    ({"fabrication": "hot_finished"}, True), ({"fabrication": "welded"}, False),
    ({"design_code": "../../etc"}, False), ({"design_code": "SG NA"}, False),
    ({"deflection_limit_ratio": 50}, False), ({"deflection_limit_ratio": 5000}, False),
    ({"diameter_mm": 114.3, "wall_mm": 4}, True),
    ({"load_kn": -1}, False), ({"load_kn": 100001}, False),
    ({"load_kn": "NaN"}, False), ({"load_kn": "Infinity"}, False),
    ({"diameter_mm": 100}, False), ({"wall_mm": 4}, False),
    ({"diameter_mm": 100, "wall_mm": 50}, False),
    ({"diameter_mm": 5001, "wall_mm": 5}, False),
    ({"diameter_mm": 100, "wall_mm": -1}, False),
    ({"material": "unknown"}, False), ({"structure": "command"}, False),
    ({"script": "_Delete"}, False), ({"file": "C:/outside.json"}, False),
    ({"material": "x" * 4097}, False),
])
def test_native_analysis_settings(tmp_path, settings, valid):
    source = tmp_path / "settings.json"
    source.write_text(json.dumps(settings), encoding="utf-8")
    run = subprocess.run([HOST, "--settings", str(source)], capture_output=True, text=True, timeout=15)
    assert (run.returncode == 0) == valid, run.stdout + run.stderr
    if valid:
        result = json.loads(run.stdout)
        for key, value in settings.items():
            assert result[key] == value
    else:
        assert run.stderr.strip()


def test_analysis_result_presentation():
    node = shutil.which("node")
    assert node, "Node is required for the analysis presentation checks"
    run = subprocess.run([node, "--test", str(ROOT / "tests/analysis_view.test.mjs")],
                         capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stdout + run.stderr


def test_rhino_panel_theme_boundary():
    node = shutil.which("node")
    assert node, "Node is required for panel appearance checks"
    run = subprocess.run([node, "--test", str(ROOT / "tests/panel_theme.test.mjs")],
                         capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stdout + run.stderr


def _host_solve(tmp_path, request, command):
    source = tmp_path / "request.json"
    source.write_text(json.dumps(request), encoding="utf-8")
    env = dict(os.environ, ALMOND_SOLVER_COMMAND=command)
    run = subprocess.run([HOST, "--solve", str(source)], capture_output=True, timeout=180, env=env)
    return json.loads(run.stdout.decode("utf-8"))


@pytest.mark.skipif(not HOST, reason="Build the standalone .NET archive host")
def test_panel_solver_process_boundary(tmp_path):
    """The bridge's NativeSolver runs `almond-mcp solve` out of process, UTF-8 both ways."""
    import sys
    from tests.test_asset_load_tools import BEAM
    command = f'"{sys.executable}" -m almond_mcp'
    req = {"model": dict(BEAM, warnings=["Träger · 梁"]), "settings": {"structure": "beam", "load_kn": 5}}
    out = _host_solve(tmp_path, req, command)
    assert out["protocol"] == 1 and out["status"] in ("pass", "fail"), out
    assert out["solver"].endswith("almond_mcp solve")
    assert "Träger · 梁" in out["validation"]["warnings"] and out["draw"]["type"] == "structure_draw"
    ping = _host_solve(tmp_path, {"ping": True}, command)
    assert ping["status"] == "ok", ping
    bad = _host_solve(tmp_path, {"model": {}}, command)
    assert bad["status"] == "error" and "No exported structural model" in bad["message"]
    missing = _host_solve(tmp_path, {"ping": True}, '"C:/nowhere/python.exe" -m almond_mcp')
    assert missing["status"] == "error" and "Could not start the native solver" in missing["message"]


@pytest.mark.skipif(not HOST, reason="Build the standalone .NET archive host")
@pytest.mark.parametrize("version, package", [
    ("0.7.0", "almond-mcp@0.7.0"),
    ("0.7.0-rc.1", "almond-mcp@0.7.0rc1"),             # Yak prerelease -> its PyPI twin, never an older stable
    ("0.7.0-beta.2", "almond-mcp@0.7.0b2"),
    ("0.6.1-dev", "almond-mcp"),                        # development builds take the latest
    ("", "almond-mcp"),
])
def test_panel_solver_package_pin(version, package):
    run = subprocess.run([HOST, "--package", version], capture_output=True, text=True, timeout=30)
    assert run.stdout.strip() == package, run.stdout + run.stderr


def test_results_page_presentation():
    node = shutil.which("node")
    assert node, "Node is required for the results page checks"
    run = subprocess.run([node, "--test", str(ROOT / "tests/results_view.test.mjs")],
                         capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stdout + run.stderr
