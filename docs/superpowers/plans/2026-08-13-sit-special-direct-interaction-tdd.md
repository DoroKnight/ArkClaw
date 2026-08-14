# Schwarz Sit / Special 可选中、可拖动与即时切换 TDD

> 状态：自动化 Red-Green 已完成，等待 Windows 人工验收；仍不得修改动画资源  
> 日期：2026-08-13  
> 工作树：`D:\ArkClaw\.worktrees\arkpets-spine-idle-vertical-slice`

## 1. 目标与完成定义

本次只修复 Sit 与 Special 使用 OVERFLOW 顶层窗口时的输入和用户控制问题，保持当前已经验收正确的动画画面完全不变。

完成后必须同时满足：

1. Sit 和 Special 的可见角色像素可以被左键、拖动和右键命中；
2. 单击桌宠立即进入 Interact，不等待当前 Special 播放完成；
3. 左键移动超过系统拖动阈值后立即进入拖动状态，物理动画使用现有 Relax fallback；
4. 右键立即打开桌宠动作菜单，打开菜单本身不切换动画；
5. 从桌宠右键菜单选择动作后立即替换当前 Special；
6. 从系统托盘选择动作后立即替换当前 Special；`Resume Autonomous` 立即终止 protected epoch、清空 pending 并恢复 autonomous controller，由调度器决定下一动作；
7. OVERFLOW 表面的透明扩展区域继续鼠标穿透，不把透明矩形变成热区；
8. 已开始的左键手势离开初始热区、跨越窗口或触发动画切换后仍持续接收 move/release；
9. Relax、Move、Sleep 的视觉和语义不变；Sit 与 Special 的资源、构图和落点不变；
10. Windows 原生窗口和 Z-order 不因逐帧重复发布而重建/反复提升，菜单不被 OVERFLOW 盖住。

## 2. 已确认的证据与根因

### 2.1 基线

```powershell
$env:PYTHONPATH = (Resolve-Path '.\src').Path
.\.venv\Scripts\python.exe -m pytest `
  tests\unit\test_pet_explicit_action_control.py `
  tests\qt\test_pet_effect_overlay.py -q
```

当前结果是 `19 passed in 0.45s`。这只证明旧 BODY 矩形内的代理事件可工作，不能证明 Sit/Special 的真实可见像素可命中。

### 2.2 根因 A：热区仍固定为旧 BODY

`PetEffectOverlayWindow.show_layout()` 当前把 OVERFLOW 输入热区固定为
`body_window_offset + 160 x 180`。Windows `WM_NCHITTEST` 只在该矩形内返回
`HTCLIENT`，其余位置返回 `HTTRANSPARENT`。

Sit 的尾巴和脚部已经正确绘制到旧 BODY 外；Special 也使用更大的 OVERFLOW 表面。
OVERFLOW 又位于 BODY 之上，因此“看得见”与“点得到”使用了不一致的几何依据。

### 2.3 根因 B：TRAY 仍在等待 protected completion

`PetAnimationEngine._submit_production_intent()` 已给 `ActionSource.USER` 提供 protected
动作的直接替换路径，所以应用层的 `Special -> USER Interact` 已能立即成功。

但 `ActionSource.TRAY` 仍写入 `pending_explicit_action`，等 Special 完成后才消费；
`resume_autonomous()` 在 protected 动作期间也只设置 `resume_after_protected=True`。
这与“托盘动作要等 Special 播完”完全一致。

### 2.4 根因 C：同一 OVERFLOW 每帧重设窗口状态

`PetWindow` 每个 tick 发布当前布局；`show_layout()` 每次都执行 `setWindowFlags`、
`setGeometry`、`show` 和 `raise_`。Windows 上重复 `setWindowFlags` 可能重建顶层窗口，
重复 `raise_` 会持续改变 Z-order，使刚弹出的右键菜单可能被下一帧 overlay 盖住。

## 3. 最小目标设计

参考 ArkPets：

- `D:\ArkPets\Ark-Pets\core\src\cn\harryh\arkpets\ArkPets.java`
- `D:\ArkPets\Ark-Pets\core\src\cn\harryh\arkpets\ArkChar.java`
- `D:\ArkPets\Ark-Pets\core\src\cn\harryh\arkpets\animations\AnimComposer.java`

