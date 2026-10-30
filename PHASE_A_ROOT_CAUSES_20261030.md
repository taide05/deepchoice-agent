# Phase A：最终 200 的根因分类与不变量审计

> 只读分析，零付费跑例。对象：最终 200 内部结果中的 15 个 C2 partial + 1 个 C3 partial。
> 数据来源：`.scratch/cases/runs/final-200-20261029/`。

## 1. 结论先行

这 16 个 partial 不能都归为“模型不够强”。初步根因分为：

1. **确定性报告/引用缺陷**（可离线修，不需要补检索）；
2. **证据获取不足**（官方正文缺失/只有二手来源，需检索实验）；
3. **综合/输出契约缺陷**（空字段、截断、错误前提、来源定性错误）；
4. **诚实证据缺口**（没有数据，正确结果就是 hold/insufficient，不应强刷 DG）；
5. **评审歧义**（C2 partial 的边界判断）。

本轮先做 **1 + 3 中的确定性部分**：不改变调研结论，只修报告构造层。

## 2. 五个根因层

### D0：证据获取/来源身份

- 官方正文未取到（F200-181 msgspec、F200-189/191 AWS CDK、F200-197 Kaniko repo、F200-182 Pydantic/msgspec 官方页）；
- 决定性事实只有二手/厂商来源（F200-120/130/189/191/193/197）；
- 不是“报告写错”，而是“材料本身不够硬”，需要检索/抓取实验。

### D1：引用账本/来源清单不一致

- 正文 `[Source:]` 引用的来源未进入 reference/used（F200-028 4 个方法来源、F200-164 5 个方法来源、F200-047 技术博客、F200-051 社区来源、F200-130 东吴证券、F200-189/191 被排除来源仍计入）；
- `used-not-in-body`：reference 有来源、正文没有可见引用（F200-047/105/125/137/153）；
- 标题含方括号破坏 marker（F200-047、F200-068/094 已修）；
- 可做**渲染后账本归一化**，不增加模型调用。

### D2：来源类型/归属标签

- 厂商对比页/博客标成“官方文档/官方公告”（F200-120、189、191）；
- 社区 gitbook 被称为“官方材料”（F200-193）；
- 官方页面身份未验证但列入官方（health warn 大量出现）。

### D3：输出/报告契约

- F200-158：`unresolved_questions` 被截断并残留 `[[2`；
- F200-173：`What` 两候选说明为空、`ranked_options` 无 rationale；
- F200-197：6 处引用标记缺失；
- F200-182：抓取噪声/英文样板混入正文；
- 应在 synthesis 结果 schema/required fields/截断检测层拦截。

### D4：证据使用/综合

- 决定性结论依赖单一二手来源或厂商自述（F200-130/181/182/184/189/191/193）；
- 来源可追溯、事实不假，但证据强度不足以支撑“决策级”；
- 属于合成/评审层，不是纯展示修复。

### D5：评审口径/诚实缺口

- F200-051/028/164 本身是诚实的证据缺口型 hold；
- 它们的 C2 partial 部分来自 D1 引用完整性问题，部分来自真实证据缺失；
- 不能为了 DG 指标强行补来源或改写结论。

## 3. 15 个 case（16 个 partial 判定）逐例根因表

| case | C2/C3 | 主要根因 | 次要根因 | 可否零付费修 |
|---|---|---|---|---|
| F200-120 | partial/met | D0/D2：Tencent/Zhihu 未标注、厂商对比页标官方 | D4 决定性事实依赖二手 | 部分（标签） |
| F200-130 | partial/met | D1：无关来源残留标记/清单口径 | D0 官方正文少、D4 部署事实归因错 | 部分 |
| F200-182 | partial/met | D3：抓取噪声/错误前提 | D0 官方正文缺、D4 证据校准 | 部分 |
| F200-051 | partial/met | D1：一个社区来源未入参考清单、12 vs 13 | D0 审计/RBAC 无一手证据 | 是（账本） |
| F200-193 | partial/met | D2：社区 gitbook 称官方 | D0 官方缺失、D4 单来源 | 部分 |
| F200-189 | partial/met | D2/ D1：AL2 relnotes 标官方、计数含无关来源 | D0 AWS CDK 正文缺、D4 厂商页 | 部分 |
| F200-047 | partial/met | D1：博客未入参考、marker 被剥离 | D0 单站自述、D4 | 是（账本） |
| F200-191 | partial/met | D2/D1：AL2 relnotes 标官方、计数口径 | D0 官方缺、D4 DISPUTED 厂商页 | 部分 |
| F200-028 | partial/met | D1：4 个方法来源未入 Why/reference、6 vs 10 | D0 证据缺口（honest hold） | 是（账本） |
| F200-184 | partial/met | D1：不可用 Migration Map 计入引用 | D0 msgspec 官方缺、D4 适用性 | 是（账本） |
| F200-181 | partial/met | D0/D4：msgspec 官方正文完全缺、单篇次级博客 | D1 少量 | 否（需补检索） |
| F200-164 | partial/met | D1：14 个正文来源 vs 9 个声明、5 个方法来源未列 | D0 证据缺口（honest hold） | 是（账本） |
| F200-173 | partial/met | D3：What/ranked_options 空 | D1 9 vs 8、D0 二手来源 | 部分（schema 检测） |
| F200-197 | partial/met | D3/D1：6 处 marker 缺失 | D0 Kaniko 官方仓库失败、D4 单来源 | 部分 |
| F200-158 | partial/partial | D3：unresolved_questions 截断/序列化损坏 | D1 raw 残留 | 否（需重跑/修复） |

