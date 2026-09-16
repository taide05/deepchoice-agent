# O1 执行断点

日期：2026-09-16。状态：用户已批准案例冻结，正在完成正式实验启动，**O1/真实基线未完成**。

## 已确认

- 用户接受最多 48 个研究 run（12 case × serial/concurrent × 2 次），另含检索健康检查和最小 LLM 探测；失败不自动补跑。
- 当前未提交研究任务，研究额度使用为 0/48；没有研究 case 的 token 成本可报告。
- DeepSeek 非 thinking JSON 和工具调用成功。成功探测的已知用量为输入 313、输出 36、总计 349 token。此数不是研究成本，也不是整个准备过程的账单。
- 前两次探测因采集脚本误用共享 helper 的 prompt/response_format 契约而返回 HTTP 400；脚本已修正并补测试。这不构成模型效果差的证据，其缺失 usage 不填零。
- 重启后 5 个 credential-free 路由探测通过；随后完整 health-check 的 routed Tavily POST 返回 HTTP 200。Tavily/GitHub/arXiv/official 使用 local-proxy，community 使用 self-forward；健康不是研究效果。
- `ChromaKB` 原来忽略 `CHROMA_PATH`，现按既有配置读取，默认路径及 `tech_kb` collection 不变。Docker 同步传递知识库/learned-docs 设置；未改写现有知识库。
- 采集器新增即时 fsync 提交日志、固定 run 身份、取消后有界观测、逐 case `usage.csv`、随机种子/顺序、实际 running 观测峰值、开发/保留集分目录。评分绑定 run 和实验身份，无配对报告不判通过；预算未知扣账与已知 Trace 实耗分列。
- 用户在本会话批准[官方参考清单](o1-reference-audit.md)及评分规则冻结。数据集现为 `1.0.0/frozen`，日期 2026-09-16，hash `e0317ddeaa2b37526f5a7261d8df26217b75619d6c46bcd1bc8705895f16981f`；核验由助手完成，真实报告人工盲评/复核仍待执行。P11 明确包含 RabbitMQ Streams 重放边界，不预设唯一赢家。

本地探测原件：`outputs/product-baseline-v1-20260916/`。不提交密钥、`.env`、原始端点或报告正文。

## 当前阻碍

主机于 15:30、15:48 重启，System BugCheck 都为 `0x124`；WHEA-Logger 18 报告处理器核心的 Machine Check Exception / Bus-Interconnect Error。2026-09-14 还有 Cache Hierarchy Error 记录。

该错误码表示系统报告致命硬件错误；不能据此确定具体部件或把根因归给项目代码。依据见[微软错误码说明](https://learn.microsoft.com/en-us/windows-hardware/drivers/debugger/bug-check-0x124---whea-uncorrectable-error)。未进行 BIOS、驱动、系统配置修改或压力测试。

用户在看到蓝屏记录后再次要求继续 O1。四个 profile 一致冻结数值库/torch 线程为 1，并离线预热已有 BGE-M3 缓存；不改变 LLM 并发门、Prompt、预算或整 case 并发要求。这不是硬件修复或稳定证明；再次重启先核对提交日志，不补跑。先观察首个计分 case 的启动和用量，再按批准计划推进。

## 恢复顺序

1. 用户已批准在本机继续；不修改系统配置，不复制 `.env` 到交付文档。
2. 案例/参考依据冻结、完整检索健康和四组相同知识快照已完成。实验目录为 `outputs/product-baseline-live-20260916/`，知识 hash 为 `e55ddcac30d0e498c6e5ae02cb40d1bae95eb2831fda71e924ed9211b76466e4`。
3. 完成隔离 durable 服务无研究启动验收。依赖、非敏感配置、模型参数/资产身份已冻结；已有 LLM 探测可作准备证据，若配置/模型漂移须先复核。
4. 冻结干净代码提交后运行 serial-r1 / concurrent-r1、concurrent-r2 / serial-r2；每个 profile 12 新任务，同 repetition 使用相同已保存种子/顺序。首个正式 run 同时验证真实采集，不另增授权次数。
5. 中断时先查 `admissions.jsonl`、已创建 task/run 和服务状态。日志中的 `submission_started` 不代表已确认创建；不得重复 POST 或自动 resume/retry。先核对可能已扣费的任务，作废/补跑另经确认。
6. 保存逐 case 已知 token、完整性、调用/重试、结果类型、预算结算/未知/预留；人工盲评及复核后才给并发门禁和首轮优化假设。保留集正文继续封存。

## 验证

2026-09-16，Python 3.12 项目虚拟环境：本次冻结/隔离聚焦测试 18 passed；代码/测试冻结后完整套件 1095 passed、0 skipped（206.27 秒）。pyflakes、vulture（100% confidence）、pip check、Compose 静默配置检查、frozen 结构/hash 校验、git diff --check 通过；smoke-v1 12/12，fingerprint 匹配。Compose 提示主 DeepSeek key 名未设置，当前使用已探测成功的兼容 key 名；未打印其值。

这是本机 Python 3.12 的离线验证，不冒充 Ubuntu/Python 3.11 CI 矩阵，也不证明真实报告质量或硬件稳定；Tavily 有效性来自单独的实时健康检查。探测原件与用户运行数据保留。

重启前的 `outputs/o1-focused-test-20260916` 因 Windows ACL 拒绝读取/删除而残留，未扩大权限或修改系统 ACL；需后续在有权访问它的环境中清理。它不是研究结果，不提交 Git，也不影响上述已完成验证。
