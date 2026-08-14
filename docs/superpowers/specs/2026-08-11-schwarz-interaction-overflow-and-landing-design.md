# Schwarz 交互、溢出动画与落地连续性修复设计（TDD）

**日期：** 2026-08-11  
**修订：** Revision 4.5，已纳入第三次实现后的 Windows 人工验收修订  
**状态：** 已批准并进入实现  
**适用基线：** `codex/arkpets-spine-idle-vertical-slice` 当前未提交实现

## 1. 目的

本设计处理第二轮 Windows 人工验收发现的五项问题：

1. `Sit` 的脚部低于当前逻辑窗口，被任务栏遮挡；
2. `Special` 的靶子位于当前 `160 x 180` 窗口之外，动画只显示人物；
3. 左键单击桌宠不会触发 `Interact`；
4. 拖拽释放后，落到任务栏附近存在可见卡顿；
5. 桌宠右键菜单没有生产动画选择项，动画只能从系统托盘选择。

本设计补充并部分取代
`2026-08-10-schwarz-production-animation-acceptance-repair-design.md`。
仅当本设计明确冲突时，以本设计为准。特别是，之前允许裁掉
`Special` 极端效果像素；本轮用户要求尽可能完整显示靶子，因此该决定被取代。

## 2. 诊断证据与可行性结论

### 2.1 真实素材边界

使用已验证的 Schwarz Spine 3.8 素材、Release bridge 和当前 Relax 固定缩放，
先按上一轮设计的 12 个固定诊断点

```text
t_i = (i / 12) * T, i = 0..11
```

测得以下 **12 点 sampled bounds**。它们只用于证明当前裁剪现象和估算方案，
不是连续动画的数学 envelope：

| 动画 | 当前缩放下的屏幕并集 | 是否被 `160 x 180` 裁剪 |
|---|---:|---:|
| Relax | `(28.3, 18.0)..(131.7, 180.0)` | 否 |
| Move | `(28.6, 16.8)..(135.3, 182.0)` | 是，下沿约 2px |
| Sit | `(-15.3, 68.8)..(146.2, 211.1)` | 是 |
| Sleep | `(-3.3, 98.0)..(186.6, 187.0)` | 是，下沿约 7px，横向附件溢出 |
| Special | `(12.9, -83.3)..(383.6, 180.7)` | 是 |
| Interact | `(14.8, 15.9)..(138.7, 184.0)` | 是，约 4px |

因此形成以下确定结论：

- `Sit` 素材并未缺失脚部。脚部最多低于现有窗口约 `31.1` 逻辑像素，
  可以通过动作级地面校正完整露出；
- `Special` 素材包含窗口外的大范围可见几何，靶子不是素材缺失；
- 若把完整 `Special` 强行等比缩入 `160 x 180`，缩放系数约为 `0.41`，
  角色身体会从约 `162px` 高降至约 `66px`，不满足上一轮“身体优先”决定；
- `Interact` 仅有少量下沿溢出，可与 `Sit` 使用同一地面校正规则。

Move 和 Sleep 并非未经验证的 BODY 假设：Move 只需约 2px 地面校正；
Sleep 需要约 7px 地面校正，但其横向可见附件约有 30px 超出身体窗口。
Sleep 延续上一设计的 body-priority 政策，允许横向附件裁剪，不声称完整内容可见。

本轮 profile 不再使用 12 点作为发布包络。发布阶段使用第 5.2 节定义的
至少 60Hz `sampled_action_bounds`；自动化验收只保证这些采样时刻的 content bounds，
以及 OVERFLOW surface 单独增加的 2px clipping padding。连续播放中是否仍有采样间
极值遗漏，由真实 Windows 完整播放验收负责。

### 2.2 输入路径

当前 `PetWindow.mousePressEvent` 在左键按下时立即进入 `DRAGGING`，
而 `mouseReleaseEvent` 立即执行释放、下落或落地。因此现有实现没有“单击”语义：
一次没有移动的按下/释放也会被解释为一次拖拽。

当前桌宠 `contextMenuEvent` 只创建通用菜单项：暂停、置顶、开机启动、
打开 Agent 窗口和退出。生产动作菜单只由系统托盘创建，两个入口没有复用同一菜单模块。

### 2.3 落地路径

Schwarz 没有单独的拖拽、下落和落地物理动画，当前正确地使用循环 `Relax`
作为视觉降级。但 `LANDING -> IDLE` 时，当前引擎会：

```text
clear Track 0 -> 重新提交 Relax -> 从 Relax 0 时刻开始
```

即使拖拽、下落和落地期间已经存在健康且已确认的循环 Relax，也会重建播放 epoch。
这一时间归零会在接触任务栏后产生姿态跳变，是本轮首先修复的连续性问题。

尚无证据表明重力常量本身错误。本设计不在没有测量的情况下调整重力、
计时器频率或动画速度。

## 3. 待批准的用户决策

批准本设计即表示接受以下行为：

1. 身体的物理、拖拽和命中窗口继续固定为 `160 x 180` 逻辑像素；
2. `Sit` 和少量溢出的 `Interact` 保持 Relax 身体缩放，只做一次稳定的垂直地面校正，
   不逐帧缩放；
3. 在工作区能够容纳原尺寸 projected sampled visible content bounds 时，`Special`
   保持 Relax scale；固定 2px clipping padding 只扩展 overlay surface，
   不作为可见内容必须落入 workspace 的条件，
   使用一个临时、透明、选择性输入代理的溢出显示层展示靶子；
4. 当当前朝向会让 `Special` projected sampled bounds 超出当前显示器，而镜像朝向
   可以完整容纳这些 bounds 时，
   只在该次 `Special` 展示期间采用朝向屏幕内部的有效渲染朝向；动画结束后恢复
   语义朝向；
5. 左键按下本身不再立即拖拽：移动达到系统拖拽阈值才开始拖拽，
   未达到阈值的按下/释放触发一次 `Interact`；
6. 桌宠右键菜单与系统托盘展示相同的生产动作集合；
7. 健康的 Relax 在拖拽、下落、落地和回到自主模式期间保持同一个播放 epoch，
   不在落地结束时重播。
8. 当 active workspace 在 LEFT/RIGHT 两种朝向下都无法容纳原尺寸 Special
   projected sampled visible content bounds 时，允许本次 Special
   使用临时 fit scale；该次展示标记为
   `DEGRADED_FIT`，不得写回 role-pack scale，也不得影响后续动作。surface 的固定
   2px clipping padding 在选定 scale 后加入，并单独接受 outward-round 后的资源检查；
9. `Special` 的 effect 最低点允许在人物 ground baseline 下方最多 16.0px；人物和 body
   anchor 不随 effect 上移。超过 16.0px 时直接 fail closed；不得把整个 effect 的最低点
   静默当作人物脚底。

若不接受第 4 项，可替换为“始终保留语义朝向，但靠近屏幕边缘时允许 sampled bounds
被物理屏幕裁剪”。
在不缩小人物、不移动人物且不改变朝向的三个约束同时成立时，屏幕边缘外的像素在物理上
无法显示，因此不存在第四种完整显示方案。

## 4. 总体方案

```text
真实动画 >=60Hz sampled bounds
        |
        v
RolePackRenderProfile（Spine-space renderer-neutral bounds）
        |
        v
PetActionEnvelopeProjector（唯一坐标投影 owner）
        |
        v
ProjectedActionEnvelope（LEFT/RIGHT content bounds + body anchors）
        |
        v
PetRenderLayoutPlanner（只做桌面布局）
  |                         |
  | body-contained          | overflow Special
  v                         v
160x180 PetWindow      PetEffectOverlayWindow
输入/拖拽/碰撞          透明、无焦点、代理身体区域输入并绘制
```

同时，输入和动作请求遵循：

```text
左键按下
  -> 位移 < QApplication.startDragDistance()
       -> 左键释放 -> Interact(ActionSource.USER)
  -> 位移 >= QApplication.startDragDistance()
       -> start_dragging -> drag_to -> release_drag

右键
  -> 通用桌宠菜单
  -> 共享 ProductionActionMenuSection
  -> request_action(ActionSource.USER)
```

## 5. 动作构图与溢出显示

### 5.1 不变量

- `PetMotionModel.position` 永远表示 `160 x 180` 身体窗口左上角的桌面逻辑坐标；
- 任务栏、工作区、拖拽、坠落和持久化只使用身体窗口，绝不使用 Special 溢出层尺寸；
- settled 状态仍满足：

```text
body_window_bottom == active_workspace_bottom
```

- Relax 选择的 `PetBodyTransform.scale` 在整个 role-pack 会话内不变；小屏 Special
  `DEGRADED_FIT` 只返回临时 `scale_multiplier`，不得修改 body transform；
- 一个动作正常播放时只使用一个固定构图，不按帧重新计算，不产生呼吸式缩放或画面泵动；
- Qt 工作区继续使用半开区间 `x + width`、`y + height`；
- 所有布局先以逻辑像素计算；同一 logical workspace 内仅 DPR 改变时，逻辑 layout、
  facing 和 scale 保持不变，只重建物理 framebuffer。若新 DPR 使第 5.4 节物理资源上限
  被突破，则安全终止当前 Special 并进入既有 failure containment，不得用 DPR 静默改变逻辑布局；
