"""V5 observer adapter for bounded post-response decoding failures.

The frozen v4 child remains byte-identical.  This adapter changes only the
observer-side normalization used by a new execution identity; product sources,
network policy, and the historical child implementation remain unchanged.
"""
from __future__ import annotations

from pathlib import Path
import sys

import httpx


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import o1_pr2b_child as _v4  # noqa: E402


def _bounded_response_failure(exc: BaseException, phase: str) -> BaseException:
    """Normalize only known response-consumption failures after dispatch."""

    if (
        not isinstance(exc, (httpx.DecodingError, httpx.StreamError))
        or phase not in {"http_dispatch", "response_received"}
    ):
        return exc
    from deepchoice.security.urls import SafeFetchFailure, UnsafeUrlError

    return UnsafeUrlError(
        "Response could not be consumed safely",
        failure=SafeFetchFailure.RESPONSE_REJECTED,
    )


def main() -> int:
    _v4._bounded_stream_failure = _bounded_response_failure
    return _v4.main()


if __name__ == "__main__":
    raise SystemExit(main())
