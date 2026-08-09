# Schwarz Production Autonomous Animation Design

**Date:** 2026-08-09
**Status:** Revised specification pending user freeze review
**Scope:** Production Schwarz desktop-pet runtime with six original Spine 3.8
animations, persistent tray lifetime, high-DPI rendering, ArkPets-inspired
autonomous behavior, explicit action requests, and reusable external role packs

## 1. Objective

Deliver the first production-capable Schwarz animation experience in SJTUClaw:

1. the desktop pet remains alive in the system tray until the user explicitly
   exits;
2. the Spine character is rendered at the window's real device-pixel ratio;
3. the six exact original animations `Relax`, `Move`, `Sit`, `Sleep`,
   `Special`, and `Interact` are all usable;
4. autonomous behavior is random and state-dependent rather than a fixed
   periodic playlist;
5. the user, tray, or Agent can request a specific logical action through one
   content-free application API;
6. compatible Ark-models character packages remain externally selectable as
   complete `.skel + .atlas + .png` role packs without copying them into the
   repository; and
7. an explicit looping action remains under explicit control until the user
   requests another action or explicitly resumes autonomous mode.

The behavior mechanism is an independent Python design informed by ArkPets'
stochastic transition, strict one-shot, queued-next, and mobility concepts. It
does not run ArkPets as a sidecar and does not copy its Java implementation.

## 2. Existing Contracts Retained

This specification extends rather than replaces:

- `2026-08-07-arkpets-action-sequence-reuse-design.md`, which remains
  authoritative for semantic state, Track 0 arbitration, cancellation,
  playback generations, stale callbacks, and safety priority;
- `2026-08-08-arkpets-spine-runtime-integration-design.md`, which remains
  authoritative for the Spine 3.8 bridge, external asset validation, renderer
  isolation, and Agent isolation;
- `2026-08-09-spine38-visible-frame-scaling-design.md`, which remains
  authoritative for fitting the visible character bounds to the pet window
  and placing the feet above the taskbar.

If those documents describe a broader 25-action future catalog, this document
narrows the current production milestone to the six confirmed Schwarz
animations. It preserves extension seams for later actions but does not claim
that the other actions are implemented.

## 3. Confirmed Schwarz Catalog

The accepted external Schwarz package exposes these playable, case-sensitive
animations:

| Logical role | Physical animation | Duration | Intent |
| --- | --- | ---: | --- |
| `RELAX` | `Relax` | 5.000000 s | looping idle |
| `MOVE` | `Move` | 2.666667 s | looping locomotion |
| `SIT` | `Sit` | 3.333333 s | looping seated state |
| `SLEEP` | `Sleep` | 4.000000 s | looping sleep state |
| `SPECIAL` | `Special` | 11.533334 s | protected one-shot |
| `INTERACT` | `Interact` | 1.333333 s | protected one-shot |

The zero-duration `Default` sentinel is not an action and remains filtered
from the playable catalog.

`MOVE_LEFT` and `MOVE_RIGHT` are two logical actions backed by the same
physical `Move` animation. Direction belongs to semantic motion and renderer
reflection, not to a second physical animation name.

Terminology is fixed throughout this design:

```text
Physical Spine animation count: 6
Production logical action count: 7
Autonomous state count: 6
```

The seven logical actions are `RELAX`, `MOVE_LEFT`, `MOVE_RIGHT`, `SIT`,
`SLEEP`, `SPECIAL`, and `INTERACT`. The six autonomous states exclude
`INTERACT`.

## 4. Authority and Invariants

There remains one authority for each concern:

- `PetLayeredStateMachine` owns semantic lifecycle, activity, and motion;
- `PetMotionModel` owns window position, velocity, workspace bounds, dragging,
  falling, landing, and border response;
- `PetActionArbiter` decides whether an action request may replace active
  playback or must be rejected; it owns no waiting policy or queue;
- `PetSequenceRunner` exclusively owns active sequence progress, step
  advancement, and pending graceful loop exit;
- `PendingExplicitActionSlot`, owned by `PetAnimationEngine`, exclusively owns
  at most one blocked high-level explicit intent; it never stores a prepared
  semantic epoch or renderer request;
- `PetTrack0Controller` is the thin transaction coordinator that owns Track 0
  playback side effects, generation, registry resolution, and player
  invocation;
