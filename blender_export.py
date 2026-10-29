"""白模导出：彩模 / 灰模 / 深度 / 相机空间法线。

在 Blender 里跑（经 blender_client.py），**不要**直接用 blender --python
—— 会另起一个进程，拿不到当前场景。

    D:\\python3\\python.exe blender_client.py blender_export.py

产出（out/export/）：
    <name>_combined.png   彩模（EEVEE，带材质）
    <name>_clay.png       灰模（Workbench，纯形体）
    <name>_depth.exr      深度（线性 float，米；已归一化到 near/far）
    <name>_normal.exr     相机空间法线（线性 float，编码 n*0.5+0.5）
    <name>_depth.npy      同上，float32 原始数组（给外层脚本直接用）
    <name>_normal.npy
    <name>_manifest.json  相机矩阵 / 焦距 / 分辨率 / 约定说明
    <name>_report.txt     自检报告（深度/法线的实测误差）

设计依据（全部来自本仓库 LESSONS.md 的实测结论）：
  - 深度与法线**不用合成器 pass**：Blender 5.2 把 Render Layers 节点放进
    合成器 Group 后读不到 Depth/Normal 槽（读到全 0），见 [026]/[027]。
    改用**材质驱动 + view_layer.material_override**：不碰场景材质槽，
    一个赋值就能还原，5.2 上稳定。
  - 深度的真值 = |(cam.matrix_world.inverted() @ P).z|（沿光轴的米数），
    材质用 Camera Data 的 "View Z Depth"（正值、线性、米），
    经 Map Range 从 near/far 线性映射到 1..0，见 [028]。
  - 法线的真值 = cam_inv.to_3x3() @ n_world（**只用 3x3 旋转部分**，
    用 4x4 会混入相机平移，真值全错，见 [029]）。
    Blender 的 Vector Transform(CAMERA) 的 Z 与该真值**相反**，
    所以要翻转 Z；本脚本会**实测判定**该用哪一种，不靠记忆，见 [030]。
  - EXR 直接存线性值；PNG 会被 sRGB 编码，深度图要解码才有米制意义，
    所以深度/法线一律出 EXR + npy，PNG 只给彩模和灰模。
  - **绝不使用 bpy.ops.wm.read_factory_settings()**：它会重置插件，
    9876 端口不再监听，MCP 通道直接断掉，见 [002]。
"""

import json
import os

import bpy
import numpy as np
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

OUT_DIR = r'J:\mickeylan\ai\blender\out\export'
NAME = os.environ.get('EXPORT_NAME', 'scene')
W = int(os.environ.get('EXPORT_W', 1200))
H = int(os.environ.get('EXPORT_H', 900))

os.makedirs(OUT_DIR, exist_ok=True)

scene = bpy.context.scene
cam = scene.camera
if cam is None:
    raise RuntimeError("场景里没有相机，先建好相机再导出")

NEAR = float(cam.data.clip_start)
FAR = float(cam.data.clip_end)
cam_inv = cam.matrix_world.inverted()


def scene_depth_range():
    """按场景实际内容算裁剪面。

    Blender 默认 clip_end 是 1000m 级（本机是 282.9m），
    而深度图是把 [near, far] **线性映射**到 [1, 0]：
    far 拉得越大，同样精度能表达的距离越少，深度图就没法用。
    所以导出时按"相机到所有几何的最远距离 × 1.15"收紧，
    导完再还原相机原来的裁剪面。
    """
    bpy.context.view_layer.update()
    org = cam.matrix_world.translation
    dmin, dmax = 1e18, 0.0
    for ob in bpy.data.objects:
        if ob.type != 'MESH' or ob.hide_render:
            continue
        mw = ob.matrix_world
        for c in ob.bound_box:
            p = mw @ Vector(c)
            d = (p - org).length
            dmin = min(dmin, d)
            dmax = max(dmax, d)
    if dmax <= 0.0:
        return float(cam.data.clip_start), float(cam.data.clip_end)
    near = max(0.01, dmin * 0.5)
    far = max(near * 10.0, dmax * 1.15)
    return near, far


