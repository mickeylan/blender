import bpy, os
from mathutils import Vector
p=r'J:\mickeylan\ai\blender\out\cultivation_market.blend'; out=r'J:\mickeylan\ai\blender\out'
bpy.ops.wm.open_mainfile(filepath=p); sc=bpy.context.scene; cam=sc.camera
views=[('market_hero',(14,-18,11),(0,0,2.2),(1200,900)),('market_front',(0,-25,7),(0,1,2.7),(1000,1000)),('market_right',(22,-2,8),(0,2,2.8),(1000,1000)),('market_detail',(5,-7,5),(0,-3,1.4),(1000,1000))]
for name,loc,target,res in views:
 cam.location=loc; cam.rotation_euler=(Vector(target)-cam.location).to_track_quat('-Z','Y').to_euler(); cam.data.lens=48
 sc.render.resolution_x,resy=res; sc.render.resolution_y=resy; sc.render.resolution_percentage=100; sc.render.image_settings.file_format='PNG'; sc.render.filepath=os.path.join(out,name+'.png'); bpy.ops.render.render(write_still=True)
# clay
old=sc.render.engine; sc.render.engine='BLENDER_WORKBENCH'; sc.display.shading.light='STUDIO'; sc.display.shading.color_type='SINGLE'; sc.display.shading.single_color=(.45,.45,.45); sc.display.shading.show_shadows=True; sc.display.shading.show_cavity=True; sc.render.filepath=os.path.join(out,'market_clay.png'); bpy.ops.render.render(write_still=True); sc.render.engine=old
cam.location=views[0][1]; cam.rotation_euler=(Vector(views[0][2])-cam.location).to_track_quat('-Z','Y').to_euler(); bpy.ops.wm.save_as_mainfile(filepath=p)
print('EVIDENCE OK market_hero/front/right/detail/clay')
