"""光照标定：找出能让 0.25 反射率表面读出 ~0.7 sRGB 的太阳强度。"""
import sys
sys.path.insert(0, r"J:\mickeylan\ai\blender")
import numpy as np
from PIL import Image
import ai_loop

s = ai_loop.Session()
s.connect()

code = '''
import bpy
clear_scene()
setup('BLENDER_EEVEE', (320, 240), 16, (0.06, 0.07, 0.10))
m = mat('T', (0.25, 0.42, 0.30), 0.6)
# 三个朝向的面：上、前(-y)、侧(+x)
box('Top', (2,2,0.2), (0,0,1.0), None, m)
box('Front', (2,0.2,2), (0,-1,0.5), None, m)
box('Side', (0.2,2,2), (1,0,0.5), None, m)
sun = bpy.data.objects['Sun']
print('SUN_ENERGY', sun.data.energy, 'ROT', tuple(round(v,3) for v in sun.rotation_euler))
print('VIEW_TRANSFORM', bpy.context.scene.view_settings.view_transform)
'''
r = s.run(code)
print(r.get("result", {}).get("result") or r.get("message"))

import os
for energy in (3.0, 6.0, 10.0, 16.0):
    s.run(f"bpy.data.objects['Sun'].data.energy = {energy}\n")
    p = s.render(f"calib_{int(energy)}.png")
    if not p:
        print(energy, "render fail")
        continue
    a = np.asarray(Image.open(p).convert("RGB")).astype(float)
    # 取画面中央 1/3 区域（模型所在）
    h, w, _ = a.shape
    c = a[h//3:2*h//3, w//3:2*w//3]
    print(f"energy={energy:5.1f}  中心区平均 RGB = ({c[:,:,0].mean():.0f}, {c[:,:,1].mean():.0f}, {c[:,:,2].mean():.0f})")
