"""Offline regressions for physical-request admission across research cases."""
import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from email.utils import format_datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from deepchoice import outbound
from deepchoice.retrievers import arxiv_api, github_rate, tavily_keypool
from deepchoice.outbound import throttle
from deepchoice.outbound.probe import ok_for
from deepchoice.outbound.probe import PROBES
from deepchoice.retrievers.community import CommunitySearch
from deepchoice.budget_errors import BudgetExceededError


@pytest.fixture
def virtual_clock(monkeypatch):
    now = [0.0]
    real_sleep = asyncio.sleep

    async def sleep(delay):
        now[0] += delay
        await real_sleep(0)

    monkeypatch.setattr(throttle, "_clock", lambda: now[0])
    monkeypatch.setattr(throttle, "_sleep", sleep)
    return now


def response(status=200, *, headers=None, body=None, xml=False):
    return httpx.Response(status, headers=headers, json=body if not xml else None,
                          text='<feed xmlns="http://www.w3.org/2005/Atom"/>' if xml else None,
                          request=httpx.Request("GET", "https://provider.example/search"))


@pytest.mark.asyncio
@pytest.mark.parametrize("key", [None, "", "fixture-key-one", "fixture-key-two"])
async def test_community_probe_and_search_share_request_local_credentials(key, virtual_clock, monkeypatch):
    from deepchoice.outbound.channels import OutboundConfig
    from deepchoice.outbound.resolver import ChannelResolver

    if key is None:
        monkeypatch.delenv("STACKEXCHANGE_API_KEY", raising=False)
    else:
        monkeypatch.setenv("STACKEXCHANGE_API_KEY", key)
    static_params = dict(PROBES["community"].params)
    calls = []

    @asynccontextmanager
    async def client():
        async def get(url, **kwargs):
            calls.append((url, dict(kwargs["params"])))
            return response(body={"items": []})
        yield SimpleNamespace(get=get)

    resolver = ChannelResolver(
        cfg=OutboundConfig(channel_order=("self-forward",)),
        channels=[SimpleNamespace(name="self-forward", kind="self-forward")],
    )
    monkeypatch.setattr(resolver, "_make_client", lambda _: client())
    health = await resolver.health_check(["community"])
    monkeypatch.setattr(outbound, "make_client", AsyncMock(side_effect=lambda _: client()))
    result = await CommunitySearch().search("fixture", [])

    assert health["ok"] and result["status"] == "success"
    assert len(calls) == 2
    for _, params in calls:
        assert params.get("key") == (key or None)
        assert ("key" in params) is bool(key)
    assert PROBES["community"].params == static_params and "key" not in static_params
    if key:
        assert key not in repr(resolver.summary()) + repr(health) + repr(result) + repr(PROBES)
    # Re-read on every request: neither adding, rotating nor removing a key
    # may leave credentials in the immutable, process-wide probe spec.
    monkeypatch.setenv("STACKEXCHANGE_API_KEY", "fixture-rotated")
    rotated_get = AsyncMock(return_value=response())
    assert await ok_for("community", SimpleNamespace(get=rotated_get))
    assert rotated_get.await_args.kwargs["params"]["key"] == "fixture-rotated"
    monkeypatch.delenv("STACKEXCHANGE_API_KEY", raising=False)
    get = AsyncMock(return_value=response())
    assert await ok_for("community", SimpleNamespace(get=get))
    assert "key" not in get.await_args.kwargs["params"]
    assert PROBES["community"].params == static_params
    monkeypatch.setenv("STACKEXCHANGE_API_KEY", "fixture-must-stay-community-only")
    other_get = AsyncMock(return_value=response(xml=True))
    assert await ok_for("arxiv", SimpleNamespace(get=other_get))
    assert "key" not in other_get.await_args.kwargs["params"]


@pytest.mark.asyncio
async def test_admission_interval_does_not_promise_delayed_client_start_spacing(virtual_clock):
    gate = throttle.RequestGate(interval=3.0, concurrency=1)
    grants, client_starts = [], []
    async with gate.slot():
        grants.append(virtual_clock[0])
        assert gate._active == 1
        virtual_clock[0] = 4.0  # delay after grant, before entering the client
        client_starts.append(virtual_clock[0])
    async with gate.slot():
        grants.append(virtual_clock[0])
        client_starts.append(virtual_clock[0])
    assert grants == [0.0, 4.0] and grants[1] - grants[0] >= gate.interval
    assert client_starts == [4.0, 4.0]  # not evidence of a broken grant interval
    assert gate._active == 0 and not gate._queue


