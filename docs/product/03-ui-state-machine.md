# ArkClaw UI State Machine

> 阶段：Phase 3 — UI State Machine Design  
> 文档类型：Product Design / UX State Contract  
> 上位约束：`docs/product/01-ui-vision.md`、`docs/product/02-interaction-model.md`  
> 下游用途：UI controller、state ownership、transition rules、automated tests、manual acceptance tests  
> 本文不包含：具体类、API、Qt 实现、事件循环、视觉规格或 Agent 后端架构

## 1. Purpose

本文把已确认的 UI Vision 与 Interaction Model 转换为严格的产品级 UI 状态机：明确状态、事件、转换、守卫条件、可见 Surface、用户输入、Agent 状态投影、Overlay 优先级、中断、收拢与异常行为。

本文只规定用户能够观察和验证的 UI 行为。后续工程可以据此选择实现结构，但不得把本文中的 Region、State 或 Event 直接理解为指定的类、枚举、Signal、Slot 或 API。

### 1.1 Agent architecture boundary

Agent 后端架构与执行生命周期已独立设计，不属于本文状态机。本文中的 Thinking、Acting、Waiting、Success、Error 全部是 **presentation-level projections（表现层投影）**：UI 消费后端 runtime facts / signals，将其映射为用户可见状态。

本文不得定义或复制 Agent 的 planning、tool routing、execution scheduling、memory、orchestration、MCP 或 backend task lifecycle。UI 需要后端信息时，只定义 required signal / integration contract，不规定后端如何产生它。

### 1.2 Authority and known conflict

`01` 与 `02` 已记录同一项未决冲突：`01` 保护“单击 → Interact”并确认“双击 → Capsule”的产品意图；Phase 2 输入曾提出“单击 → Capsule”；`02` 使用 `Primary Conversation Invocation` 表达产品结果，并把具体映射列为阻断性 `TBD`。

本文沿用 `02`：建模语义事件 `primary_conversation_invoked`，但不为 `character_left_click` 或 `character_double_click` 发明第三种映射。双击当前也不能标为 Reserved，因为 `01` 已赋予其产品意图。

---

## 2. State Machine Principles

1. **Character First**：除非用户明确隐藏 Schwarz，否则 UI 收拢后回到 Character only。
2. **Conversation First**：状态机不要求用户理解 tool、MCP、API、command 或 runtime。
3. **UI on Demand**：Surface 由明确事件进入，并具有明确退出路径。
4. **Progressive Disclosure**：Capsule、Expanded、Workspace 互斥；升级必须通过守卫。
5. **Agent State Visible**：Agent backend facts 只被投影为用户可理解的 Idle、Listening、Thinking、Acting、Waiting、Success、Error。
6. **Calm Desktop**：所有临时 UI 都可 dismiss、collapse、complete 或 recover。
7. **Dismiss Is Not Cancel**：收起 UI 不自动向后端发出取消意图。
8. **Orthogonal Regions**：UI、Agent projection、角色直接操控与 Overlay 分别建模，禁止组合枚举爆炸。

---

## 3. State Dimensions

状态机由四个正交 Region 构成。任一时刻，每个 Region 恰有一个活动状态；可观察状态是四者的组合。

| Region | Symbol | Owns | Does not own |
|---|---|---|---|
| UI Presentation | `P` | 主 Surface、Conversation 展开程度、Workspace 可见性 | Agent 是否仍在工作 |
| Agent Presentation Projection | `A` | 后端事实对应的用户可见语义 | 后端 planning、routing、scheduling 或 lifecycle |
| Character Interaction | `C` | Hover、Drag 等角色直接操控阶段 | Conversation 内容或 Agent 执行 |
| Overlay / Modal | `O` | Palette、Confirmation、关键 Error、临时 Notification | 基础 Presentation 与后台任务 |

本文使用 `(P=<presentation>, A=<projection>, C=<character>, O=<overlay>)`。`—` 表示 Region 不变化，`*` 表示任意合法状态。

### 3.1 DESKTOP_IDLE

`DESKTOP_IDLE` 是组合简称，而非单层枚举：

```text
P=CHARACTER_ONLY
A=AGENT_IDLE
C=CHARACTER_NEUTRAL
O=OVERLAY_NONE
```

当 UI 收起但后端仍报告 Thinking/Acting 时，`P` 仍是 `CHARACTER_ONLY`，但系统不是 `DESKTOP_IDLE`。

### 3.2 Hierarchy

```text
UI Presentation (P)
├── CHARACTER_ONLY
├── CONVERSATION
│   ├── CAPSULE_IDLE
│   ├── CAPSULE_TYPING
│   └── CONVERSATION_EXPANDED
└── WORKSPACE_OPEN

Agent Presentation Projection (A)
├── AGENT_IDLE
├── AGENT_LISTENING
├── AGENT_THINKING
├── AGENT_ACTING
├── WAITING
│   ├── AGENT_WAITING_CONFIRMATION
│   ├── AGENT_WAITING_INPUT
│   └── AGENT_WAITING_EXTERNAL
├── AGENT_SUCCESS
├── AGENT_ERROR
└── AGENT_CANCELLED

Character Interaction (C)
├── CHARACTER_NEUTRAL
├── CHARACTER_HOVER
└── CHARACTER_DRAGGING

Overlay / Modal (O)
├── OVERLAY_NONE
├── ACTION_PALETTE_OPEN
│   └── CHARACTER_ACTION_PALETTE
├── CONFIRMATION_MODAL
├── CRITICAL_ERROR_MODAL
└── TEMPORARY_NOTIFICATION
```

`CHARACTER_INTERACT_FEEDBACK` 当前不作为独立状态：它没有独立 Surface、输入所有权或持续语义。若未来具备持续、可中断或独立控制语义，再重新评估。

---

## 4. UI Presentation States

| State | Purpose | Primary visible Surface | May coexist with backend work |
|---|---|---|---|
| `CHARACTER_ONLY` | 最小桌面占用；所有 UI 收拢后的返回状态 | Schwarz；必要时只有状态/待查看信号 | Yes |
| `CAPSULE_IDLE` | Capsule 已打开，当前无未提交编辑 | Schwarz + Conversation Capsule | Yes |
| `CAPSULE_TYPING` | Capsule 内存在正在编辑或未提交的输入 | Schwarz + Capsule + draft | Yes |
| `CONVERSATION_EXPANDED` | 连续上下文、多个相关结果或持续反馈 | Schwarz + Expanded Conversation | Yes |
| `WORKSPACE_OPEN` | 复杂、持续、多对象任务的结构化控制 | Schwarz + Agent Workspace | Yes |

`CAPSULE_IDLE` 与 `CAPSULE_TYPING` 分开，是因为 outside click、Escape 与草稿保护不同。Expanded/Workspace 中的局部编辑不改变整体 dismiss 语义，因此不复制额外 Presentation 状态。

---

## 5. Agent Presentation Projection States

