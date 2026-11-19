"""Real end-to-end smoke for checkpoint resume (M5 ops tool).

Drives a running DeepChoice API through one interrupted run and one resume and
verifies the observable contract:

    create task -> stream until N nodes completed -> cancel (interrupt)
    -> poll /status until resumable -> POST /resume {"confirm": true}
    -> stream to __done__ -> verify complete status / snapshots / history

Requires real credentials (the app needs its LLM + Tavily keys) and one real
research run, so it is run by an operator, not in CI. This script is the "≤3
real interrupted resumes" smoke from the M5 release notes; it never runs the
200-case evaluation set.

Modes:
  * full smoke (default): creates a new task and interrupts it with POST /cancel.
  * --task-id ID: resumes an existing interrupted/resumable task, for the
    hard-kill scenario (kill the service, restart it, startup recovery writes the
    interrupted snapshot, then run this mode against that task).

Examples:
    python scripts/resume_smoke.py --base-url http://127.0.0.1:8000
    python scripts/resume_smoke.py --task-id <id> --base-url http://127.0.0.1:8000

Exit codes: 0 = smoke passed, 1 = verification/flow failed, 2 = could not start
(bad arguments/network).

Design record: internal_docs/fix_plans/CHECKPOINT_RESUME_DESIGN_2026-11-17.md
(M5 rollout/verification).
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import httpx

DEFAULT_QUERY = "FastAPI vs Flask for a small REST API"


class SmokeError(RuntimeError):
    """The smoke flow could not complete or a contract check failed."""


def _headers(api_key: str | None) -> dict:
    return {"X-API-Key": api_key} if api_key else {}


def _sse_events(response):
    """Yield (node, event) pairs lazily.

    Lazy is mandatory: the caller stops after N completed nodes and closes the
    stream so the run can be interrupted. Materialising the whole response first
    would let a fast run finish before the cancel is sent (regression caught by
    the real uvicorn smoke).
    """
    for line in response.iter_lines():
        if not line.startswith("data:"):
            continue
        try:
            event = json.loads(line[5:])
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            yield event.get("node"), event


def _read_stream(client: httpx.Client, base_url: str, task_id: str, *,
                 min_nodes: int | None, timeout_s: float) -> tuple[list, str | None]:
    """Read the SSE stream until `min_nodes` distinct nodes or a terminal event.

    Returns (events, terminator) where terminator is "__done__"/"__error__" or
    None when stopping early after min_nodes completed nodes.
    """
    seen: set[str] = set()
    collected: list[tuple[str | None, dict]] = []
    with client.stream(
        "GET", f"{base_url}/research/{task_id}/stream",
        timeout=httpx.Timeout(15.0, read=None),
    ) as response:
        if response.status_code != 200:
            raise SmokeError(f"stream HTTP {response.status_code}")
        deadline = time.monotonic() + timeout_s
        for node, event in _sse_events(response):
            collected.append((node, event))
            if node in ("__done__", "__error__"):
                return collected, node
            if node:
                seen.add(node)
                if min_nodes is not None and len(seen) >= min_nodes:
                    return collected, None
            if time.monotonic() > deadline:
                raise SmokeError(f"stream timed out after {timeout_s}s")
    if min_nodes is not None:
        raise SmokeError(
            f"stream ended before {min_nodes} completed nodes (saw {sorted(seen)})")
    return collected, None


def create_task(client: httpx.Client, base_url: str, query: str) -> str:
    payload = {"query": query, "scene_context": "solo", "constraints": [],
               "report_format": "what_why_how"}
    response = client.post(f"{base_url}/research", json=payload)
    if response.status_code != 200:
        raise SmokeError(f"create task HTTP {response.status_code}: {response.text[:300]}")
    task_id = response.json().get("task_id")
    if not task_id:
        raise SmokeError("create task response has no task_id")
    return str(task_id)


def cancel_task(client: httpx.Client, base_url: str, task_id: str) -> None:
    response = client.post(f"{base_url}/research/{task_id}/cancel")
    if response.status_code not in (200, 202, 204, 409):
        raise SmokeError(f"cancel HTTP {response.status_code}: {response.text[:300]}")


def poll_status(client: httpx.Client, base_url: str, task_id: str, predicate,
                *, timeout_s: float, interval_s: float = 1.0) -> dict:
    deadline = time.monotonic() + timeout_s
    last: dict = {}
    while time.monotonic() < deadline:
        response = client.get(f"{base_url}/research/{task_id}/status")
        if response.status_code == 200:
            last = response.json()
            if predicate(last):
                return last
        time.sleep(interval_s)
    raise SmokeError(f"status condition not met within {timeout_s}s; last={last}")


def wait_resumable(client: httpx.Client, base_url: str, task_id: str,
                   timeout_s: float) -> dict:
    def predicate(status: dict) -> bool:
        if status.get("status") == "complete":
            raise SmokeError(
                "the run completed before it could be interrupted; "
                "retry with --min-nodes 1")
        return bool(status.get("resumable"))

    return poll_status(client, base_url, task_id, predicate, timeout_s=timeout_s)


def resume_task(client: httpx.Client, base_url: str, task_id: str, *,
                api_key: str | None) -> dict:
    response = client.post(f"{base_url}/research/{task_id}/resume",
                           json={"confirm": True},
                           headers=_headers(api_key))
    if response.status_code == 202:
        return response.json()
    detail = ""
    try:
        detail = str(response.json().get("detail") or "")
    except Exception:
        detail = response.text[:300]
    if response.status_code == 409 and detail.startswith("RESUME_IN_PROGRESS"):
        return {"status": "resuming", "in_progress": True}
    raise SmokeError(f"resume refused HTTP {response.status_code}: {detail}")


def verify(client: httpx.Client, base_url: str, task_id: str,
           resume_payload: dict, timeout_s: float) -> dict:
    status = poll_status(client, base_url, task_id,
                         lambda body: body.get("status") == "complete",
                         timeout_s=timeout_s)
    snapshot = client.get(f"{base_url}/research/{task_id}/snapshot")
    attempt_snapshot = client.get(f"{base_url}/research/{task_id}/snapshot",
                                  params={"attempt": 1})
    # The history endpoint is global (`GET /history`), not per-task.
    history = client.get(f"{base_url}/history")
    rows = []
    if history.status_code == 200:
        body = history.json()
        rows = body.get("tasks", body if isinstance(body, list) else [])
    row = next((row for row in rows if row.get("task_id") == task_id), {})
    attempt1 = {}
    if attempt_snapshot.status_code == 200:
        attempt1 = attempt_snapshot.json()
    checks = {
        "status_complete": status.get("status") == "complete",
        "resume_attempt_advanced": (
            resume_payload.get("attempt") == 2
            or int(status.get("attempt") or 0) == 2),
        "complete_snapshot": (
            snapshot.status_code == 200 and "_error" not in snapshot.json()),
        "first_attempt_snapshot": (
            attempt_snapshot.status_code == 200
            and int(attempt1.get("_attempt") or 0) == 1),
        "history_attempts": int(row.get("attempts") or 0) >= 2,
    }
    return {"checks": checks, "passed": all(checks.values()),
            "status": status, "history_row": row}


def run_smoke(client: httpx.Client, base_url: str, *, task_id: str | None = None,
              min_nodes: int = 2, timeout_s: float = 1800.0,
              query: str = DEFAULT_QUERY, api_key: str | None = None) -> dict:
    """Run the whole smoke and return a structured result (raises SmokeError)."""
    base_url = base_url.rstrip("/")
    if task_id is None:
        task_id = create_task(client, base_url, query)
        _read_stream(client, base_url, task_id, min_nodes=min_nodes,
                     timeout_s=timeout_s)
        cancel_task(client, base_url, task_id)
    interruption = "cancel" if min_nodes and not task_id else "resume-existing"
    status = wait_resumable(client, base_url, task_id, timeout_s)
    resume_payload = resume_task(client, base_url, task_id, api_key=api_key)
    events, terminator = _read_stream(client, base_url, task_id,
                                      min_nodes=None, timeout_s=timeout_s)
    if terminator == "__error__":
        raise SmokeError("resumed stream reported __error__")
    result = verify(client, base_url, task_id, resume_payload, timeout_s)
    result.update({
        "task_id": task_id,
        "mode": interruption,
        "resumable_status": status,
        "resume": resume_payload,
        "stream_events": len(events),
        "terminator": terminator,
    })
    if not result["passed"]:
        raise SmokeError(f"contract checks failed: {result['checks']}")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Real end-to-end checkpoint-resume smoke (<=1 run; no 200-case eval).")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--task-id", default=None,
                        help="resume an existing resumable task instead of creating one")
    parser.add_argument("--min-nodes", type=int, default=2,
                        help="nodes to let complete before cancelling (default: 2)")
    parser.add_argument("--timeout", type=float, default=1800.0,
                        help="per-wait timeout in seconds (default: 1800)")
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--api-key", default=None,
                        help="X-API-Key value when DEEPCHOICE_API_KEY is configured")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        with httpx.Client(timeout=30.0) as client:
            result = run_smoke(
                client, args.base_url, task_id=args.task_id,
                min_nodes=args.min_nodes, timeout_s=args.timeout,
                query=args.query, api_key=args.api_key)
    except SmokeError as error:
        print(f"SMOKE FAILED: {error}", file=sys.stderr)
        return 1
    except httpx.HTTPError as error:
        print(f"SMOKE UNAVAILABLE: {error}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"SMOKE PASSED: task={result['task_id']} mode={result['mode']} "
              f"attempts={result['status'].get('attempt')} "
              f"checks={result['checks']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
