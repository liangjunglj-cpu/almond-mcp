"""Ginkgo worlds as a city of possibilities: all GRANDWHIS worlds on one street grid, art-directed sky, one fly-around per world.

blender -b --factory-startup -P bl_ginkgo_city.py -- <mode> [codes]      mode: sky | probe | anim
Env: GK_FRAMES (48), GK_RES (1920), GK_SAMPLES (48)
Frames -> ~/Documents/almond_promo/ginkgo/<code>/g_####.png
"""
import bpy, math, os, sys, glob
from mathutils import Vector

argv = sys.argv[sys.argv.index('--') + 1:]
MODE = argv[0]
SHOTS = argv[1].split(',') if len(argv) > 1 else ['W038', 'W041', 'W039', 'W037', 'W035', 'W036']
FAB = "C:/Users/liang/OneDrive/Documents/Builiding0/Ginkgo/publishing/fab"
OUTROOT = r"C:\Users\liang\Documents\almond_promo\ginkgo"
N = int(os.environ.get('GK_FRAMES', '48'))
RES = int(os.environ.get('GK_RES', '1920'))
sc = bpy.context.scene
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)

# ------------------------------------------------------------------ art-directed sky (gradient + sun glow + clouds)
LOOKS = {  # zenith, horizon, sun glow colour, sun elevation, sun azimuth, sun strength, cloud colour, exposure
    'golden': ((0.01, 0.05, 0.3), (1.2, 0.42, 0.14), (1.4, 0.55, 0.2), 9, 250, 3.5, (1.1, 0.75, 0.6), 0.1),
    'day': ((0.005, 0.07, 0.5), (0.35, 0.6, 0.95), (1.0, 0.95, 0.85), 50, 200, 3.2, (1.3, 1.3, 1.3), -0.15),
    'dusk': ((0.015, 0.02, 0.12), (0.85, 0.3, 0.45), (1.0, 0.35, 0.4), 2, 250, 0.8, (0.7, 0.35, 0.5), 0.4),
}
world = bpy.data.worlds.new('GK sky'); sc.world = world; world.use_nodes = True
nt = world.node_tree; nt.nodes.clear()
L = nt.links.new
out = nt.nodes.new('ShaderNodeOutputWorld'); bg = nt.nodes.new('ShaderNodeBackground')
tc = nt.nodes.new('ShaderNodeTexCoord')
nrm = nt.nodes.new('ShaderNodeVectorMath'); nrm.operation = 'NORMALIZE'; L(tc.outputs['Generated'], nrm.inputs[0])
sep = nt.nodes.new('ShaderNodeSeparateXYZ'); L(nrm.outputs['Vector'], sep.inputs[0])
# vertical gradient
zpos = nt.nodes.new('ShaderNodeMath'); zpos.operation = 'MAXIMUM'; zpos.inputs[1].default_value = 0.0; L(sep.outputs['Z'], zpos.inputs[0])
pw = nt.nodes.new('ShaderNodeMath'); pw.operation = 'POWER'; pw.inputs[1].default_value = 0.45; L(zpos.outputs[0], pw.inputs[0])
grad = nt.nodes.new('ShaderNodeMix'); grad.data_type = 'RGBA'; L(pw.outputs[0], grad.inputs['Factor'])
# sun glow
sundir = nt.nodes.new('ShaderNodeCombineXYZ')
dot = nt.nodes.new('ShaderNodeVectorMath'); dot.operation = 'DOT_PRODUCT'; L(nrm.outputs['Vector'], dot.inputs[0]); L(sundir.outputs[0], dot.inputs[1])
dcl = nt.nodes.new('ShaderNodeMath'); dcl.operation = 'MAXIMUM'; dcl.inputs[1].default_value = 0.0; L(dot.outputs['Value'], dcl.inputs[0])
glow = nt.nodes.new('ShaderNodeMath'); glow.operation = 'POWER'; glow.inputs[1].default_value = 12.0; L(dcl.outputs[0], glow.inputs[0])
glowc = nt.nodes.new('ShaderNodeMix'); glowc.data_type = 'RGBA'; glowc.blend_type = 'ADD'
L(glow.outputs[0], glowc.inputs['Factor']); L(grad.outputs[2], glowc.inputs[6])
# clouds: noise on the direction projected to a cloud deck
zc = nt.nodes.new('ShaderNodeMath'); zc.operation = 'MAXIMUM'; zc.inputs[1].default_value = 0.06; L(sep.outputs['Z'], zc.inputs[0])
px = nt.nodes.new('ShaderNodeMath'); px.operation = 'DIVIDE'; L(sep.outputs['X'], px.inputs[0]); L(zc.outputs[0], px.inputs[1])
py = nt.nodes.new('ShaderNodeMath'); py.operation = 'DIVIDE'; L(sep.outputs['Y'], py.inputs[0]); L(zc.outputs[0], py.inputs[1])
cv = nt.nodes.new('ShaderNodeCombineXYZ'); L(px.outputs[0], cv.inputs['X']); L(py.outputs[0], cv.inputs['Y'])
noise = nt.nodes.new('ShaderNodeTexNoise'); noise.noise_dimensions = '2D'
noise.inputs['Scale'].default_value = 0.9; noise.inputs['Detail'].default_value = 10; noise.inputs['Roughness'].default_value = 0.6
L(cv.outputs[0], noise.inputs['Vector'])
ramp = nt.nodes.new('ShaderNodeMapRange'); ramp.inputs['From Min'].default_value = 0.5; ramp.inputs['From Max'].default_value = 0.68
L(noise.outputs['Fac'], ramp.inputs['Value'])
hz = nt.nodes.new('ShaderNodeMapRange'); hz.inputs['From Min'].default_value = 0.03; hz.inputs['From Max'].default_value = 0.3
L(sep.outputs['Z'], hz.inputs['Value'])
cmask = nt.nodes.new('ShaderNodeMath'); cmask.operation = 'MULTIPLY'; L(ramp.outputs['Result'], cmask.inputs[0]); L(hz.outputs['Result'], cmask.inputs[1])
cmask2 = nt.nodes.new('ShaderNodeMath'); cmask2.operation = 'MULTIPLY'; cmask2.inputs[1].default_value = 0.85; L(cmask.outputs[0], cmask2.inputs[0])
cloud = nt.nodes.new('ShaderNodeMix'); cloud.data_type = 'RGBA'; L(cmask2.outputs[0], cloud.inputs['Factor']); L(glowc.outputs[2], cloud.inputs[6])
# cloud colour lit by the sun glow side
cl = nt.nodes.new('ShaderNodeMix'); cl.data_type = 'RGBA'; cl.blend_type = 'ADD'; L(glow.outputs[0], cl.inputs['Factor'])
L(cl.outputs[2], cloud.inputs[7])
L(cloud.outputs[2], bg.inputs['Color']); L(bg.outputs[0], out.inputs['Surface'])
sun_d = bpy.data.lights.new('Sun', 'SUN'); sun = bpy.data.objects.new('Sun', sun_d); sc.collection.objects.link(sun)


