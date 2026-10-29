"""在活着的 Blender 里重建一座城楼，验证修正后的屋顶。"""
import sys
sys.path.insert(0, r"J:\mickeylan\ai\blender")
import ai_loop

s = ai_loop.Session()
s.connect()

code = '''
clear_scene()
setup('BLENDER_EEVEE', (1100, 760), 64, (0.055, 0.065, 0.09))
import math

tile   = wood_mat('Tile',   (0.20, 0.30, 0.24), 0.60, 22.0)
ridgeW = wood_mat('Ridge',  (0.30, 0.16, 0.09), 0.62, 16.0)
wood   = wood_mat('Wood',   (0.34, 0.19, 0.10), 0.62, 18.0)
rail   = wood_mat('Rail',   (0.40, 0.24, 0.13), 0.58, 14.0)
stone  = stone_mat('Stone', (0.24, 0.225, 0.20), 0.86, 7.0)

# ---------- 基座：宽8 深4 高3，中央拱形门洞 ----------
BW, BD, BH = 8.0, 4.0, 3.0
AW, AH = 2.6, 2.2          # 门洞宽 / 拱顶高
half_open = AW * 0.5

# 左右墙垛
for sgn in (-1, 1):
    w = (BW * 0.5) - half_open
    box('Base_Pier_%s' % ('L' if sgn < 0 else 'R'),
        (w, BD, BH),
        (sgn * (half_open + w * 0.5), 0, BH * 0.5), None, stone)
# 拱上墙体
box('Base_Spandrel', (AW, BD, BH - AH), (0, 0, AH + (BH - AH) * 0.5), None, stone)

# 拱券：半圆排列的券石
R = half_open
N = 13
for i in range(N):
    th = math.pi * (i + 0.5) / N
    cx = -R * math.cos(th)
    cz = AH - R + R * math.sin(th)
    # 券石深度收进 4%，否则会比基座深（实测 kick 到 4.69m，超目标）
    box('Arch_%02d' % i, (AW * math.pi / N * 1.15, BD * 0.94, 0.26),
        (cx, 0, cz + 0.12), (0, math.degrees(th) - 90, 0), stone)

# 台面压顶：**内收**并嵌在 BH 以内，否则整体会超 8x4x3
box('Base_Cap', (BW - 0.06, BD - 0.06, 0.22), (0, 0, BH - 0.11), None, stone)
bevel(bpy.data.objects['Base_Cap'], 0.03)

# ---------- 两层楼阁 ----------
DG_KOU = 0.085
DG_H = 12.3 * DG_KOU          # 单朵斗拱总高（12.3 倍斗口）

def tier(idx, z0, h, rooffoot_w, rooffoot_d, rise):
    # 柱
    cols = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            x = sx * (rooffoot_w * 0.5 - 0.45)
            y = sy * (rooffoot_d * 0.5 - 0.35)
            cyl('T%d_Col_%d%d' % (idx, sx > 0, sy > 0), 0.13, h,
                (x, y, z0 + h * 0.5), None, 16, wood)
            cols.append((x, y))
    # 柱头斗拱（宋代五铺作单朵）——评审明确要求"T1 屋面缺少可辨识的斗拱"
    for i, (x, y) in enumerate(cols):
        dougong('T%d_DG_%d' % (idx, i), z=z0 + h, kou=DG_KOU,
                material=wood, x=x, y=y)
    # 额枋（柱头连梁，架在栌斗底）
    yf = rooffoot_d * 0.5 - 0.35
    xf = rooffoot_w * 0.5 - 0.45
    beam('T%d_Fang_F' % idx, (-xf, -yf, z0 + h), (xf, -yf, z0 + h), 0.16, wood)
    beam('T%d_Fang_B' % idx, (-xf, yf, z0 + h), (xf, yf, z0 + h), 0.16, wood)
    beam('T%d_Fang_L' % idx, (-xf, -yf, z0 + h), (-xf, yf, z0 + h), 0.16, wood)
    beam('T%d_Fang_R' % idx, (xf, -yf, z0 + h), (xf, yf, z0 + h), 0.16, wood)
    # 栏杆（下枭 + 扶手）
    ry = rooffoot_d * 0.5 + 0.1
    rx = rooffoot_w * 0.5 + 0.1
    for zz, th in ((z0 + 0.45, 0.07), (z0 + 0.85, 0.10)):
        beam('T%d_Rail_F%d' % (idx, int(zz * 100)), (-rx, -ry, zz), (rx, -ry, zz), th, rail)
        beam('T%d_Rail_B%d' % (idx, int(zz * 100)), (-rx, ry, zz), (rx, ry, zz), th, rail)
        beam('T%d_Rail_L%d' % (idx, int(zz * 100)), (-rx, -ry, zz), (-rx, ry, zz), th, rail)
        beam('T%d_Rail_R%d' % (idx, int(zz * 100)), (rx, -ry, zz), (rx, ry, zz), th, rail)
    # 反曲屋顶：檐口在**撩檐枋之上**（斗拱高 1.05m，檐口不抬上去斗拱会穿出屋面）
    eave_z = z0 + h + DG_H
    roof = curved_roof('T%d_Roof' % idx, rooffoot_w, rooffoot_d,
                       ridge_h=eave_z + rise, eave_h=eave_z,
                       overhang=0.55, corner_lift=rise * 0.55,
                       curve=2.4, material=tile, ridge_mat=ridgeW,
                       # LESSONS [042]：加瓦垄让反宇曲率可见
                       tile_ridges=int(rooffoot_w / 0.32),
                       tile_w=0.32, tile_h=0.05)
    return roof, eave_z

T1_Z = BH
T1_H = 2.5
# 一层屋顶必须**出挑到基座之外**（基座 8.0 宽 -> 屋顶 7.6+1.1=8.7 宽）。
# 独立评审 kimi-k2.5 指出"屋檐比基座窄"是真实缺陷，已核实并修正。
r1, T1_EAVE = tier(1, T1_Z, T1_H, 7.6, 3.9, rise=1.75)

# 二层落在**一层屋檐之上**（重檐城楼）
T2_Z = T1_EAVE + 0.10
T2_H = 2.5
# 二层按一层屋面收分
r2, T2_EAVE = tier(2, T2_Z, T2_H, 5.4, 2.9, rise=1.45)

area_light('KeyFill', (-8, -11, 9), 420, 12, (0, 0, 4))
stats('CITY GATE ')

# 存盘，方便在 Blender 界面里直接查看
import os
_OUT = "J:/mickeylan/ai/blender/out"          # 正斜杠，避免 \\a \\b 被当转义
os.makedirs(_OUT, exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(_OUT, "gate_tower.blend"))
print("SAVED gate_tower.blend")
'''
r = s.run(code)
print((r.get("result") or {}).get("result") or str(r.get("message"))[:1500])

for f in s.render_views("gate"):
    print("  ", f[0], f[1])