"""Final entry point for the single authorized diagnostic run.

Loads ONLY the credentials this run needs, arms the stop lines before the app is
imported, then verifies the real imported source and the real resolved state
paths (not the intended ones) before binding loopback only.

Credentials come from the current project's local file by path. They are never
printed, copied or committed.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

WORKTREE = Path(__file__).resolve().parent
SRC = WORKTREE / "src"
CURRENT_ENV = Path(r"D:\deepchoice-agent\.env")
HOST = "127.0.0.1"
PORT = 8100

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


def main() -> int:
    os.chdir(WORKTREE)
    sys.path.insert(0, str(SRC))

    loaded = load_credentials()
    print("credentials loaded (values not shown):")
    for name, state in sorted(loaded.items()):
        print(f"  {name:24} {state}")
    if not any(n.endswith("API_KEY") or n.endswith("API_KEYS") for n in loaded):
        print("BLOCKED: no LLM/search credential was loaded; refusing to start.")
        return 2

    os.environ["API_BASE"] = f"http://{HOST}:{PORT}"

    import run_limits

    # One Tavily key only, before anything can build a pool from both names.
    key_count = run_limits.normalize_single_tavily_key()
    print(f"tavily keys after normalisation: {key_count} (single-key mode)")
    if key_count == 0:
        print("BLOCKED: no Tavily key available after normalisation.")
        return 2

    run_limits.arm()
    run_limits.arm_run_timer()

    # ---- verify the REAL import and the REAL resolved paths ----
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
    bad = []
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

    snap = run_limits.snapshot()
    print(f"\nstop lines: LLM<={snap['llm_requests_max']} "
          f"Tavily<={snap['tavily_posts_max']} wall<={snap['wall_clock_max_s']}s")

    if bad:
        print(f"\nBLOCKED: not isolated or not the intended source: {bad}")
        return 3

    print(f"\nbinding http://{HOST}:{PORT}\n", flush=True)
    import uvicorn

    uvicorn.run("deepchoice.server.app:app", host=HOST, port=PORT, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
