# Spine 25-Animation Production Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Do not use parallel subagents for Spine Editor operations because every task mutates one ordered GUI project lineage.

**Goal:** Complete and audit 25 named Spine animation assets in isolated copies without modifying original Runtime Data, SJTUClaw code, texture assets, rig topology, or weights.

**Architecture:** Use one immutable SHA-256-identified input and a serial chain of timestamped `.spine` checkpoints under `D:\Spine\test`. Each animation is a transaction: inspect source timelines, whitelist properties, edit one target, save to a new path, reopen, verify, hash, and promote only after acceptance. Track 0 contains exclusive body states, Track 1 is the sparse `breathing` overlay, and Track 2 is the sparse `blink` overlay.

**Tech Stack:** Windows 11, Spine 3.8.75 Professional, Codex Computer Use, SHA-256 filesystem evidence, existing reconstructed Spine project.

## Global Constraints

- Accepted input project: `D:\Spine\test\stage3_idle_rebuild_20260806_145235\workspace\stage3_idle_working.spine`.
- Accepted input SHA-256: `F3CB4A733199148F5EB852EBC7B788F4F5117C601531120ED5A4793DF5857463`.
- The `EECEDEF...`, `5BC267...`, and `25E4D16...` files are not production inputs.
- At the start of Task 1, capture the actual local start time in `yyyyMMdd_HHmmss` format as the immutable run identifier `RUN_ID`.
- All new files must be created under `D:\Spine\test\stage4_all_animations_RUN_ID`, replacing `RUN_ID` once with the captured value and using that exact directory for the whole run.
- Never overwrite a file. Every accepted animation produces a new numbered checkpoint.
- Do not modify or write into `D:\ark-model\Ark-Models\models\340_shwaz_striker#1`.
- Do not write character assets, screenshots, exports, or Spine projects into `D:\SJTUClaw`.
- Do not export JSON, SKEL, Atlas, PNG, video, or Runtime packages in this plan.
- Do not change Setup Pose, Atlas, PNG, Skin definitions, attachments, Draw Order defaults, Mesh topology, weights, IK/Transform/Path constraints, or project FPS.
- Do not import or copy third-party character art, animation frames, Spine projects, audio, or pet packages.
- The reconstructed project may lack Nonessential Mesh internal edges; do not attempt to repair them.
- Use Spine 3.8.75 Professional only. Stop if the version, license availability, Skin, appearance, FPS, or baseline hash differs.
- Use Computer Use for GUI actions, take a fresh observation before every coordinate action, and perform only one input action before refreshing state.
- Do not use UI automation to operate a terminal, authentication, activation, registry, security, system settings, unrelated applications, or browser sessions.
- When a required property, source pose, attachment, or warning cannot be identified directly, stop and report; never guess.

---

### Task 1: Freeze the accepted project and establish the evidence chain

**Files:**
- Read: `D:\Spine\test\stage3_idle_rebuild_20260806_145235\workspace\stage3_idle_working.spine`
- Create: `D:\Spine\test\stage4_all_animations_RUN_ID\00_input.spine`
- Create: `D:\Spine\test\stage4_all_animations_RUN_ID\production_manifest.md`

**Interfaces:**
- Consumes: accepted Stage 3 project with SHA-256 `F3CB4A...57463`.
- Produces: immutable `00_input.spine`, evidence manifest, Editor/FPS/Skin/setup inventory, and confirmed existing `idle`.

- [ ] Verify the accepted project SHA-256 exactly matches the full hash in Global Constraints.
- [ ] Create the nonexisting timestamped production directory and copy the accepted project to `00_input.spine`.
- [ ] Verify the copied hash is identical before opening it.
- [ ] Open only `00_input.spine` in Spine 3.8.75 Professional.
- [ ] Record FPS, selected Skin, setup-visible attachments, Skeleton scale/orientation, foot baseline, Draw Order, Slot blend modes, constraints, animation names, and the Nonessential warning.
- [ ] Revalidate the existing `idle` at frames 0, 30, and 60 and across three Editor-preview loops.
- [ ] Save no changes to `00_input.spine`; close it after the audit.
- [ ] Append the input path, hash, metadata, and audit outcome to `production_manifest.md`.

