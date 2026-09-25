"""O1-PR2B profile runner with fail-closed, operation-aware telemetry."""
from __future__ import annotations

import argparse
import asyncio
from contextvars import ContextVar
from datetime import UTC, datetime
from functools import wraps
import json
import os
import re
from urllib.parse import urlsplit
from pathlib import Path
import ssl
import sys
from threading import Lock
import time

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_FIELDS = frozenset({
    "run_id", "started_at", "ended_at", "duration_ms", "rss_bytes",
    "available_bytes", "cold", "model_initialized", "status", "failure",
    "error_type", "status_code", "certificate_required", "hostname_check_enabled",
    "hostname_matches", "reason", "source", "method", "operation",
    "instance_nonce",
})
_EVENTS = frozenset({
    "embedding_first_start", "embedding_first_end", "proxy_connect_success",
    "proxy_tls_success", "safe_fetch_success", "safe_fetch_failure",
    "service_started", "service_stop_requested", "service_stopped", "child_failure",
    "external_http_response", "external_http_failure", "telemetry_ready",
    "asyncio_runner_returned",
})
_ERROR_TYPES = frozenset({
    "CancelledError", "UnsafeUrlError", "TimeoutError", "ConnectTimeout",
    "ReadTimeout", "WriteTimeout", "PoolTimeout", "ConnectError", "ReadError",
    "WriteError", "RemoteProtocolError", "ProviderRateLimitError",
    "ProviderAdmissionError", "BudgetError", "BudgetExceededError",
    "BudgetInsufficientEvidenceError", "StaleBudgetAuthorityError",
    "BudgetPersistenceError", "BudgetExecutionDeferredError", "ValueError",
    "TypeError", "RuntimeError", "OSError", "MemoryError", "ImportError",
    "ModuleNotFoundError", "PermissionError", "FileNotFoundError",
    "TransportError",
})

_SAFE_FETCH_FAILURES = frozenset({
    "safety_rejected", "route_unavailable", "route_unsupported",
    "dns_uncertain", "timeout", "response_rejected",
})



_HTTP_OPERATIONS = frozenset({
    "tavily_static_probe", "tavily_business", "llm", "github", "arxiv",
    "community", "official", "self_forward", "other", "safe_fetch_public",
    "safe_fetch_official", "citation_safe_fetch_official",
})

_SAFE_FETCH_SOURCE: ContextVar[str | None] = ContextVar(
    "o1_pr2b_safe_fetch_source", default=None
)
_CITATION_FETCH: ContextVar[bool] = ContextVar(
    "o1_pr2b_citation_fetch", default=False
)


def _safe_fetch_operation(source: str) -> str:
    if _CITATION_FETCH.get() and source == "official":
        return "citation_safe_fetch_official"
    if source == "official":
        return "safe_fetch_official"
    return "safe_fetch_public"


def _endpoint_identity(value: str | None) -> tuple[str, str, int, str, str] | None:
    if not value:
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.scheme.lower() not in {"http", "https"}
                or parsed.hostname is None
                or parsed.username is not None
                or parsed.password is not None):
            return None
        hostname = parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    except (UnicodeError, ValueError):
        return None
    return (parsed.scheme.lower(), hostname, port, parsed.path or "/", parsed.query)


def _external_operation(
    request: httpx.Request,
    model_host: str | None,
    forward_endpoint: tuple[str, str, int, str, str] | None = None,
) -> str:
    """Classify without retaining a URL; the static-probe exception is exact."""

    method = request.method.upper()
    scheme = request.url.scheme.lower()
    host = (request.url.host or "").lower()
    port = request.url.port
    path = request.url.path
    query = request.url.query
    if isinstance(query, bytes):
        query = query.decode("ascii", errors="ignore")
    if (
        method == "HEAD"
        and scheme == "https"
        and host == "api.tavily.com"
        and port in {None, 443}
        and path == "/search"
        and not query
    ):
        return "tavily_static_probe"
    if host == "api.tavily.com":
        return "tavily_business"
    if model_host and host == model_host.lower():
        return "llm"
    if method == "POST" and forward_endpoint is not None:
        request_endpoint = _endpoint_identity(str(request.url))
        if request_endpoint == forward_endpoint:
            return "self_forward"
    return {
        "api.github.com": "github",
        "export.arxiv.org": "arxiv",
        "api.stackexchange.com": "community",
        "pypi.org": "official",
    }.get(host, "other")


