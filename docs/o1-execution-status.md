# 当前质量状态

更新：2026-10-21。最终目标已明确为代表性数据集上的可信项目指标及完整使用链路；
一份合格报告只作阶段门槛。第七次失败后的离线修复与评测准备已完成；随后按新授权执行了
第八次真实单例（1 case、1 run，14/40 LLM、7/24 Tavily、研究墙钟 217.6 s），内容未通过。
之后完成三轮第八次后**离线**修复批次：首轮代码 `53a09ed`、测试 `06017e6`（修复前既有回归
测试曾触发少量真实 official GET，见下）；第二轮代码 `63cc2ca`、测试 `758e7ee`、文档
`0e3397e`；第四项收口代码 `e9acb9c`、测试 `58d7fb0`、文档 `a5cca17`（真实外呼 0，
610 passed）。第九次真实单例后账本修正、第十次单例失败及第2轮停止均见下文；本次外部调用仅限既有授权，
未执行基线/基准批次，未调用外部模型裁判。目标见[路线](current-roadmap.md)，指标与冻结要求见[评估协议](product-effectiveness-optimization.md)。

## 当前工作树与证据范围（2026-10-19核对）

| 工作树 / 分支 | 本轮核对基点 | 适用边界 |
|---|---|---|
| `D:\deepchoice-agent` / `codex/generic-selection` | 文档基点 `4ff0eb3`；本轮协议同步提交 `c8cf0bc`；最终文档头以 Git 历史为准 | 维护路线/协议及现代 durable 产品；既有 `learned_docs.json` 未提交修改保留 |
| `D:\deepchoice-precodex` / `precodex/deepseek-adapter` | 修复前 `2aa92ef`；第1轮 `33eb704`/`8ff13db`/`e4152ab`/`ad13b95`/`b42c2c6`/`5626c7b`；第2轮 `cc9e533`/`a315e88`；第3轮 `447f1a8`/`ff71fc0`/`2b42836`；第4轮 `41c9314`；第5轮 `2138be9`；第6轮 **`f151361`**，**当前实验 HEAD `f151361`**；第8/10/11/12次 task 已运行并保留 | 当前恢复实验，仍走旧 `/research` 接口；代码 tracked 仅 `learned_docs.json`（第九次 gVisor 学习，保留未提交），17项既有未跟踪材料保留 |

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
- **第十次单例冻结预算（用户已授权）**：1 case / 1 run，不补跑、不换题；LLM ≤40（含
  fallback、重试/探测）；Tavily POST ≤24（含探测/重试）；official **4 page attempts /
  12 actual HTTP**（redirect 计数）；单页 deadline 15 s、retained ≤200,000 bytes；研究开始
  后墙钟 ≤900 s，预加载与停止清理单列；外部模型裁判/付费基准 0；费用未知记 unknown；
  `LEARNED_DOCS_READONLY=1`、`RETRIEVAL_CACHE_ENABLED=0` 并在 seal 中记录 hash。该实验树
  当前没有额外检索缓存消费者，该变量作为冻结策略记录，不能据此声称缓存行为已被真实测量。

### 第 2 轮前两处修正（2026-10-21）

- 代码 `cc9e533`、测试 `a315e88`，候选 HEAD 冻结为 **`a315e88`**。完整套件 **636 passed**
  （单次；session 启动阻断外部 DNS/TCP），相关 focused 通过；真实研究/LLM/Tavily/在线探测/
  外部裁判均 **0**。
- 修正 1：`EVIDENCE_INPUT_BUDGET_CHARS` 现在是序列化证据正文 + 省略说明的硬上限；选段先
  预留 marker 空间并在超限时重建 ranges，不用末尾盲截断；tiny/many-source 预算也由
  water-fill 后削减到上限。旧复现 24,000 预算可输出 24,380，新回归用 marker-heavy 材料
  断言总序列化文本 ≤24,000。
- 修正 2：综合与自审都调用 `evidence_focus_terms_for_state`，同一 state 的 task/constraints/
  sub_questions 产生同一 focus；新回归用真实 `ConclusionSynthesizerAgent` 与
  `SelfReviewerAgent` 的 payload 断言正文与 `source_ranges` 一致，且 sub-question-only
  marker 同时进入两阶段。
