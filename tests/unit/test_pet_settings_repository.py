"""Strict offline tests for non-sensitive desktop-pet settings persistence."""

from __future__ import annotations

import json
import os
import traceback
from pathlib import Path

import pytest

from arkclaw.application.pet.pet_geometry import (
    Point,
    Rect,
    Size,
    physical_to_logical_rect,
)
from arkclaw.application.pet.pet_motion import PetMotionModel
from arkclaw.application.pet.pet_settings import (
    PET_SETTINGS_COORDINATE_LIMIT,
    PetSettings,
    PetSettingsLoadResult,
    PetSettingsWriteError,
)
from arkclaw.infrastructure.config.json_pet_settings_repository import (
    JsonPetSettingsRepository,
)
from arkclaw.presentation.qt.ui.pet_settings_controller import (
    PetSettingsController,
)

_SENSITIVE = "sk-test-never-use-this-value CredentialBlob"


class _RecordingRepository:
    def __init__(
        self,
        result: PetSettingsLoadResult,
        *,
        load_failure: BaseException | None = None,
        save_failure: BaseException | None = None,
    ) -> None:
        self.result = result
        self.load_failure = load_failure
        self.save_failure = save_failure
        self.load_count = 0
        self.saved: list[PetSettings] = []

    def load(self) -> PetSettingsLoadResult:
        self.load_count += 1
        if self.load_failure is not None:
            raise self.load_failure
        return self.result

    def save(self, settings: PetSettings) -> None:
        if self.save_failure is not None:
            raise self.save_failure
        self.saved.append(settings)


def _valid_settings() -> PetSettings:
    return PetSettings(window_x=100, window_y=-200, always_on_top=True)


def test_missing_document_returns_writable_safe_defaults(
    tmp_path: Path,
) -> None:
    repository = JsonPetSettingsRepository(tmp_path / "pet.json")

    result = repository.load()

    assert result == PetSettingsLoadResult(None, "none", True)
    assert not (tmp_path / "pet.json").exists()


def test_valid_document_round_trips_exact_non_sensitive_fields(
    tmp_path: Path,
) -> None:
    path = tmp_path / "pet.json"
    repository = JsonPetSettingsRepository(path)

    repository.save(_valid_settings())

    assert repository.load() == PetSettingsLoadResult(
        _valid_settings(),
        "none",
        True,
    )
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "schema_version": 1,
        "window_x": 100,
        "window_y": -200,
        "always_on_top": True,
    }
    serialized = path.read_text(encoding="utf-8").casefold()
    for forbidden in (
        "api_key",
        "authorization",
        "credentialblob",
        "secretvalue",
        "provider",
        "continuation",
        "conversation",
    ):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    "document",
    [
        [],
        {},
        {
            "schema_version": 1,
            "window_x": 1,
            "window_y": 2,
            "always_on_top": True,
            "unknown": 3,
        },
        {
            "schema_version": 1,
            "window_x": True,
            "window_y": 2,
            "always_on_top": True,
        },
        {
            "schema_version": 1,
            "window_x": 1.5,
            "window_y": 2,
            "always_on_top": True,
        },
        {
            "schema_version": 1,
            "window_x": "1",
            "window_y": 2,
            "always_on_top": True,
        },
        {
            "schema_version": 1,
            "window_x": 1,
            "window_y": 2,
            "always_on_top": 1,
        },
        {
            "schema_version": True,
            "window_x": 1,
            "window_y": 2,
            "always_on_top": True,
        },
        {
            "schema_version": 1,
            "window_x": PET_SETTINGS_COORDINATE_LIMIT + 1,
            "window_y": 2,
            "always_on_top": True,
        },
        {
            "schema_version": 1,
            "window_x": {"nested": 1},
            "window_y": 2,
            "always_on_top": True,
        },
    ],
)
def test_invalid_shapes_fail_closed_without_overwrite(
    tmp_path: Path,
    document: object,
) -> None:
    path = tmp_path / "pet.json"
    original = json.dumps(document).encode("utf-8")
    path.write_bytes(original)

    result = JsonPetSettingsRepository(path).load()

    assert result == PetSettingsLoadResult(
        None,
        "pet_settings_corrupted",
        False,
    )
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    "payload",
    [
        b"\xff\xfe\x80",
        b"{not-json}",
        (
            b'{"schema_version":1,"window_x":NaN,'
            b'"window_y":2,"always_on_top":true}'
        ),
        b"x" * (16 * 1024 + 1),
    ],
)
def test_corrupted_oversized_and_nonfinite_documents_use_safe_defaults(
    tmp_path: Path,
    payload: bytes,
) -> None:
    path = tmp_path / "pet.json"
    path.write_bytes(payload)

    result = JsonPetSettingsRepository(path).load()

    assert result.safe_code == "pet_settings_corrupted"
    assert result.settings is None
    assert not result.write_allowed
    assert path.read_bytes() == payload


