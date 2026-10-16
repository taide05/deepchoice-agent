# 修复包记录：收敛判断位置、修正关键理由

固定输入：任务 `8049500c-bd39-44e4-81bb-a1fbbebac780` 的已保存材料。
**原报告未手改**。冻结：**`73bc80c1bb5f35b7959c644904f1b15c96f8eaac`**
（`66db028` → **`73bc80c`**）。

---

## 一、保留的有效修复（含持久回归）

**`confidence_rationale` 的引用绑定与消毒** —— 此前被提示词要求引用，却不在
`_CITATION_TEXT_FIELDS` 中，于是既不绑定也不消毒，报告正文留下 `[[16]] [[17]] [[22]]`。
已保留，并补**持久回归**：
- `test_every_citing_field_is_bound`
- `test_prompt_fields_all_appear_in_the_binding_lists`（提示词要求引用的字段必须都进入绑定表，
  否则同类缺陷会以别的字段名复发）
- `test_bound_markers_are_converted_and_unknown_ones_dropped`
- `test_the_saved_run_no_longer_keeps_raw_markers`（用本次失败材料回放）

---

## 二、停止扩展页面主语猜测（已撤销）

`d3f8551` 为判断"页面在讲谁"新增了**词表**（`_LEADING_STOP`、`_QUALIFIER`）、
**标题前缀规则**（`subject_tokens` 取标题前三词 + host）与**最长名字兜底**（`identity_phrase`），
还加了正文必须提到候选的要求（`_mentioned_in_body`）。

**全部撤销**（`candidate_identity.py` 回到 `d3f8551^` 的内容）。撤回理由与用户判断一致：
页面可以讨论多个产品，**不能强迫整页只有一个"主人"**；词面相关只能作线索。

**防复发回归**：`test_no_subject_guessing_helpers` 断言这些名字不再存在；
`test_attribution_is_name_based_only` 断言归属只按名称。

**用新提交保留历史**：`d3f8551` 与其撤销都在历史中，**未做 reset**。

---

## 三、收拢候选说明与推荐的数据来源

**收敛前**：渲染器自己建"来源 → 候选"映射（`index_sources_by_candidate` +
`candidate_for_source`），合成器另有一套 `ranked_options`。**两处判断同一件事**，
所以 What 与推荐可以互相矛盾。

**收敛后**：What 直接呈现**合成结果里的候选说明**——每条的
`constraint_fit` / `rationale` / `key_strength` / `key_weakness`；
链接取**推荐自己引用的来源**（经证据链解析 URL）。
合成未给出说明的候选**明确记为缺口**，不由渲染器补。

**新增了 0 个模型调用、0 个核验框架**：只是让一处复用另一处的既有结果。

**导航链接**：单独列在"导航链接（无正文，不能作为依据）"标题下，**仍可达**但不冒充依据。

**顺带修掉的渲染缺陷**：模型字段内的换行会截断该候选的说明（`_one_line`），
回归 `test_a_multiline_explanation_is_not_truncated`。

---

## 四、三个真正的生成错误：先查清，再定位修法

### 4.1 「500 亿 → 5 万亿」

| 环节 | 事实 |
|---|---|
| 来源正文 | `在高达 500 亿行 的真实 OpenTelemetry 日志工作负载中…`；同段还有"数十亿乃至数万亿行"（能力上限，不是基准规模） |
| 报告 | `公开基准称其在 5 万亿行级 OTel 日志上磁盘占用约降 5 倍` |

**发生环节：模型生成**。它把同段的**能力上限（数万亿）**当成了**基准规模**，
把 `500 亿` 写成 `5 万亿`（差 100 倍）。绑定只替换来源标题，**不校验数值**。

### 4.2 Serverless 推荐理由无对应支撑

排名 #1 的 `rationale` / `constraint_fit_reason` / `key_strength` 三处都引
`OpenSearch vs ClickStack`（ClickHouse 自家对比页），而该来源正文讲的是
**查询与文件格式支持**，未讲"免集群调优""原生倒排索引秒级检索"。

**发生环节：模型生成**（把来源当成通用背书），**且无人复核**——见 4.4。

### 4.3 Athena 被无依据排除

报告把 `Amazon Athena over S3` 排 #4、`constraint_fit=low`，理由是"无原生全文检索、
难以秒级排障"，引 `OpenSearch vs ClickStack`。同时来源里
**`Amazon Athena - Serverless Interactive Query Service` 有 1224 字节正文**、
自陈"按扫描量计费""30%–90% 成本优化"。

