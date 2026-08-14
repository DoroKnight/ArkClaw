# ArkPets-Compatible Schwarz Original Idle Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Load the hash-pinned Schwarz Ark-Models Spine 3.8 triplet through official `spine-cpp`, enumerate its real animation catalog, and visibly loop the original `Relax` candidate for at least three cycles in ArkClaw's existing transparent pet window with fail-closed placeholder fallback.

**Architecture:** A version-pinned C++17 DLL wraps official `spine-cpp` behind a C ABI and receives already-verified in-memory atlas/skeleton bytes. A framework-neutral Python adapter owns Runtime state and converts evaluated region/mesh/clipped geometry into the existing `PetMeshScene` contract; a Qt renderer sends those scenes to the existing offscreen OpenGL backend and remains contained by `SafePetRenderer`. This milestone uses the legacy direct renderer path and does not enable `PetTrack0Controller` production sequencing or claim completion callbacks for the other logical actions.

**Tech Stack:** Python 3.13.6, PySide6 6.11.1, `ctypes`, C++17, CMake 4.3.0, Visual Studio 2026 x64, official `spine-cpp` 3.8 at commit `8b4844bd4b193ba9e54487ed397a777993cbad56`, Qt OpenGL 3.3 FBO backend, pytest, CTest.

## Global Constraints

- Read assets only from `D:\Spine\test\stage3_idle_rebuild_20260806_145235\runtime_input`; never write into this directory.
- Require these exact SHA-256 values before native parsing: atlas `6D42F85B5FD09F7BBD7F8DF412437BFA3D48628CC42C0BFE9AE2BA0D7329A737`, PNG `7D1654527310334AD658054ACFBAF5E58C2A0719A5A1984662713306F656E2A5`, skeleton `4C7FF39D6322D702E11E7A769457D3E4D77B1A43037F8DEEDF7CD508937DA451`.
- Do not copy `.skel`, `.atlas`, `.png`, `.spine`, screenshots, or Runtime exports into the repository.
- Pin official `spine-runtimes` 3.8 to commit `8b4844bd4b193ba9e54487ed397a777993cbad56`; do not track a moving branch during a build.
- Keep downloaded Runtime source and compiled DLL/PDB files under ignored `build/spine38/`; do not vendor or package them in this milestone.
- Preserve the Spine Runtimes License Agreement in the local build output and record the exact source commit; do not describe it as MIT, Apache, BSD, or project-owned source.
- Do not run ArkPets Java/libGDX, do not use an unofficial Python Spine decoder, and do not operate Spine Editor.
- Keep `Spine38RuntimeAdapter` independent of Qt and all Agent/provider/session/credential/network modules.
- Keep Spine bones, slots, skins, attachments, constraints, animation state, and clipping out of `pet_mesh_model.py` and the generic OpenGL backend.
- Use one existing `PetWindow`; do not add `QOpenGLWidget`, Qt Quick, a second top-level window, or another render loop.
- Any manifest, Runtime, draw conversion, OpenGL, or context failure must leave `SafePetRenderer` on `PlaceholderPetRenderer`; exceptions must not enter the Agent loop.
- Treat `Relax` as a case-sensitive candidate only. The Runtime catalog test must confirm it before the visible smoke starts; absence fails closed instead of selecting a similar name.
- Do not enable Track 1 `breathing`, Track 2 `blink`, the other 24 logical bindings, or production sequencing capabilities in this milestone.
- Do not publish, push, open a PR, or package the Runtime.
- Preserve the current uncommitted OpenGL backend work and the dirty `docs/legal/gpl_migration_audit.md` in the action-runtime worktree.

## Current Verified Baseline

- `codex/pet-opengl-mesh-backend` is at `5d6ff04` with the existing uncommitted OpenGL backend files intact.
- The OpenGL mesh/model suite passes: `15 passed`, including the real Windows driver smoke.
- `codex/arkpets-action-runtime` is independently available at `021bcbe`; its focused sequence/controller suite passes `1169 passed` and is not required to render this idle-only slice.
- The three external asset hashes were recomputed on 2026-08-08 and match the approved manifest.
- Visual Studio Community 2026 has the x64 C++ workload; `cmake --help` exposes generator `Visual Studio 18 2026`.

## File Structure

### Native bridge

- `native/spine38_bridge/CMakeLists.txt`: consume an exact verified Runtime source directory and compile the local DLL plus CTest target.
- `native/spine38_bridge/spine-runtimes.lock.json`: machine-readable repository URL, commit, Runtime data version, and license filename.
- `native/spine38_bridge/include/arkclaw_spine38_bridge.h`: stable C ABI, POD draw views, fixed error codes, and ownership rules.
- `native/spine38_bridge/src/arkclaw_spine38_bridge.cpp`: `spine-cpp` asset loading, catalog, `AnimationState`, region/mesh extraction, `SkeletonClipping`, and exception containment.
- `native/spine38_bridge/tests/spine38_bridge_contract_test.cpp`: invalid-input, catalog, lifecycle, and draw-buffer ownership tests without character assets.
- `scripts/build_spine38_bridge.ps1`: reproducible local Debug/Release configuration and build command.

### Python application and infrastructure

