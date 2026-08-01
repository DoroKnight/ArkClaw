"""Production construction for the optional autostart service."""

from __future__ import annotations

import sys
from pathlib import Path

from sjtuclaw.application.autostart_eligibility import (
    MAX_AUTOSTART_COMMAND_LENGTH,
    AutostartEligibilityResult,
    inspect_autostart_executable,
    inspect_nuitka_runtime,
)
from sjtuclaw.application.autostart_operation_journal import (
    AutostartOperationJournal,
)
from sjtuclaw.application.autostart_service import (
    AUTOSTART_ARGUMENT,
    AutostartService,
)


def diagnose_production_autostart_eligibility(
    executable: Path | None = None,
) -> AutostartEligibilityResult:
    """Return one fixed reason without retaining paths or exception details."""

    candidate = Path(sys.executable) if executable is None else executable
    runtime = inspect_nuitka_runtime(globals().get("__compiled__"), candidate)
    if not runtime.supported:
        return runtime
    command_length = len(f'"{candidate}" {AUTOSTART_ARGUMENT}')
    return inspect_autostart_executable(
        candidate,
        runtime,
        command_length=command_length,
        maximum_command_length=MAX_AUTOSTART_COMMAND_LENGTH,
    )


def _is_supported_nuitka_standalone_runtime() -> bool:
    """Accept Nuitka standalone while keeping source and onefile fail-closed."""

    return diagnose_production_autostart_eligibility().supported


def create_production_autostart_service(
    *,
    operation_journal: AutostartOperationJournal | None = None,
) -> AutostartService:
    """Construct without reading or writing the Windows registry."""

    if sys.platform != "win32":
        return AutostartService(
            None,
            lambda: Path(sys.executable),
            platform_supported=False,
            packaged_runtime_probe=lambda: False,
            operation_journal=operation_journal,
        )
    from sjtuclaw.infrastructure.autostart.windows_run_key import (
        WindowsRunKeyAutostartBackend,
    )

    return AutostartService(
        WindowsRunKeyAutostartBackend(),
        lambda: Path(sys.executable),
        platform_supported=True,
        eligibility_probe=lambda executable: (
            diagnose_production_autostart_eligibility(executable)
        ),
        operation_journal=operation_journal,
    )
