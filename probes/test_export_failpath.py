"""回归测试：导出脚本**中途抛异常**时，场景必须被还原。

背景：早期版本把还原放在正常路径末尾，脚本一崩
（实测踩到：NameError 抛在 restore() 之前），
`view_layer.material_override` 就永久留在场景里，
之后每一次渲染都被 override 材质污染，且**没有任何报错**。

用法（在外层 Python 跑，不要送进 Blender）：
    D:\\python3\\python.exe probes\\test_export_failpath.py
"""
import json
import os
import subprocess
import sys

ROOT = r'J:\mickeylan\ai\blender'
PY = r'D:\python3\python.exe'
CLIENT = os.path.join(ROOT, 'blender_client.py')
SRC = os.path.join(ROOT, 'blender_export.py')
TMP = os.path.join(ROOT, 'probes', '_export_fail_test.py')

# 注入点：深度渲染之后（此时 override 已经被设成 EXPORT_Depth）
ANCHOR = 'say("[3] 深度   -> %s" % p_dep)'
INJECT = '\n    raise RuntimeError("故意炸：验证 finally 是否还原场景")'


def run(script):
    p = subprocess.run([PY, CLIENT, script], capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    txt = p.stdout + p.stderr
    try:
        start = txt.index('{')
        return json.loads(txt[start:txt.rindex('}') + 1])
    except Exception:
        return {"status": "unparsable", "raw": txt[-800:]}


def state():
    probe = os.path.join(ROOT, 'probes', '_scene_state_probe.py')
    r = run(probe)
    if r.get("status") != "success":
        raise RuntimeError("状态探针失败: %s" % r)
    body = r["result"]["result"]
    out = {}
    for line in body.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def main():
    # 1) 生成故障注入版
    s = open(SRC, encoding='utf-8').read()
    if s.count(ANCHOR) != 1:
        raise SystemExit("注入锚点找不到（blender_export.py 结构变了？）")
    open(TMP, 'w', encoding='utf-8').write(s.replace(ANCHOR, ANCHOR + INJECT))

    # 2) 记下跑之前的状态
    before = state()
    print("跑之前: override=%s  clip=%s" % (before.get('material_override'),
                                            before.get('clip')))

    # 3) 跑故障版，**应该**抛异常
    r = run(TMP)
    print("故障版返回: status=%s exception=%s" % (
        r.get("status"), r.get("message", "")[:80]))
    if r.get("status") != "error":
        raise SystemExit("故障版居然没报错，注入失效")

    # 4) 关键断言：场景被还原
    after = state()
    print("跑之后: override=%s  clip=%s  engine=%s" % (
        after.get('material_override'), after.get('clip'),
        after.get('engine')))
    ok = True
    if after.get('material_override') != 'None':
        print("!! 断言失败: material_override 没还原 -> %s"
              % after.get('material_override'))
        ok = False
    if before.get('clip') != after.get('clip'):
        print("!! 断言失败: 相机裁剪面没还原 %s -> %s"
              % (before.get('clip'), after.get('clip')))
        ok = False
    if before.get('engine') != after.get('engine'):
        print("!! 断言失败: 渲染引擎没还原 %s -> %s"
              % (before.get('engine'), after.get('engine')))
        ok = False

    os.remove(TMP)
    print("FAILPATH OK" if ok else "FAILPATH FAIL")
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