- `src/arkclaw/application/pet_external_assets.py`: retain verified immutable bytes alongside metadata and read-only handle ownership.
- `src/arkclaw/application/spine38_runtime.py`: framework-neutral catalog/draw models, Runtime protocol, transform, and adapter lifecycle.
- `src/arkclaw/infrastructure/spine38_native.py`: `ctypes` binding, DLL ABI/version check, fixed-code conversion, and native handle ownership.
- `src/arkclaw/application/pet_mesh_model.py`: add renderer-neutral slot blend modes only; do not add Spine concepts.
- `src/arkclaw/presentation/qt/pet_mesh_opengl_renderer.py`: implement the new generic blend functions while preserving existing alpha behavior.
- `src/arkclaw/presentation/qt/spine38_renderer.py`: decode the verified PNG, convert evaluated draw data to `PetMeshScene`, and delegate rendering to the generic backend.

### Diagnostics and tests

- `scripts/qt_spine38_vertical_slice.py`: explicit one-window catalog/visible/fallback smoke; never selected by default application startup.
- `tests/unit/test_pet_external_assets.py`: immutable verified-byte snapshot and hash-failure tests.
- `tests/unit/test_spine38_runtime.py`: adapter, catalog, exact-name gate, transform, and draw conversion tests with a fake native port.
- `tests/unit/test_spine38_native.py`: DLL-path, ABI, error, lifecycle, and import-isolation tests with a fake `ctypes` library.
- `tests/unit/test_pet_mesh_model.py`: generic blend-mode validation tests.
- `tests/qt/test_pet_mesh_opengl_backend.py`: pixel tests for generic additive/multiply/screen behavior and existing regression coverage.
- `tests/qt/test_spine38_renderer.py`: fake-runtime renderer lifecycle, frame replacement, and `SafePetRenderer` fallback tests.
- `tests/integration/test_spine38_schwarz_catalog.py`: opt-in tests against the external Schwarz triplet and compiled bridge.
- `tests/qt/test_spine38_schwarz_smoke.py`: opt-in subprocess assertion over the three-loop Windows smoke JSON.
- `docs/rendering/spine38_local_vertical_slice.md`: local build/run instructions, evidence schema, license boundary, and precise non-claims.

---

### Task 1: Freeze the native source and build contract

**Files:**
- Create: `native/spine38_bridge/spine-runtimes.lock.json`
- Create: `native/spine38_bridge/CMakeLists.txt`
- Create: `native/spine38_bridge/src/arkclaw_spine38_bridge.cpp`
- Create: `scripts/build_spine38_bridge.ps1`
- Create: `tests/unit/test_spine38_build_contract.py`

**Interfaces:**
- Consumes: CMake generator `Visual Studio 18 2026`; official Git repository URL and exact commit from Global Constraints.
- Produces: `build/spine38/Release/arkclaw_spine38_bridge.dll`, copied upstream `LICENSE`, and `spine38-build-manifest.json` containing commit, configuration, architecture, and bridge ABI.

- [ ] **Step 1: Write failing build-wrapper behavior tests**

```python
def test_build_wrapper_prints_the_pinned_source_manifest() -> None:
    completed = run_build_wrapper("-PrintSourceManifest")
    assert completed.returncode == 0
    assert json.loads(completed.stdout) == EXPECTED_PINNED_SOURCE_MANIFEST


def test_build_wrapper_rejects_a_checkout_at_the_wrong_commit(tmp_path: Path) -> None:
    wrong_checkout = create_one_commit_git_repository(tmp_path)
    completed = run_build_wrapper(
        "-ValidateSourceOnly",
        "-SpineSource",
        str(wrong_checkout),
    )
    assert completed.returncode == 2
    assert completed.stdout.strip() == "spine38_source_commit_mismatch"
```

`EXPECTED_PINNED_SOURCE_MANIFEST` is a hand-written literal in the test. The test runs the PowerShell artifact and asserts its observable output; it does not grep `.gitignore`, the lock file, or the script source.

- [ ] **Step 2: Run the tests and confirm the missing lock fails**

Run: `.venv\Scripts\python.exe -m pytest tests\unit\test_spine38_build_contract.py -v`

Expected: two test failures inside the test bodies because the build wrapper/lock behavior does not exist yet; pytest collection succeeds.

- [ ] **Step 3: Add the lock, CMake build, and PowerShell wrapper**

The PowerShell wrapper must clone the official repository into ignored `build/spine38/source/` on the first build, check out the exact commit in detached-HEAD state, and verify `git rev-parse HEAD` on every build. CMake must perform no network access: it receives the verified checkout through required `SPINE_RUNTIMES_SOURCE_DIR`, builds the official `spine-cpp/spine-cpp/src/spine/*.cpp` sources as a static internal target, compiles the local bridge as a shared library, copies the upstream `LICENSE` beside the DLL, and enables CTest. The initial bridge source exports only `arkclaw_spine38_abi_version()` returning `1`; Task 3 replaces the stub with the catalog implementation.

