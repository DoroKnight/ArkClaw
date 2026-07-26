from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest

from sjtuclaw.application.active_turn_coordinator import (
    DefaultActiveTurnCoordinator,
)
from sjtuclaw.application.agent_loop import CancellationToken
from sjtuclaw.application.provider_profile_service import (
    ActiveTurnHandling,
)
from sjtuclaw.domain.models import ProfileId


@pytest.fixture(scope="module")
def coordinator_runner() -> Iterator[asyncio.Runner]:
    runner = asyncio.Runner()
    try:
        yield runner
    finally:
        runner.close()


def test_wait_for_active_shields_turn_until_natural_terminal(
    coordinator_runner: asyncio.Runner,
) -> None:
    async def scenario() -> None:
        coordinator = DefaultActiveTurnCoordinator()
        release = asyncio.Event()
        turn_started = asyncio.Event()
        profile_id = ProfileId.new()

        async def turn() -> None:
            turn_started.set()
            await release.wait()
            coordinator.mark_terminal("turn-wait")

        task = asyncio.create_task(turn())
        coordinator.bind_turn(
            task=task,
            cancellation=CancellationToken(),
            turn_id="turn-wait",
            profile_id=profile_id,
        )
        task.add_done_callback(coordinator.release_finished_turn)
        await turn_started.wait()
        switch = asyncio.create_task(
            coordinator.prepare_for_provider_switch(
                old_profile_id=profile_id,
                new_profile_id=ProfileId.new(),
                handling=ActiveTurnHandling.WAIT_FOR_ACTIVE,
            )
        )

        assert not switch.done()
        assert coordinator.current_task is task
        release.set()
        await switch
        await task
        assert task.done()
        assert coordinator.current_task is None

    coordinator_runner.run(scenario())


def test_cancel_active_requests_cooperative_cancel_and_waits(
    coordinator_runner: asyncio.Runner,
) -> None:
    async def scenario() -> None:
        coordinator = DefaultActiveTurnCoordinator()
        cancellation = CancellationToken()
        cleanup_finished = asyncio.Event()
        profile_id = ProfileId.new()

        async def turn() -> None:
            await cancellation.wait()
            coordinator.mark_terminal("turn-cancel")
            cleanup_finished.set()

        task = asyncio.create_task(turn())
        coordinator.bind_turn(
            task=task,
            cancellation=cancellation,
            turn_id="turn-cancel",
            profile_id=profile_id,
        )
        task.add_done_callback(coordinator.release_finished_turn)

        await coordinator.prepare_for_provider_switch(
            old_profile_id=profile_id,
            new_profile_id=ProfileId.new(),
            handling=ActiveTurnHandling.CANCEL_ACTIVE,
        )

        assert cancellation.cancelled
        assert cleanup_finished.is_set()
        assert task.done()

    coordinator_runner.run(scenario())


def test_cancelled_switch_preserves_active_turn_reference(
    coordinator_runner: asyncio.Runner,
) -> None:
    async def scenario() -> None:
        coordinator = DefaultActiveTurnCoordinator()
        release = asyncio.Event()
        turn_started = asyncio.Event()
        profile_id = ProfileId.new()

        async def turn() -> None:
            turn_started.set()
            await release.wait()
            coordinator.mark_terminal("turn-preserved")

        task = asyncio.create_task(turn())
        coordinator.bind_turn(
            task=task,
            cancellation=CancellationToken(),
            turn_id="turn-preserved",
            profile_id=profile_id,
        )
        task.add_done_callback(coordinator.release_finished_turn)
        await turn_started.wait()
        switch = asyncio.create_task(
            coordinator.prepare_for_provider_switch(
                old_profile_id=profile_id,
                new_profile_id=ProfileId.new(),
                handling=ActiveTurnHandling.WAIT_FOR_ACTIVE,
            )
        )
        switch.cancel()

        with pytest.raises(asyncio.CancelledError):
            await switch
        assert not task.cancelled()
        assert coordinator.current_task is task
        release.set()
        await task

    coordinator_runner.run(scenario())
