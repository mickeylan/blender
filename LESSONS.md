# AI 指挥 Blender 建模 —— 踩坑与经验记录

> 本文件是**活文档**：每验证一个新坑就追加一条。
> 格式：`## [编号] 标题` + 现象 / 原因 / 处理 + 证据。
> 编号只增不改，便于回查。

环境基线（2026-10-28 实测）：
- Blender **5.2.3 LTS**（build 2026-10-22），同时装有 5.1
- MCP 插件 `mcp-for-blender` v1.8（PyPI 包名已从 `blender-mcp` 改名）
- addon 路径：`%APPDATA%\Blender Foundation\Blender\5.2\scripts\addons\blender_mcp.py`
- socket：`127.0.0.1:9876`，协议为 **JSON over TCP，无分隔符无长度前缀**
- 驱动端客户端：`J:\mickeylan\ai\blender\blender_client.py`

---

## [001] 插件在 `--background` 模式无法启动 socket 服务

**现象**：`blender.exe --background --python ...` 里 `addon_utils.enable("blender_mcp")` 返回成功，但 9876 端口始终不开。

**原因**：addon 源码明确守卫——
```python
# blender_mcp.py:1302-1303
if bpy.app.background:
    print("BlenderMCP: cannot start server in background mode (blender -b) - commands would never execute")
```
插件靠 `bpy.app.timers` 在**主线程**泵命令队列；后台模式没有事件循环，命令永远不会被执行。

**处理**：必须用 **GUI 模式**启动 Blender（`blender.exe --python launch_mcp.py`），并确保它有窗口/桌面会话。

**推论**：凡是需要 MCP 驱动的 Blender 实例，都不能省掉 GUI。这也是为什么 dream-loop 这类方案都需要一个可见的 Blender。

---

## [002] `bpy.ops.wm.read_factory_settings()` 会连带杀死 MCP 通道

**现象**：AI 生成的建模脚本第一行习惯性写 `bpy.ops.wm.read_factory_settings(use_empty=True)` 来清场。执行后：
- **Blender 进程仍然活着**（内存正常、未崩溃、无 `blender.crash.txt`）
- 但 **9876 端口不再监听**，后续所有命令都收不到回包，客户端表现为 `TimeoutError: 已收到 0 字节`

**原因**：`read_factory_settings` 会重置整个 Blender 状态，插件的 socket 服务线程随之被销毁。**进程活着 ≠ 通道活着** —— 这点容易误判成"Blender 崩了"。

**处理**：改用手动清场，保留插件与 UI 状态：
```python
for ob in list(bpy.data.objects):
    bpy.data.objects.remove(ob, do_unlink=True)
for c in list(bpy.data.collections):
    bpy.data.collections.remove(c)
for blk in (bpy.data.meshes, bpy.data.materials, bpy.data.cameras, bpy.data.lights):
    for d in list(blk):
        if d.users == 0:
            blk.remove(d)
```

**纪律**：给 AI 的建模脚本模板里**禁止出现 `read_factory_settings`**。更稳妥的做法是在插件外部准备好干净 .blend，AI 只做增量修改。

---

## [003] 误判「进程死了」—— 先区分进程与通道

**现象**：端口拒连后，我断言"Blender 进程死了"，实际进程一直在（456 MB）。

**原因**：把**通道故障**误当成**进程故障**。二者要分开查：
```powershell
Get-Process -Name blender | ForEach-Object { "pid=$($_.Id) mem=$([math]::Round($_.WorkingSet64/1MB))MB" }
Test-Path "$env:APPDATA\Blender Foundation\Blender\5.2\config\blender.crash.txt"
```
无 crash 文件 + 进程有内存 = 进程活着，问题在通道。

**纪律**：报告状态前先取证，别用"应该死了"这类推断代替实际检查。

---

## [004] socket 回包无分隔符，客户端必须自行累积缓冲

**现象**：客户端用 `recv` 一次就 `json.loads`，遇到分片就失败。

**原因**：addon 侧是裸 `client.sendall(response_json.encode('utf-8'))` —— **没有换行、没有长度前缀**。大响应（如 `get_scene_info`）必然分片。

**处理**：累积 buffer 后**反复尝试整块 `json.loads`**，失败再退化到按行切。已固化在 `blender_client.py` 的 `_send()`。

---

## [005] 命令名要对齐 addon 的 `handlers` 字典

**现象**：我凭直觉写的 `get_addon_status` 无效。

**原因**：addon 的真实命令名定义在 `blender_mcp.py:1537-1559` 的 `handlers` 字典里：
`get_scene_info` / `get_world_state_snapshot` / `get_addon_info` / `get_object_info` /
`list_scene_items` / `get_viewport_screenshot` / `pick_viewport_object` / `execute_code` /
`describe_node_type` / `bpy_api_lookup` / `drain_human_activity` /
`get_addon_status`→ 实为 **`get_addon_info`** / `export_scene` 等，
另有 PolyHaven / Hunyuan3D / Meshy / Tripo / Sketchfab / PolyPizza / Hyper3D 系列（按开关启用）。

**处理**：不要猜命令名。先 `ping` 再 `get_addon_info` 确认，`get_addon_info` 的 `capabilities` 列表就是可用命令的权威清单。

**额外收获**：发现两个对 AI 极有用的自省工具 ——
- **`bpy_api_lookup`**：让模型结构化查询 Blender API，不必靠记忆
- **`describe_node_type`**：描述某个节点类型的属性名/类型/枚举/插槽顺序
两者都是"一次调用给出答案"，比让模型反复试错 `execute_code` 高效得多。**应优先引导 AI 用它们。**

---

## [006] 材质节点名在 5.2 变了，`nodes.get("Principled BSDF")` 返回 None

**现象**：`AttributeError: 'NoneType' object has no attribute 'inputs'`（在 `make_material` 里）。

**原因**：按名字取节点在版本间不可靠。5.2 里该节点的 `.name` 与旧的显示名不一致。

**处理**：**按类型取，不按名字取**：
```python
bsdf = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
```
同理 World 的环境光节点用 `n.type == 'BACKGROUND'`。

**纪律**：写 Blender Python 时，凡是用 `.nodes.get("...")` / `bpy.data.node_groups["..."]` 这类按名索引，都要准备退路为按 `type` 查找。

---

## [007] 插件的报错会带完整 traceback 和行号 —— 这是核心价值

**现象**：脚本抛异常时，响应为
```json
{"status":"error","message":"{\"exception_type\":\"AttributeError\",\"message\":\"...\",\"traceback\":\"... File \\\"<string>\\\", line 74, in <module> ...\"}"}
```

**原因**：addon 的 `execute_code` 捕获异常后把 `exception_type` / `message` / **带行号的 traceback** 一起打包回传（源码注释明确说这是为了让多行脚本的调用方能定位到失败行）。

**处理**：客户端要**解析嵌套 JSON**（`message` 是 JSON 字符串），把 traceback 直接呈现给 AI。

