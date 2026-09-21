> 归档快照：2026-09-21。本文只保留当时事实与决策；其中“当前”“下一步”“待批准”均不是现行指令。
> 当前入口：[任务地图](../../current-roadmap.md)、[文档索引](../../README.md)。原文来源：40f9266 工作树。

# O1 后续任务：收敛规划

更新：2026-09-21。用户本轮要求整理现状并重新规划；本轮交付是事实盘点与规划文档，
没有授权或启动新的产品改动、实验规则变更、付费研究或发布。

**建议主线：现有证据诊断 → 一个有依据的产品改进 → 小样本配对验证与本轮结项。**
把完整 48-run 的 12 路并发认证列为后置专项。采用此路线需要明确接受下面列出的验收范围
调整；接受之前，v4 仍是正式 48-run 的判定依据，旧 O1-PR2B / O1-PR3 不标完成。

## 1. 已核实的当前事实

- 冻结产品候选为 `d23c948`，2026-09-21 的 P01 × 1 已完成重新资格、完整台账及独立复核；
  这是助手暂定测量资格，未做人类校准。
- 控制器修复身份为 `7d16d28`；最新代码/测试验证为 93 项 PR2 聚焦、1579 项全量通过
  （2026-09-21，181.94 秒）。随后只有维护文档变更，没有新的产品版本。
- 当前持续授权账本为 **90/134，剩余 44 个研究 run**。这不是项目全部历史运行的总分母，
  也不是已完成质量评分的报告数。前置探测与研究 run 分账，价格未知不记零。
- 最近一轮 fresh serial-r1 准入 4 个：2 普通报告、1 受限报告、1 cancelled；
  官方安全抓取 GET HTTP 521 正确触发既定 5xx 停止规则，4/4 收尾、服务正常退出。
- 现有最新候选没有完整的 12 组成对报告评审，没有 round-1/round-2 gate 或 review lock。
  第一轮正式门禁、第二轮、旧 O1-PR3 和并发资格均未完成。
- 不复用停止根、不跨候选拼接；本轮只读核对控制/采集元数据，未读取保留集报告正文。

## 2. 已完成与未完成

| 工作 | 当前状态 | 已有证据 / 还缺什么 |
|---|---|---|
| Phase 0–6-A 内已批准的工程基础 | 已完成并进入维护 | durable 生命周期、预算/Trace、引用验证、检索缓存、HITL、安全、smoke 与工程验收 |
| 模型统一及基线入口 | 已完成 | DeepSeek Flash、durable collector、冻结案例/manifest/知识身份，历史直连入口隔离 |
| O1-A 评估口径 | 已完成 | 12-case、逐处原子声明、0/1/2 rubric、旧六份开发报告台账及复核；不等于当前候选质量 |
| O1-B / C1 / C2 离线补修 | 已完成既定实现 | 输出诊断、缓存拆账、候选/引用清理、安全代理等；各项实测盲区仍保留 |
| O1-PR1 当前候选资格与冻结 | 已完成，资格有效 | `d23c948` P01 × 1，单例资格不能推断全案例质量或并发稳定 |
| O1-PR2A 及后续控制修复 | 已完成已发现缺陷的离线修复 | 探测/HITL/安全失败误报、冷初始化清理、timeout 双事件关联；不能声称控制器覆盖所有未来异常 |
| 租约隔离、API 查询隔离、GitHub 响应中断重试 | 已实现并验证 | 生产修复及新候选资格已留证；没有两轮 12 路并发完整实测验收 |
| 当前候选报告质量评审 | 部分完成 | P01 资格已审；正式串行/并发报告尚无完整锁定评审集 |
| 正式 48-run 配对与两轮门禁 | 未完成 | 多次停止，不能用已花费 run 数抵扣配对分母 |
| O1 总体结项 / O2 改善证明 / 人类校准 | 未完成 | 尚未形成完整质量与成本结论、唯一优先假设及前后效果证据 |

## 3. 可复用材料及边界

