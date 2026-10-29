# 通用渲染加强：探索地图（2026-10-29）

> 状态：**探索/设计阶段，不实现**。用户要求先验证 C2/引用/可靠性，再做通用渲染。
> 本文件只描述问题、根因、方案和测试，不改代码。

## 1. 目标与非目标

### 目标

只改**报告呈现/来源身份**，不改检索、评分、综合结论：

1. 同一来源在不同标题/通道下只显示一次，引用计数与身份一致；
2. 报告中的来源数、参考清单条目、`+N more` 三者一致；
3. 官方来源标签更准确：官方文档 / 官方公告 / 官方页面，而不是一律“官方文档”；
4. 社区来源继续保留“（社区问答/非官方）”；
5. 不重新引入 raw citation / 引用未解析。

### 非目标

- 不改 decision_status、winner、结论文本；
- 不改来源评分/检索选择/C2 规则；
- 不重做报告版式；
- 不把渲染修复伪装成内容质量提升。

## 2. 已观察到的具体缺陷

| 缺陷 | 证据 | 影响 |
|---|---|---|
| 同 URL 双身份/双标题 | 20 例审阅 F200-198：同一 SO URL 以两个标题出现 | 来源清单重复，读者困惑 |
| 来源计数与清单不一致 | F200-155：正文 `13 个来源`，清单 12 条 + `(+1 more sources used)`；F200-075 把被自己判“噪声”的 SO 帖计入引用 | 读者无法核对 basis |
| 官方标签粒度粗 | F200-104/077/183：官方首页、公告、发布说明均标“（官方文档）” | “官方文档”被误读为中性技术文档 |
| 截断隐藏来源 | `what_why_how.py` 参考清单只显示前 12 条，其余写 `+N` | 计数与可见清单脱节 |
| 引用未解析 | 已由 `6648f29` 修复；新独立样本 raw/gap=0 | 需回归保护 |

## 3. 代码地图与根因

- `src/deepchoice/agents/conclusion_synthesizer.py::build_source_registry`
  - 每个 evidence chain/source 建一个 entry，`source_id = url`；
  - 同一 URL 可在多个 chain/通道出现，entry 未按 URL 合并；
  - `_disambiguate_same_title_entries` 只处理同标题不同身份，不处理同 URL 不同标题。
- `src/deepchoice/formats/basis.py`
  - `_used_from_identity_map` 以 `source_id/url` 聚合；但标题来自各 binding，
    同一 URL 的 binding 标题可能不同；
  - `used_sources` 最终按 URL 建 dict，理论上同 URL 应合并；
    需实测 F200-198 的重复是 registry 还是 renderer 层。
- `src/deepchoice/formats/what_why_how.py`
  - 顶部 `len(used)` 计数用全集；参考清单 `refs[:12]` + `+N more`；
  - 计数与可见清单天然可能不一致。
- `src/deepchoice/formats/basis.py::source_provenance_note`
  - `source_type == official_doc` → “官方文档”；
  - 没有 page-kind（首页/公告/API/教程）信息。
- `src/deepchoice/formats/community_evidence` 已加“社区问答/非官方”；
  需要回归测试，避免渲染改动覆盖掉。

## 4. 方案选项

### A. 渲染层去重（最小影响）

- 在 `basis.used_sources` 返回前，以 **canonical URL** 去重；
- 同 URL 多个标题时选一个 canonical title：
  - 优先非泛化、最长/最具体标题；
  - 保留 aliases 仅用于引用解析，不进入显示。
- 优点：改动小，不影响 registry/引用解析。
- 风险：不同页面同 URL 不应发生；同 URL 不同 body 需要保留最佳 body  provenance。

### B. registry 层 canonical identity（更彻底）

- `build_source_registry` 按 canonical URL 合并 entry：
  - 合并 provenance/date/body/answer facts；
  - 保留 aliases（旧标题）用于 citation title resolution；
  - `number`/`source_id` 仍稳定，避免破坏引用。
