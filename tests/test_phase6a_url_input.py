import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from deepchoice.clarify.session_manager import SessionManager, SessionState
from deepchoice.clarify.clarification_agent import ClarificationAgent, _research_payload
from deepchoice.contracts.api import ResearchRequest
from deepchoice.outbound.channels import OutboundConfig, SelfForwardChannel
from deepchoice.outbound.resolver import ChannelResolver, _PinnedNetworkBackend
from deepchoice.retrievers import official as official_module
from deepchoice.security.input_limits import RequestBodyLimitMiddleware
from deepchoice.security.urls import SafeUrlPolicy, UnsafeUrlError
from deepchoice.server.clarify_routes import MessageRequest, StartRequest
from deepchoice.server.app import app as server_app


async def _resolve(values):
    return values


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    (
        "http://127.0.0.1/",
        "http://[::1]/",
        "http://169.254.169.254/latest/meta-data/",
        "https://[fe80::1]/",
    ),
)
async def test_safe_url_rejects_private_and_link_local_literals(url):
    with pytest.raises(UnsafeUrlError):
        await SafeUrlPolicy().resolve(url)


@pytest.mark.asyncio
async def test_safe_url_rejects_mixed_dns_userinfo_and_nonstandard_port():
    policy = SafeUrlPolicy(resolver=lambda _host, _port: _resolve(["93.184.216.34", "10.0.0.7"]))
    with pytest.raises(UnsafeUrlError):
        await policy.resolve("https://example.com/")
    with pytest.raises(UnsafeUrlError):
        await policy.resolve("https://user@example.com/")
    with pytest.raises(UnsafeUrlError):
        await policy.resolve("https://example.com:8443/")


def _direct_resolver(policy, transport_factory):
    cfg = OutboundConfig(channel_order=("direct",))

    async def probe(_source, _channel):
        return True

    return ChannelResolver(
        cfg=cfg,
        probe_fn=probe,
        safe_url_policy=policy,
        safe_transport_factory=transport_factory,
    )


@pytest.mark.asyncio
async def test_safe_fetch_revalidates_redirects_and_pins_each_connection():
    answers = {
        "one.example": ["93.184.216.34"],
        "two.example": ["1.1.1.1"],
    }

    async def dns(host, _port):
        return answers[host]

    connections = []

    def transport_factory(resolved, pinned_ip):
        connections.append((resolved.hostname, pinned_ip))

        async def handler(request):
            if request.url.host == "one.example":
                return httpx.Response(302, headers={"location": "https://two.example/end"})
            return httpx.Response(200, headers={"content-type": "text/html"}, text="ok")

        return httpx.MockTransport(handler)

    response = await _direct_resolver(SafeUrlPolicy(resolver=dns), transport_factory).safe_fetch(
        "official", "https://one.example/start", allowed_content_types=("text/html",)
    )
    assert response.text == "ok"
    assert connections == [("one.example", "93.184.216.34"), ("two.example", "1.1.1.1")]


@pytest.mark.asyncio
async def test_safe_fetch_rejects_private_redirect_before_transport():
    async def dns(host, _port):
        return {"one.example": ["93.184.216.34"], "internal.example": ["192.168.1.3"]}[host]

    calls = []

    def transport_factory(resolved, _ip):
        calls.append(resolved.hostname)
        return httpx.MockTransport(
            lambda _request: httpx.Response(302, headers={"location": "http://internal.example/"})
        )

    resolver = _direct_resolver(SafeUrlPolicy(resolver=dns), transport_factory)
    with pytest.raises(UnsafeUrlError):
        await resolver.safe_fetch("official", "https://one.example/")
    assert calls == ["one.example"]


