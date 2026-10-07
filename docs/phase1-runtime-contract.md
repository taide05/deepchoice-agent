# Phase 1 运行契约与恢复手册

本文固化 Phase 1-A～1-G 的 durable lifecycle 契约，并记录后续阶段对恢复、事件和持久化
决策的增量。代码、迁移历史和自动化测试仍是最终事实源；设计文档描述目标，不能覆盖这里
记录的实现边界。

## 1. 适用范围与兼容边界

具备完整 durable lifecycle 保证的是 `/api/v1/tasks/*`：任务和 run 写入产品 SQLite，
由 coordinator 执行，通过 durable `task_events` 对外发布状态。

Streamlit 默认创建、查询、事件、取消、恢复和结果读取均使用 `/api/v1/tasks/*`，并保存
`Last-Event-ID` 以支持断线 replay/resync。

`POST /research` 是一条已弃用的独立兼容路径，仍使用进程内 `_active_tasks` 和旧 SSE。
它创建的任务不会自动登记为 durable task，也不具备新 API 的取消、恢复、lease/fencing
或 durable replay 保证。旧接口保留一版并返回 `Deprecation`、`Warning` 和 successor `Link`
响应头；旧结果读取在本地文件不存在时只读 durable artifact，不会创建或重复执行任务。

## 2. 身份、状态与版本

2026-10-07 R9：合成v34、引用v20冻结runtime-source-views-v2。视图菜单、数值坐标兼容菜单、
范围绑定及引用范围准入共用最终来源集合；调用者显式传入可信task候选，不从模型正文推断。
标题中的字面产品身份复用R8匹配区间规则，仅对明确单产品来源分配机会，不证明语义支持。
按请求候选顺序，依来源原顺序尝试首个可装、真实可绑定的来源，再由余量填充其他来源；
输出沿用原链顺序和S原位置/数值原位置编号，不重排evidence_chains。此策略尽力覆盖，
不保证全局最优装箱：较大首源仍可能使后置候选缺位；选择提示列出没有字面标题提及的候选。
24来源/24000 UTF-8字节不变，每来源以数值行与视图行较大字节数加统一换行计费；
只投影同一集合，不分别截断。所有完整句、争议及邻句、唯一title/URL/position规则保留。
数值整行是最终成本下界；若已超剩余空间，不生成其视图。仅本次调用复用已构建行，
无持久缓存、新状态或外呼。每次视图选择从当前来源重算并比较完整offered映射；未知、
伪造或过期ID拒绝。五事实上限不变。带source_ranges的事实始终受共同菜单准入，
无范围的完整来源事实仍保留既有直接兼容绑定，不允许非法/空范围转成完整来源。
旧数值函数保留签名/坐标格式，但采用当前统一容量规则；历史v33/v19 manifest身份可读，
当前同run恢复拒绝。工作流、state schema、数据库、报告模板及自审v9均不变。


2026-10-07 R8：自审v9的候选归属复用来源准入的字面产品身份，剥离已识别选择动作仅用于
匹配，原option标签不变。option、reasoning、assumptions、change_condition及provisional
解释提到的显式产品必须在该项自己的绑定来源中出现；其他项事实不授予归属。保持版本、
符号和复合名称，不猜别名；动作为空产品或嵌套动作的具名标签拒绝。同请求中短名只作为
更长显式候选的一部分出现时，不算短名归属；独立短名提及和同一产品的不同动作仍可用。
这只是字面归属防错，不证明主张语义或来源适用性，不改变引用状态、判断/操作权限和调用上限。
新manifest冻结自审v9及提示内的literal-product-identity-v1；历史v8身份可读且hash有效，
不允许同run恢复。工作流、state schema、数据库、公开结果结构和三模板身份均不变。

2026-10-07 R7：合成v33的默认第二次判断调用仅选择一个已展示的R0/Q question_id
和1–12个唯一basis_refs原句ID。临时映射由运行时逐事实生成，保留独立passage位置；
只有完整saved_text通过来源边界，且逐passage展示句序与原binder对整段分句完全一致，
才提供该事实的引用。没有可引用原句时跳过第二调用，不产生该调用的预算消费或Trace。
运行时仅从已展示ID复制完整原句及原fact_id/1-based sentence_ids，再经既有结构绑定、
引用核验和自审。未知/重复/非法/超限引用整行拒绝，不猜测坐标或留下部分依据；仍限
4个事实、每事实3句、每原问题1行/总8行。无效第一行也占用该问题，后续重复行不能替换。
R0的单侧候选保护及子问题不得choice保持。模型旧requirement_ids/basis/复制来源/权限字段
不透传。公共answer_contract和canonical basis格式不变，无manifest的数字引用兼容入口保留。
逐行requirement_ids仅绑定该原问题，不推断C覆盖；完整原始C约束仍提供给合成、公共
answer_delivery inventory和SelfReviewer original_request，报告逐行Addresses不再列C。
这是范围明确的投影变化，不证明每约束已回答。新diagnostic profile question-judgment-v2
只作浅层观察；旧v1仍可读。manifest冻结新prompt及runtime-question-basis-v1策略，v32及
更早身份可读且原hash有效，但不能当前同run恢复。工作流、引用政策、状态schema、数据库
和公共节点不变，不新增调用或判断权限。原句身份不等于语义支持；工程验证不证明模型
选择正确、关键问题有用或质量稳定。

2026-10-06 R6：合成v32的默认事实选择调用仅返回source_view_ids（最多五个菜单ID），
运行时生成F编号并通过原binder复制来源。短焦点与最大窗口均保留原关注坐标及左右邻句，
模型不能提交F编号/范围/复制正文来改变该绑定。临时ID映射冻结完整原来源并比对重绑文本、
位置、标题和规范URL；仅实际展示的ID可用，源身份变化、未知ID、非法类型或超限不猜测。
重复ID只占一个事实槽。事实初始unknown，页面核验及分析自审仍独立执行。
菜单实际有视图的完整来源行限24源/24000 UTF-8字节，超限整行跳过；整源可补位，
范围源仍只从历史selection_packet限额集合准入，binding/citation/review共用重算守卫。
不会让历史范围门外来源因菜单补位获得权限；该限额可能继续排除后置长来源。
公开source_facts及无manifest直接兼容格式不变；范围关注坐标始终从原文派生相邻上下文。
不增加调用、节点、环境参数、graph state、数据库或判断权限。synthesis资产冻结视图策略，
新观察profile为fact-view-selection-v1；旧profile与v31及更早manifest可读、身份有效，
但不可当前同run恢复。窗口和机械邻句不能证明远处限定、语义适用或真实报告改善。


2026-10-06 R4：分析的assumptions必须是显式list、0–4项额外未确认前提；[]合法，
缺字段/None/空文本/超限仍拒绝。合成与自审提示要求保留用户给定条件及绑定来源限定，
不把它们重写为未知；用户陈述仍不能证明技术真值，basis/引用/自审和操作限制不变。

SelfReviewer仅在有可审analysis或provisional槽时调用模型。两者为空时，先通过原
apply_analysis_review清除旧审阅元数据并撤回无效提交，再记录not_run/no_reviewable_items、
passed_count=0、total_checks=0、targeted_attempts=0；不追加伪造的LLM usage行，仍保持
既有node retry_count语义。任一无效提交或无有效完整引用投影均low+固定安全缺口：严格
解析CitationVerification，要求非空checks和计数与实际check状态一致；None/数组/非法
counts/空或缺失投影不可视作已完成核验。有效且全verified的无对象路径只保持不高于
既有confidence，不把跳过记成六项通过。旧knowledge_gaps原文不透传，防止检查点/模型
文本含私密输入。报告说明撤回，空额外前提不再声称必须确认假设。
合成v31、自审v8与三模板v20/v19/v18隔离历史同run恢复；citation v19、workflow/state、
生命周期、HITL和数据库不变。工程测试不能证明真实模型正确区分已给条件与额外未知。

2026-10-06：默认 graph 与独立直接代理默认模式均采用 `scan-only-v2`；manifest schema v1
冻结 conflict_policy_version、scan v4、合成 v33、自审 v8、三模板v20/v19/v18与
deterministic-citation-v19。历史
scan-only-v1 / scan v3 / 引用 v18 及缺省字段身份可读且保持原hash，但不能当前同run恢复。
当前核心资产只索引6个prompt与6个LLM call快照，不含已退出默认路径的 arbitration、
evidence_gather、rearbitration。历史manifest的缺省None不进入历史hash；旧prompt/call
仍可解析并校验原身份，但不能同run恢复。workflow research-v4、state schema v3不变，
无生命周期或产品数据库迁移，旧结果可读。

扫描仍只覆盖score≥5、标题余弦≥0.65的前15对，局部并发4。双方均有完整连续的保存文本
（至多2000字符、40句、每句400字符，无遗漏标记、片段或多位置）时，同一次原scan调用
提供完整索引句；否则退回两段前400字符，不能授权局部复用。单一passage必须与可见snippet
完全一致。输出上限仍512，无新增调用。
明确的false/none为否定；合法true/允许的差异类型为模型标记冲突；调用失败、无描述或
非法/矛盾输出为unknown。unknown不声称事实矛盾，其reason只用固定枚举，不带异常正文。
标记/未知均保存在原conflicts字段，scan_status区分confirmed/unknown；confirmed只表示
扫描标记，不是语义证明。默认resolution为insufficient_data、confidence为low。
双方各1–3个有序、不重叠、整数的零基半开句范围，经唯一位置核对后产生runtime scope：
sentence-conflict-v1、URL/完整文本/结构的hash及原范围。hash只证明同一保存视图，不证明
模型定位完整或事实真伪。false/none带非空或非法范围为unknown；true范围缺失/任一侧非法
仍保留confirmed并整来源排除，不丢掉扫描记录。忽略检索器输入的scope元数据。
证据链按规范URL合并所有已知冲突；任一unknown、旧无绑定或身份失配都保持整来源排除。
有效scope仅允许显式source_ranges事实；焦点与左右各一完整相邻句必须避开所有争议范围，
不得整来源引用。selection、绑定、引用重新派生和自审共用校验，保存原来源与幂等事实地址。
通过页面词法核验和自审后，局部事实可用于有前提的choice分析，不能赋予确定赢家或生产
操作权限。chain.disputed仍true；预算最低证据门继续按整URL排除，不把局部事实计入三个
无争议链。HITL、恢复及生命周期契约不变。未扫描对不视作已验证无冲突。
quality_signals分别统计conflicts_found与scan_unknown_count；unresolved_count包含两者。
预算错误和取消继续传播，扫描已派发工作先drain；普通提供方/输出故障只保留未知，不泄露细节。

默认取消仲裁和补搜外呼；`gather_evidence`保留请求及manifest的输入值，用于历史输入身份，
在OpenAPI标记deprecated并说明scan-only不受此开关影响，公开质量信号记录requested及
effective=false。这同样适用于已弃用`/research`的当前graph，不增加新的HTTP入口。
只为旧直接代理保留显式legacy_arbitration=True与原补搜开关，SDK重试/预算/Trace契约保留。
兼容仲裁异常必须保全扫描标记，任何赢家/高置信度仍不能解封来源；未知对不参与仲裁。
标题筛对、未提供完整坐标的短描述、模型范围漏判与保守排除仍可能丢失或误用事实。
词法核验、自审与hash均不是语义证明；真实质量收益尚未测量。


2026-10-06：source-score-v9 与 synthesis v29 冻结候选动作标签的字面产品路由。
共享 candidate_search_name 只移除一次明确的前置动作短语：继续使用/继续采用/迁移到/
切换到，以及 continue using/keep using/migrate to/switch to/move to/stay with。
保留原任务、原选项标签和分析 option；未知前缀、版本/复合标识保持字面身份，不生成
alias或从原问题猜产品。来源完整名称匹配、受审种子候选归一化、问题包完整名称及原有
长词提示均使用这一身份；受审种子仍要求冻结identity、登记target和可见目标词。
只有动作而无产品或剩余串再次以已知动作开头时，拒绝推断产品；来源gate保持非空
永不匹配模式，问题包不记覆盖；不得退回无候选
的兼容放行。无新LLM调用、状态字段或schema迁移；历史评分v8/合成v28身份可读但
不能当前同run续跑。问题包的既有复合长词提示仍只是路由，不证明版本或完整复合适用性；
来源及引用核验不因此放宽。本包不保证所有自然语言候选都能解析或真实报告质量改善。

2026-10-06：official 检索版本 v4。durable 路径将已学习及模型回退发现的地址纳入
有界正文读取；动态地址必须是无凭据、无 query/fragment 的有效 HTTP(S) 精确页面，
端口仅80/443，沿用 SafeUrlPolicy 的 DNS/IP、响应大小、类型与时间边界。动态 HEAD
和 GET 均 max_redirects=0，不访问子链接；HEAD 不受支持时保留安全 fetch 的 Range GET
兼容，探测200/206视为可达，404/410视为缺页，其他状态或安全/网络异常为显式失败。
正文 GET 返回地址必须与规范化请求地址相同。
地址/标题/learned 元数据不能授予目录权限；仅代码 TECH_DOCS 命中可读取原有目录范围
及最多两个子页。两类共享最多两个根名额，登记目录优先，正文 GET 总上限仍为6。
目录占位文本不进入 durable 结果，PyPI 元数据分支保留；无 RunContext 的兼容行为不变。

