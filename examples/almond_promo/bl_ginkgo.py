"""Animated fly-arounds of Ginkgo GRANDWHIS worlds on a strong sky/ground environment.

blender -b --factory-startup -P bl_ginkgo.py -- <world_code> <mode>     mode: probe | anim
Env: GK_FRAMES (48), GK_RES (1920), GK_SAMPLES (48)
Writes ~/Documents/almond_promo/ginkgo/<code>/g_####.png
"""
import bpy, math, os, sys, glob
from mathutils import Vector

argv = sys.argv[sys.argv.index('--') + 1:]
CODE, MODE = argv[0], argv[1]
FAB = "C:/Users/liang/OneDrive/Documents/Builiding0/Ginkgo/publishing/fab"
OUT = os.path.join(r"C:\Users\liang\Documents\almond_promo\ginkgo", CODE)
os.makedirs(OUT, exist_ok=True)
N = int(os.environ.get('GK_FRAMES', '48'))
RES = int(os.environ.get('GK_RES', '1920'))

# per world: (time of day, azimuth start deg, orbit deg, elevation deg, lens, radius factor, aim height factor)
SETUP = {
    'W038': ('dusk', 210, 18, 8, 26, 1.05, 0.42),   # Idol Tower
    'W041': ('golden', 150, 20, 13, 30, 1.00, 0.30),  # Coral Terminal
    'W039': ('golden', 30, 22, 14, 30, 1.00, 0.30),   # Container Stack
    'W037': ('night', 200, 16, 7, 24, 1.00, 0.45),    # Scaffold Spire
    'W035': ('golden', 240, 20, 12, 30, 1.00, 0.30),  # Flyover Fuel
    'W036': ('day', 120, 22, 14, 30, 1.00, 0.25),     # Overgrown Platform
    'W034': ('golden', 60, 20, 22, 30, 1.00, 0.30),
    'W033': ('dusk', 300, 20, 18, 30, 1.00, 0.35),
    'W040': ('night', 30, 20, 26, 30, 1.00, 0.25),
    'W032': ('day', 200, 20, 18, 30, 1.00, 0.35),
}
tod, az0, orbit, elev, lens, rfac, aimh = SETUP[CODE]

sc = bpy.context.scene
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)

glb = sorted(glob.glob(f"{FAB}/{CODE}/*/*.glb"))[-1]
bpy.ops.import_scene.gltf(filepath=glb)
meshes = [o for o in sc.objects if o.type == 'MESH']
lo = Vector((1e9, 1e9, 1e9)); hi = Vector((-1e9, -1e9, -1e9))
for o in meshes:
    for c in o.bound_box:
        w = o.matrix_world @ Vector(c)
        lo = Vector(map(min, lo, w)); hi = Vector(map(max, hi, w))
size = hi - lo
ctr = (lo + hi) / 2
print('BBOX', CODE, tuple(round(v, 2) for v in lo), tuple(round(v, 2) for v in hi))

