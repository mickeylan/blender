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
---

## [043] 只给整体包围盒 → critic 连续三次误判尺寸

kimi 连续三轮报"基座深度超4m"。**实测基座精确是 4.00m** ——
它把**屋檐出挑的 5.26m** 当成了基座深度。整体包围盒含出挑，必然大于基座。

**根因**：critic 只拿到一个数字，没有"哪个数字属于哪个构件"的对应关系。

**修法**：新增 `Session.component_dims()`，按对象名 `_` 前的部分分族量取：
```
  Base            6 件   宽  8.00 × 深  4.00 × 高  3.00 m
  T1             74 件   宽  8.91 × 深  5.21 × 高  4.55 m
```
并明确告诉 critic：
> 核对尺寸时**必须用分族实测值**，不要用整体包围盒去套某个构件。

**效果**：kimi 立刻从"基座尺寸 FAIL"变成 **"基座尺寸 PASS"**。

**教训**：给评审的数据必须**可归因**。一个笼统的总尺寸，
会让评审把不同构件的指标混在一起 —— 然后报出看似有理、实则错误的缺陷。

---

## [044] 斗拱助手 `dougong()`：从"评审要求"到"宋式可辨"

评审反复要求"T1 屋面缺少可辨识的斗拱结构"。模型自由发挥做不出斗拱
（层数/出跳/斗块全靠猜），所以做成形制助手。

### 五铺作单朵（k = 斗口）
```
0  栌斗      十字形基座（两盒交叉，臂 3.4k）
1  华栱      十字出跳 4k，端上置交互斗
2  泥道栱    沿 x 架在两端交互斗上
3  令栱      再出跳到 5.6k，上置散斗
4  下昂      自泥道栱层斜挑出檐外（宋式昂修长）
5  撩檐枋    顶部承檩
```
总高 = **12.3k**。斗口 0.085m → 1.05m 高、22 构件。

### 视觉评审实测点名的缺失项，正是宋式关键
qwen 判 `looks_like_dougong: "yes"`，但 `missing_features` 点名：
**卷杀**（栱的曲线杀削）与**斗欹**（斗块收分）。

于是补了两个自定义网格：

| 构件 | 实现 |
|---|---|
| `_juan_sha_gong()` | 栱**底面是一道上翘曲线**（`bot = h*(1-0.45*t^1.7)`），顶面平直，两端收薄 |
| `_dou_block()` | 斗块**底部收分**到 70%，到 1/3 高处再放大到全尺寸 |

补完后复判：`song_style` 从 `"unclear"` 变成明确判断 `"no"`，
且可见特征变为"出跳斗拱 / 层层叠出 / 散斗交互斗 / 顶部横向承檩枋"。

**仍在缺**：栱头卷杀曲线细节、泥道栱雕饰、昂的延伸曲线特征
（qwen 实测点名，非推测）。斗口放大到 0.12m 以上会更易读。

### 接入城楼时的坑
斗拱高 1.05m，**屋檐必须抬到撩檐枋之上**，否则斗拱直接穿出屋面。
`build_gate.py` 里因此把 `eave_h` 从 `z0+h` 改成 `z0+h+DG_H`，
二层也从"一层柱顶"改为"**一层屋檐之上**"（重檐城楼）。

---

## [045] 增量修改：模型可声明保留哪些构件

**动机**：原来每轮都让模型重写整份脚本。
改一处要重跑全部，且模型经常把已合格的部分改坏。

**协议**：模型在代码**最前面**写一行
```python
KEEP = ["Base_", "Col_"]      # 名字按前缀匹配
```
harness 提取它并注入 `_KEEP`，`clear_scene()` 随即只删除保留集合之外的构件。
不写 `KEEP` 就是全量重建（原行为不变）。

**验证**（`probes/test_incremental.py`）：
```
R1 构件: ['Base_Plate', 'Beam_Top', 'Col_0', 'Col_1', 'Col_2']
  [keep] 增量模式：保留 2 项 -> Base_, Col_
R2 构件: ['Base_Plate', 'Beam_Top', 'Col_0', 'Col_1', 'Col_2']
断言1 保留族仍在: PASS
断言2 只剩保留族+重建件: PASS
断言3 Beam 已重建: PASS
断言4 梁已上移到 2.80: BEAMZ 2.80
```

**踩到的坑（已修）**：注入顺序错了。
`run()` 里先注入 `_KEEP = [...]` 再拼 `PRELUDE`，
而 `PRELUDE` 开头有 `_KEEP = None` —— **把注入值冲掉了**，
增量模式静默退化成全量清场（第一版测试就是这样失败的）。
修法：PRELUDE 里**不写** `_KEEP = None`，
`clear_scene()` 改用 `globals().get("_KEEP", None)` 取值。

> 教训：**注入的值会被后续的默认赋值覆盖**。
> 静默退化成"更激进的破坏"比直接报错更危险 —— 它不报错，只是效果不对。

---

## [046] 快照 / 回滚：每轮存 .blend，结束时回滚到最佳轮

