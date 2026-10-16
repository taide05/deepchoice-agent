"""Offline proof of the stop lines. No network, no real credentials.

Reference counts are taken at httpx.AsyncClient.send (the actual socket write
attempt) and at the Tavily destination, independently of the guard under test.

Item 1  call_model's own retry loop against a transport that always fails:
        one guard increment per real send, and the failure surfaces.
Item 2  Tavily with a fake key, temporary key state and simulated transport:
        initialization probe, key failover, and the search entry point.
Item 3  a triggered limit aborts the work and is not swallowed.
"""
import asyncio
import os
import pathlib
import sys
import tempfile
import time

ROOT = pathlib.Path(r"D:\deepchoice-precodex")
STATE = pathlib.Path(tempfile.mkdtemp(prefix="precodex-limits-"))

os.environ["PRECODEX_LLM_MAX"] = "40"
os.environ["PRECODEX_TAVILY_MAX"] = "24"
os.environ["PRECODEX_WALL_MAX_S"] = "900"
os.environ["DS_FLASH_API_KEY"] = "fake-llm-key"
os.environ["DS_FLASH_BASE_URL"] = "https://llm.invalid/v1"
os.environ["TAVILY_API_KEYS"] = "fake-tavily-key"
os.environ["TAVILY_KEY_STATE_PATH"] = str(STATE / "tavily_key_state.json")

sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

results: list[tuple[str, bool, str]] = []
SENDS = {"n": 0}
TAVILY = {"n": 0}
MODE = {"fail": True}

# Reference counters, installed before the guard patches so the guard wraps them.
_real_send = httpx.AsyncClient.send
_real_post = httpx.AsyncClient.post


async def _counting_send(self, request, *args, **kwargs):
    SENDS["n"] += 1
    if MODE["fail"] and "api.tavily.com" not in str(request.url):
        raise httpx.ConnectError("simulated transport failure", request=request)
    return await _real_send(self, request, *args, **kwargs)


async def _counting_post(self, url, *args, **kwargs):
    target = url if isinstance(url, str) else str(url)
    if "api.tavily.com" in target:
        TAVILY["n"] += 1
    return await _real_post(self, url, *args, **kwargs)


httpx.AsyncClient.send = _counting_send
httpx.AsyncClient.post = _counting_post

import run_limits  # noqa: E402

run_limits.arm()

from deepchoice.utils import llm as llm_module  # noqa: E402
from deepchoice.retrievers import tavily_keypool as kp  # noqa: E402
import deepchoice.retrievers.tavily_search as ts  # noqa: E402


def check(label, ok, detail=""):
    results.append((label, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' -- ' + detail) if detail else ''}")


async def no_sleep(_delay):
    return None


async def item1():
    print("--- item 1: call_model retry loop counts every real send ---")
    llm_module._retry_sleep = no_sleep
    MODE["fail"] = True
    SENDS["n"] = 0
    run_limits._state.update(started_at=time.monotonic(), llm_requests=0,
                             llm_rejected=0, stop_reason=None)

    raised = None
    try:
        await llm_module.call_model([{"role": "user", "content": "ping"}],
                                    model="deepseek-flash", response_format="json",
                                    tag="limits-probe", usage=[])
    except Exception as exc:
        raised = exc

    expected = llm_module._MAX_RETRIES + 1
    check(f"guard incremented once per real send (expect {expected})",
          run_limits._state["llm_requests"] == expected,
          f"guard={run_limits._state['llm_requests']}")
    check("guard count equals actual sends",
          run_limits._state["llm_requests"] == SENDS["n"] == expected,
          f"actual={SENDS['n']}")
    check("failure surfaced, not swallowed", raised is not None, type(raised).__name__)


async def item2():
    print("--- item 2: Tavily probe / failover / search, fake key + temp state ---")
    from deepchoice.retrievers.tavily_keypool import _state_path
    check("key state file is the temporary one",
          pathlib.Path(_state_path()) == STATE / "tavily_key_state.json")

    for attr, value in (("_pool", []), ("_exhausted", {}), ("_probed", False)):
        setattr(kp, attr, value)
    run_limits._state.update(tavily_posts=0, tavily_rejected=0, stop_reason=None)
    TAVILY["n"] = 0

    transport = httpx.MockTransport(lambda req: httpx.Response(
        200, json={"results": [{"url": "https://example.invalid/a",
                                "title": "t", "content": "c"}]}, request=req))
    async with httpx.AsyncClient(transport=transport) as client:
        async def post(url, json=None, **kw):
            return await client.post(url, json=json, **kw)

        await kp.ensure_probed(post)
        check("initialization probe counted",
              run_limits._state["tavily_posts"] >= 1 and TAVILY["n"] >= 1,
              f"guard={run_limits._state['tavily_posts']} actual={TAVILY['n']}")

        before = run_limits._state["tavily_posts"]
        await kp.post_with_failover(post, {"query": "q", "max_results": 1})
        check("key failover path counted", run_limits._state["tavily_posts"] > before,
              f"{before} -> {run_limits._state['tavily_posts']}")

        before = run_limits._state["tavily_posts"]
        before_actual = TAVILY["n"]
        try:
            await ts.TavilySearch()._do_search("q", [], 3)
        except Exception as exc:
            print(f"        (search raised {type(exc).__name__})")
        check("search entry counted",
              run_limits._state["tavily_posts"] > before and TAVILY["n"] > before_actual,
              f"guard {before} -> {run_limits._state['tavily_posts']}")


async def item3():
    print("--- item 3: a triggered limit aborts, not swallowed ---")
    MODE["fail"] = False
    run_limits._state.update(started_at=time.monotonic(),
                             llm_requests=run_limits.LLM_REQUESTS_MAX,
                             llm_rejected=0, stop_reason=None)
    SENDS["n"] = 0
    raised = None
    try:
        await llm_module.call_model([{"role": "user", "content": "ping"}],
                                    model="deepseek-flash", tag="limits-probe", usage=[])
    except Exception as exc:
        raised = exc
    check("LLM limit surfaced as DispatchLimitReached",
          isinstance(raised, run_limits.DispatchLimitReached), type(raised).__name__)
    check("no real send after the limit", SENDS["n"] == 0, f"sends={SENDS['n']}")

    run_limits._state.update(tavily_posts=run_limits.TAVILY_POSTS_MAX,
                             tavily_rejected=0, stop_reason=None)
    TAVILY["n"] = 0
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={}, request=req))
    async with httpx.AsyncClient(transport=transport) as client:
        async def post(url, json=None, **kw):
            return await client.post(url, json=json, **kw)
        raised = None
        try:
            await kp.post_with_failover(post, {"query": "q"})
        except Exception as exc:
            raised = exc
    check("Tavily limit surfaced as DispatchLimitReached",
          isinstance(raised, run_limits.DispatchLimitReached), type(raised).__name__)
    check("no real Tavily POST after the limit", TAVILY["n"] == 0,
          f"posts={TAVILY['n']}")


async def main():
    await item1()
    await item2()
    await item3()
    print("--- summary ---")
    for label, ok, _ in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    failed = [r for r in results if not r[1]]
    print(f"  {len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


sys.exit(asyncio.run(main()))
