# O1 剩余交付与 PR 划分

更新：2026-09-19。2026-09-18 原始重组将剩余 C/D/E 工作组织为 **3 个 PR**，A/B 保留已完成状态；
该次规划不改变 [评估协议 v4](product-effectiveness-optimization.md)的冻结案例、rubric、质量/并发阈值、
HITL 策略或预算，且当时不构成新的实施、付费调用或发布授权。

随后用户依次授权并完成 O1-PR1，又在 2026-09-19 明确授权 O1-PR2 的新 48-run 批次。
PR2 已按停止线结束本次尝试，并重新拆为离线控制面修复 O1-PR2A 与重新执行/评审
O1-PR2B。PR2A 已完成；新的真实 PR2B 批次、O1-PR3 和发布仍未授权。

| 已完成部分 | 已有交付 | 尚不能据此宣称 |
|---|---|---|
| O1-A 评估口径 | 冻结 12-case/参考、v4 逐处声明口径、旧六份开发报告台账、独立复核及离线复算 | 当前候选的真实质量、人类校准或 O1 结项 |
| O1-B 观测与运行补修 | JSON/结构/截断/parser 次数、token/cache 拆账、失败分类、冷加载与租约/health 离线补修 | 当前候选的真实冷启、整 case 并发或硬件稳定 |
| O1-C 的 C1/C2 离线部分 | 候选准入/题名/互证/明确引用展示，逐子句引用提示，unknown 分类与地址拒绝，可信本地 CONNECT 适配及冻结身份 | 模型实际遵从、语义支持或真实 pinned CONNECT/TLS 互通 |

当前状态：**O1-PR1 与离线 O1-PR2A 已完成；原 O1-PR2 真实批次在第一轮首个
serial run 后按停止线阻断，O1-PR2B 尚未授权。**
PR1 冻结候选仍为 `7d622fd`；2026-09-18 的 P01 × 1 completed（167.469 秒、14,093 token），
53 原子完整台账及独立复核闭环；228 聚焦 / 1478 全套通过、0 跳过。
2026-09-19 的 PR2 受限前置通过，随后 serial-r1 仅准入 P06 × 1；该 run 已取消结算，
其余 11 个 case 未准入，concurrent-r1 与第二轮均未启动。质量配对、逐报告台账和轮次门禁
因此 unavailable，不能声明 PR2 基线或并发门禁完成。PR1 的累计 **46/48** 与 PR2 新批次分母分开，
不能拼接。候选、依赖/模型、逐 case manifest、registry、知识副本和工具身份保持冻结。

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
| O1-PR1 当前候选单例资格与冻结 | C3，含必要的 C 问题收口 | 先用一次当前候选 P01 冷启核对执行、引用/报告与成本；处理实际阻断后形成可测量的锁定候选 | 完整前置、可追溯单例记录、v4 内容核对与独立复核、资格判定和冻结清单；只有资格通过才进入 PR2 |
| O1-PR2A 控制面离线修复 | D 的执行前置 | 修复静态探测误报、停止态预算证据和冷初始化关闭阻断；不执行真实研究 | exact operation 单元测试、公开 API stop-final 证据测试、冷初始化收束/正常退出测试及全套验证；已完成 |
| O1-PR2B 正式串并发基线与逐轮评审 | D，含 E 的逐报告评审 | 用新的 fresh 根、同一冻结产品候选完成 12-case × serial/concurrent × 2 重复，共 48 个新 run；采集和质量核验一起交付 | 重新冻结 PR2A 工具身份；每轮 12 组成对报告、声明台账及独立复核；需要新的真实批次授权 |
| O1-PR3 O1 结项与优化假设 | E 的总体结论 | 汇总质量、运行/成本和残余风险，冻结一个最优先的 O2 假设 | 可复算结项报告、评审资格/校准状态、独立复核及假设卡；结论可不通过，O2 实施另授权 |

## O1-PR1：当前候选单例资格与冻结

- 收口执行入口：新输出目录、空产品/检查点数据库对、同一只读知识副本，资源线程上限和
  离线模型下载约束；明确冷启，避免现有 serve 的预热被误标为冷启。
  每次真实尝试在提交前冻结本次代码/环境身份及对应 manifest，不能事后给结果换身份。
- 单例资格模式在等待 HITL 时停止，不自动提交冻结 case 的决策动作；正式 PR2 的动作策略
  保持协议不变。冻结一次任务准入、关闭自动恢复的控制入口；不能用自动 limited_report
  把暂停转成资格通过。若需维护采集工具，相关变更及回归归入本 PR，先离线验收再真实调用。
- 本轮已批准一轮前置及 P01 一次：前置路由/健康 HTTP 上限 20，Tavily 付费 POST 上限 1，
  LLM JSON/工具探测实际请求上限 4；准备成本单列。失败停止，不循环探测或自动补跑。
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

以 PR1 资格通过及用户明确批准新批次/额度为前置；保持同一锁定候选，无中途调参。
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
