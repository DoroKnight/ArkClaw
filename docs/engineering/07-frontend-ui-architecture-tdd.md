# ArkClaw Frontend UI Architecture TDD

> 阶段：Phase 7R — Frontend Engineering TDD Reconciliation  
> 类型：Repository-Grounded Technical Design Document  
> 输入：`docs/product/01-ui-vision.md` 至 `docs/design/06-interaction-freeze-and-prototype-review.md`  
> 唯一权威产品冻结：`docs/design/06-interaction-freeze-and-prototype-review.md`  
> Readiness：`READY_WITH_NON_BLOCKING_TBD`  
> 本文不修改生产代码、测试或 Agent backend

## 1. Executive Summary

ArkClaw 当前桌宠前端由应用级协调对象、不可获得焦点的 BODY 窗口、不可获得焦点的 OVERFLOW 窗口、系统托盘和传统 Control Center 组成。Click/Drag 仲裁已收敛到 framework-free 的 `PetPointerGesture`；只有它在 release 阶段最终返回 `CLICK` 后，`PetWindow` 才请求一次 `ProductionAction.INTERACT`。Drag 一旦成立，同一指针序列只进入移动、释放和既有落地流程。

推荐最小架构：

```text
PetWindow / existing gesture transaction
        │ confirmed Click / Drag / Right-click intents
        ▼
application-lifetime Frontend Presentation Coordinator
        ├─ owns orthogonal presentation model
        ├─ consumes one Conversation Invocation Seam
        ├─ owns one logical Conversation context and semantic focus return
        ├─ enforces one primary Surface + one foreground Overlay
        └─ drives lazily-created Qt Surface hosts

QtRuntimeBridge facts → Agent Presentation Mapper → same model

Action Palette / future Shortcut
        │ conversation-open intent
        └─────────────────────────→ same coordinator/model
```

该 seam 集中 Surface exclusivity、draft、focus 与 backend-fact projection，不重写桌宠核心。`PetWindow`、`PetPointerGesture`、animation、renderer、OVERFLOW proxy、tray 与 action dispatch 均保留。

`06` 已将最终入口契约冻结为：Left Click 只执行既有 `Interact`；Drag 只执行既有拖动；Right Click 只打开 Anchored Action Palette；Palette 中 `Ask ArkClaw` 是 mouse-driven Conversation 的主要入口；未来 Keyboard Shortcut 复用同一 invocation seam，但具体按键仍为 `Shortcut: TBD`；Double Click 保留且没有独立语义。

测试基线将交互冻结与仓库现状分开记录：直接覆盖 Click/Drag/OVERFLOW/context forwarding 的目标集合为 `20 passed`；较宽相关集合为 `169 passed, 5 failed, 1 skipped`，其失败均为现存 label/smoke 差异，另有 native Schwarz probe `2 skipped`。这些问题必须在生产 cutover 前收敛，但没有 Blocking Product TBD，也不阻止下一阶段编制 Implementation Plan。因此本 TDD 判定为 `READY_WITH_NON_BLOCKING_TBD`；本阶段仍不创建 Implementation Plan、不实现 UI。

## 2. Scope

本文覆盖：启动/关闭、窗口、gesture、menu、focus 与 state ownership 的真实事实；Left-click `Interact` preservation gate；Drag regression；Conversation Entry Integration；Draft Safety；Surface exclusivity；focus restoration；Right-click parity；Conversation/Activity/Workspace 的最小职责；backend integration signals；测试、风险、rollback 和 vertical slices。

工程边界是 **Left-click Interact Preservation**：confirmed non-drag click 仍且只触发一次既有 `ProductionAction.INTERACT`，Conversation Surface 不消费、延迟、重解释或 shadow 同一次手势。Conversation 入口是另一条独立链。

## 3. Non-goals

- 不设计 Agent planner、reasoning、memory、tool router、MCP、orchestration、scheduler 或 backend lifecycle。
- 不实现 Capsule、Palette、Workspace、新动画或生产 UI。
- 不冻结 Qt class/file hierarchy、signal/slot 名称、mouse threshold 或 positioning algorithm。
- 不定义 exact geometry、pixel、color、type、icon、motion 或 asset。
- 不做 repository-wide refactor、dependency upgrade、bug fix 或 formatter rewrite。
- 不修改 `01–06`；若 `01–05` 的历史表述与 `06` 已冻结结论冲突，以 `06` 为准。

## 4. Product / UX Inputs

### 4.1 Authority used here

1. `06`：唯一 authoritative frontend product design freeze；
2. `01–05`：未被 `06` supersede 的原则、状态与 Surface 合同；
3. 当前仓库可验证行为与测试事实。

| Topic | Status | Consequence |
|---|---|---|
| Character First / Calm Desktop | Confirmed | 默认仅 Schwarz；Surface lazy/on-demand |
| completed non-drag Left Click | Confirmed: exactly one existing `Interact` | zero Conversation；不得延迟等待 Double Click |
| valid Drag | Confirmed: existing Drag | zero `Interact`；zero Conversation invocation |
| Right Click | Confirmed: Anchored Action Palette only | zero `Interact`；Right Click 本身不执行 action |
| Primary mouse Conversation entry | Confirmed: Palette → `Ask ArkClaw` | dismiss Palette → create/restore one Conversation → focus input |
| Fast Conversation entry | Confirmed seam; `Shortcut: TBD` | 可设计 reusable seam；本阶段不得绑定具体组合键 |
| Control Center | Confirmed secondary/legacy/recovery | 不是 Capsule shell，不是主入口 |
| Double Click | `Reserved / no independent semantic` | zero Conversation；不得为其延迟 single click |
| draft outside click | collapse + preserve | draft 独立于 visibility |
| Capsule + Palette | 不同时可见 | 保存 draft/focus return target |
| Confirmation + Palette | Never coexist | Confirmation wins |
| Activity → Result | same correlated container | 无 popup chain |
| Agent state | presentation projection | 只消费 backend facts |

### 4.2 Canonical resolution

`06` 已完成旧冲突仲裁。工程实现必须相信下列 active contract，而不是保留互相覆盖的版本：

```text
Completed Left Click → existing Interact only
Valid Drag          → existing Drag only
Right Click         → Action Palette only
Palette → Ask ArkClaw → dismiss → create/restore Conversation → focus
Keyboard Shortcut   → same Conversation invocation seam (`Shortcut: TBD`)
Double Click        → Reserved / no independent semantic
```

### 4.3 Superseded Engineering Assumption Inventory

