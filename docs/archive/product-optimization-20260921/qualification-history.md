> 归档快照：2026-09-21。本文只保留当时事实与决策；其中“当前”“下一步”“待批准”均不是现行指令。
> 当前入口：[任务地图](../../current-roadmap.md)、[文档索引](../../README.md)。原文来源：40f9266 工作树。

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
正式配对与并发门禁未完成。最新计数以[执行记录](../../o1-execution-status.md)为准；
后续任务以[收敛规划](../../o1-next-steps.md)为准，本文件只维护资格及其证据。

## 查询隔离候选重新资格：2026-09-21

> 历史状态：该资格在当时通过；后续 GitHub 响应中断生产修复改变了生产代码，新候选必须
> 重新资格。本节保留原分母和证据，不代表当前冻结候选。

**候选 `09f9b66cf114953c09ebe928c1c081667647db16` 的助手暂定单例测量资格通过。**
这是并发 API 查询隔离生产改动后的新资格，使用 product-baseline-v1/1.0.0 的 P01 × 1、
全新产品/检查点数据库、原冻结知识种子及 cold-in-research；不与 `15ca251` 或任何旧报告拼接。

- 新前置五类路由 5/5、Tavily POST 200、DeepSeek JSON/tool 2/2；research run 0。
  数据集、依赖、配置、端点、代理、embedding、manifest/registry 及知识种子身份与候选一致。
- P01 completed；manifest
  `3a7cd59683104f31c9e43f2b52defdef2c3c2bdf3fe48e5853482d9b0dddcd4a`。
  active 71,620 ms；21 LLM / 6 retrieval / 27 Trace calls，全部 succeeded；
  输入 12,568、输出 2,717、合计 15,285 tokens，usage/cache 完整，0 retry、0 budget denial。
- 六源 envelope 全部 success，结果数 Tavily 7 / Chroma 4 / GitHub 7 / arXiv 7 /
  community 0 / official 2，partial_failures 空。系统引用投影为 verified 0 /
  unsupported 7 / unreachable 0 / unknown 49；unknown 不等于事实错误。
- 独立复核后的完整分母为 **59 原子**：supported 34 / partial 14 / unsupported 8 /
  uncited 3；来源 eligible 0 / ineligible 52 / unknown 7；逐原子系统投影
  verified 0 / unsupported 6 / unknown 53。必答 5/6、冲突 2/2、重大错误 0，
  qualification blocker 0；非盲 assistant_review，人类校准 not_run。
- 主要非阻断缺陷是 `zero operations` 绝对化、10k DAU 与 100–1,000 RPS/90-10
  单源示例，以及备份一致性、FTS、迁移触发缺合格绑定证据；不能写成高质量证据通过。
- source-aware 遥测只允许官方 safe-fetch 使用产品契约的 HEAD/GET；一次官方 GET
  `route_unsupported` 保持 typed failure 与引用 `unknown`，其他异常仍 fail closed。
  31 个资源样本最低可用内存 1,217,785,856 bytes，heartbeat failure/lease loss 为 0；
  服务正常退出码 0，产品/检查点库 quick_check ok，task/run/result 一致且租约清空。
- 原知识种子 hash
  `e55ddcac30d0e498c6e5ae02cb40d1bae95eb2831fda71e924ed9211b76466e4`
  运行后未变；已使用的 profile 副本发生预期运行时变化且禁止复用。
  主审 hash `3c0828e7ab734b7faca0349e572caeb26acd71c91a95db40ed00800d59234dcc`，
  独立复核 `2961c0f2d137ad3d56dd7907fb9902e51aefc30154693e1cc65ae70f17ff3e0b`，
  候选冻结 `d1f5b3d6209c5a7e16356588fe75331812a6feaa809904c68fb14b6d9d68af00`。

本次资格在当时是第 36/84 个 research run；当时计划用第 37～84 个执行完整
12 serial + 12 concurrent × 2 配对。后续停止与 109 上限见当前任务卡；控制器当时的
重绑定验收为 50 项聚焦与 1559 项全套通过、
0 failed（187.96 秒），py_compile、pyflakes 与 diff 检查通过。资格不证明并发容量、硬件稳定、
最终报告质量或人工验收。原始报告、快照、Trace、telemetry 与审查包留在 ignored `outputs/`，不提交。

## O1-PR2B 修复候选重新资格：2026-09-21

**候选 `15ca251a89ff996bc787435d8965a918a89437f6` 的助手暂定单例测量资格通过。**
本轮只执行 P01 × 1，使用全新产品/检查点数据库、原冻结知识种子和 cold-in-research；
不与旧候选报告拼接。持续授权 49 个研究 run 已使用资格 1 个，正式两轮剩余 48 个。

- 前置 06:29:14–06:29:30 UTC：五类路由 5/5、Tavily POST 200、DeepSeek JSON/tool 2/2；
  非 LLM HTTP 8、Tavily POST 1、LLM 2，research run 0。依赖/配置/模型端点/代理/数据集/
  manifest/registry 与候选一致；知识种子 hash
  `e55ddcac30d0e498c6e5ae02cb40d1bae95eb2831fda71e924ed9211b76466e4`。
- P01 于 06:33:31–06:35:19 UTC completed；task `205b1912-bd86-44a0-af5f-b39ff4a0618e`，
  run `04cb62cb-2bac-4bc6-94e2-7ede035102da`，manifest
  `3a7cd59683104f31c9e43f2b52defdef2c3c2bdf3fe48e5853482d9b0dddcd4a`。Wall 108,282 ms /
  active 107,276 ms；11 LLM / 6 retrieval / 17 Trace calls，0 failed、0 LLM/node retry。
  输入 9,627、输出 2,287、合计 11,914 tokens；usage/cache 11/11 完整，hit 512 / miss 9,115。
- 六源均 success、partial_failures 空。系统 50 项投影为 verified 2 / unsupported 24 /
  unreachable 0 / unknown 24；这不是语义质量评分。产品库 quick_check ok，task/run/result
  completed 且 immutable snapshot/report 与采集原件相等；run heartbeat 10 success / 0 failure /
  0 loss，实例 authority 有效。停机后服务 PID 与 8021 监听均不存在；exit code unavailable，
  因而只声明进程/监听已停止和持久结果一致，不声明自然 exit 0 或 guard 清理已证明。
- v4 完整分母 68 原子：supported 31 / partial 22 / unsupported 1 / uncited 2 / unknown 12；
  来源 eligible 7 / ineligible 52 / unknown 9；逐原子系统投影 verified 2 / unsupported 29 /
  unknown 37。必答 5/6、冲突 2/2，冻结重大错误 0；非盲 assistant_review、人类校准 not_run。
  “零运维”在 5 处绝对化，与报告自身监控、备份和迁移要求矛盾，是重要非阻断缺陷并使
  运维比较只得 1/2；不能把本次资格写成高质量证据通过。
