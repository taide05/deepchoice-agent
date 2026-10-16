"""Prove the stop lines fire before dispatch, without contacting anything."""
import asyncio
import os
import sys

# Tight caps so the guard trips immediately.
os.environ["PRECODEX_LLM_MAX"] = "2"
os.environ["PRECODEX_TAVILY_MAX"] = "1"
os.environ["PRECODEX_WALL_MAX_S"] = "900"

sys.path.insert(0, r"D:\deepchoice-precodex\src")

import run_limits  # noqa: E402  (local module next to this file)

run_limits.arm()

from deepchoice.utils import llm  # noqa: E402
from deepchoice.retrievers import tavily_keypool  # noqa: E402

print("caps seen by module :", run_limits.LLM_REQUESTS_MAX, run_limits.TAVILY_POSTS_MAX)


class Reached:
    def __init__(self):
        self.r = None

    def set(self, request):
        self.r = request

    async def get(self, url, options, **kw):
        return {"ok": True}


async def llm_attempts() -> None:
    """Each create() is one real request; the counter must stop the third."""
    import openai

    client = llm._get_client(timeout=1.0, tier="deepseek-flash", max_retries=0)
    print("client class        :", type(client).__name__)
    for index in range(1, 5):
        try:
            # _send_request would hit the network; replace it with a stub so the
            # counter is exercised at the request() layer only.
            async def stub(*a, **k):
                return None

            client._send_request = stub
            await client.request(object, object())
        except run_limits.DispatchLimitReached as exc:
            print(f"  attempt {index}: BLOCKED -> {exc}")
            break
        except Exception as exc:
            print(f"  attempt {index}: passed guard, failed later ({type(exc).__name__})")
        else:
            print(f"  attempt {index}: passed guard")


async def tavily_attempts() -> None:
    post = Reached()

    async def transport(url, json=None, **kw):
        return post

    for index in range(1, 4):
        try:
            await tavily_keypool.post_with_failover(transport, {"query": "x"})
        except run_limits.DispatchLimitReached as exc:
            print(f"  tavily {index}: BLOCKED -> {exc}")
            break
        except Exception as exc:
            print(f"  tavily {index}: passed guard, failed later ({type(exc).__name__})")
        else:
            print(f"  tavily {index}: passed guard")


async def main() -> None:
    print("--- LLM counter ---")
    await llm_attempts()
    print("--- Tavily counter ---")
    await tavily_attempts()
    print("--- snapshot ---")
    snap = run_limits.snapshot()
    for key in ("llm_requests", "llm_rejected", "tavily_posts", "tavily_rejected",
                "stop_reason", "llm_requests_max", "tavily_posts_max"):
        print(f"  {key:18}: {snap[key]}")


asyncio.run(main())
