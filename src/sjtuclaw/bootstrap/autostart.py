"""Production construction for the optional autostart service."""

from __future__ import annotations

import sys
from pathlib import Path

from sjtuclaw.application.autostart_service import AutostartService


def _is_supported_nuitka_standalone_runtime() -> bool:
    """Accept Nuitka standalone while keeping source and onefile fail-closed."""

    marker = globals().get("__compiled__")
    if marker is None or type(marker).__name__ != "__nuitka_version__":
        return False
    standalone = getattr(marker, "standalone", None)
    onefile = getattr(marker, "onefile", None)
    containing_dir = getattr(marker, "containing_dir", None)
    if (
        standalone is not True
        or onefile is not False
        or not isinstance(containing_dir, str)
    ):
        return False
    try:
        executable_parent = Path(sys.executable).resolve(strict=True).parent
        compiled_parent = Path(containing_dir).resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return False
    return compiled_parent == executable_parent


def create_production_autostart_service() -> AutostartService:
    """Construct without reading or writing the Windows registry."""

    if sys.platform != "win32":
        return AutostartService(
            None,
            lambda: Path(sys.executable),
            platform_supported=False,
            packaged_runtime_probe=lambda: False,
        )
    from sjtuclaw.infrastructure.autostart.windows_run_key import (
        WindowsRunKeyAutostartBackend,
    )

    return AutostartService(
        WindowsRunKeyAutostartBackend(),
        lambda: Path(sys.executable),
        platform_supported=True,
        packaged_runtime_probe=_is_supported_nuitka_standalone_runtime,
    )