```cmake
cmake_minimum_required(VERSION 3.25)
project(arkclaw_spine38_bridge LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(SPINE_RUNTIMES_SOURCE_DIR "" CACHE PATH "Exact pinned spine-runtimes checkout")
if(NOT EXISTS "${SPINE_RUNTIMES_SOURCE_DIR}/spine-cpp/spine-cpp/include/spine/spine.h")
  message(FATAL_ERROR "SPINE_RUNTIMES_SOURCE_DIR is not a spine-runtimes checkout")
endif()
file(GLOB SPINE38_SOURCES CONFIGURE_DEPENDS
  "${SPINE_RUNTIMES_SOURCE_DIR}/spine-cpp/spine-cpp/src/spine/*.cpp")
add_library(spine38_runtime STATIC ${SPINE38_SOURCES})
target_include_directories(spine38_runtime PUBLIC
  "${SPINE_RUNTIMES_SOURCE_DIR}/spine-cpp/spine-cpp/include")
set_target_properties(spine38_runtime PROPERTIES POSITION_INDEPENDENT_CODE ON)
add_library(arkclaw_spine38_bridge SHARED
  src/arkclaw_spine38_bridge.cpp)
target_link_libraries(arkclaw_spine38_bridge PRIVATE spine38_runtime)
target_include_directories(arkclaw_spine38_bridge PUBLIC include)
```

The PowerShell script must configure x64 Release by default, use an explicit repository-relative build directory, fail if the produced DLL or copied license is missing, and emit only fixed build-stage codes plus ordinary compiler output.

- [ ] **Step 4: Re-run source-lock tests**

Run: `.venv\Scripts\python.exe -m pytest tests\unit\test_spine38_build_contract.py -v`

Expected: PASS.

- [ ] **Step 5: Configure and compile the empty bridge target**

Run: `powershell -ExecutionPolicy Bypass -File scripts\build_spine38_bridge.ps1 -Configuration Release`

Expected: the pinned source is fetched once, CMake uses `Visual Studio 18 2026` x64, the DLL and Runtime license appear only under ignored `build/spine38/`, and CTest is discoverable.

- [ ] **Step 6: Commit the build contract**

```powershell
git add native/spine38_bridge/CMakeLists.txt native/spine38_bridge/spine-runtimes.lock.json native/spine38_bridge/src/arkclaw_spine38_bridge.cpp scripts/build_spine38_bridge.ps1 tests/unit/test_spine38_build_contract.py
git commit -m "build: pin spine cpp 3.8 bridge"
```

### Task 2: Preserve verified asset bytes atomically

**Files:**
- Modify: `src/arkclaw/application/pet_external_assets.py`
- Modify: `tests/unit/test_pet_external_assets.py`

**Interfaces:**
- Consumes: `ExternalPetAssetLoader.load(descriptor)` and the existing read-only Windows filesystem handles.
- Produces: `ExternalPetAssetSnapshot(skeleton_bytes: bytes, atlas_bytes: bytes, texture_bytes: bytes)` exposed through `ExternalPetAssetBundle.snapshot`; bytes correspond exactly to the hashes in `bundle.metadata`.

- [ ] **Step 1: Write failing snapshot tests**

```python
def test_successful_load_retains_the_verified_bytes() -> None:
    result = loader.load(valid_descriptor())
    assert result.succeeded
    assert result.bundle is not None
    assert result.bundle.snapshot.skeleton_bytes == skeleton_bytes
    assert result.bundle.snapshot.atlas_bytes == atlas_bytes
    assert result.bundle.snapshot.texture_bytes == texture_bytes


def test_hash_failure_publishes_no_snapshot() -> None:
    result = loader.load(descriptor_with_wrong_skeleton_hash())
    assert result.status is ExternalPetAssetStatus.HASH_MISMATCH
    assert result.bundle is None
```

- [ ] **Step 2: Verify the tests fail on the absent snapshot**

Run: `.venv\Scripts\python.exe -m pytest tests\unit\test_pet_external_assets.py -v`

Expected: FAIL because `ExternalPetAssetBundle.snapshot` is absent.

- [ ] **Step 3: Retain full bytes in the existing verified read pass**

Extend `_ReadResult` with `data: bytes`, accumulate chunks once, and create the frozen snapshot only after size, identity, hash, PNG, atlas, and version validation all succeed. Keep the open handles and existing close order unchanged; do not reopen native paths.

```python
@dataclass(frozen=True, slots=True, repr=False)
class ExternalPetAssetSnapshot:
    skeleton_bytes: bytes
    atlas_bytes: bytes
    texture_bytes: bytes
```

- [ ] **Step 4: Run asset tests**

Run: `.venv\Scripts\python.exe -m pytest tests\unit\test_pet_external_assets.py tests\unit\test_pet_renderer_model.py -v`

Expected: PASS, including hash mismatch, changed-during-read, limits, and handle cleanup.

- [ ] **Step 5: Commit the immutable asset handoff**

```powershell
git add src/arkclaw/application/pet_external_assets.py tests/unit/test_pet_external_assets.py
git commit -m "feat: retain verified spine asset bytes"
```

### Task 3: Implement the catalog-only C ABI

