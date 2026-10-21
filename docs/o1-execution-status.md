# 当前质量状态

更新：2026-10-21。最终目标已明确为代表性数据集上的可信项目指标及完整使用链路；
一份合格报告只作阶段门槛。第七次失败后的离线修复与评测准备已完成；随后按新授权执行了
第八次真实单例（1 case、1 run，14/40 LLM、7/24 Tavily、研究墙钟 217.6 s），内容未通过。
之后完成三轮第八次后**离线**修复批次：首轮代码 `53a09ed`、测试 `06017e6`（修复前既有回归
测试曾触发少量真实 official GET，见下）；第二轮代码 `63cc2ca`、测试 `758e7ee`、文档
`0e3397e`；第四项收口代码 `e9acb9c`、测试 `58d7fb0`、文档 `a5cca17`（真实外呼 0，
610 passed）。第九次真实单例后账本修正见下文；本次外部调用仅限既有授权，未执行基线/基准批次，
未调用外部模型裁判。目标见[路线](current-roadmap.md)，指标与冻结要求见[评估协议](product-effectiveness-optimization.md)。

## 当前工作树与证据范围（2026-10-19核对）

| 工作树 / 分支 | 本轮核对基点 | 适用边界 |
|---|---|---|
| `D:\deepchoice-agent` / `codex/generic-selection` | 文档基点 `4ff0eb3`；本轮协议同步提交 `c8cf0bc`；最终文档头以 Git 历史为准 | 维护路线/协议及现代 durable 产品；既有 `learned_docs.json` 未提交修改保留 |
| `D:\deepchoice-precodex` / `precodex/deepseek-adapter` | 修复前 `2aa92ef`；第一批 `f07f87b`；第八次后首轮 `53a09ed`/`06017e6`；第二轮代码 `63cc2ca`、测试 `758e7ee`、文档 `0e3397e`；第四项收口代码 `e9acb9c`、测试 `58d7fb0`、文档 `a5cca17`；第1轮代码 `33eb704`/`8ff13db`、测试 `e4152ab`/`ad13b95`、文档 `b42c2c6`/`5626c7b`；第八次 task `e339d065-7a61-4993-9819-1405b23bb7cd` 已运行并保留 | 当前恢复实验，仍走旧 `/research` 接口；代码 tracked 仅 `learned_docs.json`（第九次 gVisor 学习，保留未提交），17项既有未跟踪材料保留 |

以上是身份记录；两工作树共享项目目标，不共享运行契约、工程套件分母或质量结论。
恢复实验的离线修复未据此声明已集成到现代产品。


## 恢复实验的工程与内容状态

- v10 冻结代码 `0e6305a` 的交付记录记载完整套件 **525 passed / 0 failed**，原两项前端失败
  已修复。依据实验工作树的 `.scratch/v10_delivery_record.md`；本次核对记录，未重跑工程套件。
  该结果不能替换下方现代分支历史的 3853 项结果，也不证明内容合格。
- 第六次研究的原报告内容未通过；v8–v10 的离线机制回放不回写原报告或原验收结论。
- 第七次于 **2026-10-18** 在 `0e6305a` 完成一次研究，task
  `49cf0eee-ad7d-48c3-aa39-1b51731fb1c5`。研究 **165.8 s / 900 s**，
  实际 LLM **12/40**、Tavily POST **11/24**；已知 token **45,563**，12次请求中2次
  无 token 记录，完整 token 总量及费用为 `unknown`。运行记录确认研究终态完成及服务退出。
- 第七次运行身份、预算和主要产物一致性通过，含方括号来源标题的注释角标定界仍有缺陷；
  不能判整体产物检查全部通过。**内容未通过**：关键必答项与版本条件缺失、推荐反转条件
  不具体、无依据断言及集成文档适用范围扩大。原始报告保留，不补跑或手修。
  原验收记录对该标题的 Markdown 语法另有归因；此处不把“嵌套方括号链接必然无效”作为
  已证实结论，注释锚点缺失与正文标记定界须按实际渲染器分别诊断。
- 本地依据为实验工作树的 `.scratch/run_record_v7_acceptance.md`、冻结记录和对应
  `outputs/49cf0eee-ad7d-48c3-aa39-1b51731fb1c5/` 原始产物；原件留在忽略区。
  原始模型输出未保留，不能从后处理结果推断模型最初选择或删除了哪些标记。

## 2026-10-19 离线修复与评测准备（本轮）

- 第一批候选 **`f07f87b`**（2026-10-19，22 个文件：19 修改 + 3 个新测试模块）修复
  已保存材料可观察的问题：GitHub 仓库元数据被当成可引正文（保存快照可见 99 字符元数据
  源）；冲突记录 `claim_a/claim_b` 是文章标题（保存快照观察）；StackExchange score/tags 同型问题在该次
  材料中未返回结果，按同代码类审计修复；综合/自审输入缺冻结约束、
  来源日期和推荐改变条件；方括号标题的引用角标漏匹配（保存报告/annotated 材料观察；实际
  Markdown 标签括号平衡，问题是注释扫描器）、字段 Sources 固定截断 3 条、多行 query 标题
  及悬空标点；`report_quality.py` 的 A/B/C/D 活动输出被表述为报告质量/生产就绪。
  **Tavily 多查询的因果边界**：保存材料只有 6 个 adapted query 和最终 7 条合并结果，
  未保存 per-query 原始响应，因此不能声称“第 4–6 个查询被截断”是已证明的历史事实；
  本轮轮转合并的覆盖/合并机制差异由离线回放证明（模拟每查询 3 条、cap 7：旧并集覆盖
  查询 0–2，新覆盖 0–5），不证明报告质量收益。
