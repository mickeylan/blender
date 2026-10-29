"""验证瓦垄在垂脊处不再重复几何（Z-fighting 源）。"""
import sys
sys.path.insert(0, r"J:\mickeylan\ai\blender")
import ai_loop

s = ai_loop.Session()
s.connect()

code = '''
import bpy
from mathutils import Vector as V
bpy.context.view_layer.update()
o = bpy.data.objects.get("T2_Roof")
pts = [o.matrix_world @ v.co for v in o.data.vertices]

# 垂脊线：从前坡角 (W/2, -halfD) 到脊端 (Rx, 0)
W = 8.91*0+6.76   # T2_Roof 宽
D = 4.26
halfD = D/2
Rx = max(0.0, W/2 - D/2)

# 统计落在"垂脊附近"的顶点，看是否有成对的重复
near = []
for p in pts:
    # 垂脊方向
    if p.x > 0:
        # 参数化：t = (x-Rx)/(W/2-Rx), y = -t*halfD
        if Rx < W/2 - 1e-6:
            t = (p.x - Rx) / (W/2 - Rx)
            if 0 <= t <= 1.001:
                yline = -t * halfD
                if abs(p.y - yline) < 0.06 and p.x > Rx + 0.02:
                    near.append((round(p.x,3), round(p.y,3), round(p.z,4)))
print("垂脊附近顶点数=%d" % len(near))
# 找重复位置（同一 xy 多个 z）
from collections import defaultdict
d = defaultdict(list)
for x,y,z in near:
    d[(x,y)].append(z)
dup = {k:v for k,v in d.items() if len(v) > 1}
print("同一 xy 出现多次的点数=%d" % len(dup))
if dup:
    ks = list(dup)[:5]
    for k in ks:
        print("  DUP at", k, sorted(round(z,4) for z in dup[k]))
else:
    print("  无重复几何 -> 垂脊处无 Z-fighting")

# 瓦垄在正脊处的终止：数正脊附近顶点
ridge = [p for p in pts if abs(p.y) < 0.05 and p.x > 0]
print("正脊线上(右半)顶点数=%d" % len(ridge))
'''
r = s.run(code)
print((r.get("result") or {}).get("result") or str(r.get("message"))[:1200])