| Section | Old assumption | Why invalid | Required replacement |
|---|---|---|---|
| Header / §1 / §4 | 07 需要依赖一个“最新补充”覆盖 06，且产品输入仍冲突 | 06 已规范化为唯一权威 freeze | 只引用 canonical 06；`01–05 < 06` |
| §1 / §4 / §12 | Capsule invocation 是 Blocking Product TBD | 06 已冻结 Palette `Ask ArkClaw` 为 mouse primary entry | 建立 reusable Conversation Invocation Seam |
| §15 | 仍以 left-click migration 为问题框架 | 产品冻结明确禁止迁移 | 改为 Left-click Interact Preservation Gate |
| §15 / §18 | Palette item click/dismiss/focus 仍未定义 | 06 已冻结事务顺序 | Palette Ask → dismiss → create/restore → focus |
| §18 / §20 / §21 | Conversation 只能等待未来未确认 trigger | mouse trigger 已确认，只有 shortcut 键位仍 TBD | Palette Ask 现在接入；未来 shortcut 复用同一 seam |
| §27 / §28 | 测试与验收未覆盖 Ask entry、single ownership、duplicate guard | 不足以验证最终入口合同 | 按本 TDD 的 A–J 类重组 |
| §29 / §30 | vertical slices / rollback 仍允许未来迁移 left click | Left Click 是永久保护合同 | 只允许回滚 Palette/Capsule；不得回滚为 click-to-Capsule |
| §31 / §33 / §34 | 入口冲突和替代入口是 blocker，结论 `NOT_READY` | 产品 blocker 已由 06 消除 | 重分类仓库事实，采用 `READY_WITH_NON_BLOCKING_TBD` |

## 5. Current Repository Evidence

| Concern | File / class / method | Confirmed behaviour | Implication |
|---|---|---|---|
| entry | `pyproject.toml`; `pet_application.main` | production pet has independent GUI entry | 新 UI 接入 pet composition |
| lifecycle | `PetApplicationCoordinator` | coordinates PetWindow/MainWindow/tray/shutdown | 新 coordinator 的自然创建点 |
| BODY | `PetWindow.__init__`, `_apply_window_flags` | Frameless Tool, translucent, NoFocus, show-without-activating | 不能承载文本输入 |
| OVERFLOW | `PetEffectOverlayWindow` | top-level NoFocus, alpha hit proxy, `HTTRANSPARENT` | 只用于渲染/代理 |
| gesture | `PetPointerGesture.move/release` | threshold 前 release=Click；越阈值=Drag | 真正决策不在 press |
| left click | `PetWindow.mouseReleaseEvent` | `CLICK → request_user_pet_action(INTERACT)` | 与最新决定一致 |
| right click | `PetWindow.contextMenuEvent` | 每次构建并 popup `QMenu` | Palette 替 presentation |
| actions | `ProductionActionMenuSection` | pet/tray 共享 production action section | 语义可复用 |
| agent facts | `QtRuntimeBridge` | turn id/state/delta/terminal signals | mapper 起点但信息不足 |
| old conversation | `MainWindow` | line edit/transcript；submit 前立即 clear | 不满足新 draft contract |

### 5.1 Startup

```text
arkclaw-pet → pet_application.main
→ QApplication → single-instance owner
→ QtRuntimeBridge + hidden MainWindow
→ production pet composition/fallback → PetWindow
→ PetApplicationCoordinator → restore settings
→ PetWindow.show → SystemTrayController → app.exec
```

Shutdown：`PetWindow.request_safe_exit → coordinator → MainWindow.request_safe_close → bridge.shutdown → shutdown_finished → save settings / tray / renderer / windows cleanup → app.quit`。

### 5.2 Current ownership

| State | Owner |
|---|---|
| pet lifecycle/motion | `PetAnimationEngine` / `PetMotionModel` through PetWindow |
| explicit animation | `PetTrack0Controller` |
| pointer transaction | `PetWindow._pointer_gesture` |
| BODY/OVERFLOW | PetWindow + renderer + effect overlay |
| pet/tray coordination | `PetApplicationCoordinator` |
| tray presentation | `SystemTrayController` |
| Control Center turn flags | `MainWindow` |
| runtime task | backend `RuntimeSessionController`, projected by bridge |
| new Surface state | Not present |

## 6. Current Window Architecture

### 6.1 BODY

`PetWindow` owns authoritative input and body position. Initial/workspace geometry comes from `QScreen.availableGeometry()` and `PetMotionModel`. Flags are `FramelessWindowHint | Tool | WindowDoesNotAcceptFocus` plus optional topmost；`WA_TranslucentBackground`、`WA_ShowWithoutActivating` and `NoFocus` are set.

### 6.2 OVERFLOW

`PetEffectOverlayWindow(QWidget(None))`：

- no text focus；
- publishes alpha hit frame from rendered image；
- Windows `WM_NCHITTEST` returns `HTCLIENT` for body/visible pixels and `HTTRANSPARENT` elsewhere；
- forwards mouse/context events to PetWindow；
- `_proxy_pointer_active` keeps the sequence across bounds, retirement and generation change；
- raises only on initial show/flag change, not per frame；
- taskbar z-order correction uses `SWP_NOACTIVATE`。

### 6.3 Lifecycle and protected facts

Show reclaims PetWindow into an available workspace；hide cancels pending gesture and hides OVERFLOW；tray survives because `setQuitOnLastWindowClosed(False)`；MainWindow is activated only on explicit open. New Surfaces must preserve BODY/OVERFLOW composition、motion position、landing、alpha hit、active proxy、taskbar grounding and tray recovery.

## 7. Current Pointer / Gesture Architecture

### 7.1 Click chain

```text
BODY press or OVERFLOW-forwarded press
→ PetWindow.mousePressEvent
→ PetPointerGesture.press(... QApplication.startDragDistance())
→ PENDING
→ release
→ PetPointerGesture.release() rechecks movement
→ CLICK
→ request_user_pet_action(INTERACT)
→ _request_pet_action(... ActionSource.USER)
→ PetAnimationEngine / PetTrack0Controller / renderer
```

**真正决定 Click/Drag 的位置**是 `src/arkclaw/presentation/pet_pointer_gesture.py` 的 `move()` / `release()`；`mousePressEvent` 只开启 pending transaction。

### 7.2 Drag chain

```text
press → PENDING
→ move; Manhattan distance reaches snapshotted platform threshold
→ BEGIN_DRAG once → PetAnimationEngine.start_dragging()
→ subsequent DRAG → PetMotionModel.drag_to() → PetWindow.move()
→ release → RELEASE_ACTIVE_DRAG
→ PetAnimationEngine.release_drag(workspaces)
→ existing falling/landing; no Interact
```

未发现显式 `grabMouse()` / Win32 capture；当前连续性由 Qt delivery 与 OVERFLOW `_proxy_pointer_active` 共同提供。这是事实，不是替换现有逻辑的理由。

Right click 通过 `QContextMenuEvent`，不进入 `PetPointerGesture`。OVERFLOW 仅在 body/visible hit 上转发一次。Alpha hit threshold 为 8；新 Surface 不得扩大隐形阻挡区。

## 8. Current Menu Architecture

Pet context menu：Pause/Continue、Always on top、Start with Windows、production section、Open ArkClaw Control Center、Exit。

共享 `ProductionActionMenuSection`：role heading、Relax、Move Left/Right、Sit、Sleep、Special、Interact、Resume Autonomous，并根据 available actions/closing 更新 enabled state。

Tray 另有 Hide/Show，且同样提供 Control Center、Pause、topmost、production actions、autostart、Exit。Tray 通过 `PetTrayCommands` / `PetProductionActionCommands` 调用 coordinator；production action source 是 TRAY，pet menu 是 USER。