- `PetAnimationEngine` owns the current immutable
  `AutonomousSchedulerState` value, the current execution mode, and the only
  proposal/commit bridge between scheduler output and application state;
- `AutonomousActionScheduler` has no hidden mutable state and may only propose
  low-authority actions;
- the Spine renderer draws evaluated geometry and owns no behavior policy;
- `PetApplicationCoordinator` and `SystemTrayController` own production
  lifetime.

Mandatory invariants:

1. Random selection never calls the renderer or moves the window directly.
2. A random proposal must pass through the same semantic transition and Track
   0 arbitration as an explicit request.
3. Closing, motion safety, dragging, and falling always outrank autonomous and
   explicit actions.
4. `Move` playback and physical window movement must start, turn, and stop as
   one application transaction. A walking pet may not continue displaying
   `Relax`.
5. A stale animation callback cannot change semantic state, scheduler dwell,
   pending explicit action, sequence progress, or playback state.
6. Randomness is injectable and deterministic in tests.
7. Missing optional actions in another role pack are disabled before
   selection; their weights are never sampled.
8. Runtime, asset, or OpenGL failure cannot wake, close, restart, or otherwise
   mutate the local Agent.
9. Scheduler proposals are not state transitions. Only an accepted semantic,
   motion, and playback transaction may commit a proposed autonomous
   destination.
10. An explicit looping action suspends autonomous scheduling until an
    explicit resume command or a higher-authority lifecycle/safety event.

## 5. Component Architecture

```text
RolePackManifest ----> AnimationRoleRegistry ---------------------+
                                                                 |
AutonomousActionScheduler ---- proposed ActionIntent ---------+   |
Tray/User/Agent -------------- explicit action/mode command --+   |
Safety/Drag/Close ------------ mandatory request -------------+   |
                                                             v   v
                                                   PetAnimationEngine
                                                    |             |
                                  PendingExplicitActionSlot       |
                                                    |             |
                                                    v             v
                                              PetActionArbiter
                                                    |
                                                    v
                                             PetSequenceRunner
                                                    |
                                                    v
                                           PetTrack0Controller
                                                    |
                                                    v
                                             AnimationPlayer
                                                    |
                                                    v
                                         Spine38 player/renderer

PetLayeredStateMachine + PetMotionModel remain the semantic and physical
authorities coordinated by PetAnimationEngine; they are not downstream
renderer components.
```

### 5.1 `AnimationRoleRegistry`

Business logic speaks only the following production roles:

```text
RELAX
MOVE_LEFT
MOVE_RIGHT
SIT
SLEEP
SPECIAL
INTERACT
```

The registry maps them to one role pack's exact physical names and direction
policy. Both move roles may explicitly alias the same physical animation when
the pack declares a reviewed reflection policy.

The registry also exposes capabilities. The scheduler can ask whether `SIT`,
`SLEEP`, or `SPECIAL` is available without learning a Spine name. `RELAX` is
required for every production-capable pack. A pack lacking another role can
still load, but that role is unavailable and removed from autonomous and
explicit menus.

The semantic mapping is fixed and extends the existing enums without renaming
existing values:

| Production action | `PetMotionState` | `PetActivityState` |
| --- | --- | --- |
| `RELAX` | `IDLE` | `NONE` |
| `MOVE_LEFT` | `WALKING_LEFT` | `NONE` |
| `MOVE_RIGHT` | `WALKING_RIGHT` | `NONE` |
| `SIT` | `IDLE` | `SITTING` |
| `SLEEP` | `IDLE` | `SLEEPING` |
| `SPECIAL` | `IDLE` | new `SPECIAL` |
| `INTERACT` | `IDLE` | new `INTERACT` |

`AnimationRoleRegistry` maps these logical actions to physical names; it does
not own or infer semantic state.

### 5.2 `AutonomousActionScheduler`

The scheduler is a deterministic, framework-independent application component
whose state is explicit and immutable:

```text
AutonomousExecutionMode: AUTONOMOUS | EXPLICIT_HOLD | SUSPENDED
```

`PetAnimationEngine` owns this mode. `SUSPENDED` covers pause, safety,
containment/recovery, role-pack replacement, and protected one-shot playback;
the scheduler itself neither enters nor exits a mode.

```python
@dataclass(frozen=True, slots=True)
class AutonomousSchedulerState:
    last_committed_state: AutonomousState
    entered_at: float
    dwell_target_seconds: float | None
    boundary_epoch: int
    proposal_eligible: bool
```

