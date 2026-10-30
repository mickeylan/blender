"""女侠转台视频：固定灯光，镜头绕人物 360 度。

默认 6 秒 / 24fps / 144 帧。先用 --preview 渲染 24 帧验证机位，再去掉
--preview 输出正式 MP4。视频对应 warrior_lookdev.blend 版本。

后台运行：
  Blender.exe --background --python warrior_turntable.py -- --blend out/warrior_lookdev.blend
"""
import argparse
import math
import os
import bpy
from mathutils import Vector


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blend", default=r"J:\mickeylan\ai\blender\out\warrior_lookdev.blend")
    ap.add_argument("--out", default=r"J:\mickeylan\ai\blender\out\warrior_turntable.mp4")
    ap.add_argument("--preview", action="store_true")
    # Blender 5.2 在部分 Windows 启动方式下会把自身参数也留在
    # sys.argv；只取脚本选项，避免 argparse 把 --background 当成脚本参数。
    args, _unknown = ap.parse_known_args()

    bpy.ops.wm.open_mainfile(filepath=args.blend)
    sc = bpy.context.scene
    cam = bpy.data.objects.get("WarriorCam")
    if cam is None:
        raise RuntimeError("WarriorCam not found")
    sc.camera = cam
    fps = 24
    frames = 24 if args.preview else 144
    sc.render.engine = 'BLENDER_EEVEE'
    sc.render.resolution_x = 720 if args.preview else 900
    sc.render.resolution_y = 900 if args.preview else 1100
    sc.render.resolution_percentage = 100
    sc.render.fps = fps
    sc.frame_start = 1
    sc.frame_end = frames
    # 当前 Blender 5.2 构建的 file_format 枚举没有 FFMPEG；先输出无损
    # PNG 序列，再由外部 ffmpeg 编码，避免把视频编码能力误当成 Blender 能力。
    seq_dir = os.path.splitext(args.out)[0] + ("_preview_frames" if args.preview else "_frames")
    os.makedirs(seq_dir, exist_ok=True)
    sc.render.image_settings.file_format = 'PNG'
    sc.render.image_settings.color_mode = 'RGB'
    sc.render.image_settings.color_depth = '8'
    sc.render.filepath = os.path.join(seq_dir, "frame_####.png")

    target = Vector((0.0, 0.0, 1.03))
    radius = 2.65
    height = 1.20
    for f in range(1, frames + 1):
        t = (f - 1) / float(frames)
        a = math.radians(28.0) + t * math.tau
        cam.location = target + Vector((radius * math.sin(a), -radius * math.cos(a), height))
        cam.rotation_euler = (target - cam.location).to_track_quat('-Z', 'Y').to_euler()
        cam.data.lens = 58
        cam.keyframe_insert(data_path="location", frame=f)
        cam.keyframe_insert(data_path="rotation_euler", frame=f)
    # 每帧显式写入相机关键帧；Blender 5.2 的 Action 已采用 slots API，
    # 不再访问旧版 action.fcurves，避免后台脚本在渲染前崩溃。
    bpy.ops.render.render(animation=True)
    print("TURN TABLE OK: %s frames=%d" % (sc.render.filepath, frames))

if __name__ == "__main__":
    main()
