# ArkClaw Interaction Freeze & Low-Fidelity Prototype Review

> 阶段：Phase 6 — Frontend Product Design Freeze  
> 文档类型：Canonical Product Design Freeze / Engineering Handoff Gate  
> 上位输入：`docs/product/01-ui-vision.md`、`02-interaction-model.md`、`03-ui-state-machine.md`、`04-ui-design-system.md`、`docs/design/05-ui-screen-spec.md`  
> 下游用途：`docs/engineering/07-frontend-ui-architecture-tdd.md` 及后续实现规划  
> 权威级别：01–05 与本文冲突时，以本文为准；07 不得反向推翻本文  
> 本文不包含：代码、Qt/QML/QSS、工程架构、Agent backend redesign 或 high-fidelity visual design

## 1. Purpose

本文是 ArkClaw 当前阶段唯一有效的 **Frontend Product Design Freeze**。它把 01–05 中经过讨论、演进和原型验证的内容收敛为工程应该相信的最终交互合同。

本文冻结：

- Character Interaction 与 Agent Conversation 的概念边界；
- Schwarz 的 Left Click、Drag、Right Click 与 Double Click 语义；
- Conversation Capsule 的 Primary、Fast 与 Secondary Entry；
- Outside Click、Escape、Draft Preservation 与 Focus Restoration；
- Action Palette 的层级、迁移边界与 capability parity；
- Capsule two-state、anchoring、Activity → Result 与 Surface priority；
- Engineering TDD 必须遵守的产品不变量和 integration requirements。

本文中的 low-fidelity prototype 是文档化 state/logic walkthrough，不是观察性用户研究，也不是可运行或高保真原型。它验证规则是否唯一、一致、可退出且不破坏既有桌宠体验。

### 1.1 Canonical authority

工程阅读顺序为：

```text
01 Vision
→ 02 Interaction Model
→ 03 UI State Machine
→ 04 Design System
→ 05 Surface Specification
→ 06 Frontend Product Design Freeze
→ 07 Frontend Engineering TDD
```

如果 01–05 中的讨论性、候选性或旧结论与本文冲突，本文是唯一 active authoritative contract。07 负责解释如何实现本文，不得改变本文的产品语义。

### 1.2 Agent architecture boundary

本文引用的 Thinking、Acting、Waiting、Success、Error 与 Cancelled 都是 backend runtime facts 的 presentation-level projections。

本文不得定义或复制 Agent backend 的 planning、tool routing、execution scheduling、memory、orchestration、MCP 或 task lifecycle。前端所需信息只能记录为 integration contract / required signal，不规定后端如何产生。

---

## 2. Final Freeze Summary

```text
Character interaction
Left Click Schwarz
→ Interact only

Character movement
Drag Schwarz
→ existing Drag / release / landing only

Contextual actions
Right Click Schwarz
→ Anchored Action Palette

Primary Agent conversation
Action Palette
→ Ask ArkClaw
→ Conversation Capsule

Fast Agent conversation
Keyboard Shortcut
→ Conversation Capsule
Shortcut: TBD

Secondary Agent conversation / recovery
Existing Control Center / tray access

Double Click
→ Not Defined / Reserved
```

### 2.1 Confirmed constraints

1. Schwarz 是 resting state、primary visual anchor 和持续状态载体。
2. Character-only、Capsule、Expanded Conversation 与 Workspace 是互斥主 Presentation。
3. 同时最多一个 foreground Overlay。
4. Dismiss、Collapse 与 Close 不等于 Cancel。
5. Left Click 的语义在所有 Surface 和 Agent projection 中保持 Interact。
6. Drag 一旦成立，同一 pointer sequence 不能再成为 Click、Interact、Conversation 或 Palette。
7. Right Click 只打开 Palette；Conversation 需要第二个明确的 `Ask ArkClaw` command。
8. Confirmation / Critical Error 高于 Palette 和普通 Conversation。
9. Agent projection 只能由有效 backend fact 改变。
10. Context/Voice、exact dimensions、visual tokens 与 motion duration 不在本文冻结。

### 2.2 Repository-verified current behaviour

只读仓库核验确认：

- completed left-click release currently requests `ProductionAction.INTERACT`；
- Drag 是独立的既有 pointer sequence，并包含既有 release / falling / landing 行为；
- pet right-click menu 当前包含 Pause/Continue、Always on top、Start with Windows、active role identity、Relax、Move Left/Right、Sit、Sleep、Special、Interact、Resume Autonomous、Open ArkClaw Control Center、Exit；
- tray 另有 Hide/Show Pet，并复用大部分 production actions；
- Exit 使用现有 safe-exit path。

这些事实是 regression baseline，不是重写现有桌宠核心的许可。

---

## 3. Character Interaction vs Agent Conversation

Schwarz 同时是角色与 Agent 的视觉载体，但 Character Interaction 和 Agent Conversation 是两个不同的 interaction domain。

| Domain | User intent | Primary entry | Result |
|---|---|---|---|
| Character Interaction | 与 Schwarz 角色本身互动 | Left Click Schwarz | Existing `Interact` semantic |
| Agent Conversation | 向 ArkClaw 表达目标、问题或任务 | Palette → Ask ArkClaw | Open/restore Conversation Capsule |

正式定义：

