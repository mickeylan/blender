"""探针 v2：Blender 5.2 白模导出三通道实测（clay / depth / normal）。

合成器 API 在 5.2 变动大（scene.node_tree 已删、OutputFile 无 base_path），
故改用**材质驱动**方案：Camera Data -> View Z Depth 出深度，
Vector Transform(World->Camera) + Geometry.Normal 出相机空间法线。
引擎无关、不受合成器 API 变更影响。

运行:
  "D:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe" ^
      --background --python probe_passes2.py
"""

import os
import bmesh
import bpy
import numpy as np

OUT = r"J:\mickeylan\ai\blender\probe_out"
os.makedirs(OUT, exist_ok=True)

W, H = 320, 180
NEAR, FAR = 0.5, 30.0          # 深度归一化区间（米）

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
print("=" * 64)
print("Blender", bpy.app.version_string, "| build", bpy.app.build_date)
print("=" * 64)

# ---------------- 场景 ----------------
def add_box(name, loc, scale):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    ob.location, ob.scale = loc, scale
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


objs = [
    add_plane("Ground", 60, (0, 0, 0)),
    add_box("Near", (-2.0, -3.0, 0.5), (0.6, 0.6, 1.0)),
    add_box("CharProxy", (0.0, 1.0, 0.875), (0.45, 0.30, 1.75)),
    add_box("Far", (2.5, 8.0, 0.5), (0.6, 0.6, 1.0)),
]

cam_data = bpy.data.cameras.new("Cam")
cam_data.lens = 35.0
cam_data.sensor_fit = "HORIZONTAL"
cam_data.clip_start = NEAR
cam_data.clip_end = FAR
cam = bpy.data.objects.new("Cam", cam_data)
scene.collection.objects.link(cam)
cam.location = (0.0, -6.0, 1.6)
cam.rotation_euler = (1.5359, 0.0, 0.0)
scene.camera = cam

sun_data = bpy.data.lights.new("Sun", type="SUN")
sun_data.energy = 3.0
sun = bpy.data.objects.new("Sun", sun_data)
scene.collection.objects.link(sun)
sun.location = (4, -4, 8)
sun.rotation_euler = (0.7, 0.2, 0.3)

scene.render.resolution_x = W
scene.render.resolution_y = H
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGB"
scene.render.image_settings.color_depth = "8"


def render_to(engine, fname, material=None):
    """切换引擎（可选给所有物体套材质）并渲染到 OUT/fname。"""
    scene.render.engine = engine
    scene.render.filepath = os.path.join(OUT, fname)
    for ob in objs:
        ob.data.materials.clear()
        if material is not None:
            ob.data.materials.append(material)
    bpy.ops.render.render(write_still=True)
    print(f"  rendered {engine:<18} -> {fname}")


def measure(fname, label):
    p = os.path.join(OUT, fname)
    if not os.path.exists(p):
        print(f"  !! {fname} 不存在")
        return None
    img = bpy.data.images.load(p)
    w, h, ch = img.size[0], img.size[1], img.channels
    arr = np.array(img.pixels[:], dtype=np.float64).reshape(h, w, ch)
    img.reload()
    g = arr[:, :, 0]
    print(f"  {label:<12} {w}x{h} ch={ch} | R:[{g.min():.4f},{g.max():.4f}] "
          f"mean={g.mean():.4f} | G mean={arr[:,:,1].mean():.4f} B mean={arr[:,:,2].mean():.4f}")
    return arr


# ---------------- 通道 1：clay（Workbench 平涂） ----------------
print("\n[1] clay / Workbench")
scene.render.engine = "BLENDER_WORKBENCH"
try:
    scene.display.shading.light = "FLAT"
    scene.display.shading.color_type = "SINGLE"
    scene.display.shading.single_color = (0.72, 0.72, 0.72)
    scene.display.shading.show_shadow = False
    print("  Workbench FLAT + SINGLE color 设置 OK")
except Exception as e:                                    # noqa: BLE001
    print("  Workbench 设置失败:", e)
render_to("BLENDER_WORKBENCH", "clay.png")

# ---------------- 通道 2：depth（材质驱动） ----------------
print("\n[2] depth  (Camera Data -> View Z Depth -> MapRange 反转)")
md = bpy.data.materials.new("M_depth")
md.use_nodes = True
nt = md.node_tree
nt.nodes.clear()
cam_n = nt.nodes.new("ShaderNodeCameraData")            # View Z Depth / View Distance
mr = nt.nodes.new("ShaderNodeMapRange")
mr.interpolation_type = "LINEAR"
# From [NEAR..FAR] -> To [1..0]  (近=白，远=黑，ControlNet 约定)
mr.inputs["From Min"].default_value = NEAR
mr.inputs["From Max"].default_value = FAR
mr.inputs["To Min"].default_value = 1.0
mr.inputs["To Max"].default_value = 0.0
emi = nt.nodes.new("ShaderNodeEmission")
out = nt.nodes.new("ShaderNodeOutputMaterial")
nt.links.new(cam_n.outputs["View Z Depth"], mr.inputs["Value"])
nt.links.new(mr.outputs["Result"], emi.inputs["Color"])
nt.links.new(emi.outputs["Emission"], out.inputs["Surface"])
print("  节点: CameraData / MapRange / Emission / Output ->",
      [n.bl_idname for n in nt.nodes])
