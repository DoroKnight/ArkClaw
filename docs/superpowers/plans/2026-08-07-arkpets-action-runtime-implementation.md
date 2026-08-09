# ArkPets Action Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the frozen ArkPets-inspired action sequencing architecture as a pure-Python, capability-gated Track 0 runtime while preserving the current placeholder renderer and local Agent lifecycle.

**Architecture:** Keep immutable action names, sequences, catalog entries, and registry bindings in `pet_action_sequence.py`; keep arbitration, runner state, player protocol, generation, health, cancellation, and watchdog behavior in `pet_track0.py`; keep semantic state and epoch authority in `pet_state.py`; coordinate atomic semantic/playback transactions from `pet_animation.py`. The Qt pet window remains on `LEGACY_DIRECT` until a future renderer proves all four production capabilities.

**Tech Stack:** Python 3.13, frozen dataclasses, `Enum`, `MappingProxyType`, `Protocol`, pytest, Ruff, mypy, PySide6 regression tests.

## Global Constraints

- Treat `docs/superpowers/specs/2026-08-07-arkpets-action-sequence-reuse-design.md` as frozen and authoritative.
- Use strict TDD: every production behavior is preceded by a test that fails for the expected missing-behavior reason.
- Do not modify `PetMotionModel` ownership of position, dragging, gravity, collision, landing, or workspace constraints.
- Do not change Agent prompts, Provider activation, credentials, sessions, networking, window lifecycle, or shutdown behavior.
- Do not import Qt, Agent, Provider, runtime, credential, or network modules from `pet_action_sequence.py` or `pet_track0.py`.
- Do not add ArkPets/Arknights images, animation frames, Spine projects, audio, pet packs, Java sources, or other art assets.
- Do not claim Spine Runtime playback, Track mixing, Runtime export, or renderer callbacks are implemented.
- Preserve existing public request methods and `PetAnimationIntent.base_action`; add new fields with backward-compatible defaults where needed.
- Leave the unrelated Mesh/OpenGL files in the original worktree untouched.

---

### Task 1: Immutable Logical Catalog, Sequences, and Registry

**Files:**
- Create: `src/sjtuclaw/application/pet_action_sequence.py`
- Create: `tests/unit/test_pet_action_sequence_catalog.py`

**Interfaces:**
- Produces: `PetActionName`, `SequenceName`, `SequenceTerminal`, `InterruptClass`, `PlaybackHealth`, `PetActionStep`, `PetActionSequence`, `SequenceCatalogEntry`, `AnimationBinding`, `AnimationRegistry`, `SEQUENCE_CATALOG`, `default_animation_registry()`.
- Consumes: no application, Qt, Agent, renderer, or filesystem services.

- [ ] **Step 1: Write the failing immutable-catalog tests**

```python
def test_logical_catalog_is_exact_and_case_sensitive() -> None:
    assert tuple(action.value for action in PetActionName) == (
        "idle", "breathing", "blink", "walk_left", "walk_right",
        "run_left", "run_right", "sit_down", "sit_idle", "sleep_start",
        "sleep_loop", "sleep_end", "wave", "happy", "think", "read",
        "type", "remind", "confused", "angry", "drag_start", "drag_loop",
        "drag_end", "landing", "return_idle",
    )
    with pytest.raises(ValueError):
        PetActionName("Sleep_Loop")


def test_sequence_is_immutable_and_step_has_no_successor_pointer() -> None:
    step = PetActionStep(PetActionName.IDLE, loop=True)
    sequence = PetActionSequence((step,), loop_index=0)
    assert not hasattr(step, "next")
    with pytest.raises(FrozenInstanceError):
        sequence.loop_index = None  # type: ignore[misc]


def test_then_returns_new_ordered_sequence_without_mutating_source() -> None:
    source = PetActionSequence((PetActionStep(PetActionName.WAVE, False),))
    result = source.then(PetActionStep(PetActionName.RETURN_IDLE, False))
    assert tuple(step.action for step in source.steps) == (PetActionName.WAVE,)
    assert tuple(step.action for step in result.steps) == (
        PetActionName.WAVE,
        PetActionName.RETURN_IDLE,
    )
```