- `Interact` 不等于 Chat、Ask 或 Agent request。
- Character click 不承担 Conversation Surface 的打开、恢复、聚焦、切换或提示职责。
- Conversation 是 Agent-domain interaction，必须由独立、明确的入口触发。
- Character First 不意味着所有功能共用角色单击；它要求入口与状态仍围绕 Schwarz 建立。
- Conversation First 表示自然语言是 Agent 能力的主要协议，不表示可以覆盖既有 Character gesture。

---

## 4. Mouse Gesture Contract

## 4.1 Left Click Schwarz

### Frozen contract

```text
A completed non-drag left-click gesture on Schwarz
→ exactly one existing Interact request
→ zero Conversation invocation
```

产品语义：

```text
Left Click Schwarz → Interact only
```

不得实现：

- Left Click 打开、恢复、聚焦或 toggle Capsule；
- Left Click 同时执行 Interact 与 Conversation；
- Left Click 完成 Interact 后自动出现 `Ask ArkClaw` affordance；
- 根据 Capsule、Workspace 或 Agent state 改变 Left Click 的主语义；
- 为其他鼠标语义延迟、吞掉、重复或重新解释普通 Interact。

### State consistency

| Current state | Left Click Schwarz result |
|---|---|
| Character-only | Interact once；no Surface |
| Capsule visible | Interact once；Capsule/draft/focus ownership unchanged |
| Expanded Conversation | Interact once；Conversation context unchanged |
| Workspace | Interact once；Workspace/task unchanged |
| Palette open | Interact once；Palette dismisses；no Conversation opens |
| Thinking / Acting / Waiting | Interact once；Agent task and projection continue |
| Confirmation / Critical Error | Interact once；higher-priority Surface remains authoritative |

`Palette open + Left Click Schwarz` 是显式 Character-target rule，不是 generic outside-click pass-through。工程结果必须是一次 Interact 和一次 Palette dismiss，而不是吞掉 Interact、执行两次命令或打开 Conversation。

## 4.2 Click vs Drag

Click 与 Drag 是互斥终局：

```text
Pointer sequence begins
├─ released before existing Drag recognition
│  → Click → Interact
└─ existing Drag recognized
   → move Schwarz
   → release / existing landing
   → no Interact / Conversation / Palette
```

- 保留现有 platform threshold 与 gesture transaction；本文不定义数值。
- 一旦成为 Drag，同一 sequence 不得再降级或升级为 Click。
- Drag release 不补发 Interact。
- Drag 中 Right Click 不打开 Palette。
- Drag 不取消 Agent task，也不清除 draft。
- Palette 在 Drag 开始时 dismiss。
- Expanded/Workspace 保持原位置；包含 draft 或 active task 的 Conversation 保持可恢复且不随角色跳动。
- Drag 完全结束后的新独立 click 正常执行 Interact。
- Active Drag 下 Escape 保持现有语义；本文不新增 drag-cancel 行为。

## 4.3 Right Click Schwarz

```text
Right Click Schwarz → Anchored Action Palette only
```

Right Click 本身不触发 Interact、Conversation、Character action 或 Agent action。

| Situation | Result |
|---|---|
| Palette closed, no blocking Surface | Open one Palette |
| Palette enter transition active | Coalesce repeated invocation；no flicker/duplicate |
| Palette stable + distinct Right Click | Dismiss Palette and restore valid return target |
| Capsule visible | Temporarily hide Capsule；preserve draft/focus return；open Palette |
| Workspace visible | Workspace remains stable；Palette may open conditionally |
| Confirmation / Critical Error | Do not open Palette；retain/refocus higher Surface |
| Active Drag | No Palette |

## 4.4 Double Click and repeated Left Click

Double Click 的最终状态是：

```text
Not Defined / Reserved
```

- Double Click 不打开 Conversation，也不拥有第二个产品语义。
- 每个被现有 gesture transaction 确认为 completed non-drag click 的输入继续遵守 Interact contract。
- 不为识别 Double Click 延迟 single-click Interact。
- 不增加 Conversation-specific rapid-click coalescing。
- 未来若赋予 Double Click 新语义，必须重新打开产品 gesture gate，并标记 `Engineering Validation Required`。

## 4.5 Mixed input

| Sequence | Frozen result |
|---|---|
| Repeated completed Left Click | Existing Interact requests；zero Conversation Surface |
| Rapid Right Click during Palette enter | One Palette open result |
| Distinct Right Click after Palette stable | Dismiss Palette |
| Left Click Schwarz while Palette open | One Interact + Palette dismiss；zero Conversation |
| Right Click after Capsule open | Hide Capsule temporarily；open Palette；preserve draft/return target |
| Click candidate from same Drag sequence | Forbidden / suppressed |
| New Left Click after Drag fully ends | Normal Interact |

---

## 5. Conversation Entry Model

## 5.1 Candidate assessment

| Candidate | Actions to focused Capsule | Discoverability | Expert efficiency | Conflict risk | Product alignment | Decision |
|---|---:|---|---|---|---|---|
| Palette → Ask ArkClaw | 2 | Medium；Palette 内明确 | Medium | Low after right-click parity | High | **Primary** |
| Keyboard Shortcut | 1 | Low unless taught | Very high | Medium until key chosen | High | **Fast** |
| Hover Ask affordance | 1 click after hover | Pointer-dependent | Medium | Medium/High around hit region | Conditional | Not approved |
| Interact-completion Ask affordance | 2 | Medium | Low/Medium | High；pollutes Interact-only | Low | Rejected |
| Existing Control Center | Existing menu/tray path | Medium | Low/Medium | Low for pet gesture | Valid only as fallback | **Secondary** |
| Double Click Schwarz | 1 compound gesture | Low/Medium | High if learned | Critical with Interact/Drag | Low | Reserved |
| Permanent button/input | 1 | High | High | Low gesture conflict, permanent clutter | Fails Calm Desktop | Rejected |

