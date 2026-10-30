"""女侠 lookdev：在已通过服装闸门的当前场景上做电影感静帧。

不重建几何，不调用 read_factory_settings；只负责：
  - 丝绸/皮肤/头发/剑的材质层次
  - 暖主光 + 冷轮廓光 + 柔补光
  - 简洁摄影棚背景，避免背景抢人物
  - hero / full / face 三张固定证据图

运行：
  D:\\python3\\python.exe blender_client.py warrior_lookdev.py
"""
import math
import os
import bpy
from mathutils import Vector

OUT = r"J:\\mickeylan\\ai\\blender\\out"
LOOKDEV_COLL = "Lookdev"

def bsdf(mat):
    mat.use_nodes = True
    return next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)

def mat(name, color, rough, metallic=0.0, spec=0.45):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    n = bsdf(m)
    if n is None:
        raise RuntimeError("no Principled: %s" % name)
    n.inputs["Base Color"].default_value = (*color, 1.0)
    n.inputs["Roughness"].default_value = rough
    if "Metallic" in n.inputs:
        n.inputs["Metallic"].default_value = metallic
    if "Specular IOR Level" in n.inputs:
        n.inputs["Specular IOR Level"].default_value = spec
    elif "Specular" in n.inputs:
        n.inputs["Specular"].default_value = spec
    return m

def assign(prefixes, material):
    for ob in bpy.data.objects:
        if ob.type == 'MESH' and ob.name.startswith(prefixes):
            ob.data.materials.clear()
            ob.data.materials.append(material)

def clear_lookdev():
    c = bpy.data.collections.get(LOOKDEV_COLL)
    if c:
        for ob in list(c.objects):
            bpy.data.objects.remove(ob, do_unlink=True)
        bpy.data.collections.remove(c)

def collection():
    c = bpy.data.collections.new(LOOKDEV_COLL)
    bpy.context.scene.collection.children.link(c)
    return c

def add_area(c, name, loc, energy, color, size, target=(0, 0, 1.1)):
    ld = bpy.data.lights.new(name, 'AREA')
    ld.energy = energy
    ld.color = color
    ld.shape = 'DISK'
    ld.size = size
    ob = bpy.data.objects.new(name, ld)
    c.objects.link(ob)
    ob.location = loc
    ob.rotation_euler = (Vector(target) - ob.location).to_track_quat('-Z', 'Y').to_euler()
    return ob

def add_backdrop(c):
    # 低调的摄影棚地面和后墙；不做复杂环境，保证轮廓可读。
    m = mat("LOOK_Backdrop", (0.018, 0.025, 0.040), 0.82)
    for name, loc, scale in (# 地面必须是薄板；厚度 2m 会把 z<0.99 的下半身全部挡住。
                             ("LookFloor", (0, 0, -0.012), (5, 5, 0.01)),
                             ("LookWall", (0, 2.8, 2.2), (5, 0.08, 2.2))):
        bpy.ops.mesh.primitive_cube_add(location=loc)
        ob = bpy.context.object
        ob.name = name
        # 移到专用 collection
        for cc in list(ob.users_collection):
            cc.objects.unlink(ob)
        c.objects.link(ob)
        ob.scale = scale
        ob.data.materials.append(m)

def aim(cam, direction, target, radius, margin=1.05):
    d = Vector(direction).normalized()
    fov = 2 * math.atan(0.5 * cam.data.sensor_width / cam.data.lens)
    dist = radius / math.sin(fov * 0.5) * margin
    cam.location = Vector(target) + d * dist
    cam.rotation_euler = (Vector(target) - cam.location).to_track_quat('-Z', 'Y').to_euler()

def render(sc, cam, name, target, direction, radius, res):
    aim(cam, direction, target, radius)
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = 'PNG'
    sc.render.image_settings.color_mode = 'RGB'
    sc.render.image_settings.color_depth = '8'
    sc.render.filepath = os.path.join(OUT, name)
    bpy.ops.render.render(write_still=True)

