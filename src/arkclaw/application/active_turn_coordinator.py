"""Framework-independent coordination for one active Agent turn."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from arkclaw.application.agent_loop import CancellationToken
from arkclaw.application.provider_profile_service import (
    ActiveTurnCoordinator,
    ActiveTurnHandling,
)
from arkclaw.domain.errors import ArkClawError
from arkclaw.domain.models import ProfileId


class ActiveTurnCoordinatorError(ArkClawError):
    """A fixed-message failure while coordinating the active turn."""


@dataclass(slots=True)
class _ActiveTurnRecord:
    task: asyncio.Task[None]
    cancellation: CancellationToken
    turn_id: str
    profile_id: ProfileId
    terminal: bool = False


class DefaultActiveTurnCoordinator(ActiveTurnCoordinator):
    """Own and quiesce the single active turn without orphan tasks."""

    def __init__(self) -> None:
        self._record: _ActiveTurnRecord | None = None

    @property
    def has_active_turn(self) -> bool:
        return self._record is not None

    @property
    def current_task(self) -> asyncio.Task[None] | None:
        record = self._record
        return None if record is None else record.task

    @property
    def current_cancellation(self) -> CancellationToken | None:
        record = self._record
        return None if record is None else record.cancellation

    @property
    def current_turn_id(self) -> str | None:
        record = self._record
        return None if record is None else record.turn_id

    @property
    def current_profile_id(self) -> ProfileId | None:
        record = self._record
        return None if record is None else record.profile_id

    @property
    def current_turn_terminal(self) -> bool:
        record = self._record
        return False if record is None else record.terminal

    def bind_turn(
        self,
        *,
        task: asyncio.Task[None],
        cancellation: CancellationToken,
        turn_id: str,
        profile_id: ProfileId,
    ) -> None:
        if self._record is not None:
            raise ActiveTurnCoordinatorError(
                "An Agent turn is already active."
            )
        self._record = _ActiveTurnRecord(
            task=task,
            cancellation=cancellation,
            turn_id=turn_id,
            profile_id=profile_id,
        )

    def mark_terminal(self, turn_id: str) -> None:
        record = self._record
        if record is not None and record.turn_id == turn_id:
            record.terminal = True

    def release_finished_turn(self, task: asyncio.Task[None]) -> None:
        record = self._record
        if record is not None and record.task is task and task.done():
            self._record = None

    async def prepare_for_provider_switch(
        self,
        *,
        old_profile_id: ProfileId,
        new_profile_id: ProfileId,
        handling: ActiveTurnHandling,
    ) -> None:
        del new_profile_id
        record = self._record
        if record is None:
            return
        if record.profile_id != old_profile_id:
            raise ActiveTurnCoordinatorError(
                "The active turn does not belong to the retiring profile."
            )
        if handling is ActiveTurnHandling.CANCEL_ACTIVE:
            record.cancellation.cancel()
        try:
            await asyncio.shield(record.task)
        except asyncio.CancelledError:
            raise
        if not record.task.done() or not record.terminal:
            raise ActiveTurnCoordinatorError(
                "The active turn did not reach a safe terminal state."
            )
