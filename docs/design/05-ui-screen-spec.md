# ArkClaw UI Screen / Surface Specification

> 阶段：Phase 5 — UI Screen / Surface Specification  
> 文档类型：Product Design / Implementable Surface Contract  
> 上位约束：`docs/product/01-ui-vision.md`、`02-interaction-model.md`、`03-ui-state-machine.md`、`04-ui-design-system.md`  
> 下游用途：low/high-fidelity prototype、prototype review、frontend engineering TDD、implementation planning  
> 本文不包含：代码、Qt/QML/QSS、controller architecture、backend redesign 或最终资产

## 1. Purpose

本文把已确认的产品、交互、状态和视觉规则转化为可审查、可原型化、可验收的 UI Surface Specification。这里的 Screen 不是传统页面，而是围绕 Schwarz、当前任务和 UI presentation state 按需出现的 Surface。

本文只规定用户可观察的结构、内容、层级、行为和状态映射：

- 不重新定义 Product Positioning、Interaction Model、UI State Machine 或 Design System；
- 不把 Surface 命名解释为窗口、类或工程模块；
- Agent states 仅指 `03` 中由 backend facts 驱动的 presentation-level projections；
- 本文不解决 Primary Conversation Invocation 的 single-click / double-click 冲突；
- 未经 gesture gate 确认，wireframe 中的 Character → Capsule 只表示语义入口，不授权具体鼠标事件。

### 1.1 Normative terms

- **Must**：原型、TDD 与实现不得违反。
- **Should**：默认规则；偏离必须记录原因并评审。
- **Planned**：已保留设计位置，但能力/MVP 尚未确认；不得发布无功能的假控件。
- **`TBD` / `Unknown`**：尚未确认，不得由 Screen 或工程静默决定。

### 1.2 Recorded upstream conflict

除已知的 Primary Conversation Invocation gesture 冲突外，复核发现一项 Capsule dismiss 差异：

| Source | Capsule with draft + outside click |
|---|---|
| `02-interaction-model.md` §12.2 | 只移除输入焦点，不丢弃草稿 |
| `03-ui-state-machine.md` §13 | Dismiss 到 Character only，并保留草稿 |

两者共同确认“草稿不得丢失”，但是否保持 Capsule 可见并不一致。本文不替上位文档选择：该动作的最终可见结果标记为 `TBD — requires upstream alignment`。Escape 仍按 `03` 逐级收拢。

---

## 2. Surface Inventory

| ID | Surface | State-machine owner | Primary role | Default persistence |
|---|---|---|---|---|
| `S0` | Character-only Desktop State | `P=CHARACTER_ONLY` | 默认桌面、入口、状态载体 | Persistent |
| `S1` | Conversation Capsule | `P=CAPSULE_IDLE/TYPING` | 发起轻量自然语言交互 | Temporary |
| `S2` | Expanded Conversation | `P=CONVERSATION_EXPANDED` | 持续对话、较长回答、关联结果 | Task-bound |
| `S3` | Agent Activity | `A=THINKING/ACTING` 的上下文表现 | 真实活动、进度与控制 | State-bound |
| `S4` | Confirmation | `O=CONFIRMATION_MODAL` + `A=WAITING_CONFIRMATION` | 明确授权或拒绝 | Blocking until explicit resolution/collapse |
| `S5` | Result | `A=SUCCESS/CANCELLED` | 表达完成、部分完成或取消 | Content-dependent |
| `S6` | Error | `A=ERROR`; critical 时 `O=CRITICAL_ERROR_MODAL` | 解释失败和恢复路径 | Until understood/resolved/collapsed |
| `S7` | Anchored Action Palette | `O=ACTION_PALETTE_OPEN` | 少量上下文动作 | Temporary |
| `S8` | Character Action Palette | `O=CHARACTER_ACTION_PALETTE` | 角色动作选择 | Temporary |
| `S9` | Agent Workspace | `P=WORKSPACE_OPEN` | 复杂、持续、多对象任务 | Task-bound |
| `S10` | Passive / Ambient Notification | `O=TEMPORARY_NOTIFICATION` 或 Character signal | 低打扰的待查看反馈 | Temporary / ambient |

### 2.1 Universal Surface contract

所有 Surface 都必须遵守：

1. 同时最多一个主 Presentation 和一个前景 Overlay。
2. Surface 必须有明确 Trigger、Precondition、Entry、Exit 和 return target。
3. Dismiss / Collapse / Close 只改变 UI visibility，不发送 Cancel intent。
4. Focus 始终属于最高优先、可见、有效的交互层；关闭后恢复到有效来源。
5. Activity、Result 和普通 Error 在主 Presentation 可见时优先嵌入，不另开竞争窗口。
6. Thinking、Acting、Waiting、Success、Error、Cancelled 只响应当前有效 backend projection fact。
7. 所有状态使用文字/图标/containment/motion 中至少两类线索，不只靠颜色。
8. Reduced Motion 保留完整状态与可读结果。
9. 无 Surface 可以遮挡 Schwarz 主要身体轮廓、既有 hit region 或制造透明阻挡区。
10. 不显示 raw tool、MCP、API、token、runtime、thread、stack trace 或 developer controls，除非未来通过 Details progressive disclosure 明确授权。

### 2.2 Shared visual language

- Shape：`shape.full` 用于 Capsule/Pill；`shape.l` 用于 Palette/Floating container；`shape.xl` 用于 Focused/Expanded/Workspace。
- Spacing：只使用 `spacing.0–8`；compact 以 `spacing.2–4`，comfortable 以 `spacing.4–5`，rich 以 `spacing.5–7` 组织。
- Surface：`none → ambient → floating → focused → workspace`。
- Material：长文本、Confirmation、Error、Workspace 使用稳定近不透明材质；blur 只在满足 `04` guard 时作为辅助。
- Motion：一个主导容器 motion；exit 不比 enter 拖沓；状态结果不能等动画结束才可读。

---

## 3. Character-only Desktop State

| Field | Specification |
|---|---|
| **Purpose** | ArkClaw 的 resting state；保持 Schwarz 可达、状态诚实且桌面安静。 |
| **Trigger** | 应用处于可见桌宠状态；所有临时 Surface 已收拢；或用户明确 Return to desktop。 |
| **Preconditions** | Schwarz 未被 Hide/Quit；若 A 非 Idle，必须存在可恢复任务 identity。 |
| **Anchor** | Schwarz 本体即 anchor；无独立 UI container。 |
| **Visual Priority** | Character 是唯一持久层；active projection 只提高 Schwarz/ambient signal 强度，不增加永久面板。 |
| **Visible Elements** | Schwarz；仅在有活动/待查看任务时允许一个克制的状态或待查看 signal。 |
| **Hidden Elements** | Input、toolbar、sidebar、status label、task panel、buttons、floating orb、permanent badge、developer status。 |
| **Primary Action** | Primary Conversation Invocation（具体输入绑定为阻断性 `TBD`）。 |
| **Secondary Actions** | 既有 Interact、Right Click Palette、Drag；Hover 仅反馈可交互。 |
| **State Variants** | Idle；Thinking/Acting/Waiting/Success/Error/Cancelled projection 下的 Character-only；Hover；Dragging。 |
| **Entry Behaviour** | Capsule/Expanded/Workspace 按来源方向收拢；有 active A 时视觉注意交给 Schwarz。 |
| **Exit Behaviour** | 进入 Capsule、Palette，或保持 Character only 并响应既有桌宠动作。 |
| **Expansion / Collapse** | 本身不可再收缩；Invocation 恢复当前任务的最后有效 Surface 或打开 Capsule。 |
| **Keyboard Behaviour** | 无默认常驻焦点。Global shortcut 若确认可召唤 Capsule：`Shortcut: TBD`。Escape 无可见层时不取消任务。 |
| **Outside Click** | 无效果；不得拦截桌面。 |
| **Relationship with Schwarz** | Schwarz 是完整视觉主体、入口和 A projection 载体，不是按钮旁的装饰。 |
| **Relationship with Agent State** | A=Idle 时真正 `DESKTOP_IDLE`；A 活动时仍 P=Character only，但必须可感知并可恢复。 |
| **Motion Contract** | Idle 低频 ambient；active projection 使用 `04` 对应 motion；不得持续多元素循环。 |
| **Accessibility Notes** | 状态不只靠角色姿态/颜色；必要 signal 有可访问名称；Hover/Drag 不是唯一入口；Reduced Motion 使用静态状态 cue。 |
| **Forbidden Behaviours** | 永久 UI、角色周围按钮环、点击透明区、Hover 打开大型 UI、active task 无恢复入口、用外观暗示未确认 click mapping。 |

### 3.1 Product-level pointer behaviour

| Input | Behaviour |
|---|---|
| Hover | 最低强度反馈；不创建 Surface，不中断角色动画；精确视觉/时机 `TBD`。 |
| Left click | 当前受保护基线为一次 `Interact`；是否改为 Capsule 入口仍为阻断性 `TBD`。 |
| Double click | `01` 已确认 Capsule 产品意图，但与 single click 的仲裁未决；在门禁通过前不进入实现规格。 |
| Right click | 目标形态为 Anchored Action Palette；替换现有菜单前必须完成能力对等和迁移确认。 |
| Drag | 既有 Drag 优先；同一指针序列不得触发 Interact、Invocation 或 Palette。 |

### 3.2 Low-fidelity state

```text
Desktop content remains unobstructed

                              [Schwarz]

No input, toolbar, badge rail, status bar, or floating control
```

---

## 4. Conversation Capsule