@pytest.mark.asyncio
async def test_safe_fetch_head_fallback_is_only_405_or_501_and_bounded():
    async def dns(_host, _port):
        return ["93.184.216.34"]

    methods = []

    def transport_factory(_resolved, _ip):
        async def handler(request):
            methods.append((request.method, request.headers.get("range")))
            if request.method == "HEAD":
                return httpx.Response(405, headers={"content-type": "text/html"})
            return httpx.Response(200, headers={"content-type": "text/html"}, content=b"12345")

        return httpx.MockTransport(handler)

    response = await _direct_resolver(SafeUrlPolicy(resolver=dns), transport_factory).safe_fetch(
        "official",
        "https://example.com/",
        method="HEAD",
        max_response_bytes=5,
        allowed_content_types=("text/html",),
        head_fallback_to_range_get=True,
    )
    assert response.content == b"12345"
    assert methods == [("HEAD", None), ("GET", "bytes=0-4")]

    def oversized_factory(_resolved, _ip):
        return httpx.MockTransport(
            lambda _request: httpx.Response(
                200, headers={"content-type": "text/html"}, content=b"123456"
            )
        )

    with pytest.raises(UnsafeUrlError, match="body"):
        await _direct_resolver(SafeUrlPolicy(resolver=dns), oversized_factory).safe_fetch(
            "official",
            "https://example.com/",
            max_response_bytes=5,
            allowed_content_types=("text/html",),
        )

    def missing_type_factory(_resolved, _ip):
        return httpx.MockTransport(lambda _request: httpx.Response(200, content=b"ok"))

    with pytest.raises(UnsafeUrlError, match="content type"):
        await _direct_resolver(SafeUrlPolicy(resolver=dns), missing_type_factory).safe_fetch(
            "official", "https://example.com/"
        )


@pytest.mark.asyncio
async def test_safe_fetch_enforces_one_total_timeout():
    async def dns(_host, _port):
        return ["93.184.216.34"]

    def transport_factory(_resolved, _ip):
        async def handler(_request):
            await asyncio.sleep(0.05)
            return httpx.Response(200, headers={"content-type": "text/html"})

        return httpx.MockTransport(handler)

    resolver = _direct_resolver(SafeUrlPolicy(resolver=dns), transport_factory)
    with pytest.raises(UnsafeUrlError, match="total timeout"):
        await resolver.safe_fetch(
            "official",
            "https://example.com/",
            timeout_s=0.01,
            allowed_content_types=("text/html",),
        )

@pytest.mark.asyncio
async def test_safe_fetch_fails_closed_for_proxy_and_official_uses_safe_path(monkeypatch):
    cfg = OutboundConfig(
        channel_order=("local-proxy", "direct"), local_proxy="http://127.0.0.1:7897"
    )

    async def probe(_source, channel):
        return channel.name == "local-proxy"

    resolver = ChannelResolver(cfg=cfg, probe_fn=probe)
    with pytest.raises(UnsafeUrlError, match="cannot bind"):
        await resolver.safe_fetch("official", "https://example.com/")

    captured = {}

    async def fake_safe_fetch(source, url, **kwargs):
        captured.update(source=source, url=url, kwargs=kwargs)
        return httpx.Response(200, headers={"content-type": "text/html"})

    monkeypatch.setattr(official_module._outbound, "safe_fetch", fake_safe_fetch)
    assert await official_module.OfficialSearch()._verify_reachable("https://docs.example.com/")
    assert captured["source"] == "official"
    assert captured["kwargs"]["method"] == "HEAD"


@pytest.mark.asyncio
async def test_pinned_backend_uses_validated_ip_not_hostname():
    backend = _PinnedNetworkBackend("93.184.216.34")
    captured = {}

    class Delegate:
        async def connect_tcp(self, host, port, **kwargs):
            captured.update(host=host, port=port)
            return object()

    backend._backend = Delegate()
    await backend.connect_tcp("attacker-controlled.example", 443)
    assert captured == {"host": "93.184.216.34", "port": 443}


def test_forward_allowlist_uses_exact_hosts_and_explicit_wildcards():
    cfg = OutboundConfig(
        channel_order=("self-forward",),
        fwd_base="https://forward.example",
        fwd_allowed=("api.example.com", "*.docs.example.com"),
    )
    channel = SelfForwardChannel(cfg)
    assert channel.is_allowed("https://api.example.com/path")
    assert channel.is_allowed("https://v1.docs.example.com/path")
    assert not channel.is_allowed("https://api.example.com.evil.test/path")
    assert not channel.is_allowed("https://user@api.example.com/path")
    assert not channel.is_allowed("http://api.example.com/path")
    assert not channel.is_allowed("https://api.example.com:444/path")
    assert not channel.is_allowed("https://docs.example.com/path")


async def _run_asgi(middleware, headers, incoming):
    sent = []
    messages = iter(incoming)

    async def receive():
        return next(messages)

    async def send(message):
        sent.append(message)

    await middleware({"type": "http", "headers": headers}, receive, send)
    return sent