- active screen 或 logical workspace 发生实质变化时，当前 Special composition 立即失效：
  先准备正常 BODY 状态，再隐藏 overlay 并安全取消本次 Special；不得在动作中途重新规划、
  翻向或缩放。

### 5.2 `RolePackRenderProfile`

在 `src/arkclaw/bootstrap/pet_production.py` 的生产候选发布阶段，
将当前只返回 Relax 12 点并集的采样结果深化为一个不可变 profile：

```python
@dataclass(frozen=True, slots=True)
class RolePackRenderProfile:
    body_bounds: Spine38Bounds
    sampled_action_bounds: Mapping[PetRendererAction, Spine38Bounds]
```

#### 采样契约

对持续时间为 `T > 0` 的每个唯一物理动画，profile 构建始终以 **non-loop
sampling mode** 设置 Track 0，使 terminal pose 可观察，并定义：

```text
N = max(12, ceil(60 * T))
t_i = (i / N) * T, i = 0..N
```

因此每个物理动画固定产生 `N+1` 个均匀样本，相邻间隔满足 `T / N <= 1/60s`，
同时包含 `t=0` 和 `t=T`。对 one-shot，`t=T` 是必须保留的 terminal pose；
对 loop，它可能与起点重复，也可能暴露 authored terminal pose。profile 构建接受这一个
保守冗余样本，不按运行时 loop 属性分叉采样政策，也不让同名动画因逻辑 binding 的
loop 属性不同而产生两套 cache。

每个唯一物理动画的采样必须彼此隔离。开始采样前恢复同一个 canonical setup state、
清空先前 Track 0/mix 状态，并以零继承混合安装目标动画的 non-loop sampling state；
完成后不得把 skeleton pose、track time、mix 或 attachment state 泄漏到下一动画。
`sample A -> sample B` 与 `sample B -> sample A` 必须产生逐动画相同的 sampled bounds；
若 bridge 无法提供可验证的 reset/isolation，候选 profile fail closed。

如果 bridge 将来能可靠发布 animation keyframe 时刻，则再合并所有
`[0, T)` 内的唯一 keyframe 时刻；keyframe 支持不是本轮 bridge 变更的前置条件。

`sampled_action_bounds` 这个名称是契约的一部分：它只表示这些离散时刻的并集，
不得在代码、测试或文档中简称为能够证明连续极值的 `animation envelope`。
OVERFLOW 布局阶段另加 2 逻辑像素 clipping padding；padding 与 content bounds 分离，
并且同样不构成连续曲线的数学证明。

#### Profile 规则

- 相同物理动画的逻辑别名共享同一个并集；
- 因为 profile 统一使用 non-loop sampling mode 并包含 terminal pose，sample cache key
  只需物理动画名，不受运行时 binding 的 loop 属性影响；
- `body_bounds` 与 `PetBodyTransform` 保留上一轮已验收的 Relax 12 个固定 calibration
  采样所得数值；本轮 >=60Hz profile sampling 只用于动作布局与验证，不重新校准身体 scale；
- `sampled_action_bounds` 只用于稳定平移、溢出判定和 overlay 大小，
  正常工作区下绝不反向降低 Relax scale；
- profile 以 renderer-neutral `PetRendererAction` 索引；bootstrap 中一个显式 adapter
  将 `ProductionAction`/role binding 转换成 renderer action，renderer 不得导入
  `ProductionAction`；
- `SPECIAL` 和 `INTERACT` 是新增的真实 renderer-neutral 枚举值；旧的 `WAVE`、
  `HAPPY_JUMP` 保留给既有占位表现，但不得作为 Schwarz Special/Interact 的别名；
- `MOVE_LEFT` 和 `MOVE_RIGHT` 对应的 renderer key 共享同一个 canonical Move sampled bounds，
  左右几何由 projector 产生；
- 任意非有限或空 bounds 使候选 role pack 失败关闭；
- `T <= 60s` 是 role-pack animation duration contract；`N <= 3600` 是独立的
  defensive allocation contract。二者当前由同一公式关联，但必须分别验证，防止未来
  采样公式变化后失去内存/启动时间上限；包含 terminal pose 后实际 sample count
  上限为 `N+1 <= 3601`；若未来合并 keyframe 时刻，去重后的 total sample count
  另设硬上限 `<=4096`；
- profile 在 renderer 发布前完成，播放期间不重新扫描素材。

若未来需要用高密度 Relax 样本重新校准身体尺寸，必须另立 TDD 并重新完成
`153..171` 身体高度视觉验收；本轮不得顺带改变已接受的 `162px` 目标 framing。

`frozen=True` 只冻结字段绑定，不足以冻结内部 `dict`。构造函数必须 defensive-copy，
并以 `MappingProxyType(dict(sampled_action_bounds))` 保存 mapping。该类型是应用内只读值，
不写回外部 manifest，不修改素材，也不包含绝对素材路径。

### 5.3 `PetActionEnvelopeProjector` seam

Profile 的 bounds 位于 Spine space，而布局需要身体窗口逻辑坐标。两者之间新增唯一投影
module，renderer 和 PetWindow 都不得重复实现 scale、translation、mirror 或 rounding。

```python
@dataclass(frozen=True, slots=True)
class PetBodyTransform:
    scale: float
    origin_x: float
    origin_y: float
    mirror_axis_x: float

@dataclass(frozen=True, slots=True)
class ProjectedFacingEnvelope:
    content_bounds: Rect
    body_anchor: Point

@dataclass(frozen=True, slots=True)
class ProjectedActionEnvelope:
    right: ProjectedFacingEnvelope
    left: ProjectedFacingEnvelope

def project_action_envelope(
    *,
    sampled_bounds: Spine38Bounds,
    body_transform: PetBodyTransform,
) -> ProjectedActionEnvelope:
    ...
```

`PetBodyTransform` 是 renderer 绘制与 envelope 投影共享的同一个不可变值，
由 Relax body calibration 只构造一次。RIGHT 使用 canonical transform；LEFT 严格围绕
`mirror_axis_x` 映射 RIGHT 的 content bounds 和 body anchor。`body_anchor` 是 Spine
skeleton/body origin 在身体窗口逻辑坐标中的投影：RIGHT 取 body transform origin，
LEFT 取该 origin 关于同一 mirror axis 的镜像。

`ProjectedActionEnvelope` 是纯几何值，不重复携带 action identity；调用路径已经通过
`RolePackRenderProfile.sampled_action_bounds[action]` 选择了 bounds。projector 只负责
Spine geometry 到身体逻辑坐标，不负责 action dispatch、padding 或 desktop layout。
它保留连续浮点 content bounds，不做 raster 行索引转换；只有最终 surface rect 向外取整。

完整数据流固定为：

```text
Spine sampled bounds
    -> RolePackRenderProfile
    -> shared PetBodyTransform
    -> ProjectedActionEnvelope(LEFT + RIGHT)
    -> PetRenderLayoutPlanner
    -> PetRenderLayoutResult
```

新增测试必须证明 renderer 顶点和 projector bounds 使用同一个 transform/mirror axis，
避免 scale 相同但 translation 或 rounding 相差 1～2px。

### 5.4 `PetRenderLayoutPlanner` seam

在 `src/arkclaw/application/pet_render_layout.py` 新增纯计算 module。Planner 不再推导镜像；
它显式接收两个朝向的 projected content bounds 和 body anchor：

```python
def plan_pet_render_layout(
    *,
    body_rect: Rect,
    workspace: Rect,
    envelope: ProjectedActionEnvelope,
    preferred_facing: PetFacing,
    policy: RenderContainmentPolicy,
    device_pixel_ratio: float,
) -> PetRenderLayoutResult:
    ...
```

成功与失败都是显式、可穷举的纯值：

```python
@dataclass(frozen=True, slots=True)
class PetRenderLayout:
    mode: PetRenderSurfaceMode       # BODY 或 OVERFLOW
    surface_rect: Rect               # 桌面逻辑坐标
    body_window_offset: Point        # float-valued domain Point
    ground_correction: float         # 向上校正的正数幅值
    effective_facing: PetFacing
    scale_multiplier: float          # 正常为 1；小屏降级可小于 1
    quality: PetRenderLayoutQuality  # FULL_SCALE 或 DEGRADED_FIT

class PetRenderLayoutFailureReason(StrEnum):
    BODY_VERTICAL_INFEASIBLE = "body_vertical_infeasible"
    SPECIAL_EFFECT_FLOOR_INFEASIBLE = "special_effect_floor_infeasible"
    LOGICAL_RESOURCE_LIMIT_EXCEEDED = "logical_resource_limit_exceeded"
    INVALID_DPR = "invalid_dpr"
    PHYSICAL_RESOURCE_LIMIT_EXCEEDED = "physical_resource_limit_exceeded"
    WORKSPACE_FIT_INFEASIBLE = "workspace_fit_infeasible"

@dataclass(frozen=True, slots=True)
class PetRenderLayoutFailure:
    reason: PetRenderLayoutFailureReason

PetRenderLayoutResult = PetRenderLayout | PetRenderLayoutFailure
```

