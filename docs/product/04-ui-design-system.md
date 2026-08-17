# ArkClaw UI Design System

> 阶段：Phase 4 — UI Design System  
> 文档类型：Product Design / Visual Language Contract  
> 上位约束：`docs/product/01-ui-vision.md`、`docs/product/02-interaction-model.md`、`docs/product/03-ui-state-machine.md`  
> 下游用途：Screen Specification、high-fidelity prototype、frontend engineering TDD  
> 本文不包含：代码、Qt/QML/QSS、最终 Screen Layout、工程架构或 Agent backend

## 1. Purpose

本文定义 ArkClaw 的视觉语言与可 token 化的 Design System，使 Character、Conversation、Action、Workspace 与 Agent presentation projection 在视觉上属于同一个产品。

本文只决定跨 Surface 可复用的视觉规则：Shape、Spacing、Surface、Color、Typography、Iconography、Motion、状态表达、组件族、桌面适配和可访问性。它不改变 `01 / 02 / 03` 已确认的产品定位、交互层级、状态、事件、守卫或输入优先级，也不把视觉选择升级为新的产品功能。

### 1.1 Normative language

- **Must**：后续视觉与 Screen Specification 不得违反。
- **Should**：默认采用；偏离时必须说明具体场景和原因。
- **May**：允许使用，但须满足本文 guard。
- **`TBD` / `Unknown`**：尚未获得产品确认，不得由原型或实现静默决定。

### 1.2 Design-system boundary

- UI 只表现 `03` 已定义的 UI state 与 Agent presentation projection。
- Thinking、Acting、Waiting、Success、Error、Cancelled 的视觉变化必须由有效的 UI projection 驱动；视觉系统不定义 Agent backend lifecycle。
- Motion 不得生成虚假进度、虚假完成或虚假可取消性。
- 本文不解决 Primary Conversation Invocation 的 single-click / double-click 冲突；任何 hover、shape 或 motion 也不得暗示未确认的鼠标语义。

---

## 2. Design Direction

ArkClaw 的视觉方向是：

> **Character-centered Desktop Agent + quiet dynamic surfaces + restrained expressive motion + Schwarz-compatible identity**

用户应感到 UI 是 Schwarz 在当前任务中的临时延伸，而不是一个独立 App 被放在桌宠旁边。视觉系统用稳定的中性材质、有限强调色、统一 shape hierarchy 和连续容器 motion，让 Surface 在需要时清晰出现，在完成职责后自然降低存在感。

### 2.1 Desired qualities

| Quality | Visual consequence |
|---|---|
| Quiet | 默认没有 Surface；低饱和、少装饰、少同时运动元素 |
| Lightweight | 容器尺寸与内容相称；少 chrome、少边界、少工具按钮 |
| Responsive | 输入与状态改变有立即但克制的视觉反馈 |
| Contextual | 重要性由当前任务决定，不展示全局功能库存 |
| Fluid | Capsule、Expanded、Workspace 通过连续形变表达同一上下文 |
| Character-attached | 轻量 Surface 有清晰 anchor，状态由 Schwarz 与 Surface 共同表达 |
| Desktop-native | 适应多背景、DPI、屏幕边缘和键盘焦点，不套用移动端页面结构 |
| Intelligent, not noisy | 显示用户目标、状态和恢复路径，不显示低层运行噪声 |

### 2.2 Visual tension to preserve

ArkClaw 应同时保持两种气质：

- Schwarz 提供角色复杂度、身份和有限温度。
- UI 提供秩序、清晰度和克制。

UI 不通过复制角色服装纹理、游戏符号或装饰性线框来“匹配” Schwarz；它通过比例、节奏、材质、强调色和 motion temperament 与角色形成统一。

---

## 3. Visual Principles

1. **Character Owns the Scene**：Schwarz 是视觉中心；Surface 是临时关系，不是主角旁的主窗口。
2. **Surfaces Earn Weight**：重要性越高，材质越稳定、层级越明确；不是越大越花。
3. **One Shape Language**：圆角来自有限 scale 和容器层级，不按组件随意选择。
4. **Spacing Communicates Structure**：先用空白和分组，再使用边框、底色或分隔线。
5. **Color Has a Job**：颜色用于层级、交互与语义；不用于制造 AI 氛围。
6. **Motion Explains State**：每个动效必须解释来源、关系、活动或结果。
7. **Stable Before Translucent**：可读性与桌面背景稳定性优先于 blur 或玻璃效果。
8. **Expressive, Not Decorative**：表达来自 shape、scale、containment 和 motion hierarchy，不来自纹理堆叠。
9. **State Is Redundant**：状态至少由文字、图标、motion、shape/containment 中两种以上方式表达，绝不只靠颜色。
10. **Calm Is the Default**：无任务、后台继续、完成后的视觉强度必须逐步降低。
11. **Focus Is Visible**：键盘焦点、当前决定和当前任务必须清楚且不被遮挡。
12. **Every Choice Is Tokenizable**：重复视觉值必须归入有限 token，不在 Screen 中产生无来源特例。

### 3.1 Explicit visual exclusions

不得使用以下方向建立 ArkClaw 身份：Admin Dashboard、IDE shell、traditional desktop app chrome、gaming HUD、cyberpunk、sci-fi control panel、card wall、永久 sidebar/toolbar/status indicator、大面积霓虹、复杂网格、扫描线、故障效果、过度 gradient、过度 glassmorphism 或 Arknights-style decorative HUD。

---

## 4. Character / UI Relationship

## 4.1 Spatial relationship

轻量 Surface 必须从 Schwarz 的可用邻近区域出现，并保持可追溯的空间来源：

- 首选在不遮挡角色主体、现有 hit region 和用户当前桌面内容的一侧锚定。
- Schwarz 与轻量 Surface 的默认视觉间距使用 `spacing.3`（12）；需要更清晰分离时使用 `spacing.4`（16）。
- Surface 可因屏幕边缘、任务栏或可用空间翻转/平移，但 anchor 关系不能消失。
- Expanded Conversation 可增加阅读面积并降低物理贴近程度，但展开路径必须从 Capsule 连续可见。
- Workspace 可成为稳定大 Surface；它仍应通过进入 motion、任务 identity 和 Schwarz 状态保持来源关系，不要求永久用连线或尾巴连接。
- 任何 Surface 不得覆盖 Schwarz 的主要身体轮廓、既有可交互像素或 Drag 目标区域。

具体方位、碰撞策略和几何尺寸属于 Screen Specification。

## 4.2 Visual weight

Schwarz 的视觉复杂度高于所有轻量 UI。Surface 因此必须：

