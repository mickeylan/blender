import sys
sys.path.insert(0, r"J:\mickeylan\ai\blender")
import ai_loop
from blender_client import BlenderMCP

c = BlenderMCP(timeout=120)
c.connect()

diag = '''
import bpy
sc = bpy.context.scene
print("scene:", sc.name)
print("scene.camera:", repr(sc.camera))
print("mesh count:", sum(1 for o in sc.objects if o.type=='MESH'))
print("total objects:", len(sc.objects))
print("camera objects:", [o.name for o in bpy.data.objects if o.type=='CAMERA'])
print("collections:", [c.name for c in bpy.data.collections])
'''
r = c.execute_code(diag)
print("=== 诊断 ===")
print(r.get("result", {}).get("result", r.get("message")))

print("\n=== 单独跑 FRAME_SNIPPET ===")
r2 = c.execute_code("import bpy\n" + ai_loop.FRAME_SNIPPET)
print("status:", r2.get("status"))
print("output:", repr(r2.get("result", {}).get("result", "")))
if r2.get("status") != "success":
    print("message:", str(r2.get("message"))[:1500])

print("\n=== 再看 camera ===")
r3 = c.execute_code(
    "import bpy\n"
    "print('camera:', repr(bpy.context.scene.camera))\n"
    "if bpy.context.scene.camera:\n"
    "    print('loc:', tuple(bpy.context.scene.camera.location))\n"
)
print(r3.get("result", {}).get("result", r3.get("message")))