### Task 2: Create the sparse `breathing` overlay

**Files:**
- Read: `00_input.spine`
- Create: `01_breathing.spine`

**Interfaces:**
- Consumes: accepted `idle`, `Relax`, and directly observed torso/head secondary-motion timelines.
- Produces: five-second `breathing` loop candidate for future Track 1.

- [ ] Copy `00_input.spine` to the nonexisting `01_breathing.spine` and verify the copied input hash.
- [ ] Inspect all `Relax` timelines and record the exact changing bones, Slots, attachments, colors, Draw Order, Deform, and constraints before copying any key.
- [ ] Create lowercase animation `breathing`, 150 frames at the existing 30 FPS.
- [ ] Copy only directly observed low-amplitude breathing motion on `F_Hip`, `F_Waist`, `F_Chest`, head controls, and strictly necessary hair/tail follow bones.
- [ ] Remove every eye, eyelid, eye attachment, Slot color, attachment switch, Draw Order, Deform, root, foot, whole-character scale, and unrelated secondary-motion timeline.
- [ ] Keep root translation/rotation/scale and both feet unchanged.
- [ ] Make frames 0 and 150 identical for every keyed property and use restrained Bezier easing without overshoot.
- [ ] Compare frames 0, 75, and 150; play three loops and inspect feet, silhouette, attachments, clipping, Mesh deformation, and amplitude.
- [ ] Save, close, reopen `01_breathing.spine`, repeat the timeline whitelist and visual audit, compute SHA-256, and promote only on pass.

### Task 3: Create the sparse `blink` overlay

**Files:**
- Read: accepted `01_breathing.spine`
- Create: `02_blink.spine`

**Interfaces:**
- Consumes: the observed blink in `Relax` around source frames 10–20.
- Produces: independent short `blink` candidate for future Track 2.

- [ ] Copy the accepted checkpoint to `02_blink.spine` and verify its initial hash.
- [ ] Inspect the source blink and list the exact eye/eyelid bones, attachments, and Slot color properties that change.
- [ ] Create lowercase `blink` with a 10-frame duration at 30 FPS.
- [ ] Retarget the source timing so closing begins at frame 0, full closure occupies approximately frames 3–6, and the original open-eye state is restored at frame 10.
- [ ] Retain only directly evidenced eye properties; remove body, root, head, hair, tail, attachment-unrelated, Draw Order, Deform, and constraint timelines.
- [ ] Use fast ease-in/ease-out curves without rebound or overshoot.
- [ ] Verify frames 0 and 10 match the accepted open-eye pose exactly and the closed frame has no texture gap or face deformation.
- [ ] Save, close, reopen, re-audit, hash, and promote only on pass.
- [ ] Record that real multi-Track composition remains a future Runtime test if Spine Editor cannot reproduce AnimationState layering.

### Task 4: Build walk and run locomotion

**Files:**
- Read: accepted `02_blink.spine`, source animation `Move`
- Create sequentially: `03_walk_left.spine`, `04_walk_right.spine`, `05_run_left.spine`, `06_run_right.spine`

**Interfaces:**
- Consumes: `Move`, accepted setup appearance, and the audited asymmetric-content list.
- Produces: four root-stationary locomotion loops for future Track 0.

- [ ] Audit weapon, clothing, hair, tail, text, Slot order, constraints, bounding/collision attachments, and asymmetric accessories before choosing direction handling.
- [ ] Prefer independent left/right animations if negative-X mirroring produces any visual, constraint, attachment, or collision defect; otherwise document and separately validate the whole-skeleton mirror strategy.
- [ ] Create `walk_left` as a 1.0–1.4 second loop derived from the useful gait portion of `Move`, with two readable contacts, weight transfer, fixed average ground baseline, and no accumulated root translation.
- [ ] Save/reopen/hash/accept `walk_left` before creating `walk_right`.
- [ ] Create and separately validate `walk_right`; do not infer acceptance from the left-facing result.
- [ ] Create `run_left` as a distinct 0.6–0.9 second loop with longer flight/stride, greater torso lean, stronger arm/secondary follow, and a readable run silhouette. Do not make it only a time-scaled walk.
- [ ] Save/reopen/hash/accept `run_left` before creating `run_right`.
- [ ] Create and separately validate `run_right`.
- [ ] For every locomotion asset, inspect frames at both contacts, passing poses, mid-loop, and end; verify feet, root, weapon, accessories, Draw Order, constraints, Mesh/Deform, clipping, and three loops.

