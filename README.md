# AI 指挥 Blender 建模 —— 探索与工具

用 AI（视觉/3D 理解强的大模型）驱动 Blender 建白模，走「生成代码 → 执行 → 渲染 → 批评 → 修正」的闭环。
方法论取自 [dream-loop](https://github.com/achimala/dream-loop)，工具链基于 [mcp-for-blender](https://github.com/ahujasid/mcp-for-blender)。

**所有结论都经过实测**，踩过的坑逐条记在 [LESSONS.md](LESSONS.md)（24 条，含证据）。

---

## 环境

| 项 | 值 |
|---|---|
| Blender | 5.2.3 LTS（另有 5.1） |
| MCP 插件 | `mcp-for-blender` v1.8，装在 `%APPDATA%\Blender Foundation\Blender\5.2\scripts\addons\blender_mcp.py` |
| 通道 | `127.0.0.1:9876`，JSON over TCP（无分隔符、无长度前缀） |
| Python | `D:\python3\python.exe`（有 PIL / numpy） |
| 驱动模型 | `qwen3.5-plus`（视觉可用）／`MiniMax-M2.5`（仅文本） |

---

## 快速开始

```powershell
# 1) 启动 Blender 并自动开启 MCP（必须有 GUI，后台模式插件不工作）
Start-Process 'D:\Program Files\Blender Foundation\Blender 5.2\blender.exe' `
  -ArgumentList '--python','J:\mickeylan\ai\blender\launch_mcp.py'

# 2) 自检（7 项）
D:\python3\python.exe selftest.py

# 3) 跑闭环
D:\python3\python.exe ai_loop.py `
  --goal "搭一座中式城楼，基座宽8m深4m高3m，两层楼阁每层2.5m，反曲屋顶带起翘檐角" `
  --rounds 4 --provider ali
```

产出在 `out/`：`roundN.png`（各轮渲染）、`roundN_build.py`（模型写的代码）、`best_verdict.json`（最佳评审）。

---

## 文件

| 文件 | 作用 |
|---|---|
| `blender_client.py` | 最小 socket 客户端，不依赖 MCP 框架，任何语言/进程可用 |
| `ai_loop.py` | 闭环驱动：建模提示词 + 安全助手库 + 强制取景 + 视觉批评家 |
| `launch_mcp.py` | 启动 GUI Blender 并自动启用插件、等端口就绪 |
| `camera_auto.py` | 按包围盒自动取景（可单独用） |
| `selftest.py` | 端到端自检 7 项 |
| `task_dougong.py` | 手写基准样例：13 构件斗拱，用来标定助手库正确性 |
| `probes/` | 20 个探针脚本，5.2 API 与色彩管理的验证证据 |
| `LESSONS.md` | **踩坑记录，24 条，建议先读这个** |

---

## 闭环结构

```
目标描述
   ↓
① 模型生成 Blender Python（只能调助手库，不许碰 bpy.ops）
   ↓
② 注入 __name__ + 助手库 → MCP execute_code
   ↓  ← 失败则把带行号的 traceback 回传，模型自修
③ 后置校验：场景里必须真有 MESH，否则当失败
   ↓
④ 强制取景（排除地面/背景板）+ EEVEE 渲染
   ↓
⑤ 视觉模型按 rubric 打分（结构/构图/材质/细节，满分 10）
   ↓  total ≥ 8 或 verdict=keep → 停
⑥ 把评审意见回灌，回到 ①
```

---

## 三条设计原则（都是被坑出来的）

**1. 取景是工程约束，不是创作决定。**
模型给的相机经常框不住模型（残留上一轮的、或对着 8 米建筑用 0.3 米的机位）。
harness 在渲染前按包围盒强制重设相机，并剔除地面/背景板（否则包围盒被撑爆，相机被推到 100 米外）。

**2. 让模型在「构件语义层」工作，不要在「API 语法层」工作。**
实测发现多轮迭代中大部分轮次花在修 `create_cube(size=tuple)`、颜色 5 元组、`.base_color` 不存在这类拼写错误。
注入助手库后：`box()` / `cyl()` / `prism()` / `beam()` / `mat()` / `setup()` / `stats()`。

**3. 助手层必须容错，因为 LLM 会「大概地」调 API。**
`rot=None` 占位、角度当弧度传、材质挤进数字位、`samples` 塞进 `res` 位 —— 全部在适配层吸收掉。
验证：容错层单测照抄模型真实写法，`ROT 1.5708 EXPECT 1.5708` 通过。

---

## 实测成绩

同一目标（中式城楼）、同一模型（qwen3.5-plus）：

| 阶段 | 得分 | 说明 |
|---|---|---|
| 裸 API 提示词 | **3.5** | 3 轮里 2 轮在修 API 拼写 |
| 助手库（无容错） | 失败 | 3 轮全挂于调用姿势 |
| 助手库 + 容错 | **5.5** | 59 构件 / 872 顶点 |

端到端一轮约 2.5 分钟，**瓶颈在模型生成代码（100–200 s）**，不在 Blender（执行 1–3 s、渲染 2–4 s）。

---

## 已知限制

- **视口截图不可用**：`get_viewport_screenshot` 在无人值守时拍到的是空视口（均匀灰底）。自查必须用 `bpy.ops.render.render`。
- **本会话视觉被套餐限制**：批评家必须由独立脚本调 API，不能靠当前会话「看图」。
- **批评家只能看单视图**：判断不了三维结构错误（例如构件在背面缺失）。需要多角度渲染。
- **形制类难点仍弱**：反曲屋顶、起翘檐角这类，模型倾向做成平板。建议在助手库里补 `curved_roof()`。
- **每轮重写整份脚本**：还没有增量修改机制，改一处要重跑全部。

---

## 下一步方向

1. `curved_roof()` 等形制助手，把"难描述的形状"变成参数
2. 多角度渲染（顶视/侧视/前视）供批评家判断三维结构
3. 增量修改：只重建指定构件
4. 构件模板库：斗拱/柱/栏/屋顶 参数化，减少模型自由发挥
5. 多模型对比：qwen3-max / glm-5 / kimi-k2.5 在同一目标下的建模质量
6. 快照/回滚：模型改坏场景后如何恢复