from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sjtuclaw.application.autostart_eligibility import (
    AutostartEligibilityReason,
    AutostartEligibilityResult,
    ExecutableFacts,
    NuitkaRuntimeFacts,
    evaluate_executable,
    evaluate_nuitka_runtime,
    inspect_nuitka_runtime,
)

_SUPPORTED_RUNTIME_FACTS = NuitkaRuntimeFacts(
    marker_present=True,
    marker_type_matches=True,
    standalone_mode=True,
    onefile_disabled=True,
    containing_dir_valid=True,
    executable_resolvable=True,
    executable_parent_matches=True,
)
_SUPPORTED_EXECUTABLE_FACTS = ExecutableFacts(
    executable_resolvable=True,
    executable_absolute=True,
    executable_matches_resolved=True,
    executable_regular=True,
    executable_reparse_point=False,
    executable_hardlink_valid=True,
    executable_name_valid=True,
    virtual_environment_path=False,
    executable_path_safe=True,
    command_length_valid=True,
)
_SUPPORTED = AutostartEligibilityResult(
    AutostartEligibilityReason.SUPPORTED
)


@pytest.mark.parametrize(
    ("field_name", "field_value", "expected"),
    [
        (
            "marker_present",
            False,
            AutostartEligibilityReason.MARKER_MISSING,
        ),
        (
            "marker_type_matches",
            False,
            AutostartEligibilityReason.MARKER_TYPE_MISMATCH,
        ),
        (
            "standalone_mode",
            False,
            AutostartEligibilityReason.STANDALONE_MODE_INVALID,
        ),
        (
            "onefile_disabled",
            False,
            AutostartEligibilityReason.ONEFILE_MODE_INVALID,
        ),
        (
            "containing_dir_valid",
            False,
            AutostartEligibilityReason.CONTAINING_DIR_INVALID,
        ),
        (
            "executable_resolvable",
            False,
            AutostartEligibilityReason.EXECUTABLE_UNRESOLVABLE,
        ),
        (
            "executable_parent_matches",
            False,
            AutostartEligibilityReason.EXECUTABLE_PARENT_MISMATCH,
        ),
    ],
)
def test_nuitka_runtime_reason_is_fixed_and_path_free(
    field_name: str,
    field_value: bool,
    expected: AutostartEligibilityReason,
) -> None:
    facts = replace(
        _SUPPORTED_RUNTIME_FACTS,
        **{field_name: field_value},
    )

    result = evaluate_nuitka_runtime(facts)

    assert result.reason is expected
    assert result.supported is False
    assert "\\" not in repr(result)
    assert "/" not in repr(result)


def test_supported_nuitka_runtime_is_explicit() -> None:
    result = evaluate_nuitka_runtime(_SUPPORTED_RUNTIME_FACTS)

    assert result.reason is AutostartEligibilityReason.SUPPORTED
    assert result.supported is True


@pytest.mark.parametrize(
    ("field_name", "field_value", "expected"),
    [
        (
            "executable_resolvable",
            False,
            AutostartEligibilityReason.EXECUTABLE_UNRESOLVABLE,
        ),
        (
            "executable_absolute",
            False,
            AutostartEligibilityReason.EXECUTABLE_NOT_ABSOLUTE,
        ),
        (
            "executable_matches_resolved",
            False,
            AutostartEligibilityReason.EXECUTABLE_PATH_MISMATCH,
        ),
        (
            "executable_regular",
            False,
            AutostartEligibilityReason.EXECUTABLE_NOT_REGULAR,
        ),
        (
            "executable_reparse_point",
            True,
            AutostartEligibilityReason.EXECUTABLE_REPARSE_POINT,
        ),
        (
            "executable_hardlink_valid",
            False,
            AutostartEligibilityReason.EXECUTABLE_HARDLINK_INVALID,
        ),
        (
            "executable_name_valid",
            False,
            AutostartEligibilityReason.EXECUTABLE_NAME_INVALID,
        ),
        (
            "virtual_environment_path",
            True,
            AutostartEligibilityReason.VIRTUAL_ENVIRONMENT_PATH_REJECTED,
        ),
        (
            "executable_path_safe",
            False,
            AutostartEligibilityReason.EXECUTABLE_PATH_UNSAFE,
        ),
        (
            "command_length_valid",
            False,
            AutostartEligibilityReason.COMMAND_LENGTH_INVALID,
        ),
    ],
)
def test_executable_reason_is_fixed_and_path_free(
    field_name: str,
    field_value: bool,
    expected: AutostartEligibilityReason,
) -> None:
    facts = replace(
        _SUPPORTED_EXECUTABLE_FACTS,
        **{field_name: field_value},
    )

    result = evaluate_executable(_SUPPORTED, facts)

    assert result.reason is expected
    assert result.supported is False
    assert "\\" not in repr(result)
    assert "/" not in repr(result)


def test_runtime_rejection_cannot_be_overridden_by_executable_facts() -> None:
    rejected = AutostartEligibilityResult(
        AutostartEligibilityReason.ONEFILE_MODE_INVALID
    )

    result = evaluate_executable(rejected, _SUPPORTED_EXECUTABLE_FACTS)

    assert result is rejected


def test_supported_executable_is_explicit() -> None:
    result = evaluate_executable(_SUPPORTED, _SUPPORTED_EXECUTABLE_FACTS)

    assert result.reason is AutostartEligibilityReason.SUPPORTED
    assert result.supported is True


@pytest.mark.parametrize(
    ("attribute", "expected"),
    [
        ("standalone", AutostartEligibilityReason.STANDALONE_MODE_INVALID),
        ("onefile", AutostartEligibilityReason.ONEFILE_MODE_INVALID),
        (
            "containing_dir",
            AutostartEligibilityReason.CONTAINING_DIR_INVALID,
        ),
    ],
)
def test_marker_attribute_failure_is_reduced_to_fixed_reason(
    tmp_path: Path,
    attribute: str,
    expected: AutostartEligibilityReason,
) -> None:
    executable = tmp_path / "SJTUClaw.exe"
    executable.write_bytes(b"offline-placeholder")

    class _Marker:
        standalone = True
        onefile = False
        containing_dir = str(tmp_path)

        def __getattribute__(self, name: str) -> object:
            if name == attribute:
                raise OSError("unsafe-runtime-path-never-display")
            return super().__getattribute__(name)

    _Marker.__name__ = "__nuitka_version__"

    result = inspect_nuitka_runtime(_Marker(), executable)

    assert result.reason is expected
    assert "unsafe-runtime-path-never-display" not in repr(result)