- **存**：`bpy.ops.wm.save_as_mainfile(filepath=..., copy=True)`
  —— `copy=True` **只另存一份**，不改变当前会话打开的文件，因而**不会影响 MCP 通道**。
- **恢复**：`bpy.data.libraries.load(path, link=False)` 把对象追加进当前场景。
  **不用** `bpy.ops.wm.open_mainfile` —— 那会整体重载文件，
  有重置插件状态的风险（LESSONS [002] 同样禁掉了 `read_homefile`）。

**验证**（`probes/test_snapshot.py`）：建场景 → 存快照 → 破坏（只剩 Junk）→ 恢复：
```
断言1 快照文件存在: PASS
断言2 构件名完全一致: PASS
断言3 垃圾对象已清除: PASS
断言4 尺寸一致: PASS
   A: Base 1件 6.00×4.00×0.40 | Beam 1件 4.40×0.20×0.20 | Col 3件 4.30×0.30×2.00
   B: Base 1件 6.00×4.00×0.40 | Beam 1件 4.40×0.20×0.20 | Col 3件 4.30×0.30×2.00
D MCP 通道: 仍通
```

**踩到的坑**：`restore()` 里用 `%` 拼接代码字符串，
而代码本身含 `print('RESTORED %d' % _n)` —— **外层格式化把内层吃掉了**，
报 `TypeError: not enough arguments for format string`。
改用 `.replace("__PATH__", ...)` 拼接。凡是拼 Python 代码字符串，
**不要用 `%` 格式化**（代码里几乎必然含 `%`）。

---

## [047] 瓦垄：让反宇曲率从"看不见"到"看得见"

LESSONS [042] 记的是"反宇曲率在渲染图上读不出来"。
本轮用**瓦垄**解决 —— 眼睛需要参照物。

### 三个版本，前两个都是错的

| 版本 | 做法 | 结果 |
|---|---|---|
| v1 | 垄沿 x 固定、平行于坡向 | 起点落在垂脊之外，**脊部附近断垄**（评审报"瓦垄显示不完整"）|
| v2 | 垄从正脊**扇形**张开到檐口 | 前坡最外垄与侧坡最外垄**落在同一条垂脊线上**，两套几何重叠 → Z-fighting（评审报"瓦垄在屋脊处衔接不连续"）|
| v3 ✅ | 垄**平行于坡向**，在垂脊处**裁断** | 通过 |

v3 的裁断起点是几何算出来的：
- 前坡：垄沿 y 走向，起点 `t0 = (|x| - Rx) / (W/2 - Rx)`
- 侧坡：垄沿 x 走向，起点 `t0 = |y| / halfD`

**关键**：垄线必须**贴合曲面**（每点 z 取 `height(x,y)`），
不能用直线插值 —— 否则垄线自己就是直线，参照物反而掩盖了曲率。

### 效果
kimi 的反馈从"屋顶为平直斜面，无法辨认反曲"变成
**"瓦垄完整性 PASS"** —— 它开始讨论瓦垄与正脊的关系，说明真的看见垄了。

---

# LESSONS 048–062 —— 贯木拱虹桥

> 这一段的起点是"评审说虹桥不像虹桥"，终点是两个独立能看图的模型
> 全部判 `is_guan_mu_gong / no_pier_in_river / weaving_visible / arch_rise_visible`
> 四项 yes。
>
> 过程中最大的教训：**先查权威形制，再动手建模**。
> 连续四轮评审失败，根因全在"我以为的虹桥"和"文献里的虹桥"不是一回事。

---

## [048] 形制必须查权威来源，不能靠"看起来像"

虹桥是《清明上河图》的核心结构，也是最容易凭印象做错的东西。
我最初的做法是**三组平行的梁**（"三组梁并排"），结果两位评审一致判：

> "梁表现为平行的直线木梁，三维结构不明确"
> "结构表现为简化的支墩式三角桁架结构"

查证后（唐寰澄 1953 年对《清明上河图》的首次科学认定 +
百科"虹桥"条 + 福建屏南万安桥 / 浙江云和梅崇桥等"活态虹桥"）：

> **主体结构由两组拱骨系统交错搭置，通过横梁贯穿联合而成**，
> 中间无榫无钉，靠木料**相互别压咬合**承重。
> 净跨约 20m，**拱矢约 5m**，宽约 8m。
> （万安桥）"拱架系统由两套系统构成：最下方由三段实木搭建的**三节苗**
>  构成了一级受力系统，由五段实木组成的**五节苗**与其**穿插别压**，
>  构成了二级受力系统。"

于是重写为：**A = 三节苗（3 段，4 节点，下）**，
**B = 五节苗（5 段，6 节点，上）**，节点互相错开、交替上下。

> **教训**：形制助手（`hongqiao()` / `dougong()` / `curved_roof()`）这类
> "历史建筑"函数，参数必须来自文献，不能来自直觉。
> 评审说"不对"时，先怀疑自己的形制假设，而不是怀疑渲染。

---

## [049] 三节苗 vs 五节苗：节苗数不同，才是"编织"的来源