| State | Consumed backend fact / signal | User-facing meaning |
|---|---|---|
| `AGENT_IDLE` | no active or pending user-relevant task | Agent 可用，不需要注意 |
| `AGENT_LISTENING` | UI is accepting current conversation input | 输入尚未提交或正在等待表达 |
| `AGENT_THINKING` | backend reports reasoning/planning phase | 尚未开始真实外部行动 |
| `AGENT_ACTING` | backend reports user-relevant external action | 已经发生或正在发生实际行动 |
| `AGENT_WAITING_CONFIRMATION` | backend requires explicit decision | 未确认前不会执行受保护行动 |
| `AGENT_WAITING_INPUT` | backend requires missing information/choice | 用户需补充内容，不是授权确认 |
| `AGENT_WAITING_EXTERNAL` | backend reports external dependency wait | Agent 没有持续推进 |
| `AGENT_SUCCESS` | backend reports completed/partial result | 结果已产生；可继续或收拢 |
| `AGENT_ERROR` | backend reports user-relevant failure | 目标、影响和恢复路径可理解 |
| `AGENT_CANCELLED` | backend acknowledges cancellation | 当前请求已停止；不是 Error 或 Success |

这些状态不规定后端状态数量、内部转换或执行模型。Partial Success 是 `AGENT_SUCCESS` 的结果变体，不另建 UI projection state；Result 必须明确已完成和未完成部分。

### 5.1 Required integration signals

UI 至少需要接收以下语义事实；名称只表达契约，不是 API：

- stable task identity / correlation；
- user-facing phase：thinking、acting、waiting；
- waiting reason：confirmation、input、external；
- user-facing action label 与可选 semantic progress；
- cancellability：currently cancellable / not cancellable；
- confirmation scope、effect 与有效性；
- result：success、partial、error、cancelled；
- recovery availability：retry / alternative / none；
- stale/duplicate event correlation information。

---

## 6. Overlay / Modal States

| State | Role | Priority | Base state behaviour |
|---|---|---:|---|
| `OVERLAY_NONE` | 无独立临时层 | — | Base Presentation 正常交互 |
| `ACTION_PALETTE_OPEN` | Palette 根层 | Low | 轻量 Conversation 暂时收拢；Workspace 可保留 |
| `CHARACTER_ACTION_PALETTE` | Character 分组获得选择焦点 | Low | 仍是同一 Palette，不是第二窗口 |
| `CONFIRMATION_MODAL` | Required confirmation | High | Base context 可见，普通输入不争夺决定 |
| `CRITICAL_ERROR_MODAL` | 使行动或确认失效的关键错误 | Highest | 替代失效决定，保留恢复路径 |
| `TEMPORARY_NOTIFICATION` | Character only 下的短暂结果入口 | Lowest | 有更高 Surface 时合并或降级 |

普通 Action Progress 与普通 Error Result 嵌入当前 Presentation；只有 Character only 下必要的临时反馈，或必须取得前景的阻断情况，才进入 Overlay。

---

## 7. Event Model

### 7.1 Event rules

- Event 表达已发生的用户意图或后端提供的 UI integration fact，不表达实现回调。
- 重复 Event 必须明确为 idempotent、ignored 或 self-transition。
- `conversation_dismiss`、`workspace_close` 与 `outside_click` 默认只改变 UI。
- `cancel` 只是向后端提交明确取消意图；只有 cancellation acknowledgement 才投影为 Cancelled。

### 7.2 Character and conversation events

| Event | Producer / valid states | Repeat policy | UI effect | Backend impact |
|---|---|---|---|---|
| `character_hover_enter/leave` | 有效角色命中区；非 Drag | 重复 ignored | `C↔HOVER/NEUTRAL` | None |
| `character_left_click` | 完整 click；非 Drag | 映射未决 | **TBD**；不授权新 Conversation 转换 | 当前基线请求一次 Interact；最终 TBD |
| `character_double_click` | 完整 double click；非 Drag | 门禁通过前 blocked | `01` 意图为 Capsule，但当前阻断 | None |
| `primary_conversation_invoked` | 最终确认的召唤映射/可访问入口 | 恢复同一主 Surface | 打开/恢复 Conversation | None |
| `character_right_click` | 有效右键；无 Drag/阻断 Overlay | Palette 开时 toggle close | 打开/关闭 Palette | None |
| `character_drag_start/end` | 既有 Drag 语义 | Active Drag 中重复 ignored | `C↔DRAGGING`；Palette dismiss | None |
| `character_action_selected` | Character Palette | 单次消费 | Palette dismiss | 提交角色动作意图；不改变 Agent projection |
| `conversation_open` | Primary Invocation 或 required input | 已开时恢复 | `P→CAPSULE` 或恢复原层级 | None |
| `text_input_started/cleared` | Capsule draft 变化 | 无变化时 ignored | `P↔CAPSULE_TYPING/IDLE` | None |
| `submit` | 有效非空输入；无 Confirmation | 相同未接受 submit ignored | 保留 P，保护/清理 draft | 提交用户请求；等待后端 acknowledgement |
| `conversation_expand/collapse` | 用户或内容 guard | 已在目标层 ignored | Capsule ↔ Expanded | None |
| `conversation_dismiss` | Escape、允许 outside click、回桌面 | Character only ignored | `P→CHARACTER_ONLY` | MUST NOT send cancel |

### 7.3 Backend projection and decision events

| Event | Producer | Repeat policy | UI effect | Projection effect |
|---|---|---|---|---|
| `backend_thinking` | Agent integration | 同 task/phase idempotent | Thinking feedback | `A→THINKING` |
| `backend_acting` | Agent integration | 同 action 合并 | Action/Progress | `A→ACTING` |
| `backend_waiting_confirmation` | Agent integration | 同 confirmation 合并 | `O→CONFIRMATION` | `A→WAITING_CONFIRMATION` |
| `backend_waiting_input` | Agent integration | 同 prompt 合并 | 关联 prompt | `A→WAITING_INPUT` |
| `backend_waiting_external` | Agent integration | 更新同一等待 | semantic waiting | `A→WAITING_EXTERNAL` |
| `backend_succeeded` | Agent integration | 按 task identity idempotent | Success/Partial Result | `A→SUCCESS` |
| `backend_failed` | Agent integration | 同 failure 合并 | Error；关键时 modal | `A→ERROR` |
| `backend_cancelled` | Agent integration | 已取消 ignored | Cancellation Result | `A→CANCELLED` |
| `confirm` | 用户明确 Confirm | 单次消费 | Confirmation closes | 提交 decision；等待新 backend fact |
| `cancel` | 用户明确 Cancel/Not now | 只作用最高目标 | 取消请求反馈 | 提交 cancel intent；不自行宣布 cancelled |
| `retry` | Error 中真实 Retry | accepted 前重复 ignored | Retry request feedback | 提交 retry intent；等待 backend fact |
| `dismiss_error` | 用户收起 Error/details | 重复 ignored | Foreground closes；signal remains | None |
| `workspace_open/collapse/close` | 用户/复杂度 guard | 已在目标层 ignored | 改变 P | None；close MUST NOT cancel |
| `outside_click` | 指针 | 按 dismiss guard | 关闭允许的最高层 | None |
| `escape` | Keyboard | 只处理最高可退出层 | 见第 13 节 | 默认 None |
| `notification_open` | 用户 | 已打开时 focus existing | 恢复所属 P | None |
| `feedback_completed` | UI 可读反馈结束 | 重复 ignored | 临时反馈关闭 | 不改变 backend；projection 可回 Idle only when signalled/cleared |

## 8. State Definitions

以下状态采用统一模板。每行依次说明 Purpose、Visible Surfaces / Schwarz、Allowed Inputs、Invalid Inputs、Entry、Exit / Allowed Transitions、Interruptibility / Background。Forbidden Transitions 另由第 17 节统一锁定。