ArkPets 从最终帧读取鼠标位置 alpha：非透明像素接收左右键，透明像素把事件交给下层；
按下后由手势状态持续管理拖动。ArkClaw 不复制 Java/LibGDX 实现，只复用现有
`render_scene()` 已经产生的最终 `QImage`，禁止为了输入再渲染或 readback 一次。

### 3.1 命中模型

设 (B) 为旧 BODY 输入矩形，(A_t) 为当前已发布 OVERFLOW 帧的非透明像素集合，
本次向后兼容的热区为：

\[
H_t = B \cup A_t
\]

全局坐标映射到 overlay 局部坐标 (L) 后：

\[
\operatorname{hit}(L)=
\begin{cases}
\mathrm{HTCLIENT}, & L \in H_t \\
\mathrm{HTTRANSPARENT}, & L \notin H_t
\end{cases}
\]

保留 (B) 维持旧交互兼容性；增加 (A_t) 让 Sit 尾巴/脚部和 Special 可见像素可选中；
透明扩展区仍穿透。

alpha 命中阈值固定为：

\[
\alpha_{hit}=8/255
\]

不得针对不同动画、动作或颜色调整。设 \(G_t\) 为当前有效 render generation，只有 hit
snapshot 的 generation 与 \(G_t\) 相等时才允许使用 \(A_t\)。否则只使用 BODY fallback：

\[
H_t=
\begin{cases}
B, & \text{snapshot generation 无效} \\
B \cup A_t, & \text{snapshot generation 有效}
\end{cases}
\]

最终图像是物理像素，事件是逻辑坐标。对局部逻辑坐标 \((x_l,y_l)\) 和 DPR \(d\)：

\[
x_p=\lfloor x_l d \rfloor,\qquad y_p=\lfloor y_l d \rfloor
\]

只有物理坐标在最终帧内且 alpha 大于等于 8 才属于 \(A_t\)。必须覆盖 DPR
1.00、1.25、1.50、2.00、负屏幕坐标和半开边界。

### 3.2 帧一致性

1. `render_surface()` 获取一张 `QImage`；
2. 同一张图用于绘制，并交给 overlay 构造 bitmap hit snapshot；
3. 绘制成功且 generation 匹配后原子替换 `published_hit_frame`；
4. 绘制失败时不发布半成品；
5. animation replacement、surface retire、render failure、hide、close 时清除 alpha bitmap，只保留 BODY fallback；
6. active 左键手势期间即使 surface retire，也保留手势到 release；
7. 新动作第一帧尚未成功绘制时只保留 (B)，不得误用上一动作 alpha。

### 3.3 `PetSurfaceHitFrame`

新增不可变值对象，保存：

```text
width
height
device_pixel_ratio
alpha_mask
generation
```

`alpha_mask` 是 compact bitmap。值对象不得保存完整 `QImage` 作为查询结构。构造时使用固定
阈值把 alpha 转为 bitmap；`contains_logical(QPointF)` 只做坐标转换和 bit 查询，复杂度为
\(O(1)\)。禁止在 mouse move 扫描图像、重建 `QRegion` 或重新计算 alpha bounds。

### 3.4 Render 与 Hit 职责

Spine renderer 只负责产生并绘制最终 `QImage`，不管理输入语义；
`PetEffectOverlayWindow` 从同一张最终图构造 hit snapshot 并负责 `WM_NCHITTEST`。
不得增加第二次 render、GPU readback 或 hit-only pass。

### 3.5 用户控制优先级

protected 继续防止自动调度打断一次性动作，但不阻止人在 UI 明确下达新指令：

| 输入来源 | protected 播放中选择新动作 | 结果 |
|---|---:|---|
| `USER`：单击/桌宠菜单 | 是 | 立即 `REPLACE` |
| `TRAY`：托盘动作/恢复自动 | 是 | 立即 `REPLACE` |
| `AGENT` | 是 | 保留 latest-pending |
| `AUTONOMOUS` | 是 | 拒绝 |
| 拖动、暂停、关闭等安全事件 | 是 | 继续立即打断 |

打开右键菜单不产生动作请求；只有选择菜单项才替换 Track 0。

## 4. 冻结不变量

### 4.1 禁止修改

- 任意 `.skel`、`.atlas`、`.png`、manifest、资源 hash、动画名称映射；
- Sit/Special/Interact 的速度、循环、时长、mix 和物理动画名；
- Sit 的 surface rect、body offset、基线、屁股位置、脚部覆盖、缩放和朝向；
- Special 的 sampled bounds、floor lift、缩放、换向和 immutable composition；
- Relax、Move、Sleep 的布局、速度、朝向和视觉；
- native Spine bridge、BODY 尺寸 `160 x 180`。