两套系统如果都是 3 段、只做纵向平移，那它们**永远平行**，
永远织不起来。**节苗数不同**（3 vs 5）才会让节点错开、
让二级系统交替压上/钻下。

建模要点：
- A（三节苗）节点 u = 0, 1/3, 2/3, 1；z = z_end, z_top, z_top, z_end
- B（五节苗）节点 u = 0, 0.2, 0.4, 0.6, 0.8, 1；z = **A 的折线值 ± weave_amp**，符号交替

几何自检（写进 `probes/test_hongqiao.py`）：沿桥跨采样
`z_A(x) - z_B(x)` 的**符号变化次数**，必须 ≥ 3 段。
实测稳定在 **6 段**（`ABAABAABA`）。

---

## [050] 别压的净空必须大于一个梁径

两梁"压上去"要有可见的上下关系，压的幅度必须 **> 两倍梁半径**，
否则交点处两梁互相穿插，渲染上糊成一根。

实测参数：`weave_amp = 1.25 m`（梁半径 0.34），
横向苗的编织幅度 `amp2 = beam_r * 2.6`。

另外：**两套纵向系统的横向间距 `dw` 必须 > 2 × 梁半径**。
早前 `dw = beam_r * 1.5 = 0.51` 而两个半径之和是 0.68 → **互相穿插**，
评审原话："两根纵梁在相交处呈现平顺的交叉，未能形成直接的互相咬合搭接"。
改成 `dw = beam_r * 2.15` 后立刻改善。

---

## [051] 横向苗必须**斜跨**，垂直的苗只是横档

百科原文："巨木**纵横**相贯、交错搭置"。
把横向苗做成垂直于桥轴的横档，网格感出不来。
改成每道苗沿 x 方向偏移 `skew = width * 0.34`（斜跨）后，
才形成菱形网格。

---

## [052] 竖杆会把编木拱变成"三角形桁架"

早前在拱背与桥面之间放了一圈 **4 × 13 = 52 根整齐的垂直撑木**。
评审直接判：

> "结构表现为简化的支墩式三角桁架结构"
> "垂直支撑的三角形桁架"

真实的虹桥在这个空间里是**斜撑交织的腹架**。
改成斜撑 + 苗顶短垫木后，"桁架"读感消失。

> **教训**：桁架是"规整杆件 + 直角"的美学；编木是"错位 + 斜向 + 咬合"的美学。
> 加一根整齐的竖杆，就足以让整个形制读错。

---

## [053] 同色构件在渲染里糊成一片 —— 多体系必须分色

几百根同色圆木叠在一起，评审完全读不出结构层次。
给三套体系各配一种木色：

| 体系 | 材质 | 颜色 |
|---|---|---|
| A 三节苗 | `mat_a` | 深褐 (0.24, 0.13, 0.07) |
| B 五节苗 | `mat_b` | 浅黄褐 (0.62, 0.42, 0.22) |
| 横向苗 | `mat_miao` | 中性灰 (0.46, 0.44, 0.40) |

评审原话："使用颜色区分两套体系是有效的"。
这是**古建测绘图**区分结构体系的老办法，渲染里同样成立。

---

## [054] 灰模视图不能用单一灰

Workbench 灰模原本 `color_type = 'SINGLE'`，几百根构件刷成一片，
评审说"彩陶渲染图细节显示结构过于简化和平滑"。
改成 `color_type = 'RANDOM'`（按物体随机着色）后，
评审说"clay 视图由于采用随机着色，也呈现出'编织'的结构特征"。

灰模仍然是"无材质无灯光"的纯形体证据，只是不同构件能区分开。

---

## [055] 节点必须看得出是接头

评审原话：**"拱肋为长弧形直木，非短段折线木"**。

三节苗 / 五节苗的关键是**短木首尾相接**。节点不显眼，
两根短木在渲染里就看成了一根长弧木。
故把"牛头"加粗加长（半径 ×1.45、长 ×1.45），
并另加一道更粗的**麻绳箍**（半径 ×1.62）标出接头位置。

---

## [056] 正交取景：`ortho_scale` 映射到渲染的**长边**

Blender 的 `ortho_scale` 对应渲染的**长边**（本项目横图 = x），
短边的可视范围 = `ortho_scale × (ry / rx)`。
原来写 `max(w, h)` 没做换算，横图上竖向会被裁掉。

实测：虹桥 `right` 视图 ortho=10.67 → 短边只显示 7.11m，
而桥高 8.43m —— **被裁**，kimi 独立指出"right 视图被裁切"。
改为 `max(需宽, 需高 × rx/ry)` 后 ortho=14.67，6/6 图无裁切。

配套工具：`probes/check_crop.py` —— 扫渲染图四边，
看是否有非背景像素触边（细节大样 `detail` 是**故意**裁切，列入白名单）。

---

## [057] 取景的边距是**乘数**不是除数

相机拟合公式写成：

```python
_need = abs(_q.x) / (_tan_x * margin) - _depth      # ❌
```

