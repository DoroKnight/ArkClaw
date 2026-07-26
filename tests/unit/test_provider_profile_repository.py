from __future__ import annotations

import json
import os
import traceback
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from sjtuclaw.application.provider_profile_repository import (
    ProviderMetadataConflictError,
    ProviderMetadataCorruptedError,
    ProviderMetadataReferenceError,
    ProviderMetadataSchemaError,
    ProviderMetadataWriteError,
)
from sjtuclaw.config.provider_profile_policy import (
    ProviderProfilePolicyError,
    build_supported_credential_binding,
    build_supported_profile,
    validate_supported_credential_binding,
)
from sjtuclaw.config.provider_profiles import (
    deepseek_profile,
    openai_profile,
)
from sjtuclaw.config.secrets import InMemorySecretStore, SecretValue
from sjtuclaw.domain.models import (
    DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID,
    DEEPSEEK_PROVIDER_ID,
    OPENAI_MANUAL_TEST_CREDENTIAL_ID,
    OPENAI_PROVIDER_ID,
    ApiProtocol,
    CredentialBinding,
    CredentialId,
    ProfileId,
    ProviderId,
)
from sjtuclaw.infrastructure.config.json_provider_profile_repository import (
    JsonProviderProfileRepository,
)

_FAKE_API_KEY = "sk-profile-json-never-use"


def _repository(path: Path) -> JsonProviderProfileRepository:
    return JsonProviderProfileRepository(path)


def _openai_binding(
    credential_id: CredentialId,
) -> CredentialBinding:
    return build_supported_credential_binding(
        provider_id=OPENAI_PROVIDER_ID,
        credential_id=credential_id,
        display_name="OpenAI metadata",
    )


def _deepseek_binding(
    credential_id: CredentialId,
) -> CredentialBinding:
    return build_supported_credential_binding(
        provider_id=DEEPSEEK_PROVIDER_ID,
        credential_id=credential_id,
        display_name="DeepSeek metadata",
    )


def test_empty_document_is_created_on_first_mutation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "providers.json"
    repository = _repository(path)
    credential_id = CredentialId.new()
    profile_id = ProfileId.new()

    assert repository.list_profiles() == ()
    assert repository.get_active_profile_id() is None
    assert not path.exists()

    repository.save_credential_binding(
        _openai_binding(credential_id)
    )
    profile = openai_profile(
        "gpt-5-mini",
        profile_id=profile_id,
        credential_id=credential_id,
        display_name="Primary OpenAI",
    )
    repository.save_profile(profile)
    repository.set_active_profile_id(profile_id)

    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["schema_version"] == 1
    assert document["active_profile_id"] == profile_id.value
    assert repository.get_profile(profile_id) == profile


def test_profile_crud_active_id_and_credential_isolation(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path / "providers.json")
    first_credential = CredentialId.new()
    second_credential = CredentialId.new()
    deepseek_credential = CredentialId.new()
    for binding in (
        _openai_binding(first_credential),
        _openai_binding(second_credential),
        _deepseek_binding(deepseek_credential),
    ):
        repository.save_credential_binding(binding)

    first = openai_profile(
        "gpt-5-mini",
        profile_id=ProfileId.new(),
        credential_id=first_credential,
        display_name="OpenAI first",
    )
    second = openai_profile(
        "gpt-5-mini",
        profile_id=ProfileId.new(),
        credential_id=second_credential,
        display_name="OpenAI second",
    )
    deepseek = deepseek_profile(
        "deepseek-v4-flash",
        profile_id=ProfileId.new(),
        credential_id=deepseek_credential,
        display_name="DeepSeek first",
    )
    for profile in (first, second, deepseek):
        repository.save_profile(profile)

    updated = replace(first, display_name="Updated", model="gpt-5")
    repository.save_profile(updated)
    repository.set_active_profile_id(second.profile_id)

    assert repository.get_profile(first.profile_id) == updated
    assert repository.get_active_profile_id() == second.profile_id
    assert len(repository.list_profiles()) == 3

    repository.delete_profile(deepseek.profile_id)
    assert repository.get_profile(deepseek.profile_id) is None
    assert (
        repository.get_credential_binding(deepseek_credential)
        is not None
    )


def test_cross_provider_binding_and_referenced_deletion_are_rejected(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path / "providers.json")
    credential_id = CredentialId.new()
    repository.save_credential_binding(
        _openai_binding(credential_id)
    )

    with pytest.raises(ProviderMetadataReferenceError):
        repository.save_profile(
            deepseek_profile(
                "deepseek-v4-flash",
                profile_id=ProfileId.new(),
                credential_id=credential_id,
            )
        )

    profile = openai_profile(
        "gpt-5-mini",
        profile_id=ProfileId.new(),
        credential_id=credential_id,
    )
    repository.save_profile(profile)
    with pytest.raises(ProviderMetadataReferenceError):
        repository.delete_credential_binding(credential_id)

    repository.delete_profile(profile.profile_id)
    repository.delete_credential_binding(credential_id)
    assert repository.get_credential_binding(credential_id) is None


