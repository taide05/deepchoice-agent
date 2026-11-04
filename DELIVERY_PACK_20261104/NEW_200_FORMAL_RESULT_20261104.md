# 新代码正式 200 结果（2026-11-04）

> 运行：`final-200-newcode-20261104`；题集 `.scratch/cases/cases_formal_200.json`（200 例固定分母）；
> 代码 commit `a0355554d33b`；配置 `EVIDENCE_INPUT_BUDGET_CHARS=32000`、并发 4、cap 16M；协议 `PROTOCOL_V12_DRAFT_20261103.md`（v1.2，已批准）。
> 本报告只描述本轮观测，不预设“通过/优秀”；内容结论以评审层为准。

## 1. 完整性

- 完成：**200/200**；缺失：无；
- 状态分布：{'complete': 200}；budget_stopped：False；
- 混合批次 provenance：首跑 3 例（F200-105/123/173）health invalid（报告契约问题），按协议 v1.2 §3 **同案例重跑**（补跑批 `final-200-newcode-fill-20261104`，258,604 tokens），最终 health invalid=0；无替换案例，分母仍为 200。详见 `PROVENANCE_MIXED_BATCH.md`。
- 题集 SHA-256：`46728f209aa12760afa39e0467b1c6c8fae1b0dac130b20e76ff1810031e3807`。

## 2. 成本与耗时

- tokens：主批 **15,932,513**（均值 79,662.6，p50 78,060，min 45,764，max 133,860）+ 补跑 258,604 = **16,191,117**；
- wall p50 248.9s，p95 371.2s，max 452.3s；
- 与基线对比：基线 13,068,148（旧代码 24k 证据预算），本轮更高属配置变化（32k）。

## 3. 决策与证据

- 置信度分布：{'low': 124, 'medium': 76}；
- 官方正文页：合计 912，均值 4.56，0 页案例 0；
- 服务端 extract 页（`fetch_via=tavily_extract`）：170；
- 证据预算：32000 字符；full_included 分布 {'True': 91, 'False': 109}；省略字符合计 1,473,339（109 例）；
- 引用 gap：31 例 / 489 处（最差：[['F200-180', 68], ['F200-066', 60], ['F200-100', 59], ['F200-092', 50], ['F200-043', 48], ['F200-157', 33], ['F200-189', 33], ['F200-051', 19]]）；
- health：首跑 {'warn': 167, 'ok': 30, 'invalid': 3}；3 例 invalid 已同案例重跑（补跑后 invalid=0，gate 通过）；问题类型 {'report_claim_support': 100, 'report_quality': 187, 'page_issue': 52, 'report_ledger': 5, 'report_contract': 5}。

## 4. 内容评审（协议 v1.2 三层）

**第一层（内部全量）**：200/200 例；C1 200 · C2 157 · C3 200 · C4 1；usable **199/200（99.5%）**，decision-grade **157/200（78.5%）**；
- D1–D5 均值：D1 4.46 · D2 4.62 · D3 4.27 · D4 4.95 · D5 4.95；
- paraphrase：{'low': 142, 'medium': 55, 'high': 3}；证据不对称：{'mild': 110, 'strong': 90}。

**第二层（独立复核）**：200/200 例；usable **197/200（98.5%）**，decision-grade **178/200（89.0%）**；C4 3；
- D1–D5 均值：D1 4.36 · D2 4.72 · D3 4.64 · D4 4.84 · D5 4.96；
- 两层一致率：usable 98.0% · decision-grade 78.5% · C4 98.0%（共有 200 例）；
- C4 分歧：[{'case_id': 'F200-018', 'kind': 'C4'}, {'case_id': 'F200-023', 'kind': 'C4'}, {'case_id': 'F200-026', 'kind': 'C4'}, {'case_id': 'F200-066', 'kind': 'C4'}]。

**第三层（人工抽检 20–30 例）**：**pending**（用户回来后执行；不阻塞本报告）。

## 4.1 两层评审的 C4 分歧（逐例披露）

- 内部层 C4=1：F200-026（默认 Rails/fit=high 以"存量系统为 Rails/Ruby"为前提，输入未给出，属错误前提归因）；
- 独立层 C4=1：F200-018（Flutter=rewrite-only 前提无来源且忽略 add-to-app）、F200-023（"团队缺 Java/C#"前提与输入矛盾）、
  F200-066（排名前提默认现网为 MySQL，却称不作假设）；
