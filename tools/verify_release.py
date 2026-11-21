"""Verify a built wheel's contents and the generated asset pack it downloads.

The wheel carries the generated library's manifest, catalogue and previews but
no model files: those are GitHub release assets (see almond_mcp/model_store.py).
Every manifest GLB and contract must be in the sdist (or this checkout) with a
matching sha256, and --stage-models copies them out for the release upload.
"""
import argparse
import hashlib
import json
import shutil
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from almond_mcp.asset_passport import audit_library
from almond_mcp.drafting import audit_package
from almond_mcp.asset_repository import AssetRepository


def _evidence_root(sdist: Path | None, tmp: str) -> Path:
    """GeneratedAssetfiles directory that holds batches/ and models/ (neither is in the wheel)."""
    if sdist is None:
        return REPO / "GeneratedAssetfiles"
    with tarfile.open(sdist) as tar:
        members = [m for m in tar.getmembers()
                   if ("/GeneratedAssetfiles/batches/" in m.name or "/GeneratedAssetfiles/models/" in m.name)
                   and m.isfile() and not Path(m.name).is_absolute() and ".." not in Path(m.name).parts]
        if not any("/GeneratedAssetfiles/batches/" in m.name for m in members):
            raise ValueError("Source distribution has no GeneratedAssetfiles/batches evidence")
        tar.extractall(tmp, members=members, filter="data")
        top = members[0].name.split("/", 1)[0]
    return Path(tmp) / top / "GeneratedAssetfiles"


def release_model_files(source: Path, manifest: dict) -> list[Path]:
    """Every manifest GLB + contract under *source*, sha256-checked against the
    manifest: the files attached to the GitHub release that installs download."""
    files = []
    for asset in manifest["assets"]:
        for rel, expected in ((asset["file"], asset["sha256"]),
                              (asset["contract_file"], asset["contract_sha256"])):
            path = (source / rel).resolve()
            if not path.is_relative_to(source.resolve()) or not path.is_file():
                raise ValueError(f"Release model file missing from the source distribution: {rel}")
            if hashlib.sha256(path.read_bytes()).hexdigest().upper() != expected.upper():
                raise ValueError(f"Release model file does not match the manifest sha256: {rel}")
            files.append(path)
    names = [f.name for f in files]
    if len(set(names)) != len(names):
        raise ValueError("Release asset names must be unique (GitHub release assets are flat)")
    return files


