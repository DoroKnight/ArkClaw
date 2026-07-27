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
- Qt platforms and styles plugins;
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
uses the platform and styles groups. PySide6 6.11.1 in the reviewed
environment has no `platformthemes` plugin directory, so that nonexistent
family is not requested. The current QtNetwork use is local
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

## Controlled standalone build and static-audit boundary

The standalone build entry remains dry-run by default. A real build requires
`packaging/build_standalone.ps1 -ConfirmBuild`, and the script rejects an
existing `dist/`, `packaging/deployment/`, or `build/windows-standalone/`
directory instead of deleting or merging it. It also requires at least 12 GiB
of free space, the fixed Dependency Walker cache, Python 3.13.6, Nuitka 4.0,
PySide6 6.11.1, and the exact MSVC 14.44 Hostx64/x64 tools.

The confirmed path copies the tracked `pysidedeploy.spec` into the ignored
build directory. PySide6 may normalize that private copy, but the tracked
source spec is hashed before and after the build and must remain byte-for-byte
unchanged. The fixed deployment command includes standalone mode,
`--keep-deployment-files`, Nuitka 4.0, and no force, onefile, MinGW, ccache, or
automatic-download option.

`packaging/standalone_build.py` starts `pyside6-deploy.exe` suspended, assigns
it to a Windows Job Object, and resumes it only after enabling
kill-on-job-close and an active-process limit of 128. Standard input is the
null device. Standard output and error go only to ignored logs; the public
result reports their SHA-256 and byte counts. A 90-minute build deadline
terminates the Job process tree. The controller records Job accounting and
rejects a newly remaining `python`, `nuitka`, `cl`, `link`, `depends`, or
`pyside6-deploy` process. It creates its attempt marker before process start
and never retries automatically.

The build environment sets `PIP_NO_INDEX=1`,
`PIP_DISABLE_PIP_VERSION_CHECK=1`, and `UV_OFFLINE=1`, and removes API-key,
token, authorization, cookie, password, credential, and secret-like
environment variables. This is an offline expectation, not an operating
system network sandbox:

```text
hard_network_isolation=False
```

A zero deployment exit code is insufficient. Success additionally requires a
parseable compilation report, the preserved raw
`packaging/deployment/pet_entry.dist`, the final
`dist/SJTUClaw.dist`, an AMD64 GUI `SJTUClaw.exe`, exact raw-to-final file and
SHA-256 equality, an unchanged tracked spec, and an unchanged fixed Dependency
Walker cache.

`packaging/standalone_artifact_audit.py` does not execute the packaged
application. It parses the Nuitka XML report, creates a full final-dist
manifest, parses every PE ordinary and delay-load import table, checks AMD64
consistency and dependency closure, and uses the fixed MSVC 14.44 `dumpbin`
only for independent main-executable header and dependency observations. The
main executable must be Windows GUI, ASLR-enabled, and DEP/NX-compatible.
Control Flow Guard is reported separately rather than silently assumed.

The audit rejects tests, manual-verification and smoke modules, scripts,
Dependency Walker files, build logs and reports, local settings, manual test
Targets, secret-like values, repository/user/virtual-environment paths, and
PNG/atlas/skel character resources. It records the actual platforms,
platformthemes, and styles plugin sets (including an empty family), plus the
included distribution metadata as a preliminary license inventory. This does
not complete
Authenticode, public-distribution license, installer, reputation, runtime, or
wire-level review.

Even after a successful build and static audit, `SJTUClaw.exe` remains
unexecuted. Runtime testing requires a separate authorization:

```text
safe_code=packaged_runtime_authorization_required
```

### Actual one-attempt build result

The separately authorized standalone command ran exactly once on 2026-07-27.
The Windows Job Object was configured before process resume with
kill-on-job-close and an active-process limit of 128. The observed peak was 13
active processes, the root deployment process returned 0, no active-process
limit was hit, no timeout occurred, and no newly remaining build process was
observed. The attempt lasted 4.358 seconds and consumed approximately
5,120,000 bytes of free disk space. The tracked spec and fixed Dependency
Walker cache hashes remained unchanged. No download or installation prompt was
detected.

