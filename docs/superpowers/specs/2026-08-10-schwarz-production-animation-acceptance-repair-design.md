# Schwarz Production Animation Acceptance Repair Design

**Date:** 2026-08-10
**Status:** Revised after user review, pending final approval

## 1. Purpose

The first Windows manual review of the real Schwarz Spine 3.8 role pack found
five production-path failures:

1. the visible character occupies only a small portion of the `160 x 180`
   logical window and its feet do not appear anchored to the taskbar;
2. `Move Left` translates the window left while the character continues to
   face right, producing an obvious backward walk;
3. all other physical animations also remain right-facing after the semantic
   facing changes to left;
4. a fresh, untouched launch remains on `Relax` for more than 60 seconds and
   never visibly commits another autonomous action;
5. the production pet cannot be dragged, preventing manual validation of the
   fall and landing sequence.

The external assets, hashes, Spine version, six-animation catalog, tray action
bindings, and direct playback of all six physical animations were separately
validated. This repair therefore changes the application integration, not the
Schwarz asset triplet.

This document supplements the frozen 2026-08-09 autonomous-animation design.
Where the two documents conflict on framing, the body-priority decision in
this document supersedes the previous all-effects-uncropped requirement.

## 2. Frozen User Decisions

- Keep the existing `160 x 180` logical pet window.
- Keep the external Schwarz package read-only and outside Git.
- Keep the existing six physical animations and seven typed logical actions.
- Do not require separately authored left-facing animation assets.
- Prefer a near-full-window character body and taskbar-aligned feet over
  preserving every extreme `Special`/`Interact` weapon or effect pixel.
- Keep random, state-dependent autonomy rather than introducing a fixed
  playlist.
- Preserve explicit hold: a user-selected looping action remains selected
  until replacement, mandatory interruption, or `Resume Autonomous`.

## 3. Selected Approach

Repair the existing production seams instead of changing assets or adding
per-animation windows:

1. apply persistent semantic facing in `Spine38PetRenderer`;
2. replace effect-dominated union framing with one immutable body-priority
   transform;
3. let mandatory drag/fall/land motion operate without requiring missing
   Spine drag animations;
4. restore the native playback-event to scheduler commit chain and add a
   bounded liveness rule;
5. retain atomic workspace-boundary containment and direction changes.

The rejected alternatives are:

- authoring left/right and drag-specific Spine animations, which expands the
  asset contract and is unnecessary for this milestone;
- recomputing framing per action or per frame, which would make the character
  visibly resize or pump during transitions;
- adding a second independent random timer, which would create competing
  state sources instead of repairing scheduler authority.

## 4. Persistent Facing and Mirroring

The Schwarz source assets have canonical right-facing geometry. The semantic
`PetFacing` value is the only runtime direction source.

The complete data flow is:

```text
PetMotionModel.facing
    -> PetRenderFrame.intent.facing
    -> PetRendererActionRequest.facing
    -> Spine38PetRenderer scene transform
```

For `RIGHT`, renderer geometry uses the immutable session transform directly.
For `LEFT`, the final logical mesh positions are reflected horizontally about
the logical pet-window center:

```text
x_left = 2 * mirror_axis_x - x_right
mirror_axis_x = logical_window_width / 2
```

Mirroring changes positions only. UV coordinates, triangle winding, draw
order, blend mode, clipping ownership, animation time, and native Track 0 are
unchanged. If the rendering backend requires winding preservation after a
negative transform, the scene builder must preserve the existing visible
front face without changing semantic direction.

Facing applies to every physical animation. After the pet turns left,
`Relax`, `Sit`, `Sleep`, `Special`, and `Interact` remain visually left-facing
until another accepted semantic action changes facing. `Move Left` atomically
combines mirrored geometry, left-facing state, and negative horizontal
velocity; `Move Right` combines canonical geometry, right-facing state, and
positive velocity.

## 5. Body-Priority Immutable Framing

The renderer retains exactly one transform for the role-pack session. It must
not reframe per action, per loop, or per frame.