- [ ] **Step 2: Run Task 1 tests and verify RED**

Run: `python -m pytest -q tests/unit/test_pet_action_sequence_catalog.py`

Expected: collection fails because `pet_action_sequence` does not exist.

- [ ] **Step 3: Implement the immutable types and validation**

```python
class PetActionName(Enum):
    IDLE = "idle"
    BREATHING = "breathing"
    BLINK = "blink"
    WALK_LEFT = "walk_left"
    WALK_RIGHT = "walk_right"
    RUN_LEFT = "run_left"
    RUN_RIGHT = "run_right"
    SIT_DOWN = "sit_down"
    SIT_IDLE = "sit_idle"
    SLEEP_START = "sleep_start"
    SLEEP_LOOP = "sleep_loop"
    SLEEP_END = "sleep_end"
    WAVE = "wave"
    HAPPY = "happy"
    THINK = "think"
    READ = "read"
    TYPE = "type"
    REMIND = "remind"
    CONFUSED = "confused"
    ANGRY = "angry"
    DRAG_START = "drag_start"
    DRAG_LOOP = "drag_loop"
    DRAG_END = "drag_end"
    LANDING = "landing"
    RETURN_IDLE = "return_idle"


@dataclass(frozen=True, slots=True)
class PetActionStep:
    action: PetActionName
    loop: bool
    speed: float = 1.0
    mix_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.speed <= 0:
            raise ValueError("Playback speed must be positive.")
        if self.mix_seconds is not None and self.mix_seconds < 0:
            raise ValueError("Mix duration must not be negative.")


@dataclass(frozen=True, slots=True)
class PetActionSequence:
    steps: tuple[PetActionStep, ...]
    loop_index: int | None = None
    loop_exit_index: int | None = None
    terminal: SequenceTerminal = SequenceTerminal.COMPLETE

    def then(self, step: PetActionStep) -> PetActionSequence:
        return replace(self, steps=(*self.steps, step))
```

Validation must reject an empty sequence, invalid loop/exit indices, a non-looping loop target, a loop exit without a loop, Track 1/2 actions on Track 0, duplicate physical bindings, empty names, missing logical bindings, case mismatch against loaded names, and missing required duration metadata.

- [ ] **Step 4: Add literal catalog and registry tests**

```python
def test_catalog_union_covers_all_25_names_and_track_ownership() -> None:
    seen = {
        step.action
        for entry in SEQUENCE_CATALOG.values()
        for step in entry.sequence.steps
    }
    assert seen == set(PetActionName)
    assert SEQUENCE_CATALOG[SequenceName.BREATHING].track == 1
    assert SEQUENCE_CATALOG[SequenceName.BLINK].track == 2
    assert all(
        step.action not in {PetActionName.BREATHING, PetActionName.BLINK}
        for entry in SEQUENCE_CATALOG.values()
        if entry.track == 0
        for step in entry.sequence.steps
    )


def test_registry_rejects_case_mismatch() -> None:
    registry = default_animation_registry()
    names = {action.value for action in PetActionName} - {"sleep_loop"}
    names.add("Sleep_Loop")
    with pytest.raises(AnimationRegistryError):
        registry.validate_loaded_names(frozenset(names))
```

- [ ] **Step 5: Run, refactor, and commit Task 1**

Run:

```powershell
python -m pytest -q tests/unit/test_pet_action_sequence_catalog.py
python -m ruff check src/sjtuclaw/application/pet_action_sequence.py tests/unit/test_pet_action_sequence_catalog.py
python -m mypy src/sjtuclaw/application/pet_action_sequence.py tests/unit/test_pet_action_sequence_catalog.py
git add src/sjtuclaw/application/pet_action_sequence.py tests/unit/test_pet_action_sequence_catalog.py
git commit -m "feat: add immutable pet action catalog"
```

Expected: all Task 1 tests pass and the two new files are the only staged paths.

---

### Task 2: Semantic Activity, Compatibility, and State-Owned Epochs

**Files:**
- Modify: `src/sjtuclaw/application/pet_state.py`
- Modify: `tests/unit/test_pet_motion.py`
- Create: `tests/unit/test_pet_state_animation_compatibility.py`