def _observed_operation(
    request: httpx.Request,
    model_host: str | None,
    forward_endpoint: tuple[str, str, int, str, str] | None = None,
) -> str:
    """Keep dynamic safe-fetch traffic distinct without retaining its URL."""

    safe_fetch_source = _SAFE_FETCH_SOURCE.get()
    if safe_fetch_source in {
        "safe_fetch_official", "safe_fetch_public",
        "citation_safe_fetch_official",
    }:
        return safe_fetch_source
    return _external_operation(request, model_host, forward_endpoint)


def _observed_source(operation: str) -> str:
    if operation == "safe_fetch_official":
        return "official"
    if operation == "citation_safe_fetch_official":
        return "citation"
    if operation == "safe_fetch_public":
        return "safe_fetch"
    if operation.startswith("tavily_"):
        return "tavily"
    if operation == "self_forward":
        return "forward"
    return operation


def _error_type(exc: BaseException) -> str:
    name = type(exc).__name__
    if name in _ERROR_TYPES:
        return name
    if isinstance(exc, httpx.TransportError):
        return "TransportError"
    return "OtherError"


def _safe_fetch_failure(exc: BaseException) -> str | None:
    try:
        value = getattr(getattr(exc, "failure", None), "value", None)
    except Exception:
        return None
    return value if value in _SAFE_FETCH_FAILURES else None


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


class Telemetry:
    def __init__(self, root: Path):
        self.path = root / "telemetry.jsonl"
        self.lock = Lock()

    def emit(self, event: str, **fields) -> None:
        if event not in _EVENTS:
            raise ValueError("unknown telemetry event")
        record = {"schema_version": 1, "event": event, "timestamp": _timestamp()}
        record.update({key: value for key, value in fields.items() if key in _FIELDS})
        line = (json.dumps(record, separators=(",", ":")) + "\n").encode("utf-8")
        with self.lock:
            with self.path.open("ab", buffering=0) as handle:
                written = handle.write(line)
                if written != len(line):
                    raise OSError("short telemetry write")
                os.fsync(handle.fileno())


def _memory() -> dict:
    try:
        import psutil

        return {"rss_bytes": psutil.Process().memory_info().rss,
                "available_bytes": psutil.virtual_memory().available}
    except Exception:
        return {"rss_bytes": None, "available_bytes": None}


def _run_id() -> str | None:
    try:
        from deepchoice.runtime.context import get_run_context

        context = get_run_context()
        return context.run_id if context is not None else None
    except Exception:
        return None


