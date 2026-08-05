#!/bin/bash
# DeepChoice batch benchmark: evidence vs no-evidence comparison
# Each batch runs same cases twice (with/without evidence).
# Anaconda Python 3.12 avoids sklearn/pyarrow segfault on Python 3.13.
#
# Usage:
#   bash benchmarks/run_batch_comparison.sh [start] [end] [total_cases] [batch_size]
#   bash benchmarks/run_batch_comparison.sh 1 5 50 10   # default: 5 batches of 10
#   bash benchmarks/run_batch_comparison.sh 6 10 50 10   # resume from batch 6

set -e

PYTHON="D:/Anaconda/python.exe"
export HF_HUB_OFFLINE=1
export HF_HOME="C:/Users/6666/.cache/huggingface"

cd "$(dirname "$0")/.."

START="${1:-1}"
END="${2:-5}"
TOTAL="${3:-50}"
BATCH_SIZE="${4:-10}"
OUTDIR="benchmarks/runs/batch-comparison"
mkdir -p "$OUTDIR"

echo "========================================"
echo "Batch Comparison: evidence vs no-evidence"
echo "Batches: $START -> $END (size=$BATCH_SIZE, total=$TOTAL)"
echo "Python: $(D:/Anaconda/python.exe --version 2>&1)"
echo "========================================"

for batch in $(seq "$START" "$END"); do
    TS=$(date +%H%M%S)
    echo ""
    echo "===== BATCH $batch/$END ($TS) ====="

    echo "[$TS] Running WITH evidence gathering..."
    $PYTHON -m benchmarks.run_baseline \
        --cases "$TOTAL" --batch "$batch" --batch-size "$BATCH_SIZE" \
        2>&1 | grep -E "^\[|Done|ERROR|confidence|Batch|Report" || true
    LATEST=$(ls -t benchmarks/runs/benchmark-*.json 2>/dev/null | head -1)
    if [ -n "$LATEST" ]; then
        cp "$LATEST" "$OUTDIR/batch-${batch}-evidence.json"
        echo "  Saved: $OUTDIR/batch-${batch}-evidence.json"
    fi

    sleep 3

    echo "[$TS] Running WITHOUT evidence gathering..."
    $PYTHON -m benchmarks.run_baseline \
        --cases "$TOTAL" --batch "$batch" --batch-size "$BATCH_SIZE" --no-evidence \
        2>&1 | grep -E "^\[|Done|ERROR|confidence|Batch|Report" || true
    LATEST=$(ls -t benchmarks/runs/benchmark-*.json 2>/dev/null | head -1)
    if [ -n "$LATEST" ]; then
        cp "$LATEST" "$OUTDIR/batch-${batch}-noevidence.json"
        echo "  Saved: $OUTDIR/batch-${batch}-noevidence.json"
    fi

    echo "Batch $batch done. $(date +%H:%M:%S)"

    if [ "$batch" -lt "$END" ]; then
        echo "  Next batch in 10s... (Ctrl+C to stop)"
        sleep 10
    fi
done

echo ""
echo "All done. Files in $OUTDIR:"
ls -la "$OUTDIR/"