**发生环节：模型生成 + 归属后处理**。它的正反两面都写进了 rationale，
但**排序依据（低适配）主要来自无正文的对比页**，而非它自己的文档。

### 4.4 为什么已有合成与自审没纠正

**这是本轮最重要的发现。**

用本次运行的 checkpoint 逐节点回放（`outputs/checkpoints.db`，thread
`8049500c-bd39-44e4-81bb-a1fbbebac780`）：

```
… → conclusion_synthesizer → report_generator → self_reviewer → query_analyzer
                                                                     ↑ 回到起点
```

**逐条区分代码事实、运行证据与推测：**

| 类别 | 内容 |
|---|---|
| **代码事实**（读代码可证） | `orchestrator.py` 的 `_route_after_review` 在 `confidence` 非 high/medium 且 `retry_count <= 1` 时返回 `retry_small`(→`query_adapter`) 或 `retry_full`(→`query_analyzer`)；`retry_full` **从起点重跑整图**。 |
| **运行证据**（checkpoint 实测） | 该次运行的 checkpoint 序列确实出现 `self_reviewer → query_analyzer`；**最终快照停在 `#26 phase='query_analyzer'`**，`quality_signals` 只剩 `query_analyzer`，**没有 self_reviewer 痕迹**；被保存的报告是**自审之前**那一份（`confidence_rationale` 仍带 `[[16]]`）。自审实际消耗 **20 448 tokens**。 |
| **推测（已撤回）** | 我此前写"**`query_analyzer` 重置计数导致无限循环**"。**撤回**：我**没有**观察到第二次进入自审，checkpoint 里只有一段 `self_reviewer → query_analyzer`；`retry_count` 的值也**未出现在 checkpoint 的 channel 值中**，无法从材料确认它被重置。"无限循环"是读代码后对最坏情况的**推断**，不是证据。 |

**代码事实中确有一条值得记录**：`retry_count` 是**唯一的**重跑护栏，而它由**每次运行结束时的
`self_reviewer`** 递增；这使得"重跑预算"与"复核结论"共用一个计数——这正是我修掉它的理由，
但**不是**"已观测到无限循环"。

**结论：自审的结论从未生效，报告是"未经自审"的产物，而自审的成本已经付掉。**

**另有一层**：`ranked_options` 的四个字段（决定排名顺序）**在整个代码库中没有任何复核**——
`analysis_review.py` 里对 `ranked_options`/`rationale`/`key_strength`/`key_weakness`
的引用数为 **0**；自审 payload 只带 `winner`、`recommendation` 等 headline 字段。
`ranked_options` 只在渲染器与合成器中被**输出**，从未被**检查**。

### 修法（最小）

1. **自审不再被丢弃**：`self_reviewer` 直接 `→ END`，删掉
   `_route_after_review` 与其两条 `retry_small`/`retry_full` 死边。
   `confidence` 与 `knowledge_gaps` 已足以把结果标记为临时性。
   回归：`test_review_terminates_the_graph`、`test_router_is_gone`、
   `test_low_confidence_run_ends_after_one_review`（低置信度只审一次且以自审态结束）。
2. **自审能看到被审内容**：payload 增加每个候选的
   `rationale` / `constraint_fit_reason` / `key_strength` / `key_weakness` 与权衡，
   并明确要求把**来源未陈述的数值/单位/规模**、**无支撑的理由**、**无支撑的排除**
   判为决定性错误。
   回归：`test_claims_text_carries_the_ranked_justifications`、
   `test_the_claims_summary_exposes_the_three_named_errors`（断言 `5 万亿`、`Serverless`、
   `Athena` 都进入自审输入）、`test_the_wrong_scale_is_absent_from_the_cited_source`
   （断言来源写 `500 亿行`、**从不写** `5 万亿`）。

**未做**：没有加数值校验框架、没有逐题黑名单/答案表、
**没有用 strong 标签或"未归属"标记去压制排名**。

### 4.5 复核发现的阻断项（已修，`73bc80c`）

独立复核判定 **BLOCKING: yes**：4.4 的修法**当时是空的**——
自审被告知"对照被引来源正文核查"，但 payload 里**只有来源标题**。
在已保存材料上实测：完整 payload 含 `5 万亿`（报告的说法）为真，
含 `500 亿`（来源的说法）为**假**；28 条链里只有 2 条正文出现过。
**所以那个差 100 倍的错误当时仍不可复核。**

**修法**：证据链区块改为携带每个来源的**有界正文**（`bounded_content_summary(limit=700)`），
不再只给标题。实测：payload 现含 `在高达 500 亿行`（来自 InfoQ 来源正文 16 415 字符），
而 `5 万亿` 只出现在 claims 中，二者**可区分**。

