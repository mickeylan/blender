"""探针 v3：验证「AgX 视图变换会静默破坏控制图」这一假设。

对照实验：同一场景，分别在 AgX（默认）与 Standard（关闭色彩管理）下渲染深度图，
采样点用相机投影矩阵精确计算，不再硬编码比例。
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
    ob = bpy.data.objects.new(name, me)
    ob.location, ob.scale = loc, scale
    scene.collection.objects.link(ob)
    return ob


def add_plane(name, size, loc):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new(); bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=size*0.5)
    bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new(name, me)
    ob.location = loc
    scene.collection.objects.link(ob)
    return ob


named = {
    "Ground": add_plane("Ground", 60, (0, 0, 0)),
    "Near": add_box("Near", (-2.0, -3.0, 0.5), (0.6, 0.6, 1.0)),
    "CharProxy": add_box("CharProxy", (0.0, 1.0, 0.875), (0.45, 0.30, 1.75)),
    "Far": add_box("Far", (2.5, 8.0, 0.5), (0.6, 0.6, 1.0)),
}
objs = list(named.values())

cam_data = bpy.data.cameras.new("Cam")
cam_data.lens = 35.0
cam_data.sensor_fit = "HORIZONTAL"
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

# --- 深度材质 ---
md = bpy.data.materials.new("M_depth"); md.use_nodes = True
nt = md.node_tree; nt.nodes.clear()
cam_n = nt.nodes.new("ShaderNodeCameraData")
mr = nt.nodes.new("ShaderNodeMapRange"); mr.interpolation_type = "LINEAR"
mr.inputs["From Min"].default_value = NEAR
mr.inputs["From Max"].default_value = FAR
mr.inputs["To Min"].default_value = 1.0
mr.inputs["To Max"].default_value = 0.0
emi = nt.nodes.new("ShaderNodeEmission")
out = nt.nodes.new("ShaderNodeOutputMaterial")
nt.links.new(cam_n.outputs["View Z Depth"], mr.inputs["Value"])
nt.links.new(mr.outputs["Result"], emi.inputs["Color"])
nt.links.new(emi.outputs["Emission"], out.inputs["Surface"])

# --- 法线材质 ---
mn = bpy.data.materials.new("M_normal"); mn.use_nodes = True
n2 = mn.node_tree; n2.nodes.clear()
geo = n2.nodes.new("ShaderNodeNewGeometry")
vt = n2.nodes.new("ShaderNodeVectorTransform")
vt.vector_type, vt.convert_from, vt.convert_to = "VECTOR", "WORLD", "CAMERA"
mul = n2.nodes.new("ShaderNodeVectorMath"); mul.operation = "MULTIPLY"
mul.inputs[1].default_value = (0.5, 0.5, 0.5)
add = n2.nodes.new("ShaderNodeVectorMath"); add.operation = "ADD"
add.inputs[1].default_value = (0.5, 0.5, 0.5)
emi2 = n2.nodes.new("ShaderNodeEmission")
out2 = n2.nodes.new("ShaderNodeOutputMaterial")
n2.links.new(geo.outputs["Normal"], vt.inputs["Vector"])
n2.links.new(vt.outputs["Vector"], mul.inputs[0])
n2.links.new(mul.outputs["Vector"], add.inputs[0])
n2.links.new(add.outputs["Vector"], emi2.inputs["Color"])
n2.links.new(emi2.outputs["Emission"], out2.inputs["Surface"])


def apply(mat):
    for ob in objs:
        ob.data.materials.clear()
        if mat is not None:
            ob.data.materials.append(mat)


def shoot(tag, mat, depth8="8"):
    scene.render.engine = "BLENDER_EEVEE"
    apply(mat)
    scene.render.image_settings.color_depth = depth8
    fn = f"{tag}.png"
    scene.render.filepath = os.path.join(OUT, fn)
    bpy.ops.render.render(write_still=True)
    return os.path.join(OUT, fn)


def load(path):
    img = bpy.data.images.load(path)
    w, h, ch = img.size[0], img.size[1], img.channels
    a = np.array(img.pixels[:], dtype=np.float64).reshape(h, w, ch)
    img.reload()
    return a


def sample(arr, name, ob):
    """把物体原点投影到像素，取 3x3 中位数。返回 (像素值RGB, 相机空间Z真值)"""
    co = world_to_camera_view(scene, cam, ob.matrix_world.translation)
    px = int(round(co.x * (W - 1)))
    py = int(round((1.0 - co.y) * (H - 1)))
    if not (0 <= px < W and 0 <= py < H):
        return None, None, (px, py)
    win = arr[max(0, py-2):py+3, max(0, px-2):px+3, :3]
    med = np.median(win.reshape(-1, 3), axis=0)
    cam_z = (cam.matrix_world.inverted() @ ob.matrix_world.translation).z
    return med, cam_z, (px, py)


def expected(cam_z):
    return 1.0 - (cam_z - NEAR) / (FAR - NEAR)


print("\n" + "=" * 70)
print("对照组 A：默认色彩管理（AgX）")
print("=" * 70)
print("view_transform =", scene.view_settings.view_transform, "| look =", scene.view_settings.look)
pA = shoot("depth_agx", md)
aA = load(pA)
print(f"{'物体':<12}{'相机Z真值':>10}{'期望01':>9}{'实测01':>9}{'误差':>9}")
for nm in ("Near", "CharProxy", "Far"):
    med, cz, pxy = sample(aA, nm, named[nm])
    if med is None:
        print(f"{nm:<12} 投影越界 {pxy}"); continue
    e = expected(cz)
    print(f"{nm:<12}{cz:>10.3f}{e:>9.4f}{med[0]:>9.4f}{med[0]-e:>+9.4f}")
print(f"  全图 R 范围: [{aA[:,:,0].min():.4f}, {aA[:,:,0].max():.4f}]")

print("\n" + "=" * 70)
print("对照组 B：Standard（关闭色彩管理）")
print("=" * 70)
scene.view_settings.view_transform = "Standard"
scene.view_settings.look = "None"
scene.view_settings.use_curve = False
print("view_transform =", scene.view_settings.view_transform, "| look =", scene.view_settings.look)
pB = shoot("depth_std", md)
aB = load(pB)
print(f"{'物体':<12}{'相机Z真值':>10}{'期望01':>9}{'实测01':>9}{'误差':>9}")
ok = 0; tot = 0
for nm in ("Near", "CharProxy", "Far"):
    med, cz, pxy = sample(aB, nm, named[nm])
    if med is None:
        print(f"{nm:<12} 投影越界 {pxy}"); continue
    e = expected(cz)
    err = med[0] - e
    tot += 1
    if abs(err) < 0.02:
        ok += 1
    print(f"{nm:<12}{cz:>10.3f}{e:>9.4f}{med[0]:>9.4f}{err:>+9.4f}")
print(f"  全图 R 范围: [{aB[:,:,0].min():.4f}, {aB[:,:,0].max():.4f}]")
print(f"\n  >>> Standard 下误差<0.02 的采样点: {ok}/{tot}")

print("\n" + "=" * 70)
print("法线图校验（Standard）")
print("=" * 70)
pN = shoot("normal_std", mn)
aN = load(pN)
med, cz, pxy = sample(aN, "CharProxy", named["CharProxy"])
print(f"  CharProxy 正面 像素{pxy} RGB = ({med[0]:.4f}, {med[1]:.4f}, {med[2]:.4f})")
print("  期望（正对相机的竖直面）≈ (0.5, 0.5, 1.0)")
med2, _, _ = sample(aN, "Ground", named["Ground"])
if med2 is not None:
    print(f"  Ground(原点处)      RGB = ({med2[0]:.4f}, {med2[1]:.4f}, {med2[2]:.4f})  期望≈水平面向上")

print("\n--- 结论判据 ---")
print("若 B 组误差≈0 而 A 组误差大，则确认：控制图必须关闭色彩管理(Standard)。")