## 5.2 Primary Conversation Entry

```text
Right Click Schwarz
→ Anchored Action Palette
→ Ask ArkClaw
→ Palette dismisses
→ existing Conversation context restores, or one Capsule opens
→ input receives focus when safe
```

`Ask ArkClaw` 必须是 Palette root 的直接顶层 command，不得藏入 Character、System、generic Actions library 或第三层菜单。

这一入口需要两个明确动作，是保护 Character click 所必须接受的成本。不能用 gesture ambiguity 换取表面上的一步到达。

## 5.3 Fast Conversation Entry

```text
Keyboard Shortcut
→ existing Conversation Surface restores, or Capsule opens
→ input receives focus when safe
```

`Shortcut: TBD`

Fast Entry 的产品方向已批准；具体 key combination、Global/Local scope、冲突验证和教学方式尚未冻结。它不是唯一或主要可发现入口，也不得绕过 Confirmation/Critical Error。

## 5.4 Secondary Conversation Entry

Existing Control Center / tray access 保留 secondary、legacy 与 recovery role。它可以进入现有 Agent conversation 或 task context，但：

- 不取代 Capsule；
- 不成为默认 Workspace；
- 不成为 ArkClaw 的产品主入口；
- 不授权永久主窗口、输入框或状态面板。

## 5.5 Rejected / reserved entries

- Left Click：永久保留给 Interact，除非未来有新的明确产品决定。
- Double Click：`Not Defined / Reserved`；no Conversation。
- Hover-only Ask：关键入口不能只依赖 Hover；新增 hit region 也未通过手势门禁。
- Interact-completion Ask：会让 Character click 产生 Agent UI 副作用，Rejected。
- Permanent Ask button、chat bubble、input：违反 Character First、Calm Desktop 与 UI on Demand。

## 5.6 Entry availability

在 Action Palette 完成 production parity migration 前，Existing Control Center 可以继续作为兼容入口，但不改变最终 Primary Entry。Primary Entry 上线必须与 Palette focus、Surface exclusivity、draft return 和 capability parity 一起启用；同一次 Right Click 不得同时打开 native menu 与 Palette。

---

## 6. Outside-click Contract

Outside Click 只作用于最高可 dismiss transient Surface；它不透传为底层 Character action，也不发送 Cancel、Confirm 或 Submit。

| Active context | Outside-click result | Data/task effect |
|---|---|---|
| Character-only | No ArkClaw UI effect | None |
| Capsule empty, no active task | Collapse to Character-only | None |
| Capsule with draft | Collapse to Character-only | Preserve draft and editing position |
| Capsule with Thinking/Acting | Collapse when allowed | Task continues；Schwarz carries projection |
| Expanded Conversation | Keep open | No effect |
| Workspace | Keep open | No effect |
| Palette root/secondary layer | Dismiss Palette；restore valid return target | No command executed；no pass-through |
| Temporary Details | Close Details only | Base remains |
| Passive/Ambient Notification | Dismiss Surface | Result/task remains recoverable |
| Confirmation | No effect | No Confirm/Cancel intent |
| Critical Error | No effect | Error remains unresolved |

### 6.1 Draft decision

有 draft 的 Capsule 使用以下唯一合同：

```text
Outside Click
→ Capsule collapses
→ draft and valid editing position are preserved
→ outside target keeps focus
```

这同时满足 Calm Desktop 与 Draft Safety。再次恢复 draft 必须使用 approved Conversation Entry，而不是 Character Left Click。

---

## 7. Escape Contract

Escape 与 Outside Click 分开定义。一次 Escape 最多处理一个最高优先、允许 Escape 的层级。

```text
Critical Error Details
> Critical Error Surface
> Confirmation
> Palette secondary layer
> Palette root / transient Details
> Workspace local layer
> Workspace
> Expanded Conversation
> Capsule
> Character-only
```

| Current context | Escape result |
|---|---|
| Critical Error + Details | Close Details；keep Error |
| Critical Error summary | Collapse to Character Error signal；not resolved |
| Confirmation | Submit Cancel / Not now intent；never approve |
| Character/System Palette layer | Return to Palette root |
| Palette root | Dismiss；restore valid return target/focus |
| Other transient Details | Close Details only |
| Workspace local Overlay | Close local Overlay first |
| Workspace | Collapse to Expanded Conversation |
| Expanded Conversation | Collapse to Capsule |
| Capsule empty | Collapse to Character-only |
| Capsule with draft | Collapse and preserve draft |
| Character-only + active task | No effect；never Cancel task |
| Active Drag | No new Phase 6 action；preserve existing semantics |

Escape is always a refusal/defer path for Confirmation, never approval. If the integration contract does not provide a valid decline semantic, UI must not invent one or fall through to Confirm.

---

## 8. Draft Preservation Contract

## 8.1 Draft ownership