- 独立窄复核 `D:\deepchoice-dsh\r2_fix_review\review.md`：两项 **PASS**；复核后补了旧预算
  形状/实际 agent 回归，未再扩展来源启发式。测试通过仍只证明机制，不证明内容。
- learned_docs：保留第九次 `gVisor`/`gvisor` 条目，未提交；第十次 seal 前记录实际路径/hash。

### 第十次开发单例（2026-10-21，已执行，失败）

- 身份：候选 HEAD **`a315e88`**；seal `D:\deepchoice-precodex\.scratch\v10_seal`，manifest
  sha256 `bebb6f298ce3472c0238dbee13ba954f0003b6c0c602b3abe0637cfa84ca0435`；payload
  sha256 `84e6a7ead6c758a18575a48471fa6074547cc987fe2188bb249462f921ec9240`，query sha256
  `cbdbcf3afc65d593db49bc4c81ccdb3c65c385284deb979f0316783ce6a67330`。派发前及运行后
  `verify_seal` 均 ok，seal 内文件未改写；learned_docs 运行前后 sha256
  `da065234f9262f16ac4cdc312df31c3da59826ebf6ac5e5e48c430ae5e756f19` 未变。
- 实际运行：task `600af92f-f65e-41c0-aa6f-2811f943c124`，1 case/1 run；研究
  `14:14:46–14:19:10`，墙钟 **263.8 s / 900 s**；LLM **10/40**、Tavily POST **6/24**；
  official **4/4 page attempts、6/12 actual HTTP、2 redirects、0 body pages、0 bytes**，
  失败 `http:404`、`content_too_large`×2、`timeout`。guard `service_exited`、
  `exit_confirmed=true`、`forced=false`，服务退出已确认，无残留监听。
- A：**机制性通过**——单次派发、预算未超、报告/快照/端点/导出归一后一致（92 个
  `[Source:]`、0 未解析标记）、guard/退出记录完整、seal 前后不变；但 official 正文
  获取为 0，这是来源/内容失败事实，不是预算超限。
- B：**`not_usable`**。独立内容评审
  `D:\deepchoice-dsh\v10_review\review.md` 将 5 个必答项全部评 `partial`（0
  answered_supported）；没有 Sigstore 或 Notation 的官方正文，决策性来源仅来自 snippets
  与第三方；另有 C1 无依据的“迁移而非重新签名”断言。报告在 24k 证据预算内全量可见
  （10,406/10,406，无下游截断），损失在上游 official 获取。
- 运行账本：已知 token **74,243**（10 次 LLM 全部有记录；query_adapter 6,901、official_fallback
  475、conflict_detector 10,051、conclusion_synthesizer 20,379、self_reviewer 36,437），
  费用 **unknown**；无外部裁判、付费基准、补跑或手修。
- **失败原因分类**：official 官方正文 0（404/正文过大/超时）与候选覆盖不足属于来源/
  获取阻断；B 另有模型迁移断言无依据。不是 A 预算或封存问题。
- **按第2轮停止条件暂停当前技术路线**：第十次单例失败，不补跑、不换题、不自动改代码，
  不进入校准/正式评测。替代路线判断：(a) 先单独解决 official 官方正文可达性与内容大小/
  404 获取问题，再重新授权新单例，不能靠测试或别名表宣称内容；或 (b) 若产品路线继续，
  需重新冻结一个不依赖当前 official 抓取形态的新题及独立新授权；不在现有失败的第十次
  上追加修补重跑。历史产物、seal 和 learned_docs 原样保留。

### 第 3 轮替代路线与简单基线（2026-10-21，离线完成，未派发）

- 实验基点 `a315e88`；本轮离线实现提交 `447f1a8`（采集/共享证据/配对入口）、`ff71fc0`
  （测试）、`2b42836`（README/CHANGELOG）。**当前实验 HEAD/下一轮候选 `2b42836`**；本轮无
  新研究身份、无 seal、无第 11 次运行。完整套件 **655 passed, 1 warning**（单次；测试进程
  阻断外部 DNS/TCP），相关 focused 通过；本轮真实研究/LLM provider/Tavily/在线探测/外部裁判
  均 **0**，费用 unknown，不把机制测试当作内容收益。
