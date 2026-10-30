"""修正宗门巡游预览中出现的近黑段落：补光 + 拉远近景机位 + 提高环境底光。"""
import bpy, os, math
from mathutils import Vector

BLEND=r"J:\mickeylan\ai\blender\out\xianmen_sect_tour.blend"
OUT=r"J:\mickeylan\ai\blender\out"

def add_light(c,name,loc,energy,color,size,target):
    ld=bpy.data.lights.new(name,'AREA'); ld.energy=energy; ld.color=color; ld.shape='DISK'; ld.size=size
    o=bpy.data.objects.new(name,ld); c.objects.link(o); o.location=loc
    o.rotation_euler=(Vector(target)-o.location).to_track_quat('-Z','Y').to_euler()
    return o

def main():
    bpy.ops.wm.open_mainfile(filepath=BLEND)
    sc=bpy.context.scene
    c=bpy.data.collections.get('XianmenSect')
    # 1) 提高环境底光，避免远景纯黑
    w=sc.world; bg=next(n for n in w.node_tree.nodes if n.type=='BACKGROUND')
    bg.inputs['Strength'].default_value=0.30
    bg.inputs['Color'].default_value=(0.02,0.05,0.12,1)
    # 2) 侧峰补光（丹峰/器峰之前完全没被主光照到）
    add_light(c,'FillAlchemy',(-18,-6,14),1400,(0.45,0.6,1.0),8,(-13,2,5))
    add_light(c,'FillWeapon',(19,-4,15),1400,(0.5,0.62,1.0),8,(13,2,5))
    add_light(c,'FillScripture',(-16,6,16),1100,(1.0,0.55,0.35),7,(-12,12,8))
    add_light(c,'FillMedicine',(17,8,15),1100,(0.6,0.7,1.0),7,(13,13,7))
    add_light(c,'FillGate',(0,-22,9),900,(1.0,0.42,0.18),6,(0,-14,4))
    # 3) 修正过暗的两处机位：器峰拉远抬高，离场补远景轮廓光
    cam=bpy.data.objects.get('SectTourCamera')
    newshots={360:((20,-4,12),(13,2,5.5)),701:((22,30,44),(0,8,10)),720:((26,38,52),(0,8,8))}
    for f,(loc,tgt) in newshots.items():
        cam.location=loc; cam.rotation_euler=(Vector(tgt)-cam.location).to_track_quat('-Z','Y').to_euler()
        cam.keyframe_insert(data_path='location',frame=f); cam.keyframe_insert(data_path='rotation_euler',frame=f)
    add_light(c,'RimDeparture',(-10,30,26),2200,(0.35,0.5,1.0),10,(0,8,9))
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT,'xianmen_sect_tour.blend'))
    print('XIANMEN LIGHTING FIX OK')
main()
