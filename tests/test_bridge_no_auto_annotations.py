"""The bridge must not add annotations the caller did not ask for.

Earlier bridges stamped a LinearDimension over every script's output, so each
place_generated_asset call left two stray dimensions in the user's document.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_script_execution_adds_no_dimensions():
    for source in (ROOT / "RhinoAlmondBridge/ScriptExecutor.cs", ROOT / "rhino_bridge.py"):
        text = source.read_text(encoding="utf-8")
        assert "AddLinearDimension" not in text, source.name
        assert "AddScaleDimensions" not in text and "_add_scale_dimensions" not in text, source.name
