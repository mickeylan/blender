import bpy
sc=bpy.context.scene
for n in ('LookFloor','LookWall','Ground'):
 o=bpy.data.objects.get(n)
 if o:o.hide_render=True; o.hide_viewport=True
for o in bpy.data.objects:
 if o.type=='MESH': o.hide_render=False; o.hide_viewport=False; o.hide_set(False)
# re-hide environment after blanket restore
for n in ('LookFloor','LookWall','Ground'):
 o=bpy.data.objects.get(n)
 if o:o.hide_render=True; o.hide_viewport=True
sc.render.engine='BLENDER_EEVEE'; sc.render.resolution_x=900; sc.render.resolution_y=1200; sc.render.resolution_percentage=100
sc.render.filepath=r'J:\mickeylan\ai\blender\out\FINAL_FULL_BODY.png'
bpy.ops.render.render(write_still=True)
bpy.ops.wm.save_as_mainfile(filepath=r'J:\mickeylan\ai\blender\out\warrior_lookdev.blend')
print('FINAL_NO_ENV_SAVED')
