# ArkClaw DeepSeek TDD Execution Handoff

> 阶段：Stage 9 — Execution / Handoff Protocol  
> 文档类型：GPT → DeepSeek TDD Execution Contract  
> 当前授权：`Stage 9 / Slice 0 — Characterization / Baseline only`  
> 当前状态：`READY_TO_START_SLICE_0_WITH_NON_BLOCKING_TBD`  
> 本文不执行任何 Slice，不覆盖 06–08，不修改 production code 或 tests

## 1. Purpose

本文规定 DeepSeek 接手 ArkClaw Frontend Stage 9 后，如何一次执行一个已授权 Slice、如何应用 TDD、何时必须停止，以及必须向 GPT / User 交付哪些可复核证据。

01–08 决定产品、架构与 Slice 内容；09 只提供执行协议、导航、报告格式和 review handoff。它不是新的产品设计、架构 TDD 或 Implementation Plan，也不是执行授权本身。

最重要的规则：

```text
One authorized Slice per execution session.

Authorized Slice N
→ execute only Slice N
→ validate
→ deliver evidence
→ READY_FOR_REVIEW
→ STOP
```

即使 Slice N 完全通过，也不得自动开始 Slice N+1。下一 Slice 必须由 User 重新明确授权。

### DeepSeek startup checklist

```text
[ ] Read 06 completely
[ ] Read relevant 07 sections
[ ] Read the full relevant 08 Slice specification
[ ] Read this 09 protocol
[ ] Confirm the explicitly authorized Slice
[ ] Confirm branch/worktree and user-owned dirty files
[ ] Run and record the required baseline
[ ] Confirm expected, protected and forbidden files
[ ] Identify one first observable behaviour at an approved public seam
[ ] Confirm that the next Slice will not be executed
```

## 2. Authority

```text
06 — Product / Interaction Freeze
        ↓
07 — Engineering Architecture Contract
        ↓
08 — Implementation Slice Plan
        ↓
09 — Execution / Handoff Protocol
```

- `06` 决定用户可见行为。
- `07` 决定工程边界、ownership、public seams 与 integration contracts。
- `08` 决定 Slice 顺序、范围、门禁、测试、native/manual acceptance 与 rollback。
- `09` 只决定 DeepSeek 如何执行一个已授权 Slice并交付证据。

DeepSeek 必须阅读原文，不得仅凭 09 的摘要执行。09 是 navigation，不是 06–08 的替代副本。

若 06–09、用户最新明确决定或当前仓库事实之间出现会改变当前 Slice 的冲突：

```text
STOP
→ classify the conflict
→ report exact sources and evidence
→ do not invent a resolution
```

09 不得覆盖、修订或“优化”06–08。

## 3. Roles

### 3.1 Product / Architecture Authority

由 06–08 提供。DeepSeek 不重新设计 UX、interaction、Surface hierarchy、frontend architecture、Agent backend 或 Slice dependency。

### 3.2 DeepSeek — Execution Agent

DeepSeek 负责：

- 只执行当前被明确授权的一个 Slice；
- 先读权威文档、测试与生产代码；
- 通过公共 seam 写失败测试或 characterization；
- 只做当前 behaviour 所需的最小 Green；
- 运行规定的 focused、regression、native/manual gates；
- 收集 exact evidence、residual risks 和 rollback boundary；
- 输出固定 Executor Handoff Report，然后停止。

DeepSeek 不负责：决定下一 Slice、重写 06–08、扩大 scope、替用户决定 TBD、重设计 backend 或把多个 Slice 合并实施。

### 3.3 GPT / Reviewer

GPT 负责审查 repo diff 与 evidence package，核验 TDD、产品/架构 compliance、exit criteria、native/manual gate 和 rollback，并给出 review result。GPT 可以设计 correction prompt，但不能替 User 自动授权下一 Slice。

### 3.4 User / Product Owner

User 最终批准进入下一 Slice，决定产品级 TBD，批准 scope expansion 与 protected core 修改，并决定是否接受 reviewer 建议。

## 4. Execution Philosophy

1. **One authorized Slice**：一次 session 只能执行一个明确编号的 Slice 或 sub-Slice。
2. **No auto-advance**：`SLICE_COMPLETE` 只允许输出 `READY_FOR_REVIEW`，不允许继续。
3. **One behaviour at a time**：每个 TDD loop 只选择一个 observable behaviour 和一个 pre-agreed public seam。
4. **New behaviour**：`Red → minimum Green → review-scoped refactor only when necessary`。
5. **Existing correct behaviour**：`Characterize → Freeze → Regression`；不得故意破坏以制造 Red。
6. **Tests describe behaviour**：测试 public intents、snapshots、effects、commands、visible/native results，不测试 private methods、incidental widget tree 或内部 call choreography。
7. **Mocks at boundaries only**：仅 mock/fake backend bridge、native OS、time/environment 等边界；不 mock 自有 Model/Coordinator/Host 内部来证明实现细节。
8. **No speculative preparation**：不得提前实现未来 Slice、generic event bus、framework 或未批准 capability。
9. **Evidence over confidence**：没有 exact command/result、diff、native/manual evidence，就不能报告完成。

## 5. Global Frozen Contracts

DeepSeek 不得重新讨论或重新解释：

```text
Completed non-drag Left Click Schwarz
→ exactly one existing Interact
→ zero Conversation

Valid Drag
→ existing Drag / release / landing
→ zero Interact
→ zero Conversation

Right Click Schwarz
→ Anchored Action Palette only

Action Palette → Ask ArkClaw
→ Palette dismiss
→ create/restore one Conversation Surface
→ focus semantic input when permitted

Double Click
→ Reserved / no independent semantic
```

同时冻结：

- draft survives collapse、outside click、Escape、Palette roundtrip、Drag、focus loss、task Cancel/Error；
- Dismiss / Collapse / Close 不等于 Cancel Agent task；
- one logical Conversation context；one primary Presentation；at most one foreground Overlay；
- UI 不用 timer、visibility、tool name 或 animation 猜 Agent state；
- Thinking、Acting、Waiting、Success、Error、Cancelled 只投影 verified backend facts；
- native QMenu 与 Palette 在 production cutover 后必须 XOR；
- Control Center 保持 secondary/legacy/recovery，不冒充 Capsule 或 Settings。