**同时修掉一条假测试**：原 `test_the_claims_summary_exposes_the_three_named_errors`
**在测试里重抄了节点的循环**，因此在父提交上也通过，即使把节点的 `claims_text` 删掉也照过。
现改为**拦截 `call_model`、驱动真实节点、断言真正构建出的 payload**。
**变异验证**：把 `bounded_content_summary` 替换为不返回正文时该测试**失败**；
恢复后通过。

**同时删除死代码**：`candidate_for_source` / `index_sources_by_candidate` / `UNASSIGNED`
在生产代码中已无消费者（只有测试引用），已删除；
相关测试改为覆盖 `names_candidate`——它在**官方来源映射查找**中仍有真实消费者，
那是另一个问题（某个声明候选是否点名了某个策划的文档条目）。

---

## 五、记录更正

`run_record_v3.md` 已撤回"四项全部达到"，改为**未通过内容验收**，并把
"段落主语与候选不符 / 已有正文被显示为无资料 / 排名结论超出证据"写在开头。
**原报告与快照保持不变。**

---

## 六、验证

| 项 | 结果 |
|---|---|
| 整套 | **376 passed**，2 条 `test_frontend_obs.py` 失败在**纯净 48b32bd 同样失败** |
| 端点验证（导航不可引用、普通正文不被误伤、四端点可达） | **21/21** |
| 泄漏验证（无正文来源在各路径不可引用） | **13/13** |
| 身份验证（候选身份贯通、Athena 有材料） | **20/20** |
| 自审 payload 含来源正文 | **通过**（含 `在高达 500 亿行`） |
| 变异验证（去掉来源正文后新测试失败） | **通过** |
| 新增回归 | `tests/test_converged_package.py` + `test_candidate_identity.py`；共 56 条相关测试通过 |

**独立复核（时限 30 分钟）结论**：`66db028` 上 **BLOCKING: yes**（见 4.5），
其余各项 CONFIRMED：自审不再被丢弃（图 `self_reviewer → END`，无条件边归零）、
What 复用同一份说明、主语猜测规则确已撤除、导航不可引用且普通正文不被误标（21/21）、
范围仅限预期文件、整套 379 passed 且无新增失败。
阻断项已在 `73bc80c` 闭合，**但闭合后的版本尚未再经独立复核**。

---

## 七、剩余缺口（未修，如实记录）

1. **数值不一致仍靠模型自查**：本轮只把"来源未陈述的数值"**交给自审**，
   **没有确定性校验**。若自审也判错，错误仍会进入报告。未加数值核对框架
   （用户明确不要庞大核验框架）。
2. **自审的检出率未经验证**：无从在不跑真实研究的前提下测出它对
   `500 亿/5 万亿` 这类错误的召回率。**这是下一份真实研究的观察点。**
3. **排名仍可与证据强度不符**：候选可排 #1 而其理由薄弱。用户明确
   **暂不开展基于当前归属结果的排名调整**，本轮只让排序理由
   **首次接受复核**，未改排序逻辑。
4. **`ranked_options` 无确定性复核**：`analysis_review` 框架仍不认识这个结构，
   只是自审 payload 现在带上它。要不要把它接入既有复核结构，属下一包判断。
5. **归属仍然只有"名称命中"一档**：页面覆盖多产品时会被整体判为未归属，
   其中关于候选的有效段落会丢。这是**用召回换准确**，未做段落级归属。
6. **`73bc80c` 尚未经独立复核**（`66db028` 的复核结论见第五节）。
7. **报告未重新生成**：原报告保留未改，本包只改代码与记录；
   **不自动补跑**，下一份真实验收另定授权。
8. **`retry_count` 分支现已不可达**：`query_adapter.py:40` 与 `multi_retriever.py:37`
   仍以 `retry_count > 0` 判断"是否用 knowledge_gaps 作为新目标"。
   该计数现在只由**终点的** `self_reviewer` 递增，因此在默认图中**永不触发**；
   仅在**显式带 `retry_count>0` 的 resume/replay** 下可达（属恢复语义，故保留未删）。
   无测试覆盖此分支。**这是恢复层与复核层的语义混用**，未在本包处理。
9. **本轮只让排序理由"可被复核"，未改动排序逻辑**：`ranked_options` 仍不被任何
   确定性检查覆盖（`analysis_review` 框架不认识该结构），自审 payload 现在带上它，
   但**自审对数值/规模错误的检出率无从在不跑真实研究的前提下验证**。
