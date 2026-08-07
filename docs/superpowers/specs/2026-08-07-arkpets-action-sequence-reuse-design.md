# ArkPets Action Sequence Reuse Design

**Date:** 2026-08-07  
**Status:** Closed and frozen for TDD implementation
**Scope:** Conditional GPL-3.0-only migration and code-level reuse of selected
ArkPets animation-sequencing mechanisms

## 1. Objective

Adapt selected GPL-3.0 ArkPets animation-sequencing mechanisms into
SJTUClaw's existing Python desktop-pet architecture without changing the
locally deployed Agent runtime.

The selected reuse scope is limited to the ideas and code structure embodied
by ArkPets `AnimData`, `AnimComposer`, animation-step chaining,
completion-driven advancement, and the `Begin -> Loop -> End` lifecycle. The
implementation will be rewritten in Python and integrated as independent,
small application-layer components.

This work does not reduce or redesign the approved list of 25 logical Spine
animations. Spine production remains paused while this mechanism and its
licensing boundary are prepared.

## 2. Decisions and Non-goals

The following decisions remain approved:

1. Use an independent action-sequence module rather than embedding sequencing
   in the renderer or state machine.
2. Intend to migrate the distributable SJTUClaw source code to
   `GPL-3.0-only`, but perform that migration only after the license and
   provenance audit in section 12 returns `PASS`.
3. Attribute the adapted implementation to ArkPets and Harry Huang.
4. Do not copy ArkPets character images, animation frames, Spine projects,
   audio, pet packs, or other art assets.
5. Do not port the ArkPets stochastic behavior matrix or broad behavior
   subsystem in this change.
6. Do not port ArkPets mobility or root-motion ownership. Window movement,
   dragging, gravity, collision, and landing remain owned by
   `PetMotionModel`.
7. Do not alter the local Agent's prompts, Provider activation, credentials,
   sessions, networking, window lifecycle, or shutdown behavior.
8. Do not modify unrelated in-progress OpenGL Mesh worktree changes.
9. Do not claim that Spine Runtime playback, Track mixing, or runtime
   completion callbacks exist before a separately approved integration.

## 3. Authority and Core Invariants

SJTUClaw retains one authority for each kind of state:

- `PetLayeredStateMachine` in `pet_state.py` owns semantic pet state and
  validates lifecycle, exclusive motion, and behavior transitions.
- `PetMotionModel` in `pet_motion.py` owns window position, dragging, gravity,
  collision, landing, and workspace constraints.
- `PetTrack0Controller` owns Track 0 playback side effects and coordinates
  arbitration, sequence progress, and the animation player.
- `AnimationPlayer` owns only renderer-facing `play` and `clear` operations.
- `PetAnimationEngine` remains the single application-level entry point that
  coordinates a state transition with its playback directive.

The following invariants are mandatory:

1. A motion model never starts or cancels an animation directly.
2. A state machine never calls a renderer directly.
3. A player callback never mutates `PetState` directly.
4. Every accepted Track 0 request is associated with the semantic transition
   that authorized it and with a monotonically increasing playback
   `generation`.
5. A callback may advance a sequence only when its generation, logical action,
   physical animation name, player token, and expected step all match the
   active playback.
6. After every handled event, semantic state and active logical animation must
   satisfy the executable compatibility table in section 6. For example,
   `dragging` may be paired only with `drag_start` or `drag_loop`, never
   `sleep_loop`.
7. If playback fails, semantic state remains authoritative. Playback is
   cleared and marked degraded or unknown; Agent state is never changed as
   recovery.
8. All mutable state, arbitration, and callback handling occurs on the Qt GUI
   thread. A renderer callback arriving on another thread is queued to that
   thread before it is inspected.

## 4. Component Architecture

The original broad `PetActionComposer` is replaced by narrow components:

```text
PetActionSequence       AnimationRegistry
        |                       |
        v                       v
PetSequenceRunner <- PetActionArbiter
        |                       |
        +----> PetTrack0Controller ----> AnimationPlayer
                         ^
                         |
                 PetAnimationEngine
                         ^
                         |
       PetLayeredStateMachine + PetMotionModel
```

### 4.1 `PetActionSequence`

The only sequencing truth. It contains an ordered tuple of `PetActionStep`
values plus sequence-level loop and terminal metadata. A step never contains
a `next` pointer.

```python
@dataclass(frozen=True, slots=True)
class PetActionStep:
    action: PetActionName
    loop: bool
    speed: float = 1.0
    mix_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class PetActionSequence:
    steps: tuple[PetActionStep, ...]
    loop_index: int | None = None
    loop_exit_index: int | None = None
    terminal: SequenceTerminal = SequenceTerminal.COMPLETE
```

When no loop is active, the runner advances by `index + 1`. While a loop is
active, a normal boundary preserves `loop_index` and the existing player
epoch; it does not request the same step again. After a pending graceful exit,
the next matching boundary jumps to `loop_exit_index` and causes exactly one
new player command for that exit step. Validation rejects an out-of-range
index, a loop index pointing to a non-looping step, an exit index without a
loop, or any second source of next-step information.

### 4.2 `PetSequenceRunner`

Owns only execution progress:

- active immutable sequence;
- current step index;
- pending graceful exit;
- active playback generation and expected player token;
- matching completion advancement;
- runner-local reset state.

It does not decide whether a request outranks another request and does not call
the renderer.

### 4.3 `PetActionArbiter`

Owns only request acceptance:

- compare the incoming and active `ActionRequest` policies using the exact
  algorithm in section 7;
- reject duplicate or lower-priority requests;
- apply the explicit same-class replacement matrix;
- select the permitted cancellation mode for an accepted replacement.

Interruption metadata belongs to the request, not to individual steps:

```python
@dataclass(frozen=True, slots=True)
class ActionRequest:
    sequence_name: SequenceName
    interruption_class: InterruptClass
    protected: bool
    request_token: object
    semantic_epoch: int
    input_session_token: object | None = None
```

