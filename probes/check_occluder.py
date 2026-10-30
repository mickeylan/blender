import bpy
from mathutils import Vector
for name in ('LookFloor','Ground','LookWall'):
 o=bpy.data.objects.get(name)
 if o:
  zs=[(o.matrix_world@Vector(c)).z for c in o.bound_box]
  print(name,'z',min(zs),max(zs),'scale',tuple(o.scale),'hide',o.hide_render)
for p in ('Thigh_','Calf_','Foot_'):
 for o in bpy.data.objects:
  if o.name.startswith(p):
   zs=[(o.matrix_world@Vector(c)).z for c in o.bound_box]; print(o.name,min(zs),max(zs),o.hide_render)