render_to("BLENDER_EEVEE", "depth_cn.png", md)

# ---------------- 通道 3：normal（相机空间） ----------------
print("\n[3] normal (Geometry.Normal -> VectorTransform World->Camera -> *0.5+0.5)")
mn = bpy.data.materials.new("M_normal")
mn.use_nodes = True
nt2 = mn.node_tree
nt2.nodes.clear()
geo = nt2.nodes.new("ShaderNodeNewGeometry")
vt = nt2.nodes.new("ShaderNodeVectorTransform")
vt.vector_type = "VECTOR"
vt.convert_from = "WORLD"
vt.convert_to = "CAMERA"
mul = nt2.nodes.new("ShaderNodeVectorMath")
mul.operation = "MULTIPLY"
mul.inputs[1].default_value = (0.5, 0.5, 0.5)
add = nt2.nodes.new("ShaderNodeVectorMath")
add.operation = "ADD"
add.inputs[1].default_value = (0.5, 0.5, 0.5)
emi2 = nt2.nodes.new("ShaderNodeEmission")
out2 = nt2.nodes.new("ShaderNodeOutputMaterial")
nt2.links.new(geo.outputs["Normal"], vt.inputs["Vector"])
nt2.links.new(vt.outputs["Vector"], mul.inputs[0])
nt2.links.new(mul.outputs["Vector"], add.inputs[0])
nt2.links.new(add.outputs["Vector"], emi2.inputs["Color"])
nt2.links.new(emi2.outputs["Emission"], out2.inputs["Surface"])
render_to("BLENDER_EEVEE", "normal_cam.png", mn)

# ---------------- 通道 4：合成器 Z 通道对照 ----------------
print("\n[4] 合成器 API 现状核对")
vl = scene.view_layers[0]
vl.use_pass_z = True
vl.use_pass_normal = True
vl.use_pass_mist = True
ng = bpy.data.node_groups.new("Comp", "CompositorNodeTree")
scene.compositing_node_group = ng
rl = ng.nodes.new("CompositorNodeRLayers")
print("  启用 use_pass_z/normal/mist 后, Render Layers 输出:")
for o in rl.outputs:
    print(f"    {o.identifier:<14} enabled={o.enabled}")
fo = ng.nodes.new("CompositorNodeOutputFile")
attrs = [a for a in dir(fo) if not a.startswith("_")
         and any(k in a.lower() for k in ("path", "dir", "file", "slot", "format"))]
print("  OutputFile 路径相关属性:", attrs)

# ---------------- 测量 ----------------
print("\n" + "=" * 64)
print("实测结果")
print("=" * 64)
clay = measure("clay.png", "clay")
dep = measure("depth_cn.png", "depth_cn")
nrm = measure("normal_cam.png", "normal_cam")

if dep is not None:
    print("\n--- 深度图采样点（近=白/1.0，远=黑/0.0）---")
    pts = [("Near 盒 (~3.2m)", 0.28, 0.55), ("CharProxy (~7.1m)", 0.50, 0.52),
           ("Far 盒 (~14.1m)", 0.73, 0.50), ("天空/无物体", 0.05, 0.05),
           ("近处地面", 0.50, 0.92)]
    for label, fx, fy in pts:
        x = int(fx * (W - 1)); y = int((1.0 - fy) * (H - 1))
        patch = dep[max(0, y - 3):y + 4, max(0, x - 3):x + 4, 0]
        v = float(np.median(patch))
        # 由归一化值反推米数： depth01 = 1 - (d-NEAR)/(FAR-NEAR)
        d_est = NEAR + (1.0 - v) * (FAR - NEAR)
        print(f"  {label:<22} 像素={v:.4f}  -> 反推距离 {d_est:6.2f} m")

if nrm is not None:
    print("\n--- 法线图（相机空间）校验 ---")
    print("  面向相机的平面应 R~0.5 G~0.5 B~1.0（+Z 朝向相机）")
    ys, xs = int(0.45 * H), int(0.50 * W)
    print(f"  CharProxy 正面像素 RGBA = {nrm[H-1-ys, xs]}")

print("\n产出:")
for f in sorted(os.listdir(OUT)):
    print(f"   {f:<22} {os.path.getsize(os.path.join(OUT,f)):>9,} B")
