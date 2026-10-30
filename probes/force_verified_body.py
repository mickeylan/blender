import bpy, os, math
from mathutils import Vector
sc=bpy.context.scene
# 强制全体可见并排除集合排除
for vl in sc.view_layers:
    def walk(c):
        c.exclude=False; c.hide_viewport=False
        for ch in c.children: walk(ch)
    walk(vl.layer_collection)
for o in bpy.data.objects:
    o.hide_render=False; o.hide_viewport=False; o.hide_set(False)
cam=bpy.data.objects.get('WarriorCam'); sc.camera=cam
# 用全体 mesh 的世界包围盒自动框选，避免手工机位再次裁切
lo=Vector((1e9,1e9,1e9)); hi=Vector((-1e9,-1e9,-1e9))
for o in bpy.data.objects:
    if o.type!='MESH' or o.name in ('Ground','LookFloor','LookWall'): continue
    for c in o.bound_box:
        p=o.matrix_world @ Vector(c)
        lo.x=min(lo.x,p.x); lo.y=min(lo.y,p.y); lo.z=min(lo.z,p.z)
        hi.x=max(hi.x,p.x); hi.y=max(hi.y,p.y); hi.z=max(hi.z,p.z)
target=(lo+hi)*0.5; radius=(hi-lo).length*0.5
cam.data.lens=52
d=Vector((-0.72,-1.25,0.10)).normalized(); fov=2*math.atan(.5*cam.data.sensor_width/cam.data.lens)
cam.location=target+d*(radius/math.sin(fov*.5)*1.12)
cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler()
sc.render.engine='BLENDER_EEVEE'; sc.render.resolution_x=900; sc.render.resolution_y=1200; sc.render.resolution_percentage=100
sc.render.image_settings.file_format='PNG'; sc.render.image_settings.color_mode='RGB'; sc.render.image_settings.color_depth='8'
sc.render.filepath=r'J:\mickeylan\ai\blender\out\FINAL_FULL_BODY.png'
bpy.ops.render.render(write_still=True)
# 只显示腰以下，用于事实诊断
upper_prefix=('Head','Hair_','Pony','SideLock','Fringe','Eye','Lid','Brow','Nose','Lip','Neck','Deltoid','Clavicle','UpperArm','Forearm','Palm','Finger','Thumb','Fist','Sword_','Ruan_','Collar_','Sleeve_','Cuff_','BackSash')
changed=[]
for o in bpy.data.objects:
    if o.type=='MESH' and o.name.startswith(upper_prefix): changed.append((o,o.hide_render)); o.hide_render=True
deliver=sc.render.filepath
sc.render.filepath=r'J:\mickeylan\ai\blender\out\LOWER_BODY_DIAGNOSTIC.png'
bpy.ops.render.render(write_still=True)
for o,h in changed: o.hide_render=h
sc.render.filepath=deliver
bpy.ops.wm.save_as_mainfile(filepath=r'J:\mickeylan\ai\blender\out\warrior_lookdev.blend')
print('AUTO_BBOX',tuple(round(x,3) for x in lo),tuple(round(x,3) for x in hi),'target',tuple(round(x,3) for x in target),'radius',round(radius,3))
print('RENDERED FINAL_FULL_BODY and LOWER_BODY_DIAGNOSTIC')
