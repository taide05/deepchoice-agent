# O1 执行断点

2026-09-21 最新授权：用户给予候选 `15ca251` 的有界持续授权，覆盖一次 P01 单例资格、
资格通过后的两轮正式测量（每轮 12 serial + 12 concurrent）及本地 O1-PR3 收口，研究 run
原总上限为 49（1 + 48，失败/取消/limited 均计入）。沿用此前批准的查询、候选项、必要上下文、
DeepSeek/Tavily/GitHub API/StackExchange API/arXiv/PyPI/官方来源、当前 local-proxy/
self-forward 路由及公共 HTTP(S) 引用安全抓取范围。正常阶段门禁通过后无需再次征求批准；
资源、预算、租约、主机、身份或质量异常须自动停线。超额、扩展外传范围、改变冻结评测口径、
冻结后生产代码变更所需的额外付费替代运行，以及 push/merge/release/发布仍须另行批准。
在本页所述 HEAD 遥测误判停线后，用户已批准离线 source-aware 修正，并把总上限从 49
调整为 59；供应商、外传范围、案例、rubric、预算、HITL 和质量阈值均不变。

随后候选 `15ca251` 的 P01 单例资格完成并由独立只读复核确认助手暂定通过：前置五类路由、
Tavily POST 和 DeepSeek JSON/tool 均通过；P01 completed，11 LLM / 6 retrieval，11,914 tokens，
0 failed/retry/lease loss，usage/cache 完整。v4 台账为 68 原子，支持 31/22/1/2/12，来源质量
7/52/9；必答 5/6、冲突 2/2、冻结重大错误 0。“零运维”五次绝对化为重要非阻断缺陷；动态
pinned CONNECT/TLS 仍 unavailable。产品库及 immutable result 一致，停后 PID/端口无残留，
exit code unavailable。资格使用 1/49，正式两轮当时剩余 48。PR2B 五个执行工具已重绑定
新候选，33 项聚焦与 1540 项全套、0 skipped（184.26 秒）通过；控制冻结提交为 `83185ad`。

随后 `83185ad` 控制器在 fresh 根 `o1-pr2b-round1-20260921-15ca251-standing-v1` 启动正式
serial-r1，准入 10/12 后按停止线退出：8 completed、P07 completed_with_warnings/limited_report、
P05 cancelled，P03/P10 未提交，共 9 份报告。停止后 10 个已入场 run 的公开观测完整，合计
101,227 tokens、126 LLM / 60 retrieval、0 failed calls；服务 graceful exit 0，cleanup unresolved 0。
最低可用内存 0.898 GiB、高于 512 MiB 线，峰值服务 RSS 2.191 GiB；172 个 health 样本均 200、
authority 有效，heartbeat failure/lease loss 均 0。concurrent-r1 和第二轮均未启动。

停止原因为 `PR2_EXTERNAL_HTTP_STOP`，但离线核对确认是控制器契约遗漏：产品官方文档
`OfficialRetriever._verify_reachable()` 通过统一安全抓取明确发出 `HEAD`，且 `SafeUrlPolicy`
支持 GET/HEAD；子控制器用布尔上下文把该请求折叠成 `safe_fetch_public`，父控制器又只允许该
operation 使用 GET，因而把成功的 HEAD 302→200 误判为异常。三个 GET
`UnsafeUrlError(route_unsupported)` 均属于控制器已接受的冻结安全结果，provider 调用未见失败。
停止根保持不变，不重启、不补跑、不与新根拼接。持续授权累计使用 11/59，未用 48；重新取得
完整配对仍需从新根执行 48 个 run。source-aware 修正把 exact `official` 安全抓取投影为独立
operation，只允许产品契约的 HEAD/GET（包括既有 HEAD 405/501 回退），公共引用继续仅允许 GET；
错误来源/方法、普通 transport 异常和不允许的 5xx 均 fail closed。精确事件回放只改写旧根的
两条合法官方 HEAD 事件后通过，注入 POST 仍停线；50 项聚焦、pyflakes、diff 检查和最终
1557 项全套测试通过（198.52 秒）。首次全套中的 learned-docs Windows `PermissionError` 为独立
瞬态：该单项随后连续 5 次通过，完整重跑也通过。本次控制结果、遥测、stop-final 和
resource-health SHA-256 分别为
`682129ee20291564832d55f126219d52482813fe1b67387e3f41bc2226618203`、
`f49f232b4ebeb9b18a46b8811b029f1f13ab49c90b061edf2d4957ecc4ce2b47`、
`73e00da001e258bc23ba007b2e8deb10c6878ced010ac3429a1c4a8f906d499c`、
`db91058a992267384c9ab49e36f3b559f42102fe8c38ee94cb47ee34076bc8f5`。

