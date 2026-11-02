# G1 行为验证结果（评审修复后，2026-11-02）

> 16 例 G1 行为集：覆盖 C2 partial 先例、生命周期遗漏、转述强化、台账卫生、未解析引用、self-review 契约失败，加 1 例既有 DG 对照。
> 主运行 13 例 + 台账卫生补充运行 3 例，共 **16/16 已评审**（补充运行见 §11）。
> 与冻结 200 同一 case 的对照是**信息性**的（不同运行、不同时间、模型非确定性），不作受控提升声明。

## 1. 运行身份

- 主运行目录：`.scratch\cases\runs\g1-review-fixes-20261102-retry1`
- 补充运行目录：`.scratch\cases\runs\g1-ledger-20261102`（3 例台账卫生组，196,450 tokens，git `1b6a3e7`）
- cases：`.scratch\cases\cases_g1_review_fixes_20261102.json`（sha256 `2cf552d848c7be07…`）
- git：主运行 `7ab55e4c6`；concurrency 2；硬 token 上限 900000 / 补充 230000
- 时间：主运行 2026-11-02T10:08:08Z → 10:36:56Z；补充 2026-11-02T11:58:24Z → 12:06:05Z
- 结果：主 13/16 完成（3 跳过）；补充 3/3 完成；G1 合计记录 tokens **1,176,528**

## 2. 成本与产出

- 主运行 13 例：**980,078** tokens，p50 70,766/例；wall p50 206s / p95 510s
- 补充运行 3 例：**196,450** tokens，p50 64,457/例；wall p50 215s
- 已评审：**16/16**

## 3. 内容评审（C1–C4，合计 16 例）

| 指标 | 结果 |
|---|---:|
| C1 met | 16/16 |
| C2 met / partial / no | 15 / 1 / 0 |
| C3 met / partial / no | 15 / 1 / 0 |
| C4 计次 / C4 case | 0 / 0 |
| usable | **16/16** |
| DG | **14/16** |

非 DG case：
- F200-041：C2 partial（NestJS 自有托管平台 vs ASP.NET Core 自托管步骤的比较基础不对称，未计入 Azure App Service 托管路径；与冻结基线一致，非回归）。
- F200-190（补充运行）：C3 partial（报告称 Pulumi 官方 import/许可文档"本批缺失"，但所引 Pulumi 对比页正文含 "Import existing resources: pulumi import…"、Apache-2.0 等；属 gap 准确性缺陷，非 C4，报告以"未验证"口径表述）。


## 4. 评审暴露缺陷的可见计数（修复后新报告，16 例合计）

| 检查 | 计数 |
|---|---:|
| 未解析引用标记 | 0 |
| 自审注记泄漏 | 0 |
| 模板计数句（另有 N 个…） | 0 |
| 置信度 label/正文矛盾 case | 0 |
| 尚未可知来源标签恢复 | 122 |
| 参考来源重复 | 0 |
| 裸 deep-documentation 标签 | 0 |

## 5. self-review 契约（R8）

- 主运行 review_attempts：{"F200-001": 2, "F200-041": 1, "F200-042": 2, "F200-049": 1, "F200-053": 1, "F200-056": 1, "F200-060": 1, "F200-130": 1, "F200-142": 1, "F200-151": 1, "F200-164": 1, "F200-165": 1, "F200-186": 1}；补充运行 3 例均为 1
- unavailable：无
- 触发一次重试并成功的 case：F200-001, F200-042

## 6. 与冻结 200 的逐例对照（信息性）

