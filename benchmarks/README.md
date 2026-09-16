# 评估入口与历史工具

更新：2026-09-16。正式产品效果协议见 [产品效果优化](../docs/product-effectiveness-optimization.md)，
准备检查结果见 [基线准备检查](../docs/baseline-readiness-audit.md)。

| 入口 | 用途和边界 |
|---|---|
| `python -m benchmarks.run_offline_eval --check-baseline` | 固定 smoke-v1 的 12 例，无 LLM/网络；只验证确定性路径 |
| `python -m benchmarks.product_baseline validate` | 校验 O1 的 12 例候选集，不调用 LLM/网络 |
| `python -m benchmarks.product_baseline collect ...` | 经 durable API 采集 serial=1 或 concurrent=12 的真实结果；必须冻结案例和环境，并显式确认付费运行 |
| `python -m benchmarks.product_baseline compare ...` | 对人工评分后的同 repetition 串并发结果执行质量门禁，无网络调用 |
| `python -m benchmarks.run_baseline --health-check` | 检索路由与 Tavily 连通性，会消耗 Tavily 额度；不检查 LLM，也不证明研究完成 |
| `/api/v1/tasks/*` | 当前产品路径；真实基线须经此入口采集任务、报告、HITL 和 observability |
| `python -m benchmarks.run_baseline --legacy-direct ...` | 保留的历史直连实验，不经过 durable RunContext，不能用于新产品基线；会调用付费 LLM 与 judge |
| `locust -f benchmarks/locustfile.py` | 只读 health/docs/durable 查询负载，不创建研究、不衡量报告质量或研究吞吐 |
| `.github/workflows/benchmark.yml` | 手动离线 smoke；已移除旧付费 runner 和固定 Top-1 门槛 |

O1 的 12 例及[官方参考依据](../docs/o1-reference-audit.md)已获用户批准冻结为 1.0.0，48-run 额度已确认。
正式实验进度及主机风险见[执行断点](../docs/o1-execution-status.md)。候选状态、未通过检索健康或 LLM 兼容检查时，采集器会在
任何研究调用前停止。LLM 检查需覆盖 JSON、工具调用与实际使用的 thinking 配置；全量测试不
代替此项。

隔离实验服务使用独立产品/检查点数据库；知识库与 learned-docs 快照必须显式指定，不能复用
日常写入目录冒充冷启动：

```powershell
$env:DEEPCHOICE_EXPERIMENT_DIR = "outputs/product-baseline-v1/serial-r1-runtime"
$env:CHROMA_PATH = "<只读知识库快照路径>"
$env:LEARNED_DOCS_PATH = "<learned-docs 快照路径>"
$env:LEARNED_DOCS_READONLY = "1"
.\.venv\Scripts\python.exe -m uvicorn benchmarks.product_baseline_server:create_app --factory --workers 1
```

另一个终端先校验候选集。人工核验并将案例标为 `frozen`、填写私有环境 manifest 且两项健康
检查为 `passed`、确认 48-run 上限后，才可添加最后一行的显式执行开关：

```powershell
.\.venv\Scripts\python.exe -m benchmarks.product_baseline validate
.\.venv\Scripts\python.exe -m benchmarks.product_baseline collect --profile serial --concurrency 1 --repetition 1 --environment-file <环境清单.json> --output-dir outputs/product-baseline-v1/serial-r1 --execute-paid-runs
.\.venv\Scripts\python.exe -m benchmarks.product_baseline collect --profile concurrent --concurrency 12 --repetition 1 --environment-file <环境清单.json> --output-dir outputs/product-baseline-v1/concurrent-r1 --execute-paid-runs
.\.venv\Scripts\python.exe -m benchmarks.product_baseline compare --serial-dir outputs/product-baseline-v1/serial-r1 --concurrent-dir outputs/product-baseline-v1/concurrent-r1 --output outputs/product-baseline-v1/concurrency-r1.json
```

