"""Rebuild the Almond Modern district in Blender with matched sun + materials.

Run headless:  blender -b -P examples/city_kit_v2/blender_modern.py

Reads the per-material GLBs exported by the driver's EXPORT phase
(modern-mat-<material_id>.glb plus foliage / lampheads / pv splits) from
<scratch>/modern_glb_mat, assigns a Cycles Principled material per file,
and lights the scene with a Sun lamp aimed along the EXACT model-space
sun vector Rhino computed from the user's Sun panel (North 209.2,
azimuth 168.3, altitude 22.4, intensity 2.22) - read from
<scratch>/sun_state.json. Renders an SE aerial and an SE street view,
then saves ~/Documents/almond_modern.blend.

Env: ALMOND_MODERN_SCRATCH (default %TEMP%/almond_modern),
     ALMOND_BLEND_PATH, ALMOND_SKIP_RENDER=1.
"""
import bpy
import glob
import json
import math
import os
import sys

from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from blender_modern_mats import build_rich_material
except Exception as exc:
    print(f"rich materials unavailable ({exc}); using flat recipes")
    build_rich_material = None

SCRATCH = os.environ.get(
    "ALMOND_MODERN_SCRATCH",
    os.path.join(os.environ.get("TEMP", "/tmp"), "almond_modern"))
GLB_DIR = os.path.join(SCRATCH, "modern_glb_mat")
OUT_DIR = SCRATCH

sun_state = {"vector": [-0.6988, -0.6053, -0.3811], "altitude": 22.4, "intensity": 2.22}
try:
    with open(os.path.join(SCRATCH, "sun_state.json")) as fh:
        sun_state = json.load(fh)
except Exception:
    print("sun_state.json missing - using baked-in vector")

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

# ── material recipes keyed by export file stem fragment ─────────────────────
RECIPES = {
    "plaster-white":      dict(base=(0.90, 0.90, 0.88), rough=0.85, bump=0.03),
    "concrete-smooth":    dict(base=(0.70, 0.69, 0.66), rough=0.72, bump=0.05),
    "concrete-boardformed": dict(base=(0.60, 0.58, 0.55), rough=0.85, bump=0.12),
    "steel-painted-sage": dict(base=(0.50, 0.58, 0.42), rough=0.45, metal=0.15),
    "steel-galvanized":   dict(base=(0.62, 0.63, 0.65), rough=0.45, metal=1.0),
    "aluminium-anodized": dict(base=(0.78, 0.78, 0.80), rough=0.30, metal=1.0),
    "metal-corrugated":   dict(base=(0.42, 0.48, 0.38), rough=0.50, metal=0.9),
    "glass-clear":        dict(base=(0.88, 0.94, 0.92), rough=0.03, glass=True),
    "glass-laminated":    dict(base=(0.80, 0.88, 0.86), rough=0.05, glass=True),
    "polycarbonate-opal": dict(base=(0.92, 0.94, 0.90), rough=0.30, glass=True, glass_rough=0.4),
    "polycarbonate-clear": dict(base=(0.88, 0.92, 0.86), rough=0.15, glass=True),
    "wood-oak":           dict(base=(0.50, 0.34, 0.20), rough=0.60, bump=0.03),
    "wood-walnut":        dict(base=(0.30, 0.19, 0.12), rough=0.55),
    "wood-birch-ply":     dict(base=(0.76, 0.62, 0.44), rough=0.65),
    "brick-red":          dict(base=(0.45, 0.19, 0.14), rough=0.90, bump=0.15),
    "rubber-black":       dict(base=(0.05, 0.05, 0.055), rough=0.95),
    "foliage":            dict(base=(0.14, 0.30, 0.10), rough=0.80, bump=0.25),
    "lampheads":          dict(base=(0.90, 0.85, 0.70), rough=0.4, emit=(1.0, 0.85, 0.6), emit_str=8.0),
    "pv":                 dict(base=(0.02, 0.05, 0.14), rough=0.12, metal=0.4),
    "steel-mesh":         dict(base=(0.50, 0.58, 0.40), rough=0.6, metal=0.9),
}


