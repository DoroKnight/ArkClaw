# Optional Windows Autostart

ArkClaw autostart is an explicit user setting and is disabled by default.
Opening Agent Settings, the tray menu, or the pet context menu may query the
current state, but it never creates, changes, or deletes a registry value.
Only an explicit user toggle submits a mutation.

## Fixed registration

The production backend owns only this per-user value:

```text
Key: HKCU\Software\Microsoft\Windows\CurrentVersion\Run
Value name: ArkClaw
Value type: REG_SZ
Value data: "<absolute packaged ArkClaw.exe>" --startup
```

The executable must be an absolute, local, ordinary, non-reparse, single-link
file named `ArkClaw.exe`. The current process must carry Nuitka's compiled
runtime marker with `standalone=true`, `onefile=false`, and a containing
directory that has Nuitka 4.0's emitted one-level relationship to the
standalone distribution directory. Source launches, Python executables,
scripts, `.venv`, `.venv-packaging`, UNC paths, control characters, and
over-limit commands are rejected. The command has one fixed argument and
cannot be supplied or extended by UI input.

Enabling first confirms that the fixed value is absent or already equals the
expected command. A different value is `occupied` and is never overwritten.
After writing, the service reads the value back and requires an exact type and
command match.

Disabling first reads the value again. It deletes only when the current type
and command still match the application-owned value. A changed or removed
value after ownership was confirmed is `ownership_lost`; ArkClaw does not
delete or replace it.

## Shared UI state

Agent Settings, the system tray, and the pet context menu use one
`AutostartUiController`. The controller submits non-blocking commands through
`QtRuntimeBridge`; `AutostartService` and the Windows backend are created and
used only inside `RuntimeThread`.

Agent Settings separates Provider configuration from autostart configuration
with **Providers** and **General** tabs. The startup control, safe status,
safe error area, and Windows-control explanation live in the scrollable
General page. Both pages use resizable scroll containers and wrapped status
text so the startup checkbox remains reachable at supported high-DPI scales
and smaller legal dialog sizes.

The backend performs only short, synchronous access to one fixed HKCU value.
It does not enumerate keys, recurse, scan files, or use a network. This may
briefly occupy `RuntimeThread`, while the GUI event loop remains non-blocking.
The closing barrier rejects new mutations; an already-running read/write/delete
finishes before the queued safe shutdown proceeds.

The UI states are:

- `unavailable`: the platform or runtime does not support this operation;
- `disabled`: the fixed value is absent;
- `enabled`: the value strictly matches this packaged executable;
- `occupied`: the fixed name contains another value;
- `ownership_lost`: an owned value changed during this process;
- `invalid_executable`: the current process is not the packaged executable;
- `error`: the backend failed behind a sanitized boundary.

The UI does not change its final checked state until the write or delete has
been verified. Backend failures restore the last confirmed checked state and
show only fixed safe codes and messages. Registry data and the complete command
are never sent to Qt signals.

## Controlled packaged-runtime diagnosis

The packaged entry also accepts one exact, explicitly invoked diagnostic
argument:

```text
--diagnose-autostart-runtime
```

This mode exits before constructing `QApplication`, the single-instance
manager, `RuntimeThread`, a Provider, a SecretStore, or the Windows Run-key
backend. It emits one bounded JSON object containing only a schema version,
the fixed completion code, a supported boolean, and one fixed eligibility
reason. It never emits a path, registry value, environment value, exception
message, credential, or command line.

The internal eligibility reasons distinguish the Nuitka marker, standalone
and onefile modes, containing-directory validation, executable resolution and
parent matching, regular-file and reparse-point checks, hard-link count,
fixed executable name, virtual-environment rejection, path safety, and command
length. Ordinary UI state remains intentionally coarser: every failed packaged
eligibility check still maps to the existing fixed `invalid_executable` state.
The internal reason is not sent through Qt signals, logs, public exceptions,
tray state, or pet-menu state.

The diagnostic is observational only. It does not query or mutate the Run key,
and it does not prove registry write/delete behavior. Normal launch and the
fixed `--startup` launch keep their existing behavior.

## Startup mode

The packaged entry accepts only the exact argument:

```text
--startup
```

Startup mode shows the pet and tray while leaving the Agent window hidden. The
pet uses Qt's show-without-activation and no-focus behavior. Startup does not
open Agent Settings, activate a real Provider, read a Provider credential, or
send an Agent request. Single-instance activation and the existing safe
shutdown path remain unchanged.

## Windows control remains authoritative

Users may also control startup through **Windows Settings > Apps > Startup**
or Task Manager. Windows may delay execution of a Run entry. The ArkClaw UI
reports whether its own Run command is registered; it does not claim that
Windows will execute it immediately.

ArkClaw never modifies Windows' internal `StartupApproved` state and does not
attempt to bypass a Windows-level user decision to disable the application.
An ordinary application shutdown leaves a valid autostart registration in
place.

All automated tests use an injected in-memory backend. They do not access the
real registry, network, Credential Manager, or a real Provider.

The production value name is not injectable. A future separately authorized
real-registry verification must use a narrow manual-only adapter with the
fixed value name `ArkClaw-Test-Autostart`, must refuse an occupied value, and
must delete only a value that it wrote and still strictly owns. Its default
entry must remain inert. No such real HKCU validation was run in this stage.

