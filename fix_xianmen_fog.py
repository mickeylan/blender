"""修正体积雾：巨型立方体覆盖整座宗门，改为局部雾团。

第一版雾把 fx_alchemy 对比度压到 9.7、fx_departure 压到 7.3，主体不可读。
本脚本删除巨型雾体，改为：
  - 山谷雾：贴山脚外围的小雾团（不进中轴街市）
  - 高空云：z=20 附近的薄层，只做云海起伏，不遮主峰
  - 山门雾：单独一团体现在山门附近，作为层次
"""
import bpy, os, math
from mathutils import Vector

BLEND=r"J:\mickeylan\ai\blender\out\xianmen_sect_tour.blend"
OUT=r"J:\mickeylan\ai\blender\out"

def active(): return bpy.context.view_layer.objects.active

def move(o,c):
    for q in list(o.users_collection): q.objects.unlink(o)
    c.objects.link(o)

def volume_mat(name,color,density,noise_scale,lo,hi):
    m=bpy.data.materials.get(name) or bpy.data.materials.new(name); m.use_nodes=True
    nt=m.node_tree; nt.nodes.clear()
    out=nt.nodes.new('ShaderNodeOutputMaterial')
    vol=nt.nodes.new('ShaderNodeVolumePrincipled')
    vol.inputs['Color'].default_value=(*color,1)
    vol.inputs['Density'].default_value=density
    tex=nt.nodes.new('ShaderNodeTexNoise'); tex.inputs['Scale'].default_value=noise_scale; tex.inputs['Detail'].default_value=3.0
    ramp=nt.nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].position=lo; ramp.color_ramp.elements[1].position=hi
    nt.links.new(tex.outputs['Fac'],ramp.inputs['Fac'])
    nt.links.new(ramp.outputs['Color'],vol.inputs['Density'])
    nt.links.new(vol.outputs['Volume'],out.inputs['Volume'])
    return m

def main():
    bpy.ops.wm.open_mainfile(filepath=BLEND); sc=bpy.context.scene
    eff=bpy.data.collections.get('SectEffects')
    # 1) 删除巨型雾体
    for n in ('FX_FogValley','FX_FogHigh'):
        o=bpy.data.objects.get(n)
        if o: bpy.data.objects.remove(o,do_unlink=True)
    # 2) 局部雾团材质
    m_valley=volume_mat('FX_FogValley',(0.45,0.55,0.75),0.030,0.09,0.40,0.78)
    m_high=volume_mat('FX_FogHigh',(0.55,0.63,0.88),0.006,0.05,0.45,0.80)
    m_gate=volume_mat('FX_FogGate',(0.60,0.66,0.85),0.022,0.12,0.42,0.80)
    def puff(name,loc,scale,mat):
        bpy.ops.mesh.primitive_cube_add(location=loc,scale=scale)
        o=active(); o.name=name; move(o,eff); o.data.materials.append(mat); o.display_type='WIRE'; return o
    # 3) 山谷雾：沿九峰外围脚下的环带，不进中轴
    ring=[(-26,10),(26,9),(-20,22),(20,22),(-14,28),(14,28),(-24,-4),(24,-4)]
    for i,(x,y) in enumerate(ring):
        puff('FX_ValleyFog_%02d'%i,(x,y,1.4),(6.5,5.5,1.5),m_valley)
    # 4) 山门雾：一团，位于山门外侧
    puff('FX_GateFog',(0,-22,1.6),(7.0,4.0,1.6),m_gate)
    # 5) 高空云海：z=20 的薄层，只做起伏
    for i in range(14):
        a=i*math.tau/14
        puff('FX_HighCloud_%02d'%i,(26*math.cos(a),8+18*math.sin(a),19.5+1.2*math.sin(i*2.1)),(7.0,5.0,1.1),m_high)
    # 6) 主峰顶部的薄云，强化主峰在云海之上的高度感
    puff('FX_MainPeakMist',(0,10,16.5),(5.0,4.0,1.0),m_high)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT,'xianmen_sect_tour.blend'))
    print('FOG REDONE objs=%d'%len(eff.objects))
main()
