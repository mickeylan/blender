"""探针 v12：独立验证 PNG 字节值（用 PIL，不用 Blender 加载器）。

目的：确定 Blender 写出的 PNG 原始字节 与 我们设计的控制值 的关系，
      从而决定 ComfyUI 侧是否需要反 sRGB。
方法：两个常量色块平面（0.25 / 0.75），Raw vs Standard，各 8/16bit，
      直接读 PNG 字节。
"""

import os
import bpy

OUT = r"J:\mickeylan\ai\blender\probe_out"
os.makedirs(OUT, exist_ok=True)
W, H = 128, 64

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
print("Blender", bpy.app.version_string)


def make_plane(name, x, value, size=1.0):
    me = bpy.data.meshes.new(name)
    import bmesh
    bm = bmesh.new(); bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=size*0.5)
    bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new(name, me)
    ob.location = (x, 0, 0)
    scene.collection.objects.link(ob)
    m = bpy.data.materials.new("M_" + name); m.use_nodes = True
    t = m.node_tree; t.nodes.clear()
    emi = t.nodes.new("ShaderNodeEmission")
    emi.inputs["Color"].default_value = (value, value, value, 1.0)
    o = t.nodes.new("ShaderNodeOutputMaterial")
    t.links.new(emi.outputs["Emission"], o.inputs["Surface"])
    ob.data.materials.append(m)
    return ob


make_plane("L", -0.6, 0.25)
make_plane("R", 0.6, 0.75)

cam_data = bpy.data.cameras.new("Cam")
cam = bpy.data.objects.new("Cam", cam_data)
scene.collection.objects.link(cam)
# 俯视：网格在 XY 平面，法线 +Z，相机从 +Z 往下看才不会侧视成线
cam.location = (0, 0, 3.0)
cam_data.lens = 35.0
scene.camera = cam
bpy.context.view_layer.update()

scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x, scene.render.resolution_y = W, H
scene.render.resolution_percentage = 100
scene.render.film_transparent = False

manifest = []
for vt in ("Raw", "Standard", "AgX"):
    try:
        scene.view_settings.view_transform = vt
        try:
            scene.view_settings.look = "None"
        except Exception:
            pass
    except Exception as e:
        print("skip", vt, e)
        continue
    for depth in ("8", "16"):
        scene.render.image_settings.file_format = "PNG"
        scene.render.image_settings.color_mode = "RGB"
        scene.render.image_settings.color_depth = depth
        fn = os.path.join(OUT, f"v12_{vt}_{depth}.png")
        scene.render.filepath = fn
        bpy.ops.render.render(write_still=True)
        manifest.append((vt, depth, fn))
        print(f"  wrote {os.path.basename(fn)}")

# ---- 用外部 PIL 独立读字节 ----
import subprocess
import sys

PIL_SCRIPT = r'''
import sys, json
from PIL import Image
import numpy as np
out = {}
for path in sys.argv[1:]:
    im = Image.open(path)
    a = np.asarray(im.convert("RGB")).astype(np.float64)
    h, w = a.shape[:2]
    L = float(np.median(a[:, int(w*0.28):int(w*0.36), 0])) / 255.0
    R = float(np.median(a[:, int(w*0.64):int(w*0.72), 0])) / 255.0
    out[path] = [round(L, 5), round(R, 5)]
print("__JSON__" + json.dumps(out))
'''

pscript = os.path.join(OUT, "_read_png.py")
with open(pscript, "w", encoding="utf-8") as f:
    f.write(PIL_SCRIPT)

res = subprocess.run([r"D:\python3\python.exe", pscript] + [m[2] for m in manifest],
                     capture_output=True, text=True)
line = [l for l in res.stdout.splitlines() if l.startswith("__JSON__")]
if not line:
    print("PIL 读取失败:")
    print(res.stdout[-2000:])
    print(res.stderr[-2000:])
else:
    import json
    data = json.loads(line[0][len("__JSON__"):])

    def s2l(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    print("\n" + "=" * 78)
    print("PIL 独立读取结果（设计值：左 0.25，右 0.75，线性）")
    print("=" * 78)
    print(f"{'view_transform':<18}{'bit':>5}{'左字节':>10}{'右字节':>10}"
          f"{'左sRGB解码':>12}{'右sRGB解码':>12}{'字节==线性':>12}")
    for vt, depth, fn in manifest:
        L, R = data.get(fn, [None, None])
        if L is None:
            continue
        ll, rl = s2l(L), s2l(R)
        exact = abs(L - 0.25) < 0.01 and abs(R - 0.75) < 0.01
        print(f"{vt:<18}{depth:>5}{L:>10.4f}{R:>10.4f}{ll:>12.4f}{rl:>12.4f}"
              f"{'  YES' if exact else '   no':>12}")

    print("\n" + "=" * 78)
    print("结论")
    print("=" * 78)
    raw8 = data.get(os.path.join(OUT, "v12_Raw_8.png"))
    std8 = data.get(os.path.join(OUT, "v12_Standard_8.png"))
    if raw8 and abs(raw8[0] - 0.25) < 0.01 and abs(raw8[1] - 0.75) < 0.01:
        print("  ✅ Raw + PNG8: 字节值 == 线性值，ComfyUI 直接读即可，无需反 sRGB")
    else:
        print(f"  Raw8 实测: {raw8}")
    if std8:
        ll, rl = s2l(std8[0]), s2l(std8[1])
        ok = abs(ll - 0.25) < 0.01 and abs(rl - 0.75) < 0.01
        print(f"  Standard8: 字节=({std8[0]:.4f},{std8[1]:.4f}) -> sRGB解码=({ll:.4f},{rl:.4f})"
              f" {'✅ 解码后正确，但 ComfyUI 需先反 sRGB' if ok else '❌'}")
