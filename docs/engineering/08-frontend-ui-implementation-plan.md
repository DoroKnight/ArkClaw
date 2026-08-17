# ArkClaw Frontend UI Implementation Plan

> 阶段：Phase 8 — Frontend UI Implementation Plan  
> 类型：Repository-Grounded / Test-First / Incremental Delivery Plan  
> 权威产品输入：`docs/design/06-interaction-freeze-and-prototype-review.md`  
> 权威工程输入：`docs/engineering/07-frontend-ui-architecture-tdd.md`  
> 本文只规定实施顺序、验证门禁与回滚边界；不修改生产代码或测试  
> Plan Readiness：`READY_TO_START_SLICE_0_WITH_NON_BLOCKING_TBD`

## 1. Purpose

本文将 06 已冻结的用户可见合同和 07 已冻结的 frontend architecture 转换为可逐 Slice 实施、独立停止、独立评审和独立回滚的 Stage 9 计划。它不重新选择入口、窗口架构、state ownership 或 backend lifecycle。

实施节奏固定为：

```text
one behavioural seam
→ one failing specification test (Red)
→ minimum production change (Green)
→ agreed regression + native/manual gate
→ review and record evidence
→ next behavioural seam
```

禁止把 Model、Capsule、Palette、Activity 和 Workspace 合并为一次 Big Bang 交付。本文中的 expected path 是变更预测，不是提前冻结 class/file hierarchy。

## 2. Authority / Inputs

权威关系：

```text
01–05 product/design context
        ↓
06 — authoritative frontend product freeze
        ↓
07 — authoritative frontend engineering architecture
        ↓
08 — sequencing, gates, evidence and rollback only
```

已完整复核：

- `docs/product/01-ui-vision.md`
- `docs/product/02-interaction-model.md`
- `docs/product/03-ui-state-machine.md`
- `docs/product/04-ui-design-system.md`
- `docs/design/05-ui-screen-spec.md`
- `docs/design/06-interaction-freeze-and-prototype-review.md`
- `docs/engineering/07-frontend-ui-architecture-tdd.md`

01–05 中关于 single/double click、Palette-open click 或 draft outside-click 的旧讨论，不得覆盖 06。08 若发现与 07 的新 blocking contradiction，必须停止并回到 07 评审；不得在实现 Slice 内偷偷修架构。本轮未发现该类新冲突。

## 3. Implementation Principles

1. **Frozen semantics first**：Left Click 永远是一个既有 Interact；Drag 永远不产生 Interact/Conversation；Right Click 只负责 Palette presentation。
2. **Test public seams**：Model 测试只经 `dispatch(intent/fact) → effects + snapshot`；Host 测试经可见行为与 emitted intent；不测试 private method 或 internal call count。
3. **Vertical TDD**：不先写完所有测试再写所有生产代码。每个 Slice 内以一个 behaviour tracer bullet 完成 Red→Green，再增加下一个行为。
4. **Mocks only at boundaries**：仅在 backend bridge、native OS、time/environment 等边界使用 fake；不 mock 自有 Model/Coordinator/Host 内部协作者来证明实现细节。
5. **One state owner**：Presentation Model 是 Primary Presentation、Foreground Overlay、logical Conversation、draft 和 semantic focus target 的 source of truth；QWidget visibility 只是 effect。
6. **No architecture-purity work**：不顺手重构 PetWindow、统一全部 QAction、重写 tray/MainWindow、移动 renderer 或创建 event bus。
7. **Cutover is atomic**：native QMenu XOR Palette；未满足 native gate 时只能保留 inactive shell/harness。
8. **Facts, not guesses**：Agent projection 只消费可靠 runtime facts；缺失能力成为 `Frontend Integration Requirement` 或 subfeature gate。
9. **Offscreen is not native proof**：涉及 focus、Popup/Tool、outside routing、Z-order、taskbar、DPI、BODY/OVERFLOW 时必须取得真实 Windows 证据。
10. **Stop independently**：每个 Slice 完成后产品仍可安全停留在已交付状态；后续 Slice 不是前一 Slice 正确性的补丁。

全局 Definition of Done：planned tests、required regression、required native/manual gate 全部通过；未修改 forbidden files；无 Critical regression；rollback 可用；证据已记录。任一项不满足，不得进入下一个依赖 Slice。

## 4. Current Baseline

2026-08-14 在当前工作区重新执行 07 记录的命令：

| Baseline | Result | Meaning |
|---|---|---|
| Targeted Click/Drag/OVERFLOW/context set | `20 passed in 2.58s` | current known-green input preservation gate |
| Broad related set | `169 passed, 5 failed, 1 skipped in 10.67s` | not green；must be classified in Slice 0 |
| `tests/qt/test_schwarz_native_input.py` | `2 skipped in 0.27s` | production manifest/bridge absent；not passed |

Known-green command remains the exact 07 §10.2 selection。Broad command remains the exact 07 §10.1 selection。Stage 9 must record command、environment、commit/worktree identity and complete output before making Slice 0 changes。

Repository delta review found no architecture drift from 07：

- `PetPointerGesture.press/move/release` remains the Click/Drag decision point；
- `PetWindow.mouseReleaseEvent` still maps final `CLICK` to USER `ProductionAction.INTERACT`；
- `PetWindow.contextMenuEvent` still creates the native `QMenu`；
- `PetApplicationCoordinator` still owns pet/MainWindow/tray lifecycle composition；
- `ProductionActionMenuSection` still holds shared production Character actions；
- `QtRuntimeBridge` still exposes turn/state/delta/terminal and command result signals；
- `MainWindow._send_message()` still clears input before asynchronous acceptance evidence；
- no Presentation Model、Conversation host or Palette host exists。

## 5. Existing Failure / Skip Disposition

### 5.1 Five broad-suite failures

| Failure | Current classification | Slice to resolve | Blocks which slice | Required evidence |
|---|---|---:|---|---|
| role header expected `Role Pack: schwarz-production` but production renders `ACTIVE PET · SCHWARZ / 黑` | Stale assertion, supported by current production and 06 parity inventory | 0 | Slice 1 until documented disposition | source label、06 role-identity destination、focused test before/after |
| tray view expects `Open Agent Window` instead of `Open ArkClaw Control Center` | Stale assertion | 0 | Slice 1 until documented disposition | current tray source、06 System-layer contract、focused test |
| right-click exit test expects `Open Agent window` | Stale assertion | 0 | Slice 1 until documented disposition | current pet menu source、06 verified capability、focused test |
| `qt_pet_smoke.py` exits 2 with `drag_struggle_entered,drag_struggle_exited` | Smoke observability defect until root cause proves environment or production defect | 0 | Slice 1 if still unclassified；Slice 3/6 if real input defect | isolated reproduction、environment capture、per-check diagnostics、owner/action trace |
| `qt_tray_smoke.py` exits 2 while `failed_checks` is empty | Smoke observability defect | 0 | Slice 1 if cause remains opaque | exit-path instrumentation、resource cleanup facts、independent tray regression result |

Slice 0 may update stale expectations or smoke observability only after recording the independent product/current-source evidence。If either smoke exposes a real production defect，create a separate prerequisite bug change；do not bury its fix in Capsule/Palette commits。

### 5.2 Native two-skip unblock plan

`tests/qt/test_schwarz_native_input.py` requires：

1. `ARKCLAW_PET_ROLE_MANIFEST` points to the existing production Schwarz manifest；
2. `ARKCLAW_SPINE38_BRIDGE_DLL` points to the compatible existing Spine 3.8 bridge DLL；
3. both paths are absolute/existing and `create_optional_production_pet_composition()` returns a non-`None` composition；
4. `QApplication.platformName()` is `windows`，not offscreen；
5. the manifest/assets/hash expectations and bridge ABI preflight pass without modifying assets or expected hashes。

Environment verification record：resolved paths (redacted if necessary)、file existence、manifest pack id、composition-created result、Qt platform name and exact native test output。The environment may remain a known skip at Slice 0 exit，but it becomes mandatory before Slice 3 can close its production preservation gate and again before Slice 6B right-click cutover。Skipped is never recorded as passed。

## 6. Global Protected Contracts

### 6.1 Input invariants

```text
completed non-drag Left Click Schwarz
→ exactly one existing Interact
→ zero Conversation

valid Drag
→ existing Drag/release/landing
→ zero Interact
→ zero Conversation

Right Click Schwarz
→ Palette only
```

Palette-open routes remain separate：explicit Schwarz Left Click → one Interact + Palette dismiss + zero Conversation；ordinary non-Schwarz outside click → dismiss without pass-through + zero Character/Conversation action。

### 6.2 Protected core files / areas

