"""探针 v7：定死法线通道 + 确认多通道 EXR 导出。

要点：
  - 5.2 OutputFile 的 file_output_items.new() 签名是 (socket_type, name)
  - 逐槽设置 format（每个 item 自己有 format）
  - 解析真值：盒子正面法线在【世界空间】是 (0,-1,0)；若 pass 读出 (0,0,1) 则是相机空间
  - 备选路线：材质驱动 True Normal（几何法线，非着色法线）
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

scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = 8
scene.render.resolution_x, scene.render.resolution_y = W, H
scene.render.resolution_percentage = 100
scene.view_settings.view_transform = "Standard"

# ============ 路线 1：原生 pass + 合成器 OutputFile ============
vl = scene.view_layers[0]
vl.use_pass_z = True
vl.use_pass_normal = True

ng = bpy.data.node_groups.new("Comp", "CompositorNodeTree")
scene.compositing_node_group = ng
rl = ng.nodes.new("CompositorNodeRLayers")
print("\nRender Layers 输出:", [o.identifier for o in rl.outputs if o.enabled])

fo = ng.nodes.new("CompositorNodeOutputFile")
fo.directory = OUT
fo.file_name = "v7"
print("\n--- 建槽 ---")
for stype, nm in (("RGBA", "Depth"), ("RGBA", "Normal")):
    try:
        it = fo.file_output_items.new(stype, nm)
        print(f"  new({stype!r}, {nm!r}) OK -> name={it.name!r}")
        if hasattr(it, "format"):
            it.format.file_format = "OPEN_EXR"
            it.format.color_depth = "32"
            it.format.color_mode = "RGBA"
            print(f"     item.format -> {it.format.file_format} {it.format.color_depth} {it.format.color_mode}")
    except Exception as e:                                # noqa: BLE001
        print(f"  new({stype!r}, {nm!r}) 失败: {type(e).__name__}: {e}")

print("items:", [(i.name, getattr(i, 'socket_type', '?')) for i in fo.file_output_items])
print("fo.inputs:", [(s.identifier, s.bl_idname) for s in fo.inputs])

# 连线：Depth -> 槽0, Normal -> 槽1
try:
    ng.links.new(rl.outputs["Depth"], fo.inputs[0])
    print("  linked Depth -> inputs[0] OK")
except Exception as e:                                    # noqa: BLE001
    print("  link Depth 失败:", e)
try:
    ng.links.new(rl.outputs["Normal"], fo.inputs[1])
    print("  linked Normal -> inputs[1] OK")
except Exception as e:                                    # noqa: BLE001
    print("  link Normal 失败:", e)

scene.render.filepath = os.path.join(OUT, "v7_combined.png")
bpy.ops.render.render(write_still=True)

print("\n产出:")
for f in sorted(os.listdir(OUT)):
    if f.startswith("v7"):
        print(f"   {f:<30} {os.path.getsize(os.path.join(OUT,f)):>9,} B")


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

# 解析真值：相机空间正对相机的面法线
cam_inv = cam.matrix_world.inverted()
print("\n" + "=" * 74)
print("解析真值")
print("=" * 74)
print("  相机矩阵旋转部分（列向量）:")
for r in range(3):
    print("   ", "  ".join(f"{cam_inv[r][c]:+7.4f}" for c in range(3)))
print("  相机沿自身 -Z 观察 => 世界 +Y 方向")
print("  盒子正面（朝相机）世界法线 = (0,-1,0)")
w_n = Vector((0.0, -1.0, 0.0))
c_n = (cam_inv.to_3x3() @ w_n).normalized()
print(f"  变换到相机空间 = ({c_n.x:+.4f}, {c_n.y:+.4f}, {c_n.z:+.4f})")
g_n = Vector((0.0, 0.0, 1.0))
cg = (cam_inv.to_3x3() @ g_n).normalized()
print(f"  地面法线(0,0,1) 相机空间 = ({cg.x:+.4f}, {cg.y:+.4f}, {cg.z:+.4f})")

# ============ 找导出的文件并验证 ============
print("\n" + "=" * 74)
print("验证")
print("=" * 74)
exrs = [f for f in sorted(os.listdir(OUT)) if f.lower().endswith(".exr") and f.startswith("v7")]
for f in exrs:
    a = load(os.path.join(OUT, f))
    print(f"\n--- {f}  ({a.shape[1]}x{a.shape[0]}, ch={a.shape[2]}) ---")
    for nm, pt in PROBES:
        v = read(a, pt)
        if v is None:
            print(f"  {nm:<11} 越界"); continue
        print(f"  {nm:<11} ({v[0]:+8.4f}, {v[1]:+8.4f}, {v[2]:+8.4f})")
    print(f"  全图范围 X[{a[:,:,0].min():+.3f},{a[:,:,0].max():+.3f}] "
          f"Y[{a[:,:,1].min():+.3f},{a[:,:,1].max():+.3f}] "
          f"Z[{a[:,:,2].min():+.3f},{a[:,:,2].max():+.3f}]")
