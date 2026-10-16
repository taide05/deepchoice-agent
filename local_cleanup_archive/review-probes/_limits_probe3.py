"""Prove the Tavily POST stop line using the armed wrapper itself."""
import asyncio
import os
import sys
import time

os.environ["PRECODEX_LLM_MAX"] = "40"
os.environ["PRECODEX_TAVILY_MAX"] = "2"
os.environ["PRECODEX_WALL_MAX_S"] = "900"

sys.path.insert(0, r"D:\deepchoice-precodex\src")

import run_limits  # noqa: E402

run_limits.arm()

from deepchoice.retrievers import tavily_keypool, tavily_search  # noqa: E402

# Replace the failover that the COUNTED wrapper calls, so the guard still runs.
async def fake_failover(post, payload, *args, **kwargs):
    return await post("https://api.tavily.com/search", json=payload)


tavily_keypool.post_with_failover.__globals__["post_with_failover"] = fake_failover
# The counted wrapper closes over the original; patch the name it resolves.
import deepchoice.retrievers.tavily_keypool as kp  # noqa: E402

run_limits._state.update(started_at=time.monotonic(), tavily_posts=0,
                         tavily_rejected=0, stop_reason=None)

counted = tavily_search.post_with_failover  # the armed wrapper


async def main():
    async def transport(url, json=None, **kw):
        return {"called": url}

    print("--- Tavily counter via the armed wrapper (cap 2) ---")
    for index in range(1, 5):
        try:
            await counted(transport, {"query": "x"})
        except run_limits.DispatchLimitReached as exc:
            print(f"  tavily {index}: BLOCKED -> {exc}")
            break
        print(f"  tavily {index}: dispatched")

    snap = run_limits.snapshot()
    print("--- snapshot ---")
    for key in ("tavily_posts", "tavily_rejected", "stop_reason", "tavily_posts_max"):
        print(f"  {key:18}: {snap[key]}")


asyncio.run(main())
