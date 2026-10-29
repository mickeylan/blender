"""重写瓦垄：平行于坡向 + 在垂脊处裁断（修 Z-fighting）。

修正前（v3 扇形）：前坡最外垄与侧坡最外垄都正好落在同一条垂脊线上，
                  两套几何重叠 -> Z-fighting -> 评审报"瓦垄在屋脊处衔接不连续"。
真实几何：瓦垄**平行于坡向**（不是扇形），沿坡向走到垂脊就停。
          前坡的垄在 x 固定，起点 t0 = (|x|-Rx)/(W/2-Rx)
          侧坡的垄在 y 固定，起点 t0 = |y|/halfD
"""
import ast

P = r"J:\mickeylan\ai\blender\ai_loop.py"
src = open(P, encoding="utf-8").read()

i = src.index("    # ---- 瓦垄（筒瓦）：从正脊扇向檐口 ----")
j = src.index("    # 4 条檐口板：", i)

NEW = '''    # ---- 瓦垄（筒瓦）：平行于坡向，在垂脊处裁断 ----
    # LESSONS [042]：这是让"反宇曲率可见"的关键。
    # 光有曲面时两个评审一致说"像平直斜面"——眼睛没有参照物。
    # 瓦垄沿坡向从脊走到檐，**每条垄的走向本身就是屋面的剖面曲线**，
    # 有了参照线，凹曲就一眼可辨。
    # 关键 1：垄线必须**贴合曲面**（每点 z 取 height(x,y)），
    #         若用直线插值，垄线自己就成了直线，参照物反而掩盖了曲率。
    # 关键 2：垄**平行于坡向**，不是扇形。扇形版本会让前坡最外垄与侧坡最外垄
    #         落在同一条垂脊线上，两套几何重叠 -> Z-fighting ->
    #         评审报"瓦垄在屋脊处衔接不连续"。
    #         正确做法：沿坡向走到垂脊就停（起点 t0 由几何算出）。
    if tile_ridges and tile_ridges > 0:
        _TW = max(0.05, float(tile_w))
        _TH = max(0.005, float(tile_h))
        _SEG = 16          # 每条垄沿坡向的段数
        _HALF = 5          # 每垄横截面采样点数（半圆）
        _hw = _TW * 0.40   # 垄半宽

        def _sweep(t0, path_fn, perp_fn):
            """沿坡向生成一条垄并铺面。t0 是坡向起点（0=脊，>0 表示被垂脊截断）。"""
            if t0 >= 0.985:
                return
            span = 1.0 - t0
            rows = []
            for i in range(_SEG + 1):
                t = t0 + span * i / _SEG
                cx, cy = path_fn(t)
                row = []
                for j in range(_HALF + 1):
                    s = -1.0 + 2.0 * j / _HALF
                    dx, dy = perp_fn(s)
                    px, py = cx + dx, cy + dy
                    pz = height(px, py)
                    bulge = math.sqrt(max(0.0, 1.0 - s * s))
                    row.append((px, py, pz + _TH * bulge))
                rows.append(row)
            for i in range(_SEG):
                for j in range(_HALF):
                    a = rows[i][j]
                    b = rows[i][j + 1]
                    c = rows[i + 1][j + 1]
                    d = rows[i + 1][j]
                    nrm = (Vector(b) - Vector(a)).cross(Vector(d) - Vector(a))
                    if nrm.z < 0:
                        add_quad_geo([a, d, c, b], 0)
                    else:
                        add_quad_geo([a, b, c, d], 0)

        # ---- 前坡 / 后坡：垄沿 y 走向（脊 -> 檐），x 固定 ----
        # 起点 t0 = (|x| - Rx) / (W/2 - Rx)：x 超出正脊半跨时，
        # 该垄在到达正脊之前就先碰上垂脊，必须在那里停。
        _n1 = max(2, int(round(W / _TW)))
        _span_x = max(1e-6, W * 0.5 - Rx)
        for _sgn in (-1.0, 1.0):
            for k in range(_n1):
                _x0 = -W * 0.5 + _TW * (k + 0.5)

                def _path(t, _sgn=_sgn, _x0=_x0):
                    return (_x0, _sgn * t * halfD)

                _t0 = max(0.0, (abs(_x0) - Rx) / _span_x)
                _sweep(_t0, _path, lambda s: (_hw * s, 0.0))

        # ---- 左坡 / 右坡：垄沿 x 走向（脊端 -> 檐角），y 固定 ----
        # 起点 t0 = |y| / halfD：靠近正脊端（y≈0）的垄已经到顶，
        # 靠檐边的垄（|y|→halfD）几乎立刻碰上垂脊。
        _n2 = max(2, int(round(D / _TW)))
        for _sx in (-1.0, 1.0):
            for k in range(_n2):
                _y0 = -halfD + _TW * (k + 0.5)

                def _path(t, _sx=_sx, _y0=_y0):
                    return (_sx * (Rx + (W * 0.5 - Rx) * t), _y0)

                _t0 = min(0.98, abs(_y0) / halfD)
                _sweep(_t0, _path, lambda s: (0.0, _hw * s))

'''

src = src[:i] + NEW + src[j:]
ast.parse(src)
open(P, "w", encoding="utf-8").write(src)
print("瓦垄块已重写为平行+裁断，语法 OK")