这里的 `Point` 是 application geometry 中允许浮点坐标的 domain value，不是整数
`QPoint`。设 `L_s = surface_rect.top_left`、`L_b = body_rect.top_left`，必须满足：

```text
L_s + body_window_offset = L_b
A_desktop = L_b + corrected_body_anchor
A_surface = body_window_offset + corrected_body_anchor
L_s + A_surface = A_desktop
```

因此 `body_window_offset` 明确表示“身体窗口左上角相对于 surface 左上角的偏移”，
不是 skeleton/body anchor。只允许最终 `surface_rect` 向外取整；offset 保持浮点，避免重新
引入 1px rounding drift。

这是一个深 module：调用方不需要知道地面校正、逻辑像素取整、工作区选择、
边缘朝向或安全尺寸上限的具体算法；Spine transformation 知识则完全属于 projector。
Planner 本身没有 bootstrap 或 UI 副作用。failure ownership 冻结为两类：
`BODY_VERTICAL_INFEASIBLE`、`SPECIAL_EFFECT_FLOOR_INFEASIBLE` 和
`LOGICAL_RESOURCE_LIMIT_EXCEEDED` 是 candidate-static failure，bootstrap preflight
必须拒绝候选；`INVALID_DPR`、`PHYSICAL_RESOURCE_LIMIT_EXCEEDED` 和
`WORKSPACE_FIT_INFEASIBLE` 是当前运行环境 failure，只由 runtime 进入既有
placeholder/failure containment，不得永久判坏 role pack。

#### Policy matrix

```text
BODY_PRIORITY
    vertical correction feasible   -> BODY
    vertical correction infeasible -> LAYOUT_FAILURE(BODY_VERTICAL_INFEASIBLE)

FULL_SAMPLED_BOUNDS
    rounded padded surface fits 160x180 body surface -> BODY
    rounded padded surface needs more draw space     -> OVERFLOW
    Special effect-floor lift exceeds tolerance     -> LAYOUT_FAILURE(SPECIAL_EFFECT_FLOOR_INFEASIBLE)
    visible content cannot fit workspace full scale -> OVERFLOW + DEGRADED_FIT
    workspace cannot hold acceptable degraded fit   -> LAYOUT_FAILURE(WORKSPACE_FIT_INFEASIBLE)
```

`PetEffectOverlayWindow` 只服务 `FULL_SAMPLED_BOUNDS`。当前正常触发者只有 Special；
Sit/Interact/Sleep 等 BODY_PRIORITY 动作不得因不可行而隐式扩大成本和 scope。

#### BODY ground correction 与 Special effect-underflow 防护

Planner 对每个待评估 facing 先执行 floor normalization，再进入 policy-specific
containment。设原始 visible content bounds 为 `B`，body anchor 为 `a`。
对 `BODY_PRIORITY`：

```text
c   = max(0, B.bottom - 180)
B_c = B + (0, -c)
a_c = a + (0, -c)
```

`ground_correction = c` 是向上移动的正数幅值，renderer translation 为 `-c`，
且对整段动作固定。`FULL_SAMPLED_BOUNDS` 的 Special 不得把整个 effect 的最低点解释成
人物脚底，也不得用 effect-floor correction 上移人物。它只计算 effect underflow：

```text
u_effect = max(0, B.bottom - 180)
if u_effect > MAX_SPECIAL_EFFECT_FLOOR_LIFT (16.0):
    -> LAYOUT_FAILURE(SPECIAL_EFFECT_FLOOR_INFEASIBLE)
else:
    ground_correction = 0
    B_c = B
    a_c = a
```

因此 Special 人物脚底仍与 `body_window_bottom == active_workspace_bottom` 对齐；允许的
effect underflow 由 always-on-top、输入穿透 overlay 绘制在任务栏上方。2px clipping
padding 只扩大 surface，不计入 16px effect underflow 判定。

#### 身体内动作

对 Relax、Move、Sleep、Sit 和 Interact：

1. 保留 Relax 固定缩放；
2. 选择 `preferred_facing`，并消费共同 ground normalization 得到的
   `corrected_content_bounds = B_c` 与 `corrected_body_anchor = a_c`；
3. 实际 renderer translation 使用共同步骤给出的 `-ground_correction`；
4. 使用连续逻辑坐标时要求 `corrected_bounds.bottom <= 180`；对原本接触地面的动作，
   `corrected_bounds.bottom` 应落在闭区间 `[178, 180]`；
5. raster alpha bounds 的 measurement contract 固定为 `alpha > 0`；硬断言仅要求非透明
   raster 不得延伸到 row 180 或更低，不从连续几何反推最低非透明行的下界；
6. 若 `corrected_content_bounds.top < 0`，BODY_PRIORITY layout 不可行并返回
   `PetRenderLayoutFailure(BODY_VERTICAL_INFEASIBLE)`；bootstrap 才负责拒绝候选，runtime
   才负责占位 containment，不得转 overlay、继续上移或静默裁头；
7. BODY_PRIORITY 允许上一设计已批准的横向附件裁剪。当前 Sleep 的 sampled bounds
   正是该情况；不宣称其全部横向内容可见。

12 点 raw bounds 的下沿溢出分别约为：Sit `31.1px`、Interact `4.0px`、
Move `2.0px`、Sleep `7.0px`。ground correction 只使用真实 content bounds，
因此同一诊断集对应 correction 仍约为这些数值。最终值来自 >=60Hz sampled
content bounds，不硬编码这些诊断值。

#### Special 溢出动作

Special 使用 `FULL_SAMPLED_BOUNDS` policy 和 `OVERFLOW` surface：

1. 正常工作区下保持 Relax scale，即 `scale_multiplier == 1`；
2. LEFT/RIGHT 分别检查 effect underflow；通过后保持原始 `B_c=B`、`a_c=a`，且
   `ground_correction=0`；
3. full-scale 路径计算 `padded_bounds = B_c.inflate(2.0)`；2px padding 只服务 surface
   clipping，不参与 ground correction，也不改变人物脚底位置；
4. overlay 坐标通过 `body_window_offset` 满足第 5.4 节坐标不变量；
5. 优先使用当前语义朝向；若该朝向的 sampled visible content bounds 被当前工作区裁剪，
   而镜像朝向可以完整容纳 visible content bounds，
   使用镜像的 `effective_facing`；
6. 只有当 active workspace 在两个朝向下都放不下原尺寸 sampled visible content bounds 时，
   才计算临时 degraded fit；目标是**最大可行缩放系数**，不是最小 scale；
7. 对 facing `f`，以 `fit_anchor_f = Point(a_c.x, 180.0)` 为缩放支点：水平方向保持
   skeleton/body anchor 对齐，垂直方向固定 body ground baseline，避免角色缩放后离地。
   内容变换为 `B_f,s = fit_anchor_f + s * (B_c - fit_anchor_f)`；
8. 顺序固定为：ground-correct content -> 围绕 `fit_anchor_f` 缩放 content ->
   对缩放后的 content 固定 inflate 2 逻辑像素 -> containment/resource test ->
   向外取整 `surface_rect`。padding 不随 `s` 缩成 `2s`；
9. 分别求
   `s_f = max { s | MIN_EFFECT_SCALE_MULTIPLIER <= s <= 1, B_f,s` 的左右和顶部在
   `workspace` 内，底部不超过 `workspace.bottom + 16px` `}`。
   取 `s_f` 较大的 facing，以最大化可见人物尺寸；二者相等时取 `preferred_facing`；
   浮点 tie 使用 `LAYOUT_SCALE_EPSILON = 1e-6`，禁止裸相等比较导致边缘翻向；
10. `MIN_EFFECT_SCALE_MULTIPLIER = 0.40`。若两个 facing 都不存在满足下限的可行 `s_f`，
    返回 `PetRenderLayoutFailure(WORKSPACE_FIT_INFEASIBLE)`，不得把效果缩到失去意义；
11. 成功 degraded fit 返回 `quality=DEGRADED_FIT`，`body_window_offset` 仍由第 5.4 节
    坐标不变量反推；人物不得向 surface 左上角漂移，接地 baseline 仍为 180；
12. degraded fit 不写回 profile/body transform，不改变后续 Relax scale，并记录固定的
   非敏感诊断码 `pet_effect_workspace_fit_degraded`；
13. 除第 5.1 节定义的 environment invalidation 外，同一次 Special 从开始到完成保持
    同一 layout、fit anchor 和有效朝向。

当前素材预计需要约 `375 x 269` 的逻辑 overlay（含安全边距，最终以向外取整为准）。

#### 明确资源上限

布局和 overlay 必须同时满足：

```text
logical_width  <= 1024
logical_height <= 1024
logical_width * logical_height <= 1_048_576
ceil(logical_width * DPR)  <= 4096
ceil(logical_height * DPR) <= 4096
physical_width * physical_height <= 4_194_304
```