Its conceptual API is:

```python
evaluate(
    state: AutonomousSchedulerState,
    snapshot: AutonomousRuntimeSnapshot,
    event: AutonomousBoundaryEvent | None,
    rng: RandomSource,
) -> AutonomousSchedulerDecision
```

`last_committed_state` is scheduling history, not a second semantic authority.
The current semantic action is always derived from `PetLayeredStateMachine`.
The scheduling value changes to a destination only after
`PetAnimationEngine` commits the corresponding semantic, motion, and playback
transaction.

`AutonomousSchedulerDecision` contains a retained immutable source-state value
and either no suggestion, `STAY`, or one proposed logical `ActionIntent`.
Given the same scheduler state, runtime snapshot, boundary event, and
random-source state, it produces the same decision. It never mutates semantic
state, motion, sequence state, or renderer objects.

Proposal handling is two-phase:

1. `evaluate(...)` may propose a destination but does not commit it or sample
   that destination's dwell;
2. `PetAnimationEngine` submits the intent through semantic validation and
   Track 0 arbitration;
3. only after the complete application transaction succeeds does the engine
   commit `last_committed_state`, the new entry time, and one destination
   dwell sample;
4. a rejected proposal keeps the source state, consumes no destination dwell,
   is never queued, invalidates the old eligibility window, and starts a fresh
   eligibility window only after autonomous scheduling becomes eligible
   again.

`STAY` is a scheduler-local accepted decision: it does not cross the playback
seam and commits only a fresh dwell target for the unchanged state.

### 5.3 Explicit action gateway

The application exposes one content-free request boundary conceptually
equivalent to:

```python
request_action(action: ProductionAction, source: ActionSource) -> ActionOutcome

resume_autonomous(source: ActionSource) -> ActionOutcome
```

Two orthogonal fields are retained:

```text
ActionOrigin: SYSTEM | EXPLICIT | AUTONOMOUS
ActionSource: TRAY | USER | AGENT | SCHEDULER | MOTION | LIFECYCLE
```

Only `ActionOrigin` participates in arbitration. `ActionSource` is diagnostic
and audit metadata used by UI state and deterministic tests. Source/origin
combinations are validated: tray, direct user, and Agent action requests are
`EXPLICIT`; scheduler requests are `AUTONOMOUS`; motion and lifecycle requests
are `SYSTEM` except that direct drag/click manipulation retains the existing
`USER_INTERACTION` interrupt class.

The request contains an enum, identity token, origin, and source metadata
only. It cannot contain Agent response text, prompts, credentials, renderer
names, or a precomputed semantic epoch.

Tray actions and future shortcuts use this same boundary. The Agent may use it
only through an explicit typed intent; ordinary conversation text is never
parsed inside the animation subsystem.

### 5.4 `PendingExplicitActionSlot`

`PetAnimationEngine` owns one narrow application-layer slot distinct from
`PetSequenceRunner.pending_graceful_exit`. Its value is a
`PendingExplicitIntent` containing only the production action, source, and
identity token. When consumed, the engine revalidates current capabilities,
creates a fresh semantic proposal, and constructs a new Track 0 request with
the then-current semantic epoch. The slot:

- stores at most one explicit request blocked by protected playback;
- replaces its value when a newer explicit request arrives;
- is consumed exactly once by a verified matching protected completion;
- is cleared by safety, drag, pause, shutdown, containment, and role-pack
  replacement;
- never accepts an autonomous proposal.

The engine also owns a `resume_after_protected` flag. A resume-autonomous
command received during protected playback clears the pending explicit slot
and sets this flag. A later explicit action clears the flag and becomes the
latest pending intent. Matching protected completion consumes exactly one of
these mutually exclusive continuations.

`PetActionArbiter` remains a pure decision component and owns no queue.
`PetSequenceRunner` owns only the active sequence's own execution state.

## 6. Autonomous State Model

The autonomous state set is:

```text
RELAX
SIT
SLEEP
MOVE_LEFT
MOVE_RIGHT
SPECIAL
```

`INTERACT` is deliberately excluded from autonomous sampling. It represents a
user or Agent-directed interaction rather than spontaneous background
behavior.

### 6.1 State-dependent weighted selection

At an eligible transition boundary, the scheduler selects the next state from
the current state's configured row. The immutable version-1 profile is:

| From / To | `RELAX` | `SIT` | `SLEEP` | `MOVE_LEFT` | `MOVE_RIGHT` | `SPECIAL` |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `RELAX` | 45 | 20 | 10 | 10 | 10 | 5 |
| `SIT` | 35 | 40 | 20 | 2 | 3 | 0 |
| `SLEEP` | 10 | 15 | 75 | 0 | 0 | 0 |
| `MOVE_LEFT` | 45 | 10 | 0 | 25 | 20 | 0 |
| `MOVE_RIGHT` | 45 | 10 | 0 | 20 | 25 | 0 |

`SPECIAL` has no weighted row. Its verified completion follows the fixed rule
in section 6.2.

Weights live in immutable validated configuration. Every row must contain
non-negative finite integer weights and at least one positive weight after
unavailable roles are removed. Disabled destinations are omitted and the
remaining row is renormalized by weighted sampling. An invalid row fails
closed to `RELAX` rather than producing no animation.

When weighted selection returns the current state, the decision is `STAY`, not
a new `ActionIntent`. `STAY` leaves semantic state, Track 0 playback,
generation, playback token, and physical animation unchanged, then samples
exactly one new dwell target. In particular, `RELAX -> RELAX` means “continue
the current Relax loop”, not “play Relax from frame zero again”.

### 6.2 Non-periodic dwell and transition boundaries

The scheduler does not choose on every Qt timer tick and does not run a fixed
`N`-second cycle.

For looping states, it samples exactly one bounded dwell target when the state
starts. Version 1 uses:

| State | Minimum | Maximum |
| --- | ---: | ---: |
| `RELAX` | 8.0 s | 20.0 s |
| `MOVE_LEFT` | 4.0 s | 10.0 s |
| `MOVE_RIGHT` | 4.0 s | 10.0 s |
| `SIT` | 15.0 s | 35.0 s |
| `SLEEP` | 30.0 s | 90.0 s |

Every value must be finite and satisfy `0 < minimum <= maximum`. The dwell
target is never resampled on a timer tick. It is resampled only on accepted
state entry or `STAY`.

An autonomous transition may be proposed only while processing a confirmed
matching loop-boundary event whose callback time is at or after the current
dwell deadline. A boundary received before the deadline is observational and
is not latched for a later timer tick. The state becomes eligible only after
both:

1. the sampled dwell target has elapsed; and
2. a confirmed matching loop boundary has arrived.

This preserves complete animation loops while making the number of loops and
wall-clock duration variable. Each state has an independently configurable
range; sleep is longer than sit, sit is longer than a typical movement run,
and relax remains the common baseline.

`SPECIAL` uses no dwell profile and never samples its own next state. Its
verified matching completion consumes one pending explicit request when
present; otherwise it requests `RELAX`. Autonomous `SPECIAL -> SPECIAL` is
impossible.

Frame cadence, delayed frames, or a large delta cannot cause multiple random
transitions in one update. At most one autonomous proposal is emitted per
accepted boundary.

### 6.3 Movement behavior

An accepted `MOVE_LEFT` or `MOVE_RIGHT` transaction:

1. commits the matching semantic motion and facing;
2. starts the physical `Move` animation;
3. enables `PetMotionModel` velocity in the same direction.

When the workspace boundary would be crossed, `PetMotionModel` contains the
position and proposes the opposite move direction. Direction changes have
these fixed playback semantics:

- an autonomous left/right transition occurs only on a verified matching loop
  boundary, commits the new semantic direction/facing/velocity, allocates a
  new generation and playback token, and starts the same physical `Move`
  animation exactly once at that natural boundary;
- a workspace collision in the middle of a loop clamps position and sets
  velocity to zero immediately, then submits a mandatory direction-turn
  transaction; version 1 immediately commits the opposite direction and
  restarts physical `Move` with a new generation and token rather than leaving
  semantic direction and playback identity inconsistent;
- neither path inserts `Relax` between directions;
- version 1 does not implement phase-preserving alias retargeting.

An explicit non-move action stops velocity in the same transaction that
replaces `Move` playback. If physical `Move` playback cannot be established,
the containment transaction stops velocity, commits the safe semantic
`RELAX` state, marks playback degraded or unknown through the existing health
protocol, and leaves autonomous scheduling stopped until recovery. The pet
must never keep moving physically after `Move` playback fails.