def test_active_profile_cannot_be_deleted(tmp_path: Path) -> None:
    repository = _repository(tmp_path / "providers.json")
    credential_id = CredentialId.new()
    profile = openai_profile(
        "gpt-5-mini",
        profile_id=ProfileId.new(),
        credential_id=credential_id,
    )
    repository.save_credential_binding(
        _openai_binding(credential_id)
    )
    repository.save_profile(profile)
    repository.set_active_profile_id(profile.profile_id)

    with pytest.raises(ProviderMetadataReferenceError):
        repository.delete_profile(profile.profile_id)


@pytest.mark.parametrize("duplicate_kind", ["profile", "binding"])
def test_duplicate_ids_in_json_are_corruption(
    tmp_path: Path,
    duplicate_kind: str,
) -> None:
    path = tmp_path / "providers.json"
    repository = _repository(path)
    credential_id = CredentialId.new()
    profile = openai_profile(
        "gpt-5-mini",
        profile_id=ProfileId.new(),
        credential_id=credential_id,
    )
    repository.save_credential_binding(
        _openai_binding(credential_id)
    )
    repository.save_profile(profile)
    document = json.loads(path.read_text(encoding="utf-8"))
    key = "profiles" if duplicate_kind == "profile" else "credential_bindings"
    document[key].append(document[key][0])
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ProviderMetadataCorruptedError):
        repository.list_profiles()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider_id", "unreviewed"),
        ("protocol", "unreviewed_protocol"),
    ],
)
def test_unknown_provider_or_protocol_is_rejected(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    path = tmp_path / "providers.json"
    repository = _repository(path)
    credential_id = CredentialId.new()
    profile = openai_profile(
        "gpt-5-mini",
        profile_id=ProfileId.new(),
        credential_id=credential_id,
    )
    repository.save_credential_binding(
        _openai_binding(credential_id)
    )
    repository.save_profile(profile)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["profiles"][0][field] = value
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ProviderMetadataCorruptedError):
        repository.list_profiles()


def test_unreviewed_cloud_origin_cannot_be_saved(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path / "providers.json")
    credential_id = CredentialId.new()
    repository.save_credential_binding(
        _openai_binding(credential_id)
    )
    profile = replace(
        openai_profile(
            "gpt-5-mini",
            profile_id=ProfileId.new(),
            credential_id=credential_id,
        ),
        base_url="https://example.invalid",
    )

    with pytest.raises(ProviderMetadataConflictError):
        repository.save_profile(profile)


def test_corrupt_json_and_unknown_schema_are_not_overwritten(
    tmp_path: Path,
) -> None:
    corrupt_path = tmp_path / "corrupt.json"
    corrupt_path.write_text("{not-json", encoding="utf-8")
    corrupt_repository = _repository(corrupt_path)
    with pytest.raises(ProviderMetadataCorruptedError):
        corrupt_repository.list_profiles()
    assert corrupt_path.read_text(encoding="utf-8") == "{not-json"

    unknown_path = tmp_path / "unknown.json"
    unknown: dict[str, object] = {
        "schema_version": 99,
        "active_profile_id": None,
        "profiles": [],
        "credential_bindings": [],
    }
    unknown_path.write_text(json.dumps(unknown), encoding="utf-8")
    unknown_repository = _repository(unknown_path)
    with pytest.raises(ProviderMetadataSchemaError):
        unknown_repository.list_profiles()
    assert json.loads(unknown_path.read_text(encoding="utf-8")) == unknown


def test_explicit_migrator_is_required_for_old_schema(
    tmp_path: Path,
) -> None:
    path = tmp_path / "providers.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 0,
                "active_profile_id": None,
                "profiles": [],
                "credential_bindings": [],
            }
        ),
        encoding="utf-8",
    )

    class _Migrator:
        calls = 0

        def migrate(
            self,
            document: Mapping[str, object],
            *,
            target_version: int,
        ) -> Mapping[str, object]:
            self.calls += 1
            migrated = dict(document)
            migrated["schema_version"] = target_version
            return migrated

    migrator = _Migrator()
    repository = JsonProviderProfileRepository(
        path,
        migrator=migrator,
    )

    assert repository.list_profiles() == ()
    assert migrator.calls == 1


