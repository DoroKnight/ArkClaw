"""Offline-safe Qt runtime composition roots."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from arkclaw.application.active_turn_coordinator import (
    DefaultActiveTurnCoordinator,
)
from arkclaw.application.agent_loop import AgentLoop
from arkclaw.application.context_manager import ContextManager
from arkclaw.application.provider_profile_service import (
    ProviderFactoryBuilder,
    ProviderProfileService,
)
from arkclaw.application.provider_settings_service import (
    ProviderSettingsService,
)
from arkclaw.application.runtime_session_controller import (
    RuntimeEventSink,
    RuntimeSessionController,
)
from arkclaw.config.secrets import SecretStore
from arkclaw.domain.models import (
    FAKE_PROVIDER_ID,
    CredentialBinding,
    ProfileId,
    ProviderProfile,
)
from arkclaw.domain.ports import LLMProvider
from arkclaw.infrastructure.config.json_provider_profile_repository import (
    JsonProviderProfileRepository,
)
from arkclaw.infrastructure.llm.fake_provider import FakeProvider
from arkclaw.infrastructure.llm.provider_factory import ProviderFactory
from arkclaw.infrastructure.llm.provider_registry import (
    CredentialBindingRegistry,
)
from arkclaw.infrastructure.security.windows_credential_store import (
    WindowsCredentialSecretStore,
)

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


class _ProductionProviderFactoryBuilder(ProviderFactoryBuilder):
    def __init__(self, secret_store: SecretStore) -> None:
        self._secret_store = secret_store
        self._bindings: tuple[CredentialBinding, ...] = ()
        self._factory: ProviderFactory | None = None

    def initialize(
        self,
        credential_bindings: tuple[CredentialBinding, ...],
    ) -> None:
        """Create the reviewed registry/factory before runtime publication."""

        self._bindings = credential_bindings
        self._factory = self._build_factory(credential_bindings)

    def __call__(
        self,
        credential_bindings: tuple[CredentialBinding, ...],
    ) -> ProviderFactory:
        if self._factory is None or credential_bindings != self._bindings:
            self.initialize(credential_bindings)
        if self._factory is None:
            raise RuntimeError("The Provider factory is unavailable.")
        return self._factory

    def _build_factory(
        self,
        credential_bindings: tuple[CredentialBinding, ...],
    ) -> ProviderFactory:
        return ProviderFactory(
            self._secret_store,
            credential_bindings=CredentialBindingRegistry(
                credential_bindings
            ),
        )


class ProductionQtRuntimeCompositionRoot:
    """Create the production runtime graph inside RuntimeThread on demand."""

    def __init__(
        self,
        metadata_path: Path,
        *,
        secret_store_factory: Callable[[], SecretStore] = (
            WindowsCredentialSecretStore
        ),
    ) -> None:
        self._metadata_path = metadata_path
        self._secret_store_factory = secret_store_factory

    def __call__(
        self,
        event_sink: RuntimeEventSink,
        runtime_thread_id: int,
    ) -> RuntimeSessionController:
        repository = JsonProviderProfileRepository(self._metadata_path)
        secret_store = self._secret_store_factory()
        coordinator = DefaultActiveTurnCoordinator()
        factory_builder = _ProductionProviderFactoryBuilder(secret_store)
        settings_service = ProviderSettingsService(
            repository,
            factory_builder,
            secret_store,
            turn_coordinator=coordinator,
        )
        settings_service.ensure_builtin_metadata()
        factory_builder.initialize(
            repository.list_credential_bindings()
        )
        return RuntimeSessionController(
            settings_service,
            coordinator,
            lambda provider: AgentLoop(provider, ContextManager()),
            event_sink,
            runtime_thread_id=runtime_thread_id,
        )


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
