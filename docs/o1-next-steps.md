# O1 剩余交付与 PR 划分

更新：2026-09-21。2026-09-18 原始重组将剩余 C/D/E 工作组织为 **3 个 PR**，A/B 保留已完成状态；
该次规划不改变 [评估协议 v4](product-effectiveness-optimization.md)的冻结案例、rubric、质量/并发阈值、
HITL 策略或预算，且当时不构成新的实施、付费调用或发布授权。

随后用户依次授权并完成 O1-PR1 与 O1-PR2A，并四次明确批准 O1-PR2B 第一轮付费执行
及所需外部数据传输。前三次分别因公共引用 GET 403、HITL partial marker 和已知
`SafeFetchFailure` 的控制器误判停止。第四次使用 `30c63f9`：serial-r1 完成 12/12，
concurrent-r1 一次准入并观测到 12 路 running，随后在多源检索阶段发生实例与 11 个 run
heartbeat 失权，0 并发报告。该 fresh 根不得补跑或重启；第二轮未启动。

| 已完成部分 | 已有交付 | 尚不能据此宣称 |
|---|---|---|
| O1-A 评估口径 | 冻结 12-case/参考、v4 逐处声明口径、旧六份开发报告台账、独立复核及离线复算 | 当前候选的真实质量、人类校准或 O1 结项 |
| O1-B 观测与运行补修 | JSON/结构/截断/parser 次数、token/cache 拆账、失败分类、冷加载与租约/health 离线补修 | 当前候选的真实冷启、整 case 并发或硬件稳定 |
| O1-C 的 C1/C2 离线部分 | 候选准入/题名/互证/明确引用展示，逐子句引用提示，unknown 分类与地址拒绝，可信本地 CONNECT 适配及冻结身份 | 模型实际遵从、语义支持或真实 pinned CONNECT/TLS 互通 |

当前状态：**source-aware 控制提交 `91d56cd` 的 fresh 第一轮再次按冻结停止线退出，
O1-PR2B 仍未完成。** serial-r1 完成 12/12，形成 12 份报告（P07 limited），合计
146,801 tokens、179 LLM / 72 retrieval、0 failed；stop-final、清理与服务退出完整。
concurrent-r1 一次准入并观测 12 路 running，但 12 个 durable API 轮询在约 105～107 秒全部
`ReadTimeout`；控制器自动取消，11 个 run cancelled、P04 interrupted，0 并发报告。
停线前 97 个 health 样本均 200、authority/heartbeat/lease 正常，最低可用内存 1.292 GiB，
且没有先发 provider 异常；当前只确认服务响应中断，内部原因仍 unknown。

该 fresh 根必须保持不变，不重启、不补跑、不与后续根拼接。累计已使用
**35 个研究 run**（资格 1 + 前一停止轮 10 + 本轮 24）。用户已批准生产修复后的新资格及
完整 fresh 48-run 配对；按 35 + 1 + 48，当前总上限为 **84**。文件型运行时的公开 task 与
observability 读取已迁到独立 WAL 连接，主连接 asyncio lock 积压故障回归和 1559 项全套测试通过。下一步
先提交生产候选并用第 36 个 run 重新资格；通过后冻结该提交，再从新根使用第 37～84 个 run。
供应商、数据外传、案例、rubric、预算、HITL、质量阈值和异常停止线保持不变。

以下为 2026-09-18 的 PR1 历史断点，只用于解释资格形成过程，不代表当前状态：
PR1 入口通过 59 聚焦 / 1439 全套及独立复审，候选实施提交为 `ce4addf`。
2026-09-18 03:45 UTC 本轮唯一前置仍为 4/5，arxiv local-proxy 投影 rate_limited 后停止；
HTTP 保守计数 6、付费 Tavily/LLM/新研究均 0。继续实施后完整新前置 5/5、JSON/tool 通过，
但在提交 P01 前内存启动线拒绝；正在形成延迟导入修正的新候选，原额度 **44/48** 不变。
P01 未提交、单例资格 unavailable、PR1 未完成且未形成 PR2 锁定候选；不自动使用剩余额度。
不与此前 arxiv 单探测 200 拼全绿，限流细因未确定；证据见
[单例验真](o1c-single-case-verification.md)与 [阻断诊断](o1c-blocker-diagnosis.md)。

