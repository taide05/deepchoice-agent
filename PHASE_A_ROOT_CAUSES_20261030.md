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
- 原始报告审计结果：64 个 `body-title-not-in-used`、5 个 `used-not-in-body`、
  2 个 raw/gap、1 个 ranked-option-no-rationale、1 个 malformed-uq；
- 当前代码重放 + finalize 后：raw marker 0、malformed-uq 1（F200-158 源数据本身损坏），
  64 个 ledger 不一致与 5 个 unlisted 仍存在；
- 说明：**渲染层能统一处理 raw marker，但账本不一致仍在 `basis/citation_sources` 侧，需要单独设计。**

## 5. 本轮已实现的安全修复

- `report_quality.finalize_report_text` 现在处理：
  - `[[7]`（格式不完整）；
  - `[[2`（被截断）；
  - `[[`（无编号截断）；
  - 原有 `[[N]]`；
- 新增 `report_quality_flags` 对应 flags；
- 新增 `tests/test_report_quality.py` 覆盖；
- 这是纯展示/后处理修复，不影响调研内容。

## 6. 待实现（Phase A 之后）

### P0：账本归一化（零付费）

二选一，需要先设计再实现：

- 方案 A：以“正文实际出现的引用”为唯一来源，移除 filtered/ghost markers，reference 只列可见引用；
- 方案 B：取消 relevance filter，所有被引来源都进 reference（包括方法/泛化来源），保证一致但会保留噪声。

仿真结果见第 7 节：裸 A / 裸 B 都有明显代价，需要方案 C（在 citation 生成时决定入账）。

### P0：输出契约拦截

- synthesis 结果要求 What/ranked_options 非空、rationale 非空；
- 检测截断/序列化损坏，重试一次或标 invalid；
- 不把 F200-173/158 这类缺陷带入最终指标。

### P1：来源标签

- `source_owner/body_identity_verified/page_kind` 已在 binding 中；
- 需要把“厂商页/官方页/官方文档/公告”的判定统一到 registry，而不是渲染层猜。

### P1：证据获取（Phase B，需付费批准）

- 官方文档 fallback/身份校验；
- 在独立验证集上做小规模实验，不使用这些 C2/C3 partial 调参。

### P1：证据使用（Phase C，需付费批准）

- claim-level evidence ledger；
- 单一二手来源不得支撑决定性结论；
- 允许诚实 hold，不强行提高 DG。

## 7. Ledger 方案仿真（只读）

对 200 个 snapshot 重放当前 renderer 后，发现 **64 个 case** 有 body 中引用但 used/reference 没有的来源；5 个 case 有 reference 列了但正文不可见的来源。

两种简单方案的数量对比：

| 方案 | 行为 | reference 总数 | 问题 |
|---|---|---:|---|
| A：以正文可见引用为准 | 删除幽灵 marker，refs 只列 visible used | 653 | 可能误删合法来源（Qwik/Ruff 官方文档也被判 ghost） |
| B：所有正文引用都入账 | 把可解析 ghost 加进 refs | 920 | 把财经新闻/股票等噪声也纳入 |

结论：**裸 A / 裸 B 都不可取**。ghost 中既有噪声，也有被 relevance filter 误伤的真实来源（如 F200-011 的 Qwik 官方文档、F200-188 的 Ruff 文档）。因此需要方案 C：

- **在 citation 生成时决定来源是否入账**，而不是渲染后猜；
- 正文可见引用必须可从 registry 解析；
- 明确不相关来源应在 synthesis 阶段不引用（rule 21），而不是“引用了再从 refs 删除”；
- 渲染层只负责“账本里的来源都显示、显示的来源都在账本里”。

## 8. 下一步（Phase A 剩余）

1. 在 citation generation 处建立 ledger 设计，避免 body/refs 二分；
2. 为“可见引用 ↔ ledger”增加合同测试；
3. 对输出契约 flags（empty ranked/truncated uq）接入合成结果校验；
4. 完成全量测试与离线重放；
5. 再决定 Phase B 的检索实验是否值得付费。


## 9. Phase A 完成度

- [x] 16 个 partial 判定的根因复核（15 个唯一 case）
- [x] 200 个 snapshot 的不变量审计
- [x] 当前代码离线重放（不付费）
- [x] malformed/truncated citation marker 修复 + 测试
- [x] report contract flags + 测试
- [x] ledger A/B 只读仿真
- [ ] ledger 方案 C 的实现
- [ ] 输出契约 flags 接入合成结果校验
- [ ] 全量重放后复测

全量测试：**768 passed**。零付费跑例。