下表均为 2026-09-21、product-baseline-v1/1.0.0、候选 `d23c948`。数字来自原根的
profile-control、lifecycle 和 runs 元数据，不是新质量评分。

| 材料 | 实际分母 | 本轮规划允许的用途 |
|---|---|---|
| P01 资格根 github-retry-v3 | 1 成功报告，严格 43 原子已复核 | 资格与既有缺陷线索；不代表 12-case 质量 |
| github-retry 配对根 serial-r1 | 12/12 报告：11 普通 + 1 受限；8 development + 4 holdout | 选择其中完整 8 份开发报告作为主要诊断材料 |
| 同根 concurrent-r1 | 12 准入、11 报告：9 普通 + 2 受限，另 1 cancelled；7 development + 4 holdout 报告 | 运行诊断；必要时核对开发报告，不补齐为正式配对 |
| cap134 根 serial-r1 | 4 准入、3 开发报告、1 cancelled | 521 停线、清理和用量证据；独立保留分母，不汇入主诊断评分 |
| 更早候选/旧六份开发报告 | 各自冻结日期、版本和分母 | 解释历史缺陷与已有修复；不得充当当前候选基线 |

本地根分别为 `outputs/o1-pr2b-qualification-p01-20260921-d23c948-github-retry-v3/`、
`outputs/o1-pr2b-pair-20260921-f6d6089-d23c948-github-retry/`、
`outputs/o1-pr2b-pair-20260921-7d16d28-cap134/`。原始报告、快照和 Trace 留本地。
保留集不用于选问题或调参；其独立盲评后置，不把“没有读取”写成“已通过”。

## 4. 为什么调整顺序

1. 单任务内容质量、批量执行稳定性和 12 路并发非退化被绑定到一个 48-run 完成条件。
   外部来源或实验控制的局部问题因此不断推迟内容诊断。
2. 生产修复确实需要新身份/资格；控制器误报与真实来源 5xx 却也多次导致整组重新起跑。
   已有工程修复值得保留，但继续单纯增加总上限没有解决这一执行成本问题。
3. 已有完整串行报告没有转化为锁定的当前候选质量诊断，继续采集的边际价值不足。
4. 主路线/README 曾滞留 60/109 和“待资格”，而执行记录已到 90/134，多个“当前状态”
   造成了决策混乱。本轮统一当前入口，旧时间线只作历史。
5. 最新 521 是当前规则正确停止，不能称为程序误报。是否把单条引用不可用从全批停线中
   分离，是需要事前定义的实验协议选择，不能为让既有结果通过而事后改判。

## 5. 建议的三个后续 PR

PR 编号使用 `O1-RP1/2/3`，避免与旧 O1-PR1/2A/2B/3 混淆。
它们是重规划提案，不继承为新生产优化或新付费实验的实施授权。

| PR | 具体交付 | 新研究 run | 结束条件 |
|---|---|---:|---|
| O1-RP1 现有证据诊断与验证规则收敛 | 核验上述 8 份串行开发报告的完整关键声明、rubric、调用/成本；复核重大错误和争议；冻结一个问题、3 个验证案例及新实验协议 | 0 | 一份可复算诊断、一个优先假设或“暂无足够依据优化”的结论，以及明确的验证范围/停止矩阵 |
| O1-RP2 单点产品改进 | 只修改 RP1 选出的一个原因；补相关自动化测试、必要独立复审及全套验收，提交并冻结候选 | 0 | 可回滚提交、离线验收通过；不加入第二优化目标或大规模重构 |
| O1-RP3 小样本配对验证与本轮结项 | 必要的新候选 P01 资格一次；新旧候选的 3 开发案例 × 2 重复 × 2 候选，全部 serial=1；盲评/复核后给结论 | 最多 13 | 明确“局部改善得到支持 / 未证实 / 实验不可评”，汇总质量、成本和残余风险，不追加循环 |

RP1 先完成内容评分再用 Trace 归因，避免按耗时/成本偏好给质量评分。只使用保存的证据，
缺失保持 unknown；不把逐个当前网页重新核实变成新的无界研究任务。已有单例支持度/来源质量
问题是候选线索，不能在 8 份诊断前直接选定为产品根因。

