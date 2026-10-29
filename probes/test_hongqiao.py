"""验证 hongqiao() 助手：几何自检 + 渲染。"""
import sys
sys.path.insert(0, r"J:\mickeylan\ai\blender")
import ai_loop

s = ai_loop.Session()
s.connect()

code = '''
clear_scene()
setup('BLENDER_EEVEE', (900, 600), 48, (0.05, 0.06, 0.09))
wood = wood_mat('HQ_Wood', (0.36, 0.21, 0.12), 0.62, 16.0)
rail = wood_mat('HQ_Rail', (0.44, 0.26, 0.14), 0.58, 14.0)
plank = wood_mat('HQ_Plank', (0.40, 0.24, 0.14), 0.66, 10.0)
stone = stone_mat('HQ_Stone', (0.28, 0.27, 0.25), 0.88)
# 三套体系分色：三级(三节苗) 深 / 五级(五节苗) 浅 / 横向苗 中性偏灰
# 同色时几十根圆木叠在一起糊成一片，编织关系在渲染里读不出来。
mat_a = wood_mat('HQ_Tri', (0.24, 0.13, 0.07), 0.66, 14.0)
mat_b = wood_mat('HQ_Wu', (0.62, 0.42, 0.22), 0.55, 14.0)
# 苗保持中性灰：试过改成木色，编织层反而读不出来
# （中性灰在木构里天然是"另一层构件"的标记，改成木色后与 A/B 混成一片）。
mat_miao = wood_mat('HQ_Miao', (0.46, 0.44, 0.40), 0.72, 12.0)
hongqiao('HQ', span=20.0, width=8.0, rise=5.0, beam_r=0.34,
         ribs=4, post_h=0.60, rail_h=1.15, z=0.0, weave_amp=1.25,
         material=wood, plank_mat=plank, rail_mat=rail,
         mat_a=mat_a, mat_b=mat_b, mat_miao=mat_miao)

# 几何自检：河中是否有桥墩？桥面中部是否高于两端？
import bpy
from mathutils import Vector as V
bpy.context.view_layer.update()      # matrix_world 惰性，不 update 读到的是旧变换
pts = [o.matrix_world @ V(c) for o in bpy.data.objects
       if o.name.startswith('HQ_Plank') for c in o.bound_box]
zs = [p.z for p in pts]
print("桥面 z 范围 %.2f .. %.2f  (起拱=%.2f)" % (min(zs), max(zs), max(zs)-min(zs)))
# 桥跨中部所有构件的最低 z —— 有桥墩的话会是负值（深入河底）
mid = [o for o in bpy.data.objects if o.type == 'MESH']
midpts = []
for o in mid:
    for c in o.bound_box:
        p = o.matrix_world @ V(c)
        if abs(p.x) < 11.0 * 0.42:
            midpts.append(p.z)
print("桥跨中部最低 z = %.2f  (桥面最低 %.2f)" % (min(midpts), min(zs)))
# 上下交错检查：同一肋对里两套系统 A / B 必须在平面内重叠、竖向错开
tops = {}
for tag in ("A", "B"):
    zs_t = []
    for o in bpy.data.objects:
        if o.name.startswith('HQ_R0%s_S' % tag):
            for c in o.bound_box:
                p = o.matrix_world @ V(c)
                zs_t.append(p.z)
    tops[tag] = (min(zs_t), max(zs_t)) if zs_t else None
print("肋对0 两套系统 z 范围: %s" % tops)

# 交叉验证：两套系统的横向位置必须重叠（否则织不到一起）
ys = {}
for tag in ("A", "B"):
    yy = []
    for o in bpy.data.objects:
        if o.name.startswith('HQ_R0%s_S' % tag):
            for c in o.bound_box:
                yy.append((o.matrix_world @ V(c)).y)
    ys[tag] = (min(yy), max(yy)) if yy else None
print("肋对0 两套系统 y 范围: %s  -> 需重叠" % ys)

# ---- 编织验证：两套系统的折线必须在桥跨内**反复交叉** ----
# 取两套系统各段的中心线端点，按 x 排序后统计符号变化次数。
def seg_pts(pref):
    res = []
    for o in bpy.data.objects:
        if o.name.startswith(pref):
            for v in o.data.vertices:
                res.append(o.matrix_world @ V(v.co))
    return res

def axis_center(pref, n=400):
    """把该系统的所有顶点按 x 分桶，取每桶的最高点 -> 近似上轮廓折线。"""
    pts = seg_pts(pref)
    buckets = {}
    for p in pts:
        b = int(round(p.x * 4))
        if b not in buckets or p.z > buckets[b].z:
            buckets[b] = p
    out = []
    for b in sorted(buckets):
        out.append((b / 4.0, buckets[b].z))
    return out

A_line = axis_center('HQ_R0A_S')
B_line = axis_center('HQ_R0B_S')
x0 = min(p[0] for p in A_line)
x1 = max(p[0] for p in A_line)

def z_at(line, x):
    if x <= line[0][0]:
        return line[0][1]
    for i in range(len(line)-1):
        xa, za = line[i]
        xb, zb = line[i+1]
        if xa <= x <= xb:
            w = (x - xa) / max(1e-6, xb - xa)
            return za + (zb - za) * w
    return line[-1][1]

signs = []
N = 200
for k in range(N + 1):
    x = x0 + (x1 - x0) * k / N
    d = z_at(A_line, x) - z_at(B_line, x)
    if abs(d) > 0.02:
        s = 1 if d > 0 else -1
        if not signs or signs[-1] != s:
            signs.append(s)
print("A/B 上下关系沿桥跨的交替段数 = %d (%s)" % (
    len(signs), ''.join('AB'[0] if s > 0 else 'BA' for s in signs)))
print("  -> 交替 >=3 段 = 反复穿插编织（X 形交叉）")
stats('HONGQIAO ')
'''
r = s.run(code)
print((r.get("result") or {}).get("result") or str(r.get("message"))[:1200])

for f in s.render_views("hq"):
    print("  ", f[0], f[1])