- Spine resources、role manifests、asset hashes and bridge ABI expectations；
- renderer、Spine player、composition/mix、animation timing/action names；
- BODY/OVERFLOW geometry、alpha hit threshold、native hit test and active proxy；
- `PetPointerGesture` threshold and transaction semantics；
- `PetWindow` press/move/release and existing falling/landing path；
- `ProductionAction` identities and Interact semantic；
- taskbar grounding、topmost behaviour and tray Show/Quit recovery；
- backend planner、reasoning、memory、tool routing、scheduler、orchestration、MCP and task lifecycle。

If a Slice discovers it must modify a protected area，stop and require explicit justification、a narrower change forecast and dedicated regression/native gate。No unrelated cleanup is allowed。

## 7. Repository Change Forecast

Exact new filenames are not architecture decisions in 08。Every path labelled candidate has the formal status `Candidate path — confirm before implementation` and must be rechecked against the local package before implementation。

| Slice | Existing files likely touched | New file responsibility | Protected files / limits |
|---:|---|---|---|
| 0 | selected tests；`scripts/qt_pet_smoke.py`；`scripts/qt_tray_smoke.py` | none expected | no product behaviour change；production fix requires separate task |
| 1 | `src/arkclaw/presentation/qt/pet_application.py` composition only | Candidate `src/arkclaw/presentation/...` Qt-free model；candidate Qt coordinator | no visible host；PetWindow gesture untouched |
| 2 | Slice 1 coordinator/model composition | Candidate `qt/ui/...conversation...` host；candidate Qt-free anchoring policy | no production mouse binding；no MainWindow reuse |
| 3 | existing pointer/Qt/native tests；new preservation tests | none expected | no production change unless regression exposes prior Slice defect |
| 4 | model、coordinator、Conversation host；possibly bridge adapter wiring | candidate draft/submission adapter only if needed | do not copy `MainWindow._send_message()` ownership；backend unchanged |
| 5A | production action/coordinator read seams | candidate presentation-neutral command descriptors/adapter | do not rewrite `ProductionActionMenuSection` or tray |
| 5B | model/coordinator | candidate Action Palette host | inactive；native QMenu remains production |
| 6A | native test harness/spike only | candidate target-routing/window-role spike adapter | no production cutover |
| 6B | `PetWindow.contextMenuEvent` edge and composition；Palette host/coordinator | only narrowly justified routing adapter | press/move/release、gesture、OVERFLOW protected unless separate proof |
| 7 | model/coordinator、Palette and Conversation hosts | none beyond confirmed seam modules | no PetWindow pointer change；no backend task on open |
| 8 | bridge connection composition、model/host | candidate Agent Presentation Mapper | Runtime bridge/backend facts not redesigned |
| 9 | Conversation model/host、anchoring policy | no fixed new path | same context/draft/task；no Workspace |
| 10 | composition and shared invocation producer | candidate Windows shortcut adapter | blocked until shortcut contract；no direct Capsule construction |
| 11 | model/coordinator | candidate Workspace host | filenames/layout deferred；no early shell freeze |

Probable new test locations follow current conventions：Qt-free behaviour under `tests/unit/`；QWidget/focus/lifecycle under `tests/qt/`；real Windows routing in `tests/qt/test_schwarz_native_input.py` or a narrowly named companion。New filenames are candidate locations and must be confirmed at each Slice start。

## 8. Slice Dependency Graph

```text
Slice 0 Baseline
  ↓
Slice 1 Presentation State Seam
  ↓
Slice 2 Capsule Skeleton (inactive harness)
  ↓
Slice 3 Left-click/Drag Preservation Gate ── hard stop gate
  ↓
Slice 4 Draft Safety
  ↓
Slice 5A Command Adapter → Slice 5B Palette Shell (inactive)
  ↓
Slice 6A Native Window/Target-routing Spike
  ↓
Slice 6B Atomic Right-click Cutover
  ↓
Slice 7 Ask ArkClaw Entry ── Milestone 1
  ├─→ Slice 8 Activity → Result [backend fact gates]
  │      ↓
  │    Slice 9 Expanded Conversation [capacity evidence]
  └─→ Slice 10 Keyboard Fast Entry [shortcut contract，independent branch]

Slice 8 + Slice 9 production-proven
  ↓
Slice 11 Workspace [later independent milestone]
```

Slice 5 and 6 are deliberately split：command reuse is reviewable independently from UI shell，and native target-routing evidence is obtained before production cutover。

## 9. Slice 0 — Characterization / Baseline

| Field | Plan |
|---|---|
| Goal | Produce a trustworthy known-green gate，a named pre-existing failure list，environment skips and production blockers；add no UI。 |
| Why this slice exists | A red broad baseline would otherwise hide regressions introduced by later frontend work。 |
| Preconditions | 08 reviewed for Slice 0 scope；dedicated clean branch/worktree；exact baseline commands and environment recorded。 |
| Dependencies | None。This is the only Slice Stage 9 may start immediately。 |
| Product contracts covered | 06 gesture baseline and current verified capability inventory；no product behaviour change。 |
| Engineering contracts covered | 07 §10 baseline classification、§27 existing regression suites、§32 findings。 |

Repository evidence：

| File | Class / method | Current role | Why touched / protected |
|---|---|---|---|
| `tests/qt/test_pet_production_actions.py` | three current menu/action tests | role label、Interact、production action characterization | stale role assertion may be corrected only with independent evidence |
| `tests/qt/test_pet_window.py` | tray/menu and two smoke wrapper tests | menu labels、shutdown、smoke process contract | stale labels and opaque smoke exits are isolated here |
| `scripts/qt_pet_smoke.py` | smoke probe main/check aggregation | pet/drag/render resource smoke | observability may be improved；behaviour must not be changed to make it green |
| `scripts/qt_tray_smoke.py` | smoke probe main/exit aggregation | tray lifecycle/resource cleanup smoke | empty `failed_checks` with exit 2 requires diagnosable cause |
| 07 §10.2 test set | named unit/Qt tests | known-green Click/Drag/OVERFLOW/context baseline | protected regression gate |

| Field | Plan |
|---|---|
| Expected files to change | Only the specifically stale tests and/or the two smoke scripts after classification。No production file expected。 |
| Files forbidden to change | `src/`、assets/manifests/hashes、PetWindow、PetPointerGesture、renderer、tray production code。If a real production defect is found，stop and open a separately scoped prerequisite。 |
| Test-first requirements | First reproduce each failure individually；for smoke observability，write/adjust the probe assertion that exposes the missing reason before changing diagnostics；for stale assertions，record 06/current-source expected literal before editing the test。 |
| Tests expected to add | Focused characterization or observability corrections around current role label、Control Center label and smoke exit reason；probable existing files above。No broad expectation rewrite。 |
| Existing regression tests | Exact targeted 20；exact broad 175 cases；focused failed tests；native test command recorded even if skipped。 |
| Implementation boundary | Test expectation correction and diagnostic observability only。No behaviour or UI feature。 |
| Explicit non-goals | Do not “fix all red”；do not alter approved labels；do not fix an exposed production bug in the same change；do not prepare Palette code。 |
| Stop conditions | Baseline differs materially from §4；a label lacks 06/current-source evidence；a smoke failure proves a production input/lifecycle defect；diagnostics require production semantic change。 |
| Native Windows gate | Attempt environment verification from §5.2 and record outcome。Native skips may remain known，but cannot be called passed。 |
| Manual acceptance | Confirm current tray/pet menu labels and current Interact/Drag behaviour are unchanged after test-only/diagnostic changes。 |
| Rollback boundary | Revert Slice 0 test/diagnostic commit set only；no production rollback。 |
| Exit criteria | All five failures have one recorded classification；known-green command remains green；stale assertions are independently justified；smoke failures are resolved or produce precise known blocker evidence；skip inventory recorded。 |
| Evidence to record | Commands/results、environment、failure-by-failure disposition、changed files、before/after diagnostics、known blocker list and rollback commit。 |

## 10. Slice 1 — Frontend Presentation State Seam

| Field | Plan |
|---|---|
| Goal | Introduce the Qt-free Presentation Model and application-lifetime Coordinator seam with zero production-visible UI behaviour change。 |
| Why this slice exists | Surface exclusivity、one Conversation context、draft/focus ownership and ordered effects need one testable source of truth before any QWidget host。 |
| Preconditions | Slice 0 exit criteria met；public Model seam from 07 accepted unchanged。 |
| Dependencies | Slice 0。 |
| Product contracts covered | 06 one Presentation/one foreground Overlay、single Conversation context、dismiss ≠ cancel、backend truth。 |
| Engineering contracts covered | 07 §12–14 and §20：`dispatch(intent_or_fact) → effects + immutable snapshot`；Coordinator executes effects；hosts are absent in this Slice。 |

Repository evidence：

