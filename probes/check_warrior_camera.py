import bpy
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view
path = r'J:\mickeylan\ai\blender\out\warrior_lookdev.blend'
bpy.ops.wm.open_mainfile(filepath=path)
sc=bpy.context.scene; cam=sc.camera
print('CAMERA', cam.name, tuple(round(x,3) for x in cam.location), 'lens', cam.data.lens)
for prefix in ('Thigh_','Calf_','Foot_','Skirt','Body_','Head'):
    obs=[o for o in bpy.data.objects if o.type=='MESH' and o.name.startswith(prefix)]
    if not obs: continue
    pts=[]
    for o in obs:
        for c in o.bound_box: pts.append(world_to_camera_view(sc,cam,o.matrix_world@Vector(c)))
    print(prefix,'count',len(obs),'hidden',sum(o.hide_render for o in obs),'z',round(min(p.z for p in pts),3),round(max(p.z for p in pts),3),'x',round(min(p.x for p in pts),3),round(max(p.x for p in pts),3),'y',round(min(p.y for p in pts),3),round(max(p.y for p in pts),3))
