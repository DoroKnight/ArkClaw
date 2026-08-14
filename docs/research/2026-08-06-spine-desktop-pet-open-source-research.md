# ArkClaw Spine 3.8 桌宠开源项目研究

日期：2026-08-06

## 研究范围与结论

本次只查阅项目官方仓库、官方源代码和 Esoteric Software 官方文档。结论是：ArkClaw 可以借鉴开源项目的**状态拆分、触发规则、失败回退和程序架构**，但不应复制任何第三方角色图像、动画帧、Spine 工程或宠物包。

最可靠的组合是：

- 使用官方 Spine 3.8 Runtime 的 `AnimationState`、Track、Mix、Listener 和 Skin 机制定义运行时合同。
- 借鉴 VPet 的 `Start -> Loop -> End -> Normal` 生命周期以及拖拽专用状态。
- 借鉴 Shimeji 的“行为选择与动作表现分离”以及拖拽、抛出、下落、着地链路。
- 借鉴 OpenPets 的定时提醒、可暂停/推迟提醒、Agent 反应和插件隔离概念。

没有找到一个同时满足“公开可编辑 `.spine` 源工程、明确允许复用角色动画资产、与 Spine 3.8 兼容、并已把 idle/breathing/blink 分层”的一手项目。因此，`breathing` 和 `blink` 的制作依据应是当前角色自己的 `Relax` 时间轴与官方 Track 叠加规则，而不是复制第三方动画数据。

## 1. Esoteric Software Spine Runtimes 3.8

### 一手来源

