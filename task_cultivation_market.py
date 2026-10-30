"""Procedural Chinese xianxia cultivation-market scene.

Design contract: cultivation_market_brief.md
Blender 5.2/MCP safe: manual cleanup only; no read_factory_settings.
"""
import bpy, math, os
from mathutils import Vector

OUT=r"J:\mickeylan\ai\blender\out"
COLL="CultivationMarket"

def clear():
    for o in list(bpy.data.objects): bpy.data.objects.remove(o, do_unlink=True)
    for c in list(bpy.data.collections):
        try: bpy.data.collections.remove(c)
        except: pass
    for db in (bpy.data.meshes,bpy.data.materials,bpy.data.curves,bpy.data.cameras,bpy.data.lights):
        for x in list(db):
            if x.users==0:
                try: db.remove(x)
                except: pass

def collection():
    c=bpy.data.collections.new(COLL); bpy.context.scene.collection.children.link(c); return c

def material(name,color,rough=.55,metal=0):
    m=bpy.data.materials.new(name); m.diffuse_color=(*color,1); m.use_nodes=True
    n=next((n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED'),None)
    if n:
        n.inputs['Base Color'].default_value=(*color,1); n.inputs['Roughness'].default_value=rough
        if 'Metallic' in n.inputs:n.inputs['Metallic'].default_value=metal
    return m

def move_coll(o,c):
    for q in list(o.users_collection): q.objects.unlink(o)
    c.objects.link(o)

def cube(name,loc,scale,mat,c,rot=(0,0,0),bevel=0.0):
    bpy.ops.mesh.primitive_cube_add(location=loc,rotation=rot); o=bpy.context.object; o.name=name; o.scale=scale; move_coll(o,c); o.data.materials.append(mat)
    if bevel:
        mod=o.modifiers.new('Soft_Edge','BEVEL'); mod.width=bevel; mod.segments=2
    return o

def cyl(name,loc,r,depth,mat,c,verts=16,rot=(0,0,0)):
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts,radius=r,depth=depth,location=loc,rotation=rot); o=bpy.context.object; o.name=name; move_coll(o,c); o.data.materials.append(mat); return o

def cone(name,loc,r1,r2,depth,mat,c):
    bpy.ops.mesh.primitive_cone_add(vertices=16,radius1=r1,radius2=r2,depth=depth,location=loc); o=bpy.context.object; o.name=name; move_coll(o,c); o.data.materials.append(mat); return o

def sphere(name,loc,scale,mat,c):
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2,radius=1,location=loc); o=bpy.context.object; o.name=name; o.scale=scale; move_coll(o,c); o.data.materials.append(mat); return o

def beam(name,a,b,r,mat,c):
    a=Vector(a); b=Vector(b); d=b-a; mid=(a+b)/2
    o=cyl(name,mid,r,d.length,mat,c,12); o.rotation_euler=d.to_track_quat('Z','Y').to_euler(); return o

def text(name,body,loc,scale,mat,c,rot=(math.pi/2,0,0)):
    cu=bpy.data.curves.new(name,'FONT'); cu.body=body; cu.align_x='CENTER'; cu.size=scale; cu.extrude=.012
    o=bpy.data.objects.new(name,cu); c.objects.link(o); o.location=loc; o.rotation_euler=rot; o.data.materials.append(mat); return o

def lantern(c,loc,metal,glow):
    cyl('LanternFrame',loc,.16,.42,metal,c,12); sphere('LanternGlow',(loc[0],loc[1],loc[2]+.02),(.105,.105,.16),glow,c)
    for z in (-.24,.24): beam('LanternBar',(loc[0]-.18,loc[1],loc[2]+z),(loc[0]+.18,loc[1],loc[2]+z),.018,metal,c)