def set_look(name):
    zen, hor, gl, el, az, sstr, ccol, expo = LOOKS[name]
    grad.inputs[6].default_value = (*hor, 1); grad.inputs[7].default_value = (*zen, 1)
    glowc.inputs[7].default_value = (*gl, 1)
    cl.inputs[6].default_value = (*ccol, 1); cl.inputs[7].default_value = (*gl, 1)
    e, a = math.radians(el), math.radians(az)
    d = Vector((math.cos(e) * math.sin(a), math.cos(e) * math.cos(a), math.sin(e)))
    sundir.inputs['X'].default_value, sundir.inputs['Y'].default_value, sundir.inputs['Z'].default_value = d
    sun.rotation_euler = (-d).to_track_quat('-Z', 'Y').to_euler()
    sun_d.energy = sstr; sun_d.color = gl if name != 'day' else (1, 0.97, 0.92); sun_d.angle = math.radians(1.2)
    bg.inputs['Strength'].default_value = 1.0
    sc.view_settings.exposure = expo


# ------------------------------------------------------------------ render settings
sc.render.engine = 'CYCLES'; sc.cycles.device = 'GPU'
prefs = bpy.context.preferences.addons['cycles'].preferences
prefs.compute_device_type = 'OPTIX'; prefs.get_devices()
for dv in prefs.devices: dv.use = dv.type == 'OPTIX'
sc.cycles.samples = int(os.environ.get('GK_SAMPLES', '48')); sc.cycles.use_denoising = True; sc.cycles.denoiser = 'OPTIX'
sc.cycles.use_adaptive_sampling = True; sc.cycles.adaptive_threshold = 0.04; sc.cycles.max_bounces = 6
sc.render.use_persistent_data = True
sc.render.resolution_x, sc.render.resolution_y = RES, RES * 9 // 16
sc.view_settings.view_transform = 'AgX'; sc.view_settings.look = 'AgX - Punchy'
sc.render.image_settings.file_format = 'PNG'
cam_data = bpy.data.cameras.new('GK cam'); cam_data.sensor_width = 36; cam_data.clip_start = 0.1; cam_data.clip_end = 20000
cam = bpy.data.objects.new('GK cam', cam_data); sc.collection.objects.link(cam); sc.camera = cam

