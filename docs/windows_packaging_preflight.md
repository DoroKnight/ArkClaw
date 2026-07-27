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

At the end of the acquisition stage the ZIP had not been extracted, no
contained PE had been executed, and no file had been copied into the Nuitka
cache. The following separately authorized stage supersedes only the static
extraction-review status; it does not authorize execution or a build.

## Dependency Walker static binary audit

On 2026-07-27, the fixed local ZIP was revalidated and exactly `depends.exe`
and `depends.dll` were extracted into the ignored
`build/tool-quarantine/dependency-walker/extracted` directory. Extraction used
unique `.part` files, streaming SHA-256 verification, flush plus fsync, and
atomic rename. Existing or unexpected targets fail closed. `depends.chm` was
neither extracted nor opened.

The reviewed binary identities are:

| File | Bytes | SHA-256 | Version resource |
| --- | ---: | --- | --- |
| `depends.exe` | 566,272 | `57c483dc985a9757501993e969c2a7043c26517f97fd49a42b33d2d6a4193d8b` | Dependency Walker for Win64 (x64), Microsoft Corporation, 2.2.6000 |
| `depends.dll` | 12,288 | `7a5cae7605ae5d8c8aee3e6d8e77e455537b636b395b8f00aebe17bf8b228770` | no version resource fields |

Both files are AMD64 (`0x8664`) PE32+ GUI-subsystem images. The EXE image base
is `0x100000000`, and the DLL image base is `0x8370000`. Neither image contains
a writable-and-executable section. Both set ASLR `DYNAMIC_BASE`; neither sets
DEP/NX, Control Flow Guard, or High Entropy VA. Their PE timestamps decode to
2006-10-30 06:49:56 UTC for the EXE and 2006-10-30 05:27:43 UTC for the DLL.
These timestamps and flags are observations, not provenance guarantees.

Neither file contains a PE Certificate Table. Both are therefore recorded as
`unsigned`; embedded PKCS#7 validation is not applicable. No online
certificate-chain, CRL, OCSP, AIA, reputation, Defender-cloud, or sample-upload
operation was attempted.

The EXE imports the following DLLs:

```text
advapi32.dll comctl32.dll comdlg32.dll gdi32.dll kernel32.dll
mfc42.dll msvcrt.dll shell32.dll user32.dll
```

It does not statically import `depends.dll`. Its imports nevertheless include
debug/process-inspection operations such as `WaitForDebugEvent`,
`ContinueDebugEvent`, `GetThreadContext`, `SetThreadContext`,
`ReadProcessMemory`, `WriteProcessMemory`, `VirtualProtectEx`, and
`VirtualQueryEx`, plus registry read/write operations. The bounded string scan
also finds profiling and hook-injection messages, including an explicit
failure message for a successfully injected hook followed by failure to load
`DEPENDS.DLL`. No network DLL or network API import, service/driver operation,
or persistence API was identified. One legacy MSDN search URL exists as an
embedded string; a string is not evidence that this audit or the tool made a
network request.

The DLL imports only `kernel32.dll`, has no named exports, and exposes five
ordinal-only exports (1 through 5). Its imports include library-loading and
diagnostic primitives but no network, registry, service, persistence, or
remote-process API identified by the audit rules. Static evidence strongly
supports its role as the runtime profiling helper. Static analysis cannot
prove that profiling is its only possible use, so the report deliberately
records that exclusivity as unproven.

Nuitka 4.0 invokes `depends.exe` with `-pa1` and `-ps1`, which enables the
profiling-oriented command path. Nuitka's generic cached-download helper also
extracts every archive file with `flatten=True`, even though the cache
readiness check names only `depends.exe`. Combining that source behavior with
the EXE's profiling strings gives a material risk that manually caching only
the EXE would make this scan path fail to load its helper or lose required
functionality. A future cache-placement authorization should therefore review
placing both the EXE and DLL together. The CHM is help content and is unrelated
to Nuitka's command-line scan path; it must not enter the cache or package.

The official site supplied no fixed SHA-256. The ZIP and entry hashes were
reported by the user as matching some public third-party records. Such a match
establishes sample consistency only; it does not establish publisher
authenticity, benign behavior, or redistribution rights. A public sandbox
risk label for the same hash is likewise a review signal, not a malware
verdict. No third-party site was revisited and no hash or sample was uploaded
during this stage.

The ignored detailed report is:

```text
build/tool-quarantine/dependency-walker/binary_audit.json
```

MSVC 14.44 x64 `dumpbin.exe` was used only with `/HEADERS`, `/DEPENDENTS`,
`/IMPORTS`, and `/EXPORTS`; its raw output is not persisted. No target PE was
executed, no DLL was dynamically loaded, nothing was copied to the Nuitka
cache, and no standalone/onefile compilation or deployment artifact was
started.

Static review permits only a later, separate execution-authorization decision.
The current gate is:

```text
safe_code=dependency_walker_execution_authorization_required
```

## Bounded Dependency Walker cache and host smoke

The next separately authorized gate does not start a Nuitka build. It adds a
fixed-path cache transaction and a one-attempt host smoke for the two reviewed
binaries.

`packaging/stage_dependency_walker_cache.ps1` is inert without
`-ConfirmStaging`. Its Python component accepts no source or destination path.
It reads only the two reviewed files from the ignored quarantine and stages
them into the repository-local cache:

```text
build/nuitka-cache/downloads/depends/x86_64/
```

The transaction verifies size, SHA-256, AMD64 PE32+ format, ordinary-file
status, link count, reparse points, and the exact two-name directory set.
New files are copied into a unique sibling `.part` directory, flushed and
fsynced, renamed within that directory, revalidated, and published by one
directory rename. An exact existing cache is an idempotent success; any
different or additional content is left untouched and rejected.

Every real `packaging/build_standalone.ps1 -ConfirmBuild` invocation now calls
the same cache validator before `pyside6-deploy`. Dry-run mode remains inert
with respect to the cache. Cache validity therefore cannot be inferred merely
from the presence of `depends.exe`.

The committed probe sources produce an AMD64 `probe.exe` that statically
imports `probe_dependency.dll`. If the probe process reaches `main`, it creates
`probe_executed.marker` in its fixed ignored smoke directory. A static
Dependency Walker scan must produce a parseable `.depends` file containing the
DLL without creating that marker.

`packaging/run_dependency_walker_smoke.ps1` is inert without
`-ConfirmExecution`. The confirmed path permits one host attempt and creates a
persistent ignored execution guard before starting the reviewed PE. The
executor:

- fixes the exact Nuitka 4.0 argument sequence and rejects `-pb` or `/pb`;
- sets `PATH` to an empty value and redirects closed stdin, stdout, and stderr;
- creates a Windows Job Object before the process;
- enables kill-on-job-close and an active-process limit of one;
- creates `depends.exe` suspended, assigns it to the Job, and only then resumes
  its main thread;
- enforces a 30-second cooperative host wait followed by Job termination;
- observes Job completion messages for child-process creation or limit events;
- checks that no `depends.exe` remains;
- hashes process output instead of copying its contents into the JSON report;
- parses the result with Nuitka 4.0's current `parseDependsExeOutput`;
- revalidates both cached binaries after execution.

The harness snapshots three fixed, Dependency Walker-related HKCU candidate
paths before and after execution. Values are hashed and never reported. It also
hashes repository files outside the fixed ignored tool directories. These are
bounded observations, not comprehensive host monitoring. The host has no
Windows Sandbox and no process-level hard network isolation. Therefore every
real report must retain:

```text
host_execution=True
windows_sandbox=False
hard_network_isolation=False
```

The absence of network imports does not prove that network access is
impossible. A full standalone build, production executable, Provider,
Credential Manager, external character asset, Defender cloud scan, or remote
reputation service remains outside this gate.

### Actual bounded host-smoke result

The separately authorized host smoke ran exactly once on 2026-07-27. Before
execution, the cache contained exactly the two reviewed ordinary files and
both source-to-cache hashes matched. MSVC 14.44 built the fixed probe locally;
`dumpbin /DEPENDENTS` confirmed that `probe.exe` imports
`probe_dependency.dll`.

The actual command was equivalent to this fixed argument array:

```text
D:\SJTUClaw\build\nuitka-cache\downloads\depends\x86_64\depends.exe
-c
-otD:\SJTUClaw\build\dependency-walker-smoke\probe.depends
-d:D:\SJTUClaw\build\dependency-walker-smoke\probe.dwp
-f1
-pa1
-ps1
D:\SJTUClaw\build\dependency-walker-smoke\probe.exe
```

There was no `-pb` or `/pb`. The Job Object was configured before process
resume with kill-on-job-close and an active-process limit of one. The process
completed without timeout; no child process or child-process-limit event was
observed, and no `depends.exe` remained. `probe_executed.marker` was absent, so
the probe process did not reach `main`. The harness did not observe
`depends.dll` loaded into the Dependency Walker process during its bounded
module sampling.

Dependency Walker returned decimal 512 (`0x00000200`). Its generated log
explains this bit as at least one required implicit or forwarded dependency not
being found; specifically, the old scanner reported `KERNEL32.DLL` as missing
under the same empty-PATH search semantics used by Nuitka 4.0. This is not
collapsed into a generic process failure. Nuitka's current parser successfully
read the output and returned `probe_dependency.dll`, which is the dependency
this compatibility smoke was designed to prove.

Both stdout and stderr were empty. The ignored JSON stores only their SHA-256
and byte count, not raw process output. The generated `.depends` file contains
host system information, but none of that content is copied into the JSON,
documentation, Git, or logs.

All bounded postconditions were satisfied:

```text
dependency_walker_smoke=True
cache_exe_hash_valid=True
cache_dll_hash_valid=True
child_process_count=0
probe_executed=False
output_created=True
output_parsed=True
expected_dependency_found=True
registry_changed=False
unexpected_files=0
process_timeout=False
depends_process_remaining=False
post_execution_hash_valid=True
```

The three fixed HKCU candidate paths remained absent. No unexpected repository
file changed outside the ignored smoke and tool directories. Post-execution
hashes of both reviewed cache binaries remained exact. The ignored execution
guard remains present and prevents another attempt.

This was host execution without Windows Sandbox or process-level hard network
isolation. The harness made no network call, but cannot prove that an arbitrary
target binary could never access the network. No standalone/onefile build,
`pyside6-deploy`, SJTUClaw production executable, Provider, Credential Manager,
Defender cloud scan, or external character resource was used.

The next gate is:

```text
safe_code=standalone_build_authorization_required
```