**Files:**
- Create: `native/spine38_bridge/include/arkclaw_spine38_bridge.h`
- Modify: `native/spine38_bridge/src/arkclaw_spine38_bridge.cpp`
- Create: `native/spine38_bridge/tests/spine38_bridge_contract_test.cpp`
- Modify: `native/spine38_bridge/CMakeLists.txt`

**Interfaces:**
- Consumes: verified skeleton and atlas byte spans plus a fixed texture-page identifier.
- Produces: ABI version, Runtime handle, exact animation names/durations, skin names, setup bounds, and fixed error codes; every pointer returned by a view remains valid only until the next mutating call or destroy.

- [ ] **Step 1: Define the failing CTest contract**

The character-asset-free contract must assert ABI version `1`, null/empty input rejection, NULL-safe native destroy with exactly-once non-null destroy, no C++ exception crossing the ABI, buffer-capacity rejection, and deterministic fixed error values. Task 4's owning Python `close()` is idempotent; the fixed raw-pointer native destroy is not. Exact catalog values are covered by Task 5's opt-in real-asset integration test.

```cpp
enum ArkClawSpine38Code {
    ARKCLAW_SPINE38_OK = 0,
    ARKCLAW_SPINE38_INVALID_ARGUMENT = 1,
    ARKCLAW_SPINE38_ATLAS_LOAD_FAILED = 2,
    ARKCLAW_SPINE38_SKELETON_LOAD_FAILED = 3,
    ARKCLAW_SPINE38_ANIMATION_NOT_FOUND = 4,
    ARKCLAW_SPINE38_RUNTIME_FAILURE = 5
};

extern "C" uint32_t arkclaw_spine38_abi_version(void);
extern "C" ArkClawSpine38Code arkclaw_spine38_create(
    const uint8_t* skeleton, size_t skeleton_size,
    const char* atlas, size_t atlas_size,
    ArkClawSpine38Handle** out_handle);
extern "C" void arkclaw_spine38_destroy(ArkClawSpine38Handle* handle);
extern "C" size_t arkclaw_spine38_animation_count(const ArkClawSpine38Handle* handle);
extern "C" ArkClawSpine38Code arkclaw_spine38_animation_info(
    const ArkClawSpine38Handle* handle, size_t index,
    char* name_utf8, size_t name_capacity, float* duration_seconds);
```

- [ ] **Step 2: Build and confirm CTest fails**

Run: `powershell -ExecutionPolicy Bypass -File scripts\build_spine38_bridge.ps1 -Configuration Debug -RunTests`

Expected: build or link failure because the C ABI implementation is absent.

- [ ] **Step 3: Implement load, catalog, skin, and setup-bounds ownership**

Implement a texture loader that records atlas page identity without opening the PNG. Construct `spine::Atlas` from the verified atlas bytes, `spine::SkeletonBinary` with `spine::AtlasAttachmentLoader`, reject any Runtime parse error, then own `SkeletonData`, `Skeleton`, `AnimationStateData`, and `AnimationState` in one opaque handle. Catch all exceptions at every exported function and return a fixed enum.

- [ ] **Step 4: Run CTest and Python build-contract tests**

Run: `ctest --test-dir build\spine38 -C Debug --output-on-failure`

Run: `.venv\Scripts\python.exe -m pytest tests\unit\test_spine38_build_contract.py -v`

Expected: both PASS.

- [ ] **Step 5: Commit the catalog bridge**

```powershell
git add native/spine38_bridge
git commit -m "feat: expose spine 3.8 catalog bridge"
```

### Task 4: Bind the C ABI safely through `ctypes`

**Files:**
- Create: `src/arkclaw/infrastructure/spine38_native.py`
- Create: `tests/unit/test_spine38_native.py`

**Interfaces:**
- Consumes: an explicit absolute DLL path and `ExternalPetAssetSnapshot` byte values.
- Produces: `Spine38CatalogNativePort` with `catalog()`, `skins()`, `setup_bounds()`, and idempotent `close()`; Task 6 extends this protocol with playback and draw methods.

- [ ] **Step 1: Write failing binding and isolation tests**

```python
def test_native_binding_rejects_wrong_abi(fake_library: FakeLibrary) -> None:
    native = importlib.import_module("arkclaw.infrastructure.spine38_native")
    fake_library.abi_version = 2
    with pytest.raises(native.Spine38NativeError) as caught:
        native.Spine38NativeLibrary(fake_library)
    assert caught.value.code is native.Spine38NativeCode.ABI_MISMATCH


def test_native_module_has_no_agent_imports() -> None:
    source = inspect.getsource(spine38_native)
    assert all(word not in source for word in ("AgentLoop", "Provider", "SecretStore"))
```

- [ ] **Step 2: Confirm tests fail before the module exists**

Run: `.venv\Scripts\python.exe -m pytest tests\unit\test_spine38_native.py -v`

Expected: pytest collects the test, then FAILS inside the test body with `ModuleNotFoundError` for `arkclaw.infrastructure.spine38_native`.

- [ ] **Step 3: Implement exact signatures and ownership**

Declare every `argtypes` and `restype`, keep Python byte buffers alive for the full create call, copy catalog strings immediately, convert only fixed numeric codes to `Spine38NativeError`, and use `weakref.finalize` only as a last-resort leak guard while normal code calls `close()` explicitly.

