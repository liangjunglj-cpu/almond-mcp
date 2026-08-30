"""Almond Modern - Blender generation film: sequential assembly + pan finale.

Run headless:  blender -b -P examples/city_kit_v2/blender_modern_anim.py

Rebuilds the district from the per-material GLBs (same materials + exact
sun vector as blender_modern.py), then choreographs a six-shot film:

  shot 1  transit spine assembles (metro -> deck -> hall -> bus) - dolly in
  shot 2  block A slab on pilotis rises - push toward the egg-crate facade
  shot 3  block B ziggurat steps up - glide along the terraces
  shot 4  block C cylinder tower stacks floor by floor - crane straight up
  shot 5  block D bars interlock + sky bridge - swing toward the bridge
  shot 6  urban realm fills in during a parallel aerial pan (the finale)

Every mesh gets its origin centered, then a staggered delta_scale 0 -> 1
animation inside its block's shot window, sorted bottom-up (so towers
stack and ziggurats step). The camera + track target are keyframed per
shot; consecutive shots cut on a single frame.

Frames land in <scratch>/blender_anim; assemble with ffmpeg afterwards.
Env: ALMOND_MODERN_SCRATCH, ALMOND_ANIM_SAMPLES (default 48),
ALMOND_ANIM_END (render only up to this frame, for quick tests).
"""
import bpy
import glob
import json
import math
import os

from mathutils import Vector

SCRATCH = os.environ.get(
    "ALMOND_MODERN_SCRATCH",
    os.path.join(os.environ.get("TEMP", "/tmp"), "almond_modern"))
GLB_DIR = os.path.join(SCRATCH, "modern_glb_mat")
ANIM_DIR = os.path.join(SCRATCH, "blender_anim")
os.makedirs(ANIM_DIR, exist_ok=True)

sun_state = {"vector": [-0.6988, -0.6053, -0.3811], "altitude": 22.4, "intensity": 2.22}
try:
    with open(os.path.join(SCRATCH, "sun_state.json")) as fh:
        sun_state = json.load(fh)
except Exception:
    pass

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

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
    "wood-oak":           dict(base=(0.50, 0.34, 0.20), rough=0.60, bump=0.03),
    "wood-walnut":        dict(base=(0.30, 0.19, 0.12), rough=0.55),
    "wood-birch-ply":     dict(base=(0.76, 0.62, 0.44), rough=0.65),
    "rubber-black":       dict(base=(0.05, 0.05, 0.055), rough=0.95),
    "foliage":            dict(base=(0.14, 0.30, 0.10), rough=0.80, bump=0.25),
    "lampheads":          dict(base=(0.90, 0.85, 0.70), rough=0.4, emit=(1.0, 0.85, 0.6), emit_str=8.0),
    "pv":                 dict(base=(0.02, 0.05, 0.14), rough=0.12, metal=0.4),
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


for glb in sorted(glob.glob(os.path.join(GLB_DIR, "*.glb"))):
    stem = os.path.splitext(os.path.basename(glb))[0]
    key = stem.replace("modern-mat-", "").replace("modern-", "")
    recipe = None
    for frag, r in RECIPES.items():
        if key == frag or key.startswith(frag):
            recipe = r
            break
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=glb)
    new_objs = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
    if recipe:
        mat = build_material(f"ALMOND {key}", recipe)
        for o in new_objs:
            o.data.materials.clear()
            o.data.materials.append(mat)

meshes = [o for o in bpy.data.objects if o.type == "MESH"]
print(f"imported {len(meshes)} meshes")

xs = [c for o in meshes for c in (o.bound_box[0][0] + o.location.x,
                                  o.bound_box[6][0] + o.location.x)]
if xs and (max(xs) - min(xs)) > 2000:
    for o in bpy.data.objects:
        if o.parent is None:
            o.scale = (0.001, 0.001, 0.001)
    bpy.context.view_layer.update()
    print("scaled mm -> m")

# center every mesh's origin so scale-in grows objects in place
bpy.ops.object.select_all(action="DESELECT")
for o in meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="BOUNDS")
bpy.context.view_layer.update()

# ── classify meshes into build groups by world position (meters) ───────────
def world_extent(o):
    pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi

GROUPS = {"base": [], "spine": [], "A": [], "B": [], "C": [], "D": [], "urban": []}
for o in meshes:
    lo, hi = world_extent(o)
    c = (lo + hi) * 0.5
    span = max(hi.x - lo.x, hi.y - lo.y)
    if span > 160:
        g = "base"
    elif 104 <= c.x <= 140 and 2 <= c.y <= 36:
        g = "C"
    elif 44 <= c.x <= 51 and 34 <= c.y <= 50:
        g = "D"           # sky bridge + landing pavilion
    elif 6 <= c.x <= 62 and 4 <= c.y <= 36:
        g = "D"
    elif 6 <= c.x <= 64 and 76 <= c.y <= 98:
        g = "A"
    elif 82 <= c.x <= 144 and 76 <= c.y <= 107:
        g = "B"
    elif 12 <= c.x <= 138 and 43.5 <= c.y <= 64.5:
        g = "spine"
    else:
        g = "urban"
    GROUPS[g].append((o, c, lo.z))
for g, items in GROUPS.items():
    print(f"group {g}: {len(items)} objects")

