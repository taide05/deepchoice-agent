# 文档入口与职责

更新：2026-09-29。开始后续工作只读下列当前入口，按任务需要补读契约；不要递归加载全部 docs 或 archive。
用户当前指令与仓库代码/可执行测试优先；历史“下一步”“待批准”不产生现行任务。

## 当前入口：每种事实只维护一处

| 顺序 | 文档 | 负责什么 | 不负责什么 |
|---|---|---|---|
| 1 | [整体任务地图](current-roadmap.md) | 产品目标、全部优化方向、依赖、阶段、完成/停止标准、预算方案 | 逐次运行流水和实现细节 |
| 2 | [执行与协作](optimization-execution.md) | 复盘、成果粒度、发现偏离、授权及中断恢复规则 | 直接批准新付费实验 |
| 3 | [当前执行状态](o1-execution-status.md) | 研究准入账本、产品/控制身份、最新停止/收尾和证据定位 | 新任务排序 |
| 4 | [S0 开发集诊断](product-optimization-s0-review.md) | P01–P08 锁分、全问题表、严重性、首要根因和 S1 执行卡 | 保留集、最终产品或并发验收 |
| 按需 | [评估边界](product-effectiveness-optimization.md) | 评分、分母、冻结协议生效范围、新方案准入条件 | 改历史结果或自动启动批次 |
| 按需 | [当前候选资格](o1c-single-case-verification.md) | 当前 P01 资格与证据、限制 | 全产品/并发通过 |

2026-09-29 v4有界验证已停止并对账：P04完成，社区检索429后原卡停止，P08/P01未提交。
独立内容复核仍判选型可用性未通过：关键官方原文和安全验证计划已经呈现，但尚缺清楚的
条件选择，部署未验证被过度扩大为无法选型。按地图第7节记录这个核心缺口并结束本轮，
不自动追加付费卡或新规则；此前P01缺口也未获得本轮新报告验证。
实耗、评分、运行身份与停止证据只查执行状态；各停止根不可复用。
工程完成、开发收尾与最终产品验收分别记录。12路并发不属于当前或近期目标，
不从历史“下一步”、剩余额度或机器卡OPEN值恢复运行。
`o1-next-steps.md` 已退役为兼容跳转，不再维护另一份任务地图。

## 持续维护的契约与冻结证据

- [默认运行契约](phase1-runtime-contract.md)：生命周期、预算/Trace、HITL、恢复、安全等实现契约。
- [Phase 5 离线评估](phase5-offline-eval.md)：smoke-v1 操作与能力边界。
- [工程验收](phase5-engineering-acceptance.md)、[Phase 1 验收](phase1-acceptance-report.md)：相应阶段的已验证工程事实与残余风险，不能解释成待做路线。
- [冻结参考](o1-reference-audit.md)、[声明台账契约](o1a-evaluation-contract.json)、
  [报告绑定](o1-development-review-bindings.json)、[原子台账](o1a-development-claims.csv)：保留原路径和内容，避免破坏可执行检查和测量身份。
- [S0 绑定](product-optimization-s0-bindings.json) 与
  [S0 关键声明台账](product-optimization-s0-claims.csv)：绑定当前候选 serial-r1 的八份开发报告和 360 项逐处原子关键声明，
  不替换历史六报告分母，也不包含保留集报告内容。
- [S1 局部测量协议](../benchmarks/product-optimization-s1-constraint-aware-v2.json)：
  P04/P08 目标、P01 回归、身份/顺序/预算/评审/停止规则的机器可读冻结；不是付费执行授权或效果结果。
  v2 绑定解释保留修复；原 v1 仍保留用于复算 bcb4c87，不跨版本复用资格。
- [评估工具操作说明](../benchmarks/README.md)：CLI 用法，不能自行产生执行授权。
- [三案例串行测量卡v2](product-optimization-serial-check-v2.md)：离线验收后的冻结设计与候选身份；
  [机器卡](../benchmarks/product-optimization-serial-check-v2.json)已接到v2薄适配入口，离线验收后
  按持续授权完成唯一正式执行后停止；当前实耗/停止查执行状态，不把v2交给旧v1 CLI或再次执行。
- [三案例串行机器卡v3](../benchmarks/product-optimization-serial-check-v3.json)：本机忽略区设计卡的
  机器绑定，离线复核后前瞻激活；只读 audit 与实测准入分开，旧v2停止根不可续跑。
- [三案例串行机器卡v4](../benchmarks/product-optimization-serial-check-v4.json)：新候选的
  P04→P08→P01 身份与 v3 停止证据绑定；2026-09-29唯一执行已停止，OPEN冻结字节不授权重跑。

历史评分和 token CSV/JSON 都保留原分母/版本，不回填为当前候选；原始报告、快照、Trace、实验库留 outputs/。

## 归档与本地会话材料

[归档索引](archive/README.md)列出 18 份设计、评估协议、任务拆分和阶段证据快照，保留来源提交与原判断。
只在需要追溯一个特定事实时打开对应文件。归档文件顶部明确失效范围，原路径保留短跳转，避免既有链接失效。

两份历史会话交接移到本地忽略区 `notes/archive/20260921/`，原路径只保留失效提示；
下一会话交接也放 notes/，不加入公开文档，不重复整段对话。归档不改写 Git 历史。

## 维护约定

- 目标变更只改地图；运行结果只改状态与对应证据；测量规则只改独立冻结协议；执行经验只改执行规则。
- README 只展示概况并链接上述入口，CHANGELOG 只记录已交付变化，不再复制整条执行时间线。
- 历史解释必须带日期、案例/版本/分母；不得用“旧”笼统替代“哪个版本、是否仍适用”。
- 新问题先登记到本阶段问题表；不会因为换 session/PR 就消失。不要为每次停线再新建长期规划文档。
- 会话结束前更新本地交接的目标、完成项、当前断点、有效授权、下一成果与必要证据定位。
