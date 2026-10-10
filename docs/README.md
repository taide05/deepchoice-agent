# Codex文档入口与效力

更新：2026-10-10。用户当前指令优先；代码、manifest构建器、pyproject.toml和可执行测试
描述已实现行为。路线描述目标，不能把尚未实现的计划当成代码事实。

## 默认阅读顺序

| 顺序 | 文档 | 唯一职责 |
|---|---|---|
| 1 | [质量路线](current-roadmap.md) | 支持范围、A–D阶段/时间上限、交付成果与总边界 |
| 2 | [评估协议](product-effectiveness-optimization.md) | 现行跨场景开发测量、历史分母与封存验收边界 |
| 3 | [推进与维修](optimization-execution.md) | 实现粒度、验证节奏、无收益后的调整、持续授权 |
| 4 | [当前状态](o1-execution-status.md) | 已验证候选、实际账本、当前缺口和下一成果 |
| 历史按需 | [旧Q0四例诊断](quality-selection-q0.md) | 旧冻结附件入口，仅供定向回归和查证 |
| 按需 | [全仓审计与精简地图](codebase-audit.md) | 已有模块审计、代码根因、参数影响及结构修复证据 |
| 按需 | [运行契约](phase1-runtime-contract.md) | durable、预算/Trace、引用、安全、HITL和恢复边界 |
| 按需 | [评估工具](../benchmarks/README.md) | 已有工具能做什么、哪些入口只供历史复算 |

当前目标是十小时有效工时内交付可运行、可审阅的求职作品，先精简完整研究链路，恢复
有依据且有用的报告。2026-10-10已同步路线A–D计划、评估标准、执行规则及状态；当前
已按用户“继续”恢复执行，A未通过后提前使用C修复，并转入预定新请求检查；实际阶段与工时见当前状态。

- 阶段任务、上限、偏差与交付判据只维护在[路线第1节](current-roadmap.md)。
- 实际耗时、研究累计、已完成与尚未通过项只维护在[当前状态](o1-execution-status.md)。
- 内容标准及最终候选三类请求加一次重复的检查见[评估协议](product-effectiveness-optimization.md)。
- 精简方式、验证节奏和暂停/恢复边界见[执行规则](optimization-execution.md)。

主产品是一条完整持久化研究链路，旧兼容入口不构成第二条质量目标。活动预设已移除；
历史问题/报告用于定向查证，不产生默认开发题或自动批次。此前工程修改已验证，但真实
内容仍未达标。旧Q0–Q3阶段、旧12/24/48格及历史“下一步/OPEN”不覆盖本次A–D安排。
长程广度声明须有相应证据，最终24继续封存，不能用本次小样本冒充普遍可靠。

## 持续有效与冻结保留

- README负责产品、启动、使用和已知限制；CHANGELOG记录交付，均不再充当优化流水。
- [Phase 5离线评估](phase5-offline-eval.md)、[工程验收](phase5-engineering-acceptance.md)、
  [Phase 1验收](phase1-acceptance-report.md)保留阶段事实与日期；不据历史测试数推断今天的质量。
- `o1a-evaluation-contract.json`、`o1-development-review-bindings.json`、
  `o1a-development-claims.csv`、`product-optimization-s0-bindings.json`和
  `product-optimization-s0-claims.csv`是历史冻结证据，保留路径和字节，不作新测量依据。
- [旧参考表](o1-reference-audit.md)绑定历史案例；参考和日期不当成当前网页事实或新保留集。
- [serial-check-v2设计](product-optimization-serial-check-v2.md)被机器卡按路径及SHA绑定，
  **原地冻结保留**；其中“未运行/下一步”是历史文字，当前不可执行。v1–v4和repair-pair
  等机器卡、原始产物与评分不改；OPEN字段不授权重新执行。

## 归档与兼容入口

[选择性归档](archive/quality-direction-20261005/README.md)保存旧Q0四例、混合评估协议和截至2026-10-05的逐轮流水原文。[旧归档索引](archive/README.md)收录单场景路线、执行规则、评估历史、旧执行流水、
S0诊断、旧资格、README交付历史和旧工具指南。索引标明来源提交或原文件hash；本次三份快照原字节保留，相对链接按原路径解读。S0和资格旧路径保留短跳转，当前入口不再要求读历史全文。
既有PRD/设计、O1拆分和历史handoff跳转继续失效。默认不递归加载archive或notes。

会话交接、临时方案、执行明细与原始报告放忽略区notes/outputs；不用每轮创建新长期文档。
同一事实只维护一个入口。下一轮开始按上表顺序读，再依据具体问题打开契约或某条历史证据。
