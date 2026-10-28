"""逐面板检查法线朝向。"""
import sys
sys.path.insert(0, r"J:\mickeylan\ai\blender")
import ai_loop

s = ai_loop.Session()
s.connect()

code = '''
import bpy
from mathutils import Vector
clear_scene()
setup()
tile = mat('Tile', (0.16, 0.28, 0.22), 0.55)
roof = curved_roof('R', 6.0, 3.0, 1.8, 0.0, 0.6, 0.9, 2.4, tile, tile)
me = roof.data
print("TOTAL", len(me.polygons))
# 按面材质/位置分组统计朝上比例
import collections
buckets = collections.defaultdict(lambda: [0, 0])
for p in me.polygons:
    c = p.center
    if abs(c.y) > 1.0 and c.z < 1.0:
        k = 'front' if c.y < 0 else 'back'
    elif abs(c.x) > 1.5:
        k = 'end'
    else:
        k = 'bars/ridge'
    buckets[k][1] += 1
    if p.normal.z > 0.2:
        buckets[k][0] += 1
for k, (u, t) in sorted(buckets.items()):
    print("  %-12s up=%4d total=%4d  ratio=%.2f" % (k, u, t, u/max(1,t)))
# 打印前 6 个面的法线与中心
for i, p in enumerate(me.polygons[:6]):
    print("  face%d center=(%.2f,%.2f,%.2f) normal=(%.2f,%.2f,%.2f)" % (
        i, p.center.x, p.center.y, p.center.z, p.normal.x, p.normal.y, p.normal.z))
'''
r = s.run(code)
print(r.get("result", {}).get("result") or r.get("message"))