| File | Class / method | Current role | Why touched / protected |
|---|---|---|---|
| `src/arkclaw/presentation/qt/pet_application.py` | `PetApplicationCoordinator.__init__`, `main` | application-lifetime composition and existing lifecycle | likely composition point；must remain behaviourally inert |
| `src/arkclaw/presentation/pet_pointer_gesture.py` | `PetPointerGesture` | existing pointer transaction | protected；Model must not consume raw mouse decisions |
| `src/arkclaw/presentation/qt/platform/runtime_bridge.py` | `QtRuntimeBridge` signals | frontend boundary facts | not connected to Agent projection yet except test fake |
| candidate `src/arkclaw/presentation/...` | new Model interface | no current owner exists | final filename confirm before implementation |
| candidate `src/arkclaw/presentation/qt/...` | new Presentation Coordinator | no current owner exists | created by existing application coordinator；no host effects yet |

| Field | Plan |
|---|---|
| Expected files to change | `pet_application.py` narrowly for composition；candidate Qt-free model and Qt coordinator modules；candidate `tests/unit/test_frontend_presentation_model.py` and coordinator unit/Qt test。Final names confirm locally。 |
| Files forbidden to change | PetWindow、PetPointerGesture、effect overlay、renderer、MainWindow、system tray、production menu、backend。 |
| Test-first requirements | One intent at a time：initial snapshot → Conversation create/restore decision → duplicate suppression → P/O exclusivity → blocking guard → semantic focus effect。Each test uses only public Model interface。 |
| Tests expected to add | Unit specifications for immutable snapshot、ordered effects、one P/O、one Conversation context、duplicate idempotence、draft/focus preservation、stale fact rejection。 |
| Existing regression tests | Slice 0 known-green + broad gate；pet production lifecycle and pointer suites。 |
| Implementation boundary | In-memory state/effects and inert composition only；effects may be recorded by a test adapter but show no UI。 |
| Explicit non-goals | No QWidget、Capsule、Palette、anchor geometry、backend task、Right Click/Left Click wiring or Workspace。 |
| Stop conditions | Any existing visible behaviour changes；Model requires QWidget visibility to decide；new generic event bus/command framework appears；PetWindow must be refactored。 |
| Native Windows gate | None for pure Model；composition smoke must prove no extra window/taskbar/focus behaviour。 |
| Manual acceptance | Launch current pet：only Schwarz/current Control Center/tray behaviours remain；Left Click/Drag/right-click native menu unchanged。 |
| Rollback boundary | Remove inert composition and new unused modules；no state migration。 |
| Exit criteria | Unit model suite green；snapshot/effect interface stable enough for Slice 2；all current UI/input regressions unchanged；zero visible new Surface。 |
| Evidence to record | Public seam、test names/results、composition diff、visible-window inventory、regression output、residual API naming TBD。 |

## 11. Slice 2 — Conversation Capsule Skeleton

| Field | Plan |
|---|---|
| Goal | Build one lazy-created、independent focusable Conversation host in a non-production harness。 |
| Why this slice exists | Validate lifecycle、focus、IME and anchoring boundaries before any production mouse entry。 |
| Preconditions | Slice 1 Model/Coordinator stable；candidate file names rechecked；Windows Qt platform available for basic focus probe。 |
| Dependencies | Slice 1。 |
| Product contracts covered | 06 Capsule Compact A/B identity、explicit-entry-only focus、anchor/no-overlap、opening UI creates no Agent state。 |
| Engineering contracts covered | 07 §20 Conversation architecture、§23 independent focusable top-level Tool recommendation、§25 anchoring input/output。 |

Repository evidence：

| File | Class / method | Current role | Why touched / protected |
|---|---|---|---|
| Slice 1 Coordinator/Model candidate | public intent/effect seam | owns lifecycle decisions | host must render/emit only |
| `src/arkclaw/presentation/qt/pet/pet_window.py` | `_apply_window_flags`, geometry exposure | no-focus character anchor | read as anchor source；do not parent input host or change flags |
| `src/arkclaw/presentation/qt/ui/main_window.py` | `MainWindow` | legacy Control Center | protected；not Capsule shell |
| candidate `src/arkclaw/presentation/qt/ui/...conversation...` | new host | no current implementation | final filename confirm |
| candidate Qt-free anchoring module | policy input/output | no current implementation | exact algorithm remains later validation |

| Field | Plan |
|---|---|
| Expected files to change | Coordinator/Model candidate；new Conversation host candidate；possibly Qt-free anchoring policy；candidate unit/Qt tests。 |
| Files forbidden to change | PetWindow input methods、PetPointerGesture、contextMenuEvent、OVERFLOW、renderer、MainWindow send flow、backend。 |
| Test-first requirements | Lazy create once → restore same host → collapse without destroy → focus semantic target → compact A/B state → anchor stays in work area/no Schwarz hit overlap → opening emits no backend/Agent projection effect。 |
| Tests expected to add | Unit anchoring constraints；Qt host lifecycle/focus/IME/Enter/Shift+Enter/Escape tests；single-host duplicate test；no-Agent-state-on-open test。Probable candidate `tests/qt/test_conversation_surface.py`。 |
| Existing regression tests | Slice 0 gate、pet window/effect overlay/render layout、Control Center lifecycle。 |
| Implementation boundary | Development/test harness activation only；text editing and Surface state skeleton；no production submit or Character entry。 |
| Explicit non-goals | No Right Click cutover、Left Click binding、Palette、Activity projection、final visual tokens、Expanded Conversation P or Workspace。 |
| Stop conditions | Host must become PetWindow child；focus requires changing PetWindow no-focus flags；host overlaps protected hit pixels；offscreen-only behaviour contradicts native probe。 |
| Native Windows gate | Validate independent Tool activation/focus、IME input、no unintended taskbar entry、no PetWindow focus mutation and basic Z-order on Windows。Real Schwarz/OVERFLOW combined gate is deferred to Slice 3/6。 |
| Manual acceptance | Harness opens one Capsule，typing/IME works，collapse/restore preserves input state，pet still Click/Drags/right-clicks normally。 |
| Rollback boundary | Disable/remove harness and host composition；Slice 1 Model remains inert。 |
| Exit criteria | Host lifecycle/focus/anchor tests and basic native gate pass；no production input edge exists；regression suites unchanged。 |
| Evidence to record | Window flags chosen for Conversation host、Qt platform、focus trace、screenshots of edge placement、test outputs、window inventory、changed files。 |

## 12. Slice 3 — Left-click Preservation Gate

| Field | Plan |
|---|---|
| Goal | Prove Slice 1–2 infrastructure leaves every existing character pointer semantic unchanged。 |
| Why this slice exists | This is the hard release gate before draft/Palette work；it is validation，not a migration。 |
| Preconditions | Slice 2 complete；production Schwarz native environment from §5.2 available before final exit。 |
| Dependencies | Slice 2。Failure blocks all later Slices。 |
| Product contracts covered | 06 Left Click all-state invariant、Drag mutual exclusion、Double Click reserved、Palette contracts later remain zero Conversation。 |
| Engineering contracts covered | 07 §11、§15–16 and Tests A/B/C/J；BODY/OVERFLOW proxy preservation。 |

Repository evidence：

| File | Class / method | Current role | Why touched / protected |
|---|---|---|---|
| `src/arkclaw/presentation/pet_pointer_gesture.py` | `press/move/release` | sole Click/Drag decision | protected，expected production changes none |
| `src/arkclaw/presentation/qt/pet/pet_window.py` | mouse press/move/release | final Click→Interact and Drag chain | protected |
| `src/arkclaw/presentation/qt/pet/pet_effect_overlay.py` | pointer/context forwarding | BODY/OVERFLOW continuity | protected |
| existing pointer/window/effect tests | named 07 §10.2 tests | known-green evidence | extend only through public behaviour |
| `tests/qt/test_schwarz_native_input.py` | native Windows test | real Schwarz click/drag/context routing | must be unskipped before exit |

| Field | Plan |
|---|---|
| Expected files to change | Test files only if additional state-context characterization is missing；production files expected none。 |
| Files forbidden to change | All pointer/renderer/asset/animation production paths。If a prior Slice caused regression，fix or rollback that Slice，not the protected core。 |
| Test-first requirements | Add characterization before remediation。If it is already green，record green without manufacturing Red；any failing test points to Slice 1/2 rollback/fix。 |
| Tests expected to add | Capsule-exists + Left Click；Agent projection contexts + Left Click；no Double-click Conversation；possibly harness-level no-focus/toggle assertion。Palette-specific K/L remain Slice 6。 |
| Existing regression tests | Exact 20；broad gate；all pointer、render layout、effect overlay and native Schwarz tests。 |
| Implementation boundary | Verification and correction of Slice 1/2 only。No new user feature。 |
| Explicit non-goals | No new gesture、no delay/coalescing、no Capsule entry、no threshold change。 |
| Stop conditions | Left Click not exactly one Interact；Drag yields Interact/Conversation；OVERFLOW route differs；native tests remain skipped at final gate；Double Click opens/focuses UI。 |
| Native Windows gate | Both parametrized Schwarz native tests pass with `windows` platform and production composition；record BODY/OVERFLOW routes for Click and Drag。 |
| Manual acceptance | Character-only、harness Capsule and Agent-state fixtures：first click Interacts once；Drag/landing unchanged；rapid/double clicks create no Conversation。 |
| Rollback boundary | Roll back offending Slice 1/2 commit set；do not patch gesture semantics。 |
| Exit criteria | Tests A/B/C/J and existing native/regression gates green；zero forbidden production changes；manual acceptance passes。 |
| Evidence to record | Native environment proof、test output、manual matrix、changed-file audit、rollback decision and any residual native risk。 |

