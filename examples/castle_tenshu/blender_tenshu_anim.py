"""Almond Tenshu - Blender film: slow pans over a techno castle that moves.

Run headless:  blender -b -P examples/castle_tenshu/blender_tenshu_anim.py

Imports the per-assembly/material GLBs from <scratch>/tns_glb
(tns-<assembly>__<matkey>.glb), builds the reference-image palette
(charcoal panel steel, vermilion accents, off-white inlays, stone,
white neon "glow" + orange neon "gloworange"), then a three-shot,
65-second film where the camera and the castle both move:

  shot 1  aggregation reveal (0-20 s)  close on a sannomaru corner
          yagura, slow pull-back reveals turret -> bailey -> bailey ->
          tenshu: the castle aggregates outward from under the camera
  shot 2  slow orbit        (20-46 s)  wide orbit while the tech rings
          counter-rotate and the lantern swarm drifts
  shot 3  the approach      (46-65 s)  flight up the south gate axis,
          over the bridge and the gatehouse chain, rising to the spinning
          apex array against the sky

Castle self-motion (linear, frame 1 -> end):
  ring1 +45deg  ring2 -60deg  apex -140deg  lantern orbit +30deg
  plus per-lantern vertical bob (sine, phase-staggered).

Env: ALMOND_TNS_SCRATCH (default %TEMP%/almond_tenshu),
     ALMOND_ANIM_SAMPLES (default 48), ALMOND_ANIM_PROBE="1,480,...",
     ALMOND_ANIM_START/END, ALMOND_BLEND_PATH.
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
    "ALMOND_TNS_SCRATCH",
    os.path.join(os.environ.get("TEMP", "/tmp"), "almond_tenshu"))
GLB_DIR = os.path.join(SCRATCH, "tns_glb")
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
bpy.context.preferences.edit.keyframe_new_interpolation_type = "LINEAR"

FPS = 24
END = 1560                                   # 65 s

# ── materials ──────────────────────────────────────────────────────────────
def _bsdf(mat):
    mat.use_nodes = True
    return mat.node_tree.nodes.get("Principled BSDF"), mat.node_tree


def build_charcoal(name):
    """Panel steel: seam grid bump, mottled albedo, varied roughness."""
    mat = bpy.data.materials.new(name)
    bsdf, tree = _bsdf(mat)
    bsdf.inputs["Metallic"].default_value = 0.65
    tc = tree.nodes.new("ShaderNodeTexCoord")
    # albedo mottling
    n1 = tree.nodes.new("ShaderNodeTexNoise")
    n1.inputs["Scale"].default_value = 14.0
    mix = tree.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.inputs["Factor"].default_value = 0.5
    mix.inputs[6].default_value = (0.040, 0.045, 0.052, 1.0)
    mix.inputs[7].default_value = (0.060, 0.066, 0.074, 1.0)
    tree.links.new(tc.outputs["Object"], n1.inputs["Vector"])
    tree.links.new(n1.outputs["Fac"], mix.inputs["Factor"])
    tree.links.new(mix.outputs[2], bsdf.inputs["Base Color"])
    # roughness variation
    n2 = tree.nodes.new("ShaderNodeTexNoise")
    n2.inputs["Scale"].default_value = 42.0
    mr = tree.nodes.new("ShaderNodeMapRange")
    mr.inputs["To Min"].default_value = 0.30
    mr.inputs["To Max"].default_value = 0.56
    tree.links.new(tc.outputs["Object"], n2.inputs["Vector"])
    tree.links.new(n2.outputs["Fac"], mr.inputs["Value"])
    tree.links.new(mr.outputs["Result"], bsdf.inputs["Roughness"])
    # panel-seam bump
    brick = tree.nodes.new("ShaderNodeTexBrick")
    brick.inputs["Scale"].default_value = 5.0
    brick.inputs["Mortar Size"].default_value = 0.012
    brick.inputs["Color1"].default_value = (1, 1, 1, 1)
    brick.inputs["Color2"].default_value = (0.92, 0.92, 0.92, 1)
    brick.inputs["Mortar"].default_value = (0, 0, 0, 1)
    bump = tree.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.14
    tree.links.new(tc.outputs["Object"], brick.inputs["Vector"])
    tree.links.new(brick.outputs["Color"], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def build_vermilion(name):
    """Worn painted steel: varied roughness + fine grain."""
    mat = bpy.data.materials.new(name)
    bsdf, tree = _bsdf(mat)
    bsdf.inputs["Base Color"].default_value = (0.70, 0.16, 0.035, 1.0)
    bsdf.inputs["Metallic"].default_value = 0.15
    tc = tree.nodes.new("ShaderNodeTexCoord")
    n2 = tree.nodes.new("ShaderNodeTexNoise")
    n2.inputs["Scale"].default_value = 60.0
    mr = tree.nodes.new("ShaderNodeMapRange")
    mr.inputs["To Min"].default_value = 0.35
    mr.inputs["To Max"].default_value = 0.62
    tree.links.new(tc.outputs["Object"], n2.inputs["Vector"])
    tree.links.new(n2.outputs["Fac"], mr.inputs["Value"])
    tree.links.new(mr.outputs["Result"], bsdf.inputs["Roughness"])
    bump = tree.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.05
    tree.links.new(n2.outputs["Fac"], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def build_glow(name, color, strength):
    mat = bpy.data.materials.new(name)
    bsdf, _ = _bsdf(mat)
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.3
    if "Emission Color" in bsdf.inputs:
        bsdf.inputs["Emission Color"].default_value = (*color, 1.0)
    bsdf.inputs["Emission Strength"].default_value = strength
    return mat


def build_screen(name, color, strength, flicker=False):
    """Interface screen: emission modulated by a grid pattern so panels read
    as glowing UIs, with an optional slow flicker."""
    mat = bpy.data.materials.new(name)
    bsdf, tree = _bsdf(mat)
    bsdf.inputs["Base Color"].default_value = (0.01, 0.012, 0.016, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.25
    if "Emission Color" in bsdf.inputs:
        bsdf.inputs["Emission Color"].default_value = (*color, 1.0)
    brick = tree.nodes.new("ShaderNodeTexBrick")
    brick.inputs["Scale"].default_value = 24.0
    brick.inputs["Color1"].default_value = (1.0, 1.0, 1.0, 1.0)
    brick.inputs["Color2"].default_value = (0.15, 0.15, 0.15, 1.0)
    brick.inputs["Mortar"].default_value = (0.0, 0.0, 0.0, 1.0)
    brick.inputs["Mortar Size"].default_value = 0.015
    val = tree.nodes.new("ShaderNodeValue")
    val.outputs[0].default_value = strength
    mult = tree.nodes.new("ShaderNodeMath")
    mult.operation = "MULTIPLY"
    tree.links.new(brick.outputs["Fac"], mult.inputs[0])
    tree.links.new(val.outputs[0], mult.inputs[1])
    tree.links.new(mult.outputs[0], bsdf.inputs["Emission Strength"])
    if flicker:
        for f in range(1, END + 1, 16):
            val.outputs[0].default_value = strength * (1.0 + 0.22 * math.sin(f * 0.37))
            val.outputs[0].keyframe_insert("default_value", frame=f)
    return mat


def build_flat(name, base, rough=0.6, metal=0.0):
    mat = bpy.data.materials.new(name)
    bsdf, _ = _bsdf(mat)
    bsdf.inputs["Base Color"].default_value = (*base, 1.0)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    return mat


def build_granite(name):
    mat = bpy.data.materials.new(name)
    bsdf, tree = _bsdf(mat)
    tc = tree.nodes.new("ShaderNodeTexCoord")
    n1 = tree.nodes.new("ShaderNodeTexNoise")
    n1.inputs["Scale"].default_value = 900.0
    mix = tree.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.inputs[6].default_value = (0.30, 0.30, 0.29, 1.0)
    mix.inputs[7].default_value = (0.42, 0.42, 0.41, 1.0)
    tree.links.new(tc.outputs["Object"], n1.inputs["Vector"])
    tree.links.new(n1.outputs["Fac"], mix.inputs["Factor"])
    tree.links.new(mix.outputs[2], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.55
    # paving-slab seam bump
    brick = tree.nodes.new("ShaderNodeTexBrick")
    brick.inputs["Scale"].default_value = 1.6
    brick.inputs["Mortar Size"].default_value = 0.02
    bump = tree.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.2
    tree.links.new(tc.outputs["Object"], brick.inputs["Vector"])
    tree.links.new(brick.outputs["Fac"], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def build_gravel(name):
    """Raked karesansui gravel: wave-texture rake lines + fine grain."""
    mat = bpy.data.materials.new(name)
    bsdf, tree = _bsdf(mat)
    bsdf.inputs["Base Color"].default_value = (0.33, 0.31, 0.27, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.95
    tc = tree.nodes.new("ShaderNodeTexCoord")
    wave = tree.nodes.new("ShaderNodeTexWave")
    wave.inputs["Scale"].default_value = 3.2
    wave.inputs["Distortion"].default_value = 3.0
    grain = tree.nodes.new("ShaderNodeTexNoise")
    grain.inputs["Scale"].default_value = 1400.0
    add = tree.nodes.new("ShaderNodeMath")
    add.operation = "ADD"
    bump = tree.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.35
    tree.links.new(tc.outputs["Object"], wave.inputs["Vector"])
    tree.links.new(tc.outputs["Object"], grain.inputs["Vector"])
    tree.links.new(wave.outputs["Fac"], add.inputs[0])
    tree.links.new(grain.outputs["Fac"], add.inputs[1])
    tree.links.new(add.outputs[0], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def build_water(name):
    mat = bpy.data.materials.new(name)
    bsdf, tree = _bsdf(mat)
    bsdf.inputs["Base Color"].default_value = (0.010, 0.018, 0.025, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.02
    bsdf.inputs["Metallic"].default_value = 0.1
    n = tree.nodes.new("ShaderNodeTexNoise")
    n.inputs["Scale"].default_value = 14.0
    bump = tree.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.015
    tree.links.new(n.outputs["Fac"], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


_mat_cache = {}

def material_for(key):
    if key in _mat_cache:
        return _mat_cache[key]
    if key == "steel-painted-charcoal":
        mat = build_charcoal("ALMOND charcoal")
    elif key == "concrete-smooth":
        # this kit's concrete-smooth is only the ground slab + bridge deck:
        # render them as dark asphalt to match the reference ground
        mat = build_flat("ALMOND asphalt", (0.028, 0.032, 0.038), rough=0.9)
    elif key == "steel-painted-vermilion":
        mat = build_vermilion("ALMOND vermilion")
    elif key == "glow":
        mat = build_glow("ALMOND neon white", (0.95, 0.97, 1.0), 2.6)
    elif key == "gloworange":
        mat = build_glow("ALMOND neon orange", (1.0, 0.36, 0.07), 3.0)
    elif key == "glowcyan":
        mat = build_screen("ALMOND screen cyan", (0.25, 0.85, 1.0), 2.4, flicker=True)
    elif key == "glowwarm":
        mat = build_glow("ALMOND window warm", (1.0, 0.62, 0.25), 1.8)
    elif key == "stone-granite-paving":
        mat = build_granite("ALMOND granite")
    elif key == "gravel-raked":
        mat = build_gravel("ALMOND gravel")
    elif key == "water-still":
        mat = build_water("ALMOND water")
    elif key == "foliage-pine":
        mat = (build_rich_material("ALMOND pine", "foliage") if build_rich_material
               else build_flat("ALMOND pine", (0.10, 0.20, 0.09), rough=0.85))
    elif build_rich_material:
        mat = build_rich_material(f"ALMOND {key}", key)
    else:
        mat = build_flat(f"ALMOND {key}", (0.6, 0.6, 0.6))
    _mat_cache[key] = mat
    return mat


# ── import per-assembly/material GLBs ──────────────────────────────────────
ASM = {}
for glb in sorted(glob.glob(os.path.join(GLB_DIR, "*.glb"))):
    stem = os.path.splitext(os.path.basename(glb))[0]   # tns-<asm>__<matkey>
    body = stem[4:] if stem.startswith("tns-") else stem
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

bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")
for o in [o for o in bpy.data.objects if o.type != "MESH"]:
    bpy.data.objects.remove(o, do_unlink=True)
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
print(f"imported {len(meshes)} meshes")

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
SPIN = {"ring1": 45, "ring2": -60, "apex": -140}
for asm, deg in SPIN.items():
    if not ASM.get(asm):
        continue
    e = make_empty(f"spin.{asm}")
    parent_to(ASM[asm], e)
    linear_spin(e, deg)

if ASM.get("holo"):
    # holographic interface panels: slow individual spin + bob
    for i, o in enumerate(ASM["holo"]):
        cen = centroid(o)
        sub = make_empty(f"holo.{i}", loc=cen)
        parent_to([o], sub)
        linear_spin(sub, 25 if i % 2 == 0 else -25)
        amp = 0.35 + 0.05 * (i % 4)
        period = FPS * (18 + (i % 5) * 4)
        base_z = sub.location.z
        for f in range(1, END + 1, 10):
            sub.location.z = base_z + amp * math.sin(2 * math.pi * f / period + i)
            sub.keyframe_insert("location", index=2, frame=f)

if ASM.get("lanterns"):
    master = make_empty("lanterns.orbit")
    clusters = {}
    for o in ASM["lanterns"]:
        c = centroid(o)
        k = round(math.degrees(math.atan2(c.y, c.x)) / 15.0) % 24
        clusters.setdefault(k, []).append(o)
    for k, objs in clusters.items():
        cen = sum((centroid(o) for o in objs), Vector()) / len(objs)
        sub = make_empty(f"lantern.{k}", loc=cen, parent=master)
        parent_to(objs, sub)
        sub.scale = (2.2, 2.2, 2.2)          # lanterns read at film distance
        amp = 0.7 + 0.05 * (k % 5)
        period = FPS * (22 + (k % 7) * 3)
        phase = k * math.pi / 6
        base_z = sub.location.z
        for f in range(1, END + 1, 8):
            sub.location.z = base_z + amp * math.sin(2 * math.pi * f / period + phase)
            sub.keyframe_insert("location", index=2, frame=f)
    linear_spin(master, 30)
    print({k: len(v) for k, v in sorted(clusters.items())})

# ── ground / sun / sky ─────────────────────────────────────────────────────
# wet-asphalt ground: puddle-patched roughness so lights reflect unevenly
bpy.ops.mesh.primitive_plane_add(size=60000, location=(0, 0, -0.42))
ground = bpy.context.active_object
gmat = bpy.data.materials.new("ALMOND ground wet")
gb, gtree = _bsdf(gmat)
gb.inputs["Base Color"].default_value = (0.016, 0.019, 0.024, 1.0)
gtc = gtree.nodes.new("ShaderNodeTexCoord")
gn = gtree.nodes.new("ShaderNodeTexNoise")
gn.inputs["Scale"].default_value = 2.4
gmr = gtree.nodes.new("ShaderNodeMapRange")
gmr.inputs["To Min"].default_value = 0.07
gmr.inputs["To Max"].default_value = 0.45
gtree.links.new(gtc.outputs["Object"], gn.inputs["Vector"])
gtree.links.new(gn.outputs["Fac"], gmr.inputs["Value"])
gtree.links.new(gmr.outputs["Result"], gb.inputs["Roughness"])
gn2 = gtree.nodes.new("ShaderNodeTexNoise")
gn2.inputs["Scale"].default_value = 400.0
gbmp = gtree.nodes.new("ShaderNodeBump")
gbmp.inputs["Strength"].default_value = 0.03
gtree.links.new(gtc.outputs["Object"], gn2.inputs["Vector"])
gtree.links.new(gn2.outputs["Fac"], gbmp.inputs["Height"])
gtree.links.new(gbmp.outputs["Normal"], gb.inputs["Normal"])
ground.data.materials.append(gmat)

# night: a dim cool moon along the Rhino sun vector keeps the massing
# legible; the neon, screens and windows carry the scene
d = Vector(sun_state["vector"]).normalized()
sun_data = bpy.data.lights.new("Moon", type="SUN")
sun_data.energy = 1.35
sun_data.color = (0.55, 0.66, 1.0)
sun_data.angle = math.radians(0.53)
sun = bpy.data.objects.new("Moon", sun_data)
scene.collection.objects.link(sun)
sun.location = (0, 0, 120)
sun.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()

# near-black night sky with the faintest blue gradient
world = bpy.data.worlds.new("Tenshu night")
scene.world = world
world.use_nodes = True
wnodes = world.node_tree.nodes
bg = wnodes.get("Background")
bg.inputs["Color"].default_value = (0.006, 0.009, 0.018, 1.0)
bg.inputs["Strength"].default_value = 1.0

# ── camera: three slow shots ───────────────────────────────────────────────
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

# sannomaru SE corner yagura at (98, -88)
SHOTS = [
    # (start, end, cam0, cam1, tgt0, tgt1, lens)
    (1,    480,  (114, -103, 9),  (165, -150, 48), (98, -88, 7),  (0, 0, 22), 35),
    (481,  1104, None, None, (0, 0, 16), (0, 0, 28), 38),        # orbit, filled below
    (1105, 1560, (30, -215, 8),   (12, -82, 70),   (0, -60, 10), (0, 0, 48), 32),
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

# shot 2: slow orbit, baked so the arc stays true, final frame keyed exactly
s0, s1 = 481, 1104
R0, R1, Z0, Z1, A0, A1 = 172.0, 148.0, 42.0, 70.0, 318.0, 222.0
for f in list(range(s0, s1 + 1, 12)) + [s1]:
    t = (f - s0) / (s1 - s0)
    a = math.radians(A0 + (A1 - A0) * t)
    R = R0 + (R1 - R0) * t
    cam.location = (R * math.cos(a), R * math.sin(a), Z0 + (Z1 - Z0) * t)
    cam.keyframe_insert("location", frame=f)
    target.location = (0, 0, 16 + 12 * t)
    target.keyframe_insert("location", frame=f)
    cam_data.lens = 38
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
scene.view_settings.exposure = -0.15         # night: emissives carry the scene
scene.view_settings.look = "AgX - Medium High Contrast"

# bloom so the neon and screens visibly luminesce (Blender 5.x compositor
# node group: scene.compositing_node_group, Glare params are input sockets)
try:
    ct = bpy.data.node_groups.new("TenshuComp", "CompositorNodeTree")
    scene.compositing_node_group = ct
    ct.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    rl = ct.nodes.new("CompositorNodeRLayers")
    glare = ct.nodes.new("CompositorNodeGlare")
    out = ct.nodes.new("NodeGroupOutput")
    for tv in ("BLOOM", "Bloom", "FOG_GLOW"):
        try:
            glare.inputs["Type"].default_value = tv
            break
        except Exception:
            continue
    for name, v in (("Threshold", 1.0), ("Strength", 0.3), ("Size", 0.5),
                    ("Quality", "HIGH"), ("Saturation", 1.0)):
        try:
            glare.inputs[name].default_value = v
        except Exception:
            pass
    ct.links.new(rl.outputs["Image"], glare.inputs["Image"])
    ct.links.new(glare.outputs["Image"], out.inputs["Image"])
    scene.render.use_compositing = True
    print("bloom compositor armed")
except Exception as exc:
    print(f"compositor unavailable ({exc}); rendering without bloom")
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
