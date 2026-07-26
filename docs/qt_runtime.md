# Qt Runtime Bridge

## Scope

This stage provides the thread and lifecycle foundation for a future Qt
desktop application. It does not provide a window, tray icon, pet animation,
Provider settings page, real credential input, or cloud connection.

The optional `gui` dependency is pinned to `PySide6==6.11.1`. Installing the
base package does not import or require PySide6; Qt modules are imported only
when the Qt presentation or bootstrap packages are used.

## Architecture and ownership

```text
GUI main thread
  QCoreApplication / future QApplication
  QtRuntimeBridge
  RuntimeThread object (QThread controller object)
          |
          | loop.call_soon_threadsafe(queue.put_nowait, command)
          v
Runtime QThread
  one persistent asyncio event loop
  command queue and dispatcher
  QtRuntimeCompositionRoot
  RuntimeSessionController
  DefaultActiveTurnCoordinator
  ProviderProfileService / Repository / Factory
  AgentLoop / Provider / asyncio Tasks
```

`RuntimeThread` is a `QThread` object created and owned by the GUI thread.
Its `run()` method executes in the worker thread and creates the sole runtime
asyncio loop there. No Qt slot is placed on the `QThread` subclass with the
assumption that object affinity will move it to the worker.

The GUI never receives a Provider, Repository, SecretStore, asyncio Task,
Future, `SecretValue`, or `ProviderContinuation`. The runtime graph is created
by the composition root after the worker starts and remains owned by that
thread.

## Command and signal paths

GUI commands are immutable command DTOs with unique `command_id` values.
`QtRuntimeBridge` validates immediate UI-boundary errors, and
`RuntimeThread.submit()` uses `loop.call_soon_threadsafe()` to enqueue accepted
commands. The GUI does not call `Future.result()`, `thread.wait()`, or
`asyncio.run()`.

Runtime results are emitted through queued Qt signals. Their payloads are
limited to immutable snapshots, turn identifiers, agent state, text deltas,
final text, and fixed safe error fields. Continuation state and credentials
stay inside `RuntimeSessionController`.

Every public bridge call allocates one tracked `command_id`. A command leaves
the pending set exactly once through either `command_completed` or
`command_failed`. Results arriving after that terminal transition are ignored.
If the worker exits unexpectedly, the bridge fails every remaining command
with a fixed safe error rather than leaving a UI operation unresolved.

Calling `shutdown()` while the bridge is `STARTING` records a shutdown intent
inside `RuntimeThread` under the same lock that protects its loop and queue.
The bridge moves directly to `CLOSING`, rejects ordinary commands, and does not
emit `runtime_ready`. After the composition root returns, the worker observes
the intent and shuts the controller down before entering the normal command
dispatcher. The GUI event loop does not need to process a ready signal for
this protocol to make progress.

## Turn coordination and state commit

Only one Agent turn may be active.

- `WAIT_FOR_ACTIVE` awaits the active Task through `asyncio.shield()`. Cancelling
  the switch therefore does not cancel or lose the active turn.
- `CANCEL_ACTIVE` sets the cooperative `CancellationToken`, waits for an Agent
  terminal event and stream cleanup, and then waits for the Task to finish.
- A switch with an active turn and no explicit policy fails with
  `switch_requires_turn_decision`.

The session history and profile-scoped continuation are updated only after an
Agent `TURN_COMPLETED` event. Text deltas are provisional UI output.
`TURN_FAILED`, `TURN_CANCELLED`, timeout, malformed terminal output, and
unexpected exceptions do not commit the user message, partial assistant text,
or continuation.

## Provider lifecycle

The runtime snapshot maps the service lifecycle directly:

- `inactive`: no published runtime Provider.
- `switching`: the old Provider is being quiesced or replaced.
- `active`: a Provider is published for one Profile.
- `cleanup_pending`: a failed close is retained and must be retried.
- `closed`: the Profile service has completed shutdown.