### 4.2 必须保持的行为

- 同一个 `PetPointerGesture` 用 `QApplication.startDragDistance()` 区分 click/drag；
- 未过阈值释放只产生一次 Interact；过阈值只产生一次 START_DRAGGING，不再 Interact；
- 缺少 Drag 动画时继续使用现有 Relax fallback；
- release 后继续走现有 landing/recovery；
- AGENT/autonomous 不因本次修复获得打断 protected 的权限；
- closing 仍拒绝输入；
- Special 被替换后的旧 completion 必须是 stale，不能回跳或消费旧 pending。

## 5. 确认后采用的公开测试 seam

测试只穿过：

1. 新增不可变 `PetSurfaceHitFrame.contains_logical(QPointF)`；
2. renderer 向 overlay 提供本次实际绘制的同一帧 `QImage` 与 render generation；
3. `PetEffectOverlayWindow.show_layout()`、Qt 事件和 Windows `WM_NCHITTEST`；
4. `PetWindow` mouse press/move/release/context menu；
5. `PetAnimationEngine.request_action()`、`resume_autonomous()`、playback event；
6. 正式 `PetWindow + Spine38PetRenderer + PetTrack0Controller`；
7. 正式 Schwarz manifest、DLL、素材 smoke；
8. 正式启动器人工验收。

本 TDD 整体确认后才写测试，并按以下切片逐个 Red-Green-Refactor。

## 6. Red-Green 垂直切片

### Slice 0：现状 characterization 与视觉冻结

先记录，不改生产代码：

1. Sit 合成帧在 BODY 外放非透明尾巴/脚部点，证明当前 native hit 是 `HTTRANSPARENT`；
2. protected Special 后提交 TRAY Relax，证明当前只写 pending，Track 0 仍是 Special；
3. 重复发布相同 OVERFLOW，记录 `winId()` 和菜单层级；
4. 冻结正式 Sit/Special 的 layout、alpha bounds、关键帧 hash 和播放参数；
5. 冻结 Relax、Move Left/Right、Sleep 的布局和动作请求。

前两项必须按预期红；冻结测试应绿。保存 Red 输出和 19-test 绿基线。

### Slice 1：同帧 alpha hit snapshot

目标：新增 `pet_surface_hit_frame.py`，最小修改 `spine38_renderer.py`。

#### Red 1：纯坐标/DPR

人工构造 32×32 `QImage`，参数化断言：alpha 0=false；alpha 1=false；alpha 8=true；
alpha 255=true；DPR
1.00/1.25/1.50/2.00；左上包含；右/下半开边界排除；负坐标、越界、空图=false。

#### Green 1

实现不可变 hit frame，保存宽高、DPR、compact alpha bitmap 和 generation；不得把完整
`QImage` 保存为查询结构；单点查询 \(O(1)\)。

#### Red 2：绘制与命中同帧

fake backend 依次返回 Frame A（generation 1，命中 10,10）和 Frame B（generation 2，命中
20,20）。每次绘制只命中当前 generation；animation replacement 到新帧成功发布期间只能
命中 BODY fallback；每 paint 仅一次 `render_scene()`；绘制/backend 失败不发布新 snapshot。

#### Green 2

renderer 向 overlay 提供与本次 `drawImage()` 相同的最终 QImage 和 generation；overlay 在绘制
成功后构造 bitmap 并原子发布。BODY 调用方可忽略该帧数据；不新增 readback。

### Slice 2：OVERFLOW 可见像素命中与透明穿透

目标：`pet_effect_overlay.py` 和 `test_pet_effect_overlay.py`。

#### Red 1：Sit 尾巴/脚部与透明区

合成帧包含 BODY 内点、BODY 左侧尾巴点、BODY 下方脚点，其余透明。Windows 直接发送
`WM_NCHITTEST`：前三者为 `HTCLIENT`，透明 padding 和 surface 外为 `HTTRANSPARENT`。
offscreen 通过公开 Qt 事件验证同一逻辑。

#### Green 1

overlay 保存最后成功绘制的 snapshot，命中采用 (B \cup A_t)。禁止把整个 surface 设为热区。

#### Red 2：左右键转发

