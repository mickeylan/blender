"""探针 v5：定死控制图导出契约（最终验证）。

验证三件事：
  (1) Standard 视图变换下，PNG 的偏差是否完全由 sRGB 编码解释（解码后应误差≈0）
  (2) OpenEXR 是否直接存线性值（免解码）
  (3) 相机空间法线 Z 取反后是否符合 ControlNet 约定 (0.5,0.5,1.0)
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
    "Near": add_box("Near", (-0.9, -2.0, 1.0), (0.30, 0.30, 1.0)),
    "CharProxy": add_box("CharProxy", (0.0, 1.0, 0.875), (0.45, 0.30, 1.75)),
    "Far": add_box("Far", (2.5, 8.0, 0.5), (0.6, 0.6, 1.0)),
}
objs = list(named.values())

cam_data = bpy.data.cameras.new("Cam")
cam_data.lens = 35.0; cam_data.sensor_fit = "HORIZONTAL"
cam_data.clip_start, cam_data.clip_end = NEAR, FAR
cam = bpy.data.objects.new("Cam", cam_data)
scene.collection.objects.link(cam)
cam.location = (0.0, -6.0, 1.6); cam.rotation_euler = (1.5359, 0.0, 0.0)
scene.camera = cam
bpy.context.view_layer.update()

scene.render.resolution_x, scene.render.resolution_y = W, H
scene.render.resolution_percentage = 100
scene.view_settings.view_transform = "Standard"
scene.view_settings.look = "None"


def mat_depth(tag):
    m = bpy.data.materials.new(f"M_d_{tag}"); m.use_nodes = True
    t = m.node_tree; t.nodes.clear()
    cd = t.nodes.new("ShaderNodeCameraData")
    mr = t.nodes.new("ShaderNodeMapRange"); mr.interpolation_type = "LINEAR"
    mr.inputs["From Min"].default_value = NEAR
    mr.inputs["From Max"].default_value = FAR
    mr.inputs["To Min"].default_value = 1.0
    mr.inputs["To Max"].default_value = 0.0
    emi = t.nodes.new("ShaderNodeEmission"); o = t.nodes.new("ShaderNodeOutputMaterial")
    t.links.new(cd.outputs["View Z Depth"], mr.inputs["Value"])
    t.links.new(mr.outputs["Result"], emi.inputs["Color"])
    t.links.new(emi.outputs["Emission"], o.inputs["Surface"])
    return m


def mat_normal(tag, flip_z):
    m = bpy.data.materials.new(f"M_n_{tag}"); m.use_nodes = True
    t = m.node_tree; t.nodes.clear()
    geo = t.nodes.new("ShaderNodeNewGeometry")
    vt = t.nodes.new("ShaderNodeVectorTransform")
    vt.vector_type, vt.convert_from, vt.convert_to = "VECTOR", "WORLD", "CAMERA"
    prev = vt.outputs["Vector"]
    if flip_z:
        fz = t.nodes.new("ShaderNodeVectorMath"); fz.operation = "MULTIPLY"
        fz.inputs[1].default_value = (1.0, 1.0, -1.0)   # Blender 相机看向 -Z
        t.links.new(prev, fz.inputs[0]); prev = fz.outputs["Vector"]
    mul = t.nodes.new("ShaderNodeVectorMath"); mul.operation = "MULTIPLY"
    mul.inputs[1].default_value = (0.5, 0.5, 0.5)
    add = t.nodes.new("ShaderNodeVectorMath"); add.operation = "ADD"
    add.inputs[1].default_value = (0.5, 0.5, 0.5)
    emi = t.nodes.new("ShaderNodeEmission"); o = t.nodes.new("ShaderNodeOutputMaterial")
    t.links.new(prev, mul.inputs[0])
    t.links.new(mul.outputs["Vector"], add.inputs[0])
    t.links.new(add.outputs["Vector"], emi.inputs["Color"])
    t.links.new(emi.outputs["Emission"], o.inputs["Surface"])
    return m


def shoot(fname, mat, fmt="PNG", depth="8"):
    scene.render.engine = "BLENDER_EEVEE"
    for ob in objs:
        ob.data.materials.clear(); ob.data.materials.append(mat)
    scene.render.image_settings.file_format = fmt
    if fmt == "PNG":
        scene.render.image_settings.color_mode = "RGB"
        scene.render.image_settings.color_depth = depth
    else:
        scene.render.image_settings.color_mode = "RGB"
        scene.render.image_settings.color_depth = depth
    scene.render.filepath = os.path.join(OUT, fname)
    bpy.ops.render.render(write_still=True)
    p = scene.render.filepath
    return p if os.path.exists(p) else os.path.join(OUT, fname)


def load(path):
    img = bpy.data.images.load(path)
    w, h, ch = img.size[0], img.size[1], img.channels
    a = np.array(img.pixels[:], dtype=np.float64).reshape(h, w, ch)
    img.reload(); return a


def pixel_of(pt):
    co = world_to_camera_view(scene, cam, Vector(pt))
    return int(round(co.x * (W - 1))), int(round((1.0 - co.y) * (H - 1)))


def read(arr, pt):
    px, py = pixel_of(pt)
    if not (0 <= px < W and 0 <= py < H):
        return None
    row = H - 1 - py                       # pixels 自下而上
    win = arr[max(0, row-2):row+3, max(0, px-2):px+3, :3]
    return np.median(win.reshape(-1, 3), axis=0)


def s2l(c):
    """sRGB -> 线性"""
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def cam_dist(pt):
    return abs((cam.matrix_world.inverted() @ Vector(pt)).z)


PROBES = [("Near", (-0.9, -2.15, 1.0)), ("CharProxy", (0.0, 0.85, 0.875)),
          ("Far", (2.5, 7.70, 0.5)), ("GroundMid", (0.0, 0.0, 0.0))]
m_d = mat_depth("x")

print("\n" + "=" * 74)
print("(1)(2) 深度：PNG(sRGB) 解码后 vs EXR(线性) 直接读")
print("=" * 74)
png = load(shoot("v5_depth.png", m_d, "PNG", "8"))
exr_path = shoot("v5_depth.exr", m_d, "OPEN_EXR", "32")
exr = load(exr_path) if os.path.exists(exr_path) else None

print(f"{'物体':<11}{'真值m':>8}{'期望':>8}{'PNG原值':>9}{'PNG解码':>9}{'解码误差':>10}"
      + (f"{'EXR值':>9}{'EXR误差':>10}" if exr is not None else ""))
errs_png, errs_exr = [], []
for nm, pt in PROBES:
    d = cam_dist(pt); e = 1.0 - (d - NEAR) / (FAR - NEAR)
    vp = read(png, pt)
    if vp is None:
        print(f"{nm:<11} 越界"); continue
    lin = float(s2l(vp[0]))
    errs_png.append(abs(lin - e))
    line = f"{nm:<11}{d:>8.3f}{e:>8.4f}{vp[0]:>9.4f}{lin:>9.4f}{lin-e:>+10.5f}"
    if exr is not None:
        ve = read(exr, pt)
        if ve is not None:
            errs_exr.append(abs(ve[0] - e))
            line += f"{ve[0]:>9.4f}{ve[0]-e:>+10.5f}"
    print(line)
print(f"\n  PNG(sRGB解码后) 平均绝对误差 = {np.mean(errs_png):.6f}")
if errs_exr:
    print(f"  EXR(线性直读)   平均绝对误差 = {np.mean(errs_exr):.6f}")
print("  判据: 误差 < 0.005 即认为该路径可精确还原米制深度")

print("\n  AgX 对照（同样的点，看是否偏离线性）:")
scene.view_settings.view_transform = "AgX"
agx = load(shoot("v5_depth_agx.png", m_d, "PNG", "8"))
scene.view_settings.view_transform = "Standard"
for nm, pt in PROBES:
    d = cam_dist(pt); e = 1.0 - (d - NEAR) / (FAR - NEAR)
    va = read(agx, pt); vs = read(png, pt)
    if va is None:
        continue
    la, ls = float(s2l(va[0])), float(s2l(vs[0]))
    print(f"    {nm:<11} 期望{e:>7.4f} | Standard解码{ls:>7.4f} (err{ls-e:+.4f})"
          f" | AgX解码{la:>7.4f} (err{la-e:+.4f})")

print("\n" + "=" * 74)
print("(3) 法线：Z 取反前 vs 取反后（期望正对相机的竖直面 = 0.5,0.5,1.0）")
print("=" * 74)
n_raw = load(shoot("v5_normal_noflip.png", mat_normal("nf", False), "PNG", "8"))
n_flip = load(shoot("v5_normal_flip.png", mat_normal("f", True), "PNG", "8"))
print(f"{'物体':<11}{'Z取反前(linear)':>26}{'Z取反后(linear)':>26}")
for nm, pt in PROBES:
    a = read(n_raw, pt); b = read(n_flip, pt)
    if a is None:
        print(f"{nm:<11} 越界"); continue
    la, lb = s2l(a[:3]), s2l(b[:3])
    print(f"{nm:<11}   ({la[0]:.3f},{la[1]:.3f},{la[2]:.3f})"
          f"          ({lb[0]:.3f},{lb[1]:.3f},{lb[2]:.3f})")
print("\n  判据: 竖直面(CharProxy/Near/Far) 取反后应 ≈ (0.5, 0.5, 1.0)")
print("        地面(GroundMid) 应 ≈ (0.5, 1.0, 0.5)（法线朝上，在相机空间指向 +Y）")
