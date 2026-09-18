"""Bounded CONNECT to a trusted literal loopback proxy, with target IP pinning."""
from __future__ import annotations

import asyncio
import ipaddress
import ssl
from urllib.parse import urlsplit

import anyio
import h11
import httpcore
import httpx

from ..budget_errors import BudgetError
from ..security.urls import ResolvedUrl, SafeFetchFailure, UnsafeUrlError

_MAX_HANDSHAKE_BYTES = 16 * 1024
_MAX_HANDSHAKE_EVENTS = 16
_READ_BYTES = 4096


def _unsupported() -> UnsafeUrlError:
    return UnsafeUrlError("Trusted proxy tunnel is unavailable", failure=SafeFetchFailure.ROUTE_UNSUPPORTED)


def validate_proxy_endpoint(value: str) -> tuple[str, int]:
    """Accept only explicit HTTP loopback literals without URL adornments."""
    try:
        if not isinstance(value, str) or not value or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError
        if "?" in value or "#" in value or "%" in value:
            raise ValueError
        parsed = urlsplit(value)
        if parsed.scheme != "http" or parsed.path or parsed.query or parsed.fragment:
            raise ValueError
        if parsed.username is not None or parsed.password is not None or not parsed.hostname:
            raise ValueError
        port_text = parsed.netloc.rsplit(":", 1)[-1]
        if not port_text.isascii() or not port_text.isdecimal():
            raise ValueError
        port = parsed.port
        if port is None or not 1 <= port <= 65535:
            raise ValueError
        address = ipaddress.ip_address(parsed.hostname)
        if not address.is_loopback or (address.version == 6 and address != ipaddress.IPv6Address("::1")):
            raise ValueError
        host = str(address)
        authority = f"[{parsed.hostname}]:{port_text}" if address.version == 6 else f"{parsed.hostname}:{port_text}"
        if parsed.netloc != authority:
            raise ValueError
        return host, port
    except (ValueError, TypeError):
        raise _unsupported() from None


def proxy_endpoint_identity(value: str) -> str:
    host, port = validate_proxy_endpoint(value)
    return f"http://{_authority(host, port)}"


def _authority(host: str, port: int) -> str:
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


def _public_ip(value: str) -> str:
    if "%" in value:
        raise ValueError
    address = ipaddress.ip_address(value)
    if (not address.is_global or address.is_loopback or address.is_private
            or address.is_link_local or address.is_reserved or address.is_multicast):
        raise ValueError
    return str(address)


async def _close_stream(stream: httpcore.AsyncNetworkStream | httpx.AsyncByteStream) -> None:
    """Complete resource cleanup under both AnyIO and asyncio cancellation."""
    with anyio.CancelScope(shield=True):
        closing = asyncio.create_task(stream.aclose())
        cancelled = False
        while not closing.done():
            try:
                await asyncio.shield(closing)
            except asyncio.CancelledError:
                cancelled = True
        try:
            closing.result()
        except BudgetError:
            raise
        except Exception:
            pass
        if cancelled:
            raise asyncio.CancelledError


class _TunnelStream(httpcore.AsyncNetworkStream):
    """Retain ownership when TLS returns a replacement network stream."""

    def __init__(self, stream: httpcore.AsyncNetworkStream, hostname: str):
        self._stream = stream
        self._hostname = hostname
        self._close_task: asyncio.Task | None = None

    async def read(self, max_bytes, timeout=None):
        try:
            return await self._stream.read(max_bytes, timeout=timeout)
        except BaseException as exc:
            await self.aclose()
            if isinstance(exc, (asyncio.CancelledError, BudgetError)) or not isinstance(exc, Exception):
                raise
            raise _unsupported() from None

    async def write(self, buffer, timeout=None):
        try:
            return await self._stream.write(buffer, timeout=timeout)
        except BaseException as exc:
            await self.aclose()
            if isinstance(exc, (asyncio.CancelledError, BudgetError)) or not isinstance(exc, Exception):
                raise
            raise _unsupported() from None

    async def aclose(self):
        if self._close_task is None:
            self._close_task = asyncio.create_task(_close_stream(self._stream))
        with anyio.CancelScope(shield=True):
            cancelled = False
            while not self._close_task.done():
                try:
                    await asyncio.shield(self._close_task)
                except asyncio.CancelledError:
                    cancelled = True
            self._close_task.result()
            if cancelled:
                raise asyncio.CancelledError

    async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        try:
            if (self._close_task is not None or server_hostname != self._hostname
                    or ssl_context.verify_mode != ssl.CERT_REQUIRED or not ssl_context.check_hostname):
                raise _unsupported()
            stream = await self._stream.start_tls(ssl_context, server_hostname=server_hostname, timeout=timeout)
            if not isinstance(stream, httpcore.AsyncNetworkStream):
                raise _unsupported()
            self._stream = stream
            return self
        except BaseException as exc:
            await self.aclose()
            if isinstance(exc, (asyncio.CancelledError, BudgetError)):
                raise
            if not isinstance(exc, Exception):
                raise
            raise _unsupported() from None

    def get_extra_info(self, info):
        return self._stream.get_extra_info(info)