**意义**：这是"AI 写代码 → 精确报错 → AI 自己改"的闭环基础。整条链路的可靠性依赖于此，务必不要在客户端吞掉 traceback。

---

## [008] `get_viewport_screenshot` 用 GPUOffScreen，不依赖窗口是否前台

**源码注释要点**（`blender_mcp.py:2126-2133`）：
> `screen.screenshot_area` 抓的是 OS 窗口帧缓冲，Blender 窗口不在前台时就是全黑（这正是 MCP 以 headless 方式驱动 Blender 时的常态）。因此改用 `gpu.types.GPUOffScreen.draw_view3d` 渲染视口，与窗口合成状态无关；只有在无 GPU 上下文时才回退到窗口抓取。

**推论**：截图通道在"AI 驱动、Blender 无人值守"场景下是可靠的 —— 这正是 dream-loop 循环里"AI 自查"那一环的地基。

---

## [009] 已知但尚未处理的 5.2 API 变更（来自控制图导出研究）

同一台 Blender 5.2 上验证过的变更，写 Blender 插件/脚本时一并适用：

| 旧写法 | 5.2 正确写法 |
|---|---|
| `scene.node_tree` | `scene.compositing_node_group`（CompositorNodeTree） |
| `OutputFile.base_path` | `fo.directory` / `fo.file_name` |
| `file_output_items` 初始为空 | `items.new(socket_type, name)` —— **签名是 (socket_type, name)**，不是反过来 |
| `fo.format.file_format = "OPEN_EXR"` | 每 item 单独设 `it.format.file_format = "OPEN_EXR"` |
| `BLENDER_EEVEE_NEXT` | 5.2 回到 `BLENDER_EEVEE` |
| `view_settings.use_curve` | 直接改 `view_transform` / `look` |

另：`use_pass_*` 必须在**创建 Render Layers 节点之前**打开，否则插槽不出现。

---

## [010] 控制图导出：Raw 色彩管理是必须的

**结论**（Blender 5.2.3 实测）：

| 项 | 做法 | 实测误差 |
|---|---|---|
| depth | `Camera Data → View Z Depth → MapRange(near→1, far→0)` | EXR **0.00022**；PNG+sRGB解码 0.0015 |
| normal | `Geometry.Normal → VectorTransform(WORLD→CAMERA) → **Z 取反** → ×0.5+0.5` | 竖直面编码 (0.497,0.479,1.000) ✓ |
| 色彩管理 | **必须 `view_transform = "Raw"`** | Raw 字节=线性值(0.247/0.749 vs 设计 0.25/0.75) ✓ |
| | AgX 禁用 | AgX 深度误差 **0.13~0.36** |

**两个被实测推翻的假设**：
1. "AgX 是元凶" —— 错，真凶是 **sRGB 编码**；AgX 只是叠加了额外非线性。`Raw` 一步解决。
2. "材质输出与 Blender 相机空间一致" —— 错，**Z 相反**。Blender 相机看向自身 −Z，正对相机的面在相机空间法线是 −Z，而 ControlNet 约定要 +Z。

**易错点**：算法线真值时**只能用旋转部分**：`cam.matrix_world.inverted().to_3x3() @ v`。
直接用 `M @ v`（4×4 矩阵）会把**平移量**也加进去，真值全错 —— 我踩过这个坑。

---

## [011] 视口截图 `get_viewport_screenshot` 在本机拍到的是空视口，不能用

**现象**：对着一座有 13 个构件的斗拱模型拍视口，得到的 `shot_camera.png`：
- 尺寸 1200×686，**全图几乎均匀灰色**（角落像素 `[76,76,76]`、中心 `[112,113,113]`）
- 亮度剖面（每 10% 一档，从上到下）：`[65.5, 66.3, 65.9, 65.2, 64.6, 64.4, 64.1, 63.9, 63.8, 63.7]` —— **平的，无任何结构**

对比真实渲染 `render_cam.png`：木色行密度 `[7,19,53,12,6,78,139,80,6,0]`，两个明显峰值。

**原因**：addon's `get_viewport_screenshot` 走 `gpu.types.GPUOffScreen.draw_view3d`（源码注释说这是为了不依赖窗口前台），但**在无人值守/非前台状态下拿到的是视口背景而非场景内容**。它返回 `"method":"offscreen"`，并附带了 `view_matrix`，说明它确实渲染了 —— 只是渲染出来的是空视口。

**附坑**：`view` 参数无效 —— `shot_camera.png` 与 `shot_persp.png` **字节大小完全相同**（均 300,983 B），两张是同一张。所以不能靠 `view="camera"`/`"persp"` 区分机位。

**处理**：**自查一律用真实渲染**，不走视口截图：
```python
bpy.context.scene.render.filepath = r"...\shot.png"
bpy.ops.render.render(write_still=True)
```
渲染耗时可接受（本例 1200×900 EEVEE 约 1–2 s），且结果是权威的。

**推论**：dream-loop 循环里的"AI 看自己作品"这一步，**必须落到 `bpy.ops.render.render`**，不能用 addon 的视口截图工具。

---

## [012] 视口截图无效 → 自查环节必须由独立脚本调视觉 API

**现象**：想在当前会话里用内置视觉看渲染结果，工具返回
```
provider error 405: {"error": "Coding Plan is currently only available for Coding Agents"}
```

**原因**：本会话的视觉能力受套餐限制，不是技术问题。

**处理**：dream-loop 的"批评家"环节**必须是一个独立进程**去调视觉 API（例如把渲染图 base64 后发给支持视觉的模型），而不是依赖当前交互会话的眼睛。

**可用端点**（用户本机已配置好，Anthropic 协议）：
| provider | baseURL | 可用模型 |
|---|---|---|
| `minimax-mickeylan` | `https://api.minimaxi.com/anthropic/v1` | MiniMax-M2.5 / M2.7 |
| `ali-coding-plan` | `https://coding.dashscope.aliyuncs.com/apps/anthropic/v1` | qwen3.5-plus、qwen3-max-2026-01-23、qwen3-coder-next/plus、glm-5、glm-4.7、kimi-k2.5 |

两者都兼容 Anthropic Messages API，接 MCP 客户端时最省事。

---

## [013] 程序化图像分析可以替代人眼做第一道筛查

**现象**：无法直接看图时，用 PIL/numpy 分析渲染图。

**手段**：按颜色分割出目标材质像素 → 统计**逐行像素密度** → 得到剖面。

**结果**（斗拱模型）：木色行密度 `[7,19,53,12,6,78,139,80,6,0]`
- 峰值 53 与 139 对应"下部坐斗群"与"上部华栱叠涩"两段式层叠 —— 结构符合斗栱形制
- 但木色像素 `y` 起点 = 0 → **模型顶部被画面裁掉**，相机没框住

**价值**：这类"构图/裁切/比例"问题用数值就能查，不必等模型看图。适合作为 dream-loop 循环的**前置自动检查**，把明显问题挡在调用视觉 API 之前。

---

## [014] Anthropic SDK 的 base_url 会重复拼 `/v1` → 404

