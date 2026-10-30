import bpy
from mathutils import Vector
sc=bpy.context.scene
print('SCENE', sc.name, 'CAM', sc.camera.name if sc.camera else None)
for p in ('Thigh_','Calf_','Foot_','Skirt','Body_'):
    obs=[o for o in bpy.data.objects if o.type=='MESH' and o.name.startswith(p)]
    print(p, 'count=',len(obs), 'hide_render=',[(o.name,o.hide_render) for o in obs], 'hide_view=',[(o.name,o.hide_viewport) for o in obs])
# current camera projected bounds
if sc.camera:
    from bpy_extras.object_utils import world_to_camera_view
    cam=sc.camera
    for p in ('Thigh_','Calf_','Foot_','Skirt'):
        pts=[]
        for o in bpy.data.objects:
            if o.type=='MESH' and o.name.startswith(p):
                for c in o.bound_box:
                    pts.append(world_to_camera_view(sc,cam,o.matrix_world @ Vector(c)))
        if pts: print('PROJ',p,'x',min(x.x for x in pts),max(x.x for x in pts),'y',min(x.y for x in pts),max(x.y for x in pts))
print('RENDER', sc.render.filepath, sc.render.resolution_x, sc.render.resolution_y)
