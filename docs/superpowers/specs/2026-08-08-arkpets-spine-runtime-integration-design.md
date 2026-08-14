# ArkPets-Compatible Spine Runtime Integration Design

**Date:** 2026-08-08
**Status:** Approved design, pending user review of this written specification
**Scope:** Local, noncommercial Spine 3.8 playback in ArkClaw

## 1. Objective

Integrate the existing Schwarz Spine 3.8 Runtime asset into ArkClaw while
preserving the existing Agent, semantic state machine, and ArkPets-inspired
action-sequencing architecture.

The integration uses animations already exercised by ArkPets before any
ArkClaw-authored replacement. Custom animations remain supplements for
logical actions that the original skeleton cannot provide; they do not replace
a semantically suitable original animation merely to normalize naming.

This design does not reduce the approved catalog of 25 logical actions.

## 2. Confirmed Source and Provenance

ArkPets does not vendor character Spine packages in its source repository. Its
launcher downloads or imports an Ark-Models data set. ArkPets custom-model
documentation requires Spine 3.8 and a per-model `.skel`, `.atlas`, and `.png`
set.

For Schwarz, the following two local directories contain byte-identical
files:

```text
D:\ark-model\Ark-Models\models\340_shwaz_striker#1
D:\Spine\test\stage3_idle_rebuild_20260806_145235\runtime_input
```

The accepted local Runtime asset manifest is:

| File | SHA-256 |
| --- | --- |
| `build_char_340_shwaz_striker#1.atlas` | `6D42F85B5FD09F7BBD7F8DF412437BFA3D48628CC42C0BFE9AE2BA0D7329A737` |
| `build_char_340_shwaz_striker#1.png` | `7D1654527310334AD658054ACFBAF5E58C2A0719A5A1984662713306F656E2A5` |
| `build_char_340_shwaz_striker#1.skel` | `4C7FF39D6322D702E11E7A769457D3E4D77B1A43037F8DEEDF7CD508937DA451` |

The integration reads the isolated `runtime_input` copy. It never writes into
either source directory and never selects a newer file merely because of its
timestamp.

## 3. Relationship to Existing Designs

This specification extends, but does not replace, the following approved
contracts:

- `2026-08-07-arkpets-action-sequence-reuse-design.md` remains authoritative
  for semantic state ownership, arbitration, cancellation, sequence running,
  callback generations, and the 25 logical action names.
- `2026-08-06-spine-animation-production-prompt-design.md` remains
  authoritative for custom animation production and its isolation rules.
- `2026-08-06-spine-desktop-pet-open-source-research.md` remains
  authoritative for Spine 3.8 Runtime mechanisms and license boundaries.

The earlier prohibition on importing ArkPets or Arknights art into ArkClaw is
retained as a repository and distribution boundary. This design authorizes
read-only local loading from an external path; it does not authorize copying
the files into the ArkClaw repository or relicensing them as project source.

## 4. Asset and Animation Priority

The source order is fixed:

1. **ArkPets-compatible original animation.** Use a semantically correct
   animation found in the accepted, hash-pinned original `.skel`.
2. **Audited ArkClaw supplement.** Use a separately exported custom animation
   only when the accepted original skeleton lacks the required semantic action
   or lacks a safe sparse overlay.
3. **Programmatic placeholder.** Retain the current placeholder renderer when
   the Runtime or asset fails validation.

Priority does not mean forced substitution. An unrelated original animation
must not be renamed or accelerated to pretend it implements a missing action.
In particular, `Move` must not be accelerated and accepted as `run_left` or
`run_right` without an independently verified run animation.

## 5. Architecture

```text
ExternalAssetManifest
        |
        v
Spine38RuntimeAdapter ----> AnimationCatalogInspector
        |                           |
        |                           v
        |                  AnimationRegistry
        |                           |
        v                           v
Spine38Renderer <---------- PetTrack0Controller
        |
        v
Qt/OpenGL presentation surface
```

### 5.1 `ExternalAssetManifest`

The manifest contains only explicit absolute paths, expected SHA-256 values,
expected Spine major/minor version, asset identity, and provenance notes. It
does not scan arbitrary folders or silently replace missing files.