@pytest.mark.parametrize(
    "field",
    [
        "schema_version",
        "window_x",
        "window_y",
        "always_on_top",
    ],
)
@pytest.mark.parametrize("duplicate_value", ["same", "different"])
def test_every_duplicate_allowed_key_is_rejected_before_dict_conversion(
    tmp_path: Path,
    field: str,
    duplicate_value: str,
) -> None:
    values = {
        "schema_version": "1",
        "window_x": "100",
        "window_y": "200",
        "always_on_top": "true",
    }
    second = (
        values[field]
        if duplicate_value == "same"
        else {
            "schema_version": "2",
            "window_x": "300",
            "window_y": "400",
            "always_on_top": "false",
        }[field]
    )
    members = [
        f'"schema_version":{values["schema_version"]}',
        f'"window_x":{values["window_x"]}',
        f'"window_y":{values["window_y"]}',
        f'"always_on_top":{values["always_on_top"]}',
        f'"{field}":{second}',
    ]
    payload = ("{" + ",".join(members) + "}").encode()
    path = tmp_path / "pet.json"
    path.write_bytes(payload)

    result = JsonPetSettingsRepository(path).load()

    assert result == PetSettingsLoadResult(
        None,
        "pet_settings_corrupted",
        False,
    )
    assert path.read_bytes() == payload


