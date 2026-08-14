# ArkClaw GPL Migration Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce an evidence-backed GPL-3.0-only migration decision and change licensing files only when every ownership, dependency, distribution, asset, ArkPets, and Spine boundary item is resolved as PASS or NOT APPLICABLE.

**Architecture:** Treat the audit as a fail-closed gate. Local inventory scripts generate reproducible evidence; the human project-owner attestation and third-party license findings determine the final result. A BLOCKED result leaves `LICENSE`, README source-license language, and package metadata unchanged.

**Tech Stack:** Git history, Python package metadata, `uv.lock`, PowerShell/Python inventory scripts, Markdown evidence, pytest policy checks.

## Global Constraints

- Use section 12 of `docs/superpowers/specs/2026-08-07-arkpets-action-sequence-reuse-design.md` verbatim as the audit checklist.
- Legal conclusions require current primary-source evidence; use official license texts and upstream package metadata.
- Do not infer copyright ownership solely from Git authorship.
- Code licensing and asset authorization are separate decisions.
- Do not add or copy ArkPets/Arknights art, Java source trees, Spine projects, exports, audio, pet packs, or proprietary Runtime data.
- Any uncertainty yields overall `BLOCKED`; never partially migrate the root project license.

---

### Task 1: Reproducible Repository and Dependency Inventory

**Files:**
- Create: `scripts/gpl_migration_inventory.py`
- Create: `tests/unit/test_gpl_migration_inventory.py`
- Create: `docs/legal/gpl_migration_audit.md`

- [ ] Write failing tests that run the inventory against a temporary repository and assert deterministic code, dependency, and asset classifications.
- [ ] Verify the tests fail because the script is absent.
- [ ] Implement inventory using `pathlib`, `tomllib`, and subprocess calls to read Git metadata; emit relative paths only and never credential/environment values.
- [ ] Record direct, optional, build, locked, packaging, and native/runtime dependencies, including OpenAI Python, PySide6/Qt, Nuitka, and shipped binaries.
- [ ] Record every repository image, icon, font, animation, audio, model, Spine, Atlas, PNG, and other non-code asset separately.
- [ ] Run `python -m pytest -q tests/unit/test_gpl_migration_inventory.py` and commit the script, test, and initial evidence.

### Task 2: Ownership, Provenance, Distribution, and License Findings

**Files:**
- Modify: `docs/legal/gpl_migration_audit.md`

- [ ] Record project-owner attestation as an explicit dated statement; if authority cannot be established, mark the audit `BLOCKED`.
- [ ] Review Git history and source headers for school, employer, third-party, generated, copied-example, and prior-contributor code; record source, license, permission, and evidence for every finding.
- [ ] Record whether every dependency is separate, dynamically linked, statically linked, bundled, or modified.
- [ ] Record the current official license evidence for each distributed dependency and whether its obligations are compatible with the intended distribution.
- [ ] Record ArkPets repository URL, Harry Huang, GPL-3.0, the four consulted Java files, rewritten portions, omissions, and confirmation that no ArkPets/Arknights art was added.
- [ ] Record Spine Editor/project/export/Runtime licensing as a separate boundary with no implied relicensing.
- [ ] Mark each checklist row `PASS`, `NOT APPLICABLE`, or `BLOCKED` and set one overall result.

### Task 3: Conditional GPL-3.0-only Migration

**Files:**
- Create only on overall PASS: `LICENSE`, `THIRD_PARTY_NOTICES.md`, `ASSETS_LICENSE.md`
- Modify only on overall PASS: `README.md`, `pyproject.toml`
- Create: `tests/unit/test_source_license_policy.py`

- [ ] Write a failing policy test that reads the audit result and enforces fail-closed behavior: BLOCKED requires proprietary metadata to remain unchanged; PASS requires complete GPLv3 text, `GPL-3.0-only` package metadata, notices, and a separate asset statement.
- [ ] Verify RED against the current repository.
- [ ] If the audit is BLOCKED, implement the policy check for the unchanged state and stop without modifying licensing files.
- [ ] If the audit is PASS, add the complete GPL version 3 text, update package metadata, add ArkPets/dependency notices, and add the exact README distinction `Source Code: GPL-3.0-only` / `Assets: not covered by the source-code license`.
- [ ] Run `python -m pytest -q tests/unit/test_source_license_policy.py`, `python -m ruff check scripts tests`, `python -m mypy scripts tests`, and the full test suite.
- [ ] Inspect `git diff --check` and commit only the evidence-backed outcome.
