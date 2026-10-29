"""让两个能看图的模型按《清明上河图》虹桥的形象判定贯木拱桥。

**实测数据全部从当前场景实时量取**，不写死 ——
写死旧数字会污染评估：评审会复述我的数字而不是读图
（实测踩过：kimi 的 visible_features 在背上一版的"3.27m/3.54m/0.30m"）。

**评审提示词里的形制描述必须来自权威来源**，不能凭印象：
本文件按唐寰澄 1953 年的认定 + 百科"虹桥"条 + 福建屏南万安桥
（"活态虹桥"）写：两组拱骨系统 —— 下层**三节苗**（3 段）、
上层**五节苗**（5 段），纵向错位、穿插别压。
（早前把两套都写成"三节苗"，评审就找不到该看的差别。）

另：同一批图重复评审，结论有**运行间方差**（实测 4/4 与 2/4 都出现过），
单次判定不能当证据 —— 见 probes/test_judge_variance.py。
"""
import sys

sys.path.insert(0, r"J:\mickeylan\ai\blender")
import ai_loop

VIEWS = ["hero", "front", "right", "back", "under", "detail", "clay"]

SYS = """你是研究北宋《清明上河图》（张择端）的建筑史专家。
你会看到一座木桥的一组渲染图。请判断它是否具备**贯木拱（编木拱 / 叠梁拱）虹桥**的特征。

《清明上河图》中虹桥的真实形制（按唐寰澄 1953 年的首次科学认定，
以及福建屏南万安桥、浙江云和梅崇桥等"活态虹桥"的实物结构）：

1. **无河中桥墩** —— 靠木构本身跨越全河，桥下全空
2. **主体由两套拱骨系统交错搭置**：
   - 下层一级受力系统 = **三节苗**：3 段圆木首尾相接成折线
   - 上层二级受力系统 = **五节苗**：5 段圆木，与三节苗**纵向错位**，
     在桥跨中段**穿插别压** —— 一套压住另一套，
     靠木料互相咬合承重，**无榫无钉**
   - 两套系统的节点位置要**错开**，不是重合
   - 节点处要有明显的**接头**（加粗的"牛头"和麻绳箍），
     不能看成一根连续的长弧木
3. **横向苗**：横向圆木把纵向拱骨别住；苗**斜跨**桥面，
   在每个纵梁处**交替压上 / 钻下**，跨中要能看到明显的菱形网格
4. **横梁贯穿**把两套系统联合成整体
5. 桥面宽而平，**中部微隆起拱**，两端接岸；拱背与桥面之间有撑木
6. 两侧有木栏杆

严格输出 JSON：
{
  "is_guan_mu_gong": "yes" | "no" | "unclear",
  "no_pier_in_river": "yes" | "no" | "unclear",
  "weaving_visible": "yes" | "no" | "unclear",
  "arch_rise_visible": "yes" | "no" | "unclear",
  "visible_features": ["..."],
  "missing_features": ["..."],
  "problems": ["..."],
  "verdict": "一句话结论"
}
"""

_PROBE = '''
import bpy
from mathutils import Vector as V
bpy.context.view_layer.update()
def zs(pref):
    out = []
    for o in bpy.data.objects:
        if o.name.startswith(pref):
            for c in o.bound_box:
                out.append((o.matrix_world @ V(c)).z)
    return out
def ys(pref):
    out = []
    for o in bpy.data.objects:
        if o.name.startswith(pref):
            for c in o.bound_box:
                out.append((o.matrix_world @ V(c)).y)
    return out
deck = zs('HQ_Plank')
ribA = zs('HQ_R0A_S'); ribB = zs('HQ_R0B_S')
ya = ys('HQ_R0A_S'); yb = ys('HQ_R0B_S')
mid = []
for o in bpy.data.objects:
    if o.type == 'MESH':
        for c in o.bound_box:
            p = o.matrix_world @ V(c)
            if abs(p.x) < 10.0 * 0.42:
                mid.append(p.z)
print('MEAS deck_z=%.2f..%.2f' % (min(deck), max(deck)))
print('MEAS A_z=%.2f..%.2f' % (min(ribA), max(ribA)))
print('MEAS B_z=%.2f..%.2f' % (min(ribB), max(ribB)))
print('MEAS A_y=%.2f..%.2f' % (min(ya), max(ya)))
print('MEAS B_y=%.2f..%.2f' % (min(yb), max(yb)))
print('MEAS mid_min_z=%.2f' % min(mid))
print('MEAS nmesh=%d' % sum(1 for o in bpy.data.objects if o.type=='MESH'))
'''


def measure():
    """从当前 Blender 场景实时量取，返回字符串列表。"""
    s = ai_loop.Session()
    s.connect()
    r = s.c.execute_code(_PROBE)
    out = str(r.get("result", {}).get("result", ""))
    return [ln.split("MEAS ", 1)[1].strip()
            for ln in out.splitlines() if "MEAS " in ln]


def build(meas=None):
    """构造 (system_prompt, user_blocks)。"""
    if meas is None:
        meas = measure()
    blocks = []
    for i, v in enumerate(VIEWS, 1):
        blocks.append({"type": "text", "text": "第 %d 张: %s" % (i, v)})
        blocks.append(ai_loop.img_block(
            rf"J:\mickeylan\ai\blender\out\hq_{v}.png"))
    blocks.append({"type": "text", "text":
                   "以下是**从当前场景实测**得到的数据（供你核对，不要当成结论）：\n"
                   + "\n".join("  " + m for m in meas) + "\n\n"
                   "请**依据图像**判断形制，看不清就写 unclear，不要猜。"
                   "特别注意：判断'编织'是否可见，要看两套拱肋在桥跨中段是否呈 X 形交叉、"
                   "且有一根明显压在另一根之上。"})
    return SYS, blocks


MODELS = (("ali", "qwen3.5-plus"), ("kimi", "kimi-k2.5"))


def ask_model(alias, model, sys_prompt, blocks):
    url, key, _ = ai_loop.load_provider(alias)
    c = ai_loop.make_client(url, key)
    return ai_loop.ask_retry(c, model, sys_prompt, blocks,
                             max_tokens=1600, tag=model)


def emit(txt):
    """GBK 安全的输出（评审结果带 ✓ 会抛 UnicodeEncodeError）。"""
    out = txt if txt else "(失败)"
    sys.stdout.buffer.write(out.encode("gbk", "replace") + b"\n")
    sys.stdout.flush()


if __name__ == "__main__":
    meas = measure()
    print("实测:")
    for m in meas:
        print("  " + m)
    sp, bl = build(meas)
    print()
    for alias, model in MODELS:
        t = ask_model(alias, model, sp, bl)
        print("\n===== %s =====" % model)
        emit(t)
