from __future__ import annotations

import asyncio
import logging
import traceback
from collections.abc import AsyncIterator, Iterator, Sequence
from dataclasses import replace
from pathlib import Path

import pytest
from tests.fakes.deepseek_sdk import FakeDeepSeekClientFactory
from tests.fakes.openai_sdk import FakeOpenAIClientFactory

from arkclaw.application.agent_loop import AgentLoop
from arkclaw.application.context_manager import ContextManager
from arkclaw.application.provider_profile_repository import (
    ProviderMetadataWriteError,
)
from arkclaw.application.provider_profile_service import (
    ActiveTurnCoordinator,
    ActiveTurnHandling,
    ProviderActivationOptions,
    ProviderLifecycleState,
    ProviderProfileService,
    ProviderProfileServiceError,
)
from arkclaw.config.provider_profile_policy import (
    builtin_managed_profiles,
)
from arkclaw.config.secrets import InMemorySecretStore
from arkclaw.domain.events import AgentEvent, AgentEventType, LLMEvent
from arkclaw.domain.models import (
    DEEPSEEK_DEFAULT_PROFILE_ID,
    DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID,
    DEEPSEEK_PROVIDER_ID,
    FAKE_DEFAULT_PROFILE_ID,
    FAKE_PROVIDER_ID,
    OPENAI_DEFAULT_PROFILE_ID,
    OPENAI_MANUAL_TEST_CREDENTIAL_ID,
    OPENAI_PROVIDER_ID,
    ApiProtocol,
    ChatMessage,
    CredentialBinding,
    CredentialId,
    Embedding,
    LLMRequest,
    MessageRole,
    ProfileId,
    ProviderCapabilities,
    ProviderContinuation,
    ProviderId,
    ProviderProfile,
    UserMessageCommand,
)
from arkclaw.domain.ports import LLMProvider
from arkclaw.infrastructure.config.json_provider_profile_repository import (
    JsonProviderProfileRepository,
)
from arkclaw.infrastructure.llm.provider_factory import ProviderFactory
from arkclaw.infrastructure.llm.provider_registry import (
    CredentialBindingRegistry,
)

_OPTIONS = ProviderActivationOptions(
    timeout_seconds=30.0,
    max_retries=0,
    stream=True,
)


class _RecordingProvider:
    def __init__(
        self,
        profile: ProviderProfile,
        events: list[str],
    ) -> None:
        self._profile = profile
        self._events = events
        self.closed = False
        self.fail_close = False
        self.close_failures_remaining = 0
        self.close_attempts = 0
        self.close_started: asyncio.Event | None = None
        self.close_release: asyncio.Event | None = None
        self.completion_continuation: ProviderContinuation | None = None
        self.name_override: str | None = None
        self.protocol_override: ApiProtocol | None = None
        self.generate_count = 0
        self.received_continuations: list[
            ProviderContinuation | None
        ] = []
        self.stream_closed_count = 0
        self.stream_started: asyncio.Event | None = None
        self.stream_release: asyncio.Event | None = None
        self.script: list[LLMEvent] | None = None

    @property
    def name(self) -> str:
        return self.name_override or self._profile.provider_id.value

    def capabilities(self) -> ProviderCapabilities:
        if self.protocol_override is not None:
            return replace(
                self._profile.capabilities,
                protocol=self.protocol_override,
            )
        return self._profile.capabilities

    async def generate_stream(
        self,
        request: LLMRequest,
    ) -> AsyncIterator[LLMEvent]:
        self.generate_count += 1
        self.received_continuations.append(request.continuation)
        if self.stream_started is not None:
            self.stream_started.set()
        try:
            if self.stream_release is not None:
                await self.stream_release.wait()
            events = self.script
            if events is None:
                events = [
                    LLMEvent.completed(self.completion_continuation)
                ]
            for event in events:
                yield event
        finally:
            self.stream_closed_count += 1

    async def embed(
        self,
        texts: Sequence[str],
    ) -> Sequence[Embedding]:
        del texts
        return ()

    async def aclose(self) -> None:
        self._events.append(f"close:{self._profile.profile_id.value}")
        self.close_attempts += 1
        if self.close_started is not None:
            self.close_started.set()
        if self.close_release is not None:
            await self.close_release.wait()
        if self.close_failures_remaining:
            self.close_failures_remaining -= 1
            raise RuntimeError("sensitive close failure")
        if self.fail_close:
            raise RuntimeError("sensitive close failure")
        self.closed = True


class _RecordingFactory:
    def __init__(self, owner: _RecordingFactoryBuilder) -> None:
        self._owner = owner

    def create_profile(
        self,
        profile: ProviderProfile,
        *,
        timeout_seconds: float,
        max_retries: int,
        stream: bool,
    ) -> LLMProvider:
        del timeout_seconds, max_retries, stream
        self._owner.create_count += 1
        self._owner.events.append(f"create:{profile.profile_id.value}")
        if self._owner.fail_on_create == self._owner.create_count:
            raise RuntimeError("sensitive factory failure")
        provider = _RecordingProvider(profile, self._owner.events)
        provider.name_override = self._owner.provider_name_override
        provider.protocol_override = self._owner.protocol_override
        provider.fail_close = self._owner.fail_candidate_close
        self._owner.providers.append(provider)
        return provider


