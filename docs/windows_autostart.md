# Optional Windows Autostart

SJTUClaw autostart is an explicit user setting and is disabled by default.
Opening Agent Settings, the tray menu, or the pet context menu may query the
current state, but it never creates, changes, or deletes a registry value.
Only an explicit user toggle submits a mutation.

## Fixed registration

The production backend owns only this per-user value:

```text
Key: HKCU\Software\Microsoft\Windows\CurrentVersion\Run
Value name: SJTUClaw
Value type: REG_SZ
Value data: "<absolute packaged SJTUClaw.exe>" --startup
```

The executable must be an absolute, local, ordinary, non-reparse, single-link
file named `SJTUClaw.exe`. The current process must carry Nuitka's compiled
runtime marker with `standalone=true`, `onefile=false`, and a containing
directory that strictly matches the executable directory. Source launches,
Python executables, scripts, `.venv`, `.venv-packaging`, UNC paths, control
characters, and over-limit commands are rejected. The command has one fixed
argument and cannot be supplied or extended by UI input.

Enabling first confirms that the fixed value is absent or already equals the
expected command. A different value is `occupied` and is never overwritten.
After writing, the service reads the value back and requires an exact type and
command match.

Disabling first reads the value again. It deletes only when the current type
and command still match the application-owned value. A changed or removed
value after ownership was confirmed is `ownership_lost`; SJTUClaw does not
delete or replace it.

## Shared UI state

Agent Settings, the system tray, and the pet context menu use one
`AutostartUiController`. The controller submits non-blocking commands through
`QtRuntimeBridge`; `AutostartService` and the Windows backend are created and
used only inside `RuntimeThread`.

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
or Task Manager. Windows may delay execution of a Run entry. The SJTUClaw UI
reports whether its own Run command is registered; it does not claim that
Windows will execute it immediately.

SJTUClaw never modifies Windows' internal `StartupApproved` state and does not
attempt to bypass a Windows-level user decision to disable the application.
An ordinary application shutdown leaves a valid autostart registration in
place.

All automated tests use an injected in-memory backend. They do not access the
real registry, network, Credential Manager, or a real Provider.

The production value name is not injectable. A future separately authorized
real-registry verification must use a narrow manual-only adapter with the
fixed value name `SJTUClaw-Test-Autostart`, must refuse an occupied value, and
must delete only a value that it wrote and still strictly owns. Its default
entry must remain inert. No such real HKCU validation was run in this stage.

Autostart still depends on a stable installed executable path, which is not yet
provided by an installer. Onefile mode is intentionally rejected and remains
unverified. Future uninstallation is responsible for safely removing an
exactly owned Run value. File-system and registry time-of-check/time-of-use
(TOCTOU) races can be reduced by strict re-reading and ownership checks but
cannot be eliminated completely.