def main():
    sc = bpy.context.scene
    # lookdev 不能继承服装隔离检查的隐藏状态；正式工程必须包含完整人物。
    for ob in bpy.data.objects:
        if ob.type == 'MESH':
            ob.hide_render = False
            ob.hide_viewport = False
    clear_lookdev()
    c = collection()

    skin = mat("LOOK_Skin", (0.50, 0.27, 0.20), 0.42, spec=0.38)
    cloth = mat("LOOK_Silk", (0.20, 0.045, 0.055), 0.30, spec=0.52)
    hair = mat("LOOK_Hair", (0.012, 0.008, 0.010), 0.25, spec=0.58)
    eye = mat("LOOK_Eye", (0.006, 0.004, 0.003), 0.18, spec=0.68)
    steel = mat("LOOK_Steel", (0.20, 0.24, 0.29), 0.20, metallic=0.82, spec=0.72)
    trim = mat("LOOK_Trim", (0.58, 0.25, 0.06), 0.28, metallic=0.35, spec=0.58)

    assign(("Body_", "Head", "Neck", "Deltoid", "Clavicle", "Thigh_", "Calf_", "Foot_",
            "UpperArm_", "Forearm_", "Palm_", "Finger_", "Thumb_", "Fist_", "Nose", "Lip", "Lid"), skin)
    assign(("Ruan_", "Belt", "Skirt", "Sleeve_", "BackSash", "Collar_", "Cuff_", "SkirtPleat_"), cloth)
    assign(("Hair_", "Pony", "SideLock", "Fringe"), hair)
    assign(("EyeBall",), eye)
    assign(("Sword_",), steel)
    assign(("BeltKnot",), trim)

    add_backdrop(c)
    add_area(c, "Look_Key", (-2.8, -4.0, 3.2), 950, (1.0, 0.68, 0.48), 2.8)
    add_area(c, "Look_Fill", (3.0, -2.0, 1.8), 420, (0.38, 0.52, 1.0), 3.4)
    add_area(c, "Look_Rim", (1.8, 2.6, 3.3), 1150, (0.30, 0.48, 1.0), 2.0)

    w = bpy.data.worlds.get("LookWorld") or bpy.data.worlds.new("LookWorld")
    w.use_nodes = True
    bg = next(n for n in w.node_tree.nodes if n.type == 'BACKGROUND')
    bg.inputs["Color"].default_value = (0.006, 0.009, 0.018, 1)
    bg.inputs["Strength"].default_value = 0.22
    sc.world = w
    sc.render.engine = 'BLENDER_EEVEE'
    sc.render.film_transparent = False
    sc.view_settings.view_transform = 'AgX'
    sc.view_settings.look = 'AgX - Medium High Contrast'
    sc.render.image_settings.file_format = 'PNG'

    cam = bpy.data.objects.get("WarriorCam")
    if cam is None:
        cd = bpy.data.cameras.new("WarriorCam")
        cam = bpy.data.objects.new("WarriorCam", cd)
        sc.collection.objects.link(cam)
    cam.data.lens = 58
    sc.camera = cam

    # hero 也必须是完整人物；上半身近景单独使用 lookdev_face。
    render(sc, cam, "lookdev_hero.png", (0, 0, 0.98), (-0.72, -1.25, 0.10), 1.35, (900, 1200))
    render(sc, cam, "lookdev_full.png", (0, 0, 0.98), (-0.72, -1.25, 0.10), 1.35, (800, 1100))
    # 仅脸部近景；地面不参与构图
    ground = bpy.data.objects.get("Ground")
    old_hide = ground.hide_render if ground else False
    if ground: ground.hide_render = True
    render(sc, cam, "lookdev_face.png", (0, -0.03, 1.575), (0.75, -1.10, 0.04), 0.145, (900, 900))
    if ground: ground.hide_render = old_hide

    # 最后一张 Render Result 必须是全身，不让 Blender 界面停在脸部特写。
    render(sc, cam, "FINAL_FULL_BODY.png", (0, 0, 0.98),
           (-0.72, -1.25, 0.10), 1.35, (900, 1200))

    # 正式工程不能停留在脸部特写：保存前恢复全身展示机位。
    # 否则打开 .blend 时下半身虽存在，却全部落在相机画面外。
    aim(cam, (-0.72, -1.25, 0.10), (0, 0, 0.98), 1.35, margin=1.05)
    sc.render.resolution_x, sc.render.resolution_y = (800, 1100)
    sc.render.resolution_percentage = 100
    sc.camera = cam
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "warrior_lookdev.blend"))
    print("LOOKDEV OK: lookdev_hero.png lookdev_full.png lookdev_face.png")

try:
    main()
except Exception:
    import traceback
    traceback.print_exc()
    raise
