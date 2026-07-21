"""Blender side of the Almond cross-app proof.

Builds a small parametric bench (an asset Blender is better at than Rhino:
subdivided/organic-ish slats), stamps Almond material metadata as custom
properties, and exports a GLB whose PBR channels match the Almond material
library. Also writes a sidecar JSON describing the asset for the placement
side (bounds, anchor, material assignments) - the same 'spatial contract'
shape Almond uses for its curated libraries.

Run: blender --background --python blender_make_asset.py
"""
import bpy
import json
import sys
from pathlib import Path

OUT_DIR = Path(sys.argv[-1] if sys.argv[-1].endswith("out") else
               r"C:\Users\liang\AppData\Local\Temp\almond_blender")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Almond material definitions (subset of Materialfiles/manifest.json)
ALMOND_MATERIALS = {
    "wood-oak": {
        "name": "Oak", "category": "wood", "base_color": (200, 170, 130),
        "metallic": 0.0, "roughness": 0.65, "opacity": 1.0,
        "ue_material_slot": "M_Wood_Oak",
    },
    "steel-painted-sage": {
        "name": "Painted steel - sage green", "category": "metal",
        "base_color": (150, 170, 120), "metallic": 0.85, "roughness": 0.45,
        "opacity": 1.0, "ue_material_slot": "M_Steel_Painted_Sage",
    },
}


def almond_material(material_id):
    """Create a Principled BSDF material matching the Almond definition and
    tag it with almond:* custom properties (survive into glTF 'extras')."""
    spec = ALMOND_MATERIALS[material_id]
    mat = bpy.data.materials.new(name=f"ALMOND::{material_id}")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    r, g, b = (c / 255.0 for c in spec["base_color"])
    bsdf.inputs["Base Color"].default_value = (r, g, b, 1.0)
    bsdf.inputs["Metallic"].default_value = spec["metallic"]
    bsdf.inputs["Roughness"].default_value = spec["roughness"]
    mat["almond:material_id"] = material_id
    mat["almond:ue_material_slot"] = spec["ue_material_slot"]
    mat["almond:metallic"] = spec["metallic"]
    mat["almond:roughness"] = spec["roughness"]
    return mat


def tag(obj, material_id):
    spec = ALMOND_MATERIALS[material_id]
    obj["almond:material_id"] = material_id
    obj["almond:material_name"] = spec["name"]
    obj["almond:material_category"] = spec["category"]
    obj["almond:ue_material_slot"] = spec["ue_material_slot"]
    obj["almond:source_app"] = "blender"


# clean scene
bpy.ops.wm.read_factory_settings(use_empty=True)

# --- bench: 1800 x 450 x 450 mm, modelled in meters (Blender native) ---
W, D, H = 1.8, 0.45, 0.45
oak = almond_material("wood-oak")
steel = almond_material("steel-painted-sage")

slats = []
n_slats = 5
gap = 0.012
slat_thk = 0.04
slat_w = (D - gap * (n_slats - 1)) / n_slats
for i in range(n_slats):
    y = -D / 2 + slat_w / 2 + i * (slat_w + gap)
    # primitive_cube_add(size=1) spans -0.5..0.5, so scale == full dimension
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, y, H - slat_thk / 2))
    slat = bpy.context.active_object
    slat.scale = (W, slat_w, slat_thk)
    bpy.ops.object.transform_apply(scale=True)
    # bevel for a nicer read - the kind of detail Blender does cheaply
    bev = slat.modifiers.new("Bevel", "BEVEL")
    bev.width = 0.004
    bev.segments = 2
    slat.name = f"bench_slat_{i}"
    slat.data.materials.append(oak)
    tag(slat, "wood-oak")
    slats.append(slat)

legs = []
leg_h = H - slat_thk          # legs stop under the slats
for sx in (-1, 1):
    x = sx * (W / 2 - 0.12)   # inset from the seat ends
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, 0, leg_h / 2))
    leg = bpy.context.active_object
    leg.scale = (0.04, D, leg_h)
    bpy.ops.object.transform_apply(scale=True)
    leg.name = f"bench_leg_{'L' if sx < 0 else 'R'}"
    leg.data.materials.append(steel)
    tag(leg, "steel-painted-sage")
    legs.append(leg)

objects = slats + legs
for obj in objects:
    obj.select_set(True)
bpy.context.view_layer.objects.active = objects[0]

# world bounds in millimetres for the Almond spatial contract
xs, ys, zs = [], [], []
deps = bpy.context.evaluated_depsgraph_get()
for obj in objects:
    ev = obj.evaluated_get(deps)
    for corner in ev.bound_box:
        world = ev.matrix_world @ __import__("mathutils").Vector(corner)
        xs.append(world.x); ys.append(world.y); zs.append(world.z)
bounds_mm = {
    "min": [min(xs) * 1000, min(ys) * 1000, min(zs) * 1000],
    "max": [max(xs) * 1000, max(ys) * 1000, max(zs) * 1000],
}

glb_path = OUT_DIR / "almond_bench.glb"
bpy.ops.export_scene.gltf(
    filepath=str(glb_path),
    export_format="GLB",
    use_selection=True,
    export_extras=True,          # carries almond:* custom props into glTF extras
    export_yup=True,
)

contract = {
    "asset_id": "blender-bench-slatted-01",
    "library_id": "blender_exchange",
    "name": "Slatted bench (Blender)",
    "source_app": "blender",
    "source_units": "m",
    "file": glb_path.name,
    "dimensions_mm": {
        "width": round(bounds_mm["max"][0] - bounds_mm["min"][0], 1),
        "depth": round(bounds_mm["max"][1] - bounds_mm["min"][1], 1),
        "height": round(bounds_mm["max"][2] - bounds_mm["min"][2], 1),
    },
    "spatial": {
        "units": "mm",
        "anchor": "bottom_center",
        "support_plane": "floor",
        "local_aabb": bounds_mm,
        "clearance_mm": {"front": 900, "back": 100, "left": 100, "right": 100},
        "collision_shape": "oriented_box",
        "placement_priority": "movable",
    },
    "materials": [
        {"material_id": "wood-oak", "objects": [o.name for o in slats]},
        {"material_id": "steel-painted-sage", "objects": [o.name for o in legs]},
    ],
    "object_count": len(objects),
}
(OUT_DIR / "almond_bench.json").write_text(json.dumps(contract, indent=2), encoding="utf-8")
print("ALMOND_EXPORT_OK", glb_path, contract["dimensions_mm"])