- 替代关系（删并/收拢）：official 来源发现改为“实际检索文档优先→curated 根页面→模型 URL”；
  候选身份/页面讨论对象/来源权威性分开：展示标题只需讨论候选，别名/括号候选可由品牌域名承载，
  不再因完整名称不等而丢弃已检索 URL；比较式 Tavily 查询自动补一个同时命名所有候选的覆盖
  查询；候选缺来源时平台页标 `candidate_coverage_incomplete`，不再用平台首页耗尽剩余正文额度；
  候选页先于平台页，检索文档先于模型猜测 URL；安全 fetch、来源身份、预算与未知语义保留。
- 简单基线/配对：`src/deepchoice/evaluation/simple_baseline.py` 在“检索完成+来源评分后”冻结
  一次共享证据；`scripts/run_pair.py` 默认离线拒绝外呼，`--allow-external` 才允许真实调用。
  基线只做确定性序列化→一次综合→现有引用绑定/渲染，不运行冲突/自审/重试；候选臂保留
  conflict→evidence chain→synthesis→self-review。两臂共用原请求、来源正文、证据预算和同一
  冻结包；`evidence_equal` 在真实消费者边界用深拷贝包 hash + 归一化 source-entry 签名校验，
  基线/候选各自必须有实际消费记录，缺失或链集分歧即 false；增量 token/calls 只记各臂新增，
  共享检索行不重复归因；offline candidate 禁用 conflict evidence gathering。
- 固定输入验证：第 8–10 次保存材料只读回放；第 10 次两个候选均无 official 正文的覆盖缺口
  保留、snippet 与完整正文区分、原产物 hash 未变；检索文档展示标题/别名恢复测试、候选覆盖
  查询、平台缺口不耗额度、两臂实际消费包一致性、预算改变实际 prompt 均有回归。没有把
  第八至十次题当未见集或成功分母，也没有用来源行数替代真实正文。
- 独立复核：`D:\deepchoice-dsh\r3_review\review.md` 首轮 BLOCKED（离线门/增量成本/预算传递），
  `r3_review2/review.md` 修复 B1/B2 后仍指出 B3 证据相等是重算；B3 修复后
  `r3_review4/review.md` **PASS 无阻断**（实际消费者包、缺失/链集分歧可检测、预算实际生效、
  B1/B2 保持、655 passed）。仅有非阻断项：arm 级消费记录、pack 异常 fail-open、测试覆盖
  边界等，未扩大本轮范围。
- 接口边界：该实现属于实验树旧 `/research` 管线能力，不代表现代 durable task API/UI 已通过；
  没有新评测平台、通用爬虫、全站遍历、额外模型裁判或逐题兜底。下一轮真实比较仍未授权；
  评估协议已写 1 固定 case×2 arms、共享 Tavily≤24、official≤4/12、LLM 总≤48、总墙钟≤1800s
  的建议上限；数据须按预声明支持范围/难度选取，不按抓取成功挑题，百例以上与公平基线/
  质量/可靠性/效率/完整链路仍为最终目标。
- 本轮暂停/恢复：20:28 暂停、20:54 恢复；暂停不计主动工作时间，代码/测试/文档已提交，
  learned_docs 修改与 17 项既有未跟踪材料未提交、保持原样。

### 第 4 轮第十一次开发配对（2026-10-22，已执行，失败）

- 代码接入提交 **`41c9314`**（以第3轮 `2b42836` 为基点）。接入只验证：模型外呼与补搜分离
  （冻结证据后候选冲突不新增检索/正文抓取）、`shared_retrieval_source_envelopes` 与派发请求数
  分离（无法核实的检索 HTTP 总数保持 unknown）、同一 `run_limits`/进程守卫/总时钟下共享采集→
  baseline→candidate、每臂 ≤900 s 和剩余总时、共享快照先于两臂、每臂结果完成即保存、冻结来源
  编号/正文不一致时模型派发前拒绝、baseline synthesis/candidate synthesis/self-review 分别消费
  校验。代码冻结后完整套件 **661 passed**；离线 preflight/PairWindow 验证 48/24/1800 与 official
  4/12/15/200000；聚焦独立复核首轮 BLOCKED（守卫发现路径、预算停止误报、launcher 异常清理）后
  修复，复核 `D:\deepchoice-dsh\r4_access_review2\review.md` **PASS**；无评测平台或选型提示改动。
