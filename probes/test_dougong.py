"""验证 dougong() 助手：几何自检 + 单朵渲染。"""
import sys
sys.path.insert(0, r"J:\mickeylan\ai\blender")
import ai_loop

s = ai_loop.Session()
s.connect()

code = '''
clear_scene()
setup('BLENDER_EEVEE', (760, 560), 48, (0.05, 0.06, 0.09))
wood = wood_mat('DgWood', (0.40, 0.22, 0.12), 0.60, 16.0)
# 一根柱子（斗拱坐落其上）
cyl('Col', 0.16, 1.30, (0, 0, 0.65), None, 20, wood)
# 单朵斗拱，斗口 0.10m
dougong('Dg', z=1.30, kou=0.10, material=wood)
stats('DOUGONG TEST')
'''
r = s.run(code)
print((r.get("result") or {}).get("result") or str(r.get("message"))[:1200])

for f in s.render_views("dg"):
    print("  ", f[0], f[1])