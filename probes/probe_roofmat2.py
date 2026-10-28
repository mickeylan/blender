import sys, os
sys.path.insert(0, r"J:\mickeylan\ai\blender")
import ai_loop

s = ai_loop.Session()
s.connect()

code = '''
clear_scene()
setup('BLENDER_EEVEE', (600, 450), 16, (0.1, 0.12, 0.16))
tile = wood_mat('Tile', (0.16, 0.28, 0.22), 0.55)
wood = wood_mat('Wood', (0.45, 0.24, 0.13), 0.62)
nt = tile.node_tree
print('LINKS:')
for l in nt.links:
    print('   %s[%s] -> %s[%s]' % (l.from_node.name, l.from_socket.name,
                                   l.to_node.name, l.to_socket.name))
ramp = next((n for n in nt.nodes if n.name.startswith('_proc_ramp')), None)
if ramp:
    print('RAMP_ELEMS', [(e.position, tuple(round(v,3) for v in e.color)) for e in ramp.color_ramp.elements])
    print('RAMP_INPUTS_LINKED', [(i.name, i.is_linked) for i in ramp.inputs])
bs = next(n for n in nt.nodes if n.type=='BSDF_PRINCIPLED')
print('BSDF_BASE_LINKED', bs.inputs['Base Color'].is_linked)

# 只放一个屋顶，渲染
roof = curved_roof('Roof', 6.0, 3.0, 1.8, 0.0, 0.6, 0.9, 2.4, tile, wood)
stats('ONLY_ROOF ')
'''
r = s.run(code)
print(r.get("result", {}).get("result") or r.get("message"))

p = s.render("probe_roof_only.png")
print("render:", p)

from PIL import Image
import numpy as np
a = np.asarray(Image.open(p).convert("RGB")).astype(int)
r_, g_, b_ = a[:, :, 0], a[:, :, 1], a[:, :, 2]
green = (g_ > r_ + 10) & (g_ > b_ + 8)
print("绿色像素占比: %.2f%%" % (100 * green.mean()))
cols, counts = np.unique(a.reshape(-1, 3), axis=0, return_counts=True)
print("top6 颜色:")
for i in np.argsort(-counts)[:6]:
    print("   ", tuple(int(x) for x in cols[i]), int(counts[i]))