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

# 说明性小样：台基 + 柱 + 梁 + 收分屋顶
prism("Base", (3.0, 2.0), 0.4, loc=(0, 0, 0.2), apex=(0.96, 0.96), material=stone)
for i, x in enumerate((-1.0, 0.0, 1.0)):
    cyl("Col_%d" % i, 0.09, 1.6, loc=(x, 0, 1.2), material=wood)
beam("Beam_F", (-1.2, -0.5, 2.0), (1.2, -0.5, 2.0), 0.14, material=wood)
beam("Beam_B", (-1.2, 0.5, 2.0), (1.2, 0.5, 2.0), 0.14, material=wood)
prism("Roof", (3.2, 2.2), 1.0, loc=(0, 0, 2.7), apex=(0.18, 0.18), material=wood)
stats("PRELUDE_TEST ")
'''
r = s.run(code)
print("status:", r.get("status"))
print("output:", (r.get("result") or {}).get("result"))
if r.get("status") != "success":
    print("message:", str(r.get("message"))[:1500])