# ArkClaw Desktop Companion UI Design v1

> 阶段：第一阶段 UI 设计提案  
> 角色方向：Schwarz / 黑  
> 本阶段不包含代码，不修改桌宠或业务逻辑

## 0. 设计依据与边界

本稿依据用户提供的黑立绘、完整档案、ArkClaw 产品目标、当前仓库能力，以及 [PRTS 黑资料页](https://prts.wiki/w/%E9%BB%91)完成。立绘是主要视觉依据；PRTS 仅用于交叉核对角色身份与资料背景。

角色美术的嵌入、修改与分发授权仍为 `Unknown`。本稿不构成复制、修改或打包角色素材的授权。

### 功能状态标签

| 标签 | 含义 |
|---|---|
| `Available` | 当前项目已存在对应能力，或已有明确设计契约 |
| `Planned` | 产品需要，但当前实现尚未确认 |
| `Unknown` | 产品或技术契约尚未定义，界面不得伪装成可用 |

### 当前边界

| 能力 | 状态 | 说明 |
|---|---|---|
| Windows 透明桌宠、拖拽、自主行为 | `Available` | 桌宠继续存在于桌面，不在主窗口中替代展示 |
| 暂停/继续、显示/隐藏、置顶、托盘 | `Available` | 可直接进入第一版 Home 快捷控制 |
| 保存桌宠位置 | `Available` | 当前持久化设置包含位置与置顶 |
| 开机启动 | `Available` | 受安装资格与运行环境限制 |
| 黑的 Spine 动作 | `Available`（设计契约） | 已记录 6 个物理动画、7 个逻辑动作；实现前需复核当前分支 |
| 多角色切换 | `Planned` | 第一版信息架构支持，但单角色状态也必须完整 |
| 在线下载角色、添加本地角色 | `Unknown` | 缺少资源包、授权、校验、更新与删除契约 |
| 缩放、透明度 | `Planned` | 当前设置模型尚未包含 |
| FPS、渲染模式、动画质量 | `Planned / Unknown` | 需要先确认真实可用值与后端 |
| 通知、应用更新 | `Unknown` | 当前没有确认的产品契约 |
| Friendly / Passive / Active | `Unknown` | 需要定义动作权重、频率与安全规则 |

---

## A. 产品定位

### A.1 ArkClaw 应该是什么

ArkClaw 是一个 **Desktop Companion Control Center（桌面伴侣控制中心）**，由三层产品价值组成：

1. **Companion（陪伴）**：呈现当前角色、状态与轻量反馈。
2. **Controller（控制）**：快速控制显示、动作、行为、位置与系统运行方式。
3. **Workshop（工作台）**：随着项目发展，管理角色和动画资源，但第一版不做复杂编辑器。

它不应像设置弹窗、后台管理系统或角色百科。主窗口应像紧凑的游戏 Companion App：角色是视觉中心，控制清楚，技术细节按需展开。

### A.2 用户

- **日常陪伴用户**：短暂打开窗口，查看黑的状态、触发动作、暂停移动或调整显示。
- **角色收藏用户**：未来管理多个合法角色包和版本。
- **高级调节用户**：调整交互、性能与渲染参数，希望知道设置对桌面的实际影响。

### A.3 核心流程

```text
从托盘或桌宠右键菜单打开
  → 看到当前角色与实时状态
  → 快捷操作，或进入一个专项页面
  → 在桌面宠物上确认结果
  → 关闭控制中心，应用继续在托盘运行
```

未来角色切换：

```text
My Pets
  → 选择已安装角色
  → 检查预览与资源健康状态
  → Use this pet
  → 等待加载成功
  → Home 展示新的当前角色
```

### A.4 产品原则

- **角色优先**：预览比标题、说明和卡片更醒目。
- **先控制，后详情**：常用动作最多一到两次点击完成。
- **桌面连续性**：文案明确说明操作影响“桌面上的宠物”。
- **真实状态**：加载、暂停、资源损坏、渲染降级和不可用功能必须区分。
- **克制的人格表达**：通过精确、安静、略带温度的语言表达黑，而非堆砌武器或战斗 HUD。
- **短时使用**：窗口适合快速打开和关闭，不要求长期占据屏幕。

### A.5 从角色档案到 UI 气质

黑同时具有冷静精准与克制关怀两面。UI 应表达这种反差，但不消费她的创伤、感染状况或杀戮经历。

| 角色信号 | UI 转译 | 避免 |
|---|---|---|
| 精准、沉默、经验丰富 | 紧凑排版、明确层级、短文案 | 满屏军事 HUD |
| 黑色装备、冷灰建筑、银白发色 | 石墨色表面、冷灰边框、高对比文字 | 全界面纯黑 |
| 琥珀色眼睛 | 当前选择、在线、焦点状态 | 所有按钮都变黄 |
| 少量橙红落叶 | 警告、危险、强操作 | 橙红渐变装饰 |
| 对亲近者克制的关怀 | 温和状态文案、柔和预览背景 | 与素材无关的通用萌系贴纸 |

医疗档案不应成为 Home 的状态或数据卡。若未来支持档案阅读，应是用户主动打开的独立阅读页。

---

## B. Visual Direction

### B.1 方向定义

**Quiet Tactical Companion（静默战术伴侣）**

关键词：

```text
克制 / 精准 / 冷静 / 哑光 / 原生桌面 / 暖色内核 / 角色主导
```

拒绝玻璃拟态、Glow、紫蓝渐变、大 Hero、装饰性 3D、假数据图表和过度科幻边框。

### B.2 色彩系统

颜色关系来自立绘中的枪械黑、建筑冷灰、银白、低饱和军绿、琥珀眼睛和少量橙色落叶。

#### 基础色

| Token | 色值 | 用途 |
|---|---:|---|
| `bg.canvas` | `#151819` | 窗口主背景 |
| `bg.sidebar` | `#111415` | 侧边栏 |
| `surface.default` | `#1D2123` | 面板和设置分组 |
| `surface.raised` | `#252A2D` | Hover、菜单、弹窗 |
| `surface.preview` | `#D8D9D5` | 深色角色的中性浅色预览舞台 |
| `border.subtle` | `#303639` | 默认边框与分隔线 |
| `border.strong` | `#495055` | 选中和强调边框 |
| `text.primary` | `#F1F0EB` | 主文字 |
| `text.secondary` | `#AAB0B1` | 辅助文字 |
| `text.muted` | `#747C80` | 元数据、禁用文字 |

#### 品牌与语义色

| Token | 色值 | 用途 |
|---|---:|---|
| `brand.primary` | `#C9774D` | 主按钮、当前导航标记 |
| `brand.hover` | `#D4865C` | Hover |
| `brand.pressed` | `#AC613F` | Pressed |
| `accent.amber` | `#D2A25C` | 当前角色、在线、Focus Ring |
| `accent.sage` | `#708078` | 自主、安静、中性行为状态 |
| `status.success` | `#72916E` | Ready、Installed、Healthy |
| `status.warning` | `#D19A4A` | 需要注意、可降级使用 |
| `status.danger` | `#C65D4B` | 失败、删除、危险确认 |
| `status.info` | `#718A9C` | 普通信息 |

典型页面应约为 80% 石墨与冷中性色、15% 灰白内容、最多 5% 暖色强调。状态不能只靠颜色表达，必须同时使用图标或文字。

### B.3 字体

| 层级 | 字体 | 字号 / 行高 | 字重 |
|---|---|---:|---:|
| 页面标题 | Segoe UI Variable / Microsoft YaHei UI | 22 / 30 px | 600 |
| 角色名 | Segoe UI Variable | 24 / 30 px | 650 |
| Section Header | 同上 | 16 / 24 px | 600 |
| Body / Control | 同上 | 14 / 20 px | 400–500 |
| Caption | 同上 | 12 / 18 px | 400 |
| Duration / 技术值 | Cascadia Mono / Consolas | 12 / 18 px | 500 |

不使用影响可读性的游戏字体。中文与拉丁字符保持统一基线。

### B.4 圆角、边框、阴影

- 大面板 10 px；卡片 8 px；控件 6 px。
- Badge 可使用胶囊圆角，其余组件不滥用胶囊形。
- 默认 1 px 边框；当前角色使用 2 px 琥珀边框或 3 px 左标记。
- 阴影只用于菜单、Tooltip、Modal 和抽屉，不做环境 Glow。
- 设置页优先使用分隔线，避免卡片套卡片。

### B.5 间距和密度

采用 4 px 基础栅格：4 / 8 / 12 / 16 / 24 / 32 px。标准控件高度 36 px，主按钮 40 px，鼠标点击区不小于 32 × 32 px。

### B.6 动效

| 场景 | 时间 | 方式 |
|---|---:|---|
| Hover / Focus | 100–140 ms | 颜色与边框变化 |
| 页面切换 | 160–200 ms | 4 px 位移 + 淡入淡出 |
| 预览切换 | 200–240 ms | Cross-fade，不弹跳缩放 |
| Drawer / Modal | 180–220 ms | 短距离 ease-out |

尊重 Windows Reduced Motion。UI 动效与桌宠动画暂停状态相互独立。

---

## C. Application Layout

### C.1 窗口规格

- 默认：**1180 × 760 px**。
- 最小：**880 × 600 px**。
- 舒适宽度：1024–1440 px。
- 标题栏关闭按钮是隐藏到托盘还是退出：`Unknown`，需确认。

### C.2 常规结构

```text
┌──────────────────────────────────────────────────────────────────────────┐
│ ArkClaw                              Schwarz · Relaxing      —  □  ×     │ 40
├──────────────┬────────────────────────────────┬──────────────────────────┤
│ Sidebar      │ Main Content                   │ Preview / Detail         │
│ 208 px       │ Flexible, min 440 px           │ 320 px                   │
│              │                                │                          │
│ Home         │                                │ Contextual inspector     │
│ My Pets      │                                │ Persistent on Home       │
│ Animations   │                                │                          │
│ Interaction  │                                │                          │
│ Appearance   │                                │                          │
│              │                                │                          │
│ Settings     │                                │                          │
└──────────────┴────────────────────────────────┴──────────────────────────┘
```

### C.3 响应式规则

| 宽度 | 行为 |
|---:|---|
| ≥1120 px | 完整侧边栏 + 主内容 + 常驻 Inspector |
| 960–1119 px | 侧边栏折叠为 72 px Icon Rail；Inspector 保留 300 px |
| 880–959 px | Icon Rail；Inspector 变为右侧抽屉 |
| <880 px | 主窗口不支持，保持最小宽度以避免功能裁切 |

### C.4 标题栏

优先保证 Windows 原生缩放、Snap Layout、系统菜单、拖动和 Resize。若自绘标题栏不能完整保持这些能力，第一版使用原生标题栏。

内容仅包括：ArkClaw 名称/合法 Logo、当前宠物紧凑状态、标准窗口按钮。不放搜索、宣传语或全局导航。

### C.5 侧边栏

- Home 和日常控制在上方，Settings 固定在底部。
- 当前项使用 3 px 暖色标记、略亮表面、图标与文字共同表达。
- 折叠模式必须保留 Tooltip 和清晰键盘焦点。
- Badge 仅提示需要用户处理的资源或运行问题，不显示无意义数量。

### C.6 Preview / Detail Panel

- Home：当前宠物预览与实时状态。
- My Pets：选中角色详情与切换操作。
- Animation Library：选中动作预览与元数据。
- 设置页面：显示效果预览或上下文说明。

预览分两期：

1. 第一版安全方案：有授权的静态缩略图或 ArkClaw 自制中性占位图。
2. 计划方案：独立 Spine 预览实例，不在确认前影响桌面宠物。

现有渲染器能否安全创建第二实例为 `Unknown`。不得复用实时宠物实例导致动作、朝向、位置或自主状态改变。

---

## D. Page Specification

## D.1 Home

### 页面目的

用户打开后立即回答：**当前是谁、正在做什么、现在可以做什么。**

### 布局

- 左侧为大面积中性预览舞台，占可视内容约 55% 以上。
- 右侧为角色身份、实时状态和主要操作。
- 底部为最多 5 条最近事件；没有事件历史时不伪造时间线。

预览是视觉中心，但不是营销 Hero，不放宣传标题。

### 组件与操作

- `Schwarz / 黑`。
- 状态：Relaxing、Moving、Sleeping、Paused、Dragging、Loading、Needs attention、Unavailable。
- 主操作：`Interact`、`Change action`、`Pause / Resume`。
- 次操作：`Show / Hide on desktop`、`Resume autonomous`、`Appearance`。
- 当前循环动作若被用户显式保持，显示 `Held`。

### 行为

- 点击动作先显示 Pending，只有 Runtime 接受后才显示成功。
- Held 动作直到替换、强制中断或 `Resume autonomous` 才结束。
- 渲染失败显示清晰恢复状态，不显示空黑框。
- 暂停桌宠不禁用设置页或角色管理。

### 特殊状态

- 无当前角色：`Choose a pet`，前往 My Pets。
- 资源校验失败：显示安全错误、`View details` 和可用回退状态。
- Runtime 启动中：元数据使用轻量 Skeleton，预览保持中性背景。

## D.2 My Pets

### 页面目的

用游戏角色选择的方式管理角色，不做文件列表。

### 布局

- Header：标题、已安装数量；角色超过 8 个后再显示搜索/筛选。
- Main：2–3 列角色卡片。
- Inspector：选中角色预览、资源状态、主要操作。

只有黑一个角色时，使用一张重点卡片和一个有意设计的 `Add character` 占位，不把单张卡片拉满页面。

### Character Card

- 合法预览图或实时缩略图。
- 名称与本地化名称。
- Current、Installed、Invalid assets、Unavailable 等状态。
- 必要时显示 `Spine 3.8`。
- 主按钮位于 Inspector，卡片本身不堆叠按钮。

### 操作

- `Use this pet`：`Planned`。
- `Open details`：展开 Inspector。
- `Add local character`：`Unknown`，资源包契约完成前禁用并解释原因。
- `Browse characters`：`Unknown`，没有合法目录和网络流程前不显示为可用。
- `Remove`：未来危险操作；若 ArkClaw 不拥有外部只读素材，不得暗示会删除原文件。

## D.3 Animation Library

### 页面目的

以用户能理解的语义动作管理动画，不把 Spine Track 和资源文件名当作主界面模型。

### 布局

- Main：按类别分组的紧凑动作行或中型 Tile。
- Toolbar：仅在动作数量较多时出现搜索与分类筛选。
- Inspector：动作预览、语义名、播放信息和触发来源。

### 黑的 v1 动作目录

| 逻辑动作 | 物理动画 | 分类 | 循环 | 触发 |
|---|---|---|---|---|
| Relax | Relax | Idle | Loop | Autonomous / Manual hold |
| Move Left | Move | Movement | Loop | Autonomous / Manual hold |
| Move Right | Move | Movement | Loop | Autonomous / Manual hold |
| Sit | Sit | Idle | 读取资源元数据 | Autonomous / Manual |
| Sleep | Sleep | Idle | 读取资源元数据 | Autonomous / Manual |
| Special | Special | Expression | 读取资源元数据 | Autonomous / Manual |
| Interact | Interact | Interaction | 读取资源元数据 | User / Manual |

准确时长和可中断性必须来自已校验 Runtime 元数据，目前为 `Unknown`，不得在 UI 中硬编码。

### 动作项

- 72 × 72 px Thumbnail 或中性 Pose 占位。
- 名称、分类、时长、Trigger、Current/Held 状态。
- `Preview`：仅在独立预览安全时启用。
- `Play on desktop`：向实时桌宠请求动作。
- `Hold action`：仅对 Runtime 支持的循环动作显示。
- `Resume autonomous`：退出显式保持。

原始动画名、Track、Hash 和 Atlas 数据只出现在可选技术详情中。

## D.4 Interaction

### 页面目的

解释鼠标行为与自主行为，并避免手势冲突。

### 布局

- Mouse Interaction：3 个设置行和简洁指针示意。
- Autonomous Behavior：模式选择与结果说明。
- Safety & Interruption：说明什么会中断 Held 动作。
- Inspector：显示手势如何影响桌面宠物。

### 鼠标映射

| 输入 | 行为 | 状态 |
|---|---|---|
| 左键按住并移动 | 拖动桌宠 | `Available` |
| 左键单击 | Interact | `Unknown` |
| 右键 | 打开桌宠菜单 | `Available` |
| 双击 | 未定义 | `Unknown` |

单击与拖拽需要移动阈值和时间契约。在定义前，左键单击行应显示为不可用，避免误触。

### 行为模式

Friendly / Passive / Active 暂为 `Unknown`。建议未来改用结果导向的名称：

- Quiet：更少自主切换，可选择禁止非必要移动。
- Balanced：使用当前验证过的调度策略。
- Lively：在安全范围内提高动作频率。

以上仅为产品建议，不代表当前功能。

## D.5 Appearance

### 页面目的

清楚控制桌宠在 Windows 桌面上的占用与可见性。

### 布局与控件

不堆叠 Slider。使用分组 Setting Row、数值框、Preset 和桌面位置示意。

#### Size & Visibility

- Scale：Preset + 百分比数值，`Planned`。
- Transparency：Slider + 数值，`Planned`。
- Always on top：Toggle，`Available`。
- Show on desktop：Toggle，`Available`。

#### Position

- Monitor Selector，`Planned`。
- 3 × 3 Anchor，`Planned`。
- `Return to visible area`，`Planned`，复用现有桌面边界规则。
- X / Y 放在 Advanced 中，不作为普通用户的主控件。

#### Rendering

- Animation quality，`Planned`。
- Rendering mode，`Unknown`；只显示真实支持的后端。

高风险实时调整应提供 10 秒 `Undo`，或确认后再应用。任何缩放与位置调整都必须保留可恢复区域，不能让宠物完全移出工作区。

## D.6 Settings

### General

- Launch with Windows：`Available`，显示资格、忙碌与错误状态。
- Close button behavior：`Unknown`。
- Language：`Unknown`。
- Update：`Unknown`。

### Performance

- FPS Limit：`Planned`，具体选项 `Unknown`。
- Rendering Mode：`Unknown`。
- Reduced UI Motion：`Planned`，默认跟随 OS。

### System

- Tray 当前 `Available`；是否允许关闭托盘为 `Unknown`。
- Notifications：`Unknown`。
- Always on top 只链接到 Appearance，不复制第二份状态。

### Intelligence

当前应用已有 Provider Profile 与凭据设置。应保留在 `Settings > Intelligence`，不与角色和动画页混合。

- Active Provider 与 Lifecycle：`Available`。
- 添加/编辑 Profile：`Available`。
- Credential 只显示已配置/未配置，永不回填 API Key。
- Runtime 错误默认显示安全信息，技术详情按需展开。

### About & Diagnostics

- App Version / Build Channel。
- Asset 与 Renderer Health。
- Copy Safe Diagnostics：排除 API Key、原始资源路径和敏感内容。
- Licenses 与 Third-party Notices。

---

## E. Component Library

### E.1 Sidebar / Navigation Item

状态：Default、Hover、Focused、Active、Disabled、Attention。Active 同时使用标记、表面和字重；Icon-only 模式必须提供 Tooltip。

### E.2 Character Card

8 px 圆角，4:3 预览区，名称、资源状态、当前标记。`Selected in UI` 与 `Active on desktop` 是两个不同状态。

### E.3 Preview Panel

包含 Stage、Playback Controls、Loading、Unavailable 和 Renderer Failure。背景使用来自立绘建筑环境的中性浅灰，不使用渐变。

### E.4 Button

- Primary：暖色填充，一个决策区域只保留一个。
- Secondary：抬升石墨表面。
- Quiet：低风险文字/图标操作。
- Danger：默认描边，只在确认弹窗中使用填充。
- Icon Button：至少 32 × 32 px，并有 Tooltip。

支持 Default、Hover、Pressed、Focus、Disabled、Busy、Success Confirmation。

### E.5 Toggle

36 × 20 px Track，标签放在开关外。重要设置同时显示状态词，如 `Enabled` / `Unavailable`，不能只靠颜色。

### E.6 Slider / Numeric Field

Slider 只用于透明度等连续感知值，必须搭配数值框与 Reset。Scale 优先 Preset + 数值，而非 Slider。

### E.7 Dropdown

36 px 高。渲染选项提供一行结果说明；不列出不支持的后端。

### E.8 Status Badge

Neutral、Ready、Active、Paused、Warning、Error、Current。使用 12 px 短标签；复杂状态同时使用图标。

### E.9 Setting Row

```text
Label                                      [Control]
一行说明设置会怎样影响桌面宠物
```

设置行之间使用分隔线。校验错误与 Restart Requirement 紧邻相关设置。

### E.10 Animation Action Item

Thumbnail、Name、Category、Duration、Trigger、Current/Held。Hover 只显示最可能操作，其他命令进入 Inspector 或 Context Menu。

### E.11 Modal

仅用于危险操作、可能失败的角色切换、资源校验处理和未保存更改。标准宽 440–520 px；危险弹窗默认焦点位于安全操作。

### E.12 Tooltip

500 ms 后出现，只放短说明，不承载必读信息或交互内容。

### E.13 Toast / Inline Message / Banner

- Toast：短暂确认，如“Desktop pet paused”。
- Inline Message：设置或资源附近的错误。
- Banner：仅用于影响整个页面的 Runtime / Renderer 问题。

### E.14 Empty / Unavailable / Error

- Empty：功能存在，但没有内容。
- Unavailable：当前 Build 没有该能力。
- Error：能力存在，但执行失败。

三种状态不能使用完全相同的通用文案。

---

## F. Implementation Suggestion

### F.1 当前技术基础

项目使用 Python 3.12/3.13、PySide6 6.11.1 和分层架构。Domain / Application 不依赖 Qt。新 UI 必须保留此边界，不把桌宠行为逻辑放进 Widget。

### F.2 推荐实现方式

第一版继续使用 **PySide6 Qt Widgets**，不引入第二套前端栈：

- 现有窗口、托盘、异步生命周期、Provider 设置和测试都基于 Qt Widgets。
- 本 UI 是高密度控制型界面，不需要依赖场景图的大型动态壳。
- Widgets 更容易保持 Windows 键盘、焦点、辅助功能、菜单和对话框语义。
- 迁移 QML 会成为大规模重构，不符合当前约束。

建议组合：

- `QMainWindow` 作为 Owner Window。
- `QStackedWidget` 承载页面。
- 固定/折叠 Sidebar Widget。
- 可在窄窗口变成 Drawer 的 Contextual Inspector。
- QSS + 小型 Design Token 层管理颜色、间距、圆角和字体。
- ArkClaw 自有或授权兼容的 SVG Icon Set。
- 所有资源、Provider、Renderer 操作继续走异步 Signal / Controller，不阻塞 UI Thread。

### F.3 架构交互

```text
Qt Page / View
  → UI Controller / Presenter
  → Application Service / Runtime Bridge
  → Domain State Transition
  → Immutable UI Snapshot
  → View renders snapshot
```

建议增加只读 Snapshot：Current Pet、Visibility/Lifecycle、Current Action/Hold/Autonomy、Installed Pet Summary、Animation Catalog、Appearance Capability、Startup/Tray/Renderer/Provider Health。

UI 只提交 Command 与渲染 Snapshot，不直接决定自主动作、不改 Spine 文件、不扫描任意目录，也不从像素结果猜测 Renderer Health。

### F.4 持久化

- 扩展当前 Pet Settings 必须有 Schema Version Migration。
- Provider Credential 继续放在 Windows Credential Manager。
- UI 偏好与角色行为尽可能分开保存：Last Page、Sidebar State、Main Window Geometry、Reduced Motion Override。
- 不保存明文 Key、瞬时预览状态或未经校验的任意资源路径。

### F.5 Preview 路线

1. 有授权的静态 Portrait / Thumbnail。
2. 通过资源所有权与性能测试后，加入只读 Renderer Preview。
3. 定义时间与隔离契约后，再做可拖动时间轴预览。

Preview 绝不能意外修改实时 Track 0、桌宠位置、Facing 或 Autonomous State。

### F.6 Windows 与可访问性验证

- 测试 100%、125%、150%、200% DPI。
- 保持原生 Resize、Minimize、Maximize、Snap、System Menu、Taskbar 行为。
- 验证纯键盘操作和 Screen Reader Name。
- 普通文字对比度至少 4.5:1；大文字与必要边界至少 3:1。
- 支持 Reduced Motion；在可行范围内兼容 High Contrast。
- 在 880 × 600 验证没有裁切或不可到达的操作。

### F.7 确认后的实现顺序

1. 冻结产品名、Logo/素材授权与色彩 Token。
2. 实现 Application Shell、Navigation、Token System、Responsive Inspector。
3. 用当前 Runtime 与 Tray 能力实现 Home。
4. 将现有 Startup 与 Provider 控制整合进 Settings。
5. 基于已校验 Runtime Metadata 实现 Animation Library。
6. 在对应 Application Setting 定义后实现 Appearance。
7. 在角色包和授权契约完成后实现 My Pets 切换与安装。
8. 在行为语义和 Click/Drag 仲裁完成后实现 Interaction Preset。

---

## G. Unknown Register

1. 发布产品名是 ArkClaw 还是当前仓库使用的 SJTUClaw？
2. 哪个 Logo 与 App Icon 可合法分发？
3. 本次立绘是仅供参考，还是可嵌入产品？
4. 黑是默认永久角色、可选外部包，还是开发集成？
5. Spine Renderer 能否安全创建第二个隔离预览实例？
6. 当前实现分支上 6 个物理动画 / 7 个逻辑动作的权威状态是什么？
7. 角色包的 Manifest、校验、授权元数据、更新与移除语义是什么？
8. 是否存在合法的远程角色目录？由谁托管，如何校验更新？
9. Scale、Transparency、FPS、Quality、Rendering Mode 的真实范围是什么？
10. Friendly、Passive、Active 对调度权重与安全规则的准确含义是什么？
11. Left Click 如何与 Drag 区分？
12. 主窗口关闭是隐藏到 Tray 还是退出？
13. Update Mechanism 与 Notification Category 是什么？
14. v1 支持哪些语言？

---

## H. 第一阶段确认清单

- [ ] 确认“桌面伴侣控制中心”而非 Web Dashboard 的产品定位。
- [ ] 确认“石墨黑 + 冷灰 + 低饱和军绿 + 少量琥珀/橙”的 Schwarz 方向。
- [ ] 确认默认与最小窗口尺寸。
- [ ] 确认页面信息架构和右侧 Inspector。
- [ ] 接受 `Available / Planned / Unknown` 功能标识。
- [ ] 明确角色立绘、Logo 与应用图标授权。
- [ ] 确认 Home 主操作优先级。
- [ ] 为影响实现的 Unknown 指定决策。
- [ ] 本文确认前不进入代码实现阶段。
