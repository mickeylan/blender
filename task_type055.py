"""055型万吨级驱逐舰公开外形概念模型。
非工程精确模型：仅依据公开影像表现外形、比例和主要可识别构件。
Blender 5.2/MCP safe：手动清场，不调用 read_factory_settings。
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
    if bev:b=o.modifiers.new('Edge','BEVEL'); b.width=bev;b.segments=2
    return o

def cyl(n,loc,r,d,m,verts=20,rot=(0,0,0)):
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts,radius=r,depth=d,location=loc,rotation=rot);o=active();o.name=n;o.data.materials.append(m);return o

def cone(n,loc,r1,r2,d,m,verts=20):
    bpy.ops.mesh.primitive_cone_add(vertices=verts,radius1=r1,radius2=r2,depth=d,location=loc);o=active();o.name=n;o.data.materials.append(m);return o

def beam(n,a,b,r,m):
    a=Vector(a);b=Vector(b);d=b-a;o=cyl(n,(a+b)/2,r,d.length,m,12);o.rotation_euler=d.to_track_quat('Z','Y').to_euler();return o

def main():
    clear(); steel=mat('055_Hull',(0.075,.095,.11),.48,.15); dark=mat('055_Deck',(.035,.045,.052),.62); black=mat('055_Stealth',(.018,.024,.03),.35,.1); glass=mat('055_Glass',(.015,.06,.085),.18,.25); red=mat('055_DeckMark',(.65,.04,.025),.45); white=mat('055_Number',(.7,.72,.68),.4); rotor=mat('055_Rotor',(.025,.03,.035),.35,.3)
    # hull: stacked tapered blocks create long stealth bow/stern silhouette
    cube('HullLower',(0,0,1.15),(8.2,1.55,.55),steel,bev=.18)
    cube('HullBelt',(0,0,1.75),(7.8,1.45,.32),steel,rot=(0,0,0),bev=.1)
    cube('UpperSheer',(0,0,2.22),(6.9,1.30,.22),steel,rot=(0,0,0),bev=.08)
    # raised angled bow shoulder and stern transom
    cube('BowShoulder',(6.9,0,2.45),(1.55,1.15,.22),steel,rot=(0,math.radians(-7),0),bev=.08)
    cube('SternDeck',(-6.3,0,2.48),(1.8,1.25,.18),dark,bev=.06)
    cube('MainDeck',(0,0,2.58),(7.5,1.38,.10),dark,bev=.04)
    # VLS grids front/rear: recognizable hatch rectangles
    for base,count in ((4.0,4),(-4.1,6)):
        for i in range(count):
            x=base + (i-(count-1)/2)*.58
            for y in (-.55,.55): cube('VLS_Hatch',(x,y,2.72),(.20,.20,.025),black,bev=.015)
    # forward gun
    cyl('MainGunBase',(5.55,0,3.0),.62,.18,black,32)
    cube('MainGunStealth',(5.55,0,3.42),(.5,.42,.55),black,rot=(0,math.radians(-12),0),bev=.06)
    beam('MainGunBarrel',(5.62,0,3.70),(7.15,0,3.84),.12,black)
    # aft CIWS-like mounts
    for x in (-5.0,-6.0):
        cyl('WeaponMount',(x,0,3.05),.38,.15,black,24); cube('WeaponHousing',(x,0,3.38),(.30,.27,.28),black,bev=.04)
    # integrated mast / forward superstructure
    cube('ForwardIsland',(1.35,0,4.0),(2.0,1.02,1.35),steel,rot=(0,0,0),bev=.08)
    cube('IslandSloped',(1.55,0,5.2),(1.65,.90,.32),black,rot=(0,math.radians(-8),0),bev=.05)
    # bridge windows bands
    for z in (4.45,4.72): cube('BridgeWindowBand',(1.05,-1.04,z),(1.3,.035,.08),glass,bev=.01)
    # aft integrated funnel/superstructure
    cube('AftIsland',(-2.5,0,4.0),(1.55,.92,1.05),steel,bev=.07)
    cube('Funnel',(-2.8,0,5.15),(.62,.55,.65),black,rot=(0,0,0),bev=.05)
    for y in (-.25,.25): cube('FunnelCap',(-2.8,y,5.82),(.48,.12,.08),black,bev=.02)
    # mast and sensor panels
    beam('IntegratedMast',(1.35,0,5.45),(1.35,0,8.0),.12,black)
    for z in (5.9,6.45,7.0):
        cube('AESA_Panel_F',(1.35,-.72,z),(.72,.08,.38),black,rot=(math.radians(-8),0,0),bev=.025)
        cube('AESA_Panel_B',(1.35,.72,z),(.72,.08,.38),black,rot=(math.radians(8),0,0),bev=.025)
    cyl('MastTop',(1.35,0,8.15),.24,.25,black,20)
    # antenna/radar dishes
    cyl('RadarHead',(1.35,0,7.55),.38,.12,black,24,rot=(math.pi/2,0,0)); beam('RadarArm',(1.35,0,7.5),(1.35,0,8.25),.045,black)
    # side boats / deck fittings
    for y in (-1.12,1.12): cube('BoatBay',(-1.0,y,2.85),(1.25,.18,.20),black,bev=.03)
    # helicopter deck and hangar
    cube('HelicopterDeck',(-5.0,0,2.78),(2.25,1.35,.10),dark,bev=.04)
    cube('Hangar',(-3.65,0,3.45),(1.25,1.0,.62),steel,bev=.06)
    # deck markings and helipad cross
    beam('HelipadMark',(-5.0,-.85,2.91),(-5.0,.85,2.91),.035,red); beam('HelipadMark',(-5.85,0,2.91),(-4.15,0,2.91),.035,red)
    # helicopter silhouette
    cyl('HeliBody',(-5.0,0,3.25),.28,.95,rotor,16,rot=(0,math.pi/2,0)); beam('HeliTail',(-5.3,0,3.25),(-6.25,0,3.32),.08,rotor); beam('HeliRotor',(-5.0,-.7,3.55),(-5.0,.7,3.55),.035,rotor)
    # hull number
    text=bpy.data.curves.new('HullNumber','FONT');text.body='055';text.align_x='CENTER';text.size=.65;text.extrude=.01;o=bpy.data.objects.new('HullNumber',text);bpy.context.collection.objects.link(o);o.location=(-.2,-1.58,1.75);o.rotation_euler=(math.pi/2,0,0);o.data.materials.append(white)
    # water plane
    water=mat('Sea',(0.008,.035,.06),.2,0);cube('Water',(0,0,-.05),(18,8,.05),water,bev=.01)
    # lights/world/camera
    w=bpy.data.worlds.new('055_World');w.use_nodes=True;bg=next(n for n in w.node_tree.nodes if n.type=='BACKGROUND');bg.inputs['Color'].default_value=(.004,.008,.018,1);bg.inputs['Strength'].default_value=.22;bpy.context.scene.world=w
    col=bpy.context.collection
    for name,loc,en,color,size in [('Key',(8,-12,12),1700,(1,.55,.32),6),('Fill',(-8,8,8),1100,(.25,.45,1),5)]:
        ld=bpy.data.lights.new(name,'AREA');ld.energy=en;ld.color=color;ld.shape='DISK';ld.size=size;ob=bpy.data.objects.new(name,ld);col.objects.link(ob);ob.location=loc;ob.rotation_euler=(Vector((0,0,2))-ob.location).to_track_quat('-Z','Y').to_euler()
    cd=bpy.data.cameras.new('Type055_Camera');cam=bpy.data.objects.new('Type055_Camera',cd);col.objects.link(cam);bpy.context.scene.camera=cam;cd.lens=52
    sc=bpy.context.scene;sc.render.engine='BLENDER_EEVEE';sc.render.resolution_x=1400;sc.render.resolution_y=800;sc.render.resolution_percentage=100;sc.render.image_settings.file_format='PNG';sc.view_settings.view_transform='AgX';sc.view_settings.look='AgX - Medium High Contrast'
    views=[('type055_hero',(14,-18,9),(0,0,2.0)),('type055_bow',(15,-8,5),(4,0,2.7)),('type055_side',(0,-19,5),(0,0,2.4)),('type055_top',(7,-10,18),(0,0,2.5))]
    for n,loc,tgt in views:
        cam.location=loc;cam.rotation_euler=(Vector(tgt)-cam.location).to_track_quat('-Z','Y').to_euler();sc.render.filepath=os.path.join(OUT,n+'.png');bpy.ops.render.render(write_still=True)
    cam.location=views[0][1];cam.rotation_euler=(Vector(views[0][2])-cam.location).to_track_quat('-Z','Y').to_euler();bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT,'type055_destroyer.blend'))
    print('TYPE055 BUILD OK objects=%d'%sum(o.type=='MESH' for o in bpy.data.objects))
try:main()
except Exception:
 import traceback;traceback.print_exc();raise
