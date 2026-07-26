from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import threading
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import (
    QApplication,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
)

from sjtuclaw.application.provider_profile_service import (
    ActiveTurnHandling,
    ProviderActivationOptions,
)
from sjtuclaw.application.provider_settings_service import (
    CredentialBindingView,
    ProviderCapabilitiesView,
    ProviderProfileView,
    ProviderSettingsSnapshot,
)
from sjtuclaw.application.runtime_session_controller import (
    RuntimeEventSink,
    RuntimeSessionController,
)
from sjtuclaw.bootstrap.qt_runtime import (
    ProductionQtRuntimeCompositionRoot,
)
from sjtuclaw.config.secrets import InMemorySecretStore, SecretValue
from sjtuclaw.domain.events import LLMEvent
from sjtuclaw.domain.models import (
    FAKE_DEFAULT_PROFILE_ID,
    OPENAI_DEFAULT_CREDENTIAL_ID,
    OPENAI_DEFAULT_PROFILE_ID,
    OPENAI_MANUAL_TEST_CREDENTIAL_ID,
    CredentialId,
    LLMRequest,
)
from sjtuclaw.infrastructure.llm.fake_provider import FakeProvider
from sjtuclaw.infrastructure.llm.provider_factory import ProviderFactory
from sjtuclaw.presentation.qt.main_window import MainWindow
from sjtuclaw.presentation.qt.provider_settings_dialog import (
    ProviderSettingsDialog,
)
from sjtuclaw.presentation.qt.runtime_bridge import QtRuntimeBridge
from sjtuclaw.presentation.qt.runtime_thread import (
    RuntimeThreadCommand,
    RuntimeThreadCommandType,
)

_FAKE_SECRET = "sk-test-never-use-qt-settings"
_OPTIONS = ProviderActivationOptions(
    timeout_seconds=30.0,
    max_retries=0,
    stream=True,
)


class _CountingSecretStore(InMemorySecretStore):
    def __init__(self) -> None:
        super().__init__()
        self.has_calls = 0
        self.get_calls = 0
        self.set_calls = 0
        self.delete_calls = 0
        self.thread_ids: list[int] = []

    def has_secret(self, credential_id: CredentialId) -> bool:
        self.has_calls += 1
        self.thread_ids.append(threading.get_ident())
        return super().has_secret(credential_id)

    def get_secret(
        self,
        credential_id: CredentialId,
    ) -> SecretValue | None:
        self.get_calls += 1
        self.thread_ids.append(threading.get_ident())
        return super().get_secret(credential_id)

    def set_secret(
        self,
        credential_id: CredentialId,
        value: SecretValue,
    ) -> None:
        self.set_calls += 1
        self.thread_ids.append(threading.get_ident())
        super().set_secret(credential_id, value)

    def delete_secret(self, credential_id: CredentialId) -> None:
        self.delete_calls += 1
        self.thread_ids.append(threading.get_ident())
        super().delete_secret(credential_id)


class _BlockingSecretStore(_CountingSecretStore):
    def __init__(
        self,
        entered: threading.Event,
        release: threading.Event,
    ) -> None:
        super().__init__()
        self._entered = entered
        self._release = release

    def has_secret(self, credential_id: CredentialId) -> bool:
        self._entered.set()
        self._release.wait()
        return super().has_secret(credential_id)


class _GatedProductionRoot:
    def __init__(
        self,
        delegate: ProductionQtRuntimeCompositionRoot,
        entered: threading.Event,
        release: threading.Event,
    ) -> None:
        self._delegate = delegate
        self._entered = entered
        self._release = release

    def __call__(
        self,
        event_sink: RuntimeEventSink,
        runtime_thread_id: int,
    ) -> RuntimeSessionController:
        self._entered.set()
        self._release.wait()
        return self._delegate(event_sink, runtime_thread_id)


@pytest.fixture(scope="module")
def qt_application() -> Iterator[QApplication]:
    existing = QApplication.instance()
    app = existing if isinstance(existing, QApplication) else QApplication([])
    yield app


def _rows(spy: QSignalSpy) -> list[list[object]]:
    return [list(spy.at(index)) for index in range(spy.count())]


