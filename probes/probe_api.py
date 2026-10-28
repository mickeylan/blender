"""内省 Blender 5.2 的合成器 API：node_tree 去哪了，Z/Normal 通道叫什么。"""
import bpy

print("=" * 60)
print("Blender", bpy.app.version_string)
print("=" * 60)

scene = bpy.context.scene

print("\n--- Scene 上含 node/composit 的属性 ---")
for a in sorted(dir(scene)):
    if a.startswith("_"):
        continue
    if any(k in a.lower() for k in ("node", "composit")):
        try:
            v = getattr(scene, a)
        except Exception as e:  # noqa: BLE001
            v = f"<err {e}>"
        print(f"  {a:<34} {type(v).__name__:<22} {str(v)[:70]}")

print("\n--- ViewLayer 上的 pass 开关（use_pass_*）---")
vl = scene.view_layers[0]
for a in sorted(dir(vl)):
    if a.startswith("use_pass"):
        try:
            print(f"  {a:<34} {getattr(vl, a)}")
        except Exception as e:  # noqa: BLE001
            print(f"  {a:<34} <err {e}>")

print("\n--- 渲染引擎可选值 ---")
for e in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES", "BLENDER_WORKBENCH"):
    try:
        scene.render.engine = e
        print(f"  {e:<22} OK -> {scene.render.engine}")
    except Exception as ex:  # noqa: BLE001
        print(f"  {e:<22} FAIL {ex}")
scene.render.engine = "CYCLES"

print("\n--- CompositorNodeRLayers 的输出插槽名 ---")
try:
    ng = scene.compositing_node_group
    print("  compositing_node_group =", ng, type(ng).__name__)
except Exception as e:  # noqa: BLE001
    print("  compositing_node_group 不可用:", e)

print("\n--- 可用的合成节点类型里与 File Output / RLayers 相关的 ---")
names = [n for n in dir(bpy.types) if n.startswith("CompositorNode")]
for key in ("OutputFile", "RLayers", "Group", "Normalize", "Math"):
    hits = [n for n in names if key.lower() in n.lower()]
    print(f"  {key:<12} -> {hits[:6]}")
