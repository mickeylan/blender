"""渲染宗门巡游低分辨率预览，不覆盖正式工程。"""
import bpy, os
from mathutils import Vector

BLEND=r"J:\mickeylan\ai\blender\out\xianmen_sect_tour.blend"
OUT=r"J:\mickeylan\ai\blender\out\xianmen_preview_frames"

def main():
    bpy.ops.wm.open_mainfile(filepath=BLEND)
    sc=bpy.context.scene
    sc.render.engine='BLENDER_EEVEE'
    sc.render.resolution_x=480
    sc.render.resolution_y=270
    sc.render.resolution_percentage=100
    sc.render.fps=24
    sc.frame_start=1
    sc.frame_end=720
    sc.render.image_settings.file_format='PNG'
    sc.render.image_settings.color_mode='RGB'
    sc.render.image_settings.color_depth='8'
    os.makedirs(OUT,exist_ok=True)
    sc.render.filepath=os.path.join(OUT,'frame_####.png')
    bpy.ops.render.render(animation=True)
    print('XIANMEN PREVIEW OK frames=720 dir=%s' % OUT)

main()
