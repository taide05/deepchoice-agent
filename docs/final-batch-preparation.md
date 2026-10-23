# 最终交付候选与批量评测准备（第9轮，离线）

更新：2026-10-23。状态：**准备完成一部分，批量评测准入未通过**。本文不授权外呼，也不声称内容质量、
基线公平性或正式指标已经成立。

## 1. 唯一交付候选与实际用户入口

- 交付分支：`codex/generic-selection`（维护树 `D:\deepchoice-agent`），基点 **`b9ad9c6`**；
  本轮代码/工具/数据/测试提交 **`8948c71`**（文档尾提交以最终 HEAD 为准）作为唯一最终候选。
  实际候选 commit、树哈希和数据集 hash 记录在
  `D:\deepchoice-dsh\r9_delivery_identity.json`，以该外部记录和 `git rev-parse HEAD` 交叉核对。
- 实际用户入口是 **durable 产品 API**，不是实验树旧 `/research`：
  - 启动：`D:\deepchoice-agent\.venv\Scripts\python.exe -m uvicorn deepchoice.server.app:app --host 127.0.0.1 --port 8000`
  - 提交任务：`POST /api/v1/tasks`，body 为 `ResearchRequest`（`schema_version/query/...`）。
  - 状态与异常：`GET /api/v1/tasks/{task_id}`（任务/最新 run 状态、版本、终态），
    `GET /api/v1/tasks/{task_id}/events`（SSE）；HITL 用
    `GET /api/v1/tasks/{task_id}/decision` 与 `POST .../decisions/{decision_id}`。
  - 结果：`GET /api/v1/tasks/{task_id}/report`、`/snapshot`、`/observability`。
  - 阅读与导出：`GET /api/v1/tasks/{task_id}/annotated`、
    `GET /api/v1/tasks/{task_id}/export?format=md|pdf`（HTML 由 annotated 的
    `report_html` 提供）。
- 离线链路证据（未联网）：
  - `tests/test_task_api_phase1c.py`、`tests/test_run_results.py`、
    `tests/test_annotated_export.py`、`tests/test_phase1f_acceptance.py`：
    **42 passed**，覆盖提交、状态、异常/冲突、结果、annotated 与 Markdown/PDF 导出路径。
  - 现有 durable 契约测试不替代真实模型/来源运行；它们只证明离线用户链路可调用。
- 旧 `POST /research` 已在 2026-10-14 结束兼容期；本候选不恢复该接口。

## 2. 实验改动的盘点与迁移结论

本候选以维护树的 **research-v6 durable 代码**为基线。实验树的改动不能整树合并；逐项核对结果：

| 实验改动 | 当前维护树对应实现 | 处理 |
|---|---|---|
| 第1–5轮来源身份/安全抓取/证据窗口 | `retrievers/official.py`、`official_pages.py`、`outbound/`、`citations/source_windows.py` | 已被更晚的维护实现取代；不迁入旧实现 |
| 第6轮主内容列表/代码/表格提取、1 MiB/20k/24k caps、失败 metadata | `official_pages.py`（`MAX_PAGE_BYTES`、truncation extensions）、`test_official_pages.py`、`test_official_paragraph_window.py`、`test_p01_fts5_body_selection.py` | 维护实现保留；本轮离线复核页面/导航相关定向套件通过；不迁入旧 `page_text.py` |
| 第7/8轮 `decision_status`/winner 回退/自审撤回 | 维护树的 `utils/decision_contract.py`、`utils/decision_analysis.py`、`formats/decision.py`、`agents/evidence_decision_gate.py`、新的 `self_reviewer` | 当前契约字段/消费者不同（`context_dependent`、`conditional_choices`、`abstain_recommendation` 等）；旧 `utils/decision.py` 不能直接合并。未证明旧模块能改善维护树内容，按“不恢复废弃接口、不整树合并”保留维护实现 |
| 第5–8轮 `launch_pair.py`/`pair_worker.py`、`simple_baseline.py`、`seal_case.py` | 维护树没有同一共享采集的 durable 配对臂；维护树已有 durable collector、预算/生命周期/快照 | **未迁移**。共享采集基线在 durable 入口的适配尚不存在，构成正式两臂评测阻断 |

结论：本轮没有把旧接口实现硬塞进维护树；迁移风险高于收益。真正缺失的不是旧模块，而是
**durable 产品入口上的共享采集基线适配**，以及独立题集/参考依据/评审冻结。

## 3. 最小批量入口与结果汇总

新增离线可审查工具：

- `benchmarks/final_batch.py`
  - `validate`：加载/校验 120 final + 12 calibration、层级配额、ID/group/候选对唯一、
    final/calibration 隔离、HITL、request 契约、引用只给评审且不进入研究输入。
  - 未 admitted（当前 draft）时 `collect` **fail closed**；即使传 `--execute-paid-runs`
    也不会派发。`collect` 通过维护树的 `DurableBaselineCollector` 调 durable API，不实现
    另一套研究算法；只支持 candidate arm，baseline arm 明确拒绝。
  - `resume-plan`：已有 terminal 记录的 case 不重派；失败记录保留而不是覆盖。
  - `summarize`：导入评审 CSV，计算 N/S/R/E、usable、重大错误、类别分母、P50/P95 墙钟、
    已知 token、失败保留与 cost=unknown；不把缺失费用写 0。