@pytest.mark.asyncio
async def test_fifo_grants_and_concurrency_are_deterministic(virtual_clock):
    gate = throttle.RequestGate(interval=2.0, concurrency=2)
    grants = []
    first_two = asyncio.Event()
    release = asyncio.Event()

    async def worker(index):
        async with gate.slot():
            grants.append((index, virtual_clock[0], gate._active))
            if len(grants) == 2:
                first_two.set()
            if index < 2:
                await release.wait()

    jobs = [asyncio.create_task(worker(index)) for index in range(4)]
    try:
        await asyncio.wait_for(first_two.wait(), timeout=5.0)
        assert [index for index, _, _ in grants] == [0, 1]
        assert gate._active == 2 and len(gate._queue) == 2
        release.set()
        await asyncio.wait_for(asyncio.gather(*jobs), timeout=5.0)
    finally:
        for job in jobs:
            if not job.done():
                job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
    assert [index for index, _, _ in grants] == list(range(4))
    assert all(b[1] - a[1] >= 2.0 for a, b in zip(grants, grants[1:]))
    assert max(active for _, _, active in grants) == 2
    assert gate._active == 0 and not gate._queue


@pytest.mark.asyncio
async def test_arxiv_separate_cases_cannot_start_as_a_burst(monkeypatch):
    starts = []
    now = [0.0]
    real_sleep = asyncio.sleep

    async def sleep(delay):
        now[0] += delay
        await real_sleep(0)

    async def get(*args, **kwargs):
        starts.append(now[0])
        return response(xml=True)

    class Client:
        async def __aenter__(self):
            return SimpleNamespace(get=get)

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(throttle, "_sleep", sleep)
    monkeypatch.setattr(throttle, "_clock", lambda: now[0])
    monkeypatch.setattr(outbound, "make_client", AsyncMock(return_value=Client()))
    for query in ("case one", "case two"):
        result = await arxiv_api.ArxivSearch().search(query, [])
        assert result["status"] == "success"
    assert starts[1] - starts[0] >= 3.0


@pytest.mark.asyncio
async def test_tavily_startup_probe_uses_the_same_admission(monkeypatch):
    admitted = AsyncMock(wraps=tavily_keypool._post_once)
    monkeypatch.setattr(tavily_keypool, "_post_once", admitted)
    post = AsyncMock(return_value=response())
    assert await tavily_keypool._probe_one(post, "dummy")
    admitted.assert_awaited_once_with(post, "dummy", tavily_keypool._PROBE_PAYLOAD, probing=True)


def test_github_does_not_shorten_a_provider_retry_after():
    assert github_rate.retry_delay({"Retry-After": "120"}) >= 120


@pytest.mark.parametrize("bad", ["nan", "inf", "-3", True, object()])
def test_retry_after_rejects_nonfinite_negative_and_invalid_types(bad):
    assert throttle.retry_after({"Retry-After": bad}, default=7) == 7


def test_retry_after_http_date_and_reset_use_the_later_deadline(monkeypatch):
    monkeypatch.setattr(throttle.time, "time", lambda: 1000.0)
    value = format_datetime(datetime.fromtimestamp(1030, UTC), usegmt=True)
    assert throttle.retry_after({"retry-after": value}, default=7) == 30
    assert throttle.retry_after({"Retry-After": "20", "X-RateLimit-Reset": "1040"},
                                default=7, github=True) == 40


@pytest.mark.asyncio
async def test_oversized_cooldown_fails_without_dispatch_or_shortening(virtual_clock):
    gate = throttle.gate_for("arxiv")
    gate.defer(1000)
    client = SimpleNamespace(get=AsyncMock())
    with pytest.raises(throttle.ProviderRateLimitError):
        await throttle.get("arxiv", client, "https://unused")
    client.get.assert_not_awaited()
    assert gate.cooling_down() and not gate._queue and gate._active == 0