### 8.1 Stable desktop and Presentation states

#### State: DESKTOP_IDLE

- **Purpose**：完全安静、没有用户相关活动的基线。
- **Visible / Schwarz**：仅 Schwarz；Idle，可有低频 ambient feedback。
- **Allowed Inputs**：Hover、Primary Invocation、Right Click、Drag、当前受保护的 Interact。
- **Ignored / Invalid**：无上下文 Confirm/Retry；直接 Workspace；冲突未解的 click-to-conversation。
- **Entry**：P=Character only、A=Idle、C=Neutral、O=None 同时成立。
- **Exit / Allowed**：→ Hover、Dragging、Capsule、Palette，或接收新的 backend projection fact。
- **Interrupt / Background**：可被任意有效入口打断；没有后台用户相关任务。

#### State: CHARACTER_ONLY

- **Purpose**：UI 收拢时保持 Character First，同时允许后端任务独立继续。
- **Visible / Schwarz**：Schwarz；按 A 表达 Idle/Thinking/Acting/Waiting/Success/Error。
- **Allowed Inputs**：Primary Invocation、Right Click、Drag、Notification open。
- **Ignored / Invalid**：dismiss 视为 cancel；无 guard 直接 Workspace。
- **Entry**：conversation dismiss、workspace close、回到桌面、空 Capsule drag start。
- **Exit / Allowed**：→ Capsule、恢复 Expanded/Workspace、Palette、阻断 Confirmation/Error。
- **Interrupt / Background**：A=Thinking/Acting/Waiting 时后端继续；必须有恢复入口。

#### State: CAPSULE_IDLE

- **Purpose**：已打开、可立即输入且无未提交草稿的轻量 Conversation。
- **Visible / Schwarz**：Schwarz + Capsule + 当前任务最小状态；Schwarz 按 A 表达。
- **Allowed Inputs**：type、Expand、Escape、允许的 outside click、Primary Invocation。
- **Ignored / Invalid**：空 Submit；第二个 Capsule；无 guard Workspace。
- **Entry**：conversation open、text cleared、Expanded collapse、无草稿恢复。
- **Exit / Allowed**：→ Typing、Expanded、Character only、Workspace（guarded）。
- **Interrupt / Background**：可收拢；不影响后端工作。

#### State: CAPSULE_TYPING

- **Purpose**：保护正在编辑或未提交的输入。
- **Visible / Schwarz**：Schwarz + Capsule + draft；Schwarz 保持真实 A 投影。
- **Allowed Inputs**：edit、Enter、Shift+Enter、clear、Expand、Escape、outside click。
- **Ignored / Invalid**：outside click 丢弃 draft；重复 Submit 创建并行副本。
- **Entry**：text input started、带 draft 恢复。
- **Exit / Allowed**：→ Capsule Idle、Expanded、Character only；Submit 等待 backend fact。
- **Interrupt / Background**：可收拢并在当前会话保留 draft；跨重启 TBD。

#### State: CONVERSATION_EXPANDED

- **Purpose**：承载连续上下文、多个相关结果或持续语义反馈。
- **Visible / Schwarz**：Schwarz + Expanded；Action/Result 嵌入；Schwarz 按 A 表达。
- **Allowed Inputs**：type、Submit、Collapse、Workspace open、有效 Cancel、Escape。
- **Ignored / Invalid**：outside click dismiss；同时 Capsule；仅因回答长进入 Workspace。
- **Entry**：conversation expand、workspace collapse。
- **Exit / Allowed**：→ Capsule、Workspace、Character only。
- **Interrupt / Background**：可收拢；不影响后端工作。

#### State: WORKSPACE_OPEN

- **Purpose**：复杂、持续、多对象任务的结构化理解与控制。
- **Visible / Schwarz**：Schwarz + 一个 Workspace；阻断 Overlay 可取得前景。
- **Allowed Inputs**：任务操作、Conversation input、Collapse、Close、有效 Cancel/Retry、Right Click。
- **Ignored / Invalid**：第二个 Workspace；outside click close；简单任务自动升级。
- **Entry**：workspace open 且复杂度 guard 通过，或恢复既有 Workspace。
- **Exit / Allowed**：→ Expanded 或 Character only；A 独立变化。
- **Interrupt / Background**：可收拢/关闭 Surface；后端继续；Schwarz 可独立拖动。

### 8.2 Character interaction states

#### State: CHARACTER_HOVER

- **Purpose**：最低强度提示可交互，不创建 Surface。
- **Visible / Schwarz**：P 不变；不新增按钮；不改变 A 或中断角色动画。
- **Allowed Inputs**：hover leave、Invocation candidate、Right Click、Drag start。
- **Ignored / Invalid**：Hover 自动打开 UI；Hover 成为关键功能唯一入口。
- **Entry**：character hover enter。
- **Exit / Allowed**：→ Neutral 或 Dragging。
- **Interrupt / Background**：完全可中断；后端不受影响。

#### State: CHARACTER_DRAGGING

- **Purpose**：保护既有桌宠直接操控，使 Drag 高于 click/invocation。
- **Visible / Schwarz**：Palette 关闭；Workspace/Expanded 原位；有内容 Capsule 不丢失。
- **Allowed Inputs**：drag continuation、drag end、既有合法取消（Escape TBD）。
- **Ignored / Invalid**：left/double click、Conversation invocation、Right Click。
- **Entry**：character drag start。
- **Exit / Allowed**：→ Neutral/Hover；恢复空间关联。
- **Interrupt / Background**：不取消后端任务；同一指针序列绝不转成 click/Interact/Conversation。

### 8.3 Agent presentation projection states

这些状态只描述 UI 如何呈现后端事实，不定义后端进入、退出或执行方式。

#### State: AGENT_IDLE

- **Purpose**：表达没有当前用户相关活动。
- **Visible / Schwarz**：由 P 决定；Schwarz Idle。
- **Allowed Inputs**：Conversation、type、Submit、Palette。
- **Ignored / Invalid**：无请求显示 Acting/Success。
- **Entry**：backend reports idle / no pending user-relevant task。
- **Exit / Allowed**：根据 backend/UI fact → Listening/Thinking/其他 projection。
- **Interrupt / Background**：无用户相关后台任务。

#### State: AGENT_LISTENING

- **Purpose**：表达 UI 正在接受当前 Conversation 输入。
- **Visible / Schwarz**：Capsule/Expanded/Workspace conversation；Schwarz Listening。
- **Allowed Inputs**：type、Submit、collapse/dismiss。
- **Ignored / Invalid**：空 Submit；Character only 仍宣称 Listening。
- **Entry**：conversation input becomes active。
- **Exit / Allowed**：submit acknowledged → Thinking；dismiss without pending need → Idle；required prompt → Waiting Input。
- **Interrupt / Background**：草稿保护适用。

#### State: AGENT_THINKING

- **Purpose**：把判断/规划与真实外部行动区分。
- **Visible / Schwarz**：semantic thinking；Character only 时由 Schwarz 表达。
- **Allowed Inputs**：Cancel intent、继续输入、提交修正、expand/collapse。
- **Ignored / Invalid**：重复相同 Submit；显示成已执行。
- **Entry**：backend thinking fact for current task。
- **Exit / Allowed**：由 backend fact → Acting/Waiting/Success/Error/Cancelled。
- **Interrupt / Background**：UI 必须提供取消意图入口；收拢后后台可继续。

