"""启动 GUI Blender 并自动启用 MCP 插件（无需手动点按钮）。

用法:
    blender.exe --python launch_mcp.py
脚本会:
  1. 启用 blender_mcp 插件
  2. 设置 scene.blendermcp_auto_start_server = True
  3. 轮询 9876 端口，就绪后打印 READY 并保持 Blender 打开
"""

import os
import socket
import sys
import time

import bpy

ADDONS_DIR = os.path.join(
    os.environ.get("APPDATA", ""),
    "Blender Foundation", "Blender", bpy.app.version_string,
    "scripts", "addons")
if ADDONS_DIR not in sys.path:
    sys.path.insert(0, ADDONS_DIR)

print(f"[launch] Blender {bpy.app.version_string}  addons={ADDONS_DIR}")

try:
    import addon_utils
    addon_utils.enable("blender_mcp", default_set=True, persistent=True)
    print("[launch] addon enabled")
except Exception as e:                                    # noqa: BLE001
    print(f"[launch] enable failed: {type(e).__name__}: {e}")

scene = bpy.context.scene
try:
    scene.blendermcp_auto_start_server = True
    print("[launch] auto_start_server = True")
except Exception as e:                                    # noqa: BLE001
    print(f"[launch] set auto_start failed: {e}")

# 插件的自动启动是 timer 驱动的；GUI 模式下 timer 会跑。
def _wait_ready():
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            s = socket.create_connection(("127.0.0.1", 9876), timeout=2)
            s.close()
            print("[launch] READY - MCP socket listening on 9876")
            return None
        except Exception:
            time.sleep(0.5)
    print("[launch] TIMEOUT - socket never opened")
    return None


bpy.app.timers.register(_wait_ready, first_interval=1.0)

# 打开一个 .blend 会话（空的启动文件即可），避免弹窗
print("[launch] ready")