| 剩余 PR | 对应旧任务 | 交付目标 | 完成证据与依赖 |
|---|---|---|---|
| O1-PR1 当前候选单例资格与冻结 | C3，含必要的 C 问题收口 | 先用一次当前候选 P01 冷启核对执行、引用/报告与成本；处理实际阻断后形成可测量的锁定候选 | 候选 `15ca251` 已完成前置、P01、68 原子台账、独立复核与冻结；助手暂定资格通过 |
| O1-PR2A 控制面离线修复 | D 的执行前置 | 修复静态探测误报、停止态预算证据和冷初始化关闭阻断；不执行真实研究 | exact operation 单元测试、公开 API stop-final 证据测试、冷初始化收束/正常退出测试及全套验证；已完成 |
| O1-PR2B 正式串并发基线与逐轮评审 | D，含 E 的逐报告评审 | 用新的 fresh 根、同一冻结产品候选完成 12-case × serial/concurrent × 2 重复，共 48 个新 run；采集和质量核验一起交付 | `91d56cd` fresh serial 12/12 产出；concurrent 12/12 running 后因全体 API ReadTimeout 停线，0 并发报告。累计 35/84，根不可拼接，第一轮门禁 unavailable；生产查询隔离已离线验收，新资格和完整 48-run 已批准但尚未执行 |
| O1-PR3 O1 结项与优化假设 | E 的总体结论 | 汇总质量、运行/成本和残余风险，冻结一个最优先的 O2 假设 | 本地收口依赖完整 PR2 测量；第一轮门禁 unavailable，未启动。O2 实施及发布另授权 |

## O1-PR1：当前候选单例资格与冻结

- 收口执行入口：新输出目录、空产品/检查点数据库对、同一只读知识副本，资源线程上限和
  离线模型下载约束；明确冷启，避免现有 serve 的预热被误标为冷启。
  每次真实尝试在提交前冻结本次代码/环境身份及对应 manifest，不能事后给结果换身份。
- 单例资格模式在等待 HITL 时停止，不自动提交冻结 case 的决策动作；正式 PR2 的动作策略
  保持协议不变。冻结一次任务准入、关闭自动恢复的控制入口；不能用自动 limited_report
  把暂停转成资格通过。若需维护采集工具，相关变更及回归归入本 PR，先离线验收再真实调用。
- 持续授权覆盖当前候选一轮前置及 P01 一次：前置路由/健康 HTTP 上限 20，Tavily 付费 POST
  上限 1，LLM JSON/工具探测实际请求上限 4；准备成本单列。失败停止，不循环探测或自动补跑。
- 观察六源实际结果/降级、C2 在该 run 内的实际 safe-fetch 路径、unknown 固定分类、
  HTTP 引用与本地 file 引用边界；未覆盖的代理互通保持 not_run，不伪造 RunContext 补测。
  动态 pinned CONNECT/TLS 未覆盖时，该能力的实测资格仍 unavailable，静态 provider
  proxy 200 不能代替；若需额外验证，先明确批准固定目标/调用边界。
- 核对新报告的候选相关性、缺失题名、虚构互证、独立子句缺引、关键结论与证据适用性；
  按 v4 完整声明分母留住 uncited/unknown，重大错误和争议独立复核。
- 记录 JSON/结构/截断、token/cache 与 usage 完整性、冷加载、内存、实例/运行租约。
  既往蓝屏/WHEA 根因仍未解决；本 PR 只观察资源及异常停止，不安排硬件压力测试。
