# Phase 5-1 离线 Smoke 评估

`smoke-v1` 是一个固定的 12-case fixture-replay 集，数据集冻结日为 2026-09-15。它覆盖 query analysis、引用验证、结论后处理和报告渲染，每个阶段 3 例。评估复用确定性代码和本地 fixture，不请求 LLM/judge 或网络。

在项目虚拟环境中运行并写出本地 artifact：

```powershell
.\.venv\Scripts\python.exe -m benchmarks.run_offline_eval --output outputs\phase5-smoke-v1.json
```

检查本次计算是否与仓库中记录的 smoke baseline 一致：

```powershell
.\.venv\Scripts\python.exe -m benchmarks.run_offline_eval --check-baseline
```

`--check-baseline` 会比较稳定 artifact fingerprint；`evaluated_at`、`current_manifest_id` 和 fingerprint 字段本身不参与指纹计算。`current_manifest_id` 仍保留在 artifact 中作为本次运行的配置溯源，但它包含未被 fixture 执行的模型、端点和推理配置，因此不应让相同离线结果误报漂移。需要评估另一份数据文件时可用 `--dataset PATH`，但它仍须满足 smoke-v1 的固定契约。只有在审阅过数据集或预期输出的有意变更后才更新 checked-in baseline；不要把 `--write-baseline` 当作普通验证命令。

Artifact 包含数据集 ID、版本、冻结日期和文件 SHA-256，评估时间、逐阶段分子/分母、manifest ID、core asset registry ID、逐例结果和 fingerprint。来源健康标记为 `not_run`，各默认来源显示 `degraded/unmeasured`，因为该评估刻意不做真实网络探测。

这些分数只能说明固定 fixture 在当前确定性代码上是否通过、报告结构检查是否满足门槛。它们不衡量真实模型语义质量、真实查询表现或在线信源可用性，也不能与历史 300-case benchmark 的结果合并或直接比较。
