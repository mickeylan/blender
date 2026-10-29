"""诊断渲染不确定性：EEVEE 随机源 + 像素级差异。"""
import os
import shutil
import subprocess
import sys

import numpy as np
from PIL import Image

OUT = r'J:\mickeylan\ai\blender\out'
HQ = os.path.join(OUT, 'hq_hero.png')


def probe_eevee():
    """在 Blender 里列出 eevee 的随机相关属性。"""
    code = (
        "import bpy\n"
        "sc = bpy.context.scene\n"
        "ev = sc.eevee\n"
        "print('EEVEE_ATTRS', [p.identifier for p in ev.bl_rna.properties"
        " if 'seed' in p.identifier or 'sample' in p.identifier"
        " or 'jitter' in p.identifier or 'noise' in p.identifier])\n"
        "print('RENDER_ATTRS', [p.identifier for p in sc.render.bl_rna.properties"
        " if 'seed' in p.identifier or 'dither' in p.identifier])\n"
    )
    p = os.path.join(OUT, '_probe_eevee.py')
    open(p, 'w', encoding='utf-8').write(code)
    r = subprocess.run([r'D:\python3\python.exe',
                        r'J:\mickeylan\ai\blender\blender_client.py', p],
                       capture_output=True, text=True, timeout=600)
    sys.stdout.write(r.stdout[:2000])


def diff(a, b):
    ia = np.asarray(Image.open(a).convert('RGB')).astype(int)
    ib = np.asarray(Image.open(b).convert('RGB')).astype(int)
    if ia.shape != ib.shape:
        return "尺寸不同 %s vs %s" % (ia.shape, ib.shape)
    d = np.abs(ia - ib)
    n = (d.max(axis=2) > 0).sum()
    return "不同像素 %d / %d (%.3f%%), 最大差 %d, 平均差 %.4f" % (
        n, ia.shape[0] * ia.shape[1], 100.0 * n / (ia.shape[0] * ia.shape[1]),
        d.max(), d.mean())


if __name__ == "__main__":
    if sys.argv[1:] == ["probe"]:
        probe_eevee()
    else:
        a, b = sys.argv[1], sys.argv[2]
        print("A:", a)
        print("B:", b)
        print(diff(a, b))
