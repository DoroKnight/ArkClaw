# Windows packaging security preflight

This document records source-boundary checks that must hold before a Windows
standalone packaging tool is authorized or installed. It does not claim that a
standalone artifact has already been produced or audited.

## Credential Target boundary

Production code under `src/sjtuclaw` contains only production credential
mapping behavior:

- the legacy OpenAI Target remains stable;
- the built-in DeepSeek credential retains its stable generic Target;
- validated user CredentialIds map to `SJTUClaw/Credentials/<uuid>`;
- both manual-verification CredentialIds fail closed before backend access.

The two fixed manual-verification Targets live only in
`scripts/manual_credential_targets.py`. The OpenAI and DeepSeek manual scripts,
plus the explicitly skipped Windows integration test, inject that resolver
deliberately. The resolver accepts no user-supplied Target and import has no
Credential Manager, client, environment, or network side effect.

`builtin_credential_bindings()` contains only production OpenAI and DeepSeek
bindings. A default `ProviderFactory` therefore rejects a manual-verification
profile before SecretStore access or SDK client creation.

## Packaging exclusion and final audit

`scripts/` and `tests/` are development and verification inputs. They must not
be included as importable modules or data in a production standalone binary.
Consequently, an approved production package must not contain either manual
verification Target.

A clean source scan is necessary but not sufficient. After a real standalone
artifact is generated, reviewers must separately:

1. inspect the packaging manifest/module report to confirm `scripts/` and
   `tests/` were excluded;
2. scan the executable and all bundled files for the manual Target prefix;
3. verify no credentials, logs, caches, local settings, or test artifacts were
   bundled;
4. run the packaged application with network and Credential Manager access
   guarded, then perform separately authorized integration checks.

Before the packaging dependency was authorized, the recorded gate was:

```text
safe_code=packaging_dependency_authorization_required
```

That dependency-only gate was satisfied by the reviewed Nuitka 4.0 pin and
installation described below. It did not authorize a standalone build.

## Pinned deployment tooling

The packaging extra pins `Nuitka==4.0`; Nuitka is not a runtime dependency.
The lock source is the official `https://pypi.org/simple` registry and the
locked source archive is served by `files.pythonhosted.org`. No PyInstaller or
additional package index is configured.

The installed Nuitka distribution identifies its compiler package as
AGPL-3.0-or-later. Its installed `LICENSE-RUNTIME.txt` grants an additional
permission for Target Code produced through Nuitka's Compilation Process and
states that the exception does not weaken the copyleft terms for Nuitka itself
or a modified compiler. This repository does not treat that summary as legal
advice and does not yet claim that a public distribution satisfies every
Nuitka, Python, PySide6, Qt, OpenSSL, OpenAI SDK, or transitive dependency
license obligation.

## Auditable PySide deployment configuration

`packaging/pet_entry.py` is the production deployment entry. It imports and
calls only `sjtuclaw.presentation.qt.pet_application.run`. The deployment spec
fixes:

- application title `SJTUClaw`;
- standalone mode and Nuitka 4.0;
- Windows console mode `disable`;
- final executable directory `dist`;
- MSVC selection `14.4` and disabled `ccache`;
- executable name `SJTUClaw.exe`;
- a diffable compilation report at
  `build/windows-standalone/compilation-report.xml`;
- explicit `--include-module` options for QtCore, QtGui, QtWidgets, and
  QtNetwork;
- Qt platforms, platformthemes, and styles plugins;
- explicit no-follow boundaries for `tests` and `scripts`.

PySide6 6.11.1's deployment helper supplies exactly one Nuitka output option:
`--output-dir=<entry directory>/deployment`. The repository spec deliberately
contains no second `--output-dir`. For this entry point, Nuitka's temporary
standalone result is therefore `packaging/deployment/pet_entry.dist`.
PySide6's `finalize()` copies that directory to the configured title and
execution directory, producing `dist/SJTUClaw.dist`. This avoids relying on
duplicate-option ordering. `build/`, `dist/`, and the transient
`packaging/deployment/` directory are ignored by Git.

