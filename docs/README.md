# 文档入口与职责

更新：2026-09-29。开始后续工作只读下列当前入口，按任务需要补读契约；不要递归加载全部 docs 或 archive。
用户当前指令与仓库代码/可执行测试优先；历史“下一步”“待批准”不产生现行任务。

## 当前入口：每种事实只维护一处

| 顺序 | 文档 | 负责什么 | 不负责什么 |
|---|---|---|---|
| 1 | [交付范围](current-roadmap.md) | 本轮定位、收尾判据、已知限制与后续边界 | 历史全量优化路线、逐次流水 |
| 2 | [执行与协作](optimization-execution.md) | 复盘、成果粒度、发现偏离、授权及中断恢复规则 | 直接批准新付费实验 |
| 3 | [当前执行状态](o1-execution-status.md) | 研究准入账本、产品/控制身份、最新停止/收尾和证据定位 | 新任务排序 |
| 按需 | [历史S0诊断](product-optimization-s0-review.md) | 旧候选锁分、问题线索和当时依据 | 当前任务排序、自动恢复S1执行卡 |
| 按需 | [评估边界](product-effectiveness-optimization.md) | 评分、分母、冻结协议生效范围、新方案准入条件 | 改历史结果或自动启动批次 |
| 按需 | [历史P01资格](o1c-single-case-verification.md) | 对应旧候选的资格与证据、限制 | 当前候选放行或新的采样要求 |

2026-09-29用户采纳单场景最小展示验收：先检查已有报告，必要时按地图的有限次数核对，
证明一个真实请求可得到有依据的条件建议。DeepChoice 仍是单用户技术选型 Agent。
此前三场景目标退役且未达成；新目标 P01 初验 completed，但主评/独立内容复核 FAIL。
新目标已用 1/2 次研究名额，未具备实质修复方案，按停止条件收尾；第二次未提交。
累计研究112/156。当前 P01、较早 P04 的内容均未通过，P08无当前候选报告。
状态、账本和定位限制见执行状态，
本轮判据与剩余风险见地图。验证包继续后置。
旧v4及本轮停止根均不补跑；代码/工程通过不能改写为产品质量通过。
工程完成、有限开发交付与广泛质量研究分别记录。旧12/24/48格及完整S3要求已退役为
[历史路线](archive/roadmap-before-delivery-closeout-20260929.md)，不阻塞当前交付。12路并发不属于当前或近期目标，
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

[归档索引](archive/README.md)记录历史设计、评估协议、任务拆分和阶段证据，新增退役的完整优化地图；保留来源提交与原判断。
只在需要追溯一个特定事实时打开对应文件。归档文件顶部明确失效范围，原路径保留短跳转，避免既有链接失效。

两份历史会话交接移到本地忽略区 `notes/archive/20260921/`，原路径只保留失效提示；
下一会话交接也放 notes/，不加入公开文档，不重复整段对话。归档不改写 Git 历史。

## 维护约定

- 目标变更只改地图；运行结果只改状态与对应证据；测量规则只改独立冻结协议；执行经验只改执行规则。
- README 只展示概况并链接上述入口，CHANGELOG 只记录已交付变化，不再复制整条执行时间线。
- 历史解释必须带日期、案例/版本/分母；不得用“旧”笼统替代“哪个版本、是否仍适用”。
- 新的阻断按影响写入当前地图或执行状态；不会因为换 session/PR 就消失。不要为每次停线再新建长期规划文档。
- 会话结束前更新本地交接的目标、完成项、当前断点、有效授权、下一成果与必要证据定位。
