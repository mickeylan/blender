# 固定证据机位（照 blender-visual-craft skill 的 review.md 规范）
# LESSONS [036]：critic 只看单视图无法判断三维结构；且必须区分"形体问题"与"材质问题"。
# 故每轮产出：hero 透视（材质） + front/right/back 正交（材质） + clay 灰模（只留形体）。
VIEW_SETUP_SNIPPET = r'''
import math as _m2
from mathutils import Vector as _V2
_KIND = "{kind}"
_CLAY = {clay}

def _bounds():
    bpy.context.view_layer.update()
    _ms = [o for o in bpy.context.scene.objects
           if o.type == 'MESH' and not o.hide_render]
    _pts = []
    for _o in _ms:
        for _c in _o.bound_box:
            _pts.append(_o.matrix_world @ _V2(_c))
    if not _pts:
        return _V2((0, 0, 0)), _V2((1, 1, 1)), _pts
    _lo = _V2((min(p.x for p in _pts), min(p.y for p in _pts), min(p.z for p in _pts)))
    _hi = _V2((max(p.x for p in _pts), max(p.y for p in _pts), max(p.z for p in _pts)))
    return _lo, _hi, _pts

_lo, _hi, _pts = _bounds()
_ctr = (_lo + _hi) * 0.5
_size = _hi - _lo
_extent = max(_size.length, 0.1)
_sc = bpy.context.scene
_cam = _sc.camera
if _cam is None:
    _cd = bpy.data.cameras.new("Camera")
    _cam = bpy.data.objects.new("Camera", _cd)
    _sc.collection.objects.link(_cam)
    _sc.camera = _cam

# 视线方向（照 skill：-Y 正面 / +X 右侧 / +Y 背面 / +Z 顶部）
_DIRS = {{
    "front": _V2((0, -1, 0)),
    "right": _V2((1, 0, 0)),
    "back":  _V2((0, 1, 0)),
    "left":  _V2((-1, 0, 0)),
    "top":   _V2((0, 0, 1)),
}}

if _KIND in _DIRS:
    _cam.data.type = 'ORTHO'
    _cam.location = _ctr + _DIRS[_KIND] * _extent * 2.0
    _cam.rotation_euler = (_ctr - _cam.location).to_track_quat('-Z', 'Y').to_euler()
    # 精确正交框选：把角点投影到相机 right/up 基向量上（照 skill 的做法）
    _rot = _cam.rotation_euler.to_matrix()
    _right, _up = _rot.col[0], _rot.col[1]
    _xx = [_right.dot(p - _ctr) for p in _pts]
    _yy = [_up.dot(p - _ctr) for p in _pts]
    _cam.data.ortho_scale = max(max(_xx) - min(_xx), max(_yy) - min(_yy)) * 1.16
    _cam.data.clip_start = 0.001
    _cam.data.clip_end = _extent * 10
    print("VIEW %s ortho scale=%.2f" % (_KIND, _cam.data.ortho_scale))
else:
    _cam.data.type = 'PERSP'
    print("VIEW persp")

# ---- clay 灰模：只留形体，排除材质/光照干扰（skill 明确要求保留灰模证据）----
if _CLAY:
    _sc.render.engine = 'BLENDER_WORKBENCH'
    _sc.render.use_compositing = False
    _sc.display.shading.light = 'STUDIO'
    _sc.display.shading.color_type = 'SINGLE'
    _sc.display.shading.single_color = (0.55, 0.55, 0.55)
    _sc.display.shading.show_shadows = False      # 正交顶视会出现阴影条带
    _sc.display.shading.show_cavity = True
    _sc.display.shading.cavity_type = 'BOTH'
    _sc.display.shading.background_type = 'WORLD'
    if _sc.world is None:
        _sc.world = bpy.data.worlds.new('ClayWorld')
    _sc.world.color = (0.12, 0.12, 0.12)
    print("CLAY workbench")
else:
    # LESSONS [034]：模型常把世界背景设得很亮，Standard 下冲成一片白，主体"灰蒙蒙"。
    try:
        _w = _sc.world
        if _w and _w.use_nodes:
            _bg = next((n for n in _w.node_tree.nodes if n.type == 'BACKGROUND'), None)
            if _bg:
                _c = list(_bg.inputs[0].default_value)[:3]
                _mx = max(_c)
                if _mx > 0.32:
                    _k = 0.32 / _mx
                    _bg.inputs[0].default_value = (_c[0]*_k, _c[1]*_k, _c[2]*_k, 1.0)
                    print("BG_CLAMPED -> %s" % (tuple(round(v*_k, 3) for v in _c),))
    except Exception:
        pass

_sc.render.filepath = r"{path}"
_sc.render.image_settings.file_format = 'PNG'

# 记录机位，供跨轮对比（skill: 固定相机矩阵，否则两张自动取景图不可严格对照）
print("CAM_MATRIX %s" % " ".join("%.6f" % v for row in _cam.matrix_world for v in row))
'''