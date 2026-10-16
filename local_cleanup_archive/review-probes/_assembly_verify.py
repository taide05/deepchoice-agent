"""Offline check through the REAL startup assembly path.

Only two things are faked: credential loading (a fake local file) and external
HTTP (simulated responses). The real limit wiring, the real entry point and the
real research assembly are used, so a wiring mistake would show up here.
"""
import json
import os
import pathlib
import runpy
import sys
import tempfile

WORKTREE = pathlib.Path(r"D:\deepchoice-precodex")
TMP = pathlib.Path(tempfile.mkdtemp(prefix="precodex-assembly-"))

# --- fake credential file, in the exact shape load_credentials expects ---
fake_env = TMP / "fake.env"
fake_env.write_text(
    "DS_FLASH_API_KEY=fake-llm-key\n"
    "DS_FLASH_BASE_URL=https://llm.invalid/v1\n"
    "TAVILY_API_KEYS=key-A,key-B,key-C\n"
    "TAVILY_API_KEY=key-A\n",
    encoding="utf-8",
)

os.environ["PRECODEX_LLM_MAX"] = "40"
os.environ["PRECODEX_TAVILY_MAX"] = "24"
os.environ["PRECODEX_WALL_MAX_S"] = "900"
os.environ["TAVILY_KEY_STATE_PATH"] = str(TMP / "tavily_key_state.json")

sys.path.insert(0, str(WORKTREE / "src"))
sys.path.insert(0, str(WORKTREE))

checks = []


def check(label, ok, detail=""):
    checks.append((label, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' -- ' + detail) if detail else ''}")


import run_service  # noqa: E402  (the real entry module)

# Keep the real code path, but point the credential file at the fake one.
run_service.CURRENT_ENV = fake_env

import run_limits  # noqa: E402

# Fake the external HTTP at the lowest level: all responses simulated.
import httpx  # noqa: E402

_real_send = httpx.AsyncClient.send
_calls = {"llm": 0, "tavily": 0}


async def fake_send(self, request, *args, **kwargs):
    url = str(request.url)
    if "api.tavily.com" in url:
        _calls["tavily"] += 1
        return httpx.Response(200, json={"results": [
            {"url": "https://example.invalid/a", "title": "t", "content": "c"}]},
            request=request)
    _calls["llm"] += 1
    return httpx.Response(200, json={
        "choices": [{"message": {"content": '{"sub_questions":["a","b"]}'}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }, request=request)


httpx.AsyncClient.send = fake_send

# --- exercise the real wiring in the order run_service.main() uses it ---
loaded = run_service.load_credentials()
check("fake credentials loaded through the real loader",
      "DS_FLASH_API_KEY" in loaded and "TAVILY_API_KEYS" in loaded,
      f"{len(loaded)} names")

key_count = run_limits.normalize_single_tavily_key()
check("single-key normalisation applied", key_count == 1, f"keys={key_count}")

run_limits.arm()
run_limits.arm_run_timer()

from deepchoice.retrievers import tavily_keypool as kp  # noqa: E402
from deepchoice.agents import orchestrator  # noqa: E402
from deepchoice.utils import llm as llm_module  # noqa: E402

check("key pool holds exactly one key", len(kp._load_keys()) == 1,
      f"keys={len(kp._load_keys())}")
check("LLM client is the counting subclass",
      llm_module.AsyncOpenAI.__name__ == "CountingAsyncOpenAI",
      llm_module.AsyncOpenAI.__name__)
check("research stream is the timed async generator",
      __import__("inspect").isasyncgenfunction(
          orchestrator.ChiefEditorAgent.astream_research_task))
check("real imported source is the worktree",
      str(pathlib.Path(llm_module.__file__).resolve()).lower().startswith(
          str(WORKTREE).lower()))

import asyncio  # noqa: E402


async def drive_real_llm():
    """One real call through the counting client into the faked transport."""
    client = llm_module.AsyncOpenAI(api_key="fake", base_url="https://llm.invalid/v1")
    response = await client.chat.completions.create(
        model="m", messages=[{"role": "user", "content": "hi"}])
    return response


asyncio.run(drive_real_llm())
check("a real LLM call went through the guard",
      run_limits._state["llm_requests"] >= 1 and _calls["llm"] >= 1,
      f"guard={run_limits._state['llm_requests']} transport={_calls['llm']}")


async def drive_real_tavily():
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={}, request=r))
    async with httpx.AsyncClient(transport=transport) as client:
        async def post(url, json=None, **kw):
            return await client.post(url, json=json, **kw)
        await kp.post_with_failover(post, {"query": "q", "max_results": 1})


asyncio.run(drive_real_tavily())
check("a real Tavily POST went through the guard",
      run_limits._state["tavily_posts"] >= 1, f"guard={run_limits._state['tavily_posts']}")

snap = run_limits.snapshot()
print("--- counters after the assembly run ---")
for key in ("llm_requests", "tavily_posts", "stop_reason", "run_elapsed_s"):
    print(f"  {key:18}: {snap.get(key)}")

httpx.AsyncClient.send = _real_send
print("--- summary ---")
for label, ok, _ in checks:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
failed = [c for c in checks if not c[1]]
print(f"  {len(checks) - len(failed)}/{len(checks)} checks passed")
sys.exit(1 if failed else 0)
