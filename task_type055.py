"""055 型万吨级驱逐舰——公开外形级重建版。

本版本先建立真正的舰体轮廓，再叠加上层建筑；不是工程图纸，也不涉及内部
系统。坐标：X 为舰艏方向（正 X 艏），Y 为左右舷，Z 为高度。
"""
import bpy, math, os
from mathutils import Vector
OUT=r"J:\mickeylan\ai\blender\out"

def active(): return bpy.context.view_layer.objects.active

def clear():
    for o in list(bpy.data.objects): bpy.data.objects.remove(o,do_unlink=True)
    for c in list(bpy.data.collections):
        try:bpy.data.collections.remove(c)
        except:pass

def mat(name,col,rough=.55,metal=0):
    m=bpy.data.materials.new(name); m.diffuse_color=(*col,1); m.use_nodes=True
    n=next((x for x in m.node_tree.nodes if x.type=='BSDF_PRINCIPLED'),None)
    if n:
        n.inputs['Base Color'].default_value=(*col,1); n.inputs['Roughness'].default_value=rough
        if 'Metallic' in n.inputs:n.inputs['Metallic'].default_value=metal
    return m

def cube(n,loc,sc,m,rot=(0,0,0),bev=.03):
    bpy.ops.mesh.primitive_cube_add(location=loc,rotation=rot); o=active(); o.name=n; o.scale=sc; o.data.materials.append(m)
    if bev:b=o.modifiers.new('Edge','BEVEL');b.width=bev;b.segments=2
    return o

def cyl(n,loc,r,d,m,verts=20,rot=(0,0,0)):
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts,radius=r,depth=d,location=loc,rotation=rot);o=active();o.name=n;o.data.materials.append(m);return o

def beam(n,a,b,r,m):
    a=Vector(a);b=Vector(b);d=b-a;o=cyl(n,(a+b)/2,r,d.length,m,12);o.rotation_euler=d.to_track_quat('Z','Y').to_euler();return o

def mesh_obj(name,verts,faces,m):
    me=bpy.data.meshes.new(name+'Mesh');me.from_pydata(verts,[],faces);me.materials.append(m);o=bpy.data.objects.new(name,me);bpy.context.collection.objects.link(o);return o

def tapered_block(name,x0,x1,y0,y1,z0,z1,top_y0,top_y1,top_z,m):
    # 8点斜收上层建筑
    v=[(x0,-y0,z0),(x0,y0,z0),(x1,y0,z0),(x1,-y0,z0),
       (x0,-top_y0,top_z),(x0,top_y0,top_z),(x1,top_y1,top_z),(x1,-top_y1,top_z)]
    f=[(0,1,2,3),(4,7,6,5),(0,4,5,1),(1,5,6,2),(2,6,7,3),(3,7,4,0)]
    return mesh_obj(name,v,f,m)

def hull(m):
    # 从艏到艉的横截面：尖艏、宽船腰、收艉；每截面绕一圈形成连续船壳
    stations=[(-8.6,.18,1.50,.32),(-7.8,.95,1.62,.30),(-6.0,1.42,1.82,.28),(-3.0,1.70,1.98,.25),(1.5,1.72,2.00,.25),(5.2,1.55,2.08,.26),(7.3,1.02,2.18,.30),(8.45,.10,2.28,.40)]
    # y,z 轮廓：甲板边、舭部、龙骨，再回到另一舷
    ring=[]; N=8
    for x,bw,dz,keel in stations:
        ring += [(x,-bw*.42,dz),(x,-bw,dz-.18),(x,-bw*.86,keel+.28),(x,-bw*.42,keel),(x,0,keel-.06),(x,bw*.42,keel),(x,bw*.86,keel+.28),(x,bw,dz-.18),(x,bw*.42,dz)]
    verts=ring; faces=[]
    for i in range(len(stations)-1):
        for j in range(N+1):
            a=i*9+j; b=i*9+(j+1)%9; c=(i+1)*9+(j+1)%9; d=(i+1)*9+j; faces.append((a,b,c,d))
    faces.append(tuple(range(8,-1,-1))); faces.append(tuple((len(stations)-1)*9+j for j in range(9)))
    return mesh_obj('HullMain',verts,faces,m)