**现象**：直接拿 opencode 配置里的 `baseURL` 建客户端，两个端点都 404：
```
ali/qwen3.5-plus:     NotFoundError: Error code: 404
minimax/MiniMax-M2.5: NotFoundError: 404 page not found
```

**原因**：`anthropic` SDK 会在 `base_url` 后**自动追加 `/v1/messages`**；而 opencode 配置里的值已带 `/v1`（`https://coding.dashscope.aliyuncs.com/apps/anthropic/v1`），拼出来是 `/v1/v1/messages`。

**处理**：剥掉尾部 `/v1` 再传给 SDK：
```python
base_url = re.sub(r"/v1/?$", "", base_url.rstrip("/"))
```
实测剥掉后两个端点均正常。

**注意**：opencode 用的是 `@ai-sdk/anthropic`，路径拼接规则与 Python `anthropic` SDK 不同 —— **两套框架的 base_url 不能直接互换**。

---

## [015] 静默失败：`if __name__ == "__main__"` 守卫让整段脚本不执行却报成功

**现象**：`execute_code` 返回 `{"status":"success"}`，但场景里 **0 个对象**。无报错、无 traceback。

**原因**：模型生成的代码习惯这样收尾：
```python
def main(): ...
if __name__ == "__main__":
    main()
```
而 addon 是 `exec(code, {"bpy": bpy})`。该命名空间**没有 `__name__`**，Python 全局名查找会命中 **`builtins` 模块字典里的 `__name__`**，其值为 `'builtins'`。守卫为 `False`，`main()` 从不执行 —— 整段退化为空操作，却仍 `success`。

**处理**（双保险）：
1. 执行前注入 `code = "__name__ = '__main__'\n" + code`
2. 执行后校验 MESH 数量，为 0 就当失败回报，不当成功

**纪律**：**`exec 成功 ≠ 场景有东西`**。所有"AI 写代码去操作软件"的工具链都必须有后置状态校验。

---

## [016] 相机取景必须由 harness 强制兜底，不能交给模型

**现象**：AI 建成 30 构件、包围盒 `(8.40, 5.40, 7.58)` 的城楼，批评家只给 2.0 分，理由"模型完全缺失""主体被裁切"。

**原因**：场景残留上一轮（斗拱，0.3m 尺度）的相机 `(0.85, -1.15, 0.95)`，对着 8 米城楼等于贴脸。

**处理**：渲染前按所有 mesh 的世界包围盒重设相机：
- `dist = radius / tan(fov/2) * margin`（margin≈1.28）
- 朝向 `(center - cam.location).to_track_quat('-Z','Y').to_euler()`

生效日志：`FRAMED center=(0.0, 0.0, 4.975) radius=6.153 dist=29.171 fov=30.2deg`

**原则**：**取景是工程约束，不是创作决定**。模型可调构图，但"能不能拍全"必须由 harness 保证。

---

## [017] `bpy.ops` 需要正确 context，AI 最容易在这里翻车

**现象**：Round 2 直接失败：
```
RuntimeError: Operator bpy.ops.mesh.select_all.poll() failed, context is incorrect
```

**原因**：`bpy.ops.*` 依赖上下文（活动对象、模式、区域类型）。MCP 驱动时没有人在 3D 视口操作，`poll()` 常返回 False。高危：`mesh.select_all` / `object.mode_set` / `object.join` / `mesh.primitive_*_add` / `object.transform_apply` / `view3d.*`

**处理**：优先 **data API + bmesh**，绕开 ops：

| 别用 | 改用 |
|---|---|
| `mesh.primitive_cube_add()` | `bpy.data.meshes.new()` + `from_pydata()`，或 `bmesh.ops.create_cube()` |
| `object.mode_set(mode='EDIT')` | `bmesh.new()` 直接编辑网格数据 |
| `object.select_all()` | 直接操作 `bpy.data.objects` |
| `object.join()` | `bmesh` 累加 `from_mesh` |
| `object.transform_apply()` | 直接改 `mesh.vertices[i].co` |

必须用 ops 时，用 `bpy.context.temp_override(...)` 显式给上下文。

**已固化进 `ai_loop.py` 的 `BUILD_SYSTEM`。**

---

## [018] 首轮实测的完整流水线性能基线

| 环节 | 耗时 |
|---|---|
| 模型生成代码（qwen3.5-plus） | 118–160 s |
| 在 Blender 执行 | 1–3 s |
| 强制取景 + EEVEE 渲染 1200×900 | 2–4 s |
| 视觉批评家（qwen3.5-plus，1024px JPEG） | 26–35 s |

**端到端一轮约 2.5–3.5 分钟**。瓶颈明显在**模型生成代码**，不在 Blender。
→ 优化方向：让模型少输出、分构件增量、或把常见构件做成可复用模板。

**模型能力实测**：
| 模型 | 文本 | 视觉 |
|---|---|---|
| `qwen3.5-plus`（ali-coding-plan） | ✅ | ✅ 能描述渲染图 |
| `MiniMax-M2.5`（minimax-mickeylan） | ✅ | ❌ 明确回复"没有看到图片" |

→ **批评家必须用 qwen3.5-plus 这类视觉模型**。

---

## [019] 地面/背景板会把包围盒撑爆，取景崩掉

**现象**：模型建了 31 个构件，但包围盒报 `(30, 24, 24)`（目标 8×4×6.7），
取景日志 `FRAMED radius=22.650 dist=107.375` —— 相机被推到 107 米外，
主体在画面里缩成一点，批评家给 **1 分**（"只有一个简单方块"）。

**原因**：模型自作主张加了一块 30×24 的地面平面。取景按"所有 mesh 的包围盒"算，
被这块板子主导。

**处理**：取景时先剔除"背景物件"，两条判据任一成立即排除：
1. 名字匹配 `ground|floor|plane|terrain|backdrop|stage|平台|地面`
2. **极扁且面积远大于其它物体**：`ez <= max(ex,ey)*0.03` 且 `max(ex,ey) >= 其它物体最大跨度*2.5`

剔除后若为空则回退用全部。日志会打印 `FRAME_OBJECTS kept=../.. excluded=[...]` 便于核对。

**提示词也加了一条**：不要加超大地面；若必须加，命名里带 `Ground`。

---

## [020] `bmesh.ops.create_cube(size=)` 只接受标量，不接受元组

**现象**：`TypeError: create_cube: keyword "size" expected a float, not tuple`

**原因**：模型习惯写成 `create_cube(size=(1,2,3))` 想要长方体，但该参数是**边长标量**。

**处理**：要长方体就自己给 8 个顶点 + 6 个面走 `from_pydata`（已封装为助手 `box()`）。

---

## [021] 颜色元组只能 4 个分量

**现象**：`ValueError: sequences of dimension 0 should contain 4 items, not 5`

**原因**：模型写了 `(r,g,b,a,1.0)` 这类 5 元组。

**处理**：`default_value` 必须是 `(r,g,b,1.0)`。已封装为助手 `mat(name, rgb, rough)`，只接 3 元组。

