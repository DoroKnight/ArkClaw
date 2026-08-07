# ArkPets Action Sequence Reuse Design

**Date:** 2026-08-07  
**Status:** Approved in conversation; pending document review  
**Scope:** GPL-3.0-only migration and code-level reuse of selected ArkPets
animation sequencing mechanisms

## 1. Objective

Adapt selected GPL-3.0 ArkPets animation sequencing mechanisms into
SJTUClaw's existing Python desktop-pet architecture without changing the
locally deployed Agent runtime.

The selected reuse scope is limited to the ideas and code structure embodied
by ArkPets `AnimData`, `AnimComposer`, animation step chaining, strict action
interruption rules, completion-driven advancement, and the
`Begin -> Loop -> End` lifecycle. The implementation will be rewritten in
Python and integrated as an independent application-layer module.

This work does not reduce or redesign the approved list of 25 Spine
animations. Spine production remains paused while this mechanism and its
licensing boundary are prepared.

## 2. Decisions

The following decisions are approved:

1. Use the independent action-sequence module approach.
2. Migrate the whole SJTUClaw source distribution from `Proprietary` to
   `GPL-3.0-only`.
3. Attribute the reused implementation to ArkPets and Harry Huang.
4. Do not copy ArkPets character images, animation frames, Spine projects,
   audio, pet packs, or other art assets.
5. Do not port the ArkPets stochastic behavior matrix or broad behavior
   subsystem in this change.
6. Do not port ArkPets mobility/root-motion ownership. Window movement,
   dragging, gravity, collision, and landing remain owned by
   `PetMotionModel`.
7. Do not alter the local Agent's prompts, Provider activation, credentials,
   sessions, networking, window lifecycle, or shutdown behavior.
8. Do not modify the unrelated in-progress OpenGL Mesh worktree changes.

## 3. Existing Architecture

SJTUClaw already separates local pet concerns:

- `pet_state.py` owns lifecycle, exclusive motion, behavior overlays, and
  transition validation.
- `pet_motion.py` owns window position, walking, dragging, gravity, collision,
  landing, and workspace constraints.
- `pet_animation.py` owns deterministic local animation timing and emits a
  framework-independent render intent.
- `pet_window.py` owns Qt input and presentation wiring.
- `PetApplicationCoordinator`, `MainWindow`, and `QtRuntimeBridge` own Agent
  window visibility and runtime shutdown coordination.

The new sequencing module must fit this separation instead of introducing a
second application architecture.

## 4. Architecture and Agent Isolation

The new dependency direction is:

```text
pet_action_sequence.py
        |
        v
pet_animation.py
        |
        v
pet_window.py -> renderer
```

The existing Agent path remains independent:

```text
MainWindow -> QtRuntimeBridge -> AgentLoop -> Provider
```

No new dependency is allowed between these paths. In particular,
`pet_action_sequence.py` must remain pure Python and framework-independent. It
must not import or receive an `AgentLoop`, `QtRuntimeBridge`, Provider,
`SecretStore`, prompt, continuation, session model, credential, or response
text.

Action steps may contain only fixed animation identifiers and local playback
metadata. Existing content-free entry points such as
`request_thinking_animation()` and `request_reminder_animation()` remain
content-free. Agent output must not be inserted into an animation step or
diagnostic result.

The Agent window's open, hide, close, and safe-shutdown flows are out of scope
and must remain behaviorally unchanged.

## 5. Data Model

The ArkPets concepts map to SJTUClaw as follows:

| ArkPets concept | SJTUClaw adaptation | Purpose |
| --- | --- | --- |
| `AnimData.animClip` | `PetActionStep.animation_name` | Exact case-sensitive Spine animation name |
| `animNext` / `join()` | `next_step` / `then()` | Build a completion-driven action chain |
| `isLoop` | `loop` | Mark a continuously repeating step |
| `isStrict` | `strict` | Reject ordinary interruption while active |
| `mobility` | Not ported | Preserve `PetMotionModel` ownership |
| `AnimComposer.offer()` | `PetActionComposer.offer()` | Accept or reject a requested sequence |
| Spine `complete` listener | `complete(animation_name)` | Advance only a matching current step |