# ---------------------------------------------------------------- 状态存取
_state = {
    "engine": scene.render.engine,
    "filepath": scene.render.filepath,
    "file_format": scene.render.image_settings.file_format,
    "color_depth": scene.render.image_settings.color_depth,
    "color_mode": scene.render.image_settings.color_mode,
    "res": (scene.render.resolution_x, scene.render.resolution_y,
            scene.render.resolution_percentage),
    "view_transform": scene.view_settings.view_transform,
    "look": scene.view_settings.look,
    "exposure": scene.view_settings.exposure,
    "gamma": scene.view_settings.gamma,
    "use_compositing": scene.render.use_compositing,
    "film_transparent": scene.render.film_transparent,
    "override": bpy.context.view_layer.material_override,
    "clip_start": cam.data.clip_start,
    "clip_end": cam.data.clip_end,
    "shading": {
        "light": scene.display.shading.light,
        "color_type": scene.display.shading.color_type,
        "single_color": tuple(scene.display.shading.single_color),
        "show_shadows": scene.display.shading.show_shadows,
        "show_cavity": scene.display.shading.show_cavity,
        "cavity_type": scene.display.shading.cavity_type,
        "background_type": scene.display.shading.background_type,
    },
}


def restore():
    scene.render.engine = _state["engine"]
    scene.render.filepath = _state["filepath"]
    scene.render.image_settings.file_format = _state["file_format"]
    scene.render.image_settings.color_depth = _state["color_depth"]
    scene.render.image_settings.color_mode = _state["color_mode"]
    (scene.render.resolution_x, scene.render.resolution_y,
     scene.render.resolution_percentage) = _state["res"]
    scene.view_settings.view_transform = _state["view_transform"]
    scene.view_settings.look = _state["look"]
    scene.view_settings.exposure = _state["exposure"]
    scene.view_settings.gamma = _state["gamma"]
    scene.render.use_compositing = _state["use_compositing"]
    scene.render.film_transparent = _state["film_transparent"]
    bpy.context.view_layer.material_override = _state["override"]
    cam.data.clip_start = _state["clip_start"]
    cam.data.clip_end = _state["clip_end"]
    sh = scene.display.shading
    sh.light = _state["shading"]["light"]
    sh.color_type = _state["shading"]["color_type"]
    sh.single_color = _state["shading"]["single_color"]
    sh.show_shadows = _state["shading"]["show_shadows"]
    sh.show_cavity = _state["shading"]["show_cavity"]
    sh.cavity_type = _state["shading"]["cavity_type"]
    sh.background_type = _state["shading"]["background_type"]


# ---------------------------------------------------------------- 材质
def mat_depth():
    """Camera Data 的 View Z Depth（正值、线性、米）→ 归一化到 1..0。"""
    m = bpy.data.materials.new("EXPORT_Depth")
    m.use_nodes = True
    t = m.node_tree
    t.nodes.clear()
    cd = t.nodes.new("ShaderNodeCameraData")
    mr = t.nodes.new("ShaderNodeMapRange")
    mr.interpolation_type = 'LINEAR'
    mr.inputs["From Min"].default_value = NEAR
    mr.inputs["From Max"].default_value = FAR
    mr.inputs["To Min"].default_value = 1.0
    mr.inputs["To Max"].default_value = 0.0
    emi = t.nodes.new("ShaderNodeEmission")
    out = t.nodes.new("ShaderNodeOutputMaterial")
    t.links.new(cd.outputs["View Z Depth"], mr.inputs["Value"])
    t.links.new(mr.outputs["Result"], emi.inputs["Color"])
    t.links.new(emi.outputs["Emission"], out.inputs["Surface"])
    return m


