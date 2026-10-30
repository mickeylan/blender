"""055 外形 v3：连续舰体与上层建筑整体比例修正版。
公开外形级概念模型，不是工程图纸。先验证船体，再谈设备细节。
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
def mat(n,c,r=.55,metal=0):
 m=bpy.data.materials.new(n);m.diffuse_color=(*c,1);m.use_nodes=True;n2=next((x for x in m.node_tree.nodes if x.type=='BSDF_PRINCIPLED'),None)
 if n2:
  n2.inputs['Base Color'].default_value=(*c,1);n2.inputs['Roughness'].default_value=r
  if 'Metallic' in n2.inputs:n2.inputs['Metallic'].default_value=metal
 return m
def cube(n,p,s,m,rot=(0,0,0),bev=.03):
 bpy.ops.mesh.primitive_cube_add(location=p,rotation=rot);o=active();o.name=n;o.scale=s;o.data.materials.append(m)
 if bev:b=o.modifiers.new('Edge','BEVEL');b.width=bev;b.segments=2
 return o
def cyl(n,p,r,d,m,v=20,rot=(0,0,0)):
 bpy.ops.mesh.primitive_cylinder_add(vertices=v,radius=r,depth=d,location=p,rotation=rot);o=active();o.name=n;o.data.materials.append(m);return o
def beam(n,a,b,r,m):
 a=Vector(a);b=Vector(b);d=b-a;o=cyl(n,(a+b)/2,r,d.length,m,12);o.rotation_euler=d.to_track_quat('Z','Y').to_euler();return o
def mesh(n,v,f,m):
 me=bpy.data.meshes.new(n+'Mesh');me.from_pydata(v,[],f);me.materials.append(m);o=bpy.data.objects.new(n,me);bpy.context.collection.objects.link(o)
 for p in me.polygons:p.use_smooth=True
 return o
def hull(m):
 # stern -> bow; deck sheer rises at both ends, maximum beam at midship
 S=[(-90,7.0,7.1),(-84,8.8,7.2),(-68,10.0,7.45),(-42,10.9,7.75),(-10,11.15,7.95),(25,11.0,8.15),(52,10.2,8.45),(70,8.6,8.9),(82,5.8,9.65),(89,2.1,10.7),(90,.15,11.8)]
 # cross-section: deck edge, upper side, chine, bottom, other side
 verts=[]
 for x,b,z in S:
  verts += [(x,-b,z),(x,-b*.98,z-.34),(x,-b*.78,4.2),(x,-b*.40,.85),(x,0,.42),(x,b*.40,.85),(x,b*.78,4.2),(x,b*.98,z-.34),(x,b,z)]
 faces=[]
 for i in range(len(S)-1):
  for j in range(9):faces.append((i*9+j,i*9+(j+1)%9,(i+1)*9+(j+1)%9,(i+1)*9+j))
 faces += [tuple(range(8,-1,-1)),tuple((len(S)-1)*9+j for j in range(9))]
 o=mesh('HullContinuousV3',verts,faces,m)
 # weighted normal/solidify for readable shell
 sol=o.modifiers.new('HullThickness','SOLIDIFY');sol.thickness=.08
 bev=o.modifiers.new('HullSoftChines','BEVEL');bev.width=.12;bev.segments=2
 return o
def deck_mesh(m):
 S=[(-90,7.0,7.15),(-68,10.0,7.5),(-10,11.15,8.0),(25,11.0,8.2),(52,10.2,8.5),(70,8.6,8.95),(82,5.8,9.7),(89,2.1,10.75)]
 v=[]
 for x,b,z in S:v += [(x,-b,z+.05),(x,b,z+.05)]
 f=[]
 for i in range(len(S)-1):f.append((2*i,2*i+1,2*i+3,2*i+2))
 return mesh('ContinuousFlightDeckV3',v,f,m)
def tapered(n,x0,x1,b0,b1,z0,zt,t0,t1,m):
 v=[(x0,-b0,z0),(x0,b0,z0),(x1,b1,z0),(x1,-b1,z0),(x0,-t0,zt),(x0,t0,zt),(x1,t1,zt),(x1,-t1,zt)]
 f=[(0,1,2,3),(4,7,6,5),(0,4,5,1),(1,5,6,2),(2,6,7,3),(3,7,4,0)]
 return mesh(n,v,f,m)
def main():
 clear();hullmat=mat('HullGrey',(.19,.21,.22),.48,.12);deck=mat('DeckGrey',(.065,.075,.08),.66);black=mat('StealthGrey',(.035,.042,.048),.38,.1);glass=mat('Glass',(.02,.09,.12),.16,.2);mark=mat('Mark',(.7,.04,.02),.4);sea=mat('Sea',(.008,.04,.065),.18)
 hull(hullmat);deck_mesh(deck)
 # bow bulwark and sharp spray rail: emphasizes real pointed bow
 beam('BowBulwark',(73,-7.0,9.0),(89,-1.0,11.25),.16,hullmat);beam('BowBulwark',(73,7.0,9.0),(89,1.0,11.25),.16,hullmat)
 # broad low forward island, not a tall box
 tapered('ForwardIsland',-2,35,8.0,7.2,8.3,20.0,6.6,5.7,hullmat)
 tapered('BridgeHouse',8,31,6.6,5.8,20.0,24.0,5.4,4.8,black)
 for z in (18.55,19.25):cube('BridgeWindow',(18,-7.5,z),(9,.045,.13),glass,rot=(0,math.radians(-5),0),bev=.01)
 # aft island/hangar integrated into stern, flight deck long and unmistakable
 tapered('AftSuperstructure',-34,-5,7.0,6.2,8.3,17.8,5.4,4.8,hullmat)
 tapered('Funnel',-25,-14,4.2,3.7,17.8,24.0,3.0,2.6,black)
 cube('FlightDeck',(-66,0,8.55),(18,8.5,.12),deck,bev=.03)
 beam('HelipadH1',(-76,-5.5,8.75),(-60,5.5,8.75),.12,mark);beam('HelipadH2',(-76,5.5,8.75),(-60,-5.5,8.75),.12,mark)
 # mast as tapered integrated tower
 tapered('IntegratedMast',14,28,2.5,2.0,24,35,1.7,1.35,black)
 for z in (26,29,32):
  cube('AESA_Port',(21,-6.6,z),(4.2,.20,1.35),black,rot=(math.radians(-7),0,0));cube('AESA_Starboard',(21,6.6,z),(4.2,.20,1.35),black,rot=(math.radians(7),0,0))
 # flush VLS fields, one forward and one around aft island
 for x0,rows in ((48,2),(-43,4)):
  for row in range(rows):
   for i in range(16):cube('VLS',(x0+(i-7.5)*1.15,-5.6+row*3.7,8.38),(.39,.39,.035),black,bev=.015)
 # low stealth gun and aft mount
 cyl('BowGunRing',(58,0,9.0),2.6,.3,black,32);tapered('BowGunTurret',55,61,2.2,1.8,9.15,12.0,1.4,1.1,black);beam('BowGunBarrel',(58,0,12),(73,0,12.7),.36,black)
 cyl('AftMount',(-39,0,9.1),1.5,.22,black,24)
 cube('Water',(0,0,-.3),(110,35,.2),sea)
 w=bpy.data.worlds.new('055V3World');w.use_nodes=True;bg=next(n for n in w.node_tree.nodes if n.type=='BACKGROUND');bg.inputs['Color'].default_value=(.004,.009,.02,1);bg.inputs['Strength'].default_value=.28;bpy.context.scene.world=w
 for n,p,en,col in [('Key',(90,-130,90),5200,(1,.5,.3)),('Fill',(-80,100,60),3200,(.3,.5,1))]:
  ld=bpy.data.lights.new(n,'AREA');ld.energy=en;ld.color=col;ld.shape='DISK';ld.size=45;o=bpy.data.objects.new(n,ld);bpy.context.collection.objects.link(o);o.location=p;o.rotation_euler=(Vector((0,0,6))-o.location).to_track_quat('-Z','Y').to_euler()
 cd=bpy.data.cameras.new('Camera055V3');cam=bpy.data.objects.new('Camera055V3',cd);bpy.context.collection.objects.link(cam);bpy.context.scene.camera=cam;cd.lens=58
 sc=bpy.context.scene;sc.render.engine='BLENDER_EEVEE';sc.render.resolution_x=1400;sc.render.resolution_y=800;sc.render.resolution_percentage=100;sc.render.image_settings.file_format='PNG';sc.view_settings.view_transform='AgX';sc.view_settings.look='AgX - Medium High Contrast'
 views=[('type055_v3_hero',(150,-180,70),(0,0,7)),('type055_v3_side',(0,-220,32),(0,0,7)),('type055_v3_bow',(150,-105,38),(55,0,8)),('type055_v3_top',(45,-110,175),(0,0,5))]
 for n,p,t in views:cam.location=p;cam.rotation_euler=(Vector(t)-cam.location).to_track_quat('-Z','Y').to_euler();sc.render.filepath=os.path.join(OUT,n+'.png');bpy.ops.render.render(write_still=True)
 cam.location=views[0][1];cam.rotation_euler=(Vector(views[0][2])-cam.location).to_track_quat('-Z','Y').to_euler();bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT,'type055_destroyer_v3.blend'));print('TYPE055 V3 OK objects=%d'%sum(o.type=='MESH' for o in bpy.data.objects))
main()