The interruption class remains stable for the lifetime of that request. A
sequence cannot silently change priority when it advances from `sleep_end` to
`return_idle`. `request_token` uniquely identifies one logical request,
`semantic_epoch` is the proposal's state-machine-issued target epoch, and
`input_session_token` is stable for one direct manipulation gesture. These
identities are values supplied by the event/state boundary, never inferred
from wall-clock timing or calculated inside `PetAnimationEngine`.

The previous name `PetActionComposer` may be retained only as a compatibility
alias during migration. It must not own sequencing, transition, callbacks,
fallback, blending, speed, randomness, emotion, or renderer state.

### 4.4 `PetTrack0Controller`

A thin transaction coordinator. It combines the arbiter's decision with the
runner's directive, resolves logical names through the registry, increments
the generation, and invokes the player. It contains no business-state rules.

### 4.5 `AnimationPlayer`

A narrow protocol rather than a Spine-specific implementation:

```python
class AnimationPlayer(Protocol):
    @property
    def capabilities(self) -> AnimationPlayerCapabilities: ...
    def play(self, request: PlaybackRequest) -> PlaybackToken: ...
    def clear(self, track: int, mix_seconds: float) -> None: ...
```

Capabilities are explicit:

```python
@dataclass(frozen=True, slots=True)
class AnimationPlayerCapabilities:
    completion_callbacks: bool
    loop_boundary_callbacks: bool
    duration_metadata: bool
    liveness_reporting: bool
```

Completion-driven production sequencing is enabled only when all four
capabilities are true. The adapters are deliberately different:

- `FakeAnimationPlayer` reports all capabilities and drives deterministic
  runner/controller tests.
- `PlaceholderAnimationPlayer` reports no completion or loop-boundary
  callbacks and stays on the existing legacy direct/symbolic render path. It
  does not start production sequences.
- a future `SpineAnimationPlayer` may enable production sequencing only after
  all four capabilities have been verified.

The placeholder must never synthesize completion with `QTimer`,
`singleShot`, or a guessed duration merely to advance a sequence.

### 4.6 Dependency and Agent Isolation

The new dependency direction is:

```text
pet_action_sequence.py
        |
        v
pet_animation.py
        |
        v
pet_window.py -> AnimationPlayer adapter
```

The existing Agent path remains independent:

```text
MainWindow -> QtRuntimeBridge -> AgentLoop -> Provider
```

The sequencing module must be pure Python and framework-independent. It must
not import or receive `AgentLoop`, `QtRuntimeBridge`, Provider, `SecretStore`,
prompts, continuations, sessions, credentials, response text, or network
clients. Existing content-free entry points such as
`request_thinking_animation()` and `request_reminder_animation()` remain
content-free.

## 5. Logical Names and `AnimationRegistry`

`PetActionName` remains the exact, case-sensitive logical catalog used by
business logic:

```text
idle
breathing
blink
walk_left
walk_right
run_left
run_right
sit_down
sit_idle
sleep_start
sleep_loop
sleep_end
wave
happy
think
read
type
remind
confused
angry
drag_start
drag_loop
drag_end
landing
return_idle
```

Business logic must never compare a Spine resource name directly.
`AnimationRegistry` maps each logical name to an immutable binding:

```text
PetActionName.SLEEP_LOOP -> "sleep_loop"
```

If a later skeleton uses another case-sensitive name, only the registry
changes:

```text
PetActionName.SLEEP_LOOP -> "SleepLoop_v2"
```

Registry validation is a startup/preflight boundary and must reject:

- a missing logical binding;
- an empty physical name;
- duplicate physical bindings unless an explicitly reviewed alias group is
  introduced later;
- a case mismatch against the names reported by the loaded skeleton;
- a Track 1 or Track 2 action assigned to a Track 0 sequence;
- unavailable duration/capability metadata required by failure recovery.

The default registry is an identity mapping for the current 25 names. This
preserves the strict resource audit while removing resource spelling from
state and sequencing code.

## 6. State-to-Animation Transaction Protocol

### 6.1 Minimal semantic-state extension

The current state model can distinguish idle, walking, dragging, falling,
landing, thinking, and reminding, but cannot represent sitting, sleeping,
running, reading, typing, or the requested performances. Treating all of those
as `motion=IDLE` would make the state machine cease to be semantic authority.

The implementation therefore makes the smallest explicit extension while
retaining `PetLayeredStateMachine`, `PetMotionModel`, and
`PetAnimationEngine`:

```python
class PetMotionState(Enum):
    IDLE = "idle"
    WALKING_LEFT = "walking_left"
    WALKING_RIGHT = "walking_right"
    RUNNING_LEFT = "running_left"
    RUNNING_RIGHT = "running_right"
    DRAGGING = "dragging"
    FALLING = "falling"
    LANDING = "landing"


class PetActivityState(Enum):
    NONE = "none"
    SITTING = "sitting"
    SLEEPING = "sleeping"
    WAVING = "waving"
    HAPPY = "happy"
    THINKING = "thinking"
    READING = "reading"
    TYPING = "typing"
    REMINDING = "reminding"
    CONFUSED = "confused"
    ANGRY = "angry"
```

`PetLayeredState` gains one `activity` field. Activity is exclusive, is
permitted only while lifecycle is active and motion is idle, and is distinct
from Track 1/2 overlays. Existing public thinking/reminding request methods are
preserved while their semantic storage migrates from `PetBehaviorState` to
`PetActivityState`. Existing behavior properties may expose a temporary
compatibility projection so current callers and tests are migrated without an
unrelated API break.

`PetBehaviorState` continues to describe overlay/derived visual facts such as
breathing and blinking. `DRAG_STRUGGLE` may remain as a compatibility-derived
view of `motion=DRAGGING`; it is not a second Track 0 authority.

### 6.2 Executable compatibility table

The following is the complete Track 0 table for healthy,
completion-driven playback. `ANY` is used only for the two inactive lifecycle
rows. All omitted combinations are invalid and must be rejected by
`validate_layered_state()` before animation arbitration.