- 动态 pinned CONNECT/TLS 能力仍 unavailable：快照有 24 项 network_uncertain，运行投影
  http_calls=0，未保存传输层证据；前置静态 provider 200 不能代替。该能力盲区不阻断本次
  单例测量资格，也不证明并发、硬件稳定、最终产品质量或 O1 完成。

本地主审、68 原子台账、独立复核、终态/知识/关停审计与候选冻结在
`outputs/o1-pr2b-qualification-p01-20260921-15ca251-standing/review/`；原始报告和快照不提交。
主审 hash `3ef487fd8b247d9e2f1d5549cd29cb1963eeaaab1254d14493fda3e0524809c2`，
独立复核 `c264ee56732cb2b0081ea2b8f15af11f44d81e3773ccd19d945aa50f6b053ab9`，
声明台账 `9c28ff747c8b3ccb4de9eb9722d30dd91fcded4a2aa5e5e97c136c8e341409f8`，
候选冻结 `1f47cf1e3c0e9b8deb37fb43ce1a3040927c2c598b458e8328bdda4714b5f050`。
候选生产代码此前 103 聚焦、1539 全套、smoke 12/12 及独立代码复核通过；本轮 PR2B
控制链候选重绑定及一致性门禁另通过 33 项聚焦与 1540 项全套、0 skipped（184.26 秒）。

## O1-PR1 新候选单例：2026-09-18

**O1-PR1 已完成：助手暂定单例测量资格通过，候选已冻结。**
候选 `7d622fd4916dad950ca077924327647a1f8f12c0` 的 P01 单例、完整声明台账及独立复核闭环。
原研究额度累计 **46/48**，剩余 2；PR2/PR3、批次、O2 和发布未启动。
下面是本候选的独立测量，不能给旧结果换标签，也不能当正式串并发或人工产品验收。

- 数据集 product-baseline-v1 / 1.0.0，冻结 2026-09-16，分母 **P01 × 1 run**，hash
  `e0317ddeaa2b37526f5a7261d8df26217b75619d6c46bcd1bc8705895f16981f`。
  Python 3.12.4，依赖 hash `c07764a225a2eef37b2ee47dacdd1dec0efac5cd263c4522b5c121c50a40493b`。
- 前置 04:53:21–04:53:41 UTC，五源 5/5；非 LLM HTTP 8、Tavily 付费 POST 1、LLM 2。
  原生 JSON/tool strict/schema valid、无截断；准备输入 313 / 输出 36 / 合计 349 token，
  hit 128 / miss 185。准备和研究分账，金额 unavailable；旧限流及启动失败记录保留。
- P01 准入 04:54:59 UTC，task `e4fe457c-f8b8-4fe8-9f43-064100ddd116`，
  run `73d91c8a-5a93-4941-80ad-046d7b4e65f2`；manifest
  `3a7cd59683104f31c9e43f2b52defdef2c3c2bdf3fe48e5853482d9b0dddcd4a`，registry
  `15cb66f6602a7f36090c1337f983ecbdbb3c74e77d7c9ca52c6c3c5ba799c850`，environment
  `fef298b4403b281d9639227eb1c8504c4f447bee33086d87cf8e7c4a5987c4f3`。
- Wall 167,469 ms / active 166,223 ms；输入 11,877 / 输出 2,216 / 合计 14,093 token，
  21 LLM / 6 logical retrieval / 27 Trace calls，failed / LLM retries / node retries 0。
  usage/cache 完整 21/21，hit 768 / miss 11,109（6.466%）；金额 unavailable。
  21/21 diagnostics/finish 已知、无截断，JSON strict 21/21、schema valid 18/18；
  repair_attempts 21 是兼容 parser 次数。Trace HTTP 0 不能当实际 fetch 总数。
- 六源 success 6/6、partial_failures 空；Tavily 7 / Chroma 5 / GitHub 7 / arxiv 7 /
  community 0 / official 2。社区空结果不能当有效证据；评分准入 10、strong 0、conflicts 0。
  系统 44 引用检查：verified 0 / unsupported 2 / unreachable 0 / unknown 42，
  不替代逐原子语义支持。来源漂移、非配对单例不能据成本或质量比例宣称改善。
- v4 完整分母 **53 原子**：supported 27 / partial 23 / unknown 3 / unsupported 0 / uncited 0，
  完整支持 27/53；来源 eligible 0 / ineligible 31 / unknown 22，确认合格覆盖 0/53。
  官方主页的一手片段不能补缺失细节，分类器标签不直接等于质量；缺证不判错误，
  不新增绝对引用/质量及格线。主审与独立复核非盲 assistant_review，人类校准 not_run。
  必答 6/6、冲突 2/2（实际三题/一冲突，各 0/1/2），不等于语义引用满分。
  初稿 3/6、1/2 的分歧保留；按冻结“正确且说明条件”仲裁，不引入额外量化/项目实测门槛。
  独立已复核完整分母、原引用、所有争议及声称闭环项，无未解决评审差异，
  未发现重大事实错误；独立网络事实认证 not_run，不强填经认证重大错误数 0。
  零维护、WAL 写入串行边界、备份一致性、可观察迁移、模板身份/异题争议、空 What 均闭环。
  场景适用性、多源互证及部分操作边界仍 partial/unknown；具体备份恢复及迁移阈值待验证。
- Cold first getter 103,094 ms，包含延迟依赖导入。真实 run 内 CONNECT/TLS 6/6 成功，
  certificate/check_hostname/原 hostname match 均 true；safe-fetch success 1，失败 5
  （response_rejected 4 / safety_rejected 1）保持 unknown，不判命题错误。
  68 样本 RSS 已知 68/68、authority_valid 全 true；RSS 最高 2,167,734,272 bytes，
  可用内存最低 753,782,784 bytes，高于 512 MiB 停止线。run heartbeat 15 success / 0 failure /
  0 loss；实例最大 gap 20,329 ms。采样不是连续峰值、硬件稳定或 12-case 并发容量证明。
- 控制器只准入一次，无 HITL 决策/取消/恢复，汇总正常；04:57:52 UTC 服务 exit 0，
  所属服务进程关闭。独立只读产品库 quick_check ok，task/run completed，immutable
  run_results 与采集 snapshot/report 相等；未读取 LangGraph 私有表或重放研究。

