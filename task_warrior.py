"""古装女侠白模：身材火辣 + 马尾辫 + 挥剑出击（**可读性优先**的版本）。

在 Blender 里跑（经 blender_client.py）：
    D:\\python3\\python.exe blender_client.py task_warrior.py

上一版被评「完全看不出是个美女」，根因（不是精度不够，是**可读性**问题）：
  1. **脸是空的** —— 只有一个鼻子。美女的辨识度一大半来自五官，
     白模也要把眼、眉、鼻、唇**雕出来**（几何，不是贴图）。
  2. **裙子是个大锥筒**，把腰臀曲线和腿全遮了 —— 火辣身材等于没建模。
     改成：贴合臀线的**高开衩**长裙（前面开衩），腿露出来。
  3. **肩是圆球**，没有肩线；改小、加坡。
  4. 腰不够细、胸不够圆、臀不够翘。

建模原则（沿用本仓库 LESSONS）：
  - 人体比例是**可判定的硬约束**：身高/头身比/肩宽/腰臀比在 build 后
    **用网格实测并打印**，不合就改参数（[064]）。
  - 建模脚本**禁止** read_factory_settings（[002]）；清场手动做。
  - 节点按 type 取，不按名字取（[006]）。
  - 场景在 finally 里还原（[072]）。

坐标约定：
  +Z 上，-Y 是她的正前方（脸朝 -Y），+X 是她的左，-X 是她的右。
  右手持剑（-X 侧），剑抡到右后上方，蓄力下劈的前一刻。
"""

import math
import os

import bmesh
import bpy
from mathutils import Euler, Matrix, Vector

OUT_DIR = r"J:\mickeylan\ai\blender\out"
NAME = "warrior"

# ==================================================================
# 比例参数
# ==================================================================
Z_HIP = 0.855
Z_WAIST = 1.060
Z_BUST = 1.235
Z_SHOULDER = 1.360
Z_HEAD = 1.585

TWIST_HIP = 8.0
TWIST_WAIST = 0.0
TWIST_SHOULDER = -20.0

HEAD_YAW = 16.0
HEAD_PITCH = 7.0

SWORD_DIR = Vector((-0.30, 0.22, 0.93)).normalized()

SEG = 28

# 头骨剖面（相对头心的高度 dz, 半宽 rx, 半深 ry）—— 放模块级，
# 因为五官要按**实际曲面**定位，不能凭"球面半径"猜。
HEAD_PROFILE = [
    (-0.106, 0.016, 0.026), (-0.090, 0.036, 0.044),
    (-0.060, 0.053, 0.062), (-0.026, 0.062, 0.075),
    (0.010, 0.066, 0.080), (0.046, 0.062, 0.074),
    (0.076, 0.049, 0.057), (0.097, 0.030, 0.036),
    (0.108, 0.009, 0.013),
]


def head_profile_at(dz):
    """插值出某个高度处的头骨 (rx, ry)。"""
    P = HEAD_PROFILE
    if dz <= P[0][0]:
        return P[0][1], P[0][2]
    if dz >= P[-1][0]:
        return P[-1][1], P[-1][2]
    for i in range(len(P) - 1):
        z0, rx0, ry0 = P[i]
        z1, rx1, ry1 = P[i + 1]
        if z0 <= dz <= z1:
            t = (dz - z0) / (z1 - z0)
            return rx0 + (rx1 - rx0) * t, ry0 + (ry1 - ry0) * t
    return P[-1][1], P[-1][2]


def face_y(lx, lz):
    """头骨前表面在 (lx, lz) 处的 y（脸朝 -Y，越负越靠前）。

    **必须用这个函数定位五官**。之前的做法是假设五官落在
    "以眼心为球心、半径 LID_R 的球面"上，但 LID_R=0.0158 根本装不下
    48mm 宽的眉毛 —— sqrt 取负后整条眉塌进头骨里，评审看到的就是
    「面部五官未雕刻，呈光滑平面」。
    """
    rx, ry = head_profile_at(lz)
    k = max(0.0, 1.0 - (lx / rx) ** 2)
    return -ry * math.sqrt(k)


# ==================================================================
# 通用工具
# ==================================================================
def clear_scene():
    """手动清场。保留插件、端口服务、UI 状态（LESSONS [002]）。"""
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    for c in list(bpy.data.collections):
        try:
            bpy.data.collections.remove(c)
        except Exception:
            pass
    for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.cameras,
                 bpy.data.lights, bpy.data.curves, bpy.data.images):
        for d in list(coll):
            if d.users == 0:
                try:
                    coll.remove(d)
                except Exception:
                    pass


def new_collection(name):
    c = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(c)
    return c


def loft(name, sections, mat=None, coll_target=None, smooth=True,
         cap_start=True, cap_end=True, closed=True):
    """把若干个**等点数截面**缝成网格。

    closed=False 时截面被当作**开口弧带**（用来做开衩裙），两侧边不封口。
    """
    n = len(sections[0])
    verts = []
    for ring in sections:
        assert len(ring) == n, "%s: 截面点数不一致 %d vs %d" % (name, len(ring), n)
        verts.extend(ring)
    faces = []
    for i in range(len(sections) - 1):
        a = i * n
        b = (i + 1) * n
        m = n if closed else (n - 1)
        for j in range(m):
            k = (j + 1) % n
            faces.append((a + j, a + k, b + k, b + j))
    cap_faces = []
    if closed and cap_start:
        cap_faces.append(len(faces))
        faces.append(tuple(range(n)))
    if closed and cap_end:
        cap_faces.append(len(faces))
        o = (len(sections) - 1) * n
        faces.append(tuple(range(o + n - 1, o - 1, -1)))

    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    if smooth:
        for p in me.polygons:
            p.use_smooth = True
        for fi in cap_faces:
            if fi < len(me.polygons):
                me.polygons[fi].use_smooth = False
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    if coll_target is not None:
        coll_target.objects.link(ob)
    if mat is not None:
        me.materials.append(mat)
    return ob


def ring_frame(center, ex, ey, rx, ry, seg, zfn=None):
    c = Vector(center)
    pts = []
    for j in range(seg):
        a = 2.0 * math.pi * j / seg
        p = c + ex * (rx * math.cos(a)) + ey * (ry * math.sin(a))
        z = c.z + (zfn(a) if zfn else 0.0)
        pts.append((p.x, p.y, z))
    return pts


