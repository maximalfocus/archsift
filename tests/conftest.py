from __future__ import annotations

import socket
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def block_outbound_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Fail every test that attempts an outbound socket connection."""

    def blocked_connect(*args: object, **kwargs: object) -> None:
        raise AssertionError("tests must not use outbound network connections")

    monkeypatch.setattr(socket, "create_connection", blocked_connect)
    monkeypatch.setattr(socket, "getaddrinfo", blocked_connect)
    monkeypatch.setattr(socket.socket, "connect", blocked_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked_connect)
    yield
