"""服装隔离检查 —— 做漂亮渲染**之前**的闸门。

依据 blender-visual-craft：
  - 「角色优先五官、手、肩、脚等视觉焦点」
  - 「对被衣物遮住的连接，额外隐藏遮挡物检查灰模」
  - 「先用低成本实图确认主画面的材质、光线和重点，再投入高分辨率」

所以这一轮**只检查服装**，不碰材质和灯光：
  1. 人 + 衣，正/侧/背 三视图（看衣服怎么穿在身上）
  2. 只留衣服（隐藏身体）（看衣服本身是否成立、是否自闭合）
  3. Workbench 灰模（看曲面与连接，不受颜色干扰）
  4. **数值穿模自检**：裙子顶点到腿轴线的距离 vs 腿半径，
     直接给出「有几处穿插、最深多少毫米」，不靠肉眼。

用法：
    D:\\python3\\python.exe blender_client.py task_warrior_clothing.py
"""

import math
import os

import bpy
from mathutils import Vector

OUT_DIR = r"J:\mickeylan\ai\blender\out"
SRC = r"J:\mickeylan\ai\blender\task_warrior.py"

# 服装相关对象前缀
CLOTH_PREFIX = ("Ruan_", "Belt", "Skirt", "Sleeve_", "Cuff_", "Collar_")
# 身体/头发/道具
BODY_PREFIX = ("Body_", "Head", "EyeBall", "Lid", "Brow", "Nose", "Lip",
               "Neck", "Deltoid", "Clavicle", "Thigh", "Calf", "Foot",
               "UpperArm", "Forearm", "Palm", "Finger", "Thumb", "Fist")
PROP_PREFIX = ("Hair_", "Ponytail", "PonyTie", "SideLock", "Fringe",
               "Sword_", "BackSash")


def load_module():
    """以模块方式载入 task_warrior.py，不触发它的建模+渲染。"""
    ns = {"__name__": "warrior_lib", "WARRIOR_NO_AUTORUN": True}
    with open(SRC, encoding="utf-8") as f:
        src = f.read()
    exec(compile(src, SRC, "exec"), ns)
    return ns


def set_visible(prefixes, visible):
    for ob in bpy.data.objects:
        if ob.type != 'MESH':
            continue
        if ob.name.startswith(prefixes):
            ob.hide_render = not visible
            ob.hide_viewport = not visible


# ------------------------------------------------------------------
# 数值穿模自检
# ------------------------------------------------------------------
def seg_point_dist(p, a, b):
    ab = b - a
    t = 0.0
    denom = ab.dot(ab)
    if denom > 1e-12:
        t = max(0.0, min(1.0, (p - a).dot(ab) / denom))
    return (p - (a + ab * t)).length


def check_intersection():
    """裙子/袖口顶点 vs 腿、手臂的轴线+半径。

    返回 (穿模处数, 最深穿插量mm, 明细列表)。
    """
    # 腿/臂的轴线与半径（与 task_warrior.py 的建模参数一致）
    limbs = [
        ("Thigh_R", Vector((-0.072, 0.030, 0.855)), Vector((-0.108, 0.205, 0.470)), 0.079),
        ("Thigh_L", Vector((0.068, 0.030, 0.855)), Vector((0.094, -0.165, 0.480)), 0.080),
        ("Calf_R", Vector((-0.112, 0.205, 0.470)), Vector((-0.135, 0.400, 0.115)), 0.063),
        ("Calf_L", Vector((0.098, -0.165, 0.480)), Vector((0.112, -0.330, 0.105)), 0.061),
        ("UpperArm_R", Vector((-0.120, 0.040, 1.312)), Vector((-0.298, 0.086, 1.512)), 0.047),
        ("Forearm_R", Vector((-0.298, 0.086, 1.512)), Vector((-0.352, 0.196, 1.746)), 0.041),
        ("UpperArm_L", Vector((0.120, -0.036, 1.312)), Vector((0.248, -0.118, 1.188)), 0.047),
        ("Forearm_L", Vector((0.248, -0.118, 1.188)), Vector((0.324, -0.252, 1.150)), 0.041),
    ]
    # 锥度：末端半径按建模参数缩放
    limb_r1 = {"Thigh_R": 0.058, "Thigh_L": 0.056, "Calf_R": 0.063,
               "Calf_L": 0.061, "UpperArm_R": 0.036, "Forearm_R": 0.041,
               "UpperArm_L": 0.036, "Forearm_L": 0.041}

    hits = 0
    worst = 0.0
    detail = []
    for ob in bpy.data.objects:
        if ob.type != 'MESH':
            continue
        if not ob.name.startswith(("Skirt", "Sleeve_", "Ruan_", "Belt")):
            continue
        mw = ob.matrix_world
        for v in ob.data.vertices:
            p = mw @ v.co
            for (nm, a, b, r0) in limbs:
                r1 = limb_r1[nm]
                d = seg_point_dist(p, a, b)
                # 该肢体的平均半径取 (r0+r1)/2 做保守估计
                rm = (r0 + r1) * 0.5
                if d < rm:
                    pen = rm - d
                    hits += 1
                    if pen > worst:
                        worst = pen
                    if len(detail) < 12:
                        detail.append("%s @ %s  穿 %.1fmm"
                                      % (ob.name, nm, pen * 1000.0))
    return hits, worst, detail


