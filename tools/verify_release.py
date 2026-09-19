"""Verify a built wheel's contents and complete offline generated asset pack."""
import argparse
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


def verify(wheel: Path) -> dict:
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        forbidden = []
        for name in names:
            path = Path(name)
            if (path.is_absolute() or ".." in path.parts
                    or path.suffix.lower() in {".skp", ".3dm", ".gh", ".ghx", ".gha", ".dll", ".pdb", ".sqlite3"}
                    or "/IkeaFurniturefiles/" in name
                    or "/raw/" in name or "/examples/" in name
                    or any(f"/{lib}/models/" in name for lib in ("IkeaFurniturefiles", "DrawingAssetfiles", "DiagramAssetfiles"))):
                forbidden.append(name)
        if forbidden:
            raise ValueError(f"Forbidden archive members: {forbidden}")
        prefix = "almond_mcp/data/GeneratedAssetfiles/"
        glbs = [n for n in names if n.endswith(".glb")]
        if len(glbs) != 47 or any(not n.startswith(prefix + "models/") for n in glbs):
            raise ValueError("Wheel must contain exactly the 47 generated GLBs")
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
            if counts != {"assets":54, "models":47, "elements":7, "drawing_packages":10, "views":60}:
                raise ValueError(f"Unified archive coverage changed: {counts}")
            for filename in ("index.html", "style.css", "app.js", "karamba.js", "analysis-view.mjs", "favicon.svg", "vendor/model-viewer.min.js", "vendor/LICENSE", "vendor/THIRD-PARTY-LICENSES.txt", "vendor/version.json"):
                if "almond_mcp/library_ui/" + filename not in names:
                    raise ValueError(f"Archive UI file missing: {filename}")
            if any(a["available"] for a in archive_catalogue.records.values() if a["kind"] == "element"):
                raise ValueError("Downloaded drawing files must not enter the distribution")
            result["object_archive"] = counts
            result["object_archive_ui"] = "packaged, including offline viewer and licence"
    result.update(wheel=wheel.name, wheel_size_mb=round(wheel.stat().st_size / 1_000_000, 2),
                  distribution_check="no third-party model binaries, raw downloads or example projects")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args()
    result = verify(args.wheel)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["status"] == "success" else 1)