- 使用大面积稳定中性面，而非角色纹理复刻；
- 每个视图最多设置一个主要强调区域；
- 把边框、阴影、颜色、图标和 motion 看作同一视觉预算，避免同时加重；
- 不在角色周围形成按钮环、状态环或持续光晕；
- 不用大型 Logo、角色名或品牌字样争夺入口焦点。

## 4.3 State partnership

- Schwarz 表达持续状态和低干扰可感知性。
- Surface 表达状态的文字含义、用户选择、进度与恢复路径。
- Character only 下的 active task 必须由 Schwarz 和最小待查看信号表达，但该信号不能变成永久 status bar。
- 角色动画不可替代 Confirmation、Error explanation、Cancel availability 或 Focus indicator。

---

## 5. Shape System

Shape 使用六级 scale。数值为逻辑视觉单位，后续按平台 DPI 正确缩放；组件不得在 scale 外自行增加 13、18、22 等随机圆角。

| Token | Radius | Use |
|---|---:|---|
| `shape.xs` | 4 | 小型进度轨道、内嵌预览、紧凑状态区；不作为普通按钮默认值 |
| `shape.s` | 8 | 小型控件、icon button、compact field、文件/应用缩略容器 |
| `shape.m` | 12 | 标准按钮、输入区内部容器、chip group、结果子容器 |
| `shape.l` | 16 | Floating card、Action/Result container、Palette 分组 |
| `shape.xl` | 24 | Focused Surface、Confirmation、Expanded Conversation、Workspace 外壳 |
| `shape.full` | Full | Conversation Capsule、pill/chip、圆形 icon control；只用于短而明确的对象 |

### 5.1 Shape rules

- Outer container radius 必须大于或等于 nested container radius。
- Capsule 使用 `shape.full` 表达低摩擦入口；Expanded 后逐步过渡到 `shape.xl`，避免大窗口仍像过度膨胀的药丸。
- Workspace 使用 `shape.xl`，内部结构优先靠 spacing 分组，只在确有独立语义时使用 `shape.m/l` 子容器。
- Confirmation 使用 `shape.xl`，通过稳定 containment 而非尖锐框体表达重要性。
- Destructive action 不改变 shape 家族，只改变语义层级、图标和色彩；避免“危险按钮必须尖角”的额外语法。
- `shape.full` 不得泛化到所有按钮与卡片，否则会产生玩具化和 Material 模仿。

### 5.2 Shape character

ArkClaw 的 shape 是“柔和但收束”：转角连续、容器清晰、不过度鼓胀。Expressiveness 主要来自不同层级之间有意义的形态变化，而不是每个元素都使用夸张、不对称或超大圆角。

---

## 6. Spacing System

基础 spacing scale：

| Token | Value | Primary use |
|---|---:|---|
| `spacing.0` | 0 | 明确贴合或重叠，不作为默认间距 |
| `spacing.1` | 4 | icon/text 微调、紧凑内部关系 |
| `spacing.2` | 8 | 同一 control 内部、紧密关联项 |
| `spacing.3` | 12 | 标准 control gap、Capsule 紧凑 padding、Schwarz anchor gap |
| `spacing.4` | 16 | 标准 component padding、Floating Surface 基础 padding |
| `spacing.5` | 24 | section gap、Focused Surface padding |
| `spacing.6` | 32 | Expanded/Workspace 主要区域分隔 |
| `spacing.7` | 48 | 大段内容、Workspace 大层级留白 |
| `spacing.8` | 64 | 仅用于大型 Workspace 的稀疏顶层节奏；非默认 |

### 6.1 Application rules

| Context | Spacing contract |
|---|---|
| Compact control internal padding | `spacing.2–3`，文字与图标关系优先 |
| Standard button / field | inline `spacing.3–4`；block `spacing.2–3` |
| Capsule | `spacing.3` compact；展开能力不靠堆入更多常驻按钮 |
| Floating Surface | `spacing.4` outer padding；关联 control gap `spacing.2–3` |
| Confirmation / important result | `spacing.5` outer padding；决定组与说明分离 |
| Expanded Conversation | `spacing.5` outer；section gap `spacing.4–5` |
| Workspace | `spacing.5–6` outer；顶层区域 `spacing.6–7` |
| Schwarz-to-surface | 默认 `spacing.3`；为避免遮挡可用 `spacing.4`，具体 placement 后定 |

Spacing 不是简单随 Surface 放大。Expanded 与 Workspace 增加的是内容层级间距；按钮、输入与文字本身仍保持适合桌面操作的紧凑节奏。

---

## 7. Surface System

Surface hierarchy 与 `03` 的 P/O Region 对齐，但只定义视觉权重，不新增状态。

| Level | Surface | Typical states/components | Visual weight |
|---|---|---|---|
| `surface.none` | Character-only | `CHARACTER_ONLY` | 仅 Schwarz；无 UI 容器 |
| `surface.ambient` | Ambient | Temporary notification、passive result、hidden-task signal | 最低；短暂、非抢焦 |
| `surface.floating` | Floating | Capsule、Action Palette、temporary action | 轻量、锚定、清晰可 dismiss |
| `surface.focused` | Elevated / Focused | Confirmation、critical error、重要 Result、active decision | 稳定、高对比、单一前景 |
| `surface.workspace` | Workspace | `WORKSPACE_OPEN` | 最持久；minimal chrome、结构清楚 |

### 7.1 Surface hierarchy rules

1. 同一时刻只能有一个主 Presentation 和一个前景 Overlay；视觉上不得伪造额外层级。
2. Action/Progress 在主 Surface 可见时嵌入，不额外浮出第二张卡。
3. Palette 不与 Capsule 并排；视觉转换应表现为同一 anchor 的上下文切换。
4. Confirmation 通过 focused material、containment 与 focus ownership 取得优先级，不靠扩大到全屏。
5. Workspace 允许更稳定的背景和更少透明度；它不是由大量 floating cards 拼成的 card wall。
6. Ambient Surface 在更高层级存在时合并、降级或不显示。

### 7.2 Surface anatomy

Surface 可包含以下语义区，但不得为了统一而强制全部出现：

- identity/context：当前对象或任务的最小标识；
- content：用户目标、回答、结果或决定；
- state：必要的状态文字与 progress；
- controls：当前真实可用的最少动作；
- recovery：Error、Partial 或 Cancelled 后的有效下一步。

永久 header、toolbar、sidebar、footer/status bar 不属于标准 anatomy。

## 8. Surface Material