Validation must complete before the Runtime parses the atlas or skeleton.

### 5.2 `Spine38RuntimeAdapter`

The adapter is the only component that knows the Spine 3.8 Runtime API. It
loads the binary skeleton, atlas, and texture; exposes animation and skin
metadata; advances `AnimationState`; and converts Runtime callbacks into the
existing narrow player event protocol.

The production implementation wraps the official `spine-cpp` 3.8 branch
through a narrow native bridge. It must not substitute an unofficial Python
Spine decoder, run the ArkPets Java/libGDX application as a sidecar, or create
a second desktop-pet window. The bridge may expose only asset loading,
catalog inspection, animation-state commands, evaluated draw data, and
callback events required by this design.

The adapter must not import or reference Agent, provider, prompt, session,
credential, reminder-content, or network-client modules.

### 5.3 `AnimationCatalogInspector`

The inspector enumerates the loaded skeleton instead of guessing names. For
each animation it records:

- exact case-sensitive physical name;
- duration;
- whether the proposed use is looped or one-shot;
- timelines and keyed property categories when exposed by the Runtime;
- candidate semantic action;
- evidence status: confirmed, rejected, or unreviewed.

Catalog inspection is read-only. It cannot create bindings automatically on
name similarity alone.

### 5.4 `AnimationRegistry`

Business logic continues to use the exact 25 `PetActionName` identifiers. Each
physical binding adds immutable metadata:

```text
logical_name
physical_name
source_tier
track
loop_intent
direction_policy
mix_in_seconds
mix_out_seconds
evidence_status
```

An original ArkPets-compatible binding wins over a supplemental binding when
both are semantically valid. Missing actions remain explicitly unbound until a
supplement is available; they do not fall through to an unrelated physical
animation.

Aliases require an explicit reviewed alias group. Directional reuse is allowed
only when the same animation plus renderer reflection is visually correct for
all asymmetric attachments.

### 5.5 `Spine38Renderer`

The renderer consumes skeleton draw order, region and mesh geometry, UVs,
colors, blend modes, clipping, and textures. It owns no semantic state,
physics, window movement, behavior selection, or action sequencing.

The existing generic Qt/OpenGL mesh backend may be used as the final draw
surface after its own work is accepted. Spine-specific parsing and animation
state remain outside that generic backend.

## 6. Track Policy

- **Track 0:** ArkPets-compatible original full-body states and transitions.
- **Track 1:** `breathing`, only after sparse-timeline and conflict validation.
- **Track 2:** `blink`, only after sparse-timeline and conflict validation.

An original full-body animation has priority on Track 0. It does not gain
priority over a safe higher-track overlay merely because both came from the
same skeleton.

The custom `breathing` currently present in `01_breathing.spine` is not part of
the accepted original `.skel`. It cannot be reported as integrated until a new,
separate Runtime export is produced and validated. The original Runtime files
must never be overwritten by that export.

## 7. Runtime Data Flow

1. Application configuration selects `SPINE38` and an explicit external
   manifest.
2. Startup hashes all three files and rejects any mismatch.
3. The adapter verifies that the binary skeleton is compatible with Spine
   3.8 before constructing playback state.
4. The inspector enumerates exact skins and animations.
5. The registry preflights requested logical bindings against that catalog.
6. The existing semantic transition protocol commits state only according to
   its approved preflight and mandatory-safety rules.
7. `PetTrack0Controller` sends physical animation commands through the narrow
   player interface.
8. Runtime callbacks carry the existing generation, token, logical name, and
   physical name identity checks before advancing a sequence.
9. The renderer draws the current evaluated skeleton without modifying
   semantic state.

## 8. Direction and Asymmetry

ArkPets-compatible reflection may serve both left and right movement only
after verification of:

- weapon and holster orientation;
- hand attachments;
- asymmetric clothing and accessories;
- text, symbols, and UI-like art;
- draw order and clipping;
- foot placement and Root motion.

If reflection is rejected, the registry requires distinct physical animations
or a separately audited supplemental action.

## 9. Failure Containment

All failures are fail-closed:

