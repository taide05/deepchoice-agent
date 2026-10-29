# Community 弱引用分析与 C2 修复（2026-10-29）

> 基于 20 份开发反馈报告的完整审阅与逐案对照；20 例仍是开发集，不用于最终验收。

## 1. 结论摘要

- C4：**0/20**；usable：20/20；DG：8/20。
- 20 例中 16 例有 community pack（共 32 个），**25/32 pack 被报告使用，7 个未被采用**。
- 社区引用**没有**被当成官方文档/共识；问题集中在：
  1. **C2 partial（12/20）**：决定性事实只有单一二手/厂商来源、社区证据承担决定性判断、引用未解析；
  2. **弱 community 引用**：相关性低/只作噪声/与选型维度错位；
  3. 呈现问题：社区来源缺少统一“非官方”标注、空 thread、同 URL 重复等。

## 2. 弱引用的具体类型

| 类型 | 20 例中的表现 | 是否错误 |
|---|---|---|
| 有 pack 但未引用 | F200-006（React Native/无回答路由帖）、F200-158（Keycloak token/JWT 帖） | 非错误；但未说明是“相关度低”还是“遗漏” |
| 引用但相关性低 | F200-136（RPM 指标含义）、F200-155（n8n+Qdrant 安装） | 非 C4；对结论贡献弱 |
| 被列为“噪声”却计入引用 | F200-075：正文称该 SO 帖“无支撑作用”，Why 清单仍计 ×1 且无社区/非官方标注 | 引用口径不一致 |
| 形式相关、推断偏强 | F200-097：用 Jenkins crumb 提问中的 `services.igor` 配置推 Spinnaker 架构；报告已注明组件数未取证 | 非 C4；推断强度偏高 |
| 相关性高、使用正确 | F200-198（Buildah 权限前提）、F200-124（AMQP/JMS 语义）、F200-172（dbt 版本漂移）、F200-104（迁移排障） | 正确 |

## 3. 根因分析（代码/链路层）

### 3.1 查询层：candidate-only 搜索太宽

- `build_query_variants` 现在每个候选单独查一次 Stack Overflow，维度和子问题词只用于**排序**，不进入查询；
- 因此会返回大量“候选名碰巧出现、但问题维度不匹配”的 thread：
  - F200-006：`React Native` 命中候选 `React`；
  - F200-136：`RPM` 指标含义与 observability 选型无关；
  - F200-155：n8n + Qdrant 安装问题与 pgvector/Qdrant 审计选型无关。
- 每个 case 只有最多 2 次搜索（一候选一次），没有额外的维度查询预算。

### 3.2 候选选择：只看 title/tags + answer 元数据

- `score_candidate` 的相关性来自 title/tags 的候选/维度词命中；正文只有在抓取后才会看到；
- 排序权重给 answer score/answer_count/accepted 较高位置，因此“高回答数的泛化帖”可能压过“回答少但正好回答子问题的帖”；
- 抓取详情后，v1 原本没有“正文是否真的回答子问题”的门槛；本轮只加了“无 answer 且无 comment 的空 thread”过滤；
- 结果：候选名匹配但主题错位的 pack 可以进入证据链。

### 3.3 来源评分：relevance 不进入 evidence-chain 门槛

- `source_evaluator` 使用 authority/timeliness/consistency/verifiability；
- 社区 authority 从 5 提到 6 后，弱 pack 也可能跨过 4.0 门槛；
- **community 选择阶段的相关性分数没有传到 source score/evidence chain**，因此“选进来”和“值得作为证据”之间没有二次质量门槛。

### 3.4 综合/报告层：缺少 C2 与社区 P2 规则

- 之前的 synthesis 只有通用 `SOURCE INDEPENDENCE`，没有明确：
  - 单一厂商/二手/社区来源不能支撑决定性比较；
  - community 是实践者经验（P2），不能作为单一决定性依据；
- 于是模型可能把弱社区帖放进证据摘要，或不说明弃用原因；
- 本轮已补：
  - synthesis `EVIDENCE APPLICABILITY (C2)`；
  - synthesis `COMMUNITY EVIDENCE IS PRACTITIONER EVIDENCE (P2)`；
  - self-review check 1 增加 applicability/community 限制。