@pytest.mark.asyncio
async def test_cancel_queue_and_active_requests_release_capacity():
    gate = throttle.RequestGate(concurrency=1)
    active = asyncio.Event()
    release = asyncio.Event()

    async def worker():
        async with gate.slot():
            active.set()
            await release.wait()

    leader = asyncio.create_task(worker())
    await active.wait()
    queued = asyncio.create_task(worker())
    await asyncio.sleep(0)
    queued.cancel()
    with pytest.raises(asyncio.CancelledError):
        await queued
    assert len(gate._queue) == 0 and gate._active == 1
    leader.cancel()
    with pytest.raises(asyncio.CancelledError):
        await leader
    async with gate.slot(timeout=0.2):
        assert gate._active == 1
    assert gate._active == 0


@pytest.mark.asyncio
async def test_queue_timeout_and_overflow_do_not_dispatch(virtual_clock, monkeypatch):
    gate = throttle.RequestGate()
    async with gate.slot():
        with pytest.raises(throttle.ProviderAdmissionError, match="timed out"):
            async with gate.slot(timeout=0.1):
                pytest.fail("must remain queued")
    monkeypatch.setattr(throttle, "MAX_WAITERS", 0)
    with pytest.raises(throttle.ProviderAdmissionError, match="full"):
        async with gate.slot():
            pytest.fail("queue full must not dispatch")
    assert gate._active == 0 and not gate._queue


def test_gate_remains_usable_after_a_contended_event_loop_closes():
    gate = throttle.RequestGate()

    async def run():
        async def worker():
            async with gate.slot():
                await asyncio.sleep(0)
        await asyncio.gather(worker(), worker())

    asyncio.run(run())
    asyncio.run(run())
    assert gate._active == 0 and not gate._queue


@pytest.mark.asyncio
async def test_github_429_defers_already_queued_peer_and_retry(virtual_clock, monkeypatch):
    monkeypatch.setattr(github_rate, "interval_s", lambda: 0.0)
    starts = []
    request_started = asyncio.Event()
    answer = asyncio.Event()

    async def get(url, **kwargs):
        starts.append((url, virtual_clock[0]))
        if len(starts) == 1:
            request_started.set()
            await answer.wait()
            return response(429, headers={"Retry-After": "20"})
        return response()

    # Serialize for this regression so the peer was queued before feedback.
    throttle.gate_for("github").concurrency = 1
    client = SimpleNamespace(get=get)
    first = asyncio.create_task(github_rate.get_with_throttle(client, "first"))
    await request_started.wait()
    peer = asyncio.create_task(github_rate.get_with_throttle(client, "peer"))
    await asyncio.sleep(0)
    answer.set()
    results = await asyncio.gather(first, peer)
    assert all(result.status_code == 200 for result in results)
    assert len(starts) == 3 and all(when >= 20 for _, when in starts[1:])


@pytest.mark.asyncio
async def test_github_permission_denial_is_not_a_rate_limit(virtual_clock):
    get = AsyncMock(return_value=response(403, body={"message": "Resource not accessible"}))
    result = await github_rate.get_with_throttle(SimpleNamespace(get=get), "permission")
    assert result.status_code == 403 and get.await_count == 1
    assert not throttle.gate_for("github").cooling_down()


@pytest.mark.asyncio
async def test_successful_github_quota_exhaustion_defers_next_case(virtual_clock, monkeypatch):
    monkeypatch.setattr(throttle.time, "time", lambda: 1000)
    get = AsyncMock(side_effect=[response(headers={"X-RateLimit-Remaining": "0",
                                                  "X-RateLimit-Reset": "1030"}), response()])
    client = SimpleNamespace(get=get)
    await github_rate.get_with_throttle(client, "first")
    await github_rate.get_with_throttle(client, "second")
    assert virtual_clock[0] >= 30