除以 margin 等于**放宽**取景，主体可以溢出画面。
正确的是：

```python
_need = abs(_q.x) * margin / _tan_x - _depth          # ✅
```

主体要留 margin 的余量，就要求深度 ≥ margin × |q.x| / tan_x。

另外 `_need` 是"还需要再退多远"，必须**累加**到当前距离上，
不能每次从初始距离重算（那样等于把已退的距离丢掉，迭代不收敛）。

---

## [058] 非正交的固定机位也要自动取景

正交四视图有精确框选，但新增的 `under`（桥下仰视）是透视，
一开始写死了相机位置 —— 模型一变宽就左右触边。
给它补上同样的拟合循环，并**只退不进**
（允许拉近时，循环会把相机推到包围盒外，构图反而垮掉：实测 dist 从 15 涨到 34）。

---

## [059] 证据集要补两个机位

| 机位 | 作用 |
|---|---|
| `under`（侧下方仰视拱底） | 唯一能看清**三维编织**的角度。正交侧视里各肋完全重叠，只剩两条折线 |
| `detail`（拱顶局部大样，正交 3/4） | 别压咬合是**亚米级**细节，整桥 900px 画面里读不出来。这正是建筑做法图"节点大样"的作用 |

---

## [060] **评审提示词里绝不能写死实测数字**

这是本轮最隐蔽的一个坑。

评审提示词里写了上一版的"跨度 22.0m、起拱 3.27m、梁半径 0.30m、三组梁"，
于是 kimi 的 `visible_features` **在复述我的数字**而不是读图：

> "桥面拱矢约3.27m"、"梁截面半径约0.30m"、"第3组梁与第4组梁约3.54m"

它据此判了 PASS —— **这个 PASS 是假的**。
改成从场景实时量取（`ai_loop.Session` 里跑一段探针，把实测值注入提示词）后，
kimi 立刻改判 `"is_guan_mu_gong": "no"`。

> **教训**：给评审的任何数字，只要是从上一版抄来的，就是污染。
> 实测值必须**现场取**，并明确写"供你核对，不要当成结论"。

---

## [061] Windows 控制台是 GBK，评审输出会炸

评审返回的 JSON 里带 `✓` 之类字符时，
`print(t)` 直接抛 `UnicodeEncodeError: 'gbk' codec can't encode character`，
**把整轮结果截断**（kimi 的结论就是因此没打出来）。
解法：`sys.stdout.buffer.write(txt.encode("gbk", "replace"))`。

同理，本仓库所有脚本打印中文都要能扛住 GBK。

---

## [062] 想"看"参考图但没有视觉能力时，用字符图

会话里的图像查看通道不可用（provider 405），但**ascii_map 工具能用**：
把图缩到终端宽度，用明暗映射成字符。这是本轮读参考图、
读自己渲染图的主要手段。

拿参考图的做法（可复用）：
1. Wikimedia Commons API 按分类/关键词找文件
2. 下载到 `out/ref/`
3. `view.ascii_map()` 输出字符图
4. 切块放大看局部（`probes/ref_crop.py` / `probes/park_view.py`）

本轮用这个方法拿到了：虹桥复原实景照（清明上河园）
与《清明上河图》细节，用于核对形制。

---

## 本轮结果

```
qwen3.5-plus : is_guan_mu_gong=yes  no_pier=yes  weaving=yes  arch_rise=yes
               missing_features=[]      problems=[]
kimi-k2.5    : is_guan_mu_gong=yes  no_pier=yes  weaving=yes  arch_rise=yes
```

模型参数：净跨 20.0m / 桥面宽 8.0m / 拱矢 5.0m（与唐寰澄推算一致），
4 对肋 ×（三节苗 + 五节苗），横向斜苗 11 道，475 个构件，**河中无桥墩**。

---

## 待验证 / 下一步

- [x] `get_viewport_screenshot` —— **不可用，见 [011]**
- [x] 驱动端接哪种模型 —— **qwen3.5-plus / kimi-k2.5 能看图，见 [040]**
- [x] 跨轮固定检查相机 —— **已实现并验证，见 [038]**
- [x] 独立交叉评审 —— **已实现并量化，自检虚高 2.3 分，见 [039]**
- [x] 分构件族尺寸喂评审 —— **已实现，见 [043]**
- [x] 形制助手 `curved_roof()` —— **见 [025]/[030]/[035]/[037]**
- [x] 形制助手 `dougong()` —— **已实现，见 [044]**
- [x] 瓦垄几何（反宇可读性）—— **已实现，见 [047]**
- [x] 增量修改 —— **已实现，见 [045]**
- [x] 快照/回滚 —— **已实现，见 [046]**
- [x] 终端字符图 —— **见 [032]**
- [x] 五通道证据渲染（含灰模）—— **见 [036]**
- [x] **贯木拱虹桥**（《清明上河图》核心结构）—— **已实现，见 [048]-[055]/[063]-[066]**（两组拱骨系统 三节苗/五节苗 穿插别压 + 38° 人字形斜跨横向苗）
- [x] **白模导出（彩模/灰模/深度/法线）** —— **已实现并自检通过，见 `EXPORT.md` + [067]-[072]**
## [063] 视觉评审的**轮间方差**足以推翻结论