## 7. Interruption, Queuing, and Priority

The existing `InterruptClass` ordering remains unchanged:

```text
SYSTEM_SHUTDOWN
    > MOTION_SAFETY
    > USER_INTERACTION
    > STRICT_ACTION
    > NORMAL_ACTION
    > IDLE
```

`ActionOrigin` adds `SYSTEM`, `EXPLICIT`, and `AUTONOMOUS` without creating a
second priority model. Within `NORMAL_ACTION` only, `EXPLICIT` outranks
`AUTONOMOUS`; an autonomous normal request cannot replace an active explicit
normal request.

| Request | Interrupt class | Origin | Protected |
| --- | --- | --- | --- |
| shutdown | `SYSTEM_SHUTDOWN` | `SYSTEM` | not applicable |
| falling/collision recovery | `MOTION_SAFETY` | `SYSTEM` | existing policy |
| direct drag/click manipulation | `USER_INTERACTION` | `EXPLICIT` | existing policy |
| `SPECIAL` | `STRICT_ACTION` | `EXPLICIT` or `AUTONOMOUS` | `True` |
| `INTERACT` | `STRICT_ACTION` | `EXPLICIT` | `True` |
| explicit `RELAX/SIT/SLEEP/MOVE_*` | `NORMAL_ACTION` | `EXPLICIT` | `False` |
| autonomous `RELAX/SIT/SLEEP/MOVE_*` | `NORMAL_ACTION` | `AUTONOMOUS` | `False` |
| idle fallback | `IDLE` | `SYSTEM` | `False` |

A tray action is an explicit normal or strict action according to this table;
it is not promoted to `USER_INTERACTION`. That class remains reserved for
direct manipulation such as dragging.

Rules approved for this milestone:

1. An explicit request immediately replaces autonomous `RELAX`, `SIT`,
   `SLEEP`, or either movement direction.
2. Once `SPECIAL` or `INTERACT` begins, an explicit normal request does not
   cut it off. `PetAnimationEngine.PendingExplicitActionSlot` stores the
   request and starts it after the protected one-shot completes.
3. A newer explicit request replaces the older pending request. There is no
   unbounded action queue.
4. An explicit request for `SPECIAL` or `INTERACT` while another protected
   action is active also occupies that single pending slot.
5. Closing, dragging, falling, landing, pause, renderer containment, or other
   mandatory safety work interrupts protected playback immediately and clears
   the pending explicit slot.
6. Autonomous proposals are never queued. A rejected autonomous proposal is
   discarded without committing its destination or consuming destination
   dwell. The old eligibility window is invalidated, and a fresh window begins
   only after autonomous scheduling becomes eligible again.
7. `SPECIAL` and `INTERACT` complete by verified native playback identity,
   not by a guessed timer. Each consumes the pending explicit request exactly
   once when present; otherwise each requests `RELAX`.

The request-origin field and equal-class tie-break are part of the pure
arbiter contract and receive an exhaustive matrix test. No new interruption
class is introduced.

### 7.1 Explicit hold and autonomous resume

An explicit `RELAX`, `SIT`, `SLEEP`, `MOVE_LEFT`, or `MOVE_RIGHT` request
enters `EXPLICIT_HOLD` after its semantic/motion/playback transaction succeeds:

- autonomous evaluation is suspended and no autonomous dwell is used to exit;
- the loop continues across matching loop boundaries without restarting,
  changing generation, or changing playback token;
- the hold ends only when a newer explicit action replaces it, a drag/safety/
  pause/shutdown/containment event interrupts it, or the user issues
  `resume_autonomous(...)`;
- repeating the same held action is an accepted idempotent no-op: it does not
  restart playback or allocate a new generation/token.

`resume_autonomous(...)` is a typed mode command, not an eighth logical
action. Outside protected playback it atomically establishes `RELAX`, samples
one fresh Relax dwell, and resumes the scheduler. During protected playback
it clears any pending explicit action and records `resume_after_protected`;
the verified matching completion then establishes `RELAX` and resumes the
scheduler.

`SPECIAL` and `INTERACT` are never held. Their matching completion consumes a
freshly revalidated pending intent when one exists. Without a pending intent,
or with `resume_after_protected`, completion establishes `RELAX`, samples one
fresh Relax dwell, and resumes autonomous scheduling. Starting a protected
one-shot from an explicit hold ends that hold.