- 给出明确的单例资格通过/不通过/unavailable 及依据；不新增绝对质量及格线，
  HTTP 200 或 completed 不能单独替代资格判定。若不达标，必要最小修复留在本 PR，
  代码/测试变更必须聚焦、全套及规定的独立复审；本次继续授权内的新尝试单列分母，
  原额度耗尽或需扩大调用/研究边界时另授权。
  修复生产代码或 Prompt 后形成新候选并提交，再取得该版本的单例资格，不继承旧版本资格。
- 资格通过后确认该已冻结尝试的 Git/依赖、模型参数、manifest/registry、知识、
  非敏感配置 hash 及启动策略为 PR2 的锁定候选。
  不把一次资格通过当稳定性保证或并发解禁。

交付落在现有单例验真、运行契约及采集工具中；原始报告/Trace/控制器留本地。

## O1-PR2：正式串并发基线与逐轮评审

以 PR1 资格通过为前置；2026-09-21 持续授权已覆盖两轮新批次额度。保持同一锁定候选，无中途调参。
每个 profile/repetition 使用独立空产品/检查点数据库对和同一知识快照，
采用同一冻结的冷启/预热策略，准备时间与研究时间分别记账。
缓存默认开启，自学习/只读设置一致；启动前确认资源条件与异常停止线，持续观测内存及
实例/运行租约。PR1 一次单例正常不证明 12 并发容量，不另安排压力测试。

### 2026-09-19 正式执行结果

- 冻结候选 `7d622fd4916dad950ca077924327647a1f8f12c0`；数据集 hash
  `e0317ddeaa2b37526f5a7261d8df26217b75619d6c46bcd1bc8705895f16981f`；知识快照 hash
  `e55ddcac30d0e498c6e5ae02cb40d1bae95eb2831fda71e924ed9211b76466e4`。12 个 case 的
  manifest 映射、依赖、配置、端点、代理、embedding revision、asset registry 及六个执行工具
  均在首个正式准入前冻结。正式根为本地 ignored 输出，不提交报告正文、Trace 或私密环境。
- 首次前置因本地监控 wrapper 参数名不符合冻结候选的严格签名检查，在分派前停止：
  0 HTTP、0 Tavily POST、0 LLM、0 research run。保留该失败证据；修复只改 wrapper 的
  `self/request` 调用约定，经静态检查和独立复审后使用 fresh 路径重试。
- fresh 前置通过：五类检索路由健康，Tavily POST 200，DeepSeek JSON/tool 2/2；外层观测
  10 个 HTTP 请求，其中内置预算记录 8 个非 LLM、2 个 LLM、1 个 Tavily POST；金额
  unavailable，research run 为 0。
- serial-r1 仅准入随机顺序首例 P06。collector 在停线记录中观测 wall time 19.125 秒；
  取消后的生命周期为 21.418 秒，active ledger 为 21.264 秒。控制器因 Tavily 无凭据静态
  `HEAD /search` 返回 401 而锁定 `PR2_EXTERNAL_HTTP_STOP`。冻结候选的探测契约明确把
  Tavily 任意 2xx-4xx 视为已到达路由，回归测试固定 401 为健康；其余已观测业务 GET/POST、
  Tavily POST 与 LLM 请求均为 200，未见 external failure。因此这是 PR2 控制器把所有
  `>=400` 一律当来源异常造成的 P1 误报，不是已证实的 provider 降级或限流。
- 停线后没有第二次准入。产品数据库只有 1 个 task/run，公共事件为 queued、started、progress、
  cancel_requested、cancelled；task/run 均已持久化为 cancelled。11 个记录为 not_submitted。
  服务已发出 `service_stopped`，但子进程未在有界等待内自然退出，控制器对已验证归属的进程执行
  terminate，退出码 15；未留下未解析进程。该关闭异常必须在新批次前离线诊断。
