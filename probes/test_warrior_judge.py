"""古装女侠白模的视觉评审：找**形体缺陷**，不评美不评喜���。

原则（沿用 LESSONS [063][064]）：
  - 提问要**可判定的几何问题**，不要"好不好看"；
  - 多模型、多轮，看分布不看单次；
  - 实测数据从场景实时量取，标注"仅供参考"，避免模型被数字带跑。

用法：
    D:\\python3\\python.exe probes\\test_warrior_judge.py --rounds 2
"""
import argparse
import json
import os
import sys

sys.path.insert(0, r"J:\mickeylan\ai\blender")
import ai_loop

VIEWS = ["hero", "front", "side", "back", "face", "clay"]
LABELS = {
    "hero": "3/4 视角（从她的右前方看，剑臂靠近镜头）",
    "front": "正视图（-Y 方向）",
    "side": "侧视图（-X 方向，从她的右侧看）",
    "back": "后视图（+Y 方向）",
    "face": "脸部近景（判断五官用）",
    "clay": "灰模（只反映形体，不反映材质）",
}

SYS = u"""你是角色建模评审专家，专���看**形体缺陷**。

请只依据图像判断，看不清就写 "unclear" 并说明为什么，**不要猜**。

必须逐项回答（用 JSON，字段固定）：
{
  "pose_reads_as_sword_strike": "yes|no|unclear",
  "ponytail_visible": "yes|no|unclear",
  "sword_clearly_visible": "yes|no|unclear",
  "hourglass_readable": "yes|no|unclear",
  "head_count_est": "大约几头身（数字或 unclear）",
  "reads_as_beautiful_woman": "yes|no|unclear",
  "face_has_features": "yes|no|unclear",
  "defects": ["形体缺陷，每条一句话"],
  "useless_parts": ["看起来多余/粘连/穿模的部位"],
  "verdict": "一句话结论"
}

判定标准（务必照此执行）：
- pose_reads_as_sword_strike=yes：能看出**蓄力或劈砍的动态** —— 身体有扭转、
  重心偏压、持剑臂抬起或挥出，而不是直立站姿。
- ponytail_visible=yes：**能看清**一条从后脑甩出的长发辫（不是模糊一团）。
- sword_clearly_visible=yes：剑的轮廓完整可辨（剑身 + 剑格 + 剑柄），
  不被身体遮掉、不只是一根看不清的细线。
- hourglass_readable=yes：从**正视图**能看出腰明显比胸和臀细。
- 头身比：数头顶到下巴是几个头高。
- reads_as_beautiful_woman=yes：这是**白模**（无贴图、单色为主），
  但仍应能看出是**年轻女性**且线条优美：脸有五官（眼/眉/鼻/唇）、
  腰细、腿长、肩窄、发型是女式。若只是"一个光滑的人形"，
  或五官糊成一片、性别不明，写 no。
- face_has_features=yes：在"脸部近景"那一张里能分辨出眼、眉、鼻、唇，
  不是一片空白的光头脸。

"defects" 只写**能指出来的**具体问题，例如"左臂和裙面粘连看不出轮廓"、
"裙摆穿透左腿"、"马尾辫根部有一段断开"。不要写风格偏好。
"""

_PROBE = u'''
import bpy
from mathutils import Vector
def bb(prefix):
    lo = Vector((1e9,)*3); hi = Vector((-1e9,)*3); f = False
    for ob in bpy.data.objects:
        if ob.type != 'MESH' or not ob.name.startswith(prefix): continue
        f = True
        for c in ob.bound_box:
            p = ob.matrix_world @ Vector(c)
            for i in range(3):
                lo[i] = min(lo[i], p[i]); hi[i] = max(hi[i], p[i])
    return (lo, hi) if f else (None, None)

me = bpy.data.objects.get("Body_Torso")
def w(z, tol=0.012):
    xs = [v.co.x for v in me.vertices if abs(v.co.z - z) < tol]
    return (max(xs)-min(xs)) if len(xs) > 3 else 0
print("MEAS 身高=%.3f" % (bb("Head")[1].z - min((ob.matrix_world @ Vector(c)).z
      for ob in bpy.data.objects if ob.name.startswith("Foot_")
      for c in ob.bound_box)))
print("MEAS 头高=%.3f" % (bb("Head")[1].z - bb("Head")[0].z))
print("MEAS 头身比=%.2f" % ((bb("Head")[1].z - min((ob.matrix_world @ Vector(c)).z
      for ob in bpy.data.objects if ob.name.startswith("Foot_")
      for c in ob.bound_box)) / (bb("Head")[1].z - bb("Head")[0].z)))
print("MEAS 肩宽=%.3f" % (bb("Deltoid")[1].x - bb("Deltoid")[0].x))
print("MEAS 胸宽=%.3f 腰宽=%.3f 臀宽=%.3f" % (w(1.235), w(1.060), w(0.900)))
print("MEAS 腰臀比=%.3f" % (w(1.060)/w(0.900)))
print("MEAS 剑尖高=%.3f" % bb("Sword_Blade")[1].z)
print("MEAS 构件数=%d" % sum(1 for o in bpy.data.objects if o.type=='MESH'))
'''


