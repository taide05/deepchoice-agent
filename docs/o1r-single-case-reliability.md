# O1-R：单 case 可靠性修复

日期：2026-09-16。用户已确认实施 O1-R，暂停所有真实 12-case 并发及整组串行。预算/实验恢复修复后已单次验证 P06 正常成功；随后补修实测发现的旧 KB 适配，当前重新离线验证，不声称单 case 已稳定。原 36 个 run 与作废证据保留，不重启原实验数据库。累计 37/48 个已创建 run，原额度剩余 11。

## 最小变更契约

- conflict_scan 输出上限 512，其他共享 helper 调用仍为 4096；派发、预算预留、manifest 共用一份定义，Prompt 不变。新 manifest identity 改变；历史 4096 扫描 manifest 可读但不可同 run 恢复。
- 每个 run 的扫描与初次仲裁阶段各最多 4 个在途调用，仍受全局 LLM_DS_CONCURRENCY 门限制。预算拒绝后停止新的准入，先等待已派发调用结算再抛出；不提高 60,000 token / 96 LLM / 72 retrieval / 900 秒标准硬上限。
- 实例获取在获得 SQLite 写锁之后计算时间，续期在共享锁内计算时间；不使用等待前的过时 TTL/谓词，不复活已过期租约。此修复覆盖确定性锁等待缺陷，不宣称已解释所有 live 失效。
- RunCoordinator 自动恢复默认开启，产品行为不变；实验 app.state.auto_recovery_enabled=False 完全跳过启动/周期 recover_runs，避免中断 run 自动入队。显式新任务与已确认 HITL 的同 run 恢复仍可执行；不绕过实例 lease、CAS、fencing 或预算 authority。
- collect-single 只能选择 P01～P08 的一个开发 case，并固定 concurrency=1；新目录、显式付费开关，metadata.case_denominator=1/execution_mode=single。它不是完整串并发基线，不能进入 12-case 配对门禁。
- 采集在准入前及轮询中检查实例健康；失联、失去实例权限、非预期 running→queued 或 interrupted 时停止后续准入，不恢复/重复 POST。正常 HITL 决策后的 queued→running 除外。
- 每 5 秒至多读取一次运行中公开用量，失败保留最后已知值/时间；只有最终终态成功刷新才可保留 Trace 完整标志。非最终/失联值是已知下界，完整性必须 false；runs/usage.csv/summary 用同一投影，queued/interrupted 不伪算终态。
- 仲裁 search_kb 复用 ChromaKB.retrieve/RetrievalRequest，统一 tech_kb、CHROMA_PATH 与 BGE query_embeddings；不再查询旧 knowledge_base 或调用默认 query_texts embedding。沿用工具外层一次预算/Trace，失败返回固定安全标签并保持 failed/knowledge_base_unavailable，BudgetError 上抛；成功仅返回 300 字符 content 及 url/title/date metadata。不迁移/改写原知识库。

## 验证和复测顺序

1. 离线 fake LLM、真实产品 SQLite：15 对扫描保持四路在途并最终结算；LLM 上限为 2 时只派发 2 个，latch 后其余请求不外呼，结算后拒绝才上抛。另覆盖扫描/仲裁峰值、旧 manifest、实例锁等待、实验不变状态/事件、显式 HITL、健康/重入队失效和失联前 True 用量降级。
2. 独立复审、聚焦及全套 CI-equivalent、文档同步、Git 提交完成后，才执行一次单 case 验证。先选此前失败的 P06；检查结果、实例健康、预算及用量之后再决定下一次，不预排队多个任务。
3. 每次新 run 计入原剩余 12 个额度，不补跑旧任务。达到三个代表性开发案例各两次独立成功的建议门槛须逐次决策：正常完成、报告/快照可读、最终 Trace 用量完整、无预算/租约故障或非预期恢复。不靠强制受限报告、放宽预算/禁用安全门通过；达到门槛也不自动恢复批次。

## 当前残余风险

- run 级 heartbeat 的时间仍在仓库锁前冻结；SQLite busy 等待、事件循环延迟及高负载仍可能消耗 TTL。未完整复现并发 live 实例失效机制，不宣称租约问题全部解决。
- 512 是短 JSON 的有界配置，不是语义质量/无截断保证；单次 live 必须检查结构是否完整，截断或 fallback 不算稳定成功。大输入或长期调用仍可能正常触发硬预算。
- 默认产品仍需自动恢复/七日 decision 过期扫描；仅实验关闭该扫描，需有界采集和受控停机，不作为长期部署配置。
- 主机 WHEA 历史风险仍在。此轮不做 BIOS/驱动改动、硬件压力测试或网络/provider 改造。

## 离线验证记录

聚焦 85 passed；API 替身更新后追加 7 passed。首轮全套为 1111 passed / 2 failed，失败均为旧 API 测试替身未接收 auto_recovery 参数；已补签名及默认 True 断言，生产代码未再改动。最终全套 **1113 passed、0 skipped（207.22 秒）**，2026-09-16。

pyflakes、vulture（100% confidence）、pip check、Compose 静默配置、git diff --check 通过；smoke-v1 12/12，fingerprint 匹配。本机 Python 3.12，不冒充 Linux/Python 3.11 CI 矩阵。独立只读复审无阻断项；非最终用量完整性问题已修复并覆盖测试。

旧 KB 补修冻结后：聚焦 **44 passed**；全套 **1116 passed、0 skipped（223.14 秒）**。pyflakes、vulture 100%、pip check、smoke-v1 12/12 fingerprint、git diff --check 再次通过；独立只读复审无阻断项。原 ChromaKB 默认/显式路径、tech_kb、1024 维 query_embeddings、失败分类/错误不反射及 BudgetError 上抛均有回归覆盖。

单次实测将按实际收集后追加；真实报告语义质量仍需人工盲评/复核，不用未校准 judge。依据 ai-evals，运行稳定性与语义质量分别验收。

## 首次单 case 观察（不是稳定验收）

2026-09-16，执行提交 2af0781，新隔离根目录 outputs/o1r-single-20260916；准备脚本虽创建四个空 profile，实际仅启动一个服务、提交 P06 一个任务，collection execution_mode=single / denominator=1 / concurrency=1。检索健康通过，知识 hash 与原冻结身份一致，原知识库 hash 未变。

P06-r1：completed，约 82.7 秒；输入 21,253 / 输出 3,602 / 总计 **24,855 token**，31 LLM / 13 retrieval，最终 Trace 用量完整，预算 reserved/unknown_spend 均 0，无 admission denial、LLM retry、HITL 决策或非预期恢复。报告 8,976 字符、快照可读。价格 unavailable，不推算金额；不是平均成本、语义质量或硬件稳定证明。

13 次 conflict_scan 的 helper 诊断均 parse_ok=True，输出最多 39 token；29 条共享 helper 脱敏诊断无 parse_ok=False 或 error_type，另两次工具式 LLM 用量由 Trace 记录。这是 helper 解析器观测，不声称严格原文 schema/语义验证。服务受控关闭，未重复 POST 或恢复旧 run。

一条 evidence_gather.tool/search_kb failed 暴露旧 collection/embedding 适配，与预算修复无关；先补修/重跑验证再进行下一次单例。本次成功发生在 KB 补修之前，不作为最新候选的重复稳定门槛证明。保留集正文未查看，O1 串并发质量基线继续暂停。
