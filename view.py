"""把渲染图变成终端字符图 —— 本会话无法直接看图时，用它代替"眼睛"。

用法:  python view.py out/round1_persp.png [宽]
"""
import sys

import numpy as np
from PIL import Image

CHARS = " .:-=+*#%@"


def classify(px):
    """返回 (字符, 颜色标签)。"""
    r, g, b = float(px[0]), float(px[1]), float(px[2])
    lum = (r + g + b) / 3.0
    if g > r + 8 and g > b + 4:
        tag = "G"                       # 绿（瓦/植被）
    elif r > g + 20 and r > b + 20:
        tag = "R"                       # 红/棕（木）
    elif b > r + 15 and b > g + 5:
        tag = "B"                       # 蓝
    elif lum > 170:
        tag = "W"                       # 亮
    elif lum < 55:
        tag = "K"                       # 暗
    else:
        tag = "."
    ch = CHARS[min(9, int(lum / 25.6))]
    return ch, tag


def ascii_map(path, width=72):
    im = Image.open(path).convert("RGB")
    w, h = im.size
    height = max(1, int(width * h / w / 2.1))       # 字符高宽比约 0.5
    im = im.resize((width, height), Image.LANCZOS)
    a = np.asarray(im).astype(float)
    lines = []
    tagmap = []
    for row in a:
        chars, tags = [], []
        for px in row:
            c, t = classify(px)
            chars.append(c)
            tags.append(t)
        lines.append("".join(chars))
        tagmap.append("".join(tags))
    return lines, tagmap


def main():
    path = sys.argv[1]
    width = int(sys.argv[2]) if len(sys.argv) > 2 else 72
    lines, tags = ascii_map(path, width)
    print(f"=== {path}  ({len(lines)}x{len(tags[0])}) ===")
    print("--- 亮度 ---")
    for l in lines:
        print("|" + l + "|")
    print("--- 颜色分类 (G绿 R木红 B蓝 W亮 K暗 .=其它) ---")
    for t in tags:
        print("|" + t + "|")
    # 统计
    flat = "".join(tags)
    print()
    for k in "GRBWK.":
        c = flat.count(k)
        if c:
            print(f"  {k}: {100*c/len(flat):5.1f}%")


if __name__ == "__main__":
    main()
