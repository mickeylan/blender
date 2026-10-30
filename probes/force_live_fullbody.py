import bpy
import os
from mathutils import Vector
sc=bpy.context.scene
# 强制恢复所有集合和对象的显示状态
for lc in sc.view_layers:
    def walk(c):
        c.exclude=False
        c.hide_viewport=False
        for ch in c.children: walk(ch)
    walk(lc.layer_collection)
for o in bpy.data.objects:
    o.hide_viewport=False
    o.hide_render=False
    o.hide_set(False)
    p=o.parent
    while p:
        p.hide_viewport=False; p.hide_render=False; p.hide_set(False)
        p=p.parent
# 清除局部视图无法通过 bpy 稳定控制；设回全身相机并渲染
cam=bpy.data.objects.get('WarriorCam')
if cam is None: raise RuntimeError('WarriorCam missing')
sc.camera=cam
cam.location=Vector((-2.381,-4.134,1.311))
cam.rotation_euler=(Vector((0,0,0.98))-cam.location).to_track_quat('-Z','Y').to_euler()
cam.data.lens=58
sc.render.engine='BLENDER_EEVEE'
sc.render.resolution_x=900; sc.render.resolution_y=1200; sc.render.resolution_percentage=100
sc.render.image_settings.file_format='PNG'; sc.render.image_settings.color_mode='RGB'; sc.render.image_settings.color_depth='8'
sc.render.filepath=r'J:\mickeylan\ai\blender\out\LIVE_FULL_BODY.png'
bpy.ops.render.render(write_still=True)
bpy.ops.wm.save_as_mainfile(filepath=r'J:\mickeylan\ai\blender\out\warrior_lookdev.blend')
print('LIVE_FULL_BODY_RENDERED',sc.render.filepath)
print('LOWER',[(o.name,o.hide_render,o.hide_viewport,o.hide_get()) for o in bpy.data.objects if o.name.startswith(('Thigh_','Calf_','Foot_'))])