- 控制器从取消前的 collector 快照生成 `active-budget-metrics.json`，因此错误记录 active settled=0
  且标记不完整；取消结算后的产品库按每个 reservation 最新 ledger 行聚合为 active 21,264 ms、
  LLM 4、retrieval 6、total tokens 1,265，均无未结 reservation。原 `runs.jsonl` 保留不改写；
  新控制器须在 cleanup 达终态后通过 public observability API 另采 stop-final 预算/调用证据。
- 正式根的工具身份已冻结，且协议禁止异常后补跑、跨候选拼表或修改工具后继续同轮；因此不修补
  P06、不启动 concurrent-r1/round-2。下一次真实批次必须先形成新的控制器候选：child 对完整
  Tavily 静态探测目标写入安全 operation enum，control 仅允许该 exact operation 的 2xx-4xx；
  Tavily POST 4xx、其他 HEAD 4xx、全部 5xx、连接失败和残缺遥测仍 fail closed。还须离线覆盖
  401 健康、429/5xx/失败停线、取消后 final 预算采集及正常退出。新的真实额度和批次须重新批准。

### O1-PR2A 离线控制面修复

- 新增 tracked successor 工具 `scripts/o1_pr2a_prepare.py`、`scripts/o1_pr2a_child.py` 和
  `scripts/o1_pr2a_control.py`；2026-09-19 首次正式尝试使用的 `notes/o1-pr2-*` 工具及其
  原始输出保持不变。successor 准备器只冻结这三个 PR2A 控制链文件；PR2B 的 preflight、
  review-pack 与 round-gate 须在真实执行授权后基于当前维护契约另行组装和冻结。
- child 以不保留 URL 的 operation enum 分类请求。只有 method/scheme/host/port/path/query
  全部精确匹配的 `HEAD https://api.tavily.com/search` 是 `tavily_static_probe`，允许
  2xx-4xx；Tavily 业务请求、其他 HEAD 和其他 operation 仍只允许 2xx-3xx，所有 5xx、
  transport failure、缺字段和残缺 JSONL 均 fail closed。
- 准入时绑定 task/case/run。cleanup 达终态后、停服务前，控制器通过公开 task detail 与
  observability API 验证终态和 latest-run identity，并另写
  `stop-final-observability.json`；`active-budget-metrics.json` 只从该停止态证据生成，
  不改写原 `runs.jsonl`，也不读取私有 Trace/checkpoint 表补证。
- shutdown 在触碰 stop flag 前等待已观测的首次冷 embedding 初始化 start/end 配平，
  上限 180 秒；超时或结构异常保持阻断。最终成功还要求 `service_stopped`、
  `asyncio_runner_returned`、进程自然退出码 0 和停止态证据完整，terminate/kill 不能通过。
- 聚焦离线回归 27 项覆盖 exact 401 健康、Tavily POST 400/429、其他 HEAD 401、5xx、
  transport failure、残缺遥测、run identity/终态、停止态 active ledger、冷初始化收束顺序
  与事件循环返回。PR2A 没有网络、付费、LLM 或 research run；它修复测量控制面，
  不把已取消 P06 改成有效基线，也不授权 PR2B。
- 最终本机验收：27 项聚焦和 1505 项全套测试通过，0 skipped（全套 207.76 秒）；
  smoke-v1 固定 12/12 与既有 baseline 匹配，pyflakes、vulture 100%、pip check 与 diff
  检查通过。该结果验证离线控制逻辑，不替代 PR2B 的真实服务退出或串并发验收。

### O1-PR2B 第一轮首次执行与后继控制器

- 2026-09-21 fresh 前置通过后，serial-r1 仅准入 P06。约 190 秒时，一个公共引用
  safe-fetch GET 返回 403；产品引用校验把该状态解释为
  `unreachable/not_publicly_accessible`，PR2A controller 却误报
  `PR2_EXTERNAL_HTTP_STOP`。停止锁生效后没有第二次准入，另外 11 个 serial case
  为 not_submitted，concurrent-r1 未启动，第一轮门禁 unavailable。