#### State: AGENT_ACTING

- **Purpose**：表达后端正在进行用户可感知的真实外部行动。
- **Visible / Schwarz**：有价值的 Action/Progress；Schwarz Acting。
- **Allowed Inputs**：Cancel（仅 signal says cancellable）、Inspect、collapse、编辑 draft。
- **Ignored / Invalid**：虚假 Cancel；新输入静默中断动作；低层 tool noise。
- **Entry**：backend acting fact + user-facing action label。
- **Exit / Allowed**：由 backend fact → Waiting/Success/Error/Cancelled。
- **Interrupt / Background**：UI 收拢不改变 backend；可取消性由 integration signal 决定。

#### State: AGENT_WAITING_CONFIRMATION

- **Purpose**：表达需要明确授权，与缺信息/外部等待区分。
- **Visible / Schwarz**：通常 Confirmation；收拢后至少 Waiting signal + 恢复入口。
- **Allowed Inputs**：Confirm、Cancel/Not now、显式 Collapse。
- **Ignored / Invalid**：outside click confirm；超时隐式 confirm；Submit 绕过决定。
- **Entry**：backend waiting-confirmation fact with valid scope/effect。
- **Exit / Allowed**：提交 decision 后等待 backend Acting/Cancelled/Error fact。
- **Interrupt / Background**：可收拢但不可丢失；后端是否继续由后端事实决定。

#### State: AGENT_WAITING_INPUT

- **Purpose**：表达缺少信息或选择。
- **Visible / Schwarz**：关联 prompt；隐藏时 Waiting signal。
- **Allowed Inputs**：type、Submit answer、Collapse、Cancel intent。
- **Ignored / Invalid**：新任务静默替换当前等待。
- **Entry**：backend waiting-input fact。
- **Exit / Allowed**：提交输入后等待 backend Thinking/Cancelled/Error fact。
- **Interrupt / Background**：可稍后返回；不得伪装成仍在推进。

#### State: AGENT_WAITING_EXTERNAL

- **Purpose**：表达外部条件、时间或依赖尚未满足。
- **Visible / Schwarz**：semantic waiting / ambient；不持续弹窗。
- **Allowed Inputs**：Inspect、有效 Cancel intent、Collapse。
- **Ignored / Invalid**：重复通知；假进度。
- **Entry**：backend waiting-external fact。
- **Exit / Allowed**：等待 backend Thinking/Acting/Cancelled/Error fact。
- **Interrupt / Background**：通常后台等待；通知降级为 Ambient。

#### State: AGENT_SUCCESS

- **Purpose**：表达完成/部分完成结果。
- **Visible / Schwarz**：Result 嵌入；隐藏时 temporary/ambient；Schwarz 短暂 Success。
- **Allowed Inputs**：Continue、Collapse、打开结果、新 Submit。
- **Ignored / Invalid**：同一 task 同时 Error；未读 Partial 自动消失。
- **Entry**：backend success/partial result fact。
- **Exit / Allowed**：新请求或 backend/UI clear-to-idle contract。
- **Interrupt / Background**：复杂结果保留；feedback timing TBD。

#### State: AGENT_ERROR

- **Purpose**：表达目标未完成、实际影响与恢复路径。
- **Visible / Schwarz**：普通 Error 嵌入；关键错误 modal；Schwarz Error。
- **Allowed Inputs**：Retry intent、修改请求、Details、Dismiss、End task。
- **Ignored / Invalid**：技术详情默认展开；Dismiss 自动变 Idle/Success。
- **Entry**：backend user-relevant failure fact。
- **Exit / Allowed**：等待 backend Thinking/Idle/other accepted result fact；Dismiss 可保持 Error。
- **Interrupt / Background**：可收拢但必须保留恢复入口。

#### State: AGENT_CANCELLED

- **Purpose**：表达 backend 已确认取消，避免误认为 Error/Success。
- **Visible / Schwarz**：Cancellation Result；随后降低强度。
- **Allowed Inputs**：Continue/new request、Collapse。
- **Ignored / Invalid**：重复 Cancel；同时显示 Acting。
- **Entry**：backend cancellation acknowledgement。
- **Exit / Allowed**：新请求或 clear-to-idle signal。
- **Interrupt / Background**：UI 不推断后端清理细节。

### 8.4 Overlay states

#### State: ACTION_PALETTE_OPEN

- **Purpose**：提供少量上下文动作，不取代 Conversation。
- **Visible / Schwarz**：一个 Palette；Workspace 可保留，轻量 Conversation 暂收拢；Schwarz 状态不变。
- **Allowed Inputs**：Ask、Current Task、Character、ArkClaw、outside click、Escape、Right Click。
- **Ignored / Invalid**：与 Confirmation/Critical Error 竞争；第二个 Palette。
- **Entry**：character right click + palette guard。
- **Exit / Allowed**：→ Character group / None / Conversation restore。
- **Interrupt / Background**：完全可 dismiss；后端继续。

#### State: CHARACTER_ACTION_PALETTE

- **Purpose**：同一 Palette 内直接选择角色动作。
- **Visible / Schwarz**：Character group；选择前 Schwarz 不变。
- **Allowed Inputs**：Relax/Sit/Sleep/Move/Special、Back、Escape、outside click。
- **Ignored / Invalid**：Character action 当作 Agent tool；虚假可用项。
- **Entry**：Character group opened。
- **Exit / Allowed**：→ Palette root / None。
- **Interrupt / Background**：完全可 dismiss；A 不变。

#### State: CONFIRMATION_MODAL

- **Purpose**：为高影响/超范围行动取得明确决定。
- **Visible / Schwarz**：单一 Confirmation + 可读 Base context；Schwarz Waiting。
- **Allowed Inputs**：Confirm、Cancel/Not now、允许的显式 Collapse、Escape 规则。
- **Ignored / Invalid**：outside click dismiss/confirm；Palette；普通 Submit 绕过。
- **Entry**：backend waiting-confirmation fact。
- **Exit / Allowed**：decision submitted、critical invalidation、expiry。
- **Interrupt / Background**：取得前景；收拢后仍需恢复入口。

#### State: CRITICAL_ERROR_MODAL

- **Purpose**：处理使当前行动/决定失效且需立即理解的错误。
- **Visible / Schwarz**：一个 Critical Error；Schwarz Error。
- **Allowed Inputs**：真实 Retry、Dismiss/Collapse、Details、End task。
- **Ignored / Invalid**：outside click 解决错误；Palette；原 Confirmation 继续有效。
- **Entry**：backend critical failure / confirmation invalidation fact。
- **Exit / Allowed**：Retry intent accepted by backend、Dismiss、End task。
- **Interrupt / Background**：可收拢但不自动标记解决。

#### State: TEMPORARY_NOTIFICATION

- **Purpose**：Character only 时表达值得查看但不应强开主 Surface 的结果。
- **Visible / Schwarz**：一个最小反馈/入口；Schwarz 显示相应 projection。
- **Allowed Inputs**：Open、Dismiss、outside click、feedback completion。
- **Ignored / Invalid**：覆盖高优先 Surface；显示 tool noise；多个通知叠加。
- **Entry**：后台 result/wait/error + notification guard。
- **Exit / Allowed**：→ None；Open 恢复所属 P。
- **Interrupt / Background**：可被更高优先交互替代或合并。

