"""Two-phase lifecycle transaction for external pet role packs."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from arkclaw.application.pet.pet_action_sequence import PlaybackHealth
from arkclaw.application.pet.pet_role_pack import ValidatedRolePackIdentity
from arkclaw.application.pet.pet_track0 import ActionOutcome


class CloseableRoleResource(Protocol):
    def close(self) -> None: ...


class RolePackPreparationError(RuntimeError):
    """Stable public failure for partially constructed role-pack candidates."""

    def __init__(self) -> None:
        super().__init__("role_pack_candidate_preparation_failed")


@dataclass(slots=True)
class RolePackCandidate:
    identity: ValidatedRolePackIdentity
    resources: tuple[CloseableRoleResource, ...]
    _transferred: bool = False
    _closed: bool = False

    @classmethod
    def prepare(
        cls,
        identity: ValidatedRolePackIdentity,
        builders: tuple[Callable[[], CloseableRoleResource], ...],
    ) -> RolePackCandidate:
        """Build a candidate off-path and contain every partial resource."""
        resources: list[CloseableRoleResource] = []
        try:
            for build in builders:
                resources.append(build())
        except Exception:
            for resource in reversed(resources):
                with suppress(Exception):
                    resource.close()
            raise RolePackPreparationError from None
        return cls(identity, tuple(resources))

    def close(self) -> None:
        if self._closed or self._transferred:
            return
        self._closed = True
        for resource in reversed(self.resources):
            with suppress(Exception):
                resource.close()

    def promote(self) -> ActiveRolePack:
        if self._closed or self._transferred:
            raise RuntimeError("candidate ownership is unavailable")
        self._transferred = True
        return ActiveRolePack(self.identity, self.resources)


@dataclass(slots=True)
class ActiveRolePack:
    identity: ValidatedRolePackIdentity
    resources: tuple[CloseableRoleResource, ...]
    _closed: bool = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for resource in reversed(self.resources):
            with suppress(Exception):
                resource.close()


class RolePackSwitchOutcome(StrEnum):
    SWITCHED = "switched"
    NO_OP = "no_op"
    CONTAINMENT_FAILED = "containment_failed"
    PUBLISH_FAILED = "publish_failed"
    RELAX_FAILED = "relax_failed"


@dataclass(frozen=True, slots=True)
class RolePackSwitchResult:
    outcome: RolePackSwitchOutcome
    active: ActiveRolePack
    playback_health: PlaybackHealth


class RolePackSwitchHost(Protocol):
    @property
    def playback_health(self) -> PlaybackHealth: ...

    def quiesce_role_pack(self) -> ActionOutcome: ...

    def publish_role_pack(self, candidate: RolePackCandidate) -> None: ...

    def confirm_relax(self, active: ActiveRolePack) -> ActionOutcome: ...

    def resume_autonomous(self) -> None: ...


class RolePackSwitchCoordinator:
    """Publish a prepared candidate only after old Track 0 containment."""

    def __init__(self, active: ActiveRolePack, host: RolePackSwitchHost) -> None:
        self._active = active
        self._host = host

    @property
    def active(self) -> ActiveRolePack:
        return self._active

    def switch(self, candidate: RolePackCandidate) -> RolePackSwitchResult:
        if candidate.identity == self._active.identity:
            candidate.close()
            return self._result(RolePackSwitchOutcome.NO_OP)

        containment = self._host.quiesce_role_pack()
        if containment is not ActionOutcome.CLEARED:
            candidate.close()
            return self._result(RolePackSwitchOutcome.CONTAINMENT_FAILED)

        old = self._active
        try:
            self._host.publish_role_pack(candidate)
            active = candidate.promote()
        except Exception:
            candidate.close()
            return self._result(RolePackSwitchOutcome.PUBLISH_FAILED)

        self._active = active
        old.close()
        relax = self._host.confirm_relax(active)
        if relax is not ActionOutcome.ACCEPTED:
            return self._result(RolePackSwitchOutcome.RELAX_FAILED)
        self._host.resume_autonomous()
        return self._result(RolePackSwitchOutcome.SWITCHED)

    def _result(self, outcome: RolePackSwitchOutcome) -> RolePackSwitchResult:
        return RolePackSwitchResult(
            outcome,
            self._active,
            self._host.playback_health,
        )
