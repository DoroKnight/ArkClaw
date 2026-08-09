# Spine 3.8 Visible Frame Scaling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the approved Schwarz `Relax` animation fill the existing 160×180 transparent desktop-pet window while keeping the character's visible foot line four pixels above the bottom edge/taskbar boundary.

**Architecture:** Derive a renderer-neutral bounding box from the current evaluated Spine draw commands, excluding only commands whose vertex alpha is entirely zero. During renderer initialization, bind `Relax`, evaluate it once with zero delta, compute the visible bounds, and build one immutable viewport transform with a 4 px top margin and a y=176 px foot baseline. Reuse that transform for every later frame so the character neither pumps nor shifts as the animation advances.

**Tech Stack:** Python 3.13.6, PySide6 6.11.1, ctypes Spine 3.8 bridge, pytest, Ruff, strict mypy, PowerShell, OpenGL software/real-driver smoke coverage.

## Global Constraints

- Work only in `D:\SJTUClaw\.worktrees\arkpets-spine-idle-vertical-slice` on branch `codex/arkpets-spine-idle-vertical-slice`.
- Use `D:\SJTUClaw\.venv\Scripts\python.exe` for Python commands so editable-import resolution is deterministic.
- Preserve the existing public filenames, class names, native ABI, approved asset hashes, `Relax` animation selection, 160×180 window, click-through behavior, Agent isolation, and placeholder fallback.
- Keep the approved ArkPets assets read-only. Do not copy or track assets, DLLs, screenshots, generated evidence, or build output.
- Do not change the default raster pet renderer or the Agent/action runtime.
- The framing constants are exact: viewport 160×180, top margin 4 px, foot baseline y=176 px, bottom safety gap 4 px.
- Compute visible bounds exactly once after `set_animation(0, "Relax", True)` and `update(0.0)`. Never recompute the transform per frame.
- Exclude a draw command only when every vertex has alpha 0. If any vertex is visible, include every vertex in that command when forming its bounds.
- Fail closed with the existing fixed errors when visible geometry is absent, non-finite, or degenerate.
- Each task follows RED → GREEN → refactor/static checks → independent review. Do not start the next task until the current task has no unresolved Critical or Important review findings.

---

## Task 1: Add Renderer-Neutral Visible Bounds

**Files:**

- Modify: `src/sjtuclaw/application/spine38_runtime.py`
- Modify: `tests/unit/test_spine38_runtime.py`

**Interface produced:** `Spine38Runtime.visible_bounds() -> Spine38Bounds`

### Step 1: Write the failing visible-bounds tests

- [ ] Add module-level `_FakeSpine38Port`, `_vertex`, and `_command` test helpers. The port must implement `catalog`, `skins`, `setup_bounds`, `set_animation`, `update`, `draw_commands`, and idempotent `close` using the existing native value types.
- [ ] Add a unit test proving a fully transparent command with very large coordinates is excluded while an opaque command determines the exact result.

```python
def test_visible_bounds_excludes_fully_transparent_commands() -> None:
    port = _FakeSpine38Port(
        draw_commands=(
            _command(
                _vertex(-1000.0, -1000.0, a=0),
                _vertex(1000.0, 1000.0, a=0),
                _vertex(0.0, 1000.0, a=0),
            ),
            _command(
                _vertex(-2.0, -3.0, a=255),
                _vertex(4.0, -3.0, a=255),
                _vertex(1.0, 9.0, a=255),
            ),
        )
    )
    runtime = Spine38Runtime(port)

    assert runtime.visible_bounds() == Spine38Bounds(
        x=-2.0,
        y=-3.0,
        width=6.0,
        height=12.0,
    )
```

- [ ] Add a mixed-alpha test proving that one nonzero-alpha vertex retains the command's other vertices in the union. This prevents partial command cropping at soft/faded edges.