冻结范围是原知识种子不可变、每次**初始字节相同的新副本**：种子 hash
`e55ddcac30d0e498c6e5ae02cb40d1bae95eb2831fda71e924ed9211b76466e4`，BGE revision
`5617a9f61b028005a4858fdac845db406aefb181`。运行副本并非 Chroma 物理只读：终态树
`3f172a617d07e145292d585486ad76db2022ea941ec8b6725872900e5eed521c`，SQLite 仅 acquire_write
行数 170→171，其余表逐行相同、embeddings 50→50、learned_docs 逐字节相同；HNSW 两个
文件字节变化原因未认证。原种子未改、实验副本不能复用；独立复核判定不阻断初始同种子测量。

PR2 锁定条件：上述候选 Git，deepseek-v4-flash / thinking disabled，immutable manifest 的
输出上限与 standard-enforced-v1 / unpriced-v1，source-score-v3 / what-why-how-v3 / synthesis v3 /
scan/arbitration v2；线程上限 1、离线模型下载、LEARNED_DOCS_READONLY=1、检索缓存开启、
LLM_DS_CONCURRENCY=80、cold-in-research、每 profile/repetition 新空产品/检查点 DB 对。
配置 hash `4240dcd933e728eff05ea91d27cc5a57056c6c87404d20fa3b946cef50d9c474`，严格可信代理 hash
`813477bf51a0efb3b5926c3759f01d02cdf25cd70e6cfc7fa186d9d5e1e1d118`，模型 endpoint hash
`12b8deaccc34b32757dbb1497e029da0c2e7b26ffa86b9c926c08cb4692f4508`；不发布原地址或密钥。
单例 HITL 即停不冒充正式批次动作，PR2 仍沿用冻结协议并须另批额度/明确授权。
后续验收文档提交只记录事实，不能把本候选 Git 换成文档 HEAD；正式比较需使用该锁定提交。
原件仅本地 `outputs/o1-pr1-continuation-20260918/experiment-4/`，报告 hash
`eb2a647c5e1d239d2772939fe177354f97f7670efad1efdfa41298588c95012f`，snapshot hash
`f115d54922c7c528e9276d70b7a39a1da9f494491723b7791c7d6d33cee25fd5`。

完整台账 hash `8d8e5f25eebc76f5c0c6065cade7ab3662e10f1973066a95b63e2fd2641ac405`；
独立复核 hash `483633a24e6f2d2e44419bcb222d4cf1ea3788e8450771de601b723a1999cbe3`，
本地 candidate-freeze hash `5b0b6f01e07a5ac87a56eeb1e06e43cb5c69ee540d4b88140a58aa9bbeb4636a`。
复核时的主审 JSON 精确副本保留，最终主审仅更新资格状态，不改变评分/绑定。
候选提交前 228 聚焦 / 1478 全套、0 跳过（217.64 秒）、smoke 12/12、静态/依赖检查及
独立代码复审通过；后续仅本地评审和验收文档，不重跑未改变的生产验证。
硬件/WHEA、并发、人类校准、真实金额及正式串并发成对门禁仍未验收；O1 整体尚未完成。

## O1-PR1 继续实施：资源修正与新候选资格

此前尝试（2026-09-18，分母 P01 × 1）：候选 `35cbe48c13b74905ac2e63026ebc8b1cfb54e35f`
completed，但内容独立复核不通过，不能冻结为资格候选。累计 45/48，剩余 3，PR2 未启动。
模板 provenance、同题冲突、空 What 与运维条件的必要修正仍在 PR1，必须形成新提交并复验。
该失败报告的最终 v4 分母为 55：supported 15 / partial 26 / unknown 14，
来源 eligible 0 / ineligible 45 / unknown 10；原引用及完整分母已获独立复核，失败结论保留。
这些旧计数不能与新候选拼成一个分母或据比例宣称改善。

- 新候选前置 04:15:37–04:15:54 UTC 五源 5/5，HTTP 保守 8 / Tavily 付费 POST 1 / LLM 2，
  JSON/tool strict/schema valid/无截断；349 token（输入 313、输出 36、hit 128、miss 185），
  仅本轮准备成本，不并入研究，金额 unavailable。原前置限流失败不覆盖。
- P01 准入 04:22:43 UTC，task `5d71ae49-9ba9-449e-b2bb-c9e80fd69b71`，
  run `424204b4-328e-43b5-bb37-b6adcdc29969`；manifest
  `d447e8d42423af34d5e6c0e12cf90c737613fff4e893036a7a988d112d9dd50e`，registry
  `d6e8fda7f89d371914c6c7a8c27f239a9175eba6c2cf6acc0afdf86c77e29f36`。
  全新产品/检查点数据库对、同只读知识种子、离线下载/线程 1、标准硬预算与 HITL 即停不变。
- Wall 160,188 ms、active 157,981 ms；输入 23,579 / 输出 3,487 / 合计 27,066 token，
  36 LLM / 13 logical retrieval，Trace failed calls / LLM/node retries 0；36/36 usage/cache 完整，
  cache hit 5,120 / miss 18,459（21.714%）。金额 unavailable。Trace 中 HTTP 0 不等于未 fetch，
  不把 49 个逻辑 Trace 调用当实际 HTTP 总量。诊断 36/36 已知、无截断，JSON strict 34/34、
  schema valid 31/31；repair_attempts 34 是兼容 parser 调用次数，不是坏 JSON 次数。
- 六源 success 6/6、partial_failures 空；结果数 Tavily 6 / Chroma 5 / GitHub 7 / arxiv 7 /
  community 0 / official 2，社区空结果不能当有效证据。系统投影 verified 0 / unsupported 14 /
  unreachable 0 / unknown 25，和 v4 助手语义核对分开。
- 真实 run 内 cold first getter 83,078 ms（包含延迟库导入，不能与旧 4.906 秒直接比较）。
  同 run CONNECT/TLS 成功 7/7，证书必需/hostname check/原 hostname 匹配均 true，至少一次
  safe-fetch 返回成功；另 5 次失败（response_rejected 2、未细分 OtherError 3）保持不确定性。
  62 个健康/内存样本均 authority_valid，RSS 已知 62/62，最高 2,198,310,912 bytes，
  可用内存最低 1,141,559,296 bytes；运行 heartbeat successes 14、failure/loss 0，
  最大 gap 19,641 ms、schedule lag 2,188 ms。样本不是连续峰值/稳定性保证，WHEA 根因未解。
- 内容独立助手复核建议必答 3/6、冲突 1/2。零维护反复用于决策，WAL/备份/迁移条件不足，
  file 模板被误标官方/authority 10，异题比较产生裁决，What 因 strong=0 空白。
  没有缺失题名或虚构多源 supporting_sources。非盲 assistant_review、人类校准 not_run；
  unknown 不判错，无新绝对质量及格线。完整原子台账单列，不能拿 completed 代替内容资格。