## 13. Slice 4 — Draft Safety

| Field | Plan |
|---|---|
| Goal | Make draft ownership、submission snapshots and clearing rules reliable before wiring a production Conversation entry。 |
| Why this slice exists | Draft loss is irreversible user harm；the current legacy window clears input before asynchronous acceptance and cannot define Capsule semantics。 |
| Preconditions | Slice 3 gate green；runtime completion semantics reverified against current code/tests。 |
| Dependencies | Slice 3。 |
| Product contracts covered | 06 Compact A/B draft preservation、restore/focus rules、submit must not fabricate Agent state。 |
| Engineering contracts covered | 07 §20–22、Tests B/F；Frontend Integration Requirement for exact acceptance correlation。 |

Repository evidence：

| File | Class / method | Current role | Why touched / protected |
|---|---|---|---|
| Slice 1 Model/Coordinator | draft and effects | future authoritative draft owner | extend through public commands/snapshots |
| `src/arkclaw/presentation/qt/ui/main_window.py` | `_send_message` | clears legacy editor before async evidence | reference only；must not be copied or changed |
| `src/arkclaw/presentation/qt/platform/runtime_bridge.py` | `send_message`、completion/failure signals | returns command id and projects runtime completion | verify whether it proves exact snapshot acceptance |
| runtime bridge tests | public signal behaviour | current integration evidence | extend at boundary only if contract exists |

| Field | Plan |
|---|---|
| Expected files to change | Model/Coordinator candidates；Conversation host binding；draft-focused unit/Qt tests；bridge adapter only if an already-supported correlation must be exposed。 |
| Files forbidden to change | MainWindow legacy semantics、backend planner/runtime lifecycle、PetPointerGesture/PetWindow input、assets/renderer。 |
| Test-first requirements | revision-tagged snapshot submit；collapse/restore preserves text/caret/selection/IME；accepted exact snapshot clears only that revision；newer edit survives old completion；failure preserves draft；duplicate completion is idempotent。 |
| Tests expected to add | `ConversationDraftModel` public contract suite；Qt editor binding/IME suite；bridge correlation contract tests where supported。 |
| Existing regression tests | Slice 0/3 gates；runtime bridge/controller tests；legacy MainWindow tests unchanged。 |
| Implementation boundary | Local draft lifecycle plus proven acceptance adapter；no visual Activity and no backend lifecycle design。 |
| Explicit non-goals | No optimistic clear、task planning、turn scheduler、memory、MCP、history persistence or retry orchestration。 |
| Stop conditions | Exact submitted snapshot cannot be correlated to acceptance；any completion clears newer text；IME/caret/selection is lost；solution requires backend redesign。 |
| Native Windows gate | Real editor IME composition、focus loss/restore and collapse/restore preservation on Windows。 |
| Manual acceptance | Type with IME，submit，edit again before completion，then observe only the accepted snapshot clears；failure keeps recoverable text。 |
| Rollback boundary | Remove acceptance adapter/binding while retaining inert Model and host；never migrate user draft destructively。 |
| Exit criteria | Draft suite green；the evidence states either a proven acceptance seam or a named blocking Frontend Integration Requirement。Production submit remains disabled if unproven。 |
| Evidence to record | Signal timeline、command/snapshot association proof、test output、IME/manual trace、blocked capabilities if any。 |

## 14. Slice 5 — Action Palette Shell

Slice 5 is deliberately split so information architecture cannot accidentally become a production input migration。

### 14.1 Slice 5A — Presentation-neutral Action Descriptors

| Field | Plan |
|---|---|
| Goal | Adapt existing commands into minimal presentation-neutral Palette descriptors without duplicating command semantics。 |
| Why this slice exists | The Palette must reuse Agent、Character and System actions while remaining independent of the legacy menu widget。 |
| Preconditions | Slice 4 complete or production submit explicitly blocked without affecting Palette work。 |
| Dependencies | Slice 4。 |
| Product contracts covered | 06 Palette hierarchy、one existing Interact semantic、Ask ArkClaw as explicit conversation action。 |
| Engineering contracts covered | 07 §17–19、§24；single command execution seam and capability-aware descriptors。 |

Repository evidence：

| File | Class / method | Current role | Why touched / protected |
|---|---|---|---|
| `src/arkclaw/presentation/qt/ui/production_action_menu.py` | `ProductionActionMenuSection` | current production command grouping | extract/adapt semantics，do not copy execution logic |
| `src/arkclaw/presentation/qt/platform/system_tray.py` | `SystemTrayController` | system/app command access | preserve tray semantics |
| `src/arkclaw/presentation/qt/pet_application.py` | coordinator command callbacks | current execution owner | reuse callbacks through one adapter |
| candidate presentation-neutral descriptor module | command id/label/group/enabled | does not exist | confirm path before implementation |

| Field | Plan |
|---|---|
| Expected files to change | Minimal descriptor/adapter candidate；focused unit tests；narrow command-source composition if required。 |
| Files forbidden to change | PetWindow context/input、QMenu cutover path、backend、renderer/assets、Conversation UI。 |
| Test-first requirements | Stable command identity；Agent/Character/System grouping；disabled reason；exactly-once dispatch；Interact descriptor points to existing semantic；Ask emits only conversation intent。 |
| Tests expected to add | Descriptor projection and command-dispatch unit suite。 |
| Existing regression tests | Production action menu、tray、PetApplication and exact/broad baseline suites。 |
| Implementation boundary | Data/command adapter only；no visible Palette。 |
| Explicit non-goals | No final labels/icons/order beyond 06、no native flags、no context-menu replacement。 |
| Stop conditions | Adapter duplicates command behaviour；Interact becomes a new implementation；tray/control capability disappears。 |
| Native Windows gate | None；pure descriptor seam。 |
| Manual acceptance | Development inspection shows the same action reaches the same existing callback exactly once。 |
| Rollback boundary | Remove adapter and tests；legacy menus remain untouched。 |
| Exit criteria | Descriptor tests green；capability inventory matches baseline；zero visible UI change。 |
| Evidence to record | Command mapping table、public adapter API、test output、capability diff。 |


### 14.1-P Slice 5A-P — Resume Autonomous Shared Capability (User-Approved Prerequisite)

User-initiated narrow scope expansion approval (Slice 5A-P):

> Slice 5A-P authorizes one behavior-preserving extraction of Resume Autonomous
> validity from PetWindow into a Qt-free application-level capability
> (`can_resume_autonomous(...)` in `src/arkclaw/application/pet/pet_production_actions.py`).
> PetWindow remains otherwise Protected Core.
> No Character input, animation, lifecycle, QMenu cutover,
> or command behavior change is authorized.

The one capability is consumed by the PetWindow execution guard, the
ProductionActionMenuSection enabled-state and the Command Descriptor Adapter
projection; no second implementation of the Resume validity rule exists.

### 14.2 Slice 5B — Inactive Palette Host

| Field | Plan |
|---|---|
| Goal | Build the Palette shell and navigation in an explicit test/development harness only。 |
| Why this slice exists | Host behaviour must be testable before right-click ownership changes。 |
| Preconditions | Slice 5A descriptors stable。 |
| Dependencies | Slice 5A。 |
| Product contracts covered | 06 Anchored Action Palette structure、dismiss、Character sublevel and Ask action placement。 |
| Engineering contracts covered | 07 §17–19、§23–25；Coordinator remains policy owner。 |

Repository evidence：

| File | Class / method | Current role | Why touched / protected |
|---|---|---|---|
| Slice 5A descriptor adapter | public descriptor/dispatch seam | Palette data source | sole action source |
| candidate `.../ui/...action_palette...` | new Qt host | no current implementation | inactive shell only |
| Slice 1 Coordinator | Palette open/dismiss/select intents | presentation policy | extend without production event edge |
| PetWindow/contextMenuEvent | production right-click owner | still QMenu | protected until 6B |