def measure():
    s = ai_loop.Session()
    s.connect()
    r = s.c.execute_code(_PROBE)
    out = str(r.get("result", {}).get("result", ""))
    return [ln.split("MEAS ", 1)[1].strip()
            for ln in out.splitlines() if "MEAS " in ln]


def build(meas):
    blocks = []
    for i, v in enumerate(VIEWS, 1):
        blocks.append({"type": "text", "text": u"第 %d 张：%s" % (i, LABELS[v])})
        blocks.append(ai_loop.img_block(
            r"J:\mickeylan\ai\blender\out\warrior_%s.png" % v))
    blocks.append({"type": "text", "text":
                   u"以下是从当前 Blender 场景**实测**的数据（供你核对，不是结论）：\n"
                   + u"\n".join(u"  " + m for m in meas)
                   + u"\n\n注意：数据只说明尺寸，不说明姿态和形体；"
                     u"请以图像为准。若实测数据与图像明显矛盾，"
                     u"请在 defects 里写出来（这说明建模有问题）。"})
    return SYS, blocks


MODELS = (("ali", "qwen3.5-plus"), ("kimi", "kimi-k2.5"))


def ask_model(alias, model, sys_prompt, blocks):
    url, key, _ = ai_loop.load_provider(alias)
    c = ai_loop.make_client(url, key)
    return ai_loop.ask_retry(c, model, sys_prompt, blocks,
                             max_tokens=1800, tag=model)


RAW_DIR = r"J:\mickeylan\ai\blender\out\judge_raw"


def emit(txt, tag=None):
    out = txt if txt else "(失败)"
    if tag:
        os.makedirs(RAW_DIR, exist_ok=True)
        with open(os.path.join(RAW_DIR, "warrior_%s.txt" % tag), "w",
                  encoding="utf-8") as f:
            f.write(out)
    sys.stdout.buffer.write(out.encode("gbk", "replace") + b"\n")
    sys.stdout.flush()


def parse(txt):
    if not txt:
        return {}
    t = txt.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        t = t.rsplit("```", 1)[0]
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j < 0:
        return {}
    try:
        return json.loads(t[i:j + 1])
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=2)
    args = ap.parse_args()

    meas = measure()
    print(u"实测：")
    for m in meas:
        print(u"  " + m)
    sp, bl = build(meas)

    tally = {}
    for rnd in range(1, args.rounds + 1):
        for alias, model in MODELS:
            print(u"\n===== %s 第%d轮 =====" % (model, rnd))
            t = ask_model(alias, model, sp, bl)
            emit(t, tag="%s_r%d" % (model.replace(".", "_").replace("-", "_"), rnd))
            d = parse(t)
            for k in ("pose_reads_as_sword_strike", "ponytail_visible",
                      "sword_clearly_visible", "hourglass_readable",
                      "reads_as_beautiful_woman", "face_has_features"):
                tally.setdefault(k, []).append(d.get(k, "?"))
            for dfc in d.get("defects", []) or []:
                tally.setdefault("defect:" + dfc[:28], []).append(model)

    print(u"\n===== 汇总 =====")
    for k, vs in tally.items():
        if k.startswith("defect:"):
            print(u"  缺陷 %-30s 出现 %d 次" % (k[7:], len(vs)))
        else:
            print(u"  %-34s %s" % (k, " ".join(str(v) for v in vs)))


if __name__ == "__main__":
    main()