- 内存两次在 Popen 前拒绝，用户释放后恢复。experiment-2 的 Windows venv launcher 端口归属
  检查导致启动后 0 准入，正常关闭，产品库 task/run/result 均 0；随后纠正真实子进程归属/RSS，
  用 experiment-3 空库一次提交。完成后控制器把 public snapshot 的业务 task 误认生命周期 task，
  汇总 KeyError；原 control-result 保留。只读 completion-audit 已验证 task/run completed、
  immutable run_results 的 snapshot/report 与采集原件相等，正常服务 exit 0，未重放研究。
  控制器修正只接受带 task_id/latest_run 的生命周期 DTO，离线归属检查及独立复审通过。

原件仅本地 `outputs/o1-pr1-continuation-20260918/experiment-3/`；不修改原数据库/报告。
新修正的 smoke-v1 对比确认 dataset、12 case output 和 metrics 完全未变，只更新
评估时间及 manifest/registry/fingerprint provenance，指纹改为
`8073732ca577499e358ee53a17678667579ef3ed8abb6ddb7d800193ee4a1f3d`，来源仍 not_run。
独立复审发现并要求关闭混合规则/LLM补证索引和缺题名本地比较范围两个缺口；
首次新全套在未通过时停止并保留日志，不能当通过结果。修正后需重新聚焦与完整验证。
上述缺口及 malformed 本地 URL 单项拒绝均已闭环，独立只读代码复审无阻断项。
最终冻结代码/测试后，本机 Python 3.12.4：228 聚焦 / 1478 全套通过、0 跳过
（217.64 秒全套），smoke 12/12、pyflakes/vulture/pip check/diff 检查通过。
HITL 超时回归仅替换采集器模块时钟，保证走到 decision GET 后超时，仍断言零决策/取消；
此前受真实短时钟与磁盘耗时影响的聚焦失败不算通过。日志仅本地
`outputs/o1-pr1-content-final-validation-20260918/full-suite.txt`。
该代码提交时旧报告台账仍待独立分母/引用复核；随后已完成55原子独立闭环，
这些离线验收不代替新提交的前置和 P01 资格。
下面保留资源修正与更早失败事实。

用户随后明确要求继续直到完成 PR1；必要最小修正和分轮前置/单例继续属于 PR1，
原研究总额度 48、每 run 硬预算、每轮前置上限及 HITL 即停保持不变，PR2/发布未授权。
此前各轮失败保留，不能循环复用身份或覆盖原件。

2026-09-18 03:53 UTC 同路由 arxiv 单探测 200（HTTP 1、付费/模型/研究 0）；
随后在审计代码身份 `294fe331f1f74453dbaa5e07741737de9878691e` 上执行独立完整前置，
03:54:47–03:55:40 UTC 五源 5/5、Tavily POST 200、原生 JSON/tool 两项严格/未截断。
本轮非 LLM HTTP 8、付费 Tavily POST 1、LLM 2，输入 313 / 输出 36 / 合计 349 token，
输入缓存 hit 128 / miss 185，usage 完整；金额 unavailable，准备成本独立于研究。
纯离线准备复制相同无 WAL 种子成功，随后控制器在启动前因可用内存不足 2 GiB 停止，
没有控制器准入日志、子服务或新 task/run，额度仍 44/48。
这不覆盖旧 4/5，也不能给下一生产候选沿用资格。

定位到契约导入链提前导入 sentence_transformers，采集器尚未研究就占用重型库内存。
最小修正延迟该依赖至首次模型调用，保留原生模型、参数透传、双检锁和失败可重试。
离线完整采集器新进程观测：sentence_transformers/torch 均未加载，RSS 94,642,176 bytes；
当时主机可用 2,435,137,536 bytes。该样本仅证明导入链，不能代替模型峰值或主机稳定。
新的候选必须在全套和独立复审后提交，再获得新前置、全新数据库对和单例资格。
该最小修正项目 Python 3.12.4 验收：103 聚焦 / 1441 全套、0 跳过（211.19 秒全套），
smoke 12/12 原指纹未变、静态/依赖/diff 检查及独立只读复审通过；完整测试日志留本地。
上述原件留在 `outputs/o1-pr1-continuation-20260918/`，原报告/旧数据库未改。

以下保留早前停止记录。

## O1-PR1：入口验收通过，真实资格被路由降级阻断

2026-09-18 用户授权实施单例资格与候选冻结。工具新增单轮 prerequisite dispatch 上限、
SDK 无重试 JSON/工具检查、相同 Git/依赖/模型端点/路由配置核对，以及冻结无 WAL 种子的
字节复制。资格 serve 跳过预热，启动与采集都消费完整冻结身份和固定资源/离线设置；
采集只允许 P01 一次、等待 HITL 或资格超时停止，不调用决策、取消或恢复。
正式采集默认 HITL 策略与预热入口保持兼容。一次前置准备成本与研究分账，原件留本地。
本轮最终本机离线验收（项目 .venv Python 3.12.4）：59 聚焦 / 1439 全套通过、0 跳过，
全套 328.91 秒。smoke-v1 固定 12 例 12/12，原 fingerprint 未变、来源健康 not_run；
pyflakes src/tests/benchmarks/本地控制器、vulture src 100%、pip check、diff 及独立只读复审通过。
复审发现的超时取消和案例/资源/manifest 冻结缺口已在付费调用前关闭。
入口实施本身不证明动态 TLS、报告质量或并发资格；真实尝试按一次边界另记。
本地完整验证日志为 `outputs/o1-pr1-validation-20260918/full-suite.txt`，不发布原始日志。

离线实施提交后，唯一前置于 **2026-09-18 03:45:15.431～03:45:23.828 UTC** 执行。
候选审计身份 `ce4addfcf017018cd2abd570fc05623749896d90`，真实前置开始前与结束后工作树干净。
五项健康 **4/5**：tavily/github/official 为 local-proxy、community 为 self-forward，均 ok；
arxiv 选 local-proxy，但投影为 `rate_limited`，完整路由汇总降级后停止。
具体 HTTP 状态、Retry-After 或冷却期限未采集，不能确定限流细因；不与此前单源 200 拼全绿。

本轮准入 journal 为 **6 个非 LLM HTTP 条目**，其中 community 的逻辑 GET 和 forward
carrier POST 保守分别计入；carrier POST 未计为 Tavily 付费调用。
Tavily 付费 POST **0**、LLM 实际请求 **0**、新研究 **0**；累计 **44/48** 不变。
未 prepare 新实验、启动服务、冷加载或提交 P01，没有重查、补跑或恢复。
金额 unavailable，付费探测 usage not_run；无报告声明分母，v4 内容评审及报告独立复核 not_run。