def mat_normal(flip_z):
    """世界法线 → 相机空间 → 编码 n*0.5+0.5。flip_z 由实测判定。

    用 Geometry 节点的 **True Normal**（面法线，未插值）：
    它与 scene.ray_cast 返回的法线是**同一个量**，所以自检能严格对齐；
    若用 "Normal"（着色法线，圆柱上会平滑插值），与面法线对不上。

    ⚠ 必须把 geo 接到 vt 的 Vector 输入上：
    没接的话 vt.inputs["Vector"] 保持默认 (0,0,0)，
    整张法线图是均匀的 0.5 灰 —— 看起来"导出成功"，实际全错。
    """
    m = bpy.data.materials.new("EXPORT_Normal%s" % ("_flipZ" if flip_z else ""))
    m.use_nodes = True
    t = m.node_tree
    t.nodes.clear()
    geo = t.nodes.new("ShaderNodeNewGeometry")
    vt = t.nodes.new("ShaderNodeVectorTransform")
    vt.vector_type = 'VECTOR'
    vt.convert_from = 'WORLD'
    vt.convert_to = 'CAMERA'
    t.links.new(geo.outputs["True Normal"], vt.inputs["Vector"])
    prev = vt.outputs["Vector"]
    if flip_z:
        fz = t.nodes.new("ShaderNodeVectorMath")
        fz.operation = 'MULTIPLY'
        fz.inputs[1].default_value = (1.0, 1.0, -1.0)
        t.links.new(prev, fz.inputs[0])
        prev = fz.outputs["Vector"]
    mul = t.nodes.new("ShaderNodeVectorMath")
    mul.operation = 'MULTIPLY'
    mul.inputs[1].default_value = (0.5, 0.5, 0.5)
    add = t.nodes.new("ShaderNodeVectorMath")
    add.operation = 'ADD'
    add.inputs[1].default_value = (0.5, 0.5, 0.5)
    emi = t.nodes.new("ShaderNodeEmission")
    out = t.nodes.new("ShaderNodeOutputMaterial")
    t.links.new(prev, mul.inputs[0])
    t.links.new(mul.outputs["Vector"], add.inputs[0])
    t.links.new(add.outputs["Vector"], emi.inputs["Color"])
    t.links.new(emi.outputs["Emission"], out.inputs["Surface"])
    return m


# ---------------------------------------------------------------- 渲染
def shoot(path, fmt="OPEN_EXR", depth="32", override=None):
    scene.render.engine = 'BLENDER_EEVEE'
    bpy.context.view_layer.material_override = override
    scene.render.image_settings.file_format = fmt
    scene.render.image_settings.color_mode = 'RGB'
    scene.render.image_settings.color_depth = depth
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    return path


def load_px(path):
    """读回像素。img.pixels 是**自下而上**的 float 缓冲。"""
    img = bpy.data.images.load(path)
    w, h, ch = img.size[0], img.size[1], img.channels
    a = np.array(img.pixels[:], dtype=np.float64).reshape(h, w, ch)
    bpy.data.images.remove(img)
    return a


def pixel_of(pt):
    co = world_to_camera_view(scene, cam, Vector(pt))
    return int(round(co.x * (W - 1))), int(round((1.0 - co.y) * (H - 1)))


def read_at(arr, pt, k=2):
    px, py = pixel_of(pt)
    if not (0 <= px < W and 0 <= py < H):
        return None
    row = H - 1 - py                       # pixels 自下而上
    win = arr[max(0, row - k):row + k + 1, max(0, px - k):px + k + 1, :3]
    return np.median(win.reshape(-1, 3), axis=0)


# ---------------------------------------------------------------- 采样点
def _cam_intrinsics():
    """显式内参：返回 (half_w, half_h)，单位归一到"焦距 = 1"。

    不用 cam.data.view_frame()：它返回的四个角点**顺序**没有可靠文档，
    猜错就会把射线指到别处（实测角点顺序猜错时，220 个采样像素只命中 52 个，
    深度误差 51m —— 完全对不上）。
    """
    f = float(cam.data.lens)
    sw = float(cam.data.sensor_width)
    fit = cam.data.sensor_fit          # 'AUTO' / 'HORIZONTAL' / 'VERTICAL'
    ar = float(W) / float(H)
    if fit == 'HORIZONTAL' or (fit == 'AUTO' and ar >= 1.0):
        half_w = sw * 0.5
        half_h = half_w / ar
    else:
        half_h = sw * 0.5
        half_w = half_h * ar
    return half_w / f, half_h / f