> 注：部分 case 同时有多个根因，表内只列主要/次要；D0/D4 类不能靠离线重放消除。

## 4. 不变量审计结果

已建立只读审计脚本：

- `.scratch/cases/phase_a_invariants.py`：直接读最终报告；
- `.scratch/cases/phase_a_render_audit.py`：用当前 renderer 重放 snapshot 再审计；
- 初始报告审计（C 方案之前）：64 个 `body-title-not-in-used`、5 个 `used-not-in-body`、
  2 个 raw/gap、1 个 ranked-option-no-rationale、1 个 malformed-uq；
- C 方案实现后的最终审计见第 8 节。

## 5. 本轮已实现的安全修复

- `report_quality.finalize_report_text` 现在处理：
  - `[[7]`（格式不完整）；
  - `[[2`（被截断）；
  - `[[`（无编号截断）；
  - 原有 `[[N]]`；
- 新增 `report_quality_flags` 对应 flags；
- 新增 `tests/test_report_quality.py` 覆盖；
- 这是纯展示/后处理修复，不影响调研内容。

## 6. 已选的 C 方案（已实现）

不采用裸 A/裸 B，而采用 **ledger-first + 标题别名**：

1. `used_sources` 不再做“候选相关性”后置过滤：**正文可见的引用必须进入账本**；
2. `_merge_used_entries` 为同一 canonical URL 保留所有标题别名（`aliases`）；
   解决 `https://qwik.dev/docs` 与 `/docs/`、`Ruff` 等标题变体被误判 ghost 的问题；
3. 由 synthesis 阶段决定是否引用来源，rendering 不再隐藏已引用来源；
4. 仍由 `report_contract_flags` 拦截空 ranked/截断字段。

效果（当前代码离线重放 200 snapshot）：

- 账本不一致从 64 个 case 降到 **6 个 case**；
- 6 个都是旧 snapshot 的方括号标题被 marker 截断（新写入流程已由
  `_citation_safe_title` 处理，旧 snapshot 不可逆）；
- 1 个空 ranked（F200-173）、1 个 truncated unresolved（F200-158）；
- raw marker：0。

### 未做的部分

- 不会强行修复旧 snapshot 的方括号标题截断内容（需要重跑/重新取正文）；
- F200-158 的截断是源数据/输出损坏，F200-173 的空 ranked 是模型输出契约问题；
  本轮只能检测/标记，不能零付费“补内容”；
- 证据获取仍属 Phase B，不在本轮。

### 历史仿真（C 之前）

| 方案 | reference 总数 | 问题 |
|---|---:|---|
| A：以正文可见引用为准 | 653 | 可能误删合法来源 |
| B：所有正文引用都入账 | 920 | 把噪声也纳入 |

结论：采用 C（ledger-first + aliases + 取消渲染层 relevance filter）。

## 7. 契约校验与拦截接入

- `conclusion_synthesizer` 在 citation 处理完成后写入：
  - `report_contract_flags`
  - `report_contract_ok`
- `report_generator` 写入：
  - `report_quality_flags`
  - `report_contract_flags` / `report_contract_ok`
  - `report_ledger_flags`
- `batch_health.py` 接入：
  - `report_quality:*`
  - `report_contract:*`
  - `report_ledger:*`
  - 关键契约失败（空 ranked、missing rationale、malformed unresolved、decision validation error）
    会让该单位 batch health **invalid**，不再只是 warn。
- 来源标签增加确定性规则：
  - 官方域下的 “X vs Y / comparison / alternatives / 对比” 页面标为
    “厂商对比页/利益相关方”，不再标成“官方文档/官方公告”。

## 8. Phase A 完成度

- [x] 16 个 partial 判定的根因复核（15 个唯一 case）
- [x] 200 个 snapshot 的不变量审计
- [x] 当前代码离线重放（不付费）
- [x] malformed/truncated citation marker 修复 + 测试
- [x] report contract flags + 测试
- [x] ledger A/B 只读仿真
- [x] ledger 方案 C 实现（去后置 relevance filter + canonical aliases）
- [x] 契约 flags 接入 quality_signals
- [x] 契约 flags 接入 batch health 的 invalid 门槛
- [x] ledger 不变量接入 batch health
- [x] 官方来源中的厂商对比页标签修复
- [x] 全量测试与离线重放

最终审计结果（当前代码，200 snapshot）：

- ledger 不一致：64 → **6**（均为旧 snapshot 方括号标题截断，新增流程已避免）；
- used-not-in-body：5 → **0**；
- raw marker：**0**；
- 空 ranked：1（F200-173，内容问题）；
- truncated unresolved：1（F200-158，内容问题）。

全量测试：**771 passed**。零付费跑例。

## 9. Phase A 边界

Permanently out of scope for Phase A：

- 旧 snapshot 的方括号标题截断内容：无法从已保存内容恢复，只能重跑；
- F200-158 / F200-173：需要模型重跑或自动重试，Phase A 只负责检测/拦截；
- D0 证据获取、D4 证据使用：Phase B/C；
- 最终 200 正式报告不重渲染、不重新评审，保持冻结。

因此 Phase A 的完成定义是：**确定性引用/契约/标签问题已修，且有回归测试和批次健康门槛**；
不是“200 份内容已经重跑到更好”。


