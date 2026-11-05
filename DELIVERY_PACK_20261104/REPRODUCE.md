# 复现说明（新代码正式 200）

## 环境
- worktree：`D:\deepchoice-precodex`，分支 `precodex/deepseek-adapter`
- 代码：主批 `a0355554d33b`；修复批 6 例（018/023/026/066/111/194）`beec4495db3c7`（并发 2）；
  023/026 复修批 `df99023`；第 4 轮复修批 `890591d`（014/023/085/187）；均含 Phase A 修复（Tavily extract 端点/403 兜底/provenance/双括号引用）
- Python：`D:\deepchoice-agent\.venv\Scripts\python.exe`
- 凭据：`D:\deepchoice-agent\.env`（由 `run_service.load_credentials()` 加载，不打印）

## 运行
```powershell
$env:PYTHONPATH='D:\deepchoice-precodex\src;D:\deepchoice-precodex'
$env:EVIDENCE_INPUT_BUDGET_CHARS='32000'
& D:\deepchoice-agent\.venv\Scripts\python.exe .scratch\cases\run_batch.py `
  --cases .scratch\cases\cases_formal_200.json `
  --out .scratch\cases\runs\final-200-newcode-20261104 `
  --concurrency 4 --timeout 1800 --max-tokens 16000000
```

## 后处理（只读、零模型调用）
```powershell
python .scratch\cases\prepare_new_run_review_ready_20261104.py <run>
python .scratch\cases\compute_new200_metrics_20261104.py <run>
python .scratch\cases\aggregate_reviews_20261104.py <run>
python .scratch\cases\make_new200_result_20261104.py <run>
python .scratch\cases\check_batch_gate_20261104.py <run> 200 --require-provenance --extra <fill_run>
```

## 评审
- 卡：`INDEPENDENT_REVIEW_CARD_20261104.md`；
- 内部层：`<run>/review_internal/*.json`（agent workflow，只读两文件/例）；
- 独立层：`<run>/review_independent/*.json`（独立 prompt，不见内部结论）。

## 修复批（第三层抽检后的重跑）
```powershell
# 6 例修复验证（2026-11-04，代码 beec4495，并发 2，cap 700k）
& D:\deepchoice-agent\.venv\Scripts\python.exe .scratch\cases\run_batch.py `
  --cases .scratch\cases\cases_fix6_20261105.json `
  --out .scratch\cases\runs\final-200-fix6b-20261104 --concurrency 2 --timeout 1200 --max-tokens 700000
# 023/026 复修（代码 df99023，并发 2，cap 300k）
& D:\deepchoice-agent\.venv\Scripts\python.exe .scratch\cases\run_batch.py `
  --cases .scratch\cases\cases_fix2_20261104.json `
  --out .scratch\cases\runs\final-200-fix2-20261104 --concurrency 2 --timeout 1200 --max-tokens 300000
```

## 第 4 轮定向复修（2026-11-05，代码 890591d，并发 2，cap 500k）
```powershell
& D:\deepchoice-agent\.venv\Scripts\python.exe .scratch\cases\run_batch.py `
  --cases .scratch\cases\cases_fix4_20261104.json `
  --out .scratch\cases\runs\final-200-fix4-20261104 --concurrency 2 --timeout 1200 --max-tokens 500000
```
