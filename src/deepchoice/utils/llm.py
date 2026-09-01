import asyncio
import os
import random

import json_repair
from openai import AsyncOpenAI
from langchain_core.utils.json import parse_json_markdown


DEEPSEEK_BASE = "https://api.deepseek.com/v1"
DASHSCOPE_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def _env(*names: str, default: str = "") -> str:
    for n in names:
        v = os.environ.get(n, "")
        if v:
            return v
    return default


# Tier -> provider config (user decision 2026-09-01, after the 10-case run:
# qwen3.8-flash is too slow/weak for the hot flash path -> flash goes back to
# deepseek-v4-flash; the heavy 'pro' tier (report synthesis + conflict
# re-arbitration) stays on qwen3.8-flash).
TIERS = {
    "flash": {
        "model": _env("FLASH_MODEL", default="deepseek-v4-flash"),
        "base": _env("FLASH_BASE_URL", "DEEPSEEK_BASE_URL", default=DEEPSEEK_BASE),
        "key": _env("FLASH_API_KEY", "DEEPSEEK_API_KEY"),
    },
    "pro": {
        "model": _env("PRO_MODEL", default="qwen3.8-flash"),
        "base": _env("PRO_BASE_URL", "LLM_BASE_URL", default=DASHSCOPE_BASE),
        "key": _env("PRO_API_KEY", "LLM_API_KEY"),
        # Qwen3* thinks by default — this doubles latency. Turn it off for
        # deterministic JSON synthesis/re-arbitration (the timeout root cause).
        "extra_body": {"enable_thinking": False},
    },
}

_MAX_RETRIES = 2
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


async def _retry_sleep(delay: float) -> None:
    await asyncio.sleep(delay)


def _get_client(timeout: float = 120.0, tier: str = "flash") -> AsyncOpenAI:
    cfg = TIERS.get(tier, TIERS["flash"])
    return AsyncOpenAI(api_key=cfg["key"], base_url=cfg["base"], timeout=timeout)


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
    model: str = "flash",
    response_format: str | None = None,
    timeout: float = 120.0,
    usage: list | None = None,
) -> dict | str:
    tier = model if model in TIERS else "flash"
    cfg = TIERS[tier]
    model = cfg["model"]
    if isinstance(prompt, list):
        prompt = list(prompt)
    client = _get_client(timeout=timeout, tier=tier)
    kwargs = {"model": model, "messages": prompt, "temperature": 0}
    extra = cfg.get("extra_body")
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

    response = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = await client.chat.completions.create(**kwargs)
            break
        except Exception as e:
            status = getattr(e, "status_code", None)
            if status not in _RETRYABLE_STATUSES or attempt >= _MAX_RETRIES:
                raise
            delay = (2 ** attempt) * 5.0 * (0.5 + random.random())
            await _retry_sleep(delay)

    # Capture token usage before content parsing so calls whose JSON parsing
    # fails are still counted.
    if usage is not None and response.usage is not None:
        usage.append({
            "model": getattr(response, "model", None) or model,
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        })

    content = response.choices[0].message.content

    if response_format == "json":
        try:
            result = parse_json_markdown(content, parser=json_repair.loads)
            if isinstance(result, dict):
                return result
            return {}
        except Exception:
            return {}
    return content
