# Phase C G1 结果（2026-10-30）

> 26 例开发集验证；未跑最终 200。
> 第一次运行因 LLM 余额 402 中断，重试一次；本文件记录重试结果。

## 1. 运行与成本

- 代码 HEAD：`cbb2079`（Phase C 初版）
- 第一次运行：26/26 complete，但 9 个 invalid，日志为
  `402 Insufficient Balance`；成本 **1,224,581 tokens**，数据受污染，不作为结果；
- 余额恢复后完整重试：`g1-phase-c-20261030-retry1`；
  - 26/26 complete
  - tokens **1,604,605**
  - health：8 ok / 18 warn / 0 invalid
  - official 正文页：**100**
- G1 总消耗（失败 + 重试）：**2,829,186 tokens**，超出原 2.0M 上限；
  超支原因是第一次运行的平台余额故障，不是代码/预算估计错误。

## 2. 内容指标

| 指标 | Phase B G1 | Phase C G1 |
|---|---:|---:|
| usable | 26/26 | **26/26** |
| decision-grade | 25/26 | **24/26** |
| C4 | 0 | **0** |
| C2 partial | 1 | **2** |
| C3 partial | 0 | 0 |
| official 正文页 | 96 | 100 |

Phase C G1 非 DG：

- F200-076：条件 hold，但 #1 Nomad 排序依赖同一篇 NetApp 厂商对比页的
  EN/zh 两个 URL + 博客译文；
- F200-117：26 例中唯一 `recommended`，决定性比较主要依赖 Redpanda 自家文档
  与 2017–2020 Pulsar 二手材料，缺独立/当前一手支撑，应降为 conditional/PoC。

## 3. 结论

Phase C 第一版 **未通过 G1 质量目标**：

- usable/C4 没退化，但 DG 从 25→24；
- claim-support 审计没有拦住 F200-117，因为把 winner 自己的 official docs
  也当成普通 `primary`，没有识别“winner-owned source 占比过高”；
- 另外 F200-076 暴露出“同一厂商 EN/zh 双 URL 被误当两个独立来源”。

这说明 Phase C 需要补一轮，而不是关闭。

## 4. G1 后已做的零付费修复

- `claim_support` 增加 `source_owner` 统计与
  `recommended_winner_owner_dominates`：
  winner 自有来源在决定性字段中显著多于非 winner primary 时告警；
- self-review 输入明确要求：出现该 flag 时，检查是否有非 winner 独立来源；
  没有则不能保留 recommended，需 conditional/PoC 或 hold；
- 新增测试；全量测试状态见提交记录。

## 5. 当前判断

- Phase B：已闭环；
- Phase C：**尚未闭环**；需要做一次针对性 G1 重测（26 例，约 1.6M tokens），
  或先只测 F200-117/076 两个代表 case 再决定；
- 不建议直接进入最终 200；
- 未跑 200。

## 6. 定向 2 例验证（2026-10-30）

用户批准后运行 F200-117、F200-076：

- 输出：`.scratch/cases/runs/phase-c-targeted-2-20261030/`
- 2/2 complete，health 0 invalid，tokens **121,141**
- Phase C 验证累计 tokens：1,224,581（失败）+ 1,604,605（重试）+ 121,141 = **2,950,327**
- 内容评审：
  - F200-117：由 `recommended` 变为 `conditional`，C1/C2/C3 met、C4=0、usable/DG；
  - F200-076：`insufficient_evidence` hold，C1/C2/C3 met、C4=0、usable/DG；
  - 两例均无 C4。
- 因果归因 caveat：
  - F200-117 本轮 synthesis 已先写成 conditional，不能单独归因于 owner-dominance 修复；
  - F200-076 本轮 NetApp EN/zh 双 URL 未出现，部分是检索数据差异；
  - 只能说明“定向样本未复现原缺陷”，不能证明修复已完全生效。

## 7. 下一步

- Phase C 仍需一次 26 例 G1 复测（约 1.6M tokens）才能判断是否闭环；
- 不直接进最终 200；
- 当前没有付费任务在跑。