# ------------------------------------------------ environment: sky with clouds + hazy endless ground
PAL = {  # sun elevation, sun azimuth offset from camera, sun strength, sky strength, haze colour, cloud tint, exposure
    'golden': (7, 150, 3.2, 0.32, (1.0, 0.72, 0.5), (1.0, 0.78, 0.62), 0.0),
    'day': (48, 120, 3.0, 0.35, (0.7, 0.82, 1.0), (1.0, 1.0, 1.0), -0.3),
    'dusk': (1.5, 170, 1.0, 0.5, (0.9, 0.5, 0.55), (0.95, 0.55, 0.6), 0.6),
    'night': (-8, 170, 0.0, 0.08, (0.12, 0.14, 0.3), (0.25, 0.25, 0.4), 1.2),
}
s_el, s_az, s_str, sky_str, haze, ctint, expo = PAL[tod]
world = bpy.data.worlds.new('GK world'); sc.world = world
world.use_nodes = True
nt = world.node_tree; nt.nodes.clear()
out = nt.nodes.new('ShaderNodeOutputWorld')
bg = nt.nodes.new('ShaderNodeBackground')
sky = nt.nodes.new('ShaderNodeTexSky')
sky.sky_type = 'MULTIPLE_SCATTERING' if 'MULTIPLE_SCATTERING' in [e.identifier for e in sky.bl_rna.properties['sky_type'].enum_items] else sky.sky_type
sun_az = math.radians(az0 + orbit / 2 + s_az)
sky.sun_elevation = math.radians(max(s_el, -2))
sky.sun_rotation = sun_az
sky.sun_disc = True
sky.aerosol_density = 2.0 if tod in ('golden', 'dusk') else 1.0
# procedural cloud layer projected on a plane at infinity
tc = nt.nodes.new('ShaderNodeTexCoord')
sep = nt.nodes.new('ShaderNodeSeparateXYZ'); nt.links.new(tc.outputs['Generated'], sep.inputs[0])
div = nt.nodes.new('ShaderNodeVectorMath'); div.operation = 'DIVIDE'
comb = nt.nodes.new('ShaderNodeCombineXYZ')
zc = nt.nodes.new('ShaderNodeMath'); zc.operation = 'MAXIMUM'; zc.inputs[1].default_value = 0.03
nt.links.new(sep.outputs['Z'], zc.inputs[0])
nt.links.new(sep.outputs['X'], comb.inputs['X']); nt.links.new(sep.outputs['Y'], comb.inputs['Y'])
nt.links.new(tc.outputs['Generated'], div.inputs[0])
zz = nt.nodes.new('ShaderNodeCombineXYZ')
for k in ('X', 'Y', 'Z'): nt.links.new(zc.outputs[0], zz.inputs[k])
nt.links.new(tc.outputs['Generated'], div.inputs[0]); nt.links.new(zz.outputs[0], div.inputs[1])
noise = nt.nodes.new('ShaderNodeTexNoise'); noise.inputs['Scale'].default_value = 1.1; noise.inputs['Detail'].default_value = 8
noise.inputs['Roughness'].default_value = 0.62
nt.links.new(div.outputs[0], noise.inputs['Vector'])
ramp = nt.nodes.new('ShaderNodeValToRGB'); ramp.color_ramp.elements[0].position = 0.5; ramp.color_ramp.elements[1].position = 0.72
nt.links.new(noise.outputs['Fac'], ramp.inputs['Fac'])
horizon = nt.nodes.new('ShaderNodeMapRange'); horizon.inputs['From Min'].default_value = 0.02; horizon.inputs['From Max'].default_value = 0.25
nt.links.new(sep.outputs['Z'], horizon.inputs['Value'])
cm = nt.nodes.new('ShaderNodeMath'); cm.operation = 'MULTIPLY'
nt.links.new(ramp.outputs['Color'], cm.inputs[0]); nt.links.new(horizon.outputs['Result'], cm.inputs[1])
mix = nt.nodes.new('ShaderNodeMix'); mix.data_type = 'RGBA'
nt.links.new(cm.outputs[0], mix.inputs['Factor'])
nt.links.new(sky.outputs['Color'], mix.inputs[6])
cloud_col = nt.nodes.new('ShaderNodeMix'); cloud_col.data_type = 'RGBA'; cloud_col.inputs['Factor'].default_value = 0.55
nt.links.new(sky.outputs['Color'], cloud_col.inputs[6]); cloud_col.inputs[7].default_value = (*[c * (1.6 if tod != 'night' else 0.2) for c in ctint], 1)
nt.links.new(cloud_col.outputs[2], mix.inputs[7])
nt.links.new(mix.outputs[2], bg.inputs['Color'])
bg.inputs['Strength'].default_value = sky_str
if tod == 'night':   # deep blue gradient instead of a black sky
    grad = nt.nodes.new('ShaderNodeValToRGB')
    grad.color_ramp.elements[0].color = (0.05, 0.07, 0.2, 1); grad.color_ramp.elements[1].color = (0.004, 0.006, 0.02, 1)
    grad.color_ramp.elements[0].position = 0.0; grad.color_ramp.elements[1].position = 0.5
    nt.links.new(sep.outputs['Z'], grad.inputs['Fac'])
    m2 = nt.nodes.new('ShaderNodeMix'); m2.data_type = 'RGBA'
    nt.links.new(cm.outputs[0], m2.inputs['Factor']); nt.links.new(grad.outputs['Color'], m2.inputs[6])
    m2.inputs[7].default_value = (0.08, 0.08, 0.14, 1)
    nt.links.new(m2.outputs[2], bg.inputs['Color']); bg.inputs['Strength'].default_value = 1.0
nt.links.new(bg.outputs[0], out.inputs['Surface'])

# sun (+ cool moon at night)
sun_d = bpy.data.lights.new('Sun', 'SUN'); sun = bpy.data.objects.new('Sun', sun_d); sc.collection.objects.link(sun)
el = math.radians(max(s_el, 3) if tod != 'night' else 35)
dvec = Vector((math.cos(el) * math.sin(sun_az), math.cos(el) * math.cos(sun_az), math.sin(el)))
sun.rotation_euler = (-dvec).to_track_quat('-Z', 'Y').to_euler()
sun_d.energy = s_str if tod != 'night' else 0.25
sun_d.color = (1, 0.85, 0.7) if tod in ('golden', 'dusk') else ((0.6, 0.7, 1.0) if tod == 'night' else (1, 0.98, 0.95))
sun_d.angle = math.radians(1.5)

