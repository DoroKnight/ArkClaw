"""Dashboard Character Animation page (Slice 7E - Workbench Redesign).

Authority: 07 section 10 and tokens component.dashboard.character_animation /
character_model / motion.character_switch: Workbench two-column architecture,
Preview preferred 640x480 / min 560x360, Character card 144x176, Animation card 168x104,
control height 44.  The page is a pure presentation surface: it renders a
:class:`~arkclaw.presentation.dashboard_presentation.CharacterAnimationSnapshot`
and emits narrow selection intents.  "Active Character" is the product term;
all character names and actions are snapshot-driven.  Animation inventory is
capability-driven and unsupported / trigger-unavailable cards carry a readable
disabled reason.  The preview is a labeled placeholder until the real Spine
presentation seam is available ("Visual placeholder"); the switch crossfade is
180 ms, cancelable, and degrades to 60 ms under reduced motion - never semantic truth.
"""

from __future__ import annotations

import math
import random
from contextlib import suppress

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QHideEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QRadialGradient,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from arkclaw.application.pet.pet_animation import (
    PetAnimationEngine,
    SystemMonotonicClock,
)
from arkclaw.application.pet.pet_geometry import Point, Rect, Size
from arkclaw.application.pet.pet_motion import PetMotionConfig, PetMotionModel
from arkclaw.application.pet.pet_production_actions import (
    ActionSource,
    ProductionAction,
)
from arkclaw.application.pet.pet_render_layout import PetRenderLayout
from arkclaw.application.pet.pet_renderer_model import action_request_for_frame
from arkclaw.bootstrap.pet_production import (
    ProductionPetComposition,
    create_optional_production_pet_composition,
)
from arkclaw.presentation.dashboard_presentation import (
    AnimationItem,
    AnimationState,
    CharacterAnimationSnapshot,
)
from arkclaw.presentation.qt.theme.design_tokens import (
    DesignTokens,
    load_design_tokens,
)
from arkclaw.presentation.qt.theme.qt_theme import QtTheme, motion_enabled

_ANIMATION_STATE_TEXT = {
    AnimationState.IDLE: "Idle",
    AnimationState.PREVIEWING: "Previewing",
    AnimationState.PLAYING: "Playing",
    AnimationState.UNSUPPORTED: "Unsupported",
    AnimationState.TRIGGER_UNAVAILABLE: "Trigger unavailable",
}