每次 profile 使用新的 `*-runtime` 数据库目录和单独的新采集输出目录。`scores.csv` 必须先完成
人工盲评，比较命令才会运行。

`admissions.jsonl` 在 POST 前及确认创建后立即保存并 fsync；重启先核对它，未写完的 run 不能
自动重建。`usage.csv` 逐 case 导出已知 token/完整性与调用数；未知为空，不是零。报告和 snapshot
分别存入 development / holdout 子目录；保留集在候选锁定前不查看。比较需同环境 hash、代码提交、
数据集 hash 和配对 manifest，评分必须绑定实验/run 并有 reviewer/evidence_notes；缺报告不判通过。

以下探测不创建研究任务，输出目录必须为新文件；routes 仅做 credential-free 路由检查，
不能替代上述包含 Tavily POST 的完整检索 health-check：

```powershell
.\.venv\Scripts\python.exe -m benchmarks.product_baseline_preflight --mode routes --output <路由检查.json>
.\.venv\Scripts\python.exe -m benchmarks.product_baseline_preflight --output <模型检查.json> --execute-paid-probes
```
第二次 repetition 使用 `serial-r2` / `concurrent-r2`；两次均通过才算并发效果门禁通过。

## 有意使用历史直连工具

仅在明确批准历史实验及调用额度后，使用项目 Python 3.11/3.12 环境：

```powershell
.\.venv\Scripts\python.exe -m benchmarks.run_baseline --legacy-direct --output-dir outputs\legacy-experiment-UNIQUE --cases-file benchmarks\annotated_cases.json --cases 1
```

`--output-dir` 必须不存在；每次创建新目录，拒绝覆盖之前结果。CLI 在任何探测和研究调用前
检查模式与目录。程序级 `run_single_case/run_baseline/merge_all_batches` 保留给已知旧调用方，
不是自动安全门；新消费者不得使用它们。新生成的原始条目/报告标记 `legacy-direct-graph`。
不要将旧 runner 的成功率、缓存/预算表现、token 汇总当作 durable 测量：失败运行的用量可能
不完整，合并还可能重新调用 judge；新测量必须使用公开观测字段，未知量不得填零。

`--profile-agents` 仅保留参数兼容，节点计时本已开启。`--debug-dump-dir` 输出脱敏 hash、
长度和用量，不输出完整 Prompt/响应；case/tag 的目录文件名使用 hash，不能由 case 文本越界。
诊断目录同样必须不存在，避免覆盖历史记录；runner 的 verbose 进度只输出案例 hash 和 query 长度。
上述参数名保持兼容，但帮助文本已纠正。

## 停用但保留定位的旧入口

已批准的 O1 私有实验可用 `product_baseline_experiment prepare --root <新实验目录> --llm-evidence <探测证据.json> --execute-paid-health-check`
制作同一知识种子和四份初始副本；它保存依赖/健康/非敏感环境清单，不复制 `.env`。`serve --root <实验目录> --profile serial-r1`
在生产模块导入前设置独立知识与数据库路径，离线预热已有 BGE-M3 缓存后启动单 worker。
每个 profile 只能从空 runtime 启动；已有数据必须核对，不能直接重新 serve 冒充新实验。

- `run_all_batches.ps1`：原先会删除批次结果，现仅说明停用并非零退出。
- `run_batch_comparison.sh`：原先绑定个人 Python 路径、吞失败并复制 latest 文件，现同样停用。
- `generate_200_cases.py`：原先导入即覆盖数据并继承跨场景答案；现导入无副作用、CLI 停用。
- `merge_checkpoints.py` CLI 与 `run_baseline --merge`：固定历史文件/案例假设、偏向成功重试、
  且可能调用付费 judge，现拒绝运行。合并实现保留审计，不作为当前指标口径。

旧实现可从 Git 历史恢复，未删除任何案例文件或已有运行结果。历史 300-case（2026-08-31）
和 Qwen adaptation 数字均保持原记录；在新代码/模型上重跑旧问题会产生新实验，不能重现当时数字。
