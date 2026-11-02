# 最终 200 内容评审结果（2026-11-02）

> **内部验收材料，不对外发布。对外口径由用户另行确认。**
> 题集：`.scratch/cases/cases_formal_200.json`
> 题集 SHA-256：`46728f209aa12760afa39e0467b1c6c8fae1b0dac130b20e76ff1810031e3807`
> 本次只做只读内容评审与汇总：未重跑最终 200、未重新生成报告、未改代码/prompt/retrieval/guard。

## 1. 运行身份与冻结状态

- 运行目录：`.scratch/cases/runs/final-200-20261031b/`
- 分支/运行 HEAD：`precodex/deepseek-adapter` / `b4b9b0a`
- 评审时工作树 HEAD：`c33f2a0`；`b4b9b0a..c33f2a0` 仅 2 个 docs-only 提交（新增本 handoff 文档），产品代码/prompt/retrieval/guard/报告形态均未变。
- 最终 200 运行代码基线：`adecccb`（产品代码 `c8fad27`）
- 200/200 唯一 case 跑完，不重跑；本次评审只读。
- 3 个替换（必须披露，按 v1.1）：F200-058、F200-187、F200-126
- 最终 200 token：本次合计 **13,068,148**；累计 **14,344,100**；上限 15,000,000；剩余 655,900（约 95.6%，未超预算）。
- 评审输入：`review_map.json` + `review_inputs/F200-XXX.json`（200 份）。
- 评审文件：`reviews/chunk-01.json` … `chunk-20.json`（20 chunk × 10 例；chunk-15 于 2026-11-02 重跑，旧半成品归档于 `reviews/archive/chunk-15.partial.json`）。

## 2. 评审方法

- **全量 200/200，不抽样**；每个 case 读 `report.md` 全文 + 对应 compact review input（任务、final_recommendation、quality_signals、source 状态、冲突、citation bindings）。
- 不联网；不改 report/snapshot；只写 `reviews/chunk-NN.json`。
- 口径：
  - C1 核心回答：是否回答用户实际问题并给出可执行答案/条件；
  - C2 证据适用性：决定性主张是否有适当来源支撑；vendor-only / secondary-only 默认排序不能算已证实；`has_body=false` 只算导航/元数据，不算证据；
  - C3 条件/缺口：分支条件、反转条件、PoC 指引、不确定性与缺口是否写清；
  - C4 致命错误：编造、候选身份/归属错误、矛盾、无效状态、危险断言；
  - `usable = C1 met && C4 == 0`；`DG = usable && C2 met && C3 met`。
- 执行：chunk-01..14 于此前会话完成；本会话按「3 agent 并行 × 每轮 3 个 chunk（30 例）」完成剩余 chunk 15–20（两轮：15–17、18–20），每轮落盘后校验再继续；chunk-15 因上次会话崩溃只留下 4 条半成品，已整块重跑。
- 评审完成时间：2026-11-02；评审结果文件 20 个、合并后 200/200。

## 3. 正式指标（200/200）

### 完整性
- 200/200 报告单位齐全；200/200 全量内容评审完成；无缺失、无重复。

### 决策状态（本批 200 单位）

| 状态 | 数量 |
|---|---:|
| recommended（明确推荐） | 6 |
| conditional（条件选择） | 159 |
| insufficient_evidence（证据不足） | 35 |

置信度：low 134、medium 66。

### 内容评审（C1–C4）

| 指标 | 结果 |
|---|---:|
| C1 met | 200/200（100.0%） |
| C2 met | 197/200（98.5%） |
| C2 partial / no | 3 / 0 |
| C3 met | 200/200（100.0%） |
| C3 partial / no | 0 / 0 |
| C4 致命错误（计次） | **0** |
| C4>0 的 case | **0/200** |
| **usable（C1 满足且 C4=0）** | **200/200（100.0%）** |
| **decision-grade（usable 且 C2、C3 均满足）** | **197/200（98.5%）** |

## 4. 未达 DG / 不可用清单

- 不可用（C4>0 或 C1 未满足）：**0/200**（无）
- C4>0：**0**（无）
- C1 未满足（partial/no）：**0**（无）
- C2 partial（usable 但非 DG）：**3** — F200-041, F200-060, F200-130
- C3 未满足（partial/no）：**0**（无）
- 未达 DG 合计：**3/200**

未达 DG 的逐例问题（完整内容见 `review_aggregate.json`）：

| case | chunk | C1 | C2 | C3 | C4 | key_issue |
|---|---:|---|---|---|---:|---|
| F200-041 | 5 | met | partial | met | 0 | 决定性“运维更轻”排序证据不对称：NestJS 侧核心依据是其官方文档对自家托管平台 Mau 的宣传（单命令置备 server/DB/brokers），ASP.NET Core 侧按自托管步骤计，并称“材料未覆盖等价托管方案”——与其所引 host-and-deploy 正文（Publish to Azure/Azure App Service、反向代理可选）不符，削弱 NestJS #1 的比较基础（C2 partial，故非 DG）。 |
| F200-060 | 6 | met | partial | met | 0 | 决定性迁移机制（双写+客户端 writetime+forkflift+dual reads、迁移骨架 5 步）主要引自 ScyllaDB 官方迁移文档，但该源在 snapshot 中 has_body=false（仅 tavily snippet 摘要，official 抓取 has_body=False/verified=False），且报告自己在"导航链接（无正文，不能作为依据）"中列出同一 URL——导航型/无正文来源被当作核心证据，C2 partial（故非 DG）；另有 How 段置信度理由写 medium 与 low 矛盾（非致命，已记 C4_notes）。 |
| F200-130 | 13 | met | partial | met | 0 | #1 Jaeger 的分支依据之一（collector/query 分离可独立扩缩）来自 has_body=false 的 2.dev 架构页，报告却把它与 1.76 调优页并列为「官方正文」——实际官方正文是 1.76+Zipkin quickstart，属证据结构陈述不实（C2 partial，故非 DG）；另决定性前提「现有埋点库」未给出、Jaeger 迁移指南正文缺失，性能/迁移基准全无。 |