**分离程度：Partial。** ProductionAction identity/availability/dispatch 可复用，系统命令也汇入 coordinator；但 pet/tray 仍分别构建若干 `QAction`、label 和 checked state，没有统一 presentation-neutral catalog。Palette 应加小型 command descriptor adapter，不复用 QAction、不复制 animation call，也不做全仓 command rewrite。

## 9. Current Focus Architecture

- PetWindow/OVERFLOW：NoFocus、WindowDoesNotAcceptFocus、show-without-activating；
- MainWindow：普通 top-level；显式 open 时 `show/raise_/activateWindow`；
- settings dialog 同样显式激活；
- QMenu 在打开时拥有 transient interaction；
- 当前没有 semantic return-focus owner；
- 当前 QMenu dismiss 后的真实 native focus destination 没有测试证据，标记 `Unknown`。

Capsule 不能作为 PetWindow 普通 child input。必须有独立 activation contract，且 animation/OVERFLOW refresh 不得对它调用 activate/focus。

## 10. Behaviour Baseline

### 10.1 Broad selected suite

```text
Command:
.\.venv\Scripts\python.exe -m pytest -q
  tests/unit/test_pet_pointer_gesture.py
  tests/unit/test_pet_surface_hit_frame.py
  tests/unit/test_pet_explicit_action_control.py
  tests/unit/test_pet_production_actions.py
  tests/unit/test_pet_render_layout.py
  tests/qt/test_pet_production_actions.py
  tests/qt/test_pet_production_lifecycle.py
  tests/qt/test_pet_effect_overlay.py
  tests/qt/test_pet_renderer.py
  tests/qt/test_pet_window.py

Result: 169 passed, 5 failed, 1 skipped
Relevant coverage: gesture, action, layout, BODY/OVERFLOW, hit, drag,
renderer, tray/menu and shutdown.
Known gap: baseline is not green.
```

Failures（未修改代码/测试）：role heading 预期与当前 `ACTIVE PET · SCHWARZ / 黑` 不同；两个用例仍预期 `Open Agent Window` 而当前是 `Open ArkClaw Control Center`；`qt_pet_smoke.py` 报 `drag_struggle_entered,drag_struggle_exited`；`qt_tray_smoke.py` 以 code 2 退出但输出的 `failed_checks` 为空。一个 Windows-only taskbar test 在 offscreen 下跳过。

### 10.2 Targeted Click/Drag/OVERFLOW/context baseline

```text
Command:
.\.venv\Scripts\python.exe -m pytest -q
  tests/unit/test_pet_pointer_gesture.py
  tests/qt/test_pet_production_actions.py::test_real_qt_mouse_chain_drags_production_window_with_relax_fallback
  tests/qt/test_pet_production_actions.py::test_left_click_requests_interact_once_with_user_source
  tests/qt/test_pet_window.py::test_visible_overflow_pixel_clicks_through_pet_window_to_interact_once
  tests/qt/test_pet_window.py::test_visible_overflow_pixel_drag_enters_relax_motion_fallback
  tests/qt/test_pet_window.py::test_visible_overflow_pixel_opens_pet_context_menu_without_action_change
  tests/qt/test_pet_window.py::test_avoided_overflow_proxies_body_press_move_release_and_context_menu
  tests/qt/test_pet_effect_overlay.py::test_overlay_forwards_body_click_to_input_owner
  tests/qt/test_pet_effect_overlay.py::test_overlay_forwards_context_menu_once_from_visible_pixel_outside_body
  tests/qt/test_pet_effect_overlay.py::test_overlay_keeps_forwarding_an_active_drag_outside_body_hit_area
Result: 20 passed
Coverage: below-threshold Click; threshold Drag; Click → Interact once;
Drag → no Click; body/overflow right-click does not mutate actions;
avoided-overflow and effect-overlay proxy continuity.
Gap: offscreen does not prove native activation/capture/Z-order.
```

### 10.3 Native Schwarz probe

```text
Command: .\.venv\Scripts\python.exe -m pytest -q tests/qt/test_schwarz_native_input.py
Result: 2 skipped
Gap: production manifest and Spine bridge env were not configured.
```

### 10.4 Baseline classification

| Classification | Evidence | Phase 7R consequence |
|---|---|---|
| Relevant Green Baseline | targeted set `20 passed` | 足以冻结现有 Click/Drag/right-click forwarding 行为并编制计划 |
| Pre-existing Failures | broad set `5 failed`：3 个 label/assertion drift，2 个 smoke exit anomaly | Slice 0 查明并归类；文档修订不把它们伪装为本阶段回归 |
| Engineering Validation Required | native Schwarz `2 skipped`；offscreen 不证明 Windows activation/capture/Z-order | 生产窗口 cutover 前必须在真实 Schwarz/native Windows 环境补证据 |
| Blocking Relevant Failure | **None for creating an Implementation Plan** | 不授权忽略生产 gate；只说明无需把产品入口重新标为 blocker |

## 11. Behaviour Preservation Contract

### Rendering / animation

- Schwarz size、BODY viewport、composition、mix、BODY/OVERFLOW ordering、hit threshold 不变；
- Relax、Move、Sit、Sleep、Special、Interact、Resume Autonomous 保持现有 semantics；
- single click 继续以 USER authority 请求 Interact；
- Palette 调同一 dispatch，不直调 renderer/player；
- Agent presentation animations 若不存在，标记 `Planned / Separate Task`。

### Input / windowing

- Click/Drag 仍是一个 gesture transaction；threshold 仍来自平台并在 press snapshot；
- Drag 不产生 Interact/Capsule/Palette；
- OVERFLOW 保持 active proxy 与透明穿透；
- right-click cutover 是 native menu 或 Palette，绝不同时；
- PetWindow/OVERFLOW 保持 no-focus；
- Agent Surface 不在 tick 中 activate/raise；
- tray 保持 Show/Quit recovery。

### Character Click Preservation Gate

| Context | Confirmed completed non-drag Left Click result |
|---|---|
| Character only | exactly one existing `Interact` |
| Capsule | exactly one existing `Interact`; Capsule/draft/caret/focus ownership unchanged |
| Expanded Conversation | exactly one existing `Interact`; Conversation context unchanged |
| Workspace | exactly one existing `Interact`; Workspace/task unchanged |
| Palette visible | exactly one existing `Interact`; Palette dismisses；zero Conversation invocation；no second click required |
| Agent Thinking / Acting / Waiting | exactly one existing `Interact`; 不 Cancel、不提交、不打开/聚焦 Conversation |
| Agent Success / Error | exactly one existing `Interact`; Result/Error truth and recovery context unchanged |
| Immediately after Drag | Drag transaction 为 zero Interact；仅下一次独立 completed click 才 Interact |

该 invariant 适用于每个 supported frontend presentation state。Palette open 时直接点中 Schwarz 是 explicit Character-target click，不是 ordinary outside dismiss 的 pass-through。通过条件不是“能打开某个 Surface”，而是所有上下文都不存在 Interact 丢失、重复、延迟、second-click requirement 或 Conversation side effect。

## 12. Proposed Frontend Architecture

### A. Frontend Presentation Model