逻辑和物理资源检查都以加入 clipping padding 后、最终 outward-rounded 的 surface 为准。
绝对逻辑资源上限在 workspace-fit 之前检查；full-scale sampled envelope 已超出这些上限时
返回 `PetRenderLayoutFailure(LOGICAL_RESOURCE_LIMIT_EXCEEDED)`，不允许通过缩小规避
恶意或异常 profile。
`DEGRADED_FIT` 只解决正常安全 profile 在 active workspace 中放不下的问题。DPR 非有限或
`DPR <= 0` 返回 `INVALID_DPR`；fit 后物理 surface 超限返回
`PHYSICAL_RESOURCE_LIMIT_EXCEEDED`。
Planner 只报告 failure value，bootstrap/runtime 分别执行第 5.4 节定义的拒绝或 containment。

### 5.5 `PetEffectOverlayWindow`

在 `src/arkclaw/presentation/qt/pet_effect_overlay.py` 新增 Qt adapter：

- frameless、translucent、tool window；
- 必须设置 `Qt.WindowDoesNotAcceptFocus` 和 `Qt.WA_ShowWithoutActivating`；不得设置
  全窗口 `WindowTransparentForInput`，而应在身体命中区域代理输入、区域外原生穿透；
- 不进入任务栏，不获取焦点，不创建第二个托盘图标；
- always-on-top、可见性、DPR、当前屏幕和关闭生命周期与身体窗口同步；
- 只在 layout 为 `OVERFLOW` 时显示；其他动作立即隐藏；
- Planner 只允许 `FULL_SAMPLED_BOUNDS` policy 产生 OVERFLOW；adapter 不自行把
  BODY_PRIORITY 提升为 overlay。当前唯一正常 OVERFLOW 动作是 Special；
- Special 期间 sampled 场景只由一个 surface 拥有：overlay 绘制场景，身体窗口暂停同一场景的重复绘制；
  overlay 将身体区域的输入显式转交给身体窗口，后者仍是唯一输入语义所有者；
- native/playback 每个 GUI tick 只 advance 一次。操作系统可请求重复 repaint，
  但 repaint 只能重画缓存状态，不得再次推进 native animation；
- BODY 与 OVERFLOW surface 互斥，不允许二者在同一 frame ownership 下推进或绘制两份场景；
- renderer/overlay 失败恢复采用可见性事务：先准备并验证 body placeholder 可绘制，
  再原子切换 body 为 fallback owner，然后隐藏 overlay，最后销毁故障资源；
- fallback readiness 必须先于 visible-surface switch，避免 blank frame；
- shutdown 时先停止计时器，再隐藏/销毁 overlay，最后释放 renderer/native 资源。

不得通过扩大 `PetMotionModel.window_size` 实现 Special；否则会改变落地高度、
边界碰撞、拖拽 offset 和持久化坐标。

### 5.6 Renderer-neutral 动作身份

当前 `action_request_for_frame` 在非 motion/behavior 状态下统一返回 `IDLE`，
因此 renderer 无法仅凭现有 request 区分 Sit、Sleep、Special 和 Interact。
本轮必须补全已有 `PetRendererAction` 的映射，而不是让 Qt adapter 读取 Track 0 私有状态：

| `PetActivityState` | `PetRendererAction` |
|---|---|
| `SITTING` | `SITTING` |
| `SLEEPING` | `SLEEP` |
| `SPECIAL` | `SPECIAL`（新增） |
| `INTERACT` | `INTERACT`（新增） |

优先级保持：closing、paused、dragging、falling、landing 高于 activity；
activity 高于普通 idle。bootstrap adapter 将 role binding 的 `ProductionAction` 转成
`PetRendererAction` profile key；`Spine38PetRenderer` 只用 renderer-neutral key 选择
`sampled_action_bounds`，不得导入 tray、Qt 菜单或 `ProductionAction` 调度细节。

新增失败测试：

- `test_renderer_request_preserves_sit_sleep_special_and_interact_identity`
- `test_mandatory_motion_renderer_identity_preempts_activity`
- `test_bootstrap_adapts_production_roles_to_renderer_profile_keys`
- `test_spine_layout_selection_does_not_query_track0_private_state`

## 6. 左键单击与拖拽消歧

### 6.1 `PetPointerGesture` seam

在 presentation 层增加一个不依赖 native 或素材的纯状态 module：

```python
class PetPointerGesture:
    def press(self, local: Point, global_: Point, drag_threshold: float) -> None: ...
    def move(self, global_: Point) -> GestureDecision: ...
    def release(self, global_: Point) -> GestureDecision: ...
    def cancel(self, reason: GestureCancelReason) -> GestureDecision: ...
```

状态明确区分 `IDLE`、`PENDING`、`DRAGGING`。`GestureDecision` 仅允许：
`NONE`、`BEGIN_DRAG`、`DRAG`、`CLICK`、`CANCEL_PENDING`、
`RELEASE_ACTIVE_DRAG`、`ABORT_ACTIVE_DRAG`。

阈值来源与距离政策是两个独立决定：

```text
drag_threshold = QApplication.startDragDistance()
gesture_distance(start, current) = abs(dx) + abs(dy)  # Manhattan distance
```

Qt adapter 在每次 press 时读取正的 `QApplication.startDragDistance()`，并把它作为
显式参数交给纯 gesture module；纯 module 不导入 Qt。该参数就是本次 session snapshot，
随后整个 `PENDING/DRAGGING` 只使用 snapshot。手势期间发生的系统设置变化只影响下一次
手势，不得让静止指针因阈值变小而突然开始拖拽。

状态规则：

1. 仅主左键可开始候选手势；
2. 按下时只记录起点和身体窗口 offset，不改变语义状态；
3. 全程最大 Manhattan 位移小于本次 `session_drag_threshold` 时，释放产生一次 `CLICK`；
4. 首次达到阈值时只产生一次 `BEGIN_DRAG`，此时才调用
   `PetAnimationEngine.start_dragging()`；
5. `BEGIN_DRAG` 被接受后，同一事件立即应用当前指针位置，避免窗口跳回按下点；
6. 一旦进入拖拽，本次释放只能产生 `release_drag`，不得再触发 Interact；
7. 在 `PENDING` 中，任何取消原因都只返回 `CANCEL_PENDING`，没有语义副作用；
8. 在 `DRAGGING` 中，取消原因决定不同事务：

```text
POINTER_CAPTURE_LOST
    -> RELEASE_ACTIVE_DRAG
    -> normal release_drag(workspaces)
    -> 允许 FALLING/LANDING

WINDOW_HIDDEN or PAUSE_REQUESTED
    -> ABORT_ACTIVE_DRAG
    -> abort drag, zero velocity, suspend autonomy
    -> 再执行 hide/pause lifecycle policy

RENDERER_DEGRADED or PLAYBACK_DEGRADED
    -> ABORT_ACTIVE_DRAG
    -> existing failure containment, zero velocity, SUSPENDED
    -> 不允许普通 release 进入 FALLING

CLOSING
    -> ABORT_ACTIVE_DRAG
    -> closing transaction 清理 drag token/state and zero velocity
```

9. `ABORT_ACTIVE_DRAG` 需要明确的 application transaction，不得通过普通
   `release_drag()` 模拟；所有 cancellation 路径完成后均不得留下
   `motion == DRAGGING`；
10. 右键、暂停切换和关闭在应用自身生命周期事务开始前先消费 gesture cancellation；
11. 不使用自定义魔法像素阈值，遵从 Windows/Qt 系统阈值来源。

### 6.2 Interact 请求

`CLICK` 满足以下条件时提交：

```text
lifecycle != CLOSING
and motion accepts interaction
and ProductionAction.INTERACT in available actions
```

请求使用 `ActionSource.USER`，经过现有 `PetAnimationEngine.request_action`、
arbiter 和 Track 0 事务，不允许从 Qt 事件直接调用 native player。

若 Interact 不可用、被 arbiter 拒绝或 playback degraded：

- 不播放替代动作；
- 不进入 DRAGGING/FALLING；
- 不移动窗口；
- 保持现有安全状态并返回现有 `ActionOutcome`。

为保持现有调用兼容，`PetWindow.request_pet_action(action)` 继续默认使用
`ActionSource.TRAY`；桌宠点击和桌宠右键菜单通过内部统一提交函数显式传入
`ActionSource.USER`。

## 7. 桌宠右键生产动作菜单

### 7.1 共享菜单 section

将系统托盘中以下菜单构造逻辑提取到
`src/arkclaw/presentation/qt/production_action_menu.py`：

- `Role Pack: <pack_id>`；
- Relax；
- Move -> Left / Right；
- Sit；
- Sleep；
- Special；
- Interact；
- Resume Autonomous。

建议 interface：

```python
class ProductionActionMenuSection:
    def __init__(self, menu: QMenu, callbacks: ProductionMenuCallbacks) -> None: ...
    def update(self, state: ProductionMenuState) -> None: ...
```

系统托盘和桌宠右键菜单是两个真实 adapter，因此共享 seam 有实际价值。
菜单 label、分组、能力禁用规则和 Resume 规则只维护一份。

### 7.2 行为规则

- 系统托盘触发动作继续使用 `ActionSource.TRAY`；
- 桌宠右键菜单触发动作使用 `ActionSource.USER`；
- 不可用动作可见但禁用，不允许静默替换为 Relax；
- `Move` 的两个方向只在对应能力存在时启用；
- closing 时所有生产动作和 Resume 禁用；
- placeholder role pack 固定显示 `Role Pack: placeholder`，生产动作和
  `Resume Autonomous` 保持可见但全部禁用；托盘与桌宠右键菜单采用完全相同规则；