- `benchmarks/prepare_final_batch.py` + `benchmarks/final-batch-v1.json`
  - 120 final：A 30、B 24、C 18、D 16、E 16、F 16；calibration 12（每层 2）。
  - 132 个草案组合的候选对，候选/组唯一，calibration 与 final 不重叠；没有声称这些组合
    全部未在历史池出现（少数可能重合），也没有完成独立查重。
  - **准备状态**：`draft_pending_reference_authoring`，`eval_ready=false`；参考依据为
    `pending_authoring_verification`，没有 expected winner/参考来源正文；属于草案，
    不是已封存数据集，也不能作为评测通过证据。
- 指标汇总样例（**合成、不是真实结果**）：
  `D:\deepchoice-dsh\r9_batch_sample\batch-summary.md` 与 `.json`，只演示 N/S/R/E、
  unknown cost、失败保留 schema。

## 4. 当前准入状态与阻断

**未达到批量评测准入**，不得启动第13次或正式两臂运行：

1. **paired baseline 未适配**：维护树 durable 入口没有共享采集 + 单次综合基线的 collector；
   旧实验 `launch_pair/pair_worker` 属旧 `/research`，不能冒充产品入口验收。
2. **数据未就绪**：120 组是 deterministic draft，参考依据、expected outcome、评分和
   独立查重/暴露清理均待独立准备者完成；全部组标记为 unverified draft。
3. **预算未授权**：没有新的 LLM/Tavily/网页/评审额度；当前外呼为 0。
4. **解锁真实运行的前置**：完成 baseline 适配的离线代码+测试；独立准备/核验数据并冻结；
   运行身份（commit/manifest/模型/依赖/缓存/learned docs）冻结；获得整批预算授权。

## 5. 整批预算申请（唯一请求，不逐例请示）

本申请覆盖从数据核验到正式测量及评审；未获批准前执行 0 次外呼。所有数值为上限，
不是估算已花费用；未知供应商价格保持 unknown。

### 5.1 阶段与次数

| 阶段 | 内容 | 次数/上限 |
|---|---|---|
| P0 数据独立准备与参考核验 | 132 组（120 final + 12 calibration）独立作者/查重/冻结；每例参考来源核验 | 132 组；每例最多 6 个参考 URL（≤792 URL 检查）；无 LLM 研究调用 |
| P1 校准 | 12 calibration cases × 2 arms（candidate/baseline） | 24 次研究 run；不进入 final 分母 |
| P2 正式 | 120 final × 2 arms | 240 次研究 run |
| P3 重复性 | 预冻结 12 个 final case × 2 arms × 2 次重复（替代运行） | 48 次额外 run；不增加 case 数 |
| P4 评审 | P1/P2/P3 报告第一评审 + 失败/关键错误 100% 与通过项分层 25–30% 第二评审 | 最多 312 次第一评审 + 约 95 次第二评审；评审者类型单独记录 |

总研究 run 上限：**312**（24 + 240 + 48；不含节点内重试）。若 P1 发现基线/评分不可用，
在 P2 前停止；不把校准题转入 final。

### 5.2 每 run 与整批上限

- 每 run：沿用当前 durable `standard-enforced-v1` 上限（60,000 tokens、96 LLM calls、
  72 retrieval calls、900,000 ms active）；不得借评测放宽。另设研究侧 per-run
  外部页面尝试 ≤4、HTTP ≤12、单页 ≤15 s、响应保留 ≤1 MiB。
- 整批：LLM 请求 ≤ **20,000**；Tavily POST ≤ **10,000**；official 页面尝试 ≤ **1,300**；
  HTTP（含 redirect）≤ **4,000**；已知 token 汇总 ≤ **20,000,000**；总研究墙钟 ≤ **72 h**
  （按串行上界；实际预计 24–40 h）。批次达到任一上限即停止新派发。
- 评审/核验/运维时间：P0 估计 **30–50 h**；P1 估计 **8–12 h**；P2/P3 运行 + 第一/第二评审
  估计 **40–80 h**；总计估计 **80–140 h**。P4 的评审工时未知，须单独对账，不编造金额。
- 外部模型裁判/付费 benchmark：**0**。供应商费用 unknown；预算批准前不产生新费用。

### 5.3 停止线

- 安全、预算、身份、租约/实例权威、未知提交、数据/评分冻结异常：立即停止新准入并对账。
- 数据集 reference/authoring 未完成、baseline 适配未通过独立复核或身份不是唯一候选：
  不启动 P1/P2。
- 任何普通内容失败保留并计入；不逐例修代码、不换题、不择优补跑。
- 任一阶段失败保留结果与原始产物，不用未评审子集计算通过率。

## 6. 当前交付边界

- 本轮已实现：批量校验/防误跑/汇总/评审导入工具、draft 数据集、durable 用户链路离线测试。
- 本轮未实现：durable 共享采集基线适配、已验证参考依据、正式两臂测量、真实指标。
- 因此不能声称报告内容通过、基线公平性成立、百例评测完成或项目达到投递标准。