The Windows platform plugin set retains `qwindows`. Native widget appearance
uses the styles and platformthemes groups. The current QtNetwork use is local
IPC/single-instance coordination and does not require the Qt TLS plugin; cloud
Provider HTTPS uses the Python HTTP stack. A future standalone build must still
audit the DLL and plugin report before concluding that TLS runtime dependencies
are complete.

The spec does not include tests, docs, smoke tools, manual verification scripts,
environment files, logs, caches, local settings, or external character assets.
Source configuration tests cannot prove the final binary exclusion: the real
standalone module report and filesystem still require a separate authorized
review.

## Controlled build entry and MSVC gate

`packaging/build_standalone.ps1` derives the repository root from
`$PSScriptRoot` and sets `NUITKA_CACHE_DIR` to the repository-local
`build/nuitka-cache`. It does not use the per-user AppData cache. With no
arguments, it activates and validates the toolchain and invokes
`pyside6-deploy` only with `--dry-run`. A real build additionally requires the
explicit `-ConfirmBuild` switch.

The script accepts an optional Visual Studio installation path or discovers
one with the installed `vswhere.exe`; no workstation-specific Visual Studio
path is committed. Before deployment it requires all of the following:

- MSVC tools version `14.44.35207`;
- `cl.exe`, `link.exe`, and `dumpbin.exe` from the same
  `Hostx64/x64` directory;
- no MSYS `link.exe`;
- compiler version 19.44;
- a 64-bit AMD64 Python built with `MSC v.1944`;
- normalized host and target architecture `amd64`;
- a successful `python -m nuitka --version` result equal to 4.0.

The deployment subprocess receives closed standard input. This is a
fail-closed backstop against interactive download prompts; it is not a
substitute for the explicit cache precheck.

## Dependency Walker boundary

Inspection of the installed Nuitka 4.0 source confirms that Windows standalone
and onefile dependency analysis calls its Dependency Walker integration. For
x64 the hard-coded URL is:

```text
https://dependencywalker.com/depends22_x64.zip
```

With the repository-local cache, Nuitka expects the extracted executable at:

```text
build/nuitka-cache/downloads/depends/x86_64/depends.exe
```

Nuitka's current downloader does not carry a fixed expected SHA-256 for this
ZIP. It can prompt before downloading, and its generic downloader may retry an
HTTPS download over HTTP after a transport failure. The project therefore does
not delegate acquisition to Nuitka. `--assume-yes-for-downloads` is forbidden,
`ccache` is disabled, and MSVC is selected explicitly so a missing compiler
cannot silently select a downloadable MinGW toolchain. `dumpbin.exe` is used
by parts of PySide deployment inspection, but it cannot replace Nuitka's
explicit Dependency Walker path.

When `-ConfirmBuild` is present, the build script checks the exact cached
`depends.exe` path before starting `pyside6-deploy`. If it is absent, the
script exits nonzero with:

```text
safe_code=dependency_walker_not_cached
```

This stage does not download or execute Dependency Walker and does not perform
a real Nuitka compilation.

### Separately authorized acquisition plan

A later stage requires explicit authorization for `dependencywalker.com` and
may download only `depends22_x64.zip`. That stage must:

1. record the ZIP SHA-256, byte size, and final resolved URL;
2. reject ZIP path traversal, absolute paths, links, duplicate names,
   unexpected files, and abnormal sizes before extraction;
3. extract only the required `depends.exe`;
4. record the extracted executable's SHA-256;
5. inspect and record its Authenticode signature status;
6. locate, review, and preserve applicable license information;
7. obtain user confirmation before executing the binary;
8. disable network access again before the first standalone compilation;
9. keep standard input closed so later missing tools fail rather than prompt
   for another download.

Because Nuitka 4.0 supplies no pinned expected hash, the recorded hash is an
audit observation, not proof that the upstream binary is trustworthy.

## Diagnostic icon limitation

