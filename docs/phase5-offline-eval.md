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

`--check-baseline` 会比较稳定 artifact fingerprint；`evaluated_at`、`current_manifest_id` 和 fingerprint 字段本身不参与指纹计算。`current_manifest_id` 仍保留在 artifact 中作为本次运行的配置溯源，但它包含未被 fixture 执行的模型、端点和推理配置，因此不应让相同离线结果误报漂移。需要评估另一份数据文件时可用 `--dataset PATH`，但它仍须满足 smoke-v1 的固定契约。只有在审阅过数据集、预期输出或有意变更的核心资产身份后才更新 checked-in baseline；资产身份单独变化时，先逐字段确认12例输出、指标、数据集和来源健康未变。不要把 `--write-baseline` 当作普通验证命令。

Artifact 包含数据集 ID、版本、冻结日期和文件 SHA-256，评估时间、逐阶段分子/分母、manifest ID、core asset registry ID、逐例结果和 fingerprint。来源健康标记为 `not_run`，各默认来源显示 `degraded/unmeasured`，因为该评估刻意不做真实网络探测。

这些分数只能说明固定 fixture 在当前确定性代码上是否通过、报告结构检查是否满足门槛。它们不衡量真实模型语义质量、真实查询表现或在线信源可用性，也不能与历史 300-case benchmark 的结果合并或直接比较。

2026-09-21 S1 验收审阅并更新了记录基线：数据集文件、版本/hash、12-case 分母和各项指标不变，
仍为 12/12 通过且 12/12 确定性一致。CS-003 的 context_dependent 结果有意清除排名，因此结果
hash 改变；另外更新评估时间、manifest/core-asset 身份与总 fingerprint。随后
`--check-baseline` 通过；来源健康仍为 `not_run`，不构成新 live 测量。

2026-09-22 不确定解释修复升级报告模板身份后再次核对产物：12 个案例的输出/hash、
全部指标、数据集与来源健康完全不变；仅 evaluated_at、current_manifest_id、
core_asset_registry_id 和 artifact_fingerprint 四项不同，因此只更新这四项基准记录。
未修改 fixture、预期输出或验收阈值，不把本次身份更新声称为模型质量改善。

2026-09-23 行动安全修复再次核对：仍只有上述四项身份/时间/fingerprint变化，12个案例
输出/hash、指标、数据集和 source_health 不变。更新对应四项基准记录；专门的行动安全
反例由自动化测试覆盖，不把 smoke-v1 冒充本次全部行为覆盖或真实质量证明。

2026-10-02 citation v15、self-review v5 与报告模板身份更新时逐字段复核基线：固定12例的
逐例结果、指标、数据集和来源健康均不变；仅 evaluated_at、current_manifest_id、
core_asset_registry_id、artifact_fingerprint 变化。更新这四项记录并通过 `--check-baseline`；
新的句子级自审行为由专门的离线回归覆盖，smoke 分数不代表真实报告质量。

2026-10-10 问题依据绑定v6后复核：固定12例输出、指标、数据集和来源健康均未变化，
仅更新 evaluated_at、current_manifest_id、core_asset_registry_id 和
artifact_fingerprint 四项，`--check-baseline` 通过。新增绑定器的多原句传递由相关
回归及固定来源节点回放验证；smoke 仍不衡量真实报告语义。

2026-10-10 Tavily v3/检索缓存策略v2后复核：12例输出、指标、数据集、core asset身份、
fingerprint及`not_run`来源健康均不变；仅更新评估时间和当前manifest ID。
`--check-baseline`通过。smoke不执行新增网页读取，也不证明真实来源或报告质量。
