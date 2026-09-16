# 评估入口与历史工具

更新：2026-09-16。正式产品效果协议见 [产品效果优化](../docs/product-effectiveness-optimization.md)，
准备检查结果见 [基线准备检查](../docs/baseline-readiness-audit.md)。

| 入口 | 用途和边界 |
|---|---|
| `python -m benchmarks.run_offline_eval --check-baseline` | 固定 smoke-v1 的 12 例，无 LLM/网络；只验证确定性路径 |
| `python -m benchmarks.run_baseline --health-check` | 检索路由与 Tavily 连通性，会消耗 Tavily 额度；不检查 LLM，也不证明研究完成 |
| `/api/v1/tasks/*` | 当前产品路径；真实基线须经此入口采集任务、报告、HITL 和 observability |
| `python -m benchmarks.run_baseline --legacy-direct ...` | 保留的历史直连实验，不经过 durable RunContext，不能用于新产品基线；会调用付费 LLM 与 judge |
| `locust -f benchmarks/locustfile.py` | 只读 health/docs/durable 查询负载，不创建研究、不衡量报告质量或研究吞吐 |
| `.github/workflows/benchmark.yml` | 手动离线 smoke；已移除旧付费 runner 和固定 Top-1 门槛 |

本轮尚未实现 O1 的 durable API 批量采集器和冻结真实案例，不能宣布“真实基线已就绪”。
下一步按协议实现采集、冻结案例/版本/评分依据并确认额度，再执行检索及 LLM 小额兼容检查。
LLM 检查需覆盖 JSON、工具调用与实际使用的 thinking 配置；全量测试不代替此项。

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

- `run_all_batches.ps1`：原先会删除批次结果，现仅说明停用并非零退出。
- `run_batch_comparison.sh`：原先绑定个人 Python 路径、吞失败并复制 latest 文件，现同样停用。
- `generate_200_cases.py`：原先导入即覆盖数据并继承跨场景答案；现导入无副作用、CLI 停用。
- `merge_checkpoints.py` CLI 与 `run_baseline --merge`：固定历史文件/案例假设、偏向成功重试、
  且可能调用付费 judge，现拒绝运行。合并实现保留审计，不作为当前指标口径。

旧实现可从 Git 历史恢复，未删除任何案例文件或已有运行结果。历史 300-case（2026-08-31）
和 Qwen adaptation 数字均保持原记录；在新代码/模型上重跑旧问题会产生新实验，不能重现当时数字。
