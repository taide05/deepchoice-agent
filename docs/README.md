# 项目文档入口与效力

更新：2026-10-11。用户当前指令优先；当前代码、manifest 构建器、`pyproject.toml`
和可执行测试描述已实现行为。旧十小时与八小时计划均已结案，后者内容未达标；
下一轮的工时、外呼额度和题集尚未冻结。旧执行卡、聊天交接和 OPEN 字段
不授权新运行。[接手复盘](agent-development-lessons.md)已按当前及归档的 18 个项目会话复核，
并记录前次遗漏的 Codex worktree 会话。

| 顺序 | 文档 | 职责 |
|---|---|---|
| 1 | [AGENTS.md](../AGENTS.md) | 全仓 Git、工程、安全和减法优先硬约束 |
| 2 | [接手约束与 Codex 复盘](agent-development-lessons.md) | 跨会话教训、下一轮开场顺序、冲突处理 |
| 3 | [质量路线](current-roadmap.md) | 产品目标、范围、优先级 |
| 4 | [评估协议](product-effectiveness-optimization.md) | 内容语义判定、全新题集与广度边界 |
| 5 | [推进与维修](optimization-execution.md) | 问题批次、验证节奏、失败处理 |
| 6 | [当前状态](o1-execution-status.md) | 工程与内容事实、研究账本、未达标项 |
| 按需 | [运行契约](phase1-runtime-contract.md) | 生命周期、预算、引用、安全、HITL、恢复 |
| 按需 | [全仓审计与精简地图](codebase-audit.md) | 既有审计证据，须核对当前代码 |
| 历史 | [归档索引](archive/README.md) | 旧计划、协议和冻结证据 |

主产品是一条完整 durable 研究链路。Codex 时期所有题目和报告仅供历史取证；
新额度内每个修复包完成后只用一份独立准备的全新题报告检查效果；旧工程套件通过不代表报告可用，
也不代表已经完成人工 UI 验收。最终 24 次仍封存。README 负责用户使用说明，
CHANGELOG 记录交付；原始输出和本地交接留在忽略区，不作为公开文档。
只针对具体问题查阅归档，不递归加载旧计划或用其“下一步”覆盖当前状态。