## 8. Role-Pack Reuse

A role pack is selected through an explicit external manifest. Conceptually it
contains:

```yaml
schema_version: 1
pack_id: schwarz-production
spine_version: "3.8"
assets:
  skeleton: D:\\...\\character.skel
  atlas: D:\\...\\character.atlas
  texture: D:\\...\\character.png
expected_sha256:
  skeleton: "..."
  atlas: "..."
  texture: "..."
animations:
  relax: Relax
  move: Move
  sit: Sit
  sleep: Sleep
  special: Special
  interact: Interact
direction_policy: mirror_move
```

The exact serialization format may reuse the project's existing manifest
model, but these semantics are mandatory:

- schema version 1 supports exactly one atlas texture page and one matching
  texture file; multi-page atlases require a later schema version;
- a manifest selects one complete `.skel + .atlas + .png` package;
- paths are explicit, absolute, external, and read-only;
- hashes and Spine version are validated before native construction;
- logical-to-physical animation bindings are data, not conditionals in the
  renderer;
- missing optional bindings are reported as capabilities;
- no attachment, atlas page, texture, or animation is mixed across role packs;
- package switching follows the two-phase replacement protocol below and
  cannot mutate either source directory;
- assets, generated evidence, and screenshots remain outside tracked source.

Schwarz production startup requires all six physical animations. The generic
framework permits a future compatible pack to omit optional roles while
retaining `RELAX`, but unavailable actions must be visibly disabled rather
than silently mapped to an unrelated animation.

### 8.1 Transactional role-pack replacement

Role-pack switching is a two-phase GUI-thread transaction:

1. parse the candidate manifest;
2. validate schema, paths, hashes, Spine version, the single texture page,
   exact animation names, aliases, direction policy, and required
   capabilities;
3. construct candidate native and renderer resources without replacing or
   destroying the active package;
4. if candidate construction fails, destroy only candidate partial resources,
   retain the active package unchanged, and return a stable failure outcome;
5. after the candidate is fully ready, enter the switch-quiesce transaction:
   stop autonomous scheduling, set velocity to zero, clear explicit hold and
   pending/resume continuation state, and commit the safe semantic `RELAX`
   state before invalidating the old Track 0 generation and clearing old
   Track 0 playback;
6. if that old-playback containment fails, abort publication and destroy the
   candidate. The old package remains the active pack identity, but its
   playback is not assumed healthy: existing `DEGRADED`/`UNKNOWN` semantics
   apply, autonomous scheduling remains stopped, and recovery requires the
   existing explicit renderer/player recovery or re-probe path;
7. after successful containment, atomically publish the candidate as active;
8. destroy the old package resources only after that commit;
9. play candidate `RELAX`; only after that playback is confirmed healthy,
   sample one fresh Relax dwell and resume autonomous scheduling.

A same-manifest request is a validated no-op. If candidate resources cannot
coexist temporarily with the active resources, the switch fails without
destroying the active package; version 1 does not use a destructive fallback.

## 9. Production Lifetime and Tray Behavior

The production entry point uses the existing `PetApplicationCoordinator` and
`SystemTrayController`. The timed vertical-slice diagnostic remains a test
tool and is not the production launcher.

Production rules:

1. startup creates exactly one pet window and one tray controller;
2. no animation count, sample count, or timer calls `quit()`;
3. closing or hiding the pet window keeps the tray/runtime alive according to
   the existing tray contract;
4. only the explicit tray `Exit` action or existing controlled application
   shutdown ends the process;
5. the tray exposes seven selectable logical actions, the separate
   `Resume Autonomous` mode command, and the current role-pack identity
   without importing Agent modules: `Relax`, `Move > Left`, `Move > Right`,
   `Sit`, `Sleep`, `Special`, and `Interact`;
6. startup or role-pack validation failure retains the existing placeholder
   and tray so the user can see that the application is still running.

## 10. High-DPI Rendering

The OpenGL backing surface must use the active pet window's actual device
pixel ratio rather than the backend's current default of `1.0`.

For logical viewport width `W`, height `H`, and finite positive device-pixel
ratio `d`, the backing dimensions are:

\[
W_p = \lceil W d \rceil, \qquad H_p = \lceil H d \rceil
\]

The renderer must:

- obtain DPR from the owning Qt window/screen;
- recreate or resize the framebuffer when logical size, DPR, or screen
  changes;
