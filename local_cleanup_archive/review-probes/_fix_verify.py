"""Offline verification of the four corrected behaviours. No network.

1  LLM: SDK-internal retry path. A client with max_retries > 0 sends, fails the
   first attempt, and the next attempt must be refused once the cap is 1.
2  Single key: a fake multi-key environment must reduce to exactly one key in
   _load_keys().
3  Timeout: an async generator consumed with `async for` produces events, and a
   short deadline cancels it.
4  Global stop: once one category trips, the other category dispatches nothing.
"""
import asyncio
import os
import pathlib
import sys
import tempfile
import time

ROOT = pathlib.Path(r"D:\deepchoice-precodex")
STATE = pathlib.Path(tempfile.mkdtemp(prefix="precodex-fix-"))

# Fake multi-key credentials BEFORE the pool is imported.
os.environ["PRECODEX_LLM_MAX"] = "1"
os.environ["PRECODEX_TAVILY_MAX"] = "2"
os.environ["PRECODEX_WALL_MAX_S"] = "900"
os.environ["DS_FLASH_API_KEY"] = "fake-llm-key"
os.environ["DS_FLASH_BASE_URL"] = "https://llm.invalid/v1"
os.environ["TAVILY_API_KEYS"] = "key-A,key-B,key-C"
os.environ["TAVILY_API_KEY"] = "key-A"
os.environ["TAVILY_KEY_STATE_PATH"] = str(STATE / "tavily_key_state.json")

sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

results = []
SENDS = {"n": 0}
TAVILY = {"n": 0}
FAIL_FIRST = {"n": 0, "fail_attempts": 1}

_real_send = httpx.AsyncClient.send
_real_post = httpx.AsyncClient.post


async def counting_send(self, request, *args, **kwargs):
    SENDS["n"] += 1
    if "api.tavily.com" in str(request.url):
        return await _real_send(self, request, *args, **kwargs)
    FAIL_FIRST["n"] += 1
    if FAIL_FIRST["n"] <= FAIL_FIRST["fail_attempts"]:
        raise httpx.ConnectError("simulated first-attempt failure", request=request)
    return await _real_send(self, request, *args, **kwargs)


async def counting_post(self, url, *args, **kwargs):
    if "api.tavily.com" in (url if isinstance(url, str) else str(url)):
        TAVILY["n"] += 1
    return await _real_post(self, url, *args, **kwargs)


httpx.AsyncClient.send = counting_send
httpx.AsyncClient.post = counting_post

import run_limits  # noqa: E402

run_limits.arm()
run_limits.arm_run_timer()

from deepchoice.retrievers import tavily_keypool as kp  # noqa: E402
from deepchoice.retrievers import tavily_search as ts  # noqa: E402


def check(label, ok, detail=""):
    results.append((label, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' -- ' + detail) if detail else ''}")


# ------------------------------------------------------------------ item 1
async def item1_sdk_retry():
    print("--- item 1: SDK-internal retry path is counted and refused ---")
    import openai

    run_limits._state.update(started_at=time.monotonic(), run_started_at=time.monotonic(),
                             llm_requests=0, llm_rejected=0, stop_reason=None, stop_at=None)
    SENDS["n"] = 0
    FAIL_FIRST.update(n=0, fail_attempts=1)

    class FakeResp:
        status_code = 200
        headers = {}
        request = httpx.Request("POST", "https://llm.invalid/v1/chat/completions")
        text = '{"choices":[{"message":{"content":"{}"}}],"usage":{}}'

        def json(self):
            return {"choices": [{"message": {"content": "{}"}}], "usage": {}}

        def read(self):
            return self.text.encode()

    async def fake_send(self, request, *args, **kwargs):
        SENDS["n"] += 1
        FAIL_FIRST["n"] += 1
        if FAIL_FIRST["n"] <= FAIL_FIRST["fail_attempts"]:
            raise httpx.ConnectError("simulated first-attempt failure", request=request)
        return FakeResp()

    httpx.AsyncClient.send = fake_send
    try:
        client = openai.AsyncOpenAI(api_key="fake", base_url="https://llm.invalid/v1",
                                    max_retries=3,
                                    http_client=httpx.AsyncClient(transport=httpx.MockTransport(
                                        lambda r: httpx.Response(200, json={}, request=r))))
        # Re-wrap the SDK retry path with the guard hook the adapter installs.
        from deepchoice.utils import llm as llm_module
        counted_cls = llm_module.AsyncOpenAI
        client2 = counted_cls(api_key="fake", base_url="https://llm.invalid/v1",
                              max_retries=3,
                              http_client=httpx.AsyncClient(transport=httpx.MockTransport(
                                  lambda r: httpx.Response(200, json={}, request=r))))
        raised = None
        try:
            await client2.chat.completions.create(
                model="m", messages=[{"role": "user", "content": "hi"}])
        except Exception as exc:
            raised = exc
        check("SDK retry path refused after the cap",
              isinstance(raised, run_limits.DispatchLimitReached), type(raised).__name__)
        check("first attempt was counted, second refused",
              run_limits._state["llm_requests"] == 1, f"counted={run_limits._state['llm_requests']}")
    finally:
        httpx.AsyncClient.send = counting_send