| Field | Specification |
|---|---|
| **Purpose** | 以最低成本开始请求、回答一次澄清或查看短结果。 |
| **Trigger** | `primary_conversation_invoked`（gesture `TBD`）；或 backend 要求轻量输入且 notification guard 允许。 |
| **Preconditions** | `G1 Gesture resolved`；无 blocking Confirmation/Critical Error；不存在第二个主 Presentation。 |
| **Anchor** | Schwarz 邻近可用区域，默认 gap `spacing.3`，必要时 `spacing.4`；不遮挡角色主体/hit region。 |
| **Visual Priority** | `surface.floating` / `elevation.2`；高于 Ambient/Palette return target，低于 Confirmation/Critical Error。 |
| **Visible Elements** | 持续可理解的 “Ask ArkClaw” 输入 identity、text input、Send；Context/Attachment 与 Voice 的语义位置标记为 `Planned`；需要时 Expand。 |
| **Hidden Elements** | Sidebar、history browser、model selector、MCP/plugins、tool logs、token/temperature、toolbar、large branding、suggestion-card wall。 |
| **Primary Action** | 输入并 Submit 当前非空请求。 |
| **Secondary Actions** | 添加 context（Planned）、voice（Planned）、Expand、Dismiss；真实可用时 Cancel/Retry 嵌入状态区。 |
| **State Variants** | Empty、Focused、Typing、Submitted/pending acknowledgement、Thinking、short Acting、short Result、inline Error、Waiting Input、capability-disabled。 |
| **Entry Behaviour** | Schwarz 立即反馈召唤；Capsule 从 anchor enter；可交互后新对话聚焦输入，恢复任务则恢复最有意义焦点。 |
| **Exit Behaviour** | Escape/允许 outside click 收拢到 Character only；Submit 不关闭；Palette 与 Capsule 不并排。 |
| **Expansion / Collapse** | 内容、上下文或控制超过 compact capacity 时 `shape.full → shape.xl` morph 到 Expanded；收回保留 draft/task。 |
| **Keyboard Behaviour** | Enter：composition 结束且请求有效时 Submit；Shift+Enter：换行；Escape：收拢并保留 draft/task；打开时 focus input，恢复结果时 focus current content。 |
| **Outside Click** | Empty：dismiss；有 draft：绝不丢弃，只移除 focus 还是同时收拢存在 `02/03` 冲突，`TBD — requires upstream alignment`。 |
| **Relationship with Schwarz** | Schwarz 始终可见并表达 A；Capsule 是角色的临时语言延伸。 |
| **Relationship with Agent State** | Listening、Thinking、短 Acting、Waiting Input、Success、Error、Cancelled；Waiting Confirmation 使用独立 focused Surface。 |
| **Motion Contract** | Enter 从 anchor；typing 只做 micro response；Thinking 非 spinner-only；Expand 使用单一 container morph。 |
| **Accessibility Notes** | “Ask ArkClaw” 是持续语义 label，不只做消失 placeholder；focus 完整可见；icon-only controls 有名称；状态非颜色唯一；Reduced Motion 使用 fade/static cues。 |
| **Forbidden Behaviours** | 浏览器地址栏、Spotlight/Windows Search/ChatGPT desktop clone、giant rectangle、按钮堆积、未确认能力的死按钮、因长回答直接打开 Workspace。 |

### 4.1 Recommended low-fidelity structure

Empty / resting:

```text
                         anchored to Schwarz
                                  ↓
╭────────────────────────────────────────────╮
│ Ask ArkClaw…                    [Mic*] [↑] │
╰────────────────────────────────────────────╯
  * Voice is Planned; do not ship as a dead control
```

Focused / typing:

```text
╭────────────────────────────────────────────╮
│ Ask ArkClaw                                │
│ Review the files I selected…               │
│                                            │
│ [＋ Context*]       [Mic*] [Expand] [Send] │
╰────────────────────────────────────────────╯
```

The label remains semantically present when user text replaces the empty prompt. Planned slots define future composition; unavailable capability is hidden or clearly explained, never silently disabled.

### 4.2 Size and growth behaviour

- Initial state fits one clear request line plus essential actions; exact width/height `TBD`.
- Input grows from one line to a small multiline area without changing anchor.
- Compact vertical growth is capped at approximately 3–4 readable lines as a product rule, not a fixed geometry.
- Beyond compact growth, input may scroll locally only while editing; response content should expand the Surface instead of turning Capsule into a mini window.
- Multi-turn context, long/rich answer, multiple results, persistent Activity or safe Confirmation context triggers/permits Expanded according to `G2`.
- Screen-edge adaptation may reduce width or change direction, but must not overlap Schwarz or shrink text below `04` type roles.

### 4.3 Interaction-state details

| Variant | Visible change | Available action |
|---|---|---|
| Empty | Quiet input identity; Send unavailable | Type, Planned context/voice if available, dismiss |
| Focused | Visible focus containment; auxiliary row may reveal | Type, attach/voice, dismiss |
| Typing | Draft and multiline growth; Send available | Submit, edit, expand |
| Submitted | Request preserved; duplicate Submit prevented | Cancel only after valid backend signal; continue draft if policy allows |
| Thinking | Request + subtle activity + Thinking label | Cancel intent, continue typing, expand |
| Acting | Short user-relevant action label; complex activity moves to S3/S2 | Valid Cancel/Inspect, collapse |
| Error | Concise inline summary + real recovery | Retry/modify/details if available |
| Disabled capability | Only affected capability unavailable with reason | Alternative path; entire Capsule disabled only if Agent unavailable fact exists |

## 5. Expanded Conversation Surface

| Field | Specification |
|---|---|
| **Purpose** | 承载需要同时看见上下文的多轮对话、较长回答、rich result、持续 Activity 或多个关联组件，而不进入 Workspace。 |
| **Trigger** | 用户 Expand；或 `G2 Expanded warranted` 在 Capsule 无法安全/清晰承载时成立。 |
| **Preconditions** | 同一 task/conversation identity 存在；Capsule 内容/控制确实不足；无第二主 Presentation。 |
| **Anchor** | 从 Capsule 原 anchor 连续扩展；可降低与 Schwarz 的物理贴近以获得阅读面积，但不跳到无关中心。 |
| **Visual Priority** | Active primary Presentation，高于 Capsule；低于 Confirmation/Critical Error。 |
| **Visible Elements** | 当前相关对话、current Agent content、嵌入 Activity/Result/Error、必要 context chips、persistent input area、Collapse；只有需要时显示 task label。 |
| **Hidden Elements** | 永久 title bar、Sidebar、完整 chat-history navigator、global toolbar、model/tool controls、每条消息卡片化。 |
| **Primary Action** | 阅读/继续当前 Conversation。 |
| **Secondary Actions** | Submit follow-up、Collapse、Open Workspace（仅 `G3`）、Cancel/Retry/Details（真实可用时）。 |
| **State Variants** | Multi-turn、long answer、rich result、embedded Activity、Waiting、Confirmation context behind Overlay、inline Error。 |
| **Entry Behaviour** | Capsule 外壳 resize/morph；相关内容 reflow；输入、draft、task 和 reading context 保持。 |
| **Exit Behaviour** | Collapse 回 Capsule；direct Return to desktop 收拢但保留 task；Workspace open 继续同一容器语义。 |
| **Expansion / Collapse** | 可双向 Capsule ↔ Expanded；仅 `G3` 允许 Expanded → Workspace。 |
| **Keyboard Behaviour** | Enter/Shift+Enter 同 Capsule；Escape 一次回 Capsule；focus 保持在触发展开的内容/输入；Overlay 打开时让出焦点。 |
| **Outside Click** | 不关闭。 |
| **Relationship with Schwarz** | Schwarz 保持可见、表达 A；空间距离可增加，但 enter path 和 task identity 保持关系。 |
| **Relationship with Agent State** | 可承载 Listening、Thinking、Acting、三类 Waiting、Success、Error、Cancelled；Confirmation/Critical Error 是上层 Overlay。 |
| **Motion Contract** | 单一 container morph 为主；内部内容分层 reveal，不逐卡片 stagger；Reduced Motion 直接稳定 resize/fade。 |
| **Accessibility Notes** | 阅读顺序与视觉顺序一致；新 Activity/Result 不无条件夺焦；长内容有可读 measure；错误在问题附近；focused element 不被输入区/Overlay 遮挡。 |
| **Forbidden Behaviours** | 变成传统 Chat App、突然新开窗口、回复全部卡片化、固定历史 Sidebar、回答稍长即 Workspace、隐藏当前 Waiting/Error。 |

### 5.1 Low-fidelity structure

```text
╭────────────────────────────────────────────────╮
│ Current task / context only when needed   [–] │
│                                                │
│ Previous relevant response                     │
│                                                │
│ Current Agent content                          │
│ [embedded Activity / Result / Error if active] │
│                                                │
│ ────────────────────────────────────────────── │
│ Ask ArkClaw                                    │
│ [Context]                              [Send]  │
╰────────────────────────────────────────────────╯
                     spatial lineage → Schwarz
```

Conversation remains a continuous task surface, not a permanent transcript browser. Multiple generated components may appear only when they are related and each has distinct semantic value.

---

## 6. Agent Activity Surface

| Field | Specification |
|---|---|
| **Purpose** | 区分 Thinking 与真实 Acting，说明用户相关活动、阶段、可取消性和转向 Result 的过程。 |
| **Trigger** | 当前 task 收到有效 `backend_thinking` 或 `backend_acting` projection fact。 |
| **Preconditions** | Stable task correlation；Acting 必须有 user-facing action label；Progress 必须有用户价值。 |
| **Anchor** | Conversation 可见时嵌入当前请求/任务附近；Character only 时在 Schwarz 邻近出现最小 floating Activity。 |
| **Visual Priority** | 嵌入时服从主 Presentation；standalone 时高于 Palette/Ambient，但低于 Confirmation/Critical Error。 |
| **Visible Elements** | Task title、Thinking/Acting label、semantic progress（如适用）、optional Cancel、Details disclosure（Planned/TBD）、Result transition target。 |
| **Hidden Elements** | raw tool name、MCP/API、arguments、logs、threads、tokens、retries、无用户价值的内部步骤、伪百分比。 |
| **Primary Action** | 理解当前 Agent 正在做什么；有真实 cancellability 时 Cancel。 |
| **Secondary Actions** | Inspect semantic details、Collapse/Return later；继续编辑 draft。 |
| **State Variants** | Thinking；simple Acting；indeterminate Acting；determinate Acting；multi-step task；cancel-pending acknowledgement。 |
| **Entry Behaviour** | 从当前 request/result 区域形成 activity containment；Character only 时从 Schwarz anchor 轻量进入。 |
| **Exit Behaviour** | backend result fact 到达后 morph 为 Result/Error/Cancelled；UI collapse 不结束 Activity。 |
| **Expansion / Collapse** | 简单 Activity 留在 Capsule；持续/多步骤进入 Expanded；复杂 task 可在 `G3` 后进入 Workspace。 |
| **Keyboard Behaviour** | Focus 不自动从输入移走；Cancel/Details 可键盘到达；Escape 收拢上层 P，不发送 Cancel。 |
| **Outside Click** | Embedded：不适用；pure informational standalone 可收拢，但 Activity 继续并由 Schwarz 表达。 |
| **Relationship with Schwarz** | Thinking 与 Acting 使用不同角色表达；UI 收起后 Schwarz 接管持续 signal。 |
| **Relationship with Agent State** | 只对应 A=Thinking/Acting；Waiting、Success、Error、Cancelled 使用各自 Surface/variant。 |
| **Motion Contract** | Thinking 低振幅非方向性；Acting 稳定方向性；multi-step 只在语义阶段更新；不得 spinner-only 或假进度。 |
| **Accessibility Notes** | 状态文字与 icon 并存；progress 可被辅助技术理解；动态更新不反复夺焦；Reduced Motion 用静态 activity form；Cancel label 清晰。 |
| **Forbidden Behaviours** | 把 tool log 当 progress、每一步弹 toast、Thinking 显示为已执行、不可取消仍显示 Cancel、无限 spinner、完成后停在 Working。 |

