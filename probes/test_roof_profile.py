"""屋顶正视轮廓检查：反宇曲线 + 起翘，直接用 ASCII 侧面剖面验证。"""
import sys
sys.path.insert(0, r"J:\mickeylan\ai\blender")
import ai_loop
import view as V

s = ai_loop.Session()
s.connect()

code = '''
clear_scene()
setup('BLENDER_EEVEE', (700, 420), 24, (0.05, 0.06, 0.09))
tile = wood_mat('Tile', (0.30, 0.45, 0.34), 0.55)
roof = curved_roof('R', 6.0, 3.0, 1.8, 0.0, 0.6, 0.95, 2.4, tile, tile)
stats('ROOF ')
'''
r = s.run(code)
print(r.get("result", {}).get("result") or r.get("message"))

p = s.render("roof_front.png")
print("render:", p)
lines, tags = V.ascii_map(p, 86)
print("--- 正视轮廓（亮度）---")
for l in lines:
    print("|" + l + "|")
flat = "".join(tags)
for k in "GRBWK.":
    c = flat.count(k)
    if c:
        print(f"  {k}: {100*c/len(flat):5.1f}%")

# 直接输出几何剖面数值
prof = '''
import bpy
from mathutils import Vector
me = bpy.data.objects['R'].data
# 取中轴线 y=0 附近的最大 z 剖面（沿 x）
tops = {}
for v in me.vertices:
    x = round(v.co.x, 2)
    z = v.co.z
    if x not in tops or z > tops[x]:
        tops[x] = z
xs = sorted(tops)
print('RIDGE_XS', xs[0], '->', xs[-1])
sel = [x for x in xs if -3.7 <= x <= 3.7]
print('PROFILE_Z', [(x, round(tops[x], 2)) for x in sel][::2])
'''
r2 = s.c.execute_code(prof)
print((r2.get("result") or {}).get("result") or r2.get("message"))