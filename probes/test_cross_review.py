"""交叉评审实测：同一组证据图，两个不同模型独立打分，量化自检偏差。

用法: python probes/test_cross_review.py [图前缀]   # 默认 gate
"""
import json
import re
import sys

sys.path.insert(0, r"J:\mickeylan\ai\blender")
import ai_loop

prefix = sys.argv[1] if len(sys.argv) > 1 else "gate"
views = ["hero", "front", "right", "back", "clay"]

# 现场量取分构件族尺寸（不硬编码）
_s = ai_loop.Session()
_s.connect()
FAM_TXT = _s.component_dims_str()
print("构件族实测：\n" + FAM_TXT + "\n")
labels = {
    "hero": "hero（透视，带材质）",
    "front": "正视图（正交，-Y）",
    "right": "右侧视图（正交，+X）",
    "back": "背视图（正交，+Y）",
    "clay": "灰模（Workbench，只看形体）",
}

blocks = []
for i, v in enumerate(views, 1):
    p = rf"J:\mickeylan\ai\blender\out\{prefix}_{v}.png"
    blocks.append({"type": "text", "text": f"第 {i} 张：{labels[v]}"})
    blocks.append(ai_loop.img_block(p))
blocks.append({"type": "text", "text":
               "建模目标：搭一座简化的中式城楼：底部矩形城墙基座带一个拱形门洞"
               "（基座宽8m深4m高3m），其上两层楼阁（每层高2.5m），每层有柱子和栏杆，"
               "两层都用反曲屋顶并带起翘檐角，屋面要有瓦垄。不要加地面。\n\n"
               "实测数据：构件数 51，整体包围盒 宽 8.96m × 深 5.26m × 高 9.80m。\n"
               "分构件族实测尺寸（每个族各自量取）：\n"
               + FAM_TXT +
               "\n取景提示：本轮与基准机位一致，视图无裁切。\n\n"
               "注意 1：第 5 张是灰模，只反映**形体**；灰模对而彩色图不对是材质/光照问题。\n"
               "注意 2：核对尺寸时**必须用分族实测值**，不要用整体包围盒去套某个构件。\n"
               "       例如「基座宽8深4」要对比基座那一族；整体包围盒含屋檐出挑，比基座大是正常的。\n"
               "注意 3：看不清的项请写 unclear 并说明原因，**不要猜**。"})

results = {}
for alias, model in (("ali", "qwen3.5-plus"), ("kimi", "kimi-k2.5")):
    url, key, _ = ai_loop.load_provider(alias)
    c = ai_loop.make_client(url, key)
    try:
        txt = ai_loop.ask_retry(c, model, ai_loop.CRITIC_SYSTEM, blocks,
                                max_tokens=3072, tag=model)
    except Exception as e:                                    # noqa: BLE001
        print(f"{model}: FAIL {type(e).__name__} {str(e)[:120]}")
        continue
    if txt is None:
        print(f"{model}: 重试耗尽")
        continue
    try:
        m = re.search(r"\{.*\}", txt, re.S)
        v = json.loads(m.group(0)) if m else {}
    except Exception:                                         # noqa: BLE001
        v = {}
    results[model] = v
    print(f"\n=== {model} ===")
    if not v:
        print("  解析失败，原文:", txt[:300])
        continue
    for k in ("structure", "composition", "materials", "details", "total"):
        print(f"  {k:<12} {v.get(k)}")
    for c_ in (v.get("checks") or [])[:8]:
        if isinstance(c_, dict):
            print(f"  [{str(c_.get('result','?')).upper():<7}] {c_.get('item','')}")
    for it in (v.get("top_issues") or [])[:4]:
        print(f"  ! {it}")

if len(results) == 2:
    a, b = results["qwen3.5-plus"], results["kimi-k2.5"]
    print("\n=== 分歧 ===")
    for k in ("structure", "composition", "materials", "details", "total"):
        va, vb = a.get(k) or 0, b.get(k) or 0
        flag = "  <-- 分歧大" if abs(va - vb) >= 1.0 else ""
        print(f"  {k:<12} qwen={va}  kimi={vb}  Δ={vb-va:+.1f}{flag}")
    print(f"  total 均值 {( (a.get('total') or 0) + (b.get('total') or 0) )/2:.2f}")