---

## [022] 瓶颈不在循环机制，而在模型对 bpy API 的熟练度

**现象**：连续三轮实测中，**两轮失败都是纯 API 细节错误**
（`create_cube(size=tuple)`、颜色元组 5 个值、`.base_color` 属性不存在），
只有一轮真正在建模。也就是说算力和时间大头花在"修拼写"，而不是"改设计"。

**处理**：注入一层**安全助手库**（`ai_loop.py` 的 `PRELUDE`），每次执行时前置到用户代码之前，
模型直接调用高层函数：

| 助手 | 作用 |
|---|---|
| `clear_scene()` | 清场（不碰 `read_factory_settings`） |
| `mat(name, rgb, rough, metallic)` | 材质，rgb 只接 3 元组 |
| `box(name, size, loc, rot, material)` | 长方体，size 为完整边长 |
| `cyl(name, radius, depth, ...)` | 圆柱（内部走 `bmesh.ops.create_cone`） |
| `prism(name, footprint, height, apex, ...)` | 棱台，用于收分屋顶/须弥座 |
| `beam(name, p1, p2, thickness)` | 两点架方木（梁/枋/栏杆） |
| `coll(name)` | 建集合 |
| `setup(engine, res, samples, bg)` | 引擎/分辨率/世界/太阳光/相机 |
| `stats(label)` | 构件数/顶点数/包围盒 |

**验证**：助手库单测通过 —— `构件=7 顶点=176 包围盒=3.20 x 2.20 x 3.20 m`。

**这是本项目最有价值的一条**：让模型在"构件语义层"工作，而不是在"API 语法层"工作。

---

## [023] `matrix_world` 是惰性的：不 `view_layer.update()` 会读到旧变换

**现象**：`stats()` 报包围盒 `3.20 x 2.20 x 2.40`，但按代码应为 `3.20 x 2.20 x 3.20`。

**诊断**（直接实测对比）：
```
BEFORE_UPDATE bboxZ=-0.800..0.800  Roof.matrix_world.translation=(0.0, 0.0, 0.0)
AFTER_UPDATE  bboxZ=0.000..3.200  Roof.matrix_world.translation=(0.0, 0.0, 2.7)
```
`Roof` 明明设了 `location.z = 2.7`，但在更新依赖图之前 `matrix_world` 仍是单位矩阵。

**原因**：给 `ob.location` 赋值只改了属性，`matrix_world` 与 `bound_box` 要等依赖图求值才刷新。

**影响面**：**所有基于包围盒的计算都会错**，包括相机取景 —— 偏差可达一倍以上。

**处理**：任何读 `matrix_world` / `bound_box` 之前先调用
```python
bpy.context.view_layer.update()
```
已加到 `stats()` 和 `_frame_camera()` 开头。

---

## [024] 助手层必须容错 —— LLM 会用「位置参数 + None 占位」

**现象**：加了助手库之后，**反而三轮全挂**，且错误全是助手调用姿势不对：

```python
box('Base_Wall_L', (2.7,4.0,3.0), (-2.65,0,1.5), None, mat_stone)
#                                                ↑ rot=None -> "bpy_struct: item.attr = val:"
cyl('Base_Arch', 1.3, 4.0, (0,0,2.0), (90.0,0,0), 24)
#                                       ↑ 传的是「度」，Blender 要弧度
cyl('Col_1', 0.15, 2.5, (-2.8,-1.6,4.45), None, mat_wood)
#                                                ↑ 材质挤进了 verts 位
setup('CYCLES', 128, ...)   # samples 传进 res 位 -> "cannot unpack non-iterable int object"
prism(..., apex=single_int) # -> "cannot unpack non-iterable int object"
footprint=((x,y),(z))       # 嵌套元组 -> "float() argument must be ... not 'tuple'"
```

**根因**：LLM 是按"大概长这样"来调 API 的，常见三种走偏：
1. 用 `None` 占位跳过可选参数
2. 把角度当弧度传
3. 位置参数错位（材质挤进数字位、samples 挤进 res 位）

**结论（重要）**：**要求模型写准 API 是错的方向**。正确做法是**助手层做容错适配**：

| 容错项 | 处理 |
|---|---|
| `rot=None` | 视为 `(0,0,0)` |
| 旋转值任一 `|v| > 2π` | 自动按角度转弧度 |
| `size` 传标量 | 视为正方体 |
| `size` 传嵌套元组 | 递归展平 |
| 材质出现在数字参数位 | 自动识别并归位到 material |
| `setup()` 的 res/samples/bg 错位 | 按类型判定后重排 |
| `apex` 传标量 | 视为等比缩放 |

**验证**（照抄模型真实写法的回归测试，`test_tolerant.py`）：
```
TOLERANT_TEST 构件=6 顶点=128 包围盒=8.00 x 4.00 x 7.75 m
Base_Arch rotation_euler = (1.5708, 0.0000, 0.0000)   期望 x≈1.5708   ✓ 度转弧度生效
Base_Wall_L rot = (0.0, 0.0, 0.0)                                    ✓ None 被接住
Cap size = (0.5, 0.5, 0.5)                                           ✓ 标量 size 生效
```

**效果对比**（同一目标、同一模型）：
| 阶段 | 得分 | 成功轮次 |
|---|---|---|
| 裸 API | 3.5 | 3 轮里 1 轮成功 |
| 助手库（无容错） | — | 3 轮全挂 |
| 助手库 + 容错 | **5.5** | 显著改善，59 构件 / 872 顶点 |

---

## [025] critic 反复扣分的根因是「形制做不出来」，要编码成参数化助手

**现象**：分数卡在 5.5，critic 的 top_issues 稳定指向同一件事：

> 屋顶结构缺失：目标要求'反曲屋顶'和'起翘檐角'，图中仅为**悬浮的灰色条状物**，未构建实际屋顶网格。
> 构件悬浮/穿插：四周代表檐角的灰色条状物完全悬浮在空中，未与主体连接。

**分析**：这不是模型"不够努力"，而是**它没有能力用基本几何拼出反曲屋面**。
反曲屋面（反宇 + 起翘）是**凹曲面 + 角部抬升**，用长方体和三角形拼不出来。
让模型反复重试只会烧时间 —— **必须把形制编码成参数化助手**。

**处理**：`curved_roof()` —— 庑殿顶反曲屋顶

```
curved_roof(name, width, depth, ridge_h, eave_h, overhang,
            corner_lift, curve, material, ridge_mat)
```

数学构造：
1. **反宇（凹曲面）**：沿坡向参数 `t∈[0,1]`（0=脊, 1=檐）
   `z(t) = eave_h + (ridge_h - eave_h) * (1 - (1-t)^curve)`，`curve>1`
   → 脊部陡、檐口缓，得到**凹**屋面。实测剖面增量
   `0.042 → 0.038 → 0.036 → 0.033 → 0.031 → 0.027 → 0.025 → 0.022` **单调递减** ✓
