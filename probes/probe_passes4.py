"""探针 v4：定死 Blender 5.2 控制图导出契约。

要验证的三件事：
  (1) Camera Data 的 "View Z Depth" 是正还是负、是否线性（用原始值直渲验证）
  (2) 默认 AgX 视图变换是否会静默破坏控制图（A/B 对照）
  (3) 相机空间法线编码是否正确

真值全部由相机矩阵算出，采样点由 world_to_camera_view 投影得到。
"""

import os
import bmesh
import bpy
import numpy as np
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

OUT = r"J:\mickeylan\ai\blender\probe_out"
os.makedirs(OUT, exist_ok=True)

W, H = 320, 180
NEAR, FAR = 0.5, 30.0

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
print("Blender", bpy.app.version_string)


def add_box(name, loc, scale):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new(); bmesh.ops.create_cube(bm, size=1.0); bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new(name, me); ob.location, ob.scale = loc, scale
    scene.collection.objects.link(ob); return ob


def add_plane(name, size, loc):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new(); bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=size*0.5)
    bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new(name, me); ob.location = loc
    scene.collection.objects.link(ob); return ob


named = {
    "Ground": add_plane("Ground", 60, (0, 0, 0)),
    "Near": add_box("Near", (-0.9, -2.0, 1.0), (0.30, 0.30, 1.0)),   # 括高至入画
    "CharProxy": add_box("CharProxy", (0.0, 1.0, 0.875), (0.45, 0.30, 1.75)),
    "Far": add_box("Far", (2.5, 8.0, 0.5), (0.6, 0.6, 1.0)),
}
objs = list(named.values())

cam_data = bpy.data.cameras.new("Cam")
cam_data.lens = 35.0; cam_data.sensor_fit = "HORIZONTAL"
cam_data.clip_start, cam_data.clip_end = NEAR, FAR
cam = bpy.data.objects.new("Cam", cam_data)
scene.collection.objects.link(cam)
cam.location = (0.0, -6.0, 1.6)
cam.rotation_euler = (1.5359, 0.0, 0.0)
scene.camera = cam
bpy.context.view_layer.update()

scene.render.resolution_x, scene.render.resolution_y = W, H
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGB"


def mat_depth(invert, tag):
    """深度材质。invert=True -> ControlNet 约定(近白远黑)；False -> 原始 ViewZ/30。"""
    m = bpy.data.materials.new(f"M_{tag}"); m.use_nodes = True
    t = m.node_tree; t.nodes.clear()
    cd = t.nodes.new("ShaderNodeCameraData")
    mr = t.nodes.new("ShaderNodeMapRange"); mr.interpolation_type = "LINEAR"
    if invert:
        mr.inputs["From Min"].default_value = NEAR
        mr.inputs["From Max"].default_value = FAR
        mr.inputs["To Min"].default_value = 1.0
        mr.inputs["To Max"].default_value = 0.0
        src = cd.outputs["View Z Depth"]
    else:
        mr.inputs["From Min"].default_value = 0.0
        mr.inputs["From Max"].default_value = FAR
        mr.inputs["To Min"].default_value = 0.0
        mr.inputs["To Max"].default_value = 1.0
        src = cd.outputs["View Z Depth"]
    emi = t.nodes.new("ShaderNodeEmission")
    o = t.nodes.new("ShaderNodeOutputMaterial")
    t.links.new(src, mr.inputs["Value"])
    t.links.new(mr.outputs["Result"], emi.inputs["Color"])
    t.links.new(emi.outputs["Emission"], o.inputs["Surface"])
    return m


def mat_normal():
    m = bpy.data.materials.new("M_normal"); m.use_nodes = True
    t = m.node_tree; t.nodes.clear()
    geo = t.nodes.new("ShaderNodeNewGeometry")
    vt = t.nodes.new("ShaderNodeVectorTransform")
    vt.vector_type, vt.convert_from, vt.convert_to = "VECTOR", "WORLD", "CAMERA"
    mul = t.nodes.new("ShaderNodeVectorMath"); mul.operation = "MULTIPLY"
    mul.inputs[1].default_value = (0.5, 0.5, 0.5)
    add = t.nodes.new("ShaderNodeVectorMath"); add.operation = "ADD"
    add.inputs[1].default_value = (0.5, 0.5, 0.5)
    emi = t.nodes.new("ShaderNodeEmission"); o = t.nodes.new("ShaderNodeOutputMaterial")
    t.links.new(geo.outputs["Normal"], vt.inputs["Vector"])
    t.links.new(vt.outputs["Vector"], mul.inputs[0])
    t.links.new(mul.outputs["Vector"], add.inputs[0])
    t.links.new(add.outputs["Vector"], emi.inputs["Color"])
    t.links.new(emi.outputs["Emission"], o.inputs["Surface"])
    return m


def shoot(fname, mat):
    scene.render.engine = "BLENDER_EEVEE"
    for ob in objs:
        ob.data.materials.clear()
        ob.data.materials.append(mat)
    scene.render.image_settings.color_depth = "8"
    scene.render.filepath = os.path.join(OUT, fname)
    bpy.ops.render.render(write_still=True)
    return os.path.join(OUT, fname)


def load(path):
    img = bpy.data.images.load(path)
    w, h, ch = img.size[0], img.size[1], img.channels
    a = np.array(img.pixels[:], dtype=np.float64).reshape(h, w, ch)
    img.reload(); return a