def _install_observers(telemetry: Telemetry) -> None:
    # serve has configured paths/thread limits, but Config has not loaded the app.
    # Importing the embedding module adds no getter/model invocation.
    from deepchoice.utils import embedding
    from deepchoice.citations import verifier as citation_verifier
    from deepchoice.outbound import resolver, tunnel
    from deepchoice.utils.llm import TIERS

    original_embedding = embedding.get_embedding_model
    original_connect = tunnel.PinnedProxyBackend.connect_tcp
    original_tls = tunnel._TunnelStream.start_tls
    original_fetch = resolver.ChannelResolver.safe_fetch
    original_citation_fetch = citation_verifier.safe_fetch
    original_http = httpx.AsyncClient._send_single_request
    model_host = urlsplit(TIERS["deepseek-flash"]["base"]).hostname
    forward_endpoint = _endpoint_identity(os.environ.get("FWD_BASE"))
    first_lock = Lock()
    first_seen = False

    @wraps(original_embedding)
    def observed_embedding():
        nonlocal first_seen
        with first_lock:
            observe = not first_seen
            if observe:
                first_seen = True
                cold = embedding._model is None
        if not observe:
            return original_embedding()
        run_id = _run_id()
        started_at = _timestamp()
        started = time.monotonic_ns()
        telemetry.emit("embedding_first_start", run_id=run_id, started_at=started_at,
                       cold=cold, **_memory())
        status, error = "failure", None
        try:
            model = original_embedding()
            status = "success"
            return model
        except BaseException as exc:
            error = _error_type(exc)
            raise
        finally:
            telemetry.emit("embedding_first_end", run_id=run_id, started_at=started_at,
                           ended_at=_timestamp(), cold=cold,
                           model_initialized=embedding._model is not None,
                           duration_ms=(time.monotonic_ns() - started) / 1_000_000,
                           status=status, error_type=error, **_memory())

    @wraps(original_connect)
    async def observed_connect(self, host, port, timeout=None, local_address=None, socket_options=None):
        stream = await original_connect(self, host, port, timeout=timeout,
                                        local_address=local_address, socket_options=socket_options)
        telemetry.emit("proxy_connect_success", run_id=_run_id(), status="success")
        return stream

    @wraps(original_tls)
    async def observed_tls(self, ssl_context, server_hostname=None, timeout=None):
        stream = await original_tls(self, ssl_context, server_hostname=server_hostname, timeout=timeout)
        telemetry.emit("proxy_tls_success", run_id=_run_id(), status="success",
                       certificate_required=ssl_context.verify_mode == ssl.CERT_REQUIRED,
                       hostname_check_enabled=bool(ssl_context.check_hostname),
                       hostname_matches=server_hostname == self._hostname)
        return stream

    @wraps(original_fetch)
    async def observed_fetch(self, source, url, **kwargs):
        run_id = _run_id()
        started = time.monotonic_ns()
        operation = _safe_fetch_operation(source)
        token = _SAFE_FETCH_SOURCE.set(operation)
        try:
            response = await original_fetch(self, source, url, **kwargs)
        except BaseException as exc:
            telemetry.emit("safe_fetch_failure", run_id=run_id, status="failure",
                           source=_observed_source(operation), operation=operation,
                           failure=_safe_fetch_failure(exc), error_type=_error_type(exc),
                           duration_ms=(time.monotonic_ns() - started) / 1_000_000)
            raise
        finally:
            _SAFE_FETCH_SOURCE.reset(token)
        telemetry.emit("safe_fetch_success", run_id=run_id, status="success",
                       source=_observed_source(operation), operation=operation,
                       status_code=response.status_code,
                       duration_ms=(time.monotonic_ns() - started) / 1_000_000)
        return response

    @wraps(original_citation_fetch)
    async def observed_citation_fetch(source, url, **kwargs):
        token = _CITATION_FETCH.set(True)
        try:
            return await original_citation_fetch(source, url, **kwargs)
        finally:
            _CITATION_FETCH.reset(token)

    @wraps(original_http)
    async def observed_http(self, request):
        operation = _observed_operation(request, model_host, forward_endpoint)
        if operation not in _HTTP_OPERATIONS:
            raise RuntimeError("unclassified external HTTP operation")
        source = _observed_source(operation)
        try:
            response = await original_http(self, request)
        except BaseException as exc:
            telemetry.emit("external_http_failure", run_id=_run_id(),
                           status="failure", source=source,
                           operation=operation, method=request.method,
                           error_type=_error_type(exc),
                           failure=_safe_fetch_failure(exc))
            raise
        telemetry.emit("external_http_response", run_id=_run_id(),
                       status="success", source=source, operation=operation,
                       method=request.method, status_code=response.status_code)
        return response
    embedding.get_embedding_model = observed_embedding
    # Existing direct-import aliases must point to the same observer. Future
    # imports obtain it from the embedding module without extra module imports.
    for name in ("deepchoice.retrievers.chroma_kb", "deepchoice.agents.conflict_detector"):
        module = sys.modules.get(name)
        if module is not None and getattr(module, "get_embedding_model", None) is original_embedding:
            module.get_embedding_model = observed_embedding
    tunnel.PinnedProxyBackend.connect_tcp = observed_connect
    tunnel._TunnelStream.start_tls = observed_tls
    resolver.ChannelResolver.safe_fetch = observed_fetch
    citation_verifier.safe_fetch = observed_citation_fetch
    httpx.AsyncClient._send_single_request = observed_http