已留住该尝试的 Git/依赖/模型端点/路由和严格代理 hash。代理身份与前次已批准端点一致，
配置 hash `4240dcd933e728eff05ea91d27cc5a57056c6c87404d20fa3b946cef50d9c474`，
依赖文件 hash `c07764a225a2eef37b2ee47dacdd1dec0efac5cd263c4522b5c121c50a40493b`。
这只是失败尝试的输入身份，**单例资格 unavailable，尚未形成 PR2 锁定候选，PR1 未完成**。
LLM JSON/工具、真实 pinned CONNECT/TLS、冷启/资源/租约、P01 报告质量仍未实测；
后续新真实尝试需单独授权，本轮不自动重做或进入 PR2。

安全原件仅留本地 `outputs/o1-pr1-20260918/prerequisites/`：

| 原件 | SHA-256 |
|---|---|
| preflight-summary.json | `615b5df23f6d45926d015a960c5892e7fbc906554055b2118e1206866802bb51` |
| retrieval-routes.json | `ec7f3500213a128569c64f7970ebb6e157c2aabb2cd9e62d06c8712a01bed742` |
| request-admissions.jsonl | `4ad5d51c5a391d9decc9e1e9d30f05566cdd647fe89ba74f200d46fbabfa729a` |

三份前置原件已由独立只读评审核对一致：6 条准入均属 routing，POST 为 forward carrier，
停止/零付费与零研究结论一致，原件无秘密或原始响应正文。计数不是完整 wire 总数；
该日志复核不替代尚未执行的 P01 内容评审、冷启或代理实测。

## 前次单源诊断：arxiv HTTP 200，完整前置/P01 未执行

2026-09-18 随后获批的 arxiv 同路由单探测仅发出一次 provider GET，02:15:38～02:15:40 UTC
返回 HTTP 200，未提供 Retry-After，当前 gate 无限流/冷却。单源健康 1/1，旧限流细因
没有复现或确定；不倒填旧前置、不拼另四源全绿。LLM/Tavily 付费/研究均 0，额度 44/48
不变；后续完整前置及 P01 一次仍需重新确认边界。源码解释、验证与原件 hash 见
[阻断诊断](../../o1c-blocker-diagnosis.md)。

## 前次进展：C3 已授权，前置降级停止，P01 未提交

2026-09-18 用户批准当前候选 P01 冷启一次及一轮必要前置：路由/健康 HTTP 上限 20，
Tavily 付费 POST 上限 1，JSON/工具 LLM 实际请求上限 4；前置失败或等待 HITL 即停，
不补跑、不恢复、不开批次。研究硬预算仍为 60,000 token / 96 LLM / 72 retrieval /
900,000 active ms。仅实验进程信任经严格校验的当前固定本地代理，不修改 `.env`。

执行代码审计身份 `d567b2632bd5548479ab8baefa8a5b07fa7cf206`，项目 .venv Python 3.12.4。
前置启动于 02:05:14 UTC（北京时间 10:05:14），最后请求准入 02:05:23 UTC；
网络健康 **4/5**：tavily/github/official 为 local-proxy、community 为 self-forward，均 ok；
arxiv 选 local-proxy，但公开健康投影为 `rate_limited`，因此停止。
具体 HTTP 状态、Retry-After 和冷却期限未记录，不能据此断言代理断线或确定恢复时刻。
Tavily 付费探测、LLM 探测、隔离服务、冷模型加载、研究与报告均未执行；新 run 0，
累计 **44/48** 不变。真实 pinned CONNECT/TLS 互通、模型逐子句遵从、报告质量、
并发资格及主机稳定性仍未验收。本轮不自动重查或提交 P01，后续真实调用需另确认。

计数审计：6 条 httpx 准入记录包含社区外层逻辑 GET 和转发 carrier POST，
底层目标/carrier 准入为 5；不把它当包含隐式 CONNECT/转发远端请求的完整 wire 计数。
原件 `tavily_post_attempts=1` 误将任意 POST 计入该字段；所有准入均在 routing 阶段，
该 POST 是社区转发，实际 Tavily 付费 POST **0**。原件不改，另加审计投影。
前置控制器应用层/SDK LLM 重试均关闭，计数先持久化再 dispatch；纯合成计数检查确认
第 21 条 httpx 准入在发送前拒绝，临时目录已清理；独立只读核对确认停止事实。
本轮控制器原件已冻结；随后仅离线修正 POST 分类，使转发 carrier 不占 Tavily 探测额度。
纯合成验证 1 carrier POST + 1 Tavily POST + 2 mock LLM 请求通过，真实请求 0，
pyflakes 通过，临时目录已清理；没有重查真实来源。本轮因 arxiv 提前停止，不影响原结论。
仓库跟踪修改仅为维护文档，没有修改生产代码、测试或持久化配置；C2 离线验收仍是该代码候选的
工程证据，不是本次真实前置全绿。金额 unavailable；不能把未执行付费探测推为完整零费用。

本地原件在 `outputs/o1c-control-20260918-c3/`，不提交：
preflight-summary.json SHA256 `0416d320eeedd5cf0fefc94a1da936554015db55581d75e7ae6df70abc1ba8bb`；
request-admissions.jsonl `e6b5163ecbe3a94c51f1978aaac18bfc089d3bb1188978a37108fc15cd41518e`；
audited-observation.json `1c441d051563b9b9123bdba70fd8f6f67f31f66c50a2fcc18b3bd46f75060bcc`。

## 上一轮：C2 最小可信代理离线验收完成

2026-09-18 用户确认 C2 具体边界后批准离线实现与验收：默认关闭的
`SAFE_FETCH_TRUSTED_LOCAL_PROXY` 仅信任固定 loopback HTTP CONNECT 端点，与选中通道
精确匹配，无认证；动态目标仅 HTTPS:443。CONNECT 使用已验证公网 IP，内层原域名
Host/SNI/证书校验保持开启，握手累计有界、每跳重验、异常/取消清理，不切 direct。
新 manifest 冻结 outbound-url-v2/可信端点哈希，旧 v1 仍可读但不能跨策略同 run 恢复，
运行 resolver 配置须与冻结信任配置一致。完整接口与信任限制见 [运行契约](../../phase1-runtime-contract.md)。
本轮不启用配置、不做真实来源健康/LLM/API/研究，额度 44/48 不变，C3 一例另批准。
最终离线验收（2026-09-18，Windows/项目 .venv Python 3.12.4）：11 个受影响文件
270 passed（120.24 秒）；完整套件 1399 passed、0 skipped（210.02 秒），无警告。
smoke-v1 固定 12-case fixture replay 12/12、原基线匹配，指纹仍为
`ef4b170d8e14af07cd3de2ef6e4ed7e37dd1b6bd563f5903f71c4270b7d2c4f0`，来源健康 not_run；
没有更改 fixtures、门槛或已记录 baseline。pyflakes src/tests/benchmarks、vulture src 100%、
pip check 与 diff 检查通过，独立只读复审未发现阻断。
本轮精确创建的测试临时目录已清理，原实测数据及本地交接文件保留。
测试代理曾误用全局 Python 3.13，其输出不采纳；上述验收全部由根代理在受支持 .venv 重跑取得。
合成协议验证 IP CONNECT/内层 Host/TLS 身份、握手累计限制、异常数据/响应脱敏、取消关闭；
集成回归验证逐跳 DNS/repin、HEAD Range fallback、429 冷却、响应/总时限和配置漂移早拒绝。
既有引用/预算、公开投影和恢复契约在同轮聚焦与全套中验证，不增加预算或重试。
残余边界：真实代理互通及 TLS 证书交换未测，可信依赖代理遵守 CONNECT 目标；
真实模型逐子句遵从、报告质量、并发资格及主机稳定性仍未验收。C3 配置启用和一例新 run
需另授权调用/费用范围；不以该实现倒推旧 P01 的 30 个 unknown 均由代理导致。