若某项“不方便实现”，输出 `ENGINEERING_CONFLICT`；不得换方案。

### 5.1 Palette routing contract

从 Slice 6A 起，必须分别验证两个不同 contract，禁止合并成 generic outside click：

```text
K — Explicit Schwarz Click while Palette open
→ Palette dismiss
→ exactly one Interact
→ zero Conversation
→ no replay / no second click

L — Ordinary outside target != Schwarz
→ Palette dismiss
→ event consumed
→ zero Character action
→ zero Conversation action
```

## 6. Protected Core

以下为全局 protected core：

- Spine resources、production manifests、asset hashes、bridge ABI expectations；
- renderer、Spine player、composition/mix；
- BODY/OVERFLOW geometry、alpha hit、native hit test、active proxy；
- `PetPointerGesture` threshold semantics 与 Click/Drag transaction；
- existing release、falling、landing；
- animation timing、mix 和 production action names；
- `ProductionAction` identities 与 existing Interact semantic；
- taskbar grounding、topmost behaviour、tray Show/Quit recovery；
- backend planner、reasoning、memory、tool routing、scheduler、orchestration、MCP 与 task lifecycle。

“这样更容易实现”不是修改理由。若当前 Slice 确实需要 protected core 变更：

```text
STOP — SCOPE_EXPANSION_REQUIRED
```

报告所需文件/符号、原因、替代方案、产品/工程影响和新增验证；等待 User 明确批准。

## 7. Slice Dependency Graph

```text
0 → 1 → 2 → 3 → 4 → 5A → 5B → 6A → 6B → 7
                                             ├→ 8 → 9
                                             └→ 10  [BLOCKED: Shortcut TBD]

8 + 9 production-proven
→ 11 [DEFERRED: new readiness review required]
```

当前执行卡：

| Slice | Name | Dependency status |
|---|---|---|
| 0 | Characterization / Baseline | Eligible now after explicit authorization |
| 1 | Frontend Presentation State Seam | Not authorized；depends on accepted Slice 0 |
| 2 | Conversation Capsule Skeleton | Not authorized；depends on Slice 1 |
| 3 | Left-click / Drag Preservation Gate | `HARD_GATE`；depends on Slice 2 |
| 4 | Draft Safety | depends on Slice 3 |
| 5A | Command Descriptor Adapter | depends on Slice 4 |
| 5B | Inactive Action Palette Host | depends on Slice 5A |
| 6A | Windows Tool / Popup Native Spike | `NATIVE_GATE`；depends on Slice 5B |
| 6B | Atomic Right-click Palette Cutover | `HIGH_RISK_CUTOVER`；depends on 6A |
| 7 | Ask ArkClaw Conversation Entry | depends on 6B + Slice 4 |
| 8 | Activity → Result | depends on Slice 7 and backend fact inventory |
| 9 | Expanded Conversation | depends on Slice 8 + observed capacity evidence |
| 10 | Keyboard Fast Entry | `BLOCKED — Shortcut TBD`；depends on Slice 7 + product approval |
| 11 | Workspace | `DEFERRED`；depends on production-proven 8/9 + new review |

## 8. Current Authorization

```text
CURRENT AUTHORIZED EXECUTION:
Stage 9 / Slice 0 — Characterization / Baseline

READINESS:
READY_TO_START_SLICE_0_WITH_NON_BLOCKING_TBD

Slice 1 is NOT authorized yet.
Slices 2–11 are NOT authorized yet.
```

这不等于 `READY_TO_EXECUTE_ALL_SLICES`。如果 DeepSeek 收到笼统的 “implement the frontend plan”，仍必须要求明确 Slice；不得将其解释为批量授权。

## 9. Universal TDD Execution Protocol

### Step 1 — Read Authority

完整读取 06 中相关 frozen contract、07 的对应 engineering sections、08 的完整当前 Slice specification 与本 09。不得仅依赖 Execution Card。

### Step 2 — Inspect Current Repository

记录 branch/worktree、initial `git status`、user-owned dirty files、relevant files/tests/classes/methods 和相对 08 的 drift。若 drift 改变 Slice 设计：`STOP — REPOSITORY_DRIFT`。

### Step 3 — Record Baseline

运行 08 指定的 focused、regression、native/environment checks，逐条记录 exact command、exit/result、pass/fail/skip count 和 failure names。禁止只写 “tests passed”。

### Step 4 — Define First Behaviour

从当前 Slice 选择一个最小 observable behaviour；声明 authority、public seam、independent expected result 和为什么它属于当前 Slice。未在 07/08 预先确认的 seam 必须先停止请求确认。

### Step 5 — Red / Characterization

- 新行为：先写最小失败测试并运行，证明 expected Red。
- 已有正确行为：characterize 当前行为；existing/new test 可以一开始就是 Green。
- 禁止制造失败、删除有效断言或用 tautological expectation 假装规格。

### Step 6 — Minimal Green

只改使当前测试通过所必需的最少生产代码。禁止 unrelated refactor、future Slice preparation、speculative abstraction 和 formatting sweep。

### Step 7 — Regression

运行 focused test、Slice regression、global protected contracts 和 required native tests。每个非绿结果进入 §11 failure classification。

### Step 8 — Refactor Only If Necessary

仅在 duplication、clarity 或 stable public seam 确有必要时进行 review-scoped refactor；不得扩大行为或跨 Slice。

### Step 9 — Acceptance Gate

逐项检查 automated、native、manual、protected files、scope delta、stop-the-line 和 rollback。Required native/manual 未通过时不得 Complete。

### Step 10 — Evidence Package

使用 §27 的固定 Executor Handoff Report，包含 repo state、commands/results、diff、tests、native/manual、risks、rollback 和 final status。

### Step 11 — STOP

输出 `READY_FOR_REVIEW` 并停止。无论结果是 Complete、Blocked 或 Conflict，都不得进入下一 Slice。

## 10. Scope / Zero-Guessing Rules

DeepSeek 禁止猜路径、class、test name、Qt flag、backend signal、command ownership、manifest、DLL、shortcut 或 Windows behaviour。

```text
inspect repository
→ still unknown?
   ├─ affects current Slice → UNKNOWN + STOP
   └─ does not affect current Slice → NON_BLOCKING_TBD + continue within scope
```