同一张图、同一套提示词，问 4 次同一个模型：

| 模型 | 4 轮结果 |
|---|---|
| qwen3.5-plus | 2/4, 2/4, 4/4, 2/4 |
| kimi-k2.5 | 4/4, unclear, 4/4, 2/4 |

**"4/4 通过"出现过 3 次，"2/4"出现过 5 次** —— 也就是说
**一轮的 PASS 有很大概率是运气**。

早前把某次 4/4 当成"结构已达标"的结论，是错的。
规则：
- 判断达标必须**多轮取多数**，单轮结果只能当线索；
- 报告结论时必须写清"n 轮里的 m 轮"，不许写"通过了"；
- 评审方差本身要**量化后写进报告**，不能只报最好的一轮。

工具：`probes/test_judge_variance.py --rounds N`。

## [064] 当评审信号只有 2 bit 时，**不要拿它调几何**

见 [063]：判定项只有 `is_guan_mu_gong` / `no_pier_in_river` /
`weaving_visible` / `arch_rise_visible` 四个 yes/no。
在 4 个候选几何配置之间，2/4 和 4/4 的分布互相重叠 —— **信噪比不足以判优**。

实测四版配置的 4 轮结果：

| 配置 | qwen3.5-plus | kimi-k2.5 |
|---|---|---|
| 苗 19° 单斜 / 空隙大 | 2/4×3 | 4/4×2, 2/4×1 |
| 苗 38° 单斜 / 空隙中 | 2/4×4 | 4/4×1, 2/4×3 |
| 苗改木色 / 删斜撑层 | 2/4×3 | 2/4×3 |
| 苗 38° 人字 / 空隙最小 | 2/4×4 | 4/4×2, 2/4×2 |

qwen 在全部 19 轮里只有 1 轮判 yes —— 这是**稳定的分歧**，不是噪声。

规则：
- **几何上的硬约束**（构件会不会互相穿插、会不会戳穿、端头会不会出桥）
  用代码判定，不问模型；
- **观感**（像不像、读不读得出来）才问模型，而且要多轮；
- 两个信号冲突时，**信代码**。评审意见只用来"发现候选问题"，
  不用来"证明改动有效"。

## [065] 评审说"结构叠置/像常规木构"时，先查**桥面与拱背的空隙**

虹桥评审反复出现"上下叠置""抬梁加斜撑框架""结构不完整"。
一开始误以为是腹架形式不对（删了竖撑、又删了斜撑、还把苗改成木色），
三次都让分数变差 —— 方向全错。

真正的变量是 **桥面底与拱背包络之间的净空 `clear`**：
- 净空大 → 桥面和拱背像两层叠起来的构件 → "上下叠置"；
- 净空小 → 读成一个密实的木构整体。

真实虹桥的桥面是**紧贴着木料**铺的。

顺带纠正一个错误推断：`profile = max(A, B)` 是两套系统的**包络**，
编织永远在包络**之下**，所以"编织被桥面遮住"这个判断是错的
（clear 再大也遮不住它）。错的推断会导致去调一个不存在的参数。

规则：**先算清变量的几何含义，再改**；不确定时先做"清场对照实验"，
一次只动一个变量。

## [066] 横向构件要"斜跨"，倾角必须够大才看得出来

评审原话："横向苗木与桥轴线垂直，未体现斜跨桥面"。
建模时确实做了斜跨，但 `skew = 宽 × 0.34` → 倾角只有 **19°**，
在正视投影里和垂直没区别。

- 倾角要 **35° 以上**才在正视图里读得出"斜"；
- 单向斜跨时，末道苗会**伸出桥外数米**（20m 跨、8m 宽、偏 6.2m 时出界 5m）；
  改成**相邻苗反向斜跨（人字形）**，端头收得住，而且相邻苗互相交叉，
  天然形成菱形网。

## [067] 自检的采样点会被**遮挡**污染

导出深度/法线后要验证，第一版取"网格面中心 → 投影回像素 → 读值"。
在密集结构（475 根木构件）上**必然**读到遮挡物的数据：

- 深度误差最大 **51 m**、法线误差 0.24；
- 而且改法线颜色、改腹架形式都改不动 —— 因为误差根本不是模型造成的。

正确做法：**反投影求交**。对每个像素自己算世界射线，
`scene.ray_cast` 拿到渲染时真正命中的点和面法线，再逐点比对。
与遮挡无关，改几何后误差会立刻跟着变。

## [068] `camera.view_frame()` 的角点**顺序**不可靠

用 `cam.data.view_frame()` 四个角点插值算像素射线，角点顺序猜错时
**220 个采样像素只命中 52 个**，深度误差 51m。

改用**显式内参**自己算：

