"""Inactive Action Palette host and effect sink (Slice 5B, harness only).

Authority: 08 14.2 (Slice 5B), 07 21/23-25, 06 9.2.

Data flow (no redesign):

    authoritative state
        -> build_command_descriptors(source)
        -> tuple[CommandDescriptor, ...]
        -> ActionPaletteHost.render_palette(layer, descriptors)
        -> user chooses a row -> host emits CommandId
        -> ActionPaletteEffectSink (integration owner)
        -> REBUILD current descriptors
        -> dispatch_command_descriptor(current_descriptor, dispatcher)
        -> existing application semantic

Ownership:

- the Host renders CommandDescriptor fields only (label, group, enabled,
  checked, disabled_reason, ordering) and emits a stable semantic
  CommandId.  It never reads PetWindow / available actions / closing /
  autostart state and never calls application commands;
- the EffectSink is the integration owner: it holds the read-only command
  source and the dispatcher, lazily creates the single host, renders current
  descriptors on every Palette show, and resolves the CURRENT descriptor at
  dispatch time so a stale rendered snapshot never owns execution truth;
- the Qt host is never reachable from production Schwarz: Right Click
  continues to open the existing native QMenu (Slice 6B owns the cutover).
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from enum import StrEnum

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import (
    QGuiApplication,
    QIcon,
    QKeyEvent,
    QMoveEvent,
    QPainter,
    QPaintEvent,
)
from PySide6.QtWidgets import (
    QPushButton,
    QStyle,
    QStyleOption,
    QVBoxLayout,
    QWidget,
)

from arkclaw.presentation.command_descriptor_adapter import (
    CommandDescriptor,
    CommandDescriptorSource,
    CommandDispatcher,
    CommandGroup,
    CommandId,
    CommandInvokeIntent,
    build_command_descriptors,
    dispatch_command_descriptor,
)
from arkclaw.presentation.frontend_presentation import (
    ActionPaletteLayer,
    DismissForegroundOverlayIntent,
    ForegroundOverlay,
    FrontendPresentationIntent,
    PresentationEffect,
    PresentationEffectKind,
    SetPaletteLayerIntent,
)
from arkclaw.presentation.qt.theme.design_tokens import (
    DesignTokens,
    load_design_tokens,
)
from arkclaw.presentation.qt.theme.icons import (
    IconKind,
    icon_color_for_theme,
    icon_pixmap,
)
from arkclaw.presentation.qt.theme.qt_theme import QtTheme, apply_theme

_CHECK_MARK = "\u2713"

_ICON_KIND_BY_COMMAND_ID: dict[CommandId, IconKind] = {
    CommandId.OPEN_CHAT_WORK: IconKind.CHAT_WORK,
    CommandId.OPEN_CHARACTER_ANIMATION: IconKind.CHARACTER_ANIMATION,
    CommandId.OPEN_SETTINGS: IconKind.SETTINGS,
    CommandId.ASK_ARKCLAW: IconKind.CHAT_WORK,
    CommandId.PAUSE_CONTINUE: IconKind.ACTIVITY_CURRENT,
    CommandId.RESUME_AUTONOMOUS: IconKind.ACTIVITY_COMPLETED,
    CommandId.RELAX: IconKind.CHARACTER_ANIMATION,
    CommandId.SIT: IconKind.CHARACTER_ANIMATION,
    CommandId.SLEEP: IconKind.CHARACTER_ANIMATION,
    CommandId.INTERACT: IconKind.CHARACTER_ANIMATION,
    CommandId.SPECIAL: IconKind.CHARACTER_ANIMATION,
    CommandId.MOVE_LEFT: IconKind.CHARACTER_ANIMATION,
    CommandId.MOVE_RIGHT: IconKind.CHARACTER_ANIMATION,
    CommandId.ALWAYS_ON_TOP: IconKind.SETTINGS,
    CommandId.START_WITH_WINDOWS: IconKind.SETTINGS,
    CommandId.HIDE_PET: IconKind.CHARACTER_ANIMATION,
    CommandId.QUIT: IconKind.ACTIVITY_ERROR,
}

_ICON_KIND_BY_NAV_LAYER: dict[ActionPaletteLayer, IconKind] = {
    ActionPaletteLayer.CHARACTER: IconKind.CHARACTER_ANIMATION,
    ActionPaletteLayer.ANIMATION: IconKind.ANIMATION,
    ActionPaletteLayer.SYSTEM: IconKind.SETTINGS,
    ActionPaletteLayer.ROOT: IconKind.OPEN,
}

# Fallback anchor metrics used only when no DesignTokens are wired; the
# production composition always loads the frozen tokens so the frozen
# `desktop_companion.action_palette` values are authoritative (07 15).
_PALETTE_ANCHOR_GAP_FALLBACK = 12
_PALETTE_WORK_AREA_MARGIN_FALLBACK = 12


def compute_anchored_palette_position(
    *,
    anchor: QRect,
    palette_size: QSize,
    work_area: QRect,
    gap: int,
    margin: int,
) -> QPoint:
    """Place the palette beside the anchor without covering Schwarz (06 9.2).

    Candidate order follows the frozen anchor contract (05 10, 07 15.208):
    right side, then left side, then above, then below; each candidate must
    fit inside the work area, and the final fallback clamps into the work
    area with the frozen margin.  A degenerate work area (narrower than the
    palette) centers instead of over/underflowing.
    """
    width = palette_size.width()
    height = palette_size.height()
    if width <= 0 or height <= 0 or work_area.width() <= 0:
        return QPoint(anchor.x(), anchor.y())

    def clamp(value: int, lower: int, upper: int) -> int:
        if upper < lower:
            return (lower + upper) // 2
        return min(max(value, lower), upper)

    min_x = work_area.x() + margin
    max_x = work_area.x() + work_area.width() - margin - width
    min_y = work_area.y() + margin
    max_y = work_area.y() + work_area.height() - margin - height

    def fits(x: int, y: int) -> bool:
        return min_x <= x <= max_x and min_y <= y <= max_y

    candidates = (
        # Preferred: right side, upper-aligned with the anchor.
        (anchor.x() + anchor.width() + gap, anchor.y()),
        # Flip: left side, upper-aligned with the anchor.
        (anchor.x() - gap - width, anchor.y()),
        # Above, horizontally centered over the anchor.
        (
            anchor.x() + (anchor.width() - width) // 2,
            anchor.y() - gap - height,
        ),
        # Below, horizontally centered over the anchor.
        (
            anchor.x() + (anchor.width() - width) // 2,
            anchor.y() + anchor.height() + gap,
        ),
    )
    for x, y in candidates:
        if fits(x, y):
            return QPoint(x, y)
    best_x, best_y = candidates[0]
    return QPoint(
        clamp(best_x, min_x, max_x),
        clamp(best_y, min_y, max_y),
    )


def compute_cascading_subpalette_position(
    *,
    main_palette_rect: QRect,
    anim_button_rect: QRect,
    subpalette_size: QSize,
    work_area: QRect,
    gap: int = 6,
    margin: int = 12,
) -> QPoint:
    """Place the subpalette cascading beside the Animation row of the main palette."""
    width = subpalette_size.width()
    height = subpalette_size.height()
    if width <= 0 or height <= 0 or work_area.width() <= 0:
        return QPoint(main_palette_rect.x() + main_palette_rect.width() + gap, anim_button_rect.y())

    min_x = work_area.x() + margin
    max_x = work_area.x() + work_area.width() - margin - width
    min_y = work_area.y() + margin
    max_y = work_area.y() + work_area.height() - margin - height

    # 1. Horizontal: default to right side, flip to left if exceeding boundary.
    right_x = main_palette_rect.x() + main_palette_rect.width() + gap
    left_x = main_palette_rect.x() - gap - width
    if right_x <= max_x:
        best_x = right_x
    elif left_x >= min_x:
        best_x = left_x
    else:
        best_x = max(min_x, min(right_x, max_x))

    # 2. Vertical: align top with the Animation button in the main palette, clamp to work area.
    ideal_y = anim_button_rect.y()
    best_y = max(min_y, min(ideal_y, max_y))

    return QPoint(best_x, best_y)


class ActionPaletteWindowStrategy(StrEnum):
    """Native window strategy candidates for the one Palette host (Slice 6A).

    Slice 6A spike seam only: the chosen strategy is applied to the native
    window flags exactly once at construction and is never restyled per
    render. The frozen production default is TOOL (07 23); POPUP exists so
    the 6A native harness can measure both candidates against the frozen
    dismiss contracts (09 5.1 K/L) before 6B chooses the cutover.
    """

    TOOL = "tool"
    POPUP = "popup"


_TOOL_WINDOW_FLAGS = (
    Qt.WindowType.Tool
    | Qt.WindowType.FramelessWindowHint
    | Qt.WindowType.WindowStaysOnTopHint
)
_POPUP_WINDOW_FLAGS = (
    Qt.WindowType.Popup
    | Qt.WindowType.FramelessWindowHint
    | Qt.WindowType.WindowStaysOnTopHint
)


class ActionPaletteSubHost(QWidget):
    """Cascading sub-palette surface displaying the character animation action set."""

    command_selected = Signal(object)
    back_requested = Signal()
    dismiss_requested = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        strategy: ActionPaletteWindowStrategy = (
            ActionPaletteWindowStrategy.TOOL
        ),
        theme: QtTheme = QtTheme.LIGHT,
        tokens: DesignTokens | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ActionPaletteSubHost")
        self._strategy = strategy
        self._theme = theme
        self._tokens = tokens if tokens is not None else load_design_tokens()
        flags = (
            _TOOL_WINDOW_FLAGS
            if strategy is ActionPaletteWindowStrategy.TOOL
            else _POPUP_WINDOW_FLAGS
        )
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        palette_tokens = self._tokens.component["desktop_companion"]["action_palette"]
        self.setFixedWidth(int(palette_tokens["width"]))
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(
            int(palette_tokens["outer_padding"]),
            int(palette_tokens["outer_padding"]),
            int(palette_tokens["outer_padding"]),
            int(palette_tokens["outer_padding"]),
        )
        self._layout.setSpacing(4)
        self._items: list[tuple[str, object]] = []
        self._buttons: dict[CommandId, QPushButton] = {}
        self._back_button: QPushButton | None = None
        self._enabled: dict[CommandId, bool] = {}
        self._checked: dict[CommandId, bool | None] = {}

    @property
    def items(self) -> tuple[tuple[str, object], ...]:
        return tuple(self._items)

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        option = QStyleOption()
        option.initFrom(self)
        painter = QPainter(self)
        self.style().drawPrimitive(
            QStyle.PrimitiveElement.PE_Widget,
            option,
            painter,
            self,
        )

    def set_theme(self, theme: QtTheme) -> None:
        self._theme = theme
        apply_theme(self, theme, self._tokens)

    def row_button(self, command_id: CommandId) -> QPushButton | None:
        return self._buttons.get(command_id)

    def navigation_button(
        self,
        target: ActionPaletteLayer,
    ) -> QPushButton | None:
        if target is ActionPaletteLayer.ROOT:
            return self._back_button
        return None

    def checked(self, command_id: CommandId) -> bool | None:
        return self._checked.get(command_id)

    def render_actions(
        self,
        descriptors: tuple[CommandDescriptor, ...],
    ) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._items = []
        self._buttons = {}
        self._enabled = {}
        self._checked = {}

        # 1. Back button
        back_btn = QPushButton("Back", self)
        back_btn.setObjectName("paletteNav_root")
        back_btn.setFixedHeight(44)
        icon_color = icon_color_for_theme(self._tokens, self._theme)
        pix = icon_pixmap(IconKind.OPEN, 20.0, icon_color)
        back_btn.setIcon(QIcon(pix))
        back_btn.setIconSize(QSize(20, 20))
        back_btn.clicked.connect(lambda: self.back_requested.emit())
        self._layout.addWidget(back_btn)
        self._back_button = back_btn
        self._items.append(("nav", ActionPaletteLayer.ROOT))

        # 2. Action buttons
        for descriptor in descriptors:
            if descriptor.group is CommandGroup.CHARACTER and descriptor.command_id in {
                CommandId.RELAX,
                CommandId.MOVE_LEFT,
                CommandId.MOVE_RIGHT,
                CommandId.SIT,
                CommandId.SLEEP,
                CommandId.SPECIAL,
                CommandId.INTERACT,
                CommandId.RESUME_AUTONOMOUS,
            }:
                label = descriptor.label
                if descriptor.checked is True:
                    label = f"{descriptor.label}  \u2713"
                button = QPushButton(label, self)
                button.setObjectName(f"paletteRow_{descriptor.command_id.value}")
                button.setFixedHeight(44)
                button.setEnabled(descriptor.enabled)
                if descriptor.disabled_reason:
                    button.setToolTip(descriptor.disabled_reason)
                elif descriptor.conditional:
                    button.setToolTip("availability is conditional")
                kind = _ICON_KIND_BY_COMMAND_ID.get(descriptor.command_id)
                if kind is not None:
                    pix = icon_pixmap(kind, 20.0, icon_color)
                    button.setIcon(QIcon(pix))
                    button.setIconSize(QSize(20, 20))
                button.clicked.connect(
                    lambda _, cid=descriptor.command_id: self._on_row_clicked(cid)
                )
                self._layout.addWidget(button)
                self._buttons[descriptor.command_id] = button
                self._enabled[descriptor.command_id] = descriptor.enabled
                self._checked[descriptor.command_id] = descriptor.checked
                self._items.append(("command", descriptor.command_id))

    def _on_row_clicked(
        self,
        command_id: CommandId,
        *args: object,
    ) -> None:
        if not self._enabled.get(command_id, False):
            return
        self.command_selected.emit(command_id)

    def focus_first_enabled(self) -> None:
        if self._back_button is not None and self._back_button.isEnabled():
            self._back_button.setFocus()
            return
        for button in self._buttons.values():
            if button.isEnabled():
                button.setFocus()
                return

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.back_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class ActionPaletteHost(QWidget):
    """Frameless Tool surface that renders descriptors and emits CommandIds.

    The host owns only local Qt rendering and signal mechanics.  It never
    owns command availability, checked truth, or application state; every
    command target is resolved by the integration owner at dispatch time.
    """

    command_selected = Signal(object)
    navigation_requested = Signal(object)  # emits ActionPaletteLayer target
    dismiss_requested = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        strategy: ActionPaletteWindowStrategy = (
            ActionPaletteWindowStrategy.TOOL
        ),
        theme: QtTheme = QtTheme.LIGHT,
        tokens: DesignTokens | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ActionPaletteHost")
        self._strategy = strategy
        self._theme = theme
        self._tokens = tokens if tokens is not None else load_design_tokens()
        flags = (
            _TOOL_WINDOW_FLAGS
            if strategy is ActionPaletteWindowStrategy.TOOL
            else _POPUP_WINDOW_FLAGS
        )
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        palette_tokens = self._tokens.component["desktop_companion"]["action_palette"]
        self.setFixedWidth(int(palette_tokens["width"]))
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(
            int(palette_tokens["outer_padding"]),
            int(palette_tokens["outer_padding"]),
            int(palette_tokens["outer_padding"]),
            int(palette_tokens["outer_padding"]),
        )
        self._layout.setSpacing(4)
        self._items: list[tuple[str, object]] = []
        self._buttons: dict[CommandId, QPushButton] = {}
        self._nav_buttons: dict[ActionPaletteLayer, QPushButton] = {}
        self._enabled: dict[CommandId, bool] = {}
        self._checked: dict[CommandId, bool | None] = {}
        self._sub_host: ActionPaletteSubHost | None = None
        self._last_descriptors: tuple[CommandDescriptor, ...] = ()
        # The rendered layer is cached for local key handling only; the
        # Qt-free FrontendPresentationModel owns the authoritative layer.
        self._layer = ActionPaletteLayer.ROOT

    @property
    def sub_host(self) -> ActionPaletteSubHost | None:
        return self._sub_host

    @property
    def items(self) -> tuple[tuple[str, object], ...]:
        """Read-only projection of the rendered hierarchy, in render order."""
        if self._layer is ActionPaletteLayer.ANIMATION and self._sub_host is not None:
            return self._sub_host.items
        return tuple(self._items)

    @property
    def current_layer(self) -> ActionPaletteLayer:
        """Currently rendered same-shell layer (presentation cache only)."""
        return self._layer

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        option = QStyleOption()
        option.initFrom(self)
        painter = QPainter(self)
        self.style().drawPrimitive(
            QStyle.PrimitiveElement.PE_Widget,
            option,
            painter,
            self,
        )

    def set_theme(self, theme: QtTheme) -> None:
        self._theme = theme
        apply_theme(self, theme, self._tokens)
        if self._sub_host is not None:
            self._sub_host.set_theme(theme)

    def row_button(self, command_id: CommandId) -> QPushButton | None:
        btn = self._buttons.get(command_id)
        if btn is not None:
            return btn
        if self._sub_host is not None:
            return self._sub_host.row_button(command_id)
        return None

    def navigation_button(
        self,
        target: ActionPaletteLayer,
    ) -> QPushButton | None:
        btn = self._nav_buttons.get(target)
        if btn is not None:
            return btn
        if self._sub_host is not None:
            return self._sub_host.navigation_button(target)
        return None

    def checked(self, command_id: CommandId) -> bool | None:
        val = self._checked.get(command_id)
        if val is not None:
            return val
        if self._sub_host is not None:
            return self._sub_host.checked(command_id)
        return None

    def moveEvent(self, event: QMoveEvent) -> None:
        super().moveEvent(event)
        if self._sub_host is not None and self._sub_host.isVisible():
            self._reposition_sub_host()

    def _reposition_sub_host(self) -> None:
        if self._sub_host is None:
            return
        screen = self.screen() or QGuiApplication.primaryScreen()
        work_area = (
            screen.availableGeometry()
            if screen is not None
            else QRect(0, 0, 1920, 1080)
        )
        anim_btn = self._nav_buttons.get(ActionPaletteLayer.ANIMATION)
        if anim_btn is not None and self.isVisible():
            btn_top_left = anim_btn.mapToGlobal(QPoint(0, 0))
            anim_btn_rect = QRect(
                btn_top_left.x(),
                btn_top_left.y(),
                anim_btn.width(),
                anim_btn.height(),
            )
        else:
            anim_btn_rect = self.frameGeometry()

        sub_size = self._sub_host.sizeHint()
        if sub_size.height() < 200:
            sub_size = QSize(220, 460)
        self._sub_host.resize(sub_size)
        pos = compute_cascading_subpalette_position(
            main_palette_rect=self.frameGeometry(),
            anim_button_rect=anim_btn_rect,
            subpalette_size=sub_size,
            work_area=work_area,
        )
        self._sub_host.move(pos)

    def show_sub_palette(
        self,
        descriptors: tuple[CommandDescriptor, ...],
    ) -> None:
        self._layer = ActionPaletteLayer.ANIMATION
        if self._sub_host is None:
            self._sub_host = ActionPaletteSubHost(
                parent=self,
                strategy=self._strategy,
                theme=self._theme,
                tokens=self._tokens,
            )
            self._sub_host.command_selected.connect(self._on_sub_command_selected)
            self._sub_host.back_requested.connect(self._on_sub_back_requested)
            apply_theme(self._sub_host, self._theme, self._tokens)
        self._sub_host.render_actions(descriptors)
        self._sub_host.adjustSize()
        self._reposition_sub_host()
        self._sub_host.show()
        self._sub_host.raise_()
        self._sub_host.focus_first_enabled()

    def hide_sub_palette(self) -> None:
        self._layer = ActionPaletteLayer.ROOT
        if self._sub_host is not None:
            self._sub_host.hide()
            self._sub_host.setVisible(False)

    def _on_sub_command_selected(
        self,
        command_id: CommandId,
        *args: object,
    ) -> None:
        self.hide_sub_palette()
        self.command_selected.emit(command_id)

    def _on_sub_back_requested(self, *args: object) -> None:
        self.hide_sub_palette()
        self.navigation_requested.emit(ActionPaletteLayer.ROOT)
        anim_btn = self._nav_buttons.get(ActionPaletteLayer.ANIMATION)
        if anim_btn is not None and anim_btn.isEnabled():
            anim_btn.setFocus()

    def hide(self) -> None:
        self.hide_sub_palette()
        super().hide()

    def close(self) -> bool:
        if self._sub_host is not None:
            self._sub_host.close()
        return super().close()

    def render_palette(
        self,
        layer: ActionPaletteLayer,
        descriptors: tuple[CommandDescriptor, ...],
    ) -> None:
        """Render one same-shell Palette layer from one descriptor snapshot."""
        self._last_descriptors = descriptors
        if layer is ActionPaletteLayer.ANIMATION:
            self.show_sub_palette(descriptors)
            return

        self.hide_sub_palette()
        self._clear()
        self._items = []
        self._buttons = {}
        self._nav_buttons = {}
        self._enabled = {}
        self._checked = {}
        self._layer = layer
        if layer is ActionPaletteLayer.ROOT:
            is_closing = any(
                d.disabled_reason == "pet_closing" for d in descriptors
            )
            # 1. Ask ArkClaw
            self._add_command_row(
                CommandDescriptor(
                    command_id=CommandId.OPEN_CHAT_WORK,
                    label="Ask ArkClaw",
                    group=CommandGroup.AGENT,
                    enabled=not is_closing,
                    invoke_intent=CommandInvokeIntent.OPEN_CHAT_WORK,
                    disabled_reason="pet_closing" if is_closing else None,
                )
            )
            # 2. Character
            self._add_command_row(
                CommandDescriptor(
                    command_id=CommandId.OPEN_CHARACTER_ANIMATION,
                    label="Character",
                    group=CommandGroup.CHARACTER,
                    enabled=not is_closing,
                    invoke_intent=CommandInvokeIntent.OPEN_CHARACTER_ANIMATION,
                    disabled_reason="pet_closing" if is_closing else None,
                )
            )
            # 3. Animation >
            self._add_navigation_row(
                "Animation",
                ActionPaletteLayer.ANIMATION,
            )
            # 4. System
            self._add_command_row(
                CommandDescriptor(
                    command_id=CommandId.OPEN_SETTINGS,
                    label="System",
                    group=CommandGroup.SYSTEM,
                    enabled=not is_closing,
                    invoke_intent=CommandInvokeIntent.OPEN_SETTINGS,
                    disabled_reason="pet_closing" if is_closing else None,
                )
            )
            return
        if layer is ActionPaletteLayer.CHARACTER:
            self._add_navigation_row("Back", ActionPaletteLayer.ROOT)
            for descriptor in descriptors:
                if descriptor.group is CommandGroup.CHARACTER:
                    self._add_command_row(descriptor)
            return
        self._add_navigation_row("Back", ActionPaletteLayer.ROOT)
        for descriptor in descriptors:
            if descriptor.group is CommandGroup.SYSTEM:
                self._add_command_row(descriptor)

    def _add_command_row(self, descriptor: CommandDescriptor) -> None:
        label = descriptor.label
        if descriptor.checked is True:
            label = f"{descriptor.label}  \u2713"
        button = QPushButton(label, self)
        button.setObjectName(f"paletteRow_{descriptor.command_id.value}")
        button.setFixedHeight(44)
        button.setEnabled(descriptor.enabled)
        if descriptor.disabled_reason:
            button.setToolTip(descriptor.disabled_reason)
        elif descriptor.conditional:
            button.setToolTip("availability is conditional")

        kind = _ICON_KIND_BY_COMMAND_ID.get(descriptor.command_id)
        if kind is not None:
            icon_color = icon_color_for_theme(self._tokens, self._theme)
            pix = icon_pixmap(kind, 20.0, icon_color)
            button.setIcon(QIcon(pix))
            button.setIconSize(QSize(20, 20))

        button.clicked.connect(
            lambda _, cid=descriptor.command_id: self._on_row_clicked(cid)
        )
        self._layout.addWidget(button)
        self._buttons[descriptor.command_id] = button
        self._enabled[descriptor.command_id] = descriptor.enabled
        self._checked[descriptor.command_id] = descriptor.checked
        self._items.append(("command", descriptor.command_id))

    def _add_navigation_row(
        self,
        label: str,
        target: ActionPaletteLayer,
    ) -> None:
        button = QPushButton(label, self)
        button.setObjectName(f"paletteNav_{target.value}")
        button.setFixedHeight(44)
        kind = _ICON_KIND_BY_NAV_LAYER.get(target)
        if kind is not None:
            icon_color = icon_color_for_theme(self._tokens, self._theme)
            pix = icon_pixmap(kind, 20.0, icon_color)
            button.setIcon(QIcon(pix))
            button.setIconSize(QSize(20, 20))

        button.clicked.connect(
            lambda _, tgt=target: self._on_navigation_clicked(tgt)
        )
        self._layout.addWidget(button)
        self._nav_buttons[target] = button
        self._items.append(("nav", target))

    def focus_first_enabled(self) -> None:
        for button in self._buttons.values():
            if button.isEnabled():
                button.setFocus()
                return
        for button in self._nav_buttons.values():
            if button.isEnabled():
                button.setFocus()
                return

    def _clear(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _on_row_clicked(
        self,
        command_id: CommandId,
        *args: object,
    ) -> None:
        # Defense-in-depth: disabled rows are non-activatable even if a stale
        # or artificial activation path reached this slot.
        if not self._enabled.get(command_id, False):
            return
        self.command_selected.emit(command_id)

    def _on_navigation_clicked(
        self,
        target: ActionPaletteLayer,
        *args: object,
    ) -> None:
        if target is ActionPaletteLayer.ANIMATION:
            if self._sub_host is not None and self._sub_host.isVisible():
                self.hide_sub_palette()
                self.navigation_requested.emit(ActionPaletteLayer.ROOT)
                return
            self.show_sub_palette(self._last_descriptors)
            self.navigation_requested.emit(ActionPaletteLayer.ANIMATION)
            return
        self.navigation_requested.emit(target)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            if self._sub_host is not None and self._sub_host.isVisible():
                self.hide_sub_palette()
                self.navigation_requested.emit(ActionPaletteLayer.ROOT)
            elif self._layer is ActionPaletteLayer.ROOT:
                self.dismiss_requested.emit()
            else:
                self.navigation_requested.emit(ActionPaletteLayer.ROOT)
            event.accept()
            return
        super().keyPressEvent(event)


class ActionPaletteEffectSink:
    """Effect-routing integration owner for the inactive Palette host.

    The sink holds the narrow command source + dispatcher seam, lazily owns
    exactly one ActionPaletteHost, and resolves the CURRENT descriptor at
    dispatch time.  The host never sees the source, the dispatcher, or any
    application callback.
    """

    def __init__(
        self,
        *,
        source: CommandDescriptorSource,
        dispatcher: CommandDispatcher,
        strategy: ActionPaletteWindowStrategy = (
            ActionPaletteWindowStrategy.TOOL
        ),
        intent_handler: (
            Callable[[FrontendPresentationIntent], None] | None
        ) = None,
        anchor_source: Callable[[], QRect] | None = None,
        theme: QtTheme | None = None,
        tokens: DesignTokens | None = None,
    ) -> None:
        self._source = source
        self._dispatcher = dispatcher
        self._strategy = strategy
        self._host: ActionPaletteHost | None = None
        self._intent_handler = intent_handler
        self._anchor_source = anchor_source
        self._theme = theme
        self._tokens = tokens
        # Presentation projection of the model-owned Palette layer, synced
        # from SHOW_FOREGROUND_OVERLAY / PALETTE_LAYER_CHANGED effects.
        self._layer = ActionPaletteLayer.ROOT

    @property
    def host(self) -> ActionPaletteHost | None:
        return self._host

    @property
    def strategy(self) -> ActionPaletteWindowStrategy:
        """Native window strategy selected at composition time (6B)."""
        return self._strategy

    def attach_intent_handler(
        self,
        handler: Callable[[FrontendPresentationIntent], None],
    ) -> None:
        self._intent_handler = handler

    def dispose(self) -> None:
        """Tear down the lazily-created host (idempotent, 6B lifecycle seam).

        Closes and schedules deferred deletion of the single host and detaches
        its signal wiring so no owned ``ActionPaletteHost`` top-level survives
        the owning composition's teardown.  A later show request lazily
        creates a fresh host; the lazy single-host contract is unchanged.
        """
        host = self._host
        if host is None:
            return
        for signal in (
            host.command_selected,
            host.navigation_requested,
            host.dismiss_requested,
        ):
            with contextlib.suppress(RuntimeError, TypeError):
                signal.disconnect()
        with contextlib.suppress(RuntimeError):
            host.hide()
            host.close()
            host.deleteLater()
        self._host = None

    def apply(self, effect: PresentationEffect) -> None:
        if (
            effect.kind is PresentationEffectKind.SHOW_FOREGROUND_OVERLAY
            and effect.overlay is ForegroundOverlay.PALETTE
        ):
            if effect.layer is not None:
                self._layer = effect.layer
            self._show_palette()
        elif (
            effect.kind is PresentationEffectKind.PALETTE_LAYER_CHANGED
            and effect.layer is not None
        ):
            self._layer = effect.layer
            self._rerender()
        elif (
            effect.kind is PresentationEffectKind.DISMISS_FOREGROUND_OVERLAY
            and effect.overlay is ForegroundOverlay.PALETTE
        ):
            self._hide_palette()

    def _show_palette(self) -> None:
        host = self._ensure_host()
        # Always render the freshest projection; the snapshot displayed here
        # is presentation only and never becomes execution authority.
        host.render_palette(
            self._layer,
            build_command_descriptors(self._source),
        )
        self._position_host(host)
        host.show()
        host.raise_()
        host.focus_first_enabled()

    def _position_host(self, host: ActionPaletteHost) -> None:
        """Anchor the host beside Schwarz before it becomes visible (06 9.2)."""
        host.adjustSize()
        position = self._resolve_palette_position(host.size())
        if position is not None:
            host.move(position)

    def _resolve_palette_position(self, size: QSize) -> QPoint | None:
        anchor = self._resolve_anchor()
        if anchor is None:
            return None
        screen = QGuiApplication.screenAt(anchor.center())
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return QPoint(anchor.x(), anchor.y())
        gap, margin = self._palette_anchor_metrics()
        return compute_anchored_palette_position(
            anchor=anchor,
            palette_size=size,
            work_area=screen.availableGeometry(),
            gap=gap,
            margin=margin,
        )

    def _resolve_anchor(self) -> QRect | None:
        anchor_source = self._anchor_source
        if anchor_source is None:
            return None
        try:
            anchor = anchor_source()
        except Exception:
            return None
        if anchor is None:
            return None
        return anchor

    def _palette_anchor_metrics(self) -> tuple[int, int]:
        tokens = self._tokens
        if tokens is None and self._theme is not None:
            tokens = load_design_tokens()
        if tokens is None:
            return (
                _PALETTE_ANCHOR_GAP_FALLBACK,
                _PALETTE_WORK_AREA_MARGIN_FALLBACK,
            )
        section = tokens.component["desktop_companion"]["action_palette"]
        return int(section["anchor_gap"]), int(section["work_area_margin"])

    def _rerender(self) -> None:
        """Rerender the current layer in the same host instance."""
        host = self._host
        if host is None or not host.isVisible():
            return
        host.render_palette(
            self._layer,
            build_command_descriptors(self._source),
        )
        host.adjustSize()
        host.focus_first_enabled()

    def _hide_palette(self) -> None:
        host = self._host
        if host is not None and host.isVisible():
            host.hide()

    def set_theme(self, theme: QtTheme) -> None:
        self._theme = theme
        if self._host is not None:
            self._host.set_theme(theme)

    def _ensure_host(self) -> ActionPaletteHost:
        if self._host is None:
            theme = self._theme if self._theme is not None else QtTheme.LIGHT
            tokens = self._tokens if self._tokens is not None else load_design_tokens()
            host = ActionPaletteHost(
                strategy=self._strategy,
                theme=theme,
                tokens=tokens,
            )
            # Bind exactly once at lazy creation; re-show never re-connects,
            # so one click can never dispatch twice.
            host.command_selected.connect(self._on_command_selected)
            host.navigation_requested.connect(
                self._on_navigation_requested
            )
            host.dismiss_requested.connect(self._on_dismiss_requested)
            apply_theme(host, theme, tokens)
            self._host = host
        return self._host

    def _on_navigation_requested(
        self,
        layer: ActionPaletteLayer,
    ) -> None:
        # Navigation is Palette presentation semantics only: route the
        # Qt-free layer intent to the model.  Zero application dispatch.
        handler = self._intent_handler
        if handler is not None:
            handler(SetPaletteLayerIntent(layer))


    def _on_dismiss_requested(self) -> None:
        handler = self._intent_handler
        if handler is not None:
            handler(DismissForegroundOverlayIntent())

    def _on_command_selected(self, command_id: CommandId) -> None:
        # Selection is one ordered transaction (07 20.2): dismiss the Palette
        # through the model, then dispatch the CURRENT descriptor.
        handler = self._intent_handler
        if handler is not None:
            handler(DismissForegroundOverlayIntent())
        self._dispatch_current_command(command_id)

    def _dispatch_current_command(
        self,
        command_id: CommandId,
    ) -> object | None:
        """Resolve the CURRENT descriptor and dispatch it exactly once.

        Rebuilds from the authoritative source at dispatch time; a command
        that is no longer present or enabled produces zero execution and no
        fallback to another command.
        """
        if self._source.pet_closing:
            return None
        if (
            command_id is CommandId.OPEN_CHAT_WORK
            or command_id is CommandId.ASK_ARKCLAW
        ):
            self._dispatcher.open_chat_work()
            return None
        if command_id is CommandId.OPEN_CHARACTER_ANIMATION:
            self._dispatcher.open_character_animation()
            return None
        if command_id is CommandId.OPEN_SETTINGS:
            self._dispatcher.open_settings()
            return None
        descriptors = build_command_descriptors(self._source)
        current = next(
            (
                item
                for item in descriptors
                if item.command_id is command_id
            ),
            None,
        )
        if current is None:
            return None
        return dispatch_command_descriptor(current, self._dispatcher)


__all__ = [
    "ActionPaletteEffectSink",
    "ActionPaletteHost",
    "ActionPaletteSubHost",
    "ActionPaletteWindowStrategy",
    "compute_anchored_palette_position",
    "compute_cascading_subpalette_position",
]