### 3.5 呈现层问题（不是 C4）

- 社区 source list 未统一标注“社区问答/非官方”（已修）；
- 空 thread pack（已修）；
- 同 URL 在不同通道以不同 title 出现、引用数字未解析、来源计数不一致：属于通用渲染修复，
  按用户要求放到下一阶段。

## 4. 已实施的修复

1. **C2 prompt/self-review**
   - 单一 vendor/secondary/community 来源不能作为决定性比较依据；
   - 社区证据仅作实践经验，需标注、不可单独决定胜负；
   - self-review 对不满足的 ranking 要求改条件/撤回。
2. **社区 pack 质量**
   - 丢弃无 answer 且无 comment 的空 thread；
   - 保留 candidate/dimension 选择逻辑（不硬调权重）。
3. **可靠性**
   - channel/request 3 次有界重试。
4. **呈现**
   - 社区来源标注“（社区问答/非官方）”。

## 5. 明确不做的过拟合调整

- 不因 20 例中某个弱帖就加产品/案例黑名单；
- 不凭 20 例调 relevance/quality 权重的具体数值；
- 不把“没有 community 引用”当错误；
- 不在同一 20 例上验证新权重后宣称泛化。

## 6. 后续计划

- 用独立批次/最终 200 观察 C2 规则和重试的实际效果；
- 下一阶段再做通用渲染修复（同 URL 去重、引用编号、来源计数）；
- 需要更多数据后再决定是否加“正文级相关性门槛”（候选+子问题词在 answer/comment 中的命中），
  不在本开发集上硬调。

## 7. 10 例 C2 验证后的更新（2026-10-29）

- 10 个 C2 partial 案例复跑：C4=0/10，C2 实质改善 9/10，F200-058 基本不变，无 C2 变差；
  详见 `C2_VALIDATION_20261029.md`；
- 弱 community 引用仍有披露型残留（F200-144 Gemini、F200-136 RPM、F200-073 CronJob），
  但已不作为决定性依据；
- 已追加 synthesis 规则 **`OMIT IRRELEVANT COMMUNITY MATERIAL`（规则 21）**：
  只有直接回答声明的子问题或具体实施坑点的 community pack 才引用/列入 basis；
  通用问答、定义/explainer、无关安装问题、平台泛化帖不进入报告；
- 仍**不**按 20 例硬调权重/阈值，也不加案例黑名单；该规则需要在最终/独立样本中验证。

## 8. 通用渲染修复（后置）

以下问题不在本文件修复范围，按用户要求放到 C2/弱引用之后：

- 同 URL 在 tavily/community 不同标题下重复；
- 引用编号未解析；
- 来源计数/参考清单一致性；
- 官方来源标签粒度。

## 9. 独立 6 例验证（2026-10-29，非 20 例开发集）

- 样本：F200-001（Svelte/Vue）、F200-021（ASP.NET/Spring）、F200-049（CockroachDB/Yugabyte）、
  F200-137（MLflow/W&B）、F200-177（Poetry/uv）、F200-117（Pulsar/Redpanda）；
- 6/6 complete，约 13 分钟，371,661 tokens；
- community：4/6 success、2/6 failed（F200-001 per-case budget exhausted，F200-021 TimeoutError）；
- 有 pack 的 4 例均被报告引用；引用内容与具体子问题/迁移/兼容性/版本/运维坑点相关，
  未出现“泛化定义/无关安装”型弱引用；引用均标“（社区问答/非官方）”；
- raw `[[N]]`=0、引用未解析=0（引用根因修复生效）；
- 结论：**不需要进一步增加 community 引用数量/覆盖**；当前更值得加强的是
  通道可靠性（2/6 失败）和结果质量，而不是扩大引用面。

## 10. 引用未解析根因修复

见 `C2_CITATION_FIX_20261029.md`：两个根因（正文引用被误判为数组索引；
`unresolved_questions` 自由文本未参与 citation pass）已修复，新独立报告 0 残余。

