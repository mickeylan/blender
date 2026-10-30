"""宗门巡游效果层：体积云雾、灵脉发光、飞舟运动、护山大阵旋转、人物点缀。

分层原则（blender-visual-craft）：效果必须可单独关闭，出问题时能定位到
具体图层，而不是整段重渲。所有效果对象放在独立集合 Effects 中。
"""
import bpy, os, math
from mathutils import Vector

BLEND=r"J:\mickeylan\ai\blender\out\xianmen_sect_tour.blend"
OUT=r"J:\mickeylan\ai\blender\out"

def active(): return bpy.context.view_layer.objects.active

def move(o,c):
    for q in list(o.users_collection): q.objects.unlink(o)
    c.objects.link(o)

def mat(name,col,rough=.6,metal=0,emit=0,alpha=1.0):
    m=bpy.data.materials.get(name) or bpy.data.materials.new(name); m.use_nodes=True
    n=next((n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED'),None)
    if n:
        n.inputs['Base Color'].default_value=(*col,1); n.inputs['Roughness'].default_value=rough
        if 'Metallic' in n.inputs:n.inputs['Metallic'].default_value=metal
        if emit:
            if 'Emission Color' in n.inputs:
                n.inputs['Emission Color'].default_value=(*col,1); n.inputs['Emission Strength'].default_value=emit
            if 'Alpha' in n.inputs: n.inputs['Alpha'].default_value=alpha
    if alpha<1.0:
        m.blend_method='BLEND' if hasattr(m,'blend_method') else m.blend_method
    return m

def volume_mat(name,color,density,noise_scale=0.06):
    """体积雾材质：Principled Volume + 噪声扰动。"""
    m=bpy.data.materials.get(name) or bpy.data.materials.new(name); m.use_nodes=True
    nt=m.node_tree; nt.nodes.clear()
    out=nt.nodes.new('ShaderNodeOutputMaterial')
    vol=nt.nodes.new('ShaderNodeVolumePrincipled')
    vol.inputs['Color'].default_value=(*color,1)
    vol.inputs['Density'].default_value=density
    tex=nt.nodes.new('ShaderNodeTexNoise'); tex.inputs['Scale'].default_value=noise_scale
    tex.inputs['Detail'].default_value=4.0
    ramp=nt.nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].position=0.35; ramp.color_ramp.elements[1].position=0.72
    nt.links.new(tex.outputs['Fac'],ramp.inputs['Fac'])
    nt.links.new(ramp.outputs['Color'],vol.inputs['Density'])
    nt.links.new(vol.outputs['Volume'],out.inputs['Volume'])
    return m

def main():
    bpy.ops.wm.open_mainfile(filepath=BLEND)
    sc=bpy.context.scene
    # ---- 独立效果集合 ----
    old=bpy.data.collections.get('SectEffects')
    if old:
        for o in list(old.objects): bpy.data.objects.remove(o,do_unlink=True)
        bpy.data.collections.remove(old)
    eff=bpy.data.collections.new('SectEffects'); sc.collection.children.link(eff)

    glowCyan=mat('FX_Cyan',(0.05,0.55,1.0),.2,0,6.0)
    glowPurple=mat('FX_Purple',(0.45,0.06,0.95),.2,0,6.0)
    glowGold=mat('FX_Gold',(0.75,0.45,0.08),.25,0,4.0)

    # ---- 1. 护山大阵：整体旋转 + 呼吸式明暗 ----
    rings=[o for o in bpy.data.objects if o.name.startswith('ArrayRing_')]
    rays=[o for o in bpy.data.objects if o.name.startswith('ArrayRay')]
    array_root=bpy.data.objects.new('ArrayRoot',None); eff.objects.link(array_root)
    array_root.empty_display_size=2.0
    for o in rings+rays:
        o.parent=array_root
    for f,ang in ((1,0.0),(360,math.radians(6)),(720,math.radians(14))):
        array_root.rotation_euler=(0,0,ang); array_root.keyframe_insert(data_path='rotation_euler',frame=f)

    # ---- 2. 灵脉：沿山脊的发光曲线 + 脉动 ----
    veins=[o for o in bpy.data.objects if o.name.startswith('SpiritVein')]
    for i,o in enumerate(veins):
        o.data.materials.clear(); o.data.materials.append(glowCyan if i%2==0 else glowPurple)

    # ---- 3. 体积云雾：山谷雾 + 高空云层 ----
    fog_low=volume_mat('FX_FogLow',(0.45,0.55,0.75),0.010,0.05)
    fog_high=volume_mat('FX_FogHigh',(0.55,0.62,0.85),0.004,0.03)
    bpy.ops.mesh.primitive_cube_add(location=(0,6,2.0),scale=(40,34,5.0))
    o=active(); o.name='FX_FogValley'; move(o,eff); o.data.materials.append(fog_low); o.display_type='WIRE'
    bpy.ops.mesh.primitive_cube_add(location=(0,10,26.0),scale=(46,40,9.0))
    o=active(); o.name='FX_FogHigh'; move(o,eff); o.data.materials.append(fog_high); o.display_type='WIRE'

    # ---- 4. 飞舟：沿曲线运动 + 帆面发光 ----
    def curve_from(points,name):
        cu=bpy.data.curves.new(name,'CURVE'); cu.dimensions='3D'
        sp=cu.splines.new('POLY'); sp.points.add(len(points)-1)
        for i,p in enumerate(points):
            sp.points[i].co=(p[0],p[1],p[2],1)
        ob=bpy.data.objects.new(name,cu); eff.objects.link(ob); return ob
    boats=[]
    for i,(pts,off) in enumerate([
            ([(-22,-14,7),(-14,-6,9),(-4,2,11),(6,10,14),(18,18,17)],0.0),
            ([(24,16,12),(16,10,9),(6,4,8),(-4,-2,9),(-14,-8,11)],0.0)]):
        cu=curve_from(pts,'FX_BoatPath_%d'%i)
        for k,nm in enumerate(('CloudBoatDeck','CloudBoatSail')):
            for ob in bpy.data.objects:
                if ob.name.startswith(nm) and ob.name==nm:
                    pass
        boats.append(cu)
    # 把三艘飞舟挂到第一条和第二条曲线上
    sail_objs=[o for o in bpy.data.objects if o.name.startswith('CloudBoat')]
    deck_objs=[o for o in bpy.data.objects if o.name.startswith('CloudBoatDeck')]
    sail_objs=[o for o in bpy.data.objects if o.name.startswith('CloudBoatSail')]
    for i,deck in enumerate(deck_objs):
        path=boats[i%len(boats)]
        deck.parent=path
        deck.matrix_parent_inverse=path.matrix_world.inverted()
        deck.location=(0,0,0)
        deck.keyframe_insert(data_path='location',frame=1)
        deck.location=(0,0,0)
    for i,sail in enumerate(sail_objs):
        path=boats[i%len(boats)]
        sail.parent=path
        sail.matrix_parent_inverse=path.matrix_world.inverted()
        sail.location=(0,0,0)
        sail.data.materials.clear(); sail.data.materials.append(glowPurple if i%2 else glowCyan)

    # ---- 5. 人物点缀：弟子剪影，沿中轴线站位 ----
    fig=mat('FX_Figure',(0.05,0.05,0.07),.9)
    people=[(-1.4,-6),(1.4,-4.5),(-0.9,-3.0),(1.1,-1.5),(-1.6,1.0),(1.5,2.2),(-1.0,3.5),(0.9,4.8)]
    for i,(x,y) in enumerate(people):
        bpy.ops.mesh.primitive_cube_add(location=(x,y,0.85),scale=(0.13,0.13,0.85))
        o=active(); o.name='FX_Disciple_%02d'%i; move(o,eff); o.data.materials.append(fig)
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2,radius=1,location=(x,y,1.82))
        h=active(); h.name='FX_DiscipleHead_%02d'%i; move(h,eff); h.scale=(0.13,0.13,0.15); h.data.materials.append(fig)

    # ---- 6. 场景设置：EEVEE 体积与雾 ----
    sc.render.engine='BLENDER_EEVEE'
    sc.frame_start=1; sc.frame_end=720; sc.render.fps=24
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT,'xianmen_sect_tour.blend'))
    print('SECT EFFECTS OK effects=%d'%len(eff.objects))
main()
