# ArkPets Action Sequence Reuse Design

**Date:** 2026-08-07  
**Status:** Revised after architecture review; pending document re-review
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
   physical animation name, and expected step all match the active playback.
6. After every handled event, semantic state and active logical animation must
   satisfy an explicit compatibility table. For example, `dragging` may be
   paired only with `drag_start` or `drag_loop`, never `sleep_loop`.
7. If playback fails, semantic state remains authoritative. Playback is
   cleared and reset to a state-derived safe visual fallback; Agent state is
   never changed as recovery.
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

An immutable description only. It contains ordered `PetActionStep` values and
has no queue, current index, completion handler, renderer, state machine, or
interruption policy.

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

- compare the incoming and active interruption classes;
- reject a duplicate request;
- reject an equal- or lower-priority request when the active request is
  protected;
- select the permitted cancellation mode for an accepted replacement.

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
    def play(self, request: PlaybackRequest) -> PlaybackToken: ...
    def clear(self, track: int, mix_seconds: float) -> None: ...
```

The current placeholder renderer may implement a symbolic adapter that
preserves existing behavior. A future Spine adapter may implement the same
protocol without changing state, arbitration, or sequence logic.

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

`PetAnimationEngine.handle_event()` is the sole mutation entry point for an
event that may affect both semantic state and Track 0 playback.

For each event, in one GUI-thread turn:

1. Ask `PetLayeredStateMachine` to validate and produce a proposed semantic
   transition without exposing a renderer object.
2. Derive the required logical action request from that proposal.
3. Ask `AnimationRegistry` and `PetTrack0Controller` to preflight the binding,
   interruption class, cancellation mode, and sequence.
4. If preflight rejects, do not commit the semantic transition unless the
   state transition is independently mandatory for safety. A normal rejected
   action leaves both layers unchanged.
5. If accepted, commit the semantic transition, invalidate the prior playback
   generation, and execute the returned `clear`/`play` directive.
6. If `AnimationPlayer` raises or rejects the directive, contain the error,
   attempt an immediate Track 0 clear, reset the runner, and select a
   state-derived safe visual intent. Do not roll back a committed safety or
   user-interaction state merely to preserve an old animation.
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
`USER_INTERACTION` outranks the active action. The same transaction commits
`dragging`, invalidates and clears the old generation, then plays
`drag_start`. A delayed `drag_end` completion is ignored, so the system cannot
settle into `idle` while displaying `drag_loop`.

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

A higher class may interrupt a lower class. Equal classes are rejected while
the active action is protected unless the request is an explicitly permitted
continuation of that same sequence. Consequently, a strict `wave` rejects
`happy` and normal actions, but never blocks shutdown, falling recovery, or a
new direct drag.

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
RESET_TO_IDLE
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
- `RESET_TO_IDLE`: invalidate and clear, reset runner state, then request
  logical `idle` only when lifecycle state is active and the registry/player
  are healthy enough to accept it.

The public operations are distinct:

- `PetTrack0Controller.cancel(reason, mode, replacement=None)` applies policy
  and returns a fixed outcome.
- `PetTrack0Controller.clear(reason)` is an unconditional immediate renderer
  clear reserved for shutdown, pause, and failure containment.
- `PetSequenceRunner.reset()` is internal state cleanup only and has no
  renderer side effect.

The required mapping is:

| Situation | Mode | Follow-up |
| --- | --- | --- |
| shutdown | `IMMEDIATE_CLEAR` | no idle |
| pause | `IMMEDIATE_CLEAR` | no idle until resume |
| new drag | `REPLACE` | `drag_start` |
| fall/collision recovery | `REPLACE` | state-derived safety action |
| normal request to leave a loop | `GRACEFUL_EXIT` | declared end chain |
| renderer failure or callback timeout | `RESET_TO_IDLE` | only if lifecycle is active |

## 8. Sequence Semantics

`PetActionStep` is immutable and contains only:

- logical `PetActionName`;
- loop intent;
- interruption class/protection metadata;
- declared next-step relation;
- non-sensitive playback metadata such as speed and mix suggestion when
  explicitly supported.

It contains no physical resource name, renderer, callback, state machine,
position, Agent content, or mutable queue.

The approved full-body lifecycle chains are:

```text
sit_down -> sit_idle -> return_idle -> idle
sleep_start -> sleep_loop -> sleep_end -> return_idle -> idle
drag_start -> drag_loop -> drag_end -> landing -> return_idle -> idle
```

The sequencing rules are:

1. A start step is one-shot and advances on a matching completion event.
2. A loop never exits because of a guessed normal-playback timer.
3. A graceful exit request records a pending exit.
4. The next matching loop boundary advances to the declared end step.
5. End advances to `return_idle`, then to `idle`.
6. A duplicate completion advances at most once.
7. A stale-generation callback is ignored even if its animation name matches.
8. A missing callback is handled only by the failure watchdog in section 10,
   not by ordinary sequence timing.
9. An invalid sequence is rejected during preflight and cannot partially
   replace the active state or playback.

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

Normal advancement remains completion-driven. A watchdog exists only to
contain a failed player/callback path. It uses duration and capability metadata
reported by the active player/registry plus a bounded tolerance; it must not
guess an animation duration from a hard-coded timer.

For a one-shot, absence of the expected callback by the verified deadline
produces `CALLBACK_TIMEOUT`. For a loop, the watchdog applies only after a
graceful exit is pending or when the player reports lost playback liveness.
Recovery invalidates the generation before any fallback request.

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
FALLBACK_IDLE
CLEARED
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
2. `then()` returns ordered data without mutating its source;
3. the logical catalog contains exactly 25 unique, case-sensitive names;
4. registry identity mapping, alias mapping, missing binding, duplicate
   binding, and case mismatch behavior;
5. the arbiter alone implements the total priority order and equal-priority
   protection;
6. the runner alone implements current step, one-shot completion, loop pending
   exit, duplicate completion suppression, and reset;
7. controller `cancel`, `clear`, and runner `reset` have the exact distinct
   side effects defined in section 7;
8. `breathing` and `blink` cannot enter Track 0;
9. invalid sequences are rejected before state or player mutation.

### 13.2 Deterministic interleaving tests

Although mutation is GUI-thread-owned, logical concurrency is tested by
controlling event order:

1. old completion then new request;
2. new request then old completion;
3. completion queued from a renderer thread while a drag request is pending;
4. duplicate completion before and after replacement;
5. callback with correct name but stale generation;
6. callback with correct generation but wrong physical binding;
7. graceful loop exit racing with a higher-priority replacement.

Every interleaving asserts both runner state and semantic-state/action
compatibility. In particular, `dragging + sleep_loop`, `sleeping + drag_loop`,
and inactive lifecycle plus `idle` are forbidden combinations.

### 13.3 Player failure tests

A fake player exercises:

- exception or rejection from `play`;
- exception from `clear`;
- missing one-shot completion;
- lost loop liveness;
- stale callback after failure recovery;
- failure while attempting fallback idle.

Each failure must leave `PetState` valid, invalidate the old generation, avoid
uncaught Qt exceptions, and leave the Agent runtime untouched.

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
- state-to-animation ownership, interruption, cancellation, stale callback,
  and failure recovery protocols are tested;
- the GPL audit passed before any source-license migration;
- relevant unit, Qt, Agent-isolation, license, and asset checks pass.

It does not mean that Spine Runtime export, Track composition, programmatic
Spine playback, event callbacks, remaining Spine animation production, or
Agent program integration has been completed. Those activities remain paused
pending their own approved execution steps.
