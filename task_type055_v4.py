"""055 外形 v4：修正"像潜艇"的问题。

v3 缺陷：横截面是圆滑椭圆 + 整体光滑着色 + 干舷过低，
读成潜艇。本版改为军舰应有的船体语言：
  平底 -> 硬舭折角 -> 外飘舷侧 -> 明显舷弧 -> 艏部甲板台阶（forecastle break）
并取消整体光滑着色，让折面在光下读出结构。
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
def mat(n,c,r=.55,metal=0,emit=0):
 m=bpy.data.materials.new(n);m.diffuse_color=(*c,1);m.use_nodes=True;p=next((x for x in m.node_tree.nodes if x.type=='BSDF_PRINCIPLED'),None)
 if p:
  p.inputs['Base Color'].default_value=(*c,1);p.inputs['Roughness'].default_value=r
  if 'Metallic' in p.inputs:p.inputs['Metallic'].default_value=metal
  if emit and 'Emission Color' in p.inputs:
   p.inputs['Emission Color'].default_value=(*c,1);p.inputs['Emission Strength'].default_value=emit
 return m
def cube(n,p,s,m,rot=(0,0,0),bev=.03):
 bpy.ops.mesh.primitive_cube_add(location=p,rotation=rot);o=active();o.name=n;o.scale=s;o.data.materials.append(m)
 if bev:b=o.modifiers.new('Edge','BEVEL');b.width=bev;b.segments=2
 return o
def cyl(n,p,r,d,m,v=20,rot=(0,0,0)):
 bpy.ops.mesh.primitive_cylinder_add(vertices=v,radius=r,depth=d,location=p,rotation=rot);o=active();o.name=n;o.data.materials.append(m);return o
def beam(n,a,b,r,m):
 a=Vector(a);b=Vector(b);d=b-a;o=cyl(n,(a+b)/2,r,d.length,m,12);o.rotation_euler=d.to_track_quat('Z','Y').to_euler();return o
def mesh(n,v,f,m,smooth=False):
 me=bpy.data.meshes.new(n+'Mesh');me.from_pydata(v,[],f);me.materials.append(m);o=bpy.data.objects.new(n,me);bpy.context.collection.objects.link(o)
 if smooth:
  for p in me.polygons:p.use_smooth=True
 return o
def tapered(n,x0,x1,b0,b1,z0,zt,t0,t1,m):
 v=[(x0,-b0,z0),(x0,b0,z0),(x1,b1,z0),(x1,-b1,z0),(x0,-t0,zt),(x0,t0,zt),(x1,t1,zt),(x1,-t1,zt)]
 f=[(0,1,2,3),(4,7,6,5),(0,4,5,1),(1,5,6,2),(2,6,7,3),(3,7,4,0)]
 return mesh(n,v,f,m)

# 驱逐舰横截面（半边）：平底 -> 硬舭 -> 外飘舷侧 -> 舷边
# 每个站点: (x, 半宽, 甲板z, 平底半宽, 舭部z, 舷侧外飘量)
STATIONS=[
 # x,    beam, deck_z, flat_half, chine_z, flare
 (-90,  6.6,  7.6,  4.0,  3.4, 0.05),
 (-84,  8.6,  7.7,  5.4,  3.6, 0.10),
 (-66,  9.9,  8.0,  6.2,  3.9, 0.18),
 (-40, 10.9,  8.4,  6.8,  4.2, 0.26),
 (-8,  11.2,  8.9,  7.0,  4.4, 0.30),
 (26,  10.9,  9.3,  6.7,  4.5, 0.30),
 (52,  9.8,  9.7,  6.0,  4.6, 0.26),
 (68,  8.2, 10.1,  5.0,  4.8, 0.20),
 (80,  5.6, 10.6,  3.4,  5.2, 0.12),
 (88,  2.4, 11.2,  1.5,  5.8, 0.05),
 (90,  0.25,11.6,  0.15, 6.0, 0.0),
]
def hull(m):
 verts=[]
 for x,b,dz,fh,cz,fl in STATIONS:
  # 从左舷顶 -> 左舷舭 -> 平底 -> 右舷舭 -> 右舷顶，共 9 点闭合
  verts += [
   (x, -(b+fl), dz),          # 0 左舷边(外飘)
   (x, -b*0.99, dz-0.30),     # 1 左舷侧上
   (x, -b, cz+1.9),           # 2 左舭折角(硬)
   (x, -fh, cz),              # 3 左平底外缘(硬折角)
   (x, 0.0, cz-0.25),         # 4 龙骨中心
   (x,  fh, cz),              # 5 右平底外缘
   (x,  b, cz+1.9),           # 6 右舭折角
   (x,  b*0.99, dz-0.30),     # 7 右舷侧上
   (x,  (b+fl), dz),          # 8 右舷边
  ]
 faces=[]
 for i in range(len(STATIONS)-1):
  for j in range(9):
   faces.append((i*9+j, i*9+(j+1)%9, (i+1)*9+(j+1)%9, (i+1)*9+j))
 faces += [tuple(range(8,-1,-1)), tuple((len(STATIONS)-1)*9+j for j in range(9))]
 o=mesh('HullDestroyer',verts,faces,m)   # 平面着色：保留折角
 sol=o.modifiers.new('Shell','SOLIDIFY');sol.thickness=.07
 return o
def deck(m,forecastle=False):
 """甲板面；forecastle=True 时生成艏部抬高的甲板台阶。"""
 S=[s for s in STATIONS if s[0]>=-90]
 if forecastle: S=[s for s in S if s[0]>=52]
 v=[]
 for x,b,dz,fh,cz,fl in S:
  z=dz+0.06+(1.15 if forecastle else 0)
  v += [(x,-(b+fl),z),(x,(b+fl),z)]
 f=[]
 for i in range(len(S)-1): f.append((2*i,2*i+1,2*i+3,2*i+2))
 return mesh('DeckForecastle' if forecastle else 'DeckMain',v,f,m)
def main():
 clear()
 hullm=mat('Hull',(0.20,.215,.225),.50,.12); deckm=mat('Deck',(.055,.065,.07),.70)
 blkm=mat('Stealth',(.032,.038,.045),.40,.1); glassm=mat('Glass',(.02,.09,.12),.16,.2)
 markm=mat('Mark',(.72,.05,.02),.4); seam=mat('Sea',(.006,.035,.055),.18)
 hull(hullm); deck(deckm); deck(deckm,forecastle=True)
 # 艏部甲板台阶立面 + 舷墙：明确读出军舰而非潜艇
 for i in range(len(STATIONS)-1):
  x0,d0=STATIONS[i][0],STATIONS[i][2]; x1,d1=STATIONS[i+1][0],STATIONS[i+1][2]
  b0=STATIONS[i][1]+STATIONS[i][5]; b1=STATIONS[i+1][1]+STATIONS[i+1][5]
  beam('ForecastleStep',(x0,-b0,d0+1.15),(x1,-b1,d1+1.15),.12,hullm)
  beam('ForecastleStepS',(x0,b0,d0+1.15),(x1,b1,d1+1.15),.12,hullm)
 # 舷弧线（sheer strake）：沿甲板边缘的连续可见线
 prev=None
 for x,b,dz,fh,cz,fl in STATIONS:
  y=b+fl
  if prev: beam('SheerStrake',(prev[0],-prev[1],prev[2]),(x,-y,dz),.10,blkm); beam('SheerStrakeS',(prev[0],prev[1],prev[2]),(x,y,dz),.10,blkm)
  prev=(x,y,dz)
 # 前部上层建筑：明显高于甲板的宽体块，立面带斜切
 tapered('ForwardIsland',-4,34,8.2,7.0,9.0,21.0,6.4,5.4,hullm)
 tapered('BridgeHouse',6,30,6.6,5.6,21.0,25.5,5.2,4.4,blkm)
 for z in (19.3,20.1): cube('BridgeWindow',(17,-7.45,z),(8.5,.05,.14),glassm,rot=(0,math.radians(-6),0),bev=.01)
 # 后部上层建筑 + 烟囱 + 长飞行甲板
 tapered('AftIsland',-36,-6,7.0,6.0,9.0,18.6,5.2,4.6,hullm)
 tapered('Funnel',-27,-15,4.0,3.6,18.6,24.5,2.9,2.5,blkm)
 cube('FlightDeck',(-67,0,9.45),(19,8.6,.14),deckm,bev=.03)
 beam('PadH1',(-78,-5.6,9.65),(-60,5.6,9.65),.13,markm);beam('PadH2',(-78,5.6,9.65),(-60,-5.6,9.65),.13,markm)
 # 综合桅杆：渐缩塔
 tapered('IntegratedMast',13,29,2.6,2.0,25.5,36,1.6,1.2,blkm)
 for z in (27,30,33):
  cube('AESA_Port',(21,-6.5,z),(4.0,.22,1.3),blkm,rot=(math.radians(-7),0,0));cube('AESA_Starboard',(21,6.5,z),(4.0,.22,1.3),blkm,rot=(math.radians(7),0,0))
 # 低矮贴甲板的设备
 for x0,rows in ((46,2),(-42,4)):
  for r in range(rows):
   for i in range(16): cube('VLS',(x0+(i-7.5)*1.1,-5.4+r*3.6,9.08),(.37,.37,.035),blkm,bev=.012)
 cyl('BowGunRing',(58,0,9.55),2.5,.28,blkm,32);tapered('BowGunTurret',55,61,2.1,1.7,9.7,12.4,1.3,1.0,blkm);beam('BowGunBarrel',(58,0,12.4),(72,0,13.1),.34,blkm)
 cyl('AftMount',(-38,0,9.7),1.4,.2,blkm,24)
 cube('Sea',(0,0,-.3),(110,36,.2),seam)
 w=bpy.data.worlds.new('W055V4');w.use_nodes=True;bg=next(n for n in w.node_tree.nodes if n.type=='BACKGROUND');bg.inputs['Color'].default_value=(.004,.009,.02,1);bg.inputs['Strength'].default_value=.30;bpy.context.scene.world=w
 for n,p,en,col in [('Key',(95,-125,80),6000,(1,.5,.3)),('Fill',(-85,95,55),3400,(.3,.5,1))]:
  ld=bpy.data.lights.new(n,'AREA');ld.energy=en;ld.color=col;ld.shape='DISK';ld.size=45;o=bpy.data.objects.new(n,ld);bpy.context.collection.objects.link(o);o.location=p;o.rotation_euler=(Vector((0,0,8))-o.location).to_track_quat('-Z','Y').to_euler()
 cd=bpy.data.cameras.new('C055V4');cam=bpy.data.objects.new('C055V4',cd);bpy.context.collection.objects.link(cam);bpy.context.scene.camera=cam;cd.lens=58
 sc=bpy.context.scene;sc.render.engine='BLENDER_EEVEE';sc.render.resolution_x=1400;sc.render.resolution_y=800;sc.render.resolution_percentage=100;sc.render.image_settings.file_format='PNG';sc.view_settings.view_transform='AgX';sc.view_settings.look='AgX - Medium High Contrast'
 views=[('type055_v4_hero',(150,-175,68),(0,0,8)),('type055_v4_side',(0,-215,30),(0,0,8)),('type055_v4_bow',(145,-100,36),(55,0,9)),('type055_v4_top',(40,-105,170),(0,0,6))]
 for n,p,t in views:cam.location=p;cam.rotation_euler=(Vector(t)-cam.location).to_track_quat('-Z','Y').to_euler();sc.render.filepath=os.path.join(OUT,n+'.png');bpy.ops.render.render(write_still=True)
 cam.location=views[0][1];cam.rotation_euler=(Vector(views[0][2])-cam.location).to_track_quat('-Z','Y').to_euler();bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT,'type055_destroyer_v4.blend'));print('TYPE055 V4 OK objects=%d'%sum(o.type=='MESH' for o in bpy.data.objects))
main()