ArkClaw 使用 **stable translucent restraint（稳定、有限的半透明）**，不采用全面玻璃拟态。

### 8.1 Material policy

| Property | Decision |
|---|---|
| Opacity | Workspace、Confirmation、Error 与长文本 Surface 以近不透明材质为默认；Ambient/Floating 可在满足可读性时使用有限透明 |
| Blur | 仅作为 Ambient/Floating 的背景分离辅助；不能承担文字对比或层级的唯一责任 |
| Border | 优先使用低对比 outline 说明边界；同一 Surface 不同时使用强 border 与强 shadow |
| Shadow | 用于表达与桌面的空间分离，不制造悬浮奇观；层级越高越稳定，不必越浓重 |
| Background separation | 由 surface tone、outline 与必要 shadow 共同保证，必须适应亮/暗/复杂壁纸 |
| Desktop adaptation | 当采样结果不可靠、背景过亮/过暗或高频时，自动选择更实的 fallback material |

### 8.2 Opacity roles

| Token | Contract |
|---|---|
| `opacity.ambient` | 允许最高透明感，但文字必须位于独立稳定底层上 |
| `opacity.floating` | 轻微透出环境，仅在对比稳定时使用 |
| `opacity.focused` | 接近不透明，确保决定和错误不会受壁纸干扰 |
| `opacity.workspace` | 稳定、近不透明；长时间阅读优先 |
| `opacity.disabled` | 降低强调但仍保持可辨识；不单靠透明度表示不可用 |

精确 opacity 与 blur radius 为 `TBD`，必须基于实际 Schwarz 素材和多类桌面背景测试后决定。

### 8.3 Blur guard

只有同时满足以下条件才可使用 blur：

1. Surface 为 Ambient 或短时 Floating；
2. 关闭 blur 后仍有完整 solid fallback；
3. 文字、图标、焦点和边界在亮/暗/高频背景上均稳定；
4. 不影响响应性与 motion 清晰度；
5. 不与角色高复杂度区域重叠产生噪声。

Focused Surface、Workspace、长文本、代码/路径、Confirmation 与 Error 默认不依赖 blur。

### 8.4 Elevation scale

| Token | Meaning |
|---|---|
| `elevation.0` | 无 Surface 或内嵌区域 |
| `elevation.1` | Ambient / embedded result |
| `elevation.2` | Capsule / Palette / floating action |
| `elevation.3` | Focused decision / important result |
| `elevation.4` | Critical foreground interruption；全系统同一时刻最多一个 |

Workspace 依靠稳定面积和结构获得层级，通常使用 `elevation.2–3`，而不是最高阴影。精确 shadow 值为 `TBD`。

---

## 9. Color System

Color system 以 **charcoal neutrals + quiet cool support + one restrained character-compatible accent** 为方向。Exact accent hue 必须在 Schwarz 正式角色素材、亮/暗背景和可访问性验证后决定，因此本阶段定义 role 与关系，不冻结品牌色值。

### 9.1 Core roles

| Token family | Role | Direction |
|---|---|---|
| `color.primary` / `on-primary` | 主操作、明确选中和品牌核心强调 | 深墨/石墨方向；高对比，不是 Google blue |
| `color.secondary` / `on-secondary` | 次级控制、上下文标识、辅助强调 | 低饱和冷灰/矿物色，弱于 Primary |
| `color.accent` / `on-accent` | 稀缺的 Character-compatible emphasis、当前关键点 | 单一、克制、有限饱和；exact hue `TBD` |
| `color.surface` / `on-surface` | 标准内容背景与主文字 | 稳定中性，支持亮/暗环境 |
| `color.surface-variant` | 内嵌区域、分组、只读内容 | 与 Surface 形成轻微而可靠的 tone 差 |
| `color.surface-elevated` | Floating/Focused/Workspace 的背景分离 | 比 base surface 更稳定，而非必然更亮 |
| `color.text-primary` | 标题、正文、关键值 | 最高可读层级 |
| `color.text-secondary` | 帮助、时间、次要标签 | 降低权重但仍可读，不使用灰上灰 |
| `color.outline` | Surface/Control 边界 | 低噪声；focus outline 使用独立增强 role |
| `color.focus` | 键盘焦点与当前控制 | 在所有 surface/background 上可见，不与 Accent 绑定 |
| `color.success` | 完成/部分完成中的已完成部分 | 克制自然绿方向 |
| `color.warning` | 风险、等待超时、需要注意 | 低饱和琥珀方向 |
| `color.error` | 失败、破坏性操作、无效确认 | 清晰红方向；不使用霓虹或持续泛红 |
| `color.info` | 中性信息、外部等待或提示 | 冷静蓝灰方向；不成为默认 AI 品牌色 |

每个色彩 role 都必须有 `on-*` 前景配对和高对比 fallback。不得在 Screen 中直接选择“看起来合适”的 raw color。

### 9.2 Neutral hierarchy

中性色承担大部分界面：

- `surface.canvas`：Workspace 背景或可读大面积基底；
- `surface.base`：标准 Surface；
- `surface.variant`：内嵌分组；
- `surface.elevated`：Floating/Focused；
- `text.primary / secondary / disabled`；
- `outline.subtle / standard / strong`。

层级优先由 tone 与 spacing 建立，再由 outline/shadow 补充。不得把所有容器都变成不同颜色卡片。

### 9.3 Accent budget

- 单个轻量 Surface 原则上只有一个 accent focal point。
- Accent 不用于大面积 Surface fill、所有 icon 或常驻角色轮廓。
- Primary action 可以使用 Primary 或 Accent，但不能同时出现两种竞争 CTA。
- Agent state semantic color 不应取代品牌 Accent；Error/Success 只在对应状态出现。
- 禁止 rainbow palette、Google 四色组合、Gemini 蓝紫渐变、purple-AI cliché、霓虹 cyan/magenta 对撞。

### 9.4 State color is supplementary

Thinking、Acting、Waiting、Success、Error 与 Cancelled 均必须同时具有文字/图标/motion/containment 线索。色彩缺失、色觉差异或高对比模式下，语义仍须完整。

### 9.5 Light / dark strategy

ArkClaw 必须支持亮、暗和高复杂桌面背景，但“是否提供用户可选 Light/Dark mode、是否跟随系统、是否根据桌面自适应”仍为 `TBD`。无论策略如何：

- 同一语义 role 在不同模式中保持相同层级关系；
- 不简单反相阴影、outline 和 semantic colors；
- Surface 必须有不依赖壁纸采样的稳定 fallback；
- Schwarz 本体与 UI 的分离不得依赖给角色添加永久光圈。

---

