"""Almond promo: lighting + material experiments on Atelier-07 from one locked axon camera.

Run:  blender -b Atelier-07-Golden-Hour-Contact-Fixed.blend -P bl_promo.py
Env:  PROMO_MODE = probe | stills | sweep | save
      PROMO_LOOKS = comma list of look names (stills), PROMO_RES = 1920 | 3840, PROMO_SAMPLES
The source .blend is never saved over; `save` writes ~/Documents/almond_promo/almond_promo.blend.
"""
import bpy, math, os
from mathutils import Vector, Euler

OUT = r"C:\Users\liang\Documents\almond_promo\blender"
os.makedirs(OUT, exist_ok=True)
MODE = os.environ.get('PROMO_MODE', 'probe')
RES = int(os.environ.get('PROMO_RES', '1920'))
SAMPLES = int(os.environ.get('PROMO_SAMPLES', '96'))
sc = bpy.context.scene
INTERIOR = os.environ.get('PROMO_CAM') == 'living'   # original living-room camera, full envelope, no cutaway

# ---------------------------------------------------------------- cutaway (matches Rhino)
for c in ([] if INTERIOR else bpy.data.collections):
    if c.name in ('A07 / 03 Facade', 'A07 / 12 Roof / hide for cutaway', 'A07 / 13 Urban context'):
        c.hide_render = c.hide_viewport = True
for o in ([] if INTERIOR else sc.objects):
    if (o.name.startswith('East concrete wall') or o.name.startswith('Full-height linen curtain fold')
            or o.get('almond_asset_id') == 'gen-tree-deciduous-medium-1'):
        o.hide_render = o.hide_viewport = True

# ---------------------------------------------------------------- camera (Rhino hfov 50.47 deg)
cam_data = bpy.data.cameras.new('Promo axon')
cam_data.sensor_fit = 'HORIZONTAL'
cam_data.sensor_width = 36
cam_data.lens = 18 / math.tan(math.radians(50.469 / 2))
cam_data.clip_start, cam_data.clip_end = 1, 400
cam = bpy.data.objects.new('Promo axon', cam_data)
sc.collection.objects.link(cam)
loc, tgt = Vector((18.9, -18.1, 15.1)), Vector((6.5, 4.7, 2.4))
cam.location = loc
cam.rotation_euler = (tgt - loc).to_track_quat('-Z', 'Y').to_euler()
sc.camera = cam if not INTERIOR else bpy.data.objects['Living room / original Rhino composition']
sc.render.resolution_x, sc.render.resolution_y = RES, RES * 9 // 16
sc.render.resolution_percentage = 100

# ---------------------------------------------------------------- render settings
cy = sc.cycles
cy.samples = SAMPLES
cy.use_adaptive_sampling = True
cy.adaptive_threshold = 0.03
cy.use_denoising = True
cy.denoiser = 'OPTIX'
cy.max_bounces = 8
sc.render.use_persistent_data = True
sc.render.image_settings.file_format = 'PNG'
sc.render.image_settings.color_depth = '8'
for o in sc.objects:  # the source scene had subtle DoF for the interior shot
    pass
cam_data.dof.use_dof = False
if INTERIOR:
    cy.adaptive_threshold = 0.02

# ---------------------------------------------------------------- studio ground
gmat = bpy.data.materials.new('Promo / ground')
gmat.use_nodes = True
gbsdf = gmat.node_tree.nodes['Principled BSDF']
bpy.ops.mesh.primitive_plane_add(size=400, location=(6.4, 5.0, -0.265 if not INTERIOR else -50))
ground = bpy.context.active_object
ground.name = 'Promo ground'
ground.data.materials.append(gmat)

# ---------------------------------------------------------------- lights inventory
sun = bpy.data.objects['Late afternoon sun']
SUN0 = sun.rotation_euler.copy()
SUN0_E = sun.data.energy
# window fills were for the interior camera; with the facade cut away they flood the ground
for n in (() if INTERIOR else ('West glazing / soft sky', 'South glazing / soft sky')):
    bpy.data.objects[n].hide_render = True
