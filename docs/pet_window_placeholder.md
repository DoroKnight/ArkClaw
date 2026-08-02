# Placeholder Pet Window

This stage adds an original, programmatically painted placeholder character.
It does not contain, load, derive, or distribute Spine, PNG, atlas, skel, or
third-party character assets.

## Runtime boundary

`PetWindow` owns only Qt presentation state and a deterministic local motion
model. It never receives a Provider, repository, `SecretStore`, asyncio task,
continuation, or API key. Opening the Agent window and exiting are emitted as
Qt signals. `PetApplicationCoordinator` maps those signals to the existing
`MainWindow` and `QtRuntimeBridge` safe shutdown flow.

In pet mode, closing the Agent `MainWindow` hides that window without stopping
the runtime or the pet. The standalone GUI keeps its original close-to-shutdown
behavior. Only the pet's explicit Exit action calls `request_safe_close()`,
which bypasses hide-on-close and enters the reviewed asynchronous RuntimeThread
shutdown path. A failed shutdown restores hide-on-close behavior for retry.

The production startup remains lazy: constructing the pet does not activate a
cloud Provider, read a credential, create a cloud client, or send a request.

## Layered state and animation

The lifecycle layer contains `active`, `paused`, and `closing`. The exclusive
motion layer contains `idle`, `walking_left`, `walking_right`, `dragging`,
`falling`, and `landing`. The behavior layer can combine `breathing`,
`blinking`, `thinking`, `reminding`, and `drag_struggle` where the combination
is valid.

Examples include `idle + breathing + blinking`, `walking_left + blinking`,
`dragging + drag_struggle`, and `idle + reminding`. Invalid combinations such
as `closing + blinking`, `paused + breathing`, or `drag_struggle` without
dragging fail closed.

Priority is:

```text
closing > paused > dragging/drag_struggle > falling/landing
> reminding > walking > thinking > idle/breathing/blinking
```

One GUI timer reads an injected monotonic clock and supplies explicit delta
time to `PetAnimationEngine`. Delta is capped before movement or animation,
and paused/closing lifecycles do not advance animation or random scheduling.
A paused pet can still be dragged for manual repositioning; releasing it keeps
the lifecycle paused and does not start falling. Blink and idle-action
randomness use an injectable `random.Random`.

`request_reminder_animation()` accepts no text or payload and only starts a
local visual action. It does not access notifications, persistence, Provider
state, or Agent output.

## Replaceable renderer

`PetWindow` produces a non-sensitive `PetRenderFrame` and passes it to the
`PetRenderer` Protocol. Its lifecycle is `initialize`, viewport/state updates,
explicit delta-time `update`, `render`, `pause`/`resume`, and idempotent
`close`. `PlaceholderPetRenderer` contains all current QPainter character
details. `SafePetRenderer` contains construction and frame failures behind
fixed safe codes and switches to a fresh programmatic placeholder; it never
publishes an exception or an asset path.

The framework-free action request vocabulary is intentionally smaller than a
future asset runtime API. It covers movement and presentational requests while
leaving window movement, gravity, landing, display clamping, input, and safe
shutdown with the existing application and Qt layers. Placeholder rendering
supports its existing actions; requests such as running, sitting, sleeping,
reading, or typing report unsupported and use `idle` as their safe visual
fallback.

`PetRendererConfig` keeps renderer selection separate from its optional,
in-memory-only `ExternalPetAssetDescriptor`. The descriptor uses an opaque ID,
an explicitly supplied local root, three exact filenames, an expected major
and minor version, optional hashes, and centralized size limits. It rejects
URLs, UNC/device roots, traversal, control characters, streams and nested
filenames; it is never persisted and does not discover files by scanning.

`ExternalPetAssetLoader` opens exactly those three names through an injected
filesystem boundary. The Windows implementation retains restrictive,
non-inheritable read handles, rejects reparse points and multiple hard links,
checks the final handle path, denies named data streams, and compares handle
identity before and after streaming hashes. A bundle is published only after
all three files pass. It owns the directory and file handles and closes them
in reverse order, including partial-failure cleanup.

Metadata parsing stops at PNG IHDR fields, atlas page/packing bounds, and the
binary skeleton version header. It does not parse bones, slots, skins,
attachments, constraints, events, animations, meshes, or deforms. Because no
external animation runtime is part of this stage, every external renderer
selection remains unavailable and falls back to Placeholder. A future legally
sourced renderer can replace it without changing Agent Runtime, Provider,
dragging, workspace physics, behavior state, or safe shutdown.

Breathing uses a local coordinate deformation that tapers to zero above the
lower legs. The torso, shoulders, head, ears, face, and upper arms move
slightly while the window, shadow, lower legs, and foot pixels remain fixed.
Blinking is an independent eye overlay. Walking uses a stride/cycle-derived
speed. Thinking and reminding use programmatic vector marks rather than font
or image assets. Dragging uses procedural limb/body oscillation without
changing mouse-follow coordinates.

Closing stops interaction and the single animation timer. Renderer resources
are closed after Runtime shutdown succeeds. A failed Runtime shutdown returns
the pet to a paused state so the process is not forcibly terminated.

## Coordinates and displays

Qt 6 supplies window and `availableGeometry()` values in device-independent
pixels. The pure geometry layer selects the workspace with the greatest window
overlap, falls back to the nearest workspace, and clamps the whole placeholder
inside that workspace. A separate physical-to-logical conversion is tested for
common scale factors.

## Offline verification

```powershell
.\.venv\Scripts\python.exe .\scripts\qt_pet_smoke.py
```

The pet and Agent GUI commands are installed as Windows GUI launchers. The
Agent development demo remains a console launcher.

The smoke uses `FakeQtRuntimeCompositionRoot`, an offscreen Qt platform, an
injectable clock/RNG, a temporary metadata file, and no external assets,
network, or Credential Manager access. It covers breathing, blinking, walking,
drag struggle, reminder completion, Agent-window hide/reopen, renderer close,
timer close, and RuntimeThread close. A smoke-only Qt message handler counts
exactly reviewed offscreen warnings; every unknown warning or critical message
fails the smoke. It does not alter production Qt logging.
