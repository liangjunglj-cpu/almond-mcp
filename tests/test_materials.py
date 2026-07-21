"""Material library manifest validity + assign_material script generation."""
import importlib.util
import json
import sys
import tempfile
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = PROJECT_ROOT / "Materialfiles" / "manifest.json"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def load_server():
    import os
    os.environ["RHINO_MCP_STATE_DB"] = tempfile.mktemp(suffix=".sqlite3")
    spec = importlib.util.spec_from_file_location(
        f"almond_server_materials_{uuid.uuid4().hex}",
        PROJECT_ROOT / "almond_mcp" / "server.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manifest_is_valid():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    materials = manifest["materials"]
    assert len(materials) >= 10
    seen = set()
    for material in materials:
        for key in ("material_id", "name", "category", "base_color",
                    "metallic", "roughness", "opacity", "ue_material_slot"):
            assert key in material, f"{material.get('material_id')} missing {key}"
        assert material["material_id"] not in seen
        seen.add(material["material_id"])
        r, g, b = material["base_color"]
        assert all(0 <= v <= 255 for v in (r, g, b))
        for channel in ("metallic", "roughness", "opacity"):
            assert 0.0 <= material[channel] <= 1.0, material["material_id"]
        assert material["ue_material_slot"].startswith("M_")


def test_library_loads_and_filters():
    server = load_server()
    assert len(server.material_library.materials) >= 10
    metals = server.material_library.list(category="metal")
    assert metals and all(m["category"] == "metal" for m in metals)
    hits = server.material_library.list(query="polycarbonate")
    assert hits and all("polycarbonate" in m["material_id"] for m in hits)


def test_material_script_contains_pbr_and_metadata():
    server = load_server()
    material = server.material_library.get("steel-painted-sage")
    guid = str(uuid.uuid4())
    script = server._material_script(material, [guid], True, True)
    assert "ALMOND::steel-painted-sage" in script
    assert guid in script
    assert "PhysicallyBased" in script
    assert "MaterialFromObject" in script
    assert 'SetUserString("almond:material_id", "steel-painted-sage")' in script
    assert 'SetUserString("almond:ue_material_slot", "M_Steel_Painted_Sage")' in script

    no_meta = server._material_script(material, [guid], True, False)
    assert "SetUserString" not in no_meta
    no_render = server._material_script(material, [guid], False, True)
    assert "MaterialFromObject" not in no_render