if MODE == 'sky':
    os.makedirs(OUTROOT, exist_ok=True)
    for nm in LOOKS:
        set_look(nm); cam_data.lens = 18
        cam.location = (0, 0, 2); cam.rotation_euler = (math.radians(100), 0, math.radians(-110))
        sc.render.filepath = os.path.join(OUTROOT, f'sky_{nm}.png'); bpy.ops.render.render(write_still=True)
    print('DONE sky'); sys.exit(0)

# ------------------------------------------------------------------ city: every world as a collection, placed by instancing
ALL = ['W032', 'W033', 'W034', 'W035', 'W036', 'W037', 'W038', 'W039', 'W040', 'W041']
info = {}
for code in ALL:
    glb = sorted(glob.glob(f"{FAB}/{code}/*/*.glb"))[-1]
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=glb)
    objs = [o for o in bpy.data.objects if o not in before]
    col = bpy.data.collections.new('GK_' + code); bpy.context.scene.collection.children.link(col)
    for o in objs:
        for c in list(o.users_collection): c.objects.unlink(o)
        col.objects.link(o)
    lo = Vector((1e9, 1e9, 1e9)); hi = Vector((-1e9, -1e9, -1e9))
    for o in objs:
        if o.type != 'MESH': continue
        for c in o.bound_box:
            w = o.matrix_world @ Vector(c); lo = Vector(map(min, lo, w)); hi = Vector(map(max, hi, w))
    col.instance_offset = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
    info[code] = (col, hi - lo)
    bpy.context.view_layer.layer_collection.children[col.name].exclude = True
    print('IMPORTED', code, tuple(round(v, 1) for v in (hi - lo)), flush=True)

import random
rnd = random.Random(7)
SP = 110.0
HEROES = {'W038': (-3, -2), 'W041': (0, -2), 'W039': (3, -2), 'W037': (-3, 2), 'W035': (0, 2), 'W036': (3, 2)}
place = {}
near = set()
for code, (cx, cy) in HEROES.items():
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            near.add((cx + dx, cy + dy))


def inst(name, code, x, y, rot=0.0, s=1.0):
    e = bpy.data.objects.new(name, None); e.instance_type = 'COLLECTION'; e.instance_collection = info[code][0]
    e.location = (x, y, 0); e.rotation_euler = (0, 0, rot); e.scale = (s, s, s); sc.collection.objects.link(e)


for code, (cx, cy) in HEROES.items():
    inst('H_' + code, code, cx * SP, cy * SP); place[code] = Vector((cx * SP, cy * SP, 0))
k = 0
for gx in range(-6, 7):
    for gy in range(-6, 7):
        if (gx, gy) in near: continue
        code = rnd.choice(ALL)
        inst('F_%03d' % k, code, gx * SP + rnd.uniform(-6, 6), gy * SP + rnd.uniform(-6, 6), rnd.choice([0, 0.5, 1, 1.5]) * math.pi,
             rnd.uniform(1.45, 1.9)); k += 1
print('FILLERS', k)

