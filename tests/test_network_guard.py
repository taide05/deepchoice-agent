"""The test process itself must stay offline except for explicit loopback."""
import socket

import pytest


def test_external_dns_is_blocked():
    with pytest.raises(socket.gaierror):
        socket.getaddrinfo("example.com", 443)


def test_loopback_dns_is_available():
    assert socket.getaddrinfo("localhost", 80, type=socket.SOCK_STREAM)
