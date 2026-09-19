"""Build the redistributable, read-only archive hosted by the Rhino plugin."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from almond_mcp import __version__
from almond_mcp.asset_repository import AssetRepository, UI_ROOT
from almond_mcp.asset_passport import audit_library
from almond_mcp.drafting import audit_package
from document_generation_sources import build_register


def build_bundle(destination: Path):
    destination = destination.resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Archive destination must be new or empty")
    generated = ROOT / "GeneratedAssetfiles"
    register = build_register(generated)
    if register.get("errors") or register != json.loads((generated/"source-register.json").read_text(encoding="utf-8")):
        raise ValueError("Source register is stale or contains errors")
    audit = audit_library(generated)
    if audit["status"] != "success":
        raise ValueError(f"Generated asset audit failed: {audit}")
    # Never index installed community files into a redistributable payload.
    repo = AssetRepository({"generated":generated, "drawing":ROOT/"DrawingAssetfiles", "drafting":ROOT/"Draftingfiles"})
    for record in repo.records.values():
        if record["kind"] == "element":
            record.update(available=False, model=None, preview=None, contract=None)
        if record["drawing"]:
            package = repo.files[record["drawing"]["record"]][1].parent
            repo.file("drafting", (package / "views.json").relative_to(repo.roots["drafting"]).as_posix())
            result = audit_package(package, repo.files[record["model"]][1])
            if result["status"] != "success":
                raise ValueError(f"Drawing audit failed: {result}")
    destination.mkdir(parents=True, exist_ok=True)
    routes = {}

    def write(route, relative, payload, mime):
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        routes[route] = {"path":relative, "sha256":hashlib.sha256(payload).hexdigest(), "mime":mime}

    for route, (_, path) in repo.files.items():
        if route.startswith("/files/drawing/"):
            continue
        suffix = path.suffix
        mime = {".glb":"model/gltf-binary", ".png":"image/png", ".json":"application/json", ".svg":"image/svg+xml", ".dxf":"application/dxf"}[suffix]
        write(route, unquote(route.lstrip("/")), path.read_bytes(), mime)
    for path in sorted(UI_ROOT.rglob("*")):
        if path.is_file():
            relative = path.relative_to(UI_ROOT).as_posix()
            mime = {".html":"text/html; charset=utf-8", ".css":"text/css; charset=utf-8", ".js":"text/javascript; charset=utf-8", ".json":"application/json", ".svg":"image/svg+xml"}.get(path.suffix,"text/plain; charset=utf-8")
            write("/"+relative, "ui/"+relative, path.read_bytes(), mime)
    routes["/"] = routes["/index.html"]
    write("/api/materials", "api/materials.json", (ROOT/"Materialfiles/manifest.json").read_bytes(), "application/json")
    catalogue = repo.catalogue()
    catalogue["distribution"] = "rhino"
    catalogue["indexed_at"] = "release-build"
    write("/api/catalogue", "api/catalogue.json", json.dumps(catalogue, ensure_ascii=False).encode(), "application/json")
    for record in repo.records.values():
        write(record["record_url"], record["record_url"].lstrip("/"), json.dumps(record, ensure_ascii=False, indent=2).encode(), "application/json")
    for name in ("README.md", "source-register.json", "passport.schema.json", "manifest.json", "catalogue.json", "provenance.json"):
        target = destination / "evidence" / name
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(generated/name,target)
    shutil.copyfile(ROOT/"THIRD-PARTY-NOTICES.md",destination/"THIRD-PARTY-NOTICES.md")
    (destination/"ATTRIBUTION.txt").write_text("Generated 3D models and derived drawings: Almond generated asset library.\nDeclared licence: CC BY 4.0 — https://creativecommons.org/licenses/by/4.0/\nRetain attribution, link the licence, and indicate modifications.\nAlmond code: MIT. Viewer and dependencies: see ui/vendor/ licences.\nGeneration source records and documented gaps: evidence/source-register.json.\nCommunity drawing models are metadata-only here, with separate source terms.\n", encoding="utf-8")
    manifest = {"schema_version":1, "version":__version__, "counts":catalogue["counts"], "routes":routes}
    (destination/"bundle.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8")
    return {"version":__version__, "routes":len(routes), "counts":catalogue["counts"], "directory":str(destination)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(json.dumps(build_bundle(args.destination),indent=2))