def verify(wheel: Path, sdist: Path | None = None, stage_models: Path | None = None) -> dict:
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        forbidden = []
        for name in names:
            path = Path(name)
            if (path.is_absolute() or ".." in path.parts
                    or path.suffix.lower() in {".skp", ".3dm", ".gh", ".ghx", ".gha", ".dll", ".pdb", ".sqlite3"}
                    or "/IkeaFurniturefiles/" in name
                    or "/GeneratedAssetfiles/batches/" in name
                    or "/raw/" in name or "/examples/" in name
                    or any(f"/{lib}/models/" in name for lib in ("IkeaFurniturefiles", "DrawingAssetfiles", "DiagramAssetfiles"))):
                forbidden.append(name)
        if forbidden:
            raise ValueError(f"Forbidden archive members: {forbidden}")
        prefix = "almond_mcp/data/GeneratedAssetfiles/"
        if prefix + "previews/render-record.json" not in names:
            raise ValueError("Preview derivation record missing")
        model_files = [n for n in names if n.endswith((".glb", ".almond.json")) or n.startswith(prefix + "models/")]
        if model_files:
            raise ValueError(f"Wheel must contain no generated model files (they are release assets): {model_files[:5]}")
        for filename in ("manifest.json", "catalogue.json", "provenance.json", "source-register.json",
                         "structural-loads.json", "passport.schema.json", "README.md"):
            if prefix + filename not in names:
                raise ValueError(f"Generated library file missing from the wheel: {filename}")
        with tempfile.TemporaryDirectory(prefix="almond-release-audit-") as tmp, \
                tempfile.TemporaryDirectory(prefix="almond-release-evidence-") as evidence_tmp:
            archive.extractall(tmp)
            generated = Path(tmp) / prefix
            evidence = _evidence_root(sdist, evidence_tmp)
            manifest = json.loads((generated / "manifest.json").read_text())
            missing_previews = [a["asset_id"] for a in manifest["assets"]
                                if prefix + f"previews/{a['asset_id']}.png" not in names]
            if missing_previews:
                raise ValueError(f"Wheel previews missing: {missing_previews}")
            # The installed library = wheel data + the release's model files: audit them together.
            release_files = release_model_files(evidence, manifest)
            for path in release_files:
                target = generated / path.relative_to(evidence.resolve())
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
            if stage_models is not None:
                stage_models.mkdir(parents=True, exist_ok=True)
                if any(stage_models.iterdir()):
                    raise ValueError(f"Model staging directory must be new or empty: {stage_models}")
                for path in release_files:
                    shutil.copy2(path, stage_models / path.name)
            result = audit_library(generated)
            result["release_model_files"] = len(release_files)
            result["release_model_bytes"] = sum(p.stat().st_size for p in release_files)
            if stage_models is not None:
                result["release_models_staged_in"] = str(stage_models)
            images_checked = text_to_3d_checked = procedural_checked = 0
            sources = json.loads((generated / "source-register.json").read_text())
            assets = {a["asset_id"]: a for a in manifest["assets"]}
            if sources["errors"] or len(sources["assets"]) != len(assets):
                raise ValueError("Source register has errors or incomplete coverage")
            for record in sources["assets"]:
                if record["model_sha256"] != assets[record["asset_id"]]["sha256"]:
                    raise ValueError("Source register does not match packaged models")
                captured = record["recorded_generation"].get("captured_generation")
                if captured and captured.get("route") == "meshy_text_to_3d":
                    # Text-to-3D has no image stage: nothing to retain, and nothing may claim one.
                    if captured.get("input_image_file") is not None or "image" in captured:
                        raise ValueError(f"Text-to-3D record claims an input image: {record['asset_id']}")
                    text_to_3d_checked += 1
                elif captured and captured.get("route") == "procedural_script":
                    # Blender-script geometry: no image stage; the retained script text and kit record must ship
                    # with the evidence and still hash to the recorded values.
                    if captured.get("input_image_file") is not None or "image" in captured:
                        raise ValueError(f"Procedural record claims an input image: {record['asset_id']}")
                    for entry, expected in ((captured["generator"]["script"], captured["generator"]["script"]["retained_sha256"]),
                                            (captured["generator"]["kit_record"], captured["generator"]["kit_record"]["retained_sha256"])):
                        kept = (evidence / entry["retained_file"]).resolve()
                        if (not kept.is_relative_to(evidence.resolve()) or not kept.is_file()
                                or hashlib.sha256(kept.read_bytes()).hexdigest() != expected):
                            raise ValueError(f"Procedural evidence is missing or changed: {entry['retained_file']}")
                    procedural_checked += 1
                elif captured:
                    source_image = (evidence / captured["input_image_file"]).resolve()
                    if (not source_image.is_relative_to(evidence.resolve()) or not source_image.is_file()
                            or hashlib.sha256(source_image.read_bytes()).hexdigest() != captured["mesh"].get("input_image_sha256", captured["image"]["output_sha256"])):
                        raise ValueError(f"Captured generation image is missing or changed: {captured['input_image_file']}")
                    images_checked += 1
            result["captured_images_checked"] = images_checked
            result["text_to_3d_records_checked"] = text_to_3d_checked
            result["procedural_records_checked"] = procedural_checked
            result["evidence_checked_in"] = sdist.name if sdist else "repository checkout"
            drafts = Path(tmp) / "almond_mcp/data/Draftingfiles"
            pilot = json.loads((drafts / "manifest.json").read_text())
            drawing_audits = []
            for record in pilot["assets"]:
                package = (drafts / record["package"]).resolve()
                package.relative_to(drafts.resolve())
                audit = audit_package(package, generated / assets[record["asset_id"]]["file"])
                if audit["status"] != "success":
                    raise ValueError(f"Drawing audit failed: {audit}")
                drawing_audits.append(audit)
            result["drawing_packages_checked"] = len(drawing_audits)
            result["drawing_files_checked"] = sum(a["checked_files"] for a in drawing_audits)
            result["source_records_checked"] = len(sources["assets"])
            archive_catalogue = AssetRepository({"generated": generated, "drafting": drafts,
                                                "drawing": Path(tmp) / "almond_mcp/data/DrawingAssetfiles"})
            counts = archive_catalogue.catalogue()["counts"]
            if counts != {"assets":151, "models":144, "elements":7, "drawing_packages":10, "views":60}:
                raise ValueError(f"Unified archive coverage changed: {counts}")
            for filename in ("index.html", "style.css", "app.js", "karamba.js", "karamba-help.js", "panel-theme.js", "panel.css", "analysis-view.mjs", "environment.js", "environment.css", "favicon.svg", "vendor/model-viewer.min.js", "vendor/LICENSE", "vendor/THIRD-PARTY-LICENSES.txt", "vendor/version.json"):
                if "almond_mcp/library_ui/" + filename not in names:
                    raise ValueError(f"Archive UI file missing: {filename}")
            if any(a["available"] for a in archive_catalogue.records.values() if a["kind"] == "element"):
                raise ValueError("Downloaded drawing files must not enter the distribution")
            result["object_archive"] = counts
            result["object_archive_ui"] = "packaged, including offline viewer and licence"
        env = "almond_mcp/environment/data/"
        for filename in ("materials.json", "glazing.json", "assemblies.json", "sources.json", "LICENSES/EnergyPlus.txt",
                         "LICENSES/honeybee-standards.txt", "codes/sg_bca.json", "codes/uk_adl_2021.json"):
            if env + filename not in names:
                raise ValueError(f"Environment data file missing: {filename}")
    # every bundled component and data source under a licence that allows commercial redistribution
    sys.path.insert(0, str(REPO / "tools"))
    from license_scan import scan
    licences = scan()
    if not licences["ok"]:
        raise ValueError(f"Licence scan failed: {licences['denied_or_unknown']}")
    result["licence_scan"] = {"components": len(licences["components"]), "review": [r["component"] for r in licences["review"]]}
    result.update(wheel=wheel.name, wheel_size_mb=round(wheel.stat().st_size / 1_000_000, 2),
                  distribution_check="no third-party model binaries, raw downloads or example projects; "
                                     "no generated model files (release assets)")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    parser.add_argument("--sdist", type=Path, help="source distribution holding the model files and generation evidence (default: this checkout)")
    parser.add_argument("--stage-models", type=Path, help="copy every verified model file (GLB + contract) here, flat, for the GitHub release upload")
    args = parser.parse_args()
    result = verify(args.wheel, args.sdist, args.stage_models)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["status"] == "success" else 1)