## 上一轮：既定地址拒绝契约补修（不含代理适配）

2026-09-18 安全适配前的离线核对发现既定地址拒绝缺口：Python 将部分组播地址的
is_global 标为 True，旧 guard 会接受；现补显式组播/保留等类别拒绝，覆盖字面地址、
混合 DNS 与正常公网单播回归。这不是 proxy 适配；proxy/forward 仍拒绝。
该缺口不证明旧 P01 的 unknown 由此引起，不修改或补写实测原件。
该轮结束时代理最小范围仍待具体批准：用户明确可信的固定 loopback HTTP CONNECT 端点，
仅 HTTPS、目标端口 443，CONNECT 目标/Host 使用已验证 IP:443，内层 Host/TLS 校验仍为原域名。
须显式 opt-in 且默认关闭；当前只是待批准范围，没有启用配置或实现该能力。
loopback 本身不是可信证明；不能保证恶意代理遵守目标。握手须累计有界、异常数据拒绝、
逐跳重新验证、取消清理且不 fallback；未经离线协议验证不冻结底层实现。
本轮仅纯内存协议模拟及合成/字面地址回归，未调用系统 DNS 或真实网络/API/模型/case，
额度保持 44/48；安全适配与复测不自动启动。
本次 Windows/Python 3.12.4 离线验收：84 聚焦通过（152.03 秒），1306 全套通过、
0 skipped（212.40 秒）；smoke 12/12 原基线匹配，pyflakes src/tests/benchmarks、
vulture 100%、pip check 与 diff 检查通过。代码和维护文档独立只读复审无阻断，
复审不重复全套、不证明代理能力或真实质量。测试临时目录清理，实测原件保留。

## 前一轮：缺引用与网络 unknown 分类收口

用户进一步授权将缺引用与网络 unknown 纳入 O1-C 并离线处理，不调用真实服务。
缺引用四处均在 P01 最终文本中真实不存在 marker：推荐末句与三个 finding 分号前子句；
没有已存在引用被代码丢弃的证据，也不是 verifier 误判。合成提示 synthesis v2 明确
每个独立分号子句、推荐首尾各自引用；无支撑断言应删去并记录证据缺口，不借附近引用。
离线 mock 验证消息规则送达和绑定行为，仍保留真实缺引；不证明模型实际会遵守。

安全获取补充固定内部失败分类：route_unavailable、route_unsupported、dns_uncertain、
safety_rejected、response_rejected、timeout；验证器另区分限流、准入、传输及其他异常。
只在日志中输出经集中脱敏的固定分类，不包含 URL、异常正文、页面、DNS/IP 或堆栈；
每个逻辑 URL 一次异常分类，不把多个 claim 重复算多次 fetch。分类日志不是公共结果字段，
也不是新增 Trace/lifecycle 事件或历史失败回填。所有 BudgetError 继续 fail closed，
取消仍传播；HTTP 非成功响应保留原 http_uncertain/not_publicly_accessible 投影规则。
公开四状态、reason/schema、词法支持策略不变；分类诊断不是网络修复。

proxy/forward 被选中仍不能固定已验证 IP，继续拒绝，不自动切 direct。
该轮结束时下一步是单独确认 C2 安全传输适配范围/契约；当时未获授权，不能声称复测准备就绪。
再经离线验收，才另确认 C3 一例新 run。旧 synthesis v1 identity 可读，跨版本同 run 恢复拒绝；
当前 manifest 与 registry 冻结 synthesis v2/hash。smoke fixture、指标、门槛、12 个输出不变，
仅更新时间/manifest/registry/指纹 provenance，来源健康仍 not_run。
2026-09-17 候选 Windows/Python 3.12.4 离线验收：175 聚焦通过（51.25 秒），1296 全套通过、
0 skipped（196.59 秒）；smoke 12/12 基线匹配，pyflakes src/tests/benchmarks、vulture 100%、
pip check 和 diff 检查通过。新 smoke 指纹
`ef4b170d8e14af07cd3de2ef6e4ed7e37dd1b6bd563f5903f71c4270b7d2c4f0`。
独立只读复审覆盖代码、兼容、测试与维护文档，构造兼容边界补回后无阻断；
复审未重跑完整测试，不证明真实质量。P01 报告/快照 hash 与下方原观察一致。
测试临时目录清理，原始实测输出保留；额度保持 44/48，D/E/O2 与批次仍暂停。

### 前一轮确定性证据修复验收（历史候选）

2026-09-17 用户授权离线定位及有回归测试的最小修复，不自动补跑。明确区分：

- **产品缺陷**：旧来源评估没有显式候选准入；把所有其他高分 URL 当互证，抬高 strong；
  Tavily 的 `\N` 原样进入证据；What/Why/How 用任意标题词片段给声明补 Sources，
  例如 `On` 可把无关论文附到 PostgreSQL 文案。合成 sanitizer 另会截断含标点/括号的真实标题。
- **不是已确认的词法误判**：P01 的 53 处检查实际为 30 network_uncertain、19 url_invalid
  （本地 file://）、4 citation_missing；没有 lexical_mismatch。其中三个分号前子句未带引用，
  另一处为推荐末句未引；不把尾部引用自动移给前句。
- **安全获取边界**：本轮 official 选 local-proxy；按候选代码，动态 safe-fetch 不接受不能固定
  已验证 IP 的 proxy/forward，因而可产生 network_uncertain。原件未保存异常细分类，不能
  将每个 unknown 的个别原因都倒推确定；不绕过安全策略、不以搜索片段冒充实时验证。