### 6.1 Activity structures

Thinking:

```text
╭────────────────────────────────────────╮
│ Thinking                               │
│ Reviewing your request                 │
│                              [Cancel]  │
╰────────────────────────────────────────╯
```

Simple Acting:

```text
╭────────────────────────────────────────╮
│ Opening VS Code…                       │
│                    [Cancel if valid]   │
╰────────────────────────────────────────╯
```

Multi-step:

```text
╭────────────────────────────────────────╮
│ Project review                         │
│ ✓ Reading repository                   │
│ ● Reviewing architecture               │
│ ○ Preparing report                     │
│                  [Details*] [Cancel*]  │
╰────────────────────────────────────────╯
  * only when genuinely available
```

Completed steps, current step and pending steps use icon + label + containment; color is supplementary. The step list contains user-meaningful phases, not backend scheduling.

---

## 7. Confirmation Surface

| Field | Specification |
|---|---|
| **Purpose** | 在明显副作用、超出表达范围或需要选择时取得明确、知情的用户决定。 |
| **Trigger** | 当前 task 收到有效 `backend_waiting_confirmation`，包含 scope、effect 和 validity。 |
| **Preconditions** | `G4 Confirmation required`；关联 Base context 可恢复；不存在更高优先 Critical Error。 |
| **Anchor** | 从发起行动的 Conversation/Activity 区域提升；Character only 时恢复最小必要 context 后显示，不从系统中心无来源弹出。 |
| **Visual Priority** | `surface.focused` / `elevation.3`；高于主 Presentation、Activity、Palette、Ambient；低于 invalidating Critical Error。 |
| **Visible Elements** | Action summary、affected target/scope、consequence、Confirm、Cancel/Not now；optional Details 仅在有助于决定时出现。 |
| **Hidden Elements** | raw permission/tool/API wording、默认勾选、倒计时式施压、无关 Conversation controls、Palette。 |
| **Primary Action** | 作出明确决定；当行动本身 destructive 时，destructive action 是语义主动作，但不自动获得焦点。 |
| **Secondary Actions** | Cancel/Not now、Details、显式 Collapse（若允许稍后处理）。 |
| **State Variants** | Standard side-effect；destructive；scope choice；expired/invalidated（转 Error/Result，不继续确认）。 |
| **Entry Behaviour** | Base context 保留可读；focused containment 稳定进入；focus 到标题/安全控制，不默认触发 Confirm。 |
| **Exit Behaviour** | Confirm/Cancel 提交 decision intent并防重复；等待新 backend fact；critical invalidation 转 Error。 |
| **Expansion / Collapse** | Details 可 progressive disclose；可收拢为 Schwarz Waiting signal，但不能丢失决定。 |
| **Keyboard Behaviour** | Escape 默认等同 Cancel/Not now；例外 `TBD`。Enter 仅在 Confirm 被用户显式 focus 时确认；Tab 留在有效决定控件；关闭后恢复来源 focus。 |
| **Outside Click** | 不关闭、不确认、不取消。 |
| **Relationship with Schwarz** | Schwarz 表达 Waiting，不继续 Acting motion。 |
| **Relationship with Agent State** | 必须与 A=Waiting Confirmation 同时有效；Confirm 不让 UI 本地进入 Acting。 |
| **Motion Contract** | Activity motion 停止/降级；Confirmation 稳定提升，不弹跳、不 shake；Reduced Motion 直接建立 focused containment。 |
| **Accessibility Notes** | Summary/consequence/controls 读序明确；destructive 不只靠红色；focus 完整可见；按钮用明确动词；Details 不遮挡主决定。 |
| **Forbidden Behaviours** | MessageBox 复制、outside click approval、timeout approval、Enter 默认误触 destructive、只写“Allow?”、角色动画替代 consequence、Confirm 后立即伪装 Acting。 |

### 7.1 Low-fidelity structure

```text
╭────────────────────────────────────────────╮
│ Delete 3 files?                            │
│ These files will be removed from the       │
│ selected project.                          │
│                                            │
│ [Details]              [Cancel] [Delete]   │
╰────────────────────────────────────────────╯
        Base conversation remains readable
```

“Delete” is preferred over a generic “Confirm”. If deletion permanence/recoverability is not known from the integration contract, the copy must not claim it.

---

## 8. Result Surface

| Field | Specification |
|---|---|
| **Purpose** | 说明实际完成内容、未完成部分、产生的对象和最相关下一步，而不是只显示 “Done”。 |
| **Trigger** | 有效 `backend_succeeded`、partial result 或 `backend_cancelled` fact。 |
| **Preconditions** | Current task correlation；结果内容可面向用户表达；终态不与 Error/Acting 同时属于同一 task。 |
| **Anchor** | Conversation/Workspace 可见时替换对应 Activity；Character only 时使用 Ambient/temporary Result。 |
| **Visual Priority** | 普通 Result 嵌入主 Surface；important rich result 可用 focused containment；低于 Confirmation/Critical Error。 |
| **Visible Elements** | Result summary、必要对象/路径/artifact、partial breakdown、最多一项主要 follow-up 与少量真实 secondary actions。 |
| **Hidden Elements** | 仅 “Done”、庆典动画、无关推荐按钮、raw execution summary、每个结果都大卡。 |
| **Primary Action** | 理解结果；若有自然下一步，Open/Show/Continue 中选择唯一主要动作。 |
| **Secondary Actions** | Collapse、copy/share（能力确认后）、Retry incomplete part、Details（有价值时）。 |
| **State Variants** | Simple Success、Rich Result、Partial Success、Cancelled、result with artifact、result awaiting review。 |
| **Entry Behaviour** | Activity container morph/settle 为 Result；内容先可读，完成 motion 只做辅助。 |
| **Exit Behaviour** | Simple Success 可在可读后降级/收拢；Rich/Partial 在用户理解前保留；Conversation 开着时不强制关闭。 |
| **Expansion / Collapse** | Short result 留 Capsule；rich/partial 展开 Expanded；multiple persistent artifacts 可进入 Workspace（`G3`）。 |
| **Keyboard Behaviour** | Focus 通常不自动移到 Result；若 Result 是阻断提交的直接回应，可把 focus 移到 summary。Escape 按 P 层级收拢。 |
| **Outside Click** | Embedded：不适用；temporary simple result 可 dismiss，不删除结果或 task context。 |
| **Relationship with Schwarz** | Schwarz 短暂 Success/neutral Cancelled 后降低强度；未读 rich/partial 保留可恢复 signal。 |
| **Relationship with Agent State** | A=Success（含 Partial）或 Cancelled；新请求前不混用 Acting/Error 视觉。 |
| **Motion Contract** | 单次 settle/completion；无彩带、全屏颜色或重复 bounce；Partial 不使用完整 Success 庆典。 |
| **Accessibility Notes** | Icon + summary；Partial 用结构区分已完成/未完成；动态更新不抢焦；路径可完整访问；Reduced Motion 立即显示结果。 |
| **Forbidden Behaviours** | 只显示 Done、Partial 当 Success、按钮墙、自动消失重要 artifact、用绿色替代说明、结果到达时强抢前景。 |

### 8.1 Result structures

Simple Success:

```text
╭──────────────────────────────────────╮
│ ✓ VS Code opened                    │
╰──────────────────────────────────────╯
```

Rich / Partial:

```text
╭────────────────────────────────────────────╮
│ Project review complete                    │
│                                            │
│ ✓ 2 checks completed                       │
│ ! 1 check could not run                    │
│ Report: project-review.md                  │
│                                            │
│                  [Show report] [Details]   │
╰────────────────────────────────────────────╯
```

---

## 9. Error Surface

| Field | Specification |
|---|---|
| **Purpose** | 以用户能理解的方式说明目标未完成、实际影响和真实恢复路径。 |
| **Trigger** | 有效 `backend_failed` fact；critical variant 仅在错误使行动/确认失效且需立即理解时。 |
| **Preconditions** | Current task correlation；用户相关失败；Retry/alternative availability 来自 integration signal。 |
| **Anchor** | 普通 Error 嵌入发生问题的 request/action/result 附近；Critical Error 替代失效 Confirmation 并取得前景。 |
| **Visual Priority** | Inline recoverable Error 服从主 P；Critical Error 是最高 foreground Overlay。 |
| **Visible Elements** | Concise summary、what was not completed、actual impact、Retry/alternative/modify request、optional Details。 |
| **Hidden Elements** | Raw exception、stack trace、error code wall、system MessageBox chrome、无效 Retry、持续告警。 |
| **Primary Action** | 采用真实可用的恢复路径；无恢复时理解并结束/修改任务。 |
| **Secondary Actions** | Details、Collapse、Return later、copy diagnostic（未来/Planned）。 |
| **State Variants** | Recoverable；User Action Required；Technical Failure summary；Critical invalidation；capability unavailable。 |
| **Entry Behaviour** | 失败的 Activity 停止并 morph 为 Error；Critical Error 取代原 Confirmation，不叠加第二 modal。 |
| **Exit Behaviour** | Retry/modify 提交 intent，等待 backend fact；Dismiss 只隐藏前景，不宣称 resolved/Idle。 |
| **Expansion / Collapse** | Details progressive disclosure；复杂诊断可在 Expanded/Workspace 查看，但 technical detail 默认隐藏。 |
| **Keyboard Behaviour** | Focus Error summary only when needed to prevent silent failure or failed form flow；Retry/alternative/Details 可达；Escape 先关 Details，再收拢 Error，不标记解决。 |
| **Outside Click** | Inline 不适用；Critical Error 不关闭；非阻断 temporary summary 可收拢并保留 signal。 |
| **Relationship with Schwarz** | Schwarz 表达 Error，但不持续 shake/alarm；Surface 收起后保留恢复入口。 |
| **Relationship with Agent State** | A=Error；Retry 不让 UI 本地进入 Thinking，必须等待新 backend fact。 |
| **Motion Contract** | 一次清晰注意变化后静止；不闪烁、不循环 shake；Reduced Motion 使用 outline/icon/text。 |
| **Accessibility Notes** | Summary 在问题附近并可被辅助技术获知；不只红框；恢复动词明确；focus 不被 Overlay 遮挡；Details 保持读序。 |
| **Forbidden Behaviours** | 技术异常框、错误 toast 后消失、只有红色、虚假 Retry、Dismiss=resolved、Error 与 Activity 同时宣称同一动作仍在进行。 |

