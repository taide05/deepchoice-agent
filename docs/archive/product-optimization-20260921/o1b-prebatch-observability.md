> 归档快照：2026-09-21。本文只保留当时事实与决策；其中“当前”“下一步”“待批准”均不是现行指令。
> 当前入口：[任务地图](../../current-roadmap.md)、[文档索引](../../README.md)。原文来源：40f9266 工作树。

# O1-B：批次前观测与离线可靠性补修

日期：2026-09-17。用户批准 O1-B，并明确批准一并最小修复租约等待取时、冷加载调度和
过期 health 准入。本轮只有离线实现与验证；没有真实检索、模型调用、研究提交或保留集报告/评分读取。
43/48 与剩余 5 不变。O1 仍 incomplete，不授权 O1-C、批次恢复或 O2。

## 观测口径

LLM 主入口及补证直连调用记录安全的 finish_reason / truncated；缺失或未知原因保留 null。
JSON 输出独立检查严格解析（拒绝重复 key、非有限数字和外围 Markdown），不以修复后的对象
冒充严格 JSON。保留原 json_repair 兼容解析和返回值，不增加重试/调用，不改 Prompt。

- json_status：strict / repaired / invalid / non_object / not_requested；历史缺失为 null。
- repair_attempts：实际进入兼容修复 parser 的次数，不是实际改写次数，也不是 LLM 重试数。
  严格 JSON 通常也调用一次；Markdown fallback 可调用两次，输入预处理失败可能零次。
  实际需修复的观察用 repaired，不能直接用 repair_attempts > 0 推断。
- node-shape-v1：只检查冻结 Prompt 的必要字段、容器、元素类型及枚举，不执行新的路由门。
  覆盖分析、适配、扫描、仲裁/再仲裁、综合、自审与探测/三项搜索工具。
  澄清同一 tag 有多种结构，记录 not_configured；不推断结构通过。
  这是浅层结构观察，不是完整业务 schema、语义正确性或引用证明。
- 调用状态与输出问题分开：接口成功但截断/解析/结构异常仍可为 succeeded，同时有
  output_truncated / json_parse_error / json_schema_error；旧 failed_calls 仍是传输/执行状态统计。
  工具发生供应商失败时该类别优先，参数结构问题仍在 diagnostics 中，不从记录消失。

失败类别分开保留预算触顶、预算持久化门失败、429/准入失败、provider_timeout、transport_error、
检索契约、已知 lease_lost、runtime_recovery、run_timeout、cancelled 及 unknown。
run 类别从最新 run 的已知稳定编码/状态读取，不公开编码或原始异常；interrupted 只表达恢复边界，
不证明其根因。租约失效而 fenced 收尾被拒绝时不能伪造终态，靠 heartbeat 失败计数辅助诊断。

公开 API 只投影通过类型/枚举校验的诊断字段，不公开 prompt、回复、工具参数、内部 ID、
lease owner、epoch、checkpoint 或原始错误。Trace 仍 best-effort；预算结算与 token 用量不改。
历史 Trace/结果不回填，未知不当作零。

采集器新增 diagnostics.csv（逐调用）和 diagnostics-summary.json（逐 case 分母、已知调用、
严格 JSON 比例、结构检查、修复 parser 次数和失败类别），保存最近健康观测；非最终/缺失字段
不判资格通过。probe 顶层 passed 需要严格 JSON、结构、已知未截断及既有功能探测均通过，
output_qualification 区分 passed / failed / unavailable；旧探测不能自动获此资格。

## 已修复与离线故障

| 边界 | 修改 / 回归 |
|---|---|
| run 获取/续期 | 默认生产路径传可注入 clock，取得共享锁及 BEGIN IMMEDIATE 写锁后取时；保留 explicit now 测试/旧调用适配。共享锁与另一 SQLite writer 等待后，新 TTL 从取得锁开始，已过期续期零变更/零事件 |
| 实例续期 | 显式写事务后取时，双时钟本地有效窗口，失败撤权；writer 等待成功/过期拒绝及回滚回归 |
| 停服取消 | release 按 owner 清理，不依赖已被取消改变的本地标志；续期中取消后立即冷重启，并确认旧 owner 不删除替代 owner |
| 冷本地工作 | 默认/补证 Chroma 构造、模型获取/encode、collection query 放入线程；模型初始化加单次加载锁。假构造、假模型、假查询阻塞时实例心跳仍成功；冲突扫描冷模型同样离开事件循环 |
| 过期-before-callback | health 与 durable 写准入直接检查本地已接受的 lease 窗口，到期即 503/拒绝；不能因时钟回退复活本地权力 |

health 新增 runtime_observations：有效权力、最近成功年龄/剩余 lease、续期耗时、最大心跳间隔与
续期计数。run_heartbeat 为进程级成功/失败/已知失租计数、最大调度延迟/成功续期耗时、活动 run
最老成功年龄；没有观测时 null，正常进程重启会重置，不是跨进程恢复次数或逐 run 根因日志。
时间覆盖等待总耗时，不声称拆出了共享锁与 SQLite busy 各自贡献。
实例首次 acquire 也作为最近成功；活动 run 首次 heartbeat 前没有成功年龄。

实验 serve 仍预热 embedding，启动输出标记 prewarmed 与 embedding_warmup_ms。
进程重启不等于模型在研究中冷加载，不能把该启动方案的旧六例描述成真实冷模型验收。

## 验收与停止线

最终聚焦 187 passed / 0 skipped（72.89 秒），Python 3.12.4；
pyflakes（src/tests 与本轮 benchmark 文件）、vulture src min-confidence=100、
pip check 和 git diff --check 通过。最终全套 1238 passed / 0 skipped（211.83 秒），
smoke-v1 固定 fixture 12/12、baseline_matches=true，fingerprint
0e4dd8d574ea8554881eb7f39039e0a1131320f547b22e7cae382e83825ef919。
smoke 不测真实模型/来源，source-health not_run；B 离线验收完成，真实资格未验收。测试入口：
tests/test_o1b_observations.py，以及 LLM/检索/观测 API/实例 guard/coordinator/repository/Phase1-F
现有回归。本轮不执行任何健康或付费 probe CLI。

诊断 CSV/摘要是同一实验目录的补件，须与 experiment.json / runs.jsonl 一起保留和绑定，
不能当作脱离冻结身份的独立质量评估。本轮只是合成测试生成它们，不创建新正式评测产物。

独立只读助手复审（非质量评分）无剩余阻断项；曾发现取消中续期漏清理，以及 JSON 指数
溢出产生非有限值，两项均已修正并补回归。复审者确认代码/文档与 diff 检查，未执行测试套件；
只用合成 strict_json 输入确认过溢出缺口，未联网或读取实验/保留集报告。

以下仍为 unknown / not_run：真实冷启耗时与模型内存峰值、主机蓝屏/WHEA 根因、供应商实时
额度/限流、同一冻结新候选的逐次单 case 稳定性、语义质量、缓存命中成本及 12-case 并发差距。
线程工作不能被协程取消强制终止；局部计算可能继续，但不得由旧权力提交产品状态。
health 拒绝新准入不是瞬间取消全部在途请求；停止既有 runner 仍有 heartbeat/回调窗口，
已派发外部请求不可撤回。旧调用显式固定 now 是历史兼容，不代表默认生产路径取时。

下一步仍是 O1-C：另行确认主机/API/费用和一例计划，明确模型预热/冷加载条件，先一次提交，
失败或降级停止，不自动重复或排队。离线 B 完成不等于单 case 或批次资格通过。
