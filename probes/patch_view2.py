"""替换 VIEW_SETUP_SNIPPET 为带相机锁定功能的版本。"""
import ast
import re

P = r"J:\mickeylan\ai\blender\ai_loop.py"
NEW = r"J:\mickeylan\ai\blender\probes\_new_view_snippet2.py"

src = open(P, encoding="utf-8").read()
new_block = open(NEW, encoding="utf-8").read().rstrip("\n")

start = src.index("# 固定证据机位")
# 旧块结束于 CAM_MATRIX 那行之后的 '''
end_marker = "'''"
j = src.index("print(\"CAM_MATRIX", src.index("_sc.render.image_settings.file_format = 'PNG'", start))
j = src.index(end_marker, j) + len(end_marker)

old = src[start:j]
print("旧块行数:", old.count("\n"))
print("旧块开头:", old.split("\n")[0][:60])
print("旧块结尾:", old.split("\n")[-2][:60])

src = src[:start] + new_block + src[j:]
ast.parse(src)
open(P, "w", encoding="utf-8").write(src)
print("已替换，语法 OK")