"""Ginkgo batches staged with tools/stage_ginkgo_chains.py: mesh bank, Freiburg and refset_1118.

Each batch has a different image stage and link to the mesh stage; the evidence must keep every link checkable.
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
           for name in ("ginkgo-meshbank-2026-11", "ginkgo-freiburg-2026-11", "ginkgo-refset-1118")}
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
        image, mesh, derivation = captured["image"], captured["mesh"], captured["derivation"]
        assert image["request"]["prompt"] == brief["prompt"] == generation["prompt"]
        assert image["task_id"] == brief["image_job_id"] and mesh["task_id"] == brief["mesh_task_id"]
        link = mesh["input_link"]
        if link == "input_task_id":
            assert mesh["request"]["input_task_id"] == image["task_id"]
        elif link == "media_job_id":
            assert [m["value"] for m in mesh["request"]["medias"]] == [image["task_id"]]
            assert mesh["request"]["model"] == "tripo_h3_1_image_to_3d"
            assert record["provenance"]["generator"] == "tripo" and "tripo" in records[brief["asset_id"]]["tags"]
        else:
            assert link == "upload" and "input_task_id" not in mesh["request"]
            assert mesh["request"]["image"].startswith("local upload of ")
        assert mesh["input_image_sha256"] == image["output_sha256"]
        retained = repo.files[record["generation_image"]][1]
        assert hashlib.sha256(retained.read_bytes()).hexdigest() == image["output_sha256"]
        assert derivation["source_sha256"] == mesh["output_sha256"]
        q = derivation["quality"]
        assert q["triangles"] <= brief["target_triangles"] + 100
        assert not q["nonfinite_coordinates"] and not q["zero_area_faces"]
        assert not q["nonmanifold_edges_excluding_boundary"]
        assert derivation["method"].startswith("Remove provider PBR materials")
        assert captured["origin"]["source_name"] == brief["ginkgo_name"]
        assert not any(s in json.dumps(captured) for s in ("cloudfront", "assets.meshy", ":\\\\", "Users/", "user_"))
        asset = records[brief["asset_id"]]
        assert asset["dimensions_mm"]["height"] == brief["height_mm"]
        assert asset["render_material_id"] == brief["material"]
        assert asset["spatial"]["support_plane"] == brief["support_plane"]
        assert asset["spatial"].get("mount_height_mm") == brief.get("mount_height_mm")


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