较早的第四次正式第一轮尝试（2026-09-21，已由上文新候选状态取代）：用户批准使用控制提交
`30c63f9`、新的 fresh 输出根、原冻结
候选 `7d622fd` 和原知识种子，执行 O1-PR2B 完整第一轮 12 serial + 12 concurrent。
有界前置再次通过五类路由、Tavily POST 200 与 DeepSeek JSON/tool 2/2；0 research run。
fresh prepare 冻结候选、12 个 case manifest、知识种子及六文件 PR2B 控制链。

serial-r1 完成 12/12：10 份普通报告，P07/P12 为冻结动作下的
completed_with_warnings/limited_report；所有终态 token/cache 完整，合计 **149,654 tokens、
185 LLM / 72 retrieval、0 failed calls**，profile makespan 552,000 ms。该串行结果只属于
本次候选/轮次，尚无可配对并发报告，不能单独判质量或并发门禁。

concurrent-r1 一次准入 12/12，并观测到 12 个 run 同时 running；进入多源检索后，实例
heartbeat 与 11 个 run heartbeat 在约 31 秒无成功续期后失权。控制器立即停止，未生成报告，
未启动第二轮。最低可用内存约 1.16 GiB，高于 512 MiB 停止线；峰值服务 RSS 约 2.05 GiB。
服务自然退出码 0、无残留进程/监听。停止后的只读产品库核对显示 12 个 task/run 仍为 running；
WAL 为空。该根不得重启，避免自动恢复改变现场。Trace 只显示 query_adapter 12 succeeded，
multi_retriever 1 succeeded/11 started，各六源 1 succeeded/11 started；这定位到并发检索阶段，
不构成语义质量结果。

四条 `external_http_failure/CancelledError` 均发生在实例/run 失权后的任务取消阶段；
成功 provider 响应先于它们。旧控制器先检查 HTTP telemetry，因而误写
`PR2_EXTERNAL_HTTP_STOP`；真实首因是资源/租约停止。离线修复让 filesystem 产品库使用一条
专用 SQLite 连接和锁承载实例 guard 与 run heartbeat，避免在主连接的 Trace、预算、缓存与 API
高流量队列后等待；仍使用同一数据库、同一 fencing/TTL，SQLite 写锁超时或事件循环停顿继续
fail closed。控制器只在 HTTP 遥测全部为 `CancelledError` 且 health 不安全时记录资源/租约
停止；真实 5xx/transport failure 仍优先外部停止。真实 SQLite 回归同时运行
12 个 run heartbeat 与实例 guard，在主连接锁阻塞超过完整租约窗口时仍保持续期。

本轮修复通过 103 项聚焦回归与 **1539 项全套测试、0 skipped（189.64 秒）**；
smoke-v1 12/12 baseline 匹配，pyflakes、vulture 100% 与 pip check 通过；独立只读复审无阻断项。
本轮没有为修复再次联网、提交研究或重启失败根。由于生产 runtime 已改变，`7d622fd` 只保留为本次已测证据身份，
不能作为下一次 live 的当前候选；当时的下一步是从新提交形成候选并重新完成单例资格/冻结。
该前置现已由上文候选 `15ca251` 完成，fresh 正式两轮也已纳入持续授权；24-report 配对、
声明台账、第一轮门禁和第二轮结果仍 unavailable。