每次正文调用仍先取得 http_calls 预算，拒绝不得 dispatch，失败/取消保守结算。
公开结果 origin_kind 仅为 curated/discovered；界面将该通道标为文档检索，并标注发现页
身份未审核。source_type 权威分类仍按原静态目录校验，不按通道或此标记提升。
动态映射的有界文件字节 SHA256 通过内部 RetrievalRequest.official_mapping_id 进入
现有缓存 hash 键，不持久化明文查询/URL。缺文件为稳定空身份；不可读、非法 JSON、
非对象或超过512 KiB则绕过缓存和 single-flight。hit/coalesced/write 前重核身份；若
本次回退学习改变映射，不把结果写入旧身份键。无缓存表迁移、请求端口或状态 schema 变化。
新 manifest 隔离旧 official v3 缓存及同run续跑，历史身份/结果仍可读。

HEAD 成功后的映射学习仍先于正文 GET，正文失败不自动删除该映射；后续失败仍可见。
精确发现页不保证有相关正文；英文词项提取、空主题及共享容量仍可能产生证据缺口。
本变更不证明来源适用性、语义正确或真实报告质量，也不增加 provider/模型纠错调用。

2026-10-06：查询适配提示版本 v3；Tavily/GitHub 检索版本 v2。适配器仍输出
`adapted_queries: dict[str, list[str]]`，每个列表按当前目标索引排序，缺失或无效变体逐项
回退到原目标；重复索引的目标整体回退，布尔/越界索引不采信。不追加模型纠错调用。
Tavily/GitHub 的已返回查询批次按轮分配不重复URL，保留每批内部顺序；不保证返回结果
具有相关性或全部目标都有证据。GitHub 保留仓库搜索接口、最多4次搜索与旧原查询回退，
完整适配表达式直接传入q，不再拆分qualifier/引号。源内故障继续显式失败，预算错误直接
传播，缓存键继续绑定manifest。历史身份可读但不能同run续跑；无迁移或状态schema变化。
此包不改变arxiv/community的单查询选择、候选词法准入、官方正文入口或引用安全边界。


2026-10-05：新 schema v1 manifest 的每个 LLM call 显式冻结 `sdk_max_retries=0`。
普通 `call_model` 的重试仍由共享帮助函数逐次预算准入；冲突证据补搜每轮只执行一次 SDK
请求，关闭 SDK 隐式重试。补搜遇到限流、5xx 或连接异常沿现有失败路径结束，未知 token
按 unknown_spend 保守记账，已知 LLM 调用计为一次；不因失败重置费用或暗中再发送。
历史 v1 manifest 缺少该字段时仍按原 hash 可读，但不能在当前代码上同 run 恢复；新身份
不修改 prompt、workflow/state schema 或迁移，旧结果仍可查询。每轮补搜预算拒绝仍必须在
dispatch 前传播，不得由普通来源降级吞掉。HTTP/retrieval 的逻辑调用计量边界没有改变。


2026-10-03：开启 `DEEPCHOICE_SYNTH_THINKING=1` 的新 manifest 显式保存
`thinking.type=enabled` 与 `reasoning_effort=high`；默认仍关闭，输出上限仍4096。
思考模式下供应商忽略 temperature，不据此声称生成确定性。当前工作流/资产兼容的历史
manifest 若只有 enabled 而无显式 effort，仍按其原身份校验和保存的 body 调用，恢复时不
补写新参数。本次参数明示不改变 workflow/state schema、提示版本或生命周期/预算边界。

2026-10-04 的 v23 研究运行保持 `research-v4` / state schema v3、citation v16、自审 v7，
当时将 synthesis 提示身份升为 v23。带 manifest 的合成先从完整证据链选至多5条来源编号，
运行时用原有来源注册表重建完整原句；随后在一次有界判断调用中，按原请求 R0、冻结子问题 Q（最多8个原题行）
分别返回短分析行。每次仅给已绑定事实的完整分句地址、原约束及不可信用户补充上下文。
来源标题命中候选只作路由提示，不证明适用性；全部事实明确只涉及部分候选时，
R0 留空，具体子问题仍可条件回答。子问题不能另造 choice；空/畸形结果按项留缺口，
不调用旧整体结构纠正。保留分析继续经过原绑定、引用和自审，运行时不接受模型写入的
Winner、需求满足状态或行动权限。每次阶段生成均使用同一 manifest 冻结的 DeepSeek
参数并独立预算准入/结算；预算和执行权威错误直接传播。`quality_signals` 仅记阶段数量、
绑定量、单侧弃答与固定错误计数，不保存来源正文或模型推理。旧 prompt v22 与已撤回的实验 v24/v25 可读，
与该 v23 提示身份不兼容的同 run 恢复安全拒绝；无新迁移、顶层状态或生命周期事件。
无 manifest 的直接兼容调用保留原单次合成和最多一次结构纠正。
此处是工程机制，不证明语义正确或真实报告质量；公开四例与保留集仍按协议分开。

2026-10-02 当时运行使用 `research-v4` / state schema v3、synthesis v22、citation v16、
self-review v7，三模板 what-why-how-v18 / evidence-first-v17 / comparison-matrix-v16。
来源事实最多5条，单项分析仍最多4条；旧manifest身份可读但不能同run续跑。

当时有 manifest 的运行使用 question-analysis-v1 合成输出；当前分阶段运行沿用其输出契约：模型只交付来源事实与
针对原问题的条件分析，不交付可采信的 Winner、逐项满意状态、正式分支或操作许可。当时缺
必需字段触发既有最多一次结构纠正；当前分阶段运行不执行该纠正，显式空列表允许作为真实缺答。来源原句、引用核验、
自审和原有预算/HITL 门控逐项生效；受限报告移除该交付模式。三种报告格式保留各自
阅读顺序并只展示已保留分析，未触及的问题明确列出；触及原问题不宣称完整回答。
自审留下的公开关键缺口以固定提示显示，长操作计划在紧凑报告中只保留安全边界说明。
超出需求上限时不发表新分析。旧结果读取及无 manifest 的直接调用保留旧投影路径；
/research 启动时也生成当前 manifest，因此新运行采用当前紧凑契约。
工作流顺序为 citation_validator → self_reviewer → evidence_decision_gate → report_generator。
自审先降低置信度，再由原唯一 gate 判断结构不足与实质不确定；没有新增 HITL 门或自动重搜。
旧 research-v1–v3 身份可读，不能以新图恢复旧检查点；旧 pending 仍允许 cancel。

自审使用共享最多 8 个槽位：先保留有效 A 分析槽，再接纳原请求中未知需求的 R 解释槽。
对仅因另一个句子的限定条件未核实而保持unknown的完整来源，新策略只允许其已通过
词法检查的原句作为A分析依据；自审仍检查完整保存来源，未审分析不可展示。R解释沿用
原完整来源资格；来源整体status、Winner、行动权限和引用四状态不变。
R 按原行号、需求 ID/文字、claim_path、完整 claim_text/title 多重集合、canonical URL 和
当前重绑来源核对；仅 verified 或 network_uncertain 可进入，其他未知原因不能借自审提权。
原/历史 provisional_explanation 没有本轮有效审阅时不显示，原结果存储正文不改写。

输入包含原请求、私有补充上下文、准确绑定原句和全部至多 4 个完整可审保存来源。
每个保留项必须对这些来源返回有界 stance/句号；漏项、错句、重复或 qualify/conflict 后
仍 keep 均拒绝该项。运行时还检查标题、推理、假设和改变条件中明示候选的名称在本项依据
原文/标题中出现；这是词面覆盖，会漏掉别名，也不能证明来源真正支持该断言。
A revise 可改推理/假设/改变条件；optional additional_basis 仅追加当前可审来源的确切句子，
原依据原序不动、总来源至多 4，新增句子须覆盖本项 qualifies/conflicts 指定的反例句，
且推理必须变化。模型仍可能误判 stance 或写出错误修订，不能称为语义验证。
R revise 只改至多 200 字解释，不增来源；仅本轮明确保留的解释以字面文本显示，并附运行时
来源原文和真实核验状态。来源状态、需求状态、Winner、计划和操作权威不因自审升级。

无法解析/服务失败时撤回未审文字，其他合格项按项保留；存储固定计数/状态及固定公开缺口，
不保存自由自审评语。六项检查只覆盖上述输入和标题摘要，不代表整个报告或方案安全验收。
模型修订仍需人工审阅，置信度只降不升。仍只有一次调用、4096 输出 token；最多 8 项并不
保证任意长修订都能装入输出，截断或缺项按相同门撤回，外呼仍受完整输入预算准入限制。

普通研究轮仍调用自审一次；过去先暂停/limited_report/cancel而跳过自审的分支，现在
会先调用一次并可能预算拒绝。pending 检查点重启与 limited_report 恢复不重复自审；
provide_context 发起新的研究轮并再次计量自审。模型成功、失败、重试和取消沿用既有
预算准入/结算；拒绝与持久化失败不能吞掉。完整消息按UTF-8字节加4096输出上限预留，
不截断已绑定依据以绕过预算；大输入可超过60,000上限，只有符合最低结构证据时生成
本地受限报告。真实双库测试覆盖暂停、重启、两种恢复及重复解决；这是离线工程证明。

以下为 synthesis v18 已引入并保留的绑定规则。新生成的每项 decision_analysis 必须提供 basis：
1–4个不重复 fact_id，每项选择该保存片段内1–3个不重复、从1开始的整数 sentence_ids。
提示与绑定使用同一完整文本规范化和分句函数；运行时据此重建 fact_ids 与 source_sentences，
不信任模型提供的引文或旧 fact_ids。无效地址移除整项并进入既有最多一次结构纠正，不增加
新调用类别；历史无 basis 投影可只读，当前生成不能走该兼容分支。旧 v16/v17 身份仍可读取，
不能在当前行为下同 run 恢复；该次合成修订未改变 workflow/state schema、迁移与生命周期。
v18精简重复的合成规则与示例；完整保存片段、句子地址和一次纠正保持。预算仍按完整消息
UTF-8字节加输出上限保守预留，未提高硬限额或改用乐观token估算。

引用节点继续重建来源及地址，必须完整保存片段通过本轮核验后才保留分析；渲染再次复制
保存原句并转义，先展示原句、再展示模型判断，完整上下文继续可见。提示要求按判断维度
拆分、明确缺失前提并保留条件方向，但这些是生成约束，不是语义证明。合法地址仍可能
指向不相关原句；human_review_required、未知语义、Winner及行动隔离边界保持。

以下记录 v16 引入并由当前版本保留的需求范围规则：citation v11、三模板 what-why-how-v11 /
evidence-first-v10 / comparison-matrix-v9。迁移触发/概念性过渡不再自动追加完整迁移与回退
的决策关键义务；仅原 query、冻结约束、显式 scene 要求或原始子问题中的明确步骤/方案请求
经有界措辞识别后追加。识别不是通用语义分类，原始 C/Q 始终保留；分析器文本不触发额外
迁移义务，但原有 analysis-constraint A 自身仍可成为关键项，此处未改变其权威。
投递、幂等与恢复义务继续适用。迁移主题的行动隔离限制单独执行，即使没有合成 A 行也不能
把来源依据当作生产操作许可；引用检查、未知状态与部署未验证边界保持。旧 v15 身份仍可
读取，但拒绝按新行为同 run 恢复。共享合成节点的兼容/direct-graph 路径适用同一范围规则。

以下记录 v15 引入并由 v16 保留的结构纠正行为：citation v11、三模板 what-why-how-v11 /
evidence-first-v10 / comparison-matrix-v9。合成前继续标出可绑定来源；合成后复用来源事实与
模型分析绑定器，结构违规时最多纠正一次。合法空输出、普通弃权、词法 unknown 或内容不满意
不触发纠正。原始要求编号规则由绑定与反馈共用，不把分析器派生问题作为原问题。

纠正沿用同一原始输入与冻结参数，反馈仅含固定类别、计数和合法编号，不带模型原始正文。
纠正回答须满足完整响应 shape，并重新通过绑定、原约束和引用校验；第二次违规/普通服务
错误时保留第一份安全过滤结果，不拼接或继续循环。来源事实仍最多四项，分析最多八项；
模型推断仍需全部关联来源通过本轮核验，且只标为 human_review_required，不升级决定或操作权限。

每次节点执行最多两次逻辑生成，现有 helper 每次最多三次传输尝试，合计最多六次物理请求；
恢复或重跑节点仍受 run 总预算与活动时长限制，此六次不是跨恢复的 run 上限。所有实际
尝试经既有预算、Trace 和 usage 路径，预算/租约/取消错误直接传播。纠正计数与本地 JSON
解析 repair_attempts 分开，节点诊断只存固定类别和计数。纠正反馈模板及一次上限协议进入
v15 的 prompt 资产哈希；旧 v14 仍可读取，但不能在新行为下同 run 恢复。无新迁移或顶层状态。
修复位于共享合成节点，兼容接口与显式 direct-graph 调用同样可能纠正一次；没有 RunContext
的执行仍沿用其既有观测/预算边界，不宣称具有 durable 强制预算保证，也不增加兼容接口消费者。

以下为此前来源绑定实现的历史记录：synthesis v12、citation v9、三模板 what-why-how-v10 /
evidence-first-v9 / comparison-matrix-v8。推荐内新增至多四条 source_facts 和四条
conditional_choices：模型只选择来源编号、原始候选名、原始 C 需求 ID 和固定关系枚举；
不接受模型编造的片段、需求、核验状态或操作步骤。运行时绑定本次未争议的唯一来源，完整
保留至多1200字且符合逐句检查上限的保存片段，过长或带引用标记的片段不截断使用。
这些可用片段也完整进入合成输入，使模型能看到尾部前提；其余片段沿用旧提示长度限制。

