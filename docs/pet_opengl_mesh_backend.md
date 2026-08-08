# OpenGL textured-mesh backend

## Scope and decision

This stage turns the programmatic textured-mesh spike into an explicitly
selected, reusable renderer backend. The production default remains
`PlaceholderPetRenderer`. No external character asset, Spine runtime, Spine
format parser, resource path, or packaged artifact is involved.

The existing top-level architecture remains unchanged. `PetWindow` still owns
its translucent frameless `QWidget`, 16 ms GUI timer, logical geometry,
dragging, gravity, work-area clamping, pause state, and safe shutdown. The
backend only owns visual GPU resources and returns a premultiplied `QImage` for
the existing `QPainter` path. It never accesses the Agent runtime, providers,
secrets, settings, or window movement.

## Why the spike was not reusable

The spike proved that an offscreen OpenGL 3.3 FBO can feed the Windows
transparent-window composition path, but it deliberately recreated its FBO,
textures, VBOs, IBOs, and VAOs for every frame. It also called `glFinish()`,
used a bounding scissor rectangle for clipping, and left the texture-origin
and alpha conventions implicit. Those choices were suitable only for a route
comparison.

`OpenGLTexturedMeshBackend` replaces those behaviors with:

- one GUI-thread-owned context, offscreen surface, and shader program;
- persistent textures and geometry buffers per uploaded scene;
- one persistent FBO per physical viewport;
- transaction-like scene and viewport replacement, where the old live object
  is retained until its replacement is complete;
- no explicit `glFinish()`; FBO readback is the only unavoidable GPU/CPU
  synchronization point;
- fixed, content-free failure codes that can be contained by
  `SafePetRenderer`; and
- idempotent close with GPU destruction while the owning context is current.

Repeated `initialize()` with the same viewport is a no-op. A changed viewport
or device pixel ratio creates a replacement FBO and releases the previous one.
No OpenGL object may be created, used, or destroyed by `RuntimeThread`.

## Mesh and pixel contract

The backend consumes the existing renderer-neutral `PetMeshScene`,
`PetMeshDrawCommand`, and `PetMeshTextureData` types. It introduces no model
specific to Spine or any other animation framework.

The contract is:

- positions are logical scene coordinates with a top-left origin;
- UV `(0, 0)` addresses the top-left texture texel;
- draw commands use stable ascending draw order;
- vertex RGBA multiplies the sampled texture;
- straight-alpha sources use separate RGB and alpha blend factors;
- premultiplied-alpha sources use the matching premultiplied factors;
- the readback is `Format_RGBA8888_Premultiplied`; and
- the background remains transparent.

Clipping is explicitly limited to bounded convex polygons in this stage. The
model rejects concave, self-intersecting, degenerate, or out-of-bounds clips.
The OpenGL backend triangulates an accepted clip as a fan and writes it into
the stencil buffer before drawing the command. It never substitutes a bounding
rectangle for the polygon.

The correctness tests use tiny, original RGBA byte arrays generated at test
runtime. A software triangle rasterizer provides the pixel reference for UV
orientation, rotated UVs, alpha, vertex color, order, and clipping. No binary
image fixture is committed.

## DPI and transparent-window composition

The mesh remains in logical coordinates. The FBO dimensions are

\[
\text{physical size} = \operatorname{round}(\text{logical size} \times
\text{device pixel ratio}).
\]

The explicit smoke covers device pixel ratios 1.0, 1.25, 1.5, and 2.0 for a
160 by 180 logical viewport. The resulting physical sizes are 160 by 180, 200
by 225, 240 by 270, and 320 by 360. The logical foot baseline stays at 160;
the renderer does not resize the window or apply whole-character breathing
scale.

The Windows-platform smoke injects `OpenGLMeshPetRenderer` into the real
transparent `PetWindow`, captures the composed widget, and verifies a
transparent exterior pixel and visible mesh pixels. It also exercises pause
and resume, drag to falling, landing to idle, and idempotent shutdown without
changing `PetWindow` or adding `QOpenGLWidget`, Qt Quick, another render loop,
or another runtime thread.

## Measured local behavior

On the development machine, one representative explicit smoke reported:

- context, shader, scene, and FBO initialization: about 18.9 ms;
- first readback frame: about 36.9 ms;
- 1,000 warmed frames: about 0.42 ms mean, 0.35 ms P50, 0.69 ms P95,
  and 1.65 ms maximum;
- QImage readback: about 0.40 ms mean;
- GUI timer samples: about 16.1 ms mean and 20.0 ms maximum delay; and
- 50 complete initialize/render/close cycles: about 3.46 seconds total.

The initial scene uploads two textures and four geometry objects (three draw
meshes plus one clip mesh). Those upload counters remain unchanged throughout
the 1,000-frame loop. Each frame allocates one readback `QImage`; it allocates
no texture, mesh buffer, vertex array, or FBO. The lifecycle smoke then performs
20 scene replacements and four device-pixel-ratio/FBO replacements.

These figures establish feasibility on this machine only. The smoke records
30 and 60 FPS budget comparisons, but tests do not impose fragile timing
thresholds across GPU drivers or CI hosts. Pixel correctness, resource counts,
thread ownership, and lifecycle cleanup are the hard gates.

## Remaining risk

This is not a Spine integration and does not demonstrate any external
character animation. A future `Spine38Renderer` would only need to translate
its evaluated draw order, vertices, UVs, indices, texture identifiers, alpha
mode, and convex clips into `PetMeshScene`, then explicitly select this
backend. External resource ownership and animation evaluation remain separate
boundaries.

Driver context loss can be safely classified and contained, but broad packaged
GPU-driver coverage remains a deployment risk. FBO readback still synchronizes
the GPU and GUI thread, so future production profiling must include target
machines and longer animation sessions. Concave clipping would require a
different triangulation or stencil winding design and is deliberately rejected
rather than approximated.

The explicit diagnostic smoke also injects one-shot context creation, shader,
scene upload, viewport creation, make-current, and readback faults. Failed
scene and viewport replacements retain their previous live resources, and the
recoverable make-current/readback cases render again after the one-shot fault.
The fault controller is disarmed by default and carries only fixed enum values.