@pytest.mark.asyncio
@pytest.mark.parametrize("first", [
    response(body={"items": [], "backoff": 30}),
    response(400, body={"error_id": 502, "error_name": "throttle_violation", "backoff": 30}),
    response(429, headers={"Retry-After": "30"}, body={"items": []}),
])
async def test_community_backoff_is_shared_even_on_error_or_last_attempt(first, virtual_clock):
    calls = []

    async def get(*args, **kwargs):
        calls.append(virtual_clock[0])
        return first if len(calls) == 1 else response(body={"items": []})

    client = SimpleNamespace(get=get)
    if throttle.is_limited("community", first):
        with pytest.raises(throttle.ProviderRateLimitError):
            await throttle.get("community", client, "first", max_retries=0)
    else:
        await throttle.get("community", client, "first", max_retries=0)
    await throttle.get("community", client, "next case")
    assert calls[1] - calls[0] >= 30


@pytest.mark.asyncio
async def test_probe_and_search_share_pacing_and_backoff(virtual_clock):
    times = []

    async def get(*args, **kwargs):
        times.append(virtual_clock[0])
        return response(429, headers={"Retry-After": "15"}) if len(times) == 1 else response(xml=True)

    client = SimpleNamespace(get=get)
    assert await ok_for("arxiv", client)  # reachable route
    assert throttle.gate_for("arxiv").cooling_down()
    await throttle.get("arxiv", client, "search")
    assert times[1] - times[0] >= 15


@pytest.mark.asyncio
async def test_tavily_probe_and_429_retry_are_paced_without_rotating(virtual_clock, monkeypatch):
    tavily_keypool._reset_for_tests()
    monkeypatch.setattr(tavily_keypool, "_pool", ["one", "two"])
    monkeypatch.setattr(tavily_keypool, "_probed", True)
    starts = []

    async def post(url, json):
        starts.append((json["api_key"], virtual_clock[0]))
        return response(429, headers={"Retry-After": "20"}) if len(starts) == 2 else response()

    await tavily_keypool._probe_one(post, "one")
    result, key = await tavily_keypool.post_with_failover(post, {"query": "fixture"})
    assert result.status_code == 200 and key == "one"
    assert [key for key, _ in starts] == ["one", "one", "one"]
    assert starts[1][1] - starts[0][1] >= 12
    assert starts[2][1] - starts[1][1] >= 20
    assert tavily_keypool._exhausted == {}


@pytest.mark.asyncio
async def test_waiting_tavily_key_does_not_block_other_key(virtual_clock, monkeypatch):
    tavily_keypool._reset_for_tests()
    monkeypatch.setattr(tavily_keypool, "_pool", ["blocked", "ready"])
    entered = asyncio.Event()
    release = asyncio.Event()

    async def post(url, json):
        if json["api_key"] == "blocked":
            entered.set()
            await release.wait()
        return response()

    pending = asyncio.create_task(tavily_keypool._post_once(post, "blocked", {}))
    await entered.wait()
    assert (await tavily_keypool._post_once(post, "ready", {})).status_code == 200
    release.set()
    await pending


@pytest.mark.asyncio
async def test_rate_limit_failure_does_not_invalidate_route(virtual_clock, monkeypatch):
    fake = SimpleNamespace(invalidate=AsyncMock())
    monkeypatch.setattr(outbound, "get_resolver", lambda: fake)

    @asynccontextmanager
    async def client():
        yield SimpleNamespace(get=AsyncMock(return_value=response(429, headers={"Retry-After": "0"})))

    monkeypatch.setattr(outbound, "make_client", AsyncMock(side_effect=lambda _: client()))
    result = await CommunitySearch().search("fixture", [])
    assert result["status"] == "failed" and result["results"] == []
    assert result["error"] == "ProviderRateLimitError: HTTP 429"
    fake.invalidate.assert_not_awaited()


@pytest.mark.asyncio
async def test_scholarly_tool_and_normal_arxiv_share_gate(virtual_clock, monkeypatch):
    from deepchoice.agents.conflict_detector import _execute_search

    starts = []

    async def get(*args, **kwargs):
        starts.append(virtual_clock[0])
        return response(xml=True)

    @asynccontextmanager
    async def client():
        yield SimpleNamespace(get=get)

    monkeypatch.setattr(outbound, "make_client", AsyncMock(side_effect=lambda _: client()))
    assert (await arxiv_api.ArxivSearch().search("fixture", []))["status"] == "success"
    assert json.loads(await _execute_search("search_scholarly", {"query": "fixture"})) == []
    assert starts[1] - starts[0] >= 3