引用节点每次重建绑定；标题须能往返解析为唯一原标题，逐句检查必须完整覆盖该片段，且
标题和规范 URL 必须与绑定相同。任一检查未知/不支持/不可达、缺失或总检查溢出时，相关
选择推断不展示为可用依据。核验通过仅说明来源文字有词法支持；consider/prefer/
insufficient_alone 始终是模型对用户需求的条件推断，不证明适用性、满足要求或产品必然不适合。
报告保留原文前提并明确推断性质；未完成部署演练不再被固定文案描述为用户要求。

这些字段在普通弃权时保留，但不提升 Winner、需求状态、HITL或行动权限；预算/HITL受限
报告移除这两项。部署状态仍为未验证，操作型计划仍限隔离验证。嵌套字段沿现有结果快照
持久化，无新迁移或顶层状态。旧 citation v1–v8、prompt及模板身份仍可读取，但拒绝同run
恢复；当前策略不回写历史结果。真实模型是否选对关系及阶段性方案仍需有限内容复核。

S1 约束感知结论（2026-09-21）在 final_recommendation 内使用
constraint-aware-v1：逐项 requirement_assessments、条件 decision_branches 和 action_plan
记录验证、变更触发与回退。ResearchState 新增可选 constraints，保留需求分析器输出；
冻结请求的 task.constraints 与分析约束分开传给合成，不允许分析结果覆盖请求。
状态/schema 和生命周期表仍为原版本；新 synthesis prompt v4 与三个模板
what-why-how-v4 / evidence-first-v2 / comparison-matrix-v2 冻结原 S1 身份；
2026-09-22 不确定解释修复将模板升级为 what-why-how-v5 / evidence-first-v3 /
comparison-matrix-v3，prompt v4、状态 schema v3 与引用策略 v1 不变。
2026-09-23 行动安全修复使用 synthesis prompt v5 和 what-why-how-v6 / evidence-first-v4 /
comparison-matrix-v4；manifest schema v1、状态 schema v3、HITL策略不变。2026-09-25 引用策略
升级为 deterministic-citation-v2：获胜项仍通过时，任一未验证的模型行动字段会使整份行动计划
替换为固定的隔离验证步骤，而不是撤回获胜项或发布未核验操作。历史 manifest/结果可读，旧
prompt/template 或 citation-policy v1 的同 run 恢复按兼容检查拒绝。

2026-09-26 条件决策修复将 synthesis prompt 升级为 v6：当 scene context 明确说明会改变选择的
关键输入缺失，且冻结请求约束明确要求条件性结论时，确定性后处理撤回具体 Winner 与序数排名、
保留条件分支并按既有规则限制行动计划；两项条件必须同时成立，普通未知措辞不触发。用户通过
HITL提供的私有补充上下文显式进入合成提示，但仍是不可信用户条件，不能替代产品事实的引用证据，
也不得进入公共事件或结果投影。prompt v5 的历史run可读，但不能在v6运行时同run恢复；workflow、
state schema、HITL策略与报告模板版本不变。

同日P04行动完整性修复将 synthesis prompt 升级为v7、evidence-first模板升级为v5。对同时涉及
队列/恢复与阶段性/过渡要求的请求，确定性要求集增加可观测推进/中止和回退/恢复后验证；普通
rollout措辞本身不会触发。合成必须区分broker消息持久化与result backend结果状态，明确late
acknowledgement可能重投，不能单独证明不丢失或exactly-once，并要求幂等和重复执行边界。若行动
计划已被限制为validation_only，evidence-first末尾只允许隔离验证，不再给通用快速原型指令。
历史prompt v6与evidence-first v4结果可读，但不能在当前运行时同run恢复；workflow、state schema、
HITL与citation策略不变。

2026-09-27引用策略升级为deterministic-citation-v3。结论合成器在主动收回结论时生成的固定
validation-only计划是确定性安全输出，不是模型事实断言；只有计划模式和全部字段与代码内模板精确
一致时才从引用检查中排除，空计划也允许，伪造模式或任意计划继续逐字段检查并在未核验时整体替换。
status为unknown、没有evidence_ids且不含引用标记的说明只表达证据缺口，不再制造
`citation_missing`；带引用的unknown分析仍照常核验。历史citation-policy v1/v2结果和计数原样可读，
但不得按v3语义同run恢复。

后续同日离线优化使用 synthesis v8、deterministic-citation-v4，以及 what-why-how-v7 /
evidence-first-v6 / comparison-matrix-v5。决定性事实保留来源语言，需求/未知/非事实验证任务使用
查询语言；不验证翻译等价、不降低词法阈值、不保证语义或场景适用性。gist.github.com、
gist.githubusercontent.com、pastebin.com 在合成输入、编号/标题绑定和最终 verifier registry 中
一致排除，保留其他来源原编号与原始检索数据；这不是 URL 安全分类或历史失败重标。
v4 将 unknown 豁免缩到代码内精确无事实模板；非模板 unknown 也逐项检查，失败后替换缺口说明，
仅通过既有有界规则的暂定分析能进入 provisional 字段。后台任务受限计划使用四阶段固定隔离
模板：权威任务/结果对账、服务/worker/broker 故障矩阵、幂等键和模拟副作用、切换/排空/回退
演练；每段包含验证、推进/中止与回退边界。生产写入、真实副作用和越过不可逆点的回退仍不放行。
旧 citation v3、prompt v7 和旧模板仍可读取，但必须新建 run；schema、预算、HITL、安全抓取
及生命周期契约不变。

此前候选使用 synthesis v9、citation v5 及三模板 v8/v7/v6。自动恢复 A 义务只询问文献可
支撑的恢复机制、前提与限制，仍为 decision-critical；用户 C/冻结 Q 和 analysis 中明确要求
实际演练的原文不豁免。final_recommendation.deployment_readiness 由合成、弃权、受限计划及引用
校准统一覆盖为 unverified，三个报告模板固定展示未验收警示，不采用模型的 ready/scope 声明。
该字段嵌套于现有推荐快照，不新增顶层状态、结果 schema 或迁移，也不改 HITL 结构门。
操作型义务强制完整固定隔离计划（包括模型计划为空/畸形时）；缺模型计划不再单独触发选型弃权，
但关键需求 unknown/contradicted、溢出、P08 缺上下文和引用失败仍按原规则降级。部署警示及固定
验证任务不是实测事实，不增加 verified 数量。来源词法支持不能证明真实演练或场景适用性。
旧 citation v4、prompt v8 和旧模板身份可读但拒绝同 run 恢复；不可改写历史结果或引用计数。

查询分析/适配 prompt v2 使用白名单 JSON 请求投影，保留 task 的 query、scene_context、
candidate_techs、constraints、sub_questions 原文；粗场景分类不替换自由文本场景。适配始终独立
读取 task，即使预置子问跳过分析或 retry/HITL 换了当前目标，也保留冻结请求上下文。任意 task
扩展和私有状态不进入投影，现有 HITL 补充仍仅按原路径进入当前目标；JSON 是结构分栏，不保证
模型免疫提示注入。不裁切已接收原文、不新增调用或适配目标，不改现有响应展开/fallback与检索
端口限制；模型输出 index/数量仍未逐项校验，不能声称检索数量或语义覆盖有新硬保证。旧两种
prompt v1 身份可读但不可同 run 恢复；现有 state/result schema、预算、HITL、安全契约不变。

关键约束缺项、未知、冲突或缺少可用引用绑定时，结论收回具体 Winner/序数排名，
保留条件分支、待验证计划与明确未知。绑定到有内容的来源只证明结构完整，不是语义验证。
合成 v11 从原始 scene_context 词法抽取明确的候选能力/运行要求，追加为 C 行，保留原冻结 C
编号与优先顺序；并列能力分别评估。明确的数据丢失风险是硬要求，复杂度/基础设施的场景偏好
可见但不单独否决 Winner；描述性流量/团队事实不升级为来源证明义务。缺失的硬场景行按 unknown
收回具体选择；模型无法通过把该行标成非关键来绕过。显式属于本次回答/报告的交付指令不参与
产品选型门禁。该提取是有界词法契约，不证明需求已完整解析；来源编号和词法 verified 仍不能
证明来源条件与当前场景匹配。旧合成 v1–v10 身份可读但不可按本实现同 run 恢复。
引用节点优先检查新判断字段，继续使用原总检查/安全抓取上限；关键判断、胜者依据及
决定性总结/排名/取舍/置信理由未通过检查，或检查被截断时，收回确定结论。
关键判断降为 unknown，不能解释成事实被证伪；一个通过的胜者标题不能掩盖其余无依据结论。
citation_verification 保留校准前声明的检查证据；校准只在本次 graph 结果内执行，不改历史结果。
词法 verified 同样不证明语义正确或来源适用，真实效果仍需局部配对评审。
此前 citation v7 对同语言的决定性断言增加有界的句内限定核对：整页分散词不能拼成一次
verified；已匹配来源句中的 if/when 条件分句和强制性语气被省略、换位或强化时标为
`unknown/qualifier_unverified`，不把它当成反证。完整保留的条件句仍只能得到词法支持，
不能证明用户工作负载满足条件。旧 v1–v6 检查和 manifest 可读，但不能同 run 恢复。

此前 citation v8：同一需求解释内有引用但跨语言/限定条件不确定的事实与无引用
推断混写时，整项继续降为 unknown、移除模型原句与 evidence_ids，关键项仍撤回 Winner；
不得把原句的安全部分自动提取为已验证结论。只可从本次证据链、引用注册表及相同规范 URL
重新绑定上述不确定检查的保存来源片段；无引用部分不能决定片段内容。保留每处最多两段、
全报告最多四段及先分配条件分支的上限；关键混合需求行先于普通待核查行各取至多一段，
不改变报告行顺序。直接来源文字仍不证明语义、工作负载适用或部署验收，也不提升引用通过数、
选型或行动权限。v1–v7 身份可读，但不能在 v8 runtime 同 run 恢复。

普通报告不把“尚未核验”解释成“没有可读分析”：原已判断需求的 explanation 在完整检查后，
若只含 verified/unknown/unreachable，且原因仅为词法支持、网络/HTTP/跨语言/限定条件不确定、
正文不足或公开不可达，可由引用节点生成显示专用 provisional_explanation；跨语言 unknown
及限定条件 unknown 例外：不能把可能遗漏来源限定条件的模型断言当作分析继续展示，条件分支改为固定的适用性待核查
提示。对这两类检查，引用节点可从同一次运行已保存、经引用来源注册表重新绑定且 URL 一致的
来源 snippet 回填完整空白规范化片段；gist/paste、导航占位和超过 1200 字的片段不展示，不裁切，
每处最多两段、全报告最多四次展示，先分配条件分支。片段只是供人工核对的保存内容，不是新外呼、
原页完整性、当前场景适用性或语义验证；不得因此提升需求状态、Winner、部署验收或引用通过数。
其他允许原因仍可生成 provisional_explanation。整段须不超过
MAX_CLAIM_TEXT（500 字符，含标记），任何检查溢出、缺引用、unsupported 或 source_limit
均不能保留。主 explanation 改为未知提示、status 为 unknown、evidence_ids 清空，具体胜者
和排名仍撤回。三格式在分析旁明确“待独立核验，不代表需求已满足”；自审覆盖计数包含该字段。
模型输入归一化丢弃此扩展字段；仅当前校验可生成，不能作为已满足依据。预算/HITL 受限
路径再次归一化并删除它，历史结果不回填；可用条件分支时摘要指向条件选择而非无结论。

保守降级同时撤回模型原 action_plan 的生产操作正文，不能只把双写/切流/旧快照恢复
改标为“待验证”。运行时设置 action_plan_mode=validation_only：原计划结构完整时，替换为
固定的只读观测、可丢弃隔离副本验证任务，要求定义观测窗口/阈值、权威写入、一致性边界、
新增已确认写入保全/回放及禁止回退点；未知前提不放行生产变更。空、无效或溢出的原计划仍为空。
条件分支、需求判断及允许的待核验分析继续显示，三格式明确“仅隔离验证；禁止生产变更”。
模型归一化将 mode 重置为 proposed，模型不能伪造验证状态。未触发降级的普通提案保留原计划，
仍只是提案：此修复不是完整语义安全证明，也不是生产实施许可。
公共 snapshot 的 citation_verification.checks 仍可保存校准前原声明与失败状态供审计，
包括已撤回的操作文本；它不会重新成为 final_recommendation.action_plan 或报告步骤。
因此本契约是撤回操作建议，不是抹除整个公共快照的审计原文。

单一 evidence-insufficient gate 继续同时要求结构证据不足与方向实质不确定；
新契约的 context_dependent 不再依赖存在两条排名才识别不确定性。
用户 limited_report 与预算触顶报告使用同一纯后处理清除具体胜者、排名及旧确定性总结，
所有逐项判断改为待独立验证的 unknown 并清除其引用绑定，覆盖预算可能在引用节点前触顶的路径；
保留可用条件分支，原操作计划按上述规则替换为隔离验证；三种格式展示一致，公开事件、决策动作、
TTL、CAS、fencing、预算准入及四种引用状态不变。

- `task_id` 标识一次用户研究意图；`run_id` 标识绑定一个 `RunManifest` 的执行尝试。
- `tasks.latest_run_id` 指向当前尝试。当前 task 与 latest run 的状态必须一致。
- task/run 的 `version` 是乐观并发控制字段。读取后再写的生命周期操作必须做 CAS；
  CAS 失败返回冲突，不得覆盖赢家。