class _RecordingFactoryBuilder:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.providers: list[_RecordingProvider] = []
        self.binding_snapshots: list[tuple[CredentialBinding, ...]] = []
        self.create_count = 0
        self.fail_on_create: int | None = None
        self.network_request_count = 0
        self.provider_name_override: str | None = None
        self.protocol_override: ApiProtocol | None = None
        self.fail_candidate_close = False

    def __call__(
        self,
        credential_bindings: tuple[CredentialBinding, ...],
    ) -> _RecordingFactory:
        self.binding_snapshots.append(credential_bindings)
        return _RecordingFactory(self)


class _Coordinator(ActiveTurnCoordinator):
    def __init__(
        self,
        events: list[str],
        *,
        started: asyncio.Event | None = None,
        release: asyncio.Event | None = None,
    ) -> None:
        self.events = events
        self.started = started
        self.release = release
        self.calls: list[
            tuple[ProfileId, ProfileId, ActiveTurnHandling]
        ] = []

    async def prepare_for_provider_switch(
        self,
        *,
        old_profile_id: ProfileId,
        new_profile_id: ProfileId,
        handling: ActiveTurnHandling,
    ) -> None:
        self.calls.append(
            (old_profile_id, new_profile_id, handling)
        )
        self.events.append(f"coordinate:{handling.value}")
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            await self.release.wait()


def _service(
    path: Path,
    builder: _RecordingFactoryBuilder,
    *,
    coordinator: _Coordinator | None = None,
) -> ProviderProfileService:
    service = ProviderProfileService(
        JsonProviderProfileRepository(path),
        builder,
        turn_coordinator=coordinator,
    )
    service.ensure_builtin_metadata()
    return service


async def _run_agent(
    provider: LLMProvider,
    continuation: ProviderContinuation | None = None,
) -> list[AgentEvent]:
    agent = AgentLoop(provider, ContextManager())
    return [
        event
        async for event in agent.run(
            UserMessageCommand.create("Remain offline."),
            continuation=continuation,
        )
    ]


@pytest.fixture(scope="module")
def managed_async_runner() -> Iterator[asyncio.Runner]:
    runner = asyncio.Runner()
    try:
        yield runner
    finally:
        runner.close()


def test_builtin_initialization_is_idempotent(
    tmp_path: Path,
) -> None:
    builder = _RecordingFactoryBuilder()
    service = _service(tmp_path / "providers.json", builder)

    service.ensure_builtin_metadata()

    assert service.list_profiles() == tuple(
        sorted(
            builtin_managed_profiles(),
            key=lambda item: item.profile_id.value,
        )
    )
    assert service.get_active_profile_id() == FAKE_DEFAULT_PROFILE_ID
    assert len(
        JsonProviderProfileRepository(
            tmp_path / "providers.json"
        ).list_credential_bindings()
    ) == 2


def test_create_update_and_delete_multiple_cloud_profiles(
    tmp_path: Path,
) -> None:
    service = _service(
        tmp_path / "providers.json",
        _RecordingFactoryBuilder(),
    )
    openai_first = CredentialId.new()
    openai_second = CredentialId.new()
    deepseek_credential = CredentialId.new()
    for provider_id, credential_id, display_name in (
        (OPENAI_PROVIDER_ID, openai_first, "OpenAI first key"),
        (OPENAI_PROVIDER_ID, openai_second, "OpenAI second key"),
        (
            DEEPSEEK_PROVIDER_ID,
            deepseek_credential,
            "DeepSeek key",
        ),
    ):
        service.create_credential_binding(
            provider_id=provider_id,
            credential_id=credential_id,
            display_name=display_name,
        )

    first = service.create_profile(
        provider_id=OPENAI_PROVIDER_ID,
        display_name="First OpenAI",
        model="gpt-5-mini",
        credential_id=openai_first,
    )
    second = service.create_profile(
        provider_id=OPENAI_PROVIDER_ID,
        display_name="Second OpenAI",
        model="gpt-5-mini",
        credential_id=openai_second,
    )
    deepseek = service.create_profile(
        provider_id=DEEPSEEK_PROVIDER_ID,
        display_name="DeepSeek V4",
        model="deepseek-v4-flash",
        credential_id=deepseek_credential,
    )
    updated = service.update_profile(
        first.profile_id,
        display_name="Updated OpenAI",
        model="gpt-5",
        credential_id=openai_second,
    )

    assert updated.credential_id == openai_second
    assert updated.display_name == "Updated OpenAI"
    assert {first.profile_id, second.profile_id, deepseek.profile_id} <= {
        profile.profile_id for profile in service.list_profiles()
    }

    service.delete_profile(deepseek.profile_id)
    assert service.get_profile(deepseek.profile_id) is None
    with pytest.raises(ProviderProfileServiceError):
        service.delete_credential_binding(openai_second)


def test_duplicate_unknown_and_cross_provider_metadata_are_rejected(
    tmp_path: Path,
) -> None:
    service = _service(
        tmp_path / "providers.json",
        _RecordingFactoryBuilder(),
    )
    credential_id = CredentialId.new()
    service.create_credential_binding(
        provider_id=OPENAI_PROVIDER_ID,
        credential_id=credential_id,
        display_name="OpenAI key",
    )
    profile_id = ProfileId.new()
    service.create_profile(
        provider_id=OPENAI_PROVIDER_ID,
        profile_id=profile_id,
        display_name="OpenAI",
        model="gpt-5-mini",
        credential_id=credential_id,
    )

    with pytest.raises(ProviderProfileServiceError):
        service.create_profile(
            provider_id=OPENAI_PROVIDER_ID,
            profile_id=profile_id,
            display_name="Duplicate",
            model="gpt-5-mini",
            credential_id=credential_id,
        )
    with pytest.raises(ProviderProfileServiceError):
        service.create_profile(
            provider_id=DEEPSEEK_PROVIDER_ID,
            display_name="Cross provider",
            model="deepseek-v4-flash",
            credential_id=credential_id,
        )
    with pytest.raises(ProviderProfileServiceError):
        service.create_profile(
            provider_id=ProviderId("unknown"),
            display_name="Unknown",
            model="unknown",
        )