practicals = [o for o in sc.objects if o.type == 'LIGHT' and o is not sun and not o.hide_render]
P0 = {o.name: o.data.energy for o in practicals}
world = sc.world
wn = world.node_tree.nodes
bg = wn['Background']
sky = wn.get('Sky Texture')
W0 = bg.inputs['Strength'].default_value


def aim_sun(az_deg, el_deg):
    """az measured from +Y (north) clockwise, like Rhino's sun azimuth."""
    az, el = math.radians(az_deg), math.radians(el_deg)
    d = Vector((math.sin(az) * math.cos(el), math.cos(az) * math.cos(el), math.sin(el)))  # towards sun
    sun.rotation_euler = (-d).to_track_quat('-Z', 'Y').to_euler()
    if sky is not None:
        for attr in ('sun_elevation',):
            if hasattr(sky, attr):
                setattr(sky, attr, max(math.radians(el_deg), math.radians(-2)))
        if hasattr(sky, 'sun_rotation'):
            sky.sun_rotation = az


def new_mat(name, color, rough=0.5, metal=0.0, emit=None, emit_strength=0.0, coat=0.0):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes['Principled BSDF']
    b.inputs['Base Color'].default_value = (*color, 1)
    b.inputs['Roughness'].default_value = rough
    b.inputs['Metallic'].default_value = metal
    if 'Coat Weight' in b.inputs:
        b.inputs['Coat Weight'].default_value = coat
    if emit is not None:
        b.inputs['Emission Color'].default_value = (*emit, 1)
        b.inputs['Emission Strength'].default_value = emit_strength
    return m


def srgb(h):
    h = h.lstrip('#')
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c)


neon_rigs = []


def neon(on):
    global neon_rigs
    for o in neon_rigs:
        bpy.data.objects.remove(o, do_unlink=True)
    neon_rigs = []
    if not on:
        return
    focus = Vector((6.4, 5.0, 1.2))
    for name, col, loc, size, e in [
        ('Neon magenta', srgb('#ff2bd6'), (-7, 11, 11), 3.5, 3200),
        ('Neon cyan', srgb('#00e5ff'), (19, -6, 9), 3.5, 2600),
        ('Neon top', srgb('#7a5cff'), (6.4, 5, 16), 14, 450),
    ]:
        d = bpy.data.lights.new(name, 'AREA')
        d.color, d.energy, d.size = col, e, size
        o = bpy.data.objects.new(name, d)
        o.location = loc
        o.rotation_euler = (focus - Vector(loc)).to_track_quat('-Z', 'Y').to_euler()
        sc.collection.objects.link(o)
        neon_rigs.append(o)


def reset():
    sc.view_layers[0].material_override = None
    sun.data.energy = SUN0_E
    sun.rotation_euler = SUN0
    sun.hide_render = False
    for o in practicals:
        o.data.energy = P0[o.name]
        o.hide_render = False
    bg.inputs['Strength'].default_value = W0
    if sky is not None:
        bg.inputs['Color'].links and None
    neon(False)
    gbsdf.inputs['Base Color'].default_value = (0.56, 0.55, 0.53, 1)
    gbsdf.inputs['Roughness'].default_value = 0.8
    sc.view_settings.view_transform = 'AgX'
    sc.view_settings.look = 'AgX - Medium High Contrast'
    sc.view_settings.exposure = 0.1


def dim_world(strength, color=None):
    """Replace sky by a flat colour at given strength (links cut, restored on reset via relink)."""
    bg.inputs['Strength'].default_value = strength
    if color is not None:
        for l in list(bg.inputs['Color'].links):
            world.node_tree.links.remove(l)
        bg.inputs['Color'].default_value = (*color, 1)


def restore_sky():
    if sky is not None and not bg.inputs['Color'].links:
        world.node_tree.links.new(sky.outputs['Color'], bg.inputs['Color'])


def practical_scale(k):
    for o in practicals:
        o.data.energy = P0[o.name] * k


LOOKS = {}


