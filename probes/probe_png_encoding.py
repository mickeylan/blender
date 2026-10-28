"""探针 v11：确定 PNG 字节值能否精确等于我们算出的控制值。

问题：Blender 写 8bit PNG 时会套 sRGB OETF，ControlNet 却按原始字节读。
      若不做处理，模型看到的深度分布不是我们设计的。
方案：找能让输出字节 == 线性值的视图变换（Raw?），并测 16bit。
"""

import os
import bpy
import numpy as np

OUT = r"J:\mickeylan\ai\blender\probe_out"
os.makedirs(OUT, exist_ok=True)
W, H = 64, 64

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
print("Blender", bpy.app.version_string)

print("\n--- view_transform 可选 ---")
vt_enum = [i.identifier for i in
           scene.view_settings.bl_rna.properties["view_transform"].enum_items]
print("  ", vt_enum)
print("\n--- image_settings.color_management 可选 ---")
cm_enum = [i.identifier for i in
           scene.render.image_settings.bl_rna.properties["color_management"].enum_items]
print("  ", cm_enum)
print("\n--- color_depth 可选 ---")
print("  ", [i.identifier for i in
             scene.render.image_settings.bl_rna.properties["color_depth"].enum_items])

# 一个已知水平渐变：左 0.0 -> 右 1.0（线性）
bpy.ops.mesh.primitive_plane_add(size=2)
ob = bpy.context.object
m = bpy.data.materials.new("grad")
m.use_nodes = True
t = m.node_tree
t.nodes.clear()
geo = t.nodes.new("ShaderNodeNewGeometry")
tc = t.nodes.new("ShaderNodeTexCoord")
sep = t.nodes.new("ShaderNodeSeparateXYZ")
mr = t.nodes.new("ShaderNodeMapRange")
mr.inputs["From Min"].default_value = -1.0
mr.inputs["From Max"].default_value = 1.0
emi = t.nodes.new("ShaderNodeEmission")
o = t.nodes.new("ShaderNodeOutputMaterial")
t.links.new(tc.outputs["Generated"], sep.inputs["Vector"])
t.links.new(sep.outputs["X"], mr.inputs["Value"])
t.links.new(mr.outputs["Result"], emi.inputs["Color"])
t.links.new(emi.outputs["Emission"], o.inputs["Surface"])
ob.data.materials.append(m)

cam_data = bpy.data.cameras.new("Cam")
cam = bpy.data.objects.new("Cam", cam_data)
scene.collection.objects.link(cam)
cam.location = (0.0, -3.0, 0.0)
cam.rotation_euler = (1.5708, 0.0, 0.0)
scene.camera = cam

scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x, scene.render.resolution_y = W, H
scene.render.resolution_percentage = 100
scene.render.film_transparent = False


def read_bytes(path):
    """读 PNG 的原始 8/16bit 字节（绕过 Blender 的色彩管理）。"""
    with open(path, "rb") as f:
        data = f.read()
    import struct
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not png"
    pos = 8
    idat = b""
    bitdepth = None
    ctype = None
    while pos < len(data):
        ln = struct.unpack(">I", data[pos:pos+4])[0]
        typ = data[pos+4:pos+8]
        chunk = data[pos+8:pos+8+ln]
        if typ == b"IHDR":
            bitdepth = chunk[8]
            ctype = chunk[9]
        elif typ == b"IDAT":
            idat += chunk
        elif typ == b"IEND":
            break
        pos += 12 + ln
    import zlib
    raw = zlib.decompress(idat)
    ch = {0: 1, 2: 3, 4: 2, 6: 4}[ctype]
    bpp = ch * (bitdepth // 8)
    stride = W * bpp
    out = np.zeros((H, stride), dtype=np.uint8)
    prev = np.zeros(stride, dtype=np.uint8)
    p = 0
    for y in range(H):
        ft = raw[p]; p += 1
        line = np.frombuffer(raw[p:p+stride], dtype=np.uint8).copy(); p += stride
        if ft == 1:
            for i in range(bpp, stride):
                line[i] = (int(line[i]) + int(line[i-bpp])) & 0xFF
        elif ft == 2:
            line = (line.astype(int) + prev.astype(int)).astype(np.uint8)
        elif ft == 3:
            for i in range(stride):
                a = int(line[i-bpp]) if i >= bpp else 0
                line[i] = (int(line[i]) + ((a + int(prev[i])) >> 1)) & 0xFF
        elif ft == 4:
            for i in range(stride):
                a = int(line[i-bpp]) if i >= bpp else 0
                b = int(prev[i])
                c = int(prev[i-bpp]) if i >= bpp else 0
                pp = a + b - c
                pa, pb, pc = abs(pp-a), abs(pp-b), abs(pp-c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (int(line[i]) + pr) & 0xFF
        out[y] = line
        prev = line
    if bitdepth == 16:
        arr = out.view(">u2").reshape(H, W, ch).astype(np.float64) / 65535.0
    else:
        arr = out.reshape(H, W, ch).astype(np.float64) / 255.0
    return arr, bitdepth, ctype


def srgb_to_linear(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


print("\n" + "=" * 72)
print("渐变测试：左端应=0, 右端应=1（线性）")
print("=" * 72)
print(f"{'view_transform':<20}{'depth':>7}{'左端字节':>10}{'右端字节':>10}"
      f"{'左端线性':>10}{'右端线性':>10}{'字节==线性?':>12}")

candidates = []
for v in ("Raw", "Standard", "AgX", "Filmic", "False Color"):
    try:
        scene.view_settings.view_transform = v
        candidates.append(v)
    except Exception:
        pass
print("  实际可用的 view_transform:", candidates)
results = {}
for vt in candidates:
    scene.view_settings.view_transform = vt
    try:
        scene.view_settings.look = "None"
    except Exception:
        pass
    for depth in ("8", "16"):
        if depth not in cm_enum and depth == "16":
            pass
        scene.render.image_settings.file_format = "PNG"
        scene.render.image_settings.color_mode = "RGB"
        scene.render.image_settings.color_depth = depth
        fn = os.path.join(OUT, f"v11_{vt}_{depth}.png")
        scene.render.filepath = fn
        bpy.ops.render.render(write_still=True)
        arr, bd, ct = read_bytes(fn)
        left = float(np.median(arr[:, 2:6, 0]))
        right = float(np.median(arr[:, -6:-2, 0]))
        ll, rl = srgb_to_linear(left), srgb_to_linear(right)
        # 若字节直接就是线性值，则 left≈0, right≈1
        exact = (abs(left) < 0.02) and (abs(right - 1.0) < 0.02)
        results[(vt, depth)] = (left, right, exact)
        print(f"{vt:<20}{depth:>7}{left:>10.4f}{right:>10.4f}{ll:>10.4f}{rl:>10.4f}"
              f"{'  YES' if exact else '   no':>12}")

print("\n" + "=" * 72)
print("结论")
print("=" * 72)
winners = [k for k, v in results.items() if v[2]]
if winners:
    print("  字节值 == 线性值 的组合:", winners)
else:
    print("  没有组合能让字节直接等于线性值。")
    print("  => 方案: 深度/法线用 EXR(32bit, 线性) 输出，或在 ComfyUI 侧做一次 sRGB→linear 还原。")
    print("     对比 sRGB 编码后的反解值与真值：")
    for (vt, depth), (l, r, _) in results.items():
        if vt in ("Standard", "Raw"):
            ll, rl = srgb_to_linear(l), srgb_to_linear(r)
            print(f"     {vt:<10}{depth:>3}bit  解码后 左={ll:.4f} 右={rl:.4f}")