## 10. Typography

Typography 采用紧凑、现代、跨语言友好的 sans-serif system。Exact typeface 为 `TBD`；候选必须覆盖简体中文、Latin、数字、标点与常用符号，并在中英文混排时具有相近的视觉高度和字重。

### 10.1 Type scale

| Token | Size / line height | Weight | Use |
|---|---|---:|---|
| `type.display` | 28 / 36 | 600 | Workspace 的少量关键结果或空态；不用于 Capsule |
| `type.title-lg` | 20 / 28 | 600 | Workspace/Focused Surface 顶层标题 |
| `type.title` | 16 / 24 | 600 | Result、Confirmation、section title |
| `type.body` | 14 / 21 | 400 | 标准对话、说明、结果正文 |
| `type.body-sm` | 13 / 19 | 400 | 次要说明、紧凑列表；不承载长段关键内容 |
| `type.label` | 13 / 18 | 500 | Button、field label、chip、task label |
| `type.caption` | 12 / 16 | 400/500 | 时间、辅助元数据；不得承担关键状态或恢复说明 |
| `type.code` | 13 / 20 | 400/500 | path、filename、command/code fragment |

数值是 Design System 基线，不决定最终组件几何。Display 应极少使用；ArkClaw 不需要营销页式大标题。

### 10.2 Typographic rules

- 中文正文不使用过紧行高或过细字重。
- 中英文混排保持自然大小写；不把状态标签全部转为 uppercase。
- Button label 使用清晰动词，不为视觉对称强行截断。
- Title 与 Body 通常只使用 400、500、600 三档；避免依赖大量 weight 建层级。
- 路径、文件名和短代码使用 `type.code`，但界面其他文字不使用 monospace。
- 长路径允许可理解的截断与查看完整值；不得用缩小到难以阅读来解决空间问题。
- Placeholder 不是 label；输入目的必须在使用中仍可理解。
- 禁止 sci-fi font、装饰性 Arknights-like 字体、极细字体和 tiny status label。

### 10.3 Typeface selection criteria

最终字体必须验证：Windows 桌面渲染、简体中文全字形覆盖、Latin 与数字辨识、不同 DPI 清晰度、路径/代码可读性、授权与分发。Noto Sans SC 可作为覆盖性验证参考，但本阶段不把它确认为品牌字体。

---

## 11. Iconography

Icon 风格为简洁、平衡、低噪声的几何图形：转角与 Shape System 协调，stroke/fill 逻辑在同一层级内一致。

### 11.1 Visual contract

- 默认 icon 视觉尺寸使用 `icon.m`（20）；compact control 使用 `icon.s`（16）；重要状态可使用 `icon.l`（24）。
- 同一 control family 不混用明显不同 stroke weight、optical size 或 filled/outlined 风格。
- Filled icon 只用于当前选中、强语义状态或关键结果；普通操作优先 balanced outline。
- Icon button 必须有可访问名称；不依赖 tooltip 才能理解关键行动。
- Success、Error、Warning、Waiting 等状态 icon 必须与文字共同出现，除非语义已在相邻内容中明确。
- 不使用 emoji 作为产品 icon，不在本阶段指定 icon library。

### 11.2 Required semantic set

后续资产必须覆盖：Send、Voice、Attach/Context、Close、Expand、Collapse、Settings、Retry、Cancel/Stop、Success、Partial、Warning、Error、Waiting、Progress、Back/Return 与 Details。

每个 icon 在 compact、standard、high-contrast 和 disabled 状态下都应保持辨识；最终图形和 stroke 数值为 `TBD`。

---

## 12. Motion System

Motion 是 ArkClaw 的状态解释系统。它回答三个问题：对象从哪里来、它与什么保持关系、当前状态发生了什么变化。

### 12.1 Motion tokens

| Token family | Meaning | Typical use |
|---|---|---|
| `motion.duration.micro` | 最短反馈 | focus、press、icon state |
| `motion.duration.short` | 轻量 enter/exit | Palette、Ambient、small result |
| `motion.duration.medium` | 容器变化 | Capsule enter、Expanded transition |
| `motion.duration.long` | 大范围连续变形 | Expanded ↔ Workspace；只在关系需要解释时使用 |
| `motion.easing.standard` | 克制响应 | 普通 control/state |
| `motion.easing.enter` | 快速建立、柔和停下 | Surface enter |
| `motion.easing.exit` | 更直接离场 | dismiss/collapse |
| `motion.spring.soft` | 低振幅、快速稳定 | Character-attached container morph |
| `motion.spring.none` | 无弹性 | Error、critical decision、Reduced Motion |

精确 duration、curve 与 spring 参数为 `TBD`。关系必须满足：micro < short < medium < long；exit 不得比 enter 更拖沓；同一次 transition 只有一个主导容器 motion。

### 12.2 Enter

- Capsule / Palette 从 Schwarz anchor 处进行短距离 translate + scale/shape settle + fade。
- Enter 必须立即让用户知道输入已被接收；不得先播放独立角色动画再迟到显示 Surface。
- Confirmation 从当前任务内容区域提升为 focused containment，不从屏幕边缘或系统中心无来源弹入。
- Workspace 不从 Character only 无提示出现。

### 12.3 Exit

- dismiss 优先使用较短 fade/scale/translate 回 anchor，表明 UI 被收拢而非任务消失。
- 有 active projection 时，Exit 应把视觉注意交回 Schwarz 的状态表达。
- Error/Confirmation 的退出不得使用庆祝或成功式 motion。

### 12.4 Expand and collapse

```text
Capsule shape.full
→ container resize / content reflow
→ Expanded shape.xl
→ Workspace stable surface
```

- 外壳是主导运动对象；内部内容按层级揭示，不逐卡片 stagger 表演。
- 阅读位置、task identity 和关键 controls 保持空间连续。
- Collapse 反向降低信息密度，关键状态/草稿/待处理决定不被 motion 隐藏。
- 不使用 `disappear → unrelated window appears`。

### 12.5 Morph

当 state ownership 和内容连续时，优先 morph 同一容器；只有语义对象确实改变时才 cross-fade 或替换。Morph 不允许把 Palette 与 Capsule 视觉上误认为同一功能，只表达它们共享 Schwarz anchor。

### 12.6 Agent activity motion

- Thinking：低振幅、非方向性的内部相位变化或呼吸式 containment；不是单一无限 spinner。
- Acting：方向更明确、节奏更稳定，并与 task label / semantic progress 对齐。
- Waiting：运动减速、保持或停止，并显示等待对象；不得看似仍在推进。
- Success：一次清晰 settle/completion，随后降低强度。
- Error：一次明确但非惊吓式注意变化，随后稳定停留供阅读。
- Cancelled：动作收束并回到中性，不借用 Success 或 Error 的庆祝/警报语法。