```python
def test_visible_bounds_keeps_entire_partially_visible_command() -> None:
    port = _FakeSpine38Port(
        draw_commands=(
            _command(
                _vertex(-7.0, -5.0, a=0),
                _vertex(8.0, 6.0, a=1),
                _vertex(2.0, 10.0, a=0),
            ),
        )
    )

    assert Spine38Runtime(port).visible_bounds() == Spine38Bounds(
        x=-7.0,
        y=-5.0,
        width=15.0,
        height=15.0,
    )
```

- [ ] Add parametrized fail-closed cases for no commands, all-transparent commands, non-finite x/y, zero width, and zero height. Each case must satisfy `pytest.raises(runtime.Spine38FrameError, match="^spine38_frame_invalid$")`.

### Step 2: Run the focused tests and capture RED

- [ ] Run:

```powershell
D:\SJTUClaw\.venv\Scripts\python.exe -m pytest tests\unit\test_spine38_runtime.py -k visible_bounds -v
```

Expected RED: the tests collect successfully and fail inside their bodies because `Spine38Runtime.visible_bounds` does not exist.

### Step 3: Implement the minimal bounds calculation

- [ ] Add this method next to `draw_commands()` in `Spine38Runtime`:

```python
def visible_bounds(self) -> Spine38Bounds:
    visible_vertices = [
        vertex
        for command in self.draw_commands()
        if any(vertex.a > 0 for vertex in command.vertices)
        for vertex in command.vertices
    ]
    if not visible_vertices:
        raise Spine38FrameError

    xs = tuple(vertex.x for vertex in visible_vertices)
    ys = tuple(vertex.y for vertex in visible_vertices)
    if not all(math.isfinite(value) for value in (*xs, *ys)):
        raise Spine38FrameError

    minimum_x = min(xs)
    maximum_x = max(xs)
    minimum_y = min(ys)
    maximum_y = max(ys)
    width = maximum_x - minimum_x
    height = maximum_y - minimum_y
    if width <= 0.0 or height <= 0.0:
        raise Spine38FrameError
    return Spine38Bounds(
        x=minimum_x,
        y=minimum_y,
        width=width,
        height=height,
    )
```

- [ ] Reuse the module's existing `math` import and fixed error. Do not add a second bounds type or renderer dependency.

### Step 4: Run GREEN and static checks

- [ ] Run the focused test again; expected GREEN is all selected tests passing.
- [ ] Run the full runtime unit file:

```powershell
D:\SJTUClaw\.venv\Scripts\python.exe -m pytest tests\unit\test_spine38_runtime.py -v
```

- [ ] Run static verification:

```powershell
D:\SJTUClaw\.venv\Scripts\python.exe -m ruff check src\sjtuclaw\application\spine38_runtime.py tests\unit\test_spine38_runtime.py
D:\SJTUClaw\.venv\Scripts\python.exe -m mypy --strict src\sjtuclaw\application\spine38_runtime.py tests\unit\test_spine38_runtime.py
git diff --check
```

### Step 5: Review and checkpoint

- [ ] Self-review alpha semantics, finite-number handling, degeneracy, and absence of renderer imports.
- [ ] Request an independent code review against this task and resolve every Critical or Important finding with a new RED/GREEN cycle.
- [ ] Commit only these two files:

```powershell
git add -- src\sjtuclaw\application\spine38_runtime.py tests\unit\test_spine38_runtime.py
git commit -m "feat: derive visible spine frame bounds"
```

---

## Task 2: Fit the Qt Renderer Once to the Visible Relax Frame

**Files:**

- Modify: `src/sjtuclaw/presentation/qt/spine38_renderer.py`
- Modify: `tests/qt/test_spine38_renderer.py`
- Modify: `tests/qt/test_spine38_schwarz_smoke.py`

**Interface consumed:** `_Spine38RenderRuntime.visible_bounds() -> Spine38Bounds`

### Step 1: Extend the fake-runtime contract before production edits

