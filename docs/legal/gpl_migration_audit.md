# ArkClaw GPL-3.0-only Migration Audit

Audit date: 2026-08-08  
Inventory snapshot: `a712a3d`  
Overall gate: **BLOCKED (audit in progress)**

The migration is fail-closed. Until every checklist row is supported by
evidence and marked `PASS` or `NOT APPLICABLE`, the root `LICENSE`, README
source-license statement, and package metadata must remain unchanged.

## Authoritative checklist

This checklist reproduces section 12 of the frozen design specification:

1. **Relicensing authority.** Identify copyright holders for all original
   ArkClaw source and obtain an explicit project-owner attestation that the
   code may be distributed as `GPL-3.0-only`. Git authorship is evidence, not
   proof of ownership or authority.
2. **Code provenance.** Search for school-provided code, employer code,
   third-party snippets, copied examples, generated code, and prior
   contributions. Record source, license, and permission for each finding.
3. **Dependency inventory.** Record direct, transitive, optional, build, and
   packaging dependencies and the license version actually shipped. The audit
   must separately review OpenAI Python, PySide6/Qt, Nuitka, and any bundled
   native libraries; dependencies are not relicensed merely because ArkClaw
   changes license.
4. **Distribution mode.** Record whether each dependency is merely separate,
   dynamically linked, statically linked, bundled, or modified, because those
   facts affect obligations.
5. **Asset inventory.** Record every image, icon, font, animation, audio file,
   model, exported Spine file, and other non-code asset with its separate
   license or authorization. Source-code GPL status must not be presented as
   an asset license.
6. **ArkPets provenance.** Record the repository URL, Harry Huang, GPL-3.0,
   exact source files consulted, rewritten/modified portions, omissions, and
   confirmation that no ArkPets or Arknights art asset was added.
7. **Spine boundary.** Treat Spine Editor projects, exports, and Spine Runtime
   licensing as a separate review. This change neither vendors nor relicenses
   them.
8. **Resolution.** Mark every item `PASS`, `NOT APPLICABLE`, or `BLOCKED`, with
   evidence. Any uncertain ownership, incompatible term, or missing permission
   makes the overall gate `BLOCKED` and stops the license migration.

## Reproducible inventory method

Run from the repository root:

```powershell
python scripts/gpl_migration_inventory.py --repo .
```

The inventory reads only:

- paths returned by `git ls-files`;
- declared requirements in `pyproject.toml`;
- resolved package names and versions in `uv.lock`;
- non-secret Git commit count and author identities.

All file paths are repository-relative and normalized to `/`. The tool does
not read or emit environment-variable values, credentials, file contents, or
absolute local paths. Classifications and output ordering are deterministic.

The asset result therefore describes material tracked for repository
distribution. Ignored or untracked local files are outside that distribution
inventory and are not implicitly authorized for publication.

## Inventory evidence at `a712a3d`

### Repository and code

- Git commits: 58
- Git author identities: `DoroKnight <2312786648@qq.com>`
- Tracked code files: 203
- Tracked native/runtime binaries: 0

Git authorship is recorded only as a search lead. It is not treated as proof
of copyright ownership or relicensing authority.

### Declared dependencies

| Group | Requirements |
| --- | --- |
| Runtime/direct | `openai==2.48.0` |
| GUI optional | `PySide6==6.11.1` |
| Packaging optional | `Nuitka==4.0` |
| Development optional | `mypy>=1.14`, `pytest>=8.3`, `ruff>=0.9` |
| Build system | `setuptools>=75` |

### Locked dependency graph

| Package | Locked version |
| --- | --- |
| annotated-types | 0.8.0 |
| anyio | 4.14.2 |
| ast-serialize | 0.6.0 |
| certifi | 2026.7.22 |
| colorama | 0.4.6 |
| distro | 1.9.0 |
| h11 | 0.16.0 |
| httpcore | 1.0.9 |
| httpx | 0.28.1 |
| idna | 3.18 |
| iniconfig | 2.3.0 |
| jiter | 0.16.0 |
| librt | 0.13.0 |
| mypy | 2.3.0 |
| mypy-extensions | 1.1.0 |
| nuitka | 4.0 |
| openai | 2.48.0 |
| packaging | 26.2 |
| pathspec | 1.1.1 |
| pluggy | 1.6.0 |
| pydantic | 2.13.4 |
| pydantic-core | 2.46.4 |
| pygments | 2.20.0 |
| pyside6 | 6.11.1 |
| pyside6-addons | 6.11.1 |
| pyside6-essentials | 6.11.1 |
| pytest | 9.1.1 |
| ruff | 0.16.0 |
| shiboken6 | 6.11.1 |
| arkclaw | 0.1.0 |
| sniffio | 1.3.1 |
| tqdm | 4.69.0 |
| typing-extensions | 4.16.0 |
| typing-inspection | 0.4.2 |

Package presence and version are inventory facts, not license conclusions.
Official license evidence and the actual distribution/linking mode remain to
be recorded for Task 2.

### Tracked asset inventory

| Category | Tracked paths | Result |
| --- | ---: | --- |
| Images and icons | 0 | None tracked |
| Fonts | 0 | None tracked |
| Animations, Spine projects, SKEL, and Atlas | 0 | None tracked |
| Audio | 0 | None tracked |
| 3D/model files | 0 | None tracked |
| Native binaries (`.dll`, `.exe`, `.pyd`, `.so`, `.dylib`) | 0 | None tracked |

No ArkPets or Arknights art, Java source tree, Spine project, Runtime export,
audio, pet pack, Atlas, PNG, Mesh data, or other character asset is present in
the tracked repository snapshot.

## Current gate status

| Checklist item | Status | Current evidence or blocker |
| --- | --- | --- |
| 1. Relicensing authority | BLOCKED | One Git author identity found; explicit owner attestation and authority scope not yet recorded. |
| 2. Code provenance | BLOCKED | Automated file inventory complete; history/header/content review pending. |
| 3. Dependency inventory and license | BLOCKED | Versions inventoried; official license and shipped-license evidence pending. |
| 4. Distribution mode | BLOCKED | Packaging configuration review pending. |
| 5. Asset inventory and authorization | BLOCKED | No tracked assets found; explicit project-owner confirmation about intended distribution scope pending. |
| 6. ArkPets provenance | BLOCKED | Runtime provenance recorded; license and no-art boundary require final audit confirmation. |
| 7. Spine boundary | BLOCKED | No tracked Spine material found; intended Runtime/project distribution boundary requires confirmation. |
| 8. Resolution | BLOCKED | Items 1–7 are not all PASS or NOT APPLICABLE. |

## License mutation status

No root license, README license statement, package metadata, dependency notice,
or asset-license declaration has been changed by this audit stage.
