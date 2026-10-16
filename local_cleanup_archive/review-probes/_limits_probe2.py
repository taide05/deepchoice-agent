"""Prove the Tavily POST stop line at the transport, and the wall-clock line."""
import asyncio
import os
import sys

os.environ["PRECODEX_LLM_MAX"] = "40"
os.environ["PRECODEX_TAVILY_MAX"] = "2"
os.environ["PRECODEX_WALL_MAX_S"] = "900"

sys.path.insert(0, r"D:\deepchoice-precodex\src")

import run_limits  # noqa: E402

run_limits.arm()

from deepchoice.retrievers import tavily_keypool  # noqa: E402

captured = {}


def fake_failover(post, payload):
    """Stand in for the real failover: invoke the transport it was handed."""
    captured["post"] = post
    return post("https://api.tavily.com/search", json=payload)


tavily_keypool.post_with_failover.__wrapped__ = None  # clarity only
import deepchoice.retrievers.tavily_search as tavily_search  # noqa: E402


async def exercise(failover):
    async def transport(url, json=None, **kw):
        return {"called": url}

    for index in range(1, 5):
        try:
            await failover(transport, {"query": "x"})
        except run_limits.DispatchLimitReached as exc:
            print(f"  tavily {index}: BLOCKED -> {exc}")
            return
        except Exception as exc:
            print(f"  tavily {index}: transport error {type(exc).__name__}")
            return
        print(f"  tavily {index}: dispatched")


async def main():
    # Swap the real failover for a spy so no key pool or network is needed.
    real = tavily_search.post_with_failover

    async def spy(post, payload, *args, **kwargs):
        return await fake_failover(post, payload)

    # Re-arm so the counted wrapper wraps the spy.
    tavily_keypool.post_with_failover = spy
    tavily_search.post_with_failover = spy
    run_limits._state["started_at"] = __import__("time").monotonic()
    run_limits._state["tavily_posts"] = 0
    run_limits._state["tavily_rejected"] = 0
    run_limits._state["stop_reason"] = None

    print("--- Tavily counter (cap 2) ---")
    await exercise(spy)

    print("--- wall clock line (deadline forced to now) ---")
    run_limits._state["started_at"] = __import__("time").monotonic() - 10_000
    run_limits._state["llm_requests"] = 0
    try:
        run_limits._guard("llm_requests", "llm_rejected", 40, "LLM request", "llm")
        print("  NOT blocked (unexpected)")
    except run_limits.DispatchLimitReached as exc:
        print(f"  blocked -> {exc}")

    snap = run_limits.snapshot()
    print("--- snapshot ---")
    for key in ("tavily_posts", "tavily_rejected", "stop_reason"):
        print(f"  {key:18}: {snap[key]}")


asyncio.run(main())
