# Community（StackExchange）检索方向：目标、地图与路线

> 状态：**设计探索阶段，不实现**。用户已确认方向；先明确目标/路线/地图，再讨论实现。
> 本文不改变现有链路，不引入新依赖，不发起付费研究运行。

## 1. 目标与非目标

### 目标

把 StackExchange/Stack Overflow 从“实际返回 0 条、不可引用”的源，改造成：

1. 能检索到与候选/场景相关的**问题、回答、评论**；
2. 能抽取并保存**可引用的正文/评论片段**，带作者、日期、分数、内容类型；
3. 报告能正确使用社区证据：作为实践者经验/坑点/版本提醒，而不是官方事实；
4. 在 StackExchange API 配额、单 IP 限流、backoff 下稳定运行；
5. 对现有六源链路**可回滚、默认不破坏**。

### 非目标

- 不要求每个 case 都强行引用社区源；没有高质量内容时允许“社区无可用证据”；
- 不把评论/单个回答当权威事实；
- 不替换 official/primary 证据；
- 不为了覆盖率抓取低质/无关帖子；
- 不重写整个检索/报告链路。

### 成功标准（单例验证与后续评估用）

- 单例：能抓到至少一条与候选/场景具体相关的 question/answer/comment 正文；
- 报告中的社区引用可定位到具体帖子/回答/评论，带作者/日期/分数；
- 未把社区观点写成官方事实，未把单条评论当共识；
- API 请求遵守 backoff/配额，单例不出现 429/超时失败；
- 现有其它源、默认报告格式和测试不回归。

## 2. 当前状态地图

### 2.1 代码入口

- `src/deepchoice/retrievers/community.py`
  - `CommunitySearch(BaseRetriever)`，source = `community`；
  - 当前请求：`GET https://api.stackexchange.com/2.3/search`，参数 `intitle=<150字 adapted query>`；
  - 返回 `has_body=False` 的元数据 `snippet = Score/Tags`；
  - 已有：进程内 `_SEARCH_SEM=1`、20s 排队超时、`_next_allowed` backoff、缺通道重试；
  - 读取 `STACKEXCHANGE_API_KEY`（用户已提供）。
- `src/deepchoice/retrievers/base.py`
  - `BaseRetriever.search()` 统一包装 status/results/error；
  - 异常会 invalidate outbound，再返回 `failed`。
- `src/deepchoice/agents/multi_retriever.py`
  - `RETRIEVER_REGISTRY` 将 6 个源并行检索；community 只是其中一个 channel；
  - 保存 `search_results`、`empty_sources`、`partial_failures`。
- `src/deepchoice/agents/evidence_chain.py`
  - 把有正文的来源转成 `evidence_chains[].sources[]`，字段包含 url/title/snippet/has_body/provenance/date 等；
  - 只有 `has_body=True` 的来源可进入综合引用。
- `conclusion_synthesizer.build_source_registry` / `formats/basis.py` / `what_why_how.py`
  - 以 URL/source_id 作为身份，生成编号来源与引用；报告按来源类型/日期显示。
- `batch_health.py` / `report_quality.py`
  - 健康门可见 source 失败；quality lint 检查 raw citation/泛化标题/来源集中。
- 测试：`tests/test_community_retry.py` 等；无真实网络测试。

### 2.2 实测现状

- 200 例正式批次：community `success` 200/200，但 **结果行 0、正文 0**；
- 30 例试点、6 例审计、4 例验证：同样 0 条；
- 即当前 community 不是“元数据-only 可导航”，而是**基本没有返回结果**；这是检索层问题，不是报告层问题。

### 2.3 StackExchange API 能力（探索性清单）

- `/2.3/search/advanced`：`q`、`title`、`tagged`、`site`、`sort`、`order`、`pagesize`；返回 question 元数据；
- `/2.3/questions/{ids}`：可带 `filter=withbody` 取问题正文；
- `/2.3/questions/{ids}/answers`：回答正文/分数/是否 accepted；
- `/2.3/questions/{ids}/comments` 或 `/answers/{ids}/comments`：评论正文/分数/日期；
- 响应含 `quota_remaining`、`backoff`；单 IP 同时只能一个请求；
- 需核实：`filter` 具体字段、评论 URL/anchor、favorite_count 等字段、是否需注册 app/key 权限；
- 用户已有 API key，但配额上限/日请求数需实测确认。

## 3. 设计空间与选定方向

### 选项

