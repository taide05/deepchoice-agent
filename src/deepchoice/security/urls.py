"""Validation primitives for URLs that may originate outside the trust boundary."""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

MAX_URL_LENGTH = 2048
ALLOWED_SCHEMES = frozenset({"http", "https"})
ALLOWED_PORTS = frozenset({80, 443})


class UnsafeUrlError(ValueError):
    """A URL cannot be fetched without crossing a private-network boundary."""


DnsResolver = Callable[[str, int], Awaitable[Sequence[str]]]


@dataclass(frozen=True, slots=True)
class ResolvedUrl:
    url: str
    hostname: str
    port: int
    addresses: tuple[str, ...]


def _normalise_hostname(hostname: str) -> str:
    raw = hostname.rstrip(".")
    if not raw or "%" in raw:
        raise UnsafeUrlError("URL hostname is invalid")
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        try:
            ascii_name = raw.encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise UnsafeUrlError("URL hostname is invalid") from exc
        if len(ascii_name) > 253 or any(
            not label
            or len(label) > 63
            or label.startswith("-")
            or label.endswith("-")
            or any(not (char.isascii() and (char.isalnum() or char == "-")) for char in label)
            for label in ascii_name.split(".")
        ):
            raise UnsafeUrlError("URL hostname is invalid")
        return ascii_name


def _require_public_address(value: str) -> str:
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise UnsafeUrlError("DNS returned an invalid address") from exc
    # is_global excludes private, loopback, link-local, reserved, multicast,
    # unspecified and shared-use ranges for both IPv4 and IPv6.
    if not address.is_global:
        raise UnsafeUrlError("URL resolves to a non-public address")
    return str(address)


async def _system_resolver(hostname: str, port: int) -> Sequence[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(
        hostname,
        port,
        family=socket.AF_UNSPEC,
        type=socket.SOCK_STREAM,
        proto=socket.IPPROTO_TCP,
    )
    return [info[4][0] for info in infos]


class SafeUrlPolicy:
    """Parse, resolve and validate an outbound HTTP URL.

    Every returned address has been checked. Rejecting mixed public/private DNS
    answers prevents a caller from relying on resolver ordering to reach an
    internal address.
    """

    def __init__(
        self,
        *,
        dns_timeout_s: float = 3.0,
        resolver: DnsResolver | None = None,
    ) -> None:
        if dns_timeout_s <= 0:
            raise ValueError("dns_timeout_s must be positive")
        self.dns_timeout_s = dns_timeout_s
        self._resolver = resolver or _system_resolver

    async def resolve(self, url: str) -> ResolvedUrl:
        if not isinstance(url, str) or not url or len(url) > MAX_URL_LENGTH:
            raise UnsafeUrlError("URL length is invalid")
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError as exc:
            raise UnsafeUrlError("URL is invalid") from exc
        scheme = parsed.scheme.lower()
        if scheme not in ALLOWED_SCHEMES:
            raise UnsafeUrlError("URL scheme is not allowed")
        if parsed.username is not None or parsed.password is not None:
            raise UnsafeUrlError("URL user information is not allowed")
        if not parsed.hostname:
            raise UnsafeUrlError("URL hostname is required")
        hostname = _normalise_hostname(parsed.hostname)
        port = port or (443 if scheme == "https" else 80)
        if port not in ALLOWED_PORTS:
            raise UnsafeUrlError("URL port is not allowed")

        try:
            literal = ipaddress.ip_address(hostname)
        except ValueError:
            try:
                answers = await asyncio.wait_for(
                    self._resolver(hostname, port), timeout=self.dns_timeout_s
                )
            except (TimeoutError, OSError, socket.gaierror) as exc:
                raise UnsafeUrlError("URL hostname could not be resolved safely") from exc
        else:
            answers = [str(literal)]
        if not answers:
            raise UnsafeUrlError("URL hostname has no addresses")
        addresses = tuple(dict.fromkeys(_require_public_address(item) for item in answers))

        host_for_url = f"[{hostname}]" if ":" in hostname else hostname
        default_port = 443 if scheme == "https" else 80
        authority = host_for_url if port == default_port else f"{host_for_url}:{port}"
        normalised = urlunsplit((scheme, authority, parsed.path or "/", parsed.query, ""))
        return ResolvedUrl(normalised, hostname, port, addresses)


__all__ = [
    "ALLOWED_PORTS",
    "ALLOWED_SCHEMES",
    "MAX_URL_LENGTH",
    "DnsResolver",
    "ResolvedUrl",
    "SafeUrlPolicy",
    "UnsafeUrlError",
]
