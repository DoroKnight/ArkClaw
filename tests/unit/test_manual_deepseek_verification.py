from __future__ import annotations

import logging
import traceback
from collections.abc import Callable

import pytest
import scripts.manual_deepseek_verification as manual
from scripts.manual_credential_targets import ManualCredentialTargetResolver
from tests.fakes.deepseek_sdk import (
    FakeDeepSeekClientFactory,
    FakeDeepSeekScenario,
)

from arkclaw.config.errors import SecretStoreError
from arkclaw.config.secrets import SecretValue
from arkclaw.domain.models import (
    DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID,
    CredentialId,
)
from arkclaw.infrastructure.llm.deepseek_sdk import (
    DeepSeekEvent,
    DeepSeekEventKind,
    DeepSeekRequest,
    DeepSeekSDKError,
)

_FAKE_KEY = "sk-deepseek-manual-test-never-use"
_BODY = "assistant-body-must-not-be-printed"
_REASONING = "reasoning-content-must-not-be-printed"


class _RecordingStore:
    def __init__(
        self,
        initial: str | None = None,
        *,
        fail_write: bool = False,
        fail_delete: bool = False,
    ) -> None:
        self.values: dict[CredentialId, str] = {}
        if initial is not None:
            self.values[DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID] = initial
        self.fail_write = fail_write
        self.fail_delete = fail_delete
        self.read_count = 0
        self.write_count = 0
        self.delete_count = 0

    def has_secret(self, credential_id: CredentialId) -> bool:
        return credential_id in self.values

    def get_secret(
        self,
        credential_id: CredentialId,
    ) -> SecretValue | None:
        self.read_count += 1
        value = self.values.get(credential_id)
        return SecretValue(value) if value is not None else None

    def set_secret(
        self,
        credential_id: CredentialId,
        value: SecretValue,
    ) -> None:
        self.write_count += 1
        if self.fail_write:
            raise RuntimeError(f"write failed {_FAKE_KEY}")
        self.values[credential_id] = value.reveal()

    def delete_secret(self, credential_id: CredentialId) -> None:
        self.delete_count += 1
        if self.fail_delete:
            raise RuntimeError(f"delete failed {_FAKE_KEY}")
        self.values.pop(credential_id, None)

    def has_openai_api_key(self) -> bool:
        return False

    def get_openai_api_key(self) -> SecretValue | None:
        return None

    def set_openai_api_key(self, value: SecretValue) -> None:
        del value
        raise AssertionError("OpenAI facade must not be used")

    def delete_openai_api_key(self) -> None:
        raise AssertionError("OpenAI facade must not be used")


class _ReplacingStore(_RecordingStore):
    def get_secret(
        self,
        credential_id: CredentialId,
    ) -> SecretValue | None:
        if self.read_count == 2:
            self.values[credential_id] = "external-replacement-never-use"
        return super().get_secret(credential_id)


class _ReplaceAfterDeleteStore(_RecordingStore):
    external_value = "external-after-delete-never-use"

    def delete_secret(self, credential_id: CredentialId) -> None:
        super().delete_secret(credential_id)
        self.values[credential_id] = self.external_value


class _FailReadAfterDeleteStore(_RecordingStore):
    def __init__(self) -> None:
        super().__init__()
        self.deleted = False

    def get_secret(
        self,
        credential_id: CredentialId,
    ) -> SecretValue | None:
        if self.deleted:
            raise RuntimeError(
                f"credential read failed after delete {_FAKE_KEY}"
            )
        return super().get_secret(credential_id)

    def delete_secret(self, credential_id: CredentialId) -> None:
        super().delete_secret(credential_id)
        self.deleted = True


class _Prompt:
    def __init__(
        self,
        value: str | Exception,
        *,
        on_call: Callable[[], None] | None = None,
    ) -> None:
        self.value = value
        self.on_call = on_call
        self.calls = 0

    def __call__(self, prompt: str) -> str:
        del prompt
        self.calls += 1
        if self.on_call is not None:
            self.on_call()
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