# endless ground with distance haze (keeps a strong horizon, never a grey void)
bpy.ops.mesh.primitive_plane_add(size=6000, location=(ctr.x, ctr.y, lo.z - 0.02))
g = bpy.context.active_object; gm = bpy.data.materials.new('GK ground'); gm.use_nodes = True; g.data.materials.append(gm)
gn = gm.node_tree; b = gn.nodes['Principled BSDF']
b.inputs['Base Color'].default_value = (0.09, 0.09, 0.1, 1) if tod != 'day' else (0.28, 0.28, 0.27, 1)
b.inputs['Roughness'].default_value = 0.35 if tod in ('night', 'dusk') else 0.8
cam_d = gn.nodes.new('ShaderNodeCameraData')
mr = gn.nodes.new('ShaderNodeMapRange'); mr.inputs['From Min'].default_value = size.length * 2; mr.inputs['From Max'].default_value = size.length * 25
gn.links.new(cam_d.outputs['View Distance'], mr.inputs['Value'])
em = gn.nodes.new('ShaderNodeEmission'); em.inputs['Color'].default_value = (*[c * (0.35 if tod == 'night' else 0.8) for c in haze], 1)
em.inputs['Strength'].default_value = 1.0
ms = gn.nodes.new('ShaderNodeMixShader')
gn.links.new(mr.outputs['Result'], ms.inputs['Fac']); gn.links.new(b.outputs[0], ms.inputs[1]); gn.links.new(em.outputs[0], ms.inputs[2])
gn.links.new(ms.outputs[0], gn.nodes['Material Output'].inputs['Surface'])

# ------------------------------------------------ camera: slow orbit + gentle push, constant speed (no easing = calm cut-to-cut)
cam_data = bpy.data.cameras.new('GK cam'); cam_data.lens = lens; cam_data.sensor_width = 36
cam_data.clip_start = 0.1; cam_data.clip_end = 10000
cam = bpy.data.objects.new('GK cam', cam_data); sc.collection.objects.link(cam); sc.camera = cam
horiz = max(size.x, size.y); tall = size.z > 1.4 * horiz
fitdim = size.z if tall else max(horiz, size.z)
half = math.atan(18 / lens)
r0 = rfac * (0.5 * size.z / math.tan(half * 9 / 16) * 1.35 if tall else 0.5 * size.length / math.tan(half) * 1.05)
aim = Vector((ctr.x, ctr.y, lo.z + size.z * aimh))
sc.frame_start, sc.frame_end = 0, N - 1


def pose(i):
    u = i / max(1, N - 1)
    a = math.radians(az0 + orbit * u)
    r = r0 * (1.0 - 0.08 * u)
    e = math.radians(elev)
    p = aim + Vector((r * math.cos(e) * math.sin(a), -r * math.cos(e) * math.cos(a), r * math.sin(e)))
    cam.location = p
    cam.rotation_euler = (aim - p).to_track_quat('-Z', 'Y').to_euler()


# ------------------------------------------------ render
sc.render.engine = 'CYCLES'
sc.cycles.device = 'GPU'
prefs = bpy.context.preferences.addons['cycles'].preferences
prefs.compute_device_type = 'OPTIX'; prefs.get_devices()
for d in prefs.devices: d.use = d.type == 'OPTIX'
sc.cycles.samples = int(os.environ.get('GK_SAMPLES', '48')); sc.cycles.use_denoising = True; sc.cycles.denoiser = 'OPTIX'
sc.cycles.use_adaptive_sampling = True; sc.cycles.adaptive_threshold = 0.04
sc.render.use_persistent_data = True
sc.render.resolution_x, sc.render.resolution_y = RES, RES * 9 // 16
sc.view_settings.view_transform = 'AgX'; sc.view_settings.look = 'AgX - Medium High Contrast'; sc.view_settings.exposure = expo
sc.render.image_settings.file_format = 'PNG'
frames = [0, N // 2, N - 1] if MODE == 'probe' else range(N)
for i in frames:
    pose(i)
    sc.render.filepath = os.path.join(OUT, ('probe_%02d.png' if MODE == 'probe' else 'g_%04d.png') % i)
    bpy.ops.render.render(write_still=True)
    print('FRAME', CODE, i, flush=True)
print('DONE', CODE)
