# Spine Animation Production Prompt Design

Date: 2026-08-06

## Objective

Produce one final desktop-operation prompt that directs Codex to finish the
SJTUClaw character's Spine animation assets in a serial, auditable workflow.
This scope ends after Spine Editor asset validation. It does not export runtime
data, modify SJTUClaw code, or integrate a Spine Runtime.

The deliverable contains the 24 originally required animation names plus the
independent `breathing` overlay, for 25 animation assets total:

`idle`, `breathing`, `blink`, `walk_left`, `walk_right`, `run_left`,
`run_right`, `sit_down`, `sit_idle`, `sleep_start`, `sleep_loop`, `sleep_end`,
`wave`, `happy`, `think`, `read`, `type`, `remind`, `confused`, `angry`,
`drag_start`, `drag_loop`, `drag_end`, `landing`, and `return_idle`.

## Authoritative input and isolation

The accepted Stage 3 project is the only production baseline for the next
stage:

- project: `D:\Spine\test\stage3_idle_20260806_182345\stage3_idle_working.spine`
- SHA-256: `F3CB4A733199148F5EB852EBC7B788F4F5117C601531120ED5A4793DF5857463`

The project path and SHA-256 above are one atomic evidence pair. They were
reverified together after the path-recording defect was diagnosed. Never take a
directory from the clean reconstruction baseline and combine it with this
working project's filename or hash.

The earlier `EECEDEF...`, clean reconstruction `5BC267...`, and accidental
save `25E4D16...` are not valid production inputs for the 25-animation build.

Before any Editor input, Codex must verify the baseline hash and create a new
timestamped directory under `D:\Spine\test`. Every stage operates on a copy in
that directory. The accepted input of a stage remains immutable. No file may
be overwritten. New screenshots, manifests, reports, and `.spine` files may be
written only under the current timestamped evidence directory.

The original `.skel`, `.atlas`, and `.png` files are read-only evidence. No
character asset, screenshot, Spine project, export, or generated texture may
be written to `D:\SJTUClaw`.

## External reference boundary

Only mechanisms may be borrowed from the researched projects:

- Spine Runtime 3.8: ordered tracks, sparse higher-track timelines, mixing,
  queueing, empty-animation mix-out, listeners, events, skins, and strict
  Editor/runtime version matching.
- VPet: `Start -> Loop -> End -> Normal`, random idle selection, explicit sleep
  lifecycle, drag lifecycle, and fallback behavior.
- Shimeji-Desktop: separation of behavior selection from action playback and
  the `Dragged -> Thrown/Fall -> Landing` interaction chain.
- OpenPets: reminder scheduling and semantic Agent reactions that remain
  separate from animation resources.

No third-party character image, animation frame, Spine project, audio file,
pet package, or derived art asset may be downloaded, imported, traced, or
copied. Spine Runtimes use the dedicated Spine Runtimes License rather than a
permissive open-source license. VPet's Apache-2.0 code license does not grant a
blanket right to its bundled animation assets. Shimeji contains multiple
license texts, and OpenPets code is MIT; none of those facts authorize copying
their pet artwork.

## Serial production stages

### Stage 0: freeze and audit

Verify the accepted baseline hash, copy it to a timestamped stage directory,
record Editor version/FPS/Skin/setup attachments/Draw Order/constraints, and
confirm that the existing `idle` still passes its saved Stage 3 acceptance
criteria. Stop on any mismatch.

### Stage 1: overlays

Create and validate:

- `breathing`: sparse Track 1 candidate containing only observed torso, waist,
  chest, head, and strictly necessary secondary-motion properties extracted
  from `Relax`; no eye, attachment, color, Draw Order, root, foot, or whole-body
  scale timelines.
- `blink`: sparse Track 2 candidate extracted from the observed blink in
  `Relax`; only eyelid/eye attachment or eye color timelines that are directly
  evidenced may be retained.

Test `idle`, `idle + breathing`, `idle + blink`, and
`idle + breathing + blink`. If the Editor cannot prove multi-track composition,
record that limitation rather than claiming a pass.

### Stage 2: locomotion

Create `walk_left`, `walk_right`, `run_left`, and `run_right`. Select one
direction strategy only after auditing asymmetric clothes, weapons, text,
constraints, collision/bounding attachments, and Draw Order. A mirrored pair
must be separately accepted. Window movement remains program-driven, so the
skeleton must not accumulate root translation.

Walk and run require distinct silhouettes, contact timing, stride, vertical
bounce, and tempo. Run must not be a simple time-scaled walk.

### Stage 3: seated and sleeping lifecycles

Create and validate:

- `sit_down -> sit_idle -> return_idle`
- `sleep_start -> sleep_loop -> sleep_end -> return_idle`

Entry and exit poses must match exactly across adjacent animations. Only the
loop portions loop. Start and end animations are one-shot assets.

### Stage 4: drag and landing lifecycle

Create and validate:

`drag_start -> drag_loop -> drag_end -> landing -> return_idle`

The Spine animations express pose and secondary motion only. Mouse-following,
release velocity, gravity, window position, and landing detection remain
program responsibilities. Test slow release, fast release, interrupted drag,
and direct return without landing as semantic cases, without implementing the
program state machine in this stage.

