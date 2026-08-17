# ArkClaw Interaction Model

> 阶段：Phase 2 — Interaction Model Design  
> 文档类型：Product Design / UX Interaction Contract  
> 上位约束：`docs/product/01-ui-vision.md`  
> 下游用途：UI State Machine、Screen Specification、Interaction Prototype  
> 本文不包含：视觉 Token、精确尺寸、工程实现、Qt 设计、Agent 后端或工具协议

## 1. Purpose

本文定义用户如何通过 Schwarz 与 ArkClaw Desktop Agent 交互，以及 Character、Conversation Surface、Action Surface、Agent Workspace 与 Action Palette 在什么条件下出现、扩展、共存、收拢和消失。

本文把交互描述为可验证的产品契约：每个交互必须说明 Trigger（触发）、State（状态）与 Result（结果）。没有产品授权或与上位文档存在冲突的事项标记为 `TBD` 或 `Unknown`，不得由原型或实现自行补全。

### 1.1 规范词

- **必须（Must）**：不可违反的交互约束。
- **应该（Should）**：默认行为；偏离时必须经过产品评审。
- **可以（May）**：允许的行为，不代表第一版必须提供。
- **`TBD`**：方向已知，但规则尚待设计或确认。
- **`Unknown`**：是否需要、是否可用或前提条件尚不明确。
- **`Not Defined / Reserved`**：当前不赋予产品语义，保留给未来决策。

### 1.2 已发现的上位冲突

`01-ui-vision.md` 与本阶段输入对 Conversation 入口存在直接冲突：

| 来源 | 左键单击 | 左键双击 |
|---|---|---|
| `01-ui-vision.md` | 保护现有 `Interact` 语义 | 已确认产品意图：打开 Conversation Capsule；事件仲裁未决 |
| 本阶段输入 | 打开 Conversation Capsule | 重新判断是否需要语义 |

两种映射不能同时作为最终规则，否则会违反 `Pet Gestures Are Protected`。因此本文确定“**从 Schwarz 直接召唤 Capsule**”这一产品结果，但不静默改写手势：

- 在上位决策统一前，具体的单击/双击映射为 **阻断性 `TBD`**。
- 现有单击 `Interact`、拖拽、右键和命中规则继续受到保护。
- `01-ui-vision.md` 中的双击产品意图仍有效，但在完成单击/双击仲裁前不能进入实现规格。
- 如果未来正式确认“单击打开 Capsule”，则双击应改为 `Not Defined / Reserved`，除非另有独立、可验证且不冲突的产品价值。

本文后续使用 **Primary Conversation Invocation（主要对话召唤）** 指代这项尚待绑定最终手势的入口。

---

## 2. Interaction Principles

### 2.1 Character Is the Resting State

Schwarz 是默认状态，也是所有临时 Surface 的返回点。没有用户任务、待处理决定或值得注意的结果时，桌面只保留 Schwarz。

### 2.2 Intent Before Interface

用户先表达目标，ArkClaw 再披露完成目标所需的结构。用户不需要理解 tool name、MCP、raw API、internal command 或 runtime implementation。

### 2.3 One Primary Surface at a Time

同一时刻最多存在一个主 Conversation 容器：Capsule、Expanded Conversation 或 Workspace 三者择一。Action、Confirmation、Error 与 Progress 优先成为该容器中的上下文状态，而不是在 Schwarz 周围叠加多个窗口。

### 2.4 Complexity Must Be Earned

Surface 只有在当前内容、控制或持续时间无法由更轻层级可靠承载时才升级。回答较长本身不是打开 Workspace 的理由。

### 2.5 Collapse Is Not Cancel

收起 UI 只改变可见层级，不自动取消对话、任务或 Agent 行动。取消必须是独立、明确的用户意图。

### 2.6 State Must Be Honest

`Thinking`、`Acting` 与 `Waiting` 必须具有不同含义。界面不能用持续动画掩盖阻塞，也不能把计划显示成已经执行。

### 2.7 Existing Pet Gestures Win

尚未通过鼠标设计门禁的新手势，不得抢占现有单击、拖拽、右键、透明区域穿透或有效指针序列。

### 2.8 Interruption Must Be Proportional

只有需要立即决策或避免明显损失的事件可以主动取得前景。普通完成、非紧急等待与可恢复问题使用 ambient feedback 或用户主动展开。

---

## 3. Interaction Layers

交互层级不是固定页面导航，而是同一任务按复杂度变化的承载模型。

| Layer | Purpose | Entry condition | Exit result |
|---|---|---|---|
| `Character` | 表达存在、状态与入口 | 默认；所有 Surface 收拢后 | 打开 Capsule 或 Palette，或继续保持安静 |
| `Conversation Capsule` | 最低成本开始请求、澄清或查看短结果 | Primary Conversation Invocation；Agent 需要轻量输入 | 收拢到 Character，或扩展到 Expanded Conversation |
| `Expanded Conversation` | 承载需要连续上下文的多轮内容与较丰富结果 | Capsule 容量不足；用户主动扩展 | 收缩到 Capsule，或进入 Workspace |
| `Action Surface` | 表达真实行动、进度、确认与结果 | Agent 将执行、正在执行或已完成实际操作 | 融回 Conversation、转为 Result，或收拢 |
| `Agent Workspace` | 承载复杂、持续、多对象且需要控制的任务 | 任务结构达到 Workspace 条件 | 收缩到 Expanded/Capsule/Character，任务状态保留 |
| `Anchored Action Palette` | 提供角色、当前任务与应用级快捷动作 | 右键 Schwarz | 选择动作、转入 Conversation，或 dismiss |