def main():
    clear()
    hullmat=mat('055_Hull',(0.07,.085,.095),.46,.15); deckmat=mat('055_Deck',(.025,.035,.042),.68); stealth=mat('055_Stealth',(.012,.018,.024),.35,.1); glass=mat('055_Glass',(.01,.055,.08),.15,.25); red=mat('055_Mark',(.65,.035,.02),.42); white=mat('055_Number',(.72,.74,.70),.38); metal=mat('055_Metal',(.34,.17,.035),.35,.55); sea=mat('055_Sea',(.004,.025,.045),.18)
    hull(hullmat)
    # 甲板轮廓与舷侧折角带
    cube('MainDeck',(0,0,2.18),(7.15,1.38,.08),deckmat,bev=.02)
    beam('PortChine',(-7.8,-1.08,1.72),(6.8,-1.35,2.05),.045,stealth); beam('StarboardChine',(-7.8,1.08,1.72),(6.8,1.35,2.05),.045,stealth)
    # 前后 VLS，嵌在甲板上，不再悬浮成外挂方块
    for x,count in ((5.0,16),(-4.2,32)):
        for i in range(count):
            xx=x+(i%8-3.5)*.42; yy=(-.62 if i//8==0 else .62)
            cube('VLS_FlushHatch',(xx,yy,2.29),(.15,.15,.018),stealth,bev=.01)
    # 艏炮低矮隐身炮塔和长炮管
    cyl('MainGunRing',(5.72,0,2.48),.72,.12,stealth,32)
    tapered_block('MainGunTurret',5.25,6.25,.48,.40,2.48,2.48,.30,.30,2.98,stealth)
    beam('MainGunBarrel',(5.72,0,3.02),(7.15,0,3.16),.105,stealth)
    # 前部大体量综合舰桥：斜面收口，不用正方盒子
    tapered_block('ForwardIsland',.1,3.35,1.02,1.0,2.28,2.28,.73,.68,5.25,hullmat)
    tapered_block('BridgeUpper',.48,2.75,.78,.74,5.25,5.25,.60,.55,5.92,stealth)
    # 连续斜窗带
    for z in (4.45,4.72): cube('BridgeWindow',(1.52,-1.035,z),(1.0,.025,.075),glass,rot=(0,math.radians(-4),0),bev=.008)
    # 后部低矮上层建筑、烟囱和直升机机库
    tapered_block('AftIsland',-3.15,-1.15,.88,.84,2.28,2.28,.67,.62,4.85,hullmat)
    tapered_block('Funnel',-3.0,-1.95,.48,.44,4.82,4.82,.34,.30,5.65,stealth)
    cube('HelicopterHangar',(-4.15,0,3.35),(1.05,1.03,.62),hullmat,bev=.05)
    cube('HelicopterDeck',(-6.25,0,2.30),(1.65,1.28,.07),deckmat,bev=.02)
    beam('HMark1',(-6.95,-.82,2.40),(-5.55,.82,2.40),.025,red);beam('HMark2',(-6.95,.82,2.40),(-5.55,-.82,2.40),.025,red)
    # 综合桅杆与四面阵列面板
    beam('IntegratedMast',(1.62,0,5.85),(1.62,0,8.1),.11,stealth)
    for z in (6.15,6.85,7.5):
        cube('AESA_Port',(1.62,-.73,z),(.68,.07,.30),stealth,rot=(math.radians(-7),0,0),bev=.018)
        cube('AESA_Starboard',(1.62,.73,z),(.68,.07,.30),stealth,rot=(math.radians(7),0,0),bev=.018)
    cyl('MastTop',(1.62,0,8.35),.18,.32,stealth,20)
    # 舷侧小艇舱门和标识
    for y in (-1.43,1.43): cube('BoatBay',(-1.0,y,3.0),(1.05,.025,.28),stealth,bev=.01)
    text=bpy.data.curves.new('HullNumber','FONT');text.body='055';text.align_x='CENTER';text.size=.52;text.extrude=.008;o=bpy.data.objects.new('HullNumber',text);bpy.context.collection.objects.link(o);o.location=(-1.1,-1.47,1.35);o.rotation_euler=(math.pi/2,0,0);o.data.materials.append(white)
    cube('Water',(0,0,-.12),(18,8,.08),sea,bev=.01)
    # 灯光、相机、四张轮廓验证图
    w=bpy.data.worlds.new('055_World');w.use_nodes=True;bg=next(n for n in w.node_tree.nodes if n.type=='BACKGROUND');bg.inputs['Color'].default_value=(.003,.007,.016,1);bg.inputs['Strength'].default_value=.20;bpy.context.scene.world=w
    col=bpy.context.collection
    for name,loc,en,color,size in [('Key',(10,-14,12),1900,(1,.52,.28),6),('Fill',(-10,9,9),1300,(.25,.45,1),5)]:
        ld=bpy.data.lights.new(name,'AREA');ld.energy=en;ld.color=color;ld.shape='DISK';ld.size=size;ob=bpy.data.objects.new(name,ld);col.objects.link(ob);ob.location=loc;ob.rotation_euler=(Vector((0,0,2))-ob.location).to_track_quat('-Z','Y').to_euler()
    cd=bpy.data.cameras.new('Type055_Camera');cam=bpy.data.objects.new('Type055_Camera',cd);col.objects.link(cam);bpy.context.scene.camera=cam;cd.lens=55
    sc=bpy.context.scene;sc.render.engine='BLENDER_EEVEE';sc.render.resolution_x=1400;sc.render.resolution_y=800;sc.render.resolution_percentage=100;sc.render.image_settings.file_format='PNG';sc.view_settings.view_transform='AgX';sc.view_settings.look='AgX - Medium High Contrast'
    views=[('type055_hero',(15,-18,8),(0,0,2.1)),('type055_bow',(15,-7,4.5),(4.5,0,2.25)),('type055_side',(0,-20,4.5),(0,0,2.1)),('type055_top',(5,-10,17),(0,0,2.0))]
    for n,loc,tgt in views:
        cam.location=loc;cam.rotation_euler=(Vector(tgt)-cam.location).to_track_quat('-Z','Y').to_euler();sc.render.filepath=os.path.join(OUT,n+'.png');bpy.ops.render.render(write_still=True)
    cam.location=views[0][1];cam.rotation_euler=(Vector(views[0][2])-cam.location).to_track_quat('-Z','Y').to_euler();bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT,'type055_destroyer.blend'))
    print('TYPE055 REBUILD OK objects=%d'%sum(o.type=='MESH' for o in bpy.data.objects))
try:main()
except Exception:
 import traceback;traceback.print_exc();raise
