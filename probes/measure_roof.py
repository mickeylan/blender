"""测量屋顶像素的实际颜色，判断是否被正确打光。"""
import sys
sys.path.insert(0, r"J:\mickeylan\ai\blender")
import numpy as np
from PIL import Image

for path in ("out/probe_roof_only.png", "out/roof_front.png"):
    a = np.asarray(Image.open(path).convert("RGB")).astype(float)
    h, w, _ = a.shape
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    bg = (np.abs(r - 89) < 6) & (np.abs(g - 97) < 6) & (np.abs(b - 111) < 7)
    fg = ~bg
    n = fg.sum()
    if n == 0:
        print(path, "无前景")
        continue
    print(f"{path}: 前景 {n} px ({100*n/len(flat) if False else 100*n/fg.size:.1f}%)")
    print(f"   前景平均 RGB = ({r[fg].mean():.0f}, {g[fg].mean():.0f}, {b[fg].mean():.0f})")
    ys, xs = np.where(fg)
    print(f"   前景 bbox x[{xs.min()},{xs.max()}] y[{ys.min()},{ys.max()}]  图像 {w}x{h}")
    # 最亮的 5% 前景像素
    lum = (r + g + b) / 3
    thr = np.percentile(lum[fg], 90)
    bright = fg & (lum >= thr)
    print(f"   最亮10%前景 RGB = ({r[bright].mean():.0f}, {g[bright].mean():.0f}, {b[bright].mean():.0f})")
    greenish = fg & (g > r + 8) & (g > b + 4)
    print(f"   偏绿前景: {100*greenish.sum()/n:.1f}%")
