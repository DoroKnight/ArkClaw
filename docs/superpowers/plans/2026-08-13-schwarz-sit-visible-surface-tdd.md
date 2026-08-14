# Schwarz Sit 尾巴完整显示与任务栏脚部覆盖 TDD

## 1. 目标

只修正 Schwarz 的 `Sit` 动画：

1. Sit 全周期内尾巴不得被固定 `160 x 180` 身体窗口裁剪；
2. Sit 脚部允许越过任务栏上沿，并显示在任务栏区域之上；
3. 保持当前 Sit 身体位置、屁股接地点和窗口落地点不变；
4. Relax、Move、Sleep、Special、Interact 的布局和播放行为必须与修正前一致。

本计划只定义测试、最小实现边界和验收门禁。在本计划获确认前，不修改生产代码。

## 2. 已确认的根因与测量证据

当前所有非 Special 动作都使用 `RenderContainmentPolicy.BODY_PRIORITY`。该策略始终返回
固定的 `160 x 180` BODY 表面，因此超出身体窗口的 Sit 网格会在 OpenGL viewport 边缘被裁掉。

对本机经过 SHA-256 校验的 Schwarz Spine 3.8 资源进行 60 Hz、包含首尾帧的 Sit 全周期采样，得到：

```text
Sit Spine union bounds:
x      = -278.8448486328125
y      =  -78.73991394042969
width  =  399.77774810791016
height =  351.7436065673828

Relax calibration bounds:
x      = -170.41197204589844
y      =   -1.9676189422607422
width  =  255.40875244140625
height =  400.436185836792
```

使用当前生产校准 `target_height=162`、`foot_baseline=180` 投影后，Sit 的身体局部可见包络为：

```text
left   = -15.5314137629547
top    =  68.7579243590932
right  = 146.2022094313230
bottom = 211.0589108317310
```

因此当前 BODY 表面会裁掉：

- 左侧约 `15.53` 个逻辑像素，正是截图中缺失的尾巴末段；
- 底部约 `31.06` 个逻辑像素，正是没有进入任务栏区域的脚部。

加入现有的 2 像素抗裁剪 padding，并执行向外取整后，右朝向 Sit 所需的身体局部表面为：

```text
left=-18, top=66, right=149, bottom=214
surface size = 167 x 148
```

本机 Qt 显示器几何为：

```text
full screen geometry = (0, 0, 1707, 1067)
available workspace  = (0, 0, 1707, 1019)
DPR                  = 1.5
taskbar logical height = 48
```

当前身体窗口底边位于 `available workspace.bottom`。Sit 内容只需向下延伸约 31.06 像素，
加 padding 后表面底边向下延伸 34 像素，仍小于本机任务栏的 48 逻辑像素，能够完整显示且不会越出物理屏幕。

## 3. 借鉴 ArkPets，但不直接复制实现

ArkPets 的相关设计位于：

- `D:\ArkPets\Ark-Pets\core\src\cn\harryh\arkpets\ArkChar.java`
- `D:\ArkPets\Ark-Pets\core\src\cn\harryh\arkpets\render\DynamicOrthographicCamara.java`
- `D:\ArkPets\Ark-Pets\core\src\cn\harryh\arkpets\ArkPets.java`

其核心机制是：

1. 对每个动画阶段采样透明度覆盖范围；
2. 为每个阶段缓存独立的 camera insert；
3. 动作切换时改变画布包络，而不是用逐帧骨骼 bounds 改角色世界位置；
4. 窗口落地点和角色画布尺寸分别管理。

ArkClaw 已经具有等价基础设施：`sampled_action_bounds`、纯布局规划器、OVERFLOW 表面和输入代理。
因此最小实现应复用现有 OVERFLOW 机制，只增加 Sit 专属 containment policy，不移植 ArkPets 的
LibGDX/FBO 实现，也不改动 Spine 素材。

## 4. 冻结的不变量

### 4.1 Sit 不变量

设身体窗口位置为 \(P=(x,y)\)，大小为 \(160\times180\)，任务栏上沿为
\(G=workspace.bottom\)。修正前后必须满足：

\[
y + 180 = G
\]

Sit 布局必须满足：

- `resolved_body_position == Point(x, y)`；
- `ground_correction == 0.0`；
- `scale_multiplier == 1.0`；
- `effective_facing == requested_facing`；
- 身体基线的桌面坐标仍为 `G`；
- 不写回 `PetMotionModel.position` 的新 Y 值；
- 不更改 manifest 的 `foot_baseline=180`；
- 不增加 Sit 骨骼、root 或动作级 Y offset；
- 不改 Sit 动画混合时长、播放速度、循环和 Track 0 语义。