### 3.1 Conversation 与 Action 不是串行页面

`Conversation → Action` 表示任务从表达意图进入实际行动，不表示必须打开另一个页面。若 Conversation 已可见，Action 状态优先在当前 Conversation 容器中呈现。若 UI 已收起，才使用最小独立 Action Surface 提供必要反馈。

### 3.2 Progressive Disclosure Ladder

```text
Character
  ├─ Primary Conversation Invocation → Capsule
  │    ├─ 内容连续性增加 → Expanded Conversation
  │    └─ 任务结构复杂 → Workspace
  └─ Right Click → Anchored Action Palette

Action / Confirmation / Result
  → 嵌入当前最合适的主 Surface
  → 完成后回到原上下文或逐级收拢
```

---

## 4. Character Interaction

## 4.1 Idle

**Trigger**：没有前景交互，且 Agent 没有需要用户立即处理的事项。  
**State**：Schwarz 处于 `Idle`。  
**Result**：桌面保持 Character only。

用户可以：

- 使用 Primary Conversation Invocation 召唤 Capsule；具体单击/双击绑定为 `TBD`。
- 右键打开 Anchored Action Palette。
- 使用现有拖拽行为移动 Schwarz。
- 在冲突解决前继续使用现有单击 `Interact`。

Idle 时不得显示永久输入框、toolbar、sidebar、status text、floating button 或 system panel。

Schwarz 可以有低频、非任务性的 ambient feedback，但不得：

- 被误解为 Agent 正在请求注意；
- 持续占用视觉焦点；
- 改变用户输入语义；
- 与 `Listening`、`Thinking`、`Acting` 等任务状态混淆。

Ambient feedback 的动画集合、频率与 Reduced Motion 替代为 `TBD`。

## 4.2 Hover

**Trigger**：指针进入 Schwarz 的既有有效命中区域，且没有进行中的按下/拖拽序列。  
**State**：保持当前 Agent 状态；Hover 不是新的 Agent 状态。  
**Result**：仅提供“可交互”的最低强度反馈。

规则：

- Hover 不打开 Capsule、Palette、Workspace 或按钮组。
- Hover 不显示大量操作，也不改变当前任务。
- 可以使用细微视觉反馈提示角色可交互；具体形式为 `TBD`。
- Hover 不应中断当前角色动画。是否使用可叠加、非中断式角色反馈为 `TBD`。
- 指针离开后反馈应自然撤销，不留下 UI；精确退场时机为 `TBD`。
- Hover 不能成为发现关键功能的唯一方式；键盘和辅助技术入口需另行定义。

## 4.3 Primary Conversation Invocation

**Trigger**：用户在 Schwarz 上执行最终确认的主要对话召唤手势。  
**State**：从 Character only 进入 `Listening`。  
**Result**：打开或恢复唯一的 Conversation Capsule。

交互顺序：

1. Schwarz 立即给出轻量“已接收召唤”的反馈。
2. Capsule 从 Schwarz 的空间语义附近出现，明确属于 Schwarz，而非凭空出现独立应用窗口。
3. Capsule 可交互后，文本输入获得焦点；若恢复的是正在阅读、确认或执行中的上下文，则恢复上次有意义的焦点，不强制跳到输入框。
4. 已存在 Capsule 时，召唤只恢复并聚焦原 Surface，不创建第二个 Capsule。

Capsule 与 Schwarz 保持可见的来源关系，但不得遮挡角色的主要可交互区域，也不得扩大透明的桌面阻挡区。具体方位、屏幕边界适配与动画属于后续 Screen Specification。

再次使用 Primary Conversation Invocation 时：

- Capsule 被收起：恢复 Capsule 和上下文。
- Capsule 已打开但未聚焦：聚焦现有 Capsule。
- Capsule 已打开且已聚焦：不创建副本、不提交输入；是否作为 toggle 收起为 `TBD`。

## 4.4 Left Click

左键单击的最终语义处于第 1.2 节所述冲突中。

- 当前受保护基线：单击触发一次 `Interact`。
- Phase 2 候选方向：单击打开 Conversation Capsule。
- 最终规则：`TBD — requires upstream decision`。

无论最终选择哪一种语义，点击后的角色反馈与 Capsule 出现必须被用户理解为同一次响应；不得先播放容易被理解为独立动作的反馈，再延迟出现 UI。

## 4.5 Double Click

双击在 `01-ui-vision.md` 中具有“打开 Capsule”的明确产品价值，因此当前不能标记为无意义的桌面惯例。

- 当前状态：产品意图已确认，输入仲裁 `TBD`。
- 若未来单击正式接管 Conversation：双击改为 `Not Defined / Reserved`。
- 不得为双击另行发明第二个功能。

## 4.6 Drag

**Trigger**：左键指针序列被识别为现有桌宠拖拽。  
**State**：角色进入既有拖拽交互；该手势优先于对话召唤。  
**Result**：Schwarz 移动；不得误开 Capsule 或提交 `Interact`。

UX 规则：