| Lifecycle | Motion | Activity | Allowed Track 0 logical actions |
| --- | --- | --- | --- |
| `PAUSED` | `ANY` | `ANY` | none; Track 0 must be cleared |
| `CLOSING` | `ANY` | `ANY` | none; Track 0 must be cleared |
| `ACTIVE` | `IDLE` | `NONE` | `idle`, `return_idle` |
| `ACTIVE` | `WALKING_LEFT` | `NONE` | `walk_left` |
| `ACTIVE` | `WALKING_RIGHT` | `NONE` | `walk_right` |
| `ACTIVE` | `RUNNING_LEFT` | `NONE` | `run_left` |
| `ACTIVE` | `RUNNING_RIGHT` | `NONE` | `run_right` |
| `ACTIVE` | `DRAGGING` | `NONE` | `drag_start`, `drag_loop` |
| `ACTIVE` | `FALLING` | `NONE` | `drag_end` |
| `ACTIVE` | `LANDING` | `NONE` | `landing` |
| `ACTIVE` | `IDLE` | `SITTING` | `sit_down`, `sit_idle` |
| `ACTIVE` | `IDLE` | `SLEEPING` | `sleep_start`, `sleep_loop`, `sleep_end` |
| `ACTIVE` | `IDLE` | `WAVING` | `wave` |
| `ACTIVE` | `IDLE` | `HAPPY` | `happy` |
| `ACTIVE` | `IDLE` | `THINKING` | `think` |
| `ACTIVE` | `IDLE` | `READING` | `read` |
| `ACTIVE` | `IDLE` | `TYPING` | `type` |
| `ACTIVE` | `IDLE` | `REMINDING` | `remind` |
| `ACTIVE` | `IDLE` | `CONFUSED` | `confused` |
| `ACTIVE` | `IDLE` | `ANGRY` | `angry` |

This table is implemented once, not duplicated in conditionals:

```python
SemanticTrack0Key = tuple[
    PetLifecycleState,
    PetMotionState,
    PetActivityState,
]

STATE_ACTION_COMPATIBILITY: Mapping[
    SemanticTrack0Key,
    frozenset[PetActionName],
] = MappingProxyType({...})

def assert_animation_compatible(
    state: PetLayeredState,
    action: PetActionName | None,
    health: PlaybackHealth,
) -> None: ...
```

For `HEALTHY` production playback, an active lifecycle requires the desired
Track 0 action to be in the mapped set, and an inactive lifecycle requires it
to be `None`. For `DEGRADED` or `UNKNOWN` playback, desired action `None` is
permitted for any otherwise valid semantic state; the program must not claim
that an unconfirmed renderer action is compatible.

Before playing `return_idle`, the same transaction first commits the semantic
destination: activity becomes `NONE`, or landing becomes motion `IDLE`. This
is why `return_idle` belongs only to the `ACTIVE/IDLE/NONE` row. During
`FALLING`, completed `drag_end` may hold its final pose until the physical
landing event replaces it; animation completion never invents a landing state.

Track 1/2 use a separate `OVERLAY_COMPATIBILITY` mapping that initially
preserves existing breathing/blinking state validation. Expanding an overlay
to a new activity requires the later Spine property-conflict audit; it is not
implicitly allowed by this Track 0 table.

### 6.3 Atomic event protocol

`PetAnimationEngine.handle_event()` is the sole mutation entry point for an
event that may affect both semantic state and Track 0 playback.

The state machine owns epoch allocation and returns it as part of the proposal:

```python
@dataclass(frozen=True, slots=True)
class ProposedStateTransition:
    source_state: PetLayeredState
    target_state: PetLayeredState
    source_epoch: int
    target_epoch: int
    mandatory_for_safety: bool = False
```

For example, a machine currently at epoch 17 proposes
`source_epoch=17, target_epoch=18`. The derived
`ActionRequest.semantic_epoch` is exactly `proposal.target_epoch`, so preflight
evaluates the identity that would become authoritative. A successful commit
atomically verifies the current source epoch and installs the target state at
exactly epoch 18. A rejected normal proposal never makes epoch 18 committed.
`PetAnimationEngine` must not compute `current_epoch + 1`, reserve an epoch, or
mutate the state machine's counter itself.

For each event, in one GUI-thread turn:

1. Ask `PetLayeredStateMachine` to validate and produce a proposed semantic
   transition, including source/target epochs, without exposing a renderer
   object.
2. Derive the required logical action request from that proposal and copy
   `proposal.target_epoch` into `ActionRequest.semantic_epoch`.
3. Ask `AnimationRegistry` and `PetTrack0Controller` to preflight the binding,
   interruption class, cancellation mode, and sequence.
4. If preflight rejects, a normal transition leaves both layers unchanged. An
   independently mandatory safety transition takes the fixed containment path:

   1. commit the mandatory proposed semantic state and its target epoch;
   2. invalidate the old playback generation and attempt an immediate Track 0
      `clear` (the clear attempt consumes its own invalidation generation);
   3. reset the runner and set `desired_action=None`;
   4. if clear succeeds, set `confirmed_epoch=None`, health `DEGRADED`, and
      return `PLAYBACK_DEGRADED`;
   5. if clear fails, treat confirmed playback as unknowable, set health
      `UNKNOWN`, and return `RENDERER_STATE_UNKNOWN`.

   The rejected replacement is never played. For example, if `READING/read`
   receives a mandatory falling transition but the `FALL_RECOVERY/drag_end`
   binding fails preflight, semantic state still becomes `FALLING` while old
   `read` playback is contained by this clear path. The method never returns
   with healthy `FALLING/read`.
5. If accepted, commit the semantic transition at `proposal.target_epoch` and
   execute the controller's returned `clear`/`play` directive. Each physical
   command advances the controller-owned playback generation counter exactly
   as specified in section 8; it does not advance the semantic state epoch.
6. If `AnimationPlayer` raises or rejects the directive, contain the error,
   apply the playback-health transition in section 10, and reset the runner.
   Do not roll back a committed safety or user-interaction state merely to
   preserve an old animation.
7. Assert the state/action compatibility invariant before returning a fixed
   result code.

Completion callbacks carry at least:

```text
generation
logical_action
physical_animation_name
playback_token
```

Callbacks are queued to the GUI thread. Any field mismatch makes the callback
stale and side-effect free.