## 5. 证据与来源覆盖

### community 使用

| 状态 | 数量 |
|---|---:|
| cited | 166 |
| pack-unused | 32 |
| none | 2 |

### official 覆盖

- official 正文页（`batch summary official_body_pages`，official 通道逐 case）：**195/200 例 ≥1 页**；0 页 5 例（F200-030, F200-070, F200-071, F200-072, F200-088）；合计 743 页，p50 4 页/例。
- `review_inputs.official_body_results` 的构建口径是**全部检索源** `has_body` 合计（非 official 专属），合计 1116 条，仅作参考。
- official 检索状态（200 单位，按 case 计）：success 200。
- official 覆盖率是诊断信号，不是验收目标；0 页的 5 例在评审中仍按 C1–C4 如实评级（均 usable/DG，缺口已写入各自 key_issue/official_notes）。

### 批次 health 信号（评审外的运行侧诊断，仅作内容限制参考）

主 10 批（200 单位）：

| health 状态 | 数量 |
|---|---:|
| ok | 34 |
| warn | 163 |
| invalid | 3 |

- 3 个 invalid 即原 F200-058 / F200-187 / F200-126（均已按 v1.1 替换，替换后评审见 §6）。
- 替换目录（2 例）与 canary（1 次）：warn 4。

主要 issue 类型：

| issue 类型 | 次数 |
|---|---:|
| `report_quality:source_concentration` | 148 |
| `page_issue:official` | 78 |
| `report_claim_support:conditional_top_option_owner_dominates` | 61 |
| `report_claim_support:conditional_top_option_secondary_dominant` | 23 |
| `report_claim_support:conditional_no_primary` | 7 |
| `incomplete_output:recommendation_missing` | 3 |
| `incomplete_output:invalid_status` | 3 |
| `report_contract:no_ranked_options` | 3 |
| `report_contract:decision_validation_error` | 3 |
| `optional_source_failed:community` | 3 |
| `optional_source_failed:github` | 2 |
| `report_ledger:ledger_unlisted_sources` | 1 |

说明：`report_claim_support:conditional_top_option_owner_dominates / secondary_dominant / conditional_no_primary` 是运行侧告警，表示条件型结论的 top option 证据以 owner/二手为主；评审时按 C2 判断其是否被报告以强度校准/条件分支/缺口披露吸收，未自动等同 C4 或不可用。以上内容限制不因规则修补而消失。`incomplete_output:*` / `report_contract:*` 的计数均来自上述 3 个原 invalid 例（已替换）。

## 6. 替换披露

| case | 替换后 decision_status | C1 | C2 | C3 | C4 | usable | DG |
|---|---|---|---|---|---:|---|---|
| F200-058 | conditional | met | met | met | 0 | True | True |
| F200-187 | conditional | met | met | met | 0 | True | True |
| F200-126 | conditional | met | met | met | 0 | True | True |

原 invalid 报告保留在各自 batch 目录，未被覆盖；替换目录见 `replacements-01/02`。3 例替换均按同一 C1–C4 口径全量评审，结果见上表；本轮指标不另设替换/非替换分母。

## 7. 与上一轮最终 200（2026-10-29 运行）的对照（信息性，不作提升/下降声明）

| 指标 | 10/29 轮 | 本轮（10/31b） |
|---|---:|---:|
| 评审单位 | 200 | 200 |
| usable | 200/200 | 200/200（100.0%） |
| DG | 185/200（92.5%） | 197/200（98.5%） |
| C4 计次 | 0 | 0 |
| C2 met / partial / no | 185 / 15 / 0 | 197 / 3 / 0 |
| C3 met / partial / no | 199 / 1 / 0 | 200 / 0 / 0 |
| community cited / pack-unused / none | 169 / 28 / 3 | 166 / 32 / 2 |

> 上一轮（10/29 运行）评审口径不同（含 D1-D5），仅作信息对照，不作提升/下降声明。两轮是不同运行（题集相同但运行时间/代码身份/评审分块不同），本轮只报告自身正式指标，不据此宣称相对上一轮的提升或下降。

## 8. 结论边界

- 本轮完成的是**内部内容评审**：200/200 全量、C1–C4 口径、usable/DG 计算；
- C4>0 一律视为不可用，未静默忽略；C2/C3 partial 与不可用案例逐例保留，不用平均值掩盖；
- 未改报告、未重新生成、未重跑 batch、未改代码/prompt/retrieval/guard；
- 本次结果不外推为“对外投递标准”；是否对外交付、对外口径、是否与旧轮对照对外表述、是否继续改代码、是否优化报告形态或升级 DSH 核心，均需用户明确确认；
- 旧最终 200（`final-200-20261029`）保持不动、不覆盖。

## 9. 产物

- 评审文件：`.scratch/cases/runs/final-200-20261031b/reviews/chunk-01..20.json`
- 归档半成品：`.scratch/cases/runs/final-200-20261031b/reviews/archive/chunk-15.partial.json`
- 合并评审：`.scratch/cases/runs/final-200-20261031b/reviews_merged.json`
- 聚合指标：`.scratch/cases/runs/final-200-20261031b/review_aggregate.json`
- 评审输入：`.scratch/cases/runs/final-200-20261031b/review_inputs/`、`review_map.json`
- 合并/校验脚本：`.scratch/cases/merge_final_200_reviews_20261102.py`

