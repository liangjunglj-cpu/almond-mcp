"""Ginkgo batches staged with tools/stage_ginkgo_chains.py: mesh bank, Freiburg, refset_1118, Daxi harbour, the
Project Y2K props (v038 and round 1/2 Meshy text-to-3D, refset_0923b trees), the Ginkgo props reused in Project Y2K
(refset_1003, refset_1007, refset_0924, Lausanne market) and Project Y2K's procedural kit pieces (street v004, district
v016, megastructure v020, Mirai Ward world v040).

Each batch has a different image stage and link to the mesh stage (or, for Meshy text-to-3D, a preview task and no
image at all; for procedural kits, a Blender script and its FBX and no provider at all); the evidence must keep every
link checkable.
"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

import pytest

from almond_mcp.asset_loads import LoadTable
from almond_mcp.asset_repository import AssetRepository

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "GeneratedAssetfiles"
BATCHES = {name: json.loads((LIBRARY / f"batches/{name}.json").read_text(encoding="utf-8"))
           for name in ("ginkgo-meshbank-2026-11", "ginkgo-freiburg-2026-11", "ginkgo-refset-1118",
                        "ginkgo-daxi-2026-11", "y2k-props-v038", "y2k-trees-refset-0923b",
                        "y2k-twofronts-2026-09", "ginkgo-refset-1003", "ginkgo-refset-1007",
                        "ginkgo-refset-0924", "ginkgo-lausanne-market", "y2k-street-kit-v004",
                        "y2k-district-kit-v016", "y2k-megastructure-kit-v020", "y2k-world-kit-v040")}
PROCEDURAL = sorted(name for name, batch in BATCHES.items() if batch.get("route") == "procedural_script")
spec = importlib.util.spec_from_file_location("ginkgo_chain_sources", ROOT / "tools/document_generation_sources.py")
source_doc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(source_doc)


def manifest():
    return {a["asset_id"]: a for a in json.loads((LIBRARY / "manifest.json").read_text(encoding="utf-8"))["assets"]}


@pytest.mark.parametrize("name", sorted(BATCHES))
def test_batch_keeps_its_generation_chain(name):
    batch = BATCHES[name]
    repo, records = AssetRepository(), manifest()
    assert repo.search(name)["total"] == len(batch["release_assets"]) == len(batch["assets"])
    for brief in batch["assets"]:
        record = repo.records[brief["asset_id"]]
        generation = record["provenance"]["recorded_generation"]
        captured = generation["captured_generation"]
        mesh, derivation = captured["mesh"], captured["derivation"]
        if batch.get("route") == "meshy_text_to_3d":
            check_text_to_3d(name, brief, record, captured)
        elif batch.get("route") == "procedural_script":
            check_procedural(name, brief, record, captured)
        else:
            check_image_stage(name, brief, record, captured, records, repo)
        assert derivation["source_sha256"] == mesh["output_sha256"]
        q = derivation["quality"]
        assert q["triangles"] <= brief["target_triangles"] + 100
        assert not q["nonfinite_coordinates"] and not q["zero_area_faces"]
        assert not q["nonmanifold_edges_excluding_boundary"]
        assert derivation["method"].startswith("Import the kit FBX" if batch.get("route") == "procedural_script"
                                               else "Remove provider PBR materials")
        assert captured["origin"]["source_name"] == brief.get("source_name", brief.get("ginkgo_name"))
        assert not any(s in json.dumps(captured) for s in ("cloudfront", "assets.meshy", ":\\\\", "Users/", "user_"))
        asset = records[brief["asset_id"]]
        assert asset["dimensions_mm"]["height"] == brief["height_mm"]
        assert asset["render_material_id"] == brief["material"]
        assert asset["spatial"]["support_plane"] == brief["support_plane"]
        assert asset["spatial"].get("mount_height_mm") == brief.get("mount_height_mm")


def check_text_to_3d(name, brief, record, captured):
    """Meshy text-to-3D: the prompt went to a preview task and a refine task named it; there is no image."""
    generation = record["provenance"]["recorded_generation"]
    preview, mesh = captured["preview"], captured["mesh"]
    assert captured["route"] == generation["generation_route"] == "meshy_text_to_3d" and "image" not in captured
    assert preview["tool"] == "meshy_text_to_3d" and mesh["tool"] == "meshy_text_to_3d_refine"
    assert preview["request"]["prompt"] == brief["prompt"] == generation["prompt"]
    assert preview["task_id"] == brief["preview_task_id"] == generation["preview_task_id"]
    assert mesh["task_id"] == brief["mesh_task_id"] and mesh["input_link"] == "preview_task_id"
    assert mesh["request"]["preview_task_id"] == preview["task_id"]
    assert "image_task_id" not in generation and "image_model" not in generation
    assert captured["input_image_file"] is None and record["generation_image"] is None
    assert not any((LIBRARY / "batches" / name).glob(brief["asset_id"] + "*.png"))
    if mesh["output_format"] == "obj":
        # Meshy's OBJ download is the hashed source; Blender converted its geometry to the library GLB.
        assert captured["derivation"]["source_format"] == "obj"
        assert "Import the provider OBJ geometry" in captured["derivation"]["method"]
        assert mesh["download"]["format"] == "obj"


def check_procedural(name, brief, record, captured):
    """Blender-script kit piece: the retained script and kit record and the FBX hash are the evidence; no provider."""
    generation = record["provenance"]["recorded_generation"]
    script, kit, mesh = captured["generator"]["script"], captured["generator"]["kit_record"], captured["mesh"]
    assert captured["route"] == generation["generation_route"] == "procedural_script"
    assert not {"image", "preview"} & set(captured) and captured["input_image_file"] is None
    assert record["generation_image"] is None and generation["prompt"] is None and brief["prompt"] is None
    assert not {"mesh_task_id", "mesh_model", "image_task_id", "image_model"} & set(generation)
    assert record["provenance"]["generator"] == "procedural_script"
    assert script["path"] == brief["generator_script"] == generation["generator_script"] == mesh["generator_script"]
    assert script["sha256"] == generation["generator_script_sha256"] == mesh["generator_script_sha256"]
    assert mesh["output_sha256"] == brief["source_sha256"] == generation["source_sha256"]
    assert mesh["tool"] == "blender_procedural_script" and mesh["output_format"] == "fbx"
    assert captured["derivation"]["source_format"] == "fbx"
    # Low-poly kit geometry is never decimated: the target is the source count, and the library mesh holds at most
    # the source minus the recorded removals (weld and degenerate cleanup may drop a few more).
    derivation = captured["derivation"]
    applied = [e for e in derivation["source_edits"] if e["op"] != "remove_collision_hulls"]
    assert derivation["source_triangles"] == brief["target_triangles"]
    assert derivation["quality"]["triangles"] <= brief["target_triangles"] - sum(e["triangles_removed"] for e in applied)
    # Every recorded edit was applied and removed something.
    assert [{k: v for k, v in e.items() if k != "triangles_removed"} for e in applied] == brief["edits"] == captured["edits"]
    assert all(e["triangles_removed"] > 0 for e in captured["derivation"]["source_edits"])
    for entry in (script, kit):
        kept = LIBRARY / entry["retained_file"]
        text = kept.read_text(encoding="utf-8")
        assert hashlib.sha256(kept.read_bytes()).hexdigest() == entry["retained_sha256"]
        assert "Users\\" not in text and "Users/" not in text
    assert not any((LIBRARY / "batches" / name).glob(brief["asset_id"] + "*.png"))


def check_image_stage(name, brief, record, captured, records, repo):
    generation = record["provenance"]["recorded_generation"]
    image, mesh = captured["image"], captured["mesh"]
    assert image["request"]["prompt"] == brief["prompt"] == generation["prompt"]
    assert image["task_id"] == brief["image_job_id"] and mesh["task_id"] == brief["mesh_task_id"]
    link = mesh["input_link"]
    if link == "input_task_id":
        assert mesh["request"]["input_task_id"] == image["task_id"]
    elif link == "media_job_id":
        assert [m["value"] for m in mesh["request"]["medias"]] == [image["task_id"]]
        assert mesh["request"]["model"] == "tripo_h3_1_image_to_3d"
        assert record["provenance"]["generator"] == "tripo" and "tripo" in records[brief["asset_id"]]["tags"]
    elif link == "uploaded_derivative":
        upload = mesh["uploaded_input"]
        assert [m["value"] for m in mesh["request"]["medias"]] == [upload["media_id"]]
        assert upload["derived_from_sha256"] == image["output_sha256"] != upload["sha256"]
        assert upload["operation"] and record["provenance"]["generator"] == "tripo"
        kept = LIBRARY / "batches" / name / image["output_file"]
        assert hashlib.sha256(kept.read_bytes()).hexdigest() == image["output_sha256"]
    else:
        assert link == "upload" and "input_task_id" not in mesh["request"]
        assert mesh["request"]["image"].startswith("local upload of ")
    mesh_input = mesh["uploaded_input"]["sha256"] if link == "uploaded_derivative" else image["output_sha256"]
    assert mesh["input_image_sha256"] == mesh_input
    retained = repo.files[record["generation_image"]][1]
    assert hashlib.sha256(retained.read_bytes()).hexdigest() == mesh_input


def test_photo_inputs_are_named_and_hashed_but_not_shipped():
    batch = BATCHES["ginkgo-freiburg-2026-11"]
    repo = AssetRepository()
    shipped = {p.name for p in (LIBRARY / "batches/ginkgo-freiburg-2026-11").iterdir()}
    for brief in batch["assets"]:
        image = repo.records[brief["asset_id"]]["provenance"]["recorded_generation"]["captured_generation"]["image"]
        assert image["tool"] == "meshy_image_to_image" and image["reference_inputs"]
        for ref in image["reference_inputs"]:
            assert len(ref["sha256"]) == 64 and ref["retained"] is False
            assert ref["name"] not in shipped


def test_new_props_have_loads_and_rooms():
    table = LoadTable(LIBRARY / "structural-loads.json")
    records = manifest()
    for batch in BATCHES.values():
        for aid in batch["release_assets"]:
            asset = records[aid]
            assert table.lookup(aid, asset["category"])
            if asset["category"] == "ornament":
                assert asset["passport"]["usage"]["suggested_rooms"] == ["architecture", "streetscape"]


def test_source_audit_rejects_tripo_mesh_naming_another_image(tmp_path):
    for name in ("catalogue.json", "provenance.json"):
        shutil.copyfile(LIBRARY / name, tmp_path / name)
    shutil.copytree(LIBRARY / "batches", tmp_path / "batches")
    data = json.loads((LIBRARY / "manifest.json").read_text(encoding="utf-8"))
    provenance = json.loads((tmp_path / "provenance.json").read_text(encoding="utf-8"))
    aid = "gen-taxi-sedan-1"
    asset = next(a for a in data["assets"] if a["asset_id"] == aid)
    for captured in (asset["geometry_source"]["parameters"]["captured_generation"],
                     provenance["assets"][aid]["captured_generation"]):
        captured["mesh"]["request"]["medias"][0]["value"] = "00000000-0000-0000-0000-000000000000"
    asset["passport"]["provenance"] = copy.deepcopy(asset["geometry_source"])
    (tmp_path / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
    (tmp_path / "provenance.json").write_text(json.dumps(provenance), encoding="utf-8")
    result = source_doc.build_register(tmp_path)
    assert f"{aid}: captured task chain differs" in result["errors"]


def test_source_audit_rejects_derivative_not_made_from_the_generated_image(tmp_path):
    for name in ("catalogue.json", "provenance.json"):
        shutil.copyfile(LIBRARY / name, tmp_path / name)
    shutil.copytree(LIBRARY / "batches", tmp_path / "batches")
    data = json.loads((LIBRARY / "manifest.json").read_text(encoding="utf-8"))
    provenance = json.loads((tmp_path / "provenance.json").read_text(encoding="utf-8"))
    aid = "gen-fishing-boat-coastal-b-1"
    asset = next(a for a in data["assets"] if a["asset_id"] == aid)
    for captured in (asset["geometry_source"]["parameters"]["captured_generation"],
                     provenance["assets"][aid]["captured_generation"]):
        captured["mesh"]["uploaded_input"]["derived_from_sha256"] = "0" * 64
    asset["passport"]["provenance"] = copy.deepcopy(asset["geometry_source"])
    (tmp_path / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
    (tmp_path / "provenance.json").write_text(json.dumps(provenance), encoding="utf-8")
    result = source_doc.build_register(tmp_path)
    assert f"{aid}: captured task chain differs" in result["errors"]


def tampered_register(tmp_path, aid, edit):
    for name in ("catalogue.json", "provenance.json"):
        shutil.copyfile(LIBRARY / name, tmp_path / name)
    shutil.copytree(LIBRARY / "batches", tmp_path / "batches")
    data = json.loads((LIBRARY / "manifest.json").read_text(encoding="utf-8"))
    provenance = json.loads((tmp_path / "provenance.json").read_text(encoding="utf-8"))
    asset = next(a for a in data["assets"] if a["asset_id"] == aid)
    for captured in (asset["geometry_source"]["parameters"]["captured_generation"],
                     provenance["assets"][aid]["captured_generation"]):
        edit(captured)
    asset["passport"]["provenance"] = copy.deepcopy(asset["geometry_source"])
    (tmp_path / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
    (tmp_path / "provenance.json").write_text(json.dumps(provenance), encoding="utf-8")
    return source_doc.build_register(tmp_path)


def test_source_audit_rejects_refine_naming_another_preview(tmp_path):
    aid = "gen-kiosk-pod-1"
    result = tampered_register(tmp_path, aid, lambda c: c["mesh"]["request"].update(
        preview_task_id="00000000-0000-0000-0000-000000000000"))
    assert f"{aid}: captured task chain differs" in result["errors"]


def test_source_audit_rejects_text_to_3d_record_with_an_input_image(tmp_path):
    aid = "gen-refuse-bag-heap-1"
    result = tampered_register(tmp_path, aid, lambda c: c.update(input_image_file="batches/x.png"))
    assert f"{aid}: text-to-3D record names an input image" in result["errors"]


def test_image_stage_assets_still_need_an_image_id(tmp_path):
    """The text-to-3D exemption is keyed on the recorded route only; it does not relax image-stage assets."""
    for name in ("catalogue.json", "provenance.json"):
        shutil.copyfile(LIBRARY / name, tmp_path / name)
    data = json.loads((LIBRARY / "manifest.json").read_text(encoding="utf-8"))
    provenance = json.loads((tmp_path / "provenance.json").read_text(encoding="utf-8"))
    aid = "gen-tree-maple-red-1"
    del provenance["assets"][aid]["image_job_id"]
    (tmp_path / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
    (tmp_path / "provenance.json").write_text(json.dumps(provenance), encoding="utf-8")
    result = source_doc.build_register(tmp_path)
    assert any(e.startswith(f"{aid}: missing recorded fields: image_generation_id") for e in result["errors"])


def test_source_audit_rejects_changed_retained_script(tmp_path):
    aid = "gen-shipping-container-1"
    result = tampered_register(tmp_path, aid, lambda c: None)
    assert not [e for e in result["errors"] if e.startswith("gen-shipping")]
    kept = tmp_path / "batches/y2k-district-kit-v016/build_district_kit_v016.py.txt"
    kept.write_text(kept.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
    result = source_doc.build_register(tmp_path)
    assert f"{aid}: retained build_district_kit_v016.py.txt missing or changed" in result["errors"]


def test_source_audit_rejects_procedural_record_naming_a_provider_task(tmp_path):
    aid = "gen-utility-pole-1"
    result = tampered_register(tmp_path, aid, lambda c: c["mesh"].update(generator_script_sha256="0" * 64))
    assert f"{aid}: captured script chain differs" in result["errors"]
    provenance = json.loads((tmp_path / "provenance.json").read_text(encoding="utf-8"))
    provenance["assets"][aid]["mesh_task_id"] = "01a00000-0000-0000-0000-000000000000"
    (tmp_path / "provenance.json").write_text(json.dumps(provenance), encoding="utf-8")
    result = source_doc.build_register(tmp_path)
    assert f"{aid}: procedural record also names a generation provider, prompt or task" in result["errors"]


def test_procedural_exemption_is_keyed_on_the_recorded_route(tmp_path):
    """Without its recorded route a procedural piece fails the provider checks (prompt, image and mesh task)."""
    for name in ("catalogue.json", "provenance.json"):
        shutil.copyfile(LIBRARY / name, tmp_path / name)
    data = json.loads((LIBRARY / "manifest.json").read_text(encoding="utf-8"))
    provenance = json.loads((tmp_path / "provenance.json").read_text(encoding="utf-8"))
    aid = "gen-bench-street-slab-1"
    asset = next(a for a in data["assets"] if a["asset_id"] == aid)
    del asset["geometry_source"]["parameters"]["generation_route"]
    del provenance["assets"][aid]["generation_route"]
    asset["passport"]["provenance"] = copy.deepcopy(asset["geometry_source"])
    (tmp_path / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
    (tmp_path / "provenance.json").write_text(json.dumps(provenance), encoding="utf-8")
    result = source_doc.build_register(tmp_path)
    assert any(e.startswith(f"{aid}: missing recorded fields: prompt") and "image_generation_id" in e
               for e in result["errors"])


@pytest.mark.parametrize("name", PROCEDURAL)
def test_procedural_kits_record_their_scripts_and_exclusions(name):
    batch = BATCHES[name]
    assert batch["rights"].count("2026-11-20") >= 1 and "CC BY 4.0" in batch["rights"]
    assert batch["origin"]["excluded"] and batch["estimated_credits"] == 0
    for path, script in batch["generator"]["scripts"].items():
        kept = LIBRARY / "batches" / name / script["retained_as"]
        assert hashlib.sha256(kept.read_bytes()).hexdigest() == script["retained_sha256"]
        assert script["authoring"]["basis"] and ("sessions" in script["authoring"])
        if script.get("redact_local_paths"):
            assert script["retained_sha256"] != script["sha256"] and script["redaction_note"]
    for brief in batch["assets"]:
        assert brief["generator_script"] in batch["generator"]["scripts"]
        assert brief["kit_record"] in batch["generator"]["kit_records"]


def test_concept_conditioned_references_name_their_concept_image():
    """refset_1007 reference images took a session-generated concept image as their only media reference."""
    repo = AssetRepository()
    for brief in BATCHES["ginkgo-refset-1007"]["assets"]:
        image = repo.records[brief["asset_id"]]["provenance"]["recorded_generation"]["captured_generation"]["image"]
        concept = image["concept_reference"]
        assert [m["value"] for m in image["request"]["medias"]] == [concept["job_id"]]
        assert len(concept["sha256"]) == 64 and concept["retained"] is False and concept["prompt"]
        assert not (LIBRARY / "batches/ginkgo-refset-1007" / concept["name"]).exists()


def test_refine_without_model_records_the_gap():
    """The Lausanne refine request named no ai_model: the record says so instead of guessing a model."""
    repo = AssetRepository()
    generation = repo.records["gen-dress-form-mannequin-1"]["provenance"]["recorded_generation"]
    mesh = generation["captured_generation"]["mesh"]
    assert "ai_model" not in mesh["request"]
    assert generation["mesh_model"] == mesh["provider_model"] and generation["mesh_model"].startswith("unspecified")