PR1 历史分母与 PR2 新批次分开；下文为较早历史轮次。

2026-09-17 最新诊断：用户要求先定位两项阻断；一次 community 单源反馈为 HTTP 400 /
API 502 throttle_violation，probe 未带已配置的可选 key，限流范围/恢复期限未知。
本轮带观察器离线回归 54 passed（27.35 秒），确认毫秒级断言低于本机时钟分辨率且
混用了准入/调用起点；原 RequestGate 虚拟时钟反例复现同类断言失败。
[定位记录](o1c-blocker-diagnosis.md)保留首次失败及未确认边界；未改产品/测试、未修复，
LLM/Tavily/研究调用 0、43/48 不变，不恢复单例/批次或进入 O2。

2026-09-17 最新更新：用户授权 O1-C 真实单例验真，本次选 P01 一次提交上限。
真实前置网络健康 4/5，community 选中 self-forward 但未通过（代码推断 provider gate 不可用，
具体限流反馈未采集）；routed Tavily POST 通过。本轮按停止线停在前置阶段，
LLM 探测/冷启/研究/报告均 not_run，新建 run 0、累计 43/48 不变。
本轮额外离线回归 53 passed / 1 failed（模拟调度时间断言），单项复查 1 passed；
首次失败保留、原因未确认，未修改代码/断言，不代表当前验证全绿。
见 [O1-C 停止记录](o1c-single-case-verification.md)。不自动重查或补跑、不恢复批次、不进入 O2；
O1 仍 incomplete。下文保留各轮当时状态。

2026-09-17 后续更新：用户授权 O1-B 批次前观测，并批准租约/冷加载/过期 health 最小补修。
[O1-B 记录](o1b-prebatch-observability.md)保存安全字段、离线故障、验收及残余边界。
离线已完成：187 聚焦、1238 全套通过且无跳过（全套 211.83 秒），smoke-v1 12/12 baseline 匹配，
静态/依赖门禁及独立只读复审无阻断。
O1 仍 incomplete；真实冷启、主机和新候选逐次单例资格未验收，不启动 C、批次或 O2，
43/48 及剩余 5 不变。下文按原日期保留。

2026-09-17 当前更新：用户授权 O1-A 收口评估口径，v4 区分历史/开发/新正式配对分母并
补六份开发报告原子台账，见 [收口记录](o1a-evaluation-closure.md)与 [剩余任务卡](o1-next-steps.md)。
旧评分绑定/历史记录不回填；O1 仍 incomplete，来源健康 not_run，43/48 及剩余 5 不变，
无新付费研究、无保留集揭示、无批次恢复或 O2 授权。下文按原日期保留各次观察。

日期：2026-09-16。状态：案例已冻结，累计创建 43/48 个研究 run（原基线 36 + O1-R 7）；最新候选三开发例各两次 **6/6 正常完成**，本轮服务/采集器已关闭；原串并发基线暂停，**O1/真实基线未完成**。[部分实测](o1-live-baseline.md)、[O1-R 样本观察](o1r-single-case-reliability.md)。

## 已确认

- 2026-09-17 O1-A 已完成：六份旧候选报告 279 关键声明出现项、暂定引用 79/279、来源 8/279；
  独立只读复核无剩余阻断项但未全量重评分/人类校准；聚焦 20、全套 1196 passed / 0 skipped
  （192.12 秒），smoke 12/12 及静态/依赖门禁通过。[收口记录](o1a-evaluation-closure.md)保留范围与盲区。
  无新付费研究/批次/保留集揭示，O1 仍未完成，下一建议 B 离线资格须确认。

- 2026-09-17 继续用户授权的六源限流离线修复，覆盖正常检索、补证工具、探测与重试的共享准入；
  已完成离线验收：223 项聚焦、1176 项全套通过，无跳过；smoke 12/12、静态/依赖检查及独立复审
  无阻断项，[限流审计](o1-retrieval-throttle-audit.md)记录证据和边界。本轮没有真实检索/研究调用，
  43/48 与剩余 5 不变，来源健康 not_run，真实付费批次继续暂停；不宣布 O1 完成或进入 O2。