def _text(value: str = _BODY) -> DeepSeekEvent:
    return DeepSeekEvent(
        kind=DeepSeekEventKind.TEXT_DELTA,
        text=value,
    )


def _completed() -> DeepSeekEvent:
    return DeepSeekEvent(
        kind=DeepSeekEventKind.COMPLETED,
        finish_reason="stop",
    )


def _success_scenarios() -> tuple[FakeDeepSeekScenario, ...]:
    return (
        FakeDeepSeekScenario(events=(_text("one"), _completed())),
        FakeDeepSeekScenario(events=(_text("two"), _completed())),
        FakeDeepSeekScenario(events=(_text("cancel"), _completed())),
        FakeDeepSeekScenario(events=(_text("reuse"), _completed())),
        FakeDeepSeekScenario(
            create_error=DeepSeekSDKError("invalid_api_key")
        ),
        FakeDeepSeekScenario(events=(_text("restored"), _completed())),
    )


def _dependencies(
    *,
    store: _RecordingStore | None = None,
    sdk: FakeDeepSeekClientFactory | None = None,
    confirmation: str | Exception = "RUN",
    secret: str | Exception = _FAKE_KEY,
    output: list[str] | None = None,
    get_secret_on_call: Callable[[], None] | None = None,
    platform: str = "win32",
    sdk_version: str = "2.48.0",
) -> tuple[
    manual.ManualDeepSeekDependencies,
    _RecordingStore,
    FakeDeepSeekClientFactory,
    _Prompt,
    list[str],
]:
    selected_store = store or _RecordingStore()
    selected_sdk = sdk or FakeDeepSeekClientFactory(
        _success_scenarios()
    )
    secret_prompt = _Prompt(
        secret,
        on_call=get_secret_on_call,
    )
    outputs = output if output is not None else []
    dependencies = manual.ManualDeepSeekDependencies(
        platform=platform,
        sdk_version=sdk_version,
        store_factory=lambda: selected_store,
        client_factory=selected_sdk,
        input_text=_Prompt(confirmation),
        get_secret=secret_prompt,
        output=outputs.append,
    )
    return (
        dependencies,
        selected_store,
        selected_sdk,
        secret_prompt,
        outputs,
    )