- 动作执行后菜单关闭，播放失败继续由现有安全策略处理。

桌宠原有通用菜单项保持原名称、行为和相对顺序；生产 section 插入在
`Always on top` 之后、`Start with Windows` 之前。

## 8. 落地连续性

### 8.1 选定修复

引擎新增内部“采用已确认 Relax 并恢复自主调度”路径，职责为：

1. 验证 Track 0 健康；
2. 验证 confirmed epoch 存在、物理动画为 Relax、loop 为真；
3. 保留原 generation、playback token 和同一个 Track 0 epoch；
4. 将语义 motion 从 LANDING 完成到 IDLE；
5. 将 active production action 设为 Relax；
6. 采样一个新的 Relax dwell；
7. 进入 `AUTONOMOUS`；
8. 不调用 `clear`，不调用 `play(Relax)`。

该路径只用于缺少 drag/fall/land 动画且已经使用健康 Relax fallback 的生产角色。
若 epoch、health 或逻辑/物理动作不满足条件，保持速度为零并进入 `SUSPENDED`，
不得假装恢复成功。

### 8.2 连续性不变量

`generation_before` 和 `playback_token_before` 的取样时刻固定为：拖拽开始已经合法切换到
Relax fallback、且该 Relax epoch 已 confirmed 之后。它们不是 mouse press 前的 Special/Sleep
epoch，也不是 `start_dragging()` 调用前的值。

从该 confirmed Relax fallback 开始，直到 adoption transaction 提交并发布第一个
`IDLE + AUTONOMOUS` snapshot：

```text
generation_before == generation_after
playback_token_before is playback_token_after
clear() call count 不变
play(Relax) call count 不变
vertical_velocity 在接地时归零
```

不得用 loop-local `animation_time` 单调性证明连续性。Relax 局部时间允许在循环边界合法地
从接近 `T` 回绕到接近 `0`。只有 bridge 已经提供不随 loop 回绕的 epoch/track elapsed time 时，
它才可作为附加诊断；本轮必要断言以上述 epoch 身份和 player call count 为准。
测试窗口不延伸到下一次 autonomous Relax dwell/loop boundary；到那时 scheduler 可能合法选择
新动作并产生新的 `play()`，不属于落地 adoption 连续性。

位置不变量从 accepted `release_drag` 开始，而不是从 mouse press/拖拽开始：

```text
DRAGGING: 不声明 y 单调性，允许用户向上或向下拖动
FALLING:  vertical_velocity >= 0
          y_next = min(y_current + delta_y, floor_y)
          y_next >= y_current
LANDING:  y == floor_y
IDLE:     y == floor_y
floor_y = workspace_bottom - body_height
```

计时器仍使用现有 monotonic clock 和最大 delta 限制。第一轮实现不得同时修改重力、
终端速度或 timer interval，以便单变量验证“重播 Relax”是否为卡顿原因。

如果修复播放连续性后，Windows 帧间隔证据仍显示卡顿，再提出独立性能 TDD，
不得在本轮混入未经测量的物理调参。

## 9. 事务顺序

### 9.1 单击 Interact

```text
mouse press
  -> gesture candidate
mouse release below threshold
  -> request Interact(USER)
  -> arbiter preflight
  -> semantic + Track 0 commit
  -> renderer state/layout update
  -> body surface remains fixed
```

### 9.2 Special

```text
request Special
  -> Track 0 + semantic transaction accepted
  -> projector produces LEFT/RIGHT projected sampled bounds
  -> select fixed Special layout from precomputed profile
  -> choose current or inward effective render facing
  -> configure renderer viewport
  -> show selectively input-proxying overlay
  -> each GUI tick advances native animation exactly once
  -> BODY xor OVERFLOW owns visible scene; repaint never advances native state
  -> completion event commits recovery
  -> hide overlay
  -> restore body rendering without restarting unrelated playback
```

任何一步失败均不得留下空白大窗口、不可点击区域或悬挂 overlay。

### 9.3 拖拽和落地

```text
press -> threshold crossed -> begin drag
  -> confirmed looping Relax fallback
release -> falling/landing
  -> keep same Relax epoch
landing complete
  -> adopt confirmed Relax
  -> fresh autonomous dwell
```

## 10. TDD 实施顺序

每一切片必须先看到指定测试因缺失行为而失败，再写最小实现使其通过。

### Slice A：冻结高密度 sampled bounds 与类型层

先增加失败测试：

- `test_real_schwarz_sit_sampled_bounds_report_bottom_overflow`
- `test_real_schwarz_special_sampled_bounds_contain_observed_effect_geometry`
- `test_profile_samples_at_least_sixty_hz_and_includes_terminal_pose`
- `test_profile_sampling_uses_non_loop_mode_to_expose_terminal_pose`
- `test_loop_profile_accepts_duplicate_terminal_sample_without_special_case`
- `test_non_loop_profile_includes_terminal_pose`
- `test_short_animation_uses_twelve_intervals_and_thirteen_endpoint_inclusive_samples`
- `test_duplicate_physical_names_share_one_sample_set`
- `test_profile_uses_renderer_neutral_action_keys`
- `test_profile_mapping_is_defensively_copied_and_immutable`
- `test_profile_rejects_duration_over_role_pack_contract`
- `test_profile_rejects_uniform_sample_allocation_over_3601`
- `test_profile_rejects_merged_sample_allocation_over_4096`
- `test_high_density_profile_does_not_recalibrate_frozen_relax_body_transform`

实现 `RolePackRenderProfile`，保持 Relax 身体缩放不变。

### Slice B：唯一投影 seam 与 BODY 地面校正

先增加失败测试：

- `test_projector_uses_same_body_transform_as_renderer`
- `test_projector_returns_explicit_left_and_right_content_with_body_anchors`
- `test_projector_mirrors_bounds_and_anchor_about_declared_body_axis`
- `test_projected_envelope_contains_no_surface_padding`
- `test_sit_ground_correction_exposes_lowest_visible_pixel`
- `test_interact_ground_correction_exposes_lowest_visible_pixel`
- `test_ground_correction_is_positive_magnitude_but_translation_is_negative`
- `test_ground_correction_translates_content_and_body_anchor_together`
- `test_ground_normalization_is_shared_by_body_and_full_sampled_bounds_policies`
- `test_continuous_bottom_uses_180_boundary_not_raster_row_180`
- `test_nontransparent_raster_never_extends_below_row_179_without_asserting_lower_row`
- `test_body_priority_with_negative_corrected_top_fails_layout_without_overlay`
- `test_layout_failure_reasons_are_explicit_and_exhaustive`
- `test_bootstrap_rejects_failed_layout_while_runtime_uses_placeholder_containment`
- `test_only_full_sampled_bounds_policy_can_select_overflow`
- `test_sleep_body_priority_allows_declared_horizontal_attachment_crop`
- `test_action_ground_correction_is_constant_for_whole_animation`
- `test_relax_scale_is_identical_before_during_and_after_correction`

实现 `PetActionEnvelopeProjector` 和纯 `PetRenderLayoutPlanner` 的 BODY 分支。

### Slice C：Special overflow layout

先增加失败测试：

- `test_special_layout_preserves_body_scale_and_contains_projected_sampled_bounds`
- `test_special_layout_faces_inward_when_current_side_is_clipped`
- `test_special_layout_preserves_current_facing_when_both_sides_fit`
- `test_special_layout_uses_degraded_fit_only_when_neither_facing_fits`
- `test_degraded_fit_selects_facing_with_largest_feasible_scale`
- `test_degraded_fit_scale_tie_preserves_preferred_facing`
- `test_degraded_fit_uses_body_anchor_x_and_ground_baseline_y`
- `test_degraded_fit_preserves_ground_contact`
- `test_degraded_fit_rejects_scale_below_minimum_effect_floor`
- `test_degraded_fit_preserves_body_window_offset_coordinate_invariant`
- `test_degraded_fit_does_not_mutate_role_pack_or_later_relax_scale`
- `test_surface_padding_expands_overlay_without_shifting_content_or_ground`
- `test_degraded_fit_preserves_two_pixel_post_scale_clipping_padding`
- `test_overlay_layout_enforces_logical_and_physical_resource_limits`
- `test_special_layout_is_stable_across_all_sampled_frames`

实现 planner 的 OVERFLOW 分支，不接 Qt。

### Slice D：透明 overlay adapter

先增加失败测试：

- `test_special_shows_one_input_transparent_overlay_without_resizing_body`
- `test_overlay_tracks_body_origin_and_selected_screen_in_logical_pixels`
- `test_overlay_dpr_change_rebuilds_physical_surface_only`
- `test_same_workspace_dpr_change_preserves_logical_layout_facing_and_scale`
- `test_material_screen_change_cancels_special_before_hiding_overlay`
- `test_material_workspace_change_never_replans_or_flips_active_special`
- `test_overlay_sets_transparent_no_focus_and_show_without_activating_flags`
- `test_special_scene_is_not_double_painted`
- `test_special_tick_advances_native_player_exactly_once`
- `test_repaint_redraws_cached_state_without_advancing_native_player`
- `test_special_completion_hides_overlay_and_restores_body_surface`
- `test_overlay_failure_prepares_body_fallback_before_visible_surface_switch`
- `test_overlay_failure_never_publishes_blank_frame`
- `test_shutdown_destroys_overlay_before_native_renderer`

