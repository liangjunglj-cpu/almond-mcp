"""Blender: bounded architectural derivatives of user-supplied Meshy OBJ files.

blender --factory-startup -b --python tools/convert_project_meshes.py -- PROJECT CONFIG OUTPUT
Source files and textures are never edited. OUTPUT is private staging, not a release directory.
"""
import hashlib
import json
from pathlib import Path
import sys
import bpy

source, config_file, output = map(Path, sys.argv[sys.argv.index('--') + 1:])
source = source.resolve()
config = json.loads(config_file.read_text(encoding='utf-8'))
output.mkdir(parents=True, exist_ok=True)
records = []
for asset in config['assets']:
    path = (source / asset['source']).resolve()
    if not path.is_relative_to(source):
        raise ValueError('Source path escapes project')
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.wm.obj_import(filepath=str(path), forward_axis='NEGATIVE_Z', up_axis='Y')
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    before = sum(len(p.vertices)-2 for o in meshes for p in o.data.polygons)
    for obj in meshes:
        bpy.context.view_layer.objects.active = obj
        if before > 20000:
            modifier = obj.modifiers.new('Almond compact geometry', 'DECIMATE')
            modifier.ratio = 19800 / before
            bpy.ops.object.modifier_apply(modifier=modifier.name)
        obj.data.materials.clear()
        # Geometry edition: source textures remain in Y2K; Almond assigns a named material.
        material = bpy.data.materials.new(asset['material'])
        obj.data.materials.append(material)
        for polygon in obj.data.polygons: polygon.material_index = 0
    target = output / (asset['asset_id'] + '.glb')
    bpy.ops.export_scene.gltf(filepath=str(target), export_format='GLB', export_animations=False,
                              export_texcoords=False, export_materials='EXPORT', export_cameras=False,
                              export_lights=False, export_extras=False)
    after = sum(len(p.vertices)-2 for o in meshes for p in o.data.polygons)
    record = {'asset_id':asset['asset_id'], 'source_file':asset['source'],
              'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
              'source_bytes':path.stat().st_size, 'source_triangles':before,
              'output_triangles':after, 'converted_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
              'converter':'Blender '+bpy.app.version_string, 'triangle_target':20000,
              'coordinate_transform':'OBJ Y-up to Blender Z-up; exported glTF Y-up',
              'material_derivation':'Source texture atlases omitted; assigned Almond semantic material, not original textured appearance'}
    records.append(record)
    print('CONVERTED', asset['asset_id'], before, '->', after, flush=True)
(output/'conversion-record.json').write_text(json.dumps(records,indent=2)+'\n',encoding='utf-8')
