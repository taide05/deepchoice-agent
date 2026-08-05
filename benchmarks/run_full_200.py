"""Run all 40 batches (200 cases, 5/batch) and merge at the end.
Logs to benchmarks/runs/full_run.log for progress tracking.

Usage:
    cd D:\deepchoice-agent
    python -m benchmarks.run_full_200
"""
import asyncio
import sys
from datetime import datetime
from pathlib import Path

# Ensure project root and src are importable
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from dotenv import load_dotenv
load_dotenv()

from benchmarks import run_baseline as rb

BENCHMARKS_DIR = Path(__file__).resolve().parent
CASES_FILE = BENCHMARKS_DIR / "cases_200.json"
LOG_FILE = BENCHMARKS_DIR / "runs" / "full_run.log"

# Clean old batch files
for f in BENCHMARKS_DIR.glob("runs/runs-batch*.json"):
    f.unlink()
for f in BENCHMARKS_DIR.glob("runs/benchmark-batch*.json"):
    f.unlink()

rb.ANNOTATED_CASES_PATH = CASES_FILE


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


async def main():
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log("Starting 200-case benchmark (40 batches x 5 cases)")

    ok = 0
    fail = 0
    for b in range(1, 41):
        log(f"BATCH {b}/40 starting...")
        try:
            await rb.run_baseline(
                n_cases=None,
                verbose=True,
                batch=b,
                batch_size=5,
                cases_file=CASES_FILE,
                gather_evidence=True,
            )
            ok += 1
            log(f"BATCH {b}/40 DONE ({ok} ok / {fail} failed)")
        except Exception as e:
            fail += 1
            log(f"BATCH {b}/40 FAILED: {e}")

    log(f"ALL DONE: {ok}/40 ok, {fail} failed")

    if ok > 0:
        log("Merging all batches...")
        await rb.merge_all_batches(verbose=True)

    log("Complete.")


if __name__ == "__main__":
    asyncio.run(main())
