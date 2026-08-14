# Schwarz Production Animation TDD Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the frozen Schwarz production desktop-pet runtime with six
Spine 3.8 animations, deterministic autonomous behavior, explicit hold,
transactional external role packs, persistent tray lifetime, and correct
high-DPI rendering.

**Architecture:** Merge the already-tested action-runtime history into the
Spine worktree, then deepen `PetAnimationEngine` as the single application
transaction seam. Pure scheduler, manifest, registry, and arbitration modules
remain Qt-free; a Spine 3.8 player adapter translates verified native Track 0
events into stable playback identities; Qt owns only window, tray, and render
lifecycle.

**Tech Stack:** Python 3.13.6, PySide6 6.11.1, pytest, C++17, CMake/CTest,
official `spine-cpp` 3.8, Qt OpenGL 3.3 FBO, ruff, mypy.

## Global Constraints

- Follow red-green-refactor: no production behavior without a focused test
  that was observed failing for the intended reason.
- Preserve existing public identifiers and interfaces; add only the frozen
  backward-compatible methods.
- Keep `.skel`, `.atlas`, `.png`, screenshots, and evidence external and
  untracked; never write to role-pack asset directories.
- Spine packages are complete, single-page, absolute-path, SHA-256-pinned,
  Spine 3.8 packages; never mix assets across packs.
- Preserve Agent/provider/credential/prompt/session/network isolation.
- Preserve the action-runtime worktree's uncommitted
  `docs/legal/gpl_migration_audit.md`; integrate only committed branch history.
- Known pre-implementation environment exception: the current PySide6 wheel
  emits a missing-font-directory warning in `qt_pet_smoke.py`, causing
  `test_pet_smoke_isolates_inherited_qt_environment` to fail before feature
  changes. Do not hide or broaden warning classification as part of this work.
- Run focused suites after every task and full static/native/Qt gates at the
  final task.

---

### Task 1: Integrate the Existing Action Runtime

**Files:**
- Merge: committed history from `codex/arkpets-action-runtime`
- Resolve: `src/arkclaw/presentation/qt/pet_window.py`
- Resolve: `tests/qt/test_pet_window.py`
- Preserve: `docs/legal/gpl_migration_audit.md` from branch history only

**Interfaces:**
- Consumes: Spine branch HEAD and action-runtime commit `021bcbe`.
- Produces: one integrated branch exposing `PetActionArbiter`,
  `PetSequenceRunner`, `PetTrack0Controller`, `PetAnimationEngine`, and the
  current Spine/OpenGL renderer.

- [ ] **Step 1: Merge committed action-runtime history**

Run:

```powershell
git merge --no-ff codex/arkpets-action-runtime
```

Expected: conflicts only in `pet_window.py` and `test_pet_window.py`.

- [ ] **Step 2: Resolve conflicts by composition**

Keep both the Spine renderer imports/lifecycle and action-runtime Track 0
construction/event forwarding. Keep every test from both sides; do not select
one whole version over the other.

- [ ] **Step 3: Verify the integrated existing contracts**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_pet_action_arbiter.py tests/unit/test_pet_sequence_runner.py tests/unit/test_pet_track0_controller.py tests/unit/test_spine38_runtime.py tests/qt/test_spine38_renderer.py tests/qt/test_pet_window.py -q
```

Expected: feature-relevant tests pass; only the documented Qt font-warning
baseline test may fail when included.

- [ ] **Step 4: Commit the resolved merge**

```powershell
git add src/arkclaw/presentation/qt/pet_window.py tests/qt/test_pet_window.py
git commit
```

### Task 2: Freeze Production Actions, Sources, and Role-Pack Registry

**Files:**
- Create: `src/arkclaw/application/pet_production_actions.py`
- Create: `src/arkclaw/application/pet_role_pack.py`
- Create: `tests/unit/test_pet_production_actions.py`
- Create: `tests/unit/test_pet_role_pack.py`
- Modify: `src/arkclaw/application/pet_state.py`
- Modify: `src/arkclaw/application/pet_action_sequence.py`

**Interfaces:**
- Produces:
  `ProductionAction`, `ActionOrigin`, `ActionSource`,
  `AutonomousExecutionMode`, `ActionIntent`, `PendingExplicitIntent`,
  `RolePackManifest`, `ValidatedRolePackIdentity`, and
  `AnimationRoleRegistry`.
- Consumes: existing `PetMotionState`, `PetActivityState`, `PetActionName`, and
  `AnimationBinding`.

- [ ] **Step 1: Write failing enum, source-validation, semantic-map tests**

```python
def test_production_action_semantics_are_complete() -> None:
    assert semantic_target(ProductionAction.SPECIAL).activity is PetActivityState.SPECIAL
    assert semantic_target(ProductionAction.INTERACT).activity is PetActivityState.INTERACT