RP1 的控制面范围仅限为新协议必需的停止分类和终态读取：
建立一张穷尽已知状态的离线矩阵，覆盖 provider 失败、引用不可用、429/Retry-After、
typed timeout、取消、服务/租约/预算/身份失败、官方 HEAD/GET 和公共 GET。
必要最小控制修复在该 PR 离线完成，沿用现有入口，不重建评测平台、不先启动 paid 探路批次。

建议的新协议区分单条引用不可用与运行完整性受损：可明确归属 citation 验证的普通
HTTP 5xx/可达性不确定可作为该报告 unknown/warning 留存，不因此作全批重开；前置健康失败、
检索来源失败/降级、429 与 Retry-After、安全/预算/租约/身份/主机异常和无法归类的异常仍停线。
这项变化必须先写清归属证据与自动化测试并被接受；在此之前仍执行旧 5xx 停止规则。
安全 fetch 的地址、DNS/IP、代理、重定向、大小/时间和 HTTP 方法约束不变，不新增外呼重试。

RP2 只有在 RP1 能指出可修复且影响决策/可信度的主要问题时才实施；若证据不足，
可直接交付诊断结论，不为了“必须有优化提交”继续找功能做。
修复生产代码/Prompt 后按已有规则重新资格；控制器或文档变更不自动使产品资格失效。

## 6. 小样本验证的精确边界（提案）

- RP1 在改代码前，从 P01–P08 选 2 个体现目标问题的开发案例和 1 个回归案例，说明选择理由；
  不查看 P09–P12 来挑选优化方向。案例请求、rubric、预算、HITL 不改。
- 同一不超过 7 天的测量窗口新跑 baseline 和 candidate：3 case × 2 repetition × 2 version = **12 run**；
  若生产版本变化，再留 **1 次 P01 资格**，总量最多 **13**。旧停止根只用于诊断，
  不作为新旧数值改善比较的一半。知识/依赖/模型/配置相同，仅允许声明过的优化变量不同。
- 运行顺序在准入前冻结，交替候选顺序抵消部分时间漂移；每个 profile 使用独立空数据库对
  和相同知识种子。记录 manifest 的预期差异，不要求变化后的 Prompt 身份伪装成相同。
- 沿用逐处声明口径和 0/1/2 rubric；隐藏候选标签、随机评审顺序，锁分后关联成本/Trace。
  改善声明、重大错误及争议需独立依据；助手评审和人类校准 not_run 分开标注。
- RP1 预先冻结一个主指标。内容主指标须在两个目标 case 的两次重复中均相对 baseline 改善，回归案例
  两次不新增重大错误且决策、引用和完成率不下降；不以平均分抵消新错误。
  若选择效率，沿用按 case 两次均值计算再取配对节省比例中位数至少 15%，且质量不下降。
- 此矩阵只能支持 **3 个已选开发案例上的暂定局部结论**。不能声称其余开发例/保留集已无回归、
  全产品质量通过、原 v4 完成或 12 路并发通过。选择性开发案例不能提供总体泛化保证。
- 一次资格加一次固定矩阵后结束本轮。失败/取消计入分母，缺配对则 unavailable，
  不反复抽样直到通过，不追加第二个优化循环。价格不明与 usage 不完整继续显式保留。
- 若采用本提案且无其他新增运行，累计最多 **90 + 13 = 103/134**；剩余 31 只是额度余额，
  不是自动重跑许可。前置费用单列，仍沿用一次有界健康/LLM 检查，而非免费或无限探测。
  本轮规划本身新增研究 run、健康/LLM 外呼均为 0。

## 7. 后置事项与结论范围