### Task 5: Build seated and sleeping lifecycles

**Files:**
- Read: accepted locomotion checkpoint; source animations `Default`, `Sit`, and `Sleep`
- Create sequentially: `07_sit_down.spine`, `08_sit_idle.spine`, `09_sleep_start.spine`, `10_sleep_loop.spine`, `11_sleep_end.spine`

**Interfaces:**
- Produces: `sit_down -> sit_idle -> return_idle` and `sleep_start -> sleep_loop -> sleep_end -> return_idle` pose-compatible chains.

- [ ] Create `sit_down` as a 0.5–0.8 second one-shot from accepted idle pose to the exact `sit_idle` entry pose.
- [ ] Create `sit_idle` as a restrained 2–4 second loop using the stable portion of `Sit`; frames 0 and end must match completely.
- [ ] Verify the final `sit_down` pose equals frame 0 of `sit_idle` for every keyed bone, Slot, attachment, color, Draw Order, Deform, and constraint property.
- [ ] Create `sleep_start` as a 1.0–1.5 second one-shot from a valid resting pose to the exact `sleep_loop` entry pose.
- [ ] Create `sleep_loop` as a 3–5 second loop using the stable portion of `Sleep`; no root drift, attachment flicker, or loop pop.
- [ ] Create `sleep_end` as a 0.8–1.2 second one-shot from the exact `sleep_loop` exit pose toward the accepted standing return pose.
- [ ] Save, close, reopen, hash, and accept each animation before moving to the next.
- [ ] Audit all adjacent handoffs by comparing exact exit/entry values, not only screenshots.

### Task 6: Build the drag, release, landing, and return chain

**Files:**
- Read: accepted seated/sleeping checkpoint; source rig and useful poses from `Default`, `Move`, `Interact`, or `Sit`
- Create sequentially: `12_drag_start.spine`, `13_drag_loop.spine`, `14_drag_end.spine`, `15_landing.spine`, `16_return_idle.spine`

**Interfaces:**
- Produces: pose-only interaction chain; future code owns cursor following, velocity, gravity, window location, and landing detection.

- [ ] Create `drag_start` as a 0.2–0.35 second one-shot that changes pose without changing root/world position.
- [ ] Create `drag_loop` as a 0.8–1.2 second suspended/struggle loop with controlled secondary motion and no cursor-follow translation.
- [ ] Create `drag_end` as a 0.25–0.5 second release one-shot that supplies a stable pose for either falling/landing or direct return.
- [ ] Create `landing` as a 0.25–0.45 second one-shot with clear impact, compression, settle, fixed foot contact, and no window translation.
- [ ] Create `return_idle` as a 0.3–0.6 second one-shot whose final pose exactly matches accepted `idle` frame 0.
- [ ] Validate the semantic chains `drag_start -> drag_loop -> drag_end -> landing -> return_idle` and `drag_end -> return_idle` by exact pose comparisons.
- [ ] Save/reopen/hash/accept each checkpoint and stop if an action requires program physics inside Spine.

### Task 7: Build Agent and reminder states

**Files:**
- Read: accepted drag-chain checkpoint; sources `Interact`, `Relax`, `Special`, and existing rig controls
- Create sequentially: `17_think.spine`, `18_read.spine`, `19_type.spine`, `20_remind.spine`

**Interfaces:**
- Produces: semantic visual assets only; no Agent text, timer, secret, notification payload, or program state is stored in Spine.

