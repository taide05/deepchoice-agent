# 评测工具使用说明

> 2026-10-25：本目录工具属于已放弃的durable路线；不是恢复树的必选评测入口。
> 见[纠偏交接](../docs/next-session-product-optimization-handoff.md)，按用户与dsh当前方案选择工具。

更新：2026-10-24。开发反馈、公开测量和历史复算用途不同。旧四例锁、逐阶段批准、失败根禁续、
最终 24 格预留、固定双评和原生思考单独准入规则已移出本页，见 [历史原文](../docs/archive/retired-contracts-20261024/README.md)。
它们不控制新开发。实际工具仍有代码检查，变更范围时修改工具与对应测试，不假填准入状态。

## 选择入口

| 入口 | 用途和当前状态 |
|---|---|
| `final_batch.py` | durable 批次数据检查、采集、恢复计划、评审汇总及授权账本 |
| `product_baseline.py` | durable 采集基础；名称不表示共享证据的单次综合 baseline 已实现 |
| `prepare_final_batch.py` / `final-batch-v1.json` | 旧 120+12 草案工具；参考未核验，不是现成正式集 |
| `run_offline_eval` | smoke-v1 的固定输入回放，不调用模型/网络 |
| `report_quality.py` 等旧结构指标 | 结构诊断，不替代用户报告的内容判断 |
| 旧 quality-* / optimization-* 工具及数据 | 可查实现或复用素材；各自冻结参数、旧准入根不代表新路线 |

小规模开发不要求先准备 132 题、实现完整 baseline、获得 11/12 或建立全量人工评分。
可以复用已暴露失败题、固定输入和轻量采集器；按当前委托连续调试、复测，保留版本和失败。
大批次工具若不适合开发规模，可简化/适配，不必复制其全部历史流程。

## 现有 final_batch 的离线命令

以下命令不派发研究（路径按实际材料替换）：

```powershell
.\.venv\Scripts\python.exe -m benchmarks.final_batch validate --dataset <dataset.json>
.\.venv\Scripts\python.exe -m benchmarks.final_batch resume-plan --dataset <dataset.json> --output-dir <batch-dir>
.\.venv\Scripts\python.exe -m benchmarks.final_batch summarize --dataset <dataset.json> --output-dir <batch-dir> --reviews <reviews.csv>
```

`validate` 当前检查旧 120 final + 12 calibration 结构及配额；通过不等于参考正确或内容可用。
`--require-admitted` 还检查准入状态。`summarize` 使用实际报告绑定和评审分母；合成样例不算成绩。
`resume-plan` 只规划，不替代未知提交的产品侧对账。

## 使用实际采集时

`collect` 需要 dataset、output-dir、api-base、arm 和显式执行开关；授权通过
`--authorization-id`、`--authorization-ledger`、`--authorization-cap`、`--authorization-prior-used` 传入。
具体参数以 `python -m benchmarks.final_batch collect --help` 为准。
当前只支持 candidate；baseline 参数存在但未实现完整两臂路径，不应靠标签声称公平比较。

- 同一授权的 ledger 放在批次输出目录外，跨新目录、进程重启和 experiment ID 继续累计。
- `--authorization-prior-used` 表示该授权已经发生的用量，不因目录变更填零；另起授权由用户决定。
- 不确定是否提交成功时，使用 `ledger-status`、产品 task/events 和 `reconcile` 查清已有任务；
  不先释放槽位重派。已有 terminal 结果按记录复用。
- 内容不足、单源失败或普通解析错误是开发反馈，不是默认禁止下一例的流程条件。
  预算耗尽、提交身份不明和数据/安全故障按实际问题处理；每 run 限额与批次限额分别记账。
- HITL 可以在方案中约定 provide_context、limited_report 或取消的处理，无需每例等 Codex。
  执行仍使用公开 decision API，不能直接改生命周期表冒充完成。

当前数据、账本和候选状态见 [交接](../docs/next-session-product-optimization-handoff.md)。本页命令说明不是新的付费授权。

## 以报告反馈改进

内容判断以回答核心取舍、依据适用、限制清楚为主；有用的条件建议可以按该用途评价。
不因补充项缺失、没有唯一赢家、没有 exact-reference URL 或词法 unknown 自动判整份失败。
明确事实错误、重要遗漏和推荐前提缺失仍如实记录。开发可以抽看，公开全量评审时才声称全量。

比较方案时记录 case、版本、证据/模型差异和用量，避免把共享检索重复计费；不同条件的比较
可以作为探索结果，注明差异即可，不要求所有开发实验都先达到正式公平配对规格。
更完整的方法见 [评估说明](../docs/product-effectiveness-optimization.md)。

## 离线 smoke 和历史指标

```powershell
.\.venv\Scripts\python.exe -m benchmarks.run_offline_eval --check-baseline
```

smoke 的 12 例仅验证确定性路径；预期行为有意变化时可以核对后更新 baseline，不能只为消除
失败覆盖结果。历史 300-case 及各 quality 数据集保留原日期、版本和结论，不混成当前产品成绩。
历史文档中的付费命令按当前代码和当前额度选择使用，不批量执行。
