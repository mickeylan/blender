import bpy

m = bpy.data.materials.new("probe_mat")
m.use_nodes = True
print("NODES:", [(n.name, n.bl_idname, n.type) for n in m.node_tree.nodes])

bsdf = [n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"]
print("BSDF_PRINCIPLED count:", len(bsdf))
if bsdf:
    n = bsdf[0]
    print("name:", n.name)
    print("inputs:", [i.name for i in n.inputs])

# 5.2 里 World 的 Background 节点也确认一下
w = bpy.data.worlds.new("probe_world")
w.use_nodes = True
print("WORLD NODES:", [(n.name, n.type) for n in w.node_tree.nodes])
bg = [n for n in w.node_tree.nodes if n.type == "BACKGROUND"]
if bg:
    print("Background inputs:", [i.name for i in bg[0].inputs])

bpy.data.materials.remove(m)
bpy.data.worlds.remove(w)
