"""Almond Celestia - Blender film: bright anime-day sky-citadel in motion.

Run headless:  blender -b -P examples/castle_celestia/blender_celestia_anim.py

Imports the per-assembly/material GLBs from <scratch>/sky_glb
(sky-<assembly>__<matkey>.glb) and rebuilds the Genshin-inspired grade:
EEVEE at 1920x1080, Standard view transform, a gradient-sky backdrop
sphere (warm horizon -> cerulean zenith), a sea of stylized flat cloud
discs below the island, warm sun + soft blue ambient, facing-gradient
glazed-teal roofs, polished gold, ivory drums, mint foliage, and cyan /
gold emissive accents with compositor bloom.

Three-shot, 65-second film where everything moves:
  shot 1  the rise      (0-20 s)  from beneath the cloud sea, past the
          glowing under-crystals and a waterfall, up over the island rim
  shot 2  grand orbit   (20-46 s) wide orbit while the energy rings spin,
          the crystal swarm drifts, sigils rotate, islands orbit + bob
  shot 3  the ascent    (46-65 s) approach from the south and climb the
          drum-spire to the crown, the gold halo turning behind it

Motion (linear over the film): ring1 +50, ring2 -38, ring3 +65,
crown -120, vertical halo +90 (about its own axis), sigils spin
individually, crystal swarm + satellite islands orbit and bob.

Env: ALMOND_SKY_SCRATCH (default %TEMP%/almond_celestia),
     ALMOND_ANIM_SAMPLES (default 48), ALMOND_ANIM_PROBE="1,480,...",
     ALMOND_ANIM_START/END, ALMOND_BLEND_PATH.
"""
import bpy
import glob
import math
import os

from mathutils import Matrix, Vector

SCRATCH = os.environ.get(
    "ALMOND_SKY_SCRATCH",
    os.path.join(os.environ.get("TEMP", "/tmp"), "almond_celestia"))
