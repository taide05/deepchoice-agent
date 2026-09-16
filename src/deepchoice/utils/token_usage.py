"""Allowlisted provider usage; context-cache metadata never discounts budgets."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


TOKEN_FIELDS = ("input_tokens", "output_tokens", "total_tokens")
CACHE_FIELDS = ("prompt_cache_hit_tokens", "prompt_cache_miss_tokens")


def _get(value: Any, name: str) -> Any:
    return value.get(name) if isinstance(value, Mapping) else getattr(value, name, None)


def _count(value: Any) -> bool:
    return type(value) is int and value >= 0


def _has(value: Any, name: str) -> bool:
    return name in value if isinstance(value, Mapping) else hasattr(value, name)


def cache_usage(value: Any, *, input_field: str = "prompt_tokens") -> dict[str, int]:
    """Accept a consistent native pair or the documented cached_tokens alias.

    Missing/invalid native fields are unknown, not zero. An explicitly supplied
    but invalid native pair must not be rescued by another representation.
    The alias implies miss = input - cached only when native fields are absent.
    """
    prompt = _get(value, input_field)
    hit, miss = (_get(value, field) for field in CACHE_FIELDS)
    details = _get(value, "prompt_tokens_details")
    cached = _get(details, "cached_tokens")
    if not any(_has(value, field) for field in CACHE_FIELDS):
        if not (_count(prompt) and _count(cached)):
            return {}
        hit, miss = cached, prompt - cached
    if not all(_count(number) for number in (prompt, hit, miss)):
        return {}
    if hit + miss != prompt or (cached is not None and (not _count(cached) or cached != hit)):
        return {}
    return dict(zip(CACHE_FIELDS, (hit, miss)))


def provider_usage(value: Any) -> dict[str, int]:
    """Normalize SDK objects/dicts without retaining arbitrary provider fields."""
    fields = ("prompt_tokens", "completion_tokens", "total_tokens")
    return {
        **{field: count for field in fields if _count(count := _get(value, field))},
        **cache_usage(value),
    }


def trace_usage(value: Any) -> dict[str, int]:
    normalized = provider_usage(value)
    names = dict(zip(("prompt_tokens", "completion_tokens", "total_tokens"), TOKEN_FIELDS))
    return {names.get(field, field): count for field, count in normalized.items()}


def public_usage(value: Any) -> dict[str, int]:
    """Revalidate persisted usage before projecting public numeric fields."""
    return {
        **{field: count for field in TOKEN_FIELDS if _count(count := _get(value, field))},
        **cache_usage(value, input_field="input_tokens"),
    }


def cache_totals(usages: list[dict], *, input_field: str = "input_tokens") -> dict:
    pairs = [cache_usage(usage, input_field=input_field) for usage in usages]
    known = [pair for pair in pairs if pair]
    complete = bool(usages) and len(known) == len(usages)
    totals = {
        field: sum(pair[field] for pair in known) if known else None
        for field in CACHE_FIELDS
    }
    prompt = sum(usage[input_field] for usage in usages) if complete else 0
    return {
        **totals,
        "cache_usage_known_calls": len(known),
        "cache_usage_complete": complete,
        "prompt_cache_hit_ratio": totals[CACHE_FIELDS[0]] / prompt if complete and prompt else None,
    }