- 收尾候选 **`6b96a56`**：冲突正文摘录使用统一 Markdown 转义
  （HTML、自动链接、格式控制符均按文字展示；来源链接和存储正文保留），用三种 renderer 的
  实际 Markdown 渲染 + annotated 结果验证；Tavily 轮转合并恢复“空/缺失 URL 不占结果位”
  的旧边界；评估协议新增决定性断言采集范围、case/run/请求/重复测量/墙钟计数、共享证据
  基线的输入截取点和成本归属定义；状态和测试注释区分保存材料观察与模拟机制证明。
- 验证：第一批代码/测试冻结后完整套件 **554 passed / 0 failed**；收尾后完整套件
  **557 passed / 0 failed**（实验工作树，Python 3.12.4，显式 PYTHONPATH）。第一批独立
  只读复核无阻断，其非阻断项（未闭合 `[` 提前终止、裸 excerpt 标签、无正文计数未进入
  报告/综合、StackExchange 同类元数据）已在第一批提交前修复并加回归。收尾复核发现两项
  阻断：annotated/PDF 二次 Markdown 解析会重新解释未转义标题，以及共享证据截取点与管线
  顺序矛盾；两项均已修复（`_plain_label` 只还原 HTML 层并保留 Markdown 转义；截取点改为
  检索+来源评分之后、冲突/证据链/综合之前），第三份只读复评无阻断。第六/七次原始报告与
  运行产物哈希未变；未调用真实 LLM/Tavily/外部裁判，未运行付费基准。
