from __future__ import annotations

import importlib
from pathlib import Path
from typing import cast

import pytest
from scripts.manual_credential_targets import (
    DEEPSEEK_MANUAL_TEST_TARGET,
    OPENAI_MANUAL_TEST_TARGET,
    ManualCredentialTargetResolver,
)

from sjtuclaw.domain.models import (
    DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID,
    OPENAI_DEFAULT_CREDENTIAL_ID,
    OPENAI_MANUAL_TEST_CREDENTIAL_ID,
    CredentialId,
)
from sjtuclaw.infrastructure.security import windows_credential_store
from sjtuclaw.infrastructure.security.windows_credential_store import (
    CredentialTargetResolutionError,
)


def test_manual_resolver_maps_only_two_fixed_targets() -> None:
    resolver = ManualCredentialTargetResolver()

    assert (
        resolver.resolve(OPENAI_MANUAL_TEST_CREDENTIAL_ID)
        == OPENAI_MANUAL_TEST_TARGET
    )
    assert (
        resolver.resolve(DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID)
        == DEEPSEEK_MANUAL_TEST_TARGET
    )


@pytest.mark.parametrize(
    "credential_id",
    [OPENAI_DEFAULT_CREDENTIAL_ID, CredentialId.new()],
)
def test_manual_resolver_rejects_non_manual_ids(
    credential_id: CredentialId,
) -> None:
    with pytest.raises(CredentialTargetResolutionError) as raised:
        ManualCredentialTargetResolver.resolve(credential_id)

    assert credential_id.value not in str(raised.value)


def test_manual_resolver_does_not_accept_a_target_string() -> None:
    with pytest.raises(TypeError, match="CredentialId"):
        ManualCredentialTargetResolver.resolve(
            cast(CredentialId, OPENAI_MANUAL_TEST_TARGET)
        )


def test_manual_target_module_import_is_resource_inert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend_calls = 0

    def fail_backend() -> None:
        nonlocal backend_calls
        backend_calls += 1
        raise AssertionError("native backend must remain inert")

    monkeypatch.setattr(
        windows_credential_store,
        "Win32CredentialBackend",
        fail_backend,
    )

    module = importlib.import_module("scripts.manual_credential_targets")
    importlib.reload(module)

    assert backend_calls == 0


def test_production_source_contains_no_manual_target_prefix() -> None:
    source_root = Path("src") / "sjtuclaw"
    matches = [
        path
        for path in source_root.rglob("*.py")
        if "SJTUClaw/Test/" in path.read_text(encoding="utf-8")
    ]

    assert matches == []