- use physical-pixel viewport dimensions while preserving logical layout and
  visible-bounds fitting;
- avoid a second Qt upscale of a 1x intermediate image;
- preserve transparent edges and the approved foot baseline/taskbar gap;
- resolve minification and magnification independently: use each
  atlas-declared filter when exposed and supported, otherwise use `LINEAR`
  for only that missing or unavailable field, replacing the current backend's
  unconditional `Nearest` behavior;
- retain premultiplied-alpha and blend-mode correctness.

Acceptance covers DPR values `1.0`, `1.25`, `1.5`, and `2.0`. At each value,
the offscreen surface must have the corresponding physical dimensions and the
visible character must retain the same logical footprint and foot baseline.
One immutable transform is used for a role-pack session; it is never recomputed
per frame. Schwarz acceptance samples all six physical animations and rejects
production framing if any nontransparent geometry is cropped by the approved
fixed transform.

## 11. Failure Containment

All new paths fail closed:

- invalid random profile: use `RELAX`, publish a fixed safe status, and do not
  loop exceptions through Qt;
- unavailable explicit action: reject with a stable outcome and retain current
  valid action;
- asset/hash/version failure: do not construct the Spine bridge; retain the
  placeholder and tray;
- native playback failure: stop physical movement, commit safe semantic
  `RELAX`, clear/invalidate Track 0 using the existing health protocol, and
  stop autonomous scheduling until recovery;
- render-context or high-DPI framebuffer failure: close partial GPU resources,
  retain the application/tray, and use the safe fallback;
- role-pack switch failure before quiesce: close candidate partial resources
  and retain the last fully valid package unchanged;
- role-pack containment failure after quiesce: retain the old pack identity
  without claiming its playback is healthy, destroy the candidate, and keep
  autonomous scheduling stopped pending explicit recovery;
- stale callback: ignore it without consuming dwell time or pending requests;
- shutdown: cancel autonomous work and pending explicit action before native,
  GPU, bundle, window, tray, and application teardown.

No exception or recovery path may activate a Provider, inspect credentials,
or terminate the Agent runtime.

## 12. Verification Strategy

Implementation is test-driven. Each behavior begins with a failing test that
collects successfully and fails for the absent or incorrect behavior.

### 12.1 Pure unit tests

- seeded state-transition sequences are reproducible;
- selected distinct seeds produce at least two distinct deterministic
  histories; no statistical distribution or “looks non-periodic” assertion is
  used;
- every transition row respects disabled capabilities and positive-weight
  validation;
- sleep never transitions directly to move/special and special never repeats;
- same-state selection produces `STAY`, resamples dwell once, and does not
  change semantic state, generation, token, or player call count;
- dwell is sampled exactly once on state entry, remains within the frozen
  range, and is not consumed by a stale boundary;
- dwell targets require both elapsed time and the correct playback boundary;
- one update emits at most one autonomous proposal;
- a proposed destination is committed only after the corresponding semantic,
  motion, and playback transaction succeeds;
- a rejected autonomous proposal retains the source scheduler state, consumes
  no destination dwell, is not queued, and invalidates the old eligibility
  window;
- explicit requests replace autonomous loops immediately;
- explicit normal loops enter hold, ignore autonomous dwell/boundaries, and
  remain stable until replacement, mandatory interruption, or explicit
  autonomous resume;
- repeating the currently held loop is idempotent and does not call `play()`
  or change generation/token;
- autonomous resume establishes `RELAX`, samples one fresh dwell, and enables
  the scheduler only after Relax playback succeeds;
- explicit requests queue behind protected `SPECIAL/INTERACT` in the bounded
  latest-wins slot;
- drag, safety, pause, and shutdown interrupt protected actions and clear the
  pending slot;
- stale or mismatched completion does not release a pending request;
- the pending explicit slot is latest-wins, never accepts autonomous work, is
  consumed once by matching protected completion, and is cleared by safety;
- the pending slot stores no semantic epoch; consumption revalidates the
  capability and creates a fresh epoch-bound request;
- resume during protected playback clears pending explicit work and is applied
  once by matching protected completion;
- all priority/origin combinations are covered by an exhaustive arbiter
  matrix;
- missing role bindings are disabled rather than substituted.

### 12.2 Motion and playback integration tests

- walking left/right selects physical `Move`, changes facing, and changes the
  window position in the same direction;