```python
class Spine38CatalogNativePort(Protocol):
    def catalog(self) -> tuple[Spine38AnimationInfo, ...]: ...
    def skins(self) -> tuple[str, ...]: ...
    def setup_bounds(self) -> Spine38Bounds: ...
    def close(self) -> None: ...
```

- [ ] **Step 4: Run binding tests and mypy**

Run: `.venv\Scripts\python.exe -m pytest tests\unit\test_spine38_native.py -v`

Run: `.venv\Scripts\python.exe -m mypy src\arkclaw\infrastructure\spine38_native.py tests\unit\test_spine38_native.py`

Expected: PASS.

- [ ] **Step 5: Commit the native binding**

```powershell
git add src/arkclaw/infrastructure/spine38_native.py tests/unit/test_spine38_native.py
git commit -m "feat: bind spine 3.8 catalog dll"
```

### Task 5: Enumerate the real Schwarz catalog and gate `Relax`

**Files:**
- Create: `src/arkclaw/application/spine38_runtime.py`
- Create: `tests/unit/test_spine38_runtime.py`
- Create: `tests/integration/test_spine38_schwarz_catalog.py`
- Create: `scripts/qt_spine38_vertical_slice.py`

**Interfaces:**
- Consumes: `ExternalPetAssetBundle.snapshot`, `Spine38CatalogNativePort`, and exact requested name `Relax`.
- Produces: immutable `Spine38Catalog`, explicit `require_animation("Relax")`, and a `--list-only` JSON audit under ignored `build/spine38/evidence/`.

- [ ] **Step 1: Write failing exact-name and no-guess tests**

```python
def test_exact_relax_candidate_is_required() -> None:
    runtime = importlib.import_module("arkclaw.application.spine38_runtime")
    catalog = runtime.Spine38Catalog((runtime.Spine38AnimationInfo("Relax", 3.2),))
    assert catalog.require_animation("Relax").duration_seconds == 3.2
    with pytest.raises(runtime.Spine38CatalogError):
        catalog.require_animation("relax")


def test_catalog_never_selects_by_similarity() -> None:
    catalog = Spine38Catalog((Spine38AnimationInfo("Relax_A", 3.2),))
    with pytest.raises(Spine38CatalogError):
        catalog.require_animation("Relax")
```

- [ ] **Step 2: Confirm the unit test fails before the application adapter exists**

Run: `.venv\Scripts\python.exe -m pytest tests\unit\test_spine38_runtime.py -v`

Expected: pytest collects the test, then FAILS inside the test body with `ModuleNotFoundError` for `arkclaw.application.spine38_runtime`.

- [ ] **Step 3: Implement catalog models and list-only CLI mode**

The script must require explicit `--bridge-dll` and `--asset-root`, build the existing `ExternalPetAssetDescriptor` with the three exact hashes, call `ExternalPetAssetLoader(WindowsExternalPetAssetFilesystem())`, load the native adapter only after success, write catalog/hash/Runtime-commit JSON under `build/`, print content-free status JSON to stdout, and close bundle/native resources in reverse order.

- [ ] **Step 4: Run the real catalog probe**

Run:

```powershell
.venv\Scripts\python.exe scripts\qt_spine38_vertical_slice.py --list-only --bridge-dll "build\spine38\Release\arkclaw_spine38_bridge.dll" --asset-root "D:\Spine\test\stage3_idle_rebuild_20260806_145235\runtime_input"
```

Expected: exit `0`; all three recomputed hashes match; the JSON contains every exact animation name and positive duration; `Relax` appears exactly once. If `Relax` is absent, stop execution at this task and report `spine38_relax_unconfirmed` without choosing another animation.

- [ ] **Step 5: Run the opt-in catalog integration test**

```powershell
$env:ARKCLAW_SPINE38_BRIDGE_DLL=(Resolve-Path "build\spine38\Release\arkclaw_spine38_bridge.dll")
$env:ARKCLAW_SPINE38_ASSET_ROOT='D:\Spine\test\stage3_idle_rebuild_20260806_145235\runtime_input'
.venv\Scripts\python.exe -m pytest tests\integration\test_spine38_schwarz_catalog.py -v
```

Expected: PASS with exact hashes, Spine version `3.8.x`, nonempty skin/catalog, positive durations, and exact `Relax` confirmation. The test skips with an explicit reason when either environment variable is absent.

- [ ] **Step 6: Commit catalog inspection**

```powershell
git add src/arkclaw/application/spine38_runtime.py tests/unit/test_spine38_runtime.py tests/integration/test_spine38_schwarz_catalog.py scripts/qt_spine38_vertical_slice.py
git commit -m "feat: inspect original schwarz animations"
```

### Task 6: Evaluate `Relax` and expose renderer-neutral draw views

**Files:**
- Modify: `native/spine38_bridge/include/arkclaw_spine38_bridge.h`
- Modify: `native/spine38_bridge/src/arkclaw_spine38_bridge.cpp`
- Modify: `native/spine38_bridge/tests/spine38_bridge_contract_test.cpp`
- Modify: `src/arkclaw/infrastructure/spine38_native.py`
- Modify: `tests/unit/test_spine38_native.py`