修复契约：有 `task.candidate_techs` 时，标题/摘要须词法提及至少一个显式候选才进入评分；
保留原始检索结果和失败状态，无候选/类别任务不猜词。共享候选名不构成主张互证，
`supporting_sources` 不再凭分数/数量填充。缺失标题使用 `Untitled source (<URL hash>)`，
只标元数据缺失、不编造题名。来源链接只按显式且唯一的标题引用展示，无引用/歧义不补链。
平衡括号的语法解析在合成、验证与渲染间复用，多引用只在最外层拆分；合成清洗和
链接展示保留 C++ / C# / node.js 等标点。引用验证的支持判断和四状态规则不变，
其 v1 注册表仍有简化标题/子串匹配盲区，本轮不声称全面精确绑定或语义证明。

新运行冻结 `source-score-v2` / `what-why-how-v2`；旧 v1 manifest 身份仍可读，
same-run resume 拒绝跨版本。schema、Prompt、冻结案例、路由、预算和重试策略不改。
回归覆盖见 `tests/test_o1c_evidence_cleanup.py`。P01 原件离线复算分母为 27 个来源，
准入 13、排除 14、strong 0；旧报告/快照未改，也未运行合成模型，不是新的质量/成本对照。
仍会保留提及 PostgreSQL 的 Redis/Neo4j 等相邻比较，词法门不是语义相关性证明。

smoke-v1 fixture/指标/门槛不变且 12/12：模板不再猜测补链，只有 RP-001 报告 hash 变化，
连同 registry/manifest/时间及指纹更新确定性基线；来源健康仍 not_run。
新指纹 `6d57e84daa93ed8473116dfca2fb171da367883e62e4fc1a76d40c87753210f2`。
最终 Windows/Python 3.12.4 离线验收：167 聚焦通过（20.20 秒）、1271 全套通过、
0 skipped（212.38 秒）；smoke-v1 12/12 且新基线匹配，pyflakes src/tests/benchmarks、
vulture 100%、pip check、diff 检查通过。独立只读复审的两项标点/嵌套解析发现已修正，
复审者离线断言确认闭环，无剩余阻断；未重跑全套或验证真实质量。原报告/快照 hash 未变。
本轮测试临时目录清理，全部实测原件保留。没有新增真实调用，额度保持 44/48；
下一步只可另行确认一次新 run 单例复测，不恢复 D/E/O2 或批次。以下保留原运行事实。

## 实测结论：P01 冷启完成，质量与批次资格未通过

2026-09-17 用户重新授权前置并确认执行 P01 一次。仅创建 1 个 run，无重新提交、恢复、
批次或保留集访问；累计 **44/48**，剩余 4。研究状态 completed、报告可取、无需 HITL，
但报告仍有明显缺陷；本次不是 O1 闭环、稳定性保证或串并发门禁通过。

### 冻结身份与执行条件

- 代码审计身份 `d451b49138558f2c5ebd86f50772c1c70709c4a5`；最近生产改动
  `dddc036781a3630b5b73971a08199e5e47284be2`。数据集 product-baseline-v1 / 1.0.0，
  冻结日期 2026-09-16，hash 同下方历史记录；分母为 P01 × 单例 × 1 次。
- manifest `ed3821f00026bb881df626e2e97c5c2706d0074ce9f0c50c22d41bf567da4b01`；
  core registry `8918c0fd30e14ab9888b6e6472486d1da0c8a8601337c12e803e704b14d65d7c`；
  environment `d6d843ec0145fe1aab3af9f49c5b571ce2aa6a9dbd3c7a004fae661539889fc5`。
- Python 3.12.4、请求模型 deepseek-v4-flash、thinking disabled、线程上限 1、离线模型下载，
  新空产品/检查点数据库对、只读知识副本、缓存开启；没有预热。冻结知识 hash
  `e55ddcac30d0e498c6e5ae02cb40d1bae95eb2831fda71e924ed9211b76466e4`。
- 准备时 SQLite backup 改变了知识库头部偏移 27/43/95，物理 hash 校验停止，尚未提交研究。
  两份 DB 完整性通过；失败副本保留，将未使用的实验副本恢复为原冻结文件逐字节拷贝，
  重新验证全部知识 hash 和空运行目录后冻结环境。原知识库与生产复制逻辑未修改。
- 研究准入 12:52:11 UTC，采集结束 12:53:44 UTC；默认硬预算 60,000 token / 96 LLM /
  72 retrieval / 900,000 active ms 不变，auto-recovery 仅在隔离服务关闭。

### 已知结果与成本（2026-09-17，分母 1 run）

- Wall 93,140 ms，预算 active 90,900 ms；27 LLM、13 retrieval，共 40 个逻辑外部调用，
  failed calls / LLM retries / node retries 均 0。逻辑调用数不是实际 HTTP 尝试总量。
- 六源状态 success 6/6，结果数 tavily 7 / chroma 4 / github 7 / arxiv 7 / community 0 /
  official 2；partial_failures 空。community 零结果不等于提供了有效证据，也不证明并发限流已解决。
- 输入 21,039、输出 3,159、合计 **24,198 token**；27/27 usage 和缓存拆账完整。
  输入 cache hit 5,760 / miss 15,279，命中率 27.38%，未命中占输入 72.62%。
  冲突检测 miss 7,399、结论合成 miss 5,812，合计占 miss 86.46%。价格 unavailable，
  金额 unknown；这些数不含前置探测/健康检查，不是完整账单或节省证明。
- 输出诊断覆盖 27/27、finish_reason 已知 27/27，无截断；JSON strict 25/25，浅层 schema
  valid 22/22。repair_attempts 25 是兼容 parser 调用次数，不是 25 次坏 JSON；另 3 次 JSON
  没有 schema 检查，采集器整体 qualification 仍 not_evaluated，不把这些分母合并。
- Embedding 12:52:19 UTC 开始，冷加载 **4,906 ms**。78 个约 2 秒间隔的健康/内存样本均
  HTTP 200、authority_valid；实例最大心跳间隔 19,766 ms，实例/运行最大续期
  9,375 / 9,469 ms，运行最大 schedule lag 312 ms，运行 heartbeat failure / lease loss 均 0。
  采样不是连续无故障证明。服务峰值 working set 1,801,977,856 bytes（约 1.68 GiB），
  主机最低可用内存 497,569,792 bytes（约 475 MiB）；仍有内存余量风险，既往蓝屏/WHEA
  根因未解决。本轮未观测到重启，不能宣称硬件稳定。

### 报告核对与停止线

报告读取核对发现：无关仓库/论文混入证据与引用列表、来源标题出现 `\N`、结论 high confidence。
确定性引用检查共 53 处：verified 0 / unsupported 23 / unreachable 0 / unknown 30；
这是系统词法/可达性投影，不是助手逐原子声明的语义评分，unknown 不等于错误。
报告内容质量尚未正式按 v4 台账复核，本次不填最终 rubric 分数、不与旧候选六份报告拼表。

