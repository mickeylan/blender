"""坊市宏伟主图升级：只在现有 cultivation_market.blend 上追加展示层。

目标不是堆摊位，而是用尺度、纵深、轴线和低机位表现仙城坊市的宏伟。
"""
import bpy, os, math
from mathutils import Vector

OUT=r"J:\mickeylan\ai\blender\out"
SRC=os.path.join(OUT,'cultivation_market.blend')
COLL='GrandHero'

def getmat(name, color, rough=.5, metal=0):
    m=bpy.data.materials.get(name) or bpy.data.materials.new(name); m.use_nodes=True
    n=next((x for x in m.node_tree.nodes if x.type=='BSDF_PRINCIPLED'),None)
    if n:
        n.inputs['Base Color'].default_value=(*color,1); n.inputs['Roughness'].default_value=rough
        if 'Metallic' in n.inputs:n.inputs['Metallic'].default_value=metal
    return m

def move(o,c):
    for q in list(o.users_collection): q.objects.unlink(o)
    c.objects.link(o)

def cube(c,name,loc,scale,mat,rot=(0,0,0),bev=.04):
    bpy.ops.mesh.primitive_cube_add(location=loc,rotation=rot); o=bpy.context.view_layer.objects.active; o.name=name; o.scale=scale; move(o,c); o.data.materials.append(mat)
    if bev:
        b=o.modifiers.new('GrandSoft','BEVEL'); b.width=bev; b.segments=2
    return o

def cyl(c,name,loc,r,depth,mat,verts=20):
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts,radius=r,depth=depth,location=loc); o=bpy.context.view_layer.objects.active; o.name=name; move(o,c); o.data.materials.append(mat); return o

def beam(c,name,a,b,r,mat):
    a=Vector(a); b=Vector(b); d=b-a; o=cyl(c,name,(a+b)/2,r,d.length,mat,16); o.rotation_euler=d.to_track_quat('Z','Y').to_euler(); return o

def lantern(c,loc,frame,glow):
    cyl(c,'GrandLamp',loc,.22,.55,frame,16); bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2,radius=.14,location=(loc[0],loc[1],loc[2]+.02)); o=bpy.context.view_layer.objects.active; move(o,c); o.data.materials.append(glow)