def shop(c,x,y,label,wood,roof,accent):
    cube('ShopBase',(x,y,.65),(1.8,1.15,.65),wood,c,bevel=.08)
    for sx in (-1.55,1.55):
        for z in (1.3,2.7): cube('ShopPost',(x+sx,y,.0+z),( .12,.12,1.4),wood,c)
    cube('ShopUpper',(x,y,2.2),(1.75,1.1,.7),wood,c,bevel=.05)
    # upturned roof
    cube('RoofA',(x,y-.58,3.05),(2.05,.72,.12),roof,c,rot=(math.radians(-8),0,0),bevel=.04)
    cube('RoofB',(x,y+.58,3.05),(2.05,.72,.12),roof,c,rot=(math.radians(8),0,0),bevel=.04)
    text('ShopSign',label,(x,y-1.18,2.25),.35,accent,c,rot=(math.pi/2,0,0))
    lantern(c,(x-1.55,y-1.05,2.1),accent,accent)

def main():
    clear(); c=collection()
    stone=material('Stone',(0.16,.19,.22),.9); dark=material('DarkWood',(.075,.035,.02),.72)
    wood=material('VermilionWood',(.26,.055,.025),.48); roof=material('TileBlue',(.035,.08,.12),.62)
    gold=material('Brass',(.55,.22,.045),.3,.55); jade=material('Jade',(.04,.35,.28),.22,.15)
    red=material('Cinnabar',(.55,.025,.018),.38); paper=material('Talisman',(.72,.47,.14),.7)
    glow=material('SpiritGlow',(.18,.48,.9),.18); purple=material('ArrayGlow',(.4,.08,.8),.2)
    # ground and S-shaped main street platforms
    cube('Ground',(0,0,-.18),(18,16,.18),stone,c)
    cube('StreetA',(0,-5,.02),(3.2,6,.08),stone,c,bevel=.08)
    cube('StreetB',(0,3,.02),(3.8,5,.08),stone,c,bevel=.08)
    cube('CentralSquare',(0,-.5,.04),(5.0,3.6,.1),stone,c,bevel=.1)
    # entrance gate
    for x in (-3.8,3.8): cube('GatePillar',(x,-10,2.2),(.42,.5,2.2),stone,c,bevel=.1); cone('GateCap',(x,-10,4.65),.65,.35,.45,gold,c)
    beam('GateBeam',(-4.4,-10,4.3),(4.4,-10,4.3),.38,wood,c)
    beam('GateBeam2',(-4.0,-10,4.75),(4.0,-10,4.75),.2,gold,c)
    text('GateTitle','万象坊',(0,-10.48,4.38),.65,paper,c)
    # guardian beasts
    for x in (-2.7,2.7): sphere('StoneGuardian',(x,-9.4,.45),(.65,.75,.5),stone,c); cone('GuardianHorn',(x,-9.4,1.05),.2,.02,.45,stone,c)
    # shops
    shop(c,-5,-1,'丹阁',wood,roof,red); shop(c,5,-1,'器阁',wood,roof,gold); shop(c,-5,5,'符坊',wood,roof,paper); shop(c,5,5,'灵茶',wood,roof,jade)
    # central spirit spring
    cyl('SpiritPool',(0,-.2,.18),2.0,.18,stone,c,32); cyl('SpiritWater',(0,-.2,.29),1.65,.06,glow,c,32)
    for i in range(8):
        a=i*math.tau/8; beam('JadeRail',(1.9*math.cos(a),-.2+1.9*math.sin(a),.45),(2.0*math.cos(a),-.2+2.0*math.sin(a),.45),.06,jade,c)
    sphere('SpiritCore',(0,-.2,.65),(.35,.35,.55),purple,c)
    # stalls and props
    for i,x in enumerate((-2.5,-1.0,1.0,2.5)):
        cube('StallTable',(x,-4.0,.65),(.65,.45,.08),wood,c); beam('StallPole',(x-.55,-4, .7),(x-.55,-4,2.1),.06,wood,c); beam('StallPole',(x+.55,-4,.7),(x+.55,-4,2.1),.06,wood,c); cube('StallCloth',(x,-4,2.08),(.7,.5,.04),paper if i%2 else red,c)
    for x in (-5,5):
        cyl('Tripod', (x,-3.2,.8),.45,.08,gold,c); cone('Pill', (x,-3.2,1.25),.22,.14,.8,glow if x<0 else purple,c); sphere('SpiritLantern',(x,-3.2,1.75),(.22,.22,.28),glow if x<0 else purple,c)
    # distant elevated hall
    cube('HallPlatform',(0,10,2.5),(5,2,.25),stone,c); cube('MainHall',(0,10,4.5),(3.6,1.5,2),wood,c,bevel=.08)
    for x in (-3,3): cube('HallColumn',(x,9.0,4.5),(.22,.22,2.3),gold,c)
    cube('HallRoofA',(0,9.25,6.8),(4.3,1.1,.18),roof,c,rot=(math.radians(-7),0,0)); cube('HallRoofB',(0,10.75,6.8),(4.3,1.1,.18),roof,c,rot=(math.radians(7),0,0)); text('HallSign','天机殿',(0,8.45,4.8),.5,gold,c)
    # suspended bridge
    for x in (-3.2,3.2): beam('BridgeCable',(x,6,4.8),(x,10,3.2),.08,gold,c)
    for y in [6+i*.5 for i in range(9)]: cube('BridgePlank',(0,y,3.4+(y-6)*-.05),(3.3,.18,.1),wood,c)
    # floating talisman array and lamps
    for i in range(12):
        a=i*math.tau/12; loc=(7*math.cos(a),1+3*math.sin(a),6.5+.35*math.sin(2*a)); lantern(c,loc,gold,glow if i%2 else purple)
    for i in range(7):
        x=-3+i; lantern(c,(x,-7.2,3.5+.25*math.sin(i)),gold,glow)
    # mountains/clouds background
    for i in range(9):
        x=-16+i*4; cone('Mountain',(x,14,3.2+(i%3)),3.5,0,7+2*(i%2),dark,c)
    for i in range(10): sphere('Cloud',( -12+i*2.7,8+0.5*(i%3),1.5+(i%2)*.5),(1.8,.8,.35),glow if i%3==0 else stone,c)
    # world/lights
    w=bpy.data.worlds.new('MarketWorld'); w.use_nodes=True; bg=next(n for n in w.node_tree.nodes if n.type=='BACKGROUND'); bg.inputs['Color'].default_value=(.004,.008,.02,1); bg.inputs['Strength'].default_value=.18; bpy.context.scene.world=w
    for name,loc,energy,color,size in [('Warm',(-6,-8,8),1800,(1,.3,.12),5),('Cool',(5,1,7),1200,(.15,.35,1),4),('Purple',(0,5,8),1000,(.5,.08,1),3)]:
        ld=bpy.data.lights.new(name,'AREA'); ld.energy=energy; ld.color=color; ld.shape='DISK'; ld.size=size; o=bpy.data.objects.new(name,ld); c.objects.link(o); o.location=loc; o.rotation_euler=(Vector((0,0,1.5))-o.location).to_track_quat('-Z','Y').to_euler()
    # camera
    cd=bpy.data.cameras.new('MarketCam'); cam=bpy.data.objects.new('MarketCam',cd); c.objects.link(cam); bpy.context.scene.camera=cam; cd.lens=42
    target=Vector((0,0,2.2)); cam.location=Vector((14,-18,11)); cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler()
    sc=bpy.context.scene; sc.render.engine='BLENDER_EEVEE'; sc.render.resolution_x=1200; sc.render.resolution_y=900; sc.render.resolution_percentage=100; sc.render.image_settings.file_format='PNG'; sc.render.filepath=os.path.join(OUT,'market_hero.png'); sc.view_settings.view_transform='AgX'; sc.view_settings.look='AgX - Medium High Contrast'; bpy.ops.render.render(write_still=True)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT,'cultivation_market.blend'))
    print('MARKET BUILD OK objects=%d' % len([o for o in bpy.data.objects if o.type=='MESH']))

try: main()
except Exception:
 import traceback; traceback.print_exc(); raise
