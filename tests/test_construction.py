"""Construction-system manifest validity + guidance/cross-check behavior."""
import importlib.util
import json
import sys
import tempfile
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = PROJECT_ROOT / "Constructionfiles" / "manifest.json"
MATERIAL_MANIFEST = PROJECT_ROOT / "Materialfiles" / "manifest.json"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

VALID_CATEGORIES = {"floor", "wall", "roof", "foundation", "longspan"}
VALID_STRUCTURE_TYPES = {"beam", "truss", "shell", "frame", "canopy",
                         "gridshell", "membrane", "highrise"}
VALID_STRUCTURAL_MATERIALS = {"Steel", "Concrete", "Wood", "Aluminium"}


def load_server():
    import os
    os.environ["RHINO_MCP_STATE_DB"] = tempfile.mktemp(suffix=".sqlite3")
    spec = importlib.util.spec_from_file_location(
        f"almond_server_construction_{uuid.uuid4().hex}",
        PROJECT_ROOT / "almond_mcp" / "server.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manifest_is_valid():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    systems = manifest["systems"]
    assert len(systems) >= 15
    render_ids = {m["material_id"] for m in
                  json.loads(MATERIAL_MANIFEST.read_text(encoding="utf-8"))["materials"]}
    seen = set()
    for system in systems:
        sid = system.get("system_id")
        for key in ("system_id", "name", "category", "structural_material",
                    "structure_types", "span_range_m", "elements", "bci_ref"):
            assert key in system, f"{sid} missing {key}"
        assert sid not in seen
        seen.add(sid)
        assert system["category"] in VALID_CATEGORIES, sid
        assert system["structural_material"] in VALID_STRUCTURAL_MATERIALS, sid
        assert set(system["structure_types"]) <= VALID_STRUCTURE_TYPES, sid
        lo, hi = system["span_range_m"]
        assert 0 <= lo <= hi, sid
        # every referenced render material must exist in the PBR library
        for material_id in system.get("render_material_ids", []):
            assert material_id in render_ids, f"{sid} -> {material_id}"
        for rule in system.get("depth_rules", []):
            assert "element" in rule and "span_ratio" in rule, sid
            assert rule["span_ratio"] >= 0, sid
        if system["category"] == "wall":
            assert system.get("span_axis") == "vertical", sid
    # reference tables ship with the manifest
    reference = manifest["reference"]
    assert reference["live_loads_kpa"]["office"] > 0
    assert reference["material_densities_kg_m3"]["steel_rolled"] > 7000
    egress = reference["egress_rules"]
    assert egress["occupant_load_m2_per_person"]["business"] == 9.3
    assert egress["exit_separation_fraction_of_diagonal"]["sprinklered"] < 0.5
    assert egress["stair_rules_mm"]["max_riser"] == 180
    assert egress["min_widths_mm"]["exit_stair"] == 1120
    tiers = egress["exits_required_by_occupant_load"]
    assert tiers[0]["exits"] == 1 and tiers[-1]["max_occupants"] is None
    assert egress["fire_resistance"]["solid_reinforced_concrete_wall_mm"]["2hr"] == 125


def test_library_loads_and_filters():
    server = load_server()
    library = server.construction_library
    assert len(library.systems) >= 15
    floors = library.list(category="floor")
    assert floors and all(s["category"] == "floor" for s in floors)
    wood_beams = library.list(material="Wood", structure_type="beam")
    assert wood_beams
    assert all(s["structural_material"] == "Wood" and "beam" in s["structure_types"]
               for s in wood_beams)
    # S355 is a steel grade; guidance must treat it as Steel
    s355 = library.list(material="S355")
    assert s355 and all(s["structural_material"] == "Steel" for s in s355)
    hits = library.list(query="glulam")
    assert hits
    assert library.get("wood-joist-floor")
    assert library.get("nonexistent-system") is None


def test_assess_span_fitting():
    server = load_server()
    check = server.construction_library.assess_span("beam", "Steel", 8.0)
    assert check["matching_systems"]
    assert not check["warnings"]
    fitting = [s for s in check["matching_systems"] if s.get("fits_span")]
    assert fitting
    # depth guidance derives from the span-ratio rules
    guided = [s for s in check["matching_systems"] if "depth_guidance" in s]
    assert guided
    wf = next(s for s in check["matching_systems"]
              if s["system_id"] == "steel-wide-flange-floor")
    beam_rule = next(d for d in wf["depth_guidance"] if d["element"] == "beam")
    assert beam_rule["suggested_depth_mm"] == 400  # 8 m / 20


def test_assess_span_out_of_range_warns():
    server = load_server()
    # 15 m sawn-lumber beam floor is not a real construction system
    check = server.construction_library.assess_span("beam", "Wood", 15.0)
    assert check["warnings"]
    assert "outside the typical range" in check["warnings"][0]
    assert not any(s.get("fits_span") for s in check["matching_systems"])


def test_assess_span_no_candidates_warns():
    server = load_server()
    check = server.construction_library.assess_span("membrane", "Wood", 10.0)
    assert check["warnings"]
    assert "No curated construction system" in check["warnings"][0]
    assert check["matching_systems"] == []


def _check_egress(server, **kwargs):
    tool = server.check_egress
    fn = getattr(tool, "fn", tool)
    return json.loads(fn(**kwargs))


def test_check_egress_single_exit_fails():
    server = load_server()
    # the 24x16 m 3-story office from the live test, before remediation
    result = _check_egress(
        server,
        plate_bounds_mm=[0, 0, 24000, 16000],
        exits=[{"name": "stair 1", "x_mm": 9770, "y_mm": 8200, "width_mm": 1120}],
        occupancy="business", stories=3, sprinklered=True)
    assert result["occupant_load"] == 42
    assert result["passed"] is False
    exit_check = next(c for c in result["checks"] if c["check"] == "exit_count")
    assert exit_check["required"] == 2 and exit_check["provided"] == 1
    assert not exit_check["passed"]


def test_check_egress_two_core_tower_passes():
    server = load_server()
    # the 40x24 m tower: two stairs 19.3 m apart, measured travel distances
    result = _check_egress(
        server,
        plate_bounds_mm=[0, 0, 40000, 24000],
        exits=[{"name": "stair A", "x_mm": 11420, "y_mm": 12600, "width_mm": 1120},
               {"name": "stair B", "x_mm": 30700, "y_mm": 12600, "width_mm": 1120}],
        occupancy="business", stories=6, sprinklered=True,
        travel_distances_m=[21.2, 15.1], dead_end_m=11.4)
    assert result["occupant_load"] == 104
    assert result["passed"] is True
    sep = next(c for c in result["checks"] if c["check"] == "exit_separation_m")
    assert sep["passed"] and sep["provided"] > sep["required"]
    assert len(result["checks"]) == 6  # count, separation, 2x width, travel, dead-end


def test_check_egress_separation_and_width_failures():
    server = load_server()
    # two exits too close together, one door below stair minimum
    result = _check_egress(
        server,
        plate_bounds_mm=[0, 0, 40000, 24000],
        exits=[{"name": "a", "x_mm": 10000, "y_mm": 12000, "width_mm": 1120},
               {"name": "b", "x_mm": 14000, "y_mm": 12000, "width_mm": 900}],
        occupancy="business", stories=6, sprinklered=True)
    assert result["passed"] is False
    sep = next(c for c in result["checks"] if c["check"] == "exit_separation_m")
    assert not sep["passed"]
    minw = next(c for c in result["checks"] if c["check"] == "min_exit_width_mm")
    assert not minw["passed"]
    assert any("below minimum width" in w for w in result["warnings"])


def test_check_egress_unsprinklered_tightens_limits():
    server = load_server()
    kwargs = dict(
        plate_bounds_mm=[0, 0, 24000, 16000],
        exits=[{"name": "s1", "x_mm": 2000, "y_mm": 8000, "width_mm": 1120},
               {"name": "s2", "x_mm": 22000, "y_mm": 8000, "width_mm": 1120}],
        occupancy="business", stories=2, dead_end_m=9.3)
    ok = _check_egress(server, sprinklered=True, **kwargs)
    bad = _check_egress(server, sprinklered=False, **kwargs)
    dead_ok = next(c for c in ok["checks"] if c["check"] == "max_dead_end_m")
    dead_bad = next(c for c in bad["checks"] if c["check"] == "max_dead_end_m")
    assert dead_ok["passed"] and not dead_bad["passed"]


def test_check_egress_input_errors():
    server = load_server()
    r = _check_egress(server, plate_bounds_mm=[0, 0, 1000], exits=[{"name": "x"}])
    assert r["status"] == "error"
    r = _check_egress(server, plate_bounds_mm=[0, 0, 10000, 10000], exits=[])
    assert r["status"] == "error"
    r = _check_egress(server, plate_bounds_mm=[0, 0, 10000, 10000],
                      exits=[{"name": "x", "x_mm": 0, "y_mm": 0, "width_mm": 1120}],
                      occupancy="spaceship")
    assert r["status"] == "error" and "spaceship" in r["message"]


def test_material_script_carries_construction_metadata():
    server = load_server()
    material = server.material_library.get("steel-painted-sage")
    guid = str(uuid.uuid4())
    script = server._material_script(
        material, [guid], True, True,
        {"almond:structural_role": "girder",
         "almond:construction_system": "steel-wide-flange-floor",
         "almond:structural_material": "Steel"})
    assert 'SetUserString("almond:structural_role", "girder")' in script
    assert 'SetUserString("almond:construction_system", "steel-wide-flange-floor")' in script
    assert 'SetUserString("almond:structural_material", "Steel")' in script
    # default path unchanged
    plain = server._material_script(material, [guid], True, True)
    assert "structural_role" not in plain