The deployment exit code was not accepted as success. The parseable Nuitka 4.0
report recorded standalone mode but `completion=error exit message (1)`, zero
included modules, zero included data files, and zero included binaries. The
controlled error stated that Nuitka's PySide6 plugin has no `platformthemes`
plugin family for the installed PySide6 6.11.1 files. Therefore neither the raw
nor final dist existed, and the controller returned:

```text
safe_code=standalone_postcondition_failed
```

This failure occurred before Dependency Walker analysis; its build-time
execution was not observed. No `SJTUClaw.exe` was generated or executed, so PE,
DLL-closure, final plugin, local-path, secret, and license artifact audits
could not be completed. The failed ignored logs are retained only by SHA-256
and byte count in the structured build report.

The source configuration now requests only the plugin families that exist in
the reviewed environment (`platforms` and `styles`), and the PowerShell
preflight explicitly requires those directories plus `qwindows.dll`. This is
the correction that was later used by the separately authorized second build
described below. The first build authorization remained exhausted and was not
reused.

## Existing-artifact audit attribution and dependency-pruning gate

The separately authorized second standalone attempt completed successfully on
2026-07-27. Its build postconditions passed, but the first static audit used
overly broad duplicate-DLL, Qt-plugin, `CredentialBlob`, and Bearer-pattern
rules. Before those rules were changed, the original audit JSON was copied
byte-for-byte to the ignored fixed history directory:

```text
build/standalone-audit-history/
20260727T070135Z-pre-attribution/artifact_audit.json
```

The archived file is 383,989 bytes with SHA-256
`2b53b257dbf3e86f93f10e92234b95d51d78b33caa5b75b4b580397a7da5cd14`.
The raw and final distributions, compilation report, build logs, and
executable were not modified.

DLL resolution now evaluates a unique candidate at the importer's directory
before the distribution root, explicitly modeled PySide6 or shiboken6 runtime
directories, and the Windows system set. Lower-priority duplicates are
recorded as shadowed rather than making a higher-priority unique result
ambiguous. The four duplicate basename groups remain in the report as
inventory. The existing artifact has no ambiguous or unresolved normal or
delay-load dependency under this model.

Qt plugin paths are accepted only at
`PySide6/qt-plugins/<family>/<file>.dll`, where the fixed family allowlist is
`platforms`, `styles`, `imageformats`, `iconengines`, and `tls`. Deeper paths,
unknown families, and `platformthemes` remain invalid. The existing artifact
contains 4 platform, 1 style, 10 image-format, 1 icon-engine, and 3 TLS
plugins. It contains no platformthemes plugin; both `qwindows.dll` and
`qmodernwindowsstyle.dll` are present.

The literal identifier `CredentialBlob` is expected in the Win32 structure
binding and in JSON rejection logic, so identifier presence is now
informational. A contextual high-entropy value after that identifier still
fails. The former Bearer hit is attributed to prose in
`openai/providers/bedrock.py`: type `Bearer`, length 22, SHA-256
`52477424de5444aee8b33d00bc58491877ab0f42f4c587a5149bd069ca1d3df3`.
The report stores only type, length, hash, artifact-relative file, offset, and
attribution; it does not store the matched text. JWT-like, high-entropy
Bearer, known `sk-`, manual Target, and contextual CredentialBlob values
remain forbidden.

Exactly one attribution-aware static re-audit was run against the preserved
artifact. All structural, PE, DLL, Qt, path, and real-secret checks passed.
The only failed check is `production_dependency_surface_valid`, because the
artifact includes `pydantic.mypy`, the `mypy` and `mypyc` trees,
`httpx._main`, the `pygments` tree, and the `mypy`, `mypy_extensions`, and
`Pygments` distributions. These are dependency-surface and license-review
issues, not credential findings. The current result is:

```text
safe_code=standalone_dependency_pruning_required
```

The package has still not been executed and is not authorized for runtime
testing.

## Isolated production-packaging environment

The third-build chain uses the fixed ignored environment
`.venv-packaging`; it does not use the ordinary development `.venv`.
`packaging/prepare_packaging_environment.ps1` is inert unless
`-ConfirmPrepare` is supplied. Its confirmed path fixes uv to version 0.11.2,
uses the existing Python 3.13.6 AMD64 interpreter without downloading Python,
and performs a locked, offline sync with only the runtime dependency set plus
the `gui` and `packaging` extras. It explicitly excludes the `dev` group and
checks that `pyproject.toml` and `uv.lock` hashes do not change.

