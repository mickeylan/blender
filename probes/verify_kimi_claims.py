"""核实 kimi 的两条具体指控：屋檐尺寸、起翘形态。

kimi 说："屋檐尺寸-宽 FAIL"、"屋檐尺寸-深 FAIL"、"屋顶缺少起翘形态 FAIL"。
用几何数值核对，而不是再问一个模型。
"""
import sys
sys.path.insert(0, r"J:\mickeylan\ai\blender")
import ai_loop

s = ai_loop.Session()
s.connect()

code = '''
import bpy
from mathutils import Vector as V
bpy.context.view_layer.update()
def dims(name):
    o = bpy.data.objects.get(name)
    if o is None:
        return None
    c = [o.matrix_world @ V(v) for v in o.bound_box]
    d = (max(p.x for p in c)-min(p.x for p in c),
         max(p.y for p in c)-min(p.y for p in c),
         max(p.z for p in c)-min(p.z for p in c))
    return tuple(round(v, 3) for v in d)

print("Base 宽深高 =", dims("Base_Pier_L"))
# 基座整体：左右墙垛 + 拱上墙
allbase = [o for o in bpy.data.objects if o.name.startswith("Base_")]
pts = [o.matrix_world @ V(v) for o in allbase for v in o.bound_box]
bw = max(p.x for p in pts)-min(p.x for p in pts)
bd = max(p.y for p in pts)-min(p.y for p in pts)
bh = max(p.z for p in pts)-min(p.z for p in pts)
print("BASE 总尺寸 = %.2f x %.2f x %.2f" % (bw, bd, bh))
print("T1_Roof 尺寸 =", dims("T1_Roof"))
print("T2_Roof 尺寸 =", dims("T2_Roof"))

# 起翘是否真的存在：比较檐口中点与檐角的高差
r = bpy.data.objects.get("T2_Roof")
if r:
    zs = {}
    for v in r.data.vertices:
        p = r.matrix_world @ v.co
        key = (round(p.x, 1), round(p.y, 1))
        zs[key] = max(zs.get(key, -9e9), p.z)
    # 找最低的檐口带（z 接近 eave）
    zmin = min(zs.values())
    eave = {k: v for k, v in zs.items() if v < zmin + 0.15}
    if eave:
        xs = [k[0] for k in eave]
        ys = [k[1] for k in eave]
        print("EAVE 檐口带 z~%.2f  x范围[%.1f,%.1f] y范围[%.1f,%.1f] 点数=%d"
              % (zmin, min(xs), max(xs), min(ys), max(ys), len(eave)))
    # 找最高的非脊点，判断起翘
    zmax = max(zs.values())
    print("ROOF z范围 %.2f .. %.2f  举高=%.2f" % (zmin, zmax, zmax-zmin))
'''
r = s.run(code)
print((r.get("result") or {}).get("result") or str(r.get("message"))[:800])