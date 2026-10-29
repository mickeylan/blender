import bpy

sc = bpy.context.scene
c = sc.camera
print("engine = %s" % sc.render.engine)
print("clip = %s" % ("%s %s" % (round(c.data.clip_start, 4),
                                round(c.data.clip_end, 2))))
print("material_override = %s" % bpy.context.view_layer.material_override)
print("view_transform = %s" % sc.view_settings.view_transform)
print("objects = %s" % len(bpy.data.objects))
