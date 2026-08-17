# Stage 10 — Independent Review Closure

Date: 2026-08-16. Scope: ArkClaw V1 Release Candidate review before
`ARKCLAW_V1_RELEASE_CANDIDATE_READY`.

## 1. Interaction Review

Reviewed the frozen Slice 0–6B interaction contracts against the V1 surface.

- Desktop: Right Click Schwarz opens the Action Palette at ROOT under the
  frozen `Qt.Tool | FramelessWindowHint` strategy; `Qt.Popup` is not present.
  Same-shell Character/System layers + Back/Escape to ROOT are preserved.
- Native gates re-run in one process: 6A (10) + 6B (7) + Native Schwarz (2) =
  **19 passed, 0 skipped, exit 0**.
- Left Click Interact, Drag threshold, BODY/OVERFLOW, alpha hit-test,
  Conversation Capsule draft/IME and Resume Autonomous are untouched by
  Stage 10 (verified: no Stage 10 change to `PetWindow` gesture/geometry code;
  `pet_production_actions.can_resume_autonomous` remains the ONE authority).
- Dashboard open is a pure presentation transition (zero command) — proven by
  user-journey tests.

## 2. Visual Review

Reviewed the Dashboard implementation against the frozen token contract.

- No raw `#RRGGBB` literals in the Dashboard package; Light/Dark come from one
  semantic token contract (`DesignTokens` + `QtTheme`).
- Shell geometry is token-derived: Top Shell 56, Navigation expanded 208 /
  collapsed 72 / row 44 / radius 12 / leading inset 16 / icon 20 / gap 12 /
  rail 12 / indicator 3×24, page gutter 40 / compact 32, content max 1120.
- This pass removed the remaining page-level raw margin/spacing duplicates in
  `ChatWorkPage` and `CharacterAnimationPage` by wiring
  `page_gutter` / `compact_gutter` / `conversation_block_gap` /
  `character_preview_gap` / `bottom_clearance` from the frozen tokens
  (value-preserving; 75 dashboard+Stage 10 tests still green).
- Remaining small literals (4/6/8/12/16 micro-gaps) are members of the frozen
  spacing scale and conform visually; not refactored to avoid churn.
- Navigation items are exactly `home / chat_work / character_animation`; no
  expanded IA, no Settings top-level page.

## 3. Code Review

- No duplicate presentation truth: Dashboard consumes
  `FrontendPresentationCoordinator` + `ConversationDraftModel` (ONE draft),
  never a second context/draft/IME model.
- No global singletons or UI event buses added in Stage 10.
- Lifecycle: `DashboardIntegration` lazily owns one `DashboardWindow`;
  `dispose()` is idempotent; cross-test order A/B both pass 130/130; the
  perf loop proves window identity is stable and no top-level survives dispose.
- No fake backend state in production: Home renders an explicit empty state;
  submit is an inert snapshot; attachment/agent states are presentation-level.
- Dead/temporary code: the Dashboard Spine preview is an explicit labeled
  placeholder (recorded as a known limitation, not hidden).

## 4. Findings

- P0: none.
- P1: none unresolved. The pre-existing native OpenGL smoke failure
  (`drag_to_falling`) is environment/native flake tracked as a known
  limitation; fixing it would touch frozen PetWindow drag semantics and is
  deliberately deferred.
- Non-blocking: manual visual review of renders A–E on a real display and a
  physical multi-hour soak remain outstanding (automated proxies are green).

## 5. Conclusion

Interaction, visual and code reviews are closed for the V1 release candidate.
All Stage 10 automated gates are green with the evidence in
`docs/release/V1_VALIDATION_REPORT.md`.
