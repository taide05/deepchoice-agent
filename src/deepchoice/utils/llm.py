import asyncio
import hashlib
import json
import os
import random
import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Any

import json_repair
from langchain_core.utils.json import parse_json_markdown
from openai import APIConnectionError, AsyncOpenAI

from deepchoice.security.redaction import redact_text
from deepchoice.utils.call_diagnostics import exception_category, observe_output, output_failure, validate_diagnostic_profile
from deepchoice.utils.token_usage import cache_totals, provider_usage, trace_usage

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


def _content_metadata(value: Any, prefix: str) -> dict[str, Any]:
    """Return reproducible diagnostics without retaining model content."""

    if value is None:
        return {f"{prefix}_sha256": None, f"{prefix}_chars": 0}
    if isinstance(value, str):
        encoded = value
    else:
        try:
            encoded = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
        except (TypeError, ValueError):
            encoded = str(type(value).__name__)
    return {
        f"{prefix}_sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        f"{prefix}_chars": len(encoded),
    }


def _safe_error_metadata(exc: Exception) -> dict[str, Any]:
    status = getattr(exc, "status_code", None)
    if not isinstance(status, int) or isinstance(status, bool):
        status = None
    label = type(exc).__name__
    if status is not None:
        label = f"{label}: HTTP {status}"
    return {
        "error": label,
        "error_type": type(exc).__name__,
        "error_status": status,
    }


def _env(*names: str, default: str = "") -> str:
    for n in names:
        v = os.environ.get(n, "")
        if v:
            return v
    return default


# All new calls use the existing DeepSeek Flash deployment. Former Qwen
# credentials are deliberately not fallbacks: they belong to another provider.
TIERS = {
    "deepseek-flash": {
        "model": _env("DS_FLASH_MODEL", "FLASH_MODEL", default="deepseek-v4-flash"),
        "base": _env("DS_FLASH_BASE_URL", "FLASH_BASE_URL", "DEEPSEEK_BASE_URL", default=DEEPSEEK_BASE),
        "key": _env("DS_FLASH_API_KEY", "FLASH_API_KEY", "DEEPSEEK_API_KEY"),
        "extra_body": {"thinking": {"type": "disabled"}},
    },
}


def synthesis_extra_body() -> dict:
    """Resolve the synthesis option once when freezing a new run."""
    if os.environ.get("DEEPCHOICE_SYNTH_THINKING", "0") == "1":
        # Freeze the provider's effective effort instead of inheriting its default.
        return {"thinking": {"type": "enabled"}, "reasoning_effort": "high"}
    return {"thinking": {"type": "disabled"}}


def deepseek_extra_body(extra_body: dict | None = None) -> dict:
    """Apply native defaults and adapt the deprecated Qwen thinking keyword.

    The legacy call_model(model="qwen-flash") selector still falls back to
    DeepSeek, as other retired selectors do. It never creates a Qwen client.
    Durable historical manifests are rejected by compatibility before dispatch.
    """
    extra = {**TIERS["deepseek-flash"]["extra_body"], **(extra_body or {})}
    if "enable_thinking" in extra:
        enabled = extra.pop("enable_thinking")
        if "thinking" not in (extra_body or {}):
            extra["thinking"] = {"type": "enabled" if enabled else "disabled"}
    return extra

_MAX_RETRIES = 2
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
MAX_OUTPUT_TOKENS = 4096


def max_output_tokens_for(tag: str) -> int:
    """One source of truth for dispatch, reservation, and manifest identity."""
    if tag == "conflict_scan":
        return 512
    if tag == "source_scope_selector":
        return 1024
    return MAX_OUTPUT_TOKENS


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

    summary = {
        "agent": agent_name,
        "model": model,
        "calls": len(usage),
        "prompt_tokens": sum(u.get("prompt_tokens", 0) for u in usage),
        "completion_tokens": sum(u.get("completion_tokens", 0) for u in usage),
        "total_tokens": sum(u.get("total_tokens", 0) for u in usage),
    }
    cache = cache_totals(usage, input_field="prompt_tokens")
    if cache["cache_usage_known_calls"]:
        summary.update(cache)
    return summary


