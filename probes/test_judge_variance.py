"""量化视觉评审的**运行间方差**。

背景：同一批渲染图，重复评审得到的结论会变
（实测 qwen3.5-plus 在完全相同的图上给过 4/4 PASS，也给过 2/4 FAIL）。
渲染本身是像素确定的（PNG 里只有 Date/RenderTime 元数据在变），
所以差异来自模型端。

结论用法：单次判定不能当证据。要么多次取多数，要么用几何自检做硬证据。

用法:
    python probes/test_judge_variance.py --rounds 3
"""
import argparse
import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, r"J:\mickeylan\ai\blender")
import test_hongqiao_judge as J

FLAGS = ["is_guan_mu_gong", "no_pier_in_river", "weaving_visible",
         "arch_rise_visible"]
OUT = r'J:\mickeylan\ai\blender\out\judge_variance.json'


def parse(txt):
    """从评审输出里抠出 JSON（模型爱加 ``` 围栏和前言）。"""
    if not txt:
        return None
    m = re.search(r"```(?:json)?\s*\n(.*?)```", txt, re.S)
    body = m.group(1) if m else txt
    m2 = re.search(r"\{.*\}", body, re.S)
    if not m2:
        return None
    try:
        return json.loads(m2.group(0))
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=3)
    args = ap.parse_args()

    meas = J.measure()
    print("实测: " + " | ".join(meas))
    sp, bl = J.build(meas)

    tally = {}
    for alias, model in J.MODELS:
        c = Counter()
        rows = []
        for r in range(args.rounds):
            t = J.ask_model(alias, model, sp, bl)
            j = parse(t)
            if not j:
                c["解析失败"] += 1
                rows.append({"round": r + 1, "parsed": False})
                continue
            vals = [str(j.get(f, "?")).lower() for f in FLAGS]
            nyes = sum(1 for v in vals if v == "yes")
            c["%d/4" % nyes] += 1
            rows.append({"round": r + 1, "flags": dict(zip(FLAGS, vals)),
                         "n_yes": nyes,
                         "missing": len(j.get("missing_features") or []),
                         "problems": len(j.get("problems") or [])})
            print("  %s 第%d轮: %s  (missing=%d problems=%d)" % (
                model, r + 1, vals, len(j.get("missing_features") or []),
                len(j.get("problems") or [])))
        tally[model] = {"分布": dict(c), "逐轮": rows}

    print("\n===== 方差汇总 =====")
    for model, t in tally.items():
        print("%s: %s" % (model, t["分布"]))
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(tally, f, ensure_ascii=False, indent=2)
    print("已写入", OUT)


if __name__ == "__main__":
    main()
