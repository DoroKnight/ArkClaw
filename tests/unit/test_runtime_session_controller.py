from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from pathlib import Path

import pytest

from sjtuclaw.application.active_turn_coordinator import (
    DefaultActiveTurnCoordinator,
)
from sjtuclaw.application.agent_loop import AgentLoop
from sjtuclaw.application.context_manager import ContextManager
from sjtuclaw.application.provider_profile_service import (
    ActiveTurnHandling,
    ProviderActivationOptions,
    ProviderLifecycleState,
    ProviderProfileService,
)
from sjtuclaw.application.runtime_session_controller import (
    RuntimeEvent,
    RuntimeEventType,
    RuntimeSessionController,
    RuntimeState,
)
from sjtuclaw.domain.events import LLMEvent
from sjtuclaw.domain.models import (
    FAKE_PROVIDER_ID,
    CredentialBinding,
    Embedding,
    LLMRequest,
    ProfileId,
    ProviderCapabilities,
    ProviderContinuation,
    ProviderProfile,
)
from sjtuclaw.domain.ports import LLMProvider
from sjtuclaw.infrastructure.config.json_provider_profile_repository import (
    JsonProviderProfileRepository,
)

_OPTIONS = ProviderActivationOptions(
    timeout_seconds=30.0,
    max_retries=0,
    stream=True,
)


class _ControlledProvider:
    def __init__(
        self,
        profile: ProviderProfile,
        script: Sequence[LLMEvent],
    ) -> None:
        self._profile = profile
        self.script = tuple(script)
        self.requests: list[LLMRequest] = []
        self.stream_started = asyncio.Event()
        self.stream_closed = asyncio.Event()
        self.before_release: asyncio.Event | None = None
        self.after_first_release: asyncio.Event | None = None
        self.after_first_blocked = asyncio.Event()
        self.closed = False
        self.fail_close = False

    @property
    def name(self) -> str:
        return self._profile.provider_id.value

    def capabilities(self) -> ProviderCapabilities:
        return self._profile.capabilities

    async def generate_stream(
        self,
        request: LLMRequest,
    ) -> AsyncIterator[LLMEvent]:
        self.requests.append(request)
        self.stream_started.set()
        try:
            if self.before_release is not None:
                await self.before_release.wait()
            for index, event in enumerate(self.script):
                yield event
                if index == 0 and self.after_first_release is not None:
                    self.after_first_blocked.set()
                    await self.after_first_release.wait()
        finally:
            self.stream_closed.set()

    async def embed(
        self,
        texts: Sequence[str],
    ) -> Sequence[Embedding]:
        del texts
        return ()

    async def aclose(self) -> None:
        if self.fail_close:
            raise RuntimeError("sensitive provider close failure")
        self.closed = True


ProviderConfigurer = Callable[
    [_ControlledProvider, int, ProviderProfile],
    None,
]


class _Factory:
    def __init__(self, owner: _FactoryBuilder) -> None:
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
        index = len(self._owner.providers)
        provider = _ControlledProvider(
            profile,
            [
                LLMEvent.text_delta("ok"),
                LLMEvent.completed(),
            ],
        )
        self._owner.configure(provider, index, profile)
        self._owner.providers.append(provider)
        return provider


class _FactoryBuilder:
    def __init__(
        self,
        configure: ProviderConfigurer | None = None,
    ) -> None:
        self.providers: list[_ControlledProvider] = []
        self._configure = configure

    def configure(
        self,
        provider: _ControlledProvider,
        index: int,
        profile: ProviderProfile,
    ) -> None:
        if self._configure is not None:
            self._configure(provider, index, profile)

    def __call__(
        self,
        credential_bindings: tuple[CredentialBinding, ...],
    ) -> _Factory:
        del credential_bindings
        return _Factory(self)


class _ObservedCoordinator(DefaultActiveTurnCoordinator):
    def __init__(self) -> None:
        super().__init__()
        self.prepare_started = asyncio.Event()

    async def prepare_for_provider_switch(
        self,
        *,
        old_profile_id: ProfileId,
        new_profile_id: ProfileId,
        handling: ActiveTurnHandling,
    ) -> None:
        self.prepare_started.set()
        await super().prepare_for_provider_switch(
            old_profile_id=old_profile_id,
            new_profile_id=new_profile_id,
            handling=handling,
        )


@pytest.fixture(scope="module")
def controller_runner() -> Iterator[asyncio.Runner]:
    runner = asyncio.Runner()
    try:
        yield runner
    finally:
        runner.close()