### 9.1 Error structures

Recoverable:

```text
╭────────────────────────────────────────────╮
│ Couldn’t open VS Code                      │
│ The application was not found.             │
│                                            │
│                 [Choose another app] [Retry]│
╰────────────────────────────────────────────╯
```

User action required:

```text
╭────────────────────────────────────────────╮
│ I need a project folder to continue.       │
│                                            │
│                         [Choose folder]     │
╰────────────────────────────────────────────╯
```

Technical details, if later supported, live behind `Details` and never replace the user-facing summary.

## 10. Anchored Action Palette

| Field | Specification |
|---|---|
| **Purpose** | 通过少量、高确定性、上下文相关动作补充 Conversation First，并逐步取代传统右键菜单。 |
| **Trigger** | Schwarz 有效 hit region 上的 Right Click；或未来等价可访问入口。 |
| **Preconditions** | `G7 Palette allowed`；非 Drag；无 Confirmation/Critical Error；替换旧菜单前能力对等已确认。 |
| **Anchor** | 锚定本次右键对应的 Schwarz context；优先侧上方/上方，按可用工作区翻转。 |
| **Visual Priority** | `surface.floating` / `shape.l` / `elevation.2`；低于主 P、Activity control、Confirmation/Error；高于 Ambient。 |
| **Visible Elements** | Ask ArkClaw；Current Task（仅有任务时）；Character group；ArkClaw group：Settings、Hide Schwarz、Quit。 |
| **Hidden Elements** | 空分组、工具目录、MCP/plugins、app launcher grid、全局历史、模型设置、不可用 task action。 |
| **Primary Action** | 选择当前明确意图：Ask/Return to task/Character/Settings 等。 |
| **Secondary Actions** | Escape/outside click dismiss；Character group drill-in；Current Task 中真实可用的 Continue/Cancel。 |
| **State Variants** | Idle palette；active-task palette；task-waiting palette；Character group selected；destructive Quit placement。 |
| **Entry Behaviour** | 从 Schwarz anchor 短 enter；记录 return target；轻量 Conversation 暂时收拢，Workspace 可保留。 |
| **Exit Behaviour** | 选择、outside click、Escape、再次 Right Click、Drag start 时 dismiss；选择 Ask 转换为 Capsule，不并排。 |
| **Expansion / Collapse** | Character group 在同一 Palette 内替换内容；不级联多个窗口。Current Task 不形成深层导航。 |
| **Keyboard Behaviour** | 打开后 focus 首个可用项；Arrow/Tab 顺序符合视觉顺序；Enter/Space 激活 focus 项；Escape 从 Character group 返回 root，再次 Escape 关闭。 |
| **Outside Click** | 关闭 Palette；同一次 click 不透传为 Schwarz Interact/Invocation。 |
| **Relationship with Schwarz** | Palette 属于 Schwarz，但打开不改变角色 A projection 或暂停动画。 |
| **Relationship with Agent State** | A 不变；Current Task 内容由当前 projection/cancellability 决定；阻断 Waiting/Error 时不允许 Palette 抢占。 |
| **Motion Contract** | Root enter/exit 轻量；root ↔ Character group 使用短 content morph/translate，外壳保持；无 card stagger。 |
| **Accessibility Notes** | grouped list 有清楚名称；icon 不代替 label；focus 完整可见；destructive Quit 可辨；不依赖 Hover。 |
| **Forbidden Behaviours** | legacy menu 换皮、巨大 launcher、command palette clone、每项大 tile、复杂二级导航、图标网格、Palette/Capsule 同时围绕 Schwarz。 |

### 10.1 Final information architecture

采用 **compact grouped list**，而不是 expressive tile 或 compact grid。原因：动作以文字语义为主，数量少且类别不同；列表在中英文本、键盘和可访问性上更稳定，也不会产生 mobile app menu 或 launcher 感。

```text
╭──────────────────────────────────╮
│ Ask ArkClaw                      │
│                                  │
│ CURRENT TASK            (if any) │
│ Return to task                    │
│ Cancel task              (if valid)│
│                                  │
│ CHARACTER                         │
│ Character actions              › │
│                                  │
│ ARKCLAW                           │
│ Settings                          │
│ Hide Schwarz                      │
│ Quit                              │
╰──────────────────────────────────╯
```

不设置泛化的顶层 “Actions” 库。Agent Actions 只在 Current Task 中显示当前真实动作；Character Actions 与 Agent task controls 必须分组。

---

## 11. Character Action Palette

| Field | Specification |
|---|---|
| **Purpose** | 在不与 Agent Actions 混淆的情况下直接选择 Schwarz 的角色动作。 |
| **Trigger** | Anchored Action Palette 中选择 Character actions。 |
| **Preconditions** | Root Palette 有效；Character capability list 可用；无 blocking Overlay。 |
| **Anchor** | 保持 Root Palette 同一外壳和 Schwarz anchor；内容层切换，不打开第二 Palette。 |
| **Visual Priority** | 与 root Palette 相同。 |
| **Visible Elements** | Back、Character heading、可用动作（候选：Relax、Sit、Sleep、Move、Special）；manual action active 时可显示 Resume Autonomous。 |
| **Hidden Elements** | Agent task controls、tool actions、不可用动作、动画调试参数、动作资产名称。 |
| **Primary Action** | 选择一个可用角色动作。 |
| **Secondary Actions** | Back、Resume Autonomous（条件出现）、Dismiss。 |
| **State Variants** | No manual action；manual action active；action unavailable；selection acknowledged；action failure Result。 |
| **Entry Behaviour** | Root content 短 morph/translate 为 Character group；外壳与 anchor 不变。 |
| **Exit Behaviour** | 选择动作后立即 dismiss；Back 回 root；outside click/Escape dismiss 或分层返回。 |
| **Expansion / Collapse** | 不再进入第三级；动作数量超出 compact capacity 时需重新分组/范围评审，不滚成动作库。 |
| **Keyboard Behaviour** | Focus 从 Character group heading/首项开始；Enter 选择；Escape 先回 root；focus 状态清楚。 |
| **Outside Click** | 关闭整个 Palette，不执行动作。 |
| **Relationship with Schwarz** | 选择后 Schwarz 执行角色动作；Palette 不抢先播放选择结果。 |
| **Relationship with Agent State** | Character action 不改变 A；A=Thinking/Acting 时是否允许特定动作取决于角色能力，`TBD`，不得遮蔽 Agent state。 |
| **Motion Contract** | Palette content 轻量切换；选中后 Surface 收拢，再由 Schwarz 的实际动作提供反馈。 |
| **Accessibility Notes** | Active/manual state 使用 check/icon + text，不只颜色；动作名称可读；提供非 Drag/非 Hover 入口。 |
| **Forbidden Behaviours** | 把角色动作显示为 Agent tool、点击后 Palette 悬挂、虚假 active state、动画预览墙、深层子菜单、Move 与 Drag 语义混淆。 |

### 11.1 Active state and autonomy

- 只有当角色系统能够可靠报告当前 manual action 时，才显示 active check/state。
- `Resume Autonomous` 仅在角色处于明确 manual action mode 时出现；没有该状态就不显示空入口。
- Selecting action 后 Palette 自动关闭；失败使用最小 Result/Error，不重新挂住菜单。
- Relax/Sit/Sleep/Move/Special 的最终集合、availability、命名和与 Agent projection 的并行规则为 `TBD`。

```text
╭──────────────────────────────────╮
│ ‹ Character                      │
│                                  │
│ Relax                            │
│ Sit                          ✓   │
│ Sleep                            │
│ Move                             │
│ Special                          │
│                                  │
│ Resume Autonomous   (conditional)│
╰──────────────────────────────────╯
```

---

## 12. Passive / Ambient Notification Surface

| Field | Specification |
|---|---|
| **Purpose** | 在用户没有打开主 Surface 时，以比系统 toast 更角色中心、更低打扰的方式提示值得查看的后台变化。 |
| **Trigger** | Background task Success、non-urgent Waiting Input/External、recoverable Error 或阶段 Result，通过 `G9` 后为 non-interruptive。 |
| **Preconditions** | P=Character only；无高优先 Surface；事件与可恢复 task 关联；不属于 Silent category。 |
| **Anchor** | Schwarz 邻近，但不遮挡角色；具体 bubble/badge-like form 为 `TBD`。 |
| **Visual Priority** | `surface.ambient` / `elevation.1`；低于所有交互 Surface。 |
| **Visible Elements** | 一句结果/等待摘要、semantic icon、可点击恢复区域；必要时 Dismiss。 |
| **Hidden Elements** | 多条通知堆栈、永久 count badge、完整结果、按钮组、工具过程、系统 toast chrome。 |
| **Primary Action** | 打开所属 Conversation/Workspace。 |
| **Secondary Actions** | Dismiss；在非紧急情况下忽略并稍后从 Schwarz 恢复。 |
| **State Variants** | Success、Waiting Input、Waiting External、recoverable Error、result available。 |
| **Entry Behaviour** | 与 Schwarz 状态同步轻量出现；不抢走其他应用键盘焦点。 |
| **Exit Behaviour** | 用户打开、dismiss、可读反馈完成或被更高 Surface 合并/替代；结果本身不被删除。 |
| **Expansion / Collapse** | 点击后恢复所属 P；Surface 本身不展开为第二层通知。 |
| **Keyboard Behaviour** | 不主动抢焦；若通过可访问入口导航到该 signal，可 Enter 打开、Escape dismiss。 |
| **Outside Click** | 可 dismiss；不得把同一 click 透传为 Character action。 |
| **Relationship with Schwarz** | Schwarz 是主 signal，Ambient Surface 只提供必要文字；没有永久光圈或 badge rail。 |
| **Relationship with Agent State** | 映射实际 Success/Waiting/Error 等 A；通知关闭不改变 A。 |
| **Motion Contract** | `motion.duration.short` 的低位移/fade；Success 单次 settle；Waiting 不循环弹跳；Reduced Motion 静态出现。 |
| **Accessibility Notes** | 不只靠角色动画/颜色；摘要可被读出但避免重复播报；不抢焦；用户可暂停/关闭持续内容。 |
| **Forbidden Behaviours** | 每次内部步骤通知、传统 Windows toast 默认化、永久 badge、通知堆叠、抢焦、自动打开 Workspace、关闭通知等于取消任务。 |

