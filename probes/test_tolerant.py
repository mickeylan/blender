import sys
sys.path.insert(0, r"J:\mickeylan\ai\blender")
import ai_loop

s = ai_loop.Session()
s.connect()

# 完全照抄模型实际写出的调用形式（含 None 占位、角度当弧度、材质挤位）
code = '''
clear_scene()
setup('BLENDER_EEVEE', (1024, 768), 32, (0.7, 0.8, 0.9))

mat_stone = mat('Stone', (0.60, 0.58, 0.55))
mat_wood  = mat('RedWood', (0.72, 0.18, 0.12))
mat_roof  = mat('RoofGreen', (0.12, 0.28, 0.18))

# 1) rot 传 None（模型最常犯）—— 曾经直接抛 bpy_struct attr 错
box('Base_Wall_L', (2.7, 4.0, 3.0), (-2.65, 0.0, 1.5), None, mat_stone)
box('Base_Wall_R', (2.7, 4.0, 3.0), ( 2.65, 0.0, 1.5), None, mat_stone)

# 2) 旋转传「度」而不是弧度
cyl('Base_Arch', 1.3, 4.0, (0.0, 0.0, 2.0), (90.0, 0.0, 0.0), 24)

# 3) 材质挤到 verts 位
cyl('Col_1', 0.15, 2.5, (-2.8, -1.6, 4.45), None, mat_wood)

# 4) 正常调用
prism('F1_Roof', (7.0, 3.6), 1.8, (0.0, 0.0, 6.6), (0.0, 0.0, 0.0), (0.30, 0.30), mat_roof)

# 5) 标量 size（正方体）
box('Cap', 0.5, (0.0, 0.0, 7.5), None, mat_roof)

stats('TOLERANT_TEST ')

# 验证旋转确实被当角度处理（90 度 -> 1.5708 弧度）
import math
a = bpy.data.objects['Base_Arch'].rotation_euler
print("Base_Arch rotation_euler = (%.4f, %.4f, %.4f)  期望 x≈%.4f" % (a[0], a[1], a[2], math.radians(90)))
print("Base_Wall_L rot =", tuple(bpy.data.objects['Base_Wall_L'].rotation_euler))
print("Cap size =", tuple(round(v,3) for v in bpy.data.objects['Cap'].dimensions))
'''

r = s.run(code)
print("status:", r.get("status"))
print((r.get("result") or {}).get("result") or str(r.get("message"))[:2000])