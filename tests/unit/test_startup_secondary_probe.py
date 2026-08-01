from __future__ import annotations

import ast
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PROBE_PATH = _PROJECT_ROOT / "packaging/startup_secondary_probe.py"


def _source() -> str:
    return _PROBE_PATH.read_text(encoding="utf-8")


def test_probe_source_has_valid_python_ast() -> None:
    ast.parse(_source())


def test_probe_reads_parent_environment_exactly_once() -> None:
    source = _source()

    assert source.count("dict(os.environ)") == 1
    assert "os.environ.copy" not in source
    assert "secondary_environment=os.environ" not in source


def test_probe_uses_one_launch_pair_for_both_processes() -> None:
    source = _source()

    assert source.count("prepare_launch_pair(") == 1
    assert "pair.owner_environment" in source
    assert "pair.secondary_environment" in source
    assert source.count("environment_manifest_sha256") >= 2


def test_probe_has_one_owner_and_one_secondary_start_site() -> None:
    source = _source()

    assert source.count("_start_child(") == 3  # definition plus two calls
    assert source.count("lifecycle.owner_created(") == 1
    assert source.count("lifecycle.secondary_created(") == 1
    assert "retry" not in source.casefold()


def test_probe_requires_exact_identity_before_secondary_cleanup() -> None:
    source = _source()

    assert "lifecycle.require_exact_secondary(" in source
    assert "secondary.kill()" in source
    assert "Get-Process -Name" not in source


def test_probe_never_serializes_environment_values() -> None:
    source = _source()

    assert '"environment_values_recorded": False' in source
    assert "parent_snapshot" not in source.split("_write_json(")[-1]
    assert "owner_environment" not in source.split("_write_json(")[-1]


def test_probe_redirects_every_required_runtime_path() -> None:
    source = _source()

    for relative in ("temp", "appdata", "localappdata", "userprofile"):
        assert f'"{relative}"' in source
    assert '"runtime"' in source


def test_probe_records_secondary_ack_and_ui_safety_facts() -> None:
    source = _source()

    for marker in (
        "ack_verified",
        "secondary_foreground_observed",
        "startup_secondary_single_instance_verified",
        "owner_foreground_before_confirmation",
    ):
        assert marker in source
