# Local Spine 3.8 Schwarz Idle Vertical Slice

This diagnostic exercises one explicit, local-only rendering path for the approved original Schwarz Spine 3.8 asset triplet. It is not selected by normal SJTUClaw startup and does not enable the production Agent or action-sequencing path.

## Local prerequisites

- Windows x64 with the repository Python virtual environment and PySide6 dependencies installed.
- CMake/MSVC prerequisites required by the native build wrapper.
- The external asset directory containing the exact approved `.skel`, `.atlas`, and `.png` files. These assets remain outside the repository.
- Network access is needed only if the pinned official Runtime source is not already present under ignored `build/spine38/source`.

Build and test the Release bridge from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_spine38_bridge.ps1 -Configuration Release -RunTests
```

The wrapper verifies and checks out official `spine-runtimes` commit `8b4844bd4b193ba9e54487ed397a777993cbad56`. The expected local outputs include:

- `build\spine38\Release\sjtuclaw_spine38_bridge.dll`
- `build\spine38\Release\spine38-build-manifest.json`
- `build\spine38\Release\LICENSE`

The copied license is the Spine Runtimes License Agreement from the pinned upstream source. The Runtime is not MIT-, Apache-, BSD-, or SJTUClaw-owned code. Runtime source, DLLs, PDBs, generated evidence, and external character assets stay under ignored/local paths and are not packaged by this slice.

## Catalog-only check

The existing nonvisual check validates the adjacent build manifest, approved hashes, Spine metadata, catalog, and exact case-sensitive `Relax` candidate:

```powershell
.venv\Scripts\python.exe scripts\qt_spine38_vertical_slice.py `
  --list-only `
  --bridge-dll "build\spine38\Release\sjtuclaw_spine38_bridge.dll" `
  --asset-root "D:\path\to\approved\runtime_input"
```

## Three-loop visible diagnostic

Run the explicit smoke mode:

```powershell
.venv\Scripts\python.exe scripts\qt_spine38_vertical_slice.py `
  --bridge-dll "build\spine38\Release\sjtuclaw_spine38_bridge.dll" `
  --asset-root "D:\path\to\approved\runtime_input" `
  --animation Relax `
  --loops 3
```

Only the exact combination `--animation Relax --loops 3` is accepted. The process creates one existing transparent `PetWindow`; it does not create a second visual window. `Spine38PetRenderer` selects looping `Relax` once. The Runtime-reported positive `Relax` duration controls only the diagnostic sample schedule and automatic stop time. Normal `PetWindow` timer updates continue to advance the renderer; the diagnostic does not manually sequence or restart the animation.

The run samples in-memory alpha bounds and a short vertex checksum near the start, midpoint, and end of each loop, including both sides of all three boundaries. It stops after the final post-boundary sample, at no less than three reported durations. No screenshot is written.

In the same process, before the successful bridge construction path, a nonvisual probe changes the expected skeleton hash in memory. The loader must return `external_asset_hash_mismatch`; that path must not construct the bridge and must initialize a `SafePetRenderer` placeholder with a fixed construction-failure code. It opens no window.

## Automated opt-in assertion

The subprocess test skips unless both explicit variables are set:

```powershell
$env:SJTUCLAW_SPINE38_BRIDGE_DLL = (Resolve-Path "build\spine38\Release\sjtuclaw_spine38_bridge.dll").Path
$env:SJTUCLAW_SPINE38_ASSET_ROOT = "D:\path\to\approved\runtime_input"
.venv\Scripts\python.exe -m pytest tests\qt\test_spine38_schwarz_smoke.py -v
```

The test forces the Windows Qt platform plugin, launches the local script in a subprocess, checks the fixed schema and fallback proof, and confirms the evidence file matches stdout.

## Evidence boundary and schema

The diagnostic atomically writes one ignored file:

```text
build/spine38/evidence/schwarz-smoke.json
```

The same single-line JSON object is printed to stdout only when the diagnostic and cleanup complete. Failures print only a fixed status object on stderr. Neither form includes asset paths, DLL paths, tracebacks, screenshots, or raw character bytes.

Schema version 1 contains:

- `status`: currently `visual_review_required`; automated evidence is not visual acceptance.
- `animation`, `loops_requested`, `duration_seconds`, and `completed_elapsed_seconds`.
- `window_count` and `window_transparent`.
- `renderer_safe_code`.
- `sampled_nontransparent_frames`, equal to the ten validated samples.
- `samples`: ten ordered entries with label, target/observed elapsed seconds, nonempty alpha bounds, nonzero pixel count, and a 16-character vertex checksum.
- `forced_hash_failure`: loader status, `bridge_constructed`, placeholder state, and its fixed safe code.
- `agent_modules_imported`: a literal `sys.modules` observation made before explicit lazy Runtime-bridge access; it must be false.
- `visual_review_required`: true until a person performs the checks below.

Evidence is local audit data only. Do not add it to Git.

## Manual visual checkpoint

Automated alpha bounds and checksums show that frames were produced around the requested phases, but they cannot establish artistic or attachment correctness. A person must observe the one visible window across all three loops and check:

- weapon and other attachments;
- missing atlas regions;
- clipping behavior;
- obvious mesh intersections or deformation errors;
- foot placement and drift;
- visible jumps on both sides of each loop boundary.

Until that observation is recorded, the diagnostic reports `visual_review_required`. The current slice must not be described as visually accepted.

## Exact non-claims

This slice proves only direct playback and local measurement of the approved original case-sensitive `Relax` animation through the pinned Spine 3.8 Runtime and the existing PetWindow/OpenGL boundary. It does not prove or complete:

- any other logical action or animation binding;
- Track 1 `breathing`, Track 2 `blink`, or multi-track mixing;
- production animation callbacks, completion events, or loop-boundary callbacks;
- production action sequencing, interruption policy, or Agent integration;
- Runtime export or general-purpose Spine asset support;
- default renderer selection or normal application startup integration;
- packaging, redistribution, publication, pushing, or a pull request;
- manual visual acceptance of weapon, attachments, clipping, mesh behavior, foot stability, or boundary continuity.