- Click 与 Drag 必须是互斥结果；具体阈值不在本文定义。
- 一旦成为 Drag，该指针序列不能再转成 Conversation Invocation。
- Drag 不取消正在执行的 Agent 任务。
- Palette 在 Drag 开始时 dismiss。
- Capsule 若为空且无活动任务，可暂时收拢；若包含草稿、结果或活动任务，内容必须保留，且不得跟随角色移动造成阅读困难。
- Expanded Conversation 与 Workspace 保持在原有桌面位置；拖拽完成后恢复与 Schwarz 的空间关联提示。
- Confirmation 或阻断 Error 不因拖拽被视为已处理。
- Drag 期间 Surface 的具体视觉过渡为 `TBD`，但不得阻断既有拖拽、下落与落地语义。

## 4.7 Right Click

**Trigger**：用户在 Schwarz 的既有有效命中区域右键。  
**State**：当前 Agent 状态保持不变。  
**Result**：出现一个 Anchored Action Palette；不触发角色动作。

Palette：

- 锚定于本次右键所指向的 Schwarz 上下文，并在屏幕可用区域内保持可访问。
- 打开时不暂停、不替换当前角色动画。
- 同一时刻只存在一个 Palette。
- 选择命令后 dismiss；点击外部、按 Escape、开始 Drag 或再次右键可 dismiss。
- 若存在阻断 Confirmation 或安全相关 Error，Palette 不得遮盖或替代该决定；只保留返回当前决定的路径。
- 与传统 Windows Context Menu 的迁移、能力对等和失败回退仍为 `TBD`。

---

## 5. Conversation Surface

## 5.1 Level 1 — Conversation Capsule

### Purpose

以最低交互成本开始一次 Agent 对话、提交简短请求、回答一次澄清或查看短结果。

### Interaction contract

| Item | Contract |
|---|---|
| Trigger | Primary Conversation Invocation；或 Agent 确实需要轻量用户输入 |
| Entry | 从 Schwarz 连续出现；先确认召唤已被接收，再进入可输入状态 |
| Visible content | 当前输入、最近且与当前任务直接相关的 Agent 回应、必要的状态或操作 |
| Input behaviour | 文本输入与 Submit 是基础能力；空输入不创建任务 |
| Focus behaviour | 新对话默认聚焦输入；恢复已有任务时恢复最有意义的上下文焦点 |
| Dismiss behaviour | 空闲且无草稿时可外部点击或 Escape 收拢；有草稿、等待或阻断状态时不得无提示丢失 |
| Expansion | 内容连续性、控制需求或任务结构超过 Capsule 能力时进入 Level 2 |
| Schwarz relationship | Schwarz 保持身份与状态载体；Capsule 是其临时延伸，不取代角色 |

第一版可以考虑 context / attachment entry、voice entry，但两者的范围、权限、反馈与可用性均为 `TBD`，不得因为占位控件而视为已确认功能。

Capsule 默认不包含：Sidebar、history browser、model selector、MCP、plugins、tool logs、developer console、token usage、temperature 或 raw system information。

### Input during Agent work

- `Thinking`：用户可以继续输入并取消。新提交内容被解释为对当前请求的补充或修正，Agent 必须明确显示已采纳并重新进入 `Thinking`，不能静默并行执行两个版本。
- `Acting`：用户可以编辑草稿。提交新指令时，UI 必须说明它将作为后续指令，还是需要先取消/重定向当前行动；具体重定向策略为 `TBD`。
- `Waiting`：输入优先回答当前等待问题；若用户开始新任务，必须明确当前等待是保留、取消还是稍后处理。

## 5.2 Level 2 — Expanded Conversation Surface

### Purpose

在不进入完整 Workspace 的前提下，承载持续对话、较长内容、多个相关结果或需要持续反馈的单一任务。

### Capsule → Expanded trigger

满足以下任一条件时可以扩展：

- 多轮上下文必须同时可见才能理解当前问题；
- 回答包含多个相关结果或必要的后续选择，Capsule 会隐藏关键信息；
- Agent 需要在一段时间内持续提供有意义的阶段反馈；
- 用户主动选择 Expand；
- 当前确认或错误需要保留足够上下文才能做出安全决定。

单纯因为回答字数较多、Agent 开始调用工具或产品希望展示更多功能，不构成扩展理由。

### Expansion behaviour

- 当关键内容或必要控制会被 Capsule 截断时，可以自动扩展到 Level 2。
- 其他情况应由用户主动扩展，或由 Agent提出可忽略的扩展建议。
- 扩展保持同一任务、草稿、阅读位置与 Agent 状态，不产生新窗口语义。
- Expanded Surface 仍与 Schwarz 保持来源关系，但可以降低空间依附以保证阅读。

### Collapse behaviour

- 用户可收缩回 Capsule；当前任务、关键结果与草稿保留。
- 收缩后的 Capsule 只显示继续当前任务所需的最小摘要，不复制完整长内容。
- 若存在 Confirmation、阻断 Error 或未保存输入，收缩不能隐藏其未解决状态；Character 必须继续表达 `Waiting` 或 `Error`。

## 5.3 Conversation continuity

Conversation Surface 是当前任务上下文，不是传统聊天软件的永久消息列表。历史会话的发现、跨会话管理、保留周期和搜索均为 `TBD`。

---

## 6. Action Surface

Action Surface 表达 Agent 与桌面应用、文件或工具发生的真实行动。它不是普通聊天消息，也不是低层工具日志。

## 6.1 Informational Action

**Use when**：行动会产生用户可感知的外部效果或短暂等待，例如“正在打开 VS Code”。  
**Do not use when**：操作极短、没有副作用且成功结果本身已经足够清楚。

规则：