**Why:** 当前没有 Surface exclusivity、draft、focus return 或 Agent projection owner。分散 `isVisible()` 会造成冲突。  
**Why now:** Capsule/Palette 在 MVP 前共享这些不变量。  
**Alternative:** coordinator 目前只协调旧窗口，MainWindow 是传统 Control Center。  
**Interface:** `dispatch(frontend_intent_or_fact) → presentation_effects` 与 immutable snapshot。它是 Qt-free in-process deep module；同一 interface 供生产与测试使用。Model 是 Conversation create-vs-restore、duplicate protection、presentation level、draft 和 semantic focus target 的唯一决策者。

### B. Frontend Presentation Coordinator

由 `PetApplicationCoordinator` 创建并拥有，application-lifetime。它持有 model、lazy Surface hosts、消费 Conversation Invocation Seam、按序执行 show/hide/focus/command effects、连接 bridge mapper；不取代现有 coordinator，也不持有 backend planning。

### C. Qt Surface Hosts

Conversation host（Capsule A/B + Expanded）、Palette host（root + Character/System）、Activity/Result view、later Workspace host。Host 只 render state/emit intent，不决定跨 Surface coexistence。只有一个实际 adapter 时不引入形式主义 view port。

### D. Agent Presentation Mapper

把 bridge signals 变成 correlated frontend facts；拒绝/降级 stale facts；缺失事实形成 integration requirement；不调度、路由或取消 backend 工具。

### E. Conversation Invocation Seam

这是一个小而具体的 semantic interface，不是 event bus、通用 command framework 或 backend task入口。

| Responsibility | Contract |
|---|---|
| Producers | Palette `Ask ArkClaw`；未来 Keyboard Shortcut；若以后统一 Control Center，仅经显式 adapter |
| Consumer | Frontend Presentation Coordinator → Model interface |
| State owner | Model 中唯一 logical Conversation context |
| create vs restore / duplicate protection | Model 决定并发出 idempotent Surface effects |
| focus | Model 选择 semantic target；Coordinator 解析并激活唯一实际 target |
| test boundary | 直接向 Model dispatch invocation intent，断言 snapshot/effects；不依赖 QAction/widget identity |

Palette command 不得直接 `new Capsule()`、自行寻找 widget 或保存另一份 Conversation visibility。PetWindow 保持所有 character pointer decisions：completed Left Click → existing Interact；valid Drag → existing Drag；Right Click → Palette intent。Conversation 不经过 pet gesture transaction。

## 13. State Ownership

| Dimension | Owner | Values/examples |
|---|---|---|
| Primary Presentation | frontend model | Character, Capsule, Expanded, Workspace |
| Foreground Overlay | frontend model | None, Palette layers, Confirmation, Critical Error, Ambient |
| Agent projection | model, sourced by mapper | Idle, Thinking, Acting, Waiting, Success, Error, Cancelled |
| Draft | model / Conversation context | text, revision, caret, submitted snapshot |
| Focus return | model semantic token | input, workspace control, external/none |
| pointer gesture | existing PetPointerGesture | Idle, Pending, Dragging |
| pet action/motion | existing pet modules | production action, autonomy, lifecycle |
| backend task | Agent backend | outside frontend ownership |

禁止 `CAPSULE_WITH_PALETTE` 等组合枚举；用正交 P/O/projection/draft/focus，并由不变量限制组合。

Capsule、Expanded Conversation 和 later Workspace 不是三个独立会话。它们是同一 logical Conversation context 的不同 presentation level；该 context 还拥有 current task correlation、draft 和 semantic focus target。现有 MainWindow/Control Center 暂保留为 secondary/legacy/recovery surface，不得成为第二个 Capsule state owner。

## 14. Surface Ownership & Exclusivity

Invariants：exactly one P；at most one foreground O；只有一个 logical Conversation context；Capsule/Expanded/Workspace 是该 context 的互斥 presentation level；Capsule/Palette 不同时可见；Confirmation/Critical Error 排斥 Palette；Activity/Result/Error 优先嵌入 P；dismiss 不 Cancel；hidden Surface 不持焦点；view 不能自行 show；stale fact 不替前景任务。Right Click 本身永不创建 Conversation。

Palette dismissal has two distinct input contracts：

| Input while Palette is open | Result |
|---|---|
| ordinary outside click whose target is not Schwarz | dismiss Palette；do not pass the dismiss event through；zero Character action；zero Conversation action |
| completed non-drag Left Click explicitly targeting Schwarz | exactly one existing `Interact`；dismiss Palette；zero Conversation invocation |

The second row is Character Click Preservation，not outside-click leakage。No model/host exclusivity rule may convert it into dismiss-only or require a second click。

Model 决定合法 next state/return target；coordinator 先 dismiss previous 再 show next；host 不读取其他 host visibility 作策略。Widget visibility 是 effect，不是 source of truth。

| Combination | Rule |
|---|---|
| Capsule + Palette | Not visible together; preserve draft/focus target |
| Conversation + Activity | Allowed only embedded/correlated |
| Workspace + Palette | Conditional; no blocking overlay/required control |
| Confirmation + Conversation | readable base, focused overlay, base input disabled |
| Error + same-task Activity | Error replaces Activity |
| Character + standalone Activity/Ambient | one minimal host |

## 15. Left-click Interact Preservation Gate

### Frozen decision

```text
completed non-drag left click
→ exactly one existing ProductionAction.INTERACT semantic
→ zero Conversation invocation/focus/toggle

valid drag
→ existing Drag behaviour
→ zero Interact
→ zero Conversation invocation
```

When Palette is open，the same invariant resolves as：

```text
completed non-drag Left Click explicitly targeting Schwarz
→ exactly one existing ProductionAction.INTERACT semantic
→ Palette dismiss
→ zero Conversation invocation
→ no second click required
```

这个 gate 保护既有 command semantic，不要求复制 action 实现。Left Click primary entry 与 Palette → Character → Interact secondary entry 必须汇入同一 existing `ProductionAction.INTERACT` dispatch；不能出现第二套 animation call。

### Repository decision points and evidence

| File | Class | Method | Current behaviour | Evidence | Engineering implication |
|---|---|---|---|---|---|
| `src/arkclaw/presentation/pet_pointer_gesture.py` | `PetPointerGesture` | `press`, `move`, `release` | release below the snapshotted threshold yields Click；crossing yields Drag and release never yields Click | targeted unit tests | preserve this module as the sole Click/Drag decision point |
| `src/arkclaw/presentation/qt/pet/pet_window.py` | `PetWindow` | `mousePressEvent`, `mouseMoveEvent`, `mouseReleaseEvent` | only final `CLICK` requests USER `ProductionAction.INTERACT` once | targeted Qt Interact/real-drag tests | do not insert Conversation or double-click delay into this chain |
| same | `PetWindow` | `contextMenuEvent` | constructs the current native `QMenu`；does not dispatch Interact merely by opening it | body/overflow context tests and source inspection | future cutover replaces only presentation with one Palette-open intent |
| `src/arkclaw/presentation/qt/pet/pet_effect_overlay.py` and related hit proxy | `PetEffectOverlayWindow` / existing proxy classes | pointer/context forwarding methods | visible overflow forwards one physical sequence to the input owner；active Drag remains continuous | selected effect-overlay/window tests | Palette work must not alter proxy/transaction identity |

