# Textured mesh renderer spike

The follow-up engineering result is documented in
`pet_opengl_mesh_backend.md`. This file remains the historical route comparison.

## Scope

This spike evaluates renderer backends with an original, runtime-generated
checker texture and fictional triangle meshes. It does not load, parse, copy,
or render Spine assets. It adds no production renderer selection and does not
change the default `PlaceholderPetRenderer`.

## Existing presentation boundary

`PetWindow` is a fixed 160 by 180 logical-pixel, frameless `QWidget` with
`WA_TranslucentBackground`, `WA_ShowWithoutActivating`, `Tool`, and
`WindowDoesNotAcceptFocus`. On Windows, Qt composes this translucent top-level
window through the platform's layered-window path. A 16 ms GUI-thread `QTimer`
advances motion and animation, calls the renderer lifecycle, moves the window,
and schedules `update()`. `paintEvent()` creates a `QPainter` and delegates one
frame to `SafePetRenderer`.

The existing ownership boundary remains correct:

- `PetWindow` owns window geometry, dragging, gravity, work-area clamping,
  device-independent coordinates, the timer, and shutdown.
- A renderer owns visual state and follows `initialize`, `set_viewport`,
  `set_state`, `update`, `render`, `pause`/`resume`, and idempotent `close`.
- All Qt painting and OpenGL object work belongs to the GUI thread.
- `SafePetRenderer` catches a selected renderer failure and replaces it with a
  new programmatic placeholder without exposing an exception body.

Qt uses logical coordinates for the widget. The spike therefore generates
physical test images at device-pixel ratios 1.0, 1.25, 1.5, and 2.0 while
preserving a logical foot baseline of 160.

## Four routes reviewed

| Route | Finding | Spike decision |
| --- | --- | --- |
| Python software triangles into `QImage` | Simplest ownership and transparent-window composition; CPU cost scales with covered pixels and Python loops | Selected as the correctness baseline |
| `QOpenGLContext` + `QOffscreenSurface` + FBO | Keeps OpenGL out of the top-level widget, accepts VBO/IBO triangle data, but adds context lifetime and readback | Selected as the accelerated candidate |
| `QOpenGLWidget` | Changes the existing translucent top-level widget into a child-surface composition problem and may be unreliable with layered windows | Rejected for this spike |
| Qt Quick / QSG | Introduces a second scene graph, render loop, window model, and packaging surface | Rejected for this spike |

## Minimal mesh contract

`pet_mesh_model.py` contains only positions, UVs, RGBA vertex colors, triangle
indices, opaque texture IDs, stable draw order, alpha convention, and an
optional clip polygon. It deliberately contains no bones, slots, skins,
attachments, constraints, events, animation timelines, or deform data.

The generated scene contains:

- one 64 by 64 RGBA checker texture with a semi-transparent edge gradient;
- a matching premultiplied-alpha form for convention comparison;
- two overlapping quads with deliberately unsorted input order;
- one non-rectangular triangle mesh;
- a rectangular clip polygon; and
- a fixed logical ground baseline.

No PNG or other binary fixture is created or committed.

## Software result

The software candidate is a bounds-checked, nearest-neighbour barycentric
rasterizer. It accumulates into `Format_RGBA8888_Premultiplied`, explicitly
converts straight-alpha samples, applies vertex color, performs source-over
blending, and returns a new `QImage`. It does not resize the pet window or add a
whole-character breathing scale. Closing is idempotent, and its explicit
`PetRenderer` adapter can be contained by `SafePetRenderer`.

On the development machine, five 160 by 180 frames measured approximately:

- 112.101 ms wall time per frame;
- 112.500 ms process CPU time per frame; and
- five tracked transient allocations per frame.

This correctness-oriented Python implementation misses both the 30 FPS

\[
\frac{1000}{30} \approx 33.3\text{ ms}
\]

and 60 FPS

\[
\frac{1000}{60} \approx 16.7\text{ ms}
\]

budgets. A native C++ rasterizer could be materially faster, but introducing a
compiled extension solely to rescue this candidate would add a new ABI and
packaging boundary and was outside this minimal experiment.

## OpenGL result

The accelerated candidate creates an OpenGL 3.3 core context, offscreen
surface, FBO, shaders, textures, VBO, IBO, and VAO on one GUI thread. It draws
the same in-memory geometry, reads the transparent FBO back to a premultiplied
`QImage`, and then allows the existing `QPainter`/layered-window path to remain
unchanged. A rectangular scissor implements the current generated clip; an
arbitrary future clip polygon would require stencil geometry.

The first frame paid approximately 0.6 seconds for context and shader setup.
After warm-up, 30 frames including FBO readback averaged approximately
1.531 ms per frame and met both budgets. The transparent corner remained alpha
zero. This is not a direct OpenGL-to-layered-window claim: readback deliberately
avoids that unproven composition boundary.

The costs are additional GUI-thread context management, per-frame GPU/CPU
synchronization at `glFinish` and readback, explicit context-loss handling, and
more packaged Qt/OpenGL surface area. OpenGL objects must never be created,
used, or destroyed by `RuntimeThread`.

## Decision

Recommend the offscreen OpenGL FBO route for a future textured-triangle
renderer prototype, with QImage readback into the existing `QPainter` path.
The measured Python software route is not viable at 30 FPS for this tiny target,
while the warmed OpenGL route has ample measured headroom and naturally accepts
position/UV/index output.

This recommendation is conditional, not a production integration decision.
Before becoming a selectable renderer it still needs packaged-machine context
loss tests, repeated create/close tests, driver coverage, arbitrary clipping or
a documented clip limitation, and end-to-end GUI timer impact measurement. A
native optimized software implementation remains a valid fallback option if a
future toolchain already supplies one without expanding the distribution.

The spike does not establish that any Spine runtime, resource, animation, or
character has been integrated or validated.
