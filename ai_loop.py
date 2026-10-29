"""AI 指挥 Blender 建模的闭环驱动（dream-loop 的最小可用实现）。

设计要点（全部来自本仓库 LESSONS.md 的实测结论）：
  - 建模脚本禁止出现 read_factory_settings（会杀死 MCP 通道，见 [002]）
  - 自查必须用真实渲染，不用视口截图（见 [011]）
  - 批评家是独立调用，带图；不依赖当前会话的视觉能力（见 [012]）
  - 模型/端点从本机已有配置读取，**不写入任何密钥**

用法:
    python ai_loop.py --goal "搭一个中式斗拱，斗口 10cm" --rounds 3
    python ai_loop.py --goal "..." --provider minimax --model MiniMax-M2.7
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from blender_client import BlenderMCP          # noqa: E402

OUT_DIR = os.path.join(HERE, "out")
os.makedirs(OUT_DIR, exist_ok=True)

OPENCODE_CFG = os.path.join(os.path.expanduser("~"), ".config", "opencode", "opencode.json")

# 已在本机验证存在的 Anthropic 兼容端点（凭据运行时从配置读取）
PROVIDERS = {
    "ali":      {"provider": "ali-coding-plan",   "model": "qwen3.5-plus"},
    "minimax":  {"provider": "minimax-mickeylan", "model": "MiniMax-M2.5"},
    # 视觉实测（LESSONS [040]）：只有 qwen3.5-plus 与 kimi-k2.5 真能看图。
    # glm-5 / MiniMax-M2.5 会回复"没有上传图片"；qwen3-max / qwen3-coder-* 该端点报错。
    # 因此独立评审只能在这两者之间交叉。
    "kimi":     {"provider": "ali-coding-plan",   "model": "kimi-k2.5"},
}

# 实测能看图、可做评审的模型
VISION_CAPABLE = {"qwen3.5-plus", "kimi-k2.5"}

# ---------------------------------------------------------------- 禁止模式
# LESSONS.md [002]：这些调用会重置 Blender，连带杀死 MCP socket 服务
FORBIDDEN = [
    (r"read_factory_settings", "会重置整个 Blender 并杀死 MCP 通道（LESSONS [002]）"),
    (r"read_homefile", "会重载启动文件，可能重置插件状态"),
    (r"wm\.quit_blender", "会关闭 Blender，终止本次会话"),
]


def check_code_safety(code: str) -> str | None:
    for pattern, reason in FORBIDDEN:
        if re.search(pattern, code):
            return f"代码里出现了 `{pattern}` —— {reason}。请改用手动清场。"
    return None


# ---------------------------------------------------------------- 安全助手库
# LESSONS [022]：实测发现多轮迭代中大部分轮次花在修 bpy API 细节
# （create_cube(size=tuple) / 颜色元组 5 个值 / base_color 属性不存在 …），
# 而不是改进设计。对策：注入一层预置助手，让模型写高层调用。
PRELUDE = r'''
import bpy, math, bmesh
from mathutils import Vector, Matrix, Euler

def clear_scene():
    """清场。增量模式下只删保留集合之外的构件。

    _KEEP 由 harness 在 PRELUDE **之前**注入（见 Session.run）。
    这里用 globals().get 取，**不要**在 PRELUDE 里写 _KEEP = None ——
    那会把注入值冲掉（实测踩过：注入被覆盖，增量模式退化成全量清场）。
    """
    keep = globals().get("_KEEP", None)
    if keep is not None:
        keep = list(keep)

        def _kept(n):
            return any(n == k or n.startswith(k) for k in keep)

        for o in list(bpy.data.objects):
            if _kept(o.name):
                continue
            bpy.data.objects.remove(o, do_unlink=True)
        # 集合：只删空的
        for c in list(bpy.data.collections):
            if not c.objects and not c.children:
                bpy.data.collections.remove(c)
        print("CLEAR_PARTIAL kept=%d" % len(keep))
        return
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)
    # 材质也清掉：否则多轮循环会残留上一轮材质（.001 后缀堆积），
    # 且上一轮的坏材质会被下一轮的幂等 mat() 复用。
    for m in list(bpy.data.materials):
        if m.users == 0 or m.name.startswith('_DefaultGrey'):
            try:
                bpy.data.materials.remove(m)
            except Exception:
                pass

# ---- 容错适配层（LESSONS [024]）----
# LLM 会用「位置参数 + None 占位」的写法，还会把角度当弧度传。
# 与其要求模型写准，不如让助手层接受各种形式。
def _is_mat(v):
    return v is not None and v.__class__.__name__ == "Material"

def _shift(args, idx, want):
    """若第 idx 个位置参数是 Material 而期望的是向量，则把它挤到 material 位。"""
    return args

def _vec(v, default=(0.0, 0.0, 0.0)):
    if v is None:
        return tuple(float(x) for x in default)
    if _is_mat(v):
        return tuple(float(x) for x in default)
    if isinstance(v, (int, float)):
        return (float(v),) * 3
    vals = [float(x) for x in v]
    if len(vals) == 2:
        vals.append(0.0)
    return tuple(vals[:3])

def _rot(v):
    """接受 None / 标量 / 2-3 元组；明显是角度（任一 |值|>2π）就自动转弧度。"""
    if v is None or _is_mat(v):
        return (0.0, 0.0, 0.0)
    if isinstance(v, (int, float)):
        vals = [0.0, 0.0, float(v)]
    else:
        vals = [float(x) for x in v]
        if len(vals) == 2:
            vals.append(0.0)
        vals = vals[:3]
    if any(abs(x) > 6.2832 for x in vals):
        vals = [math.radians(x) for x in vals]
    return tuple(vals)

def _flatten(v):
    out = []
    if isinstance(v, (int, float)):
        return [float(v)]
    try:
        for x in v:
            if isinstance(x, (tuple, list)):
                out.extend(_flatten(x))
            else:
                try:
                    out.append(float(x))
                except (TypeError, ValueError):
                    pass
    except TypeError:
        pass
    return out

def _size(v):
    """接受标量 / 2 元组 / 3 元组 / 嵌套元组；Material 误传则回退 1m。"""
    if v is None or _is_mat(v):
        return (1.0, 1.0, 1.0)
    vals = _flatten(v)
    if not vals:
        return (1.0, 1.0, 1.0)
    if len(vals) == 1:
        return (vals[0],) * 3
    if len(vals) == 2:
        return (vals[0], vals[1], min(vals))
    return tuple(vals[:3])

def _pick_mat(candidates):
    for c in candidates:
        if _is_mat(c):
            return c
    return None

def mat(name, rgb, rough=0.6, metallic=0.0):
    """建材质。同名材质复用（幂等），避免 .001 后缀堆积。

    若复用的材质已经没有 Principled BSDF（历史遗留的坏材质），重建节点树。
    """
    m = bpy.data.materials.get(name)
    if m is None:
        m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = next((n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if b is None:
        # 坏材质：清空重建
        nt = m.node_tree
        for n in list(nt.nodes):
            try:
                nt.nodes.remove(n)
            except Exception:
                pass
        b = nt.nodes.new('ShaderNodeBsdfPrincipled')
        out = nt.nodes.new('ShaderNodeOutputMaterial')
        b.location = (0, 0)
        out.location = (300, 0)
        nt.links.new(b.outputs[0], out.inputs[0])
    rgb = list(rgb) + [0.0] * (3 - len(rgb))
    b.inputs["Base Color"].default_value = (rgb[0], rgb[1], rgb[2], 1.0)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metallic
    return m

def _link(ob):
    bpy.context.scene.collection.objects.link(ob)
    return ob

# 默认兜底材质：保证任何构件都至少有 1 个材质槽
_DEFAULT_MAT = None

def _ensure_slot(ob, material):
    """保证 ob 至少有 1 个材质槽。

    LESSONS [027]：模型常写 `ob.material_slots[0].material = m`，
    若物体建时没给材质，material_slots 为空 -> IndexError。
    """
    global _DEFAULT_MAT
    if material is not None:
        try:
            ob.data.materials.append(material)
        except Exception:
            pass
    if len(ob.data.materials) == 0:
        if _DEFAULT_MAT is None:
            _DEFAULT_MAT = bpy.data.materials.new("_DefaultGrey")
            _DEFAULT_MAT.use_nodes = True
        try:
            ob.data.materials.append(_DEFAULT_MAT)
        except Exception:
            pass
    return ob

def box(name, size, loc=(0, 0, 0), rot=(0, 0, 0), material=None, coll=None):
    """长方体：size=(x,y,z) 为完整边长，loc 为中心。参数全部容错。"""
    material = material or _pick_mat([rot, coll])
    sx, sy, sz = (v * 0.5 for v in _size(size))
    lx, ly, lz = _vec(loc)
    rx, ry, rz = _rot(rot)
    verts = [(x * sx, y * sy, z * sz) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    ob = _link(bpy.data.objects.new(name, me))
    ob.location = (lx, ly, lz)
    ob.rotation_euler = (rx, ry, rz)
    _ensure_slot(ob, material)
    if coll is not None and hasattr(coll, "objects"):
        coll.objects.link(ob)
        bpy.context.scene.collection.objects.unlink(ob)
    return ob

def cyl(name, radius, depth, loc=(0, 0, 0), rot=(0, 0, 0), verts=24, material=None, coll=None):
    # 模型可能把 material 挤进 verts 位，或把 verts 传成材质
    material = material or _pick_mat([verts, coll])
    if _is_mat(verts):
        verts = 24
    verts = int(verts) if isinstance(verts, (int, float)) else 24
    lx, ly, lz = _vec(loc)
    rx, ry, rz = _rot(rot)
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=max(3, verts),
                          radius1=float(radius), radius2=float(radius), depth=float(depth))
    bm.to_mesh(me); bm.free(); me.update()
    ob = _link(bpy.data.objects.new(name, me))
    ob.location = (lx, ly, lz)
    ob.rotation_euler = (rx, ry, rz)
    _ensure_slot(ob, material)
    if coll is not None and hasattr(coll, "objects"):
        coll.objects.link(ob)
        bpy.context.scene.collection.objects.unlink(ob)
    return ob

def prism(name, footprint, height, loc=(0, 0, 0), rot=(0, 0, 0), apex=(0.5, 0.5), material=None, coll=None):
    """棱台/反曲屋顶毛坯：footprint=(x,y) 底面，height 高，apex=(fx,fy) 顶面缩放比。"""
    material = material or _pick_mat([apex, coll])
    fp = _size(footprint if not isinstance(footprint, (int, float)) else (footprint, footprint, 1.0))
    if _is_mat(apex):
        apex = (0.5, 0.5)
    if apex is None:
        apex = (0.5, 0.5)
    if isinstance(apex, (int, float)):
        fx = fy = float(apex)
    else:
        ap = [float(x) for x in apex]
        fx = ap[0]
        fy = ap[1] if len(ap) > 1 else ap[0]
    hx, hy, hz = fp[0] * 0.5, fp[1] * 0.5, float(height) * 0.5
    lx, ly, lz = _vec(loc)
    rx, ry, rz = _rot(rot)
    verts = [(-hx, -hy, -hz), (hx, -hy, -hz), (hx, hy, -hz), (-hx, hy, -hz),
             (-hx * fx, -hy * fy, hz), (hx * fx, -hy * fy, hz),
             (hx * fx, hy * fy, hz), (-hx * fx, hy * fy, hz)]
    faces = [(0, 1, 2, 3), (7, 6, 5, 4), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)]
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    ob = _link(bpy.data.objects.new(name, me))
    ob.location = (lx, ly, lz)
    ob.rotation_euler = (rx, ry, rz)
    _ensure_slot(ob, material)
    if coll is not None and hasattr(coll, "objects"):
        coll.objects.link(ob)
        bpy.context.scene.collection.objects.unlink(ob)
    return ob

def beam(name, p1, p2, thickness, material=None):
    """两点之间架一根方木（梁/枋/栏杆）。"""
    a, b = Vector(p1), Vector(p2)
    d = b - a
    length = d.length
    if length < 1e-6:
        raise ValueError("beam: 两点重合")
    ob = box(name, (thickness, thickness, length), loc=(a + b) * 0.5, material=material)
    ob.rotation_mode = 'QUATERNION'
    ob.rotation_quaternion = d.to_track_quat('Z', 'Y')
    return ob

def coll(name):
    c = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(c)
    return c

# ================= 形制助手：宋代斗拱 =================
# LESSONS [044]：评审反复要求"T1 屋面缺少可辨识的斗拱结构"——
# 模型自由发挥做不出斗拱（层数/出跳/斗块全靠猜）。
# 把"五铺作单朵斗拱"编码成参数，模型只需给斗口 kou 与位置。
#
# 层级（自下而上），k = 斗口模数：
#   0  栌斗        十字形基座，落在柱头
#   1  华栱(第一跳) 十字出跳 4k，4 个交互斗
#   2  泥道栱      沿 x 连到两端交互斗
#   3  令栱(第二跳) 再出跳，散斗
#   4  下昂        斜挑出檐外 + 蚂蚱头
#   5  撩檐枋      顶部承檩
#
# 形制细节（宋式区别于清式的关键）：
#   卷杀 —— 栱的**底面是一道曲线**，向两端翘起，不是直棱方木
#   斗欹 —— 斗块**底部收分**（下小上大），不是直立方块
# 视觉评审实测点名的缺失项正是这两条（LESSONS [044]）。

def _mesh_object(name, verts, faces, material=None, coll_target=None):
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    ob = _link(bpy.data.objects.new(name, me))
    if material is not None:
        me.materials.append(material)
    if coll_target is not None:
        coll_target.objects.link(ob)
    return ob


def _juan_sha_gong(name, span, width, height, loc=(0, 0, 0), axis='X',
                   material=None, coll_target=None, taper=0.45):
    """带**卷杀**的栱（华栱/令栱）。

    底面沿长度方向是一道上翘的曲线（宋式「卷杀」），
    顶面平直，两端收薄。清式斗拱的栱是直棱的，
    这条曲线正是区分宋清的最直观特征。
    """
    N = 12
    V, F = [], []
    for i in range(N + 1):
        u = i / N
        x = -span * 0.5 + u * span
        t = min(u, 1.0 - u) * 2.0            # 0=中心 1=两端
        bot = height * (1.0 - taper * (t ** 1.7))
        V.extend([
            (x, -width * 0.5, bot), (x, width * 0.5, bot),
            (x, width * 0.5, height), (x, -width * 0.5, height),
        ])
    for i in range(N):
        a = i * 4
        b = (i + 1) * 4
        for k in range(4):
            k2 = (k + 1) % 4
            F.append((a + k, a + k2, b + k2, b + k))
    # 两端封口
    F.append((0, 3, 2, 1))
    F.append((N * 4, N * 4 + 1, N * 4 + 2, N * 4 + 3))
    ob = _mesh_object(name, V, F, material, coll_target)
    ob.location = loc
    if axis == 'Y':
        ob.rotation_euler = (0.0, 0.0, math.radians(90.0))
    return ob


def _dou_block(name, w, d, h, loc=(0, 0, 0), material=None, coll_target=None,
               neck=0.70):
    """带**斗欹**的斗块（散斗/交互斗）。

    底部按 neck 比例收分，到 1/3 高处再放大到全尺寸，
    形成宋式斗块特有的「下小上大」束腰。
    """
    V = []
    hw, hd = w * 0.5, d * 0.5
    nw, nd = hw * neck, hd * neck
    z1 = h * 0.34
    # 底环（收分）
    V.extend([(-nw, -nd, 0), (nw, -nd, 0), (nw, nd, 0), (-nw, nd, 0)])
    # 中环（全尺寸）
    V.extend([(-hw, -hd, z1), (hw, -hd, z1), (hw, hd, z1), (-hw, hd, z1)])
    # 顶环（全尺寸）
    V.extend([(-hw, -hd, h), (hw, -hd, h), (hw, hd, h), (-hw, hd, h)])
    F = [(3, 2, 1, 0)]
    for ring in (0, 1):
        a, b = ring * 4, (ring + 1) * 4
        for k in range(4):
            k2 = (k + 1) % 4
            F.append((a + k, a + k2, b + k2, b + k))
    F.append((8, 9, 10, 11))
    ob = _mesh_object(name, V, F, material, coll_target)
    ob.location = loc
    return ob

def dougong(name, z=0.0, kou=0.10, material=None, coll_target=None,
            x=0.0, y=0.0):
    """宋代五铺作斗拱（单朵），坐落在柱头上。

    kou : 斗口（模数，米）。所有构件尺寸按斗口倍数推算。
    z   : 栌斗底面高度（应等于柱头高度）
    x,y : 这朵斗拱在平面上的位置（柱心）
    返回：构件名列表（便于 stats 分组统计）

    宋式特点（与清式最大的区别）：**出跳少、构件简洁、昂修长**。
    """
    k = float(kou)
    M = material
    made = []
    bx, by = float(x), float(y)

    def mk(part, size, loc, rot=(0.0, 0.0, 0.0)):
        ob = box("%s_%s" % (name, part), size,
                 (loc[0] + bx, loc[1] + by, loc[2]), rot, M, coll_target)
        made.append(ob.name)
        return ob

    def mk_gong(part, span, width, height, loc, axis):
        ob = _juan_sha_gong("%s_%s" % (name, part), span, width, height,
                             (loc[0] + bx, loc[1] + by, loc[2]), axis,
                             M, coll_target)
        made.append(ob.name)
        return ob

    def mk_dou(part, w, d, h, loc):
        ob = _dou_block("%s_%s" % (name, part), w, d, h,
                        (loc[0] + bx, loc[1] + by, loc[2]), M, coll_target)
        made.append(ob.name)
        return ob

    # ---- 0 栌斗：十字形基座（两个盒子交叉，十字臂 3.4k）----
    mk("Lutou_X", (3.4 * k, 1.9 * k, 2.0 * k), (0, 0, z + 1.0 * k))
    mk("Lutou_Y", (1.9 * k, 3.4 * k, 2.0 * k), (0, 0, z + 1.0 * k))

    # ---- 1 华栱（第一跳）：十字向外出跳 4k（带卷杀）----
    z1 = z + 2.0 * k
    mk_gong("HuaGong_X", 8.0 * k, 1.6 * k, 1.6 * k, (0, 0, z1), 'X')
    mk_gong("HuaGong_Y", 8.0 * k, 1.6 * k, 1.6 * k, (0, 0, z1), 'Y')

    # ---- 交互斗：华栱 4 个出挑端顶上的十字斗（带斗欹）----
    z2 = z1 + 1.6 * k
    for sx in (-1, 1):
        mk_dou("JiaoDouX%d" % (sx > 0), 1.9 * k, 1.9 * k, 1.5 * k,
               (sx * 4.0 * k, 0, z2))
    for sy in (-1, 1):
        mk_dou("JiaoDouY%d" % (sy > 0), 1.9 * k, 1.9 * k, 1.5 * k,
               (0, sy * 4.0 * k, z2))

    # ---- 2 泥道栱：沿 x 架在两端交互斗上 ----
    z3 = z2 + 1.5 * k
    mk_gong("NiDaoGong", 9.6 * k, 1.5 * k, 1.5 * k, (0, 0, z3), 'X')

    # ---- 散斗：泥道栱两端 ----
    z4 = z3 + 1.5 * k
    for sx in (-1, 1):
        mk_dou("SanDouX%d" % (sx > 0), 1.8 * k, 1.8 * k, 1.4 * k,
               (sx * 4.0 * k, 0, z4))

    # ---- 3 令栱（第二跳）：沿 x 再出跳到 5.6k，另沿 y 出跳 ----
    z5 = z4 + 1.4 * k
    mk_gong("LingGong_X", 11.2 * k, 1.4 * k, 1.4 * k, (0, 0, z5), 'X')
    mk_gong("LingGong_Y", 9.6 * k, 1.4 * k, 1.4 * k, (0, 0, z5), 'Y')

    # ---- 散斗：令栱外端 ----
    z6 = z5 + 1.4 * k
    for sx in (-1, 1):
        mk_dou("SanDou2X%d" % (sx > 0), 1.8 * k, 1.8 * k, 1.4 * k,
               (sx * 5.6 * k, 0, z6))
    for sy in (-1, 1):
        mk_dou("SanDou2Y%d" % (sy > 0), 1.8 * k, 1.8 * k, 1.4 * k,
               (0, sy * 4.8 * k, z6))

    # ---- 4 下昂：从泥道栱层斜挑出檐外（宋式昂修长）----
    # 昂身自中心向外斜上，至端部再以蚂蚱头斜收。
    for sy in (-1, 1):
        p0 = (0.0, sy * 0.6 * k, z4 - 0.3 * k)
        p1 = (0.0, sy * 6.6 * k, z6 + 0.5 * k)
        beam("%s_Ang%d" % (name, sy > 0), p0, p1, 1.3 * k, M)
        made.append("%s_Ang%d" % (name, sy > 0))
        # 蚂蚱头：昂端斜垫块（三角感用旋转盒近似）
        mk("MaZhaTou%d" % (sy > 0), (1.3 * k, 1.9 * k, 1.1 * k),
           (0, sy * 7.0 * k, z6 + 1.0 * k), (math.radians(22 * sy), 0, 0))

    # ---- 5 撩檐枋：顶部承檩的横枋 ----
    z7 = z6 + 1.4 * k
    mk("LiaoYanFang", (12.6 * k, 1.5 * k, 1.5 * k), (0, 0, z7 + 0.75 * k))

    print("DOUGONG %s 构件数=%d 斗口=%.3fm 总高=%.2fm" % (
        name, len(made), k, z7 + 1.5 * k - z))
    return made

# ================= 形制助手：贯木拱虹桥 =================
# LESSONS [048]：《清明上河图》最著名的建筑是虹桥。
#
# 形制依据（唐寰澄 1953 年首次科学认定 + 后续研究）：
#   - 名称："编木拱 / 贯木拱 / 叠梁拱"
#   - 《东京梦华录》："其桥无柱，皆以巨木虚架，饰以丹艧，宛如飞虹"
#   - **主体结构由两组拱骨系统交错搭置，通过横梁贯穿联合而成**，
#     中间无榫无钉，靠木料相互**别压咬合**承重
#   - 推算尺寸：净跨约 20m，**拱矢约 5m**，宽约 8m
#   - 后世木拱廊桥（福建屏南万安桥、浙江云和梅崇桥）为其"活态"遗存：
#     一级受力系统 = **三节苗**（3 段实木），
#     二级受力系统 = **五节苗**（5 段实木），
#     两套系统**穿插别压**，接头称"大小牛头"，以榫卯咬合
#
# 早前错误版本：把桥做成"三组平行梁"。
# 视觉评审一致判"梁表现为平行的直线木梁，三维结构不明确"，
# 根因正是**没有第二套系统**，因此无从"交错搭置"。
#
def hongqiao(name, span=20.0, width=8.0, rise=5.0, beam_r=0.34,
             ribs=4, deck_th=0.18, post_h=0.55, rail_h=1.10, z=0.0,
             weave_amp=1.25, material=None, plank_mat=None, rail_mat=None,
             mat_a=None, mat_b=None, mat_miao=None, coll_target=None):
    """贯木拱虹桥（编木拱 / 叠梁拱）。

    span      : 净跨（两岸桥台之间的水平距离），唐寰澄推算约 20m
    width     : 桥面宽，推算约 8m
    rise      : 拱矢（拱背中部相对两岸抬高），推算约 5m
    beam_r    : 拱肋圆木的截面半径
    ribs      : 横向并列的拱肋**对**数（每对 = 三节苗 + 五节苗两套系统）
    post_h    : 拱背与桥面之间的撑木高度
    weave_amp : 二级（五节苗）系统相对一级（三节苗）折线的**交替偏离量**。
                这就是"穿插别压"的编织幅度：越大，X 形交叉越明显。
    z         : 两岸桥台顶（梁端搭放处）的高度

    返回构件名列表。
    """
    M = material
    made = []

    def mkbox(part, size, loc, rot=(0.0, 0.0, 0.0), mat=None):
        ob = box("%s_%s" % (name, part), size, loc, rot,
                 mat if mat is not None else M, coll_target)
        made.append(ob.name)
        return ob

    def mkcyl(part, radius, depth, loc, rot=(0.0, 0.0, 0.0), verts=16,
              mat=None):
        ob = cyl("%s_%s" % (name, part), radius, depth, loc, rot, verts,
                 mat if mat is not None else M, coll_target)
        made.append(ob.name)
        return ob

    half = span * 0.5
    z_end = z + beam_r * 0.35
    z_top = z + rise

    # ---- 两套拱骨系统：**三节苗**（一级受力）与 **五节苗**（二级受力）----
    # 权威依据（福建屏南万安桥 / 浙江云和梅崇桥，"活态虹桥"）：
    #   "拱架系统由两套系统构成：最下方由三段实木搭建的'三节苗'构成了一级
    #    受力系统，由五段实木组成的'五节苗'与其穿插别压，构成了二级受力系统。"
    #
    # **关键在于两套系统的节苗数不同（3 段 vs 5 段）**：
    # 节点因此互相错开，二级（五节苗）的节点交替落在
    # 一级（三节苗）折线的上��与下方 —— 于是两套梁**反复上下交替**，
    # 侧立面上就是连续的 X 形交叉，也就是"穿插别压"。
    #
    # 早前版本两套系统都用 3 段、只做纵向平移，结果永远平行，
    # 视觉评审实测判"结构为平行的双层木梁，缺少编织网架的交错咬合"。
    def poly_eval(pts, x):
        """折线求值：给定 x，返回 z。"""
        if x <= pts[0][0]:
            return pts[0][1]
        for i in range(len(pts) - 1):
            x0, z0 = pts[i]
            x1, z1 = pts[i + 1]
            if x0 <= x <= x1:
                w = (x - x0) / max(1e-6, (x1 - x0))
                return z0 + (z1 - z0) * w
        return pts[-1][1]

    # 一级系统：三节苗（4 节点 = 3 段）
    _u3 = (0.0, 1.0 / 3.0, 2.0 / 3.0, 1.0)
    A_pts = [(-half + uu * span, z_end if i in (0, 3) else z_top)
             for i, uu in enumerate(_u3)]

    # 二级系统：五节苗（6 节点 = 5 段），节点在 u = 0.2/0.4/0.6/0.8，
    # 高度相对一级折线**交替** 上下偏离 weave_amp —— 这就是编织的来源。
    _u5 = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
    B_pts = []
    for i, uu in enumerate(_u5):
        x = -half + uu * span
        if i in (0, len(_u5) - 1):
            B_pts.append((x, z_end))
        else:
            base = poly_eval(A_pts, x)
            # i=1 上, i=2 下, i=3 上, i=4 下 —— 交替
            sgn = +1.0 if (i % 2 == 1) else -1.0
            B_pts.append((x, base + sgn * weave_amp))

    # ---- 逐肋对：两套系统横向错开 ----
    # 横向间距必须 **> 两个梁半径之和**，否则两套系统在交叉处互相穿插，
    # 渲染上糊成一根，"一根压住另一根"完全看不出来
    # （实测视觉评审："两根纵梁在相交处呈现平顺的交叉，
    #   未形成直接的互相咬合搭接"）。
    dw = beam_r * 2.15
    pair_w = width / ribs
    # 三套体系用**不同木色**区分 —— 同色同调时几十根叠在一起的圆木
    # 在渲染里糊成一片，编织关系完全读不出来（实测踩过：
    # 视觉评审连续判"呈现为普通三角桁架，未能展示两套系统交织的咬合"）。
    # 这也是古建测绘图区分结构体系的做法。
    _mat_ab = {"A": mat_a if mat_a is not None else M,
               "B": mat_b if mat_b is not None else M}
    for i in range(ribs):
        yc = -width * 0.5 + pair_w * (i + 0.5)
        for tag, pts, sgn in (("A", A_pts, -1.0), ("B", B_pts, +1.0)):
            y = yc + sgn * dw * 0.5
            mtag = _mat_ab[tag]
            for s in range(len(pts) - 1):
                a = Vector((pts[s][0], y, pts[s][1]))
                b = Vector((pts[s + 1][0], y, pts[s + 1][1]))
                d = b - a
                ob = mkcyl("R%d%s_S%d" % (i, tag, s), beam_r, d.length * 1.01,
                           tuple((a + b) * 0.5), mat=mtag)
                ob.rotation_mode = 'QUATERNION'
                ob.rotation_quaternion = d.to_track_quat('Z', 'Y')
                made[-1] = ob.name
            # 节点处的"大小牛头"—— 榫卯咬合处加厚（无榫无钉，靠别压）
            # 评审实测点名"缺少节点绑扎细节（短柱与横梁的连接）"，
            # 故此处加：加厚的节点木 + 穿过节点的短横木 + 麻绳箍。
            # 节点必须**看得出是接头**：评审实测原话
            # "拱肋为长弧形直木，非短段折线木"——
            # 接头不显眼，两根短木就看成了一根长弧木。
            # 故牛头加粗加长，并另加一道更粗的麻绳箍。
            for s in range(1, len(pts) - 1):
                px, pz = pts[s]
                mkcyl("R%d%s_Joint%d" % (i, tag, s), beam_r * 1.45,
                      beam_r * 1.45, (px, y, pz), mat=mtag)
                # 麻绳箍：套在接头处，比牛头更粗
                mkcyl("R%d%s_Rope%d" % (i, tag, s), beam_r * 1.62,
                      beam_r * 0.30, (px, y, pz),
                      mat=(mat_miao if mat_miao is not None else M))
                # 短横木：沿 y 贯穿该节点，把这一对的 A/B 两系统别住
                ob = mkbox("R%d%s_Tie%d" % (i, tag, s),
                           (beam_r * 1.15, dw * 2.4, beam_r * 0.9),
                           (px, yc, pz - beam_r * 0.15), mat=mtag)
                made[-1] = ob.name

    # ---- 拱背剖面（桥面与撑木跟随它）----
    # 取两套系统的**包络**（max），否则桥面会压到二级（五节苗）系统上。
    def profile(u):
        u = max(0.0, min(1.0, u))
        x = -half + u * span
        return max(poly_eval(A_pts, x), poly_eval(B_pts, x))

    # ---- 横向苗：与纵向拱肋交叉编织，形成立体的菱形网格 ----
    # 这是《清明上河图》虹桥最醒目的形象特征 —— 从桥下仰望，
    # 无数横木与纵梁交错成菱形网格。
    #
    # 关键：横向苗**不是垂直于桥轴的**，而是**斜跨**的
    # （百科原文："巨木**纵横**相贯、交错搭置"）。
    # 苗一旦斜跨，与纵向拱肋就构成明确的对角交叉，
    # 网格才读得出"编织网架"；垂直的苗只会像一道道横档。
    #
    # 每道苗沿 y 方向横跨全桥，在**每一道纵向肋的所在位置**
    # 交替地压上去 / 钻下去（篮式编织）。压的幅度必须 > 一个梁径，
    # 否则两梁在交点互相穿插，看不出谁压谁。
    cross_ys = []
    for i in range(ribs):
        yc = -width * 0.5 + pair_w * (i + 0.5)
        for sgn in (-1.0, +1.0):
            cross_ys.append(yc + sgn * dw * 0.5)
    cross_ys.sort()

    amp2 = beam_r * 2.6          # 压/钻的净空，必须大于一个梁径
    n_cross = 11
    skew = width * 0.78          # 苗的斜跨量：倾角 atan(0.78)≈38°，
                                # 早前 0.34 只有 19°，看起来就是垂直的
                                # （评审："横向苗木与桥轴线垂直，未体现斜跨"）
    for k in range(n_cross):
        # 相邻的苗**反向斜跨**（人字形）：
        # 一来端头收得住（单向斜跨时末道苗会伸出桥外 5m），
        # 二来相邻苗互相交叉，才形成真正的菱形网格，
        # 而不是一片平行的横档。
        sdir = +1.0 if (k % 2 == 0) else -1.0
        uu = 0.12 + k * (0.76 / (n_cross - 1.0))
        xc = -half + uu * span               # 苗的中点位置
        x0 = xc - sdir * skew * 0.5          # 苗在 -y 侧的端点 x
        # 苗的节点：沿 y 方向横跨全桥，在每一道纵向肋处交替上下
        pts = []
        for j, yy in enumerate(cross_ys):
            t = (yy + width * 0.5) / width            # 0..1 沿桥宽
            xx = x0 + t * sdir * skew
            base = profile((xx + half) / span)
            sgn = +1.0 if (j % 2 == 0) else -1.0
            pts.append((xx, yy, base + sgn * amp2))
        # 两端落在桥边
        pts.insert(0, (x0, -width * 0.5,
                       profile((x0 + half) / span) - beam_r * 0.2))
        pts.append((x0 + sdir * skew, width * 0.5,
                    profile((x0 + sdir * skew + half) / span) - beam_r * 0.2))
        for s in range(len(pts) - 1):
            a = Vector(pts[s])
            b = Vector(pts[s + 1])
            d = b - a
            ob = mkcyl("Miao_%d_S%d" % (k, s), beam_r * 0.95, d.length * 1.02,
                       tuple((a + b) * 0.5),
                       mat=(mat_miao if mat_miao is not None else M))
            ob.rotation_mode = 'QUATERNION'
            ob.rotation_quaternion = d.to_track_quat('Z', 'Y')
            made[-1] = ob.name
            # 交叉点的"别压"记号：一小段加粗的短木，明确标出压/钻处
            if 1 <= s < len(pts) - 1:
                ob2 = mkcyl("Miao_%d_X%d" % (k, s), beam_r * 1.25,
                            beam_r * 0.7, tuple(a),
                            mat=(mat_miao if mat_miao is not None else M))
                ob2.rotation_mode = 'QUATERNION'
                ob2.rotation_quaternion = d.to_track_quat('Z', 'Y')
                made[-1] = ob2.name

    # ---- 横梁贯穿：把两套系统联合成整体 ----
    # 百科原文："通过横梁贯穿联合而成"。横梁沿 y 方向贯穿整桥宽。
    for k, uu in enumerate((0.16, 0.30, 0.44, 0.56, 0.70, 0.84)):
        x = -half + uu * span
        zz = profile(uu)
        ob = mkbox("Tie_%d" % k, (0.22, width * 1.01, 0.22),
                   (x, 0.0, zz - beam_r * 0.5))
        made[-1] = ob.name

    # ---- 桥面：横向铺板（一块块铺，板间留缝，看得出铺装纹理）----
    # 评审实测点名"缺少桥面铺装纹理"。整块大板看着像塑料板。
    # 桥面底必须高于**整段编织的最高点**（profile + weave_amp），
    # 否则五节苗的上半段被桥面盖住，只剩下半段，
    # 视觉上就成了"上下叠置"而不是"穿插别压"
    # （实测 clear=1.31 > weave_amp=1.25 → 编织被吃掉）。
    # 净空还要再留一个梁径，才能看清压在上方的那根。
    # 桥面底 = 包络(profile) + clear。
    # 早前误以为"编织被桥面遮住"—— 其实 profile 是两套系统的**包络**，
    # 编织永远在包络之下，遮不住。真正的变量是**桥面与拱背之间的空隙**：
    # 空隙大 → 视觉读成"上下叠置"（评审原话），空隙小 → 读成密实的木构整体。
    # 真实的虹桥桥面是紧贴着木料铺的。
    # clear 的下限由横向苗决定：苗要压过肋，峰值 = profile + amp2，
    # 所以 clear 必须 > amp2 才不会把苗戳穿。
    clear = amp2 + beam_r * 1.25
    NS = 8
    deck = []
    for i in range(NS + 1):
        u = i / NS
        deck.append((-half + u * span, profile(u) + clear + deck_th * 0.5))

    def deck_top(u):
        u = max(0.0, min(1.0, u))
        x = -half + u * span
        for i in range(NS):
            x0, z0 = deck[i]
            x1, z1 = deck[i + 1]
            if x0 <= x <= x1:
                w = (x - x0) / max(1e-6, (x1 - x0))
                return z0 + (z1 - z0) * w
        return deck[-1][1]

    n_plank = 46
    plank_w = span / n_plank * 0.88
    for i in range(n_plank):
        u = i / (n_plank - 1.0)
        x = -half + u * span
        ua, ub = max(0.0, u - 0.004), min(1.0, u + 0.004)
        ang = math.atan2(deck_top(ub) - deck_top(ua), (ub - ua) * span)
        # 相邻板用不同木色，板缝才看得出来（评审两次点名"缺少铺装纹理"）
        pm = plank_mat if (plank_mat is not None and i % 2 == 1) else M
        ob = box("%s_Plank_%d" % (name, i), (plank_w, width, deck_th),
                 (x, 0.0, deck_top(u)), (0.0, -math.degrees(ang), 0.0),
                 pm, coll_target)
        made.append(ob.name)

    # ---- 腹架：斜撑（拱背与桥面之间）----
    # 这层的取舍实测过三版，结论是**必须留**：
    #   整齐的垂直撑木 -> "垂直支撑的三角形桁架"（太规整）
    #   斜撑           -> "抬梁加斜撑框架"（读成常规木构）
    #   完全删掉       -> "结构不完整、缺少支撑"（桥面像悬空）
    # 折中：用**斜撑**但压低体量（半径 0.42 梁径），且不成阵列，
    # 让它读作腹架而不读作主体结构。
    for i in range(ribs):
        yc = -width * 0.5 + pair_w * (i + 0.5)
        for k in range(n_cross):
            uu0 = (k + 0.6) / (n_cross + 0.2)
            uu1 = (k + 1.6) / (n_cross + 0.2)
            if uu1 > 1.0:
                break
            x0 = -half + uu0 * span
            x1 = -half + uu1 * span
            z0 = profile(uu0) + beam_r * 0.4
            z1 = profile(uu1) + clear + deck_th * 0.2
            d = Vector((x1 - x0, 0.0, z1 - z0))
            ob = mkcyl("Brace_%d_%d" % (i, k), beam_r * 0.34, d.length,
                       ((x0 + x1) * 0.5, yc, (z0 + z1) * 0.5),
                       mat=(mat_miao if mat_miao is not None else M))
            ob.rotation_mode = 'QUATERNION'
            ob.rotation_quaternion = d.to_track_quat('Z', 'Y')
            made[-1] = ob.name

    # ---- 两岸桥台（石）----
    for side in (-1, 1):
        ob = mkbox("Abutment_%d" % side, (2.6, width + 1.2, 2.8),
                   (side * (half + 1.1), 0.0, z + 2.8 * 0.5 - 1.5))
        made[-1] = ob.name

    # ---- 两侧栏杆：望柱 + 扶手 ----
    for side in (-1, 1):
        y = side * (width * 0.5 - 0.14)
        n_p = 15
        for i in range(n_p):
            u = i / (n_p - 1.0)
            x = -half + u * span
            zz = profile(u) + clear + deck_th
            mkbox("Post_%d_%d" % (side, i), (0.14, 0.14, rail_h),
                  (x, y, zz + rail_h * 0.5))
        for i in range(NS):
            x0, z0 = deck[i]
            x1, z1 = deck[i + 1]
            seg_len = ((x1 - x0) ** 2 + (z1 - z0) ** 2) ** 0.5
            ang = math.atan2(z1 - z0, x1 - x0)
            mid = ((x0 + x1) * 0.5, (z0 + z1) * 0.5)
            ob = mkbox("Rail_%d_%d" % (side, i),
                       (seg_len * 1.02, 0.11, 0.11),
                       (mid[0], y, mid[1] + rail_h),
                       (0.0, -math.degrees(ang), 0.0))
            made[-1] = ob.name

    print("HONGQIAO %s 构件数=%d 净跨=%.1fm 宽=%.1fm 拱矢=%.2fm "
          "肋对=%d 编织幅度=%.2fm（三节苗x3 / 五节苗x5）" % (
              name, len(made), span, width, rise, ribs, weave_amp))
    return made

# ================= 形制助手：反曲屋顶 =================
# LESSONS [025]：模型做不出反曲屋顶，只会做平板或悬浮条。
# 把"庑殿顶 + 反宇 + 起翘"编码成参数，模型只需给尺寸。
def curved_roof(name, width, depth, ridge_h=2.2, eave_h=0.0, overhang=0.55,
                corner_lift=0.9, curve=2.4, material=None, ridge_mat=None,
                tile_ridges=0, tile_w=0.30, tile_h=0.045,
                coll_target=None):
    """庑殿顶（四坡）反曲屋顶 —— 凹曲屋面 + 起翘檐角。

    **返回单个 mesh 对象**（屋面 + 正脊 + 垂脊 + 檐口板 已合并，
    两个材质槽：0=屋面材质, 1=脊/檐材质）。
    返回单对象是刻意的 —— 这样 `roof.location.z = 5.5` 会整体移动屋顶，
    模型不必知道内部结构（早期版本返回 dict，模型当对象用直接炸掉）。

    width/depth : 屋面（不含出檐）平面尺寸
    ridge_h     : 正脊的**绝对 z 高度**
    eave_h      : 檐口的**绝对 z 高度**（必须 <= ridge_h）
    overhang    : 出檐外挑
    corner_lift : 檐角起翘量（绝对长度，内部会按屋脊高度比例钳制）
    curve       : 反宇程度，>1 越大越凹
    tile_ridges : 瓦垄条数（0 = 不加）。LESSONS [042]：光有曲面时，
                  反宇曲率在渲染图上**读不出来**（两个评审一致说"像平直斜面"），
                  因为眼睛没有参照物。瓦垄沿坡向从脊走到檐，
                  **每条垄的走向本身就是屋面的剖面曲线**，
                  有了参照线，凹曲就一眼可辨。
    tile_w      : 瓦垄间距（米）
    tile_h      : 瓦垄凸起高度（米）
    """
    ridge_h = float(ridge_h)
    eave_h = float(eave_h)
    corner_lift = float(corner_lift)

    # LESSONS [037]：ridge_h/eave_h 是绝对高度，模型可能传反 —— 那屋顶就是真倒的。
    if ridge_h < eave_h:
        print("ROOF_FIX ridge_h(%.2f) < eave_h(%.2f)，已交换" % (ridge_h, eave_h))
        ridge_h, eave_h = eave_h, ridge_h
    rise = ridge_h - eave_h
    W0 = float(width)
    D0 = float(depth)
    # 太平时给一个下限，避免"平板屋顶"（中式屋顶举高一般 >= 跨度的 1/4）
    _min_rise = 0.28 * min(W0, D0)
    if rise < _min_rise:
        print("ROOF_FIX 举高 %.2fm 过平（跨度 %.2fx%.2f），已抬到 %.2fm"
              % (rise, W0, D0, _min_rise))
        ridge_h = eave_h + _min_rise
        rise = _min_rise
    # 起翘绝不能超过举高的一半，否则檐角高过屋脊 -> 看起来像翻过来的
    _max_lift = rise * 0.55
    if corner_lift > _max_lift:
        print("ROOF_FIX 起翘 %.2fm 超过举高的一半，已压到 %.2fm"
              % (corner_lift, _max_lift))
        corner_lift = _max_lift
    corner_lift = max(0.0, corner_lift)

    W = W0 + float(overhang) * 2
    D = D0 + float(overhang) * 2
    Rx = max(0.0, W * 0.5 - D * 0.5)
    halfD = D * 0.5
    if Rx < 1e-4:
        Rx = W * 0.18

    N = 24          # 沿脊方向分段
    M = 16          # 沿坡向分段

    def prof(t):
        """反宇曲线：t=0 脊, t=1 檐。

        LESSONS [035]：这里曾经写成
            eave_h + (ridge_h-eave_h) * (1 - (1-t)**curve)
        代入两端得 t=0 -> eave_h、t=1 -> ridge_h，**脊低檐高，整个屋面是倒的**。
        正确写法必须让 t=0 得 ridge_h、t=1 得 eave_h。
        dz/du 在 t=0 处大、t=1 处趋 0，即"脊部陡、檐口缓"，这才是反宇（凹曲面）。
        """
        t = max(0.0, min(1.0, t))
        return ridge_h - (ridge_h - eave_h) * (1.0 - (1.0 - t) ** curve)

    def corner_boost(x, y, t):
        """起翘：只在四角附近、且靠近檐口抬升。

        指数用 4 而不是 8 —— 8 太陡，抬升只在极角出现，檐口绝大部分是平的，
        看起来像"贴上去的四根翘条"而不是连续上翘的檐口。
        """
        if corner_lift <= 0.0:
            return 0.0
        ax = min(1.0, abs(x) / (W * 0.5))
        ay = min(1.0, abs(y) / (D * 0.5))
        return corner_lift * (ax ** 4) * (ay ** 4) * (t ** 1.5)

    def height(x, y):
        dx = max(0.0, abs(x) - Rx)
        t = min(1.0, max(abs(y), dx) / halfD)
        return prof(t) + corner_boost(x, y, t)

    V, F, FM = [], [], []          # verts, faces, per-face material index

    def add_quad_geo(pts, mi):
        i0 = len(V)
        V.extend(pts)
        F.append((i0, i0 + 1, i0 + 2, i0 + 3))
        FM.append(mi)

    # ---- 4 个坡面 ----
    def panel(pts_grid, mi, outward):
        """pts_grid 是 (M+1) x (N+1) 的点阵。

        绕序判据用**绝对规则：屋面必须朝上**（n.z > 0），而不是"外法线方向"启发式。
        后者在端面板 tv=0 退化行会失效，导致大面积法线朝下、渲染成"灰板"。
        """
        rows = []
        for j in range(M):
            row = []
            for i in range(N):
                a = pts_grid[j][i]
                b = pts_grid[j][i + 1]
                c = pts_grid[j + 1][i + 1]
                d = pts_grid[j + 1][i]
                n = (Vector(b) - Vector(a)).cross(Vector(d) - Vector(a))
                if n.z < 0:
                    quad = [a, d, c, b]        # 反绕序 -> 法线朝上
                else:
                    quad = [a, b, c, d]
                row.append(quad)
            rows.append(row)
        for j in range(M):
            for i in range(N):
                add_quad_geo(rows[j][i], mi)

    def front_edge(u, tv):
        # 必须用 * u，不能用 *(1 if u>=0 else -1)：
        # 后者会在 u=0 处把 x 从负值突变为正值，屋面网格在中轴线上折叠断裂。
        return ((Rx + (W * 0.5 - Rx) * tv) * u, -tv * halfD)

    def back_edge(u, tv):
        return ((Rx + (W * 0.5 - Rx) * tv) * u, tv * halfD)

    def end_edge(sign):
        def f(u, tv):
            return (sign * (Rx + (W * 0.5 - Rx) * tv), u * tv * halfD)
        return f

    for edge_fn, outward in (
        (front_edge, (0, -1, 0.35)),
        (back_edge, (0, 1, 0.35)),
        (end_edge(-1), (-1, 0, 0.35)),
        (end_edge(1), (1, 0, 0.35)),
    ):
        grid = []
        for j in range(M + 1):
            tv = j / M
            row = []
            for i in range(N + 1):
                u = -1.0 + 2.0 * i / N
                x, y = edge_fn(u, tv)
                row.append((x, y, height(x, y)))
            grid.append(row)
        panel(grid, 0, outward)

    # ---- 方木几何（正脊 / 垂脊 / 檐口板）----
    CUBE_FACES = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1),
                  (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]

    def add_box_geo(size, center, quat=None, mi=1):
        sx, sy, sz = size[0] * 0.5, size[1] * 0.5, size[2] * 0.5
        local = [(-sx, -sy, -sz), (-sx, -sy, sz), (-sx, sy, -sz), (-sx, sy, sz),
                 (sx, -sy, -sz), (sx, -sy, sz), (sx, sy, -sz), (sx, sy, sz)]
        c = Vector(center)
        pts = []
        for p in local:
            v = Vector(p)
            if quat is not None:
                v = quat @ v
            pts.append(tuple(c + v))
        i0 = len(V)
        V.extend(pts)
        for f in CUBE_FACES:
            F.append(tuple(i0 + k for k in f))
            FM.append(mi)

    def add_bar(p0, p1, thick, mi=1):
        a, b = Vector(p0), Vector(p1)
        d = b - a
        L = d.length
        if L < 1e-6:
            return
        q = d.to_track_quat('Z', 'Y')
        add_box_geo((thick, thick, L), (a + b) * 0.5, q, mi)

    # 正脊
    add_box_geo((Rx * 2 + 0.25, 0.30, 0.30), (0, 0, ridge_h + 0.15), None, 1)

    # 4 条垂脊：从脊端沿曲面下到檐角
    for p0, p1 in (((Rx, 0.0), (W * 0.5, -halfD)),
                   ((Rx, 0.0), (W * 0.5, halfD)),
                   ((-Rx, 0.0), (-W * 0.5, -halfD)),
                   ((-Rx, 0.0), (-W * 0.5, halfD))):
        segs = 10
        prev = None
        for k in range(segs + 1):
            t = k / segs
            x = p0[0] + (p1[0] - p0[0]) * t
            y = p0[1] + (p1[1] - p0[1]) * t
            cur = (x, y, height(x, y) + 0.06)
            if prev is not None:
                add_bar(prev, cur, 0.16, 1)
            prev = cur

    # ---- 瓦垄（筒瓦）：平行于坡向，在垂脊处裁断 ----
    # LESSONS [042]：这是让"反宇曲率可见"的关键。
    # 光有曲面时两个评审一致说"像平直斜面"——眼睛没有参照物。
    # 瓦垄沿坡向从脊走到檐，**每条垄的走向本身就是屋面的剖面曲线**，
    # 有了参照线，凹曲就一眼可辨。
    # 关键 1：垄线必须**贴合曲面**（每点 z 取 height(x,y)），
    #         若用直线插值，垄线自己就成了直线，参照物反而掩盖了曲率。
    # 关键 2：垄**平行于坡向**，不是扇形。扇形版本会让前坡最外垄与侧坡最外垄
    #         落在同一条垂脊线上，两套几何重叠 -> Z-fighting ->
    #         评审报"瓦垄在屋脊处衔接不连续"。
    #         正确做法：沿坡向走到垂脊就停（起点 t0 由几何算出）。
    if tile_ridges and tile_ridges > 0:
        _TW = max(0.05, float(tile_w))
        _TH = max(0.005, float(tile_h))
        _SEG = 16          # 每条垄沿坡向的段数
        _HALF = 5          # 每垄横截面采样点数（半圆）
        _hw = _TW * 0.40   # 垄半宽

        def _sweep(t0, path_fn, perp_fn):
            """沿坡向生成一条垄并铺面。t0 是坡向起点（0=脊，>0 表示被垂脊截断）。"""
            if t0 >= 0.985:
                return
            span = 1.0 - t0
            rows = []
            for i in range(_SEG + 1):
                t = t0 + span * i / _SEG
                cx, cy = path_fn(t)
                row = []
                for j in range(_HALF + 1):
                    s = -1.0 + 2.0 * j / _HALF
                    dx, dy = perp_fn(s)
                    px, py = cx + dx, cy + dy
                    pz = height(px, py)
                    bulge = math.sqrt(max(0.0, 1.0 - s * s))
                    row.append((px, py, pz + _TH * bulge))
                rows.append(row)
            for i in range(_SEG):
                for j in range(_HALF):
                    a = rows[i][j]
                    b = rows[i][j + 1]
                    c = rows[i + 1][j + 1]
                    d = rows[i + 1][j]
                    nrm = (Vector(b) - Vector(a)).cross(Vector(d) - Vector(a))
                    if nrm.z < 0:
                        add_quad_geo([a, d, c, b], 0)
                    else:
                        add_quad_geo([a, b, c, d], 0)

        # ---- 前坡 / 后坡：垄沿 y 走向（脊 -> 檐），x 固定 ----
        # 起点 t0 = (|x| - Rx) / (W/2 - Rx)：x 超出正脊半跨时，
        # 该垄在到达正脊之前就先碰上垂脊，必须在那里停。
        _n1 = max(2, int(round(W / _TW)))
        _span_x = max(1e-6, W * 0.5 - Rx)
        for _sgn in (-1.0, 1.0):
            for k in range(_n1):
                _x0 = -W * 0.5 + _TW * (k + 0.5)

                def _path(t, _sgn=_sgn, _x0=_x0):
                    return (_x0, _sgn * t * halfD)

                _t0 = max(0.0, (abs(_x0) - Rx) / _span_x)
                _sweep(_t0, _path, lambda s: (_hw * s, 0.0))

        # ---- 左坡 / 右坡：垄沿 x 走向（脊端 -> 檐角），y 固定 ----
        # 起点 t0 = |y| / halfD：靠近正脊端（y≈0）的垄已经到顶，
        # 靠檐边的垄（|y|→halfD）几乎立刻碰上垂脊。
        _n2 = max(2, int(round(D / _TW)))
        for _sx in (-1.0, 1.0):
            for k in range(_n2):
                _y0 = -halfD + _TW * (k + 0.5)

                def _path(t, _sx=_sx, _y0=_y0):
                    return (_sx * (Rx + (W * 0.5 - Rx) * t), _y0)

                _t0 = min(0.98, abs(_y0) / halfD)
                _sweep(_t0, _path, lambda s: (0.0, _hw * s))

    # 4 条檐口板：封住坡面下沿，消除"悬浮"感
    for p0, p1 in (((-W * 0.5, -halfD), (W * 0.5, -halfD)),
                   ((-W * 0.5, halfD), (W * 0.5, halfD)),
                   ((-W * 0.5, -halfD), (-W * 0.5, halfD)),
                   ((W * 0.5, -halfD), (W * 0.5, halfD))):
        add_bar((p0[0], p0[1], height(*p0)), (p1[0], p1[1], height(*p1)), 0.18, 1)

    me = bpy.data.meshes.new(name)
    me.from_pydata(V, [], F)
    me.update()
    ob = _link(bpy.data.objects.new(name, me))

    # 材质槽：0 = 屋面, 1 = 脊/檐
    if material is not None:
        me.materials.append(material)
    if ridge_mat is not None:
        me.materials.append(ridge_mat)
    elif material is not None:
        me.materials.append(material)
    for p, mi in zip(me.polygons, FM):
        p.material_index = min(mi, max(0, len(me.materials) - 1))

    if coll_target is not None:
        coll_target.objects.link(ob)
        bpy.context.scene.collection.objects.unlink(ob)

    # ---- 几何健全性自检 ----
    # (a) 法线朝上比例（LESSONS [030]）：折叠/绕序错了会渲染成"灰板"
    up = sum(1 for p in me.polygons if p.normal.z > 0.2)
    ratio = up / max(1, len(me.polygons))
    print("ROOF_CHECK faces=%d up=%d ratio=%.2f  %s" % (
        len(me.polygons), up, ratio,
        "OK" if ratio > 0.5 else "!! 法线大面积朝下，检查参数化"))

    # (b) 屋面朝向（LESSONS [035]）：必须在 z=0 处向檐口单调下降。
    #     之前用"每个 x 的最大 z"检查，对屋面倒置完全不敏感，漏判了翻转。
    #     正确做法：沿 +y 从脊走向檐口采样，z 必须单调不增。
    _zs = [height(0.0, halfD * k / 8.0) for k in range(9)]
    _mono = all(_zs[i] >= _zs[i + 1] - 1e-9 for i in range(len(_zs) - 1))
    _drop = _zs[0] - _zs[-1]
    print("ROOF_ORIENT profile=%s drop=%.2f  %s" % (
        [round(z, 3) for z in _zs], _drop,
        "OK(脊高檐低)" if (_mono and _drop > 0.05)
        else "!! 屋面倒置或过平：脊应高于檐"))

    # (c) 起翘不得高过屋脊（LESSONS [037]）。
    #     实测有调用传 corner_lift = ridge_h*0.5 = 3.64m，而举高只有 1.55m，
    #     四角翘到比屋脊高一倍多，看起来就像整个屋顶翻过来了。
    _corner_z = max(height(sx * W * 0.5, sy * halfD)
                    for sx in (-1, 1) for sy in (-1, 1))
    _ridge_z = max(height(0.0, 0.0), height(Rx, 0.0), height(-Rx, 0.0))
    print("ROOF_LIFT ridge_z=%.2f corner_z=%.2f  %s" % (
        _ridge_z, _corner_z,
        "OK(角低于脊)" if _corner_z < _ridge_z
        else "!! 檐角高过屋脊，看起来会像倒置"))
    return ob


def bevel(ob, width=0.03, segments=2):
    """加倒角修改器（不去掉锐利边缘是 critic 的高频扣分点）。"""
    if ob is None:
        return None
    try:
        m = ob.modifiers.new("Bevel", 'BEVEL')
        m.width = width
        m.segments = segments
        m.limit_method = 'ANGLE'
        return m
    except Exception:
        return None


def _reset_proc_nodes(m):
    """清掉**我们自己**加的程序化节点，让 wood_mat/stone_mat 幂等。

    LESSONS [028]：不能"删除除 BSDF 外的所有节点" ——
    Blender 删掉 Material Output 节点时会连带清空整棵树（实测 NODES_AFTER: []）。
    所以只删带 _proc_ 前缀的节点，Output 与 BSDF 一律不碰。
    """
    nt = m.node_tree
    b = next((n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    for n in list(nt.nodes):
        if n.name.startswith('_proc_'):
            try:
                nt.nodes.remove(n)
            except Exception:
                pass
    return nt, b


def wood_mat(name, base=(0.42, 0.24, 0.13), rough=0.62, grain=14.0):
    """带木纹的程序化材质（Noise -> 颜色/粗糙度 + Bump），避免纯色平涂。"""
    m = mat(name, base, rough)
    nt, b = _reset_proc_nodes(m)
    if b is None:
        return m
    base = list(base) + [0.0] * (3 - len(base))
    tex = nt.nodes.new('ShaderNodeTexNoise')
    tex.name = '_proc_tex'
    tex.inputs['Scale'].default_value = grain
    tex.inputs['Detail'].default_value = 6.0
    tex.location = (-700, 0)
    ramp = nt.nodes.new('ShaderNodeValToRGB')
    ramp.name = '_proc_ramp'
    ramp.location = (-480, 0)
    c0 = tuple(max(0.0, c * 0.55) for c in base)
    c1 = tuple(min(1.0, c * 1.35 + 0.04) for c in base)
    ramp.color_ramp.elements[0].position = 0.30
    ramp.color_ramp.elements[0].color = (*c0, 1.0)
    ramp.color_ramp.elements[1].position = 0.72
    ramp.color_ramp.elements[1].color = (*c1, 1.0)
    bump = nt.nodes.new('ShaderNodeBump')
    bump.name = '_proc_bump'
    bump.inputs['Strength'].default_value = 0.12
    bump.location = (-260, -260)
    nt.links.new(tex.outputs['Fac'], ramp.inputs['Fac'])
    nt.links.new(ramp.outputs['Color'], b.inputs['Base Color'])
    nt.links.new(tex.outputs['Fac'], bump.inputs['Height'])
    nt.links.new(bump.outputs['Normal'], b.inputs['Normal'])
    return m


def stone_mat(name, base=(0.56, 0.54, 0.50), rough=0.85, scale=9.0):
    """石材：Noise 驱动颜色变化 + Bump 凹凸。"""
    m = mat(name, base, rough)
    nt, b = _reset_proc_nodes(m)
    if b is None:
        return m
    base = list(base) + [0.0] * (3 - len(base))
    tex = nt.nodes.new('ShaderNodeTexNoise')
    tex.name = '_proc_tex'
    tex.inputs['Scale'].default_value = scale
    tex.inputs['Detail'].default_value = 8.0
    tex.location = (-700, 0)
    ramp = nt.nodes.new('ShaderNodeValToRGB')
    ramp.name = '_proc_ramp'
    ramp.location = (-480, 0)
    c0 = tuple(max(0.0, c * 0.72) for c in base)
    c1 = tuple(min(1.0, c * 1.18) for c in base)
    ramp.color_ramp.elements[0].color = (*c0, 1.0)
    ramp.color_ramp.elements[1].color = (*c1, 1.0)
    bump = nt.nodes.new('ShaderNodeBump')
    bump.name = '_proc_bump'
    bump.inputs['Strength'].default_value = 0.25
    bump.location = (-260, -260)
    nt.links.new(tex.outputs['Fac'], ramp.inputs['Fac'])
    nt.links.new(ramp.outputs['Color'], b.inputs['Base Color'])
    nt.links.new(tex.outputs['Fac'], bump.inputs['Height'])
    nt.links.new(bump.outputs['Normal'], b.inputs['Normal'])
    return m


def area_light(name, loc, energy=800.0, size=6.0, target=(0, 0, 2.0)):
    ld = bpy.data.lights.new(name, 'AREA')
    ld.energy = energy
    ld.size = size
    ob = bpy.data.objects.new(name, ld)
    ob.location = loc
    d = Vector(target) - Vector(loc)
    ob.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    bpy.context.scene.collection.objects.link(ob)
    return ob


def setup(engine='BLENDER_EEVEE', res=(1200, 900), samples=32, bg=(0.05, 0.06, 0.08)):
    # 容错：模型可能把 samples 传进 res 位，或把 bg 传进 samples 位
    if isinstance(res, (int, float)):
        samples, res = int(res), (1200, 900)
    if not isinstance(res, (tuple, list)) or len(res) < 2:
        res = (1200, 900)
    if isinstance(bg, (int, float)):
        bg = (0.05, 0.06, 0.08)
    elif not isinstance(bg, (tuple, list)) or len(bg) < 3:
        bg = (0.05, 0.06, 0.08)
    if isinstance(samples, (tuple, list)):
        samples = 32
    sc = bpy.context.scene
    if engine not in ('BLENDER_EEVEE', 'CYCLES', 'BLENDER_WORKBENCH'):
        engine = 'BLENDER_EEVEE'
    sc.render.engine = engine
    if engine == 'BLENDER_EEVEE':
        try:
            sc.eevee.taa_render_samples = max(1, int(samples))
        except Exception:
            pass
        # LESSONS [063]：EEVEE 默认 `use_animated_seed=True`，
        # 每帧换随机种子 → **同一场景两次渲染的 PNG 哈希不同**。
        # 后果：跨轮"同机位对照"根本不是同一张图，
        # 视觉评审的结论因此有运行间方差（实测同一模型
        # 4/4 PASS 与 2/4 FAIL 都出现过）。必须钉死种子。
        for _k, _v in (("use_animated_seed", False), ("seed", 0)):
            try:
                setattr(sc.eevee, _k, _v)
            except Exception:
                pass
    else:
        try:
            sc.cycles.samples = max(1, int(samples))
        except Exception:
            pass
    sc.render.resolution_x, sc.render.resolution_y = int(res[0]), int(res[1])
    # 大分辨率 + CYCLES 在这台机器上太慢，收敛到可接受范围
    if engine == 'CYCLES':
        sc.render.resolution_x = min(sc.render.resolution_x, 1024)
        sc.render.resolution_y = min(sc.render.resolution_y, 768)
        try:
            sc.cycles.samples = min(int(samples), 48)
        except Exception:
            pass
    sc.render.image_settings.file_format = 'PNG'
    sc.view_settings.view_transform = 'Standard'
    w = bpy.data.worlds.get("World") or bpy.data.worlds.new("World")
    w.use_nodes = True
    bgn = next((n for n in w.node_tree.nodes if n.type == 'BACKGROUND'), None)
    if bgn:
        bgn.inputs[0].default_value = (bg[0], bg[1], bg[2], 1.0)
        bgn.inputs[1].default_value = 1.4
    sc.world = w
    if sc.camera is None:
        cd = bpy.data.cameras.new("Camera")
        cam = bpy.data.objects.new("Camera", cd)
        sc.collection.objects.link(cam)
        sc.camera = cam
    # 太阳强度标定（LESSONS [031]）：Blender 漫反射 = albedo/π × 辐照度 × N·L。
    # 能量 3.0 时 0.25 反射率表面只读出 ~0.42 sRGB，整幅图像是灰的，
    # critic 会扣"材质像默认着色器"。实测 8.0~10.0 才有清晰色相且不过曝。
    sun = bpy.data.lights.new("Sun", 'SUN')
    sun.energy = 6.0
    sun.angle = math.radians(2.0)          # 稍柔，避免硬边阴影
    so = bpy.data.objects.new("Sun", sun)
    so.location = (6, -8, 12)
    so.rotation_euler = (math.radians(50), math.radians(8), math.radians(30))
    sc.collection.objects.link(so)

    # 补光：暗部不要死黑，否则 critic 判"材质无质感"
    fill = bpy.data.lights.new("Fill", 'AREA')
    fill.energy = 900.0
    fill.size = 10.0
    fo = bpy.data.objects.new("Fill", fill)
    fo.location = (-7.0, -9.0, 7.0)
    d = Vector((0.0, 0.0, 2.0)) - Vector(fo.location)
    fo.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    sc.collection.objects.link(fo)
    return sc

def stats(label=""):
    # LESSONS [023]：matrix_world 是惰性的，新建/移动对象后不 update 会读到旧变换，
    # 导致包围盒完全错误（实测 Roof 的 translation 更新前是 (0,0,0)）。
    bpy.context.view_layer.update()
    sc = bpy.context.scene
    ms = [o for o in sc.objects if o.type == 'MESH']
    nv = sum(len(o.data.vertices) for o in ms)
    if ms:
        pts = [o.matrix_world @ Vector(v) for o in ms for v in o.bound_box]
        lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
        hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
        d = hi - lo
        print("%s构件=%d 顶点=%d 包围盒=%.2f x %.2f x %.2f m" % (label, len(ms), nv, d.x, d.y, d.z))
    else:
        print("%s构件=0" % label)
'''
# LESSONS [016]：模型生成的相机常常框不住模型（尤其场景里残留上一轮的相机）。
# 取景是工程约束，不该交给模型猜 —— 每次渲染前由 harness 强制重设。
FRAME_SNIPPET = r'''
import math as _m
import re as _re
from mathutils import Vector as _V
# LESSONS [019]：地面/背景板会把包围盒撑爆，导致相机拉太远、主体缩成一点。
# 判定为"背景物件"：名字像地面，或极扁且面积远大于其它物体。
_BG_NAME = _re.compile(r'(ground|floor|plane|terrain|backdrop|stage|平台|地面)', _re.I)
def _is_backdrop(_ob, _others_max):
    if _BG_NAME.search(_ob.name):
        return True
    _c = [_ob.matrix_world @ _V(v) for v in _ob.bound_box]
    _ex = max(p.x for p in _c) - min(p.x for p in _c)
    _ey = max(p.y for p in _c) - min(p.y for p in _c)
    _ez = max(p.z for p in _c) - min(p.z for p in _c)
    _flat = _ez <= max(_ex, _ey) * 0.03
    _huge = max(_ex, _ey) >= _others_max * 2.5
    return _flat and _huge

def _frame_camera(margin=1.28, lens=50.0, direction=(0.9, -1.25, 0.62)):
    # LESSONS [023]：必须先求值依赖图，否则 matrix_world / bound_box 是旧值，
    # 取景会算错（实测偏差可达一倍以上）。
    bpy.context.view_layer.update()
    _sc = bpy.context.scene
    _meshes = [o for o in _sc.objects if o.type == 'MESH' and not o.hide_render]
    if not _meshes:
        print("FRAME_SKIP no mesh")
        return
    _spans = []
    for _o in _meshes:
        _c = [_o.matrix_world @ _V(v) for v in _o.bound_box]
        _spans.append(max(max(p.x for p in _c) - min(p.x for p in _c),
                          max(p.y for p in _c) - min(p.y for p in _c)))
    _others_max = max(sorted(_spans)[:-1]) if len(_spans) > 1 else _spans[0]
    _keep = [_o for _o in _meshes if not _is_backdrop(_o, _others_max)]
    if not _keep:
        _keep = _meshes
    print("FRAME_OBJECTS kept=%d/%d excluded=%s" % (
        len(_keep), len(_meshes),
        [o.name for o in _meshes if o not in _keep]))
    _lo = _V((float("inf"),) * 3)
    _hi = _V((float("-inf"),) * 3)
    _found = False
    for _ob in _keep:
        for _c in _ob.bound_box:
            _p = _ob.matrix_world @ _V(_c)
            _lo = _V((min(_lo.x, _p.x), min(_lo.y, _p.y), min(_lo.z, _p.z)))
            _hi = _V((max(_hi.x, _p.x), max(_hi.y, _p.y), max(_hi.z, _p.z)))
            _found = True
    if not _found:
        print("FRAME_SKIP no mesh")
    else:
        _ctr = (_lo + _hi) * 0.5
        _rad = max((_hi - _lo).length * 0.5, 1e-4)
        _cam = _sc.camera
        if _cam is None:
            _cd = bpy.data.cameras.new("Camera")
            _cam = bpy.data.objects.new("Camera", _cd)
            _sc.collection.objects.link(_cam)
            _sc.camera = _cam
        _cam.data.lens = lens
        _cam.data.type = 'PERSP'
        _sw = _cam.data.sensor_width
        _ar = _sc.render.resolution_x / max(_sc.render.resolution_y, 1)
        _sh = _sw / _ar if _ar >= 1.0 else _sw
        _tan_x = (_sw / (2 * lens))          # 半宽 / 焦距
        _tan_y = (_sh / (2 * lens))          # 半高 / 焦距
        _fov = 2 * _m.atan(min(_tan_x, _tan_y))

        # 收集所有角点（世界坐标）
        _corners = []
        for _ob in _keep:
            for _c in _ob.bound_box:
                _corners.append(_ob.matrix_world @ _V(_c))

        # LESSONS [033]：用包围球半径定位会浪费大量画面（又高又窄的建筑尤其明显），
        # 主体只占画面一小块。改成**包围盒精确适配**：
        # 迭代几次，把相机拉近/推远直到所有角点都落在画面内且留白 margin。
        _d = _V(direction).normalized()
        _dist = _rad / _m.tan(min(_tan_x, _tan_y)) * margin
        for _it in range(8):
            _cam.location = _ctr + _d * _dist
            _cam.rotation_euler = (_ctr - _cam.location).to_track_quat('-Z', 'Y').to_euler()
            bpy.context.view_layer.update()
            _inv = _cam.matrix_world.inverted()
            _need = 0.0
            for _p in _corners:
                _q = _inv @ _p
                _depth = max(-_q.z, 1e-3)      # 相机前方深度
                # 边距是**乘数**不是除数：主体要留 margin 的余量，
                # 就要求深度 >= margin * |q.x| / tan_x。
                # 写成 / (tan_x * margin) 会让要求深度**变小**，
                # 等于放宽取景，主体可以溢出画面（实测 under 图左侧触边）。
                _need = max(_need,
                            abs(_q.x) * margin / _tan_x - _depth,
                            abs(_q.y) * margin / _tan_y - _depth)
            if abs(_need) < 1e-3:
                break
            _dist = max(0.05, _dist + _need)
        # 让主体中心落在画面中心（沿视线方向微调不影响距离）
        print("FRAMED center=%s radius=%.3f dist=%.3f fov=%.1fdeg iters=%d" % (
            tuple(round(v, 3) for v in _ctr), _rad, _dist, _m.degrees(_fov), _it + 1))
_frame_camera()
'''

# 固定证据机位（照 blender-visual-craft skill 的 review.md 规范）
# LESSONS [036]：critic 只看单视图无法判断三维结构；且必须区分"形体问题"与"材质问题"。
# LESSONS [038]：跨轮必须固定相机矩阵，否则自动重框会让两轮图不可严格对照
#               （skill 明确警告："不能直接把两张自动取景图当作严格对照"）。
# 故每轮产出：hero 透视 + front/right/back 正交 + clay 灰模，并回传 CAM_STATE。
VIEW_SETUP_SNIPPET = r'''
import json as _json
import math as _m2
from mathutils import Vector as _V2
_KIND = "{kind}"
_CLAY = {clay}
_LOCK = {lock}

def _bounds():
    bpy.context.view_layer.update()
    _ms = [o for o in bpy.context.scene.objects
           if o.type == 'MESH' and not o.hide_render]
    _pts = []
    for _o in _ms:
        for _c in _o.bound_box:
            _pts.append(_o.matrix_world @ _V2(_c))
    if not _pts:
        return _V2((0, 0, 0)), _V2((1, 1, 1)), _pts
    _lo = _V2((min(p.x for p in _pts), min(p.y for p in _pts), min(p.z for p in _pts)))
    _hi = _V2((max(p.x for p in _pts), max(p.y for p in _pts), max(p.z for p in _pts)))
    return _lo, _hi, _pts

_lo, _hi, _pts = _bounds()
_ctr = (_lo + _hi) * 0.5
_size = _hi - _lo
_extent = max(_size.length, 0.1)
_sc = bpy.context.scene
_cam = _sc.camera
if _cam is None:
    _cd = bpy.data.cameras.new("Camera")
    _cam = bpy.data.objects.new("Camera", _cd)
    _sc.collection.objects.link(_cam)
    _sc.camera = _cam

_DIRS = {{
    "front": _V2((0, -1, 0)),
    "right": _V2((1, 0, 0)),
    "back":  _V2((0, 1, 0)),
    "left":  _V2((-1, 0, 0)),
    "top":   _V2((0, 0, 1)),
}}

_locked = False
if _LOCK and _KIND in _LOCK:
    _L = _LOCK[_KIND]
    _cam.location = tuple(_L["loc"])
    _cam.rotation_euler = tuple(_L["rot"])
    if _L.get("type") == "ORTHO":
        _cam.data.type = 'ORTHO'
        _cam.data.ortho_scale = _L["ortho"]
    else:
        _cam.data.type = 'PERSP'
        _cam.data.lens = _L["lens"]
    if _L.get("res"):
        _sc.render.resolution_x, _sc.render.resolution_y = _L["res"]
    _cam.data.clip_start = 0.001
    _cam.data.clip_end = _extent * 10
    _locked = True
    print("CAM_LOCKED %s" % _KIND)

if not _locked:
    if _KIND == "detail":
        # 拱顶局部大样：只框跨中一小段，正交 3/4 视角。
        # 理由：别压咬合是**亚米级**的局部细节，在整桥 900px 的画面里
        # 根本读不出来（视觉评审反复判"未能观察到两根梁互相别压咬合"）。
        # 这正是建筑做法图里"节点大样"的作用。
        _cx = _ctr.x
        _half_x = _size.x * 0.20
        _sel = [p for p in _pts if abs(p.x - _cx) <= _half_x] or _pts
        _lo2 = _V2((min(p.x for p in _sel), min(p.y for p in _sel),
                    min(p.z for p in _sel)))
        _hi2 = _V2((max(p.x for p in _sel), max(p.y for p in _sel),
                    max(p.z for p in _sel)))
        _c2 = (_lo2 + _hi2) * 0.5
        _cam.data.type = 'ORTHO'
        _dirv = _V2((0.55, -1.0, 0.30)).normalized()
        _cam.location = _c2 + _dirv * _extent * 2.0
        _cam.rotation_euler = (_c2 - _cam.location).to_track_quat('-Z', 'Y').to_euler()
        _rot = _cam.rotation_euler.to_matrix()
        _right, _up = _rot.col[0], _rot.col[1]
        _xx = [_right.dot(p - _c2) for p in _sel]
        _yy = [_up.dot(p - _c2) for p in _sel]
        _rx = _sc.render.resolution_x or 1
        _ry = _sc.render.resolution_y or 1
        _need_w = max(_xx) - min(_xx)
        _need_h = (max(_yy) - min(_yy)) * (_rx / float(_ry))
        _cam.data.ortho_scale = max(_need_w, _need_h) * 1.35
        _cam.data.clip_start = 0.001
        _cam.data.clip_end = _extent * 10
        print("VIEW detail (拱顶局部大样, ortho=%.2f)" % _cam.data.ortho_scale)
    elif _KIND == "under":
        # 仰视机位：从桥下**侧下方**看拱底。
        # 《清明上河图》里船夫仰望虹桥木构 —— 这也是唯一能看清
        # **三维编织**的角度：正交侧视里各肋完全重叠，只剩两条折线，
        # 视觉评审因此判"呈平行双层木梁，未见 X 形交叉"。
        # 相机压到接近起拱线的高度并斜看拱底，
        # 斜跨的横向苗与纵向拱肋的交叉才成菱形网格。
        _cam.data.type = 'PERSP'
        _cam.data.lens = 20.0
        _target = _V2((_ctr.x, _ctr.y, _ctr.z + _size.z * 0.10))
        _off = _V2((-_extent * 0.22, -_extent * 0.46,
                    _lo.z + _size.z * 0.16 - _target.z))
        _dirv = _off.normalized()
        # 自动取景：这个机位不像正交那样有精确框选，
        # 苗一斜跨场景就变宽，会把画面裁掉（实测 under 图左右触边）。
        # 但**只退不进**：若允许拉近，取景循环会把相机推到包围盒之外，
        # 构图垮掉（实测 dist 从 15 涨到 34，桥面反而占满画面）。
        _tan_x = _cam.data.sensor_width / (2.0 * _cam.data.lens)
        _ar = _sc.render.resolution_x / max(_sc.render.resolution_y, 1)
        _sh = (_cam.data.sensor_width / _ar) if _ar >= 1.0 else _cam.data.sensor_width
        _tan_y = _sh / (2.0 * _cam.data.lens)
        _dist0 = _off.length
        _dist = _dist0
        for _it in range(10):
            _cam.location = _target + _dirv * _dist
            _cam.rotation_euler = (_target - _cam.location).to_track_quat('-Z', 'Y').to_euler()
            bpy.context.view_layer.update()
            _inv = _cam.matrix_world.inverted()
            _need = 0.0
            for _p in _pts:
                _q = _inv @ _p
                _depth = max(-_q.z, 1e-3)
                _need = max(_need,
                            abs(_q.x) * 1.20 / _tan_x - _depth,
                            abs(_q.y) * 1.20 / _tan_y - _depth)
            if _need <= 1e-3:
                break
            # _need 是"还需要再退多远"，必须**累加**到当前距离上，
            # 不能从 dist0 重算（那样每次迭代都把已退的距离丢掉）。
            _dist = max(_dist0, _dist + _need * 1.05)
        _cam.data.clip_start = 0.001
        _cam.data.clip_end = _extent * 10
        print("VIEW under (侧下方仰视拱底, dist=%.2f)" % _dist)
    elif _KIND in _DIRS:
        _cam.data.type = 'ORTHO'
        _cam.location = _ctr + _DIRS[_KIND] * _extent * 2.0
        _cam.rotation_euler = (_ctr - _cam.location).to_track_quat('-Z', 'Y').to_euler()
        # 精确正交框选：角点投影到相机 right/up 基向量
        _rot = _cam.rotation_euler.to_matrix()
        _right, _up = _rot.col[0], _rot.col[1]
        _xx = [_right.dot(p - _ctr) for p in _pts]
        _yy = [_up.dot(p - _ctr) for p in _pts]
        # Blender 的 ortho_scale 映射到渲染的**长边**（本项目横图 = x），
        # 短边的可视范围 = ortho_scale * (ry / rx)。
        # 所以竖向需求必须先换算成 ortho_scale 的需求：h * (rx / ry)。
        # 早前直接写 max(w, h)，横图上会把竖向裁掉
        # （实测：虹桥 right 视图 ortho=10.67，短边只显示 7.1m，
        #   而桥高 8.43m —— 被裁，视觉评审独立指出"right 视图被裁切"）。
        _rx = _sc.render.resolution_x or 1
        _ry = _sc.render.resolution_y or 1
        _need_w = max(_xx) - min(_xx)
        _need_h = (max(_yy) - min(_yy)) * (_rx / float(_ry))
        _cam.data.ortho_scale = max(_need_w, _need_h) * 1.16
        _cam.data.clip_start = 0.001
        _cam.data.clip_end = _extent * 10
        print("VIEW %s ortho scale=%.2f (需宽 %.2f 需高 %.2f, rx/ry=%.2f)" % (
            _KIND, _cam.data.ortho_scale, _need_w, _need_h, _rx / float(_ry)))
    else:
        _cam.data.type = 'PERSP'
        print("VIEW persp")

# ---- clay 灰模：只留形体，排除材质/光照干扰 ----
if _CLAY:
    _sc.render.engine = 'BLENDER_WORKBENCH'
    _sc.render.use_compositing = False
    _sc.display.shading.light = 'STUDIO'
    # 灰模用**按物体随机着色**，不是单一灰。
    # 单色灰模把几百根构件刷成一片，密集的编织网格全糊在一起
    # （视觉评审原话："彩陶渲染图细节显示结构过于简化和平滑"）。
    # 随机着色仍是"无材质无灯光"的纯形体证据，但体系分得开。
    _sc.display.shading.color_type = 'RANDOM'
    _sc.display.shading.single_color = (0.55, 0.55, 0.55)
    # 正交顶视会出阴影条带故关掉；但透视灰模需要阴影才看得出形体起伏
    # （实测全关后 StdDev 只有 11，形体读不出来）
    _sc.display.shading.show_shadows = (_KIND not in ("top",))
    _sc.display.shading.show_cavity = True
    _sc.display.shading.cavity_type = 'BOTH'
    _sc.display.shading.background_type = 'WORLD'
    if _sc.world is None:
        _sc.world = bpy.data.worlds.new('ClayWorld')
    _sc.world.color = (0.12, 0.12, 0.12)
    print("CLAY workbench")
else:
    # LESSONS [034]：模型常把世界背景设得很亮，Standard 下冲成一片白，主体"灰蒙蒙"
    try:
        _w = _sc.world
        if _w and _w.use_nodes:
            _bg = next((n for n in _w.node_tree.nodes if n.type == 'BACKGROUND'), None)
            if _bg:
                _c = list(_bg.inputs[0].default_value)[:3]
                _mx = max(_c)
                if _mx > 0.32:
                    _k = 0.32 / _mx
                    _bg.inputs[0].default_value = (_c[0]*_k, _c[1]*_k, _c[2]*_k, 1.0)
                    print("BG_CLAMPED -> %s" % (tuple(round(v*_k, 3) for v in _c),))
    except Exception:
        pass

_sc.render.filepath = r"{path}"
_sc.render.image_settings.file_format = 'PNG'

# 回传相机状态，供后续轮次锁定复用
# ortho 只对正交相机有意义；PERSP 记 0，避免把默认值 6.0 当成有效参数误导排查
print("CAM_STATE " + _json.dumps({{
    "kind": _KIND,
    "loc": [round(v, 6) for v in _cam.location],
    "rot": [round(v, 6) for v in _cam.rotation_euler],
    "type": _cam.data.type,
    "lens": round(_cam.data.lens, 6),
    "ortho": round(_cam.data.ortho_scale, 6) if _cam.data.type == 'ORTHO' else 0.0,
    "res": [_sc.render.resolution_x, _sc.render.resolution_y],
}}, ensure_ascii=False))
'''


# ---------------------------------------------------------------- provider
def load_provider(alias: str) -> tuple[str, str, str]:
    """从本机 opencode 配置读取 (base_url, api_key, model)。不回显密钥。"""
    if not os.path.exists(OPENCODE_CFG):
        raise FileNotFoundError(f"找不到 {OPENCODE_CFG}")
    with open(OPENCODE_CFG, encoding="utf-8") as f:
        cfg = json.load(f)

    spec = PROVIDERS[alias]
    pname = spec["provider"]
    p = cfg.get("provider", {}).get(pname)
    if not p:
        raise KeyError(f"配置里没有 provider `{pname}`，可选: {list(cfg.get('provider', {}))}")

    opts = p.get("options", {})
    base_url = opts.get("baseURL") or opts.get("base_url")
    api_key = opts.get("apiKey") or opts.get("api_key")
    if not base_url or not api_key:
        raise KeyError(f"provider `{pname}` 缺少 baseURL/apiKey")

    model = spec["model"]
    available = list((p.get("models") or {}).keys())
    if available and model not in available:
        model = available[0]

    # 陷阱（LESSONS [014]）：Anthropic SDK 会在 base_url 后自动拼 "/v1/messages"，
    # 而 opencode 配置里的 baseURL 已带 /v1，直接传会得到 /v1/v1/messages -> 404。
    # 必须剥掉尾部 /v1。
    base_url = re.sub(r"/v1/?$", "", base_url.rstrip("/"))
    return base_url, api_key, model


def make_client(base_url: str, api_key: str):
    from anthropic import Anthropic
    return Anthropic(base_url=base_url, api_key=api_key, timeout=300.0, max_retries=2)


# ---------------------------------------------------------------- blender
class Session:
    def __init__(self):
        self.c = BlenderMCP(timeout=180)
        # 跨轮固定的检查相机（LESSONS [038]）：首轮自动取景后记录，
        # 后续轮原样复用 —— 否则每轮重框会让两轮的图不可严格对照。
        self.cam_lock: dict | None = None
        self.lock_size: tuple | None = None      # 锁定时模型的包围盒尺寸
        self.overflow_note: str | None = None    # 本轮机位溢出/裁切的提示

    def connect(self):
        self.c.connect()
        info = self.c._send({"type": "get_addon_info", "params": {}})
        return info.get("result", {})

    def run(self, code: str) -> dict:
        blocked = check_code_safety(code)
        if blocked:
            return {"status": "blocked", "message": blocked}

        # LESSONS [045]：增量修改。模型可在代码开头写
        #     KEEP = ["构件前缀", ...]
        # harness 提取它并注入 _KEEP，clear_scene() 随即只删除保留集合之外的构件。
        keep = self._parse_keep(code)
        if keep is not None:
            print("  [keep] 增量模式：保留 %d 项 -> %s"
                  % (len(keep), ", ".join(keep[:12])
                     + (" ..." if len(keep) > 12 else "")))

        # LESSONS [015]：addon 用 exec(code, {"bpy": bpy}) 执行，命名空间里没有 __name__，
        # 而 builtins 模块字典里有 __name__='builtins'，导致模型常写的
        #     if __name__ == "__main__": main()
        # 守卫为 False，整个脚本静默不执行却返回 success。
        # 注入 __name__ 让守卫成立。
        # 注入安全助手库（LESSONS [022]）—— 模型可直接调用 box/cyl/prism/beam/mat/setup/stats
        code = ("__name__ = '__main__'\n"
                + "_KEEP = %r\n" % (keep,)
                + PRELUDE + "\n# ---- 用户代码 ----\n" + code)
        r = self.c.execute_code(code)

        # 后置校验：exec 成功 ≠ 场景有东西。空场景必须当失败报回去。
        if r.get("status") == "success":
            n = self.mesh_count()
            if n == 0:
                return {"status": "error", "message":
                        "代码执行成功但场景里没有任何 MESH 对象。"
                        "很可能你把建模逻辑包进了函数却没有调用，"
                        "或用了 if __name__ == '__main__' 守卫。"
                        "请确保脚本顶层直接执行建模代码。"}
            r.setdefault("result", {})["mesh_count"] = n
        return r

    @staticmethod
    def _parse_keep(code: str) -> list[str] | None:
        """从模型代码里提取 KEEP = [...] 增量声明。"""
        m = re.search(r"^\s*KEEP\s*=\s*\[(.*?)\]", code, re.S | re.M)
        if not m:
            return None
        items = re.findall(r"['\"]([^'\"]+)['\"]", m.group(1))
        return items or None

    def object_names(self) -> list[str]:
        """当前场景的构件名（供模型决定增量时保留哪些）。"""
        r = self.c.execute_code(
            "import bpy\n"
            "print('OBJNAMES ' + '|'.join(sorted("
            "o.name for o in bpy.context.scene.objects if o.type == 'MESH')))\n")
        out = str(r.get("result", {}).get("result", ""))
        m = re.search(r"OBJNAMES\s*(.*)", out)
        if not m:
            return []
        return [x for x in m.group(1).split("|") if x]

    # ---------------- 快照 / 回滚（LESSONS [046]）----------------
    def snapshot(self, path: str) -> str | None:
        """把当前场景存成 .blend 快照。

        用 save_as_mainfile(copy=True) —— copy=True 只另存一份，
        **不改变**当前会话打开的文件，也就不会影响 MCP 通道。
        """
        code = (
            "import bpy, os\n"
            "_p = r'%s'\n"
            "os.makedirs(os.path.dirname(_p), exist_ok=True)\n"
            "bpy.ops.wm.save_as_mainfile(filepath=_p, copy=True)\n"
            "print('SNAPSHOT ' + _p)\n"
        ) % path.replace("\\", "\\\\")
        r = self.c.execute_code(code)
        if r.get("status") != "success":
            print("  [snap] 失败:", str(r.get("message"))[:200])
            return None
        print("  [snap] 已存快照 %s" % os.path.basename(path))
        return path if os.path.exists(path) else None

    def restore(self, path: str) -> bool:
        """从 .blend 快照恢复场景。

        **不用** bpy.ops.wm.open_mainfile —— 那会整体重载文件，
        有重置插件状态的风险（LESSONS [002] 同样禁掉了 read_homefile）。
        改用 bpy.data.libraries.load 把对象追加进当前场景，
        只动数据不动会话。
        """
        if not os.path.exists(path):
            print("  [restore] 快照不存在:", path)
            return False
        code = (
            "import bpy\n"
            "_p = r'__PATH__'\n"
            "for _o in list(bpy.data.objects):\n"
            "    bpy.data.objects.remove(_o, do_unlink=True)\n"
            "with bpy.data.libraries.load(_p, link=False) as (_src, _dst):\n"
            "    _dst.objects = _src.objects\n"
            "_sc = bpy.context.scene.collection\n"
            "for _o in bpy.data.objects:\n"
            "    if _o.name not in _sc.objects:\n"
            "        _sc.objects.link(_o)\n"
            "bpy.context.view_layer.update()\n"
            "_n = sum(1 for _o in _sc.objects if _o.type == 'MESH')\n"
            "print('RESTORED ' + str(_n))\n"
        ).replace("__PATH__", path.replace("\\", "\\\\"))
        r = self.c.execute_code(code)
        if r.get("status") != "success":
            print("  [restore] 失败:", str(r.get("message"))[:200])
            return False
        out = str(r.get("result", {}).get("result", ""))
        m = re.search(r"RESTORED\s+(\d+)", out)
        n = int(m.group(1)) if m else -1
        print("  [restore] 已恢复 %d 个 MESH 构件" % n)
        return n > 0

    def mesh_count(self) -> int:
        r = self.c.execute_code(
            "import bpy\nprint('MESH_COUNT', sum(1 for o in bpy.context.scene.objects "
            "if o.type == 'MESH'))\n")
        out = str(r.get("result", {}).get("result", ""))
        m = re.search(r"MESH_COUNT\s+(\d+)", out)
        return int(m.group(1)) if m else -1

    def scene_bbox(self) -> str:
        """量取场景真实包围盒，作为硬数据喂给 critic（比看图估尺寸可靠）。"""
        return self.scene_size_str()

    def scene_size(self) -> tuple[float, float, float] | None:
        """量取包围盒尺寸 (宽, 深, 高)。"""
        code = (
            "import bpy\n"
            "from mathutils import Vector as _Vb\n"
            "bpy.context.view_layer.update()\n"
            "_ms = [o for o in bpy.context.scene.objects if o.type=='MESH' and not o.hide_render]\n"
            "_lo = _Vb((float('inf'),)*3); _hi = _Vb((float('-inf'),)*3)\n"
            "for _o in _ms:\n"
            "    for _c in _o.bound_box:\n"
            "        _p = _o.matrix_world @ _Vb(_c)\n"
            "        _lo = _Vb((min(_lo.x,_p.x),min(_lo.y,_p.y),min(_lo.z,_p.z)))\n"
            "        _hi = _Vb((max(_hi.x,_p.x),max(_hi.y,_p.y),max(_hi.z,_p.z)))\n"
            "_d = _hi - _lo\n"
            "print('BBOX %.4f %.4f %.4f ZMIN %.4f ZMAX %.4f' % "
            "(_d.x,_d.y,_d.z,_lo.z,_hi.z))\n"
        )
        r = self.c.execute_code(code)
        out = str(r.get("result", {}).get("result", ""))
        m = re.search(
            r"BBOX\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+ZMIN\s+([-\d.]+)\s+ZMAX\s+([-\d.]+)",
            out)
        if not m:
            return None
        return (float(m.group(1)), float(m.group(2)), float(m.group(3)))

    def scene_size_str(self) -> str:
        s = self.scene_size()
        if s is None:
            return "未知"
        return f"宽 {s[0]:.2f}m × 深 {s[1]:.2f}m × 高 {s[2]:.2f}m"

    def component_dims(self) -> list[tuple[str, int, float, float, float]]:
        """按构件族（对象名 '_' 前的部分）量取各自尺寸。

        动机（LESSONS [043]）：只把"整体包围盒"喂给 critic 时，
        它无法分辨哪个数字属于哪个构件 —— 实测它连续三次把
        **屋檐出挑的 5.26m** 当成"基座深度"判 FAIL，
        而基座实测精确是 4.00m。
        分族给出尺寸后，"基座是否 8×4×3"才有唯一答案。
        """
        code = (
            "import bpy\n"
            "from mathutils import Vector as _Vb\n"
            "bpy.context.view_layer.update()\n"
            "_fams = {}\n"
            "for _o in bpy.context.scene.objects:\n"
            "    if _o.type != 'MESH' or _o.hide_render:\n"
            "        continue\n"
            "    _k = _o.name.split('_')[0] or _o.name\n"
            "    _fams.setdefault(_k, []).append(_o)\n"
            "for _k, _objs in sorted(_fams.items()):\n"
            "    _pts = [_o.matrix_world @ _Vb(_c) for _o in _objs for _c in _o.bound_box]\n"
            "    if not _pts:\n"
            "        continue\n"
            "    print('FAM %s %d %.3f %.3f %.3f' % (_k, len(_objs),\n"
            "        max(p.x for p in _pts)-min(p.x for p in _pts),\n"
            "        max(p.y for p in _pts)-min(p.y for p in _pts),\n"
            "        max(p.z for p in _pts)-min(p.z for p in _pts)))\n"
        )
        r = self.c.execute_code(code)
        out = str(r.get("result", {}).get("result", ""))
        res = []
        for line in out.splitlines():
            m = re.match(r"FAM\s+(\S+)\s+(\d+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)",
                         line.strip())
            if m:
                res.append((m.group(1), int(m.group(2)),
                            float(m.group(3)), float(m.group(4)),
                            float(m.group(5))))
        return res

    def component_dims_str(self) -> str:
        rows = self.component_dims()
        if not rows:
            return "（未量到构件）"
        out = []
        for fam, n, w, d, h in rows:
            out.append(f"  {fam:<14} {n:>3} 件   宽 {w:6.2f} × 深 {d:6.2f} × 高 {h:6.2f} m")
        return "\n".join(out)

    def render(self, name: str) -> str | None:
        """单视图（3/4 透视）。保持返回路径，兼容既有调用。"""
        path, _cam = self._render_one(name, "persp")
        return path

    def render_views(self, prefix: str) -> list[tuple[str, str]]:
        """固定证据渲染：hero 透视 + front/right/back 正交 + clay 灰模。

        照 blender-visual-craft skill 的 review.md：
          - 保留标准正面/侧面/背面与展示视角
          - 另存灰模证据，避免"材质问题"与"形体问题"混淆
          - **跨轮固定相机**：首轮自动取景后记录，后续轮原样复用
        """
        out = []
        plan = [
            ("hero", "persp", False),
            ("front", "front", False),
            ("right", "right", False),
            ("back", "back", False),
            ("under", "under", False),
            ("detail", "detail", False),
            ("clay", "persp", True),
        ]
        cam_states = {}
        for suffix, kind, clay in plan:
            p, cam = self._render_one(f"{prefix}_{suffix}.png", kind, clay)
            if p:
                out.append((suffix, p))
            if cam:
                cam_states[suffix] = cam

        # 首轮：把各通道相机定死，之后每轮复用（LESSONS [038]）
        if self.cam_lock is None:
            if len(cam_states) == len(plan):
                self.cam_lock = cam_states
                self.lock_size = self.scene_size()
                print("  [cam] 已锁定 %d 个检查机位（基准尺寸 %s），后续轮次沿用"
                      % (len(cam_states), self.scene_size_str()))
        else:
            print("  [cam] 沿用已锁定的检查机位")
            # 固定机位 + 模型变大 = 裁切。这是真实缺陷信号，必须报出来，
            # 不能悄悄重框（那会让两轮不可比，skill 明确警告过）。
            cur = self.scene_size()
            if cur and self.lock_size:
                ratios = [c / l if l > 1e-6 else 1.0
                          for c, l in zip(cur, self.lock_size)]
                if max(ratios) > 1.02:
                    self.overflow_note = (
                        f"本轮模型 {cur[0]:.2f}×{cur[1]:.2f}×{cur[2]:.2f}m 超出"
                        f"基准取景 {self.lock_size[0]:.2f}×{self.lock_size[1]:.2f}"
                        f"×{self.lock_size[2]:.2f}m（最大 {max(ratios):.2f} 倍），"
                        f"正交视图边缘有裁切")
                    print("  [cam] !! FRAME_OVERFLOW " + self.overflow_note)
                else:
                    self.overflow_note = None
        return out

    def _render_one(self, name: str, kind: str = "persp",
                    clay: bool = False) -> tuple[str | None, dict | None]:
        """渲染单通道。返回 (文件路径, 相机状态)。

        相机已锁定时不再前置自动取景，否则会把锁定值覆盖掉。
        """
        path = os.path.join(OUT_DIR, name)
        safe = path.replace("\\", "\\\\")
        locked = self.cam_lock is not None
        lock_literal = repr(self.cam_lock) if locked else "None"
        code = (
            "import bpy\n"
            + ("" if locked else FRAME_SNIPPET)
            + VIEW_SETUP_SNIPPET.format(
                kind=kind,
                path=safe,
                clay="True" if clay else "False",
                lock=lock_literal,
            )
            + "bpy.ops.render.render(write_still=True)\n"
            f"print('RENDERED {name}')\n"
        )
        r = self.c.execute_code(code)
        if r.get("status") != "success":
            print("  render error:", str(r.get("message"))[:300])
            return None, None
        out = str(r.get("result", {}).get("result", ""))
        cam = None
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("CAM_STATE "):
                try:
                    cam = json.loads(line[len("CAM_STATE "):])
                except Exception:                          # noqa: BLE001
                    pass
            elif line.startswith(("FRAMED", "FRAME_SKIP", "VIEW ", "CLAY",
                                  "BG_CLAMPED", "CAM_LOCKED")):
                print("  " + line)
        return (path if os.path.exists(path) else None), cam

    def scene_brief(self) -> str:
        r = self.c._send({"type": "get_scene_info", "params": {}})
        return json.dumps(r.get("result", {}), ensure_ascii=False)[:2500]


# ---------------------------------------------------------------- llm
BUILD_SYSTEM = """你是 Blender 建模专家。用 Python（bpy）直接建模，输出可执行代码。