GLB_DIR = os.path.join(SCRATCH, "sky_glb")
ANIM_DIR = os.path.join(SCRATCH, "blender_anim")
os.makedirs(ANIM_DIR, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
bpy.context.preferences.edit.keyframe_new_interpolation_type = "LINEAR"

FPS = 24
END = 1560

# ── materials (anime-flat, saturated pastel) ───────────────────────────────
def _bsdf(mat):
    mat.use_nodes = True
    return mat.node_tree.nodes.get("Principled BSDF"), mat.node_tree


def flat(name, base, rough=0.8, metal=0.0):
    mat = bpy.data.materials.new(name)
    bsdf, _ = _bsdf(mat)
    bsdf.inputs["Base Color"].default_value = (*base, 1.0)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    return mat


def noisy(name, c1, c2, scale=18.0, rough=0.9):
    mat = bpy.data.materials.new(name)
    bsdf, tree = _bsdf(mat)
    bsdf.inputs["Roughness"].default_value = rough
    tc = tree.nodes.new("ShaderNodeTexCoord")
    n = tree.nodes.new("ShaderNodeTexNoise")
    n.inputs["Scale"].default_value = scale
    mix = tree.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.inputs[6].default_value = (*c1, 1.0)
    mix.inputs[7].default_value = (*c2, 1.0)
    tree.links.new(tc.outputs["Object"], n.inputs["Vector"])
    tree.links.new(n.outputs["Fac"], mix.inputs["Factor"])
    tree.links.new(mix.outputs[2], bsdf.inputs["Base Color"])
    return mat


def teal_roof(name):
    """Glazed teal with a facing gradient - the anime roof sheen."""
    mat = bpy.data.materials.new(name)
    bsdf, tree = _bsdf(mat)
    bsdf.inputs["Roughness"].default_value = 0.35
    lw = tree.nodes.new("ShaderNodeLayerWeight")
    lw.inputs["Blend"].default_value = 0.45
    mix = tree.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.inputs[6].default_value = (0.09, 0.30, 0.34, 1.0)
    mix.inputs[7].default_value = (0.30, 0.62, 0.62, 1.0)
    tree.links.new(lw.outputs["Facing"], mix.inputs["Factor"])
    tree.links.new(mix.outputs[2], bsdf.inputs["Base Color"])
    return mat


def glow(name, color, strength, base=None):
    mat = bpy.data.materials.new(name)
    bsdf, _ = _bsdf(mat)
    bsdf.inputs["Base Color"].default_value = (*(base or color), 1.0)
    bsdf.inputs["Roughness"].default_value = 0.4
    if "Emission Color" in bsdf.inputs:
        bsdf.inputs["Emission Color"].default_value = (*color, 1.0)
    bsdf.inputs["Emission Strength"].default_value = strength
    return mat


_cache = {}

def material_for(key):
    if key in _cache:
        return _cache[key]
    if key == "plaster-white":
        mat = flat("SKY ivory", (0.93, 0.90, 0.84), rough=0.8)
    elif key == "brass-polished":
        mat = flat("SKY gold", (0.78, 0.57, 0.20), rough=0.32, metal=1.0)
    elif key == "ceramic-teal":
        mat = teal_roof("SKY teal roof")
    elif key == "stone-granite-paving":
        mat = flat("SKY marble", (0.80, 0.78, 0.74), rough=0.55)
    elif key == "concrete-boardformed":
        mat = noisy("SKY rock", (0.42, 0.37, 0.32), (0.58, 0.52, 0.44), scale=9.0)
    elif key == "grass-meadow":
        mat = noisy("SKY meadow", (0.42, 0.64, 0.36), (0.56, 0.78, 0.47), scale=26.0)
    elif key == "foliage-pine":
        mat = noisy("SKY mint canopy", (0.36, 0.66, 0.42), (0.50, 0.80, 0.55), scale=40.0)
    elif key == "wood-walnut":
        mat = flat("SKY walnut", (0.28, 0.18, 0.11), rough=0.7)
    elif key == "glowcyan":
        mat = glow("SKY cyan", (0.30, 0.90, 1.0), 2.2)
    elif key == "glowgold":
        mat = glow("SKY goldlight", (1.0, 0.78, 0.32), 2.6)
    elif key == "waterfall":
        mat = glow("SKY waterfall", (0.72, 0.88, 0.97), 0.4, base=(0.80, 0.90, 0.97))
    elif key == "mist":
        mat = glow("SKY mist", (1.0, 1.0, 1.0), 0.4)
    else:
        mat = flat(f"SKY {key}", (0.7, 0.7, 0.7))
    _cache[key] = mat
    return mat


# ── import per-assembly/material GLBs ──────────────────────────────────────
ASM = {}
for glb in sorted(glob.glob(os.path.join(GLB_DIR, "*.glb"))):
    stem = os.path.splitext(os.path.basename(glb))[0]   # sky-<asm>__<matkey>
    body = stem[4:] if stem.startswith("sky-") else stem
    asm, _, matkey = body.partition("__")
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=glb)
    new = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in new if o.type == "MESH"]
    mat = material_for(matkey or "plaster-white")
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


def linear_spin(empty, degrees, axis=2):
    empty.rotation_mode = "XYZ"
    rot = [0.0, 0.0, 0.0]
    empty.rotation_euler = rot
    empty.keyframe_insert("rotation_euler", frame=1)
    rot[axis] = math.radians(degrees)
    empty.rotation_euler = rot
    empty.keyframe_insert("rotation_euler", frame=END)


def bob(empty, amp, period_s, phase):
    base_z = empty.location.z
    for f in range(1, END + 1, 10):
        empty.location.z = base_z + amp * math.sin(2 * math.pi * f / (FPS * period_s) + phase)
        empty.keyframe_insert("location", index=2, frame=f)


# ── motion ─────────────────────────────────────────────────────────────────
for asm, deg in (("ring1", 50), ("ring2", -38), ("ring3", 65), ("crown", -120)):
    if ASM.get(asm):
        e = make_empty(f"spin.{asm}")
        parent_to(ASM[asm], e)
        linear_spin(e, deg)

if ASM.get("vring"):
    e = make_empty("spin.vring", loc=(0, 19, 96))
    parent_to(ASM["vring"], e)
    linear_spin(e, 90, axis=1)

if ASM.get("sigil"):
    for i, o in enumerate(ASM["sigil"]):
        sub = make_empty(f"sigil.{i}", loc=centroid(o))
        parent_to([o], sub)
        linear_spin(sub, 180 if i % 2 == 0 else -180)
        bob(sub, 0.5 + 0.1 * (i % 3), 16 + (i % 5) * 3, i * 0.7)