Window placement and in-window character placement have separate owners:

- workspace containment positions the logical pet window and requires
  `window_bottom == active_workspace_bottom`;
- the renderer transform positions Schwarz inside that window;
- the renderer must never move the logical window into the taskbar merely to
  align the character feet.

Scale calibration is deterministic and uses the real verified samples as
follows:

1. twelve `Relax` poses determine the target body scale. Their body envelope
   is scaled toward `162` logical pixels high, with an allowed visible-height
   range of `153` through `171` pixels;
2. twelve poses from each of `Relax`, `Move`, `Sit`, and `Sleep` validate that
   the principal body is not cropped by the resulting immutable transform;
3. twelve poses from each of `Special` and `Interact` are validation-only.
   They never participate in scale reduction;
4. `Special` and `Interact` must keep the head and torso visible, but extreme
   weapon, attachment, or effect geometry may touch or slightly cross a
   viewport edge;
5. the visible Schwarz foot baseline lies in logical rows `178` through `180`;
6. calibrated `Relax` contains no transparent bottom padding larger than two
   logical pixels;
7. the logical footprint remains stable across DPR `1.0`, `1.25`, `1.5`, and
   `2.0`.

Equivalently, after window placement, the on-screen foot error satisfies:

```text
0 <= active_workspace_bottom - visible_foot_screen_y <= 2
```

The chosen scale and offsets are established once before renderer
publication. Persisted positions and screen changes are clamped so the
logical window bottom, not an internal renderer baseline, equals the active
workspace bottom.

If the body-priority constraints cannot be satisfied for a candidate role
pack, candidate publication fails closed to the existing placeholder. The
renderer must not silently publish the old miniature framing.

## 6. Mandatory Drag, Fall, and Landing

Direct manipulation is a mandatory motion interaction and must not depend on
the role pack providing `Drag`, `Fall`, or `Land` animations.

### 6.1 Drag start

An accepted left-button press while interaction is enabled performs one
transaction:

1. clear explicit hold and all protected continuation state;
2. suspend autonomous scheduling;
3. set horizontal and vertical velocity to zero;
4. contain the current Track 0 playback when containment is healthy;
5. enter semantic `DRAGGING` and begin following the pointer.

If no dedicated drag animation is registered, healthy production rendering
uses confirmed looping `Relax` as the visual fallback. A missing drag
animation must never reject the physical drag transition.

During `DRAGGING`, horizontal position is clamped so that at least a
16-logical-pixel recoverable strip of the pet window remains inside the active
workspace:

```text
workspace_left - (pet_width - 16) <= x <= workspace_right - 16
```

### 6.2 Release and recovery

On left-button release:

1. clear the drag offset;
2. clamp the complete logical window horizontally into the active workspace,
   so `workspace_left <= x <= workspace_right - pet_width`;
3. enter `FALLING` with zero horizontal velocity and the existing bounded
   gravity policy;
4. update the window position from motion physics without autonomous work;
5. contain the fall at the current workspace bottom;
6. enter the landing recovery path;
7. establish and confirm `Relax` playback;
8. sample a fresh `Relax` dwell and re-enter `AUTONOMOUS`.

If playback health is degraded or unknown, velocity remains zero and the
engine stays `SUSPENDED`; it must not resume autonomous motion silently.

## 7. Autonomous Playback Liveness

A fresh healthy production launch must establish `Relax`, confirm playback,
sample a dwell, and enter `AUTONOMOUS` without a tray command. The same
obligation applies after every healthy return to autonomous `Relax`; liveness
is not a one-time startup property.

The only scheduling clock is the monotonic autonomous scheduler clock. Native
loop-boundary events flow through `Spine38AnimationPlayer`, `PetWindow`, and
`PetAnimationEngine`. A proposal changes scheduler state only after the
arbiter accepts it and the semantic/playback/motion transaction commits.

Every healthy eligible autonomous period must satisfy this event cycle:

```text
enter autonomous state
    -> sample one fresh dwell
    -> wait until that deadline and the next valid loop boundary
    -> produce exactly one eligible proposal
    -> commit it after accepted playback, or reschedule after rejection
```

Healthy eligible autonomy also satisfies a bounded liveness rule:

- `STAY` remains a valid randomized outcome;
- after two consecutive eligible `STAY` decisions in the same autonomous
  state, the next eligible draw excludes `STAY` once;
- the destination is still selected randomly from the state-dependent
  non-`STAY` weights;
- no eligible autonomous `Relax` period may continue indefinitely;
- after every healthy return to autonomous `Relax`, at least one non-`Relax`
  action must be committed within 60 seconds of eligible scheduler time;
- rejected or ineligible proposals do not consume the liveness budget;
- explicit hold, protected playback, drag, pause, safety, containment,
  degraded health, and shutdown suspend the liveness deadline rather than
  forcing an action.

Both `Move Left` and `Move Right` have explicit nonzero reachable weights from
autonomous `Relax`. A selected autonomous Move must be able to commit matching
Track 0 `Move` playback, facing, mirroring, and velocity. The 60-second rule
does not require a Move on every period; it guarantees continuing autonomous
activity while the nonzero Move weights preserve occasional walking.

This is bounded randomness, not a playlist. The scheduler may choose different
destinations on different runs and continues using the frozen transition
matrix and dwell ranges.

`Resume Autonomous` retains its existing semantics: establish confirmed
`Relax`, sample a fresh dwell, reset consecutive `STAY` accounting, and begin
a new eligibility window.

## 8. Workspace Boundary Transactions

No Move transaction may place any part of the logical pet window outside the
current workspace.

Containment occurs in the same transaction as motion integration. For right
motion:

```text
x_max = workspace_right - pet_width
x_new = min(x_old + velocity_x * delta_seconds, x_max)
```

Left motion uses the corresponding `max(..., workspace_left)` calculation.
Even when the pet begins one pixel from a boundary and a large delta would
cross it by many pixels, no committed or externally observable frame may
contain an out-of-workspace position.

When an explicit held Move reaches the matching boundary, safety ends the
hold, zeros velocity, and recovers through confirmed `Relax` before autonomy.

When an autonomous Move would cross the matching boundary mid-loop, the
existing exception remains valid:

1. contain position at the workspace edge;
2. stop old velocity;
3. request the opposite semantic Move;
4. atomically commit opposite facing, matching mirrored/canonical rendering,
   opposite velocity, and confirmed `Move` playback;
5. sample a fresh movement dwell and re-enter `AUTONOMOUS` without an
   intermediate visible `Relax`.

If any part of that transaction fails, velocity stays zero and normal
degraded/unknown recovery rules apply.

## 9. Failure Containment

- A renderer failure stops velocity and autonomous scheduling before
  fallback publication.
- A playback callback with a stale generation, token, or boundary index is
  side-effect free.
- A missing optional motion animation uses the defined visual fallback and
  never disables drag physics.
- An invalid body-priority transform prevents candidate publication.
- No recovery path assumes healthy playback after containment failure.
- Shutdown clears pending continuation, cancels autonomous eligibility, stops
  motion, and destroys native resources through the existing controlled exit.

## 10. Test Strategy

Tests are added vertically, one red-green slice at a time, at public seams.

### 10.1 Renderer tests

- `LEFT` and `RIGHT` requests produce horizontally reflected logical scenes;
- `Move Left -> Relax -> Sit -> Sleep -> Special -> Interact` remains `LEFT` at
  every step;
- `Move Right -> Relax -> Sit -> Sleep -> Special -> Interact` remains `RIGHT`
  at every step;
- the immutable transform is reused across state changes;
- real Schwarz alpha bounds meet the approved height and foot-baseline ranges;
- the logical window bottom equals the active workspace bottom while the
  renderer independently keeps visible foot error at no more than two pixels;
- `Special` and `Interact` validation never reduces the scale selected from
  the `Relax` body calibration;
- DPR changes preserve logical bounds and rebuild only physical framebuffer
  resources.