- `RunManifest` 冻结模型、LLM 参数、Prompt hash、workflow/state schema、retriever 和报告
  模板版本。当前新运行使用 `research-v4`/state schema v3，并冻结
  `deterministic-citation-v15` 与 `evidence-insufficient-v1` 策略；历史 workflow v1–v3 及
  citation-policy v1–v14 manifest 仍可读取和校验身份，但不能在当前 runtime 上续同一 run，须创建
  新 run。same-run resume 必须校验 manifest ID 及当前运行时兼容性；不兼容时拒绝恢复。
- `completed`、`completed_with_warnings` 和 `cancelled` 是不可重开的 task 结果；
  `failed`、`timed_out` 可通过新 run 重试；`interrupted` 是可恢复状态，不是不可重开终态。

2026-09-16 模型适配：新 manifest 只冻结 DeepSeek Flash，含原 Qwen 综合与再仲裁调用；默认
thinking 显式关闭，综合开关使用 DeepSeek 原生格式并按 run 冻结。manifest schema 仍为 v1，
workflow/state 仍为 research-v3/v3。历史双 provider manifest 身份和结果保持可读，但不能
改写旧 manifest 后续跑。interrupted 的恢复入口先校验完整 manifest：配置不兼容时创建新 run，
身份损坏则拒绝且不改变状态；failed/timed_out 仍按既有规则新建 run。其他旧任务可新建任务，
HITL 绑定的旧 run 同样不能换模型恢复：未过期 pending decision 的非 cancel 新提交在落库前
校验兼容性，不兼容则返回 409 并保留 pending，用户仍可取消。相同已提交 body 的幂等重试、
到期和 CAS 冲突保持原语义。生命周期事务与 checkpoint fencing 保持原契约。

主要 durable API：

基线准备检查（2026-09-16）将仓库只读负载探针迁移到 durable GET；旧服务端接口和生命周期
契约未删除。历史直连评估入口已隔离，不能用其结果代表 durable budget/cache/HITL 行为。

| API | 契约 |
|---|---|
| `POST /api/v1/tasks` | 原子创建 queued task/run，返回 `202` |
| `GET /api/v1/tasks/{task_id}` | 返回公开 task/latest-run 投影，不返回执行所有权或 checkpoint 字段 |
| `GET /api/v1/tasks` | 按 `(created_at, task_id)` 做稳定 cursor 分页 |
| `POST /api/v1/tasks/{task_id}/cancel` | 幂等；queued 直接 cancelled，running 先进入 cancelling |
| `POST /api/v1/tasks/{task_id}/resume` | 必须携带当前 task version 的 `If-Match`；兼容 checkpoint 可续同 run，否则按允许状态创建新 run |
| `GET /api/v1/tasks/{task_id}/events` | 从产品库 replay 公开事件，支持 `Last-Event-ID` |
| `GET /api/v1/tasks/{task_id}/snapshot` | 返回 latest successful run 的 immutable public result；运行中/失败终态使用不同结构化 `409` |
| `GET /api/v1/tasks/{task_id}/observability` | 返回 latest run 的 allowlisted Trace/usage 摘要；无 latest run、无 Trace 或历史策略缺失时以 `available`/`unavailable` 明确表达 |
| `GET /api/v1/tasks/{task_id}/decision` | 返回最新 HITL 决策的公开投影；不包含补充文本、checkpoint 或 fencing identity |
| `POST /api/v1/tasks/{task_id}/decisions/{decision_id}` | 携带当前 task version 的 `If-Match` 原子提交一个允许动作；相同 resolution 重放幂等 |
| `GET /api/v1/tasks/{task_id}/report` | 返回持久化报告，或从同一 public result 确定性渲染指定格式 |
| `GET /api/v1/tasks/{task_id}/annotated` | 返回带 TOC 和引用映射的阅读投影 |
| `GET /api/v1/tasks/{task_id}/export` | 从 durable result 导出 Markdown/PDF，不读取旧 snapshot 文件 |

## 3. 事务、lease 与 checkpoint

- 任务状态、latest run 状态和相应公开事件必须由 repository 在同一 `BEGIN IMMEDIATE`
  事务中提交。API、coordinator 和节点不得绕过 repository 直接改表。
- 成功 run 结束时，allowlisted `run_results`、task/run 成功终态和 `run.completed` 事件必须
  在同一事务提交。结果写入失败、过期 lease、旧 epoch、取消或 deadline 获胜时不得留下
  成功 artifact 或完成事件。产品结果不复制 checkpoint payload、运行所有权或原始异常。
- 同一 run 的执行权由 `(lease_owner, execution_epoch, lease_expires_at)` 决定。每次重新
  获取执行权都产生更高 epoch；旧 owner/epoch 的 heartbeat、checkpoint 引用或收尾写入
  必须被 fencing 拒绝。
- heartbeat 只续 lease，不产生用户事件。CAS/fencing 失败必须零状态变更、零事件、
  零 checkpoint 引用。
- 停机取消可能与 lease 提交竞态。coordinator 必须等待正在进行的 lease acquisition 落定；
  如果 grant 已提交，即使调用方尚未收到返回值，也要按该 owner/epoch 完成 fenced finalization，
  然后再传播取消，不能遗留幽灵 `running`。
- 产品连接的事务入口必须在独占连接锁内完成。SQLite 已排队的 BEGIN 不因 asyncio 取消而
  撤销；即使入口尚未返回，也须排空并回滚后再传播取消，不能仅依赖本地 began 标志或瞬时
  in_transaction。预算、Trace、生命周期、实例租约共用此入口；可观测性读快照仍用 deferred
  BEGIN，不升级写锁。二次取消不能截断回滚；已成功 BEGIN 后 cursor 关闭失败也须回滚。
  共享入口 helper 本身遇到正常嵌套 BEGIN 错误不主动回滚；不支持合法嵌套，各 owner 既有
  异常清理仍生效，不保证上层调用路径保留未知外层事务。迁移保留其已有的独立
  begin-task settle/rollback 机制，迁移SQL、CAS、fencing、预算和事件语义不变。
- 产品库只保存已接受的 checkpoint 引用；LangGraph payload 保存在独立
  `outputs/checkpoints.db`。每个 epoch 使用隔离的物理 namespace，逻辑根 namespace 为空。
- checkpoint payload 与产品引用不可能跨两个 SQLite 文件原子提交。恢复只信任产品库中
  已接受且实际可读取、schema/workflow 兼容的引用；引用缺失或 payload 不可读时保持
  `interrupted` 或安全创建新 run，不得猜测状态。
- coordinator 在节点调用前后及 checkpoint 写入前检查执行权。已经发出的第三方请求不能
  被强制撤回；取消后不得继续调度后续节点，也不得由旧 epoch 提交结果。
- 已持久化 cancel request 优先于普通完成；deadline 到期优先投影为 `timed_out`；
  stale `cancelling` 在恢复时收敛为 `cancelled`。

### 3.1 Durable HITL 决策暂停与恢复

- 新运行的唯一人工决策门为 `evidence-insufficient`，位于引用验证之后、报告渲染之前；它只在
  证据结构不足且推荐方向实质不确定时触发。`POST /research` 及无 `RunContext` 执行不进入该
  durable 决策路径。
- schema v10 的 `hitl_decisions` 记录决策状态及其产品库接受的 checkpoint 引用、run、state
  schema 和暂停 execution epoch。LangGraph checkpoint payload 仍保存在 checkpoint store。
- 创建决策、task/run 进入 `waiting_for_input`、清除 lease/lease deadline，并追加
  `decision.required` 事件在一个产品库事务中提交。等待期间不持有 worker lease、active runtime
  deadline 或执行槽；pending decision 可跨进程重启保留。
- 允许的 resolution 为 `provide_context`（带 1–4000 字符补充内容）、`limited_report`（仅使用
  暂停前已收集证据并标记为受限）、`cancel`（不恢复图，task/run 进入 cancelled）。补充文本
  只作为 untrusted context 提供给恢复图，不得进入公开事件或 GET decision 响应。
- 每个 decision 在创建后 7 天过期。到期由 recovery 或 resolve 路径原子标记 decision expired，
  并将仍等待的 task/run 收敛为 cancelled；过期 resolution 不得恢复执行。
- resolve 需要当前 task version `If-Match`。decision 的 task/run 状态、已接受 checkpoint、
  state schema 和暂停 epoch 必须一致；同 body 重放返回原结果，不同 body 冲突。非取消动作
  原子地把 run/task 入队并保存 resolution，再由 coordinator 从绑定 checkpoint 恢复；只有已
  解决且匹配 checkpoint 的 resolution 可注入 LangGraph interrupt resume。
- cancellation 不恢复图。公开 `decision.required`、`decision.resolved`、`decision.cancelled`、
  `decision.expired` 事件只包含必要的 decision ID/kind、reason、gaps、allowed actions、expiry、
  action/status；不得暴露 supplement、checkpoint ID/namespace、execution epoch、lease owner、
  manifest 或完整 state。

#### Streamlit 交互与恢复验收（Phase 4-2）

- durable SSE 收到 `waiting_for_input` 或 `decision.required` 后，服务端在事件追平时结束本次
  SSE 响应，客户端呈现最新公开 decision projection；等待用户期间不维持 SSE 连接。决策提交后从最近收到的
  `Last-Event-ID` 续接；若 replay 返回 resync，则先读取公开 task/decision 快照，再恢复事件流。
- 页面展示 reason、evidence gaps、allowed actions 和 expiry，并提供补充信息继续、受限报告、取消。
  每次 resolve 携带当前 task version 的 `If-Match`。提交结果不确定时仅以相同 body 重试；版本或
  resolution 冲突后刷新状态，不自动替用户选择。
- 补充文本只允许暂存在用户输入控件及提交结果不确定时的私有 session 重试体；不得进入公开
  decision 投影、页面事件、日志或错误信息。checkpoint/fencing identity、lease owner、manifest
  和完整研究 state 同样不得进入这些公开表面。页面渲染报告仍须使用服务端提供的安全 HTML。
- 端到端恢复验收使用独立产品 SQLite 与 LangGraph checkpoint SQLite、真实 StateGraph/checkpoint
  saver，验证 pending decision 重启保留、相同提交幂等、不同提交/旧版本冲突、七天过期、取消不
  resume，以及合法 resolution 从绑定 checkpoint 恢复同一 run 且只恢复一次。

## 4. Durable task events 与 SSE

`task_events.event_id` 是数据库级全局单调 cursor；`seq` 只在单个 task 内从 1 单调递增。
两者含义不可互换。常见事件包括：

- `task.queued`、`run.started`、`run.progress`
- `task.cancel_requested`、`task.cancelled`、`run.cancelled`
- `run.resumed`、`run.retry_queued`、`run.auto_resumed`
- `run.completed`、`run.completed_with_warnings`、`run.failed`、`run.timed_out`、`run.interrupted`
- `legacy.imported`
- `decision.required`、`decision.resolved`、`decision.cancelled`、`decision.expired`

事件 envelope 可以包含 `id`、`seq`、公开 `run_id`、`created_at`；payload 只允许稳定的
`status`、`node`、`reason` 等最小公开字段。decision events 可额外包含公开 decision ID/kind、
evidence gaps、allowed actions、expiry 和用户选择的 action，但禁止写入补充文本、lease owner、
epoch、checkpoint ID/namespace、manifest 内容、原始异常、密钥、完整请求、完整研究 state 或
报告正文。

SSE 规则：

1. 无 `Last-Event-ID` 或值为 `0` 时从头 replay。
2. header 必须是非负、未带符号的十进制整数；非法值返回结构化 `422`。
3. cursor 不属于当前 task、已不存在或超前时，服务发送 `resync_required` 和公开 task
   snapshot。客户端必须用 snapshot 覆盖本地投影，再从返回的最新 ID 继续。
4. 当前状态为 completed/failed/timed-out/cancelled/interrupted 且事件已追平时连接关闭。
   `waiting_for_input` 也会结束本次连接，但仍是可恢复的非终态；decision resolve 后客户端从最后
   event ID 新建连接。`interrupted` 后若发生 resume，客户端同样重新连接读取后续事件。
5. SSE 不依赖 Phase 2 trace。当前未实现事件 retention 和空闲 keepalive；代理断线后依靠
   浏览器重连及最后收到的 event ID 恢复。

## 5. Migration 与旧 snapshot

- 产品 schema migration 只向前追加；已经提交的 migration 内容、名称和 checksum 禁止修改。
- runner 在 `BEGIN IMMEDIATE` 下串行执行，验证连续版本、名称和 checksum；失败整体回滚。
- 当前产品 schema 为 v10：v4 引入 `task_events`/`legacy_imports`，v5 在不修改 v4 checksum
  的前提下重建 `legacy_imports`，强制 imported 行绑定非空 task/run，error 行不得绑定实体；
  已绑定的 imported 审计行以 `RESTRICT` 防止删除其 task/run 后形成悬空记录。v6 增加
  immutable `run_results`；v7 增加产品库单实例租约；v8 建立 Phase 2-A 的预算/Trace
  表 `run_budget_policies`、`node_attempts`、`external_calls`、`trace_events` 和
  `budget_ledger`。Phase 2-B 已将节点尝试和 LLM/检索调用写入 Trace 表并提供只读摘要查询；
  Phase 2-C 已接入预算预留、结算、硬限制、受限结果和预算摘要；v9 增加带 TTL 的
  `retrieval_cache` 表；v10 增加唯一 `evidence-insufficient` 决策门的 `hitl_decisions`。这些
  表均属于产品数据库，现有成对备份中的产品库副本会一并包含缓存与决策元数据。