def main():
    bpy.ops.wm.open_mainfile(filepath=SRC)
    sc=bpy.context.scene
    c=bpy.data.collections.get(COLL) or bpy.data.collections.new(COLL)
    if c.name not in sc.collection.children: sc.collection.children.link(c)
    stone=getmat('GrandStone',(.10,.14,.20),.88); wood=getmat('GrandWood',(.18,.025,.012),.5); roof=getmat('GrandRoof',(.018,.045,.09),.55); gold=getmat('GrandGold',(.52,.20,.035),.3,.55); glow=getmat('GrandGlow',(.04,.32,.85),.16); purple=getmat('GrandPurple',(.28,.025,.62),.18)
    # 巨型两侧塔楼，作为入口尺度锚点
    for x in (-10,10):
        for z in (2.5,5.0,7.5):
            cube(c,'MonumentTower',(x,0,z),(1.15,1.15,.75),wood,bev=.08)
            for dx in (-.85,.85):
                cyl(c,'TowerColumn',(x+dx,0,z+1.0),.16,2.0,gold,12)
        cube(c,'TowerRoof',(x,0,9.1),(1.8,1.8,.18),roof,rot=(0,0,math.radians(45)),bev=.05)
        cyl(c,'TowerSpire',(x,0,10.1),.18,1.8,gold,12)
        lantern(c,(x,-1.5,6.2),gold,glow)
    # 主殿后方的巨大悬空法坛，制造远端制高点
    cube(c,'GrandTerrace',(0,12,7.2),(7.0,2.6,.35),stone,bev=.12)
    cube(c,'GrandPalace',(0,13,11.0),(5.2,2.0,3.2),wood,bev=.10)
    for x in (-4.2,4.2):
        cyl(c,'PalaceCol',(x,11.3,11),.32,6.8,gold,20)
        beam(c,'PalaceBrace',(x,11.3,8.0),(x*.72,10.5,12.8),.16,gold)
    cube(c,'PalaceRoofA',(0,11.2,14.5),(6.4,2.8,.28),roof,rot=(math.radians(-7),0,0),bev=.08)
    cube(c,'PalaceRoofB',(0,14.8,14.5),(6.4,2.8,.28),roof,rot=(math.radians(7),0,0),bev=.08)
    cyl(c,'PalaceSpire',(0,13,16.5),.28,3.5,gold,20)
    # 多层悬桥，把入口轴线导向主殿
    for level,y in enumerate((3.5,7.0,10.5)):
        z=3.8+level*1.35
        for x in (-4.5,4.5): beam(c,'SuspensionCable',(x,y-2.0,z+1.6),(x,y+2.0,z),.10,gold)
        for yy in [y-2+i*.5 for i in range(9)]: cube(c,'SuspensionPlank',(0,yy,z),(4.4,.18,.10),wood,bev=.02)
    # 大尺度空中灵脉环
    for i in range(3):
        a=math.radians(18+i*120); center=Vector((0,7,9.5)); r=5.5+i*.8
        pts=[]
        for j in range(25):
            t=j/24*math.tau; p=center+Vector((r*math.cos(t),.15*r*math.sin(t),.35*math.sin(t*2)))
            pts.append(p)
        for j in range(len(pts)-1): beam(c,'SpiritRing',(pts[j]),(pts[j+1]),.055,purple)
    # 前景巨大灯柱，强化镜头尺度
    for x in (-7.0,7.0):
        cyl(c,'ForeLampPost',(x,-8,3.0),.20,6.0,gold,16); lantern(c,(x,-8,6.5),gold,glow)
    # 摄影棚/世界调整：深色天空，主殿轮廓有冷边光
    w=bpy.data.worlds.get('MarketWorld');
    if w:
        w.use_nodes=True; bg=next(n for n in w.node_tree.nodes if n.type=='BACKGROUND'); bg.inputs['Strength'].default_value=.10
    # 重新布置主图灯光
    for o in list(bpy.data.objects):
        if o.type=='LIGHT' and o.name.startswith('Grand'): bpy.data.objects.remove(o,do_unlink=True)
    for name,loc,energy,color,size in [('GrandKey',(-12,-18,16),2600,(1.0,.32,.12),7),('GrandFill',(12,-2,14),1800,(.12,.30,1.0),6),('GrandRim',(0,15,18),2400,(.40,.08,1.0),5)]:
        ld=bpy.data.lights.new(name,'AREA'); ld.energy=energy; ld.color=color; ld.shape='DISK'; ld.size=size; o=bpy.data.objects.new(name,ld); c.objects.link(o); o.location=loc; o.rotation_euler=(Vector((0,3,6))-o.location).to_track_quat('-Z','Y').to_euler()
    cam=bpy.data.objects.get('MarketCam')
    if cam is None:
        cd=bpy.data.cameras.new('MarketCam'); cam=bpy.data.objects.new('MarketCam',cd); sc.collection.objects.link(cam)
    sc.camera=cam; cam.data.lens=30
    target=Vector((0,3.5,6.0)); cam.location=Vector((23,- thirty if False else -30,16))
    cam.location=Vector((23,-30,16)); cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler()
    sc.render.engine='BLENDER_EEVEE'; sc.render.resolution_x=1600; sc.render.resolution_y=900; sc.render.resolution_percentage=100; sc.render.image_settings.file_format='PNG'; sc.view_settings.view_transform='AgX'; sc.view_settings.look='AgX - Medium High Contrast'; sc.render.filepath=os.path.join(OUT,'market_grand_hero.png'); bpy.ops.render.render(write_still=True)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT,'cultivation_market_grand.blend'))
    print('GRAND MARKET OK objects=%d' % sum(o.type=='MESH' for o in bpy.data.objects))
try: main()
except Exception:
 import traceback; traceback.print_exc(); raise