### 4.2 非 Sit 零回归不变量

以下动作修正前后的公共布局结果必须相等：

- `IDLE` / Relax；
- `WALK_LEFT`、`WALK_RIGHT` / Move；
- `SLEEP`；
- `SPECIAL`；
- `INTERACT`。

相等字段包括：`mode`、`surface_rect`、`body_window_offset`、
`resolved_body_position`、`ground_correction`、`effective_facing`、
`scale_multiplier` 和 `quality`。

## 5. 确认后采用的测试 seam

测试只穿过以下公共 seam，不测试私有 helper，也不 mock ArkClaw 内部类：

1. **纯布局 seam**：`plan_pet_render_layout(...) -> PetRenderLayoutResult`；
2. **渲染器 seam**：`Spine38PetRenderer.set_state()`、`plan_layout()`、
   `set_render_layout()`、`update()`；
3. **Qt 组合 seam**：用户请求 Sit 后，由 `PetWindow` 发布 BODY 或 OVERFLOW 表面；
4. **真实资源 seam**：通过正式 manifest、DLL 和 Schwarz 素材运行 Sit 全周期 smoke；
5. **人工视觉 seam**：正式启动器打开桌宠，观察 Sit 任务栏覆盖效果。

## 6. 目标设计

新增一个语义明确的 Sit containment policy，例如：

```text
SIT_FULL_SAMPLED_BOUNDS
```

该策略和 Special 的 `FULL_SAMPLED_BOUNDS` 不是同一个语义：

- Sit 必须使用完整采样包络和 OVERFLOW 表面；
- Sit 禁止 lift、缩放、换向和改变身体位置；
- Sit 表面可以越过 `availableGeometry().bottom`；
- Sit 表面不得越过对应 `QScreen.geometry().bottom`；
- 左右朝向分别使用镜像后的包络；
- 其他动作继续走原策略，不读取 Sit 的屏幕下边界参数。

Qt 层需要同时提供：

```text
workspace = QScreen.availableGeometry()  # 任务栏上沿/落地点
display   = QScreen.geometry()           # Sit 表面可占用的物理屏幕边界
```

两者不能混用：身体窗口仍以 `workspace` 落地，只有 Sit 的透明 OVERFLOW 表面允许延伸到
`display` 内。不得把所有动作的地面从 `availableGeometry` 改成 `geometry`。

## 7. Red-Green 垂直切片

### Slice 0：冻结现状和改动边界

#### Red 测试

在 `tests/unit/test_pet_render_layout.py` 增加真实测量字面量测试：

```python
def test_sit_real_envelope_currently_exceeds_body_surface() -> None:
    ...
```

断言右朝向 Sit 包络左边小于 `0`，底边大于 `180`。该测试记录缺陷输入，不把预期值由生产
算法重新计算出来。

增加非 Sit characterization 参数化测试，冻结五类动作当前的完整布局结果。

#### Green

本切片不改生产代码；缺陷描述测试通过，目标行为测试保持红灯。

### Slice 1：纯 Sit 扩展表面

#### Red 测试 1：右朝向尾巴和脚部完整包含

输入使用本机真实投影包络、`body=Rect(500,839,160,180)`、
`workspace=Rect(0,0,1707,1019)`、`display=Rect(0,0,1707,1067)`。

期望：

```text
mode                   = OVERFLOW
surface_rect           = Rect(482, 905, 167, 148)
body_window_offset     = Point(18, -66)
resolved_body_position = Point(500, 839)
ground_correction      = 0
scale_multiplier       = 1
effective_facing       = RIGHT
```

并验证：

```text
surface.bottom = 1053
workspace.bottom < surface.bottom <= display.bottom
surface.y + body_window_offset.y + 180 == workspace.bottom
```

#### Green 1

只实现 Sit policy 生成完整采样表面。不得复用会执行 lift、缩放或换向的 Special fit 分支。

#### Red 测试 2：左朝向镜像完整包含

断言镜像后的尾巴改为向身体窗口右侧扩展，朝向不改变，身体 X/Y 不改变。

#### Green 2

只补齐 Sit 镜像包络计算。

#### Red 测试 3：物理屏幕空间不足时失败关闭

当 `display.bottom < required_surface.bottom` 时，期望返回专属 typed failure，例如：