每个 Slice 开始前必须声明：

```text
Allowed Files:
Expected Files:
Protected Files:
Forbidden Work:
Public Seam Under Test:
```

08 中 candidate path 仍是 `Candidate path — confirm before implementation`，不是授权创建指定文件。若需要修改 Expected list 外文件：

```text
Scope delta:
Reason:
Repository evidence:
Why still inside this Slice:
Added tests/gates:
```

若涉及 protected core、改变 public architecture 或扩大产品行为，必须停止：`SCOPE_EXPANSION_REQUIRED`。

## 11. Failure Classification

每个失败必须使用以下分类之一并提供证据：

| Classification | Meaning | Required action |
|---|---|---|
| `NEW_REGRESSION` | 当前 Slice 导致此前通过的 contract 失败 | stop；fix within scope or rollback |
| `PRE_EXISTING_FAILURE` | 在本 Slice 修改前可复现 | record exact baseline；do not hide |
| `STALE_ASSERTION` | test expectation 与当前权威产品/实现事实不符 | update expectation only with independent authority evidence |
| `ENVIRONMENT_FAILURE` | prerequisite/tool/runtime unavailable | record environment；apply native gate rules |
| `TEST_OBSERVABILITY_DEFECT` | failure exists but diagnostics cannot attribute cause | improve observability before production fix |
| `PRODUCT_CONFLICT` | current request/behaviour contradicts 06 | stop and escalate |
| `ENGINEERING_CONFLICT` | required implementation would violate 07/08 architecture | stop and escalate |
| `BACKEND_INTEGRATION_MISSING` | required user-facing fact/correlation is absent | block affected subfeature/Slice；do not invent state |
| `NATIVE_VALIDATION_BLOCKED` | required native gate cannot execute | Slice cannot Complete when native pass is mandatory |
| `PREREQUISITE_BUG_FOUND` | real production defect predates or blocks current Slice | stop current Slice；report separate bug |

禁止使用无证据的 “probably unrelated”。

## 12. Escalation Rules

| Condition | Required status | Required response |
|---|---|---|
| 06 与最新明确产品决定冲突 | `PRODUCT_CONFLICT` | stop；quote exact contracts；User decides |
| 继续必须违反 07/08 | `ARCHITECTURE_CONFLICT` | stop；report required violation/alternatives |
| protected core modification required | `SCOPE_EXPANSION_REQUIRED` | stop；request explicit User approval |
| required backend fact absent | `BACKEND_INTEGRATION_MISSING` | stop or disable only affected capability；no fabricated lifecycle |
| mandatory native gate cannot run/pass | `NATIVE_VALIDATION_BLOCKED` | Slice remains blocked；offscreen/skip is not pass |
| new real production defect discovered | `PREREQUISITE_BUG_FOUND` | stop；separate bug；do not bury in UI Slice |
| repository drift changes Slice architecture/scope | `REPOSITORY_DRIFT` | stop；provide diff/evidence and request plan reconciliation |

这些 escalation labels 说明阻断原因；Executor 的 `Final Slice Status` 仍使用 §27 允许的 vocabulary，并在 Residual Risks / Next Action 中记录具体 label。

## 13. Slice 0 Execution Card — Characterization / Baseline

| Field | Execution contract |
|---|---|
| Slice | `0 — Characterization / Baseline` |
| Status | **CURRENTLY AUTHORIZED**；only after confirming 08 §30 entry criteria |
| Goal | Establish a trusted green regression gate、classified five-failure inventory、native skip inventory and attributable smoke diagnostics；add no UI。 |
| Authority | 06 §§2、4、9；07 §§10、27、32；08 §§4–5、9。Read all cited text，not this card alone。 |
| Dependencies | None；does not authorize Slice 1。 |
| Expected scope | Reproduce first；then only specifically stale assertions and/or `scripts/qt_pet_smoke.py`、`scripts/qt_tray_smoke.py` observability after evidence。`src/` is forbidden。 |
| Protected contracts | Existing labels/semantics、targeted Click/Drag/OVERFLOW/context gate、all protected core、zero product behaviour change。 |
| First TDD behaviour | Re-run one known failing assertion exactly；prove whether current source + 06 make it `STALE_ASSERTION` before editing its expectation。Do not batch-fix all five。 |
| Required tests | Re-run exact 07 §10.2 targeted command、07 §10.1 broad command、each failing test individually and native command；record exact outputs。 |
| Native gate | Attempt/inspect prerequisites only as authorized by Slice 0；`KNOWN_ENVIRONMENT_SKIP` is allowed with exact reason。Do not perform asset/hash changes or call skip a pass。 |
| Stop conditions | Baseline materially differs；product/current-source evidence does not support a label；smoke proves a real production defect；diagnostic change would require production semantics。 |
| Expected evidence | Initial/final status；commands/results；five row dispositions；native environment/skip evidence；changed-file audit；manual label/Interact/Drag check；rollback。 |
| Exit status | `SLICE_COMPLETE` or `SLICE_COMPLETE_WITH_NON_BLOCKING_TBD` only if every failure is attributable and gates meet 08；otherwise `SLICE_BLOCKED` / `PREREQUISITE_BUG_FOUND`。Always `READY_FOR_REVIEW` then STOP。 |

### 13.1 Known five-failure starting inventory

| Current candidate classification | Item | Slice 0 rule |
|---|---|---|
| `STALE_ASSERTION` | role heading expects `Role Pack: schwarz-production` while current product renders `ACTIVE PET · SCHWARZ / 黑` | reproduce → verify source + 06 role identity → update test expectation only |
| `STALE_ASSERTION` | tray expects `Open Agent Window` instead of current Control Center label | reproduce → verify source + 06 System capability → update test only |
| `STALE_ASSERTION` | pet right-click test expects `Open Agent window` instead of current Control Center label | same；do not rename production to satisfy old test |
| `TEST_OBSERVABILITY_DEFECT` | `qt_pet_smoke.py` reports `drag_struggle_entered,drag_struggle_exited` | make cause observable/attributable before any production fix |
| `TEST_OBSERVABILITY_DEFECT` | `qt_tray_smoke.py` exits 2 with empty `failed_checks` | expose exit/resource/failed-check cause before any production fix |

DeepSeek must re-run and prove these classifications；08 numbers are starting evidence，not current results。If either smoke becomes a real production defect：