**Interfaces:**
- Consumes: exact physical animation name, loop flag, nonnegative delta seconds, and one atlas page.
- Produces: evaluated draw commands with world vertices, UVs, triangle indices, multiplied RGBA, texture-page index, draw order, and renderer-neutral blend mode. Spine clipping is already applied by `spine::SkeletonClipping`; no Spine clipping attachment crosses the ABI.

The extended Python protocol is:

```python
class Spine38NativePort(Spine38CatalogNativePort, Protocol):
    def set_animation(self, track: int, name: str, loop: bool) -> None: ...
    def update(self, delta_seconds: float) -> None: ...
    def draw_commands(self) -> tuple[Spine38DrawCommand, ...]: ...
```

- [ ] **Step 1: Add failing playback/draw contract tests**

Character-asset-free CTests must reject null handles, negative/nonfinite delta, undersized output views, and invalid draw indices with fixed codes. Task 8's injected fake proves `setAnimation(0, name, true)` is issued only once, while Task 9's opt-in real-asset smoke exercises region/mesh/clipping output across three full `Relax` cycles.

```cpp
struct ArkClawSpine38Vertex {
    float x, y, u, v;
    uint8_t r, g, b, a;
};

struct ArkClawSpine38DrawView {
    const ArkClawSpine38Vertex* vertices;
    size_t vertex_count;
    const uint32_t* indices;
    size_t index_count;
    uint32_t texture_page;
    uint32_t blend_mode;
    int32_t draw_order;
};
```

- [ ] **Step 2: Run CTest and observe missing playback exports**

Run: `powershell -ExecutionPolicy Bypass -File scripts\build_spine38_bridge.ps1 -Configuration Debug -RunTests`

Expected: build/link failure for absent playback/draw exports.

- [ ] **Step 3: Implement official Runtime evaluation**

On each update call: validate delta, call `AnimationState.update(delta)`, apply it to the skeleton, update world transforms, walk current skeleton draw order, handle `RegionAttachment` and `MeshAttachment`, multiply skeleton/slot/attachment colors, map all Runtime slot blend modes, call `SkeletonClipping.clipStart/clipTriangles/clipEnd`, and materialize owned vectors in the opaque handle. Reject unsupported attachment types instead of partially drawing them.

- [ ] **Step 4: Rebuild and run native plus Python binding tests**

Run: `powershell -ExecutionPolicy Bypass -File scripts\build_spine38_bridge.ps1 -Configuration Release -RunTests`

Run: `.venv\Scripts\python.exe -m pytest tests\unit\test_spine38_native.py -v`

Expected: PASS.

- [ ] **Step 5: Commit Runtime evaluation**

```powershell
git add native/spine38_bridge src/arkclaw/infrastructure/spine38_native.py tests/unit/test_spine38_native.py
git commit -m "feat: evaluate spine 3.8 draw data"
```

### Task 7: Extend the generic mesh backend for Spine slot blend modes

**Files:**
- Modify: `src/arkclaw/application/pet_mesh_model.py`
- Modify: `src/arkclaw/presentation/qt/pet_mesh_opengl_renderer.py`
- Modify: `tests/unit/test_pet_mesh_model.py`
- Modify: `tests/qt/test_pet_mesh_opengl_backend.py`
- Modify: `docs/rendering/pet_opengl_mesh_backend.md`

**Interfaces:**
- Consumes: `PetMeshBlendMode.NORMAL_STRAIGHT`, `NORMAL_PREMULTIPLIED`, `ADDITIVE`, `MULTIPLY`, and `SCREEN`.
- Produces: deterministic OpenGL blend factors with existing ordinary/PMA behavior preserved and no Spine-specific enum names.

- [ ] **Step 1: Add failing renderer-neutral blend tests**

Generate one-pixel foreground/background textures at test runtime and compare OpenGL output to integer-tolerant expected RGBA for normal straight, normal premultiplied, additive, multiply, and screen. Keep the existing `STRAIGHT_ALPHA` and `PREMULTIPLIED_ALPHA` values as compatibility aliases if renaming would break current callers.

- [ ] **Step 2: Run focused tests and confirm new enum cases fail**

Run: `.venv\Scripts\python.exe -m pytest tests\unit\test_pet_mesh_model.py tests\qt\test_pet_mesh_opengl_backend.py -v`

Expected: FAIL because additive/multiply/screen are absent.

- [ ] **Step 3: Implement exact blend functions**

Keep alpha convention separate from slot compositing in the model documentation. Set `glBlendFuncSeparate` per command and restore no global semantic state. Preserve transparent FBO clearing, stable draw order, stencil behavior, and fixed errors.

- [ ] **Step 4: Run the full OpenGL backend smoke**

Run: `.venv\Scripts\python.exe -m pytest tests\unit\test_pet_mesh_model.py tests\qt\test_pet_mesh_opengl_backend.py -v`

Expected: all prior 15 tests plus the new blend cases PASS; existing UV, alpha, clipping, DPI, lifecycle, context fault, and persistent-upload assertions remain green.

- [ ] **Step 5: Commit generic blend support**

