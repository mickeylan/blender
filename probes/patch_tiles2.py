"""重写瓦垄：改为从正脊扇向檐口（真实庑殿顶瓦垄走向）。

修正前：前坡瓦垄的 x 固定在 [-W/2, W/2]，但正脊只有 [-Rx, Rx]，
          -> 垄的起点落在垂脊之外，脊部附近瓦垄断裂（kimi 报"瓦垄显示不完整"）。
修正后：垄中心线 x(t) = s * (Rx + (W/2-Rx)*t)，s in [-1,1] 为脊上的归一化位置，
          -> 从正脊上一点扇向檐口一点，正是庑殿顶真实瓦垄走向。
"""
import ast

P = r"J:\mickeylan\ai\blender\ai_loop.py"
src = open(P, encoding="utf-8").read()

i = src.index("    # ---- 瓦垄（筒瓦）：沿坡向从正脊走到檐口 ----")
j = src.index("    # 4 条檐口板：", i)

NEW = '''    # ---- 瓦垄（筒瓦）：从正脊扇向檐口 ----
    # LESSONS [042]：这是让"反宇曲率可见"的关键。
    # 光有曲面时两个评审一致说"像平直斜面"——眼睛没有参照物。
    # 瓦垄沿坡向从脊走到檐，**每条垄的走向本身就是屋面的剖面曲线**，
    # 有了参照线，凹曲就一眼可辨。
    # 关键 1：垄线必须**贴合曲面**（每点 z 取 height(x,y)），
    #         若用直线插值，垄线自己就成了直线，参照物反而掩盖了曲率。
    # 关键 2：垄必须**从正脊扇向檐口**，不能沿 x 平移 ——
    #         正脊只有 [-Rx, Rx]，若垄起点落在 [-W/2, W/2]，
    #         脊部附近就是断的（评审实测报"瓦垄显示不完整"）。
    if tile_ridges and tile_ridges > 0:
        _TW = max(0.05, float(tile_w))
        _TH = max(0.005, float(tile_h))
        _SEG = 16          # 每条垄沿坡向的段数
        _HALF = 5          # 每垄横截面采样点数（半圆）
        _hw = _TW * 0.40   # 垄半宽

        def _sweep(path_fn, perp_fn):
            """沿坡向生成一条垄的点阵并铺面。

            path_fn(t) : t in [0,1] 脊->檐 -> (px, py) 垄中心线
            perp_fn(s) : s in [-1,1] 横截面 -> (dx, dy)
            """
            rows = []
            for i in range(_SEG + 1):
                t = i / _SEG
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

        # ---- 前坡 / 后坡：梯形坡面 ----
        # 垄在正脊上的归一化位置 s in [-1,1]，随坡向扇开到檐口
        _n1 = max(3, int(round(W / _TW)))
        for _sgn in (-1.0, 1.0):
            for k in range(_n1):
                _s = -1.0 + 2.0 * k / (_n1 - 1) if _n1 > 1 else 0.0

                def _path(t, _s=_s, _sgn=_sgn):
                    _halfspan = Rx + (W * 0.5 - Rx) * t
                    return (_s * _halfspan, _sgn * t * halfD)

                _sweep(_path, lambda s: (_hw * s, 0.0))

        # ---- 左坡 / 右坡：三角坡面 ----
        # 垄在脊端归一化位置 q in [-1,1]，沿坡向扇开到檐边
        _n2 = max(3, int(round(D / _TW)))
        for _sx in (-1.0, 1.0):
            for k in range(_n2):
                _q = -1.0 + 2.0 * k / (_n2 - 1) if _n2 > 1 else 0.0

                def _path(t, _q=_q, _sx=_sx):
                    return (_sx * (Rx + (W * 0.5 - Rx) * t),
                            _q * t * halfD)

                _sweep(_path, lambda s: (0.0, _hw * s))

'''

src = src[:i] + NEW + src[j:]
ast.parse(src)
open(P, "w", encoding="utf-8").write(src)
print("瓦垄块已重写为扇形，语法 OK")