def test_switch_withdraws_old_provider_then_closes_before_create(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        builder = _RecordingFactoryBuilder()
        started = asyncio.Event()
        release = asyncio.Event()
        coordinator = _Coordinator(
            builder.events,
            started=started,
            release=release,
        )
        service = _service(
            tmp_path / "providers.json",
            builder,
            coordinator=coordinator,
        )
        first = service.create_profile(
            provider_id=FAKE_PROVIDER_ID,
            display_name="Fake first",
            model="fake",
        )
        second = service.create_profile(
            provider_id=FAKE_PROVIDER_ID,
            display_name="Fake second",
            model="fake",
        )
        old = await service.activate_profile(first.profile_id, _OPTIONS)
        switch_task = asyncio.create_task(
            service.activate_profile(
                second.profile_id,
                _OPTIONS,
                turn_handling=ActiveTurnHandling.WAIT_FOR_ACTIVE,
            )
        )
        await started.wait()

        assert service.active_provider is None
        assert service.runtime_profile_id is None
        assert not builder.providers[0].closed
        blocked = [
            event
            async for event in old.generate_stream(
                LLMRequest(
                    instructions="Remain offline.",
                    messages=(
                        ChatMessage(
                            role=MessageRole.USER,
                            content="blocked",
                        ),
                    ),
                    max_output_tokens=16,
                )
            )
        ]
        assert blocked[-1].error_code == "provider_switching"

        release.set()
        new = await switch_task
        assert builder.providers[0].closed
        assert service.active_provider is new
        assert builder.events == [
            f"create:{first.profile_id.value}",
            "coordinate:wait_for_active",
            f"close:{first.profile_id.value}",
            f"create:{second.profile_id.value}",
        ]
        assert coordinator.calls == [
            (
                first.profile_id,
                second.profile_id,
                ActiveTurnHandling.WAIT_FOR_ACTIVE,
            )
        ]
        await service.aclose()
        remaining = {
            task
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task()
        }
        assert remaining == set()

    asyncio.run(scenario())


def test_close_failure_prevents_new_provider_publication(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        builder = _RecordingFactoryBuilder()
        coordinator = _Coordinator(builder.events)
        service = _service(
            tmp_path / "providers.json",
            builder,
            coordinator=coordinator,
        )
        first = service.create_profile(
            provider_id=FAKE_PROVIDER_ID,
            display_name="Fake first",
            model="fake",
        )
        second = service.create_profile(
            provider_id=FAKE_PROVIDER_ID,
            display_name="Fake second",
            model="fake",
        )
        provider = await service.activate_profile(
            first.profile_id,
            _OPTIONS,
        )
        assert provider is service.active_provider
        builder.providers[0].close_failures_remaining = 2

        with pytest.raises(
            ProviderProfileServiceError,
            match="previous Provider",
        ):
            await service.activate_profile(
                second.profile_id,
                _OPTIONS,
                turn_handling=ActiveTurnHandling.CANCEL_ACTIVE,
            )

        assert builder.create_count == 1
        assert service.active_provider is None
        assert service.runtime_profile_id is None
        assert service.retiring_provider_count == 1
        assert (
            service.lifecycle_state
            is ProviderLifecycleState.CLEANUP_PENDING
        )
        assert service.get_active_profile_id() == first.profile_id
        assert builder.network_request_count == 0

        with pytest.raises(
            ProviderProfileServiceError,
            match="Pending Provider cleanup",
        ):
            await service.activate_profile(second.profile_id, _OPTIONS)
        assert builder.create_count == 1
        assert service.retiring_provider_count == 1

        replacement = await service.activate_profile(
            second.profile_id,
            _OPTIONS,
        )
        assert replacement is service.active_provider
        assert builder.create_count == 2
        assert builder.providers[0].close_attempts == 3
        assert service.retiring_provider_count == 0
        assert service.lifecycle_state is ProviderLifecycleState.ACTIVE
        await service.aclose()
        assert service.lifecycle_state.value == "closed"

    asyncio.run(scenario())


def test_factory_failure_does_not_fallback_after_old_close(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        builder = _RecordingFactoryBuilder()
        coordinator = _Coordinator(builder.events)
        service = _service(
            tmp_path / "providers.json",
            builder,
            coordinator=coordinator,
        )
        first = service.create_profile(
            provider_id=FAKE_PROVIDER_ID,
            display_name="Fake first",
            model="fake",
        )
        second = service.create_profile(
            provider_id=FAKE_PROVIDER_ID,
            display_name="Fake second",
            model="fake",
        )
        await service.activate_profile(first.profile_id, _OPTIONS)
        builder.fail_on_create = 2

        with pytest.raises(ProviderProfileServiceError) as caught:
            await service.activate_profile(
                second.profile_id,
                _OPTIONS,
                turn_handling=ActiveTurnHandling.WAIT_FOR_ACTIVE,
            )

        assert builder.providers[0].closed
        assert builder.create_count == 2
        assert service.active_provider is None
        assert service.get_active_profile_id() == first.profile_id
        assert caught.value.__cause__ is None
        assert caught.value.__context__ is None
        assert "sensitive factory failure" not in "".join(
            traceback.format_exception(caught.value)
        )

    asyncio.run(scenario())


def test_switch_requires_explicit_turn_policy(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        builder = _RecordingFactoryBuilder()
        service = _service(
            tmp_path / "providers.json",
            builder,
        )
        first = service.create_profile(
            provider_id=FAKE_PROVIDER_ID,
            display_name="Fake first",
            model="fake",
        )
        second = service.create_profile(
            provider_id=FAKE_PROVIDER_ID,
            display_name="Fake second",
            model="fake",
        )
        old = await service.activate_profile(first.profile_id, _OPTIONS)

        with pytest.raises(
            ProviderProfileServiceError,
            match="explicit turn policy",
        ):
            await service.activate_profile(second.profile_id, _OPTIONS)

        assert service.active_provider is old
        assert builder.create_count == 1
        await service.aclose()

    asyncio.run(scenario())


def test_continuation_cannot_cross_profile(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        builder = _RecordingFactoryBuilder()
        coordinator = _Coordinator(builder.events)
        service = _service(
            tmp_path / "providers.json",
            builder,
            coordinator=coordinator,
        )
        first = service.create_profile(
            provider_id=FAKE_PROVIDER_ID,
            display_name="Fake first",
            model="fake",
        )
        second = service.create_profile(
            provider_id=FAKE_PROVIDER_ID,
            display_name="Fake second",
            model="fake",
        )
        old = await service.activate_profile(first.profile_id, _OPTIONS)
        continuation = ProviderContinuation(
            provider_name="fake",
            state=b"opaque",
            profile_id=first.profile_id,
        )
        service.validate_continuation(first.profile_id, continuation)

        with pytest.raises(
            ProviderProfileServiceError,
            match="active profile",
        ):
            await service.activate_profile(
                second.profile_id,
                _OPTIONS,
                turn_handling=ActiveTurnHandling.WAIT_FOR_ACTIVE,
                continuation=continuation,
            )

        assert service.active_provider is old
        assert coordinator.calls == []
        assert builder.create_count == 1
        await service.aclose()

    asyncio.run(scenario())


def test_cancelled_old_provider_close_is_retained_and_retried(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        builder = _RecordingFactoryBuilder()
        coordinator = _Coordinator(builder.events)
        service = _service(
            tmp_path / "providers.json",
            builder,
            coordinator=coordinator,
        )
        first = service.create_profile(
            provider_id=FAKE_PROVIDER_ID,
            display_name="Fake first",
            model="fake",
        )
        second = service.create_profile(
            provider_id=FAKE_PROVIDER_ID,
            display_name="Fake second",
            model="fake",
        )
        await service.activate_profile(first.profile_id, _OPTIONS)
        close_started = asyncio.Event()
        close_release = asyncio.Event()
        builder.providers[0].close_started = close_started
        builder.providers[0].close_release = close_release

        switch_task = asyncio.create_task(
            service.activate_profile(
                second.profile_id,
                _OPTIONS,
                turn_handling=ActiveTurnHandling.CANCEL_ACTIVE,
            )
        )
        await close_started.wait()
        switch_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await switch_task

        assert service.active_provider is None
        assert service.retiring_provider_count == 1
        assert (
            service.lifecycle_state
            is ProviderLifecycleState.CLEANUP_PENDING
        )
        assert builder.create_count == 1

        close_release.set()
        replacement = await service.activate_profile(
            second.profile_id,
            _OPTIONS,
        )
        assert replacement is service.active_provider
        assert builder.providers[0].close_attempts == 2
        assert builder.create_count == 2
        await service.aclose()
        remaining = {
            task
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task()
        }
        assert remaining == set()

    asyncio.run(scenario())


def test_persistence_and_candidate_close_failures_retain_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        builder = _RecordingFactoryBuilder()
        repository = JsonProviderProfileRepository(
            tmp_path / "providers.json"
        )
        service = ProviderProfileService(repository, builder)
        service.ensure_builtin_metadata()
        profile = service.create_profile(
            provider_id=FAKE_PROVIDER_ID,
            display_name="Candidate",
            model="fake",
        )

        def fail_persistence(profile_id: ProfileId) -> None:
            del profile_id
            builder.providers[-1].fail_close = True
            raise ProviderMetadataWriteError(
                "sensitive persistence failure"
            )

        monkeypatch.setattr(
            repository,
            "set_active_profile_id",
            fail_persistence,
        )
        with pytest.raises(
            ProviderProfileServiceError,
            match="candidate Provider",
        ) as caught:
            await service.activate_profile(profile.profile_id, _OPTIONS)

        assert service.active_provider is None
        assert service.runtime_profile_id is None
        assert service.candidate_cleanup_pending_count == 1
        assert (
            service.lifecycle_state
            is ProviderLifecycleState.CLEANUP_PENDING
        )
        assert caught.value.__cause__ is None
        assert caught.value.__context__ is None
        visible = repr(caught.value) + "".join(
            traceback.format_exception(caught.value)
        )
        assert "sensitive persistence failure" not in visible
        assert "sensitive close failure" not in visible

        builder.providers[-1].fail_close = False
        await service.aclose()
        assert builder.providers[-1].closed
        assert service.candidate_cleanup_pending_count == 0
        assert service.lifecycle_state.value == "closed"
        remaining = {
            task
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task()
        }
        assert remaining == set()

    asyncio.run(scenario())


def test_aclose_retains_failed_active_provider_for_retry(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        builder = _RecordingFactoryBuilder()
        service = _service(tmp_path / "providers.json", builder)
        profile = service.create_profile(
            provider_id=FAKE_PROVIDER_ID,
            display_name="Retained",
            model="fake",
        )
        await service.activate_profile(profile.profile_id, _OPTIONS)
        builder.providers[0].fail_close = True

        with pytest.raises(
            ProviderProfileServiceError,
            match="Pending Provider cleanup",
        ):
            await service.aclose()

        assert service.retiring_provider_count == 1
        assert (
            service.lifecycle_state
            is ProviderLifecycleState.CLEANUP_PENDING
        )
        builder.providers[0].fail_close = False
        await service.aclose()
        assert builder.providers[0].close_attempts == 2
        assert service.retiring_provider_count == 0
        assert service.lifecycle_state.value == "closed"

    asyncio.run(scenario())


def test_active_profile_allows_display_name_only(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        builder = _RecordingFactoryBuilder()
        service = _service(tmp_path / "providers.json", builder)
        profile = service.create_profile(
            provider_id=FAKE_PROVIDER_ID,
            display_name="Before",
            model="fake",
        )
        provider = await service.activate_profile(
            profile.profile_id,
            _OPTIONS,
        )

        updated = service.update_profile(
            profile.profile_id,
            display_name="After",
        )

        assert updated.display_name == "After"
        assert service.runtime_profile_snapshot == updated
        assert service.runtime_activation_options == _OPTIONS
        assert (
            await service.activate_profile(
                profile.profile_id,
                _OPTIONS,
            )
            is provider
        )
        assert builder.create_count == 1
        await service.aclose()

    asyncio.run(scenario())


def test_active_profile_model_and_credential_changes_are_rejected(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        builder = _RecordingFactoryBuilder()
        service = _service(tmp_path / "providers.json", builder)
        alternate_credential = CredentialId.new()
        service.create_credential_binding(
            provider_id=OPENAI_PROVIDER_ID,
            credential_id=alternate_credential,
            display_name="Alternate OpenAI",
        )
        await service.activate_profile(
            OPENAI_DEFAULT_PROFILE_ID,
            _OPTIONS,
        )

        with pytest.raises(
            ProviderProfileServiceError,
            match="before changing",
        ):
            service.update_profile(
                OPENAI_DEFAULT_PROFILE_ID,
                model="gpt-5",
            )
        with pytest.raises(
            ProviderProfileServiceError,
            match="before changing",
        ):
            service.update_profile(
                OPENAI_DEFAULT_PROFILE_ID,
                credential_id=alternate_credential,
            )

        persisted = service.get_profile(OPENAI_DEFAULT_PROFILE_ID)
        assert persisted == service.runtime_profile_snapshot
        assert builder.create_count == 1
        await service.aclose()

    asyncio.run(scenario())


def test_same_profile_rejects_repository_or_options_drift(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        builder = _RecordingFactoryBuilder()
        repository = JsonProviderProfileRepository(
            tmp_path / "providers.json"
        )
        service = ProviderProfileService(repository, builder)
        service.ensure_builtin_metadata()
        profile = service.create_profile(
            provider_id=FAKE_PROVIDER_ID,
            display_name="Stable",
            model="fake",
        )
        provider = await service.activate_profile(
            profile.profile_id,
            _OPTIONS,
        )

        for changed_options in (
            replace(_OPTIONS, timeout_seconds=31.0),
            replace(_OPTIONS, max_retries=1),
            replace(_OPTIONS, stream=False),
        ):
            with pytest.raises(
                ProviderProfileServiceError,
                match="activation options changed",
            ):
                await service.activate_profile(
                    profile.profile_id,
                    changed_options,
                )
        repository.save_profile(replace(profile, model="externally-changed"))
        with pytest.raises(
            ProviderProfileServiceError,
            match="active profile or activation options changed",
        ):
            await service.activate_profile(profile.profile_id, _OPTIONS)

        assert service.active_provider is provider
        assert service.runtime_profile_snapshot == profile
        assert builder.create_count == 1
        await service.aclose()

    asyncio.run(scenario())


def test_managed_provider_scopes_completed_continuation(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        builder = _RecordingFactoryBuilder()
        service = _service(tmp_path / "providers.json", builder)
        profile = service.create_profile(
            provider_id=FAKE_PROVIDER_ID,
            display_name="Scoped",
            model="fake",
        )
        provider = await service.activate_profile(
            profile.profile_id,
            _OPTIONS,
        )
        delegate_continuation = ProviderContinuation(
            provider_name="fake",
            state=b"opaque-state",
            version="v1",
        )
        builder.providers[0].completion_continuation = (
            delegate_continuation
        )

        events = [
            event
            async for event in provider.generate_stream(
                LLMRequest(
                    instructions="Remain offline.",
                    messages=(
                        ChatMessage(
                            role=MessageRole.USER,
                            content="scope continuation",
                        ),
                    ),
                    max_output_tokens=16,
                )
            )
        ]

        managed = events[-1].continuation
        assert managed is not None
        assert managed.profile_id == profile.profile_id
        assert managed.provider_name == "fake"
        assert managed.state == b"opaque-state"
        assert delegate_continuation.profile_id is None
        service.validate_continuation(profile.profile_id, managed)
        await service.aclose()

    asyncio.run(scenario())


def test_agent_loop_passes_valid_profile_continuation_to_delegate(
    tmp_path: Path,
    managed_async_runner: asyncio.Runner,
) -> None:
    async def scenario() -> None:
        builder = _RecordingFactoryBuilder()
        service = _service(tmp_path / "providers.json", builder)
        profile = service.create_profile(
            provider_id=FAKE_PROVIDER_ID,
            display_name="Scoped",
            model="fake",
        )
        provider = await service.activate_profile(
            profile.profile_id,
            _OPTIONS,
        )
        continuation = ProviderContinuation(
            provider_name="fake",
            state=b"valid-opaque",
            profile_id=profile.profile_id,
        )

        events = await _run_agent(provider, continuation)

        assert builder.providers[0].generate_count == 1
        assert builder.providers[0].received_continuations == [
            continuation
        ]
        assert builder.providers[0].stream_closed_count == 1
        assert events[-1].type is AgentEventType.TURN_COMPLETED
        await service.aclose()

    managed_async_runner.run(scenario())


@pytest.mark.parametrize(
    "continuation_kind",
    ["missing_profile", "other_profile", "wrong_provider"],
)
def test_agent_loop_rejects_invalid_continuation_before_delegate(
    tmp_path: Path,
    continuation_kind: str,
    managed_async_runner: asyncio.Runner,
) -> None:
    async def scenario() -> None:
        builder = _RecordingFactoryBuilder()
        service = _service(tmp_path / "providers.json", builder)
        profile = service.create_profile(
            provider_id=FAKE_PROVIDER_ID,
            display_name="Scoped",
            model="fake",
        )
        provider = await service.activate_profile(
            profile.profile_id,
            _OPTIONS,
        )
        continuation = ProviderContinuation(
            provider_name=(
                "openai"
                if continuation_kind == "wrong_provider"
                else "fake"
            ),
            state=b"invalid-opaque",
            profile_id=(
                ProfileId.new()
                if continuation_kind == "other_profile"
                else None
            ),
        )

        events = await _run_agent(provider, continuation)
        request = ContextManager().build_request(
            UserMessageCommand.create("Remain offline."),
            continuation=continuation,
        )
        managed_events = [
            event
            async for event in provider.generate_stream(request)
        ]

        failures = [
            event
            for event in events
            if event.type is AgentEventType.TURN_FAILED
        ]
        assert len(failures) == 1
        assert (
            failures[0].error_code
            == "provider_continuation_mismatch"
        )
        assert not any(
            event.type is AgentEventType.TURN_COMPLETED
            for event in events
        )
        assert builder.providers[0].generate_count == 0
        assert builder.providers[0].received_continuations == []
        assert builder.providers[0].stream_closed_count == 0
        assert len(managed_events) == 1
        assert (
            managed_events[0].error_code
            == "provider_continuation_mismatch"
        )
        await service.aclose()

    managed_async_runner.run(scenario())


def test_agent_loop_accepts_unscoped_or_matching_delegate_continuation(
    tmp_path: Path,
    managed_async_runner: asyncio.Runner,
) -> None:
    async def scenario() -> None:
        for index, already_scoped in enumerate((False, True)):
            builder = _RecordingFactoryBuilder()
            service = _service(
                tmp_path / f"providers-{index}.json",
                builder,
            )
            profile = service.create_profile(
                provider_id=FAKE_PROVIDER_ID,
                display_name="Scoped",
                model="fake",
            )
            provider = await service.activate_profile(
                profile.profile_id,
                _OPTIONS,
            )
            returned = ProviderContinuation(
                provider_name="fake",
                state=b"delegate-opaque",
                version="v1",
                profile_id=(
                    profile.profile_id if already_scoped else None
                ),
            )
            builder.providers[0].completion_continuation = returned

            events = await _run_agent(provider)

            completed = next(
                event
                for event in events
                if event.type is AgentEventType.TURN_COMPLETED
            )
            assert completed.continuation is not None
            assert (
                completed.continuation.profile_id
                == profile.profile_id
            )
            assert completed.continuation.provider_name == "fake"
            assert completed.continuation.state == b"delegate-opaque"
            assert completed.continuation.version == "v1"
            if already_scoped:
                assert completed.continuation is returned
            else:
                assert returned.profile_id is None
            assert builder.providers[0].stream_closed_count == 1
            await service.aclose()

    managed_async_runner.run(scenario())


@pytest.mark.parametrize(
    "conflict_kind",
    ["profile_id", "provider_name"],
)
def test_agent_loop_rejects_conflicting_delegate_continuation(
    tmp_path: Path,
    conflict_kind: str,
    managed_async_runner: asyncio.Runner,
) -> None:
    async def scenario() -> None:
        builder = _RecordingFactoryBuilder()
        service = _service(tmp_path / "providers.json", builder)
        profile = service.create_profile(
            provider_id=FAKE_PROVIDER_ID,
            display_name="Scoped",
            model="fake",
        )
        provider = await service.activate_profile(
            profile.profile_id,
            _OPTIONS,
        )
        builder.providers[0].script = [
            LLMEvent.text_delta("partial"),
            LLMEvent.completed(
                ProviderContinuation(
                    provider_name=(
                        "openai"
                        if conflict_kind == "provider_name"
                        else "fake"
                    ),
                    state=b"conflicting-opaque",
                    profile_id=(
                        ProfileId.new()
                        if conflict_kind == "profile_id"
                        else profile.profile_id
                    ),
                )
            ),
        ]

        events = await _run_agent(provider)

        failure = next(
            event
            for event in events
            if event.type is AgentEventType.TURN_FAILED
        )
        assert failure.error_code == "provider_continuation_mismatch"
        assert not any(
            event.type is AgentEventType.TURN_COMPLETED
            for event in events
        )
        assert all(event.continuation is None for event in events)
        assert builder.providers[0].generate_count == 1
        assert builder.providers[0].stream_closed_count == 1
        await service.aclose()

    managed_async_runner.run(scenario())


def test_continuation_mismatch_does_not_leak_opaque_state(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    managed_async_runner: asyncio.Runner,
) -> None:
    secret = "opaque-state-never-log"

    async def scenario() -> None:
        builder = _RecordingFactoryBuilder()
        service = _service(tmp_path / "providers.json", builder)
        profile = service.create_profile(
            provider_id=FAKE_PROVIDER_ID,
            display_name="Scoped",
            model="fake",
        )
        provider = await service.activate_profile(
            profile.profile_id,
            _OPTIONS,
        )
        continuation = ProviderContinuation(
            provider_name="fake",
            state=secret.encode(),
            profile_id=ProfileId.new(),
        )
        caplog.set_level(logging.DEBUG)

        events = await _run_agent(provider, continuation)
        with pytest.raises(ProviderProfileServiceError) as caught:
            service.validate_continuation(
                profile.profile_id,
                continuation,
            )

        visible = (
            repr(events)
            + repr(caught.value)
            + "".join(traceback.format_exception(caught.value))
            + caplog.text
        )
        assert secret not in visible
        assert repr(continuation) == "<ProviderContinuation redacted>"
        assert builder.providers[0].generate_count == 0
        await service.aclose()

    managed_async_runner.run(scenario())
    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err


def test_agent_loop_cancellation_closes_managed_and_delegate_streams(
    tmp_path: Path,
    managed_async_runner: asyncio.Runner,
) -> None:
    async def scenario() -> None:
        builder = _RecordingFactoryBuilder()
        service = _service(tmp_path / "providers.json", builder)
        profile = service.create_profile(
            provider_id=FAKE_PROVIDER_ID,
            display_name="Blocking",
            model="fake",
        )
        provider = await service.activate_profile(
            profile.profile_id,
            _OPTIONS,
        )
        started = asyncio.Event()
        builder.providers[0].stream_started = started
        builder.providers[0].stream_release = asyncio.Event()
        task = asyncio.create_task(_run_agent(provider))
        await started.wait()

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert builder.providers[0].generate_count == 1
        assert builder.providers[0].stream_closed_count == 1
        await service.aclose()
        remaining = {
            running
            for running in asyncio.all_tasks()
            if running is not asyncio.current_task()
        }
        assert remaining == set()

    managed_async_runner.run(scenario())


@pytest.mark.parametrize(
    ("provider_id", "model"),
    [
        (FAKE_PROVIDER_ID, "fake"),
        (OPENAI_PROVIDER_ID, "gpt-5-mini"),
        (DEEPSEEK_PROVIDER_ID, "deepseek-v4-flash"),
    ],
)
def test_same_provider_continuation_cannot_cross_profiles(
    tmp_path: Path,
    provider_id: ProviderId,
    model: str,
) -> None:
    async def scenario() -> None:
        builder = _RecordingFactoryBuilder()
        coordinator = _Coordinator(builder.events)
        service = _service(
            tmp_path / "providers.json",
            builder,
            coordinator=coordinator,
        )
        credentials: list[CredentialId | None] = [None, None]
        if provider_id != FAKE_PROVIDER_ID:
            credentials = [CredentialId.new(), CredentialId.new()]
            for credential in credentials:
                assert credential is not None
                service.create_credential_binding(
                    provider_id=provider_id,
                    credential_id=credential,
                    display_name="Scoped credential",
                )
        first = service.create_profile(
            provider_id=provider_id,
            display_name="First",
            model=model,
            credential_id=credentials[0],
        )
        second = service.create_profile(
            provider_id=provider_id,
            display_name="Second",
            model=model,
            credential_id=credentials[1],
        )
        await service.activate_profile(first.profile_id, _OPTIONS)
        continuation = ProviderContinuation(
            provider_name=provider_id.value,
            state=b"opaque",
            profile_id=first.profile_id,
        )

        with pytest.raises(
            ProviderProfileServiceError,
            match="active profile",
        ):
            await service.activate_profile(
                second.profile_id,
                _OPTIONS,
                turn_handling=ActiveTurnHandling.WAIT_FOR_ACTIVE,
                continuation=continuation,
            )
        assert coordinator.calls == []
        await service.activate_profile(
            second.profile_id,
            _OPTIONS,
            turn_handling=ActiveTurnHandling.WAIT_FOR_ACTIVE,
        )
        with pytest.raises(
            ProviderProfileServiceError,
            match="active profile",
        ):
            service.validate_continuation(
                second.profile_id,
                continuation,
            )
        await service.aclose()

    asyncio.run(scenario())


def test_managed_continuation_requires_profile_and_provider_match(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        service = _service(
            tmp_path / "providers.json",
            _RecordingFactoryBuilder(),
        )
        profile = service.create_profile(
            provider_id=FAKE_PROVIDER_ID,
            display_name="Fake",
            model="fake",
        )
        await service.activate_profile(profile.profile_id, _OPTIONS)

        for continuation in (
            ProviderContinuation(
                provider_name="fake",
                state=b"legacy",
            ),
            ProviderContinuation(
                provider_name="openai",
                state=b"wrong-provider",
                profile_id=profile.profile_id,
            ),
        ):
            with pytest.raises(
                ProviderProfileServiceError,
                match="active profile",
            ):
                service.validate_continuation(
                    profile.profile_id,
                    continuation,
                )
        await service.aclose()

    asyncio.run(scenario())


def test_legacy_continuation_constructor_remains_compatible() -> None:
    continuation = ProviderContinuation("fake", b"opaque", "v1")

    assert continuation.profile_id is None
    assert repr(continuation) == "<ProviderContinuation redacted>"


@pytest.mark.parametrize(
    ("provider_id", "credential_id"),
    [
        (OPENAI_PROVIDER_ID, OPENAI_MANUAL_TEST_CREDENTIAL_ID),
        (DEEPSEEK_PROVIDER_ID, DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID),
    ],
)
def test_service_rejects_manual_test_credential_bindings(
    tmp_path: Path,
    provider_id: ProviderId,
    credential_id: CredentialId,
) -> None:
    service = _service(
        tmp_path / "providers.json",
        _RecordingFactoryBuilder(),
    )

    with pytest.raises(
        ProviderProfileServiceError,
        match="could not be created safely",
    ):
        service.create_credential_binding(
            provider_id=provider_id,
            credential_id=credential_id,
            display_name="Forbidden manual credential",
        )

    assert (
        JsonProviderProfileRepository(
            tmp_path / "providers.json"
        ).get_credential_binding(credential_id)
        is None
    )


@pytest.mark.parametrize(
    ("provider_name_override", "protocol_override"),
    [
        ("wrong-provider", None),
        (None, ApiProtocol.CHAT_COMPLETIONS),
    ],
)
def test_factory_candidate_identity_must_match_profile(
    tmp_path: Path,
    provider_name_override: str | None,
    protocol_override: ApiProtocol | None,
    managed_async_runner: asyncio.Runner,
) -> None:
    async def scenario() -> None:
        builder = _RecordingFactoryBuilder()
        builder.provider_name_override = provider_name_override
        builder.protocol_override = protocol_override
        service = _service(tmp_path / "providers.json", builder)
        profile = service.create_profile(
            provider_id=FAKE_PROVIDER_ID,
            display_name="Wrong identity",
            model="fake",
        )

        with pytest.raises(
            ProviderProfileServiceError,
            match="identity does not match",
        ) as caught:
            await service.activate_profile(profile.profile_id, _OPTIONS)

        assert service.active_provider is None
        assert service.runtime_profile_id is None
        assert service.candidate_cleanup_pending_count == 0
        assert builder.providers[0].closed
        assert caught.value.__cause__ is None
        assert caught.value.__context__ is None
        await service.aclose()

    managed_async_runner.run(scenario())


def test_invalid_factory_candidate_close_failure_is_retained(
    tmp_path: Path,
    managed_async_runner: asyncio.Runner,
) -> None:
    async def scenario() -> None:
        builder = _RecordingFactoryBuilder()
        builder.provider_name_override = "wrong-provider"
        builder.fail_candidate_close = True
        service = _service(tmp_path / "providers.json", builder)
        profile = service.create_profile(
            provider_id=FAKE_PROVIDER_ID,
            display_name="Wrong identity",
            model="fake",
        )

        with pytest.raises(
            ProviderProfileServiceError,
            match="invalid candidate Provider",
        ):
            await service.activate_profile(profile.profile_id, _OPTIONS)

        assert service.active_provider is None
        assert service.candidate_cleanup_pending_count == 1
        assert (
            service.lifecycle_state
            is ProviderLifecycleState.CLEANUP_PENDING
        )
        builder.providers[0].fail_close = False
        await service.aclose()
        assert service.candidate_cleanup_pending_count == 0
        assert builder.providers[0].close_attempts == 2
        assert service.lifecycle_state.value == "closed"

    managed_async_runner.run(scenario())


def test_service_builds_real_factory_with_persisted_bindings_offline(
    tmp_path: Path,
) -> None:
    class _RealFactoryBuilder:
        def __init__(self) -> None:
            self.openai_sdk = FakeOpenAIClientFactory()
            self.deepseek_sdk = FakeDeepSeekClientFactory()
            self.store = InMemorySecretStore()

        def __call__(
            self,
            credential_bindings: tuple[CredentialBinding, ...],
        ) -> ProviderFactory:
            return ProviderFactory(
                secret_store=self.store,
                openai_client_factory=self.openai_sdk,
                deepseek_client_factory=self.deepseek_sdk,
                credential_bindings=CredentialBindingRegistry(
                    credential_bindings
                ),
            )

    async def scenario() -> None:
        builder = _RealFactoryBuilder()
        events: list[str] = []
        coordinator = _Coordinator(events)
        service = ProviderProfileService(
            JsonProviderProfileRepository(
                tmp_path / "providers.json"
            ),
            builder,
            turn_coordinator=coordinator,
        )
        service.ensure_builtin_metadata()

        openai = await service.activate_profile(
            OPENAI_DEFAULT_PROFILE_ID,
            _OPTIONS,
        )
        deepseek = await service.activate_profile(
            DEEPSEEK_DEFAULT_PROFILE_ID,
            _OPTIONS,
            turn_handling=ActiveTurnHandling.WAIT_FOR_ACTIVE,
        )

        assert openai.name == "openai"
        assert deepseek.name == "deepseek"
        assert builder.openai_sdk.create_count == 0
        assert builder.deepseek_sdk.create_count == 0
        assert builder.openai_sdk.network_request_count == 0
        assert builder.deepseek_sdk.network_request_count == 0
        await service.aclose()

    asyncio.run(scenario())
