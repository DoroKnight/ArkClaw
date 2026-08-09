# Spine 3.8 Visible-Frame Scaling Design

## Context

The local Schwarz `Relax` vertical slice creates the expected transparent
`160 x 180` pet window, but manual review found that the character is too small
to use. The measured nontransparent frame is only about `18 x 28` pixels.

The failure is caused by the transform input, not by window creation, UVs, or
OpenGL composition. The Runtime setup bounds are approximately
`2001.6 x 906.6`, while the first evaluated `Relax` frame's commands with
nonzero vertex alpha occupy approximately `256.6 x 397.1`. Fitting the inflated
setup bounds reduces the visible character by about eight times horizontally.

## Goal

Fit the directly tested `Relax` visual into the existing `160 x 180` pet
window so that:

- the visible character uses nearly all available vertical space;
- the feet sit immediately above the taskbar;
- the transform remains fixed for the entire playback and cannot pump between
  frames; and
- the existing one-window, local-only, fail-closed integration remains intact.

## Non-goals

This change does not generalize framing for arbitrary Spine assets or other
animations. It does not alter native geometry evaluation, atlas loading,
production renderer selection, action sequencing, Agent integration, window
size, packaging, or publication.

## Selected approach

Use a one-time visible-frame envelope after binding `Relax`.

During renderer initialization:

1. Require the exact, case-sensitive `Relax` catalog entry.
2. Bind `Relax` to track 0 with looping enabled exactly once.
3. Evaluate the Runtime with a zero-second delta. This materializes draw data
   without advancing animation time.
4. Read the evaluated draw commands and discard commands whose vertices all
   have alpha zero.
5. Compute one finite, positive union bound from every vertex in the remaining
   commands.
6. Fit that bound once into the logical viewport and retain the resulting
   transform for every later frame.

The renderer must not recompute the transform during ordinary updates.

## Viewport geometry

The logical window remains `160 x 180`.

- top margin: `4` logical pixels;
- foot baseline: `176` logical pixels;
- bottom safety gap: `4` logical pixels; and
- horizontal centering: based on the visible-frame bound center.

The uniform scale is the smaller of the available-width and available-height
ratios. For the approved Schwarz `Relax` frame, height is the limiting axis, so
the expected result is approximately `172` pixels high and `111` pixels wide.

The Runtime coordinate system remains y-up and the Qt logical viewport remains
y-down. The visible bound's minimum y maps to the foot baseline. Its maximum y
maps toward the top margin.

## Module boundaries

`Spine38Runtime` owns renderer-neutral frame inspection. It will expose a
method that returns a validated `Spine38Bounds` for the currently evaluated
visible commands. It will not know about taskbars, Qt, or viewport constants.

`Spine38PetRenderer` owns initialization order and viewport policy. It will
perform the zero-delta evaluation, request the visible bounds, create the fixed
transform, build the first mesh scene, and initialize the existing OpenGL
backend.

The native ABI and generic OpenGL mesh backend remain unchanged.

## Failure behavior

Initialization fails closed with the existing fixed renderer error when:

- no draw command has a vertex with nonzero alpha;
- a selected vertex coordinate is nonfinite;
- the union bound is empty or nonpositive;
- zero-delta evaluation fails; or
- the resulting mesh scene fails existing validation.

No native error detail, asset path, catalog contents, or traceback is exposed.
`SafePetRenderer` continues to replace a failed delegate with the placeholder.

## Test design

TDD starts with failing tests for the user-visible defect.

Unit tests will prove that:

- fully transparent commands do not enlarge visible bounds;
- visible commands produce the exact finite union bound;
- empty, degenerate, or nonfinite visible geometry fails closed;
- renderer initialization calls `set_animation(0, "Relax", True)` once;
- renderer initialization performs exactly one `update(0.0)` before framing;
- later updates use caller deltas and never recompute the transform; and
- the fixed transform maps the visible feet to `y = 176` and the visible top
  to at least `y = 4` within tolerance.

The opt-in real-asset smoke will add a semantic visibility assertion. Across
three `Relax` loops, every sampled nontransparent bound must be at least `80`
pixels wide and `150` pixels high, remain inside the `160 x 180` viewport, and
place its bottom edge between `y = 172` and `y = 180`. These thresholds catch
the observed `18 x 28` regression while allowing antialiasing and transparent
atlas padding. This supplements, rather than replaces, the manual visual
checkpoint.

## Acceptance

The change is accepted only after:

- focused unit and Qt renderer suites pass;
- the real three-loop opt-in smoke passes its new visibility assertions;
- existing window, placeholder, OpenGL, native, Ruff, and mypy gates remain
  green; and
- a new `pythonw.exe` manual run visibly shows Schwarz filling the window with
  stable feet immediately above the taskbar and no obvious loop-boundary jump.