One Conversation context owns at most one current unsent draft。Capsule、Expanded Conversation 与 Workspace 显示同一 draft，不复制。

A draft exists after a committed, non-empty user edit。Active IME composition must not be submitted or destroyed by Surface transitions；exact composition handling belongs to Engineering TDD。

## 8.2 Persistence matrix

| Event | Draft result | Surface/focus result |
|---|---|---|
| Left Click Schwarz | Preserve | Interact；no draft/focus/visibility mutation |
| Outside Click | Preserve | Capsule collapses；outside target keeps focus |
| Escape from Capsule | Preserve | Character-only |
| Manual collapse | Preserve | Character-only |
| Palette opens | Preserve | Capsule hides；Palette owns focus |
| Palette dismisses without navigation | Preserve | Restore prior Capsule and semantic edit target |
| Palette → Ask ArkClaw | Preserve/restore same context | Capsule/Conversation opens；focus input |
| Character action selected | Preserve | Restore prior Conversation target when still valid |
| Schwarz Drag | Preserve | Meaningful Surface remains stable；no submit |
| Expanded/Workspace opens | Preserve and transfer same draft | Destination Conversation input |
| Accepted exact Submit snapshot | Submitted snapshot ceases to be draft | Request remains correlated |
| Thinking/Acting without this draft submit | Preserve | Remains editable |
| Application focus loss | Preserve | No auto-submit/discard |
| Hide / temporary UI loss | Preserve in current session | Restore later |
| Agent task Cancel/Error | Preserve separate unsent draft | Task control does not own draft |

## 8.3 Allowed destruction

Draft can be destroyed only by：

1. successful acceptance of the exact submitted snapshot；
2. explicit `Clear draft` / `Discard draft` user action；
3. an explicit safe Quit flow in which the user knowingly chooses to discard an unsent draft。

Escape、Outside Click、Collapse、Palette、Drag、Interact、task Cancel、Error 和 focus loss are never discard actions。

Cross-restart persistence mechanism remains non-blocking。Before such persistence exists, Quit with draft must preserve it or obtain explicit discard confirmation。

---

## 9. Action Palette Freeze

## 9.1 Migration principle

Action Palette replaces presentation and grouping, not existing command semantics：

```text
verified existing command meaning
→ same user outcome
→ new anchored grouped presentation
```

No existing capability is removed by this freeze。Right-click cutover replaces the native menu atomically；one Right Click must never produce both presentations。

## 9.2 Frozen hierarchy

```text
╭────────────────────────────────────╮
│ Ask ArkClaw                        │  direct
│ Current Task             (if any)  │  Return / valid Cancel
│ Character                         › │  same-shell secondary layer
│ System                            › │  same-shell secondary layer
╰────────────────────────────────────╯
```

No generic Agent tool library is added。Agent actions remain Conversation requests or current-task controls。

### Character layer

```text
╭────────────────────────────────────╮
│ ‹ Character · Schwarz              │
│ Pause / Continue                   │
│ Resume Autonomous       (if valid) │
│ Relax                              │
│ Sit                                │
│ Sleep                              │
│ Interact                           │
│ Special                            │
│ Move                 [Left] [Right]│
╰────────────────────────────────────╯
```

Left Click remains the primary Interact entry。Palette 保留 `Interact` 作为 secondary / explicit command，以满足 current capability parity、文字可发现性与键盘可达性。两者必须指向同一个 existing command semantic，不重复实现。

### System layer

```text
╭────────────────────────────────────╮
│ ‹ System                           │
│ Always on Top                 [✓]  │
│ Start with Windows             [ ] │
│ Open ArkClaw Control Center         │
│ Hide Schwarz                       │
│ Quit                               │
╰────────────────────────────────────╯
```

Direct `Settings` 只有在 capability mapping 完成后才能替换或补充 Control Center。Quit 保留现有 safe-exit 与 draft protection。

## 9.3 Verified capability destination

| Current capability | Frozen destination |
|---|---|
| Pause / Continue | Character layer |
| Relax / Sit / Sleep / Special | Character layer |
| Move Left / Right | Character layer one labeled row；no third-level submenu |
| Interact | Left Click primary + Character layer secondary |
| Resume Autonomous | Character layer conditional |
| Role identity | Character heading；context, not command |
| Always on Top | System layer；preserve checked state |
| Start with Windows | System layer；preserve checked/busy state |
| Open ArkClaw Control Center | System layer legacy access |
| Hide / Show | Hide in Palette；Show remains reachable from tray |
| Exit | System `Quit`；existing safe-exit path |

## 9.4 Navigation and dismiss

```text
Right Click → Root
Root → Character/System same-shell layer
Secondary layer + Back/Escape → Root
Root + Escape/Outside Click/distinct Right Click → dismiss + return target
Root + Ask ArkClaw → dismiss → Conversation open/restore → focus input
```

- Palette and Capsule are never simultaneously visible around Schwarz。
- Selecting Character command dismisses Palette and executes exactly one existing semantic command。
- Outside Click dismisses without pass-through。
- Left Click directly on Schwarz is the explicit exception：Interact once + Palette dismiss。
- Drag starts：Palette dismiss；Drag owns sequence。
- Confirmation/Critical Error excludes Palette。

## 9.5 Release gate

Palette production activation requires：