- P06 取消请求已提交，但 30 秒 cleanup 窗口结束时 task/run 仍为 `cancelling`；
  stop-final observability 与 active budget 因此不完整。服务随后正常发出停止和 asyncio
  runner 返回事件，退出码 0、无残留进程。服务 RSS 峰值约 2.178 GiB，可用内存最低约
  602 MiB，主机资源风险仍是下一次执行的显式观察项。
- 新增 `scripts/o1_pr2b_child.py` 和 `scripts/o1_pr2b_control.py`，并让 PR2B prepare
  与 round gate 冻结/验证这组新身份。child 通过任务本地 ContextVar 把 safe-fetch 内部
  请求标为 `safe_fetch_public`，不保存 URL；仅该 operation 的 GET 2xx-4xx 被视为有界
  引用结果。5xx、transport failure、非 GET 或错误 source 继续 fail closed；Tavily POST、
  其他 HEAD 和所有 provider 规则保持既定停线。
- cleanup 最多等待 180 秒，并在轮询期间持续执行 512 MiB 可用内存停止线。超过时限或跌破
  停止线仍保持 unresolved，不生成成功 profile。
- 离线验收为 41 项 PR2A/PR2B 聚焦回归与 1519 项全套测试通过、0 skipped（193.56 秒）；
  smoke-v1 12/12 baseline 匹配，pyflakes、vulture 100%、pip check 与 diff 检查通过。
- 失败根和 PR2A 工具保持不变；协议禁止在已停止的同轮自动补跑。因此这次批准实际产生
  1 个已准入 run，未完成 24-run 第一轮。离线验收完成后，新的 fresh 第一轮须重新获得
  明确执行批准。

### O1-PR2B 重新执行停止与来源判定修复

- 重新批准的 fresh 前置通过五类路由、Tavily POST 200、DeepSeek JSON/tool 2/2；
  prepare 冻结 `26185c5` 控制器、候选 `7d622fd`、知识种子和 12-case manifest。
- serial-r1 先后完成 P06 与 P07。P06 为普通报告；P07 六源全部 success，但证据不足门禁按
  冻结动作生成 limited_report。控制器把 `evidence_insufficient_user_limited` 视为来源
  partial failure，锁定 `PR2_SOURCE_DEGRADATION_STOP`；其余 10 例未提交，未启动并发组。
- 两个 run 的终态 observability/active budget 完整，服务自然退出。合计 17,467 tokens、
  21 LLM / 12 retrieval、0 failed calls；峰值 RSS 约 2.029 GiB、最低可用内存约 843 MiB。
  观测到 2 个 HTTP 4xx、0 个 5xx 和 0 transport failure，不支持来源降级结论。
- 修复后来源门只接受六个 distinct source envelope 全部 success；非来源 HITL/budget 标记
  不影响来源健康。缺失、重复、failed/partial envelope 仍 fail closed。
- 离线验收：46 项聚焦与 1524 项全套通过、0 skipped（229.00 秒）；smoke-v1 12/12
  baseline 匹配，pyflakes、vulture 100%、pip check 与 diff 检查通过。首次全套中的既有
  coordinator 时序断言失败经单项 11/11 和完整重跑 1524/1524 通过。
- 本次 fresh 根保持不变且不得补跑；第一轮仍缺完整 12+12 配对。再次真实执行须新建 fresh
  根、冻结新 controller hash，并重新获得明确批准。

### O1-PR2B 第三次 fresh 执行停止与安全失败分类修复

- fresh 前置再次通过五类路由、Tavily POST 200、DeepSeek JSON/tool 2/2；prepare 冻结
  控制提交 `8a959a2`、候选 `7d622fd`、原知识种子和 12-case manifest。