再实现 `PetEffectOverlayWindow` 和最小 PetWindow 接线。

### Slice E：click/drag 手势

先增加失败测试：

- `test_left_click_below_system_drag_threshold_requests_interact_once`
- `test_left_click_does_not_enter_dragging_falling_or_landing`
- `test_crossing_system_drag_threshold_starts_drag_without_interact`
- `test_drag_starts_at_current_pointer_without_position_jump`
- `test_unavailable_interact_click_is_side_effect_free`
- `test_closing_or_cancelled_pointer_session_never_dispatches_interact`
- `test_gesture_uses_manhattan_metric_with_qt_threshold_source`
- `test_gesture_snapshots_drag_threshold_at_press`
- `test_threshold_change_during_pending_applies_only_to_next_gesture`
- `test_lost_capture_before_threshold_is_side_effect_free`
- `test_lost_capture_after_begin_drag_releases_into_normal_recovery`
- `test_renderer_degraded_during_drag_aborts_with_zero_velocity_and_no_fall`
- `test_hide_pause_and_close_cancellation_leave_no_dragging_state`
- 更新原 `QTest` 拖拽测试，使其移动超过系统阈值后才期待 DRAGGING。

先测试纯 `PetPointerGesture`，再测试真实 `QTest.mousePress/move/release` 链。

### Slice F：共享右键动作菜单

先增加失败测试：

- `test_pet_context_menu_exposes_same_production_actions_as_tray`
- `test_pet_context_menu_dispatches_user_source`
- `test_tray_menu_retains_tray_source`
- `test_both_menus_apply_identical_capability_disabling`
- `test_placeholder_menus_keep_actions_visible_but_disabled`
- `test_closing_menu_state_disables_all_commands`

实现 `ProductionActionMenuSection`，用共享 section 替换托盘内重复构造逻辑。

### Slice G：无重播落地恢复

先增加失败测试：

- `test_landing_adopts_existing_confirmed_relax_epoch_without_clear_or_play`
- `test_continuity_baseline_is_confirmed_drag_fallback_relax_epoch`
- `test_loop_local_animation_time_may_wrap_without_new_epoch`
- `test_drag_fall_land_does_not_add_clear_or_relax_play_calls`
- `test_landing_recovery_samples_fresh_dwell_without_new_generation`
- `test_landing_continuity_ends_at_first_published_idle_autonomous_snapshot`
- `test_invalid_or_degraded_relax_epoch_stays_suspended_with_zero_velocity`
- `test_dragging_has_no_monotonic_y_requirement`
- `test_falling_y_is_monotonic_only_after_accepted_release`
- `test_floor_contact_publishes_no_overshoot_or_bounce_frame`

实现 adoption 路径，并运行原有拖拽、自治和 Track 0 回归测试。

### Slice H：真实 Windows 验收

- 用真实 Schwarz 素材分别捕获 Sit、Special、Interact 和拖拽落地；
- DPR `1.0 / 1.25 / 1.5 / 2.0` 各执行一次；
- 至少测试一个底部任务栏、一个非 100% 缩放、一个靠左和一个靠右的 Special；
- 验证 overlay 身体区域可点击和拖拽，区域外仍可点击其下方桌面；
- 连续完整播放 Special 多次，人工检查 >=60Hz sampled bounds 之间没有遗漏靶子极值；
- 在足够大的工作区确认 `FULL_SCALE`，在合成小工作区确认并记录 `DEGRADED_FIT`；
- 记录落地前后 Track 0 generation/token，证明没有重播；
- 人工确认落地无可见停顿、闪回或一帧姿态跳变。

### 实现提交分组

为隔离风险，批准后的实现至少拆成三个可独立验证的提交组：

1. **Render composition（Slices A-D）**：采样、类型、projector、planner 和 overlay；
2. **Input and menus（Slices E-F）**：pointer gesture、Interact 和共享菜单；
3. **Landing continuity（Slice G）**：Relax epoch adoption。

Slice H 是三组完成后的 Windows 验收，不与任一实现提交混合。某一组失败不得迫使另外两组
一起回滚或调试。

## 11. 测试层次与验收门

### 11.1 Unit

- profile 采样、projector、布局规划、朝向选择和 ground correction 使用纯数据测试；
- pointer gesture 使用确定坐标、Manhattan metric 与注入的系统阈值测试；
- landing adoption 使用 fake player、fake clock 和 fake random；
- 不断言私有字段；通过公开 snapshot、player calls 和 layout 结果观察行为。

### 11.2 Qt

- 使用真实 `QTest` 事件链，不直接调用 mouse event handler；
- 验证身体窗口尺寸、位置、overlay flags、可见性和关闭顺序；
- 菜单测试通过可见 action 文本、enabled 状态和回调结果验证共享 interface；
- offscreen 平台只验证逻辑；Windows 平台验证输入穿透和实际窗口组合。

### 11.3 Real Schwarz

- 哈希、catalog、Spine 版本和 texture page count 继续先行验证；
- 自动渲染 alpha bounds 必须覆盖 Sit 最低像素和 Special 的全部 >=60Hz
  projected sampled content bounds 及固定 2px clipping padding；
- Relax 身体高度仍在 `153..171`，基准目标仍为 `162`；
- 非 Special 动作身体窗口仍为 `160 x 180`；
- active workspace 足够容纳原尺寸 projected sampled content bounds 及固定 2px clipping
  padding 时，Special 不得降低 Relax scale；
- 小工作区 `DEGRADED_FIT` 必须显式可观察，且不得修改 role-pack scale；
- 自动化不声称 sampled bounds 等同连续 animation envelope；完整连续播放仍需 Windows 人工验收。

### 11.4 回归门

必须通过：

```text
pytest 全量 Python/Qt suite
ruff check src tests
mypy src
CTest spine38_bridge_contract
git diff --check
真实 Schwarz catalog + smoke
```

原有半开区间、16px 可恢复拖拽条、左右镜像、60 秒自治 liveness、
显式动作 hold、失败占位降级和 Agent isolation 均不得回归。

## 12. 最终验收标准

实现只有在以下条件全部满足时才算完成：

1. Sit 全部 >=60Hz profile 采样中，对接地动作的连续逻辑
   `178 <= corrected_bounds.bottom <= 180`；以 `alpha > 0` 测得的非透明 raster 不得延伸
   到 row 180 或更低，但不由连续几何规定其最低非透明行下界；
2. Sit、Interact 的人物缩放与 Relax 相同，动作过程中无逐帧缩放或上下泵动；
3. 自动化证明 Special 的全部 projected sampled content bounds 与固定 2px clipping
   padding 可见；允许 effect content 在任务栏方向下探最多 16px，但人物 body anchor
   和 ground baseline 不得上移；
   Windows 连续完整播放人工确认人物和靶子没有采样间遗漏；
4. active workspace 足够容纳原尺寸 projected sampled content bounds（底部含 16px
   effect underflow 容差）及固定 2px clipping padding 时，Special 必须保持 Relax scale；
   只有两个 facing 都放不下时才允许显式 `DEGRADED_FIT`；降级时选择最大可行 scale 的
   facing、同值保留 preferred facing，且 `scale_multiplier >= 0.40`；
5. Special overlay 不改变身体窗口的 `160 x 180` 物理语义，不改变落地高度和持久化坐标，
   并满足 `surface top-left + body_window_offset = body window top-left`；
6. Special overlay 不获取焦点、不进入任务栏；身体区域输入转交给 PetWindow、区域外不拦截
   桌面，动作结束或失败后立即消失；
7. 每个 GUI tick 最多推进一次 native animation；repaint 不推进，BODY/OVERFLOW surface ownership 互斥；
8. 左键单击只提交一次 Interact，不进入拖拽或下落；
9. 超过 press 时 snapshot 的系统阈值之 Manhattan 位移只执行拖拽，不触发 Interact；
   当前手势期间的系统阈值变化只影响下一次手势；pointer capture lost
   使用 normal release，而 renderer/playback degraded 使用 abort containment；两者均不遗留 DRAGGING；
10. 桌宠右键菜单和系统托盘提供同一组生产动作、能力禁用和 Resume 规则；
    placeholder 动作可见但全部禁用；
11. 桌宠右键和左键 Interact 请求使用 USER source，托盘保持 TRAY source；
12. 从 confirmed drag-fallback Relax 开始，到 adoption 提交并发布第一个
    `IDLE + AUTONOMOUS` snapshot，generation/token 不变且没有新增 `clear()` 或
    `play(Relax)`；loop-local animation time 允许正常回绕；
13. accepted release 后 FALLING 的 y 单调不减且不超过 floor；LANDING/IDLE 固定在 floor；
14. 落地接触帧无工作区越界、反弹或 playback transaction 重启；
15. overlay 故障时 body placeholder 先 ready，再切换可见 owner 和隐藏 overlay，不出现 blank frame；
16. logical/physical overlay 尺寸和面积不超过第 5.4 节固定上限；
17. Planner 的六类 failure reason 均可观察；三类 candidate-static failure 由 bootstrap
    preflight 拒绝，三类 environment failure 由 runtime 进入占位 containment。
    renderer/playback/overlay 任一失败后速度为零、自治停止且占位降级可用；