**Interfaces:**
- Produces: `PetActivityState`, running motion values, `ProposedStateTransition`, `PetLayeredState.activity`, `PetLayeredStateMachine.epoch`, `propose()`, `commit()`, `STATE_ACTION_COMPATIBILITY`, `assert_animation_compatible()`.
- Consumes: `PetActionName` and `PlaybackHealth` as pure application values; `pet_state.py` must not consume an `AnimationPlayer`.

- [ ] **Step 1: Write failing state-extension tests**

```python
def test_state_machine_owns_target_epoch_and_rejected_proposal_does_not_commit() -> None:
    machine = PetLayeredStateMachine(initial_epoch=17)
    proposal = machine.propose(activity=PetActivityState.READING)
    assert proposal.source_epoch == 17
    assert proposal.target_epoch == 18
    assert machine.epoch == 17
    machine.commit(proposal)
    assert machine.epoch == 18
    assert machine.snapshot.activity is PetActivityState.READING


def test_commit_rejects_stale_source_epoch() -> None:
    machine = PetLayeredStateMachine(initial_epoch=17)
    stale = machine.propose(activity=PetActivityState.READING)
    machine.commit(machine.propose(activity=PetActivityState.THINKING))
    with pytest.raises(PetStateTransitionError):
        machine.commit(stale)
```

- [ ] **Step 2: Verify RED, then implement the minimal proposal/commit API**

Run: `python -m pytest -q tests/unit/test_pet_state_animation_compatibility.py`

Expected: import failure for `PetActivityState` or missing constructor argument `initial_epoch`.

Implement `ProposedStateTransition` exactly with `source_state`, `target_state`, `source_epoch`, `target_epoch`, and `mandatory_for_safety`. `commit()` must compare both source state and source epoch before assigning the exact target epoch; it must never increment independently.

- [ ] **Step 3: Write the exhaustive compatibility test**

```python
@pytest.mark.parametrize("state", all_valid_layered_states())
@pytest.mark.parametrize("action", (*PetActionName, None))
def test_track0_compatibility_is_exhaustive(
    state: PetLayeredState,
    action: PetActionName | None,
) -> None:
    key = (state.lifecycle, state.motion, state.activity)
    expected = (
        action is None
        if state.lifecycle is not PetLifecycleState.ACTIVE
        else action in STATE_ACTION_COMPATIBILITY.get(key, frozenset())
    )
    if expected:
        assert_animation_compatible(state, action, PlaybackHealth.HEALTHY)
    else:
        with pytest.raises(AnimationCompatibilityError):
            assert_animation_compatible(state, action, PlaybackHealth.HEALTHY)
```

Also assert that `desired_action=None` is permitted with `DEGRADED` and `UNKNOWN`, while `dragging + sleep_loop`, `sleeping + drag_loop`, and inactive lifecycle plus `idle` are rejected.

- [ ] **Step 4: Preserve the legacy behavior projection**

Update `start_thinking()`, `finish_thinking()`, `start_reminding()`, and `finish_reminding()` to store activity while retaining `PetLayeredState.behaviors` as the overlay/compatibility view expected by existing render code. Add running values without changing existing walking methods. Re-run `tests/unit/test_pet_motion.py` and `tests/unit/test_pet_animation.py` before committing.

- [ ] **Step 5: Run, refactor, and commit Task 2**

```powershell
python -m pytest -q tests/unit/test_pet_motion.py tests/unit/test_pet_animation.py tests/unit/test_pet_state_animation_compatibility.py
python -m ruff check src/sjtuclaw/application/pet_state.py tests/unit/test_pet_motion.py tests/unit/test_pet_state_animation_compatibility.py
python -m mypy src/sjtuclaw/application/pet_state.py tests/unit/test_pet_motion.py tests/unit/test_pet_state_animation_compatibility.py
git add src/sjtuclaw/application/pet_state.py tests/unit/test_pet_motion.py tests/unit/test_pet_state_animation_compatibility.py
git commit -m "feat: add semantic animation state authority"
```

---

### Task 3: Deterministic Action Arbitration

**Files:**
- Create: `src/sjtuclaw/application/pet_track0.py`
- Create: `tests/unit/test_pet_action_arbiter.py`

