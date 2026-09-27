"""Almond Infinity - Blender film: slow pans over a castle that moves.

Run headless:  blender -b -P examples/infinity_castle/blender_infinity_anim.py

Imports the per-assembly/material GLBs exported by the driver's EXPORT
phase (inf-<assembly>__<matkey>.glb from <scratch>/inf_glb), rebuilds the
material palette (rich textured materials shared with city kit v2, plus a
cyan emissive for every "glow" file), then choreographs a three-shot,
65-second film where the CAMERA and the CASTLE both move:

  shot 1  fractal reveal   (0-20 s)  close-up on a grandchild mini-castle,
          an unbroken slow pull-back reveals it stands on a castle that
          stands on the castle - the infinity read
  shot 2  slow orbit       (20-46 s) quarter orbit at distance while the
          halo rings counter-rotate and the islets drift past
  shot 3  the ascent       (46-65 s) slow rise up the spiral ziggurat to
          the rotating crown, ending wide against the sky

Castle self-motion (linear, frame 1 -> end):
  ring1 +55deg  ring2 -40deg  ring3 +70deg  crown -90deg  islet orbit +25deg
  plus a per-islet vertical bob (sine, 28-40 s periods, phase-staggered).

Frames land in <scratch>/blender_anim; assemble with ffmpeg afterwards.
Env: ALMOND_INF_SCRATCH (default %TEMP%/almond_infinity),
     ALMOND_ANIM_SAMPLES (default 48),
     ALMOND_ANIM_PROBE="1,480,900" (render only those frames, as stills),
     ALMOND_ANIM_START / ALMOND_ANIM_END (sub-range render for chunking),
     ALMOND_BLEND_PATH (saves the scene when set).
"""
import bpy
import glob
import json
import math
import os
import sys

from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "city_kit_v2"))
try:
    from blender_modern_mats import build_rich_material
except Exception as exc:
    print(f"rich materials unavailable ({exc}); using flat recipes")
    build_rich_material = None

SCRATCH = os.environ.get(
    "ALMOND_INF_SCRATCH",
    os.path.join(os.environ.get("TEMP", "/tmp"), "almond_infinity"))
GLB_DIR = os.path.join(SCRATCH, "inf_glb")
ANIM_DIR = os.path.join(SCRATCH, "blender_anim")
os.makedirs(ANIM_DIR, exist_ok=True)

sun_state = {"vector": [-0.6988, -0.6053, -0.3811], "altitude": 22.4, "intensity": 2.22}
try:
    with open(os.path.join(SCRATCH, "sun_state.json")) as fh:
        sun_state = json.load(fh)
except Exception:
    print("sun_state.json missing - using baked-in vector")

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
# Blender 5.x slotted actions dropped action.fcurves; make every inserted
# keyframe linear at the source instead
bpy.context.preferences.edit.keyframe_new_interpolation_type = "LINEAR"

FPS = 24
END = 1560                                   # 65 s

# ── materials ──────────────────────────────────────────────────────────────
FLAT = {
    "plaster-white":      dict(base=(0.90, 0.90, 0.88), rough=0.85),
    "concrete-smooth":    dict(base=(0.70, 0.69, 0.66), rough=0.72),
    "concrete-boardformed": dict(base=(0.60, 0.58, 0.55), rough=0.85),
    "steel-galvanized":   dict(base=(0.62, 0.63, 0.65), rough=0.45, metal=1.0),
    "aluminium-anodized": dict(base=(0.78, 0.78, 0.80), rough=0.30, metal=1.0),
    "glass-clear":        dict(base=(0.88, 0.94, 0.92), rough=0.03, glass=True),
    "rubber-black":       dict(base=(0.05, 0.05, 0.055), rough=0.95),
}


def build_flat(name, r):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*r["base"], 1.0)
    bsdf.inputs["Roughness"].default_value = r.get("rough", 0.5)
    if "metal" in r:
        bsdf.inputs["Metallic"].default_value = r["metal"]
    if r.get("glass"):
        key = "Transmission Weight" if "Transmission Weight" in bsdf.inputs else "Transmission"
        bsdf.inputs[key].default_value = 1.0
        bsdf.inputs["IOR"].default_value = 1.45
    return mat


