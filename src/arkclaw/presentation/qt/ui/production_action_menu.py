"""Shared production-action section for tray and pet context menus."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu

from arkclaw.application.pet.pet_production_actions import ProductionAction

ARKCLAW_MENU_STYLE = """
QMenu {
    background: #171A1B;
    color: #EAE9E4;
    border: 1px solid #3A4144;
    border-radius: 8px;
    padding: 7px;
    font-family: "Segoe UI";
    font-size: 13px;
}
QMenu::item {
    min-width: 210px;
    min-height: 28px;
    padding: 4px 30px 4px 12px;
    margin: 1px 0;
    border-radius: 5px;
}
QMenu::item:selected {
    background: #B9623E;
    color: #FFFFFF;
}
QMenu::item:disabled {
    color: #747C80;
}
QMenu::separator {
    height: 1px;
    background: #303639;
    margin: 7px 8px;
}
QMenu::indicator {
    width: 14px;
    height: 14px;
    left: 10px;
}
QMenu::indicator:checked {
    background: #C9774D;
    border: 2px solid #F1F0EB;
    border-radius: 3px;
}
QMenu::right-arrow {
    width: 6px;
    height: 10px;
    margin-right: 8px;
}
"""


def prepare_arkclaw_menu(menu: QMenu, *, object_name: str) -> None:
    """Apply one compact native-desktop visual language to an ArkClaw menu."""

    menu.setObjectName(object_name)
    menu.setMinimumWidth(244)
    menu.setToolTipsVisible(True)
    menu.setStyleSheet(ARKCLAW_MENU_STYLE)


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
            not closing and ProductionAction.RELAX in available_actions
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
