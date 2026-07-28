"""Pure classification for the packaged-runtime PID/TCP observer.

The Windows supervisor is the authority for sampling ``Get-NetTCPConnection``.
This module keeps address classification and packaged-local channel attribution
deterministic and independently testable without opening a socket or process.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from ipaddress import IPv4Address, IPv6Address, ip_address
from typing import Final


class NetworkObserverError(RuntimeError):
    """A fixed-message observer boundary error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__("The packaged runtime network observation failed safely.")


class AddressCategory(StrEnum):
    LOOPBACK = "loopback"
    UNSPECIFIED = "unspecified"
    PRIVATE = "private"
    LINK_LOCAL = "link_local"
    EXTERNAL = "external"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class ProcessIdentity:
    pid: int
    creation_token: str

    def __post_init__(self) -> None:
        if self.pid <= 0 or not self.creation_token:
            raise ValueError("invalid process identity")


@dataclass(frozen=True, slots=True)
class TcpEndpoint:
    owning_process: int
    state: str
    local_address: str
    local_port: int
    remote_address: str
    remote_port: int

    def __post_init__(self) -> None:
        if self.owning_process <= 0:
            raise ValueError("invalid owning process")
        if not 0 <= self.local_port <= 65535:
            raise ValueError("invalid local port")
        if not 0 <= self.remote_port <= 65535:
            raise ValueError("invalid remote port")

    @property
    def key(self) -> tuple[int, str, str, int, str, int]:
        return (
            self.owning_process,
            self.state.casefold(),
            self.local_address.casefold(),
            self.local_port,
            self.remote_address.casefold(),
            self.remote_port,
        )


@dataclass(slots=True)
class EndpointObservation:
    endpoint: TcpEndpoint
    first_poll: int
    last_poll: int
    sample_count: int = 1


@dataclass(frozen=True, slots=True)
class NetworkObservationSummary:
    poll_count: int
    sample_count: int
    unique_endpoint_count: int
    bound_endpoint_count: int
    listen_endpoint_count: int
    established_endpoint_count: int
    loopback_endpoint_count: int
    external_endpoint_count: int
    unattributed_endpoint_count: int
    unique_flow_count: int
    process_exit_observed: bool
    endpoints_disappeared_after_exit: bool
    pid_reuse_detected: bool
    packaged_local_channel_verified: bool
    safe_code: str

    def to_safe_dict(self) -> dict[str, bool | int | str]:
        return {
            "poll_count": self.poll_count,
            "sample_count": self.sample_count,
            "unique_endpoint_count": self.unique_endpoint_count,
            "bound_endpoint_count": self.bound_endpoint_count,
            "listen_endpoint_count": self.listen_endpoint_count,
            "established_endpoint_count": self.established_endpoint_count,
            "loopback_endpoint_count": self.loopback_endpoint_count,
            "external_endpoint_count": self.external_endpoint_count,
            "unattributed_endpoint_count": self.unattributed_endpoint_count,
            "unique_flow_count": self.unique_flow_count,
            "process_exit_observed": self.process_exit_observed,
            "endpoints_disappeared_after_exit": self.endpoints_disappeared_after_exit,
            "pid_reuse_detected": self.pid_reuse_detected,
            "packaged_local_channel_verified": self.packaged_local_channel_verified,
            "safe_code": self.safe_code,
        }


_TCP_STATES: Final = frozenset({"bound", "listen", "established"})


def classify_address(value: str) -> AddressCategory:
    """Classify an address using the observer's strict loopback policy."""

    try:
        parsed = ip_address(value)
    except ValueError:
        return AddressCategory.INVALID
    if isinstance(parsed, IPv6Address) and parsed.ipv4_mapped is not None:
        mapped = parsed.ipv4_mapped
        if mapped.is_loopback:
            return AddressCategory.LOOPBACK
        parsed = mapped
    if parsed.is_loopback:
        return AddressCategory.LOOPBACK
    if parsed.is_unspecified:
        return AddressCategory.UNSPECIFIED
    if parsed.is_link_local:
        return AddressCategory.LINK_LOCAL
    if parsed.is_private:
        return AddressCategory.PRIVATE
    if isinstance(parsed, (IPv4Address, IPv6Address)):
        return AddressCategory.EXTERNAL
    return AddressCategory.INVALID


def _is_reverse_pair(first: TcpEndpoint, second: TcpEndpoint) -> bool:
    return (
        first.local_address.casefold() == second.remote_address.casefold()
        and first.local_port == second.remote_port
        and first.remote_address.casefold() == second.local_address.casefold()
        and first.remote_port == second.local_port
    )