async def _managed_server(server, root: Path, parent, telemetry: Telemetry,
                          instance_nonce: str) -> None:
    async def watch():
        started_logged = False
        pending_reason = None
        while True:
            if server.started and not started_logged:
                telemetry.emit(
                    "service_started", status="success", instance_nonce=instance_nonce
                )
                started_logged = True
            if (root / "stop-service.flag").exists():
                pending_reason = "stop_flag"
            try:
                parent_alive = parent.is_running()
            except Exception:
                parent_alive = False
            if not parent_alive:
                pending_reason = "parent_exit"
            # Let lifespan startup settle before requesting normal shutdown.
            # Uvicorn can otherwise return after startup without its teardown.
            if pending_reason is not None and server.started:
                telemetry.emit("service_stop_requested", reason=pending_reason)
                server.should_exit = True
                return
            await asyncio.sleep(0.5)

    watcher = asyncio.create_task(watch())
    try:
        await server.serve()
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)
        telemetry.emit("service_stopped", status="finished")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--profile", choices=("serial-r1", "concurrent-r1", "concurrent-r2", "serial-r2"), required=True)
    parser.add_argument("--frozen-root", type=Path, required=True)
    parser.add_argument("--control-root", type=Path, required=True)
    parser.add_argument("--instance-nonce", required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    frozen_root = args.frozen_root.resolve()
    control_root = args.control_root.resolve()
    # A repository checkout uses the ``src`` layout.  Put both the frozen
    # product package and its benchmark helpers ahead of the editable current
    # checkout so a historical arm cannot silently import current product
    # code from the active virtual environment.
    sys.path.insert(0, str(frozen_root))
    sys.path.insert(0, str(frozen_root / "src"))
    telemetry = Telemetry(control_root)
    try:
        if (not root.is_dir() or not frozen_root.is_dir() or not control_root.is_dir()
                or not 1 <= args.port <= 65535 or (control_root / "stop-service.flag").exists()):
            raise ValueError
        if re.fullmatch(r"[0-9a-f]{32}", args.instance_nonce) is None:
            raise ValueError
        telemetry.emit(
            "telemetry_ready", status="success", instance_nonce=args.instance_nonce
        )
        # Inherited effective config is trusted only in this child process.
        # No .env or parent environment is changed by this runner.
        from deepchoice.outbound.tunnel import proxy_endpoint_identity

        os.environ["SAFE_FETCH_TRUSTED_LOCAL_PROXY"] = proxy_endpoint_identity(os.environ.get("LOCAL_PROXY", ""))
        import psutil
        import uvicorn
        import benchmarks as benchmarks_package
        import benchmarks.product_baseline_experiment as baseline_experiment

        if (Path(benchmarks_package.__file__).resolve()
                != (frozen_root / "benchmarks/__init__.py").resolve()
                or Path(baseline_experiment.__file__).resolve()
                != (frozen_root / "benchmarks/product_baseline_experiment.py").resolve()):
            raise RuntimeError("benchmark import escaped frozen root")
        serve = baseline_experiment.serve

        parent = psutil.Process(os.getppid())
        original_run = uvicorn.run

        def observed_run(app, **kwargs):
            if kwargs.get("workers") != 1 or kwargs.get("host") != "127.0.0.1" or kwargs.get("port") != args.port:
                raise ValueError
            _install_observers(telemetry)
            server = uvicorn.Server(uvicorn.Config(app, **kwargs))
            asyncio.run(
                _managed_server(
                    server, control_root, parent, telemetry, args.instance_nonce
                )
            )
            telemetry.emit("asyncio_runner_returned", status="finished")

        uvicorn.run = observed_run
        try:
            serve(root, args.profile, args.port, "cold-in-research")
        finally:
            uvicorn.run = original_run
        return 0
    except Exception as exc:
        telemetry.emit("child_failure", status="failure", error_type=_error_type(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
