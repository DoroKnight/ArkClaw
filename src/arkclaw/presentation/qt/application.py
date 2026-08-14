"""Production Qt application entry point."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import NoReturn

from PySide6.QtWidgets import QApplication

from arkclaw.bootstrap.autostart import (
    create_production_autostart_service,
)
from arkclaw.bootstrap.qt_runtime import (
    ProductionQtRuntimeCompositionRoot,
)
from arkclaw.presentation.qt.autostart_controller import (
    AutostartUiController,
)
from arkclaw.presentation.qt.main_window import MainWindow
from arkclaw.presentation.qt.runtime_bridge import QtRuntimeBridge


def default_provider_metadata_path() -> Path:
    """Return the per-user non-sensitive Provider metadata path."""

    local_app_data = os.environ.get("LOCALAPPDATA")
    base = (
        Path(local_app_data)
        if local_app_data
        else Path.home() / "AppData" / "Local"
    )
    return base / "ArkClaw" / "provider_profiles.json"


def main(argv: list[str] | None = None) -> int:
    """Run the ordinary Qt shell without activating a cloud Provider."""

    app = QApplication(sys.argv if argv is None else argv)
    app.setApplicationName("ArkClaw")
    app.setOrganizationName("ArkClaw")
    bridge = QtRuntimeBridge(
        ProductionQtRuntimeCompositionRoot(
            default_provider_metadata_path()
        ),
        autostart_service_factory=create_production_autostart_service,
    )
    autostart_controller = AutostartUiController(bridge, bridge)
    window = MainWindow(
        bridge,
        autostart_controller=autostart_controller,
    )
    window.show()
    return app.exec()


def run() -> NoReturn:
    """Console-script compatible wrapper."""

    raise SystemExit(main())