```
hw = sensor_width/2 / lens          # 归一到"焦距 = 1"
hh = hw / (W/H)      # sensor_fit=AUTO 且横向时
x = (2*(px+0.5)/W - 1) * hw
y = (1 - 2*(py+0.5)/H) * hh
d_world = (cam.matrix_world.to_3x3() @ Vector((x, y, -1))).normalized()
```

并加**自检**：画面中心的射线必须与相机光轴重合（余弦 ≈ 1）。

## [069] 节点建好但**没连线**，输出看起来完全正常

`ShaderNodeVectorTransform` 的 Vector 输入没接（保持默认 (0,0,0)），
整张法线图是**均匀的 0.5 灰** —— 文件正常写出、尺寸正常、报告"导出成功"，
但内容全错。错误码表现为误差 ≈ 0.5 × |真值|。

规则：**每个节点都要检查它是不是真的接上了**，不能只看"渲染成功"。
顺带：`Geometry` 节点的 `Normal`（着色法线，圆柱上会平滑插值）
和 `True Normal`（面法线）不是一回事；自检要和 `ray_cast` 对齐就用
`True Normal`。

## [070] 深度图是 `[near,far]→[1,0]` 的**线性**映射，far 必须收紧

Blender 默认 `clip_end` 是 1000m 级（本机 282.9m），
深度图把这段线性映射到 0..1，far 拉得越大深度图越没法用。

导出时按**相机到所有几何的最远距离 × 1.15** 收紧 near/far，导完还原。
另外深度残差要用**"折合像素"**看（误差 ÷ 像素足迹）：
75m 外 50mm 镜头，一个像素在物体上 4.3cm，掠射圆柱面上
一个像素内深度就变好几厘米 —— 用米看会误判成"深度图坏了"。

## [071] `Vector Transform(CAMERA)` 的 Z 与 `cam_inv.to_3x3()` 真值**相反**

相机空间法线的真值是 `cam_inv.to_3x3() @ n_world`（**只用 3x3 旋转部分**，
用 4x4 会混入相机平移，真值全错）。
Blender 的 Vector Transform 转到 CAMERA 后，Z 与该真值相反，需要翻转。

但**不要靠记忆**：两种约定各渲一张，用真值判定，自动选。
实测：不翻 |dz| = 0.599，翻转后 |dz| = 0.019。

另外判别指标要**分通道**：用 `max(|Δ|)` 时 X/Y 的误差会盖住 Z，
两种约定给出**完全相同**的数字（实测都是 0.6963），根本分不出来。

## [072] 还原场景的代码必须放在 `finally` 里

`blender_export.py` 早期把 `restore()` 放在正常路径末尾。
中途一次 `NameError`（异常抛在 `restore()` 之前）就把
`view_layer.material_override` **永久留在了场景里**，
而且**没有任何报错** —— 之后每一次渲染都被 override 材质污染，
画面看起来"有点灰"但没人知道原因。

排查花了很久才定位到：现象是"导出脚本跑了十几遍，材质列表里堆了
31 个 `EXPORT_*`，而 override 指向的是一个早就该没用的材质"。

规则：
- 凡是"临时改场景 → 做事 → 还原"的脚本，**还原必须放 `finally`**；
- 临时建的材质/物体，事后要**清理**（0 用户就删），否则会越堆越多；
- 加一条**故障注入回归测试**：在中间人为 `raise`，
  然后断言场景状态没变 —— `probes/test_export_failpath.py`。

## [073] 写给 Blender 执行的 .py **不能带 BOM**

用 PowerShell 的 `Set-Content -Encoding UTF8` 写脚本会写入 UTF-8 BOM，
Blender 的 `exec(code, namespace)` 直接报：

```
SyntaxError: invalid non-printable character U+FEFF
```

报错位置在第 1 行、报的是"不可打印字符" —— 很容易误以为是脚本内容坏了。

规则：写给 Blender 执行的 .py 一律用**无 BOM 的 UTF-8**
（编辑器的 Write 工具、或 `Set-Content -Encoding utf8NoBOM`）。
同理，**别在 PowerShell 里内联多行 Python**：
中文和引号会被重新解析，实测把 `say("中文")` 改成乱码、
三引号直接语法错误。
一律写成 .py 文件再执行。

## [074] 服装必须先过隔离灰模闸门，再做 lookdev

当前女侠渲染中，直接看 hero 图很容易把袖子、裙片、披帛误认成
身体或道具。按 `blender-visual-craft` 的角色连接检查，先输出
`cloth_front/right/back/only/clay`，分别看服装与身体的关系、服装自身
轮廓和遮挡后的连接，再进入材质与灯光阶段。

**证据**：`task_warrior_clothing.py` 实跑输出 5 张隔离图。

## [075] 穿模不能只靠视觉评审，要加数值间隙检查

AI 评审只说“裙摆与腿穿插”，没有深度和位置。把裙子、袖子顶点与
肢体轴线/半径比较后，第一轮测得裙-腿最小间隙 **-35.5mm**；
重排裙褶、裙面和大腿参数后为 **+6.5mm**。负值才是穿入，正值表示
至少有几何余量。当前仍有袖子与上臂的保守命中，不能宣称完全无穿模，
需在袖口遮挡灰模中继续确认。

