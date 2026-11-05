"""Ginkgo refset_1024 props: an external image stage linked to Meshy by checksum, not by task ID."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

from almond_mcp.asset_loads import LoadTable
from almond_mcp.asset_repository import AssetRepository

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "GeneratedAssetfiles"
BATCH = json.loads((LIBRARY / "batches/ginkgo-refset-1024.json").read_text(encoding="utf-8"))
spec = importlib.util.spec_from_file_location("ginkgo_sources", ROOT / "tools/document_generation_sources.py")
source_doc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(source_doc)


def test_ginkgo_props_keep_their_generation_chain():
    repo = AssetRepository()
    manifest = {a["asset_id"]: a for a in json.loads((LIBRARY / "manifest.json").read_text())["assets"]}
    assert repo.search("ginkgo-refset-1024")["total"] == len(BATCH["release_assets"]) == 16
    for brief in BATCH["assets"]:
        record = repo.records[brief["asset_id"]]
        generation = record["provenance"]["recorded_generation"]
        captured = generation["captured_generation"]
        image, mesh, q = captured["image"], captured["mesh"], captured["derivation"]["quality"]
        assert image["provider"] == "higgsfield" and image["request"]["model"] == "gpt_image_2_5"
        assert image["request"]["prompt"] == brief["prompt"] == generation["prompt"]
        assert image["task_id"] == brief["image_job_id"] and mesh["task_id"] == brief["mesh_task_id"]
        assert mesh["request"]["ai_model"] == "meshy-7.1" and "input_task_id" not in mesh["request"]
        assert mesh["input_image_sha256"] == image["output_sha256"]
        retained = repo.files[record["generation_image"]][1]
        assert hashlib.sha256(retained.read_bytes()).hexdigest() == image["output_sha256"]
        assert captured["derivation"]["source_sha256"] == mesh["output_sha256"]
        assert q["triangles"] <= brief["target_triangles"] + 100 <= captured["derivation"]["source_triangles"]
        assert not q["nonfinite_coordinates"] and not q["zero_area_faces"]
        assert not q["nonmanifold_edges_excluding_boundary"]
        assert max(q["bounds_relative_change"]) < 0.02
        assert captured["derivation"]["method"].startswith("Remove provider PBR materials")
        assert captured["origin"]["source_name"] == brief["ginkgo_name"]
        assert not any(s in json.dumps(captured) for s in ("cloudfront", ":\\\\", "Users/", "user_"))
        asset = manifest[brief["asset_id"]]
        assert asset["dimensions_mm"]["height"] == brief["height_mm"]
        assert asset["render_material_id"] == brief["material"]
        assert asset["spatial"]["support_plane"] == brief["support_plane"]
        assert asset["spatial"].get("mount_height_mm") == brief.get("mount_height_mm")


def test_ginkgo_props_have_loads_and_rooms():
    table = LoadTable(LIBRARY / "structural-loads.json")
    manifest = {a["asset_id"]: a for a in json.loads((LIBRARY / "manifest.json").read_text())["assets"]}
    for aid in BATCH["release_assets"]:
        asset = manifest[aid]
        assert table.lookup(aid, asset["category"])
        if asset["category"] in ("building_services", "household"):
            assert asset["passport"]["usage"]["suggested_rooms"]


def test_source_audit_rejects_unlinked_uploaded_image(tmp_path):
    for name in ("catalogue.json", "provenance.json"):
        shutil.copyfile(LIBRARY / name, tmp_path / name)
    shutil.copytree(LIBRARY / "batches", tmp_path / "batches")
    manifest = json.loads((LIBRARY / "manifest.json").read_text(encoding="utf-8"))
    provenance = json.loads((tmp_path / "provenance.json").read_text(encoding="utf-8"))
    aid = BATCH["release_assets"][0]
    asset = next(a for a in manifest["assets"] if a["asset_id"] == aid)
    for captured in (asset["geometry_source"]["parameters"]["captured_generation"],
                     provenance["assets"][aid]["captured_generation"]):
        captured["mesh"]["input_image_sha256"] = "0" * 64
    asset["passport"]["provenance"] = copy.deepcopy(asset["geometry_source"])
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "provenance.json").write_text(json.dumps(provenance), encoding="utf-8")
    result = source_doc.build_register(tmp_path)
    assert f"{aid}: captured task chain differs" in result["errors"]
