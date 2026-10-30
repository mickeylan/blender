"""抽查效果层在关键帧的表现，验证体积雾和发光没有糊掉主体。"""
import bpy, os
from mathutils import Vector
BLEND=r"J:\mickeylan\ai\blender\out\xianmen_sect_tour.blend"
OUT=r"J:\mickeylan\ai\blender\out"
def main():
    bpy.ops.wm.open_mainfile(filepath=BLEND); sc=bpy.context.scene
    sc.render.engine='BLENDER_EEVEE'; sc.render.resolution_x=960; sc.render.resolution_y=540; sc.render.resolution_percentage=100
    sc.render.image_settings.file_format='PNG'
    for f,n in [(1,'fx_aerial.png'),(120,'fx_approach.png'),(300,'fx_alchemy.png'),(541,'fx_mainpeak.png'),(660,'fx_departure.png')]:
        sc.frame_set(f); sc.render.filepath=os.path.join(OUT,n); bpy.ops.render.render(write_still=True)
    print('FX SPOTCHECK OK')
main()