A. **只修查询 + 保持元数据**：成本低，但无法成为可引用证据；不满足目标。
B. **查询 + 候选筛选 + 抓 question/answer/comment 正文 + 报告标注**：成本较高，但能真正补上社区源；选定。
C. 换 Reddit/其他社区：用户认为 SE 更可信、通道更好；不选。

### 选定方向

**B：独立、可回滚的 StackExchange 证据包（evidence pack）方案。**

核心决策：**一个 question 生成一个“社区证据包”来源**，而不是让每个回答/评论都变成独立 citation source。
理由：

- 现有链路以 URL/source_id 为身份，多 answer/comment 独立来源会牵动 registry/引用/去重/报告版式；
- 一个 pack 保留 question URL 作为身份，不破坏现有引用模型；
- pack 正文按“问题 / 高价值回答 / 高价值评论”分段，报告引用 pack 时可说明来源类型；
- 如果后续证明需要逐条 answer/comment 引用，再作为第二阶段扩展，不在第一版引入。

## 4. 目标架构（六层）

### L1 查询规划 Query planner

- 输入：原问题、候选、sub_questions、约束、adapted queries；
- 生成 2–4 个短查询变体：
  - `候选A 候选B` + 关键维度词（审计/权限/迁移/性能等）；
  - Stack Overflow 标签（如 `[llamaindex]`/`[haystack]`，从候选/技术映射得到）；
  - 限制 `title`/`q` 长度，不再用 150 字自然语言塞 `intitle`；
- 查询计划写入日志，便于评估命中率。

### L2 API 客户端与限流

- 使用现有 `STACKEXCHANGE_API_KEY`；
- 全局单并发 `_SEARCH_SEM=1`（保留）；
- 尊重 `backoff` 和 `quota_remaining`；
- 429/5xx/timeout 指数退避重试（有限次数）；
- 配额预算：每 case 最多请求数、每批最多请求数、缓存相同 query；
- 不与其他源争用同一出口限流。

### L3 候选选择 Selector

输入 question 元数据；输出要抓正文的 question/answer/comment 集合。

评分维度（**相对排序，不做硬阈值**）：

- 相关性：候选/维度词在 title/tags/正文中的匹配 + 语义相似度（可用 embedding/BM25）；
- 答案质量：accepted answer、回答分数、回答数量、正文长度/具体性；
- 时效：creation/last_activity 与问题版本敏感性；旧帖对稳定概念可保留；
- 社区信号：question score、favorite_count、评论中版本/修复信息；
- 多样性/去重：避免同题转载、同一回答重复；
- 小众保护：低票但高相关、有 accepted/具体正文的帖子不能被简单票数/日期过滤掉；
- 选取 top K questions，每问题选 accepted + 最高分 1–2 个 answer、以及相关 comments。

### L4 内容抽取与证据包 Evidence pack

- 抓取 question body、answers body、comments body；
- 保留：question_id、answer_id/comment_id、title、url、author、score、is_accepted、creation_date、last_activity_date、tags、favorite_count；
- 截断/清洗 HTML，保留可引用段落；正文长度受预算限制；
- 组装 pack：
  - 标题 = question title；
  - URL = question link；
  - body = 结构化文本（问题上下文 / 回答 / 评论，含作者/日期/分数标签）；
  - `source_type=community`、`has_body=True`、`date`=最近活动/发布时间；
  - 额外字段：`community_question_id`、`answers_count`、`comments_count`、`selected_answer_ids`。

### L5 报告与证据使用策略

- 社区证据等级为 P2（具体、标注作者/日期/分数的实践者经验），不是 P1 官方事实；
- 用于：真实坑点、版本兼容、运维经验、社区共识/反例；
- 不用于：单一来源决定高合规/审计结论；与官方冲突时并列；
- 引用显示：来源类型 community + 日期 + 作者/分数（若版式支持）；
- 报告明确“社区观点，非官方确认”。

### L6 评估与可观测性

- 单例评估：抓到的 question/answer/comment 数量、正文有效性、报告引用是否正确标注；
- 批次指标：community 命中率、可用 pack 数、请求数/quota、429/backoff 次数、失败原因；
- 不把“有 community 引用”当作必须，只统计可用性和质量。

## 5. 非影响现有链路的策略

