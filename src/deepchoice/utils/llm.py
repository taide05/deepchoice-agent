import asyncio
import os
import random
import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Any

import json_repair
from langchain_core.utils.json import parse_json_markdown
from openai import APIConnectionError, AsyncOpenAI

DEEPSEEK_BASE = "https://api.deepseek.com/v1"

# Diagnostics (task 0.2): optional observer hook + current-case context.
# Both default to inert so the production path is unchanged when disabled.
_record_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None
_current_case: ContextVar[str] = ContextVar("dc_current_case", default="")


def set_record_callback(cb: Callable[[dict[str, Any]], Awaitable[None]] | None) -> None:
    global _record_callback
    _record_callback = cb


def set_current_case(case_id: str) -> None:
    _current_case.set(case_id)


async def _emit_record(entry: dict[str, Any]) -> None:
    if _record_callback is not None:
        try:
            await _record_callback(entry)
        except Exception:
            pass  # diagnostics must never break the pipeline


def _env(*names: str, default: str = "") -> str:
    for n in names:
        v = os.environ.get(n, "")
        if v:
            return v
    return default


# Tier -> provider config (user decision 2026-09-01): two flash tiers —
# deepseek-flash (the hot, high-frequency path) and qwen-flash (report
# synthesis + conflict re-arbitration).
#
# RECOVERY ADAPTER (2026-10-14): this revision is 48b32bd + a service
# adaptation, NOT a reproduction of the historical model setup. The retired
# Qwen/DashScope tier no longer has credentials, so the qwen-flash tier name is
# kept for the unchanged call sites but served by the current DeepSeek service
# and credential. The Qwen-only `enable_thinking` payload is dropped because it
# is not part of the DeepSeek request contract. No research node, prompt or
# answer-handling rule is changed; only the transport target. Callers that still
# request `model="qwen-flash"` therefore no longer select a second provider.
TIERS = {
    "deepseek-flash": {
        "model": _env("DS_FLASH_MODEL", "FLASH_MODEL", default="deepseek-v4-flash"),
        "base": _env("DS_FLASH_BASE_URL", "FLASH_BASE_URL", "DEEPSEEK_BASE_URL", default=DEEPSEEK_BASE),
        "key": _env("DS_FLASH_API_KEY", "FLASH_API_KEY", "DEEPSEEK_API_KEY"),
    },
    "qwen-flash": {
        "model": _env("DS_FLASH_MODEL", "FLASH_MODEL", default="deepseek-v4-flash"),
        "base": _env("DS_FLASH_BASE_URL", "FLASH_BASE_URL", "DEEPSEEK_BASE_URL", default=DEEPSEEK_BASE),
        "key": _env("DS_FLASH_API_KEY", "FLASH_API_KEY", "DEEPSEEK_API_KEY"),
    },
}

_MAX_RETRIES = 2
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


async def _retry_sleep(delay: float) -> None:
    await asyncio.sleep(delay)


def _get_client(timeout: float = 120.0, tier: str = "deepseek-flash",
                max_retries: int | None = None) -> AsyncOpenAI:
    cfg = TIERS.get(tier, TIERS["deepseek-flash"])
    kwargs = {"api_key": cfg["key"], "base_url": cfg["base"], "timeout": timeout}
    if max_retries is not None:
        kwargs["max_retries"] = max_retries
    return AsyncOpenAI(**kwargs)


