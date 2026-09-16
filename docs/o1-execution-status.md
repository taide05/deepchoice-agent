# O1 执行断点

日期：2026-09-16。状态：准备代码已通过本地验证，正式实测待执行，**O1/真实基线未完成**。

## 已确认

- 用户接受最多 48 个研究 run（12 case × serial/concurrent × 2 次），另含检索健康检查和最小 LLM 探测；失败不自动补跑。
- 当前未提交研究任务，研究额度使用为 0/48；没有研究 case 的 token 成本可报告。
- DeepSeek 非 thinking JSON 和工具调用成功。成功探测的已知用量为输入 313、输出 36、总计 349 token。此数不是研究成本，也不是整个准备过程的账单。
- 前两次探测因采集脚本误用共享 helper 的 prompt/response_format 契约而返回 HTTP 400；脚本已修正并补测试。这不构成模型效果差的证据，其缺失 usage 不填零。
- 重启后 5 个 credential-free 路由探测通过：Tavily/GitHub/arXiv/official 使用 local-proxy，community 使用 self-forward。Tavily 真实 POST/keypool 尚无可核验的通过记录；不能将路由探测写成完整检索健康通过。
- `ChromaKB` 原来忽略 `CHROMA_PATH`，现按既有配置读取，默认路径及 `tech_kb` collection 不变。Docker 同步传递知识库/learned-docs 设置；未改写现有知识库。
- 采集器新增即时 fsync 提交日志、固定 run 身份、取消后有界观测、逐 case `usage.csv`、随机种子/顺序、实际 running 观测峰值、开发/保留集分目录。评分绑定 run 和实验身份，无配对报告不判通过；预算未知扣账与已知 Trace 实耗分列。
- 候选案例修正 P06/P07 的未经核验前提和 P08 对唯一 evidence-insufficient gate 的错误期待。版本为 `0.1.1-candidate`；未假装已完成人工参考核验或冻结。

本地探测原件：`outputs/product-baseline-v1-20260916/`。不提交密钥、`.env`、原始端点或报告正文。

## 当前阻碍

主机于 15:30、15:48 重启，System BugCheck 都为 `0x124`；WHEA-Logger 18 报告处理器核心的 Machine Check Exception / Bus-Interconnect Error。2026-09-14 还有 Cache Hierarchy Error 记录。

该错误码表示系统报告致命硬件错误；不能据此确定具体部件或把根因归给项目代码。依据见[微软错误码说明](https://learn.microsoft.com/en-us/windows-hardware/drivers/debugger/bug-check-0x124---whea-uncorrectable-error)。未进行 BIOS、驱动、系统配置修改或压力测试。

不在反复蓝屏的主机上启动 12-case 并发付费研究。低并行离线测试仅在当前进程设置数值库线程数为 1，不是生产优化，也不能证明硬件已稳定。O1 不宣告完成。

## 恢复顺序

1. 主机稳定后继续，或由用户指定稳定的评测环境；不要复制 `.env` 到交付文档。
2. 完成人工参考依据核验及 12-case 版本/hash/日期冻结；制作相同初始知识资产快照，并为四个 profile 创建独立空产品/检查点数据库对。
3. 完成完整检索健康（含 Tavily POST）和隔离 durable 服务无研究启动验收，冻结依赖、非敏感配置、模型参数/资产身份。已有 LLM 探测可作准备证据；若配置/模型漂移，重新确认探测额度。
4. 冻结干净代码提交后运行 serial-r1 / concurrent-r1、concurrent-r2 / serial-r2；每个 profile 12 新任务，同 repetition 使用相同已保存种子/顺序。首个正式 run 同时验证真实采集，不另增授权次数。
5. 中断时先查 `admissions.jsonl`、已创建 task/run 和服务状态。日志中的 `submission_started` 不代表已确认创建；不得重复 POST 或自动 resume/retry。先核对可能已扣费的任务，作废/补跑另经确认。
6. 保存逐 case 已知 token、完整性、调用/重试、结果类型、预算结算/未知/预留；人工盲评及复核后才给并发门禁和首轮优化假设。保留集正文继续封存。

## 验证

2026-09-16，Python 3.12 项目虚拟环境：最终聚焦测试 42 passed；代码/测试冻结后完整套件 1092 passed、0 skipped（218.92 秒）。pyflakes、vulture（100% confidence）、pip check、Compose 静默配置检查、candidate 结构验证、git diff --check 通过；smoke-v1 12/12，fingerprint 匹配。

这是本机 Python 3.12 的离线验证，不冒充 Ubuntu/Python 3.11 CI 矩阵，也不证明真实报告质量、Tavily key 有效或硬件稳定。重启后创建的三个测试临时目录已清理，探测原件与用户运行数据保留。

重启前的 `outputs/o1-focused-test-20260916` 因 Windows ACL 拒绝读取/删除而残留，未扩大权限或修改系统 ACL；需后续在有权访问它的环境中清理。它不是研究结果，不提交 Git，也不影响上述已完成验证。
