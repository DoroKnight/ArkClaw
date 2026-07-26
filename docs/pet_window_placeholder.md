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

## State machine

| State | Entry | Exit | Interruptible | Priority |
|---|---|---|---:|---:|
| `idle` | Landing completed | Drag, fall, pause, close | yes | 0 |
| `falling` | Drag released | Ground, drag, pause, close | yes | 40 |
| `landing` | Ground contact | Timer, drag, pause, close | yes | 50 |
| `paused` | Explicit user action | Resume or close | yes | 70 |
| `dragging` | Primary-button press | Release, pause, close | yes | 80 |
| `closing` | Safe shutdown requested | Close or reviewed failure recovery | no | 100 |

Closing stops interaction and the physics timer. A failed runtime shutdown
returns the pet to a paused state so the process is not forcibly terminated.

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

The smoke uses `FakeQtRuntimeCompositionRoot`, an offscreen Qt platform, a
temporary metadata file, and no external assets, network, or Credential
Manager access.
