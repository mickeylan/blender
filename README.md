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
| 驱动模型 | `qwen3.5-plus`（视觉 ✅）／`kimi-k2.5`（视觉 ✅）／`MiniMax-M2.5`、`glm-5`（**不能看图**） |

> 能看图的只有 `qwen3.5-plus` 和 `kimi-k2.5`（见 LESSONS [040]）。独立评审只能在这两者之间交叉。

---

## 快速开始

```powershell
# 1) 启动 Blender 并自动开启 MCP（必须有 GUI，后台模式插件不工作）
Start-Process 'D:\Program Files\Blender Foundation\Blender 5.2\blender.exe' `
  -ArgumentList '--python','J:\mickeylan\ai\blender\launch_mcp.py'

# 2) 自检（7 项）
D:\python3\python.exe selftest.py

# 3) 跑闭环（建模与评审同模型 = 自检，分数会虚高约 2.3 分）
D:\python3\python.exe ai_loop.py `
  --goal "搭一座中式城楼，基座宽8m深4m高3m，两层楼阁每层2.5m，反曲屋顶带起翘檐角" `
  --rounds 4 --provider ali

# 4) 跑闭环（独立交叉评审，推荐）
D:\python3\python.exe ai_loop.py --goal "..." --rounds 4 `
  --provider ali --model qwen3.5-plus `
  --critic-provider kimi --critic-model kimi-k2.5
```

产出在 `out/`：每轮 5 个证据通道 `roundN_{hero,front,right,back,clay}.png`、
`roundN_build.py`、`best_verdict.json`。

---

## 文件

| 文件 | 作用 |
|---|---|
| `blender_client.py` | 最小 socket 客户端，不依赖 MCP 框架，任何语言/进程可用 |
| `ai_loop.py` | 闭环驱动：建模提示词 + 安全助手库 + 强制取景 + 视觉批评家 |
| `launch_mcp.py` | 启动 GUI Blender 并自动启用插件、等端口就绪 |
| `camera_auto.py` | 按包围盒自动取景（可单独用） |
| `selftest.py` | 端到端自检 7 项 |
| `view.py` | 把渲染图降采样成终端字符图，无法直接看图时的自查手段 |
| `build_gate.py` | 手写基准样例：中式城楼（51 构件 / 13592 顶点 / 基座精确 8×4×3m） |
| `task_dougong.py` | 手写基准样例：13 构件斗拱，用来标定助手库正确性 |
| `probes/` | 40+ 个探针脚本：5.2 API、色彩管理、几何自检、相机锁定、交叉评审的验证留档 |
| `LESSONS.md` | **踩坑记录，42 条，建议先读这个** |

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
④ 五通道证据渲染：hero / front / right / back 正交 / clay 灰模
   首轮自动取景后**锁定相机**，后续轮原样复用（保证跨轮可比）
   ↓
⑤ 视觉模型按 rubric 打分，输出 checks[]（pass/fail/unclear）
   + dim_check[]（目标 vs 实测）+ invariants[]（下轮必须保持的）
   ↓  total ≥ 8 且无 fail → 停；连续两轮不升 → 换路线
⑥ 把评审意见 + invariants 回灌，回到 ①
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

同一目标（中式城楼）、同一模型（qwen3.5-plus 建模）：

| 阶段 | 得分 | 说明 |
|---|---|---|
| 裸 API 提示词 | **3.5** | 3 轮里 2 轮在修 API 拼写 |
| 助手库（无容错） | 失败 | 3 轮全挂于调用姿势 |
| 助手库 + 容错 | **5.5** | 59 构件 / 872 顶点 |
| 形制助手 + 五通道证据 | **6.0** | 59→76 构件，但一轮回归把分拉低 |
| 修正缺陷 + 交叉评审 | **7.0–7.3** | 51 构件 / 13592 顶点，基座精确 8×4×3m |

**自检与独立评审的差距（同一组图）**：

| 版本 | qwen3.5-plus（建模者自检） | kimi-k2.5（独立） | Δ |
|---|---|---|---|
| 有真实缺陷时 | 8.8 | 6.5 | **−2.3** |
| 修正后 | 7.3 | 7.0 | −0.3 |

→ **分歧大往往意味着真有缺陷**，这让"交叉评审分歧"本身成为可用的缺陷探针。

端到端一轮约 2.5 分钟，**瓶颈在模型生成代码（100–200 s）**，不在 Blender（执行 1–3 s、渲染 2–4 s × 5 通道）。

---

## 已知限制

- **视口截图不可用**：`get_viewport_screenshot` 在无人值守时拍到的是空视口（均匀灰底）。自查必须用 `bpy.ops.render.render`。
- **只有两个模型能看图**：`qwen3.5-plus` 与 `kimi-k2.5`。`glm-5` / `MiniMax-M2.5` 会回复"没有上传图片"，绝不能当评审。
- **屋面曲率视觉可读性不足**：反宇几何成立（坡度变化 40 倍），但在 720px、3/4 俯视下读不出来，两个评审一致反馈"像平直斜面"。见 LESSONS [042]。
- **固定机位会裁切**：跨轮锁定相机保证可比，但模型变大时边缘被裁。harness 会报 `FRAME_OVERFLOW` 并告知评审，不会悄悄重框。
- **每轮重写整份脚本**：还没有增量修改机制，改一处要重跑全部。
- **批评家也可能错**：它的每条指控都要落到可测量的几何量上再决定改不改。见 LESSONS [041]。

---

## 下一步方向

1. **屋面曲率可读性**：加陡举高、加瓦垄几何、或专出一张屋面剖面证据图
2. 增量修改：只重建指定构件，而不是每轮重写整份脚本
3. 构件模板库：斗拱参数化助手 `dougong()`，减少模型自由发挥
4. 快照/回滚：模型改坏场景后如何恢复（`bpy.data` 序列化 / .blend 版本）
5. 三模型投票：`qwen3.5-plus` + `kimi-k2.5` 独立打分取中位数，减少单点评审偏差