Example: if `drag_end` is playing and the user begins a new drag,
the new input-session token activates the equal-class `USER_INTERACTION`
replacement rule. The same transaction commits `dragging`, invalidates and
clears the old generation, then plays `drag_start`. A delayed `drag_end`
completion is ignored, so the system cannot settle into `idle` while
displaying `drag_loop`.

## 7. Interruption and Cancellation Model

### 7.1 Interruption classes

The term "ordinary interruption" is removed. Every Track 0 request has an
explicit class and total order:

| Rank | Class | Examples |
| ---: | --- | --- |
| 500 | `SYSTEM_SHUTDOWN` | final close and renderer teardown |
| 400 | `MOTION_SAFETY` | fall, collision recovery, workspace recovery |
| 300 | `USER_INTERACTION` | drag start, direct click interaction |
| 200 | `STRICT_ACTION` | protected `wave`, `happy`, `confused`, `angry` |
| 100 | `NORMAL_ACTION` | think, read, type, remind, ordinary transitions |
| 0 | `IDLE` | idle maintenance |

The arbiter uses this deterministic algorithm in order:

1. With no active request, accept the incoming request.
2. `SYSTEM_SHUTDOWN` always wins. If shutdown is already active, return
   `ACCEPTED` with no controller directive; otherwise accept it with
   `IMMEDIATE_CLEAR`.
3. If `incoming.rank > active.rank`, accept with the cancellation mode assigned
   to the incoming event.
4. If `incoming.rank < active.rank`, return `REJECTED_PRIORITY` regardless of
   whether the active request is protected.
5. If ranks are equal and the incoming request is the runner-authorized
   continuation of the active sequence, accept without replacement.
6. If ranks are equal and the request is the same sequence and request token,
   return `REJECTED_DUPLICATE`.
7. Otherwise apply the following exhaustive same-class matrix.

| Equal class | Replacement rule |
| --- | --- |
| `SYSTEM_SHUTDOWN` | `ACCEPTED` with no controller directive; do not issue a second clear |
| `MOTION_SAFETY` | replace only when the proposed semantic state epoch differs or the active safety action is stale/incompatible; otherwise duplicate |
| `USER_INTERACTION` | same input session plus same sequence is `REJECTED_DUPLICATE`; same input session plus the approved `DRAG_HOLD -> DRAG_RELEASE` phase transition is `REPLACE`; a different input session is `REPLACE`; every other same-session transition is rejected |
| `STRICT_ACTION` | reject; validation requires `protected=True` |
| `NORMAL_ACTION` | replace a different sequence only when `active.protected=False`; otherwise reject |
| `IDLE` | reject as duplicate; idle never replaces another equal idle request |

`STRICT_ACTION` requests must be protected, while other classes default to
unprotected and may be protected only by a separately documented catalog rule.
Consequently, a strict `wave` rejects `happy` and normal actions, but never
blocks shutdown, motion recovery, or a new direct drag.

For this matrix, a safety action is `stale/incompatible` exactly when playback
health is not `HEALTHY`, the confirmed epoch does not match the active request,
or `STATE_ACTION_COMPATIBILITY` rejects it for the proposed state. No heuristic
age or elapsed-time comparison participates in arbitration. Every matrix result
contains both an outcome and either one exact cancellation mode or an explicit
no-controller-directive value.

`DRAG_HOLD` and `DRAG_RELEASE` carry the same input-session token for one
press-drag-release gesture. Release is the sole approved same-session phase
replacement. A later press creates a new token, so a new `DRAG_HOLD` replaces
an older session's still-playing `DRAG_RELEASE`. `MOTION_SAFETY` remains
reserved for actual fall recovery, collision/workspace recovery, and landing;
it does not classify the user-release animation.

### 7.2 Cancellation reasons

`CancelReason` is separate from priority:

```text
USER_INTERRUPT
SYSTEM_SHUTDOWN
MOTION_OVERRIDE
PAUSE
RENDERER_FAILURE
CALLBACK_TIMEOUT
```

### 7.3 Cancellation modes

```text
GRACEFUL_EXIT
IMMEDIATE_CLEAR
REPLACE
```

Their semantics are exact:

- `GRACEFUL_EXIT`: keep the active loop until its next matching completion
  boundary, then advance to its declared exit step.
- `IMMEDIATE_CLEAR`: invalidate the generation, call
  `AnimationPlayer.clear(track=0, ...)`, empty the runner, and do not emit
  `end`, `return_idle`, or `idle` automatically.
- `REPLACE`: invalidate and clear the old generation, start the approved
  replacement in the same controller transaction, and make late callbacks
  stale.

The public operations are distinct:

- `PetTrack0Controller.cancel(reason, mode, replacement=None)` applies policy
  and returns a fixed outcome.
- `PetTrack0Controller.clear(reason)` is an unconditional immediate renderer
  clear reserved for shutdown, pause, and failure containment.
- `PetSequenceRunner.reset()` is internal state cleanup only and has no
  renderer side effect.

Neither `clear()` nor `reset()` automatically plays `idle`. A healthy normal
transition reaches idle only through the sequence catalog. Failure recovery
uses the health model in section 10 and does not create a second speculative
player command.

The required mapping is:

| Situation | Mode | Follow-up |
| --- | --- | --- |
| shutdown | `IMMEDIATE_CLEAR` | no idle |
| pause | `IMMEDIATE_CLEAR` | no idle until resume |
| new drag | `REPLACE` | `drag_start` |
| fall/collision recovery | `REPLACE` | state-derived safety action |
| normal request to leave a loop | `GRACEFUL_EXIT` | declared end chain |
| renderer failure or callback timeout | `IMMEDIATE_CLEAR` | reset runner and mark degraded/unknown; no automatic idle |

## 8. Sequence Semantics

### 8.1 One sequencing truth

`PetActionStep` contains only logical playback data: action, loop flag, speed,
and optional mix suggestion. It contains no next pointer, interruption policy,
physical resource name, renderer, callback, state machine, position, Agent
content, or mutable queue.

The ordered `PetActionSequence.steps` tuple is the only source of advancement.
The runner uses its index and the sequence-level `loop_index` /
`loop_exit_index`. `then()` creates a new ordered tuple; it does not link
nodes. Catalog validation rejects any model or serialized input that attempts
to provide a per-step next relation.

