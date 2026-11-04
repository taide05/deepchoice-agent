# Provenance note — mixed batch (protocol v1.2 §3)

Primary run: batch inal-200-newcode-20261104 (200/200 complete, 15,932,513 tokens).
Three cases were first-attempt invalid per batch health (report-contract issues):

  F200-105  report_contract:malformed_unresolved_question
  F200-123  report_contract:ranked_option_no_rationale + decision_validation_recovered
  F200-173  report_contract:ranked_option_no_rationale + decision_validation_recovered

Per protocol v1.2 §3 (invalid must be re-run or explicitly counted), the same three
fixed-set cases were re-run in fill batch inal-200-newcode-fill-20261104
(258,604 tokens, 2026-11-04 05:54–06:03). All three returned health warn (no invalid).
Their fill artifacts (
eport.md, snapshot.json, 
esearch_snapshot.json,
status.json) replaced the main-run copies so downstream metrics/reviews read one
consistent artifact per case. Provenance for the three cases:

  case      main attempt (invalid)      final attempt (used)
  F200-105  05:5x batch-...             final-200-newcode-fill-20261104
  F200-123  ...                         final-200-newcode-fill-20261104
  F200-173  ...                         final-200-newcode-fill-20261104

No replacement cases: all 200 case IDs are the fixed formal set; denominator 200.
Total formal-200 spend including fill: 16,191,117 tokens.

## 第三层抽检后的修复重跑（2026-11-04）

第三层 24 例 AI 抽检发现 5 例关键错误（018/026/066/111/194）及 023 无依据描述。修复内容：
合成 prompt 规则 35–38（不得虚构用户门槛/不得以未声明现网栈排序/属性与权限表逐行归属/不得把兼容性陈述
升格为必然关系）、自审同类 decisive-error 检查、confidence 文字对齐扩展。修复后重跑 6 例：

- 运行：`final-200-fix6b-20261104`（代码 `beec449`，`EVIDENCE_INPUT_BUDGET_CHARS=32000`，并发 2）；
- 结果：6/6 完成，health 无 invalid；tokens **505,534**（在 700k 上限内）；
- 6 例最终产物以本次重跑为准（report/snapshot/research_snapshot/status 已替换）；
- 正式 200 全量指标仍以主批 + 3 例 invalid 重跑为口径（16,191,117 tokens）；
  本次 6 例重跑用于修复验证，累计付费 tokens 16,696,651（详见表）。

### 全量付费台账（2026-11-03/04 夜间）

| 项目 | tokens |
|---|---:|
| 既有记录（G1/R2–R5 等） | 2,012,101 |
| Phase B1+B2 | 1,104,515 |
| Phase C（pilot-30 + 补跑） | 2,386,159 |
| Phase D（正式 200 + invalid 重跑 3 例） | 16,191,117 |
| 第三层修复重跑 6 例 | 505,534 |
| 单例 smoke（F200-018） | 86,286 |
| **合计** | **22,285,712 / 22,500,000（含用户批准的 +0.5M 修复额度）** |

## 第三层复检后的追加修复（2026-11-04 晚，v1.2.2）

第三层复检指出 023、026 仍 C4=1（026："或"分支错误推导现网为 Rails；023：检索缺口→需要自研 +
旧 Spring 升级成本）。新增合成规则 39–41 与自审检查后重跑：

- 运行：`final-200-fix2-20261104`（代码 `df99023`，并发 2，cap 300k）；
- 结果：2/2 完成，health 无 invalid，tokens **139,653**；
- 023/026 最终产物以本次重跑为准（已替换主目录 report/snapshot/status）；
- 复评：按 v1.2.2 C2 输出契约（`C2_failed_checks`/`C2_comparable`、notes 与布尔一致性）重做内部+独立两层。

### 更新后的付费台账

| 项目 | tokens |
|---|---:|
| 此前合计（截至 fix6b+smoke） | 22,285,712 |
| 023/026 复修批（fix2） | 139,653 |
| **合计** | **22,425,365 / 22,500,000** |
