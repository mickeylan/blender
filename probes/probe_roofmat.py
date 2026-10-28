import sys
sys.path.insert(0, r"J:\mickeylan\ai\blender")
import ai_loop

s = ai_loop.Session()
s.connect()

code = '''
clear_scene()
setup('BLENDER_EEVEE', (600, 450), 16, (0.1, 0.12, 0.16))
tile = wood_mat('Tile', (0.16, 0.28, 0.22), 0.55)
wood = wood_mat('Wood', (0.45, 0.24, 0.13), 0.62)
roof = curved_roof('Roof', 6.0, 3.0, 1.8, 0.0, 0.6, 0.9, 2.4, tile, wood)

print('SLOTS', len(roof.data.materials), [m.name for m in roof.data.materials])
print('POLYS', len(roof.data.polygons))
idxs = {}
for p in roof.data.polygons:
    idxs[p.material_index] = idxs.get(p.material_index, 0) + 1
print('MAT_INDEX_HIST', idxs)
print('TILE_BASE', tuple(round(v,3) for v in tile.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value) if 'Principled BSDF' in tile.node_tree.nodes else 'BY_NAME_FAIL')
bs = next(n for n in tile.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
print('TILE_BASE_BY_TYPE', tuple(round(v,3) for v in bs.inputs['Base Color'].default_value))
print('TILE_NODES', [(n.name, n.type) for n in tile.node_tree.nodes])
# 法线朝向检查：取一个屋面多边形，看法线 z 分量
import mathutils
up = sum(1 for p in roof.data.polygons if p.normal.z > 0.2)
print('FACES_UP', up, 'OF', len(roof.data.polygons))
'''
r = s.run(code)
print(r.get("result", {}).get("result") or r.get("message"))