class _SpinePreviewWidget(QWidget):
    """Live Spine 3.8 preview widget embedded into the Workbench Showcase Stage."""

    def __init__(
        self,
        composition: ProductionPetComposition,
        parent: QWidget | None = None,
    ) -> None:
        self._disposed = False
        self._initialized = False
        self._composition = composition
        self._renderer = composition.renderer
        self._track0 = composition.track0
        self._playback_event_source = composition.playback_event_source
        self._current_layout: PetRenderLayout | None = None
        super().__init__(parent)
        self.setObjectName("spinePreviewWidget")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self.setMinimumSize(320, 240)

        motion = PetMotionModel(
            Point(0.0, 0.0),
            Size(160.0, 180.0),
            config=PetMotionConfig(walking_stride_pixels=0.001),
        )
        self._clock = SystemMonotonicClock()
        self._last_tick = self._clock.now()
        self._animation = PetAnimationEngine(
            motion,
            rng=random.Random(42),
            config=None,
            track0=self._track0,
            autonomous_scheduler=None,
            clock=self._clock,
            use_relax_motion_fallback=True,
        )

        self._last_dpr = float(self.devicePixelRatioF())
        self._renderer.set_device_pixel_ratio(self._last_dpr)
        self._renderer.initialize(Size(160.0, 180.0))
        self._renderer.set_state(action_request_for_frame(self._animation.frame))
        self._initialized = True

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._on_tick)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not getattr(self, "_initialized", False):
            return
        self._last_tick = self._clock.now()
        if hasattr(self, "_timer") and not self._timer.isActive():
            self._timer.start()

    def hideEvent(self, event: QHideEvent) -> None:
        super().hideEvent(event)
        if hasattr(self, "_timer"):
            self._timer.stop()

    def _on_tick(self) -> None:
        if (
            getattr(self, "_disposed", False)
            or not getattr(self, "_initialized", False)
            or not self.isVisible()
        ):
            return
        dpr = float(self.devicePixelRatioF())
        if not math.isclose(dpr, self._last_dpr):
            self._last_dpr = dpr
            self._renderer.set_device_pixel_ratio(dpr)
        now = self._clock.now()
        elapsed = max(0.0, now - self._last_tick)
        self._last_tick = now
        workspace = Rect(-10000.0, 0.0, 20000.0, 180.0)
        snapshot = self._animation.advance(elapsed, (workspace,))
        if self._playback_event_source is not None:
            try:
                events = self._playback_event_source.update(
                    snapshot.applied_delta_seconds
                )
                for event in events:
                    self._animation.handle_playback_event(event)
            except Exception:
                pass

        request = action_request_for_frame(snapshot.frame)
        self._renderer.set_state(request)

        stage_w = max(320.0, float(self.width()))
        stage_h = max(240.0, float(self.height()))
        center_x = stage_w / 2.0
        baseline_y = stage_h * 0.76
        body_x = center_x - 80.0
        body_y = baseline_y - 180.0
        body_rect = Rect(body_x, body_y, 160.0, 180.0)
        stage_workspace = Rect(
            0.0,
            0.0,
            stage_w,
            stage_h + 400.0,
        )

        try:
            layout = self._renderer.plan_layout(
                body_rect, stage_workspace, dpr, display=stage_workspace
            )
            if hasattr(layout, "surface_rect"):
                self._renderer.set_render_layout(layout)
                self._current_layout = layout
            else:
                self._current_layout = None
        except Exception:
            self._current_layout = None

        self._renderer.update(snapshot.applied_delta_seconds)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        if (
            getattr(self, "_disposed", False)
            or not getattr(self, "_initialized", False)
            or not self.isVisible()
        ):
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        stage_w = max(320.0, float(self.width()))
        stage_h = max(240.0, float(self.height()))
        center_x = stage_w / 2.0
        baseline_y = stage_h * 0.76

        # Draw aesthetic pedestal shadow under feet
        shadow_rect = QRectF(center_x - 65.0, baseline_y - 8.0, 130.0, 16.0)
        gradient = QRadialGradient(center_x, baseline_y, 65.0)
        gradient.setColorAt(0.0, QColor(0, 0, 0, 45))
        gradient.setColorAt(0.7, QColor(0, 0, 0, 18))
        gradient.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setBrush(QBrush(gradient))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(shadow_rect)

        layout = self._current_layout
        if layout is not None:
            try:
                drawn_img = self._renderer._backend.render_scene()
                painter.drawImage(
                    round(layout.surface_rect.x),
                    round(layout.surface_rect.y),
                    drawn_img,
                )
            except Exception:
                self._renderer.render_surface(painter)
        else:
            self._renderer.render_surface(painter)
        painter.end()

    def play_action(self, action_id: str) -> None:
        if getattr(self, "_disposed", False) or not hasattr(self, "_animation"):
            return
        action_map = {
            "relax": ProductionAction.RELAX,
            "move_left": ProductionAction.MOVE_LEFT,
            "move_right": ProductionAction.MOVE_RIGHT,
            "sit": ProductionAction.SIT,
            "sleep": ProductionAction.SLEEP,
            "special": ProductionAction.SPECIAL,
            "interact": ProductionAction.INTERACT,
        }
        action = action_map.get(action_id.lower())
        if action is not None:
            self._animation.request_action(
                action, ActionSource.USER
            )
            request = action_request_for_frame(self._animation.frame)
            self._renderer.set_state(request)
            self.update()

    def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        self._timer.stop()
        with suppress(Exception):
            self._renderer.close()
        self.deleteLater()


