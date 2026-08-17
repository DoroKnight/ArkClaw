"""Shared production-action section for tray and pet context menus."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu

from arkclaw.application.pet.pet_production_actions import (
    ProductionAction,
    can_resume_autonomous,
)
from arkclaw.presentation.qt.theme.qt_theme import (
    QtTheme,
    build_menu_stylesheet,
)

__all__ = [
    "ARKCLAW_MENU_STYLE",
    "ProductionActionMenuSection",
    "build_menu_stylesheet",
    "prepare_arkclaw_menu",
]

# One token-generated menu language shared by the tray and pet context menus.
ARKCLAW_MENU_STYLE = build_menu_stylesheet(QtTheme.LIGHT)


def prepare_arkclaw_menu(
    menu: QMenu,
    *,
    object_name: str,
    theme: QtTheme | None = None,
) -> None:
    """Apply one compact native-desktop visual language to an ArkClaw menu."""

    menu.setObjectName(object_name)
    menu.setMinimumWidth(244)
    menu.setToolTipsVisible(True)
    menu.setStyleSheet(build_menu_stylesheet(theme or QtTheme.LIGHT))


class ProductionActionMenuSection:
    """Build and update one identical role-pack action section."""

    def __init__(
        self,
        menu: QMenu,
        *,
        request_action: Callable[[ProductionAction], object],
        resume_autonomous: Callable[[], object],
    ) -> None:
        self.role_pack_action = QAction("ACTIVE PET  ·  placeholder", menu)
        self.role_pack_action.setObjectName("arkclawRolePackHeader")
        self.role_pack_action.setEnabled(False)
        menu.addAction(self.role_pack_action)
        menu.addSeparator()
        self.action_items: dict[ProductionAction, QAction] = {}
        self._add_action(menu, ProductionAction.RELAX, "Relax", request_action)
        self.move_menu = menu.addMenu("Move")
        prepare_arkclaw_menu(
            self.move_menu,
            object_name="arkclawMoveActionMenu",
        )
        self._add_action(
            self.move_menu,
            ProductionAction.MOVE_LEFT,
            "Left",
            request_action,
        )
        self._add_action(
            self.move_menu,
            ProductionAction.MOVE_RIGHT,
            "Right",
            request_action,
        )
        for action, label in (
            (ProductionAction.SIT, "Sit"),
            (ProductionAction.SLEEP, "Sleep"),
            (ProductionAction.SPECIAL, "Special"),
            (ProductionAction.INTERACT, "Interact"),
        ):
            self._add_action(menu, action, label, request_action)
        self.resume_autonomous_action = QAction("Resume Autonomous", menu)
        self.resume_autonomous_action.setObjectName(
            "resumeAutonomousAction"
        )
        self.resume_autonomous_action.triggered.connect(
            lambda checked=False: resume_autonomous()
        )
        menu.addAction(self.resume_autonomous_action)

    def update(
        self,
        *,
        role_pack_id: str,
        available_actions: frozenset[ProductionAction],
        closing: bool,
    ) -> None:
        display_role = (
            "SCHWARZ / 黑"
            if role_pack_id == "schwarz-production"
            else role_pack_id
        )
        self.role_pack_action.setText(f"ACTIVE PET  ·  {display_role}")
        for production_action, menu_action in self.action_items.items():
            menu_action.setEnabled(
                not closing and production_action in available_actions
            )
        self.move_menu.setEnabled(
            not closing
            and any(
                action in available_actions
                for action in (
                    ProductionAction.MOVE_LEFT,
                    ProductionAction.MOVE_RIGHT,
                )
            )
        )
        self.resume_autonomous_action.setEnabled(
            can_resume_autonomous(
                closing=closing,
                available_actions=available_actions,
            )
        )

    def _add_action(
        self,
        menu: QMenu,
        action: ProductionAction,
        label: str,
        callback: Callable[[ProductionAction], object],
    ) -> None:
        item = QAction(label, menu)
        item.setObjectName(f"petAction_{action.value}")
        item.triggered.connect(
            lambda checked=False, selected=action: callback(selected)
        )
        menu.addAction(item)
        self.action_items[action] = item