- v6 不臆测或回填旧 completed row 的报告；无法从可信来源重建的 pre-v6 成功记录保留为
  只读历史，并在结果查询时返回 `TASK_RESULT_UNAVAILABLE`。v6 后的新成功收尾和带有效报告的
  legacy success import 都必须同时写入 `run_results`。
- 新 migration 必须覆盖：空库安装、上一版本升级、保留已有数据、重复执行、并发 runner、
  失败回滚、未来版本和历史漂移拒绝。
- 旧 snapshot importer 在 readiness 完成后作为受管后台任务运行，只扫描 `outputs` 的直接
  合法 task 子目录并拒绝 symlink/junction 越界；成功文件优先。原文件永不改写，`_error`、
  非 allowlist 字段和私有运行 state 不进入产品库；有效公开报告及渲染所需公开字段会作为
  immutable `run_result` 导入。
- 导入以相对路径和 SHA-256 幂等；内容变化或 task/run 冲突只记录安全错误，不覆盖现有数据。
  默认最多检查 1000 个候选、总 I/O 预算 5 秒、单文件上限 64 MiB；超限文件先按元数据
  拒绝，不为完整哈希继续读取。预算触顶明确记录 `budget_exhausted`，不得伪装为完整扫描。
  I/O 时间预算在目录枚举、读取块和解析步骤之间协作检查；单次底层文件系统调用若永久阻塞，
  Python 线程无法强制中止它。导入已移出 readiness，因此不会阻塞服务就绪；对不可信或远程
  存储应在独立进程或离线维护窗口执行。

## 6. 升级流程

1. 停止 API/coordinator，确认没有仍在写入的进程。
2. 使用 `python scripts/runtime_db.py backup --product-db outputs/deepchoice.db
   --checkpoint-db outputs/checkpoints.db --destination <new-dir> --maintenance-confirmed`
   成对备份。脚本使用 SQLite backup API 并生成双文件哈希 manifest；旧 snapshot 目录另保留
   只读副本。两个 SQLite 文件之间没有跨库原子快照，因此确认维护模式是强制前提。
3. 在备份副本或临时环境启动新版本，确认 migration history 连续、旧 task/run/checkpoint
   可读，并运行对应升级验收测试。若 v4 中存在违反 v5 imported/error 约束的手工数据，
   升级会整体回滚；应在副本中核对并修复来源，不能跳过 v5 或改 checksum。
4. 只启动一个 worker/实例。启动顺序是：worker 配置检查 → 产品 DB migration → 获取实例
   lease → checkpoint DB 初始化 → stale-run recovery → readiness → 后台旧 snapshot 导入。
5. 检查没有幽灵 `running`/`cancelling`、旧 owner 已被 fencing、SSE 能 replay；再恢复流量。

禁止 destructive downgrade、手工删除 `schema_migrations` 或修改 checksum。需要回退时停止
所有新进程，并成对恢复升级前的产品 DB/checkpoint DB 备份及原 snapshot；仅回滚代码而继续
使用新 schema，旧应用会因 future schema 检查而安全拒绝启动。

恢复前先运行 `python scripts/runtime_db.py verify --backup-dir <dir>`；`restore` 默认只做 dry-run，
实际替换必须增加 `--apply --replace --maintenance-confirmed`，已有数据库会保留为带时间戳的
`.pre-restore-*.bak`；对应 `-wal`/`-shm` sidecar 也必须一并隔离或回滚，防止旧 WAL 回放到
新主库。发布演练使用 `exercise --backup-dir <dir> --drill-dir <new-dir>`，只恢复到
新目录并执行完整性检查，不接触产品文件。

## 7. 故障处置

| 现象 | 安全动作 |
|---|---|
| `SCHEMA_MIGRATION_*` | 停止启动循环，保留数据库，核对应用版本和 migration history；不要改 checksum |
| `RUN_MANIFEST_*` | 不续旧 run；保留审计记录，使用当前运行时创建新 run |
| stale `running` | 确认旧实例停止并等待 lease 失效；单实例启动 recovery，验证旧 epoch 被拒绝 |
| `RUNTIME_SINGLE_WORKER_REQUIRED` / `RUNTIME_INSTANCE_CONFLICT` | 修正 worker/副本配置或等待已确认停止的旧实例 lease 失效；不得绕过 guard |
| stale `cancelling` | recovery 应收敛为 cancelled；不得强制改为 completed |
| checkpoint 引用不可读 | 保持 interrupted 或新 run 重试；禁止手工伪造 checkpoint ID |
| `LEGACY_SOURCE_CHANGED` / `LEGACY_ID_CONFLICT` | 保留原文件和现有 task，人工核对来源；不得覆盖导入 |
| legacy import 预算触顶 | readiness 不受影响；查看安全汇总，缩小扫描目录或在维护窗口分批导入 |
| SSE `resync_required` | 用随事件返回的公开 snapshot 重建本地状态，再保存最新 event ID |

## 8. 当前运行边界

- SQLite/coordinator 通过产品库 lease 和启动配置检查强制单实例、单 worker；不能把它当作
  分布式队列或横向扩缩容机制。
- 当前 API 面向单用户、可信主机/可信网络，尚无认证、租户隔离和任务 ownership。不得把
  `0.0.0.0:8000` 直接暴露公网；远程部署必须由认证反向代理限制访问，多用户化前必须补齐
  API token/会话认证与 tenant ownership。
- 产品 DB 与 checkpoint DB 必须作为一组备份和恢复。
- 旧 `/research` 创建/SSE 仅用于一版兼容，任何新消费者必须使用 durable API。
- SSE keepalive 和事件 retention 延后到真实反向代理或生产部署接入前完成。
- Phase 2 Trace 与观测失败不得影响 task state 或 durable SSE 的正确性；预算账本属于
  fail-closed 正确性路径，预留失败必须阻止外呼并使 run 进入可解释终态。
- Phase 2-C 后新 durable run/retry 原子冻结 `standard-enforced-v1` 与 `unpriced-v1`；已有
  `standard-observe-v1` run 在同 run resume 时保留原策略。标准硬上限为 60,000 total token、
  96 次 LLM、72 次 retrieval 和 900,000 active milliseconds，80% 触发软提示。
  价格未知保持 unknown，不得按零成本结算。旧 run 不回填，policy 投影在
  `GET /api/v1/tasks/{task_id}/observability` 中明确为 unavailable。该 endpoint 在同一个
  SQLite read transaction 中读取 task 的 latest run、该 run 的状态/epoch/policy 和 Trace，避免
  retry 时混读旧 run。Phase 2-B 写入节点尝试与 LLM/检索调用 Trace，并通过该 API 返回
  latest-run allowlist 摘要；调用包含安全的节点名、run 内节点尝试序号和可选的非负 `retry_no`，
  不公开内部 attempt/call ID、epoch、lease、checkpoint、manifest、原始异常或其他请求/结果摘要。
  跨 epoch 残留或 run 本身已 `interrupted` 的 started 记录投影为 `interrupted`；其他非活动 run
  当前 epoch 的 started 记录投影为 `unknown`，避免呈现为仍运行。无 Trace 返回 unavailable；Token 汇总只累加已知字段并标明是否
  完整，unknown 不当作零。预算摘要按每个 reservation 的最新 append-only 状态聚合 settled、
  unknown、reserved、剩余额度与软/硬限制；`admission_denied` 单独表示“仍有余额但不足以准入
  下一次调用”，不把它伪装成已消费到硬上限。不公开 reservation/call ID、epoch 或内部 summary。
  Streamlit 查询不可用时回退 snapshot panels。Trace 是可选观测，不影响 task state、结果或
  durable SSE；预算预留与结算按当前 lease/epoch fencing，并发不得超发。首次 admission denial
  会在串行事务内锁存该 run，已经越过快速检查但尚未提交的并发申请也必须拒绝。触顶后仅当确定性结构
  证据门满足（三条非争议可用链、两个有效 HTTP(S) host、至少一条 moderate/strong）时生成
  不再外呼的受限报告并以 `completed_with_warnings` 原子持久化，否则以
  `BUDGET_EXCEEDED_INSUFFICIENT_EVIDENCE` 失败。`RunManifest` 保持 schema v1，并冻结每个 LLM
  call 的 `max_output_tokens`；旧 manifest 按历史 identity 可读，但不能兼容恢复。
- Phase 6-A 的受管 URL 外呼只允许 HTTP(S)、80/443 和无 userinfo；DNS 解析、实际 direct-IP
  连接以及每一跳 redirect 都必须重新验证公网地址、hostname、端口和响应上限。无法证明安全的
  proxy/forward 动态 URL 必须拒绝。forward allowlist 只接受完整 hostname 精确匹配或显式
  `*.example.com` 子域匹配。
- 请求 body 上限为 128 KiB，query、候选项、澄清文本、字段和聚合输入另有数量/长度上限。
  日志、错误、Trace 和 LLM diagnostics 统一脱敏；LLM diagnostics 只保留 hash、length、usage
  和 error type。报告继续支持 Markdown，`report_html` 和 PDF 使用服务端同一 sanitizer；
  前端不得把未清洗报告放入 `unsafe_allow_html`。
- Phase 6-A 不包含认证/API key 或 rate limiting，也不声称所有静态 provider 已迁移到安全 fetch；
  这些仍是后续安全收口或独立适配任务。

## O1-R：单 case 可靠性边界（2026-09-16）

O1 六源出站限流补充（2026-09-17）：单进程内跨 run/路由共享 provider FIFO 准入，最多 256
等待者、每次排队 600 秒；重试/搜索探测同门，冷却不截短，取消不泄漏许可。补证工具的整个
调用（含全部排队/重试）时限由 20 调到 630 秒，manifest v1 既有字段冻结新值，旧值保持历史
可读但拒绝同 run 恢复。run 期限、900 秒 active 预算准入与 exhaustion latch 不变；预算不是
已提交调用的自动 900 秒取消器。仍为单 worker，不新增外部队列或生命周期状态。安全 URL
逻辑检查排队后网络总时限仍 15 秒，逐跳安全校验不变；失败显式，Trace/预算仍按逻辑调用计数。
入口/策略与残余风险见 [限流审计](o1-retrieval-throttle-audit.md)，不构成真实并发效果验收。

O1 追加缓存用量观测只扩展 Trace usage/public observability：严格校验模型输入缓存 hit/miss，公开调用完整性、run 已知小计/完整调用数，完整分项才给命中率；不改 lifecycle/SSE、manifest/state schema、预算总 token 或 unpriced-v1。历史 Trace/immutable run_results 不回填；旧 graph usage 行保持可读。详见 [缓存拆账协议](o1-cache-cost-accounting.md)。

- 实例获取在 BEGIN IMMEDIATE 写锁取得后采集 now/expiry，续期在共享连接锁内采集；等待前的时间不得缩短新 TTL 或复活过期租约。默认 30 秒 lease/10 秒 heartbeat、失权 fail-closed 与单 worker 不变。run heartbeat 的锁前时间及 SQLite busy/event-loop 延迟仍是残余风险，不能把此修复描述成完整 live 根因解决。
- RunCoordinator.auto_recovery 默认 True，正常 startup/周期恢复、HITL 及七日过期语义不变。实验专用 app.state.auto_recovery_enabled=False 使 coordinator.start 跳过 recover_runs 且不创建周期扫描；显式新任务及已确认 HITL 恢复仍走原 fencing/预算契约。它不适合长期默认产品部署，不授权直接读取/恢复私有 checkpoint。
- 短 conflict_scan 最大输出冻结为 512，其他 LLM call 仍 4096；请求和预算预留使用同一上限。schema v1 不变，历史 4096 scan manifest identity 可读但拒绝同 run 兼容。每 run 扫描/初次仲裁各四路，额外受全局门约束；预算 denial latch 不变，已派发调用在失败上抛前完成结算，不放宽标准硬预算。
- 评测单次消费者只用 durable API；健康/身份/生命周期漂移停止新准入，不自动恢复或重复 POST。运行中用量缓存保留数字但不得冒充最终完整使用，非终态或最终刷新失败必须标为 incomplete；不修改公共 lifecycle/SSE 投影来迎合评测。
- 仲裁 KB 工具复用默认 ChromaKB.retrieve，使用 tech_kb/BGE 查询而非旧 knowledge_base/query_texts；保持工具外层一次预算和 Trace，失败明确、安全，BudgetError 仍传播，不增加预算/租约例外或修改原知识库。

## O1-B：批次前观测与最小可靠性补修（2026-09-17）

用户批准的补修收口上节取时残余边界：默认 run acquire/heartbeat 传 clock，在共享锁与
BEGIN IMMEDIATE writer 等待后取时；explicit now 保留旧调用/测试语义。实例续期同样显式
写事务后取时，失败回滚/撤权；取消中 release 不依赖本地成功标志，按 owner 清理，不能删
替代实例。实例本地已接受的 UTC/monotonic 有效窗口到期后 health 为 503，durable 写准入拒绝，
不等失租回调才拒绝新请求。heartbeat 回调仍负责停止既有 coordinator；在途外部请求不可撤回，
不能把 health 503 描述为瞬时停止所有 runner。