def _run_until(
    predicate: Callable[[], bool],
    *,
    timeout_ms: int = 5_000,
) -> bool:
    if predicate():
        return True
    event_loop = QEventLoop()
    poll_timer = QTimer()
    timeout_timer = QTimer()
    timeout_timer.setSingleShot(True)

    def poll() -> None:
        if predicate():
            event_loop.quit()

    poll_timer.timeout.connect(poll)
    timeout_timer.timeout.connect(event_loop.quit)
    poll_timer.start(1)
    timeout_timer.start(timeout_ms)
    event_loop.exec()
    poll_timer.stop()
    timeout_timer.stop()
    return predicate()


def _wait_command(spy: QSignalSpy, command_id: str) -> None:
    assert _run_until(
        lambda: any(row[0] == command_id for row in _rows(spy))
    )


def _start_bridge(
    tmp_path: Path,
) -> tuple[QtRuntimeBridge, _CountingSecretStore]:
    store = _CountingSecretStore()
    bridge = QtRuntimeBridge(
        ProductionQtRuntimeCompositionRoot(
            tmp_path / "profiles.json",
            secret_store_factory=lambda: store,
        )
    )
    ready_spy = QSignalSpy(bridge.runtime_ready)
    bridge.start_runtime()
    assert _run_until(lambda: ready_spy.count() == 1)
    return bridge, store


def _shutdown_bridge(bridge: QtRuntimeBridge) -> None:
    shutdown_spy = QSignalSpy(bridge.shutdown_finished)
    bridge.shutdown(cancel_active=True)
    assert _run_until(lambda: shutdown_spy.count() == 1)
    assert _rows(shutdown_spy) == [[True, "none"]]
    assert not bridge.runtime_thread.isRunning()
    assert bridge.runtime_thread.pending_task_count_at_close == 0


def _dialog_snapshot(
    *,
    active_turn: bool,
    cleanup_pending: bool,
) -> ProviderSettingsSnapshot:
    capabilities = ProviderCapabilitiesView(
        streaming=True,
        tools=False,
        embeddings=False,
        continuation_mode="replay_messages",
        protocol="internal",
    )
    profile = ProviderProfileView(
        profile_id="fake-dialog-profile",
        display_name="Dialog Fake",
        provider_id="fake",
        model="fake",
        credential_id=None,
        fixed_origin=None,
        capabilities=capabilities,
        is_runtime_profile=False,
    )
    binding = CredentialBindingView(
        credential_id=OPENAI_DEFAULT_CREDENTIAL_ID.value,
        display_name="OpenAI default credential",
        provider_id="openai",
        fixed_origin="https://api.openai.com",
        configured=False,
    )
    return ProviderSettingsSnapshot(
        profiles=(profile,),
        credential_bindings=(binding,),
        stored_active_profile_id=profile.profile_id,
        runtime_profile_id=None,
        provider_lifecycle=(
            "cleanup_pending" if cleanup_pending else "active"
        ),
        runtime_state="ready",
        active_turn=active_turn,
        cleanup_pending=cleanup_pending,
    )


def _active_openai_dialog_snapshot() -> ProviderSettingsSnapshot:
    capabilities = ProviderCapabilitiesView(
        streaming=True,
        tools=True,
        embeddings=False,
        continuation_mode="replay_output_items",
        protocol="responses",
    )
    profile = ProviderProfileView(
        profile_id=OPENAI_DEFAULT_PROFILE_ID.value,
        display_name="OpenAI",
        provider_id="openai",
        model="gpt-5-mini",
        credential_id=OPENAI_DEFAULT_CREDENTIAL_ID.value,
        fixed_origin="https://api.openai.com",
        capabilities=capabilities,
        is_runtime_profile=True,
    )
    binding = CredentialBindingView(
        credential_id=OPENAI_DEFAULT_CREDENTIAL_ID.value,
        display_name="OpenAI default credential",
        provider_id="openai",
        fixed_origin="https://api.openai.com",
        configured=True,
    )
    return ProviderSettingsSnapshot(
        profiles=(profile,),
        credential_bindings=(binding,),
        stored_active_profile_id=profile.profile_id,
        runtime_profile_id=profile.profile_id,
        provider_lifecycle="active",
        runtime_state="ready",
        active_turn=False,
        cleanup_pending=False,
    )


