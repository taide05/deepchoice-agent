# 当前项目状态

更新：2026-10-24。后续由用户与dsh直接规划和执行，入口见
[交接](next-session-product-optimization-handoff.md)。本页只记录事实，不设置下一阶段审批。

## 身份与已完成能力

- 产品代码：维护树 `D:\deepchoice-agent` / `codex/generic-selection`，`fef61b8`。
  之后的本次提交仅修改文档。用户 `learned_docs.json` 修改保留。
- 实验树：`D:\deepchoice-precodex` / `precodex/deepseek-adapter` / `b080213`；
  learned_docs修改及17项未跟踪材料保留，没有合并。
- durable API、任务/事件/恢复/HITL、报告查询与导出已有实现；不能据此推导内容普遍可用。
- 最近离线收口统一容量契约、来源展示、阶段诊断及批次授权账本。
  dsh记录3866测试通过；本次文档调整没有重跑套件。
- 没有新增push、历史改写、产品修改或付费运行。

## 最新内容与诊断

dev6的12份报告：0/12可用，6份零analysis；该历史结果不改。
所需事实支持8/44与已写论断支持34/35是不同统计，均不能代替整份报告的可用性。

两例真实诊断已执行并结束：

| 案例 | 结果 | 关键观察 |
|---|---|---|
| A-02 Temporal/Celery | 不可用 | 综合shape拒绝、引用校准和自审source_checks形成级联丢失，最终0 analysis |
| E-01 SES/Postmark | 条件/不足证据简报可用，非已验证推荐 | 5条分析全部保留，正文有条件偏好；决定性来源不足及结构化表达有缺口 |

两例不是正式通过率或稳定性证明。A-02的最后一条条件选择来自dsh独立诊断的checkpoint恢复；
3条shape拒绝具体内容未保存。E-01不应仅按结构choice计数判定“没有任何条件选择”。

完整原始诊断及评审：`D:\deepchoice-dsh\r10_diag2\`。
历史dev6、离线核对和r10结果见交接里的材料表。

## 用量与预算事实

- 历史开发32 + 28 = 60 tasks；其中28次超过24次子额度4次，记录保留。
- 新两例授权 `r10-diag2-exposed-20261024` 已用2/2，无未决reservation。
- 两例新增47,948 known tokens、28 LLM、12 retrieval、2 Tavily POST、225.745秒active。
- 诊断记录累计62 tasks、623 LLM、约1,007,074 known tokens、62 Tavily POST；费用unknown。
- 这些是研究产品用量，不能与dsh/Codex编程会话token合并。
- 本次文档交接不新增额度；后续由用户与dsh整体约定预算，范围内连续执行。

## 可继续利用及未完成项

已有失败材料可以用于开发复测，不再限制“所有旧题只能取证”。来源选择、分析保留和条件表达
仍有改善空间，允许用户与dsh直接选方案，不指定新的强制修复顺序。

132题草案的参考仍prepared_unverified，formal未seal；durable共享证据baseline仍无完整正式
比较结果。尚无该最终版本的120题正式指标。可先使用已有真实成果准备展示，指标只写实际结果。
原投递目标未被宣布达成，未来验收和时间由用户与dsh决定。

## 历史记录位置

此前逐轮结果、超限、停止决定及评测口径全部保留在Git与本地原件。
原状态长文：`git show fef61b8:docs/o1-execution-status.md`。
旧文中的“当前”“下一步”“必须停止”等只描述当时，不作为新路线的执行命令。
旧十轮/十小时和最后两例提案均不再是待执行计划。
