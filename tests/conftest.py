"""Suite-wide safety guards."""

from __future__ import annotations

import socket

import pytest


@pytest.fixture(autouse=True)
def block_network_connections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail every automated test that attempts an outbound socket connection."""

    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def is_loopback(address: object) -> bool:
        return (
            isinstance(address, tuple)
            and bool(address)
            and address[0] in {"127.0.0.1", "::1"}
        )

    def guarded_connect(
        client_socket: socket.socket,
        address: object,
    ) -> None:
        if is_loopback(address):
            original_connect(client_socket, address)  # type: ignore[arg-type]
            return
        raise AssertionError("Automated tests must not access the network")

    def guarded_connect_ex(
        client_socket: socket.socket,
        address: object,
    ) -> int:
        if is_loopback(address):
            return original_connect_ex(
                client_socket,
                address,  # type: ignore[arg-type]
            )
        raise AssertionError("Automated tests must not access the network")

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