在 BODY 外非透明点发送 left press/release 与 context-menu event，覆盖负坐标副屏和 DPR 1.5。
input target 收到的 local/global 坐标必须正确，右键只收到一次。

#### Green 2

mouse press/context menu/native hit 共用相同公开 hit snapshot；继续用 global 坐标映射到 BODY target。

#### Red 3：活动手势捕获

从尾巴/脚部按下，移到透明区、移出 overlay、retire、release。目标只收到一次 press、
至少一次 move、一次 release；release 后 overlay 才隐藏。

#### Green 3

保留 `_proxy_pointer_active`，只扩展手势起始条件，不改变后续捕获。

#### Red 4：跨 generation 手势

从 Special 非透明像素 press，保持按下时请求 Interact 并发布新 generation，再 move/release。
必须保证 release 可达、不残留 pressed 状态、不产生额外 click、不触发第二次 drag。

#### Green 4

gesture 生命周期与 `published_hit_frame` 解耦：snapshot 可以失效/retire，已开始的 gesture
必须存活到 release 或明确的窗口关闭取消事件。

### Slice 3：稳定发布原生窗口

目标：`pet_effect_overlay.py`、必要时 `pet_window.py`。

#### Red 1：相同发布幂等

连续 120 tick 发布相同 layout/always-on-top，断言 overlay 始终可见、Windows `winId()`
不变、geometry 不变、hit frame 不被逐帧清空、顶层 overlay 始终只有一个、renderer 正常画 120 帧。

#### Green 1

flags/geometry 仅在值变化时设置；`show/raise` 只在首次显示、重新启用或所有权切换时执行；
普通帧只 repaint。

#### Red 2：菜单层级

从 Sit/Special 可见像素打开菜单并推进三个 timer tick：菜单仍在 overlay 之上；overlay 未重建；
动作、generation、pending 未变。此项必须有 Windows 原生 smoke，offscreen 不替代 Windows。

#### Green 2

删除逐帧 Z-order churn。Always-on-top 值真正变化时才重设 flags 并恢复可见性。

### Slice 4：Sit/Special 端到端 click/drag/right-click

目标：`test_pet_window.py`；仅在必要时修改 `pet_window.py` 的输入组合。

#### Red 1：click -> Interact

分别从 Sit/Special 的 BODY 外非透明像素 press/release：只提交一次 USER Interact；立即
`ACCEPTED`；generation 增加；physical name=`Interact`；pending=None；旧 Special completion
为 `STALE_COMPLETION`；不先进入 Relax/drag。

#### Green 1

事件可达后复用现有 `PetPointerGesture` 和 `request_user_pet_action()`，不改 Interact 资源/sequence。

#### Red 2：drag -> Relax fallback

分别从 Sit/Special 非透明像素按下并越过 drag threshold：START_DRAGGING 一次；motion 立即
`DRAGGING`；physical name 立即 `Relax`；protected continuation 清空；窗口连续跟随且首次无跳变；
释放前无 Interact；release 后只有一次现有 recovery。

#### Green 2

不新增 Drag 动画，复用 `PRODUCTION_MOTION_FALLBACK -> IDLE -> physical Relax`。

#### Red 3：right-click 只开菜单

在 Sit/Special BODY 外非透明点右键：菜单可见且项目完整；打开不会改变动作/generation；
选择动作只提交一次 `ActionSource.USER`。

#### Green 3

复用 `ProductionActionMenuSection`，只修输入可达和 Z-order。

### Slice 5：USER/TRAY 立即替换 protected

目标：`pet_animation.py`、`test_pet_explicit_action_control.py` 和托盘组合测试。

#### Red 1：来源矩阵

protected Special 中参数化提交 Relax、Move Left/Right、Sit、Sleep、Special、Interact。
对 USER/TRAY：不等 completion；outcome=`ACCEPTED`；generation 立即更新；physical name 匹配；
pending=None；resume_after_protected=False；旧 completion stale。相同 Special 遵守现有 duplicate/idempotent 契约。

#### Green 1

把仅 USER 的 direct override 收敛为“人工 UI 来源”集合 USER/TRAY。禁止删除
`_PRODUCTION_PROTECTED_ACTIONS`、降低 Special interruption class 或修改 catalog。

#### Red 2：Resume Autonomous 恢复 controller