**Interfaces:**
- Produces: `ActionRequest`, `CancelReason`, `CancellationMode`, `ActionOutcome`, `ArbitrationDecision`, `PetActionArbiter.decide(incoming, active, context)`.
- Consumes: immutable sequence names, interruption classes, compatibility result, playback health, and confirmed semantic epoch.

- [ ] **Step 1: Write failing named drag and priority tests**

```python
def test_drag_release_replaces_hold_in_same_input_session() -> None:
    session = object()
    decision = PetActionArbiter().decide(
        request(SequenceName.DRAG_RELEASE, session=session),
        request(SequenceName.DRAG_HOLD, session=session),
        healthy_context(),
    )
    assert decision == ArbitrationDecision(
        ActionOutcome.ACCEPTED,
        CancellationMode.REPLACE,
    )


def test_new_drag_session_replaces_previous_release() -> None:
    decision = PetActionArbiter().decide(
        request(SequenceName.DRAG_HOLD, session=object()),
        request(SequenceName.DRAG_RELEASE, session=object()),
        healthy_context(),
    )
    assert decision.mode is CancellationMode.REPLACE


def test_motion_safety_outranks_user_interaction() -> None:
    decision = PetActionArbiter().decide(
        request(SequenceName.FALL_RECOVERY),
        request(SequenceName.DRAG_HOLD, session=object()),
        healthy_context(),
    )
    assert decision.mode is CancellationMode.REPLACE
```

- [ ] **Step 2: Verify RED and implement only the total-order algorithm**

Run: `python -m pytest -q tests/unit/test_pet_action_arbiter.py`

Expected: import failure for `pet_track0`.

Use interruption ranks `500, 400, 300, 200, 100, 0`; implement the seven ordered checks and the exact equal-class matrix from frozen section 7. Do not put renderer calls or runner mutation in the arbiter.

- [ ] **Step 3: Add a literal full-matrix test**

Represent each expected cell as a literal `ArbiterCase` fixture containing incoming class, active class, protection, equality dimensions, expected outcome, and exact mode. Cross-product every rank pair and separately enumerate equal-class dimensions so no branch is example-only.

- [ ] **Step 4: Run, refactor, and commit Task 3**

```powershell
python -m pytest -q tests/unit/test_pet_action_arbiter.py
python -m ruff check src/sjtuclaw/application/pet_track0.py tests/unit/test_pet_action_arbiter.py
python -m mypy src/sjtuclaw/application/pet_track0.py tests/unit/test_pet_action_arbiter.py
git add src/sjtuclaw/application/pet_track0.py tests/unit/test_pet_action_arbiter.py
git commit -m "feat: add deterministic pet action arbiter"
```

---

### Task 4: Sequence Runner and Stale Callback Rejection

**Files:**
- Modify: `src/sjtuclaw/application/pet_track0.py`
- Create: `tests/unit/test_pet_sequence_runner.py`

**Interfaces:**
- Produces: `PlaybackToken`, `ConfirmedPlaybackEpoch`, `PlaybackEvent`, `RunnerDirective`, `PetSequenceRunner.start()`, `accept_playback()`, `handle_completion()`, `request_graceful_exit()`, `reset()`.
- Consumes: immutable `PetActionSequence`; it never calls the player or arbiter.

- [ ] **Step 1: Write failing one-shot and loop tests**

```python
def test_matching_one_shot_completion_advances_once() -> None:
    runner = started_runner(SequenceName.SLEEP, index=0, generation=10, token="p10")
    first = runner.handle_completion(event(10, PetActionName.SLEEP_START, "sleep_start", "p10"))
    second = runner.handle_completion(event(10, PetActionName.SLEEP_START, "sleep_start", "p10"))
    assert first.next_index == 1
    assert second.outcome is ActionOutcome.STALE_COMPLETION


def test_loop_boundary_without_pending_exit_is_observational() -> None:
    runner = started_runner(SequenceName.SLEEP, index=1, generation=11, token="p11")
    before = runner.snapshot
    directive = runner.handle_completion(
        event(11, PetActionName.SLEEP_LOOP, "sleep_loop", "p11", loop_boundary=True)
    )
    assert directive is None
    assert runner.snapshot == before
```