def _build_controller(
    path: Path,
    builder: _FactoryBuilder,
    *,
    coordinator: DefaultActiveTurnCoordinator | None = None,
) -> tuple[
    RuntimeSessionController,
    ProviderProfileService,
    DefaultActiveTurnCoordinator,
    list[RuntimeEvent],
]:
    selected_coordinator = coordinator or DefaultActiveTurnCoordinator()
    service = ProviderProfileService(
        JsonProviderProfileRepository(path),
        builder,
        turn_coordinator=selected_coordinator,
    )
    service.ensure_builtin_metadata()
    events: list[RuntimeEvent] = []
    controller = RuntimeSessionController(
        service,
        selected_coordinator,
        lambda provider: AgentLoop(provider, ContextManager()),
        events.append,
        runtime_thread_id=12345,
    )
    return controller, service, selected_coordinator, events


def _create_fake_profile(
    service: ProviderProfileService,
    name: str,
) -> ProfileId:
    return service.create_profile(
        provider_id=FAKE_PROVIDER_ID,
        display_name=name,
        model="fake",
    ).profile_id


def test_only_one_turn_can_run(
    tmp_path: Path,
    controller_runner: asyncio.Runner,
) -> None:
    async def scenario() -> None:
        release = asyncio.Event()

        def configure(
            provider: _ControlledProvider,
            index: int,
            profile: ProviderProfile,
        ) -> None:
            del index, profile
            provider.before_release = release

        builder = _FactoryBuilder(configure)
        controller, service, _, _ = _build_controller(
            tmp_path / "providers.json",
            builder,
        )
        profile_id = _create_fake_profile(service, "One turn")
        assert (
            await controller.activate_profile(
                profile_id,
                _OPTIONS,
                None,
            )
        ).success
        assert (
            await controller.start_turn(
                content="first",
                session_id="session",
            )
        ).success
        await builder.providers[0].stream_started.wait()

        duplicate = await controller.start_turn(
            content="second",
            session_id="session",
        )

        assert not duplicate.success
        assert duplicate.safe_code == "turn_already_running"
        release.set()
        await controller.wait_until_turn_idle()
        await controller.shutdown(cancel_active=False)

    controller_runner.run(scenario())


def test_completed_turn_commits_history_and_continuation(
    tmp_path: Path,
    controller_runner: asyncio.Runner,
) -> None:
    def configure(
        provider: _ControlledProvider,
        index: int,
        profile: ProviderProfile,
    ) -> None:
        del index, profile
        provider.script = (
            LLMEvent.text_delta("answer"),
            LLMEvent.completed(
                ProviderContinuation(
                    provider_name="fake",
                    state=b"opaque",
                )
            ),
        )

    async def scenario() -> None:
        builder = _FactoryBuilder(configure)
        controller, service, _, events = _build_controller(
            tmp_path / "providers.json",
            builder,
        )
        profile_id = _create_fake_profile(service, "Commit")
        await controller.activate_profile(profile_id, _OPTIONS, None)
        await controller.start_turn(
            content="question",
            session_id="session",
        )
        await controller.wait_until_turn_idle()

        history = controller.history_for_session("session")
        continuation = controller.continuation_for(
            "session",
            profile_id,
        )
        assert [message.content for message in history] == [
            "question",
            "answer",
        ]
        assert continuation is not None
        assert continuation.profile_id == profile_id
        assert any(
            event.type is RuntimeEventType.TURN_COMPLETED
            for event in events
        )
        assert all(not hasattr(event, "continuation") for event in events)
        await controller.shutdown(cancel_active=False)

    controller_runner.run(scenario())


@pytest.mark.parametrize("terminal_kind", ["failed", "cancelled"])
def test_partial_delta_failure_or_cancel_does_not_commit(
    tmp_path: Path,
    terminal_kind: str,
    controller_runner: asyncio.Runner,
) -> None:
    release = asyncio.Event()

    def configure(
        provider: _ControlledProvider,
        index: int,
        profile: ProviderProfile,
    ) -> None:
        del index, profile
        if terminal_kind == "failed":
            provider.script = (
                LLMEvent.text_delta("partial"),
                LLMEvent.failure(
                    "fake_failure",
                    "The Fake Provider failed.",
                ),
            )
        else:
            provider.script = (LLMEvent.text_delta("partial"),)
            provider.after_first_release = release

    async def scenario() -> None:
        builder = _FactoryBuilder(configure)
        controller, service, _, events = _build_controller(
            tmp_path / f"{terminal_kind}.json",
            builder,
        )
        profile_id = _create_fake_profile(service, terminal_kind)
        await controller.activate_profile(profile_id, _OPTIONS, None)
        await controller.start_turn(
            content="question",
            session_id="session",
        )
        if terminal_kind == "cancelled":
            await builder.providers[0].stream_started.wait()
            await builder.providers[0].after_first_blocked.wait()
            await controller.cancel_active_turn()
        await controller.wait_until_turn_idle()

        assert controller.history_for_session("session") == ()
        assert controller.continuation_for("session", profile_id) is None
        assert not any(
            event.type is RuntimeEventType.TURN_COMPLETED
            for event in events
        )
        assert builder.providers[0].stream_closed.is_set()
        await controller.shutdown(cancel_active=False)

    controller_runner.run(scenario())