```text
STOP Slice 0
Final Slice Status: PREREQUISITE_BUG_FOUND
Next Action: READY_FOR_REVIEW
```

### 13.2 Native skip starting inventory

Record，without guessing or altering protected artifacts：

- `ARKCLAW_PET_ROLE_MANIFEST` resolution/existence；
- `ARKCLAW_SPINE38_BRIDGE_DLL` resolution/existence/compatibility；
- Qt platform (`windows` vs offscreen)；
- manifest/hash/ABI preflight result；
- production composition creation result；
- exact native test command/result。

Slice 0 may exit with a fully explained `KNOWN_ENVIRONMENT_SKIP`。Slice 3 and 6B may not。

## 14. Slice 1 Execution Card — Frontend Presentation State Seam

| Field | Execution contract |
|---|---|
| Slice | `1 — Frontend Presentation State Seam` |
| Status | **NOT AUTHORIZED**；requires accepted Slice 0 + new User authorization |
| Goal | Add Qt-free Presentation Model and application-lifetime Coordinator seam with zero visible behaviour change。 |
| Authority | 06 §§14、17、19；07 §§12–14、20；08 §10。 |
| Dependencies | Slice 0 approved。 |
| Expected scope | Candidate Model/Coordinator paths confirmed from repo；narrow inert composition in `pet_application.py` only if required。 |
| Protected contracts | one P/O、one logical Conversation、dismiss ≠ cancel、backend truth；PetWindow/gesture/tray/MainWindow unchanged。 |
| First TDD behaviour | Through pre-agreed public `dispatch(intent_or_fact) → effects + immutable snapshot` seam，characterize initial Character-only/None state or add the first new state-transition Red；one behaviour only。 |
| Required tests | Qt-free public-model tests；inert composition smoke；Slice 0 gates and pet lifecycle/pointer regressions。 |
| Native gate | No new native Surface；manual/native inventory must prove no additional focus/taskbar/window behaviour。 |
| Stop conditions | visible change；Model reads QWidget visibility；generic event bus/framework appears；PetWindow refactor required。 |
| Expected evidence | Confirmed public seam、first Red/Green trace、snapshot/effect examples、composition diff、window inventory、regression results。 |
| Exit status | Complete only with zero visible behaviour and stable public seam；`READY_FOR_REVIEW` then STOP。 |

## 15. Slice 2 Execution Card — Conversation Capsule Skeleton

| Field | Execution contract |
|---|---|
| Slice | `2 — Conversation Capsule Skeleton` |
| Status | **NOT AUTHORIZED**；requires accepted Slice 1 + new authorization |
| Goal | Build one lazy independent focusable Conversation host in a non-production harness。 |
| Authority | 06 §§10–12；07 §§20、23、25；08 §11。 |
| Dependencies | Slice 1 approved。 |
| Expected scope | Confirmed candidate Conversation host/anchoring policy and Model/Coordinator binding；harness only。 |
| Protected contracts | no production pointer entry；PetWindow/OVERFLOW remain no-focus；MainWindow is not Capsule；opening emits no backend state/task。 |
| First TDD behaviour | Invocation through the approved model seam lazily creates exactly one host in the harness；repeat restores the same host。 |
| Required tests | host lifecycle、focus/IME/Enter/Shift+Enter/Escape、single instance、anchor constraints、no-Agent-state-on-open；Slice 0/1 regressions。 |
| Native gate | Basic Windows independent Tool focus/IME、no taskbar surprise、no PetWindow focus mutation and Z-order；offscreen is insufficient。 |
| Stop conditions | host must be PetWindow child；requires changing pet no-focus flags；overlaps protected hit pixels；native contradicts harness。 |
| Expected evidence | Window flags/platform、host identity、focus trace、edge-placement screenshots、tests、window inventory、rollback。 |
| Exit status | Complete only as inactive/non-production host；`READY_FOR_REVIEW` then STOP。 |

## 16. Slice 3 Execution Card — Left-click / Drag Preservation Gate

| Field | Execution contract |
|---|---|
| Slice | `3 — Left-click / Drag Preservation Gate` |
| Status | **NOT AUTHORIZED / HARD_GATE**；requires accepted Slice 2 + new authorization |
| Goal | Prove Slice 1–2 infrastructure leaves every existing Character pointer semantic unchanged。 |
| Authority | 06 §§4、15、17、19.1；07 §§11、15–16、Tests A/B/C/J；08 §12。 |
| Dependencies | Slice 2 approved；failure blocks every later dependent Slice。 |
| Expected scope | Characterization tests only when coverage is missing；production pointer files are expected unchanged。 |
| Protected contracts | Left Click exactly one Interact in every presentation state；Drag owns threshold-crossed sequence；Double Click no Conversation/delay；BODY/OVERFLOW parity。 |
| First TDD behaviour | Characterize Capsule-existing + completed Left Click → one Interact、zero Conversation、unchanged draft/focus；it may already be Green。 |
| Required tests | A/B/C/J、exact 20 gate、broad gate、pointer/render/effect/native Schwarz suites。 |
| Native gate | Mandatory unskipped production Schwarz tests on `windows`，covering BODY/OVERFLOW Click and Drag。 |
| Stop conditions | any stolen/duplicate/delayed Interact；Drag emits action/UI；OVERFLOW differs；native remains skipped；Double Click opens/focuses UI。 |
| Expected evidence | Native env proof、commands/results、manual state matrix、forbidden-file audit、rollback or pass decision。 |
| Exit status | Only `SLICE_COMPLETE` after mandatory native/manual gates；otherwise `SLICE_BLOCKED` / `NATIVE_VALIDATION_BLOCKED`。Then STOP。 |

## 17. Slice 4 Execution Card — Draft Safety