While `cleanup_pending`, no new turn is accepted and no candidate Provider is
treated as active. Retained and candidate Provider counts are exposed as
non-sensitive integers so a future settings page can explain why an operation
is blocked without receiving resource objects.

## Cooperative shutdown

Shutdown is ordered:

1. mark the controller `closing` and stop accepting commands and turns;
2. cancel or wait for the active turn according to the explicit request;
3. wait for Agent stream cleanup and Task completion;
4. call `ProviderProfileService.aclose()` to retry retained resources;
5. stop the command dispatcher only after successful cleanup;
6. cancel and await any remaining loop-owned Tasks;
7. finalize asynchronous generators with `shutdown_asyncgens()`;
8. wait for the default executor with `shutdown_default_executor()`;
9. clear shared loop and queue references under the submission lock;
10. clear the thread-local event loop and close it;
11. let `QThread.run()` return normally;
12. emit `shutdown_finished` in the GUI thread.

If Provider cleanup fails, the dispatcher remains alive in `closing` state so
shutdown can be retried. The bridge does not report success and does not use
`QThread.terminate()` or `os._exit()`.

Cancellation keeps its native asyncio meaning inside `AgentLoop`, turn
coordination, Provider lifecycle code, controller commands, and loop cleanup
coroutines: those layers re-raise `CancelledError` to their async owner.
`RuntimeThread.run()` is different because it is the final synchronous owner
called by Qt and has no awaiting coroutine above it. At that boundary,
cancellation is converted to a fixed result:

- `runtime_command_cancelled` for the active non-shutdown command;
- `runtime_shutdown_cancelled` for the active shutdown command;
- `runtime_thread_cancelled` when no command owns the cancellation.

The active command receives that result once. When the thread exits, the
bridge fails any other pending commands once with
`runtime_thread_cancelled`. Raw exception text and tracebacks are never signal
payloads.

Cancellation during finalization is also represented only by fixed safe
codes: `runtime_task_cleanup_cancelled`,
`runtime_asyncgen_cleanup_cancelled`, or
`runtime_executor_cleanup_cancelled`. The first cleanup failure is retained,
later independent cleanup stages are still attempted, shared loop references
are cleared, and the event loop is detached and closed where possible. A
Provider or controller close cancellation remains a cancellation throughout
the async layers and is finally mapped at the same `QThread.run()` boundary.
No original exception object is retained for later re-raising.

The `run()` override has a final `BaseException` safety boundary around both
runtime execution and its recovery path. It emits only a fixed shutdown
outcome when possible and then returns normally. This prevents Python
exceptions from crossing into Qt's native thread entry point and producing an
`Error calling Python override of QThread::run()` failure.

`RuntimeThread.submit()` holds the runtime guard through
`loop.call_soon_threadsafe()`. Loop close first disables submissions using the
same guard. Therefore a submission either schedules before the close boundary
or observes the closed/closing state and returns `False`; a closed-loop
`RuntimeError` is also contained as a final defensive check.

This is cooperative cleanup, not a process-level hard deadline. A synchronous
call or a resource close that never reaches a cancellation point can still
prevent shutdown from completing. A future product may need an independently
reviewed watchdog design. Forced process termination can leave external
resources requiring manual inspection.

## Offline smoke

Run the non-production smoke entry after installing the `gui` extra:

```powershell
cd D:\SJTUClaw
.\.venv\Scripts\python.exe .\scripts\qt_runtime_smoke.py
```

It creates a `QCoreApplication`, starts the runtime thread, activates the
built-in Fake Profile, completes one streaming turn, switches to a second
temporary Fake Profile, and shuts down. It uses a temporary metadata document,
does not use a SecretStore, and makes no network request.

## Licensing

PySide6 is distributed under LGPLv3, GPLv2/GPLv3, and commercial licensing
options.
This development dependency choice is not a conclusion that a packaged or
commercial SJTUClaw distribution is compliant. Before distribution, the
project must review the selected Qt license, dynamic-linking and replacement
requirements, notices, bundled Qt components and plugins, deployment tooling,
and any commercial-license obligations.