# ── shot plan (24 fps) ─────────────────────────────────────────────────────
FPS = 24
SHOTS = [
    # (group, start, end, cam0, cam1, tgt0, tgt1, lens)
    ("spine", 1,   96,  (185, -45, 72), (128, 6, 26),  (75, 54, 4),  (75, 54, 8),  35),
    ("A",     97,  192, (118, 38, 34),  (72, 58, 16),  (36, 88, 12), (34, 88, 16), 35),
    ("B",     193, 288, (152, 36, 26),  (122, 58, 22), (113, 92, 8), (110, 90, 12), 35),
    ("C",     289, 384, (192, -55, 8),  (172, -18, 58), (117, 25, 10), (117, 25, 38), 35),
    ("D",     385, 480, (92, -28, 28),  (60, -8, 11),  (34, 18, 8),  (46, 30, 9),  35),
    ("urban", 481, 672, (28, -65, 45),  (114, -65, 45), (28, 50, 8), (114, 50, 8), 32),
]

def stagger(group, s0, s1, spread_frac=0.72, grow=20, sort_mode="z"):
    """Staggered delta_scale 0 -> 1 for every object in the group."""
    items = GROUPS[group]
    if sort_mode == "x":
        items = sorted(items, key=lambda t: (t[1].x, t[2]))
    else:
        items = sorted(items, key=lambda t: (round(t[2] / 3.0), t[1].x, t[1].y))
    n = max(len(items) - 1, 1)
    window = (s1 - s0) * spread_frac
    for i, (o, c, zmin) in enumerate(items):
        t0 = int(s0 + window * i / n)
        t1 = t0 + grow
        o.delta_scale = (0.001, 0.001, 0.001)
        o.keyframe_insert("delta_scale", frame=1)
        o.keyframe_insert("delta_scale", frame=t0)
        o.delta_scale = (1.0, 1.0, 1.0)
        o.keyframe_insert("delta_scale", frame=t1)

for (group, s0, s1, *_rest) in SHOTS:
    if group == "urban":
        stagger(group, s0, s0 + int((s1 - s0) * 0.62), grow=16, sort_mode="x")
    else:
        stagger(group, s0, s1)
for (o, c, z) in GROUPS["base"]:
    o.delta_scale = (1.0, 1.0, 1.0)

# ── ground / sun / sky (same as the stills script) ─────────────────────────
bpy.ops.mesh.primitive_plane_add(size=2400, location=(75, 54, -0.42))
ground = bpy.context.active_object
ground.data.materials.append(build_material("ALMOND ground", dict(base=(0.52, 0.52, 0.50), rough=0.9)))

d = Vector(sun_state["vector"]).normalized()
sun_data = bpy.data.lights.new("RhinoSun", type="SUN")
sun_data.energy = float(sun_state.get("intensity", 2.22)) * 2.4
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
wlinks.new(sky.outputs["Color"], wnodes.get("Background").inputs["Color"])
wnodes.get("Background").inputs["Strength"].default_value = 0.5

# ── one camera + target, keyframed per shot (1-frame jumps = cuts) ─────────
cam_data = bpy.data.cameras.new("filmcam")
cam_data.clip_end = 5000
cam = bpy.data.objects.new("filmcam", cam_data)
scene.collection.objects.link(cam)
target = bpy.data.objects.new("filmcam.target", None)
scene.collection.objects.link(target)
con = cam.constraints.new("TRACK_TO")
con.target = target
con.track_axis = "TRACK_NEGATIVE_Z"
con.up_axis = "UP_Y"
scene.camera = cam

for (group, s0, s1, cam0, cam1, tgt0, tgt1, lens) in SHOTS:
    for frame, cl, tl in ((s0, cam0, tgt0), (s1, cam1, tgt1)):
        cam.location = cl
        cam.keyframe_insert("location", frame=frame)
        target.location = tl
        target.keyframe_insert("location", frame=frame)
        cam_data.lens = lens
        cam_data.keyframe_insert("lens", frame=frame)

# ── render ─────────────────────────────────────────────────────────────────
scene.render.engine = "CYCLES"
scene.cycles.samples = int(os.environ.get("ALMOND_ANIM_SAMPLES", "48"))
scene.cycles.use_denoising = True
scene.render.use_persistent_data = True
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
scene.render.resolution_x = 1280
scene.render.resolution_y = 720
scene.render.fps = FPS
scene.view_settings.view_transform = "AgX"
scene.view_settings.exposure = -0.4
scene.view_settings.look = "AgX - Medium High Contrast"
scene.frame_start = 1
scene.frame_end = int(os.environ.get("ALMOND_ANIM_END", str(SHOTS[-1][2])))
scene.render.filepath = os.path.join(ANIM_DIR, "f")
scene.render.image_settings.file_format = "PNG"

probe = os.environ.get("ALMOND_ANIM_PROBE")
dbg = os.environ.get("ALMOND_ANIM_DEBUGCAM")
if dbg:
    cam.animation_data_clear()
    target.animation_data_clear()
    cx, cy, cz = (float(v) for v in dbg.split(","))
    cam.location = (cx, cy, cz)
    target.location = (122, 20, 25)
if probe:
    for fr in [int(x) for x in probe.split(",")]:
        scene.frame_set(fr)
        scene.render.filepath = os.path.join(ANIM_DIR, f"probe_{fr:04d}.png")
        bpy.ops.render.render(write_still=True)
        print(f"probe {fr} rendered")
else:
    bpy.ops.render.render(animation=True)
print("DONE")