- 用户授权助手核验已有六份最新开发报告并补缓存成本拆账：完整阅读、关键声明核对及暂定必答/冲突评分见 [核验](o1-development-report-review.md)。不是人工盲评或完整原子引用分母，系统引用状态保持不变。新观测可采集 hit/miss，但旧 167 调用均未采集；最终全套 1142 passed / 0 skipped（218.18 秒），静态/独立复审见 [拆账](o1-cache-cost-accounting.md)。来源/语义与并发门禁不因此通过，无新付费研究、43/48 及剩余 5 不变。

- 用户已确认 O1-R 实施，预算/恢复/旧 KB 工具最小修复落地。最新候选 P01/P06/P07 各两次，6/6 正常完成、Trace 用量完整，共 143,354 token，1/78 scholarly 逻辑检索失败，来源 degraded；补修前 P06 24,855 token 另存、不计六次。O1-R 当时全套 1116 passed / 0 skipped（223.14 秒），独立复审无阻断项，见 [可靠性观察及残余风险](o1r-single-case-reliability.md)。剩余额度 5，不启动批次，不宣称语义/严格 JSON/冷启动/并发或硬件稳定已验收。
- 最新用户约束（2026-09-16）：单 case 稳定成功前，禁止 12-case 付费并发及整组串行。优先离线复现/最小修复，再逐次单 case 验证；不得自动排队多例。建议稳定门槛与已批准修复范围见 O1-R；通过单 case 验收后，恢复批次仍需用户确认。
- 用户接受最多 48 个研究 run（12 case × serial/concurrent × 2 次），另含检索健康检查和最小 LLM 探测；失败不自动补跑。
- 原 12-case 基线已创建 36 个研究 run，未恢复旧任务；serial-r1 报告 1/12、concurrent-r1 报告 0/12，concurrent-r2 因实例权限丢失主动作废/停止，serial-r2 未提交。该原基线唯一成功 P04 的完整 Trace 用量为 14,778 token；[逐例安全观察](o1-token-observations.csv)不是完整账单，不与本轮三例六次合并分母。
- DeepSeek 非 thinking JSON 和工具调用成功。成功探测的已知用量为输入 313、输出 36、总计 349 token。此数不是研究成本，也不是整个准备过程的账单。
- 前两次探测因采集脚本误用共享 helper 的 prompt/response_format 契约而返回 HTTP 400；脚本已修正并补测试。这不构成模型效果差的证据，其缺失 usage 不填零。
- 重启后 5 个 credential-free 路由探测通过；随后完整 health-check 的 routed Tavily POST 返回 HTTP 200。Tavily/GitHub/arXiv/official 使用 local-proxy，community 使用 self-forward；健康不是研究效果。
- `ChromaKB` 原来忽略 `CHROMA_PATH`，现按既有配置读取，默认路径及 `tech_kb` collection 不变。Docker 同步传递知识库/learned-docs 设置；未改写现有知识库。
- 采集器新增即时 fsync 提交日志、固定 run 身份、取消后有界观测、逐 case `usage.csv`、随机种子/顺序、实际 running 观测峰值、开发/保留集分目录。评分绑定 run 和实验身份，无配对报告不判通过；预算未知扣账与已知 Trace 实耗分列。
- 用户在本会话批准[官方参考清单](o1-reference-audit.md)及评分规则冻结。数据集现为 `1.0.0/frozen`，日期 2026-09-16，hash `e0317ddeaa2b37526f5a7261d8df26217b75619d6c46bcd1bc8705895f16981f`；核验由助手完成，真实报告人工盲评/复核仍待执行。P11 明确包含 RabbitMQ Streams 重放边界，不预设唯一赢家。

本地探测原件：`outputs/product-baseline-v1-20260916/`。不提交密钥、`.env`、原始端点或报告正文。

## 原串并发基线阻碍（历史证据保留）

