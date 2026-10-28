import bpy, addon_utils, socket, time, sys
sys.path.insert(0, r"C:\Users\Administrator\AppData\Roaming\Blender Foundation\Blender\5.2\scripts\addons")
try:
    addon_utils.enable("blender_mcp", default_set=True, persistent=True)
    print("ENABLE_OK")
except Exception as e:
    print("ENABLE_FAIL", type(e).__name__, e)
# 等一下服务线程起来
for i in range(40):
    try:
        s = socket.create_connection(("127.0.0.1", 9876), timeout=2)
        print("PORT_OPEN after", i*0.25, "s")
        s.close(); break
    except Exception as e:
        time.sleep(0.25)
else:
    print("PORT_CLOSED")
print("bpy.app.timers running?")
bpy.ops.wm.quit_blender()