| Field | Plan |
|---|---|
| Expected files to change | Inactive Palette host candidate；Coordinator/Model Palette states；unit/Qt navigation tests。 |
| Files forbidden to change | `contextMenuEvent`、mouse press/move/release、legacy production QMenu path、backend、renderer/assets。 |
| Test-first requirements | one root Palette；sublevel/back；Escape/select dismiss；disabled actions do not dispatch；selection exactly once；opening itself performs no action。 |
| Tests expected to add | Palette model/navigation/dispatch Qt suite in harness。 |
| Existing regression tests | Slice 0–5A gates；legacy right-click/menu/tray tests。 |
| Implementation boundary | Inactive shell and model only；not reachable from production Schwarz。 |
| Explicit non-goals | No outside-click pass-through claim、native flag decision、Conversation creation or QMenu removal。 |
| Stop conditions | Host requires two command sources；selection dispatches twice；legacy menu becomes unreachable before 6B。 |
| Native Windows gate | Harness-only keyboard/focus smoke；authoritative Tool-vs-Popup gate is Slice 6A。 |
| Manual acceptance | Harness opens Palette，navigates Character，executes test action once，Escape closes。Production right click still opens legacy menu。 |
| Rollback boundary | Remove inactive host/composition；5A descriptors can remain inert。 |
| Exit criteria | Harness tests green；production right-click unchanged；host ready for native flag spike。 |
| Evidence to record | Navigation trace、dispatch count、visible-window inventory、test results。 |

## 15. Slice 6 — Right-click Palette Cutover

### 15.1 Slice 6A — Tool-vs-Popup Native Spike

| Field | Plan |
|---|---|
| Goal | Select Palette window semantics from measured Windows behaviour，especially explicit Schwarz-target versus ordinary outside dismissal。 |
| Why this slice exists | Qt flag names do not prove focus、pass-through、Z-order or target classification on native Windows。 |
| Preconditions | Slice 5B inactive host；production Schwarz manifest/bridge environment available。 |
| Dependencies | Slice 5B。Hard gate before 6B。 |
| Product contracts covered | 06 K/L distinction、dismiss-first rules、no silent click stealing、Calm Desktop。 |
| Engineering contracts covered | 07 §23、§26–27、Tests D/K/L and native validation。 |

Repository evidence：

| File | Class / method | Current role | Why touched / protected |
|---|---|---|---|
| inactive Palette host | window flags/event routing | candidate Surface | spike variants only |
| `pet_window.py` / `pet_effect_overlay.py` | native target/proxy paths | Schwarz target identity | observe，do not alter pointer semantics |
| `tests/qt/test_schwarz_native_input.py` | production native harness | real route evidence | extend with Palette cases |

| Field | Plan |
|---|---|
| Expected files to change | Spike/test-only flag configuration；native Palette test harness；decision evidence。No production cutover。 |
| Files forbidden to change | PetPointerGesture semantics、production contextMenuEvent edge、renderer/assets/backend。 |
| Test-first requirements | For each candidate prove K explicit Schwarz click = dismiss + one Interact + no Conversation/second click；L ordinary outside = dismiss + no pass-through/action；also focus、keyboard、Z-order、taskbar and restore。 |
| Tests expected to add | Native Tool and Popup comparison cases with target-labelled event traces。 |
| Existing regression tests | Native Schwarz input、effect overlay、window flags、Slice 3 gates。 |
| Implementation boundary | Reversible spike and written choice only。 |
| Explicit non-goals | No assumption that Qt Popup auto-dismiss satisfies K/L；no production ownership change。 |
| Stop conditions | Neither candidate can prove K and L；native prerequisites skipped；choice relies only on offscreen tests。 |
| Native Windows gate | Mandatory，unskipped，with production Schwarz composition and `windows` platform。 |
| Manual acceptance | Open Palette near center/edges；test ordinary desktop click，explicit Schwarz BODY/OVERFLOW click，keyboard focus，Alt-Tab/taskbar and topmost behaviour。 |
| Rollback boundary | Remove spike flag branch/test harness；production QMenu remains authoritative。 |
| Exit criteria | One candidate has evidence for every matrix row in §21，or 6B is blocked with a precise unresolved native contract。 |
| Evidence to record | OS/Qt/platform values、window flags、event trace、screenshots/video、matrix verdict and rejected option。 |

### 15.2 Slice 6B — Atomic Right-click Cutover

| Field | Plan |
|---|---|
| Goal | Replace the production Schwarz right-click QMenu edge with exactly one Palette edge while preserving all other pointer semantics。 |
| Why this slice exists | Product freeze requires Palette；atomic XOR cutover avoids native menu and Palette coexistence。 |
| Preconditions | 6A decision passes；native environment available；5B host/5A commands green。 |
| Dependencies | Slice 6A。 |
| Product contracts covered | 06 Right Click → Palette only；K/L；Left Click/Drag invariants。 |
| Engineering contracts covered | 07 §17–19、§26–27；Tests D/H/K/L。 |

Repository evidence：

| File | Class / method | Current role | Why touched / protected |
|---|---|---|---|
| `src/arkclaw/presentation/qt/pet/pet_window.py` | `contextMenuEvent` | current native menu entry | expected single production cutover edge |
| `src/arkclaw/presentation/qt/pet_application.py` | composition/callback wiring | owns app commands | narrow Palette composition |
| inactive Palette host + Coordinator | open/dismiss/select | prevalidated | activate without duplicating policy |
| pointer gesture and mouse methods | Click/Drag | protected core | no semantic changes permitted |

| Field | Plan |
|---|---|
| Expected files to change | `pet_window.py` context edge only as needed；`pet_application.py` composition；Palette host/Coordinator；focused unit/Qt/native tests。 |
| Files forbidden to change | PetPointerGesture thresholds/semantics、mouse press/move/release、renderer/assets/animation、backend。 |
| Test-first requirements | D right-click opens one Palette/zero actions；H command parity；K/L exact routing；legacy QMenu and Palette are mutually exclusive；all Click/Drag states unchanged。 |
| Tests expected to add | Production composition/cutover tests；native Palette BODY/OVERFLOW/outside route tests；capability parity test。 |
| Existing regression tests | All Slice 0–6A gates、menu/tray tests、native Schwarz tests、broad suite。 |
| Implementation boundary | One right-click entry replacement and required composition。 |
| Explicit non-goals | No Ask-to-Capsule wiring（Slice 7）、Activity、visual polish or new commands。 |
| Stop conditions | Menu+Palette both appear；Right Click Interacts/opens Conversation；K/L fail；Left Click/Drag changes；capability disappears。 |
| Native Windows gate | Mandatory D/H/K/L plus BODY/OVERFLOW，focus，Z-order，topmost，taskbar and edge placement。 |
| Manual acceptance | Right click opens one anchored Palette；ordinary outside silently dismisses；explicit Schwarz click dismisses and Interacts exactly once；all actions still reachable。 |
| Rollback boundary | One production composition/input-edge commit restores legacy QMenu；new inactive modules can remain unreachable。 |
| Exit criteria | XOR cutover、capability parity、native and broad gates green；rollback rehearsed as diff review。 |
| Evidence to record | Before/after event maps、native trace、capability inventory、tests、changed-file audit、rollback commit boundary。 |

## 16. Slice 7 — Ask ArkClaw Conversation Entry

| Field | Plan |
|---|---|
| Goal | Wire Palette → Ask ArkClaw to a single reusable create/restore/focus Conversation intent。 |
| Why this slice exists | This is the frozen primary discoverable mouse-driven Conversation entry and completes the first usable vertical interaction。 |
| Preconditions | Slice 6B cutover green；Slice 2 host and Slice 4 draft seam green；production submit stays disabled if acceptance is unproven。 |
| Dependencies | Slice 6B and Slice 4。 |
| Product contracts covered | 06 Ask flow、dismiss-before-open、one Surface、focus exactly once、Right Click alone zero Conversation。 |
| Engineering contracts covered | 07 §18–20、§26；Tests E/F/I。 |

Repository evidence：

| File | Class / method | Current role | Why touched / protected |
|---|---|---|---|
| Palette descriptor/host | Ask selection | emits semantic command | consume once |
| Slice 1 Coordinator | open/restore/focus effects | policy owner | canonical invocation seam |
| Conversation host | lazy create/restore | inactive user Surface | production activation |
| `pet_application.py` | composition | process lifecycle owner | narrow wiring only |

| Field | Plan |
|---|---|
| Expected files to change | Coordinator/Model、Palette selection wiring、Conversation host composition、focused unit/Qt/native tests。 |
| Files forbidden to change | Pet click/drag methods、context semantic after 6B、backend lifecycle、MainWindow legacy send path、renderer/assets。 |
| Test-first requirements | E order: select → Palette dismissed → exactly one create/restore → input focus；F repeated/stale intent no duplicate；I no confirmation collision；Right Click alone zero Conversation；open emits zero backend task。 |
| Tests expected to add | End-to-end presentation seam tests and production Qt focus/duplicate tests。 |
| Existing regression tests | All 0–6 gates，especially A–D/H/K/L and native cutover。 |
| Implementation boundary | Explicit Ask invocation and reusable `open_or_restore_conversation` seam。 |
| Explicit non-goals | No direct Left Click/Double Click entry、no shortcut binding、Activity projection、Expanded Conversation or Workspace。 |
| Stop conditions | Focus before Palette dismiss；duplicate host；open starts a task；Right Click alone opens Conversation；Left Click changes。 |
| Native Windows gate | Ask from BODY/OVERFLOW Palette；dismiss ordering；focus/IME；single window；restore preserved draft；Z-order/taskbar。 |
| Manual acceptance | Right Click → Ask → one focused Capsule；repeat restores it；collapse and restore preserve draft；pet Click/Drag remain exact。 |
| Rollback boundary | Remove the Ask invocation edge only；Palette and inactive Conversation infrastructure remain independently usable/testable。 |
| Exit criteria | E/F/I and native focus/duplicate tests green；first seven Slice gates green；Milestone 1 criteria in §28 met。 |
| Evidence to record | Ordered effect/event trace、window identity、focus target、draft state、test outputs、manual video/screenshots。 |