- command-by-command action parity；
- checked、disabled、busy and conditional state parity；
- safe Quit and draft preservation；
- tray recovery for Show/Quit；
- Palette Ask → Conversation integration；
- no native-menu/Palette double response；
- focused-control and outside-click validation on Windows。

---

## 10. Capsule Two-State Prototype

## 10.1 State A — Compact Capsule

Used for empty、focused、one-line/short input and simple immediate interaction。

```text
                       anchor → Schwarz
╭──────────────────────────────────────╮
│ Ask ArkClaw…              [Voice*] [↑]│
╰──────────────────────────────────────╯
```

Focused / short input：

```text
╭──────────────────────────────────────────╮
│ Ask ArkClaw                              │
│ Open VS Code…                            │
│ [＋ Context*]           [Voice*] [Send] │
╰──────────────────────────────────────────╯
```

`Context` / `Voice` remain Planned and appear only when functional。

## 10.2 State B — Expanded Compact Capsule

State B is a visual Capsule variant, not `P=CONVERSATION_EXPANDED`。It supports multiline input、one short response、simple Activity or simple Result。

```text
╭──────────────────────────────────────────╮
│ Opening VS Code…                         │
│                               [Cancel*]  │
│ ──────────────────────────────────────── │
│ Ask ArkClaw                              │
│ You can add a follow-up…                 │
│ [＋ Context*]           [Voice*] [Send] │
╰──────────────────────────────────────────╯
```

## 10.3 Capacity contract

| Content | Compact A | Expanded Compact B | Expanded Conversation |
|---|---|---|---|
| Empty / one-line input | Preferred | Not needed | No |
| Multiline draft within compact limit | May grow | Preferred | If stable limit exceeded |
| One short response | Possible | Preferred | If continuity required |
| Thinking / simple Acting | Possible | Preferred | If persistent/complex |
| One simple Result/Error | Possible | Preferred | If recovery/explanation is rich |
| Multi-turn context | No | No | Required |
| Multiple generated components | No | No | Required |
| Multi-step progress | No | Summary only | Expanded/Workspace by structure |
| Rich Result/artifact | No | No | Expanded/Workspace |

When response content needs internal scrolling、history navigation、tabs、toolbar or multiple cards, State B has exceeded its purpose and must enter Expanded Conversation。

## 10.4 Prototype verdict

`PASS — Approved for Engineering TDD`

- A/B use the same Capsule/P state and anchored shell。
- B holds at most one current response/activity/result。
- Simple tasks do not immediately create a large Conversation window。
- Exact capacity and geometry remain configurable/non-blocking。

---

## 11. Anchoring Prototype

## 11.1 Global rules

- Preferred placement uses the nearest clear upper-side region around Schwarz。
- Direction changes before readability is reduced。
- No temporary Surface overlaps visible Schwarz body pixels、existing interactive hit region or taskbar reserved area。
- Anchor remains understandable through distance、entry origin、motion path and task continuity；no permanent connector line is required。
- Expanded/Workspace may reduce physical attachment for readability but must preserve identity continuity。

## 11.2 Position scenarios

| Schwarz position | Preferred direction | Fallback | Frozen result |
|---|---|---|---|
| Center | Upper-right | Upper-left → above → clearer side | Preserve gap and origin |
| Left edge | Upper-right / right | Above-right → below-right | Open inward |
| Right edge | Upper-left / left | Above-left → below-left | Same control order |
| Near taskbar | Above-right / above-left | Side-above | Keep taskbar separation |
| Near top edge | Side with downward bias | Below-right/left | No clipping |

`PASS — Approved for Engineering TDD`。Exact geometry、multi-monitor transition and post-Drag re-anchor motion remain non-blocking。

---

## 12. Focus Contract and Prototype

## 12.1 Core focus rules

- Only an explicit Conversation Entry may activate and focus Conversation。
- Left Click Interact does not change Conversation focus ownership。
- Hidden Capsule controls cannot retain focus while Palette is open。
- Dynamic Activity/Result updates normally do not steal typing/reading focus。
- Closing a transient layer restores a valid semantic target, not a stale widget identity。
- Ordinary Outside Click collapse keeps focus on the external clicked target；ArkClaw does not steal it back。
- Blocking Confirmation/Critical Error owns foreground focus and cannot be bypassed by Ask or Shortcut。

## 12.2 Focus scenarios

| Scenario | Focus result |
|---|---|
| Palette → Ask ArkClaw | Palette dismisses；Capsule/Conversation opens or restores；input focus when safe |
| Shortcut invocation | Conversation opens/restores；input focus when safe |
| Left Click while Capsule input focused | Interact；focus/caret remains unchanged |
| Left Click while external app focused | Interact；external focus remains；Capsule does not activate |
| Palette opens over Capsule | First available Palette item；draft + semantic return target stored |
| Palette dismisses without navigation | Prior Capsule input/caret or Workspace control |
| Character action selected | Execute command；restore prior valid Conversation target when appropriate |
| Confirmation arrives | Confirmation summary or first safe control；never automatic Confirm |
| Confirmation resolves | Return to valid base context while awaiting backend fact |
| Activity → Result | Preserve current typing/reading focus unless silence would be unsafe |

`PASS — Approved for Engineering TDD`。Exact focus APIs and native window flags are engineering concerns。

---

## 13. Activity → Result Prototype