@pytest.mark.asyncio
async def test_probe_503_publishes_shared_cooldown(virtual_clock):
    client = SimpleNamespace(get=AsyncMock(side_effect=[
        response(503, headers={"Retry-After": "20"}), response(xml=True)]))
    assert not await ok_for("arxiv", client)
    await throttle.get("arxiv", client, "next-route-or-case")
    assert virtual_clock[0] >= 20


@pytest.mark.asyncio
async def test_budget_failure_is_not_swallowed_by_probes(monkeypatch):
    from deepchoice.outbound.probe import probe_source

    error = BudgetExceededError("retrieval_calls", limit=1, consumed=1, requested=1)
    get = AsyncMock(side_effect=error)

    @asynccontextmanager
    async def client():
        yield SimpleNamespace(get=get)

    with pytest.raises(BudgetExceededError):
        await probe_source("arxiv", SimpleNamespace(name="self-forward", kind="self-forward"),
                           make_client=lambda _: client())
    get.assert_awaited_once()


@pytest.mark.asyncio
async def test_health_is_degraded_for_live_or_long_provider_cooldown(monkeypatch):
    from deepchoice.outbound.resolver import ChannelResolver
    from deepchoice.outbound.channels import OutboundConfig

    resolver = ChannelResolver(cfg=OutboundConfig(channel_order=("direct",)))
    throttle.gate_for("official-web").defer(100)
    monkeypatch.setattr(resolver, "_probe_for", AsyncMock(return_value=SimpleNamespace(name="direct")))
    health = await resolver.health_check(["official"])
    assert not health["ok"] and health["sources"]["official"]["status"] == "rate_limited"
    monkeypatch.setattr(resolver, "_probe_for", AsyncMock(side_effect=throttle.ProviderRateLimitError()))
    health = await resolver.health_check(["arxiv"])
    assert not health["ok"] and health["degraded_sources"] == ["arxiv"]


@pytest.mark.asyncio
async def test_official_fallback_drains_siblings_before_reporting_failure(monkeypatch):
    from deepchoice.retrievers import official

    pending = asyncio.Event()
    release = asyncio.Event()
    ended = []
    monkeypatch.setattr(official, "load_learned", lambda: {})
    monkeypatch.setattr(official, "learn", lambda *args, **kwargs: pytest.fail("failed source must not learn"))
    retriever = official.OfficialSearch()
    monkeypatch.setattr(retriever, "_propose_official_url", AsyncMock(side_effect=lambda term: f"https://{term}.dev/docs"))

    async def verify(url):
        if "alpha" in url:
            await pending.wait()
            raise throttle.ProviderRateLimitError()
        pending.set()
        await release.wait()
        ended.append(url)
        return True

    monkeypatch.setattr(retriever, "_verify_reachable", verify)
    task = asyncio.create_task(retriever.search("alpha beta", []))
    await asyncio.wait_for(pending.wait(), timeout=3)
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    result = await task
    assert result["status"] == "failed" and ended == ["https://beta.dev/docs"]


@pytest.mark.asyncio
async def test_tavily_fanout_drains_siblings_before_client_closes(monkeypatch):
    from deepchoice.retrievers import tavily_search

    pending = asyncio.Event()
    release = asyncio.Event()
    finished = []

    async def post(*args, **kwargs):
        return response()

    @asynccontextmanager
    async def client():
        yield SimpleNamespace(post=post)
        assert finished == ["slow"]

    async def fake_search(post, payload):
        if payload["query"] == "fail":
            await pending.wait()
            raise throttle.ProviderRateLimitError()
        pending.set()
        await release.wait()
        finished.append("slow")
        return response(body={"results": []}), "dummy"

    monkeypatch.setattr(outbound, "make_client", AsyncMock(side_effect=lambda _: client()))
    monkeypatch.setattr(tavily_search, "post_with_failover", fake_search)
    task = asyncio.create_task(tavily_search.TavilySearch().search("fixture", [], adapted_queries=["fail", "slow"]))
    await asyncio.wait_for(pending.wait(), timeout=3)
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    assert (await task)["status"] == "failed"


