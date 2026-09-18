"""CONNECT security tests use synthetic streams, never DNS or sockets."""
import asyncio
import ssl

import httpcore
import httpx
import pytest

from deepchoice.budget_errors import BudgetError
from deepchoice.outbound.tunnel import (
    PinnedProxyBackend, PinnedProxyTransport, proxy_endpoint_identity,
    validate_proxy_endpoint,
)
from deepchoice.security.urls import ResolvedUrl, SafeFetchFailure, UnsafeUrlError

PROXY = "http://127.0.0.1:7890"
IP = "93.184.216.34"
OK = b"HTTP/1.1 200 Connection established\r\n\r\n"


def resolved(ip=IP):
    return ResolvedUrl("https://example.com/document", "example.com", 443, (ip,))


class Stream(httpcore.AsyncNetworkStream):
    def __init__(self, chunks=(), *, tls_error=None, tls_result=None):
        self.chunks = list(chunks)
        self.writes = []
        self.read_sizes = []
        self.timeouts = []
        self.tls_calls = []
        self.closed = 0
        self.tls_error = tls_error
        self.tls_result = tls_result
        self.tls_entered = asyncio.Event()
        self.tls_gate = None
        self.read_entered = asyncio.Event()
        self.read_gate = None
        self.close_entered = asyncio.Event()
        self.close_gate = None

    async def read(self, max_bytes, timeout=None):
        self.read_sizes.append(max_bytes)
        self.timeouts.append(timeout)
        self.read_entered.set()
        if self.read_gate is not None:
            await self.read_gate.wait()
        if not self.chunks:
            return b""
        chunk = self.chunks.pop(0)
        if isinstance(chunk, BaseException):
            raise chunk
        if len(chunk) > max_bytes:
            self.chunks.insert(0, chunk[max_bytes:])
        return chunk[:max_bytes]

    async def write(self, buffer, timeout=None):
        self.writes.append(buffer)
        self.timeouts.append(timeout)

    async def aclose(self):
        self.close_entered.set()
        if self.close_gate is not None:
            await self.close_gate.wait()
        await asyncio.sleep(0)
        self.closed += 1

    async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        self.tls_calls.append((ssl_context, server_hostname, timeout))
        self.tls_entered.set()
        if self.tls_gate is not None:
            await self.tls_gate.wait()
        if self.tls_error is not None:
            raise self.tls_error
        return self if self.tls_result is None else self.tls_result


class Backend(httpcore.AsyncNetworkBackend):
    def __init__(self, stream):
        self.stream = stream
        self.calls = []

    async def connect_tcp(self, host, port, **kwargs):
        self.calls.append((host, port, kwargs))
        return self.stream

    async def sleep(self, seconds):
        raise AssertionError("no retry allowed")


def pinned(stream, ip=IP, proxy=PROXY):
    backend = Backend(stream)
    return PinnedProxyBackend(resolved(ip), ip, proxy, backend=backend), backend


@pytest.mark.parametrize("value", [
    "", "http://localhost:7890", "https://127.0.0.1:7890", "socks5://127.0.0.1:7890",
    "http://127.0.0.1", "http://127.0.0.1:0", "http://127.0.0.1:65536",
    "http://127.0.0.1:+80", "http://127.0.0.1:８０", "http://127.0.0.1:80/",
    "http://127.0.0.1:80/path", "http://127.0.0.1:80?", "http://127.0.0.1:80#",
    "http://user@127.0.0.1:80", "http://user:secret@127.0.0.1:80",
    "http://10.0.0.1:80", "http://8.8.8.8:80", "http://[::]:80",
    "http://[::1%25scope]:80", "http://[::ffff:127.0.0.1]:80",
    "http://127.1:80", " http://127.0.0.1:80", "http://127.0.0.1:80\n",
    "http://127.0.0.1:80\x00", "http://127.0.0.1:80\\", None,
])
def test_endpoint_rejects_unsupported_forms_without_disclosure(value):
    with pytest.raises(UnsafeUrlError) as caught:
        validate_proxy_endpoint(value)
    assert str(caught.value) == "Trusted proxy tunnel is unavailable"
    assert caught.value.failure == SafeFetchFailure.ROUTE_UNSUPPORTED


