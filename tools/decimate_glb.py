"""Blender headless: reduce a dense GLB to a target triangle count.

Meshy's ultra mode returns multi-million-triangle meshes; entourage needs
tens of thousands. Collapse-decimate keeps the silhouette and the foliage
clumps while dropping the file from hundreds of MB to a few MB.

Run: blender -b --python tools/decimate_glb.py -- <in.glb> <out.glb> <target_tris>
"""
import sys
from pathlib import Path

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
SRC, DST, TARGET = Path(argv[0]), Path(argv[1]), int(argv[2])

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(SRC))
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
bpy.ops.object.select_all(action="DESELECT")
for o in meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
if len(meshes) > 1:
    bpy.ops.object.join()
obj = bpy.context.active_object
before = sum(len(p.vertices) - 2 for p in obj.data.polygons)
ratio = min(1.0, TARGET / max(before, 1))
mod = obj.modifiers.new("dec", "DECIMATE")
mod.decimate_type = "COLLAPSE"
mod.ratio = ratio
mod.use_collapse_triangulate = True
bpy.ops.object.modifier_apply(modifier="dec")
# Meshy ultra output is unindexed (three vertices per triangle); merge them so
# the exporter can share vertices, and skip stored normals - Rhino recomputes.
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.mesh.remove_doubles(threshold=1e-5)
bpy.ops.mesh.delete_loose(use_verts=True, use_edges=True, use_faces=False)
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.mesh.normals_make_consistent(inside=False)
bpy.ops.object.mode_set(mode="OBJECT")
after = sum(len(p.vertices) - 2 for p in obj.data.polygons)
bpy.ops.object.shade_smooth()
bpy.ops.object.select_all(action="SELECT")
DST.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.export_scene.gltf(filepath=str(DST), export_format="GLB", use_selection=True,
                          export_yup=True, export_apply=True, export_normals=False)
print(f"DECIMATED {SRC.name}: {before} -> {after} tris, {len(obj.data.vertices)} verts "
      f"(ratio {ratio:.4f}) -> {DST.stat().st_size / 1e6:.1f} MB")
