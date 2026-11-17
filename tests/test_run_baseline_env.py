"""The benchmark entry point freezes reproducibility settings before imports.

A case must not learn an official-docs term that changes a later case, and the
retrieval cache must be frozen for the same reason. `learned_docs` reads its flag
at import time, so the entry point has to set the environment before the first
deepchoice import — only a fresh process can prove that ordering.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

EVALUATION_VARIABLES = ("LEARNED_DOCS_READONLY", "RETRIEVAL_CACHE_ENABLED")


def test_default_concurrency_is_one_documented_value():
    from benchmarks import run_baseline

    assert run_baseline.DEFAULT_CONCURRENCY == 4
    source = Path(run_baseline.__file__).read_text(encoding="utf-8")
    # The historical entry point disagreed with itself (10 in the header, 8 in
    # the constant, 5 in the docstring); those values must not come back.
    assert "--concurrency 10" not in source
    assert "default 5" not in source
    assert "default 8" not in source


def test_freeze_helper_sets_the_two_evaluation_variables(monkeypatch):
    from benchmarks import run_baseline

    for name in EVALUATION_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    run_baseline._freeze_evaluation_env()
    assert os.environ["LEARNED_DOCS_READONLY"] == "1"
    assert os.environ["RETRIEVAL_CACHE_ENABLED"] == "0"


def test_allow_learning_is_the_explicit_opt_out(monkeypatch):
    from benchmarks import run_baseline
    from deepchoice.retrievers import learned_docs

    monkeypatch.setenv("LEARNED_DOCS_READONLY", "1")
    monkeypatch.setattr(learned_docs, "_READONLY", True)
    run_baseline.allow_learning_mode()
    assert os.environ["LEARNED_DOCS_READONLY"] == "0"
    assert learned_docs._READONLY is False


def test_entry_point_freezes_learned_docs_in_a_fresh_process():
    env = {key: value for key, value in os.environ.items()
           if key not in EVALUATION_VARIABLES}
    script = (
        "import os\n"
        "import benchmarks.run_baseline as rb\n"
        "from deepchoice.retrievers import learned_docs\n"
        "assert os.environ['LEARNED_DOCS_READONLY'] == '1'\n"
        "assert os.environ['RETRIEVAL_CACHE_ENABLED'] == '0'\n"
        "assert rb.DEFAULT_CONCURRENCY == 4\n"
        "assert learned_docs._READONLY is True\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script], cwd=str(REPO_ROOT), env=env,
        # No pipes: the sandbox cannot create them, and the child proves the
        # order by exiting non-zero when an assertion fails.
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180,
    )
    assert proc.returncode == 0