18. 全量自动化门和真实 Schwarz smoke 通过；
19. 用户完成目标 Windows/DPR 人工视觉审查并明确接受。

## 13. 风险与控制

### Overlay 与选择性输入代理

风险：Windows/Qt 对分区 hit-test 和 overlay 手势代理的行为可能与 offscreen 平台不同。

控制：Windows 专项 QTest/Win32 验收；身体窗口始终保留；身体区域 press 后保持代理到
release；overlay 故障后先准备可绘制的 body placeholder，再切换 visible owner、隐藏
overlay 并释放故障资源，避免空白帧。

### 多显示器和 DPR

风险：overlay 跨屏或跨 DPR 时可能偏移一像素或重建 framebuffer。

控制：以身体中心选择 active screen；布局只使用该屏幕逻辑工作区。同一 logical workspace
内仅 DPR 改变时只重建物理 framebuffer，不改变 logical layout；active screen 或 logical
workspace 实质变化时，先准备正常 BODY 状态，再安全取消当前 Special 并隐藏 overlay，
不得在动作中途重新规划、翻向或缩放。

### 动作切换时闪烁

风险：身体 surface 与 overlay 同时显示或同时隐藏一帧。

控制：先完成 renderer/layout 准备，再在一个 GUI turn 中切换 surface；
测试要求不存在 double paint 或 blank frame。

### 菜单逻辑重复

风险：托盘和桌宠菜单再次分叉。

控制：两个入口必须使用同一 `ProductionActionMenuSection`，测试比较同一状态下的完整 action map。

## 14. 非目标

本轮不包含：

- 编辑、复制或重新导出 Schwarz 素材；
- 新增 Drag、Fall、Land Spine 动画；
- 修改自治概率矩阵或 60 秒 liveness；
- 修改重力、timer interval 或人为添加落地慢动作；
- 让任意尺寸、任意内容的第三方 role pack 无限制创建超大 overlay；
- 声称有限离散 sampled bounds 能数学证明连续动画的全局几何极值；
- 用透明大窗口替代固定身体命中窗口；
- 修改本设计未覆盖的运行行为。

## 15. 审查清单

用户审查时请重点确认：

- 是否接受 Special 使用临时选择性输入代理 overlay，而不是把人物缩小到约 41%；
- 是否接受 Special 靠近屏幕边缘时临时朝屏幕内部展示，以优先完整显示靶子；
- 是否接受只有在两个朝向的 visible content 都放不下时才使用带诊断码的临时
  `DEGRADED_FIT`，且透明 2px clipping padding 不参与 workspace fit 判定；
- 是否接受 Special effect geometry 最多只允许造成 16px scene-floor lift，超过则
  fail closed；
- 是否接受自动化保证 >=60Hz sampled bounds，而连续动画完整性由 Windows 完整播放最终确认；
- 是否接受“左键移动达到 Windows 系统拖拽阈值才开始拖拽”；
- 是否接受落地流畅性本轮先以“保持同一 Relax epoch”修复，若仍卡顿再依据帧间隔证据单独调优；
- 右键动作菜单插入位置和动作集合是否符合预期。

## 16. 本轮评审意见闭环

| 编号 | 级别 | 修订结果 |
|---:|---|---|
| 1 | P0 | 12 点降为诊断证据；发布 profile 改为 >=60Hz `sampled_action_bounds`，连续完整性交由 Windows 验收 |
| 2 | P0 | Planner 改为显式接收 LEFT/RIGHT 两份 `ProjectedActionEnvelope` |
| 3 | P0 | 新增唯一 `PetActionEnvelopeProjector` 和共享 `PetBodyTransform` |
| 4 | P0 | full scale 与小屏 fit 改为 `FULL_SCALE`/`DEGRADED_FIT` 条件契约 |
| 5 | P0 | y 单调性起点改为 accepted release；DRAGGING 明确无单调约束 |
| 6 | P0 | 删除 loop-local time 单调断言，改测 epoch 身份及 clear/play call count |
| 7 | P0 | profile 统一以 `PetRendererAction` 索引，并新增真正的 `SPECIAL`/`INTERACT` 值 |
| 8 | P1 | 分离连续 bottom `[178,180]` 与 raster 上限；不再由连续几何断言最低非透明行下界 |
| 9 | P1 | `ground_correction` 定义为向上正幅值，实际 translation 明确为负 |
| 10 | P1 | corrected top 越界时 BODY_PRIORITY 明确返回 LAYOUT_FAILURE，绝不转 OVERFLOW |
| 11 | P1 | gesture 区分 PENDING/DRAGGING，active cancellation 必须结束 engine drag |
| 12 | P1 | 阈值来源固定为 Qt system setting，距离政策固定为 Manhattan |
| 13 | P1 | placeholder 菜单固定为动作可见但禁用 |
| 14 | P1 | fallback 先 ready，再切 visible owner，最后隐藏/销毁 overlay |
| 15 | P1 | 正式冻结每 tick advance 一次、repaint 不 advance、surface owner 互斥 |
| 16 | P1 | 固定 logical dimension/area 与 physical dimension/area 上限 |
| 17 | P1 | profile mapping defensive-copy 后以 `MappingProxyType` 冻结 |
| 18 | P2 | generation baseline 固定在 drag fallback Relax confirmed 之后 |
| 19 | P2 | 补充 Move/Sleep 真实 bounds，并明确 Sleep 横向附件采用 body-priority crop |
| 20 | P2 | 实现拆分为 Render、Input/Menu、Landing 三个提交组 |

## 17. 第二轮评审意见闭环

| 编号 | 级别 | 修订结果 |
|---:|---|---|
| 1 | P0 | 所有 profile 采样统一使用 non-loop mode，并采 `i=0..N`，one-shot 与 loop 均包含 terminal pose |
| 2 | P0 | `ProjectedActionEnvelope` 删除无来源的 action 字段，保持纯几何职责 |
| 3 | P0 | LEFT/RIGHT 分别携带 body anchor；后续 Revision 4 将 degraded fit 支点细化为 body anchor x 加 ground baseline y |
| 4 | P0 | policy matrix 冻结为 BODY_PRIORITY 不可行即 fail，只有 FULL_SAMPLED_BOUNDS 可 OVERFLOW |
| 5 | P1 | content bounds 与 2px clipping padding 分离；ground correction 不再受 padding 影响 |
| 6 | P1 | cancellation reason 区分 normal release 与 failure abort，degraded 路径禁止进入 FALLING |
| 7 | P2 | `T<=60s` 定义为 duration contract，`N<=3600`/sample count `<=3601` 定义为 allocation contract |
| 8 | P2 | landing 连续性终点改为 adoption 提交并发布首个 `IDLE + AUTONOMOUS` snapshot |

## 18. 第三轮评审意见闭环

| 编号 | 级别 | 修订结果 |
|---:|---|---|
| 1 | P0 | Planner 返回显式 `PetRenderLayoutResult`；Revision 4.1 将 reason 细化为六类并冻结 static/environment ownership |
| 2 | P0 | floor normalization 提升为公共前置概念；Revision 4.1 进一步区分 BODY ground correction 与 Special scene-floor correction |
| 3 | P0 | degraded fit 冻结为最大可行 scale；Revision 4.1 用 1e-6 epsilon 定义双 facing tie，并在缩放后固定增加 2px padding |
| 4 | P0 | `body_offset` 更名为浮点 `body_window_offset`，并用 surface/body/anchor 方程冻结语义 |
| 5 | P0 | 同 workspace 的 DPR-only 变化只重建 framebuffer；实质 screen/workspace 变化安全取消当前 Special |
| 6 | P1 | 清除 BODY 不可行转 OVERFLOW 的旧闭环结论，统一为 typed LAYOUT_FAILURE |
| 7 | P1 | workspace fit 只看 visible content；padding 仅决定 surface allocation/resource |
| 8 | P1 | 原 input-transparent 契约由 Revision 4.5 取代；保留 does-not-accept-focus、show-without-activating，并新增身体区域输入代理 |
| 9 | P1 | 系统拖拽阈值在 press 时做 gesture snapshot，运行中变化只影响下一次手势 |
| 10 | P1 | raster 硬断言不得延伸到 row 180 或更低位置；不再由连续几何推导最低非透明行下界 |
| 11 | P2 | 冻结既有 12 点 Relax calibration；高密度 profile sampling 不重新校准身体 scale |
| 12 | P2 | `DEGRADED_FIT` 设置 0.40 质量下限，并以 body anchor x 与 ground baseline y 组成缩放支点 |

## 19. 第四轮评审意见闭环