同步 Chroma 构造、collection query 和默认/补证/冲突扫描模型获取移出事件循环，模型只初始化
一次；线程取消不等于强制终止本地工作，后续产品写仍须原 fencing。单实例、30 秒/10 秒
租约/心跳、恢复/取消/预算/lifecycle/event/checkpoint 语义及 schema 不变。

health 增补进程内安全 runtime_observations 与 run_heartbeat，含成功年龄、剩余有效期、
总续期/调度耗时与计数，不公开 owner/epoch/checkpoint 或原始错误，不是跨重启持久化日志。
observability API 同一 latest-run 读快照增补 allowlisted failure_category、diagnostics 和
run_failure_category；只公开 finish_reason、截断、严格/修复 JSON、实际 parser 次数及浅层
结构状态，拒绝存储摘要中的任意其他字段。Trace 仍 best-effort，token/预算不改；成功传输可
同时存在输出异常，不能单用 failed_calls 判结构可用。历史不回填，缺失保持 unknown。

json_repair 兼容返回/重试不改；新调用观察器为 node-shape-v2，仍读取历史 v1。
本地 diagnostic_profile 分别选择事实选择、问题判断、主审和定向补审的浅层格式，
不写入模型请求、不改变 call tag、manifest、输出上限、预算、解析返回或重试。
主审与定向补审分别验证，缺少后者未要求的主审字段不再误报；空对象仍无效。
格式有效不等于事实正确、引用绑定合格或审查完整。澄清多结构仍为 not_configured。

2026-10-05 增补 nodes[].stage_counts，复用产品库每次成功 node attempt 的 summary，
与 latest-run 状态/Trace 在同一读快照公开。仅投影 source_evaluator、evidence_chain、
conclusion_synthesizer、citation_validator、self_reviewer 的固定计数键，严格整数
0–10000，拒绝 bool、负数、字符串、任意新键与原始摘要；历史或无有效观察返回 null。
计数包含来源过滤、范围提议、选取/绑定事实、问题行接收/筛选及固定拒绝分类、
分析绑定拒绝分类、引用前/重绑/校准后分析数、自审提交/保留/撤下数。
analyses_returned 是该节点返回的行数，analyses_rebound 是引用节点完成重新绑定、
尚未校准时的行数；缺失字段不推成零。每次尝试独立记录，不把跨重试计数直接当分母。
这些计数在 Trace 中保留，不改变 graph quality_signals 覆盖、state schema、HITL、
报告准入或 lifecycle/SSE。Trace 写失败仍只造成观测缺失，不保存模型响应全文，也不
回填旧快照或据现有计数反推历史丢弃环节。
评测逐调用与已知分母输出、旧探测资格、冷启动模式、离线故障与边界详见
[O1-B 记录](o1b-prebatch-observability.md)。不因此批准真实 case 或批次、不证明蓝屏根因。

## O1-PR2B：并发租约队列隔离（2026-09-21）

filesystem 产品数据库在同一 SQLite/WAL 文件上使用三条应用连接：主写连接继续承载
lifecycle、Trace、预算、检索缓存与所有状态变更；专用租约连接只供 runtime instance guard
和 RunCoordinator 的 run heartbeat 使用；专用查询连接承载公开 task/list/decision 快照与
latest-run observability 读事务。三条连接各有独立 asyncio lock，使租约续期和公开读取不会
排在主写连接的高流量协程队列之后。它们仍指向同一个产品库，不改变备份对、schema、事务
事实源、lease owner/epoch、30 秒 TTL、10 秒节拍、单实例或单 worker 约束。恢复、HITL
resolution 与其他 mutation 的预检继续使用主写仓库并由原事务/CAS 复核。`:memory:` 兼容路径
因第二连接会得到不同数据库，继续共用原连接；durable 部署使用 filesystem 数据库。

专用连接仍通过同一 SQLite WAL/writer lock 与有界 busy timeout；真正的长写事务、磁盘停顿、
query 自身过载或 event-loop stall 仍可能使操作失败，不能声称 API 或租约永不失效。失权后的
coordinator 取消、fencing 拒绝与 health 503 不变。离线故障回归在主连接 asyncio lock 阻塞超过一个
完整测试租约窗口时，同时运行实例 guard 与 12 个 run heartbeat，确认专用租约队列持续续期；
另验证主连接 asyncio lock 积压时 task detail 与 observability 仍返回，并保留 writer wait 超时、过期不可复活、
旧 owner 不得清理替代 owner 等既有回归。

2026-09-21 的 O1-PR2B concurrent-r1 一次观察到 12 路 running 后在 multi_retriever 阶段
发生实例与 run heartbeat 失权；内存没有越过实验停止线。该 live 事实支持修复共享应用锁
排队边界，但不能排除主机/磁盘/事件循环的其他风险，也不构成修复后 live 并发验收。
失败实验根保持关闭，生产变更形成新候选后须重新资格与另行授权。

## Run heartbeat 短时写锁竞争维修（2026-09-29）

每个 run heartbeat 节拍最多尝试两次续租，仅第一次仓库操作明确返回
`RepositoryOperationError.error_detail.retryable=true`（SQLite busy/locked）时重试。
第二次仍失败、不可重试仓库错误、租约失效或未知异常，仍取消 runner 并走原有
fenced interrupted 收尾；取消直接传播。实例 guard 的续租策略、30 秒 TTL、10 秒节拍、
SQLite busy timeout 和单实例/单 worker 不变，不对磁盘停顿或未知故障自动恢复。

两次续租均调用同一仓库方法，在取得连接锁和 BEGIN IMMEDIATE 写锁后按当前 clock
检查 owner、epoch、状态与 expiry，并由 UPDATE CAS 再次约束。过期或被替代的 lease
不能复活；重试开始不算续租成功，提交返回后才更新成功统计。重试只限制尝试次数，
不声称独立于 SQLite/应用锁等待的固定总耗时。heartbeat 仍不生成用户生命周期事件。

`/health.run_heartbeat` 增加 `retries`、`recovered_retries` 和 `failure_categories`。
前两者分别统计安排重试的次数及成功的重试；取消可能发生在第二次实际调用之前。
`failures` 保持“最终失败并取消”含义，
`successes` 仅计成功节拍；`failure_categories` 统计每次失败尝试，固定为 `database_busy`、
`database_error`、`lease_lost`、`unexpected_error`，因此恢复的失败也仍可见。
同样的固定类别及尝试序号写入脱敏日志，不保存原异常、堆栈、ID、路径或请求正文；
统计是进程内数据，重启清零，不新增 schema 或 Trace 正确性依赖。

真实双连接 SQLite 离线复现证明旧实现会因一次短时竞争取消任务；修复覆盖释放后续租、
持续竞争、过期、换 epoch、远程取消及重试中取消。该证据不确定历史 P01 中断的具体原因；
原始异常当时未保存。本次无真实研究，不宣称 live 效果、来源可达性或报告验收通过。

## O1-C：社区凭据与节拍契约澄清（2026-09-17）

社区 route probe 和业务检索共用请求局部的可选 `STACKEXCHANGE_API_KEY` 参数构造；
每次构造参数时读取当前环境，复制非敏感 params，不修改静态 ProbeSpec，不在公共健康/审计
中保留 key；已准备或排队中的请求不承诺自动切换到之后轮换的凭据。
无 key 时均省略参数。probe 的 `/search/advanced` 与业务 `/search` 不变；同凭据不等于同方法
配额充足，仍可能受出口 IP/上游限制，HTTP 400 / API 502 throttle_violation 仍必须显式降级。

RequestGate 的 interval 是同门串行提交许可的最小间隔，取时/next_start 在锁内；
concurrency 限制从准入至 slot 退出的许可数（包括调用者延迟），FIFO 约束未取消的排队者。
等待者不持许可，每次重试重新排队；冷却反馈在后来准入时检查，不撤回已提交许可或预算预留。
这不是任意进程调度延迟下客户端进入、HTTP 连接或实际发包时间的最小间隔承诺，也不协调
转发出口的其他调用者。准入后的迟滞可使不同调用时间戳重合，不能据此单独判断准入门失效。
若未来要改变物理调用节拍保证，须另行定义并审查派发契约，不靠放宽测试容差或绕过冷却。

回归使用合成 HTTP/KB 与虚拟时间，保留原秒级间隔，分别测准入、FIFO/许可上限、取消/冷却、
六源结果一致性和准入后延迟反例；不测 live provider 配额、LLM/报告语义或真实并发效果。
该测试时钟在每次模拟 sleep 时累计前进，不是并发墙钟模拟器；合成调度只验证准入不变量，
不测吞吐、最短等待时长或多等待者的真实公平等待期限。这些仍须另做相应评测。
本次不改变节拍算法、run/instance lease、lifecycle/SSE、schema/manifest 或硬预算。

## O1-C：证据准入与报告绑定版本（2026-09-17）

新 manifest 冻结 `source-score-v2` / `what-why-how-v2`：显式候选的标题/摘要词法准入，
缺失题名标记、无依据互证删除，以及显式唯一标题引用才显示 Sources；不是语义相关性或
claim agreement 判定。类别/无候选输入保持不应用准入词门，原检索 envelope/失败可见性不改。
旧 source-score-v1 / what-why-how-v1 manifest 仍能按原内容读取并校验 identity，但
`ensure_run_manifest_compatible` 对跨版本同 run 恢复返回 RUN_MANIFEST_INCOMPATIBLE，须新 run。
不改 workflow/state/schema、生命周期、fencing、缓存/预算/安全获取或四种引用状态；
本地 file:// 不赚取公开 HTTP 核验，proxy/forward 安全性不可证明仍 fail closed。
不得回写历史报告、推断 unknown 为错误、跨句补引或用片段把 unknown 改 verified。
真实复测和批次继续按独立授权处理，详见 [单例验真](o1c-single-case-verification.md)。

## O1-C：缺引用约束与内部安全失败分类（2026-09-17）

当前 synthesis prompt 冻结 v2/hash：要求独立分号子句和推荐首尾逐句引用，缺证不借引文。
PromptSnapshot 保留 v1/v2 可读；旧 v1 身份按旧内容校验，same-run compatibility 拒绝跨版本。
不改变 public citation 四状态/reason/schema 或工作流/状态 schema，不自动跨句补链。
UnsafeUrlError 保留 ValueError 零参/多位置参数构造，并增加固定内部 SafeFetchFailure 分类；
resolver 的路由拒绝、DNS/地址固定、重定向/响应上限与 no fallback 均不变。
verifier 日志只含集中脱敏后的固定分类，无 URL、异常文本/堆栈/页面；非 public result/Trace/event。
预算错误 fail closed，取消传播；分类不能消除 unknown，proxy/forward 安全适配须另行批准。
不回填旧报告，不改 lifecycle/lease/fencing/SSE、硬预算、重试或缓存契约。

## O1-C：既定地址拒绝契约补修（2026-09-18）

安全地址判断不再仅依赖 `is_global`：Python 会将部分组播和保留 IPv6 地址标为 global，
因此显式拒绝 loopback/private/link-local/reserved/multicast，任一 DNS 答案违规就拒绝整组。
字面地址、DNS 及每跳 redirect 共用该规则；正常公网单播 IPv4/IPv6 不变。
这是补齐既定 outbound-url-v1 拒绝契约，不新增通道、代理信任或 fallback；
proxy/forward 仍拒绝，公开引用状态/reason、预算与节拍不变。

## O1-C C2：可信 loopback CONNECT 代理（2026-09-18）

用户批准的离线扩展采用 `outbound-url-v2`，`RunManifest` 仍为 schema v1；新 run 冻结
`safe_fetch_proxy_sha256`（默认 null 表示关闭）。旧 `outbound-url-v1` 缺失该字段时按历史
内容核对 identity，仍可读取，但跨策略 same-run resume 必须拒绝。恢复时配置哈希变化也
拒绝；`RunContext` 内部携带持久化 manifest 的策略/哈希，safe-fetch 在探测/外呼前核对
resolver 的固定配置，漂移 fail closed。内部配置不进入 public result/event/Trace。
该新增代理能力只用于绑定 RunContext 的 durable 执行；legacy `/research` 和其他无 context
执行仍拒绝代理动态 URL，原 direct 路径不因该兼容约束新增拒绝。

`SAFE_FETCH_TRUSTED_LOCAL_PROXY` 默认空且独立于 `LOCAL_PROXY`；只有显式设为严格
loopback 字面 IP 的 HTTP 端点，且与 selected local-proxy 的规范端点完全匹配才允许。
端点必须有显式合法端口 1～65535，无认证、路径（包括尾部 `/`）、query、fragment、
scope ID 或空白。该信任依赖用户认可的代理遵守指定 CONNECT 目标，loopback 本身不是
可信证明，不能证明恶意代理实际连接哪个 IP。不将任意远程/forward 服务纳入这一模型。

动态目标仅 HTTPS:443；本地 SafeUrlPolicy 验证全部 DNS 答案，CONNECT authority 和 Host
均使用选中已验证字面 IP:443，IPv6 带方括号。内层 URL/HTTP Host、TLS SNI 和证书校验
对象仍为原 hostname，SSL 默认校验开启。每跳 redirect 建新隧道并重新验证，HTTPS 降
HTTP 拒绝；HEAD 的 405/501 Range GET fallback 也重新解析/固定。现有 direct/direct-v6
路径与普通 make_client/probe 兼容入口保持原契约，拒绝后没有 direct fallback。

