"""替换 ai_loop.py 的瓦垄块为干净实现（覆盖四个坡面）。"""
import ast

P = r"J:\mickeylan\ai\blender\ai_loop.py"
src = open(P, encoding="utf-8").read()

start_marker = "    # ---- 瓦垄（筒瓦）：沿坡向从正脊走到檐口 ----"
end_marker = "    # 4 条檐口板：封住坡面下沿，消除\"悬浮\"感"

i = src.index(start_marker)
j = src.index(end_marker, i)

NEW = '''    # ---- 瓦垄（筒瓦）：沿坡向从正脊走到檐口 ----
    # LESSONS [042]：这是让"反宇曲率可见"的关键。
    # 光有曲面时两个评审一致说"像平直斜面"——眼睛没有参照物。
    # 瓦垄沿坡向从脊走到檐，**每条垄的走向本身就是屋面的剖面曲线**，
    # 有了参照线，凹曲就一眼可辨。
    # 关键：垄线必须**贴合曲面**（每点 z 取 height(x,y)），
    # 若用直线插值，垄线自己就成了直线，参照物反而掩盖了曲率。
    if tile_ridges and tile_ridges > 0:
        _TW = max(0.05, float(tile_w))
        _TH = max(0.005, float(tile_h))
        _SEG = 14          # 每条垄沿坡向的段数
        _HALF = 5          # 每垄横截面采样点数（半圆）

        def _sweep_row(path_fn, perp_fn, x0):
            """沿坡向生成一条垄的点阵。

            path_fn(t)  : t in [0,1] 脊->檐 -> (px, py) 垄中心线
            perp_fn(s)  : s in [-1,1] 横截面 -> (dx, dy) 偏移方向
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

        # ---- 前坡 / 后坡：梯形坡面，垄沿 y 走向（脊 -> 檐）----
        # 垄沿脊向(x)分布，每条垄是一条固定 x 的窄带
        for _sgn in (-1.0, 1.0):
            _n = max(2, int(round(W / _TW)))
            _hw = _TW * 0.40
            for k in range(_n):
                _xc = -W * 0.5 + _TW * (k + 0.5)

                def _path(t, _sgn=_sgn, _xc=_xc):
                    return (_xc, _sgn * t * halfD)

                def _perp(s, _hw=_hw):
                    return (_hw * s, 0.0)

                _sweep_row(_path, _perp, _xc)

        # ---- 左坡 / 右坡：三角坡面，垄沿 x 走向（脊端 -> 檐角）----
        # 三角坡的垄要"扇开"：在脊处汇聚为一点，在檐处散开
        for _sx in (-1.0, 1.0):
            _n = max(2, int(round(D / _TW)))
            _hw = _TW * 0.40
            for k in range(_n):
                # q: 三角坡上的横向位置比例 (-1..1)
                _q = -1.0 + 2.0 * (k + 0.5) / _n

                def _path(t, _sx=_sx, _q=_q):
                    # t=0 在脊端 (x=±Rx, y=0)，t=1 在檐 (x=±W/2, y=±D/2)
                    # y 随 t 线性放大 -> 形成扇形
                    return (_sx * (Rx + (W * 0.5 - Rx) * t),
                            _q * t * halfD)

                def _perp(s, _hw=_hw):
                    return (0.0, _hw * s)

                _sweep_row(_path, _perp, 0.0)

'''

src = src[:i] + NEW + src[j:]
ast.parse(src)
open(P, "w", encoding="utf-8").write(src)
print("瓦垄块已重写，语法 OK")
print("新块行数:", NEW.count("\n"))