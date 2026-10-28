"""验证背景钳制：模型把背景设成亮色时，渲染前应被压下来。"""
import sys
sys.path.insert(0, r"J:\mickeylan\ai\blender")
import numpy as np
from PIL import Image
import ai_loop

s = ai_loop.Session()
s.connect()

# 模拟模型把背景设成过亮
code = '''
clear_scene()
setup('BLENDER_EEVEE', (600, 400), 16, (0.80, 0.85, 0.95))
wood = wood_mat('Wood', (0.30, 0.17, 0.09), 0.62)
stone = stone_mat('Stone', (0.38, 0.36, 0.33), 0.85)
box('Base', (6.0, 3.0, 0.6), (0, 0, 0.3), None, stone)
for x in (-2.2, 0.0, 2.2):
    cyl('Col_%.0f' % x, 0.14, 2.4, (x, 0, 1.8), None, 16, wood)
m = mat('Tile', (0.20, 0.30, 0.24), 0.55)
prism('Roof', (6.4, 2.6), 1.4, (0, 0, 3.7), None, (0.25, 0.25), m)
stats('CLAMPTEST ')
'''
r = s.run(code)
print(r.get("result", {}).get("result"))

p = s.render("clamp_test.png")
out = None
a = np.asarray(Image.open(p).convert("RGB")).astype(float)
h, w, _ = a.shape
corners = np.concatenate([a[0:6, 0:6].reshape(-1, 3), a[0:6, -6:].reshape(-1, 3)])
bg = np.median(corners, axis=0)
fg = np.abs(a - bg).sum(2) > 40
print(f"背景 RGB = {tuple(int(v) for v in bg)}  (期望 <= ~175，不应是 240+)")
print(f"主体占比 = {100*fg.mean():.1f}%")
ys, xs = np.where(fg)
print(f"主体 bbox x[{xs.min()},{xs.max()}] y[{ys.min()},{ys.max()}] / {w}x{h}")
print(f"主体平均 RGB = ({a[:,:,0][fg].mean():.0f}, {a[:,:,1][fg].mean():.0f}, {a[:,:,2][fg].mean():.0f})")