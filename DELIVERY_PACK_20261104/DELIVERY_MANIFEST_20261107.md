# 最终交付清单（2026-11-07）

> 项目：DeepChoice 新代码正式 200 例研究管线（precodex/deepseek-adapter）
> 版本：候选最终版（第 5 轮抽检 + 第二复审通过，仅抽检验证口径）
> 性质声明：AI 辅助抽检/复审，非真人签字；样本不可外推全量 200；
> **不构成本项目的"最终验收通过"标记**；最终验收/发布由用户与真人层决定。

## 1. 最终口径

- 完成：200/200，gate PASS，invalid 0；
- C4=1/200（F200-174，已披露）· C2=true 179/200 · usable 199/200 · decision-grade 179/200；
- 累计付费：42,422,985 / 42,400,000（超 22,985 = 0.054%，已披露；亦披露对上一档 42.2M 的超支 222,985）；
- 冻结 v3：代码 `da99f23`，src_tree `a51a5bc4…`，902 tests passed；
- 修复 provenance：39 例 fix39 + F200-138 invalid 重跑 + 4 例 fix4last（同案例、无替换）。

## 2. 验证链

1. 内部全量 200 + 独立复核 200（v1.2.4 严格）→ 发现口径漂移；
2. v1.2.5 校准（C4 二次裁决 83→39；C2 重评）→ usable 161、DG 146；
3. 解冻加规则 47–48 修复 39 例；规则 49 修复最后 4 例；v1.2.6/1.2.7 两层复评 + 裁决 → C4=1；
4. 第 5 轮第三层独立抽检（DSH 新会话）：首次不通过（C2 记录/文档 blocker R1/R2 等）→ 修复 → 第二复审通过，blockers=[]。

## 3. 披露清单（必须随交付一起提供）

- F200-174 为已知 C4=1（翻转条件与分支门控不一致），已披露；
- 未被两层标记的 161 例沿用 v1.2.5 校准（默认无 C4），残余风险未消除；
- 抽检样本（修复 10 例 + 新抽 10 例）不可外推全量 200；
- AI 辅助抽检 ≠ 真人签字；旧冻结批（`final-200-20261031b`）指标未混用；
- 预算超支 22,985 tokens 已披露。

## 4. 关键文件（SHA-256）

| 文件 | SHA-256 |
|---|---|
| `FINAL200_FINAL_RESULT_20261107.md` | `5a9f6c074b3a7d46fda870fcea80b51366b337724477aacc36de55a6e8c66d3e` |
| `CALIBRATION_RESULT_20261106.md` | `3ec7154d4a065a3f19d6d3da2469369f64ebb56b4c20f1dce943377e0796d278` |
| `FREEZE_20261107.md` | `ea660eed4133e56875ee608fe533d8a9e298988448675ed0c0df4df8c99cc78c` |
| `FREEZE_MANIFEST_20261107.json` | `a39f9905de6fe0ac8a02f4ab402473e6638748a6b8a034667f4d8decdf5a0246` |
| `BUDGET_LEDGER_20261107.md` | `aea84185608b0800661b9d9929b009c4de43eea0a8825b2348858438b575b641` |
| `ROUND5_REVIEW_RESULT_20261107.md` | `fd372b9af669c6b81bfe3a57273d8d2180bb941da382bb359d804eba4173b57c` |
| `ROUND5_RECHECK2_RESULT_20261107.md` | `820695d5af48c0cfafb015fb7689c9d7aeba46b2d92dfbaacddae2927b7bbc6c` |
| `POST_RECHECK_NOTES_20261107.md` | `15967d7131441730aee05c8ab57bb920ee5b312049b43c39626bea04d2bb934c` |
| `PROTOCOL_V12_DRAFT_20261103.md` | `443a8e50d2e78a11fbf13f5a4ddae567bf83ddbb0274ca26b1d9a1f156477323` |
| `INDEPENDENT_REVIEW_CARD_20261104.md` | `30a5f8c174fe034b9e07e615f7eabf80d3ce6b9bddf8adba44e97ce312a5303c` |
| `AI_SPOT_CHECK_LAYER3_20261104.md` | `f03ef971475aa2feb9e175ed092244097c20506852a9ab2a265eb65619de46cc` |

## 4.1 内部完整性自检

- `FINAL_INTEGRITY_CHECK_20261108.md`：18 项内部检查全部通过（快照/指标/冻结哈希/预算台账/跨文档一致性/修复 SHA/provenance/包副本/审查归档）。

## 5. 运行产物

- 最终批次：`.scratch/cases/runs/final-200-finalcode-20261106`（200 例报告 + review_final_200.json + provenance）；
- 修复批：`final-200-fix39-20261106`、`final-200-fix4last-20261107`、`final-200-invalid-rerun138-20261106`；
- 交付包：`DELIVERY_PACK_20261104/`（旧文件已在 `SUPERSEDED.md` 标注，仅供历史）。

## 6. 不可声明项

- 不得写成"最终验收通过"、"真人签字/盲审"、"全量零缺陷"、"样本代表全量"；
- 如需正式发布，建议由真人抽查并签署验收记录后再发布。
