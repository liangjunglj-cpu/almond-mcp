import bpy, collections
sc = bpy.context.scene
print('ENGINE', sc.render.engine, sc.render.resolution_x, sc.render.resolution_y, 'cam', sc.camera and sc.camera.name)
print('COLLECTIONS', [c.name for c in bpy.data.collections])
objs = [o for o in sc.objects]
print('NOBJ', len(objs), collections.Counter(o.type for o in objs))
keys = collections.Counter(k for o in objs for k in o.keys())
print('PROPS', keys.most_common(20))
for o in objs[:5]:
    print('SAMPLE', o.name, {k: o[k] for k in o.keys() if isinstance(o[k], (str, int, float))})
lay = collections.Counter(str(o.get('rhino_layer') or o.get('layer') or o.get('Rhino.Layer')) for o in objs)
print('LAYERS', lay.most_common(30))
for o in objs:
    if o.type in ('LIGHT', 'CAMERA'):
        print('LC', o.name, o.type, tuple(round(v, 2) for v in o.location), o.data.type if o.type == 'LIGHT' else o.data.lens)
print('WORLD', sc.world and sc.world.name, [n.bl_idname for n in sc.world.node_tree.nodes] if sc.world and sc.world.use_nodes else None)
print('MATS', len(bpy.data.materials), [m.name for m in bpy.data.materials][:60])
print('VIEW', sc.view_settings.view_transform, sc.view_settings.look, sc.view_settings.exposure)
