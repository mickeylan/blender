"""验证增量修改机制：KEEP 声明的构件必须存活，其余必须被删除。"""
import sys
sys.path.insert(0, r"J:\mickeylan\ai\blender")
import ai_loop

s = ai_loop.Session()
s.connect()

# --- 第 1 轮：全量建 3 个族 ---
code1 = '''
clear_scene()
setup('BLENDER_EEVEE', (640, 480), 16, (0.05, 0.06, 0.09))
wood = wood_mat('W', (0.34, 0.19, 0.10), 0.62)
stone = stone_mat('S', (0.30, 0.29, 0.26), 0.85)
box('Base_Plate', (6, 4, 0.4), (0, 0, 0.2), None, stone)
for i in range(3):
    cyl('Col_%d' % i, 0.15, 2.0, (-2 + 2*i, 0, 1.4), None, 16, wood)
beam('Beam_Top', (-2.2, 0, 2.5), (2.2, 0, 2.5), 0.2, wood)
stats('ROUND1 ')
'''
r = s.run(code1)
print("R1:", (r.get("result") or {}).get("result", "").strip().splitlines()[-1:])
names1 = s.object_names()
print("R1 构件:", sorted(names1))

# --- 第 2 轮：增量，保留 Base_* 和 Col_*，只重建梁 ---
code2 = '''
KEEP = ["Base_", "Col_"]
clear_scene()
wood = wood_mat('W', (0.34, 0.19, 0.10), 0.62)
beam('Beam_Top', (-2.2, 0, 2.8), (2.2, 0, 2.8), 0.25, wood)
stats('ROUND2 ')
'''
r = s.run(code2)
print("R2:", (r.get("result") or {}).get("result", "").strip().splitlines()[-2:])
names2 = s.object_names()
print("R2 构件:", sorted(names2))

# --- 断言 ---
kept = [n for n in names2 if n.startswith("Base_") or n.startswith("Col_")]
gone = [n for n in names2 if n not in kept]
old_beam_gone = "Beam_Top" in names2   # 应仍存在（重建了）
print()
print("保留的构件 (%d):" % len(kept), sorted(kept))
print("非保留的构件 (%d):" % len(gone), sorted(gone))
print("断言1 保留族仍在:", "PASS" if len(kept) == 4 else "FAIL")
print("断言2 只剩保留族+重建件:", "PASS" if len(gone) == 1 and gone[0].startswith("Beam") else "FAIL")
print("断言3 Beam 已重建:", "PASS" if old_beam_gone else "FAIL")

# 确认梁确实换了高度
r = s.c.execute_code(
    "import bpy\n"
    "o = bpy.data.objects.get('Beam_Top')\n"
    "print('BEAMZ %.2f' % o.location.z)\n")
out = str(r.get("result", {}).get("result", ""))
print("断言4 梁已上移到 2.80:", out.strip().splitlines()[-1])