- 新逻辑放在独立模块（如 `retrievers/community_evidence.py` 或 `community_v2.py`），**不改现有默认行为**；
- 通过 env/feature flag 切换：`COMMUNITY_RETRIEVAL_MODE=legacy|evidence_pack`，默认 `legacy`；
- `CommunitySearch` 只做一层适配：flag 为 legacy 时完全走旧路径；flag 为 evidence_pack 时调用新模块；
- 不改变其它 5 个 retriever、evidence chain 字段语义、综合 prompt、报告默认格式；
- 新来源仍用同一个 source channel 名称 `community`，但结果行是 evidence pack；health/report 向下兼容；
- 保留旧测试；新测试只覆盖新模块和 flag 分支；真实单例验证放 scratch，不进单测。

## 6. 测试策略（按新规则）

- 单元：查询规划、评分/相对阈值/小众保护、评论筛选、日期/URL/身份、HTML 清洗；
- 契约：用保存的 StackExchange JSON fixture（search/questions/answers/comments）验证解析、quota/backoff、429/5xx 重试；不发真实网络；
- 集成：用 fake HTTP client + feature flag，验证 `CommunitySearch` 在 legacy/evidence_pack 两种模式下输出 shape 与 status；
- e2e：**只在必要时**做一条 flag-on 的单例真实报告验证，检查内容/引用；不把 200 例批跑当测试；
- 真实 API 单例验证：单独记录在 `.scratch/`，不属于 pytest。

## 7. 分阶段路线与决策门

| 阶段 | 产出 | 门 |
|---|---|---|
| 0 设计（本文件） | 目标/地图/契约 | 用户确认方向与数据契约 |
| 1 API 探索 | 真实 API 返回样本（question/answers/comments、quota/backoff），只读探测，不改链路 | 确认 endpoint/filter/URL 规则 |
| 2 独立模块 | query/selector/pack builder + fixtures/unit tests，未接入 | 单测通过，不触网 |
| 3 flag 集成 | legacy/evidence_pack 双路径；默认 legacy；集成测试 | 旧路径零回归 |
| 4 单例验证 | 一条真实 case + API key，检查抓取内容与报告引用 | 内容可引用、标注正确、无 429/超时 |
| 5 评估与决策 | 记录命中/质量/成本；决定是否默认启用/扩展 | 用户决定，不自动进最终 200 |

## 8. 待确认问题（进入实现前必须定）

1. **证据包粒度**：一个 question 一个 pack（推荐，最小影响）还是 answer/comment 独立来源？
2. **评论是否可独立引用**：作为 pack 内的“评论摘录”还是独立 citation？是否需要作者/分数展示？
3. **选择标准**：相关性/质量/时效的相对权重；小众保护阈值；每 case 最多抓几个 question/answer/comment。
4. **配额与预算**：每 case 最大 API 请求数、每批上限、缓存策略；key 的日配额实测。
5. **内容长度/截断**：question/answer/comment 正文的上限；如何避免报告被社区文本淹没。
6. **证据等级与报告措辞**：community 固定为 P2/经验证据；是否允许作为 conditional 分支依据。
7. **URL/归属**：question URL、answer/comment anchor、作者/日期/许可（CC BY-SA 归属）展示。
8. **适用范围**：所有 case 都尝试 community，还是按类别/技术触发；没有命中时如何披露。
9. **单例验证案例**：选哪个案例（需 StackOverflow 上有具体讨论），验证标准如何量化。
10. **回滚**：flag 默认 legacy；何时允许切默认，需要什么证据。

## 9. v1 设计决策（2026-10-28 用户确认后）

### 9.1 证据粒度：question-level evidence pack（选定）

- 一个 question 对应一个来源 pack，identity 仍用 question URL；
- pack 内部结构：问题正文 / 选中的 answer / 选中的 comment，每条带 author/score/date/type；
- 不把 answer/comment 各自注册为独立 citation source（v1），避免改动现有 source identity、
  registry、去重和报告版式；后续若证明需要逐条引用，再在第二阶段扩展；
- 报告引用 pack 时标 community/P2，并可在正文提及“社区回答/评论”而不冒充官方事实。

### 9.2 评论处理（选定）

- 评论是 pack 内的**结构化摘录**，保留 author/score/date；
- v1 不将单条评论作为独立 citation/共识；
- 评论只用于版本提醒、反例、实践坑点；与官方冲突时并列。

### 9.3 选择与请求预算（初始值，可调）

- 查询：最多 2 次搜索（首选短查询/标签；为空时换第二个变体）；
- 每 case：搜索最多 2 次 + 详情最多 3 次（questions/answers/comments 各 1 次批量请求），
  总 **≤6 次 API 请求**；