def measure_clearance():
    """裙子到腿的最小间隙（正 = 没穿，负 = 穿）。"""
    legs = [
        ("Thigh_R", Vector((-0.072, 0.030, 0.855)), Vector((-0.108, 0.205, 0.470)), 0.079, 0.055),
        ("Thigh_L", Vector((0.068, 0.030, 0.855)), Vector((0.094, -0.165, 0.480)), 0.080, 0.054),
    ]
    best = 1e9
    for ob in bpy.data.objects:
        if ob.type != 'MESH' or not ob.name.startswith("Skirt"):
            continue
        mw = ob.matrix_world
        for v in ob.data.vertices:
            p = mw @ v.co
            for (nm, a, b, r0, r1) in legs:
                ab = b - a
                t = max(0.0, min(1.0, (p - a).dot(ab) / ab.dot(ab)))
                r = r0 + (r1 - r0) * t
                gap = seg_point_dist(p, a, b) - r
                best = min(best, gap)
    return best


# ------------------------------------------------------------------
def main():
    ns = load_module()
    ns["clear_scene"]()
    coll, made = ns["build"]()
    ns["setup_world"]()
    ns["add_lights"]()
    cam = ns["make_camera"]()

    ground = bpy.data.objects.get("Ground")
    if ground is not None:
        ground.hide_render = True

    shots = []

    # --- A. 人 + 衣，三视图 ---
    set_visible(BODY_PREFIX, True)
    set_visible(CLOTH_PREFIX, True)
    set_visible(PROP_PREFIX, True)
    for nm, d in (("front", (0.0, -1.0, 0.0)),
                  ("right", (-1.0, 0.0, 0.0)),
                  ("back", (0.0, 1.0, 0.0))):
        ns["aim_camera"](cam, d, margin=1.02, target=(0.0, 0.0, 0.95))
        shots.append(ns["render"](os.path.join(OUT_DIR, "cloth_%s.png" % nm)))

    # --- B. 只留衣服 ---
    set_visible(BODY_PREFIX, False)
    ns["aim_camera"](cam, (0.0, -1.0, 0.0), margin=1.02, target=(0.0, 0.0, 0.95))
    shots.append(ns["render"](os.path.join(OUT_DIR, "cloth_only.png")))
    set_visible(BODY_PREFIX, True)

    # --- C. 灰模（Workbench）：只看曲面与连接 ---
    sc = bpy.context.scene
    sc.render.engine = 'BLENDER_WORKBENCH'
    sh = sc.display.shading
    sh.light = 'STUDIO'
    sh.color_type = 'SINGLE'
    sh.single_color = (0.55, 0.55, 0.55)
    sh.show_shadows = True
    sh.show_cavity = True
    sh.cavity_type = 'BOTH'
    ns["aim_camera"](cam, (-0.82, -1.18, 0.22), margin=1.03, target=(0.0, 0.0, 1.00))
    shots.append(ns["render"](os.path.join(OUT_DIR, "cloth_clay.png")))
    sc.render.engine = 'BLENDER_EEVEE'

    # --- D. 数值自检 ---
    hits, worst, detail = check_intersection()
    gap = measure_clearance()

    print("=" * 64)
    print("CLOTHING GATE")
    print("  构件数: %d" % len(made))
    print("  穿模顶点: %d   最深: %.1f mm" % (hits, worst * 1000.0))
    print("  裙-腿最小间隙: %+.1f mm" % (gap * 1000.0))
    for d in detail[:8]:
        print("    " + d)
    print("  图: " + ", ".join(os.path.basename(s) for s in shots))
    print("=" * 64)

    if ground is not None:
        ground.hide_render = False
    # 隔离检查不得污染后续正式渲染：所有人物网格恢复可见。
    for ob in bpy.data.objects:
        if ob.type == 'MESH':
            ob.hide_render = False
            ob.hide_viewport = False


try:
    main()
except Exception:
    # 即使检查异常，也不把隐藏状态留在 MCP 当前场景。
    for ob in bpy.data.objects:
        if ob.type == 'MESH':
            ob.hide_render = False
            ob.hide_viewport = False
    import traceback
    traceback.print_exc()
    raise
