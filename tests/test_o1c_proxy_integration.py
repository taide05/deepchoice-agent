import asyncio
from types import SimpleNamespace

import httpx
import pytest

from deepchoice.outbound.channels import BaseChannel, OutboundConfig
from deepchoice.outbound.resolver import ChannelResolver
from deepchoice.runtime import context as context_module
from deepchoice.security.urls import SafeFetchFailure, SafeUrlPolicy, UnsafeUrlError


PUBLIC_IP = "93.184.216.34"
TRUSTED_PROXY = "http://127.0.0.1:7897"
_UNSET = object()


def _context_for(cfg: OutboundConfig, *, proxy_hash: str | None = None, policy: str | None = None):
    return SimpleNamespace(
        security_policy_version=policy,
        safe_fetch_proxy_sha256=cfg.safe_fetch_proxy_sha256 if proxy_hash is None else proxy_hash,
    )


def _proxy_resolver(
    *,
    dns=None,
    handler=None,
    cfg: OutboundConfig | None = None,
    channels=None,
    probe_fn=None,
    context=_UNSET,
    monkeypatch=None,
):
    cfg = cfg or OutboundConfig(
        channel_order=("local-proxy",),
        local_proxy=TRUSTED_PROXY,
        safe_fetch_trusted_local_proxy=TRUSTED_PROXY,
    )
    if context is _UNSET:
        context = (
            _context_for(cfg, policy="outbound-url-v2")
            if cfg.safe_fetch_proxy_sha256 is not None
            else None
        )
    calls = []
    dns = dns or (lambda _host, _port: _resolve((PUBLIC_IP,)))

    async def resolver(host, port):
        values = dns(host, port)
        if asyncio.iscoroutine(values):
            values = await values
        return values

    if handler is None:
        async def handler(request):
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text="ok",
                request=request,
            )

    def proxy_factory(resolved, pinned_ip, proxy_url):
        calls.append((resolved.hostname, pinned_ip, proxy_url))
        return httpx.MockTransport(handler)

    async def default_probe(_source, channel):
        return channel.name == "local-proxy"

    resolver_obj = ChannelResolver(
        cfg=cfg,
        channels=channels,
        probe_fn=probe_fn or default_probe,
        safe_url_policy=SafeUrlPolicy(resolver=resolver),
        safe_proxy_transport_factory=proxy_factory,
    )
    if monkeypatch is not None:
        monkeypatch.setattr(
            context_module,
            "get_run_context",
            lambda: context,
        )
    return resolver_obj, calls


async def _resolve(values):
    return values


@pytest.mark.asyncio
async def test_trusted_proxy_is_default_off_and_never_falls_back_to_direct():
    cfg = OutboundConfig(
        channel_order=("local-proxy", "direct"),
        local_proxy=TRUSTED_PROXY,
    )
    direct_calls = []

    def direct_factory(*args):
        direct_calls.append(args)
        return httpx.MockTransport(lambda request: httpx.Response(200, request=request))

    async def probe(_source, channel):
        return channel.name == "local-proxy"

    resolver = ChannelResolver(
        cfg=cfg,
        probe_fn=probe,
        safe_transport_factory=direct_factory,
    )
    with pytest.raises(UnsafeUrlError) as caught:
        await resolver.safe_fetch("community", "https://example.test/")
    assert caught.value.failure is SafeFetchFailure.ROUTE_UNSUPPORTED
    assert direct_calls == []


@pytest.mark.parametrize(
    "endpoint",
    (
        "https://127.0.0.1:7897",
        "http://127.0.0.1",
        "http://127.0.0.1:7897/path",
        "http://user:secret@127.0.0.1:7897",
        "http://[::1]",
    ),
)
def test_trusted_proxy_rejects_noncanonical_endpoints(endpoint):
    with pytest.raises(UnsafeUrlError):
        OutboundConfig(
            channel_order=("local-proxy",),
            local_proxy=TRUSTED_PROXY,
            safe_fetch_trusted_local_proxy=endpoint,
        )