## 17. Slice 8 — Activity → Result

| Field | Plan |
|---|---|
| Goal | Map verified backend facts into conservative user-facing Thinking、Acting、Waiting、Success and Error projections plus Action/Result UI。 |
| Why this slice exists | Users need legible progress without exposing tool noise，but the frontend must not invent or redesign backend lifecycle。 |
| Preconditions | Slice 7 vertical entry stable；required runtime facts inventoried with backend owners。 |
| Dependencies | Slice 7。 |
| Product contracts covered | 06 presentation-state projection、Action/Result priority、technical detail hidden by default、character feedback coordination。 |
| Engineering contracts covered | 07 §12–14、§21–22；Frontend Integration Requirements remain contracts，not backend designs。 |

Repository evidence：

| File | Class / method | Current role | Why touched / protected |
|---|---|---|---|
| `runtime_bridge.py` | turn/state/delta/terminal signals | current runtime fact ingress | consume only documented facts |
| Slice 1 Model/Coordinator | backend fact → snapshot/effect | presentation policy | add pure mapper with stale-event defence |
| Conversation host | presentation renderer | Compact Surface | render projection，not infer lifecycle |
| PetWindow/animation paths | character feedback | existing pet semantics | protected unless separately proven mapping seam exists |

| Field | Plan |
|---|---|
| Expected files to change | Presentation mapper/model/Coordinator；Action/Result view candidates；bridge adapter only for existing facts；unit/Qt tests。 |
| Files forbidden to change | Agent planning/tool routing/scheduling/memory/orchestration/MCP/backend lifecycle；pointer gestures；renderer/assets absent a separate approved scope。 |
| Test-first requirements | Known fact mapping；unknown/missing fact degrades safely；stale task event ignored；terminal precedence；Error hides technical details；no fake progress/cancel/retry/confirmation。 |
| Tests expected to add | Mapper table suite including stale/out-of-order facts；Action/Result priority suite；capability-gating tests。 |
| Existing regression tests | A–L presentation contracts、runtime bridge/controller suites、Milestone 1 native gates。 |
| Implementation boundary | Presentation projection of verified facts and minimal surfaces only。 |
| Explicit non-goals | Backend state machine、planner、tool protocol、confirmation authority、task cancellation implementation、raw logs。 |
| Stop conditions | UI infers Acting/Waiting reason without signal；stale event wins；unsupported control is enabled；backend change becomes necessary without separate contract/authority。 |
| Native Windows gate | Surface priority/focus while task updates；collapse does not cancel；Result does not steal focus；critical confirmation remains blocked unless authoritative signal exists。 |
| Manual acceptance | Simulate documented facts and see calm，ordered projections；unknown facts show neutral ongoing state or nothing，never fictional progress。 |
| Rollback boundary | Disable mapper/surfaces and retain Conversation vertical path；backend is untouched。 |
| Exit criteria | Mapper/priority/stale-event tests green；each visible control has an authoritative capability signal；missing contracts listed explicitly。 |
| Evidence to record | Backend signal inventory、mapping table、unsupported capability list、event traces、tests/manual results。 |

## 18. Slice 9 — Expanded Conversation

| Field | Plan |
|---|---|
| Goal | Promote the same conversation context from Capsule to Expanded Conversation only when measured content/task pressure exceeds Compact capacity。 |
| Why this slice exists | Progressive Disclosure requires more room for sustained interaction，not a second chat product。 |
| Preconditions | Slice 8 projections proven；observational evidence shows Compact limits；promotion policy approved against 06。 |
| Dependencies | Slice 8。 |
| Product contracts covered | 06 Compact A/B → Expanded P、single context、manual collapse、not “long answer therefore Workspace”。 |
| Engineering contracts covered | 07 state identity/effect architecture and anchoring/focus contracts。 |

Repository evidence：

| File | Class / method | Current role | Why touched / protected |
|---|---|---|---|
| Conversation Model/Coordinator | context and presentation level | canonical state | add promotion effect，not new session |
| Conversation host | Compact renderer | one Surface instance/lifecycle | adapt shell or controlled replacement |
| anchoring policy | work-area placement | Compact constraints | extend without exact geometry freeze |

| Field | Plan |
|---|---|
| Expected files to change | Conversation state/promotion policy；host layout mode；promotion/collapse tests。 |
| Files forbidden to change | Backend lifecycle、pet gestures、Palette semantics、Workspace implementation。 |
| Test-first requirements | Explicit capacity condition or user request promotes once；draft/context/selection preserved；manual collapse deterministic；focus not stolen by automatic content update。 |
| Tests expected to add | Promotion policy/model tests；Qt identity/focus/context continuity tests。 |
| Existing regression tests | Milestone 1/2 gates，A–L，native focus/draft。 |
| Implementation boundary | Expanded Conversation only，using one context。 |
| Explicit non-goals | Workspace、history Sidebar、tool logs、automatic promotion on length alone without approved capacity rule。 |
| Stop conditions | Promotion creates duplicate session/window；loses draft/context；acts like permanent chat app；trigger remains unmeasured/ambiguous。 |
| Native Windows gate | Promotion/collapse placement，focus，Z-order，taskbar and Schwarz visual relation across work-area edges。 |
| Manual acceptance | Continue a qualifying task，promote once，continue seamlessly，collapse back without losing context。 |
| Rollback boundary | Disable promotion effect；Compact remains canonical and functional。 |
| Exit criteria | Approved trigger and continuity tests green；no Workspace or permanent chrome introduced。 |
| Evidence to record | Trigger rationale、context identity、focus trace、screenshots、tests。 |

## 19. Slice 10 — Keyboard Fast Entry

| Field | Plan |
|---|---|
| Goal | Add the fast Conversation entry only after key combination and scope are explicitly approved。 |
| Why this slice exists | The invocation seam should be reusable，but registering an arbitrary global shortcut would violate the frozen TBD。 |
| Preconditions | `Shortcut: TBD` resolved with key、enablement/default、scope、conflict/accessibility policy；Slice 7 seam stable。 |
| Dependencies | Slice 7 plus product decision。Blocked while TBD。 |
| Product contracts covered | 06 Fast Conversation Entry；same create/restore/focus semantics as Ask。 |
| Engineering contracts covered | 07 reusable invocation seam and lifecycle/capability handling。 |

Repository evidence：

| File | Class / method | Current role | Why touched / protected |
|---|---|---|---|
| Slice 7 Coordinator invocation | `open_or_restore` semantic | canonical entry | reuse exactly |
| `pet_application.py` | app startup/shutdown | registration lifecycle candidate | narrow composition only after approval |
| platform integration candidate | no confirmed shortcut service | TBD | path/technology must be repository-verified |

| Field | Plan |
|---|---|
| Expected files to change | Approved platform shortcut adapter、composition/settings exposure if separately specified、unit/native tests。 |
| Files forbidden to change | Pet gestures、Palette Ask semantics、backend、hard-coded unapproved key。 |
| Test-first requirements | successful registration invokes canonical seam once；conflict/denial/unregister are safe；repeat does not duplicate；disabled setting registers nothing。 |
| Tests expected to add | Adapter lifecycle/conflict tests；native registration/invocation/unregister test。 |
| Existing regression tests | Slice 7 entry/focus/duplicate tests and full native gate。 |
| Implementation boundary | One approved shortcut adapter and existing intent。 |
| Explicit non-goals | Choosing the key、OS-wide remapping UI、multiple shortcuts or accessibility design beyond approved contract。 |
| Stop conditions | Product decision absent；conflict silently steals another shortcut；shutdown leaves registration；alternate entry semantics emerge。 |
| Native Windows gate | Mandatory registration、collision、focus、repeat and shutdown/unregister on supported Windows environments。 |
| Manual acceptance | Approved shortcut creates/restores one Capsule with focus；conflict reports non-destructively；pet interactions unchanged。 |
| Rollback boundary | Disable/unregister adapter；Palette Ask remains primary discoverable entry。 |
| Exit criteria | Only available after TBD resolution；native lifecycle and shared-seam tests green。 |
| Evidence to record | Approval reference、key/scope policy、registration result、conflict trace、tests。 |

## 20. Slice 11 — Workspace