class _PreviewFrame(QFrame):
    """Frozen Spine Preview frame: preferred 640x480, minimum 560x360."""

    def __init__(
        self,
        tokens: DesignTokens,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        preview = tokens.component["dashboard"]["character_animation"]
        self._preferred = QSize(
            int(preview["preview_preferred_width"]),
            int(preview["preview_preferred_height"]),
        )
        self.setMinimumSize(
            int(preview["preview_min_width"]),
            int(preview["preview_min_height"]),
        )
        self.setObjectName("previewFrame")

    def sizeHint(self) -> QSize:
        return QSize(self._preferred)


class _StageBackgroundWidget(QWidget):
    """Visual backdrop container for the Stage showcase."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("stageBackgroundWidget")


class _StageFrame(QFrame):
    """Composite showcase stage holding the backdrop, viewport, and overlay controls."""

    def __init__(
        self,
        tokens: DesignTokens,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("stageFrame")
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )


def _clear_layout(layout: QGridLayout | QHBoxLayout | QVBoxLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item is None:
            continue
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()


class _CharacterCard(QFrame):
    """One Available Character card (frozen 144 x 176)."""

    switch_requested = Signal(str)

    def __init__(
        self,
        tokens: DesignTokens,
        name: str,
        *,
        is_current: bool,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self._tokens = tokens
        self._name = name
        self._selected = False
        character = tokens.component["dashboard"]["character_animation"]
        self.setObjectName("characterCard")
        self.setFixedSize(
            int(character["character_card_width"]),
            int(character["character_card_height"]),
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)
        self._name_label = QLabel(name, self)
        self._name_label.setObjectName("textPrimary")
        self._name_label.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
        )
        self._name_label.setWordWrap(True)
        layout.addWidget(self._name_label)
        self._current_marker = QLabel("Current" if is_current else "", self)
        self._current_marker.setObjectName("agentStatus")
        self._current_marker.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._current_marker)
        self._selected_marker = QLabel("", self)
        self._selected_marker.setObjectName("textCaption")
        self._selected_marker.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._selected_marker)
        layout.addStretch(1)
        self._switch = QPushButton("Switch", self)
        self._switch.setObjectName("secondaryButton")
        self._switch.setEnabled(not is_current)
        self._switch.setAccessibleName(f"Switch to {name}")
        self._switch.setToolTip(f"Switch active companion to {name}")
        self._switch.clicked.connect(lambda: self.switch_requested.emit(name))
        layout.addWidget(self._switch)

    def name_label(self) -> QLabel:
        return self._name_label

    def current_marker(self) -> QLabel:
        return self._current_marker

    def is_current(self) -> bool:
        return self._current_marker.text().strip() == "Current"

    def switch_button(self) -> QPushButton:
        return self._switch

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.setProperty("selected", "true" if selected else "false")
        self._selected_marker.setText("✓ Selected" if selected else "")
        self.style().unpolish(self)
        self.style().polish(self)

    def is_selected(self) -> bool:
        return self._selected


_ACTION_METADATA: dict[str, tuple[str, str]] = {
    "relax": ("☕", "Idle & Rest"),
    "move_left": ("◀", "Walk Left"),
    "move_right": ("▶", "Walk Right"),
    "sit": ("🪑", "Take a Seat"),
    "sleep": ("🌙", "Deep Rest"),
    "special": ("⚡", "Signature Skill"),
    "interact": ("💬", "Touch & React"),
}


class _AnimationCard(QFrame):
    """One capability-driven animation card (rich action row with icon and subtitle)."""

    preview_requested = Signal(str)
    play_requested = Signal(str)
    trigger_requested = Signal(str)

    def __init__(
        self,
        tokens: DesignTokens,
        item: AnimationItem,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self._tokens = tokens
        self._item = item
        self._selected = False
        self.setObjectName("animationCard")
        self.setFixedHeight(48)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 12, 6)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        icon_char, subtitle_text = _ACTION_METADATA.get(
            item.action_id.lower(), ("✨", "Action")
        )

        # 1. Left Icon Badge (32x32)
        self._icon_badge = QFrame(self)
        self._icon_badge.setObjectName("animIconBadge")
        self._icon_badge.setFixedSize(32, 32)
        badge_layout = QVBoxLayout(self._icon_badge)
        badge_layout.setContentsMargins(0, 0, 0, 0)
        badge_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_label = QLabel(icon_char, self._icon_badge)
        self._icon_label.setObjectName("animIconLabel")
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge_layout.addWidget(self._icon_label)
        layout.addWidget(self._icon_badge)

        # 2. Text Column (Name + Subtitle)
        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(1)
        text_col.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self._name_label = QLabel(item.name, self)
        self._name_label.setObjectName("textPrimary")
        text_col.addWidget(self._name_label)

        self._subtitle_label = QLabel(subtitle_text, self)
        self._subtitle_label.setObjectName("animSubtitle")
        text_col.addWidget(self._subtitle_label)

        self._reason_label = QLabel(self)
        self._reason_label.setObjectName("textCaption")
        self._reason_label.setVisible(item.disabled_reason is not None)
        if item.disabled_reason is not None:
            self._reason_label.setText(item.disabled_reason)
            self._subtitle_label.hide()
            self.setToolTip(f"{item.name} · {item.disabled_reason}")
        text_col.addWidget(self._reason_label)
        layout.addLayout(text_col, 1)

        # 3. Right Status / Indicator Badge
        self._indicator_label = QLabel("▶", self)
        self._indicator_label.setObjectName("animIndicator")
        self._indicator_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._indicator_label)

        # Hidden state labels and buttons preserved for tests and programmatic access
        self._state_label = QLabel(
            _ANIMATION_STATE_TEXT[item.state], self
        )
        self._state_label.setObjectName("agentStatus")
        self._state_label.hide()
        self._state_label.setVisible(False)
        self._preview = QPushButton("Preview", self)
        self._play = QPushButton("Play", self)
        self._trigger = QPushButton("Trigger on Desktop", self)
        for button in (self._preview, self._play, self._trigger):
            button.setObjectName("ghostButton")
            button.hide()
            button.setVisible(False)
        self._preview.setAccessibleName(f"Preview {item.name}")
        self._play.setAccessibleName(f"Play {item.name}")
        self._trigger.setAccessibleName(f"Trigger {item.name} on Desktop")
        self._trigger.setToolTip(f"Trigger {item.name} on the active desktop pet")
        self._preview.clicked.connect(
            lambda: self.preview_requested.emit(item.action_id)
        )
        self._play.clicked.connect(
            lambda: self.play_requested.emit(item.action_id)
        )
        self._trigger.clicked.connect(
            lambda: self.trigger_requested.emit(item.action_id)
        )
        self._refresh_enabled()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        super().mousePressEvent(event)
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._item.state is not AnimationState.UNSUPPORTED
        ):
            self.preview_requested.emit(self._item.action_id)

    def _refresh_enabled(self) -> None:
        unsupported = self._item.state is AnimationState.UNSUPPORTED
        trigger_unavailable = (
            self._item.state is AnimationState.TRIGGER_UNAVAILABLE
        )
        self.setEnabled(not unsupported)
        self._preview.setEnabled(not unsupported)
        self._play.setEnabled(not unsupported)
        self._trigger.setEnabled(
            not unsupported and not trigger_unavailable
        )

    def name_label(self) -> QLabel:
        return self._name_label

    def state_label(self) -> QLabel:
        return self._state_label

    def disabled_reason_label(self) -> QLabel:
        return self._reason_label

    def preview_button(self) -> QPushButton:
        return self._preview

    def play_button(self) -> QPushButton:
        return self._play

    def trigger_button(self) -> QPushButton:
        return self._trigger

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.setProperty("selected", "true" if selected else "false")
        self.style().unpolish(self)
        self.style().polish(self)
        for child in self.findChildren(QWidget):
            child.style().unpolish(child)
            child.style().polish(child)

    def is_selected(self) -> bool:
        return self._selected

    def action_id(self) -> str:
        return self._item.action_id


class CharacterAnimationPage(QWidget):
    """Two-column Character Animation Workbench: Header + Control Sidebar + Showcase Stage."""

    character_selected = Signal(str)
    animation_preview_requested = Signal(str)
    animation_play_requested = Signal(str)
    animation_trigger_requested = Signal(str)
    preview_retry_requested = Signal()

    def __init__(
        self,
        tokens: DesignTokens | None = None,
        parent: QWidget | None = None,
        *,
        enable_live_preview: bool = False,
        composition: ProductionPetComposition | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens = tokens if tokens is not None else load_design_tokens()
        self._disposed = False
        character = self._tokens.component["dashboard"]["character_animation"]
        window_tokens = self._tokens.component["dashboard"]["window"]
        self._page_gutter = int(window_tokens["page_gutter"])
        self._compact_gutter = int(window_tokens["compact_gutter"])
        self._preview_gap = int(self._tokens.spacing["character_preview_gap"])
        self._content_max_width = int(character["page_content_max_width"])
        self._character_card_size = (
            int(character["character_card_width"]),
            int(character["character_card_height"]),
        )
        self._animation_card_size = (
            int(character["animation_card_width"]),
            int(character["animation_card_height"]),
        )
        self._grid_gap = int(character["grid_gap"])
        self._preview_controls_gap = int(
            character["preview_controls_gap"]
        )
        self._preview_control_height = int(
            character["preview_control_height"]
        )
        self.setObjectName("characterAnimationPage")

        self._character_cards: list[_CharacterCard] = []
        self._animation_cards: list[_AnimationCard] = []
        self._selected_animation: _AnimationCard | None = None
        self._switch_animation: QPropertyAnimation | None = None
        self._switch_effect: QGraphicsOpacityEffect | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            self._page_gutter,
            self._compact_gutter,
            self._page_gutter,
            self._preview_gap,
        )
        outer.setSpacing(12)

        # -- Header Section ----------------------------------------------------
        self._header_title = QLabel(
            self._tokens.product_term, self
        )
        self._header_title.setObjectName("pageTitle")
        outer.addWidget(self._header_title)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(12)
        self._header_name = QLabel(self)
        self._header_name.setObjectName("sectionTitle")
        header_row.addWidget(self._header_name)
        self._header_subtitle = QLabel(self)
        self._header_subtitle.setObjectName("textSecondary")
        header_row.addWidget(self._header_subtitle)
        self._header_reference = QLabel(self)
        self._header_reference.setObjectName("textCaption")
        self._header_reference.setVisible(False)
        header_row.addWidget(self._header_reference)
        header_row.addStretch(1)
        outer.addLayout(header_row)

        # -- Workbench Two-Column Body ------------------------------------------
        self._body = QHBoxLayout()
        self._body.setContentsMargins(0, 0, 0, 0)
        self._body.setSpacing(self._grid_gap)
        outer.addLayout(self._body, 1)

        # -- Left Control Sidebar (240-280px) ----------------------------------
        self._sidebar_widget = QWidget(self)
        self._sidebar_widget.setObjectName("sidebarWidget")
        self._sidebar_widget.setMinimumWidth(220)
        self._sidebar_widget.setMaximumWidth(280)
        sidebar_layout = QVBoxLayout(self._sidebar_widget)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(12)

        # 1. Character Surface (Top of sidebar)
        self._character_surface = QWidget(self._sidebar_widget)
        self._character_surface.setObjectName("characterSurface")
        char_surface_layout = QVBoxLayout(self._character_surface)
        char_surface_layout.setContentsMargins(12, 12, 12, 12)
        char_surface_layout.setSpacing(8)
        self._selector_title = QLabel("Available Characters", self._character_surface)
        self._selector_title.setObjectName("sectionTitle")
        char_surface_layout.addWidget(self._selector_title)
        self._selector_empty = QLabel(
            "No other characters available", self._character_surface
        )
        self._selector_empty.setObjectName("textSecondary")
        self._selector_empty.setVisible(False)
        char_surface_layout.addWidget(self._selector_empty)
        self._character_grid = QGridLayout()
        self._character_grid.setContentsMargins(0, 0, 0, 0)
        self._character_grid.setHorizontalSpacing(self._grid_gap)
        self._character_grid.setVerticalSpacing(self._grid_gap)
        self._character_grid.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
        )
        char_surface_layout.addLayout(self._character_grid)
        sidebar_layout.addWidget(self._character_surface)

        # 2. Animation Selector Surface (Bottom of sidebar with scroll safety)
        self._animation_surface = QWidget(self._sidebar_widget)
        self._animation_surface.setObjectName("animationSurface")
        anim_surface_layout = QVBoxLayout(self._animation_surface)
        anim_surface_layout.setContentsMargins(12, 12, 12, 12)
        anim_surface_layout.setSpacing(8)
        self._inventory_title = QLabel("Animations", self._animation_surface)
        self._inventory_title.setObjectName("sectionTitle")
        anim_surface_layout.addWidget(self._inventory_title)
        self._inventory_empty = QLabel(
            "No animations available for this character", self._animation_surface
        )
        self._inventory_empty.setObjectName("textSecondary")
        self._inventory_empty.setVisible(False)
        anim_surface_layout.addWidget(self._inventory_empty)

        self._animation_scroll = QScrollArea(self._animation_surface)
        self._animation_scroll.setObjectName("animationScrollArea")
        self._animation_scroll.setWidgetResizable(True)
        self._animation_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._animation_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._animation_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._animation_scroll.setStyleSheet(
            "background: transparent; border: none;"
        )
        self._animation_scroll.viewport().setStyleSheet(
            "background: transparent; border: none;"
        )
        self._animation_container = QWidget(self._animation_scroll)
        self._animation_container.setObjectName("animationContainer")
        self._animation_container.setStyleSheet(
            "background: transparent; border: none;"
        )
        self._animation_grid = QVBoxLayout(self._animation_container)
        self._animation_grid.setContentsMargins(0, 0, 0, 0)
        self._animation_grid.setSpacing(6)
        self._animation_grid.setAlignment(
            Qt.AlignmentFlag.AlignTop
        )
        self._animation_scroll.setWidget(self._animation_container)
        anim_surface_layout.addWidget(self._animation_scroll, 1)
        sidebar_layout.addWidget(self._animation_surface, 1)

        self._body.addWidget(self._sidebar_widget, 0)

        # -- Right Showcase Stage ----------------------------------------------
        self._stage_frame = _StageFrame(self._tokens, self)
        stage_layout = QVBoxLayout(self._stage_frame)
        stage_layout.setContentsMargins(16, 16, 16, 16)
        stage_layout.setSpacing(12)

        # 1. Spine Preview Viewport
        self._preview_frame = _PreviewFrame(self._tokens, self._stage_frame)
        self._preview_layout = QVBoxLayout(self._preview_frame)
        self._preview_layout.setContentsMargins(0, 0, 0, 0)
        self._preview_layout.setSpacing(0)
        self._preview_placeholder = QLabel(
            self._tokens.character_model["placeholder_label"], self._preview_frame
        )
        self._preview_placeholder.setObjectName("textCaption")
        self._preview_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_layout.addWidget(self._preview_placeholder, 1)

        self._live_preview_enabled = enable_live_preview
        self._pending_composition = composition
        self._spine_widget: _SpinePreviewWidget | None = None
        if enable_live_preview and composition is not None:
            try:
                self.attach_live_composition(composition)
            except Exception:
                self._spine_widget = None

        self._preview_status = QLabel(self._preview_frame)
        self._preview_status.setObjectName("agentStatus")
        self._preview_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_status.setVisible(False)
        self._preview_layout.addWidget(self._preview_status)
        self._preview_retry = QPushButton("Retry", self._preview_frame)
        self._preview_retry.setObjectName("secondaryButton")
        self._preview_retry.setVisible(False)
        self._preview_retry.clicked.connect(
            self.preview_retry_requested.emit
        )
        retry_row = QHBoxLayout()
        retry_row.setContentsMargins(0, 0, 0, 0)
        retry_row.addStretch(1)
        retry_row.addWidget(self._preview_retry)
        retry_row.addStretch(1)
        self._preview_layout.addLayout(retry_row)
        stage_layout.addWidget(self._preview_frame, 1)

        # 2. Control Strip (Bottom Overlay)
        self._control_strip = QWidget(self._stage_frame)
        self._control_strip.setObjectName("stageControlStrip")
        self._control_strip.setFixedHeight(self._preview_control_height)
        strip_layout = QHBoxLayout(self._control_strip)
        strip_layout.setContentsMargins(0, 0, 0, 0)
        strip_layout.setSpacing(12)
        strip_layout.addStretch(1)
        self._strip_preview = QPushButton("Preview", self._control_strip)
        self._strip_play = QPushButton("Play", self._control_strip)
        self._strip_trigger = QPushButton(
            "Trigger on Desktop", self._control_strip
        )
        self._strip_preview.setObjectName("secondaryButton")
        self._strip_play.setObjectName("secondaryButton")
        self._strip_trigger.setObjectName("primaryButton")
        for button in (
            self._strip_preview,
            self._strip_play,
            self._strip_trigger,
        ):
            button.setEnabled(False)
            button.setMinimumHeight(self._preview_control_height)
        self._strip_preview.setAccessibleName("Preview active animation")
        self._strip_preview.setToolTip("Restart loop preview on stage")
        self._strip_play.setAccessibleName("Play active animation once")
        self._strip_play.setToolTip("Play selected animation once on stage")
        self._strip_trigger.setAccessibleName("Trigger active animation on Desktop")
        self._strip_trigger.setToolTip("Trigger this animation on the active desktop pet")
        self._strip_preview.clicked.connect(
            lambda: self._strip_action("preview")
        )
        self._strip_play.clicked.connect(
            lambda: self._strip_action("play")
        )
        self._strip_trigger.clicked.connect(
            lambda: self._strip_action("trigger")
        )
        strip_layout.addWidget(self._strip_preview)
        strip_layout.addWidget(self._strip_play)
        strip_layout.addWidget(self._strip_trigger)
        strip_layout.addStretch(1)
        stage_layout.addWidget(self._control_strip, 0)

        self._body.addWidget(self._stage_frame, 1)

    def attach_live_composition(
        self, composition: ProductionPetComposition
    ) -> None:
        if self._spine_widget is not None:
            return
        self._spine_widget = _SpinePreviewWidget(
            composition, self._preview_frame
        )
        self._preview_layout.insertWidget(
            0, self._spine_widget, 1
        )
        self._preview_placeholder.hide()
        self._preview_placeholder.setVisible(False)

    # -- frozen geometry -----------------------------------------------------
    def content_max_width(self) -> int:
        return self._content_max_width

    def character_card_size(self) -> tuple[int, int]:
        return self._character_card_size

    def animation_card_size(self) -> tuple[int, int]:
        return self._animation_card_size

    def grid_gap(self) -> int:
        return self._grid_gap

    def preview_controls_gap(self) -> int:
        return self._preview_controls_gap

    def preview_control_height(self) -> int:
        return self._preview_control_height

    def switch_crossfade_duration_ms(self) -> int:
        if motion_enabled():
            return int(
                self._tokens.motion["character_switch"]["duration_ms"]
            )
        return int(self._tokens.motion["reduced_motion_crossfade_ms"])

    # -- accessors ------------------------------------------------------------
    def header_title(self) -> QLabel:
        return self._header_title

    def header_name_label(self) -> QLabel:
        return self._header_name

    def header_reference_label(self) -> QLabel:
        return self._header_reference

    def character_cards(self) -> list[_CharacterCard]:
        return list(self._character_cards)

    def character_selector_empty_label(self) -> QLabel:
        return self._selector_empty

    def character_switch_button(self, index: int) -> QPushButton:
        return self._character_cards[index].switch_button()

    def preview_frame(self) -> QFrame:
        return self._preview_frame

    def preview_placeholder_label(self) -> QLabel:
        return self._preview_placeholder

    def preview_status_label(self) -> QLabel:
        return self._preview_status

    def preview_retry_button(self) -> QPushButton:
        return self._preview_retry

    def preview_control_strip(self) -> QWidget:
        return self._control_strip

    def strip_preview_button(self) -> QPushButton:
        return self._strip_preview

    def strip_play_button(self) -> QPushButton:
        return self._strip_play

    def strip_trigger_button(self) -> QPushButton:
        return self._strip_trigger

    def animation_cards(self) -> list[_AnimationCard]:
        return list(self._animation_cards)

    def selected_card(self) -> _AnimationCard | None:
        return self._selected_animation

    def preview_crossfade_active(self) -> bool:
        animation = self._switch_animation
        if animation is None:
            return False
        return (
            animation.state() == QAbstractAnimation.State.Running
        )

    # -- presentation -----------------------------------------------------------
    def apply_snapshot(self, snapshot: CharacterAnimationSnapshot) -> None:
        self._apply_header(snapshot)
        self._rebuild_characters(snapshot)
        self._apply_preview(snapshot)
        self._rebuild_animations(snapshot)
        self._refresh_strip_state()

    def _apply_header(self, snapshot: CharacterAnimationSnapshot) -> None:
        summary = snapshot.active_character
        display_name = summary.display_name or "Active Character"
        self._header_name.setText(display_name)
        self._header_subtitle.setText("· Active Desktop Companion")
        reference = (
            summary.reference_name
            if summary.is_reference and summary.reference_name
            else None
        )
        if reference:
            self._header_reference.setText(
                f"Reference Character: {reference}"
            )
            self._header_reference.setVisible(True)
        else:
            self._header_reference.clear()
            self._header_reference.setVisible(False)

    def _rebuild_characters(
        self, snapshot: CharacterAnimationSnapshot
    ) -> None:
        _clear_layout(self._character_grid)
        self._character_cards.clear()
        current_name = snapshot.active_character.display_name
        for column, name in enumerate(snapshot.available_characters):
            card = _CharacterCard(
                self._tokens,
                name,
                is_current=(name == current_name),
                parent=self,
            )
            card.switch_requested.connect(self.character_selected)
            card.set_selected(False)
            self._character_grid.addWidget(card, 0, column)
            card.show()
            self._character_cards.append(card)
        self._selector_empty.setVisible(
            not snapshot.available_characters
        )
        self._selector_title.setVisible(bool(snapshot.available_characters))
        self._character_grid.setEnabled(bool(snapshot.available_characters))

    def _apply_preview(self, snapshot: CharacterAnimationSnapshot) -> None:
        if snapshot.preview_error:
            self._preview_status.setText(
                f"Renderer failure · {snapshot.preview_error}"
            )
            self._preview_status.setVisible(True)
            self._preview_retry.setVisible(True)
        elif snapshot.preview_loading:
            self._preview_status.setText("Loading…")
            self._preview_status.setVisible(True)
            self._preview_retry.setVisible(False)
        else:
            self._preview_status.clear()
            self._preview_status.setVisible(False)
            self._preview_retry.setVisible(False)
        if self._spine_widget is None:
            self._begin_switch_crossfade()
        else:
            self._preview_placeholder.hide()
            self._preview_placeholder.setVisible(False)

    def _rebuild_animations(
        self, snapshot: CharacterAnimationSnapshot
    ) -> None:
        _clear_layout(self._animation_grid)
        self._animation_cards.clear()
        prev_action_id = (
            self._selected_animation.action_id()
            if self._selected_animation is not None
            else None
        )
        self._selected_animation = None
        for item in snapshot.animations:
            card = _AnimationCard(self._tokens, item, self._animation_container)
            card.preview_requested.connect(
                self._on_card_preview_requested
            )
            card.play_requested.connect(self.animation_play_requested)
            card.trigger_requested.connect(
                self.animation_trigger_requested
            )
            self._animation_grid.addWidget(card)
            card.show()
            self._animation_cards.append(card)

        self._inventory_empty.setVisible(not snapshot.animations)
        self._inventory_title.setVisible(bool(snapshot.animations))

        # Preserve previous selection if present
        if prev_action_id is not None and self._animation_cards:
            for idx, card in enumerate(self._animation_cards):
                if card.action_id() == prev_action_id:
                    self.select_card(idx, emit_preview=False)
                    break

    def _on_card_preview_requested(self, action_id: str) -> None:
        for idx, card in enumerate(self._animation_cards):
            if card.action_id() == action_id:
                self.select_card(idx, emit_preview=False)
                break
        if self._spine_widget is not None:
            self._spine_widget.play_action(action_id)
        self.animation_preview_requested.emit(action_id)

    # -- selection + strip ------------------------------------------------------
    def select_card(self, index: int, *, emit_preview: bool = True) -> None:
        if not (0 <= index < len(self._animation_cards)):
            return
        for card in self._animation_cards:
            card.set_selected(False)
        selected = self._animation_cards[index]
        selected.set_selected(True)
        self._selected_animation = selected
        self._refresh_strip_state()
        if emit_preview and selected.preview_button().isEnabled():
            if self._spine_widget is not None:
                self._spine_widget.play_action(selected.action_id())
            self.animation_preview_requested.emit(selected.action_id())

    def _strip_action(self, action: str) -> None:
        selected = self._selected_animation
        if selected is None:
            return
        action_id = selected.action_id()
        if action in ("preview", "play") and self._spine_widget is not None:
            self._spine_widget.play_action(action_id)
        if action == "preview":
            self.animation_preview_requested.emit(action_id)
        elif action == "play":
            self.animation_play_requested.emit(action_id)
        elif action == "trigger":
            self.animation_trigger_requested.emit(action_id)

    def _refresh_strip_state(self) -> None:
        selected = self._selected_animation
        if selected is None:
            for button in (
                self._strip_preview,
                self._strip_play,
                self._strip_trigger,
            ):
                button.setEnabled(False)
            return
        self._strip_preview.setEnabled(
            selected.preview_button().isEnabled()
        )
        self._strip_play.setEnabled(selected.play_button().isEnabled())
        self._strip_trigger.setEnabled(
            selected.trigger_button().isEnabled()
        )

    # -- switch crossfade (cancelable, non-semantic) -----------------------------
    def _begin_switch_crossfade(self) -> None:
        self.cancel_switch_crossfade()
        duration = self.switch_crossfade_duration_ms()
        if duration <= 0:
            return
        effect = QGraphicsOpacityEffect(self._preview_placeholder)
        self._preview_placeholder.setGraphicsEffect(effect)
        effect.setOpacity(0.0)
        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(duration)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.start()
        self._switch_animation = animation
        self._switch_effect = effect

    def cancel_switch_crossfade(self) -> None:
        animation = self._switch_animation
        self._switch_animation = None
        if animation is not None:
            animation.stop()
            animation.deleteLater()
        if self._switch_effect is not None:
            self._preview_placeholder.setGraphicsEffect(None)  # type: ignore[arg-type]
            self._switch_effect = None

    def spine_preview_widget(self) -> _SpinePreviewWidget | None:
        return self._spine_widget

    def set_theme(self, theme: QtTheme) -> None:
        self._theme = theme
        self.style().unpolish(self)
        self.style().polish(self)
        for card in self._animation_cards:
            card.style().unpolish(card)
            card.style().polish(card)
        if self._spine_widget is not None:
            self._spine_widget.update()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._live_preview_enabled and self._spine_widget is None:
            try:
                live_comp = (
                    self._pending_composition
                    or create_optional_production_pet_composition()
                )
                if live_comp is not None:
                    self.attach_live_composition(live_comp)
            except Exception:
                self._spine_widget = None
        if self._spine_widget is not None:
            self._preview_placeholder.hide()

    # -- lifecycle --------------------------------------------------------------
    def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        self.cancel_switch_crossfade()
        if self._spine_widget is not None:
            self._spine_widget.dispose()
            self._spine_widget = None
        self.hide()
        self.deleteLater()


__all__ = ["CharacterAnimationPage"]