The generated
`build/windows-packaging-environment/environment_inventory.json` records
package names and versions but no environment-variable values. Validation
uses distribution metadata, import specifications, the site-packages
filesystem, and `sys.path`. It rejects mypy, mypy_extensions, mypyc, pytest,
Pygments, and ruff; it also rejects a prefix, base prefix, `PYTHONPATH`, or
`sys.path` that injects the ordinary development environment.

The standalone controller validates the fixed packaging interpreter,
PySide6, Nuitka, deploy executable, and Qt plugin paths before creating a Job
Object or starting a build process. Its child environment removes the
development Scripts directory, clears `PYTHONHOME` and `PYTHONPATH`, and
prepends only the packaging Scripts directory.

The tracked spec contains one exact no-follow rule for each build-time-only
surface:

```text
--nofollow-import-to=pydantic.mypy
--nofollow-import-to=mypy
--nofollow-import-to=mypy_extensions
--nofollow-import-to=mypyc
--nofollow-import-to=httpx._main
--nofollow-import-to=pygments
```

These rules do not exclude pydantic, httpx, openai, any provider, or the Qt
runtime. The private materialized build spec adds exactly one
`--include-qt-plugins=platforms,styles` argument. Production imports and the
Fake Provider are checked by the inert-by-default
`packaging/production_import_smoke.py`; the six Qt smoke scripts are run with
the isolated interpreter and offscreen Qt.

The original raw distribution from the successful second build was later
deleted by an unsafe dry-run lifecycle. PySide6 6.11.1 constructs its
configuration and calls `cleanup(config)` before checking whether the Nuitka
command is a dry run; its `finally` path can call cleanup again. The former
dry-run implementation copied only the spec. Its source remained
`packaging/pet_entry.py`, so PySide6 derived
`packaging/deployment` as `generated_files_path` and removed that production
raw directory together with generated build/dist subdirectories.

The surviving final distribution and seven build-evidence files remain
unchanged. The raw distribution has not been reconstructed from the final
copy, and prior raw/final equality is historical audit evidence rather than a
newly reverified equality claim. The fixed ignored incident record is:

```text
build/packaging-incidents/20260727-dry-run-cleanup/
```

It records full current manifests, sizes and SHA-256 values, the final
executable hash, `raw_dist_present=False`,
`raw_dist_reconstructed=False`,
`dry_run_cleanup_side_effect_confirmed=True`, and zero third-build attempts.
It stores no environment-variable values.

The corrected dry-run owns the complete fixed
`build/standalone-dry-run` workspace. It byte-copies the production entry to
`input/pet_entry.py`, verifies its SHA-256, rewrites source, project, exec and
compilation-report paths into that workspace, and writes command output only
there. A complete before/after snapshot covers `dist`,
`packaging/deployment`, and `build/windows-standalone`, including existence,
relative paths, sizes, hashes, attributes, reparse status and hard-link
counts. Any difference fails closed before cleanup. Cleanup accepts only a
fixed owned allowlist; an unknown entry preserves the workspace as evidence.

The canonical `packaging/archive_standalone_attempt.py` is directly runnable
under Python isolated mode and owns both fixed archive modes. The redundant
same-directory import wrapper was removed. The degraded surviving-evidence
mode never reconstructs raw output and can archive only:

```text
dist/SJTUClaw.dist/
build/windows-standalone/
```

Its fixed target is:

```text
build/standalone-artifact-archive/
20260727T063632Z-unpruned-degraded/
```

The archive labels prior raw/final equality as reported but not currently
reverified.

### Dry-run recovery and degraded archive result

The repaired real dry-run was executed exactly once. Its effective paths
were:

```text
source_file:
build/standalone-dry-run/input/pet_entry.py

generated output:
build/standalone-dry-run/input/deployment

compilation report:
build/standalone-dry-run/compilation-report.xml

exec directory:
build/standalone-dry-run/dist
```

The emitted command retained standalone mode, the fixed platforms/styles
plugin set and all six narrow no-follow rules. It contained no production
deployment, final-dist or build-report output path. The dry-run branch did
not activate MSVC and PySide6 reported that dumpbin was unavailable; no
Nuitka compilation, cl, link or Dependency Walker execution occurred.