@pytest.mark.asyncio
async def test_selected_proxy_mismatch_auth_and_self_forward_do_not_fallback(monkeypatch):
    mismatch = OutboundConfig(
        channel_order=("local-proxy", "direct"),
        local_proxy="http://127.0.0.1:7898",
        safe_fetch_trusted_local_proxy=TRUSTED_PROXY,
    )
    resolver, calls = _proxy_resolver(cfg=mismatch, monkeypatch=monkeypatch)
    with pytest.raises(UnsafeUrlError) as caught:
        await resolver.safe_fetch("community", "https://example.test/")
    assert caught.value.failure is SafeFetchFailure.ROUTE_UNSUPPORTED
    assert calls == []

    enabled = OutboundConfig(
        channel_order=("local-proxy", "direct"),
        local_proxy=TRUSTED_PROXY,
        safe_fetch_trusted_local_proxy=TRUSTED_PROXY,
    )
    no_context, no_context_calls = _proxy_resolver(
        cfg=enabled,
        context=None,
        monkeypatch=monkeypatch,
    )
    with pytest.raises(UnsafeUrlError) as caught:
        await no_context.safe_fetch("community", "https://example.test/")
    assert caught.value.failure is SafeFetchFailure.ROUTE_UNSUPPORTED
    assert no_context_calls == []

    auth = OutboundConfig(
        channel_order=("local-proxy", "direct"),
        local_proxy="http://user:secret@127.0.0.1:7897",
        safe_fetch_trusted_local_proxy=TRUSTED_PROXY,
    )
    auth_resolver, auth_calls = _proxy_resolver(cfg=auth, monkeypatch=monkeypatch)
    with pytest.raises(UnsafeUrlError):
        await auth_resolver.safe_fetch("community", "https://example.test/")
    assert auth_calls == []

    class ForwardChannel(BaseChannel):
        name = "self-forward"
        kind = "self-forward"

    cfg = OutboundConfig(channel_order=("self-forward", "direct"))
    direct_calls = []

    def direct_factory(*args):
        direct_calls.append(args)
        return httpx.MockTransport(lambda request: httpx.Response(200, request=request))

    async def probe(_source, channel):
        return channel.name == "self-forward"

    forward_resolver = ChannelResolver(
        cfg=cfg,
        channels=[ForwardChannel(cfg)],
        probe_fn=probe,
        safe_transport_factory=direct_factory,
    )
    with pytest.raises(UnsafeUrlError) as caught:
        await forward_resolver.safe_fetch("community", "https://example.test/")
    assert caught.value.failure is SafeFetchFailure.ROUTE_UNSUPPORTED
    assert direct_calls == []


@pytest.mark.asyncio
async def test_proxy_requires_https_443_and_rejects_downgrade_redirect(monkeypatch):
    dns_calls = []

    async def dns(host, port):
        dns_calls.append((host, port))
        return [PUBLIC_IP]

    resolver, calls = _proxy_resolver(dns=dns, monkeypatch=monkeypatch)
    with pytest.raises(UnsafeUrlError) as caught:
        await resolver.safe_fetch("community", "http://example.test/")
    assert caught.value.failure is SafeFetchFailure.ROUTE_UNSUPPORTED
    assert dns_calls == []

    async def downgrade(request):
        return httpx.Response(
            302,
            headers={"location": "http://other.example/"},
            request=request,
        )

    resolver, calls = _proxy_resolver(dns=dns, handler=downgrade, monkeypatch=monkeypatch)
    with pytest.raises(UnsafeUrlError) as caught:
        await resolver.safe_fetch("community", "https://example.test/")
    assert caught.value.failure is SafeFetchFailure.ROUTE_UNSUPPORTED
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_proxy_revalidates_and_repins_each_redirect_hop_with_mixed_families(monkeypatch):
    answers = {
        "one.example": ["93.184.216.34"],
        "two.example": ["2606:4700:4700::1111"],
    }

    async def dns(host, _port):
        return answers[host]

    async def handler(request):
        if request.url.host == "one.example":
            return httpx.Response(
                302,
                headers={"location": "https://two.example/end"},
                request=request,
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="ok",
            request=request,
        )

    resolver, calls = _proxy_resolver(dns=dns, handler=handler, monkeypatch=monkeypatch)
    response = await resolver.safe_fetch("community", "https://one.example/start")
    assert response.text == "ok"
    assert calls == [
        ("one.example", "93.184.216.34", TRUSTED_PROXY),
        ("two.example", "2606:4700:4700::1111", TRUSTED_PROXY),
    ]


@pytest.mark.asyncio
async def test_proxy_head_fallback_is_bounded_and_repinning_is_fresh(monkeypatch):
    methods = []

    async def handler(request):
        methods.append((request.method, request.headers.get("range")))
        if request.method == "HEAD":
            return httpx.Response(405, headers={"content-type": "text/html"}, request=request)
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b"12345",
            request=request,
        )

    resolver, calls = _proxy_resolver(handler=handler, monkeypatch=monkeypatch)
    response = await resolver.safe_fetch(
        "community",
        "https://example.test/",
        method="HEAD",
        max_response_bytes=5,
        head_fallback_to_range_get=True,
    )
    assert response.content == b"12345"
    assert methods == [("HEAD", None), ("GET", "bytes=0-4")]
    assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("content_type", ["application/json", "text/plain"])