隔离服务 12:54:18 UTC 正常退出，观测器退出，所属进程和端口均已关闭；全部本地原件保留。
下一步仍在 O1：优先离线追踪本报告的无关来源、异常标题与声明/引用绑定，再决定最小修复；
不自动改 Prompt、冻结案例或预算，不补跑 P01，不启动 D/E/O2 或整组串行/12-case 并发。

原件位于 `outputs/o1c-single-20260917/` 与 `outputs/o1c-control-20260917/`，不提交 Git。
SHA256：experiment.json `24b624ac0650e28c4c294379ff04217aa07a68e1f5147dc84fbda3345c2a05dd`；
runs.jsonl `d1865efa93bc67a607ccd8661dfdad24b8cd4e9bf714b754bdd25f9fb064850f`；
P01.md `2013306bb116a8349e17bd09096e7cb8fd508dd5c7472a5e128254fb9c112c3e`；
P01.json `fea087e895e6b6a6cf76946487f110c8bc389608c7ed31e47b1cd50f43d824f0`；
health-memory.jsonl `90e79dd2d09bc368e85dc5cc675783ca2c147e2778057f56a5e0078acdf98d09`；
cold-start.jsonl `1cebe02d9c1441a097ab3433cbcb38a46347fd4e2aa589c6cca4236bfa1da174`。
本轮未改生产代码或测试；既往同生产候选 1244 全套 / smoke 12/12 与静态验收仍有效，
仅新增真实单例观察与文档核对，不重复未变更全套。以下保留先前失败，不倒填原件。

## 历史：首次前置停止

日期：2026-09-17。状态：**preflight_stopped，单例未执行，O1 仍 incomplete**。
随后用户授权定位两项阻断，见 [诊断记录](../../o1c-blocker-diagnosis.md)：新社区单源反馈确认
throttle_violation，并发现 probe 未带已配置的可选 key；离线时间断言存在时钟/打点契约错位。
后续诊断不倒填本次原件，也未修复或继续研究。
用户授权先验真一例；按任务卡选开发例 P01，最多一次提交，不重复、不自动恢复、不跑批次。
本轮未修改产品、测试、冻结案例、Prompt、路由或预算。

## 实际观察

- 执行候选：`51c7c21083da75e8411c1cb062df15a85c3f6322`（O1-B 已验收版本）。
- 数据集：product-baseline-v1 / 1.0.0 / 2026-09-16，SHA256
  `e0317ddeaa2b37526f5a7261d8df26217b75619d6c46bcd1bc8705895f16981f`。
- 一次真实检索前置检查，完成时间 2026-09-17 11:50:35.350290 UTC（北京时间 19:50:35）。
  五个网络来源健康项 **4/5 通过**：tavily/github/arxiv/official 为 local-proxy；
  community 选中 self-forward，但 `ok=false`。另行 routed Tavily 搜索 POST 通过。
  这不是研究六源的成功率：本地 ChromaKB 未测，研究内六源状态均 not_run。
- LLM/Tavily/GitHub 凭据存在检查通过，但不等于 LLM 连通或输出资格通过。
  LLM 探测、冷模型初始化、隔离服务、研究提交、报告、缓存 token 拆账均 **not_run**。
- 新建研究 run **0**，累计仍 **43/48**、剩余 5。健康检查已发生真实网络请求及 Tavily 搜索，
  其费用/重试总量未完整采集，金额 unknown；不能写成“本轮零费用”。无研究 token 观察。
- 主机前置可用内存约 2.9 GiB；读取到两条既往 WHEA-Logger 18（09-16 15:30、15:48）。
  没有真实研究峰值、心跳或冷启耗时样本；这些前置事实不证明硬件稳定或已修复。

## 阻断解释与证据边界

`outbound/resolver.py:health_check()` 仅在探测接受某通道后返回该 channel；当 provider gate
`unavailable()` 时仍保留 channel、把 `ok` 置 false 并标为 rate_limited。
`throttle.py:unavailable()` 表示已记录限流或冷却未结束；社区的反馈可来自 HTTP 429、
throttle_violation 或成功响应中的 backoff（见 `probe.py:ok_for()`、`throttle.py:observe()`）。

因此，**按冻结候选代码推断，此次 community 属 provider gate 不可用，不是转发断线的证据**。
安全检查产物只保留 ok/channel，未保留原 status、HTTP 状态、backoff/Retry-After；
具体触发原因与冷却期限 unavailable，不能断言实际收到 429，也不能判定限流补修无效。
下一次授权检查应保留 allowlisted status/安全限流分类，不保留响应正文、私有 URL 或凭据。

原件（本地保留、不提交 Git）：`outputs/o1c-control-20260917/retrieval-preflight.json`，SHA256
`6c88ef73320f591be26f438a0b77e3f97ecc691d0cc42e33dae3ae5b6b3e5e31`；
执行 helper `check-health.py` SHA256
`6f7795e9013e16d66823e3935da75788bc3d5e9aaa03ec42f4ea248ec9f7cc0f`。
脱敏事实投影见 [JSON 记录](../../o1c-preflight-observation.json)。未创建 `outputs/o1c-live-20260917`。

## 后续动作 / 停止线

1. 保留这次失败，不自动重跑健康、切路由、绕过冷却或提交 P01；没有进入 O1-D/O2。
2. 下一步先确认 community 可用性与安全限流反馈；若需改代码，另做有测试的最小修复。
3. 前置恢复后，重新明确授权 P01 一次提交，使用新空数据库对、同一知识快照与冻结预算；
   继续检查六源失败、缓存拆账、JSON/结构、冷启/心跳。再次失败或降级仍停止。
4. 单例成功只支持该例执行观察；不代表语义质量、硬件稳定、12-case 并发或 O1 闭环通过。

验证：O1-B 的 1238 全套通过（0 skipped）及 smoke 12/12 是该未变更候选的既往验收，
不是本轮全绿声明。本轮 outbound/限流离线回归 **53 passed / 1 failed**（22.25 秒）；
失败项 `test_mocked_twelve_cases_retain_six_source_results` 的缩放毫秒级请求间隔断言失败，
此前六源结果一致性断言通过。仅该项独立复查 **1 passed**（19.06 秒），不覆盖首次失败，
不据此确认根因或宣称 flaky 已修复。该测试完全使用合成 HTTP/本地 fixture，未调用真实服务。
JSON 原件哈希、脱敏投影、4/5 分母、无新研究目录及 git diff 检查通过；未产生测试临时目录。
本轮只补文档/事实投影，未改代码/测试；不重复未变更全套。后续应先定位这一时序不稳定，
修复后按契约跑聚焦和全套，再考虑真实单例准入。O1-C 不能呈现为完成或当前验证全绿。
