import os
import sys

sys.path.insert(0, r'J:\mickeylan\ai\blender')
sys.path.insert(0, r'J:\mickeylan\ai\blender\probes')
import test_hongqiao_judge as J

OUTDIR = r'J:\mickeylan\ai\blender\out\judge_raw'
os.makedirs(OUTDIR, exist_ok=True)

want = sys.argv[1] if len(sys.argv) > 1 else ""
n = int(sys.argv[2]) if len(sys.argv) > 2 else 1
meas = J.measure()
sp, bl = J.build(meas)
for alias, model in J.MODELS:
    if want and want not in model:
        continue
    for i in range(n):
        t = J.ask_model(alias, model, sp, bl)
        p = os.path.join(OUTDIR, "%s_r%d.txt" % (model.replace('.', '_'), i + 1))
        with open(p, "w", encoding="utf-8") as f:
            f.write(t or "(失败)")
        print("已保存", p)