- [ ] **Step 2: Verify RED and implement runner-local state only**

Run: `python -m pytest -q tests/unit/test_pet_sequence_runner.py`

Expected: missing runner API.

Every callback comparison must match generation, logical action, physical name, playback token, and current step. A mismatch returns `STALE_COMPLETION` and changes no state.

- [ ] **Step 3: Pin graceful and replace-only loop behavior**

Add tests proving that the first matching boundary after `request_graceful_exit()` jumps once to `loop_exit_index`, and that `DRAG_HOLD` rejects graceful exit because it has no exit index. Assert `reset()` empties runner state without allocating generation or invoking any external object.

- [ ] **Step 4: Run, refactor, and commit Task 4**

```powershell
python -m pytest -q tests/unit/test_pet_sequence_runner.py
python -m ruff check src/sjtuclaw/application/pet_track0.py tests/unit/test_pet_sequence_runner.py
python -m mypy src/sjtuclaw/application/pet_track0.py tests/unit/test_pet_sequence_runner.py
git add src/sjtuclaw/application/pet_track0.py tests/unit/test_pet_sequence_runner.py
git commit -m "feat: add completion driven sequence runner"
```

---

### Task 5: Player Protocol, Track 0 Controller, Generation, and Health

**Files:**
- Modify: `src/sjtuclaw/application/pet_track0.py`
- Create: `tests/fakes/pet_animation_player.py`
- Create: `tests/unit/test_pet_track0_controller.py`

**Interfaces:**
- Produces: `AnimationPlayerCapabilities`, `PlaybackRequest`, `AnimationPlayer`, `Track0PlaybackState`, `ControllerPreflight`, `PetTrack0Controller.preflight()`, `play()`, `cancel()`, `clear()`, `handle_completion()`.
- Consumes: registry, sequence catalog, arbiter, runner, and an injected player.

- [ ] **Step 1: Write the failing generation and health tests**

```python
def test_every_play_and_clear_attempt_consumes_generation() -> None:
    player = FakeAnimationPlayer()
    controller = controller_with(player)
    controller.play(accepted_request(SequenceName.WAVE))
    controller.clear(CancelReason.PAUSE)
    assert [call.generation for call in player.calls] == [1, 2]


def test_replace_uses_clear_generation_then_play_generation() -> None:
    player = FakeAnimationPlayer()
    controller = controller_with(player)
    controller.play(accepted_request(SequenceName.DRAG_RELEASE))
    controller.cancel(
        CancelReason.USER_INTERRUPT,
        CancellationMode.REPLACE,
        replacement=accepted_request(SequenceName.DRAG_HOLD),
    )
    assert [call.generation for call in player.calls] == [1, 2, 3]


def test_failed_play_with_successful_containment_is_degraded_and_empty() -> None:
    player = FakeAnimationPlayer(fail_play=True)
    controller = controller_with(player)
    assert controller.play(accepted_request(SequenceName.WAVE)) is ActionOutcome.PLAYBACK_DEGRADED
    assert controller.state == Track0PlaybackState(None, None, PlaybackHealth.DEGRADED)
```

- [ ] **Step 2: Verify RED and implement minimal controller behavior**

Run: `python -m pytest -q tests/unit/test_pet_track0_controller.py`

Expected: missing controller/player APIs.

Allocate generation immediately before every physical `play` or `clear` attempt. Only a returned playback token creates `ConfirmedPlaybackEpoch`. On a failed play, attempt containment clear; successful containment yields no desired/confirmed action and `DEGRADED`, failed containment yields desired `None` and `UNKNOWN`. Never issue fallback idle.

- [ ] **Step 3: Add cancel/clear/reset distinction tests**

Assert:

```python
controller.cancel(reason, CancellationMode.GRACEFUL_EXIT)
# no player command; pending loop exit only

controller.clear(CancelReason.SYSTEM_SHUTDOWN)
# one clear command; runner empty; no idle play

runner.reset()
# no player command and no generation increment
```

Also test failed normal clear, stale callbacks after replacement, and player exceptions never escaping to Qt callers.