- serial-r1 依次完成 P06、P07、P08、P09。P07 按冻结动作生成 limited_report，其余三例为
  普通报告；四份报告终态 token/cache 完整，合计 52,867 tokens、67 LLM / 24 retrieval、
  0 failed calls。P11 已完成六次成功 retrieval 与后续 LLM 节点，在引用验证阶段尚未出报告。
- P11 的动态引用通过精确 `safe_fetch_public` 路径时出现
  `UnsafeUrlError(route_unsupported)`。产品引用契约将所有已知 `SafeFetchFailure` 安全类别
  结算为 `unknown/network_uncertain`，控制器却把 httpx 层该异常统称为 transport failure，
  锁定 `PR2_EXTERNAL_HTTP_STOP`。停止后的另一个 `CancelledError` 是取消造成的次生事件。
- P11 最终 durably cancelled，停止态 observability 完整：13,569 tokens、20 LLM /
  6 retrieval、0 failed calls，token/cache 完整。七例未提交，concurrent-r1 未启动；服务
  自然退出码 0。最低可用内存约 1.07 GiB，峰值服务 RSS 约 2.15 GiB，没有越过 512 MiB 停止线。
- 修复后 child 在 `external_http_failure` 中只公开 allowlist 的安全失败类别；controller
  仅接受精确 `safe_fetch_public` / `safe_fetch` / GET、`UnsafeUrlError` 与六个已知类别的
  组合。缺字段、未知类别、普通 transport error、错误 method/source、5xx 和 provider 失败
  继续 fail closed；产品安全策略、引用状态、案例、Prompt、预算和 HITL 均未改变。
- 离线验收：58 项 PR2A/PR2B 聚焦与 1536 项全套通过、0 skipped（191.19 秒）；smoke-v1
  12/12 baseline 匹配，pyflakes、vulture 100%、pip check 和 diff 检查通过。本次停止根保持
  原样且不得补跑；新的完整第一轮仍须 fresh 根和明确批准。

### O1-PR2B 第四次 fresh 第一轮：串行完成、并发租约停止

- 前置与 prepare 绑定控制提交 `30c63f9`、候选 `7d622fd`、原知识种子和 12-case
  manifest；五类路由、Tavily POST 200、DeepSeek JSON/tool 2/2。
- serial-r1 完成 12/12，10 份普通报告、P07/P12 两份 limited_report；终态 token/cache
  完整，149,654 tokens、185 LLM / 72 retrieval、0 failed calls，makespan 552,000 ms。
- concurrent-r1 一次准入并观测到 12 路 running，在 multi_retriever 阶段发生实例 heartbeat
  与 11 个 run heartbeat 失权。0 报告、0 可评分配对；第二轮未启动。最低可用内存约
  1.16 GiB、高于 512 MiB 停止线，峰值 RSS 约 2.05 GiB；服务自然退出且无残留进程。
- 只读停机现场保留 12 个 running task/run 与对应 started Trace。失败根不得重启或补跑。
  四条 HTTP `CancelledError` 是失权后的取消结果；控制器原先先检查 telemetry，错误记录为
  `PR2_EXTERNAL_HTTP_STOP`。
- 修复让 filesystem 产品库的实例 guard 与 run heartbeat 共用一条专用 SQLite 连接/锁，
  不再排在主连接高流量事务之后；仍是同一数据库与原 fencing/TTL，SQLite writer busy 或
  event-loop stall 继续 fail closed。控制器优先记录不安全 health。真实 SQLite 回归覆盖
  12 路续期、实例 guard 与主连接锁超过一个完整租约窗口。
- 离线验收为 103 项聚焦、1539 项全套通过、0 skipped（189.64 秒）；smoke-v1 12/12
  baseline 匹配，pyflakes、vulture 100% 与 pip check 通过；独立只读复审无阻断项。
  未重启失败根或新增付费调用。
