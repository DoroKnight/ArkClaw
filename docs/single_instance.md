# Desktop pet single-instance boundary

The production pet entry point creates `QApplication` first, then performs the
single-instance decision before constructing the composition root, runtime
bridge, `RuntimeThread`, windows, tray, Provider factory, or credential store.

`QLockFile` is the sole ownership authority. The fixed production lock lives in
Qt's per-user `AppLocalDataLocation`. The owner keeps the lock for the complete
GUI and runtime lifetime. A runtime shutdown failure does not emit the
application's final `quit_requested` signal, so the lock remains held. It is
released only after the reviewed shutdown path has cleaned the runtime, tray,
Renderer, and windows.

Production explicitly calls `setStaleLockTime(0)` before `tryLock()`. This
disables replacement based only on lock-file age, so a long-running owner can
never be displaced merely because its lock is old. Qt may still recover an
abandoned lock when it can reliably establish that the recorded process no
longer exists. Tests that simulate abnormal-owner recovery inject a separate,
non-zero threshold; production does not.

`QLocalServer` is not used as a mutex. It only carries this versioned protocol:

- request: `ACTIVATE_PET_V1`
- accepted response: `ACK_V1`
- closing response: `BUSY_V1`
- invalid response: `REJECT_V1`

Messages are newline terminated, ASCII only, and limited to 64 bytes. Unknown,
repeated, overlong, truncated, and non-ASCII messages are rejected without
printing their bytes. The server uses
`QLocalServer.SocketOption.UserAccessOption`. It queues the fixed ACK before
emitting the activation signal on a later Qt event, preventing IPC cleanup from
being re-entered by GUI callbacks.

At most eight accepted clients may be active. `setMaxPendingConnections(8)`
limits only the unaccepted queue, so the manager also enforces a separate
accepted-client table. Every accepted client owns one single-shot read timer.
An incomplete client is closed with `single_instance_client_timeout`; a ninth
active client is immediately rejected with
`single_instance_client_limit_reached`. Completion, rejection, disconnect,
timeout, and manager shutdown share one idempotent cleanup path for the socket
and timer.

When the lock is already held, the secondary process performs only bounded
local connection, write, and ACK waits. It never constructs a second runtime,
window, tray, Provider, repository, or credential store. An unreachable owner,
permission failure, timeout, or unrecognized response fails closed; IPC failure
never promotes the secondary process to owner.

A valid activation reclaims a hidden pet into an available display workspace
and shows it without calling `raise_()` or `activateWindow()`. It does not open
the Agent window, activate a Provider, cancel the current turn, or create new
GUI/runtime objects. An owner already in `closing` returns the fixed busy
response and remains closed to activation.

The implementation never calls `removeStaleLockFile()`. Permission errors and
unknown lock states remain fail-closed. A Windows host whose process or
hostname identity cannot be interpreted reliably can therefore require manual
inspection; an IPC connection failure alone is never treated as proof that the
owner is dead.

`SingleInstanceManager.close()` contains ordinary server, client, timer, and
lock cleanup failures behind `single_instance_cleanup_failed`. It attempts all
independent resources, retains failed references, and permits an explicit
retry. A failed `lock.unlock()` never reports `released=True`. These optional
IPC cleanup failures do not raise through a Qt Slot or block the application's
final quit request.

The fully offline two-process smoke uses a unique server namespace and a
temporary lock directory:

```powershell
.\.venv\Scripts\python.exe .\scripts\qt_single_instance_smoke.py
```

It starts one fake-runtime owner and one secondary process, verifies one
activation, and completes the normal safe shutdown. It does not access the
network, Windows Credential Manager, a real API key, or a production
single-instance namespace.
