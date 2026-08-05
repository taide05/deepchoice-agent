# DeepChoice 200-case benchmark — 5 cases per batch, 40 batches total
# Run from D:\deepchoice-agent:  .\benchmarks\run_all_batches.ps1

$ErrorActionPreference = "Continue"

# Clean old batch results
Remove-Item -Path "benchmarks\runs\runs-batch*.json" -Force -ErrorAction SilentlyContinue
Remove-Item -Path "benchmarks\runs\benchmark-batch*.json" -Force -ErrorAction SilentlyContinue
Write-Host "Cleaned old batch files. Starting 40 batches (200 cases, 5/batch)."

$totalBatches = 40
$ok = 0
$fail = 0

for ($b = 1; $b -le $totalBatches; $b++) {
    Write-Host ("#" * 60)
    Write-Host "# BATCH $b/$totalBatches"
    Write-Host ("#" * 60)

    python -m benchmarks.run_baseline `
        --cases-file benchmarks/cases_200.json `
        --batch $b `
        --batch-size 5 `
        --verbose

    if ($LASTEXITCODE -eq 0) {
        $ok++
        Write-Host "BATCH $b OK ($ok OK / $fail FAILED)"
    } else {
        $fail++
        Write-Host "BATCH $b FAILED (exit $LASTEXITCODE) ($ok OK / $fail FAILED)"
    }
}

Write-Host ("=" * 60)
Write-Host "ALL DONE: $ok/$totalBatches OK, $fail failed"
Write-Host ("=" * 60)

Write-Host "`nMerging..."
python -m benchmarks.run_baseline --merge --verbose
Write-Host "`nDone."
