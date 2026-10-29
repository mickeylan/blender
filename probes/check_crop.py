"""验证正交视图不再裁切：物体像素不得触及图像边界。

做法：读渲染图，扫四边一圈，看是否存在非背景像素。
背景是 setup() 设的世界色 (0.05,0.06,0.08) -> sRGB 约 (63,68,74)。
"""
import sys
import numpy as np
from PIL import Image

sys.path.insert(0, r"J:\mickeylan\ai\blender")

BG = np.array([63, 68, 74], dtype=int)


def touching(path, tol=26):
    im = np.asarray(Image.open(path).convert("RGB")).astype(int)
    h, w, _ = im.shape
    # 背景不止一种（EEVEE 有渐变），用"与四边角点色差异"判断
    corner = im[0, 0]
    mask = (np.abs(im - corner).sum(axis=2) > tol)

    def edge_has(m):
        return bool(m.any())

    out = {}
    out["top"] = edge_has(mask[0, :])
    out["bottom"] = edge_has(mask[h - 1, :])
    out["left"] = edge_has(mask[:, 0])
    out["right"] = edge_has(mask[:, w - 1])
    return out, (w, h)


if __name__ == "__main__":
    # 细节大样（detail）是**故意**的局部裁切放大，边缘触边是预期行为，
    # 不算缺陷 —— 建筑做法图的节点大样就是这样。
    EXPECTED_CROP = ("detail",)
    files = sys.argv[1:]
    bad = 0
    for f in files:
        e, size = touching(f)
        hit = [k for k, v in e.items() if v]
        expect = any(k in f.lower() for k in EXPECTED_CROP)
        if expect:
            tag = "CROP*" if hit else "OK  *"
        else:
            tag = "CROP" if hit else "OK  "
            if hit:
                bad += 1
        print("%s %-34s %dx%d  触边=%s" % (tag, f.split("\\")[-1], size[0], size[1],
                                           hit or "-"))
    print("\n裁切的图: %d / %d" % (bad, len(files)))