Relevant characterization includes `test_release_below_snapshot_threshold_is_one_click`, `test_crossing_manhattan_threshold_begins_drag_once`, `test_left_click_requests_interact_once_with_user_source`, real Qt drag fallback, visible/avoided overflow Click/Drag/context tests, and effect-overlay active-drag/context forwarding tests.

### Hard failure conditions

- Left Click opens, restores, focuses or toggles Conversation；
- Left Click does both `Interact` and Conversation；
- Interact is delayed to wait for Double Click；
- an open Capsule changes the primary left-click semantic；
- a Drag produces Interact or Conversation；
- an ordinary Palette outside-dismiss targeting something other than Schwarz passes through and triggers a Character/Conversation action；
- an explicit Schwarz click while Palette is open is swallowed as dismiss-only or requires a second click before Interact。

Any of these blocks production integration. There is no planned left-click migration slice.

## 16. Drag Regression Protection

保留 `press → pending → Click/Drag` transaction，不在 press 打开 Surface。保护 platform threshold、单次 BEGIN_DRAG、跨 BODY/OVERFLOW move、final position、fall/landing、no Interact/Capsule/Palette、no draft loss、no focus steal。

Conversation 可见时 Drag：draft 仍由 model 持有；meaningful Surface 保持可读位置。Palette visible 时，Schwarz Drag threshold recognition dismisses Palette；Drag owns that pointer sequence and produces zero Interact/Conversation。它与 completed non-drag Character click 的 Interact contract 相互独立。Drag 后可 recompute anchor 但不抢焦或 replay Conversation entry。Workspace 可见时 Schwarz movement 不改变 Workspace task/context ownership。Exact re-anchor motion TBD。

## 17. Draft Safety

Draft 是 frontend/session state：

```text
text; has_draft; revision; caret/selection semantic position;
submitted_snapshot_identity | None
```

IME composition 不得因 visibility transition submit/discard。

| Event | Outcome |
|---|---|
| Palette `Ask ArkClaw` | dismiss Palette；create/restore same Conversation context；preserve draft；focus input |
| future Shortcut | same invocation intent and same draft/context；不创建第二实例 |
| outside/Escape/manual collapse | preserve; Capsule hidden |
| Palette roundtrip | preserve; restore semantic edit target |
| Drag/focus loss | preserve; no auto-submit |
| Expanded/Workspace | same draft transfers |
| Agent Cancel/Error | separate unsent draft survives |
| accepted exact submit snapshot | ceases to be draft |
| explicit Clear/Discard | destroy |
| Quit with draft | persist or explicit discard confirmation |

Current `MainWindow._send_message()` clears before correlated acceptance，不能复用于新 Capsule。Frontend needs request-acceptance/correlation fact before clearing exact snapshot. Cross-restart persistence TBD；within-session required。

## 18. Focus Restoration

保存 semantic token，不保存 raw QWidget pointer：conversation input + revision、workspace control identity、palette command identity、confirmation safe control、external/none。恢复时解析到当前可见 target；不存在则用最近 semantic parent。

| Transition | Focus result |
|---|---|
| Palette `Ask ArkClaw` | Palette dismiss 后 create/restore one Conversation；input focus when interactive |
| future Keyboard Shortcut | 与 Palette 相同 semantic target；具体 `Shortcut: TBD` |
| single click Schwarz | Interact; no-focus pet must not steal Capsule/external focus |
| Palette over Capsule | first enabled palette item; Capsule hidden |
| no-navigation Palette dismiss | prior input/caret, Workspace control or external target |
| navigation/hide/quit | destination focus; no obsolete restore |
| Expanded → Capsule | corresponding input/content |
| Workspace → Expanded | Conversation region |
| outside collapse | external clicked target keeps focus |
| Activity → Result | normally preserve typing/reading focus |
| Confirmation | summary/first safe control, never implicit Confirm |

只有 coordinator 可激活新 Agent Surface；render tick 永不 activate；hidden Capsule 先 relinquish focus；raise/activate/setFocus 每个显式 transition 一次；outside dismiss 不抢回 ArkClaw focus。

## 19. Right-click Capability Parity

| Capability | Current Entry | Target | Reuse | MVP | Risk |
|---|---|---|---|---|---|
| Pause/Continue | pet+tray | Character | coordinator method | Yes | state parity |
| Relax | both | Character | `RELAX` | Yes | availability/source |
| Move L/R | submenu | Character row | existing actions | Yes | not Drag |
| Sit/Sleep/Special | both | Character | existing actions | Yes | availability/OVERFLOW |
| Interact | left click+menus | preserve click + Character | existing action | Yes | no remove/duplicate |
| Resume Autonomous | both | Character conditional | existing method | Yes | active-state proof |
| Role identity | heading | Character heading | role id | Yes | presentation only |
| Always on Top | both | System | existing setter | Yes | checked/native flags |
| Start with Windows | both | System | autostart controller | Yes | busy/unavailable |
| Open Control Center | both | System legacy | existing method | Yes | not label-only Settings |
| Settings | Control Center internal entry | System direct only after mapping exists | current `_open_settings` cannot be assumed standalone | No / TBD | must not relabel Control Center as Settings |
| Hide/Show | tray | Hide in Palette; Show tray | visibility command | Yes | recovery |
| Exit | both | Quit | safe-exit path | Yes | draft safety |

Palette uses a read-only command descriptor：semantic id、label、group、enabled、checked/conditional state、invoke intent。它由现有 state/methods 生成，不把 QAction 当模型，不建立全仓 command framework。

Tray 第一阶段不迁移、不改 source/ordering/recovery。Right-click production activation 只切换：`contextMenuEvent → old QMenu OR Palette intent`，绝不二者都响应。保留 narrow rollback。

## 20. Conversation Entry Integration & Surface Architecture

### 20.1 Minimal invocation interface

```text
Palette Ask command ─┐
                     ├─ ConversationOpenOrRestore intent
future Shortcut ─────┘
                              ↓
                Coordinator → Presentation Model
                              ↓
           ordered dismiss/show/focus effects
```

该 intent 只表达 frontend presentation 请求，不创建 backend task、不改变 Agent projection。它足够窄，不能演化成全局 event bus 或通用 command dispatcher。

### 20.2 Palette transaction

`Ask ArkClaw` selection is one ordered semantic transaction：

1. Palette emits one command intent；
2. Model removes Palette overlay and records Conversation input as semantic focus target；
3. Model chooses create-or-restore for the single Conversation context/host；
4. Coordinator applies dismiss before show/restore；
5. Coordinator resolves and focuses the current interactive input once。

重复 activation、key repeat 或 re-entrant host callback 必须由 model/coordinator duplicate guard 合并，不能生成第二 Capsule。

Guards：

| Condition | Result |
|---|---|
| Blocking Confirmation exists | 不创建普通 Capsule；保留/恢复更高优先级 required context |
| Critical Error exists | obey priority contract；不得用普通 Conversation 覆盖错误处理 |
| Capsule/Expanded exists | restore applicable level/context；never duplicate |
| Workspace/current Agent task exists | restore the applicable Conversation region associated with that logical context/task |
| stale/duplicate Palette command | no second Surface、task or focus transition |

