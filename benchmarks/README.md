# 评估工具入口

更新：2026-09-29。本页仅说明已实现工具。目标见[质量路线](../docs/current-roadmap.md)，
判据见[quality-selection-v1](../docs/product-effectiveness-optimization.md)，实际预算与结果见
[当前状态](../docs/o1-execution-status.md)。新协议的4+4案例清单和运行适配尚待Q0完成。

## 当前可复用能力

| 入口 | 用途与边界 |
|---|---|
| `python -m benchmarks.run_offline_eval --check-baseline` | smoke-v1固定12例，无模型/网络；只验证确定性路径 |
| `product_optimization_dev_requests.load_dev_requests` | 读取原P01/P04/P08冻结请求；不包含新协议的全部案例 |
| `python -m benchmarks.product_baseline validate` | 校验旧O1案例，不能当成新数据集已冻结 |
| `DurableBaselineCollector`及`/api/v1/tasks/*` | 已有durable研究采集与观测；复用前检查新矩阵、HITL、身份和分母兼容 |
| `python -m benchmarks.product_baseline_preflight` | 已有路由/LLM探测；会按所选模式外呼，不自动执行 |
| `python -m benchmarks.run_baseline --health-check` | 检索/Tavily检查，会消耗额度；不验证LLM或研究效果 |
| 官方source-capture/review/seed模块 | 已有来源保存、审核与种子工具；按原安全/身份契约复用，不把旧受审主题外推为通用证据 |
| `locust -f benchmarks/locustfile.py` | 只读端点负载；不是报告质量或研究吞吐验收 |

新路线先复用现有collector和数据结构；仅增加确有缺口的薄适配，不新增通用评估平台。
必须在首次外呼前检查新场景是否被旧case allowlist、旧停止规则或源hash锁定；有差异先
离线验收再执行，不能把新协议JSON直接交给旧CLI。不要声称不存在的新命令已经可用。

## 新批次执行约束

只走durable路径，串行、每批新目录和独立产品/检查点两库；显式绑定请求、候选/基线、
模型配置、知识种子和研究上限。报告、快照、准入、预算/Trace和只读评审结果保存在outputs。
原始.env、报告正文和trace不提交。研究中断先对账，不复用旧停止根。

用户已有范围内持续付费授权，执行开关是防误触措施，不产生每次重新询问的义务。
范围与预算未冻结时先准备；不得仅凭旧机器卡OPEN或剩余额度执行。复用兼容的前置结果，
不对每个小改动重做LLM/健康探测；具体调用上限与停止分类见质量协议。

## 历史工具与冻结文件

`product_optimization_serial_check_v1/v2/v3/v4`、`s1_qualification`、repair-pair、
PR2B及旧串并发compare的运行/阈值只绑定各自历史身份。保留代码和机器卡供审计/复算，
不直接作为新路线执行器。旧`--legacy-direct`绕过durable，不用于新产品质量结论。
旧12路并发和48格命令不再出现在默认运行说明中。

详细历史参数和使用条件见[旧工具指南](../docs/archive/quality-direction-20260929/benchmark-guide-history.md)。
旧数据/哈希/评分保持原义；本轮quality-selection-v1与300-case、smoke-v1和旧O1分母分开。