class PackagedRuntimeNetworkObserver:
    """Aggregate authoritative samples for one immutable process identity."""

    def __init__(self, identity: ProcessIdentity) -> None:
        self._identity = identity
        self._poll_count = 0
        self._sample_count = 0
        self._observations: dict[
            tuple[int, str, str, int, str, int], EndpointObservation
        ] = {}

    def add_poll(
        self,
        identity: ProcessIdentity,
        endpoints: tuple[TcpEndpoint, ...],
    ) -> None:
        if identity != self._identity:
            raise NetworkObserverError("process_identity_changed")
        self._poll_count += 1
        seen_in_poll: set[tuple[int, str, str, int, str, int]] = set()
        for endpoint in endpoints:
            if endpoint.owning_process != self._identity.pid:
                raise NetworkObserverError("owning_process_mismatch")
            state = endpoint.state.casefold()
            if state not in _TCP_STATES:
                continue
            if endpoint.key in seen_in_poll:
                continue
            seen_in_poll.add(endpoint.key)
            self._sample_count += 1
            observation = self._observations.get(endpoint.key)
            if observation is None:
                self._observations[endpoint.key] = EndpointObservation(
                    endpoint=endpoint,
                    first_poll=self._poll_count,
                    last_poll=self._poll_count,
                )
            else:
                observation.last_poll = self._poll_count
                observation.sample_count += 1

    def finish(
        self,
        *,
        process_exit_observed: bool,
        post_exit_endpoints: tuple[TcpEndpoint, ...],
        post_exit_identity: ProcessIdentity | None = None,
    ) -> NetworkObservationSummary:
        pid_reuse_detected = (
            post_exit_identity is not None and post_exit_identity != self._identity
        )
        endpoints_disappeared = not post_exit_endpoints and not pid_reuse_detected
        endpoints = tuple(item.endpoint for item in self._observations.values())
        bound = tuple(item for item in endpoints if item.state.casefold() == "bound")
        listen = tuple(item for item in endpoints if item.state.casefold() == "listen")
        established = tuple(
            item for item in endpoints if item.state.casefold() == "established"
        )

        external_count = 0
        strict_loopback_established: list[TcpEndpoint] = []
        for endpoint in established:
            local_category = classify_address(endpoint.local_address)
            remote_category = classify_address(endpoint.remote_address)
            if (
                local_category is AddressCategory.LOOPBACK
                and remote_category is AddressCategory.LOOPBACK
            ):
                strict_loopback_established.append(endpoint)
            else:
                external_count += 1
        for endpoint in listen:
            if classify_address(endpoint.local_address) is not AddressCategory.LOOPBACK:
                external_count += 1

        reverse_pair = (
            len(strict_loopback_established) == 2
            and _is_reverse_pair(
                strict_loopback_established[0],
                strict_loopback_established[1],
            )
        )
        pair_ports = (
            {
                strict_loopback_established[0].local_port,
                strict_loopback_established[0].remote_port,
            }
            if reverse_pair
            else set()
        )
        bound_matches_pair = (
            len(bound) == 1
            and bound[0].local_port in pair_ports
            and classify_address(bound[0].local_address)
            in {AddressCategory.LOOPBACK, AddressCategory.UNSPECIFIED}
        )
        packaged_channel = (
            process_exit_observed
            and endpoints_disappeared
            and not pid_reuse_detected
            and len(endpoints) == 3
            and len(listen) == 0
            and external_count == 0
            and reverse_pair
            and bound_matches_pair
        )
        loopback_count = 3 if packaged_channel else len(strict_loopback_established)
        unattributed_count = (
            0 if packaged_channel else len(endpoints) - external_count - loopback_count
        )
        safe_code = (
            "corrective_packaged_runtime_diagnostic_verified"
            if packaged_channel
            else "packaged_runtime_network_signature_unattributed"
        )
        if external_count:
            safe_code = "packaged_runtime_external_network_detected"
        elif pid_reuse_detected:
            safe_code = "packaged_runtime_pid_identity_changed"
        elif not process_exit_observed or not endpoints_disappeared:
            safe_code = "packaged_runtime_network_cleanup_failed"

        return NetworkObservationSummary(
            poll_count=self._poll_count,
            sample_count=self._sample_count,
            unique_endpoint_count=len(endpoints),
            bound_endpoint_count=len(bound),
            listen_endpoint_count=len(listen),
            established_endpoint_count=len(established),
            loopback_endpoint_count=loopback_count,
            external_endpoint_count=external_count,
            unattributed_endpoint_count=unattributed_count,
            unique_flow_count=1 if reverse_pair else 0,
            process_exit_observed=process_exit_observed,
            endpoints_disappeared_after_exit=endpoints_disappeared,
            pid_reuse_detected=pid_reuse_detected,
            packaged_local_channel_verified=packaged_channel,
            safe_code=safe_code,
        )