### 12.7 Motion hierarchy and budget

- 每个可见上下文最多 1–2 个主运动元素。
- 高优先变化可以更明显，但 Confirmation/Error 首先依靠稳定结构与文字，而非大幅 motion。
- Hover、ambient 与 passive progress 必须低于输入、决策和主容器转移。
- 持续 motion 必须能够停止或降级；不允许为了“Agent 在工作”长期循环多个元素。

### 12.8 Reduced Motion

Reduced Motion 下保留状态变化，但替换路径：

- translate/scale/spring → 短 fade 或即时容器替换；
- 循环活动 → 静态 icon + 明确文字 + 必要的非运动进度；
- success/error emphasis → tone、outline、icon 和 text；
- 最终可读状态必须立即成立，不能依赖动画结束才出现。

## 13. Agent State Visual Language

本节映射 `03` 的 Agent presentation projection，不定义 backend state。每个状态至少使用两种非颜色线索，并由 Schwarz 与当前 Surface 表达同一事实。

| Projection | Schwarz | Surface / container | Motion | Text / icon | Must not resemble |
|---|---|---|---|---|---|
| `Idle` | 安静姿态、低频 ambient | 默认无 Surface；打开的空 Capsule保持中性 | 无持续任务 motion | 无永久 status | 正在等待用户处理 |
| `Listening` | 轻微响应，表示输入正在被接收 | input focus、清晰 caret/focus containment | 对输入有即时小反馈，不持续脉冲 | 输入状态与 Send availability | Thinking 或录音中（除非 voice active） |
| `Thinking` | 克制的思考动作 | 当前请求 + subtle activity region | 低振幅、非方向性、可取消 | Thinking label + distinct icon/shape cue | 已执行、下载进度或卡死 spinner |
| `Acting` | 更明确的执行姿态 | Action/Progress container、task label、真实 Cancel/Inspect | 稳定、方向性、与阶段变化一致 | 正在做什么 + progress type | 内部 tool log 或 Thinking |
| `Waiting Confirmation` | Waiting，注意力指向决定 | Focused Confirmation | 主活动停止；decision container 稳定进入 | scope/effect + Confirm/Cancel + decision icon | Loading、自动继续或系统警告框 |
| `Waiting Input` | Waiting，低强度提示 | 关联问题/选择获得焦点 | 不循环制造忙碌感 | 明确说明缺少什么 + question/input icon | Confirmation 或 Error |
| `Waiting External` | Ambient Waiting | 低权重 waiting summary | 减速/静止；只在事实更新时响应 | 等待对象/条件 + waiting icon | 持续假进度 |
| `Success` | 短暂完成反馈后安静 | Result 使用 Success role；复杂结果保留 | 单次 settle，不庆典化 | 完成内容 + success icon | 游戏胜利、彩带、全屏绿色 |
| `Partial Success` | 与 Success 相近但不宣称全部完成 | 已完成/未完成分区；Warning/Info 辅助 | 单次 settle，未完成部分保持可见 | 两部分明确文字 + partial icon | 纯 Success 或纯 Error |
| `Error` | 可识别但不惊吓 | Error summary + recovery；critical 才 focused | 单次注意变化后静止 | 目标、影响、Retry/alternative + error icon | OS exception dialog、持续 shake/alarm |
| `Cancelled` | 收束到中性 | Cancellation Result，低于 Error/Success | 停止活动并柔和退出 | “已取消” + neutral stop icon | 失败或成功 |

### 13.1 Cross-state rules

- Thinking → Acting 必须改变 motion direction、task wording 与 Action containment，而不是只换颜色。
- Acting → Waiting 必须停止“推进”感，明确说明等待用户还是外部条件。
- Waiting → Acting 只能在 UI 收到新的 backend projection fact 后改变视觉。
- Success/Error/Cancelled 只能选择一种结果语言；不得混合互相冲突的色彩和 motion。
- Character only 下使用 Schwarz + 单一 ambient signal；不得长期悬挂文字状态标签。
- 声音和 haptic 是否存在均为 `TBD`，不属于本阶段默认状态通道。

---

## 14. Component Families

本节定义组件族及视觉角色，不决定页面布局或具体功能范围。

## 14.1 Inputs

| Family | Contract |
|---|---|
| Text input | 中性 stable field；focus 清晰；支持多行与中英文；placeholder 不替代 label/context |
| Voice entry | 只在 voice 功能确认后出现；recording/listening 状态必须可区分并可停止；范围 `TBD` |
| Context attachment | 以 icon + text/chip 表达已选择对象、来源和移除操作；权限与功能 `TBD` |

Input 不使用持续发光边框作为 AI 标志。Validation、Waiting Input 与 backend Error 必须在语义和视觉上区分。

## 14.2 Buttons

| Type | Use | Visual rule |
|---|---|---|
| Primary | 当前 Surface 唯一主要推进动作 | 实色或最高对比 containment；原则上每个决定区一个 |
| Secondary | 替代、返回、查看等并列但非主要动作 | 低于 Primary，可用 variant surface/outline |
| Tertiary | 轻量上下文动作 | 无强 containment；仍需明确 focus/hover/pressed |
| Destructive | 会产生删除、退出或高影响取消 | 使用 destructive role + 明确动词；不因红色省略后果 |
| Icon button | Close、Expand、Voice 等高熟悉度动作 | `shape.s/full`；必须有 accessible name 和可见状态 |

Disabled 不得是唯一解释机制：若用户合理期待某动作可用，应说明不可用原因。Cancel 只有在 `03` 的 cancellability guard 通过时显示。

## 14.3 Pills / Chips

用于 context、task label、status 和轻量 action。规则：

- 使用 `shape.full`，短标签、有限数量；
- status chip 不成为永久状态栏；
- 可关闭 context chip 提供独立 remove affordance；
- 超长路径不强塞入 chip，转为 file/path container；
- 不用彩虹 chip 区分大量类型；优先 icon、label 和 neutral variants。

## 14.4 Cards / Containers

Cards 只用于具有独立语义、边界或操作的对象：Result、File、App、Confirmation、Progress。连续对话段落和普通文本不必每条加卡。

- Embedded：`shape.m/l`、`elevation.0–1`；
- Floating：`shape.l`、`elevation.2`；
- Focused：`shape.xl`、`elevation.3–4`；
- 同层 cards 不得以多种随机色和阴影制造 wall。

