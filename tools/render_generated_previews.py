"""Blender headless: render every generated asset from a 3/4 view.
Run: blender -b --python tools/render_generated_previews.py -- <models_dir> <out_dir> --archive
"""
import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import bpy
from mathutils import Vector

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("models_dir", type=Path)
parser.add_argument("out_dir", type=Path)
parser.add_argument("--archive", action="store_true", help="Transparent background for library cards")
parser.add_argument("--clay", action="store_true", help="Optional neutral geometry study instead of source material colours")
parser.add_argument("--asset", help="Render one asset ID for inspection")
args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
MODELS = args.models_dir.resolve()
OUT = args.out_dir.resolve()
OUT.mkdir(parents=True, exist_ok=True)
SIZE = 640
ARCHIVE_STYLE = args.archive


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.studio_light = "paint.sl"
    scene.display.shading.studiolight_intensity = 1.0
    scene.display.shading.color_type = "MATERIAL"
    scene.display.shading.show_shadows = True
    scene.display.shading.show_cavity = True
    scene.display.shading.cavity_type = "BOTH"
    scene.display.shading.show_object_outline = True
    scene.render.resolution_x = SIZE
    scene.render.resolution_y = SIZE
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    if ARCHIVE_STYLE:
        scene.display.shading.show_object_outline = False
        scene.display.shading.studiolight_rotate_z = math.radians(25)
        scene.render.film_transparent = True
        scene.render.image_settings.color_mode = "RGBA"
    if args.clay:
        scene.display.shading.color_type = "SINGLE"
        scene.display.shading.single_color = (0.65, 0.66, 0.62)
    scene.world = bpy.data.worlds.new("World")
    scene.world.color = (0.86, 0.88, 0.90)
    return scene


def render(glb: Path):
    scene = reset_scene()
    bpy.ops.import_scene.gltf(filepath=str(glb))
    meshes = [o for o in scene.objects if o.type == "MESH"]
    if not meshes:
        raise ValueError("No mesh in " + glb.name)
    lo = Vector((math.inf,) * 3)
    hi = Vector((-math.inf,) * 3)
    for o in meshes:
        for corner in o.bound_box:
            w = o.matrix_world @ Vector(corner)
            lo = Vector(min(a, b) for a, b in zip(lo, w))
            hi = Vector(max(a, b) for a, b in zip(hi, w))
    centre = (lo + hi) / 2
    radius = max((hi - lo).length / 2, 1e-3)

    if not ARCHIVE_STYLE:
        # ground plane at the model's base
        bpy.ops.mesh.primitive_plane_add(size=radius * 8, location=(centre.x, centre.y, lo.z))
        plane = bpy.context.active_object
        mat = bpy.data.materials.new("ground")
        mat.diffuse_color = (0.80, 0.82, 0.84, 1.0)
        plane.data.materials.append(mat)

    cam_data = bpy.data.cameras.new("cam")
    cam_data.lens = 50
    cam = bpy.data.objects.new("cam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    direction = Vector((1.0, -1.35, 0.75)).normalized()
    distance = radius / math.sin(cam_data.angle / 2 * 0.85)  # angle is already radians
    cam.location = centre + direction * distance
    cam.rotation_euler = (centre - cam.location).to_track_quat("-Z", "Y").to_euler()
    # the GLBs are in millimetres: a 1750-unit figure is outside the default 100-unit clip range
    cam_data.clip_start = max(distance * 0.01, 0.01)
    cam_data.clip_end = distance * 20

    scene.render.filepath = str(OUT / (glb.stem + ".png"))
    bpy.ops.render.render(write_still=True)
    print("RENDERED", glb.stem)
    return {"asset_id":glb.stem,
            "model_sha256":hashlib.sha256(glb.read_bytes()).hexdigest(),
            "preview_sha256":hashlib.sha256(Path(scene.render.filepath).read_bytes()).hexdigest(),
            "material_names":sorted({m.name for obj in meshes for m in obj.data.materials if m})}


models = [p for p in sorted(MODELS.glob("gen-*.glb")) if not args.asset or p.stem == args.asset]
if not models:
    raise ValueError("No matching generated models")
records = [render(glb) for glb in models]
record = {"schema_version":1,"created_at":datetime.now(timezone.utc).isoformat(),
          "renderer":"Blender " + bpy.app.version_string,"engine":"BLENDER_WORKBENCH",
          "script":"tools/render_generated_previews.py",
          "script_sha256_lf":hashlib.sha256(Path(__file__).read_text(encoding="utf-8").encode()).hexdigest(),
          "colour_mode":"neutral_clay" if args.clay else "embedded_material_base_colour",
          "transparent_background":ARCHIVE_STYLE,"resolution":[SIZE,SIZE],
          "view_transform":"Standard","look":"None","studio_light":"paint.sl","studio_light_intensity":1.0,
          "notes":"Preview-only derivation from the unchanged GLBs. Studio shading of assigned material colours; not photographic textures or a full PBR render.",
          "assets":records}
(OUT / "render-record.json").write_text(json.dumps(record,indent=2)+"\n",encoding="utf-8",newline="\n")