- 若行动可取消，提供直接 Cancel；若不可取消，明确说明当前阶段不可取消，不显示虚假按钮。
- Conversation 可见时，Informational Action 嵌入当前 Conversation。
- Character only 时，使用最小临时 Action Surface。
- 完成后转为 Result；不得无限停留在进行中。
- 中间步骤没有用户价值时不逐条展示。

## 6.2 Progress

Progress 只用于用户需要理解耗时、阶段或控制权的任务，例如：

- 任务持续到用户可能怀疑是否仍在工作；
- 存在多个用户可理解的阶段；
- 用户可能需要取消、收起或稍后返回；
- 阶段性结果会影响下一步决定。

Progress 使用用户目标语言，例如“Reading project / Inspecting files / Running tests”，但不得暴露内部 tool name、调用参数、线程、Token、协议或重复重试噪声。

简单操作省略 Progress，直接从 `Thinking` 进入 Result。Progress 不承诺无法可靠估计的百分比；确定性进度与非确定性活动必须区分。

## 6.3 Confirmation

**Trigger**：行动具有明显副作用、范围可能超出用户当前表达，或需要用户在继续前作出选择。具体风险分类属于后续设计。

Confirmation 必须：

- 与发起它的 Conversation 和目标行动保持可见关联；
- 使用用户能理解的语言说明“将做什么、影响什么、确认后发生什么”；
- 提供明确的 Confirm 与 Cancel / Not now；
- 不以角色动画代替决定内容；
- 取得当前 Surface 的交互优先级，但不创建第二套堆叠窗口。

结果：

- Confirm → 进入 `Acting`，Confirmation 转为 Action/Progress。
- Cancel → 不执行该行动，记录为用户取消，并返回原 Conversation 上下文。
- 长时间无响应 → 保持 `Waiting`，绝不隐式确认；外部条件导致请求失效时，明确转为可理解的 expired/result 状态。

## 6.4 Result

| Result type | Required content | Dismiss rule |
|---|---|---|
| `Success` | 完成了什么；必要时给出可继续动作 | 简单且无后续要求时可短暂显示后收拢；Conversation 已打开时保留在当前上下文 |
| `Partial Success` | 已完成部分、未完成部分、影响与可选下一步 | 在用户看见并理解前不自动消失 |
| `Failure` | 用户目标未完成的原因、实际影响、恢复建议 | 阻断错误不自动消失；提供 Retry 或替代路径（若真实可用） |

Technical Details 默认隐藏，只在有助于诊断且用户主动展开时出现。不得把异常窗口、堆栈或 raw error 作为结果本身。

---

## 7. Agent Workspace

## 7.1 Trigger conditions

Workspace 用于复杂、持续且需要结构化控制的任务。满足以下一项并不必然打开；应综合判断任务是否需要同时保留多个对象、阶段和结果：

- multi-step task，且用户需要查看或控制阶段关系；
- project inspection，需要组织项目范围、发现与后续动作；
- multiple files 或多个可比较对象；
- persistent artifacts，需要持续查看、选择或交付；
- long-running task，需要离开后返回、检查进度或处理阻断；
- complex tool activity，且用户需要理解高层行动、范围或影响。

以下情况不得单独触发 Workspace：

- 一次回答稍长；
- 一次普通工具调用；
- 产品想展示更多功能；
- 仅需要一个确认或一个结果。

## 7.2 Entry rule

- 用户主动选择 Open Workspace 时进入。
- Agent 可以在 Expanded Conversation 中提出扩展建议，并说明 Workspace 将解决什么承载问题。
- 用户已明确请求天然需要 Workspace 的复杂任务时，该请求可以视为对扩展的同意，但转换仍必须连续且可理解。
- 不得从 Character only 无提示弹出大型 Workspace。

## 7.3 Workspace role

Workspace 存在是为了让用户理解和控制一个复杂任务，而不是提供更大的聊天窗口。

它应该承载：

- 当前目标与范围的简明表述；
- 用户可理解的任务阶段与当前状态；
- 与任务直接相关的文件、结果、artifact 或选择；
- 需要用户处理的确认、冲突和错误；
- 可用时的 Cancel、Retry、Continue 或 Return controls；
- 与当前任务相关的精简 Conversation 上下文。

它仍然不应该默认显示：

- 永久 Sidebar 或 IDE 式树状导航；
- 原始 tool call、MCP、API、runtime、线程或日志流；
- model selector、temperature、token usage 或开发者控制台；
- 与当前任务无关的全局管理面板；
- 为制造“忙碌感”而堆叠的状态卡片。

## 7.4 Collapse and continuity

用户可以：

```text
Workspace
→ Expanded Conversation
→ Conversation Capsule
→ Character only
```

每次收缩都保留任务状态、关键结果和待处理决定。用户也可以明确选择直接回到 Character only；这不会取消任务。若任务仍在 `Acting`、`Waiting` 或 `Error`，Schwarz 必须保留相应状态信号，并提供恢复入口。

---

## 8. Action Palette

## 8.1 Purpose

Anchored Action Palette 提供无需先组织一句自然语言即可完成的少量高确定性动作。它是辅助入口，不取代 Conversation First。

## 8.2 Information architecture

Palette 使用少量上下文分组，而不是深层级菜单：

1. **Ask ArkClaw**：转入或恢复 Conversation Capsule。
2. **Current Task**：仅在存在活动任务时出现，包含 View / Return to task，以及真实可用的 Cancel 或 Continue。
3. **Character**：当前确认的角色动作，如 Relax、Sit、Sleep、Move、Special；在同一分组内直接选择，避免再进入多层菜单。
4. **ArkClaw**：Settings、Hide Schwarz、Quit 等应用级操作。

