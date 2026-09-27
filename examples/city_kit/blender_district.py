"""Rebuild the Almond District in Blender with upgraded materials + lighting.

Run headless:  blender -b -P examples/city_kit/blender_district.py
Reads the per-material GLBs exported by export_asset_contract (one file per
Almond material_id, plus 'foliage' and 'lampheads' splits), assigns a
quality Principled/Cycles material to each file's meshes, adds a Nishita
sun/sky world, ground plane, and renders an aerial and a street view.

Set ALMOND_DISTRICT_SCRATCH to the folder that holds district_glb_mat/.
"""
import bpy
import glob
import math
import os

SCRATCH = os.environ.get(
    "ALMOND_DISTRICT_SCRATCH",
    os.path.join(os.environ.get("TEMP", "/tmp"), "almond_district"))
GLB_DIR = os.path.join(SCRATCH, "district_glb_mat")
OUT_DIR = SCRATCH

# ── clean scene ─────────────────────────────────────────────────────────────
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

# ── material recipes: material_id fragment -> settings ─────────────────────
RECIPES = {
    "concrete-smooth":    dict(base=(0.70, 0.69, 0.66), rough=0.72, bump=0.05),
    "concrete-boardformed": dict(base=(0.60, 0.58, 0.55), rough=0.85, bump=0.12),
    "steel-painted-sage": dict(base=(0.50, 0.58, 0.42), rough=0.45, metal=0.15),
    "steel-galvanized":   dict(base=(0.62, 0.63, 0.65), rough=0.45, metal=1.0),
    "aluminium-anodized": dict(base=(0.78, 0.78, 0.80), rough=0.30, metal=1.0),
    "metal-corrugated":   dict(base=(0.42, 0.48, 0.38), rough=0.50, metal=0.9),
    "glass-clear":        dict(base=(0.88, 0.94, 0.92), rough=0.03, glass=True),
    "glass-laminated":    dict(base=(0.80, 0.88, 0.86), rough=0.05, glass=True),
    "wood-oak":           dict(base=(0.50, 0.34, 0.20), rough=0.60, bump=0.03),
    "wood-walnut":        dict(base=(0.30, 0.19, 0.12), rough=0.55),
    "wood-birch-ply":     dict(base=(0.76, 0.62, 0.44), rough=0.65),
    "brick-red":          dict(base=(0.45, 0.19, 0.14), rough=0.90, bump=0.15),
    "rubber-black":       dict(base=(0.05, 0.05, 0.055), rough=0.95),
    "foliage":            dict(base=(0.14, 0.30, 0.10), rough=0.80, bump=0.25),
    "lampheads":          dict(base=(0.90, 0.85, 0.70), rough=0.4, emit=(1.0, 0.85, 0.6), emit_str=8.0),
}


def build_material(name, r):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*r["base"], 1.0)
    bsdf.inputs["Roughness"].default_value = r.get("rough", 0.5)
    if "metal" in r:
        bsdf.inputs["Metallic"].default_value = r["metal"]
    if r.get("glass"):
        key = "Transmission Weight" if "Transmission Weight" in bsdf.inputs else "Transmission"
        bsdf.inputs[key].default_value = 1.0
        bsdf.inputs["IOR"].default_value = 1.45
    if "emit" in r:
        if "Emission Color" in bsdf.inputs:
            bsdf.inputs["Emission Color"].default_value = (*r["emit"], 1.0)
        bsdf.inputs["Emission Strength"].default_value = r.get("emit_str", 5.0)
    if r.get("bump"):
        noise = nodes.new("ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = 180.0
        bump = nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = r["bump"]
        links.new(noise.outputs["Fac"], bump.inputs["Height"])
        links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


# ── import per-material GLBs ───────────────────────────────────────────────
imported_total = 0
for glb in sorted(glob.glob(os.path.join(GLB_DIR, "*.glb"))):
    stem = os.path.splitext(os.path.basename(glb))[0]          # district-mat-<id> | district-foliage
    key = stem.replace("district-mat-", "").replace("district-", "")
    recipe = None
    for frag, r in RECIPES.items():
        if key == frag or key.startswith(frag):
            recipe = r
            break
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=glb)
    new_objs = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
    imported_total += len(new_objs)
    if recipe:
        mat = build_material(f"ALMOND {key}", recipe)
        for o in new_objs:
            o.data.materials.clear()
            o.data.materials.append(mat)
