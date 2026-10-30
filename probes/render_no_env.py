import bpy
sc=bpy.context.scene
for n in ('LookFloor','LookWall','Ground'):
 o=bpy.data.objects.get(n)
 if o:o.hide_render=True
sc.render.filepath=r'J:\mickeylan\ai\blender\out\NO_ENV_FULL.png'
bpy.ops.render.render(write_still=True)
print('rendered')