- 独立准备者创建并停止写入后，执行者将 5 个案例文件、run config、依赖 freeze 复制进
  `D:\deepchoice-precodex\.scratch\v11_seal`；manifest sha256
  `9b241f759d3500d2883b70cc1fda262f050264696a53a8d6e1e36044ddc2ff14`，外部锚点
  `D:\deepchoice-dsh\v11_run\seal_manifest.sha256.json`；payload sha256
  `131b54d4b66d098d62a1668ce03149bdc55d48c109f93fff153355dcd74f90c7`，canonical payload
  `e1e76d4f0edd3d49c90f355ef8e2ecdedc5074c4a7a60d8ba25bde39636ebd0f`，query sha256
  `97dc4da44954d47840d40842e24e0fafa4b122bff016012cc61bb00e8e79c399`；运行前后
  `verify_seal` ok，learned_docs 前后 sha256
  `da065234f9262f16ac4cdc312df31c3da59826ebf6ac5e5e48c430ae5e756f19` 未变。
- 实际运行 task `v11pair-a42b7594fa47`：1 case、共享采集 1 次、baseline/candidate 各 1 次；
  共享后先保存快照，再 baseline（09:39）→ candidate（09:40–09:41）；两臂均完成、无补跑/换题。
  总墙钟 **232.735 s / 1800 s**（baseline 46.203 s、candidate 134.765 s，均 ≤900 s），预加载
  **24.28 s** 单列；LLM **5/48**（共享 1 + baseline 1 + candidate 3），Tavily **7/24**，official
  **4/4 page attempts、7/12 HTTP、3 redirects、1 body page、0 stop**；总已知 token **69,932**
  （shared 4,988 + baseline 17,769 + candidate 47,175），费用 unknown；guard `service_exited`、
  `exit_confirmed=true`、`forced=false`，exit 0。
- 共享采集：6 个来源信封（actual HTTP 总体 unknown，不拿行数替代请求数），`source_scores=26`；
  official 只有 **Vector 文档首页 3,320 字正文**，OpenTelemetry resiliency/scaling 等决定性页因
  `content_too_large` 只有 snippet，无任何版本/日期；3 个失败页均 `content_too_large`。该来源
  缺口原样进入比较，未人工补正文。
- 证据消费/配对完整性：共享包 `c5d23e...`；baseline 只消费 `baseline_synthesis`，candidate
  消费 `candidate_synthesis` + `candidate_self_review`，全部 `entries_match=true`、包 hash/
  source-entry 签名一致；`evidence_consistent=true`。无配对/封存/证据身份不一致，故可作路线
  比较输入。
- 独立盲评：报告匿名 A/B，先锁定内容结论，再揭示映射与成本。content review
  `D:\deepchoice-dsh\v11_blind\content_review.md`：匿名 A（揭示后=candidate）**not_usable**，
  匿名 B（揭示后=baseline）**needs_review/not accepted**；两臂均未过 D2 证据门（决定性 claim
  依赖 snippet-only/第三方，OTel 官方正文未取得），出现自相矛盾/错误 provenance/未标推断的
  具体拓扑等；无版本/日期。最终比较 `D:\deepchoice-dsh\v11_blind\final_comparison.md`：baseline
  成本更低（1 call/17,769 tok/46.2 s vs candidate 3 calls/47,175 tok/134.8 s）但内容仍不通过；
  按预定规则 **R4 两臂均不可用 → 保留失败、停止自动研究与修复，不选下一阶段路线**。
- 本轮结论：**配对诊断失败（内容门），不是接入/预算/封存失败**；N=1 开发诊断，不形成正式
  通过率/统计性增益，不自动启动校准/百例评测或第12次。失败原因指向 official 正文获取
  （content_too_large/未取得决定性页）与两臂共同的 snippet-only 证据支撑，而非 baseline/
  candidate 差异；后续若继续须用户另行授权，先解决来源获取或重新准备新题/新 seal，不在本失败
  运行上补跑或手修报告。
