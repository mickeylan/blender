"""内省 5.2 合成器 node group 的正确用法，并找出 Math 节点的真实类名。"""
import bpy

scene = bpy.context.scene
print("Blender", bpy.app.version_string)

# --- 1. 找 Math / Map Range 类节点的真实类名 ---
print("\n--- 含 math / range / invert 的节点类型 ---")
for prefix in ("CompositorNode", "ShaderNode", "FunctionNode"):
    for n in sorted(dir(bpy.types)):
        if n.startswith(prefix) and any(k in n.lower() for k in ("math", "range", "invert", "normali")):
            print(f"  {n}")

# --- 2. 建 compositing node group ---
print("\n--- 创建 compositing_node_group ---")
ng = bpy.data.node_groups.new("Comp", "CompositorNodeTree")
scene.compositing_node_group = ng
print("  type:", type(ng).__name__, "| scene.compositing_node_group =", scene.compositing_node_group.name)
print("  ng.bl_idname:", ng.bl_idname)
print("  ng.interface:", type(ng.interface).__name__)

# --- 3. 加 RLayers，看输出插槽 ---
rl = ng.nodes.new("CompositorNodeRLayers")
print("\n--- Render Layers 输出插槽 ---")
for o in rl.outputs:
    print(f"  {o.identifier:<24} {o.bl_idname:<26} enabled={o.enabled}")

# --- 4. 试 Math 节点（用第 1 步找到的名字）---
for cls in ("ShaderNodeMath", "CompositorNodeMath", "FunctionNodeMath"):
    if hasattr(bpy.types, cls):
        try:
            n = ng.nodes.new(cls)
            print(f"\n  {cls} 可用 -> bl_label={n.bl_label!r}, inputs={[i.name for i in n.inputs]}")
            n2 = n
            break
        except Exception as e:  # noqa: BLE001
            print(f"  {cls} 失败: {e}")

# --- 5. File Output 在 group 内能否用 ---
try:
    fo = ng.nodes.new("CompositorNodeOutputFile")
    print("\n  CompositorNodeOutputFile 可用; base_path =", fo.base_path)
    print("  默认 slots:", [s.name for s in fo.file_slots])
except Exception as e:  # noqa: BLE001
    print("\n  CompositorNodeOutputFile 失败:", e)

# --- 6. group 的输入接口（5.2 里合成 group 的入口长什么样）---
print("\n--- node group interface sockets ---")
try:
    for s in ng.interface.items_tree:
        print(f"  {s.item_type:<10} {getattr(s,'name','?'):<20} {getattr(s,'socket_type','?')}")
except Exception as e:  # noqa: BLE001
    print("  interface 读取失败:", e)

# --- 7. Mist 通道（替代 raw Z 的归一化深度）---
print("\n--- Mist / World 设置 ---")
vl = scene.view_layers[0]
vl.use_pass_mist = True
vl.use_pass_z = True
vl.use_pass_normal = True
print("  use_pass_mist/z/normal:", vl.use_pass_mist, vl.use_pass_z, vl.use_pass_normal)
w = scene.world or bpy.data.worlds.new("World")
scene.world = w
ms = w.mist_settings
print("  mist start/depth/falloff:", ms.start, ms.depth, ms.falloff)
print("  mist 可用:", ms.is_valid if hasattr(ms, "is_valid") else "n/a")

# --- 8. Camera Data 节点（无合成器方案的深度来源）---
print("\n--- ShaderNodeCameraData / Geometry ---")
for cls in ("ShaderNodeCameraData", "ShaderNodeNewGeometry"):
    if hasattr(bpy.types, cls):
        m = bpy.data.materials.new("probe_" + cls)
        m.use_nodes = True
        n = m.node_tree.nodes.new(cls)
        print(f"  {cls}: outputs={[o.name for o in n.outputs]}")