@pytest.mark.asyncio
async def test_mocked_twelve_cases_retain_six_source_results(monkeypatch, virtual_clock):
    """Scheduling integration only: real adapters, synthetic HTTP and local KB.

    Virtual time retains unscaled admission intervals and concurrency logic.
    Grant timestamps, not later client starts, validate the pacing contract.
    No real research queries, model, socket, embedding or local knowledge writes.
    """
    from deepchoice.agents import multi_retriever
    from deepchoice.retrievers import RETRIEVER_REGISTRY, chroma_kb, official

    monkeypatch.setattr(github_rate, "interval_s", lambda: 6.0)
    tavily_keypool._reset_for_tests()
    monkeypatch.setattr(tavily_keypool, "_pool", ["fixture-only"])
    monkeypatch.setattr(tavily_keypool, "_probed", True)
    monkeypatch.setattr(multi_retriever, "harvest", lambda *args, **kwargs: [])
    monkeypatch.setattr(official, "load_learned", lambda: {})
    monkeypatch.setattr(official.OfficialSearch, "_propose_official_url", AsyncMock(return_value=None))
    monkeypatch.setattr(chroma_kb, "get_embedding_model", lambda: SimpleNamespace(
        encode=lambda _: SimpleNamespace(tolist=lambda: [0.1, 0.2])))

    def kb_init(self):
        self.collection = SimpleNamespace(query=lambda **_: {
            "ids": [["fixture"]], "documents": [["sqlite fixture evidence"]],
            "metadatas": [[{"url": "https://kb.example/doc", "title": "Fixture"}]],
        })

    monkeypatch.setattr(chroma_kb.ChromaKB, "__init__", kb_init)
    starts = {source: [] for source in ("arxiv", "community", "github", "official", "tavily")}
    grants = {source: [] for source in starts}
    provider_gates = {throttle.gate_for(source): source for source in starts if source != "tavily"}
    original_slot = throttle.RequestGate.slot

    @asynccontextmanager
    async def observed_slot(gate, **kwargs):
        async with original_slot(gate, **kwargs):
            source = provider_gates.get(gate)
            if source is None and gate in tavily_keypool._key_gates.values():
                source = "tavily"
            if source in grants:
                grants[source].append((virtual_clock[0], gate._active))
            yield

    monkeypatch.setattr(throttle.RequestGate, "slot", observed_slot)

    @asynccontextmanager
    async def client(source):
        async def get(*args, **kwargs):
            starts[source].append(throttle._clock())
            if source == "arxiv":
                return response(xml=True)
            if source == "github":
                return response(body={"items": [{"full_name": "fixture/repo", "html_url": "https://github.com/fixture/repo"}]})
            if source == "community":
                return response(body={"items": [{"title": "Fixture", "link": "https://stackoverflow.com/q/1",
                                                "body": "<p>SQLite fixture question body.</p>"}]})
            return response(404)

        async def post(*args, **kwargs):
            starts["tavily"].append(throttle._clock())
            return response(body={"results": [{"url": "https://web.example/doc", "title": "Fixture", "content": "sqlite fixture"}]})

        yield SimpleNamespace(get=get, post=post)

    monkeypatch.setattr(outbound, "make_client", AsyncMock(side_effect=client))
    state = {"task": {"query": "sqlite vs postgresql"}, "adapted_queries": {
        source: ["sqlite vs postgresql"] for source in RETRIEVER_REGISTRY}}
    agent = multi_retriever.MultiRetrieverAgent()
    single = await agent.run(state)
    concurrent = await asyncio.gather(*(agent.run(state) for _ in range(12)))

    def normalized(result):
        assert result["partial_failures"] == []
        assert len(result["search_results"]) == 6
        assert all(row["status"] == "success" for row in result["search_results"])
        return [(row["source"], row["results"]) for row in result["search_results"]]

    assert all(normalized(result) == normalized(single) for result in concurrent)
    for source, interval in (("arxiv", 3), ("community", 1), ("github", 6), ("official", 0.5), ("tavily", 12)):
        assert len(starts[source]) >= 13
        assert len(grants[source]) == len(starts[source])
        assert all(b[0] - a[0] >= interval for a, b in zip(grants[source], grants[source][1:]))
        assert max(active for _, active in grants[source]) <= (2 if source in {"github", "official"} else 1)
    assert all(gate._active == 0 and not gate._queue for gate in
               [*provider_gates, *tavily_keypool._key_gates.values()])
