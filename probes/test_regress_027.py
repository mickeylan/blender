"""回归测试：LESSONS [027] 提到的三类失败。

1. curved_roof 返回值必须能当对象用（roof.location.z = ...）
2. material_slots[0] 在没给材质时也不能越界
3. mat/wood_mat/stone_mat 幂等（重复调用不叠节点、不产生 .001 后缀）
"""
import sys
sys.path.insert(0, r"J:\mickeylan\ai\blender")
import ai_loop

s = ai_loop.Session()
s.connect()

code = '''
clear_scene()
setup('BLENDER_EEVEE', (700, 520), 16, (0.1, 0.12, 0.16))
tile = wood_mat('Tile', (0.16, 0.28, 0.22), 0.55)
wood = wood_mat('Wood', (0.45, 0.24, 0.13), 0.62)

# --- 1) curved_roof 返回值当对象用（模型就是这么写的）---
roof = curved_roof('Roof1', 6.0, 3.0, 1.8, 0.0, 0.6, 0.9, 2.4, tile, wood)
roof.location.z = 3.0
bevel(roof, 0.02, 2)
print('ROOF_TYPE', type(roof).__name__, 'HAS_LOC', hasattr(roof, 'location'))
print('ROOF_Z', round(roof.location.z, 3))

# --- 2) material_slots[0] 不越界（物体建时没给材质）---
plain = box('Plain', (1, 1, 1), (0, 0, 0))
plain.material_slots[0].material = wood
print('SLOT_OK', plain.material_slots[0].material.name)

# --- 3) 幂等 ---
m1 = mat('Same', (0.5, 0.3, 0.2))
m2 = mat('Same', (0.5, 0.3, 0.2))
print('MAT_SAME', m1 is m2, m1.name)
w1 = wood_mat('SameWood', (0.5, 0.3, 0.2))
n1 = len(w1.node_tree.nodes)
w2 = wood_mat('SameWood', (0.5, 0.3, 0.2))
n2 = len(w2.node_tree.nodes)
print('WOOD_NODES', n1, n2, 'STABLE', n1 == n2)
print('MAT_COUNT', len([m for m in bpy.data.materials if m.name.startswith('Same')]))

stats('REGRESS ')
'''
r = s.run(code)
print("status:", r.get("status"))
print((r.get("result") or {}).get("result") or str(r.get("message"))[:1500])