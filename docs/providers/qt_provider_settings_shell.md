# Qt Provider Settings Shell

## Scope

This stage adds an ordinary, testable `QMainWindow` and Provider settings
dialog. It intentionally does not implement a transparent desktop-pet window,
tray integration, animation, custom Provider endpoints, packaging, persistent
chat history, tools, or long-term memory.

## Runtime ownership

`QtRuntimeBridge` remains GUI-owned. `RuntimeThread` owns the asyncio loop and
creates the production object graph through
`ProductionQtRuntimeCompositionRoot`:

```text
RuntimeThread
  JsonProviderProfileRepository
  WindowsCredentialSecretStore
  DefaultActiveTurnCoordinator
  ProviderSettingsService / ProviderProfileService lifecycle
  ProviderFactory builder and reviewed ProviderRegistry
  RuntimeSessionController
  AgentLoop and active Provider
```

The GUI receives only immutable runtime and settings views. It never receives
a Repository, SecretStore, Provider, asyncio Task, `SecretValue`,
`CredentialBlob`, API key, or continuation.

Constructing the composition-root object on the GUI thread stores only the
metadata path and a factory callable. The runtime graph is constructed when
`RuntimeThread` invokes it. Startup initializes non-sensitive built-in
metadata but does not query a credential, construct a cloud SDK client,
activate a Provider, or send a network request.

## Settings boundary

`ProviderSettingsService` is framework-neutral. It validates the reviewed
Fake, OpenAI, and DeepSeek profile types, delegates lifecycle-safe profile
operations to `ProviderProfileService`, and maps SecretStore operations to
fixed safe codes.

Credential views expose only `configured=True/False`. Saved values are never
read back into the dialog. The API-key field uses Qt Password echo mode and is
cleared immediately after command submission. Runtime command `repr` excludes
the secret field and the worker clears its reference after processing.

Python strings are immutable and the interpreter may retain copies, so the
application cannot promise reliable in-memory zeroization. The design instead
minimizes reference lifetime, prevents serialization and logging, and keeps
the value out of Qt result signals, snapshots, exceptions, and UI models.

OpenAI and DeepSeek continue to use reviewed fixed origins and credential
targets. Manual-verification CredentialIds remain outside production
metadata and are rejected by the production policy and settings service.
Custom base URLs are not accepted.

A credential used by the current runtime Profile cannot be overwritten or
deleted in place. The user must first switch to another Profile. This rule is
enforced by `ProviderSettingsService` before any SecretStore write or delete;
the dialog mirrors it by disabling the two credential actions and explaining
why. A future credential-rotation workflow must rebuild and publish a new
Provider explicitly instead of mutating the active Provider's credentials
behind its back.

Profile and credential deletion require an explicit confirmation dialog.
Credential confirmation displays only reviewed binding metadata and never
reads or renders the stored secret.

## Commands and Provider switching

Settings operations use the existing command-id protocol. Each accepted or
rejected command has exactly one terminal `command_completed` or
`command_failed` signal. Repository, SecretStore, and Provider work occurs in
`RuntimeThread`; GUI methods only validate small DTO fields and enqueue.

After a turn emits its user-visible terminal event, the controller releases
the finished asyncio Task and emits an internal `turn_settled` lifecycle
event. RuntimeThread then publishes a final snapshot with no active turn.
This ordering prevents a stale pre-release snapshot from leaving the GUI in a
permanent busy state after the first reply or cancellation.

When a turn is active, the settings dialog requires an explicit choice:

- wait for the current turn;
- cancel the current turn and then switch;
- abandon the switch.

There is no default cancellation or silent wait. Lifecycle coordination stays
inside `DefaultActiveTurnCoordinator`. `cleanup_pending` blocks metadata,
credential, and activation mutations until retained Providers are cleaned.

## Main window and shutdown

The conversation widget is `QPlainTextEdit`; model content is inserted only
as plain text. Runtime readiness and active-turn signals control send, cancel,
and settings actions.

The first `closeEvent` is ignored while the runtime thread is active. The
window disables new actions and submits asynchronous shutdown while the
QApplication event loop keeps running. A successful `shutdown_finished`
allows a second, final close. A failure leaves the window and RuntimeThread
references alive, displays only a fixed safe error, and permits a later
shutdown retry. The GUI does not call `QThread.wait()`, `terminate()`,
`asyncio.run()`, a nested event loop, or `processEvents()`.

## Running

Install the optional GUI dependency and start the production shell:

```powershell
uv sync --extra dev --extra gui
.\.venv\Scripts\arkclaw-gui.exe
```

The offline GUI smoke uses the Fake composition root:

```powershell
.\.venv\Scripts\python.exe .\scripts\qt_gui_smoke.py
```
