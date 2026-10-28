import sys
sys.path.insert(0, r"J:\mickeylan\ai\blender")
import ai_loop

s = ai_loop.Session()
s.connect()

code = '''
import bpy
m = bpy.data.materials.new("PROBE_MAT")
m.use_nodes = True
nt = m.node_tree
print("NODES:", [(n.name, n.type, n.bl_idname) for n in nt.nodes])
bsdf = next((n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'), None)
print("BSDF_FOUND:", bsdf)
if bsdf:
    print("INPUTS_BEFORE:", [i.name for i in bsdf.inputs])
    print("HAS_BaseColor:", "Base Color" in [i.name for i in bsdf.inputs])

# 模拟 _reset_proc_nodes
keep = bsdf
for n in list(nt.nodes):
    if n is not keep:
        nt.nodes.remove(n)
print("NODES_AFTER:", [(n.name, n.type) for n in nt.nodes])
b2 = next((n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'), None)
print("BSDF2_FOUND:", b2)
if b2:
    names = [i.name for i in b2.inputs]
    print("INPUTS_AFTER:", names)
    print("HAS_BaseColor_after:", "Base Color" in names)
'''
r = s.c.execute_code(code)
print(r.get("result", {}).get("result") or r.get("message"))