### Stage 5: Agent and reminder states

Create `think`, `read`, `type`, and `remind`. `think`, `read`, and `type` may
loop while their semantic state is active; `remind` is a high-priority
one-shot. No timer, prompt text, secret, notification payload, or Agent state is
stored in the Spine project.

### Stage 6: performance and emotion

Create `wave`, `happy`, `confused`, and `angry` as one-shot animations with a
defined exit pose compatible with `return_idle` or `idle`. Their expressions
must be checked against `blink` property ownership so a higher track cannot
silently overwrite incompatible eye timelines.

### Stage 7: final asset audit

Validate all 25 animations after saving and reopening the project. Audit exact
names, duration, loop intent, first/last pose, curves, foot baseline, root
transform, attachments, Slot color, Draw Order, constraints, Mesh/Deform,
clipping, direction behavior, and cross-animation handoff poses. Do not export
JSON, SKEL, Atlas, or PNG in this scope.

## Per-animation transaction

Each animation is one transaction:

1. Record the current accepted project hash and copy it to a new nonexisting
   checkpoint file.
2. Inspect source timelines before copying anything.
3. List the exact bones, Slots, attachments, colors, Draw Order, Deform, and
   constraint properties authorized for the target.
4. Create or modify only the named target animation.
5. Remove unrelated inherited timelines; never key every property globally.
6. Verify duration, loop intent, key values, curves, first/last pose, feet,
   root, attachments, Draw Order, Mesh/Deform, and visible clipping.
7. Save to a new file, close, reopen, and repeat the visual and timeline audit.
8. Compute the output SHA-256 and append an evidence record.
9. Promote the output as the next immutable input only if every mandatory
   check passes. Otherwise stop and retain both input and failed output.

No intermediate or automatic backup becomes a production baseline solely
because it is newer.

## Animation and track contract

- Track 0 assets: all exclusive full-body states and transitions.
- Track 1 asset: `breathing` only, using sparse directly observed properties.
- Track 2 asset: `blink` only, using sparse directly observed eye properties.
- Emotion or facial timelines require a written property-conflict matrix with
  `blink`; track number alone does not resolve an ambiguous ownership conflict.
- Looping assets must have continuous first/last keyed values, attachment
  state, Draw Order, Deform, and constraint state.
- One-shot assets must have a stable final pose and an explicit semantic next
  animation.
- `start -> loop -> end -> return_idle` is the standard lifecycle.
- No Runtime loop flag is encoded by the Editor playback-loop button; the
  report must distinguish Editor preview settings from future Runtime calls.

## Desktop-operation rules

Codex is authorized to control the Windows desktop for this production task,
but only within these boundaries:

- use Spine Editor 3.8.75 Professional and the isolated stage copy;
- do not operate authentication, activation, registry, crack, security, or
  system-settings interfaces;
- do not save over an existing file;
- do not access or modify the original Runtime Data directory;
- do not touch unrelated applications or browser sessions;
- take a fresh window observation before each coordinate action;
- stop on an unexpected modal, path, version, Skin, attachment, or hash;
- never dismiss a warning whose effect is not understood;
- do not use UI automation to run terminal commands.

## Stop conditions

Stop immediately and report evidence if any of the following occurs:

- baseline or promoted checkpoint hash mismatch;
- Editor version is not 3.8.75 or the project cannot be safely opened;
- Skin/setup appearance differs from the accepted baseline;
- an operation would require modifying Atlas, PNG, Mesh topology, weights, or
  original Runtime Data;
- a required source property cannot be directly identified;
- an animation cannot be saved to a new nonexisting file;
- a save/reopen audit changes appearance, timelines, or animation names;
- a third-party asset would need to be copied;
- Spine or desktop control becomes uncertain or interrupted.

## Final report contract

The prompt must require one final report containing:

- complete checkpoint lineage and SHA-256 values;
- all files created during the run;
- Editor version, FPS, reconstruction warning, Skin, and setup state;
- a 25-animation table with type, source, duration, frames, loop intent, Track,
  mix recommendation, next state, and acceptance result;
- an exact per-animation timeline inventory;
- all keyed bones, Slots, attachment/color/Draw Order/Deform/constraint keys,
  values, frame positions, and curves;
- direction strategy and asymmetric-content test results;
- start/loop/end handoff results;
- overlay property-conflict matrix;
- save/reopen, three-loop, foot, root, Mesh/Deform, clipping, attachment, and
  Draw Order results;
- confirmed facts, unconfirmed facts, deviations, and stop events;
- explicit confirmation that original Runtime Data, Atlas/PNG, SJTUClaw, and
  third-party assets were not modified or copied;
- explicit statement that Runtime export and program playback remain outside
  this scope.

After the report, Codex must pause and wait for user confirmation. It must not
export runtime data or begin program integration.

## Acceptance of the prompt design

The final prompt is acceptable only if it preserves the serial checkpoint
model, names all 25 assets, separates Editor validation from Runtime
validation, enforces sparse overlays, prevents third-party asset copying, and
provides deterministic stop conditions rather than encouraging guesses.
