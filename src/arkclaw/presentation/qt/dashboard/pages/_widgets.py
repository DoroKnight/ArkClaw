"""Small shared widgets for Dashboard pages (Slice 7C-7E).

All geometry comes from the frozen tokens; no raw dimension literals are
scattered here.  State is always rendered as icon + text (never color-only)
per 07 14, and the widgets remain pure presentation surfaces.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from arkclaw.presentation.dashboard_presentation import (
    ActivityItem,
    ActivityState,
    AttachmentItem,
    AttachmentState,
)
from arkclaw.presentation.qt.theme.design_tokens import (
    DesignTokens,
    ThemeColors,
    ThemeVariant,
)
from arkclaw.presentation.qt.theme.icons import IconKind, icon_pixmap
from arkclaw.presentation.qt.theme.qt_theme import QtTheme

_ACTIVITY_KINDS = {
    ActivityState.COMPLETED: IconKind.ACTIVITY_COMPLETED,
    ActivityState.CURRENT: IconKind.ACTIVITY_CURRENT,
    ActivityState.FUTURE: IconKind.ACTIVITY_FUTURE,
    ActivityState.ERROR: IconKind.ACTIVITY_ERROR,
    ActivityState.WARNING: IconKind.ACTIVITY_WARNING,
}

_ACTIVITY_COLOR_PATH = {
    ActivityState.COMPLETED: ("state", "success"),
    ActivityState.CURRENT: ("accent", "default"),
    ActivityState.FUTURE: ("text", "tertiary"),
    ActivityState.ERROR: ("state", "danger"),
    ActivityState.WARNING: ("state", "warning"),
}


def _resolve_theme_color(colors: ThemeColors, path: tuple[str, str]) -> str:
    group = getattr(colors, path[0])
    return str(getattr(group, path[1]))

_ATTACHMENT_STATE_TEXT = {
    AttachmentState.SELECTED_LOCALLY: "Selected locally",
    AttachmentState.UPLOADING: "Uploading\u2026",
    AttachmentState.UPLOADED: "Uploaded",
    AttachmentState.FAILED: "Upload failed \u00b7 Retry",
    AttachmentState.REMOVED: "Removed",
    AttachmentState.UNSUPPORTED: "Unsupported",
    AttachmentState.TOO_LARGE: "Too large",
}


class TaskStateBlock(QFrame):
    """Lightweight agent task strip (Home + Chat / Work)."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("homeTaskState")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)
        self._status = QLabel("Working", self)
        self._status.setObjectName("agentStatus")
        layout.addWidget(self._status)
        self._task = QLabel(self)
        self._task.setObjectName("textPrimary")
        self._task.setWordWrap(True)
        layout.addWidget(self._task, 1)
        self.setVisible(False)

    def set_task(self, title: str) -> None:
        self._task.setText(title)

    def set_status(self, status: str) -> None:
        self._status.setText(status)

    def text(self) -> str:
        return self._status.text() + " " + self._task.text()


class ActivityRow(QWidget):
    """One activity row: icon + text (07 9, min height 36)."""

    def __init__(
        self,
        tokens: DesignTokens,
        item: ActivityItem,
        parent: QWidget,
        *,
        theme: QtTheme = QtTheme.LIGHT,
    ) -> None:
        super().__init__(parent)
        self._item = item
        self._tokens = tokens
        self.setObjectName("activityRow")
        self.setMinimumHeight(
            int(tokens.component["dashboard"]["chat_work"][
                "activity_row_min_height"
            ])
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self._icon = QLabel(self)
        self._icon.setObjectName("agentStatus")
        action_size = int(tokens.icon["action"])
        self._icon.setFixedSize(action_size, action_size)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._icon)
        self._text = QLabel(item.text, self)
        self._text.setObjectName("textPrimary")
        self._text.setWordWrap(True)
        layout.addWidget(self._text, 1)
        self._theme = QtTheme.LIGHT
        self._refresh()

    def set_theme(self, theme: QtTheme) -> None:
        if self._theme is theme:
            return
        self._theme = theme
        self._refresh()

    def icon_kind(self) -> IconKind:
        return _ACTIVITY_KINDS[self._item.state]

    def icon_pixmap(self) -> object:
        pixmap = self._icon.pixmap()
        assert pixmap is not None
        return pixmap

    def _refresh(self) -> None:
        colors = self._tokens.theme(ThemeVariant(self._theme.value))
        color = _resolve_theme_color(colors, _ACTIVITY_COLOR_PATH[self._item.state])
        self._icon.setPixmap(
            icon_pixmap(
                _ACTIVITY_KINDS[self._item.state],
                int(self._tokens.icon["action"]),
                color,
                dpr=self.devicePixelRatioF(),
            )
        )

    def state(self) -> ActivityState:
        return self._item.state

    def text(self) -> str:
        return self._text.text()



class AttachmentChip(QWidget):
    """One attachment chip with all frozen states (07 9 Attachment)."""

    retry_requested = Signal(str)
    remove_requested = Signal(str)

    def __init__(
        self,
        tokens: DesignTokens,
        item: AttachmentItem,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self._item = item
        attachment = tokens.component["dashboard"]["attachment"]
        self.setObjectName(
            "attachChipFailed"
            if item.state is AttachmentState.FAILED
            else "attachChip"
        )
        self.setFixedHeight(int(attachment["chip_height"]))
        self.setMaximumWidth(int(attachment["chip_max_width"]))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            int(attachment["chip_horizontal_padding"]),
            0,
            int(attachment["chip_horizontal_padding"]),
            0,
        )
        layout.setSpacing(6)
        self._name = QLabel(item.name, self)
        self._name.setObjectName("textPrimary")
        layout.addWidget(self._name, 1)
        self._state = QLabel(self)
        self._state.setObjectName("textCaption")
        layout.addWidget(self._state)
        self._retry = QPushButton("Retry", self)
        self._retry.setObjectName("ghostButton")
        self._retry.setVisible(item.can_retry)
        self._retry.clicked.connect(
            lambda: self.retry_requested.emit(item.name)
        )
        layout.addWidget(self._retry)
        self._remove = QPushButton("\u00d7", self)
        self._remove.setObjectName("ghostButton")
        self._remove.setFixedSize(
            int(attachment["remove_hit_target"]),
            int(attachment["remove_hit_target"]),
        )
        self._remove.setAccessibleName(f"Remove {item.name}")
        self._remove.clicked.connect(
            lambda: self.remove_requested.emit(item.name)
        )
        layout.addWidget(self._remove)
        self._refresh_state()

    def _refresh_state(self) -> None:
        self._state.setText(_ATTACHMENT_STATE_TEXT[self._item.state])

    def name(self) -> str:
        return self._item.name

    def state(self) -> AttachmentState:
        return self._item.state

    def state_text(self) -> str:
        return self._state.text()

    def retry_button(self) -> QPushButton:
        return self._retry

    def remove_button(self) -> QPushButton:
        return self._remove