Special/Interact 中分别调用 USER/TRAY resume。不得把 Resume Autonomous 实现成“强制请求
Relax 动画”。必须立即使 protected epoch 失效、清空 pending、恢复 autonomous controller，
再由 scheduler 按正常策略决定下一动作；旧 completion 必须 stale。

#### Green 2

把 resume 作为 controller 状态转换：invalidate protected epoch -> clear pending -> activate
autonomous scheduler -> scheduler chooses next action。不向该路径硬编码 Relax action。

#### Red 3：非人工零回归

AGENT 仍 latest-pending；autonomous 仍 priority rejection；pause/drag/shutdown 仍立即打断；
renderer degraded/closing 不被绕过；pending 仍只消费一次。

### Slice 6：真实 Schwarz 与 Windows 原生门禁

使用正式 manifest/DLL/素材：

1. Sit 全周期采样最终 QImage，从真实 alpha 中选 BODY 外尾巴/脚部点；
2. 这些点发布后 `WM_NCHITTEST == HTCLIENT`，透明 padding 为 `HTTRANSPARENT`；
3. Special 起始/中段/结束前各选非透明点并验证可命中；
4. Special 中段真实点 click 立即 Interact；
5. 重新进入 Special，中段 drag 立即 Relax fallback；
6. 重新进入 Special，托盘选 Sit/Relax 立即替换；Resume Autonomous 立即恢复 controller，由 scheduler 选择下一动作；
7. renderer safe code 始终 `none`；每帧 `render_scene()` 仍只调用一次。

若真实 smoke 要求修改渲染公共代码，必须证明输出 QImage 的像素 hash/alpha bounds 不变。

## 7. 允许与禁止修改范围

### 7.1 Red 证明必要后允许

- `src/arkclaw/presentation/qt/pet_surface_hit_frame.py`（新增纯值对象）；
- `src/arkclaw/presentation/qt/spine38_renderer.py`（返回已绘制帧 snapshot）；
- `src/arkclaw/presentation/qt/pet_effect_overlay.py`（命中、稳定发布）；
- `src/arkclaw/presentation/qt/pet_window.py`（仅 surface/事件组合；不必要则不改）；
- `src/arkclaw/application/pet_animation.py`（仅 USER/TRAY override/resume）；
- 对应测试和验收文档。

### 7.2 明确禁止

- `pet_action_sequence.py`、`pet_role_pack.py`、`pet_render_layout.py`、`pet_motion.py`；
- `pet_track0.py`、`spine38_player.py`；
- native bridge、manifest、素材和打包资源。

若 Red 无法在允许范围内变绿，必须暂停并给出证据，不得自行扩大修改面。

### 7.3 Native bridge 例外门禁

默认禁止修改 native bridge。只有 Qt/Python 层无法同时实现 alpha hit-test 与
`HTTRANSPARENT` 时才可申请例外；继续前必须先提交：当前行为证据、Qt/Python 层无法解决的
证明、精确文件范围和风险分析。即使获准，也禁止 native 重构、窗口模型变更和消息循环修改。

## 8. 自动测试门禁

每个 Slice 必须保留“因预期缺陷失败”的 Red，再做最小 Green，禁止先实现后补测试。

```powershell
Set-Location 'D:\ArkClaw\.worktrees\arkpets-spine-idle-vertical-slice'
$env:PYTHONPATH = (Resolve-Path '.\src').Path

.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider `
  tests\unit\test_pet_surface_hit_frame.py `
  tests\qt\test_pet_effect_overlay.py -q

.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider `
  tests\unit\test_pet_explicit_action_control.py `
  tests\unit\test_pet_production_motion.py -q

.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider `
  tests\qt\test_pet_window.py `
  tests\qt\test_qt_autostart.py -q

.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider `
  tests\unit\test_pet_render_layout.py `
  tests\qt\test_spine38_renderer.py `
  tests\qt\test_spine38_schwarz_smoke.py -q

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\start_schwarz_pet.ps1 -ValidateOnly
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\start_schwarz_pet.ps1 -Smoke

