from __future__ import annotations

import dataclasses
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_MODEL_PATH = (
    _PROJECT_ROOT / "packaging/startup_secondary_environment.py"
)


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "_startup_secondary_environment_test",
        _MODEL_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_MODEL: Any = _load_module()
CanonicalEnvironmentError = _MODEL.CanonicalEnvironmentError
LaunchContext = _MODEL.LaunchContext
LaunchContextMismatch = _MODEL.LaunchContextMismatch
ProbeLifecycle = _MODEL.ProbeLifecycle
ProbeLifecycleError = _MODEL.ProbeLifecycleError
ProbePhase = _MODEL.ProbePhase
ProcessIdentity = _MODEL.ProcessIdentity
build_canonical_environment = _MODEL.build_canonical_environment
prepare_launch_pair = _MODEL.prepare_launch_pair
require_matching_launch_contexts = _MODEL.require_matching_launch_contexts


def _identity(**overrides: object) -> Any:
    values: dict[str, object] = {
        "session_id": 1,
        "user_token_sha256": "a" * 64,
        "integrity_level": "medium",
        "desktop": "default",
        "window_station": "interactive",
    }
    values.update(overrides)
    return ProcessIdentity(**values)


def _environment(tmp_path: Path) -> Any:
    return build_canonical_environment(
        {
            "Path": "fixed-path",
            "PATH": "ignored-path-variant",
            "SYSTEMROOT": "fixed-system-root",
            "HTTP_PROXY": "must-not-survive",
            "API_KEY": "must-not-survive",
            "PYTHONPATH": "must-not-survive",
            "VIRTUAL_ENV": "must-not-survive",
            "QT_PLUGIN_PATH": "must-not-survive",
            "SJTUCLAW_SESSION_NONCE": "old-nonce",
        },
        repository_root=tmp_path,
        runtime_root=tmp_path / "build" / "runtime",
    )