Before and after the run, the final distribution had 136 files totaling
187,599,080 bytes, the build-evidence directory had seven files, and every
recorded size and SHA-256 matched. `packaging/deployment` remained absent.
The owned dry-run workspace was completely removed after its allowlist and
protected snapshots passed.

The degraded surviving evidence was then moved by same-volume rename to:

```text
build/standalone-artifact-archive/
20260727T063632Z-unpruned-degraded/
```

It contains 143 evidence files totaling 191,116,359 bytes with aggregate
manifest SHA-256
`a5d1762838436f08b9c28e373b90d95e4d0166d76a79ea0416970bbe243798f5`.
The executable remains
`10fe39ab457ecf017dc752ce92c90699735f832dbdf44e54d28f6236a5066dae`.
No staging or `.part` directory remains. The original `dist`,
`build/windows-standalone`, and `packaging/deployment` paths are absent, while
the separate incident record is retained. The raw distribution was not
reconstructed.

### Future third-build plan

A third standalone build requires a new explicit authorization. Before it
starts:

1. archive the current successful artifact and keep its reports immutable;
2. create an ignored `.venv-packaging` using the existing lock file and
   `uv --offline`;
3. install only runtime dependencies plus the `gui` and `packaging` extras,
   never the `dev` extra;
4. make the build entry reject the ordinary development `.venv`;
5. add narrow no-follow exclusions for `pydantic.mypy`, `mypy`, `mypyc`,
   `httpx._main`, and `pygments`, without excluding all of pydantic or httpx;
6. prove with offline import tests that production startup, provider
   activation, and the Qt entry do not import those modules;
7. inspect a new dry-run command and compilation plan before authorization;
8. use fresh output directories rather than reusing the current dist;
9. rerun the complete manifest, PE, DLL, Qt, secret, path, dependency-surface,
   and preliminary license audits after that separately authorized build.

### Prebuild scope recovery checkpoint

The first recovery gate invoked:

```text
mypy --strict --no-incremental .
```

The positional `.` overrode the controlled `pyproject.toml` discovery scope
and caused mypy to scan duplicate pytest project copies retained below
`build/test-temp-prebuild`. That directory is failure evidence, not production
source. Its ignored read-only manifest records 1,397 files totaling 3,631,194
bytes, including 14 copies of `pet_entry.py`, with manifest SHA-256
`37884ae98e0d08c760aa30b18c90bf16288349ab3a5abe0aeb697c829b76188e`.
The evidence directory was not deleted, moved, overwritten, or reused.

The canonical type-check command is now:

```text
.\.venv\Scripts\mypy.exe --strict --no-incremental
```

It relies on this explicit repository-relative allowlist:

```text
src
tests
scripts
packaging
```

Anchored exclusions cover only `build/`, `dist/`,
`packaging/deployment/`, `.venv/`, and `.venv-packaging/`. The recovery
gate checked 125 source files successfully while the preserved failure
evidence remained present.

The first regression fixture created empty `src` and `tests` directories, so
mypy stopped before reaching the deliberate errors. Valid
`src/fixture_package/__init__.py` and `tests/test_fixture.py` files correct
discovery without changing production package semantics. The next fixture
used `scripts/type_error.py` and `packaging/type_error.py`; because those
directories are not packages, mypy derived the same top-level module name
twice. The final fixture uses distinct
`scripts/script_scope_type_error.py` and
`packaging/packaging_scope_type_error.py` basenames. Both deliberate return
type errors are reported with exit code 1, proving that neither production
directory was excluded or weakened.

The confirmed-build entry validates that
`build/standalone-third-build-temp` is the exact direct controlled child of
the repository `build` directory. It creates that directory and assigns
`TEMP`, `TMP`, and `TMPDIR` before importing `vcvarsall.bat`; after importing
the MSVC environment it reapplies the packaging environment, assigns all
three variables again, normalizes them, and verifies exact equality before
Python, Nuitka, cl, link, dumpbin, or Dependency Walker may run.

This checkpoint ran no Nuitka compilation, compiler, Dependency Walker,
packaged executable, artifact audit, network request, Credential Manager
operation, or real Provider. The incident record still reports zero
third-build attempts. A third standalone build remains separately
authorization-gated.