| Field | Execution contract |
|---|---|
| Slice | `4 — Draft Safety` |
| Status | **NOT AUTHORIZED**；requires accepted HARD_GATE Slice 3 |
| Goal | Protect one draft、revision-tagged submit snapshot、IME/caret/selection and exact acceptance clearing。 |
| Authority | 06 §8；07 §§17、20、26；Tests B/F；08 §13 and contract N。 |
| Dependencies | Slice 3 approved。 |
| Expected scope | Model/Coordinator + Conversation binding；bridge adapter only for an existing provable fact。Legacy MainWindow/backend remain protected。 |
| Protected contracts | ordinary transitions never discard；newer edits survive older completion；UI does not infer acceptance/backend lifecycle。 |
| First TDD behaviour | Collapse and restore preserve exact draft revision and semantic editing position through the public model/host seam。 |
| Required tests | draft model、Qt IME/editor binding、exact acceptance/failure/duplicate completion；Slice 3 and runtime bridge regressions。 |
| Native gate | Real Windows IME composition、focus loss/restore and collapse/restore preservation。 |
| Stop conditions | no exact acceptance correlation；older completion clears newer text；IME/caret lost；backend redesign required。 |
| Expected evidence | command/snapshot timeline、first Red/Green、IME trace、tests、unsupported production-submit decision、rollback。 |
| Exit status | May be `SLICE_COMPLETE_WITH_NON_BLOCKING_TBD` with production submit disabled if acceptance signal is absent；never approximate。STOP for review。 |

## 18. Slice 5A Execution Card — Command Descriptor Adapter

| Field | Execution contract |
|---|---|
| Slice | `5A — Command Descriptor Adapter` |
| Status | **NOT AUTHORIZED**；requires accepted Slice 4 |
| Goal | Project existing commands into a minimal presentation-neutral descriptor without duplicating semantics。 |
| Authority | 06 §9；07 §§8、19、21、24；08 §14.1。 |
| Dependencies | Slice 4 approved or its submit-only blocker explicitly isolated per 08。 |
| Expected scope | Small descriptor/adapter and focused tests；narrow existing command-source composition only。 |
| Protected contracts | Left Click primary Interact and Palette secondary Interact reach the same existing command；tray/Control Center/system capabilities remain。 |
| First TDD behaviour | One existing command descriptor exposes stable id/group/enabled state and dispatches exactly the existing semantic once through the approved adapter seam。 |
| Required tests | descriptor projection、availability/disabled reason、exactly-once dispatch、G/H capability mapping；production menu/tray/PetApplication regressions。 |
| Native gate | Not required for pure adapter。 |
| Stop conditions | command behaviour duplicated；new Interact implementation；capability loss；general command framework emerges。 |
| Expected evidence | Command mapping table、public adapter API、Red/Green trace、capability diff、tests、rollback。 |
| Exit status | Complete only with zero visible UI change；`READY_FOR_REVIEW` then STOP。 |

### 18.1 Slice 5A-P — Resume Autonomous Shared Capability Prerequisite

User-approved narrow exception to the PetWindow Protected Core freeze:
Slice 5A-P authorizes exactly one behavior-preserving extraction of the
Resume Autonomous validity predicate from `PetWindow._resume_pet_autonomous`
into the Qt-free application-level capability
`pet_production_actions.can_resume_autonomous(...)`.  The PetWindow execution
guard, `ProductionActionMenuSection` enabled-state and the command descriptor
adapter projection consume that one predicate; no second implementation of
the Resume validity rule may exist.  PetWindow remains otherwise Protected
Core; no Character input, animation, lifecycle, QMenu cutover or command
behavior change is authorized.

## 19. Slice 5B Execution Card — Inactive Action Palette Host

| Field | Execution contract |
|---|---|
| Slice | `5B — Inactive Action Palette Host` |
| Status | **NOT AUTHORIZED**；requires accepted Slice 5A |
| Goal | Build root/Character/System same-shell Palette navigation in a test/development harness only。 |
| Authority | 06 §9；07 §§14、21、23–25；08 §14.2。 |
| Dependencies | Slice 5A approved。 |
| Expected scope | Inactive host + Model/Coordinator Palette states + harness tests；production `contextMenuEvent` remains QMenu。 |
| Protected contracts | one Palette；opening performs no command；same descriptor source；no Conversation creation；no production right-click change。 |
| First TDD behaviour | Harness opens one root Palette and a repeated open cannot create a duplicate or execute an action。 |
| Required tests | root/layer/back/Escape/select、disabled action、exactly-once dispatch；legacy menu/tray/right-click regressions。 |
| Native gate | Harness keyboard/focus smoke only；Tool-vs-Popup decision is deferred to 6A。 |
| Stop conditions | two command sources；double dispatch；legacy production menu becomes unreachable；native choice is assumed early。 |
| Expected evidence | navigation trace、dispatch count、visible-window inventory、tests、production-edge audit、rollback。 |
| Exit status | Complete only while production right click remains unchanged；`READY_FOR_REVIEW` then STOP。 |

## 20. Slice 6A Execution Card — Windows Tool / Popup Native Spike

| Field | Execution contract |
|---|---|
| Slice | `6A — Windows Tool / Popup Native Spike` |
| Status | **NOT AUTHORIZED / NATIVE_GATE**；requires accepted Slice 5B |
| Goal | Select Palette window semantics only from measured real-Windows behaviour。 |
| Authority | 06 §§4.5、9.4–9.5、12、15；07 §§21、23–25、Tests D/K/L；08 §§15.1、21。 |
| Dependencies | Slice 5B approved；production Schwarz native environment available。 |
| Expected scope | Reversible spike/test harness only；no production `contextMenuEvent` cutover。 |
| Protected contracts | K explicit Schwarz click and L ordinary outside are separate；focus/keyboard/Z-order/taskbar/BODY/OVERFLOW/edge placement/rollback all require evidence。 |
| First TDD behaviour | Create the first target-labelled native test proving one candidate's K route；do not choose Tool/Popup before both K and L plus the full 08 §21 matrix execute。 |
| Required tests | D/K/L native comparison、existing native Schwarz/effect/window-flag/Slice 3 gates。 |
| Native gate | Mandatory unskipped `windows` platform + production Schwarz composition；offscreen and framework-name reasoning are invalid。 |
| Stop conditions | neither candidate satisfies K/L；prerequisites skip；focus/target trace is ambiguous；production edge changes。 |
| Expected evidence | OS/Qt/platform、manifest/bridge/preflight、flags、target event traces、matrix result、screenshots/video、rejected option、rollback。 |
| Exit status | `SLICE_COMPLETE` only with a full measured decision；otherwise `SLICE_BLOCKED` / `NATIVE_VALIDATION_BLOCKED`。Then STOP。 |

## 21. Slice 6B Execution Card — Atomic Right-click Palette Cutover

