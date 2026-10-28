"""用新的 VIEW_SETUP_SNIPPET 替换 ai_loop.py 里的旧版。"""
P = r"J:\mickeylan\ai\blender\ai_loop.py"
NEW = r"J:\mickeylan\ai\blender\probes\_new_view_snippet.py"

src = open(P, encoding="utf-8").read()
new_block = open(NEW, encoding="utf-8").read().rstrip("\n")

start_marker = "# 三视图机位："
end_marker = "bpy.context.scene.render.image_settings.file_format = 'PNG'\n'''"

i = src.index(start_marker)
j = src.index(end_marker, i) + len(end_marker)
old = src[i:j]
print("--- 将被替换的旧块长度:", len(old))
print(old[:160].replace("\n", " | "))
print("...")
print(old[-160:].replace("\n", " | "))

src = src[:i] + new_block + src[j:]
import ast
ast.parse(src)
open(P, "w", encoding="utf-8").write(src)
print("--- 已替换，语法 OK")