2. **庑殿顶高度场**：`t = max(|y|, max(0,|x|-Rx)) / (D/2)`，`Rx` 为正脊半长
   → 自动生成 4 个坡面，天然形成垂脊折角
3. **起翘**：角部抬升 `corner_lift * (|x|/(W/2))^8 * (|y|/(D/2))^8 * t^1.5`
   → 只在**四角 + 靠近檐口**抬升，长边檐口中点不受影响
   实测：檐角 `z=2.850` vs 檐边中点 `z=1.900`，**抬升 0.95 m** ✓
4. **连通性**：正脊 + 4 条垂脊（沿曲面细分贴合）+ 4 条檐口板 —— 消除"悬浮感"
5. **一体成形**：4 个坡面网格片边界坐标对齐，共享顶点位置

**验证**（`probes/test_roof.py`）：
```
ROOF_TEST 构件=56 顶点=2260 包围盒=7.82 x 4.42 x 2.94 m
PROFILE: [1.54, 1.582, 1.62, 1.656, 1.689, 1.72, 1.747, 1.772, 1.794]
CORNER z=2.850   EDGEMID z=1.900   LIFT_DIFF = 0.950
```

**同时补齐 critic 另两条高频指控**：
| 指控 | 对应助手 |
|---|---|
| "木材纯色平涂，像默认着色器" | `wood_mat()` — Noise→ColorRamp→Base Color + Bump |
| "基座缺乏砖石质感、边缘锐利" | `stone_mat()` + `bevel(ob, width)` |

---

## [026] 单视图让 critic 判断不了三维结构，必须给三视图

**现象**：critic 能指出"缺屋顶"，但**看不出背面/侧面缺构件** —— 结构分长期停在 1.5/3。

**原因**：3/4 透视只能看到两个面。第三维的信息完全缺失，模型自然评不准。

**处理**：每轮渲染三张，一起喂给 critic：

| 视图 | 相机 | 用途 |
|---|---|---|
| persp | 透视 3/4 | 整体形态、材质、比例 |
| front | **正交**，沿 −Y 看 | 立面、对称、层数、轮廓 |
| top | **正交**，沿 −Z 看 | 平面布局、屋面覆盖、背面构件 |

正交相机的 `ortho_scale` 按包围盒尺寸算，保证各视图主体大小可比。

**验证**（`probes/test_views.py`）：
```
roof_test_persp.png  bbox x[181,628] y[176,449]  占比=14.3%
roof_test_front.png  bbox x[104,695] y[188,410]  占比=20.6%
roof_test_top.png    bbox x[ 80,719] y[119,480]  占比=43.2%
```
顶视占比明显更大 → 说明顶视图确实暴露了平面布局（顶视图里"占地"最大）。

**提示词同步改造**：critic 现在被要求
- 指出**是哪个视图**的哪个部位有问题
- 区分**建模问题**（几何/构件/悬空）与**渲染问题**（材质/光照/取景）
- actions 必须能翻译成代码（提到屋顶就给 `curved_roof()`，材质给 `wood_mat()`…）

---

## [027] 三类"看着像小问题、实际直接挂掉"的失败

实测同一目标连续两轮，三轮里两轮失败，错误各不相同，但根因同属**"我以为模型会正确使用我的 API"**。

### (a) 返回 dict 的助手 → 模型当对象用
```python
roof1 = curved_roof('Roof1', 5.5, 3.0, ...)
roof1.location.z = 5.5          # AttributeError: 'dict' object has no attribute 'location'
```
**根因**：返回 dict 语义不自然，模型必然假设返回的是对象。
**修法**：**助手一律返回单个真实 bpy Object**。
`curved_roof` 改为把屋面 + 正脊 + 垂脊 + 檐口板**合并成一个 mesh**，
两个材质槽（0=屋面, 1=脊檐），这样 `roof.location.z = 5.5` 整体移动，符合直觉。

### (b) 没给材质的物体 → `material_slots[0]` 越界
```python
arch.material_slots[0].material = base_mat
# IndexError: bpy_prop_collection[index]: index 0 out of range, size 0
```
**修法**：`_ensure_slot(ob, material)` —— 任何构件建好后都保证至少 1 个材质槽
（没有就给个默认灰材质）。模型随时可能用 `material_slots[0]`。

### (c) 幂等后复用了"坏材质"
`mat()` 改成同名复用后，上一轮遗留的坏材质会被下一轮复用 → `no BSDF_PRINCIPLED in new material`。
**修法**：
- `mat()` 检测到复用材质没有 BSDF 就**重建节点树**（自愈）
- `clear_scene()` 一并清理无用户材质，避免多轮循环累积 `.001` 后缀

**回归测试**（`probes/test_regress_027.py`）：
```
ROOF_TYPE Object HAS_LOC True      ROOF_Z 3.0
SLOT_OK Wood
MAT_SAME True Same                 WOOD_NODES 5 5 STABLE True    MAT_COUNT 2
```

---

## [028] 删除 Material Output 节点会连带清空整棵节点树

**现象**：`wood_mat()` 第二次调用报
`KeyError: 'bpy_prop_collection[key]: key "Base Color" not found'` —— 而第一次完全正常。

**探针实测**（`probes/probe_bsdf.py`）：
```
NODES: [('原理化 BSDF','BSDF_PRINCIPLED',...), ('材质输出','OUTPUT_MATERIAL',...)]
INPUTS_BEFORE: ['Base Color','Metallic','Roughness','IOR',...]   HAS_BaseColor: True
NODES_AFTER: []                    ← 删掉 Output 后整棵树空了
BSDF2_FOUND: None
```

**根因**：Blender 里删掉 **Material Output** 节点会触发节点树清理，
**连同喂给它的 BSDF 一起删掉**。"保留 BSDF、删掉其他所有节点"这种写法是错的。

**修法**：只删**我们自己加的**节点 —— 用 `_proc_` 前缀标记
（`_proc_tex` / `_proc_ramp` / `_proc_bump`），`_reset_proc_nodes()` 只删带前缀的，
Output 与 BSDF 一律不碰。

**额外坑**：批量打前缀时**不能给 BSDF/Output 也加前缀**，
否则它们会被 `_reset_proc_nodes` 删掉，症状同样是 `Base Color not found`。

---

## [029] 这个 Blender 的 UI 是中文，节点名不可用

探针输出：
```
NODES: [('原理化 BSDF', 'BSDF_PRINCIPLED', 'ShaderNodeBsdfPrincipled'),
        ('材质输出', 'OUTPUT_MATERIAL', 'ShaderNodeOutputMaterial')]
```

| 用途 | 正确写法 | 错误写法 |
|---|---|---|
| 找到 Principled | `n.type == 'BSDF_PRINCIPLED'` | `nodes.get("Principled BSDF")` |
| 找到世界背景 | `n.type == 'BACKGROUND'` | `nodes.get("Background")` |
| 找到输出 | `n.type == 'OUTPUT_MATERIAL'` | `nodes.get("Material Output")` |

---

## [030] 屋面网格的两个几何 bug：折叠 + 绕序