Command selection is consumed exactly once；Palette stops accepting further commands before dismiss effects begin。

### 20.3 Single Conversation ownership

One Conversation context owns draft、presentation level、current task correlation and focus target；one lazy Conversation host renders Capsule A/B or Expanded；Workspace later presents the same context rather than copying it。Current Control Center remains secondary/legacy/recovery and is not reused as the Capsule shell。

Host renders input/draft、short response/activity/result、focus/IME、variant、dismiss intents、anchor result。它不决定 priority、backend lifecycle、cancellability 或 invocation source。

### 20.4 Lifecycle

First invocation lazy-instantiates the host；ordinary collapse/Palette roundtrip hides but keeps session state；safe shutdown performs the draft-safe policy；repeat invocation restores/re-focuses the existing context。Conversation opening alone never submits text or starts a backend task。

### 20.5 Other producers

Keyboard producer is planned against this same seam，but the actual `Shortcut: TBD` and scope/native registration require later validation。Control Center may receive an adapter only if future consolidation is approved；it must not become a second primary mouse path or a second Conversation state owner。

## 21. Action Palette Architecture

One lazy host；Root、Character、System 是 same shell，不是 cascade。

```text
Root
├─ Ask ArkClaw
├─ Current Task (facts only)
├─ Character → same-shell Character layer
└─ System → same-shell System layer
```

Right Click Schwarz creates/shows this host only and performs zero command. State 从 current pet/coordinator facts 刷新；availability 从 available actions；Resume active indicator TBD。Secondary Escape→root；root Escape/outside/distinct stable right click→dismiss；selection invokes exactly one semantic command then dismiss；no-navigation dismiss restores semantic focus；Hide/Quit/Control Center use destination lifecycle。`Ask ArkClaw` follows §20.2 rather than directly constructing a widget。

Dismiss routing must classify the intended target before applying an effect：ordinary outside click on a non-Schwarz target dismisses without pass-through and invokes no command；a completed non-drag Left Click explicitly targeting Schwarz invokes exactly one existing Interact and dismisses Palette in the same semantic outcome。The latter is an explicit Character rule，not generic pass-through。

## 22. Agent Activity / Result Integration

Thinking、Acting、Result 是一个 correlated presentation object 的 variants：visible Conversation 中 embed；Character-only 时最多一个 minimal host。Result 只来自 backend fact。

Opening/restoring/collapsing a Conversation Surface is frontend presentation only；it must not synthesize Thinking、Acting、Waiting、Success or Error。

Stable task id 是 guard；duplicate phase merge；stale terminal 不替前景 task，可降为 ambient/recoverable。Cancel 仅在 cancellability fact 下显示；点击只发 intent并防重复，等待 correlated fact；collapse 不 Cancel；completion 胜出时显示真实 result。

当前 `AgentState` 只有 `IDLE/LISTENING/THINKING/SPEAKING/ERROR/REMINDING`，不足以表达 Acting、Waiting reason、confirmation、progress、partial、recovery、foreground-control。它们是 integration requirements，不是 backend redesign 许可。

## 23. Window Strategy

| Option | Focus | Window/drag impact | Decision |
|---|---|---|---|
| PetWindow child | parent top-level refuses focus | clipped/coupled to Drag | Reject |
| OVERFLOW extension | explicitly NoFocus/hit-proxy | corrupts hit/capture | Reject |
| current MainWindow | focus works | large traditional Control Center | Reject as Capsule/Workspace shell |
| QMenu | native dismiss | no draft/container continuity | rollback only |
| independent focusable top-level Tool | explicit IME/focus | independent from Drag; must native-test | **Recommend Capsule/Expanded and Palette candidate** |
| normal top-level Workspace | stable long-lived focus/taskbar | independent | later validation |

Conversation Surface 是 lazy frameless focusable top-level，不能有 `WindowDoesNotAcceptFocus` / show-without-activating when opening for text. Palette 用独立 custom host；final `Tool` vs `Popup` 需 Windows spike，因为产品 dismiss contract 不可交给 Qt default。Spike 必须覆盖 PetWindow NoFocus → Palette → Ask dismiss → Conversation activation/focus 的完整 native chain。

Workspace later 更适合 normal focusable top-level；不要求同一 native window，只要求 visual/task continuity 和 one-P。不要为 z-order 把 Capsule native-parent 到 no-focus PetWindow。

## 24. Input Routing

```text
Character BODY/visible OVERFLOW → PetWindow gesture
  ├─ completed Left Click → existing INTERACT
  ├─ valid Drag → existing Drag
  └─ Right Click → Palette-open intent
Palette open + explicit completed Left Click on Schwarz
  → existing INTERACT once + Palette dismiss + zero Conversation
Palette open + ordinary outside click whose target is not Schwarz
  → Palette dismiss only + no pass-through + zero Character/Conversation action
Palette Ask → ConversationOpenOrRestore intent → coordinator/model
Conversation bounds → input/IME/selection/controls
Palette bounds → navigation/command/dismiss
Workspace bounds → task controls/conversation/artifacts
outside transient on a non-Schwarz target → coordinator dismiss highest allowed only; no pass-through
```

Character-target classification must preserve the existing PetWindow gesture result even while Palette is visible；Palette presence may add a dismiss effect but may not swallow or reinterpret the completed Click。Character Drag 在其 pointer sequence 中最高；Surface event 不经 PetWindow；PetWindow 不读 text state；text selection 不成为 Drag；Right Click inside Palette 不重新 invocation；Expanded/Workspace/Confirmation/Critical Error 不应用普通 outside dismiss。Left Click 和 Conversation invocation 永远是两条独立链。Exact event filter/native hook TBD。

## 25. Anchoring Boundary

Input：Schwarz visible BODY/protected hit bounds、Surface preferred size/variant、containing screen、available work area、DPI logical space、prior placement。Output：side/quadrant、logical geometry、motion origin、fallback status、no-overlap result。

Upper-side preferred，先 directional fallback 再降低尺寸；保持 work area、control order、no visible/hit overlap。Recompute on size variant、Drag end、screen/work-area/DPI/taskbar/monitor change；不得 activate、reset caret 或 replay entry。Exact algorithm/offset TBD。

## 26. Agent Backend Integration Boundary

Current bridge facts：turn_started、agent_state_changed(turn_id,state)、text_delta、turn_completed、turn_cancelled、turn_failed、runtime snapshot/active turn。

Frontend Integration Requirements：stable submit→task correlation；Thinking vs Acting；Waiting reason；user-facing label；reliable semantic progress；cancellability/ack；confirmation summary/scope/consequence/validity/decline；Success/Partial/Error/Cancelled structure/artifacts；Retry/alternative；required foreground-control；stale/duplicate ordering。

Absent facts use conservative UI：no fake Acting/progress/Cancel/Retry/Confirm or Palette hiding sole required control。Frontend 不从 timers、tool names、delta、animation、visibility 或 Submit click 推断 backend lifecycle。

ConversationOpenOrRestore is not one of these backend signals：it stops at frontend presentation until the user submits a draft。本文只规定 frontend 所需 signal contract，不定义 Agent planning、tool routing、execution scheduling、memory、orchestration、MCP 或 backend task lifecycle。

## 27. Test Strategy