| 项目 | 重规划建议 | 必须保留的事实 |
|---|---|---|
| 原 O1-PR2B 的 48-run / 两轮 12 路并发门禁 | 从当前产品改进主线移出，作为需要明确容量目标时再启动的专项 | 未完成；v4 阈值和旧失败证据不被改写 |
| 原 O1-PR3 | 将当前部分改为“诊断与局部改进阶段总结”，并由 RP3 交付 | 这是缩小结项范围，不能把旧完整 O1 追溯标成通过 |
| 保留集盲评、人类校准 | 全产品验收前再做，不作为当前诊断收口的前置 | 尚未完成，当前仅助手暂定结论 |
| 第二个 O2 优化、展示/面试材料、企业扩展 | 不列入这次三个 PR | 没有自动实施或发布授权 |
| 历史失败根、全部已准入成本与未知项 | 原样保留，只读引用 | 不删除失败、不补写旧 run、不以新规则回填旧成功 |

## 8. 文档与交接约定

- [current-roadmap.md](../../current-roadmap.md)：当前总体范围、已完成工程能力和规划状态。
- 本文件：唯一的后续任务拆分入口；当前建议下一步仅实施 RP1 的离线诊断与规则收敛。
- [o1-execution-status.md](../../o1-execution-status.md)：研究准入账本、最新终态与证据哈希。
- [product-effectiveness-optimization.md](../../product-effectiveness-optimization.md)：原 v4 的冻结判定规则；
  RP1 若被授权，新增独立的小样本协议身份，不覆写 v4 历史结果。
- [o1c-single-case-verification.md](../../o1c-single-case-verification.md)：候选资格，不再承担最新额度入口。

本次已完成盘点和文档整理；RP1/2/3 仍为建议。用户接受“并发认证后置、有限样本结项及新停止分类”
后，才据此实施和使用对应额度。无需为阶段内常规只读核对、测试或文档更新重复申请业务批准。

<details>
<summary>旧 PR 划分与执行时间线（历史记录，不作为当前任务入口）</summary>

# O1 剩余交付与 PR 划分

2026-09-21 当前授权与结果：用户已把总硬上限从 110 提高到 **134**，从累计 86 个 run
启动 fresh 48-run 配对。候选仍为 `d23c948`，控制器为 `7d16d28`。新根首个 serial-r1
准入 4 个 run 后因官方来源安全抓取 GET **HTTP 521** 命中既定 5xx 停止线：2 份普通报告、
1 份受限报告、1 个取消，全部 settled，服务正常退出。当前 **90/134**，剩余 44；
concurrent-r1、concurrent-r2、serial-r2 未启动，第一轮质量门禁与本地 O1-PR3 unavailable。
离线遥测前缀重放确认 521 前通过、包含 521 后停止，本次不属于超时双事件误判。
正常授权范围仍为两轮各 12 serial + 12 concurrent、逐轮评审/门禁及本地 O1-PR3；
供应商、外传范围、冻结案例、rubric、每 run 预算、HITL 和质量阈值保持既定契约。
停止根不得复用或拼接；若另行批准完整替代 48 run，最低累计上限为 138。下文较低计数为历史。

更新：2026-09-21。2026-09-18 原始重组将剩余 C/D/E 工作组织为 **3 个 PR**，A/B 保留已完成状态；
该次规划不改变 [评估协议 v4](../../product-effectiveness-optimization.md)的冻结案例、rubric、质量/并发阈值、
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

当前状态：**GitHub 响应中断修复候选 `d23c948` 已重新资格并冻结，但其 formal fresh
第一轮因 safe-fetch timeout 遥测误判停止，O1-PR2B 仍未完成。** 查询隔离候选 `09f9b66` 的
历史 serial-r1 完成 12/12，形成 12 份报告（1 份 limited），合计
147,687 tokens、186 LLM / 72 retrieval、0 failed calls；stop-final、清理与服务退出完整。
concurrent-r1 准入 12/12 后，GitHub GET 出现 `RemoteProtocolError`，控制器按
`PR2_EXTERNAL_HTTP_STOP` 取消并清理 12 个任务，0 报告且服务正常退出。该 fresh 根必须
保持不变，不重启、不补跑、不与后续根拼接。