- failed `Move` playback stops velocity, establishes semantic `RELAX`, marks
  playback degraded/unknown, and leaves autonomous scheduling stopped;
- stopping or replacing move stops physical velocity and no frame reports
  moving semantic state with `Relax` playback;
- boundary contact turns autonomous movement without leaving the workspace;
- `Special` and `Interact` play exactly once and return to `Relax` or the one
  valid pending explicit action;
- all six exact Schwarz names and durations are verified through the Release
  Spine 3.8 bridge;
- production startup creates the tray and remains alive beyond the previous
  three-loop diagnostic duration in the manual Windows smoke;
- deterministic lifecycle tests prove animation completion, scheduler ticks,
  hide, and tray-governed window close never call `quit()`;
- deterministic lifecycle tests prove one startup creates exactly one
  `PetWindow` and one `SystemTrayController`, while explicit tray `Exit`
  invokes controlled shutdown.

### 12.3 High-DPI and Qt/OpenGL tests

- DPR-dependent framebuffer dimensions at `1.0`, `1.25`, `1.5`, and `2.0`;
- DPR/screen-change recreation without leaked or double-destroyed resources;
- alpha bounds, visible scale, and foot baseline remain logically stable;
- all six Schwarz animations remain within the approved immutable viewport
  transform without per-frame reframing or nontransparent cropping;
- real-driver pixel probes exercise texture filtering, normal/PMA blend modes,
  transparency, and no 1x-to-high-DPI upscale;
- the Windows production smoke remains visible and alive for manual review
  until the operator exits from the tray.

### 12.4 Role-pack and isolation tests

- complete manifest parsing, hashes, Spine version, exact animation catalog,
  aliases, and direction policy;
- schema version 1 rejects a second atlas texture page;
- a compatible second fake pack can switch through configuration without code
  changes;
- cross-pack asset mixing is rejected;
- candidate validation/native failure preserves the active pack and destroys
  candidate partial resources only;
- old-playback containment failure aborts the swap, destroys the candidate,
  retains the old package identity without assuming healthy playback, and
  leaves autonomous work stopped with explicit degraded/unknown health;
- successful swap quiesces to semantic `RELAX` with zero velocity, clears
  explicit hold and pending continuation state, invalidates old playback,
  commits the candidate before destroying old resources, confirms candidate
  Relax playback, samples a fresh dwell, and then resumes autonomy;
- no tracked `.skel`, `.atlas`, `.png`, screenshot, or evidence artifact;
- production pet startup and every animation request leave Agent/provider,
  credential, prompt, session, and network modules untouched.

## 13. Acceptance Criteria

This milestone is complete only when:

1. the production launcher remains resident in the tray until explicit exit;
2. Schwarz renders sharply at the current Windows DPR with the approved
   near-full-window scale and foot placement;
3. all six physical animations (`Relax`, `Move`, `Sit`, `Sleep`, `Special`,
   and `Interact`) and all seven logical actions (including both move
   directions) are exercised through exact native playback;
4. walking visibly uses `Move` while the window actually travels in the same
   direction;
5. autonomous behavior is state-dependent and randomized, with no fixed
   periodic playlist;
6. tray/user/Agent callers can explicitly request an available action through
   the one typed gateway;
7. explicit normal actions interrupt autonomous loops, enter explicit hold,
   queue behind protected one-shots when blocked, and never outrank safety or
   shutdown;
8. `Resume Autonomous` is a separate typed mode command that safely returns
   explicit hold to a fresh confirmed `RELAX` dwell;
9. the Schwarz package remains external and read-only;
10. another compatible complete role pack can be described through data and
   selected without renderer or scheduler code changes;
11. all focused unit, integration, Qt, native CTest, static, artifact-scope,
    and Agent-isolation gates pass;
12. a final Windows manual review confirms clarity, animation choice,
    movement, tray persistence, transparency, taskbar placement, and explicit
    action selection.

## 14. Non-goals

This milestone does not:

- implement or fabricate the remaining future 25-action catalog;
- copy Ark-models assets into SJTUClaw;
- mix individual art attachments across skeleton packages;
- reproduce ArkPets' full application, tray, Java classes, or fixed source
  matrix;
- let autonomous behavior override Agent, safety, drag, lifecycle, or motion
  authority;
- add unbounded action queues or infer animation commands from arbitrary text;
- claim visual acceptance before the user completes the final manual review.
