from __future__ import annotations

import pytest

from sjtuclaw.application.pet_action_sequence import PlaybackHealth
from sjtuclaw.application.pet_role_pack import (
    MoveDirectionPolicy,
    RoleAnimationNames,
    RolePackFraming,
    RolePackHashes,
    ValidatedRolePackIdentity,
)
from sjtuclaw.application.pet_role_pack_switch import (
    ActiveRolePack,
    RolePackCandidate,
    RolePackPreparationError,
    RolePackSwitchCoordinator,
    RolePackSwitchOutcome,
)
from sjtuclaw.application.pet_track0 import ActionOutcome


class _Resource:
    def __init__(self, name: str, events: list[str]) -> None:
        self.name = name
        self.events = events
        self.closed = False

    def close(self) -> None:
        if not self.closed:
            self.events.append(f"close:{self.name}")
            self.closed = True


class _Host:
    def __init__(
        self,
        events: list[str],
        *,
        quiesce: ActionOutcome = ActionOutcome.CLEARED,
        relax: ActionOutcome = ActionOutcome.ACCEPTED,
        health: PlaybackHealth = PlaybackHealth.HEALTHY,
    ) -> None:
        self.events = events
        self.quiesce_outcome = quiesce
        self.relax_outcome = relax
        self.playback_health = health

    def quiesce_role_pack(self) -> ActionOutcome:
        self.events.append("quiesce")
        return self.quiesce_outcome

    def publish_role_pack(self, candidate: RolePackCandidate) -> None:
        self.events.append(f"publish:{candidate.identity.pack_id}")

    def confirm_relax(self, active: ActiveRolePack) -> ActionOutcome:
        self.events.append(f"relax:{active.identity.pack_id}")
        return self.relax_outcome

    def resume_autonomous(self) -> None:
        self.events.append("resume")


def _identity(pack_id: str, hash_char: str) -> ValidatedRolePackIdentity:
    hashes = RolePackHashes(*(hash_char * 64 for _ in range(3)))
    return ValidatedRolePackIdentity(
        1,
        pack_id,
        "3.8",
        hashes,
        RoleAnimationNames("Relax", "Move", "Sit", "Sleep", "Special", "Interact"),
        MoveDirectionPolicy.MIRROR_MOVE,
        RolePackFraming(1.0, 0.0, 176.0),
    )


def _active(events: list[str]) -> ActiveRolePack:
    return ActiveRolePack(_identity("old", "a"), (_Resource("old", events),))


def _candidate(events: list[str], *, changed_hash: bool = False) -> RolePackCandidate:
    identity = _identity("old" if changed_hash else "new", "b")
    return RolePackCandidate(identity, (_Resource("candidate", events),))


def test_success_commits_candidate_before_destroying_old_and_resuming() -> None:
    events: list[str] = []
    host = _Host(events)
    coordinator = RolePackSwitchCoordinator(_active(events), host)

    result = coordinator.switch(_candidate(events))

    assert result.outcome is RolePackSwitchOutcome.SWITCHED
    assert result.active.identity.pack_id == "new"
    assert events == [
        "quiesce",
        "publish:new",
        "close:old",
        "relax:new",
        "resume",
    ]


def test_containment_failure_keeps_old_identity_and_destroys_candidate() -> None:
    events: list[str] = []
    old = _active(events)
    host = _Host(
        events,
        quiesce=ActionOutcome.RENDERER_STATE_UNKNOWN,
        health=PlaybackHealth.UNKNOWN,
    )
    coordinator = RolePackSwitchCoordinator(old, host)

    result = coordinator.switch(_candidate(events))

    assert result.outcome is RolePackSwitchOutcome.CONTAINMENT_FAILED
    assert result.active is old
    assert result.playback_health is PlaybackHealth.UNKNOWN
    assert events == ["quiesce", "close:candidate"]


def test_same_validated_identity_is_no_op_but_same_path_changed_hash_is_not() -> None:
    events: list[str] = []
    old = _active(events)
    host = _Host(events)
    coordinator = RolePackSwitchCoordinator(old, host)
    same = RolePackCandidate(old.identity, (_Resource("same", events),))

    no_op = coordinator.switch(same)
    changed = coordinator.switch(_candidate(events, changed_hash=True))

    assert no_op.outcome is RolePackSwitchOutcome.NO_OP
    assert changed.outcome is RolePackSwitchOutcome.SWITCHED
    assert events[0] == "close:same"
    assert "publish:old" in events


def test_failed_candidate_relax_remains_active_but_suspended() -> None:
    events: list[str] = []
    host = _Host(
        events,
        relax=ActionOutcome.PLAYBACK_DEGRADED,
        health=PlaybackHealth.DEGRADED,
    )
    coordinator = RolePackSwitchCoordinator(_active(events), host)

    result = coordinator.switch(_candidate(events))

    assert result.outcome is RolePackSwitchOutcome.RELAX_FAILED
    assert result.active.identity.pack_id == "new"
    assert result.playback_health is PlaybackHealth.DEGRADED
    assert events == [
        "quiesce",
        "publish:new",
        "close:old",
        "relax:new",
    ]


def test_candidate_preparation_closes_partial_resources_in_reverse_order() -> None:
    events: list[str] = []

    def fail() -> _Resource:
        raise RuntimeError("private constructor detail")

    with pytest.raises(RolePackPreparationError) as caught:
        RolePackCandidate.prepare(
            _identity("candidate", "c"),
            (
                lambda: _Resource("assets", events),
                lambda: _Resource("native", events),
                fail,
            ),
        )

    assert str(caught.value) == "role_pack_candidate_preparation_failed"
    assert events == ["close:native", "close:assets"]