Tests target frontend interfaces and observable contracts，not backend planning or implementation details。

| Test | Required contract | Primary level |
|---|---|---|
| A — Left-click Preservation | Character-only completed non-drag click → exactly one Interact；zero Conversation intent | existing unit + Qt + native |
| B — Left-click With Capsule | Capsule/draft remain unchanged；one Interact；no focus transition or duplicate Surface | model + Qt integration |
| C — Drag Regression | threshold-crossed Drag owns sequence；zero Interact；zero Conversation invocation | existing unit + Qt + native |
| D — Right Click | exactly one Action Palette；zero Interact；zero Capsule/native menu simultaneously after cutover | model + Qt proxy + native |
| E — Palette Ask | consume once；Palette dismisses；one Conversation context creates/restores；focus when permitted | model effect order + Qt integration |
| F — Existing Conversation Restore | existing Capsule/Expanded/Workspace context restores；draft preserved；no second Capsule | model + host integration |
| G — Palette Character Interact | Character → Interact reuses exactly the existing semantic used by Left Click | adapter + coordinator + Qt |
| H — Palette Capability Parity | every MVP existing menu capability preserves semantic behaviour/state | adapter + coordinator + tray/Qt |
| I — Blocking Surface Guard | Confirmation/Critical Error priority prevents ordinary Capsule competition and preserves required context | model exhaustive transitions |
| J — No Double-click Conversation | no double-click sequence opens Capsule or delays/duplicates normal Interact | gesture + Qt + native |
| K — Palette + Character Click | Given Palette open，explicit completed non-drag Left Click on Schwarz → exactly one existing Interact；Palette dismisses；zero Conversation；no second click | model effect order + Qt proxy + native |
| L — Palette Ordinary Outside Click | Given Palette open，ordinary outside click targets something other than Schwarz → Palette dismisses without pass-through；zero Interact/Conversation | model effect order + Qt/native desktop target |

Tests K and L are separate contracts and must not be implemented as one generic outside-click assertion：

```text
K — Palette + Character Click
Given Action Palette is open
When a completed non-drag Left Click explicitly targets Schwarz
Then exactly one existing Interact semantic is requested
And Palette is dismissed
And zero Conversation invocation occurs
And no second click is required

L — Palette Ordinary Outside Click
Given Action Palette is open
When an ordinary outside click targets something other than Schwarz
Then Palette is dismissed
And the dismiss event does not pass through
And zero Interact occurs
And zero Conversation invocation occurs
```

Continue pointer、renderer、OVERFLOW、layout、composition/actions、explicit-action、animation、tray、shutdown and smoke suites。Do not duplicate backend state-machine tests。Slice 0 must explain the five broad-suite failures and establish the agreed green gate before production cutover。

## 28. Manual Acceptance

### Character input

- Character-only, Conversation-visible and Agent-active contexts: one Left Click → one existing Interact，never Capsule/focus/toggle；
- Palette open + explicit Schwarz Left Click: one existing Interact + Palette dismiss，zero Conversation，no second click；
- rapid clicks remain independent Interact gestures；Double Click creates no Conversation and does not delay Click；
- threshold Drag, BODY↔OVERFLOW and active-overlay forwarding: move/landing only，zero Interact/Conversation；
- Right Click opens exactly one Palette and performs no command。

### Conversation entry and draft

- Right Click → Palette → Ask: Palette dismisses，one Capsule creates/restores，input focuses once；
- repeated Ask restores same context without duplicate/reset；future shortcut harness yields identical effects；
- Escape/outside/manual collapse, app focus loss and Schwarz Drag preserve exact draft/IME/caret；
- Enter/Shift+Enter/IME and submit acceptance follow the draft contract；opening alone does not start an Agent task。

### Palette and recovery

- Root/Character/System navigation；secondary Interact and all existing character actions use current semantics；
- Pause/topmost/autostart/Control Center/Hide/Quit parity；Settings is not faked by relabeling Control Center；
- ordinary outside click on a non-Schwarz desktop target dismisses without pass-through and produces zero Interact/Conversation；
- Escape/outside/right-click dismiss rules, return focus and tray Show/Quit recovery。

### Agent UI and Windows regression

- Inject correlated Thinking/Acting/Waiting/Success/Partial/Error/Cancelled facts；same-container truth/no focus theft；
- Cancel/Confirm/Retry only when facts authorize them；Confirmation excludes Palette；
- real Schwarz build validates Palette→Ask focus, capture, placement/taskbar/Z-order/topmost/mixed DPI；
- BODY/OVERFLOW transparent hit and Relax/Move/Sit/Sleep/Special/Interact remain unchanged。

## 29. Recommended Vertical Slices

These are implementation-plan inputs，not implementation authorization。

0. **Characterization / Baseline**：freeze targeted green set；diagnose five broad failures and two native skips；define production gate；no behaviour change。
1. **Frontend Presentation State Seam**：Qt-free Surface coordination、one logical Conversation context、draft、semantic focus and ordered effects。
2. **Conversation Capsule Skeleton**：one lazy host、create/restore/collapse/focus/anchor in a non-default-production harness；no Left Click wiring。
3. **Left-click Interact Preservation Gate**：prove new infrastructure leaves Click→Interact and Drag ownership exactly unchanged；failure stops later slices。
4. **Draft Safety**：IME、caret/selection、Palette/focus loss、submit acceptance and safe quit。
5. **Action Palette Shell**：root/same-shell layers and minimal command descriptor adapter；native QMenu remains production path。
6. **Right-click Palette Cutover**：atomically replace native/right-click presentation with Palette；parity、native no-pass-through and independent rollback；tray unchanged。
7. **Ask ArkClaw Conversation Entry**：wire Palette Ask to the shared invocation seam；ordered dismiss/create-or-restore/focus；no pointer semantic changes。
8. **Activity → Result**：only available correlated facts；missing facts conservative；Conversation open alone creates no Agent state。
9. **Expanded Conversation**：same logical context，only if MVP content/complexity need and window validation justify it。
10. **Keyboard Fast Entry**：execute only after exact shortcut contract is approved；must reuse the Slice 7 seam and never instantiate directly。
11. **Workspace**：later independent phase，only after product need and normal top-level/task continuity validation。

No slice binds Conversation to Left Click or assigns Double Click a semantic。Slice 10 remains planned-but-unstartable while `Shortcut: TBD`。

## 30. Rollback Strategy

| Slice | Rollback |
|---|---|
| model / invocation seam | remove unused composition wiring；PetWindow/tray untouched |
| Conversation skeleton | disable/destroy host；context state remains isolated；no pointer binding |
| draft/focus | disable unreleased Surface；never silently discard production draft |
| Palette shell / adapter | remove dormant shell；native menu unchanged |
| Ask entry | disable only Ask producer edge；do not redirect to Left Click/Double Click |
| right-click cutover | restore the one presentation edge to QMenu；commands/Interact/Drag unchanged |
| Activity mapper | disconnect mapper；existing Control Center remains recovery surface |

Left Click and Drag are protected baseline，not rollout switches。Rollback must never turn Left Click into Conversation、duplicate Interact or change threshold/proxy behaviour。

## 31. Risk Register

