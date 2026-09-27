"""Texture-mapped Cycles materials for the Almond Modern Blender scenes.

Shared by blender_modern.py (stills + .blend) and blender_modern_anim.py
(generation film). Every material maps procedural textures through ONE
world-anchored empty ("ALMOND texspace"), so texture space is world
meters and continuous across all 2,949 meshes regardless of each mesh's
local origin or the mm->m import scale.

build_rich_material(name, key) returns a Blender material for an export
key (material_id fragment or split name: foliage / lampheads / pv).
"""
import bpy


PALETTE = {
    "plaster-white":      dict(base=(0.90, 0.90, 0.88)),
    "concrete-smooth":    dict(base=(0.70, 0.69, 0.66)),
    "concrete-boardformed": dict(base=(0.60, 0.58, 0.55)),
    "steel-painted-sage": dict(base=(0.50, 0.58, 0.42)),
    "steel-galvanized":   dict(base=(0.62, 0.63, 0.65)),
    "aluminium-anodized": dict(base=(0.78, 0.78, 0.80)),
    "metal-corrugated":   dict(base=(0.42, 0.48, 0.38)),
    "glass-clear":        dict(base=(0.88, 0.94, 0.92)),
    "glass-laminated":    dict(base=(0.80, 0.88, 0.86)),
    "polycarbonate-opal": dict(base=(0.92, 0.94, 0.90)),
    "wood-oak":           dict(base=(0.50, 0.34, 0.20), dark=(0.35, 0.22, 0.12)),
    "wood-walnut":        dict(base=(0.30, 0.19, 0.12), dark=(0.18, 0.10, 0.06)),
    "wood-birch-ply":     dict(base=(0.76, 0.62, 0.44), dark=(0.62, 0.48, 0.32)),
    "rubber-black":       dict(base=(0.05, 0.05, 0.055)),
    "foliage":            dict(base=(0.14, 0.30, 0.10), dark=(0.07, 0.18, 0.05)),
    "lampheads":          dict(base=(0.90, 0.85, 0.70)),
    "pv":                 dict(base=(0.02, 0.05, 0.14)),
    "ground":             dict(base=(0.52, 0.52, 0.50)),
}


def _texspace():
    obj = bpy.data.objects.get("ALMOND texspace")
    if obj is None:
        obj = bpy.data.objects.new("ALMOND texspace", None)
        bpy.context.scene.collection.objects.link(obj)
        obj.hide_render = True
        obj.hide_viewport = True
    return obj


def _coords(nodes, links):
    """World-meter texture coordinates via the shared anchor empty."""
    tc = nodes.new("ShaderNodeTexCoord")
    tc.object = _texspace()
    return tc.outputs["Object"]


def _noise(nodes, links, co, scale, detail=4.0, rough=0.5):
    n = nodes.new("ShaderNodeTexNoise")
    n.inputs["Scale"].default_value = scale
    n.inputs["Detail"].default_value = detail
    if "Roughness" in n.inputs:
        n.inputs["Roughness"].default_value = rough
    links.new(co, n.inputs["Vector"])
    return n


def _bump(nodes, links, height_out, strength, bsdf):
    b = nodes.new("ShaderNodeBump")
    b.inputs["Strength"].default_value = strength
    links.new(height_out, b.inputs["Height"])
    links.new(b.outputs["Normal"], bsdf.inputs["Normal"])
    return b


