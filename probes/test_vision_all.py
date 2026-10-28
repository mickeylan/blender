"""复核各模型的视觉能力 —— 决定独立评审该用哪个。"""
import sys
sys.path.insert(0, r"J:\mickeylan\ai\blender")
import ai_loop

IMG = r"J:\mickeylan\ai\blender\out\gate_hero.png"
blk = ai_loop.img_block(IMG)
print(f"图块 base64 长度 {len(blk['source']['data']):,}")

CASES = [
    ("ali", "qwen3.5-plus"),
    ("ali", "qwen3-max-2026-01-23"),
    ("ali", "glm-5"),
    ("ali", "kimi-k2.5"),
    ("ali", "qwen3-coder-plus"),
    ("minimax", "MiniMax-M2.5"),
]

for prov, model in CASES:
    try:
        url, key, _ = ai_loop.load_provider(prov)
        c = ai_loop.make_client(url, key)
        t = ai_loop.ask(c, model, "你是视觉评审。只回答一句。",
                        [blk, {"type": "text", "text":
                              "这张图里是什么建筑？说出你看到的主要构件。"}],
                        max_tokens=200)
        t = t.strip().replace("\n", " ")
        # 判定是否真看到图：必须提到建筑相关词
        kw = ["楼", "塔", "建筑", "屋", "柱", "门", "城", "台", "斗", "拱", "顶"]
        seen = any(k in t for k in kw)
        print(f"{prov}/{model:<26} {'看到图' if seen else '没看到图?':<10} {t[:80]!r}")
    except Exception as e:                                   # noqa: BLE001
        print(f"{prov}/{model:<26} FAIL {type(e).__name__}: {str(e)[:100]}")