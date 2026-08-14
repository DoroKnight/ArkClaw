from __future__ import annotations

import pytest

from arkclaw.application.pet_action_sequence import (
    SEQUENCE_CATALOG,
    PetActionName,
    SequenceName,
    SequenceTerminal,
)
from arkclaw.application.pet_track0 import (
    ActionOutcome,
    ConfirmedPlaybackEpoch,
    PetSequenceRunner,
    PlaybackEvent,
    RunnerDirective,
)


def _event(
    epoch: ConfirmedPlaybackEpoch,
    *,
    loop_boundary: bool = False,
) -> PlaybackEvent:
    return PlaybackEvent(
        generation=epoch.generation,
        logical_action=epoch.logical_action,
        physical_name=epoch.physical_name,
        playback_token=epoch.playback_token,
        loop_boundary=loop_boundary,
    )


def _start(
    sequence_name: SequenceName,
    *,
    generation: int = 1,
    physical_name: str | None = None,
    playback_token: object | None = None,
) -> tuple[PetSequenceRunner, ConfirmedPlaybackEpoch]:
    runner = PetSequenceRunner()
    directive = runner.start(SEQUENCE_CATALOG[sequence_name].sequence)
    assert directive.next_index == 0
    assert directive.step is not None
    action = directive.step.action
    epoch = runner.accept_playback(
        generation=generation,
        logical_action=action,
        physical_name=physical_name or action.value,
        playback_token=(object() if playback_token is None else playback_token),
    )
    return runner, epoch


def _start_sleep_loop() -> tuple[PetSequenceRunner, ConfirmedPlaybackEpoch]:
    runner, start_epoch = _start(SequenceName.SLEEP, generation=10)
    directive = runner.handle_completion(_event(start_epoch))
    assert directive == RunnerDirective(
        outcome=ActionOutcome.ACCEPTED,
        next_index=1,
        step=SEQUENCE_CATALOG[SequenceName.SLEEP].sequence.steps[1],
        terminal=None,
    )
    loop_epoch = runner.accept_playback(
        generation=11,
        logical_action=PetActionName.SLEEP_LOOP,
        physical_name="sleep_loop",
        playback_token="p11",
    )
    return runner, loop_epoch


def test_start_selects_first_step_without_confirming_player_state() -> None:
    runner = PetSequenceRunner()

    directive = runner.start(SEQUENCE_CATALOG[SequenceName.SLEEP].sequence)

    assert directive.next_index == 0
    assert directive.step is not None
    assert directive.step.action is PetActionName.SLEEP_START
    assert runner.snapshot.current_index == 0
    assert runner.snapshot.confirmed_epoch is None
    assert not runner.snapshot.pending_graceful_exit


def test_matching_one_shot_completion_advances_once() -> None:
    runner, epoch = _start(SequenceName.SLEEP, generation=10)

    first = runner.handle_completion(_event(epoch))
    second = runner.handle_completion(_event(epoch))

    assert first is not None
    assert first.next_index == 1
    assert first.step is not None
    assert first.step.action is PetActionName.SLEEP_LOOP
    assert second == RunnerDirective(ActionOutcome.STALE_COMPLETION)


@pytest.mark.parametrize(
    "changed_field",
    ["generation", "logical_action", "physical_name", "playback_token"],
)
def test_each_callback_identity_mismatch_is_stale_and_side_effect_free(
    changed_field: str,
) -> None:
    runner, epoch = _start(SequenceName.SLEEP, generation=10)
    event = _event(epoch)
    before = runner.snapshot

    mismatched = PlaybackEvent(
        generation=999 if changed_field == "generation" else event.generation,
        logical_action=(
            PetActionName.READ if changed_field == "logical_action" else event.logical_action
        ),
        physical_name=(
            "SleepStart_wrong_case" if changed_field == "physical_name" else event.physical_name
        ),
        playback_token=(object() if changed_field == "playback_token" else event.playback_token),
        loop_boundary=event.loop_boundary,
    )
    directive = runner.handle_completion(mismatched)

    assert directive == RunnerDirective(ActionOutcome.STALE_COMPLETION)
    assert runner.snapshot == before


