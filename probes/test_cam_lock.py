"""验证跨轮相机锁定：两轮渲染的 CAM_STATE 必须完全一致。"""
import sys
sys.path.insert(0, r"J:\mickeylan\ai\blender")
import ai_loop

code_a = '''
clear_scene()
setup('BLENDER_EEVEE', (640, 480), 16, (0.05, 0.06, 0.09))
stone = stone_mat('S', (0.30, 0.29, 0.26), 0.85)
wood = wood_mat('W', (0.34, 0.19, 0.10), 0.62)
box('Base', (6, 3, 0.5), (0, 0, 0.25), None, stone)
for x in (-2, 0, 2):
    cyl('C%.0f' % x, 0.14, 2.0, (x, 0, 1.5), None, 16, wood)
tile = mat('T', (0.20, 0.30, 0.24), 0.55)
curved_roof('R', 5.4, 2.8, 3.4, 2.5, 0.5, 0.35, 2.4, tile, wood)
stats('A ')
'''

# 第二轮：模型变大（模拟模型改动导致包围盒变化）
code_b = '''
clear_scene()
setup('BLENDER_EEVEE', (640, 480), 16, (0.05, 0.06, 0.09))
stone = stone_mat('S', (0.30, 0.29, 0.26), 0.85)
wood = wood_mat('W', (0.34, 0.19, 0.10), 0.62)
box('Base', (10, 5, 0.8), (0, 0, 0.4), None, stone)      # 明显更大
for x in (-3.4, 0, 3.4):
    cyl('C%.0f' % x, 0.2, 3.2, (x, 0, 2.4), None, 16, wood)
tile = mat('T', (0.20, 0.30, 0.24), 0.55)
curved_roof('R', 9.0, 4.6, 5.2, 4.0, 0.6, 0.4, 2.4, tile, wood)
stats('B ')
'''

s = ai_loop.Session()
s.connect()

print("=== 第 1 轮（自动取景 + 锁定）===")
r = s.run(code_a)
print((r.get("result") or {}).get("result", "").strip())
s.render_views("lockA")
lock_after_round1 = dict(s.cam_lock or {})
print("锁定通道:", sorted(lock_after_round1))

print()
print("=== 第 2 轮（模型变大，应沿用锁定机位）===")
r = s.run(code_b)
print((r.get("result") or {}).get("result", "").strip())
s.render_views("lockB")
lock_after_round2 = s.cam_lock or {}

print()
print("=== 比对 ===")
same = True
for k in sorted(lock_after_round1):
    a = lock_after_round1[k]
    b = lock_after_round2.get(k, {})
    eq = (a["loc"] == b["loc"] and a["rot"] == b["rot"]
          and abs(a["ortho"] - b["ortho"]) < 1e-6
          and abs(a["lens"] - b["lens"]) < 1e-6
          and a["res"] == b["res"])
    same = same and eq
    print(f"  {k:<6} {'一致' if eq else '不一致'}  loc={[round(v,3) for v in a['loc']]} ortho={a['ortho']:.2f}")
print("结论:", "PASS 两轮机位完全一致" if same else "FAIL 机位漂移")