def test_agent_source_cannot_claim_autonomous_origin() -> None:
    with pytest.raises(ValueError):
        ActionIntent(ProductionAction.RELAX, ActionOrigin.AUTONOMOUS, ActionSource.AGENT, object())
```

Run the two tests and verify they fail because the new module/enums do not yet
exist.

- [ ] **Step 2: Implement the minimal production action model**

```python
class ProductionAction(Enum):
    RELAX = "relax"
    MOVE_LEFT = "move_left"
    MOVE_RIGHT = "move_right"
    SIT = "sit"
    SLEEP = "sleep"
    SPECIAL = "special"
    INTERACT = "interact"

class ActionOrigin(Enum):
    SYSTEM = "system"
    EXPLICIT = "explicit"
    AUTONOMOUS = "autonomous"
```

Add the frozen `ActionSource` and execution-mode values, content-free intent
dataclasses, `SPECIAL`/`INTERACT` activity values, and exhaustive semantic
mapping.

- [ ] **Step 3: Write failing manifest and normalized-identity tests**

Cover absolute paths, hashes, Spine version `3.8`, one texture page, exact
physical animation bindings, Move alias policy, missing optional capabilities,
and same-path/different-hash inequality.

- [ ] **Step 4: Implement immutable manifest and registry validation**

`ValidatedRolePackIdentity` equality must use normalized schema, pack ID,
hashes, bindings, direction, and framing—not manifest path.

- [ ] **Step 5: Run focused tests and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_pet_production_actions.py tests/unit/test_pet_role_pack.py tests/unit/test_pet_state_animation_compatibility.py -q
git add src/arkclaw/application/pet_production_actions.py src/arkclaw/application/pet_role_pack.py src/arkclaw/application/pet_state.py src/arkclaw/application/pet_action_sequence.py tests/unit/test_pet_production_actions.py tests/unit/test_pet_role_pack.py
git commit -m "feat: define production pet actions and role packs"
```

### Task 3: Build the Pure Autonomous Scheduler

**Files:**
- Create: `src/arkclaw/application/pet_autonomous_scheduler.py`
- Create: `tests/unit/test_pet_autonomous_scheduler.py`

**Interfaces:**
- Produces: `AutonomousState`, `AutonomousSchedulerState`,
  `AutonomousBoundaryEvent`, `AutonomousRuntimeSnapshot`,
  `AutonomousSchedulerDecision`, `AutonomousActionScheduler.evaluate()`,
  `.commit_accepted()`, and `.reject()`.
- Consumes: `ActionIntent`, available capabilities, `RandomSource`, and a
  monotonic fake clock value supplied by callers.

- [ ] **Step 1: Write RED tests for deterministic weighted history**

Use fixed RNG fakes, not statistical assertions. Pin one exact history for one
seed and prove a second seed yields a different exact history.

- [ ] **Step 2: Implement validated immutable weights and dwell profiles**

Use the frozen matrix and ranges verbatim. Filter unavailable roles before
weighted selection and fail closed to Relax on an invalid remaining row.

- [ ] **Step 3: Write RED boundary-identity and STAY tests**

Implement the named cases:

```text
duplicate_loop_boundary_is_side_effect_free
stay_consumes_boundary_once
new_loop_boundary_with_same_generation_and_token_is_valid
old_boundary_cannot_trigger_after_new_dwell_deadline
```

- [ ] **Step 4: Implement boundary consumption and proposal/commit**

Match generation/token, require strictly greater `boundary_index`, consume
pre-deadline unique boundaries, and never sample destination dwell before
`commit_accepted()`.

- [ ] **Step 5: Run focused tests and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_pet_autonomous_scheduler.py -q
git add src/arkclaw/application/pet_autonomous_scheduler.py tests/unit/test_pet_autonomous_scheduler.py
git commit -m "feat: add deterministic autonomous action scheduler"
```

### Task 4: Extend Arbitration and Engine Control Modes

**Files:**
- Modify: `src/arkclaw/application/pet_track0.py`
- Modify: `src/arkclaw/application/pet_animation.py`
- Create: `tests/unit/test_pet_explicit_action_control.py`
- Modify: `tests/unit/test_pet_action_arbiter.py`
- Modify: `tests/unit/test_pet_animation_transactions.py`

**Interfaces:**
- Produces: `PetAnimationEngine.request_action()`,
  `PetAnimationEngine.resume_autonomous()`, engine `execution_mode`, and
  complete protected-continuation ownership.
- Extends: `ActionRequest` with orthogonal `origin` and `source`.

- [ ] **Step 1: Write the exhaustive RED origin tie-break matrix**

Prove `EXPLICIT > AUTONOMOUS` only for equal `NORMAL_ACTION`; source never
changes priority; safety, user interaction, strict, and shutdown retain their
existing order.

- [ ] **Step 2: Implement origin/source arbitration minimally**

Do not introduce a new interruption class. Preserve duplicate request-token
and drag-session rules.

- [ ] **Step 3: Write RED explicit-hold and idempotence tests**

Cover explicit loop entry, scheduler suspension, same held action as an
accepted no-op, explicit replacement, and Resume Autonomous establishing a
fresh confirmed Relax dwell.

- [ ] **Step 4: Write RED protected continuation tests**

Cover latest-wins pending intent, fresh semantic epoch on consumption,
resume-after-protected, and the four mandatory-clear tests for safety, drag,
pause, and shutdown.

- [ ] **Step 5: Implement engine mode and continuation transactions**

Keep pending high-level intent separate from `PetSequenceRunner` and build a
fresh Track 0 request only when consuming it. Any protected invalidation clears
both continuation fields.

- [ ] **Step 6: Run focused tests and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_pet_action_arbiter.py tests/unit/test_pet_animation_transactions.py tests/unit/test_pet_explicit_action_control.py -q
git add src/arkclaw/application/pet_track0.py src/arkclaw/application/pet_animation.py tests/unit/test_pet_action_arbiter.py tests/unit/test_pet_animation_transactions.py tests/unit/test_pet_explicit_action_control.py
git commit -m "feat: coordinate explicit and autonomous pet actions"
```

### Task 5: Expose Verified Spine Track Events and Player Adapter

**Files:**
- Modify: `native/spine38_bridge/include/arkclaw_spine38_bridge.h`
- Modify: `native/spine38_bridge/src/arkclaw_spine38_bridge.cpp`
- Modify: `native/spine38_bridge/tests/spine38_bridge_contract_test.cpp`
- Modify: `src/arkclaw/infrastructure/spine38_native.py`
- Modify: `src/arkclaw/application/spine38_runtime.py`
- Create: `src/arkclaw/presentation/qt/spine38_player.py`
- Create: `tests/unit/test_spine38_player_events.py`
- Create: `tests/qt/test_spine38_player.py`

**Interfaces:**
- Produces: native immutable Track 0 event views, `Spine38PlaybackEvent`, and
  `Spine38AnimationPlayer` satisfying existing `AnimationPlayer`.
- Event identity: event type, physical animation, loop ordinal, current
  generation, and Python playback token.