- [ ] Create `think` as a 2–3 second restrained loop with readable head/upper-body thought posture.
- [ ] Create `read` as a 2–4 second loop using only existing attachments; do not create or import a new book image.
- [ ] Create `type` as a 1–2 second loop using existing arm/hand controls and attachments; do not import a keyboard asset.
- [ ] Create `remind` as a 1.0–1.5 second high-priority one-shot with a clear anticipation, accent, and stable return pose.
- [ ] Ensure none of these animations contains timers, text payloads, event secrets, root/window motion, accidental blink data, or unrelated Deform.
- [ ] Save/reopen/hash/accept each checkpoint.

### Task 8: Build performance and emotion one-shots

**Files:**
- Read: accepted Agent-state checkpoint; sources `Interact`, `Special`, `Relax`, and existing facial controls
- Create sequentially: `21_wave.spine`, `22_happy.spine`, `23_confused.spine`, `24_angry.spine`

**Interfaces:**
- Produces: four one-shot Track 0 assets with defined `return_idle` or `idle` exits.

- [ ] Create `wave` as a 1.0–1.5 second readable greeting without introducing a new attachment.
- [ ] Create `happy` as a 0.8–1.2 second positive full-body accent with stable feet or a deliberately verified airborne-and-landed cycle.
- [ ] Create `confused` as a 1.0–1.5 second readable uncertain expression/posture.
- [ ] Create `angry` as a 1.0–1.5 second controlled expression/posture that does not damage the neutral setup appearance.
- [ ] For every eye or facial property used, append a property-conflict row against `blink`; explicitly choose ownership or suppression rather than relying on Track number.
- [ ] Verify each final pose hands off to `return_idle` or equals accepted `idle` entry pose.
- [ ] Save/reopen/hash/accept each checkpoint.

### Task 9: Perform the final 25-animation asset audit

**Files:**
- Read: accepted `24_angry.spine`
- Create: `25_all_animations_final.spine`
- Update: `production_manifest.md`
- Create: `final_animation_audit.md`

**Interfaces:**
- Produces: final Editor-validated project and complete evidence report; it does not produce Runtime exports.

- [ ] Copy the accepted final checkpoint to the nonexisting `25_all_animations_final.spine`.
- [ ] Verify the exact 25 names: `idle`, `breathing`, `blink`, `walk_left`, `walk_right`, `run_left`, `run_right`, `sit_down`, `sit_idle`, `sleep_start`, `sleep_loop`, `sleep_end`, `wave`, `happy`, `think`, `read`, `type`, `remind`, `confused`, `angry`, `drag_start`, `drag_loop`, `drag_end`, `landing`, `return_idle`.
- [ ] For every animation record source, duration, frame range, FPS, loop intent, future Track, recommended mix, semantic next state, and acceptance status.
- [ ] Inventory every keyed bone, Slot, attachment, color, Draw Order, Deform, and constraint property with frames, values, and curves.
- [ ] Recheck all loops for first/end equality and three-cycle stability.
- [ ] Recheck every start/loop/end/return handoff by exact property values.
- [ ] Recheck feet, root transforms, silhouette, asymmetric direction behavior, attachments, Slot colors/blend modes, Draw Order, Mesh/Deform, constraints, clipping, and visible intersections.
- [ ] Save, close, reopen the final file and repeat animation-name and appearance checks.
- [ ] Compute the final SHA-256 and append the complete checkpoint lineage and all created files to both reports.
- [ ] Confirm original Runtime Data hashes remain unchanged and confirm no character asset or Spine export was written to `D:\SJTUClaw`.
- [ ] State explicitly that JSON/SKEL/Atlas/PNG export, real AnimationState Track composition, mix callbacks, events, Skin switching, PMA rendering, and SJTUClaw Runtime playback are not validated by this plan.
- [ ] Pause and wait for user confirmation. Do not export or begin program integration.

## Execution handoff

Execute this plan inline in one ordered desktop-control session using
`superpowers:executing-plans` plus `computer-use:computer-use`. Parallel agents
must not control Spine Editor or mutate the checkpoint lineage. A research-only
agent may be used only if it does not access the GUI or project files.