@pytest.mark.parametrize(("value", "host", "port", "identity"), [
    (PROXY, "127.0.0.1", 7890, PROXY),
    ("http://127.2.3.4:00080", "127.2.3.4", 80, "http://127.2.3.4:80"),
    ("http://[0:0:0:0:0:0:0:1]:7890", "::1", 7890, "http://[::1]:7890"),
])
def test_endpoint_normalization(value, host, port, identity):
    assert validate_proxy_endpoint(value) == (host, port)
    assert proxy_endpoint_identity(value) == identity


@pytest.mark.asyncio
@pytest.mark.parametrize(("ip", "authority", "proxy", "proxy_host"), [
    (IP, IP + ":443", PROXY, "127.0.0.1"),
    ("2606:4700:4700::1111", "[2606:4700:4700::1111]:443", "http://[::1]:7890", "::1"),
])
async def test_connect_pins_authority_and_loopback_endpoint(ip, authority, proxy, proxy_host):
    stream = Stream([OK])
    network, backend = pinned(stream, ip, proxy)
    tunnel = await network.connect_tcp("example.com", 443, timeout=2)
    assert backend.calls == [(proxy_host, 7890, {"timeout": 2, "local_address": None, "socket_options": None})]
    assert b"".join(stream.writes) == (
        f"CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\n\r\n".encode()
    )
    assert stream.read_sizes == [4096]
    assert all(timeout == 2 for timeout in stream.timeouts)
    await tunnel.aclose()
    await tunnel.aclose()
    assert stream.closed == 1


@pytest.mark.asyncio
async def test_fragmented_handshake_with_allowed_informationals():
    response = b"".join(f"HTTP/1.1 {code} Continue\r\n\r\n".encode() for code in (100, 102, 103)) + OK
    stream = Stream([response[i:i + 3] for i in range(0, len(response), 3)])
    network, _ = pinned(stream)
    tunnel = await network.connect_tcp("example.com", 443)
    await tunnel.aclose()
    assert stream.closed == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\nprivate proxy error",
    b"HTTP/1.1 404 Missing\r\n\r\n", b"HTTP/1.1 101 Switching Protocols\r\n\r\n",
    b"HTTP/1.1 199 Other\r\n\r\n", b"not http\r\n\r\n", b"",
    b"HTTP/1.1 200 Incomplete\r\n", OK + b"extra tunneled data",
    b"HTTP/1.1 200 OK\r\ninvalid-header\r\n\r\n",
    b"HTTP/1.1 103 Early Hints\r\n\r\n" * 16 + OK,
    (b"HTTP/1.1 103 Early Hints\r\nX-Padding: " + b"a" * 1100 + b"\r\n\r\n") * 15 + OK,
    b"HTTP/1.1 200 OK\r\nX-Padding: " + b"a" * 16384 + b"\r\n\r\n",
])
async def test_handshake_rejections_are_bounded_closed_and_sanitized(response):
    stream = Stream([response])
    network, backend = pinned(stream)
    with pytest.raises(UnsafeUrlError) as caught:
        await network.connect_tcp("example.com", 443)
    assert caught.value.failure == SafeFetchFailure.ROUTE_UNSUPPORTED
    assert str(caught.value) == "Trusted proxy tunnel is unavailable"
    assert caught.value.__cause__ is None
    assert stream.closed == 1
    assert len(backend.calls) == 1
    assert all(size <= 4096 for size in stream.read_sizes)


@pytest.mark.asyncio
async def test_sixteen_total_events_are_accepted():
    stream = Stream([b"HTTP/1.1 103 Early Hints\r\n\r\n" * 15 + OK])
    network, _ = pinned(stream)
    tunnel = await network.connect_tcp("example.com", 443)
    await tunnel.aclose()