| Field | Execution contract |
|---|---|
| Slice | `6B — Atomic Right-click Palette Cutover` |
| Status | **NOT AUTHORIZED / HIGH_RISK_CUTOVER**；requires accepted 6A |
| Goal | Replace the production Schwarz right-click QMenu edge with exactly one Palette edge。 |
| Authority | 06 §§4.3、9、14–17；07 §§19、21、24、Tests D/H/K/L；08 §15.2。 |
| Dependencies | 6A decision approved；5A/5B green；native env available。 |
| Expected scope | One narrow `contextMenuEvent`/composition cutover plus prevalidated Palette/Coordinator and tests。 |
| Protected contracts | QMenu XOR Palette；Right Click performs zero command/Conversation；all capability parity；Left Click/Drag unchanged；K/L exact。 |
| First TDD behaviour | Production composition test: one Right Click yields exactly one Palette and zero legacy menu/action before changing the single cutover edge。 |
| Required tests | D/H/K/L、capability parity、production composition、BODY/OVERFLOW native routing、all Slice 0–6A regressions。 |
| Native gate | Mandatory focus、Z-order、topmost、taskbar、edge placement、K/L、BODY/OVERFLOW and XOR evidence。 |
| Stop conditions | menu+Palette coexist；Right Click acts/opens Conversation；K/L fails；capability loss；Left Click/Drag regression。 |
| Expected evidence | Before/after route map、capability inventory、native traces、tests/manual results、changed/protected-file audit、single-edge rollback。 |
| Exit status | Only Complete with all automated/native/manual gates and clear QMenu rollback；`READY_FOR_REVIEW` then STOP。 |

## 22. Slice 7 Execution Card — Ask ArkClaw Conversation Entry

| Field | Execution contract |
|---|---|
| Slice | `7 — Ask ArkClaw Conversation Entry` |
| Status | **NOT AUTHORIZED**；requires accepted 6B and safe Slice 4 seam |
| Goal | Wire Palette Ask to the single reusable dismiss → create/restore → focus Conversation intent。 |
| Authority | 06 §§5、12、19.2；07 §§18、20、26、Tests E/F/I；08 §16。 |
| Dependencies | 6B approved；Slice 2 host and Slice 4 draft contract green；submit disabled if acceptance unproven。 |
| Expected scope | Palette selection、Model/Coordinator invocation and Conversation host composition only。 |
| Protected contracts | Right Click alone zero Conversation；Ask consumed once；Palette dismisses before focus；one context/host；opening creates no backend task/state；Left Click/Drag untouched。 |
| First TDD behaviour | Through the Model public seam，Ask selection emits ordered dismiss then one create/restore effect，without focus or backend effect yet；continue vertically one behaviour at a time。 |
| Required tests | E/F/I、duplicate/stale invocation、no-task-on-open、production Qt focus/native chain；all A–D/H/K/L regressions。 |
| Native gate | BODY/OVERFLOW Palette → Ask、dismiss order、one focusable host、IME/draft restore、Z-order/taskbar。 |
| Stop conditions | focus before dismiss；duplicate host；open starts task；Right Click alone opens Capsule；any Character semantic changes。 |
| Expected evidence | Ordered intent/effect trace、window identity/focus、draft state、backend-zero proof、tests/native/manual、rollback edge。 |
| Exit status | Complete only after Milestone 1 Slice gates pass；then `READY_FOR_REVIEW` and STOP for mandatory Milestone Review。 |

## 23. Slice 8 Execution Card — Activity → Result

| Field | Execution contract |
|---|---|
| Slice | `8 — Activity → Result` |
| Status | **NOT AUTHORIZED**；requires Slice 0–7 Milestone Review approval |
| Goal | Conservatively project verified backend facts into user-facing Activity/Result variants。 |
| Authority | 06 §§13、17–19.5；07 §§22、26；08 §17 and contract M。 |
| Dependencies | Slice 7 + Milestone 1 approval + backend fact inventory。 |
| Expected scope | Pure presentation mapper、Model/Coordinator projection and minimal views；bridge adapter exposes only existing facts。 |
| Protected contracts | no backend redesign/inference；stale facts cannot win；unsupported progress/confirmation/cancel/retry absent；technical details hidden。 |
| First TDD behaviour | One documented current-task backend fact maps through the public mapper seam to one independent known presentation result；then add stale/unknown case separately。 |
| Required tests | mapper table M、stale/out-of-order/terminal precedence、priority/capability gates、runtime bridge regressions、A–L milestone gates。 |
| Native gate | Updates do not steal focus；collapse does not Cancel；Result remains correlated；blocking controls absent without signals。 |
| Stop conditions | missing fact is guessed；stale event replaces current；unsupported control enabled；backend lifecycle change required。 |
| Expected evidence | Signal inventory、mapping table、unsupported facts/capabilities、Red/Green traces、event correlation、tests/native/manual、rollback。 |
| Exit status | Complete or Complete-with-non-blocking-TBD only for fact-supported subset；missing required fact may yield `SLICE_BLOCKED` / `BACKEND_INTEGRATION_MISSING`。STOP。 |

## 24. Slice 9 Execution Card — Expanded Conversation

| Field | Execution contract |
|---|---|
| Slice | `9 — Expanded Conversation` |
| Status | **NOT AUTHORIZED**；requires accepted Slice 8 + approved capacity evidence |
| Goal | Promote the same conversation context only when Compact capacity is demonstrably insufficient。 |
| Authority | 06 §§10.3、14、17；07 §§13–14、20、25；08 §18。 |
| Dependencies | Slice 8 approved；observed content/task pressure and promotion rule approved。 |
| Expected scope | Existing Conversation Model/Coordinator、host presentation mode and anchoring/promotion tests；no Workspace。 |
| Protected contracts | one context/session；draft/focus/selection continuity；manual collapse；no permanent chat chrome；long text alone is insufficient。 |
| First TDD behaviour | An explicit approved Expand intent promotes the same context exactly once while preserving draft and semantic focus。 |
| Required tests | promotion guard、identity/context continuity、focus/no-steal、collapse、native placement；Milestone 1/2 regressions。 |
| Native gate | promotion/collapse placement、focus、Z-order/taskbar and Schwarz relationship at work-area edges。 |
| Stop conditions | duplicate session/window；draft/context loss；unapproved automatic trigger；Workspace/chat-app structure appears。 |
| Expected evidence | Capacity evidence、approved trigger、context identity、focus/placement traces、tests/manual、rollback。 |
| Exit status | Complete only for approved measured trigger；otherwise `SLICE_BLOCKED`。`READY_FOR_REVIEW` then STOP。 |