- 因生产 runtime 改动，旧 `7d622fd` 仅保留为上述证据身份。下一 live 候选必须先重新
  单例资格/冻结；通过后 fresh 第一轮与后续第二轮仍分别授权，禁止跨候选补齐。

| PR 内检查点 | 新研究 run 上限 | 该段交付与推进条件 |
|---|---|---|
| 第一轮 | 24：12 serial + 12 concurrent | 完整配对、盲评/复核与门禁判定；不只运行后看 CSV passed；存在异常停止后续准入 |
| 第二轮 | 另批 24：12 serial + 12 concurrent | 第一轮满足既定门禁且无未解决阻断后单独批准；完成第二次独立配对和判定 |

- serial 是整 case 并发 1，concurrent 是 12 个完整任务在途，记录真实 running 观察及其局限。
- 正式 HITL 沿用冻结动作：P08 一次有界补充、再次暂停则 limited_report；其余默认
  limited_report，人工等待单列，不把 PR1 等待即停模式带入正式比较。
- 保留所有已启动 run，包括失败/取消/未结束；来源降级/限流、预算/租约、非预期恢复或主机异常即停止
  后续准入，已提交任务按正式流程收尾，不自动补跑或跨候选拼表。
- 每段同步做隐藏 profile/版本标签且随机顺序的报告评审，保留提交及评审顺序/随机种子、
  逐处关键声明台账及重大错误/争议独立复核。所有声称改善项也须独立依据；
  锁定评分后再看 Trace 归因。实施者不接触保留集正文、逐例分数或失败原因，
  锁定后的隔离评审/复核者只回聚合。以保留集调参则该集退役，另建保留集并重新批准；
  正式比较中修复产生新候选时，不能跨候选补齐本轮报告。
- 报告完成率、普通/受限报告、决策/引用/来源/冲突分数及全部调用、限流、重试、
  token/cache/unknown usage、wall/queue/active/等待/makespan；金额 unavailable 不填零。
- 严格沿用 v4 门禁；每轮缺完整 12 组成对可评分报告则质量 unavailable，
  两轮及复核均满足才可声明并发门禁通过，并注明助手评审/人类校准资格。

历史 run、PR1 单例与 PR2 新批次是独立分母；本次 PR2 只有 1 个已准入后取消的 run。
提前停止时交付诊断证据，仍不标完整基线完成。用户若选择缩减 48-run 交付，
须明确修订协议与对应结论范围，不能由 PR 分包暗中降低验收标准。

## O1-PR3：O1 结项与优化假设

- 汇总已批准测量的冻结身份、独立分母、逐轮门禁、宏/微指标、完整声明台账及复核覆盖。
- 准备/研究费用分账，Trace 实耗与预算 ledger 区分；无法定价或缺 usage 保持 unknown。
- 将问题按是否改变决策、影响案例数及修复成本排序，选 **一个** 主要优化假设；写清目标
  案例、预期机制、质量/成本判据、测量窗口与回退条件，不在本 PR 实施 O2。
- 分别报告 O1 评估是否闭环、并发是否通过及最终产品验收是否具备条件。
  O1 闭环可得出不通过；缺测量/评分/复核仍 unavailable，不能以一份总结替代。
- 人类校准当前尚未执行。助手盲评和独立复核可给暂定结论；若要声称最终产品质量验收，
  还须明确的人类校准/验收记录，不以助手一致替代。

交付优先更新现有评估协议/验收摘要与风险记录，只保留必要的脱敏可复算证据。
演示、面试材料、企业平台扩展以及 O2 生产优化不属于这 3 个 PR。

依赖依据：[评估协议 v4](product-effectiveness-optimization.md)、[O1-A 记录](o1a-evaluation-closure.md)、
[单例观察](o1r-single-case-reliability.md)、[六源限流离线审计](o1-retrieval-throttle-audit.md)、
[O1-B 观测与补修](o1b-prebatch-observability.md)。