## [076] 装饰褶线必须贴着服装表面生成

直接按世界坐标放裙褶会让褶线穿进前腿 28–32mm。褶线应由服装截面
的角度、高度和外推量生成，跟随裙面，而不是凭 x/y 坐标摆放。

**证据**：修正后 `SkirtPleat_*` 不再出现在最深穿模明细中。

## [077] “漂亮渲染”要与结构证据分阶段

先用低成本固定机位确认轮廓、连接、遮挡和重心，再投入高分辨率、材质、
Cycles 或视频序列。视频编码成功不等于角色成立；主图、灰模、隔离图和
转台必须对应同一个已检查的工程版本。

## [078] Blender 5.2 当前构建没有 FFMPEG image format

尝试在 `warrior_turntable.py` 里直接设置
`scene.render.image_settings.file_format = 'FFMPEG'`，Blender 5.2
实际报 enum 不存在，支持列表只有 PNG、OPEN_EXR、TIFF 等图像格式。
处理方式：Blender 只负责输出 PNG 序列，外部 `d:\\qt5\\bin\\ffmpeg.exe`
负责编码 H.264 MP4。不能仅凭“Blender 支持视频输出”的旧经验猜测当前构建。

## [079] Blender 5.2 Action API 不再保证旧版 `action.fcurves`

转台脚本访问 `cam.animation_data.action.fcurves` 时后台实跑报
`AttributeError: 'Action' object has no attribute 'fcurves'`。本轮没有
依赖旧 Action API，而是逐帧插入相机关键帧后直接渲染动画。若以后需要
修改插值，应针对 5.2 的 slots API 单独探测，不能照抄旧版脚本。

## [080] 转台视频必须保留 PNG 序列作为可复查中间产物

6 秒、24fps 的转台已实际输出 **144 帧**，再编码为
`out/warrior_turntable.mp4`（1,736,784 bytes）。同时保留
`out/warrior_turntable_frames/`，这样视频编码失败或画面有问题时可以
逐帧回查，不把 MP4 文件存在当成画面通过。

## [081] lookdev 只改变展示层，不应覆盖结构闸门证据

`warrior_lookdev.py` 在服装隔离检查之后运行，创建独立 `Lookdev`
集合、摄影棚背景、暖主光/冷补光/轮廓光，并输出 hero/full/face 三张图。
lookdev 的漂亮材质不能替代 `cloth_*` 灰模、数值间隙和多视图检查；两类
产物必须分开归档并对应同一个 `.blend` 版本。

## [082] 隔离检查的隐藏状态不能流入正式工程

`task_warrior_clothing.py` 为了输出 `cloth_only.png` 会暂时隐藏身体。
如果当前 Blender 会话随后直接运行 lookdev，而 lookdev 不主动恢复
`hide_render` / `hide_viewport`，正式 `warrior_lookdev.blend` 就可能保存
成“下半身消失”。这是**场景状态污染**，不是建模几何丢失。

规则：隔离脚本结束（包括异常路径）必须恢复对象可见性；lookdev 开始时
也必须显式恢复人物网格可见。实测修复后：下半身网格 11 个、隐藏 0 个，
正式 lookdev 工程重新保存。

## [083] 正式工程保存前必须恢复展示机位

上一轮虽然恢复了下半身网格可见性，但 `warrior_lookdev.blend` 保存时
相机仍停在脸部特写机位，导致打开工程时腿部投影全部落在画面外；这会被
误判为“下半身消失”。验证方式不能只查 `hide_render`，还要查关键对象的
相机投影包围盒。修复后保存前强制恢复全身机位，并验证大腿、小腿、脚的
投影 `0<y<1`。

## [084] Blender Render Result 可能仍停在最后一张特写

即使正式工程的相机已恢复全身，lookdev 脚本如果最后一次调用是脸部
特写，Blender 界面的 Render Result 仍显示特写图，用户会看到“没有下半身”。
因此脚本必须在保存前再渲染一次明确命名的 `FINAL_FULL_BODY.png`，并把
正式相机恢复到同一全身机位。不能只验证 `.blend` 里的相机位置。

## [085] 摄影棚地面厚度也会遮掉下半身

最终查明“对象存在、相机也在画面内，但 PNG 看不到腿”的真正原因：
`warrior_lookdev.py` 用立方体做地面，旧参数 `scale=(5,5,1)` 使地面顶面
达到约 `z=0.988`，人物膝盖以下全部被地面遮住。只查对象可见性和相机投影
仍会误判通过，因为遮挡物本身没有被检查。

修复：地面改成薄板 `scale z=0.01`；最终诊断渲染还暂时隐藏地面、墙和原始
Ground，生成无环境 `FINAL_FULL_BODY.png`，并保存到正式工程。以后构图检查
必须包含遮挡物深度检查，不能只做 2D 投影包围盒。

## [086] 复杂场景先写视觉约定再参数化搭建

