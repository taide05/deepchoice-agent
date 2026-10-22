"""Launcher for one real paired diagnostic.

The launcher owns credentials and the frozen 48/24/1800 caps, starts the worker
as a child it can guard, and leaves the exact child/guard records beside the run.
The worker itself writes the run_limits record before the first research
outbound call; the process guard watches that record and the same total deadline.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

WORKTREE = Path(__file__).resolve().parent.parent
SRC = WORKTREE / "src"
CURRENT_ENV = Path(r"D:\deepchoice-agent\.env")
NEEDED = (
    "DS_FLASH_API_KEY", "FLASH_API_KEY", "DEEPSEEK_API_KEY",
    "DS_FLASH_MODEL", "FLASH_MODEL",
    "DS_FLASH_BASE_URL", "FLASH_BASE_URL", "DEEPSEEK_BASE_URL",
    "TAVILY_API_KEY", "TAVILY_API_KEYS",
    "GITHUB_TOKEN", "STACKEXCHANGE_API_KEY",
    "LLM_DS_CONCURRENCY",
)


def load_credentials() -> int:
    if not CURRENT_ENV.is_file():
        print(f"BLOCKED: credentials file missing at {CURRENT_ENV}", flush=True)
        return 0
    from dotenv import dotenv_values
    values = dotenv_values(CURRENT_ENV)
    loaded = 0
    for name in NEEDED:
        value = values.get(name)
        if value:
            os.environ[name] = value
            loaded += 1
    print(f"credentials loaded: {loaded} names (values not shown)", flush=True)
    return loaded


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", required=True)
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--task-id", required=True)
    args = parser.parse_args(argv)

    os.chdir(WORKTREE)
    sys.path.insert(0, str(SRC))
    os.environ["LEARNED_DOCS_READONLY"] = "1"
    os.environ["RETRIEVAL_CACHE_ENABLED"] = "0"
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["PRECODEX_LLM_MAX"] = "48"
    os.environ["PRECODEX_TAVILY_MAX"] = "24"
    os.environ["PRECODEX_WALL_MAX_S"] = "1800"
    os.environ["OFFICIAL_FETCH_MAX_PAGE_ATTEMPTS_PER_RUN"] = "4"
    os.environ["OFFICIAL_FETCH_MAX_HTTP_REQUESTS_PER_RUN"] = "12"
    os.environ["OFFICIAL_FETCH_TOTAL_DEADLINE_S"] = "15"
    os.environ["OFFICIAL_FETCH_MAX_BYTES"] = "200000"
    os.environ["OFFICIAL_BODY_STORE_CHARS"] = "8000"
    print("budget: LLM<=48 Tavily<=24 wall<=1800s official pages<=4 HTTP<=12 "
          "page<=15s bytes<=200000", flush=True)

    if load_credentials() == 0:
        return 2
    import run_limits
    if run_limits.normalize_single_tavily_key() == 0:
        print("BLOCKED: no Tavily key after normalisation", flush=True)
        return 2
    snap = run_limits.snapshot()
    if (snap["llm_requests_max"] != 48 or snap["tavily_posts_max"] != 24
            or snap["wall_clock_max_s"] != 1800.0):
        print(f"BLOCKED: caps were not loaded as authorized: {snap}", flush=True)
        return 3

    outdir = Path(args.outdir).resolve()
    outdir.parent.mkdir(parents=True, exist_ok=True)
    # The process guard discovers the worker's run record by globbing
    # `<guard_root>/*/run_state.json`; use the actual parent so any --outdir
    # nesting depth is still armed and the 1800 s deadline is not silently lost.
    guard_root = outdir.parent
    service_token = uuid.uuid4().hex
    env = dict(os.environ)
    env["DEEPCHOICE_SERVICE_TOKEN"] = service_token
    env["PYTHONPATH"] = os.pathsep.join(
        [str(SRC), str(WORKTREE)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    env["API_BASE"] = "http://127.0.0.1:8100"

    service_started_epoch = time.time()
    child = subprocess.Popen(
        [sys.executable, str(WORKTREE / "scripts" / "pair_worker.py"),
         "--payload", str(Path(args.payload).resolve()),
         "--outdir", str(outdir),
         "--task-id", args.task_id],
        cwd=str(WORKTREE), env=env, stdout=None, stderr=None,
    )
    print(f"[launcher] worker pid {child.pid}; guard owns this child only", flush=True)
    from deepchoice.run_guard import guard_service
    try:
        record = guard_service(
            child,
            outputs_dir=guard_root,
            wall_clock_max_s=1800.0,
            service_started_epoch=service_started_epoch,
            cancel_fn=lambda task_id: "no-op: worker owns its own loop",
            service_token=service_token,
            log=lambda message: print(message, flush=True),
        )
    except Exception as exc:
        # The guard itself failed: never leave a credentialed child running
        # unguarded. Record the failure and terminate only the child we created.
        try:
            guard_root.mkdir(parents=True, exist_ok=True)
            (guard_root / "guard_failure.json").write_text(
                json.dumps({
                    "at_epoch": time.time(),
                    "worker_pid": child.pid,
                    "error": f"{type(exc).__name__}: {exc}",
                    "note": "guard failed; launcher terminated its own child; "
                            "no stop record may be assumed",
                }, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
        raise
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except Exception:
                child.kill()
    print(json.dumps({"guard": record, "worker_exit": child.poll()},
                     ensure_ascii=False, default=str), flush=True)
    return 0 if child.poll() == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