.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m mypy src tests scripts packaging
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -q
git diff --check
```

视觉零回归额外冻结 Sit/Special 的 surface rect、body offset、alpha bounds、关键帧 hash、
physical name、speed、loop、mix。修复前后必须相等，唯一允许新增的是 hit snapshot/输入结果。

## 9. Windows 人工验收

先从旧桌宠托盘选择 `Quit`，再用唯一正式入口：

```powershell
Set-Location 'D:\ArkClaw\.worktrees\arkpets-spine-idle-vertical-slice'
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\start_schwarz_pet.ps1 -Console
```

### 9.1 Sit

1. `Relax -> Sit`；
2. 分别单击头、身体、BODY 外尾巴、任务栏上的脚部：每次立即 Interact；
3. 再进 Sit，从四处分别拖动：立即 Relax fallback 并跟随，首次移动无跳变；
4. 再进 Sit，从四处分别右键：菜单立即出现，停留 3 秒不被盖住；
5. 从菜单选 Relax/Special/Sit：各自立即生效。

尾巴、脚部、屁股落点、缩放和朝向必须与修复前一致。

### 9.2 Special

每次在 Special 中段操作，禁止等自然结束：

1. 单击角色像素：立即 Interact；
2. 拖动角色像素：立即 Relax fallback 并移动；
3. 右键角色像素：菜单立即出现；
4. 菜单选 Sit：立即 Sit；
5. 托盘选 Relax、Move Left/Right：立即对应动作；
6. 托盘选 `Resume Autonomous`：立即结束 protected epoch 并恢复 autonomous controller，由 scheduler 决定下一动作，不得硬编码强制 Relax；
7. 菜单打开后等待三个 render tick：仍位于 overlay 上方。

### 9.3 跨 generation 手势竞争

Special 像素 press 后不释放，切换 Interact，再 move/release。必须收到 release，不残留 pressed，
不产生重复 Interact，也不触发错误的第二次 drag。

### 9.4 穿透、DPI、多屏

至少覆盖 DPI 100/125/150/200%、主副屏、一个负 X/Y 副屏、Always on Top 开/关、
底部任务栏和自动隐藏任务栏。每组验证：可见像素可选中；透明空白穿透；active drag 不断线；
菜单不闪退/不被盖/不重复；画面无闪烁、残影、位移或缩放变化。

建议保存同时包含桌宠、任务栏、托盘和菜单的连续录屏，并记录显示器/DPI/置顶配置。

## 10. 性能与资源门禁

- 每个显示帧最多调用一次现有 `render_scene()`；命中数据只能复用这一次调用返回的最终 `QImage`；
- 禁止新增 FBO readback、GPU readback 或 hit-only render pass；
- hit query 为 (O(1))，mouse move 不扫描整图；
- animation tick 不重建 QRegion、原生窗口或 flags；
- 不新增后台线程/轮询 timer；
- 只持有当前已发布 bitmap hit frame，禁止为查询长期保存完整 QImage，hide/close 可释放；
- 120 秒压力运行中 overlay 数量始终 1、窗口句柄稳定、无持续内存增长趋势。

## 11. 完成判定

只有以下全部满足才能宣布完成：

1. Slice 0–6 均有可信 Red，Green 仅做最小改动；
2. Sit/Special 真实非透明像素在 Windows 可选中，透明区仍 `HTTRANSPARENT`；
3. click、drag、right-click 三链路通过；
4. USER/TRAY 动作立即替换 Special；Resume Autonomous 立即恢复 controller 并由 scheduler 决策；
5. AGENT/autonomous/protected/safety 语义零回归；
6. 旧 Special completion 为 stale，不回跳；
7. overlay 不逐帧重建/提升，菜单层级稳定；
8. Sit/Special 布局、alpha bounds、像素 hash、播放参数不变；
9. 目标测试、真实 smoke、ruff、mypy、全量 pytest、diff check 达标；
10. 人工验收覆盖 Sit、Special、托盘、菜单、拖动、多 DPI、多屏；
11. Git diff 不含资源、布局、catalog、native 或非必要动画改动；若触发 native 例外，必须已有单独批准证据。

本 TDD 获确认后才进入测试实现；任何扩大生产修改范围的需求都必须停止并重新审查。

## 12. 2026-08-13 实施记录

自动化已完成：

- alpha 命中快照仅复用当前 `render_surface()` 已取得的最终 `QImage`；真实 Windows smoke
  对 Sit 及 Special 1%/50%/99% 帧逐样本计数，`render_scene()` 均恰好为 1；
- 未新增 FBO/GPU readback、hit-only pass、后台线程、轮询 timer 或动画资源；
- hit query 为紧凑 bitmap 的常数时间查询；`752×536`、200% DPI 样本的 bitmap 构建由
  纯 Python 逐像素约 `66.0 ms` 优化为 Qt 批处理约 `0.83 ms`；
- Sit/Special 的 click、drag、right-click、跨 generation release、菜单三 tick 层级稳定均已覆盖；
- USER/TRAY 可立即替换 protected；AGENT 仍 pending；相同 Special 为 accepted no-op；
  Resume 立即清除 protected epoch/pending，并用最近非 protected scheduler 锚点恢复所有权；
- 相关目标套件：`128 passed, 2 deselected`；控制语义最终复跑：`43 passed`；
- 正式 Schwarz catalog/真实像素/Windows 原生命中门禁：`7 passed, 1 deselected`；
- Ruff 与本轮生产文件 mypy 均通过。

未计入本轮完成的既有环境/工作树问题：

- Qt 6.11 offscreen 子进程缺字体的 2 条旧 smoke；
- 旧 `schwarz-smoke.json` 无法删除导致 1 条 Relax 证据 smoke 在进入渲染前失败；
- 全仓 `--maxfail=4` 另有 OpenGL 旧 smoke 返回码 2，以及 3 个 autostart layout probe
  30 秒超时；这些文件均在本 TDD 白名单之外，本轮未修改。

最终状态仍为“待人工验收”，只有完成第 9 节的 Sit、Special、多 DPI、多屏和任务栏动态目视
检查后，才能把第 11 节第 10 项标记为完成。

## 13. 人工验收失败追加 Slice 7：点击任务栏后 Sit 脚部仍在其上方

### 13.1 失败事实与边界

2026-08-13 人工验收报告：Sit 初次显示时脚部覆盖正确；用户点击任务栏后，任务栏重新遮住
脚部。该事实使第 9.1 节和第 11 节第 10 项失败，本文状态退回“Red-Green 进行中”。

本 Slice 只处理 Windows 原生 Z-order，不改变 Sit/Special 或其他动画资源、播放参数、布局、
锚点、surface bounds、alpha bounds、命中 bitmap 或动作状态机。继续严格遵守：每个显示帧
最多一次现有 `render_scene()`；禁止新增 FBO/GPU readback、hit-only render pass、后台线程和
轮询 timer。

### 13.2 机制与可证伪假设

Windows 任务栏自身属于 topmost band。`WindowStaysOnTopHint` 只保证 overlay 处于该 band，
不能保证它永远排在同 band 的 `Shell_TrayWnd` 之前。点击任务栏后 Explorer 可将任务栏移动到
已有 overlay 之前，因此任务栏覆盖 Sit 脚部；这与 Sit 坐标正确并不矛盾。

首要假设通过真实 Windows 红灯测试验证：创建与任务栏相交的既有 overlay，使用
`SetWindowPos(Shell_TrayWnd, HWND_TOPMOST, ..., SWP_NOACTIVATE)`复现点击后的顺序，随后执行
下一次既有 `show_layout()`。修复前 taskbar 仍在 overlay 之前；修复后 overlay 恢复到 taskbar
之前，且 HWND、geometry、flags 不变。

若首要假设不成立，才依次检查：overlay HWND 被重建；Sit 意外退出 OVERFLOW；DWM 裁剪。

### 13.3 Red-Green 与实现约束

1. Red：Windows/Qt `windows` 平台测试必须先证明 taskbar 可排到 overlay 前，且现有
   `show_layout()` 无法恢复顺序。
2. Green：只在 overlay 与当前显示器任务栏矩形相交、任务栏确实位于 overlay 前方时，执行
   一次 `SetWindowPos(..., SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)`层级修复。
3. 修复插入位置必须是任务栏之前、已有更高窗口之后；不得无条件 `raise_()`，以免覆盖右键菜单。
4. 无相交或顺序已正确时必须为 no-op；不得每 tick 重建窗口、flags、QRegion 或渲染数据。
5. Green 后复跑：真实 Z-order 测试、既有相同布局 120 次稳定性、菜单三 tick 层级、
   Sit/Special 点击/拖动/右键、单 render_scene 门禁和全量目标套件。

### 13.4 新增人工验收步骤

进入 Sit，确认屁股落点和脚部初始效果不变；依次点击任务栏空白、任务栏应用图标、系统托盘，
每次停留至少 3 秒。脚部必须始终显示在任务栏上方；透明区域仍可点击任务栏；右键桌宠菜单
必须仍高于 overlay。至少验证主屏和一个副屏任务栏，以及 Always on Top 开/关的项目既有语义。

### 13.5 2026-08-13 实施记录

- 真实 Windows Red 已复现：`Shell_TrayWnd` 重新置顶后，现有相同 Sit 布局无法恢复 overlay；
- Green 只修改 Qt overlay 的 Windows Z-order：仅在 HWND 矩形相交且 overlay 不在任务栏上方时，
  将其插到任务栏之前、原有更高窗口之后；无 `raise_()`、窗口/flags 重建或渲染改动；
- 真实 Windows 测试同时冻结 `popup -> overlay -> taskbar` 顺序，防止右键菜单被盖；
- 新增真实 Z-order 测试 `1 passed`；覆盖层/输入/动作 `63 passed, 1 skipped`（真实 Windows
  用例在 offscreen 跳过但已单跑通过）；布局/renderer `56 passed`；Ruff、mypy 通过；
- 真实 Schwarz 单渲染门禁 `1 passed`，每个 Sit/Special 样本仍只有一次现有
  `render_scene()`；未新增 FBO/GPU readback 或 hit-only render pass；
- `start_schwarz_pet.ps1 -ValidateOnly` 已在真实工作树权限下通过，并解析到本工作树 `.venv`。

本 Slice 自动化状态为 Green，整体仍等待第 13.4 节 Windows 人工验收。既有全量门禁中仍有
一条 `qt_pet_smoke.py` 的 `drag_struggle_entered/exited` 环境失败，以及已记录的 offscreen
OpenGL/evidence 文件权限问题；本 Slice 未修改相应代码。

## 14. 人工验收失败追加 Slice 8：Sit/Special 原生输入 DPI 坐标

### 14.1 失败事实与真实 Red

2026-08-13 再次人工验收：Slice 7 已解决 Sit 点击任务栏后的层级问题，但 Sit 与 Special
角色仍无法用鼠标选中。既有测试只直接调用 Qt 事件或向 HWND 发送用 Qt 逻辑坐标拼出的
`WM_NCHITTEST`，没有证明 Windows 的真实鼠标路由会把输入交给 overlay。

新增独立真实 Windows/OpenGL Schwarz 测试，经 `WindowFromPoint` 和系统鼠标注入复现：
Sit/Special 的 BODY 中心均被路由到后方 Chrome 窗口；向 overlay 同一点直接发送
`WM_NCHITTEST`，两者均返回 `HTTRANSPARENT(-1)`。这是本 Slice 的可信 Red。

### 14.2 根因与 Green

`WM_NCHITTEST.lParam` 是 Win32 原生屏幕像素坐标；旧实现直接执行
`screen_x - QWidget.x()`，把原生物理坐标与 Qt 逻辑坐标混用。在非 100% DPI 下，本应位于
BODY/角色 alpha 的点被换算到错误位置，返回 `HTTRANSPARENT`，因此 click、drag、right-click
的 Qt 转发链从未收到事件。

Green 仅在 Windows 原生命中入口增加坐标转换：

1. `ScreenToClient`：原生屏幕像素转 overlay 原生客户区像素；
2. `GetClientRect`：获得原生客户区宽高；
3. 按原生/Qt 客户区比例换算为 Qt 逻辑局部坐标；
4. 复用原有 BODY rect 与当前帧 alpha bitmap 命中判断。

没有改变 Sit/Special 或其他动画资源、布局、锚点、窗口几何、播放参数、状态机或渲染；透明
像素仍返回 `HTTRANSPARENT`。每帧最多一次现有 `render_scene()`，未新增 readback/render pass。

### 14.3 自动化完成证据

- 正式 Schwarz Sit/Special 真实原生输入：`2 passed`；每例均验证右键立即打开菜单、单击立即
  Interact、重新进入原动作后拖动立即 Relax/dragging 并正常 release；
- BODY、BODY 外可见 alpha 和透明 padding 原生命中组合：`4 passed`；
- 原生测试使用真实 HWND 客户区比例，因此覆盖当前非 100% DPI 环境，并保持多 DPI 比例无关；
- 覆盖层/输入/动作回归：`63 passed, 1 skipped`，跳过项仅因 offscreen 无真实任务栏，已在
  Windows 单跑通过；任务栏层级与真实多帧单 `render_scene()` 最终门禁：`2 passed`；
- Ruff、mypy、`git diff --check` 通过；
- 整体仍需按第 9 节在用户正式实例中人工复验，尤其是 100/125/150/200% DPI 与副屏。