- [ ] **Step 4: Run, refactor, and commit Task 5**

```powershell
python -m pytest -q tests/unit/test_pet_track0_controller.py tests/unit/test_pet_sequence_runner.py
python -m ruff check src/sjtuclaw/application/pet_track0.py tests/fakes/pet_animation_player.py tests/unit/test_pet_track0_controller.py
python -m mypy src/sjtuclaw/application/pet_track0.py tests/fakes/pet_animation_player.py tests/unit/test_pet_track0_controller.py
git add src/sjtuclaw/application/pet_track0.py tests/fakes/pet_animation_player.py tests/unit/test_pet_track0_controller.py
git commit -m "feat: add track zero playback controller"
```

---

### Task 6: Capability Gate and Exact Watchdog

**Files:**
- Modify: `src/sjtuclaw/application/pet_track0.py`
- Create: `tests/unit/test_pet_track0_watchdog.py`

**Interfaces:**
- Produces: `WatchdogPolicy.deadline(start, source_duration, speed)`, `sequencing_enabled(capabilities)`, `PetTrack0Controller.poll_watchdog()`.
- Consumes: injected `MonotonicClock`; no test sleeps.

- [ ] **Step 1: Write failing all-or-nothing capability tests**

```python
@pytest.mark.parametrize("missing", range(4))
def test_each_missing_capability_disables_production_sequencing(missing: int) -> None:
    values = [True, True, True, True]
    values[missing] = False
    capabilities = AnimationPlayerCapabilities(*values)
    assert not sequencing_enabled(capabilities)
```

- [ ] **Step 2: Write failing literal watchdog deadline tests**

```python
@pytest.mark.parametrize(
    ("source_duration", "speed", "expected"),
    [(0.4, 1.0, 10.65), (4.0, 2.0, 12.5), (40.0, 2.0, 31.0)],
)
def test_watchdog_deadline_uses_bounded_tolerance(
    source_duration: float,
    speed: float,
    expected: float,
) -> None:
    assert WatchdogPolicy().deadline(10.0, source_duration, speed) == pytest.approx(expected)
```

- [ ] **Step 3: Verify RED and implement capability/watchdog behavior**

Run: `python -m pytest -q tests/unit/test_pet_track0_watchdog.py`

Expected: missing watchdog APIs.

Use (d=d_s/v) and deadline `start + d + clamp(0.25*d, 0.25, 1.0)`. Reject non-positive speed. Arm one-shot deadlines only after successful play; arm loop-boundary deadlines only after graceful exit becomes pending; never guess missing duration.

- [ ] **Step 4: Add timeout containment tests and commit**

Use `FakeClock` to advance beyond the literal deadline. Assert `CALLBACK_TIMEOUT`, a clear attempt, runner reset, `DEGRADED`/`UNKNOWN`, and no fallback idle play.

```powershell
python -m pytest -q tests/unit/test_pet_track0_watchdog.py tests/unit/test_pet_track0_controller.py
python -m ruff check src/sjtuclaw/application/pet_track0.py tests/unit/test_pet_track0_watchdog.py
python -m mypy src/sjtuclaw/application/pet_track0.py tests/unit/test_pet_track0_watchdog.py
git add src/sjtuclaw/application/pet_track0.py tests/unit/test_pet_track0_watchdog.py
git commit -m "feat: add track zero capability watchdog"
```

---

### Task 7: Atomic Animation Engine Transactions and Mandatory Containment

**Files:**
- Modify: `src/sjtuclaw/application/pet_animation.py`
- Modify: `tests/unit/test_pet_animation.py`
- Create: `tests/unit/test_pet_animation_transactions.py`

**Interfaces:**
- Produces: `PetAnimationEvent`, `PetAnimationEngine.handle_event()`, optional `PetAnimationIntent.track0_action`.
- Consumes: state proposals, registry/controller preflight, and exact controller outcomes.

- [ ] **Step 1: Write the failing semantic-epoch transaction test**

```python
def test_action_request_copies_state_proposal_target_epoch() -> None:
    engine, controller, machine = transaction_engine(initial_epoch=17)
    outcome = engine.handle_event(PetAnimationEvent.start_reading(token=object()))
    assert outcome is ActionOutcome.ACCEPTED
    assert controller.requests[-1].semantic_epoch == 18
    assert machine.epoch == 18
```

