"""Run batches 2-40 (batch 1 already done) and merge all."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# Ensure benchmarks is importable
_benchmarks_dir = str(Path(__file__).resolve().parent.parent)
if _benchmarks_dir not in sys.path:
    sys.path.insert(0, _benchmarks_dir)

from dotenv import load_dotenv
load_dotenv()

from benchmarks import run_baseline as rb

CASES_FILE = Path(__file__).resolve().parent / "cases_200.json"


async def main():
    # Patch the annotated cases path for merge
    rb.ANNOTATED_CASES_PATH = CASES_FILE

    for b in range(2, 41):
        print(f"\n{'#' * 60}")
        print(f"# BATCH {b}/40 (cases {(b-1)*5+1}-{b*5})")
        print(f"{'#' * 60}")
        try:
            await rb.run_baseline(
                n_cases=None,
                verbose=True,
                with_judge=True,
                batch=b,
                batch_size=5,
                cases_file=CASES_FILE,
                gather_evidence=True,
            )
        except Exception as e:
            print(f"BATCH {b} ERROR: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 60)
    print("ALL 40 BATCHES DONE")
    print("=" * 60)

    # Merge
    print("\nMerging all 40 batches...")
    await rb.merge_all_batches(verbose=True)


if __name__ == "__main__":
    asyncio.run(main())
