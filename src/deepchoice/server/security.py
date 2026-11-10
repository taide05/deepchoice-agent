"""Optional API-key authentication and in-memory rate limiting.

Both controls are environment-gated and disabled by default, so the local
single-user deployment keeps working unchanged. They are meant for exposing the
API to a trusted demo audience:

- ``DEEPCHOICE_API_KEY``: when set, every non-public request must carry
  ``X-API-Key: <value>``.
- ``DEEPCHOICE_RATE_LIMIT_PER_MINUTE``: when > 0, mutating requests
  (POST/PUT/PATCH/DELETE) are limited per client (per API key when supplied,
  otherwise per client IP).
- Public paths (``/health``, docs) stay exempt.

The limiter is in-process only; for a multi-worker deployment use a shared
store (Redis) instead.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import threading
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

PUBLIC_PATHS = frozenset({
    "/health",
    "/docs",
    "/docs/oauth2-redirect",
    "/openapi.json",
    "/redoc",
})
MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
WINDOW_SECONDS = 60.0


def _read_positive_int(value: str, default: int = 0) -> int:
    try:
        parsed = int(str(value).strip() or default)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


class ApiSecurityMiddleware(BaseHTTPMiddleware):
    """API-key gate + in-memory per-client rate limiting for mutating requests."""

    def __init__(
        self,
        app,
        api_key: str | None = None,
        rate_limit_per_minute: int | None = None,
        public_paths: set[str] | frozenset[str] | None = None,
    ) -> None:
        super().__init__(app)
        self.api_key = (api_key if api_key is not None else os.environ.get("DEEPCHOICE_API_KEY", "")).strip()
        limit = rate_limit_per_minute if rate_limit_per_minute is not None else os.environ.get(
            "DEEPCHOICE_RATE_LIMIT_PER_MINUTE", "0")
        self.rate_limit_per_minute = _read_positive_int(limit)
        self.public_paths = frozenset(public_paths if public_paths is not None else PUBLIC_PATHS)
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    # -- helpers -----------------------------------------------------
    def _is_public(self, path: str) -> bool:
        return path in self.public_paths or path.startswith(("/docs", "/redoc"))

    @staticmethod
    def _client_bucket(request: Request) -> str:
        supplied = request.headers.get("x-api-key", "")
        if supplied:
            digest = hashlib.sha256(("deepchoice-rate:" + supplied).encode("utf-8")).hexdigest()
            return "key:" + digest[:16]
        host = request.client.host if request.client is not None else "unknown"
        return "ip:" + host

    def _consume(self, bucket: str) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[bucket]
            while hits and now - hits[0] > WINDOW_SECONDS:
                hits.popleft()
            if len(hits) >= self.rate_limit_per_minute:
                return False
            hits.append(now)
            return True

    # -- middleware --------------------------------------------------
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not self._is_public(path):
            if self.api_key:
                supplied = request.headers.get("x-api-key", "")
                if not hmac.compare_digest(supplied, self.api_key):
                    return JSONResponse({"detail": "unauthorized"}, status_code=401)
            if (
                self.rate_limit_per_minute > 0
                and request.method in MUTATING_METHODS
                and not self._consume(self._client_bucket(request))
            ):
                return JSONResponse({"detail": "rate limit exceeded"}, status_code=429)
        return await call_next(request)
