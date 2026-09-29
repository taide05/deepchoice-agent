# O1-C 真实单例验真

> 2026-09-29效力说明：本页保留对应历史候选的事实、评分与当时计划；其资格/执行卡及
> “下一步”不指导当前开发，不要求继续完成旧矩阵。现行范围见[交付地图](current-roadmap.md)，
> 最新候选与实耗见[执行状态](o1-execution-status.md)。历史问题仅作为需核对的线索，不能当作全部待办。

## S1 解释保留修复候选：2026-09-22 执行，2026-09-23 锁分

**83852d8 的 P01 执行完成，但内容资格不通过。** 冻结数据集仍为 product-baseline-v1
v1.0.0（2026-09-16）；主评与独立助手复核一致：必答 **5/6（2、2、1）**、冲突 **2/2**、
已确认 **major 1**。没有同窗口配对，不能据两份单例的分数差宣称因果改善；非盲评，
人类校准 not_run，未读取保留集报告或反馈。运行器曾自动显示总用量，节点成本在内容锁分后读取。

L78/L84/L89–90 已保留低运维、单 writer 及条件性选择的解释；L79/L85/L94 给出锁频率、
等待时长等观察方向，但适用阈值未定义。阻断项 **S1-P01-MIGRATION-01** 位于 L96：
在双写、切读、切写之后，只建议回退 SQLite 快照，没有新增写入回放、逆同步或禁止回退
条件。这是已确认的数据完整性边界遗漏，并非实际发生了数据丢失。“待验证”标签不能补足
该边界。L95 的恢复失败即考虑换 PostgreSQL、旧快照回退缺恢复点/新增写入界限另记 high，
不重复计 major。旧的解释丢失问题得到局部展示证据，但整个 S1 资格门禁未通过。

独立复核后锁定 **36 个逐处原子关键声明**：supported 12 / partial 6 / unsupported 0 /
unknown 11 / uncited 7；来源 eligible 0 / ineligible 19 / unknown 17；系统逐原子
unknown 20 / unsupported 16。原系统 36 次检查（unknown 13、unsupported 23）是另一分母。
完整支持率为 12/36，适用来源确认覆盖率为 0/36；unknown 不被解释为事实错误。
复核将截断 WAL 片段的一项 unsupported 改 unknown，排除两条纯监控指令，并拆开双写/影子读。

本地报告/快照在 outputs/s1-qualification-20260922-uncertain-analysis-v1/qualification/collections/
serial-r1/development/；锁分在 outputs/s1-qualification-review-20260922-83852d8/main-review.json。
报告 SHA256 eec87fc291903f8f60da12dd6353e8d9c5fc2f675e90fa3054fd740882261d2a；快照 SHA256
07d8c2247547548065203f0d5c109ed0da5c5efffd2add39bccaf49e789ff27a。原始报告不修改、资格不补跑。

## S1 约束感知候选：2026-09-22

**bcb4c87 的 P01 执行完成，但内容资格未通过；正式局部配对尚未启动。**
使用冻结 product-baseline-v1 v1.0.0（2026-09-16）的 P01；不是重复采样效果对照。
主评与独立助手评审锁定必答 **2/6（1、0、1）**、冲突 **1/2**、已确认 major **0**，
qualification blocker 为 S1-P01-CONTENT-01。评审非盲、人类校准 not_run，未读取保留集正文。

报告 L87/L92 保留 SQLite 条件分支与起步行动，故不是完全无行动；但 L67/L72 顶层退回
“暂无唯一胜者/再决定”，L76–83 中六项解释变成通用 unknown，未解释 SQLite 写串行化与
PostgreSQL 运维成本。迁移方向可见，但缺门槛及阶段验证。未知未被当作事实错误；没有命中
冻结重大错误条件。资格失败不应靠删除未知标记或放宽抓取安全来解决。

独立复核后冻结 **20 个逐处原子关键声明**：supported 14 / partial 5 / unsupported 1，
来源 eligible 0 / ineligible 20，系统投影 unknown 20。支持度来自当次保存片段，既非权威
事实核验，也非本项目适用性证明；系统原始 38 项检查（0 verified / 7 unsupported /
31 unknown）是不同分母。没有配对改善声明，不与原候选 43 原子的比例直接作因果比较。

