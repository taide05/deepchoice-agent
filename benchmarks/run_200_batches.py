"""Run 200 cases in batches of 5, then merge."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from dotenv import load_dotenv
load_dotenv()

from run_baseline import run_baseline, merge_all_batches

CASES_FILE = Path(__file__).resolve().parent / "cases_200.json"
BATCH_SIZE = 5
TOTAL_CASES = 200
TOTAL_BATCHES = TOTAL_CASES // BATCH_SIZE  # 40


async def main():
    ok_batches = 0
    fail_batches = 0

    for b in range(1, TOTAL_BATCHES + 1):
        print(f"\n{'#' * 60}")
        print(f"# BATCH {b}/{TOTAL_BATCHES}")
        print(f"{'#' * 60}")
        try:
            await run_baseline(
                n_cases=None,
                verbose=True,
                with_judge=True,
                batch=b,
                batch_size=BATCH_SIZE,
                cases_file=CASES_FILE,
                gather_evidence=True,
            )
            ok_batches += 1
        except Exception as e:
            print(f"BATCH {b} FAILED: {e}")
            fail_batches += 1

    print(f"\n{'=' * 60}")
    print(f"ALL BATCHES DONE: {ok_batches} ok / {fail_batches} failed")
    print(f"{'=' * 60}")

    if ok_batches > 0:
        print("\nMerging all batches...")
        try:
            # Patch merge to use our cases file
            from run_baseline import ANNOTATED_CASES_PATH as orig_path
            import run_baseline as rb
            rb.ANNOTATED_CASES_PATH = CASES_FILE
            await merge_all_batches(verbose=True)
        except Exception as e:
            print(f"Merge failed: {e}")


if __name__ == "__main__":
    asyncio.run(main())