def build_material(name, r):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*r["base"], 1.0)
    bsdf.inputs["Roughness"].default_value = r.get("glass_rough", r.get("rough", 0.5))
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
    stem = os.path.splitext(os.path.basename(glb))[0]      # modern-mat-<id> | modern-foliage
    key = stem.replace("modern-mat-", "").replace("modern-", "")
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
        frag = next((f for f in RECIPES if key == f or key.startswith(f)), key)
        mat = (build_rich_material(f"ALMOND {frag}", frag) if build_rich_material
               else build_material(f"ALMOND {key}", recipe))
        for o in new_objs:
            o.data.materials.clear()
            o.data.materials.append(mat)
print(f"imported {imported_total} meshes from {GLB_DIR}")

# ── normalize units: exported mm arrives kilometres across ─────────────────
xs = [c for o in bpy.data.objects if o.type == "MESH"
      for c in (o.bound_box[0][0] + o.location.x, o.bound_box[6][0] + o.location.x)]
extent = (max(xs) - min(xs)) if xs else 0
if extent > 2000:
    for o in bpy.data.objects:
        if o.parent is None:
            o.scale = (0.001, 0.001, 0.001)
    bpy.context.view_layer.update()
    print(f"scene extent {extent:.0f} -> scaled x0.001")

# ── ground plane (site slab is exported; this catches the horizon) ─────────
bpy.ops.mesh.primitive_plane_add(size=2400, location=(75, 54, -0.42))
ground = bpy.context.active_object
gmat = (build_rich_material("ALMOND ground", "ground") if build_rich_material
        else build_material("ALMOND ground", dict(base=(0.52, 0.52, 0.50), rough=0.9)))
ground.data.materials.append(gmat)

# ── lighting: exact Rhino sun vector + Nishita ambience ────────────────────
d = Vector(sun_state["vector"]).normalized()      # light travel direction (down)
sun_data = bpy.data.lights.new("RhinoSun", type="SUN")
sun_data.energy = float(sun_state.get("intensity", 2.22)) * 2.4   # W/m2, AgX-calibrated
sun_data.angle = math.radians(0.53)
sun = bpy.data.objects.new("RhinoSun", sun_data)
scene.collection.objects.link(sun)
sun.location = (75, 54, 80)
sun.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()

world = bpy.data.worlds.new("Modern sky")
scene.world = world
world.use_nodes = True
wnodes, wlinks = world.node_tree.nodes, world.node_tree.links
sky = wnodes.new("ShaderNodeTexSky")
try:
    sky.sky_type = "NISHITA"
    sky.sun_disc = False
    sky.sun_elevation = math.radians(float(sun_state.get("altitude", 22.4)))
    to_sun = -d
    sky.sun_rotation = math.atan2(to_sun.x, to_sun.y)
    sky.altitude = 20
except Exception:
    pass
bg = wnodes.get("Background")
wlinks.new(sky.outputs["Color"], bg.inputs["Color"])
bg.inputs["Strength"].default_value = 0.5

# ── cameras: SE aerial (matches the Rhino recording view) + SE street ──────
def make_camera(name, loc, target, lens=45):
    cam_data = bpy.data.cameras.new(name)
    cam_data.lens = lens
    cam_data.clip_end = 5000
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

cam_aerial = make_camera("aerial-SE", (262, -112, 102), (75, 54, 9), lens=45)
cam_street = make_camera("street-SE", (146, 40, 2.0), (78, 55, 12), lens=30)

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
            if any(dv.type != "CPU" for dv in prefs.devices):
                for dv in prefs.devices:
                    dv.use = True
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
scene.view_settings.exposure = -0.4
scene.view_settings.look = "AgX - Medium High Contrast"

if not os.environ.get("ALMOND_SKIP_RENDER"):
    for cam, out in ((cam_aerial, "blender_modern_aerial.png"),
                     (cam_street, "blender_modern_street.png")):
        scene.camera = cam
        scene.render.filepath = os.path.join(OUT_DIR, out)
        bpy.ops.render.render(write_still=True)
        print(f"rendered {out}")
scene.camera = cam_aerial
blend_path = os.environ.get(
    "ALMOND_BLEND_PATH",
    os.path.join(os.path.expanduser("~"), "Documents", "almond_modern.blend"))
bpy.ops.wm.save_as_mainfile(filepath=blend_path)
print(f"saved {blend_path}")
print("DONE")