- 两层 C4 一致率 98%（196/200）；usable 一致率 98%；decision-grade 一致率 78.5%；
- **共识可用**：200 − 4 个单层 C4 = **196/200（98%）**；4 例分歧需人工抽检确认（已列入待办）。

## 5. 与冻结基线对比

| 指标 | 冻结批（旧代码 c8fad27） | 本轮新代码 |
|---|---|---|
| 完成 | 200/200 | 200/200 |
| usable | 200/200 | 199/200 |
| decision-grade | 197/200 | 157/200 |
| C4 关键错误 | 0 | 内部 1 · 独立 3 |
| tokens | 13,068,148 | 16,191,117（含补跑） |
| 官方正文覆盖 | 195/200 | 0 页 0 例（均值 4.56 页） |

## 6. 已知限制与披露

- echo.labstack.com 等站点本地与服务端均不可达，相关候选仍可能缺官方正文（逐例披露）；
- 官方页面存储上限 8,000 字符，个别大页（如 elastic release-notes 92 万字符）只存前 8k，截断会以 `stored_truncated` 与引用 gap 披露；
- 证据输入预算 32k 仍会截断正文丰富案例（见 §3 omitted chars）；
- 服务端 extract 的正文 provenance 为 `tavily_extract`（本轮 170 页），非本地一手抓取；
- 引用 gap：31 例 / 489 处（最差 F200-180 68 处、F200-066 60 处、F200-100 59 处），主要来自官方大页存储截断与模型未解析引用；
- 评审第二层为独立 agent 复核，不等同人工评审；人工抽检 pending；
- 本轮为**协议 v1.2 首次正式 200**，与旧批指标体系不可混合引用。

## 7. 复现

```powershell
$env:PYTHONPATH='D:\deepchoice-precodex\src;D:\deepchoice-precodex'
$env:EVIDENCE_INPUT_BUDGET_CHARS='32000'
& D:\deepchoice-agent\.venv\Scripts\python.exe .scratch\cases\run_batch.py --cases .scratch\cases\cases_formal_200.json --out .scratch\cases\runs\final-200-newcode-20261104 --concurrency 4 --timeout 1800 --max-tokens 16000000
```

评审数据：`review_internal/chunk-*.json`、`review_independent/chunk-*.json`；
确定性指标：`metrics.json`；评审汇总：`review_metrics.json`。

## 8. 本轮预算台账（夜间全部付费运行）

| 项目 | tokens |
|---|---:|
| 既有记录（G1/R2–R5 等） | 2,012,101 |
| Phase B1（10 例定向） | 753,745 |
| Phase B2（5 例官方 0 页复验） | 350,770 |
| Phase C（pilot-30 + 补跑 1 例） | 2,386,159 |
| Phase D（正式 200 + 重跑 3 例） | 16,191,117 |
| **合计** | **21,693,892 / 22,000,000** |

## 9. 与 B 轮 D1–D5 诊断对比（同口径内部评审）

| 维度 | 冻结 B 轮（200 例） | 新代码正式 200（本轮内部层） |
|---|---:|---:|
| D1 回答 | 4.30 | 4.46 |
| D2 权衡 | 4.58 | 4.62 |
| D3 证据校准 | 4.38 | 4.27 |
| D4 风险/反转 | 4.74 | 4.95 |
| D5 诚信 | 4.89 | 4.95 |

说明：两轮都是内部诊断、样本同为 200 例、口径相同；B 轮为冻结旧代码产物，本轮为新代码产物。
D3 未升反降（4.38→4.27），与 §3 的 31 例引用 gap、32k 预算截断（109 例）、官方页存储上限相关，属诚实读数。

## 10. 阶段产物索引

- Phase A 修复与协议：`PHASE_A_PROGRESS_20261103.md`、`PROTOCOL_V12_DRAFT_20261103.md`；
- Phase B 定向验证：`PHASE_B_RESULT_20261103.md`；
- Phase C pilot gate：`PHASE_C_RESULT_20261104.md`；
- D1–D5 冻结批诊断：`D1D5_DIAGNOSTIC_RESULT_20261103.md`；
- 夜间状态与预算：`NIGHT_RUN_STATUS_20261103.md`；
- 评审卡与评审数据：`INDEPENDENT_REVIEW_CARD_20261104.md`、运行目录 `review_internal/`、`review_independent/`。