### 10.2 Window and motion tests

- production Track 0 cannot prevent mouse press from entering `DRAGGING`;
- `QTest.mousePress`, `QTest.mouseMove`, and `QTest.mouseRelease` target the
  actual production receiving widget/window and traverse the real Qt event
  chain into `PetWindow` and `PetAnimationEngine`;
- pointer movement updates window position while dragging and retains at least
  the recoverable 16-pixel strip;
- release fully clamps horizontal position before falling begins;
- release enters `FALLING`, gravity advances, and landing establishes Relax;
- dragging clears explicit hold and protected continuation;
- persisted positions and screen changes clamp to the active workspace.

### 10.3 Autonomous tests

- fresh production startup enters eligible autonomous Relax;
- every later return to autonomous Relax samples a fresh dwell and eventually
  reaches a new proposal; the guarantee is tested across repeated cycles;
- native loop boundaries reach the scheduler exactly once;
- `FakeClock` and an injected `FakeRandom` deterministically produce two
  `STAY` draws and prove the next candidate set excludes `STAY`;
- core scheduler tests assert rules and candidate sets rather than a concrete
  Python seeded sequence;
- a seeded real integration smoke may additionally demonstrate continuing
  non-Relax execution inside the eligible 60-second bounds;
- both left and right Move are reachable from autonomous Relax using injected
  draws, and each commits matching playback, facing, mirroring, and velocity;
- explicit hold and suspended modes do not consume the liveness budget;
- accepted proposals commit scheduler, semantic, playback, facing, and
  velocity state atomically.

### 10.4 Boundary and integration tests

- a real Schwarz end-to-end Move test observes Track 0 `Move`, semantic
  facing, rendered mirrored/canonical scene, velocity sign, and actual window
  x displacement for both directions;
- left and right Move stop at their respective workspace limits;
- starting one pixel from either boundary with high velocity and a large
  `delta_seconds` never publishes an overshoot position;
- explicit boundary containment recovers through Relax;
- autonomous mid-loop turns commit the opposite Move without Relax;
- a failed turn leaves zero velocity and stopped autonomy;
- the real external Schwarz catalog, hashes, filters, and Agent isolation
  remain unchanged.

## 11. Acceptance Criteria

The repair is complete only when:

1. the logical pet-window bottom equals the active workspace bottom;
2. Schwarz occupies the approved near-full-window body scale, its visible foot
   error above the workspace bottom is no more than two logical pixels, and
   calibrated Relax has no larger transparent bottom padding;
3. both left-facing and right-facing multi-animation sequences preserve their
   semantic facing through all six physical animations;
4. the real Schwarz end-to-end Move transaction combines Track 0 `Move`,
   matching facing, mirrored/canonical rendering, velocity sign, and actual
   window displacement in both directions;
5. every healthy eligible return to autonomous Relax commits a non-Relax
   action within 60 seconds of eligible scheduler time, not only after launch;
6. both Move directions remain reachable autonomous destinations and commit
   their complete movement transactions under injected RNG control;
7. explicit looping actions still hold until replacement, mandatory
   interruption, or `Resume Autonomous`;
8. real Qt mouse events can drag the production pet, release it, observe
   falling, and safely recover after landing;
9. drag release restores a fully recoverable horizontal position;
10. explicit Move never exposes an out-of-workspace position, including a
    large-delta overshoot attempt;
11. autonomous boundary turns follow the confirmed opposite-Move exception;
12. renderer or playback failure leaves velocity zero and autonomy stopped;
13. focused unit, Qt, native, integration, artifact-scope, and Agent-isolation
    gates pass;
14. the user repeats Windows manual acceptance at the target DPR values.

## 12. Non-Goals

This repair does not:

- edit, copy, or redistribute the Schwarz assets;
- author new left-facing, drag, fall, or landing Spine animations;
- add per-frame or per-action reframing;
- replace weighted autonomy with a deterministic playlist;
- change protected one-shot or explicit-hold arbitration;
- claim final visual acceptance before the user repeats the Windows review.
