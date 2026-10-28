"""通过 MCP 截图：验证 dream-loop 的"AI 自查"通道。

对应 addon 命令: get_viewport_screenshot
参数: max_size, filepath, format
"""

import json
import os
import sys

sys.path.insert(0, r"J:\mickeylan\ai\blender")
from blender_client import BlenderMCP  # noqa: E402

OUT = r"J:\mickeylan\ai\blender\out"
os.makedirs(OUT, exist_ok=True)

c = BlenderMCP(timeout=90)
c.connect()

for view, name in (("camera", "shot_camera.png"), ("persp", "shot_persp.png")):
    path = os.path.join(OUT, name)
    try:
        r = c._send({"type": "get_viewport_screenshot",
                     "params": {"filepath": path, "max_size": 1200, "format": "png"}})
        print(f"[{view}] {json.dumps(r, ensure_ascii=False)[:500]}")
        if os.path.exists(path):
            print(f"      -> 文件存在 {os.path.getsize(path)} B")
        else:
            print("      -> 文件未生成")
    except Exception as e:                                # noqa: BLE001
        print(f"[{view}] FAIL {e}")

# 再试一次真实渲染（比视口截图更权威）
print()
try:
    r = c.execute_code(
        "import bpy\n"
        "bpy.context.scene.render.filepath = r'J:\\\\mickeylan\\\\ai\\\\blender\\\\out\\\\render_cam.png'\n"
        "bpy.ops.render.render(write_still=True)\n"
        "print('RENDER_DONE')\n")
    print("render:", json.dumps(r, ensure_ascii=False)[:300])
except Exception as e:                                    # noqa: BLE001
    print("render FAIL", e)

for f in sorted(os.listdir(OUT)):
    print(f"  {f:<28} {os.path.getsize(os.path.join(OUT, f)):>9,} B")
