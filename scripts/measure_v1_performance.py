"""Stage 10 F - V1 performance baseline measurement.

Measures the production Desktop<->Dashboard seam (FrontendPresentationCoordinator
+ DashboardIntegration) under the offscreen Qt platform - the same platform the
automated Qt suites use:

- Dashboard cold-open latency: first create + show of the production window;
- warm reopen latency: hide + show of the reused window;
- private memory at: startup (no dashboard), dashboard open, dashboard hidden,
  after dispose, and after 100 open/close cycles (the automated long-session
  proxy used by the runtime-reliability suite);
- top-level widget count stability across cycles;
- window identity stability (reopen must reuse the same DashboardWindow).

Outputs a machine-readable JSON report plus a human summary.  No network, no
backend, no sleeps; deterministic and fast.  Memory uses the Windows
GetProcessMemoryInfo API when available (production target) and reports the
Python heap otherwise.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QMessageLogContext,
    QtMsgType,
    qInstallMessageHandler,
)
from PySide6.QtWidgets import QApplication

from arkclaw.presentation.qt.dashboard.dashboard_integration import (
    DashboardIntegration,
)
from arkclaw.presentation.qt.dashboard.dashboard_page import DashboardPage
from arkclaw.presentation.qt.frontend_presentation_coordinator import (
    FrontendPresentationCoordinator,
)

_OUTPUT = Path(__file__).resolve().parent.parent / "docs" / "release"
_REPORT = _OUTPUT / "v1_performance_baseline.json"
_CYCLES = 100


def _flush(application: QApplication) -> None:
    application.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _private_bytes() -> int | None:
    """Return process private memory in bytes, or None off-Windows."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class _PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = _PROCESS_MEMORY_COUNTERS()
    counters.cb = ctypes.sizeof(_PROCESS_MEMORY_COUNTERS)
    get_current_process = ctypes.windll.kernel32.GetCurrentProcess
    get_current_process.restype = wintypes.HANDLE
    get_memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
    get_memory_info.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_PROCESS_MEMORY_COUNTERS),
        wintypes.DWORD,
    ]
    get_memory_info.restype = wintypes.BOOL
    ok = get_memory_info(
        get_current_process(),
        ctypes.byref(counters),
        counters.cb,
    )
    if not ok:
        return None
    return int(counters.PagefileUsage)


def _measure(
    application: QApplication,
) -> dict[str, object]:
    before_construct = time.perf_counter()
    presentation = FrontendPresentationCoordinator()
    integration = DashboardIntegration(presentation)
    construct_ms = (time.perf_counter() - before_construct) * 1000.0

    memory_startup = _private_bytes()

    cold_start = time.perf_counter()
    window = integration.open(DashboardPage.HOME)
    cold_open_ms = (time.perf_counter() - cold_start) * 1000.0
    _flush(application)
    memory_open = _private_bytes()

    # Warm reopen: hide then show the SAME window object.
    integration.close()
    _flush(application)
    memory_closed = _private_bytes()
    warm_start = time.perf_counter()
    reopened = integration.open(DashboardPage.HOME)
    warm_open_ms = (time.perf_counter() - warm_start) * 1000.0

    # Long-session proxy: 100 open/close cycles, sampling memory growth.
    memory_samples: dict[str, int | None] = {}
    identity_stable = True
    for cycle in range(1, _CYCLES + 1):
        integration.close()
        current = integration.open()
        if current is not window or reopened is not window:
            identity_stable = False
        _flush(application)
        if cycle % 20 == 0:
            memory_samples[str(cycle)] = _private_bytes()

    integration.dispose()
    _flush(application)
    memory_disposed = _private_bytes()

    top_levels = [w for w in application.topLevelWidgets() if w.isVisible()]
    return {
        "platform": sys.platform,
        "qt_platform": os.environ.get("QT_QPA_PLATFORM", "unspecified"),
        "cycles": _CYCLES,
        "construction_ms": round(construct_ms, 2),
        "cold_open_ms": round(cold_open_ms, 2),
        "warm_open_ms": round(warm_open_ms, 2),
        "window_identity_stable_across_cycles": identity_stable,
        "visible_top_levels_after_dispose": len(top_levels),
        "memory_bytes": {
            "startup": memory_startup,
            "dashboard_open": memory_open,
            "dashboard_closed": memory_closed,
            "disposed": memory_disposed,
            "samples_per_20_cycles": memory_samples,
        },
    }


_KNOWN_OFFSCREEN_WARNINGS = {
    "This plugin does not support raise()",
    "This plugin does not support propagateSizeHints()",
}


def _install_message_audit() -> None:
    def handle(
        message_type: QtMsgType,
        context: QMessageLogContext,
        message: str,
    ) -> None:
        del context
        if message_type is QtMsgType.QtWarningMsg and (
            message in _KNOWN_OFFSCREEN_WARNINGS
            or "Cannot find font directory" in message
        ):
            return
        print(message, file=sys.stderr)

    qInstallMessageHandler(handle)


def main() -> int:
    _install_message_audit()
    application = QApplication.instance()
    if not isinstance(application, QApplication):
        application = QApplication([])
    report = _measure(application)
    _OUTPUT.mkdir(parents=True, exist_ok=True)
    _REPORT.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    memory = report["memory_bytes"]
    assert isinstance(memory, dict)
    start = memory.get("startup")
    disposed = memory.get("disposed")
    growth = (
        f"{disposed - start:,} bytes"
        if isinstance(start, int) and isinstance(disposed, int)
        else "n/a (non-Windows)"
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"report={_REPORT}")
    print(f"memory growth after {_CYCLES} cycles: {growth}")

    ok = bool(
        report["window_identity_stable_across_cycles"]
        and report["visible_top_levels_after_dispose"] == 0
    )
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