def test_wait_for_active_delays_switch_until_natural_completion(
    tmp_path: Path,
    controller_runner: asyncio.Runner,
) -> None:
    release = asyncio.Event()

    def configure(
        provider: _ControlledProvider,
        index: int,
        profile: ProviderProfile,
    ) -> None:
        del profile
        if index == 0:
            provider.before_release = release

    async def scenario() -> None:
        coordinator = _ObservedCoordinator()
        builder = _FactoryBuilder(configure)
        controller, service, _, _ = _build_controller(
            tmp_path / "providers.json",
            builder,
            coordinator=coordinator,
        )
        first = _create_fake_profile(service, "First")
        second = _create_fake_profile(service, "Second")
        await controller.activate_profile(first, _OPTIONS, None)
        await controller.start_turn(
            content="wait",
            session_id="session",
        )
        await builder.providers[0].stream_started.wait()
        switch = asyncio.create_task(
            controller.activate_profile(
                second,
                _OPTIONS,
                ActiveTurnHandling.WAIT_FOR_ACTIVE,
            )
        )
        await coordinator.prepare_started.wait()

        assert not switch.done()
        assert len(builder.providers) == 1
        release.set()
        result = await switch
        assert result.success
        assert len(builder.providers) == 2
        assert builder.providers[0].closed
        await controller.shutdown(cancel_active=False)

    controller_runner.run(scenario())


def test_cancel_active_waits_for_stream_cleanup_then_switches(
    tmp_path: Path,
    controller_runner: asyncio.Runner,
) -> None:
    release = asyncio.Event()

    def configure(
        provider: _ControlledProvider,
        index: int,
        profile: ProviderProfile,
    ) -> None:
        del profile
        if index == 0:
            provider.before_release = release

    async def scenario() -> None:
        builder = _FactoryBuilder(configure)
        controller, service, _, events = _build_controller(
            tmp_path / "providers.json",
            builder,
        )
        first = _create_fake_profile(service, "First")
        second = _create_fake_profile(service, "Second")
        await controller.activate_profile(first, _OPTIONS, None)
        await controller.start_turn(
            content="cancel",
            session_id="session",
        )
        await builder.providers[0].stream_started.wait()

        result = await controller.activate_profile(
            second,
            _OPTIONS,
            ActiveTurnHandling.CANCEL_ACTIVE,
        )

        assert result.success
        assert builder.providers[0].stream_closed.is_set()
        assert builder.providers[0].closed
        assert any(
            event.type is RuntimeEventType.TURN_CANCELLED
            for event in events
        )
        await controller.shutdown(cancel_active=False)

    controller_runner.run(scenario())


def test_cancelled_switch_preserves_turn_and_old_provider(
    tmp_path: Path,
    controller_runner: asyncio.Runner,
) -> None:
    release = asyncio.Event()

    def configure(
        provider: _ControlledProvider,
        index: int,
        profile: ProviderProfile,
    ) -> None:
        del profile
        if index == 0:
            provider.before_release = release

    async def scenario() -> None:
        coordinator = _ObservedCoordinator()
        builder = _FactoryBuilder(configure)
        controller, service, _, _ = _build_controller(
            tmp_path / "providers.json",
            builder,
            coordinator=coordinator,
        )
        first = _create_fake_profile(service, "First")
        second = _create_fake_profile(service, "Second")
        await controller.activate_profile(first, _OPTIONS, None)
        await controller.start_turn(
            content="preserve",
            session_id="session",
        )
        await builder.providers[0].stream_started.wait()
        active_task = controller.active_turn_task
        switch = asyncio.create_task(
            controller.activate_profile(
                second,
                _OPTIONS,
                ActiveTurnHandling.WAIT_FOR_ACTIVE,
            )
        )
        await coordinator.prepare_started.wait()
        switch.cancel()

        with pytest.raises(asyncio.CancelledError):
            await switch
        assert controller.active_turn_task is active_task
        assert service.runtime_profile_id == first
        assert service.active_provider is not None
        release.set()
        await controller.wait_until_turn_idle()
        await controller.shutdown(cancel_active=False)

    controller_runner.run(scenario())


