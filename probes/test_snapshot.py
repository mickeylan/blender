"""验证快照/回滚：restore 后场景必须与快照时一致，且 MCP 通道不受影响。"""
import os
import sys
sys.path.insert(0, r"J:\mickeylan\ai\blender")
import ai_loop

s = ai_loop.Session()
s.connect()
SNAP = r"J:\mickeylan\ai\blender\out\snap\test.blend"

code1 = '''
clear_scene()
setup('BLENDER_EEVEE', (640, 480), 16, (0.05, 0.06, 0.09))
wood = wood_mat('W', (0.34, 0.19, 0.10), 0.62)
stone = stone_mat('S', (0.30, 0.29, 0.26), 0.85)
box('Base_Plate', (6, 4, 0.4), (0, 0, 0.2), None, stone)
for i in range(3):
    cyl('Col_%d' % i, 0.15, 2.0, (-2 + 2*i, 0, 1.4), None, 16, wood)
beam('Beam_Top', (-2.2, 0, 2.5), (2.2, 0, 2.5), 0.2, wood)
stats('SNAP ')
'''
r = s.run(code1)
print("A 建场景:", (r.get("result") or {}).get("result", "").strip().splitlines()[-1])
names_a = sorted(s.object_names())
fams_a = s.component_dims_str()
print("A 构件:", names_a)

# 快照
p = s.snapshot(SNAP)
print("快照:", p, "存在" if p and os.path.exists(p) else "失败")

# 破坏场景
code2 = '''
clear_scene()
setup('BLENDER_EEVEE', (640, 480), 16, (0.05, 0.06, 0.09))
box('Junk', (1, 1, 1), (0, 0, 0), None, None)
stats('BROKEN ')
'''
s.run(code2)
print("B 破坏后:", sorted(s.object_names()))

# 回滚
ok = s.restore(SNAP)
names_b = sorted(s.object_names())
print("C 回滚后:", names_b)
print("D MCP 通道:", "仍通" if s.mesh_count() >= 0 else "断了")

# 断言
print()
print("断言1 快照文件存在:", "PASS" if os.path.exists(SNAP) else "FAIL")
print("断言2 构件名完全一致:", "PASS" if names_a == names_b else "FAIL  %s vs %s" % (names_a, names_b))
print("断言3 垃圾对象已清除:", "PASS" if "Junk" not in names_b else "FAIL")
fams_b = s.component_dims_str()
print("断言4 尺寸一致:", "PASS" if fams_a == fams_b else "FAIL")
print("   A:", fams_a.replace("\n", " | "))
print("   B:", fams_b.replace("\n", " | "))
os.remove(SNAP)