### Third standalone build verification checkpoint

The separately authorized third and final standalone build started from
commit `3524d2b92aa832b68524d047782169368a62f176` on
`codex/windows-packaging-preflight`. The build guard was created once, the
controller performed no automatic retry, and the build completed with exit
code 0. No fourth build is authorized.

Before compilation, the packaging environment passed all required version,
specification, prefix, virtual-environment, `PYTHONPATH`, and development-site
checks. It contained 23 distributions, with no forbidden distribution,
import specification, or filesystem entry. The tracked spec retained exactly
the six reviewed no-follow rules. All controllable temporary files, caches,
logs, raw output, final output, and evidence stayed below the repository.

The raw and final distributions each contain 70 files totaling 139,376,360
bytes. Their relative paths, sizes, and SHA-256 values match exactly. The
static audit identified 69 parseable AMD64 PE files and no unknown or
unparseable PE. The main executable is AMD64 with the Windows GUI subsystem.
Its DEP, ASLR, and high-entropy-VA flags are enabled. Control Flow Guard is
not enabled and Authenticode signing is not required at this preliminary
checkpoint; both remain release-hardening considerations.

Every normal and delay-load dependency resolved deterministically, with no
unresolved or ambiguous dependency. The required Windows Qt platform plugin
is present at
`PySide6/qt-plugins/platforms/qwindows.dll`; no `platformthemes` file is
present. The final distribution contains no Dependency Walker executable,
debug symbol, import library, build report, XML, or JSON evidence file.

The compilation report contains no forbidden production module,
distribution, or resource. The artifact scan found no real secret material,
local development path, manual-verification Credential Target, or external
character-resource path. A source-level `CredentialBlob` identifier is not
credential material and is tracked separately from the zero real-secret
finding. The auditor and build harness did not access the network or Windows
Credential Manager and did not execute the packaged application. The
controller did not provide an operating-system-enforced hard network
isolation boundary, so the result is evidence of no observed harness access,
not a general network non-interference proof.

Post-build regression results were:

```text
pytest: 920 passed, 1 skipped
ruff: all checks passed
mypy strict: 125 source files checked successfully
PowerShell AST: passed
git diff --check: passed
Qt Fake smokes: 6 passed
production imports: valid
Fake Provider smoke: passed
forbidden production imports: 0
OpenAI manual entry: manual_verification_disabled
DeepSeek manual entry: manual_verification_disabled
```

The skipped pytest case remains the explicitly gated real Windows Credential
Manager integration test. No real Provider, API key, Credential Manager
integration, packaged executable, DLL, or PYD was run or loaded. Runtime
execution of the packaged application remains separately authorization-gated.

### Recursive JSON alias corrective source checkpoint

The first authorized packaged-runtime owner launch created the audited
standalone executable once and exited with code 1 before Qt, the runtime,
SecretStore, or any Provider was initialized. The compiled
`sjtuclaw.infrastructure.llm.openai_sdk` module raised a `NameError` while
binding the self-recursive `JSONValue` PEP 695 alias. CPython imports the same
source successfully, but Nuitka 4.0 eagerly resolved the recursive reference
while initializing the compiled module.

The source-level correction retains `JSONScalar`, `JSONValue`, and
`JSONObject` and preserves their recursive static typing. Only the recursive
edges now use string forward references through an explicitly documented
`TypeAlias` compatibility exception. The alias was not weakened to `Any` or
`object`, and the OpenAI request, response-event, normalization, Provider, and
SDK adapter APIs remain unchanged. A repository-wide AST check found no other
self-recursive PEP 695 alias; the packaging regression test prevents this
specific alias from returning to the incompatible form.

Invalid JSON normalization continues to raise `OpenAISDKError` with
`code == "invalid_response"` for internal classification. Its user-visible
message and exception arguments remain the fixed sanitized text
`The OpenAI SDK operation failed safely.`. Regression tests verify that raw
invalid input is absent from `str`, `repr`, formatted traceback, and
`logger.exception` output.

Corrective source-level regression results were:

```text
OpenAI SDK: 33 passed
OpenAI Provider: 80 passed
pytest: 935 passed, 1 skipped
ruff: all checks passed
mypy strict: 125 source files checked successfully
PowerShell AST: 10 files passed
git diff --check: passed
Qt Fake smokes: 6 passed
production imports: valid
Fake Provider smoke: passed
forbidden production imports: 0
OpenAI manual entry: manual_verification_disabled
DeepSeek manual entry: manual_verification_disabled
```

