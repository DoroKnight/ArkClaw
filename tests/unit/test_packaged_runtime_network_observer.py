from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_OBSERVER_PATH = _PROJECT_ROOT / "packaging/packaged_runtime_network_observer.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "_packaged_runtime_network_observer_test",
        _OBSERVER_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_OBSERVER: Any = _load_module()
AddressCategory = _OBSERVER.AddressCategory
NetworkObserverError = _OBSERVER.NetworkObserverError
PackagedRuntimeNetworkObserver = _OBSERVER.PackagedRuntimeNetworkObserver
ProcessIdentity = _OBSERVER.ProcessIdentity
TcpEndpoint = _OBSERVER.TcpEndpoint
classify_address = _OBSERVER.classify_address


def _identity(token: str = "owner-start-token") -> Any:
    return ProcessIdentity(pid=41234, creation_token=token)


def _endpoint(
    state: str,
    local_address: str,
    local_port: int,
    remote_address: str = "0.0.0.0",
    remote_port: int = 0,
) -> Any:
    return TcpEndpoint(
        owning_process=41234,
        state=state,
        local_address=local_address,
        local_port=local_port,
        remote_address=remote_address,
        remote_port=remote_port,
    )


def _packaged_channel() -> tuple[Any, Any, Any]:
    return (
        _endpoint("Bound", "::", 50123, "::", 0),
        _endpoint("Established", "127.0.0.1", 50123, "127.0.0.1", 50124),
        _endpoint("Established", "127.0.0.1", 50124, "127.0.0.1", 50123),
    )


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("127.0.0.1", AddressCategory.LOOPBACK),
        ("127.255.255.254", AddressCategory.LOOPBACK),
        ("::1", AddressCategory.LOOPBACK),
        ("::ffff:127.0.0.1", AddressCategory.LOOPBACK),
        ("0.0.0.0", AddressCategory.UNSPECIFIED),
        ("::", AddressCategory.UNSPECIFIED),
        ("10.0.0.1", AddressCategory.PRIVATE),
        ("169.254.10.2", AddressCategory.LINK_LOCAL),
        ("8.8.8.8", AddressCategory.EXTERNAL),
        ("not-an-address", AddressCategory.INVALID),
    ],
)
def test_address_classification_is_strict(address: str, expected: Any) -> None:
    assert classify_address(address) is expected


def test_exact_packaged_local_signature_is_verified() -> None:
    observer = PackagedRuntimeNetworkObserver(_identity())
    observer.add_poll(_identity(), _packaged_channel())

    summary = observer.finish(
        process_exit_observed=True,
        post_exit_endpoints=(),
    )

    assert summary.packaged_local_channel_verified
    assert summary.bound_endpoint_count == 1
    assert summary.established_endpoint_count == 2
    assert summary.unique_flow_count == 1
    assert summary.loopback_endpoint_count == 3
    assert summary.external_endpoint_count == 0
    assert summary.unattributed_endpoint_count == 0
    assert summary.safe_code == "corrective_packaged_runtime_diagnostic_verified"


def test_repeated_samples_count_polls_without_duplicating_endpoints() -> None:
    observer = PackagedRuntimeNetworkObserver(_identity())
    observer.add_poll(_identity(), _packaged_channel())
    observer.add_poll(_identity(), _packaged_channel())

    summary = observer.finish(process_exit_observed=True, post_exit_endpoints=())

    assert summary.poll_count == 2
    assert summary.sample_count == 6
    assert summary.unique_endpoint_count == 3


def test_duplicate_records_inside_one_poll_are_counted_once() -> None:
    observer = PackagedRuntimeNetworkObserver(_identity())
    endpoint = _packaged_channel()[0]
    observer.add_poll(_identity(), (endpoint, endpoint))

    summary = observer.finish(process_exit_observed=True, post_exit_endpoints=())

    assert summary.sample_count == 1
    assert summary.unique_endpoint_count == 1


def test_non_loopback_established_endpoint_fails_closed() -> None:
    observer = PackagedRuntimeNetworkObserver(_identity())
    observer.add_poll(
        _identity(),
        (_endpoint("Established", "127.0.0.1", 50123, "8.8.8.8", 443),),
    )

    summary = observer.finish(process_exit_observed=True, post_exit_endpoints=())

    assert summary.external_endpoint_count == 1
    assert summary.safe_code == "packaged_runtime_external_network_detected"


@pytest.mark.parametrize("address", ["0.0.0.0", "::", "10.0.0.1", "169.254.1.1"])
def test_non_loopback_listen_endpoint_fails_closed(address: str) -> None:
    observer = PackagedRuntimeNetworkObserver(_identity())
    observer.add_poll(_identity(), (_endpoint("Listen", address, 50123),))

    summary = observer.finish(process_exit_observed=True, post_exit_endpoints=())

    assert summary.external_endpoint_count == 1
    assert summary.safe_code == "packaged_runtime_external_network_detected"


def test_loopback_listen_is_not_misreported_as_packaged_channel() -> None:
    observer = PackagedRuntimeNetworkObserver(_identity())
    observer.add_poll(_identity(), (_endpoint("Listen", "127.0.0.1", 50123),))

    summary = observer.finish(process_exit_observed=True, post_exit_endpoints=())

    assert summary.external_endpoint_count == 0
    assert summary.unattributed_endpoint_count == 1
    assert summary.safe_code == "packaged_runtime_network_signature_unattributed"


