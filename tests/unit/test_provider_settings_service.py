from __future__ import annotations

import asyncio
import logging
import traceback
from pathlib import Path

import pytest

from sjtuclaw.application.active_turn_coordinator import (
    DefaultActiveTurnCoordinator,
)
from sjtuclaw.application.provider_profile_service import (
    ActiveTurnHandling,
    ProviderActivationOptions,
    ProviderProfileServiceError,
)
from sjtuclaw.application.provider_settings_service import (
    ProviderSettingsService,
    ProviderSettingsServiceError,
)
from sjtuclaw.config.secrets import InMemorySecretStore, SecretValue
from sjtuclaw.domain.models import (
    DEEPSEEK_DEFAULT_CREDENTIAL_ID,
    DEEPSEEK_PROVIDER_ID,
    FAKE_DEFAULT_PROFILE_ID,
    FAKE_PROVIDER_ID,
    OPENAI_DEFAULT_CREDENTIAL_ID,
    OPENAI_DEFAULT_PROFILE_ID,
    OPENAI_MANUAL_TEST_CREDENTIAL_ID,
    OPENAI_PROVIDER_ID,
    CredentialBinding,
    CredentialId,
    ProviderCapabilities,
    ProviderProfile,
)
from sjtuclaw.domain.ports import LLMProvider
from sjtuclaw.infrastructure.config.json_provider_profile_repository import (
    JsonProviderProfileRepository,
)
from sjtuclaw.infrastructure.llm.fake_provider import FakeProvider

_OPTIONS = ProviderActivationOptions(
    timeout_seconds=30.0,
    max_retries=0,
    stream=True,
)
_FAKE_SECRET = "sk-test-never-use-provider-settings"


class _FakeFactory:
    def create_profile(
        self,
        profile: ProviderProfile,
        *,
        timeout_seconds: float,
        max_retries: int,
        stream: bool,
    ) -> LLMProvider:
        del timeout_seconds, max_retries, stream
        if profile.provider_id != FAKE_PROVIDER_ID:
            raise ValueError("Fake settings tests activate Fake only.")
        return FakeProvider(response_text="settings-ok")


class _FakeFactoryBuilder:
    def __call__(
        self,
        credential_bindings: tuple[CredentialBinding, ...],
    ) -> _FakeFactory:
        del credential_bindings
        return _FakeFactory()


class _CloseFailureControl:
    def __init__(self) -> None:
        self.fail = True


class _CloseFailingProvider(FakeProvider):
    def __init__(self, control: _CloseFailureControl) -> None:
        super().__init__(response_text="settings-ok")
        self._control = control

    async def aclose(self) -> None:
        if self._control.fail:
            raise RuntimeError("opaque-close-failure")
        await super().aclose()


class _CloseFailingFactory:
    def __init__(self, control: _CloseFailureControl) -> None:
        self._control = control

    def create_profile(
        self,
        profile: ProviderProfile,
        *,
        timeout_seconds: float,
        max_retries: int,
        stream: bool,
    ) -> LLMProvider:
        del profile, timeout_seconds, max_retries, stream
        return _CloseFailingProvider(self._control)


class _CloseFailingFactoryBuilder:
    def __init__(self, control: _CloseFailureControl) -> None:
        self._control = control

    def __call__(
        self,
        credential_bindings: tuple[CredentialBinding, ...],
    ) -> _CloseFailingFactory:
        del credential_bindings
        return _CloseFailingFactory(self._control)


class _ExplodingSecretStore(InMemorySecretStore):
    def set_secret(
        self,
        credential_id: CredentialId,
        value: SecretValue,
    ) -> None:
        del credential_id, value
        raise OSError(_FAKE_SECRET)


class _CountingSecretStore(InMemorySecretStore):
    def __init__(self) -> None:
        super().__init__()
        self.set_calls = 0
        self.delete_calls = 0

    def set_secret(
        self,
        credential_id: CredentialId,
        value: SecretValue,
    ) -> None:
        self.set_calls += 1
        super().set_secret(credential_id, value)

    def delete_secret(self, credential_id: CredentialId) -> None:
        self.delete_calls += 1
        super().delete_secret(credential_id)


