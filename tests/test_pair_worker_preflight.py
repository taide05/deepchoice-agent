"""The real-entry preflight checks frozen caps without dispatching research."""
import json
import os
import pathlib
import subprocess
import sys

WORKTREE = pathlib.Path(__file__).resolve().parents[1]


def _run(env_overrides):
    env = dict(os.environ)
    env.update({
        "PYTHONPATH": str(WORKTREE / "src"),
        "PRECODEX_LLM_MAX": "48",
        "PRECODEX_TAVILY_MAX": "24",
        "PRECODEX_WALL_MAX_S": "1800",
        "OFFICIAL_FETCH_MAX_PAGE_ATTEMPTS_PER_RUN": "4",
        "OFFICIAL_FETCH_MAX_HTTP_REQUESTS_PER_RUN": "12",
        "OFFICIAL_FETCH_TOTAL_DEADLINE_S": "15",
        "OFFICIAL_FETCH_MAX_BYTES": "1048576",
        "OFFICIAL_BODY_STORE_CHARS": "20000",
        "EVIDENCE_INPUT_BUDGET_CHARS": "24000",
    })
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, str(WORKTREE / "scripts" / "pair_worker.py"),
         "--payload", "unused.json", "--outdir", "unused",
         "--task-id", "preflight", "--preflight-only"],
        cwd=str(WORKTREE), env=env, capture_output=True, text=True,
        timeout=60,
    )


def test_preflight_passes_authorized_caps_without_dispatch():
    result = _run({})
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["snapshot"]["llm_requests_max"] == 48
    assert payload["effective_env"]["official_page_attempts"] == 4


def test_preflight_rejects_over_cap():
    result = _run({"PRECODEX_LLM_MAX": "49"})
    assert result.returncode == 4
