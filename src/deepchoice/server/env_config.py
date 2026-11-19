"""Environment-file loading and shared paths for deployment.

Multiple git worktrees of the same repository each have their own working
directory, so a `.env` file and an `outputs/` directory inside one checkout are
invisible to the others. Two environment variables let one deployment share them
instead of copying them into every worktree:

  * ``DEEPCHOICE_ENV_FILE``   explicit dotenv file loaded by the server (kept
    outside the git working tree, e.g. ``D:\\deepchoice-data\\.env``);
  * ``DEEPCHOICE_OUTPUT_DIR`` directory for run outputs and checkpoint database
    (default: ``./outputs``, preserving existing behaviour).

Both are resolved at import time by ``app``/``snapshot_store``; the helpers below
are safe to import from scripts and tests.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ENV_FILE_VAR = "DEEPCHOICE_ENV_FILE"
OUTPUT_DIR_VAR = "DEEPCHOICE_OUTPUT_DIR"


def env_file_path() -> str | None:
    """Explicit dotenv path from the environment (None = use default discovery)."""
    value = os.environ.get(ENV_FILE_VAR, "").strip()
    return value or None


def load_environment() -> bool:
    """Load configuration: the explicit env file when configured, else default."""
    path = env_file_path()
    if path:
        return load_dotenv(dotenv_path=path)
    return load_dotenv()


def output_dir() -> Path:
    """Output/checkpoint directory, overridable for a shared data location."""
    value = os.environ.get(OUTPUT_DIR_VAR, "").strip()
    return Path(value) if value else Path("./outputs")
