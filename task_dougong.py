"""【由 AI 驱动的建模任务】搭一个中国古建筑风格的木构斗拱（dougong）支架。

这是 dream-loop 循环里"实现"步骤的产物：AI 直接写 Blender Python。
要求：
  - 只用 bpy + mathutils，不依赖任何外部资产
  - 斗拱由若干层方木叠涩而成：坐斗、栌斗、华栱、泥道拱、散斗、昂、耍头
  - 比例参照《营造法式》感觉：宽 3 个斗口，高 4 个斗口
  - 每根方木用独立 mesh，命名清晰，便于后续 AI 修改单个构件
  - 加一个相机 + 灯光，最后存 blend
"""

import math
import os

import bpy
from mathutils import Vector

# ---------- 清场（不能用 bpy.ops.wm.read_factory_settings！）----------
# 陷阱：read_factory_settings 会重置整个 Blender，连带把 MCP 插件的 socket
# 服务一起干掉 —— 进程还活着，但 9876 端口不再监听，后续所有命令都收不到回包。
# 正确做法：手动删对象/集合，保留插件与 UI 状态。
for ob in list(bpy.data.objects):
    bpy.data.objects.remove(ob, do_unlink=True)
for c in list(bpy.data.collections):
    bpy.data.collections.remove(c)
for blk in (bpy.data.meshes, bpy.data.materials, bpy.data.cameras, bpy.data.lights):
    for d in list(blk):
        if d.users == 0:
            blk.remove(d)

scene = bpy.context.scene
scene.unit_settings.system = 'METRIC'

COLL_NAME = "Dougong"
if COLL_NAME in bpy.data.collections:
    coll = bpy.data.collections[COLL_NAME]
    bpy.data.collections.remove(coll)
coll = bpy.data.collections.new(COLL_NAME)
scene.collection.children.link(coll)

# ---------- 斗口单位 ----------
KOU = 0.10          # 1 斗口 = 10cm
W = 3 * KOU         # 宽 3 斗口
H = 4 * KOU         # 高 4 斗口


