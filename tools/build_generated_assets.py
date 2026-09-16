"""Normalise Meshy-generated GLBs into the Almond generated-asset library.

Input:  GeneratedAssetfiles/catalogue.json   (what to make: prompts, nominal
                                              dimensions, spatial contract)
        GeneratedAssetfiles/provenance.json  (Meshy task ids per asset)
        GeneratedAssetfiles/raw/<asset_id>.glb (raw Meshy download)
Output: GeneratedAssetfiles/models/<asset_id>.glb          normalised mesh
        GeneratedAssetfiles/models/<asset_id>.almond.json  asset contract
        GeneratedAssetfiles/manifest.json                  library manifest

Per asset the script:
  1. parses the GLB and measures the world-space bounding box (glTF is
     Y-up; accessor min/max are transformed through the node hierarchy);
  2. optionally rotates 90 degrees about the vertical axis when the model's
     long plan axis disagrees with the catalogue's width/depth convention;
  3. scales uniformly so the height equals the catalogue height, and moves
     bottom-centre onto the origin, by inserting one root node;
  4. renames every material to ALMOND::<render_material_id> with the
     library base colour, so import_asset_contract restores the canonical
     Almond material and metadata in Rhino;
  5. records the *measured* dimensions (never the nominal ones) so that
     search filters and layout validation see the real geometry.

Pure standard library - no numpy, no trimesh - so it runs anywhere the
server runs.  Run:  python tools/build_generated_assets.py [--only id ...]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import math
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from almond_mcp import exchange  # noqa: E402

LIBRARY_DIR = REPO / "GeneratedAssetfiles"
MATERIAL_MANIFEST = REPO / "Materialfiles" / "manifest.json"

GLB_MAGIC = 0x46546C67
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN = 0x004E4942

# Where fetch-assets downloads the models from on a wheel install (the
# manifest ships in the wheel; the GLBs live in the git repository).
RAW_BASE = "https://raw.githubusercontent.com/liangjunglj-cpu/almond-mcp/master/GeneratedAssetfiles"

ASSET_LICENSE = "CC-BY-4.0"
ASSET_LICENSE_NOTE = (
    "Generated with Meshy (meshy.ai) on a paid plan, whose terms assign the "
    "output to the generating account; released under CC BY 4.0. Attribute "
    "'Almond generated asset library'."
)

# ── GLB container ────────────────────────────────────────────────────────────

def read_glb(path: Path) -> tuple[dict, bytes]:
    data = path.read_bytes()
    magic, version, length = struct.unpack_from("<III", data, 0)
    if magic != GLB_MAGIC or version != 2:
        raise ValueError(f"{path.name}: not a glTF 2.0 binary")
    offset = 12
    gltf: dict | None = None
    binary = b""
    while offset < length:
        chunk_len, chunk_type = struct.unpack_from("<II", data, offset)
        payload = data[offset + 8: offset + 8 + chunk_len]
        if chunk_type == CHUNK_JSON:
            gltf = json.loads(payload.decode("utf-8"))
        elif chunk_type == CHUNK_BIN:
            binary = bytes(payload)
        offset += 8 + chunk_len
    if gltf is None:
        raise ValueError(f"{path.name}: no JSON chunk")
    return gltf, binary


def write_glb(path: Path, gltf: dict, binary: bytes) -> None:
    json_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    json_bytes += b" " * (-len(json_bytes) % 4)
    bin_bytes = binary + b"\0" * (-len(binary) % 4)
    total = 12 + 8 + len(json_bytes) + (8 + len(bin_bytes) if bin_bytes else 0)
    with path.open("wb") as handle:
        handle.write(struct.pack("<III", GLB_MAGIC, 2, total))
        handle.write(struct.pack("<II", len(json_bytes), CHUNK_JSON))
        handle.write(json_bytes)
        if bin_bytes:
            handle.write(struct.pack("<II", len(bin_bytes), CHUNK_BIN))
            handle.write(bin_bytes)


# ── small matrix helpers (row-major 4x4 lists) ──────────────────────────────

def identity() -> list[list[float]]:
    return [[1.0 if r == c else 0.0 for c in range(4)] for r in range(4)]


def matmul(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    return [[sum(a[r][k] * b[k][c] for k in range(4)) for c in range(4)] for r in range(4)]


def transform_point(m: list[list[float]], p: list[float]) -> list[float]:
    x, y, z = p
    return [m[r][0] * x + m[r][1] * y + m[r][2] * z + m[r][3] for r in range(3)]


def from_column_major(values: list[float]) -> list[list[float]]:
    return [[values[c * 4 + r] for c in range(4)] for r in range(4)]


def quat_to_matrix(q: list[float]) -> list[list[float]]:
    x, y, z, w = q
    m = identity()
    m[0][0] = 1 - 2 * (y * y + z * z)
    m[0][1] = 2 * (x * y - z * w)
    m[0][2] = 2 * (x * z + y * w)
    m[1][0] = 2 * (x * y + z * w)
    m[1][1] = 1 - 2 * (x * x + z * z)
    m[1][2] = 2 * (y * z - x * w)
    m[2][0] = 2 * (x * z - y * w)
    m[2][1] = 2 * (y * z + x * w)
    m[2][2] = 1 - 2 * (x * x + y * y)
    return m


def node_local_matrix(node: dict) -> list[list[float]]:
    if "matrix" in node:
        return from_column_major([float(v) for v in node["matrix"]])
    t = node.get("translation", [0, 0, 0])
    r = node.get("rotation", [0, 0, 0, 1])
    s = node.get("scale", [1, 1, 1])
    m = quat_to_matrix([float(v) for v in r])
    for row in range(3):
        for col in range(3):
            m[row][col] *= float(s[col])
        m[row][3] = float(t[row])
    return m


# ── geometry measurement ────────────────────────────────────────────────────

def accessor_bounds(gltf: dict, binary: bytes, index: int) -> tuple[list[float], list[float]]:
    accessor = gltf["accessors"][index]
    if "min" in accessor and "max" in accessor:
        return [float(v) for v in accessor["min"]], [float(v) for v in accessor["max"]]
    # Fallback: decode float VEC3 positions from the buffer.
    if accessor.get("componentType") != 5126 or accessor.get("type") != "VEC3":
        raise ValueError("POSITION accessor without min/max and not float VEC3")
    view = gltf["bufferViews"][accessor["bufferView"]]
    stride = view.get("byteStride", 12)
    start = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    lo = [math.inf] * 3
    hi = [-math.inf] * 3
    for i in range(accessor["count"]):
        x, y, z = struct.unpack_from("<fff", binary, start + i * stride)
        for axis, value in enumerate((x, y, z)):
            lo[axis] = min(lo[axis], value)
            hi[axis] = max(hi[axis], value)
    return lo, hi


def world_bounds(gltf: dict, binary: bytes, pre: list[list[float]] | None = None
                 ) -> tuple[list[float], list[float], int]:
    """AABB of every mesh in the default scene, after an optional extra
    transform ``pre`` applied above the scene roots. Returns (min, max, tris)."""
    lo = [math.inf] * 3
    hi = [-math.inf] * 3
    tris = 0
    scene = gltf.get("scenes", [{}])[gltf.get("scene", 0)]
    stack = [(n, pre or identity()) for n in scene.get("nodes", [])]
    while stack:
        node_index, parent = stack.pop()
        node = gltf["nodes"][node_index]
        world = matmul(parent, node_local_matrix(node))
        if "mesh" in node:
            for prim in gltf["meshes"][node["mesh"]].get("primitives", []):
                pos = prim.get("attributes", {}).get("POSITION")
                if pos is None:
                    continue
                pmin, pmax = accessor_bounds(gltf, binary, pos)
                for corner in range(8):
                    p = [pmax[a] if corner >> a & 1 else pmin[a] for a in range(3)]
                    w = transform_point(world, p)
                    for a in range(3):
                        lo[a] = min(lo[a], w[a])
                        hi[a] = max(hi[a], w[a])
                if "indices" in prim:
                    tris += gltf["accessors"][prim["indices"]]["count"] // 3
                else:
                    tris += gltf["accessors"][pos]["count"] // 3
        stack.extend((c, world) for c in node.get("children", []))
    if lo[0] is math.inf:
        raise ValueError("GLB contains no positioned meshes")
    return lo, hi, tris


# ── normalisation ───────────────────────────────────────────────────────────

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def load_material_colours() -> dict[str, dict]:
    if not MATERIAL_MANIFEST.is_file():
        return {}
    manifest = json.loads(MATERIAL_MANIFEST.read_text(encoding="utf-8"))
    return {m["material_id"]: m for m in manifest.get("materials", [])}


def normalise(asset: dict, raw_path: Path, out_dir: Path, materials: dict[str, dict],
              provenance: dict) -> dict:
    gltf, binary = read_glb(raw_path)
    nominal = asset["dimensions_mm"]

    # 1. measure as generated (glTF space: X right, Y up, Z toward viewer)
    lo, hi, tris = world_bounds(gltf, binary)
    raw_w, raw_h, raw_d = (hi[a] - lo[a] for a in range(3))
    if raw_h <= 0:
        raise ValueError(f"{asset['asset_id']}: zero height")

    # 2. long-axis convention: catalogue width is X, depth is Z(glTF)/Y(Rhino)
    rotate = False
    nominal_long_x = nominal["width"] > nominal["depth"] * 1.2
    nominal_long_z = nominal["depth"] > nominal["width"] * 1.2
    measured_long_x = raw_w > raw_d * 1.2
    measured_long_z = raw_d > raw_w * 1.2
    if (nominal_long_x and measured_long_z) or (nominal_long_z and measured_long_x):
        rotate = True
    half = math.sqrt(0.5)
    rotation = [0.0, half, 0.0, half] if rotate else [0.0, 0.0, 0.0, 1.0]  # 90deg about +Y
    pre = quat_to_matrix(rotation)
    lo, hi, _ = world_bounds(gltf, binary, pre)

    # 3. scale to catalogue height and put bottom-centre on the origin
    scale = float(nominal["height"]) / (hi[1] - lo[1])
    centre_x = (lo[0] + hi[0]) / 2 * scale
    centre_z = (lo[2] + hi[2]) / 2 * scale
    bottom_y = lo[1] * scale
    translation = [-centre_x, -bottom_y, -centre_z]

    scene = gltf.setdefault("scenes", [{"nodes": []}])[gltf.get("scene", 0)]
    root = {
        "name": f"{asset['asset_id']}_root",
        "children": list(scene.get("nodes", [])),
        "translation": translation,
        "rotation": rotation,
        "scale": [scale, scale, scale],
    }
    gltf.setdefault("nodes", []).append(root)
    scene["nodes"] = [len(gltf["nodes"]) - 1]

    lo, hi, tris = world_bounds(gltf, binary)
    width, height, depth = (round(hi[a] - lo[a], 1) for a in range(3))

    # 4. materials: the catalogue's Almond identity for every material, except
    #    materials the source already named ALMOND::<id> (procedural assets
    #    ship e.g. wood + foliage), which keep their own library identity.
    material_id = asset["render_material_id"]

    def apply_material(mat: dict, mid: str) -> None:
        spec = materials.get(mid)
        base = [1.0, 1.0, 1.0, 1.0]
        if spec:
            r, g, b = spec["base_color"]
            base = [exchange.srgb_to_linear(r), exchange.srgb_to_linear(g),
                    exchange.srgb_to_linear(b), float(spec.get("opacity", 1.0))]
        mat["name"] = exchange.material_name(mid)
        mat.pop("pbrMetallicRoughness", None)
        pbr = mat.setdefault("pbrMetallicRoughness", {})
        pbr["baseColorFactor"] = [round(v, 4) for v in base]
        if spec:
            pbr["metallicFactor"] = float(spec["metallic"])
            pbr["roughnessFactor"] = float(spec["roughness"])
        if base[3] < 1.0:
            mat["alphaMode"] = "BLEND"

    mats = gltf.setdefault("materials", [])
    if not mats:
        mats.append({})
    mat_ids: list[str] = []
    for mat in mats:
        existing = exchange.material_id_from_name(mat.get("name", ""))
        mid = existing if existing in materials else material_id
        apply_material(mat, mid)
        mat_ids.append(mid)
    object_names: list[str] = []
    objects_by_material: dict[str, list[str]] = {}
    for mesh_index, mesh in enumerate(gltf.get("meshes", [])):
        mesh["name"] = f"{asset['asset_id']}_part{mesh_index + 1}"
        object_names.append(mesh["name"])
        prims = mesh.get("primitives", [])
        for prim in prims:
            prim.setdefault("material", 0)
        mesh_mid = mat_ids[prims[0]["material"]] if prims else material_id
        objects_by_material.setdefault(mesh_mid, []).append(mesh["name"])
    material_groups = [{"material_id": mid, "objects": names}
                       for mid, names in sorted(objects_by_material.items())]
    for node in gltf.get("nodes", []):
        if "mesh" in node:
            node["name"] = gltf["meshes"][node["mesh"]]["name"]

    gltf.setdefault("asset", {})["generator"] = "almond-mcp build_generated_assets"
    gltf["asset"]["extras"] = {
        "almond": {"asset_id": asset["asset_id"], "library_id": "generated_assets",
                   "material_id": material_id, "units": "mm",
                   "dimensions_mm": {"width": width, "depth": depth, "height": height}}
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    glb_path, contract_path = exchange.contract_paths(out_dir, asset["asset_id"])
    write_glb(glb_path, gltf, binary)

    # 5. contract + manifest record from measured geometry
    clearance = asset.get("clearance_mm") or {"front": 0, "back": 0, "left": 0, "right": 0}
    bounds_mm = {"min": [-width / 2, -depth / 2, 0.0], "max": [width / 2, depth / 2, height]}
    contract = exchange.build_contract(
        asset_id=asset["asset_id"], name=f"{asset['product']} ({asset['variant']})",
        glb_filename=glb_path.name, bounds_mm=bounds_mm,
        materials=material_groups,
        source_app="meshy", source_units="m", clearance_mm=clearance,
        object_count=len(object_names),
    )
    contract["library_id"] = "generated_assets"
    contract["spatial"]["support_plane"] = asset.get("support_plane", "floor")
    contract["spatial"]["placement_priority"] = asset.get("placement_priority", "movable")
    contract["license"] = ASSET_LICENSE
    contract_path.write_text(json.dumps(contract, indent=2), encoding="utf-8")

    deviation = max(abs(width - nominal["width"]) / nominal["width"],
                    abs(depth - nominal["depth"]) / nominal["depth"])
    prov = provenance.get(asset["asset_id"], {})
    record = {
        "asset_id": asset["asset_id"],
        "brand": "Generic",
        "source_class": "generated_asset",
        "catalogue_status": "generated",
        "drawing_roles": asset.get("drawing_roles", []),
        "geometry_mode": asset.get("geometry_mode", "3d_entourage"),
        "lod": asset.get("lod", "medium"),
        "category": asset["category"],
        "series": "ALMOND-GEN",
        "product": asset["product"],
        "variant": asset["variant"],
        "dimensions_mm": {"width": width, "depth": depth, "height": height},
        "nominal_dimensions_mm": dict(nominal),
        "match_status": "generated_height_normalised",
        "plan_dimension_deviation": round(deviation, 3),
        "warehouse_title": None,
        "warehouse_publisher": None,
        "warehouse_status": "generated",
        "warehouse_url": "",
        "file": f"models/{glb_path.name}",
        "contract_file": f"models/{contract_path.name}",
        "download_url": f"{RAW_BASE}/models/{glb_path.name}",
        "contract_download_url": f"{RAW_BASE}/models/{contract_path.name}",
        "sha256": sha256(glb_path),
        "file_size_bytes": glb_path.stat().st_size,
        "triangle_count": tris,
        "tags": asset.get("tags", []),
        "render_material_id": material_id,
        "license": ASSET_LICENSE,
        "geometry_source": {
            "type": "generated",
            "format": "glb",
            "generator": "meshy",
            "parameters": {
                "prompt": asset["prompt"],
                "image_task_id": prov.get("image_task_id"),
                "image_model": prov.get("image_model"),
                "mesh_task_id": prov.get("mesh_task_id"),
                "mesh_model": prov.get("mesh_model"),
                "generated_at": prov.get("generated_at"),
                "orientation_correction": "rotated_90_about_vertical" if rotate else None,
                "scale_applied": round(scale, 6),
            },
        },
        "spatial": {
            "metadata_version": 1,
            "units": "mm",
            "anchor": "bottom_center",
            "support_plane": asset.get("support_plane", "floor"),
            "bounds_source": "measured_from_normalised_glb",
            "geometry_bounds_status": "measured",
            "local_aabb": bounds_mm,
            "footprint": [[-width / 2, -depth / 2], [width / 2, -depth / 2],
                          [width / 2, depth / 2], [-width / 2, depth / 2]],
            "clearance_mm": clearance,
            "collision_shape": "oriented_box",
            "placement_priority": asset.get("placement_priority", "movable"),
        },
    }
    if "mount_height_mm" in asset:
        record["spatial"]["mount_height_mm"] = asset["mount_height_mm"]
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--library", default=str(LIBRARY_DIR))
    parser.add_argument("--only", nargs="*", default=[], help="asset ids to rebuild")
    parser.add_argument("--allow-missing", action="store_true",
                        help="skip assets whose raw GLB is absent instead of failing")
    args = parser.parse_args(argv)

    library = Path(args.library)
    catalogue = json.loads((library / "catalogue.json").read_text(encoding="utf-8"))
    provenance_path = library / "provenance.json"
    provenance = {}
    if provenance_path.is_file():
        provenance = json.loads(provenance_path.read_text(encoding="utf-8")).get("assets", {})
    materials = load_material_colours()
    manifest_path = library / "manifest.json"
    existing: dict[str, dict] = {}
    if manifest_path.is_file():
        for rec in json.loads(manifest_path.read_text(encoding="utf-8")).get("assets", []):
            existing[rec["asset_id"]] = rec

    records: list[dict] = []
    skipped: list[str] = []
    for asset in catalogue["assets"]:
        asset_id = asset["asset_id"]
        raw = library / "raw" / f"{asset_id}.glb"
        if args.only and asset_id not in args.only:
            if asset_id in existing:
                records.append(existing[asset_id])
            continue
        if not raw.is_file():
            if asset_id in existing and not args.only:
                records.append(existing[asset_id])
                continue
            if args.allow_missing:
                skipped.append(asset_id)
                continue
            raise SystemExit(f"raw GLB missing: {raw}")
        record = normalise(asset, raw, library / "models", materials, provenance)
        dims = record["dimensions_mm"]
        flag = " (plan deviates %.0f%%)" % (record["plan_dimension_deviation"] * 100) \
            if record["plan_dimension_deviation"] > 0.25 else ""
        rot = " rotated" if record["geometry_source"]["parameters"]["orientation_correction"] else ""
        print(f"{asset_id:32} {dims['width']:7.0f} x {dims['depth']:7.0f} x {dims['height']:7.0f} mm  "
              f"{record['triangle_count']:6d} tris{rot}{flag}")
        records.append(record)

    manifest = {
        "library_id": catalogue["library_id"],
        "library_name": catalogue["library_name"],
        "catalogue_region": "Generated (Meshy) - no vendor catalogue",
        "catalogue_checked": _dt.date.today().isoformat(),
        "schema_version": "2.0",
        "purpose": catalogue["purpose"],
        "license": ASSET_LICENSE,
        "license_note": ASSET_LICENSE_NOTE,
        "generation_recipe": catalogue.get("generation_recipe", {}),
        "placement_policy": {
            "participates_in_room_furniture_search": True,
            "participates_in_room_collision_by_default": True,
            "default_rhino_layer": "ALMOND-GEN",
        },
        "spatial_contract": {
            "units": "millimeters",
            "coordinate_system": "asset_local_z_up",
            "default_anchor": "bottom_center",
            "nominal_bounds_require_runtime_measurement": False,
        },
        "assets": records,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nwrote {manifest_path} with {len(records)} asset(s)")
    if skipped:
        print("skipped (no raw GLB): " + ", ".join(skipped))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