## 9. Transition Tables

下表描述 UI 合法转换，不是 Agent 后端生命周期。用户事件只提交 intent；只有后端 integration fact 可以改变 `A` 中的 Thinking、Acting、Waiting、Success、Error 或 Cancelled 投影。

### 9.1 Presentation and character transitions

| Current | Event | Guard | Next | Observable result |
|---|---|---|---|---|
| `DESKTOP_IDLE` | `primary_conversation_invoked` | `G1` | `(P=CAPSULE_IDLE, A=LISTENING, C=NEUTRAL, O=NONE)` | Capsule 从 Schwarz 邻近关系进入并取得输入焦点 |
| `P=CHARACTER_ONLY, A!=IDLE` | `primary_conversation_invoked` | current task context exists | 恢复该任务最后有效的 Capsule/Expanded/Workspace；`A` 不变 | 用户回到正在进行或待处理的任务 |
| `P=WORKSPACE_OPEN` | `primary_conversation_invoked` | — | self-transition | 聚焦 Workspace 的 Conversation 区域，不新建 Capsule |
| `C=NEUTRAL` | `character_hover_enter` | not dragging | `C=HOVER` | 只有轻微角色反馈，无 Surface |
| `C=HOVER` | `character_hover_leave` | — | `C=NEUTRAL` | Hover feedback 结束 |
| `C=*` | `character_drag_start` | existing pet drag recognized | `C=DRAGGING`; Palette dismiss | 同一指针序列不再产生 click/invocation |
| `C=DRAGGING` | click/double-click candidate | — | self-transition / ignored | 不打开 Capsule，不触发 Interact |
| `C=DRAGGING` | `character_drag_end` | — | `C=NEUTRAL/HOVER` | P、A 与草稿保持 |
| any | raw left/double click | binding unresolved | blocked as Conversation transition | 沿用既有 Interact；Conversation 映射为阻断性 TBD |
| `P=CAPSULE_IDLE` | `text_input_started` | draft non-empty | `P=CAPSULE_TYPING` | 保护草稿 |
| `P=CAPSULE_TYPING` | `text_input_cleared` | draft empty | `P=CAPSULE_IDLE` | 回到空输入 |
| `P=CAPSULE_*` | `conversation_expand` | `G2` or explicit user action | `P=CONVERSATION_EXPANDED` | 上下文连续扩展 |
| `P=CONVERSATION_EXPANDED` | `conversation_collapse` | no blocking overlay | `P=CAPSULE_IDLE/TYPING` | 草稿与当前任务上下文保留 |
| `P=CAPSULE_* / EXPANDED` | `workspace_open` | `G3` | `P=WORKSPACE_OPEN` | 同一任务连续升级，不创建第二会话 |
| `P=WORKSPACE_OPEN` | `workspace_collapse` | no blocking overlay | `P=CONVERSATION_EXPANDED` | 结构化工件保留 |
| any visible P | `conversation_dismiss/workspace_close` | `G6` | `P=CHARACTER_ONLY` | 只隐藏 UI；`A` 不变且不发 cancel |

### 9.2 Agent projection transitions

| Current projection | Event | Guard | Next projection | UI responsibility |
|---|---|---|---|---|
| `LISTENING` | `submit` | valid input; no blocking confirmation | unchanged until backend fact | 防重复提交，显示“请求已提交”反馈；不自行进入 Thinking |
| `IDLE/LISTENING/*` | `backend_thinking` | `G10` | `THINKING` | 显示可取消入口；不伪装为 Acting |
| `THINKING` | corrective `submit` | product policy allows | unchanged until backend fact | 提交修正 intent；排队/重定向语义 TBD |
| `THINKING/*` | `backend_acting` | `G10` + action label | `ACTING` | 只显示用户相关行动/进度 |
| `THINKING/ACTING/*` | `backend_waiting_confirmation` | `G10` + valid confirmation payload | `WAITING_CONFIRMATION` | `O→CONFIRMATION_MODAL` |
| `THINKING/ACTING/*` | `backend_waiting_input` | `G10` | `WAITING_INPUT` | 将问题连接到当前 Conversation |
| `THINKING/ACTING/*` | `backend_waiting_external` | `G10` | `WAITING_EXTERNAL` | 降低动态强度，不显示假进度 |
| `WAITING_CONFIRMATION` | `confirm` | confirmation current and valid | unchanged until backend fact | 禁止重复决定；提交 decision intent；不自行进入 Acting |
| `THINKING/ACTING/WAITING` | `cancel` | `G5` or explicit decline | unchanged until backend fact | 提交 cancel/decline intent；不自行宣布 Cancelled |
| active or waiting | `backend_succeeded` | `G10` | `SUCCESS` | 显示 success/partial result |
| active or waiting | `backend_failed` | `G10` | `ERROR` | 显示影响与恢复路径；技术详情默认隐藏 |
| active or waiting | `backend_cancelled` | `G10` | `CANCELLED` | 显示已取消，停止活动反馈 |
| `ERROR` | `retry` | `G8` | unchanged until backend fact | 提交 retry intent；不自行进入 Thinking |
| `SUCCESS/ERROR/CANCELLED` | new accepted backend fact | `G10` | matching projection | 开始/恢复对应用户请求 |
| terminal projection | backend clear/idle fact | current result can leave foreground | `IDLE` | 结束临时反馈；结果保留策略遵循 P |

### 9.3 Overlay transitions

| Current | Event | Guard | Next | Return target |
|---|---|---|---|---|
| `O=NONE` | `character_right_click` | `G7` | `O=ACTION_PALETTE_OPEN` | 记录当前 P |
| Palette open | `character_right_click/escape/outside_click` | — | `O=NONE` | Workspace 保留；轻量 Conversation 恢复或按用户意图保持收拢 |
| Palette root | open Character group | — | `O=CHARACTER_ACTION_PALETTE` | Palette root |
| Character group | Back | — | `O=ACTION_PALETTE_OPEN` | — |
| Character group | `character_action_selected` | action available | `O=NONE` | P/A 不变；提交角色动作 intent |
| any non-critical overlay | `backend_waiting_confirmation` | `G4, G10` | `O=CONFIRMATION_MODAL` | Base P 保留 |
| `CONFIRMATION_MODAL` | `outside_click` | — | self-transition | 不丢失、不确认 |
| Confirmation/any lower overlay | critical `backend_failed` | `G10` | `O=CRITICAL_ERROR_MODAL` | 原决定失效时不得恢复 |
| `O=NONE` + Character only | background noteworthy fact | `G9` | `O=TEMPORARY_NOTIFICATION` | 所属任务 P |
| Temporary notification | open/dismiss/complete | — | 恢复 P / `O=NONE` | 不改变 A |

---

## 10. Guard Conditions

