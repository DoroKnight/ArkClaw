# Schwarz production desktop-pet runtime

The production launcher is the existing `arkclaw.presentation.qt.pet_application`
entry point. The timed `scripts/qt_spine38_vertical_slice.py` program remains a
three-loop diagnostic and intentionally exits; it is not the production launcher.

## External role-pack manifest

No Spine art asset is tracked or copied into this repository. Production startup
is opt-in through two process environment variables:

```powershell
$env:ARKCLAW_PET_ROLE_MANIFEST = 'D:\ArkModels\Schwarz\schwarz.json'
$env:ARKCLAW_SPINE38_BRIDGE_DLL = `
  'D:\ArkClaw\build\spine38\Release\arkclaw_spine38_bridge.dll'
```

The manifest is UTF-8 JSON using schema version 1:

```json
{
  "schema_version": 1,
  "pack_id": "schwarz-production",
  "spine_version": "3.8",
  "assets": {
    "skeleton": "D:\\ArkModels\\Schwarz\\character.skel",
    "atlas": "D:\\ArkModels\\Schwarz\\character.atlas",
    "texture": "D:\\ArkModels\\Schwarz\\character.png"
  },
  "expected_sha256": {
    "skeleton": "<64 lowercase hexadecimal characters>",
    "atlas": "<64 lowercase hexadecimal characters>",
    "texture": "<64 lowercase hexadecimal characters>"
  },
  "animations": {
    "relax": "Relax",
    "move": "Move",
    "sit": "Sit",
    "sleep": "Sleep",
    "special": "Special",
    "interact": "Interact"
  },
  "direction_policy": "mirror_move",
  "framing": {
    "scale": 1.0,
    "x_offset": 0.0,
    "foot_baseline": 180.0
  },
  "texture_page_count": 1
}
```

All three asset files must be absolute paths under one package directory. They
are opened read-only and validated against the expected hashes before the native
bridge is constructed. Invalid configuration, assets, native runtime, framing,
or OpenGL setup leaves the application alive with its tray and placeholder.

## Production behavior

The tray displays the active role-pack identity, seven typed actions, and the
separate `Resume Autonomous` command. `Move > Left` and `Move > Right` share the
physical `Move` animation and use semantic facing plus window velocity for
direction. A tray looping action enters explicit hold until another explicit
action, a mandatory interruption, or `Resume Autonomous` occurs. `Special` and
`Interact` are protected one-shots.

The native runtime supplies exact completion and monotonic loop-boundary events.
Autonomous dwell is selected once per state entry or STAY and commits only after
the engine accepts the scheduler proposal. Playback failure stops velocity and
autonomous scheduling instead of escaping through the Qt timer.

The OpenGL FBO uses `ceil(logical_size * device_pixel_ratio)` independently for
width and height. Atlas minification and magnification filters remain independent;
an unavailable filter field falls back to Linear. Production preparation samples
12 fixed poses from each of the six physical animations. `Relax` alone calibrates
the immutable 162-logical-pixel body transform; `Special` and `Interact` effects
never reduce that scale.

## Windows manual acceptance

After building the Release bridge and setting the two variables above, launch the
normal production application and check:

1. the pet and tray stay alive beyond three Relax loops;
2. hiding or closing the pet window does not exit the process;
3. every tray action selects the matching animation, and both Move directions
   move the window with matching facing;
4. explicit Sleep/Sit/Move remains held until replaced or autonomous mode is
   resumed;
5. Special/Interact complete once and then follow pending-or-Relax semantics;
6. dragging, pause, workspace collision, and shutdown stop unsafe movement;
7. rendering is sharp at DPR 1.0, 1.25, 1.5, and 2.0, with transparent edges,
   stable logical footprint, and feet above the taskbar;
8. only the tray `Exit` action performs controlled application shutdown.

Visual acceptance requires a human review on the target Windows display. A
passing automated suite does not substitute for that review.
