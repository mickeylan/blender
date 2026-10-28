"""综合验证：修正后的屋顶在三视图下是否正常（亮度/色相/轮廓）。"""
import sys
sys.path.insert(0, r"J:\mickeylan\ai\blender")
import numpy as np
from PIL import Image
import ai_loop
import view as V

s = ai_loop.Session()
s.connect()

code = '''
clear_scene()
setup('BLENDER_EEVEE', (760, 460), 32, (0.05, 0.06, 0.09))
tile = wood_mat('Tile', (0.22, 0.36, 0.27), 0.55)
ridge = wood_mat('Ridge', (0.42, 0.24, 0.13), 0.62)
wood = wood_mat('Wood', (0.45, 0.26, 0.14), 0.62)
stone = stone_mat('Stone', (0.58, 0.56, 0.52), 0.85)

box('Base', (7.0, 3.6, 0.5), (0, 0, 0.25), None, stone)
bevel(bpy.data.objects['Base'], 0.04)
for i, x in enumerate((-2.6, 0.0, 2.6)):
    for j, y in enumerate((-1.3, 1.3)):
        cyl('Col_%d%d' % (i, j), 0.13, 2.2, (x, y, 1.6), None, 16, wood)
curved_roof('Roof', 6.4, 3.0, 1.9, 0.0, 0.6, 0.95, 2.4, tile, ridge)
stats('FULL ')
'''
r = s.run(code)
print(r.get("result", {}).get("result") or r.get("message"))

shots = s.render_views("fix")
for p in shots:
    a = np.asarray(Image.open(p).convert("RGB")).astype(float)
    h, w, _ = a.shape
    corners = np.concatenate([a[0:8, 0:8].reshape(-1, 3), a[0:8, -8:].reshape(-1, 3),
                              a[-8:, 0:8].reshape(-1, 3), a[-8:, -8:].reshape(-1, 3)])
    bg = np.median(corners, axis=0)
    fg = np.abs(a - bg).sum(2) > 40
    ys, xs = np.where(fg)
    r_, g_, b_ = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    green = fg & (g_ > r_ + 8) & (g_ > b_ + 4)
    brown = fg & (r_ > g_ + 20)
    print(f"{p.split(chr(92))[-1]:<22} 前景={100*fg.mean():5.1f}% 绿={100*green.sum()/max(1,fg.sum()):5.1f}% "
          f"木色={100*brown.sum()/max(1,fg.sum()):5.1f}% 平均RGB=({r_[fg].mean():.0f},{g_[fg].mean():.0f},{b_[fg].mean():.0f}) "
          f"bbox=x[{xs.min()},{xs.max()}] y[{ys.min()},{ys.max()}]")

print()
lines, tags = V.ascii_map(shots[1], 88)   # 正视图
print("--- 正视图 ---")
for l in lines:
    print("|" + l + "|")