`curved_roof()` 写完后渲染出来是"灰板"，critic 判"平直灰色板状"。两个独立 bug。

### (a) 中轴折叠
```python
# 错
def front_edge(u, tv):
    return ((Rx + (W*0.5 - Rx) * tv) * (1 if u >= 0 else -1), -tv * halfD)
# 对
def front_edge(u, tv):
    return ((Rx + (W*0.5 - Rx) * tv) * u, -tv * halfD)
```
`* (1 if u>=0 else -1)` 在 `u=0` 处把 x 从负值**突变**为正值 —— 屋面网格在中轴线上折叠断裂。
正确写法是 `* u`：`tv=0` 时 x ∈ [-Rx, Rx]（正脊），`tv=1` 时 x ∈ [-W/2, W/2]（檐口），连续。

### (b) 法线绕序判据用错
```python
# 错：拿"外法线方向"当启发式
if n.normalized().dot(Vector(outward)) < 0: quad = [a, d, c, b]
# 对：屋面必须朝上，用绝对规则
if n.z < 0: quad = [a, d, c, b]
```
端面板在 `tv=0` 是退化行，法线长度为 0，启发式失效，导致**大面积法线朝下** → 渲染成灰板。

**实测**（`ROOF_CHECK` 自检）：
| 阶段 | 朝上比例 | 判定 |
|---|---|---|
| 原始（折叠 + 启发式绕序） | ratio=0.28 | `!! 法线大面积朝下` |
| 修折叠后（启发式仍错） | ratio=0.28 | 仍不对 |
| 改为"必须朝上" | **ratio=0.88** | OK |

**几何最终验证**（沿 x 的最高点剖面，should be: 檐角起翘 → 檐口 0 → 正脊 1.8 → 檐口 0 → 檐角起翘）：
```
x=-3.69 → z=2.84   ← 起翘
x=-1.0  → z=0.0    ← 檐口
x= 0.0  → z=1.80   ← 正脊
x=+1.0  → z=0.0    ← 檐口
x=+3.69 → z=2.84   ← 起翘
```

**教训**：`curved_roof()` 现在**每次都打印 `ROOF_CHECK faces=.. up=.. ratio=..`，
ratio < 0.5 会报警**。几何正确性要有自动断言，不能靠肉眼。

---

## [031] 太阳强度 3.0 会让整幅图像是灰的

**现象**：critic 稳定指控"木材呈现无纹理的纯色平涂，像默认着色器""屋顶是灰色板状"。
但代码里材质明明是 `wood_mat('Tile', (0.16, 0.28, 0.22))` —— **绿的**。

**实测**：屋顶像素平均 RGB = **(107, 109, 98)** —— r≈g≈b，**几乎没有色偏**。

**原因**：Blender 漫反射 = `albedo/π × 辐照度 × N·L`。
`0.25/π × 3.0 × 0.79 ≈ 0.19` → sRGB ≈ 120。**强度 3.0 配 Standard 色彩管理，出来就是中灰**。
色偏被"亮度不足 + 色调映射"吃掉了。

**标定实验**（`probes/calib_light.py`，测画面中心 1/3 区域平均 RGB）：

| 太阳强度 | 中心区平均 RGB | 判断 |
|---|---|---|
| 3.0（原） | (107, 137, 120) | 偏暗，色相弱 |
| **6.0** | **(144, 182, 159)** | **色相清晰，不过曝** |
| 10.0 | (179, 226, 196) | 明亮但接近过曝 |
| 16.0 | (220, 254, 239) | 过曝 |

**修法**：`setup()` 里太阳能量 3.0 → **6.0**，世界背景 strength 1.0 → 1.4，
并加一盏 **Area 补光**（energy 900, size 10）避免暗部死黑。

**验证**（`probes/test_full_roof.py`）：
```
fix_persp.png  前景=10.6% 绿=26.5% 木色=30.5% 平均RGB=(197,194,177)
fix_front.png  前景=21.3% 绿= 1.3% 木色=28.0%   ← 正视只看得到脊/檐木料，绿少是对的
fix_top.png    前景=53.1% 绿=57.0% 木色=21.2%   ← 顶视看到瓦面，绿占多数
```
**顶视绿 57%、正视绿 1.3%** —— 与"顶视看瓦面、正视看檐口木料"完全吻合，说明材质分配正确。

**教训**：critic 说"材质像默认着色器"时，**先量像素实际 RGB**，
别急着改材质节点 —— 可能是**光照**问题。

---

## [032] 没有视觉能力时，用终端字符图代替"眼睛"

本会话的视觉工具被套餐限制（`provider error 405`），但建模闭环**必须**能看图。

**做法**：`view.py` —— 把渲染图降采样成字符网格，并按颜色分类：

```
|::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::|
|:::::::::::::::::::::::::::::----:::::::::::::::::::::::::::::::::::::::::::::::::::::::|
|:::::::::::::::::::::::::::::-------+----=-------:::::::::::::::::::::::::::::::::::::|
|::::::::::::::::::::::::--------:::=*+--:::----------------:::::::::::::::::::::::::::|
|::::::::::::::::::::::::-==------=+++**+===----::::::------===-:::::::::::::::::::::::|
|:::::::::::::::::::::::::----==++++++==+++*+**+++====-------==::::::::::::::::::::::::|
|:::::::::::::::::::::::::::------=+++=------===+++***++==--==-::::::::::::::::::::::::|
|::::::::::::::::::::::::::::::::::---====+++=---=*+++==--==-::::::::::::::::::::::::::|
```
配合颜色分类图（`G`绿 `R`木红 `B`蓝 `W`亮 `K`暗 `.`其它），
能直接看出"这是不是屋顶""柱子有几根""有没有阴影黑块"。

**用途**：
- 快速判断构图/剪影/明暗
- 对比修改前后的差异
- 在不能看图的环境里保持"自查"能力

**局限**：读不出精细细节，**不能替代** critic 的视觉模型。
但对几何轮廓、裁切、留白这类问题，字符图够用。

---

## [035] 屋顶"倒过来"的两个独立原因（第一个是我的 bug）

用户两次指出"屋顶是倒的"。查下来是**两个不同的 bug**，而且我的自检两次都漏了。

### (a) `prof(t)` 两端取值互换
```python
# 错：t=0(脊) 得 eave_h，t=1(檐) 得 ridge_h —— 屋面整个翻转
return eave_h + (ridge_h - eave_h) * (1.0 - (1.0 - t) ** curve)
# 对：t=0 必须得 ridge_h
return ridge_h - (ridge_h - eave_h) * (1.0 - (1.0 - t) ** curve)
```

**为什么自检漏了**：我写的是"每个 x 上的**最大** z"。
屋面翻转后，每个 x 上仍能从檐口那一圈取到高值 → 测出 `x=0 → 1.80` 这种**假阳性**。
**检查指标本身对被测缺陷不敏感，等于没检查。**