## 25. Slice 10 Execution Card — Keyboard Fast Entry

| Field | Execution contract |
|---|---|
| Slice | `10 — Keyboard Fast Entry` |
| Status | **BLOCKED — Shortcut TBD**；must not execute |
| Goal | Reuse Slice 7 invocation seam after exact shortcut product contract approval。 |
| Authority | 06 §§5.3、19.3；07 §§20.5、33；08 §19。 |
| Dependencies | Slice 7 approved + explicit User decision on key、scope、default、conflict/accessibility policy。 |
| Expected scope | Approved platform registration adapter and lifecycle only；never direct Capsule construction。 |
| Protected contracts | same create/restore/focus behaviour；blocking Overlay priority；safe registration conflict/unregister；pet gestures unchanged。 |
| First TDD behaviour | After approval only：adapter registration success invokes the existing semantic intent exactly once。 |
| Required tests | registration/conflict/denial/unregister/repeat/disabled policy + Slice 7 invocation regressions。 |
| Native gate | Mandatory real Windows register、collision、focus、repeat and shutdown/unregister。 |
| Stop conditions | Shortcut still TBD；key guessed；conflict steals existing shortcut；alternate invocation path or leaked registration。 |
| Expected evidence | Product approval reference、registration lifecycle、conflict trace、tests/native/manual、rollback。 |
| Exit status | While TBD: `SLICE_BLOCKED`。Do not write code/tests。After future authorization，normal review/STOP rule applies。 |

## 26. Slice 11 Execution Card — Workspace

| Field | Execution contract |
|---|---|
| Slice | `11 — Workspace` |
| Status | **DEFERRED**；not an executable current card |
| Goal | Future smallest Workspace boundary for production-proven complex persistent tasks。 |
| Authority | 06 §§14、18.2、19；07 §§20、23、33；08 §20。 |
| Dependencies | Slices 8/9 production-proven + Product and Engineering Readiness Review + dedicated screen/state/TDD amendment if needed。 |
| Expected scope | None is authorized now；file/class structure remains unfrozen。 |
| Protected contracts | Workspace never default；same context/task/artifacts；manual collapse；no IDE/sidebar/dashboard/raw logs；backend untouched。 |
| First TDD behaviour | TBD only after new review；09 does not invent it。 |
| Required tests | Future approved promotion、artifact continuity、lifecycle/focus/native gates plus all prior regressions。 |
| Native gate | Future mandatory multi-window focus/Z-order/taskbar/collapse/restore。 |
| Stop conditions | no real task evidence；no approved spec；backend redesign；Workspace becomes permanent/default；attempt to infer future file structure。 |
| Expected evidence | Future task corpus、capacity failures、approved design/TDD delta、tests/native/manual and rollback。 |
| Exit status | `DEFERRED`。Do not execute because preceding Slices passed。A new authorization packet is mandatory。 |

## 27. Executor Output Format

DeepSeek 每个 Slice 结束时必须原样采用以下结构。不得省略空项；不适用时写 `NOT_REQUIRED` 并解释原因。

```markdown
# Executor Handoff Report

## Execution Summary
Slice:
Status:
Authority used:
Authorized scope:

## Repository State
Branch/worktree:
Initial git status:
Final git status:
User-owned pre-existing changes preserved:

## Baseline
Command:
Result:
Classification:

## Behaviour / TDD Trace
Public seam:
Observable behaviour:
Independent expected result:
Red or Characterization command:
Initial result:
Minimal Green change:
Final focused result:

## Tests Added / Modified
Test:
Why:
Initial result:
Final result:

## Production Changes
File:
Change:
Reason:
Contract satisfied:

## Protected Files
Protected files modified: YES/NO
Authorization and added gates if YES:

## Regression Results
Command:
Result:

## Native Results
Status: PASS / FAIL / SKIPPED / NOT_REQUIRED
Command/environment:
Result/reason:

## Manual Acceptance
Check:
Status: PASS / FAIL / NOT_RUN
Evidence:

## Stop Conditions Checked
- Condition:
  Result:

## Failure Classification
Failure:
Classification:
Evidence:
Disposition:

## Residual Risks
- Actual remaining risk only

## Scope Deviations
None

or

Scope delta:
Reason:
Repository evidence:
Authorization:
Added tests/gates:

## Deferred Findings
Finding:
Evidence:
Impact:
Recommended separate task:

## Rollback Boundary
Change set / commit:
How to revert safely:
State/data implications:

## Final Slice Status
SLICE_COMPLETE

## Next Action
READY_FOR_REVIEW
```

`Final Slice Status` 只能使用：

- `SLICE_COMPLETE`
- `SLICE_COMPLETE_WITH_NON_BLOCKING_TBD`
- `SLICE_BLOCKED`
- `PREREQUISITE_BUG_FOUND`
- `ARCHITECTURE_CONFLICT`
- `PRODUCT_CONFLICT`

`Next Action` 完成后只能是：

```text
READY_FOR_REVIEW
```

不得写 `Proceeding to Slice N+1` 或任何等价表述。

## 28. Evidence Standard

### 28.1 Quality requirements

禁止：

- `Everything works.`
- `Tests mostly pass.`
- `Native validation done.`（实际为 offscreen / skipped）
- `Probably unrelated.`（无证据）

必须给出：

- exact command；
- exact exit/result，例如 `43 passed, 1 skipped in ...`；
- failed/skipped test names and reasons；
- before/after classification；
- changed-file list and protected-file audit；
- native platform/environment；
- manual expected/actual result；
- rollback boundary and residual risk。

### 28.2 TDD evidence

New behaviour 至少包含一次可验证 Red 和对应最小 Green。Existing correct behaviour 包含 characterization authority、initial Green/current result 与 regression role。每个 test 必须说明 public seam、observable behaviour 和独立 expected source；不得以内部 call count、private method 或 mock choreography 代替产品行为。

### 28.3 Native evidence