@pytest.mark.parametrize(("target", "ip"), [
    (ResolvedUrl("http://example.com/", "example.com", 443, (IP,)), IP),
    (ResolvedUrl("https://example.com:80/", "example.com", 80, (IP,)), IP),
    (ResolvedUrl("https://other.com/", "example.com", 443, (IP,)), IP),
    (ResolvedUrl("https://user@example.com/", "example.com", 443, (IP,)), IP),
    (resolved(), "8.8.8.8"), (resolved("127.0.0.1"), "127.0.0.1"),
    (resolved("224.0.0.1"), "224.0.0.1"), (resolved("fe80::1"), "fe80::1"),
    (ResolvedUrl("https://example.com/", "example.com", 443, (IP, "10.0.0.1")), IP),
])
def test_backend_revalidates_public_target_and_membership(target, ip):
    with pytest.raises(UnsafeUrlError):
        PinnedProxyBackend(target, ip, PROXY, backend=Backend(None))


@pytest.mark.asyncio
async def test_backend_rejects_wrong_origin_http_port_and_unix_without_dispatch():
    network, backend = pinned(Stream())
    for host, port in (("other.com", 443), ("example.com", 80)):
        with pytest.raises(UnsafeUrlError):
            await network.connect_tcp(host, port)
    with pytest.raises(UnsafeUrlError):
        await network.connect_unix_socket("secret-socket")
    assert backend.calls == []


@pytest.mark.asyncio
async def test_inner_httpx_request_keeps_original_host_and_verified_tls_identity(monkeypatch):
    stream = Stream([OK, b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"])
    backend = Backend(stream)
    monkeypatch.setattr(httpcore, "AnyIOBackend", lambda: backend)
    transport = PinnedProxyTransport(resolved(), IP, PROXY)
    async with httpx.AsyncClient(transport=transport, trust_env=False) as client:
        response = await client.get(resolved().url)
        assert response.content == b"ok"
    inner_request = b"".join(stream.writes[2:])
    assert b"GET /document HTTP/1.1\r\n" in inner_request
    assert b"Host: example.com\r\n" in inner_request
    assert IP.encode() not in inner_request
    context, hostname, _ = stream.tls_calls[0]
    assert hostname == "example.com"
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    assert stream.closed == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [{"server_hostname": "wrong.com"}, {"insecure": True}])
async def test_tls_rejects_identity_override_or_disabled_certificate_checks(kwargs):
    stream = Stream([OK])
    network, _ = pinned(stream)
    tunnel = await network.connect_tcp("example.com", 443)
    context = ssl.create_default_context()
    if kwargs.get("insecure"):
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    with pytest.raises(UnsafeUrlError):
        await tunnel.start_tls(context, server_hostname=kwargs.get("server_hostname", "example.com"))
    assert stream.closed == 1 and stream.tls_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [RuntimeError("raw secret TLS error"), asyncio.CancelledError(), BudgetError("budget")])
async def test_tls_failure_closes_and_propagates_cancel_or_budget(error):
    stream = Stream([OK], tls_error=error)
    network, _ = pinned(stream)
    tunnel = await network.connect_tcp("example.com", 443)
    expected = type(error) if isinstance(error, (asyncio.CancelledError, BudgetError)) else UnsafeUrlError
    with pytest.raises(expected):
        await tunnel.start_tls(ssl.create_default_context(), server_hostname="example.com")
    await tunnel.aclose()
    assert stream.closed == 1


@pytest.mark.asyncio
async def test_tls_replacement_remains_owned_by_wrapper():
    replacement = Stream()
    stream = Stream([OK], tls_result=replacement)
    network, _ = pinned(stream)
    tunnel = await network.connect_tcp("example.com", 443)
    assert await tunnel.start_tls(ssl.create_default_context(), server_hostname="example.com") is tunnel
    await tunnel.aclose()
    await tunnel.aclose()
    assert replacement.closed == 1


@pytest.mark.asyncio
async def test_no_valid_backend_or_tls_stream_fails_closed():
    network, _ = pinned(None)
    with pytest.raises(UnsafeUrlError):
        await network.connect_tcp("example.com", 443)
    stream = Stream([OK], tls_result=object())
    network, _ = pinned(stream)
    tunnel = await network.connect_tcp("example.com", 443)
    with pytest.raises(UnsafeUrlError):
        await tunnel.start_tls(ssl.create_default_context(), server_hostname="example.com")
    assert stream.closed == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [RuntimeError("raw secret handshake error"), BudgetError("budget")])
async def test_handshake_io_error_is_sanitized_but_budget_is_not_swallowed(error):
    stream = Stream([error])
    network, _ = pinned(stream)
    with pytest.raises(BudgetError if isinstance(error, BudgetError) else UnsafeUrlError):
        await network.connect_tcp("example.com", 443)
    assert stream.closed == 1