规则：

- 空的 `Current Task` 分组不显示。
- Agent Actions 只展示当前上下文中高确定性、用户可理解的动作，不暴露工具目录。
- Character Actions 与 Agent Actions 必须分组，避免把角色动画误解为 Agent 工具执行。
- Settings、Hide 与 Quit 保持可达，但不占据角色附近的永久 UI。
- Quit 的确认需求为 `TBD`；不得在本文设计具体安全机制。
- 第一版准确标签、排序和可用项仍需根据真实能力验证，状态为 `TBD`。

## 8.3 Dismiss and transition

- 点击外部、Escape、再次右键、开始 Drag 或完成一个选择时 dismiss。
- 选择 Ask ArkClaw 时，Palette 转换为 Capsule，不允许两者并排堆叠。
- 选择 Character Action 后，Palette dismiss，Schwarz 执行动作；失败时使用最小 Result，而不是保持菜单悬挂。
- 打开 Palette 本身不改变角色动画或 Agent 状态。

---

## 9. Agent State Feedback

角色与 Surface 必须表达同一个 Agent 状态；Surface 提供语义，Schwarz 提供持续、低干扰的可感知反馈。

| Agent state | Schwarz contract | Surface contract | User control |
|---|---|---|---|
| `Idle` | 安静、可用；允许低频 ambient feedback | 默认无 Surface；打开的空闲 Capsule 可收拢 | 召唤 Conversation、打开 Palette、拖拽、既有 Interact |
| `Listening` | 表达正在接收输入，但不持续抢占注意力 | Capsule/Conversation 输入可见并获得合理焦点 | 输入、Submit、Dismiss |
| `Thinking` | 表达正在判断，不能像已开始外部行动 | Conversation 显示当前请求与简洁状态；不显示低层工具噪声 | Cancel；继续输入；提交修正或补充 |
| `Acting` | 与 `Thinking` 可区分，表达正在对桌面环境采取行动 | 显示必要的 Action/Progress；优先嵌入当前主 Surface | 可取消时 Cancel；可展开时 Inspect progress；可收拢 UI |
| `Waiting` | 明确处于等待，而不是继续工作 | 显示等待对象：confirmation、external dependency 或 required input | Confirm/Cancel、提供输入、稍后返回；不得隐式继续 |
| `Success` | 短暂、克制的完成反馈，随后降低强度 | 简单结果可临时显示；复杂结果保留在 Conversation/Workspace | Continue、查看结果或 Collapse |
| `Error` | 可识别但不惊吓；不循环制造焦虑 | 说明目标、影响、可恢复动作；技术详情默认隐藏 | Retry、改变请求、Details（若有价值）、Collapse 后稍后返回 |

### 9.1 Cancellation contract

- `Thinking` 必须允许 Cancel。
- `Acting` 仅在行动真实可取消时显示 Cancel；不可取消阶段必须诚实表达。
- Collapse 或关闭 Surface 不等于 Cancel。
- Cancel 后显示明确结果，并返回最近可继续的 Conversation 层级。

### 9.2 Timing

Success feedback、ambient feedback、临时 Result 与自动收拢的具体持续时间均为 `TBD`。后续设计应基于可读性、Reduced Motion 与任务风险验证，不使用一个固定时长覆盖所有状态。

---

## 10. Surface Priority

优先级用于决定谁拥有前景交互，不表示把所有较低 Surface 同时显示。

```text
1. Safety-critical interruption / invalidating critical error
2. Required confirmation or blocking user input
3. Active primary surface: Workspace > Expanded Conversation > Capsule
4. Active Action / Progress
5. Anchored Action Palette
6. Passive result / ambient notification
```

### 10.1 Resolution rules

1. 安全相关错误若使待确认行动不再有效，应替代该 Confirmation，并解释原因。
2. Confirmation 在有效时取得当前主 Surface 的输入优先级；Conversation 上下文可见但不与其争夺操作。
3. Workspace、Expanded 与 Capsule 只保留当前最高层级，不能同时作为三个窗口存在。
4. Action/Progress 在主 Surface 可见时嵌入；否则才出现最小临时 Surface。
5. Palette 不覆盖 Confirmation、阻断 Error 或关键 Action control。
6. Passive notification 在任何更高优先级 Surface 活跃时降级为 ambient signal 或合并到当前上下文。

---

## 11. Surface Coexistence Rules

| Combination | Rule | Reason |
|---|---|---|
| Conversation Capsule + Action Palette | **Not Allowed** | 两者都以 Schwarz 为轻量入口；打开一方应 dismiss 或转换另一方，避免入口竞争 |
| Conversation + Agent Activity | **Allowed / Conditional** | Activity 必须嵌入当前 Conversation，或以单一关联区域表达；不得成为无规则叠层 |
| Workspace + Character Palette | **Allowed / Conditional** | Workspace 保持，右键 Schwarz 可临时打开 Palette；Palette 不复制 Workspace 的任务控制，也不覆盖阻断决定 |
| Confirmation + Conversation | **Allowed / Conditional** | Confirmation 在当前 Conversation 上下文中取得输入优先级；Conversation 可读，但普通 Submit 不与确认争夺 |
| Error + Activity | **Conditional** | 同一行动的 Error 替代失败的 Activity；无关后台活动只保留摘要，不产生第二个竞争前景 |
| Palette + Confirmation | **Not Allowed** | 待确认决定优先；Palette 只能提供返回该决定的路径 |
| Passive notification + foreground Surface | **Conditional** | 不另弹 Surface；合并到当前上下文或降级为 ambient feedback |
| Capsule + Expanded Conversation | **Not Allowed** | 二者是同一个 Conversation 的不同层级，只能存在一个 |
| Expanded Conversation + Workspace | **Not Allowed** | 进入 Workspace 是同一容器扩展，不是打开第二个主窗口 |