At a boundary where the next step requires another semantic state, the runner
only proposes the next logical action. `PetAnimationEngine` performs the
section 6 state transaction before the controller plays it. For example,
`wave` completion proposes `return_idle`; the engine first changes activity
from `WAVING` to `NONE`, preflights the compatibility table, and then plays
`return_idle`.

### 8.2 Complete sequence catalog

`SEQUENCE_CATALOG: Mapping[SequenceName, SequenceCatalogEntry]` is the single
source for all standard sequences and request policies. No request method may
construct an ad-hoc chain in `if`/`else` logic.

Notation: `*` marks a loop step; `exit=N` is the index selected at the next
matching loop boundary after graceful exit; `hold` keeps the completed final
pose until an external state event replaces it. Reaching terminal `idle`
starts the baseline `IDLE` request with class `IDLE`, so an old strict or normal
request never retains priority while idle.

| Sequence | Track | Ordered steps | Loop/exit/terminal | Request policy |
| --- | ---: | --- | --- | --- |
| `IDLE` | 0 | `idle*` | loop 0; hold | `IDLE`, unprotected |
| `BREATHING` | 1 | `breathing*` | loop 0; hold | overlay scheduler |
| `BLINK` | 2 | `blink` | complete | overlay scheduler |
| `WALK_LEFT` | 0 | `walk_left* -> return_idle` | loop 0; exit=1; terminal `IDLE` | `NORMAL_ACTION`, unprotected |
| `WALK_RIGHT` | 0 | `walk_right* -> return_idle` | loop 0; exit=1; terminal `IDLE` | `NORMAL_ACTION`, unprotected |
| `RUN_LEFT` | 0 | `run_left* -> return_idle` | loop 0; exit=1; terminal `IDLE` | `NORMAL_ACTION`, unprotected |
| `RUN_RIGHT` | 0 | `run_right* -> return_idle` | loop 0; exit=1; terminal `IDLE` | `NORMAL_ACTION`, unprotected |
| `SIT` | 0 | `sit_down -> sit_idle* -> return_idle` | loop 1; exit=2; terminal `IDLE` | `NORMAL_ACTION`, unprotected |
| `SLEEP` | 0 | `sleep_start -> sleep_loop* -> sleep_end -> return_idle` | loop 1; exit=2; terminal `IDLE` | `NORMAL_ACTION`, unprotected |
| `WAVE` | 0 | `wave -> return_idle` | terminal `IDLE` | `STRICT_ACTION`, protected |
| `HAPPY` | 0 | `happy -> return_idle` | terminal `IDLE` | `STRICT_ACTION`, protected |
| `THINK` | 0 | `think -> return_idle` | terminal `IDLE` | `NORMAL_ACTION`, unprotected |
| `READ` | 0 | `read* -> return_idle` | loop 0; exit=1; terminal `IDLE` | `NORMAL_ACTION`, unprotected |
| `TYPE` | 0 | `type* -> return_idle` | loop 0; exit=1; terminal `IDLE` | `NORMAL_ACTION`, unprotected |
| `REMIND` | 0 | `remind -> return_idle` | terminal `IDLE` | `NORMAL_ACTION`, unprotected |
| `CONFUSED` | 0 | `confused -> return_idle` | terminal `IDLE` | `STRICT_ACTION`, protected |
| `ANGRY` | 0 | `angry -> return_idle` | terminal `IDLE` | `STRICT_ACTION`, protected |
| `DRAG_HOLD` | 0 | `drag_start -> drag_loop*` | loop 1; replace-only; hold | `USER_INTERACTION`, unprotected |
| `DRAG_RELEASE` | 0 | `drag_end` | complete then hold until physical landing | `USER_INTERACTION`, unprotected |
| `FALL_RECOVERY` | 0 | `drag_end` | complete then hold until physical landing | `MOTION_SAFETY`, unprotected |
| `LANDING` | 0 | `landing -> return_idle` | terminal `IDLE` | `MOTION_SAFETY`, unprotected |

The drag lifecycle is deliberately state-gated rather than a blind playback
chain:

```text
DRAG_HOLD
  drag_start -> drag_loop
       |
       | user release commits FALLING
       v
DRAG_RELEASE
  drag_end (completed pose may hold)
       |
       | PetMotionModel reports physical landing
       v
LANDING
  landing -> return_idle -> IDLE
```

Animation completion cannot invent the physical landing event. Catalog
validation proves that every one of the 25 `PetActionName` values occurs in at
least one entry, that Track 1/2 names never occur on Track 0, and that every
Track 0 action is allowed by at least one compatibility-table row.

`DRAG_RELEASE` is emitted only for the release phase of a direct manipulation
session. An independently detected fall uses `FALL_RECOVERY`; collision or
workspace recovery selects the compatible safety sequence for its proposed
motion state. Thus identical logical `drag_end` playback may be reached through
different sequence-level policies without moving interruption metadata onto
the step.

### 8.3 Advancement rules

1. A one-shot advances only on a matching completion event.
2. A loop never exits because of a guessed normal-playback timer.
3. A loop-boundary callback with no pending graceful exit is observational:
   it issues no player command, does not advance generation, preserves the
   current playback token and confirmed epoch, and leaves the current step
   index unchanged.
4. A graceful exit records a pending exit and advances at the next matching
   loop-boundary callback.
5. A replace-only loop such as `DRAG_HOLD` rejects graceful exit and requires
   an accepted replacement request.
6. A duplicate completion advances at most once.
7. A stale callback is ignored even when its action name matches.
8. A missing callback is handled only by the failure policy in section 10.
9. An invalid sequence is rejected before any state or player mutation.

### 8.4 Generation means one physical playback epoch

`generation` identifies exactly one concrete Track 0 player command epoch,
not a whole sequence. The controller owns a monotonically increasing Python
integer counter.

- Every `play` attempt allocates a fresh generation before invoking the
  player, including a normal step advance and an explicit post-recovery play.
- Every `clear` attempt allocates a fresh invalidation generation before
  invoking the player, even if clear later fails.
- `replace` therefore invalidates/clears the old epoch and allocates another
  generation for the replacement play.