- [ ] **Step 2: Write mandatory safety preflight-failure tests**

```python
@pytest.mark.parametrize(
    ("clear_fails", "health", "outcome"),
    [
        (False, PlaybackHealth.DEGRADED, ActionOutcome.PLAYBACK_DEGRADED),
        (True, PlaybackHealth.UNKNOWN, ActionOutcome.RENDERER_STATE_UNKNOWN),
    ],
)
def test_mandatory_fall_commits_then_contains_failed_preflight(
    clear_fails: bool,
    health: PlaybackHealth,
    outcome: ActionOutcome,
) -> None:
    engine = reading_engine_with_missing_drag_end(clear_fails=clear_fails)
    result = engine.handle_event(PetAnimationEvent.start_falling())
    assert result is outcome
    assert engine.motion.state.motion is PetMotionState.FALLING
    assert engine.motion.states.epoch == 2
    assert engine.track0.state.desired_action is None
    assert engine.track0.state.health is health
    assert engine.track0.runner.snapshot.active_sequence is None
    assert PetActionName.DRAG_END not in engine.player.played_actions
```

- [ ] **Step 3: Verify RED and implement the seven-step atomic protocol**

Run: `python -m pytest -q tests/unit/test_pet_animation_transactions.py`

Expected: missing `handle_event()` or event values.

Normal preflight rejection commits neither target state nor target epoch. Mandatory safety preflight rejection commits the proposal, invalidates/clears Track 0, resets the runner, sets desired `None`, and returns the fixed health outcome. The engine must copy `proposal.target_epoch` and must not calculate `epoch + 1`.

- [ ] **Step 4: Preserve existing request methods**

Route existing `request_walk()`, `request_thinking_animation()`, `request_reminder_animation()`, `start_dragging()`, `release_drag()`, `pause()`, `resume()`, and `begin_closing()` through transaction events only when production sequencing is enabled. With the placeholder player, retain existing semantic behavior and return `LEGACY_DIRECT`; do not create timers or synthetic completions.

- [ ] **Step 5: Add deterministic interleaving tests**

Cover old-completion/new-request orderings, queued completion during drag, duplicate completion around replacement, correct name with stale generation, correct generation with wrong binding, graceful exit versus higher priority replacement, repeated loop boundaries, and session-A release callback after session-B drag replacement. Assert both runner state and `assert_animation_compatible()` after every event.

- [ ] **Step 6: Run, refactor, and commit Task 7**

```powershell
python -m pytest -q tests/unit/test_pet_animation.py tests/unit/test_pet_animation_transactions.py tests/unit/test_pet_motion.py
python -m ruff check src/sjtuclaw/application/pet_animation.py tests/unit/test_pet_animation.py tests/unit/test_pet_animation_transactions.py
python -m mypy src/sjtuclaw/application/pet_animation.py tests/unit/test_pet_animation.py tests/unit/test_pet_animation_transactions.py
git add src/sjtuclaw/application/pet_animation.py tests/unit/test_pet_animation.py tests/unit/test_pet_animation_transactions.py
git commit -m "feat: coordinate atomic pet animation transactions"
```

---

### Task 8: Placeholder Adapter, Qt Boundary, and Agent Isolation

**Files:**
- Modify: `src/sjtuclaw/presentation/qt/pet_window.py`
- Modify: `tests/qt/test_pet_window.py`
- Modify: `tests/unit/test_pet_renderer_model.py`
- Create: `tests/unit/test_pet_action_isolation.py`

**Interfaces:**
- Produces: `PlaceholderAnimationPlayer` reporting all production capabilities as false and returning `LEGACY_DIRECT` through the existing renderer-neutral path.
- Consumes: content-free engine request methods; Qt only marshals future callback values and never passes renderer/runtime objects into the pure application modules.

- [ ] **Step 1: Write failing placeholder and import-isolation tests**