@pytest.mark.parametrize("failure_point", ["flush", "replace"])
def test_atomic_write_failure_preserves_old_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    path = tmp_path / "providers.json"
    repository = _repository(path)
    credential_id = CredentialId.new()
    profile = openai_profile(
        "gpt-5-mini",
        profile_id=ProfileId.new(),
        credential_id=credential_id,
        display_name="Before",
    )
    repository.save_credential_binding(
        _openai_binding(credential_id)
    )
    repository.save_profile(profile)
    before = path.read_bytes()

    def fail(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise OSError(f"{failure_point} failed {_FAKE_API_KEY}")

    if failure_point == "flush":
        monkeypatch.setattr(os, "fsync", fail)
    else:
        monkeypatch.setattr(os, "replace", fail)

    with pytest.raises(ProviderMetadataWriteError) as caught:
        repository.save_profile(
            replace(profile, display_name="After")
        )

    assert path.read_bytes() == before
    assert _repository(path).get_profile(profile.profile_id) == profile
    assert not list(tmp_path.glob("*.tmp"))
    visible = repr(caught.value) + "".join(
        traceback.format_exception(caught.value)
    )
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert _FAKE_API_KEY not in visible


def test_secret_value_and_api_key_never_enter_json(
    tmp_path: Path,
) -> None:
    path = tmp_path / "providers.json"
    repository = _repository(path)
    credential_id = CredentialId.new()
    secret_store = InMemorySecretStore()
    secret_store.set_secret(
        credential_id,
        SecretValue(_FAKE_API_KEY),
    )
    repository.save_credential_binding(
        _openai_binding(credential_id)
    )
    repository.save_profile(
        openai_profile(
            "gpt-5-mini",
            profile_id=ProfileId.new(),
            credential_id=credential_id,
        )
    )

    serialized = path.read_text(encoding="utf-8")
    assert _FAKE_API_KEY not in serialized
    assert "Authorization" not in serialized
    assert "CredentialBlob" not in serialized
    assert "SecretValue" not in serialized

    unsafe = openai_profile(
        "gpt-5-mini",
        profile_id=ProfileId.new(),
        credential_id=credential_id,
        display_name=_FAKE_API_KEY,
    )
    with pytest.raises(ProviderMetadataConflictError) as caught:
        repository.save_profile(unsafe)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert _FAKE_API_KEY not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("provider_id", "credential_id", "model"),
    [
        (
            OPENAI_PROVIDER_ID,
            OPENAI_MANUAL_TEST_CREDENTIAL_ID,
            "gpt-5-mini",
        ),
        (
            DEEPSEEK_PROVIDER_ID,
            DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID,
            "deepseek-v4-flash",
        ),
    ],
)
def test_production_policy_rejects_manual_test_credentials(
    provider_id: ProviderId,
    credential_id: CredentialId,
    model: str,
) -> None:
    with pytest.raises(
        ProviderProfilePolicyError,
        match="Manual verification credentials",
    ):
        build_supported_credential_binding(
            provider_id=provider_id,
            credential_id=credential_id,
            display_name="Forbidden manual binding",
        )
    with pytest.raises(
        ProviderProfilePolicyError,
        match="Manual verification credentials",
    ):
        build_supported_profile(
            provider_id=provider_id,
            profile_id=ProfileId.new(),
            display_name="Forbidden manual profile",
            model=model,
            credential_id=credential_id,
        )
    production_binding = (
        _openai_binding(CredentialId.new())
        if provider_id == OPENAI_PROVIDER_ID
        else _deepseek_binding(CredentialId.new())
    )
    with pytest.raises(
        ProviderProfilePolicyError,
        match="Manual verification credentials",
    ):
        validate_supported_credential_binding(
            replace(
                production_binding,
                credential_id=credential_id,
            )
        )


@pytest.mark.parametrize(
    ("provider_id", "manual_credential_id"),
    [
        (OPENAI_PROVIDER_ID, OPENAI_MANUAL_TEST_CREDENTIAL_ID),
        (
            DEEPSEEK_PROVIDER_ID,
            DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID,
        ),
    ],
)
def test_json_with_manual_test_binding_is_corrupted(
    tmp_path: Path,
    provider_id: ProviderId,
    manual_credential_id: CredentialId,
) -> None:
    path = tmp_path / "providers.json"
    repository = _repository(path)
    production_credential_id = CredentialId.new()
    binding = (
        _openai_binding(production_credential_id)
        if provider_id == OPENAI_PROVIDER_ID
        else _deepseek_binding(production_credential_id)
    )
    repository.save_credential_binding(binding)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["credential_bindings"][0]["credential_id"] = (
        manual_credential_id.value
    )
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ProviderMetadataCorruptedError):
        repository.list_credential_bindings()

    assert json.loads(path.read_text(encoding="utf-8")) == document


def test_protocol_enum_remains_closed() -> None:
    assert ApiProtocol.RESPONSES.value == "responses"
    assert ProviderId("openai") == OPENAI_PROVIDER_ID