def cam_dist(world_pt):
    """相机空间 Z 的绝对值 = 沿视轴的深度（米）。"""
    p = cam.matrix_world.inverted() @ Vector(world_pt)
    return abs(p.z)


def pixel_of(world_pt):
    co = world_to_camera_view(scene, cam, Vector(world_pt))
    return int(round(co.x * (W - 1))), int(round((1.0 - co.y) * (H - 1)))


def read(arr, world_pt):
    px, py = pixel_of(world_pt)
    if not (0 <= px < W and 0 <= py < H):
        return None, (px, py)
    # ⚠ img.pixels 是自下而上存储，py 是自上而下 -> 必须翻转
    row = H - 1 - py
    win = arr[max(0, row-2):row+3, max(0, px-2):px+3, :3]
    return np.median(win.reshape(-1, 3), axis=0), (px, py)


# 物体正面中心（朝向相机那一面的中心），避免采到侧壁
# 物体正面中心（朝向相机那一面 = -Y 面），避免采到侧壁或盒内部
PROBES = [
    ("Near",      (-0.9, -2.15, 1.0)),
    ("CharProxy", (0.0,   0.85, 0.875)),
    ("Far",       (2.5,   7.70, 0.5)),
    ("GroundMid", (0.0,   0.00, 0.0)),
]

m_inv = mat_depth(True, "inv")
m_raw = mat_depth(False, "raw")
m_nrm = mat_normal()

# ============ (1) 原始 View Z Depth，Standard，验证符号与线性 ============
scene.view_settings.view_transform = "Standard"
scene.view_settings.look = "None"
print("\n" + "=" * 72)
print("(1) 原始 ViewZ/FAR 直渲 (Standard)  -> 验证 View Z Depth 的符号与线性")
print("=" * 72)
a_raw = load(shoot("depth_raw.png", m_raw))
print(f"{'物体':<12}{'相机Z真值(m)':>13}{'期望 raw':>10}{'实测 raw':>10}{'误差':>9}")
sign_ok = True
for nm, pt in PROBES:
    d = cam_dist(pt); e = d / FAR
    v, pxy = read(a_raw, pt)
    if v is None:
        print(f"{nm:<12} 投影越界 {pxy}"); continue
    err = v[0] - e
    if abs(err) > 0.02:
        sign_ok = False
    print(f"{nm:<12}{d:>13.3f}{e:>10.4f}{v[0]:>10.4f}{err:>+9.4f}")
print(f"  => View Z Depth 为【正值、线性、单位=米】: {'确认' if sign_ok else '未确认'}")
print(f"  全图范围: [{a_raw[:,:,0].min():.4f}, {a_raw[:,:,0].max():.4f}]")

# ============ (2) ControlNet 约定深度：AgX vs Standard ============
print("\n" + "=" * 72)
print("(2) ControlNet 深度图 (近=白 远=黑)：AgX 默认 vs Standard")
print("=" * 72)
scene.view_settings.view_transform = "AgX"
a_agx = load(shoot("depth_agx.png", m_inv))
scene.view_settings.view_transform = "Standard"
a_std = load(shoot("depth_std.png", m_inv))

hdr = f"{'物体':<12}{'真值(m)':>9}{'期望01':>9}{'AgX实测':>10}{'AgX误差':>10}{'Std实测':>10}{'Std误差':>10}"
print(hdr)
agx_err, std_err = [], []
for nm, pt in PROBES:
    d = cam_dist(pt)
    e = 1.0 - (d - NEAR) / (FAR - NEAR)
    va, _ = read(a_agx, pt)
    vs, _ = read(a_std, pt)
    if va is None or vs is None:
        print(f"{nm:<12} 越界"); continue
    agx_err.append(abs(va[0] - e)); std_err.append(abs(vs[0] - e))
    print(f"{nm:<12}{d:>9.3f}{e:>9.4f}{va[0]:>10.4f}{va[0]-e:>+10.4f}"
          f"{vs[0]:>10.4f}{vs[0]-e:>+10.4f}")
if agx_err and std_err:
    print(f"\n  平均绝对误差  AgX = {np.mean(agx_err):.4f}   Standard = {np.mean(std_err):.4f}")
    print(f"  最大值可达    AgX max={a_agx[:,:,0].max():.4f}  Std max={a_std[:,:,0].max():.4f}")
    verdict = "确认：AgX 破坏控制图" if np.mean(agx_err) > 3 * max(np.mean(std_err), 1e-6) else "两者接近，假设不成立"
    print(f"  => {verdict}")

# ============ (3) 相机空间法线 ============
print("\n" + "=" * 72)
print("(3) 相机空间法线编码校验 (Standard)")
print("=" * 72)
a_n = load(shoot("normal_std.png", m_nrm))
for nm, pt in PROBES:
    v, pxy = read(a_n, pt)
    if v is None:
        print(f"{nm:<12} 越界"); continue
    print(f"  {nm:<12} 像素{str(pxy):<12} RGB=({v[0]:.4f}, {v[1]:.4f}, {v[2]:.4f})")
print("  期望：正对相机的竖直面 ≈ (0.5, 0.5, 1.0)；朝上的地面 B 分量应偏小、G 偏大")

print("\n产出:")
for f in sorted(os.listdir(OUT)):
    if f.startswith("depth") or f.startswith("normal") or f == "clay.png":
        print(f"   {f:<20} {os.path.getsize(os.path.join(OUT,f)):>9,} B")
