# 白模导出说明（blender_export.py）

把当前 Blender 场景导出成**彩模 / 灰模 / 深度 / 相机空间法线**四件套，
供 ControlNet、几何重建、贴图烘焙等下游使用。

---

## 1. 怎么跑

```powershell
cd J:\mickeylan\ai\blender
D:\python3\python.exe .\blender_client.py .\blender_export.py
```

**必须经 `blender_client.py` 送进已经在跑的 Blender**，不能直接
`blender --python blender_export.py` —— 后者会另起一个进程，
拿不到当前场景（相机、材质、灯光全都没有）。

可调环境变量：

| 变量 | 默认 | 说明 |
|---|---|---|
| `EXPORT_NAME` | `scene` | 输出文件名前缀 |
| `EXPORT_W` | `1200` | 宽 |
| `EXPORT_H` | `900` | 高 |

跑完会打印一份自检报告，同时落到 `out/export/<name>_report.txt`。

---

## 2. 产出

| 文件 | 格式 | 内容 |
|---|---|---|
| `<name>_combined.png` | PNG 8bit | 彩模（EEVEE，带原材质） |
| `<name>_clay.png` | PNG 8bit | 灰模（Workbench，单色 + 阴影 + cavity） |
| `<name>_depth.exr` | OpenEXR 32bit float | 深度，线性 |
| `<name>_normal.exr` | OpenEXR 32bit float | 相机空间法线，线性 |
| `<name>_depth.npy` | float32 H×W×C | 同上（外层脚本直接读，免去 EXR 解码） |
| `<name>_normal.npy` | float32 H×W×C | 同上 |
| `<name>_manifest.json` | JSON | 相机矩阵 / 内参 / 分辨率 / 约定 |
| `<name>_report.txt` | 文本 | 自检报告（实测误差） |

### 深度约定

- 存的值是**归一化后的**：`(near - d) / (near - far)`，即近处→1、远处→0。
- 换回米：`d = near + (1 - v) * (far - near)`。
  `near`/`far` 记在 manifest 的 `near` / `far` 字段里。
- `near`/`far` 是**导出时按场景实际范围算的**（相机到所有几何的最远距离 ×1.15），
  不是 Blender 的默认 1000m。导出完相机的裁剪面会**还原**。

### 法线约定

- 相机空间，编码 `n * 0.5 + 0.5`（0..1），线性 EXR 里就是原值。
- 来源是 Geometry 节点的 **True Normal**（面法线，未插值）——
  和 `scene.ray_cast` 返回的是同一个量，所以能严格自检。
- **Z 需要翻转**：Blender 的 Vector Transform(CAMERA) 输出，
  相对真值 `cam_inv.to_3x3() @ n_world` 的 Z 是反的。
  脚本**不靠记忆**，两种约定各渲一张、用真值判定，实测选定。
- 翻转与否记在 manifest 的 `normal_convention.flip_z`。

### 真值公式

```
相机空间法线  n_cam = cam_inv.to_3x3() @ n_world     # 只用 3x3 旋转部分
沿光轴距离    d     = |(cam_inv @ P).z|
```

---

## 3. 自检怎么做的

不靠"肉眼看图对不对"，而是**反投影求交**：

1. 在画面上撒一批像素；
2. 对每个像素用**显式内参**算世界射线，
   `scene.ray_cast` 求交，拿到渲染时真正命中的点和面法线；
3. 把这个真值和导出的 EXR 在同一像素上的值逐点比对。

这样**不受遮挡影响** —— 早前用"网格面中心投影回像素"的做法在密集结构上
必然读到遮挡物的深度/法线，实测深度误差 51m、法线误差 0.24，完全对不上。

实测结果（本机，1200×900，50mm 镜头）：

| 指标 | 结果 |
|---|---|
| 法线 \|dx\| / \|dy\| | 0.035 / 0.032（编码单位，约 1.5°） |
| 法线 \|dz\|（翻转后） | 0.019 |
| 深度绝对误差中位 | 0.079 m |
| 深度折合像素中位 | 1.87 px（像素足迹 4.3 cm） |
| 深度误差 < 1 个像素足迹 | 27.7% |

