# Placeholder pet system tray

The placeholder pet creates a `QSystemTrayIcon` only when
`QSystemTrayIcon.isSystemTrayAvailable()` reports that a platform tray exists.
The icon is drawn programmatically into several `QPixmap` sizes; the repository
contains no PNG, ICO, font, or character asset.

The tray exposes only these fixed commands:

- Show/Hide Pet
- Open Agent Window
- Pause/Continue
- Always on Top
- Exit

`SystemTrayController` depends on the narrow `PetTrayCommands` Protocol. It
does not access a Provider, repository, SecretStore, AgentLoop, continuation,
API key, network client, asyncio task, or RuntimeThread. The
`PetApplicationCoordinator` implements the commands and remains the single
window-operation boundary.

The pet context menu and tray call the same `PetWindow.toggle_paused()` and
`PetWindow.set_always_on_top()` methods. `presentation_state_changed` refreshes
the tray after changes initiated from either surface, so there is no second
pause or topmost state.

Hiding the pet does not stop its animation timer or the Agent Runtime. Showing
it first constrains the current position to an available display workspace.
Closing the Agent window still only hides it and preserves the existing
session, MainWindow, RuntimeThread, and active Profile.

Tray Exit reuses the reviewed asynchronous shutdown path. The exact successful
order is:

1. the exit request moves `PetWindow` to `closing` and immediately stops its
   animation timer;
2. the tray menu becomes disabled while the icon remains alive;
3. `RuntimeThread` performs cooperative cleanup;
4. `shutdown_finished(success=True)` is received;
5. the tray is hidden and cleaned;
6. the Renderer and windows close;
7. `QApplication.quit()` is requested.

Exit is idempotent. On runtime shutdown failure, the pet recovers in `paused`,
its timer resumes, tray operations are restored, the Runtime reference is
preserved, and a later explicit Exit retries the same safe path.

If the platform tray is unavailable, construction returns the fixed safe code
`system_tray_unavailable`. The pet remains visible and its context menu remains
functional. The application does not retry tray construction automatically.

The tray is optional and all factory, show, refresh, and cleanup calls are
isolated at `SystemTrayController`. Ordinary Qt tray failures expose only fixed
codes: `system_tray_initialization_failed`,
`system_tray_refresh_failed`, or `system_tray_cleanup_failed`. They never copy
the underlying exception text. Initialization failures degrade to the pet
context menu without constructing a second tray. Refresh failures are contained
inside the Qt callback boundary. Cleanup failures retain the view reference for
an explicit retry, but never block Renderer, window, RuntimeThread, or
application cleanup.

The offline tray smoke uses an injected Fake Tray:

```powershell
.\.venv\Scripts\python.exe .\scripts\qt_tray_smoke.py
```

It does not claim to verify the Windows Explorer notification area. Real tray
presence, icon appearance, and interaction require manual Windows acceptance.
This stage does not implement autostart, single-instance locking, packaging,
notifications, external icons, Spine, or official character resources.