@pytest.mark.asyncio
async def test_body_limit_rejects_declared_and_streamed_sizes():
    async def app(_scope, receive, send):
        body = bytearray()
        while True:
            message = await receive()
            body.extend(message.get("body", b""))
            if not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": bytes(body)})

    middleware = RequestBodyLimitMiddleware(app, max_bytes=4)
    declared = await _run_asgi(
        middleware,
        [(b"content-length", b"5")],
        [{"type": "http.request", "body": b"12345", "more_body": False}],
    )
    assert declared[0]["status"] == 413
    assert json.loads(declared[1]["body"])["error"]["code"] == "REQUEST_BODY_TOO_LARGE"

    streamed = await _run_asgi(
        middleware,
        [],
        [
            {"type": "http.request", "body": b"123", "more_body": True},
            {"type": "http.request", "body": b"45", "more_body": False},
        ],
    )
    assert streamed[0]["status"] == 413

    conflicting = await _run_asgi(
        middleware,
        [(b"content-length", b"3"), (b"Content-Length", b"4")],
        [{"type": "http.request", "body": b"123", "more_body": False}],
    )
    assert conflicting[0]["status"] == 400

    invalid = await _run_asgi(
        middleware,
        [(b"content-length", b"+3")],
        [{"type": "http.request", "body": b"123", "more_body": False}],
    )
    assert invalid[0]["status"] == 400


def test_research_and_clarify_text_boundaries():
    with pytest.raises(ValidationError):
        ResearchRequest(query="unsafe\x00query")
    with pytest.raises(ValidationError):
        ResearchRequest(
            query="x" * 4000,
            constraints=["y" * 500 for _ in range(50)],
            candidate_techs=["z" * 500 for _ in range(10)],
        )
    assert StartRequest(query=" x ").query == "x"
    assert MessageRequest(message=" y ").message == "y"
    for model, payload in (
        (StartRequest, {"query": "x", "extra": True}),
        (MessageRequest, {"message": "x", "extra": True}),
        (StartRequest, {"query": "x\u202e"}),
        (MessageRequest, {"message": "x" * 2001}),
    ):
        with pytest.raises(ValidationError):
            model.model_validate(payload)


def test_session_state_and_manager_enforce_collection_and_id_limits():
    manager = SessionManager()
    created = manager.create("FastAPI or Flask")
    state = manager.get(created["session_id"])
    assert state.messages[0] == {"role": "user", "content": "FastAPI or Flask"}
    with pytest.raises(KeyError):
        manager.get("clarify_../../etc")
    with pytest.raises(ValidationError):
        SessionState(candidate_techs=["x"] * 51)
    with pytest.raises(ValueError):
        manager.process_message(created["session_id"], "x\x00")


@pytest.mark.asyncio
async def test_application_wires_request_body_limit():
    transport = httpx.ASGITransport(app=server_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/not-found", content=b"x" * (128 * 1024 + 1))
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "REQUEST_BODY_TOO_LARGE"


def test_clarification_agent_rejects_unbounded_model_collections():
    state = SessionState(missing_required=["candidate_techs"])
    response = ClarificationAgent()._merge_and_build_response(
        state,
        {
            "action": "unexpected",
            "message": "ok",
            "candidate_techs": ["x"] * 51,
            "constraints": ["y"] * 51,
        },
    )
    assert state.candidate_techs == []
    assert state.constraints == []
    assert response["action"] == "ask"


def test_clarification_model_merge_is_atomic_on_invalid_output():
    state = SessionState(missing_required=["scene", "complexity"])
    with pytest.raises(ValidationError):
        ClarificationAgent()._merge_and_build_response(
            state,
            {"scene": "solo", "complexity": "invalid", "message": "ok"},
        )
    assert state.scene is None
    assert state.complexity is None
    assert state.filled_required == []
    assert state.missing_required == ["scene", "complexity"]


def test_clarification_output_closes_over_research_request_contract():
    state = SessionState(
        scene="team",
        complexity="medium",
        candidate_techs=["FastAPI", "Flask"],
        constraints=["small team"],
        messages=[{"role": "user", "content": "Compare FastAPI and Flask"}],
    )
    sub_questions = ["Which option has stronger typing?"]
    payload = _research_payload(state, sub_questions=sub_questions)
    request = ResearchRequest(**payload, sub_questions=sub_questions)
    assert request.query == "Compare FastAPI and Flask"
