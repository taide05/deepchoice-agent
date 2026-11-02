# 两次最终 200 全量评审的对照（2026-11-02）

> 内部对照材料。**不是受控实验**：两轮是不同运行（代码身份/时间/替换/评审口径不同），
> 数字只作信息对照，不据此声明提升或下降。

## 1. 运行身份

| 项 | 10/29 轮（A） | 10/31b 轮（B，本轮） |
|---|---|---|
| 运行目录 | `.scratch/cases/runs/final-200-20261029/` | `.scratch/cases/runs/final-200-20261031b/` |
| 运行 HEAD | `95d8bea`（+ 4 例引用修复工作树） | `adecccb`（产品代码 `c8fad27`） |
| 主题集 | 200 例固定题集 | 同一 200 例固定题集 |
| 替换 | 5 例：F200-076, F200-051, F200-068, F200-094, F200-130 | 3 例：F200-058, F200-187, F200-126 |
| 采用 tokens | 12,646,242 | 12,693,425 |
| wall p50 / p95 | 221.2s / 415.1s | 211.8s / 345.0s |

本轮 B 的 provenance：10 个主批 `batch_meta.json` 齐全；主批 commit 前缀 5ef3cb971, 71de2b41a, adecccbb7, dbe5bd965（各批之间仅有 docs-only 提交，产品代码未变；`source_dirty=false`）；替换/canary 批 commit=adecccbb7；learned_docs SHA 前缀 de28babb021e；运行窗口 2026-10-31T09:35:38.908889+00:00 → 2026-11-01T05:01:30.573016+00:00。

## 2. 决策状态与置信度

| 状态 | A | B |
|---|---:|---:|
| recommended | 6 | 6 |
| conditional | 149 | 159 |
| insufficient_evidence | 45 | 35 |
| invalid | 0 | 0 |

置信度：A = low 139 / medium 61；B = low 134 / medium 66。

## 3. 内容评审（C1–C4）

| 指标 | A | B |
|---|---|---|
| C1 met | 200/200 | 200/200 |
| C2 met / partial / no | 185 / 15 / 0 | 197 / 3 / 0 |
| C3 met / partial / no | 199 / 1 / 0 | 200 / 0 / 0 |
| C4 计次 | 0 | 0 |
| usable | 200/200 | 200/200 |
| DG | 185/200（92.5%） | 197/200（98.5%） |
| community cited / pack-unused / none | 169 / 28 / 3 | 166 / 32 / 2 |

## 4. 逐例变化（方向性信息，不是因果）

- DG：A→B 升（14 例）：F200-028, F200-047, F200-051, F200-120, F200-158, F200-164, F200-173, F200-181, F200-182, F200-184, F200-189, F200-191, F200-193, F200-197
- DG：A→B 降（2 例）：F200-041, F200-060
- 两轮均非 DG：F200-130
- 两轮均 DG：183 例

C2 变化分桶：

| 变化 | 例数 | case |
|---|---:|---|
| met->met | 183 | （略） |
| met->partial | 2 | F200-041, F200-060 |
| partial->met | 14 | F200-028, F200-047, F200-051, F200-120, F200-158, F200-164, F200-173, F200-181, F200-182, F200-184, F200-189, F200-191, F200-193, F200-197 |
| partial->partial | 1 | F200-130 |

决策状态发生变化：46 例（conditional→insufficient_evidence：14 例；insufficient_evidence→conditional：24 例；recommended→conditional：4 例；conditional→recommended：4 例）。

其中 recommended ↔ conditional 的变化（与 Phase C decision guard / claim-support 相关）：

| case | A 状态 | B 状态 |
|---|---|---|
| F200-039 | recommended | conditional |
| F200-079 | conditional | recommended |
| F200-095 | recommended | conditional |
| F200-143 | recommended | conditional |
| F200-177 | conditional | recommended |
| F200-197 | conditional | recommended |
| F200-198 | recommended | conditional |
| F200-199 | conditional | recommended |