**正确检查**：沿固定路径采样，验证**单调性**。
```python
_zs = [height(0.0, halfD * k / 8.0) for k in range(9)]   # 脊 -> 檐
_mono = all(_zs[i] >= _zs[i+1] - 1e-9 for i in range(len(_zs)-1))
```
修好后输出：`ROOF_ORIENT profile=[1.9, 1.379, 0.953, 0.615, 0.36, 0.18, 0.068, 0.013, 0.0] drop=1.90 OK(脊高檐低)`
—— 递减量本身也从 0.52 缩到 0.013，同时证明"脊陡檐缓"的反宇曲率是对的。

### (b) 起翘量超过举高 → 檐角翘到比屋脊还高
```python
# build_gate.py 里我写的调用
curved_roof(..., ridge_h=T1_Z + T1_H + 1.55, eave_h=T1_Z + T1_H,
            corner_lift=ridge_h * 0.5)      # = 7.27*0.5 = 3.64m
```
`ridge_h` 是**绝对高度 7.27**，举高只有 **1.55m**。
于是檐角被抬到 **10.9m**，比屋脊 7.27m 还高 3.6m —— 四角翘成喇叭，**看起来就像整个屋顶翻过来了**。

**修法（三层防御）**：
1. 在 `curved_roof` 内部硬钳制：`corner_lift = min(corner_lift, rise * 0.55)`
2. `ridge_h < eave_h` 时自动交换（模型传反了就是真倒置）
3. 举高过平时自动抬到 `0.28 * min(宽, 深)`（否则是"平板屋顶"）

并新增断言：
```
ROOF_LIFT ridge_z=7.27 corner_z=6.26  OK(角低于脊)     ← 修好后
                          (修前 corner_z = 10.9，直接被抓出)
```

**教训**：**绝对高度**与**相对举高**混用是形制助手的头号坑。
凡是"比例类"参数（起翘、收分、出檐），一律在函数内部按主尺寸钳制，
不要让调用方传绝对值。

---

## [036] 采用 blender-visual-craft skill 的取证规范

读了 `j:/mickeylan/ai/blender-visual-craft`，它的核心一句话正好治我的病：

> **"MCP、Python、修改器数量或文件生成成功不构成美术验收。"**

我上一轮 `ROOF_CHECK ratio=0.88 OK` 打印得漂漂亮亮，屋顶却是倒的 —— 正是这句话说的情况。

落地改造：

| skill 要求 | 我的实现 |
|---|---|
| 保留标准**正面/侧面/背面**与展示视角 | 渲染通道改为 hero(透视) + front + right + back + **clay 灰模** |
| 展示机位不冒充正交检查机位 | hero 用 PERSP，其余用 ORTHO，分别标注 |
| **灰模证据**与材质图分开 | Workbench `SINGLE` 色 + cavity，单独一张 |
| 正交框选按投影基向量算 | `ortho_scale = max(max(right·p), max(up·p)) * 1.16` |
| 记录相机矩阵以便跨版本严格对照 | 每张打印 `CAM_MATRIX` |
| 逐项 **pass/fail/unclear** + 证据图 | critic 输出 `checks[]`，要求看不见必须写 unclear |
| 审稿要写"**保持不变的要求**" | critic 输出 `invariants[]`，注入下一轮建模提示 |
| 两轮没改善 → 换路线而非微调 | 连续两轮不升分时打印 warn |
| 自动框选改变相机会破坏对照 | 已记录该限制；固定相机待实现 |

**灰模的一个实测细节**：skill 的 `show_shadows = False` 是为避免正交顶视的
Workbench 阴影条带。但我照搬到透视灰模后 StdDev 只有 **11**，形体完全读不出来。
改为**只在 top 视图关阴影**，透视灰模开阴影。

---

## [037] 起翘量用绝对值传参 → 檐角翘到比屋脊还高

**现象**：用户第二次指出"屋顶还是倒过来的"。几何自检却报 `OK(脊高檐低)`。

**原因**（`build_gate.py` 的调用）：
```python
curved_roof(..., ridge_h=T1_Z + T1_H + 1.55,   # 绝对高度 7.27
                eave_h=T1_Z + T1_H,            # 绝对高度 5.72
                corner_lift=ridge_h * 0.5)     # = 3.64m ！！
```
`ridge_h` 是**绝对 z**，但 `corner_lift` 被当成举高的比例去算。
举高只有 1.55m，起翘却给了 3.64m → 檐角抬到 **10.9m，比屋脊 7.27m 还高 3.6m**。
四角翘成喇叭状，视觉上就是"整个屋顶翻过来了"。

**为什么自检没抓到**：`ROOF_ORIENT` 只沿 `x=0` 的中线采样。
起翘只发生在四角，中线完全不受影响 —— **采样路径避开了缺陷所在位置**。
（同一个错误换了形式：上一版是"指标不敏感"，这次是"采样点不覆盖"。）

**修法（三层防御，全部写在 `curved_roof` 内部）**：
1. `corner_lift = min(corner_lift, rise * 0.55)` —— 起翘不超过举高的 55%
2. `ridge_h < eave_h` 时自动交换（模型传反了就是真倒置）
3. 举高过平时抬到 `0.28 * min(宽, 深)`，避免平板屋顶
4. 新增断言 `ROOF_LIFT`，直接比较**屋脊顶点与檐角顶点**的 z：
```
ROOF_LIFT ridge_z=7.27 corner_z=10.90  !! 檐角高过屋脊，看起来会像倒置   ← 修前
ROOF_LIFT ridge_z=7.47 corner_z=6.68   OK(角低于脊)                    ← 修后
```

**设计原则**：形制助手里凡是"比例类"参数（起翘、收分、出檐），
一律**在函数内部按主尺寸钳制**，不要让调用方传绝对值。

---

## [038] 跨轮固定检查相机（skill 明确警告，我之前没做）

**问题**：每轮都按包围盒重新自动取景。模型一改尺寸，机位就变，
**两张图不可严格对照** —— 6.0 → 4.0 那次下降有多少是真实退步、多少是机位变了，说不清。

**实现**：
- 首轮自动取景后，把 5 个通道的 `loc / rot / type / lens / ortho / res` 记进 `Session.cam_lock`
- 后续轮把这份字典序列化进渲染脚本，**原样设置相机**，不再运行自动取景
- 日志会打印 `CAM_LOCKED <channel>`

**验证**（`probes/test_cam_lock.py`，故意让第二轮模型大 1.58 倍）：
```
back  一致  loc=[0.0, 17.068, 1.85]  ortho=7.63
clay  一致  loc=[10.697, -14.857, 9.219]
front 一致  loc=[0.0, -17.068, 1.85]  ortho=7.63
hero  一致  loc=[10.697, -14.857, 9.219]
right 一致  loc=[17.068, 0.0, 1.85]  ortho=4.62
结论: PASS 两轮机位完全一致
```

