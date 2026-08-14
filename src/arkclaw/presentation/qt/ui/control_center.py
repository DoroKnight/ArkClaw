"""ArkClaw v1 desktop companion control-center widgets."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from PySide6.QtCore import QPointF, QSignalBlocker, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QIcon,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from arkclaw.application.system.autostart_operation_journal import (
    AutostartOperationOrigin,
)
from arkclaw.application.system.autostart_service import AutostartSnapshot
from arkclaw.presentation.qt.ui.autostart_controller import (
    AutostartUiController,
)

CONTROL_CENTER_STYLE: Final = """
QWidget {
    background: #151819;
    color: #F1F0EB;
    font-family: "Segoe UI";
    font-size: 14px;
}
QMainWindow, QWidget#controlCenterRoot, QStackedWidget#pageStack {
    background: #151819;
}
QLabel {
    background: transparent;
}
QFrame#sidebar {
    background: #111415;
    border-right: 1px solid #303639;
}
QLabel#brandMark {
    color: #F1F0EB;
    font-size: 17px;
    font-weight: 650;
    letter-spacing: 1px;
}
QLabel#brandCaption, QLabel[muted="true"] {
    color: #747C80;
    font-size: 12px;
}
QPushButton[nav="true"] {
    background: transparent;
    border: 0;
    border-left: 3px solid transparent;
    border-radius: 6px;
    color: #AAB0B1;
    min-height: 38px;
    padding: 0 12px;
    text-align: left;
}
QPushButton[nav="true"]:hover {
    background: #1D2123;
    color: #F1F0EB;
}
QPushButton[nav="true"]:checked {
    background: #252A2D;
    border-left-color: #C9774D;
    color: #F1F0EB;
    font-weight: 600;
}
QPushButton[nav="true"]:focus {
    border: 2px solid #D2A25C;
    border-left: 3px solid #D2A25C;
}
QLabel#pageTitle {
    color: #F1F0EB;
    font-size: 22px;
    font-weight: 600;
}
QLabel#pageDescription {
    color: #AAB0B1;
    font-size: 13px;
}
QLabel#sectionTitle {
    color: #F1F0EB;
    font-size: 16px;
    font-weight: 600;
}
QFrame[panel="true"] {
    background: #1D2123;
    border: 1px solid #303639;
    border-radius: 10px;
}
QFrame#previewStage {
    background: #D8D9D5;
    border: 1px solid #495055;
    border-radius: 10px;
}
QLabel#previewMonogram {
    background: transparent;
    color: #252A2D;
    font-family: "Microsoft YaHei UI";
    font-size: 78px;
    font-weight: 300;
}
QLabel#previewName {
    background: transparent;
    color: #495055;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 3px;
}
QLabel#previewNotice {
    background: transparent;
    color: #747C80;
    font-size: 12px;
}
QLabel[badge="true"] {
    border: 1px solid #495055;
    border-radius: 9px;
    color: #AAB0B1;
    font-size: 12px;
    font-weight: 600;
    padding: 2px 8px;
}
QLabel[badgeVariant="current"] {
    background: #493B29;
    border-color: #D2A25C;
    color: #F0CA8D;
}
QLabel[badgeVariant="ready"] {
    background: #253126;
    border-color: #72916E;
    color: #A9C5A6;
}
QLabel[badgeVariant="paused"] {
    background: #353023;
    border-color: #D19A4A;
    color: #E8C178;
}
QLabel[badgeVariant="unavailable"], QLabel[badgeVariant="neutral"] {
    background: #252A2D;
    border-color: #495055;
    color: #AAB0B1;
}
QPushButton {
    background: #252A2D;
    border: 1px solid #495055;
    border-radius: 6px;
    color: #F1F0EB;
    min-height: 34px;
    padding: 0 14px;
}
QPushButton:hover {
    background: #303639;
    border-color: #60686D;
}
QPushButton:pressed {
    background: #1D2123;
}
QPushButton:focus, QToolButton:focus, QCheckBox:focus, QComboBox:focus,
QLineEdit:focus, QPlainTextEdit:focus, QListWidget:focus {
    border: 2px solid #D2A25C;
}
QPushButton[variant="primary"] {
    background: #C9774D;
    border-color: #C9774D;
    color: #151819;
    font-weight: 600;
    min-height: 38px;
}
QPushButton[variant="primary"]:hover {
    background: #D4865C;
    border-color: #D4865C;
}
QPushButton[variant="primary"]:pressed {
    background: #AC613F;
}
QPushButton[variant="quiet"] {
    background: transparent;
    border-color: transparent;
    color: #AAB0B1;
}
QPushButton:disabled, QToolButton:disabled {
    background: #1B1F21;
    border-color: #303639;
    color: #747C80;
}
QFrame#capabilityNotice {
    background: #202527;
    border: 1px solid #495055;
    border-radius: 8px;
}
QLabel#capabilityTitle {
    color: #F1F0EB;
    font-weight: 600;
}
QLabel#capabilityBody {
    color: #AAB0B1;
    font-size: 12px;
}
QFrame#characterCard, QPushButton#animationItem {
    background: #1D2123;
    border: 1px solid #303639;
    border-radius: 8px;
}
QFrame#characterCard[selected="true"], QPushButton#animationItem:checked {
    background: #252A2D;
    border: 2px solid #D2A25C;
}
QPushButton#animationItem {
    min-height: 70px;
    padding: 10px 14px;
    text-align: left;
}
QPushButton#animationItem:hover {
    background: #252A2D;
}
QFrame#inspector {
    background: #1D2123;
    border-left: 1px solid #303639;
}
QLabel#inspectorTitle {
    font-size: 20px;
    font-weight: 600;
}
QLabel#inspectorSubtitle {
    color: #AAB0B1;
}
QFrame#settingRow {
    background: transparent;
    border-bottom: 1px solid #303639;
}
QLabel#settingLabel {
    font-weight: 600;
}
QLabel#settingDescription {
    color: #AAB0B1;
    font-size: 12px;
}
QCheckBox {
    spacing: 9px;
}
QCheckBox::indicator {
    background: #111415;
    border: 1px solid #495055;
    border-radius: 4px;
    height: 16px;
    width: 16px;
}
QCheckBox::indicator:checked {
    background: #C9774D;
    border-color: #D4865C;
}
QCheckBox::indicator:disabled {
    background: #1B1F21;
    border-color: #303639;
}
QComboBox, QLineEdit, QPlainTextEdit, QListWidget {
    background: #111415;
    border: 1px solid #495055;
    border-radius: 6px;
    color: #F1F0EB;
    selection-background-color: #C9774D;
    selection-color: #151819;
}
QComboBox, QLineEdit {
    min-height: 34px;
    padding: 0 10px;
}
QPlainTextEdit, QListWidget {
    padding: 8px;
}
QTabWidget::pane {
    border: 1px solid #303639;
    border-radius: 8px;
    background: #1D2123;
    top: -1px;
}
QTabBar::tab {
    background: transparent;
    color: #AAB0B1;
    padding: 9px 14px;
    border-bottom: 2px solid transparent;
}
QTabBar::tab:selected {
    color: #F1F0EB;
    border-bottom-color: #C9774D;
}
QScrollArea {
    border: 0;
    background: transparent;
}
QScrollBar:vertical {
    background: #151819;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #495055;
    border-radius: 5px;
    min-height: 24px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QToolButton#detailsButton, QToolButton#closeInspectorButton {
    background: #252A2D;
    border: 1px solid #495055;
    border-radius: 6px;
    color: #F1F0EB;
    min-height: 32px;
    padding: 0 10px;
}
"""


class CapabilityState(StrEnum):
    AVAILABLE = "Available"
    SPECIFIED = "Specified"
    PROPOSED = "Proposed"
    UNKNOWN = "Unknown"


class NavigationIcon(StrEnum):
    HOME = "home"
    PETS = "pets"
    ANIMATIONS = "animations"
    INTERACTION = "interaction"
    APPEARANCE = "appearance"
    SETTINGS = "settings"


@dataclass(frozen=True, slots=True)
class PetPresentationSnapshot:
    visible: bool = False
    paused: bool = False
    always_on_top: bool = True
    action: str = "Relaxing"
    attached: bool = False


@dataclass(frozen=True, slots=True)
class ActionSummary:
    name: str
    source_animation: str
    category: str
    trigger: str


SCHWARZ_ACTIONS: Final = (
    ActionSummary("Relax", "Relax", "Idle", "Autonomous / Manual"),
    ActionSummary("Move Left", "Move", "Movement", "Autonomous / Manual"),
    ActionSummary("Move Right", "Move", "Movement", "Autonomous / Manual"),
    ActionSummary("Sit", "Sit", "Idle", "Autonomous / Manual"),
    ActionSummary("Sleep", "Sleep", "Idle", "Autonomous / Manual"),
    ActionSummary("Special", "Special", "Expression", "Autonomous / Manual"),
    ActionSummary("Interact", "Interact", "Interaction", "User / Manual"),
)


def _navigation_icon(kind: NavigationIcon) -> QIcon:
    pixmap = QPixmap(20, 20)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(
        QPen(
            QColor("#AAB0B1"),
            1.6,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
    )
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if kind is NavigationIcon.HOME:
        painter.drawPolyline(
            QPolygonF(
                (QPointF(3, 9), QPointF(10, 3), QPointF(17, 9))
            )
        )
        painter.drawRect(5, 8, 10, 9)
        painter.drawLine(9, 17, 9, 12)
    elif kind is NavigationIcon.PETS:
        painter.drawPolyline(
            QPolygonF(
                (
                    QPointF(5, 7),
                    QPointF(5, 3),
                    QPointF(8, 6),
                    QPointF(12, 6),
                    QPointF(15, 3),
                    QPointF(15, 7),
                )
            )
        )
        painter.drawEllipse(5, 6, 10, 10)
        painter.drawPoint(8, 10)
        painter.drawPoint(12, 10)
    elif kind is NavigationIcon.ANIMATIONS:
        painter.drawPolygon(
            QPolygonF(
                (QPointF(6, 4), QPointF(16, 10), QPointF(6, 16))
            )
        )
    elif kind is NavigationIcon.INTERACTION:
        painter.drawLine(4, 7, 16, 7)
        painter.drawLine(4, 7, 7, 4)
        painter.drawLine(4, 7, 7, 10)
        painter.drawLine(4, 13, 16, 13)
        painter.drawLine(16, 13, 13, 10)
        painter.drawLine(16, 13, 13, 16)
    elif kind is NavigationIcon.APPEARANCE:
        painter.drawRoundedRect(3, 4, 14, 10, 1.5, 1.5)
        painter.drawLine(10, 14, 10, 17)
        painter.drawLine(7, 17, 13, 17)
    else:
        painter.drawEllipse(6, 6, 8, 8)
        painter.drawEllipse(9, 9, 2, 2)
        for x1, y1, x2, y2 in (
            (10, 2, 10, 5),
            (10, 15, 10, 18),
            (2, 10, 5, 10),
            (15, 10, 18, 10),
            (4, 4, 6, 6),
            (14, 14, 16, 16),
            (16, 4, 14, 6),
            (6, 14, 4, 16),
        ):
            painter.drawLine(x1, y1, x2, y2)
    painter.end()
    return QIcon(pixmap)


def _clear_layout(layout: QLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item is None:
            continue
        widget = item.widget()
        if widget is not None:
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
            continue
        child_layout = item.layout()
        if child_layout is not None:
            _clear_layout(child_layout)


def _page_header(title: str, description: str) -> QWidget:
    header = QWidget()
    layout = QVBoxLayout(header)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    title_label = QLabel(title)
    title_label.setObjectName("pageTitle")
    description_label = QLabel(description)
    description_label.setObjectName("pageDescription")
    description_label.setWordWrap(True)
    layout.addWidget(title_label)
    layout.addWidget(description_label)
    return header


def _section_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("sectionTitle")
    return label


def _scroll_page(content: QWidget) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setWidget(content)
    return scroll


class StatusBadge(QLabel):
    def __init__(
        self,
        text: str,
        variant: str = "neutral",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        self.setProperty("badge", True)
        self.setProperty("badgeVariant", variant)
        self.setSizePolicy(
            QSizePolicy.Policy.Maximum,
            QSizePolicy.Policy.Fixed,
        )

    def set_status(self, text: str, variant: str) -> None:
        self.setText(text)
        self.setProperty("badgeVariant", variant)
        style = self.style()
        style.unpolish(self)
        style.polish(self)


class CapabilityNotice(QFrame):
    def __init__(
        self,
        state: CapabilityState,
        title: str,
        message: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("capabilityNotice")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(12)
        state_badge = StatusBadge(state.value, "unavailable")
        text_column = QVBoxLayout()
        text_column.setSpacing(2)
        title_label = QLabel(title)
        title_label.setObjectName("capabilityTitle")
        body_label = QLabel(message)
        body_label.setObjectName("capabilityBody")
        body_label.setWordWrap(True)
        text_column.addWidget(title_label)
        text_column.addWidget(body_label)
        layout.addWidget(state_badge, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(text_column, 1)


class PreviewPanel(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("previewStage")
        self.setMinimumHeight(280)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 18)
        layout.addStretch(1)
        monogram = QLabel("黑")
        monogram.setObjectName("previewMonogram")
        monogram.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name = QLabel("SCHWARZ")
        name.setObjectName("previewName")
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        notice = QLabel("Static preview · character artwork not embedded")
        notice.setObjectName("previewNotice")
        notice.setAlignment(Qt.AlignmentFlag.AlignCenter)
        notice.setWordWrap(True)
        layout.addWidget(monogram)
        layout.addWidget(name)
        layout.addSpacing(18)
        layout.addWidget(notice)
        layout.addStretch(1)


class NavigationItem(QPushButton):
    def __init__(
        self,
        key: str,
        icon: NavigationIcon,
        label: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.key = key
        self.label = label
        self.setIcon(_navigation_icon(icon))
        self.setCheckable(True)
        self.setProperty("nav", True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(label)
        self.set_full_text()

    def set_full_text(self) -> None:
        self.setText(self.label)
        self.setToolTip("")
        self.setStyleSheet("")

    def set_compact_text(self) -> None:
        self.setText("")
        self.setToolTip(self.label)
        self.setStyleSheet("text-align: center; padding: 0;")


class AppSidebar(QFrame):
    page_requested = Signal(str)

    _ITEMS: Final = (
        ("home", NavigationIcon.HOME, "Home"),
        ("pets", NavigationIcon.PETS, "My Pets"),
        ("animations", NavigationIcon.ANIMATIONS, "Animations"),
        ("interaction", NavigationIcon.INTERACTION, "Interaction"),
        ("appearance", NavigationIcon.APPEARANCE, "Appearance"),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(208)
        self._compact = False
        self._buttons: dict[str, NavigationItem] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 18, 12, 14)
        layout.setSpacing(6)

        brand = QWidget()
        brand_layout = QVBoxLayout(brand)
        brand_layout.setContentsMargins(9, 0, 8, 18)
        brand_layout.setSpacing(0)
        self.brand_mark = QLabel("ARKCLAW")
        self.brand_mark.setObjectName("brandMark")
        self.brand_caption = QLabel("DESKTOP COMPANION")
        self.brand_caption.setObjectName("brandCaption")
        brand_layout.addWidget(self.brand_mark)
        brand_layout.addWidget(self.brand_caption)
        layout.addWidget(brand)

        for key, glyph, label in self._ITEMS:
            self._add_item(layout, key, glyph, label)
        layout.addStretch(1)

        self.status_footer = QFrame()
        self.status_footer.setProperty("panel", True)
        footer_layout = QVBoxLayout(self.status_footer)
        footer_layout.setContentsMargins(12, 10, 12, 10)
        footer_layout.setSpacing(3)
        self.pet_status = QLabel("Desktop pet · connecting")
        self.pet_status.setWordWrap(True)
        self.pet_status.setProperty("muted", True)
        self.runtime_status = QLabel("Runtime · starting")
        self.runtime_status.setWordWrap(True)
        self.runtime_status.setProperty("muted", True)
        footer_layout.addWidget(self.pet_status)
        footer_layout.addWidget(self.runtime_status)
        layout.addWidget(self.status_footer)

        settings = self._add_item(
            layout,
            "settings",
            NavigationIcon.SETTINGS,
            "Settings",
        )
        settings.setObjectName("settingsNavigationButton")
        self.set_current("home")

    def _add_item(
        self,
        layout: QVBoxLayout,
        key: str,
        icon: NavigationIcon,
        label: str,
    ) -> NavigationItem:
        button = NavigationItem(key, icon, label)
        button.setObjectName(f"nav{key.title()}Button")
        button.clicked.connect(
            lambda checked=False, page=key: self.page_requested.emit(page)
        )
        self._group.addButton(button)
        self._buttons[key] = button
        layout.addWidget(button)
        return button

    def set_current(self, key: str) -> None:
        button = self._buttons.get(key)
        if button is not None:
            button.setChecked(True)

    def set_compact(self, compact: bool) -> None:
        if compact == self._compact:
            return
        self._compact = compact
        self.setFixedWidth(72 if compact else 208)
        self.brand_caption.setVisible(not compact)
        self.brand_mark.setText("AC" if compact else "ARKCLAW")
        self.brand_mark.setAlignment(
            Qt.AlignmentFlag.AlignCenter
            if compact
            else Qt.AlignmentFlag.AlignLeft
        )
        self.status_footer.setVisible(not compact)
        for button in self._buttons.values():
            if compact:
                button.set_compact_text()
            else:
                button.set_full_text()

    def update_status(
        self,
        snapshot: PetPresentationSnapshot,
        runtime_ready: bool,
    ) -> None:
        if not snapshot.attached:
            self.pet_status.setText("Desktop pet · unavailable")
        elif not snapshot.visible:
            self.pet_status.setText("Schwarz · hidden")
        elif snapshot.paused:
            self.pet_status.setText("Schwarz · paused")
        else:
            self.pet_status.setText(f"Schwarz · {snapshot.action}")
        self.runtime_status.setText(
            "Runtime · ready" if runtime_ready else "Runtime · starting"
        )


class HomePage(QWidget):
    interact_requested = Signal()
    change_action_requested = Signal()
    pause_requested = Signal()
    visibility_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._snapshot = PetPresentationSnapshot()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 28)
        layout.setSpacing(20)
        layout.addWidget(
            _page_header(
                "Home",
                "See the current companion and control the desktop pet.",
            )
        )

        layout.addWidget(_section_title("Current Pet"))
        layout.addWidget(PreviewPanel(), 1)

        identity = QHBoxLayout()
        identity.setSpacing(10)
        name_column = QVBoxLayout()
        name_column.setSpacing(2)
        name = QLabel("Schwarz / 黑")
        name.setObjectName("inspectorTitle")
        self.action_label = QLabel("Connecting to desktop pet…")
        self.action_label.setObjectName("inspectorSubtitle")
        name_column.addWidget(name)
        name_column.addWidget(self.action_label)
        self.lifecycle_badge = StatusBadge("Unavailable", "unavailable")
        self.autonomy_badge = StatusBadge("Autonomous", "neutral")
        identity.addLayout(name_column, 1)
        identity.addWidget(self.lifecycle_badge)
        identity.addWidget(self.autonomy_badge)
        layout.addLayout(identity)

        primary_row = QHBoxLayout()
        primary_row.setSpacing(10)
        self.interact_button = QPushButton("Interact")
        self.interact_button.setObjectName("interactButton")
        self.interact_button.setProperty("variant", "primary")
        self.interact_button.setEnabled(False)
        self.interact_button.setToolTip(
            "Play Schwarz's Interact action on the desktop."
        )
        self.change_action_button = QPushButton("Change Action")
        self.change_action_button.setObjectName("changeActionButton")
        primary_row.addWidget(self.interact_button)
        primary_row.addWidget(self.change_action_button)
        primary_row.addStretch(1)
        layout.addLayout(primary_row)

        controls = QFrame()
        controls.setProperty("panel", True)
        control_layout = QHBoxLayout(controls)
        control_layout.setContentsMargins(14, 10, 14, 10)
        control_layout.setSpacing(10)
        control_label = QLabel("Runtime controls")
        control_label.setObjectName("settingLabel")
        self.pause_button = QPushButton("Pause")
        self.pause_button.setObjectName("pausePetButton")
        self.visibility_button = QPushButton("Hide")
        self.visibility_button.setObjectName("togglePetVisibilityButton")
        control_layout.addWidget(control_label)
        control_layout.addStretch(1)
        control_layout.addWidget(self.pause_button)
        control_layout.addWidget(self.visibility_button)
        layout.addWidget(controls)

        self.interact_button.clicked.connect(self.interact_requested)
        self.change_action_button.clicked.connect(
            self.change_action_requested
        )
        self.pause_button.clicked.connect(self.pause_requested)
        self.visibility_button.clicked.connect(self.visibility_requested)
        self.update_pet(PetPresentationSnapshot())

    def update_pet(self, snapshot: PetPresentationSnapshot) -> None:
        self._snapshot = snapshot
        enabled = snapshot.attached
        self.interact_button.setEnabled(enabled and snapshot.visible)
        self.pause_button.setEnabled(enabled)
        self.visibility_button.setEnabled(enabled)
        self.pause_button.setText("Resume" if snapshot.paused else "Pause")
        self.visibility_button.setText("Show" if not snapshot.visible else "Hide")
        if not enabled:
            self.action_label.setText("Desktop pet controls are unavailable.")
            self.lifecycle_badge.set_status("Unavailable", "unavailable")
        elif not snapshot.visible:
            self.action_label.setText(f"{snapshot.action} · hidden from desktop")
            self.lifecycle_badge.set_status("Hidden", "neutral")
        elif snapshot.paused:
            self.action_label.setText(f"{snapshot.action} · autonomy paused")
            self.lifecycle_badge.set_status("Paused", "paused")
        else:
            self.action_label.setText(f"{snapshot.action} · autonomous")
            self.lifecycle_badge.set_status("Ready", "ready")


class CharacterCard(QFrame):
    selected = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("characterCard")
        self.setProperty("selected", True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Schwarz character card")
        self.setFixedWidth(280)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        preview = PreviewPanel()
        preview.setMinimumHeight(190)
        layout.addWidget(preview)
        title_row = QHBoxLayout()
        title = QLabel("Schwarz / 黑")
        title.setObjectName("sectionTitle")
        current = StatusBadge("Current Pet", "current")
        title_row.addWidget(title)
        title_row.addStretch(1)
        title_row.addWidget(current)
        layout.addLayout(title_row)
        meta = QLabel("Spine 3.8 · resource contract specified")
        meta.setProperty("muted", True)
        layout.addWidget(meta)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() is Qt.MouseButton.LeftButton:
            self.selected.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.selected.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class MyPetsPage(QWidget):
    character_selected = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 28)
        layout.setSpacing(20)
        layout.addWidget(
            _page_header(
                "My Pets",
                "Select an installed companion and inspect resource health.",
            )
        )
        layout.addWidget(_section_title("Installed characters"))
        card_row = QHBoxLayout()
        self.schwarz_card = CharacterCard()
        self.schwarz_card.selected.connect(self.character_selected)
        card_row.addWidget(self.schwarz_card)
        card_row.addStretch(1)
        layout.addLayout(card_row)
        layout.addWidget(
            CapabilityNotice(
                CapabilityState.UNKNOWN,
                "More characters",
                "Character package support is not available in this build.",
            )
        )
        layout.addStretch(1)


class AnimationsPage(QWidget):
    action_selected = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 28)
        layout.setSpacing(18)
        layout.addWidget(
            _page_header(
                "Animations",
                "Browse semantic actions without exposing renderer internals.",
            )
        )
        layout.addWidget(
            CapabilityNotice(
                CapabilityState.AVAILABLE,
                "Schwarz action catalog",
                "Select an action, inspect its role, then play it on the "
                "current desktop companion.",
            )
        )
        action_group = QButtonGroup(self)
        action_group.setExclusive(True)
        for index, action in enumerate(SCHWARZ_ACTIONS):
            item = QPushButton(
                f"{action.name}\n"
                f"{action.category}  ·  {action.trigger}  ·  Duration from runtime"
            )
            item.setObjectName("animationItem")
            item.setCheckable(True)
            item.setAccessibleName(f"{action.name} action")
            item.clicked.connect(
                lambda checked=False, selected=action: (
                    self.action_selected.emit(selected)
                )
            )
            action_group.addButton(item)
            layout.addWidget(item)
            if index == 0:
                item.setChecked(True)
        layout.addStretch(1)


class InteractionPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 28)
        layout.setSpacing(20)
        layout.addWidget(
            _page_header(
                "Interaction",
                "Understand how direct input affects the desktop pet.",
            )
        )
        layout.addWidget(_section_title("Mouse interaction"))
        for title, description, state in (
            ("Left drag", "Move the pet across the desktop.", "Available"),
            ("Right click", "Open the desktop pet context menu.", "Available"),
            (
                "Left click",
                "Play Interact without entering drag below the system threshold.",
                "Available",
            ),
            ("Double click", "No product behavior is defined.", "Unknown"),
        ):
            layout.addWidget(
                SettingRow(
                    title,
                    description,
                    StatusBadge(
                        state,
                        "ready" if state == "Available" else "unavailable",
                    ),
                )
            )
        layout.addWidget(_section_title("Action Priority"))
        priority = QFrame()
        priority.setProperty("panel", True)
        priority_layout = QVBoxLayout(priority)
        priority_layout.setContentsMargins(16, 14, 16, 14)
        priority_layout.addWidget(
            QLabel("User interaction temporarily overrides autonomous behavior.")
        )
        detail = QLabel(
            "Dragging and mandatory recovery take priority over scheduled actions."
        )
        detail.setProperty("muted", True)
        detail.setWordWrap(True)
        priority_layout.addWidget(detail)
        layout.addWidget(priority)
        layout.addWidget(
            CapabilityNotice(
                CapabilityState.PROPOSED,
                "Behavior presets",
                "Quiet, Balanced, and Lively require a separate behavior contract.",
            )
        )
        layout.addStretch(1)


class SettingRow(QFrame):
    def __init__(
        self,
        title: str,
        description: str,
        control: QWidget,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("settingRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 12, 0, 14)
        layout.setSpacing(16)
        text = QVBoxLayout()
        text.setSpacing(3)
        title_label = QLabel(title)
        title_label.setObjectName("settingLabel")
        description_label = QLabel(description)
        description_label.setObjectName("settingDescription")
        description_label.setWordWrap(True)
        text.addWidget(title_label)
        text.addWidget(description_label)
        layout.addLayout(text, 1)
        layout.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)


class AppearancePage(QWidget):
    visibility_changed = Signal(bool)
    always_on_top_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 26, 28, 28)
        layout.setSpacing(18)
        layout.addWidget(
            _page_header(
                "Appearance",
                "Control how the companion occupies the Windows desktop.",
            )
        )
        layout.addWidget(_section_title("Visibility"))
        self.visibility_toggle = QCheckBox("Shown")
        self.visibility_toggle.setObjectName("appearanceVisibilityToggle")
        self.always_on_top_toggle = QCheckBox("Enabled")
        self.always_on_top_toggle.setObjectName("alwaysOnTopToggle")
        layout.addWidget(
            SettingRow(
                "Show on Desktop",
                "Hide the pet window without stopping the runtime.",
                self.visibility_toggle,
            )
        )
        layout.addWidget(
            SettingRow(
                "Always on Top",
                "Keep the desktop pet above ordinary windows.",
                self.always_on_top_toggle,
            )
        )
        layout.addWidget(_section_title("Size & transparency"))
        layout.addWidget(
            CapabilityNotice(
                CapabilityState.SPECIFIED,
                "Scale and transparency",
                "The UI contract is defined, but runtime ranges and persistence "
                "are not available in this build.",
            )
        )
        layout.addWidget(_section_title("Position"))
        layout.addWidget(
            CapabilityNotice(
                CapabilityState.SPECIFIED,
                "Position recovery",
                "Monitor, anchor, and return-to-visible-area commands require an "
                "application-layer contract.",
            )
        )
        layout.addWidget(_section_title("Rendering"))
        layout.addWidget(
            CapabilityNotice(
                CapabilityState.UNKNOWN,
                "Rendering options",
                "No quality levels or selectable renderer backends are defined.",
            )
        )
        layout.addStretch(1)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(_scroll_page(content))
        self.visibility_toggle.toggled.connect(self.visibility_changed)
        self.always_on_top_toggle.toggled.connect(
            self.always_on_top_changed
        )

    def update_pet(self, snapshot: PetPresentationSnapshot) -> None:
        for checkbox, checked in (
            (self.visibility_toggle, snapshot.visible),
            (self.always_on_top_toggle, snapshot.always_on_top),
        ):
            blocker = QSignalBlocker(checkbox)
            checkbox.setChecked(checked)
            checkbox.setEnabled(snapshot.attached)
            del blocker


class SettingsPage(QWidget):
    open_provider_settings_requested = Signal()
    open_appearance_requested = Signal()

    def __init__(
        self,
        autostart_controller: AutostartUiController | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._autostart_controller = autostart_controller
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 28)
        layout.setSpacing(18)
        layout.addWidget(
            _page_header(
                "Settings",
                "Application, intelligence, and diagnostic configuration.",
            )
        )
        self.tabs = QTabWidget()
        self.tabs.setObjectName("settingsTabs")
        self.tabs.addTab(self._general_tab(), "General")
        self.tabs.addTab(self._performance_tab(), "Performance")
        self.tabs.addTab(self._system_tab(), "System")
        self.tabs.addTab(self._intelligence_tab(), "Intelligence")
        self.tabs.addTab(self._about_tab(), "About")
        layout.addWidget(self.tabs, 1)
        if autostart_controller is not None:
            autostart_controller.state_changed.connect(
                self._on_autostart_changed
            )
            autostart_controller.operation_failed.connect(
                self._on_autostart_failed
            )
        self._refresh_autostart()

    def _tab_layout(self) -> tuple[QWidget, QVBoxLayout]:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        return widget, layout

    def _general_tab(self) -> QWidget:
        widget, layout = self._tab_layout()
        self.autostart_toggle = QCheckBox("Enabled")
        self.autostart_toggle.setObjectName("controlCenterAutostartToggle")
        self.autostart_toggle.toggled.connect(self._set_autostart)
        layout.addWidget(
            SettingRow(
                "Launch with Windows",
                "Start the companion when the current Windows user signs in.",
                self.autostart_toggle,
            )
        )
        self.autostart_message = QLabel("Autostart status is unavailable.")
        self.autostart_message.setObjectName("settingDescription")
        self.autostart_message.setWordWrap(True)
        layout.addWidget(self.autostart_message)
        layout.addWidget(
            CapabilityNotice(
                CapabilityState.UNKNOWN,
                "Close behavior, language, and updates",
                "These product contracts are not defined in this build.",
            )
        )
        layout.addStretch(1)
        return widget

    def _performance_tab(self) -> QWidget:
        widget, layout = self._tab_layout()
        reduced_motion = QComboBox()
        reduced_motion.addItem("Follow Windows")
        reduced_motion.setEnabled(False)
        layout.addWidget(
            SettingRow(
                "Reduced UI Motion",
                "The first implementation follows the Windows preference.",
                reduced_motion,
            )
        )
        layout.addWidget(
            CapabilityNotice(
                CapabilityState.PROPOSED,
                "Performance controls",
                "FPS limits and animation quality are not backed by runtime "
                "capabilities yet.",
            )
        )
        layout.addWidget(
            CapabilityNotice(
                CapabilityState.UNKNOWN,
                "Rendering mode",
                "No user-selectable rendering backend is defined.",
            )
        )
        layout.addStretch(1)
        return widget

    def _system_tab(self) -> QWidget:
        widget, layout = self._tab_layout()
        tray_badge = StatusBadge("Available", "ready")
        layout.addWidget(
            SettingRow(
                "System Tray",
                "The tray keeps the companion controllable in the background.",
                tray_badge,
            )
        )
        appearance_button = QPushButton("Open Appearance")
        appearance_button.clicked.connect(self.open_appearance_requested)
        layout.addWidget(
            SettingRow(
                "Always on Top",
                "This setting has a single source of truth in Appearance.",
                appearance_button,
            )
        )
        layout.addWidget(
            CapabilityNotice(
                CapabilityState.UNKNOWN,
                "Notifications",
                "Notification categories and delivery rules are not defined.",
            )
        )
        layout.addStretch(1)
        return widget

    def _intelligence_tab(self) -> QWidget:
        widget, layout = self._tab_layout()
        self.runtime_label = QLabel("Runtime: starting")
        self.runtime_label.setObjectName("runtimeStateLabel")
        self.profile_label = QLabel("Profile: inactive")
        self.profile_label.setObjectName("activeProfileLabel")
        self.settings_button = QPushButton("Manage Provider Profiles")
        self.settings_button.setObjectName("openProviderSettingsButton")
        self.settings_button.clicked.connect(
            self.open_provider_settings_requested
        )
        status_row = QHBoxLayout()
        status_row.addWidget(self.runtime_label)
        status_row.addWidget(self.profile_label)
        status_row.addStretch(1)
        status_row.addWidget(self.settings_button)
        layout.addLayout(status_row)

        layout.addWidget(_section_title("Agent Console"))
        help_label = QLabel(
            "The console is retained as an advanced tool. It is not a primary "
            "navigation destination."
        )
        help_label.setProperty("muted", True)
        help_label.setWordWrap(True)
        layout.addWidget(help_label)
        self.conversation_view = QPlainTextEdit()
        self.conversation_view.setObjectName("conversationView")
        self.conversation_view.setReadOnly(True)
        self.conversation_view.setMinimumHeight(170)
        layout.addWidget(self.conversation_view, 1)
        command_row = QHBoxLayout()
        self.input_edit = QLineEdit()
        self.input_edit.setObjectName("messageInput")
        self.input_edit.setPlaceholderText("Message the active provider")
        self.send_button = QPushButton("Send")
        self.send_button.setObjectName("sendMessageButton")
        self.send_button.setProperty("variant", "primary")
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("cancelTurnButton")
        command_row.addWidget(self.input_edit, 1)
        command_row.addWidget(self.send_button)
        command_row.addWidget(self.cancel_button)
        layout.addLayout(command_row)
        self.error_label = QLabel("")
        self.error_label.setObjectName("safeErrorLabel")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)
        return widget

    def _about_tab(self) -> QWidget:
        widget, layout = self._tab_layout()
        layout.addWidget(_section_title("ArkClaw"))
        description = QLabel(
            "Desktop Companion Control Center\n"
            "Build: development · UI specification v1"
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        layout.addWidget(
            CapabilityNotice(
                CapabilityState.SPECIFIED,
                "Safe diagnostics",
                "Diagnostics must exclude credentials, private content, and "
                "unnecessary absolute asset paths.",
            )
        )
        layout.addWidget(
            CapabilityNotice(
                CapabilityState.UNKNOWN,
                "Character artwork license",
                "The static monogram is used because third-party preview artwork "
                "is not approved for product embedding.",
            )
        )
        layout.addStretch(1)
        return widget

    def _set_autostart(self, enabled: bool) -> None:
        controller = self._autostart_controller
        if controller is None:
            self._refresh_autostart()
            return
        controller.set_enabled(
            enabled,
            origin=AutostartOperationOrigin.SETTINGS_CHECKBOX,
        )
        self._refresh_autostart()

    def _refresh_autostart(self) -> None:
        controller = self._autostart_controller
        if controller is None:
            self.autostart_toggle.setEnabled(False)
            self.autostart_message.setText(
                "Autostart control is unavailable in this window."
            )
            return
        snapshot = controller.snapshot
        blocker = QSignalBlocker(self.autostart_toggle)
        self.autostart_toggle.setChecked(snapshot.enabled)
        self.autostart_toggle.setEnabled(controller.user_toggle_allowed)
        del blocker
        self.autostart_message.setText(
            controller.display_message
            or ("Enabled" if snapshot.enabled else "Disabled")
        )

    def _on_autostart_changed(self, value: object) -> None:
        if isinstance(value, AutostartSnapshot):
            self._refresh_autostart()

    def _on_autostart_failed(
        self,
        safe_code: str,
        safe_message: str,
    ) -> None:
        self.autostart_message.setText(f"{safe_code}: {safe_message}")
        self._refresh_autostart()


class InspectorPanel(QFrame):
    action_play_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("inspector")
        self.setFixedWidth(320)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)
        header = QHBoxLayout()
        label = QLabel("INSPECTOR")
        label.setProperty("muted", True)
        self.close_button = QToolButton()
        self.close_button.setObjectName("closeInspectorButton")
        self.close_button.setText("Close")
        self.close_button.setVisible(False)
        header.addWidget(label)
        header.addStretch(1)
        header.addWidget(self.close_button)
        root.addLayout(header)
        self.content = QVBoxLayout()
        self.content.setSpacing(12)
        root.addLayout(self.content, 1)
        self.show_home(PetPresentationSnapshot())

    def _base_content(self, title: str, subtitle: str) -> None:
        _clear_layout(self.content)
        preview = PreviewPanel()
        preview.setMinimumHeight(220)
        self.content.addWidget(preview)
        title_label = QLabel(title)
        title_label.setObjectName("inspectorTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("inspectorSubtitle")
        subtitle_label.setWordWrap(True)
        self.content.addWidget(title_label)
        self.content.addWidget(subtitle_label)

    def show_home(self, snapshot: PetPresentationSnapshot) -> None:
        self._base_content("Schwarz / 黑", snapshot.action)
        badges = QHBoxLayout()
        if not snapshot.attached:
            badges.addWidget(StatusBadge("Unavailable", "unavailable"))
        elif not snapshot.visible:
            badges.addWidget(StatusBadge("Hidden", "neutral"))
        elif snapshot.paused:
            badges.addWidget(StatusBadge("Paused", "paused"))
        else:
            badges.addWidget(StatusBadge("Current Pet", "current"))
            badges.addWidget(StatusBadge("Ready", "ready"))
        badges.addStretch(1)
        self.content.addLayout(badges)
        self.content.addWidget(
            CapabilityNotice(
                CapabilityState.UNKNOWN,
                "Static preview",
                "Animated preview remains isolated until renderer support is "
                "verified.",
            )
        )
        self.content.addStretch(1)

    def show_character(self) -> None:
        self._base_content(
            "Schwarz / 黑",
            "Current desktop companion · Spine 3.8 contract",
        )
        badges = QHBoxLayout()
        badges.addWidget(StatusBadge("Current Pet", "current"))
        badges.addWidget(StatusBadge("Specified", "neutral"))
        badges.addStretch(1)
        self.content.addLayout(badges)
        self.content.addWidget(
            CapabilityNotice(
                CapabilityState.SPECIFIED,
                "Runtime compatibility",
                "The existing pet remains active. Multi-character switching is "
                "not yet connected.",
            )
        )
        use_button = QPushButton("Use This Pet")
        use_button.setProperty("variant", "primary")
        use_button.setEnabled(False)
        use_button.setToolTip(
            "Character switching is specified but not available in this build."
        )
        self.content.addWidget(use_button)
        self.content.addStretch(1)

    def show_action(self, action: ActionSummary) -> None:
        self._base_content(action.name, f"Source Animation · {action.source_animation}")
        metadata = QFrame()
        metadata.setProperty("panel", True)
        grid = QGridLayout(metadata)
        grid.setContentsMargins(12, 12, 12, 12)
        for row, (label, value) in enumerate(
            (
                ("Category", action.category),
                ("Trigger", action.trigger),
                ("Duration", "Runtime metadata"),
                ("Playback", "Runtime metadata"),
            )
        ):
            key = QLabel(label)
            key.setProperty("muted", True)
            grid.addWidget(key, row, 0)
            grid.addWidget(QLabel(value), row, 1)
        self.content.addWidget(metadata)
        play = QPushButton("Play on Desktop")
        play.setObjectName("playDesktopActionButton")
        play.setProperty("variant", "primary")
        play.setToolTip(
            f"Play {action.name} on Schwarz."
        )
        play.clicked.connect(
            lambda checked=False, selected=action.name: (
                self.action_play_requested.emit(selected)
            )
        )
        self.content.addWidget(play)
        self.content.addStretch(1)

    def show_context(self, title: str, message: str) -> None:
        self._base_content(title, message)
        self.content.addWidget(
            CapabilityNotice(
                CapabilityState.AVAILABLE,
                "Context",
                "Settings on this page affect the independent desktop pet.",
            )
        )
        self.content.addStretch(1)


class ControlCenterView(QWidget):
    page_changed = Signal(str)
    action_requested = Signal(str)

    PAGE_ORDER: Final = (
        "home",
        "pets",
        "animations",
        "interaction",
        "appearance",
        "settings",
    )

    def __init__(
        self,
        autostart_controller: AutostartUiController | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("controlCenterRoot")
        self.sidebar = AppSidebar()
        self.stack = QStackedWidget()
        self.stack.setObjectName("pageStack")
        self.home_page = HomePage()
        self.pets_page = MyPetsPage()
        self.animations_page = AnimationsPage()
        self.interaction_page = InteractionPage()
        self.appearance_page = AppearancePage()
        self.settings_page = SettingsPage(autostart_controller)
        self.pages: dict[str, QWidget] = {
            "home": self.home_page,
            "pets": self.pets_page,
            "animations": _scroll_page(self.animations_page),
            "interaction": self.interaction_page,
            "appearance": self.appearance_page,
            "settings": self.settings_page,
        }
        for key in self.PAGE_ORDER:
            self.stack.addWidget(self.pages[key])

        workspace = QWidget()
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)
        utility = QHBoxLayout()
        utility.setContentsMargins(16, 10, 16, 0)
        utility.addStretch(1)
        self.details_button = QToolButton()
        self.details_button.setObjectName("detailsButton")
        self.details_button.setText("Details")
        self.details_button.setVisible(False)
        utility.addWidget(self.details_button)
        workspace_layout.addLayout(utility)
        workspace_layout.addWidget(self.stack, 1)

        self.inspector = InspectorPanel()
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.sidebar)
        root.addWidget(workspace, 1)
        root.addWidget(self.inspector)

        self.sidebar.page_requested.connect(self.navigate)
        self.details_button.clicked.connect(self.open_inspector)
        self.inspector.close_button.clicked.connect(self.close_inspector)
        self.home_page.change_action_requested.connect(
            lambda: self.navigate("animations")
        )
        self.pets_page.character_selected.connect(
            self.inspector.show_character
        )
        self.animations_page.action_selected.connect(
            self.inspector.show_action
        )
        self.inspector.action_play_requested.connect(
            self.action_requested
        )
        self.settings_page.open_appearance_requested.connect(
            lambda: self.navigate("appearance")
        )
        self._minimum_layout = False
        self.navigate("home")

    @property
    def current_page(self) -> str:
        index = self.stack.currentIndex()
        return self.PAGE_ORDER[index]

    def navigate(self, key: str) -> None:
        if key not in self.PAGE_ORDER:
            return
        self.stack.setCurrentIndex(self.PAGE_ORDER.index(key))
        self.sidebar.set_current(key)
        if key == "home":
            self.inspector.show_home(self.home_page._snapshot)
        elif key == "pets":
            self.inspector.show_character()
        elif key == "animations":
            self.inspector.show_action(SCHWARZ_ACTIONS[0])
        elif key == "interaction":
            self.inspector.show_context(
                "Interaction",
                "Direct input overrides autonomous behavior when required.",
            )
        elif key == "appearance":
            self.inspector.show_context(
                "Appearance",
                "Only visibility and always-on-top are connected in this build.",
            )
        else:
            self.inspector.show_context(
                "Settings",
                "Application-level configuration and safe diagnostics.",
            )
        if self._minimum_layout:
            self.close_inspector()
        self.page_changed.emit(key)

    def apply_width(self, width: int) -> None:
        compact = width < 1120
        minimum = width < 960
        self.sidebar.set_compact(compact)
        if minimum != self._minimum_layout:
            self._minimum_layout = minimum
            if minimum:
                self.close_inspector()
            else:
                self.inspector.show()
        self.details_button.setVisible(minimum)
        self.inspector.close_button.setVisible(minimum)

    def open_inspector(self) -> None:
        self.inspector.show()
        self.details_button.setText("Hide Details")

    def close_inspector(self) -> None:
        if not self._minimum_layout:
            return
        self.inspector.hide()
        self.details_button.setText("Details")

    def update_pet(
        self,
        snapshot: PetPresentationSnapshot,
        runtime_ready: bool,
    ) -> None:
        self.home_page.update_pet(snapshot)
        self.appearance_page.update_pet(snapshot)
        self.sidebar.update_status(snapshot, runtime_ready)
        if self.current_page == "home":
            self.inspector.show_home(snapshot)