## 14.5 Progress components

| Type | Use | Visual rule |
|---|---|---|
| Indeterminate | 无可靠比例但等待值得显示 | 非百分比；稳定活动 + task label；不可无限无说明 |
| Determinate | 有真实、稳定、可解释比例 | 轨道 + 值/阶段说明；不伪造精度 |
| Multi-step | 用户需理解高层阶段 | 只显示语义阶段；当前/完成/待处理可辨，不显示低层 tool noise |

简单快速操作省略 Progress，直接呈现 Result。

## 14.6 Result components

- **Success**：完成内容、必要的 next action；短结果可以收拢。
- **Partial**：已完成与未完成部分必须在结构上分开；不只用 warning color。
- **Error**：目标、实际影响、真实 Retry/alternative/Details；technical details 默认收起。
- **Cancelled**：说明请求已停止；若有已发生副作用，恢复语言为 `TBD`。

---

## 15. Conversation Capsule Contract

Conversation Capsule 是最低视觉成本的 Agent 入口，必须满足：

- 使用 `shape.full` 外形和 `surface.floating` 材质；
- 锚定 Schwarz，默认间距 `spacing.3`，边缘适配时允许调整；
- 主要视觉内容是当前输入，而非品牌、建议卡或工具栏；
- text input、真实可用的 context/voice entry 与 Submit 必须形成一个清晰交互组；
- 非核心入口默认不常驻；更多能力通过 context 或 expansion 按需出现；
- focus、draft、Thinking/Acting/Waiting 状态不改变容器 identity；
- 可通过 shape.full → shape.xl 的连续 morph 扩展；
- 不复制浏览器搜索栏、Gemini prompt bar 或系统搜索框的精确比例和图标布局。

Capsule 不得成为 giant floating rectangle，不显示 Sidebar/history/model/MCP/plugins/logs/token/temperature，也不使用大型 placeholder 或品牌 Logo 占据内容空间。

其 exact width、height、placement quadrant、按钮可见策略与 voice/attachment 范围属于 Screen Specification / `TBD`。

---

## 16. Action Palette Contract

Action Palette 使用 `surface.floating`、`shape.l`、`elevation.2`，视觉上像 Schwarz 的上下文动作延伸，而不是传统 Windows menu 换皮。

### 16.1 Visual rules

- 锚定本次右键上下文，使用清楚但克制的 enter/exit；
- 顶层分组数量有限，以 spacing 和 label 建层级，不依赖多层 separator；
- Current Task、Character、ArkClaw 等分组通过标题、icon 和间距区分；
- 当前不可用或不存在的分组不显示空壳；
- hover/focus/pressed 必须可区分，keyboard focus 不被圆角或 shadow 遮蔽；
- destructive Quit 与普通 Settings/Hide 具有清晰间隔和语义，但不制造红色警报区；
- 选择后 Palette 收拢；不留下选中高亮或第二个 Surface。

### 16.2 Explicit exclusions

不得表现为 legacy context menu、mobile full-screen sheet、command palette clone、app launcher grid、icon matrix 或深层 cascade menu。最终标签、排序、角色动作可用性和 Quit 规则仍为 `TBD`。

---

## 17. Workspace Contract

Workspace 是最稳定、信息容量最大的 Surface，但视觉上仍从同一 Conversation container 生长。

### 17.1 Visual role

- 使用 `surface.workspace`、`shape.xl` 和稳定近不透明材质；
- minimal chrome：只显示当前任务所需的结构和 controls；
- Conversation 保持中心语义，但不独占面积；task、artifact、file、result、confirmation 按需进入信息层级；
- 顶层区域通过 spacing、type 和 surface tone 组织，而非永久 Sidebar + Toolbar；
- Action/Progress/Result 在任务上下文中嵌入，不沿边缘堆成状态卡；
- Schwarz 保持可见身份与状态关系；Workspace 不把角色降级为装饰贴图。

### 17.2 Structural constraints

Workspace 可以有 contextual panels，但它们必须：

- 由当前任务对象或决定触发；
- 可收拢或随任务结束消失；
- 不承担全局应用导航；
- 不复制 IDE tree、inspector dock、console 或 dashboard metric cards；
- 维持一个清晰主要焦点，避免同时出现多个“主面板”。

最终 layout、panel ownership、resizing 和 exact geometry 不在本阶段决定。

---

## 18. Desktop Adaptation

ArkClaw 的 Surface 必须在桌面环境中保持锚定、可读和不阻挡。

### 18.1 Placement principles

- 先选择不遮挡 Schwarz 主体且有足够可用空间的 anchor quadrant；空间不足时翻转、平移或改变展开方向。
- 角色靠近屏幕边缘时，Surface 保持在可用工作区内，不因坚持某一侧而裁切。
- Taskbar、系统保留区域、多个显示器边界和不同 DPI 必须被视为布局约束。
- Surface 移动/翻转后仍通过 enter origin、motion path 和 task continuity 表达属于 Schwarz。
- Workspace 需保持可用阅读面积；不要求始终贴在角色旁，也不能突然跳到无关系的屏幕中心。

### 18.2 Desktop background adaptation

设计验证至少覆盖：纯亮、纯暗、高饱和、照片、高频图案和与 Schwarz 相近色调的桌面背景。失败时优先提高 Surface material 稳定性，而不是为每种壁纸生成复杂主题。

是否实时采样桌面背景、采样范围、跨显示器策略和 light/dark mode ownership 为 `TBD`；本文不规定 geometry 或渲染实现。

### 18.3 Density and scale

- Spacing 与 type 使用逻辑 scale，在高 DPI 下保持视觉关系。
- 不以缩小文字、hit area 或状态 label 解决小屏空间；优先收拢次要内容和改变 Surface 层级。
- 大屏不自动展开更多永久 panels；额外空间只在任务确实需要时使用。

## 19. Accessibility

Accessibility 是 visual system 的设计门禁，不是完成 Screen 后的修补项。

### 19.1 Contrast and readability

- Normal text 以至少 4.5:1 的可读对比作为基线；大型文字、控件边界与状态 indicator 采用适用的可访问性标准验证。
- 透明 Surface 上的文字必须相对稳定底层验证，不能只测理想壁纸。
- `text.secondary` 不得形成 gray-on-gray；辅助信息仍必须可读。
- Focus、hover、pressed、selected、disabled 必须彼此可辨，且不只用透明度或颜色。
- `type.caption` 不承担关键状态、错误影响、Confirmation scope 或恢复路径。

### 19.2 Non-color state

所有 Agent state 至少结合以下两类线索：

