# O1 执行断点

日期：2026-09-16。状态：案例已冻结，已创建 36/48 个研究 run；因预算扇出及并发实例租约失效暂停，**O1/真实基线未完成**。[部分实测与 O1-R 修复卡](o1-live-baseline.md)。

## 已确认

- 用户已确认 O1-R 实施，最小修复与离线验证已通过（最终全套 1113 passed / 0 skipped，207.22 秒），独立复审无阻断项，见 [单 case 可靠性断点](o1r-single-case-reliability.md)。原始部分基线保持历史记录；当前生产修复获批，不再沿用旧记录中的“待批准”作为阻塞。尚未新增付费研究，剩余额度仍 12；不启动批次。
- 最新用户约束（2026-09-16）：单 case 稳定成功前，禁止 12-case 付费并发及整组串行。优先离线复现/最小修复，再逐次单 case 验证；不得自动排队多例。建议稳定门槛与已批准修复范围见 O1-R；通过单 case 验收后，恢复批次仍需用户确认。
- 用户接受最多 48 个研究 run（12 case × serial/concurrent × 2 次），另含检索健康检查和最小 LLM 探测；失败不自动补跑。
- 已创建 36/48 个研究 run，未补跑；serial-r1 报告 1/12、concurrent-r1 报告 0/12，concurrent-r2 因实例权限丢失主动作废/停止，serial-r2 未提交。唯一成功 P04 的完整 Trace 用量为 14,778 token；[逐例安全观察](o1-token-observations.csv)不是完整账单。
- DeepSeek 非 thinking JSON 和工具调用成功。成功探测的已知用量为输入 313、输出 36、总计 349 token。此数不是研究成本，也不是整个准备过程的账单。
- 前两次探测因采集脚本误用共享 helper 的 prompt/response_format 契约而返回 HTTP 400；脚本已修正并补测试。这不构成模型效果差的证据，其缺失 usage 不填零。
- 重启后 5 个 credential-free 路由探测通过；随后完整 health-check 的 routed Tavily POST 返回 HTTP 200。Tavily/GitHub/arXiv/official 使用 local-proxy，community 使用 self-forward；健康不是研究效果。
- `ChromaKB` 原来忽略 `CHROMA_PATH`，现按既有配置读取，默认路径及 `tech_kb` collection 不变。Docker 同步传递知识库/learned-docs 设置；未改写现有知识库。
- 采集器新增即时 fsync 提交日志、固定 run 身份、取消后有界观测、逐 case `usage.csv`、随机种子/顺序、实际 running 观测峰值、开发/保留集分目录。评分绑定 run 和实验身份，无配对报告不判通过；预算未知扣账与已知 Trace 实耗分列。
- 用户在本会话批准[官方参考清单](o1-reference-audit.md)及评分规则冻结。数据集现为 `1.0.0/frozen`，日期 2026-09-16，hash `e0317ddeaa2b37526f5a7261d8df26217b75619d6c46bcd1bc8705895f16981f`；核验由助手完成，真实报告人工盲评/复核仍待执行。P11 明确包含 RabbitMQ Streams 重放边界，不预设唯一赢家。

本地探测原件：`outputs/product-baseline-v1-20260916/`。不提交密钥、`.env`、原始端点或报告正文。

## 当前阻碍

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
6. 不恢复批次：先确认单次开发案例验证分配，逐次检查；稳定成功验收且用户重新允许之后，才讨论完整串并发配对及额外额度。当前剩余原额度 12 不是批次许可。已知 token/不完整边界已保存，语义质量仍待人工盲评及复核；保留集正文继续封存。

## 验证

2026-09-16，Python 3.12 项目虚拟环境：本次冻结/隔离聚焦测试 18 passed；代码/测试冻结后完整套件 1095 passed、0 skipped（206.27 秒）。pyflakes、vulture（100% confidence）、pip check、Compose 静默配置检查、frozen 结构/hash 校验、git diff --check 通过；smoke-v1 12/12，fingerprint 匹配。Compose 提示主 DeepSeek key 名未设置，当前使用已探测成功的兼容 key 名；未打印其值。

这是本机 Python 3.12 的离线验证，不冒充 Ubuntu/Python 3.11 CI 矩阵，也不证明真实报告质量或硬件稳定；Tavily 有效性来自单独的实时健康检查。探测原件与用户运行数据保留。

重启前的 `outputs/o1-focused-test-20260916` 因 Windows ACL 拒绝读取/删除而残留，未扩大权限或修改系统 ACL；需后续在有权访问它的环境中清理。它不是研究结果，不提交 Git，也不影响上述已完成验证。
