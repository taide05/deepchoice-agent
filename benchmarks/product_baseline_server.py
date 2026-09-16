"""Isolated application factory for product-baseline experiments.

Start with::

    $env:DEEPCHOICE_EXPERIMENT_DIR = "outputs/product-baseline-v1/serial-r1-runtime"
    python -m uvicorn benchmarks.product_baseline_server:create_app --factory --workers 1

The factory changes only the product/checkpoint/legacy paths.  Knowledge-base
and learned-document snapshots remain explicit environment inputs so an
experiment cannot silently copy or mutate the user's normal runtime data.
"""

from __future__ import annotations

import os
from pathlib import Path

from deepchoice.server.app import app


def create_app():
    raw_root = os.environ.get("DEEPCHOICE_EXPERIMENT_DIR", "").strip()
    if not raw_root:
        raise RuntimeError(
            "DEEPCHOICE_EXPERIMENT_DIR is required for the baseline server"
        )
    root = Path(raw_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    app.state.product_database_path = root / "product.db"
    app.state.checkpoint_database_path = root / "checkpoints.db"
    app.state.legacy_snapshot_root = root / "legacy-import-disabled"
    app.state.execution_enabled = True
    # Baseline attempts must not silently resume interrupted paid work.
    # The normal application's recovery default remains enabled.
    app.state.auto_recovery_enabled = False
    return app


__all__ = ["create_app"]