class _ProfileIdentityFakeProvider(FakeProvider):
    def __init__(self, profile: ProviderProfile) -> None:
        super().__init__(response_text="settings-ok")
        self._profile = profile

    @property
    def name(self) -> str:
        return self._profile.provider_id.value

    def capabilities(self) -> ProviderCapabilities:
        return self._profile.capabilities


class _AnyProfileFakeFactory:
    def create_profile(
        self,
        profile: ProviderProfile,
        *,
        timeout_seconds: float,
        max_retries: int,
        stream: bool,
    ) -> LLMProvider:
        del timeout_seconds, max_retries, stream
        return _ProfileIdentityFakeProvider(profile)


class _AnyProfileFakeFactoryBuilder:
    def __call__(
        self,
        credential_bindings: tuple[CredentialBinding, ...],
    ) -> _AnyProfileFakeFactory:
        del credential_bindings
        return _AnyProfileFakeFactory()


def _service(
    path: Path,
    *,
    secret_store: InMemorySecretStore | None = None,
) -> tuple[ProviderSettingsService, InMemorySecretStore]:
    store = secret_store or InMemorySecretStore()
    coordinator = DefaultActiveTurnCoordinator()
    service = ProviderSettingsService(
        JsonProviderProfileRepository(path),
        _FakeFactoryBuilder(),
        store,
        turn_coordinator=coordinator,
    )
    service.ensure_builtin_metadata()
    return service, store


def test_settings_snapshot_exposes_only_reviewed_non_sensitive_views(
    tmp_path: Path,
) -> None:
    service, _store = _service(tmp_path / "profiles.json")

    snapshot = service.settings_snapshot(
        runtime_state="ready",
        active_turn=False,
    )

    assert {profile.provider_id for profile in snapshot.profiles} == {
        "fake",
        "openai",
        "deepseek",
    }
    assert len(snapshot.credential_bindings) == 2
    assert all(
        not binding.configured
        for binding in snapshot.credential_bindings
    )
    assert "SecretValue" not in repr(snapshot)
    assert "api_key" not in repr(snapshot).lower()
    assert _FAKE_SECRET not in repr(snapshot)


def test_settings_profile_crud_is_non_sensitive_and_provider_scoped(
    tmp_path: Path,
) -> None:
    service, _store = _service(tmp_path / "profiles.json")

    created = service.create_settings_profile(
        provider_id=FAKE_PROVIDER_ID,
        display_name="Desktop Fake",
        model="fake-v2",
        credential_id=None,
    )
    updated = service.update_settings_profile(
        created.profile_id,
        display_name="Desktop Fake Updated",
        model="fake-v3",
        credential_id=None,
    )
    service.delete_settings_profile(created.profile_id)

    assert updated.display_name == "Desktop Fake Updated"
    assert updated.model == "fake-v3"
    assert service.get_profile(created.profile_id) is None
    with pytest.raises(ProviderSettingsServiceError) as unsupported:
        service.create_settings_profile(
            provider_id=OPENAI_PROVIDER_ID,
            display_name="Missing credential",
            model="gpt-5-mini",
            credential_id=None,
        )
    assert unsupported.value.safe_code == "provider_profile_create_failed"