print(f"imported {imported_total} meshes from {GLB_DIR}")

# ── normalize units: if the scene is kilometres across, it arrived in mm ───
xs = [c for o in bpy.data.objects if o.type == "MESH"
      for c in (o.bound_box[0][0] + o.location.x, o.bound_box[6][0] + o.location.x)]
extent = (max(xs) - min(xs)) if xs else 0
if extent > 2000:
    for o in bpy.data.objects:
        if o.parent is None:
            o.scale = (0.001, 0.001, 0.001)
    bpy.context.view_layer.update()
    print(f"scene extent {extent:.0f} -> scaled x0.001")

# ── ground plane ───────────────────────────────────────────────────────────
bpy.ops.mesh.primitive_plane_add(size=1200, location=(69, 50, -0.08))
ground = bpy.context.active_object
gmat = build_material("ALMOND ground", dict(base=(0.55, 0.54, 0.52), rough=0.9))
ground.data.materials.append(gmat)

# ── world: Nishita sun/sky ─────────────────────────────────────────────────
world = bpy.data.worlds.new("District sky")
scene.world = world
world.use_nodes = True
wnodes, wlinks = world.node_tree.nodes, world.node_tree.links
sky = wnodes.new("ShaderNodeTexSky")
try:
    sky.sky_type = "NISHITA"
    sky.sun_elevation = math.radians(32)
    sky.sun_rotation = math.radians(155)
    sky.sun_intensity = 1.0
    sky.altitude = 30
except Exception:
    pass
bg = wnodes.get("Background")
wlinks.new(sky.outputs["Color"], bg.inputs["Color"])
bg.inputs["Strength"].default_value = 0.55

# ── cameras (track-to empties) ─────────────────────────────────────────────
def make_camera(name, loc, target, lens=35):
    cam_data = bpy.data.cameras.new(name)
    cam_data.lens = lens
    cam = bpy.data.objects.new(name, cam_data)
    scene.collection.objects.link(cam)
    cam.location = loc
    empty = bpy.data.objects.new(name + ".target", None)
    scene.collection.objects.link(empty)
    empty.location = target
    con = cam.constraints.new("TRACK_TO")
    con.target = empty
    con.track_axis = "TRACK_NEGATIVE_Z"
    con.up_axis = "UP_Y"
    return cam

cam_aerial = make_camera("aerial", (215, -75, 115), (66, 52, 6), lens=42)
cam_street = make_camera("street", (66.0, 38.0, 1.7), (95, 68, 12), lens=32)

# ── render settings ────────────────────────────────────────────────────────
scene.render.engine = "CYCLES"
scene.cycles.samples = 64
scene.cycles.use_denoising = True
try:
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for dev_type in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
        try:
            prefs.compute_device_type = dev_type
            prefs.get_devices()
            if any(d.type != "CPU" for d in prefs.devices):
                for d in prefs.devices:
                    d.use = True
                scene.cycles.device = "GPU"
                print(f"GPU rendering via {dev_type}")
                break
        except Exception:
            continue
except Exception:
    pass
scene.render.resolution_x = 1600
scene.render.resolution_y = 1000
scene.view_settings.view_transform = "AgX"
scene.view_settings.exposure = -0.9
scene.view_settings.look = "AgX - Medium High Contrast"

if not os.environ.get("ALMOND_SKIP_RENDER"):
    for cam, out in ((cam_aerial, "blender_aerial.png"), (cam_street, "blender_street.png")):
        scene.camera = cam
        scene.render.filepath = os.path.join(OUT_DIR, out)
        bpy.ops.render.render(write_still=True)
        print(f"rendered {out}")
scene.camera = cam_aerial
blend_path = os.environ.get(
    "ALMOND_BLEND_PATH",
    os.path.join(os.path.expanduser("~"), "Documents", "almond_district.blend"))
bpy.ops.wm.save_as_mainfile(filepath=blend_path)
print(f"saved {blend_path}")
print("DONE")