def test_loop_boundary_without_pending_exit_is_observational() -> None:
    runner, epoch = _start_sleep_loop()
    before = runner.snapshot

    directive = runner.handle_completion(_event(epoch, loop_boundary=True))

    assert directive is None
    assert runner.snapshot == before


def test_non_boundary_completion_cannot_advance_a_loop() -> None:
    runner, epoch = _start_sleep_loop()
    before = runner.snapshot

    directive = runner.handle_completion(_event(epoch))

    assert directive == RunnerDirective(ActionOutcome.STALE_COMPLETION)
    assert runner.snapshot == before


def test_graceful_exit_advances_once_at_next_matching_loop_boundary() -> None:
    runner, epoch = _start_sleep_loop()
    assert runner.request_graceful_exit() is ActionOutcome.ACCEPTED
    pending = runner.snapshot

    directive = runner.handle_completion(_event(epoch, loop_boundary=True))
    duplicate = runner.handle_completion(_event(epoch, loop_boundary=True))

    assert pending.current_index == 1
    assert pending.confirmed_epoch == epoch
    assert pending.pending_graceful_exit
    assert directive is not None
    assert directive.next_index == 2
    assert directive.step is not None
    assert directive.step.action is PetActionName.SLEEP_END
    assert not runner.snapshot.pending_graceful_exit
    assert runner.snapshot.confirmed_epoch is None
    assert duplicate == RunnerDirective(ActionOutcome.STALE_COMPLETION)


def test_repeated_graceful_exit_request_is_duplicate() -> None:
    runner, _ = _start_sleep_loop()

    assert runner.request_graceful_exit() is ActionOutcome.ACCEPTED
    assert runner.request_graceful_exit() is ActionOutcome.REJECTED_DUPLICATE


def test_drag_hold_rejects_graceful_exit_because_it_has_no_exit_step() -> None:
    runner, start_epoch = _start(SequenceName.DRAG_HOLD)
    directive = runner.handle_completion(_event(start_epoch))
    assert directive is not None
    runner.accept_playback(
        generation=2,
        logical_action=PetActionName.DRAG_LOOP,
        physical_name="drag_loop",
        playback_token="drag-loop",
    )
    before = runner.snapshot

    outcome = runner.request_graceful_exit()

    assert outcome is ActionOutcome.INVALID_SEQUENCE
    assert runner.snapshot == before


def test_final_completion_returns_terminal_directive_and_empties_runner() -> None:
    runner, epoch = _start(SequenceName.DRAG_RELEASE)

    directive = runner.handle_completion(_event(epoch))

    assert directive == RunnerDirective(
        outcome=ActionOutcome.ACCEPTED,
        next_index=None,
        step=None,
        terminal=SequenceTerminal.HOLD,
    )
    assert runner.snapshot.sequence is None
    assert runner.snapshot.current_index is None
    assert runner.snapshot.confirmed_epoch is None


def test_accept_playback_rejects_action_for_another_step_without_mutation() -> None:
    runner = PetSequenceRunner()
    runner.start(SEQUENCE_CATALOG[SequenceName.SLEEP].sequence)
    before = runner.snapshot

    with pytest.raises(ValueError):
        runner.accept_playback(
            generation=1,
            logical_action=PetActionName.SLEEP_LOOP,
            physical_name="sleep_loop",
            playback_token=object(),
        )

    assert runner.snapshot == before


def test_reset_empties_runner_local_state() -> None:
    runner, _ = _start_sleep_loop()
    runner.request_graceful_exit()

    runner.reset()

    assert runner.snapshot.sequence is None
    assert runner.snapshot.current_index is None
    assert runner.snapshot.confirmed_epoch is None
    assert not runner.snapshot.pending_graceful_exit