```powershell
git add src/arkclaw/application/pet_mesh_model.py src/arkclaw/presentation/qt/pet_mesh_opengl_renderer.py tests/unit/test_pet_mesh_model.py tests/qt/test_pet_mesh_opengl_backend.py docs/rendering/pet_opengl_mesh_backend.md
git commit -m "feat: support generic mesh blend modes"
```

### Task 8: Convert Runtime frames and render in the existing pet window

**Files:**
- Modify: `src/arkclaw/application/spine38_runtime.py`
- Create: `src/arkclaw/presentation/qt/spine38_renderer.py`
- Modify: `tests/unit/test_spine38_runtime.py`
- Create: `tests/qt/test_spine38_renderer.py`
- Modify: `scripts/qt_spine38_vertical_slice.py`

**Interfaces:**
- Consumes: verified PNG bytes, `Spine38NativePort`, fixed `Relax` binding, logical viewport `Size(160, 180)`, and elapsed seconds from `PetWindow`.
- Produces: `Spine38PetRenderer` implementing existing `PetRenderer`; each evaluated frame becomes a validated `PetMeshScene` and is rendered through `OpenGLTexturedMeshBackend`.

- [ ] **Step 1: Write failing transform, conversion, and lifecycle tests**

```python
def test_transform_is_fixed_from_setup_bounds() -> None:
    transform = Spine38ViewportTransform.fit(
        Spine38Bounds(-20.0, 0.0, 40.0, 100.0),
        viewport=Size(160, 180),
        foot_baseline_y=160.0,
        margin=8.0,
    )
    assert transform.point(0.0, 0.0).y == pytest.approx(160.0)
    assert transform.point(0.0, 100.0).y >= 8.0


def test_renderer_sets_relax_once_and_only_advances_time(fake_runtime) -> None:
    module = importlib.import_module("arkclaw.presentation.qt.spine38_renderer")
    renderer = module.Spine38PetRenderer(fake_runtime, verified_texture_bytes)
    renderer.initialize(Size(160, 180))
    renderer.update(0.016)
    renderer.update(0.016)
    assert fake_runtime.set_animation_calls == [(0, "Relax", True)]
    assert fake_runtime.update_calls == [0.016, 0.016]
```

- [ ] **Step 2: Run tests and confirm the renderer is absent**

Run: `.venv\Scripts\python.exe -m pytest tests\unit\test_spine38_runtime.py tests\qt\test_spine38_renderer.py -v`

Expected: pytest collects the test, then FAILS inside the test body with `ModuleNotFoundError` for `arkclaw.presentation.qt.spine38_renderer`.

- [ ] **Step 3: Implement fixed transform and Qt renderer**

Decode the verified PNG with `QImage.fromData`, require RGBA conversion and atlas-dimension match, create one renderer-neutral texture ID, map native commands without reordering, validate each scene, and call backend `set_scene`. Compute scale/origin once from setup bounds so per-frame bounds cannot resize or vertically pump the character. `animation_capability()` reports only the directly tested idle visual and must not advertise completion/loop-boundary metadata to `PetTrack0Controller`.

- [ ] **Step 4: Add fail-closed lifecycle behavior**

Any catalog, texture, update, draw, mesh validation, OpenGL, or close failure raises only a fixed renderer exception; `SafePetRenderer` catches it and replaces the delegate. `close()` must release OpenGL before native Runtime and asset handles and remain idempotent.

- [ ] **Step 5: Run renderer and existing window tests**

Run: `.venv\Scripts\python.exe -m pytest tests\qt\test_spine38_renderer.py tests\qt\test_pet_window.py tests\qt\test_pet_renderer.py -v`

Expected: PASS; no second window or Agent import is introduced.

- [ ] **Step 6: Commit the visible renderer**

```powershell
git add src/arkclaw/application/spine38_runtime.py src/arkclaw/presentation/qt/spine38_renderer.py tests/unit/test_spine38_runtime.py tests/qt/test_spine38_renderer.py scripts/qt_spine38_vertical_slice.py
git commit -m "feat: render original schwarz idle"
```

### Task 9: Prove three loops and hash-failure fallback

**Files:**
- Modify: `scripts/qt_spine38_vertical_slice.py`
- Create: `tests/qt/test_spine38_schwarz_smoke.py`
- Create: `docs/rendering/spine38_local_vertical_slice.md`

**Interfaces:**
- Consumes: exact `Relax` duration from the Runtime catalog, explicit DLL/asset arguments, and `--loops 3`.
- Produces: a single transparent `PetWindow`, automatic stop after at least `3 * duration`, local audit JSON, and a second nonvisual wrong-hash run proving placeholder fallback.

- [ ] **Step 1: Write the failing subprocess smoke assertion**

The opt-in test must assert fixed schema fields rather than screenshots:

```python
assert result["animation"] == "Relax"
assert result["completed_elapsed_seconds"] >= 3 * result["duration_seconds"]
assert result["sampled_nontransparent_frames"] >= 3
assert result["renderer_safe_code"] == "none"
assert result["forced_hash_failure"]["bridge_constructed"] is False
assert result["forced_hash_failure"]["using_placeholder"] is True
assert result["agent_modules_imported"] is False
```