修仙坊市第一版先写 `cultivation_market_brief.md`，锁定入口—主街—灵泉—
主殿的空间层级、暖店铺光/青灵泉光/紫符阵光和必须出现的识别点，再用
语义对象名生成。这样“复杂”由可读的空间关系构成，而不是单纯堆 207 个
方块。正式验收保留 hero、front、right、detail、clay 五张图；灰模不通过
时不进入更高成本的动画和细节制作。

## [087] “宏伟”首先是镜头与尺度关系，不是对象数量

坊市第一版只有 207 个网格时，增加摊位并没有自动产生宏伟感。升级主图时
加入两侧巨型塔楼、远端高台主殿、多层悬桥、空中灵脉环和前景灯柱，并把
镜头改为较远的低机位广角；对象数从 207 增到 353。验收重点是入口—主街—
灵泉—主殿的轴线、前中后景和尺度参照，而不是 353 这个数量本身。

## [088] 中国古典建筑必须表现构造语汇

坊市宏伟版的体块虽然拉开了尺度，但原建筑仍像现代方盒子：两片斜板不能
替代中国屋顶，巨柱加横梁也不能替代牌楼或殿堂。古典建筑升级后按
“台基 → 柱网 → 梁架 → 斗拱 → 出檐 → 坡屋顶 → 正脊/垂脊 → 格栅/匾额”
生成，店铺改为三开间街屋，主殿改为五开间重檐，高大尺度与中国构造逻辑
分别负责宏伟和文化识别。证据：`market_classical_hero.png`、
`cultivation_market_classical.blend`，建筑网格数 806。

## [089] 宗门巡游要先有空间路线，再做特效

第一版宗门巡游以 9 个镜头节点建立高空接近—山门—演武场—丹器峰—藏经阁—
主峰—升空离开的路线，保存为 720 帧、24fps 的相机动画。先输出高空、山门、
主峰和离开四张证据图，再决定是否投入全动画渲染；这样可以先验证空间叙事，
避免云雾和粒子掩盖路线问题。证据：`task_xianmen_tour.py`、
`out/xianmen_sect_tour.blend`。

## [090] 用亮度直方图做动画分段体检

宗门巡游首版预览渲染后，逐帧统计中位亮度，发现 341–371 帧（器峰段）
和 701–711 帧（离场段）中位亮度低于 8，画面几乎全黑。原因是三盏主光
都在主峰一侧，丹峰/器峰完全没有被照到。补五盏分区补光、提高环境底光，
并把器峰机位拉远抬高后复测，近黑帧归零，明暗曲线呈现
山门暗 → 主峰最亮（118）→ 离场回落的节奏。

规则：长动画先出低分辨率预览，再用**逐帧亮度统计**找出死黑段，
比逐帧看图快得多，也不能只看首尾两张就认为通过。

## [091] 体积雾必须按空间区域限制范围

第一版效果层用两个大体积立方体覆盖整座宗门，导致中景对比度降到约 9.7、
离场段约 7.3，主体几乎被雾洗平。把雾拆成山脚外围局部雾团、山门雾和
高空薄云后，关键帧对比度恢复到丹峰 48.7、主峰 137.3、离场 154.3；
加入效果层后的 720 帧预览仅有 0 个中位亮度低于 8 的死黑帧，只有 1 帧
接近低对比阈值，仍需正式片逐段抽检。

规则：云雾是构图层，不是全场景滤镜；必须避开主街和关键建筑，且每种效果
放在可关闭的独立集合中。

## [092] 军舰外形必须先从船体截面开始

055 第一版用多个方块叠成“舰体”，虽然有炮塔、桅杆和雷达，却没有尖艏、
舭部折线、船腰和收艉，视觉上不像军舰。重建版改用 8 个沿舰长方向的横截面
放样成连续船壳，再加甲板、斜收上层建筑和设备。验收顺序固定为：侧视舰体
轮廓 → 俯视线型 → 艏视宽度/吃水 → 上层建筑和设备；不能用设备数量掩盖
基础船体失败。

## [093] 055 外形重建先锁定真实长宽比

上一版模型的舰体比例约为 5:1，视觉上短胖；公开资料约束的舰长/舰宽约为
180/22，接近 8:1。重建 v2 把船体尺度改为 180m × 22m，使用 10 个横截面
生成连续尖艏、船腰、舭部和收艉，并将舰炮、VLS、舰桥、烟囱和直升机甲板
放到甲板高度上。必须先审核 `type055_v2_side/bow/top` 三视图，再继续做
材质和细节；“有武器”不能证明“像军舰”。

## [094] 055 三视图不通过时，必须继续重做整体而不是加设备

v2 仍被反馈“不像”，说明长宽比修正只是必要条件，不是充分条件。v3 继续
把舰体甲板线、舰艏上翘、舷侧折角、舰艏护舷、前后上层建筑比例作为第一优先，
并把武器设备保持为低矮、贴甲板的轮廓组件。当前输出 `type055_v3_side/bow/top`
作为下一轮人工/视觉审查依据，不能仅凭脚本成功和对象数量宣称通过。