```text
User request submitted
→ backend Thinking fact
→ Thinking in current correlated container
→ backend Acting fact
→ user-facing Action in same container
→ backend Success / Partial / Error / Cancelled fact
→ truthful Result in same container
→ Continue / Collapse
```

Frozen rules：

- Thinking、Acting and Result share one logical task-correlated container。
- Thinking cannot imply external action has begun。
- Acting uses user-facing language, never raw tool/MCP/API output。
- Cancel appears only when current cancellability is true。
- Result appears only after backend fact；UI motion cannot declare completion。
- Simple Success remains readable；Conversation-open result stays until next user action/collapse。
- Partial/Error use truthful structure, not Success styling。
- Separate popup/toast is unnecessary when the main Conversation Surface is visible。

`PASS — Approved for Engineering TDD`。Exact timing/motion remains non-blocking。

---

## 14. Surface Priority and Coexistence

## 14.1 Final priority

```text
Highest
1. Critical Error / invalidating safety interruption
2. Blocking Confirmation / required blocking input
3. Active primary Presentation: Workspace > Expanded Conversation > Capsule
4. User-relevant Activity control, embedded when P is visible
5. Anchored Action Palette / Character or System layer
6. Passive Result / Ambient Notification
7. Schwarz
Lowest
```

## 14.2 Coexistence matrix

| Surface A | Surface B | Allowed | Frozen rule |
|---|---|---|---|
| Capsule | Expanded / Workspace | No | Same P morph；never separate windows |
| Capsule | Palette | No visible coexistence | Capsule hides；draft/focus return preserved |
| Expanded | Palette | Conditional | Expanded remains task P；Palette temporary |
| Workspace | Palette | Conditional | Workspace stable below；not with blocking Overlay/required control |
| Conversation | Embedded Activity/Result/Error | Yes | One correlated context |
| Character-only | Standalone Activity/Ambient | Yes, one | Minimum necessary feedback |
| Activity | Palette | Conditional | Required foreground control wins |
| Confirmation | Readable Conversation base | Yes, focused | Base readable；Confirmation owns input |
| Confirmation | Palette | No | Confirmation wins |
| Critical Error | Confirmation | No | Error replaces invalid decision |
| Critical Error | Palette | No | Error wins |
| Error | Same-task Activity | No | Error replaces failed Activity |
| Multiple foreground Overlays | No | Highest valid one only |
| Multiple Ambient notifications | No | Aggregate、replace or silence |

If the frontend lacks a reliable fact stating whether Activity requires uninterrupted foreground control, default conservatively：do not open Palette when it would hide the only required control。

---

## 15. Master Gesture Matrix

| Gesture | Character-only | Capsule Open | Palette Open | Agent Acting |
|---|---|---|---|---|
| **Left Click Schwarz** | **Interact once；no Capsule** | **Interact once；Capsule remains；no draft/focus mutation** | **Interact once；Palette dismisses；no Conversation** | **Interact once；Agent task/Surface continue** |
| **Drag Schwarz** | Existing Drag only | Drag；draft/task preserved；meaningful Surface stable | Palette dismisses；Drag only | Drag；Agent task continues |
| **Right Click Schwarz** | Open Palette | Hide Capsule temporarily；preserve return；open Palette | Distinct stable right click dismisses | Conditional Palette；higher required control wins |
| **Double Click Schwarz** | No independent semantic；completed clicks follow Interact | Same；no toggle/open | Same after dismiss rules | Same；no Agent mutation |
| **Outside Click** | No ArkClaw effect | Collapse allowed Capsule；preserve draft/task | Dismiss without pass-through | Dismiss only transient UI；task continues |
| **Escape** | No effect；never Cancel | Collapse one level；preserve draft/task | Secondary → root；root → dismiss | Unwind one allowed UI layer；never implicit Cancel |

### 15.1 Capsule-open Character interaction

```text
Capsule open
+ completed non-drag Left Click Schwarz
→ Interact
→ Capsule remains visible
→ draft and caret/selection remain unchanged
→ focus ownership remains unchanged
→ no Submit / duplicate / toggle / entry replay
```

Thinking、Acting 或 Waiting 不因 Interact 被取消、重启、重定向或宣称完成。Character animation must not make Agent projection appear to change；exact animation arbitration remains validation detail, not a semantic TBD。

---

## 16. Prototype Findings and UX Risks

| Prototype / risk | Finding | Treatment | Verdict |
|---|---|---|---|
| Character vs Conversation entry | One gesture cannot safely own both domains | Left Click Interact；Palette Ask Conversation | Pass |
| Capsule two-state | One-line Capsule is too small for short Activity/Result | Compact A + Expanded Compact B | Pass |
| Anchoring | No fixed direction works at all screen edges | Directional fallback with one anchor language | Pass |
| Focus | Capsule and Palette cannot both stay interactive | Exclusive visibility + semantic return target | Pass |
| Escape | One-level unwind prevents Cancel/Discard confusion | Explicit hierarchy | Pass |
| Activity → Result | Separate popup fragments task identity | Same correlated container morph | Pass |
| Palette hierarchy | Root parity would be too tall/menu-like | Root + same-shell Character/System | Pass |
| Hover Ask | Important action cannot rely only on Hover | Not approved | Pass |
| Draft loss | Visibility and draft ownership must be separate | Preserve across all ordinary transitions | Pass |
| Palette capability loss | Presentation migration may omit commands | Repository inventory + parity release gate | Engineering constraint |
| Required Activity hidden | Palette could hide sole control | Priority guard + conservative default | Integration requirement |