- Runner `reset()` does not allocate a generation because it has no player
  side effect; it retains no active generation afterward.

Example:

```text
play sleep_start -> generation 10
complete          -> matches generation 10
play sleep_loop  -> generation 11
loop boundary     -> matches generation 11; no player command
loop boundary     -> matches generation 11; no player command
graceful exit     -> pending; generation and token unchanged
loop boundary     -> matches generation 11 and advances once
play sleep_end   -> generation 12
```

Callbacks carry generation, logical action, physical name, and playback token.
All four must match the current confirmed epoch. A callback from any earlier
epoch is stale and side-effect free.

## 9. Track Ownership

- Track 0 contains full-body states, transitions, and performances and is the
  only track managed by `PetTrack0Controller`.
- Track 1 contains only logical `breathing`.
- Track 2 contains only logical `blink`.

`breathing` and `blink` remain members of the 25-name logical catalog but
cannot be inserted into a Track 0 sequence. Their existing local overlay
scheduling is preserved.

The design records a property-conflict matrix for future Spine integration.
An overlay may be enabled only if its keyed properties do not conflict with
the active Track 0 expression or transition. This change defines the boundary
but does not claim actual runtime Track composition.

## 10. Failure Recovery and Diagnostics

### 10.1 Desired intent, confirmed playback, and health

The controller never treats a command it attempted as renderer truth. It keeps
three distinct facts:

```python
class PlaybackHealth(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Track0PlaybackState:
    desired_action: PetActionName | None
    confirmed_epoch: ConfirmedPlaybackEpoch | None
    health: PlaybackHealth
```

- `desired_action` is the application intent.
- `confirmed_epoch` exists only after `play()` returns a token for the current
  generation, or is `None` after a confirmed successful clear.
- `UNKNOWN` means the adapter failed to establish what remains visible. The
  application must not relabel the renderer as idle or cleared.

State transitions are exact:

1. Successful `play`: desired action and confirmed epoch match; health is
   `HEALTHY`.
2. Failed `play`, then successful containment `clear`: runner resets, desired
   and confirmed playback become `None`, health becomes `DEGRADED`.
3. Failed `play`, then failed containment `clear`: runner resets, desired
   becomes `None`, confirmed playback is unknowable, health becomes `UNKNOWN`.
4. Failed normal `clear`: runner resets, desired becomes `None`, health becomes
   `UNKNOWN` regardless of the previously confirmed epoch.
5. A callback timeout follows the same containment path as failed `play`.
6. A mandatory safety transition whose replacement fails preflight follows the
   section 6.3 containment path: the semantic transition remains committed,
   desired playback is `None`, and clear success/failure yields `DEGRADED` or
   `UNKNOWN` respectively.

There is no automatic `FALLBACK_IDLE` player command. A second speculative
play could fail again and would violate the semantic compatibility table for
states such as dragging. The semantic state is retained. The existing legacy
placeholder may continue to derive a renderer-neutral safe visual through
`action_request_for_frame(state)`; that is not reported as confirmed Spine
Track 0 playback.

Recovery from `DEGRADED` or `UNKNOWN` requires an explicit adapter re-probe or
renderer reinitialization followed by capability validation and a new
state-derived request. It is not hidden inside `clear()` or `reset()`.

### 10.2 Exact watchdog policy

Normal advancement remains completion-driven. The watchdog only detects a
failed callback/player path and is available only when production sequencing
passed the capability gate.

```python
@dataclass(frozen=True, slots=True)
class WatchdogPolicy:
    tolerance_ratio: float = 0.25
    minimum_tolerance_seconds: float = 0.25
    maximum_tolerance_seconds: float = 1.0
```

Let (d_s) be the source duration reported by the registry/player and (v)
be the strictly positive playback speed. The effective duration is

\[
d = \frac{d_s}{v}.
\]

With \(\alpha=0.25\), \(t_{\min}=0.25\) seconds, and
\(t_{\max}=1.0\) second, the deadline is

\[
t_{\text{deadline}}
= t_{\text{start}} + d
+ \operatorname{clamp}(\alpha d, t_{\min}, t_{\max}).
\]

Production uses `time.monotonic()` through the existing `MonotonicClock`
protocol. Tests inject `FakeClock` and advance it directly; no test sleeps.

For a one-shot, no matching completion by the deadline produces
`CALLBACK_TIMEOUT`. For a loop, a boundary deadline is armed only after a
graceful exit becomes pending; an explicit negative liveness report may fail
earlier. A replace-only loop has no ordinary boundary watchdog until an
external replacement is requested. Missing duration metadata disables
completion-driven production sequencing rather than causing a guessed
timeout.

### 10.3 Fixed outcomes

Fixed, non-sensitive outcomes include:

```text
ACCEPTED
REJECTED_PRIORITY
REJECTED_DUPLICATE
REJECTED_INCOMPATIBLE_STATE
STALE_COMPLETION
INVALID_SEQUENCE
REGISTRY_MISMATCH
PLAYER_FAILURE
CALLBACK_TIMEOUT
CLEARED
PLAYBACK_DEGRADED
RENDERER_STATE_UNKNOWN
SEQUENCING_DISABLED_CAPABILITY
LEGACY_DIRECT
```

No outcome contains a prompt, response, credential, Provider continuation,
external asset path, or raw exception. Detailed local diagnostics may record
logical identifiers, generation, fixed reason codes, and exception class, but
never Agent content or secrets.

## 11. Engineering Integration

### 11.1 New application module

Add:

```text
src/sjtuclaw/application/pet_action_sequence.py
```

It contains immutable sequence types, registry types, the runner, arbiter,
Track 0 controller, and the player protocol. If that file becomes difficult to
navigate, split by the component boundaries in section 4 without changing
their public responsibilities.

The adapted source includes an SPDX identifier and a concise provenance notice
pointing to ArkPets and the specific original Java sources.

### 11.2 Existing animation engine

Update `pet_animation.py` to coordinate the state-to-animation transaction
while preserving existing public method names and call signatures where
possible. `PetAnimationIntent` may gain a logical Track 0 action field while
retaining `base_action`, so current renderers and callers remain compatible.

### 11.3 Existing state and motion models