硬性规则：
1. 只能用 bpy / mathutils / math / os。禁止网络、禁止 pip 安装。
2. 禁止 bpy.ops.wm.read_factory_settings / read_homefile / quit_blender
   —— 它们会重置 Blender 并杀死 MCP 通道。要清场就手动删 objects/collections。
3. **优先使用已注入的助手函数**（执行环境里已准备好，直接调用即可，
   不要自己重写几何构造，也不要碰 bpy.ops）：

   clear_scene()                              清空场景
   mat(name, rgb, rough=0.6, metallic=0.0)    建材质，rgb 是 3 元组 0..1
   box(name, size, loc, rot, material)        长方体，size=(x,y,z) 为完整边长，loc 为中心
   cyl(name, radius, depth, loc, rot, verts)  圆柱
   prism(name, footprint, height, loc, rot, apex, material)
                                              棱台，用于反曲屋顶/须弥座收分；
                                              apex=(fx,fy) 顶面缩放比，<1 就是收分
   beam(name, p1, p2, thickness, material)    两点之间架方木（梁/枋/栏杆/椽子）
   curved_roof(name, width, depth, ridge_h, eave_h, overhang,
                corner_lift, curve, material, ridge_mat)
                                              **中式反曲屋顶（庑殿顶）**，一体成形：
                                              凹曲屋面 + 起翘檐角 + 正脊 + 4条垂脊 + 檐口板。
                                              width/depth 是屋面尺寸(不含出檐)，
                                              ridge_h 正脊高，eave_h 檐口高，
                                              overhang 出檐外挑(0.5~0.8)，
                                              corner_lift 檐角起翘高度(0.6~1.2)，
                                              curve 反宇程度(2.0~3.0, 越大越凹)。
                                              **要做中式屋顶一律用它，不要自己拼三角形。**
   wood_mat(name, base, rough, grain)        带木纹 Noise+Bump 的程序化木材
   stone_mat(name, base, rough, scale)       带凹凸 Noise+Bump 的程序化石材
   bevel(ob, width, segments)                给物体加倒角修改器（消除锐利边缘）
   area_light(name, loc, energy, size, target)  区域光（补光/主光）
   coll(name)                                 建集合
   setup(engine, res, samples, bg)            初始化渲染引擎/分辨率/世界/太阳光/相机
   stats(label)                               打印构件数、顶点数、包围盒

