"""修正 _proc_ 前缀补丁：只给程序化节点（Noise/ValToRGB/Bump）加前缀。

BSDF 与 Output 绝不能加前缀 —— _reset_proc_nodes 会删掉带前缀的节点。
"""
import ast
import re

P = r"J:\mickeylan\ai\blender\ai_loop.py"
src = open(P, encoding="utf-8").read()
lines = src.split("\n")

# 撤销所有 _proc_ 前缀改名行
lines = [l for l in lines if not re.match(r"^\s*\w+\.name = '_proc_", l)]

PROC_TYPES = {"ShaderNodeTexNoise", "ShaderNodeValToRGB", "ShaderNodeBump"}
out = []
pat = re.compile(r"^(\s*)(\w+) = nt\.nodes\.new\('(ShaderNode\w+)'\)\s*$")
n = 0
for l in lines:
    out.append(l)
    m = pat.match(l)
    if m and m.group(3) in PROC_TYPES:
        indent, var, cls = m.groups()
        out.append(f"{indent}{var}.name = '_proc_{var}'")
        n += 1

new = "\n".join(out)
ast.parse(new)
open(P, "w", encoding="utf-8").write(new)
print(f"patched {n} procedural node creations")