---

## 12. Dismiss / Collapse Model

## 12.1 Escape

Escape 遵循“先关闭最上层、再逐级收拢、从不隐式取消任务”的规则。

| Current context | Escape result |
|---|---|
| Action Palette | Dismiss Palette；不触发动作 |
| Confirmation | 选择安全的 Cancel / Not now，明确记录未执行；若无法安全等同取消则保持并给出说明，具体例外为 `TBD` |
| Error Details | 先收起 Details，保留用户可理解的 Error summary |
| Blocking Error | 不把错误标记为解决；可收拢到 Character signal，并保留恢复入口 |
| Capsule，空闲且无草稿 | 收拢到 Character only |
| Capsule，有草稿或活动任务 | 收拢但保留会话内草稿与任务；不提交、不取消 |
| Expanded Conversation | 收缩到 Capsule |
| Workspace | 先关闭 Workspace 内临时层，再收缩到 Expanded Conversation |
| Thinking / Acting Surface | 收拢 UI，任务继续；Cancel 必须单独触发 |

## 12.2 Click Outside

- Hover feedback、Palette 与纯临时 Informational Surface 支持外部点击关闭。
- 空闲且无草稿的 Capsule 可以外部点击收拢。
- 有草稿的 Capsule 外部点击仅移除输入焦点，不丢弃草稿。
- Expanded Conversation 与 Workspace 不通过外部点击关闭。
- Confirmation 与阻断 Error 不通过外部点击消失。
- 外部点击不得被解释为 Confirm、Submit 或 Cancel。

## 12.3 Task Completion

- Character only 下完成简单任务：Schwarz 给出 Success，最小 Result 临时出现；无后续要求时可自动收拢。
- Conversation 已打开：Result 保留在当前上下文，等待 Continue 或 Collapse，不强制关闭。
- Workspace 任务完成：保留结果与 artifacts，等待用户查看或主动收缩。
- Partial Success 与 Failure：在用户能够理解结果与下一步前不自动消失。
- 自动收拢的具体时间为 `TBD`。

## 12.4 Manual Collapse

用户始终可以主动降低 UI 占用：

```text
Workspace → Expanded Conversation → Capsule → Character only
```

也可以使用明确的“回到桌面”意图直接收拢到 Character only。任何收拢都必须：

- 保留活动任务、当前结果和待处理决定；
- 不提交草稿；
- 不暗示任务已取消或完成；
- 让 Schwarz 继续表达 `Thinking`、`Acting`、`Waiting` 或 `Error`；
- 提供恢复到原任务的路径。

会话草稿跨应用重启是否保留为 `TBD`。

---

## 13. Notification Model

ArkClaw 采用三级主动反馈，而不是默认弹出传统 Windows notification。

## 13.1 Interruptive

只有以下事件可以主动取得前景：

- 需要立即确认才能继续且延迟可能改变结果；
- 需要用户输入才能避免明显损失或错误行动；
- 安全相关、不可恢复或会使当前决定失效的关键错误。

Interruptive feedback 仍应出现在当前任务上下文中，不使用惊吓式动画或无关系统弹窗。

## 13.2 Ambient

以下事件默认使用 subtle character feedback、最小临时 Surface 或待查看信号：

- 后台任务完成；
- 非紧急的用户输入请求；
- 外部依赖仍在等待；
- 可恢复且不影响当前工作的失败；
- 用户收起 UI 后出现的新阶段结果。

用户主动点击该信号后恢复相关 Conversation 或 Workspace。待查看信号不得演变为永久状态栏或数字焦虑；具体形态为 `TBD`。

## 13.3 Silent

以下事件不主动显示：

- 内部工具选择与调用细节；
- 快速成功的中间步骤；
- 已自行恢复且不影响结果的重试；
- 不改变用户目标、风险或等待时间的内部状态变化。

## 13.4 System notification boundary

是否在 ArkClaw 不可见、用户离开桌面或任务具有时效性时使用操作系统通知为 `TBD`。在确认前，不把 Windows notification 作为默认完成反馈。

---

## 14. Keyboard Interaction

本文只定义 UX contract，不指定实现。

| Input | Contract |
|---|---|
| `Escape` | 关闭最上层 dismissible context 或逐级收拢；不隐式取消任务 |
| `Enter` | 输入焦点位于 Conversation 时提交当前非空请求；输入法正在组合文字时不得误提交 |
| `Shift+Enter` | 在 Conversation 输入中插入换行，不提交 |
| Focus input | 新建轻量对话时聚焦输入；恢复结果、Confirmation 或 Workspace 时恢复上次有意义的焦点 |
| Keyboard navigation | 所有可见操作必须可在不依赖 Hover 或 Drag 的情况下到达；具体顺序由 Screen Specification 定义 |
| Global shortcut | 可作为未来的 Capsule 召唤入口，但是否提供与具体组合键均未确认：`Shortcut: TBD` |

Global shortcut 不得与操作系统或常用应用快捷键冲突，也不得绕过 Confirmation 或把后台输入误发送给 Agent。