4. **材质一律用 wood_mat()/stone_mat()/mat()，不要用纯色默认材质。**
   critic 会把"纯色平涂"直接扣分。屋顶瓦用 wood_mat('Tile', (0.16,0.26,0.20), 0.55)，
   木构件用 wood_mat('Wood', (0.45,0.24,0.13), 0.62)，基座用 stone_mat()。
5. **凡是要做中式屋顶，必须调用 curved_roof()**。自己拼三角形/长方板会被判为
   "平板屋顶""悬浮条状物"，是当前最主要的扣分项。
6. 每个构件独立 mesh + 清晰命名（如 Tower_Body_1 / Tower_Roof_L1），便于单独修改。
7. 开头调用 clear_scene()，然后 setup()，再建模，最后 stats()。
8. 材质参数只能走 inputs 字典；Principled BSDF 用 mat() 创建即可，不要用
   `.base_color` / `.roughness` 这类不存在的属性。
9. **建模代码必须在脚本顶层直接执行**。不要包进 main() 再靠
   `if __name__ == "__main__":` 触发 —— 该守卫可能不成立，会导致整段脚本
   静默不执行（场景为空却报成功）。
10. 严禁依赖上下文的 bpy.ops：mesh.select_all / object.mode_set / object.join /
   object.select_all / object.transform_apply / view3d.*。
   违反会抛 "context is incorrect"。要改几何就用 bmesh 或直接改 mesh.vertices。