| case | 旧→新 decision | 旧 C2/DG | 新 C2/DG | review_attempts | gaps | official 页 | tokens |
|---|---|---|---|---|---:|---:|---:|
| F200-001 | conditional→conditional | met/True | met/True | 2 | 0 | 3 | 99539 |
| F200-041 | conditional→conditional | partial/False | partial/False | 1 | 0 | 5 | 59718 |
| F200-042 | conditional→conditional | met/True | met/True | 2 | 0 | 5 | 85343 |
| F200-049 | insufficient_evidence→insufficient_evidence | met/True | met/True | 1 | 0 | 3 | 57912 |
| F200-053 | conditional→conditional | met/True | met/True | 1 | 0 | 4 | 99734 |
| F200-056 | conditional→conditional | met/True | met/True | 1 | 0 | 4 | 65266 |
| F200-060 | conditional→conditional | partial/False | met/True ↑ | 1 | 0 | 6 | 86724 |
| F200-130 | conditional→conditional | partial/False | met/True ↑ | 1 | 0 | 2 | 60284 |
| F200-142 | conditional→conditional | met/True | met/True | 1 | 0 | 3 | 70766 |
| F200-151 | conditional→conditional | met/True | met/True | 1 | 0 | 3 | 92207 |
| F200-164 | conditional→conditional | met/True | met/True | 1 | 0 | 6 | 55561 |
| F200-165 | conditional→conditional | met/True | met/True | 1 | 0 | 4 | 69622 |
| F200-186 | conditional→conditional | met/True | met/True | 1 | 0 | 6 | 77402 |
| F200-187 | conditional→conditional | met/True | met/True | 1 | 0 | 6 | 64457 |
| F200-190 | conditional→conditional | met/True | met/False ↓（C3 partial） | 1 | 0 | 5 | 76318 |
| F200-199 | recommended→recommended | met/True | met/True | 1 | 0 | 2 | 55675 |

## 7. 结论边界

- 16 例是行为验证集，不是正式 200；本轮结果不替代、也不迁移冻结 200 的正式指标。
- 新旧对照不是受控实验：运行时间、检索结果、模型非确定性不同；PG 变化只作方向性参考。
- 正式指标仍需修复收敛后的新 200（新预算/窗口/新运行目录）。

## 8. 评审记录的残留缺陷（G1 观察）

已在本轮之后**确定性修复**（代码 + 测试；未参与本批 G1 报告生成）：

1. 决策摘要「关键缺口」引用被截断成悬空片段（F200-049/053/056/165 出现 `[Source: Airflow vs.` 类断口）
   → `_summary_excerpt` 增加未闭合引用/链接标记裁剪。
2. F200-151 正文泄漏内部提示词规则号（"rule 25"）→ 合成 prompt 新增规则 27（禁止在报告中提规则号/
   prompt/内部字段名），自审 prompt 增加内部元数据泄漏检查项。
3. guard 强度校准措辞过度（F200-001/042/060 被写成"缺少非厂商、独立或一手正文支撑"，但这些 top option
   其实有 first-party 官方正文，真实缺口是缺独立对照）→ 改为"决定性比较主要依赖其自有材料或二手来源，
   缺少独立的非厂商对照"。

待处理（内容级，需下一轮行为验证或更强规则）：

- **F200-041 仍 C2 partial**：与冻结基线完全一致（比较基础不对称：NestJS 自有托管平台 vs ASP.NET Core
  自托管步骤，未计入 Azure App Service 托管路径）；另其"已声明排除"的 AWS blog/SO/示例 repo 仍计入
  "实际引用了 14 个来源"（台账卫生 R5 残留）。
- F200-060 轻微模态强化（"必须使用 client-generated timestamp" vs 源文 "as general guidance, make sure to use"）。
- F200-186 正文写"结论本身证据充分（high）"而 label=medium（输入 confidence_rationale 原文如此；
  当前置信度对齐规则只处理"最终定级"句式，未覆盖此表述）。
- F200-165 证据摘要把两个不同 dagster.io URL 说成"同一 URL"却分别计数（模型表述错误，非渲染）。
- F200-142/151 含"强度校准/排序已降级"自指元注释（guard 文本嵌入建议段，口吻偏内部）。
- F200-164 在 conflict_count=0 时仍保留"未参与冲突比较"模板句（事实正确但冗余）。
- R5 台账卫生：主 13 例中仅 F200-041 复现；**补充 3 例台账全部 CLEAN**（187/190/199），
  prompt 规则 26 方向有效；F200-041 的残留（排除来源仍计入引用）可评估渲染层过滤。
- **F200-190（补充运行，C3 partial）**：gap 准确性——报告称 Pulumi 官方 import/许可文档
  "本批缺失"，但所引 Pulumi 对比页正文含 "Import existing resources: pulumi import…" 与
  Apache-2.0 许可；需 prompt/自审增强"缺口陈述须与已引正文对照"。
