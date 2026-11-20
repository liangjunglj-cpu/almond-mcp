"""Blender: derive detailed library meshes without inflating source polygon counts.

blender --factory-startup -b --python tools/prepare_organic_meshes.py -- BATCH
Dense provider outputs remain under raw/BATCH; derivatives and QA are staged there.
"""
import hashlib
import json
import math
from pathlib import Path
import sys

import bmesh
import bpy

REPO = Path(__file__).resolve().parents[1]
batch = json.loads(Path(sys.argv[sys.argv.index('--') + 1]).read_text())
root = REPO / 'GeneratedAssetfiles/raw' / batch['batch_id']
output = root / 'prepared'
output.mkdir(exist_ok=True)
records_path = output / 'quality.json'
records = json.loads(records_path.read_text()) if records_path.exists() else []
only = sys.argv[sys.argv.index('--') + 2:]

for asset in batch['assets']:
    aid = asset['asset_id']
    if only and aid not in only:
        continue
    source = root / (aid + '.glb')
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    source_triangles = sum(len(p.vertices) - 2 for o in meshes for p in o.data.polygons)
    if not source_triangles:
        raise ValueError('Empty source: ' + aid)
    for obj in meshes:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    if batch.get('strip_source_materials'):
        # Textured provider meshes: the library assigns Almond materials, so drop the
        # provider's PBR materials and their embedded texture images before export.
        obj.data.materials.clear()
    print('VALIDATING', aid, source_triangles, flush=True)
    validation_repairs = int(obj.data.validate(verbose=True, clean_customdata=True))
    if any(not math.isfinite(v) for vert in obj.data.vertices for v in vert.co):
        raise ValueError('Nonfinite source coordinates: ' + aid)
    before_bounds = list(obj.dimensions)
    mesh = bmesh.new()
    mesh.from_mesh(obj.data)
    weld_tolerance = max(before_bounds) * 1e-7
    bmesh.ops.remove_doubles(mesh, verts=list(mesh.verts), dist=weld_tolerance)
    bmesh.ops.dissolve_degenerate(mesh, edges=list(mesh.edges), dist=weld_tolerance)
    bmesh.ops.recalc_face_normals(mesh, faces=list(mesh.faces))
    mesh.to_mesh(obj.data)
    mesh.free()
    validation_repairs += int(obj.data.validate(verbose=True, clean_customdata=True))
    for attempt in range(4):
        triangle_count = sum(len(p.vertices)-2 for p in obj.data.polygons)
        if triangle_count <= asset['target_triangles'] + 100:
            break
        print('REDUCING', aid, triangle_count, 'pass', attempt + 1, flush=True)
        modifier = obj.modifiers.new('Almond detailed derivative', 'DECIMATE')
        modifier.ratio = asset['target_triangles'] / triangle_count
        modifier.use_collapse_triangulate = True
        bpy.ops.object.modifier_apply(modifier=modifier.name)
        validation_repairs += int(obj.data.validate(verbose=True, clean_customdata=True))
    # Recalculate normals after reduction; retain actual organic geometry, no subdivision.
    mesh = bmesh.new()
    mesh.from_mesh(obj.data)
    bmesh.ops.triangulate(mesh, faces=list(mesh.faces))
    bmesh.ops.recalc_face_normals(mesh, faces=list(mesh.faces))
    mesh.to_mesh(obj.data)
    mesh.free()
    validation_repairs += int(obj.data.validate(verbose=True, clean_customdata=True))
    topology_repairs = {}
    if batch.get('repair_nonmanifold'):
        # Opt-in per batch: loose wire edges are removed, edges shared by more than two faces are split
        # (each face keeps its own edge, so they become open boundaries) and zero-area faces are removed.
        mesh = bmesh.new()
        mesh.from_mesh(obj.data)
        wires = [e for e in mesh.edges if e.is_wire]
        if wires:
            bmesh.ops.delete(mesh, geom=wires, context='EDGES')
        crowded = [e for e in mesh.edges if len(e.link_faces) > 2]
        if crowded:
            bmesh.ops.split_edges(mesh, edges=crowded)
        flat = [f for f in mesh.faces if f.calc_area() <= 0]
        if flat:
            bmesh.ops.delete(mesh, geom=flat, context='FACES_ONLY')
        loose = [v for v in mesh.verts if not v.link_faces]
        if loose:
            bmesh.ops.delete(mesh, geom=loose, context='VERTS')
        mesh.to_mesh(obj.data)
        mesh.free()
        validation_repairs += int(obj.data.validate(verbose=True, clean_customdata=True))
        topology_repairs = {'wire_edges_removed': len(wires), 'nonmanifold_edges_split': len(crowded),
                            'zero_area_faces_removed': len(flat), 'loose_vertices_removed': len(loose)}
    mesh = bmesh.new()
    mesh.from_mesh(obj.data)
    mesh.verts.ensure_lookup_table()
    visited = set()
    components = []
    for vertex in mesh.verts:
        if vertex in visited:
            continue
        stack = [vertex]
        visited.add(vertex)
        size = 0
        while stack:
            current = stack.pop()
            size += 1
            for edge in current.link_edges:
                other = edge.other_vert(current)
                if other not in visited:
                    visited.add(other)
                    stack.append(other)
        components.append(size)
    quality = {
        'vertices': len(mesh.verts), 'triangles': len(mesh.faces),
        'boundary_edges': sum(e.is_boundary for e in mesh.edges),
        'nonmanifold_edges_excluding_boundary': sum(len(e.link_faces) > 2 or e.is_wire for e in mesh.edges),
        'zero_area_faces': sum(f.calc_area() <= 0 for f in mesh.faces),
        'connected_components': len(components),
        'largest_component_vertices': max(components),
        'nonfinite_coordinates': sum(not math.isfinite(c) for v in mesh.verts for c in v.co),
        'self_intersections': 'not_tested',
        'mesh_validation_repair_passes': validation_repairs,
        **({'topology_repairs': topology_repairs} if topology_repairs else {}),
        'use': 'Visual entourage; not certified for fabrication or structural analysis'
    }
    if quality['zero_area_faces'] or quality['nonfinite_coordinates'] or quality['triangles'] > asset['target_triangles'] + 100:
        raise ValueError('Invalid output: ' + aid + ' ' + json.dumps({k: quality[k] for k in ('zero_area_faces', 'nonfinite_coordinates', 'triangles')}))
    mesh.to_mesh(obj.data)
    mesh.free()
    for p in obj.data.polygons:
        p.use_smooth = True
    bpy.context.view_layer.update()
    quality['bounds_relative_change'] = [abs(a-b)/a if a else 0 for a,b in zip(before_bounds,obj.dimensions)]
    target = output / (aid + '.glb')
    bpy.ops.export_scene.gltf(filepath=str(target), export_format='GLB', export_animations=False,
                             export_texcoords=False, export_materials='EXPORT', export_extras=False,
                             use_selection=True)
    records = [record for record in records if record['asset_id'] != aid]
    records.append({'asset_id':aid,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                    'source_triangles':source_triangles,'target_triangles':asset['target_triangles'],
                    'prepared_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
                    'software':'Blender '+bpy.app.version_string,
                    'method':('Remove provider PBR materials and textures; ' if batch.get('strip_source_materials') else '')+'Validate mesh; weld coincident vertices; dissolve degenerates; recalculate normals; collapse decimation only when above target with validation between passes; triangulate and validate before measuring.'
                    +(' Remove wire edges, split edges shared by more than two faces and remove zero-area faces (counts in quality.topology_repairs).' if topology_repairs else '')+' Never subdivide to inflate counts.',
                    'weld_tolerance_source_units':weld_tolerance,'quality':quality})
    print('PREPARED', aid, source_triangles, '->', quality['triangles'], quality, flush=True)

    records_path.write_text(json.dumps(records,indent=2)+'\n')
