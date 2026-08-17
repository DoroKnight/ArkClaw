# ArkClaw V1 — Architecture Status

Status: Release Candidate 1 (Alpha). This document records which architecture
is implemented and owned, which is intentionally deferred, and how ownership is
distributed for the V1 surface.

## Implemented

### Presentation (Qt)
- `FrontendPresentationCoordinator` owns no presentation truth; it routes
  intents to the Qt-free `FrontendPresentationModel` and applies ordered
  effects. It is the single production coordinator for both Desktop and
  Dashboard presentation.
- `FrontendPresentationModel` (Qt-free) owns foreground overlay, palette layer,
  ConversationContext and semantic focus state. Opening the Dashboard is a pure
  presentation transition (zero command).
- `ConversationDraftModel` remains the ONE authoritative draft owner
  (text, caret, selection, IME composition, revision, submitted snapshot).
  Both the Capsule and the Dashboard Composer attach through the same
  draft-host convention.
- `DashboardIntegration` lazily owns one `DashboardWindow`, wires page signals
  once, feeds snapshots from the presentation model and is disposed idempotently.
- `DashboardPresentationModel` holds presentation snapshots only; it never
  fabricates recent work, character data, tasks or artifacts.
- Theme: `QtTheme` + `DesignTokens` provide one semantic contract for
  Light/Dark (surface/text/border/focus/accent/state + spacing/radius/
  typography/motion). No per-component Light/Dark branching.

### Desktop Companion (frozen earlier slices)
- `PetWindow` (right-click recognition, BODY/OVERFLOW, alpha native hit-test,
  drag threshold) unchanged by Stage 10.
- Action Palette host under the frozen `Qt.Tool | FramelessWindowHint` strategy;
  `Qt.Popup` is retired.
- ActionPaletteEffectSink + production composition root wire Right Click
  Schwarz → Palette → ROOT.
- Resume Autonomous has ONE authoritative validity implementation
  (`can_resume_autonomous` in `pet_production_actions`).

### Infrastructure
- Spine 3.8 native bridge, role manifests, single instance, tray, Windows
  autostart, provider settings, safe shutdown.

## Deferred (by design, not V1)

- Real backend task execution / provider dispatch from the Dashboard.
- Real Dashboard Spine preview (placeholder frame).
- Real attachment upload transport.
- Expanded IA (Materials/Projects/Tools/Models/Plugins/History, Settings page).
- IDE-like panes/terminal/debug surfaces.

## Ownership Summary (Stage 10)

| Concern | Owner |
| --- | --- |
| Presentation truth / overlay / palette layer | `FrontendPresentationModel` |
| Intent routing / effect application | `FrontendPresentationCoordinator` |
| Draft truth | `ConversationDraftModel` (ONE) |
| Dashboard window lifecycle | `DashboardIntegration` (lazy, idempotent dispose) |
| Page snapshots | `DashboardPresentationModel` |
| Resume Autonomous validity | `pet_production_actions.can_resume_autonomous` (ONE) |
| Theme tokens | `DesignTokens` / `QtTheme` |

## Contract Status

- Slice 0–6B interaction contracts: preserved (native gates 19/19).
- Slice 7 visual implementation: preserved (dashboard suites green).
- Stage 10: journeys, reliability, error handling and performance baseline are
  implemented and gated.
- No Stage 10 change alters Left Click / Drag / hit-test / BODY / OVERFLOW /
  animation / Palette strategy / tray semantics.