- 每 case 最多 2 个 question pack；每 pack：accepted/最高分 answers 最多 2 条、
  相关 comments 最多 6 条；正文截断在 pack 总长度约 12k 字符；
- 每批最多 **1,200 次** StackExchange 请求；`quota_remaining` 低于 500 时停止 community
  请求并标记 empty/warn，不硬撑；
- 缓存：进程内按 normalized query 缓存搜索结果，按 question_id 缓存 pack；同一批不重复请求；
- 全局单并发（现有 semaphore）+ backoff + 429/5xx/timeout 有限重试；不做并行 StackExchange 请求。

### 9.4 初始排序（相对排序，不做绝对阈值）

- 相关性 0.45 + 回答质量 0.30（accepted、answer score、answer 具体性）+ 时效/版本 0.15 +
  社区信号 0.10（question score、comments 中版本/修复信息）；Diversity/去重另做调整；
- 小众保护：高相关但低票、若有 accepted 或具体 answer/comment，仍进入候选，不能被票数/日期硬筛掉；
- 以上权重是 v1 默认，真实 API 样本与单例验证后再调，不预设为最终参数。

### 9.5 单例验证案例（探索结果）

选择 **F200-083（Cilium vs Calico）** 作为单例验证：

- StackExchange API 实际返回了候选问题，例如
  [AKS Network Policy Manager vs Azure Cilium Network Policies](https://stackoverflow.com/questions/79187626/aks-network-policy-manager-vs-azure-cilium-network-policies)
  （tags: cilium/kubernetes-networkpolicy/azure，question body 完整，comments 有 6 条实质技术讨论，
  其中包含对 Cilium 效率/限制/文档的对比）；
- 另有
  [Network Policy not enforced on Minikube Calico cluster](https://stackoverflow.com/questions/76762360/network-policy-not-enforced-on-minikube-calico-cluster)
  可作为“具体坑点/无答案帖子”的对照；
- 该案例与 Cilium/Calico 网络策略选型直接相关，且能同时检验 question body、answers（应抓取）、
  comments 的打包与报告引用；answers 端点在本次网页探测中一次失败，实施阶段用 API key 重试并确认；
- 备用：F200-144（LangGraph/AutoGen）或 F200-148（LlamaIndex/Haystack）。

## 10. 实现与单例验证结果（2026-10-28 晚）

### 10.1 API 探索

- 用现有 `STACKEXCHANGE_API_KEY` + 项目 outbound 实测：
  - `/search/advanced` 200，quota 9911/10000，返回问题元数据；
  - `/questions/{ids}?filter=withbody`、`/questions/{ids}/answers`、`/questions/{ids}/comments`
    均 200，正文/回答/评论 body 可取；
  - 单例 F200-083 的 question 79187626 有 1 个 accepted answer、6 条实质评论。
- 未在测试中使用真实网络/真实 key。

### 10.2 实现与默认开关

- 新增 `src/deepchoice/retrievers/community_evidence.py`：
  - 短查询规划（每个候选单独搜索，维度英文词作 fallback；不再用 150 字 intitle）；
  - 相对多因素选择（相关性/回答质量/时效/社区信号；无绝对票数/日期硬筛；小众保护；
    每个候选至少保留一个 pack，避免两边证据只来一边）；
  - question-level evidence pack（question + answers + comments，带 author/score/date/type 标注）；
  - 批量详情请求（一次 questions + 一次 answers + 一次 comments），每 case 请求 ≤6；
  - quota floor、单并发、backoff、429/5xx/timeout 重试、进程内 query/pack 缓存。
- `community.py` 加入 evidence_pack 分支；经三主题验证后，**默认已切为 `evidence_pack`**，
  `COMMUNITY_RETRIEVAL_MODE=legacy` 可即时回退旧路径；`run_batch.py` 默认同步为 evidence_pack。
- `source_evaluator` 将 StackOverflow authority 5→6，使带正文的社区 pack 能跨过
  evidence-chain 的 4.0 阈值（否则 3.9 分会被静默丢弃）。
- 新增 `tests/test_community_evidence.py`：查询规划、相对选择/候选均衡、pack 内容/标注、
  fake-client 契约、429 重试、默认/legacy 分支；无真实网络。
- 关键提交：`dc859b8`（模块+flag）、`41e8adf`（候选单独搜索/空源）、`7403b2b`（候选均衡）、
  `9581a70`（先搜完所有候选）、`1801437`（authority 阈值）。

### 10.3 单例与扩大验证

- 单例 F200-083（infra）：2 个 pack（2402/3209 字符），报告引用两个 Stack Overflow 帖，C4=0。
- 扩大验证共 3 个主题（F200-083 infra、F200-144 AI/ML、F200-107 CI/CD）：
  - F200-144：balanced packs（LangGraph + AutoGen），报告引用两个候选的社区证据；53,775 tokens；
  - F200-107：balanced packs（Drone + Tekton），报告引用 Tekton 社区问答并标注 Drone 旧帖局限；
    68,888 tokens；
  - 三例报告均无 C4、无 raw citation；健康警告仅来源集中/可选源瞬时失败，无 invalid。
- 验证过程中实际发现并修复了 3 个实现缺陷：
  1. 组合查询（如 `LangGraph AutoGen`）返回 0 → 改为每个候选单独查询；
  2. 只搜第一个候选/先胜者 → 改为搜完所有候选，并至少保留每候选一个 pack；
  3. 社区 pack 3.9 分低于 evidence-chain 4.0 阈值 → authority 调整后确认进入引用。
- 没有把单例/三主题结果外推为 200 结论；旧 200 基线 community 仍为 0 结果。

### 10.4 负担与限制

- 新增 API 请求：每 case 最多 2 次搜索 + 3 次批量详情（≤5 次）；无新增 LLM 调用。
- 新增上下文：每例 2 个 pack，约 1.4–3.5k 字符；F200-083 配对显示 prompt/input +1,934 tokens
  （+5.2%），但总 tokens 因模型输出长度波动并未单向上升（pack 63,240 vs legacy 78,019）。
- 延迟：pack 单例 155.8–334.1s，基线 185.8–275.9s；没有稳定变慢，网络/LLM 输出波动更大。
- 可靠性：20 例中有 4 例 community 外部失败（ReadTimeout/无 outbound），health 记为
  optional_source_failed，未 invalid；已在此基础上加 3 次有界重试（`b612f70`，仅基础设施重试，
  未改查询/评分），下一批验证；这是默认启用的主要风险。
- 一次性开发/验证成本：community 迭代累计约 **1.99M tokens**（0.78M 三主题迭代 + 1.21M 20 例），
  这是验证成本，不是每例固定负担。
- 限制：20 例仍只覆盖一次批跑；评论/回答的实际引用取决于综合模型；默认启用不等于
  全量可用性证明；最终 200 全量评审才是测量。

### 10.5 20 例扩大验证（2026-10-29 09:14–09:53，峰价窗口，用户允许）

- 固定种子分层抽样 20 例：12 类全覆盖；已做 3 例保留，新增 17 例；
- 默认 evidence_pack，concurrency=2；20/20 complete，wall 约 40 分钟；
- **community 命中**：16/20 有 evidence pack（80%）；4 例失败（1 个 ReadTimeout，3 个
  `no outbound channel available`；health 记为 optional_source_failed，未 invalid）；
- **报告引用**：14/20 报告实际出现 Stack Overflow 引用（70%）；raw citation 0、空括号 0；
- **token**：合计 1,212,857，同 20 例旧基线 1,020,580，+192,277（+18.8%）；中位 +6,403/例。
  该对比跨版本，不能全部归因于 community；单例配对 F200-083 的 prompt 增量只有 +1,934
  （+5.2%），差异主要来自模型输出/检索组合波动；
- **健康**：4/20 ok，16/20 warn；community 相关失败 4 例；其余 warn 为官方页/page_issue/
  来源集中/可选源失败，没有因 community 导致的 invalid；
- 结论：社区源**能稳定覆盖多数（80%）案例并进入报告（70%）**，但仍有 20% 外部失败；
  默认保留 evidence_pack，同时保留 legacy 回退；不把 20 例当作 200 成绩。

### 10.6 回退演练（零跑例）

- 回退演练只检查代码/env 分支，不跑任何研究 case；
- 设置 `COMMUNITY_RETRIEVAL_MODE=legacy` 后运行 legacy/community/retriever 测试：
  **40 passed**；旧路径可即时恢复；
- 没有为回退演练启动付费运行。

## 11. 当前状态

- v1 已实现并**默认启用 evidence_pack**，legacy 可回退；3 主题 + 20 例扩大验证完成（有上述限制）；
- 余额预检已加并验证；arXiv non-XML 重试已加；并发按用户要求为 2；
- 最终 200 未批准/未运行；社区源质量、token 负担需在最终全量评审中实测，不能把本轮
  3 主题/20 例验证当作最终成绩。