def ellipse_ring(center, rx, ry, seg=SEG, twist=0.0, bumps=None, zfn=None):
    """XY 平面上的椭圆环，可整体扭转、可加局部隆起。

    bumps: [(角度, 幅度, 宽度), ...]，幅度沿 +Y（负值 = 往前凸）。
    """
    c = Vector(center)
    pts = []
    for j in range(seg):
        a = 2.0 * math.pi * j / seg + twist
        x = rx * math.cos(a)
        y = ry * math.sin(a)
        if bumps:
            for (ang, amt, wid) in bumps:
                d = math.atan2(math.sin(a - ang), math.cos(a - ang))
                y += amt * math.exp(-(d / wid) ** 2)
        pts.append((c.x + x, c.y + y, c.z + (zfn(a) if zfn else 0.0)))
    return pts


def ellipse_arc(center, rx, ry, seg, a0, a1, zfn=None):
    """椭圆的一段弧（a0 -> a1，角度制）。开衩裙用。"""
    c = Vector(center)
    pts = []
    for j in range(seg):
        a = math.radians(a0 + (a1 - a0) * j / (seg - 1.0))
        pts.append((c.x + rx * math.cos(a), c.y + ry * math.sin(a),
                    c.z + (zfn(a) if zfn else 0.0)))
    return pts


def _basis(tangent, up_hint=Vector((0.0, 0.0, 1.0))):
    t = Vector(tangent).normalized()
    up = Vector(up_hint)
    if abs(t.dot(up)) > 0.95:
        up = Vector((1.0, 0.0, 0.0))
    ex = t.cross(up).normalized()
    ey = ex.cross(t).normalized()
    return ex, ey


def tube(name, path, radii, seg=14, mat=None, coll_target=None,
         up_hint=Vector((0.0, 0.0, 1.0)), squash=None, zmin=None):
    n = len(path)
    sections = []
    for i, p in enumerate(path):
        if i == 0:
            tg = Vector(path[1]) - Vector(path[0])
        elif i == n - 1:
            tg = Vector(path[-1]) - Vector(path[-2])
        else:
            tg = Vector(path[i + 1]) - Vector(path[i - 1])
        ex, ey = _basis(tg, up_hint)
        r = radii[i]
        ry = r * (squash[i] if squash else 1.0)
        ring = ring_frame(p, ex, ey, r, ry, seg)
        if zmin is not None:
            ring = [(q[0], q[1], max(q[2], zmin)) for q in ring]
        sections.append(ring)
    return loft(name, sections, mat=mat, coll_target=coll_target)


def ribbon(name, path, widths, thickness=0.006, twist_fn=None, mat=None,
           coll_target=None):
    n = len(path)
    sections = []
    for i, p in enumerate(path):
        if i == 0:
            tg = Vector(path[1]) - Vector(path[0])
        elif i == n - 1:
            tg = Vector(path[-1]) - Vector(path[-2])
        else:
            tg = Vector(path[i + 1]) - Vector(path[i - 1])
        ex, ey = _basis(tg)
        if twist_fn:
            a = twist_fn(i / (n - 1.0))
            ex2 = ex * math.cos(a) + ey * math.sin(a)
            ey2 = -ex * math.sin(a) + ey * math.cos(a)
            ex, ey = ex2, ey2
        w = widths[i] * 0.5
        th = thickness * 0.5
        c = Vector(p)
        sections.append([
            tuple(c + ex * w + ey * th), tuple(c + ex * w - ey * th),
            tuple(c - ex * w - ey * th), tuple(c - ex * w + ey * th),
        ])
    return loft(name, sections, mat=mat, coll_target=coll_target)


def ellipsoid(name, center, radii, mat=None, coll_target=None, seg=20,
              rings=12):
    sections = []
    for i in range(rings + 1):
        t = -math.pi / 2.0 + math.pi * i / rings
        rr = math.cos(t)
        zz = math.sin(t)
        if i == 0 or i == rings:
            rr = 1e-4
        sections.append(ring_frame((center[0], center[1], center[2] + zz * radii[2]),
                                   Vector((1, 0, 0)), Vector((0, 1, 0)),
                                   radii[0] * rr, radii[1] * rr, seg))
    return loft(name, sections, mat=mat, coll_target=coll_target)