---

## 15. Core User Flows

流程中的 `Primary Conversation Invocation` 表示“直接从 Schwarz 召唤 Capsule”；具体单击/双击绑定仍为阻断性 `TBD`。

## 15.1 Flow A — Simple Conversation

```text
Idle / Character only
→ Primary Conversation Invocation on Schwarz
→ Schwarz acknowledges
→ Conversation Capsule / Listening
→ Type
→ Submit
→ Thinking
→ Short response in Capsule
→ Continue / Collapse to Character only
```

验证点：不打开 Workspace；不显示工具或模型配置；收拢不丢失当前结果。

## 15.2 Flow B — Open Desktop Application

```text
Idle
→ Primary Conversation Invocation
→ Capsule
→ “Open VS Code”
→ Submit
→ Thinking
→ Acting / “Opening VS Code…”
→ Success or Failure Result
→ Continue / Collapse
```

验证点：普通打开行为不因工具调用而升级 Workspace；只有真实可取消时显示 Cancel。

## 15.3 Flow C — Confirmation Required

```text
Conversation
→ User request
→ Thinking
→ Required Confirmation / Waiting
→ Confirm
→ Acting
→ Success
→ Return to previous Conversation context
```

Cancel 分支：

```text
Confirmation
→ Cancel / Not now
→ No action performed
→ Cancellation Result
→ Return to Conversation
```

验证点：点击外部不确认；长时间不响应不隐式继续。

## 15.4 Flow D — Character Action

```text
Idle
→ Right Click Schwarz
→ Anchored Action Palette
→ Character group
→ Sit
→ Palette dismiss
→ Schwarz performs Sit
```

验证点：打开 Palette 不改变动画；Agent Actions 与 Character Actions 不混淆；不经过多层页面。

## 15.5 Flow E — Complex Agent Task

```text
Conversation Capsule
→ Submit complex task
→ Thinking
→ Content requires continuity
→ Expanded Conversation
→ Workspace is proposed or implied by explicit complex request
→ Agent Workspace
→ Semantic task progress / decisions / artifacts
→ Result
→ Review
→ Collapse to Expanded / Capsule / Character only
```

验证点：Workspace 由任务结构而非回答长度触发；Collapse 不取消任务；技术日志默认隐藏。

## 15.6 Interaction Cost Review

| Core task | Target interaction cost | Model decision |
|---|---:|---|
| Start a conversation | 1 direct invocation | Schwarz → focused Capsule；具体手势 `TBD` |
| Ask one simple question | Invocation + Submit | 不进入 Expanded 或 Workspace |
| Open an application through Agent | Invocation + Submit；仅风险需要时增加 Confirmation | Acting 与 Result 在 Capsule 内完成 |
| Cancel an Agent action | 活动 Surface 中 1 次直接操作；UI 已收起时先恢复任务，共不超过 2 次 | Cancel 不藏入多层菜单；仅真实可取消时出现 |
| Select a character animation | Right Click + select action | Character actions 在 Palette 同一分组直接可选，不再进入深层菜单 |
| Open Settings | Right Click + Settings | 保持两步可达；不提供永久 Settings 入口 |
| Return to quiet desktop | 1 次明确收拢可直接回 Character；Escape 支持逐级返回 | Collapse 不等于 Cancel，状态由 Schwarz 延续 |

如果后续 Screen Specification 使以上常用动作增加额外无必要层级，应视为交互回归。

---

## 16. Edge Cases

## 16.1 Capsule 已打开时再次点击 Schwarz

- 若该输入是已确认的 Primary Conversation Invocation：恢复并聚焦现有 Capsule，不创建副本、不提交内容。
- 若最终仍保留单击 `Interact`：单击继续执行 `Interact`，不改变 Capsule。
- 在手势冲突解决前，具体映射为 `TBD`。

## 16.2 Action Palette 已打开时左键 Schwarz

- Palette dismiss。
- 左键随后只能执行最终确认的单击语义；不得同时触发 `Interact` 和打开 Capsule。
- 若该操作意图是进入 Conversation，Palette 应转换为 Capsule，而非二者共存。

## 16.3 Agent 正在 Acting 时用户再次输入

- 用户可以编辑草稿。
- 新 Submit 不得静默中断正在发生的外部行动。
- UI 必须明确新内容将作为后续指令，还是需要 Cancel / Redirect 当前行动；Redirect 的精确规则为 `TBD`。

## 16.4 用户在 Thinking 时关闭 Surface

- Surface 收拢，Thinking 继续。
- Schwarz 表达 `Thinking`。
- 重新召唤恢复同一任务。
- 关闭不等于 Cancel。

## 16.5 Workspace 打开时 Schwarz 被拖动

- Workspace 保持原位置和任务连续性，不随 Schwarz 移动。
- Drag 不取消任务、不关闭 Workspace。
- 拖动结束后恢复角色与 Workspace 的来源关联；具体视觉方式为 `TBD`。

## 16.6 Agent 请求确认时用户长时间不响应

- Agent 保持 `Waiting`，不隐式确认。
- Confirmation 可以被用户明确收拢，但 Schwarz 必须保留待处理信号和恢复入口。
- 若外部条件令确认失效，转为 expired Result 并解释影响；超时条件为 `TBD`。

## 16.7 Error 出现后用户继续输入

- 输入仍可用于 Retry、修改目标或开始恢复路径。
- Error summary 保留到其被解决、替代或用户明确结束当前任务。
- 新输入不能让原失败无说明地消失。

