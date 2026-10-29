"""核实 kimi 的两条指控：
1. "基座深度超4m"      -> 实测
2. "瓦垄结构显示不完整" -> 检查瓦垄覆盖范围
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

def grp(prefix):
    objs = [o for o in bpy.data.objects if o.name.startswith(prefix)]
    if not objs:
        return None
    pts = [o.matrix_world @ V(v) for o in objs for v in o.bound_box]
    return (max(p.x for p in pts)-min(p.x for p in pts),
            max(p.y for p in pts)-min(p.y for p in pts),
            max(p.z for p in pts)-min(p.z for p in pts))

print("BASE      =", tuple(round(v,2) for v in grp("Base_")))
print("ARCH      =", tuple(round(v,2) for v in grp("Arch_")))
print("T1_Roof   =", tuple(round(v,2) for v in grp("T1_Roof")))
print("T2_Roof   =", tuple(round(v,2) for v in grp("T2_Roof")))

# 瓦垄覆盖：T2_Roof 的顶点 y 分布 vs 屋面 y 范围
o = bpy.data.objects.get("T2_Roof")
ys = [(o.matrix_world @ v.co).y for v in o.data.vertices]
print("T2_Roof y 范围 [%.2f, %.2f]  顶点数=%d" % (min(ys), max(ys), len(ys)))

# 瓦垄是否覆盖了左右三角坡？三角坡在 |x| > Rx 区域
xs = [(o.matrix_world @ v.co).x for v in o.data.vertices]
print("T2_Roof x 范围 [%.2f, %.2f]" % (min(xs), max(xs)))

# 统计每个 x 段的顶点数，看三角坡区域是否稀疏（说明扇形垄没铺满）
import collections
cnt = collections.Counter()
for v in o.data.vertices:
    p = o.matrix_world @ v.co
    cnt[round(p.x, 1)] += 1
ks = sorted(cnt)
print("x 分桶顶点分布 (x: 计数):")
line = []
for k in ks:
    line.append("%+.1f:%d" % (k, cnt[k]))
print("  " + "  ".join(line[:24]))
'''
r = s.run(code)
print((r.get("result") or {}).get("result") or str(r.get("message"))[:1500])