CONNECT 使用 public h11 的有界协议握手：每隧道最多 16 KiB 接收字节及 16 个响应事件；
1xx、分片合计在这些限制内，101、非 2xx、缺失/异常隧道和共包额外数据拒绝。正常完成、
TLS 失败、断连、超时和取消均清理持有 stream，取消继续传播。握手失败抛固定脱敏安全
错误，不把代理 404/407 当作目标 HTTP 状态，引用保持 unknown；不返回原始代理响应。
保留 content-type/有界正文、最多 3 redirects、15 秒总网络限制、官方节拍/429 冷却及引用
逻辑 `http_calls` reserve/settle/unknown。公开引用四状态/reason/schema、预算错误 fail
closed 和 lifecycle/fencing/SSE 不变。self-forward、远程、SOCKS/HTTPS 代理、认证和
经代理 HTTP 引用继续拒绝。本轮离线验收不证明真实代理可用性或模型报告质量。

安全 fetch 每一跳显式请求 `Accept-Encoding: identity`，HEAD 405/501 的有界 Range GET
也保留该请求头，以便正文上限作用于实际消费的表示。服务端或中间层仍返回无法解码的
`Content-Encoding`，或 HTTPX 在打开/消费响应时抛出 `StreamError`，都统一投影为脱敏的
`response_rejected`，不泄露底层异常、正文或网络细节，也不作为可重试 transport 证据；未知编码
仍在读取正文和清理表示头前拒绝。已绑定 `RunContext` 在任何通道上都必须匹配 v4 和冻结的
代理身份，旧上下文在路由探测前关闭。不放宽 content-type、正文大小、redirect、超时、DNS/IP
固定、429 或取消边界。新 run 因此冻结 `outbound-url-v4`；历史 v1–v3 manifest 继续可读，
但不能在 v4 runtime 同 run 恢复，须新建 run，避免同一安全策略身份下改变错误语义。

2026-09-26 的引用正文边界修复将新 run 的安全策略升级为 `outbound-url-v5`。共享安全抓取默认仍在
正文超过上限时 fail closed；只有引用验证显式启用有界前缀，最多消费 64 KiB 已解码正文并立即关闭
响应。前缀内存在足够词法支持时可判 `verified`；前缀内的数字或词法缺失只能判
`unknown/content_insufficient`，不能把未读取的后半页推断为不支持。否定冲突、跨语言不确定、HTTP
状态、预算、DNS/IP固定、重定向、content-type、编码、总耗时、代理身份及脱敏边界不变。历史
v1–v4 manifest 继续可读，但不能在 v5 runtime 同 run 恢复。

2026-09-30 的 `deterministic-citation-v12` 将引用专用响应上限设为 128 KiB，提取文本最多
65,536 字符；共享安全 fetch 默认和 `outbound-url-v5` 的路由/DNS/IP/编码/超时/预算语义不变。
仅对可从本次来源编号、标题、URL、保存片段和逐句标记重新构建的 `source_facts` 使用段落定位：
原片段须在正文中唯一出现、起止完整；取覆盖的完整块及两侧相邻块，最多 6,000 字符。HTML
未闭合尾部、响应/提取边界、过长窗口、缺失或重复位置不授予通过；text/plain 的完整 EOF
单独处理。限定词、否定和支持检查使用同一窗口，并检查已消费页面内其他强匹配句的反证，
包括窗口内部并列句，避免句序决定结果。原句与强匹配数字/否定反证同时存在时为unknown，
保留冲突reason而不把适用范围歧义断言为原句错误。模型断言不使用此特殊路径。原始正文和段落窗口仅在
本次校验内存中，不能进入状态、公开结果、Trace 或日志；仍一次 URL fetch/预留，无新增模型调用。
来源事实仍须完整逐句通过，未通过的依赖分析不保留；词法定位不是语义证明。旧引用策略 v1–v11
manifest 继续可读但须新 run，不能与新策略混用同 run 恢复。

2026-10-04 的 `deterministic-citation-v17` 允许检索器通过私有 `_source_passages`
提出至多三段、总长不超过 1200 字的同 URL 原文。来源评分先检查片段与可见 snippet
逐字规范化一致，证据链保留段界；事实绑定重新生成 `saved_passages`，引用核验须在
同一次已获取的正文中分别唯一定位全部片段，顺序一致后才逐句检查支持与同页反证；
三种报告模板及不确定性来源投影分别显示非连续片段，原题判断提示保留段界与全局句子地址。
畸形或重复提议在来源评分被拒；引用时缺失、倒序、伪造或不完整响应保持 `unknown`；多段仍算一个 URL 和一次
抓取，不增加事实槽位或授予语义适用性。技术标识符内部句号不拆句。新运行同时冻结
`source-score-v7`、合成提示 v26、三模板 v19/v18/v17 和引用 v17；旧 manifest 可读，不兼容同 run 续跑。
该段描述先前的工程检查点；新 durable 运行另有下述有界提议机制，仍未完成真实质量测量。

2026-10-04 的来源范围提议在来源评分前运行：受审 Chroma chunk 须核对冻结哈希，
官方页面只用本次安全抓取且完整的正文块。每条最多 2000 字/40 句，
每句最多 400 字；至多 8 条来源、16,000 原文字符，
发给 DeepSeek Flash 的整份消息不超过 12,000 UTF-8 字节。
原始请求含 scene_context、候选、约束和原子问题；来源只提供去掉查询参数的
HTTP(S) URL 路径、标题与编号句子。先按较短输入优先尝试标题/URL/片段仅命中一个明确候选的来源，
再由官方与 Chroma 轮流尝试余量；消息上限仍可能跳过任一来源，保留原 snippet，
不能把尝试顺序视为两候选证据均已覆盖。模型仅提议 0 起始、末端不含的句子范围；
运行时以保存句子重建，仍受最多三段/1200 字及同页唯一定位约束。
无效提议或普通模型故障保留旧 snippet；预算和运行权威故障向上抛出。
私有 _source_scope_sentences 不进入公开结果，引用时仍需实际安全抓取核验。
新 manifest 冻结 Chroma v7、official v3、source-score-v8、选择提示 v1 和
source_scope_selector DeepSeek Flash 调用（seed 0，输出上限 1024）。
旧身份可读但不可在当前实现同 run 续跑。此处是工程能力，尚无真实报告净收益证据；
最终 24 次仍封存。

## O1-PR1：单例资格消费者（2026-09-18）

仅 `collect-single --stop-at-hitl` 在读取 public pending decision 后停止采集，保留
task/run/manifest、最后 observability 和 `HITL_REQUIRED_NO_AUTO_RESOLUTION`。
该模式不调用决策 POST、cancel 或 resume，正常 HITL 停止也不伪造来源降级；正式采集
默认策略不变。隔离实验 factory 仍禁用自动恢复，产品默认恢复保持原有契约。
`serve --embedding-startup-mode cold-in-research` 使用同一资源限制，跳过启动预热，
第一次实际研究调用才加载模型；旧环境缺少 startup mode 时只按原 prewarmed 解释。
嵌入工具延迟导入 sentence_transformers，契约/采集器导入不提前加载该库；首次调用
仍在既有线程工作中构造真实原生模型，双检锁保持单例，导入/构造失败不缓存失败对象。
冻结启动策略或可信代理 hash 漂移在模型加载和服务启动前拒绝。
资格前置独立于研究预算，dispatch 前限制非 LLM HTTP 20、Tavily POST 1、LLM 4；
JSON/工具探测禁用 SDK 重试，失败停止，路由降级时不调用付费服务。`prepare` 不外呼，
只接受同 Git/依赖/模型端点/路由的成功前置；无 WAL 种子按字节复制至新目录，原件不改。
单例控制器限定一个任务准入，保留实例/运行租约与资源观测；该观察不证明并发或主机稳定。

S1 的 scripts.s1_qualification 复用 PR2B 的 HTTP 遥测、所有权/资源检查及有界服务关闭，
但不继承整批流程的自动取消：资格控制器只允许一次 P01 创建及只读 API，收尾对非终态只读
记录未解决状态，再关闭本次拥有的服务。waiting_for_input 保持待决，普通中断由既有关闭
契约处理；不回答 decision、不调用 cancel/resume，也不重启该根。正常 HITL 以独立资格
停线原因记录，不伪造来源降级，且不能视为资格通过。原 PR2B 整批默认清理策略未改变。

PR1 的内容修正冻结 source-score-v3、what-why-how-v3，冲突扫描/仲裁 prompt v2 与合成 v3；
历史 v1/v2 身份仍可反序列化并校验，跨资产修订同 run 恢复拒绝，必须新候选/新 run。
本地 file 模板不因 Chroma 通道获 official_doc 身份，显式多候选的本地成对比较标题须
覆盖请求候选才进评分；原检索结果/失败不隐藏。来源评分是排序依据，不是正确性证明，
异题、不同条件/偏好的描述不能伪造同题矛盾；不增加裁判、外部工具、重试或硬预算。
缺强链的 What 保留任务候选标签，不提升 moderate 为 strong；合成未决问题在报告可见，
不能用“零维护”、无条件并发/WAL/备份/平滑迁移保证替代条件与证据缺口。

2026-09-23 Q2 准入修复冻结 source-score-v4：只排除完整的已知导航占位格式
`Official documentation site for <single-token term>`（规范化空白/大小写）。它不是页面正文，
不进入来源评分/冲突候选池或新建证据链；合成结构绑定及预算/HITL 使用已有链时也不接纳，
其他来源编号不因此错位。原始 search_results、失败投影和检索 envelope 保留，实际正文、
短包摘要、评分权重、三链/双 hostname/至少 moderate 的结构门槛不变。只有占位帮助满足门槛
的样本可能变为证据不足，不增加 HITL 类型或外呼。未把所有弱片段/标题判成占位，也不声称
通过本规则即具备适用的一手证据。旧 source-score-v1/v2/v3 身份仍可读、校验但不可同 run
恢复；须新 run。无需迁移、改变工作流/状态 schema、提示/模板版本或核心资产索引范围。

Q2 来源分类后续规则冻结 `source-score-v5`：已知平台类型只按规范化 hostname 的完整域名/
点边界子域匹配，路径、query、userinfo 中的名字不提供身份。遗留 `official_doc` 标签仅表示
命中手工静态 locator 的精确 host 和 seed path 段边界，不证明页面所有权、正文真实性或声明/
场景适用性。静态 GitHub URL 仍优先归 github；多租户站点不因一条登记升级其他路径。
不为所有站点自动增删 www；仅有冻结参考支持的显式别名。通用 docs.*、ReadTheDocs 或
`source=official` 不能单独升级；file、未登记/无效URL仍为 tech_blog，不表示它们一定是博客。
静态 TECH_DOCS 内容和 official.py 兼容导出保留；不读取 learned 数据来建立信任，不改变检索/
安全 fetch、权重、证据阈值或来源失效投影。旧v1–v4仍可读取/校验，但不能在v5同run恢复，
新manifest ID隔离缓存；历史报告不重新评分。此分类规则不是新的外呼 allowlist。

2026-09-30 官方 retriever `v2` 在存在 RunContext 且取得真实 HTTP 预算预留时，从现有
TECH_DOCS 匹配中选择至多两个文档根；每根读取根页与至多两个根页实际链接，共最多六次
新增逻辑 GET，串行执行。旧 adapted-only 目录匹配/LLM回退输入保持；原 query、适配查询
及子问只供正文与子页词法相关性使用。learned/LLM 回退 URL 不获得正文遍历权限，未选根
及无 RunContext 的旧路径保留目录角色。跨根按轮转保留结果，最终仍受 max_results 限制。

每页经过既有 safe_fetch：HTTP(S)、DNS/IP 固定、每跳安全检查、HTML/XHTML/plain 类型、
15秒总限、最多三次 redirect、最多128 KiB前缀。子页必须同 scheme、有效端口、精确目录
hostname/已有显式别名与路径段范围；拒绝 query、userinfo、编码路径、非网页资源。最终
响应URL再次核对范围；越界正文使整源失败，不声称 redirect 从未访问其他安全公共域名。
正文提取仅在此 opt-in 路径跳过 nav/form/pre、role=navigation 和 hidden 容器，保留 aside
等限定条件。选取相关实质段及相邻各一块，最多1200字符，不裁去过长相邻条件来迁就上限；
截断边缘、空相关词或无合格正文不产出证据。默认引用解析行为保持。HTML/链接仅在内存短暂
使用，结果仍为 URL/title/snippet/date，不能把相关片段或目录来源当成语义/场景证明。

全部官方 HTTP 分支先预留 http_calls：新增正文最多6，已有回退HEAD最多3、PyPI最多3，
合计最多12次逻辑HTTP；redirect/HEAD的range-GET回退可能产生更多物理请求。已知响应结算1，
异常/取消保守记 unknown_spend；正文预留为空则fail closed，预算拒绝/持久化错误透传。
外层 retrieval_calls 仍按来源计1；没有RunContext的既有HEAD/PyPI保留历史无预算行为。
已发正文请求失败不返回部分成功或静默空成功，使用既有原子失败 envelope；成功网页无相关
正文才可为空。旧 official v1 manifest 可读但不能同run恢复；manifest身份隔离缓存。
本变更不扩展目录、供应商、提示、种子、默认工作流或安全策略，也不变更历史评分。