No Nuitka, MSVC, Dependency Walker, network, Credential Manager, or real
Provider operation was performed during this corrective checkpoint. The old
70-file standalone remains the known failing artifact and was not modified or
executed again. A corrected standalone has not yet been generated; rebuilding
and auditing it requires separate authorization.

### Corrective standalone artifact checkpoint

One separately authorized corrective standalone build was performed from
commit `959285087481b177429bc77b5728c364e3b6cb92`. The attempt guard was
created before process creation, stdin was closed, automatic retry remained
disabled, and no second corrective build was attempted. The Job Object was
configured with kill-on-close and a 128-process active limit. The build
completed without timeout or remaining child processes:

```text
build attempts: 1
automatic retries: 0
duration: 1406.151 seconds
disk consumed: 906813440 bytes
total processes: 1794
peak active processes: 38
pyside6-deploy exit code: 0
```

The MSVC 14.44 toolchain started a `vctip.exe` helper after compilation. The
Job Object correctly retained the build until that helper exited, rather than
publishing a premature success result. No download or installation prompt was
observed. The harness set the fixed offline package-manager variables and
reported no network or Credential Manager access, but it did not provide an
operating-system-enforced hard network-isolation boundary.

The raw and final standalone manifests contain the same 70 relative paths,
sizes, and SHA-256 values. The final artifact contains 70 files, 69 parsed PE
files, and 139376872 total bytes. The corrected executable SHA-256 is:

```text
119192a1380a639e4bdce581fe41e72534647ade6f119d27742a745cd275bdfe
```

It differs from the archived failing executable. The old 147-file failure
archive and 5308-file residual-build archive were revalidated against their
stored manifests with zero size or hash mismatches. Their manifest hashes
remain:

```text
old failure archive: 293e73a19372f1b53f618f67158c5dd7705c180ed7a025b36393f8d9b9328673
residual build archive: bf35bb036a84f7c7e22da523deb3229cb92e6ea64258fabe158b0ed5e92fd659
```

The corrected compilation report has `completion=yes`, `mode=standalone`,
`architecture=x86_64`, and no onefile node. It includes
`sjtuclaw.infrastructure.llm.openai_sdk` from the current production entry
surface. This confirms that the corrected module was compiled; it is not a
runtime proof that the recursive alias now imports successfully in the
packaged executable.

All 69 PE files parsed as AMD64. The main executable uses the Windows GUI
subsystem. ASLR, DEP/NX compatibility, and High Entropy VA are enabled;
Control Flow Guard is not enabled and remains recorded as a deployment
hardening limitation. Unresolved and ambiguous dependency counts are both
zero. The required `qwindows.dll` and `qmodernwindowsstyle.dll` plugins are
present under the expected Qt plugin layout, `platformthemes` is empty, and
the plugin dependency closure is complete.

The production dependency scan found zero occurrences of `pydantic.mypy`,
`mypy`, `mypy.*`, `mypy_extensions`, `mypyc`, `mypyc.*`, `httpx._main`,
`pygments`, `pygments.*`, or `Pygments`. The artifact contains no real secret
material, Authorization value, real CredentialBlob, manual-verification
Credential Target, user directory, development virtual-environment path,
external character-resource path, settings, conversation, or continuation.
The source-level `CredentialBlob` identifier remains classified separately
from credential material. Dependency Walker files are absent from the final
distribution.

Corrective post-build regression results were:

```text
OpenAI SDK: 33 passed
OpenAI Provider: 80 passed
pytest: 935 passed, 1 skipped
ruff: all checks passed
mypy strict: 125 source files checked successfully
PowerShell AST: 10 files passed
git diff --check: passed
Qt Fake smokes: 6 passed
production imports: valid
Fake Provider smoke: passed
forbidden production imports: 0
OpenAI manual entry: manual_verification_disabled
DeepSeek manual entry: manual_verification_disabled
```

Neither the corrected `SJTUClaw.exe` nor any packaged DLL or PYD was executed,
imported, or loaded during this checkpoint. Runtime validation of the
corrected executable remains separately authorization-gated.