| Guard | Condition | If false |
|---|---|---|
| `G1 Gesture resolved` | Invocation 已通过既有桌宠 gesture arbitration，且不是 Drag 或受保护 Interact 的歧义序列 | 不产生 Conversation 转换 |
| `G2 Expanded warranted` | 多轮上下文、较长可读内容、多个相关结果或持续反馈使 Capsule 不再适合；或用户主动展开 | 保持 Capsule |
| `G3 Workspace justified` | 多步骤、项目检查、多文件、持久工件、长时任务或复杂工具活动至少一项成立，且 Expanded 已不足以理解/控制 | 保持 Capsule/Expanded；回答稍长不满足 |
| `G4 Confirmation required` | 后端明确提供当前任务的 confirmation requirement、scope 与 effect | UI 不自行推断风险等级，不打开 Confirmation |
| `G5 Action cancellable` | 后端明确报告当前操作可取消，或 UI 正在表达明确拒绝尚未授权行动 | 隐藏/禁用虚假 Cancel；可提供 Collapse |
| `G6 Dismiss allowed` | 没有必须保留前景的关键决定；未提交草稿可保存 | 若不允许，则解释阻断并提供安全出口 |
| `G7 Palette allowed` | 非 Drag，且没有 Confirmation/Critical Error 抢占前景 | 忽略右键 Palette 请求或维持高优先层 |
| `G8 Retry available` | 后端提供可恢复语义与有效 Retry | 不显示 Retry，提供修改请求/Details/结束 |
| `G9 Interruptive notification warranted` | 用户安全、明确时限或立即行动需求足以打断；普通成功只 ambient notify | 合并到现有 Surface、Schwarz signal 或完全静默 |
| `G10 Current backend fact` | fact 具有有效 task correlation，且非 stale/duplicate；能够映射到当前或明确可恢复的任务 | 忽略、合并或记录为非前景结果，不替换当前任务 |

---

## 11. Entry and Exit Behaviour

| State | Entry behaviour | Focus | Exit behaviour |
|---|---|---|---|
| `CAPSULE_IDLE` | 保持与 Schwarz 的视觉锚定；恢复当前会话 | 输入框，除非由纯查看结果进入 | 保存上下文；收拢不取消任务 |
| `CAPSULE_TYPING` | 建立/恢复 draft | 文本输入 | Submit 后防重复；dismiss 保留 draft |
| `CONVERSATION_EXPANDED` | 以容器连续扩展，不模拟页面跳转 | 触发扩展的内容/输入 | Collapse 恢复 Capsule 对应焦点 |
| `WORKSPACE_OPEN` | 延续同一任务、对话与工件 | 触发 Workspace 的内容或首个任务控制 | Collapse 回 Expanded；Close 回 Character only |
| `ACTION_PALETTE_OPEN` | 锚定 Schwarz；记录 return target | Palette 首个可用项 | 恢复先前焦点，不改变 A |
| `CONFIRMATION_MODAL` | Base context 保留可读；普通输入暂停争夺焦点 | 决定标题/首个安全控制；不默认触发 Confirm | 决定提交后防重复；等待 backend fact |
| `CRITICAL_ERROR_MODAL` | 取代失效 Confirmation；保留恢复信息 | Error 摘要或首个安全恢复控制 | Dismiss 不把 Error 宣布为解决 |
| `TEMPORARY_NOTIFICATION` | 只在无更高 Surface 时出现 | 不主动抢占当前输入焦点 | 自动结束或用户打开；A 不受影响 |

焦点必须始终位于最高优先且可见的交互层；关闭该层后恢复到仍可见且仍有效的前一目标。任何被遮挡、已关闭或已失效的控件不得保留输入所有权。

---

## 12. Cancellation Model

Cancellation 是一条显式用户意图链，而不是 UI 本地状态捷径：

```text
User chooses Cancel
→ UI validates cancellability / decision context
→ UI submits cancel or decline intent
→ UI prevents duplicate intent and shows pending acknowledgement
→ backend emits a new integration fact
→ UI projects Cancelled, Error, Success, Acting or Waiting as actually reported
```

- **Thinking**：必须提供取消意图入口；UI 不保证后端已经停止。
- **Acting**：仅在后端 signal 说明当前可取消时提供 Cancel；否则解释“当前不可取消”并保留 Collapse/Inspect。
- **Waiting Confirmation**：Cancel/Not now 表示拒绝当前决定；是否等价于取消整个任务由 confirmation contract 表达，UI 不猜测。
- **Waiting Input / External**：可取消性同样由后端 signal 决定。
- **Dismiss / Collapse / Workspace close**：永远不发送 cancel intent。
- **Cancellation acknowledgement**：只有 `backend_cancelled` 才进入 `AGENT_CANCELLED`；若动作在取消请求前已完成，UI 必须呈现真实 Result。
- **Side effects already occurred**：取消意图与已发生副作用之间的产品文案和恢复契约为 `TBD`。

---

## 13. Escape and Dismiss Semantics

Escape 只处理当前最高优先、可退出的层；一次按键最多退一级。

| Active context | Escape | Outside click |
|---|---|---|
| Critical Error | 按其明确安全出口 dismiss/collapse；不得宣称解决 | No effect |
| Confirmation | 默认等同 Cancel / Not now；存在必须明确选择的例外时为 `TBD` | No effect |
| Character action group | 回到 Palette root | Dismiss whole Palette |
| Palette root | Dismiss Palette | Dismiss Palette |
| Workspace | `Workspace → Expanded` | No effect |
| Expanded Conversation | `Expanded → Capsule` | No effect |
| Capsule with draft | `Capsule → Character only`，draft 保留 | Dismiss 并保留 draft |
| Empty Capsule | `Capsule → Character only` | Dismiss |
| Temporary Notification | Dismiss | Dismiss |
| Character only + active task | 无可见层可退；不取消任务 | No effect |
| Character Dragging | `TBD`：需与既有 Drag cancel 语义一致 | Not applicable |

显式 Close 与 Escape 都遵守 `Dismiss Is Not Cancel`。如果关闭会隐藏正在等待确认或输入的任务，Schwarz 必须保留 Waiting signal 和恢复入口。

---

## 14. Input Priority and Ownership

同一时刻输入按以下优先级解释：

```text
Active character drag
> Critical Error / Confirmation
> Active Palette or temporary Overlay
> Text composition and focused input
> Focused primary Surface controls
> Character invocation candidates
> Hover feedback
```

1. Drag 一旦成立，同一指针序列不能再被解释为 click、double click、Interact 或 Conversation Invocation。
2. Confirmation 只接受决定相关输入；Enter 只有在 Confirm 控件已被用户显式聚焦时才可确认，不能依赖模糊默认。
3. 文本输入与 IME composition 拥有 Enter；`Shift+Enter` 换行，`Enter` 在 composition 结束且请求有效时 Submit。
4. Palette 打开时，outside click 只关闭 Palette，不把同一次点击透传为 Schwarz 的新动作。
5. 用户在 Thinking/Acting 时再次输入，不得静默取消当前任务；系统提交补充/新请求的具体归属为 `TBD`。
6. Primary Invocation 在活动任务中只恢复对应 Surface，不创建第二个独立上下文。

## 15. Re-entry Rules

Re-entry 的目标是恢复用户正在做的事，而不是重置或复制状态。