2026-09-25 后续 Q2 规则冻结 `source-score-v6` 与 Chroma retriever `v2`。Chroma 始终保留原始
用户比较，查询维度最多8、每维候选池30–100；无 adapted query 时子问题只补原问题的来源短缺，
有 adapted query 时原问题占 `ceil(max_results/2)` 个公共结果槽，适配维度至少保留
`floor(max_results/2)` 个槽并按维度轮转。最终仍受请求 `max_results`
限制，并按精确 URL 只保留一项；这不是 URL 规范等价证明，也不把同 URL chunk 算成多源佐证。
受审种子场景门只绑定精确 `product-optimization-knowledge-seed-v1` identity 和15项 target/alias
registry，且只能负向排除跨场景页面；正向命中仍须通过可见标题/摘要的受审 target 完整 token
词法门，该门只接受 registry 明示的 separator/CamelCase 拼写。身份不匹配退回原词法门，精确
身份下未知 target fail closed。内部 `_seed_*` provenance 由 durable 与 deprecated legacy
公共投影递归移除。
旧 Chroma v1/source-score-v1–v5 manifest 仍可读取和验证，但不能在当前运行时同 run 恢复；须新 run。
本规则不证明片段语义支持、来源适用性或正文窗口完整。

2026-09-28 Chroma retriever v3 对精确受审种子中的 official chunk 保留原500字前缀；
仅当第500字后首个换行落在800字内，才延至该行结尾。换行只是排版边界，不能泛称整段或
所有限定均完整。扩展结果带内部 `_seed_excerpt_window` 标记；来源评估须重新确认 Chroma、
种子身份与候选范围，证据链仅传递该标记。合成输入只有在标记与静态官方目录 URL 同时成立
时才可展示至800字，其他来源仍为600字；公共结果递归清除内部标记。不增加来源数、查询维度、
外呼、LLM调用或选型通过数。合成输入身份为 v10；旧 Chroma v1/v2、合成 v9 均可读但不可
同 run 恢复。P04 FastAPI Caveat 的小任务限定可在此界内出现，P01 FTS5 错段不因此修复；
来源出现不证明模型采纳、语义正确或场景适用。

2026-09-30 Chroma v6 在同一精确受审 chunk 边界内修正上述 v3 的换行截取：仅从500字符向后，
在800字符内找到首个有句末标点的行尾或完整 EOF 才扩展；省略号不算结束。找不到时继续保留
原500字符前缀，不回切到前一句以删除未完的限定语。标点与行尾只是文本选择启发式，不能
声称语义或限定完整；来源事实仍由引用v12检查完整周边文本块与强匹配反证。普通/未核验片段、
原正文身份、窗口标记用途、来源权限、查询与外呼数量不变。v1–v5身份继续可读但不能同run恢复，
现有基于manifest的检索缓存隔离旧片段。无新增配置或网络请求，也不变更已冻结测量材料。

2026-09-28 Chroma v4 在多源节点仅对 Chroma 构造至多一条候选名加正向原文场景需求的有界
本地查询；否定、缺失或超长需求不触发，其他来源的查询不变。受审 SQLite FTS5 页面被
全文检索查询命中时，若同次有界候选池内存在精确官方种子身份、URL 与正文锚点匹配的概述段，
可用其500字内真实正文替换同 URL 的导航/深层命令片段；不得拼接不相邻段、改变来源数或
把正文存在解释为场景适用。Chroma v1–v3 身份可读但不可同 run 恢复。额外计算仅为
一个本地 embedding/Chroma 查询维度，不新增网络、模型生成调用或外部检索预算格。

2026-09-28 Chroma v5 默认多源路径从原始 `query`、`scene_context`、`constraints` 提取至多三项
`backup`、`full_text_search`、`task_recovery` 能力标志，原始否定优先；模型子问和适配查询
只作检索提示，不得产生该标志。标志只交给 Chroma 并进入检索缓存键。FTS5 概述及 P01
备份/检索、P04 Celery 任务语义正文，只能从本次候选池中精确核对冻结 `chunks.json`、
`seed-manifest.json` 字节哈希、chunk 内容哈希、target、URL 与种子身份后选用；否则回退
原片段。直接旧 `search()` 或未带标志的 `retrieve()` 保留端口形状，但不会按查询词擅自
提升 FTS5 正文。Chroma 缓存键还绑定实际库文件及可选审计 sidecar 的字节身份；身份
无法取得则旁路缓存，正常可用时保留既有 TTL 与 run 内同键单飞。库在检索期间自然
改写时保留本次结果、不以旧身份写缓存；命中或等待时身份漂移则重新按预算/Trace
检索。指纹工作在线程中执行，不阻塞事件循环。v1–v4 身份仍可读但不能同 run 恢复。

2026-09-18 PR1 冻结候选 `7d622fd` 的 P01（product-baseline-v1/1.0.0、分母一 run）
完成单例测量、完整53原子及独立助手复核，资格为暂定通过；不是并发或人类质量验收。
锁定身份和残余风险见 [单例验真](o1c-single-case-verification.md)。知识冻结指原种子不变及
每次初始字节相同的新副本；Chroma 运行副本物理可变，不能复用或声称整个数据库只读。
后续文档提交不替换候选代码身份；正式批次/HITL 动作和预算仍须按冻结协议另行授权。

## 2026-10-01 分析交付与可用性不确定

citation v14保留v13的四种公开引用状态与网络不确定性边界。连续句末标点及方括号省略号
保持完整；含引用的纯标点段不能把引用转给下一断言，尾部纯标点仍产生未知检查。
来源窗口仍要求原样、唯一、完整定位，省略号不授权跨越网页缺失内容。历史v13及以前
manifest可读但不能同run恢复；历史分析重渲染须比对保存的source_sentences与重算原句，
不一致则隐藏分析，不能仅按旧编号换成另一句。原存储报告不改写。

当前策略保存来源的每句检查、title/canonical URL身份必须
完整匹配，且没有整份溢出；全部结果仅为verified/lexical_support或unknown/network_uncertain
且至少一项为network_uncertain时，可赋予来源`review_availability=network_unconfirmed`。
unknown不会升级成verified。
缺失/重复检查、identity不符、unsupported/unreachable、文本不足、跨语言或限定不明，均不
满足这个窄范围例外。其他引用与来源安全规则保持。

依赖此类来源的分析只获得`network_unconfirmed_pending_review`，渲染前不可展示。
自审从本次citation检查再次核对来源状态与资格、重新绑定原句；keep/revise有效时才成为
`network_unconfirmed_human_review_required`。三模板逐项和逐源显示unknown及保存片段限制，
不把模型解释计作verified。自审失败/缺项撤回对应分析；此路径确定性降至low并保留固定缺口。
Winner、需求状态、行动方案和唯一HITL门不读取此资格作为权威；预算/HITL受限报告仍移除
分析投影，没有新调用或自动补搜。历史产物不重写，旧身份可读但须新run。

2026-10-02 citation v15新增另一条仅限A分析的句子级审阅资格：整份来源若因其他句子的
`qualifier_unverified`保持unknown，可从身份及逐句检查完整匹配的来源中标出已获
`verified/lexical_support`的原句编号。A分析只有自身完整basis仅使用这些编号才可进入
现有一次自审；完整保存来源及未核实限定句仍在自审挑战输入中。R解释不使用这个资格；
来源status不变，缺失、重复、身份错配、溢出、负面和其他unknown原因不适用。
通过自审后报告仍明确标出整份来源unknown，模型推断待人工核对；Winner和行动权限不提升。
旧v14 manifest可读但不能按v15语义同run恢复。本机制当前仅完成离线结构回放，
没有新的真实报告质量结论。

synthesis v19把文本拒绝细分为类型、长度、空值、引用/链接四类，反馈只含固定类别与数量。
完整或部分纠正都需保留原已覆盖R0/C/Q、候选及来源原句地址，不提升需求/赢家权威。
部分纠正另需有效分析数量和问题覆盖严格增加；只选择一份独立绑定的响应，不拼接、不
恢复无效行。选中纠正后在通用归一化结束再限制为validation_only/low，防止后续归一化
覆盖安全标记。该结构择优不证明语义质量，新增真实测量仍按开发评审门槛执行。

## 2026-09-29 人审分析

以下为2026-09-29历史边界；当前网络可用性例外见上一节。用户已授权模型推断供人工审阅。synthesis v13 / citation v10 /模板v11/v10/v9把
`decision_analysis`作为无决定权限的投影：原问题R0及冻结C/Q从请求重建，来源fact_ids仅可
绑定本次完整核验的source_facts。模型提交的状态、需求标签、URL和额外权限字段不可信；
运行时重建绑定并固定人审状态。释义、假设和概念设计没有语义验证状态，不计入verified；
原文核验标识只属于原文。缺失/歧义/溢出/未通过来源核验时不展示对应分析。普通弃权
保留符合条件的分析；预算与HITL受限结果均移除，包括引用节点之前的提前退出。
此投影不升级winner、需求satisfied、HITL或action_plan，不回灌为来源证据；历史结果不回填。
原实际操作门禁继续生效，概念方案供人审，不构成生产执行许可。Markdown/HTML/PDF共享
现有出口，模型文本以字面内容呈现，不能产生自带引用徽标、链接或可执行模板。
后续synthesis v14在生成前用同一来源绑定器标记source_facts可接受编号，保持完整片段、
句数、身份与争议规则；标记不表示verified。现有quality_signals记录source_facts收到/绑定
数量及analysis_binding的provided、received、retained和固定拒绝类别计数，不包含模型正文、
来源文本、请求或私有身份；这些是结构诊断，不是答案覆盖率或质量分数。后续节点会覆盖
quality_signals，最终公开快照不保留合成节点的这些计数；只读诊断须使用产品已接受的检查点引用。
没有新增网络调用、自动重试或决定权限；历史快照无需回填，缺少诊断时不能反推当时生成或拒绝了多少分析。
后续citation v11校准对decision_branches逐项查同路径结果：只保留全部verified的模型条件；
content_insufficient、其他未通过状态或缺失检查都换成固定待核查条件，且不回写历史结果。
此规则只阻止未经核验的条件作为可用分支，不保证报告能回答机制或方案问题。

## quality-selection-v1 评估适配

2026-09-30 新评估入口复用 durable 创建、查询、HITL CAS、观测和报告导出端点。
仅本地评估服务增加 `/evaluation/identity` 供采集器校验冻结绑定哈希，普通产品应用不增加此端点。
生产与采集器提交分别冻结；配置/知识路径在工作流导入前设置，评估两库隔离、关闭自动恢复。
停止的评估根不续跑；默认产品恢复和预算/Trace合同继续生效。采集器另有研究总次数账本，
提交前计入、未知结果不退款，不替代产品每run预算门。报告读取、快照与Markdown导出正文
逐格一致性检查只证明产物完整，不证明语义质量；普通降级、运行失败和安全停止分别记录。
评估准备必须保留Chroma、learned_docs及两个运行时审定文件，冻结并复核索引/字节身份。
一次性维修基线另绑定事故与原控制组；所有相位禁止跨binding续记关闭批次。
操作、固定故障矩阵和留存边界见 [评估工具](../benchmarks/README.md)。


### 显式短候选名的原题路由修复（2026-10-05）

新合成资产v27在标题提示中先匹配完整显式候选名（含短名称、符号和空白），
按ASCII标识符边界排除嵌入词，再保留原长词fallback。来源评分复用同一完整名称
规则且不改变其准入行为。标题仍不证明来源适用；单侧证据的R0保留缺口、引用校准、
分析自审、预算和操作权威边界保持不变。旧v26及更早manifest可读、身份可验证，
但不能在新身份上同run续跑，须新建run。没有workflow/state schema或数据库迁移。


### 事实选择中的来源范围（2026-10-05）

新合成资产v28、引用策略deterministic-citation-v18复用现有事实选择调用。
输入按原chain/source顺序整源放入，最多24源、24000 UTF-8字节；可供选段的保存正文
最多2000字符、40句、单句400字符，拒绝超限来源而不截掉尾部限定。模型可按
`source_ranges: [[start, end], ...]` 选择零基、尾端不含的句子范围。
无ranges时保留历史整段绑定；已有独立passages的来源只可原样选择，不二次切片。

来源身份、编号、disputed、URL/标题唯一性及粘贴站排除仍由原绑定规则决定。
带ranges的事实在绑定与引用阶段确定性重算同一可选源集合；不接纳被输入容量排除的来源。
最多五事实，每事实最多三段、合计1200字符和16句。范围必须有序、不重叠、非布尔整数，
范围表示关注句：运行时从原正文复制，并机械保留前后各一个紧邻完整句，不猜测限定词。
关注范围或紧邻句含省略标记时拒绝该选择，防止跳过同句中的适用前提；扩展上下文重叠时合并。
上述输出限额包含邻句，
超限即拒绝；重复位置、省略标记内选段和未结束句也被拒绝。保存原关注坐标，
每次重绑从原文重新派生同一上下文，不在已扩展文本上再次扩展。
中文句末无需空格，仍保留整块上下文；ASCII单词中间不作为边界。
本地词面检查只约束片段，不赋予verified，也不能证明语义充分性或远处限定已保全。

公开run结果的source_facts可包含有界source_ranges与saved_passages。它们是来源文本坐标，
不含checkpoint/run执行权威。合成输出、引用重绑和自审比较均保留同一坐标；
原search_results与evidence_chains正文不改，恢复后从原chain重新派生。
独立网页抓取仍必须定位各段、保留邻接限定及检查冲突；网络/内容不确定保持unknown。
预算、外呼路由、SSE、HITL及来源事实之外的判断权威均不变化；旧v27/v17身份可读，
但不能同run续跑到新策略。无数据库迁移或新增graph state字段。

历史范围格式观察使用fact-selection-v2；当前默认视图选择使用fact-view-selection-v1，旧profile保持可读。
形状通过不代表坐标、绑定、语义或内容验收通过。
