"""Verify a built wheel's contents and complete offline generated asset pack."""
import argparse
import hashlib
import json
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from almond_mcp.asset_passport import audit_library
from almond_mcp.drafting import audit_package
from almond_mcp.asset_repository import AssetRepository


def _verify_parametric(library: Path, names: list[str], prefix: str) -> int:
    """Every packaged teaching definition matches its register hash and carries its licence."""
    catalogue = json.loads((library / "catalogue.json").read_text(encoding="utf-8"))["entries"]
    register = {i["id"]: i for i in json.loads((library / "source-register.json").read_text(encoding="utf-8"))["items"]}
    packaged = sorted(n for n in names if n.startswith(prefix + "definitions/"))
    expected = sorted(prefix + e["definition"] for e in catalogue)
    if packaged != expected or set(register) != {e["id"] for e in catalogue}:
        raise ValueError("Parametric definitions do not match the catalogue and source register")
    for entry in catalogue:
        item = register[entry["id"]]
        digest = hashlib.sha256((library / entry["definition"]).read_bytes()).hexdigest()
        if digest != item["derivation"][-1]["output_sha256"]:
            raise ValueError(f"Parametric definition changed after registration: {entry['id']}")
        licence = library / item["rights"]["licence_file"]
        if not licence.is_file() or not (library / entry["preview"]).is_file() or not (library / entry["lesson"]).is_file():
            raise ValueError(f"Parametric licence, preview or lesson missing: {entry['id']}")
        if item["rights"]["licence"] not in {"MIT", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0", "BlueOak-1.0.0",
                                             "CC0-1.0", "CC-BY-4.0", "BSL-1.0"}:
            raise ValueError(f"Parametric definition is not permissively licensed: {entry['id']}")
    # Harnessed capsules: the teaching file plus ALMOND_* sockets, registered as their own derivation.
    capsules = [e for e in catalogue if e.get("capsule")]
    packaged_capsules = sorted(n for n in names if n.startswith(prefix + "capsules/") and n.endswith(".ghx"))
    if packaged_capsules != sorted(prefix + e["capsule"]["definition"] for e in capsules):
        raise ValueError("Harnessed capsule definitions do not match the catalogue")
    for entry in capsules:
        harnessed = register[entry["id"]].get("harnessed")
        if not harnessed or harnessed["capsule_id"] != entry["capsule"]["capsule_id"]:
            raise ValueError(f"Harnessed capsule is not in the source register: {entry['id']}")
        for key, rel in (("output_sha256", entry["capsule"]["definition"]), ("manifest_sha256", entry["capsule"]["manifest"])):
            if hashlib.sha256((library / rel).read_bytes()).hexdigest() != harnessed["derivation"][key]:
                raise ValueError(f"Harnessed capsule changed after registration: {entry['id']}")
        manifest = json.loads((library / entry["capsule"]["manifest"]).read_text(encoding="utf-8"))
        if manifest["audited"] != harnessed["audited"] or not harnessed["derivation"]["logic_fingerprint_unchanged_after_mapping"]:
            raise ValueError(f"Harnessed capsule audit state or logic check does not match the register: {entry['id']}")
    return len(catalogue)


def verify(wheel: Path) -> dict:
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        forbidden = []
        parametric = "almond_mcp/data/ParametricLibrary/"
        for name in names:
            path = Path(name)
            # Adapted, register-checked teaching definitions (and their harnessed capsules) are the only
            # Grasshopper files allowed.
            parametric_definition = (name.startswith((parametric + "definitions/", parametric + "capsules/"))
                                     and path.suffix.lower() == ".ghx")
            if (path.is_absolute() or ".." in path.parts
                    or (path.suffix.lower() in {".skp", ".3dm", ".gh", ".ghx", ".gha", ".dll", ".pdb", ".sqlite3"}
                        and not parametric_definition)
                    or name.startswith(parametric + "upstream/")
                    or "/IkeaFurniturefiles/" in name
                    or "/raw/" in name or "/examples/" in name
                    or any(f"/{lib}/models/" in name for lib in ("IkeaFurniturefiles", "DrawingAssetfiles", "DiagramAssetfiles"))):
                forbidden.append(name)
        if forbidden:
            raise ValueError(f"Forbidden archive members: {forbidden}")
        prefix = "almond_mcp/data/GeneratedAssetfiles/"
        if prefix + "previews/render-record.json" not in names:
            raise ValueError("Preview derivation record missing")
        glbs = [n for n in names if n.endswith(".glb")]
        if len(glbs) != 50 or any(not n.startswith(prefix + "models/") for n in glbs):
            raise ValueError("Wheel must contain exactly the 50 generated GLBs")
        with tempfile.TemporaryDirectory(prefix="almond-release-audit-") as tmp:
            archive.extractall(tmp)
            result = audit_library(Path(tmp) / prefix)
            generated = Path(tmp) / prefix
            sources = json.loads((generated / "source-register.json").read_text())
            assets = {a["asset_id"]: a for a in json.loads((generated / "manifest.json").read_text())["assets"]}
            if sources["errors"] or len(sources["assets"]) != len(assets):
                raise ValueError("Source register has errors or incomplete coverage")
            for record in sources["assets"]:
                if record["model_sha256"] != assets[record["asset_id"]]["sha256"]:
                    raise ValueError("Source register does not match packaged models")
                captured = record["recorded_generation"].get("captured_generation")
                if captured:
                    source_image = (generated / captured["input_image_file"]).resolve()
                    if not source_image.is_relative_to(generated.resolve()) or hashlib.sha256(source_image.read_bytes()).hexdigest() != captured["image"]["output_sha256"]:
                        raise ValueError("Captured generation image is missing or changed")
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
            if counts != {"assets":57, "models":50, "elements":7, "drawing_packages":10, "views":60}:
                raise ValueError(f"Unified archive coverage changed: {counts}")
            for filename in ("index.html", "style.css", "app.js", "karamba.js", "karamba-help.js", "panel-theme.js", "panel.css", "analysis-view.mjs", "environment.js", "environment.css", "favicon.svg", "vendor/model-viewer.min.js", "vendor/LICENSE", "vendor/THIRD-PARTY-LICENSES.txt", "vendor/version.json"):
                if "almond_mcp/library_ui/" + filename not in names:
                    raise ValueError(f"Archive UI file missing: {filename}")
            if any(a["available"] for a in archive_catalogue.records.values() if a["kind"] == "element"):
                raise ValueError("Downloaded drawing files must not enter the distribution")
            result["object_archive"] = counts
            result["parametric_definitions_checked"] = _verify_parametric(Path(tmp) / parametric, names, parametric)
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
                  distribution_check="no third-party model binaries, raw downloads or example projects; Grasshopper files only as "
                                     "register-checked, permissively licensed teaching definitions and their harnessed capsules")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args()
    result = verify(args.wheel)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["status"] == "success" else 1)