生产候选 `d23c9480b9f368f8ec75ec44ee7e25c64146d4be` 仅对 GitHub 幂等 GET 的
`RemoteProtocolError` / `ReadError` 最多重试 2 次，每次重新进入共享 provider gate；PR2B 遥测按 run 关联物理重试，成功响应才清零。第三次中断、
其他 source/method/异常、非允许状态与 safe-fetch 异常继续 fail closed。并发故障注入、
134 项聚焦和 1570 项全套测试通过。生产代码已再次变化，因此 `09f9b66` 的资格转为历史。新候选的首次资格 runner 在准入后因
瞬时 health-stop 退出，fresh v3 P01 随后完成；独立复核把严格分母从 44 校正为 43，最终
support 19/15/9、quality 0/34/9、must-answer 5/6、conflict 2/2、major/blocker 0。
其后的 `d23c948` fresh serial-r1 完成 12/12；concurrent-r1 准入 12/12 并形成 11 份报告，
P03 因控制器把底层取消误判为异常而 cancelled。产品在 0.505 ms 后已把同一事件归类为允许的
`UnsafeUrlError(timeout)` 并完成 citation validator，因此这是控制器误停。停止根计入 24 个 run，
当前使用 **86/110**。相关修复只接受同 run、known failure、250 ms 内配对，并在 2.5 秒后或最终化时对
未配对取消 fail closed；93 项 PR2 聚焦和 1579 项全套通过。完整 fresh 48-run 替代需要上限
134，尚未启动。供应商、数据外传、案例、rubric、每 run 预算、HITL、质量阈值和停止线不变。

以下为 2026-09-18 的 PR1 历史断点，只用于解释资格形成过程，不代表当前状态：
PR1 入口通过 59 聚焦 / 1439 全套及独立复审，候选实施提交为 `ce4addf`。
2026-09-18 03:45 UTC 本轮唯一前置仍为 4/5，arxiv local-proxy 投影 rate_limited 后停止；
HTTP 保守计数 6、付费 Tavily/LLM/新研究均 0。继续实施后完整新前置 5/5、JSON/tool 通过，
但在提交 P01 前内存启动线拒绝；正在形成延迟导入修正的新候选，原额度 **44/48** 不变。
P01 未提交、单例资格 unavailable、PR1 未完成且未形成 PR2 锁定候选；不自动使用剩余额度。
不与此前 arxiv 单探测 200 拼全绿，限流细因未确定；证据见
[单例验真](../../o1c-single-case-verification.md)与 [阻断诊断](../../o1c-blocker-diagnosis.md)。

| 剩余 PR | 对应旧任务 | 交付目标 | 完成证据与依赖 |
|---|---|---|---|
| O1-PR1 当前候选单例资格与冻结 | C3，含必要的 C 问题收口 | 生产改动后用一次新候选 P01 核对执行、引用/报告与成本并冻结 | 候选 `d23c948` 已通过离线验收和校正后的 P01/台账/独立复核，当前 62/110 |
| O1-PR2A 控制面离线修复 | D 的执行前置 | 修复静态探测误报、停止态预算证据和冷初始化关闭阻断；不执行真实研究 | exact operation 单元测试、公开 API stop-final 证据测试、冷初始化收束/正常退出测试及全套验证；已完成 |
| O1-PR2B 正式串并发基线与逐轮评审 | D，含 E 的逐报告评审 | 用新的 fresh 根、同一冻结产品候选完成 12-case × serial/concurrent × 2 重复，共 48 个新 run；采集和质量核验一起交付 | `d23c948` 资格有效；新停止根为 serial 12 报告、concurrent 11 报告，控制器已离线修复；当前 86/110，完整替代需 134，门禁仍待测 |
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

依赖依据：[评估协议 v4](../../product-effectiveness-optimization.md)、[O1-A 记录](../../o1a-evaluation-closure.md)、
[单例观察](../../o1r-single-case-reliability.md)、[六源限流离线审计](../../o1-retrieval-throttle-audit.md)、
[O1-B 观测与补修](../../o1b-prebatch-observability.md)。

</details>