- missing or changed asset: reject `SPINE38`, retain placeholder;
- unsupported skeleton version: reject before playback;
- missing atlas page or attachment: reject the asset, do not partially draw;
- missing logical binding: reject only the affected action during preflight;
- callback identity mismatch: ignore as stale and retain state consistency;
- render-context loss: stop Runtime drawing and fall back without changing
  Agent or semantic state;
- mandatory safety replacement failure: preserve the previously approved
  containment path (`desired_action = None`, generation invalidation, Track 0
  clear attempt, runner reset, and `DEGRADED` or `UNKNOWN` health).

No Runtime exception may propagate into the Agent loop.

## 10. First Vertical Slice

The first implementation milestone is deliberately narrow:

1. validate the pinned Schwarz triplet;
2. load it through a Spine 3.8 adapter;
3. enumerate and record every exact animation name and duration;
4. bind one confirmed ArkPets-compatible idle action;
5. display the correct skin and loop the action for at least three cycles;
6. close and reopen the application without asset mutation;
7. demonstrate that a forced asset validation failure returns to the
   placeholder while the local Agent remains operational.

This milestone does not claim completion of all 25 bindings, Track 1/2
composition, custom Runtime export, or packaging.

## 11. Verification

### 11.1 Unit tests

- manifest path and SHA-256 validation;
- skeleton-version rejection;
- exact-case catalog and registry matching;
- original-source priority over supplemental-source priority;
- explicit missing binding instead of unrelated fallback;
- alias-group and direction-policy validation;
- Runtime callback identity and stale-generation rejection;
- Runtime failure cannot mutate Agent or semantic state.

### 11.2 Integration tests

- load the accepted `.skel`, `.atlas`, and `.png` together;
- verify the expected skin and attachment resolution;
- exercise all supported blend modes and clipping found in the asset;
- render the selected idle action at 0%, 50%, and 100%;
- play at least three loops without boundary jump, foot drift, attachment
  flashing, missing regions, or obvious clipping;
- destroy and recreate the OpenGL context;
- verify placeholder fallback after deliberate hash mismatch;
- verify the Agent remains responsive while Runtime playback starts, stops,
  fails, and recovers.

### 11.3 Evidence artifact

The integration produces a local audit containing the source hashes, Runtime
version, enumerated animations, accepted and rejected mappings, skin, atlas
pages, playback results, and unresolved actions. It contains paths and hashes,
not copies of the character assets.

## 12. Repository and License Boundaries

- Do not copy `.skel`, `.atlas`, `.png`, `.spine`, screenshots, or Runtime
  exports into `D:\ArkClaw`.
- Do not commit Ark-Models assets to the ArkClaw GitHub repository.
- Do not describe the character assets as GPL-covered ArkClaw source.
- Preserve ArkPets attribution for adapted GPL-3.0 code.
- Preserve the separate Spine Runtimes license and required notices.
- Treat Ark-Models and Arknights art under their own repository notice and
  copyright boundary; this design is for local noncommercial use and is not
  legal advice.

Primary references:

- <https://github.com/isHarryh/Ark-Pets/tree/v3.x>
- <https://github.com/isHarryh/Ark-Pets/blob/v3.x/docs/CustomModel.md>
- <https://github.com/isHarryh/Ark-Pets/blob/v3.x/build.gradle>
- <https://github.com/isHarryh/Ark-Models>
- <https://github.com/EsotericSoftware/spine-runtimes/tree/3.8>

## 13. Acceptance Criteria

The design is satisfied when:

1. the hash-pinned ArkPets-compatible original asset is the first animation
   source considered;
2. exact original animations are used wherever semantic and visual audit
   passes;
3. the 25 logical action catalog and state-machine authority remain intact;
4. missing original actions remain explicit until custom supplements pass
   audit;
5. assets remain external and unmodified;
6. Agent execution remains independent of Runtime success;
7. the first vertical slice visibly renders and loops an original idle action
   and demonstrates safe placeholder fallback;
8. no claim is made that the remaining 24 logical bindings, custom export,
   multi-Track composition, program callbacks, or packaging are complete.
