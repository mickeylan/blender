"""检查城楼五通道渲染：正视剪影 + 各通道明暗统计。"""
import numpy as np
from PIL import Image
import view as V

def silhouette(path, tag):
    a = np.asarray(Image.open(path).convert("RGB")).astype(float)
    h, w, _ = a.shape
    corners = np.concatenate([a[0:6, 0:6].reshape(-1, 3), a[0:6, -6:].reshape(-1, 3)])
    bg = np.median(corners, axis=0)
    fg = np.abs(a - bg).sum(2) > 40
    tops = []
    for x in range(w):
        ys = np.where(fg[:, x])[0]
        tops.append(ys.min() if len(ys) else np.nan)
    tops = np.array(tops, float)
    xs = np.where(~np.isnan(tops))[0]
    if len(xs) == 0:
        print(f"{tag}: 无前景")
        return
    x0, x1 = xs.min(), xs.max()
    prof = [float(tops[int(x0 + (x1 - x0) * k / 8)]) for k in range(9)]
    print(f"{tag}: 前景{x0}..{x1} 剪影顶部行 {[round(p,0) for p in prof]}")
    mid = prof[4]
    sides = [p for p in (prof[1], prof[7]) if not np.isnan(p)]
    if sides and not np.isnan(mid):
        ok = all(mid < s - 3 for s in sides)
        print(f"    中心={mid:.0f} 侧={[round(s,0) for s in sides]} -> "
              f"{'脊高檐低 正确' if ok else '中心偏低 可能倒置'}")

for name in ("gate_front", "gate_right", "gate_back", "gate_clay", "gate_hero"):
    p = f"out/{name}.png"
    a = np.asarray(Image.open(p).convert("RGB")).astype(float)
    print(f"{name:<12} 平均亮度={a.mean():6.1f}  StdDev={a.std():5.1f}")
silhouette("out/gate_front.png", "gate_front")

print()
lines, tags = V.ascii_map("out/gate_clay.png", 66)
print("--- 灰模（只看形体）---")
for l in lines:
    print("|" + l + "|")