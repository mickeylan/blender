"""探针 v10（收尾）：定死法线通道的编码约定 + 验证 group output 机制。

方法：用 mathutils 直接算相机空间真值（不手写矩阵），与材质渲染实测值逐点比对，
判定 (a) Blender 相机空间 Z 朝向，(b) ControlNet 约定需要怎么翻转。
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
cam = bpy.data.objects.new("Cam", cam_data)
scene.collection.objects.link(cam)
cam.location = (0.0, -6.0, 1.6); cam.rotation_euler = (1.5359, 0.0, 0.0)
scene.camera = cam
sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", type="SUN"))
sun.data.energy = 3.0; sun.location = (4, -4, 8); sun.rotation_euler = (0.7, 0.2, 0.3)
scene.collection.objects.link(sun)
bpy.context.view_layer.update()

scene.render.resolution_x, scene.render.resolution_y = W, H
scene.render.resolution_percentage = 100
scene.view_settings.view_transform = "Standard"
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGB"
scene.render.image_settings.color_depth = "8"

M = cam.matrix_world.inverted()          # world -> camera
print("\n--- mathutils 真值（world->camera）---")
for nm, wn in (("竖直面(朝相机)", Vector((0, -1, 0))), ("地面(朝上)", Vector((0, 0, 1)))):
    cn = (M @ wn).normalized()
    print(f"  {nm:<16} world={tuple(round(v,3) for v in wn)} -> camera=({cn.x:+.4f}, {cn.y:+.4f}, {cn.z:+.4f})")


def mat_normal(tag, flip_z, use_true_normal):
    m = bpy.data.materials.new(f"M_{tag}"); m.use_nodes = True
    t = m.node_tree; t.nodes.clear()
    geo = t.nodes.new("ShaderNodeNewGeometry")
    src = geo.outputs["True Normal"] if use_true_normal else geo.outputs["Normal"]
    vt = t.nodes.new("ShaderNodeVectorTransform")
    vt.vector_type, vt.convert_from, vt.convert_to = "VECTOR", "WORLD", "CAMERA"
    prev = vt.outputs["Vector"]
    t.links.new(src, vt.inputs["Vector"])
    if flip_z:
        fz = t.nodes.new("ShaderNodeVectorMath"); fz.operation = "MULTIPLY"
        fz.inputs[1].default_value = (1.0, 1.0, -1.0)
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


def shoot(fname, mat, engine="BLENDER_EEVEE"):
    scene.render.engine = engine
    for ob in objs:
        ob.data.materials.clear(); ob.data.materials.append(mat)
    scene.render.filepath = os.path.join(OUT, fname)
    bpy.ops.render.render(write_still=True)
    return os.path.join(OUT, fname)


def load(path):
    img = bpy.data.images.load(path)
    w, h, ch = img.size[0], img.size[1], img.channels
    a = np.array(img.pixels[:], dtype=np.float64).reshape(h, w, ch)
    img.reload(); return a


def s2l(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def pixel_of(pt):
    co = world_to_camera_view(scene, cam, Vector(pt))
    return int(round(co.x * (W - 1))), int(round((1.0 - co.y) * (H - 1)))


def read_lin(arr, pt):
    px, py = pixel_of(pt)
    if not (0 <= px < W and 0 <= py < H):
        return None
    row = H - 1 - py
    win = arr[max(0, row-2):row+3, max(0, px-2):px+3, :3]
    med = np.median(win.reshape(-1, 3), axis=0)
    return s2l(med) * 2.0 - 1.0        # 反编码 -> [-1,1]


PROBES = [("Near", (-0.9, -2.15, 1.0)), ("CharProxy", (0.0, 0.85, 0.875)),
          ("Far", (2.5, 7.70, 0.5)), ("GroundMid", (0.0, 0.0, 0.0))]
WORLD_N = {"Near": Vector((0, -1, 0)), "CharProxy": Vector((0, -1, 0)),
           "Far": Vector((0, -1, 0)), "GroundMid": Vector((0, 0, 1))}

variants = [
    ("noflip_shading", False, False),
    ("flip_shading", True, False),
    ("noflip_true", False, True),
    ("flip_true", True, True),
]
print("\n" + "=" * 78)
print("法线材质 4 变体 vs mathutils 相机空间真值")
print("=" * 78)
best = None
for tag, flip, true_n in variants:
    a = load(shoot(f"v10_{tag}.png", mat_normal(tag, flip, true_n)))
    print(f"\n--- {tag} ---")
    errs = []
    for nm, pt in PROBES:
        v = read_lin(a, pt)
        if v is None:
            print(f"  {nm:<11} 越界"); continue
        truth = (M @ WORLD_N[nm]).normalized()
        err = float(np.linalg.norm(v - truth))
        errs.append(err)
        print(f"  {nm:<11} 实测=({v[0]:+.3f},{v[1]:+.3f},{v[2]:+.3f}) "
              f"真值=({truth.x:+.3f},{truth.y:+.3f},{truth.z:+.3f}) err={err:.4f}")
    if errs:
        me = float(np.mean(errs))
        print(f"  平均误差 = {me:.5f}")
        if best is None or me < best[1]:
            best = (tag, me)
print(f"\n>>> 最贴合 Blender 相机空间的变体: {best}")

# 目标约定：ControlNet normal 期望 +Z 指向「远离相机/进入画面」
if best:
    tag = best[0]
    flip = tag.startswith("flip")
    a = load(shoot("v10_best.png", mat_normal("best", flip, "true" in tag)))
    print("\n" + "=" * 78)
    print("最终编码方案")
    print("=" * 78)
    for nm, pt in PROBES:
        v = read_lin(a, pt)
        if v is None:
            continue
        enc = (v * 0.5 + 0.5)
        print(f"  {nm:<11} 相机空间=({v[0]:+.3f},{v[1]:+.3f},{v[2]:+.3f}) "
              f"-> 编码 RGB=({enc[0]:.3f},{enc[1]:.3f},{enc[2]:.3f})")
    print("\n  判据: 竖直面(朝相机) 编码后应 ≈ (0.5, 0.5, 1.0)  [Z 指向远离相机]")
    print("        地面 编码后应 ≈ (0.5, 1.0, 0.5)  [法线朝上]")
    need_flip = not best[0].startswith("flip")
    print(f"\n  >>> 结论: Blender 相机空间 Z {'需要' if need_flip else '不需要'} 取反才符合 ControlNet 约定")
    if need_flip:
        print("      即编码公式: rgb = (n.x, n.y, -n.z) * 0.5 + 0.5")
    else:
        print("      即编码公式: rgb = (n.x, n.y,  n.z) * 0.5 + 0.5")

# ---------- group output 机制自检：用 Combined 图像 ----------
print("\n" + "=" * 78)
print("group output 机制自检（接 Combined 图像）")
print("=" * 78)
ng = bpy.data.node_groups.new("Comp2", "CompositorNodeTree")
scene.compositing_node_group = ng
ng.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
go = ng.nodes.new("NodeGroupOutput")
rl = ng.nodes.new("CompositorNodeRLayers")
ng.links.new(rl.outputs["Image"], go.inputs[0])
scene.render.engine = "BLENDER_EEVEE"
for ob in objs:
    ob.data.materials.clear()
scene.render.image_settings.file_format = "PNG"
scene.render.filepath = os.path.join(OUT, "v10_group_combined.png")
bpy.ops.render.render(write_still=True)
ga = load(os.path.join(OUT, "v10_group_combined.png"))
print(f"  group output 的 Combined 图: 尺寸 {ga.shape[1]}x{ga.shape[0]}  "
      f"R均值={ga[:,:,0].mean():.4f} 最大={ga[:,:,0].max():.4f}")
print("  (若 R 全为 0 -> group 内 Render Layers 拿不到渲染结果，5.2 应改用 Group Input)")
