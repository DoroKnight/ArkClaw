# ArkClaw V1 — Release Notes

Status: **Release Candidate 1 (Alpha)** — local-first Windows desktop AI companion.
Audience: engineering reviewers, release owners, early testers.

## What V1 Is

ArkClaw V1 is the first usable end-to-end frontend for the ArkClaw desktop
companion. It presents the frozen interaction and visual contracts through two
surfaces of one product:

- **Desktop Companion** — the Active Character on the desktop with the Action
  Palette, Conversation Capsule, tray and safe-exit facilities.
- **Full Dashboard** — App Shell with `Home`, `Chat / Work` and
  `Character Animation`, sharing the one authoritative presentation state.

## Included Capabilities

### Desktop Companion
- Active Character (reference asset: Schwarz) rendered through the production
  Spine 3.8 runtime with a programmable-pet fallback when assets fail.
- Right Click Schwarz → Action Palette at ROOT (Qt `Tool | FramelessWindowHint`
  strategy); same-shell Character / System layers with Back/Escape to ROOT.
- Left Click Interact, drag with the frozen threshold, falling/landing, and
  autonomous action scheduling.
- Conversation Capsule bound to the ONE authoritative ConversationContext,
  draft, revision and IME-safe submit semantics.
- Tray, single-instance, safe shutdown, and Windows autostart facilities.

### Full Dashboard
- App Shell: 56 px top bar, expanded/collapsed Navigation (208 px / 72 px),
  40 px page gutter, 1120 px content max — all from the frozen design tokens.
- Home: greeting, primary Ask entry, Continue Recent Work (explicit empty
  state when absent), Active Character summary, Explore.
- Chat / Work: Conversation, Task State, Activity, Result/Artifact and the
  frozen Composer (800 px max, 24 px radius, IME-safe draft).
- Character Animation: Active Character header, capability-driven character
  selector, Spine preview frame (labeled placeholder until the real Spine
  presentation seam binds), capability-driven animation inventory with real
  Unsupported / Trigger-unavailable states.
- Light and Dark themes from one semantic token contract; Reduced Motion and
  keyboard/focus support.

### Reliability & Failure Behavior
- Agent Error renders on Chat / Work while the authoritative context and draft
  survive and the composer stays usable for follow-up.
- Failed result artifacts render `Failed` plus capability-driven recovery
  actions; a missing Spine resource renders Unavailable + reason + Retry.
- Unsupported / too-large attachments are readable and never show fake retry.
- Dashboard open is a pure presentation transition: zero conversation, zero
  backend task, zero application command.
- Lazy Dashboard host: reopen reuses the same window; dispose removes the owned
  top-level and is idempotent.

## Not Included in V1

- Real backend task execution: submit captures an inert snapshot only; no
  provider is invoked from the Dashboard.
- Real Spine preview inside the Dashboard Character Animation page (placeholder
  surface only).
- Real upload/attachment backend: states are presentation-level.
- No Materials / Projects / Tasks / Files / Tools / Models / Plugins / Agents /
  History navigation; Settings is not a fourth top-level page.

## Validation Snapshot (2026-08-16)

- Stage 10 suites: 13 passed, 0 skipped (user journeys, runtime reliability,
  error handling) in one pytest process.
- Cross-test order: 130 passed in both old→new and new→old order.
- Broad regression: 3407 passed; 1 pre-existing native smoke failure
  (`qt_pet_opengl_backend_smoke` `drag_to_falling`, also failed at Slice 7
  final); 27 environment-gated skips (native manifest/bridge).
- Native Windows gates (6A + 6B + Schwarz combined): 19 passed, 0 skipped,
  exit 0 in one process.
- `qt_pet_smoke` exit 0; `qt_tray_smoke` exit 0.
- Performance baseline: Dashboard cold open ~13 ms, warm reopen ~0.3 ms,
  private memory flat across 100 open/close cycles (see
  `v1_performance_baseline.json`).

See `V1_KNOWN_LIMITATIONS.md` and `V1_VALIDATION_REPORT.md`.
