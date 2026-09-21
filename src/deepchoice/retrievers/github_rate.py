"""Compatibility entry points for the shared GitHub request gate."""
import asyncio
from contextlib import asynccontextmanager

import httpx

from ..outbound import throttle

_MAX_IN_FLIGHT = 2
_MAX_RETRIES = 2
_RETRYABLE_RESPONSE_ERRORS = (httpx.RemoteProtocolError, httpx.ReadError)


def interval_s() -> float:
    return throttle.github_interval()


@asynccontextmanager
async def request_slot():
    gate = throttle.gate_for("github")
    gate.interval = interval_s
    async with gate.slot():
        yield


def retry_delay(headers) -> float:
    # Server deadlines are never shortened; the local queue has its own bound.
    return throttle.retry_after(headers, default=60.0, github=True)


async def get_with_throttle(client, url, *, params=None, headers=None,
                            max_retries: int = _MAX_RETRIES):
    gate = throttle.gate_for("github")
    for attempt in range(max_retries + 1):
        try:
            async with request_slot():
                async with asyncio.timeout(30.0):
                    response = await client.get(
                        url, params=params, headers=headers)
                limited = throttle.observe(
                    "github", response, gate,
                    fallback=retry_delay(response.headers),
                )
        except _RETRYABLE_RESPONSE_ERRORS:
            # GitHub search is an idempotent GET. A peer or relay can close a
            # valid connection before the response is complete under bursty
            # concurrency; retry only that narrow response-interruption class.
            # Re-entering request_slot preserves the shared provider pacing and
            # concurrency limit. The final exception remains visible upstream.
            if attempt == max_retries:
                raise
            continue
        if not limited or attempt == max_retries:
            return response


def _reset_for_tests() -> None:
    throttle.reset_for_tests()