async def call_model(
    prompt: list[dict],
    model: str = "deepseek-flash",
    response_format: str | None = None,
    timeout: float = 120.0,
    usage: list | None = None,
    tag: str = "",
    extra_body: dict | None = None,
    seed: int | None = None,
    diagnostics: list | None = None,
    diagnostic_profile: str | None = None,
) -> dict | str:
    # Lazy to keep the historic agent/manifest import graph acyclic.
    from deepchoice.observability import (
        ExternalCallKind,
        TraceStatus,
        current_trace_recorder,
    )
    from deepchoice.runtime.context import classify_cancelled_trace_status

    validate_diagnostic_profile(tag, diagnostic_profile)
    tier = model if model in TIERS else "deepseek-flash"
    cfg = TIERS[tier]
    model = cfg["model"]
    if isinstance(prompt, list):
        prompt = list(prompt)
    client = _get_client(timeout=timeout, tier=tier, max_retries=0)
    output_limit = max_output_tokens_for(tag)
    kwargs = {
        "model": model,
        "messages": prompt,
        "temperature": 0,
        "max_tokens": output_limit,
    }
    if seed is not None:
        kwargs["seed"] = seed
    kwargs["extra_body"] = deepseek_extra_body(extra_body)
    if response_format == "json":
        kwargs["response_format"] = {"type": "json_object"}
        # DeepSeek JSON mode requires the prompt to mention JSON as well.
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
            from deepchoice.budget import (
                BudgetAmount,
                BudgetError,
                BudgetExceededError,
                BudgetResource,
                reserve_call,
                settle_call,
                unknown_call,
            )

            trace, node_attempt_id = current_trace_recorder()
            trace_call = None
            if trace is not None:
                trace_call = await trace.start_external_call(
                    node_attempt_id=node_attempt_id,
                    kind=ExternalCallKind.LLM,
                    provider=tier,
                    operation="chat.completions.create",
                    request_summary={
                        "model": model,
                        "retry_no": attempt,
                        "response_format": response_format or "text",
                    },
                )
            sent_messages = kwargs["messages"]
            message_bytes = len(
                json.dumps(
                    sent_messages,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    default=str,
                ).encode("utf-8")
            )
            reservations = ()
            try:
                reservations = await reserve_call(
                    (
                        BudgetAmount(resource=BudgetResource.LLM_CALLS, amount=1),
                        BudgetAmount(
                            resource=BudgetResource.TOTAL_TOKENS,
                            amount=message_bytes + output_limit,
                        ),
                    ),
                    call_id=trace_call.call_id if trace_call is not None else None,
                    summary={"operation": "llm", "retry_no": attempt},
                )
            except BudgetError as budget_exc:
                if trace is not None:
                    await trace.finish_external_call(
                        trace_call,
                        status=TraceStatus.FAILED,
                        result_summary={
                            "failure_category": (
                                "budget_exceeded"
                                if isinstance(budget_exc, BudgetExceededError)
                                else "budget_gate_failed"
                            ),
                            "retry_no": attempt,
                        },
                    )
                raise
            attempt_started = time.monotonic()
            try:
                response = await client.chat.completions.create(**kwargs)
            except asyncio.CancelledError:
                await unknown_call(
                    reservations,
                    known_actuals={BudgetResource.LLM_CALLS: 1},
                )
                if trace is not None:
                    cancelled_status = classify_cancelled_trace_status()
                    await trace.finish_external_call(
                        trace_call,
                        status=cancelled_status,
                        result_summary={"retry_no": attempt, "failure_category":
                                        "run_timeout" if cancelled_status == TraceStatus.TIMED_OUT else "cancelled"},
                    )
                raise
            except Exception as e:
                await unknown_call(
                    reservations,
                    known_actuals={BudgetResource.LLM_CALLS: 1},
                )
                status = getattr(e, "status_code", None)
                retryable = isinstance(e, APIConnectionError) or status in _RETRYABLE_STATUSES
                if trace is not None:
                    await trace.finish_external_call(
                        trace_call,
                        status=(
                            TraceStatus.TIMED_OUT
                            if exception_category(e) == "provider_timeout"
                            else TraceStatus.FAILED
                        ),
                        result_summary={
                            "elapsed_ms": round(
                                (time.monotonic() - attempt_started) * 1000
                            ),
                            "error_type": type(e).__name__,
                            "error_status": status if isinstance(status, int) else None,
                            "retry_no": attempt,
                            "retryable": retryable,
                            "failure_category": exception_category(e),
                        },
                    )
                if not retryable or attempt >= _MAX_RETRIES:
                    raise
                delay = (2 ** attempt) * 5.0 * (0.5 + random.random())
                await _retry_sleep(delay)
            else:
                call_usage = trace_usage(response.usage)
                await settle_call(
                    reservations,
                    {
                        BudgetResource.LLM_CALLS: 1,
                        BudgetResource.TOTAL_TOKENS: (
                            response.usage.total_tokens
                            if response.usage is not None
                            else None
                        ),
                    },
                )
                content = response.choices[0].message.content
                parsed, parse_ok = content, None
                repair_attempts = 0
                if response_format == "json":
                    def repair_parser(value):
                        nonlocal repair_attempts
                        repair_attempts += 1
                        return json_repair.loads(value)

                    try:
                        result = parse_json_markdown(content, parser=repair_parser)
                        parsed = result if isinstance(result, dict) else {}
                        parse_ok = isinstance(result, dict)
                    except Exception:
                        parsed, parse_ok = {}, False
                observation = observe_output(
                    response.choices[0], json_requested=response_format == "json",
                    content=content, parsed=parsed, parse_ok=parse_ok,
                    repair_attempts=repair_attempts, tag=tag, profile=diagnostic_profile,
                )
                if trace is not None:
                    await trace.finish_external_call(
                        trace_call,
                        status=TraceStatus.SUCCEEDED,
                        result_summary={
                            "elapsed_ms": round(
                                (time.monotonic() - attempt_started) * 1000
                            ),
                            "retry_no": attempt,
                            "diagnostics": observation,
                            "failure_category": output_failure(observation),
                        },
                        usage_summary=call_usage,
                    )
                break
    except Exception as e:
        record = {
            "case_id": _current_case.get(),
            "tag": tag or tier,
            "tier": tier,
            "model": model,
            "elapsed_ms": round((time.monotonic() - t0) * 1000),
            "usage": None,
            **_safe_error_metadata(e),
            "failure_category": exception_category(e),
            **_content_metadata(prompt, "prompt"),
            **_content_metadata(None, "response"),
        }
        if diagnostics is not None:
            diagnostics.append({key: redact_text(value) if key in {"case_id", "tag", "tier", "model"} else value for key, value in record.items()})
        await _emit_record({key: redact_text(value) if key in {"case_id", "tag", "tier", "model"} else value for key, value in record.items()})
        raise

    # Capture token usage before content parsing so calls whose JSON parsing
    # fails are still counted. The observer always gets it; the caller's list
    # is only appended when one was passed.
    usage_entry = None
    if response.usage is not None:
        usage_entry = {
            "model": getattr(response, "model", None) or model,
            **provider_usage(response.usage),
        }
        if usage is not None:
            usage.append(usage_entry)

    content = response.choices[0].message.content

    if response_format == "json":
        record = {
            "case_id": _current_case.get(),
            "tag": tag or tier,
            "tier": tier,
            "model": model,
            "elapsed_ms": round((time.monotonic() - t0) * 1000),
            "error": None,
            "error_type": None,
            "error_status": None,
            "parse_ok": parse_ok,
            "parsed_type": type(parsed).__name__,
            "usage": usage_entry,
            "diagnostics": observation,
            "failure_category": output_failure(observation),
            **_content_metadata(prompt, "prompt"),
            **_content_metadata(content, "response"),
        }
        if diagnostics is not None:
            diagnostics.append({key: redact_text(value) if key in {"case_id", "tag", "tier", "model"} else value for key, value in record.items()})
        await _emit_record({key: redact_text(value) if key in {"case_id", "tag", "tier", "model"} else value for key, value in record.items()})
        return parsed

    record = {
        "case_id": _current_case.get(),
        "tag": tag or tier,
        "tier": tier,
        "model": model,
        "elapsed_ms": round((time.monotonic() - t0) * 1000),
        "error": None,
        "error_type": None,
        "error_status": None,
        "parsed_type": None,
        "usage": usage_entry,
        "diagnostics": observation,
        "failure_category": output_failure(observation),
        **_content_metadata(prompt, "prompt"),
        **_content_metadata(content, "response"),
    }
    if diagnostics is not None:
        diagnostics.append({key: redact_text(value) if key in {"case_id", "tag", "tier", "model"} else value for key, value in record.items()})
    await _emit_record({key: redact_text(value) if key in {"case_id", "tag", "tier", "model"} else value for key, value in record.items()})
    return content