11. 相机位置随便给，harness 会在渲染前按包围盒自动取景；但必须存在相机对象。
12. 不要添加超大地面/背景板，它会把取景撑坏。若确实需要，命名里带 Ground。
13. **构件之间要真正连接**：梁柱端点用同一组坐标变量，不要各写各的；
   不要让构件悬在空中。
14. **先定尺寸预算再动手**。在代码开头用注释写出：
   总体包围盒目标（宽x深x高）、每层高度、构件数量上限。
   如果目标没给数字，就按真实古建比例自己定一套，并在注释里写明。
15. **严禁过度建造**：构件总数控制在 120 个以内；
   任一水平方向尺寸不要超过目标值的 1.3 倍（实测有模型把 4m 进深做成 11m）。
   建完后调用 stats() 核对包围盒，若与你的尺寸预算不符，就地修正后再输出。

只输出一个 ```python 代码块，代码块外不要有任何解释。"""

CRITIC_SYSTEM = """你是严格的三维视觉评审。你会看到同一模型的一组固定证据渲染图和建模目标。

证据通道（按顺序给出）：
- hero（透视，带材质）：看整体形态、材质、比例、叙事焦点
- 正视图 / 右侧视图 / 背视图（正交）：看立面、对称、层数、轮廓、背面是否缺构件
- 灰模（Workbench，无材质无灯光）：**只反映形体**。灰模上形体正确而彩色图不对，
  就是材质/光照问题，不要当成建模缺陷。

按以下维度打分（可给小数）：
- structure (0-3)：形制/构件/比例是否符合目标。用正交视图看层数与平面完整性，
  用灰模看真实形体。视图之间矛盾要指出。
- composition (0-3)：主体占比、留白、是否被裁切
- materials (0-3)：木色/石色/瓦色是否可信，亮部是否保留颜色、暗部是否仍能读出部件
- details (0-1)：构件接合、倒角、有无穿插/悬空/断连

要求：
1. **先做尺寸核对**：用给出的实测包围盒逐项对照目标的尺寸/层数。
   形如"进深：目标 4m，实际 11m"。尺寸不符直接判 structure 不及格。
2. **逐项判定 pass / fail / unclear**，并注明依据哪张图。看不见的部位必须写 unclear，
   **不许猜**。允许审美判断，但必须说明针对哪个可见特征。
3. **必须给出 invariants**：这一轮要**保持不变**的要求（已经做对的部分）。
   这是防止下一轮改坏已经正确的东西 —— 上一轮就有模型把合格的两层楼改成三段式。
4. 明确区分"建模问题"与"渲染问题"，分别给建议。
5. 输出 JSON：
{
  "structure": x, "composition": x, "materials": x, "details": x, "total": x,
  "verdict": "keep|fix",
  "checks": [{"item":"层数","result":"pass|fail|unclear","evidence":"正视图","note":"..."}],
  "dim_check": ["目标 8m 宽 vs 实测 8.0m → pass", "..."],
  "top_issues": ["图/部位 → 可见差距 → 修改动作"],
  "invariants": ["下一轮必须保持不变的要求"],
  "actions": ["可直接翻译成代码的修改动作"]
}
6. actions 要能落到这些助手上：屋顶→curved_roof()，木构→dougong() / hongqiao()，
   材质→wood_mat()/stone_mat()，锐边→bevel()，接缝→让构件共享端点坐标。
   **做历史建筑必须先查形制来源**（见 LESSONS [048]）：
   评审说"不像"时，先怀疑形制假设，别只改渲染参数。
7. 若 total >= 8 且无 fail 项，verdict 用 "keep"。
只输出 JSON，不要多余文字。"""


def extract_code(text: str) -> str | None:
    m = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.S)
    if m:
        return m.group(1).strip()
    # 退路：整段就是代码
    if "import bpy" in text:
        return text.strip()
    return None


def ask(client, model, system, user_blocks, max_tokens=8192) -> str:
    resp = client.messages.create(
        model=model, system=system, max_tokens=max_tokens,
        messages=[{"role": "user", "content": user_blocks}],
    )
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


def ask_retry(client, model, system, user_blocks, max_tokens=8192,
              attempts=3, tag=""):
    """代理链路会偶发 ReadTimeout，退避重试；失败返回 None 而不是让整个循环崩掉。"""
    import anthropic
    delay = 5.0
    for i in range(1, attempts + 1):
        try:
            return ask(client, model, system, user_blocks, max_tokens)
        except (anthropic.APITimeoutError, anthropic.APIConnectionError,
                anthropic.InternalServerError) as e:
            print(f"  [{tag}] 第 {i}/{attempts} 次失败: {type(e).__name__}: {str(e)[:120]}")
            if i == attempts:
                return None
            time.sleep(delay)
            delay *= 2
        except Exception as e:                            # noqa: BLE001
            print(f"  [{tag}] 非重试类错误: {type(e).__name__}: {str(e)[:200]}")
            return None
    return None


def img_block(path: str, max_side: int = 1024, quality: int = 88):
    """降采样后再 base64 —— 原图 1200x900 会到 1.4MB base64，浪费 token 且可能超限。"""
    from io import BytesIO

    from PIL import Image
    im = Image.open(path).convert("RGB")
    w, h = im.size
    scale = min(1.0, max_side / max(w, h))
    if scale < 1.0:
        im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    buf = BytesIO()
    im.save(buf, format="JPEG", quality=quality)
    data = base64.standard_b64encode(buf.getvalue()).decode()
    return {"type": "image", "source": {"type": "base64",
                                        "media_type": "image/jpeg", "data": data}}


# ---------------------------------------------------------------- loop
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--goal", required=True)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--provider", default="ali", choices=list(PROVIDERS))
    ap.add_argument("--model", default=None)
    ap.add_argument("--critic-provider", default=None, choices=list(PROVIDERS),
                    help="评审用另一个 provider（默认与建模同源，属自检）")
    ap.add_argument("--critic-model", default=None,
                    help="评审模型；与建模模型不同才算独立评审")
    ap.add_argument("--keep-on-disk", action="store_true", default=True)
    args = ap.parse_args()

    base_url, api_key, model = load_provider(args.provider)
    if args.model:
        model = args.model
    print(f"[cfg] builder  provider={args.provider} model={model}")
    client = make_client(base_url, api_key)

    # 独立评审（LESSONS [039]）：同模型既写代码又评分会有自我一致性偏差。
    # 显式指定不同的 critic 才算独立评审；否则如实标注为自检。
    if args.critic_provider or args.critic_model:
        c_provider = args.critic_provider or args.provider
        c_url, c_key, c_model = load_provider(c_provider)
        if args.critic_model:
            c_model = args.critic_model
        critic_client = make_client(c_url, c_key)
        independent = (c_model != model)
        print(f"[cfg] critic   provider={c_provider} model={c_model}  "
              f"{'独立评审' if independent else '同模型自检'}")
    else:
        critic_client, c_model = client, model
        independent = False
        print("[cfg] critic   与 builder 同模型 —— 这是自检，不是独立评审")

    s = Session()
    info = s.connect()
    print(f"[blender] connected  addon={info.get('name')} v{info.get('addon_version')}")
    print(f"[blender] 初始场景: {s.scene_brief()[:160]}")

    history: list[str] = []
    best = None
    scores: list[float] = []
    last_verdict: dict = {}

    for rnd in range(1, args.rounds + 1):
        print(f"\n===== Round {rnd}/{args.rounds} =====")

        if rnd == 1:
            user = [{"type": "text", "text":
                     f"建模目标：{args.goal}\n\n"
                     f"当前场景：\n{s.scene_brief()}\n\n"
                     "请写出完整建模代码。"}]
        else:
            # skill：审稿必须写明"保持不变的要求"，否则模型会把已合格的部分改坏
            keep = last_verdict.get("invariants") or []
            keep_txt = ("\n".join(f"  - {k}" for k in keep)
                        if keep else "  （无，本轮请自行保持已正确的部分）")
            names = s.object_names()
            # 只列族前缀，避免清单过长（同名族用前缀表示）
            fams = sorted({n.split("_")[0] for n in names})
            user = [{"type": "text", "text":
                     f"建模目标：{args.goal}\n\n"
                     "上一轮的评审意见：\n" + "\n".join(history[-1:]) + "\n\n"
                     f"**以下这些上一轮已经做对，本轮必须保持不变：**\n{keep_txt}\n\n"
                     f"当前场景已有构件族（按 '_' 前缀分组）：{', '.join(fams)}\n"
                     f"（共 {len(names)} 个构件）\n\n"
                     "**本轮你可以二选一：**\n"
                     "(A) 完整重写：清场后重建全部（默认，稳妥）。\n"
                     "(B) 增量修改：只重建需要改的部分。在代码**最前面**单独写一行\n"
                     "    KEEP = [\"要保留的构件名或前缀\", ...]\n"
                     "    harness 会自动删掉不在此列表里的构件并保留这些，"
                     "你的代码只写要改的部分。\n"
                     "    适合：评审只指出了个别构件的问题，而其它部分已经做对。\n"
                     "    注意：保留的构件若位置/大小需要改，请直接对它设置 transform 或删除重建。\n\n"
                     "两种方式都要先调用 clear_scene()。请直接给出代码，不要解释。"}]

        t0 = time.time()
        text = ask_retry(client, model, BUILD_SYSTEM, user, tag="build")
        if text is None:
            print("  [build] 重试耗尽，跳过本轮")
            history.append("上一轮请求超时，请直接重试。")
            continue
        code = extract_code(text)
        if not code:
            print("  [build] 模型没给出代码，重试")
            history.append("上一轮没有输出代码块。")
            continue
        print(f"  [build] 收到 {len(code)} 字符代码 ({time.time()-t0:.1f}s)")

        with open(os.path.join(OUT_DIR, f"round{rnd}_build.py"), "w", encoding="utf-8") as f:
            f.write(code)

        res = s.run(code)
        if res.get("status") != "success":
            msg = str(res.get("message"))[:1200]
            print(f"  [exec] 失败: {msg[:300]}")
            history.append(f"上一轮代码执行失败，错误如下，请修正：\n{msg}")
            continue
        print(f"  [exec] 成功  output={str(res.get('result',{}).get('result',''))[:200]!r}")

        shots = s.render_views(f"round{rnd}")
        if not shots:
            print("  [render] 失败")
            history.append("上一轮渲染失败，请检查相机/灯光/引擎设置。")
            continue
        print(f"  [render] {len(shots)} 通道 -> "
              + ", ".join(os.path.basename(p) for _, p in shots))

        # 快照：每轮存一份场景，便于回滚到最佳轮（LESSONS [046]）
        snap_path = os.path.join(OUT_DIR, "snap", f"round{rnd}.blend")
        s.snapshot(snap_path)

        t1 = time.time()
        bbox = s.scene_bbox()
        fams = s.component_dims_str()
        labels = {
            "hero": "hero（透视，带材质）",
            "front": "正视图（正交，-Y 方向）",
            "right": "右侧视图（正交，+X 方向）",
            "back": "背视图（正交，+Y 方向）",
            "clay": "灰模（Workbench，无材质无灯光，只看形体）",
        }
        blocks = []
        for i, (suffix, p) in enumerate(shots, 1):
            blocks.append({"type": "text", "text": f"第 {i} 张：{labels.get(suffix, suffix)}"})
            blocks.append(img_block(p))
        blocks.append({"type": "text", "text":
                       f"建模目标：{args.goal}\n\n"
                       f"实测数据（Blender 直接量取，比看图估算准确，以此为准）：\n"
                       f"  构件数 = {res.get('result', {}).get('mesh_count', '?')}\n"
                       f"  整体包围盒 = {bbox}\n"
                       f"  分构件族实测尺寸（每个族各自量取）：\n"
                       f"{fams}\n"
                       + (f"  ⚠ 取景提示：{s.overflow_note}\n"
                          if s.overflow_note else
                          "  取景提示：本轮与基准机位一致，视图无裁切。\n")
                       + f"\n注意 1：第 5 张是灰模，它只反映**形体**；如果灰模上形体正确而彩色图看着不对，\n"
                       f"那是材质/光照问题，不要当成建模缺陷。\n"
                       f"注意 2：核对尺寸时**必须用上面的分族实测值**，不要用整体包围盒去套某个构件。\n"
                       f"例如「基座宽8深4」要对比基座那一族的行；整体包围盒包含了屋檐出挑，\n"
                       f"比基座大是正常的，不算超标。\n"
                       f"注意 3：看不清的项请写 unclear 并说明原因，"})
        verdict_text = ask_retry(critic_client, c_model, CRITIC_SYSTEM, blocks,
                                 max_tokens=3072, tag="critic")
        if verdict_text is None:
            print("  [critic] 重试耗尽，保留本轮渲染")
            continue
        print(f"  [critic] {time.time()-t1:.1f}s")

        try:
            m = re.search(r"\{.*\}", verdict_text, re.S)
            verdict = json.loads(m.group(0)) if m else {}
        except Exception:                                  # noqa: BLE001
            verdict = {}
        if not verdict:
            print("  [critic] 无法解析 JSON，原文:", verdict_text[:300])
            history.append(verdict_text[:1500])
            continue

        total = verdict.get("total", 0)
        verdict["_critic"] = {
            "model": c_model,
            "independent": independent,
        }
        print(f"  [score] total={total} "
              f"structure={verdict.get('structure')} "
              f"composition={verdict.get('composition')} "
              f"materials={verdict.get('materials')} "
              f"details={verdict.get('details')}  "
              f"({'独立评审' if independent else '自检'}:{c_model})")

        # skill review.md：逐项 pass/fail/unclear，并注明证据图
        for c in (verdict.get("checks") or [])[:10]:
            if isinstance(c, dict):
                print(f"          [{str(c.get('result','?')).upper():<7}] "
                      f"{c.get('item','')}  ({c.get('evidence','')})")
        for d in (verdict.get("dim_check") or [])[:6]:
            print(f"          dim: {d}")
        for it in (verdict.get("top_issues") or [])[:5]:
            print(f"          ! {it}")
        for inv in (verdict.get("invariants") or [])[:6]:
            print(f"          KEEP: {inv}")

        if best is None or total > best[0]:
            best = (total, rnd, verdict, shots[0][1])

        if verdict.get("verdict") == "keep" or total >= 8:
            print(f"\n[done] 达到退出标准 total={total} (round {rnd})")
            break

        # skill：两轮没有改善是重新检查路线（而不是继续微调）的信号
        if len(scores) >= 2 and total <= scores[-1] and total <= scores[-2]:
            print(f"  [warn] 连续两轮未改善（{scores[-2]} -> {scores[-1]} -> {total}），"
                  f"下一轮应换建模路线而非微调")
        scores.append(total)
        last_verdict = verdict

        history.append(json.dumps(verdict, ensure_ascii=False, indent=2))

    if best:
        print(f"\n[best] round={best[1]} total={best[0]}  image={best[3]}")
        with open(os.path.join(OUT_DIR, "best_verdict.json"), "w", encoding="utf-8") as f:
            json.dump(best[2], f, ensure_ascii=False, indent=2)
        # 回滚到最佳轮的场景（若最佳轮不是最后一轮）
        best_snap = os.path.join(OUT_DIR, "snap", f"round{best[1]}.blend")
        if os.path.exists(best_snap) and best[1] != rnd:
            print(f"[restore] 最佳轮是第 {best[1]} 轮（当前第 {rnd} 轮），回滚场景")
            s.restore(best_snap)
            # 回滚后重新出证据图，保证 out/ 里的图与最终场景一致
            s.render_views("final")
        else:
            print(f"[restore] 当前场景即最佳轮（第 {best[1]} 轮），无需回滚")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())