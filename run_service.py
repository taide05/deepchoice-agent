"""Launcher for the single-run diagnostic service.

The launcher owns the run's identity boundary: it loads only the credentials the
run needs, verifies the real imported source and the real resolved state paths,
and then starts the service as a **dedicated child process** it can guard.

The child arms the in-process stop lines and prepares the embedding model from
local files before dispatch. The launcher's guard is the final stop mechanism:
if research does not finish inside the wall-clock deadline - including when the
child's event loop is blocked in a synchronous call - the guard cancels first,
waits a bounded grace period, and then stops only the child it created, recording
the deadline and the actual exit time beside the run.

Credentials are loaded from a local `.env` file (override its location with the
`DEEPCHOICE_ENV_FILE` environment variable). They are never printed, copied or committed.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

WORKTREE = Path(__file__).resolve().parent
SRC = WORKTREE / "src"
CURRENT_ENV = Path(os.environ.get("DEEPCHOICE_ENV_FILE") or (WORKTREE / ".env"))
HOST = "127.0.0.1"
PORT = 8100
BASE_URL = f"http://{HOST}:{PORT}"

# Only what this run needs. Deliberately excludes retired Qwen/DashScope names.
NEEDED = (
    "DS_FLASH_API_KEY", "FLASH_API_KEY", "DEEPSEEK_API_KEY",
    "DS_FLASH_MODEL", "FLASH_MODEL",
    "DS_FLASH_BASE_URL", "FLASH_BASE_URL", "DEEPSEEK_BASE_URL",
    "TAVILY_API_KEY", "TAVILY_API_KEYS",
    "GITHUB_TOKEN", "STACKEXCHANGE_API_KEY",
    "LLM_DS_CONCURRENCY",
)


def load_credentials() -> dict[str, str]:
    if not CURRENT_ENV.is_file():
        print(f"BLOCKED: no credentials file at {CURRENT_ENV}")
        return {}
    from dotenv import dotenv_values

    values = dotenv_values(CURRENT_ENV)
    loaded = {}
    for name in NEEDED:
        value = values.get(name)
        if value:
            os.environ[name] = value
            loaded[name] = f"set (len {len(value)})"
    return loaded


def verify_identity() -> list[str]:
    """Verify the REAL import and the REAL resolved paths, before starting."""
    import deepchoice
    from deepchoice.agents import orchestrator
    from deepchoice.retrievers import learned_docs, tavily_keypool
    from deepchoice.utils import llm

    real = {
        "deepchoice": Path(deepchoice.__file__).resolve(),
        "orchestrator": Path(orchestrator.__file__).resolve(),
        "llm": Path(llm.__file__).resolve(),
    }
    print("\nactual imported source:")
    bad: list[str] = []
    for label, path in real.items():
        inside = str(path).lower().startswith(str(WORKTREE).lower())
        print(f"  {'OK ' if inside else 'BAD'} {label:14} {path}")
        if not inside:
            bad.append(label)

    state_paths = {
        "outputs": orchestrator.OUTPUT_DIR.resolve(),
        "checkpoints": (orchestrator.OUTPUT_DIR / "checkpoints.db").resolve(),
        "learned_docs": learned_docs.LEARNED_DOCS_PATH.resolve(),
        "tavily_key_state": Path(os.path.abspath(tavily_keypool._state_path())),
        "chroma_db": Path(os.path.abspath(
            os.environ.get("CHROMA_PATH", "./chroma_kb/chroma_db"))),
    }
    print("\nactual resolved state paths:")
    for label, path in state_paths.items():
        inside = str(path).lower().startswith(str(WORKTREE).lower())
        print(f"  {'OK ' if inside else 'BAD'} {label:18} {path}")
        if not inside:
            bad.append(label)

    print("\ntiers:")
    for name, cfg in llm.TIERS.items():
        print(f"  {name:16} {cfg['model']} @ {cfg['base']}")
    return bad


def cancel_via_http(task_id: str) -> str:
    """Normal cancellation path; bounded, and useless if the loop is blocked."""
    request = urllib.request.Request(
        f"{BASE_URL}/research/{task_id}/cancel", data=b"", method="POST")
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return f"http {response.status}"
    except Exception as exc:
        return f"failed: {type(exc).__name__}"


def main() -> int:
    os.chdir(WORKTREE)
    sys.path.insert(0, str(SRC))

    # Evaluation identity: the learned-docs file and retrieval cache are frozen
    # for the whole run. These are set before the child imports the modules that
    # read them, and before verify_identity imports learned_docs in this process.
    os.environ["LEARNED_DOCS_READONLY"] = "1"
    os.environ["RETRIEVAL_CACHE_ENABLED"] = "0"
    print("evaluation freeze: LEARNED_DOCS_READONLY=1 RETRIEVAL_CACHE_ENABLED=0")

    loaded = load_credentials()
    print("credentials loaded (values not shown):")
    for name, state in sorted(loaded.items()):
        print(f"  {name:24} {state}")
    if not any(n.endswith("API_KEY") or n.endswith("API_KEYS") for n in loaded):
        print("BLOCKED: no LLM/search credential was loaded; refusing to start.")
        return 2

    os.environ["API_BASE"] = BASE_URL

    import run_limits

    # One Tavily key only, before anything can build a pool from both names.
    key_count = run_limits.normalize_single_tavily_key()
    print(f"tavily keys after normalisation: {key_count} (single-key mode)")
    if key_count == 0:
        print("BLOCKED: no Tavily key available after normalisation.")
        return 2

    bad = verify_identity()
    snap = run_limits.snapshot()
    print(f"\nstop lines: LLM<={snap['llm_requests_max']} "
          f"Tavily<={snap['tavily_posts_max']} wall<={snap['wall_clock_max_s']}s")
    if bad:
        print(f"\nBLOCKED: not isolated or not the intended source: {bad}")
        return 3

    env = dict(os.environ)
    env["DEEPCHOICE_WORKTREE"] = str(WORKTREE)
    env["DEEPCHOICE_HOST"] = HOST
    env["DEEPCHOICE_PORT"] = str(PORT)
    # The guard recognises this service's runs by this token, not by process ids:
    # a virtualenv python.exe is a launcher and the service runs as its child.
    service_token = uuid.uuid4().hex
    env["DEEPCHOICE_SERVICE_TOKEN"] = service_token
    # Offline model stack for the child; set before transformers is imported there.
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"
    env["HF_HUB_DISABLE_TELEMETRY"] = "1"
    env["PYTHONPATH"] = os.pathsep.join(
        [str(SRC), str(WORKTREE)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))

    print(f"\nstarting dedicated service process on http://{HOST}:{PORT}\n", flush=True)
    service_started_epoch = time.time()
    child = subprocess.Popen(
        [sys.executable, "-m", "deepchoice.server.service"],
        cwd=str(WORKTREE), env=env,
        stdout=None, stderr=None,  # inherit: the run's logs stay visible
    )
    print(f"[launcher] service pid {child.pid}; the guard owns this process only",
          flush=True)

    try:
        from deepchoice.run_guard import guard_service

        record = guard_service(
            child,
            outputs_dir=WORKTREE / "outputs",
            wall_clock_max_s=float(run_limits.WALL_CLOCK_MAX_S),
            service_started_epoch=service_started_epoch,
            cancel_fn=cancel_via_http,
            service_token=service_token,
            log=lambda message: print(message, flush=True),
        )
    except Exception as guard_err:
        # The guard itself failed; say so next to the runs and stop the child, but
        # never pretend a stop record exists.
        print(f"[launcher] guard failed: {type(guard_err).__name__}: {guard_err}",
              flush=True)
        try:
            (WORKTREE / "outputs").mkdir(parents=True, exist_ok=True)
            (WORKTREE / "outputs" / "guard_failure.json").write_text(
                json.dumps({
                    "at_epoch": time.time(),
                    "at_iso": time.strftime("%Y-%m-%dT%H:%M:%S%z",
                                            time.localtime(time.time())),
                    "service_pid": child.pid,
                    "error": f"{type(guard_err).__name__}: {guard_err}",
                    "note": "no guard_stop record could be written; the child was "
                            "terminated by the launcher's cleanup",
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

    print(f"\n[launcher] guard record: {record}", flush=True)
    if record.get("forced"):
        print(f"[launcher] research was stopped at the wall-clock deadline; "
              f"deadline {record.get('deadline_iso')} exit "
              f"{record.get('exited_at_iso')}", flush=True)
        return 4
    return 0 if record.get("exit_code") in (0, None) else int(record.get("exit_code") or 0)


if __name__ == "__main__":
    raise SystemExit(main())