def add_box(name, size, location, rotation=(0, 0, 0), material=None):
    """建一根方木（中心在 location，尺寸 size=(x,y,z)）。"""
    me = bpy.data.meshes.new(name)
    verts = [(sx * size[0] / 2, sy * size[1] / 2, sz * size[2] / 2)
             for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1),
             (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    me.from_pydata(verts, [], faces)
    me.update()
    ob = bpy.data.objects.new(name, me)
    ob.location = location
    ob.rotation_euler = rotation
    coll.objects.link(ob)
    if material:
        ob.data.materials.append(material)
    return ob


def make_material(name, rgb, roughness=0.6):
    """按 type 取 Principled BSDF，不按名字取（5.2 里名字变了，见 LESSONS.md [006]）。"""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if bsdf is None:
        raise RuntimeError(f"{name}: 找不到 Principled BSDF 节点，"
                           f"实际节点={[ (n.name, n.type) for n in mat.node_tree.nodes ]}")
    bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    return mat


wood = make_material("Wood_Dougong", (0.42, 0.24, 0.13), 0.65)
wood_dark = make_material("Wood_Dougong_Dark", (0.28, 0.15, 0.08), 0.7)

# ---------- 构件 ----------
# 1) 栌斗（最下的大斗）：底面 3x3 斗口，上有凹口
dougong = []
dougong.append(add_box("Dou_Lutou", (W, W, 1.0 * KOU), (0, 0, 0.5 * KOU), material=wood_dark))

# 2) 坐斗（一排小斗，每个 1 斗口），骑在华栱上
z_dou = 1.0 * KOU
for i, x in enumerate((-1.0 * KOU, 0.0, 1.0 * KOU)):
    dougong.append(add_box(f"Dou_Zuo_{i}", (1.0 * KOU, 1.0 * KOU, 0.8 * KOU),
                           (x, 0, z_dou + 0.4 * KOU), material=wood_dark))

# 3) 华栱（前后出跳的栱）：沿 Y 方向伸出，层层叠涩
z_hua = z_dou + 0.8 * KOU
for i in range(2):
    z = z_hua + i * 0.8 * KOU
    dougong.append(add_box(f"HuaGong_{i}", (1.0 * KOU, W, 0.8 * KOU),
                           (0, 0, z + 0.4 * KOU), material=wood))

# 4) 泥道拱（横向的栱）：沿 X 方向
z_ni = z_hua + 1.6 * KOU
dougong.append(add_box("NiDaoGong", (W, 1.0 * KOU, 0.8 * KOU),
                       (0, 0, z_ni + 0.4 * KOU), material=wood))

# 5) 散斗（小斗，压在栱头之上）
for i, x in enumerate((-1.5 * KOU, 1.5 * KOU)):
    dougong.append(add_box(f"Dou_San_{i}", (0.8 * KOU, 0.8 * KOU, 0.7 * KOU),
                           (x, 0, z_ni + 0.8 * KOU + 0.35 * KOU), material=wood_dark))

# 6) 昂（斜出的尖木，翘出）
z_ang = z_ni + 0.8 * KOU
ang_len = 2.2 * KOU
ang = add_box("Ang", (0.7 * KOU, 0.7 * KOU, ang_len),
              (0, 0, z_ang + 0.5 * KOU),
              rotation=(math.radians(-18), 0, 0), material=wood)
dougong.append(ang)

# 7) 耍头（横向伸出的装饰木）
z_shua = z_ang + 1.4 * KOU
dougong.append(add_box("ShuaTou", (2.6 * KOU, 0.6 * KOU, 0.6 * KOU),
                       (0, 0.3 * KOU, z_shua), material=wood))

# 8) 替木（纵向压顶木）
dougong.append(add_box("TiMu", (0.7 * KOU, 2.4 * KOU, 0.6 * KOU),
                       (0, 0, z_shua + 0.6 * KOU), material=wood))

# 9) 令栱（最上层小栱）
dougong.append(add_box("LingGong", (2.0 * KOU, 0.6 * KOU, 0.5 * KOU),
                       (0, 0, z_shua + 1.1 * KOU), material=wood))

# ---------- 相机 ----------
cam_data = bpy.data.cameras.new("Camera")
cam_data.lens = 50.0
cam = bpy.data.objects.new("Camera", cam_data)
scene.collection.objects.link(cam)
target = Vector((0, 0, H * 0.5))
cam.location = target + Vector((0.85, -1.15, 0.75))
direction = target - cam.location
cam.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
scene.camera = cam

# ---------- 灯光 ----------
sun_data = bpy.data.lights.new("Sun_Key", type='SUN')
sun_data.energy = 4.0
sun_data.angle = math.radians(3)
sun = bpy.data.objects.new("Sun_Key", sun_data)
sun.rotation_euler = (math.radians(50), math.radians(10), math.radians(35))
scene.collection.objects.link(sun)

fill_data = bpy.data.lights.new("Area_Fill", type='AREA')
fill_data.energy = 60.0
fill_data.size = 2.0
fill = bpy.data.objects.new("Area_Fill", fill_data)
fill.location = (-1.5, -1.5, 1.5)
fill.rotation_euler = (math.radians(60), 0, math.radians(-40))
scene.collection.objects.link(fill)

# ---------- 渲染设置 ----------
scene.render.engine = 'BLENDER_EEVEE'
scene.render.resolution_x = 1200
scene.render.resolution_y = 900
scene.render.resolution_percentage = 100
scene.render.film_transparent = False
scene.view_settings.view_transform = 'Standard'

# 世界环境光（同样按 type 取，不用名字，见 LESSONS.md [006]）
world = bpy.data.worlds.new("World")
world.use_nodes = True
bg = next((n for n in world.node_tree.nodes if n.type == 'BACKGROUND'), None)
if bg is None:
    raise RuntimeError(f"World 里找不到 Background 节点，实际节点="
                       f"{[ (n.name, n.type) for n in world.node_tree.nodes ]}")
bg.inputs["Color"].default_value = (0.05, 0.06, 0.08, 1.0)
bg.inputs["Strength"].default_value = 1.0
scene.world = world

# ---------- 存盘 ----------
OUT_DIR = r"J:\mickeylan\ai\blender\out"
os.makedirs(OUT_DIR, exist_ok=True)
blend_path = os.path.join(OUT_DIR, "dougong.blend")
bpy.ops.wm.save_as_mainfile(filepath=blend_path)

# ---------- 汇报 ----------
total_verts = sum(len(o.data.vertices) for o in coll.objects if o.type == 'MESH')
print("=" * 60)
print("DOUGONG BUILD OK")
print(f"  构件数: {len(coll.objects)}")
print(f"  顶点总数: {total_verts}")
print(f"  尺寸: 宽 {W:.3f} m x 深 {W:.3f} m x 高约 {H:.3f} m (斗口 {KOU} m)")
print(f"  构件清单: {', '.join(o.name for o in coll.objects)}")
print(f"  blend: {blend_path}")
print("=" * 60)