### 12.1 Duration policy

- Simple non-critical Success：在达到可读时长后可淡出，exact duration `TBD`。
- Waiting Input：可以降低为 Schwarz signal，但不能在用户尚未看到时永久消失。
- Recoverable Error：可淡出 Surface，必须保留恢复入口。
- Partial/Rich Result：不依靠短通知承载；点击/恢复到 Expanded/Workspace。
- Safety、时限或立即行动需求不属于 Passive；按 `03` 的 interruptive rule 进入 Confirmation/Critical Error。

### 12.2 When not to notify

内部工具选择、快速成功中间步骤、已自行恢复且不影响结果的 retry、无用户后果的 phase change、当前主 Surface 已显示同一结果时均保持 Silent/merge。

---

## 13. Agent Workspace

| Field | Specification |
|---|---|
| **Purpose** | 让用户理解和控制复杂、持续、多对象任务，保留 Conversation、semantic progress、context、artifacts 与结果。 |
| **Trigger** | 用户明确 Open Workspace；或 complex request 已提供扩展同意且 `G3 Workspace justified`。 |
| **Preconditions** | Expanded 已不足；存在多步骤/多文件/persistent artifact/long-running/complex activity 等真实结构；同一 task identity 可连续恢复。 |
| **Anchor** | 从 Expanded 容器连续扩展；可脱离紧密邻近以获得可用面积，但通过 motion、task identity 和 Schwarz state 保持来源。 |
| **Visual Priority** | 最高主 Presentation；低于 Confirmation/Critical Error。 |
| **Visible Elements** | 当前 goal/scope；Conversation；当前 Task/Activity（active 时）；Context（需要时）；Artifacts（产生时）；相关 Actions/Recovery；Collapse/Return。 |
| **Hidden Elements** | 永久 global Sidebar、工具目录、IDE tree/dock、developer console、metric dashboard、与任务无关 Settings、所有逻辑区域同时空载显示。 |
| **Primary Action** | 理解/推进当前复杂任务。 |
| **Secondary Actions** | Conversation follow-up、artifact open/show、semantic Details、valid Cancel/Retry/Continue、Collapse/Return to desktop。 |
| **State Variants** | Active task；Waiting decision/input/external；artifact review；rich/partial Result；Error recovery；task complete。 |
| **Entry Behaviour** | Expanded shell 使用 `motion.duration.long` 的 controlled morph；保留 task、draft、focus/reading context；不从 Character only 突然弹出。 |
| **Exit Behaviour** | Collapse → Expanded；direct Return → Character only；task/artifacts 保留；close 不发送 Cancel。 |
| **Expansion / Collapse** | 逻辑区域按需显现/收拢；Workspace 不再扩展为更大产品层级。 |
| **Keyboard Behaviour** | Focus 顺序遵循当前可见逻辑区域；Escape 先关局部 Overlay/Details，再 Workspace → Expanded；Conversation Enter/Shift+Enter 保持；焦点不被固定区域遮挡。 |
| **Outside Click** | 不关闭。 |
| **Relationship with Schwarz** | Schwarz 仍是 identity/state anchor，可独立 Drag；Workspace 不跟随角色移动。 |
| **Relationship with Agent State** | 可承载所有 A projection；Confirmation/Critical Error 仍用高优先 O；Workspace visibility 不决定 A。 |
| **Motion Contract** | 一个主 shell transition；logical region 只在有内容时 reveal；Activity → Result 原位 morph；Reduced Motion 直接布局稳定态。 |
| **Accessibility Notes** | 区域有语义 heading 和逻辑读序；动态新增 artifact 不夺焦；长文 measure 可读；所有 drag-like organization 有按钮/键盘替代；状态非颜色唯一。 |
| **Forbidden Behaviours** | 默认主界面、Sidebar+Chat+Toolbar+Inspector、Dashboard card wall、所有区域永久显示、简单回答触发、角色变装饰、raw logs、关闭即丢 task。 |

### 13.1 Logical regions

这些是按需出现的语义区域，不是固定列：

| Region | Appears when | Disappears/collapses when |
|---|---|---|
| Goal / Scope | 复杂任务需要持续参照 | 任务结束后可压缩为 Result summary |
| Conversation | 始终是意图与澄清通道 | 不消失，但可降低为 compact follow-up area |
| Current Task / Activity | A=Thinking/Acting/Waiting | 转 Result/Error 后原位替换或收起 |
| Context | 已附加/选择对象或需要范围理解 | 不再影响任务时收拢；不丢失必要 provenance |
| Artifacts | 文件、报告或可持续结果产生 | 用户收起或离开 Workspace；task context 中保留 |
| Actions / Recovery | 当前状态存在真实动作 | 状态变化后立即更新，不保留 stale controls |

### 13.2 Low-fidelity philosophy

```text
╭────────────────────────────────────────────────────╮
│ Current goal / scope                 [Collapse] [×]│
│                                                    │
│ Conversation and current decision                  │
│                                                    │
│ ┌ Current task / semantic activity ─────────────┐ │
│ │ appears only while relevant                   │ │
│ └───────────────────────────────────────────────┘ │
│                                                    │
│ Artifacts / context appear when produced or needed │
│                                                    │
│ ────────────────────────────────────────────────── │
│ Follow up with ArkClaw                       [Send]│
╰────────────────────────────────────────────────────╯
                  continuity → Schwarz
```

Forbidden default:

```text
┌──────────┬─────────────────────┬──────────────┐
│ Nav tree │ Permanent chat      │ Tool panels  │
│          │                     │ / inspector  │
└──────────┴─────────────────────┴──────────────┘
```

Final layout, region placement, resize model and artifact arrangement remain `TBD`.

## 14. Geometry Principles

本节定义预期体验，不规定 Qt geometry、坐标或固定像素。

### 14.1 Schwarz anchoring

1. Capsule、Palette、Ambient 和 Character-only standalone Activity 优先位于 Schwarz 上方或侧上方。
2. 默认 anchor gap 使用 `spacing.3`；避免遮挡需要更清晰分离时使用 `spacing.4`。
3. Surface 边缘不能侵入角色主要身体轮廓、既有 pixel hit region 或 Drag 起始区域。
4. Anchor 可在左/右侧翻转，但 enter origin、shape direction 或空间路径必须保持可追溯。
5. 不使用永久连线、气泡尾巴、光束或状态环证明关联；关系主要由距离、motion 和 task continuity 建立。

### 14.2 Screen-edge adaptation

| Constraint | Expected behaviour |
|---|---|
| Schwarz near left edge | Surface 优先向右上/右侧展开；不裁切 leading controls |
| Schwarz near right edge | Surface 向左上/左侧翻转；保持 control order，不镜像语义 |
| Schwarz near top edge | Surface 侧向或向下展开，但避开角色主体 |
| Schwarz near taskbar/bottom | Surface 向上展开并保持与任务栏可操作区分离 |
| Limited vertical space | Capsule 限制 compact growth并更早进入 Expanded；不缩小文字 |
| Limited horizontal space | 调整 width、换行或重新排列次要 actions；不隐藏 Primary/Cancel |
| Multiple monitors | Surface 保持在 Schwarz 所在显示器可用工作区；跨显示器/移动时恢复规则 `TBD` |
| Different DPI | 保持 token relationship、text readability 和 control clarity，不按物理像素复制 |

### 14.3 Workspace geometry

Workspace 可以使用更稳定的可用工作区并降低紧密 anchor，但必须：

- 从 Expanded 连续进入；
- 保持 Schwarz 可见或有明确 return identity；
- 不覆盖任务栏/系统保留区；
- 保持一个主要阅读焦点；
- 在 Schwarz Drag 时维持原位，不跟随跳动；
- 不因大屏自动显示更多永久 panels。

Exact dimensions、minimum/maximum size、monitor migration、snap 与 resize behaviour 为 `TBD`。

---

## 15. Surface Layering

优先级表示谁拥有前景注意与输入，不要求每一层都形成独立窗口。

```text
Highest
1. Critical Error / invalidating safety interruption
2. Required Confirmation or blocking required input
3. Active primary Presentation: Workspace > Expanded > Capsule
4. Active Action control: embedded in P; standalone only when P is hidden
5. Anchored Action Palette / Character Action Palette
6. Passive Result / Ambient Notification
7. Schwarz / Character
Lowest
```

### 15.1 Coverage and pre-emption

| Incoming Surface | Existing lower Surface | Rule |
|---|---|---|
| Critical Error | Confirmation | Replace invalid Confirmation; do not stack; preserve explanation of invalidation |
| Confirmation | Palette | Dismiss Palette and restore Base context; Confirmation takes focus |
| Confirmation | Conversation/Workspace | Keep Base readable; disable competing ordinary Submit; one focused containment |
| Workspace | Expanded/Capsule | Morph same P; lower P ceases to exist as separate Surface |
| Expanded | Capsule | Morph same P; no overlap window |
| Activity | Visible P | Embed at related request/task location |
| Standalone Activity | Palette | Activity control wins; Palette dismisses if it would hide control |
| Palette | Capsule | Capsule temporarily dismisses/transforms; never side-by-side |
| Ambient | Any foreground P/O | Merge into current context or remain silent; no extra floating Surface |