def test_owner_and_secondary_clone_one_frozen_snapshot(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    owner = environment.clone()
    secondary = environment.clone()

    assert owner == secondary
    assert owner is not secondary
    owner["TEMP"] = "mutated-copy"
    assert secondary["TEMP"] != owner["TEMP"]


def test_launch_pair_freezes_parent_once_and_uses_independent_clones(
    tmp_path: Path,
) -> None:
    parent = {"Path": "fixed-path", "EXAMPLE": "original"}
    pair = prepare_launch_pair(
        parent,
        repository_root=tmp_path,
        runtime_root=tmp_path / "build" / "runtime",
        working_directory=tmp_path / "dist",
        identity=_identity(),
    )
    parent["EXAMPLE"] = "changed-after-freeze"

    assert pair.owner_environment == pair.secondary_environment
    assert pair.owner_environment["EXAMPLE"] == "original"
    assert pair.owner_environment is not pair.secondary_environment


def test_path_variants_become_one_logical_key(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    clone = environment.clone()

    assert [name for name in clone if name.casefold() == "path"] == ["Path"]
    assert clone["Path"] == "fixed-path"


def test_all_redirected_paths_are_shared_and_inside_repository(
    tmp_path: Path,
) -> None:
    environment = _environment(tmp_path)
    clone = environment.clone()

    assert clone["TEMP"] == clone["TMP"] == clone["TMPDIR"]
    assert clone["APPDATA"] != clone["LOCALAPPDATA"]
    assert clone["HOME"] == clone["USERPROFILE"]
    assert environment.manifest.repository_redirect_count == 7
    assert environment.manifest.outside_repository_path_count == 0


def test_sensitive_proxy_python_qt_and_old_namespace_are_removed(
    tmp_path: Path,
) -> None:
    environment = _environment(tmp_path)
    names = {name.upper() for name in environment.clone()}

    for forbidden in (
        "HTTP_PROXY",
        "API_KEY",
        "PYTHONPATH",
        "VIRTUAL_ENV",
        "QT_PLUGIN_PATH",
        "SJTUCLAW_SESSION_NONCE",
    ):
        assert forbidden not in names


def test_manifest_contains_hashes_but_no_values(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    document = environment.manifest.to_safe_dict()
    rendered = repr(document)

    assert document["environment_values_recorded"] is False
    assert "fixed-path" not in rendered
    assert "must-not-survive" not in rendered
    assert len(str(document["aggregate_sha256"])) == 64


def test_frozen_environment_repr_does_not_expose_values(tmp_path: Path) -> None:
    environment = _environment(tmp_path)

    assert "fixed-path" not in repr(environment)
    assert "fixed-system-root" not in repr(environment)


def test_runtime_root_outside_repository_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(
        CanonicalEnvironmentError,
        match="runtime_root_outside_repository",
    ):
        build_canonical_environment(
            {},
            repository_root=tmp_path / "repository",
            runtime_root=tmp_path / "outside",
        )


def test_conflicting_ordinary_duplicate_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(
        CanonicalEnvironmentError,
        match="conflicting_environment_duplicate",
    ):
        build_canonical_environment(
            {"Example": "one", "EXAMPLE": "two"},
            repository_root=tmp_path,
            runtime_root=tmp_path / "build" / "runtime",
        )


def test_matching_launch_contexts_are_accepted(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    context = LaunchContext(
        environment=environment,
        working_directory=tmp_path,
        identity=_identity(),
    )

    require_matching_launch_contexts(context, dataclasses.replace(context))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("session_id", 2, "session_mismatch"),
        ("user_token_sha256", "b" * 64, "user_token_mismatch"),
        ("integrity_level", "high", "integrity_level_mismatch"),
        ("desktop", "other", "desktop_mismatch"),
        ("window_station", "other", "window_station_mismatch"),
    ],
)
def test_identity_mismatch_fails_before_secondary(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    environment = _environment(tmp_path)
    owner = LaunchContext(
        environment=environment,
        working_directory=tmp_path,
        identity=_identity(),
    )
    secondary = dataclasses.replace(
        owner,
        identity=_identity(**{field: value}),
    )

    with pytest.raises(LaunchContextMismatch, match=message):
        require_matching_launch_contexts(owner, secondary)


def test_working_directory_mismatch_fails_before_secondary(
    tmp_path: Path,
) -> None:
    environment = _environment(tmp_path)
    owner = LaunchContext(
        environment=environment,
        working_directory=tmp_path / "one",
        identity=_identity(),
    )
    secondary = dataclasses.replace(
        owner,
        working_directory=tmp_path / "two",
    )

    with pytest.raises(LaunchContextMismatch, match="working_directory_mismatch"):
        require_matching_launch_contexts(owner, secondary)


def test_owner_failure_prevents_secondary_creation() -> None:
    lifecycle = ProbeLifecycle()
    lifecycle.owner_create_failed()

    with pytest.raises(
        ProbeLifecycleError,
        match="secondary_retry_or_order_invalid",
    ):
        lifecycle.secondary_created(20, "secondary-token")
    assert lifecycle.owner_creation_count == 0
    assert lifecycle.secondary_creation_count == 0


def test_owner_and_secondary_each_have_one_creation_budget() -> None:
    lifecycle = ProbeLifecycle()
    lifecycle.owner_created(10, "owner-token")
    lifecycle.secondary_created(20, "secondary-token")

    with pytest.raises(ProbeLifecycleError, match="owner_retry_forbidden"):
        lifecycle.owner_created(11, "retry")
    with pytest.raises(
        ProbeLifecycleError,
        match="secondary_retry_or_order_invalid",
    ):
        lifecycle.secondary_created(21, "retry")
    assert lifecycle.owner_creation_count == 1
    assert lifecycle.secondary_creation_count == 1


def test_secondary_cleanup_requires_pid_and_creation_token() -> None:
    lifecycle = ProbeLifecycle()
    lifecycle.owner_created(10, "owner-token")
    lifecycle.secondary_created(20, "secondary-token")

    lifecycle.require_exact_secondary(20, "secondary-token")
    with pytest.raises(ProbeLifecycleError, match="secondary_identity_mismatch"):
        lifecycle.require_exact_secondary(20, "reused-token")
    with pytest.raises(ProbeLifecycleError, match="secondary_identity_mismatch"):
        lifecycle.require_exact_secondary(21, "secondary-token")


def test_normal_probe_lifecycle_reaches_owner_exit() -> None:
    lifecycle = ProbeLifecycle()
    lifecycle.owner_created(10, "owner-token")
    lifecycle.secondary_created(20, "secondary-token")
    lifecycle.secondary_exited()
    lifecycle.owner_exited()

    assert lifecycle.phase is ProbePhase.OWNER_EXITED