def cam_ray(px, py):
    """像素 -> 世界射线。px/py 从**左上**角数，与渲染的像素网格一致。"""
    hw, hh = _cam_intrinsics()
    x = (2.0 * (px + 0.5) / float(W) - 1.0) * hw
    y = (1.0 - 2.0 * (py + 0.5) / float(H)) * hh
    d_local = Vector((x, y, -1.0)).normalized()
    d = (cam.matrix_world.to_3x3() @ d_local).normalized()
    return cam.matrix_world.translation.copy(), d


def _selftest_ray():
    """自检：画面中心的射线必须与相机光轴一致（余弦应≈1）。"""
    _o, d = cam_ray(W // 2, H // 2)
    axis = (cam.matrix_world.to_3x3() @ Vector((0.0, 0.0, -1.0))).normalized()
    return d.dot(axis)


def pick_pixels(n=300, step=None):
    """在画面上撒一批像素，逐个射线求交，返回 (px, py, 命中点, 世界法线)。"""
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    out = []
    step = step or max(1, int(min(W, H) / 30))
    tried = 0
    for py in range(step // 2, H - step // 2, step):
        for px in range(step // 2, W - step // 2, step):
            tried += 1
            o, d = cam_ray(px, py)
            hit, loc, nrm, _idx, _obj, _mat = scene.ray_cast(dg, o, d)
            if not hit:
                continue
            out.append((px, py, loc.copy(), nrm.copy()))
            if len(out) >= n:
                print("    [ray] 试射 %d 条，命中 %d 条" % (tried, len(out)))
                return out
    print("    [ray] 试射 %d 条，命中 %d 条" % (tried, len(out)))
    return out


def read_px(arr, px, py):
    """按 (px, py)（左上原点）取值；arr 是自下而上的。"""
    row = H - 1 - py
    if not (0 <= row < arr.shape[0] and 0 <= px < arr.shape[1]):
        return None
    return arr[row, px, :3]


# ================================================================ 主流程
def main():
    """主体。**必须**由下面的 try/finally 调用：
    脚本中途抛异常时如果不还原，material_override 会留在场景里，
    之后的每一次渲染都会被 override 材质污染（实测踩到过）。
    """
    global NEAR, FAR
    report = []
    def say(s):
        report.append(s)
        print(s)


    say("=" * 70)
    say("EXPORT %s   %dx%d" % (NAME, W, H))
    say("=" * 70)

    # 收紧裁剪面：深度图把 [near, far] 线性映射到 [1,0]，far 太大就没精度
    _n, _f = scene_depth_range()
    say("裁剪面: 原 near=%.4g far=%.4g  ->  导出用 near=%.4g far=%.4g" % (
        _state["clip_start"], _state["clip_end"], _n, _f))
    cam.data.clip_start = _n
    cam.data.clip_end = _f
    NEAR, FAR = _n, _f

    scene.render.resolution_x = W
    scene.render.resolution_y = H
    scene.render.resolution_percentage = 100
    scene.render.use_compositing = False
    scene.render.film_transparent = False
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.look = 'None'
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0

    # ---- 1) 彩模 ----
    p_comb = os.path.join(OUT_DIR, "%s_combined.png" % NAME)
    shoot(p_comb, "PNG", "8", override=None)
    say("[1] 彩模   -> %s" % p_comb)

    # ---- 2) 灰模 ----
    scene.render.engine = 'BLENDER_WORKBENCH'
    sh = scene.display.shading
    sh.light = 'STUDIO'
    sh.color_type = 'SINGLE'
    sh.single_color = (0.55, 0.55, 0.55)
    sh.show_shadows = True
    sh.show_cavity = True
    sh.cavity_type = 'BOTH'
    sh.background_type = 'WORLD'
    p_clay = os.path.join(OUT_DIR, "%s_clay.png" % NAME)
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGB'
    scene.render.image_settings.color_depth = '8'
    scene.render.filepath = p_clay
    bpy.ops.render.render(write_still=True)
    say("[2] 灰模   -> %s" % p_clay)

    # ---- 3) 深度 EXR ----
    scene.render.engine = 'BLENDER_EEVEE'
    m_depth = mat_depth()
    p_dep = os.path.join(OUT_DIR, "%s_depth.exr" % NAME)
    shoot(p_dep, "OPEN_EXR", "32", override=m_depth)
    say("[3] 深度   -> %s" % p_dep)

    # ---- 4) 法线：两种 Z 约定各渲一张，用 ray_cast 真值判定 ----
    say("[4] 法线   -> 渲染两种 Z 约定，用 ray_cast 真值判定")
    samples = pick_pixels(220)
    say("    相机位置 %s  镜头 %.1fmm  传感器 %.1fmm  fit=%s" % (
        tuple(round(v, 3) for v in cam.matrix_world.translation),
        cam.data.lens, cam.data.sensor_width, cam.data.sensor_fit))
    _o0, _d0 = cam_ray(W // 2, H // 2)
    _axis = (cam.matrix_world.to_3x3() @ Vector((0.0, 0.0, -1.0))).normalized()
    say("    中心射线 %s  光轴 %s  余弦 %.6f" % (
        tuple(round(v, 3) for v in _d0), tuple(round(v, 3) for v in _axis),
        _d0.dot(_axis)))
    say("    命中像素样本: %d" % len(samples))
    depth_arr = load_px(p_dep)
    np.save(os.path.join(OUT_DIR, "%s_depth.npy" % NAME),
            depth_arr.astype(np.float32))

    norm_cand = {}
    for flip in (False, True):
        p = os.path.join(OUT_DIR, "%s_normal%s.exr" %
                         (NAME, "_flipZ" if flip else ""))
        m = mat_normal(flip)
        shoot(p, "OPEN_EXR", "32", override=m)
        norm_cand[flip] = (p, load_px(p))


    def normal_truth(nw):
        """相机空间法线真值：只用旋转部分（3x3），不能带平移。"""
        return (cam_inv.to_3x3() @ Vector(nw)).normalized()


    # 分通道误差。**Z 通道**才是判别翻转的依据：
    # 用 max(|Δ|) 会让 X/Y 的误差盖住 Z，两种约定给出相同的数字。
    per_flip = {}
    for flip, (p, arr) in norm_cand.items():
        ex, ey, ez = [], [], []
        for (px, py, loc, nrm) in samples:
            v = read_px(arr, px, py)
            if v is None:
                continue
            t = normal_truth(nrm)
            ex.append(abs(float(v[0]) - (t.x * 0.5 + 0.5)))
            ey.append(abs(float(v[1]) - (t.y * 0.5 + 0.5)))
            ez.append(abs(float(v[2]) - (t.z * 0.5 + 0.5)))
        per_flip[flip] = (ex, ey, ez)
        say("    %-9s 样本 %d  |dx|=%.4f |dy|=%.4f |dz|=%.4f" % (
            "flipZ" if flip else "no-flip", len(ex),
            float(np.mean(ex)) if ex else -1,
            float(np.mean(ey)) if ey else -1,
            float(np.mean(ez)) if ez else -1))

    best_flip = min(per_flip, key=lambda f: float(np.mean(per_flip[f][2])))
    say("    => 采用: %s（按 Z 通道误差）" % ("flipZ" if best_flip else "no-flip"))
    p_norm, norm_arr = norm_cand[best_flip]
    final_norm = os.path.join(OUT_DIR, "%s_normal.exr" % NAME)
    if p_norm != final_norm:
        if os.path.exists(final_norm):
            os.remove(final_norm)
        os.rename(p_norm, final_norm)
        norm_arr = load_px(final_norm)
    np.save(os.path.join(OUT_DIR, "%s_normal.npy" % NAME),
            norm_arr.astype(np.float32))
    say("    法线   -> %s" % final_norm)

    # ---- 5) 深度自检（ray_cast 真值）----
    _hw, _hh = _cam_intrinsics()
    derr, dfoot = [], []
    for (px, py, loc, nrm) in samples:
        d = abs((cam_inv @ loc).z)
        exp = 1.0 - (d - NEAR) / (FAR - NEAR)
        v = read_px(depth_arr, px, py)
        if v is None:
            continue
        derr.append(abs(float(v[0]) - exp))
        # 一个像素在物体上的世界尺寸（米）：掠射面上深度在**一个像素内**
        # 就能变好几厘米，所以绝对误差必须换算成"像素数"才有意义。
        dfoot.append(2.0 * _hh * d / float(H))
    say("[5] 深度自检: 样本 %d" % len(derr))
    if derr:
        a = np.array(derr) * (FAR - NEAR)      # 换成米
        f = np.array(dfoot)
        say("    绝对误差: 中位 %.4f m  P90 %.4f m  最大 %.4f m" % (
            float(np.median(a)), float(np.percentile(a, 90)), float(a.max())))
        ratio = a / np.maximum(f, 1e-9)
        say("    折合像素: 中位 %.2f px  P90 %.2f px  最大 %.2f px" % (
            float(np.median(ratio)), float(np.percentile(ratio, 90)),
            float(ratio.max())))
        say("    像素足迹: 中位 %.4f m（这就是能分辨的最小深度差）" % (
            float(np.median(f))))
        say("    合格率(|误差| < 1 个像素足迹): %.1f%%" % (
            100.0 * float((ratio < 1.0).mean())))

    # 法线最终误差（按选定约定）
    ex, ey, ez = per_flip[best_flip]
    if ez:
        say("[5b] 法线自检(选定约定): |dx|=%.4f |dy|=%.4f |dz|=%.4f" % (
            float(np.mean(ex)), float(np.mean(ey)), float(np.mean(ez))))

    # ---- 6) 清单 ----
    manifest = {
        "name": NAME,
        "resolution": [W, H],
        "engine": "BLENDER_EEVEE",
        "near": NEAR,
        "far": FAR,
        "camera_matrix_world": [list(r) for r in cam.matrix_world],
        "camera_inverse_3x3": [list(r) for r in cam_inv.to_3x3()],
        "lens": cam.data.lens,
        "sensor_width": cam.data.sensor_width,
        "normal_convention": {
            "space": "camera",
            "encoding": "n * 0.5 + 0.5",
            "flip_z": bool(best_flip),
            "truth": "cam_inv.to_3x3() @ n_world  (3x3 rotation only)",
        },
        "depth_convention": {
            "raw": "Camera Data -> View Z Depth (metres, positive)",
            "stored": "linear, remapped near->1, far->0",
            "metres_from_value": "(1 - v) * (far - near) + near",
        },
        "files": {
            "combined": os.path.basename(p_comb),
            "clay": os.path.basename(p_clay),
            "depth_exr": os.path.basename(p_dep),
            "depth_npy": "%s_depth.npy" % NAME,
            "normal_exr": os.path.basename(final_norm),
            "normal_npy": "%s_normal.npy" % NAME,
        },
    }
    mpath = os.path.join(OUT_DIR, "%s_manifest.json" % NAME)
    with open(mpath, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    say("[6] 清单   -> %s" % mpath)

    # ---- 7) 还原场景 ----
    say("    捕获时 override = %s" % _state["override"])
    restore()
    say("    还原后 override = %s" % bpy.context.view_layer.material_override)
    bpy.context.view_layer.update()
    with open(os.path.join(OUT_DIR, "%s_report.txt" % NAME), "w",
              encoding="utf-8") as f:
        f.write("\n".join(report))

    say("[7] 场景已还原（渲染引擎/材质覆盖/视图变换/着色器均已复位）")
    say("EXPORT DONE")


def _cleanup_export_materials():
    """删掉本次导出建的临时材质（还原后已无用户）。"""
    for m in list(bpy.data.materials):
        if m.name.startswith("EXPORT_") and m.users == 0:
            bpy.data.materials.remove(m)


try:
    main()
except Exception:
    import traceback
    traceback.print_exc()
    raise
finally:
    restore()
    _cleanup_export_materials()
    bpy.context.view_layer.update()
    print("[7] 场景已还原（渲染引擎/材质覆盖/视图变换/着色器/相机裁剪面均已复位）")