def test_production_composition_root_is_lazy_until_runtime_thread(
    tmp_path: Path,
    qt_application: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del qt_application
    store = _CountingSecretStore()
    store_factory_calls = 0
    provider_factory_calls = 0
    original_provider_factory_init = ProviderFactory.__init__

    def make_store() -> _CountingSecretStore:
        nonlocal store_factory_calls
        store_factory_calls += 1
        return store

    def count_provider_factory(
        factory: ProviderFactory,
        *args: object,
        **kwargs: object,
    ) -> None:
        nonlocal provider_factory_calls
        provider_factory_calls += 1
        original_provider_factory_init(factory, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        ProviderFactory,
        "__init__",
        count_provider_factory,
    )
    root = ProductionQtRuntimeCompositionRoot(
        tmp_path / "lazy-profiles.json",
        secret_store_factory=make_store,
    )
    assert store_factory_calls == 0
    assert provider_factory_calls == 0
    assert store.has_calls == 0
    bridge = QtRuntimeBridge(root)
    ready_spy = QSignalSpy(bridge.runtime_ready)
    bridge.start_runtime()
    assert _run_until(lambda: ready_spy.count() == 1)

    assert store_factory_calls == 1
    assert provider_factory_calls == 1
    assert store.has_calls == 0
    assert store.get_calls == 0
    assert store.set_calls == 0
    assert store.delete_calls == 0
    assert bridge.runtime_thread.runtime_thread_id != threading.get_ident()
    _shutdown_bridge(bridge)


def test_qt_settings_crud_and_credential_flow_stay_in_runtime_thread(
    tmp_path: Path,
    qt_application: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del qt_application
    bridge, store = _start_bridge(tmp_path)
    settings_spy = QSignalSpy(bridge.provider_settings_changed)
    completed_spy = QSignalSpy(bridge.command_completed)
    failed_spy = QSignalSpy(bridge.command_failed)
    captured: list[RuntimeThreadCommand] = []
    settings_signal_thread_ids: list[int] = []
    original_submit = bridge.runtime_thread.submit

    def capture_submit(command: RuntimeThreadCommand) -> bool:
        captured.append(command)
        return original_submit(command)

    monkeypatch.setattr(bridge.runtime_thread, "submit", capture_submit)
    bridge.provider_settings_changed.connect(
        lambda _command_id, _snapshot: settings_signal_thread_ids.append(
            threading.get_ident()
        )
    )
    request_id = bridge.request_provider_settings()
    _wait_command(completed_spy, request_id)
    assert store.has_calls == 2
    assert store.thread_ids
    assert set(store.thread_ids) == {bridge.runtime_thread.runtime_thread_id}
    assert settings_signal_thread_ids == [threading.get_ident()]

    create_id = bridge.create_provider_profile(
        provider_id="fake",
        display_name="GUI Fake",
        model="fake-gui",
        credential_id=None,
    )
    _wait_command(completed_spy, create_id)
    create_snapshot = next(
        row[1]
        for row in _rows(settings_spy)
        if row[0] == create_id
    )
    assert isinstance(create_snapshot, ProviderSettingsSnapshot)
    created = next(
        profile
        for profile in create_snapshot.profiles
        if profile.display_name == "GUI Fake"
    )

    update_id = bridge.update_provider_profile(
        profile_id=created.profile_id,
        display_name="GUI Fake Updated",
        model="fake-gui-v2",
        credential_id=None,
    )
    _wait_command(completed_spy, update_id)
    save_id = bridge.save_provider_credential(
        OPENAI_DEFAULT_CREDENTIAL_ID.value,
        _FAKE_SECRET,
    )
    _wait_command(completed_spy, save_id)
    assert store.set_calls == 1
    save_command = next(
        command
        for command in captured
        if command.command_id == save_id
    )
    assert save_command.secret == ""
    assert _FAKE_SECRET not in repr(save_command)
    assert _FAKE_SECRET not in repr(
        _rows(settings_spy) + _rows(completed_spy) + _rows(failed_spy)
    )
    assert set(settings_signal_thread_ids) == {threading.get_ident()}

    delete_key_id = bridge.delete_provider_credential(
        OPENAI_DEFAULT_CREDENTIAL_ID.value
    )
    _wait_command(completed_spy, delete_key_id)
    delete_profile_id = bridge.delete_provider_profile(created.profile_id)
    _wait_command(completed_spy, delete_profile_id)

    assert store.delete_calls == 1
    for command_id in (
        request_id,
        create_id,
        update_id,
        save_id,
        delete_key_id,
        delete_profile_id,
    ):
        terminal_count = sum(
            row[0] == command_id
            for row in _rows(completed_spy) + _rows(failed_spy)
        )
        assert terminal_count == 1
    _shutdown_bridge(bridge)


def test_qt_settings_reject_manual_test_credential_without_store_access(
    tmp_path: Path,
    qt_application: QApplication,
) -> None:
    del qt_application
    bridge, store = _start_bridge(tmp_path)
    failed_spy = QSignalSpy(bridge.command_failed)

    command_id = bridge.save_provider_credential(
        OPENAI_MANUAL_TEST_CREDENTIAL_ID.value,
        _FAKE_SECRET,
    )
    _wait_command(failed_spy, command_id)
    failure = next(row for row in _rows(failed_spy) if row[0] == command_id)

    assert failure[1] == "credential_binding_not_found"
    assert store.set_calls == 0
    assert _FAKE_SECRET not in repr(failure)
    _shutdown_bridge(bridge)


def test_qt_settings_reject_active_credential_mutation_before_store_access(
    tmp_path: Path,
    qt_application: QApplication,
) -> None:
    del qt_application
    bridge, store = _start_bridge(tmp_path)
    completed_spy = QSignalSpy(bridge.command_completed)
    failed_spy = QSignalSpy(bridge.command_failed)

    save_id = bridge.save_provider_credential(
        OPENAI_DEFAULT_CREDENTIAL_ID.value,
        _FAKE_SECRET,
    )
    _wait_command(completed_spy, save_id)
    activate_id = bridge.activate_profile(
        OPENAI_DEFAULT_PROFILE_ID.value,
        _OPTIONS,
        None,
    )
    _wait_command(completed_spy, activate_id)
    baseline_set_calls = store.set_calls
    baseline_delete_calls = store.delete_calls

    rejected_save_id = bridge.save_provider_credential(
        OPENAI_DEFAULT_CREDENTIAL_ID.value,
        f"{_FAKE_SECRET}-replacement",
    )
    rejected_delete_id = bridge.delete_provider_credential(
        OPENAI_DEFAULT_CREDENTIAL_ID.value
    )
    _wait_command(failed_spy, rejected_save_id)
    _wait_command(failed_spy, rejected_delete_id)

    failures = {
        row[0]: row for row in _rows(failed_spy)
    }
    assert failures[rejected_save_id][1] == (
        "active_profile_credential_change_requires_switch"
    )
    assert failures[rejected_delete_id][1] == (
        "active_profile_credential_change_requires_switch"
    )
    assert store.set_calls == baseline_set_calls
    assert store.delete_calls == baseline_delete_calls
    assert _FAKE_SECRET not in repr(
        (failures[rejected_save_id], failures[rejected_delete_id])
    )
    _shutdown_bridge(bridge)


def test_qt_settings_submission_is_non_blocking_while_store_is_busy(
    tmp_path: Path,
    qt_application: QApplication,
) -> None:
    del qt_application
    entered = threading.Event()
    release = threading.Event()
    store = _BlockingSecretStore(entered, release)
    bridge = QtRuntimeBridge(
        ProductionQtRuntimeCompositionRoot(
            tmp_path / "blocking-settings.json",
            secret_store_factory=lambda: store,
        )
    )
    ready_spy = QSignalSpy(bridge.runtime_ready)
    completed_spy = QSignalSpy(bridge.command_completed)
    bridge.start_runtime()
    assert _run_until(lambda: ready_spy.count() == 1)

    command_id = bridge.request_provider_settings()
    assert command_id
    assert _run_until(entered.is_set)
    gui_timer_fired = threading.Event()
    QTimer.singleShot(0, gui_timer_fired.set)
    assert _run_until(gui_timer_fired.is_set)
    assert not any(row[0] == command_id for row in _rows(completed_spy))

    release.set()
    _wait_command(completed_spy, command_id)
    _shutdown_bridge(bridge)


def test_provider_settings_dialog_enforces_password_cleanup_and_turn_choice(
    tmp_path: Path,
    qt_application: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del qt_application
    bridge = QtRuntimeBridge(
        ProductionQtRuntimeCompositionRoot(
            tmp_path / "dialog.json",
            secret_store_factory=_CountingSecretStore,
        )
    )
    dialog = ProviderSettingsDialog(bridge)
    activations: list[tuple[str, ActiveTurnHandling | None]] = []

    def capture_activation(
        profile_id: str,
        options: ProviderActivationOptions,
        handling: ActiveTurnHandling | None,
    ) -> str:
        del options
        activations.append((profile_id, handling))
        return "captured-activation"

    monkeypatch.setattr(bridge, "activate_profile", capture_activation)
    dialog._on_settings_changed(
        "settings",
        _dialog_snapshot(active_turn=True, cleanup_pending=False),
    )

    assert (
        dialog.api_key_edit.echoMode()
        is QLineEdit.EchoMode.Password
    )
    assert dialog.api_key_edit.text() == ""
    dialog.activate_button.click()
    assert activations == []
    assert "switch_requires_turn_decision" in dialog.error_label.text()

    wait_index = dialog.turn_choice.findData(
        ActiveTurnHandling.WAIT_FOR_ACTIVE
    )
    dialog.turn_choice.setCurrentIndex(wait_index)
    dialog.activate_button.click()
    cancel_index = dialog.turn_choice.findData(
        ActiveTurnHandling.CANCEL_ACTIVE
    )
    dialog.turn_choice.setCurrentIndex(cancel_index)
    dialog.activate_button.click()
    abandon_index = dialog.turn_choice.findData("abandon")
    dialog.turn_choice.setCurrentIndex(abandon_index)
    dialog.activate_button.click()

    assert activations == [
        ("fake-dialog-profile", ActiveTurnHandling.WAIT_FOR_ACTIVE),
        ("fake-dialog-profile", ActiveTurnHandling.CANCEL_ACTIVE),
    ]
    dialog._on_settings_changed(
        "cleanup",
        _dialog_snapshot(active_turn=False, cleanup_pending=True),
    )
    assert not dialog.activate_button.isEnabled()
    assert not dialog.create_button.isEnabled()
    assert not dialog.update_button.isEnabled()
    assert not dialog.save_key_button.isEnabled()
    dialog.close()


def test_provider_settings_dialog_disables_active_credential_actions(
    tmp_path: Path,
    qt_application: QApplication,
) -> None:
    del qt_application
    bridge = QtRuntimeBridge(
        ProductionQtRuntimeCompositionRoot(
            tmp_path / "active-dialog.json",
            secret_store_factory=_CountingSecretStore,
        )
    )
    dialog = ProviderSettingsDialog(bridge)

    dialog._on_settings_changed(
        "settings",
        _active_openai_dialog_snapshot(),
    )

    assert dialog._credential_id() == OPENAI_DEFAULT_CREDENTIAL_ID.value
    assert not dialog.save_key_button.isEnabled()
    assert not dialog.delete_key_button.isEnabled()
    assert "Switch away" in dialog.save_key_button.toolTip()
    assert "Switch away" in dialog.delete_key_button.toolTip()
    dialog.close()


def test_provider_settings_dialog_confirms_destructive_actions(
    tmp_path: Path,
    qt_application: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del qt_application
    bridge = QtRuntimeBridge(
        ProductionQtRuntimeCompositionRoot(
            tmp_path / "confirm-dialog.json",
            secret_store_factory=_CountingSecretStore,
        )
    )
    dialog = ProviderSettingsDialog(bridge)
    profile_deletes: list[str] = []
    credential_deletes: list[str] = []
    answers = [
        QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes,
        QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes,
    ]

    def answer_question(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return answers.pop(0)

    def capture_profile_delete(profile_id: str) -> str:
        profile_deletes.append(profile_id)
        return "profile"

    def capture_credential_delete(credential_id: str) -> str:
        credential_deletes.append(credential_id)
        return "credential"

    monkeypatch.setattr(QMessageBox, "question", answer_question)
    monkeypatch.setattr(
        bridge,
        "delete_provider_profile",
        capture_profile_delete,
    )
    monkeypatch.setattr(
        bridge,
        "delete_provider_credential",
        capture_credential_delete,
    )
    dialog._on_settings_changed(
        "settings",
        _active_openai_dialog_snapshot(),
    )
    active_profile = dialog._selected_profile()
    assert active_profile is not None
    inactive_profile = ProviderProfileView(
        profile_id=active_profile.profile_id,
        display_name=active_profile.display_name,
        provider_id=active_profile.provider_id,
        model=active_profile.model,
        credential_id=active_profile.credential_id,
        fixed_origin=active_profile.fixed_origin,
        capabilities=active_profile.capabilities,
        is_runtime_profile=False,
    )
    inactive_snapshot = ProviderSettingsSnapshot(
        profiles=(inactive_profile,),
        credential_bindings=tuple(dialog._bindings.values()),
        stored_active_profile_id=None,
        runtime_profile_id=None,
        provider_lifecycle="inactive",
        runtime_state="ready",
        active_turn=False,
        cleanup_pending=False,
    )
    dialog._on_settings_changed("inactive", inactive_snapshot)

    dialog._delete_profile()
    dialog._delete_profile()
    dialog._delete_credential()
    dialog._delete_credential()

    assert profile_deletes == [inactive_profile.profile_id]
    assert credential_deletes == [OPENAI_DEFAULT_CREDENTIAL_ID.value]
    assert answers == []
    dialog.close()


def test_provider_settings_dialog_confirmed_delete_removes_profile(
    tmp_path: Path,
    qt_application: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del qt_application
    bridge, _store = _start_bridge(tmp_path)
    settings_spy = QSignalSpy(bridge.provider_settings_changed)
    completed_spy = QSignalSpy(bridge.command_completed)
    failed_spy = QSignalSpy(bridge.command_failed)
    dialog = ProviderSettingsDialog(bridge)
    request_id = bridge.request_provider_settings()
    _wait_command(completed_spy, request_id)
    create_id = bridge.create_provider_profile(
        provider_id="fake",
        display_name="Delete Through Dialog",
        model="fake-delete",
        credential_id=None,
    )
    _wait_command(completed_spy, create_id)
    created_snapshot = next(
        row[1]
        for row in _rows(settings_spy)
        if row[0] == create_id
    )
    assert isinstance(created_snapshot, ProviderSettingsSnapshot)
    created = next(
        profile
        for profile in created_snapshot.profiles
        if profile.display_name == "Delete Through Dialog"
    )
    created_item = next(
        dialog.profile_list.item(index)
        for index in range(dialog.profile_list.count())
        if dialog.profile_list.item(index).data(
            Qt.ItemDataRole.UserRole
        )
        == created.profile_id
    )
    dialog.profile_list.setCurrentItem(created_item)
    assert dialog.delete_button.isEnabled()
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    previous_settings_count = settings_spy.count()

    dialog.delete_button.click()

    assert _run_until(
        lambda: settings_spy.count() == previous_settings_count + 1
    )
    deleted_snapshot = _rows(settings_spy)[-1][1]
    assert isinstance(deleted_snapshot, ProviderSettingsSnapshot)
    assert all(
        profile.profile_id != created.profile_id
        for profile in deleted_snapshot.profiles
    )
    assert failed_spy.count() == 0
    dialog.close()
    _shutdown_bridge(bridge)


def test_main_window_renders_plain_text_and_closes_asynchronously(
    tmp_path: Path,
    qt_application: QApplication,
) -> None:
    del qt_application
    bridge = QtRuntimeBridge(
        ProductionQtRuntimeCompositionRoot(
            tmp_path / "window-profiles.json",
            secret_store_factory=_CountingSecretStore,
        )
    )
    ready_spy = QSignalSpy(bridge.runtime_ready)
    shutdown_spy = QSignalSpy(bridge.shutdown_finished)
    window = MainWindow(bridge)
    window.show()
    assert _run_until(lambda: ready_spy.count() == 1)
    assert isinstance(window.conversation_view, QPlainTextEdit)

    bridge.turn_completed.emit("fake-turn", "<b>plain text only</b>")
    assert "<b>plain text only</b>" in window.conversation_view.toPlainText()
    assert window.close() is False
    assert window.is_closing
    gui_timer_fired = threading.Event()
    QTimer.singleShot(0, gui_timer_fired.set)
    assert _run_until(gui_timer_fired.is_set)
    assert _run_until(lambda: shutdown_spy.count() == 1)
    assert _rows(shutdown_spy) == [[True, "none"]]
    assert _run_until(lambda: not window.isVisible())
    assert not bridge.runtime_thread.isRunning()
    assert bridge.runtime_thread.pending_task_count_at_close == 0


def test_main_window_allows_two_sequential_fake_turns(
    tmp_path: Path,
    qt_application: QApplication,
) -> None:
    del qt_application
    bridge = QtRuntimeBridge(
        ProductionQtRuntimeCompositionRoot(
            tmp_path / "two-turns.json",
            secret_store_factory=_CountingSecretStore,
        )
    )
    ready_spy = QSignalSpy(bridge.runtime_ready)
    completed_spy = QSignalSpy(bridge.command_completed)
    turn_completed_spy = QSignalSpy(bridge.turn_completed)
    failed_spy = QSignalSpy(bridge.command_failed)
    window = MainWindow(bridge)
    window.show()
    assert _run_until(lambda: ready_spy.count() == 1)
    activate_id = bridge.activate_profile(
        FAKE_DEFAULT_PROFILE_ID.value,
        _OPTIONS,
        None,
    )
    _wait_command(completed_spy, activate_id)

    window.input_edit.setText("first local turn")
    window.send_button.click()
    assert _run_until(lambda: turn_completed_spy.count() == 1)
    assert _run_until(window.send_button.isEnabled)

    window.input_edit.setText("second local turn")
    window.send_button.click()
    assert _run_until(lambda: turn_completed_spy.count() == 2)
    assert _run_until(window.send_button.isEnabled)

    visible = window.conversation_view.toPlainText()
    assert "You: first local turn" in visible
    assert "You: second local turn" in visible
    assert visible.count("Assistant:") == 2
    assert failed_spy.count() == 0
    assert window.close() is False
    assert _run_until(lambda: not window.isVisible())
    assert not bridge.runtime_thread.isRunning()
    assert bridge.runtime_thread.pending_task_count_at_close == 0


def test_main_window_close_during_starting_is_non_blocking(
    tmp_path: Path,
    qt_application: QApplication,
) -> None:
    del qt_application
    entered = threading.Event()
    release = threading.Event()
    root = _GatedProductionRoot(
        ProductionQtRuntimeCompositionRoot(
            tmp_path / "starting-close.json",
            secret_store_factory=_CountingSecretStore,
        ),
        entered,
        release,
    )
    bridge = QtRuntimeBridge(root)
    shutdown_spy = QSignalSpy(bridge.shutdown_finished)
    window = MainWindow(bridge)
    window.show()
    assert _run_until(entered.is_set)

    assert window.close() is False
    assert window.is_closing
    gui_timer_fired = threading.Event()
    QTimer.singleShot(0, gui_timer_fired.set)
    assert _run_until(gui_timer_fired.is_set)
    assert bridge.runtime_thread.isRunning()

    release.set()
    assert _run_until(lambda: shutdown_spy.count() == 1)
    assert _rows(shutdown_spy) == [[True, "none"]]
    assert _run_until(lambda: not window.isVisible())
    assert not bridge.runtime_thread.isRunning()


def test_main_window_close_cancels_active_turn_without_blocking_gui(
    tmp_path: Path,
    qt_application: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del qt_application
    entered = threading.Event()
    release = threading.Event()

    async def gated_stream(
        provider: FakeProvider,
        request: LLMRequest,
    ) -> AsyncIterator[LLMEvent]:
        del provider, request
        entered.set()
        await asyncio.get_running_loop().run_in_executor(
            None,
            release.wait,
        )
        yield LLMEvent.text_delta("late fake text")
        yield LLMEvent.completed()

    monkeypatch.setattr(FakeProvider, "generate_stream", gated_stream)
    bridge = QtRuntimeBridge(
        ProductionQtRuntimeCompositionRoot(
            tmp_path / "active-turn-close.json",
            secret_store_factory=_CountingSecretStore,
        )
    )
    ready_spy = QSignalSpy(bridge.runtime_ready)
    completed_spy = QSignalSpy(bridge.command_completed)
    shutdown_spy = QSignalSpy(bridge.shutdown_finished)
    window = MainWindow(bridge)
    window.show()
    assert _run_until(lambda: ready_spy.count() == 1)
    activate_id = bridge.activate_profile(
        FAKE_DEFAULT_PROFILE_ID.value,
        _OPTIONS,
        None,
    )
    _wait_command(completed_spy, activate_id)
    bridge.send_message("hold", "active-close")
    assert _run_until(entered.is_set)

    assert window.close() is False
    gui_timer_fired = threading.Event()
    QTimer.singleShot(0, gui_timer_fired.set)
    assert _run_until(gui_timer_fired.is_set)
    assert shutdown_spy.count() == 0
    release.set()

    assert _run_until(lambda: shutdown_spy.count() == 1)
    assert _rows(shutdown_spy) == [[True, "none"]]
    assert not bridge.runtime_thread.isRunning()
    assert bridge.runtime_thread.pending_task_count_at_close == 0


def test_main_window_shutdown_failure_stays_open_and_can_retry(
    tmp_path: Path,
    qt_application: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del qt_application
    fail_close = True
    close_calls = 0
    original_close = FakeProvider.aclose

    async def controlled_close(provider: FakeProvider) -> None:
        nonlocal close_calls
        close_calls += 1
        if fail_close:
            raise RuntimeError("opaque-window-close-failure")
        await original_close(provider)

    monkeypatch.setattr(FakeProvider, "aclose", controlled_close)
    bridge = QtRuntimeBridge(
        ProductionQtRuntimeCompositionRoot(
            tmp_path / "retry-close.json",
            secret_store_factory=_CountingSecretStore,
        )
    )
    ready_spy = QSignalSpy(bridge.runtime_ready)
    completed_spy = QSignalSpy(bridge.command_completed)
    shutdown_spy = QSignalSpy(bridge.shutdown_finished)
    window = MainWindow(bridge)
    window.show()
    assert _run_until(lambda: ready_spy.count() == 1)
    activate_id = bridge.activate_profile(
        FAKE_DEFAULT_PROFILE_ID.value,
        _OPTIONS,
        None,
    )
    _wait_command(completed_spy, activate_id)

    assert window.close() is False
    assert _run_until(lambda: shutdown_spy.count() == 1)
    assert _rows(shutdown_spy)[0][0] is False
    assert window.isVisible()
    assert not window.is_closing
    assert bridge.runtime_thread.isRunning()
    assert "shutdown_provider_cleanup_failed" in window.error_label.text()

    fail_close = False
    assert window.close() is False
    assert _run_until(lambda: shutdown_spy.count() == 2)
    assert _rows(shutdown_spy)[-1] == [True, "none"]
    assert close_calls == 2
    assert _run_until(lambda: not window.isVisible())
    assert not bridge.runtime_thread.isRunning()
    assert bridge.runtime_thread.pending_task_count_at_close == 0


def test_runtime_thread_command_repr_redacts_secret() -> None:
    command = RuntimeThreadCommand(
        command_id="safe-command",
        type=RuntimeThreadCommandType.SAVE_PROVIDER_CREDENTIAL,
        credential_id=OPENAI_DEFAULT_CREDENTIAL_ID.value,
        secret=_FAKE_SECRET,
    )

    assert _FAKE_SECRET not in repr(command)
    command.clear_sensitive()
    assert command.secret == ""


def test_gui_subprocess_starts_and_closes_without_qthread_traceback() -> None:
    probe = Path(__file__).parents[2] / "scripts" / "qt_gui_smoke.py"
    result = subprocess.run(
        [sys.executable, str(probe)],
        cwd=probe.parents[1],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    combined = f"{result.stdout}\n{result.stderr}"

    assert result.returncode == 0
    assert "qt_gui_smoke=True" in result.stdout
    assert "shutdown_count=1" in result.stdout
    assert "thread_running=False" in result.stdout
    assert "pending_asyncio_tasks=0" in result.stdout
    assert "Error calling Python override of QThread::run()" not in combined
    assert "Traceback" not in combined
    assert _FAKE_SECRET not in combined
