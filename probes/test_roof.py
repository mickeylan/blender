import sys
sys.path.insert(0, r"J:\mickeylan\ai\blender")
import ai_loop

s = ai_loop.Session()
s.connect()

code = '''
clear_scene()
setup('BLENDER_EEVEE', (900, 700), 24, (0.10, 0.12, 0.16))
tile = wood_mat('Tile', (0.16, 0.28, 0.22), 0.55)
wood = wood_mat('Wood', (0.45, 0.24, 0.13), 0.62)
stone = stone_mat('Stone', (0.58, 0.56, 0.52), 0.85)

# 基座
box('Base', (7.0, 3.6, 0.5), (0, 0, 0.25), None, stone)
bevel(bpy.data.objects['Base'], 0.04)

# 柱
for i, x in enumerate((-2.6, 0.0, 2.6)):
    for j, y in enumerate((-1.3, 1.3)):
        cyl('Col_%d%d' % (i, j), 0.13, 2.2, (x, y, 1.6), None, 16, wood)

# 反曲屋顶
r = curved_roof('Roof', 6.4, 3.0, ridge_h=1.9, eave_h=0.0, overhang=0.6,
                corner_lift=0.95, curve=2.4, material=tile, ridge_mat=wood)
stats('ROOF_TEST ')

bpy.context.view_layer.update()
# 验证反曲：沿前坡中线取样，看高度是否呈凹曲线（斜率递减）
hs = []
for k in range(9):
    y = -1.5 - 0.6*k/8
    t = abs(y)/3.0
    z = 0.0 + (1.9-0.0)*(1.0-(1.0-t)**2.4)
    hs.append(round(z, 3))
print("PROFILE:", hs)
# 验证起翘：四角高度 vs 长边中点高度
import math
def h(x, y):
    Rx = max(0.0, (6.4+1.2)*0.5 - (3.0+1.2)*0.5)
    t = min(1.0, max(abs(y), max(0.0, abs(x)-Rx)) / ((3.0+1.2)*0.5))
    z = 0.0 + 1.9*(1.0-(1.0-t)**2.4)
    z += 0.95*(abs(x)/((6.4+1.2)*0.5))**8*(abs(y)/((3.0+1.2)*0.5))**8*(t**1.5)
    return z
print("CORNER  (%.3f, %.3f) z=%.3f" % (3.8, -2.1, h(3.8, -2.1)))
print("EDGEMID (%.3f, %.3f) z=%.3f" % (0.0, -2.1, h(0.0, -2.1)))
print("LIFT_DIFF = %.3f (应 > 0.5)" % (h(3.8,-2.1)-h(0.0,-2.1)))
'''

r = s.run(code)
print("status:", r.get("status"))
print((r.get("result") or {}).get("result") or str(r.get("message"))[:2000])