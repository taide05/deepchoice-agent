"""URL safety and address validation for dynamic outbound fetches.

Ported minimally from the maintenance worktree's security/urls.py. Only the
policy primitives needed by the official-page fetcher are kept here; no runtime
cross-worktree import is used.
"""
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

# Well-known and local-use NAT64 prefixes embed an IPv4 target in the last 32
# bits. Treating the IPv6 literal as "global" would bypass the IPv4 checks.
_NAT64_PREFIXES = (
    ipaddress.ip_network("64:ff9b::/96"),
    ipaddress.ip_network("64:ff9b:1::/48"),
)


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


def _public_ip(value: str) -> str:
    """Return the pinned textual IP, or raise for an address we cannot prove safe.

    is_global alone is not enough: Python can report multicast/reserved IPv6 as
    global, and IPv4-mapped/NAT64 literals hide an IPv4 target that must be
    checked itself. IPv4-mapped, Teredo and 6to4 forms are rejected because their
    effective peer cannot be established from the literal alone.
    """
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise UnsafeUrlError("DNS returned an invalid address") from exc

    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            raise UnsafeUrlError("IPv4-mapped IPv6 addresses are not supported")
        if any(address in prefix for prefix in _NAT64_PREFIXES):
            raise UnsafeUrlError("NAT64 addresses cannot be pinned safely")
        if address.teredo is not None or address.sixtofour is not None:
            raise UnsafeUrlError("transition IPv6 addresses are not supported")

    if (
        not address.is_global
        or address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or getattr(address, "is_site_local", False)
    ):
        raise UnsafeUrlError("URL resolves to a non-public address")
    return str(address)


async def _system_resolver(hostname: str, port: int) -> Sequence[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(
        hostname, port, family=socket.AF_UNSPEC,
        type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP,
    )
    return [info[4][0] for info in infos]


@dataclass(frozen=True, slots=True)
class ResolvedUrl:
    url: str
    hostname: str
    port: int
    addresses: tuple[str, ...]


class SafeUrlPolicy:
    """Parse, resolve and validate one HTTP(S) URL; reject mixed unsafe answers."""

    def __init__(self, *, dns_timeout_s: float = 3.0,
                 resolver: DnsResolver | None = None) -> None:
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
                    self._resolver(hostname, port), timeout=self.dns_timeout_s)
            except (TimeoutError, OSError, socket.gaierror) as exc:
                raise UnsafeUrlError("URL hostname could not be resolved safely") from exc
        else:
            answers = [str(literal)]
        if not answers:
            raise UnsafeUrlError("URL hostname has no addresses")
        # Reject if any answer is unsafe: resolver ordering must not decide the
        # address family or expose a mixed public/private answer.
        addresses = tuple(dict.fromkeys(_public_ip(item) for item in answers))

        host_for_url = f"[{hostname}]" if ":" in hostname else hostname
        default_port = 443 if scheme == "https" else 80
        authority = host_for_url if port == default_port else f"{host_for_url}:{port}"
        normalised = urlunsplit((scheme, authority, parsed.path or "/", parsed.query, ""))
        return ResolvedUrl(normalised, hostname, port, addresses)


__all__ = [
    "ALLOWED_PORTS", "ALLOWED_SCHEMES", "MAX_URL_LENGTH", "DnsResolver",
    "ResolvedUrl", "SafeUrlPolicy", "UnsafeUrlError",
]
