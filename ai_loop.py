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

# ================= 形制助手：反曲屋顶 =================
# LESSONS [025]：模型做不出反曲屋顶，只会做平板或悬浮条。
# 把"庑殿顶 + 反宇 + 起翘"编码成参数，模型只需给尺寸。
def curved_roof(name, width, depth, ridge_h=2.2, eave_h=0.0, overhang=0.55,
                corner_lift=0.9, curve=2.4, material=None, ridge_mat=None,
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
                _need = max(_need,
                            abs(_q.x) / (_tan_x * margin) - _depth,
                            abs(_q.y) / (_tan_y * margin) - _depth)
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
    if _KIND in _DIRS:
        _cam.data.type = 'ORTHO'
        _cam.location = _ctr + _DIRS[_KIND] * _extent * 2.0
        _cam.rotation_euler = (_ctr - _cam.location).to_track_quat('-Z', 'Y').to_euler()
        # 精确正交框选：角点投影到相机 right/up 基向量
        _rot = _cam.rotation_euler.to_matrix()
        _right, _up = _rot.col[0], _rot.col[1]
        _xx = [_right.dot(p - _ctr) for p in _pts]
        _yy = [_up.dot(p - _ctr) for p in _pts]
        _cam.data.ortho_scale = max(max(_xx) - min(_xx), max(_yy) - min(_yy)) * 1.16
        _cam.data.clip_start = 0.001
        _cam.data.clip_end = _extent * 10
        print("VIEW %s ortho scale=%.2f" % (_KIND, _cam.data.ortho_scale))
    else:
        _cam.data.type = 'PERSP'
        print("VIEW persp")

# ---- clay 灰模：只留形体，排除材质/光照干扰 ----
if _CLAY:
    _sc.render.engine = 'BLENDER_WORKBENCH'
    _sc.render.use_compositing = False
    _sc.display.shading.light = 'STUDIO'
    _sc.display.shading.color_type = 'SINGLE'
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

        # LESSONS [015]：addon 用 exec(code, {"bpy": bpy}) 执行，命名空间里没有 __name__，
        # 而 builtins 模块字典里有 __name__='builtins'，导致模型常写的
        #     if __name__ == "__main__": main()
        # 守卫为 False，整个脚本静默不执行却返回 success。
        # 注入 __name__ 让守卫成立。
        # 注入安全助手库（LESSONS [022]）—— 模型可直接调用 box/cyl/prism/beam/mat/setup/stats
        code = "__name__ = '__main__'\n" + PRELUDE + "\n# ---- 用户代码 ----\n" + code
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
6. actions 要能落到这些助手上：屋顶→curved_roof()，材质→wood_mat()/stone_mat()，
   锐边→bevel()，接缝→让构件共享端点坐标。
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
            user = [{"type": "text", "text":
                     f"建模目标：{args.goal}\n\n"
                     "上一轮的评审意见：\n" + "\n".join(history[-1:]) + "\n\n"
                     f"**以下这些上一轮已经做对，本轮必须保持不变：**\n{keep_txt}\n\n"
                     "请写出**完整替换版**代码（包含清场），修正上述问题，"
                     "同时严格遵守上面的保持不变项。不要只给补丁。"}]

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

        t1 = time.time()
        bbox = s.scene_bbox()
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
                       f"  包围盒 = {bbox}\n"
                       + (f"  ⚠ 取景提示：{s.overflow_note}\n"
                          if s.overflow_note else
                          "  取景提示：本轮与基准机位一致，视图无裁切。\n")
                       + f"\n注意：第 5 张是灰模，它只反映**形体**；如果灰模上形体正确而彩色图看着不对，\n"
                       f"那是材质/光照问题，不要当成建模缺陷。请用实测数字做尺寸核对。"})
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

        scores.append(total)
        last_verdict = verdict

        history.append(json.dumps(verdict, ensure_ascii=False, indent=2))

    if best:
        print(f"\n[best] round={best[1]} total={best[0]}  image={best[3]}")
        with open(os.path.join(OUT_DIR, "best_verdict.json"), "w", encoding="utf-8") as f:
            json.dump(best[2], f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())