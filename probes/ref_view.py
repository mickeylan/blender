"""读画：把《清明上河图》参考图切块 + ascii 化，用来"看"虹桥的真实木构。

ascii 只能看明暗结构（看不清细节），但足以回答形制问题：
拱是几段的、梁怎么交错、有没有横向编织、腹架长什么样。
"""
import os
import sys
from PIL import Image

sys.path.insert(0, r'J:\mickeylan\ai\blender')
import view

SRC = r'J:\mickeylan\ai\blender\out\ref\scroll_detail.jpg'
TMP = r'J:\mickeylan\ai\blender\out\ref'


def dump(im, w=120, title=""):
    p = os.path.join(TMP, "_tmp.png")
    im.save(p)
    ls = view.ascii_map(p, w)[0]
    print("=== %s  %s ===" % (title, im.size))
    print('\n'.join(ls))
    print()


if __name__ == "__main__":
    im = Image.open(SRC)
    w, h = im.size
    # 全景定位（很宽，ascii 压扁）
    dump(im, 200, "全景")
