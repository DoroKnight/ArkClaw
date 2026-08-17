"""Dashboard primary NavigationPane (Slice 7B).

Authority: 07 sections 7/17 and tokens component.dashboard.navigation:
expanded 208 / collapsed 72 / row 44 / radius 12 / leading inset 16 /
icon 20 / icon-text gap 12 / rail padding 12 / indicator 3x24 / toggle
hit target 40.  Selected rows carry surface-selected background, accent
indicator, and primary text; hover/pressed/focus/disabled states come from
the token-generated QSS.  Collapsed rows keep accessible names and expose
tooltips, and remain keyboard reachable.
"""

from __future__ import annotations

from functools import partial

from PySide6.QtCore import Qt, QVariantAnimation, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from arkclaw.presentation.qt.dashboard.dashboard_page import (
    PAGE_LABELS,
    DashboardPage,
)
from arkclaw.presentation.qt.theme.design_tokens import (
    DesignTokens,
    load_design_tokens,
)
from arkclaw.presentation.qt.theme.icons import (
    IconKind,
    accent_color_for_theme,
    icon_color_for_theme,
    icon_kind_for_page,
    icon_pixmap,
)
from arkclaw.presentation.qt.theme.qt_theme import QtTheme, motion_enabled


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class _NavRow(QWidget):
    """One primary navigation row: indicator + icon + label (keyboardable)."""

    activated = Signal()

    def __init__(
        self,
        page: DashboardPage,
        tokens: DesignTokens,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._page = page
        self._tokens = tokens
        self.setObjectName("navRow")
        self.setProperty("selected", False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        navigation = tokens.component["dashboard"]["navigation"]
        self.setMinimumHeight(int(navigation["row_height"]))
        self.setMinimumWidth(int(navigation["toggle_hit_target"]))
        self.setAccessibleName(PAGE_LABELS[page])
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 4, 0)
        layout.setSpacing(0)
        self._indicator = QFrame(self)
        self._indicator.setObjectName("navIndicator")
        self._indicator.setFixedSize(
            int(navigation["active_indicator_width"]),
            int(navigation["active_indicator_height"]),
        )
        self._indicator.setVisible(False)
        layout.addWidget(self._indicator)
        layout.addSpacing(
            int(navigation["leading_inset"])
            - int(navigation["active_indicator_width"])
        )
        self._icon = QLabel(self)
        self._icon.setFixedSize(
            int(navigation["icon_size"]),
            int(navigation["icon_size"]),
        )
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._icon)
        self._icon_kind = icon_kind_for_page(page)
        self._theme = QtTheme.LIGHT
        self._render_icon()
        layout.addSpacing(8)
        self._label = QLabel(PAGE_LABELS[page], self)
        self._label.setWordWrap(False)
        layout.addWidget(self._label)
        layout.addStretch(1)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) or (
            key == Qt.Key.Key_Space
            and not event.modifiers()
        ):
            self.activated.emit()
            event.accept()
            return
        if key == Qt.Key.Key_Down:
            self._focus_relative(1)
            event.accept()
            return
        if key == Qt.Key.Key_Up:
            self._focus_relative(-1)
            event.accept()
            return
        super().keyPressEvent(event)

    def _focus_relative(self, delta: int) -> None:
        pane = self.parentWidget()
        if isinstance(pane, NavigationPane):
            pane._focus_relative(self, delta)

    def set_selected(self, selected: bool) -> None:
        if bool(self.property("selected")) == selected:
            self._indicator.setVisible(selected)
            return
        self.setProperty("selected", selected)
        self._indicator.setVisible(selected)
        self._render_icon()
        _repolish(self)

    def set_theme(self, theme: QtTheme) -> None:
        if self._theme is theme:
            return
        self._theme = theme
        self._render_icon()

    def icon_kind(self) -> IconKind:
        return self._icon_kind

    def icon_pixmap(self) -> QPixmap:
        pixmap = self._icon.pixmap()
        assert pixmap is not None
        return pixmap

    def _render_icon(self) -> None:
        size = int(self._tokens.component["dashboard"]["navigation"]["icon_size"])
        selected = bool(self.property("selected"))
        color = (
            accent_color_for_theme(self._tokens, self._theme)
            if selected
            else icon_color_for_theme(self._tokens, self._theme)
        )
        self._icon.setPixmap(
            icon_pixmap(
                self._icon_kind,
                size,
                color,
                dpr=self.devicePixelRatioF(),
            )
        )

    def set_label_visible(self, visible: bool) -> None:
        self._label.setVisible(visible)


