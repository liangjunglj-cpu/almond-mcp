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
    ({"structure": "shell", "material": "Concrete", "explicit_supports": True}, True),
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
