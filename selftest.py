"""端到端自检：确认 MCP 连通、助手库可用、取景可取。

    python selftest.py
"""

import sys

sys.path.insert(0, r"J:\mickeylan\ai\blender")

import ai_loop  # noqa: E402

checks = []

# 1) 配置可读
for alias in ("ali", "minimax"):
    try:
        url, key, model = ai_loop.load_provider(alias)
        checks.append((f"provider {alias}", True, f"{model} @ {url}"))
    except Exception as e:                                # noqa: BLE001
        checks.append((f"provider {alias}", False, str(e)[:80]))

# 2) MCP 连通
s = ai_loop.Session()
try:
    info = s.connect()
    checks.append(("MCP socket", True,
                   f"{info.get('name')} v{info.get('addon_version')}"))
except Exception as e:                                    # noqa: BLE001
    checks.append(("MCP socket", False, str(e)[:80]))
    for name, ok, detail in checks:
        print(f"[{'OK ' if ok else 'FAIL'}] {name:<18} {detail}")
    raise SystemExit(1)

# 3) 安全护栏拦截 read_factory_settings
blocked = ai_loop.check_code_safety("bpy.ops.wm.read_factory_settings()")
checks.append(("护栏:read_factory", blocked is not None, "已拦截"))

# 4) 助手库 + 取景
probe = '''
clear_scene()
setup('BLENDER_EEVEE', (640, 480), 16)
wood = mat('W', (0.5, 0.25, 0.1))
box('A', (1, 1, 1), (0, 0, 0.5), None, wood)
box('B', (1, 1, 2), (0.8, 0, 1.0))
stats('SELFTEST ')
'''
r = s.run(probe)
out = (r.get("result") or {}).get("result", "")
checks.append(("助手库", r.get("status") == "success", out.strip().splitlines()[-1]
               if out.strip() else str(r.get("message"))[:80]))

# 5) 端正的容错：None 占位 + 角度
tol = '''
clear_scene(); setup()
m = mat('M', (0.4, 0.3, 0.2))
box('X', (2, 3, 4), (0, 0, 0), None, m)
cyl('Y', 0.3, 1.0, (0, 0, 1), (90, 0, 0), 12, m)
import math
print('ROT %.4f' % bpy.data.objects['Y'].rotation_euler[0], 'EXPECT %.4f' % math.radians(90))
'''
r = s.run(tol)
out = (r.get("result") or {}).get("result", "")
checks.append(("容错层", "ROT 1.5708" in out, out.strip().replace("\n", " | ")[:90]))

# 6) 渲染 + 取景
shot = s.render("selftest.png")
checks.append(("渲染+取景", shot is not None, str(shot)))

print()
for name, ok, detail in checks:
    print(f"[{'OK ' if ok else 'FAIL'}] {name:<18} {detail}")

bad = [c for c in checks if not c[1]]
print()
print(f"结果: {len(checks) - len(bad)}/{len(checks)} 通过")
raise SystemExit(1 if bad else 0)