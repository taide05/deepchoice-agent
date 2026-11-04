# 披露清单（新代码正式 200，2026-11-04）

本文件列出交付时必须随报告披露的限制与异常，避免选择性引用。

## 1. 批次与 provenance
- 固定题集 200 例，一次跑齐；**无替换案例**，分母 200。
- 首跑 3 例（F200-105/123/173）health invalid（报告契约问题），按协议 v1.2 §3 同案例重跑；
  最终 health invalid=0；见 `PROVENANCE_MIXED_BATCH.md`。
- 首跑 tokens 15,932,513 + 补跑 258,604 = 16,191,117。

## 2. 评审层
- 第一层内部全量：200/200；usable 199/200（99.5%），decision-grade 157/200（78.5%）；C4=1 一例（F200-026）。
- 第二层独立复核：200/200；usable 197/200（98.5%），decision-grade 178/200（89.0%）；C4=1 三例（F200-018/023/066）。
- 两层一致率：usable 98.0% · decision-grade 78.5% · C4 98.0%。
- **共识可用 196/200（98%）**；4 例 C4 分歧（018/023/026/066）待人工抽检确认。
- 第三层人工抽检 20–30 例：**pending**（用户执行）。
- 评审为内部/独立 agent 复核，不等同人工评审；评审数据在 `reviews/`。

## 3. 检索与证据
- 官方正文页合计 912，均值 4.56，0 页案例 0；
- 服务端 extract 页（`fetch_via=tavily_extract`）170 页：非本地一手抓取，provenance 已标注；
- 官方页面存储上限 8,000 字符；大页（如 elastic release-notes 92 万字符）只存前 8k，以 `stored_truncated` 与引用 gap 披露；
- 证据输入预算 32,000 字符：full_included True 91 例 / False 109 例；省略字符合计 1,473,339；
- 引用 gap：31 例 / 489 处（最差 F200-180 68、F200-066 60、F200-100 59）；
- echo.labstack.com 本地与服务端均不可达（个别候选官方正文仍缺，逐例披露）。

## 4. Health
- 首跑：ok 30 / warn 167 / invalid 3 → 重跑后 invalid=0；
- 问题类型：{'report_claim_support': 100, 'report_quality': 187, 'page_issue': 52, 'report_ledger': 5, 'report_contract': 5}；
- 主要 warn：source_concentration（单域来源集中）、claim_support（条件选项来源归属）、citation_gap、page_issue（官方页抓取失败）。

## 5. 与旧批关系
- 冻结批 `final-200-20261031b`（旧代码 c8fad27）的正式指标仍保留为历史基线（usable 200/200、DG 197/200、C4=0、13,068,148 tokens、195/200 官方正文覆盖）；
- 本轮为协议 v1.2 首次正式 200，**新旧指标不可混合引用**；对比见正式报告 §5/§9。