def test_bound_endpoint_without_reverse_flow_stays_unattributed() -> None:
    observer = PackagedRuntimeNetworkObserver(_identity())
    observer.add_poll(_identity(), (_endpoint("Bound", "::", 50123),))

    summary = observer.finish(process_exit_observed=True, post_exit_endpoints=())

    assert summary.bound_endpoint_count == 1
    assert summary.unattributed_endpoint_count == 1


def test_two_loopback_endpoints_must_be_reverse_directions() -> None:
    observer = PackagedRuntimeNetworkObserver(_identity())
    endpoints = (
        _endpoint("Bound", "::", 50123, "::", 0),
        _endpoint("Established", "127.0.0.1", 50123, "127.0.0.1", 50124),
        _endpoint("Established", "127.0.0.1", 50123, "127.0.0.1", 50125),
    )
    observer.add_poll(_identity(), endpoints)

    summary = observer.finish(process_exit_observed=True, post_exit_endpoints=())

    assert summary.unique_flow_count == 0
    assert not summary.packaged_local_channel_verified


def test_bound_port_must_match_reverse_flow() -> None:
    observer = PackagedRuntimeNetworkObserver(_identity())
    bound, first, second = _packaged_channel()
    observer.add_poll(
        _identity(),
        (
            _endpoint(
                bound.state,
                bound.local_address,
                60000,
                bound.remote_address,
                bound.remote_port,
            ),
            first,
            second,
        ),
    )

    summary = observer.finish(process_exit_observed=True, post_exit_endpoints=())

    assert summary.unique_flow_count == 1
    assert not summary.packaged_local_channel_verified


def test_unknown_tcp_states_are_not_counted() -> None:
    observer = PackagedRuntimeNetworkObserver(_identity())
    observer.add_poll(_identity(), (_endpoint("TimeWait", "127.0.0.1", 50123),))

    summary = observer.finish(process_exit_observed=True, post_exit_endpoints=())

    assert summary.sample_count == 0
    assert summary.unique_endpoint_count == 0


def test_endpoint_from_other_pid_is_rejected_before_aggregation() -> None:
    observer = PackagedRuntimeNetworkObserver(_identity())
    endpoint = TcpEndpoint(
        owning_process=49999,
        state="Bound",
        local_address="::",
        local_port=50123,
        remote_address="::",
        remote_port=0,
    )

    with pytest.raises(NetworkObserverError) as captured:
        observer.add_poll(_identity(), (endpoint,))

    assert captured.value.code == "owning_process_mismatch"


def test_changed_process_identity_is_rejected() -> None:
    observer = PackagedRuntimeNetworkObserver(_identity())

    with pytest.raises(NetworkObserverError) as captured:
        observer.add_poll(_identity("reused-pid-token"), ())

    assert captured.value.code == "process_identity_changed"


def test_pid_reuse_after_exit_fails_closed() -> None:
    observer = PackagedRuntimeNetworkObserver(_identity())
    observer.add_poll(_identity(), _packaged_channel())

    summary = observer.finish(
        process_exit_observed=True,
        post_exit_endpoints=(),
        post_exit_identity=_identity("reused-pid-token"),
    )

    assert summary.pid_reuse_detected
    assert summary.safe_code == "packaged_runtime_pid_identity_changed"


def test_records_remaining_after_exit_fail_cleanup() -> None:
    observer = PackagedRuntimeNetworkObserver(_identity())
    observer.add_poll(_identity(), _packaged_channel())

    summary = observer.finish(
        process_exit_observed=True,
        post_exit_endpoints=(_packaged_channel()[0],),
    )

    assert not summary.endpoints_disappeared_after_exit
    assert summary.safe_code == "packaged_runtime_network_cleanup_failed"


def test_missing_process_exit_fails_cleanup() -> None:
    observer = PackagedRuntimeNetworkObserver(_identity())
    observer.add_poll(_identity(), _packaged_channel())

    summary = observer.finish(
        process_exit_observed=False,
        post_exit_endpoints=(),
    )

    assert summary.safe_code == "packaged_runtime_network_cleanup_failed"


def test_safe_serialization_contains_counts_not_endpoint_values() -> None:
    secret_like_address = "203.0.113.77"
    observer = PackagedRuntimeNetworkObserver(_identity())
    observer.add_poll(
        _identity(),
        (_endpoint("Established", "127.0.0.1", 50123, secret_like_address, 443),),
    )

    payload = repr(
        observer.finish(
            process_exit_observed=True,
            post_exit_endpoints=(),
        ).to_safe_dict()
    )

    assert secret_like_address not in payload
    assert "local_address" not in payload
    assert "remote_address" not in payload


def test_error_message_does_not_expose_internal_code_or_input() -> None:
    observer = PackagedRuntimeNetworkObserver(_identity())
    sensitive = "sk-test-never-use-this-value"

    with pytest.raises(NetworkObserverError) as captured:
        observer.add_poll(
            _identity(sensitive),
            (),
        )

    assert captured.value.code == "process_identity_changed"
    assert sensitive not in str(captured.value)
    assert sensitive not in repr(captured.value)