def test_default_entry_is_completely_inert(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def explode() -> manual.ManualDeepSeekDependencies:
        raise AssertionError("dependencies must remain lazy")

    monkeypatch.setattr(manual, "_default_dependencies", explode)

    exit_code = manual.main([])

    assert exit_code == 0
    assert capsys.readouterr().out == (
        "safe_code=manual_verification_disabled\n"
    )


def test_real_store_factory_explicitly_injects_manual_target_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    expected_store = _RecordingStore()

    def fake_windows_store(
        *,
        target_resolver: object,
    ) -> _RecordingStore:
        captured["target_resolver"] = target_resolver
        return expected_store

    monkeypatch.setattr(
        manual,
        "WindowsCredentialSecretStore",
        fake_windows_store,
    )

    assert manual._windows_store_factory() is expected_store
    assert isinstance(
        captured["target_resolver"],
        ManualCredentialTargetResolver,
    )


def test_confirmation_failure_does_not_construct_store() -> None:
    dependencies, _, sdk, secret_prompt, outputs = _dependencies(
        confirmation="NO",
    )
    store_calls = 0

    def store_factory() -> _RecordingStore:
        nonlocal store_calls
        store_calls += 1
        return _RecordingStore()

    dependencies = manual.ManualDeepSeekDependencies(
        platform=dependencies.platform,
        sdk_version=dependencies.sdk_version,
        store_factory=store_factory,
        client_factory=dependencies.client_factory,
        input_text=dependencies.input_text,
        get_secret=dependencies.get_secret,
        output=dependencies.output,
    )

    exit_code = manual.main(
        ["--confirm-real-api"],
        dependencies=dependencies,
    )

    assert exit_code == 2
    assert store_calls == 0
    assert secret_prompt.calls == 0
    assert sdk.create_count == 0
    assert outputs == ["safe_code=confirmation_failed"]


def test_occupied_target_is_not_read_overwritten_or_deleted() -> None:
    existing = "external-value-never-use"
    store = _RecordingStore(initial=existing)
    dependencies, _, sdk, secret_prompt, outputs = _dependencies(
        store=store
    )

    exit_code = manual.main(
        ["--confirm-real-api"],
        dependencies=dependencies,
    )

    assert exit_code != 0
    assert secret_prompt.calls == 0
    assert store.values[DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID] == existing
    assert store.write_count == 0
    assert store.delete_count == 0
    assert sdk.create_count == 0
    assert any("safe_code=test_target_occupied" in line for line in outputs)


def test_target_occupied_during_hidden_input_is_not_overwritten() -> None:
    store = _RecordingStore()

    def occupy() -> None:
        store.values[DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID] = (
            "external-racing-value"
        )

    dependencies, _, sdk, secret_prompt, outputs = _dependencies(
        store=store,
        get_secret_on_call=occupy,
    )

    exit_code = manual.main(
        ["--confirm-real-api"],
        dependencies=dependencies,
    )

    assert exit_code != 0
    assert secret_prompt.calls == 1
    assert store.write_count == 0
    assert store.delete_count == 0
    assert sdk.create_count == 0
    assert any("safe_code=test_target_occupied" in line for line in outputs)


@pytest.mark.parametrize(
    ("store", "secret", "expected_code"),
    [
        (
            _RecordingStore(fail_write=True),
            _FAKE_KEY,
            "credential_setup_failed",
        ),
        (
            _RecordingStore(),
            "   ",
            "invalid_api_key_input",
        ),
        (
            _RecordingStore(),
            RuntimeError(f"getpass failed {_FAKE_KEY}"),
            "credential_setup_failed",
        ),
    ],
)
def test_credential_setup_failures_are_safe(
    store: _RecordingStore,
    secret: str | Exception,
    expected_code: str,
) -> None:
    dependencies, _, sdk, _, outputs = _dependencies(
        store=store,
        secret=secret,
    )

    exit_code = manual.main(
        ["--confirm-real-api"],
        dependencies=dependencies,
    )

    visible = "\n".join(outputs)
    assert exit_code != 0
    assert expected_code in visible
    assert _FAKE_KEY not in visible
    assert sdk.create_count == 0


def test_owned_store_detects_replacement_without_deleting_it() -> None:
    store = _RecordingStore()
    owned = manual.OwnedDeepSeekTestSecretStore(store)
    owned.set_secret(
        DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID,
        SecretValue(_FAKE_KEY),
    )
    external = "external-replacement-never-use"
    store.values[DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID] = external

    with pytest.raises(SecretStoreError):
        owned.get_secret(DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID)
    with pytest.raises(SecretStoreError):
        owned.delete_secret(DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID)

    assert owned.ownership_lost
    assert store.values[DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID] == external
    assert store.delete_count == 0


def test_ownership_loss_during_provider_read_stops_without_deleting() -> None:
    store = _ReplacingStore()
    dependencies, _, sdk, _, outputs = _dependencies(store=store)

    exit_code = manual.main(
        ["--confirm-real-api"],
        dependencies=dependencies,
    )

    assert exit_code != 0
    assert any(
        "safe_code=test_target_ownership_lost" in line
        for line in outputs
    )
    assert store.values[DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID] == (
        "external-replacement-never-use"
    )
    assert store.delete_count == 0
    assert sdk.create_count == 0


def test_external_replacement_after_delete_is_not_deleted_or_exposed(
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = _ReplaceAfterDeleteStore()
    owned = manual.OwnedDeepSeekTestSecretStore(store)
    owned.set_secret(
        DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID,
        SecretValue(_FAKE_KEY),
    )

    caught: SecretStoreError | None = None
    try:
        owned.cleanup_owned()
    except SecretStoreError as error:
        caught = error
        rendered = "".join(traceback.format_exception(error))
        with caplog.at_level(logging.ERROR):
            logging.getLogger("test.deepseek-cleanup").exception(
                "DeepSeek test Target ownership was lost safely."
            )
        captured = capsys.readouterr()
        visible = (
            rendered
            + caplog.text
            + repr(error)
            + captured.out
            + captured.err
        )
    else:
        raise AssertionError("external replacement was not detected")

    assert caught is not None
    assert caught.__cause__ is None
    assert caught.__context__ is None
    assert owned.ownership_lost
    assert store.delete_count == 1
    assert store.values[DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID] == (
        store.external_value
    )
    assert store.external_value not in visible
    assert _FAKE_KEY not in visible


def test_external_replacement_after_delete_sets_final_ownership_code() -> None:
    store = _ReplaceAfterDeleteStore()
    dependencies, _, _, _, outputs = _dependencies(store=store)

    exit_code = manual.main(
        ["--confirm-real-api"],
        dependencies=dependencies,
    )

    assert exit_code != 0
    assert outputs[-1] == (
        "verification_complete=False "
        "safe_code=test_target_ownership_lost"
    )
    assert store.delete_count == 1
    assert store.values[DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID] == (
        store.external_value
    )
    assert store.external_value not in "\n".join(outputs)


def test_cleanup_read_failure_has_distinct_safe_code() -> None:
    store = _FailReadAfterDeleteStore()
    dependencies, _, _, _, outputs = _dependencies(store=store)

    exit_code = manual.main(
        ["--confirm-real-api"],
        dependencies=dependencies,
    )

    visible = "\n".join(outputs)
    assert exit_code != 0
    assert outputs[-1] == (
        "verification_complete=False "
        "safe_code=credential_store_unavailable"
    )
    assert store.delete_count == 1
    assert _FAKE_KEY not in visible


def test_false_cleanup_result_cannot_leave_safe_code_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dependencies, _, _, _, outputs = _dependencies()

    def fail_cleanup(
        owned: manual.OwnedDeepSeekTestSecretStore,
    ) -> bool:
        del owned
        return False

    monkeypatch.setattr(
        manual.OwnedDeepSeekTestSecretStore,
        "cleanup_owned",
        fail_cleanup,
    )

    exit_code = manual.main(
        ["--confirm-real-api"],
        dependencies=dependencies,
    )

    assert exit_code != 0
    assert outputs[-1] == (
        "verification_complete=False safe_code=target_cleanup_failed"
    )


def test_complete_fake_verification_enforces_all_safety_checks() -> None:
    previous_logging = logging.root.manager.disable
    dependencies, store, sdk, _, outputs = _dependencies()

    exit_code = manual.main(
        ["--confirm-real-api"],
        dependencies=dependencies,
    )

    visible = "\n".join(outputs)
    delegate_requests = sum(
        len(client.requests)
        for client in sdk.clients
    )
    assert exit_code == 0
    assert "verification_complete=True safe_code=none" in visible
    assert "request_attempts=6" in visible
    assert "delegate_create_calls=6" in visible
    assert delegate_requests == 6
    assert sdk.network_request_count == 0
    assert DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID not in store.values
    assert all(client.closed for client in sdk.clients)
    assert all(
        stream.closed
        for client in sdk.clients
        for stream in client.streams
    )
    assert logging.root.manager.disable == previous_logging
    assert _FAKE_KEY not in visible
    assert _BODY not in visible
    assert _REASONING not in visible
    assert "continuation" not in visible.lower()


@pytest.mark.parametrize("failure_kind", ["stream", "client", "delete"])
def test_cleanup_failure_never_reports_success(failure_kind: str) -> None:
    scenarios = list(_success_scenarios())
    store = _RecordingStore(fail_delete=failure_kind == "delete")
    if failure_kind == "stream":
        scenarios[0].stream_close_failures = 1
    if failure_kind == "client":
        scenarios[3].client_close_failures = 1
    sdk = FakeDeepSeekClientFactory(tuple(scenarios))
    dependencies, _, _, _, outputs = _dependencies(
        store=store,
        sdk=sdk,
    )

    exit_code = manual.main(
        ["--confirm-real-api"],
        dependencies=dependencies,
    )

    assert exit_code != 0
    assert not any(
        "verification_complete=True" in line for line in outputs
    )


def test_non_text_event_cannot_satisfy_cancellation_check() -> None:
    scenarios = list(_success_scenarios())
    scenarios[2] = FakeDeepSeekScenario(
        events=(
            DeepSeekEvent(kind=DeepSeekEventKind.METADATA),
            _completed(),
        )
    )
    dependencies, _, _, _, outputs = _dependencies(
        sdk=FakeDeepSeekClientFactory(tuple(scenarios))
    )

    exit_code = manual.main(
        ["--confirm-real-api"],
        dependencies=dependencies,
    )

    assert exit_code != 0
    assert any(
        "cancellation_verification_failed" in line
        for line in outputs
    )


def test_failure_to_reuse_after_cancellation_fails_verification() -> None:
    scenarios = list(_success_scenarios())
    scenarios[3] = FakeDeepSeekScenario(
        create_error=DeepSeekSDKError("provider_unavailable")
    )
    dependencies, _, _, _, outputs = _dependencies(
        sdk=FakeDeepSeekClientFactory(tuple(scenarios))
    )

    exit_code = manual.main(
        ["--confirm-real-api"],
        dependencies=dependencies,
    )

    assert exit_code != 0
    assert not any(
        "verification_complete=True" in line for line in outputs
    )


def test_sensitive_provider_failure_is_not_printed() -> None:
    sensitive = f"{_FAKE_KEY} {_BODY} {_REASONING} Authorization"
    scenarios = list(_success_scenarios())
    scenarios[0] = FakeDeepSeekScenario(
        create_error=RuntimeError(sensitive)
    )
    dependencies, _, _, _, outputs = _dependencies(
        sdk=FakeDeepSeekClientFactory(tuple(scenarios))
    )

    exit_code = manual.main(
        ["--confirm-real-api"],
        dependencies=dependencies,
    )

    visible = "\n".join(outputs)
    assert exit_code != 0
    assert _FAKE_KEY not in visible
    assert _BODY not in visible
    assert _REASONING not in visible
    assert "Authorization" not in visible
    assert "Traceback" not in visible


@pytest.mark.parametrize(
    ("platform", "sdk_version", "safe_code"),
    [
        ("linux", "2.48.0", "unsupported_platform"),
        ("win32", "0.0.0", "sdk_version_mismatch"),
    ],
)
def test_platform_and_sdk_mismatch_fail_before_store(
    platform: str,
    sdk_version: str,
    safe_code: str,
) -> None:
    dependencies, store, sdk, prompt, outputs = _dependencies(
        platform=platform,
        sdk_version=sdk_version,
    )

    exit_code = manual.main(
        ["--confirm-real-api"],
        dependencies=dependencies,
    )

    assert exit_code != 0
    assert store.read_count == 0
    assert prompt.calls == 0
    assert sdk.create_count == 0
    assert any(safe_code in line for line in outputs)


def test_audit_rejects_nonzero_retries_before_client_creation() -> None:
    sdk = FakeDeepSeekClientFactory()
    audit = manual._AuditFactory(sdk)

    with pytest.raises(Exception, match="failed safely"):
        audit.create(
            api_key=_FAKE_KEY,
            timeout_seconds=60.0,
            max_retries=1,
        )

    assert sdk.create_count == 0
    assert audit.retries_disabled is False


@pytest.mark.parametrize(
    "candidate",
    [
        DeepSeekRequest(
            model="modified-model",
            messages=(
                {"role": "user", "content": "offline"},
            ),
            max_tokens=256,
        ),
        DeepSeekRequest(
            model="deepseek-v4-flash",
            messages=(
                {"role": "user", "content": "offline"},
            ),
            max_tokens=257,
        ),
    ],
)
def test_audit_rejects_modified_model_or_budget(
    candidate: DeepSeekRequest,
) -> None:
    audit = manual._AuditFactory(FakeDeepSeekClientFactory())

    with pytest.raises(
        manual._ManualVerificationFailure,
        match="failed safely",
    ):
        audit.validate_request(candidate)

    assert audit.requests_valid is False