- [ ] **Step 1: Write failing C++ event contract tests**

Verify one-shot completion, loop ordinals `1,2,3`, queue reset/containment on
new Track 0 binding, undersized view rejection, and no zero-duration sentinel
events.

- [ ] **Step 2: Implement the minimal native event queue ABI**

Attach the official Spine 3.8 AnimationState listener. Stamp a physical loop
ordinal once at the native source; Qt duplicates must reuse the resulting
Python event object/index.

- [ ] **Step 3: Write failing ctypes/runtime adapter tests**

Prove ABI narrowing, stable fixed errors, event copying before native lifetime
ends, and no asset/path leakage.

- [ ] **Step 4: Implement Python event and player adapters**

`play()` maps exactly one Track 0 request to `set_animation`; `clear()`
contains Track 0; `update()` emits content-free events tagged with the active
generation/token and stable boundary index.

- [ ] **Step 5: Run native and Python gates and commit**

```powershell
cmake --build build\spine38 --config Release
ctest --test-dir build\spine38 -C Release --output-on-failure
.\.venv\Scripts\python.exe -m pytest tests/unit/test_spine38_native.py tests/unit/test_spine38_runtime.py tests/unit/test_spine38_player_events.py tests/qt/test_spine38_player.py -q
git add native/spine38_bridge src/arkclaw/infrastructure/spine38_native.py src/arkclaw/application/spine38_runtime.py src/arkclaw/presentation/qt/spine38_player.py tests/unit/test_spine38_player_events.py tests/qt/test_spine38_player.py
git commit -m "feat: expose verified Spine playback events"
```

### Task 6: Make Motion and Playback One Transaction

**Files:**
- Modify: `src/arkclaw/application/pet_motion.py`
- Modify: `src/arkclaw/application/pet_animation.py`
- Modify: `tests/unit/test_pet_motion.py`
- Create: `tests/unit/test_pet_production_motion.py`

**Interfaces:**
- Produces: zero-velocity containment, atomic Move start/stop/turn, and the
  unique mid-loop workspace-boundary exception.

- [ ] **Step 1: Write RED direction/velocity/facing tests**

Prove logical Move aliasing selects physical `Move`, moves the window in the
matching direction, and stops velocity in the same replacement transaction.

- [ ] **Step 2: Write RED boundary-turn and failed-play tests**

Success must clamp, reverse without Relax, allocate one new generation/token,
sample one opposite dwell, and enter autonomous mode. Failed opposite Move
must stop velocity, commit semantic Relax, mark degraded/unknown, and remain
suspended.

- [ ] **Step 3: Implement minimal motion proposals and engine commits**

`PetMotionModel` detects/contains geometry and proposes; only
`PetAnimationEngine` commits semantic/motion/playback mode changes.

