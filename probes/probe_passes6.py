"""探针 v6：用 5.2 原生合成器 pass 导出 Depth / Normal（EXR 线性），并对真值验证。

5.2 API 变化点：
  - scene.node_tree 已删除 -> scene.compositing_node_group（NodeGroup）
  - CompositorNodeOutputFile.base_path 已删除 -> directory / file_name / file_output_items
  - use_pass_* 必须在创建 Render Layers 节点【之前】打开，否则插槽不出现
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

# ---- 先开 pass，再建 Render Layers 节点 ----
vl = scene.view_layers[0]
vl.use_pass_z = True
vl.use_pass_normal = True
vl.use_pass_mist = True

ng = bpy.data.node_groups.new("Comp", "CompositorNodeTree")
scene.compositing_node_group = ng
rl = ng.nodes.new("CompositorNodeRLayers")
print("\nRender Layers 可用输出:", [o.identifier for o in rl.outputs if o.enabled])

fo = ng.nodes.new("CompositorNodeOutputFile")
print("OutputFile 属性: directory=%r file_name=%r" % (fo.directory, fo.file_name))
print("file_output_items 初始:", [(it.name, it.socket_type if hasattr(it,'socket_type') else '?')
                                for it in fo.file_output_items])
# 探查 item 的可用属性
if len(fo.file_output_items):
    it0 = fo.file_output_items[0]
    print("item 属性:", [a for a in dir(it0) if not a.startswith("_")
                       and a in ("name", "path", "socket_type", "use_file_extension", "format")])

fo.directory = OUT
fo.format.file_format = "OPEN_EXR"
fo.format.color_depth = "32"
fo.format.color_mode = "RGB"

# 把 Depth / Normal 接到两个 slot
try:
    items = fo.file_output_items
    # 5.2: 通过 add() 新增或直接改现有 item 的 name
    while len(items) < 2:
        try:
            items.add()
        except Exception:
            ng.links.new(rl.outputs["Depth"], fo.inputs.new("DEPTH_TMP"))
            break
    names = [i.name for i in fo.file_output_items]
    print("items after setup:", names)
except Exception as e:                                    # noqa: BLE001
    print("file_output_items 操作失败:", e)

linked = []
for want in ("Depth", "Normal"):
    src = rl.outputs[want]
    tgt = None
    for inp in fo.inputs:
        if not inp.is_linked:
            tgt = inp
            break
    if tgt is not None:
        ng.links.new(src, tgt)
        linked.append((want, tgt.name))
print("已连接:", linked)

scene.render.filepath = os.path.join(OUT, "v6_combined.png")
bpy.ops.render.render(write_still=True)

print("\n产出文件:")
produced = []
for f in sorted(os.listdir(OUT)):
    if f.startswith("v6"):
        produced.append(f)
        print(f"   {f:<28} {os.path.getsize(os.path.join(OUT,f)):>9,} B")


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

# 找到 Depth / Normal 的 EXR
depth_f = normal_f = None
for f in produced:
    low = f.lower()
    if "depth" in low or "z" in low.split("_")[0]:
        depth_f = depth_f or os.path.join(OUT, f)
for f in produced:
    if "normal" in f.lower():
        normal_f = os.path.join(OUT, f)
# 若命名不含关键字，按连接顺序推断
if depth_f is None and len(produced) >= 2:
    cands = [os.path.join(OUT, f) for f in produced if f.lower().endswith(".exr")]
    if len(cands) >= 2:
        depth_f, normal_f = cands[0], cands[1]

print("\n" + "=" * 74)
print("Depth pass 验证（应为相机空间线性深度，单位米；注意可能是负值）")
print("=" * 74)
if depth_f and os.path.exists(depth_f):
    print("文件:", os.path.basename(depth_f))
    dz = load(depth_f)
    print(f"{'物体':<11}{'相机Z真值m':>12}{'pass读数':>12}{'|读数|':>10}{'误差':>10}")
    for nm, pt in PROBES:
        v = read(dz, pt)
        if v is None:
            print(f"{nm:<11} 越界"); continue
        truth = abs((cam.matrix_world.inverted() @ Vector(pt)).z)
        d = v[0]
        print(f"{nm:<11}{truth:>12.3f}{d:>12.4f}{abs(d):>10.4f}{abs(d)-truth:>+10.5f}")
    print(f"  全图范围: [{dz[:,:,0].min():.4f}, {dz[:,:,0].max():.4f}]")
else:
    print("!! 未找到 Depth EXR")

print("\n" + "=" * 74)
print("Normal pass 验证（Blender 文档称相机空间；看 Z 分量符号）")
print("=" * 74)
if normal_f and os.path.exists(normal_f):
    print("文件:", os.path.basename(normal_f))
    nz = load(normal_f)
    print(f"{'物体':<11}{'X':>10}{'Y':>10}{'Z':>10}   期望(正对相机竖直面)")
    for nm, pt in PROBES:
        v = read(nz, pt)
        if v is None:
            print(f"{nm:<11} 越界"); continue
        exp = "(0,0,±1)" if nm != "GroundMid" else "(0,±1,0) 法线朝上"
        print(f"{nm:<11}{v[0]:>10.4f}{v[1]:>10.4f}{v[2]:>10.4f}   {exp}")
    print(f"  全图 Z 范围: [{nz[:,:,2].min():.4f}, {nz[:,:,2].max():.4f}]")
else:
    print("!! 未找到 Normal EXR")
