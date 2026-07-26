# Desktop-pet settings persistence

The placeholder pet stores a deliberately small, non-sensitive settings
document. It is separate from Provider profile metadata and from Windows
Credential Manager.

## Stored fields

Schema version 1 contains exactly:

```json
{"schema_version":1,"window_x":100,"window_y":200,"always_on_top":true}
```

No API key, CredentialBlob, Provider/Profile data, conversation, continuation,
runtime state, pause state, visibility state, animation state, asset path,
window size, or scale factor is accepted or serialized.

The production path is the Qt `AppLocalDataLocation` for SJTUClaw followed by
`pet_settings.json`. It is fixed by the application; the desktop-pet CLI does
not accept an arbitrary settings path. Tests inject temporary repository paths.

## Load and validation

Only the owner process constructs and reads the repository, after the
single-instance gate succeeds. The parser enforces UTF-8, an exact field set,
strict integer and Boolean types, bounded coordinates, a 16 KiB document limit,
and schema version 1. JSON `NaN`, infinity values, and duplicate keys in any
object are rejected before an object is converted to a dictionary.

A missing document uses the window's safe built-in defaults. Corrupted,
oversized, invalid UTF-8, unreadable, and unsupported-schema documents also
fall back to those defaults with fixed safe codes. Such a document becomes
read-only for that process lifetime, so a normal shutdown cannot silently
delete or overwrite evidence or a future-version document. Raw JSON, paths,
and filesystem exception text are not sent to the UI or logs.

The complete settings subsystem is optional. Path discovery, controller
construction, and Repository load failures map to
`pet_settings_initialization_failed`; window application failures map to
`pet_settings_restore_failed`. The Runtime, pet window, and tray still start
with the window's constructor defaults.

Loaded coordinates are applied to the authoritative motion model and clamped
to the current display workspaces before the window is shown. This handles
removed displays, 150%/200% logical-coordinate scaling, and changed desktop
layouts without persisting monitor identifiers, scale factors, or window size.

## Save and shutdown

There are no writes on move, drag, animation frames, topmost toggles, or failed
runtime shutdown. After the Runtime reports a successful safe shutdown, the
coordinator:

1. clamps the position against the current workspaces again;
2. captures `window_x`, `window_y`, and `always_on_top`;
3. attempts one atomic save for the process lifetime;
4. continues Renderer, tray, window, single-instance lock, and application
   cleanup even if the settings write fails.

The repository creates a temporary file in the destination directory, writes
UTF-8, flushes, calls `fsync`, and then uses `os.replace`. A failed write keeps
the previous document and reports `pet_settings_write_failed`; temporary files
are removed on the handled failure path.

A final window snapshot or `PetSettings` construction failure reports
`pet_settings_snapshot_failed`. Snapshot and write failures never change the
successful Runtime shutdown result and do not prevent tray, Renderer, timer,
main-window, single-instance lock, or QApplication cleanup. Only ordinary
`Exception` failures are contained; process-control exceptions retain their
normal Python semantics.

## Offline verification

Run:

```powershell
.\.venv\Scripts\python.exe .\scripts\qt_pet_settings_smoke.py
```

The smoke uses a temporary directory and Fake Runtime for two independent
window lifecycles. It checks first-run save, second-run restore, thread/timer
cleanup, zero pending asyncio tasks, and zero leftover settings temporary
files. It does not access the network, real Providers, Windows Credential
Manager, API keys, or external character resources.

An abnormal process termination cannot run the successful shutdown path, so
the current session's last position may be lost. The previous atomically
replaced settings document remains the recovery point.
