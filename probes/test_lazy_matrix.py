import sys
sys.path.insert(0, r"J:\mickeylan\ai\blender")
import ai_loop

s = ai_loop.Session()
s.connect()

code = '''
clear_scene()
setup()
wood = mat("Wood", (0.42, 0.24, 0.13), 0.65)
stone = mat("Stone", (0.56, 0.54, 0.50), 0.8)
prism("Base", (3.0, 2.0), 0.4, loc=(0, 0, 0.2), apex=(0.96, 0.96), material=stone)
for i, x in enumerate((-1.0, 0.0, 1.0)):
    cyl("Col_%d" % i, 0.09, 1.6, loc=(x, 0, 1.2), material=wood)
prism("Roof", (3.2, 2.2), 1.0, loc=(0, 0, 2.7), apex=(0.18, 0.18), material=wood)

from mathutils import Vector
def bbox_now(tag):
    ms = [o for o in bpy.context.scene.objects if o.type=='MESH']
    pts = [o.matrix_world @ Vector(v) for o in ms for v in o.bound_box]
    zs = [p.z for p in pts]
    print("%s bboxZ=%.3f..%.3f  Roof.matrix_world.translation=%s" % (
        tag, min(zs), max(zs), tuple(round(v,3) for v in bpy.data.objects['Roof'].matrix_world.translation)))

bbox_now("BEFORE_UPDATE")
bpy.context.view_layer.update()
bbox_now("AFTER_UPDATE ")
'''

r = s.run(code)
print("status:", r.get("status"))
print((r.get("result") or {}).get("result") or str(r.get("message"))[:800])