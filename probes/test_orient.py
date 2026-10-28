"""屋顶朝向回归测试 —— 必须报 脊高檐低。"""
import sys
sys.path.insert(0, r"J:\mickeylan\ai\blender")
import ai_loop

s = ai_loop.Session()
s.connect()

code = '''
clear_scene()
setup('BLENDER_EEVEE', (700, 460), 24, (0.05, 0.06, 0.09))
tile = wood_mat('Tile', (0.22, 0.34, 0.27), 0.55)
ridge = wood_mat('Ridge', (0.42, 0.24, 0.13), 0.62)
r = curved_roof('Roof', 6.0, 3.0, 1.8, 0.0, 0.6, 0.9, 2.4, tile, ridge)
stats('ORIENT ')
'''
res = s.run(code)
out = (res.get("result") or {}).get("result", "")
print(out)

ok = "OK(脊高檐低)" in out
print("朝向断言:", "PASS" if ok else "FAIL")
p = s.render("orient_check.png")
print("render:", p)