if ASM.get("crys"):
    master = make_empty("crys.orbit")
    for i, o in enumerate(ASM["crys"]):
        sub = make_empty(f"crys.{i}", loc=centroid(o), parent=master)
        parent_to([o], sub)
        linear_spin(sub, 120 if i % 2 == 0 else -120)
        bob(sub, 0.6 + 0.12 * (i % 4), 14 + (i % 6) * 3, i)
    linear_spin(master, 15)

if ASM.get("islands"):
    master = make_empty("islands.orbit")
    clusters = {}
    for o in ASM["islands"]:
        c = centroid(o)
        k = round((math.degrees(math.atan2(c.y, c.x)) - 10.0) / 36.0) % 10
        clusters.setdefault(k, []).append(o)
    for k, objs in clusters.items():
        cen = sum((centroid(o) for o in objs), Vector()) / len(objs)
        sub = make_empty(f"island.{k}", loc=cen, parent=master)
        parent_to(objs, sub)
        bob(sub, 1.6 + 0.2 * (k % 4), 30 + (k % 5) * 5, k * 0.6)
    linear_spin(master, 10)
    print({k: len(v) for k, v in sorted(clusters.items())})

# ── sky: gradient backdrop sphere + soft ambient + warm sun ────────────────
world = bpy.data.worlds.new("Celestia ambient")
scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes.get("Background")
bg.inputs["Color"].default_value = (0.55, 0.68, 0.85, 1.0)
bg.inputs["Strength"].default_value = 0.85

bpy.ops.mesh.primitive_uv_sphere_add(radius=20000, location=(0, 0, 0), segments=32, ring_count=16)
sky_sphere = bpy.context.active_object
skymat = bpy.data.materials.new("SKY gradient")
skymat.use_nodes = True
nodes, links = skymat.node_tree.nodes, skymat.node_tree.links
for n in list(nodes):
    nodes.remove(n)
out = nodes.new("ShaderNodeOutputMaterial")
emis = nodes.new("ShaderNodeEmission")
ramp = nodes.new("ShaderNodeValToRGB")
ramp.color_ramp.elements[0].position = 0.0
ramp.color_ramp.elements[0].color = (0.96, 0.87, 0.68, 1.0)     # warm horizon
ramp.color_ramp.elements[1].position = 1.0
ramp.color_ramp.elements[1].color = (0.13, 0.35, 0.75, 1.0)     # cerulean zenith
e_mid = ramp.color_ramp.elements.new(0.45)
e_mid.color = (0.55, 0.78, 0.92, 1.0)                            # pale cyan
mr = nodes.new("ShaderNodeMapRange")
mr.inputs["From Min"].default_value = -6000.0
mr.inputs["From Max"].default_value = 14000.0
sep = nodes.new("ShaderNodeSeparateXYZ")
tc = nodes.new("ShaderNodeTexCoord")
links.new(tc.outputs["Object"], sep.inputs["Vector"])
links.new(sep.outputs["Z"], mr.inputs["Value"])
links.new(mr.outputs["Result"], ramp.inputs["Fac"])
links.new(ramp.outputs["Color"], emis.inputs["Color"])
emis.inputs["Strength"].default_value = 1.0
links.new(emis.outputs["Emission"], out.inputs["Surface"])
sky_sphere.data.materials.append(skymat)

# sea of stylized cloud discs below the island
import random as _random
crng = _random.Random(3)
cloudmat = glow("SKY cloud", (1.0, 1.0, 1.0), 0.55, base=(0.97, 0.97, 0.98))
for k in range(48):
    r = crng.uniform(22, 75)
    x, y = crng.uniform(-520, 520), crng.uniform(-520, 520)
    z = crng.uniform(-118, -82)
    bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=crng.uniform(2.5, 6), location=(x, y, z))
    c = bpy.context.active_object
    c.scale = (1.0, crng.uniform(0.55, 0.9), 1.0)
    c.rotation_euler[2] = crng.uniform(0, 3.14)
    c.data.materials.append(cloudmat)