```python
def test_placeholder_never_starts_production_sequence() -> None:
    player = PlaceholderAnimationPlayer()
    assert player.capabilities == AnimationPlayerCapabilities(False, False, False, False)
    assert player.request(PetActionName.IDLE) is ActionOutcome.LEGACY_DIRECT
    assert player.play_call_count == 0


def test_sequencing_modules_do_not_import_agent_or_provider_layers() -> None:
    forbidden = {"agent_loop", "runtime_bridge", "provider", "secrets", "openai"}
    for path in (ACTION_SEQUENCE_MODULE, TRACK0_MODULE):
        imports = imported_module_names(path)
        assert not any(any(part in name for part in forbidden) for name in imports)
```

- [ ] **Step 2: Verify RED and wire only the placeholder boundary**

Run: `python -m pytest -q tests/unit/test_pet_action_isolation.py tests/unit/test_pet_renderer_model.py`

Expected: missing placeholder adapter behavior.

Do not add a Spine adapter. Do not add `QTimer.singleShot`, guessed durations, network access, Provider activation, Agent callbacks, or content parameters.

- [ ] **Step 3: Add Qt lifecycle regressions**

Assert pet startup neither activates a Provider nor reads a `SecretStore`; Agent-window close still hides without stopping the pet runtime; safe exit waits for `RuntimeThread`; animation failure does not close, restart, or wake the Agent; drag/release/pause/resume behavior remains unchanged.

- [ ] **Step 4: Run targeted and full verification**

```powershell
python -m pytest -q tests/unit/test_pet_action_sequence_catalog.py tests/unit/test_pet_state_animation_compatibility.py tests/unit/test_pet_action_arbiter.py tests/unit/test_pet_sequence_runner.py tests/unit/test_pet_track0_controller.py tests/unit/test_pet_track0_watchdog.py tests/unit/test_pet_animation_transactions.py tests/unit/test_pet_animation.py tests/unit/test_pet_motion.py tests/unit/test_pet_renderer_model.py tests/unit/test_pet_action_isolation.py
python -m pytest -q tests/qt/test_pet_window.py
python -m pytest -q
python -m ruff check src tests
python -m mypy src tests
```

- [ ] **Step 5: Commit Task 8**

```powershell
git add src/sjtuclaw/presentation/qt/pet_window.py tests/qt/test_pet_window.py tests/unit/test_pet_renderer_model.py tests/unit/test_pet_action_isolation.py
git commit -m "feat: integrate capability gated pet actions"
```

---

### Task 9: Provenance, Completion Audit, and Handoff

**Files:**
- Modify: `src/sjtuclaw/application/pet_action_sequence.py`
- Modify: `src/sjtuclaw/application/pet_track0.py`
- Create: `docs/arkpets_action_runtime.md`

**Interfaces:**
- Produces: SPDX/provenance notices and an operator-facing boundary document.
- Consumes: frozen design and passing implementation evidence.

- [ ] **Step 1: Add provenance without vendoring Java**

Add a concise module notice naming ArkPets, Harry Huang, GPL-3.0, the four consulted Java paths, the Python rewrite, and the omitted asset/mobility/behavior-matrix scope. Do not copy Java source or comments.

- [ ] **Step 2: Document actual capability boundary**

Record that the placeholder remains `LEGACY_DIRECT`, production sequencing is disabled without all four capabilities, Track 1/2 composition is not performed, and Spine Runtime/export/callback integration remains unimplemented.

- [ ] **Step 3: Run fresh complete verification and inspect the diff**

```powershell
python -m pytest -q
python -m ruff check src tests
python -m mypy src tests
git diff --check
git status --short
```

Review each frozen invariant and name the test that protects it. Confirm no Agent, Provider, credential, network, Spine asset, Runtime export, Mesh, Atlas, PNG, audio, or ArkPets art file was changed or added.

- [ ] **Step 4: Commit documentation**

```powershell
git add src/sjtuclaw/application/pet_action_sequence.py src/sjtuclaw/application/pet_track0.py docs/arkpets_action_runtime.md
git commit -m "docs: record ArkPets action runtime provenance"
```

The GPL migration is not performed by this plan. Execute `docs/superpowers/plans/2026-08-07-sjtuclaw-gpl-migration-audit.md` separately; root license and package metadata may change only after that plan records an overall `PASS`.