An empty `icon` field causes `pyside6-deploy` to use the default icon supplied
with PySide6. It is permitted only for a local diagnostic package. It is not an
SJTUClaw brand asset and must not be presented as the final product icon.
Before distribution it must be replaced by an original, explicitly authorized
ICO. This stage does not add or generate character artwork.

## Quarantined Dependency Walker review

The separately authorized acquisition was performed on 2026-07-27 with
`packaging/acquire_dependency_walker.ps1 -ConfirmDownload`. The entry point is
inert without that switch. Its fixed URL validation rejects HTTP, credentials,
ports, query strings, fragments, path changes, and host changes. The Python
audit helper uses system TLS validation, disables redirect handling, reads the
body in bounded chunks, enforces a 2 MiB limit independently of
`Content-Length`, flushes and fsyncs a unique `.part`, and performs a
no-extraction ZIP and PE-header audit before the completed ZIP is atomically
renamed inside the ignored quarantine.

The actual download result was:

- request and final URL:
  `https://dependencywalker.com/depends22_x64.zip`;
- HTTP 200 with no redirect and successful system TLS validation;
- content type `application/x-zip-compressed`;
- declared and actual size 468,618 bytes;
- start `2026-07-27T02:12:27.723Z`;
- completion `2026-07-27T02:12:29.192Z`;
- ZIP SHA-256
  `35db68a613874a2e8c1422eb0ea7861f825fc71717d46dabf1f249ce9634b4f1`;
- ZIP SHA-512
  `7d73eaec69c2e39cf447a7c40c7f32db9b02fac3330b1d60296d8b595cd4563cb55fe848ce9ddb35f234da5afa6bba65f5dfcee520e35ea5d01634b4f7c684ce`.

The archive contained exactly three non-directory entries:

| Entry | Compressed | Uncompressed | SHA-256 |
| --- | ---: | ---: | --- |
| `depends.chm` | 150,509 | 164,468 | `e5a4e001fbfe731b5d8b9d2046c57fa1786599364366704a800d59239d0c064d` |
| `depends.dll` | 5,781 | 12,288 | `7a5cae7605ae5d8c8aee3e6d8e77e455537b636b395b8f00aebe17bf8b228770` |
| `depends.exe` | 312,012 | 566,272 | `57c483dc985a9757501993e969c2a7043c26517f97fd49a42b33d2d6a4193d8b` |

Total compressed entry data was 468,302 bytes and total uncompressed data was
743,028 bytes. The static checks found no encryption, duplicate or
case-colliding names, absolute/UNC/drive/ADS/traversal paths, control
characters, symlinks, special files, size-limit violations, or abnormal
compression ratio. There was exactly one `depends.exe`; its bounded header
prefix contained an MZ header, a PE signature, and machine value `0x8664`
(AMD64). Entry content was streamed for hashing and no archive entry was
extracted.

The archive is structurally safe under these checks, but `depends.chm` and
`depends.dll` are additional entries and therefore require explicit human
review. The result remains `manual_review_required=true`; structural checks
do not establish provenance or redistribution rights.

The official homepage and FAQ were read over their exact authorized HTTPS URLs
with redirects disabled. Both returned HTTP 200 without redirect. The homepage
identifies Dependency Walker version 2.2 as a free utility. It also states
distribution restrictions: recipients may not profit from distributing it and
may not bundle it with another product. SJTUClaw therefore treats the tool only
as a local build-time dependency and does not claim redistribution permission.
The final SJTUClaw package must not contain the ZIP, `depends.exe`,
`depends.dll`, or `depends.chm`.

The ignored local evidence is retained at:

- `build/tool-quarantine/dependency-walker/depends22_x64.zip`;
- `build/tool-quarantine/dependency-walker/download_audit.json`;
- `build/tool-quarantine/dependency-walker/archive_audit.json`.

The ZIP was not extracted, no contained PE was executed, and no file was copied
into the Nuitka cache. No standalone or onefile compilation was started.
Moving the reviewed executable into the Nuitka cache, executing it, or starting
a standalone build requires a new explicit authorization and review.

Until that review is granted, the gate is:

```text
safe_code=dependency_walker_review_required
```
