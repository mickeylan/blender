"""用渲染图的剪影高度曲线判定屋顶是否倒置 —— 测的是像素，不是代码。"""
import sys
sys.path.insert(0, r"J:\mickeylan\ai\blender")
import numpy as np
from PIL import Image
import ai_loop

s = ai_loop.Session()
s.connect()

code = '''
clear_scene()
setup('BLENDER_EEVEE', (720, 480), 24, (0.04, 0.05, 0.08))
tile = wood_mat('Tile', (0.24, 0.36, 0.28), 0.55)
ridge = wood_mat('Ridge', (0.42, 0.24, 0.13), 0.62)
box('Base', (0.2, 0.2, 0.2), (0, 0, -5))   # 占位，避免空场景
bpy.data.objects.remove(bpy.data.objects['Base'], do_unlink=True)
r = curved_roof('Roof', 6.0, 3.0, 1.9, 0.0, 0.6, 0.95, 2.4, tile, ridge)
stats('ORIENT2 ')
'''
res = s.run(code)
print((res.get("result") or {}).get("result", ""))

# 只渲染正视正交
p = s._render_one("orient_front.png", "front", False)
print("render:", p)

a = np.asarray(Image.open(p).convert("RGB")).astype(float)
h, w, _ = a.shape
corners = np.concatenate([a[0:6, 0:6].reshape(-1, 3), a[0:6, -6:].reshape(-1, 3)])
bg = np.median(corners, axis=0)
fg = np.abs(a - bg).sum(2) > 40

# 每列最上方非背景像素的行号（越小 = 越高）
tops = []
for x in range(w):
    ys = np.where(fg[:, x])[0]
    tops.append(ys.min() if len(ys) else np.nan)
tops = np.array(tops, dtype=float)

valid = ~np.isnan(tops)
xs = np.where(valid)[0]
if len(xs) == 0:
    print("无前景")
else:
    x0, x1 = xs.min(), xs.max()
    print(f"前景列范围 x[{x0},{x1}]")
    # 取 9 个采样列的顶部行号
    samples = [int(x0 + (x1 - x0) * k / 8) for k in range(9)]
    prof = [round(tops[c], 1) if not np.isnan(tops[c]) else None for c in samples]
    print(f"剪影顶部行号（小=高）: {prof}")
    mid = prof[4]
    left, right = prof[1], prof[7]
    if mid is None:
        print("中心无前景")
    else:
        print(f"  中心(脊) 顶部行={mid:.1f}   左1/8={left}  右7/8={right}")
        verdict = "脊高檐低 ✓ 正确" if (left is not None and mid < left - 2 and mid < right - 2) \
            else "!! 中心比两侧低 —— 屋顶是倒的（谷形）"
        print("  判定:", verdict)

# 顺便用字符图看一眼
import view as V
lines, _ = V.ascii_map(p, 74)
print("--- 正视图 ---")
for l in lines:
    print("|" + l + "|")