async def test_proxy_rejects_non_html_and_oversized_responses(content_type, monkeypatch):
    async def non_html(request):
        return httpx.Response(200, headers={"content-type": content_type}, text="body", request=request)

    resolver, _ = _proxy_resolver(handler=non_html, monkeypatch=monkeypatch)
    with pytest.raises(UnsafeUrlError) as caught:
        await resolver.safe_fetch("community", "https://example.test/")
    assert caught.value.failure is SafeFetchFailure.RESPONSE_REJECTED

    async def oversized(request):
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b"123456",
            request=request,
        )

    resolver, _ = _proxy_resolver(handler=oversized, monkeypatch=monkeypatch)
    with pytest.raises(UnsafeUrlError):
        await resolver.safe_fetch(
            "community",
            "https://example.test/",
            max_response_bytes=5,
        )


@pytest.mark.asyncio
async def test_proxy_redirect_cap_and_429_cooldown(monkeypatch):
    async def loop(request):
        return httpx.Response(
            302,
            headers={"location": "https://example.test/next"},
            request=request,
        )

    resolver, _ = _proxy_resolver(handler=loop, monkeypatch=monkeypatch)
    with pytest.raises(UnsafeUrlError, match="redirect"):
        await resolver.safe_fetch("community", "https://example.test/", max_redirects=1)

    from deepchoice.outbound import throttle

    throttle.reset_for_tests()
    try:
        async def limited(request):
            return httpx.Response(
                429,
                headers={"content-type": "text/plain", "Retry-After": "120"},
                text="private provider diagnostic",
                request=request,
            )

        resolver, _ = _proxy_resolver(handler=limited, monkeypatch=monkeypatch)
        with pytest.raises(throttle.ProviderRateLimitError):
            await resolver.safe_fetch("official", "https://example.test/")
        assert throttle.gate_for("official-web").cooling_down()
    finally:
        throttle.reset_for_tests()


@pytest.mark.asyncio
async def test_proxy_total_timeout_is_cancellation_safe(monkeypatch):
    async def slow(request):
        await asyncio.sleep(0.05)
        return httpx.Response(200, headers={"content-type": "text/html"}, request=request)

    resolver, _ = _proxy_resolver(handler=slow, monkeypatch=monkeypatch)
    with pytest.raises(UnsafeUrlError) as caught:
        await resolver.safe_fetch(
            "community",
            "https://example.test/",
            timeout_s=0.01,
        )
    assert caught.value.failure is SafeFetchFailure.TIMEOUT

    task = asyncio.create_task(
        resolver.safe_fetch("community", "https://example.test/", timeout_s=1.0)
    )
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_proxy_requires_matching_durable_context_and_rejects_drift(monkeypatch):
    cfg = OutboundConfig(
        channel_order=("local-proxy",),
        local_proxy=TRUSTED_PROXY,
        safe_fetch_trusted_local_proxy=TRUSTED_PROXY,
    )
    matching = _context_for(cfg, policy="outbound-url-v2")
    resolver, calls = _proxy_resolver(cfg=cfg, context=matching, monkeypatch=monkeypatch)
    response = await resolver.safe_fetch("community", "https://example.test/")
    assert response.text == "ok"
    assert len(calls) == 1

    drifted = _context_for(cfg, proxy_hash="0" * 64, policy="outbound-url-v2")
    async def forbidden_probe(*_args):
        pytest.fail("configuration drift must reject before route probing")

    async def forbidden_dns(*_args):
        pytest.fail("configuration drift must reject before DNS")

    resolver, calls = _proxy_resolver(
        cfg=cfg,
        context=drifted,
        probe_fn=forbidden_probe,
        dns=forbidden_dns,
        monkeypatch=monkeypatch,
    )
    with pytest.raises(UnsafeUrlError) as caught:
        await resolver.safe_fetch("community", "https://example.test/")
    assert caught.value.failure is SafeFetchFailure.ROUTE_UNSUPPORTED
    assert calls == []

    legacy = _context_for(cfg, policy="outbound-url-v1")
    resolver, calls = _proxy_resolver(
        cfg=cfg,
        context=legacy,
        probe_fn=forbidden_probe,
        dns=forbidden_dns,
        monkeypatch=monkeypatch,
    )
    with pytest.raises(UnsafeUrlError) as caught:
        await resolver.safe_fetch("community", "https://example.test/")
    assert caught.value.failure is SafeFetchFailure.ROUTE_UNSUPPORTED
    assert calls == []
