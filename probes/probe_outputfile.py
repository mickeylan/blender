"""内省 5.2 CompositorNodeOutputFile 的新 API：file_output_items 怎么加槽。"""
import bpy

ng = bpy.data.node_groups.new("Comp", "CompositorNodeTree")
fo = ng.nodes.new("CompositorNodeOutputFile")

print("fo.directory =", repr(fo.directory))
print("fo.file_name =", repr(fo.file_name))
print("fo.format.file_format 可选:", [i.identifier for i in fo.format.bl_rna.properties["file_format"].enum_items])
print("fo.format.color_depth 可选:", [i.identifier for i in fo.format.bl_rna.properties["color_depth"].enum_items])
print("fo.format.color_mode 可选:", [i.identifier for i in fo.format.bl_rna.properties["color_mode"].enum_items])

print("\n--- file_output_items 集合 API ---")
items = fo.file_output_items
print("type:", type(items).__name__)
print("dir:", [a for a in dir(items) if not a.startswith("_")])
print("len:", len(items))

print("\n--- 尝试 add() ---")
try:
    it = items.add()
    print("add() OK ->", it)
    print("  item dir:", [a for a in dir(it) if not a.startswith("_")])
    for a in ("name", "path", "socket_type", "use_file_extension", "format", "index"):
        if hasattr(it, a):
            try:
                print(f"  {a} = {getattr(it, a)!r}")
            except Exception as e:  # noqa: BLE001
                print(f"  {a} -> err {e}")
except Exception as e:                                    # noqa: BLE001
    print("add() 失败:", e)

print("\n--- add 之后 len / 列表 ---")
try:
    print("len:", len(items))
    for i, it in enumerate(items):
        print(f"  [{i}] name={getattr(it,'name','?')!r} socket_type={getattr(it,'socket_type','?')!r}")
except Exception as e:                                    # noqa: BLE001
    print("读取失败:", e)

print("\n--- 尝试 items.new('Depth') / items.add('Depth') ---")
for expr in ("items.new('Depth')", "items.add('Depth')"):
    try:
        r = eval(expr)
        print(f"  {expr} -> OK {r}")
    except Exception as e:                                # noqa: BLE001
        print(f"  {expr} -> FAIL {type(e).__name__}: {e}")

print("\n--- OutputFile 的 inputs 插槽（用于连线）---")
for s in fo.inputs:
    print(f"  {s.identifier:<18} {s.bl_idname:<22} linked={s.is_linked}")

print("\n--- 是否有 Scene Output 节点（5.2 合成器新入口）---")
for n in sorted(dir(bpy.types)):
    if n.startswith("CompositorNode") and any(k in n for k in ("Output", "Viewer", "Composite")):
        print("  ", n)

print("\n--- CompositorNodeComposite 是否存在 ---")
print("  ", hasattr(bpy.types, "CompositorNodeComposite"))
if hasattr(bpy.types, "CompositorNodeComposite"):
    c = ng.nodes.new("CompositorNodeComposite")
    print("   inputs:", [s.name for s in c.inputs])
    print("   outputs:", [s.name for s in c.outputs])
