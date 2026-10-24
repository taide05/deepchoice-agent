# 交接给 dsh：后续由用户与你直接推进

更新：2026-10-24。本次用户明确结束 Codex 对最后开发阶段的规划与审批，由用户和 dsh
共同确定接下来的目标、路线、时间与交付安排。直接从当前代码和已有材料继续，不需再等 Codex 指令。

## 先读这一页即可开始

本次已将 AGENTS、路线、执行、评估和批量准备文档收拢。旧十轮/八轮/十小时计划、每包仅一个
全新题、固定11/12晋级、多轮独立复核、所有修改交付前必须全套等流程不再是默认要求。
开发可以复用旧题和失败材料、连续修改和复测。普通失败不自动要求停止开发或申请“下一轮”。

目标仍是尽快修好个人技术选型项目，用真实可展示能力和指标支持投递。百例评测、公平基线等
原目标没有被宣布完成，也没有被本次擅自替换成小样本目标。如何安排、修改或分期交付由你与用户决定。
Codex最后给出的10小时方案、40–80小时估算均不作为你的活动计划、硬期限或完成承诺。

本次仅交接文档，没有新增研究额度。最近两例授权已用完；下一次整体委托确定资源后，
在范围内自主推进，不要求逐步、逐例或跨阶段再找 Codex 审批。真实费用、预算和用户数据仍须保护。

## 代码与工作树

| 项目 | 核对结果 |
|---|---|
| 当前产品目录 | `D:\deepchoice-agent`，`codex/generic-selection` |
| 产品代码基点 | `fef61b8`，本次其后的变更仅文档 |
| 当前产品入口 | durable `/api/v1/tasks/*`，FastAPI + Streamlit |
| 用户修改 | 维护树 `learned_docs.json` 保留 |
| 实验目录 | `D:\deepchoice-precodex`，`precodex/deepseek-adapter`，`b080213` |
| 实验材料 | `learned_docs.json` 修改与17项未跟踪材料保留，未合并 |
| 历史尝试 | 两个旧stash及patch保留，本次未恢复 |

启动（使用已配置的项目环境，不打印密钥）：

```powershell
D:\deepchoice-agent\.venv\Scripts\python.exe -m uvicorn deepchoice.server.app:app --host 127.0.0.1 --port 8000
D:\deepchoice-agent\.venv\Scripts\python.exe -m streamlit run frontend/app.py
```

前端配置 `API_BASE` 指向实际服务。涉及运行时才查
[运行契约](phase1-runtime-contract.md)。实验树旧接口不代表这个产品入口。

## 已有成果与最新事实

`fef61b8` 统一了整份5个保存来源、每条分析最多4个不同事实的活动契约；去掉来源展示的隐形5行
限制，按canonical URL组织入口；保留多阶段quality signals；新增批次授权账本。
这些是可修改的实现选择，不是本次交接要求永久保留的容量标准。
dsh交付记录为3866测试通过；本次文档交接未重跑测试，也不宣称内容因此达标。

此前dev6：12份产出、0/12可用；6份无analysis。8/44是所需事实的证据覆盖，34/35是已写
论断的完整支持；分母不同。旧开发子额度执行28而授权24，超4次仍保留。

最近两例诊断（`fef61b8`，各一次）：

| case | 实际损失 | 产品判断 |
|---|---|---|
| A-02 Temporal/Celery | 综合5行收2行，3行shape拒绝；校准2→1；自审source_checks再删最后1行 | 最终无分析，不可用 |
| E-01 SES/Postmark | 综合、校准、自审均5→5；来源薄弱、条件偏好只在正文而未成为结构字段 | 可作条件/不足证据简报，不能当已验证推荐 |

A-02独立诊断报告通过隔离checkpoint恢复了一条以两条verified事实为依据的Temporal条件选择，
最后被source_checks拒绝；本次交接依据该诊断记录，没有重新读取私有checkpoint。
它证明曾有有价值分析，但不证明这条分析已回答所有核心要求。3条shape拒绝的细因仍未知。