| Situation | Re-entry result |
|---|---|
| Capsule 已打开时再次触发 Primary Invocation | Focus existing Capsule；不得创建第二个 Capsule。是否 toggle-collapse 为 `TBD` |
| Expanded 已打开时再次触发 | Focus current input/context；不收缩 |
| Workspace 已打开时再次触发 | Focus Workspace Conversation 区域；不叠加 Capsule |
| UI 已收拢但 A=Thinking/Acting/Waiting | 恢复该任务最后有效层级；若层级不可恢复，至少打开 Expanded |
| UI 已收拢且 A=Success/Error/Cancelled | 打开对应 Result；不伪造新任务 |
| Palette 打开时左键 Schwarz | Dismiss Palette，再按已确认的 invocation/Interact 映射处理；同一点击是否继续触发为 `TBD`，不得双重执行 |
| Confirmation/Critical Error 在前景 | Primary Invocation 不绕过 Overlay；focus existing decision/error |
| 快速重复 invocation | 合并为一次 open/focus；不得多建 Surface 或多次 Submit |
| stale backend result arrives | 不抢占当前任务；合并为可恢复结果或 ambient signal |

---

## 16. Global Invariants

以下规则在所有状态、事件和未来 Screen Specification 中必须成立：

1. **Character anchor**：Schwarz 是持久入口；除显式 Hide/Quit 外，收拢目标为 Character only。
2. **Exactly one Presentation**：`P` 同时且只能有一个稳定状态。
3. **Projection independence**：P 的打开/关闭不得直接决定 A；A 的变化不得无条件强开大型 UI。
4. **One foreground Overlay**：同一时刻最多一个前景 Overlay；高优先层替代、合并或压低低优先层。
5. **Dismiss is not Cancel**：任何 dismiss/collapse/close 都不得隐式发送 cancel。
6. **Drag wins**：合法 Drag 高于 click、double click、Interact 与 Conversation Invocation。
7. **No ambiguous gesture capture**：未解决的鼠标语义不得静默偷取、重解释或遮蔽既有桌宠 gesture。
8. **Workspace is guarded**：Workspace 只能因明确复杂度或用户主动动作进入；长回答本身不充分。
9. **Backend truth**：Thinking/Acting/Waiting/Success/Error/Cancelled 只能由有效 backend fact 投影。
10. **No backend redesign**：UI 不推断 planning、routing、scheduling 或 execution lifecycle，也不合成 backend transition。
11. **Explicit confirmation**：outside click、timeout、默认焦点或 Surface 消失都不得等同 Confirm。
12. **Single result truth**：同一 task projection 不能同时显示 Success、Error 与 Cancelled。
13. **No orphan Overlay**：Confirmation/Critical Error 必须关联有效 task 与 Base context。
14. **Context continuity**：Capsule → Expanded → Workspace 是同一任务/会话连续变形，不是新页面导航或新会话。
15. **No tool noise**：低层 tool name、MCP、raw API、内部命令、token/runtime 信息不进入默认 UI 状态。
16. **Recoverable hidden work**：A 活动而 P=Character only 时，Schwarz 必须表达状态并提供恢复路径。
17. **Temporary states terminate**：Hover、Palette、Notification、Success/Error 动态反馈均有明确退出或稳定降级路径。
18. **Focus remains valid**：焦点只能属于最高、可见、可操作的层；关闭后恢复到有效目标。
19. **Current facts only**：stale、duplicate 或错误关联的 backend event 不得替换当前任务表现。
20. **Accessible equivalence**：任何仅靠 Drag 或 Hover 暴露的必要功能都必须有非 Drag/非 Hover 可访问替代；具体方案 `TBD`。

---

## 17. Forbidden State Combinations and Transitions

| Forbidden condition | Reason |
|---|---|
| Capsule + Expanded + Workspace 任意两个同时作为主 P | 违反单一 Presentation 与 Progressive Disclosure |
| 两个 Workspace 或两个 Capsule | 破坏 re-entry 与任务归属 |
| Palette + Confirmation / Critical Error | 低优先动作不能遮蔽决定或关键错误 |
| 两个前景 Overlay 同时围绕 Schwarz | 造成 Surface 堆叠与输入歧义 |
| 同一指针序列同时产生 Drag 与 Click/Double Click | 侵犯现有桌宠 gesture |
| `A=SUCCESS` 与 `A=ERROR/CANCELLED` 同属于同一 task | 相互矛盾的用户事实 |
| `A=ACTING` 与 `A=CANCELLED` 同属于同一 task | 已停止与正在行动矛盾 |
| `A=LISTENING` 且 `P=CHARACTER_ONLY` | 没有可接受输入的 Surface；required input 应投影 Waiting Input |
| Confirmation Modal 无当前 `A=WAITING_CONFIRMATION` | 形成无来源授权请求 |
| Critical Error Modal 无当前 `A=ERROR` | 形成虚假阻断状态 |
| Workspace 在 `G3` 未通过时自动打开 | 把简单任务升级为大型窗口 |
| A 活动但 Character only 无任何状态/恢复信号 | 用户无法感知或返回任务 |
| dismiss/collapse transition 同时发 cancel | 混淆 UI 可见性与任务控制 |
| UI 因 Submit/Confirm/Retry 本地进入 Acting/Success/Error | 越过后端事实边界 |
| raw single/double click 在 gesture 冲突解决前打开 Conversation | 绕过 01/02 的设计门禁 |

---

## 18. Canonical Flows

流程中的 `backend_*` 仅表示 UI 接收到 integration fact；它们不描述后端内部路径。

### Flow A — Simple Conversation

```text
(Character only, Idle, Neutral, None)
→ primary_conversation_invoked [G1]
→ (Capsule idle, Listening, Neutral, None)
→ text_input_started
→ (Capsule typing, Listening, Neutral, None)
→ submit [request intent; A unchanged until backend fact]
→ backend_thinking
→ (Capsule, Thinking, Neutral, None)
→ backend_succeeded
→ (Capsule, Success, Neutral, None)
→ continue typing / collapse
→ Capsule Listening / Character only with result signal
```

### Flow B — Open Desktop Application

```text
Desktop idle
→ Primary Invocation
→ Capsule + Listening
→ submit “Open VS Code”
→ backend_thinking
→ Thinking
→ backend_acting “Opening VS Code…”
→ Acting + informational Action Surface
→ backend_succeeded / backend_failed
→ Result in Conversation
→ continue / collapse to Character only
```

简单打开动作可短暂显示 cancel only if cancellable；若完成很快，不制造多阶段低层 progress。

### Flow C — Confirmation Required

```text
Conversation + Listening
→ submit request
→ backend_thinking
→ Thinking
→ backend_waiting_confirmation [valid scope/effect]
→ (same P, Waiting confirmation, Neutral, Confirmation modal)
→ Confirm [decision intent; no local Acting transition]
→ backend_acting
→ (same P, Acting, Neutral, None)
→ backend_succeeded
→ Success Result
```

Cancel/Not now 提交拒绝意图；最终投影取决于后续 backend fact。

### Flow D — Character Action

```text
Desktop idle
→ character_right_click [G7]
→ Action Palette
→ open Character group
→ Character Action Palette
→ select Sit
→ submit character-action intent
→ Palette dismiss
→ Character only; A remains Idle
```

角色动作不伪装为 Agent tool activity，也不改变 Agent projection。

### Flow E — Complex Agent Task

```text
Capsule + Listening
→ submit complex request
→ backend_thinking
→ Capsule + Thinking
→ G2 becomes true
→ Expanded Conversation + Thinking/Acting
→ G3 becomes true or user explicitly opens
→ Workspace + current A projection
→ backend acting/waiting facts
→ semantic task progress / required decisions
→ backend success/partial/error
→ structured Result in Workspace
→ Workspace collapse
→ Expanded Conversation
→ Capsule
→ Character only
```

