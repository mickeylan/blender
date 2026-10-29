import os
import sys
from PIL import Image

sys.path.insert(0, r'J:\mickeylan\ai\blender')
import view

SRC = r'J:\mickeylan\ai\blender\out\ref\scroll_detail.jpg'
TMP = r'J:\mickeylan\ai\blender\out\ref'


def dump(im, w=110, title=""):
    p = os.path.join(TMP, "_tmp.png")
    im.save(p)
    ls = view.ascii_map(p, w)[0]
    print("=== %s  %s ===" % (title, im.size))
    print('\n'.join(ls))
    print()


im = Image.open(SRC)
W, H = im.size
args = sys.argv[1:]
if args:
    x, y, cw, ch = [int(v) for v in args[:4]]
    dump(im.crop((x, y, x + cw, y + ch)), int(args[4]) if len(args) > 4 else 110,
         "crop %d,%d %dx%d" % (x, y, cw, ch))
else:
    for i in range(4):
        x = i * (W // 4)
        dump(im.crop((x, 0, x + W // 4, H)), 110, "tile %d (x=%d)" % (i, x))