```text
SIT_DISPLAY_FLOOR_INFEASIBLE
```

不得静默裁脚、缩小角色、抬高屁股或改变世界 Y。该情形包括任务栏自动隐藏后物理屏幕没有
足够下方空间的极端配置。

#### Green 3

加入 display floor 校验，不改变现有 Special 的 16 像素 floor 规则。

### Slice 2：仅 SITTING 选择新策略

#### Red 测试

在 `tests/qt/test_spine38_renderer.py` 通过渲染器公共接口验证：

- `SITTING` 得到 OVERFLOW；
- viewport 改为 Sit 表面大小；
- transform 的桌面基线仍落在任务栏上沿；
- `origin_y` 只吸收 `body_window_offset`，不包含新的 ground correction；
- 真实 Sit 网格点全部落入 viewport；
- 左右朝向均完整。

另加参数化零回归测试：IDLE、WALK_LEFT、WALK_RIGHT、SLEEP、INTERACT 的布局继续为
原 BODY 结果；SPECIAL 的原 OVERFLOW 结果不变。

#### Green

在 `Spine38PetRenderer.plan_layout()` 中仅当：

```python
self._request.action is PetRendererAction.SITTING
```

时选择 Sit policy。Special 和默认分支保持原行为。

### Slice 3：Qt 任务栏覆盖组合

#### Red 测试

在 `tests/qt/test_pet_window.py` 通过用户请求 Sit 的公共操作验证：

1. 主身体窗口的 `geometry()` 在 Relax -> Sit -> Relax 全程不变；
2. Sit 时 OVERFLOW 窗口可见；
3. OVERFLOW 顶部/左右/底部等于布局结果；
4. OVERFLOW 底部大于 `availableGeometry().bottom`；
5. OVERFLOW 底部不大于 `geometry().bottom`；
6. `overlay.y + body_window_offset.y + 180 == availableGeometry().bottom`；
7. Sit -> Relax 时先重绘 BODY，再 retire OVERFLOW，不能出现一帧空白；
8. Relax、Move、Sleep、Interact 不创建新的 OVERFLOW 所有权；
9. Special 的已有 immutable composition 行为不变；
10. overlay 输入代理仍映射到原 `160 x 180` 身体窗口，尾巴和脚部扩展区域不扩大拖动热区。

#### Green

Qt 层只在当前请求为 `SITTING` 时向规划器提供对应屏幕的 full geometry。不得改变
`PetMotionModel`、窗口落地公式或其他动作的 workspace 选择。

### Slice 4：真实 Schwarz Sit 全周期像素门禁

#### Red 测试

新增 Sit 专用 opt-in smoke，不修改已有 Relax smoke 的断言。通过正式 manifest 和 native DLL：

1. 非循环设置 Sit，并按 60 Hz 采样 `3.333333` 秒，包含 `t=0` 与终点；
2. 每帧渲染到最终 Sit OVERFLOW viewport；
3. 读取每帧 alpha bounding box；
4. 每一帧非透明像素都必须位于表面以内，并保留至少 1 物理像素安全边；
5. 至少一帧 alpha bounds 进入旧 BODY 左边界之外，证明尾巴确实被保留；
6. 至少一帧 alpha bounds 进入旧 BODY 底边界之外，证明脚部确实被保留；
7. 所有帧的桌面基线恒等于任务栏上沿；
8. renderer safe code 始终为 `none`；
9. 重复三个 Sit 循环，循环边界表面尺寸和窗口位置不得变化。

测试不能只断言 mesh union；必须断言最终渲染图像的 alpha bounds，否则无法捕获 OpenGL viewport、
QImage 或 overlay 二次裁剪。

#### Green

只修复由真实 smoke 暴露的 Sit 专属表面提交问题。若需要改 OpenGL 公共代码，必须先证明改动由
`SITTING + OVERFLOW` 条件隔离，并重跑非 Sit characterization 门禁。

### Slice 5：多 DPI 与任务栏配置

自动参数化逻辑测试覆盖 DPR：

```text
1.00, 1.25, 1.50, 2.00
```

对每个 DPR 验证：

- 逻辑表面矩形不随 DPR 漂移；
- 物理 viewport 使用向上取整；
- alpha bounds 不接触物理 viewport 边缘；
- 不超过现有物理资源上限。

人工验收至少覆盖：

- 底部任务栏，100%、125%、150%、200%；
- 主屏和副屏；
- 负坐标屏幕；
- 任务栏自动隐藏开启/关闭；
- Always on Top 开启；若关闭时 Windows 任务栏遮住脚部，应记录为窗口 Z-order 限制，不得通过
  移动 Sit 或改其他动画来补偿。