- explicit text；
- semantic icon；
- motion or static activity form；
- container shape/outline/tone；
- control availability and placement。

高对比或无颜色条件下，Thinking、Acting、Waiting、Success、Error、Cancelled 仍须互相可区分。

### 19.3 Keyboard focus

- 每个可操作组件有持续可见的 focus indicator；focus 不被 shadow、clip、透明边缘或上层 Surface 遮挡。
- Focus role 与品牌 Accent 分离，保证在所有 Surface role 上可见。
- Overlay 打开后 focus 进入最高层；关闭后恢复到仍有效的前一目标，与 `03` 一致。
- Icon-only action 具有可访问名称；tooltip 不是唯一名称来源。
- Hover/Drag 不能成为必要功能的唯一入口；具体非鼠标路径仍为 `TBD`。

### 19.4 Reduced Motion and cognitive load

- 尊重系统 Reduced Motion；保留状态结果，移除不必要路径和弹性。
- 不同时动画化多个 cards、角色、progress 和背景材质。
- Waiting 必须用文字说明，不要求用户从节奏推断。
- Error 不使用持续 shake、flash 或警报循环。
- 自动消失内容必须满足阅读与恢复要求；exact timing 仍为 `TBD`。

### 19.5 Input and target clarity

- 控件 hit area、间距和焦点必须适合桌面鼠标与键盘；精确最小尺寸由 Screen Specification 验证。
- 透明区域不产生不可见点击阻挡；Surface 不覆盖 Schwarz 现有 gesture hit region。
- Destructive、Confirm、Cancel 不得只靠位置习惯区分，必须有明确 label 与语义。

---

## 20. Design Token Taxonomy

所有重复视觉决定使用三层 token 模型：

```text
Reference value
→ Semantic role
→ Component alias
```

例如 Shape 的 reference value `16` 被命名为 `shape.l`，再由 `component.result.radius` 引用；Screen 不直接写入无语义值。

### 20.1 Token families

| Family | Examples | Owns |
|---|---|---|
| `color.*` | `color.surface.base`, `color.text.primary`, `color.state.error` | 色彩 role 与 on-color relationship |
| `shape.*` | `shape.xs` … `shape.full` | radius hierarchy |
| `spacing.*` | `spacing.0` … `spacing.8` | gap、padding、section rhythm |
| `type.*` | `type.body.size`, `type.body.line`, `type.title.weight` | font role、size、line-height、weight |
| `icon.*` | `icon.s/m/l`, `icon.stroke.*` | optical size 与风格 role |
| `motion.*` | `motion.duration.*`, `motion.easing.*`, `motion.spring.*` | transition hierarchy |
| `surface.*` | `surface.ambient/floating/focused/workspace` | material、tone、content relationship |
| `elevation.*` | `elevation.0–4` | foreground hierarchy |
| `opacity.*` | `opacity.ambient/floating/focused/workspace/disabled` | transparency role |
| `outline.*` | `outline.subtle/standard/strong/focus` | 边界与 focus relationship |
| `state.*` | `state.thinking.motion`, `state.error.icon` | projection 到多通道视觉 alias，不存 backend logic |

### 20.2 Token rules

1. Semantic token 优先于 raw value；组件不得直接引用品牌色或任意像素值。
2. Light/Dark/High-contrast mode 只替换 role value，不改变 token 语义。
3. Component alias 只能组合已定义 semantic token，不制造新 scale。
4. State token 只映射 UI projection；不得包含 backend planning/tool lifecycle。
5. 临时原型值必须标注 temporary，不能自动进入 master token。
6. Exact color、opacity、blur、shadow、font 与 motion values 在 TBD 解决前保留 semantic placeholder。

---

## 21. Reference Adaptation

Google Gemini 与 Material 3 / Material 3 Expressive 是原则参考，不是 component kit 或品牌模板。

| Reference principle | Borrow | Adapt for ArkClaw | Do not copy |
|---|---|---|---|
| Expressive shape hierarchy | 用 shape、size 和 containment 表达层级 | 六级 restrained Shape Scale；Capsule → Workspace 逐渐稳定 | Material 默认圆角数值、所有元素超大圆角 |
| Responsive container motion | 连续 resize/morph 解释对象关系 | 以 Schwarz anchor 和同一任务 continuity 为起点 | Gemini prompt bar 的精确 morph、页面路径和曲线 |
| Layered surfaces | Surface weight 对应注意力和决定优先级 | Ambient/Floating/Focused/Workspace 与 `03` 的 P/O 对齐 | Material elevation 默认 shadow、card wall |
| Contextual UI | 当前意图优先，工具按需出现 | Character/Conversation/Action/Workspace 动态披露 | Gemini 页面布局、建议卡、永久 prompt arrangement |
| Meaningful motion | Motion 说明状态变化与空间来源 | Thinking/Acting/Waiting 使用不同 motion grammar | 高弹跳、庆典式动画、品牌星芒/glow |
| Accessible expressiveness | 色彩之外保留文字、形状和 motion/static cues | Schwarz + Surface 双通道、Reduced Motion 完整语义 | 只用品牌色或动画区分状态 |
| Minimal chrome | 内容和当前决定成为中心 | 无永久 sidebar/toolbar/status bar | Google app shell、mobile FAB/bottom navigation |
| Brand adaptation | 原则可迁移，品牌必须独立 | Charcoal neutral、restrained accent、Schwarz-compatible temperament | Google 四色、Gemini 蓝紫渐变、logo/icon identity |

本地设计参考检索曾给出通用网页 Hero、蓝橙 CTA 和 Lora/Raleway 组合；这些与 Desktop Agent、Schwarz identity 和 Calm Desktop 不匹配，因此明确不采用。仅采纳其中跨产品适用的可见焦点、稳定文字对比、Reduced Motion 和有限动效原则。

---

## 22. Decision Table

