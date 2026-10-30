# Phase B G1 结果（2026-10-30）

> 26 例开发集小规模行为验证；未跑最终 200。
> 目的：验证 Phase B 官方证据获取改动的覆盖/质量/成本。

## 1. 样本与运行

- 20 例 expanded 开发集 + 6 例 independent，合并 26 例；
- 输出：`.scratch/cases/runs/g1-phase-b-20261030/`；
- 代码 HEAD：`0b26700`；
- 模型 `deepseek-flash`，concurrency=2，`evidence_pack`，`LEARNED_DOCS_READONLY=1`；
- 运行时间：2026-10-30 12:41–13:28（约 47 分钟）；
- 26/26 complete。

## 2. 成本

| 项 | 结果 |
|---|---:|
| 原始批次 tokens | 1,581,480 |
| 替换后采用 tokens | **1,570,262** |
| 预算上限 | 2,000,000 |
| 相对旧 20+6 批次 | -5,637 tokens（基本持平） |

## 3. 官方正文覆盖

| 指标 | 旧 20+6 | G1 | 变化 |
|---|---:|---:|---:|
| official_doc 正文页总数 | 86 | **96** | **+10** |
| 26 例 | — | 96 | — |

明显改善：

- F200-183（Pydantic/msgspec）：0 → 5 页（msgspec.dev 新映射生效）；
- F200-077（OpenTofu/Terraform）：3 → 6 页（Terraform developer docs 映射生效）；
- F200-117（Kafka/Pulsar/Redpanda）：5 → 7 页；
- F200-006：2 → 3；
- F200-198：2 → 3。

少数回退（F200-107 6→5、F200-144 4→3）属于外部抓取波动，非系统性退化。

## 4. 内容评审

26/26 逐份 C1–C4 全量评审：

| 指标 | 结果 |
|---|---:|
| complete | 26/26 |
| usable | **26/26（100%）** |
| decision-grade | **25/26（96.2%）** |
| C4 关键错误 | **0/26** |
| C2 partial | 1/26（F200-001） |
| C3 partial | 0/26（替换后） |

唯一非 DG：F200-001（Pydantic/msgspec 的 C2 前提假设问题），C4=0，属内容校准限制，不是 C4。

## 5. 契约/health

- 原始批 health：8 ok / 17 warn / 1 invalid；
- invalid = F200-075：`malformed_unresolved_question`（输出截断），由 G1 契约门捕获；
- F200-075 已按替换流程重跑：
  - 替换后 usable/DG，C4=0，contract flags `[]`、ledger flags `[]`；
  - 原始 invalid 记录保留，替换 provenance 记在 `replacement-F200-075`。
- 替换后采用单位无 invalid；
- 仍有 17 个 warn，主要是 `source_concentration` / `source_identity_unverified` / 页面超时；
  这些是证据/来源结构诊断，不是 C4。

## 6. 结论

Phase B 首轮 bundle 通过 G1：

- 官方正文覆盖 **+10 页**，关键 msgspec/Terraform/CDK 类缺口改善；
- tokens 基本持平；
- usable 26/26、DG 25/26、C4=0；
- 契约门成功捕获 F200-075 截断并完成替换；
- 没有跑 200，也没有改最终 200 结果。

## 7. 下一步

按顺序进入 **Phase C：证据使用/claim support**：

- 决定性 claim 必须有可追溯来源；
- 单一二手/厂商来源不能支撑决定性结论；
- self-review 增加 claim-level C2 检查；
- 先实现零付费，再走 G1；不直接跑 200。

## 8. 产物

- 运行：`.scratch/cases/runs/g1-phase-b-20261030/`
- 评审：同目录 `reviews_merged.json`
- 原始/替换：`batch-*`、`replacement-F200-075/`
- 规范：`VALIDATION_GATES_20261030.md`
