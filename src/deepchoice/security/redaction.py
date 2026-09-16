"""Central redaction helpers for logs, diagnostics, and error summaries."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit, urlunsplit


REDACTED = "[REDACTED]"

_SENSITIVE_KEY = re.compile(
    r"(?i)(?:^|[_-])(?:api[_-]?key|access[_-]?token|auth[_-]?token|authorization|"
    r"client[_-]?secret|cookie|credential|password|passwd|private[_-]?key|"
    r"refresh[_-]?token|secret|session[_-]?token|fwd[_-]?key)(?:$|[_-])"
)
_SENSITIVE_CONTAINER_KEYS = frozenset(
    {
        "body",
        "content",
        "exception",
        "headers",
        "messages",
        "prompt",
        "query",
        "raw_content",
        "raw_response",
        "request_body",
        "response_body",
        "traceback",
        "x_fwd_key",
    }
)
_AUTH_RE = re.compile(r"(?i)\b(?:authorization\s*[:=]\s*)?(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]+")
_SENSITIVE_HEADER_RE = re.compile(
    r"(?im)\b(authorization|proxy-authorization|cookie|set-cookie|x-fwd-key)"
    r"(\s*:\s*)[^\r\n]+"
)
_ASSIGNMENT_RE = re.compile(
    r"(?i)\b([a-z][a-z0-9_-]{0,80})(\s*[:=]\s*)([^\s,;]+)"
)
_KNOWN_SECRET_RE = re.compile(
    r"(?i)\b(?:sk|pk|ghp|github_pat|xox[abprs]|AIza)[_-][A-Za-z0-9._-]{12,}\b"
)
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9_+/=-]{32,}(?![A-Za-z0-9])")
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.IGNORECASE)
_HEX_RE = re.compile(r"^[0-9a-f]{32,128}$", re.IGNORECASE)


def _entropy(token: str) -> float:
    counts = Counter(token)
    length = len(token)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def _redact_url(match: re.Match[str]) -> str:
    raw = match.group(0)
    trailing = ""
    while raw and raw[-1] in ".,;)]}":
        trailing = raw[-1] + trailing
        raw = raw[:-1]
    try:
        parsed = urlsplit(raw)
        host = parsed.hostname
        if not host:
            return "[REDACTED_URL]" + trailing
        port = parsed.port
        netloc = f"[{host}]" if ":" in host else host
        if port is not None:
            netloc += f":{port}"
        path = "/" if parsed.path in {"", "/"} else "/[REDACTED_PATH]"
        clean = urlunsplit(
            (parsed.scheme.lower(), netloc, path, "", "")
        )
        return clean + trailing
    except (TypeError, ValueError):
        return "[REDACTED_URL]" + trailing


def _redact_high_entropy(match: re.Match[str]) -> str:
    token = match.group(0)
    if _UUID_RE.fullmatch(token) or _HEX_RE.fullmatch(token):
        return token
    has_letter = any(char.isalpha() for char in token)
    has_digit = any(char.isdigit() for char in token)
    if has_letter and has_digit and _entropy(token) >= 4.0:
        return REDACTED
    return token


def _redact_assignment(match: re.Match[str]) -> str:
    key = match.group(1)
    normalized = _normalized_key(key)
    if normalized in _SENSITIVE_CONTAINER_KEYS or _SENSITIVE_KEY.search(
        f"_{normalized}_"
    ):
        return f"{key}{match.group(2)}{REDACTED}"
    return match.group(0)


def redact_text(value: object, *, max_length: int = 1000) -> str:
    """Return bounded text with common secret carriers removed."""

    text = str(value)
    text = _URL_RE.sub(_redact_url, text)
    text = _SENSITIVE_HEADER_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}{REDACTED}", text
    )
    text = _AUTH_RE.sub(REDACTED, text)
    text = _ASSIGNMENT_RE.sub(_redact_assignment, text)
    text = _KNOWN_SECRET_RE.sub(REDACTED, text)
    text = _JWT_RE.sub(REDACTED, text)
    text = _TOKEN_RE.sub(_redact_high_entropy, text)
    if len(text) > max_length:
        return text[:max_length] + "…[TRUNCATED]"
    return text


def _normalized_key(key: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_")


def redact_value(value: Any, *, max_depth: int = 6, max_items: int = 100) -> Any:
    """Recursively redact structured diagnostic values without mutating input."""

    def walk(item: Any, depth: int) -> Any:
        if depth > max_depth:
            return "[TRUNCATED_DEPTH]"
        if isinstance(item, Mapping):
            result: dict[str, Any] = {}
            for index, (key, nested) in enumerate(item.items()):
                if index >= max_items:
                    result["__truncated__"] = True
                    break
                name = str(key)
                normalized = _normalized_key(name)
                result[name] = (
                    REDACTED
                    if normalized in _SENSITIVE_CONTAINER_KEYS
                    or _SENSITIVE_KEY.search(f"_{normalized}_")
                    else walk(nested, depth + 1)
                )
            return result
        if isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            result = [walk(nested, depth + 1) for nested in item[:max_items]]
            if len(item) > max_items:
                result.append("[TRUNCATED_ITEMS]")
            return result
        if isinstance(item, str):
            return redact_text(item)
        if item is None or isinstance(item, (bool, int, float)):
            return item
        return redact_text(item)

    return walk(value, 0)


__all__ = ["REDACTED", "redact_text", "redact_value"]