| case | A 状态 | B 状态 |
|---|---|---|
| F200-007 | conditional | insufficient_evidence |
| F200-008 | insufficient_evidence | conditional |
| F200-012 | insufficient_evidence | conditional |
| F200-015 | insufficient_evidence | conditional |
| F200-019 | insufficient_evidence | conditional |
| F200-020 | insufficient_evidence | conditional |
| F200-031 | insufficient_evidence | conditional |
| F200-032 | insufficient_evidence | conditional |
| F200-035 | insufficient_evidence | conditional |
| F200-039 | recommended | conditional |
| F200-043 | conditional | insufficient_evidence |
| F200-046 | insufficient_evidence | conditional |
| F200-049 | conditional | insufficient_evidence |
| F200-052 | conditional | insufficient_evidence |
| F200-055 | conditional | insufficient_evidence |
| F200-060 | insufficient_evidence | conditional |
| F200-072 | insufficient_evidence | conditional |
| F200-079 | conditional | recommended |
| F200-092 | conditional | insufficient_evidence |
| F200-095 | recommended | conditional |
| F200-100 | insufficient_evidence | conditional |
| F200-107 | insufficient_evidence | conditional |
| F200-108 | insufficient_evidence | conditional |
| F200-111 | insufficient_evidence | conditional |
| F200-116 | insufficient_evidence | conditional |
| F200-119 | conditional | insufficient_evidence |
| F200-120 | conditional | insufficient_evidence |
| F200-123 | conditional | insufficient_evidence |
| F200-127 | conditional | insufficient_evidence |
| F200-128 | conditional | insufficient_evidence |
| F200-131 | insufficient_evidence | conditional |
| F200-143 | recommended | conditional |
| F200-147 | insufficient_evidence | conditional |
| F200-148 | conditional | insufficient_evidence |
| F200-152 | conditional | insufficient_evidence |
| F200-163 | conditional | insufficient_evidence |
| F200-164 | insufficient_evidence | conditional |
| F200-168 | insufficient_evidence | conditional |
| F200-175 | insufficient_evidence | conditional |
| F200-177 | conditional | recommended |
| F200-179 | insufficient_evidence | conditional |
| F200-192 | insufficient_evidence | conditional |
| F200-196 | insufficient_evidence | conditional |
| F200-197 | conditional | recommended |
| F200-198 | recommended | conditional |
| F200-199 | conditional | recommended |

## 5. 报告长度（“报告过长” backlog 的量化）

| 项 | A | B |
|---|---:|---:|
| 字符数 p50 | 21,860 | 23,242 |
| 字符数 p95 | 30,286 | 31,054 |
| 字符数 mean | 22,157.3 | 23,252.8 |
| 最小 / 最大 | 10,798 / 37,635 | 13,510 / 37,729 |

逐例变化：中位数 +1,227.0 字符；变长 121 例、变短 79 例、不变 0 例。

## 6. 怎么读这份对照（限制）

1. 两轮不是受控实验：A 轮代码 `95d8bea`、B 轮 `adecccb`（含 Phase A/B/C 与引用/claim-support 修复），
   且运行时间、替换、模型非确定性都不同；差异不能归因给某一个改动。
2. 两轮评审批次与口径也不完全相同：A 轮评审逐例另含 D1–D5 诊断；B 轮按 2026-11-02 handoff 只做 C1–C4
   （usable/DG 公式相同），且 B 轮为 20 chunk × 10 例、A 轮为 40 chunk × 5 例。
3. 共同事实是较稳的信号：两轮 C4 均为 0，usable 均 200/200；B 轮 DG 更高但**不宣称提升**。
4. 对外/投递材料默认只引用一轮的数字，避免把两次运行混成“提升证据”；如需对照需用户确认口径。

## 7. 产物

- 本对照：`FINAL_200_ROUND_COMPARISON_20261102.md`
- 机器可读：`.scratch/cases/runs/final-200-20261031b/round_comparison_20261102.json`
- A 轮结果：`FINAL_200_RESULT_20261029.md`；B 轮结果：`FINAL_200_REVIEW_RESULT_20261102.md`

