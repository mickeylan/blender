"""探针 v9：用合成器 node group 的【组输出】把某个 pass 选为场景输出，
再走常规渲染保存（EXR 32bit），这样 Blender 自己就能读回验证。

先内省 5.2 的 group interface / GroupOutput API。
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

# ---------- 内省 group interface API ----------
ng = bpy.data.node_groups.new("Comp", "CompositorNodeTree")
print("\n--- ng.interface API ---")
print("dir:", [a for a in dir(ng.interface) if not a.startswith("_")])
try:
    print("new_socket 签名:", ng.interface.new_socket.__doc__)
except Exception as e:                                    # noqa: BLE001
    print("new_socket doc err:", e)

print("\n--- NodeGroupOutput 节点 ---")
go = ng.nodes.new("NodeGroupOutput")
print("inputs:", [(s.identifier, s.bl_idname) for s in go.inputs])
print("outputs:", [(s.identifier, s.bl_idname) for s in go.outputs])

# ---------- 建场景 ----------
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

scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = 8
scene.render.resolution_x, scene.render.resolution_y = W, H
scene.render.resolution_percentage = 100
scene.view_settings.view_transform = "Standard"

vl = scene.view_layers[0]
vl.use_pass_z = True
vl.use_pass_normal = True

scene.compositing_node_group = ng
rl = ng.nodes.new("CompositorNodeRLayers")
print("\nRender Layers 输出:", [o.identifier for o in rl.outputs if o.enabled])

# ---------- 建组输出接口 ----------
print("\n--- 建组输出 socket ---")
try:
    s = ng.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    print("  new_socket OK ->", s.name, s.socket_type, "in_out=", s.in_out)
except Exception as e:                                    # noqa: BLE001
    print("  new_socket 失败:", type(e).__name__, e)
    try:
        s = ng.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    except Exception as e2:                               # noqa: BLE001
        print("  retry 失败:", e2)
        s = None

go = ng.nodes.new("NodeGroupOutput")
print("  GroupOutput inputs now:", [(s.identifier, s.bl_idname) for s in go.inputs])


def select_pass(socket_name, tag):
    """把指定 pass 接到组输出，渲染保存为 EXR。"""
    for l in list(ng.links):
        if l.to_node == go:
            ng.links.remove(l)
    ng.links.new(rl.outputs[socket_name], go.inputs[0])
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_depth = "32"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.filepath = os.path.join(OUT, f"v9_{tag}.exr")
    bpy.ops.render.render(write_still=True)
    return os.path.join(OUT, f"v9_{tag}.exr")


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
    row = H - 1 - py
    win = arr[max(0, row-2):row+3, max(0, px-2):px+3, :]
    return np.median(win.reshape(-1, win.shape[2]), axis=0)


PROBES = [("Near", (-0.9, -2.15, 1.0)), ("CharProxy", (0.0, 0.85, 0.875)),
          ("Far", (2.5, 7.70, 0.5)), ("GroundMid", (0.0, 0.0, 0.0))]
cam_inv = cam.matrix_world.inverted()
R3 = cam_inv.to_3x3()
truth_world = {"Near": Vector((0, -1, 0)), "CharProxy": Vector((0, -1, 0)),
               "Far": Vector((0, -1, 0)), "GroundMid": Vector((0, 0, 1))}
truth_cam = {k: (R3 @ v).normalized() for k, v in truth_world.items()}

# ---------- 深度 ----------
print("\n" + "=" * 76)
print("Depth pass (经组输出保存)")
print("=" * 76)
p = select_pass("Depth", "depth")
a = load(p)
print(f"尺寸 {a.shape[1]}x{a.shape[0]} ch={a.shape[2]}")
print(f"{'物体':<11}{'真值|m|':>9}{'pass R':>11}{'G':>9}{'B':>9}{'误差':>10}")
errs = []
for nm, pt in PROBES:
    v = read(a, pt)
    if v is None:
        print(f"{nm:<11} 越界"); continue
    truth = abs((cam_inv @ Vector(pt)).z)
    errs.append(abs(abs(v[0]) - truth))
    print(f"{nm:<11}{truth:>9.3f}{v[0]:>11.4f}{v[1]:>9.4f}{v[2]:>9.4f}{abs(v[0])-truth:>+10.5f}")
print(f"  平均绝对误差 = {np.mean(errs):.6f}")
print(f"  全图 R 范围 = [{a[:,:,0].min():.4f}, {a[:,:,0].max():.4f}]")

# ---------- 法线 ----------
print("\n" + "=" * 76)
print("Normal pass  —— 判读空间")
print("=" * 76)
p = select_pass("Normal", "normal")
a = load(p)
print(f"尺寸 {a.shape[1]}x{a.shape[0]} ch={a.shape[2]}")
print(f"{'物体':<11}{'世界真值':>24}{'相机真值':>24}{'pass 读数':>24}{'|v|':>8}")
for nm, pt in PROBES:
    v = read(a, pt)
    if v is None:
        print(f"{nm:<11} 越界"); continue
    tw, tc = truth_world[nm], truth_cam[nm]
    print(f"{nm:<11}"
          f"({tw.x:+.3f},{tw.y:+.3f},{tw.z:+.3f})   "
          f"({tc.x:+.3f},{tc.y:+.3f},{tc.z:+.3f})   "
          f"({v[0]:+.3f},{v[1]:+.3f},{v[2]:+.3f})  {np.linalg.norm(v[:3]):.4f}")
print("\n  判据: pass≈世界真值->世界空间; pass≈相机真值->相机空间")
