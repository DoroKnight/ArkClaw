"""Production Desktop <-> Dashboard integration seam (Slice 7F).

Authority: 07 section 11 and 08 section 4 - one product, two presentations.
The Dashboard is a second top-level window that consumes the SAME
authoritative FrontendPresentationCoordinator (ConversationContext + draft);
it never creates a second draft model and never reaches into PetWindow.
Opening the Dashboard is a pure presentation transition: zero Conversation,
zero backend task, zero application command.  The integration lazily owns one
DashboardWindow, wires page signals to narrow coordinator-owned handlers
exactly once, and feeds snapshots that come from the presentation model (never
fabricated).  dispose() is idempotent and removes the owned top-level.
"""

from __future__ import annotations

from collections.abc import Callable

from arkclaw.presentation.conversation_draft_safety import DraftEditIntent
from arkclaw.presentation.dashboard_presentation import (
    ChatWorkSnapshot,
    DashboardPresentationModel,
)
from arkclaw.presentation.frontend_presentation import (
    ConversationOpenOrRestoreIntent,
)
from arkclaw.presentation.qt.dashboard.dashboard_page import DashboardPage
from arkclaw.presentation.qt.dashboard.dashboard_window import DashboardWindow
from arkclaw.presentation.qt.dashboard.pages.character_animation_page import (
    CharacterAnimationPage,
)
from arkclaw.presentation.qt.dashboard.pages.chat_work_page import ChatWorkPage
from arkclaw.presentation.qt.dashboard.pages.home_page import HomePage
from arkclaw.presentation.qt.frontend_presentation_coordinator import (
    FrontendPresentationCoordinator,
)
from arkclaw.presentation.qt.theme.design_tokens import (
    DesignTokens,
    load_design_tokens,
)


class DashboardIntegration:
    """Owns the production Dashboard window and its narrow page wiring."""

    def __init__(
        self,
        presentation: FrontendPresentationCoordinator,
        model: DashboardPresentationModel | None = None,
        *,
        tokens: DesignTokens | None = None,
        restore_character_handler: Callable[[], None] | None = None,
        autostart_controller: object | None = None,
        animation_trigger_handler: Callable[[str], None] | None = None,
    ) -> None:
        self._presentation = presentation
        self._model = (
            model if model is not None else DashboardPresentationModel()
        )
        self._tokens = tokens if tokens is not None else load_design_tokens()
        self._restore_character_handler = restore_character_handler
        self._autostart_controller = autostart_controller
        self._animation_trigger_handler = animation_trigger_handler
        self._window: DashboardWindow | None = None
        self._wired = False
        self._disposed = False

    # -- ownership -----------------------------------------------------------
    @property
    def window(self) -> DashboardWindow | None:
        """The lazily-created Dashboard window (None until first open)."""
        return self._window

    def open(self, page: DashboardPage | None = None) -> DashboardWindow:
        """Show the Dashboard (create once, reuse), optionally at ``page``."""
        window = self._ensure_window()
        self._sync_snapshots(window)
        if page is not None:
            window.select_page(page)
        window.show()
        window.raise_()
        window.activateWindow()
        return window

    def close(self) -> None:
        """Hide the Dashboard without destroying it."""
        window = self._window
        if window is not None:
            window.hide()

    def dispose(self) -> None:
        """Idempotent teardown: dispose the owned window and drop references."""
        if self._disposed:
            return
        self._disposed = True
        window = self._window
        self._window = None
        if window is not None:
            window.dispose()

    # -- internals -------------------------------------------------------------
    def _ensure_window(self) -> DashboardWindow:
        window = self._window
        if window is None:
            window = DashboardWindow(
                self._tokens,
                autostart_controller=self._autostart_controller,  # type: ignore[arg-type]
            )
            self._wire(window)
            self._window = window
        return window

    def _wire(self, window: DashboardWindow) -> None:
        if self._wired:
            return
        self._wired = True
        home = window.page_widget(DashboardPage.HOME)
        if isinstance(home, HomePage):
            home.ask_requested.connect(
                lambda: self._open_page(DashboardPage.CHAT_WORK)
            )
            home.start_chat_work_requested.connect(
                lambda: self._open_page(DashboardPage.CHAT_WORK)
            )
            home.explore_chat_work_requested.connect(
                lambda: self._select_page(DashboardPage.CHAT_WORK)
            )
            home.explore_character_animation_requested.connect(
                lambda: self._select_page(DashboardPage.CHARACTER_ANIMATION)
            )
            if self._restore_character_handler is not None:
                home.restore_character_requested.connect(
                    self._restore_character_handler
                )
        chat = window.page_widget(DashboardPage.CHAT_WORK)
        if isinstance(chat, ChatWorkPage):
            # Deliberate composer engagement opens/restores the ONE
            # authoritative ConversationContext (07 11, Slice 6B Ask trace):
            # without a context the model draft guard makes edits a no-op.
            chat.conversation_requested.connect(
                lambda: self._presentation.dispatch(
                    ConversationOpenOrRestoreIntent()
                )
            )
            chat.attach_draft_ports(
                draft_edit_handler=self._on_draft_edit,
                submit_handler=self._presentation.submit_draft,
                draft_snapshot_provider=(
                    lambda: self._presentation.draft_snapshot
                ),
            )
        character = window.page_widget(DashboardPage.CHARACTER_ANIMATION)
        if (
            isinstance(character, CharacterAnimationPage)
            and self._animation_trigger_handler is not None
        ):
            character.animation_trigger_requested.connect(
                self._animation_trigger_handler
            )

    def _open_page(self, page: DashboardPage) -> None:
        self.open(page)

    def _select_page(self, page: DashboardPage) -> None:
        window = self._window
        if window is not None:
            window.select_page(page)

    def _on_draft_edit(self, intent: DraftEditIntent) -> None:
        """Route one host edit to the authoritative model-owned draft."""
        self._presentation.apply_draft_edit(intent)

    def _sync_snapshots(self, window: DashboardWindow) -> None:
        home = window.page_widget(DashboardPage.HOME)
        if isinstance(home, HomePage):
            home.apply_snapshot(self._model.home)
        chat = window.page_widget(DashboardPage.CHAT_WORK)
        if isinstance(chat, ChatWorkPage):
            conversation = self._presentation.snapshot.conversation_context
            conversation_id = (
                conversation.context_id
                if conversation is not None
                else None
            )
            chat.apply_snapshot(ChatWorkSnapshot(conversation_id=conversation_id))
            chat.render_draft(self._presentation.draft_snapshot)
        character = window.page_widget(DashboardPage.CHARACTER_ANIMATION)
        if isinstance(character, CharacterAnimationPage):
            character.apply_snapshot(self._model.character)


__all__ = ["DashboardIntegration"]