| Area | Decision | Reason | Avoid |
|---|---|---|---|
| Direction | Character-centered、quiet、contextual、fluid | Schwarz 是视觉中心，UI 按需出现 | 独立 App window、AI spectacle |
| Shape | 4/8/12/16/24/Full 六级 scale | 有层级、可 morph、不过度玩具化 | 随机圆角、所有组件 pill |
| Spacing | 0/4/8/12/16/24/32/48/64 有限 scale | 适配 compact desktop 与 Workspace | 13/19/27 等孤立值 |
| Surface | None → Ambient → Floating → Focused → Workspace | 对齐状态机优先级和 Progressive Disclosure | 多 Surface 堆叠、card wall |
| Material | 稳定中性为主，半透明和 blur 受 guard 限制 | 适应任意壁纸并保持可读 | 全面 glassmorphism、强 glow |
| Elevation | 五级 role；Workspace 不自动最高 | 层级来自任务重要性，不来自窗口大小 | 每张卡独立重阴影 |
| Color | Charcoal neutral + quiet support + one restrained accent | 与复杂角色协调并减少噪声 | Google 四色、AI 紫、rainbow/neon |
| Typography | 28/20/16/14/13/12 紧凑 sans hierarchy；font TBD | 中英混排与桌面阅读优先 | sci-fi、装饰字体、tiny labels |
| Icon | 16/20/24，balanced stroke/fill | 清晰、一致、低噪声 | emoji、混搭 icon family |
| Motion | 一个主导容器 motion；状态 motion 有语义 | 解释来源、连续性和 projection | disappear/new window、持续弹跳 |
| Blur | Ambient/Floating 条件使用；focused/long-read 不依赖 | 背景分离是辅助，不是身份 | 模糊承担文字对比 |
| State | text/icon/motion/containment 至少两类线索 | 非颜色唯一语义，防止状态混淆 | spinner-only、color-only |
| Capsule | anchored `shape.full` floating container | 最低成本、轻量、可扩展 | 浏览器/Gemini 搜索栏复制 |
| Palette | compact anchored grouped Surface | 上下文动作，不取代 Conversation | legacy menu、command palette clone |
| Workspace | stable `shape.xl`, minimal chrome, contextual structure | 复杂任务需要理解与控制 | Sidebar + Chat + Toolbar + Settings |
| Accessibility | 可见 focus、稳定对比、Reduced Motion、非 hover-only | 可用性是系统约束 | 灰上灰、隐藏 focus、动画唯一语义 |

---

## 23. Unknown / TBD

以下问题尚未确认，不得由 Screen、prototype 或实现静默冻结：

1. Exact brand typeface、fallback order 与字体授权/分发。
2. Exact Primary、Secondary、Accent hue 和完整 tonal palette；需以正式 Schwarz 素材验证。
3. Light/Dark mode 是跟随系统、用户选择还是桌面自适应。
4. Surface 是否采样桌面背景，以及何时强制 solid fallback。
5. Exact opacity、blur radius、shadow、outline width 与 material rendering。
6. Exact motion duration、easing curve、spring stiffness/damping 和 feedback timing。
7. Schwarz 七种状态和 Cancelled 的最终角色动画、静态替代、声音与资产范围。
8. Hover feedback 的视觉形式与时机；不得解决或暗示未决鼠标绑定。
9. Capsule exact geometry、按钮可见性、placement quadrant、edge adaptation 与 attachment/voice 第一版范围。
10. Expanded/Workspace exact layout、panel ownership、resizing 和 artifact arrangement。
11. Action Palette 最终标签、排序、Character action availability 与 Quit visual treatment。
12. 状态/待查看 signal 是否使用 badge-like form，以及聚合规则。
13. Confirmation、Success、Error、Notification 的自动收拢和阅读时长。
14. System notification 的视觉与使用边界。
15. Icon library、最终 glyph、stroke/fill 数值与品牌定制范围。
16. 高对比模式具体 palette 与系统 theme integration。
17. 鼠标/键盘/辅助技术 control target 的最终最小几何。
18. Schwarz 素材使用、修改和分发授权对视觉系统的约束。
19. 已有 single-click Interact 与 double-click Capsule 的阻断性 gesture mapping；本阶段不解决。

---

## 24. Explicit Non-goals

本文不设计或产出：

- Qt implementation、QSS、QWidget、QML 或 CSS；
- animation code、window geometry implementation、native event handling；
- class hierarchy、UI controller、state ownership implementation；
- Agent backend、backend state machine、planning、tool routing、MCP 或 tool implementation；
- API、persistence、permission-system architecture；
- screen-by-screen final layout 或 `05-ui-screen-spec.md`；
- high-fidelity mockup、final icon、角色动画或其他 asset production；
- frontend engineering TDD 或 production code；
- 未确认鼠标手势的视觉原型替代决策。

---

## 25. Consistency Review

| Review item | Result | Evidence / correction |
|---|---|---|
| 符合 `01-ui-vision.md` | Pass with carried gesture TBD | Character First、Calm Desktop、Google 借鉴边界和 gesture gate 保留 |
| 符合 `02-interaction-model.md` | Pass | Surface hierarchy、Progressive Disclosure、Palette/Workspace/Notification contract 一致 |
| 符合 `03-ui-state-machine.md` | Pass | 视觉层级对齐 P/O；Agent visuals 只映射 A projection；不新增状态/转移 |
| 未把 Google 当作视觉复制 | Pass | Borrow/Adapt/Do Not Copy 分离；明确排除四色、渐变、布局和品牌资产 |
| 无过度装饰 | Pass | 中性面为主、单 accent、有限 motion、blur guard |
| 未削弱 Schwarz | Pass | Schwarz 是 scene owner、anchor 和持续状态载体；UI 视觉复杂度受限 |
| 无 Dashboard 倾向 | Pass | Workspace 禁止 permanent sidebar/toolbar/card wall/metrics |
| 无 gaming HUD / cyberpunk 倾向 | Pass | 排除霓虹、扫描线、游戏状态环、装饰线框和持续 glow |
| Motion 服务状态表达 | Pass | Enter/Exit/Expand/Morph/Activity/Result 各有语义；Waiting 不伪装进度 |
| 未过早设计最终 Screen | Pass | 只定义系统与高层 visual contracts，layout/geometry 保持 TBD |
| 未进入工程实现 | Pass | 无 Qt、CSS、类、API、渲染或 motion code |
| 所有视觉选择可 token 化 | Pass | 十一个 token family 与三层 reference/semantic/component 模型 |
| Accessibility 可验证 | Pass | 对比、非颜色状态、focus、Reduced Motion 和桌面背景测试均为门禁 |
| 未重设计 Agent backend | Pass | 状态视觉只消费 UI projection，不定义 backend lifecycle |

### Review conclusion

本文没有发现 `01 / 02 / 03` 之间的新视觉冲突。唯一已知产品冲突仍是 single-click Interact 与 double-click / candidate single-click Conversation Invocation 的映射；Design System 明确保留该阻断项，不用 hover、motion 或 Capsule 外观绕过它。

下一阶段在进入 Screen Specification 前，应先确认 gesture arbitration，并为 exact accent/typeface/material/motion 参数建立 Schwarz 素材与多桌面背景验证样本。本文不自动创建下一阶段文件。
