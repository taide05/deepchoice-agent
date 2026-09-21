# O1-C 真实单例验真

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
准入 4 个 run 后因 HTTP 521 收尾。当前累计 **90/134**，产品候选资格仍有效，
正式配对与并发门禁未完成。最新计数以[执行记录](o1-execution-status.md)为准；
后续任务以[整体地图](current-roadmap.md)为准，本文件只维护资格及其证据。

## 历史资格

更早候选和 C1/C2 实施记录见 [历史资格快照](archive/product-optimization-20260921/qualification-history.md)。
其中待办与额度均属于当时语境，不再作为当前执行入口。