The UX/accessibility review confirms that Hover may provide subtle feedback but cannot be the only discovery path for Agent Conversation。Keyboard Fast Entry reuses the same open/restore intent while the explicit Palette label remains the discoverable route。

---

## 17. Approved Decisions and Global Invariants

All items below are frozen for Engineering TDD：

1. **Character Click Preservation**：completed non-drag Left Click preserves existing Interact。
2. **Conversation Entry Separation**：mouse-driven Conversation requires Palette → Ask ArkClaw。
3. **Double Click Reserved**：no independent semantic；no Conversation。
4. **Click vs Drag**：mutually exclusive；Drag wins once recognized。
5. **Right Click**：opens one Action Palette only。
6. **Outside Click**：dismisses only allowed transient layer；never pass-through/Cancel/Confirm/Submit。
7. **Escape**：one-level unwind；Confirmation refusal；never implicit task Cancel。
8. **Draft Safety**：one draft per Conversation context；ordinary transitions never discard。
9. **Capsule Model**：Compact A + Expanded Compact B；B is not Expanded Conversation。
10. **Anchoring**：upper-side preferred、directional fallback、no visible/hit overlap。
11. **Focus**：only explicit Conversation Entry activates input；Interact does not alter focus ownership。
12. **Activity → Result**：same correlated container；backend fact controls projection。
13. **Palette Hierarchy**：Root + one same-shell Character or System layer。
14. **Interact Accessibility**：Left Click primary；Character Palette secondary；same command semantic。
15. **Surface Priority**：Critical Error > Confirmation > P > required Activity > Palette > Ambient > Character。
16. **Workspace + Palette**：conditional coexistence；Workspace remains stable。
17. **Confirmation + Palette**：never coexist。
18. **Backend Truth**：frontend never manufactures Thinking/Acting/Waiting/Success/Error/Cancelled。

### 17.1 Re-open conditions

The Design Freeze must be reopened if a downstream document proposes：

- one Left Click both Interacts and opens/focuses Conversation；
- Left Click stops executing Interact in any UI/Agent state；
- Double Click opens Conversation or delays Interact；
- Drag produces Interact/Conversation or loses existing landing semantics；
- draft can be silently discarded by Interact、collapse、focus loss or Quit；
- Palette removes verified capability without an approved successor；
- Palette competes with Confirmation/Critical Error；
- UI declares Agent projection without backend fact；
- two primary Presentations or two foreground Overlays coexist；
- a framework default changes any frozen user-visible result。

---

## 18. TBD Register

## 18.1 Blocking Product TBD

**None.**

The Conversation Entry architecture is single-valued：

- Left Click = Interact only；
- Primary Conversation = Palette → Ask ArkClaw；
- Fast Conversation = Keyboard Shortcut direction；
- Secondary Conversation = Existing Control Center / tray access；
- Double Click = Reserved。

## 18.2 Non-blocking TBD / engineering validation

1. `Shortcut: TBD`：exact key、Global/Local scope、conflict validation and teaching。
2. Exact click/Drag numeric threshold remains existing platform/engineering-defined behaviour。
3. Exact Capsule size、A/B capacity、anchor gap、edge offsets and multi-monitor transition。
4. Exact animation duration/easing、Result readable interval and Ambient timeout。
5. Typeface、color、blur/shadow、icons and Schwarz animation assets。
6. Context/Attachment and Voice capability/UX；remain Planned。
7. Direct Settings mapping；retain Control Center until confirmed。
8. Active Drag Escape semantics；no new behaviour in this freeze。
9. Cross-restart draft persistence mechanism；safe discard gate still required。
10. Optional system notification、unread aggregation and desktop background sampling。
11. Full Workspace layout、advanced artifacts and multi-task foreground selection。
12. Details diagnostic scope and user/developer content separation。
13. Reliable active/manual Character action indicator and final labels。
14. Interact animation vs Agent projection visual arbitration；semantics are already fixed。
15. Windows focus、outside-click、window role and right-click parity validation。
16. Empirical usability testing；may refine geometry/timing/labels but not silently change frozen semantics。

---

## 19. Engineering Handoff Requirements

This section defines required product outcomes and signals, not implementation classes、Qt events or APIs。

## 19.1 Left-click Interact Preservation Gate

```text
confirmed non-drag click
→ exactly one existing Interact semantic
→ zero Conversation invocation

valid Drag
→ existing Drag/release/landing
→ zero Interact and zero Conversation invocation
```

Required coverage：Character-only、Capsule open、Palette open、Workspace and Agent Acting。Capsule draft、caret、visibility and focus ownership must not change because of Interact。

## 19.2 Conversation Entry Integration

```text
Action Palette root
→ Ask ArkClaw command
→ Palette dismiss
→ Conversation open/restore intent
→ single Conversation context resolution
→ semantic focus resolution
→ Capsule / applicable existing Conversation Surface
```

This integration must cover：

- one Conversation owner and no duplicate Capsule；
- Palette/Capsule exclusivity；
- draft and return-focus preservation；
- current task recovery；
- Confirmation/Critical Error guard；
- no Agent projection mutation from opening UI。

## 19.3 Keyboard Fast Entry seam