# ground: asphalt with a street grid and distance haze toward the horizon colour
bpy.ops.mesh.primitive_plane_add(size=8000, location=(0, 0, -0.05))
g = bpy.context.active_object; gm = bpy.data.materials.new('GK ground'); gm.use_nodes = True; g.data.materials.append(gm)
gn = gm.node_tree; gb = gn.nodes['Principled BSDF']
gb.inputs['Base Color'].default_value = (0.05, 0.05, 0.055, 1); gb.inputs['Roughness'].default_value = 0.3
tcg = gn.nodes.new('ShaderNodeTexCoord'); brick = gn.nodes.new('ShaderNodeTexBrick')
brick.inputs['Scale'].default_value = 1.0 / SP; brick.offset = 0.0; brick.inputs['Mortar Size'].default_value = 0.16; brick.inputs['Mortar Smooth'].default_value = 0.02; brick.inputs['Brick Width'].default_value = 1.0; brick.inputs['Row Height'].default_value = 1.0
brick.inputs['Color1'].default_value = (0.075, 0.075, 0.08, 1); brick.inputs['Color2'].default_value = (0.085, 0.083, 0.082, 1)
brick.inputs['Mortar'].default_value = (0.035, 0.035, 0.04, 1)
mp = gn.nodes.new('ShaderNodeMapping'); mp.inputs['Location'].default_value = (SP / 2, SP / 2, 0)
gn.links.new(tcg.outputs['Object'], mp.inputs['Vector']); gn.links.new(mp.outputs['Vector'], brick.inputs['Vector'])
gn.links.new(brick.outputs['Color'], gb.inputs['Base Color'])
camd = gn.nodes.new('ShaderNodeCameraData'); hmr = gn.nodes.new('ShaderNodeMapRange')
hmr.inputs['From Min'].default_value = 300; hmr.inputs['From Max'].default_value = 1400
gn.links.new(camd.outputs['View Distance'], hmr.inputs['Value'])
hem = gn.nodes.new('ShaderNodeEmission'); hmix = gn.nodes.new('ShaderNodeMixShader')
gn.links.new(hmr.outputs['Result'], hmix.inputs['Fac']); gn.links.new(gb.outputs[0], hmix.inputs[1]); gn.links.new(hem.outputs[0], hmix.inputs[2])
gn.links.new(hmix.outputs[0], gn.nodes['Material Output'].inputs['Surface'])

# ------------------------------------------------------------------ shots
SHOT = {  # look, azimuth start, orbit deg, elevation, lens, aim height factor, distance factor
    'W038': ('dusk', 200, 16, 7, 24, 0.5, 1.25), 'W041': ('golden', 320, 18, 10, 26, 0.35, 1.25),
    'W039': ('day', 20, 20, 11, 26, 0.35, 1.2), 'W037': ('dusk', 190, 14, 6, 22, 0.5, 1.05),
    'W035': ('golden', 230, 18, 9, 26, 0.35, 1.2), 'W036': ('day', 110, 20, 10, 26, 0.35, 1.3),
}
frames = [0, N // 2, N - 1] if MODE == 'probe' else list(range(N))
for code in SHOTS:
    look, az0, orbit, elev, lens, aimh, dfac = SHOT[code]
    set_look(look)
    hem.inputs['Color'].default_value = grad.inputs[6].default_value   # ground haze = horizon colour
    size = info[code][1]; P = place[code]
    cam_data.lens = lens
    half = math.atan(18 / lens)
    tall = size.z > 1.4 * max(size.x, size.y)
    r0 = dfac * (0.5 * size.z / math.tan(half * 9 / 16) * 1.3 if tall else 0.5 * size.length / math.tan(half) * 1.0)
    aim = P + Vector((0, 0, size.z * aimh))
    od = os.path.join(OUTROOT, code); os.makedirs(od, exist_ok=True)
    for i in frames:
        u = i / max(1, N - 1)
        a = math.radians(az0 + orbit * u); r = r0 * (1 - 0.07 * u); e = math.radians(elev)
        p = aim + Vector((r * math.cos(e) * math.sin(a), -r * math.cos(e) * math.cos(a), r * math.sin(e)))
        cam.location = p; cam.rotation_euler = (aim - p).to_track_quat('-Z', 'Y').to_euler()
        sc.render.filepath = os.path.join(od, ('probe_%02d.png' if MODE == 'probe' else 'g_%04d.png') % i)
        bpy.ops.render.render(write_still=True)
        print('FRAME', code, i, flush=True)
print('DONE', ','.join(SHOTS))