| Risk | Probability | Impact | Mitigation | Test |
|---|---|---|---|---|
| Left Click stolen/reinterpreted by Conversation | Medium | Critical | preservation gate at existing release seam | A — Left-click Preservation；B — Left-click With Capsule；K — Palette + Character Click |
| Interact delayed for Double Click | Medium | Critical | no double-click timer/semantic | J — No Double-click Conversation；A — Left-click Preservation |
| press phase triggers before Drag decision | Medium | Critical | consume only final gesture outcome | C — Drag Regression；A — Left-click Preservation |
| Drag/OVERFLOW regression | Medium | Critical | keep threshold/transaction/proxies | C — Drag Regression + existing BODY/OVERFLOW regression/native suites |
| Right Click also invokes action/Conversation | Medium | Critical | Palette-open-only intent | D — Right Click |
| Ordinary Palette outside-dismiss passes through and triggers a Character action | Medium | Critical | classify non-Schwarz outside target；consume dismiss event | L — Palette Ordinary Outside Click |
| Explicit Schwarz click while Palette is open is swallowed as dismiss-only | Medium | Critical | Character Click Preservation in every presentation state；Interact + dismiss atomically | K — Palette + Character Click |
| Palette Ask activation loses focus/order | High | High | ordered model effects + native spike | E — Palette Ask + native Windows focus gate |
| duplicate Conversation context/host | Medium | High | model ownership + idempotent invocation | F — Existing Conversation Restore；E — Palette Ask |
| draft/IME loss | Medium | Critical | model ownership/correlated clear/safe quit | B — Left-click With Capsule；F — Existing Conversation Restore + draft/IME regression suite |
| focus stealing | High | High | semantic target + one-shot activation | B — Left-click With Capsule；E — Palette Ask；F — Existing Conversation Restore + native focus gate |
| Palette/Confirmation competition | Medium | High | exclusivity and priority invariants | I — Blocking Surface Guard |
| stale or invented Agent state | Medium | High | mapper correlation; no lifecycle inference | Agent mapper correlation/stale-fact regression suite（planned Slice 8） |
| command/capability loss | Medium | High | descriptor parity + narrow rollback | H — Palette Capability Parity；G — Palette Character Interact |
| Control Center mistaken for Capsule/Settings | Medium | High | explicit secondary role/mapping TBD | H — Palette Capability Parity |
| tray recovery regression | Low/Med | High | no initial tray migration | H — Palette Capability Parity + existing tray regression suite |
| native Z-order/taskbar/DPI defect | Medium/High | High | configured Windows acceptance | D — Right Click；E — Palette Ask；K/L target routing + native Windows gate |
| red baseline masks regression | High | High | Slice 0 classification/green gate | A–L named contracts + broad related regression suite |

## 32. Engineering Findings and Classification

| Finding | Evidence | Classification | Required handling |
|---|---|---|---|
| Broad related suite has five failures | §10.1 | Pre-existing Failure | Slice 0 diagnose/reconcile before production cutover |
| Three menu/role label assertions differ from current UI | current Control Center/role labels | Pre-existing Failure | establish canonical current label; do not confuse label with semantic parity |
| Two smoke processes exit anomalously | pet smoke reports drag-struggle checks；tray smoke reports empty failed list | Pre-existing Failure / attribution gap | make cause observable and establish green gate |
| MainWindow clears draft before correlated acceptance | `_send_message()` evidence | Engineering Validation Required | new Conversation cannot reuse this unsafe ownership path |
| Current MainWindow does not prove full Agent projection | bridge emits more facts than MainWindow presents | Engineering Validation Required | mapper contract only；do not redesign backend |
| Commands are partially presentation-neutral | shared production section，separate system QActions | Engineering Validation Required | minimal descriptor adapter，not general framework |
| Native focus/capture evidence incomplete | Schwarz native probe `2 skipped` | Engineering Validation Required | configured Windows acceptance before cutover |
| Pointer/Drag/right-click forwarding targeted set is green | §10.2 `20 passed` | Relevant Green Baseline | preserve as change gate |

There is no Blocking Relevant Failure for creating an Implementation Plan。Pre-existing failures and validation gaps remain explicit production gates。

## 33. Unknown / TBD

### Blocking Product TBD

**None.** The mouse Conversation entry and Left Click/Drag/Right Click/Double Click semantics are frozen by `06`。

### Blocking Engineering TBD for creating an Implementation Plan

**None.** The plan can sequence validation before production cutover。

### Non-blocking product / engineering TBD and production gates

1. Keyboard `Shortcut: TBD`：exact key、scope、registration and conflict policy；no production binding now。
2. Palette `Tool` vs `Popup` flags and full Palette→Ask activation chain on native Windows。
3. target-aware outside detection：non-Schwarz outside dismiss must not pass through，while explicit Schwarz click must still Interact；plus native QMenu focus destination during rollback period。
4. production Schwarz manifest/Spine bridge setup for the two skipped native tests。
5. root causes and agreed disposition of the five broad-suite failures。
6. submit command→task correlation/acceptance fact。
7. Acting/Waiting/confirmation/cancellability/progress/result/recovery signal details。
8. mixed-DPI/taskbar/topmost placement variants。
9. cross-restart draft policy and detailed IME hide/show handling。
10. direct Settings mapping；retain Control Center until confirmed。
11. reliable manual/Resume active indicator。
12. Context/Voice MVP scope。
13. Workspace window/taskbar strategy and multi-task selection。
14. exact geometry、motion、timing、tokens、icons and new character animations。

Items 2–9 block their respective production slice acceptance，not the act of writing a staged Implementation Plan。

## 34. Readiness Decision

### `READY_WITH_NON_BLOCKING_TBD`

The canonical Design Freeze now provides one unambiguous user-visible entry contract，and this TDD maps it to repository-grounded seams without changing implementation：

1. Left Click preservation and Drag zero-regression have concrete existing decision points and green targeted evidence；
2. Right Click → Palette → Ask has one ordered Conversation invocation interface；
3. one Model owns create/restore、duplicate protection、draft、presentation level and focus target；
4. current Control Center remains secondary/legacy/recovery and does not create a second Capsule architecture；
5. backend states remain presentation projections of runtime facts；missing facts are integration requirements only；
6. pre-existing failures and native unknowns are classified into Slice 0 / per-slice production gates；they no longer masquerade as an unresolved product decision。

This readiness is sufficient to create a later Implementation Plan with explicit gates。**Ready to create Stage 8 Implementation Plan.** It does **not** authorize implementation，does not waive the native Windows/baseline requirements，and this reconciliation stops before creating `08`。

## 35. Decision History

An earlier Phase 7 draft treated Conversation entry as unresolved and framed the work around a possible left-click migration。Phase 6 product reconciliation superseded that assumption and normalized the single authoritative `06`。The active engineering contract is now Left Click → Interact only；Drag → Drag only；Right Click → Palette；Palette Ask/future Shortcut → shared Conversation invocation seam；Double Click → Reserved。Git history preserves the superseded draft；this document contains only the current contract。

---

Production code modified: NO  
Tests modified: NO  
Pet click semantics modified: NO  
Drag semantics modified: NO  
UI implementation started: NO  
Implementation Plan created: NO