def test_continuation_is_isolated_by_profile(
    tmp_path: Path,
    controller_runner: asyncio.Runner,
) -> None:
    def configure(
        provider: _ControlledProvider,
        index: int,
        profile: ProviderProfile,
    ) -> None:
        del profile
        if index == 0:
            provider.script = (
                LLMEvent.text_delta("one"),
                LLMEvent.completed(
                    ProviderContinuation(
                        provider_name="fake",
                        state=b"profile-one",
                    )
                ),
            )

    async def scenario() -> None:
        builder = _FactoryBuilder(configure)
        controller, service, _, events = _build_controller(
            tmp_path / "providers.json",
            builder,
        )
        first = _create_fake_profile(service, "First")
        second = _create_fake_profile(service, "Second")
        await controller.activate_profile(first, _OPTIONS, None)
        await controller.start_turn(content="one", session_id="session")
        await controller.wait_until_turn_idle()
        first_continuation = controller.continuation_for(
            "session",
            first,
        )
        assert first_continuation is not None, events

        await controller.activate_profile(second, _OPTIONS, None)
        await controller.start_turn(content="two", session_id="session")
        await controller.wait_until_turn_idle()
        assert builder.providers[1].requests[0].continuation is None

        await controller.activate_profile(first, _OPTIONS, None)
        await controller.start_turn(
            content="three",
            session_id="session",
        )
        await controller.wait_until_turn_idle()
        assert (
            builder.providers[2].requests[0].continuation
            is first_continuation
        )
        await controller.shutdown(cancel_active=False)

    controller_runner.run(scenario())


def test_cleanup_pending_blocks_turn_and_shutdown_retries(
    tmp_path: Path,
    controller_runner: asyncio.Runner,
) -> None:
    async def scenario() -> None:
        builder = _FactoryBuilder()
        controller, service, _, _ = _build_controller(
            tmp_path / "providers.json",
            builder,
        )
        first = _create_fake_profile(service, "First")
        second = _create_fake_profile(service, "Second")
        await controller.activate_profile(first, _OPTIONS, None)
        builder.providers[0].fail_close = True

        activation = await controller.activate_profile(
            second,
            _OPTIONS,
            ActiveTurnHandling.WAIT_FOR_ACTIVE,
        )
        blocked = await controller.start_turn(
            content="blocked",
            session_id="session",
        )

        assert not activation.success
        assert (
            service.lifecycle_state
            is ProviderLifecycleState.CLEANUP_PENDING
        )
        assert blocked.safe_code == "provider_cleanup_pending"
        builder.providers[0].fail_close = False
        shutdown = await controller.shutdown(cancel_active=False)
        assert shutdown.success
        assert controller.state is RuntimeState.CLOSED

    controller_runner.run(scenario())


def test_shutdown_cancels_turn_closes_provider_and_leaves_no_tasks(
    tmp_path: Path,
    controller_runner: asyncio.Runner,
) -> None:
    release = asyncio.Event()

    def configure(
        provider: _ControlledProvider,
        index: int,
        profile: ProviderProfile,
    ) -> None:
        del index, profile
        provider.before_release = release

    async def scenario() -> None:
        builder = _FactoryBuilder(configure)
        controller, service, _, _ = _build_controller(
            tmp_path / "providers.json",
            builder,
        )
        profile_id = _create_fake_profile(service, "Shutdown")
        await controller.activate_profile(profile_id, _OPTIONS, None)
        await controller.start_turn(
            content="shutdown",
            session_id="session",
        )
        await builder.providers[0].stream_started.wait()

        result = await controller.shutdown(cancel_active=True)

        assert result.success
        assert controller.state is RuntimeState.CLOSED
        assert builder.providers[0].stream_closed.is_set()
        assert builder.providers[0].closed
        assert controller.active_turn_task is None
        remaining = {
            task
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task()
            and not task.done()
        }
        assert remaining == set()

    controller_runner.run(scenario())


def test_application_runtime_modules_do_not_import_qt() -> None:
    application_directory = (
        Path(__file__).parents[2] / "src" / "sjtuclaw" / "application"
    )
    for filename in (
        "active_turn_coordinator.py",
        "runtime_session_controller.py",
    ):
        source = (application_directory / filename).read_text(
            encoding="utf-8"
        )
        assert "PySide6" not in source