### 15.2 Allowed coexistence

| Combination | Rule |
|---|---|
| Conversation + embedded Activity/Result/Error | **Allowed**：one primary container, contextual component |
| Workspace + Character Palette | **Conditional**：Workspace stays; Palette temporary; no blocking Overlay/current-control conflict |
| Confirmation + readable Conversation context | **Allowed / focused**：Conversation visible but does not own ordinary input |
| Character only + Ambient/standalone Activity | **Allowed**：one minimal adjacent Surface |
| Palette + Confirmation/Critical Error | **Not Allowed** |
| Capsule + Expanded/Workspace | **Not Allowed** as separate Surfaces |
| Multiple Ambient notifications | **Not Allowed**：aggregate/replace/silence according to task relevance |
| Error + Activity for same task/action | **Not Allowed**：Error replaces failed Activity |

---

## 16. Motion Between Surfaces

Motion 使用 `04` 的 token hierarchy；exact duration/easing/spring 为 `TBD`。

### 16.1 Character → Capsule

```text
Schwarz acknowledges invocation
→ Capsule origin is visible at Schwarz anchor
→ short translate/scale + fade
→ stable focused input
```

- 角色反馈与 Capsule enter 被理解为一次响应。
- Surface 可交互状态不得等待装饰动画完成。
- Reduced Motion：直接显示稳定 Capsule + focus cue。

### 16.2 Capsule → Expanded Conversation

```text
shape.full Capsule shell
→ shell expands in place / flips direction if edge requires
→ content reflows and relevant history reveals
→ shape.xl Expanded shell settles
```

输入、draft、current request 和 focus continuity 保持；禁止 old window closes + new window appears。

### 16.3 Expanded Conversation → Workspace

```text
Expanded task identity remains
→ outer shell uses controlled long morph
→ logical regions appear only when populated
→ Workspace reaches stable material
```

不逐卡片 cascade；不突然加入 Sidebar/Toolbar；Reduced Motion 直接替换为稳定 Workspace 并保留 focus。

### 16.4 Thinking / Acting → Result

```text
Activity region remains in place
→ activity motion stops
→ label/icon/containment morph to actual result
→ single success/error/cancelled settle
```

Result 来自 backend fact；UI 不因 motion 完成自行宣布 Success/Error。

### 16.5 Success → Collapse

```text
Result becomes readable
→ completion emphasis lowers
→ Surface collapses one level or waits for user
→ Character resumes calm state / keeps unread signal
```

Simple success 可自动降低；Rich/Partial/important Result 等用户理解或主动收拢。Exact timing `TBD`。

### 16.6 Action Palette → Character Actions

外壳、anchor 和 elevation 保持；root content 以短 translate/cross-fade 切为 Character group。Back 反向恢复。不得打开 cascade 子窗口或让 Schwarz 先执行预览动作。

---

## 17. Agent State Mapping

本表映射 presentation-level Agent projection；不定义 backend lifecycle。

| Agent projection | Schwarz | Conversation | Activity / focused Surface | User actions |
|---|---|---|---|---|
| Idle | 安静、低频 ambient | 空 Capsule 可输入或收拢 | None | Invoke、type、Palette、Drag、protected Interact |
| Listening | 轻微输入响应 | Focus/draft clearly visible | None | Type、Submit、Dismiss |
| Thinking | 克制思考；非执行姿态 | Current request + concise status | Subtle non-directional activity | Cancel intent、continue type、expand/collapse |
| Acting | 明确执行姿态 | Related Action embedded | Task label + semantic/determinate progress | Cancel if valid、Inspect、collapse、edit draft |
| Waiting Confirmation | Waiting；停止推进感 | Base context readable | Focused Confirmation | Confirm、Cancel/Not now、Details、explicit collapse |
| Waiting Input | Waiting；提示需回应 | Related question/input focus | Prompt or choice, not Confirmation | Provide input、Cancel if valid、return later |
| Waiting External | Ambient Waiting | Waiting summary | Low-motion/none; condition text | Inspect、valid Cancel、collapse |
| Success | 短暂完成后降级 | Result retained if open | Success/Partial Result | Open/Show/Continue/Collapse |
| Error | 可识别、无持续 alarm | Error near failed action | Inline or Critical Error | Retry if real、alternative、Details、Collapse |
| Cancelled | 收束到中性 | Cancellation Result | No Activity | New request、Continue、Collapse |

### 17.1 State integrity rules

- Submit、Confirm、Retry 只显示 intent acknowledged；只有 backend fact 才改变 Thinking/Acting/Success/Error/Cancelled。
- Waiting 三种原因使用不同文案、icon 和 control；不能都显示为 loading。
- Active task 收拢后 Schwarz + recoverable signal 接管状态；不打开永久 status label。
- 同一 task 只显示一个真实 terminal result。

---

## 18. Core Flow Wireframes

Flow 中的 `backend_*` 代表 UI 收到 integration fact，不描述 Agent 内部执行。

### 18.1 Flow A — Start Conversation

```text
[1 Character only]       [2 Capsule]                  [3 Typing]
     Schwarz       →     ╭ Ask ArkClaw… ╮       →     ╭ Ask ArkClaw       ╮
                         ╰───────────────╯             │ Review this… [Send]│
                                                       ╰───────────────────╯

[4 backend_thinking]                                  [5 Response]
╭ Thinking                                  ╮   →     ╭ Here is what I found… ╮
│ Reviewing your request          [Cancel]  │         │                [Continue]│
╰───────────────────────────────────────────╯         ╰──────────────────────────╯
```

Verification：不打开 Workspace；不暴露工具/模型设置；gesture binding 仍 `TBD`；Collapse 保留 context。

### 18.2 Flow B — Launch Application

```text
Capsule: “Open VS Code”
→ submit intent
→ backend_thinking: [Thinking / understanding request]
→ backend_acting:   [Opening VS Code…] [Cancel only if valid]
→ backend_succeeded:[✓ VS Code opened]
→ readable pause
→ Collapse to Schwarz
```

Activity 与 Result 在同一位置转换；普通 app launch 不升级 Workspace。

### 18.3 Flow C — Confirmation

```text
Conversation request
→ backend_waiting_confirmation
→ ╭ Delete 3 files?                 ╮
  │ These files will be removed.    │
  │       [Details] [Cancel] [Delete]│
  ╰─────────────────────────────────╯
→ Confirm intent (A remains Waiting until backend fact)
→ backend_acting: [Deleting selected files…]
→ backend_succeeded / backend_failed
→ Result / Error in original context
```

Outside click 无效果；Escape 默认 Cancel/Not now；Critical invalidation replaces Confirmation。

### 18.4 Flow D — Character Action

```text
Character only
→ Right Click
→ ╭ Ask ArkClaw      ╮
  │ Character      › │
  │ Settings          │
  ╰───────────────────╯
→ ╭ ‹ Character       ╮
  │ Relax             │
  │ Sit               │
  │ Sleep             │
  ╰───────────────────╯
→ select Sit
→ Palette dismiss
→ Schwarz performs actual Sit; A unchanged
```

Right-click replacement remains blocked until existing menu parity/migration is confirmed。

### 18.5 Flow E — Complex Task

```text
Capsule request
→ backend_thinking
→ G2: Capsule shell morphs to Expanded
→ Conversation + embedded semantic Activity
→ G3/user agreement
→ same shell morphs to Workspace
→ Current Task + Context appear when needed
→ Artifacts appear when produced
→ backend result fact
→ Activity region morphs to Result/Partial/Error
→ Workspace → Expanded → Capsule → Character only
```

每次 collapse 只改变 P；task、artifact、draft 与 A projection 不因 UI 收拢而被取消。

---

## 19. Empty, Loading and Failure States

| State | Surface behaviour | User recovery | Forbidden |
|---|---|---|---|
| Empty Conversation | Capsule 显示持续 “Ask ArkClaw” identity 与明确 input affordance；不堆 suggestions | Type、Context/Voice if available、dismiss | 品牌欢迎页、suggestion cards wall |
| No context attached | 不把 Context slot 标为错误；仅在任务确实需要 context 时提示 | Attach/select context（Planned）或继续无 context | 永久 warning chip |
| Submitted / pending acknowledgement | 请求保留，防重复 Submit；不自行显示 Thinking | Wait、edit follow-up according to policy | Spinner 表示 backend 已 thinking |
| Thinking | Subtle activity + clear label + Cancel intent | Cancel、continue typing、expand | Fake percent、tool logs |
| Acting / loading | User-facing action + semantic progress | Valid Cancel/Inspect/Collapse | Infinite generic Working |
| Waiting External | Motion 降级，写明等待对象/条件 | Inspect、valid Cancel、return later | 看似持续推进 |
| No Result | 若 backend 明确完成但无可展示对象，说明完成了什么和没有产生什么 | Continue/modify request | Blank Surface 或 “Done” |
| Failed task | Error near task with actual impact/recovery | Retry/alternative/modify/details | Toast-only、stack trace |
| Agent unavailable / disconnected | 仅在 integration 能提供可靠 unavailable fact 时出现；说明当前不可处理请求 | Retry/reconnect/try later only if real | 自行推断 network/backend cause |
| Capability unavailable | 受影响入口隐藏或显示原因与替代路径；其他功能保持 | Alternative/Settings if relevant | Dead icon button、全 UI disabled |
| Empty Workspace region | Region 不出现；Workspace 不展示占位 panels | Continue task | 空 Context/Artifacts/Activity card |

Connectivity/offline taxonomy、reconnect action、capability discovery 和 availability signals 尚未由上位文档确认，均为 `TBD`；本文只规定有可靠事实时的呈现方式。

## 20. Component Usage Rules

### 20.1 Buttons

| Type | Use in Surfaces | Do not use for |
|---|---|---|
| Primary | Capsule Send；Confirmation 的明确推进/破坏性动作；Result 唯一自然 follow-up | 同一 Surface 多个并列 CTA |
| Secondary | Cancel、alternative、Show/Open、Return | 假装次要但实际 destructive 的动作 |
| Tertiary | Details、Collapse、轻量 context action | 关键 Confirm/Recovery 的唯一表达 |
| Destructive | Delete、Quit 或其他明确高影响动作 | 普通 Cancel、Error 状态装饰 |
| Icon-only | Close、Expand/Collapse、Voice/Attach 等高熟悉度 compact control | 不熟悉的 Agent/Character action、无 accessible name 的动作 |

