"""第一版气象万千修仙宗门：场景 + 巡游摄像机动画。
Blender 5.2/MCP safe：手动清场，不调用 read_factory_settings。
"""
import bpy, math, os
from mathutils import Vector
OUT=r"J:\mickeylan\ai\blender\out"
COLL='XianmenSect'

def active(): return bpy.context.view_layer.objects.active

def clear():
    for o in list(bpy.data.objects): bpy.data.objects.remove(o,do_unlink=True)
    for c in list(bpy.data.collections):
        try: bpy.data.collections.remove(c)
        except: pass
    for db in (bpy.data.meshes,bpy.data.curves,bpy.data.materials,bpy.data.cameras,bpy.data.lights):
        for x in list(db):
            if x.users==0:
                try: db.remove(x)
                except: pass

def mat(name,col,rough=.6,metal=0,emit=0):
    m=bpy.data.materials.new(name); m.diffuse_color=(*col,1); m.use_nodes=True
    n=next((n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED'),None)
    if n:
        n.inputs['Base Color'].default_value=(*col,1); n.inputs['Roughness'].default_value=rough
        if 'Metallic' in n.inputs:n.inputs['Metallic'].default_value=metal
        if emit and 'Emission Color' in n.inputs:
            n.inputs['Emission Color'].default_value=(*col,1); n.inputs['Emission Strength'].default_value=emit
    return m

def move(o,c):
    for q in list(o.users_collection): q.objects.unlink(o)
    c.objects.link(o)

def cube(c,n,loc,sc,m,rot=(0,0,0),bev=.03):
    bpy.ops.mesh.primitive_cube_add(location=loc,rotation=rot); o=active(); o.name=n; o.scale=sc; move(o,c); o.data.materials.append(m)
    if bev: b=o.modifiers.new('Edge','BEVEL'); b.width=bev; b.segments=2
    return o

def cyl(c,n,loc,r,d,m,verts=16):
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts,radius=r,depth=d,location=loc); o=active(); o.name=n; move(o,c); o.data.materials.append(m); return o

def cone(c,n,loc,r1,r2,d,m):
    bpy.ops.mesh.primitive_cone_add(vertices=24,radius1=r1,radius2=r2,depth=d,location=loc); o=active(); o.name=n; move(o,c); o.data.materials.append(m); return o

def beam(c,n,a,b,r,m):
    a=Vector(a); b=Vector(b); d=b-a; o=cyl(c,n,(a+b)/2,r,d.length,m,12); o.rotation_euler=d.to_track_quat('Z','Y').to_euler(); return o

def text(c,n,body,loc,size,m):
    cu=bpy.data.curves.new(n,'FONT'); cu.body=body; cu.align_x='CENTER'; cu.size=size; cu.extrude=.015
    o=bpy.data.objects.new(n,cu); c.objects.link(o); o.location=loc; o.rotation_euler=(math.pi/2,0,0); o.data.materials.append(m); return o

def roof(c,p,x,y,z,w,d,wood,tile,gold):
    cube(c,p+'RoofF',(x,y-d*.27,z),(w,d*.72,.11),tile,rot=(math.radians(-10),0,0))
    cube(c,p+'RoofB',(x,y+d*.27,z),(w,d*.72,.11),tile,rot=(math.radians(10),0,0))
    beam(c,p+'Ridge',(x-w,y,z+.55),(x+w,y,z+.55),.10,gold)
    for i in range(1,8):
        xx=x-w+i*2*w/8; beam(c,p+'Rafter',(xx,y-d*.62,z-.06),(xx,y,z+.55),.025,wood); beam(c,p+'Rafter',(xx,y,z+.55),(xx,y+d*.62,z-.06),.025,wood)

def hall(c,p,x,y,z,w,d,wood,tile,stone,gold,levels=1):
    cube(c,p+'Platform',(x,y,z-.35),(w+.5,d+.5,.35),stone,bev=.08)
    for lev in range(levels):
        zz=z+lev*2.3
        for xx in (x-w*.75,x,x+w*.75):
            for yy in (y-d,y+d):
                cyl(c,p+'Column',(xx,yy,zz+1),.13,2,wood,16)
                cube(c,p+'Bracket',(xx,yy,zz+2.02),(.28,.24,.09),gold)
        cube(c,p+'BeamF',(x,y-d,zz+2.0),(w,.12,.12),wood)
        roof(c,p+'Roof',x,y,zz+2.2,w+.35,d+.3,wood,tile,gold)

def main():
    clear(); bpy.ops.wm.read_factory_settings(use_empty=True) if False else None
    c=bpy.data.collections.new(COLL); bpy.context.scene.collection.children.link(c)
    rock=mat('MountainRock',(.055,.09,.13),.95); rock2=mat('PeakSnow',(.16,.22,.28),.88); stone=mat('WhiteStone',(.28,.31,.34),.86); wood=mat('CinnabarWood',(.24,.035,.018),.48); tile=mat('AzureTile',(.025,.07,.13),.58); gold=mat('GildedMetal',(.62,.27,.045),.3,.55); jade=mat('SpiritJade',(.02,.40,.32),.2,0,1.5); cyan=mat('ArrayCyan',(.03,.30,.85),.18,0,2); purple=mat('ArrayPurple',(.34,.03,.8),.2,0,2); fog=mat('Cloud',(.22,.30,.40),.9)
    # 山体底座
    cube(c,'WorldBase',(0,8,-2),(32,28,2),rock,bev=.3)
    peaks=[(-18,15,12,7),(-12,19,18,6),(-6,23,25,7),(1,25,32,8),(9,23,23,7),(16,19,17,6),(22,14,11,6),(-24,10,9,5),(26,9,10,5)]
    for i,(x,y,z,r) in enumerate(peaks):
        cone(c,'NinePeak_%02d'%i,(x,y,z/2),r*.9,.5,z,rock)
        cone(c,'PeakCrown_%02d'%i,(x,y,z*.78),r*.45,.08,z*.45,rock2)
    # 中轴石阶和山门
    for i in range(12): cube(c,'AxisStep',(0,-17+i*1.35,.15+i*.08),(3.8,.62,.10),stone,bev=.03)
    for x in (-4.8,4.8):
        cube(c,'HeavenGatePillar',(x,-17,3.2),(.55,.65,3.2),stone,bev=.1); roof(c,'HeavenGate',0,-17,6.6,6.2,.9,wood,tile,gold)
    beam(c,'HeavenGateBeam',(-5.4,-17,6.0),(5.4,-17,6.0),.25,wood); text(c,'HeavenGateTitle','太虚玄门',(0,-17.72,5.8),.8,gold)
    # 主峰主殿
    hall(c,'MainPalace',0,8,10,6.5,2.4,wood,tile,stone,gold,levels=2); text(c,'MainTitle','太虚宗',(0,5.35,14.3),.8,gold)
    # 分区建筑
    hall(c,'AlchemyPeak',-13,2,4,3.0,1.7,wood,tile,stone,gold); text(c,'AlchemyTitle','丹峰',(-13,.15,7),.5,gold)
    hall(c,'WeaponPeak',13,2,4,3.0,1.7,wood,tile,stone,gold); text(c,'WeaponTitle','器峰',(13,.15,7),.5,gold)
    hall(c,'Scripture',-12,12,6,3.4,1.8,wood,tile,stone,gold,levels=2); text(c,'ScriptureTitle','藏经阁',(-12,10,10.7),.5,gold)
    hall(c,'Medicine',13,13,5,3.4,1.8,wood,tile,stone,gold); text(c,'MedicineTitle','灵药园',(13,11,8.8),.5,gold)
    # 演武场
    cyl(c,'MartialArena',(0,-2,.35),4.3,.35,stone,32); cyl(c,'MartialInner',(0,-2,.55),3.5,.08,jade,32)
    for i in range(8):
        a=i*math.tau/8; beam(c,'ArenaRail',(4.1*math.cos(a),-2+4.1*math.sin(a),.8),(4.3*math.cos(a),-2+4.3*math.sin(a),.8),.08,gold)
    # 灵脉线和护山大阵
    for i in range(5):
        y=-12+i*6; beam(c,'SpiritVein',(-25,y,1),(25,y+5,1.6),.09,jade)
    for ring,r in enumerate((12,18,25)):
        pts=[]
        for j in range(49):
            a=j/48*math.tau; pts.append((r*math.cos(a),8+r*.38*math.sin(a),12+r*.08*math.sin(2*a)))
        for j in range(48): beam(c,'ArrayRing_%d'%ring,pts[j],pts[j+1],.045,cyan if ring%2==0 else purple)
    for i in range(12):
        a=i*math.tau/12; beam(c,'ArrayRay',(0,8,12),(25*math.cos(a),8+10*math.sin(a),2),.035,gold)
    # 云海
    for i in range(30):
        a=i*math.tau/30; x=22*math.cos(a); y=8+14*math.sin(a); z=1.0+.5*math.sin(i*2.7); bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2,radius=1,location=(x,y,z)); o=active(); o.name='Cloud_%02d'%i; o.scale=(3.4,1.7,.55); move(o,c); o.data.materials.append(fog)
    # 飞舟
    for i,(x,y,z) in enumerate([(-9,-5,8),(10,8,13),(6,-9,10)]):
        cube(c,'CloudBoatDeck',(x,y,z),(.9,.3,.12),wood); cone(c,'CloudBoatSail',(x,y,z+1),.5,.05,1.8,purple)
    # world and lights
    w=bpy.data.worlds.new('SectWorld'); w.use_nodes=True; bg=next(n for n in w.node_tree.nodes if n.type=='BACKGROUND'); bg.inputs['Color'].default_value=(.002,.006,.02,1); bg.inputs['Strength'].default_value=.14; bpy.context.scene.world=w
    for name,loc,en,col,size in [('Moon',(-18,-20,25),3500,(.35,.55,1),9),('Warm',(0,-8,14),1600,(1,.28,.10),6),('Array',(0,10,18),2600,(.2,.4,1),8)]:
        ld=bpy.data.lights.new(name,'AREA'); ld.energy=en; ld.color=col; ld.shape='DISK'; ld.size=size; o=bpy.data.objects.new(name,ld); c.objects.link(o); o.location=loc; o.rotation_euler=(Vector((0,8,5))-o.location).to_track_quat('-Z','Y').to_euler()
    # 镜头与巡游动画：高空->山门->演武->丹器峰->藏经阁->主峰->离开
    cd=bpy.data.cameras.new('SectTourCamera'); cam=bpy.data.objects.new('SectTourCamera',cd); c.objects.link(cam); bpy.context.scene.camera=cam; cd.lens=38
    shots=[(1,(0,-42,42),(0,8,8)),(90,(0,-29,20),(0,-8,5)),(180,(0,-12,9),(0,-1,4)),(270,(-15,-1,8),(-13,2,5)),(360,(15,0,9),(13,2,5)),(450,(-14,10,12),(-12,12,8)),(540,(0,1,20),(0,8,12)),(630,(0,18,34),(0,8,9)),(720,(22,34,48),(0,8,8))]
    for f,loc,tgt in shots:
        cam.location=loc; cam.rotation_euler=(Vector(tgt)-cam.location).to_track_quat('-Z','Y').to_euler(); cam.keyframe_insert(data_path='location',frame=f); cam.keyframe_insert(data_path='rotation_euler',frame=f)
    sc=bpy.context.scene; sc.frame_start=1; sc.frame_end=720; sc.render.fps=24; sc.render.engine='BLENDER_EEVEE'; sc.render.resolution_x=1280; sc.render.resolution_y=720; sc.render.resolution_percentage=100; sc.render.image_settings.file_format='PNG'; sc.render.filepath=os.path.join(OUT,'sect_tour_frame_####.png'); sc.view_settings.view_transform='AgX'; sc.view_settings.look='AgX - Medium High Contrast'
    # 输出高空建立镜头和主峰高潮帧
    for f,n in [(1,'sect_aerial.png'),(180,'sect_gate.png'),(540,'sect_mainpeak.png'),(720,'sect_departure.png')]: sc.frame_set(f); sc.render.filepath=os.path.join(OUT,n); bpy.ops.render.render(write_still=True)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT,'xianmen_sect_tour.blend'))
    print('XIANMEN TOUR OK objects=%d frames=720'%sum(o.type=='MESH' for o in bpy.data.objects))
try: main()
except Exception:
 import traceback; traceback.print_exc(); raise