- [ ] Change the fake geometry and `setup_bounds` to `x=-0.5, y=0.0, width=1.0, height=2.0`, then add `visible_bounds_calls` and `visible_bounds()` to `_FakeRuntime` in `tests/qt/test_spine38_renderer.py`. In `mesh_scene`, publish `transform.foot_baseline_y` instead of a hard-coded baseline.
- [ ] Change `test_renderer_sets_relax_once_and_only_advances_time` so initialization must produce these exact calls:

```python
assert runtime.set_animation_calls == [(0, "Relax", True)]
assert runtime.update_calls == [0.0, 0.016, 0.016]
assert runtime.visible_bounds_calls == 1
```

- [ ] Assert the initial transformed scene reaches the exact framing boundaries:

```python
initial_vertices = backends[0].initial_scene.draw_commands[0].vertices
assert min(vertex.position.y for vertex in initial_vertices) == pytest.approx(4.0)
assert max(vertex.position.y for vertex in initial_vertices) == pytest.approx(176.0)
assert renderer.foot_baseline_y == pytest.approx(176.0)
```

- [ ] Add a test where the fake runtime would return different bounds on a second call. Advance multiple frames and assert `visible_bounds_calls == 1`, proving the transform is immutable and cannot pump.
- [ ] Add an initialization failure case where zero-delta evaluation or visible bounds raises `Spine38FrameError`; assert the renderer publishes no scene and returns the existing fixed mesh/runtime failure rather than a traceback.

### Step 2: Add the real-pixel size contract

- [ ] In `test_real_schwarz_renders_three_relax_loops_and_proves_fallback`, retain all existing duration, fallback, checksum, window-count, and Agent-isolation assertions, then add these assertions for every sampled alpha bound:

```python
assert bounds["width"] >= 80
assert bounds["height"] >= 150
assert 172 <= bounds["y"] + bounds["height"] <= 180
```

These thresholds verify meaningful window fill while tolerating transparent texture padding. The fixed transform itself targets a visible geometry height of 172 px and foot baseline y=176 px.

### Step 3: Run unit and real-driver RED

- [ ] Run the Qt unit tests:

```powershell
D:\SJTUClaw\.venv\Scripts\python.exe -m pytest tests\qt\test_spine38_renderer.py -v
```

Expected RED: initialization did not call `update(0.0)`, did not request visible bounds, and still exposes the old y=160 baseline/8 px margin.

- [ ] Run the real approved-asset smoke before changing the renderer:

```powershell
$env:SJTUCLAW_SPINE38_BRIDGE_DLL='D:\SJTUClaw\.worktrees\arkpets-spine-idle-vertical-slice\build\spine38\Release\sjtuclaw_spine38_bridge.dll'
$env:SJTUCLAW_SPINE38_ASSET_ROOT='D:\Spine\test\stage3_idle_rebuild_20260806_145235\runtime_input'
D:\SJTUClaw\.venv\Scripts\python.exe -m pytest tests\qt\test_spine38_schwarz_smoke.py::test_real_schwarz_renders_three_relax_loops_and_proves_fallback -v
```

Expected RED: the existing setup-bounds transform produces approximately 17–18 px width and 28 px height, violating the new minimum size assertions.

If this approved asset root has moved, resolve it from the existing Task 9 report and revalidate the pinned hashes; do not guess, copy, or alter assets.

### Step 4: Implement fixed visible-frame initialization

- [ ] Change the exact renderer constants:

```python
_VIEWPORT = Size(width=160, height=180)
_FOOT_BASELINE_Y = 176.0
_MARGIN = 4.0
```

- [ ] Add `visible_bounds()` to `_Spine38RenderRuntime` and preserve `setup_bounds` for catalog/backward-compatible consumers even though the renderer no longer frames from it.
- [ ] Change `Spine38PetRenderer.initialize()` to use this exact order after texture/catalog validation:

```python
self._runtime.set_animation(0, "Relax", True)
self._runtime.update(0.0)
transform = Spine38ViewportTransform.fit(
    self._runtime.visible_bounds(),
    viewport=viewport,
    foot_baseline_y=_FOOT_BASELINE_Y,
    margin=_MARGIN,
)
scene = self._runtime.mesh_scene(transform, texture)
```

- [ ] Store the resulting transform once exactly as today. Leave `update(delta_seconds)` unchanged so it advances the native animation and rebuilds the scene with the same transform.
- [ ] Preserve existing fixed renderer error mapping and cleanup ownership. A failed zero-delta evaluation or visible-bounds calculation must not publish a partial backend/scene.

### Step 5: Run GREEN, compatibility, and static checks

- [ ] Run:

```powershell
D:\SJTUClaw\.venv\Scripts\python.exe -m pytest tests\unit\test_spine38_runtime.py tests\qt\test_spine38_renderer.py -v
D:\SJTUClaw\.venv\Scripts\python.exe -m pytest tests\qt\test_pet_window.py tests\qt\test_pet_renderer.py -q
```

- [ ] Rerun the exact real smoke command from Step 3. Expected GREEN:
  - all samples have width at least 80 px;
  - all samples have height at least 150 px;
  - every bottom edge is in [172, 180];
  - three `Relax` loops, one window, fallback, checksums, and Agent-isolation assertions still pass.
- [ ] Run:

```powershell
D:\SJTUClaw\.venv\Scripts\python.exe -m ruff check src\sjtuclaw\presentation\qt\spine38_renderer.py tests\qt\test_spine38_renderer.py tests\qt\test_spine38_schwarz_smoke.py
D:\SJTUClaw\.venv\Scripts\python.exe -m mypy --strict src\sjtuclaw\presentation\qt\spine38_renderer.py tests\qt\test_spine38_renderer.py tests\qt\test_spine38_schwarz_smoke.py
git diff --check
```

### Step 6: Review and checkpoint

- [ ] Self-review initialization ordering, single-call behavior, error cleanup, exact constants, and the absence of per-frame refitting.
- [ ] Request an independent code review against the approved design. Resolve every Critical or Important finding with focused RED/GREEN evidence.
- [ ] Commit only the three Task 2 files:

```powershell
git add -- src\sjtuclaw\presentation\qt\spine38_renderer.py tests\qt\test_spine38_renderer.py tests\qt\test_spine38_schwarz_smoke.py
git commit -m "fix: fit spine renderer to visible frame"
```

---

## Task 3: Document, Regress, and Perform the Manual Desktop Checkpoint

**Files:**

- Modify: `docs/spine38_local_vertical_slice.md`
- Read/verify only: `scripts/qt_spine38_vertical_slice.py`
- Read/verify only: `docs/superpowers/specs/2026-08-09-spine38-visible-frame-scaling-design.md`

### Step 1: Update the operator documentation

- [ ] Explain that setup bounds remain catalog evidence but the Qt viewport is framed from the zero-delta evaluated visible `Relax` commands.
- [ ] Document the exact invariants: 160×180 viewport, 4 px top margin, y=176 foot baseline, one-time transform, fully transparent commands excluded, mixed-alpha commands retained wholly.
- [ ] Document the automated real-pixel acceptance thresholds: width ≥80 px, height ≥150 px, bottom edge in [172, 180].
- [ ] Preserve the existing fixed-status, approved-asset, Release-DLL, placeholder, Agent-isolation, and `visual_review_required` instructions.

### Step 2: Run complete automated regression