serial-r1 有 11 个 BUDGET_EXCEEDED_INSUFFICIENT_EVIDENCE；concurrent-r1 有 10 个 RESEARCH_FAILED 及 2 个预算证据不足。concurrent-r2 健康为 runtime_instance=lost，取消接口返回 RUNTIME_INSTANCE_LEASE_LOST；产品公共事件有 12 次自动恢复入队。无法把“采集器不调用 resume”当成整个服务不恢复。三个服务/采集器已关闭，数据库及提交日志保留；11 个 queued 非终态，**不要重启原目录或绕过租约写入**。第 1 次配对报告 0/12，质量门禁 unavailable/未通过，第 2 次无有效配对。根因诊断/最小修复及新复测分配需要用户方向，不能用剩余 12 个 run 自动补齐作废组。

主机于 15:30、15:48 重启，System BugCheck 都为 `0x124`；WHEA-Logger 18 报告处理器核心的 Machine Check Exception / Bus-Interconnect Error。2026-09-14 还有 Cache Hierarchy Error 记录。

该错误码表示系统报告致命硬件错误；不能据此确定具体部件或把根因归给项目代码。依据见[微软错误码说明](https://learn.microsoft.com/en-us/windows-hardware/drivers/debugger/bug-check-0x124---whea-uncorrectable-error)。未进行 BIOS、驱动、系统配置修改或压力测试。

用户在看到蓝屏记录后再次要求继续 O1。四个 profile 一致冻结数值库/torch 线程为 1，并离线预热已有 BGE-M3 缓存；未改变 LLM 并发门、Prompt、预算或整 case 并发要求。本轮最新 BugCheck 仍为 15:48，没有新增蓝屏；这不是硬件修复或稳定证明。

## 恢复顺序

1. 用户已批准在本机继续；不修改系统配置，不复制 `.env` 到交付文档。
2. 案例/参考依据冻结、完整检索健康和四组相同知识快照已完成。实验目录为 `outputs/product-baseline-live-20260916/`，知识 hash 为 `e55ddcac30d0e498c6e5ae02cb40d1bae95eb2831fda71e924ed9211b76466e4`。
3. 隔离服务空任务/健康启动验收已完成；正式执行代码为 7acb622，依赖、模型、环境/知识身份及时间在原件和实测报告中。
4. O1-R 的生产修复范围已确认：预算感知扫描、租约续期/并发诊断及实验恢复保护；使用受控离线故障验证，相关契约、独立复审、全套验证和提交后才重测。不要直接续跑当前数据库。
5. 中断时先查 `admissions.jsonl`、已创建 task/run 和服务状态。日志中的 `submission_started` 不代表已确认创建；不得重复 POST 或自动 resume/retry。先核对可能已扣费的任务，作废/补跑另经确认。
6. 不恢复批次：本轮逐次单例观察已完成，保留当前剩余 5 个原额度；后续严格结构/冷启/语义/并发风险仍需按范围验收，用户重新允许后才讨论完整配对及额外额度。原基线暂停时剩余 12 是历史分配，不是当前余额或批次许可；保留集正文继续封存。

## 原 O1 冻结阶段验证（最新候选见顶部链接）

2026-09-16，Python 3.12 项目虚拟环境：本次冻结/隔离聚焦测试 18 passed；代码/测试冻结后完整套件 1095 passed、0 skipped（206.27 秒）。pyflakes、vulture（100% confidence）、pip check、Compose 静默配置检查、frozen 结构/hash 校验、git diff --check 通过；smoke-v1 12/12，fingerprint 匹配。Compose 提示主 DeepSeek key 名未设置，当前使用已探测成功的兼容 key 名；未打印其值。

这是本机 Python 3.12 的离线验证，不冒充 Ubuntu/Python 3.11 CI 矩阵，也不证明真实报告质量或硬件稳定；Tavily 有效性来自单独的实时健康检查。探测原件与用户运行数据保留。

重启前的 `outputs/o1-focused-test-20260916` 因 Windows ACL 拒绝读取/删除而残留，未扩大权限或修改系统 ACL；需后续在有权访问它的环境中清理。它不是研究结果，不提交 Git，也不影响上述已完成验证。