- 优点：所有消费者（synthesis/self-review/basis）统一；
- 风险：影响 prompt 编号与引用解析，需广泛回归；建议在 A 验证后再考虑。

### C. 官方 page-kind 标签

- 新增显示层分类（不改 `source_type` 评分）：
  - `official_docs`：路径/标题像 docs/reference/guide；
  - `official_announcement`：release/blog/announcement；
  - `official_page`：站点首页、产品页、定价页；
  - `community` / `secondary`。
- 数据来源：URL path、title、`source_kind`（如有）、body 是否 nav-like；
- 只影响 `source_provenance_note` 文案。

### D. 计数/清单一致性

- 参考清单不再静默截断；要么显示全部（受合理上限保护并明确“共 N 条”），
  要么计数与显示列表严格一致；
- `+N more` 改成“未显示条目数 + 总数”，并与顶部计数同源；
- 对“被自己判为噪声但计入引用”的条目，显示时明确标“未用于结论/噪声”，或不计入 basis。

## 5. 推荐路线

1. **先做 A + D**：渲染层 canonical dedupe + 计数/清单一致；影响小、可直接回归。
2. **C 官方标签**：独立显示分类，配测试。
3. **B registry 合并**：等 A/C 稳定后，评估是否值得影响 prompt/编号。
4. 全部完成前不动综合/检索/评分。

## 6. 测试设计（按项目测试规则）

- 单元：
  - 同 URL 不同标题 → 一个显示来源、canonical title 选择规则；
  - 同 URL 不同 body/provenance → 合并规则；
  - 计数 = 可见清单 + 明确隐藏数；
  - 官方 docs/announcement/page 分类；
  - community 标签回归；
  - raw/gap citation 回归。
- 合同/渲染：
  - 三格式（what_why_how/evidence_first/comparison_matrix）来源列表/计数一致；
  - 无 `[[n]]` / 引用未解析；
- e2e：只在必要时用 1 个 fixture 跑完整 renderer，不跑 200；
- 真实样本：用已有 20/6/2 报告离线重放，不直接占用最终 200。

## 7. 待确认

1. 同 URL 但不同 body（不同通道抓取）以哪份为准？保留最长/最新/最高正文验证？
2. `+N more` 是显示全部还是保留截断但显式列出“未显示 N 条 + 总数”？
3. 官方标签分类用 URL/title 规则是否足够，是否要改 official retriever 记录 page_kind？
4. “噪声来源不计入 basis”是否可确定性判断，还是只做显示标注？

## 8. 第一阶段实现状态（2026-10-29）

已实现（A + D + C 的显示层，B registry merge 未做）：

- `basis._canonical_source_url` / `_merge_used_entries`：
  同 canonical URL 的引用行合并；标题优先更具体者；citation 次数累加；
  `used_sources` 在 identity map/title fallback 合并后再走 relevance filter；
- 三个 renderer 移除 `used[:12]` 截断与 `+N more`，参考清单与计数使用同一 `used_sources`；
- `source_binding` 增加 source_owner/source_kind/body_identity_verified，
  使 verified first-party 页面即使 `source_type=web_document` 也能显示为官方；
- `source_provenance_note` 分类：官方文档 / 官方公告 / 官方页面；community 保持社区问答/非官方；
- 新增 `tests/test_rendering_consistency.py`：
  canonical URL、同 URL 双标题合并、官方三类标签、first-party verified 标签、
  13 来源时不截断且计数/清单一致；
- 全量测试 **763 passed**。

未做：

- registry 层 canonical merge（B，影响 prompt/编号，等 A/C 稳定后再评估）；
- 噪声来源不计入 basis（仅提示/规则，未做硬判定）；
- 真实运行后的目视检查（当前用单元/合同测试；下一步可用已有 20/6/2 报告离线重放）。

