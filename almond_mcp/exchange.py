"""Cross-application asset exchange.

Moving an asset between applications loses meaning, not geometry. Measured
on a Blender 5.1 -> GLB -> Rhino 8 round trip (see docs/cross-app-blender.md):

* geometry and dimensions survive exactly;
* PBR channels and the material *name* survive;
* per-object metadata written into glTF ``extras`` is dropped entirely;
* base colours drift through a linear/sRGB double conversion;
* materials are duplicated one-per-mesh instead of shared.

So the file carries geometry, and an *asset contract* travelling beside it
carries meaning. Because the contract names an Almond ``material_id``, the
receiving application can restore metadata, correct the colours from the
canonical library, and collapse duplicate materials. This module builds and
reads those contracts; the Rhino-side execution lives in server.py.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

CONTRACT_VERSION = 1
CONTRACT_SUFFIX = ".almond.json"
MATERIAL_PREFIX = "ALMOND::"

_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,80}")


def material_name(material_id: str) -> str:
    """The document material name that carries identity across applications."""
    return MATERIAL_PREFIX + material_id


def material_id_from_name(name: str) -> str:
    """Inverse of material_name; '' when the name is not an Almond material."""
    if not name or not name.startswith(MATERIAL_PREFIX):
        return ""
    return name[len(MATERIAL_PREFIX):]


def srgb_to_linear(value: float) -> float:
    """sRGB 0..255 -> linear 0..1 (Blender's Principled BSDF wants linear)."""
    c = value / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def build_contract(
    asset_id: str,
    name: str,
    glb_filename: str,
    bounds_mm: dict[str, list[float]],
    materials: list[dict[str, Any]],
    source_app: str,
    source_units: str = "mm",
    anchor: str = "bottom_center",
    clearance_mm: dict[str, float] | None = None,
    object_count: int = 0,
) -> dict[str, Any]:
    """Assemble an asset contract: the meaning that the file cannot carry."""
    if not _ID_RE.fullmatch(asset_id):
        raise ValueError(
            "asset_id must be 1-80 chars of letters, digits, dot, underscore, hyphen."
        )
    lo, hi = bounds_mm["min"], bounds_mm["max"]
    if len(lo) != 3 or len(hi) != 3:
        raise ValueError("bounds_mm min/max must each hold three numbers.")
    if not all(math.isfinite(float(v)) for v in (*lo, *hi)):
        raise ValueError("bounds_mm values must be finite.")

    width, depth, height = (round(float(hi[i]) - float(lo[i]), 1) for i in range(3))
    return {
        "schema_version": CONTRACT_VERSION,
        "asset_id": asset_id,
        "library_id": "exchange",
        "name": name or asset_id,
        "source_app": source_app,
        "source_units": source_units,
        "file": glb_filename,
        "dimensions_mm": {"width": width, "depth": depth, "height": height},
        "spatial": {
            "units": "mm",
            "anchor": anchor,
            "support_plane": "floor",
            "local_aabb": {
                "min": [round(float(v), 3) for v in lo],
                "max": [round(float(v), 3) for v in hi],
            },
            "clearance_mm": clearance_mm or {
                "front": 0, "back": 0, "left": 0, "right": 0
            },
            "collision_shape": "oriented_box",
            "placement_priority": "movable",
        },
        "materials": materials,
        "object_count": object_count,
    }


def load_contract(path: str | Path) -> dict[str, Any]:
    """Read and validate a contract file."""
    contract_path = Path(path)
    if not contract_path.is_file():
        raise FileNotFoundError(f"Asset contract not found: {contract_path}")
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    for key in ("asset_id", "file", "spatial", "dimensions_mm"):
        if key not in contract:
            raise ValueError(f"Contract is missing required key: {key}")
    if int(contract.get("schema_version", 0)) > CONTRACT_VERSION:
        raise ValueError(
            f"Contract schema {contract['schema_version']} is newer than this "
            f"almond-mcp understands (max {CONTRACT_VERSION}); upgrade almond-mcp."
        )
    glb = contract_path.parent / contract["file"]
    if not glb.is_file():
        raise FileNotFoundError(f"Contract references a missing file: {glb}")
    contract["_resolved_file"] = str(glb)
    contract["_contract_path"] = str(contract_path)
    return contract


def contract_paths(output_dir: str | Path, asset_id: str) -> tuple[Path, Path]:
    """(glb_path, contract_path) for an asset written into output_dir."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{asset_id}.glb", directory / f"{asset_id}{CONTRACT_SUFFIX}"


def dimension_report(contract: dict[str, Any], measured_mm: dict[str, float],
                     tolerance: float = 0.02) -> dict[str, Any]:
    """Compare a receiving application's measurement against the contract.

    Rotation-agnostic (sorted extents), because placement may rotate the
    asset about Z. Returns a payload only worth showing when it mismatches.
    """
    expected = contract.get("dimensions_mm") or {}
    want = sorted(float(expected.get(k, 0) or 0) for k in ("width", "depth", "height"))
    got = sorted(float(measured_mm.get(k, 0) or 0) for k in ("width", "depth", "height"))
    if not all(v > 0 for v in want):
        return {"status": "unknown", "reason": "contract has no usable dimensions"}
    worst = max(abs(g - w) / w for g, w in zip(got, want))
    return {
        "status": "ok" if worst <= tolerance else "mismatch",
        "expected_sorted_mm": [round(v, 1) for v in want],
        "measured_sorted_mm": [round(v, 1) for v in got],
        "worst_relative_error": round(worst, 4),
        "tolerance": tolerance,
    }


def blender_export_script(asset_id: str, name: str, output_dir: str,
                          selection_only: bool = True) -> str:
    """Python for Blender (run it through blender-mcp's execute_code) that
    exports the selection as an Almond contract + GLB.

    Note the ``to_mesh()`` measurement: Blender reports inflated bounding
    boxes for curve objects (observed +1 m per axis), so evaluated mesh data
    is the only trustworthy source of dimensions.
    """
    out = json.dumps(str(output_dir))
    return f'''
import bpy, json, math, mathutils
from pathlib import Path

OUT = Path({out}); OUT.mkdir(parents=True, exist_ok=True)
ASSET_ID = {json.dumps(asset_id)}
NAME = {json.dumps(name)}
SELECTION_ONLY = {bool(selection_only)}

objs = [o for o in (bpy.context.selected_objects if SELECTION_ONLY
                    else bpy.context.scene.objects) if o.type in {{'MESH', 'CURVE', 'SURFACE'}}]
if not objs:
    raise RuntimeError("Nothing to export: select mesh/curve objects first.")

deps = bpy.context.evaluated_depsgraph_get()
xs, ys, zs = [], [], []
for o in objs:
    ev = o.evaluated_get(deps)
    me = ev.to_mesh()
    if me is None:
        continue
    for v in me.vertices:                       # evaluated mesh, not bound_box
        w = ev.matrix_world @ v.co
        xs.append(w.x); ys.append(w.y); zs.append(w.z)
    ev.to_mesh_clear()

S = 1000.0                                       # Blender metres -> contract mm
bounds = {{"min": [min(xs)*S, min(ys)*S, min(zs)*S],
           "max": [max(xs)*S, max(ys)*S, max(zs)*S]}}

groups = {{}}
for o in objs:
    for slot in o.material_slots:
        m = slot.material
        if m and m.name.startswith("ALMOND::"):
            groups.setdefault(m.name[len("ALMOND::"):], []).append(o.name)
materials = [{{"material_id": k, "objects": sorted(set(v))}} for k, v in sorted(groups.items())]

glb = OUT / (ASSET_ID + ".glb")
for o in bpy.context.scene.objects:
    o.select_set(o in objs)
bpy.ops.export_scene.gltf(filepath=str(glb), export_format="GLB",
                          use_selection=True, export_extras=True, export_yup=True)

contract = {{
    "schema_version": {CONTRACT_VERSION},
    "asset_id": ASSET_ID, "library_id": "exchange", "name": NAME,
    "source_app": "blender", "source_units": "m", "file": glb.name,
    "dimensions_mm": {{
        "width": round(bounds["max"][0]-bounds["min"][0], 1),
        "depth": round(bounds["max"][1]-bounds["min"][1], 1),
        "height": round(bounds["max"][2]-bounds["min"][2], 1)}},
    "spatial": {{"units": "mm", "anchor": "bottom_center", "support_plane": "floor",
                "local_aabb": bounds, "clearance_mm": {{"front": 0, "back": 0, "left": 0, "right": 0}},
                "collision_shape": "oriented_box", "placement_priority": "movable"}},
    "materials": materials, "object_count": len(objs),
}}
path = OUT / (ASSET_ID + "{CONTRACT_SUFFIX}")
path.write_text(json.dumps(contract, indent=2), encoding="utf-8")
print("ALMOND_CONTRACT " + str(path))
print("dimensions_mm " + json.dumps(contract["dimensions_mm"]))
'''


def blender_material_script(materials: list[dict[str, Any]],
                            assignments: list[dict[str, Any]]) -> str:
    """Python for Blender that creates Almond materials (sRGB converted to
    linear so colours match the library) and assigns them to named objects."""
    lib = {}
    for material in materials:
        r, g, b = material["base_color"]
        lib[material["material_id"]] = {
            "linear": [srgb_to_linear(r), srgb_to_linear(g), srgb_to_linear(b)],
            "srgb": f"{int(r)},{int(g)},{int(b)}",
            "metallic": float(material["metallic"]),
            "roughness": float(material["roughness"]),
            "opacity": float(material["opacity"]),
            "slot": material["ue_material_slot"],
            "category": material["category"],
        }
    return f'''
import bpy
LIB = {json.dumps(lib)}
ASSIGN = {json.dumps(assignments)}

def almond_material(mid):
    name = "ALMOND::" + mid
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name=name)
    spec = LIB[mid]
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (*spec["linear"], 1.0)
        bsdf.inputs["Metallic"].default_value = spec["metallic"]
        bsdf.inputs["Roughness"].default_value = spec["roughness"]
        if spec["opacity"] < 1.0 and "Alpha" in bsdf.inputs:
            bsdf.inputs["Alpha"].default_value = spec["opacity"]
    for key, value in (("almond:material_id", mid),
                       ("almond:ue_material_slot", spec["slot"]),
                       ("almond:base_color", spec["srgb"]),
                       ("almond:metallic", spec["metallic"]),
                       ("almond:roughness", spec["roughness"]),
                       ("almond:opacity", spec["opacity"])):
        mat[key] = value
    return mat

applied = 0
for entry in ASSIGN:
    mat = almond_material(entry["material_id"])
    spec = LIB[entry["material_id"]]
    for obj_name in entry["objects"]:
        obj = bpy.data.objects.get(obj_name)
        if obj is None or not hasattr(obj.data, "materials"):
            continue
        obj.data.materials.clear()
        obj.data.materials.append(mat)
        obj["almond:material_id"] = entry["material_id"]
        obj["almond:material_category"] = spec["category"]
        obj["almond:ue_material_slot"] = spec["slot"]
        obj["almond:base_color"] = spec["srgb"]
        obj["almond:source_app"] = "blender"
        applied += 1
print("ALMOND_MATERIALS applied to " + str(applied) + " object(s)")
'''