Engineering may preserve one reusable Conversation open/restore intent for a future Shortcut, but must not bind an arbitrary key before `Shortcut: TBD` is resolved。Shortcut must not create a second logic path or bypass blocking Overlay。

## 19.4 Palette parity requirements

- Every verified Character/System command reaches the same existing semantic outcome。
- Checked、disabled、busy and conditional states remain truthful。
- Interact remains Left Click primary and Character Palette secondary。
- Tray remains initial Show/Quit recovery path。
- Native context menu and Palette never respond to the same Right Click。
- Palette selection dispatches exactly one command and then dismisses。

## 19.5 Frontend integration requirements

The frontend requires user-facing facts for：

- stable task identity / event correlation；
- Thinking、Acting、Waiting reason、Success/Partial、Error、Cancelled projection；
- user-facing task/action label；
- semantic progress when reliable；
- current cancellability and acknowledgement；
- Confirmation summary、scope、consequence、validity and valid decline；
- Result summary、artifact references and partial breakdown；
- Recovery availability：Retry / alternative / none；
- whether Activity requires uninterrupted foreground control；
- stale/duplicate event ordering。

Absent facts require conservative UI：no fake progress、Cancel、Retry、Confirm or foreground assumptions。These are integration contracts, not backend implementation design。

## 19.6 Engineering TDD revision targets

The next revision of 07 should：

- treat this 06 as the only product freeze reference；
- replace the old left-click change topic with `Left-click Interact Preservation Gate`；
- add `Conversation Entry Integration` for Palette Ask；
- update Executive Summary、Scope、Product Inputs、Frontend Architecture、Focus、Palette parity、Conversation/Palette architecture、Input Routing、Tests、Manual Acceptance、Vertical Slices、Risk Register、TBD and Readiness；
- keep baseline failures、Windows focus validation and missing backend integration facts as separate engineering readiness conditions；
- not begin an Implementation Plan solely because the product entry conflict is resolved。

---

## 20. Decision History

Phase 6 originally considered using Schwarz left-click as the Conversation Capsule entry。That decision was superseded during product reconciliation。

The final frozen interaction contract is：

- Left Click Schwarz → Interact only；
- Right Click Schwarz → Action Palette；
- Action Palette → Ask ArkClaw → Conversation Capsule；
- Keyboard Shortcut → Conversation Capsule（`Shortcut: TBD`）；
- Double Click → Reserved / no independent semantic。

Git history preserves the superseded design for audit purposes。This section is historical context only；all active specifications are stated directly in the preceding sections。

---

## 21. Final Design Freeze Decision

### Product Freeze Status: `APPROVED_WITH_NON_BLOCKING_TBD`

### Engineering Handoff Status: `READY_TO_REVISE_ENGINEERING_TDD`

Reasons：

1. Left Click and Drag preserve existing desktop-pet semantics。
2. Character Interaction and Agent Conversation have separate, explicit chains。
3. Primary、Fast and Secondary Conversation roles are unambiguous and require no permanent UI。
4. Capsule-open Left Click、draft and focus behaviour are single-valued。
5. Double Click has no competing Conversation meaning。
6. Palette migration has a clear hierarchy、parity map and release gate。
7. Outside Click、Escape、Draft、Anchoring、Activity → Result and Surface exclusivity remain fully specified。
8. No product-level Blocking TBD remains for revising 07。
9. Remaining validation items do not require competing product architectures。
10. Agent backend boundary remains intact。

Approval permits revision of Frontend Engineering TDD。It does not mean production implementation is ready, does not authorize changes to PetWindow、PetPointerGesture、Interact、Drag、tests or Agent backend, and does not authorize entering Phase 8。

---

## 22. Final Design Review

| Criterion | Result | Evidence |
|---|---|---|
| Single Source of Truth | Pass | This file is the only active Phase 6 authority；no addendum required |
| Character First | Pass | Character-only remains Home；Schwarz anchors Surface/state |
| Conversation First | Pass | Explicit Ask command leads to natural-language Capsule；no tool catalog |
| Existing pet compatibility | Pass | Click→Interact；Drag→Drag；no shared Conversation gesture |
| Gesture consistency | Pass | Left Click semantic does not vary by Surface/Agent state |
| UI on Demand / Calm Desktop | Pass | No permanent entry；Outside/Escape collapse safely |
| Progressive Disclosure | Pass | Capsule A/B → Expanded → Workspace by capacity/guards |
| Draft Safety | Pass | Interact and ordinary visibility/focus changes never discard draft |
| Focus accessibility | Pass | Explicit entries own activation；Hover is not the only critical path |
| Palette parity | Pass with engineering gate | All verified commands mapped；Interact retains primary + secondary paths |
| Surface priority | Pass | Confirmation/Error exclude Palette；one P/O enforced |
| Backend boundary | Pass | Projection consumes facts only；no lifecycle redesign |
| Historical clarity | Pass | History is short and non-normative；active body contains only final rules |
| Scope boundary | Pass | No code、Qt design、implementation plan、tests or production mutation |

### Review conclusion

ArkClaw now has one canonical Phase 6 Frontend Product Design Freeze。The active specification contains no competing Conversation gesture：Character click remains Interact, while Agent Conversation begins through Palette Ask or the future Shortcut。The document is ready to serve as the sole product input for revising 07。

---

Production code modified: NO  
Pet click semantics modified: NO  
Drag semantics modified: NO  
Engineering implementation started: NO
