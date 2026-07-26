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
- effective Nuitka work/output directory `build/windows-standalone`;
- explicit `--include-module` options for QtCore, QtGui, QtWidgets, and
  QtNetwork;
- Qt platforms, platformthemes, and styles plugins;
- explicit no-follow boundaries for `tests` and `scripts`.

PySide6 6.11.1's deployment helper prepends its own
`packaging/deployment` output option before configured Nuitka extra arguments.
Nuitka 4.0 uses the last value of this single-value option, so the reviewed
extra argument fixes the effective output at `build/windows-standalone`.
Both directories, plus the helper's transient `packaging/deployment` directory,
are ignored by Git.

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

This stage permits only `pyside6-deploy --dry-run`. Until a real build is
separately authorized, the gate is:

```text
safe_code=standalone_build_authorization_required
```