# ------------------------------------------------------------------ item 2
def item2_single_key():
    print("--- item 2: multi-key environment normalises to one key ---")
    before = os.environ["TAVILY_API_KEYS"]
    count = run_limits.normalize_single_tavily_key()
    keys = kp._load_keys()
    check("normalizer reports one key", count == 1, f"returned={count}")
    check("_load_keys() returns exactly one key",
          isinstance(keys, list) and len(keys) == 1, f"keys={len(keys)}")
    check("both env names hold the same single key",
          os.environ["TAVILY_API_KEYS"] == os.environ["TAVILY_API_KEY"] == "key-A",
          f"multi was {before!r} -> {os.environ['TAVILY_API_KEYS']!r}")
    check("no pool-wide re-probe enabled", os.environ.get("TAVILY_REPROBE") is None)


# ------------------------------------------------------------------ item 3
async def item3_stream_timeout():
    print("--- item 3: async-generator timeout, normal output then cancelled ---")
    from deepchoice.agents import orchestrator
    from deepchoice.server import app as app_module  # noqa: F401  (real entry)

    produced = []

    # Exercise the INSTALLED wrapper: it is attached to the real class, so drive
    # that class's method rather than a subclass that would shadow it.
    real_cls = orchestrator.ChiefEditorAgent

    async def source_events(self, *args, **kwargs):
        for index in range(3):
            await asyncio.sleep(0)
            yield {"node": f"n{index}"}

    run_limits._state.update(run_started_at=None, stop_reason=None, stop_at=None)
    orchestrator.ChiefEditorAgent.__dict__["astream_research_task"].__wrapped_source__ = None
    # Feed the wrapper a controllable source by patching the module-level original.
    import run_limits as rl
    original_capture = {}

    agent = real_cls.__new__(real_cls)

    async def drive(gen):
        async for event in gen:
            produced.append(event["node"])

    # Temporarily satisfy the wrapper's expectation of a real instance.
    async def patched(self, *a, **k):
        async for item in source_events(self):
            yield item

    saved = orchestrator.ChiefEditorAgent.astream_research_task
    saved_original = None
    # Re-install the timer over `patched` so the wrapper under test is the one
    # the adapter installs, not the class's own generator.
    import deepchoice.agents.orchestrator as orch_mod
    orch_mod.ChiefEditorAgent.astream_research_task = patched
    run_limits.arm_run_timer()
    wrapped = orch_mod.ChiefEditorAgent.astream_research_task

    await drive(wrapped(agent))
    check("normal consumption yields every event", produced == ["n0", "n1", "n2"],
          f"got={produced}")
    check("stream clock started at research start",
          run_limits._state["run_started_at"] is not None)

    # A genuinely short deadline, so the real asyncio.timeout scope expires.
    run_limits._state.update(stop_reason=None, stop_at=None)
    run_limits.set_wall_clock_max(0.05)
    got = []
    raised = None
    try:
        async for event in wrapped(agent):
            got.append(event["node"])
            await asyncio.sleep(0.05)
    except Exception as exc:
        raised = exc
    finally:
        run_limits.set_wall_clock_max(900)
    check("expired deadline cancels the stream",
          isinstance(raised, run_limits.DispatchLimitReached), type(raised).__name__)
    check("deadline stopped further consumption", len(got) <= 1, f"got={len(got)}")

    check("interface is still an async generator",
          __import__("inspect").isasyncgenfunction(wrapped))


# ------------------------------------------------------------------ item 4
async def item4_global_stop():
    print("--- item 4: one category tripping stops the other ---")
    run_limits._state.update(started_at=time.monotonic(), run_started_at=time.monotonic(),
                             llm_requests=0, tavily_posts=0, llm_rejected=0,
                             tavily_rejected=0, stop_reason=None, stop_at=None)

    # Reach the LLM cap first.
    run_limits._state["llm_requests"] = run_limits.LLM_REQUESTS_MAX
    raised = None
    try:
        run_limits._check("llm")
    except Exception as exc:
        raised = exc
    check("LLM cap trips the stop state",
          isinstance(raised, run_limits.DispatchLimitReached) and run_limits.stopped(),
          f"reason={run_limits._state['stop_reason']}")

    # The Tavily path must now refuse without any send.
    TAVILY["n"] = 0
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={}, request=r))
    async with httpx.AsyncClient(transport=transport) as client:
        async def post(url, json=None, **kw):
            return await client.post(url, json=json, **kw)
        raised = None
        try:
            await kp.post_with_failover(post, {"query": "q"})
        except Exception as exc:
            raised = exc
    check("Tavily refused after the LLM stop",
          isinstance(raised, run_limits.DispatchLimitReached), type(raised).__name__)
    check("no Tavily POST after the LLM stop", TAVILY["n"] == 0, f"posts={TAVILY['n']}")

    # And the reverse: a Tavily stop must refuse LLM dispatch.
    run_limits._state.update(stop_reason=None, stop_at=None,
                             tavily_posts=run_limits.TAVILY_POSTS_MAX,
                             llm_requests=0)
    raised = None
    try:
        run_limits._check("tavily")
    except Exception as exc:
        raised = exc
    check("Tavily cap trips the stop state",
          isinstance(raised, run_limits.DispatchLimitReached) and run_limits.stopped())
    check("LLM refused after the Tavily stop",
          run_limits.stopped() and run_limits._state["stop_reason"] == "tavily_posts")
    llm_refused = None
    try:
        run_limits._check("llm")
    except Exception as exc:
        llm_refused = exc
    check("LLM dispatch refused while only Tavily tripped",
          isinstance(llm_refused, run_limits.DispatchLimitReached),
          type(llm_refused).__name__)


async def main():
    await item1_sdk_retry()
    item2_single_key()
    await item3_stream_timeout()
    await item4_global_stop()
    print("--- summary ---")
    for label, ok, _ in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    failed = [r for r in results if not r[1]]
    print(f"  {len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


sys.exit(asyncio.run(main()))