- [ ] Rebuild and run the pinned Release native contract:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_spine38_bridge.ps1 -Configuration Release -RunTests
```

Expected: CTest 1/1 passes and the wrapper emits `spine38_build_complete`.

- [ ] Run all focused Python/Qt coverage:

```powershell
D:\SJTUClaw\.venv\Scripts\python.exe -m pytest tests\unit\test_spine38_runtime.py tests\unit\test_spine38_native.py tests\qt\test_spine38_renderer.py tests\qt\test_pet_renderer.py tests\qt\test_pet_window.py tests\integration\test_spine38_schwarz_catalog.py -q
```

- [ ] Run the real opt-in smoke once more with the approved Release DLL/assets and retain only ignored evidence.
- [ ] From `D:\SJTUClaw\.worktrees\arkpets-action-runtime`, run the untouched action/runtime regression exactly:

```powershell
D:\SJTUClaw\.venv\Scripts\python.exe -m pytest tests\unit\test_pet_action_sequence_catalog.py tests\unit\test_pet_track0_controller.py tests\unit\test_pet_track0_watchdog.py tests\unit\test_pet_state_animation_compatibility.py tests\unit\test_pet_animation_transactions.py -q
```

Expected: `1169 passed`, with the pre-existing `docs/legal/gpl_migration_audit.md` change untouched.
- [ ] Run final static and repository checks:

```powershell
D:\SJTUClaw\.venv\Scripts\python.exe -m ruff check src\sjtuclaw\application\spine38_runtime.py src\sjtuclaw\presentation\qt\spine38_renderer.py tests\unit\test_spine38_runtime.py tests\qt\test_spine38_renderer.py tests\qt\test_spine38_schwarz_smoke.py
D:\SJTUClaw\.venv\Scripts\python.exe -m mypy --strict src\sjtuclaw\application\spine38_runtime.py src\sjtuclaw\presentation\qt\spine38_renderer.py
git diff --check
git status --short
```

- [ ] Audit status explicitly: no tracked ArkPets assets, DLLs, build output, screenshots, or smoke evidence; no staged unrelated changes.

### Step 3: Commit the documentation

- [ ] Commit only the operator document after its statements are backed by the completed gates:

```powershell
git add -- docs\spine38_local_vertical_slice.md
git commit -m "docs: describe visible spine framing"
```

### Step 4: Launch the human-visible checkpoint without a console window

- [ ] Start the existing diagnostic with `pythonw.exe` so the user sees only the transparent desktop-pet window:

```powershell
Start-Process -FilePath 'D:\SJTUClaw\.venv\Scripts\pythonw.exe' -WorkingDirectory 'D:\SJTUClaw\.worktrees\arkpets-spine-idle-vertical-slice' -ArgumentList @(
  'scripts\qt_spine38_vertical_slice.py',
  '--asset-root', 'D:\Spine\test\stage3_idle_rebuild_20260806_145235\runtime_input',
  '--bridge-dll', 'D:\SJTUClaw\.worktrees\arkpets-spine-idle-vertical-slice\build\spine38\Release\sjtuclaw_spine38_bridge.dll',
  '--animation', 'Relax',
  '--loops', '3'
)
```

- [ ] Ask the user to verify all of the following:
  - Schwarz visibly fills most of the 160×180 window rather than appearing thumbnail-sized;
  - the visible foot line sits immediately above the taskbar with the 4 px safety gap;
  - the character does not visibly pump, jump, or drift as `Relax` loops;
  - transparency, click-through behavior, and fallback remain correct;
  - the animation appearance is acceptable.

- [ ] If the user rejects the visual, record the exact symptom and return to the smallest responsible task with a new automated RED. Do not tune constants ad hoc without updating the design/spec.
- [ ] If the user accepts, mark the parent vertical-slice Task 10 complete in its progress report and state that automated evidence remained `visual_review_required` until this human checkpoint.

### Step 5: Final independent review and handoff

- [ ] Request a final review of the complete scaling delta against the approved design and parent vertical-slice plan.
- [ ] Resolve every Critical or Important finding with TDD and rerun affected gates.
- [ ] Report the exact commits, automated results, ignored evidence location, and manual acceptance outcome. Do not claim visual acceptance unless the user explicitly gives it.