@pytest.mark.asyncio
async def test_cancellation_during_handshake_and_cleanup_waits_for_close():
    stream = Stream()
    stream.read_gate = asyncio.Event()
    stream.close_gate = asyncio.Event()
    network, _ = pinned(stream)
    operation = asyncio.create_task(network.connect_tcp("example.com", 443))
    await stream.read_entered.wait()
    operation.cancel()
    await stream.close_entered.wait()
    operation.cancel()
    stream.close_gate.set()
    with pytest.raises(asyncio.CancelledError):
        await operation
    assert stream.closed == 1


@pytest.mark.asyncio
async def test_cancelled_normal_close_completes_once():
    stream = Stream([OK])
    stream.close_gate = asyncio.Event()
    network, _ = pinned(stream)
    tunnel = await network.connect_tcp("example.com", 443)
    closing = asyncio.create_task(tunnel.aclose())
    await stream.close_entered.wait()
    closing.cancel()
    stream.close_gate.set()
    with pytest.raises(asyncio.CancelledError):
        await closing
    await tunnel.aclose()
    assert stream.closed == 1


@pytest.mark.asyncio
async def test_byte_limit_accepts_exact_boundary():
    prefix = b"HTTP/1.1 200 OK\r\nX-Padding: "
    response = prefix + b"a" * (16384 - len(prefix) - 4) + b"\r\n\r\n"
    stream = Stream([response])
    network, _ = pinned(stream)
    tunnel = await network.connect_tcp("example.com", 443)
    await tunnel.aclose()
    assert len(stream.read_sizes) == 4


@pytest.mark.asyncio
async def test_task_cancellation_during_tls_closes_original_stream():
    stream = Stream([OK])
    stream.tls_gate = asyncio.Event()
    network, _ = pinned(stream)
    tunnel = await network.connect_tcp("example.com", 443)
    operation = asyncio.create_task(tunnel.start_tls(ssl.create_default_context(), server_hostname="example.com"))
    await stream.tls_entered.wait()
    operation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await operation
    assert stream.closed == 1


@pytest.mark.asyncio
async def test_target_io_error_is_closed_and_sanitized():
    stream = Stream([OK, RuntimeError("secret target error")])
    network, _ = pinned(stream)
    tunnel = await network.connect_tcp("example.com", 443)
    await tunnel.start_tls(ssl.create_default_context(), server_hostname="example.com")
    with pytest.raises(UnsafeUrlError) as caught:
        await tunnel.read(1024)
    assert str(caught.value) == "Trusted proxy tunnel is unavailable"
    assert stream.closed == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(("url", "host"), [
    ("http://example.com:443/", "example.com"),
    ("https://other.com/", "other.com"),
    ("https://example.com/", "other.com"),
])
async def test_transport_rejects_changed_origin_or_inner_host_without_dispatch(monkeypatch, url, host):
    backend = Backend(None)
    monkeypatch.setattr(httpcore, "AnyIOBackend", lambda: backend)
    transport = PinnedProxyTransport(resolved(), IP, PROXY)
    async with httpx.AsyncClient(transport=transport, trust_env=False) as client:
        with pytest.raises(UnsafeUrlError):
            await client.get(url, headers={"Host": host})
    assert backend.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("chunks", [
    [b"HTTP/1.1 200 OK\r\nprivate\x00secret: x\r\n\r\n"],
    [b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n", b"private secret chunk\r\n"],
])
async def test_target_http_framing_error_never_discloses_response_bytes(monkeypatch, chunks):
    stream = Stream([OK, *chunks])
    backend = Backend(stream)
    monkeypatch.setattr(httpcore, "AnyIOBackend", lambda: backend)
    transport = PinnedProxyTransport(resolved(), IP, PROXY)
    async with httpx.AsyncClient(transport=transport, trust_env=False) as client:
        with pytest.raises(UnsafeUrlError) as caught:
            await client.get(resolved().url)
    assert str(caught.value) == "Trusted proxy tunnel is unavailable"
    assert caught.value.__cause__ is None
    assert stream.closed == 1