class PinnedProxyBackend(httpcore.AsyncNetworkBackend):
    """Open only a CONNECT tunnel to an independently validated public IP."""

    def __init__(self, resolved: ResolvedUrl, pinned_ip: str, proxy_url: str, *, backend=None):
        self._proxy_host, self._proxy_port = validate_proxy_endpoint(proxy_url)
        try:
            parsed = urlsplit(resolved.url)
            if (parsed.scheme != "https" or parsed.hostname != resolved.hostname
                    or parsed.port not in (None, 443) or resolved.port != 443
                    or parsed.username is not None or parsed.password is not None):
                raise ValueError
            addresses = tuple(_public_ip(value) for value in resolved.addresses)
            self._pinned_ip = _public_ip(pinned_ip)
            if not addresses or self._pinned_ip not in addresses:
                raise ValueError
        except (ValueError, TypeError):
            raise _unsupported() from None
        self._resolved = resolved
        self._backend = backend if backend is not None else httpcore.AnyIOBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if host != self._resolved.hostname or port != 443 or local_address is not None:
            raise _unsupported()
        stream = None
        try:
            stream = await self._backend.connect_tcp(
                self._proxy_host, self._proxy_port, timeout=timeout,
                local_address=None, socket_options=socket_options,
            )
            if not isinstance(stream, httpcore.AsyncNetworkStream):
                raise _unsupported()
            connection = h11.Connection(h11.CLIENT, max_incomplete_event_size=_MAX_HANDSHAKE_BYTES)
            authority = _authority(self._pinned_ip, 443).encode("ascii")
            await stream.write(connection.send(h11.Request(method=b"CONNECT", target=authority,
                               headers=[(b"Host", authority)])), timeout=timeout)
            await stream.write(connection.send(h11.EndOfMessage()), timeout=timeout)
            received = events = 0
            while True:
                event = connection.next_event()
                if event is h11.NEED_DATA:
                    chunk = await stream.read(_READ_BYTES, timeout=timeout)
                    received += len(chunk)
                    if not chunk or len(chunk) > _READ_BYTES or received > _MAX_HANDSHAKE_BYTES:
                        raise _unsupported()
                    connection.receive_data(chunk)
                    continue
                events += 1
                if events > _MAX_HANDSHAKE_EVENTS:
                    raise _unsupported()
                if isinstance(event, h11.InformationalResponse):
                    if event.status_code not in (100, 102, 103):
                        raise _unsupported()
                    continue
                if isinstance(event, h11.Response):
                    if (not 200 <= event.status_code < 300 or connection.trailing_data[0]
                            or connection.our_state is not h11.SWITCHED_PROTOCOL
                            or connection.their_state is not h11.SWITCHED_PROTOCOL):
                        raise _unsupported()
                    return _TunnelStream(stream, self._resolved.hostname)
                raise _unsupported()
        except BaseException as exc:
            if isinstance(stream, httpcore.AsyncNetworkStream):
                await _close_stream(stream)
            if isinstance(exc, (asyncio.CancelledError, BudgetError)):
                raise
            if not isinstance(exc, Exception):
                raise
            raise _unsupported() from None

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise _unsupported()

    async def sleep(self, seconds):
        await self._backend.sleep(seconds)


class PinnedProxyTransport(httpx.AsyncHTTPTransport):
    """Keep the original HTTPS origin and verified TLS identity through CONNECT."""

    def __init__(self, resolved: ResolvedUrl, pinned_ip: str, proxy_url: str):
        super().__init__(verify=True, trust_env=False, retries=0)
        self._resolved = resolved
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl.create_default_context(), retries=0,
            network_backend=PinnedProxyBackend(resolved, pinned_ip, proxy_url),
        )

    async def handle_async_request(self, request):
        hostname = self._resolved.hostname
        host_header = f"[{hostname}]" if ":" in hostname else hostname
        if (request.url.scheme != "https" or request.url.host != hostname
                or request.url.port not in (None, 443)
                or request.headers.get("host") not in (host_header, f"{host_header}:443")):
            raise _unsupported()
        try:
            response = await super().handle_async_request(request)
            response.stream = _SafeResponseStream(response.stream)
            return response
        except (asyncio.CancelledError, BudgetError):
            raise
        except Exception:
            raise _unsupported() from None


class _SafeResponseStream(httpx.AsyncByteStream):
    """HTTP framing errors must not disclose untrusted target response bytes."""

    def __init__(self, stream: httpx.AsyncByteStream):
        self._stream = stream
        self._close_task: asyncio.Task | None = None

    async def __aiter__(self):
        try:
            async for chunk in self._stream:
                yield chunk
        except BaseException as exc:
            await self.aclose()
            if isinstance(exc, (asyncio.CancelledError, BudgetError)) or not isinstance(exc, Exception):
                raise
            raise _unsupported() from None

    async def aclose(self):
        if self._close_task is None:
            self._close_task = asyncio.create_task(_close_stream(self._stream))
        with anyio.CancelScope(shield=True):
            cancelled = False
            while not self._close_task.done():
                try:
                    await asyncio.shield(self._close_task)
                except asyncio.CancelledError:
                    cancelled = True
            self._close_task.result()
            if cancelled:
                raise asyncio.CancelledError