def look(fn):
    LOOKS[fn.__name__] = fn
    return fn


@look
def golden():
    restore_sky()


@look
def noon():
    restore_sky()
    aim_sun(200, 58)
    sun.data.energy = SUN0_E * 1.1
    gbsdf.inputs['Base Color'].default_value = (0.62, 0.62, 0.62, 1)
    sc.view_settings.exposure = -0.4


@look
def bluehour_off():
    dim_world(1.2, srgb('#243a66'))
    sun.hide_render = True
    practical_scale(0.0)
    gbsdf.inputs['Base Color'].default_value = (0.08, 0.1, 0.14, 1)
    sc.view_settings.exposure = 0.6


@look
def bluehour_on():
    bluehour_off()
    practical_scale(2.2)


@look
def neon_night():
    dim_world(0.15, srgb('#07060d'))
    sun.hide_render = True
    practical_scale(1.2)
    neon(True)
    gbsdf.inputs['Base Color'].default_value = (0.02, 0.02, 0.025, 1)
    gbsdf.inputs['Roughness'].default_value = 0.18
    sc.view_settings.exposure = 0.2


@look
def clay():
    noon()
    sc.view_layers[0].material_override = new_mat('Promo / clay', (0.82, 0.8, 0.77), rough=0.65)
    sc.view_settings.exposure = -1.0


@look
def swiss_red():
    restore_sky()
    aim_sun(235, 34)
    sc.view_layers[0].material_override = new_mat('Promo / swiss red', srgb('#e9442b'), rough=0.55)
    gbsdf.inputs['Base Color'].default_value = (0.85, 0.85, 0.85, 1)
    sc.view_settings.look = 'AgX - High Contrast'


@look
def chrome_neon():
    neon_night()
    sc.view_layers[0].material_override = new_mat('Promo / chrome', (0.9, 0.92, 0.95), rough=0.12, metal=1.0)
    practical_scale(0.6)
    sc.view_settings.exposure = 0.35


@look
def graphite():
    restore_sky()
    aim_sun(235, 30)
    sc.view_layers[0].material_override = new_mat('Promo / graphite', (0.045, 0.045, 0.05), rough=0.32)
    sc.view_settings.look = 'AgX - High Contrast'
    sc.view_settings.exposure = 0.5


def render_still(name, path):
    reset()
    LOOKS[name]()
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    print('WROTE', path, flush=True)


if MODE == 'probe':
    sc.render.resolution_x, sc.render.resolution_y = 960, 540
    cy.samples = 24
    for n in os.environ.get('PROMO_LOOKS', 'golden').split(','):
        render_still(n, os.path.join(OUT, f'probe_{n}.png'))
elif MODE == 'stills':
    for n in os.environ.get('PROMO_LOOKS', ','.join(LOOKS)).split(','):
        render_still(n, os.path.join(OUT, f'{"int_" if INTERIOR else "look_"}{n}_{RES}.png'))
elif MODE == 'sweep':
    # sun time-lapse: morning (east, low) -> noon -> golden (west, low)
    reset(); golden()
    n = int(os.environ.get('PROMO_FRAMES', '120'))
    start = int(os.environ.get('PROMO_START', '0'))
    os.makedirs(os.path.join(OUT, 'sweep'), exist_ok=True)
    for i in range(start, n):
        t = i / (n - 1)
        az = 95 + 170 * t
        el = 8 + 52 * math.sin(math.pi * t)
        aim_sun(az, el)
        sun.data.energy = SUN0_E * (0.8 + 0.4 * math.sin(math.pi * t))
        sc.view_settings.exposure = 0.1 - 0.5 * math.sin(math.pi * t)
        sc.render.filepath = os.path.join(OUT, 'sweep', f's_{i:04d}.png')
        bpy.ops.render.render(write_still=True)
        print('FRAME', i, flush=True)
elif MODE == 'save':
    reset(); golden()
    bpy.ops.wm.save_as_mainfile(filepath=r"C:\Users\liang\Documents\almond_promo\almond_promo.blend", copy=True)
print('DONE', flush=True)
