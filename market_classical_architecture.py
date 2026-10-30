"""把宏伟坊市的建筑体块改成中国古典建筑语汇。

依据：cultivation_market_brief.md + blender-visual-craft 的“硬表面检查边缘、
支撑和装配；先构图再细节”。本脚本只改建筑展示层，不改灵泉、灯阵和整体镜头。

建筑构造表达：
  台基 -> 柱网 -> 梁架 -> 斗拱 -> 出檐 -> 坡屋顶 -> 正脊/垂脊 -> 格栅与匾额。
不是历史复原；是北宋坊市语汇上的修仙幻想设计。
"""
import bpy, os, math
from mathutils import Vector

OUT=r"J:\mickeylan\ai\blender\out"
SRC=os.path.join(OUT,'cultivation_market_grand.blend')
COLL='ClassicalArchitecture'

def mat(name,color,rough=.55,metal=0):
 m=bpy.data.materials.get(name) or bpy.data.materials.new(name); m.use_nodes=True
 n=next((n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED'),None)
 if n:
  n.inputs['Base Color'].default_value=(*color,1); n.inputs['Roughness'].default_value=rough
  if 'Metallic' in n.inputs:n.inputs['Metallic'].default_value=metal
 return m

def move(o,c):
 for q in list(o.users_collection): q.objects.unlink(o)
 c.objects.link(o)

def active(): return bpy.context.view_layer.objects.active

def box(c,name,loc,scale,m,rot=(0,0,0),bev=.025):
 bpy.ops.mesh.primitive_cube_add(location=loc,rotation=rot); o=active(); o.name=name; o.scale=scale; move(o,c); o.data.materials.append(m)
 if bev:
  b=o.modifiers.new('ClassicalEdge','BEVEL'); b.width=bev; b.segments=2
 return o

def cyl(c,name,loc,r,depth,m,verts=16):
 bpy.ops.mesh.primitive_cylinder_add(vertices=verts,radius=r,depth=depth,location=loc); o=active(); o.name=name; move(o,c); o.data.materials.append(m); return o

def beam(c,name,a,b,r,m):
 a=Vector(a); b=Vector(b); d=b-a; o=cyl(c,name,(a+b)/2,r,d.length,m,12); o.rotation_euler=d.to_track_quat('Z','Y').to_euler(); return o

def text(c,name,body,loc,size,m):
 cu=bpy.data.curves.new(name,'FONT'); cu.body=body; cu.align_x='CENTER'; cu.size=size; cu.extrude=.012
 o=bpy.data.objects.new(name,cu); c.objects.link(o); o.location=loc; o.rotation_euler=(math.pi/2,0,0); o.data.materials.append(m); return o

def roof(c,prefix,x,y,z,w,d,wood,tile,gold):
 # 悬山双坡：两片有明确坡度的屋面 + 檐口 + 正脊 + 垂脊
 eave=0.62; rise=.72
 box(c,prefix+'_RoofFront',(x,y-d*.25,z),(w,d*.72,.10),tile,rot=(math.radians(-10),0,0),bev=.035)
 box(c,prefix+'_RoofBack',(x,y+d*.25,z),(w,d*.72,.10),tile,rot=(math.radians(10),0,0),bev=.035)
 beam(c,prefix+'_Ridge',(x,y,z+rise),(x+w,y,z+rise),.11,gold)
 beam(c,prefix+'_EaveFront',(x-w,y-d*.62,z-eave*.1),(x+w,y-d*.62,z-eave*.1),.075,wood)
 beam(c,prefix+'_EaveBack',(x-w,y+d*.62,z-eave*.1),(x+w,y+d*.62,z-eave*.1),.075,wood)
 # 瓦垄/椽条，顺坡重复排列
 for i in range(1,8):
  xx=x-w+i*(2*w/8)
  beam(c,prefix+'_RafterF', (xx,y-d*.62,z-eave*.1),(xx,y,z+rise),.028,wood)
  beam(c,prefix+'_RafterB', (xx,y,z+rise),(xx,y+d*.62,z-eave*.1),.028,wood)
 # 两端鸱尾简化为上翘脊饰
 for sx in (-1,1):
  beam(c,prefix+'_HipRidge',(x+sx*w,y,z+rise),(x+sx*(w+.45),y,z+rise+.32),.065,gold)

def bracket(c,prefix,x,y,z,wood,gold):
 # 一组简化斗拱：坐斗、拱臂、昂，必须位于柱头下方
 box(c,prefix+'_Dou',(x,y,z),(.18,.18,.11),wood,bev=.025)
 box(c,prefix+'_HuaGong',(x,y,z+.18),(.46,.12,.08),wood,bev=.02)
 box(c,prefix+'_Ang',(x,y-.14,z+.27),(.52,.10,.07),wood,rot=(math.radians(-12),0,0),bev=.02)
 box(c,prefix+'_TopBlock',(x,y,z+.36),(.32,.22,.08),gold,bev=.02)

def classical_shop(c,x,y,label,wood,tile,stone,gold,paper):
 # 三开间街屋：窄面、深进、明确台基和柱网
 box(c,label+'_Platform',(x,y,.22),(2.15,1.55,.22),stone,bev=.08)
 for ix in (-1,0,1):
  xx=x+ix*1.65
  for yy in (y-1.05,y+1.05):
   cyl(c,label+'_Column',(xx,yy,1.62),.16,2.8,wood,16)
   bracket(c,label+'_Bracket',xx,yy,3.02,wood,gold)
 # 横向额枋/檐下梁
 for yy in (y-1.05,y+1.05): beam(c,label+'_EaveBeam',(x-2.15,yy,3.05),(x+2.15,yy,3.05),.11,wood)
 for ix in (-.825,.825): beam(c,label+'_BayBeam',(x+ix,y-1.1,1.35),(x+ix,y+1.1,1.35),.09,wood)
 # 格栅窗：每开间两竖两横
 for ix in (-1.65,0,1.65):
  for dx in (-.48,.48): beam(c,label+'_LatticeV',(x+ix+dx,y-1.20,1.65),(x+ix+dx,y-1.20,2.65),.035,gold)
  beam(c,label+'_LatticeH',(x+ix-.5,y-1.20,1.95),(x+ix+.5,y-1.20,1.95),.035,gold)
  beam(c,label+'_LatticeH',(x+ix-.5,y-1.20,2.35),(x+ix+.5,y-1.20,2.35),.035,gold)
 roof(c,label,x,y,3.25,2.55,1.65,wood,tile,gold)
 text(c,label+'_Plaque',label,(x,y-1.42,2.7),.34,paper)

def classical_hall(c,x,y,wood,tile,stone,gold):
 # 五开间主殿：高台、前廊、柱网、斗拱、重檐
 box(c,'HallClassicalPlatform',(x,y,3.0),(7.3,3.0,.45),stone,bev=.12)
 for level,(z,w,d) in enumerate(((5.0,6.6,2.35),(7.8,5.8,2.0))):
  for ix in (-2.5,-1.25,0,1.25,2.5):
   if abs(ix)>w/2: continue
   for yy in (y-d,y+d):
    cyl(c,'HallColumn',(x+ix,yy,z),.22,3.6 if level==0 else 2.5,wood,20)
    bracket(c,'HallBracket',x+ix,yy,z+1.65 if level==0 else z+1.15,wood,gold)
  # 阑额和檐口
  beam(c,'HallFrontBeam',(x-w,y-d,z+1.65),(x+w,y-d,z+1.65),.15,wood)
  beam(c,'HallBackBeam',(x-w,y+d,z+1.65),(x+w,y+d,z+1.65),.15,wood)
  roof(c,'HallRoof%d'%level,x,y,z+2.0,w+.65,d+.38,wood,tile,gold)
 text(c,'HallClassicalPlaque','天机殿',(x,y-3.35,8.4),.72,gold)

def main():
 bpy.ops.wm.open_mainfile(filepath=SRC); sc=bpy.context.scene
 old=bpy.data.collections.get(COLL)
 if old:
  for o in list(old.objects): bpy.data.objects.remove(o,do_unlink=True)
  bpy.data.collections.remove(old)
 c=bpy.data.collections.new(COLL); sc.collection.children.link(c)
 wood=mat('SongWood',(.20,.035,.018),.55); tile=mat('SongTile',(.025,.07,.11),.62); stone=mat('SongStone',(.18,.20,.22),.88); gold=mat('SongMetal',(.52,.22,.045),.3,.5); paper=mat('SongPaper',(.66,.40,.10),.7)
 # 隐藏旧的方盒店铺/主殿，保留宏伟塔楼、桥和灵脉
 for o in bpy.data.objects:
  if o.type=='MESH' and o.name.startswith(('ShopBase','ShopUpper','ShopPost','Roof','HallPlatform','MainHall','HallColumn','HallRoof')):
   o.hide_render=True; o.hide_viewport=True
 classical_shop(c,-5,-1,'丹阁',wood,tile,stone,gold,paper)
 classical_shop(c,5,-1,'器阁',wood,tile,stone,gold,paper)
 classical_shop(c,-5,5,'符坊',wood,tile,stone,gold,paper)
 classical_shop(c,5,5,'灵茶',wood,tile,stone,gold,paper)
 classical_hall(c,0,12,wood,tile,stone,gold)
 # 入口牌楼：柱—额—檐—匾，而非两根巨柱加横梁
 for x in (-4.8,4.8):
  box(c,'PaifangBase',(x,-10,.35),(.65,.65,.35),stone,bev=.08)
  cyl(c,'PaifangColumn',(x,-10,2.8),.28,5.0,wood,20); bracket(c,'PaifangBracket',x,-10,5.1,wood,gold)
 beam(c,'PaifangBeam',(-5.4,-10,5.4),(5.4,-10,5.4),.22,wood)
 roof(c,'PaifangRoof',0,-10,5.7,5.8,.72,wood,tile,gold)
 text(c,'PaifangPlaque','万象坊',(0,-10.82,5.25),.72,paper)
 # 重新保存并输出一张古典建筑主图
 cam=bpy.data.objects.get('MarketCam'); sc.camera=cam; cam.data.lens=32; target=Vector((0,2.8,5.2)); cam.location=Vector((23,-30,16)); cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler()
 sc.render.engine='BLENDER_EEVEE'; sc.render.resolution_x=1600; sc.render.resolution_y=900; sc.render.resolution_percentage=100; sc.render.image_settings.file_format='PNG'; sc.render.filepath=os.path.join(OUT,'market_classical_hero.png'); bpy.ops.render.render(write_still=True)
 bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT,'cultivation_market_classical.blend'))
 print('CLASSICAL ARCHITECTURE OK objects=%d'%sum(o.type=='MESH' for o in bpy.data.objects))
try: main()
except Exception:
 import traceback; traceback.print_exc(); raise