- 评测准备：评估协议新增/澄清[第 2.1 节决定性断言采集范围](product-effectiveness-optimization.md#21-决定性断言的采集范围)、
  [4.1.1 计数口径](product-effectiveness-optimization.md#411-caserun请求重复测量与墙钟的计数)、
  [4.2.1 共享证据基线](product-effectiveness-optimization.md#421-共享证据基线的输入截取点与成本归属)，
  以及[第 6 节具体方案](product-effectiveness-optimization.md#6-代表性评测准备方案2026-10-19-离线准备待审阅)：
  支持范围/分层配额、开发/校准/正式隔离、评审记录 schema、独立复核与分歧、简单基线
  （同检索包 + 单次综合）、工具缺口与正式运行器最小能力、阶段/资源/预算依据，以及用第七次
  材料示范的**开发示例**评审记录和 N/S/R/E 分母口径。示例不形成通过率，不替代未见集。
- 代码修复只形成“可进行下一次真实验证”的候选；离线回放只证明输入和处理机制，真实内容
  收益、可靠性、效率与基线差异均未证明，项目仍未达到投递水平。未冻结新题集、达标阈值、
  正式运行器或整批预算；下一份真实单例必须先获得新的明确授权，冻结此前未作本轮内容评审
  的全新题、必答项、候选身份、来源政策、额度与停止线，只运行一份完整报告。

## 第八次真实单例（2026-10-19）

- 授权：1 case、1 次研究；LLM≤40（含重试）、Tavily≤24（含探测/重试）、研究墙钟 ≤900 s；
  未补跑、未换题、未加额、未执行基线/基准批次、未调用外部模型裁判。代码冻结在
  `6b96a567dd309ef071c5ecd2bd310fcb171e1bb3`，运行期间 tracked clean、既有 17 项未跟踪材料保留。
- 独立准备的新题：`v8-pg-ha-cnpg-vs-patroni`（EKS 自建 PostgreSQL 高可用：CloudNativePG vs
  Patroni）；proposal file sha256 `a2fcb059…96f15e` / canonical `5bb1c2a8…41d4`；冻结 payload
  `.scratch/run_payload_v8.json` 11,879 bytes / sha256 `f6707c33…16a3bc`；query 2,416 chars
  / sha256 `66f6f2a7…e72806`。独立准备者扫描基准 case、历史 payload/run_record、KB、现代冻结
  开发集及全树候选名，候选未作为任何 case 出现；参考依据/评分规则只供验收，未注入研究输入。
- task_id **`e339d065-7a61-4993-9819-1405b23bb7cd`**；仅 1 次 `POST /research` 200
  （18:43:35，epoch 1792406615.7665）；研究 18:43:36（1792406616.4442）→18:47:14
  （1792406834.0090），**墙钟 217.6 s / 900 s**；终态 `complete`，`stop_reason=null`；
  LLM **14/40**、Tavily **7/24**，rejected 均 0。
- 服务：实际 pid 17088（`D:\Anaconda\python.exe`，端口 owner）；预加载 **72.42 s**（单列、
  不计研究墙钟）；启动器日志 imported source/paths 全 OK。停止：18:49:12 请求停止精确绑定
  pid 17088，约 6 s 后无 8100 监听、无服务 Python 残留、launcher 已退出；**但 launcher/guard
  日志未出现 guard record，无 guard_stop.json，实际退出时刻不可证**，只能记录“请求停止→
  端口/进程消失”的观察窗口。该缺口使 A 不能判为完全通过。
- token：已知 4 个 agent / 12 次调用，prompt 40,700 + completion 40,270 = **80,970**；
  实际 LLM 14 次，其中 2 次 `official_fallback` 无 token 记录，完整 token 总量与费用均
  **unknown**。来源：22 scored sources，tavily 7 / github 7 / arxiv 7 / official 1 /
  community 0；8 个来源无正文（`has_body=False`）。
- 产物（`outputs/e339d065-…/`）：`report.md` 26,723 bytes sha256 `d9e0c91f…536e9dab`；
  `research_snapshot.json` 173,981 bytes sha256 `7dff1be0…4340bb30`；
  `run_limits_counts.json` `94841eb4…e2c23c9b`；`run_state.json` `342a22fd…eb773fc`。
  `/report` 内层、`/export`（仅 CRLF 104 vs LF 104）、`/snapshot` 解析对象、`/annotated`
  归一化均与保存材料一致；25 locator / 66 绑定 / 7 个被引来源；55 个 `[Source:]` 标记，
  无 unresolved/raw 标记；1 个 GKE 标题在 identity map 用 NBSP 双空格、正文 marker 用单空格，
  同 URL，属显示空白规范化而非来源身份错配。
- **A. 运行/预算/产出一致性：主要检查通过，停止守卫记录缺失 1 项不可证，故不能判完全通过。**
  未做完整 UI 验收；不追加 UI 工程。
- **B. 内容：不通过（`not_usable`，assistant-only 独立复核，未参与实现）**。六项必答：
  职责边界=partial、故障检测/同步复制=partial、执行链/安全=partial、维护升级=missing、
  失败模式/可观察性=missing、版本/适用条件=unknown_meaningful（不算已回答）；0 项
  answered_supported。主推荐 CloudNativePG 方向在冻结允许区间，但决定性事实只由第三方博客/
  对比文章支撑，两个候选官方文档正文为 0，违反冻结来源政策；备份/PITR 硬约束未答，反转条件
  空泛；无伪造数字/危险操作/致命因果反转（按严重性锚点未发现 critical 错误），但存在重要缺口。
  失败分类：来源不足、模型遗漏/判断、代码/渲染信息损失（正文窗口截断、trade-off impact 与
  evidence_summary 未渲染、检索式进入“尚未可知”、低置信自相矛盾）、引用/适用范围问题；
  原始模型输出未保留，部分归因不可证。复核文件 `.scratch/v8_review/v8_content_review.md`；
  单例分母 N=1/S=1/R=1/E=1，不形成项目通过率。
- 边界：失败保留，未手修报告、未补跑、未自动继续修代码。该题已经暴露，不能作为未见题、
  保留集或成功分母；小规模校准/正式评测均未获授权。下一动作必须另行授权诊断/修复或新题运行。

## 第八次后离线修复批次（2026-10-19，已提交）

- 范围：只修“证据供给—综合/自审—报告输出”的共同原因，offline；未调用真实研究/LLM/Tavily/
  外部裁判，未启动第九次研究，未执行基线/基准批次。实验树代码提交 **`53a09ed`**，测试提交
  **`06017e6`**；维护文档基点为 `3c2a975`。
- **离线边界更正（必须保留）**：本批早期的一次既有回归测试（`test_candidate_identity.py`
  的 official 路径）在修复前执行了真实 `OfficialSearch`，产生了少量真实 DNS/页面 GET
  （独立复核记录至少涉及 `www.postgresql.org`、`pinecone.io`；具体次数未记录）。这不是研究
  运行，未进入报告/评分，也没有 LLM/Tavily 调用，但不符合“只允许 mock/固定材料”的离线预期；
  发现后已把测试改为 fake fetch seam，并由独立复核以网络阻断复验为 0 次真实尝试。此点不因
  后续修复而从记录中删除。
- 实际删并/替换：
  1. **官方正文**：删除 `OfficialSearch._verify_reachable()` 的“只验证链接、不交付正文”路径，
     改为经现有 `outbound.make_client("official")` 的一次有界抓取；保留 http(s)、无 userinfo、
     端口 80/443、DNS 后仅 global 地址、每跳重定向重验、请求超时、200 KB 响应上限、
     text/html/xhtml/plain、最多 3 跳、每次 official 搜索最多 2 次抓取、正文存储 8,000 字符；
     失败/超预算/不安全/类型不符保留为导航并带 `body_error`，成功正文才可引用；不新增题目
     专属域名/别名/答案，不重写 curated mapping 的用户 learned 缓存。
  2. **证据输入**：综合原来的每源 600 字符和自审 900 字符合并为
     `bounded_evidence_record()` / `EVIDENCE_WINDOW_CHARS=1600`，两阶段共享同一 visible/total/
     truncated 视图并在 quality signal 记录；fetch provenance 经 source evaluator/evidence chain
     保留；删除无消费者的 `source_scores[*].rank`。冲突模块未因一次“无冲突”删除：第八固定材料
     扫描 9 对、0 差异、9 次 LLM 调用，成本高但本轮没有可证边界决定删减；未新增模型轮次。
  3. **回答/展示**：删除“EVERY sentence/EVERY field 必须引用”和固定短字段字数上限；改为只有
     影响选择/排除/风险边界的事实主张必须引用，缺口/未知/无来源推论显式标注且不得硬挂引用；
     `what_why_how` 增加 trade-off `impact` 与 `evidence_summary`，重复的 winner_rationale 只
     显示一次；自审在**成功可用**的 review 后按实际 passed/gap 重写 confidence_rationale，
     失败/解析失败/畸形计数保留原理由，避免伪造 “0/6” 或崩溃，并清除重写后的旧引用绑定。
  4. **正常退出记录**：第八次正常路径只把 guard record print 到 launcher stdout，未落盘；
     `guard_stop.json` 仅强制停止路径写，正常完成没有它不是故障。修复为正常返回前原子写
     `outputs/guard_record.json`（task/run/exit/pid/run_state）；不改变进程绑定、deadline、
     budget 或 forced-stop `guard_stop.json` 语义。
- 固定输入诊断（第八快照只作冻结输入，未手改原报告）：
  - citable registry 14 个正文来源，最长 1,430 字符；Redrock 来源 `pgBackRest`/备份语句在
    1,358 字符处，旧 600/900/1200 窗口不可见，新 1600 共享窗口完整可见（1,430/1,430）。
  - 默认报告从 18,447 chars 增加至 23,114 chars，新增的是已有 trade-off impact 与
    evidence_summary，不是新的研究内容；原报告仍是旧报告，不能声称其内容已修复。
  - 官方正文抓取、winner_rationale 去重、confidence 一致性只在代码/测试层验证，固定输入没有
    重新抓取或重跑自审，尚未观察到内容收益；下一次真实单例必须验证。
- 验证：
  - 相关测试与全套：**575 passed**（正常离线测试；无真实外呼）。
  - 独立复核（assistant-only，未参与实现）：首轮 **blocked**，发现 B1（自审失败时伪造 0/6
    rationale、畸形 passed_count 可崩溃）与 B2（URL 安全接受 RFC 6598 `100.64.0.0/10`）；
    修复后聚焦 re-review **closed**，两项均关闭，测试与固定输入声明经核对。复核文件
    `.scratch/v9_fix_review/review.md`、`review2.md`。
  - 离线网络阻断复验：574 passed，另 1 个 guard 绑定测试为时序 flaky，单独重跑（有无网络
    阻断均）通过；评审记录的“无真实外呼”验证通过。full suite 正常口径最终 575 passed。
- 残余风险（不得当作已解决）：
  - URL 安全未做 connect-time IP pinning，仍有 DNS rebinding/proxy DNS 差异；review 还指出
    `is_global` 未覆盖 IPv4-mapped/NAT64 形式（如 `::ffff:100.64.0.1`、NAT64 前缀），本实验
    分支不声称达到 Phase-6-A 的完整安全 parity，下一轮真实抓取前应加固或限制目标。
  - official fetch 的超时是单请求/读取级，不是整页总 deadline；每轮最多 2 次抓取也不进入
    既有 LLM/Tavily 计数，下一次真实授权需把 official 抓取次数/耗时单列并冻结，不能把本轮
    0 外呼误当下一轮预算。
  - 正文抓取只离线验证了机制，未验证真实站点可达性/正文质量；共享窗口只证明信息供给，
    不证明模型会正确使用完整正文或改正历史错误。
- 未 push、未改写历史、未合并两分支、未启动第九次研究；实验树既有 17 项未跟踪材料保留。

## 第八次后第二轮离线修复（2026-10-19→20，已提交）

- 范围：关闭上一轮复核的四组问题：官方抓取安全、总deadline/大小/请求预算、正文准入与截断
  贯穿、置信理由与自审计数。真实研究/LLM/Tavily/在线探测/外部裁判调用 **0**；未启动第九次
  研究、未手改历史报告、未 push/改写历史/合并分支。实验树代码 **`63cc2ca`**，测试
  **`758e7ee`**，直接文档 **`0e3397e`**；维护文档起点 `49bcae6`。
- 实现：
  1. **固定 IP 与安全抓取**：新增 `security/urls.py`、`retrievers/official_fetch.py`；解析后
     拒绝 private/loopback/link-local/reserved/multicast、mixed DNS、IPv4-mapped、NAT64、
     Teredo/6to4；每个请求的 httpcore backend 只连已验证 IP，同时 httpx 保留原 URL 主机名给
     Host/TLS SNI；每跳重定向重新解析/验证/pinning。official 路由只读配置，配置了代理/转发
     就在任何网络探测前拒绝。未运行时跨工作树导入。
  2. **总 deadline/大小/计数**：页面级 `asyncio.timeout` 覆盖配置路由选择、DNS、连接、
     redirect、读取；`aiter_bytes` 实际读取处限制字节，content-type 缺失/不允许明确失败。
     `OfficialFetchBudget` 分开 page_attempts 与 dispatched HTTP requests（默认 2/6），
     redirect 在派发处计数，`fetch_stats` 随 official search envelope 记录；LLM/Tavily 上限不变。
  3. **正文准入与三段范围**：`utils/page_text.py` 结构提取，跳过 nav/form/hidden/aside/footer/
     header，保留 prose/heading/control/link/non-heading 结构并拒绝纯菜单、登录、heading-only
     TOC、按钮/链接菜单；`body_url`、page/stored/window 字符数与独立截断标志经 source evaluator、
     evidence chain、registry、综合与自审。非 official snippet 的整页范围标为 unknown，不再
     冒充整页；共享窗口保持 1600，但不把“容纳第八材料”当通用有效证明。
  4. **置信理由**：删除用 passed count 覆盖实质 rationale；review 必须 6 个布尔 checks 且
     passed_count 为 0–6 且等于 true 数；失败/畸形/不完整为 unavailable，不应用 corrections、
     不伪造 0/6 或 7/6、保留原 rationale/引用绑定；可用 review 改变等级时追加独立“自审调整”
     说明，reviewer 对 confidence_rationale 的修订优先，流程计数单列 quality signal。
- 验证：相关测试后冻结，单次完整套件 **601 passed**；`tests/conftest.py` 从 session 启动起
  阻断外部 DNS/TCP，仅允许回环。独立复核首轮 **blocked**：请求计数用 resolver audit-entry
  delta（一个真实探测可记 4–5 次）且非 official snippet 冒充整页；改为配置-only 路由选择、
  派发处计数、snippet page unknown 后，聚焦复评 **closed**；后续 admission/confidence 增量
  再次聚焦复核 **closed**。复核文件 `.scratch/v10_fix_review/review*.md`。
- **未完成/未验证（明确不当作已放行）**：真实站点可达性、正文可引用率、模型是否使用完整窗口、
  真实内容收益未验证；pinned 只使用首个已验证地址，无多地址 fallback；配置代理/转发时 official
  正文 fail-closed；纯文本 div/li 导航、长登录/法律文本等低链接页面仍可能误判，未实站校准；
  HTTP 请求在 transport 构造后、实际派发前预留，极端 client 构造失败可能多计 1（只会保守，
  不超 cap，不漏已派发请求）；official GET 不进既有 outbound channel 健康/审计记录；无真实
  页面/模型内容证明。
- 保留上一轮真实 DNS/GET 越界记录（`49bcae6`）；本轮的 offline 状态以测试进程阻断与复核
  报告为准，不能把上一轮偏差算作本轮验证。

## 第四项收口批次（2026-10-20，已提交）

- 范围：只关闭四项已确认问题：压缩/大小边界、研究级预算与派发计数、统一 outbound 安全入口、
  自审 item 身份。真实研究/LLM/Tavily/在线探测/外部裁判调用 **0**；未启动第九次研究，未
  push/改写历史/合并分支。实验树代码 **`e9acb9c`**、测试 **`58d7fb0`**、文档 **`a5cca17`**；
  维护文档起点 `8d83a0f`。
- 实现：
  1. **压缩/大小**：请求 `Accept-Encoding: identity`；任何非 identity Content-Encoding 在
     `aiter_bytes` 前拒绝，避免 HTTPX 先完整解压大块数据。`bytes_read` 记录从流实际消费
     字节（含越过 cap 的最后 chunk），`bytes_retained` 记录保留字节；截断长度不冒充全部读取量。
  2. **预算/派发**：删除每次 `_do_search` 重建预算；按现有 `run_limits` 研究身份
     (`task_id:run_started_at_epoch`) 归属，同一研究重入累计、不同研究独立；无身份时仅回退
     实例预算。transport/client 构造成功后才在 dispatch 前预留；重定向逐请求计数；不从
     audit entry 数量推算 HTTP。默认图只检索一次，未声称真实重入超额。
  3. **统一入口**：新增 `outbound.safe_fetch_page` / `ChannelResolver.safe_fetch_page` /
     `outbound/safe_fetch.py`，统一负责配置-only direct 路由、proxy/forward 预拒绝、pinned
     IP + Host/TLS SNI、每跳重验、总 deadline、identity 编码、读取 cap、content-type 与
     `safe_fetch` audit/health 记录；retriever 不再自行构造 HTTP client。
  4. **自审 item 身份**：在 6 布尔 + passed_count 一致性之外，要求 item 为整数且恰好覆盖
     1–6 各一次；缺项/重复/非法编号 → `item_coverage_invalid`/`invalid_item`，review
     unavailable，保留原 rationale/引用、不应用 corrections、不伪造 0/6 或 7/6。
- 验证：相关测试后冻结；单次完整套件 **610 passed**（测试进程 session 起阻断外部 DNS/TCP）。
  独立复核实际调用链（SelfReviewerAgent、Retriever → official_fetch → outbound safe entry →
  resolver → pinned fetch），结论 **PASS 四项、无 blocker**；复核文件
  `.scratch/v11_fix_review/review.md`。
- **未完成/未验证（不得当作已放行）**：不支持 gzip/br/deflate 压缩正文；仅首个已验证 IP，
  无多地址 fallback；safe fetch 不进既有 outbound route probe/health，只记 safe_fetch audit；
  非常规低链接正文仍可能误判；真实站点可达性、正文可引用率、模型窗口使用与内容收益未验证；
  预算身份按执行 attempt 变化，resume 会开新预算；无真实内容证明。离线 610 passed 只是机制证据。
- 保留此前真实 DNS/GET 越界记录；本轮以测试进程阻断和独立复核为准，不混算历史偏差。

## 第九次真实单例账本与八轮交付安排（2026-10-21）

### 账本修正

- 第九次已实际执行并消耗授权：task `f4e9b7d5-10a8-4dcf-a69d-5b2a20a58a3b`，
  1 case / 1 run，5/40 LLM、7/24 Tavily、研究墙钟 205.4 s，official **1/2 page attempt、
  1/6 actual HTTP**，未触发停止线；原始报告/快照/guard 记录保留，未手修、不补跑。
- 内容结论：**`not_usable`**；六个必答项均 partial，官方只取得 gVisor 一个 body，
  缺 Kata/Kubernetes/containerd/EKS 官方正文，决定性来源政策未通过。独立评审文件在
  `D:\deepchoice-dsh\v9_review\review.md`、`v9_review2\review.md`。
- **封存失效**：第九次派发使用未变的 payload（query hash 已冻结），但准备者在运行结束后
  继续改写 proposal/run record；最终 proposal 时间晚于运行，原始封存字节已被覆盖，
  当前材料为 `sealed-exposed`。因此不能证明 rubric/reference 与派发前逐字一致，
  **不能补写成已有效封存，也不能作为干净单例或正式分母**。保留原产物与当前封存材料，
  不再改写；下一真实运行编号为**第十次**。
- 第九次历史任务未进入第八次/第七次的分母；不合并账本、不追加通过率。

### 8 轮交付、最多第 9 轮缓冲

- 交付窗口：**8 轮**；最多使用**第 9 轮作为缓冲**，缓冲不自动增加轮次、额度或题数。
- 第 1 轮（本轮）：离线收口第九次暴露的证据获取/传递阻断（候选与平台来源发现、
  全量/有界证据包、封存交接、fallback token 与计数分离）；不改历史报告。
- 第 2 轮：第十次全新单例（1 case / 1 run）。**停止条件**：分支/HEAD/tracked/导入路径
  不符；封存副本/hash/canonical/query 不一致；运行身份或停止守卫无效；official 安全
  direct 路由不可用；实际 LLM/Tavily/official HTTP/墙钟超出冻结上限；报告/快照/用量/
  退出记录缺失或无法确认；内容评审未达到冻结最低门槛。触发后保留原件、不补跑、不换题、
  不自动改代码。
- 第 4 轮：小规模校准（仅在第十次单例内容通过且新授权后）。**停止条件**：最终交付版本
  （分支/提交/manifest/模型/依赖/缓存策略）未冻结；校准题与最终未见题隔离失败；
  评分一致性/双评覆盖/采集用量完整性/基线公平性未达预冻结要求；出现身份、预算、未知提交
  或安全越界。停止时不进入正式集，不追补通过率。
- 第 3、5–8 轮按诊断/有限修复/评测准备推进，不得用测试数、来源数、字数或结构清单冒充
  内容通过。**正式评测必须使用最终交付版本**，不能沿用历史分支、旧 manifest 或
  未冻结的 learned-docs/缓存状态。
- 下一轮新题只纳入原需求中真正影响选择的必答项，不自动扩展为完整部署审计；同时保留
  复杂场景代表性、决定性证据要求和可触发反转条件，不因收窄必答项而降低来源/归属门槛。

### 第 1 轮离线收口（2026-10-21）

- 提交：代码 **`33eb704`**（随后身份/seal 修复 **`8ff13db`**）、测试 **`e4152ab`**
  （随后 `ad13b95`）、实验文档 **`b42c2c6`**/`5626c7b`；最终完整套件 **632 passed**（Python 3.12.4，
  session 启动起阻断外部 DNS/TCP），真实研究/LLM/Tavily/在线探测/外部裁判均 **0**。
- 内容：候选与平台约束统一来源发现/归属；多词产品可用拼接 host label 或自有 vendor
  host+path，但**非 curated** 的 learned/prior/fallback 来源在安全抓取后正文必须命名
  owner，相似域名/公共托管用户子域/仅 URL 身份不通过；curated 种子按人工核验处理。
  学习映射不得用
  单 token 拥有多词 target。综合/自审共用总预算证据包：总量适配传完整正文，超限才按源
  有界选段并记录 ranges/omitted/上下文；旧每源 1600 窗口已删除。official fallback token
  进入既有 token_usage；source rows/page attempts/HTTP requests 分开，未知 None。新增
  `scripts/seal_case.py` 与 launcher 的 learned-docs/cache 冻结；运行后 addendum 写 seal 外。
- 复核：首轮独立复核为 **BLOCKED**，指出 (B1) learned/prior/mapping 路径可绕过正文身份、
  (B2) 普通大写词可成为 platform target，以及超预算均分浪费、seal 额外文件/单点 fallback
  等非阻断；修复后第二轮窄复核仍发现 prior title 可冒用身份、公共托管用户子域可通过，
  已再次修复并加负例；第三轮窄复核 **PASS**（6 项探针），指出 `docs.github.io` 仍可通过及
  vendor 子域误拒；随后补公共托管后缀与 vendor/path 回归，最终 **632 passed**。复核文件
  `D:\deepchoice-dsh\r1_review\review.md`、`r1_review2\review.md`、`r1_review3\review.md`；
  均为助手离线机制复核，不是内容/人工验收。
- learned_docs：保留第九次运行产生的 `gVisor`/`gvisor` 学习条目；调试/测试误写
  `Kata Containers` 条目已移除。该文件仍为 tracked 修改，不提交；第十次运行按
  `LEARNED_DOCS_READONLY=1` 冻结并记录 hash。历史第六至九次产物未改。
- **第十次单例预算建议（待新授权冻结）**：1 case / 1 run，不补跑；LLM ≤40（含重试/探测）、
  Tavily POST ≤24；official **4 page attempts / 12 actual HTTP**（2 候选 + 至多 2 个决定性
  平台来源，保留 redirect 余量）；单页 deadline 15 s、retained ≤200,000 bytes；研究墙钟
  ≤900 s；外部模型裁判/付费基准 0；费用未知记 unknown；`LEARNED_DOCS_READONLY=1`、
  `RETRIEVAL_CACHE_ENABLED=0` 并在 seal 中记录 hash。该实验树当前没有额外检索缓存消费者，
  该变量作为冻结策略记录，不能据此声称缓存行为已被真实测量。

## 当前授权与下一阶段

第七次单例授权 **1/1 已使用**；第八次本轮单例授权 **1/1 已使用**；第九次单例授权
**1/1 已使用**（封存失效、内容 not_usable，见上）；均不继承剩余调用上限为新研究额度，
不自动补跑。第十次单例、小规模校准和正式百例以上评测均须新的明确授权。下方旧现代分支
累计240及10/10账本保持原口径，恢复实验单列，不未经逐笔对账就相加；最终24继续封存。

第八次内容不通过，`6b96a56` 的工程通过不等于内容通过。随后完成的两轮离线修复批次只证明机制与
测试，不证明真实报告内容改善；不得据此自动补跑、换题或开展校准。下一步须先由用户另行决定
诊断/修复范围与新的运行授权。尚无新冻结正式题集、达标阈值、可用的完整语义评测实现或整批预算，
不声称项目已可投递。

### 下一次真实单例的冻结清单（建议，待授权审阅）

1. **题目**：由独立准备者新建、与 Codex 时期所有题及近义改写查重后的未见题；冻结原始请求、
   约束、影响选择的必答项、允许的条件性结论、严重性锚点、来源政策、参考依据及日期/版本、
   可答性、曝光状态和数据集 hash。实现者不据题定向修代码；运行后不换题、不改 rubric。
2. **候选身份**：本轮收尾候选 `a5cca17`（第四项收口代码 `e9acb9c`、测试 `58d7fb0`、文档
   `a5cca17`；第二轮 `63cc2ca`/`758e7ee`/`0e3397e`；首轮 `53a09ed`/`06017e6`；第一批
   `f07f87b`；如再有改动，以新提交重新冻结并说明差异）；
   冻结模型/参数、依赖、检索与缓存策略、启动器与 payload hash；运行前后核对 two trees 与
   原始产物身份。
3. **额度与停止线**：授权时明确 1 个 case、1 次研究运行（不自动补跑）、LLM/Tavily 请求上限
   （建议沿用本轮授权口径，例如 LLM ≤40 含重试、Tavily POST ≤24 含探测、研究墙钟 ≤900 s，
   最终以新授权冻结值为准）、是否允许独立评审外呼、费用未知记 `unknown`。不调用外部模型裁判。
4. **记录与验收**：保存报告、快照、用量、来源与异常；先按评估协议第 2 节评审内容，再看
   Trace 与成本；运行/产物一致性与内容分别记录（N/S/R/E 口径），失败保留；单例通过只作为
   进入小规模校准的阶段门槛，不产生正式通过率，也不证明跨场景稳定。
5. **第 2 轮封存 runbook**：准备者停止写入 → 执行者 `scripts/seal_case.py` 复制到独立目录并
   核对 `verify_seal`/payload canonical/query hash → 记录 learned-docs/cache 冻结状态 →
   派发一次 → 运行后 report/snapshot/addendum 写在 seal 外；任何 hash/身份不一致或 seal 内
   文件变化即停止，不补跑。


## 历史：2026-10-10 已关闭计划及原账本

以下保留原结案记录；其中“本轮”、暂停余额和后续步骤仅描述当时计划，不提供当前授权。

更新：2026-10-10。八小时求职交付 N1–N4 已 `closed_unmet`，非活动计划。
研究 10/10 已结算，最终 24 封存；下一轮无已冻结的工时、外呼额度或题集。
内容标准见[评估协议](product-effectiveness-optimization.md)，接手规则见[复盘](agent-development-lessons.md)。

## 已结案计划的授权、时间与暂停

本轮有效工时硬上限为8小时（28800秒），规划、实施、工具等待、验证、文档和收束均计入；
用户等待与明确暂停不计。旧十小时计划及其延期授权已
[归档](archive/delivery-ten-hour-20261010/README.md)，未达到交付标准，历史工时和研究账本保留。
本轮从北京时间2026-10-10 18:31:53计时，起始规划按3分钟估算计入；跨会话曾暂停约43秒。
用户于19:34:38再次要求暂停：当时累计**3902秒（1:05:02）**，剩**24898秒（6:54:58）**。
暂停期间另行授权的文档整理也计入有效工时；20:50:11用户明确恢复产品执行，恢复时
累计4556秒、剩24244秒。恢复不重置预算。最新秒级余额、暂停区间与现实停点以本地
`notes/delivery-pause-state.json`为准；恢复后按持续活动时间递减。

## 已核实工程与内容

- 分支 `codex/generic-selection`。基点 `f3dac3b` 的完整工程验证为Windows/Python3.12
  **3848 passed /592.01秒**，无失败或跳过。N1来源视图候选 `83e7220` 虽有
  3849项全套、smoke12/12、静态/依赖及独立复核通过，真实内容未改善，
  已由 `f059771` 可追溯撤回。
- N2绑定器 `23e37e9` 已提交，通过**3847项全套/570.77秒**、相关223项、
  smoke12/12、静态检查和独立复核。固定来源回放确认旧每事实三句否决会丢掉已生成
  回答，删除后传递改善；真实报告仍未达标。提示v43的独立内容收益也未证实。
- N3首次冻结批次233–236（候选`23e37e9`）独立内容复核**0/4**。返修候选
  `bdb3954`通过479项相关、**3854项全套/547.90秒**、smoke12/12、静态/依赖/
  编译和独立工程复核，但新冻结批次237–240再次**0/4**。237五项必答为
  缺/部分/部分/缺/缺；238五项全缺；239为缺/缺/部分/部分/缺；240五项全缺。
  未确认关键危险建议；239有局部引用适用性不足。两次FVC-02均无有效回答，
  内容不稳定，工程通过不等于可投递。
- 237/239的Tavily仅partial且official失败；238/240的Tavily `ConnectError()`，
  评分来源分别仅2弱链/0链。237的模型绑定5行经引用、自审仅留2行；239模型6行
  仅2行通过结构，保存的RDS备份事实未进入保留分析。引用unknown未被误判为假，
  渲染未见独立损失。公开快照无法确认返修包有任何网页正文成功替换；没有报告收益。
- 研究累计**240**，本轮从230起**10/10全部结算**，无剩余额度；最终24次仍封存。
  233–236及237–240运行服务均已停止，两个运行根的产品/检查点SQLite成对备份已验证。
- N4最终冻结代码/测试的受影响用例**373通过/20.73秒**，完整套件
  **3853通过/600.14秒**，无失败/跳过；smoke-v1 **12/12**且基线匹配，pyflakes、
  vulture 100%、依赖与编译检查通过。独立只读复核未发现阻断；复核指出的官方补充子页
  租约错误降级与嵌套partial边界已修复并有跨层回归。完整套件之后仅更新文档/计时记录。
  保存的237原始Markdown与导出Markdown一致，安全HTML非空，PDF具有`%PDF-`头
  （15479字节）；输入、澄清、进度与HITL相关自动化包含在全套内。未进行人工UI验收。

## 执行偏差与接续边界

前两次完整诊断分别跟随单项改动，且现场检索材料变化，成本高、报告差异难归因。
旧路线和交接措辞提供了逐包诊断暗示；我仍应先固定材料批量归因，执行偏离不能全归于文档。
230/231菜单仅使用约11KiB/24KiB并已出现官方Q1片段，模型仍只回答Q2–Q4；
232多出部分Q5内容但Q1/R0仍缺，不能把差异归功于提示修改。来源是否充分、
模型遗漏与后续代码丢失须用固定材料分开判断。21:08前的固定来源节点回放已确认：
在224/225/231三组来源中，模型多次生成完整R0及Q1–Q5六行，但旧绑定器的每事实三句
否决会整行丢弃已准确引用的行。当前候选保留每行四事实、十二原句的上界；
同一响应结构对照显示224的0行可增至5行、225的2行可增至5行、231的5行可增至6行。
这是结构传递改善，仍未证明事实适用或完整报告质量。224另有检索到的Spark官方正文
未进入保存的来源评分，具体旧拒绝原因未由公开快照定位；226首先受检索故障限制。
节点级付费探测共15次，单独记录于`outputs/delivery-batch-fixed-replay-20261010-v1`，
未增加完整报告账本，仍为232。v42/v43同来源对照各有波动，暂无稳定提示收益结论。

N3返修将Tavily拼接摘要尝试替换为安全读取的同页选段，不能证明网页正文在实际批次成功
替换，四份报告仍0/4。这条机制按“连续无内容收益”停止；`bdb3954`仅保留可回滚
的历史记录，当前工作撤回该有额外HTTP成本的候选，不继续叠补丁。独立复核发现的
非预算租约权威错误在默认检索路径可能被降为普通单源失败，作为必要安全修复单独保留。
撤回、安全边界修复与验收记录已由本地提交`5536116`保存；交付标准仍为未达标，不启用
最终24次或重置本轮10次上限。后续若继续质量工作，须基于已保存材料重新划分来源
供给、模型判断和结构过滤责任，并取得新的时间/研究授权后再设计新批次。

## 证据与封存

- 231原件在 `outputs/delivery-source-view-diagnosis-20261010-v1`；
  232原件在 `outputs/delivery-question-first-diagnosis-20261010-v1`。
  两个运行根均已关闭；原始报告不手修、不覆盖。
- 首次冻结数据集 `notes/delivery-final-cases-20261010.json`，SHA256
  `ccc092cdbd98d027d571d503f637e45705fe5738442853737525cafa3192e30e`；
  233–236原件及独立评审在`outputs/delivery-final-validation-20261010-v2`。
  两类题在运行前未暴露，失败后已用于共同原因排查，不能作为新未见题。
- 返修重检数据集 `notes/delivery-retrial-cases-20261010.json`，SHA256
  `dc67ca2dfffb7f80a6b9e82360c19ca8d5ea662bca7cd5164f2def20e8268ece`；
  两类新题由独立准备者在代码冻结后封存，顺序RVC-01/FVC-02/RVC-02/FVC-02。
  237–240原件和运行账本在`outputs/delivery-final-validation-20261010-v3`。
  两个运行根均关闭，原报告与未通过结果不覆盖、不手修、不拼接。
- 来源身份/正文绑定、引用未知语义、安全外呼、脱敏、预算、持久化CAS/fencing、
  恢复、事务与必要兼容性继续保留。测试或结构改善不代替独立报告内容判断。