def _mix_colors(nodes, links, fac_out, c1, c2, bsdf):
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (*c1, 1.0)
    ramp.color_ramp.elements[1].color = (*c2, 1.0)
    links.new(fac_out, ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    return ramp


def build_rich_material(name, key):
    p = PALETTE.get(key, dict(base=(0.6, 0.6, 0.6)))
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*p["base"], 1.0)
    co = _coords(nodes, links)

    if key.startswith("wood"):
        # grain: stretched wave rings distorted by noise, two-tone ramp
        mapping = nodes.new("ShaderNodeMapping")
        mapping.inputs["Scale"].default_value = (1.0, 8.0, 8.0)   # stretch grain along X
        links.new(co, mapping.inputs["Vector"])
        wave = nodes.new("ShaderNodeTexWave")
        wave.inputs["Scale"].default_value = 3.0
        wave.inputs["Distortion"].default_value = 6.0
        wave.inputs["Detail"].default_value = 3.0
        links.new(mapping.outputs["Vector"], wave.inputs["Vector"])
        _mix_colors(nodes, links, wave.outputs["Fac"], p["dark"], p["base"], bsdf)
        bsdf.inputs["Roughness"].default_value = 0.55
        _bump(nodes, links, wave.outputs["Fac"], 0.04, bsdf)

    elif key == "concrete-boardformed":
        # horizontal formwork boards + fine mottle
        mapping = nodes.new("ShaderNodeMapping")
        mapping.inputs["Scale"].default_value = (0.02, 0.02, 1.0)  # bands vary with Z
        links.new(co, mapping.inputs["Vector"])
        wave = nodes.new("ShaderNodeTexWave")
        wave.inputs["Scale"].default_value = 5.5                   # ~0.18 m boards
        wave.inputs["Distortion"].default_value = 0.4
        links.new(mapping.outputs["Vector"], wave.inputs["Vector"])
        n = _noise(nodes, links, co, 24.0, detail=6.0)
        mixh = nodes.new("ShaderNodeMix") if hasattr(bpy.types, "ShaderNodeMix") else nodes.new("ShaderNodeMixRGB")
        try:
            mixh.data_type = "FLOAT"
            mixh.inputs["Factor"].default_value = 0.35
            links.new(wave.outputs["Fac"], mixh.inputs["A"])
            links.new(n.outputs["Fac"], mixh.inputs["B"])
            hout = mixh.outputs["Result"]
        except Exception:
            mixh.inputs["Fac"].default_value = 0.35
            links.new(wave.outputs["Fac"], mixh.inputs["Color1"])
            links.new(n.outputs["Fac"], mixh.inputs["Color2"])
            hout = mixh.outputs["Color"]
        base = p["base"]
        _mix_colors(nodes, links, n.outputs["Fac"],
                    (base[0]*0.86, base[1]*0.86, base[2]*0.86), base, bsdf)
        bsdf.inputs["Roughness"].default_value = 0.85
        _bump(nodes, links, hout, 0.25, bsdf)

    elif key.startswith("concrete") or key == "ground":
        n = _noise(nodes, links, co, 18.0, detail=8.0)
        pores = _noise(nodes, links, co, 90.0, detail=2.0)
        base = p["base"]
        _mix_colors(nodes, links, n.outputs["Fac"],
                    (base[0]*0.82, base[1]*0.82, base[2]*0.82),
                    (base[0]*1.06, base[1]*1.06, base[2]*1.06), bsdf)
        bsdf.inputs["Roughness"].default_value = 0.75
        _bump(nodes, links, pores.outputs["Fac"], 0.14, bsdf)

    elif key == "plaster-white":
        n = _noise(nodes, links, co, 45.0, detail=6.0)
        base = p["base"]
        _mix_colors(nodes, links, n.outputs["Fac"],
                    (base[0]*0.93, base[1]*0.93, base[2]*0.93), base, bsdf)
        bsdf.inputs["Roughness"].default_value = 0.85
        _bump(nodes, links, n.outputs["Fac"], 0.12, bsdf)

    elif key == "metal-corrugated":
        mapping = nodes.new("ShaderNodeMapping")
        mapping.inputs["Scale"].default_value = (1.0, 0.02, 0.02)
        links.new(co, mapping.inputs["Vector"])
        wave = nodes.new("ShaderNodeTexWave")
        wave.inputs["Scale"].default_value = 12.0
        try:
            wave.wave_profile = "TRI"
        except Exception:
            pass
        links.new(mapping.outputs["Vector"], wave.inputs["Vector"])
        bsdf.inputs["Metallic"].default_value = 0.9
        bsdf.inputs["Roughness"].default_value = 0.45
        _bump(nodes, links, wave.outputs["Fac"], 0.3, bsdf)

    elif key in ("steel-painted-sage", "steel-galvanized", "aluminium-anodized"):
        n = _noise(nodes, links, co, 40.0, detail=5.0)
        ramp = nodes.new("ShaderNodeValToRGB")
        lo = 0.25 if key != "steel-painted-sage" else 0.35
        ramp.color_ramp.elements[0].color = (lo, lo, lo, 1.0)
        hi = lo + 0.25
        ramp.color_ramp.elements[1].color = (hi, hi, hi, 1.0)
        links.new(n.outputs["Fac"], ramp.inputs["Fac"])
        links.new(ramp.outputs["Color"], bsdf.inputs["Roughness"])
        bsdf.inputs["Metallic"].default_value = 0.2 if key == "steel-painted-sage" else 1.0

    elif key == "rubber-black":
        n = _noise(nodes, links, co, 55.0, detail=7.0)
        _mix_colors(nodes, links, n.outputs["Fac"],
                    (0.03, 0.03, 0.035), (0.09, 0.09, 0.095), bsdf)
        bsdf.inputs["Roughness"].default_value = 0.92
        _bump(nodes, links, n.outputs["Fac"], 0.15, bsdf)

    elif key == "pv":
        brick = nodes.new("ShaderNodeTexBrick")
        brick.inputs["Scale"].default_value = 6.0
        brick.inputs["Mortar Size"].default_value = 0.015
        brick.inputs["Color1"].default_value = (0.02, 0.05, 0.14, 1.0)
        brick.inputs["Color2"].default_value = (0.03, 0.07, 0.20, 1.0)
        brick.inputs["Mortar"].default_value = (0.65, 0.67, 0.70, 1.0)
        try:
            brick.offset = 0.0
        except Exception:
            pass
        links.new(co, brick.inputs["Vector"])
        links.new(brick.outputs["Color"], bsdf.inputs["Base Color"])
        bsdf.inputs["Roughness"].default_value = 0.15
        bsdf.inputs["Metallic"].default_value = 0.3

    elif key == "foliage":
        n = _noise(nodes, links, co, 14.0, detail=8.0)
        _mix_colors(nodes, links, n.outputs["Fac"], p["dark"], p["base"], bsdf)
        bsdf.inputs["Roughness"].default_value = 0.8
        big = _noise(nodes, links, co, 5.0, detail=10.0)
        _bump(nodes, links, big.outputs["Fac"], 0.6, bsdf)

    elif key == "lampheads":
        bsdf.inputs["Roughness"].default_value = 0.4
        if "Emission Color" in bsdf.inputs:
            bsdf.inputs["Emission Color"].default_value = (1.0, 0.85, 0.6, 1.0)
        bsdf.inputs["Emission Strength"].default_value = 8.0

    elif key.startswith("glass") or key.startswith("polycarbonate"):
        tkey = "Transmission Weight" if "Transmission Weight" in bsdf.inputs else "Transmission"
        bsdf.inputs[tkey].default_value = 1.0
        bsdf.inputs["IOR"].default_value = 1.45
        bsdf.inputs["Roughness"].default_value = {
            "glass-clear": 0.03, "glass-laminated": 0.05,
            "polycarbonate-opal": 0.4, "polycarbonate-clear": 0.15}.get(key, 0.05)

    else:
        bsdf.inputs["Roughness"].default_value = 0.6

    return mat