def test_cloud_profiles_keep_fixed_origins_and_reviewed_bindings(
    tmp_path: Path,
) -> None:
    service, _store = _service(tmp_path / "profiles.json")

    openai_profile = service.create_settings_profile(
        provider_id=OPENAI_PROVIDER_ID,
        display_name="Second OpenAI",
        model="gpt-5-mini",
        credential_id=OPENAI_DEFAULT_CREDENTIAL_ID,
    )
    deepseek_profile = service.create_settings_profile(
        provider_id=DEEPSEEK_PROVIDER_ID,
        display_name="Second DeepSeek",
        model="deepseek-v4-flash",
        credential_id=DEEPSEEK_DEFAULT_CREDENTIAL_ID,
    )
    updated = service.update_settings_profile(
        openai_profile.profile_id,
        display_name="Updated OpenAI",
        model="gpt-5-mini",
        credential_id=OPENAI_DEFAULT_CREDENTIAL_ID,
    )

    assert updated.origin == "https://api.openai.com"
    assert deepseek_profile.origin == "https://api.deepseek.com"
    assert updated.credential_id == OPENAI_DEFAULT_CREDENTIAL_ID
    assert deepseek_profile.credential_id == DEEPSEEK_DEFAULT_CREDENTIAL_ID


def test_settings_credential_save_overwrite_delete_exposes_presence_only(
    tmp_path: Path,
) -> None:
    service, store = _service(tmp_path / "profiles.json")

    service.save_credential(
        OPENAI_DEFAULT_CREDENTIAL_ID,
        _FAKE_SECRET,
    )
    first = service.settings_snapshot(
        runtime_state="ready",
        active_turn=False,
    )
    service.save_credential(
        OPENAI_DEFAULT_CREDENTIAL_ID,
        f"{_FAKE_SECRET}-replacement",
    )
    second = service.settings_snapshot(
        runtime_state="ready",
        active_turn=False,
    )
    service.delete_credential(OPENAI_DEFAULT_CREDENTIAL_ID)
    deleted = service.settings_snapshot(
        runtime_state="ready",
        active_turn=False,
    )

    assert any(
        binding.credential_id == OPENAI_DEFAULT_CREDENTIAL_ID.value
        and binding.configured
        for binding in first.credential_bindings
    )
    assert any(binding.configured for binding in second.credential_bindings)
    assert not any(binding.configured for binding in deleted.credential_bindings)
    assert store.get_secret(OPENAI_DEFAULT_CREDENTIAL_ID) is None
    assert _FAKE_SECRET not in repr((first, second, deleted))


def test_manual_test_credential_id_is_rejected_by_settings_boundary(
    tmp_path: Path,
) -> None:
    service, _store = _service(tmp_path / "profiles.json")

    with pytest.raises(ProviderSettingsServiceError) as caught:
        service.save_credential(
            OPENAI_MANUAL_TEST_CREDENTIAL_ID,
            _FAKE_SECRET,
        )

    assert caught.value.safe_code == "credential_binding_not_found"
    assert _FAKE_SECRET not in repr(caught.value)


def test_active_profile_model_change_requires_switch(
    tmp_path: Path,
) -> None:
    service, _store = _service(tmp_path / "profiles.json")

    async def scenario() -> None:
        await service.activate_profile(
            FAKE_DEFAULT_PROFILE_ID,
            _OPTIONS,
        )
        active = service.get_profile(FAKE_DEFAULT_PROFILE_ID)
        assert active is not None
        with pytest.raises(ProviderSettingsServiceError) as caught:
            service.update_settings_profile(
                active.profile_id,
                display_name=active.display_name,
                model="changed-while-active",
                credential_id=None,
            )
        assert (
            caught.value.safe_code
            == "active_profile_update_requires_switch"
        )
        with pytest.raises(ProviderSettingsServiceError) as credential_change:
            service.update_settings_profile(
                active.profile_id,
                display_name=active.display_name,
                model=active.model,
                credential_id=OPENAI_DEFAULT_CREDENTIAL_ID,
            )
        assert (
            credential_change.value.safe_code
            == "active_profile_update_requires_switch"
        )
        await service.aclose()

    asyncio.run(scenario())


