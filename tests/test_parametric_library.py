"""The annotated parametric library is reproducible, licensed and logic-preserving."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "ParametricLibrary"
TOOLS = ROOT / "tools" / "parametric_library"

pytestmark = pytest.mark.skipif(not LIBRARY.is_dir(), reason="ParametricLibrary is repository-only (not in the sdist)")


def _load(name):
    sys.path.insert(0, str(TOOLS))
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_is_reproducible_and_current(tmp_path):
    build = _load("build_parametric_library")
    catalogue, register, problems = build.build(LIBRARY, tmp_path)
    assert problems == []
    for entry in catalogue["entries"]:
        assert build.sha256(tmp_path / entry["definition"]) == build.sha256(LIBRARY / entry["definition"]), entry["id"]
    assert json.loads((LIBRARY / "catalogue.json").read_text(encoding="utf-8")) == catalogue
    assert json.loads((LIBRARY / "source-register.json").read_text(encoding="utf-8")) == register


def test_every_definition_keeps_upstream_logic():
    fp = _load("logic_fingerprint")
    register = json.loads((LIBRARY / "source-register.json").read_text(encoding="utf-8"))
    for item in register["items"]:
        repo = item["source"]["repo_url"].removeprefix("https://github.com/").replace("/", "__")
        upstream = (LIBRARY / "upstream" / repo / item["source"]["path"]).with_suffix(".ghx")
        overrides = item["derivation"][-1]["value_overrides"]
        before = fp.fingerprint(upstream, overrides)
        after = fp.fingerprint(LIBRARY / "definitions" / f"{item['id']}.ghx")
        assert before and before == after, item["id"]
        for guid, values in overrides.items():  # every override is justified and really differs from upstream
            assert values.get("reason"), item["id"]
            assert fp.fingerprint(upstream)[guid] != after[guid], item["id"]


def test_sources_are_permissively_licensed_and_noticed():
    register = json.loads((LIBRARY / "source-register.json").read_text(encoding="utf-8"))
    allowed = {"MIT", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0", "BlueOak-1.0.0", "CC0-1.0", "CC-BY-4.0", "BSL-1.0"}
    for item in register["items"]:
        rights = item["rights"]
        assert rights["licence"] in allowed, item["id"]
        licence_text = (LIBRARY / rights["licence_file"]).read_text(encoding="utf-8")
        assert licence_text.strip()
        definition = (LIBRARY / "definitions" / f"{item['id']}.ghx").read_text(encoding="utf-8")
        assert "LICENCE" in definition and item["source"]["commit"][:10] in definition, item["id"]
        assert len(item["source"]["commit"]) == 40


def test_annotations_are_present():
    inspect = _load("ghx_inspect").inspect
    for entry in json.loads((LIBRARY / "catalogue.json").read_text(encoding="utf-8"))["entries"]:
        info = inspect(LIBRARY / entry["definition"])
        titles = {g["nickname"] for g in info["groups"]}
        assert "README" in titles
        assert all(step in titles for step in entry["steps"]), entry["id"]
        assert not entry["plugins"] or entry["plugins"] == ["GhPython"], entry["id"]


# -- harnessed capsules (runnable derivatives) --------------------------------

def _objects(path):
    """({instance guid: Container chunk}, {every wire source guid}, ghx_inspect) for a .ghx."""
    import xml.etree.ElementTree as ET
    gi = _load("ghx_inspect")
    root = ET.parse(path).getroot()
    objs = gi.first(gi.first(root, "Definition"), "DefinitionObjects")
    out = {}
    for o in gi.sub(objs, "Object"):
        c = gi.first(o, "Container")
        if c is not None:
            out[gi.text(c, "InstanceGuid")] = c
    sources = {it.text for it in objs.iter("item") if it.get("name") == "Source"}
    return out, sources, gi


def test_harnessed_capsules_map_back_onto_teaching_logic():
    import hashlib
    from almond_mcp.ghx_parser import validate_capsule_manifest
    jsonschema = pytest.importorskip("jsonschema")
    fp = _load("logic_fingerprint")
    register = json.loads((LIBRARY / "source-register.json").read_text(encoding="utf-8"))
    catalogue = {e["id"]: e for e in json.loads((LIBRARY / "catalogue.json").read_text(encoding="utf-8"))["entries"]}
    schema = json.loads((ROOT / "capsules" / "capsule.schema.json").read_text(encoding="utf-8"))
    harnessed_items = [i for i in register["items"] if "harnessed" in i]
    assert [i["id"] for i in harnessed_items] == ["structure-shell-roof-ribs"]
    for item in harnessed_items:
        h, d = item["harnessed"], item["harnessed"]["derivation"]
        teaching = LIBRARY / "definitions" / f"{item['id']}.ghx"
        harnessed, manifest_path = LIBRARY / h["definition"], LIBRARY / h["manifest"]
        assert catalogue[item["id"]]["capsule"] == {"capsule_id": h["capsule_id"], "capability": "generate",
                                                    "definition": h["definition"], "manifest": h["manifest"],
                                                    "audited": h["audited"]}
        # register hashes are current
        assert hashlib.sha256(harnessed.read_bytes()).hexdigest() == d["output_sha256"]
        assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == d["manifest_sha256"]
        assert hashlib.sha256(teaching.read_bytes()).hexdigest() == d["input_sha256"] == item["derivation"][-1]["output_sha256"]
        # the harness undone (objects dropped, sources mapped back) is exactly the teaching logic
        before = fp.fingerprint(teaching)
        mapped = fp.fingerprint(harnessed, drop=d["harness_objects"], substitutions=d["substitutions"])
        assert before == mapped and d["logic_fingerprint_unchanged_after_mapping"]
        assert fp.fingerprint(harnessed) != before
        # replaced inputs are disconnected and every port has exactly one param with its reserved nickname
        objs, sources, gi = _objects(harnessed)
        replaced = {r["object"] for r in d["replaced"]}
        assert replaced <= set(objs) and not (replaced & sources)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        ports = {p["name"] for p in manifest["inputs"] + manifest["outputs"]}
        almond_params = {gi.text(c, "NickName") for c in objs.values() if (gi.text(c, "NickName") or "").startswith("ALMOND_")}
        assert almond_params == ports and len(ports) == len(manifest["inputs"]) + len(manifest["outputs"])
        assert set(d["substitutions"].values()) == replaced and set(d["substitutions"]) <= set(d["harness_objects"])
        # defaults are the replaced sliders' saved values; the geometry sample was copied across
        teaching_objs, _, _ = _objects(teaching)
        for port in manifest["inputs"]:
            r = next(r for r in d["replaced"] if r["port"] == port["name"])
            if "default" in port:
                slider = gi.first(teaching_objs[r["object"]], "Slider")
                assert float(gi.text(slider, "Value")) == float(port["default"]), port["name"]
            else:
                harness_param = next(c for c in objs.values() if gi.text(c, "NickName") == port["name"])
                assert gi.first(harness_param, "PersistentData") is not None
                assert gi.first(teaching_objs[r["object"]], "PersistentData") is not None
        # contract shape: capsule schema, server validator, honest audit state
        assert validate_capsule_manifest(manifest) == []
        jsonschema.validate(manifest, schema)
        assert manifest["capability"] == "generate" and manifest["audited"] is False and h["audited"] is False
        assert manifest["definition_file"] == harnessed.name and manifest["plugin_dependencies"] == []
        assert manifest["source"]["parametric_definition"] == item["id"]
        assert manifest["source"]["licence"] == item["rights"]["licence"]
        assert "not run live" in manifest["audit"]["status"]


def test_harness_refuses_ports_that_replace_nothing(tmp_path):
    hx = _load("harness_ghx")
    lesson = json.loads((LIBRARY / "lessons" / "structure-shell-roof-ribs.lesson.json").read_text(encoding="utf-8"))
    teaching = LIBRARY / "definitions" / "structure-shell-roof-ribs.ghx"
    bad = json.loads(json.dumps(lesson))
    bad["harness"]["inputs"][1]["replaces"] = "97347b13"  # the Pipe: nothing downstream consumes it
    bad["harness"]["inputs"][1]["default"] = 5
    with pytest.raises(hx.HarnessError, match="nothing consumes"):
        hx.harness(teaching, bad, tmp_path / "a.ghx")
    bad = json.loads(json.dumps(lesson))
    bad["harness"]["outputs"][0]["from"] = ["00000000"]
    with pytest.raises(hx.HarnessError, match="matches 0 objects"):
        hx.harness(teaching, bad, tmp_path / "b.ghx")
    bad = json.loads(json.dumps(lesson))
    bad["harness"]["inputs"][0]["type"] = "surface"
    with pytest.raises(hx.HarnessError, match="unsupported port type"):
        hx.harness(teaching, bad, tmp_path / "c.ghx")
