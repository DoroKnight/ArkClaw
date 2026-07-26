"""Offline-safe Qt runtime composition roots."""

from __future__ import annotations

from pathlib import Path

from sjtuclaw.application.active_turn_coordinator import (
    DefaultActiveTurnCoordinator,
)
from sjtuclaw.application.agent_loop import AgentLoop
from sjtuclaw.application.context_manager import ContextManager
from sjtuclaw.application.provider_profile_service import (
    ProviderFactoryBuilder,
    ProviderProfileService,
)
from sjtuclaw.application.runtime_session_controller import (
    RuntimeEventSink,
    RuntimeSessionController,
)
from sjtuclaw.domain.models import (
    FAKE_PROVIDER_ID,
    CredentialBinding,
    ProfileId,
    ProviderProfile,
)
from sjtuclaw.domain.ports import LLMProvider
from sjtuclaw.infrastructure.config.json_provider_profile_repository import (
    JsonProviderProfileRepository,
)
from sjtuclaw.infrastructure.llm.fake_provider import FakeProvider

QT_SMOKE_SECONDARY_PROFILE_ID = ProfileId(
    "11111111-1111-4111-8111-111111111111"
)


class _FakeOnlyProviderFactory:
    def create_profile(
        self,
        profile: ProviderProfile,
        *,
        timeout_seconds: float,
        max_retries: int,
        stream: bool,
    ) -> LLMProvider:
        del timeout_seconds, max_retries, stream
        if profile.provider_id != FAKE_PROVIDER_ID:
            raise ValueError("The offline Qt root supports Fake only.")
        return FakeProvider(response_text="qt-runtime-ok", chunk_size=4)


class _FakeOnlyProviderFactoryBuilder(ProviderFactoryBuilder):
    def __call__(
        self,
        credential_bindings: tuple[CredentialBinding, ...],
    ) -> _FakeOnlyProviderFactory:
        del credential_bindings
        return _FakeOnlyProviderFactory()


class FakeQtRuntimeCompositionRoot:
    """Build the entire offline runtime graph inside RuntimeThread."""

    def __init__(self, metadata_path: Path) -> None:
        self._metadata_path = metadata_path

    def __call__(
        self,
        event_sink: RuntimeEventSink,
        runtime_thread_id: int,
    ) -> RuntimeSessionController:
        repository = JsonProviderProfileRepository(self._metadata_path)
        coordinator = DefaultActiveTurnCoordinator()
        service = ProviderProfileService(
            repository,
            _FakeOnlyProviderFactoryBuilder(),
            turn_coordinator=coordinator,
        )
        service.ensure_builtin_metadata()
        if (
            service.get_profile(QT_SMOKE_SECONDARY_PROFILE_ID)
            is None
        ):
            service.create_profile(
                provider_id=FAKE_PROVIDER_ID,
                profile_id=QT_SMOKE_SECONDARY_PROFILE_ID,
                display_name="Qt Smoke Secondary Fake",
                model="fake",
            )
        return RuntimeSessionController(
            service,
            coordinator,
            lambda provider: AgentLoop(provider, ContextManager()),
            event_sink,
            runtime_thread_id=runtime_thread_id,
        )