def test_active_profile_credential_write_and_delete_require_switch(
    tmp_path: Path,
) -> None:
    store = _CountingSecretStore()
    service = ProviderSettingsService(
        JsonProviderProfileRepository(tmp_path / "active-credential.json"),
        _AnyProfileFakeFactoryBuilder(),
        store,
        turn_coordinator=DefaultActiveTurnCoordinator(),
    )
    service.ensure_builtin_metadata()
    store.set_secret(OPENAI_DEFAULT_CREDENTIAL_ID, SecretValue(_FAKE_SECRET))

    async def scenario() -> None:
        await service.activate_profile(
            OPENAI_DEFAULT_PROFILE_ID,
            _OPTIONS,
        )
        baseline_set_calls = store.set_calls
        baseline_delete_calls = store.delete_calls

        with pytest.raises(ProviderSettingsServiceError) as save_failure:
            service.save_credential(
                OPENAI_DEFAULT_CREDENTIAL_ID,
                f"{_FAKE_SECRET}-replacement",
            )
        with pytest.raises(ProviderSettingsServiceError) as delete_failure:
            service.delete_credential(OPENAI_DEFAULT_CREDENTIAL_ID)

        assert (
            save_failure.value.safe_code
            == "active_profile_credential_change_requires_switch"
        )
        assert (
            delete_failure.value.safe_code
            == "active_profile_credential_change_requires_switch"
        )
        assert store.set_calls == baseline_set_calls
        assert store.delete_calls == baseline_delete_calls
        assert (
            store.get_secret(OPENAI_DEFAULT_CREDENTIAL_ID)
            is not None
        )
        assert _FAKE_SECRET not in repr(
            (save_failure.value, delete_failure.value)
        )
        await service.aclose()

    asyncio.run(scenario())


def test_cleanup_pending_blocks_settings_mutation(
    tmp_path: Path,
) -> None:
    store = InMemorySecretStore()
    control = _CloseFailureControl()
    coordinator = DefaultActiveTurnCoordinator()
    service = ProviderSettingsService(
        JsonProviderProfileRepository(tmp_path / "cleanup.json"),
        _CloseFailingFactoryBuilder(control),
        store,
        turn_coordinator=coordinator,
    )
    service.ensure_builtin_metadata()
    secondary = service.create_settings_profile(
        provider_id=FAKE_PROVIDER_ID,
        display_name="Secondary Fake",
        model="fake",
        credential_id=None,
    )

    async def scenario() -> None:
        await service.activate_profile(
            FAKE_DEFAULT_PROFILE_ID,
            _OPTIONS,
        )
        with pytest.raises(ProviderProfileServiceError):
            await service.activate_profile(
                secondary.profile_id,
                _OPTIONS,
                turn_handling=ActiveTurnHandling.WAIT_FOR_ACTIVE,
            )
        with pytest.raises(ProviderSettingsServiceError) as caught:
            service.create_settings_profile(
                provider_id=FAKE_PROVIDER_ID,
                display_name="Blocked Fake",
                model="fake",
                credential_id=None,
            )
        assert caught.value.safe_code == "provider_cleanup_pending"
        control.fail = False
        await service.aclose()

    asyncio.run(scenario())


def test_backend_exception_secret_is_absent_from_error_traceback_and_log(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    service, _store = _service(
        tmp_path / "profiles.json",
        secret_store=_ExplodingSecretStore(),
    )
    caught: ProviderSettingsServiceError | None = None
    rendered = ""

    with caplog.at_level(logging.ERROR):
        try:
            service.save_credential(
                OPENAI_DEFAULT_CREDENTIAL_ID,
                _FAKE_SECRET,
            )
        except ProviderSettingsServiceError as error:
            caught = error
            rendered = "".join(
                traceback.format_exception(
                    type(error),
                    error,
                    error.__traceback__,
                )
            )
            logging.exception("safe settings failure")
        else:
            pytest.fail("Expected credential save failure")

    assert caught is not None
    assert caught.safe_code == "credential_save_failed"
    visible = f"{caught!r}\n{rendered}\n{caplog.text}"
    assert _FAKE_SECRET not in visible
    assert caught.__cause__ is None
    assert caught.__context__ is None
