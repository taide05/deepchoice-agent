"""Deeply immutable, public-safe JSON object summaries."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, PrivateAttr, model_serializer


_PROHIBITED_EXACT_KEYS = frozenset(
    {
        "body",
        "checkpoint",
        "content",
        "exception",
        "header",
        "headers",
        "prompt",
        "query",
        "request",
        "response",
        "traceback",
        "url",
    }
)
_PROHIBITED_SENSITIVE_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "auth_token",
        "authorization",
        "check_point_id",
        "checkpoint_id",
        "client_secret",
        "cookie",
        "cookies",
        "credential",
        "credentials",
        "id_token",
        "password",
        "passwd",
        "private_key",
        "raw_exception",
        "refresh_token",
        "secret",
        "session_token",
    }
)


def _normalize_key(key: str) -> str:
    separated = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", key)
    separated = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", separated)
    return re.sub(r"[^a-z0-9]+", "_", separated.lower()).strip("_")


def _validate_keys(value: Any) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise ValueError("summary keys must be strings")
            normalized = _normalize_key(key)
            if normalized in _PROHIBITED_EXACT_KEYS or any(
                normalized == sensitive or normalized.endswith(f"_{sensitive}")
                for sensitive in _PROHIBITED_SENSITIVE_KEYS
            ):
                raise ValueError(f"summary field {key!r} is prohibited")
            _validate_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            _validate_keys(nested)


class SafeJsonObject(BaseModel):
    """Canonical JSON stored as a string so nested containers cannot mutate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    _canonical_json: str = PrivateAttr(default="{}")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | "SafeJsonObject") -> "SafeJsonObject":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise ValueError("summary must be a JSON object")
        mapping = dict(value)
        _validate_keys(mapping)
        try:
            canonical = json.dumps(
                mapping,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            decoded = json.loads(canonical)
        except (TypeError, ValueError):
            raise ValueError("summary must contain finite JSON values") from None
        _validate_keys(decoded)
        instance = cls()
        object.__setattr__(instance, "_canonical_json", canonical)
        return instance

    def to_dict(self) -> dict[str, Any]:
        """Return a detached mutable copy, never the stored representation."""

        return json.loads(self._canonical_json)

    @model_serializer
    def _serialize(self) -> dict[str, Any]:
        return self.to_dict()


def coerce_safe_json_object(value: Any) -> SafeJsonObject:
    return SafeJsonObject.from_mapping(value)


__all__ = ["SafeJsonObject", "coerce_safe_json_object"]