`pet_state.py` remains semantic authority and exposes validation/proposal
behavior required by the transaction protocol. `pet_motion.py` remains the
authority for position and physics. Neither imports the player.

The state change is intentionally narrow: add the two running motion values
and the `PetActivityState` field defined in section 6.1. Existing callers keep
using the current public state-transition methods. `thinking` and `reminding`
may be projected into the legacy behavior view during migration, but the new
activity field is the single source of truth for Track 0 compatibility. The
executable `STATE_ACTION_COMPATIBILITY` mapping lives with the state/action
boundary and is imported by validation and tests; prose tables are not a
second implementation.

### 11.4 Qt and callback boundary

`pet_window.py` retains its existing content-free request methods. A future
Spine adapter supplies callbacks through a narrow event value, not runtime
objects or file paths. The application boundary marshals that event onto the
GUI thread before dispatch.

## 12. GPL Migration Audit Gate

Adding a GPL file is not by itself sufficient to relicense a project. Before
changing `LICENSE`, README, or package metadata, implementation must create a
written audit at:

```text
docs/legal/gpl_migration_audit.md
```

The audit must include:

1. **Relicensing authority.** Identify copyright holders for all original
   SJTUClaw source and obtain an explicit project-owner attestation that the
   code may be distributed as `GPL-3.0-only`. Git authorship is evidence, not
   proof of ownership or authority.
2. **Code provenance.** Search for school-provided code, employer code,
   third-party snippets, copied examples, generated code, and prior
   contributions. Record source, license, and permission for each finding.
3. **Dependency inventory.** Record direct, transitive, optional, build, and
   packaging dependencies and the license version actually shipped. The audit
   must separately review OpenAI Python, PySide6/Qt, Nuitka, and any bundled
   native libraries; dependencies are not relicensed merely because SJTUClaw
   changes license.
4. **Distribution mode.** Record whether each dependency is merely separate,
   dynamically linked, statically linked, bundled, or modified, because those
   facts affect obligations.
5. **Asset inventory.** Record every image, icon, font, animation, audio file,
   model, exported Spine file, and other non-code asset with its separate
   license or authorization. Source-code GPL status must not be presented as
   an asset license.
6. **ArkPets provenance.** Record the repository URL, Harry Huang, GPL-3.0,
   exact source files consulted, rewritten/modified portions, omissions, and
   confirmation that no ArkPets or Arknights art asset was added.
7. **Spine boundary.** Treat Spine Editor projects, exports, and Spine Runtime
   licensing as a separate review. This change neither vendors nor relicenses
   them.
8. **Resolution.** Mark every item `PASS`, `NOT APPLICABLE`, or `BLOCKED`, with
   evidence. Any uncertain ownership, incompatible term, or missing permission
   makes the overall gate `BLOCKED` and stops the license migration.

Initial authoritative references establish the questions the audit must
answer, but do not make the audit pass automatically:

- GNU's GPL FAQ states that compatibility requires satisfying both licenses
  and that relicensing authority belongs to the applicable copyright holder:
  <https://www.gnu.org/licenses/gpl-faq.en.html>.
- Qt for Python documents PySide6 as available under LGPLv3/GPLv3 and
  commercial terms; the audit must identify the terms actually relied upon by
  this distribution: <https://doc.qt.io/qtforpython-6/licenses.html>.
- The OpenAI Python package currently declares Apache-2.0 in its upstream
  metadata, while the local locked version and shipped dependency graph still
  require verification:
  <https://github.com/openai/openai-python/blob/main/pyproject.toml>.
- GNU's GPLv3 guide identifies Apache License 2.0 as GPLv3-compatible, but that
  does not cover unrelated dependencies or assets:
  <https://www.gnu.org/licenses/quick-guide-gplv3.html>.

Only after the audit is `PASS` may implementation:

1. add the complete GPL version 3 text as root `LICENSE`;
2. change package metadata from `Proprietary` to `GPL-3.0-only`;
3. add `THIRD_PARTY_NOTICES.md` with ArkPets attribution and dependency
   notices;
4. add a README section that states separately:

   ```text
   Source Code: GPL-3.0-only
   Assets: not covered by the source-code license; see the per-asset license
   or authorization records.
   ```

5. add `ASSETS_LICENSE.md` (or an equivalent asset manifest), even when the
   initial result is that no distributable character assets are included;
6. include required dependency license texts and notices in packaged
   distributions;
7. add SPDX and modification/provenance notices to the adapted Python source.

The implementation will consult only these ArkPets sources and will not vendor
the Java source tree:

```text
core/src/cn/harryh/arkpets/animations/AnimData.java
core/src/cn/harryh/arkpets/animations/AnimComposer.java
core/src/cn/harryh/arkpets/animations/AnimClipGroup.java
core/src/cn/harryh/arkpets/animations/AnimClip.java
```

## 13. Testing Strategy

### 13.1 Component unit tests

Tests verify:

1. steps and sequences are immutable descriptions;
2. the sequence's ordered `steps` tuple is the only next-step source and a
   step has no `next` field or alternate successor pointer;
3. `then()` returns ordered data without mutating its source;
4. the logical catalog contains exactly 25 unique, case-sensitive names;
5. the union of logical names referenced by the sequence catalog equals the
   complete 25-name set, assigns `breathing` only to Track 1 and `blink` only
   to Track 2, and validates every Track 0 step against at least one compatible
   semantic key;
6. registry identity mapping, alias mapping, missing binding, duplicate
   binding, and case mismatch behavior;
7. the arbiter alone implements the total priority order, request-level
   protection, and same-class replacement rules;
8. the runner alone implements current step, one-shot completion, loop pending
   exit, duplicate completion suppression, and reset;
9. controller `cancel`, `clear`, and runner `reset` have the exact distinct
   side effects defined in section 7;
10. every `play` and every `clear` attempt consumes a new generation, while a
    runner-only reset does not;
11. `loop_boundary_without_pending_exit` leaves player `play()` call count,
    generation, playback token, confirmed epoch, and runner index unchanged;
12. the first matching boundary after graceful exit issues exactly one play
    for the declared exit step and advances generation exactly once;