**随之而来的裁切问题**：固定机位 + 模型变大 = 边缘被裁。
这是**真实缺陷信号**，所以不能悄悄重框，必须报出来：
```
[cam] !! FRAME_OVERFLOW 本轮模型 10.38×5.98×5.59m 超出基准取景
      6.58×3.98×3.70m（最大 1.58 倍），正交视图边缘有裁切
```
该提示会一并喂给 critic，让它区分"建模超标"和"取景失误"。

---

## [039] 同模型自检虚高 2.3 分（实测量化）

**方法**：同一组 5 张证据图，喂给两个模型各自独立打分
（`probes/test_cross_review.py`）。

| 维度 | qwen3.5-plus（**也是建模者**） | kimi-k2.5（独立） | Δ |
|---|---|---|---|
| structure | 2.8 | 1.5 | **−1.3** |
| composition | 3.0 | 2.5 | −0.5 |
| materials | 2.2 | 2.0 | −0.2 |
| details | 0.8 | 0.5 | −0.3 |
| **total** | **8.8** | **6.5** | **−2.3** |

**自检虚高 2.3 分**（8.8 vs 6.5），而且 kimi 抓到了 qwen 漏掉的具体缺陷。

**但修完缺陷后两者收敛了**：
| 版本 | qwen | kimi | Δ |
|---|---|---|---|
| 修正前（屋顶窄于基座、基座超尺寸） | 8.8 | 6.5 | **−2.3** |
| 修正后（基座精确 8×4×3、屋顶出挑） | 7.3 | 7.0 | **−0.3** |

**结论**：得分差距大 ⇒ **往往意味着真有缺陷**，而不是"两个模型口味不同"。
这让"交叉评审分歧"本身成为一个可用的**缺陷探针**。

**实现**：`--critic-provider` / `--critic-model` 参数；不指定时如实打印
"与 builder 同模型 —— 这是自检，不是独立评审"，并把
`_critic: {model, independent}` 写进每轮 verdict。

---

## [040] 本机真正能看图的只有两个模型

把 `out/gate_hero.png` 发给 6 个模型，问"图里是什么建筑"：

| 模型 | 结果 |
|---|---|
| `qwen3.5-plus` | ✅ "中式双层亭阁的 3D 模型…底部石质基座与台阶、木柱、屋檐、木质栏杆" |
| `kimi-k2.5` | ✅ "中式双层城楼/门楼…石质基座、双层木构屋顶、木栏杆" |
| `glm-5` | ❌ "你没有上传图片" |
| `MiniMax-M2.5` | ❌ "没有看到图片" |
| `qwen3-max-2026-01-23` | ❌ 该端点 400 |
| `qwen3-coder-plus` | ❌ 该端点 400 |

→ **独立评审只能在 `qwen3.5-plus` 与 `kimi-k2.5` 之间交叉**。
已在 `PROVIDERS` 加 `kimi` 别名，并定义 `VISION_CAPABLE` 集合。
（`glm-5` / `MiniMax` 可以建模，但绝不能当评审。）

---

## [041] 批评家也会错，它的指控必须用几何数值核实

kimi 报告"屋檐尺寸 FAIL、屋顶缺少起翘形态 FAIL"。逐条核对：

| 指控 | 几何实测 | 判定 |
|---|---|---|
| 屋檐尺寸 FAIL | 一层屋顶 **7.49m 宽**，基座 **8.50m 宽** —— 屋顶比基座窄，没有出挑 | **成立** |
| 缺少起翘形态 | 檐口 z=8.27 → 檐角 z=8.72，抬升 0.85m，几何存在 | 部分成立（视觉可读性不足） |

**修法**：屋顶 footprint 从 `6.2` 提到 `7.6`（+出檐 = 8.91m，出挑到基座 8.0 之外），
起翘从 `rise*0.35` 提到 `rise*0.55`。

**原则**：critic 的每条指控都要落到一个**可测量的几何量**上再决定改不改。
模型说"看起来不对"可能对也可能错，但"宽度 7.49 < 8.50"是可验证的事实。

---

## [042] 剩余限制：反宇曲率在这个尺度上视觉读不出来

几何上反宇是成立的。沿坡向 9 点采样，递减量为：
```
0.398 → 0.325 → 0.258 → 0.194 → 0.137 → 0.086 → 0.042 → 0.010
```
坡度变化 **40 倍**（脊部陡、檐口缓），这是标准的凹曲屋面。

但两个 critic 一致反馈"屋顶为平直斜面，无法辨认反曲"。

**原因判断**：`rise / depth = 1.75 / 3.9 ≈ 24°` 平均坡度偏缓，
加上 3/4 俯视角度把剖面曲线**前缩**掉了，720px 图里读不出来。
真实中式屋顶的脊部接近 45°，且屋面有明显的瓦垄分界帮眼睛读出曲率。

**尚未解决**，后续方向：加陡举高、增加瓦垄几何（沿坡向的分条瓦）、
或改用侧视正交专门出一张"屋面剖面"证据图。

---

## 待验证 / 下一步

- [x] `get_viewport_screenshot` —— **不可用，见 [011]**
- [x] 驱动端接哪种模型 —— **qwen3.5-plus / kimi-k2.5 能看图，见 [040]**
- [x] 相机自动取景 —— **包围盒精确适配，见 [033]**
- [x] 跨轮固定检查相机 —— **已实现并验证，见 [038]**
- [x] 独立交叉评审 —— **已实现并量化，自检虚高 2.3 分，见 [039]**
- [x] 形制助手 `curved_roof()` —— **见 [025]/[030]/[035]/[037]**
- [x] 光照标定 —— **见 [031]**
- [x] 终端字符图自查 —— **见 [032]**
- [x] 五通道证据渲染（含灰模）—— **见 [036]**
- [ ] **屋面曲率的视觉可读性**（加陡举高 / 瓦垄几何 / 专用剖面图）—— 见 [042]
- [ ] 静默失败的其他变体
- [ ] 快照/回滚：模型改坏场景后如何恢复
- [ ] 增量修改：只改指定构件
- [ ] 斗拱参数化助手 `dougong()`
- [x] 安全助手库 —— **已实现，见 [022]**
- [x] 助手层容错 —— **已实现，见 [024]**，得分 3.5 → 5.5
- [x] 形制助手 `curved_roof()` —— **已实现，见 [025]**
- [x] 三视图渲染 —— **已实现，见 [026]**
- [x] 助手返回值语义 —— **已实现，见 [027]**
- [x] 屋面几何自检 —— **已实现，见 [030]**
- [x] 光照标定 —— **已实现，见 [031]**
- [x] 终端字符图 —— **已实现，见 [032]**
- [ ] 用全部修正重跑同一目标，量化得分提升
- [ ] 静默失败的其他变体：除 `__main__` 守卫外，还有哪些写法会让脚本空转？
- [ ] 快照/回滚：模型改坏场景后如何恢复
- [ ] 增量修改：只改指定构件，而不是每轮重写整份脚本
- [ ] 多模型对比：同一目标下 qwen3-max / glm-5 / kimi-k2.5 的建模质量
- [ ] 斗拱也做成参数化助手（`dougong()`）—— 下一个形制目标

