"""三视图渲染 + curved_roof 的集成自检。"""
import sys
sys.path.insert(0, r"J:\mickeylan\ai\blender")
import ai_loop

s = ai_loop.Session()
s.connect()

code = '''
clear_scene()
setup('BLENDER_EEVEE', (800, 600), 24, (0.10, 0.12, 0.16))
tile = wood_mat('Tile', (0.16, 0.28, 0.22), 0.55)
wood = wood_mat('Wood', (0.45, 0.24, 0.13), 0.62)
stone = stone_mat('Stone', (0.58, 0.56, 0.52), 0.85)
box('Base', (7.0, 3.6, 0.5), (0, 0, 0.25), None, stone)
bevel(bpy.data.objects['Base'], 0.04)
for i, x in enumerate((-2.6, 0.0, 2.6)):
    for j, y in enumerate((-1.3, 1.3)):
        cyl('Col_%d%d' % (i, j), 0.13, 2.2, (x, y, 1.6), None, 16, wood)
curved_roof('Roof', 6.4, 3.0, ridge_h=1.9, eave_h=0.0, overhang=0.6,
            corner_lift=0.95, curve=2.4, material=tile, ridge_mat=wood)
area_light('Fill', (-6, -8, 6), 900, 8, (0, 0, 1.5))
stats('INTEG ')
'''
r = s.run(code)
print("status:", r.get("status"))
print((r.get("result") or {}).get("result") or str(r.get("message"))[:800])

shots = s.render_views("roof_test")
print("shots:", [p.split("\\")[-1] for p in shots])

import os
for p in shots:
    print(f"  {os.path.basename(p)}  {os.path.getsize(p)} B")

# 程序化验证：顶视图应该比正视图"更宽"（平面布局 vs 立面）
from PIL import Image
import numpy as np
def subject(path):
    a = np.asarray(Image.open(path).convert("RGB")).astype(float)
    h, w, _ = a.shape
    corners = np.concatenate([a[0:8,0:8].reshape(-1,3), a[0:8,-8:].reshape(-1,3),
                              a[-8:,0:8].reshape(-1,3), a[-8:,-8:].reshape(-1,3)])
    bg = np.median(corners, axis=0)
    fg = np.abs(a - bg).sum(2) > 40
    ys, xs = np.where(fg)
    if len(ys) == 0:
        return None
    return xs.min(), xs.max(), ys.min(), ys.max(), fg.mean()
for p in shots:
    b = subject(p)
    if b:
        print(f"  {os.path.basename(p):<22} bbox x[{b[0]},{b[1]}] y[{b[2]},{b[3]}] 占比={b[4]*100:.1f}%")