class NavigationPane(QWidget):
    """Frozen-width primary navigation rail (expanded 208 / collapsed 72)."""

    page_selected = Signal(object)
    collapse_toggled = Signal(bool)

    def __init__(
        self,
        tokens: DesignTokens | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens = tokens if tokens is not None else load_design_tokens()
        navigation = self._tokens.component["dashboard"]["navigation"]
        self._expanded_width = int(navigation["expanded_width"])
        self._collapsed_width = int(navigation["collapsed_width"])
        self._collapsed = False
        self._selected = DashboardPage.HOME
        self._width_animation: QVariantAnimation | None = None
        self.setObjectName("navigationPane")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            int(navigation["rail_padding"]),
            int(navigation["rail_padding"]),
            int(navigation["rail_padding"]),
            int(navigation["rail_padding"]),
        )
        layout.setSpacing(4)
        self._toggle = QPushButton("«", self)
        self._toggle.setObjectName("navToggle")
        self._toggle.setFixedSize(
            int(navigation["toggle_hit_target"]),
            int(navigation["toggle_hit_target"]),
        )
        self._toggle.setToolTip("Collapse navigation")
        self._toggle.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._toggle.clicked.connect(self._on_toggle_clicked)
        layout.addWidget(self._toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self._rows: dict[DashboardPage, _NavRow] = {}
        for page in DashboardPage:
            row = _NavRow(page, self._tokens, self)
            row.activated.connect(partial(self._on_row_activated, page))
            layout.addWidget(row)
            self._rows[page] = row
        layout.addStretch(1)
        self._apply_width(self._expanded_width)
        self._refresh_rows()
        self._set_selected(self._selected)

    # -- public geometry / state -------------------------------------------
    def is_collapsed(self) -> bool:
        return self._collapsed

    def page_ids(self) -> list[DashboardPage]:
        return list(DashboardPage)

    def page_button(self, page: DashboardPage) -> QWidget:
        return self._rows[page]

    def toggle_button(self) -> QPushButton:
        return self._toggle

    def is_selected(self, page: DashboardPage) -> bool:
        return self._selected is page

    def active_indicator_size(self) -> tuple[int, int]:
        navigation = self._tokens.component["dashboard"]["navigation"]
        return (
            int(navigation["active_indicator_width"]),
            int(navigation["active_indicator_height"]),
        )

    def select_page(self, page: DashboardPage) -> None:
        self._set_selected(page)

    def set_collapsed(
        self,
        collapsed: bool,
        *,
        animate: bool = False,
    ) -> None:
        collapsed = bool(collapsed)
        self._collapsed = collapsed
        target = self._collapsed_width if collapsed else self._expanded_width
        if animate and motion_enabled():
            self._animate_width(target)
        else:
            self._stop_animation()
            self._apply_width(target)
        self._refresh_rows()
        self.collapse_toggled.emit(collapsed)

    # -- internal -----------------------------------------------------------
    def _set_selected(self, page: DashboardPage) -> None:
        self._selected = page
        for candidate, row in self._rows.items():
            row.set_selected(candidate is page)

    def _on_row_activated(self, page: DashboardPage) -> None:
        self._set_selected(page)
        self.page_selected.emit(page)

    def _on_toggle_clicked(self) -> None:
        self.set_collapsed(not self._collapsed, animate=True)

    def _refresh_rows(self) -> None:
        for page, row in self._rows.items():
            row.set_label_visible(not self._collapsed)
            row.setToolTip(PAGE_LABELS[page] if self._collapsed else "")
        self._toggle.setText("»" if self._collapsed else "«")
        self._toggle.setToolTip(
            "Expand navigation" if self._collapsed else "Collapse navigation"
        )

    def _apply_width(self, target: int) -> None:
        self.setFixedWidth(target)
        self.resize(target, max(self.height(), 56))

    def _animate_width(self, target: int) -> None:
        self._stop_animation()
        start = self.width()
        animation = QVariantAnimation(self)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setDuration(
            int(self._tokens.motion["navigation_toggle"]["duration_ms"])
        )
        animation.valueChanged.connect(
            lambda value: self._apply_width(
                int(start + (target - start) * float(value))
            )
        )
        animation.finished.connect(lambda: self._apply_width(target))
        self._width_animation = animation
        animation.start()

    def _stop_animation(self) -> None:
        if self._width_animation is not None:
            self._width_animation.stop()
            self._width_animation.deleteLater()
            self._width_animation = None

    def _focus_relative(self, current: _NavRow, delta: int) -> None:
        pages = list(DashboardPage)
        index = pages.index(current._page)
        target = pages[(index + delta) % len(pages)]
        self._rows[target].setFocus()

    def set_theme(self, theme: QtTheme) -> None:
        for row in self._rows.values():
            row.set_theme(theme)

    def dispose(self) -> None:
        """Stop owned animations (idempotent)."""
        self._stop_animation()