- [ ] **Step 4: Run focused tests and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_pet_motion.py tests/unit/test_pet_production_motion.py tests/unit/test_pet_animation_transactions.py -q
git add src/arkclaw/application/pet_motion.py src/arkclaw/application/pet_animation.py tests/unit/test_pet_motion.py tests/unit/test_pet_production_motion.py
git commit -m "feat: synchronize pet movement and Spine playback"
```

### Task 7: Add Transactional Role-Pack Construction and Switching

**Files:**
- Modify: `src/arkclaw/application/pet_external_assets.py`
- Modify: `src/arkclaw/application/pet_role_pack.py`
- Create: `src/arkclaw/application/pet_role_pack_switch.py`
- Modify: `src/arkclaw/presentation/qt/spine38_renderer.py`
- Create: `tests/unit/test_pet_role_pack_switch.py`
- Create: `tests/qt/test_spine38_role_pack_switch.py`

**Interfaces:**
- Produces: `RolePackCandidate`, `ActiveRolePack`, and
  `RolePackSwitchCoordinator.switch()` with prepare/quiesce/commit phases.

- [ ] **Step 1: Write RED candidate validation and failure-containment tests**

Cover absolute read-only files, hashes, version, catalog, aliases, one page,
cross-pack rejection, candidate partial cleanup, and same-path changed-hash
reload.

- [ ] **Step 2: Implement candidate preparation without active mutation**

The candidate owns its temporary native/renderer resources and closes them on
every precommit failure.

- [ ] **Step 3: Write RED switch transaction tests**

Cover quiesce to Relax/zero velocity, complete continuation clear, old clear
failure retaining old identity with unknown/degraded health, commit-before-old
destroy, and healthy candidate Relax before autonomy resumes.

- [ ] **Step 4: Implement GUI-thread two-phase switch**

Never use destructive fallback when active/candidate resources cannot coexist.

- [ ] **Step 5: Run focused tests and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_pet_external_assets.py tests/unit/test_pet_role_pack.py tests/unit/test_pet_role_pack_switch.py tests/qt/test_spine38_role_pack_switch.py -q
git add src/arkclaw/application/pet_external_assets.py src/arkclaw/application/pet_role_pack.py src/arkclaw/application/pet_role_pack_switch.py src/arkclaw/presentation/qt/spine38_renderer.py tests/unit/test_pet_role_pack_switch.py tests/qt/test_spine38_role_pack_switch.py
git commit -m "feat: switch external pet role packs transactionally"
```

### Task 8: Wire the Production Tray and Persistent Lifecycle

**Files:**
- Modify: `src/arkclaw/presentation/qt/system_tray.py`
- Modify: `src/arkclaw/presentation/qt/pet_application.py`
- Modify: `src/arkclaw/presentation/qt/pet_window.py`
- Create: `tests/qt/test_pet_production_actions.py`
- Create: `tests/qt/test_pet_production_lifecycle.py`

**Interfaces:**
- Extends existing tray callbacks with one typed action callback and one
  `resume_autonomous` callback.
- Preserves `PetApplicationCoordinator`, one `PetWindow`, one tray, and
  controlled-shutdown interfaces.

- [ ] **Step 1: Write RED tray menu/state tests**

Require seven actions, Move Left/Right submenu, Resume Autonomous, current
pack identity, disabled unavailable roles, and no Agent imports.

- [ ] **Step 2: Implement tray callbacks through the typed engine gateway**

Do not parse text or promote tray actions to `USER_INTERACTION`.

- [ ] **Step 3: Write RED persistent-lifecycle tests**

Fake completion, scheduler, hide, and close events must never call `quit()`;
explicit tray Exit must call the existing controlled shutdown once. Startup
failure must retain tray plus placeholder.

- [ ] **Step 4: Compose the production Spine role pack at `main()`**

Keep the timed three-loop script diagnostic-only. Construct exactly one window
and one tray; inject the player/engine without importing Agent modules.

