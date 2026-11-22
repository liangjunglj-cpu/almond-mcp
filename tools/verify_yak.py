"""Audit a Yak release without installing it or modifying Rhino."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from almond_mcp import __version__

# Exact runtime files per Yak platform. Windows ships the net48 build with the .NET Framework polyfills Roslyn
# needs; macOS ships the net7.0 build, whose runtime already contains them.
RUNTIME_WIN = {"RhinoAlmondBridge.rhp", "Microsoft.CodeAnalysis.CSharp.dll", "Microsoft.CodeAnalysis.dll",
               "Newtonsoft.Json.dll", "System.Buffers.dll", "System.Collections.Immutable.dll", "System.Memory.dll",
               "System.Numerics.Vectors.dll", "System.Reflection.Metadata.dll",
               "System.Runtime.CompilerServices.Unsafe.dll", "System.Text.Encoding.CodePages.dll",
               "System.Threading.Tasks.Extensions.dll"}
RUNTIME_MAC = {"RhinoAlmondBridge.rhp", "Microsoft.CodeAnalysis.CSharp.dll", "Microsoft.CodeAnalysis.dll",
               "Newtonsoft.Json.dll"}
PLATFORMS = {
    # platform tag: (runtime files, TargetFrameworkAttribute the plug-in must be compiled for)
    "win": (RUNTIME_WIN, b".NETFramework,Version=v4.8"),
    "mac": (RUNTIME_MAC, b".NETCoreApp,Version=v7.0"),
}


def verify(path):
    version = ET.parse(ROOT/"RhinoAlmondBridge/RhinoAlmondBridge.csproj").findtext("PropertyGroup/Version")
    match = re.fullmatch(rf"almondbridge-{re.escape(version)}-rh8_0-(win|mac)\.yak", path.name)
    if not match:
        raise ValueError("Incorrect Yak version or Rhino/platform compatibility tag")
    platform = match.group(1)
    runtime, framework = PLATFORMS[platform]
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate zip members")
        for name in names:
            p = PurePosixPath(name)
            if p.is_absolute() or ".." in p.parts or "\\" in name:
                raise ValueError(f"Unsafe member: {name}")
            if p.suffix.lower() in {".rhp", ".dll"} and name not in runtime:
                raise ValueError(f"Unexpected executable: {name}")
            if p.suffix.lower() in {".skp", ".3dm", ".gh", ".ghx", ".gha", ".sqlite3", ".exe", ".py", ".ps1"}:
                raise ValueError(f"Forbidden member: {name}")
            if "/files/drawing/" in name or "/raw/" in name:
                raise ValueError(f"Community or raw model included: {name}")
        for name in runtime | {"manifest.yml", "LICENSE", "THIRD-PARTY-NOTICES.md", "GETTING-STARTED.md", "archive/ATTRIBUTION.txt", "archive/ui/vendor/LICENSE", "archive/ui/vendor/THIRD-PARTY-LICENSES.txt"}:
            if name not in names:
                raise ValueError(f"Missing package file: {name}")
        if framework not in archive.read("RhinoAlmondBridge.rhp"):
            raise ValueError(f"RhinoAlmondBridge.rhp is not the {framework.decode()} build the {platform} package needs")
        manifest = archive.read("manifest.yml").decode("utf-8-sig")
        if f"version: {version}" not in manifest or "name: almondbridge" not in manifest:
            raise ValueError("Yak manifest version/name mismatch")
        bundle = json.loads(archive.read("archive/bundle.json"))
        if bundle["version"] != __version__:
            raise ValueError("Python/archive version mismatch")
        for route, record in bundle["routes"].items():
            member = "archive/" + record["path"]
            if ".." in PurePosixPath(record["path"]).parts or record["path"].startswith("/"):
                raise ValueError("Unsafe route target")
            if hashlib.sha256(archive.read(member)).hexdigest() != record["sha256"]:
                raise ValueError(f"Checksum mismatch: {route}")
        catalogue = json.loads(archive.read("archive/api/catalogue.json"))
        counts = catalogue["counts"]
        if counts != {"assets":151,"models":144,"elements":7,"drawing_packages":10,"views":60}:
            raise ValueError(f"Unexpected catalogue: {counts}")
        glbs = [n for n in names if n.endswith(".glb")]
        if len(glbs) != 144 or any(not n.startswith("archive/files/generated/models/") for n in glbs):
            raise ValueError("Generated-model pack is incomplete")
        evidence = json.loads(archive.read("archive/evidence/source-register.json"))
        sources = {a["asset_id"]:a for a in evidence["assets"]}
        for record in catalogue["assets"]:
            if record["kind"] == "element":
                if record["available"] or record["model"] or record["preview"]:
                    raise ValueError("Community model exposed by distributed catalogue")
                continue
            model = archive.read("archive/" + bundle["routes"][record["model"]]["path"])
            if hashlib.sha256(model).hexdigest().upper() != sources[record["id"]]["model_sha256"]:
                raise ValueError("Source evidence does not match bundled model")
            captured = sources[record["id"]]["recorded_generation"].get("captured_generation")
            route = captured.get("route") if captured else None
            if route in ("meshy_text_to_3d", "procedural_script"):
                # No image stage on these routes: nothing may claim one. Procedural pieces ship their retained
                # generator script and kit record as evidence, which must still hash to the recorded values.
                if captured.get("input_image_file") is not None or "image" in captured or record.get("generation_image"):
                    raise ValueError(f"{route} record claims an input image: {record['id']}")
                if route == "procedural_script":
                    for entry in (captured["generator"]["script"], captured["generator"]["kit_record"]):
                        member = "archive/evidence/" + entry["retained_file"]
                        if member not in names or hashlib.sha256(archive.read(member)).hexdigest() != entry["retained_sha256"]:
                            raise ValueError(f"Procedural evidence is missing or changed: {entry['retained_file']}")
            elif captured:
                # The retained image is the one the mesh stage received (a locally edited upload differs from the
                # generator's output and records that output's hash separately).
                image_path = "archive/" + bundle["routes"][record["generation_image"]]["path"]
                expected = captured["mesh"].get("input_image_sha256", captured["image"]["output_sha256"])
                if hashlib.sha256(archive.read(image_path)).hexdigest() != expected:
                    raise ValueError("Captured generation image is missing or changed")
            if record["drawing"]:
                drawing_path = "archive/" + bundle["routes"][record["drawing"]["record"]]["path"]
                drawing = json.loads(archive.read(drawing_path))
                for filename, expected in drawing["files"].items():
                    if PurePosixPath(filename).name != filename:
                        raise ValueError("Unsafe drawing member")
                    payload = archive.read(str(PurePosixPath(drawing_path).parent / filename))
                    if hashlib.sha256(payload).hexdigest().upper() != expected:
                        raise ValueError("Drawing package is stale or incomplete")
    return {"status":"success", "yak":path.name,"platform":platform,"target_framework":framework.decode(),
            "bridge_version":version,"archive_version":__version__,
            "counts":counts,"routes_checked":len(bundle["routes"]),"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
            "size_mb":round(path.stat().st_size/1e6,2), "rhino_in_process_smoke":"pending"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package",type=Path)
    parser.add_argument("--report",type=Path)
    args=parser.parse_args()
    report=verify(args.package)
    if args.report: args.report.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,indent=2))
