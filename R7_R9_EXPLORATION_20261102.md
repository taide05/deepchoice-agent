# R7/R9 探索：归因、量化与修复选项（2026-11-02）

> 零成本只读探索。数据源：`.scratch/cases/runs/final-200-20261031b/`
> （`review_inputs/*.json`、各 case `snapshot.json`、10 批量 `batch_health.json`），
> 机器可读汇总见 `r7_r9_data_20261102.json`。
> 本文件只做归因与方案，不改代码、不跑付费。

## 1. R7a — 5 例 official 正文 0 页：全部是抓取/外部限制，不是映射主错

| case | official 通道结果 | health 证据 | 类别 | 可修复性 |
|---|---|---|---|---|
| F200-030 | `docs.gofiber.io/`、`docs.gofiber.io/stable`、`docs.gofiber.io/latest`、Echo docs 均 has_body=false | `page_issue:official:timeout` ×3 | 站点超时（GoFiber 文档站） | 外部为主；重试/代理不可靠 |
| F200-070 | `elastic.co`、`opensearch.org/docs/latest`、`elastic.co/stable`、`elastic.co/latest` 均 false | `timeout:https://elastic.co` | 超时 + 映射指向站点根而非 docs | 外部为主；映射可小改（elastic.co → elastic.co/docs/…） |
| F200-071 | 同 F200-070 | `timeout:https://elastic.co` + source_concentration elastic.co:3 | 同上 | 同上 |
| F200-072 | 同 F200-070 | 同上 + source_concentration aws.amazon.com:3 | 同上 | 同上 |
| F200-088 | haproxy.org、docs.haproxy.org、envoyproxy.envoy/latest、haproxy bugs 页均 false；envoy llms.txt fallback | `ReadError` haproxy bugs 页 ×2 | 站点读取失败 + 静态 fallback 无正文 | 外部为主 |

结论：这 5 例是**外部抓取限制**（超时/ReadError/静态 fallback 不返回正文），不是 official 映射把候选指错。
唯一可做的小改动：Electron/Elastic 类映射应指向 `/docs` 深页而非站点根（降低根页 timeout 的概率），
但无法保证有正文；不建议为此开专门付费运行。

## 2. R7b — source concentration / 决定性来源单边

- 10 个主批 `batch_health`：`report_quality:source_concentration` **143**；
  `report_claim_support:conditional_top_option_owner_dominates` **58**、
  `..._secondary_dominant` **22**、`conditional_no_primary` **7**。
- 决策 guard 实际动作（200 snapshot 汇总）：`conditional_top_option_strength_caveat` **79 次**、
  `recommended_to_conditional` **4 次** → 87 个 claim-support 告警里约 83 个在报告层被降级/加校准句，
  剩余是报告已明确标注证据缺口/单一来源的情况。
- 引用绑定 host 前 10（跨字段计数，不是独立来源数）：stackoverflow.com 830、github.com 337、
  zhuanlan.zhihu.com 309、medium.com 259、buildkite.com 233、cnblogs.com 205、pulumi.com 177、
  csdn.net 174、linkedin.com 171、quant67.com 166。
  → 大量引用集中在社区/二手与厂商博客（与 61+23 的 owner/secondary 告警一致）；
  source concentration 多数是“同一官方文档站的多个页面”，本身不等于缺陷（规则明确它是诊断，不是目标）。
- 判断：**R7b 主要不是检索 bug，而是证据结构问题**（候选一方有官方正文、另一方只有二手/缺失）。
  现有 guard 已吸收绝大多数告警；剩余部分是真实证据缺口，靠复制更多同源页面无法修复。
  可选增强（均需 G1 验证，预计收益有限）：
  1. 检索层：对 top-option 增加“独立来源配额”（每候选至少 1 个非自有来源），成本是 Tavily/时间；
  2. prompt 层：把“独立来源不足时只能给分支/假设”写得更硬（现有 rule 16/19 已覆盖）；
  3. guard 层：把 `secondary_dominant` 也统一加 caveat（当前 22 例里部分只靠 prompt）。
  建议：**记录为已知限制 + 小步增强 3（零模型成本，只需 G1 验证一次）**，不为此单独开 200。

## 3. R9 — 证据正文截断

- 200 例中 **133 例**有 `evidence_stored_truncated_sources>0`，**19 例**有 page 级截断。
- 预算 `EVIDENCE_INPUT_BUDGET_CHARS = 24000`；证据视图可见字符 p50 ≈ **23,630**（贴着预算上限）。
- 被截断省略字符合计 **1,618,316** 字符（200 例），平均 **8,092 字符/例**被省略；
  省略集中在少数长官方文档页（source_chars mean ≈ 26.8k、p50 更小）。
- 影响判断：评审中确有“决定性来源被截断（仅首尾片段）”的记录，但 200 例中没有因此出现 C4；
  风险是漏掉正文中段的关键数字/限制条件。
- 成本估算（提高预算到 32k）：证据视图 +8k 字符 ≈ **+2.7–3.2k tokens/次调用**（中英混排按 ~2.5–3 字符/token）。
  证据视图用于 synthesis 1 次 + self-review 1–2 次 → **+3–6k tokens/例**；按本轮 63.5k tokens/例 ≈ **+5–9%**。
  正式 200 ≈ +0.6–1.2M tokens。
- 选项：
  1. **先做零成本抽取优化**：在预算计数前剥离导航/页眉页脚/重复模板，再把节省的字符用于正文中段；
     可用现存 200 snapshot 离线估算收益（不需要付费运行）。
  2. **提高预算到 30–32k**：直接但成本 +5–9%；需在正式 200 预算里预留。
  3. **按来源优先级分配**：把绑定到决定性维度的来源优先给全正文，其余截断；纯代码改动、
     可离线用 200 snapshot 估算。
  4. **接受并披露**：继续报告“正文被截断”，不作为事实断言。
- 建议：先做 1 与 3（零成本、可离线验证），把“是否升预算”留到正式 200 预算审批时一起决定。

## 4. 建议的最小实验（均 ≤16 例）

| 实验 | 目的 | 预算 |
|---|---|---|
| E1（零成本） | 对 5 个 official-0 例离线回放官方映射/fallback 调整，确认不会引入错误正文 | 0 |
| E2（G1 内顺带） | 在现有 16 例 G1 中观察 `owner/secondary_dominant` 类 case 的 guard 后报告形态 | 已含在 G1 |
| E3（零成本） | 抽取优化/按来源优先级分配的离线收益估算（200 snapshot 重放，不调模型） | 0 |
| E4（可选付费） | 若 E3 显示截断确实丢失决定性证据，再申请小样本验证升预算（16 例，约 1.1M） | 需批准 |

## 5. 结论

- **R7a**：外部限制为主，不改代码；最多做 Elastic 类映射小改（零成本）。
- **R7b**：已有 guard 覆盖 ~95%，剩余为真实证据缺口；建议记录限制+一次小步增强，不单开运行。
- **R9**：优先做零成本抽取/优先级优化；升预算的取舍留到正式 200 预算审批时决定。
- 以上均不阻塞当前 G1 修复验证；修复收敛后再决定是否实施 E1/E3 与正式 200。