def summarize_usage(agent_name: str, usage: list[dict]) -> dict:
    """Aggregate per-call usage records into one state row for an agent.

    Returns a dict ready to append to ResearchState["token_usage"]:
    {"agent", "model", "calls", "prompt_tokens", "completion_tokens", "total_tokens"}.
    If all calls used the same model, "model" is that name; otherwise the
    comma-joined unique model names in first-seen order.
    """
    if not usage:
        return {
            "agent": agent_name,
            "model": "",
            "calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

    models = [u.get("model", "") for u in usage]
    unique = list(dict.fromkeys(models))
    if len(unique) == 1:
        model = unique[0]
    else:
        model = ",".join(m for m in unique if m)

    return {
        "agent": agent_name,
        "model": model,
        "calls": len(usage),
        "prompt_tokens": sum(u.get("prompt_tokens", 0) for u in usage),
        "completion_tokens": sum(u.get("completion_tokens", 0) for u in usage),
        "total_tokens": sum(u.get("total_tokens", 0) for u in usage),
    }


async def call_model(
    prompt: list[dict],
    model: str = "deepseek-flash",
    response_format: str | None = None,
    timeout: float = 120.0,
    usage: list | None = None,
    tag: str = "",
    extra_body: dict | None = None,
) -> dict | str:
    tier = model if model in TIERS else "deepseek-flash"
    cfg = TIERS[tier]
    model = cfg["model"]
    if isinstance(prompt, list):
        prompt = list(prompt)
    client = _get_client(timeout=timeout, tier=tier, max_retries=0)
    kwargs = {"model": model, "messages": prompt, "temperature": 0}
    # Per-call extra_body overrides the tier default; otherwise the tier's
    # default (qwen-flash disables thinking) applies. This lets a single node
    # opt back into thinking without forking the tier table.
    extra = extra_body if extra_body is not None else cfg.get("extra_body")
    if extra:
        kwargs["extra_body"] = extra
    if response_format == "json":
        kwargs["response_format"] = {"type": "json_object"}
        # DashScope/Qwen requires the prompt to mention "json" for json_object;
        # append a guard sentence when absent (otherwise 400s across the board).
        joined = " ".join(
            str(m.get("content", "")) for m in prompt if isinstance(m.get("content"), str)
        )
        if "json" not in joined.lower():
            kwargs["messages"] = prompt + [
                {"role": "user", "content": "Respond with valid JSON only."}
            ]

    t0 = time.monotonic()
    response = None
    try:
        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = await client.chat.completions.create(**kwargs)
                break
            except Exception as e:
                status = getattr(e, "status_code", None)
                retryable = isinstance(e, APIConnectionError) or status in _RETRYABLE_STATUSES
                if not retryable or attempt >= _MAX_RETRIES:
                    raise
                delay = (2 ** attempt) * 5.0 * (0.5 + random.random())
                await _retry_sleep(delay)
    except Exception as e:
        await _emit_record({
            "case_id": _current_case.get(),
            "tag": tag or tier,
            "tier": tier,
            "model": model,
            "elapsed_ms": round((time.monotonic() - t0) * 1000),
            "error": f"{type(e).__name__}: {str(e)[:300]}",
            "prompt": prompt,
            "raw_content": None,
            "parsed": None,
            "usage": None,
        })
        raise

    # Capture token usage before content parsing so calls whose JSON parsing
    # fails are still counted. The observer always gets it; the caller's list
    # is only appended when one was passed.
    usage_entry = None
    if response.usage is not None:
        usage_entry = {
            "model": getattr(response, "model", None) or model,
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        }
        if usage is not None:
            usage.append(usage_entry)

    content = response.choices[0].message.content

    if response_format == "json":
        try:
            result = parse_json_markdown(content, parser=json_repair.loads)
            parsed: Any = result if isinstance(result, dict) else {}
            parse_ok = isinstance(result, dict)
        except Exception:
            parsed = {}
            parse_ok = False
        await _emit_record({
            "case_id": _current_case.get(),
            "tag": tag or tier,
            "tier": tier,
            "model": model,
            "elapsed_ms": round((time.monotonic() - t0) * 1000),
            "error": None,
            "parse_ok": parse_ok,
            "prompt": prompt,
            "raw_content": content,
            "parsed": parsed,
            "usage": usage_entry,
        })
        return parsed

    await _emit_record({
        "case_id": _current_case.get(),
        "tag": tag or tier,
        "tier": tier,
        "model": model,
        "elapsed_ms": round((time.monotonic() - t0) * 1000),
        "error": None,
        "prompt": prompt,
        "raw_content": content,
        "parsed": None,
        "usage": usage_entry,
    })
    return content
