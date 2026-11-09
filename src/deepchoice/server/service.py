"""Service entry for the dedicated child process the launcher starts and guards.

Two things must be true before any research can be dispatched:

  * the in-process stop lines are armed (the normal cancellation path), and
  * the embedding model has been prepared from local files only, so a research
    node never resolves it mid-run and never triggers a download.

The launcher's process guard is the *final* stop mechanism if this child's event
loop ever blocks; this module does not try to duplicate it.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

OFFLINE_MODEL_ENV = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
}


def configure_offline_model_stack() -> None:
    """Force the model stack offline, locally to this process.

    Must run before transformers / huggingface_hub are imported: they read these
    into module constants at import time. Even with ``local_files_only=True``,
    the hub's header builder otherwise performs one agent-detection GET. This
    changes this process only — no shared environment, proxy or model download.
    """
    os.environ.update(OFFLINE_MODEL_ENV)


def main() -> int:
    worktree = Path(os.environ.get("DEEPCHOICE_WORKTREE", ".")).resolve()
    os.chdir(worktree)
    sys.path.insert(0, str(worktree / "src"))

    configure_offline_model_stack()

    host = os.environ.get("DEEPCHOICE_HOST", "127.0.0.1")
    port = int(os.environ.get("DEEPCHOICE_PORT", "8100"))

    import run_limits

    run_limits.arm()
    run_limits.arm_run_timer()

    # Model preparation happens here — at startup, before any research request
    # can be accepted, never inside a research node. Local files only; an
    # unavailable model is recorded and reported per source at retrieval time.
    from deepchoice.utils.embedding import embedding_model_state, prepare_embedding_model

    prepared = prepare_embedding_model()
    print(f"[service] embedding model prepared: available={prepared['available']} "
          f"reason={prepared['reason'] or '-'} "
          f"seconds={prepared['prepare_seconds']}", flush=True)
    if not prepared["available"]:
        print(f"[service] embedding model unavailable: {prepared['detail']}", flush=True)
        print("[service] the knowledge-base source will report itself unavailable; "
              "no download is attempted", flush=True)

    import uvicorn

    try:
        uvicorn.run("deepchoice.server.app:app", host=host, port=port, log_level="info")
    finally:
        run_limits.persist_counts(str(worktree / "outputs"))
        print(f"[service] final model state: {embedding_model_state()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
