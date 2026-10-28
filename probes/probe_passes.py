"""探针：实测 Blender 5.2 的 Depth / Normal 通道约定，为白模导出契约取真值。

运行:
    "D:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe" --background --python probe_passes.py

产出 probe_out/:
    combined.png        普通渲染（clay 参考）
    depth.exr           原始 Z 通道（float，单位=米）
    normal.exr          原始法线通道（float）
    depth_cn.png        ControlNet 约定的深度图（近=白，远=黑，8bit）
    depth_raw.png       未反转的归一化深度（对照用）
控制台打印各通道的实测数值范围，用于判定约定。
"""

import os
import bmesh
import bpy
import numpy as np

OUT = r"J:\mickeylan\ai\blender\probe_out"
os.makedirs(OUT, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

print("=" * 60)
print("Blender version:", bpy.app.version_string)
print("build date     :", bpy.app.build_date)
print("=" * 60)


def add_box(name, loc, scale):
    """用 data API 建盒子，避开 background 模式下的 ops 上下文问题。"""
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    ob.location = loc
    ob.scale = scale
    scene.collection.objects.link(ob)
    return ob


def add_plane(name, size, loc):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=size * 0.5)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    ob.location = loc
    scene.collection.objects.link(ob)
    return ob


# ---- 场景：地面 + 近/中/远三个盒子 + 一个 1.75m 人形代理 ----
add_plane("Ground", 60, (0, 0, 0))
add_box("Near", (-2.0, -3.0, 0.5), (0.6, 0.6, 1.0))    # 距相机 ~3m
add_box("CharProxy", (0.0, 1.0, 0.875), (0.45, 0.30, 1.75))  # 距相机 ~7m，身高 1.75m
add_box("Far", (2.5, 8.0, 0.5), (0.6, 0.6, 1.0))       # 距相机 ~14m

# ---- 相机：35mm，眼高 1.6m ----
cam_data = bpy.data.cameras.new("Cam")
cam_data.lens = 35.0
cam_data.sensor_fit = "HORIZONTAL"
cam = bpy.data.objects.new("Cam", cam_data)
scene.collection.objects.link(cam)
cam.location = (0.0, -6.0, 1.6)
cam.rotation_euler = (1.5359, 0.0, 0.0)  # ~88° 略微下俯
scene.camera = cam

# ---- 灯光（仅为 combined 图；深度/法线不依赖光照）----
light_data = bpy.data.lights.new("Sun", type="SUN")
light_data.energy = 3.0
light = bpy.data.objects.new("Sun", light_data)
scene.collection.objects.link(light)
light.location = (4, -4, 8)
light.rotation_euler = (0.7, 0.2, 0.3)

# ---- 渲染设置 ----
scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = 16
scene.render.resolution_x = 320
scene.render.resolution_y = 180
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.filepath = os.path.join(OUT, "combined.png")

# ---- 启用 Z / Normal 通道 ----
vl = scene.view_layers[0]
vl.use_pass_z = True
vl.use_pass_normal = True

scene.use_nodes = True
nt = scene.node_tree
nt.nodes.clear()

rl = nt.nodes.new("CompositorNodeRLayers")

# float EXR 输出，保留全精度用于测量
fo_exr = nt.nodes.new("CompositorNodeOutputFile")
fo_exr.base_path = OUT
fo_exr.format.file_format = "OPEN_EXR"
fo_exr.format.color_depth = "32"
fo_exr.file_slots.clear()
fo_exr.file_slots.new("depth")
fo_exr.file_slots.new("normal")
nt.links.new(rl.outputs["Depth"], fo_exr.inputs["depth"])
nt.links.new(rl.outputs["Normal"], fo_exr.inputs["normal"])

# ControlNet 约定深度：归一化 -> 反转(1-x) -> 8bit PNG
norm = nt.nodes.new("CompositorNodeNormalize")
nt.links.new(rl.outputs["Depth"], norm.inputs[0])

inv = nt.nodes.new("CompositorNodeMath")
inv.operation = "SUBTRACT"
inv.inputs[0].default_value = 1.0   # 1 - normalized
nt.links.new(norm.outputs[0], inv.inputs[1])

fo_png = nt.nodes.new("CompositorNodeOutputFile")
fo_png.base_path = OUT
fo_png.format.file_format = "PNG"
fo_png.format.color_depth = "8"
fo_png.file_slots.clear()
fo_png.file_slots.new("depth_cn")
fo_png.file_slots.new("depth_raw")
nt.links.new(inv.outputs[0], fo_png.inputs["depth_cn"])
nt.links.new(norm.outputs[0], fo_png.inputs["depth_raw"])

bpy.ops.render.render(write_still=True)

# ---- 读回 EXR，测量真实数值范围 ----
def measure(path):
    img = bpy.data.images.load(path)
    px = np.array(img.pixels[:], dtype=np.float64)
    w, h = img.size
    px = px.reshape(h, w, img.channels)
    img.reload()
    return px, w, h, img.channels


print()
print("=" * 60)
print("通道实测")
print("=" * 60)

for name in ("depth", "normal"):
    p = os.path.join(OUT, f"{name}0001.exr")
    if not os.path.exists(p):
        print(f"{name}: 文件不存在 -> {p}")
        continue
    px, w, h, ch = measure(p)
    print(f"\n--- {name}0001.exr  ({w}x{h}, {ch} ch) ---")
    for c in range(min(ch, 4)):
        band = px[:, :, c]
        nz = band[band != 0]
        print(f"  ch{c}: min={band.min():+.6f} max={band.max():+.6f} "
              f"mean={band.mean():+.6f} | 非零占比={100.0*nz.size/band.size:.1f}%")

# 三个已知距离点上的深度读数（验证 Z = 相机空间线性距离，单位米）
p = os.path.join(OUT, "depth0001.exr")
if os.path.exists(p):
    d, w, h, ch = measure(p)
    dz = d[:, :, 0]
    # 图像坐标 y 轴向上；取每个盒子的屏幕中心附近
    print("\n--- 已知物体的深度读数（应为相机到该点的直线距离，单位米）---")
    probes = [("Near  (~3.2m)", 0.30, 0.52), ("CharProxy (~7.1m)", 0.50, 0.55),
              ("Far   (~14.1m)", 0.72, 0.50), ("Ground 前方", 0.50, 0.90)]
    for label, fx, fy in probes:
        x = int(fx * (w - 1))
        y = int((1.0 - fy) * (h - 1))
        patch = dz[max(0, y-3):y+4, max(0, x-3):x+4]
        print(f"  {label:<20} 窗口中位深度 = {np.median(patch):8.3f} m")

print("\n--- ControlNet 深度图 (depth_cn0001.png) ---")
pc = os.path.join(OUT, "depth_cn0001.png")
if os.path.exists(pc):
    ci = bpy.data.images.load(pc)
    cpx = np.array(ci.pixels[:], dtype=np.float64).reshape(ci.size[1], ci.size[0], ci.channels)
    print(f"  8bit 归一化后范围: [{cpx.min():.4f}, {cpx.max():.4f}]  "
          f"(近处应接近 1.0/白，远处接近 0.0/黑)")
    ci.reload()
else:
    print("  未生成")

print("\n产出目录:", OUT)
for f in sorted(os.listdir(OUT)):
    print("   ", f, os.path.getsize(os.path.join(OUT, f)), "bytes")