Native evidence 至少记录 OS、Qt version/platform、window role/flags relevant to the Slice、production Schwarz composition prerequisite、exact command/result、BODY/OVERFLOW route、focus/Z-order/taskbar/DPI context。`SKIPPED` 必须给出具体 prerequisite；required native gate skipped/blocked 时 Slice 不能 Complete。

### 28.4 Diff evidence

报告 initial/final `git status`、changed files、diff summary、unexpected files and user-owned pre-existing changes。不得清理、格式化、提交或覆盖不属于当前 Slice 的用户改动。

## 29. Reviewer Acceptance Standard

GPT Reviewer 应使用 repo diff + evidence package + 06–09 判断；不能只依赖 Executor 的结论。

Slice 只有同时满足以下 conjunction 才可批准：

```text
contract satisfied
AND tests pass
AND required regression passes
AND required native gate passes
AND required manual acceptance passes
AND no unauthorized protected-core change
AND scope deviations are approved/contained
AND rollback is clear
AND evidence is reproducible
```

Reviewer 只能给出：

- `APPROVED`
- `APPROVED_WITH_NON_BLOCKING_TBD`
- `CHANGES_REQUIRED`
- `BLOCKED`

`APPROVED` 不自动等于下一 Slice 已授权。只有 User 可以给出下一 Slice 的明确 execution authorization。

Reviewer checklist：

```text
[ ] Correct Slice and authority used
[ ] Diff stays within expected/approved scope
[ ] Public seam and behaviour are specification-level
[ ] Red/characterization and minimum Green are evidenced
[ ] Focused and regression commands/results are exact
[ ] Required native/manual gates genuinely executed
[ ] Left Click / Drag and other global contracts remain green
[ ] Protected core audit is clean or explicitly authorized
[ ] Failure classifications have evidence
[ ] Rollback is independent and safe
[ ] Executor stopped and did not begin the next Slice
```

## 30. Commit / Git Rules

- Before editing，record branch/worktree and full `git status`；separate user-owned dirty files from Slice scope。
- Do not use destructive reset/checkout/clean or discard unrelated work。
- If commit authority is granted，use one logical commit or a small explicitly related set per Slice。A test/implementation/review-only refactor split is acceptable when traceable。
- Never mix Slice 4 + Slice 5、6A + production 6B without their separate review gates，or any two independently authorized Slices in one commit。
- Do not combine right-click cutover、Ask wiring and Agent projection。
- Commit message/description must name the Slice、contracts、tests and rollback edge。
- No commit、push、PR or branch creation is implied by this document；each external/state-changing Git action follows the user's explicit authorization。

## 31. Deferred Findings

During execution，dead code、naming/style issues、architecture smells、unrelated bugs and future capability ideas are recorded，not fixed：

```markdown
Deferred Finding:
Finding:
Evidence:
Impact:
Why outside current Slice:
Recommended separate task:
```

A Deferred Finding must not become a hidden scope delta、future-Slice preparation or repository-wide cleanup。

## 32. Milestone Review Rules

### 32.1 Milestone 1 — Slices 0–7

After Slice 7 Executor handoff and Slice-level review，STOP for a separate **Full Frontend Milestone Review** before Slice 8 authorization。Review：

- Left Click exactly one Interact in all contexts；
- Drag/BODY/OVERFLOW/release/landing zero regression；
- Palette QMenu XOR cutover and capability parity；
- K explicit Schwarz click and L ordinary outside click；
- Ask dismiss/create-or-restore/focus ordering；
- one Capsule/context、draft/IME/caret/selection safety；
- focus、Z-order、taskbar、DPI/native Windows evidence；
- calm Character-only return、Control Center/tray recovery；
- rollback of Ask and right-click cutover independently。

Milestone review vocabulary follows §29。Passing Milestone 1 still requires User authorization for Slice 8。

### 32.2 Before Workspace

Before Slice 11，perform a new **Product + Engineering Readiness Review** proving：

- Slices 8 and 9 are production-proven；
- real tasks exceed Expanded Conversation capacity；
- Workspace product need、promotion、screen/state contract and minimum scope are approved；
- Agent fact/artifact contracts are sufficient；
- native multi-window/focus/taskbar and rollback plan exists；
- Workspace will not become Dashboard、IDE、permanent chat shell or backend redesign。

Slice 11 is never auto-authorized by successful earlier Slices。

## 33. Completion / Stop Rules

DeepSeek must stop immediately when：

- the authorized Slice reaches an exit status；
- any 08/09 stop condition occurs；
- authority/repository drift is material；
- a protected-core change is required without approval；
- required backend or native evidence is missing；
- a new prerequisite production defect is found；
- a product/engineering conflict appears；
- completing the next behaviour would cross the current Slice boundary。

### DeepSeek completion checklist

```text
[ ] Slice scope respected
[ ] TDD or characterization evidence recorded
[ ] Focused tests pass or failure is classified
[ ] Required regressions pass
[ ] Native gate handled correctly; skip is not pass
[ ] Manual acceptance recorded
[ ] Protected contracts unchanged
[ ] No unrelated cleanup
[ ] Scope deviations explicitly recorded/authorized
[ ] Rollback boundary clear
[ ] Final Slice Status assigned
[ ] READY_FOR_REVIEW emitted
[ ] Next Slice NOT started
```

Current handoff terminus：

```text
CURRENT AUTHORIZED EXECUTION:
Stage 9 / Slice 0 — Characterization / Baseline

Slice 1 is NOT authorized yet.
Do not start Slice 1 after Slice 0.
```

## 34. Do Not Duplicate 08

`08` 是详细 Implementation Plan；`09` 是执行合同、导航和交回标准。Execution Card 只抽取 goal、must-not-break、gate、stop 和 evidence，并始终链接到 08 的完整 Slice 章节。

如果 09 Card 与 08 细节不同：

1. STOP；
2. 引用两个具体段落；
3. 不选择更方便的一版；
4. 请求 GPT/User reconciliation。

不得把 09 扩写成第二份 Implementation Plan，也不得以更新 Card 的方式静默改变 08 的 Slice 顺序、expected files、test set、native gate、rollback 或 exit criteria。

---

Document creation status：

```text
Production code modified: NO
Tests modified: NO
Implementation Slice executed: NO
DeepSeek execution started: NO
```