- [官方 spine-runtimes 仓库的 3.8 分支](https://github.com/EsotericSoftware/spine-runtimes/tree/3.8)
- [3.8 分支 LICENSE](https://github.com/EsotericSoftware/spine-runtimes/blob/3.8/LICENSE)
- [3.8 spine-cpp README](https://github.com/EsotericSoftware/spine-runtimes/blob/3.8/spine-cpp/README.md)
- [3.8 spine-cpp AnimationState 实现](https://github.com/EsotericSoftware/spine-runtimes/blob/3.8/spine-cpp/spine-cpp/src/spine/AnimationState.cpp)
- [官方 Applying Animations 指南](https://esotericsoftware.com/spine-applying-animations)
- [官方 Runtime Skins 指南](https://esotericsoftware.com/spine-runtime-skins)
- [官方 Versioning 指南](https://esotericsoftware.com/spine-versioning)
- [官方 Export 指南](https://esotericsoftware.com/spine-export)

### 准确许可边界

这不是 MIT、Apache 或 BSD。3.8 分支使用专门的 **Spine Runtimes License Agreement**。仓库许可文本规定：

- 在 Spine Editor 许可协议第 2 节允许的条件下，可以把 Runtime 集成进产品；
- 否则，每个产品用户都必须取得自己的 Spine Editor 许可证，并且再分发时必须包含 Runtime 许可和版权声明；
- 官方 README 进一步说明：若要向没有 Spine 许可证的最终用户分发包含 Runtime 的软件，集成时需要有效的 Spine 许可证。

因此，Spine Runtime 源码不能按普通开源宽松许可证理解。发布前必须保留官方许可文本并重新核对当前 Spine Editor/Runtime 许可条件。本研究不是法律意见。

### 可借鉴机制

1. `AnimationState` 负责更新时间、排队、混合和多 Track 叠加。每帧应先 `update(delta)`，再 `apply(skeleton)`。
2. Track 从 0 开始按升序应用。高 Track 动画只会覆盖自己实际设置关键帧的属性，因此可采用：
   - Track 0：完整身体状态，如 `idle`、走跑、坐、睡、拖拽；
   - Track 1：只包含胸腰头部属性的 `breathing`；
   - Track 2：只包含眼睑/眼部附件或颜色属性的 `blink`；
   - 表情 Track 必须和 `blink` 做属性冲突表，不能依赖 Track 号解决不透明冲突。
3. `AnimationStateData` 可以设置默认 Mix 和动画对 Mix；`TrackEntry` 可单独设置 `mixDuration`、`alpha` 和 `timeScale`。
4. `setAnimation` 替换当前动画，`addAnimation` 排队；一次性动画可以在完成后排入 `return_idle` 或 `idle`。
5. `setEmptyAnimation`/`addEmptyAnimation` 用于把高 Track 平滑混出到低 Track 或 Setup Pose，适合结束 `breathing`、`blink`、临时表情等叠加层。
6. Listener 提供 `start`、`interrupt`、`end`、`dispose`、`complete` 和用户 `event`。状态机应使用 `complete` 或明确的 Spine Event 驱动阶段转换，同时防止过期 `TrackEntry` 引用在 `dispose` 后继续使用。
7. Skin 不是简单字符串标签。官方 Skin 指南建议切换后按需要执行 `setSkin`、恢复 Setup Pose Slot，再应用 AnimationState；否则可能保留旧附件。
8. 3.8 分支中 `spine-cpp` 明确支持 3.8.xx 数据，但它只负责加载和操作骨骼数据，**不负责渲染**。项目必须自行实现纹理加载和 Qt/OpenGL 渲染桥接。
9. 3.8 分支列出的官方 Runtime 不包含 Python 或 Qt 专用 Runtime。对 Python + Qt 项目，直接路线是封装 `spine-cpp` 并实现渲染，或者采用另一个经过许可证和版本验证的桥接；不能虚构 `spine-python` 官方包。
10. 官方版本规则要求 Editor 导出的主、次版本与 Runtime 一致。3.8.xx 数据应锁定 3.8 Runtime 分支；3.8.75 和 3.8.99属于同一主/次版本，但仍应在最终导出后用实际 Runtime 回归。

### 对本项目的直接约束

- `breathing` 和 `blink` 必须只设置它们需要改变的属性，否则高 Track 会覆盖 Track 0。
- `idle` 自循环不能在每个循环边界重新 `setAnimation`，否则会重复触发混合。
- `sit_down -> sit_idle`、`sleep_start -> sleep_loop -> sleep_end`、`drag_start -> drag_loop -> drag_end -> landing -> return_idle` 应是明确队列或事件驱动链，而不是靠固定定时器猜测动画结束。
- Skin 或附件切换必须在独立测试中验证 Setup Pose、动画附件时间轴和重开后的状态。

## 2. LorisYounger/VPet

### 一手来源

- [VPet 官方仓库](https://github.com/LorisYounger/VPet)
- [根 LICENSE：Apache License 2.0](https://github.com/LorisYounger/VPet/blob/main/LICENSE)
- [README 的架构与动画资产声明](https://github.com/LorisYounger/VPet/blob/main/README.md)
- [MainLogic.cs：闲置判断、随机移动/待机/睡眠与 WorkingState](https://github.com/LorisYounger/VPet/blob/main/VPet-Simulator.Core/Display/MainLogic.cs)
- [MainDisplay.cs：Start/Loop/End、睡眠、拖拽和回到正常状态](https://github.com/LorisYounger/VPet/blob/main/VPet-Simulator.Core/Display/MainDisplay.cs)
- [GraphInfo.cs](https://github.com/LorisYounger/VPet/blob/main/VPet-Simulator.Core/Graph/GraphInfo.cs)

### 准确许可边界

- 程序代码的根许可证是 **Apache-2.0**。
- 仓库 README 对内置桌宠动画文件另设版权声明：动画版权归虚拟主播模拟器制作组，非商用、商用和再分发有各自条件。
- 因而可借鉴或在满足 Apache-2.0 条件时复用程序代码，但不能因为根许可证是 Apache-2.0 就认定内置动画美术也可自由复制。

### 可借鉴机制

1. `WorkingState` 把 Normal、Work、Sleep、Travel 和扩展状态分开，说明“业务状态”应独立于当前正在播放的动画名。
2. 空闲计时逻辑只在可交互的默认状态触发，并随机选择移动、待机或睡眠；拖拽时不进入随机空闲行为。这适合 ArkClaw 的长期桌面驻留。
3. `AnimatType.A_Start / B_Loop / C_End` 是非常适合本项目的三段式合同：
   - `sit_down -> sit_idle -> return_idle`；
   - `sleep_start -> sleep_loop -> sleep_end`；
   - `drag_start -> drag_loop -> drag_end`。
4. `DisplaySleep` 明确区分进入、循环和退出；`DisplayRaised`/`DisplayRaising` 明确区分抬起、动态拖拽、静态拖拽和释放后的回退。
5. 找不到动画时逐级回退到 Default，最终停止宠物模块而不是无限递归或崩溃。这可转化为 ArkClaw 的 `requested -> semantic fallback -> idle -> placeholder` 策略。

### 不应复制的内容

- 不复制 VPet 的角色动画帧、角色图像或内置宠物包。
- 不把 VPet 的 WPF 组件直接套入 Python/Qt；只借鉴状态机和失败回退结构。

## 3. DalekCraft2/Shimeji-Desktop

### 一手来源

- [Shimeji-Desktop 官方仓库](https://github.com/DalekCraft2/Shimeji-Desktop)
- [仓库 LICENSE.txt](https://github.com/DalekCraft2/Shimeji-Desktop/blob/main/LICENSE.txt)
- [默认 actions.xml](https://github.com/DalekCraft2/Shimeji-Desktop/blob/main/conf/actions.xml)
- [默认 behaviors.xml](https://github.com/DalekCraft2/Shimeji-Desktop/blob/main/conf/behaviors.xml)
- [README 的配置模型和必需动作说明](https://github.com/DalekCraft2/Shimeji-Desktop#advanced-configuration)

### 准确许可边界

该仓库不是单一许可证：

- 原 Shimeji 部分附带 **zlib/libpng license** 文本；
- Shimeji-ee Group 部分附带两项再分发条件的 BSD 风格文本，README 将其称为 **New BSD license**；
- LICENSE 末尾另有 Kilkakon 的署名/链接请求。

若实际复制代码，应保留完整 `LICENSE.txt` 和相应署名，不应只写一个简化 SPDX 标识。角色图片集的来源和授权还需逐个核验；本项目不应复制这些资产。

### 可借鉴机制

1. `actions.xml` 描述“动作如何播放”，`behaviors.xml` 描述“何时选择动作”。这个分层适合把 Spine 动画资源和 Python/Qt 状态机解耦。
2. README 明确要求存在 `ChaseMouse`、`Fall`、`Dragged`、`Thrown` 动作与行为，说明拖拽结束不能直接跳回待机；至少需要释放、下落、着地和回正链路。
3. 默认配置包含 Walk、Run、Sit、Fall、Dragged、Thrown 等语义，可借鉴为事件/状态名称，但不能复制其角色帧。
4. 行为可以是其他动作或行为的 Sequence，并通过条件和频率选择。这适合把 `think/read/type/remind` 当作 Agent 或计时器触发的高优先级行为，而不是随机塞进基础动画循环。

## 4. alvinunreal/openpets

### 一手来源

- [OpenPets 官方仓库](https://github.com/alvinunreal/openpets)
- [根 LICENSE：MIT](https://github.com/alvinunreal/openpets/blob/main/LICENSE)
- [README：提醒、定时调度、Agent 反应和插件 SDK](https://github.com/alvinunreal/openpets#plugin-platform--sdk-v3)
- [官方插件目录](https://github.com/alvinunreal/openpets/tree/main/plugins/official)
- [插件架构文档](https://github.com/alvinunreal/openpets/blob/main/docs/plugins.md)

### 准确许可边界

- 根代码许可证是 **MIT**，要求在软件副本或实质部分中保留版权和许可声明。
- 宠物包、第三方美术或用户安装的插件可能有独立许可。为避免误用，本项目只借鉴代码层的定时、权限和事件机制，不复制宠物资产。

### 可借鉴机制

1. OpenPets 把桌宠本体与提醒、专注计时、喝水提示、Mood Check-in 等能力分成插件，适合 ArkClaw 将“Agent/提醒业务”与 Spine 播放器隔离。
2. SDK 提供 `once`、`every`、`daily`、`cron` 和指定时间调度，提醒应由调度事件触发 `remind`，而不是写死在动画内部。
3. 官方 Reminders 支持提示、铃声和 snooze。ArkClaw 可把 `remind` 设计成一次性不可丢失状态，并允许用户点击确认或推迟后返回先前状态。
4. Agent 集成把 `thinking`、`editing`、`testing`、`success`、`error` 作为语义反应，并通过本地 IPC/MCP 触发。可对应到 `think`、`type`、`happy`、`confused/angry`，但程序只发送稳定的语义名，不直接控制骨骼。
5. 动态内容必须过滤敏感路径、日志和秘密。这个安全边界比动画本身更重要，适合 ArkClaw 的本地 Agent 气泡和提醒文案。

## 5. 对 25 个目标动画的借鉴矩阵

| 目标动画 | 主要借鉴来源 | 建议资源类型 | 程序侧状态/触发 |
| --- | --- | --- | --- |
| `idle` | Spine Track 0；VPet Default | 基础循环 | 无任务、无拖拽时默认状态 |
| `blink` | Spine 高 Track 仅覆盖已设关键帧属性 | 可叠加短动画 | Track 2 随机或定时触发 |
| `walk_left/right` | VPet Move；Shimeji Walk | 循环移动 | 窗口位置速度与脚步相位同步 |
| `run_left/right` | Shimeji Run | 循环移动 | 高速移动，不能只加快 walk 到失真 |
| `sit_down` | VPet A_Start | 一次性过渡 | `idle -> sit_idle` |
| `sit_idle` | VPet B_Loop | 循环 | 坐姿驻留 |
| `sleep_start` | VPet A_Start | 一次性过渡 | 长时间无操作或明确睡眠命令 |
| `sleep_loop` | VPet B_Loop | 循环 | 睡眠业务状态 |
| `sleep_end` | VPet C_End | 一次性过渡 | 用户交互/提醒唤醒后返回 |
| `wave` | OpenPets react；Spine 高层或全身一次性 | 一次性 | 问候/点击 |
| `happy` | OpenPets success | 一次性表演 | Agent 成功或正反馈 |
| `think` | OpenPets thinking | 循环或短循环 | Agent 推理期间 |
| `read` | OpenPets 状态反应；VPet Work | 循环 | 阅读/检索阶段 |
| `type` | OpenPets editing | 循环 | Agent 写入/编辑阶段 |
| `remind` | OpenPets Reminders/schedule | 高优先级一次性 | 定时器到期；允许确认/推迟 |
| `confused` | OpenPets error/react | 一次性表情 | 可恢复错误或需要用户输入 |
| `angry` | OpenPets react | 一次性表情 | 谨慎使用，不代表系统错误本身 |
| `drag_start` | VPet Raised；Shimeji Dragged | 一次性过渡 | 指针按下且越过拖动阈值 |
| `drag_loop` | VPet Raising；Shimeji Dragged | 循环/程序驱动 | 指针移动期间 |
| `drag_end` | VPet C_End；Shimeji Thrown | 一次性 | 指针释放，计算释放速度 |
| `landing` | Shimeji Fall/Thrown | 一次性 | 碰到桌面工作区底边 |
| `return_idle` | VPet DisplayToNomal | 一次性过渡 | 所有表演结束后的统一回退 |

`breathing` 虽不在原始必需名称列表中，但应作为 Track 1 的独立循环资源存在；它不能被复制进上述每个全身动画。头发和服饰摆动可先随基础动画人工制作，只有在确认属性不冲突后再拆成高 Track 次级运动。

## 6. 可直接写入后续制作提示词的规则

1. 每个动画都从经哈希确认的最新验收基线复制到新的隔离目录，完成一个动画就保存、重开、验收并暂停。
2. 在创建动画前先列出来源动画中被观察到的骨骼、Slot、附件、颜色、Draw Order、Deform 和约束时间轴；没有直接观察证据不得猜测数值。
3. 基础状态使用 Track 0；`breathing` 和 `blink` 只给实际变化属性打关键帧，并分别在高 Track 叠加验证。
4. 过渡链统一采用 `start -> loop -> end -> return_idle`。每段必须有清楚的入口姿势、出口姿势和程序回退。
5. 拖拽采用 `drag_start -> drag_loop -> drag_end -> landing -> return_idle`，是否进入 `landing` 由窗口碰撞/释放速度决定，不由 Spine 动画自己移动窗口。
6. `remind`、`think`、`read`、`type` 等由业务语义触发。Spine 文件不保存定时器、Agent 状态或敏感文本。
7. 一次性动画优先由 `complete` 或明确 Event 结束；若动画缺失、事件未到或加载失败，回退 `idle`，并设置超时保护。
8. 方向处理在资产验收前不得默认选择。若使用根节点负 X 缩放，必须单独验证非对称服饰、武器文字、IK、Draw Order、碰撞区和窗口锚点。
9. Skin 切换必须验证 `setSkin -> setup slots -> apply animation` 的结果，不得把 Editor 中当前可见附件误当成 Runtime 默认状态。
10. 只借鉴上述项目的机制和命名思想；不导入它们的角色图像、动画帧、Spine 工程、音频或宠物包。

## 7. 推荐的实现优先级

1. 保持已验收 `idle` 不动，制作并叠加验证 `breathing`、`blink`。
2. 完成基础移动：`walk_left/right`、`run_left/right`。
3. 完成姿态生命周期：坐下与睡眠的 start/loop/end。
4. 完成鼠标生命周期：drag start/loop/end、landing、return_idle。
5. 完成 Agent 工作状态：think、read、type、remind。
6. 完成一次性角色表演和情绪：wave、happy、confused、angry。
7. 最后进行 Spine 3.8 Runtime 导出、Track 叠加、事件回调、Skin、PMA、方向和长期稳定性验证。

该顺序先建立最常驻、最容易暴露属性冲突的层，再做低频表演，能减少后续返工。
