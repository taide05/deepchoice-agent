# 评测工具与材料交接

更新：2026-10-24。本页是可复用资源清单，不是必须按序通过的准备流程。
当前产品代码为 `fef61b8`；后续任务由用户与 dsh 安排。

## 已有入口

- 产品：`POST /api/v1/tasks`，任务/events/decision、report/snapshot/observability、annotated及导出。
- `benchmarks/final_batch.py`：数据校验、采集、resume、评审导入汇总；现有授权账本按当前CLI使用。
- `benchmarks/product_baseline.py`：durable采集基础；名称不等于共享证据的简单综合基线已完成。
- `benchmarks/prepare_final_batch.py`、`benchmarks/final-batch-v1.json`：旧132题草案生成与校验。
- 本地开发、校准、正式草案及失败材料位置见 [交接](next-session-product-optimization-handoff.md)。

现有 final_batch 的120+12、配额和准入检查是具体工具行为，文档修改不会解除它们。
dsh 可按新方案调整这些工具和相关测试，或复用轻量采集入口；不必为了小规模开发强行补齐旧整批矩阵。
不通过伪造 eval_ready、预算或评分状态绕过实际检查。

## 尚需按方案取舍的工作

- durable共享证据、单次综合baseline仍没有正式完整比较结果，实验树旧实现不能当作已集成。
- 132题参考仍标prepared_unverified，不能宣称已经核验或封存。需要正式未见成绩时才完成对应样本的参考与隔离。
- 旧合成汇总样例不是项目成绩；可以复用schema，但实际汇总使用真实报告和评分。
- 未知提交、resume身份与review/report对应，在使用相应工具时核对。不要因此先建设通用评测平台。

## 时间和额度

不沿用旧312/320次、24次开发子额度、48/72小时或“下一阶段自动授权”。
本轮交接没有新外呼；后续可由用户一次给定开发与测量总预算，dsh在范围内自主分配，无需逐例批准。
授权账本按同一授权累计，历史超限不抹去。

旧 §7.8 及全部准备提案保存在 `git show fef61b8:docs/final-batch-preparation.md`。
这里不再给用户和dsh预设下一轮数、最终截止或强制阶段门。
