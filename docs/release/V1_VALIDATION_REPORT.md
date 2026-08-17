# ArkClaw V1 — Validation Report

Status: Release Candidate 1 (Alpha). Date: 2026-08-16.
Environment: Windows, Python 3.13.6, PySide6 6.11.1, pytest 9.1.1, `.venv`.

## Scope

Validation covers the V1 frontend (Desktop Companion + Full Dashboard),
the Stage 10 user journeys, runtime reliability, error handling, performance
baseline, native Windows gates and the release regression matrix.

## Automated Gates

### Stage 10 suites (single pytest process, offscreen)

```text
python -m pytest tests\qt\test_stage10_user_journeys.py \
               tests\qt\test_stage10_runtime_reliability.py \
               tests\qt\test_stage10_error_handling.py -q
13 passed, 0 skipped, exit 0
```

Journeys proven:
- First launch opens Home, enters Chat / Work without crash/blank/stale state.
- Ordinary task: type -> submit -> Thinking -> Working -> Result -> follow-up
  preserves the ONE authoritative ConversationContext + draft.
- Character workflow: view Active Character -> preview -> switch -> return to
  desktop, capability-driven, single page runtime.
- Draft survives a Dashboard open/close cycle (same context id, revision, text).

Reliability proven (100-cycle loops, offscreen, no sleeps):
- open/close reuses the SAME window object; no top-level growth.
- Light/Dark alternation preserves page, draft, context; no second window.
- character snapshot switches rebuild without widget accumulation.
- navigation emits `page_selected` exactly once per selection.
- sequential integration instances leave no top-level residue.

Error handling proven:
- Agent Error renders while context + draft survive; composer usable.
- Failed result renders `Failed` + recovery actions (Open, Export / Save).
- Missing character resource renders Unavailable + reason + Retry (signal
  emitted once); the rest of the Dashboard stays usable.
- Unsupported / Too-large attachments are readable with no fake retry.

### Cross-test isolation (two orders)

```text
order A: dashboard+stage10 files, 130 passed, exit 0
order B: reversed, 130 passed, exit 0
```

### Broad regression (offscreen, workspace basetemp)

```text
python -m pytest tests -q --basetemp=.pytest_tmp_stage10_broad
3407 passed, 1 failed, 27 skipped
```

- The 1 failure is pre-existing: `tests\qt\test_pet_mesh_opengl_backend.py::test_real_windows_backend_smoke_and_metrics`
  (`drag_to_falling`), identical at the Slice 7 final broad gate; not a Stage 10
  regression (see `V1_KNOWN_LIMITATIONS.md`).
- The 27 skips are environment-gated (production Spine bridge/manifest, native
  windows platform, credential/dummy-supervisor opt-in gates).

### Native Windows gates (one compatible process)

```text
ARKCLAW_SPINE38_BRIDGE_DLL + ARKCLAW_PET_ROLE_MANIFEST +
ARKCLAW_SPINE38_ASSET_ROOT + QT_QPA_PLATFORM=windows

pytest tests\qt\test_slice6b_native_cutover.py \
       tests\qt\test_schwarz_native_input.py \
       tests\qt\test_action_palette_native.py -q
19 passed, 0 skipped, exit 0
```

Breakdown: Slice 6B native (7) + Native Schwarz (2) + Slice 6A native (10).

### Smoke scripts

```text
python scripts\qt_pet_smoke.py   -> exit 0 (qt_pet_smoke=True)
python scripts\qt_tray_smoke.py  -> exit 0 (qt_tray_smoke=True)
```

## Performance Baseline (F)

`python scripts\measure_v1_performance.py` writes
`docs\release\v1_performance_baseline.json` (exit 0):

| Metric | Value |
| --- | --- |
| production composition construction | ~1.1 ms |
| Dashboard cold open (create + show) | ~13 ms |
| Dashboard warm reopen (hide + show) | ~0.3 ms |
| private memory, startup | ~25.3 MB |
| private memory, Dashboard open | ~31.8 MB |
| private memory, Dashboard closed | ~31.9 MB |
| private memory, after dispose | ~27.6 MB |
| memory samples every 20 of 100 cycles | flat (~31.9 MB) |
| window identity across 100 cycles | stable |
| visible top-levels after dispose | 0 |

The loop is the automated long-session proxy; flat samples show no unbounded
growth.

## Static Gates

```text
ruff check <stage10 files + dashboard package>        -> All checks passed
mypy --strict --no-incremental <stage10 production>    -> Success (13 files)
```

## Manual / Native Items Still Required

- Real display rendering review of the five frozen renders (A–E) in Light/Dark.
- Physical DPI transition and real resize at 1024x680.
- Multi-hour real-time soak (the automated proxy covers cycle stability).
- Real provider execution path (out of V1 scope by design).