## 8. 允许与禁止修改的文件

### 允许修改

生产文件仅允许在 Sit 条件分支内做最小改动：

- `src/arkclaw/application/pet_render_layout.py`
- `src/arkclaw/presentation/qt/spine38_renderer.py`
- `src/arkclaw/presentation/qt/pet_window.py`

测试和 Sit 专用诊断文件：

- `tests/unit/test_pet_render_layout.py`
- `tests/qt/test_spine38_renderer.py`
- `tests/qt/test_pet_window.py`
- 新增 Sit 专用真实资源 smoke/test 文件
- 本 TDD 文档

### 明确禁止修改

- Relax、Move、Sleep、Special、Interact 的动作映射与布局分支；
- `pet_animation.py`、`pet_motion.py`、`pet_action_sequence.py`；
- `pet_production_actions.py`、`pet_track0.py`、`spine38_player.py`；
- native Spine bridge；
- `.skel`、`.atlas`、`.png`；
- role manifest、`foot_baseline`、全局 scale、body calibration；
- Special 的 floor lift、缩放、换向和 immutable composition 规则；
- 所有非 Sit 动画的测试预期，除非只是新增“保持不变”的断言。

## 9. 测试执行顺序

每个 Slice 必须执行一次明确的 Red，再做最小 Green：

```powershell
$env:PYTHONPATH = (Resolve-Path '.\src').Path

.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider `
  tests\unit\test_pet_render_layout.py -q

.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider `
  tests\qt\test_spine38_renderer.py -q

.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider `
  tests\qt\test_pet_window.py -q
```

真实资源门禁通过正式启动器环境运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\start_schwarz_pet.ps1 `
  -ValidateOnly

# 实现阶段新增的 Sit 专用 smoke 命令放在此处；不得替换现有 Relax smoke。
```

最终回归：

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider `
  tests\unit\test_pet_render_layout.py `
  tests\unit\test_pet_production_motion.py `
  tests\qt\test_spine38_renderer.py `
  tests\qt\test_pet_effect_overlay.py `
  tests\qt\test_pet_window.py -q

.\.venv\Scripts\python.exe -m ruff check `
  src\arkclaw\application\pet_render_layout.py `
  src\arkclaw\presentation\qt\spine38_renderer.py `
  src\arkclaw\presentation\qt\pet_window.py `
  tests\unit\test_pet_render_layout.py `
  tests\qt\test_spine38_renderer.py `
  tests\qt\test_pet_window.py

.\.venv\Scripts\python.exe -m mypy src tests scripts packaging
git diff --check
```

## 10. 人工验收协议

通过正式入口启动：

```powershell
Set-Location 'D:\ArkClaw\.worktrees\arkpets-spine-idle-vertical-slice'
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\start_schwarz_pet.ps1 `
  -Console
```

固定执行：

```text
Relax -> Sit（三个完整循环）-> Relax
Move Left -> Sit（三个完整循环）-> Relax
Move Right -> Sit（三个完整循环）-> Relax
```

必须同时满足：

- 尾巴末端全程存在，没有齐边断口；
- 脚部越过任务栏上沿并显示在任务栏区域；
- 屁股仍坐在原任务栏上沿位置；
- 主身体窗口 X/Y 不发生跳变；
- Sit 循环边界不改变表面尺寸和身体位置；
- Sit 退出后 OVERFLOW 表面消失，无残影、空白帧或输入阻塞；
- Relax、Move 的外观、脚部贴地、移动速度和朝向与修改前一致。

建议录制包含任务栏、角色全身和动作菜单的 10 秒以上视频，并保留一张 Sit 中段截图作为人工证据。

## 11. 完成定义

只有以下条件全部满足才能宣布完成：

1. 每个 Slice 都留下过预期原因的 Red 证据；
2. Sit 真实全周期最终像素没有接触裁剪边界；
3. 尾巴和脚部都被真实像素证明确实超出旧 BODY，而不是只扩大了透明窗口；
4. Sit 的身体位置、基线、scale、facing 和 ground correction 保持冻结值；
5. 非 Sit characterization 测试全部通过；
6. 目标单元、Qt、真实资源 smoke、ruff、mypy、`git diff --check` 全部通过；
7. 人工验收在至少 150% DPI 的本机任务栏上通过；
8. Git diff 中不存在明确禁止修改的文件。