| Field | Plan |
|---|---|
| Goal | Define and later validate the smallest Workspace promotion boundary for proven complex，persistent tasks。 |
| Why this slice exists | Workspace is legitimate only when Conversation cannot safely carry artifacts/progress；premature construction would create an IDE/dashboard。 |
| Preconditions | Slices 8 and 9 are production-proven；real task evidence demonstrates multi-file/persistent artifact/long-running needs；separate screen/state specification approved。 |
| Dependencies | Slices 8 + 9 and future product approval。Deferred。 |
| Product contracts covered | 06 Agent Workspace only for complex sustained work；Character connection and manual collapse remain。 |
| Engineering contracts covered | 07 boundary rules only；implementation architecture requires later dedicated TDD amendment if scope expands。 |

Repository evidence：

| File | Class / method | Current role | Why touched / protected |
|---|---|---|---|
| Conversation Model/Coordinator | active context | promotion source | preserve identity |
| Action/Result projection | verified task facts/artifacts | evidence source | no raw tool logs |
| legacy `main_window.py` | Control Center | not Workspace | must not be rebranded/reused by assumption |

| Field | Plan |
|---|---|
| Expected files to change | None during current Phase 8 execution planning；future paths require a new approved Slice packet。 |
| Files forbidden to change | All production/test files until entry criteria and specification are approved；backend architecture always out of scope。 |
| Test-first requirements | Future tests must prove one context，qualified promotion，artifact continuity，manual collapse and no permanent chrome before code。 |
| Tests expected to add | Deferred：promotion contract、artifact continuity、window lifecycle/focus/native acceptance。 |
| Existing regression tests | All prior Slice gates and full suite。 |
| Implementation boundary | Planning boundary only；no file structure or class hierarchy frozen。 |
| Explicit non-goals | Admin Dashboard、IDE Sidebar、raw logs、backend orchestration、automatic opening for merely long answers。 |
| Stop conditions | No production evidence；screen spec absent；backend redesign required；Workspace becomes default/permanent。 |
| Native Windows gate | Deferred but mandatory before any Workspace release：multi-window focus/Z-order/taskbar/collapse/restore。 |
| Manual acceptance | Deferred task-based study with complex real scenarios。 |
| Rollback boundary | Promotion feature flag/edge returns to Expanded Conversation without task cancellation or context loss。 |
| Exit criteria | This plan leaves Slice 11 `DEFERRED`；future implementation needs approved inputs and a refreshed plan。 |
| Evidence to record | Future task corpus、capacity failure evidence、approved screen/state delta、tests and native results。 |

## 21. Native Windows Validation Plan

### 21.1 Environment gate

Before Slice 3 and Slice 6 production exits，record：

- `QApplication.platformName() == "windows"`；
- `ARKCLAW_PET_ROLE_MANIFEST` resolves to an existing production Schwarz manifest；
- `ARKCLAW_SPINE38_BRIDGE_DLL` resolves to a compatible existing bridge；
- manifest/hash/ABI preflight passes without changing assets or expected hashes；
- `create_optional_production_pet_composition()` returns a production composition；
- both parametrized native Schwarz input tests execute and pass，not skip。

A skipped native test is **not** a pass。Missing environment prerequisites block the relevant native exit gate but do not authorize fake assets、hash changes or offscreen substitution。

### 21.2 Tool vs Popup decision matrix for Slice 6A

| Decision criterion | Tool candidate must prove | Popup candidate must prove | Reject when |
|---|---|---|---|
| Explicit Schwarz click (K) | target is classified before dismiss；one Interact survives | platform dismissal still allows one classified Interact | click swallowed、replayed twice or opens Conversation |
| Ordinary outside (L) | custom dismissal consumes without desktop/app pass-through | native dismissal consumes without action | underlying target receives unintended action |
| Focus / keyboard | navigable without corrupting pet no-focus contract | keyboard works under popup activation rules | focus cannot be restored predictably |
| Conversation handoff | dismiss completes before Capsule focus | same ordering is observable | focus races or both Surfaces remain |
| Z-order / topmost | remains associated with Schwarz across active apps | popup remains visible appropriately | Palette hides behind or pins incorrectly |
| Taskbar / Alt-Tab | no unintended entry | no unintended entry | extra app identity appears |
| BODY / OVERFLOW | both routes have identical product semantics | both routes have identical product semantics | proxy route differs |
| Edge placement | work-area safe and Schwarz unobscured | same | offscreen or covers protected hit target |
| Rollback | one edge restores QMenu | one edge restores QMenu | cutover is entangled with commands/Ask |

The chosen flag set is an implementation result，not predetermined by this plan。Only real Windows evidence may select Tool or Popup。

## 22. Test Strategy per Slice

### 22.1 Red → Green → Refactor protocol

1. Define one observable behaviour at a public seam and add the smallest failing test when the behaviour is new。
2. Run that test and record the expected failure。Characterization that is already true may begin green；do not manufacture a failure。
3. Implement only enough for Green，then run the Slice regression set。
4. Refactor only within the approved Slice boundary while tests stay green。
5. Run broad and required native gates；classify every failure/skip before merge。

Tests assert snapshots、intents、effects、commands and visible/native behaviour，not private fields or incidental widget structure。Mocks/fakes are limited to external runtime、clock/platform or window-system boundaries；Model/Coordinator collaborators remain real where practical。

### 22.2 Slice test ladder

| Slice | First test layer | Integration layer | Native/manual gate |
|---|---|---|---|
| 0 | existing targeted tests | broad suite/smoke observability | classify native skips |
| 1 | Qt-free Model/Coordinator contracts | inert composition smoke | zero visible change |
| 2 | host lifecycle/anchor policy | Qt focus/IME harness | basic Windows Tool behaviour |
| 3 | A/B/C/J characterization | production composition regression | mandatory real Schwarz Click/Drag |
| 4 | draft revision/snapshot | bridge acceptance and Qt editor | IME/focus/restore |
| 5A | descriptor/dispatch | command parity | none |
| 5B | Palette navigation | inactive Qt host | harness keyboard/focus |
| 6A | target-routing contract | Tool/Popup comparison | mandatory native matrix |
| 6B | D/H/K/L | production cutover composition | mandatory native XOR cutover |
| 7 | E/F/I ordered effects | production Palette→Capsule | native focus/duplicate/draft |
| 8 | mapper/stale-fact/capability | runtime fact projection | priority/no focus steal |
| 9 | promotion/context continuity | adaptive Conversation host | native promotion/collapse |
| 10 | adapter lifecycle/conflict | shared invocation seam | mandatory shortcut lifecycle |
| 11 | deferred | deferred | deferred |

### Risk → Test Traceability Review

The reconciled 07 Risk Register was reviewed row by row。Its Test references now name the contracts that actually detect each failure；no architecture or product decision changed。

| Risk | Detecting contract(s) | Slice closure |
|---|---|---|
| Left Click stolen/toggled by Conversation | A、B、K | 3；re-run 6/7 |
| Double-click delay or new semantic | J、A | 3 |
| Interact emitted before Drag classification | C、A | 3 |
| BODY/OVERFLOW drag regression | C + existing pointer/effect/native suites | 3 and 6 |
| Right Click executes action or Conversation | D | 6B |
| Ordinary outside leaks an action | L | 6A/6B |
| Explicit Palette-open Schwarz click swallowed/replayed | K | 6A/6B |
| Ask does not dismiss/create/restore/focus in order | E + native focus | 7 |
| Duplicate Surface / stale open effect | F、E | 7 |
| Draft loss / wrong revision cleared | B、F + draft suite | 4 |
| Focus steal or focus not restored | B、E、F + native | 2/4/7 |
| Palette collides with confirmation | I | 7；expand 8 when supported |
| Stale Agent fact overwrites current presentation | dedicated mapper stale-fact suite | 8；A–L alone are insufficient |
| Command/capability lost during menu migration | H、G | 5A/6B |
| Control Center capability loss | H | 6B |
| Tray capability regression | H + existing tray suite | 5A/6B |
| Native Z-order/target/focus divergence | D、E、K、L + native matrix | 6A/6B/7 |
| Existing red baseline mistaken for new regression | A–L + broad baseline disposition | 0 and every Slice |

Review result：all current 07 risk rows now have a named detection route。The stale-Agent-fact risk intentionally uses a Slice 8 mapper suite because no current A–L interaction contract can prove task correlation。

## 23. Test Traceability Matrix

