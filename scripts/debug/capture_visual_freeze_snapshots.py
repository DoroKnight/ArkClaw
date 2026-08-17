import os
import sys
from dataclasses import dataclass
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "windows"

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from arkclaw.application.pet.pet_production_actions import ProductionAction
from arkclaw.application.system.autostart_service import (
    AutostartSnapshot,
    AutostartStatus,
)
from arkclaw.presentation.command_descriptor_adapter import (
    CommandDescriptorSource,
    build_command_descriptors,
)
from arkclaw.presentation.frontend_presentation import ActionPaletteLayer
from arkclaw.presentation.qt.dashboard.dashboard_page import DashboardPage
from arkclaw.presentation.qt.dashboard.dashboard_window import DashboardWindow
from arkclaw.presentation.qt.dashboard.settings_dialog import SettingsDialog
from arkclaw.presentation.qt.theme.design_tokens import load_design_tokens
from arkclaw.presentation.qt.theme.qt_theme import QtTheme
from arkclaw.presentation.qt.ui.action_palette import (
    ActionPaletteHost,
    ActionPaletteWindowStrategy,
)


@dataclass
class _MockDescriptorSource(CommandDescriptorSource):
    pet_visible: bool = True
    pet_paused: bool = False
    pet_always_on_top: bool = True
    pet_closing: bool = False
    available_pet_actions: frozenset[ProductionAction] = frozenset(
        {
            ProductionAction.RELAX,
            ProductionAction.SIT,
            ProductionAction.SLEEP,
            ProductionAction.INTERACT,
            ProductionAction.SPECIAL,
            ProductionAction.MOVE_LEFT,
            ProductionAction.MOVE_RIGHT,
        }
    )
    autostart_snapshot: AutostartSnapshot = AutostartSnapshot.for_status(
        AutostartStatus.ENABLED
    )
    autostart_busy: bool = False


def capture_all_snapshots() -> None:
    output_dir = Path("docs/artifacts/stage10r")
    output_dir.mkdir(parents=True, exist_ok=True)

    app = QApplication.instance() or QApplication(sys.argv)
    tokens = load_design_tokens()

    # 1. Capture Dashboard Pages (Light & Dark)
    dash = DashboardWindow(tokens)
    dash.resize(1040, 680)
    dash.show()
    app.processEvents()

    for theme, theme_name in [
        (QtTheme.LIGHT, "light"),
        (QtTheme.DARK, "dark"),
    ]:
        dash.set_theme(theme)
        app.processEvents()

        # Home
        dash.select_page(DashboardPage.HOME)
        app.processEvents()
        pix_home = dash.grab()
        pix_home.save(str(output_dir / f"dashboard_home_{theme_name}.png"))

        # Chat / Work
        dash.select_page(DashboardPage.CHAT_WORK)
        app.processEvents()
        pix_chat = dash.grab()
        pix_chat.save(str(output_dir / f"dashboard_chat_{theme_name}.png"))

        # Character Animation
        dash.select_page(DashboardPage.CHARACTER_ANIMATION)
        app.processEvents()
        pix_char = dash.grab()
        pix_char.save(str(output_dir / f"dashboard_character_{theme_name}.png"))

        # Settings Dialog
        dialog = SettingsDialog(
            parent=dash,
            tokens=tokens,
            theme=theme,
        )
        dialog.show()
        app.processEvents()
        pix_settings = dialog.grab()
        pix_settings.save(
            str(output_dir / f"settings_dialog_{theme_name}.png")
        )
        dialog.close()
        app.processEvents()

    dash.close()
    app.processEvents()

    # 2. Capture Action Palette (Light & Dark, Root, Character & System Layers)
    source = _MockDescriptorSource()
    descriptors = build_command_descriptors(source)

    palette_host = ActionPaletteHost(
        strategy=ActionPaletteWindowStrategy.TOOL,
        theme=QtTheme.LIGHT,
    )
    palette_host.move(300, 200)

    layers = [
        ("root", ActionPaletteLayer.ROOT),
        ("character", ActionPaletteLayer.CHARACTER),
        ("system", ActionPaletteLayer.SYSTEM),
    ]

    for theme, theme_name in [
        (QtTheme.LIGHT, "light"),
        (QtTheme.DARK, "dark"),
    ]:
        palette_host.set_theme(theme)

        for layer_name, layer in layers:
            palette_host.render_palette(layer, descriptors)
            palette_host.show()
            app.processEvents()
            pix = palette_host.grab()
            pix.save(
                str(output_dir / f"palette_{layer_name}_{theme_name}.png")
            )

    palette_host.close()
    app.processEvents()
    print(f"All Stage 10R visual snapshots saved to {output_dir.resolve()}")


if __name__ == "__main__":
    capture_all_snapshots()
