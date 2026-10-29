"""数值验证瓦垄：沿 x 扫描一条位于某条瓦垄上的 y 剖面，看 z 的波纹。

做法：选一个 y 切片带（|p.y - y0| < tol），收集所有顶点，
按 x 排序取每 x 的最高 z —— 如果瓦垄存在，应看到周期性波峰。
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
o = bpy.data.objects.get("T2_Roof")
if o is None:
    print("NO_ROOF")
else:
    # 把所有顶点按 y 分桶，找出瓦垄中心所在的 y
    buckets = {}
    for v in o.data.vertices:
        p = o.matrix_world @ v.co
        buckets.setdefault(round(p.y, 2), []).append((p.x, p.z))
    ys = sorted(buckets)
    print("y 切片数=%d  范围 [%.2f, %.2f]" % (len(ys), ys[0], ys[-1]))
    # 找顶点最多的 y（那是瓦垄中心线附近）
    best = max(ys, key=lambda y: len(buckets[y]))
    pts = sorted(buckets[best])
    # 每 x 取最高 z
    top = {}
    for x, z in pts:
        if x not in top or z > top[x]:
            top[x] = z
    xs = sorted(top)
    zsv = [top[x] for x in xs]
    print("SLICE y=%.2f  顶点数=%d  x=[%.2f,%.2f]" % (best, len(pts), xs[0], xs[-1]))
    peaks = sum(1 for i in range(1, len(zsv)-1)
                if zsv[i] > zsv[i-1] and zsv[i] >= zsv[i+1])
    print("WAVE 峰值数=%d" % peaks)
    print("WAVE z 序列=%s" % [round(z, 4) for z in zsv[:30]])
    if zsv:
        print("WAVE 幅度=%.4f m" % (max(zsv) - min(zsv)))
'''
r = s.run(code)
print((r.get("result") or {}).get("result") or str(r.get("message"))[:900])