E-01正文已有Postmark条件偏好，不能仅因结构choice为0就说模型完全没有选择。
其官方获取失败、route_unsupported和缺失依据仍影响建议可信度。
两例都没有保存4个预列参考文档；这提示供给/选择问题，精确URL未命中本身不证明
相关文档曾检索到后被删除。定位promotion时看实际前后输入，不把该统计当完整因果证据。

这些结果可直接用于修复与回归，无需另做一轮全仓诊断。你可选择更直接的方案，
不受“只能修某一个已证明原因”或“必须保留所有既有过滤”的限制。

## 已用资源

最近授权 `r10-diag2-exposed-20261024`：2/2已用，无未决预占。
两例总计47,948 tokens、28 LLM、12 retrieval、2 Tavily POST、225.745秒active，费用unknown。
按最新诊断累计：62 tasks、623 LLM、约1,007,074 known tokens、62 Tavily POST。
这是产品研究用量，不包含编程助手会话token；不要与UI显示的助手总用量混算。
历史额度不能换ledger重新计算；新的整体预算由用户与你决定。

## 可直接复用的材料

| 位置 | 用途 |
|---|---|
| `D:\deepchoice-dsh\r10_diag2\diagnosis.md` | 两例阶段诊断、任务身份与用量 |
| `D:\deepchoice-dsh\r10_diag2\review\review.md`、`review.json` | 助手内容评审，非专家签字 |
| `D:\deepchoice-dsh\r10_diag2\candidate\development\` | 报告、快照 |
| `D:\deepchoice-dsh\r10_diag2\authorization.sqlite` | 已用完的两例账本，不作为新额度 |
| `D:\deepchoice-dsh\r10_offline_audit.md` | 前次离线核对，读取时按当前消费者校对 |
| `D:\deepchoice-dsh\r10_dev6\review\`、`r10_result.md` | 12题失败与超限记录 |
| `D:\deepchoice-dsh\r10_data\` | dev/calibration/formal草案；参考prepared_unverified，正式未seal |
| `D:\deepchoice-dsh\r10_selection_scope_package.patch` | 未采用的旧尝试，不整包恢复 |
| `benchmarks/final_batch.py` | 当前批次/账本/汇总入口 |
| `D:\deepchoice-dsh\r10_final_baseline.py` | baseline草案，不是已验收的完整配对实现 |

新路线可按需要使用已有集。若要保留未见评测，勿把其答案用于该版本开发；若决定用于开发，
标记暴露即可，不能继续称未见。132题、六层配额、正式参考核验和完整基线都尚未完成；
不必先补齐所有准备才开始修回答。

## 代码定位线索（按需，不是待办清单）

- `agents/conclusion_synthesizer.py`、`utils/fact_selection.py`、`utils/question_packet.py`：联合来源选择、问题回答与绑定。
- `utils/decision_analysis.py`、`utils/evidence_choices.py`、`citations/`：分析结构与引用校准。
- `agents/self_reviewer.py`、`utils/analysis_review.py`：source_checks及分析保留/修订。
- `formats/`：用户实际看到的正文、条件偏好和来源。
- `retrievers/`、`outbound/`：候选资料获取和失败语义。
- `benchmarks/final_batch.py`及其账本依赖：批次授权与恢复。

## 接手权限：可改变产品路线，不只是修补原链

你与用户直接决定后续目标、实现和交付。Codex 不再负责批准、安排轮次或判定能否继续。
你可以删减/合并验证和自审、改变来源提升、调整容量/模型/结构，按实际报告收益选择方案。
不用保持“所有分析先全量核验才允许显示”“自审失败全部撤回”“置信度只能下降”等旧设计。
可以边实现边复测、准备演示和指标，不必先完成新的全仓审计、全套评测平台或最终数据集。
普通内容失败不会让委托自动终止；资源使用在用户与你约定的范围内连续执行。

安全与真实记账保持正常：保留用户数据、不泄漏秘密、不隐瞒费用、不伪造结果。
这不要求维持每一个保守的生成/过滤规则。代码层面的限制如果妨碍新设计，可以连同消费者修改，
而不是仅在文档里宣布它已解除。没有新的产品补丁被本次交接偷偷应用。

## 本次深入核对及实际改动

核对范围是本仓库 33 个文档入口（根 AGENTS/README、benchmarks/README 与 docs 顶层），
另检查归档索引、CHANGELOG 的活动说明、CI 验证入口及旧卡的代码引用。不是对所有历史档案
和知识库语料逐篇重写，也没有假称修改了其他助手的全局规则。

| 层级/文件 | 实际处理 |
|---|---|
| `AGENTS.md` | 删除旧单例/晋级/固定轮次默认流程；明确可改变验证链、自审、模型与容量；验证按风险 |
| `README.md` | 删除整行失效与修订禁止的设计宣言、旧最终24格门槛；改为当前实现和已知改进空间 |
| `docs/phase1-runtime-contract.md` | 1,768行收为275行；移出逐轮语义过滤规则，保留事务/恢复/预算/安全说明；单列可调整策略 |
| `docs/codebase-audit.md` | 911行旧审计改为42行代码定位；旧OPEN与下一动作不再进入活动正文 |
| `benchmarks/README.md` | 212行混合历史指南改为72行当前工具说明；移除旧准入根、固定配额预留、逐阶段批准规则 |
| 评估/执行/路线/批量准备 | 支持开发复用、连续迭代、条件建议与适量评审；旧11/12、全面部署审计及百例先行不再管住开发 |
| Phase1/Phase5验收记录 | 保留历史测试、结果和风险；删除“进入下一阶段前必须”及“指标稳定后才能做面试材料”的未来门槛 |
| `o1-reference-audit.md` | 保留参考表，移除仍在等批准、固定12题双评冻结的活动命令 |
| `phase5-offline-eval.md` | 说明何时复用/更新smoke；不是每次开发的全套验收关卡 |
| 其他15个历史入口 | 核对其已是历史导航/冻结输入，不把旧任务或旧额度重新激活 |
| 归档索引及7份原文副本 | 原字节与hash可追溯；无需默认阅读，不改原报告或历史评分 |

### 有意保留的范围

- `docs/product-optimization-serial-check-v2.md` 同时被旧 Python/JSON 机器卡按路径和hash引用。
  它保留原字节以免文档清理破坏历史输入；AGENTS和工具指南已将它明确排除出活动指令。
  不使用该旧卡指挥新开发。原文也有归档副本。
- 现有代码内5/4容量、绑定/撤回、final_batch数据形状、准入等仍实际执行；本次是文档交接。
  dsh可按新方案修改代码，不需要为继承旧语义限制向Codex申请许可。
- CI、生产代码、测试、原始报告、评分、seal、数据库、用户learned_docs和stash未改。
- 实验树、`D:\deepchoice-dsh`本地运行材料、外部职业文档和助手全局设置未修改。
  当前开发以维护树为入口；其他目录若含旧Codex阶段计划，仅作历史背景，不重新约束本次接手。

旧活动规范全文见 [原文归档](archive/retired-contracts-20261024/README.md) 及Git `fef61b8`、
`611b1b2`。后续维护一份当前任务说明和受影响用户文档即可，不要求把进度复制进全部旧文档。

这份交接不规定你的下一修复路线，也不要求再完成一轮交接审计。读完当前身份和两例诊断后，
直接与用户确定下一步即可。

本次文档检查：33个入口与两个归档索引的本地链接/代码块闭合检查通过；7份原文副本hash一致；
冻结serial设计卡字节保持不变；diff空白检查通过。未为纯文档调整重跑产品或测试。
