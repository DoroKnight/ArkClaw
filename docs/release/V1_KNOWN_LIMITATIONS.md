# ArkClaw V1 — Known Limitations

Status: Release Candidate 1 (Alpha). Every item below is a genuine limitation,
not a disguised P0.

## Backend / Runtime
- **Inert submit**: submitting from the Dashboard Composer captures a submitted
  draft snapshot and does not invoke any provider/backend task. The
  ConversationContext, draft, revision and submitted snapshot remain
  authoritative, but no real task runs yet.
- **No provider execution path from the Dashboard**: `Chat / Work` renders
  agent/task state from presentation snapshots only. Real agent execution is
  future work outside V1.
- **Dashboard Spine preview is a placeholder**: the Character Animation page
  shows a labeled preview frame and per-animation selection state. Wiring the
  real Spine presentation seam into the Dashboard preview is not part of V1.
- **Attachment upload is presentation-only**: `Selected locally / Uploading /
  Uploaded / Failed / Retry` states are model states; no real upload transport
  exists.

## Platform
- **Pre-existing native smoke failure**: `test_real_windows_backend_smoke_and_metrics`
  (`scripts/qt_pet_opengl_backend_smoke.py`, check `window_contracts.drag_to_falling`)
  fails on this machine. It is a real-native-window drag simulation, unmodified
  since earlier slices, and it also failed at the Slice 7 final broad gate. It is
  tracked separately and is not caused by Stage 10 changes. Fixing it would touch
  frozen PetWindow drag/native semantics and is deliberately out of V1 scope.
- **Environment-gated skips**: 27 tests skip without the production
  `ARKCLAW_SPINE38_BRIDGE_DLL` / `ARKCLAW_PET_ROLE_MANIFEST` /
  `ARKCLAW_SPINE38_ASSET_ROOT` environment and the native `windows` Qt platform.
  The required native nodes (6A + 6B + Schwarz) run with that environment and
  pass 19/19 with 0 skips.
- **Offscreen tests only exercise offscreen Qt**: screenshots/rendering on a
  real display, DPI transitions on physical monitors, and real resize behavior
  still need manual/native validation beyond the automated native nodes.

## Product Scope
- **No expanded IA**: no Materials/Projects/Tools/Models/Plugins/History, no
  IDE-like panes, no Settings top-level page. The frozen V1 IA (Home,
  Chat / Work, Character Animation) is the only navigation.
- **No fake data**: Home shows an explicit empty state when there is no recent
  work; the Dashboard never fabricates tasks, progress or artifacts.
- **Character inventory is capability-driven**: only actions declared in the
  Active Character manifest appear; unsupported actions show a real disabled
  reason instead of being hidden.

## Performance Baseline Caveats
- Memory figures are process private bytes (Windows `PagefileUsage`); they
  include retained Qt/Python runtime caches and are reported as a baseline for
  drift detection, not an absolute budget.
- The 100-cycle open/close loop is the automated proxy for a long session; a
  true multi-hour soak still requires a manual/native session.
