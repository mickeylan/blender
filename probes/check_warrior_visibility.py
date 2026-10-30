import bpy
path = r'J:\mickeylan\ai\blender\out\warrior_lookdev.blend'
bpy.ops.wm.open_mainfile(filepath=path)
low = [o for o in bpy.data.objects if o.type == 'MESH' and o.name.startswith(('Thigh_','Calf_','Foot_','Skirt'))]
hid = [o.name for o in low if o.hide_render or o.hide_viewport]
print('LOWER_MESHES=%d HIDDEN=%d' % (len(low), len(hid)))
print('HIDDEN_NAMES=' + ','.join(hid))
print('BODY_MESHES=%d' % sum(1 for o in bpy.data.objects if o.type == 'MESH'))
