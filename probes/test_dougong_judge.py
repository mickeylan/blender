"""让两个能看图的模型判定：渲染出的这朵斗拱像不像宋代五铺作斗拱？"""
import sys
sys.path.insert(0, r"J:\mickeylan\ai\blender")
import ai_loop

SYS = """你是中国古代建筑（营造法式）专家。
你会看到一组渲染图。请依据你对宋代木构的认知，判断图中构件的形制。

评判要点：
1. 能否看出层层出跳的十字栱？
2. 栱上是否能看到小斗块（散斗/交互斗）？
3. 是否有斜挑出的昂（斜杆）？
4. 顶部是否有横枋承檩？
5. 整体比例像不像宋代（出跳少、构件简洁、昂修长），
   而不是清代（层层叠密、装饰繁复）？

严格输出 JSON：
{
  "looks_like_dougong": "yes" | "no" | "unclear",
  "song_style": "yes" | "no" | "unclear",
  "visible_features": ["..."],
  "missing_features": ["..."],
  "problems": ["..."],
  "verdict": "一句话结论"
}
"""

blocks = []
for i, v in enumerate(["hero", "front", "right", "clay"], 1):
    blocks.append({"type": "text", "text": f"第 {i} 张: {v}"})
    blocks.append(ai_loop.img_block(rf"J:\mickeylan\ai\blender\out\dg_{v}.png"))
blocks.append({"type": "text", "text":
               "实测：斗口 0.100m，单朵斗拱 22 个构件，总高 1.23m。"
               "它坐落在直径 0.32m、高 1.30m 的柱头上。\n"
               "请只依据图像判断，看不清就写 unclear，不要猜。"})

for alias, model in (("ali", "qwen3.5-plus"), ("kimi", "kimi-k2.5")):
    url, key, _ = ai_loop.load_provider(alias)
    c = ai_loop.make_client(url, key)
    t = ai_loop.ask_retry(c, model, SYS, blocks, max_tokens=1600, tag=model)
    print(f"\n===== {model} =====")
    print(t if t else "(失败)")