每次 collapse 都只改变 P；任务投影和工件不会因 UI 收拢而被取消或丢弃。

---

## 19. Edge Cases

| Case | Product-level behaviour |
|---|---|
| Capsule 已打开时再次点击 Schwarz | 若该输入最终映射为 Primary Invocation，则 focus existing Capsule；是否 toggle-collapse 为 `TBD`；绝不创建第二个 Capsule |
| Action Palette 已打开时左键 Schwarz | Palette 先 dismiss；该点击是否继续产生 Interact/Invocation 为 `TBD`，不得同时触发两项 |
| Agent Acting 时用户再次输入 | 允许编辑 draft；提交后的补充/新任务归属为 `TBD`，不得静默取消或改写当前动作 |
| Thinking 时用户关闭 Surface | `P→CHARACTER_ONLY`，`A=THINKING` 保持；Schwarz 表达 Thinking 并提供恢复入口 |
| Workspace 打开时 Schwarz 被拖动 | `C→DRAGGING`；Workspace 保持，Palette dismiss；不移动 Workspace、不取消任务 |
| Confirmation 长时间未响应 | 不自动 Confirm；维持 Waiting 或收拢为可恢复信号；expiry/提醒由 backend contract 提供，策略 `TBD` |
| Error 后用户继续输入 | 允许修改请求；Error 作为上下文保留，直到新 backend fact；不把输入视为自动 Retry |
| 工作过程中 UI 手动收起 | P 变 Character only，A 不变；Schwarz 显示状态，完成后按 Notification guard 反馈 |
| 用户快速重复点击角色 | gesture arbitration 合并；不重复打开、提交或触发角色动作；single/double 语义仍为阻断性 TBD |
| Cancel 与 completion 接近同时发生 | UI 以 task-correlated backend fact 为准，不假设 Cancel 必然成功；只呈现一个真实终态 |
| stale task result 到达 | 不抢占当前 Surface；转为可恢复结果或 ambient signal，不覆盖当前任务 |
| Confirmation 期间 backend 报错 | 原 Confirmation 失效；`A→ERROR`，`O→CRITICAL_ERROR_MODAL` only if critical |
| Palette 打开期间 backend 需要确认 | Confirmation 抢占并关闭 Palette；任务 context 保留 |
| Character only 下后台任务完成 | 普通完成 ambient notify；重要结果 small temporary surface；只有安全/时限事件才打断 |

---

## 20. Unknown / TBD

以下问题尚未被上位文档确认，不得由实现层自行决定：

1. **Blocking — mouse gesture mapping**：single click Interact 与 double click Capsule 如何仲裁；最终 `primary_conversation_invoked` 绑定什么输入。
2. Active Drag 下 Escape 是否取消 Drag，以及如何与现有桌宠语义一致。
3. Hover 反馈的具体延迟、持续时间与动画映射。
4. 已开 Capsule 再次 Invocation 是只 focus 还是 toggle-collapse。
5. Capsule 第一版 attachment/context 与 voice entry 的具体交互和可用性。
6. Capsule 自动扩展的内容阈值，以及何时只提示用户主动 Expand。
7. Acting/Thinking 中再次 Submit 属于 correction、queue、new task 还是需要用户选择；后端只需提供可支持的 integration contract。
8. 后端 cancellability signal 的更新时机与用户可见语义；不涉及后端实现。
9. Escape 等同 Cancel/Not now 的 Confirmation 例外类型。
10. Success/Error/Cancelled feedback duration 与 projection clear-to-idle contract。
11. Confirmation expiry、Waiting External 恢复与提醒策略所需 signal。
12. 隐藏任务的 badge-like signal 是否需要及其聚合规则。
13. 是否以及何时使用操作系统 notification。
14. 多任务并存时 UI 的 foreground task selection、结果归属与恢复顺序；不定义后端调度。
15. Draft 与 Conversation history 跨重启 persistence。
16. Action Palette 最终标签、Character action availability、Hide/Quit 安全行为及传统菜单迁移期。
17. Global shortcut：`Shortcut: TBD`。
18. 所有 Drag/Hover 专属功能的非 Drag、非 Hover 可访问替代。
19. 各 projection 与 Schwarz 动画、Surface motion 的最终视觉映射。
20. Cancel intent 发出时已发生副作用的说明与恢复语义。

---

## 21. Explicit Non-goals

本文不设计或决定：

- Agent backend architecture 或 backend state machine；
- Agent planning、tool routing、execution scheduling、task orchestration、memory；
- MCP、tool protocol、raw API 或 backend lifecycle；
- Qt class hierarchy、QWidget、QML、signals/slots；
- Windows HWND、Z-order implementation、native event handling；
- event loop、threading、race-condition implementation；
- animation implementation、exact geometry、pixel sizes；
- color、typography、icon 或 final visual assets；
- Agent backend、API architecture、persistence architecture；
- permission-system implementation；
- Design System、Screen Specification 或 TDD。

Region、State、Event、Guard、Entry/Exit 在本文中都是 UX contract；后续实现不得把产品名称视为强制代码结构。

---

## 22. Consistency Review

| Review item | Result | Evidence / correction |
|---|---|---|
| 符合 `01-ui-vision.md` | Pass with one carried TBD | Character First、UI on Demand、gesture invariant 均为全局不变量；single/double 冲突未擅自解决 |
| 符合 `02-interaction-model.md` | Pass | 四 Region、Surface priority、dismiss/cancel、五条流程均落实为状态契约 |
| 未变成传统 Chat App | Pass | 无 permanent input/history/sidebar；Character only 是收拢基线 |
| 没有过多永久 UI | Pass | 只有 Schwarz 持久；所有 Surface 有退出路径 |
| Character First 真正成立 | Pass | Schwarz 是入口、投影载体、隐藏任务恢复入口 |
| UI on Demand 真正成立 | Pass | Surface 由明确 Event/Guard 进入 |
| Progressive Disclosure 清晰 | Pass | Capsule/Expanded/Workspace 互斥且由 `G2/G3` 控制 |
| Surface 冲突已定义 | Pass | Overlay 单一前景、优先级、禁配与 return target 明确 |
| 退出与收起清楚 | Pass | Escape、outside click、collapse、close 分层且不等于 cancel |
| UI 与 Agent 状态分离 | Pass | P 与 A 正交；A 只消费 backend facts |
| 未重设计 Agent backend | Pass | 不定义 planning/routing/scheduling/lifecycle；只列 required signals |
| 取消模型可验证 | Pass | intent → acknowledgement → projection，UI 不宣布后端结果 |
| 重复/乱序输入有规则 | Pass | repeat policy、`G10`、re-entry 与 stale event 规则明确 |
| 未过早进入视觉设计 | Pass | 无尺寸、颜色、token、最终动画/asset |
| 未过早进入工程实现 | Pass | 无 Qt、类、API、线程或事件循环设计 |

### Review conclusion

本文可作为后续 UI controller ownership、transition tests 与 manual acceptance tests 的产品依据，但在实际绑定角色鼠标入口前，必须先解决第 20.1 项 gesture mapping。除此之外，没有发现 `01`、`02` 与本文之间的新冲突。

下一阶段建议先以一次独立产品决策解决 mouse gesture arbitration，再进入 Screen Specification / state ownership refinement；本文不自动创建任何下一阶段文件。
