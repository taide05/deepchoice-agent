"""Inbound request-size and text-safety boundaries."""
from __future__ import annotations

import json
import unicodedata
from collections.abc import Awaitable, Callable
from typing import Any

DEFAULT_MAX_REQUEST_BODY_BYTES = 128 * 1024
MAX_RESEARCH_TEXT_CHARS = 32 * 1024

_BIDI_CONTROL_CHARACTERS = frozenset(
    chr(value)
    for value in (
        0x200E,
        0x200F,
        0x202A,
        0x202B,
        0x202C,
        0x202D,
        0x202E,
        0x2066,
        0x2067,
        0x2068,
        0x2069,
        0xFEFF,
    )
)


def contains_dangerous_control_characters(value: str) -> bool:
    return any(
        (unicodedata.category(char) == "Cc" and char not in "\t\n\r")
        or char in _BIDI_CONTROL_CHARACTERS
        for char in value
    )


def validate_safe_text(value: str) -> str:
    if contains_dangerous_control_characters(value):
        raise ValueError("text contains prohibited control characters")
    return value


class RequestBodyLimitMiddleware:
    """Pure ASGI middleware enforcing declared and streamed body limits."""

    def __init__(self, app: Callable[..., Awaitable[Any]], max_bytes: int = DEFAULT_MAX_REQUEST_BODY_BYTES):
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        raw_headers = scope.get("headers", ())
        content_lengths = [
            value
            for key, value in raw_headers
            if key.lower() == b"content-length"
        ]
        if len(set(content_lengths)) > 1:
            await self._reject(
                send,
                400,
                "REQUEST_CONTENT_LENGTH_INVALID",
                "Conflicting Content-Length headers",
            )
            return
        declared = content_lengths[0] if content_lengths else None
        if declared is not None:
            if not declared.isdigit():
                await self._reject(send, 400, "REQUEST_CONTENT_LENGTH_INVALID", "Invalid Content-Length header")
                return
            declared_size = int(declared)
            if declared_size > self.max_bytes:
                await self._reject_too_large(send)
                return

        method = str(scope.get("method", "")).upper()
        has_transfer_encoding = any(
            key.lower() == b"transfer-encoding" for key, _value in raw_headers
        )
        if method in {"GET", "HEAD", "OPTIONS"} and declared is None and not has_transfer_encoding:
            # A bodyless streaming request must retain its original receive
            # channel so disconnect notifications continue to work for SSE.
            await self.app(scope, receive, send)
            return

        consumed = 0
        buffered: list[dict] = []
        while True:
            message = await receive()
            buffered.append(message)
            if message.get("type") == "http.disconnect":
                return
            if message.get("type") != "http.request":
                continue
            consumed += len(message.get("body", b""))
            if consumed > self.max_bytes:
                await self._reject_too_large(send)
                return
            if not message.get("more_body", False):
                break

        index = 0

        async def replay_receive() -> dict:
            nonlocal index
            if index < len(buffered):
                message = buffered[index]
                index += 1
                return message
            return {"type": "http.disconnect"}

        await self.app(scope, replay_receive, send)

    async def _reject_too_large(self, send: Callable) -> None:
        await self._reject(
            send,
            413,
            "REQUEST_BODY_TOO_LARGE",
            f"Request body exceeds {self.max_bytes} bytes",
        )

    @staticmethod
    async def _reject(send: Callable, status: int, code: str, message: str) -> None:
        body = json.dumps(
            {
                "schema_version": 1,
                "detail": message,
                "error": {
                    "category": "validation",
                    "code": code,
                    "message": message,
                    "retryable": False,
                },
            },
            separators=(",", ":"),
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


__all__ = [
    "DEFAULT_MAX_REQUEST_BODY_BYTES",
    "MAX_RESEARCH_TEXT_CHARS",
    "RequestBodyLimitMiddleware",
    "contains_dangerous_control_characters",
    "validate_safe_text",
]
