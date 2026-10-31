# 交付材料索引 / Delivery Materials Index（2026-10-31）

> 内部材料索引。最终 200 结果仍为 2026-10-30 冻结版本。
> 外部发布材料尚未创建，需用户确认口径。

## 1. 最终 200（冻结）

| 项 | 内容 |
|---|---|
| 题集 | `.scratch/cases/cases_formal_200.json` |
| SHA-256 | `46728f209aa12760afa39e0467b1c6c8fae1b0dac130b20e76ff1810031e3807` |
| 运行 | `.scratch/cases/runs/final-200-20261029/` |
| 结果 | [FINAL_200_RESULT_20261029.md](FINAL_200_RESULT_20261029.md) |
| 指标 | usable 200/200、DG 185/200、C4=0 |
| tokens | 12,646,242 |
| wall | p50 221.2s / p95 415.1s |

运行身份：

- 主批 HEAD `95d8bea`；
- 5 个替换（1 invalid + 4 citation）；
- 后 4 个替换使用 citation title 修复工作树（later committed `14b6f69`）；
- learned_docs SHA `de28babb...b70930`。

## 2. 阶段文档

### Phase A

- [PHASE_A_ROOT_CAUSES_20261030.md](PHASE_A_ROOT_CAUSES_20261030.md)
- 账本/契约/标签/batch health；结构性部分完成。

### Phase B

- [PHASE_B_OFFICIAL_COVERAGE_20261030.md](PHASE_B_OFFICIAL_COVERAGE_20261030.md)
- [PHASE_B_G1_RESULT_20261030.md](PHASE_B_G1_RESULT_20261030.md)
- 26 例 G1：official 正文 86→96，usable 26/26、DG 25/26、C4=0。

### Phase C

- [PHASE_C_CLAIM_SUPPORT_20261030.md](PHASE_C_CLAIM_SUPPORT_20261030.md)
- [PHASE_C_G1_RESULT_20261030.md](PHASE_C_G1_RESULT_20261030.md)
- [PHASE_C_G1_12_RESULT_20261030.md](PHASE_C_G1_12_RESULT_20261030.md)
- [PHASE_C_G1_12_RETEST_RESULT_20261031.md](PHASE_C_G1_12_RETEST_RESULT_20261031.md)
- [PHASE_C_GUARD_VALIDATION_20261031.md](PHASE_C_GUARD_VALIDATION_20261031.md)
- 结构部分关闭：guard 验证 12 例 usable 12/12、DG 9/12、C4=0；
  3 个剩余 C2 partial 是真实证据缺口。

## 3. 方法与约束

- [VALIDATION_GATES_20261030.md](VALIDATION_GATES_20261030.md)
- [PROJECT_CLOSURE_20261031.md](PROJECT_CLOSURE_20261031.md)
- [FORMAL_ACCEPTANCE_PROTOCOL_20261028.md](FORMAL_ACCEPTANCE_PROTOCOL_20261028.md)
- [HANDOFF.md](HANDOFF.md)

关键口径：

- usable = C1 满足 && C4=0；
- DG = usable && C2 满足 && C3 满足；
- 200/200 全量评审，不抽样；
- C4/identity/fabrication 是硬错误；
- official 覆盖率是诊断，不是目标。

## 4. 成本与验证

| 项 | tokens |
|---|---:|
| 最终 200 | 12,646,242 |
| Phase B G1 | 1,581,480 |
| Phase C 验证（含失败 402 run、重试、2 例、12 例两轮、guard） | 约 5.29M |

## 5. 报告形态

- 新增“决策摘要”块（`what_why_how`），位于详细章节之前；
- 内容：状态/winner、建议、关键缺口、强度校准、置信度；
- 旧版平均报告 22,058 字符；加摘要后约 22,360 字符（+302，约 +1.4%）；
- 目的不是缩短，而是让读者能先读结论再决定是否深入证据；
- 离线审计 200 snapshot：无新增 raw/ledger 异常（仍为旧的 6 个方括号标题 artifact）。

## 6. 未整理/未发布

- 外部交付稿：未创建；默认不发布内部 provenance、替换、失败细节；
- 最终 200 之外的 Phase A/B/C 结果均为内部验证材料；
- 任何外部数字需用户确认口径。

## 7. 当前状态

- 无付费任务；
- 最终 200 冻结；
- 代码全量测试状态见最近提交；
- 下一批正式 200 是否开启由用户决定。