- 原始产物：`D:\deepchoice-precodex\outputs\v11pair-a42b7594fa47\`（report SHA baseline
  `f8a99456...688b`、candidate `10064264...c0c7`；shared/pair/run 状态与计数完整）；
  `D:\deepchoice-dsh\v11_run\final_audit.json` 记录 seal 前后、guard、哈希与内容结论；
  `raw_reports/` 仅复制交付，原文件未改。无 push/改写历史/合并。

### 第 5 轮证据采集与来源表示收口（2026-10-22，离线+一次有界页面验证）

- 基点实验 `41c9314`；维护树 `330b174`。本轮代码提交 **`2138be9`**（采集/提取/来源身份/
  页面证据验证入口），完整套件 **669 passed, 1 warning**；聚焦代码复核
  `D:\deepchoice-dsh\r5_review\review.md` **PASS 无阻断**。第11次结论仍是两臂未通过；未改旧
  报告、seal 或 rubric，不宣布 baseline 胜出。真实研究/LLM/Tavily/外部裁判/付费基准 **0**；
  仅执行一次页面级证据探测。
- 共同原因删并：
  - 统一有界读取：声明 `Content-Length` 超限与未知长度走同一 cap/stream，截断显式记录
    `page_truncated`、`response_size_cap`、declared length/exceeded；安全连接、重定向、类型/
    编码、大小、期限、请求预算保留。
  - 正文提取：正文由主段落 + 最近标题上下文组成；目录/链接主导/导航页判 navigation，不再把
    全量 blocks 当正文；无关键词评分/专属例外。
  - 来源身份：行级 `source_owner/source_kind/body_identity_verified/has_body/fetch_status`
    贯穿 source scoring→evidence chain→shared package→synthesis/self-review→coverage；
    `docs.`/readthedocs 等 URL 词不再单独判 official；同一 URL 的 snippet、导航/失败、
    完整正文行各自保留，不覆盖。
  - 页面探测入口 `scripts/page_probe.py` 只在代码冻结后单独运行；pytest 仍阻断外网。
- 一次有界页面实测（8 个预先冻结 URL/检查；诊断材料，不是产品专属规则）：
  - 8 page attempts、**12/24 HTTP**（8 请求 + 4 redirects）、**19.578 s / 300 s**、无额外探测/
    重试/失败补批；5 body、2 navigation、1 `ConnectError`；每页 retained ≤ **1 MiB**
    （RFC 页 1,048,576；总 retained 2,458,147）。
  - OTel resiliency **正文 2,186 chars、40 main blocks/32 prose/8 headings**；OTel scaling
    **4,675 chars、46/37/9**；两页 identity verified、无截断；queue/retry/WAL/disk loss、
    60–70% 阈值、最小 3 副本、queue-full reject、memory_limiter 等决定性段落实际取得。
  - Vector 文档首页、Kubernetes docs 首页判 `not_prose:navigation_like`（不再作为能力正文）；
    Python asyncio、MDN HTTP Overview 正文；RFC 9110 大页显式 `response_size_cap` 截断
    （61,834→20,000 chars）；Docker docs `ConnectError` 原样记录失败。无版本号；日期只记录
    存在性。
  - 消费者前后：v11 旧 official 行 OTel 为 `has_body=false/content_too_large`、只有 Vector
    目录正文；新消费者路径把 OTel 两页作为 `official_doc`+verified body 放入 shared package，
    目录页只进 navigation，MDN 无 owner 验证时保持 `official_unverified`，不冒充 official。
    证据文件 `D:\deepchoice-dsh\v11_page_probe\page_probe_result.json`、
    `consumer_before_after.json`；独立证据复核
    `D:\deepchoice-dsh\r5_evidence_review\review.md` **PASS 无阻断**。
- 残余（非阻断，但限制下一轮）：OTel resilience 的 `<li>` 列表项仍未抽取，因此“队列满丢弃
  新数据/重试超时丢最早/默认约1000批”等仍只在旧 Tavily snippet tier，不能当正文；页面探测
  使用诊断 cap（1 MiB/20k chars），与正式运行默认（200KB/8k、4/12）不同，下一轮须先冻结
  兼容 cap；探测是合成 8 URL 消费者回放，不等于真实发现覆盖。页面探测只证明采集表现，不证明
  报告通过、未见评测或 baseline 胜出。
- **路线判断**：决定性 OTel 正文已取得且身份无误报，采集路线**可以进入研究**；但按用户
  要求仍停在**第12次派发前**，不自动启动新研究/校准/百例评测。下一轮需新授权并先决定列表项
  提取与正式 cap 对齐；不得把本轮 probe 当报告通过。

### 第 6 轮第12次开发配对（2026-10-22，已执行，内容门失败）

- 前置收口提交 **`f151361`**（以第5轮 `2138be9` 为基点）：主内容保留段落、列表、代码/配置块、
  表格及标题/限定说明，导航排除；探测身份只用 URL+保存正文（无人工 label/generated title），
  原探测记录保留并追加离线 identity correction；成功、prose 拒绝和传输失败都保留已知
  bytes/declared/truncation，未知不填 0；正式 caps 实际加载并核对为 1 MiB retained、20,000
  存储 chars、24,000 证据 chars、official 4 page/12 HTTP。完整套件 **672 passed**；聚焦复核
  首轮 BLOCKED（prose 拒绝路径 metadata 丢失）后修复，`r6_preflight_review2` **PASS**。
- 独立准备 V12 后停止写入，执行者将 5 个案例文件 + run config + 依赖 freeze 封存：
  `D:\deepchoice-precodex\.scratch\v12_seal`，manifest sha256
  `230ef5f3c97d8941b4c48885696471c688cab4ff1a5ff93d5949462a5d9755fc`；payload sha256
  `9519cad0f55e18f69c14af49c33c27fe18a4e41fbe6751db70c5cedbc92a47c2`，query sha256
  `d4a4877ab8b683b412269f5a37b5bda18d7eabbd44935f3f9d91b434849d04b5`；运行前后 verify_seal
  ok，learned_docs sha256 前后 `da065234...756f19` 未变。
- 实际运行 task `v12pair-f3166ac23bcc`：1 case、共享采集 1 次、baseline 1 次、candidate 1 次，
  无补跑/换题；共享后先保存快照。总墙钟 **263.203 s / 1800 s**（baseline 70.282 s、
  candidate 152.969 s，均 ≤900 s），预加载 **77.85 s** 单列；LLM **7/48**（shared 1 +
  baseline 1 + candidate 5），Tavily **6/24**，official **4/4 page attempts、5/12 HTTP、
  1 redirect、3 body pages、1 个 403**；总已知 token **85,916**（shared 2,520 + baseline
  23,535 + candidate 59,861），费用 unknown；guard `service_exited`、`forced=false`、exit 0。
- 共享采集 6 envelopes/28 source scores；两臂共享 16-source 证据包（24,000 预算，
  visible 23,469/full_included=false）；`evidence_consistent=true`，baseline_synthesis 与
  candidate_synthesis+self_review 消费记录一致；无补搜。来源统计更正：**取得正文 ≠ 权威且
  适用的决定性证据**。3 个 unique full-body 页面分别是 Tasklist 产品营销页、早期 Temporal
  社区 forum、Schedules SDK 文档，不构成“三份合格官方依据”；另有 23 个 snippet-only 行和
  1 个 403。仍然没有版本化 Camunda 8 生命周期/许可或 Temporal 人工任务/审计官方材料。
- 盲评：先匿名为 A/B，锁定内容后揭示映射 **A=baseline，B=candidate**。content review
  `D:\deepchoice-dsh\v12_blind\content_review.md`：baseline **needs_review**（5 项全 partial；
  决定性 human-task/audit fit 依赖版本缺失的营销页 + snippet-only 平台页，社区-only Temporal
  证据）；candidate **usable (conditional, lower band)**（5 项全 partial，低 confidence，
  决定性支持主要 full-body，但仍把版本缺失营销页误称官方，RabbitMQ/审计保留未知）。
  **正式验收统一为“两臂均未通过”**：candidate 的 lower-band 只是诊断性评价，不是冻结门槛
  通过；两臂正式 rubric 均为 0 项 score 3、C1 版本化官方证据不足，均不可用。
- **决策契约缺口（当前代码机制，非第12次历史因果）**：综合输出主要要求产品 winner 或
  `context_dependent` 平局；`_validate_winner` 会在空/无效 winner 时回退到首个 ranked option，
  `_validate_constraint_fit` 会把 winner 改成最高 constraint-fit 选项，三个默认渲染器在空
  winner 时也会取首个 ranked option；自审可修改 recommendation/选项文本，但 **winner 不在
  可纠正字段内，无法撤回 winner**。第12次原始模型输出未保存，只有最终 recommendation 保留，
  因此**不能断言**第12次曾产生 hold/空 winner 又被校验或渲染覆盖；该因果未验证，上述机制
  只描述当前代码。
- **工时记录更正**：暂停记录中的“5 h 32 min”是从近似开始到暂停的**墙钟区间，不是经核实的
  主动工时**，不能据此判定 4 h 超时。可核实：暂停 19:50:08、恢复 21:18:54，暂停
  **1 h 28 min 46 s**；恢复后至交付约 **59 min**。暂停前主动工时**无法准确重建，记为
  unknown/estimated**；不基于错误暂停记录判定超时，也不补记或重置任何授权。
- **路线结论：两臂均未通过正式门槛 → 停止这条自动研究路线**；不启动第13次、同类补丁、
  校准或百例评测。N=1 只支持该 case 的门槛判断，不构成统计性优势/正式通过率；原始失败、
  内容评审和来源缺口保留。本轮不 push/不改写历史/不合并；两树 learned_docs 修改、17项既有
  未跟踪材料与历史产物保留。
- 原始报告：`D:\deepchoice-precodex\outputs\v12pair-f3166ac23bcc\baseline_report.md`
  SHA `d0e8a3a9...c5b1d4e`、`candidate_report.md` SHA `23f4dcd3...f3a230f`；
  `D:\deepchoice-dsh\v12_run\final_audit.json` 记录 seal/guard/usage/content 结论，
  `raw_reports/` 为副本，原文件未改。

## 当前授权与下一阶段

第七次单例授权 **1/1 已使用**；第八次本轮单例授权 **1/1 已使用**；第九次单例授权
**1/1 已使用**（封存失效、内容 not_usable）；第十次单例授权 **1/1 已使用**（A 机制通过、
B not_usable）；第十一次开发配对授权 **1 case/1 shared collection/baseline 1/candidate 1
已使用**（内容两臂均不可用，按 R4 保留失败、停止自动研究与修复，不选路线）；第5轮仅授权
代码收口与一次 8 页/24 HTTP/300 s 页面级证据验证；第6轮授权 1 case/共享采集1/baseline 1/
candidate 1 **已使用**（task `v12pair-f3166ac23bcc`），两臂在正式门槛下均不可用，按本轮
规则停止自动研究路线；均不继承剩余调用上限为新研究额度，不自动补跑。第3轮离线替代路线/
简单基线未派发研究；第4轮接入完成但内容失败。后续第13次、小规模校准和正式百例以上评测须
新的明确授权；第10/11/12次失败及第5轮 probe 之后不得自动启动修复、换题或补跑。下方旧现代
分支累计240及10/10账本保持原口径，恢复实验单列，不未经逐笔对账就相加；最终24继续封存。

第八次内容不通过，`6b96a56` 的工程通过不等于内容通过。随后完成的两轮离线修复批次只证明机制与
测试，不证明真实报告内容改善；不得据此自动补跑、换题或开展校准。下一步须先由用户另行决定
诊断/修复范围与新的运行授权。尚无新冻结正式题集、达标阈值、可用的完整语义评测实现或整批预算，
不声称项目已可投递。

### 下一次真实单例的冻结清单（建议，待授权审阅）

1. **题目**：由独立准备者新建、与 Codex 时期所有题及近义改写查重后的未见题；冻结原始请求、
   约束、影响选择的必答项、允许的条件性结论、严重性锚点、来源政策、参考依据及日期/版本、
   可答性、曝光状态和数据集 hash。实现者不据题定向修代码；运行后不换题、不改 rubric。
2. **候选身份**：当前实验 HEAD **`f151361`**（第5轮 `2138be9`；第4轮 `41c9314`；第3轮
   `447f1a8`/`ff71fc0`/`2b42836`；第2轮 `cc9e533`/`a315e88`；如再有改动，以新提交重新冻结
   并说明差异）；冻结模型/参数、依赖、检索与缓存策略、启动器与 payload hash；运行前后核对
   two trees 与原始产物身份。
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