本地证据：outputs/s1-qualification-20260922-constraint-aware-v2/qualification/collections/serial-r1/
下 development/reports/P01.md、development/snapshots/P01.json；锁分及独立复核差异合并在
outputs/s1-qualification-review-20260922-bcb4c87/main-review.json。执行身份、前置、账本和
收尾以[当前执行状态](o1-execution-status.md)为准。原始结果保持不变；后续修复尚无新资格。

## GitHub 响应中断修复候选重新资格：2026-09-21

**候选 `d23c9480b9f368f8ec75ec44ee7e25c64146d4be` 的助手暂定单例测量资格通过。**
离线生产验收为 134 项聚焦与 1570 项全套通过；五个 PR2B 控制入口重绑定后为 135 项聚焦与
1570 项全套通过。资格使用全新产品/检查点数据库、原冻结知识种子及 cold-in-research，
不与任何旧候选或停止根拼接。

- 前置五类路由 5/5、Tavily POST 200、DeepSeek JSON/tool 2/2；research run 0。依赖、配置、
  模型端点、代理、embedding、dataset、manifest/registry 与候选一致。
- 第一次资格 runner 已准入任务，随后把一次 5 秒 health 连接异常作为立即停线；该根保持不变，
  计为第 61 个 research run。fresh v3 P01 completed，为第 62 个 run；manifest
  `3a7cd59683104f31c9e43f2b52defdef2c3c2bdf3fe48e5853482d9b0dddcd4a`，wall 55,375 ms、
  active 53,518 ms，10 LLM / 6 retrieval / 16 external，0 failed、0 LLM/node retry。
  输入 9,119、输出 1,931、合计 11,050 tokens，usage/cache 完整。
- 六源 envelope 全部 success，结果数 Tavily 7 / Chroma 4 / GitHub 7 / arXiv 7 /
  community 0 / official 2，partial_failures 空。系统原始引用投影为 verified 0 /
  unsupported 10 / unreachable 0 / unknown 32；独立逐原子映射见下项。
- 独立复核排除一条纯证据强度标签并校正三条支持度及七条系统映射。冻结分母为 **43 原子**：
  supported 19 / partial 15 / unsupported 9；来源 eligible 0 / ineligible 34 / unknown 9；
  逐原子系统投影 verified 0 / unknown 36 / unsupported 7。必答 5/6、冲突 2/2、重大错误 0、
  qualification blocker 0；非盲 assistant_review，人类校准 not_run。
- 主要非阻断限制是备份/恢复、FTS5、PostgreSQL 并发比较及场景阈值缺少合格保存片段；
  “single-thread writing” 只能解释为同一时刻一个 writer/写事务。资格不证明最终质量、并发、
  主机容量、备份恢复、FTS5 适用性或人工验收。
- 产品/检查点库 quick_check 均为 ok，task/run/result completed 且 immutable result 为 1；
  25 个 health 样本、0 health failure，heartbeat failure/lease loss 为 0，最低可用内存
  1,409,249,280 bytes，服务自然退出 0、asyncio runner returned、50400 端口关闭。
- 原知识种子 hash
  `e55ddcac30d0e498c6e5ae02cb40d1bae95eb2831fda71e924ed9211b76466e4` 未变；已使用副本 hash
  `0e93ddc363214f2bd7ae9abb23ee1f6a831d0b495a08fbb1b2c9b06fa5491cb2` 且禁止复用。
  校正后主审 hash `a4dbd70c32f140290ef61d8bd84535052404698cc44c25d6f3bbc779b5b70c40`，
  独立复核 `979836f295fcad37fe98cc9629866378db3a7170503bf7469afe503d4c163149`，
  候选冻结 `5e185da8bc31c5d91536d1004e9227347a7f9ef489c4761f31632ddab891099c`。

资格冻结时累计为 62/110；随后 24-run 停止根达到 86/110，再获上限 134 的新根
准入 4 个 run 后因 HTTP 521 收尾，当时累计 **90/134**。该历史资格只覆盖 d23c948，
不覆盖 S1 及其后续修复。正式配对与并发门禁未完成。最新计数以[执行记录](o1-execution-status.md)为准；
后续任务以[整体地图](current-roadmap.md)为准，本文件只维护资格及其证据。

## 历史资格

更早候选和 C1/C2 实施记录见 [历史资格快照](archive/product-optimization-20260921/qualification-history.md)。
其中待办与额度均属于当时语境，不再作为当前执行入口。
