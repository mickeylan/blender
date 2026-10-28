def curved_roof(name, width, depth, ridge_h=2.2, eave_h=0.0, overhang=0.55,
                corner_lift=0.9, curve=2.4, material=None, ridge_mat=None,
                coll_target=None):
    """庑殿顶（四坡）反曲屋顶 —— 凹曲屋面 + 起翘檐角。

    **返回单个 mesh 对象**（屋面 + 正脊 + 垂脊 + 檐口板 已合并，
    两个材质槽：0=屋面材质, 1=脊/檐材质）。
    返回单对象是刻意的 —— 这样 `roof.location.z = 5.5` 会整体移动屋顶，
    模型不必知道内部结构（早期版本返回 dict，模型当对象用直接炸掉）。

    width/depth : 屋面（不含出檐）平面尺寸
    ridge_h     : 正脊高度（相对檐口）
    eave_h      : 檐口高度
    overhang    : 出檐外挑
    corner_lift : 檐角起翘高度（0 = 不起翘）
    curve       : 反宇程度，>1 越大越凹
    """
    W = float(width) + float(overhang) * 2
    D = float(depth) + float(overhang) * 2
    Rx = max(0.0, W * 0.5 - D * 0.5)
    halfD = D * 0.5
    if Rx < 1e-4:
        Rx = W * 0.18

    N = 24          # 沿脊方向分段
    M = 16          # 沿坡向分段

    def prof(t):
        """反宇曲线：t=0 脊, t=1 檐。dz 靠近檐口变缓 -> 凹曲面。"""
        t = max(0.0, min(1.0, t))
        return eave_h + (ridge_h - eave_h) * (1.0 - (1.0 - t) ** curve)

    def corner_boost(x, y, t):
        """起翘：只有四角附近、且靠近檐口才抬升。"""
        if corner_lift <= 0.0:
            return 0.0
        ax = abs(x) / (W * 0.5)
        ay = abs(y) / (D * 0.5)
        return corner_lift * (ax ** 8) * (ay ** 8) * (t ** 1.5)

    def height(x, y):
        dx = max(0.0, abs(x) - Rx)
        t = min(1.0, max(abs(y), dx) / halfD)
        return prof(t) + corner_boost(x, y, t)

    V, F, FM = [], [], []          # verts, faces, per-face material index

    def add_quad_geo(pts, mi):
        i0 = len(V)
        V.extend(pts)
        F.append((i0, i0 + 1, i0 + 2, i0 + 3))
        FM.append(mi)

    # ---- 4 个坡面 ----
    def panel(pts_grid, mi, outward):
        """pts_grid 是 (M+1) x (N+1) 的点阵；自动修正法线朝外。"""
        rows = []
        for j in range(M):
            row = []
            for i in range(N):
                a = pts_grid[j][i]
                b = pts_grid[j][i + 1]
                c = pts_grid[j + 1][i + 1]
                d = pts_grid[j + 1][i]
                n = (Vector(b) - Vector(a)).cross(Vector(d) - Vector(a))
                if n.length > 1e-12 and n.normalized().dot(Vector(outward)) < 0:
                    quad = [a, d, c, b]
                else:
                    quad = [a, b, c, d]
                row.append(quad)
            rows.append(row)
        for j in range(M):
            for i in range(N):
                add_quad_geo(rows[j][i], mi)

    def front_edge(u, tv):
        return ((Rx + (W * 0.5 - Rx) * tv) * (1 if u >= 0 else -1), -tv * halfD)

    def back_edge(u, tv):
        return ((Rx + (W * 0.5 - Rx) * tv) * (1 if u >= 0 else -1), tv * halfD)

    def end_edge(sign):
        def f(u, tv):
            return (sign * (Rx + (W * 0.5 - Rx) * tv), u * tv * halfD)
        return f

    for edge_fn, outward in (
        (front_edge, (0, -1, 0.35)),
        (back_edge, (0, 1, 0.35)),
        (end_edge(-1), (-1, 0, 0.35)),
        (end_edge(1), (1, 0, 0.35)),
    ):
        grid = []
        for j in range(M + 1):
            tv = j / M
            row = []
            for i in range(N + 1):
                u = -1.0 + 2.0 * i / N
                x, y = edge_fn(u, tv)
                row.append((x, y, height(x, y)))
            grid.append(row)
        panel(grid, 0, outward)

    # ---- 方木几何（正脊 / 垂脊 / 檐口板）----
    CUBE_FACES = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1),
                  (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]

    def add_box_geo(size, center, quat=None, mi=1):
        sx, sy, sz = size[0] * 0.5, size[1] * 0.5, size[2] * 0.5
        local = [(-sx, -sy, -sz), (-sx, -sy, sz), (-sx, sy, -sz), (-sx, sy, sz),
                 (sx, -sy, -sz), (sx, -sy, sz), (sx, sy, -sz), (sx, sy, sz)]
        c = Vector(center)
        pts = []
        for p in local:
            v = Vector(p)
            if quat is not None:
                v = quat @ v
            pts.append(tuple(c + v))
        i0 = len(V)
        V.extend(pts)
        for f in CUBE_FACES:
            F.append(tuple(i0 + k for k in f))
            FM.append(mi)

    def add_bar(p0, p1, thick, mi=1):
        a, b = Vector(p0), Vector(p1)
        d = b - a
        L = d.length
        if L < 1e-6:
            return
        q = d.to_track_quat('Z', 'Y')
        add_box_geo((thick, thick, L), (a + b) * 0.5, q, mi)

    # 正脊
    add_box_geo((Rx * 2 + 0.25, 0.30, 0.30), (0, 0, ridge_h + 0.15), None, 1)

    # 4 条垂脊：从脊端沿曲面下到檐角
    for p0, p1 in (((Rx, 0.0), (W * 0.5, -halfD)),
                   ((Rx, 0.0), (W * 0.5, halfD)),
                   ((-Rx, 0.0), (-W * 0.5, -halfD)),
                   ((-Rx, 0.0), (-W * 0.5, halfD))):
        segs = 10
        prev = None
        for k in range(segs + 1):
            t = k / segs
            x = p0[0] + (p1[0] - p0[0]) * t
            y = p0[1] + (p1[1] - p0[1]) * t
            cur = (x, y, height(x, y) + 0.06)
            if prev is not None:
                add_bar(prev, cur, 0.16, 1)
            prev = cur

    # 4 条檐口板：封住坡面下沿，消除"悬浮"感
    for p0, p1 in (((-W * 0.5, -halfD), (W * 0.5, -halfD)),
                   ((-W * 0.5, halfD), (W * 0.5, halfD)),
                   ((-W * 0.5, -halfD), (-W * 0.5, halfD)),
                   ((W * 0.5, -halfD), (W * 0.5, halfD))):
        add_bar((p0[0], p0[1], height(*p0)), (p1[0], p1[1], height(*p1)), 0.18, 1)

    me = bpy.data.meshes.new(name)
    me.from_pydata(V, [], F)
    me.update()
    ob = _link(bpy.data.objects.new(name, me))

    # 材质槽：0 = 屋面, 1 = 脊/檐
    if material is not None:
        me.materials.append(material)
    if ridge_mat is not None:
        me.materials.append(ridge_mat)
    elif material is not None:
        me.materials.append(material)
    for p, mi in zip(me.polygons, FM):
        p.material_index = min(mi, max(0, len(me.materials) - 1))

    if coll_target is not None:
        coll_target.objects.link(ob)
        bpy.context.scene.collection.objects.unlink(ob)
    return ob

