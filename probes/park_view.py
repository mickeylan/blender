import os
import sys
from PIL import Image

sys.path.insert(0, r'J:\mickeylan\ai\blender')
import view

SRC = r'J:\mickeylan\ai\blender\out\ref\rainbow_park.jpg'
TMP = r'J:\mickeylan\ai\blender\out\ref'


def dump(im, w=140, title=""):
    p = os.path.join(TMP, "_tmp.png")
    im.save(p)
    ls = view.ascii_map(p, w)[0]
    print("=== %s  %s ===" % (title, im.size))
    print('\n'.join(ls))
    print()


if __name__ == "__main__":
    im = Image.open(SRC)
    a = sys.argv[1:]
    if a:
        x, y, cw, ch = [int(v) for v in a[:4]]
        dump(im.crop((x, y, x + cw, y + ch)),
             int(a[4]) if len(a) > 4 else 140, "crop")
    else:
        dump(im, 160, "全景")