- F200-187 nits："其余 11 条检索结果"应为 10（同文折叠导致差 1）；迁移文档 label 路径与 URL 略不一致。
- F200-199 nits：Kaniko 维护状态表述超出源文（"仅 Chainguard 分叉维护"；NomadX 称社区分叉维持
  maintenance mode，报告自己的导航块还列了 osscontainertools/kaniko）；"未参与冲突比较"模板句与
  no_candidate_pairs 冲突块并存。

## 9. 与修复前基线对照（信息性）

- 主 13 例：DG 旧 **10/13**（F200-041/060/130 为 C2 partial）→ 新 **12/13**（仅 F200-041）；
  **+2 改善、0 回归**。
- 补充 3 例：旧 **3/3 DG** → 新 **2/3**（F200-190 C3 partial：gap 准确性；非受控对照，
  可能是运行间差异，需按同口径复核）。
- 合计 16 例：旧 13/16 → 新 **14/16**。方向性结论，不作受控提升声明。
- 7 类确定性缺陷在 16 份新报告中全部为 0（未解析引用/自审注记/模板计数/置信度矛盾/裸 deep-doc
  标签/参考重复），来源标签恢复 122 处。
- self-review 契约：主 13 例旧基线中 F200-049/053 为 `unavailable`；新运行 **16/16 completed**，
  主运行 2 例（F200-001/042）第一次契约不合法后经一次重试成功 → R8 方向有效（样本小）。
- 成本：主 13 例 811,881 → 980,078 tokens（**+20.7%**），补充 3 例 196,450；其中自审重试
  约 +6–7 万，其余为运行间差异与内容长度变化。

## 10. 未覆盖与待批

- 正式 200：按主运行 75.4k/例估算 200 例 ≈ **15.1M tokens**（旧 run 12.7M），需新预算审批；
  旧 200 指标不迁移到新代码（用户决定：先只做 R7/R9 优化，不重开 200）。
- R7/R9 已零成本实施（见 `R7_R9_IMPLEMENTATION_20261102.md`），但其真实行为效果尚未经过付费运行验证
  （本次 3 例补充运行在这些改动之前启动）。
- 残留内容缺陷见 §8；F200-190 的 C3 partial（gap 准确性）为补充运行新发现，可作为后续 prompt/自审增强输入。

## 11. 台账卫生补充运行（`g1-ledger-20261102`，3 例）

- 运行：3/3 完成、**196,450 tokens**（git `1b6a3e7`，硬上限 230,000，concurrency 2）。
- 评审：**usable 3/3、DG 2/3、C4=0**；确定性缺陷计数 0（未解析引用/自审注记/模板计数/置信度矛盾/
  参考重复/裸 deep-doc 标签），来源标签恢复 21 处；self-review 3/3 completed（无重试）。
- 台账卫生结论（R5）：
  - **F200-187 CLEAN**：11 declared = 11 listed = 11 distinct articles；同文别名折叠、无关巴西 "Ruff"
    燃料卡已排除且不入账；仅 nit："其余 11 条"应为 10、迁移文档 label 与 URL 路径略不一致。
  - **F200-190 CLEAN（台账）**：7 declared = 7 listed = 7 distinct；AL2 release-notes、无正文 CDK 页、
    aws/aws-cdk 与两篇 Pulumi 教程均被排除且未入账；但 **C3 partial**：报告称 Pulumi 官方
    import/许可文档"本批缺失"，而所引 Pulumi 对比页正文含 import 说明与 Apache-2.0 许可
    （gap 准确性缺陷，非 C4）。
  - **F200-199 CLEANEST**：8 declared = 8 listed = 8 distinct；无关 Crossplane/ArgoCD 文章未引用；
    6 条无正文链接隔离在导航块，20 = 8 + 12 对账一致；残留 nit：对 Kaniko 维护状态的
    "仅 Chainguard 分叉维护"表述超出源文（NomadX 说社区分叉维持 maintenance mode）、
    "未参与冲突比较"模板句与 no_candidate_pairs 冲突块并存。
- 结论：**R5 台账卫生在 3/3 例均清洁**，prompt 规则 26 方向有效；剩余问题是 gap 准确性/表述强化类
  内容缺陷（F200-190、F200-199 nits），不是引用台账结构问题。