def build_glow(name):
    """Cyan emissive for all light bands - the castle's energy signature."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (0.30, 0.85, 1.0, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.3
    if "Emission Color" in bsdf.inputs:
        bsdf.inputs["Emission Color"].default_value = (0.25, 0.85, 1.0, 1.0)
    bsdf.inputs["Emission Strength"].default_value = 30.0
    return mat


_mat_cache = {}

def material_for(key):
    if key in _mat_cache:
        return _mat_cache[key]
    if key == "glow":
        mat = build_glow("ALMOND glow")
    elif build_rich_material:
        mat = build_rich_material(f"ALMOND {key}", key)
    else:
        mat = build_flat(f"ALMOND {key}", FLAT.get(key, dict(base=(0.6, 0.6, 0.6))))
    _mat_cache[key] = mat
    return mat


# ── import per-assembly/material GLBs ──────────────────────────────────────
ASM = {}                                    # assembly -> [mesh objects]
for glb in sorted(glob.glob(os.path.join(GLB_DIR, "*.glb"))):
    stem = os.path.splitext(os.path.basename(glb))[0]   # inf-<asm>__<matkey>
    body = stem[4:] if stem.startswith("inf-") else stem
    asm, _, matkey = body.partition("__")
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=glb)
    new = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in new if o.type == "MESH"]
    mat = material_for(matkey or "concrete-smooth")
    for o in meshes:
        o.data.materials.clear()
        o.data.materials.append(mat)
    ASM.setdefault(asm, []).extend(meshes)
print({a: len(v) for a, v in ASM.items()})

# flatten any importer hierarchy, then drop non-mesh leftovers
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")
for o in [o for o in bpy.data.objects if o.type != "MESH"]:
    bpy.data.objects.remove(o, do_unlink=True)
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
print(f"imported {len(meshes)} meshes")

# normalize units: exported mm arrives 1000x too large
xs = [(o.matrix_world @ Vector(c)).x for o in meshes for c in (o.bound_box[0], o.bound_box[6])]
if xs and (max(xs) - min(xs)) > 2000:
    S = Matrix.Scale(0.001, 4)
    for o in meshes:
        o.matrix_world = S @ o.matrix_world
    bpy.context.view_layer.update()
    print("scaled mm -> m")


def centroid(o):
    pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
    return sum(pts, Vector()) / 8.0


def make_empty(name, loc=(0, 0, 0), parent=None):
    e = bpy.data.objects.new(name, None)
    scene.collection.objects.link(e)
    e.location = loc
    if parent is not None:
        e.parent = parent
    return e


def parent_to(objs, empty):
    inv = empty.matrix_world.inverted()
    for o in objs:
        o.parent = empty
        o.matrix_parent_inverse = inv


def linear_spin(empty, degrees):
    empty.rotation_mode = "XYZ"
    empty.rotation_euler = (0, 0, 0)
    empty.keyframe_insert("rotation_euler", frame=1)
    empty.rotation_euler = (0, 0, math.radians(degrees))
    empty.keyframe_insert("rotation_euler", frame=END)


# ── castle self-motion ─────────────────────────────────────────────────────
SPIN = {"ring1": 55, "ring2": -40, "ring3": 70, "crown": -90}
for asm, deg in SPIN.items():
    if not ASM.get(asm):
        continue
    e = make_empty(f"spin.{asm}")
    parent_to(ASM[asm], e)
    linear_spin(e, deg)

if ASM.get("islets"):
    master = make_empty("islets.orbit")
    # cluster islet meshes by bearing (islets sit at 15 + k*60 degrees)
    clusters = {}
    for o in ASM["islets"]:
        c = centroid(o)
        k = round((math.degrees(math.atan2(c.y, c.x)) - 15.0) / 60.0) % 6
        clusters.setdefault(k, []).append(o)
    for k, objs in clusters.items():
        cen = sum((centroid(o) for o in objs), Vector()) / len(objs)
        sub = make_empty(f"islet.{k}", loc=cen, parent=master)
        parent_to(objs, sub)
        # vertical bob: phase-staggered sine, baked every 8 frames
        amp = 0.9 + 0.18 * k
        period = FPS * (28 + 2 * k)
        phase = k * math.pi / 3
        base_z = sub.location.z
        for f in range(1, END + 1, 8):
            sub.location.z = base_z + amp * math.sin(2 * math.pi * f / period + phase)
            sub.keyframe_insert("location", index=2, frame=f)
    linear_spin(master, 25)
    print({k: len(v) for k, v in clusters.items()})

# ── ground / sun / sky ─────────────────────────────────────────────────────
bpy.ops.mesh.primitive_plane_add(size=24000, location=(0, 0, -0.42))
ground = bpy.context.active_object
ground.data.materials.append(
    build_rich_material("ALMOND ground", "ground") if build_rich_material
    else build_flat("ALMOND ground", dict(base=(0.52, 0.52, 0.50), rough=0.9)))

d = Vector(sun_state["vector"]).normalized()
sun_data = bpy.data.lights.new("RhinoSun", type="SUN")
sun_data.energy = float(sun_state.get("intensity", 2.22)) * 2.4
sun_data.angle = math.radians(0.53)
sun = bpy.data.objects.new("RhinoSun", sun_data)
scene.collection.objects.link(sun)
sun.location = (0, 0, 120)
sun.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()

world = bpy.data.worlds.new("Infinity sky")
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

# ── camera: three slow shots (cuts on a single frame) ──────────────────────
cam_data = bpy.data.cameras.new("filmcam")
cam_data.clip_start = 0.5
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

# grandchild mini-castle on the SE corner castle: ~(40.8, -40.8, 74)
SHOTS = [
    # (start, end, cam0, cam1, tgt0, tgt1, lens)
    (1,    480,  (56, -56, 77.5),  (125, -125, 60), (40.8, -40.8, 74.5), (0, 0, 45), 35),
    (481,  1104, None, None, (0, 0, 40), (0, 0, 44), 36),        # orbit, filled below
    (1105, 1560, (40, -150, 14),   (12, -68, 60),   (0, 0, 26), (0, 0, 74), 32),
]

for (s0, s1, cam0, cam1, tgt0, tgt1, lens) in SHOTS:
    if cam0 is None:
        continue
    for frame, cl, tl in ((s0, cam0, tgt0), (s1, cam1, tgt1)):
        cam.location = cl
        cam.keyframe_insert("location", frame=frame)
        target.location = tl
        target.keyframe_insert("location", frame=frame)
        cam_data.lens = lens
        cam_data.keyframe_insert("lens", frame=frame)

# shot 2: slow quarter orbit, baked every 12 frames so the arc stays true
s0, s1 = 481, 1104
R0, R1, Z0, Z1, A0, A1 = 175.0, 160.0, 64.0, 88.0, 318.0, 222.0
for f in list(range(s0, s1 + 1, 12)) + [s1]:
    t = (f - s0) / (s1 - s0)
    a = math.radians(A0 + (A1 - A0) * t)
    R = R0 + (R1 - R0) * t
    cam.location = (R * math.cos(a), R * math.sin(a), Z0 + (Z1 - Z0) * t)
    cam.keyframe_insert("location", frame=f)
    target.location = (0, 0, 40 + 4 * t)
    target.keyframe_insert("location", frame=f)
    cam_data.lens = 36
    cam_data.keyframe_insert("lens", frame=f)

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
scene.view_settings.exposure = -1.55         # all-white palette blows out above this
scene.view_settings.look = "AgX - Medium High Contrast"
scene.frame_start = int(os.environ.get("ALMOND_ANIM_START", "1"))
scene.frame_end = int(os.environ.get("ALMOND_ANIM_END", str(END)))
scene.render.filepath = os.path.join(ANIM_DIR, "f")
scene.render.image_settings.file_format = "PNG"

blend_path = os.environ.get("ALMOND_BLEND_PATH")
probe = os.environ.get("ALMOND_ANIM_PROBE")
if probe:
    for fr in [int(x) for x in probe.split(",")]:
        scene.frame_set(fr)
        scene.render.filepath = os.path.join(ANIM_DIR, f"probe_{fr:04d}.png")
        bpy.ops.render.render(write_still=True)
        print(f"probe {fr} rendered")
else:
    bpy.ops.render.render(animation=True)
if blend_path:
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    print(f"saved {blend_path}")
print("DONE")