def test_duplicate_nested_key_with_sensitive_value_is_not_exposed(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = (
        b'{"schema_version":1,"window_x":1,"window_y":2,'
        b'"always_on_top":true,"nested":{"x":1,'
        b'"x":"sk-test-never-use-this-value CredentialBlob"}}'
    )
    path = tmp_path / "pet.json"
    path.write_bytes(payload)

    result = JsonPetSettingsRepository(path).load()
    captured = capsys.readouterr()
    visible = "\n".join(
        (
            repr(result),
            result.safe_code,
            captured.out,
            captured.err,
            caplog.text,
        )
    )

    assert result == PetSettingsLoadResult(
        None,
        "pet_settings_corrupted",
        False,
    )
    assert _SENSITIVE not in visible
    assert path.read_bytes() == payload


@pytest.mark.parametrize("schema_version", [0, 2, 99])
def test_unsupported_schema_is_distinct_and_preserved(
    tmp_path: Path,
    schema_version: int,
) -> None:
    path = tmp_path / "pet.json"
    original = json.dumps(
        {
            "schema_version": schema_version,
            "window_x": 1,
            "window_y": 2,
            "always_on_top": True,
        }
    ).encode("utf-8")
    path.write_bytes(original)

    result = JsonPetSettingsRepository(path).load()

    assert result == PetSettingsLoadResult(
        None,
        "pet_settings_schema_unsupported",
        False,
    )
    assert path.read_bytes() == original


def test_atomic_replace_failure_preserves_old_document_and_cleans_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "pet.json"
    old = b'{"old":"preserved"}\n'
    path.write_bytes(old)

    def fail_replace(source: object, destination: object) -> None:
        del source, destination
        raise OSError(_SENSITIVE)

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(PetSettingsWriteError) as caught:
        JsonPetSettingsRepository(path).save(_valid_settings())

    assert str(caught.value) == (
        "The desktop-pet settings could not be written atomically."
    )
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert _SENSITIVE not in "".join(
        traceback.format_exception(caught.value)
    )
    assert path.read_bytes() == old
    assert list(tmp_path.glob(".*.tmp")) == []


def test_successful_atomic_replace_leaves_no_temporary_file(
    tmp_path: Path,
) -> None:
    path = tmp_path / "nested" / "pet.json"

    JsonPetSettingsRepository(path).save(_valid_settings())

    assert path.exists()
    assert list(path.parent.glob(".*.tmp")) == []


def test_controller_loads_and_saves_at_most_once() -> None:
    repository = _RecordingRepository(
        PetSettingsLoadResult(_valid_settings(), "none", True)
    )
    controller = PetSettingsController(repository)

    assert controller.load_once().settings == _valid_settings()
    assert controller.load_once().settings == _valid_settings()
    assert controller.save_once(_valid_settings()) == "none"
    assert controller.save_once(
        PetSettings(3, 4, False)
    ) == "none"

    assert repository.load_count == 1
    assert repository.saved == [_valid_settings()]
    assert controller.save_count == 1


@pytest.mark.parametrize(
    "load_result",
    [
        PetSettingsLoadResult(None, "pet_settings_corrupted", False),
        PetSettingsLoadResult(
            None,
            "pet_settings_schema_unsupported",
            False,
        ),
    ],
)
def test_controller_never_overwrites_read_only_invalid_document(
    load_result: PetSettingsLoadResult,
) -> None:
    repository = _RecordingRepository(load_result)
    controller = PetSettingsController(repository)

    assert controller.load_once() == load_result
    assert controller.save_once(_valid_settings()) == load_result.safe_code
    assert repository.saved == []


def test_controller_contains_unknown_sensitive_failures(
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repository = _RecordingRepository(
        PetSettingsLoadResult(None, "none", True),
        load_failure=OSError(_SENSITIVE),
    )
    controller = PetSettingsController(repository)

    result = controller.load_once()
    captured = capsys.readouterr()
    visible = "\n".join(
        (
            result.safe_code,
            repr(result),
            controller.safe_code,
            captured.out,
            captured.err,
            caplog.text,
        )
    )

    assert result.safe_code == "pet_settings_initialization_failed"
    assert not result.write_allowed
    assert _SENSITIVE not in visible


def test_controller_write_failure_is_fixed_and_non_throwing() -> None:
    repository = _RecordingRepository(
        PetSettingsLoadResult(None, "none", True),
        save_failure=OSError(_SENSITIVE),
    )
    controller = PetSettingsController(repository)

    assert (
        controller.save_once(_valid_settings())
        == "pet_settings_write_failed"
    )
    assert controller.save_count == 0


def test_controller_does_not_disguise_process_control_exceptions() -> None:
    load_repository = _RecordingRepository(
        PetSettingsLoadResult(None, "none", True),
        load_failure=KeyboardInterrupt(),
    )
    with pytest.raises(KeyboardInterrupt):
        PetSettingsController(load_repository).load_once()

    save_repository = _RecordingRepository(
        PetSettingsLoadResult(None, "none", True),
        save_failure=SystemExit(7),
    )
    with pytest.raises(SystemExit) as caught:
        PetSettingsController(save_repository).save_once(
            _valid_settings()
        )
    assert caught.value.code == 7


def test_inert_controller_reports_fixed_initialization_failure() -> None:
    controller = PetSettingsController.initialization_failed()

    assert controller.load_once() == PetSettingsLoadResult(
        None,
        "pet_settings_initialization_failed",
        False,
    )
    assert controller.safe_code == "pet_settings_initialization_failed"
    assert not controller.write_allowed
    assert (
        controller.save_once(_valid_settings())
        == "pet_settings_initialization_failed"
    )
    assert controller.load_count == 0
    assert controller.save_count == 0


def test_restored_position_selects_the_matching_monitor_and_recovers_when_removed() -> None:
    model = PetMotionModel(Point(0, 0), Size(160, 180))
    primary = Rect(0, 0, 1_920, 1_080)
    secondary = Rect(1_920, -200, 2_560, 1_440)

    on_secondary = model.restore_position(
        Point(2_500, 100),
        (primary, secondary),
    )
    after_removal = model.restore_position(
        on_secondary.position,
        (primary,),
    )

    assert on_secondary.position == Point(2_500, 1_060)
    assert after_removal.position == Point(1_760, 900)


@pytest.mark.parametrize("scale_factor", [1.5, 2.0])
def test_restored_position_clamps_in_qt_logical_coordinates(
    scale_factor: float,
) -> None:
    workspace = physical_to_logical_rect(
        Rect(0, 0, 3_840, 2_160),
        scale_factor,
    )
    model = PetMotionModel(Point(0, 0), Size(160, 180))

    restored = model.restore_position(
        Point(99_999, 99_999),
        (workspace,),
    )

    assert restored.position == Point(
        workspace.right - 160,
        workspace.bottom - 180,
    )