The new module contains:

- `PetActionName`: the exact approved set of 25 animation identifiers.
- `PetActionStep`: an immutable animation node.
- `PetActionSequence`: an immutable chain of one or more steps.
- `PetActionComposer`: the Track 0 sequencing state and transition logic.
- Small builders for the approved standard lifecycle chains.

`PetActionName` must contain exactly:

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

## 6. Sequencing Mechanism

The approved full-body lifecycle chains are:

```text
sit_down -> sit_idle -> return_idle -> idle
sleep_start -> sleep_loop -> sleep_end -> return_idle -> idle
drag_start -> drag_loop -> drag_end -> landing -> return_idle -> idle
```

The rules are:

1. A `start` step is a one-shot and advances on a matching completion event.
2. A `loop` step does not end because of a guessed fixed timer.
3. An exit request while looping records a pending exit.
4. The next matching loop-completion boundary advances to `end`.
5. `end` advances to `return_idle`.
6. `return_idle` advances to `idle`.
7. A completion callback whose animation name does not match the current step
   is stale and must be ignored.
8. An invalid or missing sequence produces a fixed safe result and falls back
   to `idle` without propagating an exception into Qt or the Agent runtime.

This adapts the ArkPets lifecycle for the approved SJTUClaw animation names.
It intentionally does not copy ArkPets animation-name recognition rules for
third-party character assets.

## 7. Strict Actions and Safety Overrides

One-shot performances such as `wave`, `happy`, `confused`, and `angry` may use
strict playback. While strict playback is active, ordinary or lower-priority
requests cannot replace it.

Strict playback is not a process-safety lock. Closing, pausing, safe shutdown,
direct drag input, and motion safety recovery may forcibly clear the composer.
The existing lifecycle and motion state priorities remain authoritative.

An action request is transactional: first validate the current layered state
and ask the composer whether it accepts the action, then commit the state
change. A rejected offer must not leave the state machine and playback intent
out of sync.

## 8. Track Ownership

- Track 0 contains full-body states, transitions, and performances and is the
  only track managed by `PetActionComposer`.
- Track 1 contains `breathing` and remains independent.
- Track 2 contains `blink` and remains independent.

`breathing` and `blink` remain members of the exact 25-name catalog but are not
inserted into Track 0 action chains. Their current local overlay scheduling is
preserved.

## 9. Engineering Integration

### 9.1 New module

Add:

```text
src/sjtuclaw/application/pet_action_sequence.py
```

This module contains all reused and adapted sequencing behavior. It includes
an SPDX identifier and a concise adaptation notice pointing to ArkPets and the
specific original Java sources.

### 9.2 Existing animation engine

Update `pet_animation.py` to own one composer while preserving existing public
method names and call signatures. `PetAnimationIntent` may gain a Track 0
animation-name field while retaining `base_action`, so current renderers and
callers remain compatible.

The existing placeholder renderer may ignore the new symbolic animation name
until Spine Runtime integration is separately approved. Therefore this work
does not claim that a Spine Runtime, Track mix, or completion callback is
already operational.

### 9.3 Existing state and motion models

`pet_state.py` remains the authority for lifecycle and physical behavior.
`pet_motion.py` remains the authority for window position and physics. The
composer is a playback plan, not a replacement business state machine.

### 9.4 Qt boundary

`pet_window.py` retains its existing content-free request methods. If a future
Spine renderer supplies completion events, it must send only the completed
animation identifier through a narrow interface. It must not expose runtime
objects, file paths, or Agent content to the application model.

## 10. Error Handling

The sequencing boundary uses fixed, non-sensitive outcomes:

- `ACCEPTED`
- `REJECTED_STRICT`
- `REJECTED_DUPLICATE`
- `STALE_COMPLETION`
- `INVALID_SEQUENCE`
- `FALLBACK_IDLE`

No result includes a prompt, response, credential, Provider continuation,
external asset path, or raw exception. Unexpected internal failures are
contained at the local pet boundary and converted to a safe idle fallback.

## 11. License Migration and Attribution

The implementation phase will:

1. Add a root `LICENSE` containing the complete GNU General Public License
   version 3 text.
2. Change package metadata from `Proprietary` to `GPL-3.0-only`.
3. Add `THIRD_PARTY_NOTICES.md` recording:
   - ArkPets project and repository URL;
   - Harry Huang as the original author identified by the reused source;
   - GPL-3.0 as the original license;
   - the precise Java files used as adaptation sources;
   - that the implementation was rewritten and modified for Python and
     SJTUClaw's existing state architecture;
   - the intentional deviations, including omission of mobility and random
     behavior logic;
   - the absence of copied character or art assets.
4. Add a README license and third-party asset-boundary section.
5. Add SPDX and provenance comments to the new adapted source module.

The adaptation sources are limited to the relevant code in:

```text
core/src/cn/harryh/arkpets/animations/AnimData.java
core/src/cn/harryh/arkpets/animations/AnimComposer.java
core/src/cn/harryh/arkpets/animations/AnimClipGroup.java
core/src/cn/harryh/arkpets/animations/AnimClip.java
```

The implementation will not vendor the ArkPets Java source tree.

GPL-3.0-only changes distribution obligations but does not alter local Agent
runtime behavior. Third-party art remains governed by its own authorization
and is not relicensed merely because the surrounding source code uses GPL.

## 12. Testing

### 12.1 Unit tests

Tests will verify:

1. Action steps and sequences are immutable.
2. `then()` returns a correctly ordered chain without mutating the source.
3. The exact 25 animation names are complete, case-sensitive, and unique.
4. Ordinary actions can be replaced when allowed.
5. Strict actions reject ordinary interruption.
6. Safety transitions and drag input can forcibly clear strict playback.
7. One-shot completion advances exactly once.
8. A pending loop exit advances at a matching loop boundary.
9. `end -> return_idle -> idle` order is exact.
10. Stale completion callbacks do not advance the current sequence.
11. Invalid sequences safely fall back without affecting the Qt event loop.
12. `breathing` and `blink` never enter the Track 0 queue.

### 12.2 Integration regression tests

Tests will preserve existing behavior for walking, thinking, reminding,
dragging, falling, landing, pause, resume, close, and placeholder rendering.

Agent isolation tests will verify:

- pet startup does not activate a Provider;
- pet startup does not read a `SecretStore`;
- pet startup does not access an external network;
- closing the Agent window still hides it without stopping the pet runtime;
- safe exit still waits for `RuntimeThread` shutdown;
- animation failures neither close, restart, nor wake the Agent.

Existing unit and Qt regression tests must remain green. An Agent regression
must be fixed at the pet/action boundary; the implementation must not alter
Agent code merely to bypass a failing test.

### 12.3 License audit

The audit will verify that:

- the complete GPLv3 license exists at the repository root;
- package metadata says `GPL-3.0-only`;
- README and third-party notices agree;
- ArkPets provenance, original author, source files, and modifications are
  recorded;
- no ArkPets or Arknights character image, animation frame, Spine project,
  audio, or pet pack was added.

## 13. Completion Boundary

Completion of this change means only:

- the selected ArkPets sequencing mechanism has been adapted into the existing
  Python architecture;
- SJTUClaw source licensing and provenance records have been migrated;
- relevant unit, Qt, Agent-isolation, and license checks pass.

It does not mean that Spine Runtime export, Track composition, programmatic
Spine playback, event callbacks, or the remaining Spine animation production
has been completed. Those activities remain paused pending their own approved
execution steps.