- [ ] **Step 2: Run the test and confirm the incomplete smoke schema fails**

Run: `.venv\Scripts\python.exe -m pytest tests\qt\test_spine38_schwarz_smoke.py -v`

Expected: SKIP without explicit environment variables; with them set, FAIL until three-loop/fallback evidence is implemented.

- [ ] **Step 3: Implement timed three-loop evidence**

Use the Runtime-reported `Relax` duration only for diagnostic stop/evidence, not sequence advancement. Sample alpha bounds and a small vertex checksum near 0%, 50%, 100%, and both sides of each loop boundary. Store audit JSON under ignored `build/spine38/evidence/`; do not save or commit character screenshots.

- [ ] **Step 4: Implement deliberate hash mismatch before Runtime construction**

Create a second descriptor in memory with one altered skeleton hash, assert the asset loader returns `HASH_MISMATCH`, assert the bridge factory was never called, and initialize `SafePetRenderer(PlaceholderPetRenderer())` with fixed safe code. Keep the visible successful run and nonvisual fallback proof in one diagnostic process without opening a second window.

- [ ] **Step 5: Run the visible Windows smoke**

```powershell
.venv\Scripts\python.exe scripts\qt_spine38_vertical_slice.py --bridge-dll "build\spine38\Release\arkclaw_spine38_bridge.dll" --asset-root "D:\Spine\test\stage3_idle_rebuild_20260806_145235\runtime_input" --animation Relax --loops 3
```

Expected: exactly one transparent pet window displays Schwarz; `Relax` plays continuously for at least three reported durations; the process exits cleanly and prints fixed-schema success JSON. Manual visual acceptance checks weapon/attachments, missing regions, clipping, obvious mesh intersections, foot drift, and boundary jump. If any check is uncertain, record `visual_review_required` and stop without accepting the slice.

- [ ] **Step 6: Run the automated smoke assertion**

With the Task 5 environment variables still set, run:

Run: `.venv\Scripts\python.exe -m pytest tests\qt\test_spine38_schwarz_smoke.py -v`

Expected: PASS.

- [ ] **Step 7: Document exact non-claims and commit**

The document must state that only original `Relax` direct playback is proven; other logical actions, `breathing`, `blink`, Track 1/2, production callbacks, action sequencing, Runtime export, packaging, and publication remain incomplete.

```powershell
git add scripts/qt_spine38_vertical_slice.py tests/qt/test_spine38_schwarz_smoke.py docs/rendering/spine38_local_vertical_slice.md
git commit -m "test: verify schwarz idle vertical slice"
```

### Task 10: Run regression and isolation gates

**Files:**
- Modify only if a failing test demonstrates a defect in files introduced by Tasks 1-9.

**Interfaces:**
- Consumes: completed vertical slice.
- Produces: evidence that placeholder rendering, existing OpenGL behavior, action Runtime invariants, and Agent lifecycle remain unchanged.

- [ ] **Step 1: Run formatting and static checks**

Run: `.venv\Scripts\python.exe -m ruff check src tests scripts`

Run: `.venv\Scripts\python.exe -m mypy`

Expected: PASS.

- [ ] **Step 2: Run native tests**

Run: `ctest --test-dir build\spine38 -C Release --output-on-failure`

Expected: PASS.

- [ ] **Step 3: Run the full Python/Qt suite**

Run: `.venv\Scripts\python.exe -m pytest -q`

Expected: PASS; opt-in external-asset tests skip unless their two environment variables are explicitly set.

- [ ] **Step 4: Re-run the action Runtime focused suite from its untouched worktree**

```powershell
D:\ArkClaw\.venv\Scripts\python.exe -m pytest tests\unit\test_pet_action_sequence_catalog.py tests\unit\test_pet_track0_controller.py tests\unit\test_pet_track0_watchdog.py tests\unit\test_pet_state_animation_compatibility.py tests\unit\test_pet_animation_transactions.py -q
```

Working directory: `D:\ArkClaw\.worktrees\arkpets-action-runtime`

Expected: `1169 passed`; the pre-existing modified `docs/legal/gpl_migration_audit.md` remains untouched.

- [ ] **Step 5: Verify repository and asset boundaries**

Run:

```powershell
git status --short
git ls-files | Select-String -Pattern '\.(skel|atlas|png|spine|dll|pdb)$'
```

Expected: no character assets, screenshots, Runtime DLLs, or PDBs are tracked; only intentional source/tests/docs changes appear.

- [ ] **Step 6: Record final local evidence without publishing**

Keep `build/spine38/evidence/*.json` local and ignored. Do not push, open a PR, package, or claim completion beyond the non-claims in Task 9.

## Execution Checkpoints

1. **Catalog checkpoint after Task 5:** continue only if official Runtime enumeration confirms exact `Relax` and positive duration.
2. **Renderer checkpoint after Task 8:** continue only if fake-runtime Qt tests and existing window tests pass.
3. **Visual checkpoint after Task 9:** stop for user observation if boundary, attachment, clipping, or foot behavior is uncertain.
4. **Completion checkpoint after Task 10:** report local evidence only; leave default ArkClaw renderer and production action sequencing unchanged.