- [ ] **Step 5: Run focused tests and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/qt/test_pet_production_actions.py tests/qt/test_pet_production_lifecycle.py tests/qt/test_pet_window.py tests/qt/test_single_instance.py -q
git add src/arkclaw/presentation/qt/system_tray.py src/arkclaw/presentation/qt/pet_application.py src/arkclaw/presentation/qt/pet_window.py tests/qt/test_pet_production_actions.py tests/qt/test_pet_production_lifecycle.py
git commit -m "feat: run Schwarz actions through the production tray"
```

### Task 9: Correct DPR, Atlas Filtering, and Fixed Framing

**Files:**
- Modify: `native/spine38_bridge/include/arkclaw_spine38_bridge.h`
- Modify: `native/spine38_bridge/src/arkclaw_spine38_bridge.cpp`
- Modify: `native/spine38_bridge/tests/spine38_bridge_contract_test.cpp`
- Modify: `src/arkclaw/infrastructure/spine38_native.py`
- Modify: `src/arkclaw/application/pet_mesh_model.py`
- Modify: `src/arkclaw/presentation/qt/pet_mesh_opengl_renderer.py`
- Modify: `src/arkclaw/presentation/qt/spine38_renderer.py`
- Modify: `src/arkclaw/presentation/qt/pet_window.py`
- Modify: `tests/qt/test_pet_mesh_opengl_backend.py`
- Modify: `tests/qt/test_spine38_renderer.py`

**Interfaces:**
- Produces: independent min/mag filter metadata, real window DPR propagation,
  ceil-sized physical FBOs, and one immutable pack-session transform.

- [ ] **Step 1: Write RED native filter propagation tests**

Cover declared Nearest/Linear combinations and absent-field fallback metadata.

- [ ] **Step 2: Expose filter enums through native, ctypes, and mesh model**

Preserve ABI size/version checks and reject unknown enum values fail-closed.

- [ ] **Step 3: Write RED DPR/FBO tests for 1.0, 1.25, 1.5, and 2.0**

Assert `ceil(W*d) x ceil(H*d)`, screen/DPR change replacement, no 1x
intermediate upscale, and no logical footprint/baseline change.

- [ ] **Step 4: Implement window DPR propagation and independent filters**

Use each declared atlas filter independently; fallback only the missing field
to Linear. Recreate the FBO on logical size, DPR, or screen change.

- [ ] **Step 5: Write RED six-animation fixed-framing tests**

Sample all six animations under one immutable transform and reject any
nontransparent crop or per-frame reframe.

- [ ] **Step 6: Implement fixed role-pack framing and run gates**

```powershell
cmake --build build\spine38 --config Release
ctest --test-dir build\spine38 -C Release --output-on-failure
.\.venv\Scripts\python.exe -m pytest tests/qt/test_pet_mesh_opengl_backend.py tests/qt/test_spine38_renderer.py tests/unit/test_spine38_native.py -q
git add native/spine38_bridge src/arkclaw/infrastructure/spine38_native.py src/arkclaw/application/pet_mesh_model.py src/arkclaw/presentation/qt/pet_mesh_opengl_renderer.py src/arkclaw/presentation/qt/spine38_renderer.py src/arkclaw/presentation/qt/pet_window.py tests/qt/test_pet_mesh_opengl_backend.py tests/qt/test_spine38_renderer.py
git commit -m "fix: render Spine pets at the real window DPR"
```

### Task 10: End-to-End Production Verification

**Files:**
- Modify: `tests/integration/test_spine38_schwarz_catalog.py`
- Modify: `tests/qt/test_spine38_schwarz_smoke.py`
- Modify: `scripts/qt_spine38_vertical_slice.py` only to keep it explicitly
  diagnostic; do not convert it into the production launcher
- Modify: relevant docs under `docs/`

**Interfaces:**
- Produces: deterministic six-action production evidence and final operator
  smoke instructions without tracked assets/screenshots.

- [ ] **Step 1: Add RED integration assertions**

Verify exact six names/durations, Move aliasing, one-shot completion identity,
pack hashes, no tracked assets, and Agent/provider isolation.

- [ ] **Step 2: Run all focused feature suites**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_pet_* tests/unit/test_spine38_* tests/qt/test_pet_production_* tests/qt/test_spine38_* -q
```

- [ ] **Step 3: Run static and native gates**

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests scripts
.\.venv\Scripts\python.exe -m mypy
cmake --build build\spine38 --config Release
ctest --test-dir build\spine38 -C Release --output-on-failure
```

- [ ] **Step 4: Run the complete pytest suite**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Report the known PySide6 font-warning baseline separately if still present;
do not describe the full suite as passing unless it actually has zero
failures.

- [ ] **Step 5: Run the manual Windows production smoke**

Launch the production entry point with the external Schwarz manifest. Verify
clarity at the active DPR, all seven logical actions, autonomous randomness,
Move direction/window motion, protected pending/resume behavior, tray
persistence, transparency, fixed foot baseline, and explicit tray Exit.

- [ ] **Step 6: Commit final tests and documentation**

```powershell
git add tests scripts docs
git commit -m "test: verify Schwarz production animation runtime"
```