13. callbacks advance only when generation, logical name, physical name,
    token, and expected step all match;
14. the four-capability gate is all-or-nothing: every missing-capability
    permutation disables production sequencing;
15. `PlaceholderAnimationPlayer` always uses `LEGACY_DIRECT`, never starts a
    production sequence, and never fabricates completion with a timer;
16. invalid sequences are rejected before state or player mutation;
17. `FakeClock` verifies the exact watchdog deadline formula, lower and upper
    tolerance clamps, positive-speed validation, and one-shot timeout behavior
    without sleeping;
18. proposal epoch tests start from committed epoch 17, verify that the state
    machine supplies target epoch 18, that `ActionRequest` copies 18, that an
    accepted or mandatory transition commits exactly 18, and that a rejected
    normal proposal leaves committed epoch 17 without engine-side increment.

The compatibility mapping receives an exhaustive table test. For every valid
combination of lifecycle, motion, activity, and overlay behaviors, the test
cross-products all 25 logical actions and checks the result against the one
immutable mapping. It separately checks `desired_action=None` in
`DEGRADED`/`UNKNOWN` health and rejects inactive-lifecycle Track 0 playback.

The arbiter receives a full matrix test over every incoming class, every active
class, both active protection values, and the relevant equality dimensions
(same/different sequence, request token, input-session token, and semantic
epoch). Every cell asserts the applicable fixed outcome such as `ACCEPTED`,
`REJECTED_PRIORITY`, or `REJECTED_DUPLICATE`, plus the exact cancellation mode
or explicit no-controller-directive result; no priority pair is left to an
example-only test.

Named drag-arbitration cases pin the matrix to lifecycle semantics:

- session A `DRAG_HOLD` requested again as session A `DRAG_HOLD` is
  `REJECTED_DUPLICATE`;
- session A `DRAG_HOLD -> DRAG_RELEASE` is the approved phase `REPLACE`;
- session B `DRAG_HOLD` replaces session A `DRAG_RELEASE`;
- `FALL_RECOVERY` and `LANDING` retain `MOTION_SAFETY` rank and outrank any
  active user-interaction request.

### 13.2 Deterministic interleaving tests

Although mutation is GUI-thread-owned, logical concurrency is tested by
controlling event order:

1. old completion then new request;
2. new request then old completion;
3. completion queued from a renderer thread while a drag request is pending;
4. duplicate completion before and after replacement;
5. callback with correct name but stale generation;
6. callback with correct generation but wrong physical binding;
7. graceful loop exit racing with a higher-priority replacement;
8. repeated loop boundaries before graceful exit with stable generation,
   player token, confirmed epoch, runner index, and `play()` call count;
9. session A release callback arriving after session B has replaced it with a
   new `DRAG_HOLD`.

Every interleaving asserts both runner state and semantic-state/action
compatibility. In particular, `dragging + sleep_loop`, `sleeping + drag_loop`,
and inactive lifecycle plus `idle` are forbidden combinations.

### 13.3 Player failure tests

A fake player exercises:

- exception or rejection from `play`;
- mandatory `READING -> FALLING` with `FALL_RECOVERY/drag_end` preflight
  rejection and a successful containment clear;
- the same mandatory transition with a failed containment clear;
- successful containment `clear` after failed `play`;
- failed containment `clear` after failed `play`;
- exception from a normal `clear`;
- missing one-shot completion;
- lost loop liveness;
- stale callback after failure recovery;
- explicit re-probe/reinitialization from `DEGRADED` and `UNKNOWN`;
- absence of any automatic fallback-idle `play` command.

Each failure must leave `PetState` valid, invalidate the old generation, avoid
uncaught Qt exceptions, and leave the Agent runtime untouched. Assertions also
distinguish desired playback from confirmed playback: successful containment
ends `DEGRADED` with no confirmed epoch, while a failed clear ends `UNKNOWN`
without claiming that the renderer is idle or empty.

The two mandatory-transition tests additionally assert that the state epoch is
committed to `FALLING`, `read` is no longer desired, the rejected `drag_end` is
never played, the old generation is invalidated, the runner is empty, and the
final state/action/health tuple passes the compatibility invariant.

### 13.4 Integration and Agent-isolation regression tests

Tests preserve walking, thinking, reminding, dragging, falling, landing,
pause, resume, close, and placeholder rendering.

They also verify:

- pet startup does not activate a Provider;
- pet startup does not read a `SecretStore`;
- pet startup does not access an external network;
- closing the Agent window hides it without stopping the pet runtime;
- safe exit still waits for `RuntimeThread` shutdown;
- animation failures neither close, restart, nor wake the Agent;
- the sequencing module cannot import Agent/runtime/provider modules.

Existing unit and Qt tests must remain green. An Agent regression must be
fixed at the pet/action boundary, never by weakening Agent lifecycle behavior.

### 13.5 License and asset tests

Before migration, tests/checks require an audit result of `PASS`. After
migration they verify agreement among root license, package metadata, README,
asset manifest, and third-party notices, and verify that no ArkPets or
Arknights character image, animation frame, Spine project, audio, or pet pack
was added.

## 14. Completion Boundary

Completion of this change means only:

- the selected ArkPets sequencing mechanism has been adapted into the
  separated registry/arbiter/runner/controller/player architecture;
- the executable state/action compatibility mapping and complete 25-action
  sequence catalog are the tested sources of truth;
- state-to-animation ownership, deterministic arbitration, cancellation,
  per-command generation, stale callback, playback-health, and exact watchdog
  protocols are tested;
- production sequencing is capability-gated, while the current placeholder
  remains on the tested legacy direct path and synthesizes no completion;
- the GPL audit passed before any source-license migration;
- relevant unit, Qt, Agent-isolation, license, and asset checks pass.

It does not mean that Spine Runtime export, Track composition, programmatic
Spine playback, event callbacks, remaining Spine animation production, or
Agent program integration has been completed. Those activities remain paused
pending their own approved execution steps.

After this closure, implementation proceeds test-first against these
invariants. A failing implementation test is corrected in implementation by
default; the architecture/specification is reopened only when evidence shows
that an invariant itself is contradictory or impossible to satisfy.