## 16.8 Agent 工作过程中 UI 被手动收起

- 工作继续，除非用户明确 Cancel。
- Schwarz 继续表达 `Thinking`、`Acting`、`Waiting` 或 `Error`。
- 值得通知的变化按第 13 节处理。
- 重新召唤恢复原上下文，而不是新建重复任务。

## 16.9 用户快速重复点击角色

- 不创建多个 Capsule、Palette 或重复提交。
- 一个有效召唤只恢复同一个主 Surface。
- 现有 `Interact`、Drag 与 Right Click 仍按各自确认语义工作。
- 重复点击的识别、单击/双击反馈和取消规则是鼠标门禁的一部分，当前为 `TBD`。

## 16.10 Action 完成时用户正在其他 Surface 中

- 不弹出第二个竞争前景。
- 结果合并到所属 Conversation/Workspace，或降级为 ambient feedback。
- 只有第 13.1 节的中断性条件允许取得前景。

## 16.11 用户收起有草稿的 Capsule

- 草稿在当前 ArkClaw 会话期间保留，不自动提交。
- 再次召唤恢复草稿。
- 跨进程或重启保留规则为 `TBD`。

---

## 17. Explicit Non-goals

本阶段不设计或决定：

- Qt class hierarchy、QWidget、QML；
- Windows HWND、Z-order implementation、native event handling；
- pointer threshold、double-click interval 或事件分发实现；
- animation implementation；
- exact geometry、exact pixel sizes；
- color tokens、typography tokens、final icons、final visual assets；
- API architecture、Agent backend、tool protocol、MCP；
- persistence architecture；
- 文件、插件或工具的具体能力实现；
- `03-ui-state-machine.md`、Design System、Screen Specification 或 TDD。

本文中的状态、优先级和流程是产品 UX contract，不是工程类、事件循环或窗口管理方案。

---

## 18. Unknown / TBD

以下问题必须在进入相关下游规格前解决：

1. **阻断项**：左键单击 `Interact`、单击打开 Capsule 与双击打开 Capsule 的最终权威映射。
2. 单击/双击/拖拽之间的产品级优先级、取消语义与反馈规则；具体数值不在本文阶段决定。
3. Primary Conversation Invocation 在已有 Capsule 聚焦时是否作为 toggle 收起。
4. Hover 的具体可交互提示与是否允许非中断式角色反馈。
5. Capsule、Expanded、Workspace 与 Schwarz 的具体方位、屏幕边界和视觉连接。
6. context / attachment entry 与 voice entry 是否进入第一版，以及对应权限和失败反馈。
7. Capsule 自动扩展到 Expanded 的内容容量标准。
8. 哪些复杂任务可将用户原始请求视为进入 Workspace 的同意。
9. Acting 中新指令的 Queue、Redirect 与 Cancel 规则。
10. 各类实际行动的 cancellability 与不可取消阶段表达。
11. 高影响操作的 Confirmation 分类与范围语言。
12. Success、ambient feedback、临时 Result 和自动收拢的持续时间。
13. 待查看信号的形态，以及是否、何时允许操作系统通知。
14. 多个并行或后台任务的选择、归属与通知模型。
15. Conversation history、搜索、保留周期与跨会话恢复。
16. 草稿与任务上下文跨应用重启的保留规则。
17. Action Palette 第一版准确标签、排序、能力对等、Quit 确认与传统菜单迁移。
18. `Shortcut: TBD`；键盘召唤、辅助技术入口与焦点恢复细节。
19. Agent 七种状态对应的角色动画、文本、声音、Reduced Motion 和无动画替代。
20. Confirmation 因外部条件失效的超时与结果规则。

---

## 19. Consistency Review

| Review item | Result | Evidence / correction |
|---|---|---|
| 符合 `01-ui-vision.md` | **Conditional pass** | 产品定位、Design Principles、Surface 关系与手势保护均保留；单击/双击冲突已显式列为阻断性 `TBD`，未静默覆盖 |
| 未退化为传统 Chat App | **Pass** | Conversation 是当前任务 Surface；不设计永久历史、会话 Sidebar 或常驻输入框 |
| 没有过多永久 UI | **Pass** | Character only 是 resting state；所有其他 Surface 按需出现 |
| Character First 成立 | **Pass** | Schwarz 是入口、状态载体与所有收拢路径的终点 |
| UI on Demand 成立 | **Pass** | 每个 Surface 有明确 Trigger，并禁止默认打开 Workspace |
| Progressive Disclosure 清晰 | **Pass** | Capsule、Expanded、Workspace 具有不同、可验证的升级条件 |
| Surface 冲突已处理 | **Pass** | 定义优先级、互斥表与嵌入规则；禁止 Capsule 与 Palette 堆叠 |
| 退出与收起清楚 | **Pass** | Escape、外部点击、任务完成与手动收拢均已定义；Collapse 不等于 Cancel |
| 未过早进入视觉设计 | **Pass** | 未定义颜色、字体、图标、尺寸或最终动效 |
| 未过早进入工程实现 | **Pass** | 未定义 Qt、事件、窗口或后端架构；手势数值与实现保持非目标 |

### Review conclusion

本文可以作为 UI State Machine 与 Screen Specification 的输入，但**不能在单击/双击阻断项解决前，把 Primary Conversation Invocation 映射为具体鼠标事件**。下一阶段应先统一上位入口决策，再建立状态机；不得由状态机文档反向替产品做出该决定。
