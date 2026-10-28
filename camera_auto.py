"""相机自动取景 —— 解决 LESSONS.md [013] 发现的"模型被画面裁掉"问题。

在渲染前调用，按所有网格对象的包围盒自动定位相机与焦距。
不依赖 bpy.ops.view3d.*（那需要 view3d 上下文，MCP 驱动时往往拿不到）。
"""

import math

import bpy
from mathutils import Vector

FRAME_MARGIN = 1.28          # 留白系数，1.0 = 刚好贴边


def scene_bbox(only_collection=None):
    """返回所有可见网格对象的世界包围盒 (min, max)。"""
    lo = Vector((float("inf"),) * 3)
    hi = Vector((float("-inf"),) * 3)
    found = False
    objs = only_collection.objects if only_collection else bpy.context.scene.objects
    for ob in objs:
        if ob.type != 'MESH':
            continue
        if ob.hide_render:
            continue
        for corner in ob.bound_box:                      # 本地空间 8 角
            p = ob.matrix_world @ Vector(corner)
            lo = Vector((min(lo.x, p.x), min(lo.y, p.y), min(lo.z, p.z)))
            hi = Vector((max(hi.x, p.x), max(hi.y, p.y), max(hi.z, p.z)))
            found = True
    if not found:
        raise RuntimeError("场景里没有可渲染的网格对象，无法取景")
    return lo, hi


def frame_camera(cam=None, direction=(0.85, -1.15, 0.75), margin=FRAME_MARGIN,
                 lens=50.0):
    """把相机摆到能完整框住整个场景的位置。

    direction: 相机相对模型中心的方向（相机在模型这一侧往回看）
    margin:    1.0 = 包围盒顶点正好落在画面边缘；>1 会留白
    """
    scene = bpy.context.scene
    if cam is None:
        cam = scene.camera
    if cam is None:
        cam_data = bpy.data.cameras.new("Camera")
        cam = bpy.data.objects.new("Camera", cam_data)
        scene.collection.objects.link(cam)
        scene.camera = cam

    lo, hi = scene_bbox()
    center = (lo + hi) * 0.5
    radius = max((hi - lo).length * 0.5, 1e-4)

    cam.data.lens = lens
    cam.data.sensor_fit = 'AUTO'
    # 以较窄的一边算垂直视场，保守取景
    sensor_w = cam.data.sensor_width
    res_x = scene.render.resolution_x
    res_y = scene.render.resolution_y
    aspect = res_x / max(res_y, 1)
    sensor_h = sensor_w / aspect if aspect >= 1.0 else sensor_w
    fov_w = 2 * math.atan(sensor_w / (2 * lens))
    fov_h = 2 * math.atan(sensor_h / (2 * lens))
    fov = min(fov_w, fov_h)

    dist = radius / math.tan(fov / 2) * margin

    d = Vector(direction).normalized()
    cam.location = center + d * dist
    cam.rotation_euler = (center - cam.location).to_track_quat('-Z', 'Y').to_euler()

    return {
        "center": tuple(round(v, 4) for v in center),
        "radius": round(radius, 4),
        "distance": round(dist, 4),
        "fov_deg": round(math.degrees(fov), 2),
        "bbox_min": tuple(round(v, 4) for v in lo),
        "bbox_max": tuple(round(v, 4) for v in hi),
    }


if __name__ == "__main__":
    info = frame_camera()
    print("FRAMED:", info)