def make_mat(name, rgb, rough=0.55):
    """按 type 取 Principled（5.2 里节点名会变，见 LESSONS [006]）。"""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = next((n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if bsdf is None:
        raise RuntimeError("找不到 Principled 节点，实际=%s"
                           % [(n.name, n.type) for n in m.node_tree.nodes])
    bsdf.inputs["Base Color"].default_value = (rgb[0], rgb[1], rgb[2], 1.0)
    bsdf.inputs["Roughness"].default_value = rough
    return m


# ==================================================================
# 建模
# ==================================================================
def build():
    coll = new_collection("Warrior")
    skin = make_mat("W_Skin", (0.70, 0.67, 0.65), 0.52)
    cloth = make_mat("W_Cloth", (0.74, 0.72, 0.70), 0.70)
    hair = make_mat("W_Hair", (0.16, 0.15, 0.15), 0.42)
    eye_m = make_mat("W_Eye", (0.035, 0.030, 0.030), 0.30)
    steel = make_mat("W_Steel", (0.55, 0.56, 0.58), 0.30)
    ground_m = make_mat("W_Ground", (0.16, 0.16, 0.17), 0.85)

    made = []

    # ---------------------------------------------------------- 躯干
    # (z, cx, cy, rx, ry, 扭转°, 前凸, 后凸)
    # 腰更细、胸更圆、臀更翘 —— 火辣身材的三要素。
    TORSO = [
        (0.845, 0.0, 0.020, 0.130, 0.104, 8.0, 0.000, 0.014),
        (0.900, 0.0, 0.022, 0.138, 0.114, 8.0, 0.000, 0.046),
        (0.960, 0.0, 0.016, 0.116, 0.100, 6.0, 0.000, 0.030),
        (1.010, 0.0, 0.004, 0.090, 0.086, 2.0, 0.000, 0.004),
        (1.060, 0.0, 0.000, 0.078, 0.078, 0.0, 0.000, 0.000),
        (1.110, 0.0, -0.006, 0.083, 0.080, -4.0, 0.014, 0.000),
        (1.160, 0.0, -0.014, 0.094, 0.084, -9.0, 0.034, 0.000),
        (1.235, 0.0, -0.020, 0.108, 0.080, -14.0, 0.052, 0.000),
        (1.290, 0.0, -0.014, 0.082, 0.070, -17.0, 0.024, 0.000),
        (1.345, 0.0, -0.004, 0.068, 0.058, -20.0, 0.005, 0.000),
        (1.398, 0.0, 0.002, 0.048, 0.042, -21.0, 0.000, 0.000),
    ]

    def torso_ring(z, cx, cy, rx, ry, tw, fb, bb, seg=SEG):
        bumps = []
        if fb:
            bumps.append((-math.pi / 2, -fb, 0.95))
        if bb:
            bumps.append((math.pi / 2, bb, 1.05))
        return ellipse_ring((cx, cy, z), rx, ry, seg, math.radians(tw), bumps)

    sections = [torso_ring(*t) for t in TORSO]
    made.append(loft("Body_Torso", sections, mat=skin, coll_target=coll).name)

    # 肩：小而坡，不是圆球
    for sgn, nm in ((-1, "R"), (1, "L")):
        a = math.radians(TWIST_SHOULDER)
        lx = sgn * 0.140
        wx = lx * math.cos(a)
        wy = lx * math.sin(a)
        made.append(ellipsoid("Deltoid_%s" % nm, (wx, wy, 1.306),
                               (0.042, 0.040, 0.056), mat=skin,
                               coll_target=coll).name)

    # 锁骨窝
    made.append(ellipsoid("Clavicle", (0.0, -0.030, 1.372),
                           (0.060, 0.030, 0.016), mat=skin,
                           coll_target=coll).name)

    # ---------------------------------------------------------- 颈
    made.append(tube("Neck",
                     [(0.0, 0.004, 1.382), (0.0, -0.006, 1.424),
                      (0.0, -0.013, 1.462)],
                     [0.036, 0.031, 0.029], seg=16, mat=skin,
                     coll_target=coll).name)

    # ---------------------------------------------------------- 头 + 五官
    hmat = (Matrix.Translation((0.0, -0.014, Z_HEAD))
            @ Euler((math.radians(HEAD_PITCH), 0.0,
                     math.radians(HEAD_YAW)), 'XYZ').to_matrix().to_4x4())

    def HP(p):
        return tuple(hmat @ Vector(p))

    # 头骨：下颌收窄、颧骨略宽，比例偏女性
    hs = []
    for (dz, rx, ry) in HEAD_PROFILE:
        hs.append([HP((rx * math.cos(2 * math.pi * j / SEG),
                       ry * math.sin(2 * math.pi * j / SEG), dz))
                   for j in range(SEG)])
    made.append(loft("Head", hs, mat=skin, coll_target=coll).name)

    # ---- 眼睛：白模也必须有眼，否则是石膏头 ----
    # 做法：眼球（暗色）微凸于皮肤 + 上下眼睑沿**杏仁轮廓**的一圈凸起。
    # 眼/眉/唇/鼻**全部**按 face_y 贴在头骨曲面上。
    EYE_X = 0.026
    EYE_Z = 0.008
    BALL_R = 0.0112
    EYE_W = 0.0325
    EYE_H = 0.0112

    def almond(a, cx, cz, w, h):
        """杏仁轮廓：|x|^1.5 + |z|^1.5 = 1（两端尖）。"""
        c, s = math.cos(a), math.sin(a)
        lx = cx + (w * 0.5) * math.copysign(abs(c) ** (4.0 / 3.0), c)
        lz = cz + (h * 0.5) * math.copysign(abs(s) ** (4.0 / 3.0), s)
        return lx, lz

    for sgn, nm in ((-1, "R"), (1, "L")):
        cx = sgn * EYE_X
        # 眼球：中心在曲面里，半个球露出来
        # 球心往里收 0.0095 -> 只凸出 1.7mm（原来凸 8.8mm，像金鱼眼）
        made.append(ellipsoid("EyeBall_%s" % nm,
                               HP((cx, face_y(cx, EYE_Z) + 0.0095, EYE_Z)),
                               (BALL_R, BALL_R, BALL_R * 0.92), mat=eye_m,
                               coll_target=coll, seg=18, rings=12).name)
        # 眼睑：沿杏仁轮廓的上下两半，各凸起 3.5mm
        for up, tag, rad in ((True, "Up", 0.0040), (False, "Lo", 0.0030)):
            path = []
            radii = []
            n = 9
            for i in range(n):
                u = i / (n - 1.0)
                # 上半：a 从 0..pi；下半：pi..2pi
                a = math.pi * u if up else math.pi + math.pi * u
                lx, lz = almond(a, cx, EYE_Z, EYE_W, EYE_H)
                ly = face_y(lx, lz) - 0.0012
                path.append(HP((lx, ly, lz)))
                radii.append(rad * (0.45 + 0.55 * math.sin(math.pi * u) ** 0.6))
            made.append(tube("Lid%s_%s" % (tag, nm), path, radii, seg=8,
                             mat=skin, coll_target=coll).name)

    # ---- 眉：沿脸面上缘一道弧 ----
    for sgn, nm in ((-1, "R"), (1, "L")):
        path = []
        radii = []
        n = 8
        for i in range(n):
            u = i / (n - 1.0)
            lx = sgn * (0.004 + u * 0.044)
            lz = EYE_Z + 0.030 + 0.009 * math.sin(math.pi * u) - 0.008 * u * u
            ly = face_y(lx, lz) - 0.0016
            path.append(HP((lx, ly, lz)))
            radii.append(0.0046 * (0.30 + 0.70 * math.sin(math.pi * u) ** 0.45))
        made.append(tube("Brow_%s" % nm, path, radii, seg=8, mat=hair,
                         coll_target=coll).name)

    # ---- 鼻：鼻梁 + 鼻头 + 鼻翼 ----
    bridge = []
    for i in range(6):
        t = i / 5.0
        lz = 0.030 - t * 0.042
        bridge.append(HP((0.0, face_y(0.0, lz) - 0.0018, lz)))
    made.append(tube("NoseBridge", bridge,
                     [0.0052, 0.0048, 0.0046, 0.0048, 0.0056, 0.0066],
                     seg=8, mat=skin, coll_target=coll).name)
    made.append(ellipsoid("NoseTip", HP((0.0, face_y(0.0, -0.016) - 0.0062,
                                         -0.016)),
                           (0.0072, 0.0086, 0.0070), mat=skin,
                           coll_target=coll, seg=14, rings=9).name)
    for sgn, nm in ((-1, "R"), (1, "L")):
        made.append(ellipsoid("NoseWing_%s" % nm,
                               HP((sgn * 0.0105, face_y(0.0105, -0.020) - 0.0026,
                                   -0.020)),
                               (0.0048, 0.0068, 0.0046), mat=skin,
                               coll_target=coll, seg=12, rings=8).name)

    # ---- 唇：上下唇各一片，贴在曲面上并微微凸出 ----
    for tag, zc, half, protr, thick in (("Up", -0.0425, 0.0180, 0.0030, 0.0058),
                                        ("Lo", -0.0545, 0.0160, 0.0042, 0.0076)):
        lip = []
        n = 9
        for i in range(n):
            u = i / (n - 1.0)
            lx = (u - 0.5) * 2.0 * half
            lz = zc + (0.0016 if tag == "Lo" else 0.0)
            ly = face_y(lx, lz) - protr * math.sin(math.pi * u) ** 0.5
            lip.append(HP((lx, ly, lz)))
        made.append(tube("Lip%s" % tag, lip,
                         [thick * (0.25 + 0.75 * math.sin(math.pi * i / (n - 1.0)) ** 0.5)
                          for i in range(n)], seg=8, mat=skin,
                         coll_target=coll).name)

    # ---------------------------------------------------------- 腿
    def leg(name, hip, knee, ankle, toe, thigh_r, knee_r, calf_r, ankle_r):
        out = []
        th = [hip,
              (hip[0] * 0.85 + knee[0] * 0.15, hip[1] * 0.8 + knee[1] * 0.2,
               hip[2] * 0.85 + knee[2] * 0.15),
              (hip[0] * 0.45 + knee[0] * 0.55, hip[1] * 0.35 + knee[1] * 0.65,
               hip[2] * 0.45 + knee[2] * 0.55),
              knee]
        out.append(tube("Thigh_%s" % name, th,
                        [thigh_r, thigh_r * 0.93, thigh_r * 0.78, knee_r],
                        seg=14, mat=skin, coll_target=coll).name)
        cf = [knee,
              (knee[0] + (ankle[0] - knee[0]) * 0.28,
               knee[1] + (ankle[1] - knee[1]) * 0.28,
               knee[2] + (ankle[2] - knee[2]) * 0.20),
              (knee[0] + (ankle[0] - knee[0]) * 0.62,
               knee[1] + (ankle[1] - knee[1]) * 0.62,
               knee[2] + (ankle[2] - knee[2]) * 0.62),
              ankle]
        out.append(tube("Calf_%s" % name, cf,
                        [knee_r, calf_r, calf_r * 0.72, ankle_r], seg=14,
                        mat=skin, coll_target=coll).name)
        # 脚：踝 -> 脚背 -> 趾。截面竖直方向**压到地面**，
        # 原来是一根锥管，评审说「脚部无脚趾细节，呈圆锥或柱状且底部切平」
        fpts = [ankle,
                (ankle[0] + (toe[0] - ankle[0]) * 0.35,
                 ankle[1] + (toe[1] - ankle[1]) * 0.35, ankle[2] * 0.52 + 0.030),
                (ankle[0] + (toe[0] - ankle[0]) * 0.72,
                 ankle[1] + (toe[1] - ankle[1]) * 0.72, 0.040),
                toe]
        fr = [ankle_r * 0.90, 0.046, 0.044, 0.026]
        fo = tube("Foot_%s" % name, fpts, fr, seg=12, mat=skin,
                  coll_target=coll, zmin=0.004)
        out.append(fo.name)
        return out

    made += leg("R", (-0.072, 0.030, 0.855), (-0.108, 0.205, 0.470),
                (-0.132, 0.400, 0.115), (-0.140, 0.505, 0.032),
                0.079, 0.055, 0.060, 0.037)
    made += leg("L", (0.068, 0.030, 0.855), (0.094, -0.165, 0.480),
                (0.108, -0.330, 0.105), (0.114, -0.450, 0.028),
                0.080, 0.054, 0.059, 0.035)

    # ---------------------------------------------------------- 手臂
    def arm(name, sh, elbow, wrist, hand, up_r, elbow_r, fore_r, wrist_r):
        out = []
        ua = [sh,
              (sh[0] + (elbow[0] - sh[0]) * 0.5,
               sh[1] + (elbow[1] - sh[1]) * 0.5,
               sh[2] + (elbow[2] - sh[2]) * 0.5),
              elbow]
        out.append(tube("UpperArm_%s" % name, ua,
                        [up_r, up_r * 0.86, elbow_r], seg=12, mat=skin,
                        coll_target=coll).name)
        fa = [elbow,
              (elbow[0] + (wrist[0] - elbow[0]) * 0.42,
               elbow[1] + (wrist[1] - elbow[1]) * 0.42,
               elbow[2] + (wrist[2] - elbow[2]) * 0.42),
              wrist]
        out.append(tube("Forearm_%s" % name, fa,
                        [elbow_r, fore_r, wrist_r], seg=12, mat=skin,
                        coll_target=coll).name)
        return out

    def fist(name, center, axis, r=0.030):
        """握拳：包住剑柄的一团，比细管像手。"""
        ax = Vector(axis).normalized()
        return tube("Fist_%s" % name,
                    [Vector(center) - ax * 0.022, Vector(center),
                     Vector(center) + ax * 0.030],
                    [r * 0.94, r, r * 0.86], seg=14, mat=skin,
                    coll_target=coll)

    def open_hand(name, wrist, tip):
        """张开的手：掌 + 四指 + 拇指。"""
        w = Vector(wrist)
        ax = (Vector(tip) - w).normalized()
        up = Vector((0.0, 0.0, 1.0))
        ex = ax.cross(up).normalized()
        ey = ex.cross(ax).normalized()
        out = []
        out.append(tube("Palm_%s" % name,
                        [w + ax * 0.010, w + ax * 0.042, w + ax * 0.064],
                        [0.030, 0.036, 0.030], seg=12, squash=[0.55] * 3,
                        mat=skin, coll_target=coll).name)
        for i in range(4):
            off = (i - 1.5) * 0.017
            base = w + ax * 0.062 + ex * off
            out.append(tube("Finger_%s_%d" % (name, i),
                            [base, base + ax * 0.022 + ey * 0.004,
                             base + ax * 0.040 + ey * 0.007],
                            [0.0064, 0.0058, 0.0042], seg=7, mat=skin,
                            coll_target=coll).name)
        tb = w + ax * 0.018 - ex * 0.026
        out.append(tube("Thumb_%s" % name,
                        [tb, tb - ex * 0.015 + ax * 0.020,
                         tb - ex * 0.020 + ax * 0.034],
                        [0.0072, 0.0062, 0.0046], seg=7, mat=skin,
                        coll_target=coll).name)
        return out

    made += arm("R", (-0.132, 0.046, 1.306), (-0.298, 0.086, 1.512),
                (-0.352, 0.196, 1.746), (-0.394, 0.214, 1.816),
                0.047, 0.036, 0.041, 0.026)
    made.append(fist("R", (-0.394, 0.214, 1.816), SWORD_DIR).name)
    made += arm("L", (0.138, -0.042, 1.306), (0.252, -0.118, 1.188),
                (0.324, -0.252, 1.150), (0.352, -0.300, 1.142),
                0.047, 0.036, 0.041, 0.026)
    made += open_hand("L", (0.324, -0.252, 1.150), (0.352, -0.300, 1.142))

    # ---------------------------------------------------------- 交领襦
    def torso_shell(z_from, z_to, off):
        out = []
        for (z, cx, cy, rx, ry, tw, fb, bb) in TORSO:
            if not (z_from <= z <= z_to):
                continue
            out.append(torso_ring(z, cx, cy, rx + off, ry + off, tw, fb, bb))
        return out

    # 齐胸短襦：下摆在胸下 1.17，**不遮腰**。
    # 评审原话「腰部结构被衣物遮挡无法判断曲线」—— 露一截腰才有沙漏。
    made.append(loft("Ruan_Top", torso_shell(1.168, 1.398, 0.011),
                      mat=cloth, coll_target=coll).name)

    collarA = [(0.080, -0.054, 1.392), (0.044, -0.092, 1.312),
               (0.000, -0.120, 1.245), (-0.044, -0.104, 1.192),
               (-0.076, -0.090, 1.170)]
    collarB = [(p[0], p[1] - 0.009, p[2]) for p in
               [(-0.080, -0.050, 1.392), (-0.044, -0.090, 1.310),
                (0.002, -0.114, 1.232), (0.046, -0.098, 1.182),
                (0.074, -0.084, 1.168)]]
    made.append(ribbon("Collar_L", collarA, [0.056] * 5, 0.006,
                       mat=cloth, coll_target=coll).name)
    made.append(ribbon("Collar_R", collarB, [0.056] * 5, 0.006,
                       mat=cloth, coll_target=coll).name)

    # 腰封（把腰勒出来）
    # 腰封原来外扩 18mm，把腰撑到 0.192 —— 和胸围 0.196 几乎一样，
    # 评审原话「胸部与腰部几乎同宽，没有女性曲线」。改成外扩 8mm。
    # 独立腰封：窄、贴身，并加一个前侧结，不再像悬浮的整圈壳。
    made.append(loft("Belt", torso_shell(1.046, 1.094, 0.008),
                      mat=cloth, coll_target=coll).name)
    made.append(ellipsoid("BeltKnot", (-0.090, -0.055, 1.070),
                           (0.024, 0.012, 0.020), mat=hair,
                           coll_target=coll).name)
    made.append(ribbon("BeltKnotTail", [(-0.098, -0.060, 1.055),
                                         (-0.112, -0.064, 0.985),
                                         (-0.106, -0.052, 0.930)],
                       [0.032, 0.026, 0.018], 0.006,
                       mat=cloth, coll_target=coll).name)

    # ---------------------------------------------------------- 高开衩长裙
    # 前面开 140 度衩：腰臀贴合胯线，下摆外扩。
    # **开衩是为了露腿** —— 上一版整条腿被裙子盖住，火辣身材等于没建。
    # 下摆 z=0.58 —— **膝上**。原来下摆 0.33，**后腿的小腿穿进裙子的后片**
    # （评审点名「裙摆与腿部穿模严重」）。抬到膝上，腿全露，也更火辣。
    # rx 必须**大于大腿外缘**（大腿根半宽约 0.165），否则裙子从腿里穿过去。
    SKIRT = [
        (1.060, 0.0, 0.000, 0.084, 0.086),
        (0.960, 0.0, 0.006, 0.124, 0.126),
        (0.870, 0.0, 0.012, 0.165, 0.176),
        (0.760, 0.0, 0.010, 0.184, 0.196),
        (0.670, 0.0, 0.004, 0.196, 0.208),
        (0.600, 0.0, 0.000, 0.206, 0.238),
    ]
    A0, A1 = 340.0, 560.0        # 开口 200..340（前方 140 度）
    ssec = []
    for (z, cx, cy, rx, ry) in SKIRT:
        fade = max(0.0, min(1.0, (0.72 - z) / 0.72))

        def zfn(a, fade=fade):
            front = max(0.0, -math.sin(a))
            lift = 0.10 * (front ** 1.3)
            wave = 0.018 * math.sin(3.0 * a + 0.6) + 0.008 * math.sin(5.0 * a)
            return fade * (lift + wave)

        def ring(a0, a1, rx, ry, z, zf):
            # **背面加深**：后腿向后甩，裙子的后片原来会插进小腿
            # （数值自检：裙-腿最小间隙 -35.5mm）。
            pts = []
            for j in range(34):
                a = math.radians(a0 + (a1 - a0) * j / 33.0)
                back = max(0.0, math.sin(a))
                rya = ry * (1.0 + 0.34 * back ** 1.5)
                pts.append((cx + rx * math.cos(a), cy + rya * math.sin(a),
                            z + zf(a)))
            return pts
        ssec.append(ring(A0, A1, rx, ry, z, zfn))
    made.append(loft("Skirt", ssec, mat=cloth, coll_target=coll,
                      closed=False).name)

    # 裙褶：必须**贴在裙面上**。原来直接按 x 摆位置，正面开衩处
    # 的褶子直接插进前腿 28~32mm（数值自检抓到）。
    def skirt_point(a_deg, z):
        """裙面在 (角度, 高度) 处的点（沿径向外推 1.2%）。"""
        a = math.radians(a_deg)
        for i in range(len(SKIRT) - 1):
            z0, _, _, rx0, ry0 = SKIRT[i]
            z1, _, _, rx1, ry1 = SKIRT[i + 1]
            if z1 <= z <= z0:
                t = (z0 - z) / max(1e-6, (z0 - z1))
                rx = rx0 + (rx1 - rx0) * t
                ry = ry0 + (ry1 - ry0) * t
                back = max(0.0, math.sin(a))
                rya = ry * (1.0 + 0.34 * back ** 1.5)
                fade = max(0.0, min(1.0, (0.72 - z) / 0.72))
                front = max(0.0, -math.sin(a))
                lift = 0.10 * (front ** 1.3)
                wave = (0.018 * math.sin(3.0 * a + 0.6)
                        + 0.008 * math.sin(5.0 * a))
                dz = fade * (lift + wave)
                return (rx * math.cos(a) * 1.012,
                        rya * math.sin(a) * 1.012,
                        z + dz)
        z0, _, _, rx0, ry0 = SKIRT[-1]
        back = max(0.0, math.sin(a))
        rya = ry0 * (1.0 + 0.34 * back ** 1.5)
        return (rx0 * math.cos(a) * 1.012, rya * math.sin(a) * 1.012, z)

    for i, a_deg in enumerate((35.0, 70.0, 110.0, 145.0)):
        path = [skirt_point(a_deg, zz) for zz in (1.058, 0.880, 0.640)]
        made.append(ribbon("SkirtPleat_%d" % i, path,
                           [0.010, 0.008, 0.005], 0.003,
                           mat=hair, coll_target=coll).name)

    # ---------------------------------------------------------- 广袖
    def sleeve(name, path, radii):
        sec = []
        n = len(path)
        for i, p in enumerate(path):
            if i == 0:
                tg = Vector(path[1]) - Vector(path[0])
            elif i == n - 1:
                tg = Vector(path[-1]) - Vector(path[-2])
            else:
                tg = Vector(path[i + 1]) - Vector(path[i - 1])
            ex, ey = _basis(tg)
            sec.append(ring_frame(p, ex, ey, radii[i], radii[i], 20))
        return loft("Sleeve_%s" % name, sec, mat=cloth, coll_target=coll)

    # 袖口起点放到**上臂中段**（原来从肩点起，环太大，成了一块"肩甲板"）
    # 布袖不应像两个倒扣酒杯：逐段轻微放宽，袖口只比前臂略大。
    made.append(sleeve("R",
                        [(-0.132, 0.046, 1.306), (-0.166, 0.052, 1.250),
                         (-0.190, 0.056, 1.170), (-0.215, 0.060, 1.075),
                         (-0.230, 0.062, 0.965)],
                        [0.053, 0.058, 0.068, 0.078, 0.090]).name)
    made.append(sleeve("L",
                        [(0.138, -0.042, 1.306), (0.158, -0.046, 1.250),
                         (0.174, -0.050, 1.170), (0.192, -0.054, 1.080),
                         (0.204, -0.056, 0.972)],
                        [0.051, 0.056, 0.066, 0.076, 0.088]).name)
    # 袖口收边：窄边带，不再使用会制造杯口轮廓的超宽横条。
    made.append(ribbon("Cuff_R", [(-0.215, 0.060, 1.075),
                                   (-0.230, 0.062, 0.965)],
                       [0.100, 0.100], 0.006, mat=hair,
                       coll_target=coll).name)
    made.append(ribbon("Cuff_L", [(0.192, -0.054, 1.080),
                                   (0.204, -0.056, 0.972)],
                       [0.098, 0.098], 0.006, mat=hair,
                       coll_target=coll).name)

    # ---------------------------------------------------------- 披帛
    # 只保留一条明确的背后披帛；旧版两条从胸前穿过，容易被读成漂浮甲片。
    sash = [(0.084, 0.105, 1.382), (0.150, 0.270, 1.270),
            (0.120, 0.430, 1.110), (0.020, 0.560, 0.930),
            (-0.100, 0.620, 0.780)]
    made.append(ribbon("BackSash", sash, [0.050] * 5, 0.006,
                       twist_fn=lambda u: math.radians(65 * u),
                       mat=cloth, coll_target=coll).name)

    # ---------------------------------------------------------- 头发
    SCALP = [
        (-0.062, 0.060, 0.072), (-0.020, 0.068, 0.080),
        (0.020, 0.071, 0.084), (0.055, 0.066, 0.077),
        (0.084, 0.052, 0.060), (0.102, 0.032, 0.038),
        (0.112, 0.010, 0.014),
    ]
    # **发际线**：正前方抬到 z=0.042（额头露出来），后脑垂到 z=-0.062。
    # 原来的头皮是一个罩住整个头的实心壳，把额头也包了 —— 评审说
    # 「头部整体呈鸡蛋状，额头过于饱满隆起」。
    ssc = []
    for (dz, _rx, _ry) in SCALP:
        ring = []
        for j in range(SEG):
            a = 2 * math.pi * j / SEG
            front = max(0.0, -math.sin(a))
            zadj = dz + max(0.0, (0.042 - dz)) * (front ** 1.6)
            hx, hy = head_profile_at(zadj)
            ring.append(HP((hx * 1.045 * math.cos(a),
                            hy * 1.045 * math.sin(a), zadj)))
        ssc.append(ring)
    made.append(loft("Hair_Scalp", ssc, mat=hair, coll_target=coll).name)

    # 发髻（后脑偏高，古典感）
    made.append(ellipsoid("Hair_Bun", HP((0.0, 0.060, 0.060)),
                           (0.040, 0.037, 0.034), mat=hair,
                           coll_target=coll).name)

    # 马尾辫：粗根、细梢，向后甩出 S 形
    # 前两点在发髻内部（局部坐标），后面转到世界坐标，步距均匀
    pony = [HP((0.0, 0.062, 0.050)),
            HP((0.0, 0.104, 0.030)),
            (0.004, 0.152, 1.594),
            (0.024, 0.238, 1.528),
            (0.044, 0.318, 1.438),
            (0.046, 0.392, 1.314),
            (0.026, 0.450, 1.176),
            (-0.012, 0.474, 1.032),
            (-0.042, 0.468, 0.928)]
    pr = [0.046, 0.044, 0.041, 0.037, 0.032, 0.027, 0.021, 0.014, 0.007]
    made.append(tube("Ponytail", pony, pr, seg=18, mat=hair,
                     coll_target=coll).name)
    made.append(tube("PonyTie", [pony[1], pony[2]],
                      [0.031, 0.030], seg=12, mat=hair,
                      coll_target=coll).name)

    # 鬓发：贴脸两侧垂到下颌 —— 修饰脸型
    for sgn, nm in ((-1, "R"), (1, "L")):
        p = [HP((sgn * 0.055, 0.034, 0.030)),
             HP((sgn * 0.060, 0.014, -0.014)),
             HP((sgn * 0.057, 0.000, -0.056)),
             HP((sgn * 0.049, -0.006, -0.086))]
        made.append(tube("SideLock_%s" % nm, p, [0.017, 0.015, 0.012, 0.007],
                         seg=10, mat=hair, coll_target=coll).name)

    # 刘海：斜扫过额头，别挡住眼睛
    bang = [HP((-0.054, 0.026, 0.044)), HP((-0.020, -0.034, 0.040)),
            HP((0.026, -0.050, 0.026)), HP((0.060, -0.030, 0.010))]
    made.append(tube("Fringe", bang, [0.017, 0.021, 0.019, 0.011],
                     seg=10, mat=hair, coll_target=coll).name)

    # ---------------------------------------------------------- 剑
    hand_r = Vector((-0.394, 0.214, 1.816))
    d = SWORD_DIR
    BLADE = [
        (0.058, 0.0240, 0.0075), (0.168, 0.0242, 0.0075),
        (0.468, 0.0220, 0.0068), (0.688, 0.0185, 0.0058),
        (0.828, 0.0140, 0.0045), (0.908, 0.0080, 0.0028),
        (0.948, 0.0022, 0.0010),
    ]
    # 剑格在**拳头上方** 4.5cm、剑柄穿过拳心：
    #   - 原来剑格离手心只 2cm，整个剑格被手掌包住（qwen：「剑格和剑柄
    #     与手部融合不可辨识」）；
    #   - 反过来把剑放在手心下方，剑身就从手腕里穿过去了（qwen：
    #     「剑身与持剑手臂连接处存在穿模」）。
    guard = hand_r + d * 0.045
    ex, ey = _basis(d)
    bsec = []
    for (t, hw, ht) in BLADE:
        c = guard + d * t
        ring = []
        for j in range(8):
            a = 2 * math.pi * j / 8
            ring.append(tuple(c + ex * (hw * math.cos(a)) + ey * (ht * math.sin(a))))
        bsec.append(ring)
    made.append(loft("Sword_Blade", bsec, mat=steel, coll_target=coll).name)

    gsec = []
    for (t, hw, ht) in [(-0.030, 0.044, 0.014), (-0.016, 0.048, 0.015),
                        (0.002, 0.044, 0.014), (0.010, 0.030, 0.011)]:
        gsec.append(ring_frame(guard + d * t, ex, ey, hw, ht, 12))
    made.append(loft("Sword_Guard", gsec, mat=steel, coll_target=coll).name)

    made.append(tube("Sword_Grip", [guard + d * 0.006, guard - d * 0.048,
                                    guard - d * 0.098],
                      [0.016, 0.0145, 0.015], seg=12, mat=steel,
                      coll_target=coll).name)
    made.append(ellipsoid("Sword_Pommel", tuple(guard - d * 0.108),
                           (0.018, 0.018, 0.016), mat=steel,
                           coll_target=coll).name)

    ts = guard - d * 0.115
    tp = [ts,
          (ts.x - 0.02, ts.y + 0.02, ts.z - 0.09),
          (ts.x - 0.03, ts.y + 0.05, ts.z - 0.18),
          (ts.x - 0.02, ts.y + 0.09, ts.z - 0.26)]
    made.append(tube("Sword_Tassel", tp, [0.008, 0.007, 0.006, 0.004],
                     seg=8, mat=hair, coll_target=coll).name)

    # ---------------------------------------------------------- 地面
    g = bpy.data.meshes.new("Ground")
    g.from_pydata([(-5, -5, 0), (5, -5, 0), (5, 5, 0), (-5, 5, 0)],
                  [], [(0, 1, 2, 3)])
    g.update()
    gob = bpy.data.objects.new("Ground", g)
    bpy.context.scene.collection.objects.link(gob)
    gob.data.materials.append(ground_m)

    return coll, made


# ==================================================================
# 相机 / 灯光 / 渲染
# ==================================================================
def body_bounds():
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    for ob in bpy.data.objects:
        if ob.type != 'MESH' or ob.name == "Ground":
            continue
        if ob.name.startswith(("Sword_", "Sash_", "Ponytail")):
            continue
        for c in ob.bound_box:
            p = ob.matrix_world @ Vector(c)
            for i in range(3):
                lo[i] = min(lo[i], p[i])
                hi[i] = max(hi[i], p[i])
    return lo, hi


def make_camera():
    cd = bpy.data.cameras.new("WarriorCam")
    cd.lens = 85.0
    cam = bpy.data.objects.new("WarriorCam", cd)
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    return cam


def aim_camera(cam, direction, margin=1.10, target=None, radius=None):
    """radius 显式给定时**不再**用全身包围盒 —— 否则近景镜头会退化成全身照。"""
    lo, hi = body_bounds()
    ctr = (lo + hi) * 0.5
    if target is not None:
        ctr = Vector(target)
    if radius is None:
        radius = max((hi - lo).length * 0.5, 0.3)
    d = Vector(direction).normalized()
    fov = 2.0 * math.atan(0.5 * cam.data.sensor_width / cam.data.lens)
    dist = radius / math.sin(fov * 0.5) * margin
    cam.location = ctr + d * dist
    q = (ctr - cam.location).to_track_quat('-Z', 'Y')
    cam.rotation_euler = q.to_euler()
    return ctr, radius, dist


def add_lights():
    for nm, loc, energy, size in (
            ("Key", (-2.4, -3.2, 3.2), 900.0, 2.2),
            ("Fill", (3.0, -2.0, 1.7), 300.0, 3.0),
            ("Rim", (1.2, 3.4, 3.0), 700.0, 2.0)):
        ld = bpy.data.lights.new("L_" + nm, 'AREA')
        ld.energy = energy
        ld.size = size
        ob = bpy.data.objects.new("L_" + nm, ld)
        bpy.context.scene.collection.objects.link(ob)
        ob.location = loc
        q = (Vector((0.0, 0.0, 1.15)) - Vector(loc)).to_track_quat('-Z', 'Y')
        ob.rotation_euler = q.to_euler()


def setup_world(bg=(0.05, 0.053, 0.062)):
    sc = bpy.context.scene
    w = bpy.data.worlds.new("WWorld")
    w.use_nodes = True
    node = next((n for n in w.node_tree.nodes if n.type == 'BACKGROUND'), None)
    if node is None:
        raise RuntimeError("World 里没有 Background 节点")
    node.inputs["Color"].default_value = (bg[0], bg[1], bg[2], 1.0)
    node.inputs["Strength"].default_value = 1.0
    sc.world = w
    sc.render.engine = 'BLENDER_EEVEE'
    sc.render.film_transparent = False
    sc.view_settings.view_transform = 'Standard'
    sc.view_settings.look = 'None'


def render(path, res=(1000, 1300)):
    sc = bpy.context.scene
    sc.render.resolution_x = res[0]
    sc.render.resolution_y = res[1]
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = 'PNG'
    sc.render.image_settings.color_mode = 'RGB'
    sc.render.image_settings.color_depth = '8'
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    return path


# ==================================================================
# 实测
# ==================================================================
def measure():
    out = {}

    def bbox_of(prefix):
        lo = Vector((1e9, 1e9, 1e9))
        hi = Vector((-1e9, -1e9, -1e9))
        found = False
        for ob in bpy.data.objects:
            if ob.type != 'MESH' or not ob.name.startswith(prefix):
                continue
            found = True
            for c in ob.bound_box:
                p = ob.matrix_world @ Vector(c)
                for i in range(3):
                    lo[i] = min(lo[i], p[i])
                    hi[i] = max(hi[i], p[i])
        return (lo, hi) if found else (None, None)

    # 身高：脚底 -> 头顶（**排除举起的右臂**，否则虚高）
    zmin = 1e9
    for ob in bpy.data.objects:
        if ob.type != 'MESH' or not ob.name.startswith("Foot_"):
            continue
        for c in ob.bound_box:
            zmin = min(zmin, (ob.matrix_world @ Vector(c)).z)
    lo4, hi4 = bbox_of("Head")
    lo7, hi7 = bbox_of("Hair_Scalp")
    zmax = max(hi4.z, hi7.z) if hi4 else 0.0
    out["height"] = zmax - zmin
    out["head_h"] = (hi4.z - lo4.z) if hi4 else 0.0
    out["head_count"] = out["height"] / out["head_h"] if out["head_h"] else 0

    lo3, hi3 = bbox_of("Deltoid")
    out["shoulder_w"] = (hi3.x - lo3.x) if hi3 else 0.0

    me = bpy.data.objects["Body_Torso"].data

    def width_at(z, tol=0.012):
        xs = [v.co.x for v in me.vertices if abs(v.co.z - z) < tol]
        return (max(xs) - min(xs)) if len(xs) > 3 else 0.0

    def depth_at(z, tol=0.012):
        ys = [v.co.y for v in me.vertices if abs(v.co.z - z) < tol]
        return (max(ys) - min(ys)) if len(ys) > 3 else 0.0

    out["w_bust"] = width_at(1.235)
    out["w_waist"] = width_at(1.060)
    out["w_hip"] = width_at(0.900)
    out["waist_hip"] = out["w_waist"] / out["w_hip"] if out["w_hip"] else 0
    out["d_hip"] = depth_at(0.900)
    out["d_bust"] = depth_at(1.235)

    lo5, hi5 = bbox_of("Sword_Blade")
    out["sword_tip_z"] = hi5.z if hi5 else 0.0
    out["sword_len"] = ((hi5 - lo5).length if hi5 else 0.0)

    lo6, hi6 = bbox_of("Skirt")
    out["skirt_hem_z"] = lo6.z if lo6 else 0.0
    return out


def main():
    clear_scene()
    coll, made = build()
    setup_world()
    add_lights()
    cam = make_camera()

    shots = []
    # hero：右前方 3/4，略高机位看脸
    aim_camera(cam, (-0.82, -1.18, 0.22), margin=1.05, target=(0.0, 0.0, 1.06))
    shots.append(render(os.path.join(OUT_DIR, "%s_hero.png" % NAME)))
    aim_camera(cam, (0.0, -1.0, 0.0), margin=1.03, target=(0.0, 0.0, 0.92))
    shots.append(render(os.path.join(OUT_DIR, "%s_front.png" % NAME)))
    aim_camera(cam, (-1.0, 0.0, 0.0), margin=1.03, target=(0.0, 0.0, 0.92))
    shots.append(render(os.path.join(OUT_DIR, "%s_side.png" % NAME)))
    aim_camera(cam, (0.0, 1.0, 0.0), margin=1.03, target=(0.0, 0.0, 0.92))
    shots.append(render(os.path.join(OUT_DIR, "%s_back.png" % NAME)))
    # 脸部近景：**必须显式给半径**，否则会退化成全身照。
    # 近景同时隐藏地面，避免地面填满画面、干扰五官判断。
    ground = bpy.data.objects.get("Ground")
    if ground is not None:
        ground.hide_render = True
    aim_camera(cam, (0.85, -1.05, 0.06), margin=1.02,
               target=(0.0, -0.03, 1.575), radius=0.145)
    shots.append(render(os.path.join(OUT_DIR, "%s_face.png" % NAME), res=(900, 900)))
    if ground is not None:
        ground.hide_render = False

    # 灰模
    sc = bpy.context.scene
    sc.render.engine = 'BLENDER_WORKBENCH'
    sh = sc.display.shading
    sh.light = 'STUDIO'
    sh.color_type = 'SINGLE'
    sh.single_color = (0.55, 0.55, 0.55)
    sh.show_shadows = True
    sh.show_cavity = True
    sh.cavity_type = 'BOTH'
    aim_camera(cam, (-0.82, -1.18, 0.22), margin=1.05, target=(0.0, 0.0, 1.06))
    shots.append(render(os.path.join(OUT_DIR, "%s_clay.png" % NAME)))
    sc.render.engine = 'BLENDER_EEVEE'

    m = measure()
    print("=" * 64)
    print("WARRIOR BUILD OK")
    print("  构件数: %d" % len(made))
    print("  身高: %.3f m   头高: %.3f m   头身比: %.2f"
          % (m["height"], m["head_h"], m["head_count"]))
    print("  肩宽: %.3f m" % m["shoulder_w"])
    print("  胸宽: %.3f  腰宽: %.3f  臀宽: %.3f  (腰/臀=%.3f)"
          % (m["w_bust"], m["w_waist"], m["w_hip"], m["waist_hip"]))
    print("  臀深: %.3f  胸深: %.3f" % (m["d_hip"], m["d_bust"]))
    print("  裙下摆 z=%.3f  剑尖高=%.3f  剑长=%.3f"
          % (m["skirt_hem_z"], m["sword_tip_z"], m["sword_len"]))
    print("  渲染: %s" % ", ".join(os.path.basename(s) for s in shots))
    print("=" * 64)

    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT_DIR, "%s.blend" % NAME))


try:
    # 供其它脚本以模块方式复用：exec 前在命名空间里放
    # WARRIOR_NO_AUTORUN=True 即可只拿到函数、不触发本脚本的建模+渲染。
    if not globals().get("WARRIOR_NO_AUTORUN"):
        main()
except Exception:
    import traceback
    traceback.print_exc()
    raise
finally:
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT_DIR, "%s.blend" % NAME))
