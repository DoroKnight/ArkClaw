# ArkPets-inspired Action Runtime

## Status

ArkClaw now contains a pure-Python, capability-gated action sequencing layer
for the pet's Track 0 body animations. The layer is present and tested, but the
current desktop renderer remains a placeholder. Production Spine playback is
therefore deliberately disabled and the existing local pet behavior continues
through the legacy direct path.

This document records implementation provenance, the actual runtime boundary,
the frozen safety invariants, and the evidence used for handoff. It does not
declare the repository-wide GPL migration complete; that decision remains
subject to the separate ownership, dependency, asset, distribution, ArkPets,
and Spine audit.

## Provenance and reuse boundary

The sequencing design was informed by
[Ark-Pets](https://github.com/isHarryh/Ark-Pets), authored by Harry Huang and
published under GPL-3.0. The implementation consulted only these Java source
paths:

```text
core/src/cn/harryh/arkpets/animations/AnimData.java
core/src/cn/harryh/arkpets/animations/AnimComposer.java
core/src/cn/harryh/arkpets/animations/AnimClipGroup.java
core/src/cn/harryh/arkpets/animations/AnimClip.java
```

ArkClaw's implementation is an independent Python rewrite. It does not vendor
or copy ArkPets Java source or comments. It also deliberately omits:

- ArkPets or Arknights character images, animation frames, Spine projects,
  audio, pet packs, and other art assets;
- the ArkPets stochastic behavior matrix or broad behavior catalog;
- ArkPets mobility logic, window movement, gravity, collision, and root-motion
  ownership.

The action runtime never imports the Agent loop, provider layer, credentials,
or network clients. Those subsystems remain independent.

## Architecture and ownership

The runtime keeps description, progression, arbitration, playback, and
semantic state authority separate:

| Component | Responsibility |
| --- | --- |
| `PetActionSequence` and catalog | Immutable ordered action descriptions and policy metadata |
| `AnimationRegistry` | Logical, case-sensitive action name to physical animation binding |
| `PetActionArbiter` | Accept, reject, or replace Track 0 requests using fixed interruption rules |
| `PetSequenceRunner` | Current step, completion matching, loop-boundary exit, and reset |
| `PetTrack0Controller` | Player commands, generation/token identity, containment, health, and watchdog |
| `PetAnimationEngine` | Atomic semantic proposal, preflight, arbitration, commit, and playback transaction |
| `PetStateMachine` | Sole authority for semantic state and monotonic semantic epochs |

Semantic state transitions own animation cancellation and replacement. A
renderer callback can advance a sequence only when its action, generation, and
playback token all match the confirmed playback epoch.

## Current capability boundary

Production sequencing requires all four player capabilities:

1. one-shot completion callbacks;
2. loop-boundary callbacks;
3. authoritative duration metadata;
4. liveness reporting.

The current `PlaceholderAnimationPlayer` advertises all four as unavailable.
Consequently:

- `sequencing_enabled` is false;
- pet action requests return `ActionOutcome.LEGACY_DIRECT`;
- no production Track 0 `play()` command is issued;
- the existing programmatic renderer and motion behavior remain active;
- Agent lifecycle, provider behavior, credentials, and network behavior are
  not changed.

This fail-closed gate prevents a partially capable renderer from pretending to
support completion-driven sequencing.

## Frozen runtime invariants and tests

| Invariant | Protecting tests |
| --- | --- |
| Exactly 25 unique, case-sensitive logical action names; immutable ordered sequences; explicit Track ownership | `test_logical_catalog_is_exact_unique_and_case_sensitive`, `test_sequence_is_immutable_and_step_has_no_successor_pointer`, `test_catalog_union_covers_all_25_names_and_track_ownership` |
| Registry bindings are exact and reject missing, duplicate, case-mismatched, or wrong-track entries | `test_default_registry_is_an_exact_identity_mapping`, `test_registry_rejects_missing_binding`, `test_registry_rejects_duplicate_physical_binding`, `test_registry_rejects_case_mismatch_from_loaded_skeleton`, `test_registry_rejects_overlay_action_on_track_zero` |
| Semantic state owns the proposed target epoch and rejected proposals do not commit | `test_state_machine_owns_target_epoch_and_rejected_proposal_does_not_commit`, `test_action_request_copies_state_proposal_target_epoch`, `test_normal_preflight_rejection_commits_neither_state_nor_epoch` |
| State/action compatibility is exhaustive; uncertain renderer health permits no desired action | `test_track0_compatibility_is_exhaustive`, `test_unconfirmed_health_permits_only_no_desired_action` |
| Drag release is user interaction; approved same-session hold-to-release and new-session takeover replace correctly | `test_drag_release_replaces_hold_in_same_input_session`, `test_new_drag_session_replaces_previous_release`, `test_production_drag_lifecycle_uses_one_session_then_new_press_replaces` |
| A loop boundary without pending graceful exit sends no player command and preserves generation/token | `test_loop_boundary_without_pending_exit_is_observational`, `test_loop_boundary_without_exit_is_observational_through_engine` |
| Mandatory safety transition commits even when replacement preflight fails, then clears/contains and leaves no desired action | `test_mandatory_fall_commits_then_contains_failed_preflight`, `test_mandatory_fall_commits_when_degraded_health_blocks_replacement` |
| Each play/clear attempt consumes a generation; stale callbacks are side-effect free | `test_every_play_and_clear_attempt_consumes_generation`, `test_stale_callback_after_replacement_is_side_effect_free`, `test_callback_identity_mismatch_is_stale_and_side_effect_free` |
| Missing capability disables sequencing without player mutation or guessed watchdog timing | `test_each_missing_capability_disables_production_sequencing`, `test_missing_capability_rejects_preflight_without_mutation`, `test_missing_duration_never_arms_or_guesses_a_deadline` |
| Placeholder desktop integration cannot start production sequencing and remains isolated from Agent/provider code | `test_placeholder_never_starts_production_sequence`, `test_sequencing_modules_do_not_import_agent_or_provider_layers`, `test_animation_failure_does_not_close_restart_or_wake_agent` |

## Explicitly not implemented or validated

The following work is intentionally still outstanding:

- a real Spine Runtime `AnimationPlayer` adapter;
- Runtime loading and authoritative animation-duration discovery;
- real completion, loop-boundary, and liveness callbacks;
- actual Track 0 playback against the produced Spine skeleton;
- Track 1 `breathing` and Track 2 `blink` composition;
- Runtime mix values, event callbacks, and program playback acceptance;
- Spine Runtime export or any JSON, SKEL, Atlas, PNG, video, or package export;
- changes to Mesh topology, weights, Setup Pose, skins, constraints, Atlas,
  PNG, audio, or original character material.

The repository-wide transition to `GPL-3.0-only`, dependency notices, and the
separate source-code versus asset-license declarations must be completed only
after the dedicated GPL migration audit reaches PASS or NOT APPLICABLE for
every checklist item.