深度残差的来源是**掠射面**：75m 外 50mm 镜头，一个像素在物体上约 4.3cm，
圆柱侧面一个像素内深度就变好几厘米。所以绝对误差要用"折合像素"看，
用米看会误判成"深度图坏了"。

---

## 4. Blender 5.2 上踩过的坑（都已在本脚本里规避）

| # | 坑 | 现象 | 规避 |
|---|---|---|---|
| 1 | 合成器 Group 里拿不到渲染 pass | Render Layers 的 Depth/Normal 槽读到全 0 | 一律用**材质驱动 + `view_layer.material_override`**，不进合成器 |
| 2 | 材质节点不能按名字取 | `nodes.get("Principled BSDF")` 返回 None | 按 `node.type` 找 |
| 3 | **Vector Transform 没接输入** | 整张法线图是均匀的 0.5 灰，但"看起来导出成功" | 必须 `geo.outputs["True Normal"] → vt.inputs["Vector"]` |
| 4 | Vector Transform 的 CAMERA 的 Z 与真值相反 | 法线 dz 误差 0.60（应 0.019） | 渲两版用真值判定，自动选 |
| 5 | `read_factory_settings()` | 插件被重置，9876 端口不再监听，**MCP 通道直接断** | 手动清场；导出脚本只改不删 |
| 6 | `camera.view_frame()` 角点顺序不可靠 | 220 个采样像素只命中 52 个，深度误差 51m | 用显式内参（lens/sensor/宽高比）算射线 |
| 7 | 深度用合成器 pass 不准 | —— | 用 `Camera Data → View Z Depth`（正值、线性、米） |
| 8 | EXR 线性、PNG 被 sRGB 编码 | PNG 深度要解码才有米制意义 | 深度/法线一律出 EXR + npy，PNG 只给彩模/灰模 |
| 9 | 深度图是 `[near,far]→[1,0]` 线性映射 | far 拉到 1000m 时深度图没法用 | 导出时按场景收紧 near/far，导完还原 |
| 10 | PowerShell 内联脚本里的中文/三引号 | `SyntaxError: unterminated triple-quoted string` | 一律写成 `.py` 文件再执行 |

---

## 5. 下游怎么用

**深度 → 米**

```python
import json, numpy as np
m = json.load(open(r'out/export/scene_manifest.json', encoding='utf-8'))
d = np.load(r'out/export/scene_depth.npy')[:, :, 0]
metres = m['near'] + (1.0 - d) * (m['far'] - m['near'])
```

**深度 → ControlNet depth（8bit 灰度）**

```python
d01 = 1.0 - (metres - m['near']) / (m['far'] - m['near'])   # 近=1 远=0
img = (np.clip(d01, 0, 1) * 255).astype(np.uint8)
```

**法线 → ControlNet normal**

```python
n = np.load(r'out/export/scene_normal.npy')          # 已编码 n*0.5+0.5，线性
rgb = np.clip(n * 255.0, 0, 255).astype(np.uint8)
# 若下游要求 OpenGL 约定（+Y 朝上）而不是 Blender 的 +Y 朝下：
# rgb = rgb[:, ::-1, :]
```

注意：ControlNet 的 normal 约定是 **OpenGL（绿通道朝上）**，
Blender 的相机空间是 **+Y 朝上**还是朝下取决于相机轴向，
接进去之前最好先确认一次；`manifest.json` 里的 `camera_matrix_world`
可以用来复算。

---

## 6. 不改场景

脚本会保存并还原：渲染引擎、输出路径/格式/位深、分辨率、视图变换、
合成器开关、film_transparent、`material_override`、相机的 clip_start/clip_end、
Workbench 着色设置。**不会**碰任何物体的材质槽、变换或可见性。