Autostart still depends on a stable installed executable path, which is not yet
provided by an installer. Onefile mode is intentionally rejected and remains
unverified. Future uninstallation is responsible for safely removing an
exactly owned Run value. File-system and registry time-of-check/time-of-use
(TOCTOU) races can be reduced by strict re-reading and ownership checks but
cannot be eliminated completely.

# Packaged runtime eligibility

Nuitka 4.0 reports `__compiled__.containing_dir` as the parent of the
standalone distribution directory. For a non-onefile build, ArkClaw therefore
validates that the packaged executable is exactly one distribution-directory
level below that marker. This check remains separate from the executable's
absolute-path, regular-file, reparse-point, hard-link, fixed-name, virtual
environment, and command-length checks.

The corrected standalone artifact was subsequently exercised once through
the explicit diagnostic-only entry point. The fixed five-field result reported
`supported=true` and `reason=supported`, with exit code 0, empty stderr, no
observed TCP endpoint, and an unchanged 70-file distribution manifest. This
confirms that the packaged Nuitka marker and executable eligibility checks
accept the corrected directory relationship.

The diagnostic did not construct the Windows Run-key backend or ordinary Qt
runtime. It does not verify that the packaged checkbox is operable, that the
tray and pet actions synchronize, that an HKCU Run value can be written or
deleted, that `--startup` behaves correctly, or that Windows login startup
works. Those behaviors still require a separately authorized packaged UI
runtime validation.

## Packaged Run-value timeline verification

The controlled packaged T0-T9 timeline completed successfully with
`safe_code=autostart_packaged_timeline_verified`. The run used one Owner, one
settings-checkbox click, one mutation command and one backend write. The
causal journal remained continuous and nonce-bound, and it recorded zero
backend delete operations and zero tray or pet autostart action activations.

The fixed Run value transitioned from absent to strictly owned and remained
owned through the Owner's ordinary tray-driven shutdown. The Owner exited with
code 0. The PID-scoped network observer reported zero external and zero
unattributed endpoints, and the distribution manifest was unchanged after the
run. The verified executable SHA-256 was
`06ef8e02d5e98cab8405502808558d3ef697d68b51436c89c0f12e3df867caf1`;
the corresponding artifact-audit SHA-256 was
`e27875eb215fb7926b551ba30ab428532ceda46938e4e80462855f654d17b8f7`.

This checkpoint does not verify actual Windows sign-in execution, restart or
logoff behavior, `StartupApproved`, installer or uninstall behavior, or the
user-driven disable lifecycle. It also does not yet verify that the explicit
`--startup` mode preserves focus, keeps the Agent window hidden, or follows the
secondary-instance contract. Those checks require separate controlled runtime
authorization; no automatic logoff or restart is permitted.

## Retained startup Owner exit handle

The external Windows lifecycle observer now opens the startup Owner while it
is still running with only `SYNCHRONIZE` and
`PROCESS_QUERY_LIMITED_INFORMATION`. It freezes the creation FILETIME and
retains the same kernel process handle across the user interaction. After that
handle becomes signaled, it rechecks the creation FILETIME, requires a nonzero
exit FILETIME, and queries the exit code before closing the handle.

The fixed result model distinguishes running, an observed exit code, an
unavailable exit code, PID reuse, process absence, access denial, wait failure,
process-time failure, and exit-code query failure. It never reopens a vanished
PID to infer an exit code, treats `STILL_ACTIVE` as terminal, or converts an
unavailable result into zero. Tests use an injected Win32 backend and verify
that the retained handle is closed exactly once on every terminal or failure
path. This observer is packaging-test infrastructure only and does not change
the packaged application or its shutdown implementation.

## Windows sign-in lifecycle verification

A user-driven Windows logoff and sign-in completed with
`safe_code=autostart_windows_lifecycle_verified`. Windows created one packaged
Owner from the strictly owned Run value. The observed command contained only
the fixed `--startup` argument, the executable matched the audited artifact,
the pet and tray appeared, the Agent window and settings remained hidden, and
ArkClaw did not take foreground focus. No second runtime was observed, and
PID-scoped observation found zero external and zero unattributed endpoints.

The user then disabled autostart with one settings-checkbox action. The
settings, tray and pet states synchronized to unchecked, and the fixed Run
value became absent. The external observer had already retained the matching
Owner process handle. After the user selected tray Exit, the same handle was
signaled, its creation FILETIME still matched, its exit FILETIME was nonzero,
and `GetExitCodeProcess` returned zero. No force termination was used. The Run
value remained absent during the post-exit change-notification window, and no
Owner or observer process remained.

The verified distribution still contained 70 files totaling 139,884,776
bytes, with no missing, extra, size-mismatched or hash-mismatched entries. The
main executable SHA-256 remained
`06ef8e02d5e98cab8405502808558d3ef697d68b51436c89c0f12e3df867caf1`,
and the artifact-audit SHA-256 remained
`e27875eb215fb7926b551ba30ab428532ceda46938e4e80462855f654d17b8f7`.
`StartupApproved` was not accessed, other Run values were not enumerated, and
no Credential Manager, real Provider, API-key or external-network operation
was exercised. The machine is restored to the default disabled state.

This verification does not cover restart or shutdown startup behavior,
Windows policy changes, Authenticode, an installer, uninstall cleanup, or
future Windows versions. Windows remains authoritative and may independently
disable or delay a registered startup application.
