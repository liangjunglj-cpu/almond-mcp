"""Blender headless: render every generated asset from a 3/4 view.
Run: blender -b --python render_assets.py -- <models_dir> <out_dir>
"""
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
MODELS = Path(argv[0]).resolve()
OUT = Path(argv[1]).resolve()
OUT.mkdir(parents=True, exist_ok=True)
SIZE = 640
ARCHIVE_STYLE = "--archive" in argv[2:]


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
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
        # Neutral geometry study for the archive; source materials are unchanged.
        scene.display.shading.color_type = "SINGLE"
        scene.display.shading.single_color = (0.65, 0.66, 0.62)
        scene.display.shading.show_object_outline = False
        scene.display.shading.studiolight_rotate_z = math.radians(25)
        scene.render.film_transparent = True
        scene.render.image_settings.color_mode = "RGBA"
    scene.world = bpy.data.worlds.new("World")
    scene.world.color = (0.86, 0.88, 0.90)
    return scene


def render(glb: Path):
    scene = reset_scene()
    bpy.ops.import_scene.gltf(filepath=str(glb))
    meshes = [o for o in scene.objects if o.type == "MESH"]
    if not meshes:
        print("NO MESH", glb.name)
        return
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


for glb in sorted(MODELS.glob("gen-*.glb")):
    render(glb)
