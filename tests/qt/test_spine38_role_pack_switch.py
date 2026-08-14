"""Qt-thread contract for transactional Spine role-pack replacement."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QThread
from PySide6.QtWidgets import QApplication

from arkclaw.application.pet.pet_action_sequence import PlaybackHealth
from arkclaw.application.pet.pet_role_pack import (
    MoveDirectionPolicy,
    RoleAnimationNames,
    RolePackFraming,
    RolePackHashes,
    ValidatedRolePackIdentity,
)
from arkclaw.application.pet.pet_role_pack_switch import (
    ActiveRolePack,
    RolePackCandidate,
    RolePackSwitchCoordinator,
    RolePackSwitchOutcome,
)
from arkclaw.application.pet.pet_track0 import ActionOutcome


@pytest.fixture(scope="module")
def qt_application() -> Iterator[QApplication]:
    existing = QApplication.instance()
    application = existing if isinstance(existing, QApplication) else QApplication([])
    yield application


class _QtResource(QObject):
    def __init__(self, name: str, events: list[str]) -> None:
        super().__init__()
        self._name = name
        self._events = events

    def close(self) -> None:
        self._events.append(f"close:{self._name}")


class _GuiHost:
    playback_health = PlaybackHealth.HEALTHY

    def __init__(self, application: QApplication, events: list[str]) -> None:
        self._application = application
        self._events = events

    def _record(self, event: str) -> None:
        assert QThread.currentThread() is self._application.thread()
        self._events.append(event)

    def quiesce_role_pack(self) -> ActionOutcome:
        self._record("quiesce")
        return ActionOutcome.CLEARED

    def publish_role_pack(self, candidate: RolePackCandidate) -> None:
        self._record(f"publish:{candidate.identity.pack_id}")

    def confirm_relax(self, active: ActiveRolePack) -> ActionOutcome:
        self._record(f"relax:{active.identity.pack_id}")
        return ActionOutcome.ACCEPTED

    def resume_autonomous(self) -> None:
        self._record("resume")


def _identity(pack_id: str, digest: str) -> ValidatedRolePackIdentity:
    return ValidatedRolePackIdentity(
        1,
        pack_id,
        "3.8",
        RolePackHashes(*(digest * 64 for _ in range(3))),
        RoleAnimationNames("Relax", "Move", "Sit", "Sleep", "Special", "Interact"),
        MoveDirectionPolicy.MIRROR_MOVE,
        RolePackFraming(1.0, 0.0, 180.0),
    )


def test_switch_is_one_synchronous_gui_thread_transaction(
    qt_application: QApplication,
) -> None:
    events: list[str] = []
    old = ActiveRolePack(_identity("old", "a"), (_QtResource("old", events),))
    candidate = RolePackCandidate(
        _identity("new", "b"),
        (_QtResource("candidate", events),),
    )
    coordinator = RolePackSwitchCoordinator(old, _GuiHost(qt_application, events))

    result = coordinator.switch(candidate)

    assert result.outcome is RolePackSwitchOutcome.SWITCHED
    assert events == [
        "quiesce",
        "publish:new",
        "close:old",
        "relax:new",
        "resume",
    ]