| ID | Contract under test | First owning Slice | Mandatory reruns |
|---|---|---|---|
| A | Completed non-drag Left Click produces exactly one existing Interact and zero Conversation in every UI/Agent presentation context。 | 3 | 6B、7、release |
| B | Capsule visibility/focus/draft state never changes the semantic of Schwarz Left Click，and collapse/restore preserves owned draft。 | 3/4 | 7、release |
| C | Valid Drag produces existing Drag behaviour with zero Interact and zero Conversation through BODY and OVERFLOW。 | 3 | 6B、release |
| D | Right Click opens exactly one Palette and performs zero Interact、Conversation or Character action。 | 6B | 7、release |
| E | Ask selection dismisses Palette before one create/restore and then focuses the semantic input exactly once。 | 7 | 9/10、release |
| F | Repeated、duplicate or stale Conversation invocation restores one Surface and never creates duplicates or clears newer draft。 | 4/7 | 9/10、release |
| G | Unsupported/unavailable commands are disabled or absent with an honest reason and never execute。 | 5A | 6B、8、release |
| H | Action Palette cutover preserves the approved Agent、Character、System/Control Center/tray command capabilities and exactly-once execution。 | 5A/6B | release |
| I | Confirmation/higher-priority blocking Surface excludes Palette conflicts；dismiss/selection cannot bypass confirmation。 | 7/8 | release |
| J | Double Click has no independent product semantic and introduces no delay/coalescing that changes two completed clicks。 | 3 | 6B、release |
| K | With Palette open，explicit Schwarz BODY/OVERFLOW click dismisses Palette，then produces exactly one Interact，zero Conversation and no replay。 | 6A/6B | 7、release |
| L | With Palette open，ordinary non-Schwarz outside click dismisses without pass-through and produces zero Agent/Character/System action。 | 6A/6B | 7、release |
| M | Verified backend facts map conservatively；unknown or stale facts cannot fabricate or overwrite current presentation state。 | 8 | 9、release |
| N | Exact submitted draft snapshot is cleared only after proven acceptance；failure or older completion preserves recoverable/newer draft。 | 4 | 7、release |
| O | Required native tests execute on production Schwarz Windows composition；skip is never accepted as pass。 | 3/6 | every native release gate |

## 24. Manual Acceptance Strategy

Manual acceptance complements，never replaces，automated evidence。Each executed Slice records date、tester、Windows/Qt/platform、manifest/bridge identity、steps、expected/actual result and artifact links。

| Scenario | Required observations |
|---|---|
| Quiet baseline | Default desktop remains Schwarz-only；no new permanent Surface/taskbar item。 |
| Click/Drag | BODY and OVERFLOW Left Click Interact once；Drag never Interacts or opens UI。 |
| Palette dismiss | Ordinary outside silently dismisses；explicit Schwarz click dismisses then Interacts once。 |
| Ask entry | Palette disappears before one Capsule focuses；Right Click alone does not open it。 |
| Draft | IME/caret/selection/newer edit survive collapse、failure and older completion。 |
| Native placement | center/all work-area edges、display scaling/current monitor；no protected hit overlap。 |
| Capability parity | Agent/Character/System、Control Center and tray-approved actions remain reachable once。 |
| Agent projection | only observed backend facts appear；technical noise hidden；collapse does not cancel。 |
| Return to calm | Escape/manual collapse returns predictably to Character-only without losing active work。 |

## 25. Stop-the-line Conditions

Any item below stops the current Slice and prevents dependent work until the cause is fixed or the Slice is rolled back：

- Left Click is not exactly one existing Interact；
- Drag emits Interact、Conversation or changes established landing/OVERFLOW behaviour；
- ordinary outside Palette click triggers an underlying action；
- explicit Palette-open Schwarz click is swallowed、duplicated or reinterpreted；
- Right Click opens both native menu and Palette，or performs an action；
- draft、IME、caret/selection or a newer revision is lost；
- duplicate Conversation/Palette windows or stale create/focus effects occur；
- focus is silently stolen，or Capsule cannot receive/restore semantic input focus；
- an approved Agent/Character/System、Control Center or tray capability is lost；
- UI fabricates backend state、progress、confirmation、cancel/retry capability or task correlation；
- a required native test skips or native behaviour contradicts offscreen tests；
- a protected file changes without Slice evidence and review justification；
- a pre-existing failure is “fixed” by weakening/removing its assertion without confirmed contract evidence。

## 26. Rollback Strategy

1. Keep every visible entry behind one narrow composition/input edge。
2. Preserve old QMenu until Slice 6B；6B is a single XOR cutover commit and can restore that edge without reverting descriptors/host tests。
3. Keep Conversation host inactive through Slice 6；Slice 7 can remove only Ask wiring and retain tested infrastructure。
4. Disable projection/promotion adapters independently；never roll back backend state or user files to hide UI defects。
5. Do not perform destructive repository resets。Use explicit revert/review of the Slice commit set after preserving evidence。
6. If draft schema/state would become persistent in a future phase，add migration/backup design first；no such persistence is authorized here。

## 27. Git / Review Strategy

- Start implementation later in a dedicated clean branch/worktree after recording `git status` and baseline evidence；this document does not choose a branch name or perform Git operations。
- Commit one Slice or one explicitly split sub-Slice per reviewable set。Do not mix refactors、formatting、asset changes or backend work。
- Suggested review boundaries：Slice 0；Slice 1；Slice 2 + validation-only Slice 3；Slice 4；Slice 5A；Slice 5B + spike-only 6A if still reviewable；Slice 6B alone；Slice 7 alone；then one PR per later Slice。
- Never combine the production right-click cutover、Ask wiring and Agent projection in one change。
- Every review includes authority links、contract IDs、before/after baseline、changed/protected-file audit、native status、manual evidence、rollback edge and unresolved TBDs。
- Existing unrelated dirty/untracked files are user-owned and excluded from Slice commits。

## 28. MVP Milestones

### Milestone 1 — Preserved Pet + Primary Conversation Entry

Requires Slices 0–7，including 5A/5B and 6A/6B：

- existing Click/Drag semantics proven unchanged；
- presentation Model/Coordinator and independent Capsule host；
- safe draft lifecycle；
- one Palette replacing QMenu through proven native semantics；
- Ask ArkClaw dismisses then creates/restores/focuses one Capsule；
- approved command capabilities preserved；
- native gates pass unskipped。

Basic submit/simple response may enter Milestone 1 only if Slice 4 proves exact submitted-snapshot acceptance。Otherwise input submission remains visibly unavailable and the missing signal is a blocking Frontend Integration Requirement；it must not be approximated。

### Milestone 2 — Honest Agent Feedback

Slice 8 projects verified runtime facts into minimal Action/Result UI with stale-event and capability safeguards。Unsupported confirmation/progress/cancel/retry remains absent。

### Milestone 3 — Evidence-based Expansion

Slice 9 adds Expanded Conversation only after capacity evidence。Slice 10 remains conditional on shortcut approval；Slice 11 remains deferred pending complex-task evidence and a dedicated specification。

## 29. Deferred Items

| Item | Status / unblock condition |
|---|---|
| Global shortcut key、default、scope、conflict policy | `TBD`；blocks Slice 10 only。 |
| Exact Conversation/Palette class and file names | `TBD`；confirm at each Slice against current repository，non-blocking for Slice 0。 |
| Tool versus Popup flags | `TBD` until Slice 6A real Windows matrix。 |
| Exact submitted snapshot acceptance/correlation | Must be proven in Slice 4；blocks production submit if absent。 |
| Acting vs Waiting reason、progress detail、partial result、confirmation、cancellable/retry capability signals | Frontend Integration Requirements；blocks only corresponding Slice 8 presentation/control。 |
| Expanded promotion threshold/policy | `TBD` until observed Compact pressure and approval。 |
| Final geometry、motion、visual tokens/assets | Later visual implementation/specification，outside this plan。 |
| Workspace structure and promotion | `DEFERRED` until Slices 8/9 evidence and dedicated approval。 |

## 30. Stage 9 Entry Criteria

Stage 9 may start Slice 0 only when：

1. 06 remains the sole product freeze and 07 remains engineering authority；
2. this 08 plan is approved without silently resolving its TBDs；
3. a dedicated clean branch/worktree and changed-file ownership are established；
4. exact 20-test baseline，broad 5-failure/1-skip disposition and native skip reasons are recorded afresh；
5. Slice 0 scope is limited to classification/characterization/smoke observability；
6. current product freeze is unchanged and no new blocking contradiction exists among 06、07、08 and repository facts；
7. Slice 0 expected files are explicitly confirmed from §7/§9 before editing；
8. Slice 0 rollback boundary is explicitly accepted：revert only assertion/observability changes and retain the recorded baseline；
9. production code、tests and UI implementation have not already been changed under Phase 8；
10. every later Slice must independently satisfy its prerequisites and may not be batch-authorized by starting Stage 9。

## 31. Final Readiness Decision

**Decision: `READY_TO_START_SLICE_0_WITH_NON_BLOCKING_TBD`**

Rationale：the authoritative interaction and engineering contracts are sufficient to begin the read-only/test-harness baseline Slice。The open shortcut、native window-kind、file-name and backend-signal questions are explicitly isolated behind later Slice gates。They do not block Slice 0 and must not be guessed。

Scope status at Phase 8 completion：

```text
Production code modified: NO
Tests modified: NO
UI implementation started: NO
Implementation Slice executed: NO
Implementation Plan created: YES
```