Rules：

- 每个 decision/action region 原则上只有一个 Primary。
- Cancel 只有在实际语义允许时出现；Collapse 永远不能伪装为 Cancel。
- Submitted/decision-pending 时防止重复触发，但必须给出状态反馈。
- Disabled control 若用户合理期待可用，提供原因；不要发布永久 disabled Planned button。

### 20.2 Chips / pills

适用于 context object、file、task label、compact status 和 lightweight action。每个 chip 表达一个清晰对象/状态；可移除 context 有独立 remove action。

不适用于：全局导航、所有 Agent states、长路径、整句结果、Palette 一级动作或用彩虹色区分类别。

### 20.3 Cards / containers

只有 Result、File、App、Confirmation、Progress 等具有独立语义或操作边界的内容使用容器。普通对话段落、每一次 Agent 回复和 Workspace 每个逻辑区域不自动成为 Card。

### 20.4 Progress

- Indeterminate：没有可靠比例但等待值得显示；必须有 task label。
- Determinate：只有真实、稳定比例才显示值。
- Multi-step：只显示用户可理解的高层阶段。
- 快速简单动作省略 progress，直接 Result。

### 20.5 Inputs and validation

- Capsule/Expanded/Workspace 的 input 使用同一语义 identity 和 Enter contract。
- Placeholder 不取代 label/accessibility name。
- 输入错误在相关 field 附近说明；多项错误在复杂 form 中可以 summary + inline，但本阶段没有定义通用 form page。
- Voice/Context 为 Planned；未确认时不以死控件占据 MVP。

### 20.6 Details disclosure

Details 只在用户需要理解范围、诊断、阶段或恢复时出现。它是同一 Surface 的 progressive disclosure，不打开 developer console，也不暴露 raw tool/MCP/API 默认信息。

---

## 21. Content Density

| Density | Surface | Content rule | Control rule |
|---|---|---|---|
| Compact | Capsule、Palette、Ambient、simple Activity/Result | 一次意图、一个状态或一个短结果；文本优先 | 只保留 Primary 和必要 secondary；`spacing.2–4` |
| Comfortable | Expanded Conversation、Confirmation、rich Result/Error | 同一任务的连续上下文和必要解释 | controls 贴近所属内容；`spacing.4–5` |
| Rich | Workspace、multi-step/artifact review | 多区域按需出现；一个主要焦点 | region controls contextual；`spacing.5–7` |

### 21.1 Density limits

- Compact Surface 不能靠缩小文字、隐藏 label 或堆 icon 承载 Rich content。
- Expanded 不显示全历史与全局导航；只显示理解当前任务所需上下文。
- Workspace 即使空间足够，也不预先显示空 Context、Artifacts、Activity 或 Actions panels。
- 当内容从 Compact 升级到 Comfortable/Rich 时，优先扩展容器，不在同一小 Surface 中加滚动、tabs 或 dense toolbar。
- 每个 Surface 同时最多一个视觉主焦点；semantic states 不形成 badge/status wall。

---

## 22. Copy / Microcopy Rules

ArkClaw 文案应 concise、action-oriented、human-readable、诚实并与当前 projection 一致。

### 22.1 Voice and structure

- 用用户目标和桌面对象命名行动，不使用 runtime jargon。
- 先说明发生了什么，再说明影响和下一步。
- Button 使用具体动词：`Delete` 优于 `Confirm`，`Choose folder` 优于 `Proceed`。
- Thinking 不使用 Acting 文案；Waiting 明确等待谁/什么；Partial 不说“完成”。
- 不承诺未由 backend fact 确认的成功、可撤销性、耗时或安全性。
- Schwarz 的角色气质通过冷静、准确、有限温度表达，不使用夸张拟人台词破坏任务清晰度。

### 22.2 Preferred examples

| Prefer | Avoid | Reason |
|---|---|---|
| `Opening VS Code…` | `Invoking desktop.launch_application…` | 用户目标语言 |
| `I need your confirmation before deleting these files.` | `Tool invocation requires approval.` | 解释用户决定 |
| `Waiting for you to choose a folder.` | `Working…` | Waiting 不伪装进度 |
| `2 of 3 actions completed.` | `Done.` | Partial truth |
| `Couldn’t open VS Code. The application was not found.` | `Process failed: 0x…` | 用户影响优先 |
| `Cancel task` | `Stop process` | 产品语义而非内部实现 |

### 22.3 Labels and status

- Status label 只在 Surface/ambient signal 需要时出现，不常驻 Schwarz 旁。
- Icon button 有可访问名称；visible tooltip 只辅助发现，不承载唯一语义。
- 路径/文件名保持原值，并提供可理解的截断/查看完整方式。
- 最终全部文案、语气本地化和 Schwarz 角色口吻范围仍为 `TBD`。

---

## 23. Visual Reference Notes

| Surface / pattern | Google / Material influence | ArkClaw adaptation | Deliberately different |
|---|---|---|---|
| Capsule | Shape hierarchy、clear input focus、responsive container | Anchored to Schwarz、two-state compact structure、restrained controls | 不复制 Gemini prompt bar、Google Search/Spotlight composition |
| Expanded | Fluid container transformation、content-first hierarchy | 同一 task shell、no chat app navigation | 无 permanent history/sidebar/title bar |
| Activity | Meaningful motion、state clarity | Thinking/Acting/Waiting distinct；semantic task language | 无 spinner-only、tool logs、colorful progress spectacle |
| Confirmation | Focused containment、clear action hierarchy | Base task context remains；Schwarz Waiting | 不做 system MessageBox 或 mobile bottom sheet |
| Result/Error | Layered surface、progressive details | Character + Surface dual feedback、calm recovery | 无 celebratory Google color、exception dialog |
| Palette | Contextual actions、grouped hierarchy | Character/Current Task/ArkClaw separation、same anchor morph | 无 legacy menu、command palette、app grid |
| Workspace | Dynamic surfaces、minimal chrome | Logical regions appear only when needed；Conversation remains central | 无 Google app shell、Sidebar+Chat+Inspector、card wall |
| Motion | Responsive/expressive motion、spatial continuity | Controlled soft temperament、one dominant container motion | 无 exaggerated spring、brand star/glow、mobile transition assumptions |

所有 Surface 使用 `04` 的 ArkClaw color/type/shape roles；不采用 Google brand palette、Gemini exact composition、Google icon identity 或 Material default token values。

## 24. MVP Scope

Design System 的完整性不代表第一版必须实现全部 Surface。MVP 以“能从 Schwarz 发起请求、理解 Agent 行为、做出必要决定、看到真实结果并回到安静桌面”为闭环。

### 24.1 MVP Required

| Surface / capability | MVP scope | Gate |
|---|---|---|
| Character-only | Idle + active projection + return-to-task signal | Existing gestures unchanged |
| Conversation Capsule | Text input、Send、focus/draft/dismiss、Thinking/short response | Primary Invocation mapping must be resolved before release binding |
| Minimal Expanded Conversation | Long answer/multi-turn/embedded action 的单一连续容器；不含 history management | `G2` rules |
| Agent Activity | Thinking、simple Acting、semantic label、valid Cancel；basic multi-step only if backend signal exists | Backend presentation facts/cancellability |
| Confirmation | Summary、consequence、Confirm、Cancel、focused priority | Confirmation integration payload |
| Result | Simple Success、Partial、Cancelled、one relevant follow-up | Correlated backend result fact |
| Error | Recoverable/User Action Required、impact、real Retry/alternative、hidden Details entry if supported | Recovery availability signal |
| Anchored Action Palette | Root grouped list、Ask、Current Task conditional、Character、Settings/Hide/Quit | Right-click parity/migration decision |
| Character Action Palette | One-level Character group、select-dismiss、conditional active/Resume Autonomous | Character capability/availability signal |

### 24.2 MVP Optional / capability-dependent

| Item | Condition |
|---|---|
| Context / Attachment entry | `Planned`；只有 capability、permission 和 failure contract 确认后启用 |
| Voice entry | `Planned`；需要 recording/listening/stop/error contract |
| Passive / Ambient Notification | 后台任务存在且 notification policy 可验证时 |
| Determinate / multi-step progress | backend 提供可靠、用户可理解的 progress facts 时 |
| Details progressive disclosure | 有真实、用户有价值的 semantic details 时 |
| Rich Result preview | 第一版能产生 file/app/artifact 且有可靠 open/show action 时 |

### 24.3 Later

- Full Agent Workspace and advanced logical-region composition；
- persistent artifact review、multiple-file comparison 和 advanced task controls；
- advanced notification aggregation / OS notification；
- conversation history/search/persistence；
- rich technical diagnostics；
- multi-task foreground selection；
- final motion/character animation asset system。

Workspace 保持设计完整但不作为第一版默认要求。若 MVP 实际任务证明 `G3` 必须支持，需单独扩大范围并评审，不能让 Expanded 静默变成临时 Workspace。

---

## 25. Acceptance Criteria

以下是产品级 criteria，可转化为后续 TDD，但不指定测试框架或实现结构。

### 25.1 Character-only

- 默认只显示 Schwarz，无永久 input/toolbar/sidebar/status/button/badge。
- Idle 与 active projection 可区分，但 active feedback 不形成永久面板。
- Hover 不打开 Surface；Drag 不触发 Interact/Invocation/Palette。
- active task 收拢后存在可理解、可操作的恢复入口。
- Surface 收拢不发送 Cancel 或丢失 task context。
- Reduced Motion 和非颜色状态仍可理解。

### 25.2 Conversation Capsule

- 从已确认的 Schwarz invocation / 可访问入口出现；在手势门禁前不绑定冲突鼠标事件。
- 新对话可输入并 Submit；Enter、Shift+Enter、IME 和 Escape 符合 contract。
- Capsule 与 Schwarz 有清晰空间关系，且不遮挡角色主要可交互区域。
- Empty、Focused、Typing、Submitted、Thinking、inline Error 状态可辨。
- 有 draft 时 dismiss 不丢失；再次召唤恢复同一 Capsule，不创建副本。
- 超过 compact capacity 时进入 Expanded，不膨胀为 giant floating window。
- 不暴露 Sidebar、history、model、MCP、tool log 或 developer controls。
- Planned Context/Voice 不作为无功能死按钮发布。