| 编号 | 级别 | 修订结果 |
|---:|---|---|
| 1 | P0 | workspace/resource 安全检查改为基于最终 outward-rounded surface；visible content containment 与透明 2px padding 分离 |
| 2 | P0 | Special 不再把 effect 最低点解释成人物脚底；Revision 4.2 根据真实 >=60Hz 采样把 `MAX_SPECIAL_EFFECT_FLOOR_LIFT` 从 2.0 调整为 16.0，超过仍为 typed failure |
| 3 | P0 | profile sampling 冻结 canonical setup/reset/zero-mix 隔离，要求 sampling-order independence |
| 4 | P1 | 六类 failure reason 明确拆分为 candidate-static 与 runtime-environment ownership |
| 5 | P1 | `PetPointerGesture.press()` 显式接收本次系统阈值 snapshot |
| 6 | P1 | degraded-fit facing tie 使用 `LAYOUT_SCALE_EPSILON=1e-6`，禁止裸浮点相等 |

## 20. Revision 4.2 真实素材修订

真实 Schwarz 的 >=60Hz 隔离采样在 `Special` 约 `t=0.466s` 捕获到
`15.8645px` scene-floor correction；即使只看完全不透明几何仍需约 `12.2637px`。
用户批准把上限从 `2.0px` 调整为 `16.0px`，以保留完整 sampled visible content。
该修订不改变 2px clipping padding、160×180 身体窗口、工作区 containment 或
`SPECIAL_EFFECT_FLOOR_INFEASIBLE` 的 fail-closed 语义。

## 21. Revision 4.3 首次实现后人工验收修订

首次 Windows 人工验收确认 Special 靶子完整显示、左键单击 Interact 正常；同时发现：
Special 人物因整段场景上移约 15.86px 而悬空，动作切换存在明显硬切，并有一次进程自行
退出及 Sleep→Interact 后动作不可继续选择的报告。

本修订冻结以下最小改动：

1. Special 的 16px 限值改为 effect underflow 容差，不再是 scene lift；通过检查后
   `ground_correction` 固定为 0，overlay 可以向任务栏方向延伸，人物脚底仍贴合任务栏；
2. bootstrap 的 `set_animation` 继续执行 canonical setup/reset/zero-mix，以保持采样隔离；
   正常播放新增独立的 `mix_animation` 路径，使用 Spine `TrackEntry.mixDuration=0.12s`；
3. `CancellationMode.REPLACE` 先预检新动作，再直接安装新 Track 0 entry，不先 clear
   旧 entry；安装失败仍执行既有 clear containment。这样旧 pose 才能成为混合来源；
4. native completion listener 只发布当前 Track 0 entry 的事件，混出中的旧 entry 不得
   产生身份不匹配回调；
5. 一个 GUI tick 内，native `update()` 和逐个 `handle_playback_event()` 共同处于窗口异常
   边界。任一步骤抛出异常都只触发一次占位降级、清空生产能力并断开事件源，不允许异常
   穿过 Qt timer 边界导致进程退出；
6. 压力门固定覆盖至少 50 轮 `Sleep -> 左键 Interact -> Sit` 高频序列；所有显式请求
   必须 accepted，结束时进程存活、role pack 仍为 `schwarz-production`、7 个动作可用且
   renderer safe code 为 `none`。

原报告中的动作锁死在 50 轮真实资源压力序列中未复现，因此本修订不声称已定位其唯一
触发根因；上述事件边界、旧 entry 事件过滤和无 clear 替换共同封闭了已确认的失稳路径。
若人工复核仍能复现，需要保留准确时间点并收集该次进程的 WER/诊断码继续归因。

## 22. Revision 4.4 第二次实现后人工验收修订

第二次人工验收报告了四项问题：Special/Interact 结束切换时空白闪烁和位置偏移、
Special 播放期间无法直接操控、Sleep 播放期间拖拽后所有动作被拒绝，以及 Move 自治
出现频率偏低。

### 22.1 已复现根因

Sleep 的真实最小复现为：

```text
request Sleep -> start dragging -> release -> landing -> IDLE
-> request Special == REJECTED_PRIORITY
```

落地后的 Track 0 仍由 `PRODUCTION_MOTION_FALLBACK` 的 `USER_INTERACTION + HOLD`
请求占有。虽然同一 confirmed Relax epoch 已被视觉上采用为 autonomous Relax，controller
的 active request authority 并未同步转换，导致后续所有普通显式动作被优先级仲裁拒绝。

闪烁的确定性根因为：`mix_animation()` 安装新 entry 后清空 draw commands，但同一 GUI tick
不会再次推进 native runtime；BODY/OVERFLOW owner 已经切换，却只能读取空 draw list，
形成一个可见空帧。若继续对 Special/Interact 使用骨骼 pose mix，旧动作几何还会在新动作
layout 中绘制，造成裁剪和 ground correction 偏移。

### 22.2 修订后的行为

1. 落地时通过 `PetTrack0Controller.adopt_active_playback()` 将同一 Relax epoch 的 active
   request 从 motion fallback 原子转换为 `PRODUCTION_RELAX`；不 clear、不 play、不改变
   generation/token，但后续显式动作可以正常替换；
2. native `mix_animation()` 成功安装 entry 后立即执行一次 `update(0)` 并物化 time-zero
   draw commands，BODY/OVERFLOW owner 在当前 tick 总能取得有效帧；
3. Special/Interact 对应的 layout-exclusive action 在进入和离开时使用零 pose mix，禁止
   旧溢出几何进入新 layout。其他布局兼容动作继续使用 0.12s Spine mix；
4. 桌宠窗口来源的 `USER` 动作可以立即中断 Special/Interact；托盘与 Agent 请求仍按原
   规则排队到 protected one-shot 完成，避免改变非直接操控语义；
5. Revision 4.5 已取代本条最初的全窗口输入穿透方案；覆盖层改为仅在 160×180 身体
   命中区域返回 `HTCLIENT` 并显式代理输入，区域外仍返回 `HTTRANSPARENT`；
6. Relax 转移行中 Move Left/Right 权重由 `10 + 10` 小幅提高为 `12 + 12`，总 Move
   概率从 20% 调整为 24%；左右对称，Sleep 状态仍不会突然转入 Move。

### 22.3 新增验收门

- Sleep 任意播放阶段拖拽并落地后，下一个 Special/Sit/Sleep 请求必须 accepted；
- Special 播放中直接单击或拖拽必须立即改变当前交互，不得仅静默排队；
- `mix_animation()` 返回成功时 draw count 必须非零；
- Special/Interact 与其他动作相互切换时不得混入旧 pose；
- Windows overlay 在身体命中区域必须返回 `HTCLIENT`，区域外必须返回
  `HTTRANSPARENT`；
- 真实 Schwarz 至少执行 5 组 Sleep→拖拽→Special→Interact→Sit 复合压力序列，所有
  显式请求 accepted，结束时 role、7 项能力、renderer safe code 和窗口存活状态正常。

## 23. Revision 4.5 第三次实现后人工验收修订

第三次人工验收确认 Revision 4.4 的“全窗口输入穿透即可操控”结论不成立：Special
播放期间鼠标仍无法选中桌宠，动作结束后也仍能观察到闪烁。

### 23.1 已复现根因

1. overlay 中显示的内容使用扩展 surface；即使 Windows 将某一点穿透，该屏幕坐标也
   不保证命中下面固定的 160×180 身体窗口。因此“覆盖层透明”不能推出“桌宠可操作”；
2. `QWidget.update()` 只登记异步绘制请求。旧逻辑调用 `self.update()` 后立即隐藏 overlay，
   BODY backing store 尚未生成新帧，存在无可见 owner 的空白窗口期；
3. BODY/OVERFLOW 发布发生在主窗口移动之前时，新 BODY 帧可能在旧坐标绘制，随后窗口
   再跳到 motion snapshot 坐标，形成切换位置偏移。

### 23.2 修订后的行为

1. overlay 在 `body_window_offset + 160×180` 区域内成为输入代理：Windows
   `WM_NCHITTEST` 返回 `HTCLIENT`，Qt 左键 press/move/release 和 context menu 事件按
   全局坐标重映射并发送给唯一的 `PetWindow` 输入所有者；
2. 身体区域外保持 `HTTRANSPARENT`，避免完整 Special surface 阻挡无关桌面区域；
3. 一旦身体区域内的左键 press 被主窗口接受，代理保持到 release；拖拽离开初始身体
   区域后 move/release 仍继续转发，不会中途丢失手势。若此时渲染已切回 BODY，overlay
   同步清空为透明输入代理，待 release 后才真正隐藏；
4. GUI tick 先把主窗口移动到 motion snapshot 坐标，再发布 surface owner；
5. OVERFLOW→BODY 时先同步 `repaint()` 已准备的 BODY 帧，确认新 backing store 已绘制后
   再隐藏旧 overlay，禁止观察到 blank owner。

### 23.3 新增验收门

- overlay 身体区域的真实/Qt 左键 click 必须到达 `PetWindow`；
- 从身体区域开始并移出 overlay 的拖拽，其 move 与 release 必须完整到达 `PetWindow`；
- overlay 身体区域内/外的 Win32 hit-test 必须分别为 `HTCLIENT`/`HTTRANSPARENT`；
- OVERFLOW→BODY 的同一发布调用返回时，BODY 至少已经绘制一帧且旧 overlay 已隐藏；
- BODY 同步绘制时的窗口坐标必须等于该 tick 的 motion snapshot 坐标。
