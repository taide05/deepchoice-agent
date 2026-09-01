"""Outbound channel layer for DeepChoice retrievers.

Usage:
    from deepchoice.outbound import make_client, get_resolver

    async with await make_client("github") as client:
        resp = await client.get("https://api.github.com/search/repositories", params=...)

`make_client` routes through the probed channel for the source (direct /
local-proxy / self-forward / direct-v6) and never trial-and-errors per request.
"""
from .channels import (
    DEFAULT_CHANNEL_ORDER,
    BaseChannel,
    DirectChannel,
    DirectV6Channel,
    LocalProxyChannel,
    OutboundConfig,
    SelfForwardChannel,
    build_channels,
)
from .resolver import AuditEntry, BACKOFF_S, ChannelResolver

_resolver: ChannelResolver | None = None


def set_resolver(resolver: ChannelResolver | None) -> None:
    """Inject a custom resolver (tests / explicit config). None resets."""
    global _resolver
    _resolver = resolver


def get_resolver() -> ChannelResolver:
    global _resolver
    if _resolver is None:
        _resolver = ChannelResolver()
    return _resolver


async def make_client(source: str):
    """Async client for `source` wired to its routed channel."""
    resolver = get_resolver()
    return await resolver.make_client(source)


def reset_for_tests() -> None:
    """Drop the cached resolver (call between tests)."""
    set_resolver(None)


__all__ = [
    "DEFAULT_CHANNEL_ORDER",
    "BaseChannel",
    "DirectChannel",
    "DirectV6Channel",
    "LocalProxyChannel",
    "OutboundConfig",
    "SelfForwardChannel",
    "build_channels",
    "ChannelResolver",
    "AuditEntry",
    "BACKOFF_S",
    "get_resolver",
    "set_resolver",
    "make_client",
    "reset_for_tests",
]