### 25.3 Minimal Expanded Conversation

- 由 Capsule 连续 morph，保留 task、draft、focus/reading context。
- 支持多轮、较长回答、rich result 和嵌入 Activity/Error。
- 不出现 permanent title bar、Sidebar、全局 history 或每条回复 Card。
- Escape/Collapse 返回 Capsule；outside click 不关闭。
- Workspace 只有 `G3` 通过才可进入。
- Schwarz 仍保持可见状态关系。

### 25.4 Agent Activity

- Thinking 与 Acting 在 label、motion/containment 和 Schwarz 表达上可区分。
- Acting 显示用户相关 task title；默认不显示 raw tool/MCP/API/log。
- 简单动作不制造虚假多步骤 Progress。
- Cancel 只在当前 action 真实可取消时出现；Cancel intent 不立即显示 Cancelled。
- UI 收拢时 Activity 继续，Schwarz 接管 signal，并可恢复。
- backend result 到达后 Activity 原位转换为 Result/Error/Cancelled，不永久停在 Working。

### 25.5 Confirmation

- 只由有效 Waiting Confirmation projection 打开，并关联当前 task/context。
- 明确显示 action、scope/target、consequence、Confirm 与 Cancel/Not now。
- Outside click 不关闭/确认；Enter 不在无明确 focus 时批准。
- Escape 默认安全拒绝，例外必须保持 `TBD`/明确说明。
- Confirm/Cancel 只提交 decision intent；视觉结果等待 backend fact。
- Palette 不与 Confirmation 共存；Critical Error 可替换失效确认。
- Schwarz 表达 Waiting，不显示 Acting motion。

### 25.6 Result

- Simple、Rich、Partial、Cancelled 使用不同且诚实的结构。
- Partial 清楚列出已完成/未完成部分，不显示完整 Success。
- Result 说明实际完成内容，不只显示 “Done”。
- 每个 Result 最多一个自然 Primary follow-up，避免按钮墙。
- Rich/Partial 结果在用户理解前不自动消失；simple result 可按 timing policy 收拢。
- Result 不依赖颜色，Reduced Motion 立即呈现可读终态。

### 25.7 Error

- Error 说明目标、实际影响与真实恢复路径，位于问题附近。
- Raw exception/stack 默认隐藏；Details 不替代用户摘要。
- Retry 只在真实可用时显示；点击 Retry 不让 UI 本地进入 Thinking。
- Critical Error 取得最高前景且不与 Confirmation 堆叠。
- Dismiss/Collapse 不把 Error 标记为 resolved；Schwarz 保留恢复 signal。
- Error 不使用持续 shake、flash、alarm 或只红色表达。

### 25.8 Anchored Action Palette

- Right Click 替换只在现有菜单能力对等和迁移确认后启用。
- Palette 锚定 Schwarz，使用 compact grouped list，不是 legacy menu/launcher/grid。
- Ask、Current Task（条件）、Character、ArkClaw 分组符合 `02`；空分组不显示。
- 打开 Palette 不改变 Agent projection 或暂停角色动画。
- Outside click/Escape/Drag/selection 可 dismiss；click 不透传为另一个角色动作。
- Palette 与 Capsule/Confirmation/Critical Error 不无规则共存。
- Keyboard focus、读序与 icon accessible names 完整。

### 25.9 Character Action Palette

- 保持 Root Palette 外壳和 Schwarz anchor，不打开 cascade window。
- Agent task controls 与 Character actions 明确分组、不混淆。
- 选择动作后 Palette 自动关闭，A projection 不改变。
- Active state 仅在角色系统可可靠报告时显示，并同时使用 icon/text。
- Resume Autonomous 只在 manual action active 时出现。
- 动作不可用时不显示虚假选择；失败使用最小 Result/Error。

### 25.10 Cross-surface MVP criteria

- 同时最多一个主 Presentation 和一个 foreground Overlay。
- Focus 不被 sticky/overlay content 遮挡，关闭后恢复到有效来源。
- 亮/暗/高频桌面背景下，文字、icon、outline 和 state 均保持可读。
- 所有必要功能有非 Hover/非 Drag 的可访问路径。
- Motion 使用连续容器关系，并支持 Reduced Motion。
- 未解决鼠标 gesture mapping 时，产品评审必须阻止 release binding。

---

## 26. Unknown / TBD

1. **Blocking**：single-click Interact、double-click Capsule 与 candidate single-click Capsule 的最终 gesture arbitration。
2. Right-click Palette 替换现有菜单的 capability parity、迁移、回退和 release gate。
3. **Upstream alignment**：有草稿的 Capsule outside click 是只移除 focus，还是收拢并保留草稿。
4. Capsule/Expanded/Workspace exact dimensions、placement、minimum/maximum size 和 resize behaviour。
5. Exact icon glyph/library、typeface、color values、opacity/blur/shadow 与 motion durations/curves。
6. Capsule Context/Attachment 与 Voice 的 MVP capability、permission、error 和 recording/listening UX。
7. Capsule compact growth 的最终行数/内容阈值及自动 Expand 策略。
8. Expanded Conversation 的 exact content grouping、reading-position restoration 和 long-content behaviour。
9. Workspace final layout、logical-region placement、artifact arrangement 和是否进入首版。
10. Multi-monitor placement、跨 DPI 移动、taskbar variants 和 character-near-edge exact rules。
11. Global shortcut：`Shortcut: TBD`。
12. Hover feedback、Drag 中 Escape、已有 Capsule 再次 Invocation toggle 行为。
13. Acting/Thinking 中新 Submit 的 correction/queue/redirect ownership。
14. Backend presentation integration 的 cancellability、progress、confirmation expiry、offline/unavailable 和 recovery signals。
15. Notification form、timeout、aggregation、unread signal 和 OS notification boundary。
16. Success/Error/Cancelled feedback duration 与 clear-to-idle contract。
17. Action Palette final labels/order、Character action list/availability、Resume Autonomous wording 和 Quit confirmation。
18. Details 中允许的 diagnostic scope 与用户/开发者内容分层。
19. Draft、conversation、task 和 artifact persistence / history。
20. Light/Dark/High-contrast strategy 与桌面背景采样。
21. Schwarz 状态动画、静态替代、声音和资产授权。
22. 多任务前景选择、结果归属与恢复顺序；不定义 backend scheduling。
23. Cancel intent 与已经发生副作用之间的恢复 microcopy/contract。

---

## 27. Explicit Non-goals

本文不设计或产出：

- Qt、QWidget、QML、QSS、Python implementation 或 CSS；
- controller architecture、signals/slots、class hierarchy、event loop；
- window flags、HWND、Z-order implementation、native event handling；
- exact coordinates、pixel geometry、rendering/animation code；
- Agent backend、backend state machine、planning、tool router、MCP 或 execution lifecycle；
- API、database、file persistence、deployment、packaging；
- final visual assets、high-fidelity prototype 或 production UI；
- engineering TDD、implementation plan 或 Codex implementation；
- 未确认 capability、gesture 或 Workspace scope 的实现承诺。

---

## 28. Final Design Review

| Review item | Result | Evidence / correction |
|---|---|---|
| 遵守 `01-ui-vision.md` | Pass with known gesture conflict | Character First、UI on Demand、Calm Desktop、gesture gate 保留 |
| 遵守 `02-interaction-model.md` | Conditional pass | Surface triggers、coexistence、flows 与 IA 一致；draft outside-click 差异已登记、未擅自选择 |
| 遵守 `03-ui-state-machine.md` | Conditional pass | P/A/C/O ownership、guards、priority、backend-fact boundary 未改变；同一 draft 差异等待上位统一 |
| 遵守 `04-ui-design-system.md` | Pass | Shape/spacing/surface/material/type/motion/state/accessibility 均应用 token contract |
| 未变成普通 Chat App | Pass | Capsule/Expanded 是 task surface，无永久 history/sidebar/input |
| 未默认引入 Sidebar | Pass | Workspace 采用按需逻辑区域，明确禁止三栏 shell |
| 未出现过多 Card | Pass | Card 只用于独立语义对象；普通回复/region 不自动卡片化 |
| Character First 成立 | Pass | Character-only 是默认/return state；轻量 Surface anchor Schwarz |
| Capsule 足够轻量 | Pass | Compact two-state structure、limited controls、planned capability slots、G2 growth |
| Workspace 只服务复杂任务 | Pass | G3 + explicit/implicit agreement；Later scope；不从 Character only 强开 |
| Activity 区别普通聊天 | Pass | 专属 task title、projection、progress/cancel/result morph；tool noise 隐藏 |
| Palette 区别传统菜单 | Pass | Product grouping、same-shell Character level、anchor/motion、no cascade/grid |
| 所有临时 Surface 有退出 | Pass | Escape、outside click、selection、collapse、return target 逐项定义 |
| Motion 保持连续性 | Pass | Character→Capsule→Expanded→Workspace 与 Activity→Result 均为同壳连续变化 |
| MVP 范围受控 | Pass | Workspace/advanced artifacts/history later；voice/context/notification capability-dependent |
| 未进入工程实现 | Pass | 无 Qt、window、controller、API 或 backend lifecycle 设计 |
| Accessibility 可审查 | Pass | Focus、read order、contrast、non-color、Reduced Motion、gesture alternatives 均写入 Surface criteria |

### Review conclusion

复核发现并记录了一项此前未显式登记的 `02/03` 差异：有草稿的 Capsule 在 outside click 后是否保持可见。本文只固定“不丢草稿”，将可见结果保持为上位统一前的 `TBD`。此外，Primary Conversation Invocation 的鼠标映射仍是已知冲突；Action Palette 还存在从现有右键菜单迁移与能力对等的 `TBD`。本文未通过 wireframe、motion 或 MVP 分类绕过这些门禁。

下一阶段应先解决 gesture arbitration 与 right-click migration，并用 low-fidelity prototype 验证 Capsule 两态结构、Surface anchoring、focus/escape、Activity→Result 和 Palette hierarchy；在这些产品门禁通过后，再编写 frontend engineering TDD。本文不自动创建下一阶段文件。