for k in range(6):
    bpy.ops.mesh.primitive_cylinder_add(radius=crng.uniform(12, 24), depth=2.5,
        location=(crng.uniform(-400, 400), crng.uniform(-400, 400), crng.uniform(150, 210)))
    bpy.context.active_object.data.materials.append(cloudmat)

sun_data = bpy.data.lights.new("Sun", type="SUN")
sun_data.energy = 4.0
sun_data.color = (1.0, 0.96, 0.88)
sun_data.angle = math.radians(2.0)
sun = bpy.data.objects.new("Sun", sun_data)
scene.collection.objects.link(sun)
sun.rotation_euler = Vector((-0.35, -0.31, -0.88)).to_track_quat("-Z", "Y").to_euler()

# ── camera: three slow shots ───────────────────────────────────────────────
cam_data = bpy.data.cameras.new("filmcam")
cam_data.clip_start = 0.5
cam_data.clip_end = 45000
cam = bpy.data.objects.new("filmcam", cam_data)
scene.collection.objects.link(cam)
target = bpy.data.objects.new("filmcam.target", None)
scene.collection.objects.link(target)
con = cam.constraints.new("TRACK_TO")
con.target = target
con.track_axis = "TRACK_NEGATIVE_Z"
con.up_axis = "UP_Y"
scene.camera = cam

SHOTS = [
    (1,    480,  (60, -290, -62),  (175, -240, 32),  (0, -35, -42), (0, 0, 50),  35),
    (481,  1104, None, None, (0, 0, 45), (0, 0, 75), 37),        # orbit below
    (1105, 1560, (40, -300, 25),   (30, -98, 148),   (0, -20, 35), (0, 12, 108), 33),
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

s0, s1 = 481, 1104
R0, R1, Z0, Z1, A0, A1 = 330.0, 290.0, 45.0, 112.0, 318.0, 198.0
for f in list(range(s0, s1 + 1, 12)) + [s1]:
    t = (f - s0) / (s1 - s0)
    a = math.radians(A0 + (A1 - A0) * t)
    R = R0 + (R1 - R0) * t
    cam.location = (R * math.cos(a), R * math.sin(a), Z0 + (Z1 - Z0) * t)
    cam.keyframe_insert("location", frame=f)
    target.location = (0, 0, 45 + 30 * t)
    target.keyframe_insert("location", frame=f)
    cam_data.lens = 37
    cam_data.keyframe_insert("lens", frame=f)

# ── render: EEVEE at 1080p, Standard transform, compositor bloom ───────────
scene.render.engine = "BLENDER_EEVEE"
for attr, v in (("taa_render_samples", int(os.environ.get("ALMOND_ANIM_SAMPLES", "32"))),
                ("use_raytracing", False), ("use_shadows", True)):
    try:
        setattr(scene.eevee, attr, v)
    except Exception:
        pass
scene.render.resolution_x = 1920
scene.render.resolution_y = 1080
scene.render.fps = FPS
scene.view_settings.view_transform = "Standard"
scene.view_settings.exposure = 0.0
scene.frame_start = int(os.environ.get("ALMOND_ANIM_START", "1"))
scene.frame_end = int(os.environ.get("ALMOND_ANIM_END", str(END)))
scene.render.filepath = os.path.join(ANIM_DIR, "f")
scene.render.image_settings.file_format = "PNG"

try:
    ct = bpy.data.node_groups.new("CelestiaComp", "CompositorNodeTree")
    scene.compositing_node_group = ct
    ct.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    rl = ct.nodes.new("CompositorNodeRLayers")
    glr = ct.nodes.new("CompositorNodeGlare")
    outn = ct.nodes.new("NodeGroupOutput")
    for tv in ("BLOOM", "Bloom", "FOG_GLOW"):
        try:
            glr.inputs["Type"].default_value = tv
            break
        except Exception:
            continue
    for name, v in (("Threshold", 1.0), ("Strength", 0.35), ("Size", 0.5)):
        try:
            glr.inputs[name].default_value = v
        except Exception:
            pass
    ct.links.new(rl.outputs["Image"], glr.inputs["Image"])
    ct.links.new(glr.outputs["Image"], outn.inputs["Image"])
    scene.render.use_compositing = True
    print("bloom compositor armed")
except Exception as exc:
    print(f"compositor unavailable ({exc})")

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
